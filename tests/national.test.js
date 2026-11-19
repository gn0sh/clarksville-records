// Node tests for site/static/national.js, the pure part of the Daylight Digest lookup (daylight-national F1, F5).
// Usage: node tests/national.test.js   (also run by tests/test_national_js.py). No browser, no network: the Census
// answers are recorded (tests/fixtures/national/census-1-public-sq.json, the verified shape in docs/platform-facts.md
// "Census geocoder") or synthetic, and the page directory is the real one, built from config/national/ by
// sitegen/national.py page_directory and embed_json (the |tojson escaping), so the flags tested are the shipped ones.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const ROOT = path.join(__dirname, '..');
const N = require(path.join(ROOT, 'site', 'static', 'national.js'));
const SRC = fs.readFileSync(path.join(ROOT, 'site', 'static', 'national.js'), 'utf8');
const PUBLIC_SQ = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'national', 'census-1-public-sq.json'), 'utf8'));

// The real page directory, as the builder embeds it.
const PAGEDIR_TEXT = execFileSync(process.env.PYTHON || 'python3', ['-c', [
  'from datetime import datetime, timezone',
  'from sitegen import national as n',
  'd, f, l = n.load_all()',
  'pd = n.page_directory(d, f, l, built_at=datetime(2026, 11, 19, 15, tzinfo=timezone.utc),',
  '                      last_ok_at={"place-4715160": "2026-11-19T06:00:00Z"})',
  'print(n.embed_json(pd))',
].join('\n')], { cwd: ROOT, encoding: 'utf8' });
const PAGEDIR = JSON.parse(PAGEDIR_TEXT);
const copyPd = () => JSON.parse(PAGEDIR_TEXT);

// --- synthetic Census answers ----------------------------------------------------------------------------------
const LAYER = { place: 'Incorporated Places', county: 'Counties', cousub: 'County Subdivisions',
  sdu: 'Unified School Districts', sds: 'Secondary School Districts', sde: 'Elementary School Districts' };
const CC = { place: 'PLACECC', county: 'COUNTYCC', cousub: 'COUSUBCC' };
function unit(layer, geoid, name, funcstat, cc) {
  const u = { OBJECTID: 1, GEOID: geoid, NAME: name, STATE: geoid.slice(0, 2), FUNCSTAT: funcstat, MTFCC: 'G0000' };
  if (cc && CC[layer]) { u[CC[layer]] = cc; }
  return [layer, u];
}
function match(addr, ...units) {
  const geographies = { States: [{ GEOID: '47', NAME: 'Tennessee', STATE: '47' }] };
  for (const [layer, u] of units) { (geographies[LAYER[layer]] = geographies[LAYER[layer]] || []).push(u); }
  return { matchedAddress: addr, coordinates: { x: -87, y: 36 }, geographies };
}
const answer = (...matches) => ({ result: { input: {}, addressMatches: matches } });
const one = (...units) => N.classify(answer(match('1 TEST ST, TOWN, ST, 00000', ...units)));
const govsOf = (units, pd) => N.governments(units, pd || PAGEDIR);
const ids = (r) => r.govs.map((g) => g.id);
const plain = (x) => JSON.parse(JSON.stringify(x));     // objects made in another module realm compare as plain data

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

// --- jsonpUrl ----------------------------------------------------------------------------------------------------
test('jsonpUrl: the geographies path, the six layers by name, fixed callback; the address is the only variable', () => {
  const u = N.jsonpUrl('1 Public Sq, Clarksville, TN');
  assert.strictEqual(u, 'https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress' +
    '?address=1%20Public%20Sq%2C%20Clarksville%2C%20TN&benchmark=Public_AR_Current&vintage=Current_Current' +
    '&layers=Incorporated%20Places,Counties,County%20Subdivisions,Unified%20School%20Districts,' +
    'Secondary%20School%20Districts,Elementary%20School%20Districts&format=jsonp&callback=crGeocode');
  const parsed = new URL(u);
  assert.deepStrictEqual([...parsed.searchParams.keys()], ['address', 'benchmark', 'vintage', 'layers', 'format', 'callback']);
});

