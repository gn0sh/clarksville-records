/* Landing address box (address pin M2). Only when the visitor submits, never on a keystroke, the address goes to the
   Census one-line geocoder by JSONP (it has no CORS). JSONP runs the geocoder's answer as script, so it runs only
   inside a hidden iframe made per submit with sandbox="allow-scripts" and no allow-same-origin (an opaque origin: it
   cannot touch this page, its storage or cookies). The iframe's one inline script (config "frame", allowed by hash in
   the page's CSP) loads the JSONP and posts the answer back as JSON text; this page accepts a message only from that
   iframe, parses it as data, validates it (classify) and shows it as text. The iframe is removed after each lookup.
   The answer's point is placed with CRGeoref.districtFor (static/georef.js) against the traced district paths in the
   settings block, and, when it holds city wards, against the ward paths too (same page space and georef, the wards'
   own margin). No map is drawn (CEO, 2026-11-10): the answer is the sentence. The address is never stored or
   logged; the found district and ward numbers (not the address) are kept in this browser only, by static/seats.js.
   If the geocoder cannot load (a sandboxed preview, a blocker, offline) the box says so and points to the official
   lookup.
   Residents type the street only, which the geocoder does not match: when the typed address names no state and no
   ZIP, it is tried with each of the county's mailing places appended in turn (settings "places", "state", from
   config/site.yml geocoder_places), one request at a time, at most MAX_TRIES, stopping at the first answer that is
   not "no match" and not outside the county (a match outside it was a wrong guess, so it counts as no match).
   Exposes CRAddress.classify / tries / jsonpUrl / frameDoc for tests (module.exports under node). */
