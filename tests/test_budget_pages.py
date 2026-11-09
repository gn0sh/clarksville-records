"""finance-contracts F13/F14: Finance index, fund pages and the Capital projects page, built from the FIXTURE
site/fixtures/finance.sample.json (fund 901, capital fund 951, one book). Problem-key families: budget-reconcile/*,
provenance/*, neutrality/*, budget-edition/*."""
import copy
import html as html_mod
import json
import re

import pytest

from conftest import ROOT, parse
from sitegen import budget_views, config, fin_views, views
from test_fin_pages import FIN, FIN_BANNED, build_with, main_of, rows

T = config.FIN_TEXT
B = T["budget"]
BOOK_URL = "https://example.invalid/fixture/finance/budget-fy2027.pdf"


@pytest.fixture(scope="module")
def fin():
    return json.loads(FIN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bpages(tmp_path_factory):
    return build_with(tmp_path_factory.mktemp("budget"))


def text_of(html):
    return html_mod.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)))


def row_text(html, fid, first=True):
    hits = [r for r in rows(html) if r.attrs["data-fact-id"] == fid]
    assert hits, fid
    return re.sub(r"\s+", " ", hits[0 if first else -1].all_text())


def budget_pages(pages):
    return {k: v for k, v in pages.items() if k.startswith(("finance/", "capital/"))}


def two_books(fin):
    """The fixture with a second, older book holding a copy of fund 901's lines (different columns)."""
    f = copy.deepcopy(fin)
    old = copy.deepcopy(f["books"][0])
    old.update(id="fy2025-approved", title="FIXTURE Example County Budget FY2025", fiscal_year=2025,
               columns=[{"fiscal_year": 2023, "header_as_printed": "FY 23 Actuals", "kind": "actual"},
                        {"fiscal_year": 2024, "header_as_printed": "FY 24 Amended", "kind": "amended"},
                        {"fiscal_year": 2025, "header_as_printed": "FY 25 Projection", "kind": "adopted"}])
    f["books"].append(old)
    for x in [x for x in fin["budget_lines"] if x["fund_no"] == "901"]:
        y = copy.deepcopy(x)
        y["id"] = x["id"].replace("fy2027-approved", "fy2025-approved")
        y["book_id"] = "fy2025-approved"
        y["scope_line_ids"] = [i.replace("fy2027-approved", "fy2025-approved") for i in x["scope_line_ids"]]
        for c, col in zip(y["cells"], old["columns"]):
            c.update(header_as_printed=col["header_as_printed"], fiscal_year=col["fiscal_year"])
        f["budget_lines"].append(y)
    f["budget_lines"].sort(key=lambda x: x["id"])
    f["coverage"]["n_books"] = 2
    return f


# ---- pages, nav, fixed strings ------------------------------------------------------------------------------------

def test_pages_are_written_and_nav_drops_the_coming_chips(bpages):
    for rel in ("finance/index.html", "finance/901.html", "finance/951.html", "capital/index.html"):
        assert rel in bpages, rel
    assert "finance.html" not in bpages and "capital-projects.html" not in bpages
    nav = bpages["about.html"][bpages["about.html"].index('<nav id="site-nav"'):]
    assert re.search(r'href="finance/index\.html">Finance</a>', nav)
    assert re.search(r'href="capital/index\.html">Capital projects</a>', nav)
    assert "chip-coming" not in nav
    assert 'finance/index.html" aria-current="page"' in bpages["finance/901.html"]
    assert 'capital/index.html" aria-current="page"' in bpages["capital/index.html"]


def test_without_budget_lines_finance_and_capital_stay_coming(tmp_path, fin):
    f = copy.deepcopy(fin)
    f["budget_lines"], f["books"] = [], []
    pages = build_with(tmp_path, fin=f)
    assert "finance.html" in pages and "capital-projects.html" in pages
    assert not any(k.startswith(("finance/", "capital/")) for k in pages)
    assert "contracts/index.html" in pages


def test_capital_fund_not_in_the_file_keeps_capital_coming(tmp_path):
    pages = build_with(tmp_path, capital_fund="999")
    assert "finance/index.html" in pages and "capital-projects.html" in pages and "capital/index.html" not in pages


