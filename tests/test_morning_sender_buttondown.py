"""T4.4: the Buttondown adapter (sender/buttondown.py) and `deliver --live`, against a local fake HTTP layer.

No test here opens a connection: every adapter gets FakeHTTP as its opener, and an autouse fixture makes any socket
use fail. The fake speaks the API shape the architecture records ("Buttondown: verified and assumed"); what is
assumed there is listed as "verify in T4.0 probe" in docs/tasks/morning-note.md T4.4. Fixture people are made up
and at example.com only.
"""
from __future__ import annotations

import copy
import dataclasses
import functools
import http.client
import json
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from sender import buttondown as bd
from sender import deliver
from sender import plan as plan_mod
from sender import settings as settings_mod
from test_morning import D, inputs  # noqa: F401
from test_morning_sender_deliver import AT_5, DAY, SECRET_BODY, TZ, key_for, people, settings, stamp
from test_morning_sender_plan import TEST_HOSTS, cfg_with, msite  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
KEY = "made-up-test-key-not-a-real-one-32b"     # also the stamps' secret (test_morning_sender_deliver.SECRET)
BASE = "https://api.buttondown.com/v1"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a test tried to open a real connection")
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, refuse)


@pytest.fixture(scope="module")
def plan(msite):  # noqa: F811
    return plan_mod.build(msite, D, cfg_with())["plan"]


# ------------------------------------------------------------------------------------------------ the fake layer
class Resp:
    """A response as urllib's https handler returns one (no error processor: every status comes back)."""

    def __init__(self, status=200, data=None, raw=None, ctype="application/json", headers=None):
        self.status = status
        self.body = raw if raw is not None else (b"" if data is None else json.dumps(data).encode("utf-8"))
        self.headers = Message()
        if ctype and self.body:
            self.headers["Content-Type"] = ctype
        for k, v in (headers or {}).items():
            self.headers[k] = v

    def read(self, n=-1):
        return self.body if n is None or n < 0 else self.body[:n]

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHTTP:
    """An in-memory Buttondown at the HTTP level, used as the adapter's opener. `faults`: {(method, route): [Resp or
    exception, ...]} answered first, one per request, before the normal route."""

    def __init__(self, subscribers=(), emails=(), page_size=2, faults=None):
        self.subs = {s["id"]: copy.deepcopy(s) for s in subscribers}
        self.email_rows = [copy.deepcopy(e) for e in emails]
        self.page_size = page_size
        self.faults = {k: list(v) for k, v in (faults or {}).items()}
        self.requests = []      # (method, url, headers {lower name: value}, body or None, timeout)
        self.drafts_sent = []

    @staticmethod
    def route(path: str) -> str:
        path = path[len("/v1"):]
        path = re.sub(r"^/emails/[^/]+/send-draft$", "/emails/{id}/send-draft", path)
        return re.sub(r"^/(subscribers|emails)/[^/]+$", r"/\1/{id}", path)

    def open(self, req, timeout=None):
        u = urlsplit(req.full_url)
        assert u.scheme == "https" and u.netloc == "api.buttondown.com", "the adapter left the pinned host"
        body = json.loads(req.data) if req.data else None
        self.requests.append((req.get_method(), req.full_url, {k.lower(): v for k, v in req.header_items()}, body,
                              timeout))
        key = (req.get_method(), self.route(u.path))
        if self.faults.get(key):
            f = self.faults[key].pop(0)
            if isinstance(f, BaseException):
                raise f
            if f is not None:
                return f
        return self.answer(req.get_method(), u, body)

    def _page(self, rows, path, query):
        page = int(parse_qs(query).get("page", ["1"])[0])
        n = self.page_size
        chunk = rows[(page - 1) * n: page * n]
        nxt = f"{BASE}{path}?page={page + 1}" if page * n < len(rows) else None
        return Resp(200, {"results": chunk, "next": nxt, "previous": None, "count": len(rows)})

    def answer(self, method, u, body):
        route, ident = self.route(u.path), u.path.rstrip("/").split("/")
        if (method, route) == ("GET", "/subscribers"):
            return self._page(list(self.subs.values()), "/subscribers", u.query)
        if (method, route) == ("GET", "/subscribers/{id}"):
            row = self.subs.get(ident[-1])
            return Resp(200, row) if row else Resp(404, {"detail": "Not found."})
        if (method, route) == ("PATCH", "/subscribers/{id}"):
            row = self.subs[ident[-1]]
            row["metadata"] = copy.deepcopy(body["metadata"])
            return Resp(200, row)
        if (method, route) == ("GET", "/emails"):
            return self._page(self.email_rows, "/emails", u.query)
        if (method, route) == ("POST", "/emails"):
            row = {"id": f"em{len(self.email_rows) + 1:04d}", "subject": body["subject"], "status": body["status"],
                   "metadata": body.get("metadata", {}), "publish_date": body.get("publish_date")}
            if "filters" in body:
                row["filters"] = body["filters"]
            self.email_rows.append(row)
            return Resp(201, row)
        if (method, route) == ("PATCH", "/emails/{id}"):
            row = next(r for r in self.email_rows if r["id"] == ident[-1])
            row["status"] = body["status"]
            return Resp(200, row)
        if (method, route) == ("POST", "/emails/{id}/send-draft"):
            self.drafts_sent.append((ident[-2], body["subscribers"]))
            return Resp(200)
        return Resp(404, {"detail": "Not found."})

    # what the provider would do with each created stamp email
    def audience(self, email_row) -> set:
        value = email_row["filters"]["filters"][0]["value"]
        return {s["id"] for s in self.subs.values() if (s.get("metadata") or {}).get("note_edition") == value}

    def calls(self, method=None, route=None):
        return [r for r in self.requests
                if (method is None or r[0] == method) and (route is None or self.route(urlsplit(r[1]).path) == route)]


