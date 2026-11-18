"""The county property tax dollar (docs/architecture/finance-contracts.md 12; sitegen/property_tax.py): on the county's
Finance index, above the general fund dollar, how each county property tax dollar splits across the funds Resolution
26-6-11 levies it for, schools included. Problem-key families: property-tax-split/*, budget-reconcile/*, provenance/*,
neutrality/*."""
import copy
import html as html_mod
import json
import re
from fractions import Fraction

import pytest

from conftest import ROOT
from sitegen import budget_views, config, fin_views, property_tax
from sitegen.build import BuildError, build

COUNTY_FIN = ROOT / "data" / "finance.json"
LEVY_PAGE = ROOT / "tests" / "fixtures" / "fy2027-tax-levy-p20.txt"
T = config.FIN_TEXT["property_tax"]
PLAIN = ["County general fund", "Roads", "Schools", "Debt service", "Capital projects", "School transportation"]


def county_budget(fin=None):
    fin = fin if fin is not None else json.loads(COUNTY_FIN.read_text(encoding="utf-8"))
    return fin, budget_views.Budget(fin_views.Finance(fin, []), None)


@pytest.fixture(scope="module")
def cfg():
    return property_tax.load("montgomery-tn")


@pytest.fixture(scope="module")
def county(cfg):
    fin, bg = county_budget()
    return fin, property_tax.split(bg, cfg, "101")


def levy_table(text):
    """The resolution's fund table as its page's text layer prints it: [(fund, FY 2027 rate)], then the total."""
    rows = re.findall(r"^\s+([A-Z][A-Za-z ]+?)\s{2,}(\$?\d\.\d{3})\s+(\$?\d\.\d{3})\s+(\$?\d\.\d{3})\s*$", text, re.M)
    return [(name, fy27) for name, _, _, fy27 in rows]


# ---- the rates are the page's -----------------------------------------------------------------------------------

def test_config_rates_are_the_printed_fy2027_column_in_the_resolutions_order(cfg):
    """property-tax-split.yml was copied by hand: the page's own text layer (book fy2027-approved, PDF p. 20) must give
    back every fund, its FY 2027 rate as printed, and the total, in the same order."""
    text = LEVY_PAGE.read_text(encoding="utf-8")
    assert cfg["resolution"] in text and "FISCAL YEAR BEGINNING JULY 1, 2026" in text
    assert f"shall be {cfg['rate_as_printed']} on each\n$100 of taxable property" in text
    assert re.search(r"FY 2025\s+FY 2026\s+FY 2027\s*\n\s*Funds\s+Rate\s+Rate\s+Rate", text)
    table = levy_table(text)
    assert table[-1] == ("Total Tax Rate", cfg["total_as_printed"])
    assert table[:-1] == [(f["printed"], f["rate"]) for f in cfg["funds"]]
    assert cfg["book"] == "fy2027-approved" and cfg["page"] == 20 and cfg["column"] == "FY 2027 Rate"


def test_the_source_page_is_the_budget_book_in_finance_json(cfg):
    fin = json.loads(COUNTY_FIN.read_text(encoding="utf-8"))
    book = next(b for b in fin["books"] if b["id"] == cfg["book"])
    src = next(s for s in fin["sources"] if s["id"] == book["source_id"])
    assert src["sha256"].startswith("f6538dd0321b") and src["pages"] >= cfg["page"]
    assert book["fiscal_year"] == cfg["fiscal_year"] and book["edition"] == "approved"


def test_plain_names_schools_included(county):
    _, d = county
    assert [r["name"] for r in d["rows"]] == PLAIN
    assert [r["printed"] for r in d["rows"]] == ["County General", "General Roads", "General Purpose School",
                                                 "Debt Service", "General Purpose Capital Projects",
                                                 "School Transportation"]


def test_cents_are_rate_over_total_rate_and_add_up_to_100(county):
    _, d = county
    total = 2100
    assert sum(r["value"] for r in d["rows"]) == total and d["total_cents"] == 100
    assert sum(r["cents"] for r in d["rows"]) == 100
    for r in d["rows"]:
        assert abs(r["cents"] - Fraction(100 * r["value"], total)) < 1, r["name"]
    # 53.81 / 6.67 / 17.57 / 18.57 / 1.90 / 1.48 round to 54 / 7 / 18 / 19 / 2 / 1 = 101: the row rounded up the most
    # (Schools and Debt service tie at 0.43 of a cent; the first listed) gives one back, and the page names it
    assert [r["cents"] for r in d["rows"]] == [54, 7, 17, 19, 2, 1]
    assert [r["name"] for r in d["rows"] if r["moved"]] == ["Schools"]
    assert "add up to 101" in d["rounding"] and d["rounding"].endswith(": Schools.")


def test_every_row_cites_the_resolution_page(county):
    _, d = county
    for r in d["rows"]:
        assert r["src"]["url"].endswith("#page=20") and r["src"]["page"] == 20
    assert d["src"]["url"].endswith("#page=20")