test('jsonpUrl: an address cannot add or change a parameter', () => {
  const evil = '1 Main St&callback=alert(1)//&format=json#x';
  const parsed = new URL(N.jsonpUrl(evil));
  assert.strictEqual(parsed.searchParams.get('address'), evil);
  assert.strictEqual(parsed.searchParams.getAll('callback').length, 1);
  assert.strictEqual(parsed.searchParams.get('callback'), 'crGeocode');
  assert.strictEqual(parsed.searchParams.get('format'), 'jsonp');
  assert.strictEqual(parsed.hash, '');
});

// --- classify ----------------------------------------------------------------------------------------------------
test('classify: recorded 1 Public Sq answer -> one match, the four layers present, other layers ignored', () => {
  const r = N.classify(PUBLIC_SQ);
  assert.strictEqual(r.kind, 'one');
  assert.strictEqual(r.matched, '1 PUBLIC SQ, CLARKSVILLE, TN, 37040');
  assert.deepStrictEqual(plain(r.units), [
    { id: 'place-4715160', layer: 'place', name: 'Clarksville city', funcstat: 'A', state: '47', cc: 'C1' },
    { id: 'county-47125', layer: 'county', name: 'Montgomery County', funcstat: 'A', state: '47', cc: 'H1' },
    { id: 'cousub-4712590886', layer: 'cousub', name: 'District 5', funcstat: 'N', state: '47', cc: 'Z1' },
    { id: 'sdu-4703030', layer: 'sdu', name: 'Clarksville-Montgomery County School System', funcstat: 'E',
      state: '47', cc: '' },
  ]);
});

test('governments: 1 Public Sq -> city, county, school district; District 5 (FUNCSTAT N) dropped; no notes', () => {
  const r = govsOf(N.classify(PUBLIC_SQ).units);
  assert.deepStrictEqual(plain(r), {
    govs: [
      { id: 'place-4715160', name: 'Clarksville city', slot: 'place', status: 'covered',
        board: 'Clarksville City Council', page: 'digest/tn/place-4715160.html', full: 'city/', stale: false },
      { id: 'county-47125', name: 'Montgomery County', slot: 'county', status: 'covered',
        board: 'Montgomery County Commission', page: 'digest/tn/county-47125.html', full: 'meetings/agendas.html',
        stale: true },
      { id: 'sdu-4703030', name: 'Clarksville-Montgomery County School System', slot: 'sdu', status: 'cant-cover',
        board: 'Clarksville-Montgomery County School System Board of Education', official_url: 'https://www.cmcss.net/',
        reason: 'blocks-readers', checked: '2026-11-10', reason_url: 'https://www.cmcss.net/' },
    ],
    notes: [],
  });
  assert.strictEqual(N.label(PAGEDIR, 'reason.blocks-readers'), 'Its records site blocks automated readers.');
  assert.strictEqual(N.label(PAGEDIR, 'slot.sdu'), 'SCHOOL DISTRICT');
});

test('classify: bad shapes are "error"; no match is "nomatch"', () => {
  for (const a of [null, undefined, 'x', 3, [], {}, { result: null }, { result: {} }, { result: { addressMatches: {} } },
    { result: { addressMatches: 'no' } }]) {
    assert.strictEqual(N.classify(a).kind, 'error', JSON.stringify(a));
  }
  assert.deepStrictEqual(plain(N.classify(answer())), { kind: 'nomatch' });
});

test('classify: 3 matches -> pick, each with its own label and units (no second request needed)', () => {
  const r = N.classify(answer(
    match('100 MAIN ST, SPRINGFIELD, IL, 62701', unit('place', '1772000', 'Springfield city', 'A', 'C1')),
    match('100 MAIN ST, SPRINGFIELD, MO, 65806', unit('place', '2970000', 'Springfield city', 'A', 'C1')),
    match('100 MAIN ST, SPRINGFIELD, OR, 97477', unit('place', '4169600', 'Springfield city', 'A', 'C1'))));
  assert.strictEqual(r.kind, 'pick');
  assert.deepStrictEqual(r.matches.map((m) => m.label), ['100 MAIN ST, SPRINGFIELD, IL, 62701',
    '100 MAIN ST, SPRINGFIELD, MO, 65806', '100 MAIN ST, SPRINGFIELD, OR, 97477']);
  assert.deepStrictEqual(r.matches.map((m) => m.units.map((u) => u.id)), [['place-1772000'], ['place-2970000'],
    ['place-4169600']]);
});

