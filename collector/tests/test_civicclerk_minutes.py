"""City Council minutes as CivicClerk posts them (M4 slice 3): the 2025-on shapes, read by the same reader and checks.

Excerpts are copied from the real minutes (pdftotext -layout), names and line breaks as printed:
- 2025-01-02 and 2024 minutes: full names with wards, as the Agenda Center's ("PRESENT: Brian Zacharias (Ward 1), ...")
- 2025-03-06: surnames with wards ("PRESENT: Zacharias (Ward 1), Peters (Ward 3), ...")
- 2025-04-03 on: surnames in capitals, the mayor among them ("PRESENT: BROWN, CHANDLER (left at 7:22 pm), ...");
  vote lists in capitals over several lines ("AYE:    BROWN, HAYWOOD, LOVATO, MARQUIS, PITTS," / "SHAKEENAB, ...")
- 2026-02-05: a note broken over two lines ("SMITH (ARRIVED AT" / "6:03 PM), STREETMAN, ZACHARIAS")
- 2024-09-05: CivicClerk lists the 2024-08-01 minutes file again as this meeting's minutes
"""
import re

import jsonschema
import pytest

from collector import agenda_center as ac
from collector.city_build import Officials, RosterBook, build, printed_full_names, resolve_surnames
from collector.city_minutes import called_to_order_on, parse_text, titled_names
from collector.tests.test_city_minutes import SCHEMA, FakeStore, entry

API = "https://clarksvilletn.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId={},plainText=false)"


@pytest.fixture(scope="module")
def cfg():
    return ac.load_config(ac.config_path("clarksville-tn"))


FULL_2025 = """                                          City of Clarksville
                                   City Council - Regular Session

                                            February 6, 2025 at 6:00 PM

                                         MINUTES

1.   Call to Order
      Regular Session of the Clarksville City Council was called to order by Mayor Joe Pitts
      on Thursday, February 6, 2025, at 6:00 p.m. in City Council Chambers, 106 Public
      Square, Clarksville, Tennessee.

2.   Attendance
      PRESENT: Brian Zacharias (Ward 1), Deanna McLaughlin (Ward 2), Carlos Peters (Ward 3), Tim
      Chandler (Ward 4), Ambar Marquis (Ward 5), Wanda Smith (Ward 6), Travis Holleman (Ward 7),
      Jerry Haywood (Ward 8), Jimmy Brown (Ward 9), Stacey Streetman (Ward 10), Joe Shakeenab
      (Ward 11), Keri Lovato (Ward 12)

3.   Consent Agenda
          Councilman Streetman made a motion to adopt the Consent Agenda. Councilman
          Holleman seconded the motion. The following vote was recorded:

             AYE: Brown, Chandler, Haywood, Holleman, Lovato, Marquis, McLaughlin,
             Peters, Pitts, Shakeenab, Smith, Streetman, Zacharias

             The motion to adopt the Consent Agenda passed.
"""

