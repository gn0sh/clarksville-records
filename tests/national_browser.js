// Daylight Digest privacy run in a real browser (daylight-national F3; architecture 3.8, 3.9 and section 6 "Privacy").
// Usage: node tests/national_browser.js <built site folder>   (driven by tests/test_national_browser.py, which builds
// the fixture site with national.enabled on and the counter on). Exit 0 when every check holds; prints one line per
// check and a JSON summary last.
//
// The built site is served from a fake https origin (https://digest.test, through page routes, so us-count.js sees an
// https page). The Census JSONP request is answered from tests/national_answers.js RECORDED (12 answers: the
// reconstructed 1 Public Sq recording and the synthetic done-when cases of tests/national.test.js); the Buttondown
// post and the GoatCounter request are stubbed; every other outside host is aborted and counted as a failure.
// For each answer it asserts: only the Census request URL holds any part of the typed address or the matched line;
// the page URL and title never change; storage holds no key but the three of 3.8, in their shapes, with no address
// text (sessionStorage and cookies stay empty); the Buttondown post holds exactly `email` and the expected `tag`s; the
// GoatCounter request after a tap holds exactly `p`, `e` and `rnd`; no CSP violation fires; no page error.
//
// navigator.webdriver: us-count.js and count.js stay silent in an automated browser, so the 12-answer run overrides
// navigator.webdriver to false with an init script to reach the tap path (and count.js then sends its page view, which
// is checked for address parts like any other request). One more run keeps webdriver true and asserts no counter
// button and no GoatCounter request at all. The native-post run removes window.fetch (an init script), so the request
// form posts itself to Buttondown as a real form (the fallback the fake-DOM tests cannot run).
const fs = require('fs');
const path = require('path');
const { RECORDED } = require('./national_answers.js');

function loadPlaywright() {
  const roots = [process.env.NODE_PATH, '/opt/node22/lib/node_modules', '/usr/local/lib/node_modules', '/usr/lib/node_modules']
    .filter(Boolean).flatMap((p) => p.split(path.delimiter));
  for (const r of [''].concat(roots)) {
    try { return require(r ? path.join(r, 'playwright') : 'playwright'); } catch (e) { /* next */ }
  }
  throw new Error('playwright not found (set NODE_PATH to the global node_modules)');
}

const SITE = path.resolve(process.argv[2] || '');
const ORIGIN = 'https://digest.test';
const ENTRY = ORIGIN + '/digest/index.html';
const CENSUS_HOST = 'geocoding.geo.census.gov';
const CENSUS_PATH = '/geocoder/geographies/onelineaddress';
const EMAIL = 'reader@example.com';
const KEYS = ['daylight.us.list', 'daylight.us.requested', 'daylight.us.counted'];
const ID_RE = /^(place|county|cousub|sdu|sds|sde)-[0-9]{2,14}$/;
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css',
  '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon',
  '.webmanifest': 'application/manifest+json', '.woff2': 'font/woff2', '.txt': 'text/plain' };

const html = fs.readFileSync(path.join(SITE, 'digest', 'index.html'), 'utf8');
const CONFIG = JSON.parse(html.match(/<script type="application\/json" id="digest-config">([^<]*)<\/script>/)[1]);
const STRINGS = JSON.parse(html.match(/<script type="application\/json" id="digest-strings">([^<]*)<\/script>/)[1]);
const COUNTER = (html.match(/data-goatcounter="([^"]+)"/) || [])[1] || null;

let failures = 0;
const summary = { cases: {}, failures: [] };
function check(label, ok, detail) {
  console.log((ok ? 'ok   ' : 'FAIL ') + label + (ok || detail === undefined ? '' : '  -> ' + JSON.stringify(detail)));
  if (!ok) { failures += 1; summary.failures.push(label); }
  return ok;
}

