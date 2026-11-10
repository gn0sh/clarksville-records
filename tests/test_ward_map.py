"""City ward lookup: the ward poster's georeference (config/localities/<locality>/wards-georef.json), the ward shapes
traced into districts.json (tools/extract_ward_poster.py) and sitegen/georef.py ward_for.

Accuracy evidence (method and numbers in docs/platform-facts.md, "City ward map"): no public record we hold ties a
street address to a ward (the city's agendas and minutes print no ward for zoning cases or property items, and council
members' addresses are not used), so the expected wards below are read off the poster itself: each ward's printed
number, and three crossings of named streets per ward, at least 250 m inside it. For each point the expected ward was
found on the poster's own, unsimplified fills (the point placed on the poster page by the wards-georef fit), not from
the traced paths tested here, and 8 of them were checked by eye on 100 dpi renders of the poster."""
import json
from pathlib import Path

import pytest

from sitegen import georef as gr
from tools import extract_ward_poster as ewp, georef_fit, seat_check

ROOT = Path(__file__).resolve().parent.parent
LOCALITY = ROOT / "config" / "localities" / seat_check.locality()
WG_PATH = LOCALITY / "wards-georef.json"
WG = json.loads(WG_PATH.read_text(encoding="utf-8"))
G = json.loads((LOCALITY / "georef.json").read_text(encoding="utf-8"))
D = json.loads((LOCALITY / "districts.json").read_text(encoding="utf-8"))
W = D["wards"]

POINTS = [
    (1, "printed number 1", [-87.444757, 36.633261]),
    (2, "printed number 2", [-87.418154, 36.564084]),
    (3, "printed number 3", [-87.4339, 36.601496]),
    (4, "printed number 4", [-87.380209, 36.563316]),
    (5, "printed number 5", [-87.392689, 36.611418]),
    (6, "printed number 6", [-87.348505, 36.519191]),
    (7, "printed number 7", [-87.300832, 36.5042]),
    (8, "printed number 8", [-87.34174, 36.624942]),
    (9, "printed number 9", [-87.335397, 36.578979]),
    (10, "printed number 10", [-87.262345, 36.528446]),
    (11, "printed number 11", [-87.291352, 36.569133]),
    (12, "printed number 12", [-87.301828, 36.61378]),
    (1, "Pembroke Rd x Pembrook Pl", [-87.414253, 36.637869]),
    (1, "Sturdivant Dr x Sunset Meadows Way", [-87.411231, 36.630882]),
    (1, "Arbor St x Copeland Rd", [-87.428764, 36.631578]),
    (2, "Collinwood Dr x Melinda Dr", [-87.40851, 36.5548]),
    (2, "Avalon St x Lasalle St", [-87.403763, 36.561394]),
    (2, "Pinetree Rd x Raintree Dr", [-87.421295, 36.571075]),
    (3, "Ambrose Dr x Mills Dr", [-87.422012, 36.587303]),
    (3, "Bobcat Dr x Chucker Dr", [-87.379957, 36.588492]),
    (3, "Timberline Pl x Timberline Way", [-87.407098, 36.588305]),
    (4, "Dale Ter x Dalewood Dr", [-87.390152, 36.567188]),
    (4, "Bel Air Blvd x Stone Mountain Rd", [-87.398499, 36.574619]),
    (4, "Galvin Dr x Rosemary Dr", [-87.416946, 36.545059]),
    (5, "Audrea Ln x Cranklen Cir", [-87.418979, 36.612265]),
    (5, "Sandburg Dr x Short St", [-87.417739, 36.604195]),
    (5, "Cobra Ln x Sikorsky Ln", [-87.368849, 36.638959]),
    (6, "Liberty Pkwy x Madison St", [-87.329082, 36.519266]),
    (6, "Commerce St x University Ave", [-87.35254, 36.527627]),
    (6, "S Spring St x W Washington St", [-87.36145, 36.523651]),
    (7, "Observatory Dr x Sun Valley Rd", [-87.366074, 36.491257]),
    (7, "Barry Dr x Cottonwood Dr", [-87.359748, 36.499014]),
    (7, "Dogwood Ln x Locust Rd", [-87.296974, 36.510596]),
    (8, "Reasons Dr x Scrub Oak Dr", [-87.334557, 36.619441]),
    (8, "Cedar Springs Cir x Sydney Louise Dr", [-87.345972, 36.609164]),
    (8, "Misty Way x Venessa Dr", [-87.322891, 36.618576]),
    (9, "Cane Brake Rd x Jace Dr", [-87.355386, 36.561307]),
    (9, "Russet Dr x Russet Ridge Dr", [-87.342038, 36.590273]),
    (9, "Harold Dr x West Dr", [-87.342133, 36.547354]),
    (10, "Old Farmers Rd x State Rte 76", [-87.250391, 36.516897]),
    (10, "Alton Dr x Auburn Dr", [-87.2882, 36.546467]),
    (10, "Kimberly Dr x Wingate Dr", [-87.297737, 36.545891]),
    (11, "Rossview Rd x Warfield Blvd", [-87.287882, 36.560958]),
    (11, "Old Russellville Pike x Rossview Rd", [-87.302219, 36.565535]),
    (11, "Jessica Dr x Kim Dr", [-87.275549, 36.56111]),
    (12, "Cindy Jo Ct x Samantha Ln", [-87.30333, 36.628361]),
    (12, "Fox Hound Dr x Gray Fox Dr", [-87.281041, 36.638448]),
    (12, "Isaac Dr x Parade Dr", [-87.295916, 36.635379]),
]


