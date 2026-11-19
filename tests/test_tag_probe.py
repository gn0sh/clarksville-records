"""tools/national/tag_probe.py (Q2, risk R-A): ADDS, REPLACES with restore, NO-CHANGE and the late re-check,
metadata checks, restore failure, --restore-tags, refusals, no address or key in the output or on disk, the form
host pinned. No network: the adapter and the form post get a fake opener built on the adapter tests' FakeHTTP, and
any socket use fails. Fixture people are made up."""
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
META = {"note_edition": "2026-11-18.abc.def"}
FIX_CMD = 'python -I tools\\national\\tag_probe.py --restore-tags "note-ward-3,note-zoning,req-county-47125"'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a test tried to open a real connection")
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, refuse)


def person(tags=TAGS, type_="regular", email=ADDR, id_=SUB, meta=META):
    return {"id": id_, "email_address": email, "type": type_, "tags": list(tags), "metadata": dict(meta),
            "creation_date": "2026-11-18T10:00:00Z"}


class FakeButtondown(FakeHTTP):
    """FakeHTTP plus the lookup by address, PATCH of tags and the public form on buttondown.com.
    `form`: what a re-submit does to the tags ("adds", "replaces", "none", "other"); `lag`: reads of the subscriber
    after the post before it shows; `post_meta` / `patch_meta`: the metadata the post / a tags PATCH leaves (None:
    untouched); `post_type`: the type the post leaves; `location`: the 302's Location."""

    def __init__(self, subscribers=(), form="adds", lag=0, patch_fault=None, form_status=302, post_meta=None,
                 patch_meta=None, post_type=None, patch_ignores=False,
                 location="https://buttondown.com/daylight/subscribed", **kw):
        super().__init__(subscribers, **kw)
        self.form, self.lag, self.patch_fault, self.form_status = form, lag, patch_fault, form_status
        self.post_meta, self.patch_meta, self.post_type = post_meta, patch_meta, post_type
        self.patch_ignores, self.location = patch_ignores, location
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
            headers = {"Location": self.location} if self.location else {}
            return Resp(self.form_status, raw=b"<html>you are subscribed, " + email.encode() + b"</html>",
                        ctype="text/html", headers=headers)
        return super().open(req, timeout)

    def _settle(self):
        if self.pending is not None:
            if self.pending[0] <= 0:
                row = self.pending[1]
                row["tags"] = list(self.pending[2])
                if self.post_meta is not None:
                    row["metadata"] = dict(self.post_meta)
                if self.post_type is not None:
                    row["type"] = self.post_type
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
            if self.patch_ignores:
                return Resp(200, {**row, "tags": list(body["tags"])})     # echoes the list, stores nothing
            row["tags"] = list(body["tags"])
            if self.patch_meta is not None:
                row["metadata"] = dict(self.patch_meta)
            return Resp(200, row)
        return super().answer(method, u, body)


def run(http, capsys, argv=(), answers=("yes", "yes"), address=ADDR, again=None, env=None):
    sleeps, asked, typed = [], [], [address, address if again is None else again]
    replies = list(answers)

    def confirm(text):
        asked.append(text)
        return replies.pop(0) if replies else ""

    code = tp.main(list(argv), env={tp.KEY_ENV: KEY} if env is None else env, opener=http,
                   ask=lambda _p: typed.pop(0), confirm=confirm, sleep=sleeps.append, monotonic=lambda: 1000.0)
    cap = capsys.readouterr()
    for s in (ADDR, KEY, "@", META["note_edition"]):
        assert s not in cap.out + cap.err
    return code, cap.out, cap.err, sleeps, asked


def verdicts(out):
    return [ln for ln in out.splitlines() if ln.startswith("VERDICT")]


def V(kind):
    return f"VERDICT (server-side post): {tp.VERDICTS[kind]}"


