# ruff: noqa: E501
"""The morning note sender's deliver stage against an in-memory fake provider (T4.4: sender/deliver.py; ADR 0004,
decision 6: one edition for every confirmed subscriber). No test opens a connection: this package has no provider
client. Every subscriber here is made up, with an address at example.com, and the tests assert that none of it ever
reaches the output. The shipped mode is `all` (no subscriber call); `stamp` stays for canary trials and `ids` is
kept but unusable on Buttondown, so the tests of those name their mode."""
import contextlib
import copy
import dataclasses
import io
import re
import socket
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from conftest import shipped_with
from sitegen import config
from sender import common, deliver, plan as plan_mod, render, settings as settings_mod
from test_morning import D, inputs  # noqa: F401
from test_morning_sender_plan import TEST_HOSTS, cfg_with, msite  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("America/Chicago")
DAY = D.isoformat()
AT_5 = datetime(2026, 11, 11, 5, 0, tzinfo=TZ)            # the run ends before send_at (07:00)
SECRET_BODY = "RESPONSE-BODY-WITH-jane.roe@example.com"
SECRET = b"made-up-test-key-not-a-real-one-32b"   # the HMAC key of the stamps (live: the provider's API key)
OTHER_SECRET = b"another-made-up-test-key-of-32-bytes"
EVERYONE = "every confirmed subscriber"
MODES = ("all", "stamp", "ids")


def stamp(key: str, day: str = DAY) -> str:
    return deliver.stamp_value(day, key, SECRET)


def settings(**kw) -> settings_mod.Settings:
    base = settings_mod.load(ROOT / "config" / "site.yml")
    hosts = base.link_hosts + tuple(TEST_HOSTS.split(","))
    return dataclasses.replace(base, **{"enabled": True, "canary_only": False, "link_hosts": hosts, **kw})


def stamp_mode(**kw) -> settings_mod.Settings:
    return settings(mode="stamp", **kw)


def sub(n: int, type_="regular", tags=("note-budget", "note-district-7", "vip"), **meta) -> dict:
    """A made-up subscriber as a provider would return one, with the fields the sender must never keep. `tags`
    are what the old form posted (and anything else); `meta` is other metadata. The sender reads neither."""
    return {"id": f"sub-{n:04d}-secret", "email_address": f"person{n}@example.com", "type": type_, "tags": list(tags),
            "metadata": dict(meta), "ip_address": "192.0.2.10", "notes": "made-up fixture person"}


CONFIRMED = {f"sub-{n:04d}-secret" for n in (1, 2, 3, 4, 7)}


def people() -> list[dict]:
    """Made-up subscribers: five confirmed (one with no tag at all), two who must get nothing."""
    return [sub(1), sub(2, tags=["note-zoning"]), sub(3, tags=["note-contracts"]), sub(4, favourite="blue"),
            sub(5, type_="unactivated"), sub(6, type_="unsubscribed"), sub(7, tags=[])]


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

    def emails(self, since):
        self._hit("emails")
        self.since = since
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
               "metadata": copy.deepcopy(payload["metadata"]), "archival_mode": payload["archival_mode"]}
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
        """Who a created email reaches, as the provider would work it out: no filter, every confirmed subscriber (the
        documented default, checked at the first send); a `stamp` filter, whoever holds exactly its value."""
        if "filters" not in payload:
            return {s["id"] for s in self.subs.values() if s["type"] == "regular"}
        rules = payload["filters"]["filters"]
        assert payload["filters"]["predicate"] == "and" and payload["filters"]["groups"] == [] and len(rules) == 1
        r = rules[0]
        assert r["field"] == "subscriber.metadata.note_edition" and r["operator"] == "equals"
        return {s["id"] for s in self.subs.values() if s["metadata"].get("note_edition") == r["value"]}


class NoSubscriberCalls(Fake):
    """`all` mode must never reach a subscriber endpoint: each raises, so a call would fail the run and the test."""

    def subscribers(self):
        raise AssertionError("provider.subscribers was called")

    def subscriber(self, subscriber_id):
        raise AssertionError("provider.subscriber was called")

    def set_metadata(self, subscriber_id, metadata, idempotency_key):
        raise AssertionError("provider.set_metadata was called")


@pytest.fixture(scope="module")
def plan(msite):  # noqa: F811
    return plan_mod.build(msite, D, cfg_with())["plan"]


def key_of(plan) -> str:
    return plan["editions"][0]["key"]


def go(plan, provider, s=None, now=AT_5, live=True, sleeps=None, canary_ids=None, secret=SECRET, clock=None):
    lines = []
    res = deliver.run(plan, s or settings(), provider=provider, live=live, now=now, canary_ids=canary_ids,
                      stamp_secret=secret, clock=clock,
                      sleep=(sleeps.append if sleeps is not None else lambda _s: None), out=lines.append)
    return res, "\n".join(lines)


def test_the_shipped_mode_is_all():
    """ADR 0004 decision 6 (manager, 2026-11-18): `all` is the daily mode; stamp stays for canary trials."""
    s = settings_mod.load(ROOT / "config" / "site.yml")
    assert s.mode == "all" and s.canary_only is False and common.MODES == MODES


# ------------------------------------------------------------------ nothing happens unless everything says go
def test_without_live_no_provider_call_at_all(plan):
    fake = Fake(people())
    res, text = go(plan, fake, live=False)
    assert res == deliver.Outcome(0, "dry-run") and fake.calls == []
    assert "dry run, no connection opened, nothing sent" in text and "1 edition(s)" in text
    assert f"a live run would create 1 email(s), to {EVERYONE}" in text           # done-when: the dry run says one email
    rehearsal = {**plan, "send": False, "reason": "disabled"}                      # a rehearsal plan: no email
    assert "would create 0 email(s)" in go(rehearsal, fake, live=False)[1] and fake.calls == []


def test_live_with_send_false_makes_no_provider_call(plan):
    for reason in ("quiet", "backfill", "disabled"):
        for mode in MODES:
            fake = Fake(people())
            res, _ = go({**plan, "send": False, "reason": reason}, fake, s=settings(mode=mode))
            assert (res.code, res.status, res.editions) == (0, "no-send", 0) and fake.calls == []
        fake = Fake(people())
        res, _ = go({**plan, "send": False, "reason": reason, "editions": []}, fake)
        assert (res.code, res.status) == (0, "no-send") and fake.calls == []


def test_a_disabled_config_sends_nothing_even_with_a_send_true_plan(plan, tmp_path):
    fake = Fake(people())
    res, text = go(plan, fake, s=settings(enabled=False))
    assert (res.code, res.status, res.editions, res.recipients) == (0, "disabled", 0, 0) and fake.calls == []
    assert "emails created 0; recipients: none from this run" in text
    assert "emails created 0; recipients in total 0" in go(plan, fake, s=stamp_mode(enabled=False))[1]
    off = settings_mod.load(shipped_with(tmp_path, enabled=False))     # the shipped file with the switch off
    off = dataclasses.replace(off, link_hosts=settings().link_hosts, canary_only=False)   # (the made-up site's links)
    assert off.enabled is False and go(plan, fake, s=off)[0].status == "disabled" and fake.calls == []


def test_live_without_a_provider_sends_nothing(plan):
    res, _ = go(plan, None)
    assert (res.code, res.status) == (2, "no-provider")


@pytest.mark.parametrize("now", [AT_5 - timedelta(days=1), AT_5 + timedelta(days=1),
                                 datetime(2026, 11, 12, 5, 30, tzinfo=ZoneInfo("UTC"))])   # 23:30 on Nov 11, Central
def test_a_plan_for_another_day_sends_nothing(plan, now):
    fake = Fake(people())
    if now.tzinfo.key == "UTC":
        res, _ = go(plan, fake, now=now)
        assert (res.code, res.status) == (3, "missed") and fake.calls == []            # still Nov 11 in the site's zone, but late
        return
    res, _ = go(plan, fake, now=now)
    assert (res.code, res.status) == (0, "wrong-date") and fake.calls == []


def test_the_day_is_judged_in_the_sites_zone_not_utc(plan):
    """00:30 Central on Nov 11 is 06:30 UTC on Nov 11; 23:30 Central on Nov 10 is 05:30 UTC on Nov 11."""
    fake = Fake(people())
    assert go(plan, fake, now=datetime(2026, 11, 11, 5, 30, tzinfo=ZoneInfo("UTC")))[0].status == "wrong-date"
    assert fake.calls == []
    assert go(plan, fake, now=datetime(2026, 11, 11, 6, 30, tzinfo=ZoneInfo("UTC")))[0].status == "sent"


@pytest.mark.parametrize("mode", ["all", "stamp"])
def test_past_latest_send_is_missed_and_sends_nothing(plan, mode):
    fake = Fake(people())
    s = settings(mode=mode)
    res, text = go(plan, fake, s=s, now=datetime(2026, 11, 11, 10, 1, tzinfo=TZ))
    assert (res.code, res.status) == (deliver.MISSED_EXIT, "missed") and deliver.MISSED_EXIT == 3 and fake.calls == [] and "missed" in text
    late = Fake(people())
    assert go(plan, late, s=s, now=datetime(2026, 11, 11, 10, 0, tzinfo=TZ))[0].status == "late"   # no margin left
    assert late.created == []
    assert go(plan, Fake(people()), s=s, now=datetime(2026, 11, 11, 9, 55, tzinfo=TZ))[0].status == "sent"


def test_a_clock_without_a_zone_sends_nothing(plan):
    fake = Fake(people())
    assert go(plan, fake, now=datetime(2026, 11, 11, 5, 0))[0].code == 2 and fake.calls == []


def test_a_plan_with_another_time_zone_sends_nothing(plan):
    fake = Fake(people())
    assert go({**plan, "timezone": "Pacific/Kiritimati"}, fake)[0].code == 2 and fake.calls == []


