"""shrink/city-listing-unguarded, shrink/city-shrink-freezes-all-sources (docs/adr/0006-daily-refresh-data-guards.md):
an empty or shrunk city listing (a 200 with no heading and no rows, an events page of `{"value": []}`) or a build that
loses committed meetings never replaces the committed city data. The committed rows and meetings are kept and the run
warns (exit 7, `guard` in build/city-report.json), so the workflow publishes everything else and opens the city
meetings-kept issue; a vanished row with no minutes dated today or later drops quietly. The county's rule 3
(test_shrink_guard.py), at the city's units."""
import copy
import json
from pathlib import Path

import pytest

from collector import agenda_center as ac
from collector import city_run
from collector import civicclerk as cc
from collector.city_run import cmd_fetch, cmd_fetch_civicclerk, new_log
from collector.store import Store
from collector.tests.test_agenda_center import FIX, FakeFetcher, small_cfg
from collector.tests.test_civicclerk import JAN4, WORK, Pages
from collector.shrink_guard import check_unit, shrink_guard
from collector.tests.test_shrink_guard import STEPS, collect, issue_step, rehash

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


def test_allow_drop_lets_a_named_listing_row_go_and_keeps_the_others(acfg, tmp_path):
    """ADR 0006 fix 3 (I4): a deliberate drop names its ids; the row named by its key goes, the others stay kept."""
    c, path = committed_agenda_center(acfg, tmp_path)
    log = new_log()
    cmd_fetch(c, store(tmp_path), path, log, fetcher=FakeFetcher({c.listing_url(2019): EMPTY_200}),
              allow_drop={"12052019-325"})
    assert [r["agenda_id"] for r in json.loads(path.read_text())] == ["10312019-303", "12302019-340"]
    assert keys(log["guard"]["allowed_drop"][0]["dropped"]) == ["12052019-325"]
    assert keys(log["guard"]["kept_listing_rows"][0]["kept"]) == ["10312019-303", "12302019-340"]
    log = new_log()                                                   # a meeting id names its row too
    out = city_run.guard_listing([], json.loads(path.read_text()), "agenda_id", path.name, log,
                                 allow_drop={"2019-10-31-special"})
    assert [r["agenda_id"] for r in out] == ["12302019-340"] and log["_allow_matched"] == {"2019-10-31-special"}


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


# ------------------------------------------------------------------ the facts guard (ADR 0006 fix 2), on the committed city
CITY = Path(__file__).resolve().parents[2] / "data" / "localities" / "clarksville-tn"


@pytest.fixture(scope="module")
def committed_city():
    return (json.loads((CITY / "facts.json").read_text(encoding="utf-8")),
            json.loads((CITY / "wards.json").read_text(encoding="utf-8")))


def minutes_meetings(facts, wards):
    """Committed meetings read from their minutes, with a verified roll call, an agenda source of their own and ward
    entries: the guard's unit at its fullest (chosen from the file, so no id is pinned)."""
    kind = {s["id"]: s["kind"] for s in facts["sources"]}
    in_wards = {w["meeting_id"] for w in wards}
    verified = {r["meeting_id"] for r in facts["roll_calls"] if r["verification"]["status"] == "verified"}
    return [m for m in facts["meetings"] if kind[m["source_id"]] == "minutes" and m["id"] in verified
            and m["id"] in in_wards and m.get("agenda_source_id") not in (None, m["source_id"])]


def records_of(facts, mid):
    m = next(x for x in facts["meetings"] if x["id"] == mid)
    srcs = {m["source_id"], m.get("agenda_source_id")}
    return {"meeting": m, **{k: [r for r in facts[k] if r["meeting_id"] == mid] for k in ("roll_calls", "motions",
                                                                                          "item_events")},
            "sources": sorted((s for s in facts["sources"] if s["id"] in srcs), key=lambda s: s["id"])}


def without(facts, wards, mid, keep_agenda=True):
    """The build when one meeting's minutes are missing from the store: the meeting is agenda-only (keep_agenda) or
    absent, its minutes source and records gone, its ward entries gone."""
    f = copy.deepcopy(facts)
    m = next(x for x in f["meetings"] if x["id"] == mid)
    f["sources"] = [s for s in f["sources"] if s["id"] != m["source_id"]
                    and (keep_agenda or s["id"] != m.get("agenda_source_id"))]
    for k in ("roll_calls", "motions", "item_events"):
        f[k] = [r for r in f[k] if r["meeting_id"] != mid]
    if keep_agenda:
        m.update(source_id=m["agenda_source_id"], minutes_status="not_posted", minutes_url=None, attendance=[],
                 attendance_status="not_extracted")
    else:
        f["meetings"] = [x for x in f["meetings"] if x["id"] != mid]
    return f, [w for w in wards if w["meeting_id"] != mid]


