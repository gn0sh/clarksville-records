# ruff: noqa: E501
"""The morning note sender's plan stage, the dry run (T4.1: sender/plan.py, `python -m sender plan`; ADR 0004).
FIXTURE data only: the notes test_morning.py builds from the fixture facts. No test opens a connection, and no
subscriber exists anywhere in this file: the plan stage knows none."""
import copy
import json
import re
import socket
from datetime import date, timedelta
from pathlib import Path

import pytest

from conftest import note_off, shipped_with
from sitegen import config, morning
from sender import common, deliver, plan as plan_mod, settings as settings_mod
from sender.__main__ import main
from test_morning import D, inputs, make  # noqa: F401  (inputs: the fixture the site is built from)

ROOT = Path(__file__).resolve().parent.parent
SITE_URL = "https://records.example.com/"
TEST_HOSTS = "records.example.com,example.com,example.invalid,tips.example.com"
NEXT = D + timedelta(days=1)
_CACHE: dict = {}


def cfg_with(enabled=True, site_url=SITE_URL, max_editions=500, **sender) -> dict:
    """The shipped config with the sender switched on and a site URL. Day D's RPC agenda (a real one, 27 cases
    printing 7 districts and 3 wards) gives 191 editions; the plan stage no longer counts them (max_editions is the
    deliver stage's, over editions that have a recipient)."""
    cfg = copy.deepcopy(config.SITE)
    cfg["alerts"]["site_url"] = site_url
    # the made-up site and the fixture's sources join the shipped link hosts (plan-untrusted/body-unchecked)
    sender.setdefault("link_hosts", cfg["morning_note"]["sender"]["link_hosts"] + "," + TEST_HOSTS)
    cfg["morning_note"]["sender"].update(enabled=enabled, max_editions=max_editions, **sender)
    return cfg


@pytest.fixture(scope="module")
def msite(inputs, tmp_path_factory):  # noqa: F811
    """The fixture site with its morning notes, built once for every sender test module."""
    if "out" not in _CACHE:
        out = tmp_path_factory.mktemp("sender-site") / "build" / "site"
        make(inputs, out)
        _CACHE["out"] = out
    return _CACHE["out"]


def read_note(site: Path, d: date = D) -> dict:
    return json.loads((site / "morning" / f"{d.isoformat()}.json").read_text(encoding="utf-8"))


def site_with(tmp_path: Path, note: dict, d: date = D) -> Path:
    """A site folder holding one made-up note file."""
    folder = tmp_path / "site" / "morning"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{d.isoformat()}.json").write_text(json.dumps(note), encoding="utf-8")
    return tmp_path / "site"


@pytest.fixture(scope="module")
def built(msite):
    return plan_mod.build(msite, D, cfg_with())


class CountingProvider(deliver.Provider):
    """Fails the test on any call: a path that must not touch the provider gets this one."""

    def __init__(self):
        self.calls = []

    def __getattribute__(self, name):
        if name in ("emails", "subscribers", "set_metadata", "create_email", "send_draft"):
            def called(*a, **k):
                self.calls.append(name)
                raise AssertionError(f"provider.{name} was called")
            return called
        return object.__getattribute__(self, name)


# ------------------------------------------------------------------ off: plans nothing, sends nothing
@pytest.fixture()
def sender_off(monkeypatch, tmp_path):
    """The sender switched off for the CLI, whatever the repository ships: config.SITE is the shipped config with
    the note off (conftest.note_off) and SITE_CONFIG_PATH a copy of config/site.yml with `sender.enabled: false`,
    so the plan command's parity check (PyYAML against the deliver job's reader) sees one config. Returns the
    file, for `deliver --config`."""
    off = shipped_with(tmp_path, enabled=False)
    monkeypatch.setattr(config, "SITE", note_off(config.SITE))
    monkeypatch.setattr(config, "SITE_CONFIG_PATH", off)
    assert settings_mod.load(off).enabled is False and config.SITE["morning_note"]["sender"]["enabled"] is False
    return off


def test_the_off_config_has_the_sender_off_and_is_clean():
    """The state every "off" test below runs in (it was the shipped config until the switch-on PR)."""
    off = note_off(config.SITE)
    s = off["morning_note"]["sender"]
    assert s["enabled"] is False and off["morning_note"]["enabled"] is False
    assert morning.problems(off) == []