# ------------------------------------------------------------------ one edition for everyone (ADR 0004 decision 6)
def test_all_mode_creates_one_scheduled_email_with_no_filter_and_calls_no_subscriber_endpoint(plan):
    """Invariant one-edition: one scheduled email with no filter, the plan's one edition, and no subscriber listing,
    re-read or write (the fake raises on each: the run would fail and nothing would be created)."""
    fake = NoSubscriberCalls(people())
    res, text = go(plan, fake)
    assert (res.code, res.status, res.editions, res.recipients) == (0, "sent", 1, 0), text
    assert text == f"morning note {DAY}: sent; emails created 1; recipients: {EVERYONE}"
    assert fake.calls == ["emails", "create_email"]
    [p] = fake.created
    ed = plan["editions"][0]
    assert sorted(p) == ["archival_mode", "body", "metadata", "publish_date", "status", "subject"]     # no "filters"
    assert (p["subject"], p["body"]) == (ed["subject"], ed["body"])
    assert p["status"] == "scheduled" and p["publish_date"] == "2026-11-11T07:00:00-06:00" and p["archival_mode"] == "disabled"
    assert p["metadata"] == {"note_date": DAY, "note_edition": f"{DAY}.{ed['key']}", "note_sha256": plan["note_sha256"],
                             "note_plan": deliver.plan_digest(plan)}
    assert fake.audience(p) == CONFIRMED                                  # the provider's documented default
    assert fake.keys == [deliver.idempotency_key(DAY, ed["key"], "email")]
    # no secret is needed (nothing is stamped), and max_recipients does not apply (nothing is written to anyone)
    assert go(plan, NoSubscriberCalls(people()), s=settings(max_recipients=1), secret=None)[0] == deliver.Outcome(0, "sent", 1, 0)


def test_tags_and_metadata_never_change_the_audience_or_the_body(plan):
    """Nothing a subscriber or the form wrote changes who gets the note or what it says: in `all` mode nothing of
    theirs is read; in `stamp` mode every confirmed subscriber gets the one edition whatever their tags and metadata
    (lists, seats, a forged canary flag, a hostile tags field of any shape)."""
    hostile = [sub(1, tags=[]), sub(2, tags=["note-zoning", "note-district-7; drop"]), sub(3, tags="note-budget"),
               sub(4, tags=[1, None, {"name": "note-budget"}]), sub(5, tags=["note-contracts"], lists=["budget"], district=7, canary="yes"),
               sub(6, tags=[f"note-district-{n}" for n in range(1, 30)], note_edition="2026-11-11.x"),
               {**sub(7), "tags": None, "metadata": None}, {**sub(8), "metadata": "x"}]
    plain = [sub(n, tags=[]) for n in range(1, 9)]
    for mode in ("all", "stamp"):
        made = []
        for rows in (plain, hostile):
            fake = Fake(rows)
            res, text = go(plan, fake, s=settings(mode=mode))
            assert (res.status, res.editions) == ("sent", 1), text
            [p] = fake.created
            made.append(({k: v for k, v in p.items() if k != "filters"}, p.get("filters"), fake.audience(p)))
        assert made[0] == made[1]                                         # the same email, the same people
        assert made[1][2] == {f"sub-{n:04d}-secret" for n in range(1, 9)}
        if mode == "stamp":
            assert all(s["metadata"] == {"note_edition": stamp(key_of(plan))} for s in fake.subs.values())
    src = (ROOT / "sender" / "deliver.py").read_text(encoding="utf-8")
    assert '"tags"' not in src and "'tags'" not in src                   # no tag is read anywhere


def test_canary_only_without_stamp_mode_is_refused_before_any_call(plan):
    """An `all` email has no filter a canary list could narrow, so `canary_only: true` would mail everyone: refused
    ("bad-config", exit 2) before any provider call, with or without a canary list. `ids` the same."""
    for mode in ("all", "ids"):
        for ids in (None, frozenset(), frozenset({"sub-0001-secret"})):
            fake = Fake(people())
            res, text = go(plan, fake, s=settings(mode=mode, canary_only=True), canary_ids=ids)
            assert (res.code, res.status, res.editions) == (2, "bad-config", 0) and fake.calls == [], text
            assert "canary_only needs mode stamp" in text
    res, _ = go(plan, Fake(people()), s=stamp_mode(canary_only=True), canary_ids=frozenset({"sub-0001-secret"}))
    assert (res.status, res.recipients) == ("sent", 1)


def test_a_plan_with_two_editions_or_signatures_is_refused(plan):
    """check_plan holds the plan to schema /2: at most one edition, exactly one when send is true, and no field but
    the plan's own (the /1 plan's per-shape map, any extra key)."""
    second = {**copy.deepcopy(plan["editions"][0]), "key": "0123456789ab"}
    for bad in ({**plan, "editions": plan["editions"] + [second]},
                {**plan, "send": False, "reason": "disabled", "editions": plan["editions"] + [second]},
                {**plan, "editions": []},
                {**plan, "signatures": {}}, {**plan, "signatures": {"budget|-|-": key_of(plan)}},
                {**plan, "audience": "everyone"}, {**plan, "schema": "morning-send/1"},
                {k: v for k, v in plan.items() if k != "send_at"}):
        for mode in MODES:
            fake = Fake(people())
            res, text = go(bad, fake, s=settings(mode=mode))
            assert (res.code, res.status) == (2, "bad-plan") and fake.calls == [] and "nothing sent" in text
        with pytest.raises(deliver.PlanInvalid):
            deliver.check_plan(bad, settings().link_hosts, settings().link_urls)
    assert sorted(deliver.PLAN_FIELDS) == sorted(plan)                   # what the plan stage writes, exactly


def test_a_busy_day_is_one_email(plan):
    """sender/max-editions-busy-day, retired: a busy day is one email whatever the list's size. `all`: one create and
    no subscriber request; `stamp` with 190 confirmed subscribers: one email reaching exactly all of them. A second
    run sends nothing more. sender/run-time-budget, re-derived: each run fits the note job's timeout at the client's
    pace (buttondown.py MIN_INTERVAL, read from the file: this suite never imports the client)."""
    import yaml
    rows = [sub(n) for n in range(1, 191)]
    pace = float(re.search(r"(?m)^MIN_INTERVAL = ([0-9.]+)", (ROOT / "sender" / "buttondown.py").read_text()).group(1))
    job = yaml.safe_load((ROOT / ".github" / "workflows" / "daily-update.yml").read_text(encoding="utf-8"))
    timeout = job["jobs"]["note"]["timeout-minutes"] * 60
    shipped = settings_mod.load(ROOT / "config" / "site.yml")
    fake = NoSubscriberCalls(rows)
    res, text = go(plan, fake)
    assert (res.code, res.status, res.editions) == (0, "sent", 1) and len(fake.created) == 1, text
    assert len(fake.audience(fake.created[0])) == 190 and len(fake.calls) == 2
    # all: an email listing (one page a day; at most MAX_PAGES), one create and at most one take-back: seconds
    assert pace > 0 and (1 + 2) * pace < 60 and (deliver_pages() + 2) * pace < timeout
    fake = Fake(rows)
    res, text = go(plan, fake, s=stamp_mode())
    assert (res.code, res.status, res.editions, res.recipients) == (0, "sent", 1, 190), text
    assert len(fake.created) == 1 and fake.audience(fake.created[0]) == set(fake.subs)
    assert len(fake.calls) * pace < timeout / 2
    # a stamp trial at max_recipients: 2 listings, the email, 2 requests (re-read, stamp) per recipient
    assert (3 + 2 * shipped.max_recipients) * pace < timeout
    for mode in ("all", "stamp"):
        again, _ = go(plan, fake, s=settings(mode=mode)) if mode == "stamp" else go(plan, NoSubscriberCalls(rows, emails=fake.email_rows))
        assert (again.status, again.editions) == ("sent", 0)              # never twice
    assert len(fake.created) == 1


def deliver_pages() -> int:
    """buttondown.MAX_PAGES, read from the file (this suite never imports the client)."""
    return int(re.search(r"(?m)^MAX_PAGES = ([0-9_]+)", (ROOT / "sender" / "buttondown.py").read_text()).group(1))


def test_a_busy_day_cut_off_part_way_is_finished_by_a_rerun_without_sending_twice(plan):
    """stamp: a run stopped after 100 of 190 stamps (a provider error, the job's timeout) created no email; the next
    run of the same plan stamps everyone and creates the one email once. all: a run that died after the provider
    stored the email (its answer lost) is finished by a re-run that finds the email in the claim and creates none."""
    rows = [sub(n) for n in range(1, 191)]
    fake = Fake(rows, fail={"set_metadata": [None] * 100 + [deliver.ProviderError("stamp")]})
    res, _ = go(plan, fake, s=stamp_mode())
    assert (res.code, res.status, res.editions, len(fake.created)) == (1, "failed", 0, 0)
    assert sum(1 for s in fake.subs.values() if s["metadata"]) == 100
    res, _ = go(plan, fake, s=stamp_mode())
    assert (res.code, res.status, res.editions, res.recipients) == (0, "sent", 1, 190)
    assert len(fake.created) == 1 and fake.audience(fake.created[0]) == set(fake.subs)
    fake = NoSubscriberCalls(rows)
    real = fake.create_email

    def stored_then_lost(payload, key):
        real(payload, key)
        raise deliver.ProviderError("timed out")
    fake.create_email = stored_then_lost
    res, _ = go(plan, fake)
    assert (res.code, res.status, len(fake.created)) == (1, "failed", 1)
    fake.create_email = real
    res, text = go(plan, fake)
    assert (res.code, res.status, res.editions, len(fake.created)) == (0, "sent", 0, 1), text


