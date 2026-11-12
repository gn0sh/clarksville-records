"""Invariant `city-seats/current-holder-matches-latest-attendance` (launch QA finding 1, bug sweep H3 and M1).

A seat's current holder is the member recorded in that seat who is still listed at the latest meeting read, unless
the record shows a successor (another record of that seat, or another seat for the member, starting later). When the
record cannot place anyone, the seat says so. The city's attendance lists stopped printing wards in 2025-04 (names
only, CivicClerk minutes); the county's seats.yml is derived by hand and can be older than the facts."""
import json

import pytest

from qa import site_checks
from sitegen import config, council, views
from sitegen.seats import Seats, stamp_seen, load_rows

from conftest import ROOT

CITY = ROOT / "data" / "localities" / "clarksville-tn"
CFG = config.load_council("clarksville-tn")


def _w(date, oid, ward):
    return {"date": date, "meeting_id": f"{date}-regular", "official_id": oid, "page": 1, "pro_tem": False,
            "raw_name": oid, "source_id": "s1", "ward": ward}


def _facts(*officials, mayors=()):
    return {"sources": [{"id": "s1", "url": "https://example.gov/m.pdf"}], "meetings": [], "roll_calls": [],
            "officials": [{"id": i, "title": "Member"} for i in officials] + [{"id": i, "title": "Mayor"} for i in mayors]}


def _seats(rows, latest):
    return Seats(rows, {}, latest, wording={"evidence": CFG["evidence"]["ward"], "latest": CFG["latest_words"]})


# ---------------------------------------------------------------- unit: the rule

def test_a_member_still_listed_by_name_after_the_last_ward_print_is_current():
    """Wards printed to 2020-02-01, names only after: a and b are listed at the latest list, so they are current;
    c is last listed two lists before it, so c served previously. L is the latest list, not the latest ward print."""
    wards = [_w("2020-01-01", "a", 1), _w("2020-02-01", "a", 1), _w("2020-01-01", "b", 2), _w("2020-02-01", "b", 2),
             _w("2020-01-01", "c", 3), _w("2020-02-01", "c", 3),
             _w("2020-03-01", "a", None), _w("2020-03-01", "b", None), _w("2020-03-01", "c", None),
             _w("2020-03-15", "a", None), _w("2020-03-15", "b", None),
             _w("2020-04-01", "a", None), _w("2020-04-01", "b", None)]
    rows, latest = council.holder_rows(wards, _facts("a", "b", "c"), CFG)
    assert latest == "2020-04-01"
    got = {r["official_id"]: (r["seat"], r["printed_to"], r["end"], r["seen_to"]) for r in rows}
    assert got == {"a": ("ward-1", "2020-02-01", None, "2020-04-01"), "b": ("ward-2", "2020-02-01", None, "2020-04-01"),
                   "c": ("ward-3", "2020-02-01", "2020-03-01", "2020-03-01")}
    s = _seats(rows, latest)
    assert s.current_of_seat("ward-1")["official_id"] == "a" and s.current_of_seat("ward-3") is None
    a = next(r for r in s.records if r["official_id"] == "a")
    assert s.dates_text(a) == ("seen in attendance lists from 2020-01-01 to 2020-02-01; listed by name in attendance "
                               "lists to 2020-04-01, the latest minutes read")
    assert site_checks.dates_worded(s.dates_text(a)) == []
    c = next(r for r in s.records if r["official_id"] == "c")
    assert site_checks.dates_worded(s.seat_text("c")) == [] and "to 2020-03-01" in s.seat_text("c")
    assert s.on("a", "2020-03-01") == "Ward 1"          # a vote between the last print and L carries the ward
    assert s.on("c", "2020-04-01") is None and not c["current"]
    assert s.basis(a) == "Current: in the attendance lists of the latest minutes read, 2020-04-01"


def test_a_successor_printed_in_the_seat_ends_the_carry_on():
    """a is printed in ward 1 to 2020-02-01 and listed by name on; b is printed in ward 1 from 2020-04-01. a's record
    stops at the last listing before b's start, and b holds the seat."""
    wards = [_w("2020-01-01", "a", 1), _w("2020-02-01", "a", 1), _w("2020-03-01", "a", None),
             _w("2020-04-01", "a", None), _w("2020-04-01", "b", 1), _w("2020-05-01", "b", 1),
             _w("2020-05-01", "a", None)]
    rows, latest = council.holder_rows(wards, _facts("a", "b"), CFG)
    got = sorted((r["official_id"], r["start"], r["end"]) for r in rows)
    assert got == [("a", "2020-01-01", "2020-03-01"), ("b", "2020-04-01", None)]


def test_a_member_moved_to_another_seat_is_not_carried_on_in_the_old_one():
    wards = [_w("2020-01-01", "a", 1), _w("2020-02-01", "a", 1), _w("2020-03-01", "a", None),
             _w("2020-04-01", "a", 4), _w("2020-05-01", "a", 4)]
    rows, _ = council.holder_rows(wards, _facts("a"), CFG)
    assert sorted((r["seat"], r["end"]) for r in rows) == [("ward-1", "2020-03-01"), ("ward-4", None)]


