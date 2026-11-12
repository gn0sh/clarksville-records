"""shrink/city-listing-unguarded, shrink/city-shrink-freezes-all-sources (docs/adr/0006-daily-refresh-data-guards.md):
an empty or shrunk city listing (a 200 with no heading and no rows, an events page of `{"value": []}`) or a build that
loses committed meetings never replaces the committed city data. The committed rows and meetings are kept and the run
warns (exit 7, `guard` in build/city-report.json), so the workflow publishes everything else and opens the city
meetings-kept issue; a vanished row with no minutes dated today or later drops quietly. The county's rule 3
(test_shrink_guard.py), at the city's units."""
import json

import pytest

from collector import agenda_center as ac
from collector import city_run
from collector import civicclerk as cc
from collector.city_run import cmd_fetch, cmd_fetch_civicclerk, new_log
from collector.store import Store
from collector.tests.test_agenda_center import FIX, FakeFetcher, small_cfg
from collector.tests.test_civicclerk import JAN4, WORK, Pages
from collector.tests.test_shrink_guard import STEPS, collect, issue_step

EMPTY_200 = b"<html><body><div id='main'>Agenda Center</div></body></html>"      # no heading, no table


@pytest.fixture(scope="module")
def acfg():
    return ac.load_config()


@pytest.fixture(scope="module")
def ccfg():
    return cc.load_config()


def store(tmp_path):
    return Store(manifest_path=tmp_path / "m.json", root=tmp_path / "s")


def committed_agenda_center(acfg, tmp_path):
    """The 2019 listing as committed (three rows), from a full read."""
    c = small_cfg(acfg, (2019, 2019))
    path = tmp_path / "listing.json"
    f = FakeFetcher({c.listing_url(2019): (FIX / "search_2019_excerpt.html").read_bytes()})
    cmd_fetch(c, store(tmp_path), path, new_log(), fetcher=f)
    assert len(json.loads(path.read_text())) == 3
    return c, path


def test_an_empty_agenda_center_page_parses_to_no_rows_so_the_guard_is_what_keeps_them(acfg):
    assert ac.parse_listing(EMPTY_200.decode(), acfg, 2019) == ([], [])


def keys(entries):
    return [e["key"] for e in entries]


def test_an_empty_agenda_center_year_keeps_the_committed_rows_and_warns(acfg, tmp_path):
    c, path = committed_agenda_center(acfg, tmp_path)
    before = path.read_text()
    log = new_log()
    rows = cmd_fetch(c, store(tmp_path), path, log, fetcher=FakeFetcher({c.listing_url(2019): EMPTY_200}))
    assert rows == []                                       # nothing new is fetched for a page that lists nothing
    assert path.read_text() == before                       # the committed rows stay, as committed
    assert log["failures"] == []                            # a warning, never a failure row (ADR 0006 I2)
    assert city_run.exit_code(log) == 0 and city_run.kept_anything(log)
    [kept] = log["guard"]["kept_listing_rows"]
    assert keys(kept["kept"]) == ["10312019-303", "12052019-325", "12302019-340"]
    assert kept["kept"][1]["meeting"] == "2019-12-05-regular"            # the id --allow-drop takes


def test_a_partly_shrunk_listing_keeps_the_rows_it_lost_and_writes_what_it_gained(acfg, tmp_path):
    c, path = committed_agenda_center(acfg, tmp_path)
    page = (FIX / "search_2019_excerpt.html").read_text(encoding="utf-8")
    rows = ac.parse_listing(page, c, 2019)[0]
    lost = rows[0]["agenda_id"]
    log = new_log()
    shrunk = [r for r in rows if r["agenda_id"] != lost] + [{**rows[1], "agenda_id": "12192019-999"}]
    out = city_run.guard_listing(shrunk, json.loads(path.read_text()), "agenda_id", path.name, log)
    assert {r["agenda_id"] for r in out} == {r["agenda_id"] for r in rows} | {"12192019-999"}
    assert [r["date"] for r in out] == sorted(r["date"] for r in out)
    assert keys(log["guard"]["kept_listing_rows"][0]["kept"]) == [lost] and log["failures"] == []


def test_a_grown_listing_is_not_guarded(acfg, tmp_path):
    c, path = committed_agenda_center(acfg, tmp_path)
    old = json.loads(path.read_text())
    log = new_log()
    grown = old + [{**old[0], "agenda_id": "12192019-999", "date": "2019-12-19"}]
    assert city_run.guard_listing(grown, old, "agenda_id", path.name, log) == grown
    assert log == new_log()


