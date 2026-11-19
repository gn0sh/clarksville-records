"""tools/national/tag_probe.py (Q2, risk R-A): ADDS, REPLACES with restore, NO-CHANGE, restore failure, refusals,
no address or key in the output or on disk, the form host pinned. No network: the adapter and the form post get a
fake opener built on the adapter tests' FakeHTTP, and any socket use fails. Fixture people are made up."""
import builtins
import io
import os
import socket
import urllib.request
from urllib.parse import parse_qsl, unquote, urlsplit

import pytest

from test_morning_sender_buttondown import FakeHTTP, Resp
from tools.national import tag_probe as tp

KEY = "bd_secretkey_0123456789abcdef"
ADDR = "probe.person@example.com"
SUB = "sub_0001"
TAGS = ["note-zoning", "note-ward-3", "req-county-47125"]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a test tried to open a real connection")
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, refuse)


def person(tags=TAGS, type_="regular", email=ADDR, id_=SUB):
    return {"id": id_, "email_address": email, "type": type_, "tags": list(tags), "metadata": {"note_edition": "x"},
            "creation_date": "2026-11-18T10:00:00Z"}


class FakeButtondown(FakeHTTP):
    """FakeHTTP plus the lookup by address, PATCH of tags and the public form on buttondown.com. `form`: what a
    re-submit does to the tags ("adds", "replaces", "none", "other"); `lag`: reads after the post before it shows."""

    def __init__(self, subscribers=(), form="adds", lag=0, patch_fault=None, form_status=302, **kw):
        super().__init__(subscribers, **kw)
        self.form, self.lag, self.patch_fault, self.form_status = form, lag, patch_fault, form_status
        self.form_posts, self.pending = [], None

    def open(self, req, timeout=None):
        u = urlsplit(req.full_url)
        if u.netloc == "buttondown.com":
            assert u.scheme == "https" and u.path == "/api/emails/embed-subscribe/daylight"
            fields = parse_qsl(req.data.decode("ascii"))
            self.form_posts.append((req.get_method(), fields, {k.lower(): v for k, v in req.header_items()}, timeout))
            email = fields[0][1]
            row = next((r for r in self.subs.values() if r["email_address"] == email), None)
            if row is not None:
                new = {"adds": row["tags"] + ["req-probe"], "replaces": ["req-probe"], "none": row["tags"],
                       "other": ["note-zoning"]}[self.form]
                self.pending = [self.lag, row, new]
                self._settle()
            return Resp(self.form_status, raw=b"<html>you are subscribed, " + email.encode() + b"</html>",
                        ctype="text/html", headers={"Location": "https://buttondown.com/daylight"})
        return super().open(req, timeout)

    def _settle(self):
        if self.pending is not None:
            if self.pending[0] <= 0:
                self.pending[1]["tags"] = list(self.pending[2])
                self.pending = None
            else:
                self.pending[0] -= 1

    def answer(self, method, u, body):
        route, ident = self.route(u.path), unquote(u.path.rstrip("/").split("/")[-1])
        if (method, route) == ("GET", "/subscribers/{id}"):
            if "@" in ident:
                row = next((r for r in self.subs.values() if r["email_address"] == ident), None)
                return Resp(200, row) if row else Resp(404, {"detail": "Not found."})
            self._settle()
        if (method, route) == ("PATCH", "/subscribers/{id}") and "tags" in body:
            assert set(body) == {"tags"}
            if self.patch_fault is not None:
                return self.patch_fault
            row = self.subs[ident]
            row["tags"] = list(body["tags"])
            return Resp(200, row)
        return super().answer(method, u, body)


def run(http, capsys, argv=(), answer="yes", address=ADDR, env=None):
    sleeps = []
    code = tp.main(list(argv), env={tp.KEY_ENV: KEY} if env is None else env, opener=http,
                   ask=lambda: address, confirm=lambda _t: answer, sleep=sleeps.append, monotonic=lambda: 1000.0)
    cap = capsys.readouterr()
    for s in (ADDR, KEY, "@"):
        assert s not in cap.out + cap.err
    return code, cap.out, cap.err, sleeps