@pytest.mark.parametrize("change", [
    {"schema": "morning-send/0"}, {"schema": "morning-send/1"}, {"date": "2026-11-11\n"}, {"send": "yes"}, {"editions": {}},
    {"signatures": {"budget|-|-": "ffffffffffff"}}, {"signatures": {}}, {"note_sha256": "x"},
    {"editions": [{"key": "../../etc", "subject": "s", "body": "b", "entry_ids": ["a"]}]},
    {"editions": [{"key": "0123456789ab", "subject": "s\nBcc: x", "body": "b", "entry_ids": ["a"]}]},
    {"editions": [{"key": "0123456789ab", "subject": "s", "body": "b", "entry_ids": ["a"], "filters": {}}]},
    {"editions": [{"key": "0123456789ab", "subject": "s", "body": "b" * 600_000, "entry_ids": ["a"]}]},
    {"editions": []},
    # plan-untrusted/log-injection: the plan comes from the job that parses untrusted PDFs, and the dry run prints
    # its reason and subjects into a public Actions log
    {"reason": "ok\n::error title=INJECTED::x"}, {"reason": "something"}, {"reason": None}, {"reason": "quiet"},
    {"send": False, "reason": "ok"},
    {"date": "٢٠٢٦-١١-١١"},          # Arabic-Indic digits match \d
])
def test_a_malformed_plan_sends_nothing(plan, change):
    fake = Fake(people())
    res, text = go({**plan, **change}, fake)
    assert (res.code, res.status) == (2, "bad-plan") and fake.calls == [] and "nothing sent" in text
    assert go([], fake)[0].code == 2 and go(None, fake)[0].code == 2


@pytest.mark.parametrize("subject", ["s\nBcc: x", "s ::error title=INJECTED::x", "s\u0085x", "s x",
                                     "s\x1b[2Kx", "s‮x", "s\x0bx", "s​x", "s x", ""])
def test_a_subject_that_is_not_one_printable_line_sends_nothing(plan, subject):
    """The edition stays valid but for its subject, so the subject check is what refuses it."""
    bad = copy.deepcopy(plan)
    bad["editions"][0]["subject"] = subject
    fake = Fake(people())
    res, text = go(bad, fake)
    assert (res.code, res.status) == (2, "bad-plan") and "subject" in text and fake.calls == []
    assert go(copy.deepcopy(plan), Fake(people()))[0].status == "sent"


@pytest.mark.parametrize("subject", [
    "Daylight morning note, November 12, 2026",                          # another day's
    "Daylight morning note, November 11, 2026 - URGENT: reply with your password",
    "Official notice from the City", "Daylight morning note,  November 11, 2026", "Daylight"])
@pytest.mark.parametrize("mode", MODES)
def test_a_subject_other_than_the_one_the_config_gives_sends_nothing(plan, subject, mode):
    """sender/plan-untrusted/subject-unchecked: the subject is rebuilt from the repository's site_name and
    text.subject for the plan's day; a printable but different one (the plan comes from the job that parses
    untrusted PDFs) is refused before any provider call, and in the dry run too."""
    assert plan["editions"][0]["subject"] == f"Daylight morning note, {render.day_words(DAY)}"
    bad = copy.deepcopy(plan)
    bad["editions"][0]["subject"] = subject
    fake = Fake(people())
    res, text = go(bad, fake, s=settings(mode=mode))
    assert (res.code, res.status) == (2, "bad-plan") and "subject" in text and fake.calls == []
    assert go(bad, fake, live=False)[0].status == "bad-plan"


def test_the_expected_subject_comes_from_the_repository_config_not_the_plan(plan):
    fake = Fake(people())
    res, _ = go(copy.deepcopy(plan), fake, s=settings(subject_template="{site_name} note for {date}"))
    assert (res.code, res.status) == (2, "bad-plan") and fake.calls == []
    res, _ = go(copy.deepcopy(plan), Fake(people()), s=settings(site_name="Elsewhere"))
    assert res.status == "bad-plan"
    for broken in ({"site_name": ""}, {"subject_template": ""}):
        assert go(copy.deepcopy(plan), Fake(people()), s=settings(**broken))[0].status == "bad-plan"


def test_deliver_rebuilds_the_subject_exactly_as_render_writes_it():
    ctx = {"site_name": "Day  light­", "text": {"subject": "{site_name}\tnote, {date} "}}
    for day in ("2026-01-01", "2026-11-11", "2028-02-29"):
        assert render.subject(ctx, day) == common.subject_line("{site_name}\tnote, {date} ", "Day  light­", day)
    s = settings_mod.load(ROOT / "config" / "site.yml")
    assert (s.site_name, s.subject_template) == (config.SITE["site_name"],
                                                 config.SITE["morning_note"]["sender"]["text"]["subject"])
    assert deliver.expected_subject(s, "2026-13-40") is None


def test_a_malformed_plan_is_refused_in_the_dry_run_too(plan):
    """The dry run prints the plan's reason and subjects; an injected line must never reach the log."""
    res, text = go({**plan, "reason": "ok\n::error title=INJECTED::x"}, Fake(), live=False)
    assert (res.code, res.status) == (2, "bad-plan") and "INJECTED" not in text


def test_the_shared_patterns_take_ascii_digits_only():
    arabic = "٢٠٢٦-١١-١١"
    assert common.DATE_RE.fullmatch(arabic) is None and common.DATE_RE.fullmatch("2026-11-11")
    assert deliver.STAMP_RE.fullmatch(arabic + ".0123456789ab.0123456789abcdef") is None
    assert common.TIME_RE.fullmatch("0٧:00") is None and common.TIME_RE.fullmatch("07:00")
    for rx in (common.DATE_RE, common.TIME_RE, deliver.STAMP_RE):
        assert "\\d" not in rx.pattern


@pytest.mark.parametrize("reason", ["quiet", "backfill", "disabled"])
def test_every_no_send_reason_the_plan_stage_writes_is_accepted(plan, reason):
    assert deliver.REASONS == ("ok", "quiet", "backfill", "disabled")
    res, text = go({**plan, "send": False, "reason": reason}, Fake(), live=False)
    assert res.status == "dry-run" and f"({reason})" in text


# ------------------------------------------------------------------ stamp (canary trials) and ids
def test_stamp_sends_one_scheduled_email_per_edition_to_exactly_its_people(plan):
    """A canary trial: the one edition, one scheduled email filtered on its stamp, reaching exactly the canaries who
    are confirmed; without canary_only, exactly every confirmed subscriber."""
    key = key_of(plan)
    fake = Fake(people())
    res, text = go(plan, fake, s=stamp_mode(canary_only=True),
                   canary_ids=frozenset({"sub-0001-secret", "sub-0003-secret", "sub-0005-secret", "sub-9999-secret"}))
    assert (res.code, res.status, res.editions, res.recipients) == (0, "sent", 1, 2)
    assert text == f"morning note {DAY}: sent; emails created 1; recipients in total 2"
    [p] = fake.created
    assert fake.audience(p) == {"sub-0001-secret", "sub-0003-secret"}
    assert p["filters"]["filters"][0]["value"] == stamp(key)                     # exactly "<D>.<key>.<mac>"
    assert p["status"] == "scheduled" and p["publish_date"] == "2026-11-11T07:00:00-06:00"
    assert p["archival_mode"] == "disabled"
    assert p["metadata"] == {"note_date": DAY, "note_edition": stamp(key), "note_sha256": plan["note_sha256"],
                             "note_plan": deliver.plan_digest(plan)}
    assert (p["subject"], p["body"]) == (plan["editions"][0]["subject"], plan["editions"][0]["body"])
    assert sorted(p) == ["archival_mode", "body", "filters", "metadata", "publish_date", "status", "subject"]
    assert not fake.sent_drafts and len(set(fake.keys)) == len(fake.keys) == 3        # 2 stamps + 1 email
    fake = Fake(people())
    res, _ = go(plan, fake, s=stamp_mode())
    assert (res.editions, res.recipients) == (1, 5) and fake.audience(fake.created[0]) == CONFIRMED


def test_stamp_rereads_each_subscriber_just_before_the_write(plan):
    """L2: each subscriber is read again just before the write, not trusted from the listing. Someone who is gone or
    no longer confirmed is not stamped (they get nothing today) and is not counted; a change of tags or other
    metadata keeps them in."""
    def change(subs):
        subs["sub-0004-secret"]["tags"].append("another-tag")                     # kept
        subs["sub-0004-secret"]["metadata"]["favourite"] = "green"
        subs["sub-0002-secret"]["type"] = "unsubscribed"                           # left: skipped
        del subs["sub-0003-secret"]                                                # gone: skipped
    fake = Fake(people())
    fake.after_listing = change
    res, _ = go(plan, fake, s=stamp_mode())
    assert (res.status, res.editions, res.recipients) == ("sent", 1, 3)
    assert fake.subs["sub-0004-secret"]["metadata"] == {"note_edition": stamp(key_of(plan))}
    assert "note_edition" not in fake.subs["sub-0002-secret"]["metadata"]
    assert fake.audience(fake.created[0]) == {"sub-0001-secret", "sub-0004-secret", "sub-0007-secret"}
    assert fake.calls.count("subscriber") == 5                                     # one re-read per recipient


def test_a_failed_reread_stops_before_the_write(plan):
    fake = Fake(people(), fail={"subscriber": deliver.ProviderError(SECRET_BODY)})
    res, text = go(plan, fake, s=stamp_mode())
    assert (res.code, res.status, res.editions) == (1, "failed", 0) and "set_metadata" not in fake.calls
    assert "subscriber re-read" in text and SECRET_BODY not in text


