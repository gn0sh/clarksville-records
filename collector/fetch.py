"""Polite HTTP fetcher.

Rules (spec AC4.2, AC4.3; architecture "Polite fetcher"):
- only hosts on ALLOWED_HOSTS; `cityofclarksville.com` is refused in code, whatever the allowlist says;
- robots.txt read once per host per run, `can_fetch` checked before every request;
- at least HOST_FLOOR seconds between requests to one host (robots.txt fetch included), more if robots
  Crawl-delay says so;
- one plain GET with a clear User-Agent, no header tricks;
- no automatic redirects: each Location goes through get() again (allowlist, denied hosts, robots, per-host
  delay), at most MAX_REDIRECTS hops, or the fetch fails;
- a connection reset (the sandbox relay dropping a slow exchange) is retried once after the host delay, like a
  server error; a second reset fails the fetch;
- a 403 or 429 sent by the site stops that host for the rest of the run, with no retry by another
  host, header or proxy. A refusal by the sandbox's own egress proxy (a rejected CONNECT, which the
  site never sees) is a different case: it is logged as ProxyRefused and does not mark the site as
  having blocked us. A 403 that cannot be attributed to the proxy is treated as the site's.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone

USER_AGENT = ("clarksville-records research collector "
              "(+https://github.com/gn0sh/clarksville-records; polite, 10s/host)")
MIN_DELAY = 10.0                 # seconds between requests on every host (brief: 10 s everywhere)
HOST_FLOORS = {"clarksvilletn.gov": 10.0}
ALLOWED_HOSTS = ("montgomerytn.gov", "mcgtn.org", "d6.mcgtn.org",
                 "montgomeryminutes.bisonline.com", "clarksvilletn.gov")
# cityofclarksville.com blocks automated tools: never collect from it. dev2.montgomerytn.gov (the M0 index host)
# answered 403 from the site on 2026-11-07: stopped for good, never retried by another route.
DENIED_HOSTS = ("cityofclarksville.com", "dev2.montgomerytn.gov")
MAX_BYTES = 50 * 1024 * 1024
PROXY_REFUSALS_BEFORE_SKIP = 3
MAX_REDIRECTS = 5
REDIRECT_CODES = (301, 302, 303, 307, 308)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib follows redirects by default; this makes every 3xx come back as an HTTPError we handle ourselves."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


class HostBlocked(Exception):
    """The site answered 403/429 (or the host is already marked blocked). Do not retry it this run."""


class RobotsDisallowed(Exception):
    pass


class HostRefused(Exception):
    """The host is denied in code or not on the allowlist. No request was made."""


class ProxyRefused(Exception):
    """The sandbox egress proxy refused the connection; the site never saw the request."""


class FetchFailed(Exception):
    """Server error after one retry, a too-large body, or a network error."""


class NotPdf(FetchFailed):
    """The body is not a PDF (e.g. a .docx behind a document link). Nothing was stored."""


def _host_matches(host: str, names) -> bool:
    host = host.lower().split(":")[0]
    return any(host == n or host.endswith("." + n) for n in names)


def proxy_status_failures() -> list[dict]:
    """Recent relay failures from the local agent proxy's status page (empty if there is no proxy)."""
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not proxy:
        return []
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(proxy.rstrip("/") + "/__agentproxy/status", timeout=5) as r:
            return json.loads(r.read()).get("recentRelayFailures", [])
    except Exception:            # status page missing: nothing can be attributed to the proxy
        return []


def _is_tunnel_refusal(err: BaseException) -> bool:
    """http.client raises OSError('Tunnel connection failed: 403 ...') when the proxy rejects CONNECT."""
    e = err.reason if isinstance(err, urllib.error.URLError) and not isinstance(err, urllib.error.HTTPError) else err
    return isinstance(e, OSError) and "Tunnel connection failed" in str(e)


def _is_reset(err: BaseException) -> bool:
    e = err.reason if isinstance(err, urllib.error.URLError) and not isinstance(err, urllib.error.HTTPError) else err
    return isinstance(e, ConnectionResetError)


