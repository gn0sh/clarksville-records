"""The weather in the header's sky (owner, 2026-11-23: "if it's raining in Clarksville, it would be cool if the top
of the Daylight page had rain also", then: whatever the weather is, as a small set of scenes; 2026-11-24: "up in
the top panel where the masthead is. It would incorporate the sun and moon that are already there", so the sun or
the moon that is up shows the weather itself: a cloud across it, rain falling in front of it).

static/sky.js asks the National Weather Service, from the visitor's browser, for the latest observation of one
station (config/site.yml sky_weather: KCKV, Clarksville's airport) and draws one scene from it. Held here:

- the decision: weatherScene(observation, now) -> {scene, intensity, windy} or null, one fixture per scene, the
  precedence of SCENES, and null (the plain sky) for anything that is not a fresh observation;
- the request: one per page view, no credentials and no referrer, nothing drawn on a timeout, an error status or
  an answer that is not JSON, nothing asked twice, nothing stored;
- the wiring: the config block, the address on the page, the CSP's connect-src, the site check that holds them, and
  the sentence on the About and Method pages;
- the drawing: on the sun or the moon, whichever is up (never a sky of its own), decoration only, the words'
  contrast kept, motion only where the visitor allows it.

The fixtures follow the service's documented observation schema (GeoJSON `properties`: timestamp, textDescription,
presentWeather[] with rawString / weather / intensity / modifier / inVicinity, cloudLayers[].amount, windSpeed,
windGust and visibility as {unitCode, value}). The sandbox cannot reach api.weather.gov, so none is a recording."""
# ruff: noqa: E501  (the fixture tables and the probes read better one case to a line)
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from qa import site_checks
from sitegen import config, views, weather
from test_daylight import DARK, LIGHT, _ratio