def test_stamp_write_replaces_the_metadata_with_the_stamp_alone_and_touches_nobody_else(plan):
    """sender/stamp-write-replaces: the provider's PATCH replaces the whole object (T4.0 probe), so the write is
    exactly {"note_edition": <stamp>}. A key the public form wrote (a forged note_edition, "canary") is dropped by
    it; the tags are never written."""
    before = {s["id"]: copy.deepcopy(s) for s in people()}
    before["sub-0001-secret"]["metadata"].update(note_edition=f"{DAY}.{'0' * 12}.{'0' * 16}", canary="yes")
    fake = Fake(before.values())
    go(plan, fake, s=stamp_mode())
    for sid in CONFIRMED:
        assert fake.subs[sid]["metadata"] == {"note_edition": stamp(key_of(plan))}
    assert fake.subs["sub-0004-secret"]["tags"] == before["sub-0004-secret"]["tags"]
    for sid in ("sub-0005-secret", "sub-0006-secret"):
        assert fake.subs[sid] == before[sid]                           # unconfirmed, unsubscribed: untouched
    for sid, s in fake.subs.items():                                   # only metadata ever changes
        assert {k: v for k, v in s.items() if k != "metadata"} == {k: v for k, v in before[sid].items() if k != "metadata"}


@pytest.mark.parametrize("mode", ["all", "stamp"])
@pytest.mark.parametrize("now, want", [
    (datetime(2026, 11, 11, 8, 15, tzinfo=TZ), "2026-11-11T08:20:00-06:00"),
    (datetime(2026, 11, 11, 6, 57, tzinfo=TZ), "2026-11-11T07:02:00-06:00"),
    (datetime(2026, 11, 11, 6, 55, tzinfo=TZ), "2026-11-11T07:00:00-06:00"),
    (datetime(2026, 11, 11, 9, 55, tzinfo=TZ), "2026-11-11T10:00:00-06:00")])
def test_a_late_run_schedules_the_email_a_margin_ahead(plan, now, want, mode):
    """provider-echo/immediate-after-send_at: never "now", so the echo check (and a take-back) runs before the email
    can leave: publish_date = max(send_at, now + 5 minutes). A run that starts before latest_send still sends."""
    assert deliver.PUBLISH_MARGIN == timedelta(minutes=5)
    fake = Fake(people())
    assert go(plan, fake, s=settings(mode=mode), now=now)[0].status == "sent"
    assert [p["publish_date"] for p in fake.created] == [want]
    assert [p["status"] for p in fake.created] == ["scheduled"]


def clock_of(*times):
    """A clock that gives these times in turn, then keeps giving the last."""
    left = list(times)
    return lambda: left.pop(0) if len(left) > 1 else left[0]


def test_publish_date_is_worked_out_from_the_clock_just_before_the_create(plan):
    """provider-echo L1: stamping can take minutes, so the publish_date comes from the clock just before the email
    is created (after the stamps), not from the run's start."""
    at = lambda h, m: datetime(2026, 11, 11, h, m, tzinfo=TZ)              # noqa: E731
    for mode in ("all", "stamp"):
        fake = Fake(people())
        res, _ = go(plan, fake, s=settings(mode=mode), now=None, clock=clock_of(at(6, 50), at(7, 10)))
        assert res.status == "sent" and [p["publish_date"] for p in fake.created] == ["2026-11-11T07:15:00-06:00"]


def test_an_edition_that_could_not_leave_by_latest_send_stops_the_run(plan):
    """Under the margin: the email would be scheduled after latest_send, so it is not created; exit 2."""
    at = lambda h, m: datetime(2026, 11, 11, h, m, tzinfo=TZ)              # noqa: E731
    for mode in ("all", "stamp"):
        fake = Fake(people())
        res, text = go(plan, fake, s=settings(mode=mode), now=None, clock=clock_of(at(5, 0), at(9, 56)))
        assert (res.code, res.status, res.editions) == (2, "late", 0) and fake.created == []
        assert "latest_send" in text
        fake = Fake(people())
        assert go(plan, fake, s=settings(mode=mode), now=at(9, 58))[0].status == "late" and fake.created == []


def test_ids_mode_rechecks_latest_send_before_the_draft_and_the_send(plan):
    """sender/never-late/ids-no-recheck: `ids` mails at once, so a run that crosses latest_send stops there: no
    draft is created, or no draft is sent after it (exit 2, "late")."""
    at = lambda h, m: datetime(2026, 11, 11, h, m, tzinfo=TZ)              # noqa: E731
    s = settings(mode="ids")
    fake = Fake(people())
    res, text = go(plan, fake, s=s, now=None, clock=clock_of(at(5, 0), at(10, 0) + timedelta(seconds=1)))
    assert (res.code, res.status, res.editions) == (2, "late", 0) and fake.created == [] and "latest_send" in text
    # past latest_send between the draft and its send: the draft is made (it claims the edition), never sent
    fake = Fake(people())
    res, _ = go(plan, fake, s=s, now=None, clock=clock_of(at(5, 0), at(9, 59), at(10, 0) + timedelta(seconds=1)))
    assert (res.code, res.status, res.editions) == (2, "late", 0)
    assert len(fake.created) == 1 and fake.sent_drafts == []
    fake = Fake(people())
    assert go(plan, fake, s=s, now=None, clock=clock_of(at(5, 0), at(9, 0)))[0].editions == 1


def test_ids_mode_drafts_then_sends_to_ids_and_never_writes_a_subscriber(plan):
    before = people()
    fake = Fake(before)
    res, _ = go(plan, fake, s=settings(mode="ids"))
    assert (res.status, res.editions, res.recipients) == ("sent", 1, 5)
    assert "set_metadata" not in fake.calls and list(fake.subs.values()) == before
    assert all(p["status"] == "draft" and "filters" not in p and "publish_date" not in p for p in fake.created)
    [(eid, ids)] = fake.sent_drafts
    assert fake.created[0]["metadata"]["note_edition"] == f"{DAY}.{key_of(plan)}"          # ids: no mac
    assert set(ids) == CONFIRMED and len(ids) == 5


def test_an_edition_with_no_recipient_creates_no_email(plan):
    """stamp and ids: nobody confirmed (or no canary confirmed) is a quiet morning: no email, exit 0."""
    for mode in ("stamp", "ids"):
        fake = Fake([sub(5, type_="unactivated"), sub(6, type_="unsubscribed")])
        res, _ = go(plan, fake, s=settings(mode=mode))
        assert (res.code, res.status, res.editions) == (0, "sent", 0) and fake.created == []
        assert "set_metadata" not in fake.calls


# ------------------------------------------------------------------ who may be mailed (stamp)
@pytest.mark.parametrize("type_", ["unactivated", "unsubscribed", "removed", "undeliverable", "spammy", "", None, "REGULAR"])
def test_only_regular_subscribers_are_recipients(plan, type_):
    fake = Fake([sub(1, type_=type_), sub(2)])
    go(plan, fake, s=stamp_mode())
    assert [fake.audience(p) for p in fake.created] == [{"sub-0002-secret"}]
    assert "note_edition" not in fake.subs["sub-0001-secret"]["metadata"]


def test_canary_only_reaches_only_the_ids_the_environment_names(plan, tmp_path):
    """audience/canary-self-set: a subscriber writes their own metadata through the public form, so a canary is
    named only by MORNING_NOTE_CANARY_IDS (the note job's environment), never by metadata."""
    rows = [sub(1), sub(2), sub(3, canary="1"), sub(4, canary=1), sub(5, type_="unactivated")]
    fake = Fake(rows)
    res, _ = go(plan, fake, s=stamp_mode(canary_only=True), canary_ids=frozenset({"sub-0002-secret", "sub-0005-secret"}))
    assert (res.editions, res.recipients) == (1, 1)
    assert [fake.audience(p) for p in fake.created] == [{"sub-0002-secret"}]
    # the deliver job's reader honours the switch both ways (Brian, 2026-11-16: the shipped value is false)
    assert settings_mod.load(shipped_with(tmp_path, canary_only=True, mode="stamp")).canary_only is True
    assert settings_mod.load(shipped_with(tmp_path, canary_only=False)).canary_only is False


@pytest.mark.parametrize("ids", [None, frozenset()])
def test_canary_only_with_no_canary_list_sends_to_nobody(plan, ids):
    fake = Fake([sub(1, canary="1"), sub(2, canary="1")])
    res, text = go(plan, fake, s=stamp_mode(canary_only=True), canary_ids=ids)
    assert (res.code, res.status, res.editions, res.recipients) == (0, "no-canary", 0, 0)
    assert fake.calls == [] and "MORNING_NOTE_CANARY_IDS" in text


def test_metadata_canary_is_not_read_at_all():
    r = deliver.recipient(sub(1, canary="1"))
    assert not hasattr(r, "canary")
    src = (ROOT / "sender" / "deliver.py").read_text(encoding="utf-8")
    assert 'get("canary")' not in src and "['canary']" not in src


@pytest.mark.parametrize("text, want", [
    (None, None), ("", frozenset()), ("  ", frozenset()), ("a1b2-c3", frozenset({"a1b2-c3"})),
    ("a, b\nc", frozenset({"a", "b", "c"})), ("a\x1cb\r\n", frozenset({"a", "b"})),
    ("a,\x1f\v,b", None)])
def test_the_canary_list_is_read_from_the_environment_text(text, want):
    if want is None and text is not None:                  # an empty entry between ASCII separators: an error
        with pytest.raises(deliver.PlanInvalid):
            deliver.canary_ids(text)
    else:
        assert deliver.canary_ids(text) == want


@pytest.mark.parametrize("text", ["a;b", "a b@example.com", "x" * 65, "a,,b", "١",
                                  # note-job/mask-unicode-ws: Unicode whitespace never separates ids (bash's mask
                                  # step does not split on it), so an id holding one is an error
                                  "a b", " a", "a ", "a, ,b", "a b", "a\x85b",
                                  "a,　b"])
