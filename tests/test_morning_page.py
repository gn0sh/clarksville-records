"""Morning note, the visitor's side (Daylight M3 T3, docs/tasks/morning-note.md): the #note section on alerts.html,
the preview page morning/index.html and static/morning.js. Off (M3): no email field, no submit, no form action and no
success text; the CSP is unchanged; morning.js makes no network call and its select() matches sitegen/morning.py
select() on the fixture day (site/fixtures/morning.sample.json) for every list and seat combination. The enabled path
is built only from a test config here. The browser run (Playwright Chromium over a local server) checks the picker by
keyboard, the per-seat feed choice, the preview filter, no request leaving the site, and no sideways scroll at 360 px."""
import copy
import functools
import http.server
import itertools
import json
import os
import re
import shutil
import subprocess
import threading

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, ROOT, parse
from qa import site_checks
from sitegen import config, morning, morning_page, views
from sitegen.build import build
from test_site_neutrality import BANNED

DAY = json.loads((ROOT / "site" / "fixtures" / "morning.sample.json").read_text(encoding="utf-8"))
MORNING_JS = ROOT / "site" / "static" / "morning.js"
LISTS = [x["key"] for x in config.SITE["morning_note"]["lists"]]
SEATS = [None, {"district": 7, "ward": None}, {"district": None, "ward": 6}, {"district": 7, "ward": 6},
         {"district": 3, "ward": 2}, {"district": 12, "ward": None}, {"district": None, "ward": 2}]
# Per-seat zoning feeds as T2's feed_list() shows them on the pages target (the fixture build has none).
SEAT_FEEDS = [{"file": "feeds/zoning-district-07.xml", "kind": "zoning-seat", "seat": "district", "number": 7,
               "title": "Zoning cases: District 7", "about": "", "key": "zoning-district-07"},
              {"file": "feeds/zoning-ward-06.xml", "kind": "zoning-seat", "seat": "ward", "number": 6,
               "title": "Zoning cases: Ward 6", "about": "", "key": "zoning-ward-06"}]
SUCCESS = re.compile(r"\b(subscribed|thank you|thanks|you're on|you are on|signed up|check your (e-?mail|inbox)|"
                     r"success|confirmed your)\b", re.IGNORECASE)
CSP_META = re.compile(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">')


def _build(out, monkeypatch, cfg=None, seat_feeds=False):
    monkeypatch.setattr(morning, "day", lambda date, **kw: copy.deepcopy(DAY))
    if cfg is not None:
        monkeypatch.setattr(config, "SITE", cfg)
    if seat_feeds:
        orig = morning_page.alerts_context
        monkeypatch.setattr(morning_page, "alerts_context", lambda feeds, cfg=None: orig(feeds + SEAT_FEEDS, cfg))
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS)
    return {p.relative_to(out).as_posix(): p.read_text(encoding="utf-8") for p in out.rglob("*.html")}


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    out = tmp_path_factory.mktemp("morning") / "site"
    pages = _build(out, mp, seat_feeds=True)
    mp.undo()
    return out, pages


def _main(html):
    return html[html.index("<main"):html.index("</main>")]


def _note(html):
    start = html.index('id="note"')
    return html[html.rindex("<", 0, start):html.index('<h2>How to follow a feed</h2>')]


# -- off (M3): nothing to submit, nothing claimed

def test_disabled_note_has_no_email_field_submit_action_or_names(site):
    _, pages = site
    note = _note(pages["alerts.html"])
    assert "<form" not in note and "action=" not in note
    assert 'type="email"' not in note and "<button" not in note and 'type="submit"' not in note
    assert " name=" not in note                                   # nothing could ever be submitted
    assert config.SITE["morning_note"]["page"]["state_off"] in note
    for x in config.SITE["morning_note"]["lists"]:
        assert f'id="n-{x["key"]}"' in note and x["label"] in note
    assert "<legend>" in note
    for html in pages.values():
        assert 'type="email"' not in html


def test_no_success_text_anywhere_while_disabled(site):
    _, pages = site
    for rel, html in pages.items():
        m = SUCCESS.search(parse(_main(html)).all_text())
        assert m is None, (rel, m.group(0))
    assert SUCCESS.search(MORNING_JS.read_text(encoding="utf-8")) is None
    assert SUCCESS.search(json.dumps(config.SITE["morning_note"])) is None


