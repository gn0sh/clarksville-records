// Node tests for the Daylight Digest entry page wiring, national.js mount() (daylight-national F2; architecture 4.1,
// 4.2, 4.2a, 3.8; UX docs/design/daylight-national.md sections 1 to 3). Usage: node tests/national_page.test.js (also
// run by tests/test_national_js.py). No browser, no network, no dependency: a small fake DOM below stands in for
// digest/index.html's mount points (site/templates/digest/index.html.j2), with a fake storage, fetch, counter and
// timers. The page directory, the lookup.*/form.*/count.* strings and the config are the real ones the builder embeds
// (sitegen/national.py page_directory, national_pages.load_page_labels, morning_page.settings), so the words and
// statuses tested are the shipped ones. Each test names the F2 "done when" clause it covers.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const ROOT = path.join(__dirname, '..');
const N = require(path.join(ROOT, 'site', 'static', 'national.js'));
const PUBLIC_SQ = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'national', 'census-1-public-sq.json'), 'utf8'));

const BLOCKS = JSON.parse(execFileSync(process.env.PYTHON || 'python3', ['-c', [
  'import json',
  'from datetime import datetime, timezone',
  'from sitegen import national as n, national_pages as npg, morning_page',
  'd, f, l = n.load_all()',
  'pd = n.page_directory(d, f, l, built_at=datetime(2026, 11, 19, 15, tzinfo=timezone.utc),',
  '                      last_ok_at={"place-4715160": "2026-11-19T06:00:00Z"}, root="../")',
  'L = npg.load_page_labels()',
  'st = {k: v for k, v in L.items() if k.startswith(npg.SCRIPT_GROUPS)}',
  'note = morning_page.settings() or {}',
  'cfg = {"schema": "daylight-digest-config/1", "frame": "geo-frame.html", "covered": "covered.html",',
  '       "requested": "requested.html", "form_action": note.get("form_action"),',
  '       "privacy_url": note.get("privacy_url"), "morning": "alerts.html#note"}',
  'print(json.dumps({"pagedir": n.embed_json(pd), "strings": n.embed_json(st), "config": n.embed_json(cfg),',
  '                  "find": L["index.find"]}))',
].join('\n')], { cwd: ROOT, encoding: 'utf8' }));
const STR = JSON.parse(BLOCKS.strings);
const CFG = JSON.parse(BLOCKS.config);
const ACTION = CFG.form_action;
assert.ok(/^https:\/\/buttondown\.com\//.test(ACTION), 'the real form_action');

// --- a fake DOM: just what national.js and lookup() use ---------------------------------------------------------
class Node_ {
  constructor(doc, tag) {
    this.ownerDocument = doc; this.tagName = tag ? tag.toUpperCase() : '#text'; this.nodeType = tag ? 1 : 3;
    this.children = []; this.attrs = new Map(); this.listeners = new Map(); this.parentNode = null;
    this.hidden = false; this._text = ''; this.value = ''; this.checked = false;
  }
  get textContent() { return this.nodeType === 3 ? this._text : this.children.map((c) => c.textContent).join(''); }
  set textContent(v) {
    if (this.nodeType === 3) { this._text = String(v); return; }
    this.children.forEach((c) => { c.parentNode = null; });
    this.children = [];
    if (String(v) !== '') { this.appendChild(this.ownerDocument.createTextNode(String(v))); }
  }
  get innerHTML() { throw new Error('innerHTML read'); }
  set innerHTML(v) { throw new Error('innerHTML write'); }
  get firstChild() { return this.children[0] || null; }
  appendChild(c) {
    assert.ok(c instanceof Node_, 'appendChild takes a node');
    if (c.parentNode) { c.parentNode.removeChild(c); }
    c.parentNode = this; this.children.push(c); return c;
  }
  removeChild(c) { this.children = this.children.filter((x) => x !== c); c.parentNode = null; return c; }
  setAttribute(k, v) { this.attrs.set(k, String(v)); }
  getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }
  hasAttribute(k) { return this.attrs.has(k); }
  removeAttribute(k) { this.attrs.delete(k); }
  get id() { return this.getAttribute('id') || ''; }
  addEventListener(t, fn) { if (!this.listeners.has(t)) { this.listeners.set(t, []); } this.listeners.get(t).push(fn); }
  removeEventListener(t, fn) { this.listeners.set(t, (this.listeners.get(t) || []).filter((f) => f !== fn)); }
  focus() { this.ownerDocument.activeElement = this; this.ownerDocument.focusLog.push(this); }
  connected() { let n = this; while (n.parentNode) { n = n.parentNode; } return n === this.ownerDocument.root; }
  visible() { let n = this; while (n) { if (n.hidden) { return false; } n = n.parentNode; } return true; }
}
function fire(node, type, extra) {
  const e = Object.assign({ type, target: node, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } },
    extra || {});
  (node.listeners.get(type) || []).slice().forEach((fn) => fn(e));
  return e;
}
const walk = (n, out = []) => { out.push(n); n.children.forEach((c) => walk(c, out)); return out; };
const all = (n, pred) => walk(n).filter((x) => x.nodeType === 1 && pred(x));
const tags = (n, tag) => all(n, (x) => x.tagName === tag.toUpperCase());
const cls = (n, c) => all(n, (x) => (x.getAttribute('class') || '').split(' ').includes(c));
const byText = (n, t, tag) => all(n, (x) => (!tag || x.tagName === tag.toUpperCase()) && x.textContent === t);
const buttonNamed = (n, t) => {
  const got = tags(n, 'button').filter((b) => b.children.length && b.children[0].nodeType === 3 && b.children[0].textContent === t);
  return got;
};
const tick = () => new Promise((r) => setImmediate(r));

class FakeStorage {
  constructor(init, o) { this.m = new Map(Object.entries(init || {})); this.o = o || {}; this.writes = []; }
  getItem(k) { if (this.o.get) { throw new Error('blocked'); } return this.m.has(k) ? this.m.get(k) : null; }
  setItem(k, v) { if (this.o.set) { throw new Error('QuotaExceededError'); } this.writes.push([k, String(v)]); this.m.set(k, String(v)); }
  removeItem(k) { this.m.delete(k); }
}
const LIST = 'daylight.us.list', REQ = 'daylight.us.requested', CNT = 'daylight.us.counted';

