"""F10: the budget-book adapter (collector/fin_budget.py, architecture A2 adapter 3) on real page extracts of both books.

Fixtures are `pdftotext -bbox` extracts of single pages (collector/tests/fixtures/finance/fy2027_p*.bbox.html,
fy2025_p*.bbox.html). A test reads a "mini-book" of a few pages; a statement page with a fund line comes first where
the case needs one. Keys: column-kind/*, budget-reconcile/* (scopes), provenance/*.
"""
import copy

import pytest

from collector import fin_budget, fin_config
from collector.fin_budget import BookLayoutError
from collector.pdfwords import Word
from collector.tests.fin_fake import page_words

CFG = fin_config.load()
RULES = CFG.budget
BOOK = {b.id: b for b in RULES.books}


def read(book_id: str, pages, mutate=None):
    prefix = book_id.split("-")[0]
    words = [w for p in pages for w in page_words(f"{prefix}_p{p}", p)]
    if mutate:
        words = mutate(words)
    r = fin_budget.read_book(words, BOOK[book_id], RULES)
    return r, {x["id"]: x for x in fin_budget.to_records(r, RULES)}


def line(lines: dict, page: int, label: str, nth: int = 0) -> dict:
    hits = [x for x in lines.values() if x["page"] == page and x["label_as_printed"] == label]
    hits.sort(key=lambda x: int(x["id"].rsplit("/r", 1)[1]))
    return hits[nth]


def values(x: dict) -> list:
    return [c["dollars"] for c in x["cells"]]


# ------------------------------------------------------------------ config
def test_budget_config_loads_both_books():
    assert [b.id for b in RULES.books] == ["fy2027-approved", "fy2025-approved"]
    assert CFG.capital_fund == "171"
    assert RULES.page_titles["Statement of Proposed Expenditures"] == "expenditure"


@pytest.mark.parametrize("path", [("budget", "kind_words"), ("budget", "rows", "fund_line"), ("budget", "tags"),
                                  ("budget", "ignore_words"), ("budget", "year")])
def test_missing_budget_key_fails_loudly(path):
    import yaml
    raw = yaml.safe_load(fin_config.default_path().read_text(encoding="utf-8"))
    d = raw
    for k in path[:-1]:
        d = d[k]
    del d[path[-1]]
    with pytest.raises(fin_config.FinanceConfigError):
        fin_config.parse(raw)


def test_unknown_kind_in_config_fails():
    import yaml
    raw = yaml.safe_load(fin_config.default_path().read_text(encoding="utf-8"))
    raw["budget"]["kind_words"].append(["Estimate", "estimated"])
    with pytest.raises(fin_config.FinanceConfigError):
        fin_config.parse(raw)


# ------------------------------------------------------------------ amounts
@pytest.mark.parametrize("tok,dollars", [("-", 0), ("105", 105), ("1,310,282", 1310282), ("(9,106,000)", -9106000),
                                         ("(5)", -5), ("1.30", None), ("(71.40)", None), ("4.32%", None),
                                         ("1,23", None), ("(1,000", None), ("$5", None)])
def test_amount_tokens(tok, dollars):
    assert fin_budget.amount_dollars(tok) == dollars


# ------------------------------------------------------------------ headers and bands
def test_p36_header_two_lines_per_band():
    r, _ = read("fy2027-approved", [36])
    assert r.columns == [{"header_as_printed": "FY 2025 Actuals", "fiscal_year": 2025, "kind": "actual"},
                         {"header_as_printed": "FY 2026 Amended", "fiscal_year": 2026, "kind": "amended"},
                         {"header_as_printed": "FY 2027 Budget", "fiscal_year": 2027, "kind": "adopted"}]
    assert r.pages_read == [36]