def client(http, **kw):
    sleeps = kw.pop("sleeps", [])
    return bd.Buttondown(KEY, opener=http, sleep=sleeps.append, monotonic=kw.pop("monotonic", lambda: 1000.0), **kw)


def live(plan, http, s=None, now=AT_5, sleeps=None, canary_ids=None):
    lines = []
    res = deliver.run(plan, s or settings(), provider=client(http), live=True, now=now, canary_ids=canary_ids,
                      stamp_secret=KEY.encode(), sleep=(sleeps.append if sleeps is not None else lambda _s: None),
                      out=lines.append)
    return res, "\n".join(lines)


# ------------------------------------------------------------------------------------------------ the connection
def test_the_default_opener_speaks_https_only_with_no_proxy_and_no_redirect():
    od = bd.make_opener()
    kinds = {type(h) for h in od.handlers}
    assert kinds == {urllib.request.HTTPSHandler, urllib.request.UnknownHandler}
    assert not any(isinstance(h, (urllib.request.ProxyHandler, urllib.request.HTTPRedirectHandler,
                                  urllib.request.HTTPHandler, urllib.request.HTTPErrorProcessor)) for h in od.handlers)
    https = next(h for h in od.handlers if isinstance(h, urllib.request.HTTPSHandler))
    assert https._context.verify_mode.name == "CERT_REQUIRED" and https._context.check_hostname
    with pytest.raises(urllib.error.URLError):          # refused before any connection: no http handler
        od.open(urllib.request.Request("http://api.buttondown.com/v1/emails"), timeout=1)


def test_every_request_is_https_to_the_pinned_host_with_the_key_header_and_a_timeout(plan):
    http = FakeHTTP(people(plan))
    assert live(plan, http)[0].status == "sent"
    assert http.requests
    for method, url, headers, _body, timeout in http.requests:
        assert url.startswith(BASE + "/") and timeout == bd.TIMEOUT
        assert headers["authorization"] == f"Token {KEY}"
        assert ("x-idempotency-key" in headers) == (method != "GET")


def test_the_client_refuses_any_other_api_base_and_a_malformed_key():
    for base in ("http://api.buttondown.com/v1", "https://api.buttondown.com.evil.example/v1",
                 "https://api.buttondown.com/v2", "https://api.buttondown.com:444/v1"):
        with pytest.raises(ValueError):
            bd.Buttondown(KEY, api_base=base, opener=FakeHTTP())
    for key in ("", "short", KEY + "\r\nX-Evil: 1", "has a space in it, so no", "é" * 20):
        with pytest.raises(ValueError) as e:
            bd.Buttondown(key, opener=FakeHTTP())
        assert key not in str(e.value) or not key


def test_the_key_is_not_in_the_clients_repr():
    c = client(FakeHTTP())
    assert KEY not in repr(c) and KEY not in str(c)


def test_a_redirect_is_never_followed(plan):
    http = FakeHTTP(people(plan), faults={("GET", "/emails"): [
        Resp(302, raw=b"", headers={"Location": "https://evil.example/v1/emails"})]})
    res, _ = live(plan, http)
    assert (res.code, res.status) == (1, "failed") and len(http.requests) == 1


@pytest.mark.parametrize("bad_next", [
    "https://evil.example/v1/subscribers?page=2", "http://api.buttondown.com/v1/subscribers?page=2",
    "https://api.buttondown.com/v2/subscribers?page=2", "https://api.buttondown.com:8443/v1/subscribers?page=2",
    "https://user@api.buttondown.com/v1/subscribers?page=2", 7])
def test_a_next_link_off_the_pinned_host_is_refused(bad_next):
    http = FakeHTTP(faults={("GET", "/subscribers"): [
        Resp(200, {"results": [], "next": bad_next, "count": 3})]})
    with pytest.raises(deliver.ProviderError):
        client(http).subscribers()
    assert len(http.requests) == 1