def verdicts(out):
    return [ln for ln in out.splitlines() if ln.startswith("VERDICT:")]


def test_adds_restores_and_posts_exactly_the_page_fields(capsys):
    http = FakeButtondown([person()], form="adds")
    code, out, err, sleeps = run(http, capsys)
    assert code == 0, err
    assert verdicts(out) == ["VERDICT: ADDS (old tags kept + req-probe)"]
    assert "RESTORED (tags back to the original 3)" in out
    assert http.subs[SUB]["tags"] == TAGS
    (method, fields, headers, timeout), = http.form_posts
    assert method == "POST" and fields == [("email", ADDR), ("tag", "req-probe")]
    assert headers["content-type"].startswith("application/x-www-form-urlencoded") and "authorization" not in headers
    assert timeout == tp.TIMEOUT
    patch, = http.calls("PATCH")
    assert patch[3] == {"tags": TAGS} and "x-idempotency-key" in patch[2]
    assert "note- tags: note-ward-3, note-zoning; other tags: 1; req-probe: present" in out
    assert "req-county-47125" not in out
    assert sleeps and all(s == tp.READ_GAP or s < 1 for s in sleeps)


def test_replaces_restores_the_note_tags(capsys):
    http = FakeButtondown([person()], form="replaces", lag=2)
    code, out, _err, _s = run(http, capsys)
    assert code == 0
    assert verdicts(out) == ["VERDICT: REPLACES (old tags gone)"]
    assert "after:  1 tags (note- tags: none; other tags: 0; req-probe: present)" in out
    assert "RESTORED" in out and http.subs[SUB]["tags"] == TAGS


def test_no_change_patches_nothing(capsys):
    http = FakeButtondown([person()], form="none")
    code, out, _err, sleeps = run(http, capsys)
    assert code == 0
    assert verdicts(out) == ["VERDICT: NO-CHANGE (the tags are as before)"]
    assert "no restore needed" in out and "--dry-run in a few minutes" in out and "R-A" not in out
    assert http.calls("PATCH") == [] and len(http.form_posts) == 1
    assert len(http.calls("GET", "/subscribers/{id}")) == 1 + tp.READS and len(sleeps) >= tp.READS


def test_other_change_is_unclear_and_restored(capsys):
    http = FakeButtondown([person()], form="other")
    code, out, _err, _s = run(http, capsys)
    assert code == 0 and verdicts(out) == ["VERDICT: UNCLEAR (the tags changed in another way)"]
    assert "RESTORED" in out and http.subs[SUB]["tags"] == TAGS


@pytest.mark.parametrize("fault", [Resp(500, {"detail": ADDR}), Resp(200, {"id": SUB, "type": "regular",
                                                                           "tags": ["req-probe"]})])
def test_restore_failure_prints_the_manual_fix(capsys, fault):
    http = FakeButtondown([person()], form="replaces", patch_fault=fault)
    code, out, _err, _s = run(http, capsys)
    assert code == 3
    assert "RESTORE FAILED (could not write the tags)" in out
    assert ("manual fix: in Buttondown, open this subscriber and set its tags to the original 3: note-ward-3, "
            "note-zoning, plus 1 other tag(s) not named here; remove req-probe if it is there") in out


def test_a_read_failure_after_the_post_still_restores(capsys):
    http = FakeButtondown([person()], form="replaces",
                          faults={("GET", "/subscribers/{id}"): [None, Resp(500, {})]})
    code, out, _err, _s = run(http, capsys)
    assert code == 0 and "could not read the tags after the post" in out and verdicts(out) == []
    assert "RESTORED" in out and http.subs[SUB]["tags"] == TAGS


