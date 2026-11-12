"""Trace the city ward shapes from the RPC "City Council Wards" poster PDF into the county map's drawing.

The poster (Esri ArcGIS Pro export, TN State Plane, north up) fills each ward as one closed polygon per part, all
with the same outline style, and repeats each fill colour once as a legend swatch beside "N - <member>". This tool:
  1. takes the filled paths with the ward outline colour (straight-line rings only, as the poster uses),
  2. sets aside the 12 legend swatches (the parts inside --legend-box) and reads each swatch's number from the
     legend line beside it (digits only: the member names are never read or stored),
  3. gives every map part the number of its fill colour, and checks that the large printed ward number lies inside
     a part of that same colour (two independent readings of the poster must agree),
  4. moves the shapes from the poster's page space into the county district map's page space through State Plane:
     poster page -> metres (the inverse of wards-georef.json's fitted affine) -> district page (georef.json), so the
     ward paths sit on the same drawing and the same georef.json places an address on both layers,
  5. writes simplified SVG path data per ward, a label point, the composite transform, the measured simplification
     error and the source details into the "wards" block of districts.json (every other key is kept).

Run after editing wards-georef.json (and after tools/georef_fit.py --write on it). Dev tool; needs pdfplumber, shapely:

  python -I tools/extract_ward_poster.py data/store/<sha256>.pdf \
      --districts config/localities/montgomery-tn/districts.json \
      --georef config/localities/montgomery-tn/georef.json \
      --wards-georef config/localities/montgomery-tn/wards-georef.json --fetched 2026-11-10

The output is checked by tests/test_ward_map.py and read by sitegen (views.map_context, georef.ward_for).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sitegen.georef import apply_affine, rings  # noqa: E402

OUTLINE = (0.0, 0.149, 0.451)      # the ward outline colour (stroke) on the 2026-02-25 poster
LABEL_SIZE = 72.3                  # font size of the large ward numbers printed on the map
LEGEND_BOX = (60.0, 1580.0, 160.0, 2040.0)   # page box (x0, y0, x1, y1) holding the 12 legend swatches
LEGEND_MIN_SIZE = 15.0            # legend lines are 19.3 pt; smaller text in the same box is map labels
SIMPLIFY_PT = 0.12                 # district-page points (about 3.4 m); see the measured error in the output
EXPECT = 12


def invert(m: list[list[float]]) -> list[list[float]]:
    (a, b, c), (d, e, f) = m
    det = a * e - b * d
    return [[e / det, -b / det, (b * f - e * c) / det], [-d / det, a / det, (d * c - a * f) / det]]


def compose(outer: list[list[float]], inner: list[list[float]]) -> list[list[float]]:
    """outer(inner(p)) as one affine."""
    (a, b, c), (d, e, f) = outer
    (g, h, i), (j, k, l_) = inner
    return [[a * g + b * j, a * h + b * k, a * i + b * l_ + c], [d * g + e * j, d * h + e * k, d * i + e * l_ + f]]


def _colour(v) -> tuple:
    return tuple(round(x, 4) for x in (v or ()))


def read_poster(pdf_path: str, page_no: int = 0):
    """The ward fill parts [(colour, Polygon)], the legend swatches [(colour, Polygon)], the printed numbers and the
    legend lines' leading numbers, all in poster page space (y down)."""
    import pdfplumber
    from shapely.geometry import Polygon

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_no]
        parts, swatches = [], []
        for c in page.curves:
            if not (c.get("fill") and c.get("stroke") and _colour(c.get("stroking_color")) == OUTLINE):
                continue
            if any(op not in ("m", "l", "h") for op, *_ in c["path"]) or sum(op == "m" for op, *_ in c["path"]) != 1:
                raise SystemExit("a ward fill has curves or several subpaths; this tool handles one straight ring")
            pts = [xy for op, *rest in c["path"] for xy in rest if op in ("m", "l")]
            poly = Polygon(pts)
            if not poly.is_valid:
                poly = poly.buffer(0)
            x0, y0, x1, y1 = poly.bounds
            lb = LEGEND_BOX
            (swatches if x0 >= lb[0] and y0 >= lb[1] and x1 <= lb[2] and y1 <= lb[3] else parts).append(
                (_colour(c["non_stroking_color"]), poly))
        chars = list(page.chars)
    labels = []
    big = sorted((ch for ch in chars if ch["text"].isdigit() and abs(ch["size"] - LABEL_SIZE) < 0.2),
                 key=lambda ch: (round(ch["top"]), ch["x0"]))
    run: list = []
    for ch in big + [None]:
        if run and (ch is None or abs(ch["top"] - run[-1]["top"]) > 1 or ch["x0"] - run[-1]["x1"] > ch["size"] * 0.5):
            labels.append((int("".join(c["text"] for c in run)), (run[0]["x0"] + run[-1]["x1"]) / 2,
                           (run[0]["top"] + run[0]["bottom"]) / 2))
            run = []
        if ch is not None:
            run.append(ch)
    legend = {}
    for colour, sw in swatches:
        x0, y0, x1, y1 = sw.bounds
        line = sorted((ch for ch in chars if x1 < ch["x0"] < x1 + 80 and y0 <= (ch["top"] + ch["bottom"]) / 2 <= y1
                       and ch["size"] > LEGEND_MIN_SIZE), key=lambda ch: ch["x0"])   # map labels overlap the box
        m = re.match(r"\s*(\d{1,2})\s*-", "".join(ch["text"] for ch in line))
        if not m:
            raise SystemExit(f"legend swatch at {sw.bounds} has no 'N -' beside it")
        legend[colour] = int(m.group(1))
    return parts, swatches, labels, legend


