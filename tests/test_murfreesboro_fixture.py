"""T4 (docs/tasks/city-only-site.md): the Murfreesboro-shaped fixture is schema-valid, at-large, made up, and never
matches a real official in the pinned snapshot."""
import json
from pathlib import Path

import pinned_data
from sitegen import build, config

FX = Path(__file__).resolve().parent / "fixtures" / "cities" / "murfreesboro-tn"


def _load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def test_fixture_loads_and_validates_against_the_schema():
    facts = build.load_facts(FX / "facts.json")   # schema + check_references
    assert facts["fixture"] is True
    assert len(facts["meetings"]) == 5
    assert all(len(m["attendance"]) == 7 for m in facts["meetings"])
    assert sorted({v["status"] for r in facts["roll_calls"] for v in [r["verification"]]}) == ["unverified", "verified"]
    assert sum(r["verification"]["status"] == "verified" for r in facts["roll_calls"]) == 2
    for s in facts["sources"]:
        assert s["url"].startswith("https://example.org/murfreesboro-fixture/")
    assert not build._schema_errors(build._validator(config.SCHEMA_PATH), facts)


def test_wards_are_at_large_prints_with_rotating_titles():
    rows = _load("wards.json")
    assert all(r["ward"] is None and "title" in r for r in rows)
    by = {}
    for r in rows:
        if r["title"]:
            by.setdefault(r["title"], {}).setdefault(r["date"], []).append(r["official_id"])
    vice = by["Vice Mayor"]
    assert sorted(vice) == ["2025-01-14", "2025-06-10", "2026-03-10", "2026-09-08"]
    assert vice["2025-01-14"] == vice["2025-06-10"] == ["fx-testperson-alpha"]
    assert vice["2026-03-10"] == vice["2026-09-08"] == ["fx-testperson-bravo"]
    assert not any(r["title"] for r in rows if r["date"] == "2025-11-11")    # meeting 3 prints no titles
    ids = {o["id"] for o in _load("facts.json")["officials"]}
    assert {r["official_id"] for r in rows} == ids


def test_conflict_file_prints_two_vice_mayors_at_one_meeting():
    rows = _load("wards-conflict.json")
    assert sum(r["title"] == "Vice Mayor" for r in rows) == 2
    assert len({r["meeting_id"] for r in rows}) == 1


def test_no_fixture_name_matches_a_real_official():
    real = set()
    for facts in (pinned_data.city()[0], pinned_data.county_facts()):
        for o in facts["officials"]:
            real.add(o["name"].casefold())
            real.add(o["surname"].casefold())
            real.update(a.casefold() for a in o["aliases"])
    for o in _load("facts.json")["officials"]:
        assert o["given"] == "Testperson" and o["id"].startswith("fx-")
        assert not ({o["name"].casefold(), o["surname"].casefold()} & real), o["name"]
