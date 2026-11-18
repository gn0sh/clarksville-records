"""The general fund dollar (docs/architecture/finance-contracts.md 11; sitegen/dollar_split.py): on the county's and
the city's Finance index, how each dollar of the general fund budget splits across departments, from the adopted
column of one book. Problem-key families: dollar-split/*, budget-reconcile/*, provenance/*, neutrality/*."""
import html as html_mod
import json
import re
from fractions import Fraction

import pytest

from collector import fin_checks
from conftest import ROOT
from sitegen import budget_views, config, dollar_split, fin_views
from sitegen.build import build

COUNTY_FIN = ROOT / "data" / "finance.json"
CITY_FIN = ROOT / "data" / "localities" / "clarksville-tn" / "finance.json"
T = config.FIN_TEXT["dollar"]


def budget(path, **kw):
    fin = json.loads(path.read_text(encoding="utf-8"))
    return fin, budget_views.Budget(fin_views.Finance(fin, []), None, **kw)


@pytest.fixture(scope="module")
def county():
    fin, bg = budget(COUNTY_FIN)
    return fin, dollar_split.split(bg, dollar_split.load("montgomery-tn"))


@pytest.fixture(scope="module")
def city():
    fin, bg = budget(CITY_FIN, prefix="city/", text=config.FIN_TEXT["budget_city"])
    return fin, dollar_split.split(bg, dollar_split.load("clarksville-tn"))


def lines_by_id(fin):
    return {x["id"]: x for x in fin["budget_lines"]}


def cell(line, header, cents):
    c = next(c for c in line["cells"] if c["header_as_printed"] == header)
    return c["cents"] if cents else c["dollars"]


def members(d):
    """Every printed department total the split uses, in the order shown (Other's in its list)."""
    return [m for r in d["rows"] for m in r["members"]]


# ---- the rounding (unit) -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("amounts", [[1, 1, 1], [50, 30, 20], [995, 3, 1, 1], [1] * 7, [333, 333, 334],
                                     [6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 4], [1, 0, 99], [100]])
