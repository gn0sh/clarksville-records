"""Place a lon/lat point on the traced district map (config/localities/<locality>/districts.json) and name its district.

The district shapes are in the source PDF's page space (points, y down). georef.json holds the map's projection and an
affine transform from projected metres to that page space, fitted to control points that appear both in the PDF and
in a public-domain source (tools/georef_fit.py fits it and records the residuals). Pure Python, no geo libraries:
the same few lines can be ported to the browser.

district_for() answers with the district whose shape holds the point, its distance to the nearest district line in
metres, and whether that distance is under the locality's boundary margin (then the page should say "near a district
line, check the official lookup" instead of a plain answer). ward_for() does the same for the city wards, which
tools/extract_ward_poster.py traces into the same page space, with their own margin.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

_RING = re.compile(r"M([^Z]+)Z")


# --- projection -------------------------------------------------------------------------------------------------

def _lcc(p: dict):
    """Forward Lambert conformal conic (2 standard parallels) on an ellipsoid, as in EPSG method 9802."""
    a, f = p["semi_major_m"], 1 / p["inverse_flattening"]
    e = math.sqrt(2 * f - f * f)

    def m(phi):
        return math.cos(phi) / math.sqrt(1 - (e * math.sin(phi)) ** 2)

    def t(phi):
        s = e * math.sin(phi)
        return math.tan(math.pi / 4 - phi / 2) / ((1 - s) / (1 + s)) ** (e / 2)

    p1, p2, p0 = (math.radians(p[k]) for k in ("lat_1", "lat_2", "lat_0"))
    n = (math.log(m(p1)) - math.log(m(p2))) / (math.log(t(p1)) - math.log(t(p2)))
    big_f = m(p1) / (n * t(p1) ** n)
    r0 = a * big_f * t(p0) ** n

    def fwd(lon: float, lat: float) -> tuple[float, float]:
        r = a * big_f * t(math.radians(lat)) ** n
        theta = n * math.radians(lon - p["lon_0"])
        return p["x_0"] + r * math.sin(theta), p["y_0"] + r0 - r * math.cos(theta)

    return fwd


def project(lon: float, lat: float, projection: dict) -> tuple[float, float]:
    if projection.get("method") != "lambert_conformal_conic_2sp":
        raise ValueError(f"unsupported projection method {projection.get('method')!r}")
    return _lcc(projection)(lon, lat)


# --- affine fit (control points -> transform) -----------------------------------------------------------------------

def _solve3(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting for a 3x3 system."""
    m = [row[:] + [v] for row, v in zip(a, b)]
    for c in range(3):
        piv = max(range(c, 3), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-12:
            raise ValueError("control points are degenerate (collinear or repeated)")
        m[c], m[piv] = m[piv], m[c]
        for r in range(3):
            if r != c:
                k = m[r][c] / m[c][c]
                m[r] = [x - k * y for x, y in zip(m[r], m[c])]
    return [m[i][3] / m[i][i] for i in range(3)]


def fit_affine(src: list[tuple[float, float]], dst: list[tuple[float, float]]) -> list[list[float]]:
    """Least-squares affine [[a, b, c], [d, e, f]] with dst = (a x + b y + c, d x + e y + f).

    Source coordinates are centred before solving (projected metres are ~1e5, which would ill-condition the normal
    equations) and the offset is folded back into c and f."""
    if len(src) != len(dst) or len(src) < 3:
        raise ValueError("need at least 3 matching points")
    ox = sum(x for x, _ in src) / len(src)
    oy = sum(y for _, y in src) / len(src)
    xs = [(x - ox, y - oy, 1.0) for x, y in src]
    ata = [[sum(r[i] * r[j] for r in xs) for j in range(3)] for i in range(3)]
    rows = []
    for k in range(2):
        atb = [sum(r[i] * d[k] for r, d in zip(xs, dst)) for i in range(3)]
        a, b, c = _solve3(ata, atb)
        rows.append([a, b, c - a * ox - b * oy])
    return rows


def apply_affine(m: list[list[float]], x: float, y: float) -> tuple[float, float]:
    return m[0][0] * x + m[0][1] * y + m[0][2], m[1][0] * x + m[1][1] * y + m[1][2]


def metres_per_unit(m: list[list[float]]) -> float:
    """Ground metres per page unit (the transform's mean scale)."""
    return 1 / math.sqrt(abs(m[0][0] * m[1][1] - m[0][1] * m[1][0]))


def to_page(lon: float, lat: float, georef: dict) -> tuple[float, float]:
    x, y = project(lon, lat, georef["projection"])
    return apply_affine(georef["affine"], x, y)


# --- point in district ------------------------------------------------------------------------------------------

def rings(path: str) -> list[list[tuple[float, float]]]:
    """The closed rings of an M...L...Z path (the only commands districts.json uses)."""
    return [[tuple(float(v) for v in p.split()) for p in sub.split("L")] for sub in _RING.findall(path)]


def _inside(rs, x: float, y: float) -> bool:
    """Even-odd ray casting over every ring, so holes and detached parts both work."""
    hit = False
    for r in rs:
        for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]):
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                hit = not hit
    return hit


