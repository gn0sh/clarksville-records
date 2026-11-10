"""site/static/georef.js is a port of sitegen/georef.py district_for (and so of ward_for, the same lookup over the ward
paths with their own margin): both must place every point in the same district or ward
with the same near-boundary flag. site/static/address.js turns a Census geocoder answer into what the visitor reads.
Runs the scripts under node (no browser) on the held-out points of tests/test_georef.py and on stubbed answers."""
import json
import shutil
import subprocess

import pytest

from sitegen import georef as gr
from test_georef import D, G, ROOT
from test_ward_map import POINTS as WARD_TEST_POINTS, WG

GEOREF_JS = ROOT / "site" / "static" / "georef.js"
ADDRESS_JS = ROOT / "site" / "static" / "address.js"

# held-out road crossings, every control point, and the outside / edge points of test_georef.py
POINTS = ([p["lonlat"] for p in G["check_points"]] + [p["lonlat"] for p in G["control_points"]]
          + [[-87.44, 36.665], [-87.339549, 36.641936], [-87.2, 36.45], [-87.5, 36.3], [-87.36, 36.53]])

HARNESS = r"""
const geo = require(process.argv[2]);
const addr = require(process.argv[3]);
const inp = JSON.parse(require("fs").readFileSync(0, "utf8"));
const districts = inp.districts.districts.map(d => ({ number: d.number, path: d.path }));
const locate = (lon, lat) => geo.districtFor(lon, lat, districts, inp.georef);
const out = { points: inp.points.map(p => locate(p[0], p[1])), answers: {} };
for (const [k, v] of Object.entries(inp.answers)) {
  try { out.answers[k] = addr.classify(v, locate); } catch (e) { out.answers[k] = { threw: String(e) }; }
}
// the wards: the same districtFor over the ward paths, with the wards' own margin (as static/address.js binds it)
const wardShapes = inp.districts.wards.wards.map(w => ({ number: w.number, path: w.path }));
const wardGeo = Object.assign({}, inp.georef, { boundary_margin_m: inp.districts.wards.boundary_margin_m });
const wardFull = (lon, lat) => geo.districtFor(lon, lat, wardShapes, wardGeo);
const locateWard = (lon, lat) => {
  const g = wardFull(lon, lat);
  return { ward: g.district, near_boundary: g.near_boundary };
};
out.wardPoints = inp.wardPoints.map(p => wardFull(p[0], p[1]));
out.wardAnswers = {};
for (const [k, v] of Object.entries(inp.wardAnswers)) {
  try { out.wardAnswers[k] = addr.classify(v, locate, locateWard); } catch (e) { out.wardAnswers[k] = { threw: String(e) }; }
}
out.url = addr.jsonpUrl("https://geo.example/x", "1 Main St, Apt #2 & <b>", "cb_1");
out.timeout = addr.TIMEOUT_MS;
out.callback = addr.CALLBACK;
out.doc = addr.frameDoc("X()", 'https://geo.example/x?a=1&b="2"<3>');
console.log(JSON.stringify(out));
"""


def _match(*pts):
    if pts and not isinstance(pts[0], (list, tuple)):
        pts = (pts,)
    return {"result": {"input": {}, "addressMatches": [
        {"matchedAddress": f"{i + 1} TEST ST", "coordinates": {"x": lon, "y": lat}} for i, (lon, lat) in enumerate(pts)]}}


def _pt(pid):
    return next(p["lonlat"] for p in G["check_points"] if p["id"] == pid)


