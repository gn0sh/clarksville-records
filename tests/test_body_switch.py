"""The "Show records from" switch (owner's mock, 2026-11-12; sitegen/bodies.py, static/switch.js): on every page under
the header, All plus one plain link per body to its hub page; hub cards, the coming ones dashed with a Coming tag and
an official link from the config; the home page's overview; data-body on the rows the script filters; the Finance
page's "County budget only so far" line; and the script's storage rules.

Builds the county fixture beside the city fixture subset (tests/test_council_pages.py) and the RPC fixture
(tests/test_rpc_pages.py), so all four bodies have a hub."""
import json
import os
from datetime import date
import re
import shutil
import subprocess
from html import unescape

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, ROOT
from qa import site_checks as SC
from sitegen import bodies, config
from sitegen.build import build
from test_council_pages import cfg, city_facts, city_wards  # noqa: F401  (module fixtures)
from test_rpc_pages import rpc_cfg  # noqa: F401  (module fixture)

SW = config.SITE["switch"]
LABELS = ["All", "Montgomery County", "Clarksville", "School board", "Planning (RPC)"]
TODAY = date(2024, 12, 1)     # the day page's window then holds two county fixture meetings (tests/test_days.py)
SWITCH_JS = ROOT / "site" / "static" / "switch.js"
CSS = (ROOT / "site" / "static" / "style.css").read_text(encoding="utf-8")


def plain(fragment: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


@pytest.fixture(scope="module")
def site(tmp_path_factory, cfg, rpc_cfg):  # noqa: F811
    out = tmp_path_factory.mktemp("switch") / "build" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, councils=[cfg], rpc=rpc_cfg,
          today=TODAY)
    return out


@pytest.fixture(scope="module")
def html(site):
    return {p.relative_to(site).as_posix(): p.read_text(encoding="utf-8") for p in site.rglob("*.html")}


def switch_of(page: str) -> tuple[str, list[tuple[str, str, str, str]]]:
    m = SC.SWITCH_NAV.search(page)
    assert m, "no body switch"
    return m.group(1), SC.SWITCH_LINK.findall(m.group(2))


def hub_cards(page: str) -> dict[str, str]:
    hub = re.search(r'<section class="hub".*?</section>', page, re.S).group(0)
    return dict(re.findall(r'<li class="hub-card[^"]*" data-card="([^"]+)">(.*?)</li>', hub, re.S))


def test_the_owners_labels_in_order():
    assert [SW["all"]["label"]] + [SW["bodies"][k]["label"] for k in bodies.ORDER] == LABELS
    assert SW["label"] == "Show records from"


def test_switch_is_on_every_page_under_the_header_with_plain_links(site, html):
    assert len(html) > 40
    for rel, page in html.items():
        assert page.count('id="body-switch"') == 1, rel
        here, opts = switch_of(page)
        assert [unescape(label) for _, _, label, _ in opts] == LABELS, rel
        assert [k for _, k, _, _ in opts] == ["all", "county", "city", "school", "rpc"], rel
        nav = SC.SWITCH_NAV.search(page)
        assert page.index("</header>") < nav.start() < page.index('<main id="main">'), rel
        assert ">Show records from</p>" in nav.group(2), rel
        assert "<button" not in nav.group(2) and "<form" not in nav.group(2), rel   # links only: works without script
        # every option resolves to the same built page from anywhere
        targets = [SC.resolve(rel, href) for href, _, _, _ in opts]
        assert targets == ["index.html", "montgomery-county.html", f"{cfg_slug(site)}/index.html",
                           "school-board.html", "rpc/index.html"], rel
    pages = {rel: SC.parse(site / rel) for rel in html}
    problems, note = SC.check_switch(site, pages)
    assert problems == [], problems[:5]
    assert f"the switch on {len(html)} pages" in note


def cfg_slug(site) -> str:
    return next(p.name for p in site.iterdir() if p.is_dir() and (p / "members").is_dir())


def test_only_an_options_own_page_marks_it_current(site, html):
    city = f"{cfg_slug(site)}/index.html"
    own = {"index.html": "all", "montgomery-county.html": "county", city: "city", "school-board.html": "school",
           "rpc/index.html": "rpc"}
    for rel, page in html.items():
        here, opts = switch_of(page)
        assert here == own.get(rel, ""), rel
        assert [k for _, k, _, cur in opts if cur] == ([own[rel]] if rel in own else []), rel


