"""PoliteFetcher's two default-off national fields (docs/architecture/daylight-national.md 4.4.4, 4.4.6 test 9):
`past_deadline` and `max_answer_seconds`. With both None the fetcher makes exactly today's clock(), sleep and read
calls, so the Clarksville collector is unchanged; with them set, nothing is sent at or after the deadline and a slow
answer fails the fetch. No network: the opener is faked."""
import http.client
import io
import socket
import threading
import time
import urllib.error

import pytest

from collector import fetch
from collector.fetch import BLOCK_BODY_BYTES, DeadlineReached, FetchFailed, HostBlocked, PoliteFetcher, RequestCapReached

URL = "https://example.gov/a"
OTHER = "https://example.gov/b"


class Resp(io.BytesIO):
    status, headers = 200, {}

    def __init__(self, body, calls):
        super().__init__(body)
        self.calls = calls

    def read(self, n=-1):
        self.calls.append(("read", n))
        return super().read(n)

    def read1(self, n=-1):
        self.calls.append(("read1", n))
        return super().read1(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def spied(codes=None, **kw):
    """A fetcher whose clock (always 0), sleep and answers' reads are recorded in one list, in call order. `codes`:
    url -> an HTTP error status that URL answers with (its body read through the same spy)."""
    calls = []

    def opener(req, timeout):
        if req.full_url.endswith("/robots.txt"):
            raise urllib.error.HTTPError(req.full_url, 404, "x", {}, io.BytesIO(b""))
        calls.append(("open", req.full_url))
        if req.full_url in (codes or {}):
            raise urllib.error.HTTPError(req.full_url, codes[req.full_url], "x", {}, Resp(b"no", calls))
        return Resp(b"hello", calls)

    def clock():
        calls.append(("clock",))
        return 0.0

    def sleep(s):
        calls.append(("sleep", s))
    f = PoliteFetcher(opener=opener, clock=clock, sleep=sleep, proxy_failures=lambda: [],
                      allowed_hosts=("example.gov",), **kw)
    return f, calls


def test_with_both_fields_none_the_calls_are_todays():
    """4.4.6 test 9: robots.txt (no wait: one clock() for _last), then per request clock() for the gap, sleep(delay),
    clock() for _last, and the body in one read(max_bytes + 1); no read1, no extra clock() for the answer."""
    f, calls = spied()
    assert f.past_deadline is None and f.max_answer_seconds is None
    assert f.get(URL)[1] == b"hello" and f.get(OTHER)[1] == b"hello"
    n = f.max_bytes + 1
    assert calls == [("clock",),                                                     # robots.txt
                     ("clock",), ("sleep", 10.0), ("clock",), ("open", URL), ("read", n),
                     ("clock",), ("sleep", 10.0), ("clock",), ("open", OTHER), ("read", n)]


def test_with_both_fields_none_error_answers_are_read_as_today():
    """fetch/clarksville-spy-200-only: a 404 body in one read(max_bytes + 1), a 403 body in one
    read(BLOCK_BODY_BYTES); no read1, no extra clock() for the answer."""
    f, calls = spied(codes={URL: 404, OTHER: 403})
    assert f.get(URL)[0] == 404
    with pytest.raises(HostBlocked):
        f.get(OTHER)
    assert calls == [("clock",),                                                     # robots.txt
                     ("clock",), ("sleep", 10.0), ("clock",), ("open", URL), ("read", f.max_bytes + 1),
                     ("clock",), ("sleep", 10.0), ("clock",), ("open", OTHER), ("read", BLOCK_BODY_BYTES)]


def test_a_deadline_refuses_before_the_wait_and_before_any_count_changes():
    asked = []
    f, calls = spied(past_deadline=lambda pause: asked.append(pause) or pause > 0)
    with pytest.raises(DeadlineReached):
        f.get(URL)                                     # robots.txt has no wait (pause 0): sent; the get waits: refused
    assert asked == [0.0, 0.0, 10.0]
    assert ("sleep", 10.0) not in calls and ("open", URL) not in calls
    assert f.sent("example.gov") == 1                  # robots.txt only
    assert f.log[-1] == {"event": "deadline", "host": "example.gov", "url": URL}
    assert issubclass(DeadlineReached, RequestCapReached)


def test_a_sleep_that_overshoots_the_deadline_is_refused_after_it():
    state = {"slept": False}
    f, calls = spied(past_deadline=lambda pause: state["slept"])
    f.sleep = lambda s: state.update(slept=True)
    f.robots("example.gov")
    with pytest.raises(DeadlineReached):
        f.get(URL)
    assert state["slept"] and ("open", URL) not in calls and f.sent("example.gov") == 1


def test_robots_refused_by_the_deadline_is_a_cap_for_the_run():
    f, calls = spied(past_deadline=lambda pause: True)
    with pytest.raises(RequestCapReached):
        f.get(URL)
    with pytest.raises(RequestCapReached):
        f.get(OTHER)
    assert f.sent("example.gov") == 0 and not [c for c in calls if c[0] == "open"]


def test_max_answer_seconds_reads_in_chunks_and_fails_a_slow_answer():
    t = {"s": 0.0}

    class Drip(Resp):
        def read1(self, n=-1):
            t["s"] += 50
            return super().read1(n)

    big = b"x" * (5 * fetch.ANSWER_CHUNK)

    def opener(req, timeout):
        if req.full_url.endswith("/robots.txt"):
            raise urllib.error.HTTPError(req.full_url, 404, "x", {}, io.BytesIO(b""))
        return Drip(big, [])
    f = PoliteFetcher(opener=opener, clock=lambda: t["s"], sleep=lambda s: t.update(s=t["s"] + s),
                      proxy_failures=lambda: [], allowed_hosts=("example.gov",), max_answer_seconds=120.0)
    with pytest.raises(FetchFailed, match="slower than 120 s"):
        f.get(URL)
    t["s"] = 0.0
    fast = PoliteFetcher(opener=opener, clock=lambda: 0.0, sleep=lambda s: None, proxy_failures=lambda: [],
                         allowed_hosts=("example.gov",), max_answer_seconds=120.0)
    assert fast.get(URL)[1] == big                     # read whole, in chunks, when it is quick



def test_a_slow_answer_is_logged_once_as_too_slow():
    """fetch/slow-log-misplaced: a slow 200 logs "answer too slow"; so does a slow 404 body, once."""
    t = {"s": 0.0}

    class Slow(Resp):
        def read1(self, n=-1):
            t["s"] += 200
            return super().read1(n)

    def opener(req, timeout):
        if req.full_url.endswith("/robots.txt"):
            raise urllib.error.HTTPError(req.full_url, 404, "x", {}, io.BytesIO(b""))
        if req.full_url == OTHER:
            raise urllib.error.HTTPError(req.full_url, 404, "x", {}, Slow(b"gone", []))
        return Slow(b"hello", [])
    f = PoliteFetcher(opener=opener, clock=lambda: t["s"], sleep=lambda s: None, proxy_failures=lambda: [],
                      allowed_hosts=("example.gov",), max_answer_seconds=120.0)
    for url in (URL, OTHER):
        with pytest.raises(FetchFailed, match="slower than 120 s"):
            f.get(url)
    slow = [e for e in f.log if e.get("detail") == "answer too slow"]
    assert slow == [{"event": "error", "host": "example.gov", "url": URL, "detail": "answer too slow"},
                    {"event": "error", "host": "example.gov", "url": OTHER, "detail": "answer too slow"}]


def _dripping_chunked_server(mode: str, drips: int, gap: float):
    """A local server answering one request with a chunked 200 whose framing drips: after a first chunk `[]`, either
    the last chunk-size line's extension ("sizeline") or the trailer ("trailer"), one piece every `gap` seconds."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve():
        c, _ = srv.accept()
        try:
            c.recv(65536)
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n"
                      b"2\r\n[]\r\n")
            if mode == "sizeline":
                c.sendall(b"0;")
                for _ in range(drips):
                    c.sendall(b"a")
                    time.sleep(gap)
                c.sendall(b"\r\n\r\n")
            else:
                c.sendall(b"0\r\n")
                for _ in range(drips):
                    c.sendall(b"X-a: 1\r\n")
                    time.sleep(gap)
                c.sendall(b"\r\n")
            time.sleep(0.1)
        except OSError:
            pass
        finally:
            c.close()
            srv.close()
    threading.Thread(target=serve, daemon=True).start()
    return srv.getsockname()[1]


@pytest.mark.parametrize("mode", ["sizeline", "trailer"])
def test_a_chunked_answer_whose_framing_drips_fails(mode):
    """national-budget/chunked-framing-drip: http.client reads chunk-size lines and the trailer with readline, each
    socket read under the timeout, so the per-read checks never see the time pass; the check after the last read
    fails the fetch instead of accepting the body (the overrun itself is the 4.4.4 residual)."""
    port = _dripping_chunked_server(mode, drips=8, gap=0.05)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1.0)
    try:
        conn.request("GET", "/")
        r = conn.getresponse()
        f = PoliteFetcher(clock=time.monotonic, max_answer_seconds=0.2, allowed_hosts=("127.0.0.1",))
        t0 = time.monotonic()
        with pytest.raises(FetchFailed, match="slower than 0.2 s"):
            f._read_answer(r, 1000, t0, f"http://127.0.0.1:{port}/")
    finally:
        conn.close()