def test_morning_js_makes_no_network_call_and_stores_nothing():
    js = MORNING_JS.read_text(encoding="utf-8")
    for bad in ("fetch", "XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource", "import(", "new Image",
                "localStorage", "sessionStorage", "cookie", "submit(", ".src =", "open("):
        assert bad not in js, bad


def test_csp_unchanged_when_disabled(site):
    _, pages = site
    for rel, html in pages.items():
        assert CSP_META.findall(html) == [views.csp().replace("'", "&#39;")], rel
    assert morning_page.form_origin() is None


def test_nav_morning_note_links_the_section_on_every_page(site):
    _, pages = site
    for rel, html in pages.items():
        nav = html[html.index('<nav id="site-nav"'):]
        nav = nav[:nav.index("</nav>")]
        assert re.search(r'href="(\.\./)*alerts\.html#note"[^>]*>Morning note<', nav), rel
    assert 'id="note"' in pages["alerts.html"]
    assert 'aria-current="page">Morning note' not in pages["morning/index.html"]


def test_no_js_shows_every_list_and_its_feeds(site):
    _, pages = site
    tree = parse(_note(pages["alerts.html"]))
    lists = [n for n in tree.walk() if n.tag == "li" and "data-list" in n.attrs]
    assert [n.attrs["data-list"] for n in lists] == LISTS
    for n in lists:
        assert "hidden" not in n.attrs
    shown = [n.attrs["href"] for n in tree.walk() if n.tag == "a" and n.attrs.get("type") == "application/atom+xml"
             and not any("hidden" in p.attrs for p in _parents(n))]
    assert "feeds/topic-rezoning.xml" in shown and "feeds/topic-budget.xml" in shown
    assert "feeds/county-meetings.xml" in shown
    assert "feeds/zoning-district-07.xml" not in shown              # a per-seat feed waits for the stored seat
    assert 'href="feeds/zoning-district-07.xml"' in pages["alerts.html"]


def _parents(n):
    while n is not None:
        yield n
        n = n.parent


def test_list_feed_mapping():
    feeds = [{"file": "feeds/county-meetings.xml", "kind": "body", "key": "county", "title": "c"},
             {"file": "feeds/council-a-meetings.xml", "kind": "body", "key": "council-a", "title": "w"},
             {"file": "feeds/topic-rezoning.xml", "kind": "topic", "key": "rezoning", "title": "z"},
             {"file": "feeds/topic-budget.xml", "kind": "topic", "key": "budget", "title": "b"},
             {"file": "feeds/topic-contracts.xml", "kind": "topic", "key": "contracts", "title": "k"}] + SEAT_FEEDS
    by = {x["key"]: x["feeds"] for x in morning_page._lists(feeds, config.SITE)}
    assert [f["file"] for f in by["zoning"]] == ["feeds/topic-rezoning.xml", "feeds/zoning-district-07.xml",
                                                 "feeds/zoning-ward-06.xml"]
    assert [(f["file"], f["seat"]) for f in by["seats"]] == [("feeds/county-meetings.xml", "district"),
                                                             ("feeds/council-a-meetings.xml", "ward")]
    assert [f["file"] for f in by["budget"]] == ["feeds/topic-budget.xml"]
    assert [f["file"] for f in by["contracts"]] == ["feeds/topic-contracts.xml"]


# -- the preview page

def test_preview_page_renders_every_entry_with_its_filter_data(site):
    _, pages = site
    html = pages["morning/index.html"]
    tree = parse(_main(html))
    lis = [n for n in tree.walk() if n.tag == "li" and "mn-entry" in n.attrs.get("class", "")
           and "data-unplaced" not in n.attrs]
    assert len(lis) == len(DAY["entries"])
    for n, e in zip(lis, DAY["entries"]):
        assert n.attrs["data-lists"] == " ".join(e["lists"]) and n.attrs["data-body"] == e["body"]
        assert n.attrs.get("data-district") == (None if e["district"] is None else str(e["district"]))
        assert n.attrs.get("data-ward") == (None if e["ward"] is None else str(e["ward"]))
        assert e["title"] in n.all_text() and e["recorded"] in n.all_text()
    assert "1 zoning case printed no district or ward" in html
    assert "December 10, 2024: what was added to this site from December 9, 7:00 AM to December 10, 7:00 AM" in html
    assert BANNED.search(parse(_main(html)).all_text()) is None
    assert BANNED.search(json.dumps(DAY)) is None
    assert 'href="../meetings/2024-12-09-formal.html"' in html     # site links from one folder down


