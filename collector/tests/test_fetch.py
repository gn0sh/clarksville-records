"""Polite fetcher tests: robots.txt obeyed, 10 s per host, stop on 403/429. No network."""
import io
import urllib.error

import pytest

from collector.fetch import HostBlocked, HostRefused, PoliteFetcher, ProxyRefused, RobotsDisallowed


class FakeResp(io.BytesIO):
    def __init__(self, body, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeNet:
    def __init__(self, routes):
        self.routes = routes          # url -> (status, body)
        self.calls = []

    def __call__(self, req, timeout):
        url = req.full_url
        self.calls.append((url, req.get_header("User-agent")))
        status, body, *rest = self.routes.get(url, (404, b""))
        headers = rest[0] if rest else {}
        if status == "tunnel":
            raise urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden"))
        if status >= 300:                 # the real opener raises for 3xx too (automatic redirects are off)
            raise urllib.error.HTTPError(url, status, "x", headers, io.BytesIO(body))
        return FakeResp(body, status)


class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def make(routes, proxy_failures=None):
    net, clock = FakeNet(routes), Clock()
    f = PoliteFetcher(opener=net, clock=clock.now, sleep=clock.sleep, proxy_failures=lambda: proxy_failures or [],
                      allowed_hosts=("h.example", "g.example", "clarksvilletn.gov", "cityofclarksville.com"))
    return f, net, clock


def test_robots_404_means_no_rules_and_delay_between_requests():
    f, net, clock = make({"https://h.example/a.pdf": (200, b"%PDF-1"), "https://h.example/b.pdf": (200, b"%PDF-2")})
    assert f.get("https://h.example/a.pdf")[1] == b"%PDF-1"
    assert f.get("https://h.example/b.pdf")[1] == b"%PDF-2"
    assert [u for u, _ in net.calls] == ["https://h.example/robots.txt", "https://h.example/a.pdf",
                                         "https://h.example/b.pdf"]
    assert clock.slept == [10.0, 10.0]
    assert all("clarksville-records research collector" in ua for _, ua in net.calls)


def test_robots_disallow_is_obeyed_and_crawl_delay_raises_wait():
    robots = b"User-agent: *\nDisallow: /private\nCrawl-delay: 15\n"
    f, net, clock = make({"https://h.example/robots.txt": (200, robots), "https://h.example/ok": (200, b"x")})
    with pytest.raises(RobotsDisallowed):
        f.get("https://h.example/private/doc")
    f.get("https://h.example/ok")
    assert clock.slept == [15.0]
    assert "https://h.example/private/doc" not in [u for u, _ in net.calls]


@pytest.mark.parametrize("code", [403, 429])
def test_403_or_429_stops_the_host(code):
    f, net, _ = make({"https://h.example/a": (code, b"no"), "https://h.example/b": (200, b"x")})
    with pytest.raises(HostBlocked):
        f.get("https://h.example/a")
    n = len(net.calls)
    with pytest.raises(HostBlocked):
        f.get("https://h.example/b")
    assert len(net.calls) == n            # no further request to that host


def test_delay_is_never_skipped_across_many_requests_and_hosts():
    routes = {f"https://h.example/{i}": (200, b"x") for i in range(5)}
    routes.update({f"https://g.example/{i}": (200, b"x") for i in range(3)})
    f, net, clock = make(routes)
    times = {}
    orig = net.__call__

    def timed(req, timeout):
        host = req.full_url.split("/")[2]
        times.setdefault(host, []).append(clock.t)
        return orig(req, timeout)
    f.opener = timed
    for i in range(3):
        f.get(f"https://h.example/{i}")
        f.get(f"https://g.example/{i}")
    for host, ts in times.items():
        gaps = [b - a for a, b in zip(ts, ts[1:])]
        assert gaps and min(gaps) >= 10.0, (host, gaps)


def test_clarksvilletn_floor_and_robots_crawl_delay_larger_wins():
    f, _, clock = make({"https://clarksvilletn.gov/robots.txt": (200, b"User-agent: *\nCrawl-delay: 12\n"),
                        "https://clarksvilletn.gov/AgendaCenter/a": (200, b"x")})
    f.get("https://clarksvilletn.gov/AgendaCenter/a")
    assert clock.slept == [12.0]
    assert f.delay_for("clarksvilletn.gov") == 12.0
    assert f.delay_for("h.example") == 10.0


@pytest.mark.parametrize("url", ["https://cityofclarksville.com/x", "https://www.cityofclarksville.com/robots.txt",
                                 "https://dev2.montgomerytn.gov/clerk/county-commission-minutes",
                                 "http://dev2.montgomerytn.gov/robots.txt"])
def test_denied_hosts_are_refused_without_any_request(url):
    """cityofclarksville.com blocks tools; dev2.montgomerytn.gov answered 403 from the site (2026-11-07): stopped
    for good, even though montgomerytn.gov itself stays allowed."""
    f, net, _ = make({})
    f.allowed_hosts = f.allowed_hosts + ("montgomerytn.gov",)
    with pytest.raises(HostRefused):
        f.get(url)
    assert net.calls == []


def test_host_not_on_allowlist_is_refused():
    f, net, _ = make({})
    with pytest.raises(HostRefused):
        f.get("https://elsewhere.example/a")
    assert net.calls == []


def test_proxy_tunnel_refusal_does_not_block_the_host():
    f, net, _ = make({"https://h.example/a": ("tunnel", b""), "https://h.example/b": (200, b"ok")})
    with pytest.raises(ProxyRefused):
        f.get("https://h.example/a")
    assert "h.example" not in f._blocked
    assert f.get("https://h.example/b")[1] == b"ok"
    assert [e["event"] for e in f.log].count("proxy_refused") == 1


def test_403_recorded_by_the_proxy_is_a_proxy_refusal_not_a_site_block():
    rec = [{"ts": "2999-01-01T00:00:00.000Z", "kind": "connect_rejected", "host": "h.example:443",
            "detail": "gateway answered 403 to CONNECT (policy denial or upstream failure)"}]
    f, _, _ = make({"https://h.example/a": (403, b"denied"), "https://h.example/b": (200, b"ok")}, rec)
    with pytest.raises(ProxyRefused):
        f.get("https://h.example/a")
    assert f.get("https://h.example/b")[1] == b"ok"


def test_unattributed_403_is_the_sites_block():
    old = [{"ts": "2000-01-01T00:00:00.000Z", "host": "h.example:443", "detail": "gateway answered 403 to CONNECT"}]
    f, net, _ = make({"https://h.example/a": (403, b"no"), "https://h.example/b": (200, b"x")}, old)
    with pytest.raises(HostBlocked):
        f.get("https://h.example/a")
    with pytest.raises(HostBlocked):
        f.get("https://h.example/b")
    assert "https://h.example/b" not in [u for u, _ in net.calls]


def test_repeated_proxy_refusals_skip_the_host_for_the_run():
    f, net, _ = make({f"https://h.example/{i}": ("tunnel", b"") for i in range(5)})
    for i in range(3):
        with pytest.raises(ProxyRefused):
            f.get(f"https://h.example/{i}")
    n = len(net.calls)
    with pytest.raises(ProxyRefused):
        f.get("https://h.example/4")
    assert len(net.calls) == n


def test_server_error_is_retried_once_after_the_delay():
    f, net, clock = make({"https://h.example/a": (503, b"busy")})
    status, _, _ = f.get("https://h.example/a")
    assert status == 503
    assert [u for u, _ in net.calls].count("https://h.example/a") == 2
    assert clock.slept == [10.0, 10.0]


# ------------------------------------------------------------------ redirects (politeness/redirect-bypass)

def test_redirect_goes_through_get_with_robots_and_delay():
    f, net, clock = make({"https://h.example/a": (302, b"", {"Location": "https://g.example/b.pdf"}),
                          "https://g.example/b.pdf": (200, b"%PDF-1")})
    assert f.get("https://h.example/a")[1] == b"%PDF-1"
    assert [u for u, _ in net.calls] == ["https://h.example/robots.txt", "https://h.example/a",
                                         "https://g.example/robots.txt", "https://g.example/b.pdf"]
    assert any(e["event"] == "redirect" for e in f.log)


def test_redirect_on_the_same_host_waits_the_host_delay():
    f, net, clock = make({"https://h.example/a": (301, b"", {"Location": "/b.pdf"}),
                          "https://h.example/b.pdf": (200, b"%PDF-1")})
    assert f.get("https://h.example/a")[1] == b"%PDF-1"
    assert clock.slept == [10.0, 10.0]          # robots -> a -> b, 10 s apart


@pytest.mark.parametrize("target", ["https://www.cityofclarksville.com/x.pdf", "https://dev2.montgomerytn.gov/m",
                                    "https://unlisted.example/x.pdf"])
def test_redirect_to_a_denied_or_unlisted_host_is_refused_without_a_request(target):
    f, net, _ = make({"https://h.example/a": (302, b"", {"Location": target})})
    with pytest.raises(HostRefused):
        f.get("https://h.example/a")
    assert all(not u.startswith(target.split("/x")[0].split("/m")[0]) for u, _ in net.calls)


def test_redirect_to_a_robots_disallowed_path_is_refused():
    f, net, _ = make({"https://h.example/a": (302, b"", {"Location": "https://g.example/private/x.pdf"}),
                      "https://g.example/robots.txt": (200, b"User-agent: *\nDisallow: /private/\n")})
    with pytest.raises(RobotsDisallowed):
        f.get("https://h.example/a")
    assert "https://g.example/private/x.pdf" not in [u for u, _ in net.calls]


def test_redirect_loop_fails():
    from collector.fetch import FetchFailed
    f, net, _ = make({"https://h.example/a": (302, b"", {"Location": "https://h.example/a"})})
    with pytest.raises(FetchFailed):
        f.get("https://h.example/a")


def test_real_opener_does_not_follow_redirects():
    import urllib.request
    from collector import fetch as F
    assert any(isinstance(h, F._NoRedirect) for h in F._OPENER.handlers)
    assert not any(type(h) is urllib.request.HTTPRedirectHandler for h in F._OPENER.handlers)


def test_host_matches_is_the_public_host_rule():
    # the rule adapters share with the fetcher (collector.county_agenda, collector.fin_run): no private import
    from collector import county_agenda, fetch, fin_run
    assert fetch.host_matches("WWW.h.example:443", ("h.example",)) and fetch.host_matches("h.example", ("h.example",))
    assert not fetch.host_matches("evilh.example", ("h.example",))
    assert not fetch.host_matches("h.example.net", ("h.example",))
    assert not hasattr(fetch, "_host_matches")
    assert county_agenda.host_matches is fetch.host_matches and fin_run.host_matches is fetch.host_matches


class HeaderNet:
    """Records each request's conditional headers; `answers` is url -> list of (status, body, headers) in order."""

    def __init__(self, answers):
        self.answers, self.seen = answers, []

    def __call__(self, req, timeout):
        url = req.full_url
        self.seen.append((url, req.get_header("If-none-match"), req.get_header("If-modified-since"),
                          req.get_header("User-agent")))
        if url.endswith("/robots.txt"):
            raise urllib.error.HTTPError(url, 404, "x", {}, io.BytesIO(b""))
        status, body, headers = self.answers[url].pop(0)
        if status >= 300:
            raise urllib.error.HTTPError(url, status, "x", headers, io.BytesIO(body))
        return FakeResp(body, status, headers)


def test_get_if_changed_sends_the_stored_validators_and_returns_304_without_a_body():
    # politeness/daily-full-pdf-recheck
    from collector.fetch import USER_AGENT
    u, lm = "https://h.example/a.pdf", "Mon, 09 Nov 2026 21:03:12 GMT"
    net, clock = HeaderNet({u: [(304, b"", {"ETag": '"abc"'}), (200, b"%PDF new", {"ETag": '"def"'}),
                                (200, b"%PDF new", {}), (200, b"%PDF new", {}), (500, b"", {}), (304, b"", {})]}), Clock()
    f = PoliteFetcher(opener=net, clock=clock.now, sleep=clock.sleep, proxy_failures=lambda: [],
                      allowed_hosts=("h.example", "g.example"))
    assert f.get_if_changed(u, etag='"abc"', last_modified=lm)[:2] == (304, b"")
    assert net.seen[-1] == (u, '"abc"', lm, USER_AGENT)
    assert "h.example" not in f._blocked                             # a 304 is not a refusal
    assert f.get_if_changed(u, etag='"abc"')[:2] == (200, b"%PDF new")          # changed: the document
    assert net.seen[-1][1:3] == ('"abc"', None)
    # no validator, or one that is not a clean header value: the plain GET
    assert f.get_if_changed(u)[0] == 200 and net.seen[-1][1:3] == (None, None)
    assert f.get_if_changed(u, etag='"a"\r\nX-Evil: 1', last_modified=" ")[0] == 200
    assert net.seen[-1][1:3] == (None, None)
    # a server error is retried once with the same validators; one request each otherwise, 10 s apart
    assert f.get_if_changed(u, etag='"def"')[0] == 304
    assert [x[1] for x in net.seen[-2:]] == ['"def"', '"def"']
    assert all(s >= 10.0 for s in clock.slept)
    assert len([x for x in net.seen if x[0] == u]) == 6
    # robots.txt and the allowlist apply as for get()
    with pytest.raises(HostRefused):
        f.get_if_changed("https://elsewhere.example/a.pdf", etag='"abc"')


def test_a_redirect_target_gets_the_plain_get_without_the_validators():
    u, v = "https://h.example/a.pdf", "https://g.example/b.pdf"
    net, clock = HeaderNet({u: [(302, b"", {"Location": v})], v: [(200, b"%PDF", {})]}), Clock()
    f = PoliteFetcher(opener=net, clock=clock.now, sleep=clock.sleep, proxy_failures=lambda: [],
                      allowed_hosts=("h.example", "g.example"))
    assert f.get_if_changed(u, etag='"abc"')[:2] == (200, b"%PDF")
    assert [(x[0], x[1]) for x in net.seen if not x[0].endswith("robots.txt")] == [(u, '"abc"'), (v, None)]