@pytest.mark.parametrize("url", ["https://evil.example/v1/emails", "http://api.buttondown.com/v1/emails",
                                 "https://api.buttondown.com:443/v1/emails", "https://u:p@api.buttondown.com/v1/emails",
                                 "https://api.buttondown.com/v1/../admin", "https://api.buttondown.com/v2/emails"])
def test_each_request_is_checked_against_the_pinned_host_on_its_own(url):
    """The second layer: even a URL that got past the listing's next-link check is refused before any request."""
    http = FakeHTTP()
    with pytest.raises(deliver.ProviderError) as e:
        client(http)._send("GET", url, "/emails")
    assert http.requests == [] and str(e.value) == "GET /emails: a URL off the pinned host"


UNSAFE = ["\t", "\n", "\r", " ", "\x00", "\x1f", "\x7f", "é", "​", "\\"]


@pytest.mark.parametrize("ch", UNSAFE, ids=repr)
def test_a_url_with_a_control_space_non_ascii_or_backslash_is_refused(ch):
    """sender/transport/parse-differential: urlsplit drops a tab or newline that another parser keeps, so any such
    character anywhere in a URL is refused before it is parsed; also in a next link."""
    http = FakeHTTP()
    for url in (f"https://api.buttondown.com/v1/emails{ch}", f"https://api.buttondown.com{ch}/v1/emails",
                f"https://api.buttondown.com/v1/em{ch}ails?page=2", f"https://api.buttondown.com{ch}@evil.example/v1/x"):
        with pytest.raises(deliver.ProviderError) as e:
            client(http)._send("GET", url, "/emails")
        assert str(e.value) == "GET /emails: a URL off the pinned host"
    nxt = f"https://api.buttondown.com/v1/emails?page=2{ch}"
    http = FakeHTTP(faults={("GET", "/emails"): [Resp(200, {"results": [], "next": nxt, "count": 0})]})
    with pytest.raises(deliver.ProviderError) as e:
        client(http).emails()
    assert str(e.value) == "GET /emails: a next link off the pinned host" and len(http.requests) == 1


@pytest.mark.parametrize("field, value", [("type", "http"), ("host", "evil.example"), ("selector", "/v2/emails"),
                                          ("host", "api.buttondown.com:443")])
def test_the_request_urllib_builds_must_agree_on_scheme_host_and_path(monkeypatch, field, value):
    """The second parse: whatever urllib's Request makes of the URL is checked again before it is opened."""
    class Skewed(urllib.request.Request):
        @property
        def selector(self):
            return value if field == "selector" else super().selector

        @selector.setter
        def selector(self, v):
            self.__dict__["_sel"] = v

    real = urllib.request.Request

    def make(*a, **k):
        r = Skewed(*a, **k) if field == "selector" else real(*a, **k)
        if field != "selector":
            setattr(r, field, value)
        return r
    monkeypatch.setattr(bd.urllib.request, "Request", make)
    http = FakeHTTP()
    with pytest.raises(deliver.ProviderError) as e:
        client(http).emails()
    assert str(e.value) == "GET /emails: a URL off the pinned host" and http.requests == []


def test_a_listing_is_read_page_by_page_and_reduced_at_the_boundary(plan):
    rows = people(plan)
    http = FakeHTTP(rows, page_size=2)
    got = client(http).subscribers()
    assert len(http.calls("GET", "/subscribers")) == 4            # 7 rows, 2 a page
    assert [g["id"] for g in got] == [r["id"] for r in rows]
    assert all(set(g) == {"id", "type", "metadata"} for g in got)  # no address, IP or notes past the adapter
    assert "example.com" not in json.dumps(got)


@pytest.mark.parametrize("page", [
    {"results": [], "next": None},                                   # no count
    {"results": [], "next": None, "count": 2},                       # rows do not add up: cut short
    {"next": None, "count": 0},                                      # no results
    {"results": {}, "next": None, "count": 0},
    ["not", "a", "page"],
])
def test_a_listing_of_an_unexpected_shape_fails_closed(page):
    http = FakeHTTP(faults={("GET", "/emails"): [Resp(200, page)]})
    with pytest.raises(deliver.ProviderError):
        client(http).emails()


def test_a_page_that_links_back_fails_closed():
    loop = Resp(200, {"results": [], "next": f"{BASE}/emails?page=1", "count": 0})
    http = FakeHTTP(faults={("GET", "/emails"): [Resp(200, {"results": [], "next": f"{BASE}/emails?page=1",
                                                             "count": 0}), loop]})
    with pytest.raises(deliver.ProviderError):
        client(http).emails()


@pytest.mark.parametrize("resp", [
    Resp(200, raw=b"<html>oops</html>", ctype="text/html"), Resp(200, raw=b"{not json"),
    Resp(200, raw=b"\xff\xfe"), Resp(200, raw=b"{}" + b" " * bd.MAX_RESPONSE),
])
def test_an_answer_that_is_not_json_or_too_big_fails_closed(resp):
    with pytest.raises(deliver.ProviderError):
        client(FakeHTTP(faults={("GET", "/emails"): [resp]})).emails()


