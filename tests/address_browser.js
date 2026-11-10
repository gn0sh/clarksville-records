// Browser test of the landing address box (static/address.js) against a stubbed Census geocoder, under the page's
// own CSP meta. The JSONP runs in the box's sandboxed srcdoc iframe; page.route answers its script request.
// Usage: node tests/address_browser.js <index.html> <points.json>   (driven by tests/test_address_box.py)
// points.json: {"district": [lon, lat], "near": [lon, lat], "outside": [lon, lat], "other": [lon, lat],
//               "wardnear": [lon, lat], "outsidecity": [lon, lat]}
// Prints JSON: {fit: {...}, cases: {name: {text, href, pin, requests, frame, frames, csp, ...}}}
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

function match(...pts) {
  return { result: { input: {}, addressMatches: pts.map(([lon, lat]) => ({
    matchedAddress: '1 TEST ST, CLARKSVILLE, TN, 37040', coordinates: { x: lon, y: lat } })) } };
}
// CSP violations seen by the page (and by its srcdoc iframe, which shares the policy)
// CSP violations: the top page's securitypolicyviolation events plus every frame's console "Refused to ..." lines
const WATCH = () => {
  if (window !== window.top) { return; }
  window.__csp = [];
  document.addEventListener('securitypolicyviolation', (e) => {
    window.__csp.push(e.violatedDirective + ' ' + e.blockedURI);
  });
};
function consoleCsp(page) {
  const seen = [];
  page.on('console', (m) => { if (/Content Security Policy|Refused to/.test(m.text())) seen.push(m.text()); });
  return seen;
}

(async () => {
  const url = pathToFileURL(process.argv[2]).href;
  const pts = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  const out = { fit: {}, cases: {} };

  for (const [w, h] of [[375, 667], [1280, 800]]) {
    const page = await browser.newPage({ viewport: { width: w, height: h } });
    await page.route(GEOCODER, (r) => r.fulfill({ status: 200, contentType: 'text/javascript',
      body: `${new URL(r.request().url()).searchParams.get('callback')}(${JSON.stringify(match(pts.district))})` }));
    await page.goto(url, { waitUntil: 'load' });
    const measure = () => page.evaluate(() => {
      const f = document.getElementById('addr-form');
      const r = f ? f.getBoundingClientRect() : null;
      return { scrollHeight: document.documentElement.scrollHeight, innerHeight: window.innerHeight,
               scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
               formShown: !!f && !f.hidden, formBottom: r && Math.round(r.bottom),
               resultBottom: Math.round(document.getElementById('addr-result').getBoundingClientRect().bottom),
               pin: (() => { const p = document.querySelector('.addr-pin'); if (!p) return null;
                             const b = p.getBoundingClientRect(); return [Math.round(b.top), Math.round(b.bottom)]; })() };
    });
    out.fit[`${w}x${h}`] = await measure();
    // with the privacy line and a district answer showing (the tallest the box gets), focus kept in the box
    await page.fill('#addr-q', '1 Test St, Clarksville TN');
    await page.press('#addr-q', 'Enter');
    await page.waitForFunction(() => /places this address/.test(document.getElementById('addr-result').textContent));
    await page.focus('#addr-q');
    out.fit[`${w}x${h} answered`] = await measure();
    await page.close();
  }

  // body: a JSONP body maker (cb => string), or 'abort', or 'hang'
  const cases = {
    district: (cb) => `${cb}(${JSON.stringify(match(pts.district))})`,
    near: (cb) => `${cb}(${JSON.stringify(match(pts.near))})`,
    wardnear: (cb) => `${cb}(${JSON.stringify(match(pts.wardnear))})`,
    outsidecity: (cb) => `${cb}(${JSON.stringify(match(pts.outsidecity))})`,
    outside: (cb) => `${cb}(${JSON.stringify(match(pts.outside))})`,
    twosame: (cb) => `${cb}(${JSON.stringify(match(pts.district, pts.district))})`,
    ambiguous: (cb) => `${cb}(${JSON.stringify(match(pts.district, pts.other))})`,
    ambiguousnear: (cb) => `${cb}(${JSON.stringify(match(pts.near, pts.near))})`,
    // a spoofed message from the page itself (not the iframe) is ignored; the iframe's answer wins
    spoof: 'spoof',
    // the JSONP tries to reach the parent page: it cannot (opaque origin), and the answer still comes through
    reachout: (cb) => `try { parent.document.body.setAttribute('data-pwned', '1'); } catch (e) {}
      try { parent.localStorage.setItem('x', '1'); } catch (e) {}
      ${cb}(${JSON.stringify(match(pts.district))})`,
    nomatch: (cb) => `${cb}(${JSON.stringify({ result: { input: {}, addressMatches: [] } })})`,
    badshape: (cb) => `${cb}(${JSON.stringify({ result: { addressMatches: [{ coordinates: { x: 'a', y: null } }] } })})`,
    servererror: 'status500',
    nocallback: () => '/* no callback */',
    blocked: 'abort',
  };
  for (const [name, body] of Object.entries(cases)) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    await page.addInitScript(WATCH);
    const refused = consoleCsp(page);
    const requests = [];
    let frame = null;
    await page.route(GEOCODER, async (r) => {
      const u = new URL(r.request().url());
      requests.push(u.search);
      frame = await page.evaluate(() => [...document.querySelectorAll('iframe')].map((f) => ({
        sandbox: f.getAttribute('sandbox'), referrerpolicy: f.getAttribute('referrerpolicy'), hidden: f.hidden,
        src: f.getAttribute('src'), srcdoc: (f.getAttribute('srcdoc') || '').slice(0, 120) })));
      if (body === 'spoof') {
        await page.evaluate(() => window.postMessage({ cr: 'answer', json: '{"result":{"addressMatches":[]}}' }, '*'));
        await new Promise((res) => setTimeout(res, 300));
        return r.fulfill({ status: 200, contentType: 'text/javascript',
          body: `${u.searchParams.get('callback')}(${JSON.stringify(match(pts.outside))})` });
      }
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
               hrefs: [...res.querySelectorAll('a')].map((x) => x.getAttribute('href')),
               pin: !!document.querySelector('svg.county-map .addr-pin'),
               found: [...document.querySelectorAll('#layer-districts a.is-found')].map((x) => x.getAttribute('data-district')),
               foundWards: [...document.querySelectorAll('#layer-wards .is-found')].map((x) => x.getAttribute('data-ward')),
               scripts: document.querySelectorAll('script[src*="census.gov"]').length,
               frames: document.querySelectorAll('iframe').length,
               pwned: document.body.hasAttribute('data-pwned'), csp: window.__csp,
               storage: Object.keys(localStorage).concat(Object.keys(sessionStorage)),
               storageText: JSON.stringify(localStorage),
               seats: JSON.parse(localStorage.getItem('cr-your-seats') || 'null') };
    });
    out.cases[name].requests = requests;
    out.cases[name].typedRequests = typed;
    out.cases[name].frame = frame;
    out.cases[name].refused = refused;
    await page.close();
  }
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
