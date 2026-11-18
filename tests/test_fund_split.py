"""The city budget dollar, by fund (docs/architecture/city-funds-dollar.md; sitegen/fund_split.py): on the city's
Finance index, above the general fund dollar, how the FY2026 adopted budget splits across the 14 funds of the book's
line-item report, in tenths of a cent. Problem-key families: fund-split/*, budget-reconcile/*, provenance/*,
neutrality/*."""
import copy
import html as html_mod
import json
import re
from fractions import Fraction

import pytest

from conftest import ROOT
from sitegen import budget_views, config, dollar_split, fin_views, fund_split
from sitegen.build import BuildError, build

CITY_FIN = ROOT / "data" / "localities" / "clarksville-tn" / "finance.json"
RAW = CITY_FIN.read_text(encoding="utf-8")
T = config.FIN_TEXT["fund_split"]
COL = "2026 2nd Readin"
BOOK = "fy2026-final"
RUN_TOTALS = [f"{BOOK}/p137/r11", f"{BOOK}/p138/r24"]

# docs/architecture/city-funds-dollar.md section 2: (printed, plain name, spending, sections, fund total line, cents)
TABLE = [
    ("General Fund", "General fund", "165,631,658.00", 67, "p108/r17", "74.9"),
    ("Drug Enforcement", "Drug enforcement", "520,773.00", 3, "p110/r21", "0.2"),
    ("Police Special Revenue", "Police special revenue", "456,923.00", 3, "p115/r27", "0.2"),
    ("Traffic Camera Pol SRF", "Traffic camera, police", "324,785.00", 2, "p116/r21", "0.2"),
    ("Traffic Camera Parks SRF", "Traffic camera, parks", "500,000.00", 1, "p117/r18", "0.2"),
    ("Road Improvements Fund", "Road improvements", "1,800,000.00", 1, "p118/r16", "0.8"),
    ("Parks Special Revenue", "Parks special revenue", "843,437.00", 4, "p124/r23", "0.4"),
    ("Special Revenue Fund", "Special revenue", "162,700.00", 2, "p126/r11", "0.1"),
    ("Debt Service Fund", "Debt service", "15,181,189.00", 1, "p127/r25", "6.9"),
    ("Parking Commission", "Parking commission", "1,094,227.00", 3, "p131/r15", "0.5"),
    ("Dental Fund", "Dental insurance", "1,498,480.00", 1, "p132/r19", "0.7"),
    ("Health Insurance Fund", "Health insurance", "27,252,761.77", 2, "p135/r8", "12.3"),
    ("Self-Insurance Fund", "Self-insurance", "1,349,000.00", 2, "p137/r9", "0.6"),
    ("Vehicle Replacement Fund", "Vehicle replacement", "4,443,912.00", 1, "p138/r22", "2.0"),
]
SECTIONS = {   # section 2's "Section totals per fund" (the general fund's are the general fund bar's)
    "Drug Enforcement": ["p109/r13", "p110/r9", "p110/r20"],
    "Police Special Revenue": ["p112/r23", "p115/r11", "p115/r26"],
    "Traffic Camera Pol SRF": ["p116/r14", "p116/r20"],
    "Traffic Camera Parks SRF": ["p117/r14"],
    "Road Improvements Fund": ["p118/r15"],
    "Parks Special Revenue": ["p119/r21", "p122/r24", "p124/r9", "p124/r22"],
    "Special Revenue Fund": ["p125/r18", "p126/r10"],
    "Debt Service Fund": ["p127/r19"],
    "Parking Commission": ["p128/r24", "p130/r17", "p131/r14"],
    "Dental Fund": ["p132/r18"],
    "Health Insurance Fund": ["p134/r27", "p135/r7"],
    "Self-Insurance Fund": ["p136/r17", "p136/r26"],
    "Vehicle Replacement Fund": ["p138/r21"],
}
BETWEEN = [   # section 3: (fund, line, label, amount as printed)
    ("Debt service", "p127/r22", "Tran In GF", "-12,174,410.00"),
    ("Dental insurance", "p132/r8", "Rev-GF", "-999,660.00"),
    ("Health insurance", "p133/r9", "Rev-GF", "-11,885,120.10"),
    ("Health insurance", "p133/r14", "Phar-GF", "-5,558,159.70"),
    ("Health insurance", "p133/r19", "OSC GF-OSC", "-1,400,760.00"),
    ("Self-insurance", "p136/r19", "Rev-GF", "-814,899.00"),
    ("Vehicle replacement", "p138/r9", "Rev-GF", "-534,089.00"),
    ("Vehicle replacement", "p138/r10", "421 Rev-GF", "-2,337,823.00"),
    ("Vehicle replacement", "p138/r11", "422 Rev-GF", "-1,053,000.00"),
    ("Vehicle replacement", "p138/r12", "431 Rev-GF", "-519,000.00"),
]


