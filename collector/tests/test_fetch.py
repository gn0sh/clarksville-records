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


# ------------------------------------------------------------------ 304, 429 back-off, the per-run request cap
def test_a_304_never_skips_the_delay():
    """A 304 (or any non-200) answer is still a request: the next one waits the full host delay."""
    f, net, clock = make({"https://h.example/robots.txt": (200, b"User-agent: *\nCrawl-delay: 12\n"),
                          "https://h.example/a": (304, b""), "https://h.example/b": (200, b"x")})
    assert f.get("https://h.example/a")[0] == 304
    assert f.get("https://h.example/b")[0] == 200
    assert clock.slept == [12.0, 12.0]                 # robots -> a -> b, the crawl-delay before each
    assert [u for u, _ in net.calls].count("https://h.example/a") == 1   # a 304 is not retried


def test_a_429_is_never_retried_and_ends_the_host_for_the_run():
    """Back-off: after a 429 the host gets no request at all for the rest of the run (no retry, faster or slower,
    whatever Retry-After says)."""
    f, net, _ = make({"https://h.example/a": (429, b"slow down", {"Retry-After": "1"}),
                      "https://h.example/b": (200, b"x")})
    with pytest.raises(HostBlocked):
        f.get("https://h.example/a")
    calls = [u for u, _ in net.calls]
    assert calls.count("https://h.example/a") == 1     # unlike a 5xx, never retried
    for _ in range(3):
        with pytest.raises(HostBlocked):
            f.get("https://h.example/b")
    assert [u for u, _ in net.calls] == calls


def test_request_cap_counts_robots_retries_and_redirects_and_is_never_exceeded():
    from collector.fetch import RequestCapReached
    f, net, _ = make({"https://h.example/a": (503, b"busy"),
                      "https://h.example/r": (302, b"", {"Location": "https://g.example/x"}),
                      "https://g.example/x": (200, b"x"), "https://h.example/b": (200, b"x")})
    f.limit_hosts(("h.example", "g.example"), 5)
    f.get("https://h.example/a")                       # robots + a + its retry: 3
    with pytest.raises(RequestCapReached):             # r: 4, g's robots.txt: 5, the redirect target: not made
        f.get("https://h.example/r")
    assert len(net.calls) == 5
    with pytest.raises(RequestCapReached):
        f.get("https://h.example/b")
    assert len(net.calls) == 5 and f.remaining("h.example") == 0 and f.remaining("other.example") is None


def _www():
    net, clock = FakeNet({"https://www.h.example/robots.txt": (200, b"User-agent: *\nCrawl-delay: 15\n"),
                          "https://www.h.example/a": (200, b"x"), "https://h.example/b": (200, b"x"),
                          "https://H.EXAMPLE:443/c": (200, b"x")}), Clock()
    f = PoliteFetcher(opener=net, clock=clock.now, sleep=clock.sleep, proxy_failures=lambda: [],
                      allowed_hosts=("h.example", "g.example"))
    return f, net, clock


def test_www_and_bare_host_share_one_delay_and_cap_but_each_has_its_robots():
    """fetch/host-key-normalization: www.h.example, h.example and H.EXAMPLE:443 are one site for the delay, a block
    and the cap; robots.txt is read and obeyed per exact host (RFC 9309)."""
    from collector.fetch import RequestCapReached, site_key
    assert site_key("WWW.CmcRpc.com:443") == site_key("cmcrpc.com") == "cmcrpc.com"
    f, net, clock = _www()
    f.limit_hosts(("h.example",), 4)
    f.get("https://www.h.example/a")
    f.get("https://h.example/b")
    calls = [u for u, _ in net.calls]
    assert calls == ["https://www.h.example/robots.txt", "https://www.h.example/a", "https://h.example/robots.txt",
                     "https://h.example/b"]
    assert clock.slept == [15.0, 15.0, 15.0]           # www's crawl-delay holds for the bare host (no robots.txt)
    assert f.remaining("www.h.example") == 0 and f.sent("h.example") == 4
    with pytest.raises(RequestCapReached):
        f.get("https://H.EXAMPLE:443/c")


def test_robots_rules_of_one_host_never_apply_to_the_other():
    f, net, _ = _www()
    net.routes["https://www.h.example/robots.txt"] = (200, b"User-agent: *\nDisallow: /a\n")
    net.routes["https://h.example/robots.txt"] = (200, b"User-agent: *\nDisallow: /b\nCrawl-delay: 20\n")
    with pytest.raises(RobotsDisallowed):
        f.get("https://www.h.example/a")
    with pytest.raises(RobotsDisallowed):
        f.get("https://h.example/b")
    assert f.get("https://h.example/a")[0] == 404        # allowed on the bare host (not routed: 404), so asked
    assert f.delay_for("www.h.example") == 20.0          # the larger crawl-delay holds for the whole site


def test_a_block_on_www_blocks_the_bare_host():
    f, net, _ = _www()
    net.routes["https://www.h.example/a"] = (429, b"no")
    with pytest.raises(HostBlocked):
        f.get("https://www.h.example/a")
    n = len(net.calls)
    with pytest.raises(HostBlocked):
        f.get("https://h.example/b")
    assert len(net.calls) == n


def test_a_redirect_from_a_capped_host_cannot_leave_its_cap_group():
    """fetch/cap-redirect-escape: the target is refused with no request (not robots.txt either)."""
    f, net, _ = make({"https://h.example/r": (302, b"", {"Location": "https://g.example/x"}),
                      "https://g.example/x": (200, b"x")})
    f.limit_hosts(("h.example",), 10)
    with pytest.raises(HostRefused):
        f.get("https://h.example/r")
    assert not any("g.example" in u for u, _ in net.calls)
    assert f.remaining("h.example") == 8                # robots.txt and r


def test_a_redirect_inside_the_cap_group_counts_against_the_cap():
    f, net, _ = make({"https://h.example/r": (302, b"", {"Location": "https://www.h.example/x"}),
                      "https://www.h.example/x": (200, b"x")})
    f.limit_hosts(("h.example",), 10)
    assert f.get("https://h.example/r")[0] == 200
    assert f.remaining("h.example") == 6                # robots.txt, r, www robots.txt and the target: one cap


def test_an_uncapped_host_still_follows_redirects_to_other_allowed_hosts():
    f, net, _ = make({"https://h.example/r": (302, b"", {"Location": "https://g.example/x"}),
                      "https://g.example/x": (200, b"x")})
    assert f.get("https://h.example/r")[0] == 200


def test_a_later_cap_never_raises_an_earlier_one():
    f, net, _ = make({"https://h.example/a": (200, b"x")})
    f.limit_hosts(("h.example",), 1)
    f.limit_hosts(("h.example",), 10)
    assert f.remaining("h.example") == 1


def test_the_docs_name_methods_that_exist():
    """The docstrings point at real methods (a renamed method once left `limit_host` behind)."""
    import re
    from collector import fetch as F
    text = F.__doc__ + F.RequestCapReached.__doc__
    for name in set(re.findall(r"\b(limit_hosts?|site_key|check_redirect)\b", text)):
        assert hasattr(F.PoliteFetcher, name) or hasattr(F, name), name
