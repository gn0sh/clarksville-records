"""City budget books (config/localities/clarksville-tn/finance.yml, collector/fin_books.py): config checks."""
import copy

import pytest
import yaml

from collector import fin_books, fin_config
from collector.fin_config import FinanceConfigError

CITY = fin_books.paths("clarksville-tn")["config"]


@pytest.fixture(scope="module")
def raw():
    return yaml.safe_load(CITY.read_text(encoding="utf-8"))


def test_city_config_loads(raw):
    cfg = fin_config.load_books(CITY)
    b = cfg.budget
    assert [x.id for x in b.books] == ["fy2024-adopted", "fy2025-adopted", "fy2026-final", "fy2027-presented"]
    assert b.books_not_read == ()
    assert [x.id for x in b.books if x.glyph_map] == ["fy2025-adopted"]       # read through its glyph table
    assert [x.id for x in b.books if x.fund_line] == ["fy2025-adopted"]       # "1100 General Fund"
    assert b.org_section_totals
    assert all(x.url.startswith("https://www.clarksvilletn.gov/DocumentCenter/View/") for x in b.books)
    assert b.amount_unit == "cents" and b.fund_from_header and b.header_year_lines
    assert dict(b.kind_words)["Mayor"] == "proposed"
    assert b.run_totals == {"TOTAL REVENUE": "revenue", "TOTAL EXPENSE": "expenditure", "GRAND TOTAL": "net"}


def test_county_config_keeps_the_defaults():
    b = fin_config.load().budget
    assert (b.amount_unit, b.header_year_lines, b.fund_from_header, b.split_glued_amounts, b.fund_total_by_name) == \
        ("dollars", False, False, False, False)
    assert b.org_code is None and b.run_end is None and not b.statement_by_code and not b.run_totals
    assert not b.header_split_before and not b.ignore_tokens and not b.books_not_read


def test_books_only_file_rejects_other_keys(raw):
    cfg = copy.deepcopy(raw)
    cfg["archive_url"] = "https://example.org/"
    with pytest.raises(FinanceConfigError, match="unknown keys"):
        fin_config.parse_books(cfg)


@pytest.mark.parametrize("key,value,match", [
    ("amount_unit", "pennies", "amount_unit"),
    ("fund_from_header", "yes", "fund_from_header"),
    ("page_titles", {"summary": "X"}, "page_titles"),
])
def test_bad_budget_keys_fail_loudly(raw, key, value, match):
    cfg = copy.deepcopy(raw)
    cfg["budget"][key] = value
    with pytest.raises(FinanceConfigError, match=match):
        fin_config.parse_books(cfg)


def test_run_totals_need_a_run_end_and_known_statements(raw):
    cfg = copy.deepcopy(raw)
    del cfg["budget"]["rows"]["run_end"]
    with pytest.raises(FinanceConfigError, match="run_end"):
        fin_config.parse_books(cfg)
    cfg = copy.deepcopy(raw)
    cfg["budget"]["rows"]["run_totals"]["GRAND TOTAL"] = "everything"
    with pytest.raises(FinanceConfigError, match="run_totals"):
        fin_config.parse_books(cfg)


def test_fund_number_group_optional_only_with_fund_from_header(raw):
    cfg = copy.deepcopy(raw)
    cfg["budget"]["fund_from_header"] = False
    with pytest.raises(FinanceConfigError, match="fund_line"):
        fin_config.parse_books(cfg)


def test_not_read_book_cannot_also_be_read(raw):
    cfg = copy.deepcopy(raw)
    cfg["budget"]["books_not_read"] = [{"id": "fy2024-adopted", "title": "x", "fiscal_year": 2024,
                                        "url": "https://www.clarksvilletn.gov/DocumentCenter/View/1", "reason": "x"}]
    with pytest.raises(FinanceConfigError, match="both read and not read"):
        fin_config.parse_books(cfg)


@pytest.mark.parametrize("value,match", [
    ("config/localities/clarksville-tn/no-such-table.json", "glyph_map must name a table file in the repo"),
    ("/etc/passwd", "glyph_map must name a table file in the repo"),
    ("../outside.json", "glyph_map must name a table file in the repo"),
    ("config/localities/clarksville-tn/finance.yml", "not a glyph table"),
])
def test_a_bad_glyph_map_fails_the_load(raw, value, match):
    cfg = copy.deepcopy(raw)
    cfg["budget"]["books"][1]["glyph_map"] = value
    with pytest.raises(FinanceConfigError, match=match):
        fin_config.parse_books(cfg)


def test_a_glyph_table_entry_must_be_one_character_and_an_advance(raw, tmp_path, monkeypatch):
    table = tmp_path / "t.json"
    monkeypatch.setattr(fin_config, "ROOT", tmp_path)
    cfg = copy.deepcopy(raw)
    cfg["budget"]["books"][1]["glyph_map"] = "t.json"
    for glyphs in ({"a" * 64: {"char": "AB", "advance": 0.6}}, {"a" * 64: {"char": "A", "advance": 0}},
                   {"A" * 64: {"char": "A", "advance": 0.6}}, {"a" * 64: {"char": "\n", "advance": 0.6}}, {}):
        table.write_text(json.dumps({"glyphs": glyphs}))
        with pytest.raises(FinanceConfigError, match="glyph_map"):
            fin_config.parse_books(cfg)
    table.write_text(json.dumps({"glyphs": {"a" * 64: {"char": "A", "advance": 0.6}}}))
    assert fin_config.parse_books(cfg).budget.books[1].glyph_map == "t.json"


def test_a_book_fund_line_needs_a_name_group(raw):
    cfg = copy.deepcopy(raw)
    cfg["budget"]["books"][1]["fund_line"] = r"^\d{4} .+$"
    with pytest.raises(FinanceConfigError, match="fund_line needs a"):
        fin_config.parse_books(cfg)


def test_org_section_totals_need_an_org_code(raw):
    cfg = copy.deepcopy(raw)
    del cfg["budget"]["rows"]["org_code"]
    with pytest.raises(FinanceConfigError, match="org_section_totals needs"):
        fin_config.parse_books(cfg)


# ------------------------------------------------------------------ the reader on real city pages
# Fixtures: `pdftotext -bbox` of single pages (collector/tests/fixtures/finance/city/<book>_p<page>.bbox.html; the
# staff login and name in the page foot and the PDF metadata are replaced). Keys: budget-reconcile/*, column-kind/*.
import json  # noqa: E402

