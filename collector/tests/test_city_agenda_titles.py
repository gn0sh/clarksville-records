"""note-titles: an item the minutes print with only its number takes the caption its meeting's own agenda prints for
exactly that number (collector/city_minutes.agenda_captions, collector/city_build.agenda_titles). Fixtures: the
text layer (pdftotext -layout) of six stored CivicClerk agendas and three Agenda Center ones (2017, 2021, 2023; their
packets trimmed), collector/tests/fixtures/city/agenda_<date>.txt (sources: agendas.SOURCE.txt)."""
import copy
import dataclasses
import json
from pathlib import Path

import jsonschema
import pytest

from collector import agenda_center as ac
from collector.city_build import build
from collector.city_minutes import agenda_captions, caption_text, parse_text
from collector.shrink_guard import keep_documents, shrink_guard, vote_content

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures" / "city"
SCHEMA = json.loads((ROOT / "schema" / "facts.schema.json").read_text())
DATES = ("2017-06-29", "2021-11-04", "2023-06-01", "2024-01-04", "2025-07-01", "2025-09-04", "2026-01-08",
         "2026-05-07", "2026-07-02")


@pytest.fixture(scope="module")
def cfg():
    return ac.load_config(ac.config_path("clarksville-tn"))


def agenda(date: str) -> list[str]:
    return (FIX / f"agenda_{date}.txt").read_text(encoding="utf-8").split("\f")


@pytest.fixture(scope="module")
def caps(cfg):
    return {d: agenda_captions(agenda(d), cfg) for d in DATES}


# ------------------------------------------------------------------ reading the agenda
def test_every_numbered_entry_of_each_fixture_agenda_gives_one_caption(caps):
    assert {d: len(c) for d, c in caps.items()} == {"2017-06-29": 3, "2021-11-04": 33, "2023-06-01": 41,
                                                     "2024-01-04": 27, "2025-07-01": 23, "2025-09-04": 27,
                                                     "2026-01-08": 16, "2026-05-07": 18, "2026-07-02": 14}
    assert all(len(v) == 1 for c in caps.values() for v in c.values())       # no number printed twice
    # one entry ends with a titled name that may be its own words: no caption, never a fragment
    assert [(d, k) for d, c in caps.items() for k, v in c.items() if v[0][0] is None] == [
        ("2021-11-04", ("ordinance", "58-2021-22")), ("2021-11-04", ("resolution", "30-2021-22")),
        ("2023-06-01", ("resolution", "67-2022-23"))]


def test_caption_is_verbatim_with_its_labels_and_without_the_planning_commission_note(caps):
    assert caps["2026-07-02"][("ordinance", "95-2025-26")] == [(
        "(FIRST READING) [ZONING CASE Z-22-2025] An Ordinance amending the zoning code and map of the City of "
        "Clarksville, application of Youth Realty, LLC for a zone change on a parcel of land located on the eastern "
        "frontage of Professional Park Dr, 1,850 +/- feet south of the intersection of Dunlop Ln & Professional Park "
        "Dr from O-1 Office District to C-2 General Commercial District.", 1)]


def test_kind_and_number_both_key_the_caption(caps):
    c = caps["2026-07-02"]
    assert c[("ordinance", "71-2025-26")][0][0].startswith("(SECOND READING) [ZONING CASE Z-11-2025] An Ordinance")
    assert c[("resolution", "71-2025-26")][0][0] == (
        "A Resolution approving a Certificate of Compliance for sale of wine in a food store at Sudden Service #25, "
        "located at 601 Hornbuckle Rd, Clarksville TN.")


def test_a_number_inside_a_caption_is_no_entry_and_a_sponsor_and_committee_note_are_cut(caps):
    c = caps["2026-07-02"]
    assert ("ordinance", "88-2025-26") not in c
    assert c[("ordinance", "93-2025-26")][0][0] == (
        "(FIRST READING) An Ordinance amending the Operating Budgets for the Fiscal Year 2026-27 for the Clarksville "
        "Parking Commission, a Proprietary Fund (ORDINANCE 88-2025-26)")         # "[Councilman Ambar Marquis] ..." cut
    assert c[("resolution", "69-2025-26")][0][0].endswith("by the Mayor on March 20, 2026.")   # "Councilman Wanda
    assert c[("ordinance", "94-2025-26")][0][0].endswith("greenway development along Matlock Rd.")   # Smith" cut