ROOT = Path(__file__).resolve().parents[1]
SKY_JS = ROOT / "site" / "static" / "sky.js"
JS = SKY_JS.read_text(encoding="utf-8")
CSS = (ROOT / "site" / "static" / "style.css").read_text(encoding="utf-8")
WX_CSS = CSS[CSS.index("/* The weather: drawn on the sun or the moon"):CSS.index(".has-sky .masthead { z-index: 1; }")]
URL = "https://api.weather.gov/stations/KCKV/observations/latest"
ORIGIN = "https://api.weather.gov"
PARTS = ["wx-veil", "wx-cloud wx-back", "wx-fall wx-a", "wx-fall wx-b", "wx-fall wx-c", "wx-cloud wx-front", "wx-flash"]
NOW = "2026-11-23T18:00:00Z"
FRESH = "2026-11-23T17:53:00+00:00"          # seven minutes before NOW
META = re.compile(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">')


def kmh(v):
    return {"unitCode": "wmoUnit:km_h-1", "value": v}


def pw(raw, weather_word, intensity=None, modifier=None, vicinity=False):
    return {"intensity": intensity, "modifier": modifier, "weather": weather_word, "rawString": raw,
            "inVicinity": vicinity}


CALM = {"windSpeed": kmh(9.4), "windGust": {"unitCode": "wmoUnit:km_h-1", "value": None},
        "visibility": {"unitCode": "wmoUnit:m", "value": 16090}}
# (name, the observation's properties, scene, intensity, windy)
SCENES = [
    ("rain", {"textDescription": "Rain", "presentWeather": [pw("RA", "rain")], "cloudLayers": [{"amount": "OVC"}]},
     "rain", "moderate", False),
    ("light drizzle", {"textDescription": "Light Drizzle", "presentWeather": [pw("-DZ", "drizzle", "light")]},
     "rain", "light", False),
    ("heavy showers", {"textDescription": "Heavy Rain Showers", "presentWeather": [pw("+SHRA", "rain", "heavy", "showers")]},
     "rain", "heavy", False),
    ("freezing rain is rain", {"textDescription": "Light Freezing Rain", "presentWeather": [pw("-FZRA", "rain", "light", "freezing")]},
     "rain", "light", False),
    ("rain by its words only", {"textDescription": "Light Rain", "presentWeather": []}, "rain", "light", False),
    ("rain with no rawString", {"presentWeather": [{"weather": "rain", "intensity": "heavy"}]}, "rain", "heavy", False),
    ("thunderstorm with rain", {"textDescription": "Thunderstorms and Rain", "presentWeather": [pw("TSRA", "rain", None, "thunderstorms")]},
     "storm", "moderate", False),
    ("thunderstorm with heavy rain, two entries", {"presentWeather": [pw("TS", "thunderstorms"), pw("+RA", "rain", "heavy")]},
     "storm", "heavy", False),
    ("dry thunderstorm", {"textDescription": "Thunderstorm", "presentWeather": [pw("TS", "thunderstorms")]},
     "storm", None, False),
    ("thunderstorm by its words only", {"textDescription": "Thunderstorms and Heavy Rain"}, "storm", "heavy", False),
    ("snow", {"textDescription": "Light Snow", "presentWeather": [pw("-SN", "snow", "light")]}, "snow", "light", False),
    ("heavy snow by its words only", {"textDescription": "Heavy Snow"}, "snow", "heavy", False),
    ("sleet is snow", {"textDescription": "Ice Pellets", "presentWeather": [pw("PL", "ice_pellets")]}, "snow", "moderate", False),
    ("rain mixed with snow is snow", {"presentWeather": [pw("-RASN", "rain", "light")]}, "snow", "light", False),
    ("snow showers by their words", {"textDescription": "Snow Showers"}, "snow", "moderate", False),
    ("fog", {"textDescription": "Fog", "presentWeather": [pw("FG", "fog")]}, "fog", None, False),
    ("mist", {"textDescription": "Fog/Mist", "presentWeather": [pw("BR", "fog_mist")]}, "fog", None, False),
    ("haze", {"textDescription": "Haze", "presentWeather": [pw("HZ", "haze")]}, "fog", None, False),
    ("low visibility with no report", {"textDescription": "Cloudy", "visibility": {"unitCode": "wmoUnit:m", "value": 1200}},
     "fog", None, False),
    ("overcast", {"textDescription": "Overcast", "cloudLayers": [{"amount": "FEW"}, {"amount": "OVC"}]}, "overcast", None, False),
    ("mostly cloudy", {"textDescription": "Mostly Cloudy", "cloudLayers": [{"amount": "BKN"}]}, "overcast", None, False),
    ("overcast by its words only", {"textDescription": "Cloudy"}, "overcast", None, False),
    ("partly cloudy", {"textDescription": "Partly Cloudy", "cloudLayers": [{"amount": "SCT"}]}, "partly", None, False),
    ("partly cloudy by its words only", {"textDescription": "Partly Cloudy"}, "partly", None, False),
    ("a few clouds is clear", {"textDescription": "Mostly Clear", "cloudLayers": [{"amount": "FEW"}]}, "clear", None, False),
    ("clear", {"textDescription": "Clear", "presentWeather": [], "cloudLayers": [{"amount": "CLR"}], **CALM},
     "clear", None, False),
    ("windy under a clear sky", {"textDescription": "Clear and Windy", "cloudLayers": [{"amount": "CLR"}], "windSpeed": kmh(35)},
     "windy", None, True),                                                       # 35 km/h is 21.7 mph
    ("gusts under a clear sky", {"cloudLayers": [{"amount": "CLR"}], "windSpeed": kmh(20), "windGust": kmh(50)},
     "windy", None, True),                                                       # gusts of 31 mph
    ("a breeze is not wind", {"cloudLayers": [{"amount": "CLR"}], "windSpeed": kmh(28), "windGust": kmh(44)},
     "clear", None, False),                                                      # 17.4 and 27.3 mph
    ("wind in metres a second", {"windSpeed": {"unitCode": "wmoUnit:m_s-1", "value": 9.5}}, "windy", None, True),
    ("wind over rain is a modifier", {"presentWeather": [pw("RA", "rain")], "windSpeed": kmh(40)}, "rain", "moderate", True),
    ("wind over cloud is a modifier", {"cloudLayers": [{"amount": "OVC"}], "windGust": kmh(60)}, "overcast", None, True),
    ("showers in the vicinity are not here", {"textDescription": "Showers in Vicinity", "presentWeather": [pw("VCSH", "rain", None, "showers", True)],
                                              "cloudLayers": [{"amount": "SCT"}]}, "partly", None, False),
    ("a thunderstorm in the vicinity is not here", {"textDescription": "Thunderstorm in Vicinity", "presentWeather": []},
     "clear", None, False),
    ("rain keeps when only the thunderstorm is in the vicinity", {"textDescription": "Light Rain and Thunderstorms in Vicinity"},
     "rain", "light", False),
    ("rain showers by the service's word", {"presentWeather": [{"weather": "rain_showers", "intensity": "light"}]},
     "rain", "light", False),
    ("blowing snow is not falling snow", {"textDescription": "Blowing Snow", "presentWeather": [pw("BLSN", "snow", None, "blowing")],
                                          "cloudLayers": [{"amount": "SCT"}]}, "partly", None, False),
    ("drifting snow is not falling snow", {"presentWeather": [pw("DRSN", "snow", None, "low_drifting")], "windSpeed": kmh(45)},
     "windy", None, True),
    ("blowing snow by its modifier only", {"presentWeather": [{"weather": "snow", "modifier": "blowing", "intensity": "heavy"}]},
     "clear", None, False),
    ("blowing snow by its words only", {"textDescription": "Blowing Snow and Breezy"}, "windy", None, True),
    ("snow falling while snow blows", {"presentWeather": [pw("-SN", "snow", "light"), pw("BLSN", "snow", None, "blowing")]},
     "snow", "light", False),
    ("visibility 0 with no fog reported is no reading", {"textDescription": "Clear", "visibility": {"unitCode": "wmoUnit:m", "value": 0}},
     "clear", None, False),
    ("visibility 0 with fog reported is fog", {"presentWeather": [pw("FG", "fog")], "visibility": {"unitCode": "wmoUnit:m", "value": 0}},
     "fog", None, False),
    ("nothing reported at all", {}, "clear", None, False),
]
# What is not a fresh observation: the plain sky (null), whatever weather it names.
RAINING = {"textDescription": "Rain", "presentWeather": [pw("RA", "rain")]}
NOT_FRESH = [
    ("ninety-one minutes old", {"properties": {**RAINING, "timestamp": "2026-11-23T16:29:00+00:00"}}),
    ("yesterday's", {"properties": {**RAINING, "timestamp": "2026-11-22T18:00:00+00:00"}}),
    ("stamped an hour ahead", {"properties": {**RAINING, "timestamp": "2026-11-23T19:00:00+00:00"}}),
    ("no timestamp", {"properties": RAINING}),
    ("a timestamp that is not a date", {"properties": {**RAINING, "timestamp": "soon"}}),
    ("a timestamp that is a number", {"properties": {**RAINING, "timestamp": 1795456380}}),
    ("no properties", {"type": "Feature"}),
    ("properties that are a string", {"properties": "Rain"}),
    ("an error document", {"title": "Not Found", "status": 404, "detail": "No observations"}),
    ("null", None), ("a string", "Rain"), ("a list", [RAINING]), ("a number", 7),
]
# Odd shapes inside a fresh observation never throw: what can be read is read.
ODD = [
    ("presentWeather is a string", {"presentWeather": "RA", "textDescription": "Rain"}, "rain"),
    ("entries that are not objects", {"presentWeather": [None, "RA", 4], "textDescription": "Light Snow"}, "snow"),
    ("a rawString that is not METAR", {"presentWeather": [{"rawString": "constructor", "weather": "__proto__"}]}, "clear"),
    ("cloudLayers of the wrong kind", {"cloudLayers": {"amount": "OVC"}, "textDescription": 12}, "clear"),
    ("an unknown cloud amount", {"cloudLayers": [{"amount": "toString"}, None]}, "clear"),
    ("wind with no number", {"windSpeed": {"unitCode": "wmoUnit:km_h-1", "value": "40"}, "windGust": "gusty"}, "clear"),
    ("wind in an unknown unit", {"windSpeed": {"unitCode": "wmoUnit:furlong", "value": 900}}, "clear"),
]


@pytest.fixture(scope="module")
def node():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    return shutil.which("node")


def run(node, probe, *args):
    res = subprocess.run([node, "-e", probe, str(SKY_JS), *args], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


SCENE_PROBE = ("const s = require(process.argv[1]); const now = Date.parse(process.argv[2]);"
               "console.log(JSON.stringify(JSON.parse(process.argv[3]).map(o => s.weatherScene(o, now))));")


def scenes(node, observations, now=NOW):
    return run(node, SCENE_PROBE, now, json.dumps(observations))


def fresh(props):
    return {"type": "Feature", "properties": {"timestamp": FRESH, **props}}


# --- the decision ----------------------------------------------------------------------------------------------

def test_each_fixture_draws_its_scene(node):
    got = scenes(node, [fresh(p) for _, p, *_ in SCENES])
    for (name, _, scene, intensity, windy), g in zip(SCENES, got):
        assert g == {"scene": scene, "intensity": intensity, "windy": windy}, (name, g)
    assert {s for _, _, s, *_ in SCENES} == {"storm", "snow", "rain", "fog", "overcast", "partly", "windy", "clear"}


def test_the_scene_table_is_one_list_in_order_of_precedence(node):
    ids = run(node, "const s = require(process.argv[1]); console.log(JSON.stringify(s.SCENES.map(x => x.id)));")
    assert ids == ["storm", "snow", "rain", "fog", "overcast", "partly", "windy", "clear"]
    # every observation below reports all of the later scenes too; the earlier one is drawn
    everything = {"cloudLayers": [{"amount": "OVC"}], "windSpeed": kmh(45), "visibility": {"unitCode": "wmoUnit:m", "value": 800}}
    stack = [("storm", [pw("TSRA", "rain", None, "thunderstorms"), pw("SN", "snow"), pw("FG", "fog")]),
             ("snow", [pw("RA", "rain"), pw("SN", "snow"), pw("BR", "fog_mist")]),
             ("rain", [pw("-RA", "rain", "light"), pw("BR", "fog_mist")]),
             ("fog", [pw("FG", "fog")])]
    got = scenes(node, [fresh({**everything, "presentWeather": entries}) for _, entries in stack]
                 + [fresh({"cloudLayers": [{"amount": "SCT"}, {"amount": "OVC"}], "windSpeed": kmh(45)}),
                    fresh({"cloudLayers": [{"amount": "SCT"}], "windSpeed": kmh(45)})])
    assert [g["scene"] for g in got] == ["storm", "snow", "rain", "fog", "overcast", "partly"]
    assert all(g["windy"] for g in got)                       # the wind stays a modifier over every one of them


def test_what_is_not_a_fresh_observation_draws_nothing(node):
    got = scenes(node, [o for _, o in NOT_FRESH])
    for (name, _), g in zip(NOT_FRESH, got):
        assert g is None, (name, g)
    # the edge: 90 minutes old is still drawn, a minute more is not; nor is anything without a number for "now"
    edge = [{"properties": {**RAINING, "timestamp": t}} for t in ("2026-11-23T16:30:00Z", "2026-11-23T16:29:59Z")]
    assert [g and g["scene"] for g in scenes(node, edge)] == ["rain", None]
    nan = run(node, "const s = require(process.argv[1]);"
                    "console.log(JSON.stringify([NaN, undefined, null, '1'].map(n => s.weatherScene(JSON.parse(process.argv[2]), n))));",
              json.dumps(fresh(RAINING)))
    assert nan == [None, None, None, None]
    assert run(node, "const s = require(process.argv[1]); console.log(JSON.stringify([s.WX_MAX_AGE, s.WX_TIMEOUT]));") \
        == [90 * 60000, 5000]


def test_odd_shapes_in_a_fresh_observation_never_throw(node):
    got = scenes(node, [fresh(p) for _, p, _ in ODD])
    for (name, _, scene), g in zip(ODD, got):
        assert g is not None and g["scene"] == scene, (name, g)


def test_only_the_weather_is_kept_and_it_draws_the_same_scene(node):
    """What the page holds of the answer: the fields the decision reads, and none of the rest."""
    full = fresh({**SCENES[0][1], **CALM, "station": "https://api.weather.gov/stations/KCKV", "stationName": "Clarksville, Outlaw Field",
                  "rawMessage": "KCKV 231753Z AUTO 18005KT 10SM RA OVC030 12/10 A2992", "temperature": {"unitCode": "wmoUnit:degC", "value": 12},
                  "icon": "https://api.weather.gov/icons/land/day/rain"})
    full["geometry"] = {"type": "Point", "coordinates": [-87.42, 36.62]}
    full["id"] = "https://api.weather.gov/stations/KCKV/observations/2026-11-23T17:53:00+00:00"
    probe = ("const s = require(process.argv[1]); const o = JSON.parse(process.argv[2]); const k = s.weatherOnly(o);"
             "console.log(JSON.stringify({kept: k, same: [o, k].map(x => s.weatherScene(x, Date.parse(process.argv[3]))),"
             " none: [null, 'x', {}, {properties: 4}].map(s.weatherOnly)}));")
    got = run(node, probe, json.dumps(full), NOW)
    assert list(got["kept"]) == ["properties"]
    assert sorted(got["kept"]["properties"]) == ["cloudLayers", "presentWeather", "textDescription", "timestamp",
                                                 "visibility", "windGust", "windSpeed"]
    assert got["same"][0] == got["same"][1] == {"scene": "rain", "intensity": "moderate", "windy": False}
    assert got["none"] == [None, None, None, None]


# --- the request (a stand-in page, fetch and clock under node) -----------------------------------------------

PAGE_PROBE = r"""
const [skyJs, caseJson] = process.argv.slice(1);
const c = JSON.parse(caseJson);
let now = Date.parse(c.now);
Date.now = () => now;
const log = { fetches: [], aborted: 0, timers: [] };
const attrs = {};
const ids = {};
log.moves = [];                                 // every time the drawing is put somewhere: where
const put = (host, name) => (el) => { el.parentNode = host; ids[el.id] = el; log.moves.push(name);
  log.layer = { id: el.id, cls: el.className, attrs: el.attrs, parts: el.kids.map(k => k.className) }; };
const header = { setAttribute: (k, v) => { attrs[k] = v; }, removeAttribute: (k) => { delete attrs[k]; },
                 getAttribute: (k) => (k in attrs ? attrs[k] : null) };
header.insertBefore = put(header, "header");
const frame = { parentNode: header, nextSibling: null };
ids["sky-moon"] = { parentNode: frame, setAttribute: () => {}, getAttribute: (k) => (k === "data-weather" ? c.url : null) };
let sunAt = c.sun || null;                      // the sun's data-at, as render() leaves it; no sun element when null
if (sunAt) {                                    // what render() writes on it is dropped: the case says whether it is up
  ids["sky-sun"] = { getAttribute: (k) => (k === "data-at" ? sunAt : null), setAttribute: () => {}, style: { setProperty() {} } };
  ids["sky-sun"].appendChild = put(ids["sky-sun"], "sun");
}
const win = {
  document: { hidden: false, getElementById: (id) => ids[id] || null,
              createElement: () => ({ attrs: {}, kids: [], style: { setProperty() {} }, setAttribute(k, v) { this.attrs[k] = v; },
                                      removeAttribute(k) { delete this.attrs[k]; }, appendChild(k) { this.kids.push(k); } }) },
  setTimeout: (fn, ms) => { log.timers.push(ms); win.fire = fn; return 1; }, clearTimeout: () => { win.fire = null; },
  AbortController: function () { this.signal = { tag: "signal" }; this.abort = () => { log.aborted += 1; }; },
};
for (const name of ["sessionStorage", "localStorage", "indexedDB", "caches"]) {         // any use of storage is seen
  Object.defineProperty(win, name, { get() { log.storage = (log.storage || []).concat(name); return undefined; } });
}
let release = null;
if (c.fetch !== "missing") {
  win.fetch = (url, opts) => {
    log.fetches.push({ url, credentials: opts.credentials, referrerPolicy: opts.referrerPolicy, signal: !!opts.signal,
                       keys: Object.keys(opts).sort() });
    if (c.fetch === "throws") { throw new Error("blocked"); }
    if (c.fetch === "rejects") { return Promise.reject(new Error("network")); }
    if (c.fetch === "hangs") { return new Promise((ok) => { release = () => ok({ ok: true, json: () => Promise.resolve(c.answer) }); }); }
    if (c.fetch === "status") { return Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve(c.answer) }); }
    if (c.fetch === "sized") { return Promise.resolve({ ok: true, headers: { get: (k) => (k.toLowerCase() === "content-length" ? c.length : null) }, json: () => { log.read = true; return Promise.resolve(c.answer); } }); }
    if (c.fetch === "html") { return Promise.resolve({ ok: true, json: () => Promise.reject(new SyntaxError("Unexpected token <")) }); }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(c.answer) });
  };
}
global.window = win;
const s = require(skyJs);
const settle = () => new Promise((r) => setImmediate(r));
(async () => {
  const seen = [];
  const snap = () => seen.push(Object.assign({}, attrs));
  s.loadWeather(); await settle(); snap();                       // the page view
  for (const step of c.then || []) {
    if (step.wait) { now += step.wait * 60000; }
    if (step.do === "timeout") { win.fire(); }
    if (step.do === "release") { release(); }
    if (step.do === "tick") { s.tick(); }
    if (step.do === "sunset") { sunAt = "down"; s.showWeather(); }
    if (step.do === "sunrise") { sunAt = "up"; s.showWeather(); }
    if (step.do === "ask again") { s.loadWeather(); }           // a second call in the same page view
    await settle(); snap();
  }
  console.log(JSON.stringify({ seen, log }));
})();
"""


def page(node, **case):
    case = {"now": NOW, "url": URL, "answer": fresh(SCENES[0][1]), **case}
    res = subprocess.run([node, "-e", PAGE_PROBE, str(SKY_JS), json.dumps(case)], capture_output=True, text=True,
                         timeout=60, env={"TZ": "America/Chicago", "PATH": str(Path(node).parent)})
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


# the stand-in page has no sun element and no moon drawn: the weather's own small cloud in the open sky
RAIN_ATTRS = {"data-wx": "rain", "data-wx-fall": "moderate", "data-wx-on": "sky"}


def test_a_page_view_asks_once_and_draws_the_scene(node):
    got = page(node)
    assert got["seen"] == [RAIN_ATTRS]
    # one request: to the page's one address, with no credentials and no referrer, and nothing else set on it
    assert got["log"]["fetches"] == [{"url": URL, "credentials": "omit", "referrerPolicy": "no-referrer",
                                      "signal": True, "keys": ["credentials", "referrerPolicy", "signal"]}]
    assert got["log"]["timers"] == [5000] and got["log"]["aborted"] == 0
    # the drawing: decoration only, made once and put in one place
    assert got["log"]["layer"] == {"id": "sky-wx", "cls": "sky-wx", "attrs": {"aria-hidden": "true"}, "parts": PARTS}
    assert got["log"]["moves"] == ["header"]
    assert "storage" not in got["log"]                         # nothing is kept in the browser


def test_each_scene_sets_its_attributes_and_clear_sets_none(node):
    wind = page(node, answer=fresh({"presentWeather": [pw("+SN", "snow", "heavy")], "windGust": kmh(70)}))
    assert wind["seen"] == [{"data-wx": "snow", "data-wx-fall": "heavy", "data-wx-wind": "", "data-wx-on": "sky"}]
    assert page(node, answer=fresh({"cloudLayers": [{"amount": "OVC"}]}))["seen"] == [{"data-wx": "overcast", "data-wx-on": "sky"}]
    clear = page(node, answer=fresh({"textDescription": "Clear"}))
    assert clear["seen"] == [{}] and "layer" not in clear["log"]          # the plain sky: no drawing is made at all
    for sun in ("up", "down"):
        clear = page(node, sun=sun, answer=fresh({"textDescription": "Clear"}))
        assert clear["seen"] == [{}] and "layer" not in clear["log"] and clear["log"]["moves"] == [], sun


def test_the_weather_is_drawn_inside_the_sun_while_it_is_up_and_leaves_it_when_it_sets(node):
    """Owner, 2026-11-24: the sun (or the moon) shows the weather. The one drawing is put inside the sun's own element
    while the sun is up, taken out to the open sky when it sets with no moon drawn, and put back at sunrise. (That it
    goes inside the drawn moon, and where it then sits, is the browser test below.)"""
    got = page(node, sun="up", then=[{"do": "tick"}, {"do": "sunset"}, {"do": "tick"}, {"do": "sunrise"}])
    day = {"data-wx": "rain", "data-wx-fall": "moderate", "data-wx-on": "sun"}
    assert got["seen"] == [day, day, RAIN_ATTRS, RAIN_ATTRS, day]
    assert got["log"]["moves"] == ["sun", "header", "sun"]                 # moved only when what is up changes
    assert got["log"]["layer"]["parts"] == PARTS and len(got["log"]["fetches"]) == 1
    # an observation that goes stale while the sun is up: the plain sun again
    stale = page(node, sun="up", then=[{"do": "tick", "wait": 90}])
    assert stale["seen"] == [day, {}] and stale["log"]["moves"] == ["sun"]


@pytest.mark.parametrize("how", ["rejects", "throws", "status", "html"])
def test_a_failed_request_draws_nothing_and_is_not_tried_again(node, how):
    got = page(node, fetch=how, then=[{"do": "tick"}, {"do": "ask again"}, {"do": "tick", "wait": 10}])
    assert got["seen"] == [{}, {}, {}, {}], how
    assert len(got["log"]["fetches"]) == 1 and "storage" not in got["log"], how      # not on a redraw, not if called again


@pytest.mark.parametrize("answer", [None, "Rain", [], {"properties": None}, {"status": 404, "title": "Not Found"},
                                    {"properties": {**RAINING, "timestamp": "2026-11-23T15:00:00Z"}}])
def test_an_answer_that_is_not_a_fresh_observation_draws_nothing(node, answer):
    got = page(node, answer=answer)
    assert got["seen"] == [{}] and len(got["log"]["fetches"]) == 1


def test_an_answer_that_says_it_is_over_64_kb_is_not_read(node):
    big = page(node, fetch="sized", length="65537", then=[{"do": "tick"}])
    assert big["seen"] == [{}, {}] and "read" not in big["log"] and len(big["log"]["fetches"]) == 1
    for length in ("65536", "4212", None, "many"):               # at the limit, usual, not given, not a number: read
        ok = page(node, fetch="sized", length=length)
        assert ok["seen"] == [RAIN_ATTRS] and ok["log"]["read"] is True, length


def test_no_answer_in_five_seconds_draws_nothing_even_if_it_comes_later(node):
    got = page(node, fetch="hangs", then=[{"do": "timeout"}, {"do": "release"}, {"do": "tick"}])
    assert got["seen"] == [{}, {}, {}, {}]
    assert got["log"]["timers"] == [5000] and got["log"]["aborted"] == 1 and len(got["log"]["fetches"]) == 1
    # answered in time, the timer is dropped and the scene is drawn
    in_time = page(node, fetch="hangs", then=[{"do": "release"}])
    assert in_time["seen"] == [{}, RAIN_ATTRS] and in_time["log"]["aborted"] == 0


def test_an_open_tab_stops_drawing_an_observation_once_it_is_ninety_minutes_old(node):
    """The observation is seven minutes old when asked. It is judged again at each redraw and never asked for again."""
    got = page(node, then=[{"do": "tick", "wait": 60}, {"do": "tick", "wait": 22}, {"do": "tick", "wait": 2}])
    assert got["seen"] == [RAIN_ATTRS, RAIN_ATTRS, RAIN_ATTRS, {}]       # 7, 67, 89 and 91 minutes old
    assert len(got["log"]["fetches"]) == 1


def test_one_request_per_page_view_however_often_it_is_called(node):
    got = page(node, then=[{"do": "ask again"}, {"do": "tick", "wait": 20}, {"do": "ask again"}])
    assert got["seen"] == [RAIN_ATTRS] * 4 and len(got["log"]["fetches"]) == 1 and "storage" not in got["log"]


@pytest.mark.parametrize("case", [{"url": None}, {"url": ""}, {"url": "http://api.weather.gov/x"}, {"url": "/weather.json"},
                                  {"fetch": "missing"}])
def test_a_page_with_no_https_address_or_no_fetch_asks_nothing(node, case):
    got = page(node, **case)
    assert got["seen"] == [{}] and got["log"]["fetches"] == [] and got["log"]["timers"] == []


def test_the_script_says_what_it_asks_and_keeps():
    head = JS[:JS.index("(function (root)")]
    assert "No network calls" not in JS and "nothing sent" not in JS
    assert "only network call" in head and "no credentials, no referrer" in head and "National Weather Service" in head
    assert "Nothing is stored by the script" in head and "this site's address" in head and "90 minutes" in head
    assert "sessionStorage" not in JS and "localStorage" not in JS and "cookie" not in JS
    assert JS.count("fetch(") == 1 and "XMLHttpRequest" not in JS and "sendBeacon" not in JS
    assert "api.weather.gov" not in JS and "KCKV" not in JS            # the address comes from the page, from config
    assert "setInterval(tick, 300000)" in JS and JS.count("setInterval(") == 1     # no timer of its own, no retry loop
    assert JS.count("requestAnimationFrame") == 1 and "canvas" not in JS.lower()     # the resize handler's only


# --- the config, the page and the CSP --------------------------------------------------------------------------

def test_config_names_the_station_and_the_address():
    w = config.SITE["sky_weather"]
    assert w["station"] == "KCKV" and w["url"] == "https://api.weather.gov/stations/{station}/observations/latest"
    assert weather.problems() == []
    s = weather.settings()
    assert (s["station"], s["url"], s["origin"]) == ("KCKV", URL, ORIGIN) and weather.origin() == ORIGIN
    assert s["disclosure"] == " ".join(w["disclosure"].split())


def test_config_off_without_the_block_or_the_place():
    base = dict(config.SITE)
    no_block = {k: v for k, v in base.items() if k != "sky_weather"}
    no_place = {k: v for k, v in base.items() if k != "sky_place"}
    assert weather.problems(no_block) == [] and weather.settings(no_block) is None and weather.origin(no_block) is None
    assert weather.settings(no_place) is None and weather.origin(no_place) is None


def test_config_problems_refuse_anything_but_a_station_and_a_plain_https_address():
    ok = dict(config.SITE["sky_weather"])
    for bad, word in (({"station": "kckv"}, "station"), ({"station": "KCKV/../x"}, "station"), ({"station": 7}, "station"),
                      ({"url": "http://api.weather.gov/stations/{station}/observations/latest"}, "url"),
                      ({"url": "https://api.weather.gov/stations/KCKV/observations/latest"}, "url"),      # no {station}
                      ({"url": "https://api.weather.gov/stations/{station}?x=1"}, "url"),
                      ({"url": "https://user@api.weather.gov/{station}"}, "url"),
                      ({"url": "https://api.weather.gov:8443/{station}"}, "url"),
                      ({"url": "https://api.weather.gov/{station}\" onload=\"x"}, "url"),
                      ({"url": "https://*/{station}"}, "url"), ({"url": "https://{station}/x"}, "url"),
                      ({"url": None}, "url"), ({"disclosure": ""}, "disclosure"), ({"disclosure": 4}, "disclosure"),
                      ({"extra": 1}, "unknown keys")):
        cfg = {**config.SITE, "sky_weather": {**ok, **bad}}
        found = weather.problems(cfg)
        assert found and any(word in p for p in found), (bad, found)
        assert weather.settings(cfg) is None and weather.origin(cfg) is None, bad
    assert weather.problems({**config.SITE, "sky_weather": "KCKV"}) == ["sky_weather must be a mapping {station, url, disclosure}"]


def test_csp_names_the_weather_origin_and_combines_it_with_the_counter():
    counter = "https://x-y.goatcounter.com"
    assert "connect-src 'none';" in views.csp()
    assert f"connect-src {ORIGIN};" in views.csp(weather=ORIGIN)
    assert f"connect-src {counter};" in views.csp(counter=counter)
    assert f"connect-src {ORIGIN} {counter};" in views.csp(counter=counter, weather=ORIGIN)
    # every other directive is as it was
    for kw in ({"weather": ORIGIN}, {"weather": ORIGIN, "counter": counter},
               {"weather": ORIGIN, "form_origin": "https://buttondown.com"}):
        base = views.csp(**{k: v for k, v in kw.items() if k != "weather"})
        plain = {k: v for k, v in site_checks.parse_csp(base).items() if k != "connect-src"}
        with_weather = site_checks.parse_csp(views.csp(**kw))
        assert {k: v for k, v in with_weather.items() if k != "connect-src"} == plain, kw
        assert with_weather["connect-src"][0] == ORIGIN and "'none'" not in with_weather["connect-src"], kw


def test_every_built_page_carries_the_address_and_allows_only_its_origin(pages):
    """The fixture build (no visitor counter): the header names the configured address, and connect-src that origin."""
    assert pages
    for rel, html in pages.items():
        assert html.count(f' data-weather="{URL}" hidden>') == 1 and html.count("data-weather") == 1, rel
        assert '<span class="sky-moon" id="sky-moon" data-lat="36.53" data-lon="-87.36" data-weather="' in html, rel
        pol = site_checks.parse_csp(META.search(html).group(1).replace("&#39;", "'"))
        assert pol["connect-src"] == [ORIGIN], rel
        assert "sky-wx" not in html and "api.weather.gov" not in html.replace(URL, "").replace(f"connect-src {ORIGIN}", ""), rel


def test_site_context_wires_the_weather_and_the_digest_pages_keep_their_own_policy(facts):
    site = views.site_context(facts, counter="https://x-y.goatcounter.com")
    assert site["sky_weather"]["url"] == URL
    assert f"connect-src {ORIGIN} https://x-y.goatcounter.com;" in site["csp"]
    assert "connect-src https://x-y.goatcounter.com;" in site["csp_digest"] and ORIGIN not in site["csp_digest"]


def test_a_build_without_the_block_asks_nothing(monkeypatch, tmp_path):
    from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, build
    monkeypatch.delitem(config.SITE, "sky_weather")
    out = tmp_path / "build" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS)
    htmls = {p.relative_to(out).as_posix(): p.read_text(encoding="utf-8") for p in out.rglob("*.html")}
    for rel, html in htmls.items():
        assert "data-weather" not in html and "weather.gov" not in html and "connect-src &#39;none&#39;" in html, rel
    assert "Weather Service" not in htmls["about.html"] + htmls["method.html"]
    assert "These two keys are all this site keeps in your browser." in htmls["method.html"]
    assert "The site's own small scripts make no network requests" in htmls["about.html"]
    parsed = {rel: site_checks.parse(out / rel) for rel in htmls}
    cfg = {k: v for k, v in site_checks._site_cfg().items() if k != "sky_weather"}
    assert site_checks.check_external(parsed, out, cfg) == []
    assert site_checks.check_header(out, parsed, cfg)[0] == []


def test_a_bad_block_stops_the_build(monkeypatch, tmp_path):
    from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, build
    from sitegen.build import BuildError
    monkeypatch.setitem(config.SITE, "sky_weather", {**config.SITE["sky_weather"], "url": "http://example.com/{station}"})
    with pytest.raises(BuildError, match="sky_weather.url"):
        build(FIXTURE, tmp_path / "build" / "site", seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS)


def test_the_site_check_holds_the_address_and_the_policy_together(built, tmp_path):
    cfg = site_checks._site_cfg()
    assert site_checks.weather_address(cfg) == URL

    def problems(edit, rel="about.html"):
        site = tmp_path / edit.__name__
        shutil.copytree(built, site)
        target = site / rel
        html = target.read_text(encoding="utf-8")
        new = edit(html)
        assert new != html
        target.write_text(new, encoding="utf-8")
        parsed = {p.relative_to(site).as_posix(): site_checks.parse(p) for p in site.rglob("*.html")}
        return site_checks.check_external(parsed, site, cfg), site_checks.check_header(site, parsed, cfg)[0]

    def untouched(html):
        return html + "\n"

    def other_address(html):
        return html.replace(URL, "https://api.weather.gov/stations/KBNA/observations/latest")

    def other_host(html):
        return html.replace(f'data-weather="{URL}"', 'data-weather="https://weather.example/latest"')

    def second_address(html):
        return html.replace("<main", f'<div data-weather="{URL}"></div><main', 1)

    def no_origin(html):
        return html.replace(f"connect-src {ORIGIN}", "connect-src &#39;none&#39;")

    def more_origins(html):
        return html.replace(f"connect-src {ORIGIN}", f"connect-src {ORIGIN} https://evil.example")

    def no_address(html):
        return html.replace(f' data-weather="{URL}"', "")

    assert problems(untouched) == ([], [])
    for edit in (other_address, other_host, second_address):
        ext, _ = problems(edit)
        assert any("weather address" in p for p in ext), (edit.__name__, ext)
    for edit in (no_origin, more_origins):
        ext, _ = problems(edit)
        assert any("CSP connect-src" in p for p in ext), (edit.__name__, ext)
    ext, header = problems(no_address)                       # an origin allowed with nothing to ask, and a header apart
    assert any("CSP connect-src" in p for p in ext) and any("header differs" in p for p in header)


def test_about_and_method_say_what_is_asked_and_kept(pages):
    said = weather.settings()["disclosure"]
    assert said.startswith("Each page asks the National Weather Service for the current weather at Clarksville's airport")
    assert "The request does not say which page you are reading." in said
    assert ("Like any web request, it tells the Weather Service your IP address, your browser and that the request "
            "came from this site.") in said
    assert said.endswith("This site keeps nothing from it; your browser may briefly cache the answer, as it does for "
                         "any web page.")
    import html as html_mod
    about, method = html_mod.unescape(pages["about.html"]), html_mod.unescape(pages["method.html"])
    assert about.count(said) == 1 and method.count(said) == 1
    assert f'<p id="weather">{said}</p>' in method
    assert "These two keys are all this site keeps in your browser." in method       # still true: nothing is stored
    assert said + " The site's own small scripts make no other network requests" in about
    for rel, page_html in pages.items():                     # config text, printed on those two pages only
        if rel not in ("about.html", "method.html"):
            assert "National Weather Service" not in page_html, rel


# --- the drawing -----------------------------------------------------------------------------------------------

def test_every_scene_but_clear_has_a_drawing_and_the_drawing_names_no_other(node):
    ids = run(node, "const s = require(process.argv[1]); console.log(JSON.stringify(s.SCENES.map(x => x.id)));")
    drawn = set(re.findall(r'\[data-wx="([a-z]+)"\]', WX_CSS))
    assert drawn == set(ids) - {"clear"}
    assert set(re.findall(r'\[data-wx-fall="([a-z]+)"\]', WX_CSS)) == {"light", "moderate", "heavy"}
    assert "[data-wx-wind]" in WX_CSS


def test_the_weather_colours_keep_the_words_contrast_in_both_themes():
    """Each colour the scene lays behind the header's words is itself 4.5:1 or better against the ink and the muted
    ink, so no mix of it with the sky (which already is) can fall below."""
    tokens = ("--wx-veil", "--wx-cloud", "--wx-fog", "--wx-fall", "--wx-moon-cloud", "--wx-moon-fall")
    for theme in (LIGHT, DARK):
        for token in tokens:
            for text in ("--fg", "--muted"):
                assert _ratio(theme[text], theme[token]) >= 4.5, (token, text, _ratio(theme[text], theme[token]))
    media = CSS[CSS.index("@media (prefers-color-scheme: dark)"):]
    media = media[:media.index("}")]
    assert all(f"{t}: {DARK[t]}" in media for t in tokens)                # the two dark blocks agree
    used = set(re.findall(r"var\((--wx-(?:moon-)?(?:veil|cloud|fog|fall))\)", WX_CSS))
    assert used == set(tokens)
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b", re.sub(r'url\("data:[^"]*"\)', "", WX_CSS).split("*/", 1)[1])   # no colour of its own


def test_the_weather_on_the_moon_is_never_the_moons_own_colour():
    """Review, wx-visible/light-moon: in the light theme the moon, the clouds and the rain were all #FFFFFF, so rain
    and cloud on the moon did not show. What is drawn on the moon has its own two colours, neither of them the
    moon's, in both themes; and what crosses the sun is not the sun's colour either."""
    for theme in (LIGHT, DARK):
        for token in ("--wx-moon-fall", "--wx-moon-cloud", "--wx-veil"):
            assert theme[token].upper() != theme["--moon"].upper(), token
            assert _ratio(theme[token], theme["--moon"]) >= 1.3, (token, _ratio(theme[token], theme["--moon"]))
        for token in ("--wx-fall", "--wx-cloud", "--wx-veil"):
            assert _ratio(theme[token], theme["--sun"]) >= 2, (token, _ratio(theme[token], theme["--sun"]))
    # on the moon the cloud, what falls, the bolt and the wind are drawn in those colours, whatever the scene
    assert '.has-sky[data-wx-on="moon"] .wx-cloud { background: linear-gradient(var(--wx-moon-cloud), var(--wx-veil) 60%); }' in WX_CSS
    assert ('.has-sky[data-wx-on="moon"] .wx-fall, .has-sky[data-wx-on="moon"] .wx-flash { background: var(--wx-moon-fall); }'
            in WX_CSS)
    assert '.has-sky[data-wx-on="moon"][data-wx="windy"] .wx-cloud { background: var(--wx-moon-fall); }' in WX_CSS


MOON_PLACE_PROBE = r"""
const s = require(process.argv[1]);
const at = Date.parse(process.argv[2]), withAddress = process.argv[3] === "yes";
const node = (id) => { const n = { id, attrs: {}, css: {}, kids: [], parentNode: null,
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }, hasAttribute(k) { return k in this.attrs; },
  setAttribute(k, v) { this.attrs[k] = v; if (k === "id") { els[v] = this; } }, removeAttribute(k) { delete this.attrs[k]; },
  appendChild(c) { this.kids.push(c); c.parentNode = this; }, insertBefore(c) { this.kids.push(c); c.parentNode = this; } };
  n.style = { setProperty(k, v) { n.css[k] = v; }, removeProperty(k) { delete n.css[k]; } }; return n; };
const els = {};
const header = node("header"), frame = node("frame"), moon = (els["sky-moon"] = node("sky-moon"));
const sun = (els["sky-sun"] = node("sky-sun")); sun.attrs["data-at"] = "down";
frame.parentNode = header; moon.parentNode = frame; moon.attrs.hidden = ""; moon.offsetWidth = 40;
if (withAddress) { moon.attrs["data-weather"] = "https://api.weather.gov/stations/KCKV/observations/latest"; }
// a 1280 by 146 band whose words fill the left half, as the name plate and the date line do
frame.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1280, height: 146 });
const words = { id: "words" };
const doc = { getElementById: (id) => els[id] || null, querySelectorAll: () => [words],
  createRange: () => ({ selectNodeContents() {}, getBoundingClientRect: () => ({ left: 112, top: 20, right: 690, bottom: 130, width: 578, height: 110 }) }),
  createElement: () => { const n = node(""); Object.defineProperty(n, "id", { set(v) { els[v] = n; }, get() { return "sky-wx"; } }); return n; },
  createElementNS: () => node("") };
const where = () => [moon.css["--moon-left"], moon.css["--moon-top"], "hidden" in moon.attrs];
const seen = {};
s.renderMoon(doc, at, { lat: 36.53, lon: -87.36 }, false);                    // the first draw, before any answer
seen.first = where();
s.drawWeather(doc, { scene: "rain", intensity: "moderate", windy: false });    // the answer comes
seen.rain = where(); seen.on = header.attrs["data-wx-on"]; seen.host = els["sky-wx"].parentNode.id;
s.drawWeather(doc, { scene: "partly", intensity: null, windy: true });
seen.partly = where();
s.drawWeather(doc, null);                                                      // and goes stale
seen.cleared = where(); seen.after = Object.keys(header.attrs);
console.log(JSON.stringify(seen));
"""


def test_the_moon_does_not_move_when_the_weather_arrives(node):
    """Review, moon-place/jump-on-weather: the moon's place must not depend on the request. A page that names a
    weather address keeps the cloud's room around the moon from the first draw, so the moon is where it was when
    the answer comes, changes or goes stale."""
    for instant in ("2026-11-25T05:30:00Z", "2026-11-27T03:00:00Z", "2026-11-12T23:20:00Z"):   # high, east, low west
        got = run(node, MOON_PLACE_PROBE, instant, "yes")
        assert got["first"][2] is False and got["first"][0].endswith("px") and got["first"][1].endswith("px"), instant
        assert got["rain"] == got["partly"] == got["cleared"] == got["first"], (instant, got)
        assert got["on"] == "moon" and got["host"] == "sky-moon" and got["after"] == [], instant
        # the room is real: beside the words, the same moon on a page that asks for no weather sits closer to them
        plain = run(node, MOON_PLACE_PROBE, instant, "no")
        assert plain["rain"] == plain["first"], instant
        assert int(plain["first"][0][:-2]) < int(got["first"][0][:-2]), (instant, plain["first"], got["first"])
    assert "placeMoon(doc)" not in JS[JS.index("function drawWeather("):JS.index("/* The observation this page view holds")]
    assert 'rooms = mayHaveWeather ? [WX_ROOM, 0] : [0];' in JS


def test_the_suns_cloud_stays_on_the_sun():
    """Review, wx-host/sun-at-horizon: over a sun on the horizon the cloud must not float above it. Its top is held
    to a part of its own height above the sun's top, and nothing falls a negative distance."""
    assert "--wx-base: min(max(var(--wx-v) * .28, var(--wx-s) * .1), var(--wx-v) - var(--wx-ch) * .55);" in WX_CSS
    assert ("--wx-base: min(max(var(--wx-v) * .45, var(--wx-s) * .4), var(--wx-v) - var(--wx-ch) * .25); "
            "--wx-fh: max(var(--wx-base), 0px);") in WX_CSS


def test_the_drawing_is_decoration_that_takes_no_room_and_belongs_to_the_sun_or_the_moon():
    assert "position: absolute; left: 0; top: 0; width: var(--wx-s); height: var(--wx-s); pointer-events: none;" in WX_CSS
    assert ".sky-wx > span { position: absolute; opacity: 0; }" in WX_CSS                # nothing shows with no scene
    assert ".sky-wx[hidden] { display: none; }" in WX_CSS
    assert CSS.index(".sky-wx {") < CSS.index(".has-sky .masthead { z-index: 1; }")     # the words sit above it
    assert 'layer.setAttribute("aria-hidden", "true")' in JS
    # inside the sun or the moon; in the header itself (after the sky, before the words) only when neither is up
    assert 'var on = sunEl && sunEl.getAttribute("data-at") === "up" ? "sun" : drawn ? "moon" : "sky";' in JS
    assert 'if (on === "sky") { header.insertBefore(layer, frame.nextSibling); } else { host.appendChild(layer); }' in JS
    # it takes its size from the body it is on, and on the sun its box is the part above the horizon
    assert ".sky-moon .sky-wx { --wx-s: var(--moon-size); }" in WX_CSS
    assert "--wx-s: var(--sun-size);" in WX_CSS and "--wx-v: calc(var(--sun-alt) * var(--sun-max) * var(--sun-size));" in WX_CSS
    assert "height: var(--wx-v);" in WX_CSS
    # no band-wide layer is left: nothing in the drawing spans the header
    assert "inset: 0" not in WX_CSS and "wx-clouds" not in CSS + JS and "wx-near" not in CSS + JS
    # the sun and the moon are not faded as wholes any more; the moon's lit part alone is drawn fainter behind cloud
    assert not re.search(r"\.sky-(sun|moon)\s*(,[^{]*)?\{[^}]*opacity", CSS)
    assert '.has-sky[data-wx-on="moon"][data-wx="storm"] .moon-lit { opacity: .42; }' in WX_CSS
    assert ".sky-moon .wx-veil, .site-header > .sky-wx .wx-veil { display: none; }" in WX_CSS   # no disc behind a crescent
    # the lone cloud of a moonless night is fainter than the same cloud on the sun or the moon
    assert ".site-header > .sky-wx { left: var(--wx-left, 0); top: var(--wx-top, 0); opacity: .7; }" in WX_CSS
    # the shapes are masks from data: addresses (img-src 'self' data:), never a file from somewhere else
    urls = re.findall(r'url\("([^"]*)"\)', WX_CSS)
    assert len(urls) == 5 and all(u.startswith("data:image/svg+xml,") for u in urls)
    assert all("http://www.w3.org/2000/svg" in u for u in urls)
    assert "<" not in "".join(urls) and "script" not in "".join(urls).lower() and "href" not in "".join(urls).lower()


def test_motion_is_transform_and_opacity_only_and_only_when_allowed():
    start = WX_CSS.index("@media (prefers-reduced-motion: no-preference) {")
    end = WX_CSS.index("\n}\n", start)
    outside = WX_CSS[:start] + WX_CSS[end:]
    assert "animation" not in re.sub(r"@keyframes[^\n]*\n", "", outside) and "transition" not in outside
    assert WX_CSS[start:end].count("animation") >= 7 and "prefers-reduced-motion: reduce" not in WX_CSS
    frames = re.findall(r"@keyframes (wx-[a-z-]+) \{(.*)\}\n", WX_CSS)
    assert {n for n, _ in frames} == {"wx-drift", "wx-fall", "wx-gust", "wx-flash"}
    used = set(re.findall(r"animation: (wx-[a-z]+)", WX_CSS[start:end]))
    assert used == {n for n, _ in frames}                                  # each is used, and none other is named
    for name, body in frames:
        props = set(re.findall(r"([a-z-]+):", body))
        assert props <= {"transform", "opacity"} and props, (name, props)
    # at rest (reduced motion) the three rows of what falls sit one under the other, shown by how much falls
    assert ".sky-wx > .wx-fall { opacity: var(--wx-o); }" in outside
    for row, share in (("a", ".08"), ("b", ".4"), ("c", ".7")):
        assert f"transform: translate3d(0, calc(var(--wx-fh) * {share}), 0); }}" in outside, row
    # lightning stays far under three flashes a second: two flickers in eleven seconds
    assert '.has-sky[data-wx="storm"] .wx-flash { animation: wx-flash 11s linear infinite; }' in WX_CSS


# --- in a browser: the weather sits on the sun or the moon -------------------------------------------------

WX_BROWSER = r"""
const path = require('path');
let pw;
const roots = [...(process.env.NODE_PATH || '').split(path.delimiter).filter(Boolean), '/opt/node22/lib/node_modules'];
for (const r of ['', ...roots]) {
  try { pw = require(r ? path.join(r, 'playwright') : 'playwright'); break; } catch (e) { /* next */ }
}
(async () => {
  const [site, cases] = [process.argv[2], JSON.parse(process.argv[3])];
  const browser = await pw.chromium.launch();
  const out = [];
  for (const c of cases) for (const width of [390, 1280]) {
    const ctx = await browser.newContext({ viewport: { width, height: 800 }, timezoneId: 'America/Chicago',
      reducedMotion: c.motion ? 'no-preference' : 'reduce' });
    const page = await ctx.newPage();
    await page.clock.setFixedTime(new Date(c.at));
    let asked = 0;
    await page.route('https://api.weather.gov/**', (route) => {
      asked += 1;
      const stamp = new Date(Date.parse(c.at) - 7 * 60000).toISOString();
      return route.fulfill({ status: 200, contentType: 'application/geo+json', headers: { 'access-control-allow-origin': '*' },
        body: JSON.stringify({ type: 'Feature', properties: Object.assign({ timestamp: stamp }, c.props) }) });
    });
    await page.goto('file://' + path.join(site, 'index.html'));
    await page.evaluate(() => document.fonts.ready.then(() => new Promise(r => setTimeout(r, 150))));
    const at = await page.evaluate(() => {
      const box = (r) => ({ left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height });
      const header = document.querySelector('.site-header'), wx = document.getElementById('sky-wx');
      const sun = document.getElementById('sky-sun'), moon = document.getElementById('sky-moon');
      const words = Array.from(document.querySelectorAll('#nav-open, .site-header .site-name, .site-header .unofficial-tag, .site-header .kicker, #sky-hero .sky-day'))
        .map((n) => { if (n.id === 'nav-open') { return box(n.getBoundingClientRect()); }
                      const g = document.createRange(); g.selectNodeContents(n); return box(g.getBoundingClientRect()); });
      const parts = {};
      if (wx) { for (const p of wx.children) { const st = getComputedStyle(p);
        parts[p.className] = { box: box(p.getBoundingClientRect()), opacity: parseFloat(st.opacity), shown: st.display !== 'none',
                               moving: st.animationName !== 'none' }; } }
      return { wx: header.getAttribute('data-wx'), on: header.getAttribute('data-wx-on'), layers: document.querySelectorAll('.sky-wx').length,
               host: wx ? (wx.parentNode.id || wx.parentNode.className) : null, hidden: wx ? wx.hasAttribute('hidden') : null,
               aria: wx ? wx.closest('[aria-hidden="true"]') !== null : null,
               sunUp: sun.getAttribute('data-at') === 'up' && getComputedStyle(sun).visibility === 'visible', sun: box(sun.getBoundingClientRect()),
               moonUp: !moon.hasAttribute('hidden'), moon: box(moon.getBoundingClientRect()),
               moonLit: moon.querySelector('.moon-lit') ? parseFloat(getComputedStyle(moon.querySelector('.moon-lit')).opacity) : null,
               header: box(header.getBoundingClientRect()), words, parts,
               scrolls: document.documentElement.scrollWidth > document.documentElement.clientWidth };
    });
    out.push({ name: c.name, width, asked, ...at });
    await ctx.close();
  }
  await browser.close();
  console.log(JSON.stringify(out));
})();
"""

NOON, NIGHT_MOON, NIGHT_NONE = "2026-11-24T18:00:00Z", "2026-11-25T05:30:00Z", "2026-11-09T06:00:00Z"
RAIN = {"presentWeather": [pw("RA", "rain")], "cloudLayers": [{"amount": "OVC"}]}
PARTLY = {"cloudLayers": [{"amount": "SCT"}]}


def _hits(a, b):
    return a["left"] < b["right"] and b["left"] < a["right"] and a["top"] < b["bottom"] and b["top"] < a["bottom"]


def _browser_ok():
    return bool(shutil.which("node")) and (os.path.exists("/opt/pw-browsers") or bool(shutil.which("playwright")))


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_in_a_browser_the_weather_sits_on_the_sun_or_the_moon(built, tmp_path):
    """At 390 and 1280, with the one request answered by a made-up observation: by day the cloud is inside the sun
    and over its disc, at night inside the moon and over it, and the moon keeps clear of the header's words; rain
    falls from the cloud across the disc; a clear answer leaves the plain sun and the plain moon; with neither up
    there is one small cloud in the open sky, off every word. One request each, and the page never scrolls sideways."""
    cases = [{"name": "sun partly", "at": NOON, "props": PARTLY}, {"name": "sun rain", "at": NOON, "props": RAIN},
             {"name": "sun rain moving", "at": NOON, "props": RAIN, "motion": True},
             {"name": "moon partly", "at": NIGHT_MOON, "props": PARTLY}, {"name": "moon rain", "at": NIGHT_MOON, "props": RAIN},
             {"name": "sun clear", "at": NOON, "props": {"textDescription": "Clear"}},
             {"name": "moon clear", "at": NIGHT_MOON, "props": {"textDescription": "Clear"}},
             {"name": "neither rain", "at": NIGHT_NONE, "props": RAIN}]
    script = tmp_path / "wx.js"
    script.write_text(WX_BROWSER, encoding="utf-8")
    res = subprocess.run(["node", str(script), str(built), json.dumps(cases)], capture_output=True, text=True, timeout=300)
    assert res.returncode == 0, res.stderr[-2000:]
    rows = json.loads(res.stdout)
    assert len(rows) == 2 * len(cases)
    for r in rows:
        tag = (r["name"], r["width"])
        body, scene = r["name"].split()[0], r["name"].split()[1]
        assert r["asked"] == 1 and not r["scrolls"], tag
        assert r["sunUp"] == (body == "sun") and r["moonUp"] == (body == "moon"), tag       # never both
        if scene == "clear":                                                  # the plain sun, the plain moon
            assert r["wx"] is None and r["on"] is None and r["layers"] == 0 and r["moonLit"] in (None, 1), tag
            continue
        assert r["layers"] == 1 and r["aria"] and not r["hidden"], tag
        assert r["on"] == {"sun": "sun", "moon": "moon", "neither": "sky"}[body], tag
        assert r["host"] == {"sun": "sky-sun", "moon": "sky-moon", "neither": "site-header has-sky"}[body], tag
        front, rows_ = r["parts"]["wx-cloud wx-front"], [r["parts"][f"wx-fall wx-{x}"] for x in "abc"]
        assert front["opacity"] == 1 and front["box"]["width"] > 20, tag
        if body != "neither":
            disc = r[body]
            assert _hits(front["box"], disc), tag                             # the cloud is over the disc
            mid = (front["box"]["left"] + front["box"]["right"]) / 2          # and across its middle, not off to a side
            assert disc["left"] < mid < disc["right"], tag
            assert front["box"]["bottom"] <= r["header"]["bottom"] + 1, tag   # above the horizon
        if scene == "rain":
            moving = r["name"].endswith("moving")
            assert all(x["moving"] == moving for x in rows_) and r["parts"]["wx-flash"]["opacity"] == 0, tag
            if not moving:                                                    # at rest: where each row sits
                assert [x["opacity"] > 0 for x in rows_] == [True, True, False], tag          # moderate: two rows of three
                assert all(x["box"]["left"] >= front["box"]["left"] and x["box"]["right"] <= front["box"]["right"] for x in rows_), tag
                assert rows_[0]["box"]["top"] < front["box"]["bottom"] < rows_[0]["box"]["bottom"], tag   # from under the cloud
                if body != "neither":
                    assert _hits(rows_[0]["box"], r[body]), tag               # in front of the disc
        else:
            assert all(x["opacity"] == 0 for x in rows_), tag
        if body == "sun":
            assert r["parts"]["wx-veil"]["shown"], tag
        if body == "moon":                                                    # only its lit part, fainter behind rain
            assert not r["parts"]["wx-veil"]["shown"] and r["moonLit"] == (0.6 if scene == "rain" else 1), tag
            air = {k: r["moon"][k] + d for k, d in (("left", -2), ("top", -2), ("right", 2), ("bottom", 2))}
            assert not any(_hits(air, w) for w in r["words"]), tag            # the moon itself never behind a word
            if r["width"] == 1280:                                            # and with room, nor is its cloud
                assert not any(_hits(front["box"], w) for w in r["words"]), tag
        if body == "neither":                                                 # the lone cloud: small, in open sky
            assert front["box"]["width"] <= 70 and not any(_hits(front["box"], w) for w in r["words"]), tag
            assert _hits(front["box"], r["header"]), tag
