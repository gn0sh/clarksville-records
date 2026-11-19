"""T4b (docs/tasks/city-only-site.md): the Salem-shaped fixture (4 wards plus a Mayor, Legistar then eScribe) is
schema-valid, made up, never matches a real official in the pinned snapshot, and reads the way ADR 0012 A1 says."""
import json
from pathlib import Path

import pinned_data
from sitegen import build, config, council

FX = Path(__file__).resolve().parent / "fixtures" / "cities" / "salem-or"
CUTOVER = "2026-07-01"
PREFIX = {"legistar": "https://example.org/salem-fixture/legistar/", "escribe": "https://example.org/salem-fixture/escribe/"}
CFG = {"seat_word": "ward", "min_ward_prints": 2, "title_seats": {"Mayor": "city-mayor"},
       "evidence": {"ward": "attendance lists", "title": "roll calls"}}


def _load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def _facts():
    return build.load_facts(FX / "facts.json")   # schema + check_references


def test_fixture_loads_and_validates_against_the_schema():
    facts = _facts()
    assert facts["fixture"] is True
    assert len(facts["meetings"]) == 6
    assert not build._schema_errors(build._validator(config.SCHEMA_PATH), facts)
    for s in facts["sources"]:
        assert s["url"].startswith("https://example.org/salem-fixture/")


def test_each_meeting_carries_one_portals_prefix_only():
    facts = _facts()
    src = {s["id"]: s for s in facts["sources"]}
    seen = []
    for m in facts["meetings"]:
        portal = "legistar" if m["date"] < CUTOVER else "escribe"
        urls = [m["minutes_url"], m["agenda_url"], src[m["source_id"]]["url"]]
        assert all(u.startswith(PREFIX[portal]) for u in urls), m["id"]
        assert not any(u.startswith(PREFIX["escribe" if portal == "legistar" else "legistar"]) for u in urls)
        seen.append(portal)
    assert seen == ["legistar"] * 3 + ["escribe"] * 3
    for r in _load("wards.json"):     # a print cites its own meeting's source
        assert src[r["source_id"]]["meeting_date"] == r["date"]


def test_roll_calls_two_confirmed_one_held_one_portal_vote_not_read():
    rcs = _facts()["roll_calls"]
    assert len(rcs) == 4
    by = {r["id"]: r["verification"] for r in rcs}
    assert sum(v["status"] == "verified" for v in by.values()) == 2
    failed = sorted(c["check"] for v in by.values() for c in v["checks"] if not c["ok"])
    assert failed == ["minutes_read", "tally_matches_stated"]
    assert all(v["status"] == "unverified" for v in by.values() if any(not c["ok"] for c in v["checks"]))


def test_wards_four_wards_mayor_every_meeting_and_the_planned_oddities():
    rows = _load("wards.json")
    dates = sorted({r["date"] for r in rows})
    assert len(dates) == 6
    for d in dates:
        day = [r for r in rows if r["date"] == d]
        assert [r["official_id"] for r in day if r["title"] == "Mayor"] == ["fx-salem-oscar"]
        assert all(r["pro_tem"] is False for r in day)
        want = [1, 2, 3, 3] if d == "2026-05-04" else [1, 2, 3, 4]      # Kilo's one wrong-ward print is a second 3
        assert sorted(r["ward"] for r in day if r["ward"] is not None) == want
    ward2 = [(r["date"], r["official_id"]) for r in rows if r["ward"] == 2]
    assert {o for d, o in ward2 if d < "2026-07-01"} == {"fx-salem-india"}        # holder changes at meeting 4
    assert {o for d, o in ward2 if d >= "2026-07-01"} == {"fx-salem-lima"}
    assert [r["date"] for r in rows if r["official_id"] == "fx-salem-kilo" and r["ward"] == 3] == ["2026-05-04"]
    pres = {}
    for r in rows:
        if r["title"] == "Council President":
            pres.setdefault(r["official_id"], []).append(r["date"])
    assert pres == {"fx-salem-hotel": dates[:3], "fx-salem-juliet": dates[3:]}
    unresolved = [r for r in rows if r["official_id"] is None]
    assert [(r["date"], r["raw_name"]) for r in unresolved] == [(dates[-1], "Testperson Kylo")]


def test_ward_machinery_reads_the_fixture():
    facts, rows = _facts(), _load("wards.json")
    recs, latest = council.holder_rows(rows, facts, CFG)
    assert latest == "2026-11-02"
    by = {}
    for r in recs:
        by.setdefault(r["seat"], []).append(r)
    assert sorted(by) == ["city-mayor", "ward-1", "ward-2", "ward-3", "ward-4"]
    # the lone wrong-ward print of Kilo (min_ward_prints: 2) is dropped: one ward-4 record, from the first meeting
    assert [(r["official_id"], r["start"]) for r in by["ward-4"]] == [("fx-salem-kilo", "2026-01-12")]
    assert [r["official_id"] for r in by["ward-3"]] == ["fx-salem-juliet"]
    # ward 2 changes holder at meeting 4: India closes at meeting 3, Lima starts at meeting 4
    assert [(r["official_id"], r["start"], r["end"]) for r in by["ward-2"]] == [
        ("fx-salem-india", "2026-01-12", "2026-05-04"), ("fx-salem-lima", "2026-07-13", None)]
    # the latest list prints a name no official matches: ward 4 is held over, naming it
    (w4,) = by["ward-4"]
    assert w4["held_over"] is True and [u["printed"] for u in w4["unplaced"]] == ["Testperson Kylo"]
    assert by["city-mayor"][0]["official_id"] == "fx-salem-oscar" and by["city-mayor"][0]["end"] is None


def test_no_fixture_name_matches_a_real_official():
    real = set()
    for facts in (pinned_data.city()[0], pinned_data.county_facts()):
        for o in facts["officials"]:
            real.add(o["name"].casefold())
            real.add(o["surname"].casefold())
            real.update(a.casefold() for a in o["aliases"])
    facts = _facts()
    for o in facts["officials"]:
        assert o["given"] == "Testperson" and o["id"].startswith("fx-salem-")
        assert not ({o["name"].casefold(), o["surname"].casefold()} & real), o["name"]
    printed = {a["raw_name"] for m in facts["meetings"] for a in m["attendance"]} | {r["raw_name"] for r in _load("wards.json")}
    assert not ({p.casefold() for p in printed} & real)
    assert not ({p.split()[-1].casefold() for p in printed} & real)