def test_adds_restores_and_posts_exactly_the_page_fields(capsys):
    http = FakeButtondown([person()], form="adds")
    code, out, err, sleeps, _a = run(http, capsys)
    assert code == 0, err
    assert verdicts(out) == [V("ADDS")]
    assert "metadata: unchanged" in out
    assert "RESTORED (tags, metadata and type equal the snapshot; 3 tags)" in out
    assert http.subs[SUB]["tags"] == TAGS
    (method, fields, headers, timeout), = http.form_posts
    assert method == "POST" and fields == [("email", ADDR), ("tag", "req-probe")]
    assert headers["content-type"].startswith("application/x-www-form-urlencoded") and "authorization" not in headers
    assert headers["origin"] == "https://daylight.gnoshcodes.com" and "referer" not in headers
    assert timeout == tp.TIMEOUT
    assert "form post (server-side): HTTP 302, Location /daylight\n" in out and "subscribed" not in out
    patch, = http.calls("PATCH")
    assert patch[3] == {"tags": TAGS} and "x-idempotency-key" in patch[2]
    assert "after:  4 tags (note-ward-3, note-zoning, req-county-47125, req-probe; req-probe: present)" in out
    assert sleeps and all(s == tp.READ_GAP or s < 1 for s in sleeps)
    # the restore is checked by a fresh read after the PATCH
    assert http.calls()[-1][0] == "GET" and http.calls()[-2][0] == "PATCH"


def test_replaces_restores_the_note_tags(capsys):
    http = FakeButtondown([person()], form="replaces", lag=2)
    code, out, _err, _s, _a = run(http, capsys)
    assert code == 0
    assert verdicts(out) == [V("REPLACES")]
    assert "after:  1 tags (req-probe; req-probe: present)" in out
    assert "RESTORED" in out and http.subs[SUB]["tags"] == TAGS


def test_no_change_rechecks_once_and_patches_nothing(capsys):
    http = FakeButtondown([person()], form="none")
    code, out, _err, sleeps, asked = run(http, capsys)
    assert code == 0
    assert verdicts(out) == [V("NO-CHANGE")]
    assert "inconclusive until R-B's live-page post" in out and "does not answer R-A at all" not in out
    assert "UNCHANGED (tags, metadata and type equal the snapshot; nothing to restore)" in out
    assert "manual fix (only if a later --dry-run shows req-probe)" in out and FIX_CMD in out
    assert http.calls("PATCH") == [] and len(http.form_posts) == 1
    assert len(asked) == 2 and "2 minutes" in asked[1]
    assert sum(sleeps) >= tp.READS * tp.READ_GAP + tp.RECHECK_WAIT
    assert len(http.calls("GET", "/subscribers/{id}")) == 1 + tp.READS + 2 + 1


def test_a_late_change_is_caught_by_the_recheck_and_restored(capsys):
    http = FakeButtondown([person()], form="replaces", lag=tp.READS + 1)     # shows only after the first reads
    code, out, _err, _s, _a = run(http, capsys)
    assert code == 0 and "no change seen yet" in out
    assert verdicts(out) == [V("REPLACES")]
    assert "RESTORED" in out and http.subs[SUB]["tags"] == TAGS


def test_a_late_change_without_the_recheck_is_left_to_the_fix_line(capsys):
    http = FakeButtondown([person()], form="replaces", lag=tp.READS + 5)
    code, out, _err, _s, asked = run(http, capsys, answers=("yes", "no"))
    assert code == 0 and verdicts(out) == [V("NO-CHANGE")] and len(asked) == 2
    assert FIX_CMD in out and http.calls("PATCH") == []


def test_a_late_change_seen_only_by_the_last_read_is_restored(capsys):
    http = FakeButtondown([person()], form="replaces", lag=tp.READS + 1)
    code, out, _err, _s, _a = run(http, capsys, answers=("yes", "no"))
    assert code == 0 and verdicts(out) == [V("NO-CHANGE")]
    assert "a late change showed in the last read: restoring" in out and "RESTORED" in out
    assert len(http.calls("PATCH")) == 1 and http.subs[SUB]["tags"] == TAGS