/* The entry page's mount points, as site/templates/digest/index.html.j2 writes them. */
function makePage(o) {
  o = o || {};
  const doc = { focusLog: [], activeElement: null, titleWrites: [] };
  let title = 'Daylight Digest: Find your local governments';
  Object.defineProperty(doc, 'title', { get: () => title, set: (v) => { doc.titleWrites.push(v); title = v; } });
  doc.createElement = (t) => {
    const n = new Node_(doc, t);
    if (t === 'iframe') { n.posted = []; n.contentWindow = { postMessage: (m, to) => n.posted.push([m, to]) }; }
    return n;
  };
  doc.createTextNode = (s) => { const n = new Node_(doc, null); n._text = String(s); return n; };
  doc.root = new Node_(doc, 'html');
  doc.body = doc.root.appendChild(doc.createElement('body'));
  doc.getElementById = (id) => walk(doc.root).find((x) => x.nodeType === 1 && x.id === id) || null;
  const mk = (parent, tag, id, attrs) => {
    const n = parent.appendChild(doc.createElement(tag));
    if (id) { n.setAttribute('id', id); }
    Object.entries(attrs || {}).forEach(([k, v]) => n.setAttribute(k, v));
    return n;
  };
  const wrap = mk(doc.body, 'div', null, { class: 'digest digest-entry', 'data-root': '../' });
  const form = mk(wrap, 'form', 'digest-form', { class: 'addr-form' });
  form.hidden = true;
  mk(form, 'label', null, { for: 'digest-q' }).textContent = 'Your street address';
  const row = mk(form, 'div', null, { class: 'search-row' });
  const input = mk(row, 'input', 'digest-q', { type: 'text', autocomplete: 'street-address', maxlength: '200' });
  const find = mk(row, 'button', null, { type: 'submit' });
  find.textContent = BLOCKS.find;
  mk(form, 'p', 'digest-privacy');
  const result = mk(form, 'p', 'digest-result', { role: 'status', 'aria-live': 'polite' });
  const noscript = mk(wrap, 'p', 'digest-noscript');
  const list = mk(wrap, 'div', 'digest-list', { tabindex: '-1' });
  list.hidden = true;
  const saved = mk(wrap, 'section', 'digest-saved');
  saved.hidden = true;
  mk(wrap, 'script', 'digest-pagedir', { type: 'application/json' }).textContent = o.pagedir || BLOCKS.pagedir;
  mk(wrap, 'script', 'digest-strings', { type: 'application/json' }).textContent = BLOCKS.strings;
  mk(wrap, 'script', 'digest-config', { type: 'application/json' }).textContent =
    o.config ? JSON.stringify(Object.assign({}, CFG, o.config)) : BLOCKS.config;

  const listeners = new Set(), timers = [];
  const locationWrites = [];
  const win = {
    addEventListener(t, fn) { assert.strictEqual(t, 'message'); listeners.add(fn); },
    removeEventListener(t, fn) { listeners.delete(fn); },
  };
  Object.defineProperty(win, 'location', { get: () => ({ href: 'https://example.test/digest/' }),
    set: (v) => locationWrites.push(v) });
  const posts = [];
  const fetchFn = o.fetch === null ? null : (o.fetch || ((url, opts) => { posts.push([url, opts]); return Promise.resolve({ type: 'opaque' }); }));
  const counts = [];
  const count = o.count === undefined ? { available: true, send: (id) => { counts.push(id); return Promise.resolve(); } } : o.count;
  const storage = o.storage === null ? null : (o.storage || new FakeStorage());
  const env = { document: doc, window: win, storage, fetch: fetchFn, count,
    setTimeout(fn, ms) { const t = { fn, ms, cleared: false }; timers.push(t); return t; },
    clearTimeout(t) { if (t) { t.cleared = true; } } };
  const api = N.mount(env);
  const page = { doc, win, env, api, form, input, find, result, noscript, list, saved, storage, posts, counts, timers,
    listeners, locationWrites };
  page.frames = () => tags(doc.body, 'iframe');
  page.submit = (address) => { if (address !== undefined) { input.value = address; } return fire(form, 'submit'); };
  /* The frame says "ready", then the parent's {address} is answered with `ans` (an object, or a word). */
  page.answer = (ans) => {
    const fr = page.frames()[0];
    assert.ok(fr, 'a frame is open');
    const send = (data) => [...listeners].forEach((fn) => fn({ source: fr.contentWindow, origin: 'null', data }));
    send('"ready"');
    send(typeof ans === 'string' ? JSON.stringify(ans) : JSON.stringify(ans));
    return fr;
  };
  page.runTimers = (ms) => timers.filter((t) => !t.cleared && t.ms === ms && !t.ran).forEach((t) => { t.ran = true; t.fn(); });
  page.cards = (where) => tags(where || list, 'li').filter((li) => (li.getAttribute('class') || '').includes('digest-card'));
  page.card = (name, where) => page.cards(where).find((li) => tags(li, 'h3')[0].textContent === name);
  page.focusesSince = (n) => doc.focusLog.slice(n);
  return page;
}

// synthetic answers (same builders as tests/national.test.js)
const LAYER = { place: 'Incorporated Places', county: 'Counties', cousub: 'County Subdivisions',
  sdu: 'Unified School Districts', sds: 'Secondary School Districts', sde: 'Elementary School Districts' };
function unit(layer, geoid, name, funcstat) { return [layer, { GEOID: geoid, NAME: name, STATE: geoid.slice(0, 2), FUNCSTAT: funcstat }]; }
function match(addr, ...units) {
  const geographies = {};
  for (const [layer, u] of units) { (geographies[LAYER[layer]] = geographies[LAYER[layer]] || []).push(u); }
  return { matchedAddress: addr, geographies };
}
const answer = (...matches) => ({ result: { input: {}, addressMatches: matches } });
// Salem, OR: three governments, none in the directory (all "not covered yet")
const SALEM = answer(match('555 COURT ST NE, SALEM, OR, 97301',
  unit('place', '4164900', 'Salem city', 'A'), unit('county', '41047', 'Marion County', 'A'),
  unit('sdu', '4110040', 'Salem-Keizer School District 24J', 'A')));