def test_a_disabled_sender_plans_nothing_and_does_not_read_the_note(tmp_path):
    got = plan_mod.build(tmp_path / "no-such-site", D, note_off(config.SITE))       # the sender off
    p = got["plan"]
    assert p["send"] is False and p["reason"] == "disabled"
    assert p["editions"] == [] and p["signatures"] == {} and got["texts"] == {} and p["note_sha256"] == ""


def test_a_disabled_sender_cli_writes_no_edition_and_delivers_nothing(msite, tmp_path, capsys, sender_off):
    out = tmp_path / "send"
    assert main(["plan", "--date", D.isoformat(), "--site", str(msite), "--out", str(out)]) == 0
    assert sorted(p.name for p in (out / D.isoformat()).iterdir()) == ["plan.json"]
    p = json.loads((out / D.isoformat() / "plan.json").read_text(encoding="utf-8"))
    assert p["send"] is False and p["reason"] == "disabled" and not p["editions"] and not p["signatures"]
    assert "send false (disabled); 0 edition(s)" in capsys.readouterr().out
    # even a live run with a provider at hand makes no call: neither on this plan nor on any plan, while disabled
    provider = CountingProvider()
    s = settings_mod.load(sender_off)
    assert s.enabled is False
    import dataclasses
    s = dataclasses.replace(s, link_hosts=s.link_hosts + tuple(TEST_HOSTS.split(",")))   # the made-up site's links
    now = plan_mod._at(D, "05:00", config.SITE["site_timezone"])
    from datetime import datetime
    for the_plan in (p, plan_mod.build(msite, D, cfg_with())["plan"]):
        res = deliver.run(the_plan, s, provider=provider, live=True, now=datetime.fromisoformat(now), out=lambda *_: None)
        assert res.status == "disabled" and res.code == 0 and res.editions == 0 and provider.calls == []


def test_rehearsal_of_a_disabled_sender_writes_editions_but_never_send_true(msite, tmp_path, sender_off):
    out = tmp_path / "send"
    assert main(["plan", "--date", NEXT.isoformat(), "--site", str(msite), "--out", str(out), "--rehearse"]) == 0
    p = json.loads((out / NEXT.isoformat() / "plan.json").read_text(encoding="utf-8"))
    assert p["send"] is False and p["reason"] == "disabled" and p["editions"] and p["signatures"]
    names = sorted(x.name for x in (out / NEXT.isoformat()).iterdir())
    assert names == sorted(["plan.json"] + [f"edition-{e['key']}.{ext}" for e in p["editions"] for ext in ("html", "txt")])
    assert main(["deliver", "--plan", str(out / NEXT.isoformat() / "plan.json"), "--config", str(sender_off)]) == 0


def test_live_with_the_sender_off_is_a_dry_run(msite, tmp_path, capsys, monkeypatch, sender_off):
    """A config with sender.enabled false: --live (even with a key set) opens nothing, a dry run."""
    monkeypatch.setenv("BUTTONDOWN_API_KEY", "made-up-test-key-not-a-real-one-32b")
    out = tmp_path / "send"
    main(["plan", "--date", NEXT.isoformat(), "--site", str(msite), "--out", str(out), "--rehearse"])
    assert main(["deliver", "--plan", str(out / NEXT.isoformat() / "plan.json"), "--live", "--config", str(sender_off)]) == 0
    got = capsys.readouterr()
    assert "dry run" in got.out and "enabled is false" in got.err and "made-up-test-key" not in got.out + got.err


def test_the_deliver_command_refuses_a_plan_file_over_the_ceiling(msite, tmp_path, capsys, monkeypatch):
    out = tmp_path / "send"
    main(["plan", "--date", NEXT.isoformat(), "--site", str(msite), "--out", str(out), "--rehearse"])
    path = out / NEXT.isoformat() / "plan.json"
    assert main(["deliver", "--plan", str(path)]) == 0
    monkeypatch.setattr(common, "MAX_PLAN_BYTES", path.stat().st_size - 1)
    assert main(["deliver", "--plan", str(path)]) == 2
    assert "MAX_PLAN_BYTES" in capsys.readouterr().err



def test_the_plan_stage_runs_the_deliver_body_check_on_every_edition(msite, monkeypatch):  # noqa: F811
    """render/clean-order: a body render writes but deliver would refuse fails the plan itself, so the daily
    rehearsal shows the gap (its ::warning) long before go-live, and a live day fails loudly, never drops quietly."""
    real = plan_mod.render.body_html
    monkeypatch.setattr(plan_mod.render, "body_html", lambda *a: real(*a).replace("</p>", "  </p>", 1))
    with pytest.raises(plan_mod.PlanError, match="body"):
        plan_mod.build(msite, NEXT, cfg_with(enabled=True))
    with pytest.raises(plan_mod.PlanError, match="body"):
        plan_mod.build(msite, NEXT, cfg_with(enabled=False), rehearse=True)

