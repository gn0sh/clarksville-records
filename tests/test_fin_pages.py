"""finance-contracts F6/F7: Bids and awards index, solicitation pages, glossary and the `sol` search type, built from
the FIXTURE site/fixtures/finance.sample.json. Problem-key families: coverage-count/*, neutrality/*, provenance/*,
scan-values/*, award-source/*."""
import copy
import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, ROOT, parse
from sitegen import build as sitegen_build, config, fin_views, views
from test_site_neutrality import BANNED, skeleton

FIN = ROOT / "site" / "fixtures" / "finance.sample.json"
T = config.FIN_TEXT
C = T["contracts"]
COVERAGE = "4 of 5 solicitations have a bid tab; award letters are scans and are linked, not read."


def build_with(out, facts=None, fin=None, **kw):
    """Build the fixture site with a (possibly changed) facts and finance file; returns {rel: html}."""
    out.mkdir(parents=True, exist_ok=True)
    fp, np = FIXTURE, FIN
    if facts is not None:
        fp = out / "facts.json"
        fp.write_text(json.dumps(facts), encoding="utf-8")
    if fin is not None:
        np = out / "finance.in.json"
        np.write_text(json.dumps(fin), encoding="utf-8")
    site = out / "build" / "site"
    kw.setdefault("seats_path", FIXTURE_SEATS)
    kw.setdefault("districts_path", FIXTURE_DISTRICTS)
    sitegen_build.build(fp, site, finance_path=np, **kw)
    return {p.relative_to(site).as_posix(): p.read_text(encoding="utf-8") for p in site.rglob("*.html")}


