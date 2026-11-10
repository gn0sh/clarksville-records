/* Landing address box (address pin M2). Only when the visitor submits, never on a keystroke, the address goes to the
   Census one-line geocoder by JSONP (it has no CORS). JSONP runs the geocoder's answer as script, so it runs only
   inside a hidden iframe made per submit with sandbox="allow-scripts" and no allow-same-origin (an opaque origin: it
   cannot touch this page, its storage or cookies). The iframe's one inline script (config "frame", allowed by hash in
   the page's CSP) loads the JSONP and posts the answer back as JSON text; this page accepts a message only from that
   iframe, parses it as data, validates it (classify) and shows it as text. The iframe is removed after each lookup.
   The answer's point is placed on the drawn map with CRGeoref.districtFor (static/georef.js) against the same
   district paths the map draws, and, when the map draws city wards, against the ward paths too (same page space and
   georef, the wards' own margin). The address is never stored or logged; the found district and ward numbers (not
   the address) are kept in this browser only, by static/seats.js. If the geocoder cannot load (a sandboxed
   preview, a blocker, offline) the box says so and points to the official lookup.
   Exposes CRAddress.classify / jsonpUrl / frameDoc for tests (module.exports under node). */
(function (root) {
  "use strict";
  var TIMEOUT_MS = 8000;
  var CALLBACK = "crGeocode";        // the one name the iframe's script defines; each lookup has its own iframe
  var MAX_MATCHES = 20;              // more than this is "more than one address matched" without placing each
  var MAX_ANSWER = 200000;           // characters of JSON text accepted from the iframe

  function point(m) {
    var c = m && typeof m === "object" ? m.coordinates : null;
    var lon = c && typeof c === "object" ? c.x : NaN, lat = c && typeof c === "object" ? c.y : NaN;
    if (typeof lon !== "number" || typeof lat !== "number" || !isFinite(lon) || !isFinite(lat) ||
        Math.abs(lon) > 180 || Math.abs(lat) > 90) {
      return null;
    }
    return [lon, lat];
  }

  /* A ward answer -> {kind: "ward" | "near" | "outside", ward}. "outside": in no ward, so outside the city as the
     ward map draws it; the city line counts as a ward line, so a point close to it is "near". */
  function wardKind(w) {
    return { kind: w.near_boundary ? "near" : (w.ward === null ? "outside" : "ward"), ward: w.ward };
  }

  /* The geocoder answer -> what to tell the visitor. `locate(lon, lat)` is districtFor bound to the map. More than one
     match is answered only when every match lands in the same district (or all outside the county) and none is near
     a district line; otherwise the visitor is asked to add the city and ZIP (addr-pin/ambiguous-match).
     `locateWard(lon, lat)` -> {ward, near_boundary}, given only when the map has ward shapes: the answer then also
     carries `ward` (wardKind), and several matches must agree on the ward too, none near a ward line. */
  function classify(data, locate, locateWard) {
    var res = data && typeof data === "object" ? data.result : null;
    if (!res || typeof res !== "object" || !Array.isArray(res.addressMatches)) { return { kind: "error" }; }
    var ms = res.addressMatches;
    if (!ms.length) { return { kind: "nomatch" }; }
    if (ms.length > MAX_MATCHES) { return { kind: "ambiguous", count: ms.length }; }
    var got = [], wards = [];
    for (var i = 0; i < ms.length; i++) {
      var p = point(ms[i]);
      if (!p) { return { kind: "error" }; }
      got.push(locate(p[0], p[1]));
      if (locateWard) { wards.push(locateWard(p[0], p[1])); }
    }
    var first = got[0];
    if (got.length > 1 && !got.every(function (g, j) {
      return !g.near_boundary && g.district === first.district &&
        (!locateWard || (!wards[j].near_boundary && wards[j].ward === wards[0].ward));
    })) {
      return { kind: "ambiguous", count: ms.length };
    }
    var matched = typeof ms[0].matchedAddress === "string" ? ms[0].matchedAddress.slice(0, 200) : "";
    var kind = first.near_boundary ? "near" : (first.district === null ? "outside" : "district");
    var out = { kind: kind, district: first.district, matched: matched, page_xy: first.page_xy };
    if (locateWard) { out.ward = wardKind(wards[0]); }
    return out;
  }

  function jsonpUrl(base, address, callback) {
    return base + "?address=" + encodeURIComponent(address) + "&benchmark=Public_AR_Current&format=jsonp&callback=" +
      encodeURIComponent(callback);
  }

  function escAttr(s) {
    return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  /* The iframe's whole document: no referrer, and the fixed frame script with the JSONP URL in an attribute. */
  function frameDoc(script, url) {
    return '<!doctype html><meta charset="utf-8"><meta name="referrer" content="no-referrer">' +
      '<script data-u="' + escAttr(url) + '">' + script + "</script>";
  }

  var api = { classify: classify, wardKind: wardKind, jsonpUrl: jsonpUrl, frameDoc: frameDoc, TIMEOUT_MS: TIMEOUT_MS, CALLBACK: CALLBACK };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  root.CRAddress = api;

  var form = document.getElementById("addr-form");
  var cfgEl = document.getElementById("addr-config");
  var svg = document.querySelector("svg.county-map");
  if (!form || !cfgEl || !svg || !root.CRGeoref) { return; }
  var cfg;
  try { cfg = JSON.parse(cfgEl.textContent); } catch (e) { return; }
  if (!cfg || typeof cfg.geocoder !== "string" || cfg.geocoder.indexOf("https://") !== 0 ||
      typeof cfg.frame !== "string" || !cfg.frame) { return; }

  var shapes = [];
  var anchors = svg.querySelectorAll("#layer-districts a[data-district]");
  for (var i = 0; i < anchors.length; i++) {
    var p = anchors[i].querySelector("path");
    if (p) {
      shapes.push({ number: Number(anchors[i].getAttribute("data-district")), path: p.getAttribute("d") || "",
                    href: anchors[i].getAttribute("href"), el: anchors[i] });
    }
  }
  if (!shapes.length) { return; }
  function locate(lon, lat) { return root.CRGeoref.districtFor(lon, lat, shapes, cfg.georef); }

  /* City wards, when the map draws them: the same page space and georef, the wards' own boundary margin. */
  var wardShapes = [];
  var wardEls = svg.querySelectorAll("#layer-wards [data-ward]");
  for (var k = 0; k < wardEls.length; k++) {
    var wp = wardEls[k].tagName.toLowerCase() === "path" ? wardEls[k] : wardEls[k].querySelector("path");
    if (wp) {
      wardShapes.push({ number: Number(wardEls[k].getAttribute("data-ward")), path: wp.getAttribute("d") || "",
                        href: wardEls[k].getAttribute("href"), el: wardEls[k] });
    }
  }
  var locateWard = null;
  if (wardShapes.length && typeof cfg.ward_margin_m === "number" && cfg.ward_margin_m > 0) {
    var wardGeo = { projection: cfg.georef.projection, affine: cfg.georef.affine, boundary_margin_m: cfg.ward_margin_m };
    locateWard = function (lon, lat) {
      var g = root.CRGeoref.districtFor(lon, lat, wardShapes, wardGeo);
      return { ward: g.district, near_boundary: g.near_boundary };
    };
  }

  var input = document.getElementById("addr-q");
  var button = form.querySelector("button");
  var out = document.getElementById("addr-result");
  var pending = null;
  form.hidden = false;
  var landing = form.closest(".landing");
  if (landing) { landing.classList.add("has-addr"); }

  function text(s) { return document.createTextNode(s); }
  function link(href, label) {
    var a = document.createElement("a");
    a.setAttribute("href", href);
    a.textContent = label;
    return a;
  }
  function lookupLink() {
    if (!cfg.lookup_url || cfg.lookup_url.indexOf("https://") !== 0) { return text("the official lookup"); }
    var a = link(cfg.lookup_url, cfg.lookup_label);
    a.setAttribute("rel", "noopener");
    return a;
  }
  function say(parts, matched) {
    while (out.firstChild) { out.removeChild(out.firstChild); }
    parts.forEach(function (x) { out.appendChild(typeof x === "string" ? text(x) : x); });
    form.classList.add("has-result");
    if (matched) {
      var s = document.createElement("span");
      s.className = "addr-matched";
      s.textContent = cfg.geocoder_short + " match: " + matched;
      out.appendChild(s);
    }
  }

  var SVGNS = "http://www.w3.org/2000/svg";
  function clearPin() {
    var old = svg.querySelector(".addr-pin");
    if (old) { old.parentNode.removeChild(old); }
    shapes.concat(wardShapes).forEach(function (s) { s.el.classList.remove("is-found"); });
  }
  function pin(xy) {
    var vb = (svg.getAttribute("viewBox") || "").split(/\s+/).map(Number);
    if (vb.length !== 4 || !(xy[0] >= vb[0] && xy[0] <= vb[0] + vb[2] && xy[1] >= vb[1] && xy[1] <= vb[1] + vb[3])) {
      return;   // off the drawn map (far outside the county): no pin, the sentence says where it is
    }
    var r = vb[2] / 70;
    var g = document.createElementNS(SVGNS, "g");
    g.setAttribute("class", "addr-pin");
    var ring = document.createElementNS(SVGNS, "circle");
    ring.setAttribute("cx", xy[0]); ring.setAttribute("cy", xy[1]); ring.setAttribute("r", r);
    var dot = document.createElementNS(SVGNS, "circle");
    dot.setAttribute("class", "addr-pin-dot");
    dot.setAttribute("cx", xy[0]); dot.setAttribute("cy", xy[1]); dot.setAttribute("r", r / 3);
    g.appendChild(ring); g.appendChild(dot);
    svg.appendChild(g);
  }

  function wardLink(n) {
    var s = wardShapes.filter(function (x) { return x.number === n; })[0];
    var label = cfg.ward_label + " " + n;
    if (s) { s.el.classList.add("is-found"); }
    return s && s.href ? link(s.href, label) : label;
  }
  var CHECK_WARD = " Check with the Election Commission or look it up on ";
  /* The ward sentence after the district one (none when the map has no wards). */
  function wardTail(w) {
    if (!w) { return []; }
    if (w.kind === "ward") { return [" The " + cfg.geocoder_short + " places it in ", wardLink(w.ward), "."]; }
    if (w.kind === "near") { return [" It is near a ward line." + CHECK_WARD, lookupLink(), " to be sure."]; }
    return [" It is outside the " + cfg.city + " wards."];
  }
  /* An address lookup answers for both seats: what it found replaces what was kept (static/seats.js, this device
     only), and a seat it could not place (near a line, or outside the city) is not kept from an earlier address. */
  function keep(r) {
    if (!root.CRSeats) { return; }
    var w = r.ward || null;
    if (!w) {
      if (r.kind === "district") { root.CRSeats.save({ district: r.district }); }
      return;
    }
    var seats = { district: r.kind === "district" ? r.district : null, ward: w.kind === "ward" ? w.ward : null };
    if (seats.district !== null || seats.ward !== null) { root.CRSeats.save(seats, true); }
  }

  function show(r) {
    clearPin();
    var w = r.ward || null;      // null: the map has no ward shapes, so the answer names the district only
    if (r.kind === "district") {
      var s = shapes.filter(function (x) { return x.number === r.district; })[0];
      var label = cfg.district_label + " " + r.district;
      var where = s ? link(s.href, label) : label;
      if (w && w.kind === "ward") {
        say(["The " + cfg.geocoder_short + " places this address in ", where, " and ", wardLink(w.ward), "."],
            r.matched);
      } else {
        say(["The " + cfg.geocoder_short + " places this address in ", where, "."].concat(wardTail(w)), r.matched);
      }
      if (s) { s.el.classList.add("is-found"); }
      pin(r.page_xy);
      keep(r);
    } else if (r.kind === "near") {
      if (w && w.kind === "near") {
        say(["This address is near a district line and a ward line." + CHECK_WARD, lookupLink(), " to be sure."],
            r.matched);
      } else {
        say(["This address is near a district line. Check ", lookupLink(), " to be sure."].concat(wardTail(w)),
            r.matched);
      }
      pin(r.page_xy);
      keep(r);
    } else if (r.kind === "outside") {
      say(["This address is outside " + cfg.county + "."], r.matched);
      pin(r.page_xy);
    } else if (r.kind === "ambiguous") {
      say(["More than one address matched. Add the city and ZIP, or check ", lookupLink(), "."]);
    } else if (r.kind === "nomatch") {
      say(["No match was found for that address. Check the spelling, or look it up on ", lookupLink(), "."]);
    } else if (r.kind === "unavailable") {
      say(["Address lookup isn't available here. Look it up on ", lookupLink(), "."]);
    } else {
      say(["The address lookup did not answer. Look it up on ", lookupLink(), "."]);
    }
  }

  function finish(req, result) {
    if (pending !== req) { return; }
    pending = null;
    clearTimeout(req.timer);
    if (req.frame.parentNode) { req.frame.parentNode.removeChild(req.frame); }   // a late answer has nowhere to go
    button.disabled = false;
    form.removeAttribute("aria-busy");
    show(result);
  }

  /* Only the current lookup's own iframe is heard, and only as data: a JSON string, parsed here, then classify. */
  root.addEventListener("message", function (e) {
    var req = pending, w = req ? req.frame.contentWindow : null;
    if (!w || e.source !== w || e.origin !== "null") { return; }
    var d = e.data;
    if (!d || typeof d !== "object") { return; }
    var r;
    if (d.cr === "answer") {
      try {
        r = typeof d.json === "string" && d.json.length <= MAX_ANSWER ? classify(JSON.parse(d.json), locate, locateWard)
          : { kind: "error" };
      } catch (err) { r = { kind: "error" }; }
    } else if (d.cr === "loaded") {
      r = { kind: "error" };          // the script loaded but did not call back: a bad answer, not a blocked one
    } else if (d.cr === "blocked") {
      r = { kind: "unavailable" };
    } else {
      return;
    }
    finish(req, r);
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var address = input.value.replace(/\s+/g, " ").trim();
    if (!address) { say(["Enter a street address and city."]); input.focus(); return; }
    if (pending) { finish(pending, { kind: "error" }); }
    var fr = document.createElement("iframe");
    var req = { frame: fr };
    pending = req;
    fr.setAttribute("sandbox", "allow-scripts");
    fr.setAttribute("referrerpolicy", "no-referrer");
    fr.setAttribute("title", "Address lookup");
    fr.setAttribute("aria-hidden", "true");
    fr.setAttribute("tabindex", "-1");
    fr.className = "addr-frame";
    fr.hidden = true;
    fr.srcdoc = frameDoc(cfg.frame, jsonpUrl(cfg.geocoder, address, CALLBACK));
    req.timer = setTimeout(function () { finish(req, { kind: "unavailable" }); }, TIMEOUT_MS);
    button.disabled = true;
    form.setAttribute("aria-busy", "true");
    say(["Looking up the address…"]);
    document.body.appendChild(fr);
  });
})(typeof window !== "undefined" ? window : this);
