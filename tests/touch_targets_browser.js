// onceover/touch/hit-area-covers-source-link: on a touch screen (pointer: coarse) a row's "Details" toggle and a
// "Show more" button are 44px targets, and neither they nor anything else lies over a link beside them: every point
// of a source link ("p. N") and of a clamped item link still hits that link.
// Usage: node tests/touch_targets_browser.js <pages.json>   pages.json: [{"name": "...", "path": "/abs/page.html"}]
// Prints JSON [{name, width, coarse, toggles, buttons, links, points, small: [...], covered: [...]}].
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
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  const out = [];
  for (const [width, height] of [[375, 812], [1280, 800]]) {
    const ctx = await browser.newContext({ viewport: { width, height }, hasTouch: true, isMobile: true });
    for (const p of pages) {
      const page = await ctx.newPage();
      await page.goto(pathToFileURL(p.path).href, { waitUntil: 'load' });
      await page.waitForTimeout(150);                   // static/clamp.js adds its buttons after the first frame
      const r = await page.evaluate(() => {
        document.querySelectorAll('details.year-group, details.toc-group').forEach((d) => { d.open = true; });
        const res = { coarse: matchMedia('(pointer: coarse)').matches, toggles: 0, buttons: 0, links: 0, points: 0,
          small: [], covered: [] };
        const label = (el) => (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40);
        const size = (el, kind) => {
          const b = el.getBoundingClientRect();
          if (b.height < 44 || b.width < 44) { res.small.push(`${kind} ${Math.round(b.width)}x${Math.round(b.height)}`); }
        };
        // the links a toggle or a button sits beside: the other links of its cell (or parent), outside any details
        const beside = (el) => {
          const box = el.closest('td, li, p, div') || el.parentElement;
          return [...box.querySelectorAll('a[href]')].filter((a) => !a.closest('details.row-details'));
        };
        const probe = (a, by) => {
          a.scrollIntoView({ block: 'center' });
          res.links += 1;
          // a clamped text shows its first lines only: the lines cut off are not on screen, so they are not probed
          const cut = a.closest('.clamp.is-clamped');
          const clip = cut ? cut.getBoundingClientRect() : null;
          for (const b of a.getClientRects()) {
            if (b.width < 1 || b.height < 1) { continue; }
            for (let i = 0; i < 6; i += 1) {
              for (let j = 0; j < 4; j += 1) {
                const x = b.left + (b.width - 1) * (i / 5) + 0.5, y = b.top + (b.height - 1) * (j / 3) + 0.5;
                if (clip && (y < clip.top || y > clip.bottom || x < clip.left || x > clip.right)) { continue; }
                const hit = document.elementFromPoint(x, y);
                res.points += 1;
                // The link, or (at the hanging space of a wrapped line) the text it sits in, is fine. Anything else
                // lies over the link: a toggle, a button, or the invisible hit area of one.
                if (!hit || !(hit === a || a.contains(hit) || hit.contains(a))) {
                  res.covered.push(`${by}: "${label(a)}" at ${Math.round(x)},${Math.round(y)} hits ` +
                    (hit ? `${hit.tagName.toLowerCase()}.${hit.className}` : 'nothing'));
                }
              }
            }
          }
        };
        [...document.querySelectorAll('details.row-details > summary')].slice(0, 80).forEach((s) => {
          if (!s.getClientRects().length) { return; }
          res.toggles += 1; size(s, 'Details'); beside(s.parentElement).forEach((a) => probe(a, 'Details'));
        });
        [...document.querySelectorAll('.clamp-btn')].slice(0, 80).forEach((btn) => {
          if (!btn.getClientRects().length) { return; }
          res.buttons += 1; size(btn, 'Show more'); beside(btn).forEach((a) => probe(a, 'Show more'));
        });
        res.small = res.small.slice(0, 10); res.covered = res.covered.slice(0, 10);
        return res;
      });
      out.push(Object.assign({ name: p.name, width }, r));
      await page.close();
    }
    await ctx.close();
  }
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