def test_school_board_option_carries_the_coming_tag_and_rpc_a_short_phone_label(html):
    nav = SC.SWITCH_NAV.search(html["about.html"]).group(2)
    assert re.search(r'data-switch="school"[^>]*>School board <span class="chip chip-coming">Coming</span></a>', nav)
    assert nav.count("chip-coming") == 1
    assert '<span class="bs-long">Planning (RPC)</span><span class="bs-short" aria-hidden="true">RPC</span>' in nav


def test_footer_page_list_lists_every_hub(site, html):
    """The footer's "All pages" list (the drawer's single source) has the county hub beside the other bodies' hubs,
    and marks it current on its own page."""
    def nav_hrefs(page):
        nav = re.search(r'<nav id="site-nav".*?</nav>', page, re.S).group(0)
        return re.findall(r'<li><a href="([^"]+)"', nav)
    hrefs = nav_hrefs(html["about.html"])
    hubs = ["montgomery-county.html", f"{cfg_slug(site)}/index.html", "rpc/index.html", "school-board.html"]
    assert all(h in hrefs for h in hubs), hrefs
    assert hrefs.index("officials.html") + 1 == hrefs.index("montgomery-county.html")
    assert hrefs.index("montgomery-county.html") < hrefs.index(f"{cfg_slug(site)}/index.html")
    nav = re.search(r'<nav id="site-nav".*?</nav>', html["montgomery-county.html"], re.S).group(0)
    assert '<a href="montgomery-county.html" aria-current="page">Montgomery County</a>' in nav


def test_county_hub_page(html):
    page = html["montgomery-county.html"]
    assert '<p class="hub-kicker">County government</p>' in page
    assert "<h1>Montgomery County</h1>" in page
    assert '<p class="lede">Records of the Montgomery County Commission' in page
    cards = hub_cards(page)
    assert list(cards)[:2] == ["meetings", "votes"] and list(cards)[-1] == "budget-committee"
    assert 'href="meetings.html"' in cards["meetings"] and re.search(r'href="votes/\d{4}\.html"', cards["votes"])
    bc = cards["budget-committee"]
    assert '<span class="chip chip-coming">Coming</span>' in bc
    link = config.SITE["committees"]["links"][1]
    assert f'<a data-ext="committee" href="{link["url"]}" target="_blank" rel="noopener noreferrer">{link["label"]}' in bc


def test_a_present_card_is_shown_only_when_its_page_is_built(site, html):
    """The fixture has no budget lines, so Finance and Capital projects are "coming" pages in this build: the county
    hub does not link them as if they were collected."""
    cards = hub_cards(html["montgomery-county.html"])
    for key, rel in (("finance", "finance/index.html"), ("capital", "capital/index.html")):
        assert (key in cards) == (site / rel).is_file()
    for key, card in cards.items():
        for href in re.findall(r'<a href="([^"#]+)', card):
            assert (site / href).is_file(), (key, href)


def test_city_and_rpc_homes_are_their_hubs(site, html):
    city = hub_cards(html[f"{cfg_slug(site)}/index.html"])
    assert {"meetings", "votes", "finance", "committees"} <= set(city)
    assert "is-coming" not in city["meetings"] and "#meetings-h" in city["meetings"]
    for key in ("finance", "committees"):
        assert '<span class="chip chip-coming">Coming</span>' in city[key]
    assert f'href="{config.SITE["unofficial"]["bodies"][0]["url"]}"' in city["finance"]
    assert f'href="{config.SITE["committees"]["links"][0]["url"]}"' in city["committees"]
    assert '<p class="hub-kicker">City government</p>' in html[f"{cfg_slug(site)}/index.html"]
    rpc_page = html["rpc/index.html"]
    rpc = hub_cards(rpc_page)
    assert list(rpc)[:2] == ["meetings", "cases"]
    assert "No budget of the Regional Planning Commission is collected, so none is shown." in plain(rpc_page)
    assert '<p class="hub-kicker">Regional Planning Commission</p>' in rpc_page


def test_rpc_votes_card_is_coming_only_while_no_vote_is_shown(html, tmp_path, rpc_cfg, monkeypatch):  # noqa: F811
    votes = hub_cards(html["rpc/index.html"])["votes"]          # this build shows no RPC vote
    assert '<span class="chip chip-coming">Coming</span>' in votes
    assert "Votes return after the minutes reader passes a fresh check." in plain(votes)
    assert f'<a data-ext="record" href="{rpc_cfg["record_url"]}"' in votes
    from sitegen import rpc as rpc_mod
    monkeypatch.setattr(rpc_mod.Rpc, "votes_shown", property(lambda self: True))
    out = tmp_path / "shown" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, rpc=rpc_cfg)
    assert "votes" not in hub_cards((out / "rpc" / "index.html").read_text(encoding="utf-8"))


