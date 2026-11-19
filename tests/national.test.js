// Node tests for site/static/national.js, the pure part of the Daylight Digest lookup (daylight-national F1, F5).
// Usage: node tests/national.test.js   (also run by tests/test_national_js.py). No browser, no network: the Census
// answers are synthetic, or tests/fixtures/national/census-1-public-sq.json, which is a RECONSTRUCTION of the 1 Public
// Sq answer from the fields docs/platform-facts.md "Census geocoder" records (a relayed reading, not raw bytes; the
// layers the lookup ignores carry made-up fields). Re-record it from a browser before R1 (national.js goes live), and the page directory is the real one, built from config/national/ by
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
  const r = one(unit('place', '4715160', 'Clark\u202Esville\u0000 city\n', 'A', 'C1'),
    unit('county', '47125', 'x'.repeat(500), 'A', 'H1'));
  assert.strictEqual(r.units[0].name, 'Clarksville city');
  const r3 = one(unit('place', '4715160', '\u061CClarks\u200Bville\u00AD\uFEFF city\u2069', 'A', 'C1'));
  assert.strictEqual(r3.units[0].name, 'Clarksville city');
  const r4 = one(unit('place', '4715160', 'Caf\u00E9 \uD83C\uDF33 town\uD800', 'A', 'C1'));
  assert.strictEqual(r4.units[0].name, 'Caf\u00E9 \uD83C\uDF33 town');      // a real pair stays, a lone half goes
  assert.strictEqual(r.units[1].name.length, 120);
  const r2 = N.classify(answer(match('1 MAIN\u2066 ST' + 'y'.repeat(400))));
  assert.strictEqual(r2.matched, ('1 MAIN ST' + 'y'.repeat(400)).replace('MAIN ST', 'MAIN  ST').replace(/\s+/g, ' ').slice(0, 200));
  assert.ok(!/[\u2066\u0000]/.test(r2.matched));
});

// --- governments: the done-when cases (synthetic) ----------------------------------------------------------------
test('unincorporated: no place -> note no-city; county and school district kept', () => {
  const r = govsOf(one(unit('county', '47125', 'Montgomery County', 'A', 'H1'),
    unit('cousub', '4712590886', 'District 5', 'N', 'Z1'),
    unit('sdu', '4703030', 'Clarksville-Montgomery County School System', 'E')).units);
  assert.deepStrictEqual(ids(r), ['county-47125', 'sdu-4703030']);
  assert.deepStrictEqual(r.notes, ['note.no-city']);
});

test('FUNCSTAT: N subdivision dropped; place/county/cousub keep A or B, school districts A or E', () => {
  const r = govsOf(one(unit('place', '4799002', 'Place S', 'S', 'C1'), unit('place', '4799004', 'Place C', 'C', 'C1'),
    unit('county', '47125', 'Montgomery County', 'A', 'H1'), unit('cousub', '4712590886', 'District 5', 'N', 'Z1'),
    unit('cousub', '4712590887', 'District 6', 'E', 'T1'), unit('sdu', '4703030', 'CMCSS', 'E'),
    unit('sds', '4700001', 'Sec A', 'A'), unit('sde', '4700002', 'Elem F', 'F'), unit('sde', '4700003', 'Elem none', '')).units);
  assert.deepStrictEqual(ids(r), ['county-47125', 'sds-4700001', 'sdu-4703030']);
  assert.deepStrictEqual(r.notes, ['note.no-city']);
});