def _seg_dist(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _edge_dist(rs, x: float, y: float) -> float:
    return min(_seg_dist(x, y, *a, *b) for r in rs for a, b in zip(r, r[1:] + r[:1]))


def district_for(lon: float, lat: float, districts: dict | None = None, georef: dict | None = None) -> dict:
    """The district at (lon, lat), WGS84/NAD83 degrees.

    Returns {"district": n or None, "distance_m": metres to the nearest district line (the county line included),
    "near_boundary": bool, "page_xy": (x, y)}. "district" is None outside every shape. A point that falls in two
    shapes (the traced shapes are simplified one by one, so neighbours can overlap by a sliver) gets district None,
    "overlap": [both] and near_boundary True; a point in no shape gets "closest": the shape whose edge is nearest.
    With no districts/georef given, the locality's config files are used."""
    if districts is None or georef is None:
        d0, g0 = _locality_files()
        districts = districts if districts is not None else d0
        georef = georef if georef is not None else g0
    if georef.get("source_sha256") != districts.get("source_sha256"):
        raise ValueError("georef.json was fitted to a different source PDF than districts.json")
    return _locate("district", [(d["number"], d["path"]) for d in districts["districts"]], lon, lat, georef,
                   float(georef["boundary_margin_m"]))


def ward_for(lon: float, lat: float, districts: dict | None = None, georef: dict | None = None) -> dict | None:
    """The city ward at (lon, lat), or None when the map has no ward shapes.

    The ward paths (districts.json "wards", traced by tools/extract_ward_poster.py) are stored in the district map's
    page space, so the same georef.json places the point, and the district fit's own error cancels out. The margin is
    the wards' own (boundary_margin_m, basis in wards-georef.json). Same answer shape as district_for, keyed "ward":
    a point in no ward is outside the city as the ward map draws it, and the city line counts as a ward line."""
    if districts is None or georef is None:
        d0, g0 = _locality_files()
        districts = districts if districts is not None else d0
        georef = georef if georef is not None else g0
    wards = wards_of(districts)
    if wards is None:
        return None
    if georef.get("source_sha256") != districts.get("source_sha256"):
        raise ValueError("georef.json was fitted to a different source PDF than districts.json")
    return _locate("ward", [(w["number"], w["path"]) for w in wards["wards"]], lon, lat, georef,
                   float(wards["boundary_margin_m"]))


def wards_of(districts: dict | None) -> dict | None:
    """The map's ward block when it holds ward shapes ("status": "available"), else None (the landing then keeps the
    district-only lookup and the "coming" ward layer). Shapes with no margin are an error, never a silent default."""
    w = (districts or {}).get("wards") or {}
    if w.get("status") != "available" or not w.get("wards"):
        return None
    if not float(w.get("boundary_margin_m") or 0) > 0:
        raise ValueError("districts.json wards: boundary_margin_m must be set (basis in wards-georef.json)")
    return w


def _locate(key: str, shapes, lon: float, lat: float, georef: dict, margin: float) -> dict:
    """Point in shape over [(number, path)] in the georef's page space; the answer district_for/ward_for return."""
    x, y = to_page(lon, lat, georef)
    scale = metres_per_unit(georef["affine"])
    hits, best = [], (math.inf, None)
    for num, rs in ((n, rings(p)) for n, p in shapes):
        dist = _edge_dist(rs, x, y) * scale
        if dist < best[0]:
            best = (dist, num)
        if _inside(rs, x, y):
            hits.append(num)
    out = {key: hits[0] if len(hits) == 1 else None, "distance_m": round(best[0], 1),
           "near_boundary": best[0] < margin or len(hits) > 1, "page_xy": (round(x, 2), round(y, 2))}
    if len(hits) > 1:
        out["overlap"] = sorted(hits)
    elif not hits:
        out["closest"] = best[1]
    return out


def load_for_map(districts_path, districts: dict | None) -> dict | None:
    """georef.json next to the map file, or None when there is no map or no georef (the landing then has no address
    box). A georef fitted to another source PDF is an error, never a silent fallback."""
    if districts is None or districts_path is None:
        return None
    path = Path(districts_path).parent / "georef.json"
    if not path.is_file():
        return None
    g = json.loads(path.read_text(encoding="utf-8"))
    if g.get("source_sha256") != districts.get("source_sha256"):
        raise ValueError(f"{path}: fitted to a different source PDF than {districts_path}")
    project(-86.0, 35.0, g["projection"])      # unsupported method -> ValueError at build time, not in the browser
    return g


def _locality_files() -> tuple[dict, dict]:
    from sitegen.config import DISTRICTS_PATH
    return (json.loads(Path(DISTRICTS_PATH).read_text(encoding="utf-8")),
            json.loads((Path(DISTRICTS_PATH).parent / "georef.json").read_text(encoding="utf-8")))