def test_coverage_sentence_and_notes_are_exact_strings(bpages, fin):
    cov = "19 budget lines from 1 books; 2 totals do not add up as printed and are marked."
    assert budget_views.coverage_sentence(fin["coverage"]) == cov
    for rel, html in budget_pages(bpages).items():
        main = main_of(html)
        assert main.count(cov) == 1, rel
        assert main.index(cov) < main.index("<table"), rel
    assert f">{T['notes']['e']}<" in main_of(bpages["finance/index.html"])
    fund = main_of(bpages["finance/901.html"])
    assert fund.count(f">{T['notes']['e']}<") == 2  # under the h1 and repeated in Transfers and available funds
    cap = main_of(bpages["capital/index.html"])
    assert cap.index(f">{T['notes']['d']}<") < cap.index("<table")


def test_rendered_budget_pages_have_no_banned_words_outside_config_text(bpages):
    fixed = [T["notes"][k] for k in T["notes"]] + [g["text"] for g in T["glossary"]]
    for rel, html in budget_pages(bpages).items():
        text = re.sub(r"<[^>]+>", " ", main_of(html))
        for s in fixed:
            text = text.replace(s, "")
        m = FIN_BANNED.search(text)
        assert m is None, (rel, m and m.group(0))


@pytest.mark.parametrize("name", ["fin_index.html.j2", "fin_fund.html.j2", "fin_capital.html.j2",
                                  "_budget_macros.html.j2"])
def test_budget_templates_have_no_banned_words(name):
    raw = (ROOT / "site" / "templates" / name).read_text(encoding="utf-8")
    raw = re.sub(r"\{#.*?#\}|\{%.*?%\}", "", raw, flags=re.S)
    m = FIN_BANNED.search(raw)
    assert m is None, (name, m and m.group(0))


# ---- finance index ------------------------------------------------------------------------------------------------

def test_index_lists_books_and_funds_in_book_order_with_no_amounts(bpages):
    main = main_of(bpages["finance/index.html"])
    assert "FIXTURE Example County Budget FY2027" in main and BOOK_URL in main
    ids = [r.attrs["data-fact-id"] for r in rows(bpages["finance/index.html"])]
    assert ids == ["fund/901", "fund/951"]
    assert not re.search(r"\d{1,3},\d{3}", text_of(main))
    assert "chart" not in main and "<svg" not in main


def test_actuals_missing_sentence_from_the_columns(tmp_path, fin):
    pages = build_with(tmp_path, fin=two_books(fin))
    main = main_of(pages["finance/index.html"])
    assert "FY2024 actuals are not in these books." in main  # actuals for 2023 and 2025 only
    assert main.index("FY2027") < main.index("FY2025")       # newest book first


# ---- fund page: columns, amounts, sections ------------------------------------------------------------------------

def test_column_headers_are_the_books_own_plus_kind(bpages):
    html = main_of(bpages["finance/901.html"])
    heads = re.findall(r'<th scope="col" class="num">([^<]+)<br><span class="kind">(?:<a [^>]+>)?([^<]+)<', html)
    assert heads[:3] == [("FY 2025 Actuals", "Actual"), ("FY 2026 Amended", "Amended budget"),
                         ("FY 2027 Budget", "Adopted budget")]
    # first use of a kind word on the page links to the glossary, later uses do not
    tables = "".join(re.findall(r"<table.*?</table>", html, flags=re.S))
    assert tables.count('glossary.html#actual"') == 1


def test_no_difference_percent_arrow_or_county_total(bpages):
    for rel, html in budget_pages(bpages).items():
        main = main_of(html)
        heads = " ".join(re.findall(r'<th scope="col"[^>]*>(.*?)</th>', main, flags=re.S))
        assert not re.search(r"Difference|Change|Increase|Percent|%", heads), rel
        assert not re.search(r"[↑↓▲▼↗↘]|sparkline|<svg|<canvas", main), rel
        assert "county-wide total" not in text_of(main).replace(T["notes"]["e"], ""), rel