def test_school_board_hub_is_all_coming_with_the_configured_link(html):
    page = html["school-board.html"]
    cards = hub_cards(page)
    assert list(cards) == ["meetings", "votes", "budget"]
    sb = config.SITE["school_board"]
    for card in cards.values():
        assert '<span class="chip chip-coming">Coming</span>' in card
        assert f'<a data-ext="school" href="{sb["url"]}" target="_blank" rel="noopener noreferrer">{sb["link_label"]}' in card
        assert '<a href="' not in card
    assert "cmcss.net" in sb["url"]


def test_every_coming_link_is_a_url_already_in_the_config(site, html):
    allowed = SC.allowed_external(config.SITE, FIXTURE_SEATS, FIXTURE_DISTRICTS) | {
        bodies.official_link({"from": "rpc", "kind": "record"}, type("R", (), {"cfg": dict(
            record_url="https://www.cmcrpc.com/documents/agenda-minutes/", record_label="x")})())["url"]}
    n = 0
    for rel in ("montgomery-county.html", f"{cfg_slug(site)}/index.html", "school-board.html", "rpc/index.html"):
        for card in hub_cards(html[rel]).values():
            for url in re.findall(r'href="(https://[^"]+)"', card):
                n += 1
                assert url in allowed, (rel, url)
    assert n >= 6


def test_official_link_never_guesses(monkeypatch):
    assert bodies.official_link({"from": "no.such.path", "kind": "body"}) is None
    assert bodies.official_link({"from": "rpc", "kind": "record"}, None) is None
    monkeypatch.setattr(config, "SITE", {**config.SITE, "school_board": {"url": "http://example.org/", "link_label": "x"}})
    assert bodies.official_link({"from": "school_board", "kind": "school"}) is None


def test_home_overview_lists_each_body_with_the_same_coming_items(site, html):
    home = html["index.html"]
    sec = re.search(r'<section class="bodies".*?</section>', home, re.S).group(0)
    assert re.findall(r'<li class="bodies-card" data-hub="([a-z]+)">', sec) == ["county", "city", "school", "rpc"]
    for key, rel in (("county", "montgomery-county.html"), ("city", f"{cfg_slug(site)}/index.html"),
                     ("school", "school-board.html")):
        card = re.search(rf'<li class="bodies-card" data-hub="{key}">(.*?)</li>', sec, re.S).group(1)
        assert f'<a href="{rel}">' in card
        coming = [plain(re.search(r"<h\d>(.*?)<span", c, re.S).group(1)) for c in hub_cards(html[rel]).values()
                  if "chip-coming" in c]
        assert coming and f"Coming: {', '.join(coming)}." in plain(card)


def test_rows_carry_their_body_for_the_filter(site, html):
    county = config.SITE["county_key"]
    today = html["today.html"]
    cards = re.findall(r'<article class="day-card day-card-([a-z]+)" id="[^"]+" data-body="([a-z]+)"', today)
    assert cards and len(cards) == today.count('<article class="day-card')
    want = {"county": county, "bids": county, "council": "city", "rpc": "rpc"}
    assert all(want[kind] == body for kind, body in cards)
    dots = re.findall(r'<i class="dot dot-[a-z]+" data-body="([a-z]+)"></i>', today)
    assert sorted(dots) == sorted(body for _, body in cards)             # the week strip's dots follow the filter
    assert today.count("<div data-body-line></div>") == 1
    home = html["index.html"]
    rows = re.findall(r'<li data-iso="[^"]+" data-body="([a-z]+)"', home)
    assert len(rows) == home.count("<li data-iso=") and set(rows) <= {county, "city", "rpc"}
    assert f'<div data-body="{county}">' in html["meetings.html"]
    votes = [rel for rel in html if rel.startswith("votes/")]
    assert votes and all(f'<ol class="vote-list" data-body="{county}">' in html[rel] for rel in votes)
    assert 'data-body-live="county city rpc"' in html["search.html"]
    # the switch's own links are never rows
    assert "data-body=" not in SC.SWITCH_NAV.search(home).group(2)


def test_finance_note_text_and_links():
    note = bodies.finance_note()
    assert note["text"] == "County budget only so far. City and school board budgets are coming."
    assert [x["url"] for x in note["links"]] == [config.SITE["unofficial"]["bodies"][0]["url"],
                                                  config.SITE["school_board"]["url"]]
    assert note["links"][0]["url"] == "https://www.clarksvilletn.gov/" and "cmcss.net" in note["links"][1]["url"]
    tpl = (ROOT / "site" / "templates" / "fin_index.html.j2").read_text(encoding="utf-8")
    assert tpl.index("body_note.text") < tpl.index("coverage_sentence")     # the first line under the h1