@pytest.mark.parametrize("date,key,end", [
    # a committee note wrapped over two lines, and two committees in one note
    ("2024-01-04", ("ordinance", "52-2023-24"), "for the Tiny Town Road sidewalk project."),
    ("2024-01-04", ("ordinance", "39-2023-24"), "relative to gas rates, charges, and/or fees"),
    ("2024-01-04", ("ordinance", "54-2023-24"), "for the purpose of road realignment and a park complex."),
    # "Committe" as printed; two notes and a bracketed sponsor; a sponsor then a note of an unheaded committee
    ("2025-09-04", ("ordinance", "18-2025-26"), "in partnership with Appalachian Service Project."),
    ("2025-09-04", ("resolution", "08-2025-26"), "return the results of the study to theCity Council."),
    ("2025-09-04", ("resolution", "18-2025-26"), "to be designated as Kenny York Memorial Way."),
    # a board's note in parentheses after a bare sponsor
    ("2026-01-08", ("resolution", "38-2025-26"), "General Manager of the Clarksville Gas & Water Department."),
    ("2026-01-08", ("resolution", "39-2025-26"), "the Pennyrile Regional Energy Agency (PREA)."),
    ("2026-05-07", ("ordinance", "67-2025-26"), "design and construction of various projects."),
    # a free-text planning commission note
    ("2025-07-01", ("ordinance", "112-2024-25"), "to include Fort Campbell Boulevard and Tiny Town Road Corridors."),
    ("2025-07-01", ("ordinance", "98-2024-25"), "for the purpose of a Sewer Pump Station"),
])
def test_trailing_notes_are_cut(caps, date, key, end):
    text = caps[date][key][0][0]
    assert text.endswith(end)
    assert "Committe" not in text[-40:] and "RPC" not in text and "Mayor Pitts" not in text


@pytest.mark.parametrize("date,key,end,page", [
    # cut by a page break: the next page goes on in lower case, or right of that page's entry labels
    ("2025-09-04", ("resolution", "13-2025-26"), "(Clarksville Bottle Shop, 549 Neptune Dr) and repealing the "
                                                 "certificate of compliance for Clarksville Bottle Shop (924 "
                                                 "Providence Blvd).", 3),
    ("2026-05-07", ("ordinance", "58-2025-26"), "to R-3 Three Family Residential District.", 1),
])
def test_a_caption_runs_on_over_a_page_break(caps, date, key, end, page):
    text, p = caps[date][key][0]
    assert text.endswith(end) and p == page


def test_a_page_break_before_the_next_entry_ends_the_caption(caps):
    text = caps["2026-07-02"][("resolution", "73-2025-26")][0][0]
    assert text.endswith("Certificate of Compliance for Planet Liquors (2400 Madison St).")


@pytest.mark.parametrize("date,key,caption", [
    # Agenda Center 2017: sponsor and committee in one parenthesis
    ("2017-06-29", ("ordinance", "77-2016-17"), "(First Reading) Approving and adopting the Fox Lawson & Associates "
                                                "updated pay plan for Fiscal Year 2017-18"),
    ("2017-06-29", ("resolution", "38-2016-17"), "Approving a public records policy"),
    # 2021: flush-left lines, the packet page after each entry, a bare sponsor (also before a note in parentheses)
    # "... Neighborhood and Community Services Mayor Pro Tem Smith Page 241": whose title, not known
    ("2021-11-04", ("ordinance", "58-2021-22"), None),
    ("2021-11-04", ("ordinance", "47-2021-22"), "(First Reading) Amending the Zoning Ordinance and Map of the City of "
                                                "Clarksville, application of Sandra Sims, Brian Bryant - Agent for Zone "
                                                "Change on property located at the intersection of Hawkins Rd. & "
                                                "Edmondson Ferry Rd. from R-1 Single Family Residential District to R-4 "
                                                "Multiple Family Residential District"),
    ("2021-11-04", ("resolution", "31-2021-22"), "Authorizing reapplication for Zone Change for Ben Kimbrough – "
                                                 "Ringgold Mill Properties, LLC , Bert Singletary – Agent, on the "
                                                 "property located at the intersection of Ft. Campbell Boulevard and "
                                                 "Millswood Drive from C-5 and R-2 to R-4"),
    # 2023: "1." entries under "8) FINANCE COMMITTEE ..." headings; a caption cut by a page break goes on
    ("2023-06-01", ("ordinance", "129-2022-23"), "(First Reading) Amending the Zoning Ordinance and Map of the City of "
                                                 "Clarksville, application of Hunter Winn, for Zone Change on property "
                                                 "fronting on the south frontage of Memorial Dr from R-3 Three Family "
                                                 "Residential District to C-2 General Commercial District"),
    ("2023-06-01", ("resolution", "60-2022-23"), "A Resolution authorizing Mayor Pitts to file with the U.S. Department "
                                                 "of Housing and Urban Development, the City of Clarksville’s FY "
                                                 "2023-2024 Annual Action Plan, and the FY 2023-2024 application for "
                                                 "community development block grant funds and home investments "
                                                 "partnership program funds"),
    # "... vision sessions Councilperson Karen Reynolds": a sponsor or the caption's own words, not known
    ("2023-06-01", ("resolution", "67-2022-23"), None),
])
def test_agenda_center_layouts(caps, date, key, caption):
    assert [c for c, _ in caps[date][key]] == [caption]