// --- address parts ------------------------------------------------------------------------------------------------
const STOP = new Set(['street', 'road', 'lane', 'square', 'main']);   // words a static path could hold by chance
function lineParts(line) {
  const low = line.toLowerCase().replace(/\s+/g, ' ').trim();
  const strong = new Set([low, low.split(',')[0].trim()]);
  (low.match(/\b\d{3,}\b/g) || []).forEach((d) => strong.add(d));
  const weak = new Set(strong);
  (low.match(/[a-z]{4,}/g) || []).filter((w) => !STOP.has(w)).forEach((w) => weak.add(w));
  return { strong, weak };
}
function partsOf(c) {
  const lines = [c.typed].concat(((c.answer.result || {}).addressMatches || []).map((m) => m.matchedAddress));
  const strong = new Set(), weak = new Set();
  lines.forEach((l) => { const p = lineParts(l); p.strong.forEach((x) => strong.add(x)); p.weak.forEach((x) => weak.add(x)); });
  return { strong: [...strong], weak: [...weak] };
}
function norm(s) {
  let t = String(s || '');
  try { t = decodeURIComponent(t.replace(/\+/g, ' ')); } catch (e) { /* keep raw */ }
  return t.toLowerCase().replace(/\s+/g, ' ');
}
function holds(text, list) { const t = norm(text); return list.filter((p) => t.includes(p)); }

// --- one browser context with the routes and the logs -------------------------------------------------------------
async function session(browser, opts) {
  const ctx = await browser.newContext();   // not serviceWorkers: 'block' (its injected script throws in the sandboxed frame)
  const log = { requests: [], aborted: [], census: [], buttondown: [], goat: [], console: [], errors: [] };
  log.answer = null;
  await ctx.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', (e) => {
      console.log('CSPV ' + e.violatedDirective + ' ' + e.blockedURI + ' at ' + location.href);
    });
  });
  if (opts.webdriverOff) {
    await ctx.addInitScript(() => {
      Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => false, configurable: true });
    });
  }
  if (opts.noFetch) {
    await ctx.addInitScript(() => { if (window === window.top) { delete window.fetch; window.fetch = undefined; } });
  }
  await ctx.route('**/*', async (route) => {
    const req = route.request();
    const u = new URL(req.url());
    const rec = { url: req.url(), method: req.method(), post: req.postData() || '', headers: await req.allHeaders(),
      frame: (() => { try { return req.frame().url(); } catch (e) { return ''; } })() };
    log.requests.push(rec);
    if (u.origin === ORIGIN) {
      rec.kind = 'site';
      const file = path.join(SITE, decodeURIComponent(u.pathname));
      rec.file = file.startsWith(SITE + path.sep) && fs.existsSync(file) && fs.statSync(file).isFile();
      if (!rec.file) { return route.fulfill({ status: 404, body: 'not found' }); }
      return route.fulfill({ status: 200, body: fs.readFileSync(file),
        contentType: TYPES[path.extname(file)] || 'application/octet-stream' });
    }
    if (u.host === CENSUS_HOST) {
      rec.kind = 'census';
      log.census.push(rec);
      const cb = u.searchParams.get('callback');
      return route.fulfill({ status: 200, contentType: 'text/javascript',
        body: `${cb}(${JSON.stringify(log.answer)});` });
    }
    if (u.host === 'buttondown.com') {
      rec.kind = 'buttondown';
      log.buttondown.push(rec);
      return route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>stub</title><p>stub' });
    }
    if (/\.goatcounter\.com$/.test(u.host)) {
      rec.kind = 'goat';
      log.goat.push(rec);
      return route.fulfill({ status: 200, contentType: 'image/gif', body: '' });
    }
    rec.kind = 'aborted';
    log.aborted.push(rec.url);
    return route.abort();
  });
  const page = await ctx.newPage();
  page.on('console', (m) => { if (/CSPV|Content Security Policy|Refused to/.test(m.text())) { log.console.push(m.text()); } });
  page.on('pageerror', (e) => log.errors.push(String(e)));
  return { ctx, page, log };
}

async function open(page) {
  await page.goto(ENTRY, { waitUntil: 'load' });
  await page.waitForFunction(() => { const f = document.getElementById('digest-form'); return f && !f.hidden; },
    null, { timeout: 10000 });
  return { url: page.url(), title: await page.title() };
}

async function lookUp(page, typed) {
  await page.fill('#digest-q', typed);
  await page.press('#digest-q', 'Enter');
  await page.waitForFunction((looking) => {
    if (!document.getElementById('digest-list').hidden) { return true; }
    const t = document.getElementById('digest-result').textContent.trim();
    return !!t && !t.startsWith(looking);
  }, STRINGS['lookup.looking'], { timeout: 20000 });
}

const storageOf = (page) => page.evaluate(() => {
  const all = {};
  for (let i = 0; i < localStorage.length; i += 1) { const k = localStorage.key(i); all[k] = localStorage.getItem(k); }
  return { local: all, session: sessionStorage.length, cookie: document.cookie };
});

