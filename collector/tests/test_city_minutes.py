"""City Council minutes reader and facts build (M4 slice 1). Text in the layout `pdftotext -layout` gives for the
clarksvilletn.gov minutes (shapes taken from the 2016 and 2019 minutes). No network, no PDFs."""
import json
from pathlib import Path

import jsonschema
import pytest

from collector import agenda_center as ac
from collector.city_build import build, resolve
from collector.city_minutes import first_sentence, parse_people, parse_text

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schema" / "facts.schema.json").read_text())

PAGE1 = """                     CLARKSVILLE CITY COUNCIL
                         REGULAR SESSION
                         DECEMBER 5, 2019

CALL TO ORDER

     The regular session of the Clarksville City Council was called to order by Mayor Joe Pitts
     on Thursday, December 5, 2019, at 7:00 p.m. in City Council Chambers.

ATTENDANCE

     PRESENT:      Richard Garrett (Ward 1), Vondell Richmond (Ward 2), Ron Erb
                   (Ward 3), David Allen, Mayor Pro Tem (Ward 8), Mike Alexander (Ward 10; arrived
                   5:05 p.m.), Jeff Burkhart (Ward
                   12)

     ABSENT:       Wanda Smith (Ward 6)

PLANNING COMMISSION

    RESOLUTION 32-2019-20 Requesting the Regional Planning Commission Director
    and Staff to perform a study

           Councilman Erb made a motion to adopt this resolution. The motion was seconded by
           Councilman Allen. The following vote was recorded:

                   AYE: Allen, Burkhart, Erb, Garrett, Pitts,
                   Richmond

                   NOTE: Councilman Alexander was not present for this vote.

           The motion to adopt this resolution unanimously passed.
"""

PAGE2 = """CONSENT AGENDA

    1.    ORDINANCE 35-2019-20 (Second Reading) Authorizing donation of property

Councilman Burkhart made a motion to adopt the Consent Agenda. The motion was seconded by
Councilman Garrett. Councilman Burkhart noted his abstention on
ORDINANCE 45-2019-20 because he was involved in the sale of the property. The following vote was recorded:

       AYE: Alexander, Allen, Burkhart, Erb, Garrett, Pitts, Richmond
      The motion to adopt the Consent Agenda passed.

FINANCE COMMITTEE Councilman Jeff Burkhart, Chair

      ORDINANCE 47-2019-20 (First Reading) Authorizing transfer of South Second Street
      property interest

             Councilman Burkhart made a motion to adopt this ordinance on first reading. The motion was
             seconded by Councilman Erb. Councilman Allen made a motion to postpone. The motion was
             seconded by Councilman Garrett. The following vote was recorded:

                    AYE: Erb, Garrett

                    NAY: Alexander, Alllen, Burkhart, Pitts, Richmond

             The motion to postpone action indefinitely failed. The following vote on the main
             motion was recorded:

                    AYE: Alexander, Allen, Burkhart, Erb, Pitts, Richmond

                    NAY: Garrett

             The motion to delete $18,680 for U.S. Conference of Mayors
             dues passed.

             Councilman Allen made a motion to cease discussion. The motion was seconded by Councilman Erb.
             The following vote was recorded:

                    AYE: Alexander, Allen, Erb, Pitts

                    NAY: Burkhart, Garrett, Richmond

             The motion to cease discussion failed due to lack of 2/3 majority.
"""


@pytest.fixture(scope="module")
def cfg():
    return ac.load_config(ac.config_path("clarksville-tn"))


@pytest.fixture(scope="module")
def parsed(cfg):
    return parse_text([PAGE1, PAGE2], cfg)


def test_attendance_with_pro_tem_and_a_note_in_parentheses(parsed):
    assert [(p.raw_name, p.ward, p.pro_tem) for p in parsed.present] == [
        ("Richard Garrett", 1, False), ("Vondell Richmond", 2, False), ("Ron Erb", 3, False),
        ("David Allen", 8, True), ("Mike Alexander", 10, False), ("Jeff Burkhart", 12, False)]
    assert [(p.raw_name, p.ward) for p in parsed.absent] == [("Wanda Smith", 6)]
    assert parsed.presiding == "Joe Pitts" and parsed.attendance_page == 1