def test_amounts_are_as_printed_with_parentheses_and_blanks(bpages):
    html = bpages["finance/901.html"]
    t = row_text(html, "fy2027-approved/p23/r1")
    assert "(1,200)" in t and "minus 1,200" in t
    t = row_text(html, "fy2027-approved/p21/r2")
    assert B["not_printed"] in t and "–" in t
    for r in rows(html):
        assert not re.search(r"\$|\d+\.\d\d\b|\d[KM]\b", r.all_text()), r.attrs["data-fact-id"]


def test_sections_in_order_and_transfers_listed_apart(bpages):
    main = main_of(bpages["finance/901.html"])
    i = [main.index(f'id="fy2027-approved-{k}-h"') for k in ("revenue", "spending", "other")]
    assert i == sorted(i)
    other = main[i[2]:]
    for fid in ("fy2027-approved/p10/r4", "fy2027-approved/p22/r1", "fy2027-approved/p23/r1"):
        assert f'data-fact-id="{fid}"' in other, fid
        assert f'data-fact-id="{fid}"' not in main[:i[2]], fid


def test_departments_are_anchors_on_the_fund_page(bpages):
    main = main_of(bpages["finance/901.html"])
    for dept in ("EXAMPLE DEPARTMENT A", "EXAMPLE DEPARTMENT B"):
        m = re.search(r'<details class="fin-group" id="(fy2027-approved-spending-\d+)"[^>]*>\s*<summary><span '
                      r'class="g-head">' + dept, main)
        assert m, dept
        assert f'href="#{m.group(1)}"' in main
    assert 'id="l-fy2027-approved-p20-r1"' in main


def test_rows_keep_book_order_by_page_and_row_not_text(tmp_path, fin):
    f = copy.deepcopy(fin)
    f["budget_lines"].sort(key=lambda x: x["id"], reverse=True)
    html = build_with(tmp_path, fin=f)["finance/901.html"]
    ids = [r.attrs["data-fact-id"] for r in rows(html)]
    spending = [i for i in ids if "/p2" in i and "/p22/" not in i and "/p23/" not in i]
    assert spending[:6] == [f"fy2027-approved/p20/r{n}" for n in range(1, 7)]
    assert budget_views.line_key("b/p100/r2") > budget_views.line_key("b/p28/r10")


def test_book_with_different_columns_gets_its_own_tables(tmp_path, fin):
    pages = build_with(tmp_path, fin=two_books(fin))
    main = main_of(pages["finance/901.html"])
    for table in re.findall(r"<table.*?</table>", main, flags=re.S):
        new, old = "FY 2027 Budget" in table, "FY 25 Projection" in table
        assert new != old  # never two books' columns in one table
    assert main.index('id="fy2027-approved"') < main.index('id="fy2025-approved"')
    assert "This fund is not in FIXTURE Example County Budget FY2025." in main_of(pages["finance/951.html"])


# ---- check states (AC-F2) ------------------------------------------------------------------------------------------

def test_check_states_in_words(bpages):
    html = bpages["finance/901.html"]
    assert "Total as printed" in row_text(html, "fy2027-approved/p10/r3")
    assert B["check"]["exact"] in row_text(html, "fy2027-approved/p10/r3")
    assert "Subtotal as printed" in row_text(html, "fy2027-approved/p20/r5")
    assert B["check"]["within_rounding"] == "Adds up within rounding"
    assert B["check"]["within_rounding"] in row_text(html, "fy2027-approved/p20/r6")
    t = row_text(html, "fy2027-approved/p21/r3")
    assert B["check"]["does_not_add_up"] == "As printed, does not add up"
    assert B["check"]["does_not_add_up"] in t
    assert "3,100" in t  # shown as printed, never corrected


def flag_block(html, block_id):
    """The fact ids in a flagged block, and whether anything in it is a collapsible group."""
    div = next(n for n in parse(html).walk() if n.attrs.get("id") == block_id)
    nodes = list(div.walk())
    return ([n.attrs["data-fact-id"] for n in nodes if n.tag == "tr" and "data-fact-id" in n.attrs],
            any(n.tag == "details" and "fin-group" in n.attrs.get("class", "") for n in nodes))