def test_cents_add_up_to_100_and_each_is_within_one_cent(amounts):
    total = sum(amounts)
    cents, nearest_sum, moved = fin_checks.cents_of_dollar(amounts, total)
    assert sum(cents) == 100
    for a, c in zip(amounts, cents):
        assert abs(c - Fraction(100 * a, total)) < 1
    assert nearest_sum == sum((200 * a + total) // (2 * total) for a in amounts)   # nearest cent, a half rounds up
    assert len(moved) == abs(nearest_sum - 100)


def test_half_a_cent_or_more_is_never_shown_as_zero():
    # four shares of 0.6 cents round up to 1 each; the two shares rounded up (48.8 -> 49) give the extra cents back
    amounts = [6] * 4 + [488, 488]
    cents, nearest_sum, moved = fin_checks.cents_of_dollar(amounts, 1000)
    assert cents == [1, 1, 1, 1, 48, 48] and nearest_sum == 102 and moved == [4, 5]


def test_no_split_that_would_break_the_one_cent_rule():
    # 15 shares of 0.6 cents make 106 cents with one exact 91: no share can give a cent back within one cent
    with pytest.raises(ValueError, match="too few shares"):
        fin_checks.cents_of_dollar([6] * 15 + [910], 1000)


@pytest.mark.parametrize("amounts", [[1130, 140, 369, 390, 40, 31], [1, 1, 1], [3, 5, 1992], [1] * 7, [995, 3, 1, 1],
                                     [6] * 15 + [910], [1, 0, 99]])
def test_tenths_add_up_to_1000_and_each_is_within_a_tenth(amounts):
    """The property tax dollar's rounding (fin_checks.tenths_of_dollar): largest remainder at tenths of a cent."""
    total = sum(amounts)
    tenths, nearest_sum, moved = fin_checks.tenths_of_dollar(amounts, total)
    assert sum(tenths) == 1000
    nearest = [(2000 * a + total) // (2 * total) for a in amounts]
    assert nearest_sum == sum(nearest) and moved == [i for i in range(len(amounts)) if tenths[i] != nearest[i]]
    for a, t in zip(amounts, tenths):
        assert abs(t - Fraction(1000 * a, total)) < 1


def test_tenths_tie_goes_to_the_larger_exact_share_and_is_named():
    # 3 and 5 of 2000 are 1.5 and 2.5 tenths: both cut to 1 and 2 with the same remainder, one tenth left over.
    # It goes to the larger exact share (2.5 -> 3); the smaller (1.5, nearest 2) is shown at 1 and is the moved one.
    assert fin_checks.tenths_of_dollar([3, 5, 1992], 2000) == ([1, 3, 996], 1001, [0])
    assert fin_checks.tenths_of_dollar([5, 3, 1992], 2000) == ([3, 1, 996], 1001, [1])   # not by position
    # the county FY2027 rates: Schools and Debt service tie on remainder and both go up; Roads stays at 6.6
    assert fin_checks.tenths_of_dollar([1130, 140, 369, 390, 40, 31], 2100) == ([538, 66, 176, 186, 19, 15], 1001, [1])
    # equal shares: ties to the first listed
    assert fin_checks.tenths_of_dollar([1, 1, 1], 3) == ([334, 333, 333], 999, [0])


def test_rounding_is_deterministic_ties_go_to_the_first_listed():
    cents, s, moved = fin_checks.cents_of_dollar([1, 1, 1], 3)      # 33.33 each: nearest 33, 99 in all
    assert (cents, s, moved) == ([34, 33, 33], 99, [0])


@pytest.mark.parametrize("amounts,total", [([1, 2], 4), ([-1, 2], 1), ([0, 0], 0)])
def test_amounts_that_do_not_add_up_to_the_total_fail(amounts, total):
    with pytest.raises(ValueError):
        fin_checks.cents_of_dollar(amounts, total)


# ---- the county: FY2027 approved book, COUNTY GENERAL FUND 101 ------------------------------------------------------

def test_county_uses_the_adopted_fy2027_column_of_fund_101(county):
    fin, d = county
    assert d["book_id"] == "fy2027-approved" and d["fund"] == "101" and d["col_amount"] == "FY 2027 Budget"
    assert d["kind"] == "Adopted budget"
    assert "the county's FY2027 adopted general fund budget" in d["lede"]
    assert 'column "FY 2027 Budget", the fund the book prints as "COUNTY GENERAL FUND"' in d["source"]


def test_county_departments_add_up_to_the_books_printed_general_fund_total(county):
    fin, d = county
    by_id = lines_by_id(fin)
    fund_total = by_id["fy2027-approved/p78/r37"]
    assert fund_total["label_as_printed"] == "Total Expenditures COUNTY GENERAL FUND 101"
    assert cell(fund_total, "FY 2027 Budget", False) == 169_501_833 == d["value_total"]
    assert d["total"] == "169,501,833" and d["total_src"]["page"] == 78
    amounts = [cell(by_id[m["line_id"]], "FY 2027 Budget", False) for m in members(d)]
    amounts += [cell(by_id[m["line_id"]], "FY 2027 Budget", False) for z in d["zero"] for m in z["members"]]
    assert fin_checks.total_of(amounts) == 169_501_833
    assert len(amounts) == 130           # every printed department total of the fund, each once
    assert len({m["line_id"] for m in members(d)} | {m["line_id"] for z in d["zero"] for m in z["members"]}) == 130


def test_county_each_figure_is_its_printed_line_and_page(county):
    fin, d = county
    by_id = lines_by_id(fin)
    for m in members(d):
        line = by_id[m["line_id"]]
        assert m["value"] == cell(line, "FY 2027 Budget", False)
        assert m["amount"] == next(c["as_printed"] for c in line["cells"] if c["header_as_printed"] == "FY 2027 Budget")
        assert m["page"] == line["page"] and m["src"]["url"].endswith(f"#page={line['page']}")
        assert m["label"] == line["label_as_printed"] and m["heading"] == line["heading_as_printed"]
    rows = {r["name"]: r for r in d["rows"]}
    # pinned against the PDF (budget book pp. 37, 58, 63, 72, 75): the printed department totals
    assert rows["COUNTY MAYOR"]["amount"] == "1,011,796" and rows["COUNTY MAYOR"]["members"][0]["page"] == 37
    assert rows["AMBULANCE SERVICE"]["members"][0]["amount"] == "24,017,739"
    assert rows["AMBULANCE SERVICE"]["members"][0]["page"] == 72
    assert rows["JAIL"]["members"][0]["amount"] == "20,610,529" and rows["JAIL"]["members"][0]["page"] == 63
    assert rows["SHERIFF'S DEPARTMENT"]["members"][0]["amount"] == "21,668,219"
    assert rows["PARKS & FAIR BOARDS"]["members"][0]["amount"] == "4,804,954"
    # a group's amount is its printed totals added up (JAIL - SCAAP ... print "-")
    for r in d["rows"]:
        assert r["value"] == fin_checks.total_of([cell(by_id[m["line_id"]], "FY 2027 Budget", False)
                                                  for m in r["members"]])


def test_county_groups_programs_under_the_department_the_book_names(county):
    _, d = county
    rows = {r["name"]: r for r in d["rows"]}
    patrols = [m["heading"] for m in rows["SPECIAL PATROLS"]["members"]]
    assert "SPECIAL PATROLS - SCHOOL RESOURCE OFFICERS" in patrols and patrols[0] == "SPECIAL PATROLS"
    assert all(h.split(" - ")[0] == "SPECIAL PATROLS" for h in patrols)
    assert rows["SPECIAL PATROLS"]["printed_as"] and not rows["COUNTY MAYOR"]["printed_as"]


# ---- the city: FY2026 final submission book, General Fund, "2026 2nd Readin" ---------------------------------------

def test_city_uses_the_fy2026_adopted_column_never_the_fy2027_proposal(city):
    fin, d = city
    assert d["book_id"] == "fy2026-final" and d["col_amount"] == "2026 2nd Readin" and d["kind"] == "Adopted budget"
    book = next(b for b in fin["books"] if b["id"] == "fy2026-final")
    assert next(c for c in book["columns"] if c["header_as_printed"] == "2026 2nd Readin")["kind"] == "adopted"
    # built from the data (dollar-split/stale-book-note), not a fixed sentence
    assert d["note"] == ("The newest book read here, FY2027 (as presented 5/29/2026), prints a proposed budget for that "
                         "year, not an adopted one, so this uses the FY2026 adopted budget.")


def test_city_departments_with_revenue_give_the_printed_general_fund_total(city):
    fin, d = city
    by_id = lines_by_id(fin)
    net = by_id["fy2026-final/p108/r17"]
    assert net["label_as_printed"] == "TOTAL General Fund" and net["statement"] == "net"
    gf = [x for x in fin["budget_lines"] if x["book_id"] == "fy2026-final" and x["fund_name"] == "General Fund"]
    rev = [cell(x, "2026 2nd Readin", True) for x in gf if x["row_role"] == "total" and x["statement"] == "revenue"]
    assert fin_checks.total_of(rev) == -16_221_009_000            # -162,210,090.00 as printed (credits)
    assert d["value_total"] == 16_563_165_800 and d["total"] == "165,631,658.00"
    assert fin_checks.parts_add_up(rev + [d["value_total"]], cell(net, "2026 2nd Readin", True))
    assert cell(net, "2026 2nd Readin", True) == 342_156_800    # 3,421,568.00 as printed, p. 108
    used = [m["line_id"] for m in members(d)] + [m["line_id"] for z in d["zero"] for m in z["members"]]
    assert len(used) == len(set(used)) == 67
    assert fin_checks.total_of([cell(by_id[i], "2026 2nd Readin", True) for i in used]) == d["value_total"]


def test_city_each_figure_is_its_printed_line_and_page(city):
    fin, d = city
    by_id = lines_by_id(fin)
    for m in members(d):
        line = by_id[m["line_id"]]
        assert m["amount"] == next(c["as_printed"] for c in line["cells"] if c["header_as_printed"] == "2026 2nd Readin")
        assert m["page"] == line["page"]
    rows = {r["name"]: r for r in d["rows"]}
    police = rows["Police"]
    assert [(m["heading"], m["amount"], m["page"]) for m in police["members"]] == [
        ("10421001 Salaries and Wages-Police", "41,022,683.00", 73),
        ("10421003 Operating Expenditures-Police", "7,562,471.00", 75),
        ("10421004 Property Purchases-Police", "2,272,982.00", 75)]
    assert police["amount"] == "50,858,136.00" and police["cents"] == 31
    assert rows["Parks and Recreation"]["amount"] == "10,441,086.00"
    assert rows["Building and Codes"]["amount"] == "3,890,869.00"


def test_city_fy2026_departments_match_the_fy2027_books_original_budget_column(city):
    """The FY2027 file prints FY2026's original adopted budget ("2026 ORIG BUD"): the same amount for every
    department both files print (a second printing of each figure)."""
    fin, d = city
    by_org: dict = {}
    for x in fin["budget_lines"]:
        if x["book_id"] == "fy2027-presented" and x["fund_name"] == "General Fund" and x["row_role"] == "total" \
                and x["statement"] == "expenditure" and x["department"]:
            by_org.setdefault(x["heading_as_printed"].split()[0][:7], []).append(cell(x, "2026 ORIG BUD", True))
    checked = 0
    for r in d["rows"]:
        if r["key"] == "other" or r["key"] not in by_org:
            continue
        assert fin_checks.total_of(by_org[r["key"]]) == r["value"], r["name"]
        checked += 1
    assert checked >= 15


def test_city_every_org_code_has_a_name():
    cfg = dollar_split.load("clarksville-tn")
    fin = json.loads(CITY_FIN.read_text(encoding="utf-8"))
    orgs = {x["heading_as_printed"].split()[0][:7] for x in fin["budget_lines"] if x["book_id"] == "fy2026-final"
            and x["fund_name"] == "General Fund" and x["statement"] == "expenditure" and x["department"]}
    assert orgs <= set(cfg["names"])


# ---- both: rounding, Other, order -----------------------------------------------------------------------------------

@pytest.mark.parametrize("which", ["county", "city"])
def test_cents_sum_to_100_and_stay_within_a_cent(which, request):
    _, d = request.getfixturevalue(which)
    assert sum(r["cents"] for r in d["rows"]) == 100 == d["total_cents"]
    for r in d["rows"]:
        exact = Fraction(100 * r["value"], d["value_total"])
        assert abs(r["cents"] - exact) < 1, r["name"]
        if r["key"] != "other":
            assert r["cents"] >= 1 and exact >= Fraction(1, 2), r["name"]
    other = d["other"]
    assert d["rows"][-1] is other and other["departments"]
    for m in other["members"]:          # each department in Other is under half a cent of the dollar
        dep = next(x for x in other["departments"] if m in x["members"] or m["heading"] in
                   [y["heading"] for y in x["members"]])
        assert dep["members"]
    assert Fraction(100 * other["value"], d["value_total"]) < Fraction(len(other["departments"]), 2)


@pytest.mark.parametrize("which", ["county", "city"])
def test_rows_keep_the_books_order(which, request):
    _, d = request.getfixturevalue(which)
    keys = [budget_views.line_key(r["members"][0]["line_id"]) for r in d["rows"] if r["key"] != "other"]
    assert keys == sorted(keys)


def test_a_total_that_does_not_add_up_fails_the_split():
    fin = json.loads(COUNTY_FIN.read_text(encoding="utf-8"))
    line = next(x for x in fin["budget_lines"] if x["id"] == "fy2027-approved/p72/r34")   # Total AMBULANCE SERVICE
    i = next(i for i, c in enumerate(line["cells"]) if c["header_as_printed"] == "FY 2027 Budget")
    line["cells"][i]["dollars"] += 1
    line["check"]["per_cell"][i]["diff"] = 1
    bg = budget_views.Budget(fin_views.Finance(fin, []), None)
    with pytest.raises(fin_views.FinanceError, match="does not add up"):
        dollar_split.split(bg, dollar_split.load("montgomery-tn"))


def test_an_unnamed_org_code_fails_the_split():
    fin, bg = budget(CITY_FIN, prefix="city/")
    cfg = dict(dollar_split.load("clarksville-tn"))
    cfg["names"] = {k: v for k, v in cfg["names"].items() if k != "1042100"}
    with pytest.raises(fin_views.FinanceError, match="1042100"):
        dollar_split.split(bg, cfg)


def test_a_book_not_in_the_file_shows_no_bar():
    fin = json.loads((ROOT / "site" / "fixtures" / "finance.sample.json").read_text(encoding="utf-8"))
    bg = budget_views.Budget(fin_views.Finance(fin, []), None)
    assert dollar_split.split(bg, dollar_split.load("montgomery-tn")) is None


# ---- dollar-split/untested-invariants: each rule the split rests on fails the build when broken ----------------------

def county_split(change):
    """The county split over a copy of the committed finance.json after `change(lines by id)`."""
    fin = json.loads(COUNTY_FIN.read_text(encoding="utf-8"))
    change({x["id"]: x for x in fin["budget_lines"]}, fin)
    return dollar_split.split(budget_views.Budget(fin_views.Finance(fin, []), None), dollar_split.load("montgomery-tn"))


def city_split(change):
    fin = json.loads(CITY_FIN.read_text(encoding="utf-8"))
    change({x["id"]: x for x in fin["budget_lines"]}, fin)
    return dollar_split.split(budget_views.Budget(fin_views.Finance(fin, []), None, prefix="city/"),
                              dollar_split.load("clarksville-tn"))


def col(line, header):
    return next(i for i, c in enumerate(line["cells"]) if c["header_as_printed"] == header)


AMB, JAIL, FUND_TOTAL = "fy2027-approved/p72/r34", "fy2027-approved/p63/r17", "fy2027-approved/p78/r37"


def test_a_held_department_total_fails_the_split():
    def change(by, fin):
        by[AMB]["held"] = "column-align"
    with pytest.raises(fin_views.FinanceError, match="is held"):
        county_split(change)


def test_a_negative_department_total_fails_the_split():
    def change(by, fin):
        i = col(by[JAIL], "FY 2027 Budget")
        by[JAIL]["cells"][i]["dollars"] = -1
    with pytest.raises(fin_views.FinanceError, match="negative department total"):
        county_split(change)


@pytest.mark.parametrize("how", ["omitted", "counted-twice"])
def test_a_spending_line_left_out_or_counted_twice_fails_the_split(how):
    def change(by, fin):
        line = by[AMB]["scope_line_ids"][0]
        if how == "omitted":
            by[AMB]["scope_line_ids"].remove(line)
        else:
            by[JAIL]["scope_line_ids"].append(line)
    with pytest.raises(fin_views.FinanceError, match="cover every spending line exactly once"):
        county_split(change)


@pytest.mark.parametrize("field,value", [("kind", "amended"), ("fiscal_year", 2026)])
def test_a_total_not_in_the_adopted_column_of_the_year_fails_the_split(field, value):
    """Every total read is checked, not only the first (nit kind-first-only): the jail total is far down the list."""
    def change(by, fin):
        by[JAIL]["cells"][col(by[JAIL], "FY 2027 Budget")][field] = value
    with pytest.raises(fin_views.FinanceError, match="not adopted FY2027"):
        county_split(change)


def test_a_fund_with_no_printed_total_fails_the_split():
    def change(by, fin):
        fin["budget_lines"].remove(by[FUND_TOTAL])
    with pytest.raises(fin_views.FinanceError, match="prints no fund total"):
        county_split(change)


def test_city_revenue_that_does_not_give_the_printed_fund_total_fails_the_split():
    def change(by, fin):
        taxes = by["fy2026-final/p34/r28"]                       # TOTAL Taxes, a revenue section total
        assert taxes["label_as_printed"] == "TOTAL Taxes"
        taxes["cells"][col(taxes, "2026 2nd Readin")]["cents"] -= 1
    with pytest.raises(fin_views.FinanceError, match="revenue and department totals do not add up"):
        city_split(change)


def test_a_total_without_the_column_is_a_finance_error_not_stopiteration():
    def change(by, fin):
        for c in by[AMB]["cells"]:
            if c["header_as_printed"] == "FY 2027 Budget":
                c["header_as_printed"] = "FY 2027 Budgte"
    with pytest.raises(fin_views.FinanceError):
        county_split(change)


def test_a_newer_adopted_book_fails_the_split():
    """dollar-split/stale-book-note: an adopted book newer than the pinned one means the config must move."""
    def change(by, fin):
        b = next(b for b in fin["books"] if b["id"] == "fy2027-presented")
        for c in b["columns"]:
            if c["fiscal_year"] == 2027:
                c["kind"] = "adopted"
    with pytest.raises(fin_views.FinanceError, match="fy2027-presented prints an adopted FY2027 budget"):
        city_split(change)


def test_the_county_has_no_newer_book_and_no_note(county):
    assert county[1]["note"] is None


def test_a_real_build_never_hides_the_bar(tmp_path, monkeypatch):
    """dollar-split/silent-hide: a config naming a book the file does not hold fails a real build."""
    from sitegen.build import BuildError
    real = dollar_split.load

    def load(locality):
        cfg = real(locality)
        return {**cfg, "book": "fy2099-adopted"} if locality == "montgomery-tn" else cfg
    monkeypatch.setattr(dollar_split, "load", load)
    with pytest.raises(BuildError, match="fy2099-adopted"):
        build(ROOT / "data" / "facts.json", tmp_path / "site", target="pages")


def test_no_sum_or_amount_sort_in_dollar_split():
    """Adding goes through collector.fin_checks (budget-reconcile/*); rows are never sorted by amount (neutrality/*)."""
    import ast
    src = (ROOT / "sitegen" / "dollar_split.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("sum", "fsum"), node.lineno
            if node.func.id == "sorted":
                assert not node.keywords, node.lineno             # a set of page numbers only
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr != "sort", node.lineno


# ---- the rendered pages ---------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def site_out(tmp_path_factory):
    out = tmp_path_factory.mktemp("dollar") / "site"
    build(ROOT / "data" / "facts.json", out, target="pages")
    return out


@pytest.fixture(scope="module")
def pages(site_out):
    return {k: (site_out / k).read_text(encoding="utf-8") for k in ("finance/index.html", "city/finance/index.html")}


@pytest.mark.parametrize("rel,which,facts_path,locality", [
    ("finance/index.html", "county", ROOT / "data" / "facts.json", "montgomery-tn"),
    ("city/finance/index.html", "city", ROOT / "data" / "localities" / "clarksville-tn" / "facts.json",
     "clarksville-tn")])
def test_site_checks_know_every_dollar_fact_id(site_out, rel, which, facts_path, locality, request):
    """qa.site_checks `unverified` (the deploy runs it): every data-fact-id on a page must be a known fact. The dollar
    rows' ids come from sitegen/dollar_split.fact_ids, the split the page renders: the same set, row for row."""
    from qa import site_checks
    fin, d = request.getfixturevalue(which)
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    page = {rel: site_checks.parse(site_out / rel)}
    on_page = {f for f in page[rel].fact_ids if f.startswith("dollar/")}
    assert on_page == dollar_split.fact_ids(fin, locality) == {r["fact_id"] for r in d["rows"]} | {d["total_fact_id"]}
    assert len(on_page) == len(d["rows"]) + 1
    kw = {} if which == "county" else {"official_prefix": "city/members/", "export": False}

    def dollar_problems(**more):
        probs = site_checks.check_unverified(site_out, page, facts, internal=False, fin=fin, **kw, **more)
        return [p for p in probs if "dollar/" in p]
    assert dollar_problems(fin_locality=locality) == []
    # the check is not weakened: without the body's dollar ids every row fails, and an unknown id still fails
    assert len(dollar_problems()) == len(on_page)
    page[rel].fact_ids.append(f"dollar/{d['book_id']}/no-such-department")
    assert [p for p in dollar_problems(fin_locality=locality) if "no-such-department" in p]


def section(page):
    i = page.index('<section aria-labelledby="dollar-h" class="dollar" id="general-fund-dollar">')
    return page[i:page.index("</section>", i)]


def text_of(s):
    return html_mod.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)))


