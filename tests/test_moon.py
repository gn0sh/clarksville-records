"""The moon on the sky band (owner, 2026-11-14; docs/design/daylight "The moon"): static/sky.js works out where the
moon really is over Clarksville (36.53 N, 87.36 W; config/site.yml sky_place, read from the page) at an instant, its
lit fraction, whether it is waxing and which way its bright edge points, then draws it. The sun is unchanged
(tests/test_daylight.py).

REFERENCE holds values from an independent library, PyEphem 4.2.1 (the XEphem/libastro engine), worked out when
this was written: an Observer at 36.53, -87.36, elevation 0, pressure 0 (no bending by the air), `Moon(observer)`
`.alt`, `.az` and `.phase`; waxing from the moon's ecliptic longitude less the sun's; the bright edge's direction
from PyEphem's own altitudes and azimuths of the moon and the sun (the bearing from one to the other on the sky,
clockwise from straight up), which is a different route from the script's. Measured against 2,670 instants spread
through 2026 (every 197 minutes): altitude within 0.37 degrees, direction within 0.36 degrees on the sky, lit
fraction within 0.002, bright edge within 3.1 degrees wherever 2% to 98% of the disc is lit, and waxing or waning
never wrong outside the hour or so around new and full."""
import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from sitegen import config
from test_daylight import DARK, LIGHT, _ratio, site  # noqa: F401  (site: the fixture build)

ROOT = Path(__file__).resolve().parents[1]
SKY_JS = ROOT / "site" / "static" / "sky.js"
CSS = (ROOT / "site" / "static" / "style.css").read_text(encoding="utf-8")

# (what, instant UTC, altitude, azimuth, lit fraction, waxing, bright edge clockwise from straight up): PyEphem 4.2.1.
# The four phase instants are PyEphem's next_full_moon and so on, which match the published 2026 phase tables.
REFERENCE = [
    ("full moon", "2026-11-24T14:53:00Z", -18.536, 322.783, 0.9981, True, 53.38),
    ("new moon", "2026-11-09T07:02:00Z", -64.978, 60.544, 0.0019, False, -61.85),
    ("first quarter", "2026-11-17T11:47:00Z", -66.933, 356.401, 0.5012, True, 112.55),
    ("last quarter", "2026-12-01T06:08:00Z", 6.873, 87.128, 0.5013, False, -165.92),
    ("full moon high at night", "2026-11-25T05:30:00Z", 76.98, 136.004, 0.9927, False, -92.95),
    ("thin crescent low at dusk", "2026-11-12T23:20:00Z", 13.331, 218.737, 0.1232, True, 119.61),
    ("gibbous rising by day", "2026-11-20T21:30:00Z", 17.809, 95.674, 0.8225, True, 57.43),
    ("last quarter high in the morning", "2026-12-01T13:30:00Z", 52.176, 217.519, 0.468, False, -82.9),
    ("summer full moon low in the south", "2026-06-30T05:10:00Z", 24.454, 166.477, 0.9984, False, -159.52),
    ("waning crescent before dawn", "2026-03-15T10:45:00Z", 4.604, 120.113, 0.1451, False, -118.47),
    ("first quarter high at dusk", "2026-03-26T00:30:00Z", 80.295, 204.023, 0.5259, True, 107.8),
    ("full moon in January", "2026-01-03T10:02:00Z", 36.892, 278.23, 0.9986, True, 67.64),
    ("waxing gibbous setting", "2026-08-24T07:00:00Z", 4.007, 232.406, 0.8581, True, 146.66),
    ("below the horizon", "2026-11-09T06:00:00Z", -73.379, 28.984, 0.0019, False, -45.44),
]
LAT, LON = 36.53, -87.36                                             # the reference's observer
ALT_TOL, SKY_TOL, FRACTION_TOL, LIMB_TOL = 0.5, 0.5, 0.01, 3.5      # degrees, degrees on the sky, share, degrees


@pytest.fixture(scope="module")
def node():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    return shutil.which("node")


