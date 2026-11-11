"""Data-age check (qa/staleness.py, config/staleness.yml; problem keys stale-check/*)."""
import json
import subprocess
from datetime import date
from pathlib import Path

import pytest
import yaml

from qa import staleness as st

ROOT = Path(__file__).resolve().parent.parent
WF = yaml.safe_load((ROOT / ".github" / "workflows" / "daily-update.yml").read_text(encoding="utf-8"))
TODAY = date(2026, 11, 11)


@pytest.fixture
def cfg():
    return st.load_config()


def write(data: Path, rel: str, obj) -> None:
    p = data / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


@pytest.fixture
def data(tmp_path):
    d = tmp_path / "data"
    write(d, "facts.json", {"meetings": [{"date": "2026-05-11"}, {"date": "2026-04-13"}, {"date": None}]})
    write(d, "county-agendas/agendas.json", {
        "sources": [{"id": "a", "pages": 3}, {"id": "nopages", "pages": None}],
        "meetings": [{"date": "2026-11-09", "source_id": "a"}, {"date": "2026-12-01", "source_id": "nopages"}]})
    write(d, "localities/clarksville-tn/facts.json", {
        "sources": [{"id": "m1", "kind": "minutes"}, {"id": "a1", "kind": "agenda"}, {"id": "a2", "kind": "agenda"}],
        "meetings": [{"date": "2026-06-04", "source_id": "m1", "agenda_source_id": "a1"},
                     {"date": "2026-11-05", "source_id": "a2"}]})
    write(d, "localities/cmc-rpc/rpc.json", {"meetings": [
        {"date": "2026-09-22", "minutes_source_id": "x", "agenda_source_id": "y"},
        {"date": "2026-10-27", "minutes_source_id": None, "agenda_source_id": "z"}]})
    write(d, "finance.json", {
        "books": [{"fiscal_year": 2027, "edition": "approved"}, {"fiscal_year": 2028, "edition": "proposed"}],
        "solicitations": [{"archive_date": "2026-10-19"}, {"archive_date": None}]})
    return d


# ---- stale-check/newest-matches-freshness-line ----------------------------------------------------------------------

def test_newest_dates_follow_the_freshness_rules(data):
    assert st.newest_dates(data) == {
        "county-agendas": "2026-11-09",      # an agenda without a page count is not shown, so it does not count
        "county-minutes": "2026-05-11",
        "city-agendas": "2026-11-05",
        "city-minutes": "2026-06-04",        # an agenda-only meeting never counts as minutes
        "rpc-agendas": "2026-10-27",
        "rpc-minutes": "2026-09-22",
        "finance-bids": "2026-10-19",
        "finance-budget": 2027,              # approved books only
    }


def test_missing_files_give_none_and_count_as_stale(tmp_path, cfg):
    newest = st.newest_dates(tmp_path / "nothing")
    assert set(newest.values()) == {None}
    assert all(r["stale"] for r in st.check(newest, cfg, TODAY))


def test_committed_data_reads_every_source():
    """The real data/ has a date for every source (a renamed file or field would silently read None)."""
    newest = st.newest_dates(ROOT / "data")
    assert all(v is not None for v in newest.values()), newest


# ---- stale-check/threshold ------------------------------------------------------------------------------------------

def test_threshold_is_exclusive_and_future_agendas_are_fresh(cfg):
    limit = cfg["sources"]["county-agendas"]["max_age_days"]
    for newest, stale in [(date.fromordinal(TODAY.toordinal() - limit), False),
                          (date.fromordinal(TODAY.toordinal() - limit - 1), True),
                          (date(2026, 12, 7), False)]:
        row = st.check({"county-agendas": newest.isoformat()}, {**cfg, "sources": {
            "county-agendas": cfg["sources"]["county-agendas"]}}, TODAY)[0]
        assert row["stale"] is stale, newest


def test_check_on_the_fixture(data, cfg):
    rows = {r["key"]: r for r in st.check(st.newest_dates(data), cfg, TODAY)}
    assert {k for k, r in rows.items() if r["stale"]} == {"county-minutes", "city-minutes"}
    assert rows["county-minutes"]["age_days"] == 184


@pytest.mark.parametrize("today,newest,stale", [
    (date(2026, 6, 30), 2026, False),     # FY2026 still current
    (date(2026, 7, 1), 2026, False),      # FY2027 began today: inside the grace
    (date(2026, 9, 30), 2026, False),     # day 91
    (date(2026, 10, 1), 2026, True),      # day 92: the FY2027 book is late
    (date(2026, 10, 1), 2027, False),
    (date(2027, 1, 15), None, True),
])
def test_budget_book_is_stale_after_the_grace(cfg, today, newest, stale):
    one = {**cfg, "sources": {"finance-budget": cfg["sources"]["finance-budget"]}}
    assert st.check({"finance-budget": newest}, one, today)[0]["stale"] is stale


