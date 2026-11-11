"""Polite HTTP fetcher.

Rules (spec AC4.2, AC4.3; architecture "Polite fetcher"):
- only hosts on ALLOWED_HOSTS; `cityofclarksville.com` is refused in code, whatever the allowlist says;
- robots.txt read once per exact host per run, `can_fetch` checked before every request;
- at least HOST_FLOOR seconds between requests to one host (robots.txt fetch included), more if robots
  Crawl-delay says so;
- one plain GET with a clear User-Agent, no header tricks. The one other request is get_if_changed: the same GET
  with the validators the server itself sent for our stored copy (If-None-Match from its ETag, If-Modified-Since
  from its Last-Modified), so an unchanged document answers 304 with no body instead of being downloaded again. A
  server that ignores the validators answers 200 with the document, exactly as a plain GET; with no stored
  validator the request is the plain GET. Same policy, robots check and per-host delay, one request either way;
- no automatic redirects: each Location goes through get() again (allowlist, denied hosts, robots, per-host
  delay), at most MAX_REDIRECTS hops, or the fetch fails;
- https on the default port only (fetch/scheme-port-unpinned): every request, the first URL, robots.txt and every
  redirect hop, must be https:// with no port other than 443 and no user:password@; anything else is refused with no
  request (SchemeRefused, a HostRefused), so a redirect cannot downgrade to http:// or move to another port;
- a connection reset (the sandbox relay dropping a slow exchange) is retried once after the host delay, like a
  server error; a second reset fails the fetch. At most RESET_RETRIES_PER_HOST resets are retried per host per
  run: after that a reset fails the fetch at once, so a relay that keeps dropping cannot double the requests;
- a 403 or 429 sent by the site stops that host for the rest of the run, with no retry by another
  host, header or proxy, and it is never asked again in that run, sooner or later. A refusal by the sandbox's own
  egress proxy (a rejected CONNECT, which the site never sees) is a different case: it is logged as ProxyRefused and
  does not mark the site as having blocked us. A 403 that cannot be attributed to the proxy is treated as the site's;
- every request waits the host delay first, whatever the previous answer was (a 304, a 404, a 5xx, a reset): no
  status code ever shortens the gap;
- one site, one state (fetch/host-key-normalization): the delay, a block and the request count are kept per
  site_key(host) (lowercase, no port, no leading "www."), so www.cmcrpc.com and cmcrpc.com share one crawl-delay
  (the largest either robots.txt asks for), one block and one cap. robots.txt itself is read and obeyed per exact
  host (RFC 9309: each host's file applies to that host only);
- limit_hosts(hosts, n): a hard cap of n more requests, shared by those hosts, for the rest of the run, counting
  robots.txt, redirects and retries. The request past it is never made (RequestCapReached); the RPC daily step
  uses it. A redirect from a capped host may only go to a host in the same cap group, where it counts against that
  cap; any other target is refused with no request (fetch/cap-redirect-escape).
"""
from __future__ import annotations

import http.client
import json
import os
import re
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
                 "montgomeryminutes.bisonline.com", "clarksvilletn.gov",
                 "clarksvilletn.api.civicclerk.com",    # the city's CivicClerk API (ADR 0003; Brian 2026-11-09)
                 "cmcrpc.com")    # Regional Planning Commission (www.cmcrpc.com; robots crawl-delay 10; CEO 2026-11-10)
# cityofclarksville.com blocks automated tools: never collect from it. dev2.montgomerytn.gov (the M0 index host)
# answered 403 from the site on 2026-11-07: stopped for good, never retried by another route.
DENIED_HOSTS = ("cityofclarksville.com", "dev2.montgomerytn.gov")
MAX_BYTES = 50 * 1024 * 1024
PROXY_REFUSALS_BEFORE_SKIP = 3
MAX_REDIRECTS = 5
RESET_RETRIES_PER_HOST = 3
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


class SchemeRefused(HostRefused):
    """The URL is not https on the default port (or carries user info). No request was made."""


class ProxyRefused(Exception):
    """The sandbox egress proxy refused the connection; the site never saw the request."""


class RequestCapReached(Exception):
    """The run's request cap for this host's cap group (limit_hosts) is used up. No request was made."""


class FetchFailed(Exception):
    """Server error after one retry, a too-large body, or a network error."""


class NotPdf(FetchFailed):
    """The body is not a PDF (e.g. a .docx behind a document link). Nothing was stored."""


def host_matches(host: str, names) -> bool:
    """True when `host` (a port is ignored) is one of `names` or a subdomain of one. The one host rule: the fetcher's
    allowlist and denied list use it, and so does any adapter that filters links before asking the fetcher."""
    host = host.lower().split(":")[0]
    return any(host == n or host.endswith("." + n) for n in names)


