"""Fit the page-space georeference of a locality's district map from the control points in its georef.json.

georef.json lists control points (a feature seen both on the source PDF and in a public-domain geo source, with both
coordinates and the source of each) and check points (the same, but held out of the fit). This tool projects the
lon/lat side with the file's projection, fits a least-squares affine to page space, and records the residual of every
control point, its leave-one-out error, and the error at every check point, all in ground metres.

  python -I tools/georef_fit.py config/localities/montgomery-tn/georef.json          # check: exit 1 if stale
  python -I tools/georef_fit.py config/localities/montgomery-tn/georef.json --write  # refit and store

Run it after editing a point. The stored numbers are checked by tests/test_georef.py; nothing at build time runs it.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sitegen.georef import apply_affine, fit_affine, metres_per_unit, project  # noqa: E402


def _err(m, scale, xy, page) -> float:
    u, v = apply_affine(m, *xy)
    return math.hypot(u - page[0], v - page[1]) * scale


def fit(g: dict) -> dict:
    proj = g["projection"]
    ctrl = g["control_points"]
    src = [project(*p["lonlat"], proj) for p in ctrl]
    dst = [tuple(p["page_xy"]) for p in ctrl]
    m = fit_affine(src, dst)
    scale = metres_per_unit(m)
    resid = [_err(m, scale, s, d) for s, d in zip(src, dst)]
    loo = []
    for i in range(len(ctrl)):
        mi = fit_affine(src[:i] + src[i + 1:], dst[:i] + dst[i + 1:])
        loo.append(_err(mi, scale, src[i], dst[i]))
    checks = [_err(m, scale, project(*p["lonlat"], proj), p["page_xy"]) for p in g["check_points"]]
    return {
        "affine": [[round(v, 12) for v in row] for row in m],
        "metres_per_page_unit": round(scale, 4),
        "rotation_deg": round(math.degrees(math.atan2(-m[0][1], m[0][0])), 4),
        "scale_ratio_x_to_y": round(abs(m[0][0] / m[1][1]), 6),
        "residual_m": {p["id"]: round(r, 1) for p, r in zip(ctrl, resid)},
        "rms_residual_m": round(math.sqrt(sum(r * r for r in resid) / len(resid)), 2),
        "leave_one_out_m": {p["id"]: round(r, 1) for p, r in zip(ctrl, loo)},
        "check_error_m": {p["id"]: round(e, 1) for p, e in zip(g["check_points"], checks)},
        "max_check_error_m": round(max(checks), 1),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("georef")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    path = Path(a.georef)
    g = json.loads(path.read_text(encoding="utf-8"))
    res = fit(g)
    stored = {k: g.get(k) if k == "affine" else g.get("fit", {}).get(k) for k in res}
    if a.write:
        g["affine"] = res.pop("affine")
        g["fit"] = res
        path.write_text(json.dumps(g, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(g["fit"], indent=1))
        return 0
    if stored != res:
        print("georef.json is stale; rerun with --write", file=sys.stderr)
        return 1
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