CAPS_2025 = """                                          City of Clarksville
                                   City Council - Regular Session

                                            August 7, 2025 at 6:00 PM

                                          MINUTES

1.   Call to Order
      Regular Session of the Clarksville City Council was called to order by Mayor Joe Pitts
      on Thursday, August 7, 2025, at 6:00 PM in the City Council Chambers, 106 Public
      Square, Clarksville, Tennessee. A prayer was offered by Mark Riggins; the Pledge of
      Allegiance was led by Councilman Keri Lovato.


2.   Attendance
      PRESENT: BROWN, CHANDLER (left at 7:22 pm), HAYWOOD, HOLLEMAN,
               LOVATO, MARQUIS, MCLAUGHLIN, PITTS, SHAKEENAB, SMITH,
               STREETMAN, ZACHARIAS

      ABSENT:        PETERS
3.   Special Recognition
      The Mayor presented a certificate of excellence to Karlie Saelens and declared August as
      Autoinflammatory Awareness Month.

4.   Planning Commission Public Hearing and Adoption of Zoning: Councilman Stacey
     Streetman
     A.   ORDINANCE 05-2025-26 (FIRST READING) [ZONING CASE Z-29-2025]
          An Ordinance amending the zoning code and map of the City of Clarksville,
          application of Charles Thomas Jerles, for a zone change on a tract of land fronting

        No one spoke for or against

        Councilman Streetman made a motion to adopt ORDINANCE 05-2025-26
        (FIRST READING); Councilman Holleman seconded the motion. The following
        vote was recorded:

                  AYE:    BROWN, HAYWOOD, LOVATO, MARQUIS, PITTS,
                          SHAKEENAB, SMITH, STREETMAN, ZACHARIAS

                  NAY:    CHANDLER, HOLLEMAN, MCLAUGHLIN

        The motion to adopt ORDINANCE 05-2025-26 (FIRST READING) passed.

B.   ORDINANCE 06-2025-26 (FIRST READING) [ZONING CASE Z-30-2025]
     An Ordinance amending the zoning code and map of the City of Clarksville,
     application of Donny Ray Plaster, Jr., for a zone change on a tract of land

        Councilman Streetman made a motion to adopt ORDINANCE 06-2025-26
        (FIRST READING); Councilman Holleman seconded the motion. Councilman
        Lovato then asked to postpone the Ordinance until the September Regular
        Session. Councilman McLaughlin seconded the motion. Councilman Chandler
        called for the question. Councilman Haywood objected. The following vote was
        recorded:

                AYE:       BROWN, CHANDLER, HAYWOOD, LOVATO,
                           MCLAUGHLIN, PITTS, SHAKEENAB, SMITH,
                           STREETMAN

                NAY:       MARQUIS, ZACHARIAS

                ABSTAIN: HOLLEMAN

        The motion to cease discussion passed.

        The following vote was then recorded on the motion to postpone Ordinance 06-
        2025-26 until the September Regular Session:

                  AYE:    BROWN, CHANDLER, HAYWOOD, HOLLEMAN, LOVATO,
                          MARQUIS, MCLAUGHLIN, PITTS, SHAKEENAB,
                          STREETMAN, ZACHARIAS
                      NAY:     SMITH

             The motion to postpone ORDINANCE 06-2025-26 (FIRST READING) until the
             September Regular session passed.
"""

OPEN_NOTE_2026 = """1.   Call to Order
      Regular Session of the Clarksville City Council was called to order by Mayor Joe Pitts
      on Thursday, February 5, 2026, at 6:00 PM.

2.   Attendance
      PRESENT: BROWN, HAYWOOD, HOLLEMAN, LOVATO, MARQUIS, PETERS,
               PITTS, SHAKEENAB (ARRIVED AT 6:06 PM), SMITH (ARRIVED AT
               6:03 PM), STREETMAN, ZACHARIAS

      ABSENT:        CHANDLER

3.   Consent Agenda
"""

SURNAMES_WARDS_2025 = """1.   Call to Order
      Regular Session of the Clarksville City Council was called to order by Mayor Joe Pitts
      on Thursday, March 6, 2025, at 6:00 p.m.

2.   Attendance
      PRESENT: Zacharias (Ward 1), Peters (Ward 3), Chandler (Ward 4), Marquis (Ward 5), Smith (Ward 6),
      Holleman (Ward 7), Haywood (Ward 8), Brown (Ward 9), Streetman (Ward 10), Shakeenab (Ward 11), Lovato
      (Ward 12)

      ABSENT: McLaughlin (Ward 2)

3.   Consent Agenda
"""


# ------------------------------------------------------------------ the reader
def test_capital_name_lists_run_over_several_lines(cfg):
    pm = parse_text([CAPS_2025], cfg)
    assert [p.raw_name for p in pm.present] == ["BROWN", "CHANDLER", "HAYWOOD", "HOLLEMAN", "LOVATO", "MARQUIS",
                                                "MCLAUGHLIN", "PITTS", "SHAKEENAB", "SMITH", "STREETMAN", "ZACHARIAS"]
    assert pm.present[1].left_early and [p.raw_name for p in pm.absent] == ["PETERS"]
    first = pm.roll_calls[0]
    assert [v.raw_name for v in first.votes if v.value == "yes"] == ["BROWN", "HAYWOOD", "LOVATO", "MARQUIS", "PITTS",
                                                                    "SHAKEENAB", "SMITH", "STREETMAN", "ZACHARIAS"]
    assert [v.raw_name for v in first.votes if v.value == "no"] == ["CHANDLER", "HOLLEMAN", "MCLAUGHLIN"]
    assert first.outcome == "passed" and first.outcome_text.startswith("The motion to adopt ORDINANCE 05-2025-26")