def test_the_packet_after_the_adjournment_entry_is_never_read(cfg, caps):
    """2021-11-04: the packet reprints earlier minutes, whose numbered entries print other words ("803 Howard St.")
    and motion prose (ORDINANCE 45-2021-22, p. 7 of the fixture): only the agenda proper counts."""
    c = caps["2021-11-04"]
    assert c[("ordinance", "32-2021-22")] == [("(Second Reading) Authorizing the sale of property located at 803 Howard "
                                               "Street to Marlon Placid", 3)]
    assert ("ordinance", "45-2021-22") not in c
    no_end = [p.replace("16) ADJOURNMENT", "16) ADJOURNED") for p in agenda("2021-11-04")]
    assert agenda_captions(no_end, cfg) == {}                     # no end line: an unknown layout, no caption


def test_a_committee_note_of_an_unknown_name_leaves_no_caption(cfg):
    """RESOLUTION 18-2025-26 ends "... Memorial Way. Mayor Pitts Designations Committee: Approval". Without
    "Designations" configured (and no such heading), where the note starts is not known: no caption, never a guess."""
    names = tuple(n for n in cfg.agenda_captions.committee_names if n != "Designations")
    c2 = dataclasses.replace(cfg, agenda_captions=dataclasses.replace(cfg.agenda_captions, committee_names=names))
    caps = agenda_captions(agenda("2025-09-04"), c2)
    assert caps[("resolution", "18-2025-26")] == [(None, 5)] and caps[("resolution", "17-2025-26")][0][0]


@pytest.mark.parametrize("raw,caption", [
    # cut: after a sentence's end, or right before a structural note (cut, or in parentheses after the name)
    ("A Resolution approving Lincoln Homes. Councilperson Karen Reynolds", "A Resolution approving Lincoln Homes."),
    ("An Ordinance on housing Councilperson Holleman Page 243", "An Ordinance on housing"),
    ("A Resolution on zoning to R-4 Councilperson Marquis (Requires 3/4 majority)", "A Resolution on zoning to R-4"),
    # the caption's own words: kept whole
    ("A Resolution electing a Mayor Pro Tem", "A Resolution electing a Mayor Pro Tem"),
    ("A Resolution recognizing outgoing Councilman Joe Smith", "A Resolution recognizing outgoing Councilman Joe Smith"),
    ("A resolution honoring Councilperson Karen Reynolds", "A resolution honoring Councilperson Karen Reynolds"),
    ("A Resolution honoring Mayor Joe Pitts Page 12", "A Resolution honoring Mayor Joe Pitts"),
    # not known: no caption, never a fragment ("... supporting Montgomery County")
    ("A Resolution supporting Montgomery County Mayor Wes Golden", None),
    ("A Resolution in support of Montgomery County Mayor Wes Golden Page 9", None),
    ("An Ordinance renaming the Department of Community Services Mayor Pro Tem Smith Page 241", None),
    ("A Resolution on vision sessions Councilperson Karen Reynolds", None),
])
def test_a_bare_titled_name_is_never_cut_to_a_fragment(cfg, raw, caption):
    ac_ = cfg.agenda_captions
    assert (caption_text(raw, ac_, set(ac_.committee_names)) or None) == caption


