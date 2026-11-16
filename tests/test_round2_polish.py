"""Daylight round 2 polish (owner approved 2026-11-14; problem keys onceover/...): the checking counts as one small
sentence, the small morning-note card before launch, three radii and one card accent, one small label, ruled tables,
one crumb line, RPC rows titled by their date, search buttons that wait, the About page's jump list, plain words for
the site's own process, and the new touch targets. The sun on every page is in test_body_switch.py and
test_daylight.py.
"""
import html as html_mod
import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, ROOT
from sitegen import bodies, config, localdates
from sitegen.build import build
from test_rpc_pages import rpc_cfg  # noqa: F401  (fixture: the RPC's fixture facts)

CSS = (ROOT / "site" / "static" / "style.css").read_text(encoding="utf-8")
TEMPLATES = ROOT / "site" / "templates"
WORDS = r"(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}"


def _browser_ok():
    # the same rule as the other browser checks (test_days._browser_ok): the CI runner has node but no Playwright
    return bool(shutil.which("node")) and (os.path.exists("/opt/pw-browsers") or bool(shutil.which("playwright")))


def main_of(page: str) -> str:
    return page.split("<main", 1)[1].split("</main>")[0]


def plain(fragment: str) -> str:
    return re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def rule(selector: str) -> str:
    m = re.search(r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert m, selector
    return m.group(1)


@pytest.fixture(scope="module")
def rpc_site(tmp_path_factory, rpc_cfg):  # noqa: F811
    out = tmp_path_factory.mktemp("r2") / "build" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, rpc=rpc_cfg)
    return out


@pytest.fixture(scope="module")
def rpc_pages(rpc_site):
    return {p.relative_to(rpc_site).as_posix(): p.read_text(encoding="utf-8") for p in rpc_site.rglob("*.html")}


# ---- B onceover/stats/zero-qa-stats ---------------------------------------------------------------------------------

def test_a_meetings_checking_counts_are_one_small_sentence_the_same_for_every_meeting(pages):
    meetings = {r: main_of(p) for r, p in pages.items() if re.fullmatch(r"meetings/\d{4}-\d\d-\d\d-\w+\.html", r)}
    assert meetings
    for rel, page in meetings.items():
        stats = page.split('<ul class="stats stats-meeting">')[1].split("</ul>")[0]
        labels = re.findall(r'<span class="stat-label">([^<]*)</span>', stats)
        assert len(labels) == 3 and labels[1:] == ["motions", "roll calls confirmed"], (rel, labels)
        assert "not confirmed" not in stats and "not match" not in stats, rel            # no big figure for a check
        notes = re.findall(r'<p class="stats-note">(.*?)</p>', page)
        assert len(notes) == 1, rel
        assert re.fullmatch(r"Roll calls not confirmed\*: \d+\. Names we could not match to an official: \d+\.",
                            notes[0]), (rel, notes[0])
        assert page.index("</ul>", page.index("stats-meeting")) < page.index('<p class="stats-note">'), rel


def test_an_officials_not_confirmed_count_is_one_small_sentence_the_same_for_every_official(pages, facts):
    seen = 0
    for o in facts["officials"]:
        page = pages.get(f"officials/{o['id']}.html")
        if page is None or '<ul class="stats stats-official">' not in page:
            continue
        seen += 1
        stats = page.split('<ul class="stats stats-official">')[1].split("</ul>")[0]
        assert 'data-n="rc_voted_nc"' not in stats and "not confirmed" not in stats, o["id"]
        notes = re.findall(r'<p class="stats-note">(.*?)</p>', page)
        assert len(notes) == 1 and re.fullmatch(
            r'Votes in not confirmed\* roll calls: <span data-n="rc_voted_nc">\d+</span>\.', notes[0]), (o["id"], notes)
    assert seen > 1
    assert "font-size: var(--t-sm)" in rule(".stats-note") and "color: var(--muted)" in rule(".stats-note")


# ---- C onceover/alerts/card-before-launch ---------------------------------------------------------------------------

def test_before_launch_the_alerts_card_is_small_with_its_feeds_in_one_closed_toggle(pages):
    if "alerts.html" not in pages or 'id="note"' not in pages["alerts.html"]:
        pytest.skip("the fixture build has no morning-note card")
    page = pages["alerts.html"]
    card = page[page.index('<section class="mn-card mn-off" id="note"'):page.index("</section>", page.index('id="note"'))]
    text = config.SITE["morning_note"]["page"]
    assert card.index(text["heading"]) < card.index(text["state_off"]) < card.index("<details")
    more = card[card.index('<details class="mn-more">'):card.index("</details>")]
    assert "<details class=\"mn-more\" open" not in card                       # closed until asked for
    assert f"<summary>{text['feeds_heading']}</summary>" in more
    assert 'class="mn-picker"' in more and 'class="mn-lists"' in more          # the picker and each list's feeds
    assert 'class="mn-picker"' not in card.replace(more, "")
    assert "min-height: 44px" in rule(".mn-more > summary")
    assert "font-size: var(--t-lg)" in rule(".mn-card.mn-off h2")