from collector import fin_budget, fin_checks, fin_facts  # noqa: E402
from collector.fin_budget import BookLayoutError  # noqa: E402
from collector.pdfwords import Word  # noqa: E402
from collector.store import Store  # noqa: E402
from collector.tests.fin_fake import page_words  # noqa: E402

RULES = fin_config.load_books(CITY).budget
BOOK = {b.id: b for b in RULES.books}


def words_of(book_id: str, pages) -> list:
    prefix = book_id.split("-")[0]
    return [w for p in pages for w in page_words(f"city/{prefix}_p{p}", p)]


def read(book_id: str, pages, mutate=None):
    words = words_of(book_id, pages)
    if mutate:
        words = mutate(words)
    r = fin_budget.read_book(words, BOOK[book_id], RULES)
    lines = fin_budget.to_records(r, RULES)
    counts = fin_checks.reconcile(lines, RULES.run_totals)
    return r, {x["id"]: x for x in lines}, counts


def by_label(lines: dict, label: str, nth: int = 0) -> dict:
    hits = sorted((x for x in lines.values() if x["label_as_printed"] == label),
                  key=lambda x: (x["page"], int(x["id"].rsplit("/r", 1)[1])))
    return hits[nth]


def cents(x: dict) -> list:
    return [c["cents"] for c in x["cells"]]


@pytest.mark.parametrize("tok,value", [("-1,404.28", -140428), (".00", 0), ("12,331,758.00", 1233175800),
                                       ("-.50", -50), ("1,404", None), ("(1.00)", None), ("-", None),
                                       ("1.2", None), ("________", None)])
def test_amount_in_cents(tok, value):
    assert fin_budget.amount_cents(tok) == value


@pytest.mark.parametrize("book_id,pages,last", [
    ("fy2024-adopted", [50], ("2024 2nd Readin", 2024, "adopted")),
    ("fy2026-final", [138], ("2026 2nd Readin", 2026, "adopted")),
    ("fy2027-presented", [378], ("2027 Mayor", 2027, "proposed")),
])
def test_columns_from_the_two_line_header(book_id, pages, last):
    r, _, _ = read(book_id, pages)
    assert [c["kind"] for c in r.columns] == ["actual", "adopted", "amended", "actual", "projected", last[2]]
    assert (r.columns[-1]["header_as_printed"], r.columns[-1]["fiscal_year"]) == last[:2]
    first = r.columns[0]["fiscal_year"]
    assert [c["fiscal_year"] for c in r.columns] == [first, first + 1, first + 1, first + 1, first + 1, first + 2]


def test_one_whole_report_run_adds_up_vehicle_replacement_fy2026():
    _, lines, counts = read("fy2026-final", [138])
    assert counts == {"exact": 6, "within_rounding": 0, "does_not_add_up": 0, "not_checked": 0}
    assert not any(x["held"] for x in lines.values())
    row = by_label(lines, "421 Rev-GF")              # org dropped (it repeats the heading), project code kept
    assert (row["account_code"], row["statement"], row["fund_name"], row["fund_no"]) == \
        ("34801", "revenue", "Vehicle Replacement Fund", None)
    assert row["heading_as_printed"] == "5645000 Vehicle Replacement Revenue" and row["department"] is None
    assert cents(row) == [0, -310527800, -310527800, -310527800, -310527800, -233782300]
    assert all(c["dollars"] is None for c in row["cells"])           # no whole-dollar value is made up
    veh = by_label(lines, "Vehicles", 0)
    assert veh["statement"] == "expenditure" and veh["department"] == "56450004 Vehicle Replacement Expense"
    fund = by_label(lines, "TOTAL Vehicle Replacement Fu")
    assert (fund["statement"], fund["fund_name"], len(fund["scope_line_ids"])) == ("net", "Vehicle Replacement Fund", 11)
    rev, exp, grand = (by_label(lines, k) for k in ("TOTAL REVENUE", "TOTAL EXPENSE", "GRAND TOTAL"))
    assert {lines[i]["statement"] for i in rev["scope_line_ids"]} == {"revenue"} and len(rev["scope_line_ids"]) == 7
    assert {lines[i]["statement"] for i in exp["scope_line_ids"]} == {"expenditure"} and len(exp["scope_line_ids"]) == 4
    assert grand["statement"] == "net" and grand["fund_name"] is None and len(grand["scope_line_ids"]) == 11
    assert grand["check"]["per_cell"][1] == {"printed": 425336400, "sum": 425336400, "diff": 0}


def test_page_foot_and_end_of_report_are_never_stored():
    _, lines, _ = read("fy2026-final", [138])
    text = " ".join(x["label_as_printed"] + " " + (x["heading_as_printed"] or "") for x in lines.values())
    for word in ("Report generated", "Program ID", "staff", "END OF REPORT", "Generated by", "________"):
        assert word not in text


def test_report_date_is_read_from_the_page_foot_once_per_date():
    """book.report_dates (finance-contracts 10): the foot's date only, first page that prints it; no time or login."""
    r, _, _ = read("fy2026-final", [111, 112, 113])
    assert r.report_dates == [{"as_printed": "07/08/2025", "page": 111}]
    r, _, _ = read("fy2027-presented", [378, 379])
    assert r.report_dates == [{"as_printed": "05/29/2026", "page": 378}]


def test_no_report_date_rule_reads_no_date():
    import dataclasses
    rules = dataclasses.replace(RULES, report_date=None)
    r = fin_budget.read_book(words_of("fy2026-final", [111]), BOOK["fy2026-final"], rules)
    assert r.report_dates == []


def test_touching_amounts_are_split_by_character_width_fy2027_p17():
    _, lines, _ = read("fy2027-presented", [17])
    for label in ("TOTAL General Fund", "TOTAL REVENUE", "GRAND TOTAL"):
        x = by_label(lines, label)
        assert x["held"] is None
        assert [c["as_printed"] for c in x["cells"]] == ["-156,603,709.95", "-162,210,090.00", "-156,067,854.19",
                                                          "-145,725,234.32", ".00", "-186,435,257.00"]
        assert cents(x)[0] == -15660370995


def test_a_split_off_its_column_edge_holds_the_line():
    # the first touching word printed 3 pt to the right: its pieces are off their columns' right edges
    words = words_of("fy2027-presented", [17])
    glued = [w.text for w in words if "-162,210,090.00" in w.text]
    assert glued                                       # the fixture prints the amounts touching
    _, lines, _ = read("fy2027-presented", [17], mutate=lambda ws: [
        Word(w.page, w.x0 + 3, w.x1 + 3, w.y0, w.y1, w.text) if w.text == glued[0] else w for w in ws])
    held = [x for x in lines.values() if x["held"] == fin_budget.HELD_ALIGN]
    assert held and all(c["cents"] is None and c["dollars"] is None for x in held for c in x["cells"])
    assert all(x["check"]["state"] == "not_checked" for x in held if x["check"])


