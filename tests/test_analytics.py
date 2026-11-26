"""Cookie-free visitor counting (ADR 0008, sitegen/analytics.py, static/count.js): off by default, path-only page
views, a search counted without its words, nothing typed into the address box ever sent, and qa/site_checks
holding the counter to config."""
import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, ROOT, build, root_prefix
from qa import site_checks
from sitegen import analytics, build as sitegen_build, config, views

COUNT_JS = ROOT / "site" / "static" / "count.js"
CODE = "daylight-test"
ORIGIN = f"https://{CODE}.goatcounter.com"
WEATHER = "https://api.weather.gov"   # the header's weather origin, on every page (sitegen/weather.py)
META = re.compile(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">')


def _csp(html):
    return site_checks.parse_csp(META.search(html).group(1).replace("&#39;", "'"))


def _parsed(out):
    return {p.relative_to(out).as_posix(): site_checks.parse(p) for p in out.rglob("*.html")}


# --- off by default --------------------------------------------------------------------------------------------

def test_config_counts_on_the_pages_build_only():
    # switched on 2026-11-16 (Brian's GoatCounter code); "" turns it off again (docs/ops/analytics.md)
    assert config.SITE["analytics"] == {"provider": "goatcounter", "code": "daylight-gnosh"}
    assert analytics.problems() == []
    assert analytics.settings(target="preview") is None and analytics.settings(fixture=True) is None
    assert analytics.settings(target="pages")["endpoint"] == "https://daylight-gnosh.goatcounter.com/count"


def test_off_by_default_when_the_code_is_empty():
    off = {**config.SITE, "analytics": {"provider": "goatcounter", "code": ""}}
    assert analytics.problems(off) == [] and analytics.settings(off, target="pages") is None


def test_off_build_loads_no_counter_and_connect_src_names_only_the_weather(pages):
    for rel, html in pages.items():
        assert "count.js" not in html and "goatcounter" not in html.lower() and "data-goatcounter" not in html, rel
        assert _csp(html)["connect-src"] == [WEATHER], rel       # only the header's weather (tests/test_weather.py)


def test_off_about_and_method_keep_the_no_tracking_text(pages):
    about = pages["about.html"]
    assert "outside scripts, outside fonts or visitor tracking" in about and "GoatCounter" not in about
    assert "GoatCounter" not in pages["method.html"]


def test_config_problems_refuse_anything_but_a_goatcounter_code():
    ok = {"analytics": {"provider": "goatcounter", "code": CODE}}
    assert analytics.problems(ok) == []
    for bad in ({"provider": "plausible", "code": CODE}, {"provider": "goatcounter", "code": "Bad Code"},
                {"provider": "goatcounter", "code": "x.evil.com/"}, {"provider": "goatcounter", "code": "a"},
                {"provider": "goatcounter", "code": "a b'; script-src *"}, {"provider": "goatcounter", "code": 7},
                {"provider": "goatcounter", "code": CODE, "url": "https://x"}, "on"):
        assert analytics.problems({"analytics": bad}), bad


def test_preview_and_fixture_builds_never_count():
    cfg = {"analytics": {"provider": "goatcounter", "code": CODE}}
    assert analytics.settings(cfg, target="preview") is None
    assert analytics.settings(cfg, target="pages", fixture=True) is None
    on = analytics.settings(cfg, target="pages")
    assert on["endpoint"] == ORIGIN + "/count" and on["origin"] == ORIGIN and on["label"] == "GoatCounter"


# --- on --------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def on_site(tmp_path_factory):
    """The fixture site built as if analytics.code were set on a pages build (the fixture guard bypassed here only)."""
    mp = pytest.MonkeyPatch()
    real = analytics.settings
    cfg = {**config.SITE, "analytics": {"provider": "goatcounter", "code": CODE}}
    mp.setattr(config, "SITE", cfg)
    mp.setattr(sitegen_build.config, "SITE", cfg)
    mp.setattr(analytics, "settings", lambda cfg=None, target="pages", fixture=False: real(cfg, "pages", False))
    out = tmp_path_factory.mktemp("an") / "site"
    try:
        build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, target="pages")
    finally:
        mp.undo()
    return out, cfg


def test_on_every_page_loads_count_js_and_connect_src_is_the_one_origin(on_site):
    out, _ = on_site
    for p in out.rglob("*.html"):
        html = p.read_text(encoding="utf-8")
        tags = re.findall(r'<script src="[^"]*static/count\.js" data-goatcounter="([^"]*)" defer></script>', html)
        assert tags == [ORIGIN + "/count"], p
        pol = _csp(html)
        assert pol["connect-src"] == [WEATHER, ORIGIN] and pol["script-src"][0] == "'self'", p
        assert "gc.zgo.at" not in html, p   # no provider script


