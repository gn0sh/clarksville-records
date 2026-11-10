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


# ------------------------------------------------------------------ off by default: plans nothing, sends nothing
def test_shipped_config_has_the_sender_off():
    s = config.SITE["morning_note"]["sender"]
    assert s["enabled"] is False and s["canary_only"] is True and config.SITE["morning_note"]["enabled"] is False
    assert morning.problems(config.SITE) == []


def test_a_disabled_sender_plans_nothing_and_does_not_read_the_note(tmp_path):
    got = plan_mod.build(tmp_path / "no-such-site", D, config.SITE)       # the shipped config, as it is
    p = got["plan"]
    assert p["send"] is False and p["reason"] == "disabled"
    assert p["editions"] == [] and p["signatures"] == {} and got["texts"] == {} and p["note_sha256"] == ""


def test_a_disabled_sender_cli_writes_no_edition_and_delivers_nothing(msite, tmp_path, capsys):
    out = tmp_path / "send"
    assert main(["plan", "--date", D.isoformat(), "--site", str(msite), "--out", str(out)]) == 0
    assert sorted(p.name for p in (out / D.isoformat()).iterdir()) == ["plan.json"]
    p = json.loads((out / D.isoformat() / "plan.json").read_text(encoding="utf-8"))
    assert p["send"] is False and p["reason"] == "disabled" and not p["editions"] and not p["signatures"]
    assert "send false (disabled); 0 edition(s)" in capsys.readouterr().out
    # even a live run with a provider at hand makes no call: neither on this plan nor on any plan, while disabled
    provider = CountingProvider()
    s = settings_mod.load(ROOT / "config" / "site.yml")
    assert s.enabled is False
    import dataclasses
    s = dataclasses.replace(s, link_hosts=s.link_hosts + tuple(TEST_HOSTS.split(",")))   # the made-up site's links
    now = plan_mod._at(D, "05:00", config.SITE["site_timezone"])
    from datetime import datetime
    for the_plan in (p, plan_mod.build(msite, D, cfg_with())["plan"]):
        res = deliver.run(the_plan, s, provider=provider, live=True, now=datetime.fromisoformat(now), out=lambda *_: None)
        assert res.status == "disabled" and res.code == 0 and res.editions == 0 and provider.calls == []


def test_rehearsal_of_a_disabled_sender_writes_editions_but_never_send_true(msite, tmp_path):
    out = tmp_path / "send"
    assert main(["plan", "--date", NEXT.isoformat(), "--site", str(msite), "--out", str(out), "--rehearse"]) == 0
    p = json.loads((out / NEXT.isoformat() / "plan.json").read_text(encoding="utf-8"))
    assert p["send"] is False and p["reason"] == "disabled" and p["editions"] and p["signatures"]
    names = sorted(x.name for x in (out / NEXT.isoformat()).iterdir())
    assert names == sorted(["plan.json"] + [f"edition-{e['key']}.{ext}" for e in p["editions"] for ext in ("html", "txt")])
    assert main(["deliver", "--plan", str(out / NEXT.isoformat() / "plan.json"), "--config", str(ROOT / "config" / "site.yml")]) == 0


def test_the_cli_refuses_live(msite, tmp_path, capsys):
    out = tmp_path / "send"
    main(["plan", "--date", NEXT.isoformat(), "--site", str(msite), "--out", str(out), "--rehearse"])
    assert main(["deliver", "--plan", str(out / NEXT.isoformat() / "plan.json"), "--live"]) == 2
    assert "nothing sent" in capsys.readouterr().err


def test_the_deliver_command_refuses_a_plan_file_over_the_ceiling(msite, tmp_path, capsys, monkeypatch):
    out = tmp_path / "send"
    main(["plan", "--date", NEXT.isoformat(), "--site", str(msite), "--out", str(out), "--rehearse"])
    path = out / NEXT.isoformat() / "plan.json"
    assert main(["deliver", "--plan", str(path)]) == 0
    monkeypatch.setattr(common, "MAX_PLAN_BYTES", path.stat().st_size - 1)
    assert main(["deliver", "--plan", str(path)]) == 2
    assert "MAX_PLAN_BYTES" in capsys.readouterr().err


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
        assert e["key"] == plan_mod.edition_key(p["date"], e["entry_ids"]) and e["entry_ids"]
    assert all(common.SIGNATURE_RE.fullmatch(s) for s in p["signatures"])
    hosts = common.parse_hosts(cfg_with()["morning_note"]["sender"]["link_hosts"])
    assert deliver.check_plan(p, hosts) is p                            # the deliver stage accepts what plan writes


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
        ids = [e["id"] for e in morning.select(note, lists, {"district": district, "ward": ward})]
        sig = common.signature(lists, district, ward)
        if ids:
            with_mail += 1
            assert editions[p["signatures"][sig]] == ids, sig
        else:
            assert sig not in p["signatures"], sig
    assert n == 15 * 22 * 13 == 4290 and len(p["signatures"]) == with_mail
    assert 0 < with_mail < n                                           # the fixture has both kinds of shape


def test_same_entries_share_an_edition_and_different_entries_do_not(built):
    p = built["plan"]
    editions = [tuple(e["entry_ids"]) for e in p["editions"]]
    assert len(set(editions)) == len(editions) > 1                     # no two editions hold the same entries
    used = set(p["signatures"].values())
    assert used == {e["key"] for e in p["editions"]}                   # every edition has a shape; none is spare
    assert len(p["signatures"]) > len(used)                            # some shapes share one
    # budget and contracts ignore seats: every seat pair of a budget-only reader shares one edition
    assert len({k for s, k in p["signatures"].items() if s.startswith("budget|")}) == 1
    assert p["signatures"]["budget|-|-"] != p["signatures"]["contracts|-|-"]


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
    # The shipped config has the sender off: a rehearsal must never fail the daily site job. It says what is wrong,
    # writes nothing and exits 0. (With the sender on, the same error fails the run: the build() call above.)
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
    files: more than the old cap of 80 editions and the 2 MB artifact check, well under the ceiling."""
    cfg = copy.deepcopy(config.SITE)
    cfg["alerts"]["site_url"] = SITE_URL
    cfg["morning_note"]["sender"]["enabled"] = True       # the shipped max_editions (80) and everything else
    cfg["morning_note"]["sender"]["link_hosts"] += "," + TEST_HOSTS       # but the fixture's links
    built = plan_mod.build(msite, D, cfg)
    assert len(built["plan"]["editions"]) > cfg["morning_note"]["sender"]["max_editions"]
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


def test_writing_again_removes_an_earlier_runs_edition_files(msite, tmp_path):
    out = tmp_path / "send"
    plan_mod.write(out, plan_mod.build(msite, D, cfg_with()))
    stale = out / D.isoformat() / "edition-000000000000.html"
    stale.write_text("old", encoding="utf-8")
    plan_mod.write(out, plan_mod.build(msite, D, config.SITE))         # disabled: no edition at all
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
    """The architecture allows exactly one module to open a connection, buttondown.py, and this task ships none."""
    assert path.name != "buttondown.py", "the provider client is a later task (needs its own security review)"
    src = path.read_text(encoding="utf-8")
    assert not NETWORK_IMPORT.search(src), path.name
    assert not re.search(r"\burlopen\b|\bos\.system\b|\bPopen\b|BUTTONDOWN_API_KEY|Authorization", src), path.name


def test_the_sender_package_is_only_the_modules_this_task_defines():
    assert sorted(p.name for p in (ROOT / "sender").glob("*.py")) == [
        "__init__.py", "__main__.py", "common.py", "deliver.py", "plan.py", "render.py", "settings.py"]