# ------------------------------------------------------------------ the contract
def test_plan_shape(built, msite):
    p = built["plan"]
    assert list(p) == ["schema", "date", "note_sha256", "timezone", "send", "reason", "send_at", "latest_send",
                       "editions", "signatures"]
    assert p["schema"] == "morning-send/1" and p["date"] == "2026-11-11" and p["timezone"] == "America/Chicago"
    assert p["send"] is True and p["reason"] == "ok"
    assert p["send_at"] == "2026-11-11T07:00:00-06:00" and p["latest_send"] == "2026-11-11T10:00:00-06:00"
    import hashlib
    assert p["note_sha256"] == hashlib.sha256((msite / "morning" / "2026-11-11.json").read_bytes()).hexdigest()
    assert p["editions"] and [e["key"] for e in p["editions"]] == sorted(e["key"] for e in p["editions"])
    for e in p["editions"]:
        assert sorted(e) == ["body", "entry_ids", "key", "subject"] and common.KEY_RE.fullmatch(e["key"])
        assert e["entry_ids"] and len(set(e["entry_ids"])) == len(e["entry_ids"])   # key: the every-signature test
    assert all(common.SIGNATURE_RE.fullmatch(s) for s in p["signatures"])
    hosts = common.parse_hosts(cfg_with()["morning_note"]["sender"]["link_hosts"])
    assert deliver.check_plan(p, hosts, (config.SITE["support_url"],)) is p     # deliver accepts what plan writes


def test_shared_constants_match_the_digest():
    assert common.LIST_KEYS == morning.LIST_KEYS and common.NOTE_SCHEMA == morning.SCHEMA
    assert common.MODES == morning.SENDER_MODES
    assert common.signature(["zoning", "budget", "nope"], 7, None) == "budget,zoning|7|-"


def test_every_signature_gets_exactly_what_select_returns(built, msite):
    """All 15 x 22 x 13 shapes: in `signatures` only when select() is non-empty, and then its edition holds
    exactly select()'s ids, in select()'s order."""
    p, note = built["plan"], read_note(msite)
    editions = {e["key"]: e["entry_ids"] for e in p["editions"]}
    n = with_mail = 0
    for lists, district, ward in plan_mod.signatures(config.SITE):
        n += 1
        seats = {"district": district, "ward": ward}
        ids = [e["id"] for e in morning.select(note, lists, seats)]
        sig = common.signature(lists, district, ward)
        if ids:
            with_mail += 1
            rows = plan_mod.placed(note, lists, seats)
            key = p["signatures"][sig]
            assert key == plan_mod.edition_key(p["date"], rows), sig
            assert editions[key] == [i for i, _ in rows] and sorted(editions[key]) == sorted(ids), sig
        else:
            assert sig not in p["signatures"], sig
    assert n == 15 * 22 * 13 == 4290 and len(p["signatures"]) == with_mail
    assert 0 < with_mail < n                                           # the fixture has both kinds of shape


def test_same_entries_share_an_edition_and_different_entries_do_not(built):
    p = built["plan"]
    editions = [(tuple(e["entry_ids"]), e["body"]) for e in p["editions"]]
    assert len(set(editions)) == len(editions) > 1                     # no two editions are the same email
    used = set(p["signatures"].values())
    assert used == {e["key"] for e in p["editions"]}                   # every edition has a shape; none is spare
    assert len(p["signatures"]) > len(used)                            # some shapes share one
    # budget and contracts ignore seats: every seat pair of a budget-only reader shares one edition
    assert len({k for s, k in p["signatures"].items() if s.startswith("budget|")}) == 1
    assert p["signatures"]["budget|-|-"] != p["signatures"]["contracts|-|-"]


def _entry(eid, lists, district=None, ward=None, seat_body=None):
    return {"id": eid, "lists": lists, "district": district, "ward": ward, "seat_body": seat_body}