def test_every_vote_of_the_capital_shape_is_read_with_its_outcome(cfg):
    pm = parse_text([CAPS_2025], cfg)
    assert [(len(r.votes), r.outcome) for r in pm.roll_calls] == [(12, "passed"), (12, "passed"), (12, "passed")]
    assert [v.raw_value for v in pm.roll_calls[1].votes][-1] == "ABSTAIN"
    assert pm.roll_calls[1].outcome_text == "The motion to cease discussion passed."


def test_a_note_broken_over_two_lines_keeps_the_list_going(cfg):
    pm = parse_text([OPEN_NOTE_2026], cfg)
    names = [p.raw_name for p in pm.present]
    assert names == ["BROWN", "HAYWOOD", "HOLLEMAN", "LOVATO", "MARQUIS", "PETERS", "PITTS", "SHAKEENAB", "SMITH",
                     "STREETMAN", "ZACHARIAS"]
    assert pm.present[7].arrived_late and pm.present[8].arrived_late
    assert [p.raw_name for p in pm.absent] == ["CHANDLER"]


def test_a_capital_heading_after_a_list_without_a_comma_still_ends_it(cfg):
    text = "AYE: BROWN, HAYWOOD\nCONSENT AGENDA\n"
    pm = parse_text(["PRESENT: Joe Smith (Ward 1)\n\n" + text], cfg)
    assert [v.raw_name for v in pm.roll_calls[0].votes] == ["BROWN", "HAYWOOD"]


def test_titled_names_and_the_called_to_order_date(cfg):
    assert called_to_order_on(CAPS_2025) == "2025-08-07"
    assert called_to_order_on("no call to order here") is None
    assert titled_names(CAPS_2025) == ["Joe Pitts", "Keri Lovato", "Stacey Streetman"]
    assert titled_names("Mayor Pitts Councilman Shakeenab Called for the question; Councilman Haywood None") == []


def test_links_on_the_new_shapes_keep_the_invariant(cfg):
    """docs/architecture/city-council.md: a roll call is linked to a numbered item only when its own words name it
    (these minutes print items as "A.   ORDINANCE ..." lines, which are not number lines), never another item."""
    pm = parse_text([CAPS_2025], cfg)
    got = [(r.item["number"], r.link["basis"], r.link["ok"]) for r in pm.roll_calls]
    assert got == [("05-2025-26", "named", True), (None, "section", True), ("06-2025-26", "named", True)]
    for r in pm.roll_calls:
        words = " ".join(x for x in ((r.motion or {}).get("text"), r.outcome_text) if x)
        named = {m.group(2) for m in re.finditer(cfg.item_number.pattern, words, re.I)}
        if r.item["number"]:
            assert named == {r.item["number"]}
        if not r.link["ok"]:
            assert r.item["number"] is None


# ------------------------------------------------------------------ surnames to members
def roster_from(cfg, text, date):
    off = Officials(cfg)
    return printed_full_names(cfg, off, parse_text([text], cfg), date), off


def book_from(cfg, text, date, meeting="2025-08-07"):
    """The bounded book a surname-only list of `meeting` is read against, from one full-name list of `date`."""
    printed, off = roster_from(cfg, text, date)
    rb = RosterBook(cfg)
    rb.add(printed)
    return rb.for_meeting(meeting), off


def test_printed_full_names_by_surname(cfg):
    book, _ = roster_from(cfg, FULL_2025, "2025-02-06")
    assert len(book) == 13 and book["pitts"] == {"date": "2025-02-06",
                                                 "people": [{"name": "Joe Pitts", "ward": None, "mayor": True}]}
    assert book["brown"]["people"] == [{"name": "Jimmy Brown", "ward": 9, "mayor": False}]
    assert roster_from(cfg, CAPS_2025, "2025-08-07")[0] == {}                  # surnames only: nothing to learn