def test_on_site_passes_the_external_check_and_the_check_catches_drift(on_site, tmp_path):
    out, cfg = on_site
    assert site_checks.check_external(_parsed(out), out, cfg) == []
    # off in config, on in the pages: fails
    off = {**cfg, "analytics": {"provider": "goatcounter", "code": ""}}
    assert any("while config analytics.code is empty" in p for p in site_checks.check_external(_parsed(out), out, off))
    # another counter address on one page: fails
    site = tmp_path / "site"
    shutil.copytree(out, site)
    about = site / "about.html"
    about.write_text(about.read_text(encoding="utf-8").replace(ORIGIN + "/count", "https://evil.goatcounter.com/count"),
                     encoding="utf-8")
    assert any(p.startswith("about.html: visitor counter tag") for p in site_checks.check_external(_parsed(site), site, cfg))
    # one page without the counter: fails
    about.write_text(re.sub(r'<script src="[^"]*count\.js"[^>]*></script>', "", about.read_text(encoding="utf-8")),
                     encoding="utf-8")
    assert any("want all or none" in p for p in site_checks.check_external(_parsed(site), site, cfg))


def test_on_about_and_method_say_what_is_counted(on_site):
    out, _ = on_site
    about = (out / "about.html").read_text(encoding="utf-8")
    method = (out / "method.html").read_text(encoding="utf-8")
    assert "visitor tracking" not in about
    for html in (about, method):
        assert "GoatCounter" in html and "without cookies" in html and analytics.PRIVACY_URL in html
        assert "never" in html and "what you type" in html


def test_csp_returns_to_connect_src_none_after_an_on_build(on_site):
    assert "connect-src 'none'" in views.csp()
    assert "connect-src https://x-y.goatcounter.com;" in views.csp(counter="https://x-y.goatcounter.com")
    assert not hasattr(analytics, "_ORIGIN")      # no module state can outlive a build (F4)


SENDS_NOTHING = re.compile(r"sends nothing|nothing is sent|sent anywhere", re.I)


def _claims(html):
    """The visible text of each <p> that says nothing is sent."""
    html = re.sub(r"<!--.*?-->|<script\b.*?</script>", "", html, flags=re.S)
    paras = [re.sub(r"<[^>]+>", "", p) for p in re.findall(r"<p\b[^>]*>(.*?)</p>", html, re.S)]
    return [p for p in paras if SENDS_NOTHING.search(p)]


def test_every_sends_nothing_claim_is_qualified_while_counting(on_site, pages):
    out, _ = on_site
    seen = 0
    for p in out.rglob("*.html"):
        for claim in _claims(p.read_text(encoding="utf-8")):
            seen += 1
            # a claim about the saved seats alone ("It stays on your device and is never sent anywhere") is scoped
            scoped = re.search(r"\bIt stays on your device and is never sent anywhere\b", claim)
            assert "visit count" in claim or scoped, (p.name, claim)
    assert seen
    for rel, html in pages.items():     # off: the old words, no exception named
        for claim in _claims(html):
            assert "visit count" not in claim, (rel, claim)


# --- the script --------------------------------------------------------------------------------------------------

def test_count_js_reads_no_typed_text_and_sends_path_only():
    js = COUNT_JS.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", js, flags=re.S)   # comments may name what is never read
    for banned in (".value", "localStorage", "sessionStorage", "cookie", "location.href", "location.hash",
                   "URLSearchParams", "innerText", "textContent", "FormData", "document.title", "XMLHttpRequest",
                   "sendBeacon", "addr-q", "\"q\"", "'q'"):
        assert banned not in code, banned
    assert "p: location.pathname" in code and "location.search.length" in code
    assert code.count("location.search") == 1        # only whether the page opened with a query, never its words
    assert 'credentials: "omit"' in code and 'referrerPolicy: "no-referrer"' in code


def _browser_ok():
    if not shutil.which("node"):
        return False
    return os.path.exists("/opt/pw-browsers") or bool(shutil.which("playwright"))