BOTH = [("finance/index.html", "county"), ("city/finance/index.html", "city")]
SOURCES = '<details class="dollar-src" id="dollar-sources">'


def glance(sec):
    """What shows before a reader opens "Where these numbers come from": lede, bar, key, the list of rows."""
    return sec[:sec.index(SOURCES)]


@pytest.mark.parametrize("rel,which", BOTH)
def test_page_shows_the_bar_and_its_table(pages, rel, which, request):
    _, d = request.getfixturevalue(which)
    sec = section(pages[rel])
    assert f"<h2 id=\"dollar-h\">{T['heading']}</h2>" in sec
    assert '<div class="dollar-bar" aria-hidden="true"' in sec            # the list and the table carry every figure
    segs = re.findall(r'<span class="dseg[^"]*" style="--n: (\d+)"', sec)
    assert [int(s) for s in segs] == [r["cents"] for r in d["rows"]]
    rows = re.findall(r'<tr class="fact[^"]*" data-fact-id="(dollar/[^"]+)">', sec)
    assert rows == [r["fact_id"] for r in d["rows"]] + [f"dollar/{d['book_id']}/total"]
    # the table: every row's cents in words and its amount as the page prints it, in the book's order, then the total
    cells = re.findall(r'<td class="num c-cents"[^>]*>([^<]+)</td>\s*<td class="num c-amt"[^>]*>([^<]+)</td>', sec)
    assert cells == [(r["cents_words"], r["amount"]) for r in d["rows"]] + [("100 cents", d["total"])]
    txt = text_of(sec)
    assert "100 cents" in txt and d["total"] in txt
    assert "general fund only" in txt and "not property tax alone" in txt
    assert "in the order the book prints them" in txt
    assert '<caption>' in sec and '<th scope="row"' in sec               # a real table for screen readers