ANSWERS = {
    "in5": _match(*next(p["lonlat"] for p in G["check_points"] if p["id"] == "franklin-2nd")),
    "line": _match(*next(p["lonlat"] for p in G["check_points"] if p["id"] == "hwy48-loneoak")),
    "ky": _match(-87.44, 36.665),
    "nomatch": {"result": {"input": {}, "addressMatches": []}},
    # more than one match (addr-pin/ambiguous-match): answered only when all land in one district, none near a line
    "two_same": _match(_pt("franklin-2nd"), _pt("franklin-2nd")),
    "two_outside": _match([-87.44, 36.665], [-87.5, 36.75]),
    "two_districts": _match(_pt("franklin-2nd"), _pt("rossview-wilma")),
    "two_one_near": _match(_pt("slayden-hwy13"), _pt("hwy48-loneoak")),          # both District 6, one near a line
    "two_in_and_out": _match(_pt("franklin-2nd"), [-87.44, 36.665]),
    "twenty": _match(*([_pt("franklin-2nd")] * 20)),
    "many": _match(*([_pt("franklin-2nd")] * 21)),
    "two_one_bad": {"result": {"addressMatches": [_match(*_pt("franklin-2nd"))["result"]["addressMatches"][0],
                                                  {"coordinates": {"x": None, "y": 36.5}}]}},
    "error_none": None,
    "error_string": "oops",
    "error_no_result": {"errors": ["bad"]},
    "error_matches_not_list": {"result": {"addressMatches": {"x": 1}}},
    "error_coords": {"result": {"addressMatches": [{"coordinates": {"x": "-87.3", "y": 36.5}}]}},
    "error_range": {"result": {"addressMatches": [{"coordinates": {"x": -870.0, "y": 36.5}}]}},
}


def _wpt(pid):
    return next(p["lonlat"] for p in WG["control_points"] + WG["check_points"] if p["id"] == pid)


# the ward lookup's points: every ward test point, the poster's road crossings, and the outside / edge points
WARD_POINTS = ([p for _w, _n, p in WARD_TEST_POINTS] + [p["lonlat"] for p in WG["control_points"] + WG["check_points"]]
               + POINTS)

WARD_ANSWERS = {
    "d5w6": _match(*_pt("franklin-2nd")),                                    # District 5, Ward 6
    "ward_near": _match(*_wpt("ashlandcity-sevenmileferry")),                # on the ward 6 / 7 line
    "outside_city": _match(*_pt("slayden-hwy13")),                           # District 6, no ward
    "ky": _match(-87.44, 36.665),
    "two_same": _match(_pt("franklin-2nd"), _pt("franklin-2nd")),
    "two_wards_one_district": _match(_wpt("pinetree-raintree"), [-87.422012, 36.587303]),   # District 10: Wards 2, 3
    "two_one_ward_near": _match(_pt("franklin-2nd"), _wpt("college-nspring"), _wpt("ashlandcity-sevenmileferry")),
}


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    h = tmp_path_factory.mktemp("georef") / "harness.js"
    h.write_text(HARNESS, encoding="utf-8")
    res = subprocess.run(["node", str(h), str(GEOREF_JS), str(ADDRESS_JS)], capture_output=True, text=True, check=True,
                         input=json.dumps({"districts": D, "georef": G, "points": POINTS, "answers": ANSWERS,
                                           "wardPoints": WARD_POINTS, "wardAnswers": WARD_ANSWERS}))
    return json.loads(res.stdout)


@pytest.mark.parametrize("i", range(len(WARD_POINTS)))
def test_js_ward_lookup_matches_python(run, i):
    py, js = gr.ward_for(*WARD_POINTS[i], D, G), run["wardPoints"][i]
    assert js["district"] == py["ward"] and js["near_boundary"] == py["near_boundary"], (WARD_POINTS[i], py, js)
    assert abs(js["distance_m"] - py["distance_m"]) <= 0.11
    assert js.get("overlap") == py.get("overlap") and js.get("closest") == py.get("closest")


def test_classify_with_wards(run):
    a = run["wardAnswers"]
    assert a["d5w6"] == {"kind": "district", "district": 5, "matched": "1 TEST ST", "page_xy": a["d5w6"]["page_xy"],
                         "ward": {"kind": "ward", "ward": 6}}
    assert a["ward_near"]["ward"]["kind"] == "near"
    assert a["outside_city"]["kind"] == "district" and a["outside_city"]["ward"] == {"kind": "outside", "ward": None}
    assert a["ky"]["kind"] == "outside"
    assert a["two_same"]["ward"] == {"kind": "ward", "ward": 6}
    # several matches must agree on the ward too, and none may be near a ward line
    assert a["two_wards_one_district"] == {"kind": "ambiguous", "count": 2}
    assert a["two_one_ward_near"] == {"kind": "ambiguous", "count": 3}