def test_total_that_does_not_add_up_lists_its_lines_open(bpages):
    main = main_of(bpages["finance/901.html"])
    ids, collapsible = flag_block(bpages["finance/901.html"], "chk-fy2027-approved-p21-r3")
    assert not collapsible  # shown, never collapsed
    assert ids == ["fy2027-approved/p21/r3", "fy2027-approved/p21/r1", "fy2027-approved/p21/r2"]
    assert 'href="#chk-fy2027-approved-p21-r3"' in main  # the row links to its lines
    cap = main_of(bpages["capital/index.html"])  # a printed total with no lines above it says so
    assert 'id="chk-fy2027-approved-p100-r4"' in cap and B["flagged_no_lines"] in cap


def test_not_checked_and_held_lines_say_why_plainly(tmp_path, fin):
    f = copy.deepcopy(fin)
    by_id = {x["id"]: x for x in f["budget_lines"]}
    by_id["fy2027-approved/p21/r2"].update(held="column-align")
    for c in by_id["fy2027-approved/p21/r2"]["cells"]:
        c["dollars"] = None
    by_id["fy2027-approved/p21/r3"].update(held="scope-held")
    by_id["fy2027-approved/p21/r3"]["check"]["state"] = "not_checked"
    html = build_with(tmp_path, fin=f)["finance/901.html"]
    for fid, check in (("fy2027-approved/p21/r2", "column-align"), ("fy2027-approved/p21/r3", "scope-held")):
        t = row_text(html, fid)
        assert "Not confirmed" in t and T["held"][check] in t and "Read it yourself" in t, fid
        assert "hard to read" not in t
        assert "450" not in t and "3,450" not in t
    assert "hard to read" not in main_of(html)


def test_tagged_line_moved_to_its_section_is_listed_under_its_total(tmp_path, fin):
    """A total that adds a transfer listed under Transfers and available funds links to it, and the flagged block
    lists it with the total's other lines."""
    f = copy.deepcopy(fin)
    by_id = {x["id"]: x for x in f["budget_lines"]}
    by_id["fy2027-approved/p21/r3"]["scope_line_ids"].append("fy2027-approved/p22/r1")
    html = build_with(tmp_path, fin=f)["finance/901.html"]
    t = row_text(html, "fy2027-approved/p21/r3")
    assert B["moved"] in t and "Transfer to Capital Projects Fund" in t
    assert 'href="#l-fy2027-approved-p22-r1"' in html
    ids, _ = flag_block(html, "chk-fy2027-approved-p21-r3")
    assert "fy2027-approved/p22/r1" in ids


def test_edition_note_links_both_lines(tmp_path, fin):
    f = two_books(fin)
    by_id = {x["id"]: x for x in f["budget_lines"]}
    by_id["fy2027-approved/p10/r1"]["edition_differs"] = ["fy2025-approved/p10/r1"]
    by_id["fy2025-approved/p10/r1"]["edition_differs"] = ["fy2027-approved/p10/r1"]
    html = build_with(tmp_path, fin=f)["finance/901.html"]
    assert T["edition_note"] == "The two books print different figures for this line. Both are shown."
    t = row_text(html, "fy2027-approved/p10/r1")
    assert T["edition_note"] in t and "FIXTURE Example County Budget FY2025, p. 10" in t
    assert 'href="#l-fy2025-approved-p10-r1"' in html and 'href="#l-fy2027-approved-p10-r1"' in html


def test_unknown_held_check_or_state_or_line_fails_the_build(tmp_path, fin):
    for change, word in ((lambda x: x.update(held="no-such-check"), "no-such-check"),
                         (lambda x: x.update(scope_line_ids=["fy2027-approved/p99/r1"]), "p99")):
        f = copy.deepcopy(fin)
        change(next(x for x in f["budget_lines"] if x["id"] == "fy2027-approved/p21/r3"))
        with pytest.raises(Exception, match=word):
            build_with(tmp_path / word, fin=f)


# ---- provenance (AC-F3) and names (AC-F9) ---------------------------------------------------------------------------

