"""F11 and F12: subtotal reconciliation and the edition compare (collector/fin_checks.py, architecture A4).

Real cases on page extracts of the FY2027 book; synthetic lines for the edges. Keys: budget-reconcile/*,
budget-edition/*. The committed data/finance.json is checked too: every check matches its scope, the scopes partition.
"""
import ast
import copy
import json
from pathlib import Path

import pytest

from collector import fin_budget, fin_checks, fin_config
from collector.tests.fin_fake import page_words

ROOT = Path(__file__).resolve().parents[2]
CFG = fin_config.load()
BOOK = {b.id: b for b in CFG.budget.books}


def lines_of(pages, book_id="fy2027-approved"):
    words = [w for p in pages for w in page_words(f"{book_id.split('-')[0]}_p{p}", p)]
    recs = fin_budget.to_records(fin_budget.read_book(words, BOOK[book_id], CFG.budget), CFG.budget)
    counts = fin_checks.reconcile(recs)
    return {x["id"]: x for x in recs}, counts


def total(lines, label):
    return next(x for x in lines.values() if x["label_as_printed"] == label)


def diffs(x):
    return [pc["diff"] for pc in x["check"]["per_cell"]]


# ------------------------------------------------------------------ real cases (AC-F2)
def test_p36_county_commission_exact():
    lines, _ = lines_of([36])
    x = total(lines, "Total COUNTY COMMISSION")
    assert x["check"]["state"] == "exact" and diffs(x) == [0, 0, 0] and len(x["scope_line_ids"]) == 10
    assert [pc["printed"] for pc in x["check"]["per_cell"]] == [376605, 449008, 466993]


def test_p37_county_mayor_within_rounding():
    lines, _ = lines_of([36, 37])
    x = total(lines, "Total COUNTY MAYOR")
    assert x["check"]["state"] == "within_rounding" and len(x["scope_line_ids"]) == 20
    assert [abs(d) for d in diffs(x)] == [1, 0, 0]
    assert x["check"]["per_cell"][0] == {"printed": 867751, "sum": 867752, "diff": -1}     # printed value unchanged


def test_p107_public_art_total_with_no_lines_does_not_add_up():
    lines, _ = lines_of([107, 108])
    x = total(lines, "Total GENERAL ADMINISTRATION PROJECT - PUBLIC ART")
    assert x["scope_line_ids"] == [] and x["check"]["state"] == "does_not_add_up"
    assert x["check"]["per_cell"][0] == {"printed": 95560, "sum": 0, "diff": 95560}


def test_p47_trustees_office_amended_does_not_add_up():
    lines, _ = lines_of([36, 47])                       # p. 36 gives the fund line; the section opens on p. 47
    x = total(lines, "Total COUNTY TRUSTEES OFFICE")
    assert x["check"]["state"] == "does_not_add_up" and abs(diffs(x)[1]) == 3900
    assert abs(diffs(x)[0]) <= fin_checks.rounding_bound(len(x["scope_line_ids"]))   # only the amended cell is off
    assert x["cells"][1]["dollars"] == 1226777


def test_run_report_counts_every_state():
    lines, counts = lines_of([36, 37, 47, 107, 108])
    assert counts == fin_checks.reconcile_counts(list(lines.values()))
    assert all(counts[s] > 0 for s in fin_checks.RECONCILE_STATES if s != fin_checks.NOT_CHECKED)
    assert counts[fin_checks.NOT_CHECKED] == 0                  # nothing held on these pages
    assert sum(counts.values()) == sum(1 for x in lines.values() if x["row_role"] != "detail")


# ------------------------------------------------------------------ rule edges
def cell(d, kind="actual", fy=2025):
    return {"header_as_printed": "FY", "fiscal_year": fy, "kind": kind, "as_printed": None if d is None else str(d),
            "dollars": d}


def mk(lid, role, dollars, scope=(), held=None, book="b1", **kw):
    x = {"id": lid, "book_id": book, "row_role": role, "cells": [cell(d) for d in dollars], "scope_line_ids": list(scope),
         "held": held, "check": None, "edition_differs": [], "fund_no": "101", "account_code": None,
         "label_as_printed": lid, "heading_as_printed": "H", "heading_from_total": False}
    x.update(kw)
    return x