def test_p105_header_fy_2025_actuals_on_one_line():
    r, lines = read("fy2027-approved", [105])
    assert [c["header_as_printed"] for c in r.columns] == ["FY 2025 Actuals", "FY 2026 Amended", "FY 2027 Budget"]
    tax = line(lines, 105, "CURRENT PROPERTY TAX")
    assert tax["account_code"] == "40110" and tax["fund_no"] == "171" and tax["statement"] == "revenue"
    assert [c["as_printed"] for c in tax["cells"]] == ["11,510,622", "12,754,000", "3,648,000"]
    assert values(tax) == [11510622, 12754000, 3648000]
    assert values(line(lines, 105, "TRUSTEE COLLECTIONS - BANKRUPT")) == [1604, 0, 0]      # "-" is 0 as printed


def test_unknown_kind_word_fails_the_book():
    def mutate(words):
        return [Word(w.page, w.x0, w.x1, w.y0, w.y1, "Estimate" if w.text == "Budget" else w.text) for w in words]
    with pytest.raises(BookLayoutError, match="Estimate"):
        read("fy2027-approved", [36], mutate)


def test_derived_columns_are_never_stored():
    _, lines = read("fy2027-approved", [36, 37])
    heads = {c["header_as_printed"] for x in lines.values() for c in x["cells"]}
    assert heads == {"FY 2025 Actuals", "FY 2026 Amended", "FY 2027 Budget"}
    assert all(len(x["cells"]) == 3 for x in lines.values())


def test_fy2025_book_two_digit_years_and_projection_column():
    r, lines = read("fy2025-approved", [31, 33, 36])
    assert r.columns == [{"header_as_printed": "FY 23 Actuals", "fiscal_year": 2023, "kind": "actual"},
                         {"header_as_printed": "FY 24 Amended", "fiscal_year": 2024, "kind": "amended"},
                         {"header_as_printed": "FY 25 Projection", "fiscal_year": 2025, "kind": "adopted"}]  # override
    assert all(x["edition"] == "approved" and x["book_id"] == "fy2025-approved" for x in lines.values())


def test_fy2025_row_printed_above_the_page_title_is_read_first():
    _, lines = read("fy2025-approved", [31, 33])
    first = lines["fy2025-approved/p33/r1"]
    assert first["account_code"] == "43380" and first["label_as_printed"] == "VENDING MACHINE COLLECTIONS"
    assert values(first) == [70322, 68000, 68000] and first["fund_no"] == "101"
    assert not any(x["label_as_printed"].startswith(("Montgomery", "For the")) for x in lines.values())


def test_blank_cell_stays_null():
    """Modelled on p. 103 (a row with no FY 2027 figure): drop the FY 2027 token of one p. 105 row."""
    def mutate(words):
        row_y = next(w.yc for w in words if w.text == "40125")
        return [w for w in words if not (abs(w.yc - row_y) < 3 and 508 < w.x1 < 560)]
    _, lines = read("fy2027-approved", [105], mutate)
    x = line(lines, 105, "TRUSTEE COLLECTIONS - BANKRUPT")
    assert [c["as_printed"] for c in x["cells"]] == ["1,604", "-", None]
    assert values(x) == [1604, 0, None] and x["held"] is None


def test_misaligned_or_non_amount_token_holds_the_line():
    def two_tokens(words):
        w = next(w for w in words if w.text == "11,510,622")
        return words + [Word(w.page, w.x0 - 60, w.x0 - 25, w.y0, w.y1, "12")]     # second token in the band
    _, lines = read("fy2027-approved", [105], two_tokens)
    x = line(lines, 105, "CURRENT PROPERTY TAX")
    assert x["held"] == "column-align" and values(x) == [None, None, None]
    assert x["cells"][0]["as_printed"] == "12 11,510,622"

    def shifted(words):
        return [Word(w.page, w.x0 - 6, w.x1 - 6, w.y0, w.y1, w.text) if w.text == "1,604" else w for w in words]
    _, lines = read("fy2027-approved", [105], shifted)
    assert line(lines, 105, "TRUSTEE COLLECTIONS - BANKRUPT")["held"] == "column-align"
    assert line(lines, 105, "CURRENT PROPERTY TAX")["held"] is None