def test_the_mayor_is_carried_on_by_name_until_the_next_mayor_starts():
    """The mayor's seat comes from confirmed roll calls; after the last one the attendance lists still list the
    mayor, so the record runs on to L and its basis is the attendance lists (city-pages/current-basis)."""
    facts = _facts("a", mayors=("m1", "m2"))
    facts["meetings"] = [{"id": f"{d}-regular", "date": d} for d in ("2020-01-01", "2020-02-01", "2020-05-01")]
    facts["roll_calls"] = [{"id": f"rc{i}", "meeting_id": f"{d}-regular", "source_id": "s1", "page": 2,
                            "verification": {"status": "verified"}, "votes": [{"official_id": o}]}
                           for i, (d, o) in enumerate([("2020-01-01", "m1"), ("2020-02-01", "m1"), ("2020-05-01", "m2")])]
    wards = [_w(d, o, None) for d, o in [("2020-01-01", "m1"), ("2020-03-01", "m1"), ("2020-04-01", "m1"),
                                         ("2020-05-01", "m1"), ("2020-05-01", "m2"), ("2020-06-01", "m2")]]
    rows, latest = council.holder_rows(wards, facts, CFG)
    got = sorted((r["official_id"], r["start"], r["end"], r["evidence"], r.get("seen_evidence")) for r in rows)
    assert latest == "2020-06-01"
    assert got == [("m1", "2020-01-01", "2020-04-01", "attendance lists", "roll calls"),
                   ("m2", "2020-05-01", None, "attendance lists", "roll calls")]
    s = _seats(rows, latest)
    m2 = s.current_of_seat("city-mayor")
    assert s.dates_text(m2).startswith("seen in roll calls from 2020-05-01 to 2020-05-01; listed by name in attendance")


def test_an_unresolved_name_is_never_placed_and_its_seat_says_so():
    """Nobody resolved is listed for ward 2 at the latest two lists (the new name resolves to no official): ward 2 has
    no current holder, and its former member served previously (as Ward 2 on the real data, CLAUNCH)."""
    wards = [_w("2020-01-01", "a", 1), _w("2020-02-01", "a", 1), _w("2020-01-01", "b", 2), _w("2020-02-01", "b", 2),
             _w("2020-03-01", "a", None), _w("2020-03-01", None, None),
             _w("2020-04-01", "a", None), _w("2020-04-01", None, None)]
    rows, latest = council.holder_rows(wards, _facts("a", "b"), CFG)
    s = _seats(rows, latest)
    assert s.current_of_seat("ward-1")["official_id"] == "a"
    assert s.current_of_seat("ward-2") is None and not s.is_current("b")


# ---------------------------------------------------------------- the committed city data

@pytest.fixture(scope="module")
def real_city():
    facts = json.loads((CITY / "facts.json").read_text(encoding="utf-8"))
    wards = json.loads((CITY / "wards.json").read_text(encoding="utf-8"))
    return facts, wards, council.load({**CFG}, facts, wards)


def test_every_member_in_the_latest_attendance_list_holds_their_last_printed_ward(real_city):
    """QA finding 1: all 12 wards read "Current member not yet recorded" while the 2026 lists name the members."""
    facts, wards, cix = real_city
    expected = site_checks.expected_ward_holders(wards)
    assert len(expected) >= 10
    seats = {s["seat"]: s for s in council.seat_list(cix)}
    for ward, oid in expected.items():
        assert seats[f"ward-{ward}"]["holder"] is not None, ward
        assert seats[f"ward-{ward}"]["holder"]["href"] == cix.official_href(oid)
        assert cix.seats.is_current(oid)


def test_the_latest_minutes_read_is_the_latest_attendance_list(real_city):
    """H3: the basis said "the latest minutes read, 2026-02-05" while later minutes were read."""
    facts, wards, cix = real_city
    read = max(m["date"] for m in facts["meetings"] if m["minutes_status"] == "read" and m.get("attendance"))
    assert cix.seats.latest == read == max(w["date"] for w in wards)
    assert views.observed_basis(cix).endswith(f"{CFG['latest_words']}, {read}")


def test_no_one_listed_at_the_latest_minutes_is_served_previously(real_city):
    facts, wards, cix = real_city
    latest = max(w["date"] for w in wards)
    listed = {w["official_id"] for w in wards if w["date"] == latest}
    page = views.officials_page(cix)
    previous = next(s for s in page["sections"] if s["key"] == "previous")
    assert not listed & {c["id"] for c in previous["cards"]}


def test_a_confirmed_vote_after_the_last_ward_print_carries_the_ward(real_city):
    """H3: the seat beside a confirmed 2026 vote read "seat not recorded"."""
    facts, wards, cix = real_city
    last_print = max(w["date"] for w in wards if w["ward"] is not None)
    dates = {m["id"]: m["date"] for m in facts["meetings"]}
    expected = {oid: ward for ward, oid in site_checks.expected_ward_holders(wards).items()}
    n = 0
    for rc in facts["roll_calls"]:
        d = dates[rc["meeting_id"]]
        if d > last_print and views.is_verified(rc):
            for v in rc["votes"]:
                if v.get("official_id") in expected:
                    n += 1
                    assert cix.seats.on(v["official_id"], d) == f"Ward {expected[v['official_id']]}"
    assert n


# ---------------------------------------------------------------- county (M1)

def _county_plus_one_meeting():
    facts = json.loads((ROOT / "data" / "facts.json").read_text(encoding="utf-8"))
    latest = max(m["date"] for m in facts["meetings"])
    ids = {m["id"] for m in facts["meetings"] if m["date"] == latest}
    new = {**next(m for m in facts["meetings"] if m["id"] in ids), "id": "2099-01-01-formal", "date": "2099-01-01"}
    rcs = [{**rc, "id": rc["id"] + "-new", "meeting_id": new["id"], "page": 9999}
           for rc in facts["roll_calls"] if rc["meeting_id"] in ids]
    return {**facts, "meetings": [*facts["meetings"], new], "roll_calls": [*facts["roll_calls"], *rcs]}, latest