def test_a_malformed_canary_list_is_an_error(text):
    with pytest.raises(deliver.PlanInvalid):
        deliver.canary_ids(text)


def test_the_cli_reads_the_canary_list_from_the_environment(monkeypatch):
    import sender.__main__ as cli
    monkeypatch.setenv("MORNING_NOTE_CANARY_IDS", "abc,def")
    assert cli._canary_from_env() == frozenset({"abc", "def"})
    monkeypatch.delenv("MORNING_NOTE_CANARY_IDS")
    assert cli._canary_from_env() is None


def test_a_subscriber_row_that_is_not_a_record_is_skipped(plan):
    for raw in (None, "x", [], {"type": "regular"}, {"type": "regular", "id": 7}, {"type": "regular", "id": ""}):
        assert deliver.recipient(raw) is None
    assert deliver.recipient({"type": "regular", "id": "a", "metadata": "x", "tags": "x"}) == deliver.Recipient(id="a")


def test_the_stamp_is_unguessable_from_the_public_note_and_stable_across_runs():
    """audience/stamp-self-set-race: "<day>.<key>" alone is computable from morning/<D>.json, so the stamp adds
    HMAC-SHA256(secret, "<day>.<key>")[:16]; the same secret gives the same stamp on a re-run."""
    import hashlib
    import hmac
    key = "0123456789ab"
    want = f"{DAY}.{key}." + hmac.new(SECRET, f"{DAY}.{key}".encode(), hashlib.sha256).hexdigest()[:16]
    assert deliver.stamp_value(DAY, key, SECRET) == want == stamp(key)
    assert deliver.STAMP_RE.fullmatch(want) and deliver.stamp_value(DAY, key, OTHER_SECRET) != want
    for secret in (b"", None, "text", SECRET[:31], b"x" * 31, SECRET.decode()):
        with pytest.raises(deliver.PlanInvalid):
            deliver.stamp_value(DAY, key, secret)


@pytest.mark.parametrize("short", [b"", b"x" * 31, SECRET[:31], "a-text-secret-of-more-than-32-chars"])
def test_a_stamp_secret_under_32_bytes_sends_nothing_and_nothing_stands_in(plan, short):
    """Low (b): a short key would make the stamp guessable; no other value is tried in its place."""
    assert len(SECRET) >= 32 and len(OTHER_SECRET) >= 32
    fake = Fake(people())
    res, _ = go(plan, fake, s=stamp_mode(), secret=short)
    assert (res.code, res.status) == (2, "no-secret") and fake.calls == []
    assert go(plan, Fake(people()), s=stamp_mode(), secret=b"x" * 32)[0].status == "sent"


def test_stamp_mode_without_the_secret_sends_nothing(plan):
    fake = Fake(people())
    res, text = go(plan, fake, s=stamp_mode(), secret=None)
    assert (res.code, res.status) == (2, "no-secret") and fake.calls == []
    assert go(plan, Fake(people()), s=settings(mode="ids"), secret=None)[0].status == "sent"   # ids needs none
    assert go(plan, Fake(people()), secret=None)[0].status == "sent"                         # nor does all


@pytest.mark.parametrize("value", ["2026-11-11", "x 2026-11-11 y", "2026-11-11.{k}", "2026-11-11.{k}.0000000000000000",
                                   "2026-11-11.ffffffffffff.0123456789abcdef", ["2026-11-11.{k}"], 20261111])
def test_a_value_that_is_not_an_expected_stamp_neither_blocks_the_run_nor_gets_mail(plan, value):
    """Narrowed stray check: only exactly the expected stamp for today counts, so nobody can stop every send by
    putting today's date in their own metadata, and a guessed stamp is mailed nothing."""
    k = key_of(plan)
    value = value.replace("{k}", k) if isinstance(value, str) else [v.replace("{k}", k) for v in value] if isinstance(value, list) else value
    fake = Fake(people() + [sub(9, note_edition=value)])                # not a canary: mailed nothing
    res, _ = go(plan, fake, s=stamp_mode(canary_only=True), canary_ids=frozenset(CONFIRMED))
    assert (res.code, res.status, res.editions, res.recipients) == (0, "sent", 1, 5)
    assert all("sub-0009-secret" not in fake.audience(p) for p in fake.created)


def test_a_subscriber_holding_todays_stamp_outside_its_audience_stops_the_run(plan):
    """audience/stamp-self-set: the provider's filter mails whoever holds the stamp, so any subscriber holding
    today's stamp who is not in this run's audience (not a canary, here) stops the run before any write."""
    value = stamp(key_of(plan))
    for rows, ids in (([sub(1), sub(9, note_edition=value)], {"sub-0001-secret"}),
                      (people() + [sub(9, note_edition=value)], CONFIRMED)):
        fake = Fake(rows)
        res, text = go(plan, fake, s=stamp_mode(canary_only=True), canary_ids=frozenset(ids))
        assert (res.code, res.status, res.editions) == (2, "stray-stamp", 0), text
        assert fake.calls == ["emails", "subscribers"] and "sub-0009" not in text


def test_a_holder_of_todays_stamp_in_the_audience_is_not_a_stray(plan):
    """A canary who already holds today's stamp (an earlier run of this plan stamped them, then died before the
    email) is in the audience, so is no stray: the run stamps and sends as usual."""
    fake = Fake([sub(1, note_edition=stamp(key_of(plan))), sub(2)])
    res, text = go(plan, fake, s=stamp_mode(canary_only=True), canary_ids=frozenset({"sub-0001-secret", "sub-0002-secret"}))
    assert (res.code, res.status, res.editions, res.recipients) == (0, "sent", 1, 2), text
    assert fake.audience(fake.created[0]) == {"sub-0001-secret", "sub-0002-secret"}


def test_the_stray_rule_itself_is_unchanged():
    """`_strays` as before one edition (architecture: unchanged): in the audience or of a created edition, skipped;
    of an edition nobody gets this run, skipped; outside it with no other edition to write over, None (the run
    stops); in another edition's audience not yet created, returned to be written over first."""
    a, b = deliver.Recipient("a"), deliver.Recipient("b")
    expected = {"S1": "k1", "S2": "k2"}
    assert deliver._strays([("a", "S1")], {"k1": [a]}, expected, set()) == []
    assert deliver._strays([("x", "S1")], {"k1": [a]}, expected, {"k1"}) == []
    assert deliver._strays([("x", "S2")], {"k1": [a]}, expected, set()) == []
    assert deliver._strays([("x", "S1"), ("y", "nope"), ("z", 7)], {"k1": [a]}, expected, set()) is None
    assert deliver._strays([("b", "S1")], {"k1": [a], "k2": [b]}, expected, set()) == [("b", "k2")]


@pytest.mark.parametrize("now_type", ["unsubscribed", "premium", "regular"])
@pytest.mark.parametrize("when", ["before 07:00", "after 07:00, A already sent"])
def test_a_rerun_after_a_stamped_subscriber_changed_type_is_not_a_stray(plan, now_type, when):
    """audience/stamp-rerun-false-stray and the invariant "one stamp, one email a day": run 1 stamped sub 1 and
    created the email A; sub 1's type then changed. Run 2 of the same plan neither stops at "stray-stamp" nor
    writes sub 1 again: they keep A's stamp. After 07:00 (A already sent) the same holds: no second email that day."""
    fake = Fake(people())
    assert go(plan, fake, s=stamp_mode())[0].editions == 1
    a = stamp(key_of(plan))
    fake.subs["sub-0001-secret"]["type"] = now_type
    now = AT_5
    if when.startswith("after"):
        for row in fake.email_rows:
            row["status"] = "sent"
        now = datetime(2026, 11, 11, 7, 30, tzinfo=TZ)
    writes = fake.calls.count("set_metadata")
    res, text = go(plan, fake, s=stamp_mode(), now=now)
    assert (res.code, res.status, res.editions) == (0, "sent", 0), text
    assert fake.calls.count("set_metadata") == writes                  # sub 1 is never stamped again
    assert fake.subs["sub-0001-secret"]["metadata"] == {"note_edition": a}
    assert len(fake.created) == 1


def test_a_holder_of_a_created_edition_is_left_out_of_a_new_one_with_other_people(plan):
    """The invariant with company: after run 1 created the email, a new subscriber confirms. Run 2 of the same plan
    creates nothing: the day's one email exists, so the newcomer is not stamped (and so not mailed today), and the
    holders are not written again."""
    fake = Fake(people())
    go(plan, fake, s=stamp_mode())
    fake.subs["sub-0010-secret"] = sub(10)
    writes = fake.calls.count("set_metadata")
    res, _ = go(plan, fake, s=stamp_mode())
    assert (res.status, res.editions, res.recipients) == ("sent", 0, 0)
    assert fake.calls.count("set_metadata") == writes and "note_edition" not in fake.subs["sub-0010-secret"]["metadata"]
    assert len(fake.created) == 1 and "sub-0010-secret" not in fake.audience(fake.created[0])


def test_the_stamp_idempotency_key_carries_the_stamp_held_now(plan):
    """sender/stamp-idem-replay: the same stamp written over a different held value uses another key, so the
    provider never answers it from memory without writing; over the same held value, the same key."""
    fake = Fake([sub(1)], fail={"create_email": [deliver.ProviderError("x")] * 2})
    go(plan, fake, s=stamp_mode())
    first = fake.keys[-1]
    fake.subs["sub-0001-secret"]["metadata"] = {}                            # held as before run 1: same key
    go(plan, fake, s=stamp_mode())
    assert fake.keys[-1] == first
    fake.subs["sub-0001-secret"]["metadata"] = {"note_edition": "something the form wrote"}
    go(plan, fake, s=stamp_mode())
    assert fake.keys[-2] != first and fake.calls.count("create_email") == 3


