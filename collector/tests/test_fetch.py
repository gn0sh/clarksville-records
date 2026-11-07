"""Polite fetcher tests: robots.txt obeyed, 10 s per host, stop on 403/429. No network."""
import io
import json
import urllib.error

import pytest

from collector.fetch import HostBlocked, PoliteFetcher, RobotsDisallowed, cache_download


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
        status, body = self.routes.get(url, (404, b""))
        if status >= 400:
            raise urllib.error.HTTPError(url, status, "x", {}, io.BytesIO(body))
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


def make(routes):
    net, clock = FakeNet(routes), Clock()
    return PoliteFetcher(opener=net, clock=clock.now, sleep=clock.sleep), net, clock


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


def test_cache_download_writes_manifest_and_skips_cached(tmp_path):
    f, net, _ = make({"https://h.example/m.pdf": (200, b"%PDF-xyz")})
    man = tmp_path / "manifest.json"
    e = cache_download(f, "https://h.example/m.pdf", tmp_path / "raw", man, {"label": "M"})
    assert (tmp_path / "raw" / e["file"]).read_bytes() == b"%PDF-xyz"
    assert json.loads(man.read_text())[0]["sha256"] == e["sha256"]
    n = len(net.calls)
    cache_download(f, "https://h.example/m.pdf", tmp_path / "raw", man)
    assert len(net.calls) == n