def test_parse_people_splits_only_outside_parentheses():
    ps = parse_people("A B (Ward 1; arrived late, after roll call), C D (Ward 2) and E F", 3)
    assert [(p.raw_name, p.ward, p.page) for p in ps] == [("A B", 1, 3), ("C D", 2, 3), ("E F", None, 3)]


def test_vote_blocks_items_and_outcomes(parsed):
    rcs = parsed.roll_calls
    assert len(rcs) == 5
    first = rcs[0]
    assert [(v.raw_name, v.value) for v in first.votes] == [(n, "yes") for n in
                                                          ("Allen", "Burkhart", "Erb", "Garrett", "Pitts", "Richmond")]
    assert first.absent == ["Alexander"]                              # from the NOTE line
    assert first.outcome == "passed" and first.page == 1
    assert first.item["number"] == "32-2019-20" and first.item["kind"] == "resolution"
    assert first.item["title"].startswith("Requesting the Regional Planning")
    assert first.motion["mover"] == "Erb" and first.motion["seconder"] == "Allen"


def test_prose_line_starting_with_an_item_number_is_not_an_item(parsed):
    consent = parsed.roll_calls[1]
    assert consent.item["number"] is None and consent.item["heading"] == "CONSENT AGENDA"
    assert consent.outcome_text == "The motion to adopt the Consent Agenda passed."


def test_motion_linked_only_when_exactly_one(parsed):
    postpone, main = parsed.roll_calls[2], parsed.roll_calls[3]
    assert postpone.motion is None                       # two motions before it: not guessed
    assert main.motion is None                           # no new motion between the two votes
    assert postpone.item["heading"].startswith("FINANCE COMMITTEE")
    assert [v.value for v in postpone.votes].count("no") == 5


def test_outcome_sentence_runs_past_abbreviations_and_lines(parsed):
    assert parsed.roll_calls[3].outcome_text == ("The motion to delete $18,680 for U.S. Conference of Mayors dues "
                                                 "passed.")
    assert first_sentence("Approved by No. 5 vote. Next") == "Approved by No. 5 vote."
    assert first_sentence("no stop here") is None


def test_scan_is_not_read(cfg):
    out = parse_text(["", ""], cfg, text_layer="none")
    assert out.roll_calls == [] and out.present == [] and out.problems == ["text layer none: not read"]


# ------------------------------------------------------------------ resolve
ROSTER = [("city-wanda-smith", "Wanda Smith"), ("city-joe-smith", "Joe Smith"), ("city-ron-erb", "Ron Erb"),
          ("city-david-allen", "David Allen")]


@pytest.mark.parametrize("token,expected", [
    ("Erb", "city-ron-erb"), ("Ron Erb", "city-ron-erb"), ("W. Smith", "city-wanda-smith"),
    ("Smith", None),               # two members named Smith: not guessed
    ("Alllen", None),              # a near spelling is never matched
    ("Wallace4", None),
])
def test_resolve(token, expected):
    assert resolve(token, ROSTER) == expected


# ------------------------------------------------------------------ build
class FakeStore:
    def __init__(self, entries):
        self.entries = {e["url"]: e for e in entries}

    def latest(self, url):
        return self.entries.get(url)

    def has_bytes(self, sha):
        return True

    def path_for(self, sha):
        return Path(f"/nonexistent/{sha}.pdf")


def entry(url, kind, date, n):
    return {"url": url, "sha256": f"{n:x}".ljust(64, "0"), "kind": kind, "meeting_date": date,
            "first_fetched_at": "2026-11-09T10:00:00+00:00"}


BASE = "https://www.clarksvilletn.gov/AgendaCenter/ViewFile/"


def rows_and_store(layer="text"):
    rows = [
        {"date": "2019-12-05", "title": "City Council Regular Session Agenda 12-5-19", "kind": "regular",
         "agenda_id": "12052019-325", "agenda_url": BASE + "Agenda/_12052019-325",
         "minutes_url": BASE + "Minutes/_12052019-325", "has_previous_versions": False},
        {"date": "2019-12-30", "title": "City Council Executive Session Agenda 12-30-19", "kind": "executive",
         "agenda_id": "12302019-340", "agenda_url": BASE + "Agenda/_12302019-340", "minutes_url": None,
         "has_previous_versions": False},
        {"date": "2019-12-31", "title": "City Council Special Session Agenda", "kind": "special",
         "agenda_id": "12312019-341", "agenda_url": BASE + "Agenda/_12312019-341", "minutes_url": None,
         "has_previous_versions": False},
    ]
    store = FakeStore([entry(rows[0]["agenda_url"], "agenda", "2019-12-05", 1),
                       entry(rows[0]["minutes_url"], "minutes", "2019-12-05", 2),
                       entry(rows[1]["agenda_url"], "agenda", "2019-12-30", 3)])
    return rows, store, (lambda path: (2, layer))