@pytest.mark.parametrize("type_", ["premium", "gifted", "trialed", "churning", "past_due", "unactivated", None])
def test_a_stamp_held_by_a_subscriber_of_any_type_counts(plan, type_):
    """L3: the provider's filter may reach receiving types other than "regular" (paying, gifted, trial), which are
    never recipients here, so the stray check reads every row of the listing, whatever its type."""
    fake = Fake(people() + [sub(9, type_=type_, note_edition=stamp(key_of(plan)))])
    res, _ = go(plan, fake, s=stamp_mode())
    assert (res.code, res.status) == (2, "stray-stamp") and "set_metadata" not in fake.calls


def test_a_paying_or_gifted_subscriber_is_never_a_recipient(plan):
    """No paid tier exists; such a subscriber gets nothing (never a wrong email) until the sender learns the type."""
    fake = Fake([sub(1, type_="premium"), sub(2, type_="gifted"), sub(3)])
    res, _ = go(plan, fake, s=stamp_mode())
    assert (res.editions, res.recipients) == (1, 1) and [fake.audience(p) for p in fake.created] == [{"sub-0003-secret"}]


def test_stamps_from_an_earlier_run_of_the_same_plan_or_another_day_are_fine(plan):
    fake = Fake(people(), fail={"create_email": [deliver.ProviderError("x")]})
    assert go(plan, fake, s=stamp_mode())[0].status == "failed"            # stamped everyone, no email
    fake.fail = {}
    assert go(plan, fake, s=stamp_mode())[0].status == "sent"              # their stamps are in `to`: fine
    old = sub(9, note_edition="2026-11-10.0123456789ab")                     # yesterday's stamp
    unconfirmed = sub(8, type_="unactivated", note_edition="2026-11-11")
    assert go(plan, Fake(people() + [old, unconfirmed]), s=stamp_mode())[0].status == "sent"
    assert go(plan, Fake(people() + [unconfirmed]), s=settings(mode="ids"))[0].status == "sent"


def test_a_subscriber_listed_twice_is_one_recipient(plan):
    row = sub(1)
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
    fake = Fake(people())
    res, text = go({**plan, "timezone": zone}, fake, s=settings(timezone=zone))
    assert (res.code, res.status) == (2, "failed") and "time zone" in text and fake.calls == []


def test_the_address_is_dropped_at_the_boundary(plan):
    r = deliver.recipient(sub(1))
    assert "example.com" not in repr(dataclasses.asdict(r)) and "sub-0001" not in repr(r)
    assert sorted(f.name for f in dataclasses.fields(r)) == ["id"]


def test_over_max_recipients_sends_nothing(plan):
    fake = Fake([sub(n) for n in range(1, 6)])
    res, _ = go(plan, fake, s=stamp_mode(max_recipients=4))
    assert (res.code, res.status) == (2, "over-limit") and fake.calls == ["emails", "subscribers"]
    assert go(plan, Fake([sub(n) for n in range(1, 5)]), s=stamp_mode(max_recipients=4))[0].status == "sent"


# ------------------------------------------------------------------ never twice
@pytest.mark.parametrize("mode", MODES)
def test_a_second_run_of_the_same_plan_sends_nothing_new(plan, mode):
    fake = Fake(people())
    assert go(plan, fake, s=settings(mode=mode))[0].editions == 1
    created, drafts = len(fake.created), len(fake.sent_drafts)
    writes = fake.calls.count("set_metadata")
    res, _ = go(plan, fake, s=settings(mode=mode), now=AT_5 + timedelta(hours=1))
    assert (res.code, res.status, res.editions, res.recipients) == (0, "sent", 0, 0)
    assert (len(fake.created), len(fake.sent_drafts), fake.calls.count("set_metadata")) == (created, drafts, writes)


def test_a_run_that_died_after_edition_1_of_3_finishes_2_and_3_only(plan):
    """One edition now. stamp: a run that died part way through the stamps (the third write) created no email; the
    re-run stamps the rest and creates the one email once. all: a run that died after the create (the answer lost)
    leaves the day claimed, so the re-run creates nothing."""
    fake = Fake(people(), fail={"set_metadata": [None, None, deliver.ProviderError(SECRET_BODY)]})
    res, text = go(plan, fake, s=stamp_mode())
    assert (res.code, res.status, res.editions) == (1, "failed", 0) and fake.created == [] and SECRET_BODY not in text
    fake.fail = {}
    res, _ = go(plan, fake, s=stamp_mode())
    assert (res.code, res.status, res.editions, res.recipients) == (0, "sent", 1, 5) and len(fake.created) == 1
    assert fake.audience(fake.created[0]) == CONFIRMED
    fake = Fake(people(), echo=lambda r: (_ for _ in ()).throw(deliver.ProviderError(SECRET_BODY)))
    res, text = go(plan, fake)
    assert (res.code, res.status, len(fake.created)) == (1, "failed", 1) and SECRET_BODY not in text
    fake.echo = None
    res, _ = go(plan, fake)
    assert (res.code, res.status, res.editions, len(fake.created)) == (0, "sent", 0, 1)


def test_ids_mode_never_resends_a_draft_whose_send_failed(plan):
    """Never twice before never missed: the draft is the claim, so the re-run skips that edition."""
    fake = Fake(people(), fail={"send_draft": [deliver.ProviderError("x")]})
    res, _ = go(plan, fake, s=settings(mode="ids"))
    assert (res.code, res.editions) == (1, 0) and len(fake.created) == 1 and fake.sent_drafts == []
    res, _ = go(plan, fake, s=settings(mode="ids"))
    assert res.editions == 0 and len(fake.created) == 1 and fake.sent_drafts == []


def test_a_day_claimed_by_a_different_note_sends_nothing(plan):
    other = {"id": "em-9", "status": "scheduled", "metadata": {"note_date": DAY, "note_edition": f"{DAY}.aaaaaaaaaaaa", "note_sha256": "0" * 64}}
    for mode in MODES:
        fake = Fake(people(), emails=[other])
        res, _ = go(plan, fake, s=settings(mode=mode))
        assert (res.code, res.status, res.editions) == (0, "claimed", 0) and fake.calls == ["emails"]
    # one email of ours and one of another plan on the same day: still nothing
    ours = {"id": "em-8", "status": "scheduled", "metadata": {"note_date": DAY, "note_edition": f"{DAY}.bbbbbbbbbbbb", "note_sha256": plan["note_sha256"]}}
    fake = Fake(people(), emails=[ours, other])
    assert go(plan, fake)[0].status == "claimed" and fake.calls == ["emails"]


def test_another_plan_of_the_same_note_claims_the_day(plan):
    """sender/claim-plan-identity: a second plan of the same note (other code or config: here the edition lists an
    extra entry) has the same note digest but another plan digest, so it takes nothing of the first plan's as its
    own and sends nothing."""
    fake = Fake(people())
    assert go(plan, fake)[0].editions == 1
    other = copy.deepcopy(plan)
    other["editions"][0]["entry_ids"].append("county/item/x/2026-11-16-formal")
    assert deliver.plan_digest(other) != deliver.plan_digest(plan) and other["note_sha256"] == plan["note_sha256"]
    res, _ = go(other, fake)
    assert (res.code, res.status, res.editions, len(fake.created)) == (0, "claimed", 0, 1)
    assert {p["metadata"]["note_plan"] for p in fake.created} == {deliver.plan_digest(plan)}
    assert go(plan, fake)[0].status == "sent" and len(fake.created) == 1          # the first plan: nothing twice


def test_the_claim_lists_emails_since_yesterday_in_the_sites_zone(plan):
    """sender/claim-listing-unbounded: the claim asks for emails created since yesterday, so every email of today is
    in it and the listing does not grow with the history."""
    fake = Fake(people())
    go(plan, fake)
    assert fake.since == "2026-11-10"
    fake = Fake(people())
    go(plan, fake, now=datetime(2026, 11, 11, 0, 30, tzinfo=TZ))         # 06:30 UTC: still Nov 11 in the zone
    assert fake.since == "2026-11-10"


def test_emails_of_other_days_and_other_kinds_do_not_claim_the_day(plan):
    rows = [{"id": "em-1", "status": "sent", "metadata": {"note_date": "2026-11-10", "note_sha256": "0" * 64}},
            {"id": "em-2", "status": "sent", "metadata": {}}, {"id": "em-4", "status": "sent", "metadata": None}]
    for mode in MODES:
        assert go(plan, Fake(people(), emails=rows), s=settings(mode=mode))[0].editions == 1


def test_a_listed_email_without_a_metadata_key_fails_closed(plan):
    """audience/provider-echo: a listing whose rows lack `metadata` cannot tell a claimed day from a free one."""
    fake = Fake(people(), emails=[{"id": "em-3", "status": "sent"}])
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
    lambda r: {**r, "id": ""},
    # render/archival-not-echoed: stored on the public archive (any mode but the "disabled" sent)
    lambda r: {**r, "archival_mode": "enabled"}, lambda r: {**r, "archival_mode": None}])
def test_stamp_unschedules_an_email_the_provider_stored_differently(plan, echo):
    """audience/provider-echo: the stored email decides who gets it, so it must echo exactly the filter, status and
    claim deliver sent; otherwise it is taken back to a draft and the run fails."""
    fake = Fake(people(), echo=echo)
    res, text = go(plan, fake, s=stamp_mode())
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


ONE_RULE = {"filters": [{"field": "subscriber.metadata.note_edition", "operator": "equals", "value": "x"}],
            "groups": [], "predicate": "and"}