const ADDRESS = '1 Public Sq, Clarksville, TN 37040';

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

// --- the address form ---------------------------------------------------------------------------------------------
test('mount: the form shows and the no-script line hides; the input has no name and the form no action', () => {
  const p = makePage();
  assert.strictEqual(p.form.hidden, false);
  assert.strictEqual(p.noscript.hidden, true);
  assert.strictEqual(p.input.hasAttribute('name'), false);
  assert.strictEqual(p.form.hasAttribute('action'), false);
  assert.strictEqual(p.form.hasAttribute('method'), false);
  assert.deepStrictEqual(p.frames(), []);
  assert.strictEqual(p.saved.hidden, true);       // nothing saved yet
});

test('submit only on press: typing, keys, change and blur start nothing; a submit starts one lookup', () => {
  const p = makePage();
  p.input.value = ADDRESS;
  for (const t of ['input', 'keydown', 'keyup', 'keypress', 'change', 'blur', 'focus', 'paste']) { fire(p.input, t); }
  assert.deepStrictEqual(p.frames(), []);
  assert.deepStrictEqual([...p.input.listeners.keys()], []);  // no listener on the input at all
  const e = p.submit();
  assert.strictEqual(e.defaultPrevented, true);                // the form itself never navigates
  assert.strictEqual(p.frames().length, 1);
  assert.strictEqual(p.find.textContent, STR['lookup.button-busy']);
  assert.strictEqual(p.find.getAttribute('aria-disabled'), 'true');
  assert.strictEqual(p.result.textContent, STR['lookup.looking']);
  p.submit();                                                  // a second press while looking is ignored
  assert.strictEqual(p.frames().length, 1);
  const fr = p.frames()[0];
  assert.ok(!fr.getAttribute('src').includes('Public'), 'no address in the frame URL');
  assert.strictEqual(fr.getAttribute('src'), 'geo-frame.html');
});

test('empty submit: the inline line, focus in the input, nothing sent', () => {
  const p = makePage();
  const n = p.doc.focusLog.length;
  p.submit('   ');
  assert.strictEqual(p.result.textContent, STR['lookup.empty']);
  assert.deepStrictEqual(p.frames(), []);
  assert.deepStrictEqual(p.focusesSince(n), [p.input]);
});

test('15 s timeout: "not answering" with Try again (focused once) and the browse link; Try again resends the box text', () => {
  const p = makePage();
  p.submit(ADDRESS);
  p.runTimers(6000);                                           // "Still looking" at 6 s
  assert.strictEqual(p.result.textContent, STR['lookup.looking'] + ' ' + STR['lookup.still']);
  const n = p.doc.focusLog.length;
  const t15 = p.timers.find((t) => t.ms === 15000);
  assert.ok(t15, 'the lookup timer is 15 s');
  p.runTimers(15000);
  assert.deepStrictEqual(p.frames(), []);                      // the frame is removed
  const retry = buttonNamed(p.result, STR['lookup.retry']);
  assert.strictEqual(retry.length, 1);
  assert.ok(p.result.textContent.startsWith(STR['lookup.down']));
  const a = tags(p.result, 'a');
  assert.strictEqual(a.length, 1);
  assert.strictEqual(a[0].getAttribute('href'), 'covered.html');
  assert.strictEqual(a[0].textContent, 'What we cover');
  assert.deepStrictEqual(p.focusesSince(n), [retry[0]]);
  assert.strictEqual(p.find.textContent, BLOCKS.find);
  assert.strictEqual(p.find.hasAttribute('aria-disabled'), false);
  assert.strictEqual(p.input.value, ADDRESS);                  // a timeout never clears what was typed
  p.input.value = ADDRESS + ' ';
  fire(retry[0], 'click');
  assert.strictEqual(p.frames().length, 1);
  p.answer(PUBLIC_SQ);
  assert.strictEqual(p.cards().length, 3);
});

test('a blocked frame and a bad answer are the same "not answering" state, never a guessed place', () => {
  for (const ans of ['blocked', 'loaded', { nope: 1 }]) {
    const p = makePage();
    p.submit(ADDRESS);
    p.answer(ans);
    assert.ok(p.result.textContent.startsWith(STR['lookup.down']), JSON.stringify(ans));
    assert.strictEqual(p.list.hidden, true);
    assert.strictEqual(p.storage.m.size, 0);
  }
});

test('not found: the tips, focus back in the input with the text kept; more than 20 matches too', () => {
  const many = answer(...Array.from({ length: 21 }, (_, i) => match(i + ' MAIN ST')));
  for (const ans of [answer(), many]) {
    const p = makePage();
    p.submit(ADDRESS);
    const n = p.doc.focusLog.length;
    p.answer(ans);
    assert.strictEqual(p.result.textContent, STR['lookup.not-found'] + ' ' + STR['lookup.not-found-tip']);
    assert.deepStrictEqual(p.focusesSince(n), [p.input]);
    assert.strictEqual(p.input.value, ADDRESS);
  }
});