def assign(parts, labels, legend) -> tuple[dict, list]:
    """{ward number: [Polygon]} from the legend colours, checked against the printed numbers."""
    from shapely.geometry import Point

    problems = []
    if sorted(legend.values()) != list(range(1, EXPECT + 1)) or len(legend) != EXPECT:
        problems.append(f"legend numbers {sorted(legend.values())}, expected 1..{EXPECT} once each")
    shapes = defaultdict(list)
    for colour, poly in parts:
        if colour not in legend:
            problems.append(f"a ward part at {tuple(round(v) for v in poly.bounds)} has a colour not in the legend")
            continue
        shapes[legend[colour]].append(poly)
    seen = set()
    for num, x, y in labels:
        inside = [n for n, ps in shapes.items() if any(p.contains(Point(x, y)) for p in ps)]
        if inside != [num]:
            problems.append(f"printed {num} at ({x:.0f},{y:.0f}) lies in ward part(s) {inside}")
        seen.add(num)
    if seen != set(range(1, EXPECT + 1)):
        problems.append(f"printed numbers {sorted(seen)}, expected 1..{EXPECT}")
    return dict(shapes), problems


def _path_d(geom, nd=1) -> str:
    polys = list(getattr(geom, "geoms", [geom]))
    parts = []
    for p in polys:
        for ring in [p.exterior, *p.interiors]:
            xy = list(ring.coords)[:-1]
            parts.append("M" + "L".join(f"{x:.{nd}f} {y:.{nd}f}" for x, y in xy) + "Z")
    return "".join(parts)


