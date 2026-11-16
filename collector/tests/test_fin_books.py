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
    assert [x.id for x in b.books] == ["fy2024-adopted", "fy2026-final", "fy2027-presented"]
    assert [x["id"] for x in b.books_not_read] == ["fy2025-adopted"]
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
    cfg["budget"]["books_not_read"][0]["id"] = "fy2024-adopted"
    with pytest.raises(FinanceConfigError, match="both read and not read"):
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
    counts = fin_checks.reconcile(lines)
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


def test_empty_scope_of_zeros_is_exact_and_of_values_is_not():
    cell = {"header_as_printed": "x", "fiscal_year": 2027, "kind": "actual", "as_printed": ".00", "dollars": None,
            "cents": 0}
    zero = {"cells": [cell], "held": None}
    assert fin_checks.check_total(zero, [])["state"] == "exact"
    assert fin_checks.check_total({"cells": [dict(cell, cents=5, as_printed=".05")], "held": None},
                                  [])["state"] == "does_not_add_up"


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


# ------------------------------------------------------------------ fin-books build on a fake store
def fake_store(tmp_path, skip=()):
    store = Store(tmp_path / "fin-manifest.json", root=tmp_path / "store", now=lambda: "2026-11-16T00:00:00+00:00")
    pages = {"fy2024-adopted": [50], "fy2026-final": [138], "fy2027-presented": [378, 379]}
    by_sha = {}
    for spec in RULES.books:
        if spec.id in skip:
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
    cfg = fin_config.load_books(CITY)
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
    assert [b["id"] for b in report["books_not_read"]] == ["fy2025-adopted"]


def test_fin_books_build_writes_nothing_when_a_book_is_missing(tmp_path, monkeypatch):
    store, by_sha = fake_store(tmp_path, skip=("fy2026-final",))
    monkeypatch.setattr(fin_facts, "pdf_meta", lambda pdf, cfg, cache=None: {"pages": 9, "text_layer": "text",
                                                                              "creator": None})
    out = tmp_path / "finance.json"
    code = fin_books.cmd_build(store, fin_config.load_books(CITY), out, tmp_path / "r.json",
                               book_words=lambda pdf, first, last: by_sha[pdf.stem])
    assert code == 2 and not out.exists()


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