test('several matches: "Which one is yours?" focused once, one button per match, "None of these" back to the input', () => {
  const p = makePage();
  p.submit('100 Main St');
  const n = p.doc.focusLog.length;
  p.answer(answer(match('100 MAIN ST, SALEM, OR, 97301', unit('place', '4164900', 'Salem city', 'A')),
    match('100 MAIN ST, SALEM, MA, 01970', unit('place', '2559105', 'Salem city', 'A'))));
  const h = tags(p.list, 'h2')[0];
  assert.strictEqual(h.textContent, STR['lookup.pick-h']);
  assert.strictEqual(h.getAttribute('tabindex'), '-1');
  assert.deepStrictEqual(p.focusesSince(n), [h]);
  const picks = cls(p.list, 'digest-pick-btn').map((b) => b.textContent);
  assert.deepStrictEqual(picks, ['100 MAIN ST, SALEM, OR, 97301', '100 MAIN ST, SALEM, MA, 01970']);
  // choosing one draws its list (no second Census request) and moves focus once, to the list heading
  const m = p.doc.focusLog.length;
  fire(cls(p.list, 'digest-pick-btn')[1], 'click');
  assert.deepStrictEqual(p.frames(), []);
  const h2 = tags(p.list, 'h2')[0];
  assert.strictEqual(h2.textContent, STR['lookup.list-h']);
  assert.deepStrictEqual(p.focusesSince(m), [h2]);
  assert.ok(p.list.textContent.includes('Census matched: 100 MAIN ST, SALEM, MA, 01970'));
  // and "None of these" from a fresh picker
  const q = makePage();
  q.submit('100 Main St');
  q.answer(answer(match('A ST'), match('B ST')));
  const k = q.doc.focusLog.length;
  fire(buttonNamed(q.list, STR['lookup.pick-none'])[0], 'click');
  assert.strictEqual(q.list.hidden, true);
  assert.deepStrictEqual(q.focusesSince(k), [q.input]);
});

// --- the list ---------------------------------------------------------------------------------------------------------
test('found (1 Public Sq): drawn on this page, URL and title never written, the address in no storage and no DOM', () => {
  const p = makePage();
  p.submit(ADDRESS);
  const n = p.doc.focusLog.length;
  const fr = p.answer(PUBLIC_SQ);
  assert.deepStrictEqual(fr.posted, [[{ address: ADDRESS }, '*']]);   // the address went to the frame only
  assert.strictEqual(p.list.hidden, false);
  const h = tags(p.list, 'h2')[0];
  assert.strictEqual(h.textContent, STR['lookup.list-h']);
  assert.deepStrictEqual(p.focusesSince(n), [h]);                       // exactly one focus move
  assert.deepStrictEqual(p.doc.titleWrites, []);
  assert.deepStrictEqual(p.locationWrites, []);
  assert.strictEqual(p.doc.title, 'Daylight Digest: Find your local governments');
  for (const [, v] of p.storage.writes) { assert.ok(!/public sq/i.test(v), v); assert.ok(!v.includes('37040'), v); }
  assert.deepStrictEqual([...p.storage.m.keys()], [LIST]);
  assert.deepStrictEqual(JSON.parse(p.storage.m.get(LIST)), { v: 1, govs: [
    { id: 'place-4715160', name: 'Clarksville city' }, { id: 'county-47125', name: 'Montgomery County' },
    { id: 'sdu-4703030', name: 'Clarksville-Montgomery County School System' }] });
  // the matched line is page text, not the typed address
  assert.ok(p.list.textContent.includes('Census matched: 1 PUBLIC SQ, CLARKSVILLE, TN, 37040'));
  assert.ok(!p.doc.root.textContent.includes(ADDRESS));
});

test('cards: slot, Census name (h3), board, pill text, and each status\'s actions in the fixed order', () => {
  const p = makePage();
  p.submit(ADDRESS);
  p.answer(PUBLIC_SQ);
  const cards = p.cards();
  assert.deepStrictEqual(cards.map((c) => cls(c, 'eyebrow')[0].textContent), ['CITY OR TOWN', 'COUNTY', 'SCHOOL DISTRICT']);
  assert.deepStrictEqual(cards.map((c) => c.getAttribute('data-status')), ['covered', 'covered', 'cant-cover']);
  const city = cards[0];
  assert.strictEqual(cls(city, 'digest-board')[0].textContent, 'Clarksville City Council');
  const chip = cls(city, 'digest-pill')[0];
  assert.strictEqual(chip.children[0].getAttribute('aria-hidden'), 'true');
  assert.ok(chip.textContent.endsWith(STR['lookup.status-covered']));
  const hrefs = tags(city, 'a').map((a) => [a.textContent, a.getAttribute('href')]);
  assert.deepStrictEqual(hrefs, [[STR['lookup.coming-up'], '../digest/tn/place-4715160.html'],
    [STR['lookup.full'], '../city/'], [STR['lookup.morning'], '../alerts.html#note']]);
  assert.deepStrictEqual(buttonNamed(city, STR['lookup.request']), []);   // no Request it on a covered card
  const school = cards[2];
  assert.ok(cls(school, 'digest-pill')[0].textContent.endsWith(STR['lookup.status-cant']));
  assert.strictEqual(cls(school, 'digest-reason')[0].textContent, 'Its records site blocks automated readers.');
  const checked = cls(school, 'digest-checked')[0];
  assert.ok(/^Checked [A-Z][a-z]+ \d{1,2}, 20\d\d\. Source$/.test(checked.textContent), checked.textContent);
  assert.strictEqual(tags(checked, 'a')[0].getAttribute('rel'), 'noopener noreferrer');
  const req = buttonNamed(school, STR['lookup.request'])[0];
  assert.strictEqual(req.textContent, STR['lookup.request'] + ': Clarksville-Montgomery County School System');
  assert.strictEqual(req.getAttribute('aria-expanded'), 'false');
  // summary: 3 found, 2 covered, 1 can't (zero parts left out)
  assert.strictEqual(cls(p.list, 'coverage')[0].textContent, "We found 3 local governments. 2 covered, 1 we can't cover.");
  // under the list: the AC2.9 line, the device line with Forget, Look up another address
  assert.ok(p.list.textContent.includes(STR['lookup.under-list']));
  assert.strictEqual(cls(p.list, 'your-seats-note')[0].textContent, STR['lookup.device-line']);
  assert.strictEqual(buttonNamed(p.list, STR['lookup.forget']).length, 1);
  assert.strictEqual(buttonNamed(p.list, STR['lookup.another']).length, 1);
});