def run(node, probe, *args):
    res = subprocess.run([node, "-e", probe, str(SKY_JS), *args], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


@pytest.fixture(scope="module")
def computed(node):
    probe = ("const s = require(process.argv[1]);"
             "const at = t => s.moon(Date.parse(t), %s, %s);"
             "console.log(JSON.stringify(JSON.parse(process.argv[2]).map(at)));" % (LAT, LON))
    return dict(zip((r[0] for r in REFERENCE), run(node, probe, json.dumps([r[1] for r in REFERENCE]))))


def test_the_page_carries_the_place_the_reference_was_worked_out_for():
    assert config.SITE["sky_place"] == {"lat": LAT, "lon": LON}


def turn(a):
    return (a + 180) % 360 - 180


@pytest.mark.parametrize("what,when,alt,az,fraction,waxing,limb", REFERENCE, ids=[r[0] for r in REFERENCE])
def test_moon_matches_the_reference(computed, what, when, alt, az, fraction, waxing, limb):
    m = computed[what]
    assert abs(m["alt"] - alt) <= ALT_TOL, (m["alt"], alt)
    # near straight overhead a small shift on the sky is a large change of compass direction, so compare on the sky
    assert abs(turn(m["az"] - az)) * math.cos(math.radians(alt)) <= SKY_TOL, (m["az"], az)
    assert 0 <= m["az"] < 360
    assert abs(m["fraction"] - fraction) <= FRACTION_TOL, (m["fraction"], fraction)
    if 0.01 < fraction < 0.99:          # at new and at full the side is about to flip, and it cannot be seen
        assert m["waxing"] is waxing
    if 0.03 < fraction < 0.97:          # a full or new disc has no bright edge to point anywhere
        assert abs(turn(m["limb"] - limb)) <= LIMB_TOL, (m["limb"], limb)


def test_the_named_phases_are_what_they_say(computed):
    assert computed["full moon"]["fraction"] > 0.99 and computed["full moon in January"]["fraction"] > 0.99
    assert computed["new moon"]["fraction"] < 0.01
    assert abs(computed["first quarter"]["fraction"] - 0.5) < 0.01 and computed["first quarter"]["waxing"] is True
    assert abs(computed["last quarter"]["fraction"] - 0.5) < 0.01 and computed["last quarter"]["waxing"] is False
    # a waxing moon in the evening sky is lit on its right (the sun has set to its west), a waning one on its left
    assert 0 < computed["thin crescent low at dusk"]["limb"] < 180
    assert -180 < computed["waning crescent before dawn"]["limb"] < 0


def test_east_is_left_south_is_the_middle_west_is_right(node):
    xs = run(node, "const s = require(process.argv[1]);"
                   "console.log(JSON.stringify([0, 55, 60, 90, 135, 180, 225, 270, 300, 320].map(s.moonX)));")
    assert xs[5] == 0.5 and xs[3] == 0.125 and xs[7] == 0.875          # south, east, west
    assert xs == sorted(xs) and xs[0] == xs[1] == xs[2] == 0 and xs[-1] == xs[-2] == 1   # kept on the band


def test_lit_shape_is_a_half_disc_closed_by_an_elliptical_terminator(node):
    new, crescent, half, gibbous, full = run(
        node, "const s = require(process.argv[1]);"
              "console.log(JSON.stringify([0, 0.25, 0.5, 0.75, 1].map(k => s.moonPath(k))));")
    arc = "M0 -10A10 10 0 0 1 0 10"                                      # the bright edge: the disc's right half
    assert crescent == arc + "A5 10 0 0 0 0 -10Z"                         # terminator bows toward the bright edge
    assert gibbous == arc + "A5 10 0 0 1 0 -10Z"                          # and away from it past half
    assert half == arc + "A0 10 0 0 0 0 -10Z"                             # a straight line at the quarters
    assert new == arc + "A10 10 0 0 0 0 -10Z" and full == arc + "A10 10 0 0 1 0 -10Z"   # nothing lit, all lit


def test_free_rect_is_the_largest_open_rectangle_clear_of_every_block(node):
    """The moon sits only in open sky: the largest rectangle of the band that touches no block (the header's words,
    the Menu column, the drawn sun) and can hold the moon; none when the band has no such room."""
    probe = r"""
const s = require(process.argv[1]);
const band = { left: 8, top: 6, right: 1272, bottom: 142 };
const words = { left: 0, top: 0, right: 700, bottom: 146 }, sun = { left: 924, top: 0, right: 1158, bottom: 168 };
const low = { left: 924, top: 100, right: 1158, bottom: 168 };
console.log(JSON.stringify([
  s.freeRect(band, [], 40), s.freeRect(band, [words], 40), s.freeRect(band, [words, sun], 40),
  s.freeRect(band, [words, low], 40), s.freeRect(band, [{ left: 0, top: 0, right: 1280, bottom: 120 }], 40),
  s.freeRect(band, [words, { left: 730, top: 0, right: 1280, bottom: 146 }], 40),
  s.moonSpot(band, [words, sun], 40, 0, 0), s.moonSpot(band, [words, sun], 40, 1, 1),
  s.moonSpot(band, [words, sun], 40, 0.5, 0.5),
  s.moonSpot(band, [{ left: 0, top: 0, right: 1280, bottom: 146 }], 40, 0.5, 0.5)]));
"""
    whole, right, between, over, none, narrow, low_east, high_west, middle, no_room = run(node, probe)
    assert whole == {"left": 8, "top": 6, "right": 1272, "bottom": 142}
    assert right == {"left": 700, "top": 6, "right": 1272, "bottom": 142}          # right of the words
    assert between == {"left": 700, "top": 6, "right": 924, "bottom": 142}         # the sun is up: left of it
    assert over == {"left": 700, "top": 6, "right": 1272, "bottom": 100}           # a low sun: the sky above it
    assert none is None and narrow is None and no_room is None                     # 22px or 30px cannot hold 40px
    # east and the horizon are the bottom left of that rectangle, west and overhead its top right
    assert low_east == {"left": 700, "top": 102} and high_west == {"left": 884, "top": 6}
    assert middle == {"left": 792, "top": 54}


RENDER_PROBE = r"""
const RealDate = Date, fixed = RealDate.parse(process.argv[2]);
global.Date = class extends RealDate { constructor(...a) { a.length ? super(...a) : super(fixed); }
  static now() { return fixed; } };
const els = {}, made = [];
const node = (tag, ns) => { const n = { tag, ns, attrs: {}, css: {}, kids: [],
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
  setAttribute(k, v) { this.attrs[k] = v; if (k === "id") { els[v] = this; } },
  removeAttribute(k) { delete this.attrs[k]; }, appendChild(c) { this.kids.push(c); } };
  n.style = { setProperty(k, v) { n.css[k] = v; }, removeProperty(k) { delete n.css[k]; } }; return n; };
const mk = id => (els[id] = node("span"));
mk("sky-sun"); const moon = mk("sky-moon"); moon.attrs.hidden = "";
const place = JSON.parse(process.argv[3]);
if (place) { moon.attrs["data-lat"] = place[0]; moon.attrs["data-lon"] = place[1]; }
// a 1280 by 146 sky band with no words and no sun measured, and a 40px moon
moon.offsetWidth = 40; moon.parentNode = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 1280, height: 146 }) };
global.window = global; global.innerWidth = 1280;
global.document = { getElementById: id => els[id] || null, querySelectorAll: () => [],
  createElementNS: (ns, tag) => { const n = node(tag, ns); made.push(tag); return n; } };
const sky = require(process.argv[1]);
sky.render(); sky.render();                                    // twice: the drawing is made once
const lit = els["sky-moon-lit"];
console.log(JSON.stringify({ sun: els["sky-sun"].css, moon: { attrs: moon.attrs, css: moon.css },
  lit: lit ? lit.attrs : {}, made,
  tree: moon.kids.map(k => [k.tag, k.ns, k.attrs, k.kids.map(c => [c.tag, c.attrs["class"]])]) }));
"""


def render(node, when, tz="America/Chicago", place=("36.53", "-87.36")):
    res = subprocess.run([node, "-e", RENDER_PROBE, str(SKY_JS), when, json.dumps(place)], capture_output=True,
                         text=True, timeout=60, env={"TZ": tz, "PATH": str(Path(node).parent)})
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def spot(alt, az):
    """Where a 40px moon goes in the probe's empty band (8 to 1272 across, 6 to 142 down): --moon-left, --moon-top."""
    return (8 + (az - 60) / 240 * (1264 - 40), 142 - 40 - alt / 90 * (136 - 40))


def test_render_places_the_moon_and_shows_it_only_above_the_horizon(node):
    up = render(node, "2026-11-25T05:30:00Z")                 # the full moon, 77 degrees up in the south-east at night
    assert "hidden" not in up["moon"]["attrs"] and "data-day" not in up["moon"]["attrs"]
    assert up["made"] == ["svg", "circle", "path"]            # drawn once, as SVG, by the script
    assert up["tree"] == [["svg", "http://www.w3.org/2000/svg", {"viewBox": "-10.5 -10.5 21 21", "focusable": "false"},
                           [["circle", "moon-disc"], ["path", "moon-lit"]]]]
    left, top = spot(76.98, 136.004)                          # real altitude and direction, inside the open sky
    assert set(up["moon"]["css"]) == {"--moon-left", "--moon-top"}
    assert up["moon"]["css"]["--moon-left"].endswith("px")
    assert abs(float(up["moon"]["css"]["--moon-left"][:-2]) - left) <= 8      # this high, 1 degree of azimuth is 5px
    assert abs(float(up["moon"]["css"]["--moon-top"][:-2]) - top) <= 2
    assert up["lit"]["d"].startswith("M0 -10A10 10 0 0 1 0 10A9.") and up["lit"]["d"].endswith(" 0 0 1 0 -10Z")
    day = render(node, "2026-11-20T21:30:00Z")                # 3:30 PM in Clarksville: the gibbous moon rising
    assert "hidden" not in day["moon"]["attrs"] and day["moon"]["attrs"]["data-day"] == ""    # paler by day
    left, top = spot(17.809, 95.674)                          # low in the east: low and to the left
    assert abs(float(day["moon"]["css"]["--moon-left"][:-2]) - left) <= 3
    assert abs(float(day["moon"]["css"]["--moon-top"][:-2]) - top) <= 2
    assert abs(float(re.fullmatch(r"rotate\((-?\d+)\)", day["lit"]["transform"]).group(1)) - (57.43 - 90)) <= 4
    down = render(node, "2026-11-09T06:00:00Z")               # the new moon, far below the horizon at midnight
    assert down["moon"]["attrs"].get("hidden") == "" and down["moon"]["css"] == {} and down["lit"] == {}
    for place in (None, ("", ""), ("north", "west"), ("136.53", "-87.36")):      # no place on the page: no moon
        none = render(node, "2026-11-25T05:30:00Z", place=place)
        assert none["moon"]["attrs"].get("hidden") == "" and none["made"] == [], place


def test_a_thin_crescent_is_drawn_as_a_visible_sliver(node):
    """A day and a half after new the moon is about 3% lit: the drawing shows 6%, never less, so the sliver can be
    seen."""
    thin = render(node, "2026-11-10T22:30:00Z")
    assert "hidden" not in thin["moon"]["attrs"]
    assert thin["lit"]["d"] == "M0 -10A10 10 0 0 1 0 10A8.8 10 0 0 0 0 -10Z"       # 6%: the terminator at 0.88 r


def test_the_moon_is_clarksvilles_whatever_the_viewers_clock_and_the_sun_is_still_the_viewers(node):
    """The same instant seen from Chicago time and from Brisbane time: the same moon; the sun follows each clock."""
    here, there = render(node, "2026-11-25T05:30:00Z"), render(node, "2026-11-25T05:30:00Z", "Australia/Brisbane")
    assert here["moon"]["css"] == there["moon"]["css"] and here["lit"] == there["lit"]
    assert float(here["sun"]["--sun-alt"]) < 0 < float(there["sun"]["--sun-alt"])      # 11:30 PM here, 3:30 PM there
    assert there["moon"]["attrs"]["data-day"] == ""           # paler beside the sun that viewer's page draws


LONG_OPEN_PROBE = r"""
// A 1280 by 146 sky band with a 190px sun at the right of the page column and a 40px moon; the clock can be moved.
const RealDate = Date; let nowMs = 0;
global.Date = class extends RealDate { constructor(...a) { a.length ? super(...a) : super(nowMs); }
  static now() { return nowMs; } };
const page = () => {
  const els = {};
  const node = () => { const n = { attrs: {}, css: {}, kids: [],
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    setAttribute(k, v) { this.attrs[k] = v; if (k === "id") { els[v] = this; } },
    removeAttribute(k) { delete this.attrs[k]; }, appendChild(c) { this.kids.push(c); } };
    n.style = { setProperty(k, v) { n.css[k] = v; }, removeProperty(k) { delete n.css[k]; } }; return n; };
  const sun = (els["sky-sun"] = node()), moon = (els["sky-moon"] = node());
  sun.offsetWidth = 190; sun.offsetLeft = 946;
  moon.attrs.hidden = ""; moon.attrs["data-lat"] = "36.53"; moon.attrs["data-lon"] = "-87.36"; moon.offsetWidth = 40;
  moon.parentNode = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 1280, height: 146 }) };
  global.document = { hidden: false, getElementById: id => els[id] || null, querySelectorAll: () => [],
    createElementNS: () => node() };
  return () => ({ sunAlt: sun.css["--sun-alt"], day: "data-day" in moon.attrs, hidden: "hidden" in moon.attrs,
                  left: parseFloat(moon.css["--moon-left"]), top: parseFloat(moon.css["--moon-top"]) });
};
global.window = global; global.innerWidth = 1280;
global.getComputedStyle = () => ({ getPropertyValue: () => "0.85" });
const sky = require(process.argv[1]);
const [first, later] = JSON.parse(process.argv[2]).map(t => RealDate.parse(t));
let state = page(); nowMs = first; sky.render(); const opened = state();
global.document.hidden = true; nowMs = later; sky.tick(); const whileHidden = state();   // a hidden tab draws nothing
global.document.hidden = false; sky.tick(); const ticked = state();
state = page(); nowMs = later; sky.render(); const fresh = state();                       // a page opened at `later`
console.log(JSON.stringify({ opened, whileHidden, ticked, fresh }));
"""


def long_open(node, first, later):
    res = subprocess.run([node, "-e", LONG_OPEN_PROBE, str(SKY_JS), json.dumps([first, later])], capture_output=True,
                         text=True, timeout=60, env={"TZ": "America/Chicago", "PATH": str(Path(node).parent)})
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_a_tab_left_open_keeps_the_drawn_sun_and_the_moon_in_step(node):
    """Review, moon/stale-sun-alt: opened at 3 PM and still open at 7:30 PM. The timer used to move only the moon, so
    the page kept its afternoon sun while the moon was placed as if the sun had set, and could sit on the disc. The
    timer now redraws the whole sky: after it the drawn sun and the moon are exactly what a page opened at 7:30 PM
    shows. While the tab is hidden nothing is redrawn."""
    r = long_open(node, "2026-11-20T21:00:00Z", "2026-11-21T01:30:00Z")        # 3 PM and 7:30 PM in Clarksville
    opened, ticked = r["opened"], r["ticked"]
    assert float(opened["sunAlt"]) > 0.5 and opened["day"] and not opened["hidden"]
    assert opened["left"] + 40 <= 946 - 48                    # the sun is up: the moon is left of its outer ring
    assert r["whileHidden"] == opened
    assert ticked == r["fresh"] and ticked != opened
    assert float(ticked["sunAlt"]) < 0 and not ticked["day"] and not ticked["hidden"]   # the drawn sun has set


def test_by_night_the_moon_keeps_clear_of_the_suns_ring_above_the_horizon(node):
    """Review, moon/night-sun-ring: with the sun down its outer ring still shows about 8px over the horizon at 1280
    (the disc sits 40px under it, the ring is 48px wide). A low moon over the sun's column stays above that ring."""
    r = long_open(node, "2026-08-24T07:00:00Z", "2026-08-24T07:00:00Z")["opened"]   # 2 AM, the moon 4 degrees up, west
    assert float(r["sunAlt"]) < 0 and not r["hidden"]
    assert 946 - 48 < r["left"] + 40 and r["left"] < 946 + 190 + 48           # over the sun's column
    ring_top = 146 + 0.25 * 0.85 * 190 - 48                                   # 138.4: where the ring starts
    assert r["top"] + 40 <= ring_top and r["top"] + 40 >= ring_top - 8        # just above it, still near the horizon


def test_sun_code_is_untouched_and_the_script_stays_on_the_device():
    src = SKY_JS.read_text(encoding="utf-8")
    assert "var RISE = 6, SET = 19, NIGHT = -0.25;" in src
    assert "return Math.round(Math.sin((hours - RISE) / (SET - RISE) * Math.PI) * 1000) / 1000;" in src
    assert 'parseFloat(el.getAttribute("data-lat"))' in src and "36.5" not in src     # the place comes from the page
    for word in ("fetch(", "XMLHttpRequest", "sendBeacon", "localStorage", "sessionStorage", "cookie", "geolocation",
                 "import(", "WebSocket", "EventSource"):
        assert word not in src, word
    # the timer and a tab coming back into view redraw the whole sky (review: moon/stale-sun-alt, moon/visibility),
    # and nothing while the tab is hidden
    tick = src[src.index("function tick()"):src.index("/* the same moon put back")]
    assert "if (!doc || doc.hidden) { return; }\n    render();" in tick
    assert "root.setInterval(tick, 300000)" in src
    assert 'root.document.addEventListener("visibilitychange", tick)' in src
    assert 'root.addEventListener("resize"' in src and "fonts.ready.then(replace" in src     # put back after a re-layout


def test_markup_is_decoration_hidden_until_drawn(site):  # noqa: F811
    html = (site / "index.html").read_text(encoding="utf-8")
    moon = ('<div class="sky-moon-frame" aria-hidden="true"><span class="sky-moon" id="sky-moon" data-lat="36.53"'
            ' data-lon="-87.36" hidden></span></div>')
    assert html.count(moon) == 1 and html.count('id="sky-moon"') == 1
    assert html.index('id="sky-sun"') < html.index(moon) < html.index('<div class="masthead">')
    for page in site.rglob("*.html"):                         # the moon is wherever the sun is, and nowhere else
        text = page.read_text(encoding="utf-8")
        assert ('id="sky-moon"' in text) == ('id="sky-sun"' in text), page


def test_moon_styles_are_quiet_and_do_not_animate():
    assert ".sky-moon[hidden] { display: none; }" in CSS
    assert ".sky-moon-frame { position: absolute; inset: 0; pointer-events: none; }" in CSS
    assert "--moon-size: clamp(28px, 3.1vw, 40px);" in CSS            # 28px on a phone, 40px at 1280
    assert "left: var(--moon-left, 0); top: var(--moon-top, 0);" in CSS
    rules = "".join(re.findall(r"\.(?:sky-moon|moon-)[^{]*\{[^}]*\}", CSS))
    assert "transition" not in rules and "animation" not in rules
    assert "box-shadow: 0 0 0 calc(var(--moon-size) * .14) color-mix(in srgb, var(--moon-ring) 30%, transparent)" in rules
    # the moon never sits behind words (the browser test below), so the header's text needs no halo
    assert "--moon-halo" not in CSS and "text-shadow" not in CSS[CSS.index(".sky-sun-frame"):CSS.index(".sky-hero {")]
    for theme in (LIGHT, DARK):                               # the lit part or its edge stands off the sky
        assert _ratio(theme["--moon-edge"], theme["--sky"]) >= 2 or _ratio(theme["--moon"], theme["--sky"]) >= 3
    assert LIGHT["--moon"] == "#FFFFFF" and _ratio(DARK["--moon"], DARK["--sky"]) >= 3
    # the two dark blocks (the system setting and the explicit choice) carry the same moon
    assert CSS.count("--moon: #C3CCDE; --moon-edge: #7C86A3; --moon-ring: #A9BDE6;") == 2


CLEAR_PROBE = r"""
const path = require('path');
let pw;
const roots = [...(process.env.NODE_PATH || '').split(path.delimiter).filter(Boolean), '/opt/node22/lib/node_modules'];
for (const r of ['', ...roots]) {
  try { pw = require(r ? path.join(r, 'playwright') : 'playwright'); break; } catch (e) { /* next */ }
}
(async () => {
  const [site, rels, instants] = [process.argv[2], JSON.parse(process.argv[3]), JSON.parse(process.argv[4])];
  const browser = await pw.chromium.launch();
  const out = [];
  for (const [width, height] of [[375, 667], [1280, 800]]) for (const rel of rels) for (const iso of instants) {
    const ctx = await browser.newContext({ viewport: { width, height }, timezoneId: 'America/Chicago' });
    const page = await ctx.newPage();
    await page.clock.setFixedTime(new Date(iso));
    await page.goto('file://' + path.join(site, rel));
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(1600);                           // the sun has slid into place
    const at = await page.evaluate(() => {
      const box = r => ({ left: r.left, top: r.top, right: r.right, bottom: r.bottom });
      const words = n => { const g = document.createRange(); g.selectNodeContents(n);
        return box(g.getBoundingClientRect()); };
      const moon = document.getElementById('sky-moon'), sun = document.getElementById('sky-sun');
      const header = box(document.querySelector('.site-header').getBoundingClientRect());
      const ring = parseFloat(getComputedStyle(moon).width) * 0.14;
      const texts = {};
      for (const [name, sel] of [['plate', '.site-header .site-name'], ['tag', '.site-header .unofficial-tag'],
                                 ['date', '#sky-hero .sky-day']]) {
        const n = document.querySelector(sel); if (n) { texts[name] = words(n); }
      }
      texts.menu = box(document.getElementById('nav-open').getBoundingClientRect());
      const s = box(sun.getBoundingClientRect());
      return { hidden: moon.hasAttribute('hidden'), moon: box(moon.getBoundingClientRect()), ring, header, texts,
               size: parseFloat(getComputedStyle(moon).width), kids: moon.querySelectorAll('svg').length,
               sun: s.top < header.bottom ? { ...s, bottom: header.bottom } : null,
               sunRing: Math.max(18, Math.min(48, innerWidth * 0.045)), sunBox: s,
               hscroll: document.documentElement.scrollWidth > innerWidth };
    });
    out.push({ width, rel, iso, ...at });
    await ctx.close();
  }
  await browser.close();
  console.log(JSON.stringify(out));
})();
"""


def _browser_ok():
    return bool(shutil.which("node")) and (os.path.exists("/opt/pw-browsers") or bool(shutil.which("playwright")))


def _hits(a, b):
    return a["left"] < b["right"] and b["left"] < a["right"] and a["top"] < b["bottom"] and b["top"] < a["bottom"]


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_the_moon_never_covers_the_headers_words_or_the_sun_in_a_browser(site, tmp_path):  # noqa: F811
    """Manager's design call, 2026-11-14: the moon sits in open sky only. At 375 and 1280, on the landing and on a
    body's page, at instants with the moon high, low, east, west, by day and by night: the moon's box with its ring
    touches no word of the header (name plate, tag, date line, Menu button) and not the sun's disc (nor, at 1280 by
    night, the ring the set sun still shows over the horizon), stays inside the band, is 28px on the phone and about
    40px wide, and the page does not scroll sideways."""
    body = next(str(p.relative_to(site)) for p in sorted(site.rglob("*.html"))
                if p.name != "index.html" and 'id="sky-moon"' in p.read_text(encoding="utf-8"))
    instants = ["2026-11-25T05:30:00Z", "2026-11-12T23:20:00Z", "2026-11-20T21:30:00Z", "2026-12-01T13:30:00Z",
                "2026-11-27T03:00:00Z", "2026-03-26T00:30:00Z", "2026-08-24T07:00:00Z", "2026-11-22T18:30:00Z"]
    script = tmp_path / "clear.js"
    script.write_text(CLEAR_PROBE, encoding="utf-8")
    res = subprocess.run(["node", str(script), str(site), json.dumps(["index.html", body]), json.dumps(instants)],
                         capture_output=True, text=True, timeout=600)
    assert res.returncode == 0, res.stderr
    rows = json.loads(res.stdout)
    assert len(rows) == 2 * 2 * len(instants)
    for r in rows:
        where = (r["width"], r["rel"], r["iso"])
        assert not r["hscroll"], where
        if r["iso"] == "2026-11-22T18:30:00Z":                # 12:30 PM, the moon not yet risen
            assert r["hidden"], where
            continue
        assert not r["hidden"] and r["kids"] == 1, where
        assert abs(r["size"] - (28 if r["width"] == 375 else 39.7)) < 0.5, where
        m, ring = r["moon"], r["ring"]
        halo = {"left": m["left"] - ring, "top": m["top"] - ring, "right": m["right"] + ring,
                "bottom": m["bottom"] + ring}
        for name, box in r["texts"].items():
            assert not _hits(halo, box), (where, name, halo, box)
        if r["sun"]:
            assert not _hits(m, r["sun"]), (where, m, r["sun"])
        elif r["width"] == 1280:                              # by night: the sun's outer ring over the horizon
            s, w = r["sunBox"], r["sunRing"]
            ring = {"left": s["left"] - w, "top": s["top"] - w, "right": s["right"] + w, "bottom": s["bottom"] + w}
            assert ring["top"] < r["header"]["bottom"] and not _hits(m, ring), (where, m, ring)
        h = r["header"]
        assert h["left"] <= m["left"] and m["right"] <= h["right"], where
        assert h["top"] <= m["top"] and m["bottom"] <= h["bottom"], where