# ------------------------------------------------------------------ row roles and scopes
def test_p33_section_totals_scope_their_section():
    _, lines = read("fy2027-approved", [30, 33])
    fees = line(lines, 33, "Total Fees Received")
    assert fees["row_role"] == "total" and fees["heading_as_printed"] == "Fees Received"
    assert [lines[i]["account_code"] for i in fees["scope_line_ids"]] == [
        "45510", "45520", "45540", "45550", "45560", "45580", "45590", "45610"]
    state = line(lines, 33, "Total State of Tennessee")
    assert len(state["scope_line_ids"]) == 21 and values(state) == [12690251, 14122548, 13095136]


def test_pp36_37_salaries_codeless_detail_and_subtotals_across_the_page_break():
    _, lines = read("fy2027-approved", [36, 37])
    sal = line(lines, 36, "Salaries & Benefits")
    assert sal["row_role"] == "detail" and sal["account_code"] is None and sal["department"] == "COUNTY COMMISSION"
    other = line(lines, 37, "Other Expenditures")                      # County Mayor's, its rows start on p. 36
    assert other["row_role"] == "subtotal" and other["department"] == "COUNTY MAYOR"
    pages = [lines[i]["page"] for i in other["scope_line_ids"]]
    assert pages[0] == 36 and pages[-1] == 37 and len(pages) == 17
    assert all(lines[i]["account_code"] for i in other["scope_line_ids"])         # Salaries & Benefits is not in it
    cap = line(lines, 37, "Capital Expenditures")
    assert [lines[i]["account_code"] for i in cap["scope_line_ids"]] == ["57110", "57180"]
    mayor = line(lines, 37, "Total COUNTY MAYOR")
    assert len(mayor["scope_line_ids"]) == 20 and sal["id"] not in mayor["scope_line_ids"]
    assert line(lines, 36, "Salaries & Benefits", 4)["id"] in mayor["scope_line_ids"]
    assert not set(other["scope_line_ids"]) - set(mayor["scope_line_ids"])


def test_pp107_108_projects_with_no_heading_and_repeated_truncated_labels():
    _, lines = read("fy2027-approved", [107, 108])
    gen = line(lines, 107, "Total GENERAL ADMINISTRATION PROJECT")
    assert gen["heading_from_total"] and gen["heading_as_printed"] == "GENERAL ADMINISTRATION PROJECT"
    assert [lines[i]["account_code"] for i in gen["scope_line_ids"]] == ["57070", "57150"]
    assert all(lines[i]["heading_from_total"] for i in gen["scope_line_ids"])
    eng = line(lines, 107, "Total GENERAL ADMINISTRATION PROJECT - ENGINEERING")
    assert not eng["heading_from_total"] and eng["heading_as_printed"].endswith("ENGINEERING SR 374")
    art = line(lines, 107, "Total GENERAL ADMINISTRATION PROJECT - PUBLIC ART")
    assert art["scope_line_ids"] == [] and values(art) == [95560, 16500, 0]
    lot = line(lines, 107, "Total GENERAL ADMINISTRATION PROJECT - PARKING LOT -")    # label "-" vs cell "-"
    assert [c["as_printed"] for c in lot["cells"]] == ["-", "34,911", "-"]
    lib = [x for x in lines.values() if x["label_as_printed"] == "Total GENERAL ADMINISTRATION PROJECT - LIBRARY"]
    assert len(lib) == 2 and len({x["id"] for x in lib}) == 2
    assert not set(lib[0]["scope_line_ids"]) & set(lib[1]["scope_line_ids"])
    food = line(lines, 108, "Total GENERAL ADMINISTRATION PROJECT - CDGB - FOOD")       # scope opens on p. 107
    assert [lines[i]["page"] for i in food["scope_line_ids"]] == [107, 107, 107]