def test_county_seats_are_unchanged_while_seats_yml_is_current():
    facts = json.loads((ROOT / "data" / "facts.json").read_text(encoding="utf-8"))
    rows = stamp_seen(load_rows(config.SEATS_PATH), facts)
    ix = views.Index(facts, rows)
    assert ix.seats.latest == ix.latest
    assert all(r["current"] for r in ix.seats.records if r["end"] is None)
    assert sum(1 for d in views.district_rows(ix) if d["holder_href"]) == config.SITE["district_count"]


def test_a_new_county_meeting_never_dates_an_open_row_past_its_last_page():
    """M1: one meeting collected after seats.yml was derived. Every open row is worded to the meeting its last page
    shows, as "the latest meeting read for seats", and still current; no seat text names the new date."""
    facts, read = _county_plus_one_meeting()
    ix = views.Index(facts, stamp_seen(load_rows(config.SEATS_PATH), facts))
    assert ix.latest == "2099-01-01" and ix.seats.latest == read
    assert sum(1 for d in views.district_rows(ix) if d["holder_href"]) == config.SITE["district_count"]
    for r in ix.seats.records:
        text = ix.seats.dates_text(r)
        assert "2099-01-01" not in text
        if r["current"] and r["dates"] == "observed":
            assert text.endswith(f"to {read}, the latest meeting read for seats")
            assert ix.seats.on(r["official_id"], "2099-01-01") is None     # the new meeting is not read for seats
    assert views.observed_basis(ix) == f"Current: in the roll calls of the latest meeting read for seats, {read}"


# ---------------------------------------------------------------- review of 0589765 (request changes)

def _drop(facts, wards, oid, date):
    """The committed city data with one member left out of one attendance list (a misread or cut-off list)."""
    facts = json.loads(json.dumps(facts))
    for m in facts["meetings"]:
        if m["date"] == date:
            m["attendance"] = [a for a in m["attendance"] if a.get("official_id") != oid]
    return facts, [w for w in wards if not (w["official_id"] == oid and w["date"] == date)]


def _until(facts, wards, date):
    """The committed city data cut at one meeting date, so that meeting's list is the latest (the D1 widening added
    later lists, and the 2026-07-06 list prints CLAULNCH, which no list before it can be compared against)."""
    facts = json.loads(json.dumps(facts))
    keep = {m["id"] for m in facts["meetings"] if m["date"] <= date}
    facts["meetings"] = [m for m in facts["meetings"] if m["id"] in keep]
    for key in ("roll_calls", "motions", "item_events"):
        facts[key] = [r for r in facts[key] if r["meeting_id"] in keep]
    return facts, [w for w in wards if w["date"] <= date]


def _home(tmp_path, seats: dict, previous=(), notes=None):
    """A city/index.html with the seat rows (and held-over notes) and the Served previously list in the template's
    shape."""
    notes = notes or {}
    lis = "".join(f'<li id="seat-{k}" data-seat="{k}"><span class="d-label">{k}</span> <span class="d-holder">'
                  + (f'<a href="../city/members/{v}.html">{v}</a>' if v else site_checks.NOT_RECORDED) + "</span>"
                  + (f' <span class="d-note muted"><a href="../city/members/{notes[k]}.html">{notes[k]}</a>: last listed'
                     f'</span>' if k in notes else "") + "</li>"
                  for k, v in seats.items())
    prev = "".join(f'<a href="../city/members/{o}.html">{o}</a>' for o in previous)
    (tmp_path / "city").mkdir(exist_ok=True)
    (tmp_path / "city" / "index.html").write_text(
        f'<ol class="districts council-seats">{lis}</ol><details class="officials-section" id="previous">{prev}'
        f'</details>', encoding="utf-8")
    return tmp_path


def _shown(cix) -> dict:
    return {s["seat"]: (s["holder"]["href"].rsplit("/", 1)[-1][:-5] if s["holder"] else None)
            for s in council.seat_list(cix)}


def _cs(facts, wards):
    return [{"slug": "city", "prefix": "city/", "facts": facts, "wards": wards, "cfg": CFG}]


def _cut(facts, wards, last):
    """The committed city data as it stood when `last` was the latest meeting held."""
    keep = {m["id"] for m in facts["meetings"] if m["date"] <= last}
    facts = {**facts, "meetings": [m for m in facts["meetings"] if m["id"] in keep],
             **{k: [x for x in facts[k] if x["meeting_id"] in keep] for k in ("roll_calls", "motions", "item_events")}}
    return facts, [w for w in wards if w["date"] <= last]


def _sections(cix) -> dict:
    return {s["key"]: {c["id"] for c in s["cards"]} for s in views.officials_page(cix)["sections"]}