def test_the_end_line_must_come_before_the_packet(cfg):
    """captions/packet-read: an agenda that prints no adjournment entry of its own is not read, even when a packet
    page after it (a reprinted ordinance or minutes) prints one; nor past max_pages."""
    agenda_page = "1) CALL TO ORDER\n\n   1. ORDINANCE 5-2021-22 (First Reading) Amending a thing Page 7\n"
    packet = "                    ORDINANCE 5-2021-22\n\nAN ORDINANCE AMENDING A THING\n\n16) ADJOURNMENT\n"
    assert agenda_captions([agenda_page, packet], cfg) == {}
    late = [agenda_page] + ["   (continued)\n"] * cfg.agenda_captions.max_pages + ["16) ADJOURNMENT\n"]
    assert agenda_captions(late, cfg) == {}
    assert agenda_captions([agenda_page, "16) ADJOURNMENT\n"], cfg) == {
        ("ordinance", "5-2021-22"): [("(First Reading) Amending a thing", 1)]}


def test_committee_headings_after_the_end_line_are_not_read(cfg):
    """A committee named only by a heading in the packet is unknown: its note leaves the entry with no caption."""
    agenda_page = ("1) CALL TO ORDER\n\n   1. ORDINANCE 6-2021-22 (First Reading) Buying a boat. Harbor Committee: "
                   "Approval\n\n16) ADJOURNMENT\n")
    packet = "9) HARBOR COMMITTEE Councilperson A Person\n"
    assert agenda_captions([agenda_page, packet], cfg) == {("ordinance", "6-2021-22"): [(None, 1)]}
    assert agenda_captions([agenda_page.replace("16) ADJOURNMENT", "9) HARBOR COMMITTEE Chair\n\n16) ADJOURNMENT")],
                           cfg) == {("ordinance", "6-2021-22"): [("(First Reading) Buying a boat.", 1)]}


FLUSH = ["   1.   ORDINANCE 10-2021-22 (First Reading) Amending the Zoning Ordinance and\n"
         "   Map of the City of Clarksville, application of Some Owner for Zone Change\n\n\n            1\n",
         "   On Property Located at the intersection of A Rd. and B Rd. Page 9\n\n"
         "   2.   ORDINANCE 11-2021-22 (First Reading) Authorizing a thing Page 10\n\n16) ADJOURNMENT\n"]


def test_a_flush_left_caption_cut_by_a_page_break_is_no_caption(cfg):
    """A flush-left layout (2021) prints a caption's lines at its label's column, so a capitalised first line on the
    next page may or may not go on with it: no caption rather than half of one."""
    caps = agenda_captions(FLUSH, cfg)
    assert caps[("ordinance", "10-2021-22")] == [(None, 1)]
    assert caps[("ordinance", "11-2021-22")] == [("(First Reading) Authorizing a thing", 2)]


def test_a_hanging_caption_cut_by_a_page_break_ends_at_a_heading_of_the_label_column(cfg):
    pages = ["     A.   ORDINANCE 10-2025-26 (FIRST READING) An Ordinance amending the\n"
             "          Official Code\n\n\n            1\n",
             "     Planning Commission - No Public Hearing Required\n\n"
             "     A.   ORDINANCE 11-2025-26 (FIRST READING) An Ordinance\n\n14. Adjournment\n"]
    caps = agenda_captions(pages, cfg)
    assert caps[("ordinance", "10-2025-26")] == [("(FIRST READING) An Ordinance amending the Official Code", 1)]


def test_labels_alone_are_no_caption(cfg):
    assert caption_text("(FIRST READING) [ZONING CASE Z-1-2026]  RPC: Approval/Approval", cfg.agenda_captions,
                        set(cfg.agenda_captions.committee_names)) == ""


def test_one_entry_for_two_items_gives_neither_a_caption(cfg):
    page = ("     A.   RESOLUTION 10-2025-26 and RESOLUTION 11-2025-26 Resolutions approving two things\n\n"
            "     B.   RESOLUTION 12-2025-26 RESOLUTION 13-2025-26 A Resolution\n\n14. Adjournment\n")
    assert agenda_captions([page], cfg) == {("resolution", "10-2025-26"): [(None, 1)],
                                            ("resolution", "12-2025-26"): [(None, 1)]}