# ---- 10 onceover/cards/radius-and-accent-families -------------------------------------------------------------------

def test_three_radii_and_the_cards_share_one_top_accent():
    for token, px in (("--radius", "6px"), ("--radius-lg", "12px"), ("--radius-xl", "18px")):
        assert re.search(rf"(?m)^  {token}: {px};", CSS), token
    values = set(re.findall(r"border-radius: ([^;}]+)[;}]", CSS))
    allowed = {"0", "0 !important", "1px", "3px", "4px", "50%", "999px", "var(--radius)", "var(--radius-lg)",
               "var(--radius-xl)", "var(--radius-lg) var(--radius-lg) 0 0", "0 0 var(--radius-lg) var(--radius-lg)"}
    assert values <= allowed, values - allowed                                  # no 12px, 14px or 18px written out
    xl = re.findall(r"(?m)^([^{}\n]+)\{[^}]*border-radius: var\(--radius-xl\)", CSS)
    assert sorted(s.strip() for s in xl) == [".day-card", ".mn-card"]            # the two feature cards only
    for sel in (".card", ".door", ".hub-card, .bodies-card"):                  # officials cards, doors, hub cards
        r = rule(sel)
        assert "border-top: 4px solid var(--mark)" in r and "border-radius: var(--radius-lg)" in r, sel


# ---- 11 onceover/labels/small-caps-vs-mono --------------------------------------------------------------------------

def test_one_small_label_rule_and_no_small_caps():
    assert "small-caps;" not in CSS and "font-variant-caps: all-small-caps" not in CSS
    m = re.search(r"(?m)^\.eyebrow, ([^{]+)\{([^}]*)\}", CSS)
    assert m
    sels = {s.strip() for s in ("." + "eyebrow, " + m.group(1)).replace("\n", " ").split(",")}
    assert {".eyebrow", ".label", ".stat-label", "thead th", ".filters label", ".r-kind", ".meet-col h3", ".day-dow",
            ".day-when", ".hub-kicker", ".crumb"} <= sels
    body = m.group(2)
    for decl in ("font-family: var(--font-mono)", "font-size: var(--t-eyebrow)", "text-transform: uppercase",
                 "letter-spacing: .08em"):
        assert decl in body, decl
    for sel in (".hub-kicker", ".meet-col h3", ".r-kind", ".item-num"):         # no second letterform of their own
        r = rule(sel)
        assert "font-family" not in r and "letter-spacing" not in r and "text-transform" not in r, sel


# ---- 12 onceover/tables/boxed-vs-ruled ------------------------------------------------------------------------------

def test_tables_are_ruled_not_boxed_and_the_small_ones_stack_on_a_phone():
    box = rule(".table-scroll")
    assert "border: 0; border-top: 2px solid var(--fg)" in box and "border-radius: 0" in box
    assert "background: transparent" in box
    assert "background: transparent" in rule("thead th") and "surface-2" not in rule("thead th")
    assert "nth-child(even)" not in CSS                                         # no stripes
    # one copy, in the base (the phone cards' own ".fin .fin-scroll { border: 0; }" inside its media block stays)
    assert not re.search(r"(?m)^\.fin \.fin-scroll \{", CSS) and ".fin table.fin-stack thead th {" not in CSS
    phone = CSS[CSS.index("  .table-scroll:has(table.holders), .table-scroll:has(table.aliases)"):]
    phone = phone[:phone.index("\n}\n")]
    assert "table.holders, table.aliases { min-width: 0; }" in phone
    assert "table.holders tr, table.aliases tr { display: block;" in phone
    assert "@media (min-width: 641px) { table.holders { min-width: 30rem; } }" in CSS   # no sideways scroll on a phone


# ---- 13 onceover/wayfinding/three-crumb-patterns --------------------------------------------------------------------

def crumb_of(page: str) -> list[tuple[str, str]]:
    navs = re.findall(r'<nav class="crumb" aria-label="You are in">(.*?)</nav>', page, re.S)
    assert len(navs) <= 1
    return re.findall(r'<a href="([^"]+)">([^<]+)</a>', navs[0]) if navs else []