(function (root) {
  "use strict";
  var TIMEOUT_MS = 8000;
  var CALLBACK = "crGeocode";        // the one name the iframe's script defines; each lookup has its own iframe
  var MAX_MATCHES = 20;              // more than this is "more than one address matched" without placing each
  var MAX_ANSWER = 200000;           // characters of JSON text accepted from the iframe
  var MAX_TRIES = 5;                 // geocoder requests per lookup, at most (sitegen GEOCODER_MAX_PLACES)

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
     traced ward lines place it; the city line counts as a ward line, so a point close to it is "near". */
  function wardKind(w) {
    return { kind: w.near_boundary ? "near" : (w.ward === null ? "outside" : "ward"), ward: w.ward };
  }

  /* The geocoder answer -> what to tell the visitor. `locate(lon, lat)` is districtFor bound to the district shapes. More than one
     match is answered only when every match lands in the same district (or all outside the county) and none is near
     a district line; otherwise the visitor is asked to add the city and ZIP (addr-pin/ambiguous-match).
     `locateWard(lon, lat)` -> {ward, near_boundary}, given only when there are ward shapes: the answer then also
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
    var out = { kind: kind, district: first.district, matched: matched };
    if (locateWard) { out.ward = wardKind(wards[0]); }
    return out;
  }

  /* Does the typed address already say where it is: the state (code or name, as a word) or a 5-digit ZIP? The
     house number is set aside first, so "10000 Main St" is not taken for a ZIP. */
  function namesPlace(address, states) {
    if (/\b\d{5}(?:-\d{4})?\b/.test(address.replace(/^\s*\d+/, ""))) { return true; }
    var low = " " + address.toLowerCase().replace(/[^a-z0-9]+/g, " ") + " ";
    return states.some(function (s) {
      var w = String(s).toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
      return w && low.indexOf(" " + w + " ") >= 0;
    });
  }

  /* The addresses one lookup sends, in order. With a state or ZIP (or no places configured): the address as typed,
     once. Without: "<address>, <place>, <state>" for each place, except that an address that already ends with a
     place's name is tried first with only the state added. At most MAX_TRIES. */
  function tries(address, places, state, stateName) {
    places = (Array.isArray(places) ? places : []).filter(function (p) { return typeof p === "string" && p; });
    if (!places.length || typeof state !== "string" || !state ||
        namesPlace(address, [state].concat(stateName ? [stateName] : []))) {
      return [address];
    }
    var base = address.replace(/[\s,]+$/, ""), low = base.toLowerCase(), own = null;
    places.forEach(function (p) {
      var w = p.toLowerCase(), cut = low.length - w.length;
      if (!own && cut > 0 && low.slice(cut) === w && /[\s,]/.test(low.charAt(cut - 1)) && low.slice(0, cut).trim()) {
        own = p;
      }
    });
    var out = own ? [base + ", " + state] : [];
    places.forEach(function (p) { if (p !== own) { out.push(base + ", " + p + ", " + state); } });
    return out.slice(0, MAX_TRIES);
  }

  /* A guessed place's answer that sends the lookup on to the next place. */
  function tryNext(r) { return r.kind === "nomatch" || r.kind === "outside"; }

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

  var api = { classify: classify, wardKind: wardKind, tries: tries, tryNext: tryNext, jsonpUrl: jsonpUrl,
              frameDoc: frameDoc, TIMEOUT_MS: TIMEOUT_MS, CALLBACK: CALLBACK, MAX_TRIES: MAX_TRIES };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  root.CRAddress = api;

  var form = document.getElementById("addr-form");
  var cfgEl = document.getElementById("addr-config");
  if (!form || !cfgEl || !root.CRGeoref) { return; }
  var cfg;
  try { cfg = JSON.parse(cfgEl.textContent); } catch (e) { return; }
  if (!cfg || typeof cfg.geocoder !== "string" || cfg.geocoder.indexOf("https://") !== 0 ||
      typeof cfg.frame !== "string" || !cfg.frame) { return; }

  /* The traced shapes, from the settings block (sitegen views.address_context): [{number, path, href}]. */
  function shapesOf(list) {
    return (Array.isArray(list) ? list : []).filter(function (s) {
      return s && typeof s.number === "number" && typeof s.path === "string" && s.path;
    }).map(function (s) {
      return { number: s.number, path: s.path, href: typeof s.href === "string" ? s.href : null };
    });
  }
  var shapes = shapesOf(cfg.districts);
  if (!shapes.length) { return; }
  function locate(lon, lat) { return root.CRGeoref.districtFor(lon, lat, shapes, cfg.georef); }

  /* City wards, when the settings hold them: the same page space and georef, the wards' own boundary margin. */
  var wardShapes = shapesOf(cfg.wards);
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
  var pending = null;                // the request in flight: {frame, timer, lookup}
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

  function wardLink(n) {
    var s = wardShapes.filter(function (x) { return x.number === n; })[0];
    var label = cfg.ward_label + " " + n;
    return s && s.href ? link(s.href, label) : label;
  }
  var CHECK_WARD = " Check with the Election Commission or look it up on ";
  /* The ward sentence after the district one (none when there are no ward shapes). */
  function wardTail(w) {
    if (!w) { return []; }
    if (w.kind === "ward") { return [" The " + cfg.geocoder_short + " places it in ", wardLink(w.ward), "."]; }
    if (w.kind === "near") { return [" It is near a ward line." + CHECK_WARD, lookupLink(), " to be sure."]; }
    return [" It is outside the " + cfg.city + " wards on the " + cfg.ward_map_owner + "'s map of " + cfg.ward_map_date +
            ". Annexations since then are not on it." + CHECK_WARD, lookupLink(), "."];
  }
  /* An address lookup answers for both seats: what it found replaces what was kept (static/seats.js, this device
     only). When it places neither seat, the earlier seats stay; when it places one, both are replaced, so a seat it
     could not place (near a line, or outside the city) is cleared rather than kept from an earlier address. */
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
    var w = r.ward || null;      // null: no ward shapes, so the answer names the district only
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
      keep(r);
    } else if (r.kind === "near") {
      if (w && w.kind === "near") {
        say(["This address is near a district line and a ward line." + CHECK_WARD, lookupLink(), " to be sure."],
            r.matched);
      } else {
        say(["This address is near a district line. Check ", lookupLink(), " to be sure."].concat(wardTail(w)),
            r.matched);
      }
      keep(r);
    } else if (r.kind === "outside") {
      say(["This address is outside " + cfg.county + "."], r.matched);
    } else if (r.kind === "ambiguous") {
      say(["More than one address matched. Add the city and ZIP, or check ", lookupLink(), "."]);
    } else if (r.kind === "nomatch" && r.guessed) {
      say(["No match was found for that address in " + cfg.county + ". Check the spelling, or add the city and ZIP, " +
           "or look it up on ", lookupLink(), "."]);
    } else if (r.kind === "nomatch") {
      say(["No match was found for that address. Check the spelling, or look it up on ", lookupLink(), "."]);
    } else if (r.kind === "unavailable") {
      say(["Address lookup isn't available here. Look it up on ", lookupLink(), "."]);
    } else {
      say(["The address lookup did not answer. Look it up on ", lookupLink(), "."]);
    }
  }

  /* The request in flight is dropped: its iframe goes, so a late answer has nowhere to go. */
  function drop(req) {
    if (pending === req) { pending = null; }
    clearTimeout(req.timer);
    if (req.frame.parentNode) { req.frame.parentNode.removeChild(req.frame); }
  }

  /* One request's answer. A guessed place that found nothing in the county moves on to the next place (a new
     request, sent only now: one at a time); when none is left the answer is "no match", never "outside". */
  function finish(req, result) {
    if (pending !== req) { return; }
    drop(req);
    var lk = req.lookup;
    if (lk.guessed && tryNext(result)) {
      lk.i += 1;
      if (lk.i < lk.tries.length && lk.i < MAX_TRIES) { send(lk); return; }
      result = { kind: "nomatch", guessed: true };
    }
    button.disabled = false;
    form.removeAttribute("aria-busy");
    show(result);
    reveal();
  }

  /* The answer is on the screen once it is given: on a short phone screen the body switch under the header can leave
     it just below the fold, so the page moves by the least that shows it (never when it is already in view). */
  function reveal() {
    try {
      var rc = out.getBoundingClientRect();
      if (rc.bottom > root.innerHeight || rc.top < 0) { out.scrollIntoView({ block: "nearest" }); }
    } catch (e) { /* an old browser: the answer is still in the page */ }
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

  /* Sends the lookup's current address: a fresh sandboxed iframe for each request. */
  function send(lk) {
    var fr = document.createElement("iframe");
    var req = { frame: fr, lookup: lk };
    pending = req;
    fr.setAttribute("sandbox", "allow-scripts");
    fr.setAttribute("referrerpolicy", "no-referrer");
    fr.setAttribute("title", "Address lookup");
    fr.setAttribute("aria-hidden", "true");
    fr.setAttribute("tabindex", "-1");
    fr.className = "addr-frame";
    fr.hidden = true;
    fr.srcdoc = frameDoc(cfg.frame, jsonpUrl(cfg.geocoder, lk.tries[lk.i], CALLBACK));
    req.timer = setTimeout(function () { finish(req, { kind: "unavailable" }); }, TIMEOUT_MS);
    document.body.appendChild(fr);
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var address = input.value.replace(/\s+/g, " ").trim();
    if (!address) { say(["Enter a street address."]); input.focus(); return; }
    if (pending) { drop(pending); }          // a new lookup replaces one still running (its later places too)
    var list = tries(address, cfg.places, cfg.state, cfg.state_name);
    button.disabled = true;
    form.setAttribute("aria-busy", "true");
    say(["Looking up the address…"]);
    send({ tries: list, i: 0, guessed: list[0] !== address });
  });
})(typeof window !== "undefined" ? window : this);