def test_finance_page_shows_the_note_first_and_the_county_hub_links_finance(tmp_path):
    """With the finance fixture the Finance page is built: the note is the first paragraph under the h1, with both
    official links, the books and funds are tagged the county's, and the county hub links Finance as present."""
    from test_fin_pages import build_with, main_of
    pages = build_with(tmp_path)
    main = main_of(pages["finance/index.html"])
    first = re.search(r"</h1>\s*<p[^>]*>(.*?)</p>", main, re.S)
    assert 'class="note body-note"' in first.group(0)
    assert plain(first.group(1)).startswith("County budget only so far. City and school board budgets are coming. ")
    assert f'<a data-ext="body" href="{config.SITE["unofficial"]["bodies"][0]["url"]}"' in first.group(1)
    assert f'<a data-ext="school" href="{config.SITE["school_board"]["url"]}"' in first.group(1)
    assert main.count(f'<div data-body="{config.SITE["county_key"]}">') == 1
    assert main.index("body-note") < main.index("data-body=")           # the note itself is never hidden
    cards = hub_cards(pages["montgomery-county.html"])
    assert 'href="finance/index.html"' in cards["finance"] and "is-coming" not in cards["finance"]
    assert "bids" in cards


def test_switch_script_storage_rules():
    js = SWITCH_JS.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", js, flags=re.S)
    assert code.count("localStorage") == 1 and "try { return window.localStorage" in code   # only through store()
    assert code.count('"cr-body"') == 1
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "document.cookie",
                   "sessionStorage", "fetch(", "XMLHttpRequest", ".remove()", "removeChild(items", ".hidden = "):
        assert banned not in code, banned
    assert "classList.toggle(\"bs-off\"" in code
    assert re.search(r"\.bs-off \{ display: none !important; \}", CSS)


def test_method_page_lists_both_storage_keys(html):
    """Security L1: the Method page names every localStorage key the scripts use, and says cr-body is never sent."""
    method = plain(html["method.html"])
    assert "cr-your-seats" in method and "cr-body" in method
    assert "key cr-body ) so other pages show the same body. It is never sent anywhere. Choosing All removes it." in method
    keys = set()
    for js in (ROOT / "site" / "static").glob("*.js"):
        keys |= set(re.findall(r'"(cr-[a-z-]+)"', js.read_text(encoding="utf-8")))
    assert keys == {"cr-your-seats", "cr-body"}


def test_switch_css_targets_and_no_old_colors():
    block = CSS[CSS.index('==== "Show records from"'):]
    assert "min-height: 44px" in block and "overflow-x: auto" in block
    assert "var(--blue)" in block and "var(--sun)" in block
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", block)          # tokens only: both themes follow
    assert ".hub-card.is-coming { border: 2px dashed" in block


PROBE = r"""
const path = require('path');
let pw;
for (const r of ['', ...(process.env.NODE_PATH || '').split(path.delimiter).filter(Boolean)]) {
  try { pw = require(r ? path.join(r, 'playwright') : 'playwright'); break; } catch (e) { /* next */ }
}
(async () => {
  const site = 'file://' + process.argv[2] + '/';
  const browser = await pw.chromium.launch();
  const out = {};
  const state = (p) => p.evaluate(() => ({
    sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,
    cur: [...document.querySelectorAll('#body-switch a[aria-current]')].map((a) => a.dataset.switch),
    line: (document.getElementById('bs-line') || {textContent: ''}).textContent.replace(/\s+/g, ' ').trim(),
    off: document.querySelectorAll('.bs-off').length, tagged: document.querySelectorAll('[data-body]').length,
    visible: [...document.querySelectorAll('#main [data-body]')].filter((e) => !e.classList.contains('bs-off')).map((e) => e.dataset.body),
    minH: Math.min(...[...document.querySelectorAll('#body-switch a')].map((a) => a.getBoundingClientRect().height)),
    stored: (() => { try { return localStorage.getItem('cr-body'); } catch (e) { return 'blocked'; } })(),
    url: location.pathname.split('/').slice(-2).join('/'),
  }));
  // 1. desktop: a saved choice filters the day page; Show all restores every row
  let ctx = await browser.newContext({viewport: {width: 1280, height: 800}, deviceScaleFactor: 1});
  let p = await ctx.newPage();
  await p.goto(site + 'today.html');
  out.fresh = await state(p);
  await p.click('#body-switch a[data-switch="county"]');
  out.picked = await state(p);
  await p.goto(site + 'meetings.html');
  out.carried = await state(p);
  await p.goto(site + 'today.html');
  await p.click('#bs-line button');
  out.all = await state(p);
  // 2. a choice with no rows on this page goes to that body's hub, and the hub is then the choice
  await p.goto(site + 'meetings.html');
  await p.click('#body-switch a[data-switch="school"]');
  await p.waitForLoadState();
  out.hub = await state(p);
  await p.goto(site + 'meetings.html');
  out.other = await state(p);
  await ctx.close();
  // 3. phones: no sideways scroll, 44px chips
  for (const w of [320, 390]) {
    ctx = await browser.newContext({viewport: {width: w, height: 700}, deviceScaleFactor: 1, hasTouch: true, isMobile: true});
    p = await ctx.newPage();
    await p.goto(site + 'index.html');
    out['phone' + w] = await state(p);
    await ctx.close();
  }
  // 4. storage blocked: the page still filters, nothing throws
  ctx = await browser.newContext({viewport: {width: 1280, height: 800}});
  await ctx.addInitScript(() => { Object.defineProperty(window, 'localStorage', {get() { throw new Error('SecurityError'); }}); });
  p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', (e) => errors.push(String(e)));
  await p.goto(site + 'today.html');
  await p.click('#body-switch a[data-switch="county"]');
  out.blocked = await state(p);
  out.errors = errors;
  await ctx.close();
  // 5. no script: plain links
  ctx = await browser.newContext({viewport: {width: 1280, height: 800}, javaScriptEnabled: false});
  p = await ctx.newPage();
  await p.goto(site + 'today.html');
  await p.click('#body-switch a[data-switch="county"]');
  await p.waitForLoadState();
  out.nojs = p.url().split('/').pop();
  await ctx.close();
  await browser.close();
  console.log(JSON.stringify(out));
})();
"""