def test_split_glued_leaves_other_words_alone():
    w = Word(1, 100.0, 148.2, 0, 10, "-1,404.28")
    assert fin_budget.split_glued(w, "cents") == [w]
    assert fin_budget.split_glued(Word(1, 0, 40, 0, 10, "PT2022"), "cents")[0].text == "PT2022"
    assert fin_budget.split_glued(Word(1, 0, 90, 0, 10, "-1.00-2.00"), "dollars")[0].text == "-1.00-2.00"
    parts = fin_budget.split_glued(Word(1, 0.0, 120.0, 0, 10, "REVENUE-1.00-22.00"), "cents")
    assert [p.text for p in parts] == ["REVENUE", "-1.00", "-22.00"]
    assert [round(p.x1, 3) for p in parts] == [round(7 * 120 / 18, 3), round(12 * 120 / 18, 3), 120.0]


def test_split_glued_starts_where_the_value_bands_start():
    # "024.00" ends at x 94.9, left of the value bands (x 100): it stays in the label (budget-reconcile/glued-split)
    w = Word(1, 0.0, 138.0, 0, 10, "FUND2024.00-5.00")       # 16 chars, ~8.6 pt each; "-5.00" ends at 138
    cw = 138.0 / 16
    parts = fin_budget.split_glued(w, "cents", value_x0=100.0)
    assert [p.text for p in parts] == ["FUND2024.00", "-5.00"]
    assert round(parts[0].x1, 3) == round(11 * cw, 3)
    assert [p.text for p in fin_budget.split_glued(w, "cents")] == ["FUND2", "024.00", "-5.00"]   # no band: cut
    assert fin_budget.split_glued(Word(1, 0, 60, 0, 10, "AB-1.00-2.00"), "cents", value_x0=100.0)[0].text == \
        "AB-1.00-2.00"                                         # every piece left of the bands: left as it is


def test_project_subtotals_inside_an_org_section_fy2027_self_insurance():
    _, lines, counts = read("fy2027-presented", [378, 379])
    assert counts == {"exact": 11, "within_rounding": 0, "does_not_add_up": 0, "not_checked": 0}
    subs = [x for x in lines.values() if x["row_role"] == "subtotal"]
    assert sorted(x["label_as_printed"] for x in subs) == ["TOTAL AUTO LIABILITY CLAIMS", "TOTAL GENERAL LIABILITY",
                                                           "TOTAL OJI", "TOTAL UNDEFINED PROJECT",
                                                           "TOTAL UNDEFINED PROJECT"]
    sect = by_label(lines, "TOTAL Self-Insurance Expendi")
    assert sect["row_role"] == "total" and len(sect["scope_line_ids"]) == 10      # every project's rows
    oji = by_label(lines, "OJI Off/Admin")
    assert (oji["account_code"], oji["statement"]) == ("4310", "expenditure")
    assert oji["heading_as_printed"] == "23410003 Self-Insurance Expenditure"


def test_project_line_under_an_org_heading_continues_it_fy2026_police():
    _, lines, counts = read("fy2026-final", [111, 112, 113])
    assert counts == {"exact": 2, "within_rounding": 0, "does_not_add_up": 0, "not_checked": 0}
    tot = by_label(lines, "TOTAL Police Special Revenue")
    assert tot["heading_as_printed"] == "29420001 Police Special Revenue PD090 Mental Health Wellness Counselor"
    assert tot["statement"] == "expenditure" and len(tot["scope_line_ids"]) == 36
    assert by_label(lines, "TOTAL Police Special Rev-Rev")["statement"] == "revenue"


def test_a_book_starting_mid_section_keeps_the_org_and_reads_the_code():
    _, lines, _ = read("fy2027-presented", [17])
    x = by_label(lines, "100360 Misc Rev")
    assert (x["account_code"], x["statement"]) == ("36500", "revenue")


def test_an_account_code_of_no_statement_class_fails_the_book():
    def recode(words):
        return [Word(w.page, w.x0, w.x1, w.y0, w.y1, "5742") if w.text == "4742" else w for w in words]
    with pytest.raises(BookLayoutError, match="statement_by_code"):
        read("fy2026-final", [138], mutate=recode)


def test_a_header_without_a_fund_name_fails_the_book():
    def drop(words):            # the fund name printed left of ACTUAL on the header's second line
        y = next(w.yc for w in words if w.text == "ACTUAL")
        return [w for w in words if not (abs(w.yc - y) < 2 and w.x1 < 250)]
    with pytest.raises(BookLayoutError, match="names no one fund"):
        read("fy2026-final", [138], mutate=drop)


def test_empty_scope_of_zeros_is_exact_only_for_a_report_run_total():
    cell = {"header_as_printed": "x", "fiscal_year": 2027, "kind": "actual", "as_printed": ".00", "dollars": None,
            "cents": 0}
    zero = {"cells": [cell], "held": None}
    assert fin_checks.check_total(zero, [], run_total=True)["state"] == "exact"
    assert fin_checks.check_total(zero, [])["state"] == "does_not_add_up"        # any other total of nothing
    assert fin_checks.check_total({"cells": [dict(cell, cents=5, as_printed=".05")], "held": None},
                                  [], run_total=True)["state"] == "does_not_add_up"


def test_reconcile_marks_only_configured_run_totals_as_run_totals():
    cell = {"header_as_printed": "x", "fiscal_year": 2027, "kind": "actual", "as_printed": ".00", "dollars": None,
            "cents": 0}

    def total(label, code=None):
        return {"id": label, "row_role": "total", "account_code": code, "label_as_printed": label,
                "scope_line_ids": [], "cells": [dict(cell)], "held": None}
    lines = [total("TOTAL REVENUE"), total("TOTAL Some Fund"), total("TOTAL REVENUE", code="4310")]
    fin_checks.reconcile(lines, RULES.run_totals)
    assert [x["check"]["state"] for x in lines] == ["exact", "does_not_add_up", "does_not_add_up"]


def _cents_cell(cents_value, printed):
    return {"header_as_printed": "x", "fiscal_year": 2027, "kind": "actual", "as_printed": printed, "dollars": None,
            "cents": cents_value}