def test_a_refused_form_post_is_reported(capsys):
    http = FakeButtondown([person()], form="none", form_status=400)
    code, out, _err, _s = run(http, capsys)
    assert code == 0 and "form post: HTTP 400 (Buttondown refused it)" in out
    assert "does not answer R-A" in out
    assert verdicts(out) == ["VERDICT: NO-CHANGE (the tags are as before)"]


@pytest.mark.parametrize("subs, text", [
    ([], "no subscriber has that address"),
    ([person(type_="unactivated")], "that subscriber is not confirmed"),
    ([person(tags=[])], "that subscriber has no tags"),
    ([person(tags=["req-county-47125"])], "that subscriber has no note- tag"),
    ([person(tags=["note-zoning", "req-probe"])], "already has req-probe"),
])
def test_refusals_post_and_change_nothing(capsys, subs, text):
    http = FakeButtondown(subs)
    code, out, err, _s = run(http, capsys)
    assert code == 1 and text in err and "nothing was changed" in err and out == ""
    assert http.form_posts == [] and http.calls("PATCH") == []


def test_a_lookup_answering_another_subscriber_is_refused(capsys):
    other = person(email="someone.else@example.com")
    http = FakeButtondown([other], faults={("GET", "/subscribers/{id}"): [Resp(200, other)]})
    code, _out, err, _s = run(http, capsys)
    assert code == 1 and err == "error: could not look the address up in Buttondown\n"
    assert http.form_posts == []


def test_no_unless_yes(capsys):
    http = FakeButtondown([person()])
    code, out, _err, _s = run(http, capsys, answer="y")
    assert code == 0 and "stopped: nothing was posted or changed" in out
    assert http.form_posts == [] and http.calls("PATCH") == []


def test_dry_run_reads_only(capsys):
    http = FakeButtondown([person()])
    code, out, _err, _s = run(http, capsys, ["--dry-run"], answer="should not be asked")
    assert code == 0 and "dry run: nothing was posted or changed" in out
    assert "3 tags (note- tags: note-ward-3, note-zoning; other tags: 1; req-probe: absent)" in out
    assert http.form_posts == [] and [r[0] for r in http.requests] == ["GET"]
    assert "%40" in http.requests[0][1]


@pytest.mark.parametrize("address", ["", "not-an-address", "a/b@example.com", "a..b@example.com", "x@y",
                                     "a@b.com\r\nHost: evil", "a%40b@example.com"])
def test_bad_addresses_are_refused_before_any_request(capsys, address):
    http = FakeButtondown([person()])
    code = tp.main([], env={tp.KEY_ENV: KEY}, opener=http, ask=lambda: address, confirm=lambda _t: "yes",
                   sleep=lambda _s: None)
    cap = capsys.readouterr()
    assert code == 2 and http.requests == [] and http.form_posts == []
    assert address.strip() == "" or address not in cap.out + cap.err


def test_needs_key(capsys):
    assert tp.main([], env={}, ask=lambda: ADDR) == 2
    assert tp.main([], env={tp.KEY_ENV: "short"}, ask=lambda: ADDR) == 2
    assert "short" not in capsys.readouterr().err


@pytest.mark.parametrize("fault, text", [
    (Resp(401, {"detail": ADDR}), "Buttondown refused the key (check it)"),
    (Resp(429, {}, headers={"Retry-After": "30"}), "Buttondown asked to slow down; try again in a minute"),
    (OSError("reset " + ADDR + " " + KEY), "could not look the address up in Buttondown"),
])
def test_lookup_errors_are_fixed_text(capsys, fault, text):
    http = FakeButtondown([person()], faults={("GET", "/subscribers/{id}"): [fault]})
    code, out, err, _s = run(http, capsys)
    assert code == 1 and out == "" and err == f"error: {text}\n"