def test_other_change_is_unclear_and_restored(capsys):
    http = FakeButtondown([person()], form="other")
    code, out, _err, _s, _a = run(http, capsys)
    assert code == 0 and verdicts(out) == [V("UNCLEAR")]
    assert "RESTORED" in out and http.subs[SUB]["tags"] == TAGS


def test_metadata_dropped_by_the_post_is_reported_and_exits_3(capsys):
    http = FakeButtondown([person()], form="adds", post_meta={})
    code, out, _err, _s, _a = run(http, capsys)
    assert code == 3 and verdicts(out) == [V("ADDS")]
    assert "metadata: CHANGED (1 keys before, 0 after; note_edition lost)" in out
    assert "RESTORE INCOMPLETE (the tags are the original ones; see below)" in out
    assert tp.METADATA_FIX in out and "RESTORED" not in out
    assert http.subs[SUB]["tags"] == TAGS


def test_metadata_dropped_by_the_restore_patch_is_reported_and_exits_3(capsys):
    http = FakeButtondown([person()], form="replaces", patch_meta={})
    code, out, _err, _s, _a = run(http, capsys)
    assert code == 3 and verdicts(out) == [V("REPLACES")]
    assert "metadata: unchanged" in out                      # the post kept it
    assert "metadata: CHANGED (1 keys before, 0 after; note_edition lost) (in the restore's echo)" in out
    assert "metadata: CHANGED (1 keys before, 0 after; note_edition lost) (fresh read)" in out
    assert "RESTORE INCOMPLETE" in out and tp.METADATA_FIX in out and "RESTORED" not in out


def test_the_metadata_fix_says_run_when_no_note_is_scheduled():
    assert "Run this probe only when no morning note is scheduled" in tp.METADATA_FIX


def test_the_fresh_read_after_a_restore_waits_first(capsys):
    events = []

    class Logged(FakeButtondown):
        def open(self, req, timeout=None):
            events.append(req.get_method())
            return super().open(req, timeout)
    http = Logged([person()], form="replaces")
    code = tp.main([], env={tp.KEY_ENV: KEY}, opener=http, ask=lambda _p: ADDR, confirm=lambda _t: "yes",
                   sleep=lambda s: events.append(s), monotonic=lambda: 1000.0)
    capsys.readouterr()
    assert code == 0
    i = events.index("PATCH")
    tail = events[i + 1:]                    # the adapter's own 0.2 s pacing may sit between them
    assert tail[0] == tp.READ_GAP and tail[-1] == "GET" and tail.count("GET") == 1


def test_a_type_change_prints_the_fix_and_exits_3(capsys):
    http = FakeButtondown([person()], form="adds", post_type="unactivated")
    code, out, _err, _s, _a = run(http, capsys)
    assert code == 3
    assert "type: CHANGED to unactivated, not regular" in out and tp.TYPE_FIX in out and "RESTORED" not in out


@pytest.mark.parametrize("fault", [Resp(500, {"detail": ADDR}), Resp(200, {"id": SUB, "type": "regular",
                                                                           "tags": ["req-probe"]})])
def test_restore_failure_prints_the_exact_fix(capsys, fault):
    http = FakeButtondown([person()], form="replaces", patch_fault=fault)
    code, out, _err, _s, _a = run(http, capsys)
    assert code == 3
    assert "RESTORE FAILED (could not write the tags): now 1 tags (req-probe; req-probe: present)" in out
    assert FIX_CMD in out
    assert ("or in Buttondown, open this subscriber and set its tags to exactly these 3: note-ward-3, note-zoning, "
            "req-county-47125 (remove req-probe if it is there)") in out


def test_a_patch_echo_that_was_not_stored_fails_on_the_fresh_read(capsys):
    http = FakeButtondown([person()], form="replaces", patch_ignores=True)
    code, out, _err, _s, _a = run(http, capsys)
    assert code == 3 and "RESTORE FAILED (a fresh read shows other tags)" in out and "RESTORED" not in out