def test_an_entry_stands_under_a_list_the_reader_picked_and_that_selected_it():
    """render/section-not-picked: an entry stood under its first list even when the reader had not picked it (a
    county budget item on the seats and budget lists, under "My two seats" for a Budget-only reader) or it had not
    selected the entry (a zoning case in another district, under "Zoning near me", that reached the reader through
    their county seat)."""
    note = {"entries": [_entry("a", ["zoning", "seats"], district=7, seat_body="district"),
                        _entry("b", ["zoning", "seats"], district=3, seat_body="district"),
                        _entry("c", ["seats", "budget"], seat_body="district"),
                        _entry("d", ["budget"])]}
    budget_only = plan_mod.placed(note, ["budget"], {"district": None, "ward": None})
    assert budget_only == [("c", "budget"), ("d", "budget")]
    near_7 = plan_mod.placed(note, ["zoning", "seats", "budget"], {"district": 7, "ward": None})
    assert near_7 == [("a", "zoning"), ("b", "seats"), ("c", "seats"), ("d", "budget")]
    near_3 = plan_mod.placed(note, ["zoning", "budget"], {"district": 3, "ward": None})
    assert near_3 == [("b", "zoning"), ("c", "budget"), ("d", "budget")]
    # the same entries under other headings are another email, so another edition
    assert plan_mod.edition_key("2026-11-11", [("c", "budget")]) != plan_mod.edition_key("2026-11-11", [("c", "seats")])


def test_editions_print_each_entry_under_its_placed_list(built, msite):
    p, note = built["plan"], read_note(msite)
    labels = {x["key"]: x["label"] for x in note["lists"]}
    for lists, district, ward in plan_mod.signatures(config.SITE):
        rows = plan_mod.placed(note, lists, {"district": district, "ward": ward})
        if not rows:
            continue
        body = next(e["body"] for e in p["editions"] if e["key"] == p["signatures"][common.signature(lists, district, ward)])
        heads = re.findall("(?m)^" + re.escape(common.TAG["h2"]) + "(.*)</h2>$", body)     # the list headings
        want = [labels[k] for i, (_, k) in enumerate(rows) if i == 0 or rows[i - 1][1] != k]
        assert heads == want and len(heads) == len(set(heads)), (lists, district, ward)
        assert set(heads) <= {labels[k] for k in lists}                # never a list the reader did not pick


def test_nobody_gets_two_emails_or_an_empty_one(built):
    p = built["plan"]
    assert all(e["entry_ids"] and e["body"].strip() and e["subject"].strip() for e in p["editions"])
    assert len(p["signatures"]) == len(set(p["signatures"]))           # one edition per shape (a mapping)


# ------------------------------------------------------------------ days that send nothing
def test_a_quiet_day_plans_no_edition(msite, tmp_path):
    note = {**read_note(msite), "entries": [], "unplaced_zoning": 0, "unplaced_text": ""}
    p = plan_mod.build(site_with(tmp_path, note), D, cfg_with())["plan"]
    assert p["send"] is False and p["reason"] == "quiet" and p["editions"] == [] and p["signatures"] == {}


def test_a_backfill_day_plans_no_edition_even_if_entries_slipped_through(msite, tmp_path):
    note = {**read_note(msite), "backfill": True}                      # entries left in on purpose
    p = plan_mod.build(site_with(tmp_path, note), D, cfg_with())["plan"]
    assert p["send"] is False and p["reason"] == "backfill" and p["editions"] == [] and p["signatures"] == {}


@pytest.mark.parametrize("case", ["missing", "schema", "date", "not json", "no entries key", "duplicate id"])
def test_a_missing_or_wrong_note_fails_the_run(msite, tmp_path, monkeypatch, capsys, case):
    note = read_note(msite)
    if case == "schema":
        note["schema"] = "morning-note/0"
    elif case == "date":
        note["date"] = NEXT.isoformat()
    elif case == "no entries key":
        del note["entries"]
    elif case == "duplicate id":
        note["entries"].append(dict(note["entries"][0]))
    site = site_with(tmp_path, note)
    if case == "missing":
        (site / "morning" / f"{D.isoformat()}.json").unlink()
    elif case == "not json":
        (site / "morning" / f"{D.isoformat()}.json").write_text("{", encoding="utf-8")
    with pytest.raises(plan_mod.PlanError):
        plan_mod.build(site, D, cfg_with())
    # With the sender off, a rehearsal must never fail the daily site job. It says what is wrong, writes nothing
    # and exits 0. (With the sender on, the same error fails the run: the build() call above.)
    monkeypatch.setattr(config, "SITE", note_off(config.SITE))
    monkeypatch.setattr(config, "SITE_CONFIG_PATH", shipped_with(tmp_path, enabled=False))
    assert config.SITE["morning_note"]["sender"]["enabled"] is False
    out = tmp_path / "send"
    assert main(["plan", "--date", D.isoformat(), "--site", str(site), "--out", str(out), "--rehearse"]) == 0
    err = capsys.readouterr().err
    assert not out.exists() and "sender plan:" in err and "rehearsal" in err and "not failing" in err
    # plan/rehearse-swallows: still visible in the Actions run, as a warning annotation on one line of fixed text
    warnings = [line for line in err.splitlines() if line.startswith("::warning")]
    assert warnings == ["::warning title=Morning note rehearsal::the sender plan failed while the sender is disabled; "
                        "see the step log"]


