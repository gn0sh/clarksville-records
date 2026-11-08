"""Zoning case facts (collector/zoning.py, config/localities/montgomery-tn/zoning.yml): the agreement rule.

The page texts are cut from the real text layer of the March 11, 2024 minutes (agenda p2, resolution p5 of
CZ-01-2024), where the text layer reads the applicant "Johnathan Blick" as "Johnathan Buck" twice: a majority of
readings is wrong, so any dissent leaves the field null. No network, no tesseract.
"""
import copy

import pytest

from collector import zoning as Z
from collector.facts import Builder
from collector.names import NAMES, Resolver, load_roster

AGENDA = """BOARD OF COMMISSIONERS                           AGENDA                      MARCH 11,2024

ZONING RESOLUTIONS

CZ-01-2024 Application ofJohnathan Buck from R-3 to C-S
CZ-02-2024 Application of Gary Thomas Mosley from R-1 to C-2

RESOLUTIONS

24_3_1*        Resolution ofthe Montgomery County Board of Commissioners to Approve the
               Appointment ofElizabeth Black as County Purchasing Agent
"""

RESOLUTION = """                                                                                         {case}
                  RESOLUTION OF THE MONTGOMERY COUNTY BOARD OF
                                  COMMISSIONERS
                AMENDING THE ZONE CLASSIFICATION OF THE PROPERTY OF
                                {upper}
        WHEREAS, an application for a zone change from R-3 Three Family Residential District to {to_named}
Commercial District has been submitted by {name}       and
        WHEREAS, said property is identified as County Tax Map 071, parcel 026.06, containing 2.32 +1- acres, situated in Civil District 13,
located A parcel located at the northwest corner of Oakwood Rd. & Wine Ln.; and
        WHEREAS, said property is described as follows:
BEGINNING AT AN IRON ROD (SET) ON THE SOUTHERLY RIGHT OF WAY LINE OF OLD DOVER ROAD
        NOW, THEREFORE, BE IT RESOLVED by the Montgomery County Board of County Commissioners assembled in regular session
on this 11th day of March, 2024 that the zone classification ofthe property of {name2} from R-3 to {to} is hereby approved.
Duly passed and approved this 11th day of March, 2024.
"""

STAFF = """           CLARKSVILLE-MONTGOMERY COUNTY REGIONAL PLANNING
                           STAFF REVIEW ZONING
 RPC MEETING DATE 02/27/2024                                          CASE NUMBER CZ-02-2024
NAME OF APPLICANT: Gary Thomas Mosley
ACREAGE TO BE REZONED: 1.29 +/-
      PRESENT ZONING: R-1
      PROPOSED ZONING: C-2
   PROPERTY LOCATION: Property fronting on the south frontage of Highway 149, 1,560 +/- feet west of the Highway 149 & Belle Rd. intersection.
 CITY COUNCIL WARD: NA                   COUNTY COMMISSION DISTRICT 7
"""


def resolution(case="CZ-01-2024", upper="JOHNATHAN BLICK", name="Johnathan Buck", name2="Johnathan Buck",
               to="C-5", to_named="C-5 Highway & Arterial"):
    return RESOLUTION.format(case=case, upper=upper, name=name, name2=name2, to=to, to_named=to_named)


@pytest.fixture(scope="module")
def rules():
    return Z.load_rules()


def pooled(readings, sid="src-505a509b28f7", date="2024-03-11"):
    return [(r, sid, date) for r in readings]


def by_case(readings, case):
    return [r for r in readings if r.case == case]


def test_rules_load_from_the_locality_config(rules):
    assert rules.case_prefixes == ("CZ",)
    assert "C-5" in rules.districts and "C-S" not in rules.districts


def test_a_majority_that_misreads_the_name_is_not_enough(rules):
    """CZ-01-2024: the page prints "Johnathan Blick" three times; the text layer reads "Buck" twice. Any dissent among
    well-formed readings leaves the field null."""
    rs = Z.page_readings([AGENDA, resolution()], rules)
    names = sorted(r.shown for r in by_case(rs, "CZ-01-2024") if r.field == "applicant")
    assert names == ["JOHNATHAN BLICK", "Johnathan Buck", "Johnathan Buck", "Johnathan Buck"]
    out = Z.decide(pooled(by_case(rs, "CZ-01-2024")))
    assert out["applicant"] is None