test('classify: 20 matches is a pick; 21 is the not-found tips (nomatch, many)', () => {
  const m = (i) => match('ADDR ' + i, unit('place', '4715160', 'Clarksville city', 'A', 'C1'));
  assert.strictEqual(N.classify(answer(...Array.from({ length: 20 }, (_, i) => m(i)))).matches.length, 20);
  assert.deepStrictEqual(plain(N.classify(answer(...Array.from({ length: 21 }, (_, i) => m(i))))),
    { kind: 'nomatch', many: true });
});

test('classify: Census text is cleaned of controls and bidi overrides and capped; labels too', () => {
  const r = one(unit('place', '4715160', 'Clark‮sville\u0000 city\n', 'A', 'C1'),
    unit('county', '47125', 'x'.repeat(500), 'A', 'H1'));
  assert.strictEqual(r.units[0].name, 'Clark sville city');
  assert.strictEqual(r.units[1].name.length, 120);
  const r2 = N.classify(answer(match('1 MAIN⁦ ST' + 'y'.repeat(400))));
  assert.strictEqual(r2.matched, ('1 MAIN ST' + 'y'.repeat(400)).replace('MAIN ST', 'MAIN  ST').replace(/\s+/g, ' ').slice(0, 200));
  assert.ok(!/[⁦\u0000]/.test(r2.matched));
});

// --- governments: the done-when cases (synthetic) ----------------------------------------------------------------
test('unincorporated: no place -> note no-city; county and school district kept', () => {
  const r = govsOf(one(unit('county', '47125', 'Montgomery County', 'A', 'H1'),
    unit('cousub', '4712590886', 'District 5', 'N', 'Z1'),
    unit('sdu', '4703030', 'Clarksville-Montgomery County School System', 'E')).units);
  assert.deepStrictEqual(ids(r), ['county-47125', 'sdu-4703030']);
  assert.deepStrictEqual(r.notes, ['note.no-city']);
});

test('FUNCSTAT: N subdivision dropped; place/county/cousub keep only A, school districts A or E', () => {
  const r = govsOf(one(unit('place', '4799001', 'Place B', 'B', 'C1'), unit('place', '4799002', 'Place S', 'S', 'C1'),
    unit('county', '47125', 'Montgomery County', 'A', 'H1'), unit('cousub', '4712590886', 'District 5', 'N', 'Z1'),
    unit('cousub', '4712590887', 'District 6', 'E', 'T1'), unit('sdu', '4703030', 'CMCSS', 'E'),
    unit('sds', '4700001', 'Sec A', 'A'), unit('sde', '4700002', 'Elem F', 'F'), unit('sde', '4700003', 'Elem none', '')).units);
  assert.deepStrictEqual(ids(r), ['county-47125', 'sdu-4703030', 'sds-4700001']);
  assert.deepStrictEqual(r.notes, ['note.no-city']);
});

test('CT: the county (H4|N, dropped by FUNCSTAT; a planning region by the state rule) -> no-county; the town shows', () => {
  // county-09003 Hartford County H4|N is a raw 2020 row; the planning region's FUNCSTAT is not verified, so it is
  // given A here to prove the state rule hides it whatever its code
  const r0 = govsOf(one(unit('county', '09003', 'Hartford County', 'N', 'H4'),
    unit('cousub', '0900382660', 'West Hartford town', 'A', 'T1')).units);
  assert.deepStrictEqual(ids(r0), ['cousub-0900382660']);
  assert.deepStrictEqual(r0.notes, ['note.no-city', 'note.no-county']);
  const r = govsOf(one(unit('county', '09110', 'Capitol Planning Region', 'A', 'H4'),
    unit('cousub', '0911082660', 'West Hartford town', 'A', 'T1'),
    unit('sdu', '0904950', 'West Hartford School District', 'E')).units);
  assert.deepStrictEqual(ids(r), ['cousub-0911082660', 'sdu-0904950']);
  assert.strictEqual(r.govs[0].slot, 'cousub');
  assert.strictEqual(r.govs[0].status, 'not-covered-yet');
  assert.deepStrictEqual(r.notes, ['note.no-city', 'note.no-county']);
});

