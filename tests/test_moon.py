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


RENDER_PROBE = r"""
const RealDate = Date, fixed = RealDate.parse(process.argv[2]);
global.Date = class extends RealDate { constructor(...a) { a.length ? super(...a) : super(fixed); }
  static now() { return fixed; } };
const els = {}, made = [];
const node = (tag, ns) => ({ tag, ns, attrs: {}, css: {}, kids: [], style: { setProperty(k, v) { this.css[k] = v; } },
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
  setAttribute(k, v) { this.attrs[k] = v; if (k === "id") { els[v] = this; } },
  removeAttribute(k) { delete this.attrs[k]; },
  appendChild(c) { this.kids.push(c); } });
const mk = id => { const n = node("span"); n.style.setProperty = (k, v) => { n.css[k] = v; }; return (els[id] = n); };
mk("sky-sun"); const moon = mk("sky-moon"); moon.attrs.hidden = "";
const place = JSON.parse(process.argv[3]);
if (place) { moon.attrs["data-lat"] = place[0]; moon.attrs["data-lon"] = place[1]; }
global.window = global;
global.document = { getElementById: id => els[id] || null,
  createElementNS: (ns, tag) => { const n = node(tag, ns); made.push(tag); return n; } };
const sky = require(process.argv[1]);
sky.render(); sky.render();                                    // twice: the drawing is made once
const lit = els["sky-moon-lit"];
console.log(JSON.stringify({ sun: els["sky-sun"].css, moon: { attrs: moon.attrs, css: moon.css },
  lit: lit ? lit.attrs : {}, made,
  tree: moon.kids.map(k => [k.tag, k.ns, k.attrs, k.kids.map(c => [c.tag, c.attrs["class"]])]) }));
"""


def render(node, when, tz="America/Chicago", place=("36.53", "-87.36")):
    res = subprocess.run([node, "-e", RENDER_PROBE, str(SKY_JS), when, json.dumps(place)], capture_output=True, text=True,
                         timeout=60,
                         env={"TZ": tz, "PATH": str(Path(node).parent)})
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_render_places_the_moon_and_shows_it_only_above_the_horizon(node):
    up = render(node, "2026-11-25T05:30:00Z")                 # the full moon, 77 degrees up in the south-east at night
    assert "hidden" not in up["moon"]["attrs"] and "data-day" not in up["moon"]["attrs"]
    assert up["made"] == ["svg", "circle", "path"]            # drawn once, as SVG, by the script
    assert up["tree"] == [["svg", "http://www.w3.org/2000/svg", {"viewBox": "-12 -12 24 24", "focusable": "false"},
                           [["circle", "moon-disc"], ["path", "moon-lit"]]]]
    assert abs(float(up["moon"]["css"]["--moon-alt"]) - 76.98 / 90) < 0.01
    assert abs(float(up["moon"]["css"]["--moon-x"]) - (136.004 - 60) / 240) < 0.01
    assert up["lit"]["d"].startswith("M0 -10A10 10 0 0 1 0 10A9.") and up["lit"]["d"].endswith(" 0 0 1 0 -10Z")
    day = render(node, "2026-11-20T21:30:00Z")                # 3:30 PM in Clarksville: the gibbous moon rising
    assert "hidden" not in day["moon"]["attrs"] and day["moon"]["attrs"]["data-day"] == ""    # paler by day
    assert float(day["moon"]["css"]["--moon-x"]) < 0.2 and float(day["moon"]["css"]["--moon-alt"]) < 0.25
    assert abs(float(re.fullmatch(r"rotate\((-?\d+)\)", day["lit"]["transform"]).group(1)) - (57.43 - 90)) <= 4
    down = render(node, "2026-11-09T06:00:00Z")               # the new moon, far below the horizon at midnight
    assert down["moon"]["attrs"].get("hidden") == "" and down["moon"]["css"] == {} and down["lit"] == {}
    for place in (None, ("", ""), ("north", "west"), ("136.53", "-87.36")):      # no place on the page: no moon
        none = render(node, "2026-11-25T05:30:00Z", place=place)
        assert none["moon"]["attrs"].get("hidden") == "" and none["made"] == [], place