def test_agreeing_engines_give_the_value_as_printed_with_its_page(rules):
    page = resolution(name="Johnathan Blick", name2="Johnathan Blick")
    rs = Z.page_readings([AGENDA, page], rules)
    rs = [r for r in rs if not (r.printing == "listing")]          # the agenda line says Buck: leave it out here
    assert Z.decide(pooled(by_case(rs, "CZ-01-2024")))["applicant"] is None     # three printings, one engine
    rs += Z.page_readings(["", page], rules, engine="tesseract")
    out = Z.decide(pooled(by_case(rs, "CZ-01-2024")))
    assert out["applicant"] == {"value": "Johnathan Blick", "source_id": "src-505a509b28f7", "page": 2}
    assert out["from_zoning"] == {"value": ["R-3"], "source_id": "src-505a509b28f7", "page": 2}
    assert out["to_zoning"]["value"] == ["C-5"]          # the agenda's "C-S" was not counted (it is not a code)


def test_a_misread_code_is_kept_as_malformed_never_corrected(rules):
    rs = Z.page_readings([AGENDA], rules)
    to = [r for r in by_case(rs, "CZ-01-2024") if r.field == "to_zoning"]
    assert [(r.key, r.value, r.shown) for r in to] == [(Z.MALFORMED, None, "C-S")]      # not a code: it vetoes
    assert Z._zoning("B-i Single-Family Estate", rules, True) is None
    assert Z._zoning("R-1 Light Industrial", rules, True) is None      # code and printed name disagree
    assert Z._zoning("R- 1", rules, False)[0] == ("R-1",)               # only spaces around the dash are dropped
    assert Z._zoning("R-l", rules, False) is None
    assert Z._zoning("C-5 Highway & Arterial Commercial District / AG Agricultural", rules, True)[0] == ("C-5", "AG")
    assert Z._zoning("C-2 - - General Commercial", rules, True)[0] == ("C-2",)


def test_one_reading_alone_is_never_published(rules):
    rs = Z.page_readings([resolution()], rules)
    acres = [r for r in rs if r.field == "acreage"]
    assert [r.value for r in acres] == [2.32]
    assert Z.decide(pooled(rs))["acreage"] is None


def test_the_same_printing_in_two_documents_counts_once(rules):
    rs = by_case(Z.page_readings([resolution()], rules), "CZ-01-2024")
    loc = [r for r in rs if r.field == "location"]
    assert len(loc) == 1
    twice = pooled(loc, "src-aaaaaaaaaaaa") + pooled(loc, "src-bbbbbbbbbbbb")
    assert Z.decide(twice)["location"] is None


def test_a_second_engine_on_the_same_printing_is_an_independent_reading(rules):
    text = by_case(Z.page_readings([resolution()], rules), "CZ-01-2024")
    tess = by_case(Z.page_readings([resolution().replace("+1-", "+/-")], rules, engine="tesseract"), "CZ-01-2024")
    out = Z.decide(pooled(text + tess))
    assert out["acreage"] == {"value": 2.32, "printed": "2.32 +/- acres", "source_id": "src-505a509b28f7", "page": 1}
    assert out["location"]["value"] == "A parcel located at the northwest corner of Oakwood Rd. & Wine Ln."
    assert out["applicant"] is None                       # Blick in the heading, Buck elsewhere: still a dissent


def test_plus_minus_misread_agrees_and_the_printed_form_is_shown(rules):
    staff = Z.page_readings([STAFF], rules, engine="tesseract")
    res = Z.page_readings([resolution(case="CZ-02-2024").replace(
        "containing 2.32 +1- acres, situated in Civil District 13,\nlocated A parcel located at the northwest corner of "
        "Oakwood Rd. & Wine Ln.",
        "containing 1.29 +1- acres, situated in Civil District 13,\nlocated Property fronting on the south frontage of "
        "Highway 149, 1,560 +1- feet west of the Highway 149 & Belle Rd. intersection")], rules)
    out = Z.decide(pooled(by_case(staff + res, "CZ-02-2024")))
    assert out["location"]["value"] == ("Property fronting on the south frontage of Highway 149, 1,560 +/- feet west "
                                        "of the Highway 149 & Belle Rd. intersection")
    assert out["acreage"]["value"] == 1.29
    assert out["from_zoning"] is None and out["to_zoning"] is None    # this resolution text says R-3 to C-5: dissent


