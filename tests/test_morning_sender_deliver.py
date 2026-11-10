# ruff: noqa: E501
"""The morning note sender's deliver stage against an in-memory fake provider (T4.4: sender/deliver.py; ADR 0004).
No test opens a connection: this package has no provider client. Every subscriber here is made up, with an
address at example.com, and the tests assert that none of it ever reaches the output."""
import contextlib
import copy
import dataclasses
import io
import socket
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sitegen import config
from sender import common, deliver, plan as plan_mod, settings as settings_mod
from test_morning import D, inputs  # noqa: F401
from test_morning_sender_plan import TEST_HOSTS, cfg_with, msite  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("America/Chicago")
DAY = D.isoformat()
AT_5 = datetime(2026, 11, 11, 5, 0, tzinfo=TZ)            # the run ends before send_at (07:00)
SECRET_BODY = "RESPONSE-BODY-WITH-jane.roe@example.com"
SECRET = b"made-up-test-key-not-a-real-one"     # the HMAC key of the stamps (live: the provider's API key)


def stamp(key: str, day: str = DAY) -> str:
    return deliver.stamp_value(day, key, SECRET)


def settings(**kw) -> settings_mod.Settings:
    base = settings_mod.load(ROOT / "config" / "site.yml")
    hosts = base.link_hosts + tuple(TEST_HOSTS.split(","))
    return dataclasses.replace(base, **{"enabled": True, "canary_only": False, "link_hosts": hosts, **kw})


def sub(n: int, lists=("budget",), district=None, ward=None, type_="regular", **meta) -> dict:
    """A made-up subscriber as a provider would return one, with the fields the sender must never keep."""
    md = {"lists": list(lists), **meta}
    if district is not None:
        md["district"] = district
    if ward is not None:
        md["ward"] = ward
    return {"id": f"sub-{n:04d}-secret", "email_address": f"person{n}@example.com", "type": type_, "metadata": md,
            "ip_address": "192.0.2.10", "notes": "made-up fixture person"}


class Fake(deliver.Provider):
    """An in-memory provider. `fail`: {method name: exception or [exceptions, then success]}."""

    def __init__(self, subscribers=(), emails=(), fail=None, echo=None):
        self.echo = echo        # echo(stored row) -> what create_email returns: a provider that stored something else
        self.stuck = False      # unschedule() answers but the email stays scheduled
        self.after_listing = None
        self.unscheduled = []
        self.subs = {s["id"]: copy.deepcopy(s) for s in subscribers}
        self.email_rows = [copy.deepcopy(e) for e in emails]
        self.fail = {k: (list(v) if isinstance(v, list) else v) for k, v in (fail or {}).items()}
        self.calls, self.created, self.sent_drafts, self.keys = [], [], [], []

    def _hit(self, name):
        self.calls.append(name)
        f = self.fail.get(name)
        if isinstance(f, list):
            if f:
                e = f.pop(0)
                if e is not None:
                    raise e
        elif f is not None:
            raise f

    def emails(self):
        self._hit("emails")
        return copy.deepcopy(self.email_rows)

    def subscribers(self):
        self._hit("subscribers")
        rows = copy.deepcopy(list(self.subs.values()))
        if self.after_listing:
            self.after_listing(self.subs)       # what subscribers change between the listing and the writes
        return rows

    def subscriber(self, subscriber_id):
        self._hit("subscriber")
        return copy.deepcopy(self.subs.get(subscriber_id))

    def set_metadata(self, subscriber_id, metadata, idempotency_key):
        self._hit("set_metadata")
        self.keys.append(idempotency_key)
        self.subs[subscriber_id]["metadata"] = copy.deepcopy(metadata)

    def create_email(self, payload, idempotency_key):
        self._hit("create_email")
        self.keys.append(idempotency_key)
        row = {"id": f"em-{len(self.email_rows) + 1}", "status": payload["status"],
               "metadata": copy.deepcopy(payload["metadata"])}
        if "filters" in payload:
            row["filters"] = copy.deepcopy(payload["filters"])
        self.email_rows.append(row)
        self.created.append(copy.deepcopy(payload))
        return self.echo(copy.deepcopy(row)) if self.echo else copy.deepcopy(row)

    def unschedule(self, email_id, idempotency_key):
        self._hit("unschedule")
        self.keys.append(idempotency_key)
        self.unscheduled.append(email_id)
        for row in self.email_rows:
            if row["id"] == email_id:
                if not self.stuck:
                    row["status"] = "draft"
                return copy.deepcopy(row)
        return None

    def send_draft(self, email_id, subscriber_ids, idempotency_key):
        self._hit("send_draft")
        self.keys.append(idempotency_key)
        self.sent_drafts.append((email_id, list(subscriber_ids)))

    def audience(self, payload) -> set:
        """Who a created `stamp` email reaches, as the provider would work it out from its filter."""
        rules = payload["filters"]["filters"]
        assert payload["filters"]["predicate"] == "and" and payload["filters"]["groups"] == [] and len(rules) == 1
        r = rules[0]
        assert r["field"] == "subscriber.metadata.note_edition" and r["operator"] == "equals"
        return {s["id"] for s in self.subs.values() if s["metadata"].get("note_edition") == r["value"]}


@pytest.fixture(scope="module")
def plan(msite):  # noqa: F811
    return plan_mod.build(msite, D, cfg_with())["plan"]


def key_for(plan, lists, district=None, ward=None) -> str:
    return plan["signatures"][common.signature(lists, district, ward)]


def people(plan) -> list[dict]:
    """Made-up subscribers over three editions, and three who must get nothing."""
    assert len({key_for(plan, ["budget"]), key_for(plan, ["contracts"]), key_for(plan, ["budget", "contracts"])}) == 3
    return [sub(1, ["budget"]), sub(2, ["budget"], district=7), sub(3, ["contracts"]),
            sub(4, ["budget", "contracts"], ward=3, favourite="blue"),
            sub(5, ["budget"], type_="unactivated"), sub(6, ["contracts"], type_="unsubscribed"),
            sub(7, [])]                                                # confirmed, but picked no list


def go(plan, provider, s=None, now=AT_5, live=True, sleeps=None, canary_ids=None, secret=SECRET, clock=None):
    lines = []
    res = deliver.run(plan, s or settings(), provider=provider, live=live, now=now, canary_ids=canary_ids,
                      stamp_secret=secret, clock=clock,
                      sleep=(sleeps.append if sleeps is not None else lambda _s: None), out=lines.append)
    return res, "\n".join(lines)


# ------------------------------------------------------------------ nothing happens unless everything says go
def test_without_live_no_provider_call_at_all(plan):
    fake = Fake(people(plan))
    res, text = go(plan, fake, live=False)
    assert res == deliver.Outcome(0, "dry-run") and fake.calls == []
    assert "dry run, no connection opened, nothing sent" in text and f"{len(plan['editions'])} edition(s)" in text


def test_live_with_send_false_makes_no_provider_call(plan):
    for reason in ("quiet", "backfill", "disabled"):
        fake = Fake(people(plan))
        res, _ = go({**plan, "send": False, "reason": reason}, fake)
        assert (res.code, res.status, res.editions) == (0, "no-send", 0) and fake.calls == []


def test_a_disabled_config_sends_nothing_even_with_a_send_true_plan(plan):
    fake = Fake(people(plan))
    res, text = go(plan, fake, s=settings(enabled=False))
    assert (res.code, res.status, res.editions, res.recipients) == (0, "disabled", 0, 0) and fake.calls == []
    assert "emails created 0; recipients in total 0" in text
    shipped = settings_mod.load(ROOT / "config" / "site.yml")           # the repository as it is: off
    shipped = dataclasses.replace(shipped, link_hosts=settings().link_hosts)   # (the made-up site's links)
    assert shipped.enabled is False and go(plan, fake, s=shipped)[0].status == "disabled" and fake.calls == []