def build(pdf_path: str, districts: dict, georef: dict, wards_georef: dict, simplify: float = SIMPLIFY_PT):
    from shapely import affinity
    from shapely.geometry import MultiPolygon, Point, Polygon
    from shapely.ops import polylabel, unary_union

    parts, _swatches, labels, legend = read_poster(pdf_path)
    shapes, problems = assign(parts, labels, legend)
    to_metres = invert(wards_georef["affine"])                 # poster page -> State Plane metres
    m = compose(georef["affine"], to_metres)                    # poster page -> district page
    flat = [m[0][0], m[0][1], m[1][0], m[1][1], m[0][2], m[1][2]]
    scale = 1 / math.sqrt(abs(georef["affine"][0][0] * georef["affine"][1][1]
                              - georef["affine"][0][1] * georef["affine"][1][0]))   # metres per district-page unit
    wards, max_err = [], 0.0
    full = {}
    for num in sorted(shapes):
        geom = affinity.affine_transform(unary_union(shapes[num]), flat)
        full[num] = geom
        simple = geom.simplify(simplify, preserve_topology=True)
        d = _path_d(simple)
        # measured error of what is published: the rounded, simplified path against the unsimplified trace
        back = MultiPolygon([Polygon(r) for r in rings(d)])
        max_err = max(max_err, geom.boundary.hausdorff_distance(back.boundary))
        biggest = max(getattr(simple, "geoms", [simple]), key=lambda g: g.area)
        lp = polylabel(biggest, tolerance=0.5)
        printed = next(((x, y) for n, x, y in labels if n == num), None)
        px, py = apply_affine(m, *printed)
        wards.append({"number": num, "path": d, "label_xy": [round(lp.x, 1), round(lp.y, 1)],
                      "printed_label_xy": [round(px, 1), round(py, 1)], "parts": len(getattr(simple, "geoms", [1]))})
    # neighbours drawn edge to edge on the poster must not overlap after the move (beyond a hairline)
    nums = sorted(full)
    for i, a in enumerate(nums):
        for b in nums[i + 1:]:
            ov = full[a].intersection(full[b]).area * scale * scale
            if ov > 2000:
                problems.append(f"wards {a} and {b} overlap by {ov:.0f} m2")
    outline = unary_union(list(full.values()))
    summary = {"parts": len(parts), "labels": len(labels), "legend": len(legend), "problems": problems,
               "max_simplify_error_m": round(max_err * scale, 1), "city_area_km2": round(outline.area * scale ** 2 / 1e6, 2),
               "label_inside": all(Point(*w["printed_label_xy"]).within(full[w["number"]]) for w in wards)}
    return wards, m, summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pdf")
    ap.add_argument("--districts", required=True)
    ap.add_argument("--georef", required=True)
    ap.add_argument("--wards-georef", required=True)
    ap.add_argument("--fetched", required=True)
    ap.add_argument("--simplify", type=float, default=SIMPLIFY_PT)
    a = ap.parse_args(argv)
    dpath = Path(a.districts)
    districts = json.loads(dpath.read_text(encoding="utf-8"))
    georef = json.loads(Path(a.georef).read_text(encoding="utf-8"))
    wg = json.loads(Path(a.wards_georef).read_text(encoding="utf-8"))
    sha = hashlib.sha256(Path(a.pdf).read_bytes()).hexdigest()
    if wg["source_sha256"] != sha:
        raise SystemExit("wards-georef.json was fitted to a different poster PDF")
    if georef["source_sha256"] != districts["source_sha256"]:
        raise SystemExit("georef.json does not belong to districts.json")
    wards, m, summary = build(a.pdf, districts, georef, wg, a.simplify)
    scale = 1 / math.sqrt(abs(georef["affine"][0][0] * georef["affine"][1][1]
                              - georef["affine"][0][1] * georef["affine"][1][0]))
    districts["wards"] = {
        "status": "available",
        "source_url": wg["source_url"],
        "source_title": wg["source_title"],
        "source_sha256": sha,
        "source_updated": wg["source_updated"],
        "fetched": a.fetched,
        "note": ("Shapes traced from the vector drawing of the RPC poster and moved into this map's page space "
                 "through Tennessee State Plane (wards-georef.json, then georef.json). Only ward numbers are read "
                 "from the poster, never its member names. Annexations after the poster's date are not on it."),
        "georef": Path(a.wards_georef).name,
        "boundary_margin_m": wg["boundary_margin_m"],
        "page_transform": [[round(v, 12) for v in row] for row in m],
        "simplify_pt": a.simplify,
        "max_simplify_error_m": summary["max_simplify_error_m"],
        "metres_per_page_unit": round(scale, 4),
        "wards": [{k: w[k] for k in ("number", "path", "label_xy", "printed_label_xy")} for w in wards],
    }
    print(json.dumps(summary, indent=1))
    if summary["problems"] or not summary["label_inside"]:
        print("not written: the shapes have problems", file=sys.stderr)
        return 1
    dpath.write_text(json.dumps(districts, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