def test_a_member_who_left_is_never_shown_current_for_one_more_list(real_city, tmp_path):
    """Must-fix (re-review): replay L = 2026-02-05, the first list without McLaughlin (that month the minutes list
    Ward 2 applicants: the seat was vacant). The list is shorter than the one before, so it cannot show she has gone,
    but it does not show she is there either: Ward 2 reads "not yet recorded" with a neutral line, and she is in
    neither Current nor Served previously on the seat lists. Her page keeps her dates."""
    facts, wards = _cut(*real_city[:2], "2026-02-05")
    cix = council.load({**CFG}, facts, wards)
    oid = "city-deanna-mclaughlin"
    assert cix.seats.latest == "2026-02-05"
    assert not cix.seats.is_current(oid) and cix.seats.current_of_seat("ward-2") is None
    row = next(s for s in council.seat_list(cix) if s["seat"] == "ward-2")
    assert row["holder"] is None and row["note"]["href"] == cix.official_href(oid)
    assert row["note"]["text"] == ("last listed in attendance lists 2026-01-08; not named in the attendance lists "
                                   "of 2026-02-05")
    assert site_checks.dates_worded(row["note"]["text"]) == []
    sec = _sections(cix)
    assert oid not in sec["current"] and oid not in sec["previous"] and oid in sec.get("held", set())
    assert "listed by name in attendance lists to 2026-01-08; not named in the attendance lists of 2026-02-05" \
        in cix.seats.header_text(oid)
    # the site check allows the held-over member's seat to read "not yet recorded" (allowed, not required)
    assert site_checks.check_current_holders(_home(tmp_path, _shown(cix)), facts, [], _cs(facts, wards))[0] == []


def test_one_list_that_does_not_name_a_member_shows_no_wrong_holder_and_the_next_list_restores_them(real_city, tmp_path):
    """Zacharias left out of the 2026-06-04 list (as ZAHARIAS was on 2025-09-04): Ward 1 is not shown with a wrong
    holder (it reads "not yet recorded" for that list), he is not under Served previously, and when the next list
    names him he is current in Ward 1 again."""
    oid = "city-brian-zacharias"
    facts, wards = _drop(*_until(*real_city[:2], "2026-06-04"), oid, "2026-06-04")
    cix = council.load({**CFG}, facts, wards)
    assert _shown(cix)["ward-1"] is None and not cix.seats.is_current(oid)
    text = cix.seats.header_text(oid)
    assert "to 2026-05-07; not named in the attendance lists of 2026-06-04, the latest minutes read" in text
    assert site_checks.dates_worded(text) == []
    sec = _sections(cix)
    assert oid not in sec["current"] and oid not in sec["previous"]
    assert site_checks.check_current_holders(_home(tmp_path, _shown(cix)), facts, [], _cs(facts, wards))[0] == []
    # the page that puts him under Served previously fails
    problems, _ = site_checks.check_current_holders(_home(tmp_path, _shown(cix), [oid]), facts, [], _cs(facts, wards))
    assert any(f"{oid} is under Served previously" in p for p in problems)
    # the page that shows him as the Ward 1 holder fails: the latest list does not name him (second re-review)
    problems, _ = site_checks.check_current_holders(_home(tmp_path, {**_shown(cix), "ward-1": oid}), facts, [],
                                                    _cs(facts, wards))
    assert any(f"ward-1 shows {oid}" in p for p in problems)
    # his held-over note in Ward 1 passes; a note naming someone not held over in that seat fails
    ok = _home(tmp_path, _shown(cix), notes={"ward-1": oid})
    assert site_checks.check_current_holders(ok, facts, [], _cs(facts, wards))[0] == []
    bad = _home(tmp_path, _shown(cix), notes={"ward-1": oid, "ward-2": "city-carlos-peters"})
    problems, _ = site_checks.check_current_holders(bad, facts, [], _cs(facts, wards))
    assert any("ward-2 notes city-carlos-peters" in p for p in problems)
    bad = _home(tmp_path, _shown(cix), notes={"ward-3": oid})
    problems, _ = site_checks.check_current_holders(bad, facts, [], _cs(facts, wards))
    assert any(f"ward-3 notes {oid}" in p for p in problems)
    # the next list names him again
    nxt = [{**w, "date": "2026-07-02", "meeting_id": "2026-07-02-regular"} for w in real_city[1]
           if w["date"] == "2026-06-04"]
    meeting = next(m for m in real_city[0]["meetings"] if m["id"] == "2026-06-04-regular")
    facts2 = {**facts, "meetings": [*facts["meetings"], {**meeting, "id": "2026-07-02-regular", "date": "2026-07-02"}]}
    cix2 = council.load({**CFG}, facts2, wards + nxt)
    assert _shown(cix2)["ward-1"] == oid and cix2.seats.is_current(oid)


def _next_list(facts, wards, date, after="2026-07-06"):
    """A list after the real latest one (2026-07-06), dated `date`: the 07-06 list with CLAULNCH read as Claunch, so it
    resolves all 13 names. (The 2026-07-09 minutes printed such a list; they are agenda-only since d1-minutes-identity,
    being called to order on July 6, so the next real list is not in the data yet. A made-up date avoids that row.)"""
    rows = [{**w, "date": date, "meeting_id": f"{date}-special"} for w in wards if w["date"] == after]
    claunch = next(w for w in wards if w["official_id"] == "city-eric-claunch" and w["date"] == "2026-06-22")
    rows.append({**claunch, "date": date, "meeting_id": f"{date}-special"})
    meeting = next(m for m in facts["meetings"] if m["date"] == after)
    att = [a for a in meeting["attendance"] if a.get("official_id")] + [
        {"official_id": "city-eric-claunch", "page": 1, "raw_name": "CLAUNCH", "status": "present"}]
    facts = {**facts, "meetings": [*facts["meetings"], {**meeting, "id": f"{date}-special", "date": date,
                                                         "attendance": att}]}
    return facts, wards + rows