def test_every_page_but_the_home_page_and_a_bodys_landing_page_has_one_crumb_above_its_h1(rpc_pages):
    hubs = {"index.html"}
    for rel, page in rpc_pages.items():
        here = re.search(r'<nav class="body-switch"[^>]*data-here="([^"]*)"', page)
        if here and here.group(1):
            hubs.add(rel)
    assert len(hubs) >= 3 and "rpc/index.html" in hubs
    for rel, page in rpc_pages.items():
        crumbs = crumb_of(page)
        if rel in hubs:
            assert crumbs == [], rel
            continue
        assert 1 <= len(crumbs) <= 2, (rel, crumbs)
        main = main_of(page)
        assert main.index('<nav class="crumb"') < main.index("<h1"), rel
        depth = "../" * rel.count("/")
        for href, label in crumbs:                                          # each part leads to a page that exists
            assert href.startswith(depth) and href[len(depth):] in rpc_pages, (rel, href)
            assert label.strip()
        assert crumbs[0][0][len(depth):] in hubs, (rel, crumbs)             # the first part is home or a body's page
    for old in ("kicker-line", '<p class="crumb">'):
        assert not any(old in p for p in rpc_pages.values()), old
        assert not any(old in t.read_text(encoding="utf-8") for t in TEMPLATES.glob("*.j2")), old
    assert ".kicker-line" not in CSS


def test_a_crumb_leads_to_the_bodys_page_then_the_sections_list(rpc_pages):
    meeting = next(r for r in sorted(rpc_pages) if re.fullmatch(r"meetings/\d{4}-\d\d-\d\d-\w+\.html", r))
    assert crumb_of(rpc_pages[meeting]) == [("../montgomery-county.html", "Montgomery County"),
                                            ("../meetings.html", "Meetings")]
    assert crumb_of(rpc_pages["meetings.html"]) == [("montgomery-county.html", "Montgomery County")]
    assert crumb_of(rpc_pages["search.html"]) == [("index.html", "Home")]
    year = next(r for r in sorted(rpc_pages) if r.startswith("rpc/meetings/"))
    (href, label), = crumb_of(rpc_pages[year])
    assert href == "../../rpc/index.html" and label == config.SITE["switch"]["bodies"]["rpc"]["label"]


def test_crumbs_without_a_switch_lead_home():
    site = {"switch": None, "nav": [{"href": "index.html", "label": "Home"}, {"href": "meetings.html", "label": "Meetings"}]}
    assert bodies.crumbs(site, "index.html") == []
    assert bodies.crumbs(site, "about.html") == [{"label": "Home", "href": "index.html"}]
    assert bodies.crumbs(site, "meetings/2026-05-11-formal.html") == [
        {"label": "Home", "href": "index.html"}, {"label": "Meetings", "href": "meetings.html"}]


# ---- 15 onceover/rpc/rows-same-title --------------------------------------------------------------------------------

def test_an_rpc_row_is_titled_by_its_date_with_the_kind_under_it(rpc_pages):
    home = main_of(rpc_pages["rpc/index.html"])
    rows = re.findall(r'<div class="item meet-item" id="([^"]+)">(.*?)</ul>\s*</div>\s*</div>', home, re.S)
    assert rows
    titles = []
    for mid, row in rows:
        h3 = re.search(r'<h3 class="item-h"><a href="[^"]+"><span class="nowrap">([^<]+)</span></a>', row)
        assert h3 and re.fullmatch(WORDS, h3.group(1)), mid
        titles.append(h3.group(1))
        kind = re.search(r'<p class="meet-kind">([^<]+)</p>', row)
        assert kind and kind.group(1).strip(), mid                             # the kind of meeting, once, under it
        block = re.search(r'<span class="meet-date" aria-hidden="true"><span class="dow">(\w{3})</span><b>(\d+)</b>'
                          r'<span class="mon">(\w{3})</span></span>', row)
        assert block, mid
        assert f"{block.group(3)}" == h3.group(1)[:3] and f" {block.group(2)}," in h3.group(1), mid
    assert not re.search(r'<h3 class="item-h"><a href="[^"]+">Regional Planning Commission</a>', home)


@pytest.mark.parametrize("given, parts", [
    ("2026-10-27", {"dow": "Tue", "n": 27, "month": "Oct"}),
    ("2026-05-01", {"dow": "Fri", "n": 1, "month": "May"}),
    ("2026-13-40", None), ("October 27, 2026", None), ("2026-10-27-formal", None), (None, None), ("", None),
])
def test_day_parts(given, parts):
    assert localdates.parts(given) == parts