def test_a_rate_limit_before_the_patch_is_waited_out(capsys):
    http = FakeButtondown([person()], form="replaces",
                          faults={("PATCH", "/subscribers/{id}"): [Resp(429, {}, headers={"Retry-After": "17"})]})
    code, out, _err, sleeps, _a = run(http, capsys)
    assert code == 0 and "RESTORED" in out and 17.0 in sleeps
    assert len(http.calls("PATCH")) == 2
    assert http.calls("PATCH")[0][2]["x-idempotency-key"] == http.calls("PATCH")[1][2]["x-idempotency-key"]


def test_a_read_failure_after_the_post_still_restores(capsys):
    http = FakeButtondown([person()], form="replaces",
                          faults={("GET", "/subscribers/{id}"): [None, Resp(500, {})]})
    code, out, _err, _s, _a = run(http, capsys)
    assert code == 0 and "could not read the subscriber after the post" in out and verdicts(out) == []
    assert "RESTORED" in out and http.subs[SUB]["tags"] == TAGS


def test_an_unexpected_exception_after_the_post_still_restores(capsys):
    http = FakeButtondown([person()], form="replaces",
                          faults={("GET", "/subscribers/{id}"): [None, RuntimeError("boom " + ADDR)]})
    code, out, _err, _s, _a = run(http, capsys)
    assert code == 0 and "an unexpected error" in out and "boom" not in out
    assert "RESTORED" in out and http.subs[SUB]["tags"] == TAGS


def test_ctrl_c_after_the_post_still_restores(capsys):
    http = FakeButtondown([person()], form="replaces",
                          faults={("GET", "/subscribers/{id}"): [None, KeyboardInterrupt()]})
    code, out, _err, _s, _a = run(http, capsys)
    assert code == 0 and "interrupted: restoring" in out and "RESTORED" in out


def test_a_refused_form_post_is_reported(capsys):
    http = FakeButtondown([person()], form="none", form_status=400, location=None)
    code, out, _err, _s, _a = run(http, capsys, answers=("yes", "no"))
    assert code == 0 and "form post (server-side): HTTP 400, Location (none) (Buttondown refused it)" in out
    assert "does not answer R-A at all" in out
    assert verdicts(out) == [V("NO-CHANGE")]


@pytest.mark.parametrize("loc, shown", [
    ("https://buttondown.com/daylight?email=" + ADDR, "(other path)"),
    ("https://buttondown.com/daylight/" + ADDR, "(other path)"),
    ("https://buttondown.com/daylight/probe.person%40example.com", "(other path)"),
    ("https://buttondown.com/daylight/x#frag", "(other path)"),
    ("https://buttondown.com/da ylight", "(other path)"),
    ("https://buttondown.com/", "(other path)"),
    ("https://buttondown.com/../x", "(other path)"),
    ("https://buttondown.com/daylight/subscribed/tok_9f8e7d6c5b4a", "/daylight"),
    ("/daylight/confirmed", "/daylight"),
    ("https://buttondown.com/daylight", "/daylight"),
])
def test_the_location_is_a_path_or_not_shown(loc, shown):
    assert tp.location_path(loc) == shown


def test_unsafe_tag_names_are_printed_escaped():
    assert tp.describe(["note-a", "evil\x1b[2J", "Big Tag"]) == \
        "3 tags ('Big Tag', 'evil\\x1b[2J', note-a; req-probe: absent)"
    lines = tp.manual_fix(["note-a", "Big Tag"])
    assert len(lines) == 1 and "--restore-tags" not in lines[0] and "'Big Tag'" in lines[0]