test('FUNCSTAT B (partially consolidated, own officials) is kept; C (consolidated, one set of officials) is not', () => {
  // B: a city partly consolidated with its county but with its own officials, so its own card; C: dropped, shown
  // through the other layer (or gov-flags `show`, as Davidson County H6|C is)
  const b = govsOf(one(unit('place', '1349999', 'Partly consolidated city', 'B', 'C1'),
    unit('county', '13999', 'Its County', 'A', 'H1')).units);
  assert.deepStrictEqual(ids(b), ['place-1349999', 'county-13999']);
  assert.deepStrictEqual(b.notes, []);
  const c = govsOf(one(unit('place', '2149999', 'Consolidated city', 'A', 'C1'),
    unit('county', '21999', 'Its County', 'C', 'H6')).units);
  assert.deepStrictEqual(ids(c), ['place-2149999']);
  assert.deepStrictEqual(c.notes, ['note.no-county']);
  const cc = govsOf(one(unit('place', '2149998', 'Consolidated city (C)', 'C', 'C3'),
    unit('county', '21998', 'Its County', 'A', 'H6')).units);
  assert.deepStrictEqual(ids(cc), ['county-21998']);
  assert.deepStrictEqual(cc.notes, ['note.no-city']);
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

test('order is place, county, cousub, then elementary, secondary, unified (UX) whatever the answer order', () => {
  const r = govsOf([
    { id: 'sde-3600003', layer: 'sde', name: 'E', funcstat: 'E', state: '36', cc: '' },
    { id: 'cousub-3607150911', layer: 'cousub', name: 'T', funcstat: 'A', state: '36', cc: 'T1' },
    { id: 'sds-3600002', layer: 'sds', name: 'S', funcstat: 'E', state: '36', cc: '' },
    { id: 'county-36071', layer: 'county', name: 'C', funcstat: 'A', state: '36', cc: 'H1' },
    { id: 'sdu-3600001', layer: 'sdu', name: 'U', funcstat: 'E', state: '36', cc: '' },
    { id: 'place-3651000', layer: 'place', name: 'P', funcstat: 'A', state: '36', cc: 'C1' },
    { id: 'place-3651000', layer: 'place', name: 'P again', funcstat: 'A', state: '36', cc: 'C1' },
  ]);
  assert.deepStrictEqual(r.govs.map((g) => g.slot), ['place', 'county', 'cousub', 'sde', 'sds', 'sdu']);
  assert.strictEqual(r.govs[0].name, 'P');
});

test('a show: true state rule fails closed: it keeps no N, F or S unit (only an id-level show brings one back)', () => {
  const pd = copyPd();
  pd.rules = pd.rules.concat([{ state: '36', layer: 'cousub', show: true }, { state: '36', layer: 'place', show: true }]);
  const r = govsOf([
    { id: 'place-3651000', layer: 'place', name: 'P', funcstat: 'A', state: '36', cc: 'C1' },
    { id: 'place-3699001', layer: 'place', name: 'CDP-like', funcstat: 'S', state: '36', cc: 'U1' },
    { id: 'cousub-3607150911', layer: 'cousub', name: 'Town', funcstat: 'A', state: '36', cc: 'T1' },
    { id: 'cousub-3607150912', layer: 'cousub', name: 'Nonfunctioning', funcstat: 'N', state: '36', cc: 'Z1' },
    { id: 'cousub-3607150913', layer: 'cousub', name: 'Fictitious', funcstat: 'F', state: '36', cc: 'Z9' },
  ], pd);
  assert.deepStrictEqual(ids(r), ['place-3651000', 'cousub-3607150911']);
  pd.show = ['cousub-3607150912'];
  const back = govsOf([{ id: 'cousub-3607150912', layer: 'cousub', name: 'Nonfunctioning', funcstat: 'N', state: '36',
    cc: 'Z1' }], pd);
  assert.deepStrictEqual(ids(back), ['cousub-3607150912']);
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
  pd.govs['place-4715160'] = { board: 'B\u202E', status: 'covered', page: '../evil.html', full: 'javascript:alert(1)', stale: 'no' };
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
    { id: 'place-4715163', name: 'bad\u202E' }, { id: 'place-4715164', name: 5 }, { id: 'place-4715165' }, null, 'x',
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

// --- geo frame protocol, parent side (F5; 4.0; finding 1, national/csp-jsonp-gadget) ------------------------------
const vm = require('vm');
const FRAME_SRC = fs.readFileSync(path.join(ROOT, 'site', 'templates', '_geo_frame.js'), 'utf8');

test('frameMessage hears only the frame window, origin "null", a string, at most MAX_ANSWER, valid JSON', () => {
  const fw = { name: 'frame' }, other = { name: 'other' };
  const ev = (data, o) => Object.assign({ source: fw, origin: 'null', data }, o || {});
  const ans = JSON.stringify(PUBLIC_SQ);
  assert.deepStrictEqual(plain(N.frameMessage(ev(ans), fw)), { type: 'answer', data: PUBLIC_SQ });
  for (const w of ['ready', 'blocked', 'loaded']) {
    assert.deepStrictEqual(plain(N.frameMessage(ev(JSON.stringify(w)), fw)), { type: w });
  }
  // ignored: another window, another origin, an object, bad JSON, JSON that is no word and no object
  assert.strictEqual(N.frameMessage(ev(ans, { source: other }), fw), null);
  assert.strictEqual(N.frameMessage(ev(ans, { source: null }), fw), null);
  assert.strictEqual(N.frameMessage(ev(ans), null), null);
  for (const origin of ['https://evil.example', 'https://gn0sh.github.io', '', undefined, null]) {
    assert.strictEqual(N.frameMessage(ev(ans, { origin }), fw), null, String(origin));
  }
  for (const data of [PUBLIC_SQ, { cr: 'answer', json: ans }, ['x'], 5, null, undefined, true]) {
    assert.strictEqual(N.frameMessage(ev(data), fw), null, JSON.stringify(data));
  }
  for (const data of ['', 'ready', '{"result":', '{bad}', 'undefined', '5', '[1]', 'null', '"go"', '"__proto__"']) {
    assert.strictEqual(N.frameMessage(ev(data), fw), null, data);
  }
  assert.strictEqual(N.frameMessage(null, fw), null);
  // oversize: not parsed; the not-found tips, not "Census down"
  const big = '{"result":{"addressMatches":[]},"pad":"' + 'x'.repeat(N.MAX_ANSWER) + '"}';
  assert.deepStrictEqual(plain(N.frameMessage(ev(big), fw)), { type: 'too-big' });
  assert.strictEqual(N.frameMessage(ev(big, { source: other }), fw), null);
  const edge = '"' + 'y'.repeat(N.MAX_ANSWER - 2) + '"';
  assert.strictEqual(edge.length, N.MAX_ANSWER);
  assert.strictEqual(N.frameMessage(ev(edge), fw), null);          // at the cap it is parsed (then not a word)
  assert.deepStrictEqual(plain(N.resultOf({ type: 'too-big' })), { kind: 'nomatch', many: true });
  assert.deepStrictEqual(plain(N.resultOf({ type: 'blocked' })), { kind: 'error', blocked: true });
  assert.deepStrictEqual(plain(N.resultOf({ type: 'loaded' })), { kind: 'error' });
  assert.strictEqual(N.resultOf({ type: 'answer', data: PUBLIC_SQ }).kind, 'one');
});

// A fake page: window listeners, a body, iframes whose contentWindow records what the parent posts, fake timers.
function fakePage() {
  const listeners = new Set(), timers = [];
  const win = {
    addEventListener(t, fn) { assert.strictEqual(t, 'message'); listeners.add(fn); },
    removeEventListener(t, fn) { assert.strictEqual(t, 'message'); listeners.delete(fn); },
  };
  const body = { children: [],
    appendChild(el) { el.parentNode = body; body.children.push(el); return el; },
    removeChild(el) { body.children = body.children.filter((c) => c !== el); el.parentNode = null; return el; } };
  const document = { body, createElement(tag) {
    assert.strictEqual(tag, 'iframe');
    const posted = [];
    return { tag, attrs: {}, hidden: false, parentNode: null, posted,
      setAttribute(k, v) { this.attrs[k] = String(v); },
      contentWindow: { postMessage: (m, t) => posted.push([m, t]) } };
  } };
  const env = { document, window: win,
    setTimeout(fn, ms) { const t = { fn, ms, cleared: false }; timers.push(t); return t; },
    clearTimeout(t) { if (t) { t.cleared = true; } } };
  const fire = (frame, data, o) => [...listeners].forEach((fn) => fn(Object.assign(
    { source: frame.contentWindow, origin: 'null', data }, o || {})));
  return { env, body, listeners, timers, fire };
}

test('lookup: a sandboxed frame with no address in its URL; the address goes by postMessage only after "ready"', () => {
  const p = fakePage(), got = [];
  N.lookup(p.env, '  1 Public Sq,\n Clarksville,   TN ', (r) => got.push(r));
  assert.strictEqual(p.body.children.length, 1);
  const fr = p.body.children[0];
  assert.deepStrictEqual(fr.attrs, { sandbox: 'allow-scripts', referrerpolicy: 'no-referrer',
    title: 'Census address lookup', 'aria-hidden': 'true', tabindex: '-1', src: 'geo-frame.html' });
  assert.ok(!/allow-same-origin/.test(fr.attrs.sandbox));
  assert.strictEqual(fr.hidden, true);
  assert.deepStrictEqual(fr.posted, []);                         // nothing before "ready"
  p.fire(fr, JSON.stringify(PUBLIC_SQ));                         // an answer before the address was sent: ignored
  p.fire(fr, '"ready"', { source: {} });                         // "ready" from another window: ignored
  p.fire(fr, '"ready"', { origin: 'https://evil.example' });
  assert.deepStrictEqual(fr.posted, []);
  assert.deepStrictEqual(got, []);
  p.fire(fr, '"ready"');
  assert.deepStrictEqual(plain(fr.posted), [[{ address: '1 Public Sq, Clarksville, TN' }, '*']]);
  p.fire(fr, '"ready"');                                         // a second "ready" sends nothing more
  assert.strictEqual(fr.posted.length, 1);
});

test('lookup: ignores a message from another window, an object, an oversize-from-elsewhere and bad JSON', () => {
  const p = fakePage(), got = [];
  N.lookup(p.env, '1 Public Sq, Clarksville, TN', (r) => got.push(r));
  const fr = p.body.children[0];
  p.fire(fr, '"ready"');
  p.fire(fr, JSON.stringify(PUBLIC_SQ), { source: { other: true } });
  p.fire(fr, PUBLIC_SQ);
  p.fire(fr, 'x'.repeat(N.MAX_ANSWER + 1), { source: { other: true } });
  p.fire(fr, '{"result": ');
  p.fire(fr, JSON.stringify(PUBLIC_SQ), { origin: 'https://gn0sh.github.io' });
  assert.deepStrictEqual(got, []);
  assert.strictEqual(p.body.children.length, 1);
  p.fire(fr, JSON.stringify(PUBLIC_SQ));
  assert.strictEqual(got.length, 1);
  assert.strictEqual(got[0].kind, 'one');
  assert.strictEqual(got[0].matched, '1 PUBLIC SQ, CLARKSVILLE, TN, 37040');
});

test('lookup: the answer ends it once; the frame, its listener and the timer go before done runs', () => {
  const p = fakePage(), got = [];
  N.lookup(p.env, '1 Public Sq, Clarksville, TN', (r) => {
    assert.strictEqual(p.body.children.length, 0, 'frame removed before done');
    assert.strictEqual(p.listeners.size, 0, 'listener removed before done');
    got.push(r);
  });
  const fr = p.body.children[0];
  assert.strictEqual(p.timers.length, 1);
  assert.strictEqual(p.timers[0].ms, 15000);
  assert.strictEqual(N.TIMEOUT_MS, 15000);
  p.fire(fr, '"ready"');
  p.fire(fr, JSON.stringify(PUBLIC_SQ));
  p.fire(fr, '"blocked"');
  assert.strictEqual(got.length, 1);
  assert.strictEqual(p.timers[0].cleared, true);
  assert.strictEqual(fr.parentNode, null);
});

test('lookup: no answer in 15 s -> error with timeout; the frame is removed and a late answer is not heard', () => {
  const p = fakePage(), got = [];
  N.lookup(p.env, '1 Public Sq, Clarksville, TN', (r) => got.push(r));
  const fr = p.body.children[0];
  p.fire(fr, '"ready"');
  p.timers[0].fn();
  assert.deepStrictEqual(plain(got), [{ kind: 'error', timeout: true }]);
  assert.strictEqual(p.body.children.length, 0);
  assert.strictEqual(p.listeners.size, 0);
  p.fire(fr, JSON.stringify(PUBLIC_SQ));
  p.timers[0].fn();
  assert.strictEqual(got.length, 1);
  // a frame that never says "ready" (blocked by the browser) also ends by the timeout
  const q = fakePage(), got2 = [];
  N.lookup(q.env, '1 Main St', (r) => got2.push(r));
  q.timers[0].fn();
  assert.deepStrictEqual(plain(got2), [{ kind: 'error', timeout: true }]);
  assert.deepStrictEqual(q.body.children, []);
});

test('lookup: "blocked", "loaded" and an oversize answer end it with their own results', () => {
  const cases = [['"blocked"', { kind: 'error', blocked: true }], ['"loaded"', { kind: 'error' }],
    ['{"pad":"' + 'x'.repeat(N.MAX_ANSWER) + '"}', { kind: 'nomatch', many: true }],
    [JSON.stringify({ result: { addressMatches: [] } }), { kind: 'nomatch' }]];
  for (const [data, want] of cases) {
    const p = fakePage(), got = [];
    N.lookup(p.env, '1 Main St, Town, ST', (r) => got.push(r));
    const fr = p.body.children[0];
    p.fire(fr, '"ready"');
    p.fire(fr, data);
    assert.deepStrictEqual(plain(got), [want], data.slice(0, 20));
    assert.deepStrictEqual(p.body.children, []);
  }
});

test('lookup: cancel drops the frame without an answer; an empty or over-long address sends nothing', () => {
  const p = fakePage(), got = [];
  const h = N.lookup(p.env, '1 Main St', (r) => got.push(r));
  h.cancel();
  assert.deepStrictEqual(p.body.children, []);
  assert.strictEqual(p.listeners.size, 0);
  assert.strictEqual(p.timers[0].cleared, true);
  assert.deepStrictEqual(got, []);
  for (const [a, want] of [['', 'empty'], ['   \n ', 'empty'], [null, 'empty'], ['x'.repeat(201), 'nomatch']]) {
    const q = fakePage(), g = [];
    N.lookup(q.env, a, (r) => g.push(r));
    assert.deepStrictEqual(plain(g), [{ kind: want }]);
    assert.deepStrictEqual(q.body.children, []);
    assert.strictEqual(q.timers.length, 0);
  }
  assert.strictEqual(N.cleanAddress('x'.repeat(200)).length, 200);
});

// --- the frame's own script (site/templates/_geo_frame.js) in a fake sandboxed window ---------------------------
function runFrame(o) {
  o = o || {};
  const parentPosts = [], appended = [], listeners = [], later = [];
  const parent = { postMessage: (m, t) => parentPosts.push([m, t]) };
  const win = { origin: o.origin === undefined ? 'null' : o.origin,
    addEventListener: (t, fn) => { assert.strictEqual(t, 'message'); listeners.push(fn); } };
  const document = { head: { appendChild: (el) => appended.push(el) },
    createElement: (tag) => { assert.strictEqual(tag, 'script'); return { tag }; } };
  const ctx = { window: win, self: win, parent: o.top ? win : parent, document, JSON, Array, String,
    encodeURIComponent, setTimeout: (fn) => later.push(fn) };
  vm.createContext(ctx);
  vm.runInContext(FRAME_SRC, ctx);
  const send = (data, source) => listeners.forEach((fn) => fn({ data, source: source === undefined ? parent : source,
    origin: 'https://gn0sh.github.io' }));
  return { win, parent, parentPosts, appended, send, later, listeners };
}

test('frame script does nothing unless it runs sandboxed in a frame (origin "null" and a parent that is not self)', () => {
  for (const o of [{ origin: 'https://gn0sh.github.io' }, { origin: 'https://evil.example' }, { origin: '' },
    { top: true }, { origin: 'https://gn0sh.github.io', top: true }]) {
    const f = runFrame(o);
    assert.deepStrictEqual(f.parentPosts, [], JSON.stringify(o));       // no "ready"
    assert.strictEqual(f.listeners.length, 0);                          // no message listener
    assert.strictEqual(f.win.crGeocode, undefined);                     // no callback defined
    f.send({ address: '1 Public Sq, Clarksville, TN' });
    assert.strictEqual(f.appended.length, 0);                           // no Census script loaded
  }
  const ok = runFrame();
  assert.deepStrictEqual(ok.parentPosts, [['"ready"', '*']]);
  assert.ok(/^\(function \(\) \{\s*"use strict";\s*if \(self\.origin !== "null" \|\| parent === self\) \{ return; \}/
    .test(FRAME_SRC.replace(/^\/\*[\s\S]*?\*\/\s*/, '')), 'the sandbox check is the first statement');
});

test('frame script: posts "ready", takes one {address} from the parent only, and builds jsonpUrl\'s exact URL', () => {
  for (const addr of ['1 Public Sq, Clarksville, TN', '12 O\'Brien Rd #4 & Sons, Ste "B", NY 10001',
    'a&callback=alert(1)//', 'Calle \u00D1and\u00FA 5, San Juan, PR', 'x'.repeat(200)]) {
    const f = runFrame();
    assert.deepStrictEqual(f.parentPosts, [['"ready"', '*']]);
    f.send({ address: addr }, { notParent: true });             // another window: ignored
    f.send(addr);                                               // a bare string: ignored
    assert.strictEqual(f.appended.length, 0);
    f.send({ address: addr });
    assert.strictEqual(f.appended.length, 1);
    assert.strictEqual(f.appended[0].src, N.jsonpUrl(addr), addr);
    assert.strictEqual(f.appended[0].referrerPolicy, 'no-referrer');
    f.send({ address: 'second' });                              // one lookup per frame
    assert.strictEqual(f.appended.length, 1);
  }
  const f = runFrame();
  for (const bad of [{ address: '' }, { address: 'x'.repeat(201) }, { address: 5 }, {}, null]) { f.send(bad); }
  assert.strictEqual(f.appended.length, 0);
});

test('frame script: the callback posts the answer as JSON text once; failures post "blocked" or "loaded"', () => {
  const f = runFrame();
  f.send({ address: '1 Public Sq, Clarksville, TN' });
  assert.strictEqual(typeof f.win.crGeocode, 'function');
  f.win.crGeocode(PUBLIC_SQ);
  f.appended[0].onload();
  f.later.forEach((fn) => fn());
  assert.strictEqual(f.parentPosts.length, 2);
  const [text, target] = f.parentPosts[1];
  assert.strictEqual(target, '*');
  assert.strictEqual(typeof text, 'string');
  assert.deepStrictEqual(JSON.parse(text), PUBLIC_SQ);
  const g = runFrame();
  g.send({ address: 'x' });
  g.appended[0].onerror();
  assert.deepStrictEqual(g.parentPosts.map((m) => m[0]), ['"ready"', '"blocked"']);
  const h = runFrame();
  h.send({ address: 'x' });
  h.appended[0].onload();
  h.later.forEach((fn) => fn());
  assert.deepStrictEqual(h.parentPosts.map((m) => m[0]), ['"ready"', '"loaded"']);
  const k = runFrame();                                         // a callback with no object is no answer
  k.send({ address: 'x' });
  k.win.crGeocode('"ready"');
  assert.deepStrictEqual(k.parentPosts.map((m) => m[0]), ['"ready"', '"loaded"']);
  // every message the frame posts is one the parent hears
  for (const [m] of [...f.parentPosts, ...g.parentPosts, ...h.parentPosts]) {
    assert.notStrictEqual(N.frameMessage({ source: 1, origin: 'null', data: m }, 1), null, m.slice(0, 20));
  }
});

test('parent and frame together: 1 Public Sq ends in its three cards, the frame gone', () => {
  const p = fakePage(), got = [];
  N.lookup(p.env, '1 Public Sq, Clarksville, TN', (r) => got.push(r));
  const fr = p.body.children[0];
  const f = runFrame();                                         // the frame document the iframe loaded
  fr.contentWindow.postMessage = (m) => f.send(m);              // parent -> frame (structured clone in a browser)
  f.parentPosts.forEach(([m]) => p.fire(fr, m));                // the "ready" it posted on load
  f.parent.postMessage = (m) => p.fire(fr, m);                  // frame -> parent from now on
  assert.strictEqual(f.appended.length, 1);
  assert.strictEqual(new URL(f.appended[0].src).searchParams.get('address'), '1 Public Sq, Clarksville, TN');
  f.win.crGeocode(PUBLIC_SQ);                                   // the Census JSONP runs
  assert.strictEqual(got.length, 1);
  assert.deepStrictEqual(ids(N.governments(got[0].units, PAGEDIR)), ['place-4715160', 'county-47125', 'sdu-4703030']);
  assert.deepStrictEqual(p.body.children, []);
});

test('frame script and national.js share the callback name, the Census path and the six layers', () => {
  assert.ok(FRAME_SRC.includes('var CALLBACK = "' + N.CALLBACK + '";'));
  assert.ok(FRAME_SRC.includes('var CENSUS = "' + N.CENSUS + '";'));
  for (const name of N.LAYER_NAMES) { assert.ok(FRAME_SRC.includes('"' + name + '"'), name); }
  assert.ok(!/<\//.test(FRAME_SRC) && !/<!--/.test(FRAME_SRC));
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