@pytest.fixture(scope="module")
def built(cfg):
    rows, store, inspect = rows_and_store()
    return build(cfg, rows, store, parse=lambda path, c: parse_text([PAGE1, PAGE2], c), inspect=inspect)


def test_build_matches_the_facts_schema(built):
    facts, summary = built
    facts = {k: v for k, v in facts.items() if k != "_wards"}
    jsonschema.validate(facts, SCHEMA)
    assert facts["coverage"] == {"body": "Clarksville City Council", "from": "2019-12-05", "to": "2019-12-30"}


def test_build_meetings_and_statuses(built):
    facts, summary = built
    ms = {m["id"]: m for m in facts["meetings"]}
    assert set(ms) == {"2019-12-05-regular", "2019-12-30-executive"}      # 12-31 has no fetched file: left out
    assert ms["2019-12-05-regular"]["minutes_status"] == "read"
    assert ms["2019-12-05-regular"]["source_id"] == "src-200000000000"            # the minutes, when read
    assert ms["2019-12-05-regular"]["agenda_source_id"] == "src-100000000000"
    assert ms["2019-12-30-executive"]["minutes_status"] == "not_posted"
    assert ms["2019-12-30-executive"]["attendance_status"] == "not_extracted"
    assert summary["minutes_status"] == {"read": 1, "not_posted": 1, "not_in_facts": 1}
    assert any("left out of facts" in p["problem"] for p in summary["problems"])


def test_build_attendance_officials_and_wards(built):
    facts, _ = built
    m = next(m for m in facts["meetings"] if m["id"] == "2019-12-05-regular")
    assert m["verification"]["status"] == "verified"
    assert {a["official_id"]: a["status"] for a in m["attendance"]}["city-wanda-smith"] == "absent"
    offs = {o["id"]: o for o in facts["officials"]}
    assert offs["city-joe-pitts"]["title"] == "Mayor"
    assert offs["city-david-allen"]["title"] == "City Council Member"
    assert all(o["id"].startswith("city-") for o in offs.values())
    wards = {w["official_id"]: w for w in facts["_wards"]}
    assert wards["city-david-allen"]["ward"] == 8 and wards["city-david-allen"]["pro_tem"] is True


def checks(rc):
    return {c["check"]: c for c in rc["verification"]["checks"]}


def test_build_roll_call_checks(built):
    facts, summary = built
    rcs = facts["roll_calls"]
    first, consent, postpone, main, cease = rcs
    assert first["verification"]["status"] == "verified"      # Alexander noted out of the room, Pitts presiding
    assert first["item_id"] == "resolution-32-2019-20" and first["motion_id"] is not None
    assert first["stated_tally"] is None
    assert consent["verification"]["status"] == "verified" and consent["item_id"].startswith("t-")
    c = checks(postpone)
    assert postpone["verification"]["status"] == "unverified"
    assert not c["names_resolve"]["ok"] and c["names_resolve"]["detail"] == "Alllen"
    assert not c["one_vote_per_present_member"]["ok"]            # Allen's vote is not counted from "Alllen"
    assert next(v for v in postpone["votes"] if v["raw_name"] == "Alllen")["official_id"] is None
    assert main["verification"]["status"] == "verified"
    assert checks(cease)["outcome_consistent"]["ok"]             # failed 4-3: the minutes state a 2/3 rule
    assert summary["unresolved_vote_names"] == {"Alllen": 1}
    assert summary["roll_calls"] == 5 and summary["roll_calls_verified"] == 4