test('MA: Suffolk (H4|N, also hidden by id) and Nantucket (H4|N, not flagged) -> no-county either way', () => {
  const r = govsOf(one(unit('place', '2507000', 'Boston city', 'A', 'C5'), unit('county', '25025', 'Suffolk County', 'N', 'H4'),
    unit('cousub', '2502507000', 'Boston city', 'A', 'C5')).units);
  assert.deepStrictEqual(ids(r), ['place-2507000']);                 // the C5 cousub copy of Boston goes (step 5)
  assert.deepStrictEqual(r.notes, ['note.no-county']);
  const r2 = govsOf(one(unit('county', '25019', 'Nantucket County', 'N', 'H4'),
    unit('cousub', '2501943790', 'Nantucket town', 'A', 'T1')).units);
  assert.deepStrictEqual(ids(r2), ['cousub-2501943790']);
  assert.deepStrictEqual(r2.notes, ['note.no-city', 'note.no-county']);
  // a statistical county equivalent (FUNCSTAT S) is dropped by step 1: "no county" too
  const r3 = govsOf(one(unit('place', '4799003', 'Somewhere city', 'A', 'C1'), unit('county', '02999', 'Census Area', 'S', 'H5')).units);
  assert.deepStrictEqual(r3.notes, ['note.no-county']);
});

test('coextensive town and city: COUSUBCC T5 (not the name) makes one row', () => {
  const r = govsOf(one(unit('place', '0937000', 'Hartford city', 'A', 'C5'),
    unit('county', '09110', 'Capitol Planning Region', 'A', 'H4'),
    unit('cousub', '0900337070', 'Hartford town', 'A', 'T5')).units);
  assert.deepStrictEqual(ids(r), ['place-0937000']);
  // same name but T1 (not coextensive): both governments stay
  const r2 = govsOf(one(unit('place', '3651000', 'Newburgh city', 'A', 'C1'),
    unit('cousub', '3607150909', 'Newburgh city', 'A', 'T1')).units);
  assert.deepStrictEqual(ids(r2), ['place-3651000', 'cousub-3607150909']);
  // T5 with no place kept: the town is the government and stays
  const r3 = govsOf(one(unit('place', '3699999', 'Inactive village', 'I', 'C9'),
    unit('cousub', '3607150910', 'Some town', 'A', 'T5')).units);
  assert.deepStrictEqual(ids(r3), ['cousub-3607150910']);
});

test('independent city (Richmond, VA; Baltimore, MD): one row, note independent-city, no no-county', () => {
  // raw 2020 rows: the place is C7|A, the county-equivalent copy C7|F (dropped by step 1 and hidden by id; its line rides)
  const r = govsOf(one(unit('place', '5167000', 'Richmond city', 'A', 'C7'),
    unit('county', '51760', 'Richmond city', 'F', 'C7')).units);
  assert.deepStrictEqual(ids(r), ['place-5167000']);
  assert.deepStrictEqual(r.notes, ['note.independent-city']);
  const b = govsOf(one(unit('place', '2404000', 'Baltimore city', 'A', 'C7'),
    unit('county', '24510', 'Baltimore city', 'F', 'C7')).units);
  assert.deepStrictEqual(ids(b), ['place-2404000']);
  assert.deepStrictEqual(b.notes, ['note.independent-city']);
  // a cousub copy of the city (C7 on the cousub layer) is the same area as the place: no third row
  const c = govsOf(one(unit('place', '5167000', 'Richmond city', 'A', 'C7'),
    unit('cousub', '5176091960', 'Richmond city', 'A', 'C7')).units);
  assert.deepStrictEqual(ids(c), ['place-5167000']);
  assert.strictEqual(N.label(PAGEDIR, 'note.independent-city'), 'This city is not part of any county.');
});

test('consolidated city-county (Nashville): Metro kept by show whatever its FUNCSTAT, note consolidated, no no-city', () => {
  // raw 2020 rows: the balance place is C8|F, Davidson County H6|C
  const r = govsOf(one(unit('place', '4752006', 'Nashville-Davidson metropolitan government (balance)', 'F', 'C8'),
    unit('county', '47037', 'Davidson County', 'C', 'H6'), unit('cousub', '4703790001', 'District 1', 'N', 'Z1'),
    unit('sdu', '4702940', 'Metropolitan Nashville Public Schools', 'E')).units);
  assert.deepStrictEqual(ids(r), ['county-47037', 'sdu-4702940']);
  assert.deepStrictEqual(r.notes, ['note.consolidated']);
  // Belle Meade, its own city inside Metro: Belle Meade and Metro, no line
  const bm = govsOf(one(unit('place', '4704760', 'Belle Meade city', 'A', 'C1'),
    unit('county', '47037', 'Davidson County', 'C', 'H6')).units);
  assert.deepStrictEqual(ids(bm), ['place-4704760', 'county-47037']);
  assert.deepStrictEqual(bm.notes, []);
});