def test_every_budget_row_cites_its_page_with_fetch_date(bpages):
    n = 0
    for rel, html in budget_pages(bpages).items():
        for r in rows(html):
            n += 1
            links = [a.attrs["href"] for a in r.walk() if a.tag == "a" and a.attrs.get("target") == "_blank"]
            pages = [int(m.group(1)) for h in links if h.startswith(BOOK_URL) and (m := re.search(r"#page=(\d+)$", h))]
            assert pages, (rel, r.attrs["data-fact-id"])
            fid = r.attrs["data-fact-id"]
            if "/p" in fid:
                assert pages == [int(fid.split("/p")[1].split("/")[0])], fid
            assert re.search(r"fetched \d{4}-\d{2}-\d{2}", r.all_text()), fid
            assert "Report an error" in r.all_text()
    assert n >= 19


def test_every_amount_sits_in_a_cited_row(bpages):
    for rel, html in budget_pages(bpages).items():
        doc = parse(html)
        for td in (n for n in doc.walk() if n.tag == "td" and "num" in n.attrs.get("class", "").split()):
            p = td.parent
            while p is not None and p.tag != "tr":
                p = p.parent
            assert p is not None and "data-fact-id" in p.attrs, rel


def test_capital_page_has_no_total_across_lines_and_no_cost_column(bpages):
    main = main_of(bpages["capital/index.html"])
    heads = re.findall(r'<th scope="col"[^>]*>(.*?)</th>', main, flags=re.S)
    assert not any(re.search(r"cost", h, re.I) for h in heads)
    assert B["project_line"] in " ".join(heads)
    ids = [r.attrs["data-fact-id"] for r in rows(bpages["capital/index.html"])]
    assert set(ids) <= {x for x in ids if x.startswith("fy2027-approved/p100/")}  # the capital fund's lines only
    # the only totals are the book's own printed lines
    totals = re.findall(r"Total as printed", main)
    assert len(totals) == 2 + 1  # p100/r3, p100/r4, and p100/r4 again in its flagged block
    assert "FUND (951, FIXTURE Example County Budget FY2027, pp. 100-100)" in main


def test_capital_filters_are_a_hidden_form_until_scripts_run(bpages):
    main = main_of(bpages["capital/index.html"])
    assert '<form id="cap-filters"' in main and "hidden>" in main[main.index('<form id="cap-filters"'):][:200]
    assert '<label for="f-name">Project name</label>' in main and '<label for="f-book">Book</label>' in main
    assert 'src="../static/finance.js"' in bpages["capital/index.html"]


def test_two_funds_share_one_skeleton(bpages):
    from test_site_neutrality import skeleton

    def shape(html):
        return [t for t in skeleton(html) if t[0] in ("h1", "h2", "section", "nav", "text")][:8]
    assert shape(bpages["finance/901.html"])[:4] == shape(bpages["finance/951.html"])[:4]


def test_no_sort_by_amount_in_budget_views():
    src = (ROOT / "sitegen" / "budget_views.py").read_text(encoding="utf-8")
    for m in re.finditer(r"sort\(key=([^\n]*)|sorted\([^\n]*key=([^\n]*)", src):
        key = m.group(1) or m.group(2) or ""
        assert not re.search(r"dollars|cells|amount|len\(|count|n_", key), key


def test_budget_page_names_link_to_officials_where_known(bpages, facts):
    """AC-F9: finance.json names no committee member, so the budget pages carry no person names; any official's
    name that appears is a link (the same person macro as the contracts pages)."""
    for rel, html in budget_pages(bpages).items():
        text = text_of(main_of(html))
        for o in facts["officials"]:
            if o["name"] in text:
                assert f'officials/{o["id"]}.html' in html, (rel, o["name"])


def test_glossary_words_toggle_on_budget_pages(bpages):
    for rel in ("finance/index.html", "finance/901.html", "capital/index.html"):
        assert T["contracts"]["words_toggle"] in bpages[rel]
    assert "glossary.html#capital-project" in bpages["capital/index.html"]


def test_views_nav_without_budget_is_unchanged(facts):
    nav = views.site_context(facts)["nav"]
    fin_entry = next(e for e in nav if e["label"] == "Finance")
    assert fin_entry["href"] == "finance.html" and fin_entry["coming"] is True


