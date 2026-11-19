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
  request (SchemeRefused, a HostRefused), so a redirect cannot downgrade to http:// or move to another port. The
  one exception is an upgrade, never a downgrade (fetch/redirect-http-upgrade, upgrade_http): a redirect Location of
  plain http:// with no port and no user info is requested as https:// on the same host and path, and then goes
  through every check above; the http:// URL itself is never requested;
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
- shared hosts (architecture daylight-national 4.4): a host in SHARED_HOSTS serves many governments ("tenants"), each
  under its own path (webapi.legistar.com/v1/<client>/...). tenant_key(url) names the tenant; the client segment is
  lowercased first, so /v1/Salem/ and /v1/salem/ are one tenant (national/tenant-key-normalize). A 403 on a tenant
  path whose body is a JSON object is that one government saying no: only that tenant is stopped for the run
  (TenantBlocked, a HostBlocked). Anything else stops the whole host: a 403 on robots.txt, on a path that is no
  tenant's, with a body that is not a JSON object, or from a second distinct tenant on the same host; and every 429.
  The delay, robots.txt and limit_hosts stay per host; limit_tenant(url, n) adds a per-tenant cap inside the host
  cap. A redirect never changes the tenant key, capped or not (national/tenant-redirect-uncapped): a tenant URL's
  redirect stays in that tenant (counted against its cap) and a host-level URL, robots.txt included, never
  redirects into a tenant. Classifying a 403/429 fails closed (architecture 4.4.2): any error while reading or
  parsing the answer is a host block, recorded before the raise. One parser,
  shared_path (architecture 4.4.1, national/tenant-block-escape), keys every URL sent to a shared host; a path outside
  its strict grammar (any "%", empty or dot segment, leading or trailing dot, backslash, ";", "+", non-ASCII, or a
  /v1/ client that is not 2-40 letters, digits, hyphens) is refused with no request (TenantPathRefused), never
  rewritten. Case is the only variation mapped: /V1/Salem is /v1/salem. robots.txt is never a tenant: any 403 while
  reading it, a redirect hop included, stops the host (national/tenant-robots-host-block); a refused hop or a cap
  while reading it caches disallow_all for that host (a host cap is still raised as RequestCapReached; a tenant cap,
  TenantCapReached, is a refused robots.txt and caps no other tenant). A subdomain of a shared host is refused.
  Callers that treat a tenant apart catch TenantBlocked before HostBlocked.
