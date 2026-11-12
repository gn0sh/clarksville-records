// The site still works under its own CSP meta (third-party-script/no-csp): nav drawer, landing search submit,
// search results, Show more (clamp), the official page's bar widths, and no
// CSP violation anywhere. The geocoder is stubbed (page.route) so the address box's iframe path runs too.
// Usage: node tests/csp_browser.js <base URL of a built site, ending in />   (driven by tests/test_csp.py)
// Prints JSON: {pages: {name: {refused: [...], violations: [...], ...probe}}}
const path = require('path');

function loadPlaywright() {
  const roots = [process.env.NODE_PATH, '/opt/node22/lib/node_modules', '/usr/local/lib/node_modules', '/usr/lib/node_modules']
    .filter(Boolean).flatMap((p) => p.split(path.delimiter));
  for (const r of [''].concat(roots)) {
    try { return require(r ? path.join(r, 'playwright') : 'playwright'); } catch (e) { /* next */ }
  }
  throw new Error('playwright not found (set NODE_PATH to the global node_modules)');
}

const WATCH = () => {
  if (window !== window.top) { return; }
  window.__csp = [];
  document.addEventListener('securitypolicyviolation', (e) => { window.__csp.push(e.violatedDirective + ' ' + e.blockedURI); });
};

(async () => {
  const base = process.argv[2];
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  const out = { pages: {} };
  async function visit(name, rel, probe, viewport) {
    const page = await browser.newPage({ viewport: viewport || { width: 1280, height: 800 } });
    await page.addInitScript(WATCH);
    const refused = [];
    page.on('console', (m) => { if (/Content Security Policy|Refused to/.test(m.text())) refused.push(m.text()); });
    await page.route('https://geocoding.geo.census.gov/**', (r) => r.fulfill({ status: 200, contentType: 'text/javascript',
      body: `${new URL(r.request().url()).searchParams.get('callback')}({"result":{"addressMatches":[]}})` }));
    await page.goto(base + rel, { waitUntil: 'load' });
    const res = probe ? await probe(page) : {};
    res.violations = await page.evaluate(() => window.__csp || []);
    res.refused = refused;
    res.csp = await page.evaluate(() => {
      const m = document.querySelector('meta[http-equiv="Content-Security-Policy"]');
      return m && m.getAttribute('content');
    });
    out.pages[name] = res;
    await page.close();
  }

  await visit('landing', 'index.html', async (page) => {
    const r = {};
    r.landingCsp = await page.evaluate(() => document.querySelector('meta[http-equiv="Content-Security-Policy"]').getAttribute('content'));
    await page.click('#nav-open');
    r.drawerOpen = await page.evaluate(() => !!document.querySelector('dialog.drawer[open]'));
    await page.keyboard.press('Escape');
    r.addrShown = await page.evaluate(() => { const f = document.getElementById('addr-form'); return !!f && !f.hidden; });
    if (r.addrShown) {
      await page.fill('#addr-q', '1 Test St');
      await page.click('#addr-form button');
      await page.waitForFunction(() => /No match/.test(document.getElementById('addr-result').textContent), null,
        { timeout: 10000 }).catch(() => {});
      r.addrResult = await page.evaluate(() => document.getElementById('addr-result').textContent);
    }
    await page.fill('#landing-q', 'budget');
    await Promise.all([page.waitForURL(/search\.html\?q=budget/), page.press('#landing-q', 'Enter')]);
    await page.waitForSelector('.result-list li', { timeout: 10000 }).catch(() => {});
    r.searchHits = await page.evaluate(() => document.querySelectorAll('.result-list li').length);
    return r;
  });
  await visit('landing-phone', 'index.html', async (page) => {
    await page.click('#nav-open');
    return { drawerOpen: await page.evaluate(() => !!document.querySelector('dialog.drawer[open]')) };
  }, { width: 375, height: 667 });
  await visit('meeting', process.argv[3], async (page) => ({
    clampButtons: await page.evaluate(() => document.querySelectorAll('.clamp-btn').length),
  }));
  await visit('official', process.argv[4], async (page) => ({
    segWidths: await page.evaluate(() => [...document.querySelectorAll('.bar .seg')].map((s) => Math.round(s.getBoundingClientRect().width))),
    segN: await page.evaluate(() => [...document.querySelectorAll('.bar .seg')].map((s) => s.style.getPropertyValue('--n').trim())),
  }));
  await visit('about', 'about.html');
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