def test_a_cents_book_allows_no_rounding_slip():
    # budget-reconcile/rounding-bound-in-cents: a book printed to the cent rounds nothing
    scope = [{"cells": [_cents_cell(100, "1.00")], "held": None}, {"cells": [_cents_cell(200, "2.00")], "held": None}]
    off = fin_checks.check_total({"cells": [_cents_cell(301, "3.01")], "held": None}, scope)
    assert off["state"] == "does_not_add_up"
    assert off["per_cell"] == [{"printed": 301, "sum": 300, "diff": 1}]
    assert fin_checks.check_total({"cells": [_cents_cell(300, "3.00")], "held": None}, scope)["state"] == "exact"
    assert fin_checks.rounding_bound(2, cents=True) == 0


def test_a_dollars_book_keeps_its_rounding_bound():
    def cell(d):
        return {"header_as_printed": "x", "fiscal_year": 2027, "kind": "actual", "as_printed": str(d), "dollars": d}
    scope = [{"cells": [cell(1)], "held": None}, {"cells": [cell(2)], "held": None}]
    assert fin_checks.check_total({"cells": [cell(4)], "held": None}, scope)["state"] == "within_rounding"
    assert fin_checks.rounding_bound(2) == 1


def test_editions_compare_on_cents():
    def line(book, value):
        return {"id": f"{book}/p1/r1", "book_id": book, "fund_no": None, "account_code": "4310",
                "label_as_printed": "Off/Admin", "heading_as_printed": "10411003 Ops", "heading_from_total": False,
                "held": None, "edition_differs": [],
                "cells": [{"fiscal_year": 2025, "kind": "actual", "cents": value, "dollars": None}]}
    a, b = line("fy2026-final", 100), line("fy2027-presented", 101)
    assert fin_checks.edition_compare([a, b]) == [(a["id"], b["id"])]
    a, b = line("fy2026-final", 100), line("fy2027-presented", 100)
    assert fin_checks.edition_compare([a, b]) == []


# ------------------------------------------------------------------ FY2025: the glyph-decoded book's layout
# Fixtures fy2025_p<page>.bbox.html: `pdftotext -bbox` of collector/type3_decode.py's copy of the book (the staff
# login and name replaced, as above). This book prints a section total as "<org> <name>" (no TOTAL), the fund number
# before the fund name, and starts a fund mid-page after the last fund's total.
def drop(page: int, y0: float, y1: float):
    """A mutate for read(): leave out the words of `page` whose centre lies between y0 and y1 (rows that continue a
    section, or open a fund, on a page the fixtures do not hold)."""
    return lambda ws: [w for w in ws if not (w.page == page and y0 < w.yc < y1)]


def test_fy2025_section_total_prints_its_org_and_name_and_adds_up():
    _, lines, _ = read("fy2025-adopted", [114, 115])
    t = by_label(lines, "10492003 Museum")
    assert (t["row_role"], t["account_code"], t["heading_as_printed"]) == ("total", None, "10492003 Museum")
    assert t["check"]["state"] == "exact" and [lines[i]["account_code"] for i in t["scope_line_ids"]] == ["4868"]
    assert cents(t) == [101334000, 103980000, 103980000, 103980000, 0, 103980000]
    assert by_label(lines, "10491004 Transit Syste")["check"]["state"] == "exact"


def test_fy2025_a_fund_that_starts_mid_page_takes_the_next_page_header_fund():
    _, lines, _ = read("fy2025-adopted", [114, 115, 116], mutate=drop(116, 385, 560))   # fund 1222's rows
    gf = by_label(lines, "TOTAL 1100 General Fund")
    assert (gf["fund_name"], gf["fund_no"], gf["statement"]) == ("General Fund", None, "net")
    drug = by_label(lines, "TOTAL 1221 Drug Enforcement")
    assert drug["fund_name"] == "Drug Enforcement" and drug["check"]["state"] == "exact"
    gf_row = int(gf["id"].rsplit("/r", 1)[1])
    after = [x for x in lines.values() if x["page"] == 114 and int(x["id"].rsplit("/r", 1)[1]) > gf_row]
    assert len(after) == 4 and all(x["fund_name"] == "Drug Enforcement" for x in after)
    assert {x["id"] for x in after} <= set(drug["scope_line_ids"])
    assert after[0]["heading_as_printed"] == "28420001 Drug Enforcement-Salaries"     # carried to p115
    sect = by_label(lines, "28420001 Drug Enforcem")
    assert sect["row_role"] == "total" and sect["check"]["state"] == "exact"
    assert all(x["fund_no"] is None for x in lines.values())


def test_fy2025_rows_after_the_last_fund_total_with_no_header_after_them_fail_the_book():
    with pytest.raises(BookLayoutError, match="rows after the last fund total"):
        read("fy2025-adopted", [116])


def test_fy2025_a_fund_that_opens_and_closes_on_one_page_is_named_by_its_total():
    _, lines, _ = read("fy2025-adopted", [129], mutate=drop(129, 125, 220))   # rows of a section begun on p. 128
    dental = by_label(lines, "TOTAL 2210 Dental Fund")
    assert dental["check"]["state"] == "exact" and dental["fund_name"] == "Dental Fund"
    assert {lines[i]["fund_name"] for i in dental["scope_line_ids"]} == {"Dental Fund"}
    assert by_label(lines, "TOTAL 2101 Parking Commissio")["fund_name"] == "Parking Commission"   # page header


def test_fy2025_a_page_that_starts_mid_section_and_ends_after_a_fund_total_fails_alone():
    with pytest.raises(BookLayoutError, match="rows after the last fund total"):
        read("fy2025-adopted", [114])


def test_fy2025_a_cut_fund_name_is_completed_from_a_header_of_another_book():
    words = drop(133, 125, 148)(words_of("fy2025-adopted", [133]))       # rows of a section begun on p. 132
    r25 = fin_budget.read_book(words, BOOK["fy2025-adopted"], RULES)
    veh = next(pl for pl in r25.lines if pl.label == "TOTAL 2240 Vehicle Replaceme")
    assert veh.fund_name == "Vehicle Replaceme" and veh.fund_from_total            # as cut on the page
    fin_budget.complete_cut_fund_names([r25])
    assert veh.fund_name == "Vehicle Replaceme" and veh.fund_name_from is None    # no full name read: kept
    assert all("fund_name_from" not in x for x in fin_budget.to_records(r25, RULES))
    r26 = fin_budget.read_book(words_of("fy2026-final", [138]), BOOK["fy2026-final"], RULES)
    fin_budget.complete_cut_fund_names([r25, r26])
    assert veh.fund_name == "Vehicle Replacement Fund" and veh.label == "TOTAL 2240 Vehicle Replaceme"
    # provenance/fund-name-cross-book: every completed line says which book the name came from and how it is printed
    marked = [x for x in fin_budget.to_records(r25, RULES) if x["fund_name"] == "Vehicle Replacement Fund"]
    assert marked and all(x["fund_name_from"] == {"book_id": "fy2026-final", "printed": "Vehicle Replaceme"}
                          for x in marked)
    assert all("fund_name_from" not in x for x in fin_budget.to_records(r26, RULES))
    lines = {x["id"]: x for x in fin_budget.to_records(r25, RULES)}
    fin_checks.reconcile(list(lines.values()), RULES.run_totals)
    v = by_label(lines, "TOTAL 2240 Vehicle Replaceme")
    assert v["check"]["state"] == "exact" and {lines[i]["fund_name"] for i in v["scope_line_ids"]} == \
        {"Vehicle Replacement Fund"}
    grand = by_label(lines, "GRAND TOTAL")
    assert (grand["fund_name"], grand["statement"]) == (None, "net")
    text = " ".join(x["label_as_printed"] for x in lines.values())
    assert "END OF REPORT" not in text and "Staff" not in text