@pytest.mark.parametrize("echo", [
    lambda r: {**r, "filters": ONE_RULE}, lambda r: {**r, "filters": {"filters": [], "groups": [ONE_RULE], "predicate": "and"}},
    lambda r: {**r, "filters": {"filters": [], "groups": [], "predicate": "or"}}, lambda r: {**r, "filters": {}},
    lambda r: {**r, "filters": []}, lambda r: {**r, "filters": "everyone"},
    lambda r: {**r, "filters": {"filters": [], "groups": [], "predicate": "and", "extra": 1}},
    lambda r: {**r, "status": "draft"}, lambda r: {**r, "metadata": {}}, lambda r: {**r, "archival_mode": "enabled"},
    lambda r: r["id"], lambda r: None])
def test_all_mode_takes_back_a_stored_email_with_a_filter(plan, echo):
    """audience/provider-echo in `all` mode: no filter is sent, so the stored email must carry none (absent, null or
    exactly the empty shape the probe saw). One with any rule or group, another shape, another status or claim is
    taken back to a draft and the run fails."""
    fake = NoSubscriberCalls(people(), echo=echo)
    res, text = go(plan, fake)
    assert (res.code, res.status, res.editions) == (1, "failed", 0) and "email check" in text
    got = echo(copy.deepcopy(fake.email_rows[0]))
    if (isinstance(got, dict) and got.get("id")) or isinstance(got, str):
        assert fake.unscheduled == [fake.email_rows[0]["id"]] and fake.email_rows[0]["status"] == "draft"
    else:
        assert fake.unscheduled == [] and "an email may still be scheduled" in text


@pytest.mark.parametrize("echo", [_drop_filter, lambda r: {**r, "filters": None},
                                  lambda r: {**r, "filters": {"filters": [], "groups": [], "predicate": "and"}}])
def test_all_mode_accepts_a_stored_email_with_no_filter_or_the_empty_one(plan, echo):
    fake = NoSubscriberCalls(people(), echo=echo)
    res, _ = go(plan, fake)
    assert (res.code, res.status, res.editions) == (0, "sent", 1) and fake.unscheduled == []
    assert deliver.EMPTY_FILTER == {"filters": [], "groups": [], "predicate": "and"}


@pytest.mark.parametrize("answer", ["stuck", "none", "other id"])
@pytest.mark.parametrize("mode", ["all", "stamp"])
def test_a_take_back_that_is_not_confirmed_a_draft_is_named(plan, answer, mode):
    bad = (lambda r: {**r, "filters": ONE_RULE}) if mode == "all" else _drop_filter
    fake = Fake(people(), echo=bad)
    if answer == "stuck":
        fake.stuck = True
    real = fake.unschedule
    if answer == "none":
        fake.unschedule = lambda i, k: (real(i, k), None)[1]
    elif answer == "other id":
        fake.unschedule = lambda i, k: {**real(i, k), "id": "em-999"}
    res, text = go(plan, fake, s=settings(mode=mode))
    assert (res.code, res.status) == (1, "failed") and "an email may still be scheduled" in text


@pytest.mark.parametrize("echo", [lambda r: {**r, "status": "scheduled"},
                                  lambda r: {**r, "filters": {"filters": [], "groups": [], "predicate": "and"}},
                                  lambda r: {**r, "metadata": {}}, lambda r: r["id"],
                                  lambda r: {**r, "archival_mode": "enabled"}])
def test_ids_never_sends_a_draft_the_provider_stored_differently(plan, echo):
    fake = Fake(people(), echo=echo)
    res, text = go(plan, fake, s=settings(mode="ids"))
    assert (res.code, res.status, res.editions) == (1, "failed", 0) and fake.sent_drafts == []
    assert "send_draft" not in fake.calls and "email check" in text


def test_a_failed_take_back_is_named_in_the_output(plan):
    fake = Fake(people(), echo=_drop_filter, fail={"unschedule": deliver.ProviderError(SECRET_BODY)})
    res, text = go(plan, fake, s=stamp_mode())
    assert (res.code, res.status) == (1, "failed") and "an email may still be scheduled" in text
    assert SECRET_BODY not in text


def test_an_echo_without_an_archival_mode_is_accepted(plan):
    """render/archival-not-echoed: nothing on record shows the create answer carries archival_mode, so it is checked
    only when present (platform-facts: unverified)."""
    for mode in MODES:
        fake = Fake(people(), echo=lambda r: {k: v for k, v in r.items() if k != "archival_mode"})
        res, _ = go(plan, fake, s=settings(mode=mode))
        assert (res.code, res.editions) == (0, 1) and fake.unscheduled == []


def test_a_faithful_echo_sends_and_unschedules_nothing(plan):
    for mode in MODES:
        fake = Fake(people())
        res, _ = go(plan, fake, s=settings(mode=mode))
        assert (res.code, res.editions) == (0, 1) and fake.unscheduled == [] and "unschedule" not in fake.calls


@pytest.mark.parametrize("failure", [
    {"fail": {"emails": deliver.ProviderError(SECRET_BODY)}}, {"fail": {"emails": TimeoutError(SECRET_BODY)}},
    {"rows": "cut short"}, {"rows": None}, {"rows": [["not", "a", "record"]]},
    {"rows": [{"id": "em-1", "metadata": "unreadable"}]}])
@pytest.mark.parametrize("mode", ["all", "stamp"])
def test_a_failed_or_unreadable_email_listing_sends_nothing_and_fails(plan, failure, mode):
    fake = Fake(people(), fail=failure.get("fail"))
    if "rows" in failure:
        fake.emails = lambda since: (fake.calls.append("emails"), failure["rows"])[1]
    res, text = go(plan, fake, s=settings(mode=mode))
    assert (res.code, res.status, res.editions) == (1, "failed", 0) and fake.calls == ["emails"]
    assert "email listing" in text and SECRET_BODY not in text


def test_a_failed_subscriber_listing_sends_nothing_and_fails(plan):
    fake = Fake(people(), fail={"subscribers": deliver.ProviderError(SECRET_BODY)})
    res, text = go(plan, fake, s=stamp_mode())
    assert (res.code, res.status) == (1, "failed") and fake.calls == ["emails", "subscribers"]
    fake = Fake(people())
    fake.subscribers = lambda: None
    assert go(plan, fake, s=stamp_mode())[0].code == 1 and fake.created == []


def test_idempotency_keys_are_stable_per_day_edition_and_step(plan):
    for mode in ("all", "stamp"):
        a, b = Fake(people()), Fake(people())
        go(plan, a, s=settings(mode=mode))
        go(plan, b, s=settings(mode=mode), now=AT_5 + timedelta(minutes=30))
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
    fake = Fake(people())
    res, _ = go(plan, fake, s=stamp_mode())
    assert (res.code, res.status, res.editions) == (1, "failed", 0) and "create_email" not in fake.calls


def test_the_audience_check_accepts_only_the_editions_own_filter():
    key = "0123456789ab"
    good = {"status": "scheduled", "filters": deliver.stamp_filter(DAY, key, SECRET)}
    deliver._check_audience("stamp", good, DAY, key, SECRET)
    for payload in ({**good, "status": "draft"}, {"status": "scheduled"}, {**good, "filters": deliver.stamp_filter("2026-11-10", key, SECRET)},
                    {**good, "filters": deliver.stamp_filter(DAY, key, OTHER_SECRET)}):
        with pytest.raises(deliver.ProviderError):
            deliver._check_audience("stamp", payload, DAY, key, SECRET)
    with pytest.raises(deliver.ProviderError):
        deliver._check_audience("ids", good, DAY, key, SECRET)                 # an ids email carries no filter, and is a draft
    with pytest.raises(deliver.PlanInvalid):
        deliver.stamp_filter(DAY, "not-a-key", SECRET)
    # all: scheduled, and no `filters` key at all (not even the empty shape, nor None)
    deliver._check_audience("all", {"status": "scheduled"}, DAY, key, None)
    for payload in (good, {"status": "scheduled", "filters": deliver.EMPTY_FILTER}, {"status": "scheduled", "filters": None},
                    {"status": "draft"}, {}):
        with pytest.raises(deliver.ProviderError):
            deliver._check_audience("all", payload, DAY, key, None)


# ------------------------------------------------------------------ rate limits
def test_429_is_obeyed_three_tries_then_stop(plan):
    sleeps = []
    fake = Fake(people(), fail={"emails": [deliver.RateLimited(2), deliver.RateLimited(7), None]})
    res, _ = go(plan, fake, sleeps=sleeps)
    assert res.status == "sent" and sleeps == [2.0, 7.0] and fake.calls.count("emails") == 3
    sleeps = []
    fake = Fake(people(), fail={"emails": [deliver.RateLimited(1)] * 5})
    res, text = go(plan, fake, sleeps=sleeps)
    assert (res.code, res.status, res.editions) == (1, "failed", 0)
    assert fake.calls == ["emails"] * 3 and sleeps == [1.0, 1.0]       # three tries, two waits, then stop


def test_a_retry_after_is_capped_and_never_negative(plan):
    sleeps = []
    fake = Fake(people(), fail={"subscribers": [deliver.RateLimited(99999), deliver.RateLimited(-5), None]})
    assert go(plan, fake, s=stamp_mode(), sleeps=sleeps)[0].status == "sent" and sleeps == [float(deliver.MAX_WAIT), 0.0]


# ------------------------------------------------------------------ no personal data out
def _secrets(rows) -> list[str]:
    out = [SECRET_BODY, "192.0.2.10", "made-up fixture person"]
    for s in rows:
        out += [s["id"], s["email_address"], s["email_address"].split("@")[0]]
    return out


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("fail", [
    None, {"emails": deliver.ProviderError(SECRET_BODY)}, {"subscribers": deliver.ProviderError(SECRET_BODY)},
    {"set_metadata": deliver.ProviderError(SECRET_BODY)}, {"create_email": deliver.ProviderError(SECRET_BODY)},
    {"send_draft": deliver.ProviderError(SECRET_BODY)}, {"create_email": [None, ValueError(SECRET_BODY)]},
    {"subscribers": KeyError("person1@example.com")}, {"emails": [deliver.RateLimited(1)] * 3},
    "over-limit", "claimed", "missed", "dry-run"])
