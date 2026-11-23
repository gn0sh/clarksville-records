"""The weather in the header's sky (owner, 2026-11-23: "if it's raining in Clarksville, it would be cool if the top
of the Daylight page had rain also", then: whatever the weather is, as a small set of scenes).

static/sky.js asks the National Weather Service, from the visitor's browser, for the latest observation of one
station (config/site.yml sky_weather: KCKV, Clarksville's airport) and draws one scene from it. Held here:

- the decision: weatherScene(observation, now) -> {scene, intensity, windy} or null, one fixture per scene, the
  precedence of SCENES, and null (the plain sky) for anything that is not a fresh observation;
- the request: one per page view, no credentials and no referrer, nothing drawn on a timeout, an error status or
  an answer that is not JSON, nothing asked twice, nothing stored;
- the wiring: the config block, the address on the page, the CSP's connect-src, the site check that holds them, and
  the sentence on the About and Method pages;
- the drawing: decoration only, the words' contrast kept, motion only where the visitor allows it.

The fixtures follow the service's documented observation schema (GeoJSON `properties`: timestamp, textDescription,
presentWeather[] with rawString / weather / intensity / modifier / inVicinity, cloudLayers[].amount, windSpeed,
windGust and visibility as {unitCode, value}). The sandbox cannot reach api.weather.gov, so none is a recording."""
# ruff: noqa: E501  (the fixture tables and the probes read better one case to a line)
import json
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
WX_CSS = CSS[CSS.index("/* The weather: one quiet scene"):CSS.index(".has-sky .masthead { z-index: 1; }")]
URL = "https://api.weather.gov/stations/KCKV/observations/latest"
ORIGIN = "https://api.weather.gov"
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
const header = { setAttribute: (k, v) => { attrs[k] = v; }, removeAttribute: (k) => { delete attrs[k]; },
                 insertBefore: (el) => { ids[el.id] = el; log.layer = { id: el.id, cls: el.className, attrs: el.attrs, parts: el.kids.map(k => k.className) }; } };