def _gate_line(i, state=None, held=None, scope=(1,), cents=100):
    """Line r<i>; a total (state set) sums the lines r<n> for n in scope."""
    return {"id": f"b/p1/r{i}", "book_id": "b", "held": held, "cells": [{"cents": cents, "dollars": None}],
            "check": {"state": state, "per_cell": []} if state else None,
            "scope_line_ids": [f"b/p1/r{n}" for n in scope] if state else None}


@pytest.mark.parametrize("lines,ok", [
    ([_gate_line(1), _gate_line(2, "exact")], True),
    ([_gate_line(1), _gate_line(2, "does_not_add_up")], False),
    ([_gate_line(1), _gate_line(2, "not_checked")], False),
    ([_gate_line(1, held="column-align"), _gate_line(2, "exact")], False),
    ([_gate_line(1)], False),                                       # no printed total: nothing proves the reading
    ([_gate_line(1), _gate_line(3), _gate_line(2, "exact")], False),   # r3 has an amount no exact total sums
    ([_gate_line(1), _gate_line(3, cents=0), _gate_line(2, "exact")], True),   # a line of zeros proves nothing
    ([_gate_line(1), _gate_line(3), _gate_line(2, "exact"), _gate_line(4, "exact", scope=(3,))], True),
])
def test_a_glyph_decoded_book_is_kept_only_when_every_total_is_exact(lines, ok):
    problems = fin_facts.glyph_book_problems("b", lines)
    assert (problems == []) is ok
    assert all("(glyph-decode)" in p and p.startswith("book b: ") for p in problems)


def test_glyph_decode_problems_stop_the_build():
    from collector.fin_run import GUARD_KEYS
    assert fin_facts.GLYPH_KEY in GUARD_KEYS


def test_the_committed_glyph_table_has_one_drawing_per_amount_character():
    """glyph-table/no-invariant-test: every character an amount is made of (0-9 . , -) has exactly one drawing, in
    the face the amounts print in, and no face has two drawings for one character (an edit that maps a second
    drawing to a digit, or a digit's drawing to another digit, fails here before any book is read)."""
    import collections
    spec = next(b for b in fin_config.load_books(CITY).budget.books if b.glyph_map)
    glyphs = json.loads((fin_config.ROOT / spec.glyph_map).read_text(encoding="utf-8"))["glyphs"]
    pairs = collections.Counter((g["face"], g["char"]) for g in glyphs.values())
    assert [p for p, n in pairs.items() if n > 1] == []
    amount_chars = set("0123456789.,-")
    drawn = collections.Counter(g["char"] for g in glyphs.values() if g["char"] in amount_chars)
    assert drawn == {c: 1 for c in amount_chars}
    assert {g["face"] for g in glyphs.values() if g["char"] in amount_chars} == {"Lucida Console"}


# ------------------------------------------------------------------ fin-books build on a fake store
def three_books():
    """The city config without the glyph-mapped FY2025 book (its fake bytes cannot be decoded; it has tests below)."""
    import dataclasses
    cfg = fin_config.load_books(CITY)
    return dataclasses.replace(cfg, budget=dataclasses.replace(
        cfg.budget, books=tuple(b for b in cfg.budget.books if not b.glyph_map)))