def test_each_surname_uses_its_own_latest_printing(cfg):
    """2025-02-06 printed a cut-off list (it ends at "Stacey Streetman"): LOVATO is read against the latest list
    that printed a Lovato, not left unresolved."""
    printed, off = roster_from(cfg, FULL_2025, "2025-01-02")
    cut = FULL_2025.replace(", Joe Shakeenab\n      (Ward 11), Keri Lovato (Ward 12)", "")
    pm_cut = parse_text([cut], cfg)
    assert "Keri Lovato" not in [p.raw_name for p in pm_cut.present]
    rb = RosterBook(cfg)
    rb.add(printed)
    rb.add(printed_full_names(cfg, off, pm_cut, "2025-02-06"))
    book = rb.for_meeting("2025-08-07")
    assert book["lovato"]["people"][0]["date"] == "2025-01-02" and book["brown"]["people"][0]["date"] == "2025-02-06"
    pm = parse_text([CAPS_2025], cfg)
    got, checks = resolve_surnames(cfg, off, pm, book)
    assert checks[0]["ok"] and "by the attendance of 2025-01-02" in checks[0]["detail"]


def test_a_repeated_label_and_a_mayor_note_in_the_attendance(cfg):
    text = ("called to order by Mayor Joe Pitts on Thursday, January 2, 2025.\n\n"
            "PRESENT: PRESENT: Brian Zacharias (Ward 1), Keri Lovato (Ward\n12), Joe Pitts (Mayor)\n\n")
    pm = parse_text([text], cfg)
    assert [(p.raw_name, p.ward, p.mayor) for p in pm.present] == [
        ("Brian Zacharias", 1, False), ("Keri Lovato", 12, False), ("Joe Pitts", None, True)]


def test_surnames_resolve_against_the_latest_full_roster_and_these_minutes(cfg):
    last, off = book_from(cfg, FULL_2025, "2025-02-06")
    pm = parse_text([CAPS_2025], cfg)
    got, checks = resolve_surnames(cfg, off, pm, last)
    names = {p.raw_name: got[id(p)] for p in pm.present + pm.absent}
    assert names["BROWN"] == ("Jimmy Brown", False) and names["MCLAUGHLIN"] == ("Deanna McLaughlin", False)
    assert names["PITTS"] == ("Joe Pitts", True)                                # the presiding mayor
    assert names["LOVATO"] == ("Keri Lovato", False)
    assert checks[0]["check"] == "surnames_resolve" and checks[0]["ok"]
    assert "by these minutes" in checks[0]["detail"] and "by the attendance of 2025-02-06" in checks[0]["detail"]


def test_a_misspelt_or_unknown_surname_is_not_resolved(cfg):
    last, off = book_from(cfg, FULL_2025, "2025-02-06")
    pm = parse_text([CAPS_2025.replace("STREETMAN, ZACHARIAS\n\n      ABSENT", "STREETMAN, ZAHARIAS, CLAUNCH\n\n"
                                                                                 "      ABSENT")], cfg)
    got, checks = resolve_surnames(cfg, off, pm, last)
    assert not checks[0]["ok"] and "not resolved: ZAHARIAS, CLAUNCH" in checks[0]["detail"]
    assert all(off.canonical(p.raw_name) == p.raw_name for p in pm.present if id(p) not in got)


def test_a_ward_that_disagrees_with_the_roster_is_not_resolved(cfg):
    last, off = book_from(cfg, FULL_2025, "2025-02-06")
    pm = parse_text([SURNAMES_WARDS_2025.replace("Brown (Ward 9)", "Brown (Ward 2)")], cfg)
    got, checks = resolve_surnames(cfg, off, pm, last)
    assert not checks[0]["ok"] and "not resolved: Brown" in checks[0]["detail"]
    assert {got[id(p)][0] for p in pm.present if id(p) in got} >= {"Brian Zacharias", "Carlos Peters"}


def test_two_full_names_for_one_surname_is_not_resolved(cfg):
    last, off = book_from(cfg, FULL_2025, "2025-02-06")
    pm = parse_text([CAPS_2025.replace("led by Councilman Keri Lovato", "led by Councilman Jim Brown")], cfg)
    got, checks = resolve_surnames(cfg, off, pm, last)
    assert "BROWN (2 full names)" in checks[0]["detail"] and not checks[0]["ok"]