test('school district "not defined" (GEOID ending 99999) is dropped, in each school layer', () => {
  const r = govsOf(one(unit('place', '4715160', 'Clarksville city', 'A', 'C1'),
    unit('sdu', '4799999', 'School District Not Defined', 'E'), unit('sds', '4799999', 'School District Not Defined', 'A'),
    unit('sde', '4799999', 'School District Not Defined', 'E'), unit('sde', '4700099', 'Real elementary', 'E')).units);
  assert.deepStrictEqual(ids(r), ['place-4715160', 'sde-4700099']);
});

test('alias to a covered body: the card is the covered id, with its status; a direct copy keeps its own name', () => {
  const pd = copyPd();
  pd.alias = { 'place-4799990': 'place-4715160' };
  const r = govsOf(one(unit('place', '4799990', 'Old Clarksville', 'A', 'C1')).units, pd);
  assert.deepStrictEqual(ids(r), ['place-4715160']);
  assert.strictEqual(r.govs[0].status, 'covered');
  assert.strictEqual(r.govs[0].name, 'Old Clarksville');
  const r2 = govsOf(one(unit('place', '4799990', 'Old Clarksville', 'A', 'C1'),
    unit('place', '4715160', 'Clarksville city', 'A', 'C1')).units, pd);
  assert.deepStrictEqual(ids(r2), ['place-4715160']);
  assert.strictEqual(r2.govs[0].name, 'Clarksville city');
});

test('nothing listable: govs empty (RI county hidden by rule, cousub nonfunctioning)', () => {
  const r = govsOf(one(unit('county', '44007', 'Providence County', 'N', 'H4'),
    unit('cousub', '4400759000', 'Providence city', 'N', 'C5')).units);
  assert.deepStrictEqual(r.govs, []);
  assert.deepStrictEqual(r.notes, ['note.no-city', 'note.no-county']);
  assert.deepStrictEqual(plain(govsOf([])), { govs: [], notes: ['note.no-city'] });
});

test('order is place, county, cousub, sdu, sds, sde whatever the answer order; one card per id', () => {
  const r = govsOf([
    { id: 'sde-3600003', layer: 'sde', name: 'E', funcstat: 'E', state: '36', cc: '' },
    { id: 'cousub-3607150911', layer: 'cousub', name: 'T', funcstat: 'A', state: '36', cc: 'T1' },
    { id: 'sds-3600002', layer: 'sds', name: 'S', funcstat: 'E', state: '36', cc: '' },
    { id: 'county-36071', layer: 'county', name: 'C', funcstat: 'A', state: '36', cc: 'H1' },
    { id: 'sdu-3600001', layer: 'sdu', name: 'U', funcstat: 'E', state: '36', cc: '' },
    { id: 'place-3651000', layer: 'place', name: 'P', funcstat: 'A', state: '36', cc: 'C1' },
    { id: 'place-3651000', layer: 'place', name: 'P again', funcstat: 'A', state: '36', cc: 'C1' },
  ]);
  assert.deepStrictEqual(r.govs.map((g) => g.slot), ['place', 'county', 'cousub', 'sdu', 'sds', 'sde']);
  assert.strictEqual(r.govs[0].name, 'P');
});

test('a pagedir that is not one (wrong schema, null) lists every kept unit as not covered yet, no flags', () => {
  for (const pd of [null, {}, { schema: 'daylight-pagedir/2', govs: PAGEDIR.govs }]) {
    const r = N.governments(N.classify(PUBLIC_SQ).units, pd);
    assert.deepStrictEqual(r.govs.map((g) => [g.id, g.status]), [['place-4715160', 'not-covered-yet'],
      ['county-47125', 'not-covered-yet'], ['sdu-4703030', 'not-covered-yet']]);
  }
  assert.strictEqual(N.indexPagedir({ schema: 'x' }), null);
});