@pytest.mark.parametrize("header, want", [("7", 7.0), ("0", 0.0), (None, bd.DEFAULT_RETRY), ("soon", bd.DEFAULT_RETRY),
                                          ("-3", bd.DEFAULT_RETRY), ("Wed, 11 Nov 2026 11:00:30 GMT", 30.0),
                                          ("Wed, 11 Nov 2026 10:59:00 GMT", 0.0)])
def test_retry_after_reads_seconds_or_a_date_and_is_never_negative(header, want):
    assert bd.retry_after(header, now=datetime(2026, 11, 11, 11, 0, tzinfo=timezone.utc)) == want


def test_a_429_raises_rate_limited_with_its_retry_after():
    http = FakeHTTP(faults={("GET", "/emails"): [Resp(429, raw=b"", headers={"Retry-After": "7"})]})
    with pytest.raises(deliver.RateLimited) as e:
        client(http).emails()
    assert e.value.retry_after == 7.0 and str(e.value) == "rate limited"


def test_429_through_the_adapter_is_obeyed_three_tries_then_stop(plan):
    limited = [Resp(429, raw=b"", headers={"Retry-After": "2"}) for _ in range(5)]
    http = FakeHTTP(people(plan), faults={("GET", "/emails"): limited})
    sleeps = []
    res, _ = live(plan, http, sleeps=sleeps)
    assert (res.code, res.status, res.editions) == (1, "failed", 0)
    assert len(http.requests) == 3 and sleeps == [2.0, 2.0]
    assert not http.calls("POST") and not http.calls("PATCH")


def test_requests_are_paced_to_at_most_five_a_second():
    clock = [100.0]
    sleeps = []
    http = FakeHTTP([{"id": f"s{i}", "type": "regular", "metadata": {}} for i in range(6)], page_size=2)
    c = bd.Buttondown(KEY, opener=http, sleep=sleeps.append, monotonic=lambda: clock[0])
    c.subscribers()
    assert len(http.requests) == 3 and sleeps == [pytest.approx(bd.MIN_INTERVAL)] * 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 500, 503])
def test_an_error_names_method_path_template_and_status_only(status):
    http = FakeHTTP([{"id": "sub-0001-secret", "type": "regular", "metadata": {}}], faults={
        ("PATCH", "/subscribers/{id}"): [Resp(status, raw=SECRET_BODY.encode(), ctype="text/plain")]})
    with pytest.raises(deliver.ProviderError) as e:
        client(http).set_metadata("sub-0001-secret", {"a": 1}, "idem")
    assert str(e.value) == f"PATCH /subscribers/{{id}}: HTTP {status}"


@pytest.mark.parametrize("exc", [urllib.error.URLError(f"cannot reach {BASE}/subscribers/sub-0001-secret"),
                                 TimeoutError("timed out sub-0001-secret"), ConnectionResetError(SECRET_BODY)])
def test_a_connection_failure_carries_no_url_and_is_not_chained(exc):
    http = FakeHTTP(faults={("GET", "/subscribers/{id}"): [exc]})
    with pytest.raises(deliver.ProviderError) as e:
        client(http).subscriber("sub-0001-secret")
    assert str(e.value) == "GET /subscribers/{id}: the connection failed"
    assert e.value.__cause__ is None and e.value.__suppress_context__


@pytest.mark.parametrize("exc", [http.client.BadStatusLine(SECRET_BODY), http.client.LineTooLong(SECRET_BODY),
                                 http.client.RemoteDisconnected(SECRET_BODY), http.client.IncompleteRead(b"sub-0001-secret"),
                                 http.client.HTTPException(f"{BASE}/subscribers/sub-0001-secret")])
def test_an_http_client_error_is_wrapped_never_let_out(exc):
    """sender/adapter-errors/httpexception-unwrapped: http.client's own errors (not all are OSError) carry what the
    server sent; each becomes the fixed connection-failed error, not chained."""
    with pytest.raises(deliver.ProviderError) as e:
        client(FakeHTTP(faults={("GET", "/subscribers/{id}"): [exc]})).subscriber("sub-0001-secret")
    assert str(e.value) == "GET /subscribers/{id}: the connection failed"
    assert e.value.__cause__ is None and e.value.__suppress_context__


def test_an_http_client_error_while_reading_is_wrapped_too():
    class Broken(Resp):
        def read(self, n=-1):
            raise http.client.IncompleteRead(SECRET_BODY.encode())
    with pytest.raises(deliver.ProviderError) as e:
        client(FakeHTTP(faults={("GET", "/emails"): [Broken(200, {"results": []})]})).emails()
    assert str(e.value) == "GET /emails: the answer could not be read" and SECRET_BODY not in repr(e.value)


