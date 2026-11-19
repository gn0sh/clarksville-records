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
A, B, C, D, G, H = (f"fx-testperson-{n}" for n in ("alpha", "bravo", "charlie", "delta", "golf", "hotel"))


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


# --- T5b: member gaps (must-fix at-large/member-gap), review nits 3-5 ------------------------------------------------


def _without(prints, oid, *dates):
    """The prints with member `oid` left out of the lists of `dates` (made up: the fixture prints every member)."""
    return [p for p in prints if not (p["official_id"] == oid and p["date"] in dates)]


def _with(prints, oid, *dates):
    """The prints plus member `oid` on the lists of `dates` (no title), where it is not printed already."""
    have = {(p["official_id"], p["date"]) for p in prints}
    name = "Testperson " + oid.rsplit("-", 1)[1].capitalize()
    extra = [dict(next(p for p in prints if p["date"] == d), official_id=oid, raw_name=name, title=None)
             for d in dates if (oid, d) not in have]
    return prints + extra


def _gap(prints, oid, *dates):
    """`oid` left out of the lists of `dates`, and the newcomer H printed there instead, so each list keeps its size
    (a list that only loses a name is a cut-off list, _complete_lists, not a departure)."""
    return _with(_without(prints, oid, *dates), H, *dates)


def _unresolved_at(prints, date, name="Testperson Unread"):
    """One printed name at `date` that resolves to no official: that list is incomplete."""
    p = next(p for p in prints if p["date"] == date)
    return dict(p, official_id=None, raw_name=name, title=None)


def test_a_member_missing_from_two_complete_lists_gets_two_records_each_with_its_own_sources(primary, facts, prints):
    assert council.AT_LARGE_GAP_LISTS == 2
    rows, latest = council.at_large_rows(_gap(prints, D, M2, M3), facts, primary)
    d = _recs(rows, "at-large", D)
    assert [(r["start"], r["seen_to"], r["end"]) for r in d] == [(M1, M1, M1), (M4, M5, None)]
    assert (d[0]["source"], d[0]["last_source"]) == (_src(facts, M1), _src(facts, M1))
    assert (d[1]["source"], d[1]["last_source"]) == (_src(facts, M4), _src(facts, M5))
    s = _seats(rows, latest, facts)
    assert s.on(D, M2) is None and s.on(D, M3) is None          # inside the gap: no seat label
    assert s.on(D, M1) == s.on(D, M4) == "Councilmember, at large"
    assert s.is_current(D) and s.seat_text(D) == "Councilmember, at large"   # the current record only
    assert s.header_text(D) == ("Councilmember, at large, seen in attendance lists from 2026-03-10 to 2026-09-08, the "
                                "latest minutes read; Councilmember, at large, seen in attendance lists on 2025-01-14")
    # every other member keeps one record
    assert all(len(_recs(rows, "at-large", o["id"])) == 1 for o in facts["officials"] if o["id"] != D)


def test_a_member_missing_from_one_complete_list_keeps_one_record(primary, facts, prints):
    for gap in (M2, M3, M4):
        rows, latest = council.at_large_rows(_without(prints, D, gap), facts, primary)
        assert [(r["start"], r["seen_to"], r["end"]) for r in _recs(rows, "at-large", D)] == [(M1, M5, None)], gap
        assert _seats(rows, latest, facts).on(D, gap) == "Councilmember, at large"


def test_two_missing_lists_of_which_one_is_incomplete_keep_one_record(primary, facts, prints):
    for unread in (M2, M3):     # an unresolved name makes that list incomplete: it neither counts nor breaks the streak
        mixed = _gap(prints, D, M2, M3) + [_unresolved_at(prints, unread)]
        rows, _ = council.at_large_rows(mixed, facts, primary)
        assert [(r["start"], r["seen_to"]) for r in _recs(rows, "at-large", D)] == [(M1, M5)], unread
    # an attendance entry with no official (facts side) makes the list incomplete too
    other = copy.deepcopy(facts)
    m3 = next(m for m in other["meetings"] if m["date"] == M3)
    m3["attendance"].append(dict(m3["attendance"][0], official_id=None, raw_name="Testperson Unread"))
    rows, _ = council.at_large_rows(_gap(prints, D, M2, M3), other, primary)
    assert [(r["start"], r["seen_to"]) for r in _recs(rows, "at-large", D)] == [(M1, M5)]


