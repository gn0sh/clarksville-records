// Node tests for site/static/us-count.js (window.DaylightCount) with a fake fetch; no browser, no network.
// Usage: node tests/us_count.test.js   (also run by tests/test_us_count.py)
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'site', 'static', 'us-count.js'), 'utf8');
const COUNT = fs.readFileSync(path.join(__dirname, '..', 'site', 'static', 'count.js'), 'utf8');
const END = 'https://daylight-gnosh.goatcounter.com/count';
const OPTS = { method: 'GET', mode: 'no-cors', credentials: 'omit', cache: 'no-store', keepalive: true,
  referrerPolicy: 'no-referrer' };

function trap(name) { throw new Error('forbidden read: ' + name); }

// Load the script in a fresh context. Every storage, cookie, form and address read throws.
function load(o) {
  o = o || {};
  const calls = [];
  const win = {};
  Object.defineProperty(win, 'localStorage', { get() { return trap('window.localStorage'); } });
  Object.defineProperty(win, 'sessionStorage', { get() { return trap('window.sessionStorage'); } });
  if (o.windowDnt) { win.doNotTrack = '1'; }
  const loc = { protocol: 'https:' };
  Object.assign(loc, o.location || {});
  for (const k of ['search', 'hash', 'href', 'pathname']) {
    Object.defineProperty(loc, k, { get() { return trap('location.' + k); } });
  }
  const ctx = {
    window: win, Math, Promise, Error, Object, encodeURIComponent,
    document: {
      querySelector: (sel) => {
        assert.strictEqual(sel, 'script[data-goatcounter]');
        if (o.noTag) { return null; }
        return { getAttribute: (a) => {
          assert.strictEqual(a, 'data-goatcounter');
          return o.end === undefined ? END : o.end;
        } };
      },
      get cookie() { return trap('document.cookie'); },
      getElementById() { return trap('getElementById'); },
      getElementsByTagName() { return trap('getElementsByTagName'); },
      querySelectorAll() { return trap('querySelectorAll'); },
      get forms() { return trap('document.forms'); },
      get referrer() { return trap('document.referrer'); },
    },
    location: loc,
    navigator: o.navigator || {},
  };
  Object.defineProperty(ctx, 'localStorage', { get() { return trap('localStorage'); } });
  Object.defineProperty(ctx, 'sessionStorage', { get() { return trap('sessionStorage'); } });
  if (o.fetch !== null) {
    ctx.fetch = o.fetch || ((u, opts) => { calls.push([u, opts]); return Promise.resolve({}); });
  }
  vm.createContext(ctx);
  vm.runInContext(SRC, ctx);
  return { dc: win.DaylightCount, calls };
}

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('sends exactly one GET with the exact URL and options', async () => {
  const { dc, calls } = load();
  assert.strictEqual(dc.available, true);
  assert.strictEqual(await dc.send('sdu-4703030'), undefined);
  assert.strictEqual(calls.length, 1);
  const [url, opts] = calls[0];
  assert.match(url, /^https:\/\/daylight-gnosh\.goatcounter\.com\/count\?p=count-sdu-4703030&e=true&rnd=[a-z0-9]{1,8}$/);
  const plain = JSON.parse(JSON.stringify(opts));  // the script runs in another realm
  assert.deepStrictEqual(plain, OPTS);
  assert.deepStrictEqual(Object.keys(plain), Object.keys(OPTS));
  assert.deepStrictEqual([...new URL(url).searchParams.keys()], ['p', 'e', 'rnd']);
});

test('every layer prefix and GEOID length bound is accepted; each tap is one request with its own rnd', async () => {
  const { dc, calls } = load();
  for (const id of ['place-4715160', 'county-47125', 'cousub-4712537', 'sdu-47', 'sds-12345678901234', 'sde-00']) {
    await dc.send(id);
  }
  assert.strictEqual(calls.length, 6);
  assert.ok(calls.every((c) => /^https:\/\/daylight-gnosh\.goatcounter\.com\/count\?p=count-[a-z0-9-]+&e=true&rnd=[a-z0-9]+$/.test(c[0])));
});