def plus_new_meeting(facts, wards):
    """Another meeting's new data: a new agenda-only meeting at the end of the listing."""
    f = copy.deepcopy(facts)
    last = f["meetings"][-1]
    src = {**next(s for s in f["sources"] if s["id"] == last["source_id"]), "id": "src-feedfacefeed",
           "sha256": "feedfacefeed" + "0" * 52, "url": "https://example.test/new-agenda.pdf", "meeting_date": "2099-01-07"}
    f["sources"].append(src)
    f["meetings"].append({**last, "id": "2099-01-07-regular", "date": "2099-01-07", "source_id": src["id"],
                          "agenda_source_id": src["id"], "minutes_url": None, "minutes_status": "not_posted",
                          "attendance": [], "agenda_url": src["url"]})
    return f, wards


@pytest.fixture
def city(tmp_path, monkeypatch, committed_city):
    """`collector city build` on a copy of the committed city files, the build faked: it returns state['new'] and
    state['wards']; nothing touches data/."""
    import collector.city_build as cb
    from collector.verify import gates
    facts, wards = committed_city
    d = tmp_path / "data"
    p = {"dir": d, "listing": d / "listing.json", "manifest": d / "manifest.json", "facts": d / "facts.json",
         "wards": d / "wards.json", "cc_listing": d / "cc.json", "report": tmp_path / "city-report.json"}
    city_run.write_json(p["facts"], facts)
    city_run.write_json(p["wards"], wards)
    monkeypatch.setattr(city_run, "paths", lambda cfg, root=None: p)
    monkeypatch.setattr(city_run, "listing_rows", lambda p, cfg, store=None: ([], []))
    state = {"new": copy.deepcopy(facts), "wards": copy.deepcopy(wards), "p": p, "facts": facts, "w": wards}

    def build(cfg, rows, store):
        f = copy.deepcopy(state["new"])
        return {**f, "_wards": copy.deepcopy(state["wards"])}, {"gates": gates(f, set())}
    monkeypatch.setattr(cb, "build", build)
    state["out"] = lambda: (json.loads(p["facts"].read_text(encoding="utf-8")),
                            json.loads(p["wards"].read_text(encoding="utf-8")))
    state["guard"] = lambda: json.loads(p["report"].read_text(encoding="utf-8"))["guard"]
    return state


def test_city_unit_holds_on_committed_facts(committed_city):
    """The county's unit (one source document and its meetings) holds for the city, and the committed facts against
    themselves keep nothing."""
    facts, _ = committed_city
    check_unit(facts, "city facts.json")
    check_unit(city_run.minutes_units(facts), "city minutes units")
    assert shrink_guard(facts, city_run.minutes_units(facts)) == {"kept": [], "corrections": []}


def test_city_missing_minutes_keeps_that_meeting_only(city):
    m = minutes_meetings(city["facts"], city["w"])[-1]["id"]
    new, wards = without(city["facts"], city["w"], m)
    city["new"], city["wards"] = plus_new_meeting(new, wards)
    assert city_run.main(["build"]) == city_run.KEPT
    out, wards_out = city["out"]()
    assert records_of(out, m) == records_of(city["facts"], m)                      # byte-identical as committed
    assert [w for w in wards_out if w["meeting_id"] == m] == [w for w in city["w"] if w["meeting_id"] == m]
    assert "2099-01-07-regular" in {x["id"] for x in out["meetings"]}              # another meeting's new data
    assert [x["id"] for x in out["meetings"]][:-1] == [x["id"] for x in city["facts"]["meetings"]]   # same order
    [k] = city["guard"]()["kept_meetings"]
    assert k["meeting_ids"] == [m] and k["ids"]


def test_city_kept_twice_is_byte_identical(city):
    m = minutes_meetings(city["facts"], city["w"])[0]["id"]
    city["new"], city["wards"] = without(city["facts"], city["w"], m)
    assert city_run.main(["build"]) == city_run.KEPT
    first = (city["p"]["facts"].read_bytes(), city["p"]["wards"].read_bytes())
    assert first == ((CITY / "facts.json").read_bytes(), (CITY / "wards.json").read_bytes())    # as committed
    assert city_run.main(["build"]) == city_run.KEPT
    assert (city["p"]["facts"].read_bytes(), city["p"]["wards"].read_bytes()) == first


def test_city_kept_meeting_agenda_source_is_published(city):
    m = minutes_meetings(city["facts"], city["w"])[-2]
    city["new"], city["wards"] = without(city["facts"], city["w"], m["id"], keep_agenda=False)
    assert m["agenda_source_id"] not in {s["id"] for s in city["new"]["sources"]}
    assert city_run.main(["build"]) == city_run.KEPT
    out, _ = city["out"]()
    assert {m["source_id"], m["agenda_source_id"]} <= {s["id"] for s in out["sources"]}
    check_unit(out, "the merged city facts")