def test_live_without_a_provider_sends_nothing(plan):
    res, _ = go(plan, None)
    assert (res.code, res.status) == (2, "no-provider")


@pytest.mark.parametrize("now", [AT_5 - timedelta(days=1), AT_5 + timedelta(days=1),
                                 datetime(2026, 11, 12, 5, 30, tzinfo=ZoneInfo("UTC"))])   # 23:30 on Nov 11, Central
def test_a_plan_for_another_day_sends_nothing(plan, now):
    fake = Fake(people(plan))
    if now.tzinfo.key == "UTC":
        res, _ = go(plan, fake, now=now)
        assert (res.code, res.status) == (3, "missed") and fake.calls == []            # still Nov 11 in the site's zone, but late
        return
    res, _ = go(plan, fake, now=now)
    assert (res.code, res.status) == (0, "wrong-date") and fake.calls == []


def test_the_day_is_judged_in_the_sites_zone_not_utc(plan):
    """00:30 Central on Nov 11 is 06:30 UTC on Nov 11; 23:30 Central on Nov 10 is 05:30 UTC on Nov 11."""
    fake = Fake(people(plan))
    assert go(plan, fake, now=datetime(2026, 11, 11, 5, 30, tzinfo=ZoneInfo("UTC")))[0].status == "wrong-date"
    assert fake.calls == []
    assert go(plan, fake, now=datetime(2026, 11, 11, 6, 30, tzinfo=ZoneInfo("UTC")))[0].status == "sent"


def test_past_latest_send_is_missed_and_sends_nothing(plan):
    fake = Fake(people(plan))
    res, text = go(plan, fake, now=datetime(2026, 11, 11, 10, 1, tzinfo=TZ))
    assert (res.code, res.status) == (deliver.MISSED_EXIT, "missed") and deliver.MISSED_EXIT == 3 and fake.calls == [] and "missed" in text
    assert go(plan, Fake(people(plan)), now=datetime(2026, 11, 11, 10, 0, tzinfo=TZ))[0].status == "late"   # no margin left
    assert go(plan, Fake(people(plan)), now=datetime(2026, 11, 11, 9, 55, tzinfo=TZ))[0].status == "sent"


def test_a_clock_without_a_zone_sends_nothing(plan):
    fake = Fake(people(plan))
    assert go(plan, fake, now=datetime(2026, 11, 11, 5, 0))[0].code == 2 and fake.calls == []


def test_a_plan_with_another_time_zone_sends_nothing(plan):
    fake = Fake(people(plan))
    assert go({**plan, "timezone": "Pacific/Kiritimati"}, fake)[0].code == 2 and fake.calls == []


def test_max_editions_counts_only_editions_with_a_recipient_before_the_first_write(plan):
    """The plan holds every edition any shape could get (191 on day D); max_editions bounds the emails this run
    would create, so it counts the editions that have a recipient, and stops before any write."""
    assert len(plan["editions"]) > 3
    for mode in ("stamp", "ids"):
        fake = Fake(people(plan))                          # people(): three editions with a recipient
        res, text = go(plan, fake, s=settings(mode=mode, max_editions=2))
        assert (res.code, res.status, res.editions) == (2, "over-limit", 0) and "max_editions" in text
        assert fake.calls == ["emails", "subscribers"]     # listings only: no stamp, no email
        assert go(plan, Fake(people(plan)), s=settings(mode=mode, max_editions=3))[0].editions == 3
    shipped = settings_mod.load(ROOT / "config" / "site.yml").max_editions
    assert go(plan, Fake(people(plan)), s=settings(max_editions=shipped))[0].status == "sent"


@pytest.mark.parametrize("change", [
    {"schema": "morning-send/0"}, {"date": "2026-11-11\n"}, {"send": "yes"}, {"editions": {}},
    {"signatures": {"budget|-|-": "ffffffffffff"}}, {"signatures": {"*|-|-": None}}, {"note_sha256": "x"},
    {"editions": [{"key": "../../etc", "subject": "s", "body": "b", "entry_ids": ["a"]}]},
    {"editions": [{"key": "0123456789ab", "subject": "s\nBcc: x", "body": "b", "entry_ids": ["a"]}]},
    {"editions": [{"key": "0123456789ab", "subject": "s", "body": "b", "entry_ids": ["a"], "filters": {}}]},
    {"editions": [{"key": "0123456789ab", "subject": "s", "body": "b" * 600_000, "entry_ids": ["a"]}]},
    {"editions": [], "signatures": {}},
    # plan-untrusted/log-injection: the plan comes from the job that parses untrusted PDFs, and the dry run prints
    # its reason and subjects into a public Actions log
    {"reason": "ok\n::error title=INJECTED::x"}, {"reason": "something"}, {"reason": None}, {"reason": "quiet"},
    {"send": False, "reason": "ok"},
    {"date": "\u0662\u0660\u0662\u0666-\u0661\u0661-\u0661\u0661"},          # Arabic-Indic digits match \d
])
def test_a_malformed_plan_sends_nothing(plan, change):
    fake = Fake(people(plan))
    res, text = go({**plan, **change}, fake)
    assert (res.code, res.status) == (2, "bad-plan") and fake.calls == [] and "nothing sent" in text
    assert go([], fake)[0].code == 2 and go(None, fake)[0].code == 2


@pytest.mark.parametrize("subject", ["s\nBcc: x", "s\u2028::error title=INJECTED::x", "s\u0085x", "s\u2029x",
                                     "s\x1b[2Kx", "s\u202ex", "s\x0bx", "s\u200bx", "s\u00a0x", ""])
def test_a_subject_that_is_not_one_printable_line_sends_nothing(plan, subject):
    """Each edition stays valid but for its subject, so the subject check is what refuses it."""
    bad = copy.deepcopy(plan)
    bad["editions"][0]["subject"] = subject
    fake = Fake(people(plan))
    res, text = go(bad, fake)
    assert (res.code, res.status) == (2, "bad-plan") and "subject" in text and fake.calls == []
    assert go(copy.deepcopy(plan), Fake(people(plan)))[0].status == "sent"


def test_a_signature_with_non_ascii_digits_sends_nothing(plan):
    bad = copy.deepcopy(plan)
    bad["signatures"]["budget|1\u0667|-"] = next(iter(bad["signatures"].values()))
    res, text = go(bad, Fake(people(plan)))
    assert (res.code, res.status) == (2, "bad-plan") and "signature" in text


def test_a_malformed_plan_is_refused_in_the_dry_run_too(plan):
    """The dry run prints the plan's reason and subjects; an injected line must never reach the log."""
    res, text = go({**plan, "reason": "ok\n::error title=INJECTED::x"}, Fake(), live=False)
    assert (res.code, res.status) == (2, "bad-plan") and "INJECTED" not in text


def test_the_shared_patterns_take_ascii_digits_only():
    arabic = "\u0662\u0660\u0662\u0666-\u0661\u0661-\u0661\u0661"
    assert common.DATE_RE.fullmatch(arabic) is None and common.DATE_RE.fullmatch("2026-11-11")
    assert deliver.STAMP_RE.fullmatch(arabic + ".0123456789ab.0123456789abcdef") is None
    assert common.TIME_RE.fullmatch("0\u0667:00") is None and common.TIME_RE.fullmatch("07:00")
    assert common.SIGNATURE_RE.fullmatch("budget|1\u0667|-") is None and common.SIGNATURE_RE.fullmatch("budget|7|-")
    for rx in (common.DATE_RE, common.TIME_RE, common.SIGNATURE_RE, deliver.STAMP_RE):
        assert "\\d" not in rx.pattern


@pytest.mark.parametrize("reason", ["quiet", "backfill", "disabled"])
def test_every_no_send_reason_the_plan_stage_writes_is_accepted(plan, reason):
    assert deliver.REASONS == ("ok", "quiet", "backfill", "disabled")
    res, text = go({**plan, "send": False, "reason": reason}, Fake(), live=False)
    assert res.status == "dry-run" and f"({reason})" in text