BROWSER_JS = r"""
const path = require('path'); const fs = require('fs');
let pw; for (const r of ['', process.env.NODE_PATH, '/opt/node22/lib/node_modules'].filter((x) => x !== undefined)) {
  try { pw = require(r ? path.join(r, 'playwright') : 'playwright'); break; } catch (e) {} }
const [site, origin] = process.argv.slice(-2);
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml',
                '.json': 'application/json', '.ico': 'image/x-icon' };
(async () => {
  const b = await pw.chromium.launch(); const sent = []; const out = {};
  async function visit(rel, act, dnt) {
    const ctx = await b.newContext();
    const page = await ctx.newPage();
    await page.addInitScript(() => { Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => false }); });
    if (dnt) await page.addInitScript(() => { Object.defineProperty(Navigator.prototype, 'doNotTrack', { get: () => '1' }); });
    await ctx.route('https://daylight.test/**', (r) => {
      const u = new URL(r.request().url()); let f = path.join(site, decodeURIComponent(u.pathname));
      if (f.endsWith('/')) f += 'index.html';
      if (!fs.existsSync(f)) return r.fulfill({ status: 404, body: '' });
      r.fulfill({ status: 200, contentType: TYPES[path.extname(f)] || 'application/octet-stream', body: fs.readFileSync(f) });
    });
    await ctx.route('https://geocoding.geo.census.gov/**', (r) => r.fulfill({ status: 200, contentType: 'text/javascript',
      body: `${new URL(r.request().url()).searchParams.get('callback')}({"result":{"addressMatches":[]}})` }));
    await ctx.route(origin + '/**', (r) => { sent.push({ url: r.request().url(), headers: r.request().headers(), from: rel });
      r.fulfill({ status: 200, body: '' }); });
    await ctx.route('https://buymeacoffee.com/**', (r) => r.fulfill({ status: 200, contentType: 'text/html', body: 'ok' }));
    await page.goto('https://daylight.test/' + rel, { waitUntil: 'load' });
    await page.waitForTimeout(300);
    if (act) await act(page);
    await page.waitForTimeout(300);
    await ctx.close();
  }
  await visit('search.html?q=secret+words', async (p) => {
    await p.fill('#q', 'another secret'); await p.waitForTimeout(1900); await p.fill('#q', 'third secret');
    await p.waitForTimeout(1900); });
  await visit('index.html#frag', async (p) => {
    const box = await p.$('#addr-q');
    if (box) { await p.evaluate(() => { const f = document.getElementById('addr-form'); if (f) f.hidden = false; });
      await box.fill('2861 McManus Circle'); await p.keyboard.press('Enter'); await p.waitForTimeout(500); }
    await p.click('a[data-ext="support"]'); });
  await visit('about.html', null, true);
  out.dnt_page = 'about.html';
  out.sent = sent;
  console.log(JSON.stringify(out)); await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_browser_sends_paths_and_events_only(on_site, tmp_path):
    out, _ = on_site
    env = dict(os.environ)
    if "NODE_PATH" not in env:
        env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    r = subprocess.run(["node", "-e", BROWSER_JS, str(out), ORIGIN], capture_output=True, text=True, timeout=300,
                       env=env)
    assert r.returncode == 0, r.stderr
    sent = json.loads(r.stdout)["sent"]
    from urllib.parse import parse_qs, urlsplit
    rows = [(s["from"], {k: v[0] for k, v in parse_qs(urlsplit(s["url"]).query).items()}, s["headers"]) for s in sent]
    for frm, q, headers in rows:
        assert set(q) <= {"p", "r", "s", "e", "rnd"}, q
        assert "referer" not in {k.lower() for k in headers}, headers
        assert "cookie" not in {k.lower() for k in headers}, headers
    blob = json.dumps([q for _, q, _ in rows]).lower()
    for typed in ("secret", "mcmanus", "2861", "frag", "?q", "words"):
        assert typed not in blob, typed
    views_ = [q["p"] for _, q, _ in rows if "e" not in q]
    events = [(f, q["p"]) for f, q, _ in rows if q.get("e") == "true"]
    assert "/search.html" in views_ and "/index.html" in views_
    assert [e for e in events if e[1] == "search"] == [("search.html?q=secret+words", "search")]   # once per view
    assert ("index.html#frag", "support-click") in events
    assert not [1 for f, _, _ in rows if f == "about.html"]   # Do Not Track: nothing sent


# --- the site in numbers (stats.html, sitegen/stats.py) ------------------------------------------------------------

def test_stats_page_counts_the_data_and_names_no_official(pages, facts):
    html = pages["stats.html"]
    main = html[html.index("<main"):html.index("</main>")]
    assert f"<dt>Meetings with minutes</dt><dd>{len(facts['meetings'])}</dd>" in main
    assert f"<dt>Agenda items</dt><dd>{len(facts['items'])}</dd>" in main
    assert f"<dt>Votes taken</dt><dd>{len(facts['roll_calls'])}</dd>" in main
    assert f"<dt>Source documents</dt><dd>{len(facts['sources'])}</dd>" in main
    assert f"<dt>Meetings listed, with an agenda, minutes or both</dt><dd>{len(facts['meetings'])}</dd>" in main
    assert "Last fetched from the official site" in main and 'class="data-as-of"' in main
    for o in facts["officials"]:          # records only: never a person, never a ranking
        assert o["name"] not in main and o["id"] not in main
    lists = " ".join(re.findall(r"<dl.*?</dl>", main, re.S)).lower()
    for word in ("rank", "top ", "most ", "best", "worst", "%"):
        assert word not in lists, word
    assert 'href="committees.html">Committees</a> <span class="chip chip-coming">Coming</span>' in main


def test_every_footer_links_the_stats_page(pages):
    for rel, html in pages.items():
        foot = html[html.index('<footer class="site-footer">'):]
        depth = root_prefix(rel)
        assert f'<a href="{depth}stats.html">The site in numbers.</a>' in foot, rel
