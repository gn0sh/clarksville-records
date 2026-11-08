"""F3: the purchasing archive adapter (collector/fin_archive.py) on a trimmed copy of the real page.

The fixture keeps the real table markup (cells are <th>) for 15 rows covering every link label form, every status
word, the real "<strong>F</strong>EBRUARY" cell, "OCTOBER 30. 2025", an empty date, a URL shared by two rows and a
.docx bid tab. Keys: doc-completeness/*, archive-structure/*.
"""
import re
from pathlib import Path

import pytest

from collector import fin_config
from collector.fin_archive import StructureChanged, absolute, parse_archive, parse_date, repair_date, stage_of

FIX = Path(__file__).parent / "fixtures" / "finance" / "archive_trimmed.html"
CFG = fin_config.load()
HTML = FIX.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rows():
    return parse_archive(HTML, CFG)


def raw_rows():
    table = HTML[HTML.find("<table"):HTML.find("</table>")]
    return re.findall(r"<tr>(.*?)</tr>", table, re.S)[1:]


def test_every_row_is_read_in_page_order(rows):
    assert [r.row for r in rows] == list(range(1, 16))
    assert rows[0].title == "RFP - RFID Tracking Solution"
    assert rows[13].title == "BID - WHEEL LOADER"


def test_link_count_per_row_equals_documents_produced(rows):
    """AC-F7, counted independently of the parser: every href in the row's second cell."""
    for r, raw in zip(rows, raw_rows(), strict=True):
        cells = re.findall(r"<th[^>]*>(.*?)</th>", raw, re.S)
        assert len(r.links) == len(re.findall(r"<a\s[^>]*href=", cells[1])), r.title


def test_links_outside_the_table_are_not_read(rows):
    assert "bonfirehub" in HTML
    assert not any("bonfirehub" in lk.url for r in rows for lk in r.links)


def test_urls_are_absolute_on_the_archive_host(rows):
    for r in rows:
        for lk in r.links:
            assert lk.url.startswith(f"https://{CFG.archive_host}/storage/"), lk.url
            assert " " not in lk.url


def test_shared_url_and_docx_are_kept_as_links(rows):
    by_title = {r.title: r for r in rows}
    salt = {lk.url for lk in by_title["ReBid - Highway Dept Salt"].links}
    armed = {lk.url for lk in by_title["Request for Proposal - Armed Security"].links}
    assert any(u.endswith("/Bid%20Tab%20Sheet.pdf") for u in salt & armed)
    assert any(lk.url.endswith(".docx") and lk.stage == "bid_tab" for lk in by_title[
        "Request for Bid - Metal Pipe & Bands"].links)


def test_dates_and_statuses(rows):
    got = {r.title: (r.date_text, r.date, r.status, r.date_held) for r in rows}
    assert got["RFP - RFID Tracking Solution"] == ("Currently Under Review", None, "Currently Under Review", False)
    assert got["RFQ - Car Wash Services"] == ("No Award", None, "No Award", False)
    assert got["BID - INMATE UNIFORMS"] == ("NOT AWARDED", None, "NOT AWARDED", False)
    assert got["RFQ - CONSULTANT ENGINEERS - ROADWAY PROJECT"] == ("UNDER REVIEW", None, "UNDER REVIEW", False)
    assert got["Bid Listing - Jobs Related to the Public Safety Facility"] == ("", None, None, False)
    assert got["BID - JAIL PLUMBING IMPROVEMENTS"] == ("OCTOBER 30. 2025", "2025-10-30", None, False)
    assert got["RFP - ORACLE IMPLEMENTATION PARTNER"] == ("FEBRUARY 4, 2025", "2025-02-04", None, False)
    assert got["BID - WHEEL LOADER"][1] == "2025-02-26"
    assert got["ReBid - Highway Dept Salt"][1] == "2026-07-06"


@pytest.mark.parametrize("text, iso", [
    ("F EBRUARY 4, 2025", "2025-02-04"), ("OCTOBER 14. 2026", "2026-10-14"), ("Sept ember 2, 2026", "2026-09-02"),
    ("S EPTEMBER 2, 2026", "2026-09-02"), ("June 5, 2026", "2026-06-05"), ("MAY 4, 2026", "2026-05-04"),
    # only the two repairs: nothing else is corrected
    ("FEBRUARY 4 2025", None), ("FEBUARY 4, 2025", None), ("4 FEBRUARY, 2025", None), ("02/04/2025", None),
    ("FEBRUARY 4,, 2025", None), ("OCTOBER 14.2026", None), ("Currently Under Review", None),
])
def test_date_repairs_only_the_two_rules(text, iso):
    assert parse_date(text, CFG) == iso