# ------------------------------------------------------------------ a normal morning, both modes
def test_stamp_sends_one_scheduled_email_per_edition_to_exactly_its_people(plan):
    fake = Fake(people(plan))
    res, text = go(plan, fake)
    assert (res.code, res.status, res.editions, res.recipients) == (0, "sent", 3, 4)
    assert text == f"morning note {DAY}: sent; emails created 3; recipients in total 4"
    by_key = {p["metadata"]["note_edition"]: p for p in fake.created}
    want = {key_for(plan, ["budget"]): {"sub-0001-secret", "sub-0002-secret"},
            key_for(plan, ["contracts"]): {"sub-0003-secret"},
            key_for(plan, ["budget", "contracts"]): {"sub-0004-secret"}}
    assert set(by_key) == {stamp(k) for k in want}
    editions = {e["key"]: e for e in plan["editions"]}
    for key, ids in want.items():
        p = by_key[stamp(key)]
        assert fake.audience(p) == ids
        assert p["filters"]["filters"][0]["value"] == stamp(key)                     # exactly "<D>.<key>.<mac>"
        assert p["status"] == "scheduled" and p["publish_date"] == "2026-11-11T07:00:00-06:00"
        assert p["archival_mode"] == "disabled"
        assert p["metadata"] == {"note_date": DAY, "note_edition": stamp(key), "note_sha256": plan["note_sha256"]}
        assert (p["subject"], p["body"]) == (editions[key]["subject"], editions[key]["body"])
        assert sorted(p) == ["archival_mode", "body", "filters", "metadata", "publish_date", "status", "subject"]
    assert [p["metadata"]["note_edition"] for p in fake.created] == sorted(by_key)    # in key order
    assert not fake.sent_drafts and len(set(fake.keys)) == len(fake.keys) == 7        # 4 stamps + 3 emails


def test_stamp_rereads_each_subscriber_just_before_the_write_and_keeps_their_changes(plan):
    """L2: the write replaces the whole metadata object, so it is built from a fresh read of that subscriber, not
    from the listing: a change made since (a new key, a new seat) survives. Someone whose shape or type changed is
    not stamped (they get nothing today) and is not counted."""
    def change(subs):
        subs["sub-0004-secret"]["metadata"]["favourite"] = "green"                 # same shape: kept
        subs["sub-0002-secret"]["metadata"]["lists"] = ["contracts"]               # another shape: skipped
        subs["sub-0003-secret"]["type"] = "unsubscribed"                           # left: skipped
    fake = Fake(people(plan))
    fake.after_listing = change
    res, _ = go(plan, fake)
    assert (res.status, res.editions, res.recipients) == ("sent", 2, 2)
    assert fake.subs["sub-0004-secret"]["metadata"]["favourite"] == "green"
    assert fake.subs["sub-0004-secret"]["metadata"]["note_edition"] == stamp(key_for(plan, ["budget", "contracts"]))
    assert "note_edition" not in fake.subs["sub-0002-secret"]["metadata"]
    assert "note_edition" not in fake.subs["sub-0003-secret"]["metadata"]
    assert sorted(sorted(fake.audience(p)) for p in fake.created) == [["sub-0001-secret"], ["sub-0004-secret"]]
    assert fake.calls.count("subscriber") == 4                                     # one re-read per write


def test_a_failed_reread_stops_before_the_write(plan):
    fake = Fake(people(plan), fail={"subscriber": deliver.ProviderError(SECRET_BODY)})
    res, text = go(plan, fake)
    assert (res.code, res.status, res.editions) == (1, "failed", 0) and "set_metadata" not in fake.calls
    assert "subscriber re-read" in text and SECRET_BODY not in text


def test_stamp_writes_the_whole_metadata_back_and_touches_nobody_else(plan):
    before = {s["id"]: copy.deepcopy(s) for s in people(plan)}
    fake = Fake(before.values())
    go(plan, fake)
    four = fake.subs["sub-0004-secret"]
    assert four["metadata"] == {**before["sub-0004-secret"]["metadata"],
                                "note_edition": stamp(key_for(plan, ['budget', 'contracts']))}
    assert four["metadata"]["favourite"] == "blue" and four["metadata"]["ward"] == 3
    for sid in ("sub-0005-secret", "sub-0006-secret", "sub-0007-secret"):
        assert fake.subs[sid] == before[sid]                           # unconfirmed, unsubscribed, no list: untouched
    for sid, s in fake.subs.items():                                   # only metadata ever changes
        assert {k: v for k, v in s.items() if k != "metadata"} == {k: v for k, v in before[sid].items() if k != "metadata"}


@pytest.mark.parametrize("now, want", [
    (datetime(2026, 11, 11, 8, 15, tzinfo=TZ), "2026-11-11T08:20:00-06:00"),
    (datetime(2026, 11, 11, 6, 57, tzinfo=TZ), "2026-11-11T07:02:00-06:00"),
    (datetime(2026, 11, 11, 6, 55, tzinfo=TZ), "2026-11-11T07:00:00-06:00"),
    (datetime(2026, 11, 11, 9, 55, tzinfo=TZ), "2026-11-11T10:00:00-06:00")])
def test_a_late_run_schedules_the_email_a_margin_ahead(plan, now, want):
    """provider-echo/immediate-after-send_at: never "now", so the echo check (and a take-back) runs before the email
    can leave: publish_date = max(send_at, now + 5 minutes). A run that starts before latest_send still sends."""
    assert deliver.PUBLISH_MARGIN == timedelta(minutes=5)
    fake = Fake(people(plan))
    assert go(plan, fake, now=now)[0].status == "sent"
    assert {p["publish_date"] for p in fake.created} == {want}
    assert {p["status"] for p in fake.created} == {"scheduled"}


def clock_of(*times):
    """A clock that gives these times in turn, then keeps giving the last."""
    left = list(times)
    return lambda: left.pop(0) if len(left) > 1 else left[0]


def test_publish_date_is_worked_out_per_edition_from_the_clock(plan):
    """provider-echo L1: stamping one edition's people can take minutes, so each edition's publish_date comes from
    the clock just before its email is created, not from the run's start."""
    at = lambda h, m: datetime(2026, 11, 11, h, m, tzinfo=TZ)              # noqa: E731
    fake = Fake(people(plan))
    res, _ = go(plan, fake, now=None, clock=clock_of(at(6, 50), at(6, 58), at(7, 10), at(7, 20)))
    assert res.status == "sent"
    assert [p["publish_date"] for p in fake.created] == ["2026-11-11T07:03:00-06:00", "2026-11-11T07:15:00-06:00",
                                                         "2026-11-11T07:25:00-06:00"]


def test_an_edition_that_could_not_leave_by_latest_send_stops_the_run(plan):
    """Under the margin: the email would be scheduled after latest_send, so it is not created; exit 2."""
    at = lambda h, m: datetime(2026, 11, 11, h, m, tzinfo=TZ)              # noqa: E731
    fake = Fake(people(plan))
    res, text = go(plan, fake, now=None, clock=clock_of(at(5, 0), at(5, 1), at(9, 56)))
    assert (res.code, res.status, res.editions) == (2, "late", 1) and len(fake.created) == 1
    assert "latest_send" in text
    fake = Fake(people(plan))
    assert go(plan, fake, now=at(9, 58))[0].status == "late" and fake.created == []


def test_ids_mode_drafts_then_sends_to_ids_and_never_writes_a_subscriber(plan):
    before = people(plan)
    fake = Fake(before)
    res, _ = go(plan, fake, s=settings(mode="ids"))
    assert (res.status, res.editions, res.recipients) == ("sent", 3, 4)
    assert "set_metadata" not in fake.calls and list(fake.subs.values()) == before
    assert all(p["status"] == "draft" and "filters" not in p and "publish_date" not in p for p in fake.created)
    sent = {fake.created[int(eid.split("-")[1]) - 1]["metadata"]["note_edition"]: ids for eid, ids in fake.sent_drafts}
    assert sent == {f"{DAY}.{key_for(plan, ['budget'])}": ["sub-0001-secret", "sub-0002-secret"],     # ids: no mac
                    f"{DAY}.{key_for(plan, ['contracts'])}": ["sub-0003-secret"],
                    f"{DAY}.{key_for(plan, ['budget', 'contracts'])}": ["sub-0004-secret"]}


