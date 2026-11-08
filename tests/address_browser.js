// Browser test of the landing address box (static/address.js) against a stubbed Census geocoder.
// Usage: node tests/address_browser.js <index.html> <points.json>   (driven by tests/test_address_js.py)
// points.json: {"district": [lon, lat], "near": [lon, lat], "outside": [lon, lat]}
// Prints JSON: {fit: {...}, cases: {name: {text, href, pin, requests: [...]}}, keystrokeRequests, storage}
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

const GEOCODER = 'https://geocoding.geo.census.gov/**';

function match(lon, lat) {
  return { result: { input: {}, addressMatches: [{ matchedAddress: '1 TEST ST, CLARKSVILLE, TN, 37040',
    coordinates: { x: lon, y: lat } }] } };
}

(async () => {
  const url = pathToFileURL(process.argv[2]).href;
  const pts = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  const out = { fit: {}, cases: {} };

  for (const [w, h] of [[375, 667], [1280, 800]]) {
    const page = await browser.newPage({ viewport: { width: w, height: h } });
    await page.route(GEOCODER, (r) => r.abort());
    await page.goto(url, { waitUntil: 'load' });
    out.fit[`${w}x${h}`] = await page.evaluate(() => {
      const f = document.getElementById('addr-form');
      const r = f ? f.getBoundingClientRect() : null;
      return { scrollHeight: document.documentElement.scrollHeight, innerHeight: window.innerHeight,
               scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
               formShown: !!f && !f.hidden, formBottom: r && Math.round(r.bottom) };
    });
    await page.close();
  }

  // body: a JSONP body maker (cb => string), or 'abort', or 'hang'
  const cases = {
    district: (cb) => `${cb}(${JSON.stringify(match(...pts.district))})`,
    near: (cb) => `${cb}(${JSON.stringify(match(...pts.near))})`,
    outside: (cb) => `${cb}(${JSON.stringify(match(...pts.outside))})`,
    nomatch: (cb) => `${cb}(${JSON.stringify({ result: { input: {}, addressMatches: [] } })})`,
    badshape: (cb) => `${cb}(${JSON.stringify({ result: { addressMatches: [{ coordinates: { x: 'a', y: null } }] } })})`,
    servererror: 'status500',
    nocallback: () => '/* no callback */',
    blocked: 'abort',
  };
  for (const [name, body] of Object.entries(cases)) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    const requests = [];
    await page.route(GEOCODER, (r) => {
      const u = new URL(r.request().url());
      requests.push(u.search);
      if (body === 'abort') return r.abort();
      if (body === 'status500') return r.fulfill({ status: 500, contentType: 'text/plain', body: 'error' });
      return r.fulfill({ status: 200, contentType: 'text/javascript', body: body(u.searchParams.get('callback')) });
    });
    await page.goto(url, { waitUntil: 'load' });
    await page.fill('#addr-q', '1 Test St, Clarksville TN <b>&"');
    const typed = requests.length;
    await page.click('#addr-form button');
    await page.waitForFunction(() => {
      const t = document.getElementById('addr-result').textContent;
      return t && !t.startsWith('Looking up');
    }, null, { timeout: 15000 });
    out.cases[name] = await page.evaluate(() => {
      const res = document.getElementById('addr-result');
      const a = res.querySelector('a');
      return { text: res.textContent, href: a && a.getAttribute('href'), html: res.innerHTML,
               pin: !!document.querySelector('svg.county-map .addr-pin'),
               found: [...document.querySelectorAll('#layer-districts a.is-found')].map((x) => x.getAttribute('data-district')),
               scripts: document.querySelectorAll('script[src*="census.gov"]').length,
               storage: localStorage.length + sessionStorage.length };
    });
    out.cases[name].requests = requests;
    out.cases[name].typedRequests = typed;
    await page.close();
  }
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