def test_rates_are_checked_against_the_books_property_tax_lines(county):
    """Every fund the book budgets CURRENT PROPERTY TAX (40110) for is a row, and each amount is the same multiple of
    its rate: 103,056,000 / 12,768,000 / 35,568,000 / 3,648,000 are 91,200,000 x 1.130 / 0.140 / 0.390 / 0.040."""
    _, d = county
    assert [(c["label"], c["amount"], c["src"]["page"]) for c in d["check_cites"]] == [
        ("County General", "103,056,000", 30), ("General Roads", "12,768,000", 91),
        ("Debt Service", "35,568,000", 99), ("General Purpose Capital Projects", "3,648,000", 105)]
    assert d["per_dollar"] == T["per_dollar"].format(amount="91,200,000")


def test_only_the_general_fund_row_links_to_the_general_fund_dollar(county):
    _, d = county
    assert [r["name"] for r in d["rows"] if r["to_dollar"]] == ["County general fund"]


# ---- missing or partial data fails loudly -------------------------------------------------------------------------

def split_with(cfg, fin=None, change=None):
    cfg = copy.deepcopy(cfg)
    if change:
        change(cfg)
    _, bg = county_budget(fin)
    return property_tax.split(bg, cfg, "101")


@pytest.mark.parametrize("change,match", [
    (lambda c: c["funds"].pop(2), "do not add up"),                                   # Schools left out
    (lambda c: (c["funds"].pop(1), c.update(total_as_printed="$1.960", rate_as_printed="$1.96")),
     "budgets account 40110 in fund\\(s\\) 131"),                                  # a fund the book taxes left out
    (lambda c: c["funds"][2].update(rate="0.370"), "do not add up"),                  # one rate wrong
    (lambda c: (c["funds"][1].update(rate="0.040"), c["funds"][4].update(rate="0.140")), "same multiple"),  # swapped
    (lambda c: c.update(total_as_printed="$2.200"), "do not add up"),
    (lambda c: c.update(rate_as_printed="$2.20"), "Section 1"),
    (lambda c: c["funds"][0].update(rate="1.13"), "not a rate as printed"),
    (lambda c: c["funds"][2].update(rate="0.000"), "above zero"),
    (lambda c: c.update(book="fy2099-approved"), "not in finance.json"),
    (lambda c: c["funds"][2].update(fund="141"), "no account 40110 line"),
    (lambda c: c.update(check_column="FY 2026 Amended"), "not adopted"),
])
def test_wrong_or_partial_rates_fail_the_split(cfg, change, match):
    with pytest.raises(fin_views.FinanceError, match=match):
        split_with(cfg, change=change)


def test_a_missing_property_tax_line_in_the_book_fails(cfg):
    """The book reading lost a fund's current property tax line (or all of them): the rates cannot be checked."""
    fin = json.loads(COUNTY_FIN.read_text(encoding="utf-8"))
    taxed = [x for x in fin["budget_lines"] if x["book_id"] == "fy2027-approved" and x.get("account_code") == "40110"]
    assert len(taxed) == 4
    next(x for x in taxed if x["fund_no"] == "151")["account_code"] = "40111"
    with pytest.raises(fin_views.FinanceError, match="151 have no account 40110 line"):
        split_with(cfg, fin=fin)
    for x in taxed:
        x["account_code"] = "40111"
    with pytest.raises(fin_views.FinanceError, match="prints no account 40110 line"):
        split_with(cfg, fin=fin)


@pytest.mark.parametrize("edit,match", [
    (lambda c: c.pop("resolution"), "`resolution`"),
    (lambda c: c.pop("page"), "`page`"),
    (lambda c: c.update(funds=c["funds"][:1]), "two or more"),
    (lambda c: c["funds"][3].pop("rate"), "`rate`"),
    (lambda c: c["funds"][3].pop("fund"), "`fund`"),
    (lambda c: c["funds"][3].update(name="Schools"), "share a `name`"),
])
def test_a_partial_config_fails_to_load(tmp_path, monkeypatch, cfg, edit, match):
    import yaml
    c = copy.deepcopy(cfg)
    edit(c)
    d = tmp_path / "localities" / "x"
    d.mkdir(parents=True)
    (d / property_tax.FILE).write_text(yaml.safe_dump(c), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    with pytest.raises(fin_views.FinanceError, match=match):
        property_tax.load("x")


def test_a_body_without_a_config_shows_no_bar():
    assert property_tax.load("clarksville-tn") is None
    _, bg = county_budget()
    assert property_tax.split(bg, None) is None


def test_no_sum_or_amount_sort_in_property_tax():
    """Adding goes through collector.fin_checks (budget-reconcile/*); rows are never sorted by amount (neutrality/*)."""
    import ast
    src = (ROOT / "sitegen" / "property_tax.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("sum", "fsum"), node.lineno
            if node.func.id == "sorted":
                assert not node.keywords, node.lineno             # fund numbers in an error message only
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr != "sort", node.lineno


# ---- the rendered page ----------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def site_out(tmp_path_factory):
    out = tmp_path_factory.mktemp("proptax") / "site"
    build(ROOT / "data" / "facts.json", out, target="pages")
    return out


@pytest.fixture(scope="module")
def page(site_out):
    return (site_out / "finance" / "index.html").read_text(encoding="utf-8")


def section(page):
    i = page.index('<section aria-labelledby="proptax-h" class="dollar proptax" id="property-tax-dollar">')
    return page[i:page.index("</section>", i)]


def text_of(s):
    return html_mod.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)))