@pytest.mark.parametrize("n,bound", [(0, 0), (1, 1), (2, 1), (3, 2), (20, 10), (126, 63)])
def test_rounding_bound_is_half_a_dollar_per_line(n, bound):
    assert fin_checks.rounding_bound(n) == bound


@pytest.mark.parametrize("printed,parts,state", [
    ([10], [[4], [6]], "exact"),
    ([11], [[4], [6]], "within_rounding"),            # n 2, bound 1
    ([12], [[4], [6]], "does_not_add_up"),
    ([None], [[None], [None]], "exact"),              # blank total, blank lines: nothing to add
    ([None], [[4], [None]], "does_not_add_up"),       # blank total, a line has dollars
    ([4], [[4], [None]], "exact"),                    # a blank line is not added
])
def test_check_states(printed, parts, state):
    lines = [mk(f"b1/p1/r{i}", "detail", d) for i, d in enumerate(parts, start=1)]
    t = mk("b1/p1/r9", "total", printed, [x["id"] for x in lines])
    fin_checks.reconcile(lines + [t])
    assert t["check"]["state"] == state


@pytest.mark.parametrize("printed,parts,state", [
    ([5], [[4], [0], [0]], "within_rounding"),           # "0" is printed (may be rounded): n 3, bound 2
    ([6], [[4], [0], [0]], "within_rounding"),
    ([5], [[4], ["-"], ["-"]], "within_rounding"),       # "-" is an exact 0: n 1, bound 1
    ([6], [[4], ["-"], ["-"]], "does_not_add_up"),
    ([1], [["-"], ["-"]], "does_not_add_up"),            # n 0, bound 0
])
def test_rounding_n_counts_printed_amounts_per_column(printed, parts, state):
    """budget-reconcile/rounding-n-counts-dashes: a "-" cell (exact 0) and a blank cell do not widen the bound."""
    def dash(d):
        return {"header_as_printed": "FY", "fiscal_year": 2025, "kind": "actual", "as_printed": "-", "dollars": 0}
    lines = []
    for i, d in enumerate(parts, start=1):
        x = mk(f"b1/p1/r{i}", "detail", [0 if d == ["-"] else d[0]])
        if d == ["-"]:
            x["cells"] = [dash(0)]
        lines.append(x)
    t = mk("b1/p1/r9", "total", printed, [x["id"] for x in lines])
    fin_checks.reconcile(lines + [t])
    assert t["check"]["state"] == state


def test_held_scope_line_holds_the_total():
    a, b = mk("b1/p1/r1", "detail", [None], held="column-align"), mk("b1/p1/r2", "detail", [6])
    t = mk("b1/p1/r3", "total", [6], [a["id"], b["id"]])
    fin_checks.reconcile([a, b, t])
    assert t["held"] == fin_checks.SCOPE_HELD and t["check"]["state"] == fin_checks.NOT_CHECKED
    assert a["check"] is None and t["cells"][0]["dollars"] == 6


def test_held_totals_are_not_checked_and_not_counted_as_book_errors():
    """budget-reconcile/held-counted-as-book-error: a held total (or one over a held line) is not_checked, counted
    apart; coverage n_flag counts does_not_add_up only."""
    a = mk("b1/p1/r1", "detail", [4])
    t = mk("b1/p1/r2", "total", [None], [a["id"]], held="column-align")
    b = mk("b1/p1/r3", "detail", [None], held="column-align")
    u = mk("b1/p1/r4", "total", [9], [b["id"]])
    e = mk("b1/p1/r5", "total", [9], [])                         # empty scope: still a book error
    lines = [a, t, b, u, e]
    counts = fin_checks.reconcile(lines)
    assert t["check"]["state"] == u["check"]["state"] == fin_checks.NOT_CHECKED
    assert e["check"]["state"] == "does_not_add_up"
    assert counts == {"exact": 0, "within_rounding": 0, "does_not_add_up": 1, "not_checked": 2}
    cov = fin_checks.coverage({"solicitations": [], "documents": [], "budget_lines": lines, "books": []})
    assert cov["n_flag"] == 1


