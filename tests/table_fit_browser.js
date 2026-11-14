// onceover/dates/contracts-table-overflows-1280: at 1280 the bids table fits its own box, so the Source column's link
// needs no sideways scroll, and a date in words takes at most two lines and never breaks inside a word.
// Usage: node tests/table_fit_browser.js <page.html> [width]   Prints JSON {box, table, page, dateLines, dateWidths}.
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
  const width = parseInt(process.argv[3] || '1280', 10);
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width, height: 800 } });
  await page.goto(pathToFileURL(process.argv[2]).href, { waitUntil: 'load' });
  await page.waitForTimeout(150);
  const out = await page.evaluate(() => {
    const box = document.querySelector('.fin-scroll');
    const dates = [...document.querySelectorAll('#sol-table tbody tr:not([hidden]) td.c-date .date')];
    return {
      box: box.clientWidth, table: box.scrollWidth,
      page: [document.documentElement.clientWidth, document.documentElement.scrollWidth],
      // lines a date takes, and whether its cell is as wide as its longest word (no break inside a word)
      dateLines: dates.map((d) => new Set([...d.getClientRects()].map((r) => Math.round(r.top))).size),
      dateClipped: dates.filter((d) => d.scrollWidth > d.parentElement.clientWidth).length,
      wrap: dates.length ? getComputedStyle(dates[0].parentElement).overflowWrap : null,
    };
  });
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