def test_failed_with_more_yes_and_no_stated_rule_is_held(cfg):
    text = PAGE1.replace("unanimously passed.", "failed.")
    rows, store, inspect = rows_and_store()
    facts, _ = build(cfg, rows[:1], store, parse=lambda p, c: parse_text([text], c), inspect=inspect)
    rc = facts["roll_calls"][0]
    assert rc["outcome"] == "failed" and rc["verification"]["status"] == "unverified"
    assert checks(rc)["outcome_consistent"]["detail"] == "failed with 6 yes and 0 no"


def test_build_items_and_events(built):
    facts, _ = built
    items = {i["id"]: i for i in facts["items"]}
    assert items["resolution-32-2019-20"]["number"] == "RESOLUTION 32-2019-20"
    assert items["ordinance-47-2019-20"]["link_basis"] == "number"
    ev = [e for e in facts["item_events"] if e["item_id"] == "resolution-32-2019-20"]
    assert [e["type"] for e in ev] == ["motion", "roll_call"]


def test_scanned_minutes_are_marked_and_nothing_is_read(cfg):
    rows, store, _ = rows_and_store()
    called = []
    facts, summary = build(cfg, rows[:1], store, parse=lambda p, c: called.append(p),
                           inspect=lambda path: (3, "ocr"))
    m = facts["meetings"][0]
    assert called == [] and m["minutes_status"] == "scan_not_read"
    assert facts["roll_calls"] == [] and m["attendance"] == []
    assert summary["minutes_status"] == {"scan_not_read": 1}


# ------------------------------------------------------------------ attendance slips seen in the 2016-2019 minutes
@pytest.mark.parametrize("text,expected", [
    # the comma after a ward group left out (2019-03-07)
    ("Ron Erb (Ward 3), Tim Chandler (Ward 4) Valerie Guzman (Ward 5)",
     [("Ron Erb", 3), ("Tim Chandler", 4), ("Valerie Guzman", 5)]),
    # an opening parenthesis left out, and no space before the number (2018-10-04)
    ("Ron Erb Ward 3), Geno Grubbs (Ward7)", [("Ron Erb", 3), ("Geno Grubbs", 7)]),
    # zero-width characters are not part of a name (2017 minutes carry them)
    ("Bill​ ​Powers​ ​(Ward​ ​11)", [("Bill Powers", 11)]),
    # a suffix after a comma stays with its name
    ("Joe Smith, Jr. (Ward 2), Ann Lee (Ward 3)", [("Joe Smith, Jr.", None), ("Ann Lee", 3)]),
])
def test_attendance_slips(text, expected):
    from collector.city_minutes import lines_of
    clean = lines_of([text])[0].text
    assert [(p.raw_name, p.ward) for p in parse_people(clean, 1)] == expected


def test_mayor_pro_team_spelling_and_mayor_on_the_present_line():
    ps = parse_people("Valerie Guzman, Mayor Pro Team (Ward 5), Mayor Kim McMillan", 1)
    assert [(p.raw_name, p.pro_tem, p.mayor) for p in ps] == [("Valerie Guzman", True, False),
                                                              ("Kim McMillan", False, True)]


def test_pro_tem_presiding_is_not_made_mayor(cfg):
    text = PAGE1.replace("called to order by Mayor Joe Pitts", "called to order by Mayor Pro Tem David Allen")
    text = text.replace("Garrett, Pitts,", "Garrett,")
    rows, store, inspect = rows_and_store()
    facts, _ = build(cfg, rows[:1], store, parse=lambda p, c: parse_text([text], c), inspect=inspect)
    offs = {o["id"]: o["title"] for o in facts["officials"]}
    assert offs["city-david-allen"] == "City Council Member" and "city-joe-pitts" not in offs
    assert facts["roll_calls"][0]["verification"]["status"] == "verified"


def test_a_run_on_of_two_names_is_not_an_official(cfg):
    text = PAGE1.replace("Ron Erb\n                   (Ward 3), ", "Ron Erb Valerie Guzman, ")
    assert text != PAGE1
    rows, store, inspect = rows_and_store()
    facts, _ = build(cfg, rows[:1], store, parse=lambda p, c: parse_text([text], c), inspect=inspect)
    m = facts["meetings"][0]
    assert m["verification"]["status"] == "unverified"
    assert checks(m)["names_well_formed"]["detail"] == "Ron Erb Valerie Guzman"
    assert not any("valerie" in o["id"] for o in facts["officials"])
    assert all(r["verification"]["status"] == "unverified" for r in facts["roll_calls"])