def _reposted(city, m, lose=False):
    """The city posted new bytes of m's minutes at a new url: new sha, new source and record ids (the county test's
    rehash), the meeting's minutes_url the new one."""
    new, sid = rehash(city["facts"], m["source_id"])
    url = "https://clarksvilletn.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=99999,plainText=false)"
    for s in new["sources"]:
        if s["id"] == sid:
            s["url"] = url
    mm = next(x for x in new["meetings"] if x["id"] == m["id"])
    mm["minutes_url"] = url
    if lose:
        rc = next(r for r in new["roll_calls"] if r["source_id"] == sid and r["verification"]["status"] == "verified")
        checks = [dict(c) for c in rc["verification"]["checks"]]
        checks[0]["ok"] = False                                     # a check fails, so the status and checks agree
        rc["verification"] = {**rc["verification"], "status": "unverified", "checks": checks}
    return new


@pytest.mark.parametrize("lose, code", [(False, 0), (True, city_run.KEPT)])
def test_city_reposted_minutes_is_a_correction(city, lose, code):
    m = minutes_meetings(city["facts"], city["w"])[-3]
    city["new"] = _reposted(city, m, lose)
    assert city_run.main(["build"]) == code
    out, _ = city["out"]()
    assert out == city["new"]                                        # the new reading wins: a correction, not kept
    g = city["guard"]()
    [c] = g["corrections"]
    assert c["meeting_ids"] == [m["id"]] and "kept_meetings" not in g
    assert bool(g.get("lowered")) is lose


def _reposted_unread(city, m, status, same_url=False):
    """The city replaced m's minutes (a new url, or new bytes at the same url) and the run did not read the new file:
    not fetched (the meeting falls back to its agenda) or a parse failure (the new file is its source, no records)."""
    new, sid = rehash(city["facts"], m["source_id"])
    mm = next(x for x in new["meetings"] if x["id"] == m["id"])
    if not same_url:
        new = _reposted(city, m)
        mm = next(x for x in new["meetings"] if x["id"] == m["id"])
    for k in ("roll_calls", "motions", "item_events"):
        new[k] = [r for r in new[k] if r["meeting_id"] != m["id"]]
    if status == "not_fetched":
        new["sources"] = [s for s in new["sources"] if s["id"] != sid]
        mm["source_id"] = mm["agenda_source_id"]
    mm.update(minutes_status=status, attendance=[], attendance_status="not_extracted")
    return new, sid, [w for w in city["w"] if w["meeting_id"] != m["id"]]


def _supersede(city, m, new, sid):
    """The store's manifest: m's committed minutes replaced at their url by the new bytes (store.superseded())."""
    old = next(s for s in city["facts"]["sources"] if s["id"] == m["source_id"])
    sha = rehash(city["facts"], m["source_id"])[0]["sources"]
    sha = next(s["sha256"] for s in sha if s["id"] == sid)
    city_run.write_json(city["p"]["manifest"], [
        {"url": old["url"], "sha256": old["sha256"], "kind": "minutes", "first_fetched_at": "2026-01-01T00:00:00+00:00",
         "superseded_by": sha},
        {"url": old["url"], "sha256": sha, "kind": "minutes", "first_fetched_at": "2026-11-12T00:00:00+00:00"}])


@pytest.mark.parametrize("status", ["not_fetched", "parse_failed"])
@pytest.mark.parametrize("same_url", [False, True], ids=["url-changed", "store-superseded"])
def test_city_reposted_minutes_not_read_keeps_the_committed_meeting(city, status, same_url):
    """shrink/city-correction-on-unread-file (ADR 0006 I1): a replaced file counts as a correction only when the new
    file was read. Unread (not fetched, parse failed), on the url-change and the store-superseded path, the committed
    meeting is kept byte-identical and the run warns (7) until the new file reads or --allow-drop names it."""
    m = minutes_meetings(city["facts"], city["w"])[-3]
    city["new"], sid, city["wards"] = _reposted_unread(city, m, status, same_url)
    if same_url:
        _supersede(city, m, city["new"], sid)
    assert city_run.main(["build"]) == city_run.KEPT
    assert (city["p"]["facts"].read_bytes(), city["p"]["wards"].read_bytes()) == \
        ((CITY / "facts.json").read_bytes(), (CITY / "wards.json").read_bytes())    # as committed, byte for byte
    g = city["guard"]()
    assert "corrections" not in g
    [k] = g["kept_meetings"]
    assert k["meeting_ids"] == [m["id"]] and k["ids"] and "were not read" in k["reason"]
    assert city_run.main(["build"]) == city_run.KEPT                  # kept again the next day, unchanged
    assert city["p"]["facts"].read_bytes() == (CITY / "facts.json").read_bytes()


