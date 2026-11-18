"""T5 (docs/tasks/city-only-site.md, ADR 0012 decision 5): at-large membership and title records.

Every record is read from the attendance lists' prints (wards.json, `ward: null` + `title`), never from
`officials[].title` and never from config naming a holder. Fixture: tests/fixtures/cities/murfreesboro-tn/ (made-up
people). Meetings: 1 2025-01-14, 2 2025-06-10, 3 2025-11-11 (prints no titles), 4 2026-03-10, 5 2026-09-08.
"""
import copy
import json
from pathlib import Path

import pytest
import yaml

import pinned_data
from conftest import ROOT
from sitegen import config, council, seats
from sitegen.seats import Seats, SeatsError

FX = Path(__file__).resolve().parent / "fixtures" / "cities" / "murfreesboro-tn"
M1, M2, M3, M4, M5 = "2025-01-14", "2025-06-10", "2025-11-11", "2026-03-10", "2026-09-08"
A, B, C, G, H = (f"fx-testperson-{n}" for n in ("alpha", "bravo", "charlie", "golf", "hotel"))


def _load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


@pytest.fixture
def facts():
    return _load("facts.json")


@pytest.fixture
def prints():
    return _load("wards.json")


@pytest.fixture
def primary(monkeypatch):
    """Murfreesboro's PRIMARY, as sitegen.config normalises its site.yml block; the process itself is Clarksville's."""
    block = yaml.safe_load((ROOT / "config" / "cities" / "murfreesboro-tn" / "site.yml").read_text(encoding="utf-8"))
    p = config._primary({"primary": block["primary"]})
    monkeypatch.setattr(config, "PRIMARY", p)
    return p


def _src(facts, date):
    m = next(m for m in facts["meetings"] if m["date"] == date)
    url = next(s["url"] for s in facts["sources"] if s["id"] == m["source_id"])
    return f"{url}#page=1"


def _recs(rows, seat, oid=None):
    return sorted((r for r in rows if r["seat"] == seat and (oid is None or r["official_id"] == oid)),
                  key=lambda r: r["start"])


def _seats(rows, latest, facts):
    return Seats(rows, {o["id"]: o for o in facts["officials"]}, latest, wording=council.AT_LARGE_WORDING)


def test_vice_mayor_moves_from_a_to_b_and_each_record_is_its_own_run(primary, facts, prints):
    rows, latest = council.at_large_rows(prints, facts, primary)
    assert latest == M5
    vm = _recs(rows, "title-vice-mayor")
    assert [(r["official_id"], r["start"], r["seen_to"], r["end"]) for r in vm] == [
        (A, M1, M2, M2), (B, M4, M5, None)]
    a, b = vm
    assert (a["source"], a["last_source"]) == (_src(facts, M1), _src(facts, M2))
    assert (b["source"], b["last_source"]) == (_src(facts, M4), _src(facts, M5))
    s = _seats(rows, latest, facts)
    assert s.on(A, M1) == s.on(A, M2) == "Vice Mayor" and s.on(B, M4) == s.on(B, M5) == "Vice Mayor"
    assert s.on(A, M4) == s.on(B, M2) == "Councilmember, at large"
    assert s.current_of_seat("title-vice-mayor")["official_id"] == B
    assert s.seat_text(A) == ("Vice Mayor (seen in attendance lists 2025-01-14 to 2025-06-10); Councilmember, "
                              "at large")


def test_meeting_3_prints_no_title_so_it_shows_only_membership_labels(primary, facts, prints):
    rows, latest = council.at_large_rows(prints, facts, primary)
    s = _seats(rows, latest, facts)
    for o in facts["officials"]:
        if o["id"] != H:     # the newcomer is not on meeting 3's list
            assert s.on(o["id"], M3) == "Councilmember, at large", o["id"]
    # the Mayor printed at every meeting but 3 has two records, and nothing is carried across meeting 3's list
    assert [(r["start"], r["seen_to"]) for r in _recs(rows, "title-mayor")] == [(M1, M2), (M4, M5)]
    assert {r["official_id"] for r in _recs(rows, "title-mayor")} == {C}


def test_a_meeting_with_no_list_at_all_is_inside_one_run(primary, facts, prints):
    """The ward rule: only a list that is read and does not print the title ends a run."""
    no3 = [p for p in prints if p["date"] != M3]
    rows, _ = council.at_large_rows(no3, facts, primary)
    assert [(r["start"], r["seen_to"], r["end"]) for r in _recs(rows, "title-mayor")] == [(M1, M5, None)]


def test_two_vice_mayors_at_one_meeting_get_no_title_record_and_the_run_log_names_it(primary, facts, prints):
    conflict = _load("wards-conflict.json")
    at = {(p["meeting_id"], p["official_id"]) for p in conflict}
    mixed = [p for p in prints if (p["meeting_id"], p["official_id"]) not in at] + conflict
    rows, latest = council.at_large_rows(mixed, facts, primary)
    vm = _recs(rows, "title-vice-mayor")
    assert [(r["official_id"], r["start"], r["seen_to"]) for r in vm] == [(A, M1, M1), (B, M4, M5)]
    assert not any(r["start"] <= M2 <= (r["seen_to"] or "") for r in vm)
    s = _seats(rows, latest, facts)
    assert s.on(A, M2) == s.on(B, M2) == "Councilmember, at large"
    assert s.on(C, M2) == "Mayor"                      # the other title at that meeting is not a conflict
    # the meeting itself is still covered by the membership records, which link its source page
    assert all(r["start"] <= M2 for r in _recs(rows, "at-large", A) + _recs(rows, "at-large", B))
    log = council.title_conflicts(mixed, facts, primary)
    assert len(log) == 1 and log[0].startswith("at-large/title-conflict: ") and M2 in log[0]
    assert "Vice Mayor" in log[0]
    assert council.title_conflicts(prints, facts, primary) == []