# ---- 17 onceover/search/controls-before-results ---------------------------------------------------------------------

def test_search_clear_and_copy_wait_for_something_to_clear_or_copy(pages):
    page = pages["search.html"]
    assert '<button type="button" id="clear" hidden>Clear all filters</button>' in page
    assert '<button type="button" id="copy" hidden>Copy link to this search</button>' in page
    js = (ROOT / "site" / "static" / "search.js").read_text(encoding="utf-8")
    assert 'document.getElementById("clear").hidden = !filtered;' in js and "copyBtn.hidden = idle;" in js
    assert "display" not in rule(".results-bar button")          # nothing overrides [hidden] on the two buttons


SEARCH_JS = r"""
const path = require('path');
let pw; for (const r of [process.env.NODE_PATH, '/opt/node22/lib/node_modules'].filter(Boolean)) { try { pw = require(path.join(r, 'playwright')); break; } catch (e) {} }
const { pathToFileURL } = require('url');
(async () => {
  const b = await pw.chromium.launch(); const p = await b.newPage();
  const shown = () => p.evaluate(() => ['clear', 'copy'].map((id) => document.getElementById(id).getClientRects().length > 0));
  const out = {};
  await p.goto(pathToFileURL(process.argv[1]).href); await p.waitForFunction(() => document.getElementById('results').getAttribute('aria-busy') !== 'true');
  out.start = await shown();
  await p.fill('#q', 'resolution'); out.query = await shown();
  await p.evaluate(() => { document.querySelector('.filter-panel').open = true; });
  await p.check('input[name="kind"]'); out.filter = await shown();
  await p.click('#clear'); out.cleared = await shown();
  out.clearFocus = await p.evaluate(() => document.activeElement !== document.body);
  await p.fill('#q', ''); out.empty = await shown();
  console.log(JSON.stringify(out)); await b.close();
})();
"""


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_search_buttons_in_a_browser(built):
    env = dict(os.environ)
    if "NODE_PATH" not in env:
        env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    r = subprocess.run(["node", "-e", SEARCH_JS, str(built / "search.html")], capture_output=True, text=True,
                       timeout=300, env=env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out == {"start": [False, False], "query": [False, True], "filter": [True, True],
                   "cleared": [False, True], "clearFocus": True, "empty": [False, False]}


# ---- 18 onceover/about/no-contents ----------------------------------------------------------------------------------

def test_the_about_page_lists_its_own_sections_in_order(pages):
    main = main_of(pages["about.html"])
    h2s = [(i, plain(t)) for i, t in re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', main, re.S)]
    assert len(h2s) >= 12
    wide = re.search(r'<nav class="fin-toc page-toc toc-wide" aria-label="On this page">(.*?)</nav>', main, re.S)
    phone = re.search(r'<details class="fin-jump page-toc toc-phone"><summary>On this page \((\d+)\)</summary>'
                      r'<nav aria-label="On this page">(.*?)</nav></details>', main, re.S)
    assert wide and phone and int(phone.group(1)) == len(h2s)
    for block in (wide.group(1), phone.group(2)):
        links = [(h[1:], plain(t)) for h, t in re.findall(r'<a href="(#[^"]+)">(.*?)</a>', block, re.S)]
        assert links == h2s                                                     # every section, its own words, in order
    assert main.index("</h1>") < main.index("toc-wide") < main.index("<h2")
    assert ".page-toc.toc-phone { display: none; }" in CSS
    assert "@media (max-width: 640px) { .page-toc.toc-wide { display: none; } .page-toc.toc-phone { display: block; } }" in CSS


# ---- 20 onceover/copy/system-words ----------------------------------------------------------------------------------

SYSTEM_WORDS = ("minutes reader", "fresh check", "extracted attendance", "not extracted", "each extracted",
                "Each extracted", "no text layer", "feed reader app", "names not matched to an official")


def test_the_sites_own_process_is_in_plain_words(rpc_pages):
    for rel, page in rpc_pages.items():
        text = plain(main_of(page))
        for w in SYSTEM_WORDS:
            assert w not in text, (rel, w)
    for src in (*TEMPLATES.glob("*.j2"), ROOT / "config" / "site.yml"):
        raw = src.read_text(encoding="utf-8")
        for w in SYSTEM_WORDS:
            assert w not in re.sub(r"\{#.*?#\}", "", raw, flags=re.S), (src.name, w)


def test_the_reworded_sentences_are_fixed_and_the_same_for_everyone(pages, facts):
    """The totals sentences keep one form for every official: only the numbers differ (no name, no judgement)."""
    forms = set()
    for o in facts["officials"]:
        page = pages.get(f"officials/{o['id']}.html")
        if page is None or '<ul class="totals">' not in page:
            continue
        lis = re.findall(r"<li>(.*?)</li>", page.split('<ul class="totals">')[1].split("</ul>")[0], re.S)
        forms.add(tuple(re.sub(r"\d+", "N", plain(x)) for x in (lis[0], lis[3], lis[4])))
        assert o["name"] not in " ".join(plain(x) for x in lis), o["id"]
    assert len(forms) >= 1
    for f in forms:
        assert f[0].startswith("Recorded absent at N of N meetings whose attendance list was read, ")
        assert re.fullmatch(r"N meetings? in this period (has|have) an attendance list that could not be read and "
                            r"(is|are) not counted\.", f[1]), f[1]
        assert re.fullmatch(r"N meetings? in this period (has|have) an attendance list that is under review and "
                            r"(is|are) not counted\.", f[2]), f[2]


# ---- touch targets of what this round added ---------------------------------------------------------------------------

TOUCH_JS = r"""
const path = require('path');
let pw; for (const r of [process.env.NODE_PATH, '/opt/node22/lib/node_modules'].filter(Boolean)) { try { pw = require(path.join(r, 'playwright')); break; } catch (e) {} }
const { pathToFileURL } = require('url');
(async () => {
  const b = await pw.chromium.launch(); const out = [];
  const specs = JSON.parse(process.argv[1]);
  for (const w of [375, 1280]) {
    const ctx = await b.newContext({ viewport: { width: w, height: 800 }, hasTouch: true, isMobile: true });
    for (const s of specs) {
      const p = await ctx.newPage(); await p.goto(pathToFileURL(s.path).href); await p.waitForTimeout(100);
      const r = await p.evaluate((sels) => {
        document.querySelectorAll('details.page-toc, details.mn-more').forEach((d) => { d.open = true; });
        const res = { coarse: matchMedia('(pointer: coarse)').matches, n: 0, small: [], sw: document.documentElement.scrollWidth, iw: innerWidth };
        for (const sel of sels) for (const el of document.querySelectorAll(sel)) {
          const box = el.getBoundingClientRect();
          if (!el.getClientRects().length) { continue; }
          res.n += 1;
          if (box.height < 44) { res.small.push(sel + ' ' + Math.round(box.width) + 'x' + Math.round(box.height)); }
        }
        return res;
      }, s.sels);
      out.push(Object.assign({ name: s.name, width: w }, r)); await p.close();
    }
    await ctx.close();
  }
  console.log(JSON.stringify(out)); await b.close();
})();
"""


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_the_new_links_and_toggles_are_44px_on_a_touch_screen_and_nothing_scrolls_sideways(rpc_site):
    meeting = next(p for p in sorted((rpc_site / "meetings").glob("*.html")) if re.match(r"\d{4}-", p.name))
    specs = [{"name": "about", "path": str(rpc_site / "about.html"),
              "sels": [".crumb a", ".page-toc.toc-wide a", ".page-toc.toc-phone > summary", ".page-toc.toc-phone a"]},
             {"name": "meeting", "path": str(meeting), "sels": [".crumb a"]},
             {"name": "search", "path": str(rpc_site / "search.html"), "sels": [".crumb a"]}]
    if (rpc_site / "alerts.html").exists() and "mn-more" in (rpc_site / "alerts.html").read_text(encoding="utf-8"):
        specs.append({"name": "alerts", "path": str(rpc_site / "alerts.html"), "sels": [".crumb a", ".mn-more > summary"]})
    env = dict(os.environ)
    if "NODE_PATH" not in env:
        env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    r = subprocess.run(["node", "-e", TOUCH_JS, json.dumps(specs)], capture_output=True, text=True, timeout=300, env=env)
    assert r.returncode == 0, r.stderr
    runs = json.loads(r.stdout)
    assert len(runs) == 2 * len(specs)
    for x in runs:
        where = (x["name"], x["width"])
        assert x["coarse"] and x["n"] > 0, (where, x)
        assert x["small"] == [], (where, x["small"])
        assert x["sw"] <= x["iw"], (where, x["sw"], x["iw"])              # no sideways scroll


def test_corrections_table_cells_are_labelled_when_stacked(tmp_path):
    t = (ROOT / "site" / "templates" / "corrections.html.j2").read_text(encoding="utf-8")
    assert 'class="aliases corrections"' in t
    for lab in ("Date", "Page", "Was", "Now"):
        assert f'data-label="{lab}"' in t
    assert "table.corrections td[data-label]::before { content: attr(data-label);" in CSS