@pytest.mark.parametrize("bad_id", ["../emails", "a/b", "a?b", "a%2fb", "", "x" * 65, None, "é"])
def test_an_id_that_could_leave_its_path_segment_is_refused_before_any_request(bad_id):
    http = FakeHTTP()
    c = client(http)
    for call in (lambda: c.subscriber(bad_id), lambda: c.set_metadata(bad_id, {}, "k"),
                 lambda: c.unschedule(bad_id, "k"), lambda: c.send_draft(bad_id, ["s1"], "k"),
                 lambda: c.send_draft("em1", [bad_id], "k")):
        with pytest.raises(deliver.ProviderError):
            call()
    assert http.requests == []


def test_a_missing_subscriber_is_none_and_another_one_is_refused():
    http = FakeHTTP([{"id": "s1", "type": "regular", "metadata": {}, "email_address": "a@example.com"}])
    c = client(http)
    assert c.subscriber("s9") is None
    assert c.subscriber("s1") == {"id": "s1", "type": "regular", "metadata": {}}
    http.faults[("GET", "/subscribers/{id}")] = [Resp(200, {"id": "s2", "type": "regular", "metadata": {}})]
    with pytest.raises(deliver.ProviderError):
        c.subscriber("s1")


# ------------------------------------------------------------------------------------------------ the writes
def test_a_metadata_write_is_a_patch_of_metadata_only_and_must_echo_whole():
    http = FakeHTTP([{"id": "s1", "type": "regular", "metadata": {"lists": ["budget"], "ward": 3}}])
    c = client(http)
    c.set_metadata("s1", {"lists": ["budget"], "ward": 3, "note_edition": "x"}, "idem-1")
    method, url, headers, body, _ = http.requests[-1]
    assert (method, url, body) == ("PATCH", f"{BASE}/subscribers/s1",
                                   {"metadata": {"lists": ["budget"], "ward": 3, "note_edition": "x"}})
    assert headers["x-idempotency-key"] == "idem-1"
    # a provider that stored something else (merged, dropped a key) fails the write
    http.faults[("PATCH", "/subscribers/{id}")] = [Resp(200, {"id": "s1", "type": "regular", "metadata": {"x": 1}})]
    with pytest.raises(deliver.ProviderError):
        c.set_metadata("s1", {"lists": ["budget"]}, "idem-2")


def test_no_write_can_change_type_address_or_create_or_delete_a_subscriber(plan):
    http = FakeHTTP(people(plan))
    assert live(plan, http)[0].status == "sent"
    for method, url, _h, body, _t in http.requests:
        assert method in ("GET", "PATCH", "POST")
        if urlsplit(url).path.startswith("/v1/subscribers"):
            assert method in ("GET", "PATCH")
            assert method == "GET" or set(body) == {"metadata"}


def test_create_email_sends_known_fields_only_and_returns_what_the_provider_stored():
    http = FakeHTTP()
    c = client(http)
    with pytest.raises(deliver.ProviderError):
        c.create_email({"subject": "s", "body": "b", "status": "sent", "recipients": ["a@example.com"]}, "k")
    assert http.requests == []
    payload = {"subject": "s", "body": "b", "status": "draft", "metadata": {"note_date": DAY},
               "archival_mode": "disabled"}
    got = c.create_email(payload, "k")
    assert got == {"id": "em0001", "status": "draft", "metadata": {"note_date": DAY}}    # no filters key: none stored
    assert http.requests[-1][3] == payload and http.requests[-1][2]["x-idempotency-key"] == "k"
    http.faults[("POST", "/emails")] = [Resp(201, ["not", "an", "email"])]
    with pytest.raises(deliver.ProviderError):
        c.create_email(payload, "k2")


def test_unschedule_and_send_draft_send_exactly_their_one_field():
    http = FakeHTTP(emails=[{"id": "em1", "status": "scheduled", "metadata": {}}])
    c = client(http)
    assert c.unschedule("em1", "k1") == {"id": "em1", "status": "draft", "metadata": {}}
    assert http.requests[-1][:2] == ("PATCH", f"{BASE}/emails/em1") and http.requests[-1][3] == {"status": "draft"}
    c.send_draft("em1", ["s1", "s2"], "k2")
    assert http.requests[-1][:2] == ("POST", f"{BASE}/emails/em1/send-draft")
    assert http.requests[-1][3] == {"subscribers": ["s1", "s2"]}
    with pytest.raises(deliver.ProviderError):
        c.send_draft("em1", [], "k3")