def test_a_member_left_out_of_the_list_after_2026_07_06_is_held_over_not_former(real_city, tmp_path):
    """city-seats/one-list-drop-prev-incomplete (code review SHOULD, acc8832): the 2026-07-06 list prints 13 names and
    resolves 12 (CLAULNCH is the 13th). A next list missing one member resolves 12 too: counted against the 07-06
    list's resolved names only it looked complete and closed the member's record (Served previously). Counted against
    every name 07-06 prints, it is short: the member is held over, neither current nor former."""
    facts, wards = _next_list(*real_city[:2], "2026-07-20")
    oid = "city-brian-zacharias"
    assert {w["official_id"] for w in wards if w["date"] == "2026-07-20"} >= {oid}
    assert council.latest_list_incomplete(wards, facts, "2026-07-20", "2026-07-06") is False   # the full list
    facts, wards = _drop(facts, wards, oid, "2026-07-20")
    assert len({w["official_id"] for w in wards if w["date"] == "2026-07-20"}) == 12
    assert len({w["official_id"] for w in wards if w["date"] == "2026-07-06"}) == 12      # CLAULNCH unresolved
    assert council.latest_list_incomplete(wards, facts, "2026-07-20", "2026-07-06") is True
    rows, latest = council.holder_rows(wards, facts, CFG)
    rec = next(r for r in rows if r["official_id"] == oid)
    assert latest == "2026-07-20" and rec["end"] is None and rec["held_over"] and rec["seen_to"] == "2026-07-06"
    cix = council.load({**CFG}, facts, wards)
    assert not cix.seats.is_current(oid) and _shown(cix)["ward-1"] is None
    sec = _sections(cix)
    assert oid not in sec["current"] and oid not in sec["previous"]
    assert site_checks.check_current_holders(_home(tmp_path, _shown(cix)), facts, [], _cs(facts, wards))[0] == []


def test_the_real_latest_list_2026_07_06_holds_ward_2_over_and_shows_no_wrong_holder(real_city, tmp_path):
    """The real latest list (2026-07-06) prints CLAULNCH, which resolves to no official (never a guess): the list is
    incomplete, so Eric Claunch (last listed 2026-06-22) is held over, not current and not former, and Ward 2 shows no
    holder, only the neutral held-over note."""
    facts, wards, cix = real_city
    assert cix.seats.latest == "2026-07-06"
    assert council.latest_list_incomplete(wards, facts, "2026-07-06", "2026-06-22") is True
    oid = "city-eric-claunch"
    assert not cix.seats.is_current(oid) and cix.seats.current_of_seat("ward-2") is None
    row = next(s for s in council.seat_list(cix) if s["seat"] == "ward-2")
    assert row["holder"] is None and row["note"]["href"] == cix.official_href(oid)
    # city-seats/held-over-note-says-not-named: the list prints CLAULNCH, so it does not leave him out; the note says
    # what it prints, linked to that page (fileId 3254 p. 1), never "not named"
    assert row["note"]["text"] == ("last listed in attendance lists 2026-06-22; the attendance lists of 2026-07-06 "
                                   "print a name the record cannot place: CLAULNCH")
    assert "not named" not in row["note"]["text"] and site_checks.dates_worded(row["note"]["text"]) == []
    (cite,) = row["note"]["cites"]
    assert cite["url"].endswith("fileId=3254,plainText=false)#page=1") and cite["page"] == 1
    sec = _sections(cix)
    assert oid not in sec["current"] and oid not in sec["previous"] and oid in sec.get("held", set())
    assert 2 not in site_checks.expected_ward_holders(wards, facts)
    assert site_checks.check_current_holders(_home(tmp_path, _shown(cix)), facts, [], _cs(facts, wards))[0] == []
    # a page that shows anyone as the Ward 2 holder fails
    problems, _ = site_checks.check_current_holders(_home(tmp_path, {**_shown(cix), "ward-2": oid}), facts, [],
                                                    _cs(facts, wards))
    assert any(f"ward-2 shows {oid}" in p for p in problems)


def test_a_cut_off_latest_list_holds_over_and_a_complete_one_closes():
    """The latest list names fewer members than the one before (cut off): b is held over, not current and not
    former. A complete latest list (a new member named in full, nobody unresolved) that leaves b out closes b's
    record; so does a second list."""
    base = [_w("2020-01-01", "a", 1), _w("2020-02-01", "a", 1), _w("2020-01-01", "b", 2), _w("2020-02-01", "b", 2),
            _w("2020-03-01", "a", None), _w("2020-03-01", "b", None), _w("2020-04-01", "a", None)]
    rows, latest = council.holder_rows(base, _facts("a", "b", "c"), CFG)
    b = next(r for r in rows if r["official_id"] == "b")
    assert latest == "2020-04-01" and b["end"] is None and b["held_over"] and b["seen_to"] == "2020-03-01"
    s = _seats(rows, latest)
    assert not s.is_current("b") and s.is_held_over("b") and s.current_of_seat("ward-2") is None
    assert s.on("b", "2020-03-01") == "Ward 2" and s.on("b", "2020-04-01") is None
    rows, _ = council.holder_rows(base + [_w("2020-04-01", "c", None)], _facts("a", "b", "c"), CFG)
    assert next(r for r in rows if r["official_id"] == "b")["end"] == "2020-03-01"
    rows, _ = council.holder_rows(base + [_w("2020-05-01", "a", None)], _facts("a", "b", "c"), CFG)
    assert next(r for r in rows if r["official_id"] == "b")["end"] == "2020-03-01"