def city_budget(fin=None):
    fin = fin if fin is not None else json.loads(RAW)
    return fin, budget_views.Budget(fin_views.Finance(fin, []), None, prefix="city/",
                                    text=config.FIN_TEXT["budget_city"])


@pytest.fixture(scope="module")
def cfg():
    return fund_split.load("clarksville-tn")


@pytest.fixture(scope="module")
def city(cfg):
    fin, bg = city_budget()
    dollar = dollar_split.split(bg, dollar_split.load("clarksville-tn"))
    return fin, fund_split.split(bg, cfg, dollar), dollar


def by_id(fin):
    return {x["id"]: x for x in fin["budget_lines"]}


def cell(line, header=COL):
    return next(c for c in line["cells"] if c["header_as_printed"] == header)


def col(line, header=COL):
    return next(i for i, c in enumerate(line["cells"]) if c["header_as_printed"] == header)


# ---- the book and column ------------------------------------------------------------------------------------------

def test_uses_the_fy2026_adopted_column_never_the_fy2027_proposal(city):
    fin, d, _ = city
    assert d["book_id"] == BOOK and d["col_amount"] == COL and d["kind"] == "Adopted budget"
    book = next(b for b in fin["books"] if b["id"] == BOOK)
    assert next(c for c in book["columns"] if c["header_as_printed"] == COL) == \
        {"fiscal_year": 2026, "header_as_printed": COL, "kind": "adopted"}
    lines = by_id(fin)
    used = [i for r in d["rows"] for i in r["line_ids"]] + [s["line_id"] for s in d["total_srcs"]]
    assert all(i.startswith(BOOK + "/") for i in used)
    assert "2027 Mayor" not in json.dumps(d, default=str)
    assert all(cell(lines[i])["kind"] == "adopted" and cell(lines[i])["fiscal_year"] == 2026 for i in used)
    assert d["note"] == ("The newest book read here, FY2027 (as presented 5/29/2026), prints a proposed budget for that "
                         "year, not an adopted one, so this uses the FY2026 adopted budget.")


# ---- the amounts: section 2, to the cent ---------------------------------------------------------------------------

def test_rows_are_the_architecture_table_to_the_cent_in_the_books_order(city):
    _, d, _ = city
    got = [(r["printed"], r["name"], r["amount_printed"], r["n_sections"], r["href"].split("#l-" + BOOK + "-")[1],
            r["cents"]) for r in d["rows"]]
    assert got == [(p, n, a, s, line.replace("/", "-"), c) for p, n, a, s, line, c in TABLE]
    assert d["total"] == "$221,059,845.77" and d["total_printed"] == "221,059,845.77"
    assert d["value_total"] == 22_105_984_577
    rows = {r["printed"]: r for r in d["rows"]}
    assert rows["General Fund"]["amount"] == "$165,631,658"
    for fund, ids in SECTIONS.items():
        assert rows[fund]["line_ids"] == [f"{BOOK}/{i}" for i in ids], fund
        assert [m["line_id"] for m in rows[fund]["members"]] == rows[fund]["line_ids"]


def test_each_member_is_its_printed_line_and_page(city):
    fin, d, _ = city
    lines = by_id(fin)
    for r in d["rows"]:
        for m in r["members"]:
            x = lines[m["line_id"]]
            assert m["amount"] == cell(x)["as_printed"] and m["page"] == x["page"]
            assert m["src"]["url"].endswith(f"#page={x['page']}")
            assert m["heading"] == x["heading_as_printed"] and m["label"] == x["label_as_printed"]
            assert m["href"].endswith("#" + budget_views.anchor(x["id"]))
        assert r["value"] == sum(cell(lines[i])["cents"] for i in r["line_ids"]), r["name"]
    for r, (*_, net_id, _c) in zip(d["rows"], TABLE):      # each row's own source: its printed TOTAL <fund> line's page
        net = lines[f"{BOOK}/{net_id}"]
        assert r["fund_src"]["page"] == net["page"] and r["fund_src"]["url"].endswith(f"#page={net['page']}")
        assert r["href"].endswith("#" + budget_views.anchor(net["id"]))