def test_an_edition_with_no_recipient_creates_no_email(plan):
    fake = Fake([sub(1, ["budget"])])
    res, _ = go(plan, fake)
    assert (res.editions, res.recipients) == (1, 1) and len(fake.created) == 1
    fake = Fake([sub(5, ["budget"], type_="unactivated"), sub(7, [])])
    res, _ = go(plan, fake)
    assert (res.status, res.editions) == ("sent", 0) and fake.created == [] and "set_metadata" not in fake.calls


# ------------------------------------------------------------------ who may be mailed
@pytest.mark.parametrize("type_", ["unactivated", "unsubscribed", "removed", "undeliverable", "spammy", "", None, "REGULAR"])
def test_only_regular_subscribers_are_recipients(plan, type_):
    fake = Fake([sub(1, ["budget"], type_=type_), sub(2, ["budget"])])
    go(plan, fake)
    assert [fake.audience(p) for p in fake.created] == [{"sub-0002-secret"}]
    assert "note_edition" not in fake.subs["sub-0001-secret"]["metadata"]


def test_canary_only_reaches_only_the_ids_the_environment_names(plan):
    """audience/canary-self-set: a subscriber writes their own metadata through the public form, so a canary is
    named only by MORNING_NOTE_CANARY_IDS (the note job's environment), never by metadata."""
    rows = [sub(1, ["budget"]), sub(2, ["budget"]), sub(3, ["contracts"], canary="1"),
            sub(4, ["contracts"], canary=1), sub(5, ["budget"], type_="unactivated")]
    fake = Fake(rows)
    res, _ = go(plan, fake, s=settings(canary_only=True), canary_ids=frozenset({"sub-0002-secret", "sub-0005-secret"}))
    assert (res.editions, res.recipients) == (1, 1)
    assert [fake.audience(p) for p in fake.created] == [{"sub-0002-secret"}]
    assert settings_mod.load(ROOT / "config" / "site.yml").canary_only is True      # the shipped default


@pytest.mark.parametrize("ids", [None, frozenset()])
def test_canary_only_with_no_canary_list_sends_to_nobody(plan, ids):
    fake = Fake([sub(1, ["budget"], canary="1"), sub(2, ["contracts"], canary="1")])
    res, text = go(plan, fake, s=settings(canary_only=True), canary_ids=ids)
    assert (res.code, res.status, res.editions, res.recipients) == (0, "no-canary", 0, 0)
    assert fake.calls == [] and "MORNING_NOTE_CANARY_IDS" in text


def test_metadata_canary_is_not_read_at_all():
    r = deliver.recipient(sub(1, ["budget"], canary="1"), settings())
    assert not hasattr(r, "canary")
    src = (ROOT / "sender" / "deliver.py").read_text(encoding="utf-8")
    assert 'get("canary")' not in src and "['canary']" not in src


@pytest.mark.parametrize("text, want", [
    (None, None), ("", frozenset()), ("  ", frozenset()), ("a1b2-c3", frozenset({"a1b2-c3"})),
    ("a, b\nc", frozenset({"a", "b", "c"}))])
def test_the_canary_list_is_read_from_the_environment_text(text, want):
    assert deliver.canary_ids(text) == want


@pytest.mark.parametrize("text", ["a;b", "a b@example.com", "x" * 65, "a,,b", "\u0661"])
def test_a_malformed_canary_list_is_an_error(text):
    with pytest.raises(deliver.PlanInvalid):
        deliver.canary_ids(text)


def test_the_cli_reads_the_canary_list_from_the_environment(monkeypatch):
    import sender.__main__ as cli
    monkeypatch.setenv("MORNING_NOTE_CANARY_IDS", "abc,def")
    assert cli._canary_from_env() == frozenset({"abc", "def"})
    monkeypatch.delenv("MORNING_NOTE_CANARY_IDS")
    assert cli._canary_from_env() is None


@pytest.mark.parametrize("meta, expect", [
    ({"lists": ["budget"], "district": "7; drop"}, "budget|-|-"),
    ({"lists": ["budget"], "district": "7"}, "budget|7|-"),
    ({"lists": ["budget"], "district": 22, "ward": 13}, "budget|-|-"),          # one past the counts
    ({"lists": ["budget"], "district": 21, "ward": 12}, "budget|21|12"),
    ({"lists": ["budget"], "district": 0, "ward": -1}, "budget|-|-"),
    ({"lists": ["budget"], "district": True, "ward": 7.0}, "budget|-|-"),
    ({"lists": ["budget"], "district": "07", "ward": " 3"}, "budget|-|-"),
    ({"lists": ["budget"], "district": {"$ne": 1}, "ward": ["3"]}, "budget|-|-"),
    ({"lists": ["zoning", "x"]}, "zoning|-|-"),
    ({"lists": ["x", "*", "budget,zoning"]}, None),
    ({"lists": "budget, zoning"}, "budget,zoning|-|-"),
    ({"lists": ["budget"] * 5000}, None),
    ({"lists": "budget," * 5000}, None),
    ({"lists": {"budget": True}}, None), ({"lists": None}, None), ({}, None)])
def test_hostile_metadata_is_ignored_not_passed_on(plan, meta, expect):
    """The public form takes any text for district, ward and lists. Whatever arrives, the sender works only with a
    known list key and a whole number in range; the rest is treated as not set."""
    s = settings()
    r = deliver.recipient({"id": "sub-0001-secret", "type": "regular", "metadata": meta}, s)
    got = common.signature(r.lists, r.district, r.ward) if r.lists else None
    assert got == expect
    fake = Fake([{"id": "sub-0001-secret", "type": "regular", "metadata": meta, "email_address": "person1@example.com"}])
    go(plan, fake)
    for p in fake.created:
        assert p["filters"]["filters"][0]["value"] == stamp(plan['signatures'][expect])
    assert bool(fake.created) == (expect in plan["signatures"])


def test_a_subscriber_row_that_is_not_a_record_is_skipped(plan):
    s = settings()
    for raw in (None, "x", [], {"type": "regular"}, {"type": "regular", "id": 7}, {"type": "regular", "id": ""}):
        assert deliver.recipient(raw, s) is None
    assert deliver.recipient({"type": "regular", "id": "a", "metadata": "x"}, s).lists == ()


def test_the_stamp_is_unguessable_from_the_public_note_and_stable_across_runs():
    """audience/stamp-self-set-race: "<day>.<key>" alone is computable from morning/<D>.json, so the stamp adds
    HMAC-SHA256(secret, "<day>.<key>")[:16]; the same secret gives the same stamp on a re-run."""
    import hashlib
    import hmac
    key = "0123456789ab"
    want = f"{DAY}.{key}." + hmac.new(SECRET, f"{DAY}.{key}".encode(), hashlib.sha256).hexdigest()[:16]
    assert deliver.stamp_value(DAY, key, SECRET) == want == stamp(key)
    assert deliver.STAMP_RE.fullmatch(want) and deliver.stamp_value(DAY, key, b"another key") != want
    for secret in (b"", None, "text"):
        with pytest.raises(deliver.PlanInvalid):
            deliver.stamp_value(DAY, key, secret)


def test_stamp_mode_without_the_secret_sends_nothing(plan):
    fake = Fake(people(plan))
    res, text = go(plan, fake, secret=None)
    assert (res.code, res.status) == (2, "no-secret") and fake.calls == []
    assert go(plan, Fake(people(plan)), s=settings(mode="ids"), secret=None)[0].status == "sent"   # ids needs none


