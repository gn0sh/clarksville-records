"""site/static/georef.js is a port of sitegen/georef.py district_for: both must place every point in the same district
with the same near-boundary flag. site/static/address.js turns a Census geocoder answer into what the visitor reads.
Runs the scripts under node (no browser) on the held-out points of tests/test_georef.py and on stubbed answers."""
import json
import shutil
import subprocess

import pytest

from sitegen import georef as gr
from test_georef import D, G, ROOT

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
out.url = addr.jsonpUrl("https://geo.example/x", "1 Main St, Apt #2 & <b>", "cb_1");
out.timeout = addr.TIMEOUT_MS;
console.log(JSON.stringify(out));
"""


def _match(lon, lat):
    return {"result": {"input": {}, "addressMatches": [{"matchedAddress": "1 TEST ST", "coordinates": {"x": lon, "y": lat}}]}}


ANSWERS = {
    "in5": _match(*next(p["lonlat"] for p in G["check_points"] if p["id"] == "franklin-2nd")),
    "line": _match(*next(p["lonlat"] for p in G["check_points"] if p["id"] == "hwy48-loneoak")),
    "ky": _match(-87.44, 36.665),
    "nomatch": {"result": {"input": {}, "addressMatches": []}},
    "error_none": None,
    "error_string": "oops",
    "error_no_result": {"errors": ["bad"]},
    "error_matches_not_list": {"result": {"addressMatches": {"x": 1}}},
    "error_coords": {"result": {"addressMatches": [{"coordinates": {"x": "-87.3", "y": 36.5}}]}},
    "error_range": {"result": {"addressMatches": [{"coordinates": {"x": -870.0, "y": 36.5}}]}},
}


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    h = tmp_path_factory.mktemp("georef") / "harness.js"
    h.write_text(HARNESS, encoding="utf-8")
    res = subprocess.run(["node", str(h), str(GEOREF_JS), str(ADDRESS_JS)], capture_output=True, text=True, check=True,
                         input=json.dumps({"districts": D, "georef": G, "points": POINTS, "answers": ANSWERS}))
    return json.loads(res.stdout)


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
    assert js.count("createElement(\"script\")") == 1 and js.count(".src = ") == 1
    assert js.index('addEventListener("submit"') < js.index("createElement(\"script\")")
    assert 'referrerPolicy = "no-referrer"' in js
    assert "http://www.w3.org/2000/svg" in js and js.count("https://") == 2   # the SVG namespace; the https checks
