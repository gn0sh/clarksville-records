// The landing's first screen carries the independent, unofficial status (config/site.yml `unofficial:`): the header
// tag and the short home line, before any address lookup. Driven by tests/test_unofficial_first_screen.py.
// Usage: node tests/unofficial_first_screen.js <index.html>
// Prints JSON: {"<w>x<h>": {innerHeight, formShown, tag: {bottom, visible, text}, intro: {...}, mainBottom}}
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
  const url = pathToFileURL(process.argv[2]).href;
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  const out = {};
  for (const [w, h] of [[375, 667], [1280, 800]]) {
    const page = await browser.newPage({ viewport: { width: w, height: h } });
    await page.route('https://**', (r) => r.abort());   // no lookup: the unanswered first screen
    await page.goto(url, { waitUntil: 'load' });
    out[`${w}x${h}`] = await page.evaluate(() => {
      const box = (sel) => {
        const e = document.querySelector(sel);
        if (!e) { return null; }
        const r = e.getBoundingClientRect();
        const s = getComputedStyle(e);
        return { top: Math.round(r.top), bottom: Math.round(r.bottom), text: e.innerText.trim(),
                 visible: r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && !e.closest('[hidden]') };
      };
      const f = document.getElementById('addr-form');
      return { innerHeight: window.innerHeight, formShown: !!f && !f.hidden,
               tag: box('.unofficial-tag'), intro: box('.unofficial-intro'),
               mainBottom: Math.round(document.querySelector('main').getBoundingClientRect().bottom) };
    });
    await page.close();
  }
  await browser.close();
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