@pytest.mark.parametrize("value", ["2026-11-11", "x 2026-11-11 y", "2026-11-11.{k}", "2026-11-11.{k}.0000000000000000",
                                   "2026-11-11.ffffffffffff.0123456789abcdef", ["2026-11-11.{k}"], 20261111])
def test_a_value_that_is_not_an_expected_stamp_neither_blocks_the_run_nor_gets_mail(plan, value):
    """Narrowed stray check: only exactly an expected stamp for today counts, so nobody can stop every send by
    putting today's date in their own metadata, and a guessed stamp is mailed nothing."""
    k = key_for(plan, ["budget"])
    value = value.replace("{k}", k) if isinstance(value, str) else [v.replace("{k}", k) for v in value] if isinstance(value, list) else value
    fake = Fake(people(plan) + [sub(9, [], note_edition=value)])                # picked no list: mailed nothing
    res, _ = go(plan, fake)
    assert (res.code, res.status, res.editions) == (0, "sent", 3)
    assert all("sub-0009-secret" not in fake.audience(p) for p in fake.created)


def test_a_subscriber_holding_todays_stamp_outside_its_audience_stops_the_run(plan):
    """audience/stamp-self-set: the stamp value is computable from the public note, so a stranger could set it on
    themselves through the form and the provider's filter would mail them. Any regular subscriber holding a stamp
    for today who is not in that edition's audience stops the run before any write."""
    value = stamp(key_for(plan, ['budget']))
    stranger = sub(9, ["contracts"], note_edition=value)                   # picked contracts, stamped for budget
    for rows, s in ((people(plan) + [stranger], settings()),
                    ([sub(1, ["budget"]), sub(9, ["budget"], note_edition=value)],          # not a canary
                     settings(canary_only=True)),
                    (people(plan) + [sub(9, [], note_edition=value)], settings())):
        fake = Fake(rows)
        res, text = go(plan, fake, s=s, canary_ids=frozenset({"sub-0001-secret"}))
        assert (res.code, res.status, res.editions) == (2, "stray-stamp", 0), text
        assert fake.calls == ["emails", "subscribers"] and "sub-0009" not in text


@pytest.mark.parametrize("type_", ["premium", "gifted", "trialed", "churning", "past_due", "unactivated", None])
def test_a_stamp_held_by_a_subscriber_of_any_type_counts(plan, type_):
    """L3: the provider's filter may reach receiving types other than "regular" (paying, gifted, trial), which are
    never recipients here, so the stray check reads every row of the listing, whatever its type."""
    value = stamp(key_for(plan, ["budget"]))
    fake = Fake(people(plan) + [sub(9, ["budget"], type_=type_, note_edition=value)])
    res, _ = go(plan, fake)
    assert (res.code, res.status) == (2, "stray-stamp") and "set_metadata" not in fake.calls


def test_a_paying_or_gifted_subscriber_is_never_a_recipient(plan):
    """No paid tier exists; such a subscriber gets nothing (never a wrong email) until the sender learns the type."""
    fake = Fake([sub(1, ["budget"], type_="premium"), sub(2, ["budget"], type_="gifted"), sub(3, ["budget"])])
    res, _ = go(plan, fake)
    assert (res.editions, res.recipients) == (1, 1) and [fake.audience(p) for p in fake.created] == [{"sub-0003-secret"}]


def test_stamps_from_an_earlier_run_of_the_same_plan_or_another_day_are_fine(plan):
    fake = Fake(people(plan), fail={"create_email": [None, deliver.ProviderError("x")]})
    assert go(plan, fake)[0].status == "failed"                             # stamped edition 1 and 2's people
    fake.fail = {}
    assert go(plan, fake)[0].status == "sent"                               # their stamps are in `to`: fine
    old = sub(9, ["budget"], note_edition="2026-11-10.0123456789ab")         # yesterday's stamp
    unconfirmed = sub(8, ["contracts"], type_="unactivated", note_edition="2026-11-11")
    assert go(plan, Fake(people(plan) + [old, unconfirmed]))[0].status == "sent"
    assert go(plan, Fake(people(plan) + [unconfirmed]), s=settings(mode="ids"))[0].status == "sent"


def test_a_subscriber_listed_twice_is_one_recipient(plan):
    row = sub(1, ["budget"])
    for mode in ("stamp", "ids"):
        fake = Fake([row])
        fake.subscribers = lambda: [copy.deepcopy(row), copy.deepcopy(row)]       # a paged listing that overlaps
        res, _ = go(plan, fake, s=settings(mode=mode))
        assert (res.editions, res.recipients) == (1, 1)
        if mode == "stamp":
            assert fake.calls.count("set_metadata") == 1
        else:
            assert fake.sent_drafts[0][1] == ["sub-0001-secret"]


@pytest.mark.parametrize("zone", ["Mars/Olympus", "../../etc/passwd", ""])
def test_an_unknown_time_zone_is_a_clean_error(plan, zone):
    fake = Fake(people(plan))
    res, text = go({**plan, "timezone": zone}, fake, s=settings(timezone=zone))
    assert (res.code, res.status) == (2, "failed") and "time zone" in text and fake.calls == []


def test_the_address_is_dropped_at_the_boundary(plan):
    r = deliver.recipient(sub(1, ["budget"], district=7), settings())
    assert "example.com" not in repr(dataclasses.asdict(r)) and "sub-0001" not in repr(r)
    assert sorted(f.name for f in dataclasses.fields(r)) == ["district", "id", "lists", "metadata", "ward"]


def test_over_max_recipients_sends_nothing(plan):
    fake = Fake([sub(n, ["budget"]) for n in range(1, 6)])
    res, _ = go(plan, fake, s=settings(max_recipients=4))
    assert (res.code, res.status) == (2, "over-limit") and fake.calls == ["emails", "subscribers"]
    assert go(plan, Fake([sub(n, ["budget"]) for n in range(1, 5)]), s=settings(max_recipients=4))[0].status == "sent"


# ------------------------------------------------------------------ never twice
@pytest.mark.parametrize("mode", ["stamp", "ids"])
def test_a_second_run_of_the_same_plan_sends_nothing_new(plan, mode):
    fake = Fake(people(plan))
    assert go(plan, fake, s=settings(mode=mode))[0].editions == 3
    created, drafts = len(fake.created), len(fake.sent_drafts)
    writes = fake.calls.count("set_metadata")
    res, _ = go(plan, fake, s=settings(mode=mode), now=AT_5 + timedelta(hours=1))
    assert (res.code, res.status, res.editions, res.recipients) == (0, "sent", 0, 0)
    assert (len(fake.created), len(fake.sent_drafts), fake.calls.count("set_metadata")) == (created, drafts, writes)


def test_a_run_that_died_after_edition_1_of_3_finishes_2_and_3_only(plan):
    fake = Fake(people(plan), fail={"create_email": [None, deliver.ProviderError(SECRET_BODY)]})
    res, text = go(plan, fake)
    assert (res.code, res.status, res.editions) == (1, "failed", 1) and len(fake.created) == 1
    first = fake.created[0]["metadata"]["note_edition"]
    fake.fail = {}
    res, _ = go(plan, fake)
    assert (res.code, res.status, res.editions) == (0, "sent", 2) and len(fake.created) == 3
    editions = [p["metadata"]["note_edition"] for p in fake.created]
    assert len(set(editions)) == 3 and editions.count(first) == 1


def test_ids_mode_never_resends_a_draft_whose_send_failed(plan):
    """Never twice before never missed: the draft is the claim, so the re-run skips that edition."""
    fake = Fake(people(plan), fail={"send_draft": [deliver.ProviderError("x")]})
    res, _ = go(plan, fake, s=settings(mode="ids"))
    assert (res.code, res.editions) == (1, 0) and len(fake.created) == 1 and fake.sent_drafts == []
    res, _ = go(plan, fake, s=settings(mode="ids"))
    assert res.editions == 2 and len(fake.created) == 3 and len(fake.sent_drafts) == 2