def test_no_captions_without_the_config_key(cfg):
    assert agenda_captions(agenda("2026-07-02"), dataclasses.replace(cfg, agenda_captions=None)) == {}


def test_agenda_captions_config_is_checked():
    raw = ac.yaml.safe_load(ac.config_path("clarksville-tn").read_text(encoding="utf-8"))
    for bad in ({k: v for k, v in raw["agenda_captions"].items() if k != "notes"},
                {**raw["agenda_captions"], "committee_heading": r"^\d+\.\s+(.+) Committee"},
                {**raw["agenda_captions"], "entry": "("},
                {k: v for k, v in raw["agenda_captions"].items() if k != "end"},
                {**raw["agenda_captions"], "sponsor_kept_after": [True]},
                {**raw["agenda_captions"], "max_pages": 0}):
        with pytest.raises(ac.AgendaCenterConfigError):
            ac.parse_config({**raw, "agenda_captions": bad})


# ------------------------------------------------------------------ the build
MINUTES_JUL = """                     CLARKSVILLE CITY COUNCIL
                         REGULAR SESSION
                           JULY 2, 2026

CALL TO ORDER

     The regular session of the Clarksville City Council was called to order by Mayor Joe Pitts
     on Thursday, July 2, 2026, at 6:00 p.m. in City Council Chambers.

ATTENDANCE

     PRESENT:      Richard Garrett (Ward 1), Vondell Richmond (Ward 2), Ron Erb (Ward 3)

PLANNING COMMISSION

    ORDINANCE 95-2025-26

           Councilman Erb made a motion to adopt this ordinance on first reading. The motion was seconded by
           Councilman Garrett. The following vote was recorded:

                   AYE: Erb, Garrett, Pitts, Richmond

           The motion to adopt this ordinance on first reading passed.

NEW BUSINESS

    RESOLUTION 69-2025-26

           Councilman Erb made a motion to adopt this resolution. The motion was seconded by
           Councilman Garrett. The following vote was recorded:

                   AYE: Erb, Garrett, Pitts

                   NAY: Richmond

           The motion to adopt this resolution passed.
"""

MINUTES_AUG = MINUTES_JUL.replace("JULY 2, 2026", "AUGUST 6, 2026").replace("July 2, 2026", "August 6, 2026") \
    .replace("    ORDINANCE 95-2025-26\n", "    ORDINANCE 96-2025-26\n") \
    .replace("    RESOLUTION 69-2025-26\n", "    RESOLUTION 69-2025-26 Requiring council approval before a lease "
                                            "ends\n") \
    .replace("NEW BUSINESS", "OLD BUSINESS\n\n    ORDINANCE 9-2025-26\n\n           Councilman Erb made a motion to "
                             "adopt this ordinance. The motion was seconded by\n           Councilman Garrett. The "
                             "following vote was recorded:\n\n                   AYE: Erb, Garrett, Pitts, Richmond\n"
                             "\n           The motion to adopt this ordinance passed.\n\nNEW BUSINESS")

AGENDA_AUG = """     A.   ORDINANCE 96-2025-26 (SECOND READING) An Ordinance approving one thing

     B.   ORDINANCE 96-2025-26 (SECOND READING) An Ordinance approving another thing

     C.   ORDINANCE 09-2025-26 (SECOND READING) An Ordinance with a leading zero

     D.   RESOLUTION 69-2025-26 A Resolution as the agenda prints it

14. Adjournment
"""


class FakeStore:
    def __init__(self, entries):
        self.entries = {e["url"]: e for e in entries}

    def latest(self, url):
        return self.entries.get(url)

    def has_bytes(self, sha):
        return True

    def path_for(self, sha):
        return Path(f"/nonexistent/{sha}.pdf")


CC = "https://clarksvilletn.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId={},plainText=false)"


def sha(n: int) -> str:
    return f"{n:x}".ljust(64, "0")