def test_the_total_is_the_two_printed_total_expense_lines(city):
    fin, d, _ = city
    lines = by_id(fin)
    runs = [lines[i] for i in RUN_TOTALS]
    assert [(x["label_as_printed"], x["fund_name"], cell(x)["as_printed"]) for x in runs] == [
        ("TOTAL EXPENSE", None, "216,615,933.77"), ("TOTAL EXPENSE", None, "4,443,912.00")]
    assert cell(runs[0])["cents"] + cell(runs[1])["cents"] == 22_105_984_577 == d["value_total"]
    assert sum(r["value"] for r in d["rows"]) == d["value_total"]
    assert [(s["line_id"], s["page"], s["amount"]) for s in d["total_srcs"]] == [
        (RUN_TOTALS[0], 137, "216,615,933.77"), (RUN_TOTALS[1], 138, "4,443,912.00")]


def test_each_fund_and_its_revenue_totals_give_its_printed_fund_total(city):
    fin, d, _ = city
    lines = by_id(fin)
    for r, (printed, *_, net_id, _c) in zip(d["rows"], TABLE):
        net = lines[f"{BOOK}/{net_id}"]
        assert net["statement"] == "net" and net["fund_name"] == printed
        assert net["label_as_printed"].startswith("TOTAL ")
        rev = [cell(x)["cents"] for x in fin["budget_lines"] if x["book_id"] == BOOK and x["fund_name"] == printed
               and x["statement"] == "revenue" and x["row_role"] == "total"]
        assert sum(rev) + r["value"] == cell(net)["cents"], printed


def test_cents_are_tenths_that_add_up_to_100_and_the_moved_row_is_named(city):
    _, d, _ = city
    total = d["value_total"]
    assert sum(r["tenths"] for r in d["rows"]) == 1000 and d["total_cents"] == "100.0"
    for r in d["rows"]:
        assert abs(r["tenths"] - Fraction(1000 * r["value"], total)) < 1, r["name"]
    assert [r["name"] for r in d["rows"] if r["moved"]] == ["Traffic camera, police"]
    assert "would add up to 99.9, so this row shows one tenth more than its nearest tenth: Traffic camera, police." \
        in d["rounding"]
    assert [(r["cents"], r["short"]) for r in d["key"]] == [("74.9", "General fund"), ("6.9", "Debt service"),
                                                            ("12.3", "Health insurance")]
    assert all(r["tenths"] > 0 for r in d["rows"]) and d["zero"] == []


def test_the_general_fund_row_is_the_general_fund_bars_total_and_links_to_it(city):
    _, d, dollar = city
    gf = d["rows"][0]
    assert gf["value"] == dollar["value_total"] == 16_563_165_800
    assert gf["to_dollar"] and gf["members"] == [] and [r["name"] for r in d["rows"] if r["to_dollar"]] == ["General fund"]
    gf_members = [m["line_id"] for r in dollar["rows"] for m in r["members"]] + \
        [m["line_id"] for z in dollar["zero"] for m in z["members"]]
    assert sorted(gf["line_ids"]) == sorted(gf_members) and len(gf_members) == 67
    assert d["dollar_members"] == "Its 67 department totals are listed under the general fund bar below."


def test_a_general_fund_row_that_differs_from_the_general_fund_bar_fails(city, cfg):
    _, bg = city_budget()
    dollar = dict(city[2], value_total=city[2]["value_total"] + 1)
    with pytest.raises(fin_views.FinanceError, match="not the general fund dollar's total"):
        fund_split.split(bg, cfg, dollar)


# ---- no double count --------------------------------------------------------------------------------------------