def _pt(points, pid):
    return next(p["lonlat"] for p in points if p["id"] == pid)


# --- the poster's georeference ------------------------------------------------------------------------------------

def test_stored_fit_is_current():
    assert georef_fit.main([str(WG_PATH)]) == 0


def test_points_and_sources_are_complete():
    ctrl, check = WG["control_points"], WG["check_points"]
    assert len(ctrl) >= 8 and len(check) >= 8
    assert not {p["id"] for p in ctrl} & {p["id"] for p in check}
    for key, s in WG["sources"].items():
        if key == "access_note":
            continue
        assert s["url"].startswith("https://") and s["licence"].startswith("Public domain") and s["fetched"]
    for p in ctrl + check:
        assert p["lonlat_source"] in WG["sources"], p["id"]
        lon, lat = p["lonlat"]
        assert -87.5 < lon < -87.15 and 36.45 < lat < 36.66
    for s in [WG["source_url"], *(v["url"] for k, v in WG["sources"].items() if k != "access_note")]:
        assert "apsu.edu" not in s and "mcgtn.org" not in s and "arcgis" not in s      # no APSU/county GIS data
    xs = [p["page_xy"][0] for p in ctrl]
    ys = [p["page_xy"][1] for p in ctrl]
    assert max(xs) - min(xs) > 1800 and max(ys) - min(ys) > 1400                       # every side of the city


def test_fit_quality_and_margin():
    f = WG["fit"]
    assert f["rms_residual_m"] <= 3 and f["max_check_error_m"] <= 5 and max(f["leave_one_out_m"].values()) <= 5
    assert abs(f["rotation_deg"]) < 0.05 and abs(f["scale_ratio_x_to_y"] - 1) < 0.001   # State Plane, north up
    basis = WG["boundary_margin_basis"]
    assert basis["transform_m"] >= max(f["leave_one_out_m"].values())
    assert basis["traced_shapes_m"] >= W["max_simplify_error_m"]
    assert WG["boundary_margin_m"] == (basis["transform_m"] + basis["traced_shapes_m"] + basis["source_drawing_m"]
                                       + basis["geocoder_m"])


# --- the traced wards in districts.json ---------------------------------------------------------------------------

def test_wards_block_is_sourced_and_belongs_to_this_georef():
    assert W["status"] == "available" and W["source_sha256"] == WG["source_sha256"]
    assert W["source_url"] == WG["source_url"] and W["source_url"].startswith("https://www.cmcrpc.com/")
    assert W["fetched"] and W["source_updated"] == "2026-02-25"
    assert W["boundary_margin_m"] == WG["boundary_margin_m"]
    assert [w["number"] for w in W["wards"]] == list(range(1, 13))


def test_ward_paths_were_traced_with_the_stored_fits():
    """The ward paths sit in the district map's page space: poster page -> metres -> district page. Refitting either
    georef without re-running tools/extract_ward_poster.py would leave them in the wrong place."""
    want = ewp.compose(G["affine"], ewp.invert(WG["affine"]))
    assert all(abs(a - b) < 1e-9 * max(1.0, abs(b)) for ra, rb in zip(W["page_transform"], want) for a, b in zip(ra, rb))