def test_p28_reads_only_the_fund_balance_block_with_the_next_statement_pages_fund():
    r, lines = read("fy2027-approved", [28, 30])
    fb = [x for x in lines.values() if x["page"] == 28]
    assert [x["label_as_printed"] for x in fb] == [
        "Estimated Beginning Fund Balance July 1", "Estimated Ending Fund Balance June 30",
        "Estimated Nonspendable Fund Balance", "Estimated Restricted Fund Balance", "Estimated Committed Fund Balance",
        "Estimated Assigned Fund Balance", "Estimated Unassigned Fund Balance", "Total Fund Balance"]
    assert all(x["statement"] == "fund_balance" and x["tags"] == ["available_funds"] for x in fb)
    assert {x["fund_no"] for x in fb} == {"101"}
    total = fb[-1]
    assert [lines[i]["label_as_printed"] for i in total["scope_line_ids"]] == [x["label_as_printed"] for x in fb[2:7]]
    assert [c["header_as_printed"] for c in fb[0]["cells"]] == [
        "FY 2025 Actuals", "FY 2026 Amended Budget", "FY 2026 Projections", "FY 2027 Budget"]
    assert 28 in r.pages_read

    def other_fund(words):           # the fund comes from the next statement page, not p. 28's own fund line
        return [Word(w.page, w.x0, w.x1, w.y0, w.y1, "999") if (w.page == 30 and w.text == "101") else w
                for w in words]
    _, lines = read("fy2027-approved", [28, 30], other_fund)
    assert {x["fund_no"] for x in lines.values() if x["page"] == 28} == {"999"}
    with pytest.raises(BookLayoutError, match="no statement page after"):
        read("fy2027-approved", [28])


def test_p114_transfers_tagged_and_fund_total_scopes_the_fund():
    _, lines = read("fy2027-approved", [107, 114])
    tr = line(lines, 114, "TRANSFERS TO OTHER FUNDS")
    assert tr["tags"] == ["transfer"] and tr["account_code"] == "55900"
    assert line(lines, 114, "Other Expenditures", 1)["tags"] == ["transfer"]
    assert line(lines, 114, "Total OPERATING TRANSFERS")["tags"] == ["transfer"]
    fund = line(lines, 114, "Total Expenditures CAPITAL PROJECTS FUND 171")
    assert fund["tags"] == [] and fund["heading_as_printed"] is None and fund["department"] is None
    details = [x["id"] for x in lines.values() if x["row_role"] == "detail"]
    assert sorted(fund["scope_line_ids"]) == sorted(details)
    assert not any(x["tags"] for x in lines.values() if x["page"] == 107)


def test_non_revenue_and_transfer_tags_on_revenue_page():
    _, lines = read("fy2027-approved", [105])
    ops = line(lines, 105, "OPERATING TRANSFERS")
    assert ops["tags"] == ["transfer", "non_revenue"]                # 49800, under Other Sources (Non-Revenue)
    assert line(lines, 105, "BOND PROCEEDS")["tags"] == ["non_revenue"]
    assert line(lines, 105, "CURRENT PROPERTY TAX")["tags"] == []
    total = line(lines, 105, "Total Revenues")
    assert ops["id"] in total["scope_line_ids"]                       # tagged lines stay in their printed totals


def test_every_line_has_provenance_and_positional_id():
    _, lines = read("fy2027-approved", [36, 37])
    for lid, x in lines.items():
        assert lid == f"fy2027-approved/p{x['page']}/r{lid.rsplit('/r', 1)[1]}" and x["page"] in (36, 37)
        assert x["book_id"] == "fy2027-approved" and x["edition"] == "approved"
        assert all(c["header_as_printed"] and c["fiscal_year"] and c["kind"] for c in x["cells"])


def test_scope_partition_each_detail_line_in_one_scope_per_level():
    r, lines = read("fy2027-approved", [36, 37, 107, 108])
    by_level: dict = {}
    for pl in r.lines:
        if pl.level:
            by_level.setdefault(pl.level, set()).add(tuple(pl.scope_line_ids))
    for level, scopes in by_level.items():
        seen: dict = {}
        for scope in scopes:
            for i in scope:
                assert lines[i]["row_role"] == "detail"
                assert seen.setdefault(i, scope) == scope, (level, i)


