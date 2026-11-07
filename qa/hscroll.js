// Horizontal-scroll check at a phone width. Usage: node qa/hscroll.js <pages.json> [width]
// pages.json: [{"name": "officials/x.html", "path": "/abs/path/to/officials/x.html"}, ...]
// Prints JSON: [{name, width, scrollWidth, bodyScrollWidth, overflow, offenders: [...]}]
// Offenders are elements wider than the viewport that are not inside their own scroll box (overflow-x auto/scroll).
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
  const width = parseInt(process.argv[3] || '390', 10);
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width, height: 844 } });
  const results = [];
  for (const p of pages) {
    const page = await ctx.newPage();
    await page.goto(pathToFileURL(p.path).href, { waitUntil: 'load' });
    const r = await page.evaluate((w) => {
      const de = document.documentElement;
      const inScrollBox = (el) => {
        for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
          const ox = getComputedStyle(a).overflowX;
          if (ox === 'auto' || ox === 'scroll' || ox === 'hidden') return true;
        }
        return false;
      };
      const offenders = [];
      for (const el of document.body.querySelectorAll('*')) {
        const rect = el.getBoundingClientRect();
        if (rect.width > 0 && rect.right > w + 0.5 && !inScrollBox(el)) {
          offenders.push(el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.split(/\s+/).join('.') : '') + ' right=' + Math.round(rect.right));
          if (offenders.length >= 5) break;
        }
      }
      return { scrollWidth: de.scrollWidth, bodyScrollWidth: document.body.scrollWidth, innerWidth: window.innerWidth, offenders };
    }, width);
    results.push({ name: p.name, width, overflow: r.scrollWidth > width || r.bodyScrollWidth > width, ...r });
    await page.close();
  }
  await browser.close();
  process.stdout.write(JSON.stringify(results));
})().catch((e) => { process.stderr.write(String(e && e.stack || e) + '\n'); process.exit(3); });
