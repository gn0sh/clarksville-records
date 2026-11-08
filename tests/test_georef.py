"""The district map's georeference (config/localities/<locality>/georef.json) and the address-pin lookup
(sitegen/georef.py district_for)."""
import json
import math
from pathlib import Path

import pytest

from sitegen import georef as gr
from tools import georef_fit, seat_check

ROOT = Path(__file__).resolve().parent.parent
LOCALITY = ROOT / "config" / "localities" / seat_check.locality()
GEOREF_PATH = LOCALITY / "georef.json"
G = json.loads(GEOREF_PATH.read_text(encoding="utf-8"))
D = json.loads((LOCALITY / "districts.json").read_text(encoding="utf-8"))


def test_projection_matches_reference_values():
    # EPSG:4269 -> EPSG:32136 from pyproj 3.8.0 (PROJ), 2026-11-08
    for lonlat, xy in [((-87.36, 36.53), (478204.3555, 244571.4239)),
                       ((-87.64, 36.64), (453335.4766, 257161.1411)),
                       ((-87.11, 36.31), (500315.3139, 219877.7392))]:
        x, y = gr.project(*lonlat, G["projection"])
        assert abs(x - xy[0]) < 0.001 and abs(y - xy[1]) < 0.001


def test_fit_affine_recovers_a_known_transform():
    m = [[0.03, -0.001, -15000.0], [0.002, -0.031, 9000.0]]
    src = [(450000.0, 220000.0), (500000.0, 225000.0), (470000.0, 258000.0), (455000.0, 240000.0)]
    got = gr.fit_affine(src, [gr.apply_affine(m, *p) for p in src])
    assert all(math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6) for ra, rb in zip(got, m) for a, b in zip(ra, rb))
    with pytest.raises(ValueError):
        gr.fit_affine([(0, 0), (1, 1), (2, 2)], [(0, 0), (1, 1), (2, 2)])


def test_stored_fit_is_current():
    assert georef_fit.main([str(GEOREF_PATH)]) == 0


def test_points_and_sources_are_complete():
    ctrl, check = G["control_points"], G["check_points"]
    assert len(ctrl) >= 6 and len(check) >= 2
    assert not {p["id"] for p in ctrl} & {p["id"] for p in check}
    sources = G["sources"]
    for key, s in sources.items():
        if key == "access_note":
            continue
        assert s["url"].startswith("https://") and s["licence"].startswith("Public domain") and s["fetched"]
        assert "apsu.edu" not in s["url"] and "mcgtn.org" not in s["url"]
    for p in ctrl + check:
        for key in p["lonlat_source"].split(" x "):
            assert key in sources, p["id"]
        lon, lat = p["lonlat"]
        assert -87.7 < lon < -87.0 and 36.2 < lat < 36.7
    # well spread: control points reach every side of the county
    xs = [p["page_xy"][0] for p in ctrl]
    ys = [p["page_xy"][1] for p in ctrl]
    assert max(xs) - min(xs) > 1500 and max(ys) - min(ys) > 1200


def test_fit_quality_and_margin():
    f = G["fit"]
    assert f["rms_residual_m"] <= 5 and f["max_check_error_m"] <= 10
    assert max(f["leave_one_out_m"].values()) <= 10
    assert abs(f["rotation_deg"]) < 0.05 and abs(f["scale_ratio_x_to_y"] - 1) < 0.001   # State Plane, north up
    basis = G["boundary_margin_basis"]
    assert basis["transform_m"] >= max(f["leave_one_out_m"].values())
    assert G["boundary_margin_m"] == basis["transform_m"] + basis["traced_shapes_m"] + basis["geocoder_m"]


def test_georef_belongs_to_the_traced_pdf():
    assert G["source_sha256"] == D["source_sha256"]
    bad = dict(G, source_sha256="0" * 64)
    with pytest.raises(ValueError):
        gr.district_for(-87.3587, 36.5276, D, bad)


def _check_point(pid):
    return next(p for p in G["check_points"] if p["id"] == pid)["lonlat"]


# Expected districts were read off the source PDF (rendered at 6x with the transformed point marked, 2026-11-08):
# each point sits on the drawn road crossing, inside the fill of the district named here.
@pytest.mark.parametrize("pid,district", [
    ("franklin-2nd", 5),            # downtown Clarksville, pink district 5, ~580 m from its nearest line
    ("warfield-rossview", 1),
    ("slayden-hwy13", 6),
    ("rossview-wilma", 14),
])
def test_held_out_points_land_in_their_district(pid, district):
    got = gr.district_for(*_check_point(pid), D, G)
    assert got["district"] == district and not got["near_boundary"], got


def test_point_on_a_district_line_is_flagged():
    # Hwy 48 x Lone Oak Rd: the road crossing lies on the line between districts 6 and 4
    got = gr.district_for(*_check_point("hwy48-loneoak"), D, G)
    assert got["near_boundary"] and got["distance_m"] < G["boundary_margin_m"]


def test_outside_the_county():
    far = gr.district_for(-87.44, 36.665, D, G)                     # Oak Grove, KY, 2.7 km north of the line
    assert far["district"] is None and not far["near_boundary"] and far["closest"] == 8
    lon, lat = _check_point("i24-ky")                                # I-24 at the state line
    edge = gr.district_for(lon, lat + 0.0003, D, G)                  # ~33 m into Kentucky
    assert edge["district"] is None and edge["near_boundary"]


def test_default_files_are_the_locality_config():
    assert gr.district_for(*_check_point("franklin-2nd"))["district"] == 5