def test_a_held_over_note_says_not_named_only_when_the_list_leaves_the_member_out(tmp_path):
    """city-seats/held-over-note-says-not-named (code review MUST-FIX, 64b5c84). Both lists hold b over. A list cut
    off (it prints only a) truly leaves b out: "not named in". A list that prints a name the record cannot place (b's
    name misspelt, QQZ) does not: the note and b's dates say it prints that name, as printed, and the seat note links
    the page that prints it."""
    base = [_w("2020-01-01", "a", 1), _w("2020-02-01", "a", 1), _w("2020-01-01", "b", 2), _w("2020-02-01", "b", 2),
            _w("2020-03-01", "a", None), _w("2020-03-01", "b", None), _w("2020-04-01", "a", None)]
    meetings = [{"id": f"{d}-regular", "date": d, "source_id": "s1",
                 "attendance": [{"official_id": w["official_id"], "raw_name": w["official_id"], "page": 1,
                                 "status": "present"} for w in base if w["date"] == d]}
                for d in sorted({w["date"] for w in base})]
    cut = {**_facts("a", "b"), "meetings": meetings}
    rows, latest = council.holder_rows(base, cut, CFG)
    s = _seats(rows, latest)
    b = next(r for r in s.records if r["official_id"] == "b")
    assert b["held_over"] and b["unplaced"] == []
    assert s.held_over_text(b) == ("last listed in attendance lists 2020-03-01; not named in the attendance lists of "
                                   "2020-04-01")
    assert s.dates_text(b).endswith("to 2020-03-01; not named in the attendance lists of 2020-04-01, the latest "
                                    "minutes read")
    # the same list printing a name the record cannot place, on page 2
    misprint = json.loads(json.dumps(cut))
    misprint["meetings"][-1]["attendance"].append({"official_id": None, "raw_name": "QQZ", "page": 2,
                                                   "status": "present"})
    rows, latest = council.holder_rows(base, misprint, CFG)
    s = _seats(rows, latest)
    b = next(r for r in s.records if r["official_id"] == "b")
    assert b["held_over"] and [u["printed"] for u in b["unplaced"]] == ["QQZ"]
    assert b["unplaced"][0]["src"] == "https://example.gov/m.pdf#page=2"
    text = s.held_over_text(b)
    assert text == ("last listed in attendance lists 2020-03-01; the attendance lists of 2020-04-01 print a name the "
                    "record cannot place: QQZ")
    assert "not named" not in text and site_checks.dates_worded(text) == []
    dates = s.dates_text(b)
    assert dates.endswith("to 2020-03-01; the attendance lists of 2020-04-01, the latest minutes read, print a name "
                          "the record cannot place: QQZ")
    assert site_checks.dates_worded(dates) == []
    # two such names: both, as printed
    misprint["meetings"][-1]["attendance"].append({"official_id": None, "raw_name": "QQY", "page": 2,
                                                   "status": "present"})
    rows, latest = council.holder_rows(base, misprint, CFG)
    b = next(r for r in _seats(rows, latest).records if r["official_id"] == "b")
    assert _seats(rows, latest).held_over_text(b).endswith("print names the record cannot place: QQY, QQZ")
    # the council home's seat note links the page that prints it
    full = {**misprint, "items": [], "item_events": [], "motions": [], "corrections": [],
            "officials": [{"id": i, "title": "Member", "name": f"{i.upper()} Example"} for i in ("a", "b")],
            "coverage": {"body": CFG["body_name"], "from": "2020-01-01", "to": "2020-04-01"},
            "sources": [{**misprint["sources"][0], "kind": "minutes", "fetched_at": "2020-04-02",
                         "meeting_date": "2020-04-01", "pages": 2}]}
    cix = council.load({**CFG}, full, base)
    row = next(x for x in council.seat_list(cix) if x["seat"] == "ward-2")
    assert [(c["url"], c["page"]) for c in row["note"]["cites"]] == [("https://example.gov/m.pdf#page=2", 2)]


def test_a_list_read_through_a_printing_correction_says_what_it_prints():
    """city-seats/printed-misspelling-of-seated-member: b's last listing is read through a configured printing
    correction (wards.json `reads`, raw_name as printed). b is current from that list, and every wording of the
    record, and the council home's seat line, says plainly what the list prints, linked to its page."""
    wards = [_w("2020-01-01", "a", 1), _w("2020-02-01", "a", 1), _w("2020-01-01", "b", 2), _w("2020-02-01", "b", 2),
             _w("2020-03-01", "a", None), _w("2020-03-01", "b", None),
             {**_w("2020-04-01", "b", None), "raw_name": "QQB", "reads": "B"}, _w("2020-04-01", "a", None)]
    facts = {**_facts("a", "b"), "items": [], "item_events": [], "motions": [], "corrections": [],
             "officials": [{"id": i, "title": "Member", "name": f"{i.upper()} Example"} for i in ("a", "b")],
             "coverage": {"body": CFG["body_name"], "from": "2020-01-01", "to": "2020-04-01"},
             "sources": [{"id": "s1", "url": "https://example.gov/m.pdf", "kind": "minutes", "fetched_at": "2020-04-02",
                          "meeting_date": "2020-04-01", "pages": 1}]}
    rows, latest = council.holder_rows(wards, facts, CFG)
    b = next(r for r in rows if r["official_id"] == "b")
    assert b["end"] is None and not b["held_over"]
    assert b["printings"] == [{"printed": "QQB", "reads": "B", "date": "2020-04-01", "source_id": "s1", "page": 1}]
    assert next(r for r in rows if r["official_id"] == "a")["printings"] == []
    s = _seats(rows, latest)
    text = s.dates_text(next(r for r in s.records if r["official_id"] == "b"))
    assert text == ("seen in attendance lists from 2020-01-01 to 2020-02-01; listed by name in attendance lists to "
                    '2020-04-01, the latest minutes read; the attendance lists of 2020-04-01 print the name as "QQB"')
    assert site_checks.dates_worded(text) == []
    cix = council.load({**CFG}, facts, wards)
    row = next(x for x in council.seat_list(cix) if x["seat"] == "ward-2")
    assert row["holder"]["href"] == cix.official_href("b") and row["note"] is None
    assert row["printed"]["text"] == 'the attendance lists of 2020-04-01 print the name as "QQB"'
    assert [(c["url"], c["page"]) for c in row["printed"]["cites"]] == [("https://example.gov/m.pdf#page=1", 1)]
    assert next(x for x in council.seat_list(cix) if x["seat"] == "ward-1")["printed"] is None