@pytest.mark.parametrize("rel,which", BOTH)
def test_the_list_names_every_row_with_its_cents_in_the_books_order(pages, rel, which, request):
    """What a reader sees without opening anything, and what a screen reader reads: a real list, one item per row of
    the split, name and cents (in words for a screen reader), in the book's order, then the total: 100 cents."""
    _, d = request.getfixturevalue(which)
    g = glance(section(pages[rel]))
    assert '<ol class="dollar-rows" role="list" aria-labelledby="dollar-list-h">' in g
    items = re.findall(r'<li class="drow[^"]*" style="--n: (\d+)">\s*<span class="drow-name">(.*?)</span>\s*'
                       r'<span class="drow-c"><span aria-hidden="true">(\d+)&cent;</span>'
                       r'<span class="sr-only">([^<]+)</span></span>', g, re.S)
    assert [(int(n), int(c), w) for n, _, c, w in items] == \
        [(r["cents"], r["cents"], r["cents_words"]) for r in d["rows"]] + [(100, 100, "100 cents")]
    names = [text_of(name).strip() for _, name, _, _ in items]
    assert names[:-1] == [r["name"] for r in d["rows"]]
    assert names[-1].startswith(T["total_row"]) and d["total"] in names[-1]
    for (_, name, _, _), r in zip(items, d["rows"]):                     # each name leads to its printed total's row
        anchor = re.search(r'href="(?:\.\./)+(?:city/)?finance/[a-z0-9-]+\.html#(l-[^"]+)"', name)
        assert (anchor is not None) == (r["key"] != "other"), r["name"]
        assert anchor is None or anchor.group(1) == r["href"].split("#")[1], r["name"]
    # Other's departments, each with its amount and its pages, are listed under its row
    other = g[g.index('<details class="dollar-list" id="dollar-other">'):]
    other = other[:other.index("</details>")]
    for dep in d["other"]["departments"]:
        assert f'<li>{html_mod.escape(dep["name"])}: {dep["amount"]} ' in other.replace("&#39;", "&#x27;"), dep["name"]
        for m in dep["members"]:
            assert f'{m["src"]["url"]}' in html_mod.unescape(other), m["heading"]


