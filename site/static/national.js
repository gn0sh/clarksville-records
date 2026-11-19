/* Daylight Digest lookup, the pure part (docs/architecture/daylight-national.md 4.0, 4.1, 3.4, 3.8; tasks F1, F5).
   Node-testable like address.js: under node it exports its functions (module.exports); in a browser it sets
   window.DaylightNational and touches no page element (the page wiring is task F2).

   - jsonpUrl(address): the Census geographies URL (ADR 0013 decision 2). The geo frame's own script
     (site/templates/_geo_frame.js) builds the same URL; tests/national.test.js holds the two to one shape.
   - classify(answer) and governments(units, pagedir): the Census answer, read as data, -> the cards and fixed lines.
   - loadList / saveList / forget / markRequested / markCounted (+ loadRequested, loadCounted): the three device keys
     of 3.8, each call wrapped so a blocked, full or throwing storage never breaks the page.
   - frameMessage(e, frameWindow) and lookup(env, address, done): the parent side of the geo frame protocol (4.0).
     The frame is digest/geo-frame.html (sandbox="allow-scripts", no allow-same-origin, so its origin is "null"); it
     posts the JSON string "ready", is sent {address} by postMessage, and posts back the Census answer as JSON text
     (or the JSON strings "blocked" / "loaded" when the Census script failed or did not call back). The parent hears
     a message only from that frame's window, with origin "null", a string at most MAX_ANSWER long that JSON.parse
     accepts. The address reaches the frame only by that one postMessage after "ready", never in its URL.

   Hardening (security finding 9, national/postmessage-hardening): a GEOID becomes an id only when it matches
   ^\d{5,10}$ with the layer's own length and its state part matches ^\d{2}$; every directory, alias, flag and label
   lookup goes through a Map or Set (an id of "__proto__" or "constructor" finds nothing); every Census string is
   cleaned of controls and bidi overrides, capped, and meant for textContent only. Nothing here writes history,
   location or document.title. */