def fake_store(tmp_path, skip=(), extra=None):
    """The three text-layer books (and `extra` {book id: words}) as fake files; -> (store, {sha256: words})."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    store = Store(tmp_path / "fin-manifest.json", root=tmp_path / "store", now=lambda: "2026-11-16T00:00:00+00:00")
    pages = {"fy2024-adopted": [50], "fy2026-final": [138], "fy2027-presented": [378, 379]}
    by_sha, extra = {}, extra or {}
    for spec in RULES.books:
        if spec.id in extra:
            e, _ = store.put(spec.url, b"%PDF-1.7 city " + spec.id.encode(), {}, {"kind": "budget_book",
                                                                                 "label": spec.title})
            by_sha[e["sha256"]] = extra[spec.id]
            continue
        if spec.id in skip or spec.glyph_map:
            continue
        e, _ = store.put(spec.url, b"%PDF-1.7 city " + spec.id.encode(), {}, {"kind": "budget_book",
                                                                             "label": spec.title})
        by_sha[e["sha256"]] = words_of(spec.id, pages[spec.id])
    store.save()
    return store, by_sha


def test_fin_books_build_writes_a_valid_city_file(tmp_path, monkeypatch):
    store, by_sha = fake_store(tmp_path)
    monkeypatch.setattr(fin_facts, "pdf_meta", lambda pdf, cfg, cache=None: {"pages": 9, "text_layer": "text",
                                                                              "creator": "Fixture Writer"})
    cfg = three_books()
    out, rep = tmp_path / "finance.json", tmp_path / "report.json"
    code = fin_books.cmd_build(store, cfg, out, rep, book_words=lambda pdf, first, last: by_sha[pdf.stem])
    assert code == 0
    fin = json.loads(out.read_text())
    from collector.fin_run import validate
    assert validate(fin) == []
    assert [b["id"] for b in fin["books"]] == ["fy2024-adopted", "fy2026-final", "fy2027-presented"]
    assert all(b["amount_unit"] == "cents" for b in fin["books"])
    assert fin["solicitations"] == [] and fin["documents"] == []
    report = json.loads(rep.read_text())
    assert report["budget"]["fy2027-presented"]["reconcile"]["exact"] == 11
    assert report["budget"]["fy2026-final"]["funds"] == ["Vehicle Replacement Fund"]
    assert report["books_not_read"] == []


def test_schema_requires_cents_on_every_cell_of_a_cents_file(tmp_path, monkeypatch):
    store, by_sha = fake_store(tmp_path)
    monkeypatch.setattr(fin_facts, "pdf_meta", lambda pdf, cfg, cache=None: {"pages": 9, "text_layer": "text",
                                                                              "creator": None})
    fin, _ = fin_books.build(store, three_books(), book_words=lambda pdf, first, last: by_sha[pdf.stem])
    from collector.fin_run import validate
    assert validate(fin) == []
    del fin["budget_lines"][0]["cells"][0]["cents"]
    assert any("'cents' is a required property" in e for e in validate(fin))


def _city_meta(monkeypatch):
    monkeypatch.setattr(fin_facts, "pdf_meta", lambda pdf, cfg, cache=None: {"pages": 9, "text_layer": "text",
                                                                              "creator": None})


def test_daily_build_keeps_the_committed_file_when_a_book_file_changed(tmp_path, monkeypatch):
    # city-books/daily-overwrite-unguarded: the city replaced a book's file; a person reviews the new reading first
    store, by_sha = fake_store(tmp_path)
    _city_meta(monkeypatch)
    cfg = three_books()
    out, rep = tmp_path / "finance.json", tmp_path / "report.json"

    def words(pdf, first, last):
        return by_sha[pdf.stem]
    assert fin_books.cmd_build(store, cfg, out, rep, keep_committed=True, book_words=words) == 0    # nothing yet
    committed = out.read_bytes()
    assert fin_books.cmd_build(store, cfg, out, rep, keep_committed=True, book_words=words) == 0    # same reading
    spec = BOOK["fy2024-adopted"]
    store.now = lambda: "2026-11-17T00:00:00+00:00"                                 # a later file at the same URL
    e, st = store.put(spec.url, b"%PDF-1.7 city replaced", {}, {"kind": "budget_book", "label": spec.title})
    store.save()
    by_sha[e["sha256"]] = words_of("fy2024-adopted", [50])
    code = fin_books.cmd_build(store, cfg, out, rep, keep_committed=True, book_words=words)
    assert code == fin_books.KEPT and out.read_bytes() == committed
    kept = json.loads(rep.read_text())["kept"]
    assert len(kept) == 1 and kept[0].startswith("book fy2024-adopted: source sha256 ")
    assert fin_books.cmd_build(store, cfg, out, rep, book_words=words) == 0      # by hand: the new reading is written
    assert out.read_bytes() != committed


def _stats_file(books):
    """A finance.json shape with, per book id: (sha, lines, held, does-not-add-up)."""
    fin = {"sources": [], "books": [], "budget_lines": []}
    for book_id, (sha, n, held, bad) in books.items():
        fin["sources"].append({"id": f"src-{sha[:12]}", "sha256": sha})
        fin["books"].append({"id": book_id, "source_id": f"src-{sha[:12]}"})
        for i in range(n):
            fin["budget_lines"].append({"book_id": book_id, "held": "column-align" if i < held else None,
                                        "check": {"state": "does_not_add_up"} if i < bad else None})
    return fin


@pytest.mark.parametrize("new,why", [
    ({"a": ("1" * 64, 5, 0, 0)}, []),
    ({"a": ("1" * 64, 6, 0, 0), "b": ("2" * 64, 3, 0, 0)}, []),                     # more lines, a new clean book
    ({"a": ("1" * 64, 4, 0, 0)}, ["book a: 4 lines, committed 5"]),
    ({"a": ("1" * 64, 5, 1, 0)}, ["book a: 1 held lines, committed 0"]),
    ({"a": ("1" * 64, 5, 0, 1)}, ["book a: 1 does not add up lines, committed 0"]),
    ({"a": ("1" * 64, 5, 0, 0), "b": ("2" * 64, 3, 0, 1)}, ["book b: 1 does not add up lines, committed 0"]),
    ({"b": ("2" * 64, 9, 0, 0)}, ["book a: in the committed file, not in the new build"]),
    ({"a": ("3" * 64, 5, 0, 0)}, ["book a: source sha256 333333333333 differs from the committed 111111111111"]),
])
def test_worse_than_committed(new, why):
    assert fin_books.worse_than_committed(_stats_file(new), _stats_file({"a": ("1" * 64, 5, 0, 0)})) == why


def test_fin_books_build_writes_nothing_when_a_book_is_missing(tmp_path, monkeypatch):
    store, by_sha = fake_store(tmp_path, skip=("fy2026-final",))
    monkeypatch.setattr(fin_facts, "pdf_meta", lambda pdf, cfg, cache=None: {"pages": 9, "text_layer": "text",
                                                                              "creator": None})
    out = tmp_path / "finance.json"
    rep = tmp_path / "r.json"
    rep.write_text('{"reconcile": "an earlier build"}')
    code = fin_books.cmd_build(store, three_books(), out, rep,
                               book_words=lambda pdf, first, last: by_sha[pdf.stem])
    assert code == 2 and not out.exists()
    report = json.loads(rep.read_text())                       # budget/exit2-stale-report: this build's reason
    assert "reconcile" not in report and any("fy2026-final" in g for g in report["stopped"]["guard"])


def test_the_glyph_decoded_book_is_written_only_when_every_total_is_exact(tmp_path, monkeypatch):
    _city_meta(monkeypatch)
    seen = []

    def decoded(pdf, spec, book_words, problems):          # stands in for the decoder process (test_type3_decode)
        seen.append(spec.id)
        return book_words(pdf, spec.first_page, spec.last_page)
    monkeypatch.setattr(fin_facts, "glyph_words", decoded)
    import dataclasses
    cfg = fin_config.load_books(CITY)
    out, rep = tmp_path / "finance.json", tmp_path / "report.json"
    # a book whose every total is exact (stand-in words: one whole report run of the FY2026 book, numbered as a page
    # of this book; its header prints no fund number, so the book's own fund_line is set aside here)
    stand_in = dataclasses.replace(cfg, budget=dataclasses.replace(cfg.budget, books=tuple(
        dataclasses.replace(b, fund_line=None) if b.glyph_map else b for b in cfg.budget.books)))
    store, by_sha = fake_store(tmp_path / "a", extra={"fy2025-adopted": page_words("city/fy2026_p138", 100)})
    assert fin_books.cmd_build(store, stand_in, out, rep, book_words=lambda pdf, f, la: by_sha[pdf.stem]) == 0
    assert seen == ["fy2025-adopted"]
    fin = json.loads(out.read_text())
    assert "fy2025-adopted" in [b["id"] for b in fin["books"]]
    # the real FY2025 pages 114-116: the General Fund total's rows start on p. 43, so it is not exact: nothing written
    out.unlink()
    real = drop(116, 385, 560)(words_of("fy2025-adopted", [114, 115, 116]))
    store, by_sha = fake_store(tmp_path / "b", extra={"fy2025-adopted": real})
    assert fin_books.cmd_build(store, cfg, out, rep, book_words=lambda pdf, f, la: by_sha[pdf.stem]) == 2
    assert not out.exists()
    guard = json.loads(rep.read_text())["stopped"]["guard"]
    assert len(guard) == 1 and guard[0].startswith("book fy2025-adopted: read through its glyph table") \
        and guard[0].endswith("(glyph-decode)")


def test_fetch_asks_the_polite_fetcher_for_every_book(tmp_path):
    seen = []

    class Fetcher:
        extra_denied, log = (), []

        def get(self, url):
            seen.append(url)
            return 200, b"%PDF-1.7 " + url.encode(), {"Content-Type": "application/pdf"}
    store = Store(tmp_path / "m.json", root=tmp_path / "s")
    log = fin_books.cmd_fetch(store, fin_config.load_books(CITY), fetcher=Fetcher(), progress=lambda *a, **k: None)
    assert log["stopped"] is None and not log["failures"]
    assert sorted(log["books"]) == ["fy2024-adopted", "fy2025-adopted", "fy2026-final", "fy2027-presented"]
    assert len(seen) == 4 and all(u.startswith("https://www.clarksvilletn.gov/") for u in seen)
    again = fin_books.cmd_fetch(store, fin_config.load_books(CITY), fetcher=Fetcher(), progress=lambda *a, **k: None)
    assert len(seen) == 4 and set(again["books"].values()) == {"cached"}     # a stored book is not asked for again


# ------------------------------------------------------------------ the daily run's step (collector run)
def _root(tmp_path):
    import shutil
    d = tmp_path / "config" / "localities" / "clarksville-tn"
    d.mkdir(parents=True)
    shutil.copy(CITY, d / "finance.yml")
    return tmp_path


def test_run_step_offline_with_no_stored_books_writes_nothing_and_never_raises(tmp_path, monkeypatch):
    from collector import fin_books
    monkeypatch.setenv("RECORDS_STORE", str(tmp_path / "store"))
    root = _root(tmp_path)
    log = {}
    out = fin_books.run_step(log, offline=True, root=root, progress=lambda *a, **k: None)
    assert out["clarksville-tn"]["fetch"] is None                 # offline: no request at all
    assert out["clarksville-tn"]["build"] == 2                    # book missing from the store: guard, nothing written
    assert not (root / "data" / "localities" / "clarksville-tn" / "finance.json").exists()
    assert log["city_books"] is out
    w = fin_books.warnings(log)                                   # exit 2 is a warning in the run log
    assert len(w) == 1 and "exit 2" in w[0] and "committed finance.json is kept" in w[0]


def test_run_step_keeps_a_worse_build_and_warns(tmp_path, monkeypatch):
    root = _root(tmp_path)
    fin = root / "data" / "localities" / "clarksville-tn" / "finance.json"
    fin.parent.mkdir(parents=True)
    fin.write_text("{}")

    def fake_build(store, cfg, finance_path, report_path, keep_committed=False, **kw):
        assert keep_committed                                     # the daily run always guards the committed file
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps({"kept": ["book fy2024-adopted: 1 held lines, committed 0"]}))
        return fin_books.KEPT
    monkeypatch.setattr(fin_books, "cmd_build", fake_build)
    log, said = {}, []
    out = fin_books.run_step(log, offline=True, root=root, progress=lambda *a, **k: said.append(a[0]))
    assert out["clarksville-tn"]["build"] == fin_books.KEPT and fin.read_text() == "{}"
    assert fin_books.warnings(log) == ["city books clarksville-tn: the new build reads worse than the committed "
                                       "finance.json, which is kept: book fy2024-adopted: 1 held lines, committed 0"]
    assert any(s.startswith("collector: WARNING city books clarksville-tn") for s in said)


def test_run_step_online_fetches_only_books_not_stored_and_survives_a_block(tmp_path, monkeypatch):
    from collector import fin_books
    from collector.fetch import HostBlocked
    monkeypatch.setenv("RECORDS_STORE", str(tmp_path / "store"))
    root = _root(tmp_path)
    asked = []

    class Blocked:
        extra_denied = ()
        log = []

        def get(self, url):
            asked.append(url)
            raise HostBlocked("blocked")

    out = fin_books.run_step({}, offline=False, fetcher=Blocked(), root=root, progress=lambda *a, **k: None)
    res = out["clarksville-tn"]
    assert len(asked) == 1 and res["fetch"]["stopped"]            # the first refusal ends the host's requests
    assert res["build"] == 2 and "error" not in res


def test_localities_lists_books_only_configs():
    from collector import fin_books
    assert fin_books.localities() == ["clarksville-tn"]


# ---------------------------------------------------- B1b row FB: config/fin-books-accepted.yml (I-in, ADR 0011 2a)

def _entry(book_id="a", sha="3" * 64, locality="clarksville-tn", **over):
    return {"locality": locality, "book_id": book_id, "source_sha256": sha, "listed_on": "2026-11-18",
            "reason": "The new file was checked page by page.", **over}


OLD_A = {"a": ("1" * 64, 5, 0, 0)}


@pytest.mark.parametrize("new,accepted,why", [
    # the city replaced book a's file, with fewer lines and a held line: the entry for the new file lets it through
    ({"a": ("3" * 64, 4, 1, 0)}, [_entry()], []),
    # no entry, or an entry for another sha256, another book or another locality: the reasons stand
    ({"a": ("3" * 64, 4, 0, 0)}, [], ["book a: source sha256 333333333333 differs from the committed 111111111111",
                                      "book a: 4 lines, committed 5"]),
    ({"a": ("3" * 64, 5, 0, 0)}, [_entry(sha="4" * 64)],
     ["book a: source sha256 333333333333 differs from the committed 111111111111"]),
    ({"a": ("3" * 64, 5, 0, 0)}, [_entry(book_id="b")],
     ["book a: source sha256 333333333333 differs from the committed 111111111111"]),
    ({"a": ("3" * 64, 5, 0, 0)}, [_entry(locality="montgomery-tn")],
     ["book a: source sha256 333333333333 differs from the committed 111111111111"]),
    # a stale entry: the stored book already has the listed file, so it is spent and changes nothing
    ({"a": ("1" * 64, 4, 0, 0)}, [_entry(sha="1" * 64)], ["book a: 4 lines, committed 5"]),
    # an entry for book a never clears another book's reasons
    ({"a": ("3" * 64, 5, 0, 0), "b": ("2" * 64, 3, 0, 1)}, [_entry()], ["book b: 1 does not add up lines, committed 0"]),
    # a book dropped from the new build has no new sha256 to match
    ({"b": ("2" * 64, 9, 0, 0)}, [_entry()], ["book a: in the committed file, not in the new build"]),
])
def test_worse_than_committed_with_accepted_readings(new, accepted, why):
    assert fin_books.worse_than_committed(_stats_file(new), _stats_file(OLD_A), accepted, "clarksville-tn") == why


def test_an_accepted_reading_needs_its_locality():
    new = _stats_file({"a": ("3" * 64, 5, 0, 0)})
    assert fin_books.worse_than_committed(new, _stats_file(OLD_A), [_entry()]) != []          # no locality: no entry


def test_an_accepted_entry_lets_a_replaced_book_through_once(tmp_path, monkeypatch):
    """The daily build keeps the stored file when the city replaces a book; an entry naming the new file's sha256 lets
    that reading through on the next run, is spent once it is stored, and does not admit a later replacement."""
    store, by_sha = fake_store(tmp_path)
    _city_meta(monkeypatch)
    cfg = three_books()
    out, rep = tmp_path / "finance.json", tmp_path / "report.json"

    def words(pdf, first, last):
        return by_sha[pdf.stem]

    def build(accepted):
        return fin_books.cmd_build(store, cfg, out, rep, keep_committed=True, book_words=words, accepted=accepted,
                                   locality="clarksville-tn")
    assert build([]) == 0
    committed = out.read_bytes()
    spec = BOOK["fy2024-adopted"]
    store.now = lambda: "2026-11-17T00:00:00+00:00"
    e, _ = store.put(spec.url, b"%PDF-1.7 city replaced", {}, {"kind": "budget_book", "label": spec.title})
    store.save()
    by_sha[e["sha256"]] = words_of("fy2024-adopted", [50])
    assert build([]) == fin_books.KEPT and out.read_bytes() == committed
    other = [_entry("fy2026-final", e["sha256"]), _entry("fy2024-adopted", "0" * 64)]
    assert build(other) == fin_books.KEPT and out.read_bytes() == committed          # another book, another file
    entry = [_entry("fy2024-adopted", e["sha256"])]
    assert build(entry) == 0 and out.read_bytes() != committed                       # through, once
    assert json.loads(rep.read_text())["accepted"] == ["fy2024-adopted"]
    stored = json.loads(out.read_text())
    assert e["sha256"] in {s["sha256"] for s in stored["sources"]}
    after = out.read_bytes()
    assert build(entry) == 0 and out.read_bytes() == after                           # spent: nothing to accept
    assert "accepted" not in json.loads(rep.read_text())
    store.now = lambda: "2026-11-18T00:00:00+00:00"                                  # the city replaces it again
    e2, _ = store.put(spec.url, b"%PDF-1.7 city replaced twice", {}, {"kind": "budget_book", "label": spec.title})
    store.save()
    by_sha[e2["sha256"]] = words_of("fy2024-adopted", [50])
    assert build(entry) == fin_books.KEPT and out.read_bytes() == after              # the old entry admits nothing


def test_run_step_reads_the_accepted_list_from_config(tmp_path, monkeypatch):
    root = _root(tmp_path)
    seen = {}

    def fake_build(store, cfg, finance_path, report_path, keep_committed=False, accepted=(), locality=None, **kw):
        seen.update(accepted=accepted, locality=locality)
        return 0
    monkeypatch.setattr(fin_books, "cmd_build", fake_build)
    fin_books.run_step({}, offline=True, root=root, progress=lambda *a, **k: None)
    assert seen == {"accepted": [], "locality": "clarksville-tn"}                    # no file: nothing accepted
    (root / "config" / "fin-books-accepted.yml").write_text(yaml.safe_dump([_entry()]), encoding="utf-8")
    fin_books.run_step({}, offline=True, root=root, progress=lambda *a, **k: None)
    assert seen["accepted"] == [_entry()]
    # an invalid list fails closed: no build, the stored file kept, a warning
    (root / "config" / "fin-books-accepted.yml").write_text(yaml.safe_dump([_entry(), _entry()]), encoding="utf-8")
    seen.clear()
    log = {}
    res = fin_books.run_step(log, offline=True, root=root, progress=lambda *a, **k: None)["clarksville-tn"]
    assert seen == {} and res["build"] is None and "ReviewedListError" in res["error"]
    assert fin_books.warnings(log)[0].endswith("the committed finance.json is kept")


def test_committed_fin_books_accepted_is_a_valid_list():
    from collector import reviewed_lists
    from collector.fin_books import ROOT
    p = ROOT / "config" / "fin-books-accepted.yml"
    assert yaml.safe_load(p.read_text(encoding="utf-8")) == []
    assert reviewed_lists.load(reviewed_lists.FIN_BOOKS_ACCEPTED) == []


@pytest.mark.parametrize("entry,ok", [
    (_entry(), True), (_entry(book_id="fy2024-adopted", locality="clarksville-tn"), True),
    (_entry(sha="3" * 63), False), (_entry(sha="3" * 65), False), (_entry(sha="A" * 64), False),
    (_entry(sha="3" * 12), False), (_entry(listed_on="2026-02-30"), False), (_entry(listed_on="18 Nov 2026"), False),
    (_entry(reason=" "), False), (_entry(locality="Clarksville TN"), False), (_entry(book_id=""), False),
    (_entry(allow_shrink=True), False), ({k: v for k, v in _entry().items() if k != "reason"}, False),
    ({k: v for k, v in _entry().items() if k != "source_sha256"}, False),
])
def test_fin_books_accepted_schema(entry, ok):
    from collector import reviewed_lists
    assert (reviewed_lists.problems(reviewed_lists.FIN_BOOKS_ACCEPTED, [entry]) == []) is ok


def test_fin_books_accepted_refuses_a_reading_listed_twice():
    from collector import reviewed_lists
    name = reviewed_lists.FIN_BOOKS_ACCEPTED
    assert reviewed_lists.problems(name, [_entry(), _entry(reason="Again.")]) == [
        "entry 1: lists the same locality, book_id, source_sha256 as entry 0"]
    assert reviewed_lists.problems(name, [_entry(), _entry(sha="4" * 64)]) == []          # two readings of one book
    assert reviewed_lists.problems(name, {"a": 1}) and reviewed_lists.problems(name, None)