def test_no_address_id_or_response_body_reaches_the_output(plan, capsys, mode, fail):
    """Across success and each failure path: stdout, stderr and every raised exception's text."""
    rows = people()
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
        tail = f"recipients: {EVERYONE}" if mode == "all" else "recipients in total 5"
        assert lines == [f"morning note {DAY}: sent; emails created 1; {tail}"]
    # totals only: no per-edition count and no edition key (with stamps, a key and a count could point at a person)
    if kw.get("live", True):
        assert len(lines) == 1 and not any(k in text for k in {e["key"] for e in plan["editions"]})


# ------------------------------------------------------------------ the job that holds the key installs nothing
def test_deliver_imports_with_sitegen_yaml_and_jinja2_blocked():
    import yaml
    shipped = yaml.safe_load((ROOT / "config" / "site.yml").read_text(encoding="utf-8"))["morning_note"]["sender"]
    want = (shipped["enabled"], shipped["mode"], shipped["canary_only"])     # what PyYAML reads from the same file
    # ci/tests-assume-py313: on Python 3.12 `import pathlib` itself loads urllib.parse (3.13 does not), so the network
    # modules count only when loaded after it; urllib.request and urllib.error are checked by exact name.
    code = (
        "import sys\n"
        "class Block:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ('sitegen', 'yaml', 'jinja2', 'jsonschema', 'collector', 'requests'):\n"
        "            raise ImportError('blocked: ' + name)\n"
        "sys.meta_path.insert(0, Block())\n"
        "import pathlib\n"
        "before = set(sys.modules)\n"
        "import sender.deliver, sender.settings, sender.common\n"
        "from sender.__main__ import main\n"
        "s = sender.settings.load('config/site.yml')\n"
        f"assert (s.enabled, s.mode, s.canary_only) == {want!r}, (s.enabled, s.mode, s.canary_only)\n"
        "new = set(sys.modules) - before\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('sitegen', 'yaml', 'jinja2'))\n"
        "bad += sorted(m for m in new if m.split('.')[0] in ('socket', 'ssl', 'http', 'urllib'))\n"
        "bad += [m for m in ('urllib.request', 'urllib.error') if m in sys.modules]\n"
        "assert not bad, bad\n"
        "print('ok')\n")
    done = subprocess.run([sys.executable, "-S", "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and done.stdout.strip() == "ok", done.stderr


def test_the_deliver_stage_opens_no_connection(plan, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the deliver stage tried to open a connection")
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, refuse)
    assert go(plan, Fake(people()))[0].status == "sent"
    with contextlib.redirect_stdout(io.StringIO()):
        assert deliver.run(plan, settings(), live=False).status == "dry-run"


def test_the_base_provider_does_nothing():
    p = deliver.Provider()
    for call in (lambda: p.emails("2026-11-10"), p.subscribers, lambda: p.set_metadata("a", {}, "k"), lambda: p.create_email({}, "k"),
                 lambda: p.send_draft("a", [], "k"), lambda: p.unschedule("a", "k"), lambda: p.subscriber("a")):
        with pytest.raises(NotImplementedError):
            call()


def test_fixture_subscribers_are_all_at_example_com():
    src = Path(__file__).read_text(encoding="utf-8")
    import re
    assert set(re.findall(r"[A-Za-z0-9._+-]+@([A-Za-z0-9-]+\.[a-z]{2,})", src)) == {"example.com"}
    # no test here reaches a provider whatever the shipped switches say: every live run gets a Fake or None
    assert not re.search(r"(?m)^\s*(?:from sender import .*\bbuttondown\b|import sender\.buttondown)", src)


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
    fake = Fake(people())
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


IMG = common.CREDIT_IMAGE
OTHER_IMAGES = [
    common.CREDIT_LINE.replace(IMG, IMG.replace("https://", "http://")),
    common.CREDIT_LINE.replace(IMG, IMG.replace("daylight.gnoshcodes.com", "records.example.com")),
    common.CREDIT_LINE.replace(IMG, IMG.replace("hook-light.png", "hook-dark.png")),
    common.CREDIT_LINE.replace(IMG, IMG.replace(".png", ".svg")), common.CREDIT_LINE.replace(IMG, IMG + "?u=1"),
    common.CREDIT_LINE.replace(IMG, "https://evil.example/t.gif"), common.CREDIT_LINE.replace('width="160"', 'width="1"'),
    common.CREDIT_LINE.replace('alt="gnoshcodes"', 'alt=""'), common.CREDIT_LINE.replace('alt="gnoshcodes"', ""),
    common.CREDIT_LINE.replace("<img ", '<img onerror="x" '), common.CREDIT_LINE.replace("</p>", " </p>"),
    common.CREDIT_LINE.replace("A gnoshcodes project.", "Click here."),
    f'<p>x <img src="{IMG}" alt="gnoshcodes" width="160" height="32"></p>', f'<li><img src="{IMG}"></li>',
    f'<p><img src="{IMG}"></p>', f'<img src="{IMG}" alt="gnoshcodes" width="160" height="32">',
]


def test_the_footer_credit_is_the_one_image_a_body_may_carry(plan):
    """note/credit-logo: the credit line exactly as render writes it passes, in the deliver check and the plan check
    alike (plan.py runs the same body_ok)."""
    s = settings()
    assert common.CREDIT_LINE.count("<img ") == 1 and IMG.startswith("https://") and IMG.endswith(".png")
    assert deliver.body_ok(_with(common.CREDIT_LINE), s.link_hosts)
    assert deliver.body_ok(GOOD_BODY[:-1] + common.CREDIT_LINE + "\n", s.link_hosts) is False   # not on one line
    good = copy.deepcopy(plan)
    good["editions"][0]["body"] = _with(common.CREDIT_LINE)
    deliver.check_plan(good, s.link_hosts, s.link_urls)
    assert all(ed["body"].endswith(common.CREDIT_LINE + "\n") for ed in plan["editions"])     # every edition has it


@pytest.mark.parametrize("line", OTHER_IMAGES)
def test_any_other_image_is_refused_in_plan_and_deliver(plan, line):
    s = settings()
    assert not deliver.body_ok(_with(line), s.link_hosts, s.link_urls)
    bad = copy.deepcopy(plan)
    bad["editions"][0]["body"] = _with(line)
    with pytest.raises(deliver.PlanInvalid, match="body"):
        deliver.check_plan(bad, s.link_hosts, s.link_urls)


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
    res, _ = go(good, Fake(people()), s=s)
    assert res.status == "bad-plan"
    res, _ = go(good, Fake(people()), s=dataclasses.replace(s, link_urls=s.link_urls + ("https://tips.example.com/x",)))
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


# ------------------------------------------------------------------ the note job's own staged launch, end to end
def test_the_note_jobs_staged_launch_runs_a_full_dry_run(msite, tmp_path):  # noqa: F811
    """main-protect coverage gap (security-n1b-3450b52): the note job's exact steps (stage from git objects, plan
    file check, dry run, deliver with MORNING_NOTE_SEND=true and the sender disabled) over a real plan for day D:
    the isolated `python -I -S -c` launch imports everything check_plan and describe need, reads the staged config
    and exits 0 with the dry-run line. A missing module or a wrong path in the launch fails here, not on the
    first morning."""
    import shutil

    from test_workflow_lock import PY_ENV, _commit_all, _note_steps, _stage
    work = tmp_path / "work"
    (work / "sender").mkdir(parents=True)
    for f in (ROOT / "sender").glob("*.py"):
        shutil.copy(f, work / "sender" / f.name)
    (work / "config").mkdir()
    # the shipped file with the sender switched off (this test is the disabled path) and the fixture's hosts
    off = shipped_with(tmp_path, enabled=False, hosts=TEST_HOSTS)
    assert settings_mod.load(off).enabled is False
    (work / "config" / "site.yml").write_text(off.read_text(encoding="utf-8"), encoding="utf-8")
    _commit_all(work)
    runner = tmp_path / "runner"
    runner.mkdir()
    staged, lib_env = _stage(work, runner)
    assert staged.returncode == 0, staged.stdout + staged.stderr
    plan_mod.write(runner / "morning-send", plan_mod.build(msite, D, cfg_with()))
    github_env = tmp_path / "github-env"
    github_env.write_text("")
    env = {**PY_ENV, **lib_env, "RUNNER_TEMP": str(runner), "GITHUB_ENV": str(github_env),
           "BUTTONDOWN_API_KEY": "", "MORNING_NOTE_CANARY_IDS": ""}
    v = subprocess.run(["bash", "-c", _note_steps()["Validate the plan files"]["run"]], cwd=work, env=env,
                       capture_output=True, text=True, timeout=120)
    assert v.returncode == 0, v.stdout + v.stderr
    name, plan_path = github_env.read_text().strip().split("=", 1)
    assert name == "PLAN" and plan_path == str(runner / "morning-send" / D.isoformat() / "plan.json")
    for step, send in (("Check the plan (dry run, no secret)", ""), ("Deliver the morning note", "true")):
        r = subprocess.run(["bash", "-c", _note_steps()[step]["run"]], cwd=work, capture_output=True, text=True,
                           env={**env, "PLAN": plan_path, "MORNING_NOTE_SEND": send}, timeout=120)
        assert r.returncode == 0, (step, r.stdout, r.stderr)
        assert f"morning note {D.isoformat()}: dry run, no connection opened, nothing sent" in r.stdout, step
        assert "Traceback" not in r.stderr
        assert ("--live was passed but morning_note.sender.enabled is false" in r.stderr) == bool(send), step
    assert not list(Path(lib_env["NOTE_LIB"]).rglob("__pycache__"))            # nothing written beside the sources