def _browser_ok():
    return bool(shutil.which("node")) and (os.path.exists("/opt/pw-browsers") or bool(shutil.which("playwright")))


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_switch_in_a_browser(site, tmp_path):
    # The fixtures' dates do not overlap, so the day page here holds county cards only. In a copy of the site, one
    # card stands in for another body's (its tag only), so the script has rows to hide and rows to keep.
    copy = tmp_path / "site"
    shutil.copytree(site, copy)
    page = (copy / "today.html").read_text(encoding="utf-8")
    county_tag = f'data-body="{config.SITE["county_key"]}" aria-labelledby'
    assert page.count(county_tag) >= 2
    (copy / "today.html").write_text(page.replace(county_tag, 'data-body="rpc" aria-labelledby', 1), encoding="utf-8")
    site = copy
    script = tmp_path / "switch.js"
    script.write_text(PROBE, encoding="utf-8")
    env = dict(os.environ)
    env.setdefault("NODE_PATH", subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip())
    res = subprocess.run(["node", str(script), str(site.resolve())], capture_output=True, text=True, timeout=240, env=env)
    assert res.returncode == 0, res.stderr
    r = json.loads(res.stdout.strip().splitlines()[-1])
    county = config.SITE["county_key"]
    assert r["fresh"]["cur"] == ["all"] and r["fresh"]["off"] == 0 and r["fresh"]["line"] == "", r["fresh"]
    pk = r["picked"]
    assert pk["url"].endswith("today.html") and pk["cur"] == ["county"] and pk["stored"] == "county", pk
    assert pk["line"] == "Showing Montgomery County only Show all", pk
    assert pk["off"] > 0 and set(pk["visible"]) == {county}, pk
    assert pk["tagged"] == r["fresh"]["tagged"]                       # hidden, never removed
    ca = r["carried"]
    assert ca["cur"] == ["county"] and ca["off"] == 0 and ca["line"].startswith("Showing Montgomery County only"), ca
    al = r["all"]
    assert al["off"] == 0 and al["line"] == "" and al["cur"] == ["all"] and al["stored"] is None, al
    assert r["hub"]["url"].endswith("school-board.html") and r["hub"]["cur"] == ["school"], r["hub"]
    ot = r["other"]
    assert ot["cur"] == ["school"] and ot["visible"] == [], ot
    assert ot["line"] == "Showing School board only Nothing on this page is from School board. School board page Show all", ot
    for w in ("phone320", "phone390"):
        assert r[w]["sw"] <= r[w]["cw"], (w, r[w])
        assert r[w]["minH"] >= 44, (w, r[w])
    assert r["errors"] == [], r["errors"]
    bl = r["blocked"]
    assert bl["cur"] == ["county"] and set(bl["visible"]) == {county} and bl["stored"] == "blocked", bl
    assert r["nojs"] == "montgomery-county.html"