def test_the_moon_is_clarksvilles_whatever_the_viewers_clock_and_the_sun_is_still_the_viewers(node):
    """The same instant seen from Chicago time and from Brisbane time: the same moon; the sun follows each clock."""
    here, there = render(node, "2026-11-25T05:30:00Z"), render(node, "2026-11-25T05:30:00Z", "Australia/Brisbane")
    assert here["moon"]["css"] == there["moon"]["css"] and here["lit"] == there["lit"]
    assert float(here["sun"]["--sun-alt"]) < 0 < float(there["sun"]["--sun-alt"])      # 11:30 PM here, 3:30 PM there
    assert there["moon"]["attrs"]["data-day"] == ""           # paler beside the sun that viewer's page draws


def test_sun_code_is_untouched_and_the_script_stays_on_the_device():
    src = SKY_JS.read_text(encoding="utf-8")
    assert "var RISE = 6, SET = 19, NIGHT = -0.25;" in src
    assert "return Math.round(Math.sin((hours - RISE) / (SET - RISE) * Math.PI) * 1000) / 1000;" in src
    assert 'parseFloat(el.getAttribute("data-lat"))' in src and "36.5" not in src     # the place comes from the page
    for word in ("fetch(", "XMLHttpRequest", "sendBeacon", "localStorage", "sessionStorage", "cookie", "geolocation",
                 "import(", "WebSocket", "EventSource"):
        assert word not in src, word
    # the timer redraws the moon only: the sun and the date line keep to page load and pageshow
    tick = src[src.index("function tick()"):src.index("var api =")]
    assert "renderMoon(" in tick and "sky-sun" not in tick and "render()" not in tick
    assert "root.setInterval(tick, 300000)" in src


def test_markup_is_decoration_hidden_until_drawn(site):  # noqa: F811
    html = (site / "index.html").read_text(encoding="utf-8")
    moon = ('<div class="sky-moon-frame" aria-hidden="true"><span class="sky-moon" id="sky-moon" data-lat="36.53"'
            ' data-lon="-87.36" hidden></span></div>')
    assert html.count(moon) == 1 and html.count('id="sky-moon"') == 1
    assert html.index('id="sky-sun"') < html.index(moon) < html.index('<div class="masthead">')
    for page in site.rglob("*.html"):                         # the moon is wherever the sun is, and nowhere else
        text = page.read_text(encoding="utf-8")
        assert ('id="sky-moon"' in text) == ('id="sky-sun"' in text), page


def test_moon_styles_keep_the_headers_words_readable_and_do_not_animate():
    assert ".sky-moon[hidden] { display: none; }" in CSS
    assert ".sky-moon-frame {\n  position: absolute; top: 0; bottom: 0; pointer-events: none;" in CSS
    rules = "".join(re.findall(r"\.(?:sky-moon|moon-)[^{]*\{[^}]*\}", CSS))
    assert "transition" not in rules and "animation" not in rules
    # light: the moon is white, lighter than the sky, so the header's ink and muted words pass on it as they are
    assert LIGHT["--moon"] == "#FFFFFF" and "--moon-halo" not in LIGHT
    for token in ("--fg", "--muted"):
        assert _ratio(LIGHT[token], LIGHT["--moon"]) >= 4.5
    # dark: the lit moon is light, so the header's words carry a halo of the sky's own color over it
    assert DARK["--moon-halo"] == DARK["--sky"]
    assert re.search(r"\.has-sky \.brand, \.has-sky \.sky-hero \{\s*text-shadow: 0 0 1px var\(--moon-halo, transparent\)",
                     CSS)
    for token in ("--fg", "--muted"):
        assert _ratio(DARK[token], DARK["--moon-halo"]) >= 4.5
    for theme in (LIGHT, DARK):
        assert _ratio(theme["--moon-edge"], theme["--sky"]) >= 2 or _ratio(theme["--moon"], theme["--sky"]) >= 3
    # the two dark blocks (the system setting and the explicit choice) carry the same moon
    assert CSS.count("--moon: #C3CCDE; --moon-edge: #7C86A3; --moon-halo: #15294F;") == 2