def test_a_day_claimed_by_a_different_note_sends_nothing(plan):
    other = {"id": "em-9", "status": "scheduled", "metadata": {"note_date": DAY, "note_edition": f"{DAY}.aaaaaaaaaaaa", "note_sha256": "0" * 64}}
    fake = Fake(people(plan), emails=[other])
    res, _ = go(plan, fake)
    assert (res.code, res.status, res.editions) == (0, "claimed", 0) and fake.calls == ["emails"]
    # one email of ours and one of another plan on the same day: still nothing
    ours = {"id": "em-8", "status": "scheduled", "metadata": {"note_date": DAY, "note_edition": f"{DAY}.bbbbbbbbbbbb", "note_sha256": plan["note_sha256"]}}
    fake = Fake(people(plan), emails=[ours, other])
    assert go(plan, fake)[0].status == "claimed" and fake.calls == ["emails"]


def test_emails_of_other_days_and_other_kinds_do_not_claim_the_day(plan):
    rows = [{"id": "em-1", "status": "sent", "metadata": {"note_date": "2026-11-10", "note_sha256": "0" * 64}},
            {"id": "em-2", "status": "sent", "metadata": {}}, {"id": "em-4", "status": "sent", "metadata": None}]
    assert go(plan, Fake(people(plan), emails=rows))[0].editions == 3


def test_a_listed_email_without_a_metadata_key_fails_closed(plan):
    """audience/provider-echo: a listing whose rows lack `metadata` cannot tell a claimed day from a free one."""
    fake = Fake(people(plan), emails=[{"id": "em-3", "status": "sent"}])
    res, text = go(plan, fake)
    assert (res.code, res.status, res.editions) == (1, "failed", 0) and fake.calls == ["emails"]
    assert "email listing" in text


def _drop_filter(row):
    row.pop("filters", None)
    return row


@pytest.mark.parametrize("echo", [
    _drop_filter, lambda r: {**r, "filters": {"filters": [], "groups": [], "predicate": "and"}},
    lambda r: {**r, "filters": {**r["filters"], "predicate": "or"}}, lambda r: {**r, "status": "about_to_send"},
    lambda r: {**r, "metadata": {**r["metadata"], "note_sha256": "0" * 64}}, lambda r: r["id"], lambda r: None,
    lambda r: {**r, "id": ""}])
def test_stamp_unschedules_an_email_the_provider_stored_differently(plan, echo):
    """audience/provider-echo: the stored email decides who gets it, so it must echo exactly the filter, status and
    claim deliver sent; otherwise it is taken back to a draft and the run fails before the next edition."""
    fake = Fake(people(plan), echo=echo)
    res, text = go(plan, fake)
    assert (res.code, res.status, res.editions) == (1, "failed", 0) and fake.calls.count("create_email") == 1
    assert "email check" in text
    stored = fake.email_rows[0]
    got = echo(copy.deepcopy(stored))
    if (isinstance(got, dict) and got.get("id")) or (isinstance(got, str) and got):
        assert fake.unscheduled == [stored["id"]] and stored["status"] == "draft"
        assert "may still be scheduled" not in text                      # taken back, and confirmed a draft
    else:
        # provider-echo/no-id-silent: no id came back, so nothing can be taken back: the output says so
        assert fake.unscheduled == [] and "an email may still be scheduled" in text


@pytest.mark.parametrize("answer", ["stuck", "none", "other id"])
def test_a_take_back_that_is_not_confirmed_a_draft_is_named(plan, answer):
    fake = Fake(people(plan), echo=_drop_filter)
    if answer == "stuck":
        fake.stuck = True
    real = fake.unschedule
    if answer == "none":
        fake.unschedule = lambda i, k: (real(i, k), None)[1]
    elif answer == "other id":
        fake.unschedule = lambda i, k: {**real(i, k), "id": "em-999"}
    res, text = go(plan, fake)
    assert (res.code, res.status) == (1, "failed") and "an email may still be scheduled" in text


@pytest.mark.parametrize("echo", [lambda r: {**r, "status": "scheduled"},
                                  lambda r: {**r, "filters": {"filters": [], "groups": [], "predicate": "and"}},
                                  lambda r: {**r, "metadata": {}}, lambda r: r["id"]])
def test_ids_never_sends_a_draft_the_provider_stored_differently(plan, echo):
    fake = Fake(people(plan), echo=echo)
    res, text = go(plan, fake, s=settings(mode="ids"))
    assert (res.code, res.status, res.editions) == (1, "failed", 0) and fake.sent_drafts == []
    assert "send_draft" not in fake.calls and "email check" in text


def test_a_failed_take_back_is_named_in_the_output(plan):
    fake = Fake(people(plan), echo=_drop_filter, fail={"unschedule": deliver.ProviderError(SECRET_BODY)})
    res, text = go(plan, fake)
    assert (res.code, res.status) == (1, "failed") and "an email may still be scheduled" in text
    assert SECRET_BODY not in text


def test_a_faithful_echo_sends_and_unschedules_nothing(plan):
    for mode in ("stamp", "ids"):
        fake = Fake(people(plan))
        res, _ = go(plan, fake, s=settings(mode=mode))
        assert (res.code, res.editions) == (0, 3) and fake.unscheduled == [] and "unschedule" not in fake.calls


@pytest.mark.parametrize("failure", [
    {"fail": {"emails": deliver.ProviderError(SECRET_BODY)}}, {"fail": {"emails": TimeoutError(SECRET_BODY)}},
    {"rows": "cut short"}, {"rows": None}, {"rows": [["not", "a", "record"]]},
    {"rows": [{"id": "em-1", "metadata": "unreadable"}]}])
def test_a_failed_or_unreadable_email_listing_sends_nothing_and_fails(plan, failure):
    fake = Fake(people(plan), fail=failure.get("fail"))
    if "rows" in failure:
        fake.emails = lambda: (fake.calls.append("emails"), failure["rows"])[1]
    res, text = go(plan, fake)
    assert (res.code, res.status, res.editions) == (1, "failed", 0) and fake.calls == ["emails"]
    assert "email listing" in text and SECRET_BODY not in text


def test_a_failed_subscriber_listing_sends_nothing_and_fails(plan):
    fake = Fake(people(plan), fail={"subscribers": deliver.ProviderError(SECRET_BODY)})
    res, text = go(plan, fake)
    assert (res.code, res.status) == (1, "failed") and fake.calls == ["emails", "subscribers"]
    fake = Fake(people(plan))
    fake.subscribers = lambda: None
    assert go(plan, fake)[0].code == 1 and fake.created == []


def test_idempotency_keys_are_stable_per_day_edition_and_step(plan):
    a, b = Fake(people(plan)), Fake(people(plan))
    go(plan, a)
    go(plan, b, now=AT_5 + timedelta(minutes=30))
    assert a.keys == b.keys and len(set(a.keys)) == len(a.keys)
    assert all(len(k) == 36 and "sub-" not in k for k in a.keys)       # a uuid5: no subscriber id inside
    assert deliver.idempotency_key(DAY, "0123456789ab", "email") != deliver.idempotency_key("2026-11-12", "0123456789ab", "email")


# ------------------------------------------------------------------ a stamp email can never go to everyone
@pytest.mark.parametrize("broken", [
    {}, None, {"filters": [], "groups": [], "predicate": "and"},
    {"filters": [{"field": "subscriber.metadata.note_edition", "operator": "equals", "value": ""}], "groups": [], "predicate": "and"},
    {"filters": [{"field": "subscriber.metadata.note_edition", "operator": "not_equals", "value": "X"}], "groups": [], "predicate": "and"},
    {"filters": [{"field": "subscriber.metadata.note_edition", "operator": "equals", "value": "X"}], "groups": [], "predicate": "or"}])