def test_every_spending_line_is_reached_once_and_no_run_total_is_a_row(city):
    fin, d, _ = city
    lines = by_id(fin)
    used = [i for r in d["rows"] for i in r["line_ids"]]
    assert len(used) == len(set(used)) == 93
    for i in used:
        x = lines[i]
        assert x["fund_name"] and x["statement"] == "expenditure" and x["row_role"] == "total" and x["department"]
    reached = [j for i in used for j in lines[i]["scope_line_ids"]]
    spending = [x["id"] for x in fin["budget_lines"] if x["book_id"] == BOOK and x["statement"] == "expenditure"
                and x["row_role"] == "detail"]
    assert len(reached) == len(spending) and set(reached) == set(spending)
    assert not any(lines[i]["fund_name"] is None for i in used)


def test_the_between_funds_list_is_the_ten_lines_and_changes_no_amount(city):
    fin, d, _ = city
    assert [(b["fund"], b["line_id"], b["label"], b["amount"]) for b in d["between_lines"]] == \
        [(f, f"{BOOK}/{i}", lab, a) for f, i, lab, a in BETWEEN]
    lines = by_id(fin)
    used = {i for r in d["rows"] for i in r["line_ids"]}
    for b in d["between_lines"]:
        x = lines[b["line_id"]]
        assert x["statement"] == "revenue" and b["line_id"] not in used
        assert b["src"]["url"].endswith(f"#page={x['page']}") and b["href"].endswith("#" + budget_views.anchor(x["id"]))
    vehicle = [x for x in fin["budget_lines"] if x["book_id"] == BOOK and x["fund_name"] == "Vehicle Replacement Fund"
               and x["statement"] == "revenue" and x["row_role"] == "total"]
    assert [cell(x)["as_printed"] for x in vehicle] == ["-4,443,912.00"]


# ---- every rule fails the split when broken ----------------------------------------------------------------------

def split_with(change=None, cfg_change=None):
    fin = json.loads(RAW)
    if change:
        change(by_id(fin), fin)
    c = copy.deepcopy(fund_split.load("clarksville-tn"))
    if cfg_change:
        cfg_change(c)
    _, bg = city_budget(fin)
    return fund_split.split(bg, c)


DRUG = f"{BOOK}/p109/r13"          # TOTAL Drug Enforcement-Salar, 180,200.00
DRUG2 = f"{BOOK}/p110/r9"


def _held(by, fin):
    by[DRUG]["held"] = "column-align"


def _not_exact(by, fin):
    by[DRUG]["check"]["per_cell"][col(by[DRUG])]["diff"] = 100


def _negative(by, fin):
    by[DRUG]["cells"][col(by[DRUG])]["cents"] = -1


def _left_out(by, fin):
    by[DRUG]["scope_line_ids"].pop()


def _twice(by, fin):
    by[DRUG2]["scope_line_ids"].append(by[DRUG]["scope_line_ids"][0])


def _run_left_out(by, fin):
    by[RUN_TOTALS[0]]["scope_line_ids"].pop()


def _run_off(by, fin):
    by[RUN_TOTALS[1]]["cells"][col(by[RUN_TOTALS[1]])]["cents"] += 1


def _revenue_off(by, fin):
    x = next(x for x in fin["budget_lines"] if x["book_id"] == BOOK and x["fund_name"] == "Dental Fund"
             and x["statement"] == "revenue" and x["row_role"] == "total")
    x["cells"][col(x)]["cents"] -= 1


def _gf_other_account(by, fin):
    by[f"{BOOK}/p133/r9"]["account_code"] = "34899"


def _account_without_gf(by, fin):
    by[f"{BOOK}/p132/r8"]["label_as_printed"] = "Rev-Gas"


def _not_adopted(by, fin):
    by[f"{BOOK}/p136/r17"]["cells"][col(by[f"{BOOK}/p136/r17"])]["kind"] = "amended"


def _newer_adopted(by, fin):
    b = next(b for b in fin["books"] if b["id"] == "fy2027-presented")
    for c in b["columns"]:
        if c["fiscal_year"] == 2027:
            c["kind"] = "adopted"


def _no_run_total(by, fin):
    fin["budget_lines"][:] = [x for x in fin["budget_lines"] if x["id"] not in RUN_TOTALS]