# ------------------------------------------------------------------ build
def cc_rows():
    return [
        {"date": "2025-02-06", "title": "City Council Regular Session", "kind": "regular", "agenda_id": "cc-1",
         "agenda_url": None, "minutes_url": API.format(1), "source": "civicclerk", "video_url": None},
        {"date": "2025-08-07", "title": "Regular Session", "kind": "regular", "agenda_id": "cc-2",
         "agenda_url": None, "minutes_url": API.format(2), "source": "civicclerk", "video_url": None},
    ]


def built(cfg, texts, rows, entries):
    store = FakeStore(entries)
    by_url = dict(zip((r["minutes_url"] for r in rows), texts))

    def parse(path, c):
        sha = str(path).rsplit("/", 1)[-1][:-4]
        url = next(e["url"] for e in entries if e["sha256"] == sha)
        return parse_text([by_url[url]], c)
    facts, summary = build(cfg, rows, store, parse=parse, inspect=lambda p: (3, "text"))
    return facts, summary


def test_build_reads_the_capital_minutes_into_verified_roll_calls(cfg):
    rows = cc_rows()
    facts, summary = built(cfg, [FULL_2025, CAPS_2025], rows,
                           [entry(rows[0]["minutes_url"], "minutes", "2025-02-06", 1),
                            entry(rows[1]["minutes_url"], "minutes", "2025-08-07", 2)])
    jsonschema.validate({k: v for k, v in facts.items() if k != "_wards"}, SCHEMA)
    m = {x["date"]: x for x in facts["meetings"]}["2025-08-07"]
    assert m["verification"]["status"] == "verified"
    att = {a["raw_name"]: a["official_id"] for a in m["attendance"]}
    assert att["BROWN"] == "city-jimmy-brown" and att["PITTS"] == "city-joe-pitts" and att["PETERS"] == "city-carlos-peters"
    rcs = [r for r in facts["roll_calls"] if r["meeting_id"] == m["id"]]
    assert [r["verification"]["status"] for r in rcs] == ["verified"] * 3
    assert {v["official_id"] for v in rcs[0]["votes"]} >= {"city-jimmy-brown", "city-joe-pitts"}
    off = {o["id"]: o for o in facts["officials"]}
    assert off["city-joe-pitts"]["title"] == "Mayor"                     # never a council member for being listed
    assert "BROWN" not in {o["name"] for o in facts["officials"]}        # no official made from a bare surname


def test_minutes_listed_for_two_meetings_are_read_once_for_the_date_they_print(cfg):
    rows = cc_rows()
    rows[0] = {**rows[0], "date": "2025-08-07", "agenda_id": "cc-3", "minutes_url": API.format(3)}   # same file
    rows[1] = {**rows[1], "date": "2025-09-04", "agenda_id": "cc-4", "minutes_url": API.format(4),
               "agenda_url": API.format(5)}
    entries = [entry(API.format(3), "minutes", "2025-08-07", 7), entry(API.format(4), "minutes", "2025-09-04", 7),
               entry(API.format(5), "agenda", "2025-09-04", 8)]
    facts, summary = built(cfg, [CAPS_2025, CAPS_2025], rows, entries)
    jsonschema.validate({k: v for k, v in facts.items() if k != "_wards"}, SCHEMA)
    ms = {m["date"]: m for m in facts["meetings"]}
    assert ms["2025-08-07"]["minutes_status"] == "read"
    sep = ms["2025-09-04"]
    assert sep["minutes_status"] == "other_meeting" and sep["source_id"] == "src-" + "8".ljust(64, "0")[:12]
    assert {r["meeting_id"] for r in facts["roll_calls"]} == {ms["2025-08-07"]["id"]}
    assert len({r["id"] for r in facts["roll_calls"]}) == len(facts["roll_calls"])
    assert any("records the meeting of 2025-08-07" in p["problem"] for p in summary["problems"])


def test_minutes_for_two_meetings_without_an_agenda_leave_the_other_out(cfg):
    rows = cc_rows()
    rows[1] = {**rows[1], "date": "2025-09-04", "minutes_url": API.format(1)}       # the Feb minutes again
    facts, summary = built(cfg, [FULL_2025, FULL_2025], rows, [entry(API.format(1), "minutes", "2025-02-06", 1)])
    assert [m["date"] for m in facts["meetings"]] == ["2025-02-06"]
    assert summary["minutes_status"]["not_in_facts"] == 1