def test_city_reposted_minutes_read_on_the_store_path_is_a_correction(city):
    """The positive case on the store-superseded path: new bytes at the same url that read are a correction."""
    m = minutes_meetings(city["facts"], city["w"])[-3]
    city["new"], sid = rehash(city["facts"], m["source_id"])
    _supersede(city, m, city["new"], sid)
    assert city_run.main(["build"]) == 0
    assert city["out"]()[0] == city["new"]
    [c] = city["guard"]()["corrections"]
    assert c["meeting_ids"] == [m["id"]] and c["new_source_ids"] == [sid]


def test_unread_meetings_lists_only_committed_read_minutes_now_unread():
    old = {"meetings": [{"id": "a", "minutes_status": "read"}, {"id": "b", "minutes_status": "scan_not_read"},
                        {"id": "c", "minutes_status": "read"}]}
    new = {"meetings": [{"id": "a", "minutes_status": "parse_failed"}, {"id": "b", "minutes_status": "scan_not_read"},
                        {"id": "c", "minutes_status": "read"}, {"id": "d", "minutes_status": "not_fetched"}]}
    assert city_run.unread_meetings(old, new) == {"a"}


def test_a_build_that_keeps_every_committed_meeting_is_written(city):
    city["new"], city["wards"] = plus_new_meeting(city["facts"], city["w"])
    assert city_run.main(["build"]) == 0
    assert city["out"]()[0] == city["new"] and city["guard"]() == {}


def test_allow_drop_with_an_empty_store_drops_only_the_named_meeting(city):
    """An empty store: two committed meetings vanish from the build, one is named. It goes; the other is kept (7)."""
    gone, stays = (m["id"] for m in minutes_meetings(city["facts"], city["w"])[:2])
    new, wards = without(city["facts"], city["w"], gone, keep_agenda=False)
    city["new"], city["wards"] = without(new, wards, stays, keep_agenda=False)
    assert city_run.main(["build", "--allow-drop", gone]) == city_run.KEPT
    out, _ = city["out"]()
    ids = {m["id"] for m in out["meetings"]}
    assert gone not in ids and stays in ids
    assert records_of(out, stays) == records_of(city["facts"], stays)
    g = city["guard"]()
    assert [k["meeting_ids"] for k in g["kept_meetings"]] == [[stays]]
    assert g["allowed_drop"][0]["kept_meetings"][0]["meeting_ids"] == [gone]


def test_allow_drop_unknown_id_is_refused(city, capsys):
    gone = minutes_meetings(city["facts"], city["w"])[0]["id"]
    city["new"], city["wards"] = without(city["facts"], city["w"], gone, keep_agenda=False)
    before = (city["p"]["facts"].read_bytes(), city["p"]["wards"].read_bytes())
    assert city_run.main(["build", "--allow-drop", f"{gone},2099-01-01-regular"]) == city_run.LISTING_FAILED
    assert (city["p"]["facts"].read_bytes(), city["p"]["wards"].read_bytes()) == before      # nothing written
    assert "REFUSED --allow-drop 2099-01-01-regular" in capsys.readouterr().err


def test_allow_drop_unknown_id_leaves_the_listing_as_it_was(acfg, tmp_path, monkeypatch):
    c, path = committed_agenda_center(acfg, tmp_path)
    before = path.read_bytes()
    d = tmp_path
    monkeypatch.setattr(city_run, "paths", lambda cfg, root=None: {
        "dir": d, "listing": path, "manifest": d / "m.json", "facts": d / "facts.json", "wards": d / "wards.json",
        "cc_listing": d / "cc.json", "report": d / "city-report.json"})
    monkeypatch.setattr(city_run, "load_config", lambda _p: c)
    monkeypatch.setattr(city_run, "PoliteFetcher", lambda: FakeFetcher({c.listing_url(2019): EMPTY_200}))
    assert city_run.main(["fetch", "--source", "agenda-center", "--allow-drop", "12052019-325,nope"]) == 2
    assert path.read_bytes() == before
    assert city_run.main(["fetch", "--source", "agenda-center", "--allow-drop", "12052019-325"]) == city_run.KEPT
    assert [r["agenda_id"] for r in json.loads(path.read_text())] == ["10312019-303", "12302019-340"]


def test_city_allow_shrink_flag_is_gone(capsys):
    with pytest.raises(SystemExit):
        city_run.main(["build", "--allow-shrink"])
    assert "--allow-shrink" in capsys.readouterr().err


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