@pytest.mark.parametrize("change,match", [
    (_held, "is held"),
    (_not_exact, "does not add up to its lines"),
    (_negative, "negative spending total"),
    (_left_out, "do not cover every spending line exactly once"),
    (_twice, "do not cover every spending line exactly once"),
    (_run_left_out, "TOTAL EXPENSE lines do not cover every spending line"),
    (_run_off, "do not add up to its printed TOTAL EXPENSE"),
    (_revenue_off, "revenue and spending totals do not add up"),
    (_gf_other_account, "is not under a from_general_fund account but has 'GF'"),
    (_account_without_gf, "is under a from_general_fund account but has no 'GF'"),
    (_not_adopted, "not adopted FY2026"),
    (_newer_adopted, "fy2027-presented prints an adopted FY2027 budget"),
    (_no_run_total, "prints no report-run TOTAL EXPENSE"),
])
def test_a_broken_rule_fails_the_split(change, match):
    with pytest.raises(fin_views.FinanceError, match=match):
        split_with(change)


@pytest.mark.parametrize("cfg_change,match", [
    (lambda c: c["funds"].pop(3), "not the funds fy2026-final prints"),                      # a fund left out
    (lambda c: c["funds"].insert(2, c["funds"].pop(5)), "in its order"),                      # out of order
    (lambda c: c["funds"].append({"printed": "Gas & Water", "name": "Gas and water"}), "not in the book"),
    (lambda c: c.update(book="fy2099-final"), "fy2099-final is not in finance.json"),         # silent-hide
    (lambda c: c.update(dollar_fund="no-such-fund"), "names 0 of the book's funds"),
])
def test_a_wrong_config_fails_the_split(cfg_change, match):
    with pytest.raises(fin_views.FinanceError, match=match):
        split_with(cfg_change=cfg_change)


@pytest.mark.parametrize("edit,match", [
    (lambda c: c.pop("book"), "`book`"),
    (lambda c: c.pop("column"), "`column`"),
    (lambda c: c.pop("dollar_fund"), "`dollar_fund`"),
    (lambda c: c.pop("from_general_fund"), "`from_general_fund`"),
    (lambda c: c["from_general_fund"].update(accounts=[]), "accounts"),
    (lambda c: c["from_general_fund"].pop("label_token"), "label_token"),
    (lambda c: c.update(funds=c["funds"][:1]), "two or more"),
    (lambda c: c["funds"][3].pop("name"), "`name`"),
    (lambda c: c["funds"][3].update(name="Health insurance"), "share a `name`"),
    (lambda c: c["funds"][3].update(printed="General Fund"), "share a `printed`"),
])
def test_a_partial_config_fails_to_load(tmp_path, monkeypatch, cfg, edit, match):
    import yaml
    c = copy.deepcopy(cfg)
    edit(c)
    d = tmp_path / "localities" / "x"
    d.mkdir(parents=True)
    (d / fund_split.FILE).write_text(yaml.safe_dump(c), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    with pytest.raises(fin_views.FinanceError, match=match):
        fund_split.load("x")


def test_a_body_without_a_config_shows_no_bar():
    assert fund_split.load("montgomery-tn") is None
    _, bg = city_budget()
    assert fund_split.split(bg, None) is None


def test_usd_drops_only_a_zero_cents_part():
    assert budget_views.usd(16_563_165_800) == "$165,631,658"
    assert budget_views.usd(22_105_984_577) == "$221,059,845.77"
    assert budget_views.usd(5) == "$0.05" and budget_views.usd(0) == "$0"
    with pytest.raises(ValueError):
        budget_views.usd(-1)


def test_no_sum_or_amount_sort_in_fund_split():
    """Adding goes through collector.fin_checks (budget-reconcile/*); rows are never sorted by amount (neutrality/*)."""
    import ast
    src = (ROOT / "sitegen" / "fund_split.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("sum", "fsum", "sorted"), node.lineno
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr != "sort", node.lineno


# ---- the rendered page ------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def site_out(tmp_path_factory):
    out = tmp_path_factory.mktemp("funds") / "site"
    build(ROOT / "data" / "facts.json", out, target="pages")
    return out


@pytest.fixture(scope="module")
def page(site_out):
    return (site_out / "city" / "finance" / "index.html").read_text(encoding="utf-8")


SECTION = '<section aria-labelledby="city-funds-h" class="dollar fundsplit" id="city-funds-dollar">'
SOURCES = '<details class="dollar-src" id="city-funds-sources">'


def section(page):
    i = page.index(SECTION)
    return page[i:page.index("</section>", i)]


def text_of(s):
    return html_mod.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)))