def test_l_comes_from_the_attendance_lists_not_a_later_roll_call():
    """Nit 6: a confirmed mayor roll call at a meeting with no attendance list must not become L and close the
    wards (the original bug's shape)."""
    facts = _facts("a", mayors=("m",))
    facts["meetings"] = [{"id": "2020-09-01-special", "date": "2020-09-01"}]
    facts["roll_calls"] = [{"id": "rc1", "meeting_id": "2020-09-01-special", "source_id": "s1", "page": 2,
                            "verification": {"status": "verified"}, "votes": [{"official_id": "m"}]}]
    wards = [_w("2020-01-01", "a", 1), _w("2020-02-01", "a", 1), _w("2020-03-01", "a", None)]
    rows, latest = council.holder_rows(wards, facts, CFG)
    assert latest == "2020-03-01"
    assert {r["official_id"]: r["end"] for r in rows} == {"a": None, "m": None}


def test_city_seats_csv_separates_printed_and_name_only_dates(real_city):
    """Must-fix 2 (provenance/seats-csv-name-only): the CSV says which page printed the seat and which only named
    the holder; the basis never says a names-only page prints the seat."""
    import csv
    import io

    from collector.export import PROVENANCE, SEAT_COLS, seats_csv
    facts, wards, cix = real_city
    names = {o["id"]: o["name"] for o in facts["officials"]}
    out = list(csv.DictReader(io.StringIO(seats_csv(cix._rows, facts, names))))
    assert all(f"seats.{c}" in PROVENANCE for c in SEAT_COLS)
    mcl = next(r for r in out if r["official_id"] == "city-deanna-mclaughlin" and r["seen_first"] > "2020")
    rec = next(r for r in cix._rows if r["official_id"] == "city-deanna-mclaughlin" and r["start"] > "2020")
    assert mcl["printed_last"] == "2025-03-06" and mcl["printed_last_source"] == rec["printed_source"]
    assert mcl["listed_last"] == "2026-01-08" and mcl["listed_last_source"] == mcl["last_source_url"]
    assert "by name only, without the seat" in mcl["dates_basis"] and "not term dates" in mcl["dates_basis"]
    smith = next(r for r in out if r["official_id"] == "city-wanda-smith")
    assert smith["seen_last"] == "" and smith["listed_last"] == "2026-07-06" and smith["printed_last"] == "2025-03-06"


def test_the_site_check_fails_a_holder_the_latest_list_does_not_name_and_a_wrong_mayor(real_city, tmp_path):
    """Should-fix 5: the check goes both ways and covers the mayor. Filling Ward 2 with McLaughlin (last listed
    2026-01-08) fails; so does showing the former mayor; the real seats pass."""
    facts, wards, cix = real_city
    shown = _shown(cix)
    assert site_checks.check_current_holders(_home(tmp_path, shown), facts, [], _cs(facts, wards))[0] == []
    bad = {**shown, "ward-2": "city-deanna-mclaughlin", "city-mayor": "city-kim-mcmillan"}
    problems, _ = site_checks.check_current_holders(_home(tmp_path, bad), facts, [], _cs(facts, wards))
    assert any("ward-2 shows city-deanna-mclaughlin" in p for p in problems)
    assert any("city-mayor does not show city-joe-pitts" in p for p in problems)
    assert any("city-mayor shows city-kim-mcmillan" in p for p in problems)


def test_a_district_page_and_a_meeting_page_agree_after_a_new_county_meeting():
    """Should-fix 3: with a meeting collected after seats.yml, the district page's vote blocks stop at the meeting
    the seats were read to, as the meeting page's seat labels do."""
    facts, read = _county_plus_one_meeting()
    ix = views.Index(facts, stamp_seen(load_rows(config.SEATS_PATH), facts))
    for n in range(1, config.SITE["district_count"] + 1):
        ctx = views.district(n, ix, None)
        assert ctx["current_blocks"][0]["heading_rest"].endswith(f"to {read}")      # the current holder's block
        for b in ctx["current_blocks"]:
            assert "2099-01-01" not in b["heading_rest"]
            assert all(r["date"] <= read for g in b["row_groups"] for r in g["rows"])


def test_stale_seats_are_reported_by_the_site_check_and_the_seat_check(tmp_path, capsys):
    """Should-fix 4: stale seats.yml is a loud WARNING in the site check, the build log and tools/seat_check.py."""
    from tools import seat_check
    facts, read = _county_plus_one_meeting()
    roster = site_checks.read_roster(config.SEATS_PATH)
    assert site_checks.seats_fresh_note(facts, roster).startswith(f"WARNING: seats.yml is read to {read}")
    current = json.loads((ROOT / "data" / "facts.json").read_text(encoding="utf-8"))
    assert not site_checks.seats_fresh_note(current, roster).startswith("WARNING")
    p = tmp_path / "facts.json"
    p.write_text(json.dumps(facts), encoding="utf-8")
    seat_check.main(["--facts", str(p), "--seats", str(config.SEATS_PATH), "--roster", str(tmp_path / "none.yml")])
    assert f"WARNING: the records are read to {read}" in capsys.readouterr().out