# ------------------------------------------------------------------ 2020-2023 formats
HYBRID = """ATTENDANCE

    IN PERSON: Richard Garrett ( Ward 1), Ron Erb (Ward 3), Gary Norris ((Ward 11), Jeff
    Burkhart (Ward 12), Trisha Butler - arrived late (Ward 4), Vacant (Ward 5)

    VIA GOOGLE MEETS: Tim Chandler (Ward 6), Wanda
    Smith (Ward 7)
APPROVAL OF ELECTRONIC MEETING

    The regular session was called to order by Mayor Joe Pitts.

    ORDINANCE 12-2022-23 (First Reading) Amending the budget

    The following vote was recorded:

           AYE: Burkhart, Erb, Garrett, Norris, Pitts

           Nay:   Smith

           NO RESPONSE: Chandler

    The motion to adopt ORDINANCE 12-2022-23 (First Reading) passed.
"""


def test_hybrid_attendance_lines_and_mixed_case_labels(cfg):
    p = parse_text([HYBRID], cfg)
    assert [(x.raw_name, x.ward) for x in p.present] == [
        ("Richard Garrett", 1), ("Ron Erb", 3), ("Gary Norris", 11), ("Jeff Burkhart", 12), ("Trisha Butler", 4),
        ("Tim Chandler", 6), ("Wanda Smith", 7)]
    assert [x.part_time for x in p.present] == [False] * 4 + [True, False, False]
    rc = p.roll_calls[0]
    assert [(v.raw_name, v.raw_value, v.value) for v in rc.votes][-2:] == [("Smith", "NAY", "no"),
                                                                          ("Chandler", "NO RESPONSE", "other")]
    assert rc.item["number"] == "12-2022-23" and rc.outcome == "passed"


ZONING = """PUBLIC HEARING

    ORDINANCE 14-2017-18 (First Reading) Amending the Zoning Ordinance and Map

             No one expressed support for or opposition to this request.

ZONING

    The recommendation of the Regional Planning Staff was for disapproval of
    ORDINANCE 14-2017-18. Councilman Erb made a motion to adopt this ordinance on first
    reading. The motion was seconded by Councilman Allen. The following vote was recorded:

             AYE: Allen, Erb

             The motion to adopt this ordinance on first reading passed.

    The recommendations were for approval of ORDINANCE 15-2017-18 and ORDINANCE 16-2017-18.
    The following vote was recorded:

             AYE: Allen, Erb

             The motion to adopt these ordinances on first reading passed.
"""


def test_vote_under_a_section_links_the_one_item_its_paragraph_names(cfg):
    a, b = parse_text([ZONING], cfg).roll_calls
    assert a.item["number"] == "14-2017-18" and a.item["title"] == "(First Reading) Amending the Zoning Ordinance and Map"
    assert a.item["heading"] == "ZONING"
    assert b.item["number"] is None and b.item["heading"] == "ZONING"     # two named: not guessed


def test_late_arrival_may_miss_a_vote(cfg):
    rows, store, inspect = rows_and_store()
    facts, _ = build(cfg, rows[:1], store, parse=lambda p, c: parse_text([HYBRID], c), inspect=inspect)
    assert facts["meetings"][0]["verification"]["status"] == "verified"
    rc = facts["roll_calls"][0]
    assert rc["verification"]["status"] == "verified"           # Butler arrived late and is not in the vote


# ------------------------------------------------------------------ review fixes (code-review-city-m4-slice1.md)
COUNCILPERSON = """ATTENDANCE

    PRESENT: Richard Garrett (Ward 1), Trisha Butler (Ward 12), Jason Knight (Ward 5), David Allen (Ward 8)

    The regular session was called to order by Mayor Joe Pitts.

    ORDINANCE 63-2020-21 (Second Reading) Amending the Official Code relative to
    short term rentals

          Councilperson Butler made a motion to adopt this ordinance on second reading. The motion was
          seconded by Councilperson Allen. The following vote was recorded:

                 AYE: Allen, Butler, Garrett, Pitts

                 NOTE: Councilperson Knight was not present for this vote.

          The motion to adopt this ordinance on second reading passed.
"""