def test_a_subject_naming_a_government_body_fails_the_run(msite):
    cfg = cfg_with()
    cfg["morning_note"]["sender"]["text"]["subject"] = "{site_name} official note, {date}"
    with pytest.raises(plan_mod.PlanError, match="official"):
        plan_mod.build(msite, D, cfg)


def test_a_plan_over_the_size_ceiling_fails_the_run(msite, built, monkeypatch, tmp_path):
    """The plan stage caps the plan's size, not its edition count: only the deliver stage knows which editions
    have a recipient (max_editions counts those)."""
    size = plan_mod.size_of(built)
    assert size == sum(p.stat().st_size for p in plan_mod.write(tmp_path, built).parent.iterdir())
    monkeypatch.setattr(common, "MAX_PLAN_BYTES", size)
    assert plan_mod.build(msite, D, cfg_with())["plan"]["send"] is True
    monkeypatch.setattr(common, "MAX_PLAN_BYTES", size - 1)
    with pytest.raises(plan_mod.PlanError, match="MAX_PLAN_BYTES"):
        plan_mod.build(msite, D, cfg_with())


def test_the_fixtures_rpc_agenda_day_plans_with_the_shipped_config(msite, tmp_path, capsys):
    """A real RPC agenda day (27 cases printing 7 districts and 3 wards) gives 191 editions and about 2.7 MB of
    files: more than the old cap of 80 editions and the 2 MB artifact check, well under the ceiling. Every shape
    of that day fits under the shipped max_editions (400 since 2026-11-17), so even a whole list of distinct
    shapes is sent, not refused."""
    cfg = copy.deepcopy(config.SITE)
    cfg["alerts"]["site_url"] = SITE_URL
    cfg["morning_note"]["sender"]["enabled"] = True       # the shipped max_editions and everything else
    cfg["morning_note"]["sender"]["link_hosts"] += "," + TEST_HOSTS       # but the fixture's links
    built = plan_mod.build(msite, D, cfg)
    assert 80 < len(built["plan"]["editions"]) == 191 < cfg["morning_note"]["sender"]["max_editions"]
    assert 2_000_000 < plan_mod.size_of(built) < common.MAX_PLAN_BYTES
    assert main(["plan", "--date", D.isoformat(), "--site", str(msite), "--out", str(tmp_path / "o"), "--rehearse"]) == 0
    assert (tmp_path / "o" / D.isoformat() / "plan.json").is_file()


def test_a_bad_date_argument_exits_2(msite, tmp_path):
    assert main(["plan", "--date", "tomorrow", "--site", str(msite), "--out", str(tmp_path / "o")]) == 2