@pytest.mark.parametrize("subs, text", [
    ([], "Buttondown answered 404"),
    ([person(type_="unactivated")], "that subscriber is not confirmed"),
    ([person(tags=[])], "that subscriber has no tags"),
    ([person(tags=["req-county-47125"])], "that subscriber has no note- tag"),
    ([person(tags=["note-zoning", "req-probe"])], "already has req-probe"),
])
def test_refusals_post_and_change_nothing(capsys, subs, text):
    http = FakeButtondown(subs)
    code, out, err, _s, _a = run(http, capsys)
    assert code == 1 and text in err and "nothing was changed" in err and out == ""
    assert http.form_posts == [] and http.calls("PATCH") == []


def test_the_404_text_says_the_lookup_may_not_exist(capsys):
    code, _out, err, _s, _a = run(FakeButtondown([]), capsys)
    assert code == 1 and "does not look subscribers up by address" in err


def test_a_typo_in_the_second_address_stops_before_any_request(capsys):
    http = FakeButtondown([person()])
    code, out, err, _s, asked = run(http, capsys, again="probe.persn@example.com")
    assert code == 2 and "the two addresses typed differ" in err and out == ""
    assert http.requests == [] and http.form_posts == [] and asked == []
    assert "probe.persn" not in err


def test_a_lookup_answering_another_subscriber_is_refused(capsys):
    other = person(email="someone.else@example.com")
    http = FakeButtondown([other], faults={("GET", "/subscribers/{id}"): [Resp(200, other)]})
    code, _out, err, _s, _a = run(http, capsys)
    assert code == 1 and err == "error: could not look the address up in Buttondown\n"
    assert http.form_posts == []


def test_no_unless_yes(capsys):
    http = FakeButtondown([person()])
    code, out, _err, _s, _a = run(http, capsys, answers=("y",))
    assert code == 0 and "stopped: nothing was posted or changed" in out
    assert http.form_posts == [] and http.calls("PATCH") == []


def test_dry_run_reads_only(capsys):
    http = FakeButtondown([person()])
    code, out, _err, _s, asked = run(http, capsys, ["--dry-run"])
    assert code == 0 and "dry run: nothing was posted or changed" in out and asked == []
    assert "3 tags (note-ward-3, note-zoning, req-county-47125; req-probe: absent)" in out
    assert "metadata keys: 1" in out
    assert http.form_posts == [] and [r[0] for r in http.requests] == ["GET"]
    assert "%40" in http.requests[0][1]


def test_restore_tags_sets_exactly_the_list_and_rereads(capsys):
    http = FakeButtondown([person(tags=["req-probe"])])
    code, out, _err, _s, asked = run(http, capsys, ["--restore-tags", "note-zoning, note-ward-3,req-county-47125"],
                                     answers=("yes",))
    assert code == 0, out
    assert "RESTORED (tags set to the 3 given: note-ward-3, note-zoning, req-county-47125)" in out
    assert set(http.subs[SUB]["tags"]) == set(TAGS) and http.form_posts == []
    assert len(asked) == 1 and "1 tags now" in asked[0]
    assert [r[0] for r in http.requests] == ["GET", "PATCH", "GET"]


def test_restore_tags_works_for_an_unconfirmed_subscriber_but_says_so(capsys):
    http = FakeButtondown([person(tags=["req-probe"], type_="unactivated")])
    code, out, _err, _s, _a = run(http, capsys, ["--restore-tags", "note-zoning"], answers=("yes",))
    assert code == 3 and "RESTORED" in out and tp.TYPE_FIX in out


@pytest.mark.parametrize("raw", ["", "note-a,,note-b", "Note-A", "note a", "note-a;rm"])
def test_restore_tags_refuses_bad_names(capsys, raw):
    http = FakeButtondown([person()])
    code, _out, err, _s, _a = run(http, capsys, ["--restore-tags", raw])
    assert code == 2 and "--restore-tags takes tag names" in err and http.calls("PATCH") == []


def test_restore_tags_failure_prints_the_fix(capsys):
    http = FakeButtondown([person(tags=["req-probe"])], patch_ignores=True)
    code, out, _err, _s, _a = run(http, capsys, ["--restore-tags", "note-zoning"], answers=("yes",))
    assert code == 3 and "RESTORE FAILED (a fresh read shows other tags)" in out and "--restore-tags" in out