def test_no_sum_of_budget_lines_outside_fin_checks():
    """Lint (budget-reconcile/*): no `sum(` over dollars or cells in collector/ or sitegen/ code but fin_checks.py."""
    offenders = []
    for path in sorted((ROOT / "collector").glob("*.py")) + sorted((ROOT / "sitegen").glob("*.py")):
        if path.name == "fin_checks.py":
            continue
        src = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("sum", "fsum"):
                seg = ast.get_source_segment(src, node) or ""
                if any(k in seg for k in ("dollars", "cells", "budget_lines", "scope_line_ids")):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []
    assert "sum(" not in (ROOT / "collector" / "fin_budget.py").read_text(encoding="utf-8")


# ------------------------------------------------------------------ edition compare (F12)
def two_books(d1, d2, **kw):
    a = mk("b1/p1/r1", "detail", [d1], account_code="40110", **kw)
    b = mk("b2/p5/r3", "detail", [d2], account_code="40110", book="b2", **kw)
    return a, b


def test_same_key_different_dollars_marks_both_and_changes_neither():
    a, b = two_books(100, 120)
    before = copy.deepcopy([a["cells"], b["cells"]])
    assert fin_checks.edition_compare([a, b]) == [("b1/p1/r1", "b2/p5/r3")]
    assert a["edition_differs"] == ["b2/p5/r3"] and b["edition_differs"] == ["b1/p1/r1"]
    assert [a["cells"], b["cells"]] == before and a["book_id"] != b["book_id"]


def test_same_dollars_or_other_kind_or_same_book_is_not_marked():
    a, b = two_books(100, 100)
    assert fin_checks.edition_compare([a, b]) == [] and not a["edition_differs"]
    a, b = two_books(100, 120)
    b["cells"][0]["kind"] = "projected"                          # FY2025 actual vs FY2025 projection: not one thing
    assert fin_checks.edition_compare([a, b]) == []
    a, b = two_books(100, 120)
    b["book_id"] = "b1"
    assert fin_checks.edition_compare([a, b]) == []


def test_ambiguous_truncated_or_held_lines_are_not_compared():
    a, b = two_books(100, 120)
    c = copy.deepcopy(b)
    c["id"] = "b2/p5/r4"                                          # the key repeats in book b2: ambiguous
    assert fin_checks.edition_compare([a, b, c]) == []
    a, b = two_books(100, 120, heading_from_total=True)
    assert fin_checks.edition_compare([a, b]) == []
    a, b = two_books(100, 120)
    b["held"] = "column-align"
    assert fin_checks.edition_compare([a, b]) == []


# ------------------------------------------------------------------ the committed data
@pytest.fixture(scope="module")
def committed():
    path = ROOT / "data" / "finance.json"
    if not path.is_file():
        pytest.skip("no data/finance.json")
    fin = json.loads(path.read_text(encoding="utf-8"))
    if not fin["budget_lines"]:
        pytest.skip("no budget lines built yet")
    return fin


def test_committed_checks_match_their_scope_and_counts(committed):
    by = {x["id"]: x for x in committed["budget_lines"]}
    for x in by.values():
        if x["row_role"] == "detail":
            assert x["check"] is None and x["scope_line_ids"] == []
            continue
        again = fin_checks.check_total(x, [by[i] for i in x["scope_line_ids"]])
        assert again == x["check"], x["id"]
        assert all(by[i]["row_role"] == "detail" and by[i]["book_id"] == x["book_id"] for i in x["scope_line_ids"])
    assert committed["coverage"]["n_flag"] == fin_checks.reconcile_counts(committed["budget_lines"])["does_not_add_up"]