@pytest.mark.parametrize("rel,which", BOTH)
def test_the_key_names_the_segments_that_carry_their_cents(pages, rel, which, request):
    """Bar and key agree: the segments that print their cents are the rows of five cents or more, and the key under
    the bar names exactly those, in the bar's order (the book's), never by colour alone."""
    _, d = request.getfixturevalue(which)
    g = glance(section(pages[rel]))
    want = [r for r in d["rows"] if r["cents"] >= dollar_split.T_LABEL_MIN]
    assert want and d["key"] == want
    on_bar = re.findall(r'<span class="dseg dseg-l[^"]*" style="--n: (\d+)"[^>]*><b class="dseg-t">(\d+)&cent;</b>', g)
    assert on_bar == [(str(r["cents"]), str(r["cents"])) for r in want]
    assert g.count('<b class="dseg-t">') == len(want)
    key = g[g.index('<ul class="dollar-key"'):]
    key = re.findall(r"<li><b>(\d+)&cent;</b> ([^<]+)</li>", key[:key.index("</ul>")])
    assert [(int(c), html_mod.unescape(n)) for c, n in key] == [(r["cents"], r["short"]) for r in want]
    assert f"{dollar_split.T_LABEL_MIN} cents or more" in text_of(g)


@pytest.mark.parametrize("rel,which", BOTH)
def test_the_glance_is_plain_and_the_provenance_is_in_the_sources_block(pages, rel, which, request):
    """Up front: one plain lede that says what this is and is not, and the fund total. The column as printed, the
    book, how the total was checked, the rounding and the full table are in the closed sources block."""
    _, d = request.getfixturevalue(which)
    sec = section(pages[rel])
    g, src = text_of(glance(sec)), sec[sec.index(SOURCES):]
    assert "general fund only" in g and "not property tax alone" in g and "in the book's order" in g
    assert d["total_line"] in g and "$" + d["total"].removesuffix(".00") in g
    assert d["col_amount"] not in g and "column" not in g and "rounded" not in g
    assert SOURCES + "\n<summary>" + T["sources_toggle"] + "</summary>" in sec and "<details open" not in sec
    s = text_of(src)
    assert f'column "{d["col_amount"]}"' in s and "rounded to the nearest whole cent" in s
    assert d["total_before"].strip() in s and d["total_after"].strip() in s
    assert '<table class="fin-stack dollar-table">' in src and src.rstrip().endswith("</details>")
    assert f'href="{d["total_src"]["url"]}"' in html_mod.unescape(src)   # the total's own page