(function (root) {
  "use strict";

  var CENSUS = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress";
  var CALLBACK = "crGeocode";        // fixed; the frame defines only this name (ADR 0013 decision 2)
  var TIMEOUT_MS = 15000;            // no answer in 15 s -> "The Census lookup is not answering" (4.1, UX section 2)
  var MAX_ADDRESS = 200;             // characters of address sent to the frame (4.0)
  var MAX_MATCHES = 20;              // more than this: the "not found" tips (add the city and ZIP)
  // Copy of sitegen/national.py MAX_ANSWER (220,000 characters); tests/test_national_js.py asserts they match.
  var MAX_ANSWER = 220000;
  var PAGEDIR_SCHEMA = "daylight-pagedir/1";

  // The six Census layers, read by exact name, in card order (4.1 step 7); any other layer is ignored.
  var LAYERS = [
    { layer: "place", name: "Incorporated Places", digits: 7, cc: "PLACECC" },
    { layer: "county", name: "Counties", digits: 5, cc: "COUNTYCC" },
    { layer: "cousub", name: "County Subdivisions", digits: 10, cc: "COUSUBCC" },
    { layer: "sdu", name: "Unified School Districts", digits: 7, cc: null },
    { layer: "sds", name: "Secondary School Districts", digits: 7, cc: null },
    { layer: "sde", name: "Elementary School Districts", digits: 7, cc: null }
  ];
  // Card order (4.1 step 7, UX section 3): city or town, county, township or town, then the school districts
  // elementary, secondary, unified. LAYERS keeps the Census request order (jsonpUrl and the frame share it).
  var ORDER = new Map(["place", "county", "cousub", "sde", "sds", "sdu"].map(function (l, i) { return [l, i]; }));
  var DIGITS = new Map(LAYERS.map(function (l) { return [l.layer, l.digits]; }));
  var SCHOOL = new Set(["sdu", "sds", "sde"]);
  // FUNCSTAT kept by step 1 (docs/platform-facts.md "Census TIGER/Line codes"; manager decision 2026-11-19): A or B
  // for general-purpose governments (B: partially consolidated, with its own officials), A or E for school districts.
  // C (consolidated, one set of officials), F, N, S and the rest are dropped; gov-flags `show` brings any id back.
  var KEEP_GENERAL = new Set(["A", "B"]);
  var KEEP_SCHOOL = new Set(["A", "E"]);
  // Step 5: COUSUBCC codes that say the county subdivision is the same area as an incorporated place (census.gov class
  // codes: T5 cousub coextensive with a place; C2, C5 and C7 places that serve as their own county subdivision).
  var COEXTENSIVE = new Set(["T5", "C2", "C5", "C7"]);

  var GEOID_RE = /^\d{5,10}$/;
  var STATE_RE = /^\d{2}$/;
  var ID_RE = /^(place|county|cousub|sdu|sds|sde)-[0-9]{2,14}$/;      // 3.8 (and us-count.js)
  var CODE_RE = /^[A-Z][0-9A-Z]?$/;
  var KEY_RE = /^[a-z0-9][a-z0-9-]{0,39}$/;                            // a `lines` value or a `reason`
  var LABEL_RE = /^(slot|reason|note)\.[a-z0-9][a-z0-9-]*$/;
  var PATH_RE = /^[a-z0-9][a-z0-9\/_.-]*$/;                            // pagedir `page` and `full` (relative)
  var DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
  // eslint-disable-next-line no-control-regex
  // Controls, bidi controls and invisible characters (the set of sitegen/national_guards.py BAD_TEXT_RE): stripped,
  // except whitespace controls, which become a space. The "u" flag makes the surrogate range match lone halves only.
  var BAD_TEXT = /[\u0000-\u001f\u007f-\u009f\u00ad\u061c\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\ud800-\udfff\u{e0000}-\u{e007f}]/gu;
  var WS_CONTROLS = /[\t\n\v\f\r]/g;
  var MAX_NAME = 120;
  var MAX_TEXT = 300;

  function own(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }
  function isObj(o) { return !!o && typeof o === "object" && !Array.isArray(o); }
  function clean(s, max) {
    if (typeof s !== "string") { return ""; }
    return s.replace(WS_CONTROLS, " ").replace(BAD_TEXT, "").replace(/\s+/g, " ").trim().slice(0, max);
  }
  function safePath(p) { return typeof p === "string" && PATH_RE.test(p) && p.indexOf("..") < 0 && p.indexOf("//") < 0; }
  function httpsUrl(u) { return typeof u === "string" && u.length <= 500 && /^https:\/\/[^\s"<>\\]+$/.test(u); }
  function layerOf(id) {
    var m = typeof id === "string" ? /^(place|county|cousub|sdu|sds|sde)-(\d+)$/.exec(id) : null;
    return m && GEOID_RE.test(m[2]) && m[2].length === DIGITS.get(m[1]) ? m[1] : null;
  }

  /* The geographies URL for one address. `address` is the only variable part, URL-encoded, so it can never add or
     change a parameter (an "&callback=" in it stays inside the address). */
  function jsonpUrl(address) {
    var layers = LAYERS.map(function (l) { return encodeURIComponent(l.name); }).join(",");
    return CENSUS + "?address=" + encodeURIComponent(String(address)) +
      "&benchmark=Public_AR_Current&vintage=Current_Current&layers=" + layers + "&format=jsonp&callback=" + CALLBACK;
  }

  /* The units of one match's geographies, from the six layers only, each checked before it becomes an id. */
  function unitsOf(geo) {
    var out = [];
    if (!isObj(geo)) { return out; }
    LAYERS.forEach(function (l) {
      var list = own(geo, l.name) ? geo[l.name] : null;
      if (!Array.isArray(list)) { return; }
      list.forEach(function (u) {
        if (!isObj(u)) { return; }
        var geoid = u.GEOID, state = u.STATE;
        if (typeof geoid !== "string" || !GEOID_RE.test(geoid) || geoid.length !== l.digits) { return; }
        if (typeof state !== "string" || !STATE_RE.test(state) || geoid.slice(0, 2) !== state) { return; }
        var name = clean(u.NAME, MAX_NAME);
        if (!name) { return; }
        var fs = typeof u.FUNCSTAT === "string" && CODE_RE.test(u.FUNCSTAT) ? u.FUNCSTAT : "";
        var cc = l.cc && typeof u[l.cc] === "string" && CODE_RE.test(u[l.cc]) ? u[l.cc] : "";
        out.push({ id: l.layer + "-" + geoid, layer: l.layer, name: name, funcstat: fs, state: state, cc: cc });
      });
    });
    return out;
  }

  /* The Census answer (parsed JSON) -> {kind: "error"} | {kind: "nomatch", many?} | {kind: "one", matched, units} |
     {kind: "pick", matches: [{label, units}]}. More than MAX_MATCHES matches is "nomatch" with many: true (the
     not-found tips, UX section 2). `matched`/`label` are the Census's matched address text, page text only. */
  function classify(answer) {
    var res = isObj(answer) && isObj(answer.result) ? answer.result : null;
    if (!res || !Array.isArray(res.addressMatches)) { return { kind: "error" }; }
    var ms = res.addressMatches;
    if (!ms.length) { return { kind: "nomatch" }; }
    if (ms.length > MAX_MATCHES) { return { kind: "nomatch", many: true }; }
    var matches = ms.map(function (m) {
      return { label: clean(isObj(m) ? m.matchedAddress : "", MAX_ADDRESS), units: unitsOf(isObj(m) ? m.geographies : null) };
    });
    if (matches.length === 1) { return { kind: "one", matched: matches[0].label, units: matches[0].units }; }
    return { kind: "pick", matches: matches };
  }

  /* The page directory (3.4, embedded with |tojson) -> an index of Maps and Sets, or null when it is not one. Only
     own keys are read, and only well-formed ids, keys and values are kept. */
  function indexPagedir(pd) {
    if (!isObj(pd) || pd.schema !== PAGEDIR_SCHEMA) { return null; }
    var idx = emptyIndex();
    function each(o, fn) { if (isObj(o)) { Object.keys(o).forEach(function (k) { fn(k, o[k]); }); } }
    each(pd.govs, function (k, v) { if (layerOf(k) && isObj(v)) { idx.govs.set(k, v); } });
    each(pd.alias, function (k, v) { if (layerOf(k) && layerOf(v)) { idx.alias.set(k, v); } });
    each(pd.lines, function (k, v) { if (layerOf(k) && typeof v === "string" && KEY_RE.test(v)) { idx.lines.set(k, v); } });
    each(pd.labels, function (k, v) { if (LABEL_RE.test(k) && typeof v === "string") { idx.labels.set(k, clean(v, MAX_TEXT)); } });
    (Array.isArray(pd.hide) ? pd.hide : []).forEach(function (i) { if (layerOf(i)) { idx.hide.add(i); } });
    (Array.isArray(pd.show) ? pd.show : []).forEach(function (i) { if (layerOf(i)) { idx.show.add(i); } });
    (Array.isArray(pd.rules) ? pd.rules : []).forEach(function (r) {
      if (isObj(r) && typeof r.state === "string" && STATE_RE.test(r.state) && ORDER.has(r.layer) &&
          typeof r.show === "boolean") {
        idx.rules.set(r.state + "|" + r.layer, r.show);
      }
    });
    idx.root = typeof pd.root === "string" && /^(\.\.\/)*$/.test(pd.root) ? pd.root : "";
    return idx;
  }
  function emptyIndex() {
    return { govs: new Map(), alias: new Map(), lines: new Map(), labels: new Map(), hide: new Set(),
             show: new Set(), rules: new Map(), root: "" };
  }
  function asIndex(p) {
    if (p && p.govs instanceof Map) { return p; }
    return indexPagedir(p) || emptyIndex();
  }
  /* A label's text ("" when there is none), for textContent. */
  function label(pagedir, key) {
    var v = asIndex(pagedir).labels.get(key);
    return typeof v === "string" ? v : "";
  }

  /* The card fields from the directory entry (3.4), each checked: status, board, and the status's own fields. */
  function cardOf(u, entry) {
    var g = { id: u.id, name: u.name, slot: u.layer, status: "not-covered-yet" };
    if (!entry || (entry.status !== "covered" && entry.status !== "cant-cover")) { return g; }
    g.status = entry.status;
    var board = clean(entry.board, MAX_NAME);
    if (board) { g.board = board; }
    if (httpsUrl(entry.official_url)) { g.official_url = entry.official_url; }
    if (entry.status === "covered") {
      if (safePath(entry.page)) { g.page = entry.page; }
      if (safePath(entry.full)) { g.full = entry.full; }
      g.stale = entry.stale !== false;
    } else {
      if (typeof entry.reason === "string" && KEY_RE.test(entry.reason)) { g.reason = entry.reason; }
      if (typeof entry.checked === "string" && DATE_RE.test(entry.checked)) { g.checked = entry.checked; }
      if (httpsUrl(entry.reason_url)) { g.reason_url = entry.reason_url; }
    }
    return g;
  }

  /* Units of one match (from classify) and the page directory -> {govs: [cards], notes: [label keys]} (4.1).
     Steps: (1) FUNCSTAT, (2) gov-flags: hide by id, else show by id, else a state-and-layer rule with show: false
     hides; state rules only ever hide (a show: true rule is ignored, so it can never bring back an N, F or S unit:
     fail closed; only an id-level `show` brings a unit back), else step 1's answer; (3) school district "not
     defined" (GEOID ends 99999); (4) alias, then one card per id; (5) a county subdivision whose COUSUBCC says it is
     the same area as an incorporated place goes when a place is kept; (6) status; (7) order place, county, cousub,
     sde, sds, sdu (school districts elementary, secondary, unified: UX section 3).
     Notes, as label keys: "note.<line>" for each returned unit's gov-flags line, kept or hidden; else "note.no-city"
     when no place is kept and "note.no-county" when the answer had a county and none is kept. */
  function governments(units, pagedir) {
    var idx = asIndex(pagedir);
    var lineNotes = [], hadCounty = false, recs = [];
    (Array.isArray(units) ? units : []).forEach(function (u) {
      if (!isObj(u) || typeof u.id !== "string" || layerOf(u.id) !== u.layer) { return; }
      var line = idx.lines.get(u.id);
      if (line && lineNotes.indexOf("note." + line) < 0) { lineNotes.push("note." + line); }
      if (u.layer === "county") { hadCounty = true; }
      var keep, rule = idx.rules.get(u.state + "|" + u.layer);
      if (idx.hide.has(u.id)) {
        keep = false;
      } else if (idx.show.has(u.id)) {
        keep = true;
      } else if (rule === false) {
        keep = false;
      } else {
        keep = (SCHOOL.has(u.layer) ? KEEP_SCHOOL : KEEP_GENERAL).has(u.funcstat);
      }
      if (!keep) { return; }
      if (SCHOOL.has(u.layer) && /99999$/.test(u.id)) { return; }
      var target = idx.alias.get(u.id) || u.id;
      recs.push({ id: target, layer: layerOf(target), name: clean(u.name, MAX_NAME), cc: u.cc, own: target === u.id });
    });
    var byId = new Map();
    recs.forEach(function (r) {
      var had = byId.get(r.id);
      if (!had || (!had.own && r.own)) { byId.set(r.id, r); }
    });
    var kept = Array.from(byId.values());
    var hasPlace = kept.some(function (r) { return r.layer === "place"; });
    kept = kept.filter(function (r) { return !(hasPlace && r.layer === "cousub" && COEXTENSIVE.has(r.cc)); });
    kept.sort(function (a, b) { return ORDER.get(a.layer) - ORDER.get(b.layer); });   // stable sort
    var govs = kept.map(function (r) { return cardOf(r, idx.govs.get(r.id)); });
    var notes = lineNotes.slice();
    if (!notes.length) {
      if (!hasPlace) { notes.push("note.no-city"); }
      if (hadCounty && !kept.some(function (r) { return r.layer === "county"; })) { notes.push("note.no-county"); }
    }
    return { govs: govs, notes: notes };
  }

  // --- device storage (3.8) ----------------------------------------------------------------------------------------
  var KEYS = { list: "daylight.us.list", requested: "daylight.us.requested", counted: "daylight.us.counted" };
  var MAX_LIST = 20;
  var MAX_IDS = 200;
  var MAX_STORED = 8192;             // characters; a longer stored value is not read at all

  function readJson(storage, key) {
    try {
      var raw = storage.getItem(key);
      if (typeof raw !== "string" || !raw || raw.length > MAX_STORED) { return null; }
      return JSON.parse(raw);
    } catch (e) { return null; }
  }
  function writeJson(storage, key, value) {
    try { storage.setItem(key, JSON.stringify(value)); return true; } catch (e) { return false; }
  }
  function goodEntry(g) {
    return isObj(g) && typeof g.id === "string" && ID_RE.test(g.id) && typeof g.name === "string" &&
      g.name.length > 0 && g.name.length <= MAX_NAME && g.name.replace(BAD_TEXT, "") === g.name && g.name.trim() === g.name;
  }
  function listOf(govs) {
    var seen = new Set(), out = [];
    (Array.isArray(govs) ? govs : []).forEach(function (g) {
      if (out.length < MAX_LIST && goodEntry(g) && !seen.has(g.id)) { seen.add(g.id); out.push({ id: g.id, name: g.name }); }
    });
    return out;
  }
  /* The saved list -> [{id, name}] (bad entries dropped, at most 20); [] when nothing valid is stored. */
  function loadList(storage) {
    var v = readJson(storage, KEYS.list);
    return isObj(v) && v.v === 1 ? listOf(v.govs) : [];
  }
  /* Replaces the saved list with this lookup's cards (ids and Census names only). false when it was not saved. */
  function saveList(storage, govs) {
    return writeJson(storage, KEYS.list, { v: 1, govs: listOf(govs) });
  }
  function idsOf(storage, key) {
    var v = readJson(storage, key);
    if (!isObj(v) || v.v !== 1 || !Array.isArray(v.ids)) { return []; }
    var seen = new Set();
    return v.ids.filter(function (i) {
      if (typeof i !== "string" || !ID_RE.test(i) || seen.has(i)) { return false; }
      seen.add(i);
      return true;
    }).slice(-MAX_IDS);
  }
  function addIds(storage, key, ids) {
    var have = idsOf(storage, key);
    (Array.isArray(ids) ? ids : [ids]).forEach(function (i) {
      if (typeof i === "string" && ID_RE.test(i) && have.indexOf(i) < 0) { have.push(i); }
    });
    return writeJson(storage, key, { v: 1, ids: have.slice(-MAX_IDS) });
  }
  function loadRequested(storage) { return idsOf(storage, KEYS.requested); }
  function loadCounted(storage) { return idsOf(storage, KEYS.counted); }
  function markRequested(storage, ids) { return addIds(storage, KEYS.requested, ids); }
  function markCounted(storage, id) { return addIds(storage, KEYS.counted, [id]); }
  /* "Forget this list": removes all three keys (each on its own, so one failure does not keep the others). */
  function forget(storage) {
    var ok = true;
    [KEYS.list, KEYS.requested, KEYS.counted].forEach(function (k) {
      try { storage.removeItem(k); } catch (e) { ok = false; }
    });
    return ok;
  }
  /* window.localStorage, or null when reading it throws (blocked storage) or it is missing. */
  function storageOf(win) {
    try { var s = win.localStorage; return s && typeof s.getItem === "function" ? s : null; } catch (e) { return null; }
  }

  // --- geo frame, parent side (4.0) --------------------------------------------------------------------------------
  var WORDS = new Set(["ready", "blocked", "loaded"]);

  /* One message event -> null (not heard) | {type: "ready" | "blocked" | "loaded" | "too-big"} |
     {type: "answer", data}. Heard only from `frameWindow`, with origin "null" and a string; a string longer than
     MAX_ANSWER is "too-big" without being parsed (more matches than the page lists: the not-found tips, not
     "Census down"); a string JSON.parse refuses, or JSON that is neither a known word nor an object, is not heard. */
  function frameMessage(e, frameWindow) {
    if (!e || !frameWindow || e.source !== frameWindow || e.origin !== "null") { return null; }
    var d = e.data;
    if (typeof d !== "string") { return null; }
    if (d.length > MAX_ANSWER) { return { type: "too-big" }; }
    var v;
    try { v = JSON.parse(d); } catch (err) { return null; }
    if (typeof v === "string") { return WORDS.has(v) ? { type: v } : null; }
    return isObj(v) ? { type: "answer", data: v } : null;
  }

  /* What a lookup ends with, from a heard message: classify's result, or {kind: "error", blocked?, timeout?}. */
  function resultOf(msg) {
    if (msg.type === "answer") { return classify(msg.data); }
    if (msg.type === "too-big") { return { kind: "nomatch", many: true }; }
    if (msg.type === "blocked") { return { kind: "error", blocked: true }; }
    return { kind: "error" };
  }

  /* The address as sent: spaces collapsed, trimmed; "" when empty or longer than MAX_ADDRESS. */
  function cleanAddress(a) {
    var s = typeof a === "string" ? a.replace(/\s+/g, " ").trim() : "";
    return s.length <= MAX_ADDRESS ? s : "";
  }

  /* One lookup: a fresh sandboxed frame (env.frameSrc, default "geo-frame.html"), the address posted to it only after
     its "ready", done(result) called exactly once (an answer, "blocked", "loaded", too big, or no answer within
     TIMEOUT_MS), and the frame and listener removed before done runs. env = {document, window, setTimeout,
     clearTimeout, frameSrc?, timeoutMs?}. Returns {cancel()} (drops the lookup without calling done). An empty or
     over-long address sends nothing and ends {kind: "empty"} or {kind: "nomatch"}. */
  function lookup(env, address, done) {
    var doc = env.document, win = env.window;
    var setT = env.setTimeout || setTimeout, clearT = env.clearTimeout || clearTimeout;
    var raw = typeof address === "string" ? address.replace(/\s+/g, " ").trim() : "";
    var addr = cleanAddress(address);
    var over = false, asked = false, timer = null;
    if (!addr) {
      done(raw ? { kind: "nomatch" } : { kind: "empty" });
      return { cancel: function () {} };
    }
    var fr = doc.createElement("iframe");
    fr.setAttribute("sandbox", "allow-scripts");
    fr.setAttribute("referrerpolicy", "no-referrer");
    fr.setAttribute("title", "Census address lookup");
    fr.setAttribute("aria-hidden", "true");
    fr.setAttribute("tabindex", "-1");
    fr.hidden = true;
    function end(result) {
      if (over) { return; }
      over = true;
      clearT(timer);
      win.removeEventListener("message", onMessage);
      if (fr.parentNode) { fr.parentNode.removeChild(fr); }
      if (result) { done(result); }
    }
    function onMessage(e) {
      var msg = frameMessage(e, fr.contentWindow);
      if (!msg || over) { return; }
      if (msg.type === "ready") {
        if (!asked) { asked = true; fr.contentWindow.postMessage({ address: addr }, "*"); }
        return;
      }
      if (!asked) { return; }        // nothing but "ready" counts before the address was sent
      end(resultOf(msg));
    }
    win.addEventListener("message", onMessage);
    timer = setT(function () { end({ kind: "error", timeout: true }); }, env.timeoutMs || TIMEOUT_MS);
    fr.setAttribute("src", env.frameSrc || "geo-frame.html");
    doc.body.appendChild(fr);
    return { cancel: function () { end(null); } };
  }

  var api = {
    jsonpUrl: jsonpUrl, classify: classify, governments: governments, indexPagedir: indexPagedir, label: label,
    loadList: loadList, saveList: saveList, forget: forget, markRequested: markRequested, markCounted: markCounted,
    loadRequested: loadRequested, loadCounted: loadCounted, storageOf: storageOf,
    frameMessage: frameMessage, resultOf: resultOf, cleanAddress: cleanAddress, lookup: lookup,
    KEYS: KEYS, CENSUS: CENSUS, CALLBACK: CALLBACK, TIMEOUT_MS: TIMEOUT_MS, MAX_ANSWER: MAX_ANSWER,
    MAX_ADDRESS: MAX_ADDRESS, MAX_MATCHES: MAX_MATCHES, LAYER_NAMES: LAYERS.map(function (l) { return l.name; })
  };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  root.DaylightNational = api;
})(typeof window !== "undefined" ? window : this);