test('directory fields are checked before they reach a card (paths, URLs, dates, status)', () => {
  const pd = copyPd();
  pd.govs['place-4715160'] = { board: 'B‮', status: 'covered', page: '../evil.html', full: 'javascript:alert(1)', stale: 'no' };
  pd.govs['county-47125'] = { board: 'C', status: 'cant-cover', reason: 'Bad Reason!', checked: 'yesterday',
    reason_url: 'http://insecure.example/', official_url: 'javascript:alert(1)' };
  pd.govs['sdu-4703030'] = { board: 'S', status: 'open-now' };
  const r = govsOf(N.classify(PUBLIC_SQ).units, pd);
  assert.deepStrictEqual(plain(r.govs), [
    { id: 'place-4715160', name: 'Clarksville city', slot: 'place', status: 'covered', board: 'B', stale: true },
    { id: 'county-47125', name: 'Montgomery County', slot: 'county', status: 'cant-cover', board: 'C' },
    { id: 'sdu-4703030', name: 'Clarksville-Montgomery County School System', slot: 'sdu', status: 'not-covered-yet' },
  ]);
});

// --- hardening (finding 9, national/postmessage-hardening) -------------------------------------------------------
test('GEOID ^\\d{5,10}$ with the layer length and a matching ^\\d{2}$ state, else the unit is dropped', () => {
  const bad = [['place', { GEOID: '47151600', STATE: '47' }], ['place', { GEOID: '471516', STATE: '47' }],
    ['place', { GEOID: ' 4715160', STATE: '47' }], ['place', { GEOID: '4715160\n', STATE: '47' }],
    ['place', { GEOID: '47a5160', STATE: '47' }], ['place', { GEOID: 4715160, STATE: '47' }],
    ['place', { GEOID: '4715160', STATE: '48' }], ['place', { GEOID: '4715160', STATE: '4' }],
    ['place', { GEOID: '4715160' }], ['county', { GEOID: '4712', STATE: '47' }],
    ['cousub', { GEOID: '47125908861', STATE: '47' }], ['sdu', { GEOID: '__proto__', STATE: '47' }],
    ['county', { GEOID: 'constructor', STATE: '47' }], ['place', { GEOID: '4715160', STATE: '47', NAME: '' }]];
  for (const [layer, u] of bad) {
    const m = { matchedAddress: 'X', geographies: { [LAYER[layer]]: [Object.assign({ NAME: 'N', FUNCSTAT: 'A' }, u)] } };
    assert.deepStrictEqual(plain(N.classify(answer(m)).units), [], JSON.stringify(u));
  }
});

test('ids __proto__ and constructor find nothing: units, directory, alias, flags and labels', () => {
  const before = Object.keys(Object.prototype).length;
  const r = N.governments([
    { id: '__proto__', layer: 'place', name: 'x', funcstat: 'A', state: '47', cc: '' },
    { id: 'constructor', layer: 'county', name: 'y', funcstat: 'A', state: '47', cc: '' },
    { id: 'place-constructor', layer: 'place', name: 'z', funcstat: 'A', state: '47', cc: '' },
  ], PAGEDIR);
  assert.deepStrictEqual(r.govs, []);
  const pd = JSON.parse('{"schema":"daylight-pagedir/1","govs":{"__proto__":{"status":"covered"},' +
    '"constructor":{"status":"covered"},"place-4715160":{"status":"covered","board":"B","page":"digest/tn/x.html"}},' +
    '"alias":{"__proto__":"place-4715160","constructor":"place-4715160"},"lines":{"__proto__":"consolidated"},' +
    '"labels":{"__proto__":"x","constructor":"y","note.no-city":"No city."},"hide":["__proto__"],"show":["constructor"]}');
  const idx = N.indexPagedir(pd);
  assert.deepStrictEqual([...idx.govs.keys()], ['place-4715160']);
  assert.strictEqual(idx.alias.size, 0);
  assert.strictEqual(idx.lines.size, 0);
  assert.strictEqual(idx.hide.size + idx.show.size, 0);
  assert.strictEqual(N.label(pd, '__proto__'), '');
  assert.strictEqual(N.label(pd, 'constructor'), '');
  assert.strictEqual(N.label(pd, 'toString'), '');
  assert.strictEqual(N.label(pd, 'note.no-city'), 'No city.');
  // a plain-object lookup would find Object.prototype.constructor for a missing key; the index does not
  const r2 = N.governments([{ id: 'county-47999', layer: 'county', name: 'Q', funcstat: 'A', state: '47', cc: '' }], pd);
  assert.strictEqual(r2.govs[0].status, 'not-covered-yet');
  assert.strictEqual(Object.keys(Object.prototype).length, before);
  assert.strictEqual(({}).status, undefined);
});