def test_tool_reads_wards_by_two_independent_readings():
    """Legend colour and printed number must agree; a part whose colour is not in the legend is a problem."""
    box = pytest.importorskip("shapely.geometry").box     # the tool's optional "maps" dependency
    legend = {(0.1, 0.1, 0.1): 1, (0.2, 0.2, 0.2): 2}
    parts = [((0.1, 0.1, 0.1), box(0, 0, 10, 10)), ((0.2, 0.2, 0.2), box(10, 0, 20, 10))]
    shapes, problems = ewp.assign(parts, [(1, 5, 5), (2, 15, 5)], legend)
    assert set(shapes) == {1, 2} and [p for p in problems if "printed" in p and "lies" in p] == []
    _, problems = ewp.assign(parts, [(2, 5, 5), (1, 15, 5)], legend)
    assert any("printed 2" in p for p in problems)
    _, problems = ewp.assign(parts + [((0.9, 0.9, 0.9), box(30, 0, 40, 10))], [(1, 5, 5), (2, 15, 5)], legend)
    assert any("not in the legend" in p for p in problems)


# --- ward_for -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("ward,where,lonlat", POINTS, ids=[f"{w}-{n}" for w, n, _ in POINTS])
def test_points_land_in_their_ward(ward, where, lonlat):
    got = gr.ward_for(*lonlat, D, G)
    assert got["ward"] == ward and not got["near_boundary"], (where, got)


def test_every_ward_has_at_least_three_street_crossings_and_its_label():
    by = {}
    for w, where, _ in POINTS:
        by.setdefault(w, []).append(where)
    assert sorted(by) == list(range(1, 13)) and all(len(v) >= 4 for v in by.values())


def test_points_near_a_ward_line_are_flagged():
    # Ashland City Rd x Seven Mile Ferry Rd N: the crossing lies on the line between wards 6 and 7 (0.8 m)
    on_line = gr.ward_for(*_pt(WG["control_points"], "ashlandcity-sevenmileferry"), D, G)
    assert on_line["near_boundary"] and on_line["distance_m"] < 5
    # Appleton Dr x Caskey Dr, 52 m from the ward 2 / ward 3 line: inside the margin, so "near", not a plain answer
    close = gr.ward_for(*_pt(WG["control_points"], "appleton-caskey"), D, G)
    assert close["near_boundary"] and close["distance_m"] < W["boundary_margin_m"]


def test_outside_the_city_and_at_the_city_line():
    rural = gr.ward_for(*_pt(G["check_points"], "hwy48-loneoak"), D, G)        # south-west county, far from the city
    assert rural["ward"] is None and not rural["near_boundary"] and rural["distance_m"] > 5000
    ky = gr.ward_for(-87.44, 36.665, D, G)                                      # Oak Grove, KY
    assert ky["ward"] is None and not ky["near_boundary"]
    edge = gr.ward_for(*_pt(G["check_points"], "i24-ky"), D, G)                 # the city reaches the state line on I-24
    assert edge["near_boundary"] and edge["distance_m"] < 5


def test_district_and_ward_are_answered_together():
    # downtown: District 5 (tests/test_georef.py) and Ward 6, each well inside its lines
    lonlat = _pt(G["check_points"], "franklin-2nd")
    assert gr.district_for(*lonlat, D, G)["district"] == 5
    w = gr.ward_for(*lonlat, D, G)
    assert w["ward"] == 6 and not w["near_boundary"]


def test_no_ward_answer_without_ward_shapes():
    assert gr.ward_for(-87.3587, 36.5276, dict(D, wards={"status": "coming", "note": "x"}), G) is None
    with pytest.raises(ValueError):
        gr.ward_for(-87.3587, 36.5276, dict(D, wards=dict(W, boundary_margin_m=0)), G)
    with pytest.raises(ValueError):
        gr.ward_for(-87.3587, 36.5276, D, dict(G, source_sha256="0" * 64))


def test_default_files_are_the_locality_config():
    assert gr.ward_for(*_pt(G["check_points"], "franklin-2nd"))["ward"] == 6