def test_three_missing_lists_with_one_incomplete_still_split(primary, facts, prints):
    """Two complete lists in the gap are enough, whatever incomplete list sits between them."""
    # M4 prints H already, so the leaver G stays one list longer to keep M4's size
    mixed = _with(_gap(prints, D, M2, M3, M4), G, M4) + [_unresolved_at(prints, M3)]
    rows, _ = council.at_large_rows(mixed, facts, primary)
    assert [(r["start"], r["seen_to"], r["end"]) for r in _recs(rows, "at-large", D)] == [(M1, M1, M1), (M5, M5, None)]


def test_a_split_record_keeps_its_own_printings(primary, facts, prints):
    """council.printings: a listing read through a printing correction belongs to the record that covers its date."""
    read = [dict(p, raw_name="TESTPERSN DELTA", reads="Testperson Delta") if p["official_id"] == D else p
            for p in _gap(prints, D, M2, M3)]
    rows, _ = council.at_large_rows(read, facts, primary)
    first, second = _recs(rows, "at-large", D)
    assert [p["date"] for p in first["printings"]] == [M1]
    assert [p["date"] for p in second["printings"]] == [M4, M5]


def test_a_one_list_tail_gap_then_a_reprint_is_one_record(primary, facts, prints):
    # build 1: L = M4, and M4's list leaves D out (one list; it resolves 6 names to M3's 7, so it is short): the
    # existing one-list-drop rule holds the record over, seen to M3, neither current nor closed
    before = _without([p for p in prints if p["date"] <= M4], D, M4)
    rows, latest = council.at_large_rows(before, facts, primary)
    assert latest == M4
    assert [(r["start"], r["seen_to"], r["end"], r["held_over"]) for r in _recs(rows, "at-large", D)] == [
        (M1, M3, None, True)]
    s = _seats(rows, latest, facts)
    assert not s.is_current(D) and s.is_held_over(D) and s.on(D, M4) is None
    # build 2: the next list prints D again, and the same record runs on to L
    rows, latest = council.at_large_rows(_without(prints, D, M4), facts, primary)
    assert [(r["start"], r["seen_to"], r["end"]) for r in _recs(rows, "at-large", D)] == [(M1, M5, None)]


def test_a_member_gap_never_carries_a_title_record_across_it(primary, facts, prints):
    """Alpha, Vice Mayor at M1-M2, leaves the lists at M3-M4 and returns at M5: two membership records, and the Vice
    Mayor records stay A's M1-M2 and B's M4-M5."""
    # H fills A's place at M3, and the leaver G stays one list longer (M4), so neither gap list is short
    rows, latest = council.at_large_rows(_with(_without(_gap(prints, A, M3), A, M4), G, M4), facts, primary)
    assert [(r["start"], r["seen_to"]) for r in _recs(rows, "at-large", A)] == [(M1, M2), (M5, M5)]
    assert [(r["official_id"], r["start"], r["seen_to"]) for r in _recs(rows, "title-vice-mayor")] == [
        (A, M1, M2), (B, M4, M5)]
    s = _seats(rows, latest, facts)
    assert s.on(A, M3) is None and s.on(A, M4) is None and s.on(A, M2) == "Vice Mayor"


def test_two_cut_off_lists_missing_the_same_member_keep_one_record(primary, facts, prints):
    """at-large/complete-list-truncated: M2 and M3 each resolve 6 officials to M1's 7 (every name resolves, the lists
    are only short). Short lists are not complete, so D's record is not split, and nobody else's either."""
    assert council.AT_LARGE_SHORT_CONFIRM == 3
    rows, latest = council.at_large_rows(_without(prints, D, M2, M3), facts, primary)
    assert [(r["start"], r["seen_to"], r["end"]) for r in _recs(rows, "at-large", D)] == [(M1, M5, None)]
    assert len(_recs(rows, "at-large")) == 8
    assert _seats(rows, latest, facts).on(D, M2) == "Councilmember, at large"


def _later(prints, facts, n):
    """`n` more made-up lists after M5, a copy of M5's prints each (and of its source page, for the URLs)."""
    m5 = [p for p in prints if p["date"] == M5]
    dates = [f"{2027 + i}-01-12" for i in range(n)]
    return prints + [dict(p, date=d, meeting_id=f"{d}-regular") for d in dates for p in m5], dates


