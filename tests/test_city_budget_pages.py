"""City of Clarksville budget books (finance-contracts 10): city/finance/ built from the committed
data/localities/clarksville-tn/finance.json with the county's budget templates. Problem-key families:
budget-reconcile/*, provenance/*, neutrality/*, budget-edition/*."""
import html as html_mod
import json
import re

import pytest

from conftest import ROOT
from sitegen import budget_views, config
from sitegen.build import build

CITY_FIN = ROOT / "data" / "localities" / "clarksville-tn" / "finance.json"
B = config.FIN_TEXT["budget"]


def text_of(page: str) -> str:
    return html_mod.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page)))


def main_of(page: str) -> str:
    return page[page.index('<main id="main">'):page.index("</main>")]


@pytest.fixture(scope="module")
def fin():
    return json.loads(CITY_FIN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("city-budget") / "site"
    res = build(ROOT / "data" / "facts.json", out, target="pages")
    assert res["city_budget"] is True
    return out


@pytest.fixture(scope="module")
def pages(site):
    return {p.relative_to(site).as_posix(): p.read_text(encoding="utf-8") for p in site.rglob("*.html")}


def city_pages(pages):
    return {k: v for k, v in pages.items() if k.startswith("city/finance/")}


def test_one_page_per_fund_by_printed_name_and_one_for_the_report_totals(pages, fin):
    keys = {budget_views.fund_key(x) for x in fin["budget_lines"]}
    assert "report-totals" in keys and "general-fund" in keys
    for k in keys:
        assert f"city/finance/{k}.html" in pages, k
    idx = main_of(pages["city/finance/index.html"])
    assert "<h1>City budget</h1>" in idx
    assert '<div data-body="city">' in idx
    assert 'class="c-fundno"' not in idx                       # the city books print no fund number
    for k in keys:
        assert f'href="../../city/finance/{k}.html"' in idx


def test_books_listed_with_report_date_and_fy2025_linked_only(pages, fin):
    idx = text_of(main_of(pages["city/finance/index.html"]))
    assert "Fiscal Year 2027 Budget, as presented 5/29/2026" in idx
    assert "Fiscal Year 2026 Budget (Final Submission)" in idx and "Fiscal Year 2024 Budget" in idx
    for b in fin["books"]:
        d = b["report_dates"][0]
        src = next(s for s in fin["sources"] if s["id"] == b["source_id"])
        assert f'{src["url"]}#page={d["page"]}' in pages["city/finance/index.html"]
        assert f"Report date as printed: {d['as_printed']}" in idx
    # FY2025: the official book, linked only; its figures are in the FY2026 book's columns, said plainly
    assert 'href="https://www.clarksvilletn.gov/DocumentCenter/View/11392" data-ext="record"' in \
        pages["city/finance/index.html"]
    assert "Linked only, not read" in idx and "printed in the columns of the Fiscal Year 2026 Budget" in idx
    assert "View/11392" not in "".join(v for k, v in city_pages(pages).items() if k != "city/finance/index.html")


def test_fy2027_is_proposed_and_never_called_adopted(pages):
    gf = main_of(pages["city/finance/parking-commission.html"])
    assert re.search(r'2027 Mayor<br><span class="kind"><a href="../../glossary.html#proposed-budget">Proposed budget</a>',
                     gf)
    assert "From: Fiscal Year 2027 Budget, as presented 5/29/2026</caption>" in gf          # edition said once
    assert "as presented 5/29/2026, as presented 5/29/2026" not in gf
    assert not re.search(r"2027 Mayor<br><span class=\"kind\">(<a[^>]*>)?Adopted", gf)


def test_year_in_progress_actual_shows_the_report_date(pages):
    p = main_of(pages["city/finance/parking-commission.html"])
    for header, date in (("2026 ACTUAL", "05/29/2026"), ("2025 ACTUAL", "07/08/2025"), ("2023 ACTUAL", "06/28/2023")):
        assert re.search(rf'{header}<br><span class="kind">(<a[^>]*>)?Actual(</a>)?</span><br><span class="kind">'
                         rf'as of {re.escape(date)} \(report date\)</span>', p), header
        assert f'data-label="{header} Actual, as of {date} (report date)"' in p
    # a finished year's Actual column carries no date: "2025 ACTUAL" in the FY2027 book, "2024 ACTUAL" in FY2026
    assert '<th scope="col" class="num">2024 ACTUAL<br><span class="kind">Actual</span></th>' in p


def test_every_printed_total_shows_its_check_state(pages, fin):
    rows = {}
    for rel, page in city_pages(pages).items():
        for m in re.finditer(r'<tr class="fact b-(total|subtotal)" id="l-([^"]+)"[^>]*>(.*?)</tr>', page, re.S):
            rows[m.group(2)] = m.group(3)
    totals = [x for x in fin["budget_lines"] if x["row_role"] != "detail"]
    assert totals and len(rows) == len(totals)
    words = set(B["check"].values())
    for x in totals:
        row = rows[budget_views.anchor(x["id"])[2:]]
        assert x["check"] is not None
        assert B["check"][x["check"]["state"]] in row and any(w in row for w in words), x["id"]


def test_amounts_are_cents_as_printed_with_source_page(pages, fin):
    x = next(x for x in fin["budget_lines"] if x["book_id"] == "fy2027-presented"
             and budget_views.fund_key(x) == "parking-commission" and x["row_role"] == "detail"
             and any(c["as_printed"].startswith("-") for c in x["cells"]))
    page = pages["city/finance/parking-commission.html"]
    row = re.search(rf'<tr class="fact b-detail" id="{budget_views.anchor(x["id"])}".*?</tr>', page, re.S).group(0)
    for c in x["cells"]:
        assert c["as_printed"] in row
    neg = next(c for c in x["cells"] if c["as_printed"].startswith("-"))
    assert f'<span class="sr-only">minus {neg["as_printed"][1:]}</span>' in row
    src = next(s for s in fin["sources"] if s["id"] == "src-738ca3e830d6")
    assert f'href="{src["url"]}#page={x["page"]}"' in row


def test_every_city_fact_row_links_its_book_page(pages, fin):
    urls = {s["url"] for s in fin["sources"]}
    n = 0
    for rel, page in city_pages(pages).items():
        if rel == "city/finance/index.html":
            continue
        for row in re.findall(r'<tr class="fact b-[a-z]+"[^>]*>.*?</tr>', page, re.S):
            hrefs = re.findall(r'href="(https://[^"#]+)#page=(\d+)"', row)
            assert hrefs and all(u in urls for u, _ in hrefs), row[:200]
            n += 1
    assert n >= len(fin["budget_lines"])


def test_report_totals_page_and_net_section(pages):
    rt = text_of(main_of(pages["city/finance/report-totals.html"]))
    for label in ("TOTAL REVENUE", "TOTAL EXPENSE", "GRAND TOTAL"):
        assert label in rt
    gf = text_of(main_of(pages["city/finance/general-fund.html"]))
    assert B["sections"]["net"] in gf
    assert B["sections"]["other"] not in gf            # the city books tag no transfers: no empty section


def test_county_and_city_budget_link_each_other_the_same_way(pages):
    county = main_of(pages["finance/index.html"])
    city = main_of(pages["city/finance/index.html"])
    assert re.search(r'budget books have their own pages: <a href="../city/finance/index.html">City budget</a>', county)
    assert re.search(r'budget books have their own pages: <a href="../../finance/index.html">County budget</a>', city)
    assert "(report date)" not in "".join(v for k, v in pages.items() if k.startswith(("finance/", "capital/")))
    hub = pages["city/index.html"]
    card = re.search(r'<li class="hub-card" data-card="finance" id="card-finance">.*?</li>', hub, re.S).group(0)
    assert 'href="../city/finance/index.html"' in card and "chip-coming" not in card
    home = pages["index.html"]
    door = re.search(r'<li class="door"[^>]*data-door="money".*?</li>\s*</ul>', home, re.S) or \
        re.search(r'Public money.*?</ul>', home, re.S)
    assert 'href="city/finance/index.html"' in door.group(0) and 'href="finance/index.html"' in door.group(0)


def test_city_budget_official_record_is_the_city_page(pages):
    rec = config.SITE["official_records"]["city_finance"]["url"]
    assert rec in pages["city/finance/index.html"] and rec in pages["city/finance/general-fund.html"]
    assert rec not in pages["finance/index.html"]


def test_hub_card_names_the_books_from_the_data_and_index_says_what_is_not_read(pages, fin):
    # city-budget/coverage-undisclosed: one fixed sentence of what the reader does not read, with the official page
    hub = pages["city/index.html"]
    card = text_of(re.search(r'<li class="hub-card" data-card="finance" id="card-finance">.*?</li>', hub, re.S).group(0))
    assert budget_views.books_phrase(fin["books"]) in card and "{books}" not in card
    assert "FY2024 (adopted), FY2026 (final submission) and FY2027 (as presented 5/29/2026)" in card
    idx = main_of(pages["city/finance/index.html"])
    note = re.search(r'<p class="note" id="not-covered">.*?</p>', idx, re.S).group(0)
    nc = config.FIN_TEXT["budget_city"]["not_covered"]["text"]
    assert text_of(note).strip().startswith(nc)
    for part in ("Gas & Water", "CDE electric and broadband", "transit", "CDBG", "debt schedules"):
        assert part in nc
    assert f'href="{config.SITE["official_records"]["city_finance"]["url"]}"' in note
    assert 'id="not-covered"' not in pages["finance/index.html"]          # the county's index names none


def test_books_phrase_lists_books_by_fiscal_year():
    books = [{"id": "b", "fiscal_year": 2027, "edition": "proposed"}, {"id": "a", "fiscal_year": 2024,
                                                                         "edition": "adopted"}]
    assert budget_views.books_phrase(books) == "FY2024 (adopted) and FY2027 (proposed)"
    assert budget_views.books_phrase(books[:1]) == "FY2027 (proposed)"


def test_preview_over_its_cap_leaves_the_city_budget_out_with_no_dangling_link(tmp_path, monkeypatch, capsys):
    """sitegen/build.py: a preview still over its cap without transcripts and the export is built again without
    city/finance/ (city_budget=False): no page of it, and no page links to it."""
    monkeypatch.setitem(config.MAX_FILES_BY_TARGET, "preview", 10 ** 6)          # first, the build with the city
    full = build(ROOT / "data" / "facts.json", tmp_path / "a", target="preview", transcripts=False, export=False)
    assert full["city_budget"] is True
    monkeypatch.setitem(config.MAX_FILES_BY_TARGET, "preview", full["files_with_export"] - 1)
    out = tmp_path / "b"
    r = build(ROOT / "data" / "facts.json", out, target="preview", transcripts=False, export=False)
    assert r["city_budget"] is False and r["files_with_export"] <= config.max_files("preview")
    assert "building again without the city budget pages" in capsys.readouterr().err
    assert not (out / "city" / "finance").exists()
    pages = {p.relative_to(out).as_posix(): p.read_text(encoding="utf-8") for p in out.rglob("*.html")}
    assert len(pages) > 50
    assert not [k for k, v in pages.items() if re.search(r'href="[^"]*city/finance/', v)]
    assert 'data-card="finance"' not in pages["city/index.html"]           # the hub card goes with the pages
    assert "budget books have their own pages" not in pages["finance/index.html"]