@pytest.fixture(scope="module")
def fin():
    return json.loads(FIN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fpages(tmp_path_factory):
    return build_with(tmp_path_factory.mktemp("fin"))


def main_of(html):
    return html.split('<main id="main">', 1)[1].split("</main>", 1)[0]


def contracts_pages(pages):
    return {k: v for k, v in pages.items() if k.startswith("contracts/")}


def rows(html):
    return [n for n in parse(html).walk() if n.tag == "tr" and "data-fact-id" in n.attrs]


# ---- pages exist, nav, fixed strings (AC-F15, design 2) -------------------------------------------------------------

def test_pages_are_written_and_nav_lists_bids_and_awards_between_finance_and_capital(fpages, fin):
    assert "contracts/index.html" in fpages and "glossary.html" in fpages
    for s in fin["solicitations"]:
        assert f"contracts/{s['slug']}.html" in fpages
    nav = fpages["about.html"][fpages["about.html"].index('<nav id="site-nav"'):]
    labels = re.findall(r'<a href="[^"]*">([^<]+)', nav)
    i = labels.index("Bids and awards")
    assert labels[i - 1].startswith("Finance") and labels[i + 1].startswith("Capital projects")
    assert 'contracts/index.html" aria-current="page"' in fpages["contracts/road-salt-fixture.html"]


def test_without_finance_data_nothing_is_built_and_finance_stays_coming(pages):
    assert not any(k.startswith("contracts/") for k in pages) and "glossary.html" not in pages
    assert "Bids and awards" not in pages["about.html"]
    assert "Coming" in main_of(pages["finance.html"])


def test_coverage_sentence_is_the_one_fixed_string_on_every_contracts_page(fpages, fin):
    assert fin_views.coverage_sentence(fin["coverage"]) == COVERAGE
    for rel, html in contracts_pages(fpages).items():
        main = main_of(html)
        assert main.count(COVERAGE) == 1, rel
        # directly under the h1 block, before any table
        assert main.index(COVERAGE) < main.find("<table") or "<table" not in main, rel


def test_coverage_counts_come_from_the_file_not_from_sitegen(tmp_path, fin):
    f = copy.deepcopy(fin)
    f["coverage"]["n_bid_tab_links"], f["coverage"]["n_total"] = 32, 91
    pages = build_with(tmp_path, fin=f)
    assert "32 of 91 solicitations have a bid tab; award letters are scans and are linked, not read." in \
        pages["contracts/index.html"]


def test_notes_are_exact_strings(fpages):
    idx = main_of(fpages["contracts/index.html"])
    for k in ("a", "b", "c"):
        assert f">{T['notes'][k]}<" in idx, k
    assert T["notes"]["c_short"] in idx
    sol = main_of(fpages["contracts/riding-mowers-fixture.html"])
    assert f">{T['notes']['a']}<" in sol and f">{T['notes']['b']}<" in sol


def test_glossary_is_alphabetical_with_anchors(fpages):
    html = main_of(fpages["glossary.html"])
    terms = re.findall(r'<dt id="([a-z-]+)">([^<]+)</dt>', html)
    assert [t for _, t in terms] == sorted((t for _, t in terms), key=str.casefold)
    assert {i for i, _ in terms} >= {"bid-tab", "award-letter", "notice-of-intent", "rfp", "fund"}
    assert 'href="../glossary.html#bid-tab"' in fpages["contracts/index.html"]


# ---- neutrality (AC-F8, N1) -----------------------------------------------------------------------------------------

def test_two_solicitations_share_one_skeleton(fpages):
    assert skeleton(fpages["contracts/riding-mowers-fixture.html"]) == skeleton(fpages["contracts/road-salt-fixture.html"])


def test_bidders_keep_printed_order_whatever_the_file_order(tmp_path, fin):
    f = copy.deepcopy(fin)
    sol = next(s for s in f["solicitations"] if s["id"] == "sol-road-salt-fixture")
    sol["bid_tab"]["bidders"].reverse()
    html = build_with(tmp_path, fin=f)["contracts/road-salt-fixture.html"]
    ids = [r.attrs["data-fact-id"] for r in rows(html) if "/bidder/" in r.attrs["data-fact-id"]]
    assert ids == [f"sol-road-salt-fixture/bidder/{n}" for n in (1, 2, 3)]
    # roof repair: the lower total is printed second and stays second
    roof = main_of(build_with(tmp_path / "b", fin=fin)["contracts/roof-repair-fixture.html"])
    table = roof[roof.index('class="fin-stack sol-bidders"'):roof.index("</table>", roof.index("sol-bidders"))]
    assert table.index("Theta Roof Works") < table.index("Eta Roofing Inc.")


def test_no_sort_by_amount_or_count_in_fin_views():
    src = (ROOT / "sitegen" / "fin_views.py").read_text(encoding="utf-8")
    for m in re.finditer(r"sort\(key=([^\n]*)|sorted\([^\n]*key=([^\n]*)|reverse=True", src):
        key = m.group(1) or m.group(2) or ""
        assert not re.search(r"total|cents|amount|len\(|count|n_", key), key
    js = (ROOT / "site" / "static" / "contracts.js").read_text(encoding="utf-8")
    assert set(re.findall(r'(\w+|"new"): (?:byDate|byText)', js)) == {'"new"', "old", "title", "dept"}
    assert [s["key"] for s in C["sorts"]] == ["new", "old", "title", "dept"]


FIN_BANNED = re.compile(BANNED.pattern + r"|\b(overpaid|suspicious|top|worst|waste|cheapest|lowest|highest)\b",
                        re.IGNORECASE)


@pytest.mark.parametrize("name", ["fin_contracts_index.html.j2", "fin_solicitation.html.j2", "_fin_macros.html.j2",
                                  "_disclosure.html.j2"])
def test_fin_templates_have_no_banned_words(name):
    """design 9: the lint skips only config/finance_text.yml and the glossary."""
    raw = (ROOT / "site" / "templates" / name).read_text(encoding="utf-8")
    raw = re.sub(r"\{#.*?#\}|\{%.*?%\}", "", raw, flags=re.S)
    m = FIN_BANNED.search(raw)
    assert m is None, (name, m and m.group(0))


def test_rendered_contracts_pages_have_no_banned_words_outside_config_text(fpages):
    fixed = [T["notes"][k] for k in T["notes"]] + [g["text"] for g in T["glossary"]]
    for rel, html in contracts_pages(fpages).items():
        text = re.sub(r"<[^>]+>", " ", main_of(html))
        for s in fixed:
            text = text.replace(s, "")
        m = FIN_BANNED.search(text)
        assert m is None, (rel, m and m.group(0))


# ---- provenance (AC-F3) ---------------------------------------------------------------------------------------------

def test_every_row_has_a_source_link_and_a_fetch_date(fpages, fin):
    urls = {s["url"]: s for s in fin["sources"]}
    n = 0
    for rel, html in contracts_pages(fpages).items():
        for r in rows(html):
            n += 1
            links = [a.attrs["href"] for a in r.walk() if a.tag == "a" and a.attrs.get("target") == "_blank"]
            # a citation is a page of a PDF source, or the archive page; a bare PDF link is the document itself
            cited = [h for h in links if h.split("#")[0] in urls and
                     ("#page=" in h or urls[h.split("#")[0]]["content_type"] == "text/html")]
            assert cited, (rel, r.attrs["data-fact-id"])
            for h in cited:
                s = urls[h.split("#")[0]]
                if "#page=" in h:
                    m = re.search(r"#page=(\d+)$", h)
                    assert m and 1 <= int(m.group(1)) <= s["pages"], (rel, h)
            assert re.search(r"fetched \d{4}-\d{2}-\d{2}", r.all_text()), (rel, r.attrs["data-fact-id"])
            assert "Report an error" in r.all_text()
    assert n >= 15


def test_every_amount_on_a_page_sits_in_a_cited_row(fpages):
    for rel, html in contracts_pages(fpages).items():
        for m in re.finditer(r"\$[\d,]+\.\d\d", main_of(html)):
            row = [r for r in rows(html) if m.group(0) in r.all_text()]
            assert row and "/bidder/" in row[0].attrs["data-fact-id"], (rel, m.group(0))


def test_department_awardee_and_archive_date_lines_cite_their_page(fpages):
    html = main_of(fpages["contracts/road-salt-fixture.html"])
    assert re.search(r"Department: Example Highway <span class=\"cite\">\(<a href=\"[^\"]+tab-salt\.pdf#page=1\"[^>]*>"
                     r"bid tab p\. 1, fetched 2026-11-07", html)
    assert re.search(r"Archive date as printed: OCTOBER 14\. 2026 <span class=\"cite\">\(<a href=\"[^\"]+archive\.html\"",
                     html)
    assert re.search(r"Awardee as printed on the bid tab: Gamma Minerals LLC\. Source: "
                     r"<a href=\"[^\"]+tab-salt\.pdf#page=2\""
                     r"[^>]*>bid tab p\. 2<span[^>]*>[^<]*</span></a>, fetched 2026-11-07\.", html)


# ---- states (design 5) ----------------------------------------------------------------------------------------------

def test_scanned_award_letter_shows_words_and_no_value(fpages):
    html = fpages["contracts/riding-mowers-fixture.html"]
    row = next(r for r in rows(html) if r.attrs["data-fact-id"].endswith("doc-4c5912f33a"))
    text = row.all_text()
    assert C["scanned_row"] in text and C["scanned_detail"] in text
    assert C["no_date"] in text and "$" not in text
    assert "Scanned" in main_of(fpages["contracts/index.html"])


def test_held_total_is_not_confirmed_with_no_number(fpages):
    html = fpages["contracts/road-salt-fixture.html"]
    row = next(r for r in rows(html) if r.attrs["data-fact-id"] == "sol-road-salt-fixture/bidder/2")
    assert "Not confirmed" in row.all_text() and "Read it yourself" in row.all_text()
    assert "1O9,875" not in html and "109,875" not in html


def test_not_a_listed_bidder_and_documents_differ_states(fpages):
    salt = main_of(fpages["contracts/road-salt-fixture.html"])
    assert C["awardee_not_listed"] in salt
    roof = main_of(fpages["contracts/roof-repair-fixture.html"])
    note = roof[roof.index('class="note differ"'):]
    note = note[:note.index("</div>")]
    assert C["differ"] in note and "tab-roof.pdf" in note and "noi-roof.pdf" in note
    assert "<p>Awardee.</p>" in note  # the field names only: no explanation
    assert C["differ"] not in main_of(fpages["contracts/road-salt-fixture.html"])


def test_no_bid_tab_and_not_read_tab_show_words_and_no_amounts(fpages):
    chairs = main_of(fpages["contracts/office-chairs-fixture.html"])
    assert C["no_tab_detail"] in chairs and "$" not in chairs
    assert C["dead_link"].format(date="2026-11-07") in chairs and C["not_pdf"] in chairs and C["shared"] in chairs
    paving = main_of(fpages["contracts/paving-unit-prices-fixture.html"])
    assert C["not_read"]["layout"] in paving and "$" not in paving
    idx = parse(fpages["contracts/index.html"])
    tab_cells = {r.attrs["data-fact-id"]: [c for c in r.children if "c-tab" in c.attrs.get("class", "")][0].all_text()
                 for r in idx.walk() if r.tag == "tr" and "data-fact-id" in r.attrs}
    assert tab_cells["sol-office-chairs-fixture"] == C["no_tab"]
    assert tab_cells["sol-paving-unit-prices-fixture"] == C["has_tab"]


def test_documents_ordered_by_date_then_stage(fpages):
    html = fpages["contracts/riding-mowers-fixture.html"]
    order = [r.attrs["data-fact-id"].split("/")[1] for r in rows(html) if "/doc-" in r.attrs["data-fact-id"]]
    # the bid has a printed date; the rest have none and follow the stage order: bid tab, award letter, other
    assert order == ["doc-1ead6510fe", "doc-3b55539a53", "doc-4c5912f33a", "doc-25b726266e"]


def test_index_rows_newest_first_with_undated_last(fpages):
    ids = [r.attrs["data-fact-id"] for r in rows(fpages["contracts/index.html"])]
    assert ids == ["sol-road-salt-fixture", "sol-roof-repair-fixture", "sol-riding-mowers-fixture",
                   "sol-office-chairs-fixture", "sol-paving-unit-prices-fixture"]


def test_official_name_links_to_their_page(tmp_path, fin, facts):
    """AC-F9 / design 5: any elected official named on a page links to their vote page."""
    o = facts["officials"][0]
    f = copy.deepcopy(fin)
    sol = next(s for s in f["solicitations"] if s["id"] == "sol-riding-mowers-fixture")
    sol["bid_tab"]["bidders"][1]["name"] = o["name"]
    html = build_with(tmp_path, fin=f)["contracts/riding-mowers-fixture.html"]
    assert f'<a href="../officials/{o["id"]}.html">{o["name"]}</a>' in html


# ---- build guards (scan-values/*, award-source/*) -----------------------------------------------------------------

def test_build_refuses_a_value_from_a_scan(tmp_path, fin):
    f = copy.deepcopy(fin)
    next(s for s in f["sources"] if s["id"] == "src-a81ad7605a23")["text_layer"] = "none"
    with pytest.raises(sitegen_build.BuildError, match="scan-values"):
        build_with(tmp_path, fin=f)


def test_build_refuses_values_from_a_shared_link(tmp_path, fin):
    f = copy.deepcopy(fin)
    next(d for d in f["documents"] if d["id"] == "doc-69bd62ac22")["shared_by"] = ["sol-office-chairs-fixture"]
    with pytest.raises(sitegen_build.BuildError, match="award-source"):
        build_with(tmp_path, fin=f)


def test_build_refuses_fixture_finance_with_real_facts(tmp_path, facts):
    real = dict(copy.deepcopy(facts), fixture=False)
    with pytest.raises(sitegen_build.BuildError, match="FIXTURE finance file cannot be built with a real facts"):
        build_with(tmp_path, facts=real, seats_path=None, districts_path=None)


def test_build_refuses_a_missing_named_finance_file(tmp_path):
    with pytest.raises(sitegen_build.BuildError, match="no such finance file"):
        sitegen_build.build(FIXTURE, tmp_path / "s", finance_path=tmp_path / "nope.json",
                            seats_path=None, districts_path=None)


def test_no_inline_script_and_one_csp_on_new_pages(fpages):
    for rel in list(contracts_pages(fpages)) + ["glossary.html"]:
        html = fpages[rel]
        assert html.count("Content-Security-Policy") == 1
        for attrs in re.findall(r"<script\b([^>]*)>", html):
            assert "src=" in attrs, (rel, attrs)


# ---- F7: search type sol and the index's own filter ---------------------------------------------------------------

def _hay(r):  # static/search.js hay(), the same fields
    return " ".join([r["n"], r["t"], r.get("st") or "", r.get("z") or "", r.get("x") or ""]).lower()


def test_search_index_has_sol_records_and_a_bidder_name_finds_its_solicitation(facts, fin):
    fx = fin_views.Finance(fin, facts["officials"])
    idx = views.search_index(views.Index(facts), fx)
    sols = [r for r in idx["records"] if r["k"] == "sol"]
    assert len(sols) == len(fin["solicitations"])
    hits = [r["h"] for r in sols if all(t in _hay(r) for t in "epsilon supply".split())]
    assert hits == ["contracts/road-salt-fixture.html"]
    hits = [r["h"] for r in sols if "example parks" in _hay(r)]
    assert hits == ["contracts/riding-mowers-fixture.html"]
    js = (ROOT / "site" / "static" / "search.js").read_text(encoding="utf-8")
    assert '(r.x || "")' in re.search(r"function hay\(r\) \{[^\n]*", js).group(0)
    assert 'sol: "' in js


def test_search_page_offers_the_sol_kind_only_with_finance(fpages, pages):
    assert 'name="kind" value="sol"' in fpages["search.html"]
    assert 'name="kind" value="sol"' not in pages["search.html"]


def test_index_rows_carry_title_department_and_bidder_names_for_the_filter_box(fpages):
    r = next(r for r in rows(fpages["contracts/index.html"]) if r.attrs["data-fact-id"] == "sol-road-salt-fixture")
    for word in ("fixture road salt", "example highway", "delta salt company", "epsilon supply group", "zeta"):
        assert word in r.attrs["data-search"]


def _browser_ok():
    return bool(shutil.which("node")) and (os.path.exists("/opt/pw-browsers") or bool(shutil.which("playwright")))


BROWSER = r"""
const path = require('path');
let pw;
for (const r of ['', ...(process.env.NODE_PATH || '').split(path.delimiter).filter(Boolean)]) {
  try { pw = require(r ? path.join(r, 'playwright') : 'playwright'); break; } catch (e) { /* next */ }
}
(async () => {
  const browser = await pw.chromium.launch();
  const out = {};
  const page = await browser.newPage({ viewport: { width: 360, height: 800 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  const base = 'file://' + process.argv[2] + '/contracts/index.html';
  const visible = () => page.$$eval('#sol-table tbody tr', (rs) => rs.filter((r) => !r.hidden).map((r) => r.dataset.factId));
  await page.goto(base);
  out.all = await visible();
  out.scroll = await page.evaluate(() => document.documentElement.scrollWidth);
  await page.fill('#f-q', 'Epsilon');
  out.typed = await visible();                       // no auto-submit while typing
  await page.press('#f-q', 'Enter');
  out.q = await visible();
  out.url = page.url();
  out.count = await page.textContent('#sol-count');
  await page.selectOption('#f-docs', 'notab');
  out.none = await page.isVisible('#sol-none');
  await page.click('#f-clear');
  await page.selectOption('#f-order', 'title');
  out.title = await visible();
  await page.goto(base + '?dept=Example%20Parks');
  out.dept = await visible();
  out.errors = errors;
  await browser.close();
  console.log(JSON.stringify(out));
})();
"""


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_index_filter_in_a_browser(tmp_path):
    out = tmp_path / "site"
    sitegen_build.build(FIXTURE, out, finance_path=FIN, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS)
    script = tmp_path / "probe.js"
    script.write_text(BROWSER, encoding="utf-8")
    env = dict(os.environ)
    env.setdefault("NODE_PATH", subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip())
    res = subprocess.run(["node", str(script), str(out)], capture_output=True, text=True, timeout=120, env=env)
    assert res.returncode == 0, res.stderr
    r = json.loads(res.stdout.strip().splitlines()[-1])
    assert r["errors"] == []
    assert len(r["all"]) == 5 and r["scroll"] <= 360
    assert len(r["typed"]) == 5
    assert r["q"] == ["sol-road-salt-fixture"] and "q=Epsilon" in r["url"]
    assert r["count"] == "Showing 1 of 1 solicitation."
    assert r["none"] is True
    assert r["title"] == ["sol-office-chairs-fixture", "sol-paving-unit-prices-fixture", "sol-riding-mowers-fixture",
                          "sol-road-salt-fixture", "sol-roof-repair-fixture"]
    assert r["dept"] == ["sol-riding-mowers-fixture"]
