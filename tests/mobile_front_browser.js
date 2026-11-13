// The landing on a phone and on a wide screen (mobile-front-lite): what is shown, in what order, and how tall the
// tap targets are. Driven by tests/test_mobile_front_lite.py. Usage: node tests/mobile_front_browser.js <index.html>
// Prints JSON: {"phone": {...}, "phone-noscript": {...}, "wide": {...}, "turned": {...}}; "turned" is the phone
// page after its window grows to 900px (a phone turned sideways, a resized window).
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

function measure() {
  const el = (sel) => document.querySelector(sel);
  const shown = (e) => {
    if (!e) { return false; }
    const r = e.getBoundingClientRect();
    const s = getComputedStyle(e);
    // checkVisibility: false inside a closed <details> (its content keeps a box size in Chromium)
    return r.height > 0 && r.width > 1 && s.display !== 'none' && s.visibility !== 'hidden' && e.checkVisibility();
  };
  const text = (sel) => { const e = el(sel); return e ? e.innerText.replace(/\s+/g, ' ').trim() : null; };
  const top = (sel) => { const e = el(sel); return e ? Math.round(e.getBoundingClientRect().top + window.scrollY) : null; };
  const heights = (sel) => [...document.querySelectorAll(sel)].filter(shown).map((e) => Math.round(e.getBoundingClientRect().height));
  const fold = el('#bodies-fold');
  return {
    innerWidth: window.innerWidth, scrollWidth: document.documentElement.scrollWidth,
    lede: text('.welcome .lede'), label: text('#addr-form label'), privacy: text('#addr-privacy'),
    privacyLink: shown(el('#addr-privacy a[data-ext="geocoder"]')), listLink: shown(el('.find-alt a')),
    meetSub: text('.meetings .sec-sub'), meetFoot: text('.meet-foot'),
    intro: shown(el('.unofficial-intro')), tag: shown(el('.unofficial-tag')), notice: shown(el('.site-footer .unofficial-notice')),
    tops: { find: top('#find-h'), meetings: top('#meet-h'), doors: top('#doors-h'), bodies: top('#bodies-h'), search: top('#search-h') },
    doorTitles: [...document.querySelectorAll('.door h3')].filter(shown).length,
    doorTexts: [...document.querySelectorAll('.door > p:not(.door-coming)')].filter(shown).length,
    comingText: text('.door-coming'), comingLinks: heights('.door-coming a'),
    doorLinks: heights('.door ul a'), doors: document.querySelectorAll('.door').length,
    foldOpen: fold ? fold.open : null, summary: fold ? shown(fold.querySelector('summary')) : null,
    summaryHeight: heights('#bodies-fold > summary')[0] || 0,
    cards: [...document.querySelectorAll('.bodies-card')].filter(shown).length,
    coming: [...document.querySelectorAll('.bodies-coming')].filter(shown).length,
    footLink: heights('.meet-foot a')[0] || 0, moreLink: heights('.meet-more a')[0] || 0,
    searchLabel: (() => { const e = el('.landing-search > label'); return e ? Math.round(e.getBoundingClientRect().height) : null; })(),
    searchName: el('#landing-q') && el('#landing-q').labels.length ? el('#landing-q').labels[0].textContent.trim() : null,
  };
}

(async () => {
  const url = pathToFileURL(process.argv[2]).href;
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  const out = {};
  for (const [name, w, h, js] of [['phone', 390, 844, true], ['phone-noscript', 390, 844, false], ['wide', 1280, 800, true]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, javaScriptEnabled: js });
    const page = await ctx.newPage();
    await page.route('https://**', (r) => r.abort());
    await page.goto(url, { waitUntil: 'load' });
    out[name] = await page.evaluate(measure);
    if (name === 'phone') {
      await page.click('#bodies-fold > summary');           // the one line opens the list
      out.opened = await page.evaluate(measure);
      await page.click('#bodies-fold > summary');
      await page.setViewportSize({ width: 900, height: 600 });
      await page.waitForFunction(() => document.getElementById('bodies-fold').open);
      out.turned = await page.evaluate(measure);
    }
    await ctx.close();
  }
  await browser.close();
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