@pytest.mark.parametrize("rel", ["finance/index.html", "city/finance/index.html"])
def test_page_text_is_neutral(pages, rel):
    from test_fin_pages import FIN_BANNED
    m = FIN_BANNED.search(text_of(section(pages[rel])))
    assert m is None, m and m.group(0)


@pytest.mark.parametrize("rel", ["finance/index.html", "city/finance/index.html"])
def test_every_department_links_to_its_row_and_its_pdf_page(pages, rel):
    sec = section(pages[rel])
    links = re.findall(r'href="([^"]+#l-[^"]+)"', sec)
    assert links and all(re.match(r"(\.\./)+(city/)?finance/[a-z0-9-]+\.html#l-", h) for h in links)
    assert re.search(r'href="https://[^"]+#page=\d+"', sec)


# ---- the caption under the bar -------------------------------------------------------------------------------------

def test_city_caption_names_the_general_fund_first_then_the_department_rule(city):
    _, d = city
    assert d["total_line"] == ("This bar is the general fund, the city's main budget for everyday services: "
                               "$165,631,658.")
    assert d["key_note"] == ("Departments that get 5 cents or more of each dollar are named, left to right in the "
                             "book's order.")


def test_county_caption_says_the_county(county):
    _, d = county
    assert d["total_line"].startswith("This bar is the general fund, the county's main budget for everyday services: $")
    assert d["total_line"].endswith(".") and "dollars" not in d["total_line"]


def test_the_caption_amount_is_budget_views_usd_and_there_is_no_second_helper():
    """finance-pages/duplicate-usd-helper: one helper writes an amount in running text for every bar."""
    import inspect
    assert not hasattr(dollar_split, "caption_amount")
    assert "usd(" in inspect.getsource(dollar_split.split)
    assert budget_views.usd(16_563_165_800) == "$165,631,658" and budget_views.usd(16_563_165_807) == "$165,631,658.07"
