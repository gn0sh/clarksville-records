/* Landing address box (address pin M2). Only when the visitor submits, never on a keystroke, the address goes to the
   Census one-line geocoder by JSONP (it has no CORS); the answer's point is placed on the drawn map with
   CRGeoref.districtFor (static/georef.js) against the same district paths the map draws. Nothing is stored and
   nothing is logged. If the geocoder script cannot load (a sandboxed preview, a blocker, offline) the box says so
   and points to the official lookup. Exposes CRAddress.classify / jsonpUrl for tests (module.exports under node). */
(function (root) {
  "use strict";
  var TIMEOUT_MS = 8000;

  /* The geocoder answer -> what to tell the visitor. `locate(lon, lat)` is districtFor bound to the map. */
  function classify(data, locate) {
    var res = data && typeof data === "object" ? data.result : null;
    if (!res || typeof res !== "object" || !Array.isArray(res.addressMatches)) { return { kind: "error" }; }
    if (!res.addressMatches.length) { return { kind: "nomatch" }; }
    var m = res.addressMatches[0], c = m && typeof m === "object" ? m.coordinates : null;
    var lon = c && typeof c === "object" ? c.x : NaN, lat = c && typeof c === "object" ? c.y : NaN;
    if (typeof lon !== "number" || typeof lat !== "number" || !isFinite(lon) || !isFinite(lat) ||
        Math.abs(lon) > 180 || Math.abs(lat) > 90) {
      return { kind: "error" };
    }
    var matched = typeof m.matchedAddress === "string" ? m.matchedAddress.slice(0, 200) : "";
    var got = locate(lon, lat);
    var kind = got.near_boundary ? "near" : (got.district === null ? "outside" : "district");
    return { kind: kind, district: got.district, matched: matched, page_xy: got.page_xy };
  }

  function jsonpUrl(base, address, callback) {
    return base + "?address=" + encodeURIComponent(address) + "&benchmark=Public_AR_Current&format=jsonp&callback=" +
      encodeURIComponent(callback);
  }

  var api = { classify: classify, jsonpUrl: jsonpUrl, TIMEOUT_MS: TIMEOUT_MS };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  root.CRAddress = api;

  var form = document.getElementById("addr-form");
  var cfgEl = document.getElementById("addr-config");
  var svg = document.querySelector("svg.county-map");
  if (!form || !cfgEl || !svg || !root.CRGeoref) { return; }
  var cfg;
  try { cfg = JSON.parse(cfgEl.textContent); } catch (e) { return; }
  if (!cfg || typeof cfg.geocoder !== "string" || cfg.geocoder.indexOf("https://") !== 0) { return; }

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

  var input = document.getElementById("addr-q");
  var button = form.querySelector("button");
  var out = document.getElementById("addr-result");
  var seq = 0, pending = null;
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
    if (!cfg.lookup_url || cfg.lookup_url.indexOf("https://") !== 0) { return text(cfg.lookup_label || "the official lookup"); }
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
      s.textContent = "Census match: " + matched;
      out.appendChild(s);
    }
  }

  var SVGNS = "http://www.w3.org/2000/svg";
  function clearPin() {
    var old = svg.querySelector(".addr-pin");
    if (old) { old.parentNode.removeChild(old); }
    shapes.forEach(function (s) { s.el.classList.remove("is-found"); });
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

  function show(r) {
    clearPin();
    if (r.kind === "district") {
      var s = shapes.filter(function (x) { return x.number === r.district; })[0];
      var label = cfg.district_label + " " + r.district;
      say(["This address is in ", s ? link(s.href, label) : label, "."], r.matched);
      if (s) { s.el.classList.add("is-found"); }
      pin(r.page_xy);
    } else if (r.kind === "near") {
      say(["This address is near a district line. Check ", lookupLink(), " to be sure."], r.matched);
      pin(r.page_xy);
    } else if (r.kind === "outside") {
      say(["This address is outside " + cfg.county + "."], r.matched);
      pin(r.page_xy);
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
    root[req.cb] = function () {};   // a late answer is ignored
    if (req.script.parentNode) { req.script.parentNode.removeChild(req.script); }
    button.disabled = false;
    form.removeAttribute("aria-busy");
    show(result);
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var address = input.value.replace(/\s+/g, " ").trim();
    if (!address) { say(["Enter a street address and city."]); input.focus(); return; }
    if (pending) { finish(pending, { kind: "error" }); }
    seq += 1;
    var req = { cb: "crGeocode" + seq + "_" + Math.floor(Math.random() * 1e9), loaded: false };
    pending = req;
    root[req.cb] = function (data) {
      var r;
      try { r = classify(data, locate); } catch (err) { r = { kind: "error" }; }
      finish(req, r);
    };
    var sc = document.createElement("script");
    req.script = sc;
    sc.referrerPolicy = "no-referrer";
    sc.async = true;
    sc.onload = function () {
      req.loaded = true;
      // a loaded script that did not call back is a bad answer, not a blocked one
      setTimeout(function () { finish(req, { kind: "error" }); }, 0);
    };
    sc.onerror = function () { finish(req, { kind: "unavailable" }); };
    req.timer = setTimeout(function () { finish(req, { kind: req.loaded ? "error" : "unavailable" }); }, TIMEOUT_MS);
    button.disabled = true;
    form.setAttribute("aria-busy", "true");
    say(["Looking up the address…"]);
    sc.src = jsonpUrl(cfg.geocoder, address, req.cb);
    document.head.appendChild(sc);
  });
})(typeof window !== "undefined" ? window : this);