def test_fin_views_held_check_is_shared():
    assert fin_views.held_check(None, "x") is None
    with pytest.raises(fin_views.FinanceError):
        fin_views.held_check("nope", "x")


def test_site_checks_know_the_budget_pages(fin):
    from qa import site_checks
    ids = site_checks.finance_fact_ids(fin)
    assert "fy2027-approved/p20/r1" in ids and "fund/901" in ids
    for rel, kind in (("finance/index.html", "finance_index"), ("finance/901.html", "fund"),
                      ("capital/index.html", "capital")):
        assert site_checks.page_type(rel) == kind and kind in site_checks.NARROW_TYPES
    assert site_checks.MAX_FILES == config.MAX_FILES == 500  # under the artifact limit of 511 files


# ---- difference notes (owner's decision 2026-11-08) ----------------------------------------------------------------

def notes_in(html, block_id=None, fid=None):
    """The b-diff notes in the row that follows a total (the first such total on the page, or in a flagged block)."""
    doc = parse(html)
    nodes = list(doc.walk())
    if block_id:
        nodes = list(next(n for n in nodes if n.attrs.get("id") == block_id).walk())
    trs = [n for n in nodes if n.tag == "tr" and ("data-fact-id" in n.attrs or "b-diffrow" in n.attrs.get("class", ""))]
    for i, tr in enumerate(trs):
        if tr.attrs.get("data-fact-id") == fid or (block_id and i == 0):
            nxt = trs[i + 1] if i + 1 < len(trs) else None
            if nxt is None or "b-diffrow" not in nxt.attrs.get("class", ""):
                return []
            return [re.sub(r"\s+", " ", li.all_text()).strip() for li in nxt.walk() if li.tag == "li"]
    return []


def line_of(fin, lid):
    return next(x for x in fin["budget_lines"] if x["id"] == lid)


def test_note_numbers_equal_the_check_cells(bpages, fin):
    x = line_of(fin, "fy2027-approved/p21/r3")
    pc = x["check"]["per_cell"][1]
    assert (pc["printed"], pc["sum"], pc["diff"]) == (3100, 3000, 100)
    want = "FY 2026 Amended: the book prints 3,100. The lines printed above it add up to 3,000. " \
           "The printed total is 100 higher."
    assert notes_in(bpages["finance/901.html"], fid="fy2027-approved/p21/r3") == [want]
    assert notes_in(bpages["finance/901.html"], block_id="chk-fy2027-approved-p21-r3") == [want]  # same note in the section


def test_note_with_no_lines_above_the_total(bpages):
    want = "FY 2026 Amended: the book prints this total, 25,000, with no lines above it to add."
    assert notes_in(bpages["capital/index.html"], fid="fy2027-approved/p100/r4") == [want]


def test_within_rounding_note_is_one_short_line(bpages, fin):
    pc = line_of(fin, "fy2027-approved/p20/r6")["check"]["per_cell"][0]
    assert pc["diff"] == 1
    n = notes_in(bpages["finance/901.html"], fid="fy2027-approved/p20/r6")
    assert n == ["FY 2025 Actuals: off by 1 because the book rounds each line to whole dollars."]


def test_negative_difference_says_lower(fin):
    x = copy.deepcopy(line_of(fin, "fy2027-approved/p21/r3"))
    x["check"]["per_cell"][1].update(printed=3000, sum=3900, diff=-900)
    assert budget_views.diff_notes(x) == [
        "FY 2026 Amended: the book prints 3,000. The lines printed above it add up to 3,900. "
        "The printed total is 900 lower."]
    x["check"]["per_cell"][1].update(printed=-1200, sum=0, diff=-1200)
    x["scope_line_ids"] = []
    assert budget_views.diff_notes(x) == [
        "FY 2026 Amended: the book prints this total, (1,200), with no lines above it to add."]


def test_held_and_not_checked_totals_get_no_numbers(fin):
    x = copy.deepcopy(line_of(fin, "fy2027-approved/p21/r3"))
    x["check"]["state"] = "not_checked"
    assert budget_views.diff_notes(x) == []