def setup():
    rows = [{"date": d, "title": "City Council Regular Session", "kind": "regular", "agenda_id": f"{d}-{n}",
             "agenda_url": CC.format(n), "minutes_url": CC.format(n + 1), "has_previous_versions": False}
            for d, n in (("2026-07-02", 3162), ("2026-08-06", 3300))]
    entries = [{"url": r[f"{k}_url"], "sha256": sha(n), "kind": k, "meeting_date": r["date"],
                "first_fetched_at": "2026-11-09T10:00:00+00:00"}
               for n, (r, k) in enumerate([(rows[0], "agenda"), (rows[0], "minutes"),
                                           (rows[1], "agenda"), (rows[1], "minutes")], start=1)]
    text = {sha(1): agenda("2026-07-02"), sha(2): [MINUTES_JUL], sha(3): [AGENDA_AUG], sha(4): [MINUTES_AUG]}
    of = lambda path: text[Path(path).stem]                                          # noqa: E731
    return rows, FakeStore(entries), of


def run(cfg):
    rows, store, of = setup()
    return build(cfg, rows, store, parse=lambda p, c: parse_text(of(p), c), inspect=lambda p: (3, "text"),
                 pages=of)


@pytest.fixture(scope="module")
def built(cfg):
    return run(cfg)


@pytest.fixture(scope="module")
def without(cfg):
    return run(dataclasses.replace(cfg, agenda_captions=None))


def items_of(facts):
    return {i["id"]: i for i in facts["items"]}


def test_an_untitled_item_takes_its_meetings_agenda_caption_with_its_source(built):
    facts, _ = built
    it = items_of(facts)["ordinance-95-2025-26"]
    assert it["title"].startswith("(FIRST READING) [ZONING CASE Z-22-2025] An Ordinance amending the zoning code")
    assert it["title_source"] == {"kind": "agenda", "source_id": f"src-{sha(1)[:12]}", "page": 1,
                                  "meeting_id": "2026-07-02-regular"}
    m = next(m for m in facts["meetings"] if m["id"] == "2026-07-02-regular")
    assert m["agenda_source_id"] == it["title_source"]["source_id"]


def test_a_title_any_minutes_print_is_never_replaced(built):
    """RESOLUTION 69-2025-26: untitled in the July minutes, whose agenda prints its caption; the August minutes print
    a title. The minutes' words win, with no title_source."""
    it = items_of(built[0])["resolution-69-2025-26"]
    assert it["title"] == "Requiring council approval before a lease ends" and "title_source" not in it


def test_two_different_captions_for_one_number_give_no_title(built):
    facts, summary = built
    it = items_of(facts)["ordinance-96-2025-26"]
    assert it["title"] == "" and "title_source" not in it
    assert summary["agenda_titles"]["ambiguous"] == [{"item_id": "ordinance-96-2025-26",
                                                      "meeting_id": "2026-08-06-regular",
                                                      "source_id": f"src-{sha(3)[:12]}", "pages": [1],
                                                      "reason": "its entries print different captions"}]


def test_an_entry_with_no_sure_caption_makes_the_number_ambiguous(cfg):
    """captions/ambiguous-miss: one entry of the number gives no caption (None), another one does: no title, and
    the report says why."""
    rows, store, of = setup()
    unsure = AGENDA_AUG.replace("An Ordinance approving another thing", "An Ordinance approving one thing") \
        .replace("     C.   ORDINANCE 09-2025-26", "     C.   ORDINANCE 96-2025-26 and RESOLUTION 1-2025-26 Two\n\n"
                                                    "     E.   ORDINANCE 09-2025-26")
    text = {sha(1): agenda("2026-07-02"), sha(2): [MINUTES_JUL], sha(3): [unsure], sha(4): [MINUTES_AUG]}
    of2 = lambda path: text[Path(path).stem]                                         # noqa: E731
    facts, summary = build(cfg, rows, store, parse=lambda p, c: parse_text(of2(p), c), inspect=lambda p: (3, "text"),
                           pages=of2)
    assert items_of(facts)["ordinance-96-2025-26"]["title"] == ""
    assert [a["reason"] for a in summary["agenda_titles"]["ambiguous"]] == ["an entry for it gives no caption"]


def test_only_the_exact_number_matches(built):
    it = items_of(built[0])["ordinance-9-2025-26"]               # the agenda prints 09-2025-26
    assert it["title"] == "" and "title_source" not in it


def test_report_and_schema(built):
    facts, summary = built
    assert {k: v for k, v in summary["agenda_titles"].items() if k != "ambiguous"} == {
        "untitled": 3, "filled": 1, "agendas_read": 2}
    jsonschema.validate({k: v for k, v in facts.items() if k != "_wards"}, SCHEMA)


