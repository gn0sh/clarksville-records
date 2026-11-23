"""The sky in the header (docs/design/daylight "The moon", "One header, and the sun or the moon"): static/sky.js works
out where the sun and the moon really are over Clarksville (36.53 N, 87.36 W; config/site.yml sky_place, read from
the page) at an instant, the moon's lit fraction, whether it is waxing and which way its bright edge points. It
draws the sun while the sun is up and the moon only while the sun is down, never both (owner, 2026-11-18), and of
the moon only the lit part: no dark disc, and nothing at new moon.

REFERENCE holds values from an independent library, PyEphem 4.2.1 (the XEphem/libastro engine), worked out when
this was written: an Observer at 36.53, -87.36, elevation 0, pressure 0 (no bending by the air), `Moon(observer)`
`.alt`, `.az` and `.phase`; waxing from the moon's ecliptic longitude less the sun's; the bright edge's direction
from PyEphem's own altitudes and azimuths of the moon and the sun (the bearing from one to the other on the sky,
clockwise from straight up), which is a different route from the script's. Measured against 2,670 instants spread
through 2026 (every 197 minutes): altitude within 0.37 degrees, direction within 0.36 degrees on the sky, lit
fraction within 0.002, bright edge within 3.1 degrees wherever 2% to 98% of the disc is lit, and waxing or waning
never wrong outside the hour or so around new and full.

SUN_REFERENCE and SUN_RISE_SET are PyEphem's too (2026-11-18): the same Observer's `Sun(observer).alt`, and
`next_rising` / `next_setting` with the horizon at -0:34 and no pressure (the almanac's sunrise and sunset: the top
edge on the horizon). Against the same 2,670 instants the script's sun is within 0.012 degrees in altitude, and its
sunrise and sunset (altitude -0.833) within 3 seconds on the six days below."""
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

# (instant UTC, the sun's altitude in degrees): PyEphem 4.2.1, the same observer.
SUN_REFERENCE = [
    ("2026-11-18T19:30:00Z", 27.821), ("2026-11-18T17:36:00Z", 34.121), ("2026-06-21T17:52:00Z", 76.906),
    ("2026-12-21T17:48:00Z", 30.03), ("2026-03-20T13:00:00Z", 12.605), ("2026-09-22T23:00:00Z", 8.429),
    ("2026-11-25T05:30:00Z", -74.158), ("2026-01-15T14:00:00Z", 9.457), ("2026-07-04T01:00:00Z", 1.18),
    ("2026-11-12T23:20:00Z", -7.901), ("2026-11-20T21:30:00Z", 10.98), ("2026-12-01T13:30:00Z", 7.306),
]
# (day, sunrise UTC, sunset UTC): PyEphem 4.2.1, the top edge on the horizon with 34' of bending.
SUN_RISE_SET = [
    ("2026-01-15", "2026-01-15T13:00:30Z", "2026-01-15T22:57:36Z"),
    ("2026-03-20", "2026-03-20T11:52:52Z", "2026-03-21T00:01:19Z"),
    ("2026-06-21", "2026-06-21T10:31:33Z", "2026-06-22T01:11:03Z"),
    ("2026-09-22", "2026-09-22T11:37:26Z", "2026-09-22T23:46:08Z"),
    ("2026-11-18", "2026-11-18T12:30:11Z", "2026-11-18T22:38:46Z"),
    ("2026-12-21", "2026-12-21T12:57:40Z", "2026-12-21T22:37:33Z"),
]
SUN_ALT_TOL, MINUTE = 0.1, 60000                                    # degrees; milliseconds


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


def test_sun_altitude_matches_the_reference(node):
    probe = ("const s = require(process.argv[1]);"
             "console.log(JSON.stringify(JSON.parse(process.argv[2]).map(t => s.sun(Date.parse(t), %s, %s))));"
             % (LAT, LON))
    got = run(node, probe, json.dumps([t for t, _ in SUN_REFERENCE]))
    for (when, alt), sun in zip(SUN_REFERENCE, got):
        assert abs(sun["alt"] - alt) <= SUN_ALT_TOL, (when, sun["alt"], alt)
        assert 29.5 < sun["noon"] < 77.5, when                # between the winter and the summer noon at 36.53 north