def test_the_site_check_fails_one_member_in_two_seats_and_a_holder_in_the_wrong_ward(real_city, tmp_path):
    """Should-fix 2: Carlos Peters shown in Ward 2 and Ward 3 fails; so does a member shown in another member's
    ward."""
    facts, wards, cix = real_city
    shown = _shown(cix)
    problems, _ = site_checks.check_current_holders(_home(tmp_path, {**shown, "ward-2": "city-carlos-peters"}), facts,
                                                    [], _cs(facts, wards))
    assert any("city-carlos-peters is shown in 2 seats" in p for p in problems)
    assert any("ward-2 shows city-carlos-peters" in p for p in problems)
    swapped = {**shown, "ward-4": shown["ward-5"], "ward-5": shown["ward-4"]}
    problems, _ = site_checks.check_current_holders(_home(tmp_path, swapped), facts, [], _cs(facts, wards))
    assert any(p.startswith("city/index.html: ward-4 shows") for p in problems)


def test_stale_seats_go_into_the_build_result_for_the_run_log():
    """Should-fix 3: the build returns the stale-seats warning; `collector run` writes it into build/run-log.json
    (`warnings`)."""
    from sitegen.build import seat_warnings
    facts, read = _county_plus_one_meeting()
    ix = views.Index(facts, stamp_seen(load_rows(config.SEATS_PATH), facts))
    assert [w for w in seat_warnings(ix) if f"seats.yml is read to {read}" in w]
    current = json.loads((ROOT / "data" / "facts.json").read_text(encoding="utf-8"))
    assert seat_warnings(views.Index(current, stamp_seen(load_rows(config.SEATS_PATH), current))) == []
    src = (ROOT / "collector" / "__main__.py").read_text(encoding="utf-8")
    assert 'log["warnings"]' in src


def test_county_seats_csv_dates_its_open_rows_with_their_source():
    """Nit 4: an open county row's printed_last and printed_last_source are both given (from its last page)."""
    import csv
    import io

    from collector.export import seats_csv
    facts = json.loads((ROOT / "data" / "facts.json").read_text(encoding="utf-8"))
    rows = load_rows(config.SEATS_PATH)
    out = list(csv.DictReader(io.StringIO(seats_csv(rows, facts, {}))))
    for row, r in zip(out, rows):
        if r["dates"] == "observed":
            assert bool(row["printed_last"]) == bool(row["printed_last_source"]), row
            if r["end"] is None:
                assert row["printed_last"] == max(m["date"] for m in facts["meetings"]) and row["seen_last"] == ""


def test_an_open_record_seen_after_l_is_dated_to_where_it_was_seen():
    """Nit 5: a mayor roll call at a meeting with no attendance list, after L: the text names that meeting, which
    its cited page shows, not L."""
    facts = _facts("a", mayors=("m",))
    facts["meetings"] = [{"id": "2020-09-01-special", "date": "2020-09-01"}]
    facts["roll_calls"] = [{"id": "rc1", "meeting_id": "2020-09-01-special", "source_id": "s1", "page": 2,
                            "verification": {"status": "verified"}, "votes": [{"official_id": "m"}]}]
    wards = [_w("2020-01-01", "a", 1), _w("2020-02-01", "a", 1), _w("2020-03-01", "a", None)]
    rows, latest = council.holder_rows(wards, facts, CFG)
    s = _seats(rows, latest)
    m = s.current_of_seat("city-mayor")
    assert s.dates_text(m) == "seen in roll calls from 2020-09-01 to 2020-09-01"


def test_ward_2_starts_with_the_configured_member_on_the_seating_date_with_its_source(real_city):
    """city-verify M1: Eric Claunch (configured, cited: the 2026-02-11 Special Session minutes, resumed 2026-02-19,
    p. 3) holds Ward 2 from 2026-02-19, the record citing that page; Deanna McLaughlin's record ends before it. The
    latest list (2026-07-06) prints CLAULNCH, which resolves to no one, so his record stays open but held over: Ward 2
    shows no holder (test_the_real_latest_list_2026_07_06_holds_ward_2_over_and_shows_no_wrong_holder)."""
    facts, wards, cix = real_city
    src = next(s for s in facts["sources"] if s["url"].endswith("fileId=3068,plainText=false)"))
    rows = [r for r in cix._rows if r["seat"] == "ward-2"]
    claunch = next(r for r in rows if r["official_id"] == "city-eric-claunch")
    assert claunch["start"] == "2026-02-19" and claunch["source"] == f"{src['url']}#page=3"
    assert claunch["end"] is None and claunch["held_over"] and cix.seats.current_of_seat("ward-2") is None
    mcl = next(r for r in rows if r["official_id"] == "city-deanna-mclaughlin")
    assert mcl["end"] is not None and mcl["end"] < "2026-02-19"
    assert cix.seats.header_text("city-eric-claunch") == (
        "Ward 2, seen in the minutes that record the seating from 2026-02-19 to 2026-02-19; listed by name in "
        "attendance lists to 2026-06-22; the attendance lists of 2026-07-06, the latest minutes read, print a name the "
        "record cannot place: CLAULNCH")
    head = views.official("city-eric-claunch", cix)["name_source"]
    assert head["quote"] == "Eric Claunch was selected as the Ward 2 replacement and was sworn in by Mayor Pitts."
    assert head["src"]["url"] == f"{src['url']}#page=3" and head["date"] == "2026-02-11" and head["kind"] == "minutes"
    assert views.official("city-deanna-mclaughlin", cix)["name_source"] is None