def test_quiet_day_says_so_and_sends_nothing(tmp_path, monkeypatch):
    quiet = {**copy.deepcopy(DAY), "entries": [], "unplaced_zoning": 0}
    monkeypatch.setattr(morning, "day", lambda date, **kw: quiet)
    out = tmp_path / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS)
    html = (out / "morning" / "index.html").read_text(encoding="utf-8")
    q = re.search(r'<p class="mn-quiet"[^>]*>', html).group(0)
    assert "hidden" not in q and config.SITE["morning_note"]["page"]["quiet"] in html


def test_site_link_check_passes_on_the_note_pages(site):
    out, _ = site
    pages = {f.relative_to(out).as_posix(): site_checks.parse(f) for f in out.rglob("*.html")}
    bad = [m for m in site_checks.check_links(out, pages, no_export=True)
           if ("alerts.html" in m or "morning/" in m) and "zoning-district-07" not in m and "zoning-ward-06" not in m]
    assert bad == []


# -- JS select() == Python select()

def _node():
    return shutil.which("node")


@pytest.mark.skipif(not _node(), reason="node not available")
def test_js_select_matches_python_select_for_every_list_and_seat_combination():
    combos = [list(c) for r in range(len(LISTS) + 1) for c in itertools.combinations(LISTS, r)]
    cases = [{"lists": c, "seats": s} for c in combos for s in SEATS]
    prog = ("const m = require(process.argv[1]); const inp = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
            "console.log(JSON.stringify(inp.cases.map(c => m.select(inp.day, c.lists, c.seats, inp.county)"
            ".map(e => e.id))));")
    r = subprocess.run(["node", "-e", prog, str(MORNING_JS)], capture_output=True, text=True, timeout=60,
                       input=json.dumps({"day": DAY, "cases": cases, "county": config.SITE["county_key"]}))
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    py = [[e["id"] for e in morning.select(DAY, c["lists"], c["seats"])] for c in cases]
    assert js == py
    # and the rule itself, as the architecture states it
    sel = lambda lists, seats: [e["id"].split("/")[2] for e in morning.select(DAY, lists, seats)]  # noqa: E731
    assert sel(["zoning"], {"district": 7, "ward": None}) == ["Z-1-2024", "CZ-5-2024"]
    assert sel(["zoning"], {"district": None, "ward": 2}) == ["Z-3-2024"]
    assert sel(["zoning"], None) == []
    assert "CZO-4-2024" not in sel(["zoning"], {"district": 7, "ward": 6})
    assert sel(["seats"], {"district": None, "ward": 6}) == ["c-1"]