# ------------------------------------------------------------------ pure and network-free
def test_two_runs_write_byte_identical_files(msite, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for out in (a, b):
        plan_mod.write(out, plan_mod.build(msite, D, cfg_with()))
    files = sorted(p.relative_to(a).as_posix() for p in a.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(b).as_posix() for p in b.rglob("*") if p.is_file()) and len(files) > 1
    assert all((a / f).read_bytes() == (b / f).read_bytes() for f in files)


def _council_votes(meetings: int = 4, per: int = 13) -> list[dict]:
    """`per` untitled votes from each of `meetings` made-up council meetings' minutes, all posted on one day (real
    shape: 2026-11-18, four past meetings, 51 votes nearly all "Title not read from the minutes" or "MINUTES")."""
    out = []
    for m in range(meetings):
        day = f"2026-0{m + 6}-0{m + 1}"
        for n in range(per):
            out.append({"id": f"city/vote/rc-{day}-{n:02}", "lists": ["seats"], "kind": "vote", "body": "city",
                        "body_name": "Fixture Council", "meeting_date": day, "meeting": "regular session",
                        "title": f"ORDINANCE {n}-2026-27: Title not read from the minutes", "title_ours": True,
                        "untitled": True, "item_number": f"ORDINANCE {n}-2026-27",
                        "recorded": "Recorded in the minutes; not confirmed", "district": None,
                        "ward": None, "case": None, "seat_body": "ward", "href": f"city/items/2026.html#o-{n}",
                        "meeting_href": f"city/meetings/2026.html#{day}-regular",
                        "source": {"url": f"https://example.com/fixture/minutes-{day}.pdf#page={n + 2}", "page": n + 2}})
    return out


def test_a_day_of_untitled_council_votes_is_one_line_per_meeting_and_keeps_its_edition_keys(msite, tmp_path):
    """note/compact-untitled: the plan still lists every entry id and keys each edition over every (id, list) row, so
    the keys are what they were and two runs match; only the body is shorter, and the deliver check accepts it."""
    note = {**read_note(msite), "entries": _council_votes(), "unplaced_zoning": 0, "unplaced_text": ""}
    built = plan_mod.build(site_with(tmp_path, note), D, cfg_with())
    p = built["plan"]
    ward = next(e for e in p["editions"] if e["key"] == p["signatures"]["seats|-|3"])
    assert ward["entry_ids"] == [e["id"] for e in note["entries"]]
    assert ward["key"] == plan_mod.edition_key(D.isoformat(), [(e["id"], "seats") for e in note["entries"]])
    assert ward["body"].count(common.TAG["card"]) == 4 and "Title not read" not in ward["body"]
    from sender import render
    ctx = render.context(cfg_with())
    assert deliver.body_ok(ward["body"], ctx["link_hosts"], ctx["link_urls"])
    text = built["texts"][ward["key"]]
    assert text.count(render.untitled_words(ctx, 13)) == 4 and "Title not read" not in text
    assert len(text.splitlines()) < 70         # 52 entries: about 320 lines before note/compact-untitled
    assert ", ".join(f"ORDINANCE {n}-2026-27" for n in range(13)) in text      # the item numbers stay
    assert plan_mod.build(site_with(tmp_path, note), D, cfg_with()) == built


def test_writing_again_removes_an_earlier_runs_edition_files(msite, tmp_path):
    out = tmp_path / "send"
    plan_mod.write(out, plan_mod.build(msite, D, cfg_with()))
    stale = out / D.isoformat() / "edition-000000000000.html"
    stale.write_text("old", encoding="utf-8")
    plan_mod.write(out, plan_mod.build(msite, D, note_off(config.SITE)))   # disabled: no edition at all
    assert sorted(p.name for p in (out / D.isoformat()).iterdir()) == ["plan.json"]


def test_the_plan_holds_no_subscriber_data(built):
    raw = plan_mod.dumps(built["plan"])
    assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}", raw)
    assert "subscriber" not in raw.lower() and "api_key" not in raw.lower()


def test_the_plan_stage_opens_no_connection(msite, tmp_path, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the plan stage tried to open a connection")
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    plan_mod.write(tmp_path / "send", plan_mod.build(msite, D, cfg_with()))
    assert main(["plan", "--date", NEXT.isoformat(), "--site", str(msite), "--out", str(tmp_path / "s2"), "--rehearse"]) == 0
    assert main(["deliver", "--plan", str(tmp_path / "s2" / NEXT.isoformat() / "plan.json"),
                 "--config", str(ROOT / "config" / "site.yml")]) == 0


NETWORK_IMPORT = re.compile(r"^\s*(?:import|from)\s+(?:urllib|socket|http|requests|subprocess|ssl|smtplib|asyncio|httpx|aiohttp)\b", re.M)


@pytest.mark.parametrize("path", sorted((ROOT / "sender").glob("*.py")), ids=lambda p: p.name)
def test_no_sender_module_imports_anything_that_can_open_a_connection(path):
    """The architecture allows exactly one module to open a connection, buttondown.py (its own tests:
    test_morning_sender_buttondown.py). Every other module: no network import, no urlopen, no Authorization."""
    if path.name == "buttondown.py":
        return
    src = path.read_text(encoding="utf-8")
    assert not NETWORK_IMPORT.search(src), path.name
    assert not re.search(r"\burlopen\b|\bos\.system\b|\bPopen\b|Authorization", src), path.name
    # the key's variable is named only by the adapter and by the command line that reads it
    assert path.name == "__main__.py" or "BUTTONDOWN_API_KEY" not in src, path.name


def test_the_sender_package_is_only_the_modules_this_task_defines():
    assert sorted(p.name for p in (ROOT / "sender").glob("*.py")) == [
        "__init__.py", "__main__.py", "buttondown.py", "common.py", "deliver.py", "plan.py", "render.py",
        "settings.py"]