const frame = { parentNode: header, nextSibling: null };
ids["sky-moon"] = { parentNode: frame, setAttribute: () => {}, getAttribute: (k) => (k === "data-weather" ? c.url : null) };
const win = {
  document: { hidden: false, getElementById: (id) => ids[id] || null,
              createElement: () => ({ attrs: {}, kids: [], setAttribute(k, v) { this.attrs[k] = v; }, appendChild(k) { this.kids.push(k); } }) },
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


RAIN_ATTRS = {"data-wx": "rain", "data-wx-fall": "moderate"}


def test_a_page_view_asks_once_and_draws_the_scene(node):
    got = page(node)
    assert got["seen"] == [RAIN_ATTRS]
    # one request: to the page's one address, with no credentials and no referrer, and nothing else set on it
    assert got["log"]["fetches"] == [{"url": URL, "credentials": "omit", "referrerPolicy": "no-referrer",
                                      "signal": True, "keys": ["credentials", "referrerPolicy", "signal"]}]
    assert got["log"]["timers"] == [5000] and got["log"]["aborted"] == 0
    # the layer the scene is drawn in: decoration only, made once
    assert got["log"]["layer"] == {"id": "sky-wx", "cls": "sky-wx", "attrs": {"aria-hidden": "true"},
                                   "parts": ["wx-veil", "wx-clouds", "wx-fall wx-far", "wx-fall wx-near", "wx-flash"]}
    assert "storage" not in got["log"]                         # nothing is kept in the browser


def test_each_scene_sets_its_attributes_and_clear_sets_none(node):
    wind = page(node, answer=fresh({"presentWeather": [pw("+SN", "snow", "heavy")], "windGust": kmh(70)}))
    assert wind["seen"] == [{"data-wx": "snow", "data-wx-fall": "heavy", "data-wx-wind": ""}]
    assert page(node, answer=fresh({"cloudLayers": [{"amount": "OVC"}]}))["seen"] == [{"data-wx": "overcast"}]
    clear = page(node, answer=fresh({"textDescription": "Clear"}))
    assert clear["seen"] == [{}] and "layer" not in clear["log"]          # the plain sky: no layer is made at all


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
    assert "Nothing is stored" in head and "90 minutes" in head
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
    assert "says nothing about you or the page you are reading" in said and "IP address and browser" in said
    assert said.endswith("Nothing is kept in your browser.")
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
    tokens = ("--wx-veil", "--wx-cloud", "--wx-fog", "--wx-fall")
    for theme in (LIGHT, DARK):
        for token in tokens:
            for text in ("--fg", "--muted"):
                assert _ratio(theme[text], theme[token]) >= 4.5, (token, text, _ratio(theme[text], theme[token]))
    media = CSS[CSS.index("@media (prefers-color-scheme: dark)"):]
    media = media[:media.index("}")]
    assert all(f"{t}: {DARK[t]}" in media for t in tokens)                # the two dark blocks agree
    used = set(re.findall(r"var\((--wx-(?:veil|cloud|fog|fall))\)", WX_CSS))
    assert used == set(tokens)
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b", re.sub(r'url\("data:[^"]*"\)', "", WX_CSS).split("*/", 1)[1])   # no colour of its own


def test_the_scene_is_decoration_that_takes_no_room():
    assert ".sky-wx { position: absolute; inset: 0; overflow: hidden; pointer-events: none; }" in WX_CSS
    assert ".sky-wx > span { position: absolute; inset: 0; opacity: 0; }" in WX_CSS      # nothing shows with no scene
    assert CSS.index(".sky-wx {") < CSS.index(".has-sky .masthead { z-index: 1; }")     # the words sit above it
    assert 'layer.setAttribute("aria-hidden", "true")' in JS
    assert "header.insertBefore(layer, frame.nextSibling)" in JS                          # after the sky, before the words
    # the shapes are masks from data: addresses (img-src 'self' data:), never a file from somewhere else
    urls = re.findall(r'url\("([^"]*)"\)', WX_CSS)
    assert len(urls) == 3 and all(u.startswith("data:image/svg+xml,") for u in urls)
    assert "http://www.w3.org/2000/svg" in urls[0] and "<" not in "".join(urls) and "script" not in "".join(urls).lower()


def test_motion_is_transform_and_opacity_only_and_only_when_allowed():
    start = WX_CSS.index("@media (prefers-reduced-motion: no-preference) {")
    end = WX_CSS.index("\n}\n", start)
    outside = WX_CSS[:start] + WX_CSS[end:]
    assert "animation" not in re.sub(r"@keyframes[^\n]*\n", "", outside) and "transition" not in outside
    assert WX_CSS[start:end].count("animation") >= 7 and "prefers-reduced-motion: reduce" not in WX_CSS
    frames = re.findall(r"@keyframes (wx-[a-z-]+) \{(.*)\}\n", WX_CSS)
    assert {n for n, _ in frames} == {"wx-drift", "wx-rain-near", "wx-rain-far", "wx-snow-near", "wx-snow-far", "wx-wisp",
                                      "wx-flash"}
    for name, body in frames:
        props = set(re.findall(r"([a-z-]+):", body))
        assert props <= {"transform", "opacity"} and props, (name, props)
    # each turn moves a layer by whole tiles of its mask (no seam): rain 48x96 and 32x64, snow 90x90 and 60x60
    assert "wx-rain-near { to { transform: translate3d(-24px, 96px, 0); } }" in WX_CSS and "--wx-tile: 48px 96px; top: -96px; right: -24px;" in WX_CSS
    assert "wx-rain-far { to { transform: translate3d(-16px, 64px, 0); } }" in WX_CSS and "--wx-tile: 32px 64px; top: -64px; right: -16px;" in WX_CSS
    assert "wx-snow-near { to { transform: translate3d(0, 90px, 0); } }" in WX_CSS and "--wx-tile: 90px 90px; top: -90px;" in WX_CSS
    assert "wx-snow-far { to { transform: translate3d(-60px, 120px, 0); } }" in WX_CSS and "--wx-tile: 60px 60px; top: -120px; right: -60px;" in WX_CSS
    assert "wx-drift { to { transform: translate3d(-560px, 0, 0); } }" in WX_CSS and "right: -560px;" in WX_CSS
    assert "wx-wisp { to { transform: translate3d(420px, 0, 0); } }" in WX_CSS and "--wx-tile: 420px 72px; left: -420px;" in WX_CSS