def test_real_trustee_note_text():
    real = json.loads((ROOT / "data" / "finance.json").read_text(encoding="utf-8"))
    x = next(x for x in real["budget_lines"] if x["id"] == "fy2027-approved/p47/r37")
    assert budget_views.diff_notes(x) == [
        "FY 2025 Actuals: the book prints 1,039,953. The lines printed above it add up to 1,039,952. "
        "The printed total is 1 higher.",
        "FY 2026 Amended: the book prints 1,226,777. The lines printed above it add up to 1,230,677. "
        "The printed total is 3,900 lower."]


# ---- page weight (finance-pages/page-weight) ----------------------------------------------------------------------

def _split_build(tmp_path, monkeypatch, fin):
    """Build two_books(fin) with PAGE_BYTES just under fund 901's whole page, so it must split by heading."""
    from qa import site_checks
    whole = build_with(tmp_path / "whole", fin=two_books(fin))
    size = len(whole["finance/901.html"].encode("utf-8"))
    monkeypatch.setattr(config, "PAGE_BYTES", size - 1)
    monkeypatch.setattr(config, "PAGE_TARGET", size // 3)
    pages = build_with(tmp_path / "split", fin=two_books(fin))
    site = tmp_path / "split" / "build" / "site"
    assert site_checks.check_links(site, {r: site_checks.parse(site / r) for r in pages}, no_export=True) == []
    return whole, pages, size


def test_a_fund_page_over_the_limit_is_split_by_heading_and_keeps_every_line_once(tmp_path, monkeypatch, fin):
    whole, pages, size = _split_build(tmp_path, monkeypatch, fin)
    parts = sorted(r for r in pages if re.fullmatch(r"finance/901(-\d+)?\.html", r))
    assert len(parts) >= 2 and "finance/901-2.html" in parts
    f = two_books(fin)
    lines = [x for x in f["budget_lines"] if x["fund_no"] == "901"]
    for x in lines:   # every row anchored on exactly one part, with its own fact id
        hits = [r for r in parts if f'id="{budget_views.anchor(x["id"])}"' in pages[r]]
        assert len(hits) == 1, (x["id"], hits)
    flagged = [x for x in lines if x["check"] and x["check"]["state"] == "does_not_add_up"]
    assert flagged
    for x in flagged:  # the "does not add up" block sits on the same part as its total's row, with its notes
        block = "chk-" + budget_views.anchor(x["id"])[2:]
        where = [r for r in parts if f'id="{block}"' in pages[r]]
        assert len(where) == 1 and f'id="{budget_views.anchor(x["id"])}"' in pages[where[0]], x["id"]
        for note in budget_views.diff_notes(x):
            assert html_mod.escape(note, quote=False) in pages[where[0]] or note in text_of(pages[where[0]])
    cov = budget_views.coverage_sentence(f["coverage"])
    for r in parts:
        assert len(pages[r].encode("utf-8")) <= size - 1, r
        assert 'class="year-nav parts-nav"' in pages[r] and "This fund is on" in pages[r]
        assert cov in text_of(pages[r]) and T["notes"]["e"] in text_of(pages[r])
    # the union of the parts shows the same rows as the whole page
    rows_of = lambda html: sorted(r.attrs["data-fact-id"] for r in rows(html))  # noqa: E731
    assert sorted(i for r in parts for i in rows_of(pages[r])) == rows_of(whole["finance/901.html"])


def test_capital_page_parts_keep_every_project_line(tmp_path, monkeypatch, fin):
    whole = build_with(tmp_path / "whole", fin=fin)
    size = len(whole["capital/index.html"].encode("utf-8"))
    monkeypatch.setattr(config, "PAGE_BYTES", size - 1)
    monkeypatch.setattr(config, "PAGE_TARGET", size // 2)
    pages = build_with(tmp_path / "split", fin=fin)
    parts = sorted(r for r in pages if re.fullmatch(r"capital/index(-\d+)?\.html", r))
    rows_of = lambda html: sorted(r.attrs["data-fact-id"] for r in rows(html))  # noqa: E731
    assert sorted(i for r in parts for i in rows_of(pages[r])) == rows_of(whole["capital/index.html"])
    if len(parts) > 1:
        assert all("This page is on" in pages[r] for r in parts)