test('the page directory arrives through |tojson (embed_json) and parses back unchanged', () => {
  assert.ok(!/[<>&']/.test(PAGEDIR_TEXT), 'embed_json escapes < > & and quote');
  assert.strictEqual(PAGEDIR.schema, 'daylight-pagedir/1');
  assert.strictEqual(PAGEDIR.lines['place-4752006'], 'consolidated');
  assert.strictEqual(N.indexPagedir(PAGEDIR).hide.has('county-51760'), true);
});

test('source: text only, no history, location or title writes, no eval or HTML sinks', () => {
  const code = SRC.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
  for (const re of [/innerHTML/, /outerHTML/, /insertAdjacentHTML/, /document\.write/, /\beval\s*\(/, /\bFunction\s*\(/,
    /\bhistory\b/, /\blocation\b/, /document\.title/, /\.srcdoc\b/, /setTimeout\s*\(\s*["']/]) {
    assert.ok(!re.test(code), 'national.js must not use ' + re);
  }
});

// --- device list (3.8), with a fake storage ----------------------------------------------------------------------
class FakeStorage {
  constructor(init, o) { this.m = new Map(Object.entries(init || {})); this.o = o || {}; this.writes = []; }
  getItem(k) { if (this.o.get) { throw new Error('blocked'); } return this.m.has(k) ? this.m.get(k) : null; }
  setItem(k, v) { if (this.o.set) { throw new Error('QuotaExceededError'); } this.writes.push([k, v]); this.m.set(k, String(v)); }
  removeItem(k) { if (this.o.remove && this.o.remove(k)) { throw new Error('blocked'); } this.m.delete(k); }
}
const LIST = 'daylight.us.list', REQ = 'daylight.us.requested', CNT = 'daylight.us.counted';

test('saveList keeps ids and Census names only (never the address or matched line) and loadList reads them back', () => {
  const s = new FakeStorage();
  const r = govsOf(N.classify(PUBLIC_SQ).units);
  const withExtra = r.govs.map((g) => Object.assign({ address: '1 Public Sq', matched: '1 PUBLIC SQ' }, g));
  assert.strictEqual(N.saveList(s, withExtra), true);
  assert.strictEqual(s.m.get(LIST), '{"v":1,"govs":[{"id":"place-4715160","name":"Clarksville city"},' +
    '{"id":"county-47125","name":"Montgomery County"},{"id":"sdu-4703030",' +
    '"name":"Clarksville-Montgomery County School System"}]}');
  assert.ok(!/public sq/i.test(s.m.get(LIST)));
  assert.deepStrictEqual(plain(N.loadList(s)), [{ id: 'place-4715160', name: 'Clarksville city' },
    { id: 'county-47125', name: 'Montgomery County' }, { id: 'sdu-4703030', name: 'Clarksville-Montgomery County School System' }]);
  // a new lookup replaces the list
  N.saveList(s, [{ id: 'place-0937000', name: 'Hartford city' }]);
  assert.deepStrictEqual(plain(N.loadList(s)), [{ id: 'place-0937000', name: 'Hartford city' }]);
});

test('loadList drops bad entries and refuses bad or oversized stored values', () => {
  const good = { id: 'place-4715160', name: 'Clarksville city' };
  const entries = [good, { id: 'place-4715160', name: 'dup' }, { id: 'town-1', name: 'x' }, { id: 'place-1', name: 'x' },
    { id: 'place-4715161', name: '' }, { id: 'place-4715162', name: 'n'.repeat(121) },
    { id: 'place-4715163', name: 'bad‮' }, { id: 'place-4715164', name: 5 }, { id: 'place-4715165' }, null, 'x',
    { id: '__proto__', name: 'p' }, { id: 'county-47125', name: 'n'.repeat(120) }];
  const s = new FakeStorage({ [LIST]: JSON.stringify({ v: 1, govs: entries }) });
  assert.deepStrictEqual(N.loadList(s).map((g) => g.id), ['place-4715160', 'county-47125']);
  for (const raw of ['not json', '{"v":2,"govs":[]}', '{"v":1,"govs":{}}', '[]', 'null', '"x"', '1',
    JSON.stringify({ v: 1, govs: [good], pad: 'x'.repeat(9000) })]) {
    assert.deepStrictEqual(N.loadList(new FakeStorage({ [LIST]: raw })), [], raw.slice(0, 40));
  }
  assert.deepStrictEqual(N.loadList(new FakeStorage()), []);
  const many = Array.from({ length: 30 }, (_, i) => ({ id: 'place-47' + String(10000 + i), name: 'P' + i }));
  assert.strictEqual(N.loadList(new FakeStorage({ [LIST]: JSON.stringify({ v: 1, govs: many }) })).length, 20);
  const s2 = new FakeStorage();
  N.saveList(s2, many);
  assert.strictEqual(JSON.parse(s2.m.get(LIST)).govs.length, 20);
});

test('a storage that throws never breaks the page: loads are empty, writes say false', () => {
  const s = new FakeStorage({ [LIST]: JSON.stringify({ v: 1, govs: [{ id: 'place-4715160', name: 'C' }] }) },
    { get: true, set: true, remove: () => true });
  assert.deepStrictEqual(N.loadList(s), []);
  assert.deepStrictEqual(N.loadRequested(s), []);
  assert.strictEqual(N.saveList(s, [{ id: 'place-4715160', name: 'C' }]), false);
  assert.strictEqual(N.markRequested(s, ['sdu-4703030']), false);
  assert.strictEqual(N.markCounted(s, 'sdu-4703030'), false);
  assert.strictEqual(N.forget(s), false);
  for (const st of [null, undefined, {}]) {
    assert.deepStrictEqual(N.loadList(st), []);
    assert.strictEqual(N.saveList(st, []), false);
    assert.strictEqual(N.forget(st), false);
  }
  const win = {}; Object.defineProperty(win, 'localStorage', { get() { throw new Error('SecurityError'); } });
  assert.strictEqual(N.storageOf(win), null);
  assert.strictEqual(N.storageOf({}), null);
  const fs2 = new FakeStorage();
  assert.strictEqual(N.storageOf({ localStorage: fs2 }), fs2);
});

test('forget removes all three keys and nothing else; it tries every key even when one throws', () => {
  const s = new FakeStorage({ [LIST]: '{}', [REQ]: '{}', [CNT]: '{}', 'cr.seats': 'keep', 'daylight.other': 'keep' });
  assert.strictEqual(N.forget(s), true);
  assert.deepStrictEqual([...s.m.keys()], ['cr.seats', 'daylight.other']);
  const s2 = new FakeStorage({ [LIST]: '{}', [REQ]: '{}', [CNT]: '{}' }, { remove: (k) => k === LIST });
  assert.strictEqual(N.forget(s2), false);
  assert.deepStrictEqual([...s2.m.keys()], [LIST]);
});

test('markRequested and markCounted add valid ids once, keep the old ones, and drop bad stored ids', () => {
  const s = new FakeStorage({ [REQ]: JSON.stringify({ v: 1, ids: ['sdu-4703030', 'bad id', 7, 'sdu-4703030', '__proto__'] }) });
  assert.deepStrictEqual(N.loadRequested(s), ['sdu-4703030']);
  assert.strictEqual(N.markRequested(s, ['place-4715160', 'sdu-4703030', 'nope', null]), true);
  assert.strictEqual(s.m.get(REQ), '{"v":1,"ids":["sdu-4703030","place-4715160"]}');
  assert.strictEqual(N.markCounted(s, 'county-47125'), true);
  assert.strictEqual(N.markCounted(s, 'county-47125'), true);
  assert.deepStrictEqual(N.loadCounted(s), ['county-47125']);
  assert.strictEqual(s.m.get(CNT), '{"v":1,"ids":["county-47125"]}');
  for (const raw of ['x', '{"v":2,"ids":["sdu-4703030"]}', '{"v":1,"ids":"sdu-4703030"}',
    JSON.stringify({ v: 1, ids: ['sdu-4703030'], pad: 'x'.repeat(9000) })]) {
    assert.deepStrictEqual(N.loadRequested(new FakeStorage({ [REQ]: raw })), []);
  }
  const many = Array.from({ length: 250 }, (_, i) => 'place-47' + String(10000 + i));
  const s3 = new FakeStorage();
  N.markRequested(s3, many);
  assert.strictEqual(N.loadRequested(s3).length, 200);
  assert.strictEqual(N.loadRequested(s3)[199], many[249]);
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