def test_deterministic():
    a = fin_budget.to_records(read("fy2027-approved", [36, 37])[0], RULES)
    b = fin_budget.to_records(read("fy2027-approved", [36, 37])[0], RULES)
    assert a == b and copy.deepcopy(a) == a


# ------------------------------------------------------------------ per-book column kinds (column-kind/budget-year-kind)
def test_fy2025_budget_year_column_is_adopted_and_keeps_its_header():
    from collector.tests.fin_fake import CFG as FCFG, book_words
    books = {b.id: b for b in FCFG.budget.books}
    r25 = fin_budget.read_book(book_words("fy2025-approved"), books["fy2025-approved"], FCFG.budget)
    col = next(c for c in r25.columns if c["fiscal_year"] == 2025)
    assert col == {"header_as_printed": "FY 25 Projection", "fiscal_year": 2025, "kind": "adopted"}
    r27 = fin_budget.read_book(book_words("fy2027-approved"), books["fy2027-approved"], FCFG.budget)
    assert {"header_as_printed": "FY 2026 Projections", "fiscal_year": 2026, "kind": "projected"} in r27.columns


def test_an_override_that_matches_no_header_fails_the_book():
    import dataclasses

    from collector.tests.fin_fake import CFG as FCFG, book_words
    spec = next(b for b in FCFG.budget.books if b.id == "fy2025-approved")
    bad = dataclasses.replace(spec, kind_overrides=(("FY 25 Projected", "adopted"),))
    with pytest.raises(fin_budget.BookLayoutError, match="kind_overrides"):
        fin_budget.read_book(book_words("fy2025-approved"), bad, FCFG.budget)


# ------------------------------------------------------------------ derived bands (column-kind/derived-band-spill)
def test_a_value_spilled_into_a_derived_band_holds_the_line():
    """The FY 2027 "-" of one p. 105 row printed 30 pt right lands in the Budgeted Difference band: its own cell would
    read blank, so the line is held (derived-spill) and nothing of it is shown as a value."""
    def spill(words):
        row_y = next(w.yc for w in words if w.text == "40125")
        return [Word(w.page, w.x0 + 30, w.x1 + 30, w.y0, w.y1, w.text) if abs(w.yc - row_y) < 3 and 540 < w.x1 < 560
                else w for w in words]
    _, lines = read("fy2027-approved", [105], spill)
    x = line(lines, 105, "TRUSTEE COLLECTIONS - BANKRUPT")
    assert x["held"] == fin_budget.HELD_DERIVED and values(x) == [None, None, None]
    assert x["cells"][2]["as_printed"] is None
    assert line(lines, 105, "CURRENT PROPERTY TAX")["held"] is None


def test_a_non_number_or_off_edge_token_in_a_derived_band_holds_the_line():
    def word_in_percent(words):
        return [Word(w.page, w.x0, w.x1, w.y0, w.y1, "n/a") if w.text == "(71.40)" else w for w in words]
    _, lines = read("fy2027-approved", [105], word_in_percent)
    assert line(lines, 105, "CURRENT PROPERTY TAX")["held"] == fin_budget.HELD_DERIVED

    def off_edge(words):
        return [Word(w.page, w.x0 - 8, w.x1 - 8, w.y0, w.y1, w.text) if w.text == "(9,106,000)" else w for w in words]
    _, lines = read("fy2027-approved", [105], off_edge)
    assert line(lines, 105, "CURRENT PROPERTY TAX")["held"] == fin_budget.HELD_DERIVED


def test_derived_band_forms_and_real_pages_hold_nothing():
    for tok in ("(1,234)", "(.50)", "-3.10%", "12.50", "9,999.99", "100.00"):
        assert fin_budget.DERIVED.match(tok), tok
    for tok in ("n/a", ".", "(12", "12,34", "1.2.3"):
        assert not fin_budget.DERIVED.match(tok), tok
    for book, pages in (("fy2027-approved", [36, 37, 105, 107, 108]), ("fy2025-approved", [31, 33, 36, 98, 99, 103])):
        _, lines = read(book, pages)
        assert not any(x["held"] for x in lines.values()), book