- Run deadline and slow answers (architecture daylight-national 4.4.4, national-budget/post-deadline-request), both
  off by default (the national run turns them on; with both None every clock(), sleep and read is today's):
  `past_deadline(pause)` is asked in _wait, the one place every request (robots.txt, retries, redirect hops) passes,
  before the wait and after it, and before _last or any sent count changes; True raises DeadlineReached (a
  RequestCapReached), so nothing is sent at or after the deadline. `max_answer_seconds` reads each answer body in
  ANSWER_CHUNK pieces and fails the fetch (FetchFailed) once the answer has taken longer than that (a 403/429 body
  read so cut short is a host block, as any unreadable refusal is).
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

from . import limits
from .safe_json import parse_json

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
# pipeline/fetch-cap-no-margin (limits invariant L16): largest real file 52,041,095 B (city agenda 2021-10-28,
# clarksville-tn manifest, 2026-11-11); 200 MiB is ~4x. The body is held in memory: fine on the runner.
MAX_BYTES = 200 * 1024 * 1024
PROXY_REFUSALS_BEFORE_SKIP = 3
MAX_REDIRECTS = 5
RESET_RETRIES_PER_HOST = 3
REDIRECT_CODES = (301, 302, 303, 307, 308)
# Hosts shared by many governments, each under its own path: site_key(host) -> the pattern whose group 1 is the tenant
# (matched after the client segment is lowercased). Architecture daylight-national 4.4.
SHARED_HOSTS = {"webapi.legistar.com": re.compile(r"^/v1/([a-z0-9-]{2,40})/")}
BLOCK_BODY_BYTES = 64 * 1024     # how much of a 403 body is read to decide tenant or host block
ANSWER_CHUNK = 64 * 1024         # one body read when max_answer_seconds is set (read1: at most one socket read)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib follows redirects by default; this makes every 3xx come back as an HTTPError we handle ourselves."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


class HostBlocked(Exception):
    """The site answered 403/429 (or the host is already marked blocked). Do not retry it this run."""


class TenantBlocked(HostBlocked):
    """One tenant of a shared host answered 403 (or is already marked blocked): that tenant only, for the rest of the
    run. A HostBlocked, so every existing `except HostBlocked` caller still stops; a caller that carries on with the
    host's other tenants must catch TenantBlocked before HostBlocked."""


class RobotsDisallowed(Exception):
    pass


class HostRefused(Exception):
    """The host is denied in code or not on the allowlist. No request was made."""


class SchemeRefused(HostRefused):
    """The URL is not https on the default port (or carries user info). No request was made."""


class TenantPathRefused(SchemeRefused):
    """A shared-host path that could reach a tenant in another spelling (a dot segment, an encoded or unusual client
    segment). Refused with no request, so a tenant block or cap cannot be stepped around."""


class ProxyRefused(Exception):
    """The sandbox egress proxy refused the connection; the site never saw the request."""


class RequestCapReached(Exception):
    """The run's request cap for this host's cap group (limit_hosts) is used up. No request was made."""


class DeadlineReached(RequestCapReached):
    """The run's deadline (`past_deadline`): this request would be sent, or its wait would end, at or after it. No
    request was made. A RequestCapReached, so robots() and every caller treat it as a cap."""


class TenantCapReached(RequestCapReached):
    """The run's request cap for this one tenant (limit_tenant) is used up. No request was made. The host's other
    tenants are not capped by it."""


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
CONTROL_OR_SPACE = re.compile(r"[\x00-\x20\x7f]")


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


def upgrade_http(url: str) -> str:
    """fetch/redirect-http-upgrade: a redirect Location of plain http:// with no port and no user:password@ ->
    the same host, path and query on https:// (the default port). Anything else is returned unchanged, so check_url
    still refuses it. The http:// URL itself is never requested: no request ever leaves https on port 443. Seen
    2026-11-12: mcgtn.org (Cloudflare) answers every path, robots.txt included, with 301 to http://montgomerytn.gov/
    <same path>. Same host and path as the Location, like discover.https_same_host: not another route."""
    try:
        p = urllib.parse.urlsplit(url)
        port = p.port
    except ValueError:                           # malformed, or a port out of range: check_url refuses it
        return url
    if p.scheme.lower() != "http" or port is not None or "@" in p.netloc or not p.hostname:
        return url
    return urllib.parse.urlunsplit(("https",) + tuple(p)[1:])


def site_key(host: str) -> str:
    """One key per site for the per-host state: lowercase, no port, no leading 'www.'."""
    h = host.lower().strip().split(":")[0].rstrip(".")
    return h[4:] if h.startswith("www.") else h


SHARED_SEG = r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*"
SHARED_PATH = re.compile(rf"/(?:{SHARED_SEG}(?:/{SHARED_SEG})*/?)?")   # the only paths sent to a shared host
TENANT_CLIENT = re.compile(r"[A-Za-z0-9-]{2,40}")


def shared_path(url: str) -> tuple[str, str | None]:
    """The one tenant parser (architecture daylight-national 4.4.1, national/tenant-block-escape) -> (site, tenant).
    Run on the raw path exactly as it will be sent. tenant is "<site>/<client lowercased>" (e.g.
    "webapi.legistar.com/salem") for /v1/<client> with or without further segments, else None (host-level: robots.txt,
    /, /v1/, /v2/...). On a shared host a path outside the strict grammar is TenantPathRefused, never rewritten:
    segments of letters, digits, "_" and "-" joined by single inner dots, one optional trailing "/", nothing else (no
    "%", empty segment, dot segment, leading or trailing dot, backslash, ";", "+" or non-ASCII); and a /v1/ client
    must be 2-40 letters, digits or hyphens. Case is the only variation mapped (Legistar treats it as one client). The
    query is not part of the key. A subdomain of a shared host (other than "www.", which site_key folds into it) is
    TenantPathRefused. A host that is not shared, or a malformed URL, is (site, None)."""
    try:
        p = urllib.parse.urlsplit(url)
        host = p.hostname or ""
    except ValueError:
        return "", None
    site = site_key(host)
    pattern = SHARED_HOSTS.get(site)
    if pattern is None:
        under = next((h for h in SHARED_HOSTS if site.endswith("." + h)), None)
        if under is not None:                # national/tenant-block-escape: x.webapi.legistar.com skips the rules
            raise TenantPathRefused(f"{url}: a subdomain of shared host {under}; not fetched")
        return site, None
    path = p.path or "/"
    if not SHARED_PATH.fullmatch(path):
        raise TenantPathRefused(f"{url}: not a canonical path on shared host {site}; not fetched")
    segs = path.split("/")                  # ["", "v1", "<client>", ...]
    if len(segs) < 3 or segs[1].lower() != "v1" or segs[2] == "":
        return site, None                   # /, /robots.txt, /v1, /v1/, /v2/...
    if not TENANT_CLIENT.fullmatch(segs[2]):
        raise TenantPathRefused(f"{url}: /v1/ client segment {segs[2]!r} is not 2-40 letters, digits or hyphens")
    m = pattern.match(f"/v1/{segs[2].lower()}/")
    if m is None:                           # cannot happen for TENANT_CLIENT; refuse rather than guess
        raise TenantPathRefused(f"{url}: client segment does not match the {site} tenant pattern")
    return site, f"{site}/{m.group(1)}"


def tenant_key(url: str) -> str | None:
    """shared_path's tenant: "<site>/<client>" or None (a host that is not shared, a host-level path, a malformed
    URL). Raises TenantPathRefused for a non-canonical shared-host path, so None only ever means "host-level and
    allowed". The "/" keeps a tenant key apart from every site key."""
    return shared_path(url)[1]


def _json_object(body: bytes) -> bool:
    """True when `body` parses as a JSON object (fetch/403-body-parse-escapes: parse_json never raises, so a nested or
    odd body is "not a JSON object", a host block)."""
    try:
        return isinstance(parse_json(body, "utf-8-sig"), dict)
    except Exception:
        return False


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
    past_deadline: object = None                     # (pause seconds) -> True when a request then is too late; None: off
    max_answer_seconds: float | None = None          # seconds one answer's body may take to read; None: off
    # Per-site state is keyed by site_key(host); robots.txt by the exact lowercase host.
    _last: dict = field(default_factory=dict)        # site -> clock() of last request
    _robots: dict = field(default_factory=dict)      # exact host -> RobotFileParser
    _blocked: dict = field(default_factory=dict)     # site -> reason (site said 403/429)
    _proxy_refused: dict = field(default_factory=dict)  # site -> count
    _delay: dict = field(default_factory=dict)       # site -> delay (any of its robots.txt Crawl-delays may raise it)
    _resets: dict = field(default_factory=dict)      # site -> resets retried this run
    _sent: dict = field(default_factory=dict)        # site -> requests sent this run (every one, retries included)
    _caps: list = field(default_factory=list)        # [(frozenset of sites, request limit)] (limit_hosts)
    _tenant_blocked: dict = field(default_factory=dict)  # tenant_key -> reason (that tenant said 403)
    _tenant_sent: dict = field(default_factory=dict)  # tenant_key -> requests sent this run (retries included)
    _tenant_caps: dict = field(default_factory=dict)  # tenant_key -> request limit (limit_tenant; only ever lowered)
    _robots_capped: dict = field(default_factory=dict)  # exact host -> why its robots.txt ran into a request cap
    _robots_unreadable: dict = field(default_factory=dict)  # exact host -> why robots.txt was not read (disallow_all)
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
        """fetch/scheme-port-unpinned: https://, port 443 or none, no user info, no space or control character.
        Raises SchemeRefused otherwise."""
        if CONTROL_OR_SPACE.search(url):
            # urlsplit drops tab/CR/LF but urllib.request.Request sends them: refuse rather than guess the URL
            self.log.append({"event": "refused", "host": "", "url": repr(url), "detail": "control character or space"})
            raise SchemeRefused(f"{url!r}: a space or control character in the URL")
        parts = split_url(url)
        try:
            port = parts.port
        except ValueError:                           # a port that is not a number in range
            port = -1
        if parts.scheme.lower() != "https" or port not in (None, 443) or "@" in parts.netloc:
            self.log.append({"event": "refused", "host": parts.netloc, "url": url,
                             "detail": "not https on the default port"})
            raise SchemeRefused(f"{url}: only https:// on the default port is fetched")
        try:
            shared_path(url)
        except TenantPathRefused as e:
            self.log.append({"event": "refused", "host": parts.netloc, "url": url,
                             "detail": "not a canonical shared-host path"})
            raise TenantPathRefused(str(e)) from None

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

    def limit_tenant(self, url: str, n: int) -> None:
        """Allow at most n more requests to url's tenant for the rest of this run, inside any host cap (both hold). A
        cap only ever adds a limit: an earlier, lower tenant cap still holds. A URL that is no tenant's is a
        ValueError (use limit_hosts for a whole host)."""
        t = tenant_key(url)
        if t is None:
            raise ValueError(f"{url}: not a tenant path of a shared host")
        limit = self._tenant_sent.get(t, 0) + max(0, int(n))
        self._tenant_caps[t] = min(limit, self._tenant_caps.get(t, limit))

    def remaining_tenant(self, url: str) -> int | None:
        """Requests url's tenant may still get under its own cap, or None when it has none (the host cap, see
        remaining(), still applies on top)."""
        t = tenant_key(url)
        if t is None or t not in self._tenant_caps:
            return None
        return max(0, self._tenant_caps[t] - self._tenant_sent.get(t, 0))

    def check_redirect(self, origin: str, target: str) -> None:
        """fetch/cap-redirect-escape: a redirect from a capped host must stay inside every cap group the origin is in,
        so the request it leads to counts against the origin's cap. Raises HostRefused, with no request, otherwise."""
        o, t = site_key(origin), site_key(target)
        for group, _ in self._caps:
            if o in group and t not in group:
                self.log.append({"event": "refused", "host": target, "detail": f"redirect from capped {origin}"})
                raise HostRefused(f"{target}: a redirect from {origin} leaves its capped hosts; not followed")

    def check_tenant_redirect(self, origin_url: str, target_url: str) -> None:
        """A redirect never changes the tenant key (national/tenant-redirect-uncapped, S2a finding 8): from a tenant
        URL it stays in that tenant (so it counts against the tenant's cap, if any), and a host-level URL (robots.txt
        included) never leads into a tenant. Hosts that are not shared have no tenant on either side. Raises
        HostRefused, with no request, otherwise."""
        t, to = tenant_key(origin_url), tenant_key(target_url)
        if t in self._tenant_caps and to != t:
            self.log.append({"event": "refused", "host": split_url(target_url).netloc, "url": target_url,
                             "detail": f"redirect from capped tenant {t}"})
            raise HostRefused(f"{target_url}: a redirect from capped tenant {t} leaves it; not followed")
        if to != t:     # national/tenant-redirect-uncapped (S2a finding 8): capped or not, a redirect keeps its tenant
            self.log.append({"event": "refused", "host": split_url(target_url).netloc, "url": target_url,
                             "detail": f"redirect changes tenant {t} -> {to}"})
            raise HostRefused(f"{target_url}: a redirect from tenant {t} to tenant {to}; not followed")

    def delay_for(self, host: str) -> float:
        floor = max([self.min_delay] + [v for k, v in HOST_FLOORS.items() if host_matches(host, (k,))])
        return max(floor, self._delay.get(site_key(host), 0.0))

    def _wait(self, host: str, url: str = "") -> None:
        """Sleep out the host delay. With `past_deadline` set, a request that would be sent (or a wait that would end)
        at or after the run's deadline raises DeadlineReached before anything sleeps or is counted (4.4.4)."""
        key = site_key(host)
        last = self._last.get(key)
        delay = self.delay_for(host)
        pause = 0.0
        if last is not None:
            gap = self.clock() - last
            if gap < delay:
                pause = delay - gap
        if self.past_deadline is not None and self.past_deadline(pause):
            self._deadline(host, url)
        if pause:
            self.sleep(pause)
        if self.past_deadline is not None and self.past_deadline(0.0):
            self._deadline(host, url)                  # a sleep that overshot the deadline
        self._last[key] = self.clock()

    def _deadline(self, host: str, url: str):
        self.log.append({"event": "deadline", "host": host, "url": url})
        raise DeadlineReached(f"{host}: the run's deadline; {url} was not requested")

    def _read_answer(self, r, limit: int, t0, url: str) -> bytes:
        """The answer body, at most `limit` bytes: one read(limit) when max_answer_seconds is None (today's), else
        ANSWER_CHUNK reads (read1 when the answer has it: at most one blocking socket read each) and FetchFailed once
        clock() - t0 passes max_answer_seconds."""
        if self.max_answer_seconds is None:
            return r.read(limit)
        read = getattr(r, "read1", None) or r.read
        parts, total = [], 0
        while total < limit:
            chunk = read(min(ANSWER_CHUNK, limit - total))
            if not chunk:
                break
            parts.append(chunk)
            total += len(chunk)
            if self.clock() - t0 > self.max_answer_seconds:
                raise FetchFailed(f"{url}: answer slower than {self.max_answer_seconds:g} s")
        return b"".join(parts)

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
    def _raw_get(self, url: str, _retry: bool = True, _headers: dict | None = None,
                 _tenant_ok: bool = True) -> tuple[int, bytes, dict]:
        """One request. `_tenant_ok=False` (robots.txt and its redirect hops): no answer stops only a tenant; a 403
        or a hop into an already blocked tenant stops the host (national/tenant-robots-host-block)."""
        host = split_url(url).netloc
        key = site_key(host)
        self.check_host(host)
        self.check_url(url)
        tenant = tenant_key(url)
        if key in self._blocked:
            raise HostBlocked(f"{host}: {self._blocked[key]}")
        if tenant in self._tenant_blocked:
            if not _tenant_ok:
                self._blocked[key] = f"robots.txt led to blocked tenant {tenant} ({url})"
                self.log.append({"event": "blocked", "host": host, "url": url, "detail": self._blocked[key]})
                raise HostBlocked(self._blocked[key])
            raise TenantBlocked(f"{tenant}: {self._tenant_blocked[tenant]}")
        if self._proxy_refused.get(key, 0) >= PROXY_REFUSALS_BEFORE_SKIP:
            raise ProxyRefused(f"{host}: skipped after {PROXY_REFUSALS_BEFORE_SKIP} proxy refusals this run")
        if self.remaining(host) == 0:
            self.log.append({"event": "cap", "host": host, "url": url, "detail": "request cap used up"})
            raise RequestCapReached(f"{host}: the run's request cap is used up; {url} was not requested")
        if tenant is not None and self.remaining_tenant(url) == 0:
            self.log.append({"event": "cap", "host": host, "url": url, "tenant": tenant,
                             "detail": "tenant request cap used up"})
            raise TenantCapReached(f"{tenant}: the run's tenant request cap is used up; {url} was not requested")
        self._wait(host, url)
        t0 = self.clock() if self.max_answer_seconds is not None else None
        self._sent[key] = self.sent(host) + 1
        if tenant is not None:
            self._tenant_sent[tenant] = self._tenant_sent.get(tenant, 0) + 1
        started = self.wall()
        try:
            req = urllib.request.Request(url, headers={**(_headers or {}), "User-Agent": self.user_agent})
            with self._open(req) as r:
                body = self._read_answer(r, self.max_bytes + 1, t0, url)
                if len(body) > self.max_bytes:
                    limits.trip("fetch.MAX_BYTES", url, f"{len(body)}+ B", f"{self.max_bytes} B")
                    raise FetchFailed(f"{url}: larger than {self.max_bytes} bytes")
                self.log.append({"event": "get", "host": host, "url": url, "detail": str(r.status)})
                return r.status, body, dict(r.headers)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                # architecture 4.4.2 (fetch/403-body-*): the decision never raises; the block is recorded and raised
                # here, outside its guard, so a refusal always leaves a block behind before anything else happens
                kind, reason = self._refusal_decision(e, e.code, host, key, tenant, url, started, _tenant_ok,
                                                      t0=t0)
                if kind == "proxy":
                    raise self._note_proxy_refusal(host, url, reason) from None
                if kind == "tenant":
                    self._tenant_blocked[tenant] = reason
                    self.log.append({"event": "blocked", "host": host, "url": url, "tenant": tenant,
                                     "detail": reason})
                    raise TenantBlocked(f"{tenant}: {reason}") from None
                self._blocked[key] = reason
                self.log.append({"event": "blocked", "host": host, "url": url, "detail": reason})
                raise HostBlocked(reason) from None
            if e.code >= 500 and _retry:
                self.log.append({"event": "retry", "host": host, "url": url, "detail": f"HTTP {e.code}"})
                return self._raw_get(url, _retry=False, _headers=_headers, _tenant_ok=_tenant_ok)
            if e.code == 304:   # a conditional GET's "unchanged": a request like any other, logged as one
                self.log.append({"event": "get", "host": host, "url": url, "detail": "304"})
            # fetch/error-body-unbounded (4.4.2 site 8): the same cap and size trip as a 200 answer; a body that
            # cannot be read fails this one fetch, never with a raw exception
            try:
                body = self._read_answer(e, self.max_bytes + 1, t0, url) or b""
            except FetchFailed:
                self.log.append({"event": "error", "host": host, "url": url, "detail": "answer too slow"})
                raise
            except Exception as x:
                detail = f"HTTP {e.code} answer body unreadable: {type(x).__name__}"
                self.log.append({"event": "error", "host": host, "url": url, "detail": detail})
                raise FetchFailed(f"{url}: {detail}") from None
            if len(body) > self.max_bytes:
                limits.trip("fetch.MAX_BYTES", url, f"{len(body)}+ B", f"{self.max_bytes} B")
                raise FetchFailed(f"{url}: larger than {self.max_bytes} bytes")
            return e.code, body, dict(e.headers or {})
        except (urllib.error.URLError, OSError) as e:
            if _is_tunnel_refusal(e):
                raise self._note_proxy_refusal(host, url, str(getattr(e, "reason", e))) from None
            if _is_reset(e) and _retry and self._resets.get(key, 0) < self.reset_retries:
                # the sandbox relay drops a tunnel when the site is slow to answer (proxy status: ws_closed_mid_
                # exchange): the site sent no refusal, so one retry after the host delay (_wait), like a server error
                self._resets[key] = self._resets.get(key, 0) + 1
                self.log.append({"event": "retry", "host": host, "url": url, "detail": f"connection reset: {e}"})
                return self._raw_get(url, _retry=False, _headers=_headers, _tenant_ok=_tenant_ok)
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

    def _refusal_decision(self, e, code: int, host: str, key: str, tenant: str | None, url: str, started,
                          tenant_ok: bool, t0=None) -> tuple[str, str]:
        """Architecture 4.4.2 (classify fails closed, fetch/403-body-*): a site's 403/429 answer -> ("proxy" | "tenant"
        | "host", reason). Every read, decode, parse and the decision itself run inside one guard: any Exception
        (OSError, ValueError, RecursionError, MemoryError, TypeError, AttributeError, ...) makes the answer a host
        block. Never raises an Exception, so the caller always records a block before it raises."""
        try:
            if code == 403 and self._proxy_said_403(host, started):
                return "proxy", "HTTP 403 recorded by the proxy"
            try:
                body = self._read_answer(e, BLOCK_BODY_BYTES, t0, url) or b""
            except Exception:
                body = b""      # fetch/403-body-read-escapes: an unreadable body is not JSON, so a host block
            if not isinstance(body, (bytes, bytearray)):
                body = b""
            snippet = bytes(body[:200]).decode("utf-8", "replace")
            server = (e.headers or {}).get("Server")
            reason = f"HTTP {code} from the site on {url} server={server!r} body={snippet!r}"
            if tenant_ok and self._tenant_only_block(code, key, tenant, bytes(body)):
                return "tenant", reason
            return "host", reason
        except Exception as x:
            return "host", f"HTTP {code} from the site on {url} (answer not classifiable: {type(x).__name__})"

    def _tenant_only_block(self, code: int, site: str, tenant: str | None, body: bytes) -> bool:
        """True when a site's 403/429 stops only `tenant`: a 403 on a tenant path (robots.txt never is one) with a JSON
        object body, while no other tenant of the same site is already blocked. Anything else stops the host."""
        if code != 403 or tenant is None or not _json_object(body):
            return False
        prefix = site + "/"
        return not any(t.startswith(prefix) and t != tenant for t in self._tenant_blocked)

    def robots(self, host: str, scheme: str = "https") -> urllib.robotparser.RobotFileParser:
        # robots.txt is per exact host (RFC 9309); delay, block, cap per site. The cache key is the plain host name:
        # check_url allows only port 443 or none, so h.example, h.example:443 and h.example:0443 are one host
        exact = plain_hostname(host) or host.lower()
        key = site_key(host)
        if exact not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            url = f"{scheme}://{host}/robots.txt"
            hops = 0
            refused = False
            status, body, headers = 0, b"", {}
            try:
                status, body, headers = self._raw_get(url, _tenant_ok=False)
                while status in REDIRECT_CODES and hops < MAX_REDIRECTS:
                    nxt = self._location(url, headers)   # HostRefused: a denied/unlisted host, http://, another port
                    hops += 1
                    url = nxt
                    status, body, headers = self._raw_get(url, _tenant_ok=False)
            except (HostRefused, RequestCapReached) as e:
                # robots.txt cannot be read: disallow everything on this host for the run, cached, so later fetches
                # neither re-request robots.txt nor fetch the host (scheme-refusal-stops-host; 4.4.1 consumer 6, a
                # hop refused or into a capped tenant). Caps only ever lower, so nothing would become fetchable later.
                self.log.append({"event": "robots_refused", "host": host, "url": url, "detail": str(e)})
                if isinstance(e, RequestCapReached) and not isinstance(e, TenantCapReached):
                    self._robots_capped[exact] = str(e)    # a host cap: later get()s report the cap, not robots
                refused = True
                self._robots_unreadable[exact] = f"refused: {type(e).__name__}"
            delay = None
            if refused:
                rp.disallow_all = True
            elif status == 200:
                try:
                    rp.parse(body.decode("utf-8", "replace").splitlines())
                    delay = rp.crawl_delay(self.user_agent) or rp.crawl_delay("*")
                    delay = float(delay) if delay else None
                except Exception as e:
                    # architecture 4.4.2 site 9: a robots.txt we cannot parse (e.g. a Crawl-delay of 5,000 digits,
                    # which int() refuses, or one float() overflows) is unreadable: disallow all, cached, never re-asked
                    rp = urllib.robotparser.RobotFileParser()
                    rp.disallow_all = True
                    delay = None
                    self._robots_unreadable[exact] = "unparseable"
                    self.log.append({"event": "robots_refused", "host": host, "url": url,
                                     "detail": f"robots.txt not parseable: {type(e).__name__}"})
            elif 400 <= status < 500:
                rp.allow_all = True          # no robots.txt = no rules (RFC 9309)
            else:
                rp.disallow_all = True       # server error: be conservative
                self._robots_unreadable[exact] = f"HTTP {int(status)}"
            self._robots[exact] = rp
            if delay:                        # the site's delay is the largest any of its hosts asks for
                self._delay[key] = max(delay, self._delay.get(key, 0.0))
        return self._robots[exact]

    def robots_unreadable(self, host: str) -> str | None:
        """Why robots.txt of `host` could not be read this run (a refused URL or hop, a cap, a server error or too
        many redirects), so every path there is disallowed for the run; None when it was read (or not asked yet). A
        caller tells "the site's rules say no" (RobotsDisallowed with None here) from "we could not read the rules"."""
        return self._robots_unreadable.get(plain_hostname(host) or host.lower())

    def _location(self, url: str, headers: dict) -> str:
        loc = next((v for k, v in (headers or {}).items() if k.lower() == "location"), None)
        if not loc:
            raise FetchFailed(f"{url}: redirect without a Location header")
        if CONTROL_OR_SPACE.search(loc):    # urljoin would silently drop a tab/CR/LF and fetch another URL
            self.log.append({"event": "refused", "host": split_url(url).netloc, "url": url,
                             "detail": f"control character or space in Location {loc!r}"})
            raise SchemeRefused(f"{url}: redirect Location {loc!r} has a space or control character")
        try:
            nxt = urllib.parse.urljoin(url, loc)
        except ValueError as e:     # e.g. Location: https://[x/
            self.log.append({"event": "error", "host": split_url(url).netloc, "url": url,
                             "detail": f"malformed Location {loc!r}"})
            raise FetchFailed(f"{url}: malformed redirect Location {loc!r} ({e})") from None
        up = upgrade_http(nxt)
        if up != nxt:
            self.log.append({"event": "upgraded", "host": split_url(nxt).netloc, "url": nxt, "detail": up})
            nxt = up
        host = split_url(nxt).netloc
        self.log.append({"event": "redirect", "host": urllib.parse.urlsplit(url).netloc, "url": url, "detail": nxt})
        self.check_url(nxt)                     # every hop, not only the first URL: no http:// or other port
        self.check_host(host)
        self.check_redirect(urllib.parse.urlsplit(url).netloc, host)
        self.check_tenant_redirect(url, nxt)    # national/tenant-cap-redirect: robots.txt hops obey it too
        return nxt

    def get(self, url: str, _hops: int = 0, _headers: dict | None = None) -> tuple[int, bytes, dict]:
        parts = split_url(url)
        self.check_host(parts.netloc)
        self.check_url(url)
        rp = self.robots(parts.netloc, parts.scheme)
        capped = self._robots_capped.get(plain_hostname(parts.netloc) or parts.netloc.lower())
        if capped is not None:   # robots.txt unread for a cap (disallow_all cached): still reported as the cap
            raise RequestCapReached(f"{url} not requested: robots.txt ran into a request cap ({capped})")
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