function checkStorage(label, st, want, parts) {
  check(`${label}: storage holds only the 3.8 keys`, Object.keys(st.local).every((k) => KEYS.includes(k)), Object.keys(st.local));
  check(`${label}: no sessionStorage, no cookie`, st.session === 0 && st.cookie === '', st);
  const leaks = holds(JSON.stringify(st), parts.strong);
  check(`${label}: storage holds no address text`, leaks.length === 0, leaks);
  for (const k of KEYS) {
    const raw = st.local[k];
    if (want[k] === undefined) { check(`${label}: ${k} absent`, raw === undefined, raw); continue; }
    let v = null;
    try { v = JSON.parse(raw); } catch (e) { /* fails below */ }
    if (k === 'daylight.us.list') {
      const shape = v && Object.keys(v).sort().join() === 'govs,v' && v.v === 1 && Array.isArray(v.govs) &&
        v.govs.length <= 20 && v.govs.every((g) => Object.keys(g).sort().join() === 'id,name' && ID_RE.test(g.id) &&
          typeof g.name === 'string' && g.name.length <= 120);
      check(`${label}: ${k} is {"v":1,"govs":[{id,name}]}`, shape, raw);
      check(`${label}: ${k} lists the expected ids`, shape && JSON.stringify(v.govs.map((g) => g.id)) === JSON.stringify(want[k]),
        { got: v && v.govs, want: want[k] });
    } else {
      const shape = v && Object.keys(v).sort().join() === 'ids,v' && v.v === 1 && Array.isArray(v.ids) &&
        v.ids.every((i) => ID_RE.test(i));
      check(`${label}: ${k} is {"v":1,"ids":[...]}`, shape, raw);
      check(`${label}: ${k} holds the expected ids`, shape && JSON.stringify(v.ids) === JSON.stringify(want[k]),
        { got: v && v.ids, want: want[k] });
    }
  }
}

function checkRequests(label, log, c, parts) {
  check(`${label}: no request to any other outside host`, log.aborted.length === 0, log.aborted);
  if (c) {
    check(`${label}: exactly one Census request, from the sandboxed frame`, log.census.length === 1 &&
      /\/digest\/geo-frame\.html$/.test(log.census[0].frame), log.census.map((r) => r.frame));
    if (log.census.length) {
      const u = new URL(log.census[0].url);
      check(`${label}: the Census request is the geographies path and carries the typed address`,
        u.pathname === CENSUS_PATH && u.searchParams.get('address') === c.typed, log.census[0].url);
      check(`${label}: the Census request sends no referrer`, !log.census[0].headers.referer, log.census[0].headers.referer);
    }
  }
  for (const r of log.requests) {
    if (r.kind === 'census') { continue; }
    const sent = [r.url, r.post, r.headers.referer || '', r.headers.cookie || ''].join(' ');
    const leaks = holds(sent, r.kind === 'site' ? parts.strong : parts.weak);
    check(`${label}: ${r.kind} ${r.method} ${r.url.slice(0, 80)} holds no address part`, leaks.length === 0, leaks);
    if (r.kind === 'site') {
      const u = new URL(r.url);
      check(`${label}: site request ${u.pathname} is a built file with no query or fragment`,
        r.file && u.search === '' && u.hash === '', r.url);
    }
  }
}

function checkClean(label, log) {
  check(`${label}: no CSP violation`, log.console.length === 0, log.console);
  check(`${label}: no page error`, log.errors.length === 0, log.errors);
}

function checkPost(label, rec, wantTags) {
  if (!check(`${label}: one Buttondown post`, !!rec, null)) { return; }
  check(`${label}: posted to the configured form action`, rec.method === 'POST' && rec.url === CONFIG.form_action, rec.url);
  const body = new URLSearchParams(rec.post);
  const keys = [...new Set([...body.keys()])].sort();
  check(`${label}: the post holds exactly email and tag`, JSON.stringify(keys) === '["email","tag"]', rec.post);
  check(`${label}: the email is the one typed`, JSON.stringify(body.getAll('email')) === JSON.stringify([EMAIL]), body.getAll('email'));
  check(`${label}: the tags are the expected req- tags`, JSON.stringify(body.getAll('tag')) === JSON.stringify(wantTags),
    { got: body.getAll('tag'), want: wantTags });
}