def test_the_drawn_sun_is_up_from_clarksvilles_sunrise_to_its_sunset_and_highest_at_noon(node):
    """Up means the almanac's sunrise to sunset. Two minutes inside the day the sun is drawn, low; two minutes
    outside it is down (NIGHT, under the horizon); at local noon it is at the top of its arc, in winter as in summer."""
    probe = ("const s = require(process.argv[1]);"
             "console.log(JSON.stringify(JSON.parse(process.argv[2]).map(t => s.sunAltitude(t, %s, %s))));" % (LAT, LON))
    from datetime import datetime, timezone

    def ms(iso):
        return int(datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp() * 1000)
    for day, rise, set_ in SUN_RISE_SET:
        r, t = ms(rise), ms(set_)
        before, after_rise, noon, before_set, after = run(node, probe, json.dumps(
            [r - 2 * MINUTE, r + 2 * MINUTE, (r + t) // 2, t - 2 * MINUTE, t + 2 * MINUTE]))
        assert before == after == -0.25, (day, before, after)
        assert 0 <= after_rise < 0.05 and 0 <= before_set < 0.05, (day, after_rise, before_set)
        assert noon > 0.99, (day, noon)
    assert run(node, "const s = require(process.argv[1]); console.log(JSON.stringify([s.SUN_UP, s.NIGHT, s.NEW]));") \
        == [-0.833, -0.25, 0.01]


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
    assert half == arc + "Z"                                              # a straight line at the quarters
    assert new == arc + "A10 10 0 0 0 0 -10Z" and full == arc + "A10 10 0 0 1 0 -10Z"   # nothing lit, all lit


def _edges(d, steps=360):
    """The edges of an SVG path of M, A, L and Z commands, each a list of (x, y) points along it, worked by the SVG
    rules apart from the script: an arc from its end points, radii, x-axis turn of 0 and two flags (SVG 1.1, F.6.5);
    Z is the straight line back to the start, when there is any way to go."""
    tokens = re.findall(r"[MALZ]|-?\d+(?:\.\d+)?(?:e-?\d+)?", d)
    edges, at, start, i = [], None, None, 0
    while i < len(tokens):
        cmd = tokens[i]
        if cmd == "M":
            at = start = (float(tokens[i + 1]), float(tokens[i + 2]))
            i += 3
        elif cmd in ("L", "Z"):
            to = start if cmd == "Z" else (float(tokens[i + 1]), float(tokens[i + 2]))
            if math.dist(at, to) > 1e-9:                      # a Z where the path is already home draws nothing
                edges.append(("line", [(at[0] + (to[0] - at[0]) * s / steps, at[1] + (to[1] - at[1]) * s / steps)
                                       for s in range(steps + 1)]))
            at, i = to, i + (1 if cmd == "Z" else 3)
        else:
            assert cmd == "A", d
            rx, ry, turn, large, sweep, x2, y2 = (float(v) for v in tokens[i + 1:i + 8])
            assert turn == 0 and rx > 0 and ry > 0, d
            (x1, y1), i = at, i + 8
            hx, hy = (x1 - x2) / 2, (y1 - y2) / 2
            grow = math.sqrt(max(1, hx * hx / (rx * rx) + hy * hy / (ry * ry)))       # radii too small are scaled up
            rx, ry = rx * grow, ry * grow
            under = rx * rx * hy * hy + ry * ry * hx * hx
            coef = math.sqrt(max(0, (rx * rx * ry * ry - under) / under)) * (1 if large != sweep else -1)
            cx_, cy_ = coef * rx * hy / ry, -coef * ry * hx / rx
            cx, cy = cx_ + (x1 + x2) / 2, cy_ + (y1 + y2) / 2
            a1 = math.atan2((hy - cy_) / ry, (hx - cx_) / rx)
            da = math.atan2((-hy - cy_) / ry, (-hx - cx_) / rx) - a1
            if sweep == 0 and da > 0:
                da -= 2 * math.pi
            if sweep == 1 and da < 0:
                da += 2 * math.pi
            edges.append(("arc", [(cx + rx * math.cos(a1 + da * s / steps), cy + ry * math.sin(a1 + da * s / steps))
                                  for s in range(steps + 1)]))
            at = (x2, y2)
    return edges


def test_the_outer_edge_is_the_moons_own_circle_and_the_terminator_is_straight_at_half(node):
    """Manager review, 2026-11-18 (moon-shape/terminator): whatever the phase, the drawn shape's outer edge is half
    of one circle of radius r, from pole to pole; the terminator joins the same two poles, as half an ellipse r high
    and r * |1 - 2k| wide that bows toward the bright edge for a crescent and away from it past half, and as a
    straight line at half; nothing is drawn outside the circle; and the drawn area is the lit share of the disc. The
    points are worked from the path by the SVG rules here, not by the script."""
    cases = [(k, 10) for k in (0.01, 0.029, 0.124, 0.25, 0.4, 0.493, 0.5, 0.507, 0.553, 0.644, 0.75, 0.841, 0.993, 1)]
    cases += [(0.2, 7), (0.5, 7), (0.8, 7)]
    paths = run(node, "const s = require(process.argv[1]);"
                      "console.log(JSON.stringify(JSON.parse(process.argv[2]).map(c => s.moonPath(c[0], c[1]))));",
                json.dumps(cases))
    for (k, r), d in zip(cases, paths):
        edges = _edges(d)
        assert len(edges) == 2, (k, d)
        (kind, limb), (shape, term) = edges
        # the limb: the right half of the circle of radius r, top pole to bottom pole through the bright side
        assert kind == "arc" and math.dist(limb[0], (0, -r)) < 1e-9, (k, d)
        assert math.dist(limb[-1], (0, r)) < 1e-9 and math.dist(limb[len(limb) // 2], (r, 0)) < 1e-9, (k, d)
        assert all(abs(math.hypot(x, y) - r) < 1e-9 and x > -1e-9 for x, y in limb), (k, d)
        # the terminator: back from the bottom pole to the top pole
        assert math.dist(term[0], (0, r)) < 1e-9 and math.dist(term[-1], (0, -r)) < 1e-9, (k, d)
        wide = r * abs(1 - 2 * k)
        for x, y in term:
            assert math.hypot(x, y) < r + 1e-9, (k, d)                              # never outside the moon's circle
            assert abs(abs(x) - wide * math.sqrt(max(0, 1 - (y / r) ** 2))) < 0.006, (k, d, x, y)   # the half ellipse
            assert (x > -1e-9) if k < 0.5 else (x < 1e-9), (k, d, x, y)             # crescent: toward the bright edge
        if k == 0.5:
            assert shape == "line" and all(x == 0 for x, _ in term), d              # half lit: a straight line
        if abs(k - 0.5) < 0.01:
            assert max(abs(x) for x, _ in term) <= 0.015 * r, (k, d)                # and all but straight beside it
        # the drawn area is the lit share of the disc (the shoelace sum over the outline)
        pts = limb + term
        area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))) / 2
        assert abs(area / (math.pi * r * r) - k) < 0.002, (k, d, area)


def test_free_rect_is_the_largest_open_rectangle_clear_of_every_block(node):
    """The moon sits only in open sky: the largest rectangle of the band that touches no block (the header's words
    and the Menu column) and can hold the moon; none when the band has no such room."""
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
console.log(JSON.stringify({ sun: els["sky-sun"].css, sunAt: els["sky-sun"].attrs["data-at"],
  moon: { attrs: moon.attrs, css: moon.css },
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


def shown(r):
    return "hidden" not in r["moon"]["attrs"]


def test_render_places_the_moon_and_shows_it_only_at_night_above_the_horizon(node):
    up = render(node, "2026-11-25T05:30:00Z")                 # the full moon, 77 degrees up in the south-east at night
    assert shown(up) and up["sunAt"] == "down" and float(up["sun"]["--sun-alt"]) < 0
    assert up["made"] == ["svg", "path"]                      # drawn once, as SVG, by the script: the lit part only
    assert up["tree"] == [["svg", "http://www.w3.org/2000/svg", {"viewBox": "-10.5 -10.5 21 21", "focusable": "false"},
                           [["path", "moon-lit"]]]]
    left, top = spot(76.98, 136.004)                          # real altitude and direction, inside the open sky
    assert set(up["moon"]["css"]) == {"--moon-left", "--moon-top"} and set(up["moon"]["attrs"]) == {"data-lat", "data-lon"}
    assert up["moon"]["css"]["--moon-left"].endswith("px")
    assert abs(float(up["moon"]["css"]["--moon-left"][:-2]) - left) <= 8      # this high, 1 degree of azimuth is 5px
    assert abs(float(up["moon"]["css"]["--moon-top"][:-2]) - top) <= 2
    assert up["lit"]["d"].startswith("M0 -10A10 10 0 0 1 0 10A9.") and up["lit"]["d"].endswith(" 0 0 1 0 -10Z")
    low = render(node, "2026-12-01T06:08:00Z")                # midnight: the last-quarter moon just up in the east
    assert shown(low) and low["sunAt"] == "down"
    left, top = spot(6.873, 87.128)                           # low in the east: low and to the left
    assert abs(float(low["moon"]["css"]["--moon-left"][:-2]) - left) <= 3
    assert abs(float(low["moon"]["css"]["--moon-top"][:-2]) - top) <= 2
    # half lit: the terminator is a straight line
    assert re.fullmatch(r"M0 -10A10 10 0 0 1 0 10A0\.0\d 10 0 0 1 0 -10Z", low["lit"]["d"])
    assert abs(float(re.fullmatch(r"rotate\((-?\d+)\)", low["lit"]["transform"]).group(1)) - (-165.92 - 90)) <= 4
    west = render(node, "2026-08-24T07:00:00Z")               # 2 AM: 4 degrees up in the west. No sun is drawn, so
    left, top = spot(4.007, 232.406)                          # the moon may stand low on the side the sun uses by day
    assert shown(west) and abs(float(west["moon"]["css"]["--moon-left"][:-2]) - left) <= 3
    assert abs(float(west["moon"]["css"]["--moon-top"][:-2]) - top) <= 2
    down = render(node, "2026-11-09T06:00:00Z")               # the new moon, far below the horizon at midnight
    assert not shown(down) and down["moon"]["css"] == {} and down["lit"] == {} and down["sunAt"] == "down"
    for place in (None, ("", ""), ("north", "west"), ("136.53", "-87.36")):      # no place on the page: no moon
        none = render(node, "2026-11-25T05:30:00Z", place=place)
        assert not shown(none) and none["made"] == [], place


def test_the_sun_and_the_moon_are_never_drawn_together(node):
    """Owner, 2026-11-18: "The moon and sun should never be on the page at the same time." By day the sun is drawn
    and the moon is not, even when the real moon is up; after sunset the sun is not drawn (data-at="down", which
    the stylesheet hides: no disc, no ring) and the moon is, if it is up; with neither up the sky is empty."""
    day = render(node, "2026-11-20T21:30:00Z")                # 3:30 PM in Clarksville: the gibbous moon is up, 18 degrees
    assert day["sunAt"] == "up" and 0.2 < float(day["sun"]["--sun-alt"]) < 0.5       # the sun 11 degrees up of 33
    assert not shown(day) and day["made"] == [] and day["moon"]["css"] == {}         # no moon by day
    morning = render(node, "2026-12-01T13:30:00Z")            # 7:30 AM: the last-quarter moon high in the south-west
    assert morning["sunAt"] == "up" and not shown(morning)
    dusk = render(node, "2026-11-12T23:20:00Z")               # 5:20 PM, 40 minutes after sunset: the crescent
    assert dusk["sunAt"] == "down" and float(dusk["sun"]["--sun-alt"]) == -0.25 and shown(dusk)
    neither = render(node, "2026-11-17T11:47:00Z")            # 5:47 AM, before sunrise, the half moon long set
    assert neither["sunAt"] == "down" and not shown(neither) and neither["made"] == []     # an empty sky
    # the stylesheet draws no sun that is down, and with the script none before the script has placed it
    assert '.js .sky-sun:not([data-at]), .sky-sun[data-at="down"] { visibility: hidden; }' in CSS


SWEEP_PROBE = r"""
// The page through a whole year, every 97 minutes: what is drawn, and what the almanac says of that instant.
const RealDate = Date; let nowMs = 0;
global.Date = class extends RealDate { constructor(...a) { a.length ? super(...a) : super(nowMs); }
  static now() { return nowMs; } };
const els = {};
const node = () => { const n = { attrs: {}, css: {}, kids: [],
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
  setAttribute(k, v) { this.attrs[k] = v; if (k === "id") { els[v] = this; } },
  removeAttribute(k) { delete this.attrs[k]; }, appendChild(c) { this.kids.push(c); } };
  n.style = { setProperty(k, v) { n.css[k] = v; }, removeProperty(k) { delete n.css[k]; } }; return n; };
const sun = (els["sky-sun"] = node()), moon = (els["sky-moon"] = node());
moon.attrs.hidden = ""; moon.attrs["data-lat"] = "36.53"; moon.attrs["data-lon"] = "-87.36"; moon.offsetWidth = 40;
moon.parentNode = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 1280, height: 146 }) };
global.window = global; global.innerWidth = 1280;
global.document = { hidden: false, getElementById: id => els[id] || null, querySelectorAll: () => [],
  createElementNS: () => node() };
const sky = require(process.argv[1]);
const count = { sun: 0, moon: 0, neither: 0, both: 0, wrong: 0, newHidden: 0 };
for (nowMs = RealDate.UTC(2026, 0, 1); nowMs < RealDate.UTC(2027, 0, 1); nowMs += 97 * 60000) {
  sky.render();
  const sunUp = sun.attrs["data-at"] === "up", moonUp = !("hidden" in moon.attrs);
  const s = sky.sun(nowMs, 36.53, -87.36), m = sky.moon(nowMs, 36.53, -87.36);
  count[sunUp && moonUp ? "both" : sunUp ? "sun" : moonUp ? "moon" : "neither"] += 1;
  const drawnAlt = sun.css["--sun-alt"];
  if (sunUp !== (s.alt > -0.833) || (sunUp ? parseFloat(drawnAlt) < 0 : drawnAlt !== "-0.25")) { count.wrong += 1; }
  if (moonUp !== (!sunUp && m.alt > 0 && m.fraction >= 0.01)) { count.wrong += 1; }
  if (!sunUp && m.alt > 0 && m.fraction < 0.01) { count.newHidden += 1; }
}
console.log(JSON.stringify(count));
"""


def test_through_a_year_the_page_never_shows_both_and_shows_each_when_the_sky_does(node):
    res = subprocess.run([node, "-e", SWEEP_PROBE, str(SKY_JS)], capture_output=True, text=True, timeout=120,
                         env={"TZ": "Asia/Tokyo", "PATH": str(Path(node).parent)})       # the viewer's zone is no matter
    assert res.returncode == 0, res.stderr
    count = json.loads(res.stdout)
    assert count["both"] == 0 and count["wrong"] == 0, count
    total = count["sun"] + count["moon"] + count["neither"]
    assert total == 5419                                      # 365 days, every 97 minutes
    assert 0.48 < count["sun"] / total < 0.52                 # the sun is up half the year
    assert count["moon"] > 0.2 * total and count["neither"] > 0.2 * total, count        # each night state is common
    assert count["newHidden"] >= 1, count                     # a new moon up at night was met, and not drawn


def test_a_thin_crescent_is_drawn_thin_and_a_new_moon_not_at_all(node):
    """The lit part is drawn as it is, never padded (it used to be drawn as 6% at least): three days after new the
    moon is 3.7% lit and its terminator is at 0.926 of the radius. Under 1% lit, in the day or so around new moon,
    nothing is drawn although the moon is up and the sun is down: it cannot be seen in the real sky either."""
    thin = render(node, "2026-04-19T01:00:00Z")               # 8 PM, the sun 7 degrees down, the moon 14 degrees up
    assert shown(thin) and thin["sunAt"] == "down"
    m = re.fullmatch(r"M0 -10A10 10 0 0 1 0 10A(9\.\d+) 10 0 0 0 0 -10Z", thin["lit"]["d"])
    assert m and abs((1 - float(m.group(1)) / 10) / 2 - 0.0368) < 0.002, thin["lit"]
    new = render(node, "2026-11-08T12:15:00Z")                # 6:15 AM, before sunrise: the moon 4 degrees up, 0.8% lit
    assert new["sunAt"] == "down" and not shown(new) and new["made"] == []


def test_the_sky_is_clarksvilles_whatever_the_viewers_clock(node):
    """The same instant seen from Chicago time and from Brisbane time: the same moon and the same sun, Clarksville's
    (11:30 PM there: the sun is down, though it is mid-afternoon in Brisbane). A page with no place has no moon,
    and its sun still follows the viewer's own clock."""
    here, there = render(node, "2026-11-25T05:30:00Z"), render(node, "2026-11-25T05:30:00Z", "Australia/Brisbane")
    assert here["moon"]["css"] == there["moon"]["css"] and here["lit"] == there["lit"] and shown(here) and shown(there)
    assert here["sun"] == there["sun"] == {"--sun-alt": "-0.25"} and here["sunAt"] == there["sunAt"] == "down"
    here, there = (render(node, "2026-11-25T05:30:00Z", tz, place=None) for tz in ("America/Chicago", "Australia/Brisbane"))
    assert float(here["sun"]["--sun-alt"]) < 0 < float(there["sun"]["--sun-alt"])      # 11:30 PM here, 3:30 PM there
    assert (here["sunAt"], there["sunAt"]) == ("down", "up") and not shown(here) and not shown(there)


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
  return () => ({ sunAlt: sun.css["--sun-alt"], sunAt: sun.attrs["data-at"], hidden: "hidden" in moon.attrs,
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


def test_a_tab_left_open_across_sunset_swaps_the_sun_for_the_moon(node):
    """Review, moon/stale-sun-alt: opened at 3 PM and still open at 7:30 PM. The timer redraws the whole sky, so after
    it the page is exactly what a page opened at 7:30 PM shows: the sun gone and the moon out. At no step are both
    drawn. While the tab is hidden nothing is redrawn."""
    r = long_open(node, "2026-11-20T21:00:00Z", "2026-11-21T01:30:00Z")        # 3 PM and 7:30 PM in Clarksville
    opened, ticked = r["opened"], r["ticked"]
    assert float(opened["sunAlt"]) > 0.4 and opened["sunAt"] == "up" and opened["hidden"]     # by day: the sun only
    assert r["whileHidden"] == opened
    assert ticked == r["fresh"] and ticked != opened
    assert float(ticked["sunAlt"]) < 0 and ticked["sunAt"] == "down" and not ticked["hidden"]  # by night: the moon only
    back = long_open(node, "2026-11-21T01:30:00Z", "2026-11-21T14:00:00Z")      # left open until 8 AM
    assert not back["opened"]["hidden"] and back["ticked"]["hidden"] and back["ticked"]["sunAt"] == "up"


def test_the_clock_sun_is_untouched_and_the_script_stays_on_the_device():
    src = SKY_JS.read_text(encoding="utf-8")
    assert "var RISE = 6, SET = 19, NIGHT = -0.25;" in src
    assert "return Math.round(Math.sin((hours - RISE) / (SET - RISE) * Math.PI) * 1000) / 1000;" in src
    assert 'parseFloat(el.getAttribute("data-lat"))' in src and "36.5" not in src     # the place comes from the page
    for word in ("XMLHttpRequest", "sendBeacon", "localStorage", "sessionStorage", "cookie", "geolocation",
                 "import(", "WebSocket", "EventSource"):
        assert word not in src, word
    # one call out, and only one: the weather over the place, to the address the page names (tests/test_weather.py)
    assert src.count("fetch(") == 1 and 'el.getAttribute("data-weather")' in src
    # the sun over the place and the moon come from one render, which draws the moon only with the sun down
    assert "var m = where && !sunUp ? moon(ms, where.lat, where.lon) : null;" in src
    assert 'sunEl.setAttribute("data-at", sunUp ? "up" : "down");' in src
    assert "moon-disc" not in src and 'createElementNS(SVG, "circle")' not in src        # no disc for the unlit part
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
            ' data-lon="-87.36"'
            ' data-weather="https://api.weather.gov/stations/KCKV/observations/latest" hidden></span></div>')
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
    # only the lit part is drawn: no disc for the dark part, and no ring or round box that would outline the whole moon
    assert ".moon-disc" not in CSS and "box-shadow" not in rules and "border-radius" not in rules
    assert "background" not in rules and "[data-day]" not in CSS
    assert ".moon-lit { fill: var(--moon); stroke: var(--moon-edge); stroke-width: .7; stroke-linejoin: round; }" in rules
    # its glow is a drop shadow, which follows the drawn shape
    assert ("filter: drop-shadow(0 0 calc(var(--moon-size) * .1) color-mix(in srgb, var(--moon-ring) 45%, transparent))"
            in rules)
    # the moon never sits behind words (the browser test below), so the header's text needs no halo
    assert "--moon-halo" not in CSS and "text-shadow" not in CSS[CSS.index(".sky-sun-frame"):CSS.index(".sky-hero {")]
    for theme in (LIGHT, DARK):                               # the lit part or its edge stands off the sky
        assert _ratio(theme["--moon-edge"], theme["--sky"]) >= 2 or _ratio(theme["--moon"], theme["--sky"]) >= 3
    assert LIGHT["--moon"] == "#FFFFFF" and _ratio(DARK["--moon"], DARK["--sky"]) >= 3
    # the two dark blocks (the system setting and the explicit choice) carry the same moon
    assert CSS.count("--moon: #C3CCDE; --moon-edge: #7C86A3; --moon-ring: #A9BDE6;") == 2
    # the sun slides only for a reader who has not asked for less motion
    assert CSS.count("transition: transform 1.4s") == 1
    assert "@media (prefers-reduced-motion: no-preference) { .sky-sun { transition: transform 1.4s" in CSS


CLEAR_PROBE = r"""
const path = require('path');
let pw;
const roots = [...(process.env.NODE_PATH || '').split(path.delimiter).filter(Boolean), '/opt/node22/lib/node_modules'];
for (const r of ['', ...roots]) {
  try { pw = require(r ? path.join(r, 'playwright') : 'playwright'); break; } catch (e) { /* next */ }
}
(async () => {
  const [site, rels, instants] = [process.argv[2], JSON.parse(process.argv[3]), JSON.parse(process.argv[4])];
  const painted = JSON.parse(process.argv[5]);
  const browser = await pw.chromium.launch();
  const out = [], paint = [];
  for (const [width, height] of [[375, 667], [1280, 800]]) for (const rel of rels) for (const iso of instants) {
    const ctx = await browser.newContext({ viewport: { width, height }, timezoneId: 'America/Chicago',
      reducedMotion: 'reduce' });                              // no slide: the sun is where it belongs at once
    const page = await ctx.newPage();
    await page.clock.setFixedTime(new Date(iso));
    await page.goto('file://' + path.join(site, rel));
    // the web fonts are in, and the moon has been put back in the open sky after them
    await page.evaluate(() => document.fonts.ready.then(() => new Promise(r => setTimeout(r, 50))));
    const at = await page.evaluate(() => {
      const box = r => ({ left: r.left, top: r.top, right: r.right, bottom: r.bottom });
      const words = n => { const g = document.createRange(); g.selectNodeContents(n);
        return box(g.getBoundingClientRect()); };
      const moon = document.getElementById('sky-moon'), sun = document.getElementById('sky-sun');
      const header = box(document.querySelector('.site-header').getBoundingClientRect());
      const air = parseFloat(getComputedStyle(moon).width) * 0.14;
      const texts = {};
      for (const [name, sel] of [['plate', '.site-header .site-name'], ['tag', '.site-header .unofficial-tag'],
                                 ['date', '#sky-hero .sky-day']]) {
        const n = document.querySelector(sel); if (n) { texts[name] = words(n); }
      }
      texts.menu = box(document.getElementById('nav-open').getBoundingClientRect());
      const lit = document.getElementById('sky-moon-lit'), ms = getComputedStyle(moon);
      // the drawn path as the browser measures it, in its own units (a disc of radius 10): `far` the farthest point
      // of its outline from the centre, `limb` the length of outline on the disc's circle, `bow` how far the rest
      // of the outline (the terminator) strays from the straight line between the poles
      let outline = null;
      if (lit && !moon.hasAttribute('hidden')) {
        const len = lit.getTotalLength(), n = 1440;
        let far = 0, on = 0, bow = 0;
        for (let i = 0; i <= n; i += 1) {
          const p = lit.getPointAtLength(len * i / n), d = Math.hypot(p.x, p.y);
          far = Math.max(far, d);
          if (d > 9.98) { on += 1; } else { bow = Math.max(bow, Math.abs(p.x)); }
        }
        outline = { far, limb: len * on / (n + 1), bow, len };
      }
      return { hidden: moon.hasAttribute('hidden'), moon: box(moon.getBoundingClientRect()), air, header, texts,
               size: parseFloat(ms.width), svgs: moon.querySelectorAll('svg').length,
               shapes: [...moon.querySelectorAll('svg *')].map(n => n.tagName.toLowerCase()),
               litPath: lit ? lit.getAttribute('d') : null, outline,
               moonBox: [ms.boxShadow, ms.backgroundColor, ms.borderTopWidth],
               sunAt: sun.getAttribute('data-at'), sunSeen: getComputedStyle(sun).visibility !== 'hidden',
               sunAlt: sun.style.getPropertyValue('--sun-alt'), sunBox: box(sun.getBoundingClientRect()),
               date: document.getElementById('sky-date').textContent,
               dateSeen: !document.getElementById('sky-hero').hidden,
               hscroll: document.documentElement.scrollWidth > innerWidth };
    });
    out.push({ width, rel, iso, ...at });
    await ctx.close();
  }
  // What is really painted, on the dark page at 1280 (the moon stands far off the dark sky): a picture of the moon's
  // box with 6px of sky around it. Counted: the pixels far brighter than the sky (the lit part and its hairline;
  // the glow is too faint to count), as a share of the whole disc; and how far the pixel in the middle of the
  // unlit side is from the sky beside it, in the same row of the picture.
  for (const iso of painted) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, timezoneId: 'America/Chicago',
      colorScheme: 'dark', reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    await page.clock.setFixedTime(new Date(iso));
    await page.goto('file://' + path.join(site, 'index.html'));
    await page.evaluate(() => document.fonts.ready.then(() => new Promise(r => setTimeout(r, 50))));
    const m = await page.evaluate(() => { const r = document.getElementById('sky-moon').getBoundingClientRect();
      const turn = /rotate\((-?\d+)\)/.exec(document.getElementById('sky-moon-lit').getAttribute('transform'));
      return { x: r.left, y: r.top, size: r.width, turn: parseFloat(turn[1]) }; });
    const pad = 6, clip = { x: Math.round(m.x) - pad, y: Math.round(m.y) - pad, width: Math.round(m.size) + 2 * pad,
                            height: Math.round(m.size) + 2 * pad };
    const png = (await page.screenshot({ clip })).toString('base64');
    const blank = await ctx.newPage();
    const px = await blank.evaluate(async b64 => {
      const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode();
      const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
      const g = c.getContext('2d'); g.drawImage(img, 0, 0);
      return { w: img.width, h: img.height, d: Array.from(g.getImageData(0, 0, img.width, img.height).data) };
    }, png);
    const at = (x, y) => { const i = 4 * (Math.round(y) * px.w + Math.round(x));
      return [px.d[i], px.d[i + 1], px.d[i + 2]]; };
    const far = (a, b) => Math.max(Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1]), Math.abs(a[2] - b[2]));
    const sky = at(0, 0), r = m.size / 2, mid = pad + r, a = m.turn * Math.PI / 180;
    let bright = 0;
    for (let y = 0; y < px.h; y += 1) for (let x = 0; x < px.w; x += 1) { if (at(x, y)[0] - sky[0] > 70) { bright += 1; } }
    const dy = mid - 0.6 * r * Math.sin(a);                    // the middle of the side away from the bright edge
    paint.push({ iso, share: bright / (Math.PI * r * r), dark: far(at(mid - 0.6 * r * Math.cos(a), dy), at(0, dy)),
                 edge: far(at(mid + 0.85 * r * Math.cos(a), mid + 0.85 * r * Math.sin(a)), sky) });
    await ctx.close();
  }
  await browser.close();
  console.log(JSON.stringify({ rows: out, paint }));
})();
"""

# (instant UTC, what the sky over Clarksville holds then, the date in Clarksville)
SKIES = [
    ("2026-11-25T05:30:00Z", "moon", "November 24"),          # 11:30 PM: the full moon high
    ("2026-11-12T23:20:00Z", "moon", "November 12"),          # 5:20 PM, after sunset: the crescent low in the west
    ("2026-11-27T03:00:00Z", "moon", "November 26"),          # 9 PM: a gibbous moon in the east
    ("2026-03-26T00:30:00Z", "moon", "March 25"),             # 7:30 PM, after sunset: the half moon overhead
    ("2026-08-20T01:10:00Z", "moon", "August 19"),            # 8:10 PM: first quarter, 49.6% lit, lit on the right
    ("2026-08-24T07:00:00Z", "moon", "August 24"),            # 2 AM: low in the west, over the sun's daytime column
    ("2026-11-20T21:30:00Z", "sun", "November 20"),           # 3:30 PM: the gibbous moon is up too, and not drawn
    ("2026-12-01T13:30:00Z", "sun", "December 1"),            # 7:30 AM: the half moon is high, and not drawn
    ("2026-11-22T18:30:00Z", "sun", "November 22"),           # 12:30 PM, the moon not yet risen
    ("2026-11-09T06:00:00Z", "neither", "November 9"),        # midnight at new moon
]


def _browser_ok():
    return bool(shutil.which("node")) and (os.path.exists("/opt/pw-browsers") or bool(shutil.which("playwright")))


def _hits(a, b):
    return a["left"] < b["right"] and b["left"] < a["right"] and a["top"] < b["bottom"] and b["top"] < a["bottom"]


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_in_a_browser_the_sky_holds_the_sun_or_the_moon_never_both_and_the_moon_is_its_lit_part(site, tmp_path):  # noqa: F811
    """Owner, 2026-11-18, at 375 and 1280, on the landing, a body's page and a page a folder down: the same header
    with the date; by day the sun and no moon, although the moon is up; at night no sun at all (not drawn: no disc
    and no ring over the horizon) and the moon, if it is up; at new moon neither. The moon is one drawn shape, its
    lit part, with no disc, ring or box behind it, so a crescent's drawing is narrower than the moon's box; with its
    air it touches no word of the header (manager's design call, 2026-11-14: open sky only), stays inside the band,
    is 28px on the phone and about 40px wide, and the page does not scroll sideways."""
    rels = sorted(str(p.relative_to(site)) for p in site.rglob("*.html"))
    body = next(r for r in rels if r != "index.html" and "/" not in r)
    deep = next(r for r in rels if "/" in r)
    script = tmp_path / "clear.js"
    script.write_text(CLEAR_PROBE, encoding="utf-8")
    painted = {"2026-11-12T23:20:00Z": (0.124, 0.05, 0.32), "2026-03-26T00:30:00Z": (0.525, 0.42, 0.68),
               "2026-11-25T05:30:00Z": (0.993, 0.9, 1.1)}     # instant: (share of the disc lit, painted share from, to)
    res = subprocess.run(["node", str(script), str(site), json.dumps(["index.html", body, deep]),
                          json.dumps([iso for iso, _, _ in SKIES]), json.dumps(list(painted))],
                         capture_output=True, text=True, timeout=600)
    assert res.returncode == 0, res.stderr
    got = json.loads(res.stdout)
    rows = got["rows"]
    assert len(rows) == 2 * 3 * len(SKIES)
    want = {iso: (sky, date) for iso, sky, date in SKIES}
    crescents = halves = 0
    for r in rows:
        where = (r["width"], r["rel"], r["iso"])
        sky, date = want[r["iso"]]
        assert not r["hscroll"], where
        assert r["dateSeen"] and r["date"] == date, where                     # the date line, on every page
        sun_seen, moon_seen = r["sunSeen"], not r["hidden"]
        assert not (sun_seen and moon_seen), where                            # never both
        assert (sun_seen, moon_seen) == (sky == "sun", sky == "moon"), where
        assert r["sunAt"] == ("up" if sky == "sun" else "down"), where
        if sky == "sun":                                      # on or over the horizon, inside the band
            assert float(r["sunAlt"]) >= 0 and r["sunBox"]["top"] < r["header"]["bottom"], where
        if not moon_seen:
            continue
        assert r["svgs"] == 1 and r["shapes"] == ["path"], where              # the lit part and nothing else
        assert r["moonBox"] == ["none", "rgba(0, 0, 0, 0)", "0px"], where     # no ring, no disc, no outline behind it
        assert abs(r["size"] - (28 if r["width"] == 375 else 39.7)) < 0.5, where
        m, air = r["moon"], r["air"]
        halo = {"left": m["left"] - air, "top": m["top"] - air, "right": m["right"] + air,
                "bottom": m["bottom"] + air}
        for name, box in r["texts"].items():
            assert not _hits(halo, box), (where, name, halo, box)
        h = r["header"]
        assert h["left"] <= m["left"] and m["right"] <= h["right"], where
        assert h["top"] <= m["top"] and m["bottom"] <= h["bottom"], where
        # the browser's own measure of the drawn outline: nothing outside the disc's circle (radius 10), and the
        # whole bright half of that circle is on it (31.4 long), at every phase
        o = r["outline"]
        assert o["far"] <= 10.01 and o["limb"] >= 31.2, (where, o)
        if r["iso"] == "2026-08-20T01:10:00Z":                # first quarter: a half disc, its terminator straight
            halves += 1
            assert o["bow"] <= 0.15 and abs(o["len"] - (10 * math.pi + 20)) < 0.2, (where, o, r["litPath"])
        if r["iso"] == "2026-11-12T23:20:00Z":                # 12% lit: the drawing is a crescent, not a disc
            crescents += 1
            assert re.fullmatch(r"M0 -10A10 10 0 0 1 0 10A7\.\d+ 10 0 0 0 0 -10Z", r["litPath"]), where
    assert crescents == 6 and halves == 6
    # what is painted: about the lit share of the disc and no more, and the unlit side is plain sky ("not a whole
    # moon with a shadow"): the faint disc this replaced stood about 30 levels off the sky there
    assert [p["iso"] for p in got["paint"]] == list(painted)
    for p in got["paint"]:
        lit, low, high = painted[p["iso"]]
        assert low <= p["share"] <= high, p
        assert p["edge"] > 100, p                             # the lit side is there, bright
        if lit < 0.9:
            assert p["dark"] <= 6, p