def test_restore_tags_and_dry_run_do_not_mix(capsys):
    with pytest.raises(SystemExit):
        tp.main(["--dry-run", "--restore-tags", "note-a"], env={tp.KEY_ENV: KEY}, ask=lambda _p: ADDR)


@pytest.mark.parametrize("address", ["", "not-an-address", "a/b@example.com", "a..b@example.com", "x@y",
                                     "a@b.com\r\nHost: evil", "a%40b@example.com"])
def test_bad_addresses_are_refused_before_any_request(capsys, address):
    http = FakeButtondown([person()])
    code = tp.main([], env={tp.KEY_ENV: KEY}, opener=http, ask=lambda _p: address, confirm=lambda _t: "yes",
                   sleep=lambda _s: None)
    cap = capsys.readouterr()
    assert code == 2 and http.requests == [] and http.form_posts == []
    assert address.strip() == "" or address not in cap.out + cap.err


def test_needs_key(capsys):
    assert tp.main([], env={}, ask=lambda _p: ADDR) == 2
    assert tp.main([], env={tp.KEY_ENV: "short"}, ask=lambda _p: ADDR) == 2
    assert "short" not in capsys.readouterr().err


@pytest.mark.parametrize("fault, text", [
    (Resp(401, {"detail": ADDR}), "Buttondown refused the key (check it)"),
    (OSError("reset " + ADDR + " " + KEY), "could not look the address up in Buttondown"),
])
def test_lookup_errors_are_fixed_text(capsys, fault, text):
    http = FakeButtondown([person()], faults={("GET", "/subscribers/{id}"): [fault]})
    code, out, err, _s, _a = run(http, capsys)
    assert code == 1 and out == "" and err == f"error: {text}\n"


def test_a_lookup_rate_limit_is_waited_out_then_gives_up(capsys):
    limited = Resp(429, {}, headers={"Retry-After": "30"})
    http = FakeButtondown([person()], faults={("GET", "/subscribers/{id}"): [limited] * tp.RATE_TRIES})
    code, out, err, sleeps, _a = run(http, capsys)
    assert code == 1 and out == "" and err == "error: Buttondown asked to slow down; try again in a minute\n"
    assert sleeps.count(30.0) == tp.RATE_TRIES - 1


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
    assert tp.post_form(http, ADDR) == (302, "/daylight")    # the 302 comes back as is; first segment only
    assert http.requests == [] and len(http.form_posts) == 1


def test_connection_failure_of_the_post_is_fixed_text_and_still_checked(capsys):
    class Breaks(FakeButtondown):
        def open(self, req, timeout=None):
            if urlsplit(req.full_url).netloc == "buttondown.com":
                raise OSError("reset " + ADDR)
            return super().open(req, timeout)
    http = Breaks([person()])
    code, out, _err, _s, _a = run(http, capsys, answers=("yes", "no"))
    assert code == 0 and "form post (server-side): the connection failed" in out and "does not answer R-A" in out
    assert verdicts(out) == [V("NO-CHANGE")]


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
    code, out, _err, _s, _a = run(http, capsys)
    monkeypatch.undo()
    assert code == 0 and writes == [] and list(tmp_path.iterdir()) == []
    assert "RESTORED" in out


def test_help_says_once_brians_pc_live_and_restore(capsys):
    with pytest.raises(SystemExit):
        tp.main(["--help"])
    out = " ".join(capsys.readouterr().out.split())
    for s in ("ONCE on Brian's PC", "LIVE daylight newsletter", "ONE team address", "tag=req-probe", "server-side",
              "restores the original tags", "--dry-run", "--restore-tags", "typed hidden, twice", tp.KEY_STEP,
              "Remove-Item Env:BUTTONDOWN_API_KEY"):
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
