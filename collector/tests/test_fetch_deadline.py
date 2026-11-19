"""PoliteFetcher's two default-off national fields (docs/architecture/daylight-national.md 4.4.4, 4.4.6 test 9):
`past_deadline` and `max_answer_seconds`. With both None the fetcher makes exactly today's clock(), sleep and read
calls, so the Clarksville collector is unchanged; with them set, nothing is sent at or after the deadline and a slow
answer fails the fetch. No network: the opener is faked."""
import io
import urllib.error

import pytest

from collector import fetch
from collector.fetch import DeadlineReached, FetchFailed, PoliteFetcher, RequestCapReached

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


def spied(**kw):
    """A fetcher whose clock (always 0), sleep and answers' reads are recorded in one list, in call order."""
    calls = []

    def opener(req, timeout):
        if req.full_url.endswith("/robots.txt"):
            raise urllib.error.HTTPError(req.full_url, 404, "x", {}, io.BytesIO(b""))
        calls.append(("open", req.full_url))
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