# ------------------------------------------------------------------------------------------------ end to end
def test_stamp_mode_end_to_end_reaches_exactly_each_editions_people(plan):
    rows = people(plan)
    http = FakeHTTP(rows)
    res, text = live(plan, http)
    assert (res.code, res.status, res.editions, res.recipients) == (0, "sent", 3, 4)
    assert text == f"morning note {DAY}: sent; emails created 3; recipients in total 4"
    made = [e for e in http.email_rows if e["metadata"].get("note_date") == DAY]
    assert len(made) == 3 and all(e["status"] == "scheduled" for e in made)
    want: dict = {}
    for sid, shape in (("sub-0001-secret", (["budget"],)), ("sub-0002-secret", (["budget"], 7)),
                       ("sub-0003-secret", (["contracts"],)), ("sub-0004-secret", (["budget", "contracts"], None, 3))):
        want.setdefault(key_for(plan, *shape), set()).add(sid)
    for e in made:
        key = e["metadata"]["note_edition"].split(".")[1]
        assert http.audience(e) == want[key]
        assert e["filters"]["filters"][0]["value"] == stamp(key)
    assert http.subs["sub-0004-secret"]["metadata"]["favourite"] == "blue"     # other keys kept


def test_ids_mode_end_to_end_drafts_then_sends_and_writes_no_subscriber(plan):
    http = FakeHTTP(people(plan))
    res, _ = live(plan, http, s=settings(mode="ids"))
    assert (res.status, res.editions, res.recipients) == ("sent", 3, 4)
    assert not http.calls("PATCH") and len(http.drafts_sent) == 3
    assert sorted(i for _, ids in http.drafts_sent for i in ids) == [
        "sub-0001-secret", "sub-0002-secret", "sub-0003-secret", "sub-0004-secret"]


@pytest.mark.parametrize("mode", ["stamp", "ids"])
def test_never_twice_through_the_adapter(plan, mode):
    http = FakeHTTP(people(plan))
    assert live(plan, http, s=settings(mode=mode))[0].editions == 3
    before = len(http.calls("POST"))
    res, _ = live(plan, http, s=settings(mode=mode))
    assert (res.status, res.editions) == ("sent", 0) and len(http.calls("POST")) == before


def test_a_run_that_died_after_edition_1_finishes_the_rest_through_the_adapter(plan):
    http = FakeHTTP(people(plan), faults={("POST", "/emails"): [None, Resp(500, raw=b"")]})
    assert live(plan, http)[0].editions == 1
    res, _ = live(plan, http)
    assert (res.status, res.editions) == ("sent", 2)
    assert len([e for e in http.email_rows if e["metadata"].get("note_date") == DAY]) == 3


def test_a_cut_short_email_listing_sends_nothing(plan):
    http = FakeHTTP(people(plan), faults={("GET", "/emails"): [Resp(200, {"results": [], "next": None, "count": 4})]})
    res, _ = live(plan, http)
    assert (res.code, res.status) == (1, "failed") and not http.calls("POST") and not http.calls("PATCH")


def test_an_email_echo_that_differs_is_taken_back_through_the_adapter(plan):
    def stored_wrong():
        return Resp(201, {"id": "em0001", "status": "scheduled", "metadata": {"note_date": DAY},
                          "filters": {"filters": [], "groups": [], "predicate": "and"}})
    http = FakeHTTP(people(plan), faults={("POST", "/emails"): [stored_wrong()]})
    http.email_rows.append({"id": "em0001", "status": "scheduled", "metadata": {}})   # what the PATCH finds
    res, text = live(plan, http)
    assert (res.code, res.status, res.editions) == (1, "failed", 0)
    assert http.calls("PATCH", "/emails/{id}") and "taken back to a draft" in text


def test_canary_only_through_the_adapter_reaches_only_the_canaries(plan):
    http = FakeHTTP(people(plan))
    res, _ = live(plan, http, s=settings(canary_only=True), canary_ids=frozenset({"sub-0003-secret"}))
    assert (res.editions, res.recipients) == (1, 1)
    patched = {urlsplit(u).path.rsplit("/", 1)[1] for m, u, *_ in http.calls("PATCH", "/subscribers/{id}")}
    assert patched == {"sub-0003-secret"}


def test_over_max_recipients_writes_nothing_through_the_adapter(plan):
    http = FakeHTTP(people(plan))
    res, _ = live(plan, http, s=settings(max_recipients=3))
    assert (res.code, res.status) == (2, "over-limit") and not http.calls("POST") and not http.calls("PATCH")


def _leaks(rows) -> list[str]:
    out = [SECRET_BODY, KEY, "192.0.2.10", "made-up fixture person"]
    for s in rows:
        out += [s["id"], s["email_address"]]
    return out