def test_config_is_validated(tmp_path):
    good = yaml.safe_load(st.CONFIG.read_text(encoding="utf-8"))
    assert set(good["sources"]) == set(st.KEYS)          # every source the site's freshness line names is checked
    for bad in [{**good, "label": ""},
                {**good, "sources": {**good["sources"], "nope": {"name": "x", "max_age_days": 3}}},
                {**good, "sources": {"city-minutes": {"name": "x", "max_age_days": 0}}},
                {**good, "sources": {"city-minutes": {"name": "x", "max_age_days": True}}},
                {**good, "sources": {"city-minutes": {"name": "x [y]", "max_age_days": 3}}},
                {**good, "sources": {"finance-budget": {"name": "x", "max_age_days": 3}}}]:
        p = tmp_path / "c.yml"
        p.write_text(yaml.safe_dump(bad), encoding="utf-8")
        with pytest.raises(st.ConfigError):
            st.load_config(p)


# ---- stale-check/no-duplicate-issue, stale-check/closes-when-fresh ---------------------------------------------------

def rows_for(cfg, **stale):
    return [{"key": k, "name": cfg["sources"][k]["name"], "newest": "2026-01-01", "age_days": 314,
             "threshold_days": 75, "stale": v} for k, v in stale.items()]


def test_plan_creates_once_then_edits_then_closes(cfg):
    rows = rows_for(cfg, **{"county-minutes": True, "city-minutes": False})
    first = st.plan(rows, [], cfg, TODAY, "https://x/run/1")
    assert [(a[0], a[1]) for a in first] == [
        ("create", "Stale source: Montgomery County Commission minutes and votes [county-minutes]")]
    assert "314 days old" in first[0][2] and "https://x/run/1" in first[0][2]

    opened = [{"number": 41, "title": first[0][1]}]
    assert [(a[0], a[1]) for a in st.plan(rows, opened, cfg, TODAY)] == [("edit", 41)]   # never a second issue

    fresh = rows_for(cfg, **{"county-minutes": False})
    closed = st.plan(fresh, opened, cfg, TODAY)
    assert [(a[0], a[1]) for a in closed] == [("close", 41)] and "Fresh again" in closed[0][2]


def test_plan_matches_by_key_not_name(cfg):
    """A renamed source in the config still finds its issue by [key]; other titles with the label are left alone."""
    rows = rows_for(cfg, **{"rpc-minutes": False})
    opened = [{"number": 7, "title": "Stale source: an old name [rpc-minutes]"},
              {"number": 8, "title": "Something else labelled by hand"},
              {"number": 9, "title": "Stale source: other [city-minutes]"}]
    assert st.plan(rows, opened, cfg, TODAY)[0][:2] == ("close", 7)
    assert len(st.plan(rows, opened, cfg, TODAY)) == 1


def test_apply_calls_gh_with_arguments_and_survives_a_failure(cfg):
    calls = []

    def run(args):
        calls.append(args)
        if args[1] == "edit":
            raise subprocess.CalledProcessError(1, args)
        return ""

    actions = [("create", "T [k]", "b; $(rm -rf /)"), ("edit", 3, "b2"), ("close", 4, "c")]
    failed = st.apply(actions, cfg, "o/r", run)
    assert calls[0] == ["issue", "create", "--repo", "o/r", "--title", "T [k]", "--label", "stale-source",
                        "--body", "b; $(rm -rf /)"]
    assert calls[2] == ["issue", "close", "4", "--repo", "o/r", "--reason", "completed", "--comment", "c"]
    assert len(failed) == 1 and failed[0].startswith("edit 3")


def test_issues_command_never_creates_when_the_list_fails(tmp_path, monkeypatch, cfg):
    rep = tmp_path / "r.json"
    rep.write_text(json.dumps({"today": "2026-11-11", "sources": rows_for(cfg, **{"county-minutes": True})}))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    seen = []

    def fake(args):
        seen.append(args[:2])
        if args[:2] == ["issue", "list"]:
            raise subprocess.CalledProcessError(1, args)
        return ""

    monkeypatch.setattr(st, "gh", fake)
    assert st.main(["issues", "--report", str(rep)]) == 2
    assert ["issue", "create"] not in seen


def test_check_command_writes_the_report_and_exits_0(data, tmp_path):
    out = tmp_path / "build" / "staleness.json"
    assert st.main(["check", "--data", str(data), "--out", str(out), "--today", "2026-11-11"]) == 0
    rep = json.loads(out.read_text())
    assert rep["today"] == "2026-11-11" and len(rep["sources"]) == len(st.KEYS)


# ---- stale-check/never-blocks-publish, stale-check/minimal-permissions ---------------------------------------------

def test_workflow_steps_never_block_publishing():
    steps = {s.get("name"): s for s in WF["jobs"]["update"]["steps"]}
    chk, iss = steps["Check data age"], steps["Open, update or close stale-source issues"]
    assert chk["continue-on-error"] is True and iss["continue-on-error"] is True
    assert "env" not in chk                                   # no token where nothing needs one
    assert iss["env"] == {"GH_TOKEN": "${{ github.token }}"}
    assert "github.ref == 'refs/heads/main'" in iss["if"]
    assert WF["jobs"]["update"]["permissions"] == {"contents": "read", "issues": "write"}   # unchanged
    names = [s.get("name") for s in WF["jobs"]["update"]["steps"]]
    assert names.index("Tests (full suite, about 12 min, default settings)") < names.index("Check data age") \
        < names.index("Upload refreshed data")
