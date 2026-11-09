/* Which district holds a lon/lat point: a port of sitegen/georef.py district_for (tests/test_georef_js.py checks
   that both give the same answer). lon/lat -> the locality's State Plane zone (Lambert conformal conic, 2 standard parallels)
   -> the fitted affine -> page space of the traced map, then even-odd point-in-polygon against the district paths.
   First-party, no libraries, no network calls. Exposes window.CRGeoref (module.exports under node). */
(function (root) {
  "use strict";

  function lcc(p) {
    if (p.method !== "lambert_conformal_conic_2sp") {
      throw new Error("unsupported projection method " + p.method);
    }
    var a = p.semi_major_m, f = 1 / p.inverse_flattening, e = Math.sqrt(2 * f - f * f);
    var rad = Math.PI / 180;
    function m(phi) { return Math.cos(phi) / Math.sqrt(1 - Math.pow(e * Math.sin(phi), 2)); }
    function t(phi) {
      var s = e * Math.sin(phi);
      return Math.tan(Math.PI / 4 - phi / 2) / Math.pow((1 - s) / (1 + s), e / 2);
    }
    var p1 = p.lat_1 * rad, p2 = p.lat_2 * rad, p0 = p.lat_0 * rad;
    var n = (Math.log(m(p1)) - Math.log(m(p2))) / (Math.log(t(p1)) - Math.log(t(p2)));
    var bigF = m(p1) / (n * Math.pow(t(p1), n));
    var r0 = a * bigF * Math.pow(t(p0), n);
    return function (lon, lat) {
      var r = a * bigF * Math.pow(t(lat * rad), n);
      var theta = n * (lon - p.lon_0) * rad;
      return [p.x_0 + r * Math.sin(theta), p.y_0 + r0 - r * Math.cos(theta)];
    };
  }

  function toPage(lon, lat, georef) {
    var xy = lcc(georef.projection)(lon, lat), m = georef.affine;
    return [m[0][0] * xy[0] + m[0][1] * xy[1] + m[0][2], m[1][0] * xy[0] + m[1][1] * xy[1] + m[1][2]];
  }

  function metresPerUnit(m) {
    return 1 / Math.sqrt(Math.abs(m[0][0] * m[1][1] - m[0][1] * m[1][0]));
  }

  /* The closed rings of an M...L...Z path (the only commands the district paths use). */
  function rings(path) {
    var out = [], re = /M([^Z]+)Z/g, hit;
    while ((hit = re.exec(path)) !== null) {
      out.push(hit[1].split("L").map(function (pt) {
        return pt.trim().split(/\s+/).map(Number);
      }));
    }
    return out;
  }

  function inside(rs, x, y) {
    var hit = false;
    rs.forEach(function (r) {
      for (var i = 0; i < r.length; i++) {
        var p = r[i], q = r[(i + 1) % r.length];
        if ((p[1] > y) !== (q[1] > y) && x < p[0] + (y - p[1]) * (q[0] - p[0]) / (q[1] - p[1])) { hit = !hit; }
      }
    });
    return hit;
  }

  function segDist(px, py, x1, y1, x2, y2) {
    var dx = x2 - x1, dy = y2 - y1, L = dx * dx + dy * dy;
    var t = L === 0 ? 0 : Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / L));
    return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
  }

  function edgeDist(rs, x, y) {
    var best = Infinity;
    rs.forEach(function (r) {
      for (var i = 0; i < r.length; i++) {
        var p = r[i], q = r[(i + 1) % r.length];
        best = Math.min(best, segDist(x, y, p[0], p[1], q[0], q[1]));
      }
    });
    return best;
  }

  function round(v, d) { var k = Math.pow(10, d); return Math.round(v * k) / k; }

  /* districts: [{number, path}] (the same paths the map draws); georef: {projection, affine, boundary_margin_m}.
     Returns {district (null outside every shape or in two), distance_m, near_boundary, page_xy, overlap?, closest?}. */
  function districtFor(lon, lat, districts, georef) {
    var xy = toPage(lon, lat, georef), x = xy[0], y = xy[1];
    var scale = metresPerUnit(georef.affine), margin = Number(georef.boundary_margin_m);
    var hits = [], bestD = Infinity, bestN = null;
    districts.forEach(function (d) {
      var rs = rings(d.path), dist = edgeDist(rs, x, y) * scale;
      if (dist < bestD) { bestD = dist; bestN = d.number; }
      if (inside(rs, x, y)) { hits.push(d.number); }
    });
    var out = { district: hits.length === 1 ? hits[0] : null, distance_m: round(bestD, 1),
                near_boundary: bestD < margin || hits.length > 1, page_xy: [round(x, 2), round(y, 2)] };
    if (hits.length > 1) { out.overlap = hits.slice().sort(function (a, b) { return a - b; }); }
    else if (!hits.length) { out.closest = bestN; }
    return out;
  }

  var api = { toPage: toPage, rings: rings, districtFor: districtFor };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; } else { root.CRGeoref = api; }
})(typeof window !== "undefined" ? window : this);
