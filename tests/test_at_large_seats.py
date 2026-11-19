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
A, B, C, D, E, F, G, H = (f"fx-testperson-{n}" for n in (
    "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"))
WHO = dict(zip("ABCDEFGH", (A, B, C, D, E, F, G, H)))


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


# --- T5b: member gaps (must-fix at-large/member-gap; rule restated after at-large/short-confirm-blesses-cutoffs),
# review nits 3-5. A record splits only across a stable run: 3 complete lists in a row printing the same officials.


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
    """`oid` left out of the lists of `dates`, and the newcomer H printed there instead."""
    return _with(_without(prints, oid, *dates), H, *dates)


def _unresolved_at(prints, date, name="Testperson Unread"):
    """One printed name at `date` that resolves to no official: that list is incomplete."""
    p = next(p for p in prints if p["date"] == date)
    return dict(p, official_id=None, raw_name=name, title=None)


def _later(prints, facts, n):
    """`n` more made-up lists y1..yn after M5, each a copy of M5's prints with its own made-up source document (added
    to `facts`, the test's own copy)."""
    m5 = [p for p in prints if p["date"] == M5]
    src5 = next(s for s in facts["sources"] if s["id"] == m5[0]["source_id"])
    dates = [f"{2027 + i}-01-12" for i in range(n)]
    for d in dates:
        facts["sources"].append(dict(src5, id=f"src-fx-{d}", meeting_date=d,
                                     url=f"https://example.org/murfreesboro-fixture/minutes/{d}.pdf"))
    return prints + [dict(p, date=d, meeting_id=f"{d}-regular", source_id=f"src-fx-{d}") for d in dates for p in m5], dates


def _ysrc(d):
    return f"https://example.org/murfreesboro-fixture/minutes/{d}.pdf#page=1"


def _members(rows):
    """Every at-large record: {official: [(start, seen_to, end), ...]} by start."""
    out = {}
    for r in _recs(rows, "at-large"):
        out.setdefault(r["official_id"], []).append((r["start"], r["seen_to"], r["end"]))
    return out


def _base(last, **changed):
    """The fixture's at-large records with the lists running to `last`, and `changed` members ({letter: records})."""
    out = {o: [(M1, last, None)] for o in (A, B, C, D, E, F)}
    out.update({G: [(M1, M3, M3)], H: [(M4, last, None)]})
    out.update({WHO[k]: v for k, v in changed.items()})
    return {k: v for k, v in out.items() if v}


def test_the_split_constant_is_three_and_the_size_rule_is_gone():
    assert council.AT_LARGE_GAP_LISTS == 3
    assert not hasattr(council, "AT_LARGE_SHORT_CONFIRM")


def test_a_member_out_of_three_equal_complete_lists_gets_two_records_each_with_its_own_sources(primary, facts,
                                                                                               prints):
    """D out at y1-y3 (each prints {A-C,E,F,H}), back at y4: a stable run, so two records. The same input made by a
    page defect that cuts D's line from 3 lists running would split too: the data cannot tell them apart (accepted
    cost 2 in ADR 0012 decision 5)."""
    longer, (y1, y2, y3, y4) = _later(prints, facts, 4)
    rows, latest = council.at_large_rows(_without(longer, D, y1, y2, y3), facts, primary)
    assert latest == y4
    assert _members(rows) == _base(y4, D=[(M1, M5, M5), (y4, y4, None)])
    d = _recs(rows, "at-large", D)
    assert (d[0]["source"], d[0]["last_source"]) == (_src(facts, M1), _src(facts, M5))
    assert (d[1]["source"], d[1]["last_source"]) == (_ysrc(y4), _ysrc(y4))
    s = _seats(rows, latest, facts)
    assert s.on(D, y1) is None and s.on(D, y2) is None and s.on(D, y3) is None    # inside the gap: no seat label
    assert s.on(D, M5) == s.on(D, y4) == "Councilmember, at large"
    assert s.is_current(D) and s.seat_text(D) == "Councilmember, at large"   # the current record only
    assert s.header_text(D) == (f"Councilmember, at large, seen in attendance lists from {y4} to {y4}, the latest "
                                f"minutes read; Councilmember, at large, seen in attendance lists {M1} to {M5}")