def test_pages_belong_to_the_case_printed_on_them(rules):
    assert Z.page_case(resolution(case="CZ-Ol-2024"), rules) == "CZ-01-2024"       # the item-number glyph rule
    assert Z.page_case(resolution(case="CZO-1-2024"), rules) is None                # a text amendment: no applicant
    assert Z.page_readings([resolution(case="")], rules) == []                      # no case number: nothing read


def test_values_are_plain_text_or_dropped(rules):
    assert Z._applicant("Kevin & Gwen Grifl3’") is not None                        # well formed, so it dissents
    assert Z._applicant("Mark Ireland and WHEREAS, said property") is None
    assert Z._applicant("~~") is None
    assert Z._acreage("I.4") is None and Z._acreage(".91")[0] == 0.91


def builder():
    return Builder(Resolver(load_roster(NAMES)), [])


class Doc:
    def __init__(self, sha, readings):
        self.source = {"sha256": sha}
        self.zoning = readings


def test_builder_attaches_zoning_only_to_rezoning_items_and_cited_sources(rules):
    b = builder()
    b.sources.append({"id": "src-505a509b28f7", "meeting_date": "2024-03-11"})
    b.items["CZ-02-2024"] = {"id": "CZ-02-2024", "number": "CZ-02-2024", "title": "CZ-02-2024", "link_basis": "number",
                             "year": 2024}
    b.items["CZO-1-2024"] = {"id": "CZO-1-2024", "number": "CZO-1-2024", "title": "CZO-1-2024",
                             "link_basis": "number", "year": 2024}
    rs = Z.page_readings([AGENDA, STAFF], rules) + Z.page_readings(["", STAFF], rules, engine="tesseract")
    b.add_zoning(Doc("505a509b28f7" + "0" * 52, rs))
    b.add_zoning(Doc("ffffffffffff" + "0" * 52, rs))           # not cited by any fact: ignored
    facts = b.facts(load_roster(NAMES))
    items = {i["id"]: i for i in facts["items"]}
    assert "zoning" not in items["CZO-1-2024"]
    z = items["CZ-02-2024"]["zoning"]
    assert set(z) == set(Z.FIELDS)
    assert z["applicant"] == {"value": "Gary Thomas Mosley", "source_id": "src-505a509b28f7", "page": 1}
    assert z["to_zoning"]["value"] == ["C-2"] and z["location"]["page"] == 2 and z["acreage"]["value"] == 1.29
    assert all(r[1] == "src-505a509b28f7" for r in b.zoning["CZ-02-2024"])


def test_decide_is_deterministic_whatever_the_reading_order(rules):
    rs = pooled(by_case(Z.page_readings([AGENDA, STAFF], rules), "CZ-02-2024"))
    a = Z.decide(rs)
    b = Z.decide(list(reversed(copy.copy(rs))))
    assert a == b


def test_a_printing_the_two_engines_read_differently_is_dissent(rules):
    """CZ-06-2024 shape: tesseract reads "Blick" where the text layer reads "Buck" in the "submitted by" line. One
    engine misread it, and nothing says which: that is dissent, so the field is null (the old rule 5 set the printing
    aside). On CZ-01-2024 the text layer's "Buck" in a line tesseract did not read dissents too."""
    page = resolution(name2="Johnathan Blick")
    text = by_case(Z.page_readings([page], rules), "CZ-01-2024")
    tess = by_case(Z.page_readings([page.replace("by Johnathan Buck", "by Johnathan Blick")], rules,
                                   engine="tesseract"), "CZ-01-2024")
    assert Z.decide(pooled(text + tess))["applicant"] is None
    no_line = [r for r in tess if r.printing != "submitted"]
    assert Z.decide(pooled(text + no_line))["applicant"] is None


def test_patterns_do_not_overrun_their_values(rules):
    """A matched group whose value fails its check vetoes the field, so the patterns keep the marks tesseract reads
    around a value (fill lines, table rules) and the "and" before WHEREAS outside the group (zoning.yml)."""
    page = resolution(name="Johnathan Blick =", name2="Johnathan Blick —", upper="| JOHNATHAN BLICK").replace(
        "Wine Ln.; and", "Wine Ln.; and |")
    rs = by_case(Z.page_readings([page], rules, engine="tesseract"), "CZ-01-2024")
    got = {(r.printing, r.field): r.shown for r in rs}
    assert got[("submitted", "applicant")] == "Johnathan Blick"
    assert got[("approved", "applicant")] == "Johnathan Blick"
    assert got[("heading", "applicant")] == "JOHNATHAN BLICK"
    assert got[("located", "location")] == "A parcel located at the northwest corner of Oakwood Rd. & Wine Ln."
    assert Z.MALFORMED not in {r.key for r in rs}
    blank = STAFF.replace("PROPOSED ZONING: C-2", "PROPOSED ZONING: EXTENSION OF ZONING CLASSIFICATION: NO")
    staff = {r.field: r for r in Z.page_readings([blank], rules)}
    assert "to_zoning" not in staff and staff["from_zoning"].value == ("R-1",)     # a blank reads nothing
    assert Z._zoning("C-5 - Highway & Arterial Commercial", rules, True)[0] == ("C-5",)    # not code "C-5-Highway"