PLAIN_HOST = re.compile(r"[a-z0-9.-]+")


def plain_hostname(host: str) -> str | None:
    """The lowercase host name of a netloc (no port, no user info) when it is a plain DNS name: letters, digits, dots
    and hyphens only. None otherwise (collector-input/host-percent-encoded): urllib decodes %23, %40, %2f in a host
    before it connects, so a raw netloc like evil.com%23.clarksvilletn.gov must never be matched against the
    allowlist."""
    try:
        name = urllib.parse.urlsplit("//" + host).hostname
    except ValueError:
        return None
    return name if name and PLAIN_HOST.fullmatch(name) else None


def split_url(url: str) -> urllib.parse.SplitResult:
    """urlsplit, with a malformed URL (e.g. "https://[x/") as FetchFailed for that one fetch instead of a ValueError
    that would end the whole run (collector-input/redirect-valueerror-escapes)."""
    try:
        return urllib.parse.urlsplit(url)
    except ValueError as e:
        raise FetchFailed(f"{url!r}: malformed URL ({e})") from None


def site_key(host: str) -> str:
    """One key per site for the per-host state: lowercase, no port, no leading 'www.'."""
    h = host.lower().strip().split(":")[0].rstrip(".")
    return h[4:] if h.startswith("www.") else h


