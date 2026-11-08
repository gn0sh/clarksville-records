"""Extract seat shapes (county districts, city wards) from a vector map PDF into a per-locality JSON file.

The county's redistricting PDFs draw each area as many small filled polygons (one colour per district, black 0.48pt
stroke) and print the district number as text inside it. This tool:
  1. takes every filled path on the page (straight-line subpaths only, as these PDFs use),
  2. unions them per fill colour and splits each union into connected parts,
  3. reads the printed numbers (digits whose glyphs sit side by side on one baseline form one number),
  4. gives each part to the number printed inside it (a colour can hold two districts: each part is matched on its
     own); a part with no number inside joins the same-colour part it touches most, or is reported,
  5. writes simplified SVG path data in PDF user space (y down, as pdfplumber reports it) plus a label point
     (pole of inaccessibility) per district and the county outline (union of all parts).

No projection, no geo data: the shapes are a drawing of the source PDF. Run (dev tool; needs pdfplumber, shapely):

  python -I tools/extract_pdf_map.py build/maps/Redistricting20211018.pdf \
      --out config/localities/montgomery-tn/districts.json --merge config/localities/montgomery-tn/districts.json \
      --source-url URL --source-title TITLE --fetched 2026-11-08 --effective 2022-09-01 --note NOTE \
      --expect 21 --label-size 15.6 --renumber 19:20,20:19 --water-colour 0.59216,0.85882,0.94902

The output is checked by tests/test_map_seats.py and loaded by sitegen (sitegen/seats.py); this script is never
imported at build time.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict

SIMPLIFY = 0.8          # PDF points; the page is 1728pt wide, so this is invisible at any screen size
CLOSE = 0.6             # closes hairline gaps between neighbouring pieces before the union
MIN_PART_AREA = 4.0     # square points; specks below this are dropped (reported in the summary)


def _polygons(page):
    from shapely.geometry import Polygon
    by_colour = defaultdict(list)
    for c in page.curves:
        # district pieces: filled and outlined in black (water and road casings are other styles)
        if not c.get("fill") or not c.get("stroke") or tuple(c.get("stroking_color") or ()) != (0.0, 0.0, 0.0):
            continue
        pts = [xy for op, *rest in c["path"] for xy in rest if op in ("m", "l")]
        if any(op not in ("m", "l", "h") for op, *_ in c["path"]):
            raise SystemExit("curved segments found; this tool handles straight-line paths only")
        if len(pts) < 3:
            continue
        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.area > 0:
            by_colour[tuple(round(v, 4) for v in c["non_stroking_color"])].append(poly)
    return by_colour


def _numbers(page, pattern: str):
    """Printed labels: consecutive digit glyphs on one baseline, at most half a glyph apart."""
    chars = sorted((ch for ch in page.chars if ch["text"].isdigit()), key=lambda ch: (round(ch["top"]), ch["x0"]))
    out, cur = [], []
    for ch in chars:
        if cur and abs(ch["top"] - cur[-1]["top"]) < 1 and ch["x0"] - cur[-1]["x1"] < ch["size"] * 0.5 \
                and abs(ch["size"] - cur[-1]["size"]) < 0.1:
            cur.append(ch)
            continue
        if cur:
            out.append(cur)
        cur = [ch]
    if cur:
        out.append(cur)
    labels = []
    for grp in out:
        text = "".join(ch["text"] for ch in grp)
        if not re.fullmatch(pattern, text):
            continue
        x = (grp[0]["x0"] + grp[-1]["x1"]) / 2
        y = (grp[0]["top"] + grp[0]["bottom"]) / 2
        labels.append((int(text), x, y, grp[0]["size"]))
    return labels


def _path_d(geom, nd=1) -> str:
    from shapely.geometry import MultiPolygon
    polys = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    parts = []
    for p in polys:
        for ring in [p.exterior, *p.interiors]:
            xy = list(ring.coords)[:-1]
            parts.append("M" + "L".join(f"{x:.{nd}f} {y:.{nd}f}" for x, y in xy) + "Z")
    return "".join(parts)


def _water(page, colour, clip, simplify):
    """Water areas (river, lakes) drawn as fills of one colour, clipped to the outline."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    polys = []
    for c in page.curves:
        if c.get("fill") and tuple(round(v, 4) for v in (c.get("non_stroking_color") or ())) == colour:
            pts = [xy for op, *rest in c["path"] for xy in rest if op in ("m", "l")]
            if len(pts) >= 3:
                polys.append(Polygon(pts).buffer(0))
    if not polys:
        return None
    geom = unary_union(polys).intersection(clip).simplify(simplify * 2, preserve_topology=True)
    keep = [g for g in getattr(geom, "geoms", [geom]) if g.geom_type == "Polygon" and g.area >= 200]
    return unary_union(keep) if keep else None


def extract(pdf_path: str, page_no: int = 0, label_pattern: str = r"[1-9]\d?", label_size: float | None = None,
            simplify: float = SIMPLIFY, renumber: dict | None = None, water_colour: tuple | None = None):
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_no]
        by_colour = _polygons(page)
        labels = _numbers(page, label_pattern)
        width, height = float(page.width), float(page.height)
        page_ref = page
        if label_size is not None:
            labels = [lb for lb in labels if abs(lb[3] - label_size) < 0.2]
        if renumber:
            labels = [(renumber.get(n, n), x, y, sz) for n, x, y, sz in labels]
        return _assemble(by_colour, labels, simplify, width, height,
                         lambda clip: _water(page_ref, water_colour, clip, simplify) if water_colour else None)