def test_allow_shrink_lets_a_deliberate_removal_through_and_records_it(acfg, tmp_path):
    c, path = committed_agenda_center(acfg, tmp_path)
    log = new_log()
    cmd_fetch(c, store(tmp_path), path, log, fetcher=FakeFetcher({c.listing_url(2019): EMPTY_200}),
              allow_shrink=True)
    assert json.loads(path.read_text()) == [] and log["failures"] == []
    assert keys(log["guard"]["allowed_shrink"][0]["dropped"]) == ["10312019-303", "12052019-325", "12302019-340"]


def test_an_empty_civicclerk_events_page_keeps_the_committed_listing_and_warns(ccfg, acfg, tmp_path):
    path = tmp_path / "civicclerk-listing.json"
    cmd_fetch_civicclerk(ccfg, acfg.kind_of, store(tmp_path), path, new_log(),
                         fetcher=Pages({ccfg.first_url(): {"value": [JAN4, WORK]}}), cache_dir=tmp_path / "c")
    before = path.read_text()
    assert [r["event_id"] for r in json.loads(before)] == [91, 1765]
    log = new_log()
    rows = cmd_fetch_civicclerk(ccfg, acfg.kind_of, store(tmp_path), path, log,
                                fetcher=Pages({ccfg.first_url(): {"value": []}}), cache_dir=tmp_path / "c")
    assert rows == [] and path.read_text() == before
    assert log["failures"] == [] and city_run.kept_anything(log)
    assert keys(log["guard"]["kept_listing_rows"][0]["kept"]) == ["91", "1765"]     # past rows, with or without minutes


def test_a_cancelled_future_event_without_minutes_drops_without_a_warning(ccfg, acfg, tmp_path):
    """ADR 0006 fix 1: a committed row with no minutes, dated on or after the run's UTC day, that the listing no longer
    has (a cancelled or deleted event: civicclerk skips isDeleted) is dropped and listed, with no code."""
    path = tmp_path / "civicclerk-listing.json"
    future = {**JAN4, "id": 4001, "startDateTime": "2099-03-01T18:00:00Z", "eventDate": "2099-03-01T18:00:00Z",
              "publishedFiles": [f for f in JAN4["publishedFiles"] if f["type"] == "Agenda"]}
    cmd_fetch_civicclerk(ccfg, acfg.kind_of, store(tmp_path), path, new_log(),
                         fetcher=Pages({ccfg.first_url(): {"value": [JAN4, future]}}), cache_dir=tmp_path / "c")
    assert [r["event_id"] for r in json.loads(path.read_text())] == [91, 4001]
    log = new_log()
    cmd_fetch_civicclerk(ccfg, acfg.kind_of, store(tmp_path), path, log, today="2026-11-12",
                         fetcher=Pages({ccfg.first_url(): {"value": [JAN4]}}), cache_dir=tmp_path / "c")
    assert [r["event_id"] for r in json.loads(path.read_text())] == [91]
    assert keys(log["guard"]["dropped_unminuted"][0]["dropped"]) == ["4001"]
    assert not city_run.kept_anything(log) and city_run.exit_code(log) == 0       # (the fake serves no minutes PDF)


def test_a_vanished_row_with_minutes_is_kept_and_warns(ccfg, acfg, tmp_path):
    """The same event once its minutes are listed, or dated before the run's day, is kept as committed (exit 7)."""
    path = tmp_path / "civicclerk-listing.json"
    cmd_fetch_civicclerk(ccfg, acfg.kind_of, store(tmp_path), path, new_log(),
                         fetcher=Pages({ccfg.first_url(): {"value": [JAN4, WORK]}}), cache_dir=tmp_path / "c")
    before = path.read_text()
    log = new_log()
    cmd_fetch_civicclerk(ccfg, acfg.kind_of, store(tmp_path), path, log, today="2026-11-12",
                         fetcher=Pages({ccfg.first_url(): {"value": [WORK]}}), cache_dir=tmp_path / "c")
    assert path.read_text() == before and keys(log["guard"]["kept_listing_rows"][0]["kept"]) == ["91"]
    assert city_run.kept_anything(log) and "dropped_unminuted" not in log["guard"]


