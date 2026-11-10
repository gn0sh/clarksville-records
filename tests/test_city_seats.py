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


def _home(tmp_path, seats: dict, previous=()):
    """A city/index.html with the seat rows and the Served previously list in the template's shape."""
    lis = "".join(f'<li id="seat-{k}" data-seat="{k}"><span class="d-label">{k}</span> <span class="d-holder">'
                  + (f'<a href="../city/members/{v}.html">{v}</a>' if v else site_checks.NOT_RECORDED) + "</span></li>"
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


def test_one_list_that_does_not_name_a_member_does_not_unseat_them(real_city, tmp_path):
    """Must-fix 1 (one-list drop): Zacharias left out of the 2026-06-04 list (as ZAHARIAS was on 2025-09-04). That
    list also prints an unresolved name and resolves fewer members, so it cannot show he has gone: he stays in Ward 1,
    and the words say the latest list does not name him."""
    facts, wards = _drop(*real_city[:2], "city-brian-zacharias", "2026-06-04")
    cix = council.load({**CFG}, facts, wards)
    assert _shown(cix)["ward-1"] == "city-brian-zacharias" and cix.seats.is_current("city-brian-zacharias")
    rec = cix.seats.current_of_seat("ward-1")
    text = cix.seats.dates_text(rec)
    assert "to 2026-05-07; not named in the attendance lists of 2026-06-04, the latest minutes read" in text
    assert site_checks.dates_worded(text) == []
    assert "Ward 1: its member is not named in the attendance lists of 2026-06-04" in views.observed_basis(cix)
    previous = next(s for s in views.officials_page(cix)["sections"] if s["key"] == "previous")
    assert "city-brian-zacharias" not in {c["id"] for c in previous["cards"]}
    # the site check reads the same lists on its own: it expects him in Ward 1, and fails the page that dropped him
    assert site_checks.expected_ward_holders(wards, facts)[1] == "city-brian-zacharias"
    dropped = {**_shown(cix), "ward-1": None}
    problems, _ = site_checks.check_current_holders(_home(tmp_path, dropped, ["city-brian-zacharias"]), facts, [],
                                                    _cs(facts, wards))
    assert any("ward 1 does not show city-brian-zacharias" in p for p in problems)
    assert any("city-brian-zacharias is under Served previously" in p for p in problems)


def test_a_cut_off_latest_list_holds_over_and_a_complete_one_closes():
    """The latest list names fewer members than the one before (cut off): b is held over. A complete latest list
    (a new member named in full, nobody unresolved) that leaves b out closes b's record; so does a second list."""
    base = [_w("2020-01-01", "a", 1), _w("2020-02-01", "a", 1), _w("2020-01-01", "b", 2), _w("2020-02-01", "b", 2),
            _w("2020-03-01", "a", None), _w("2020-03-01", "b", None), _w("2020-04-01", "a", None)]
    rows, latest = council.holder_rows(base, _facts("a", "b", "c"), CFG)
    b = next(r for r in rows if r["official_id"] == "b")
    assert latest == "2020-04-01" and b["end"] is None and b["held_over"] and b["seen_to"] == "2020-03-01"
    assert _seats(rows, latest).is_current("b")
    rows, _ = council.holder_rows(base + [_w("2020-04-01", "c", None)], _facts("a", "b", "c"), CFG)
    assert next(r for r in rows if r["official_id"] == "b")["end"] == "2020-03-01"
    rows, _ = council.holder_rows(base + [_w("2020-05-01", "a", None)], _facts("a", "b", "c"), CFG)
    assert next(r for r in rows if r["official_id"] == "b")["end"] == "2020-03-01"


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
    assert smith["seen_last"] == "" and smith["listed_last"] == "2026-06-04" and smith["printed_last"] == "2025-03-06"


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