def test_a_vacancy_confirmed_by_three_smaller_lists_still_ends_and_splits(primary, facts, prints):
    """A real departure with no successor: the council prints one name fewer from then on. Three short lists in a row
    confirm the smaller council, so they are complete: a member who returns after them gets a new record, and one who
    never returns ends at their last print, as before."""
    longer, (y1, y2, y3, y4) = _later(prints, facts, 4)
    # G leaves after M3 and nobody takes the place (H never printed): M4, M5, y1 print 6 names to M3's 7
    vacancy = [p for p in longer if p["official_id"] != H and not (p["official_id"] == G and p["date"] > M3)]
    rows, latest = council.at_large_rows(vacancy, facts, primary)
    assert latest == y4
    assert [(r["start"], r["seen_to"], r["end"]) for r in _recs(rows, "at-large", G)] == [(M1, M3, M3)]
    assert all(r["end"] is None for o in (A, B, C, D) for r in _recs(rows, "at-large", o))
    # G comes back at y2 after three short lists (M4, M5, y1): a new record, with its own first source
    back = _with(vacancy, G, y2, y3, y4)
    rows, latest = council.at_large_rows(back, facts, primary)
    g = _recs(rows, "at-large", G)
    assert [(r["start"], r["seen_to"], r["end"]) for r in g] == [(M1, M3, M3), (y2, y4, None)]
    assert _seats(rows, latest, facts).on(G, M5) is None
    # back after only two short lists (M4, M5): indistinguishable from two cut-off lists, so one record
    early = _with([p for p in vacancy if p["date"] <= M5 or p["official_id"] != G], G, y1, y2, y3, y4)
    rows, _ = council.at_large_rows(early, facts, primary)
    assert [(r["start"], r["seen_to"]) for r in _recs(rows, "at-large", G)] == [(M1, y4)]


def test_title_conflicts_keep_two_null_meeting_id_lists_apart(primary, facts, prints):
    """Nit at-large/conflict-null-id-untested: two dates whose prints have no meeting_id are two lists, one log line
    each."""
    conflict = []
    for d in (M2, M4):
        vm = next(p for p in prints if p["date"] == d and p["title"] == "Vice Mayor")
        other = next(p for p in prints if p["date"] == d and p["official_id"] == D)
        conflict += [dict(p, meeting_id=None) if p is not other else dict(p, meeting_id=None, title="Vice Mayor")
                     for p in prints if p["date"] == d]
        assert vm["official_id"] != D
    mixed = [p for p in prints if p["date"] not in (M2, M4)] + conflict
    log = council.title_conflicts(mixed, facts, primary)
    assert len(log) == 2, log
    assert M2 in log[0] and M4 in log[1] and all("no meeting id" in x and "Vice Mayor" in x for x in log)


def test_a_pro_tem_print_with_a_title_is_refused_naming_the_meeting(primary, facts, prints):
    bad = [dict(p, pro_tem=True) if p["date"] == M2 and p["official_id"] == C else p for p in prints]
    with pytest.raises(SeatsError, match=f"pro tem.*{M2} \\(2025-06-10-regular\\)"):
        council.at_large_rows(bad, facts, primary)
    with pytest.raises(SeatsError, match=M2):
        council.title_runs(bad, facts, ["Mayor"])
    # pro tem without a title is a plain print
    ok = [dict(p, pro_tem=True) if p["date"] == M3 and p["official_id"] == C else p for p in prints]
    assert council.at_large_rows(ok, facts, primary) == council.at_large_rows(prints, facts, primary)


def test_a_print_with_a_null_meeting_id_does_not_end_a_title_run(primary, facts, prints):
    """Review nit 5: the loop's end is a private sentinel, so a list whose meeting_id is null is a list like any
    other, wherever it sits (here the last list, and two dates)."""
    rows, latest = council.at_large_rows(prints, facts, primary)
    for dates in ((M5,), (M4, M5), (M2,)):
        null = [dict(p, meeting_id=None) if p["date"] in dates else p for p in prints]
        got, got_latest = council.at_large_rows(null, facts, primary)
        assert got_latest == latest
        for seat in ("title-vice-mayor", "title-mayor", "at-large"):
            assert [(r["official_id"], r["start"], r["seen_to"], r["end"]) for r in _recs(got, seat)] == [
                (r["official_id"], r["start"], r["seen_to"], r["end"]) for r in _recs(rows, seat)], (dates, seat)


def test_title_runs_is_the_shared_reader_at_large_rows_uses(primary, facts, prints):
    rows, _ = council.at_large_rows(prints, facts, primary)
    runs = council.title_runs(prints, facts, primary["titles"])
    assert [(r["official_id"], r["seat"], r["start"], r["end"]) for r in runs] == [
        (r["official_id"], r["seat"], r["start"], r["seen_to"]) for r in rows if r["seat"] != "at-large"]
    # ward-shaped prints (a wards primary) read the same way
    wards = [dict(p, ward=1 + i % 4) for i, p in enumerate(prints)]
    assert council.title_runs(wards, facts, ["Vice Mayor"]) == council.title_runs(prints, facts, ["Vice Mayor"])
    assert council.title_runs(prints, facts, []) == []


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