def _assemble(by_colour, labels, simplify, width, height, water):
    from shapely.geometry import Point
    from shapely.ops import polylabel, unary_union

    parts = []          # (colour, polygon)
    dropped = 0
    for colour, polys in by_colour.items():
        merged = unary_union([p.buffer(CLOSE, join_style="mitre") for p in polys]).buffer(-CLOSE, join_style="mitre")
        for g in getattr(merged, "geoms", [merged]):
            if g.area < MIN_PART_AREA:
                dropped += 1
                continue
            parts.append((colour, g))

    owner: dict[int, int] = {}          # part index -> district number
    problems, notes = [], []
    for num, x, y, _size in labels:
        hits = [i for i, (_c, g) in enumerate(parts) if g.contains(Point(x, y))]
        if len(hits) != 1:
            problems.append(f"label {num} at ({x:.0f},{y:.0f}) lies in {len(hits)} parts")
            continue
        if hits[0] in owner and owner[hits[0]] != num:
            problems.append(f"labels {owner[hits[0]]} and {num} lie in the same part")
        owner[hits[0]] = num
    # unlabelled parts: join the same-colour labelled part they share the longest edge with
    for i, (colour, g) in enumerate(parts):
        if i in owner:
            continue
        best, best_len = None, 0.0
        for j, (c2, g2) in enumerate(parts):
            if j in owner and c2 == colour:
                shared = g.buffer(CLOSE * 2).intersection(g2.boundary).length
                if shared > best_len:
                    best, best_len = owner[j], shared
        same = {owner[j] for j, (c2, _g2) in enumerate(parts) if j in owner and c2 == colour}
        if best is None and len(same) == 1:
            best = same.pop()          # a detached piece (exclave) in a colour only one district uses
            notes.append(f"detached part of area {g.area:.0f} at {tuple(round(v) for v in g.centroid.coords[0])} "
                         f"given to {best} (only district in its colour)")
        if best is None:
            problems.append(f"unlabelled part of area {g.area:.0f} at {tuple(round(v) for v in g.centroid.coords[0])}")
        else:
            owner[i] = best

    shapes = defaultdict(list)
    for i, num in owner.items():
        shapes[num].append(parts[i][1])
    districts = []
    for num in sorted(shapes):
        geom = unary_union(shapes[num]).simplify(simplify, preserve_topology=True)
        biggest = max(getattr(geom, "geoms", [geom]), key=lambda g: g.area)
        lp = polylabel(biggest, tolerance=1.0)
        printed = next(((x, y) for n, x, y, _s in labels if n == num), None)
        districts.append({"number": num, "path": _path_d(geom), "label_xy": [round(lp.x, 1), round(lp.y, 1)],
                          "printed_label_xy": [round(printed[0], 1), round(printed[1], 1)] if printed else None,
                          "area": round(geom.area)})
    outline = unary_union([g.buffer(CLOSE) for _c, g in parts]).buffer(-CLOSE).simplify(simplify, preserve_topology=True)
    minx, miny, maxx, maxy = outline.bounds
    pad = 8
    summary = {"colours": len(by_colour), "parts": len(parts), "dropped_specks": dropped, "labels": len(labels),
               "problems": problems, "notes": notes, "page_size": [width, height]}
    river = water(outline)
    return {
        "river_path": _path_d(river) if river is not None else None,
        "viewBox": f"{minx - pad:.0f} {miny - pad:.0f} {maxx - minx + 2 * pad:.0f} {maxy - miny + 2 * pad:.0f}",
        "outline_path": _path_d(outline),
        "districts": districts,
    }, summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, default=0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source-url", required=True)
    ap.add_argument("--source-title", required=True)
    ap.add_argument("--fetched", required=True)
    ap.add_argument("--effective", default=None)
    ap.add_argument("--note", default="")
    ap.add_argument("--expect", type=int, default=None, help="number of districts the map must yield")
    ap.add_argument("--label-size", type=float, default=None, help="font size of the district numbers, if needed")
    ap.add_argument("--renumber", default=None,
                    help="printed:actual pairs, e.g. 19:20,20:19 when the adopted map renumbered districts")
    ap.add_argument("--water-colour", default=None, help="fill colour of water areas, e.g. 0.59216,0.85882,0.94902")
    ap.add_argument("--merge", default=None, help="JSON file whose other keys (e.g. wards) are kept in --out")
    a = ap.parse_args(argv)
    renumber = dict(tuple(int(v) for v in pair.split(":")) for pair in a.renumber.split(",")) if a.renumber else None
    water = tuple(round(float(v), 4) for v in a.water_colour.split(",")) if a.water_colour else None
    data, summary = extract(a.pdf, a.page, label_size=a.label_size, renumber=renumber, water_colour=water)
    summary["renumbered"] = a.renumber
    nums = [d["number"] for d in data["districts"]]
    if a.expect and nums != list(range(1, a.expect + 1)):
        summary["problems"].append(f"expected districts 1..{a.expect}, got {nums}")
    import hashlib
    with open(a.pdf, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    out = {"source_url": a.source_url, "source_title": a.source_title, "source_sha256": sha, "fetched": a.fetched,
           "effective": a.effective, "note": a.note, "coordinates": "PDF user space of the source page, y down",
           **data}
    if a.merge:
        try:
            with open(a.merge) as fh:
                old = json.load(fh)
            out.update({k: v for k, v in old.items() if k not in out})
        except FileNotFoundError:
            pass
    for d in out["districts"]:
        d.pop("area", None)
    with open(a.out, "w") as fh:
        json.dump(out, fh, indent=1)
        fh.write("\n")
    print(json.dumps(summary, indent=1))
    return 1 if summary["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
