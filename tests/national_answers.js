// Census answer builders for the Daylight Digest tests (daylight-national F1, F3), shared by tests/national.test.js
// (the pure lookup) and tests/national_browser.js (the browser privacy run). The builders make the geographies
// answer the Census's onelineaddress JSON(P) returns; RECORDED is the 12 answers the F3 browser test plays back:
// the reconstructed 1 Public Sq answer (tests/fixtures/national/census-1-public-sq.json; see national.test.js's
// header for what "reconstructed" means) and the synthetic done-when cases national.test.js asserts, each with the
// address a person would type. `ids` is the list national.js draws for that answer with the shipped page directory
// (national.test.js proves the rules); `pick` is set when the answer has more than one match.
const fs = require('fs');
const path = require('path');

const LAYER = { place: 'Incorporated Places', county: 'Counties', cousub: 'County Subdivisions',
  sdu: 'Unified School Districts', sds: 'Secondary School Districts', sde: 'Elementary School Districts' };
const CC = { place: 'PLACECC', county: 'COUNTYCC', cousub: 'COUSUBCC' };
/* `basename`: the unit's Census BASENAME (the greeting's name, digest-warmth section 4); left out, the unit has none,
   as an answer without the field would. */
function unit(layer, geoid, name, funcstat, cc, basename) {
  const u = { OBJECTID: 1, GEOID: geoid, NAME: name, STATE: geoid.slice(0, 2), FUNCSTAT: funcstat, MTFCC: 'G0000' };
  if (cc && CC[layer]) { u[CC[layer]] = cc; }
  if (basename !== undefined) { u.BASENAME = basename; }
  return [layer, u];
}
function match(addr, ...units) {
  const geographies = { States: [{ GEOID: '47', NAME: 'Tennessee', STATE: '47' }] };
  for (const [layer, u] of units) { (geographies[LAYER[layer]] = geographies[LAYER[layer]] || []).push(u); }
  return { matchedAddress: addr, coordinates: { x: -87, y: 36 }, geographies };
}
const answer = (...matches) => ({ result: { input: {}, addressMatches: matches } });

const PUBLIC_SQ = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'national', 'census-1-public-sq.json'), 'utf8'));

const RECORDED = [
  { name: '1 Public Sq (reconstructed recording)', typed: '1 Public Sq, Clarksville, TN 37040', answer: PUBLIC_SQ,
    ids: ['place-4715160', 'county-47125', 'sdu-4703030'] },
  { name: 'CT: planning region hidden, town shown', typed: '50 South Main Street, West Hartford, CT 06107',
    answer: answer(match('50 S MAIN ST, WEST HARTFORD, CT, 06107', unit('county', '09110', 'Capitol Planning Region', 'A', 'H4'),
      unit('cousub', '0911082660', 'West Hartford town', 'A', 'T1'),
      unit('sdu', '0904950', 'West Hartford School District', 'E'))),
    ids: ['cousub-0911082660', 'sdu-0904950'] },
  { name: 'MA Boston: Suffolk hidden, C5 cousub copy dropped', typed: '1 City Hall Square, Boston, MA 02201',
    answer: answer(match('1 CITY HALL SQ, BOSTON, MA, 02201', unit('place', '2507000', 'Boston city', 'A', 'C5'),
      unit('county', '25025', 'Suffolk County', 'N', 'H4'), unit('cousub', '2502507000', 'Boston city', 'A', 'C5'))),
    ids: ['place-2507000'] },
  { name: 'MA Nantucket: county N, town shown', typed: '16 Broad Street, Nantucket, MA 02554',
    answer: answer(match('16 BROAD ST, NANTUCKET, MA, 02554', unit('county', '25019', 'Nantucket County', 'N', 'H4'),
      unit('cousub', '2501943790', 'Nantucket town', 'A', 'T1'))),
    ids: ['cousub-2501943790'] },
  { name: 'VA independent city (Richmond)', typed: '900 East Broad Street, Richmond, VA 23219',
    answer: answer(match('900 E BROAD ST, RICHMOND, VA, 23219', unit('place', '5167000', 'Richmond city', 'A', 'C7'),
      unit('county', '51760', 'Richmond city', 'F', 'C7'))),
    ids: ['place-5167000'] },
  { name: 'Nashville (consolidated Metro)', typed: '1 Public Square, Nashville, TN 37201',
    answer: answer(match('1 PUBLIC SQ, NASHVILLE, TN, 37201',
      unit('place', '4752006', 'Nashville-Davidson metropolitan government (balance)', 'F', 'C8'),
      unit('county', '47037', 'Davidson County', 'C', 'H6'), unit('cousub', '4703790001', 'District 1', 'N', 'Z1'),
      unit('sdu', '4702940', 'Metropolitan Nashville Public Schools', 'E'))),
    ids: ['county-47037', 'sdu-4702940'] },
  { name: 'unincorporated (no place)', typed: '4000 Rossview Road, Clarksville, TN 37043',
    answer: answer(match('4000 ROSSVIEW RD, CLARKSVILLE, TN, 37043', unit('county', '47125', 'Montgomery County', 'A', 'H1'),
      unit('cousub', '4712590886', 'District 5', 'N', 'Z1'),
      unit('sdu', '4703030', 'Clarksville-Montgomery County School System', 'E'))),
    ids: ['county-47125', 'sdu-4703030'] },
  { name: 'nothing listable (RI)', typed: '25 Dorrance Street, Providence, RI 02903',
    answer: answer(match('25 DORRANCE ST, PROVIDENCE, RI, 02903', unit('county', '44007', 'Providence County', 'N', 'H4'),
      unit('cousub', '4400759000', 'Providence city', 'N', 'C5'))),
    ids: [] },
  { name: '3 matches (Springfield)', typed: '100 Main Street, Springfield',
    answer: answer(
      match('100 MAIN ST, SPRINGFIELD, IL, 62701', unit('place', '1772000', 'Springfield city', 'A', 'C1')),
      match('100 MAIN ST, SPRINGFIELD, MO, 65806', unit('place', '2970000', 'Springfield city', 'A', 'C1')),
      match('100 MAIN ST, SPRINGFIELD, OR, 97477', unit('place', '4169600', 'Springfield city', 'A', 'C1'))),
    pick: 1, ids: ['place-2970000'] },
  { name: 'no match', typed: '999 Nowhere Lane, Faketown, ZZ 99999', answer: answer(), ids: [] },
  { name: 'school district "not defined" dropped in each layer', typed: '215 Legion Street, Clarksville, TN 37040',
    answer: answer(match('215 LEGION ST, CLARKSVILLE, TN, 37040', unit('place', '4715160', 'Clarksville city', 'A', 'C1'),
      unit('sdu', '4799999', 'School District Not Defined', 'E'), unit('sds', '4799999', 'School District Not Defined', 'A'),
      unit('sde', '4799999', 'School District Not Defined', 'E'), unit('sde', '4700099', 'Real elementary', 'E'))),
    ids: ['place-4715160', 'sde-4700099'] },
  { name: 'elementary and secondary districts (no unified)', typed: '12 Orchard Road, Somewhere, TN 37000',
    answer: answer(match('12 ORCHARD RD, SOMEWHERE, TN, 37000', unit('county', '47125', 'Montgomery County', 'A', 'H1'),
      unit('sds', '4700001', 'Sec A', 'A'), unit('sde', '4700002', 'Elem F', 'F'), unit('sde', '4700003', 'Elem B', 'E'))),
    ids: ['county-47125', 'sde-4700003', 'sds-4700001'] },
];

module.exports = { LAYER, CC, unit, match, answer, PUBLIC_SQ, RECORDED };