test('a malformed id rejects and sends nothing', async () => {
  const { dc, calls } = load();
  const bad = ['', 'place-', 'place-4', 'place-123456789012345', 'town-4715160', 'PLACE-4715160', 'place-47x',
    'place-4715160 ', ' place-4715160', 'place-4715160\n', 'place-4715160&p=x', 'place-4715160#x', '../x',
    'sdu-4703030.slug', null, undefined, 4715160, {}, ['place-4715160'], { toString: () => 'place-4715160' }];
  for (const id of bad) {
    await assert.rejects(() => dc.send(id), Error, 'id ' + String(id));
  }
  assert.strictEqual(calls.length, 0);
  assert.strictEqual(dc.available, true);
});

test('rejects when fetch rejects, and when fetch throws', async () => {
  const boom = load({ fetch: () => Promise.reject(new TypeError('blocked')) });
  await assert.rejects(() => boom.dc.send('place-4715160'), /blocked/);
  const thrown = load({ fetch: () => { throw new Error('sync'); } });
  await assert.rejects(() => thrown.dc.send('place-4715160'), /sync/);
});

const OFF = {
  'Do Not Track (navigator)': { navigator: { doNotTrack: '1' } },
  'Do Not Track (window)': { windowDnt: true },
  'Global Privacy Control': { navigator: { globalPrivacyControl: true } },
  'automated browser': { navigator: { webdriver: true } },
  'non-https page': { location: { protocol: 'http:' } },
  'file page': { location: { protocol: 'file:' } },
  'no fetch': { fetch: null },
  'no script tag': { noTag: true },
  'empty code': { end: '' },
  'missing attribute': { end: null },
  'http endpoint': { end: 'http://daylight-gnosh.goatcounter.com/count' },
  'wrong host': { end: 'https://daylight-gnosh.example.com/count' },
  'wrong path': { end: 'https://daylight-gnosh.goatcounter.com/count/x' },
  'query in endpoint': { end: 'https://daylight-gnosh.goatcounter.com/count?x=1' },
  'empty label': { end: 'https://.goatcounter.com/count' },
  'one-letter code': { end: 'https://a.goatcounter.com/count' },
  'uppercase code': { end: 'https://Daylight.goatcounter.com/count' },
  'dash-edged code': { end: 'https://-daylight.goatcounter.com/count' },
  'dotted code': { end: 'https://evil.com/.goatcounter.com/count' },
  'userinfo code': { end: 'https://x@evil.com#.goatcounter.com/count' },
};
for (const [name, o] of Object.entries(OFF)) {
  test('sends nothing and is unavailable: ' + name, async () => {
    const { dc, calls } = load(o);
    assert.strictEqual(dc.available, false);
    await assert.rejects(() => dc.send('place-4715160'));
    assert.strictEqual(calls.length, 0);
  });
}

test('DNT/GPC values other than the opt-in values do not switch counting off (same as count.js)', () => {
  const { dc } = load({ navigator: { doNotTrack: '0', globalPrivacyControl: false, webdriver: false } });
  assert.strictEqual(dc.available, true);
});

test("its guard lines equal count.js's guard lines", () => {
  const lines = (s) => s.split('\n');
  const guard = (s) => {
    const ls = lines(s);
    const out = [];
    ls.forEach((l, i) => {
      if (/\.goatcounter\\\.com\\\/count\$|location\.protocol !== "https:"/.test(l)) { out.push(l.trim()); }
      if (/navigator\.webdriver \|\|/.test(l)) { out.push(l.trim(), ls[i + 1].trim()); }
    });
    return out;
  };
  const theirs = guard(COUNT);
  assert.strictEqual(theirs.length, 4, 'count.js guard lines found');
  assert.deepStrictEqual(guard(SRC), theirs);
  const tagLines = (s) => lines(s).filter((l) =>
    /querySelector\("script\[data-goatcounter\]"\)|getAttribute\("data-goatcounter"\)/.test(l)).map((l) => l.trim());
  assert.strictEqual(tagLines(COUNT).length, 2);
  assert.deepStrictEqual(tagLines(SRC), tagLines(COUNT));
});

test('the source reads no storage, cookie, form field or address value', () => {
  const code = SRC.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  for (const word of ['localStorage', 'sessionStorage', 'cookie', 'indexedDB', 'getElementById', 'querySelectorAll',
    'getElementsBy', 'forms', '.value', 'location.search', 'location.hash', 'location.href', 'location.pathname',
    'document.referrer', 'screen', 'XMLHttpRequest', 'sendBeacon', 'addEventListener', 'new Image']) {
    assert.ok(!code.includes(word), 'source mentions ' + word);
  }
  assert.strictEqual((code.match(/\bfetch\(/g) || []).length, 1);
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n' + e.stack); }
  }
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