def test_votes_checks_and_counts_do_not_change(built, without):
    (a, sa), (b, sb) = built, without
    for k in ("meetings", "roll_calls", "motions", "item_events", "officials", "sources", "coverage"):
        assert a[k] == b[k], k
    assert [i["id"] for i in a["items"]] == [i["id"] for i in b["items"]]
    strip = lambda s: {k: v for k, v in s.items() if k != "agenda_titles"}           # noqa: E731
    assert strip(sa) == strip(sb)
    assert sb["agenda_titles"]["filled"] == 0
    assert vote_content(a, ["2026-07-02-regular", "2026-08-06-regular"]) == \
        vote_content(b, ["2026-07-02-regular", "2026-08-06-regular"])


def test_the_shrink_guard_sees_no_loss_when_titles_appear(built, without):
    new, old = built[0], without[0]
    assert shrink_guard(new, old) == {"kept": [], "corrections": []}


def test_a_kept_document_leaves_no_dangling_title_source(built, without):
    """The same rule as pipeline/keep-closure-dangling-zoning-ref: an item still shown whose title cites a meeting
    (or agenda) the keep took out takes the committed item's title, here none, never a dangling citation."""
    new, old = copy.deepcopy(built[0]), copy.deepcopy(without[0])
    old["meetings"] = [m for m in old["meetings"] if m["id"] != "2026-07-02-regular"]   # committed: no July meeting
    it96 = items_of(new)["ordinance-96-2025-26"]                     # voted in August, titled from July's agenda
    it96.update(title="Qq July caption", title_source={"kind": "agenda", "source_id": f"src-{sha(1)[:12]}",
                                                       "page": 1, "meeting_id": "2026-07-02-regular"})
    out = keep_documents(new, old, [{"source_id": f"src-{sha(2)[:12]}", "meeting_ids": ["2026-07-02-regular"]}])
    assert "2026-07-02-regular" not in {m["id"] for m in out["meetings"]}
    published, shown = {s["id"] for s in out["sources"]}, {m["id"] for m in out["meetings"]}
    for it in out["items"]:
        t = it.get("title_source")
        assert not t or (t["source_id"] in published and t["meeting_id"] in shown)
    assert {k: v for k, v in items_of(out)["ordinance-96-2025-26"].items()} == items_of(old)["ordinance-96-2025-26"]


def test_a_kept_document_whose_agenda_stays_published_keeps_the_title(built):
    new = copy.deepcopy(built[0])
    out = keep_documents(new, copy.deepcopy(new), [{"source_id": f"src-{sha(4)[:12]}",
                                                     "meeting_ids": ["2026-08-06-regular"]}])
    assert items_of(out)["ordinance-95-2025-26"]["title_source"]["meeting_id"] == "2026-07-02-regular"


# ------------------------------------------------------------------ the site's item type rule
def test_a_filled_zoning_caption_makes_the_item_a_rezoning(built):
    from sitegen.views import item_types
    it = items_of(built[0])["ordinance-95-2025-26"]
    assert item_types(it) == ["rezoning", "ordinance"]
    assert item_types({**it, "title": ""}) == ["ordinance"]                        # untitled: the number only


# ------------------------------------------------------------------ the export
def test_the_export_cites_the_agenda_for_a_title_it_prints(built, tmp_path):
    import csv
    import io

    from collector.export import PROVENANCE, export
    from collector.tests.test_provenance import unregistered_keys
    facts = {k: v for k, v in copy.deepcopy(built[0]).items() if k != "_wards"}
    files = {f.name: f for f in export(facts, tmp_path)}
    rows = {r["id"]: r for r in csv.DictReader(io.StringIO(files["items.csv"].read_text(encoding="utf-8")))}
    assert rows["ordinance-95-2025-26"]["title_source_url"] == CC.format(3162) + "#page=1"
    assert rows["ordinance-95-2025-26"]["title_source_page"] == "1"
    assert rows["resolution-69-2025-26"]["title_source_url"] == ""
    assert all(f"items.{c}" in PROVENANCE for c in rows["ordinance-95-2025-26"])
    assert not unregistered_keys(json.loads(files["facts.json"].read_text(encoding="utf-8")))