def test_acreage_keeps_its_printed_form(rules):
    """The number alone loses "+/-", "approximately" and trailing zeros; `printed` keeps the form the agreeing readings
    print (provenance/acreage-not-as-printed)."""
    page = resolution().replace("containing 2.32 +1- acres", "containing approximately 2.320 +/- acres")
    rs = by_case(Z.page_readings([page], rules) + Z.page_readings([page], rules, engine="tesseract"), "CZ-01-2024")
    a = Z.decide(pooled(rs))["acreage"]
    assert a["value"] == 2.32 and a["printed"] == "approximately 2.320 +/- acres"
    staff = Z.page_readings([STAFF], rules) + Z.page_readings([STAFF], rules, engine="tesseract")
    assert Z.decide(pooled(by_case(staff, "CZ-02-2024")))["acreage"]["printed"] == "1.29 +/-"


def test_zoning_keys_are_registered_as_stated():
    from collector.export import PROVENANCE
    assert PROVENANCE["facts.json:items.zoning"] == "stated"
    for f in Z.FIELDS:
        assert PROVENANCE[f"facts.json:items.zoning.{f}.value"] == "stated"
        assert PROVENANCE[f"facts.json:items.zoning.{f}.page"].startswith("derived: ")
    assert PROVENANCE["facts.json:items.zoning.acreage.printed"] == "stated"


def test_acreage_printed_needs_both_engines_to_read_the_same_form(rules):
    """The engines agree on the number but read its words differently: the number is published, the printed form is
    null, and the site words it as the number only (provenance/acreage-printed-uncorroborated)."""
    a_page = resolution().replace("containing 2.32 +1- acres", "containing approximately 2.32 +/- acres")
    b_page = resolution().replace("containing 2.32 +1- acres", "containing 2.32 +/- acres")
    rs = by_case(Z.page_readings([a_page], rules) + Z.page_readings([b_page], rules, engine="tesseract"), "CZ-01-2024")
    a = Z.decide(pooled(rs))["acreage"]
    assert a["value"] == 2.32 and a["printed"] is None and a["page"] == 1
    # "+1-" (text layer) and "+/-" (tesseract) are one symbol in the key: stated, shown with "+/-"
    c_page = resolution()
    rs = by_case(Z.page_readings([c_page], rules) + Z.page_readings([b_page], rules, engine="tesseract"), "CZ-01-2024")
    assert Z.decide(pooled(rs))["acreage"]["printed"] == "2.32 +/- acres"
    from sitegen.views import acreage_number_text, zoning_rows

    class Ix:
        def src(self, sid, page):
            return {"sid": sid, "page": page}
    (row,) = zoning_rows(Ix(), {"zoning": {"acreage": a}})
    assert row["value"] == "2.32 acres (number from the minutes)" and "printed" not in row["value"]
    assert acreage_number_text(1.0) == "1 acre (number from the minutes)"


def test_acreage_pattern_takes_only_known_plus_minus_forms(rules):
    """A garbled "+/-" ("1.00 -i-I- acres", CZ-10-2022's text layer) is not read as a qualifier: the pattern takes only
    "+/-", its known misreads "+1-", "+!-", "+l-", "+I-", and "±"."""
    for form in ("+/-", "+1-", "+ / -", "+!-", "±"):
        page = resolution().replace("containing 2.32 +1- acres", f"containing 2.32 {form} acres")
        (a,) = [r for r in by_case(Z.page_readings([page], rules), "CZ-01-2024") if r.field == "acreage"]
        assert a.value == 2.32, form
    for garble in ("-i-I-", "-I-/-", "+1-x"):
        page = resolution().replace("containing 2.32 +1- acres", f"containing 2.32 {garble} acres")
        assert not [r for r in by_case(Z.page_readings([page], rules), "CZ-01-2024") if r.field == "acreage"], garble