def test_councilperson_title_reads_motions_and_note_absences(cfg):
    # city-motions/title-regex: "Councilperson" (printed from 2021) was not a title, so no motion was read
    rc = parse_text([COUNCILPERSON], cfg).roll_calls[0]
    assert rc.motion["mover"] == "Butler" and rc.motion["seconder"] == "Allen"
    assert rc.absent == ["Knight"]
    rows, store, inspect = rows_and_store()
    facts, _ = build(cfg, rows[:1], store, parse=lambda p, c: parse_text([COUNCILPERSON], c), inspect=inspect)
    assert len(facts["motions"]) == 1 and facts["motions"][0]["verification"]["status"] == "verified"
    assert facts["roll_calls"][0]["verification"]["status"] == "verified"       # Knight out of the room


OVERRUN = """ATTENDANCE

    PRESENT: Valerie Guzman (Ward 5), Ron Erb (Ward 3), David Allen (Ward 8)

    The regular session was called to order by Mayor Kim McMillan.

GAS & WATER COMMITTEE

    ORDINANCE 53-2018-19 (First Reading) Authorizing extension of utility services to
    1621 Dunlop Lane; request of Ben Stanley
    There was no recommendation from the Gas & Water Committee due to lack of a quorum.
    Councillady Guzman made a motion to adopt this ordinance on first reading. The motion
    was seconded by Councilman Erb. The following vote was recorded:
           AYE: Allen, Erb, Guzman, McMillan
    The motion to adopt this ordinance on first reading passed.

    RESOLUTION 81-2020-21 Authorizing reapplication for zone change for Reda Home Builders,
    Inc. on property located at the intersection of Twin Rivers Road and Nolen Road
    Councilperson Allen made a motion to adopt this resolution. The motion was seconded by
    Councilperson Erb.

          AYE: Allen, Erb, Guzman, McMillan

    The motion to adopt this resolution passed.

BOARD APPOINTMENTS

    RESOLUTION 35-2018-19 was removed from the Consent Agenda. Councilman
    Allen made a motion to adopt this resolution. The motion was seconded by
    Councilman Erb. The following vote was recorded:

          AYE: Allen, Erb, Guzman, McMillan

    The motion to adopt this resolution passed.

DELIBERATION PHASE: Councilman Erb made a motion to overturn the decision
of the Regional Historic Zoning Commission. The motion was seconded by Councilman Allen.
The following vote was recorded:

          AYE: Allen, Erb, Guzman, McMillan

The motion to overturn the decision passed.
"""


def test_item_title_stops_where_the_body_starts(cfg):
    # city-items/title-overrun: the title absorbed the motion and vote text, and the AYE line inside it was lost
    rcs = parse_text([OVERRUN], cfg).roll_calls
    assert len(rcs) == 4                                       # the AYE line right under the motion is read
    a, b, c, d = rcs
    assert a.item["title"] == ("(First Reading) Authorizing extension of utility services to 1621 Dunlop Lane; "
                               "request of Ben Stanley")
    assert [v.raw_name for v in a.votes] == ["Allen", "Erb", "Guzman", "McMillan"]
    assert a.motion["mover"] == "Guzman" and a.motion["seconder"] == "Erb"
    assert b.item["title"].endswith("intersection of Twin Rivers Road and Nolen Road")
    assert b.motion["mover"] == "Allen"


def test_a_sentence_after_an_item_number_is_not_its_title(cfg):
    c = parse_text([OVERRUN], cfg).roll_calls[2]
    assert c.item["number"] == "35-2018-19" and c.item["title"] is None
    assert c.motion["mover"] == "Allen" and c.motion["seconder"] == "Erb"     # the motion on that line is read


def test_a_heading_line_does_not_take_the_sentence_after_it(cfg):
    d = parse_text([OVERRUN], cfg).roll_calls[3]
    assert d.item["number"] is None and d.item["heading"] == "DELIBERATION PHASE"
    assert d.motion["mover"] == "Erb"


def test_no_item_title_holds_motion_or_vote_text(cfg):
    rows, store, inspect = rows_and_store()
    facts, _ = build(cfg, rows[:1], store, parse=lambda p, c: parse_text([OVERRUN], c), inspect=inspect)
    import re
    assert not [i["title"] for i in facts["items"] if re.search(r"made a motion|seconded|AYE:", i["title"])]