def row_link(href):
    """A link to a line's row on its fund page, or on the page part that holds it (a real build splits a large fund
    page in parts, so the page differs from the unplanned view's; the row anchor does not)."""
    return r'<a href="(\.\./)+city/finance/[a-z0-9-]+\.html' + re.escape("#" + href.split("#")[1]) + '"'


def visible(s):
    """The text a sighted reader sees, inline tags dropped without a space ("(p. 137; p. 138).")."""
    s = re.sub(r'<span class="sr-only">[^<]*</span>', "", s)
    return html_mod.unescape(re.sub(r"\s+", " ", re.sub(r"</?(a|span|b)\b[^>]*>", "", s)))


def test_the_bar_is_on_the_city_page_only_above_the_general_fund_dollar(site_out, page):
    assert page.count(SECTION) == 1
    assert page.index(SECTION) < page.index('id="general-fund-dollar"')
    county = (site_out / "finance" / "index.html").read_text(encoding="utf-8")
    assert 'id="city-funds-dollar"' not in county and "funds/fy" not in county
    assert len(re.findall(r'\bid="city-funds-h"', page)) == 1 and len(re.findall(r'\bid="funds-h"', page)) == 1


def test_the_glance_reads_as_designed(page):
    """docs/architecture/city-funds-dollar.md section 4: the copy as it renders with today's data."""
    sec = section(page)
    g = text_of(sec[:sec.index(SOURCES)])
    assert f'<h2 id="city-funds-h">{T["heading"]}</h2>' in sec
    assert ("How the city's FY2026 adopted budget splits across the 14 funds this site reads from its budget book, in "
            "cents of each dollar. A fund is a separate set of accounts the city keeps for one purpose. "
            + T["between"]) in g
    assert "74.9¢ General fund 6.9¢ Debt service 12.3¢ Health insurance" in g
    assert ("Named here: each fund with 5 cents or more, left to right in the order the book prints them. The whole bar "
            "is $221,059,845.77, the spending the book prints for these 14 funds.") in g
    assert "column" not in g and "rounded" not in g


def test_the_sources_block_reads_as_designed(page):
    sec = section(page)
    src = sec[sec.index(SOURCES):]
    s = text_of(src)
    assert SOURCES + "\n<summary>" + T["sources_toggle"] + "</summary>" in sec and "<details open" not in sec
    assert 'From Fiscal Year 2026 Budget (Final Submission), column "2026 2nd Readin". No fund in this book' in s
    assert ('Total: $221,059,845.77, the book\'s own "TOTAL EXPENSE" lines of its 2 report runs added up (p. 137; '
            "p. 138). The funds' amounts add up to it exactly.") in visible(src)
    for k in ("fund_check", "measures", "order", "between_list"):
        assert T[k] in s, k
    assert ("The newest book read here, FY2027 (as presented 5/29/2026), prints a proposed budget for that year, not an "
            "adopted one, so this uses the FY2026 adopted budget.") in s
    assert ("Rounded to the nearest tenth they would add up to 99.9, so this row shows one tenth more than its nearest "
            "tenth: Traffic camera, police.") in s


def test_the_list_has_every_fund_in_the_books_order(page, city):
    _, d, _ = city
    sec = section(page)
    g = sec[:sec.index(SOURCES)]
    items = re.findall(r'<li class="drow" style="--n: ([\d.]+)">\s*<span class="drow-name">(.*?)</span>\s*'
                       r'<span class="drow-c"><span aria-hidden="true">([\d.]+)&cent;</span>'
                       r'<span class="sr-only">([^<]+)</span>', g, re.S)
    assert len(items) == 14
    assert [text_of(n).strip().split(" How the")[0] for _, n, _, _ in items] == [r[1] for r in TABLE]
    assert [(a, c, w) for a, _, c, w in items] == [(r["cents"], r["cents"], r["cents_words"]) for r in d["rows"]]
    assert re.search(r'<a href="#general-fund-dollar">General fund</a> <span class="drow-sub">', items[0][1])
    for (_, name, _, _), r in zip(items[1:], d["rows"][1:]):
        assert re.search(row_link(r["href"]), name), r["name"]
    segs = re.findall(r'<span class="dseg[^"]*" style="--n: ([\d.]+)"', g)
    assert segs == [r["cents"] for r in d["rows"]]