def test_js_parse_lists_keeps_known_keys_only():
    if not _node():
        pytest.skip("node not available")
    prog = ("const m = require(process.argv[1]); const k = ['zoning','seats','budget','contracts'];"
            "console.log(JSON.stringify([m.parseLists('#lists=budget,zoning', k), m.parseLists('#note', k),"
            "m.parseLists('#lists=', k), m.parseLists('#lists=evil,budget', k), m.parseLists('', k)]));")
    r = subprocess.run(["node", "-e", prog, str(MORNING_JS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [["zoning", "budget"], None, [], ["budget"], None]


# -- the enabled path, from a test config only

ENABLED = {"enabled": True, "provider": "Example Mail", "form_action": "https://forms.example.net/subscribe/x",
           "privacy_url": "https://example.net/privacy"}


def test_enabled_path_in_a_test_config(tmp_path, monkeypatch):
    cfg = copy.deepcopy(config.SITE)
    cfg["morning_note"].update(ENABLED)
    pages = _build(tmp_path / "site", monkeypatch, cfg)
    html = pages["alerts.html"]
    note = _note(html)
    fields = cfg["morning_note"]["form_fields"]
    assert re.search(r'<form class="mn-card" id="note" action="https://forms\.example\.net/subscribe/x" method="post"',
                     note)
    assert f'type="email" id="note-email" name="{fields["email"]}"' in note and 'type="submit"' in note
    assert f'name="{fields["lists"]}"' in note and f'name="{fields["district"]}"' in note
    assert 'href="https://example.net/privacy"' in note and "Example Mail" in note
    pol = site_checks.parse_csp(CSP_META.findall(html)[0].replace("&#39;", "'"))
    assert pol["form-action"] == ["'self'", "https://forms.example.net"]
    assert {k: v for k, v in pol.items() if k != "form-action"} == \
        {k: v for k, v in site_checks.parse_csp(views.csp()).items() if k != "form-action"}
    for rel, page in pages.items():   # only the Alerts page gains the origin
        if rel != "alerts.html":
            assert CSP_META.findall(page) == [views.csp().replace("'", "&#39;")], rel
    assert "We keep no list of followers" not in _main(html)
    assert SUCCESS.search(parse(_main(html)).all_text()) is None
    # the preview page's picker never submits
    assert " name=" not in _main(pages["morning/index.html"]).split('class="mn-picker"')[1].split("</fieldset>")[0]


def test_enabled_without_privacy_or_action_renders_the_off_state(tmp_path, monkeypatch):
    cfg = copy.deepcopy(config.SITE)
    cfg["morning_note"].update({**ENABLED, "privacy_url": ""})
    assert not morning_page.enabled(cfg) and morning_page.form_origin(cfg) is None


# -- in a browser

def _browser_ok():
    return bool(_node()) and (os.path.exists("/opt/pw-browsers") or bool(shutil.which("playwright")))


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def served(site):
    out, _ = site
    handler = functools.partial(_Quiet, directory=str(out))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


BROWSER_JS = r"""
const path = require('path');
let pw; for (const r of [process.env.NODE_PATH, '/opt/node22/lib/node_modules'].filter(Boolean)) { try { pw = require(path.join(r, 'playwright')); break; } catch (e) {} }
const base = process.argv[1];
(async () => {
  const b = await pw.chromium.launch(); const out = {};
  const visible = (p, sel) => p.evaluate(s => [...document.querySelectorAll(s)].filter(e => e.offsetParent !== null || e.getClientRects().length).map(e => e.getAttribute('href') || e.textContent.trim()), sel);
  for (const w of [360, 1280]) {
    const ctx = await b.newContext({ viewport: { width: w, height: 760 } }); const p = await ctx.newPage();
    const errs = [], reqs = []; p.on('pageerror', e => errs.push(String(e))); p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
    p.on('request', r => reqs.push(r.url()));
    const r = {};
    // no seats stored: the hint shows, both body feeds and the all-zoning feed show
    await p.goto(base + 'alerts.html#note');
    r.legend = await p.evaluate(() => { const l = document.querySelector('#note legend'); const b = l.getBoundingClientRect(); return b.width > 0 && b.height > 0 && getComputedStyle(l).visibility === 'visible'; });
    r.noSeats = await visible(p, '#note .mn-lists > li:not([hidden]) li:not([hidden]) > a');
    r.lists0 = await p.evaluate(() => [...document.querySelectorAll('#note .mn-lists > li')].filter(l => !l.hidden).map(l => l.dataset.list));
    r.hint = await p.evaluate(() => [...document.querySelectorAll('#note [data-hint]')].filter(h => !h.hidden).length);
    // keyboard: focus the first pill and toggle it with Space
    await p.focus('#n-zoning'); r.focusRing = await p.evaluate(() => getComputedStyle(document.querySelector('#n-zoning + span')).outlineStyle);
    await p.keyboard.press('Space'); r.afterSpace = await p.evaluate(() => [document.getElementById('n-zoning').checked, document.querySelector('li[data-list=zoning]').hidden]);
    await p.keyboard.press('Tab'); r.tabTo = await p.evaluate(() => document.activeElement.id);
    await p.keyboard.press('Tab'); await p.keyboard.press('Space');
    r.preview = await p.evaluate(() => document.getElementById('mn-preview').getAttribute('href'));
    r.sw1 = await p.evaluate(() => document.documentElement.scrollWidth);
    // seats stored (as seats.js keeps them): the per-seat feeds replace the all-zoning one, the council feed hides
    await p.evaluate(() => localStorage.setItem('cr-your-seats', JSON.stringify({ district: 7, ward: null })));
    await p.goto(base + 'alerts.html'); await p.reload(); await p.check('#n-zoning');
    r.withSeats = await visible(p, '#note .mn-lists > li:not([hidden]) li:not([hidden]) > a');
    // preview page, filtered by the fragment and the stored seat
    await p.goto(base + 'morning/index.html#lists=zoning');
    r.pz = await visible(p, '.mn-entry .mn-title');
    r.unplaced = await p.evaluate(() => !document.querySelector('[data-unplaced]').hidden);
    await p.goto(base + 'morning/index.html#lists=contracts'); r.pc = await visible(p, '.mn-entry .mn-title');
    await p.uncheck('#n-contracts'); r.quiet = await p.evaluate(() => [!document.querySelector('.mn-quiet').hidden, location.hash]);
    await p.goto(base + 'morning/index.html'); r.pall = (await visible(p, '.mn-entry .mn-title')).length;
    r.sw2 = await p.evaluate(() => document.documentElement.scrollWidth); r.iw = w;
    r.errs = errs; r.foreign = reqs.filter(u => !u.startsWith(base)); out[w] = r; await ctx.close();
  }
  const ctx = await b.newContext({ viewport: { width: 360, height: 760 }, javaScriptEnabled: false }); const p = await ctx.newPage();
  await p.goto(base + 'morning/index.html');
  out.nojs = [(await visible(p, '.mn-entry .mn-title')).length, await p.evaluate(() => getComputedStyle(document.querySelector('.mn-picker')).display), await p.evaluate(() => document.documentElement.scrollWidth)];
  await p.goto(base + 'alerts.html');
  out.nojsAlerts = [(await visible(p, '#note .mn-lists > li')).length, await p.evaluate(() => document.documentElement.scrollWidth)];
  console.log(JSON.stringify(out)); await b.close();
})();
"""


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_note_and_preview_in_a_browser(served):
    env = dict(os.environ)
    if "NODE_PATH" not in env:
        env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    r = subprocess.run(["node", "-e", BROWSER_JS, served], capture_output=True, text=True, timeout=300, env=env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    titles = {e["id"].split("/")[2]: e["title"] for e in DAY["entries"]}
    for w in ("360", "1280"):
        x = out[w]
        assert x["legend"], (w, x)
        assert x["lists0"] == ["zoning", "seats"], (w, x)                       # the two default picks
        assert x["noSeats"] == ["feeds/topic-rezoning.xml", "feeds/county-meetings.xml"], (w, x)
        assert x["hint"] == 2, (w, x)
        assert x["focusRing"] == "solid", (w, x)
        assert x["afterSpace"] == [False, True], (w, x)                         # Space unpicks, the list hides
        assert x["tabTo"] == "n-seats", (w, x)
        assert x["preview"] == "morning/index.html#lists=seats,budget", (w, x)   # Space on Budget picked it
        assert "feeds/zoning-district-07.xml" in x["withSeats"], (w, x)
        assert "feeds/topic-rezoning.xml" not in x["withSeats"], (w, x)
        assert "feeds/zoning-ward-06.xml" not in x["withSeats"], (w, x)
        assert x["pz"] == [titles["Z-1-2024"], titles["CZ-5-2024"]], (w, x)
        assert x["unplaced"], (w, x)
        assert x["pc"] == [titles["rfp-1"]], (w, x)
        assert x["quiet"] == [True, "#lists="], (w, x)
        assert x["pall"] == 5, (w, x)          # all lists, district 7 stored: no ward-only or council entries
        assert x["sw1"] <= x["iw"] and x["sw2"] <= x["iw"], (w, x)              # no sideways scroll
        assert not x["errs"], (w, x)
        assert not x["foreign"], (w, x)                                         # nothing leaves the site
    assert out["nojs"] == [len(DAY["entries"]), "none", 360]
    assert out["nojsAlerts"] == [len(LISTS), 360]
