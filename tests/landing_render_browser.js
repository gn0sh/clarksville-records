// static/landing.js render() in a browser, the clock fixed (tests/test_front_page_v2.py). Usage:
// node tests/landing_render_browser.js <page.html> <ISO instant>  -> JSON of both lists after render
const path = require('path');
const { pathToFileURL } = require('url');

function loadPlaywright() {
  const roots = [process.env.NODE_PATH, '/opt/node22/lib/node_modules', '/usr/local/lib/node_modules', '/usr/lib/node_modules']
    .filter(Boolean).flatMap((p) => p.split(path.delimiter));
  for (const r of [''].concat(roots)) {
    try { return require(r ? path.join(r, 'playwright') : 'playwright'); } catch (e) { /* next */ }
  }
  throw new Error('playwright not found (set NODE_PATH to the global node_modules)');
}

(async () => {
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.clock.setFixedTime(new Date(process.argv[3]));
  await page.goto(pathToFileURL(process.argv[2]).href, { waitUntil: 'load' });
  const out = await page.evaluate(() => {
    const rows = (id) => [...document.getElementById(id).children].filter((li) => !li.hidden)
      .map((li) => li.getAttribute('data-iso') + (li.querySelector('[data-chip]') ? ' ' + li.querySelector('[data-chip]').textContent : ''));
    const shown = (id) => !document.getElementById(id).hidden;
    return { up: rows('meet-up'), recent: rows('meet-recent'), upList: shown('meet-up'), upEmpty: shown('meet-up-empty'),
             recEmpty: shown('meet-recent-empty'), stale: shown('meet-stale') };
  });
  await browser.close();
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