def _header_value(v) -> bool:
    """A stored validator we may send back: non-empty printable ASCII (no line break or control character)."""
    return isinstance(v, str) and bool(v.strip()) and len(v) <= 512 and all(32 <= ord(c) < 127 for c in v)


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
    reset_retries: int = RESET_RETRIES_PER_HOST     # per host per run
    # Per-site state is keyed by site_key(host); robots.txt by the exact lowercase host.
    _last: dict = field(default_factory=dict)        # site -> clock() of last request
    _robots: dict = field(default_factory=dict)      # exact host -> RobotFileParser
    _blocked: dict = field(default_factory=dict)     # site -> reason (site said 403/429)
    _proxy_refused: dict = field(default_factory=dict)  # site -> count
    _delay: dict = field(default_factory=dict)       # site -> delay (any of its robots.txt Crawl-delays may raise it)
    _resets: dict = field(default_factory=dict)      # site -> resets retried this run
    _sent: dict = field(default_factory=dict)        # site -> requests sent this run (every one, retries included)
    _caps: list = field(default_factory=list)        # [(frozenset of sites, request limit)] (limit_hosts)
    log: list = field(default_factory=list)          # [{event, host, url, detail}]

    # ------------------------------------------------------------ policy
    def check_host(self, host: str) -> None:
        name = plain_hostname(host)
        if name is None:
            self.log.append({"event": "refused", "host": host, "detail": "not a plain host name"})
            raise HostRefused(f"{host!r}: not a plain host name (letters, digits, dots, hyphens)")
        host = name
        if host_matches(host, DENIED_HOSTS):
            self.log.append({"event": "refused", "host": host, "detail": "denied host"})
            raise HostRefused(f"{host}: denied in code (never collected)")
        if host_matches(host, self.extra_denied):
            self.log.append({"event": "refused", "host": host, "detail": "denied by config"})
            raise HostRefused(f"{host}: denied by config (never collected)")
        if not host_matches(host, self.allowed_hosts):
            self.log.append({"event": "refused", "host": host, "detail": "not on allowlist"})
            raise HostRefused(f"{host}: not on the allowlist")

    def check_url(self, url: str) -> None:
        """fetch/scheme-port-unpinned: https://, port 443 or none, no user info. Raises SchemeRefused otherwise."""
        parts = split_url(url)
        try:
            port = parts.port
        except ValueError:                           # a port that is not a number in range
            port = -1
        if parts.scheme.lower() != "https" or port not in (None, 443) or "@" in parts.netloc:
            self.log.append({"event": "refused", "host": parts.netloc, "url": url,
                             "detail": "not https on the default port"})
            raise SchemeRefused(f"{url}: only https:// on the default port is fetched")

    def sent(self, host: str) -> int:
        """Requests made to host's site this run (robots.txt, redirects and retries included)."""
        return self._sent.get(site_key(host), 0)

    def limit_hosts(self, hosts, n: int) -> None:
        """Allow at most n more requests, all of `hosts` together, for the rest of this run. A cap only ever adds a
        limit: an earlier cap on any of the hosts still holds."""
        group = frozenset(site_key(h) for h in hosts)
        self._caps.append((group, sum(self.sent(h) for h in group) + max(0, int(n))))

    def remaining(self, host: str) -> int | None:
        """Requests host may still get this run under its caps, or None when no cap covers it."""
        h = site_key(host)
        left = [limit - sum(self.sent(x) for x in group) for group, limit in self._caps if h in group]
        return max(0, min(left)) if left else None

    def check_redirect(self, origin: str, target: str) -> None:
        """fetch/cap-redirect-escape: a redirect from a capped host must stay inside every cap group the origin is in,
        so the request it leads to counts against the origin's cap. Raises HostRefused, with no request, otherwise."""
        o, t = site_key(origin), site_key(target)
        for group, _ in self._caps:
            if o in group and t not in group:
                self.log.append({"event": "refused", "host": target, "detail": f"redirect from capped {origin}"})
                raise HostRefused(f"{target}: a redirect from {origin} leaves its capped hosts; not followed")

    def delay_for(self, host: str) -> float:
        floor = max([self.min_delay] + [v for k, v in HOST_FLOORS.items() if host_matches(host, (k,))])
        return max(floor, self._delay.get(site_key(host), 0.0))

    def _wait(self, host: str) -> None:
        key = site_key(host)
        last = self._last.get(key)
        delay = self.delay_for(host)
        if last is not None:
            gap = self.clock() - last
            if gap < delay:
                self.sleep(delay - gap)
        self._last[key] = self.clock()

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
        self._proxy_refused[site_key(host)] = self._proxy_refused.get(site_key(host), 0) + 1
        self.log.append({"event": "proxy_refused", "host": host, "url": url, "detail": detail})
        return ProxyRefused(f"{host}: sandbox egress proxy refused ({detail}); the site did not see it")

    # ------------------------------------------------------------ requests
    def _raw_get(self, url: str, _retry: bool = True, _headers: dict | None = None) -> tuple[int, bytes, dict]:
        host = split_url(url).netloc
        key = site_key(host)
        self.check_host(host)
        self.check_url(url)
        if key in self._blocked:
            raise HostBlocked(f"{host}: {self._blocked[key]}")
        if self._proxy_refused.get(key, 0) >= PROXY_REFUSALS_BEFORE_SKIP:
            raise ProxyRefused(f"{host}: skipped after {PROXY_REFUSALS_BEFORE_SKIP} proxy refusals this run")
        if self.remaining(host) == 0:
            self.log.append({"event": "cap", "host": host, "url": url, "detail": "request cap used up"})
            raise RequestCapReached(f"{host}: the run's request cap is used up; {url} was not requested")
        self._wait(host)
        self._sent[key] = self.sent(host) + 1
        started = self.wall()
        try:
            req = urllib.request.Request(url, headers={**(_headers or {}), "User-Agent": self.user_agent})
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
                self._blocked[key] = (f"HTTP {e.code} from the site on {url} server={e.headers.get('Server')!r} "
                                      f"body={snippet!r}")
                self.log.append({"event": "blocked", "host": host, "url": url, "detail": self._blocked[key]})
                raise HostBlocked(self._blocked[key]) from None
            if e.code >= 500 and _retry:
                self.log.append({"event": "retry", "host": host, "url": url, "detail": f"HTTP {e.code}"})
                return self._raw_get(url, _retry=False, _headers=_headers)
            if e.code == 304:   # a conditional GET's "unchanged": a request like any other, logged as one
                self.log.append({"event": "get", "host": host, "url": url, "detail": "304"})
            return e.code, (e.read() or b""), dict(e.headers or {})
        except (urllib.error.URLError, OSError) as e:
            if _is_tunnel_refusal(e):
                raise self._note_proxy_refusal(host, url, str(getattr(e, "reason", e))) from None
            if _is_reset(e) and _retry and self._resets.get(key, 0) < self.reset_retries:
                # the sandbox relay drops a tunnel when the site is slow to answer (proxy status: ws_closed_mid_
                # exchange): the site sent no refusal, so one retry after the host delay (_wait), like a server error
                self._resets[key] = self._resets.get(key, 0) + 1
                self.log.append({"event": "retry", "host": host, "url": url, "detail": f"connection reset: {e}"})
                return self._raw_get(url, _retry=False, _headers=_headers)
            detail = str(e)
            if _is_reset(e) and _retry:
                detail += f" (not retried: {self.reset_retries} resets already retried on {host} this run)"
            self.log.append({"event": "error", "host": host, "url": url, "detail": detail})
            raise FetchFailed(f"{url}: {detail}") from None
        except (ValueError, http.client.HTTPException) as e:
            # http.client.InvalidURL (control characters, a bad host), IncompleteRead, a bad status line and the like:
            # that one fetch fails, never the run (collector-input/redirect-valueerror-escapes). After the OSError
            # clause, so RemoteDisconnected (also a ConnectionResetError) keeps its one retry.
            detail = f"invalid URL or response: {type(e).__name__}: {e}"
            self.log.append({"event": "error", "host": host, "url": url, "detail": detail})
            raise FetchFailed(f"{url!r}: {detail}") from None

    def robots(self, host: str, scheme: str = "https") -> urllib.robotparser.RobotFileParser:
        # robots.txt is per exact host (RFC 9309); delay, block, cap per site. The cache key is the plain host name:
        # check_url allows only port 443 or none, so h.example, h.example:443 and h.example:0443 are one host
        exact = plain_hostname(host) or host.lower()
        key = site_key(host)
        if exact not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            url = f"{scheme}://{host}/robots.txt"
            status, body, headers = self._raw_get(url)
            hops = 0
            refused = False
            while status in REDIRECT_CODES and hops < MAX_REDIRECTS:
                try:
                    nxt = self._location(url, headers)   # HostRefused: a denied/unlisted host, http://, another port
                except HostRefused as e:
                    # robots.txt cannot be read: disallow everything on this host for the run, cached, so later
                    # fetches neither re-request robots.txt nor fetch the host (scheme-refusal-stops-host)
                    self.log.append({"event": "robots_refused", "host": host, "url": url, "detail": str(e)})
                    refused = True
                    break
                hops += 1
                url = nxt
                status, body, headers = self._raw_get(url)
            if refused:
                rp.disallow_all = True
            elif status == 200:
                rp.parse(body.decode("utf-8", "replace").splitlines())
            elif 400 <= status < 500:
                rp.allow_all = True          # no robots.txt = no rules (RFC 9309)
            else:
                rp.disallow_all = True       # server error: be conservative
            self._robots[exact] = rp
            delay = rp.crawl_delay(self.user_agent) or rp.crawl_delay("*")
            if delay:                        # the site's delay is the largest any of its hosts asks for
                self._delay[key] = max(float(delay), self._delay.get(key, 0.0))
        return self._robots[exact]

    def _location(self, url: str, headers: dict) -> str:
        loc = next((v for k, v in (headers or {}).items() if k.lower() == "location"), None)
        if not loc:
            raise FetchFailed(f"{url}: redirect without a Location header")
        try:
            nxt = urllib.parse.urljoin(url, loc)
        except ValueError as e:     # e.g. Location: https://[x/
            self.log.append({"event": "error", "host": split_url(url).netloc, "url": url,
                             "detail": f"malformed Location {loc!r}"})
            raise FetchFailed(f"{url}: malformed redirect Location {loc!r} ({e})") from None
        host = split_url(nxt).netloc
        self.log.append({"event": "redirect", "host": urllib.parse.urlsplit(url).netloc, "url": url, "detail": nxt})
        self.check_url(nxt)                     # every hop, not only the first URL: no http:// or other port
        self.check_host(host)
        self.check_redirect(urllib.parse.urlsplit(url).netloc, host)
        return nxt

    def get(self, url: str, _hops: int = 0, _headers: dict | None = None) -> tuple[int, bytes, dict]:
        parts = split_url(url)
        self.check_host(parts.netloc)
        self.check_url(url)
        rp = self.robots(parts.netloc, parts.scheme)
        if not rp.can_fetch(self.user_agent, url):
            self.log.append({"event": "robots_disallowed", "host": parts.netloc, "url": url, "detail": ""})
            raise RobotsDisallowed(url)
        status, body, headers = self._raw_get(url, _headers=_headers)
        if status in REDIRECT_CODES:
            if _hops >= MAX_REDIRECTS:
                raise FetchFailed(f"{url}: more than {MAX_REDIRECTS} redirects")
            # the validators belong to the URL they were stored for: a redirect's target gets the plain GET
            return self.get(self._location(url, headers), _hops + 1)
        return status, body, headers

    def get_if_changed(self, url: str, etag: str | None = None,
                       last_modified: str | None = None) -> tuple[int, bytes, dict]:
        """get(), asking the server to send the document only if it changed since our stored copy (a conditional
        GET, RFC 9110 13.1). `etag` and `last_modified` are the ETag and Last-Modified the server sent with that
        copy, passed back unchanged. -> (304, b"", headers) when the server says it is unchanged; otherwise whatever
        get() returns (a server without validator support answers 200 with the document). A validator that is empty
        or not a clean header value is left out; with none left this is get()."""
        headers = {}
        if _header_value(etag):
            headers["If-None-Match"] = etag.strip()
        if _header_value(last_modified):
            headers["If-Modified-Since"] = last_modified.strip()
        return self.get(url, _headers=headers or None)