def test_no_stamp_email_is_created_with_an_empty_or_wrong_filter(plan, monkeypatch, broken):
    """Even if the filter builder were broken, the last check before the call refuses the email."""
    def bad(day, key, secret):
        f = copy.deepcopy(broken)
        if isinstance(f, dict) and f.get("filters") and f["filters"][0]["value"] == "X":
            f["filters"][0]["value"] = f"{day}.{key}"
        return f
    monkeypatch.setattr(deliver, "stamp_filter", bad)
    fake = Fake(people(plan))
    res, _ = go(plan, fake)
    assert (res.code, res.status, res.editions) == (1, "failed", 0) and "create_email" not in fake.calls


def test_the_audience_check_accepts_only_the_editions_own_filter():
    key = "0123456789ab"
    good = {"status": "scheduled", "filters": deliver.stamp_filter(DAY, key, SECRET)}
    deliver._check_audience("stamp", good, DAY, key, SECRET)
    for payload in ({**good, "status": "draft"}, {"status": "scheduled"}, {**good, "filters": deliver.stamp_filter("2026-11-10", key, SECRET)},
                    {**good, "filters": deliver.stamp_filter(DAY, key, b"another key")}):
        with pytest.raises(deliver.ProviderError):
            deliver._check_audience("stamp", payload, DAY, key, SECRET)
    with pytest.raises(deliver.ProviderError):
        deliver._check_audience("ids", good, DAY, key, SECRET)                 # an ids email carries no filter, and is a draft
    with pytest.raises(deliver.PlanInvalid):
        deliver.stamp_filter(DAY, "not-a-key", SECRET)


# ------------------------------------------------------------------ rate limits
def test_429_is_obeyed_three_tries_then_stop(plan):
    sleeps = []
    fake = Fake(people(plan), fail={"emails": [deliver.RateLimited(2), deliver.RateLimited(7), None]})
    res, _ = go(plan, fake, sleeps=sleeps)
    assert res.status == "sent" and sleeps == [2.0, 7.0] and fake.calls.count("emails") == 3
    sleeps = []
    fake = Fake(people(plan), fail={"emails": [deliver.RateLimited(1)] * 5})
    res, text = go(plan, fake, sleeps=sleeps)
    assert (res.code, res.status, res.editions) == (1, "failed", 0)
    assert fake.calls == ["emails"] * 3 and sleeps == [1.0, 1.0]       # three tries, two waits, then stop


def test_a_retry_after_is_capped_and_never_negative(plan):
    sleeps = []
    fake = Fake(people(plan), fail={"subscribers": [deliver.RateLimited(99999), deliver.RateLimited(-5), None]})
    assert go(plan, fake, sleeps=sleeps)[0].status == "sent" and sleeps == [float(deliver.MAX_WAIT), 0.0]


# ------------------------------------------------------------------ no personal data out
def _secrets(rows) -> list[str]:
    out = [SECRET_BODY, "192.0.2.10", "made-up fixture person"]
    for s in rows:
        out += [s["id"], s["email_address"], s["email_address"].split("@")[0]]
    return out


@pytest.mark.parametrize("mode", ["stamp", "ids"])
@pytest.mark.parametrize("fail", [
    None, {"emails": deliver.ProviderError(SECRET_BODY)}, {"subscribers": deliver.ProviderError(SECRET_BODY)},
    {"set_metadata": deliver.ProviderError(SECRET_BODY)}, {"create_email": deliver.ProviderError(SECRET_BODY)},
    {"send_draft": deliver.ProviderError(SECRET_BODY)}, {"create_email": [None, ValueError(SECRET_BODY)]},
    {"subscribers": KeyError("person1@example.com")}, {"emails": [deliver.RateLimited(1)] * 3},
    "over-limit", "claimed", "missed", "dry-run"])
def test_no_address_id_or_response_body_reaches_the_output(plan, capsys, mode, fail):
    """Across success and each failure path: stdout, stderr and every raised exception's text."""
    rows = people(plan)
    kw = {"s": settings(mode=mode)}
    emails = []
    if fail == "over-limit":
        kw["s"] = settings(mode=mode, max_recipients=1)
    elif fail == "claimed":
        emails = [{"id": "em-9-secret", "status": "sent", "metadata": {"note_date": DAY, "note_sha256": "1" * 64, "who": SECRET_BODY}}]
    elif fail == "missed":
        kw["now"] = datetime(2026, 11, 11, 11, 0, tzinfo=TZ)
    elif fail == "dry-run":
        kw["live"] = False
    fake = Fake(rows, emails=emails, fail=fail if isinstance(fail, dict) else None)
    raised = ""
    try:
        lines = []
        res = deliver.run(plan, kw["s"], provider=fake, live=kw.get("live", True), now=kw.get("now", AT_5),
                          sleep=lambda _s: None, out=lines.append, stamp_secret=SECRET)
        res2 = deliver.run(plan, kw["s"], provider=fake, live=kw.get("live", True), now=kw.get("now", AT_5),
                           sleep=lambda _s: None, stamp_secret=SECRET)                        # and once more, printing for real
    except Exception as exc:  # noqa: BLE001
        raised = f"{exc!r} {exc}"
        res = res2 = None
    cap = capsys.readouterr()
    text = "\n".join(lines) + cap.out + cap.err + raised + repr(res) + repr(res2)
    assert raised == ""                                                 # run() never lets an exception out
    for secret in _secrets(rows) + ["em-9-secret"]:
        assert secret not in text, secret
    assert "@" not in text and "sub-" not in text
    if fail is None:
        assert lines == [f"morning note {DAY}: sent; emails created 3; recipients in total 4"]
    # totals only: no per-edition count and no signature (a signature with one recipient could point at a person)
    if kw.get("live", True):
        assert len(lines) == 1 and not any(sig in text for sig in plan["signatures"])
        assert not any(k in text for k in {e["key"] for e in plan["editions"]})