def test_every_amount_in_the_table_links_to_its_row_and_pdf_page(page, city):
    _, d, _ = city
    sec = section(page)
    src = html_mod.unescape(sec[sec.index(SOURCES):])
    cells = re.findall(r'<td class="num c-cents"[^>]*>([^<]+)</td>\s*<td class="num c-amt"[^>]*>([^<]+)</td>', sec)
    assert cells == [(r["cents_words"], r["amount_printed"]) for r in d["rows"]] + [("100.0 cents", "221,059,845.77")]
    for r in d["rows"]:
        assert re.search(row_link(r["href"]), src) and r["fund_src"]["url"] in src, r["name"]
        for m in r["members"]:
            after = re.escape(f'>{m["heading"]}</a> {m["amount"]} (<a href="{m["src"]["url"]}"')
            assert re.search(row_link(m["href"]) + after, src), m
    for b in d["between_lines"]:
        assert re.search(row_link(b["href"]) + re.escape(f'>{b["label"]}</a> {b["amount"]} (<a href="{b["src"]["url"]}"'),
                         src), b
    for s in d["total_srcs"]:
        assert re.search(row_link(s["href"]) + re.escape(f'>TOTAL EXPENSE</a> {s["amount"]} (<a href="{s["src"]["url"]}"'),
                         src), s
        assert f'<a href="{s["src"]["url"]}" target="_blank" rel="noopener noreferrer">p. {s["page"]}<' in src
    links = re.findall(r'href="([^"]+#l-[^"]+)"', sec)
    assert links and all(re.match(r"(\.\./)+city/finance/[a-z0-9-]+\.html#l-", h) for h in links)
    rows = re.findall(r'<tr class="fact[^"]*" data-fact-id="(funds/[^"]+)">', sec)
    assert rows == [r["fact_id"] for r in d["rows"]] + [d["total_fact_id"]]


def test_page_text_is_neutral(page):
    from test_fin_pages import FIN_BANNED
    m = FIN_BANNED.search(text_of(section(page)))
    assert m is None, m and m.group(0)


def test_site_checks_know_every_fund_fact_id(site_out, city):
    """qa.site_checks `unverified` (the deploy runs it): every data-fact-id on a page must be a known fact."""
    from qa import site_checks
    fin, d, _ = city
    facts = json.loads((ROOT / "data" / "localities" / "clarksville-tn" / "facts.json").read_text(encoding="utf-8"))
    rel = "city/finance/index.html"
    pg = {rel: site_checks.parse(site_out / rel)}
    on_page = {f for f in pg[rel].fact_ids if f.startswith("funds/")}
    assert on_page == fund_split.fact_ids(fin, "clarksville-tn") == {r["fact_id"] for r in d["rows"]} | {d["total_fact_id"]}
    assert len(on_page) == 15 and on_page <= site_checks.finance_fact_ids(fin, "clarksville-tn")
    kw = {"official_prefix": "city/members/", "export": False}

    def problems(**more):
        return [p for p in site_checks.check_unverified(site_out, pg, facts, internal=False, fin=fin, **kw, **more)
                if "funds/" in p]
    assert problems(fin_locality="clarksville-tn") == []
    assert len(problems()) == len(on_page)                 # not weakened: without the locality every row fails
    pg[rel].fact_ids.append(f"funds/{d['book_id']}/no-such-fund")
    assert [p for p in problems(fin_locality="clarksville-tn") if "no-such-fund" in p]


def test_a_broken_config_fails_the_build(tmp_path, monkeypatch, cfg):
    """fund-split/silent-hide and fund-split/fund-list: a config that does not match the book never builds a page."""
    bad = copy.deepcopy(cfg)
    bad["funds"].pop(3)
    monkeypatch.setattr(fund_split, "load", lambda locality: bad)
    with pytest.raises(BuildError, match="not the funds fy2026-final prints"):
        build(ROOT / "data" / "facts.json", tmp_path / "site", target="pages")