def test_the_bar_sits_above_the_general_fund_dollar_on_the_county_page_only(site_out, page):
    assert page.index('id="property-tax-dollar"') < page.index('id="general-fund-dollar"')
    assert 'id="property-tax-dollar"' not in (site_out / "city" / "finance" / "index.html").read_text(encoding="utf-8")


def test_page_shows_rate_rows_and_table(page, county):
    _, d = county
    sec = section(page)
    assert f'<h2 id="proptax-h">{T["heading"]}</h2>' in sec
    txt = text_of(sec)
    assert "$2.10 per $100 of assessed value" in txt
    assert "as adopted" in txt and "Schools also get state and federal money, which is not shown here." in txt
    segs = re.findall(r'<span class="dseg[^"]*" style="--n: (\d+)"', sec)
    assert [int(s) for s in segs] == [r["cents"] for r in d["rows"]]
    items = re.findall(r'<li class="drow" style="--n: (\d+)">\s*<span class="drow-name">(.*?)</span>\s*'
                       r'<span class="drow-c">', sec, re.S)
    assert [text_of(n).strip().split(" How the")[0] for _, n in items] == PLAIN
    rows = re.findall(r'<tr class="fact[^"]*" data-fact-id="(proptax/[^"]+)">', sec)
    assert rows == [r["fact_id"] for r in d["rows"]] + [d["total_fact_id"]]
    cells = re.findall(r'<td class="num c-cents"[^>]*>([^<]+)</td>\s*<td class="num c-amt"[^>]*>([^<]+)</td>', sec)
    assert cells == [(r["cents_words"], html_mod.escape(r["rate"])) for r in d["rows"]] + [("100 cents", "$2.100")]
    # each row and the total cite the resolution's page in the book
    assert len(re.findall(r'href="[^"]+FY%202027%20Approved%20Budget\.pdf#page=20"', sec)) >= len(d["rows"]) + 1
    assert "<details open" not in sec


def test_general_fund_row_links_to_the_bar_below(page):
    sec = section(page)
    assert len(re.findall(r'href="#general-fund-dollar"', sec)) == 1
    assert re.search(r'<a href="#general-fund-dollar">County general fund</a>', sec)


def test_page_text_is_neutral(page):
    from test_fin_pages import FIN_BANNED
    m = FIN_BANNED.search(text_of(section(page)))
    assert m is None, m and m.group(0)


def test_site_checks_know_every_property_tax_fact_id(site_out, county):
    """qa.site_checks `unverified` (the deploy runs it): every data-fact-id on a page must be a known fact."""
    from qa import site_checks
    fin, d = county
    facts = json.loads((ROOT / "data" / "facts.json").read_text(encoding="utf-8"))
    rel = "finance/index.html"
    pg = {rel: site_checks.parse(site_out / rel)}
    on_page = {f for f in pg[rel].fact_ids if f.startswith("proptax/")}
    assert on_page == property_tax.fact_ids(fin, "montgomery-tn") == {r["fact_id"] for r in d["rows"]} | {d["total_fact_id"]}
    assert on_page <= site_checks.finance_fact_ids(fin, "montgomery-tn")

    def problems(**kw):
        return [p for p in site_checks.check_unverified(site_out, pg, facts, internal=False, fin=fin, **kw)
                if "proptax/" in p]
    assert problems(fin_locality="montgomery-tn") == []
    assert len(problems()) == len(on_page)                 # not weakened: without the locality every row fails
    pg[rel].fact_ids.append(f"proptax/{d['book_id']}/no-such-fund")
    assert [p for p in problems(fin_locality="montgomery-tn") if "no-such-fund" in p]


def test_a_broken_config_fails_the_build(tmp_path, monkeypatch, cfg):
    """A config with a wrong rate never builds a page: the build stops with the reason."""
    bad = copy.deepcopy(cfg)
    bad["funds"][2]["rate"] = "0.370"
    monkeypatch.setattr(property_tax, "load", lambda locality: bad)
    with pytest.raises(BuildError, match="do not add up"):
        build(ROOT / "data" / "facts.json", tmp_path / "site", target="pages")