def test_a_member_out_of_one_complete_list_keeps_one_record(primary, facts, prints):
    for gap in (M2, M3, M4):
        rows, latest = council.at_large_rows(_without(prints, D, gap), facts, primary)
        assert _members(rows) == _base(M5), gap
        assert _seats(rows, latest, facts).on(D, gap) == "Councilmember, at large"


def test_a_member_out_of_two_lists_of_any_kind_keeps_one_record(primary, facts, prints):
    longer, (y1, y2, y3, y4) = _later(prints, facts, 4)
    for name, mixed, last in (
            ("cut at M2-M3", _without(prints, D, M2, M3), M5),
            ("H printed in D's place at M2-M3", _gap(prints, D, M2, M3), M5),
            ("out at y1-y2, equal sets", _without(longer, D, y1, y2), y4)):
        rows, _ = council.at_large_rows(mixed, facts, primary)
        want = _base(last, H=[((M2 if "H printed" in name else M4), last, None)])
        assert _members(rows) == want, name


def test_two_missing_lists_of_which_one_is_incomplete_keep_one_record(primary, facts, prints):
    for unread in (M2, M3):     # an unresolved name makes that list incomplete: it is skipped
        mixed = _gap(prints, D, M2, M3) + [_unresolved_at(prints, unread)]
        rows, _ = council.at_large_rows(mixed, facts, primary)
        assert [(r["start"], r["seen_to"]) for r in _recs(rows, "at-large", D)] == [(M1, M5)], unread
    # an attendance entry with no official (facts side) makes the list incomplete too
    other = copy.deepcopy(facts)
    m3 = next(m for m in other["meetings"] if m["date"] == M3)
    m3["attendance"].append(dict(m3["attendance"][0], official_id=None, raw_name="Testperson Unread"))
    rows, _ = council.at_large_rows(_gap(prints, D, M2, M3), other, primary)
    assert [(r["start"], r["seen_to"]) for r in _recs(rows, "at-large", D)] == [(M1, M5)]


def test_an_incomplete_list_is_skipped_in_a_stable_run(primary, facts, prints):
    """D out at y1-y4 with y2 printing an unresolved name, back at y5: y1, y3, y4 are a stable run (y2 skipped), so
    it splits. D out at y1-y3 with y2 unresolved, back at y4: only 2 complete lists, one record."""
    longer, (y1, y2, y3, y4, y5) = _later(prints, facts, 5)
    rows, _ = council.at_large_rows(_without(longer, D, y1, y2, y3, y4) + [_unresolved_at(longer, y2)], facts, primary)
    assert _members(rows) == _base(y5, D=[(M1, M5, M5), (y5, y5, None)])
    short = [p for p in longer if p["date"] != y5]
    rows, _ = council.at_large_rows(_without(short, D, y1, y2, y3) + [_unresolved_at(short, y2)], facts, primary)
    assert _members(rows) == _base(y4)


def test_counterexample_a_two_cut_lists_after_a_vacancy_never_split(primary, facts, prints):
    """ADR 0012 decision 5, case (a): G leaves for good after M3 and nobody replaces G (no H anywhere); D is cut from
    M5 and y1. Two lists, no stable run: D keeps one record."""
    longer, (y1, y2, y3, y4) = _later(prints, facts, 4)
    vacancy = [p for p in longer if p["official_id"] != H and not (p["official_id"] == G and p["date"] > M3)]
    rows, latest = council.at_large_rows(_without(vacancy, D, M5, y1), facts, primary)
    assert latest == y4
    assert _members(rows) == _base(y4, H=[])
    assert _recs(rows, "at-large", D)[0]["end"] is None


def test_counterexample_b_cut_lists_without_a_vacancy_never_split(primary, facts, prints):
    """Case (b): no change beyond the fixture's; D cut at M2 and M3, E cut at M4. Every member keeps one record."""
    rows, latest = council.at_large_rows(_without(_without(prints, D, M2, M3), E, M4), facts, primary)
    assert _members(rows) == _base(M5) and len(_recs(rows, "at-large")) == 8
    assert _seats(rows, latest, facts).on(D, M2) == "Councilmember, at large"