def test_repair_is_mechanical():
    assert repair_date("F EBRUARY 4, 2025") == "FEBRUARY 4, 2025"
    assert repair_date("OCTOBER 14. 2026") == "OCTOBER 14, 2026"
    assert repair_date("BID 4. 2025") == "BID 4, 2025"       # the "." rule is positional, not a date check


def test_unparsed_date_is_held(rows):
    html = HTML.replace("MAY 4, 2026", "MAY 4TH 2026")
    r = next(x for x in parse_archive(html, CFG) if x.title.startswith("BID - SINKHOLE"))
    assert (r.date_text, r.date, r.status, r.date_held) == ("MAY 4TH 2026", None, None, True)


@pytest.mark.parametrize("label, stage", [
    ("Bid Document", "bid"), ("BID PDF", "bid"), ("Request for Bid", "bid"), ("Invitation to Bid", "advertisement"),
    ("Bid Advertisement", "advertisement"), ("Advertisement for Bid", "advertisement"),
    ("ADVERTISEMENT TO BID PDF", "advertisement"), ("BID ADVERTISEMENT PDF", "advertisement"),
    ("\xa0ADVERTISEMENT", "advertisement"), ("TDOT AD SUBMITTAL", "advertisement"),
    ("Bid Tab", "bid_tab"), ("BID TAB", "bid_tab"),
    ("Award Letter", "award_letter"), ("AWARD LETTER", "award_letter"), ("Award Letter - Laid in Place", "award_letter"),
    ("AWARD - PICKED UP", "award_letter"), ("AWARD DOCUMENT", "award_letter"), ("AWARD LETTER - BEADS", "award_letter"),
    ("Partial Award Letter 1", "partial_award"), ("PARTIAL AWARD 3", "partial_award"),
    ("Intent to Award", "notice_of_intent"), ("INTENT TO AWARD LETTER", "notice_of_intent"),
    ("NOTICE OF INTENT TO AWARD", "notice_of_intent"), ("Notice of Award", "notice_of_award"),
    ("RFP Document", "rfp"), ("RFP PDF", "rfp"), ("RFP\xa0PDF", "rfp"), ("Request for Proposals", "rfp"),
    ("Request for Proposal Document", "rfp"), ("RFQ PDF", "rfq"), ("Request for Quotes", "rfq"),
    ("Addendum #1", "addendum"), ("ADDENDUM 2", "addendum"), ("Addendum 1", "addendum"),
    ("Addenda Acknowledgement", "forms"), ("ADDENDA ACKNOWLEGEMENT FORM", "forms"), ("Required Forms", "forms"),
    ("QUESTIONS/ANSWERS", "qa"), ("Questions/Answers", "qa"), ("QUESTIONS & ANSWERS", "qa"), ("Q&As", "qa"),
    ("CONSTRUCTION DRAWINGS", "drawings"), ("GEOPHYSICAL REPORT", "other"), ("", "other"),
])
def test_stage_per_label(label, stage):
    assert stage_of(label, CFG) == stage


@pytest.mark.parametrize("edit, match", [
    (lambda h: h.replace("Bid Documents", "Documents", 1), "header"),
    (lambda h: h.replace("<strong>Bid Name</strong>", "<strong>Solicitation</strong>", 1), "header"),
    (lambda h: h.replace("</table>", "</table><table><tr><th>x</th></tr></table>"), "2 tables"),
    (lambda h: re.sub(r"(<tr>.*?</tr>).*</tbody>", r"\1</tbody>", h, flags=re.S), "no data rows"),
    (lambda h: h.replace(">BID - WHEEL LOADER</th>", ">BID - WHEEL LOADER</th><th>extra</th>"), "row 14 has 4 cells"),
    (lambda h: h.replace("<table", "<div", 1).replace("</table>", "</div>"), "0 tables"),
])
def test_structure_change_raises(edit, match):
    with pytest.raises(StructureChanged, match=match):
        parse_archive(edit(HTML), CFG)


def test_absolute_keeps_existing_escapes_and_quotes_spaces():
    base = CFG.archive_url
    assert absolute(base, "/storage/a%20b.pdf") == f"https://{CFG.archive_host}/storage/a%20b.pdf"
    assert absolute(base, "/storage/a b.pdf#page=2") == f"https://{CFG.archive_host}/storage/a%20b.pdf"
    assert absolute(base, "https://Other.Example/x") == "https://other.example/x"