@pytest.mark.parametrize("mode", ["stamp", "ids"])
@pytest.mark.parametrize("fault", [
    None,
    {("GET", "/emails"): [Resp(500, raw=SECRET_BODY.encode(), ctype="text/plain")]},
    {("GET", "/subscribers"): [Resp(400, {"detail": SECRET_BODY})]},
    {("GET", "/subscribers"): [Resp(200, {"results": [{"id": "x", "email_address": "jane.roe@example.com"}],
                                          "next": None, "count": 1})]},
    {("GET", "/subscribers/{id}"): [urllib.error.URLError(f"{BASE}/subscribers/sub-0001-secret")]},
    {("PATCH", "/subscribers/{id}"): [Resp(500, {"detail": SECRET_BODY, "email": "person1@example.com"})]},
    {("POST", "/emails"): [Resp(422, {"detail": SECRET_BODY})]},
    {("POST", "/emails/{id}/send-draft"): [Resp(500, raw=SECRET_BODY.encode(), ctype="text/plain")]},
    {("GET", "/emails"): [Resp(429, raw=b"", headers={"Retry-After": "1"})] * 3},
    {("GET", "/emails"): [Resp(302, raw=b"", headers={"Location": "https://evil.example/" + SECRET_BODY})]},
])
def test_no_address_id_key_or_response_body_reaches_the_output(plan, capsys, mode, fault):
    rows = people(plan)
    http = FakeHTTP(rows, faults=fault)
    raised = ""
    try:
        res, text = live(plan, http, s=settings(mode=mode))
    except Exception as exc:  # noqa: BLE001
        raised, res, text = f"{exc!r} {exc}", None, ""
    cap = capsys.readouterr()
    everything = text + cap.out + cap.err + raised + repr(res)
    assert raised == ""
    for leak in _leaks(rows):
        assert leak not in everything, leak
    assert "@" not in everything and "sub-" not in everything
    assert len(text.splitlines()) == 1


# ------------------------------------------------------------------------------------------------ the command line
@pytest.fixture()
def plan_file(plan, tmp_path):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    return p


def config_file(tmp_path, enabled: bool, canary_only=False, mode="stamp") -> Path:
    """The shipped config with the switches set and the fixture's link hosts added (the shipped file is unchanged)."""
    text = (ROOT / "config" / "site.yml").read_text(encoding="utf-8")
    text, n1 = re.subn(r"(?m)^(    enabled: )false\b", rf"\g<1>{'true' if enabled else 'false'}", text, count=1)
    text, n2 = re.subn(r"(?m)^(    canary_only: )true\b", rf"\g<1>{'true' if canary_only else 'false'}", text, count=1)
    text, n3 = re.subn(r'(?m)^(    link_hosts: ")', rf"\g<1>{TEST_HOSTS},", text, count=1)
    text, n4 = re.subn(r"(?m)^(    mode: )stamp\b", rf"\g<1>{mode}", text, count=1)
    assert (n1, n2, n3, n4) == (1, 1, 1, 1)
    p = tmp_path / "site.yml"
    p.write_text(text, encoding="utf-8")
    s = settings_mod.load(p)
    assert s.enabled is enabled
    return p


@pytest.fixture()
def cli(monkeypatch, plan):
    """`python -m sender deliver` in process, with the clock at 05:00 on the plan's day and FakeHTTP as the opener
    (a live run that tried to build a real opener would fail the test)."""
    import sender.__main__ as main_mod
    http = FakeHTTP(people(plan))
    monkeypatch.setattr(deliver, "run", functools.partial(deliver.run, now=AT_5, sleep=lambda _s: None))
    monkeypatch.setattr(bd, "make_opener", lambda: http)
    monkeypatch.delenv("BUTTONDOWN_API_KEY", raising=False)
    monkeypatch.delenv("MORNING_NOTE_CANARY_IDS", raising=False)
    return main_mod, http


def test_the_cli_key_variable_is_the_adapters():
    import sender.__main__ as main_mod
    assert main_mod.KEY_ENV == bd.KEY_ENV == "BUTTONDOWN_API_KEY"


@pytest.mark.parametrize("live_flag, enabled, key", [
    (False, False, False), (False, True, True), (False, True, False), (True, False, True), (True, False, False)])
def test_not_all_three_switches_is_a_dry_run_with_no_request(cli, plan_file, tmp_path, monkeypatch, capsys,
                                                            live_flag, enabled, key):
    main_mod, http = cli
    if key:
        monkeypatch.setenv("BUTTONDOWN_API_KEY", KEY)
    argv = ["deliver", "--plan", str(plan_file), "--config", str(config_file(tmp_path, enabled))]
    assert main_mod.main(argv + (["--live"] if live_flag else [])) == 0
    out = capsys.readouterr()
    assert "dry run, no connection opened, nothing sent" in out.out
    assert http.requests == []
    assert ("--live was passed but" in out.err) == live_flag
    assert KEY not in out.out + out.err


def test_all_three_switches_send_through_the_adapter(cli, plan, plan_file, tmp_path, monkeypatch, capsys):
    main_mod, http = cli
    monkeypatch.setenv("BUTTONDOWN_API_KEY", KEY)
    argv = ["deliver", "--plan", str(plan_file), "--config", str(config_file(tmp_path, True)), "--live"]
    assert main_mod.main(argv) == 0
    out = capsys.readouterr()
    assert out.out.strip() == f"morning note {DAY}: sent; emails created 3; recipients in total 4"
    assert len(http.calls("POST", "/emails")) == 3
    # the key is the stamps' secret: the filter carries the HMAC the deliver stage computes with it
    values = {e["filters"]["filters"][0]["value"] for e in http.email_rows if "filters" in e}
    assert values == {stamp(k) for k in {e["metadata"]["note_edition"].split(".")[1] for e in http.email_rows}}
    for leak in _leaks(people(plan)):
        assert leak not in out.out + out.err