test('nothing covered: the "None are covered yet" summary; not covered yet cards say so and have no official link', () => {
  const p = makePage();
  p.submit('555 Court St NE, Salem, OR');
  p.answer(SALEM);
  assert.strictEqual(cls(p.list, 'coverage')[0].textContent, 'We found 3 local governments. ' + STR['lookup.summary-none']);
  for (const c of p.cards()) {
    assert.strictEqual(c.getAttribute('data-status'), 'not-covered-yet');
    assert.ok(c.textContent.includes(STR['lookup.not-yet-line']));
    assert.ok(c.textContent.includes(STR['lookup.no-official']));
    assert.deepStrictEqual(tags(c, 'a'), []);
  }
});

test('notes and nothing listable: unincorporated line; a found address with no government still says so', () => {
  const p = makePage();
  p.submit('1 Farm Rd');
  p.answer(answer(match('1 FARM RD, X, OR', unit('county', '41047', 'Marion County', 'A'))));
  assert.ok(cls(p.list, 'note').map((n) => n.textContent).includes('This address is not inside a city or town.'));
  const q = makePage();
  q.submit('1 Lake Rd');
  const n = q.doc.focusLog.length;
  q.answer(answer(match('1 LAKE RD, X, RI', unit('cousub', '4400100000', 'Nowhere', 'N'))));
  assert.ok(q.list.textContent.includes(STR['lookup.nothing-listable']));
  assert.ok(q.list.textContent.includes(STR['lookup.under-list']));
  assert.strictEqual(q.focusesSince(n).length, 1);
  assert.strictEqual(q.storage.m.size, 0);                   // an empty list is not saved
});

test('Census text reaches the page as text only: markup in a name is a text node, never an element', () => {
  const p = makePage();
  p.submit(ADDRESS);
  p.answer(answer(match('<img src=x onerror=alert(1)>', unit('place', '4164900', '<b>Salem</b> city', 'A'))));
  assert.deepStrictEqual(tags(p.list, 'img'), []);
  assert.deepStrictEqual(tags(p.list, 'b'), []);
  assert.strictEqual(tags(p.list, 'h3')[0].textContent, '<b>Salem</b> city');
});

// --- the in-card request form (4.2) ----------------------------------------------------------------------------------
function openSalem(o) {
  const p = makePage(o);
  p.submit('555 Court St NE, Salem, OR');
  p.answer(SALEM);
  const card = p.card('Marion County');
  const n = p.doc.focusLog.length;
  fire(buttonNamed(card, STR['lookup.request'])[0], 'click');
  const f = tags(card, 'form')[0];
  return { p, card, f, n };
}

test('Request it opens one form in that card: heading focused once, email field, own tag, others unticked', () => {
  const { p, card, f, n } = openSalem();
  const h4 = tags(f, 'h4')[0];
  assert.strictEqual(h4.textContent, STR['form.h']);
  assert.deepStrictEqual(p.focusesSince(n), [h4]);
  assert.strictEqual(buttonNamed(card, STR['lookup.request'])[0].getAttribute('aria-expanded'), 'true');
  assert.strictEqual(f.getAttribute('method'), 'post');
  assert.strictEqual(f.getAttribute('action'), ACTION);
  const inputs = tags(f, 'input');
  const named = inputs.filter((i) => i.hasAttribute('name')).map((i) => [i.getAttribute('name'), i.getAttribute('type'), i.getAttribute('value')]);
  assert.deepStrictEqual(named, [['email', 'email', null], ['tag', 'hidden', 'req-county-41047'],
    ['tag', 'checkbox', 'req-place-4164900'], ['tag', 'checkbox', 'req-sdu-4110040']]);
  assert.strictEqual(inputs.every((i) => i.hasAttribute('name')), true);  // nothing unnamed, nothing else named
  assert.deepStrictEqual(inputs.filter((i) => i.getAttribute('type') === 'checkbox').map((i) => i.checked), [false, false]);
  const email = inputs[0];
  assert.strictEqual(email.getAttribute('autocomplete'), 'email');
  const lab = tags(f, 'label')[0];
  assert.strictEqual(lab.getAttribute('for'), email.getAttribute('id'));
  assert.strictEqual(tags(f, 'legend')[0].textContent, STR['form.also']);
  assert.ok(f.textContent.includes(STR['form.honest-not-yet']));
  const priv = tags(f, 'a')[0];
  assert.strictEqual(priv.getAttribute('href'), CFG.privacy_url);
  assert.strictEqual(priv.getAttribute('rel'), 'noopener noreferrer');
  // only one form open on the page: opening another card's closes this one
  fire(buttonNamed(p.card('Salem city'), STR['lookup.request'])[0], 'click');
  assert.strictEqual(tags(p.list, 'form').length, 1);
  assert.strictEqual(buttonNamed(card, STR['lookup.request'])[0].getAttribute('aria-expanded'), 'false');
});

test('Cancel closes the form and returns focus to Request it', () => {
  const { p, card, f } = openSalem();
  const n = p.doc.focusLog.length;
  fire(buttonNamed(f, STR['form.cancel'])[0], 'click');
  assert.deepStrictEqual(tags(card, 'form'), []);
  const req = buttonNamed(card, STR['lookup.request'])[0];
  assert.deepStrictEqual(p.focusesSince(n), [req]);
  assert.strictEqual(req.getAttribute('aria-expanded'), 'false');
});

test('bad email: the line next to the field, aria-invalid, focus on the field, nothing posted', async () => {
  const { p, f } = openSalem();
  const email = tags(f, 'input')[0];
  for (const bad of ['', 'nope', 'a@b', 'a b@c.d', 'x@y.z'.repeat(60)]) {
    email.value = bad;
    const n = p.doc.focusLog.length;
    const e = fire(f, 'submit');
    assert.strictEqual(e.defaultPrevented, true, bad);
    const err = p.doc.getElementById(email.getAttribute('aria-describedby'));
    assert.strictEqual(err.textContent, STR['form.bad-email']);
    assert.strictEqual(err.hidden, false);
    assert.strictEqual(email.getAttribute('aria-invalid'), 'true');
    assert.deepStrictEqual(p.focusesSince(n), [email]);
  }
  await tick();
  assert.deepStrictEqual(p.posts, []);
});

