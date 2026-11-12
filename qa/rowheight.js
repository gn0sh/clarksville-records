// Row-height check. Usage: node qa/rowheight.js <pages.json> <width> <height> [maxFraction]
// pages.json: [{"name": "...", "path": "/abs/path.html"}]. A "row" is a table row, a vote-grid/legend item or a
// result item. Prints JSON [{name, rows, tallest, offenders:[{tag, h, text}]}] where offenders are taller than
// maxFraction (default 0.6) of the viewport height. Details are collapsed (default state); clamping is on.
const path = require('path');
const fs = require('fs');
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
  const pages = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const width = parseInt(process.argv[3], 10), height = parseInt(process.argv[4], 10);
  const frac = parseFloat(process.argv[5] || '0.6');
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width, height } });
  const out = [];
  for (const p of pages) {
    const page = await ctx.newPage();
    await page.goto(pathToFileURL(p.path).href, { waitUntil: 'load' });
    const r = await page.evaluate(([limit]) => {
      // open year groups so their rows are laid out; row details stay collapsed (the default)
      document.querySelectorAll('details.year-group, details.toc-group').forEach((d) => { d.open = true; });
      const rows = [...document.querySelectorAll('table tr, ul.vote-grid li, li.result')];
      let tallest = 0; const offenders = [];
      for (const el of rows) {
        const h = el.getBoundingClientRect().height;
        if (h > tallest) tallest = h;
        if (h > limit) offenders.push({ tag: el.tagName.toLowerCase() + (el.getAttribute('data-fact-id') ? '[' + el.getAttribute('data-fact-id') + ']' : ''),
          h: Math.round(h), text: (el.innerText || '').replace(/\s+/g, ' ').slice(0, 90) });
      }
      return { rows: rows.length, tallest: Math.round(tallest), offenders: offenders.slice(0, 8), n: offenders.length };
    }, [height * frac]);
    out.push({ name: p.name, ...r });
    await page.close();
  }
  await browser.close();
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { process.stderr.write(String(e && e.stack || e) + '\n'); process.exit(3); });