# ------------------------------------------------------------------ the job that holds the key installs nothing
def test_deliver_imports_with_sitegen_yaml_and_jinja2_blocked():
    code = (
        "import sys\n"
        "class Block:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ('sitegen', 'yaml', 'jinja2', 'jsonschema', 'collector', 'requests'):\n"
        "            raise ImportError('blocked: ' + name)\n"
        "sys.meta_path.insert(0, Block())\n"
        "import sender.deliver, sender.settings, sender.common\n"
        "from sender.__main__ import main\n"
        "s = sender.settings.load('config/site.yml')\n"
        "assert s.enabled is False and s.mode == 'stamp'\n"
        "bad = [m for m in sys.modules if m.split('.')[0] in ('sitegen', 'yaml', 'jinja2', 'socket', 'ssl', 'http', 'urllib')]\n"
        "assert not bad, bad\n"
        "print('ok')\n")
    done = subprocess.run([sys.executable, "-S", "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and done.stdout.strip() == "ok", done.stderr


def test_the_deliver_stage_opens_no_connection(plan, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the deliver stage tried to open a connection")
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, refuse)
    assert go(plan, Fake(people(plan)))[0].status == "sent"
    with contextlib.redirect_stdout(io.StringIO()):
        assert deliver.run(plan, settings(), live=False).status == "dry-run"


def test_the_base_provider_does_nothing():
    p = deliver.Provider()
    for call in (p.emails, p.subscribers, lambda: p.set_metadata("a", {}, "k"), lambda: p.create_email({}, "k"),
                 lambda: p.send_draft("a", [], "k"), lambda: p.unschedule("a", "k"), lambda: p.subscriber("a")):
        with pytest.raises(NotImplementedError):
            call()


def test_fixture_subscribers_are_all_at_example_com():
    src = Path(__file__).read_text(encoding="utf-8")
    import re
    assert set(re.findall(r"[A-Za-z0-9._+-]+@([A-Za-z0-9-]+\.[a-z]{2,})", src)) == {"example.com"}
    assert config.SITE["morning_note"]["sender"]["enabled"] is False


# ------------------------------------------------------------------ plan-untrusted/body-unchecked
GOOD_BODY = ('<h1>Daylight</h1>\n<p>November 11, 2026</p>\n<ul>\n<li>A<br><strong>T</strong><br>'
             '<a href="https://records.example.com/items/2026.html#i-x">Open</a> &middot; '
             '<a href="https://www.cmcrpc.com/a.pdf?x=1&amp;y=%7B2%7D">Source</a></li>\n</ul>\n<p>&#123;why&#125;</p>\n')


@pytest.mark.parametrize("body", [
    "<script>alert(1)</script>", '<img src="https://records.example.com/x.png">', '<p class="x">x</p>',
    '<a href="https://evil.example/">x</a>', '<a href="http://records.example.com/x">x</a>',
    '<a href="https://user' + '@records.example.com/x">x</a>', '<a href="https://records.example.com:8443/x">x</a>',
    '<a href="javascript:alert(1)">x</a>', "<a>x</a>", '<a href="https://records.example.com/" title="t">x</a>',
    "<p>{{ subscriber.email }}</p>", "<p>{% if x %}</p>", "<p>a}b</p>", "<!-- note -->", "<!DOCTYPE html>",
    "<?php x ?>", '<a href="https://RECORDS.example.com.evil.example/">x</a>', "<style>p{}</style>", "<br/>x<iframe>"])
def test_a_body_that_render_could_not_have_written_sends_nothing(plan, body):
    """The plan crosses from the job that parses untrusted PDFs: deliver accepts only the tags render writes, no
    attribute but an https href on a link host, and no literal brace (render writes braces as references)."""
    s = settings()
    bad = copy.deepcopy(plan)
    bad["editions"][0]["body"] = body
    with pytest.raises(deliver.PlanInvalid, match="body"):
        deliver.check_plan(bad, s.link_hosts)
    fake = Fake(people(plan))
    res, text = go(bad, fake, s=s)
    assert (res.code, res.status) == (2, "bad-plan") and fake.calls == [] and "body" in text


def _with(line: str) -> str:
    """GOOD_BODY with one more line before its last."""
    head, last = GOOD_BODY[:-1].rsplit("\n", 1)
    return f"{head}\n{line}\n{last}\n"


# M3 (security delta at a168d24): text the old tag-only check let through, then everything it already blocked
TEXT_BYPASSES = [
    _with("<p>[Confirm](https://evil.example/x)</p>"), _with("<p>![x](https://evil.example/t.gif)</p>"),
    _with("<p>[x]: https&#58;//evil.example</p>"), _with("<p>[x]: https://evil.example</p>"),
    _with("<p>Sign in at https://evil.example/login</p>"), _with("<p>Sign in at evil.example/login</p>"),
    _with("<p>See WWW.evil now</p>"), _with("<p>mail x&#64;evil.example</p>"), _with("<p>evil\uff0eexample</p>"),
    _with("<p>https:&#8203;//evil.example</p>"), _with("<p>evil.&#x65;xample</p>"),
    _with("<li>outside a list</li>"), "<ul>\n" + GOOD_BODY, GOOD_BODY + "<ul>\n",
    GOOD_BODY + '<a href="https://evil.example/"', GOOD_BODY + "<img src=https://evil.example/t.gif",
    GOOD_BODY[:-1], GOOD_BODY + "x\n", GOOD_BODY + "\n", GOOD_BODY.replace("<h1>Daylight</h1>\n", ""),
    _with("<p>a</p><p>b</p>"), _with("<p>a\x00b</p>"), _with("<p>a\tb</p>"), _with("<p>a\u202eb</p>"),
    _with("<p>&#8238;b</p>"), _with("<p>&amp;</p>"), _with("<p>&lt;script&gt;</p>"),
]
REGRESSIONS = [
    _with('<p><a href="https://user' + '@records.example.com/x">x</a></p>'),
    _with('<p><a href="javascript&#58;alert(1)">x</a></p>'), _with('<p><a href="HTTPS://records.example.com/">x</a></p>'),
    _with('<p><a href="//records.example.com/">x</a></p>'),
    _with('<p><a href="https://records.example.com.evil.example/">x</a></p>'),
    _with('<p><a href="https://records.example.com/\tx">x</a></p>'),
    _with('<p><a href="https://records.example.com/" href="https://evil.example/">x</a></p>'),
    _with('<p><a href="https://records.example.com/x&#38;y">x</a></p>'),
    _with('<p><img src="https://records.example.com/x.png"></p>'), _with("<style>p{}</style>"),
    _with("<!-- x -->"), _with("<![CDATA[x]]>"), _with("<p>x</ p onclick=y>"), _with("<p>{% if x %}</p>"),
    _with("    <script>alert(1)</script>"), _with("<p>    indented</p>"), _with("<br/>"), _with("<P>x</P>"),
]


@pytest.mark.parametrize("body", TEXT_BYPASSES + REGRESSIONS)
def test_a_body_is_held_to_the_exact_lines_render_writes(plan, body):
    """plan-untrusted/body-unchecked: each line one of render's own forms, the text between tags free of every
    markup character, address and domain render breaks, and the body ending in a complete line."""
    s = settings()
    assert not deliver.body_ok(body, s.link_hosts)
    bad = copy.deepcopy(plan)
    bad["editions"][0]["body"] = body
    with pytest.raises(deliver.PlanInvalid, match="body"):
        deliver.check_plan(bad, s.link_hosts)


@pytest.mark.parametrize("href, ok", [("https://tips.example.com/x", True), ("https://tips.example.com/other", False),
                                       ("https://tips.example.com/x?y=1", False), ("https://tips.example.com/x/", False),
                                       ("https://records.example.com/items/2026.html", True)])
def test_the_support_url_is_allowed_exactly_not_its_host(plan, href, ok):
    """Low (a): a page anyone could host on the support link's host is refused; the configured URL passes."""
    hosts = tuple(h for h in settings().link_hosts if h != "tips.example.com")
    urls = settings().link_urls + ("https://tips.example.com/x",)        # the fixture's own support link too
    body = _with(f'<p>Please help. <a href="{href}">Tips</a></p>')
    assert deliver.body_ok(body, hosts, urls) is ok
    assert not deliver.body_ok(_with('<p>Please help. <a href="https://tips.example.com/x">Tips</a></p>'), hosts)
    good = copy.deepcopy(plan)
    good["editions"][0]["body"] = body
    if ok:
        deliver.check_plan(good, hosts, urls)
    else:
        with pytest.raises(deliver.PlanInvalid, match="body"):
            deliver.check_plan(good, hosts, urls)


def test_the_run_allows_the_settings_support_url(plan):
    s = dataclasses.replace(settings(), link_hosts=tuple(h for h in settings().link_hosts if h != "tips.example.com"))
    good = copy.deepcopy(plan)
    good["editions"][0]["body"] = _with('<p>Please help. <a href="https://tips.example.com/x">Tips</a></p>')
    res, _ = go(good, Fake(people(plan)), s=s)
    assert res.status == "bad-plan"
    res, _ = go(good, Fake(people(plan)), s=dataclasses.replace(s, link_urls=s.link_urls + ("https://tips.example.com/x",)))
    assert res.status != "bad-plan"


def test_the_bodies_render_writes_pass_the_check(plan):
    s = settings()
    deliver.check_plan(copy.deepcopy(plan), s.link_hosts, s.link_urls)
    good = copy.deepcopy(plan)
    good["editions"][0]["body"] = GOOD_BODY
    deliver.check_plan(good, s.link_hosts, s.link_urls)
    with pytest.raises(deliver.PlanInvalid, match="body"):
        deliver.check_plan(copy.deepcopy(plan), ("www.cmcrpc.com",), s.link_urls)     # the site host is not one
    with pytest.raises(deliver.PlanInvalid, match="body"):
        deliver.check_plan(copy.deepcopy(plan), s.link_hosts)               # nor is the support link's host