test('send: one no-cors POST of exactly email + one tag per ticked government (own always); ticked cards flip to Sent', async () => {
  const { p, card, f } = openSalem();
  const [email, , boxA, boxB] = tags(f, 'input');
  email.value = '  team@example.com ';
  boxB.checked = true;                                       // the school district; the city stays unticked
  boxB.setAttribute('value', 'req-evil');                    // a hand-edited value is not what is sent
  const e = fire(f, 'submit');
  assert.strictEqual(e.defaultPrevented, true);
  const send = cls(f, 'digest-send')[0];
  assert.strictEqual(send.textContent, STR['form.sending']);
  assert.strictEqual(send.getAttribute('aria-disabled'), 'true');
  fire(f, 'submit');                                         // a second press while sending is ignored
  assert.strictEqual(p.posts.length, 1);
  const [url, opts] = p.posts[0];
  assert.strictEqual(url, ACTION);
  assert.deepStrictEqual(Object.keys(opts).sort(), ['body', 'credentials', 'method', 'mode', 'referrerPolicy']);
  assert.strictEqual(opts.method, 'POST');
  assert.strictEqual(opts.mode, 'no-cors');
  assert.strictEqual(opts.credentials, 'omit');
  assert.strictEqual(opts.referrerPolicy, 'no-referrer');
  assert.ok(opts.body instanceof URLSearchParams);
  assert.deepStrictEqual([...opts.body.entries()], [['email', 'team@example.com'], ['tag', 'req-county-41047'],
    ['tag', 'req-sdu-4110040']]);
  const n = p.doc.focusLog.length;
  await tick();
  // Sent: the two ticked cards flip, the unticked one does not; focus moves once, to the sender card's message
  const sent = (c) => cls(c, 'digest-msg')[0].textContent;
  assert.strictEqual(sent(card), '✓ ' + STR['form.sent']);
  assert.strictEqual(sent(p.card('Salem-Keizer School District 24J')), '✓ ' + STR['form.sent']);
  assert.strictEqual(sent(p.card('Salem city')), '');
  assert.strictEqual(buttonNamed(card, STR['form.different']).length, 1);
  assert.deepStrictEqual(tags(p.list, 'form'), []);
  assert.deepStrictEqual(p.focusesSince(n), [cls(card, 'digest-msg')[0]]);
  // the ids are stored; the email is never stored anywhere
  assert.deepStrictEqual(JSON.parse(p.storage.m.get(REQ)), { v: 1, ids: ['county-41047', 'sdu-4110040'] });
  for (const [k, v] of p.storage.writes) { assert.ok(!v.includes('@') && !v.includes('team'), k + ' ' + v); }
  // the email stays in page memory only: the next card's form is prefilled
  fire(buttonNamed(p.card('Salem city'), STR['lookup.request'])[0], 'click');
  assert.strictEqual(tags(tags(p.card('Salem city'), 'form')[0], 'input')[0].value, 'team@example.com');
  // "Use a different email" reopens the form
  fire(buttonNamed(card, STR['form.different'])[0], 'click');
  assert.strictEqual(tags(card, 'form').length, 1);
});

test('send failed: the form stays with its text, the Failed message is focused, nothing is stored', async () => {
  const { p, card, f } = openSalem({ fetch: () => Promise.reject(new TypeError('Failed to fetch')) });
  const email = tags(f, 'input')[0];
  email.value = 'team@example.com';
  fire(f, 'submit');
  const n = p.doc.focusLog.length;
  await tick();
  const msg = cls(card, 'digest-msg')[0];
  assert.strictEqual(msg.textContent, STR['form.failed']);
  assert.deepStrictEqual(p.focusesSince(n), [msg]);
  assert.strictEqual(tags(card, 'form')[0], f);
  assert.strictEqual(email.value, 'team@example.com');
  const send = cls(f, 'digest-send')[0];
  assert.strictEqual(send.textContent, STR['form.send']);
  assert.strictEqual(send.hasAttribute('aria-disabled'), false);
  assert.strictEqual(p.storage.m.has(REQ), false);
  // a fetch that throws at once is the same Failed state
  const q = openSalem({ fetch: () => { throw new Error('blocked'); } });
  tags(q.f, 'input')[0].value = 'team@example.com';
  fire(q.f, 'submit');
  await tick();
  assert.strictEqual(cls(q.card, 'digest-msg')[0].textContent, STR['form.failed']);
});

test('no fetch: the native post is the fallback (the real form posts itself: method post, action, email + tag fields)', () => {
  const { p, f } = openSalem({ fetch: null });
  const [email, , , boxB] = tags(f, 'input');
  email.value = 'team@example.com';
  boxB.checked = true;
  const e = fire(f, 'submit');
  assert.strictEqual(e.defaultPrevented, false);             // the browser posts the form
  assert.strictEqual(f.getAttribute('method'), 'post');
  assert.strictEqual(f.getAttribute('action'), ACTION);
  assert.deepStrictEqual(JSON.parse(p.storage.m.get(REQ)), { v: 1, ids: ['county-41047', 'sdu-4110040'] });
  // a bad email still stops the post
  email.value = 'nope';
  assert.strictEqual(fire(f, 'submit').defaultPrevented, true);
});

test('Can\'t cover card: its own honest line in the form, and no "Also request" when it is the only one', () => {
  const p = makePage();
  p.submit(ADDRESS);
  p.answer(PUBLIC_SQ);
  const school = p.card('Clarksville-Montgomery County School System');
  fire(buttonNamed(school, STR['lookup.request'])[0], 'click');
  const f = tags(school, 'form')[0];
  assert.ok(f.textContent.includes(STR['form.honest-cant']));
  assert.deepStrictEqual(tags(f, 'fieldset'), []);
  assert.deepStrictEqual(tags(f, 'input').map((i) => i.getAttribute('name')), ['email', 'tag']);
});