# ------------------------------------------------------------------ the build: committed meetings are never dropped
@pytest.fixture
def city(tmp_path, monkeypatch):
    """`collector city build` with the build faked: it returns `state['meetings']`; nothing touches data/."""
    d = tmp_path / "data"
    p = {"dir": d, "listing": d / "listing.json", "manifest": d / "manifest.json", "facts": d / "facts.json",
         "wards": d / "wards.json", "cc_listing": d / "cc.json", "report": tmp_path / "city-report.json"}
    monkeypatch.setattr(city_run, "paths", lambda cfg, root=None: p)
    monkeypatch.setattr(city_run, "listing_rows", lambda p, cfg, store=None: ([], []))
    state = {"meetings": ["2026-11-05-regular", "2026-11-20-regular"], "p": p}
    gates = {"roll_calls": 0, "verified": 0, "verified_rate": 0.0, "verified_rate_gate": {"pass": True},
             "g4": {"status": "ok", "flagged": [], "uniform_share": 0, "pass": True}}

    def build(cfg, rows, store):
        return ({"meetings": [{"id": m} for m in state["meetings"]], "_wards": [{"meeting_id": m}
                                                                             for m in state["meetings"]]},
                {"gates": gates})
    import collector.city_build as cb
    monkeypatch.setattr(cb, "build", build)
    d.mkdir(parents=True)
    p["facts"].write_text(json.dumps({"meetings": [{"id": "2026-11-05-regular"}]}))
    p["wards"].write_text("[]")
    return state


def test_a_build_that_drops_a_committed_meeting_keeps_it_and_exits_7(city, capsys):
    city["meetings"] = []
    before = {k: city["p"][k].read_text() for k in ("facts", "wards")}
    assert city_run.main(["build"]) == city_run.KEPT == 7
    assert {k: city["p"][k].read_text() for k in ("facts", "wards")} == before
    report = json.loads(city["p"]["report"].read_text())
    assert report["fetch"]["failures"] == []
    assert report["guard"]["kept_meetings"][0]["meeting_ids"] == ["2026-11-05-regular"]
    assert "KEPT" in capsys.readouterr().err


def test_a_build_that_keeps_every_committed_meeting_is_written(city):
    assert city_run.main(["build"]) == 0
    assert [m["id"] for m in json.loads(city["p"]["facts"].read_text())["meetings"]] == [
        "2026-11-05-regular", "2026-11-20-regular"]


def test_allow_shrink_writes_a_smaller_build_and_records_it(city):
    city["meetings"] = []
    assert city_run.main(["build", "--allow-shrink"]) == 0
    assert json.loads(city["p"]["facts"].read_text())["meetings"] == []
    report = json.loads(city["p"]["report"].read_text())
    assert report["guard"]["allowed_shrink"] == [{"facts": "facts.json", "dropped": ["2026-11-05-regular"]}]


# ------------------------------------------------------------------ the workflow: city 7 is a warning with its own issue
CITY_ISSUE = STEPS["Open or update the city meetings-kept issue"]


@pytest.mark.parametrize("county", [0, 7, 5])
def test_city_7_publishes_everything_and_sets_city_kept(tmp_path, county):
    code, outputs, args = collect(tmp_path, city=city_run.KEPT, county=county)
    assert code == 0 and outputs["city_kept"] == "yes" and outputs["city"] == "0"
    assert args == []                                                 # allow_shrink never reaches the city run
    assert collect(tmp_path, city=0, county=county)[1]["city_kept"] == "no"


@pytest.mark.parametrize("county", [2, 3])
def test_city_7_never_hides_a_county_hard_failure(tmp_path, county):
    assert collect(tmp_path, city=city_run.KEPT, county=county)[0] != 0


def test_the_city_run_line_takes_no_allow_shrink():
    assert "python -m collector city run; city=$?" in STEPS["Collect (polite fetch, parse, verify)"]["run"]


def test_city_kept_issue_lists_the_guard_and_strips_backticks(tmp_path):
    assert CITY_ISSUE["if"] == "always() && steps.collect.outputs.city_kept == 'yes'"
    assert CITY_ISSUE["continue-on-error"] is True and CITY_ISSUE["env"]["KEPT_TITLE"] == "Daily update: city meetings kept"
    assert "${{" not in CITY_ISSUE["run"] and "--body-file" in CITY_ISSUE["run"] and "head -c 3000" in CITY_ISSUE["run"]
    report = {"guard": {"kept_listing_rows": [{"listing": "civicclerk-listing.json",
                                               "kept": [{"key": "91", "title": "Regular ```\n# injected\n```"}]}]}}
    (tmp_path / "work" / "build").mkdir(parents=True)
    (tmp_path / "work" / "build" / "city-report.json").write_text(json.dumps(report))
    calls, body = issue_step(tmp_path, CITY_ISSUE)
    assert calls[0].startswith("issue list") and calls[1].startswith("issue create") and len(calls) == 2
    assert '"key": "91"' in body and body.count("```") == 2 and "City meetings kept" in body
    (tmp_path / "work" / "build" / "city-report.json").unlink()
    calls, body = issue_step(tmp_path, CITY_ISSUE, open_issue="23")
    assert calls[1].startswith("issue comment 23") and "unknown" in body