@pytest.mark.parametrize("i", range(len(POINTS)))
def test_js_district_for_matches_python(run, i):
    py, js = gr.district_for(*POINTS[i], D, G), run["points"][i]
    assert js["district"] == py["district"] and js["near_boundary"] == py["near_boundary"], (POINTS[i], py, js)
    assert abs(js["distance_m"] - py["distance_m"]) <= 0.11
    assert all(abs(a - b) <= 0.011 for a, b in zip(js["page_xy"], py["page_xy"]))
    assert js.get("overlap") == py.get("overlap") and js.get("closest") == py.get("closest")


def test_parity_covers_inside_near_and_outside(run):
    kinds = {(p["district"] is None, p["near_boundary"]) for p in run["points"]}
    assert {(False, False), (True, False)} <= kinds and any(p["near_boundary"] for p in run["points"])


def test_classify_match_near_outside(run):
    a = run["answers"]
    assert a["in5"] == {"kind": "district", "district": 5, "matched": "1 TEST ST", "page_xy": a["in5"]["page_xy"]}
    assert a["line"]["kind"] == "near"
    assert a["ky"]["kind"] == "outside" and a["ky"]["district"] is None


def test_classify_more_than_one_match(run):
    a = run["answers"]
    assert a["two_same"]["kind"] == "district" and a["two_same"]["district"] == 5 and a["two_same"]["matched"] == "1 TEST ST"
    assert a["two_outside"]["kind"] == "outside"
    for k in ("two_districts", "two_one_near", "two_in_and_out"):
        assert a[k] == {"kind": "ambiguous", "count": 2}, k
    assert a["twenty"]["kind"] == "district" and a["twenty"]["district"] == 5
    assert a["many"] == {"kind": "ambiguous", "count": 21}
    assert a["two_one_bad"] == {"kind": "error"}


def test_frame_doc_escapes_the_url_attribute(run):
    assert run["callback"] == "crGeocode"
    assert run["doc"] == ('<!doctype html><meta charset="utf-8"><meta name="referrer" content="no-referrer">'
                          '<script data-u="https://geo.example/x?a=1&amp;b=&quot;2&quot;&lt;3&gt;">X()</script>')


def test_classify_no_match_and_bad_answers(run):
    a = run["answers"]
    assert a["nomatch"] == {"kind": "nomatch"}
    for k in ANSWERS:
        if k.startswith("error"):
            assert a[k] == {"kind": "error"}, k


def test_jsonp_url_is_encoded_and_fixed(run):
    assert run["url"] == ("https://geo.example/x?address=1%20Main%20St%2C%20Apt%20%232%20%26%20%3Cb%3E"
                          "&benchmark=Public_AR_Current&format=jsonp&callback=cb_1")
    assert run["timeout"] == 8000


def test_scripts_store_nothing_and_call_out_only_from_the_submit_handler():
    for path in (GEOREF_JS, ADDRESS_JS):
        js = path.read_text(encoding="utf-8")
        for banned in ("localStorage", "sessionStorage", "indexedDB", "document.cookie", "console.", "fetch(",
                       "XMLHttpRequest", "sendBeacon", "innerHTML", "keyup", "keydown", "\"input\"", "\"change\""):
            assert banned not in js, (path.name, banned)
    js = ADDRESS_JS.read_text(encoding="utf-8")
    # third-party-script/jsonp-runs-in-origin: the page never loads the geocoder's script itself; one sandboxed iframe
    # per submit (allow-scripts only, no allow-same-origin), heard only from that iframe, removed after
    assert "createElement(\"script\")" not in js and ".src = " not in js
    assert js.count('createElement("iframe")') == 1 and js.count(".srcdoc = ") == 1
    assert js.count('setAttribute("sandbox", "allow-scripts")') == 1
    assert js.count('setAttribute("sandbox"') == 1 and ".sandbox" not in js
    assert "allow-same-origin\"" not in js and "allow-top" not in js and "allow-popups" not in js
    assert 'setAttribute("referrerpolicy", "no-referrer")' in js
    assert "e.source !== w" in js and 'e.origin !== "null"' in js and "JSON.parse(d.json)" in js
    assert js.index('addEventListener("submit"') < js.index('createElement("iframe")')
    assert "removeChild(req.frame)" in js
    assert "http://www.w3.org/2000/svg" in js and js.count("https://") == 2   # the SVG namespace; the https checks