// --- the 12 recorded answers, with the counter reachable --------------------------------------------------------
async function runCase(browser, c) {
  const label = c.name;
  const parts = partsOf(c);
  const { ctx, page, log } = await session(browser, { webdriverOff: true });
  log.answer = c.answer;
  const start = await open(page);
  check(`${label}: the counter button can show (webdriver overridden to false)`,
    await page.evaluate(() => !!(window.DaylightCount && window.DaylightCount.available)), null);
  await lookUp(page, c.typed);
  if (c.pick !== undefined) {
    const n = await page.locator('#digest-list .digest-pick-btn').count();
    check(`${label}: the picker lists each match`, n === c.answer.result.addressMatches.length, n);
    await page.locator('#digest-list .digest-pick-btn').nth(c.pick).click();
    await page.waitForSelector('#digest-list .digest-cards, #digest-list .addr-matched', { timeout: 5000 });
  }
  check(`${label}: the lookup frame is gone`, (await page.locator('iframe').count()) === 0, null);
  const statuses = await page.locator('#digest-list .digest-card').evaluateAll((els) => els.map((e) => e.getAttribute('data-status')));
  check(`${label}: ${c.ids.length} cards drawn`, statuses.length === c.ids.length, statuses);
  const open_ = c.ids.filter((_, i) => statuses[i] && statuses[i] !== 'covered');
  const want = {};
  if (c.ids.length) { want['daylight.us.list'] = c.ids; }

  if (open_.length) {
    // request the first uncovered government, ticking "Also request" for the second when there is one
    const firstReq = page.locator('#digest-list .digest-request-btn').first();
    await firstReq.click();
    const form = page.locator('#digest-list form.digest-req-form');
    await form.locator('input[type=email]').fill(EMAIL);
    const tags = ['req-' + open_[0]];
    if (open_.length > 1) {
      await form.locator('.digest-also input[type=checkbox]').first().check();
      tags.push('req-' + open_[1]);
    }
    const before = log.buttondown.length;
    await form.locator('.digest-send').click();
    await page.waitForSelector('#digest-list .digest-msg[data-state="sent"]', { timeout: 5000 });
    check(`${label}: exactly one Buttondown post for one send`, log.buttondown.length === before + 1, log.buttondown.length);
    checkPost(label, log.buttondown[before], tags);
    want['daylight.us.requested'] = tags.map((t) => t.slice(4));

    // "No email? Just count me." on the first uncovered card
    const mark = log.goat.length;
    await page.locator('#digest-list .digest-count-btn').first().click();
    await page.waitForSelector('#digest-list .digest-msg[data-state="counted"]', { timeout: 5000 });
    const taps = log.goat.slice(mark);
    if (check(`${label}: one GoatCounter request after the tap`, taps.length === 1, taps.map((r) => r.url))) {
      const u = new URL(taps[0].url);
      check(`${label}: the counter request goes to the page's counter`, u.origin + u.pathname === COUNTER, taps[0].url);
      check(`${label}: the counter request holds exactly p, e and rnd`,
        JSON.stringify([...u.searchParams.keys()]) === '["p","e","rnd"]', taps[0].url);
      check(`${label}: p is count-<id>, e is true, rnd is short random`, u.searchParams.get('p') === 'count-' + open_[0] &&
        u.searchParams.get('e') === 'true' && /^[a-z0-9]{1,8}$/.test(u.searchParams.get('rnd')), taps[0].url);
      check(`${label}: the counter request is a GET with no body, referrer or cookie`, taps[0].method === 'GET' &&
        !taps[0].post && !taps[0].headers.referer && !taps[0].headers.cookie, taps[0].headers);
    }
    want['daylight.us.counted'] = [open_[0]];
  } else {
    check(`${label}: no request form or counter button to use`,
      (await page.locator('#digest-list .digest-request-btn, #digest-list .digest-count-btn').count()) === 0, null);
  }
  check(`${label}: the page URL never changed`, page.url() === start.url, page.url());
  check(`${label}: the title never changed`, (await page.title()) === start.title, await page.title());
  check(`${label}: URL and title hold no address part`, holds(page.url() + ' ' + (await page.title()), parts.strong).length === 0, null);
  checkStorage(label, await storageOf(page), want, parts);
  const views = log.goat.filter((r) => !/[?&]p=count-/.test(r.url));
  check(`${label}: count.js page views name only the page path`, views.every((r) => new URL(r.url).searchParams.get('p') === '/digest/index.html'),
    views.map((r) => r.url));
  checkRequests(label, log, c, parts);
  checkClean(label, log);
  summary.cases[label] = { cards: statuses.length, requests: log.requests.length, census: log.census.length,
    buttondown: log.buttondown.length, goatcounter: log.goat.length };
  await ctx.close();
}