def test_form_post_refuses_a_foreign_host(monkeypatch):
    seen = []

    class Opener:
        def open(self, req, timeout=None):
            seen.append(req)
            raise AssertionError("the post left the pinned host")
    for url in ("https://evil.example/api/emails/embed-subscribe/daylight",
                "http://buttondown.com/api/emails/embed-subscribe/daylight",
                "https://buttondown.com/api/emails/embed-subscribe/other"):
        monkeypatch.setattr(tp, "FORM_URL", url)
        with pytest.raises(tp.ProviderError, match="off the pinned host"):
            tp.post_form(Opener(), ADDR)
    assert seen == []


def test_the_form_post_follows_no_redirect_and_uses_the_adapter_opener():
    od = tp.make_opener()
    assert not any(isinstance(h, (urllib.request.HTTPRedirectHandler, urllib.request.ProxyHandler))
                   for h in od.handlers)
    http = FakeButtondown([person()])
    assert tp.post_form(http, ADDR) == 302          # the 302 comes back as is; nothing else is requested
    assert http.requests == [] and len(http.form_posts) == 1


def test_connection_failure_of_the_post_is_fixed_text_and_still_checked(capsys):
    class Breaks(FakeButtondown):
        def open(self, req, timeout=None):
            if urlsplit(req.full_url).netloc == "buttondown.com":
                raise OSError("reset " + ADDR)
            return super().open(req, timeout)
    http = Breaks([person()])
    code, out, _err, _s = run(http, capsys)
    assert code == 0 and "form post: the connection failed" in out and "does not answer R-A" in out
    assert verdicts(out) == ["VERDICT: NO-CHANGE (the tags are as before)"]


def test_nothing_written_to_disk(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    writes = []

    def guard(real):
        def opener(file, mode="r", *a, **k):
            if any(c in mode for c in "wax+"):
                writes.append(str(file))
                raise AssertionError("main() opened a file for writing")
            return real(file, mode, *a, **k)
        return opener

    def os_guard(path, flags, *a, **k):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
            writes.append(str(path))
            raise AssertionError("main() opened a file for writing")
        return real_os_open(path, flags, *a, **k)

    real_os_open = os.open
    monkeypatch.setattr(builtins, "open", guard(builtins.open))
    monkeypatch.setattr(io, "open", guard(io.open))
    monkeypatch.setattr(os, "open", os_guard)
    http = FakeButtondown([person()], form="replaces")
    code, out, _err, _s = run(http, capsys)
    monkeypatch.undo()
    assert code == 0 and writes == [] and list(tmp_path.iterdir()) == []
    assert "RESTORED" in out


def test_help_says_once_brians_pc_live_and_restore(capsys):
    with pytest.raises(SystemExit):
        tp.main(["--help"])
    out = " ".join(capsys.readouterr().out.split())
    for s in ("ONCE on Brian's PC", "LIVE daylight newsletter", "ONE team address", "tag=req-probe",
              "restores the original tags", "--dry-run", tp.KEY_STEP, "Remove-Item Env:BUTTONDOWN_API_KEY"):
        assert s in out
    assert "BUTTONDOWN_API_KEY=" not in out


def test_docstring_steps_never_put_the_key_on_a_command_line():
    doc = tp.__doc__
    assert "BUTTONDOWN_API_KEY=" not in doc
    for step in (tp.KEY_STEP, "python -I tools\\national\\tag_probe.py --dry-run", "Remove-Item Env:BUTTONDOWN_API_KEY"):
        assert step in doc


def test_verdict_table():
    assert tp.verdict(["a"], ["a"]) == "NO-CHANGE"
    assert tp.verdict(["a"], ["a", "req-probe"]) == "ADDS"
    assert tp.verdict(["a", "b"], ["b", "req-probe"]) == "REPLACES"
    assert tp.verdict(["a"], ["req-probe"]) == "REPLACES"
    assert tp.verdict(["a"], ["a", "req-probe", "c"]) == "UNCLEAR"
    assert tp.verdict(["a"], []) == "UNCLEAR"