test('returning: a requested id shows "Request sent from this device" and Request again', () => {
  const storage = new FakeStorage({ [REQ]: JSON.stringify({ v: 1, ids: ['county-41047'] }) });
  const p = makePage({ storage });
  p.submit('x');
  p.answer(SALEM);
  const card = p.card('Marion County');
  assert.strictEqual(cls(card, 'digest-msg')[0].textContent, STR['form.returning']);
  assert.strictEqual(buttonNamed(card, STR['form.again']).length, 1);
  assert.strictEqual(buttonNamed(p.card('Salem city'), STR['lookup.request']).length, 1);
});

test('no email service in the config: no Request it button (nothing to post to)', () => {
  const p = makePage({ config: { form_action: null, privacy_url: null } });
  p.submit('x');
  p.answer(SALEM);
  assert.deepStrictEqual(tags(p.list, 'form'), []);
  assert.deepStrictEqual(cls(p.list, 'digest-request-btn'), []);
  const q = makePage({ config: { form_action: 'javascript:alert(1)' } });
  q.submit('x');
  q.answer(SALEM);
  assert.deepStrictEqual(cls(q.list, 'digest-request-btn'), []);
});

// --- the counter button (4.2a) ---------------------------------------------------------------------------------------
test('"Just count me": shown only when DaylightCount.available; one event per tap; Done text, id stored', async () => {
  const p = makePage();
  p.submit('x');
  p.answer(SALEM);
  const card = p.card('Marion County');
  const b = buttonNamed(card, STR['count.button'])[0];
  assert.ok(b, 'the button shows');
  assert.strictEqual(b.textContent, STR['count.button'] + ': Marion County');
  fire(b, 'click');
  fire(b, 'click');                                          // a second tap while sending sends nothing more
  assert.deepStrictEqual(p.counts, ['county-41047']);
  const n = p.doc.focusLog.length;
  await tick();
  const msg = cls(cls(card, 'digest-count')[0], 'digest-msg')[0];
  assert.strictEqual(msg.textContent, STR['count.done']);
  assert.deepStrictEqual(p.focusesSince(n), [msg]);
  assert.deepStrictEqual(buttonNamed(card, STR['count.button']), []);
  assert.deepStrictEqual(JSON.parse(p.storage.m.get(CNT)), { v: 1, ids: ['county-41047'] });
  assert.deepStrictEqual(p.posts, []);                       // the tap sends no email
  // coming back: the Done text, no button
  const q = makePage({ storage: p.storage });
  q.submit('x');
  q.answer(SALEM);
  assert.strictEqual(cls(cls(q.card('Marion County'), 'digest-count')[0], 'digest-msg')[0].textContent, STR['count.done']);
  assert.strictEqual(buttonNamed(q.card('Salem city'), STR['count.button']).length, 1);
});

test('"Just count me" failed: the Failed text, the button stays and can be tapped again; nothing stored', async () => {
  let fail = true;
  const sent = [];
  const p = makePage({ count: { available: true, send: (id) => { sent.push(id); return fail ? Promise.reject(new Error('x')) : Promise.resolve(); } } });
  p.submit('x');
  p.answer(SALEM);
  const card = p.card('Salem city');
  const b = buttonNamed(card, STR['count.button'])[0];
  fire(b, 'click');
  const n = p.doc.focusLog.length;
  await tick();
  const msg = cls(cls(card, 'digest-count')[0], 'digest-msg')[0];
  assert.strictEqual(msg.textContent, STR['count.failed']);
  assert.deepStrictEqual(p.focusesSince(n), [msg]);
  assert.strictEqual(b.connected(), true);
  assert.strictEqual(b.hasAttribute('aria-disabled'), false);
  assert.strictEqual(p.storage.m.has(CNT), false);
  fail = false;
  fire(b, 'click');
  await tick();
  assert.deepStrictEqual(sent, ['place-4164900', 'place-4164900']);
  assert.strictEqual(cls(cls(card, 'digest-count')[0], 'digest-msg')[0].textContent, STR['count.done']);
});

test('analytics off (DaylightCount missing or not available): no counter button, and everything else works', async () => {
  for (const count of [null, { available: false, send: () => Promise.resolve() }, { available: 'yes', send: () => Promise.resolve() }]) {
    const p = makePage({ count });
    p.submit('x');
    p.answer(SALEM);
    assert.deepStrictEqual(cls(p.list, 'digest-count-btn'), [], JSON.stringify(count));
    assert.deepStrictEqual(cls(p.list, 'digest-count'), []);
    const card = p.card('Marion County');
    fire(buttonNamed(card, STR['lookup.request'])[0], 'click');
    const f = tags(card, 'form')[0];
    tags(f, 'input')[0].value = 'team@example.com';
    fire(f, 'submit');
    await tick();
    assert.strictEqual(cls(card, 'digest-msg')[0].textContent, '✓ ' + STR['form.sent']);
    assert.strictEqual(p.posts.length, 1);
  }
});

// --- Your saved list and Forget this list (3.8) ------------------------------------------------------------------------
test('Your saved list: drawn on load from storage, through strict layerOf checks; bad ids never become cards', () => {
  const storage = new FakeStorage({ [LIST]: JSON.stringify({ v: 1, govs: [
    { id: 'place-4715160', name: 'Clarksville city' },
    { id: 'place-12', name: 'Too short' },                   // passes the storage regex, not the layer length
    { id: 'county-4712', name: 'Wrong length' },
    { id: '__proto__', name: 'Proto' },
    { id: 'sdu-4703030', name: 'Clarksville-Montgomery County School System' },
    { id: 'county-41047', name: 'Marion County' }] }) });
  const p = makePage({ storage });
  assert.strictEqual(p.saved.hidden, false);
  assert.strictEqual(tags(p.saved, 'h2')[0].textContent, STR['lookup.saved-h']);
  const cards = p.cards(p.saved);
  assert.deepStrictEqual(cards.map((c) => tags(c, 'h3')[0].textContent),
    ['Clarksville city', 'Clarksville-Montgomery County School System', 'Marion County']);
  assert.deepStrictEqual(cards.map((c) => c.getAttribute('data-status')), ['covered', 'cant-cover', 'not-covered-yet']);
  assert.strictEqual(cls(p.saved, 'your-seats-note')[0].textContent, STR['lookup.device-line']);
  // its uncovered cards work as in a fresh list: Request it with the other uncovered one offered
  fire(buttonNamed(cards[2], STR['lookup.request'])[0], 'click');
  const values = tags(tags(cards[2], 'form')[0], 'input').map((i) => i.getAttribute('value'));
  assert.deepStrictEqual(values, [null, 'req-county-41047', 'req-sdu-4703030']);
});