def test_committed_scopes_never_double_count(committed):
    """Per book and role, a detail line is in at most one subtotal scope, one section-total scope and one fund-total
    scope (a fund's "Total Revenues" and "Total Revenues <fund>" print the same scope twice)."""
    seen: dict = {}
    for x in committed["budget_lines"]:
        if x["row_role"] == "detail":
            continue
        fund_level = any(p.match(x["label_as_printed"]) for p in CFG.budget.fund_totals)
        level = "subtotal" if x["row_role"] == "subtotal" else ("fund" if fund_level else "section")
        scope = tuple(x["scope_line_ids"])
        for i in scope:
            assert seen.setdefault((level, i), scope) == scope, (level, i, x["id"])


def test_committed_lines_carry_edition_and_tags(committed):
    lines = committed["budget_lines"]
    assert {x["edition"] for x in lines} == {"approved"}
    assert {x["book_id"] for x in lines} == set(BOOK)
    assert any("transfer" in x["tags"] for x in lines) and any("available_funds" in x["tags"] for x in lines)
    assert all(x["tags"] == ["available_funds"] for x in lines if x["statement"] == "fund_balance")
    assert [x["id"] for x in lines] == sorted(x["id"] for x in lines)


def test_committed_ids_sort_numerically_into_book_order(committed):
    """The frontend orders lines by (book_id, page, r) parsed from the id (schema line_id); that order puts every
    subtotal and total after all of its scope lines, as printed."""
    def key(lid):
        book, page, row = lid.split("/")
        return book, int(page[1:]), int(row[1:])
    lines = committed["budget_lines"]
    assert all(key(x["id"])[1] == x["page"] for x in lines)
    pos = {x["id"]: n for n, x in enumerate(sorted(lines, key=lambda x: key(x["id"])))}
    assert all(pos[i] < pos[x["id"]] for x in lines for i in x["scope_line_ids"])


# ------------------------------------------------------------------ subtotal scope by code class (FY2025 capital fund)
def test_fy2025_p103_capital_subtotal_adds_only_capital_codes():
    """budget-reconcile/subtotal-scope-class: "Capital Expenditures" under a 53990 service row and two 57xxx rows adds
    the 57xxx rows only, so the book's printed subtotal is exact; the section total still adds all three."""
    lines, _ = lines_of([98, 99, 103], "fy2025-approved")
    sub, tot = lines["fy2025-approved/p103/r31"], lines["fy2025-approved/p103/r32"]
    assert sub["label_as_printed"] == "Capital Expenditures"
    assert sub["scope_line_ids"] == ["fy2025-approved/p103/r29", "fy2025-approved/p103/r30"]
    assert lines["fy2025-approved/p103/r28"]["account_code"] == "53990"
    assert sub["check"]["state"] == "exact" and diffs(sub) == [0, 0, 0]
    assert tot["check"]["state"] == "exact" and len(tot["scope_line_ids"]) == 3


def test_fy2025_p99_capital_subtotals_stay_flagged_as_printed():
    """Real book errors stay flagged: p. 99 prints a Capital Expenditures subtotal (95 / 99,905 / 200,000) under a lone
    53990 row (no capital line: empty scope), and another (r35) that its two capital lines do not add up to."""
    lines, _ = lines_of([98, 99, 103], "fy2025-approved")
    r17, r35 = lines["fy2025-approved/p99/r17"], lines["fy2025-approved/p99/r35"]
    assert r17["scope_line_ids"] == [] and r17["check"]["state"] == "does_not_add_up"
    assert [pc["printed"] for pc in r17["check"]["per_cell"]] == [95, 99905, 200000]
    assert r35["scope_line_ids"] == ["fy2025-approved/p99/r33", "fy2025-approved/p99/r34"]
    assert r35["check"]["state"] == "does_not_add_up"


def test_other_expenditures_subtotal_skips_a_capital_row():
    """Mixed classes the other way: a 57xxx row directly above "Other Expenditures" is not in its scope."""
    rules = CFG.budget
    assert rules.subtotal_labels["Other Expenditures"].fullmatch("53990")
    assert not rules.subtotal_labels["Other Expenditures"].fullmatch("57060")
    assert rules.subtotal_labels["Capital Expenditures"].fullmatch("57060")
    assert not rules.subtotal_labels["Capital Expenditures"].fullmatch("53990")