def test_live_with_canary_only_and_no_canary_list_makes_no_request(cli, plan_file, tmp_path, monkeypatch):
    main_mod, http = cli
    monkeypatch.setenv("BUTTONDOWN_API_KEY", KEY)
    argv = ["deliver", "--plan", str(plan_file), "--config", str(config_file(tmp_path, True, canary_only=True)),
            "--live"]
    assert main_mod.main(argv) == 0 and http.requests == []


def test_live_past_latest_send_is_missed_with_no_request(cli, plan_file, tmp_path, monkeypatch):
    main_mod, http = cli
    monkeypatch.setattr(deliver, "run", functools.partial(deliver.run.func, now=datetime(2026, 11, 11, 10, 1,
                                                                                         tzinfo=TZ)))
    monkeypatch.setenv("BUTTONDOWN_API_KEY", KEY)
    argv = ["deliver", "--plan", str(plan_file), "--config", str(config_file(tmp_path, True)), "--live"]
    assert main_mod.main(argv) == deliver.MISSED_EXIT and http.requests == []


@pytest.mark.parametrize("bad", [None, "", "short", KEY + "\nX-Evil: 1", "a key with spaces in it okay"])
def test_live_and_enabled_with_a_missing_or_malformed_key_fails_without_printing_it(cli, plan_file, tmp_path,
                                                                                    monkeypatch, capsys, bad):
    """A forgotten or broken secret at go-live fails the job (exit 2), never passes as a dry run. The fixed message
    names the variable, never its value."""
    main_mod, http = cli
    if bad is not None:
        monkeypatch.setenv("BUTTONDOWN_API_KEY", bad)
    argv = ["deliver", "--plan", str(plan_file), "--config", str(config_file(tmp_path, True)), "--live"]
    assert main_mod.main(argv) == 2 and http.requests == []
    out = capsys.readouterr()
    assert "BUTTONDOWN_API_KEY" in out.err and "nothing sent" in out.err and "dry run" not in out.out + out.err
    if bad:
        assert bad not in out.out + out.err and "short" not in out.err and "spaces" not in out.err


def test_the_dry_run_cli_never_imports_the_adapter_or_any_network_module(plan_file, tmp_path):
    cfg = config_file(tmp_path, False)
    code = (
        "import sys\n"
        "from sender.__main__ import main\n"
        f"rc = main(['deliver', '--plan', {str(plan_file)!r}, '--config', {str(cfg)!r}, '--live'])\n"
        "bad = [m for m in sys.modules if m.split('.')[0] in ('socket', 'ssl', 'http', 'urllib') "
        "or m == 'sender.buttondown']\n"
        "assert rc == 0 and not bad, bad\n"
        "print('ok')\n")
    done = subprocess.run([sys.executable, "-S", "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60,
                          env={"PATH": "/usr/bin:/bin", "BUTTONDOWN_API_KEY": KEY})
    assert done.returncode == 0 and done.stdout.strip().endswith("ok"), done.stderr


# ------------------------------------------------------------------------------------------------ one module only
NETWORK_IMPORT = re.compile(r"^\s*(?:import|from)\s+(?:urllib|socket|http|ssl|requests|httpx|aiohttp|smtplib)\b",
                            re.M)


def test_buttondown_is_the_only_sender_module_that_imports_a_network_library():
    importing = sorted(p.name for p in (ROOT / "sender").glob("*.py")
                       if NETWORK_IMPORT.search(p.read_text(encoding="utf-8")))
    assert importing == ["buttondown.py"]


def test_the_adapter_imports_the_standard_library_only():
    src = (ROOT / "sender" / "buttondown.py").read_text(encoding="utf-8")
    mods = {m.split(".")[0] for m in re.findall(r"^\s*(?:from|import)\s+([\w.]+)", src, re.M)}
    assert mods <= {"", "__future__", "http", "json", "re", "ssl", "time", "urllib", "datetime", "email"}, mods
    assert not re.search(r"\bprint\(|\blogging\b|set_debuglevel|debuglevel=[1-9]", src)


def test_the_adapter_satisfies_every_provider_method():
    for name in ("emails", "subscribers", "subscriber", "set_metadata", "create_email", "unschedule", "send_draft"):
        assert getattr(bd.Buttondown, name) is not getattr(deliver.Provider, name), name


def test_settings_host_and_adapter_host_agree():
    assert bd.API_BASE == f"https://{settings_mod.PROVIDER_HOSTS['buttondown']}{settings_mod.API_PATH}"
    assert settings_mod.load(ROOT / "config" / "site.yml").api_base == bd.API_BASE
    assert dataclasses.is_dataclass(settings_mod.Settings)