def test_a_real_vacancy_of_three_lists_splits_and_a_shorter_one_does_not(primary, facts, prints):
    """G leaves after M3 and nobody takes the place: M4, M5, y1 each print {A-F}. Never back: G ends at M3. Back at y2:
    a stable run lies between, so a new record with its own first source. Back at y1: only 2 lists, one record
    (accepted cost 1)."""
    longer, (y1, y2, y3, y4) = _later(prints, facts, 4)
    vacancy = [p for p in longer if p["official_id"] != H and not (p["official_id"] == G and p["date"] > M3)]
    rows, latest = council.at_large_rows(vacancy, facts, primary)
    assert latest == y4 and _members(rows) == _base(y4, H=[])
    rows, latest = council.at_large_rows(_with(vacancy, G, y2, y3, y4), facts, primary)
    assert _members(rows) == _base(y4, H=[], G=[(M1, M3, M3), (y2, y4, None)])
    g = _recs(rows, "at-large", G)
    assert (g[0]["source"], g[0]["last_source"], g[1]["source"]) == (_src(facts, M1), _src(facts, M3), _ysrc(y2))
    assert _seats(rows, latest, facts).on(G, M5) is None
    rows, _ = council.at_large_rows(_with(vacancy, G, y1, y2, y3, y4), facts, primary)
    assert _members(rows) == _base(y4, H=[], G=[(M1, y4, None)])


def test_an_absence_across_a_membership_change_keeps_one_record(primary, facts, prints):
    """D out at M2-M5, back at y1: the sets are {A-C,E-G} twice, then {A-C,E,F,H} twice, so no 3 equal sets in a
    row: one record (accepted cost 1). The later lists are built first, so y1-y4 still print D."""
    longer, (y1, y2, y3, y4) = _later(prints, facts, 4)
    rows, _ = council.at_large_rows(_without(longer, D, M2, M3, M4, M5), facts, primary)
    assert _members(rows) == _base(y4)


def test_a_split_record_keeps_its_own_printings(primary, facts, prints):
    """council.printings: a listing read through a printing correction belongs to the record that covers its date."""
    longer, (y1, y2, y3, y4) = _later(prints, facts, 4)
    read = [dict(p, raw_name="TESTPERSN DELTA", reads="Testperson Delta") if p["official_id"] == D else p
            for p in _without(longer, D, y1, y2, y3)]
    rows, _ = council.at_large_rows(read, facts, primary)
    first, second = _recs(rows, "at-large", D)
    assert [p["date"] for p in first["printings"]] == [M1, M2, M3, M4, M5]
    assert [p["date"] for p in second["printings"]] == [y4]


def test_a_one_list_tail_gap_then_a_reprint_is_one_record(primary, facts, prints):
    # build 1: L = M4, and M4's list leaves D out (one list; it resolves 6 names to M3's 7, so latest_list_incomplete
    # calls it short): the one-list-drop rule holds the record over, seen to M3, neither current nor closed
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
    """Alpha, Vice Mayor at M1-M2, is out of M5, y1 and y2 (each prints {B-F,H}) and back at y3: two membership
    records, and the Vice Mayor records are A's M1-M2 and B's M4 on, as without the gap."""
    longer, (y1, y2, y3, y4) = _later(prints, facts, 4)
    rows, latest = council.at_large_rows(_without(longer, A, M5, y1, y2), facts, primary)
    assert _members(rows) == _base(y4, A=[(M1, M4, M4), (y3, y4, None)])
    vm = [(r["official_id"], r["start"], r["seen_to"]) for r in _recs(rows, "title-vice-mayor")]
    assert vm == [(A, M1, M2), (B, M4, y4)]
    assert vm == [(r["official_id"], r["start"], r["seen_to"])
                  for r in _recs(council.at_large_rows(longer, facts, primary)[0], "title-vice-mayor")]
    s = _seats(rows, latest, facts)
    assert s.on(A, y1) is None and s.on(A, M2) == "Vice Mayor" and s.on(A, y3) == "Councilmember, at large"


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