test('saved list: bad or oversized stored values and a throwing storage show nothing and never break the page', () => {
  for (const storage of [new FakeStorage({ [LIST]: '{bad json' }), new FakeStorage({ [LIST]: 'x'.repeat(9000) }),
    new FakeStorage({}, { get: true, set: true }), null]) {
    const p = makePage({ storage });
    assert.strictEqual(p.saved.hidden, true);
    assert.strictEqual(p.form.hidden, false);
    p.submit(ADDRESS);
    p.answer(PUBLIC_SQ);
    assert.strictEqual(p.cards().length, 3);
  }
  // with storage blocked the list is not saved, so the device line (and Forget) is not shown either
  const q = makePage({ storage: new FakeStorage({}, { set: true }) });
  q.submit(ADDRESS);
  q.answer(PUBLIC_SQ);
  assert.deepStrictEqual(cls(q.list, 'your-seats-note'), []);
});

test('Forget this list removes all three keys and redraws (saved list gone, focus to the input)', () => {
  const storage = new FakeStorage({
    [LIST]: JSON.stringify({ v: 1, govs: [{ id: 'county-41047', name: 'Marion County' }] }),
    [REQ]: JSON.stringify({ v: 1, ids: ['county-41047'] }),
    [CNT]: JSON.stringify({ v: 1, ids: ['county-41047'] }),
    other: 'kept' });
  const p = makePage({ storage });
  assert.strictEqual(p.saved.hidden, false);
  const n = p.doc.focusLog.length;
  fire(buttonNamed(p.saved, STR['lookup.forget'])[0], 'click');
  assert.deepStrictEqual([...storage.m.keys()], ['other']);
  assert.strictEqual(p.saved.hidden, true);
  assert.deepStrictEqual(p.saved.children, []);
  assert.deepStrictEqual(p.focusesSince(n), [p.input]);
  // from a fresh lookup's list too
  const q = makePage();
  q.submit(ADDRESS);
  q.answer(PUBLIC_SQ);
  assert.ok(q.storage.m.has(LIST));
  fire(buttonNamed(q.list, STR['lookup.forget'])[0], 'click');
  assert.strictEqual(q.storage.m.size, 0);
  assert.strictEqual(q.list.hidden, true);
});

test('a new lookup replaces the saved list view; "Look up another address" clears the list and focuses the input', () => {
  const storage = new FakeStorage({ [LIST]: JSON.stringify({ v: 1, govs: [{ id: 'county-41047', name: 'Marion County' }] }) });
  const p = makePage({ storage });
  p.submit(ADDRESS);
  p.answer(PUBLIC_SQ);
  assert.strictEqual(p.saved.hidden, true);
  assert.strictEqual(JSON.parse(storage.m.get(LIST)).govs.length, 3);
  const n = p.doc.focusLog.length;
  fire(buttonNamed(p.list, STR['lookup.another'])[0], 'click');
  assert.strictEqual(p.list.hidden, true);
  assert.deepStrictEqual(p.focusesSince(n), [p.input]);
});

// --- focus: exactly one move after each result -----------------------------------------------------------------------
test('focus moves exactly once after each result (found, pick, not found, down, empty, sent, failed, counted)', async () => {
  const cases = [
    ['found', PUBLIC_SQ], ['pick', answer(match('A'), match('B'))], ['not found', answer()], ['down', 'blocked']];
  for (const [name, ans] of cases) {
    const p = makePage();
    p.submit(ADDRESS);
    const n = p.doc.focusLog.length;
    p.answer(ans);
    assert.strictEqual(p.focusesSince(n).length, 1, name);
  }
  const { p, f } = openSalem();
  tags(f, 'input')[0].value = 'team@example.com';
  fire(f, 'submit');
  const n = p.doc.focusLog.length;
  await tick();
  assert.strictEqual(p.focusesSince(n).length, 1, 'sent');
});

// --- source rules -----------------------------------------------------------------------------------------------------
test('source: the wiring sets text with textContent and links with setAttribute("href") from checked values only', () => {
  const src = fs.readFileSync(path.join(ROOT, 'site', 'static', 'national.js'), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
  assert.ok(!/\.href\s*=/.test(src) && !/\.src\s*=/.test(src) && !/\.action\s*=/.test(src));
  assert.ok(!/localStorage\.(setItem|getItem)/.test(src));   // storage only through the wrapped helpers
  assert.ok(!/sessionStorage|document\.cookie|indexedDB/.test(src));
  const hrefs = src.match(/setAttribute\("href", [^)]*\)/g);
  assert.deepStrictEqual(hrefs, ['setAttribute("href", href)']);
});

test('dayWords and goodEmail', () => {
  assert.strictEqual(N.dayWords('2026-11-07'), 'November 7, 2026');
  for (const bad of ['2026-13-01', '2026-1-1', 'x', null]) { assert.strictEqual(N.dayWords(bad), ''); }
  for (const ok of ['a@b.co', 'first.last+tag@sub.example.org']) { assert.strictEqual(N.goodEmail(ok), true, ok); }
  for (const bad of ['a@b', '@b.co', 'a@.co', 'a b@c.co', 'a@b.co\n', '<a@b.co>', 'a@b..co']) {
    assert.strictEqual(N.goodEmail(bad), false, bad);
  }
});

// --- run ---------------------------------------------------------------------------------------------------------
(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log('ok   ' + name); } catch (e) { failed += 1; console.log('FAIL ' + name + '\n' + e.stack); }
  }
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
