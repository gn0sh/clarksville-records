/* The one script of digest/geo-frame.html (docs/architecture/daylight-national.md 4.0; security finding 1,
   national/csp-jsonp-gadget). The frame is loaded with sandbox="allow-scripts" and no allow-same-origin, so it runs
   in an opaque origin with no access to the page, its storage or cookies. Its meta CSP allows only this script (by
   its sha256, computed at build by sitegen/national.py geo_frame_html) and the Census geographies path.
   Protocol: posts the JSON string "ready" to the parent; takes one message {address} from the parent window (a
   string of 1 to 200 characters); loads the Census JSONP for it with the fixed callback name; posts back the answer
   as JSON text, or "blocked" (the script did not load) or "loaded" (it loaded but did not call back with an object).
   The URL is built exactly as site/static/national.js jsonpUrl builds it (tests/national.test.js holds them equal).
   It does nothing at all unless it runs sandboxed in a frame: a meta CSP cannot set frame-ancestors or sandbox and
   the host cannot send headers, so any site could embed this file unsandboxed and drive the JSONP in our origin.
   Sandboxed without allow-same-origin, self.origin is "null"; at the top level, parent is self.
   Fixed text, never an end tag in it (it is inlined in the frame HTML). */
(function () {
  "use strict";
  if (self.origin !== "null" || parent === self) { return; }
  var CENSUS = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress";
  var LAYERS = ["Incorporated Places", "Counties", "County Subdivisions", "Unified School Districts",
                "Secondary School Districts", "Elementary School Districts"];
  var CALLBACK = "crGeocode";
  var MAX_ADDRESS = 200;
  var asked = false, sent = false;

  function jsonpUrl(address) {
    var layers = LAYERS.map(function (l) { return encodeURIComponent(l); }).join(",");
    return CENSUS + "?address=" + encodeURIComponent(String(address)) +
      "&benchmark=Public_AR_Current&vintage=Current_Current&layers=" + layers + "&format=jsonp&callback=" + CALLBACK;
  }
  function done(text) {
    if (sent) { return; }
    sent = true;
    parent.postMessage(text, "*");
  }

  window[CALLBACK] = function (data) {
    var raw = null;
    if (data && typeof data === "object" && !Array.isArray(data)) {
      try { raw = JSON.stringify(data); } catch (e) { raw = null; }
    }
    done(typeof raw === "string" ? raw : JSON.stringify("loaded"));
  };

  window.addEventListener("message", function (e) {
    if (asked || e.source !== parent) { return; }
    var d = e.data, a = d && typeof d === "object" ? d.address : null;
    if (typeof a !== "string" || !a || a.length > MAX_ADDRESS) { return; }
    asked = true;
    var sc = document.createElement("script");
    sc.referrerPolicy = "no-referrer";
    sc.onload = function () { setTimeout(function () { done(JSON.stringify("loaded")); }, 0); };
    sc.onerror = function () { done(JSON.stringify("blocked")); };
    sc.src = jsonpUrl(a);
    document.head.appendChild(sc);
  });

  parent.postMessage(JSON.stringify("ready"), "*");
})();
