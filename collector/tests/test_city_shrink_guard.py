"""shrink/city-listing-unguarded: an empty or shrunk city listing (a 200 with no heading and no rows, an events page of
`{"value": []}`) or a build that loses committed meetings must never replace the committed city files. The committed
rows and meetings are kept, the run fails loudly (exit 2, a `shrink` failure in build/city-report.json) and
--allow-shrink lets a deliberate removal through. The county's rule 3 (test_shrink_guard.py), at the city's units."""
import json

import pytest

from collector import agenda_center as ac
from collector import city_run
from collector import civicclerk as cc
from collector.city_run import cmd_fetch, cmd_fetch_civicclerk, new_log
from collector.store import Store
from collector.tests.test_agenda_center import FIX, FakeFetcher, small_cfg
from collector.tests.test_civicclerk import JAN4, WORK, Pages

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


def test_an_empty_agenda_center_year_keeps_the_committed_rows_and_fails(acfg, tmp_path):
    c, path = committed_agenda_center(acfg, tmp_path)
    before = path.read_text()
    log = new_log()
    rows = cmd_fetch(c, store(tmp_path), path, log, fetcher=FakeFetcher({c.listing_url(2019): EMPTY_200}))
    assert rows == []                                       # nothing new is fetched for a page that lists nothing
    assert path.read_text() == before                       # the committed rows stay, as committed
    [fail] = log["failures"]
    assert fail["stage"] == "shrink" and "lacks 3 of the 3 committed rows" in fail["error"]
    assert city_run.exit_code(log) == city_run.LISTING_FAILED == 2
    assert log["kept_listing_rows"][0]["kept"] == ["10312019-303", "12052019-325", "12302019-340"]


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
    assert log["failures"][0]["stage"] == "shrink" and lost in log["failures"][0]["error"]


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
    assert log["allowed_shrink"][0]["dropped"] == ["10312019-303", "12052019-325", "12302019-340"]


def test_an_empty_civicclerk_events_page_keeps_the_committed_listing_and_fails(ccfg, acfg, tmp_path):
    path = tmp_path / "civicclerk-listing.json"
    cmd_fetch_civicclerk(ccfg, acfg.kind_of, store(tmp_path), path, new_log(),
                         fetcher=Pages({ccfg.first_url(): {"value": [JAN4, WORK]}}), cache_dir=tmp_path / "c")
    before = path.read_text()
    assert [r["event_id"] for r in json.loads(before)] == [91, 1765]
    log = new_log()
    rows = cmd_fetch_civicclerk(ccfg, acfg.kind_of, store(tmp_path), path, log,
                                fetcher=Pages({ccfg.first_url(): {"value": []}}), cache_dir=tmp_path / "c")
    assert rows == [] and path.read_text() == before
    [fail] = log["failures"]
    assert fail["stage"] == "shrink" and fail["source"] == cc.SOURCE and "lacks 2 of the 2" in fail["error"]
    assert city_run.exit_code(log) == 2


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


def test_a_build_that_drops_a_committed_meeting_writes_nothing_and_exits_2(city, capsys):
    city["meetings"] = []
    before = {k: city["p"][k].read_text() for k in ("facts", "wards")}
    assert city_run.main(["build"]) == city_run.LISTING_FAILED
    assert {k: city["p"][k].read_text() for k in ("facts", "wards")} == before
    report = json.loads(city["p"]["report"].read_text())
    [fail] = report["fetch"]["failures"]
    assert fail["stage"] == "shrink" and "would drop 1 of the 1" in fail["error"] and "2026-11-05-regular" in fail["error"]
    assert "SHRINK GUARD" in capsys.readouterr().err


def test_a_build_that_keeps_every_committed_meeting_is_written(city):
    assert city_run.main(["build"]) == 0
    assert [m["id"] for m in json.loads(city["p"]["facts"].read_text())["meetings"]] == [
        "2026-11-05-regular", "2026-11-20-regular"]


def test_allow_shrink_writes_a_smaller_build_and_records_it(city):
    city["meetings"] = []
    assert city_run.main(["build", "--allow-shrink"]) == 0
    assert json.loads(city["p"]["facts"].read_text())["meetings"] == []
    report = json.loads(city["p"]["report"].read_text())
    assert report["fetch"]["allowed_shrink"] == [{"facts": "facts.json", "dropped": ["2026-11-05-regular"]}]