@dataclass
class PoliteFetcher:
    min_delay: float = MIN_DELAY
    user_agent: str = USER_AGENT
    timeout: float = 120.0
    sleep: object = time.sleep
    clock: object = time.monotonic
    opener: object = None                            # injectable for tests
    proxy_failures: object = proxy_status_failures  # injectable for tests
    wall: object = lambda: datetime.now(timezone.utc)
    allowed_hosts: tuple = ALLOWED_HOSTS
    extra_denied: tuple = ()                         # hosts denied for this run, e.g. finance.yml bonfire_hosts
    max_bytes: int = MAX_BYTES
    _last: dict = field(default_factory=dict)        # host -> clock() of last request
    _robots: dict = field(default_factory=dict)      # host -> RobotFileParser
    _blocked: dict = field(default_factory=dict)     # host -> reason (site said 403/429)
    _proxy_refused: dict = field(default_factory=dict)  # host -> count
    _delay: dict = field(default_factory=dict)       # host -> delay (robots Crawl-delay may raise it)
    log: list = field(default_factory=list)          # [{event, host, url, detail}]

    # ------------------------------------------------------------ policy
    def check_host(self, host: str) -> None:
        if _host_matches(host, DENIED_HOSTS):
            self.log.append({"event": "refused", "host": host, "detail": "denied host"})
            raise HostRefused(f"{host}: denied in code (never collected)")
        if _host_matches(host, self.extra_denied):
            self.log.append({"event": "refused", "host": host, "detail": "denied by config"})
            raise HostRefused(f"{host}: denied by config (never collected)")
        if not _host_matches(host, self.allowed_hosts):
            self.log.append({"event": "refused", "host": host, "detail": "not on allowlist"})
            raise HostRefused(f"{host}: not on the allowlist")

    def delay_for(self, host: str) -> float:
        floor = max([self.min_delay] + [v for k, v in HOST_FLOORS.items() if _host_matches(host, (k,))])
        return max(floor, self._delay.get(host, 0.0))

    def _wait(self, host: str) -> None:
        last = self._last.get(host)
        delay = self.delay_for(host)
        if last is not None:
            gap = self.clock() - last
            if gap < delay:
                self.sleep(delay - gap)
        self._last[host] = self.clock()

    def _open(self, req):
        if self.opener is not None:
            return self.opener(req, self.timeout)
        return _OPENER.open(req, timeout=self.timeout)

    def _proxy_said_403(self, host: str, since: datetime) -> bool:
        for f in self.proxy_failures() or []:
            fh = str(f.get("host", "")).split(":")[0].lower()
            try:
                ts = datetime.fromisoformat(str(f.get("ts", "")).replace("Z", "+00:00"))
            except ValueError:
                continue
            if fh == host.lower() and ts >= since and "403" in str(f.get("detail", "")):
                return True
        return False

    def _note_proxy_refusal(self, host: str, url: str, detail: str):
        self._proxy_refused[host] = self._proxy_refused.get(host, 0) + 1
        self.log.append({"event": "proxy_refused", "host": host, "url": url, "detail": detail})
        return ProxyRefused(f"{host}: sandbox egress proxy refused ({detail}); the site did not see it")

    # ------------------------------------------------------------ requests
    def _raw_get(self, url: str, _retry: bool = True) -> tuple[int, bytes, dict]:
        host = urllib.parse.urlsplit(url).netloc
        self.check_host(host)
        if host in self._blocked:
            raise HostBlocked(f"{host}: {self._blocked[host]}")
        if self._proxy_refused.get(host, 0) >= PROXY_REFUSALS_BEFORE_SKIP:
            raise ProxyRefused(f"{host}: skipped after {PROXY_REFUSALS_BEFORE_SKIP} proxy refusals this run")
        self._wait(host)
        started = self.wall()
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with self._open(req) as r:
                body = r.read(self.max_bytes + 1)
                if len(body) > self.max_bytes:
                    raise FetchFailed(f"{url}: larger than {self.max_bytes} bytes")
                self.log.append({"event": "get", "host": host, "url": url, "detail": str(r.status)})
                return r.status, body, dict(r.headers)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                if e.code == 403 and self._proxy_said_403(host, started):
                    raise self._note_proxy_refusal(host, url, "HTTP 403 recorded by the proxy") from None
                snippet = (e.read() or b"")[:200].decode("utf-8", "replace")
                self._blocked[host] = (f"HTTP {e.code} from the site on {url} server={e.headers.get('Server')!r} "
                                       f"body={snippet!r}")
                self.log.append({"event": "blocked", "host": host, "url": url, "detail": self._blocked[host]})
                raise HostBlocked(self._blocked[host]) from None
            if e.code >= 500 and _retry:
                self.log.append({"event": "retry", "host": host, "url": url, "detail": f"HTTP {e.code}"})
                return self._raw_get(url, _retry=False)
            return e.code, (e.read() or b""), dict(e.headers or {})
        except (urllib.error.URLError, OSError) as e:
            if _is_tunnel_refusal(e):
                raise self._note_proxy_refusal(host, url, str(getattr(e, "reason", e))) from None
            if _is_reset(e) and _retry:
                # the sandbox relay drops a tunnel when the site is slow to answer (proxy status: ws_closed_mid_
                # exchange): the site sent no refusal, so one retry after the host delay, like a server error
                self.log.append({"event": "retry", "host": host, "url": url, "detail": f"connection reset: {e}"})
                return self._raw_get(url, _retry=False)
            self.log.append({"event": "error", "host": host, "url": url, "detail": str(e)})
            raise FetchFailed(f"{url}: {e}") from None

    def robots(self, host: str, scheme: str = "https") -> urllib.robotparser.RobotFileParser:
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            url = f"{scheme}://{host}/robots.txt"
            status, body, headers = self._raw_get(url)
            hops = 0
            while status in REDIRECT_CODES and hops < MAX_REDIRECTS:
                nxt = self._location(url, headers)       # raises HostRefused for a denied or unlisted host
                hops += 1
                url = nxt
                status, body, headers = self._raw_get(url)
            if status == 200:
                rp.parse(body.decode("utf-8", "replace").splitlines())
            elif 400 <= status < 500:
                rp.allow_all = True          # no robots.txt = no rules (RFC 9309)
            else:
                rp.disallow_all = True       # server error: be conservative
            self._robots[host] = rp
            delay = rp.crawl_delay(self.user_agent) or rp.crawl_delay("*")
            if delay:
                self._delay[host] = float(delay)
        return self._robots[host]

    def _location(self, url: str, headers: dict) -> str:
        loc = next((v for k, v in (headers or {}).items() if k.lower() == "location"), None)
        if not loc:
            raise FetchFailed(f"{url}: redirect without a Location header")
        nxt = urllib.parse.urljoin(url, loc)
        host = urllib.parse.urlsplit(nxt).netloc
        self.log.append({"event": "redirect", "host": urllib.parse.urlsplit(url).netloc, "url": url, "detail": nxt})
        self.check_host(host)
        return nxt

    def get(self, url: str, _hops: int = 0) -> tuple[int, bytes, dict]:
        parts = urllib.parse.urlsplit(url)
        self.check_host(parts.netloc)
        rp = self.robots(parts.netloc, parts.scheme)
        if not rp.can_fetch(self.user_agent, url):
            self.log.append({"event": "robots_disallowed", "host": parts.netloc, "url": url, "detail": ""})
            raise RobotsDisallowed(url)
        status, body, headers = self._raw_get(url)
        if status in REDIRECT_CODES:
            if _hops >= MAX_REDIRECTS:
                raise FetchFailed(f"{url}: more than {MAX_REDIRECTS} redirects")
            return self.get(self._location(url, headers), _hops + 1)
        return status, body, headers