def test_an_unresolved_name_printed_with_a_title_blocks_the_title_never_makes_it(primary, facts, prints):
    extra = dict(next(p for p in prints if p["date"] == M1 and p["official_id"] == A),
                 official_id=None, raw_name="Testperson Zzz")
    rows, _ = council.at_large_rows(prints + [extra], facts, primary)
    assert [(r["official_id"], r["start"]) for r in _recs(rows, "title-vice-mayor")] == [(A, M2), (B, M4)]
    alone = [p for p in prints if p["date"] != M1 or p["official_id"] != A] + [extra]
    rows, _ = council.at_large_rows(alone, facts, primary)
    assert all(r["official_id"] for r in rows)


def test_records_ignore_officials_title(primary, facts, prints):
    rows, latest = council.at_large_rows(prints, facts, primary)
    other = copy.deepcopy(facts)
    for o, t in zip(other["officials"], ("Mayor", "Vice Mayor", "Councilmember", "Vice Mayor")):
        o["title"] = t
    other["officials"][-1]["title"] = "Mayor"
    assert council.at_large_rows(prints, other, primary) == (rows, latest)
    # and a print's title is the only source: drop every printed title, and no title record is left
    bare = [dict(p, title=None) for p in prints]
    assert not [r for r in council.at_large_rows(bare, other, primary)[0] if r["seat"] != "at-large"]


def test_leaver_ends_at_meeting_3_and_newcomer_starts_at_meeting_4(primary, facts, prints):
    rows, latest = council.at_large_rows(prints, facts, primary)
    (g,), (h,) = _recs(rows, "at-large", G), _recs(rows, "at-large", H)
    assert (g["start"], g["end"], g["seen_to"]) == (M1, M3, M3)
    assert (h["start"], h["end"], h["seen_to"]) == (M4, None, M5)
    assert len(_recs(rows, "at-large")) == 8 == len({r["official_id"] for r in _recs(rows, "at-large")})
    s = _seats(rows, latest, facts)
    assert not s.is_current(G) and s.is_current(H)
    assert s.on(G, M4) is None and s.on(H, M3) is None        # never guessed outside a record
    assert s.header_text(G) == "Councilmember, at large, seen in attendance lists 2025-01-14 to 2025-11-11"
    assert s.header_text(H) == ("Councilmember, at large, seen in attendance lists from 2026-03-10 to 2026-09-08, the "
                                "latest minutes read")


def test_every_record_has_a_first_and_last_source_and_the_holder_rows_shape(primary, facts, prints):
    rows, _ = council.at_large_rows(prints, facts, primary)
    urls = {_src(facts, m["date"]) for m in facts["meetings"]}
    assert rows
    for r in rows:
        assert r["source"] in urls and r["last_source"] in urls, r
        assert r["dates"] == "observed" and r["evidence"] == "attendance lists"
    ward_like, _ = council.holder_rows(
        [dict(p, ward=1) for p in prints[:1]], facts,
        {"min_ward_prints": 1, "seat_word": "ward", "evidence": {"ward": "x", "title": "x"}, "title_seats": {}})
    assert all(set(r) == set(ward_like[0]) for r in rows)


def test_a_prints_file_naming_an_official_the_facts_lack_is_refused(primary, facts, prints):
    bad = prints + [dict(prints[0], official_id="someone-real")]
    with pytest.raises(SeatsError, match="someone-real"):
        council.at_large_rows(bad, facts, primary)


def test_labels_and_order_come_from_primary(primary):
    assert seats.at_large_seats() == {"title-mayor": "Mayor", "title-vice-mayor": "Vice Mayor",
                                      "at-large": "Councilmember, at large"}
    assert seats.seat_label("title-vice-mayor") == "Vice Mayor"
    assert sorted(["at-large", "title-vice-mayor", "title-mayor"], key=seats.seat_order) == [
        "title-mayor", "title-vice-mayor", "at-large"]


def test_clarksville_seat_words_are_untouched():
    assert config.PRIMARY["seats"] == "districts" and config.PRIMARY["titles"] == []
    assert seats.at_large_seats() is None
    assert seats.seat_label("at-large") == "At Large"      # the old fallback: no at-large word on a district site
    assert seats.seat_order("city-mayor") == (2, 1, "city-mayor")


def test_no_city_config_file_names_an_official():
    """Settings name which words are titles, never who holds them (ADR 0012 decision 5)."""
    names, ids = set(), set()
    for f in (_load("facts.json"), pinned_data.city()[0], pinned_data.county_facts()):
        for o in f["officials"]:
            names.add(o["name"].casefold())
            ids.add(o["id"].casefold())
    files = [p for p in (ROOT / "config" / "cities").rglob("*") if p.is_file()]
    assert files
    for p in files:
        text = p.read_text(encoding="utf-8").casefold()
        hits = sorted(n for n in names | ids if n in text)
        assert not hits, f"{p.relative_to(ROOT)} names {hits}"
