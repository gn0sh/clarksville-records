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
    c's last listing is earlier, so c served previously. L is the latest list, not the latest ward print."""
    wards = [_w("2020-01-01", "a", 1), _w("2020-02-01", "a", 1), _w("2020-01-01", "b", 2), _w("2020-02-01", "b", 2),
             _w("2020-01-01", "c", 3), _w("2020-02-01", "c", 3),
             _w("2020-03-01", "a", None), _w("2020-03-01", "b", None), _w("2020-03-01", "c", None),
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
    """Nobody resolved is listed for ward 2 at the latest list (the new name resolves to no official): ward 2 has no
    current holder, and its former member served previously."""
    wards = [_w("2020-01-01", "a", 1), _w("2020-02-01", "a", 1), _w("2020-01-01", "b", 2), _w("2020-02-01", "b", 2),
             _w("2020-03-01", "a", None), _w("2020-03-01", None, None)]
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