// --- webdriver left true: no counter button, nothing sent to GoatCounter ------------------------------------------
async function runAutomated(browser) {
  const c = RECORDED[0], label = 'automated browser (webdriver true)';
  const { ctx, page, log } = await session(browser, {});
  log.answer = c.answer;
  await open(page);
  await lookUp(page, c.typed);
  check(`${label}: cards drawn`, (await page.locator('#digest-list .digest-card').count()) === c.ids.length, null);
  check(`${label}: no counter button`, (await page.locator('.digest-count-btn').count()) === 0, null);
  check(`${label}: no GoatCounter request at all`, log.goat.length === 0, log.goat.map((r) => r.url));
  checkRequests(label, log, c, partsOf(c));
  checkClean(label, log);
  await ctx.close();
}

// --- fetch removed: the request form posts itself (native submit fallback) ----------------------------------------
async function runNativePost(browser) {
  const c = RECORDED.find((x) => x.ids.length === 2 && x.ids[0].startsWith('cousub-'));   // CT: two uncovered cards
  const label = 'native post (no fetch), ' + c.name;
  const parts = partsOf(c);
  const { ctx, page, log } = await session(browser, { noFetch: true });
  log.answer = c.answer;
  await open(page);
  check(`${label}: fetch is gone from the page`, await page.evaluate(() => typeof window.fetch !== 'function'), null);
  await lookUp(page, c.typed);
  const form = page.locator('#digest-list form.digest-req-form');
  await page.locator('#digest-list .digest-request-btn').first().click();
  check(`${label}: the form is a real post to the form action`, await form.evaluate((f, act) =>
    f.getAttribute('method') === 'post' && f.getAttribute('action') === act, CONFIG.form_action), null);
  await form.locator('input[type=email]').fill(EMAIL);
  await form.locator('.digest-also input[type=checkbox]').first().check();
  await Promise.all([page.waitForURL(CONFIG.form_action, { timeout: 10000 }), form.locator('.digest-send').click()]);
  check(`${label}: the native post reached Buttondown once`, log.buttondown.length === 1, log.buttondown.map((r) => r.url));
  const rec = log.buttondown[0];
  checkPost(label, rec, c.ids.map((i) => 'req-' + i));
  check(`${label}: posted as a urlencoded form`, rec && /^application\/x-www-form-urlencoded/.test(rec.headers['content-type'] || ''),
    rec && rec.headers['content-type']);
  check(`${label}: the referrer, if any, is the origin only`, rec && (!rec.headers.referer || rec.headers.referer === ORIGIN + '/'),
    rec && rec.headers.referer);
  const back = await ctx.newPage();
  back.on('console', (m) => { if (/CSPV|Content Security Policy|Refused to/.test(m.text())) { log.console.push(m.text()); } });
  await back.goto(ENTRY, { waitUntil: 'load' });
  checkStorage(label, await storageOf(back), { 'daylight.us.list': c.ids, 'daylight.us.requested': c.ids }, parts);
  check(`${label}: the saved list says Request sent on both cards`,
    (await back.locator('#digest-saved .digest-msg[data-state="returning"]').count()) === 2, null);
  checkRequests(label, log, c, parts);
  checkClean(label, log);
  await ctx.close();
}

(async () => {
  if (!fs.existsSync(path.join(SITE, 'digest', 'index.html'))) { throw new Error('no built digest/index.html under ' + SITE); }
  check('the build has the counter on (data-goatcounter on us-count.js)', !!COUNTER && /us-count\.js/.test(html), COUNTER);
  check('the build has the email form on', typeof CONFIG.form_action === 'string' && CONFIG.form_action.startsWith('https://buttondown.com/'),
    CONFIG.form_action);
  check('12 recorded answers', RECORDED.length === 12, RECORDED.length);
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  try {
    for (const c of RECORDED) { await runCase(browser, c); }
    await runAutomated(browser);
    await runNativePost(browser);
  } finally {
    await browser.close();
  }
  summary.failed = failures;
  console.log(JSON.stringify(summary));
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
