/* Daylight Digest lookup, the pure part (docs/architecture/daylight-national.md 4.0, 4.1, 3.4, 3.8; tasks F1, F5).
   Node-testable like address.js: under node it exports its functions (module.exports) and touches no page; in a
   browser it sets window.DaylightNational and, on digest/index.html (the page with #digest-form), runs mount().

   - jsonpUrl(address): the Census geographies URL (ADR 0013 decision 2). The geo frame's own script
     (site/templates/_geo_frame.js) builds the same URL; tests/national.test.js holds the two to one shape.
   - classify(answer) and governments(units, pagedir): the Census answer, read as data, -> the cards and fixed lines.
   - loadList / saveList / forget / markRequested / markCounted (+ loadRequested, loadCounted): the three device keys
     of 3.8, each call wrapped so a blocked, full or throwing storage never breaks the page.
   - mount(env): the page wiring (task F2; 4.1, 4.2, 4.2a): address form, states, picker, cards, in-card request
     form, counter button, "Your saved list" and "Forget this list". Every page part comes in env, so node tests
     drive it with a fake page, storage, fetch and counter.
     Framed by any page (window.top is not window.self), it wires nothing, keeps the form hidden and shows a line
     with a target="_top" link to the page instead, and returns null.
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

  // --- page wiring (task F2; architecture 4.1, 4.2, 4.2a; UX sections 1 to 3) -------------------------------------
  /* mount(env) draws the entry page: the address form (submit only on a press), the lookup states in #digest-result,
     the picker and the cards in #digest-list, the in-card request form, the counter button and "Your saved list" in
     #digest-saved. env = {document, window, storage (or null), fetch (or null: the request form then posts natively),
     count (window.DaylightCount or undefined), setTimeout, clearTimeout}. Every word is a label from #digest-strings or
     the page directory, or a Census or directory string, all drawn with textContent; links are built with
     setAttribute("href") from checked paths and https URLs only. The address goes to the frame only (lookup); the
     email lives in one page variable (to prefill a second card's form) and is posted only to the config's
     form_action; storage gets ids and Census names only (3.8). Nothing here writes the page's URL or title. */
  var CONFIG_SCHEMA = "daylight-digest-config/1";
  var STILL_MS = 6000;                                   // "Still looking" after 6 s (UX section 2)
  var FILE_RE = /^[a-z0-9][a-z0-9-]*\.html$/;            // config frame and covered: a page beside digest/index.html
  var HREF_RE = /^[a-z0-9][a-z0-9\/_.-]*(#[a-z0-9-]+)?$/; // config morning, relative to the site root
  var STRING_RE = /^(lookup|form|count)\.[a-z0-9][a-z0-9-]*$/;
  var EMAIL_RE = /^[^\s@<>()\[\]",;:\\]+@[^\s@<>()\[\]",;:\\.]+(\.[^\s@<>()\[\]",;:\\.]+)+$/;
  var MAX_EMAIL = 254;
  var MAX_STRING = 600;
  var MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
    "November", "December"];

  /* "2026-11-07" -> "November 7, 2026" (the site's day_words); "" for anything else. */
  function dayWords(iso) {
    if (typeof iso !== "string" || !DATE_RE.test(iso)) { return ""; }
    var p = iso.split("-").map(Number);
    return p[1] >= 1 && p[1] <= 12 && p[2] >= 1 && p[2] <= 31 ? MONTHS[p[1] - 1] + " " + p[2] + ", " + p[0] : "";
  }
  function goodEmail(s) { return typeof s === "string" && s.length <= MAX_EMAIL && EMAIL_RE.test(s); }
  /* `{name}` fields filled from `values` (own keys only); an unknown field stays as written. */
  function fill(t, values) {
    return String(t).replace(/\{([a-z]+)\}/g, function (m, k) { return values && own(values, k) ? String(values[k]) : m; });
  }
  /* #digest-strings -> Map of the lookup.*, form.* and count.* labels, cleaned (textContent only). */
  function stringsOf(v) {
    var m = new Map();
    if (isObj(v)) {
      Object.keys(v).forEach(function (k) {
        if (STRING_RE.test(k) && typeof v[k] === "string") { m.set(k, clean(v[k], MAX_STRING)); }
      });
    }
    return m;
  }
  /* #digest-config -> the checked settings. The request form shows only with an https form_action and privacy_url;
     the election-office and Census lines only with an https election_url / census_url. */
  function configOf(v) {
    var c = { frame: "geo-frame.html", covered: "covered.html", formAction: null, privacyUrl: null, morning: null,
              election: null, census: null };
    if (!isObj(v) || v.schema !== CONFIG_SCHEMA) { return c; }
    if (typeof v.frame === "string" && FILE_RE.test(v.frame)) { c.frame = v.frame; }
    if (typeof v.covered === "string" && FILE_RE.test(v.covered)) { c.covered = v.covered; }
    if (httpsUrl(v.form_action) && httpsUrl(v.privacy_url)) { c.formAction = v.form_action; c.privacyUrl = v.privacy_url; }
    if (typeof v.morning === "string" && HREF_RE.test(v.morning) && v.morning.indexOf("..") < 0 &&
        v.morning.indexOf("//") < 0) { c.morning = v.morning; }
    // fixed outside pages (UX v1.2): the election-office finder and the Census's own lookup; never given the address
    if (httpsUrl(v.election_url)) { c.election = v.election_url; }
    if (httpsUrl(v.census_url)) { c.census = v.census_url; }
    return c;
  }
  function readBlock(doc, id) {
    var el = doc.getElementById(id);
    if (!el) { return null; }
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }
  function findButton(node) {
    var kids = node && node.children ? node.children : [];
    for (var i = 0; i < kids.length; i++) {
      if (String(kids[i].tagName).toUpperCase() === "BUTTON") { return kids[i]; }
      var got = findButton(kids[i]);
      if (got) { return got; }
    }
    return null;
  }

  function mount(env) {
    var doc = env.document, win = env.window, storage = env.storage || null;
    var setT = env.setTimeout || setTimeout, clearT = env.clearTimeout || clearTimeout;
    var form = doc.getElementById("digest-form"), input = doc.getElementById("digest-q");
    var result = doc.getElementById("digest-result"), list = doc.getElementById("digest-list");
    var saved = doc.getElementById("digest-saved"), noscript = doc.getElementById("digest-noscript");
    var find = form ? findButton(form) : null;
    if (!form || !input || !result || !list || !saved || !find) { return null; }
    var idx = asIndex(readBlock(doc, "digest-pagedir"));
    var STR = stringsOf(readBlock(doc, "digest-strings"));
    var cfg = configOf(readBlock(doc, "digest-config"));
    var post = typeof env.fetch === "function" ? env.fetch : null;
    var count = env.count && env.count.available === true && typeof env.count.send === "function" ? env.count : null;
    var findText = find.textContent;
    var busy = false, stillTimer = null, seq = 0;
    var email = "";                 // page memory only: prefills the next card's form; never stored
    var openCard = null;            // the card whose request form is open (one at a time)
    var epoch = 0;                  // bumped by "Forget this list": a post or count that ends later writes nothing
    var censusLine = null;          // the down state's Census line, a sibling after #digest-result
    if (!result.hasAttribute("tabindex")) { result.setAttribute("tabindex", "-1"); }

    function S(k) { var v = STR.get(k); return typeof v === "string" ? v : ""; }
    function text(s) { return doc.createTextNode(String(s)); }
    function el(tag, cls, words) {
      var e = doc.createElement(tag);
      if (cls) { e.setAttribute("class", cls); }
      if (words) { e.textContent = words; }
      return e;
    }
    function button(words, cls) {
      var b = el("button", cls, words);
      b.setAttribute("type", "button");
      return b;
    }
    function named(b, name) { b.appendChild(el("span", "sr-only", ": " + name)); return b; }
    function heading(tag, words) { var h = el(tag, null, words); h.setAttribute("tabindex", "-1"); return h; }
    function status(cls) {
      var p = el("p", cls);
      p.setAttribute("role", "status");
      p.setAttribute("tabindex", "-1");
      return p;
    }
    function focus(node) { if (node && typeof node.focus === "function") { node.focus(); } }
    function anchor(words, href, ext) {
      var a = el("a", null, words);
      a.setAttribute("href", href);
      if (ext) { a.setAttribute("rel", "noopener noreferrer"); }
      return a;
    }
    function linkLine(words, href, ext) {
      var p = el("p");
      p.appendChild(anchor(words, href, ext));
      return p;
    }
    /* A label with one `[text]` link mark: the parts before and after as text, the mark a link to `href`; with no
       href the mark and its words are left out. Fields are filled in each part after the mark is found, so a value
       holding brackets never becomes a link. */
    function put(parent, key, href, values, ext) {
      var t = S(key), m = /\[([^\[\]]+)\]/.exec(t);
      if (!m) { parent.appendChild(text(fill(t, values))); return parent; }
      var before = fill(t.slice(0, m.index), values), after = fill(t.slice(m.index + m[0].length), values);
      if (!href) {
        parent.appendChild(text((before + after).replace(/\s+/g, " ").replace(/\s+([.,])/g, "$1").trim()));
        return parent;
      }
      parent.appendChild(text(before));
      parent.appendChild(anchor(fill(m[1], values), href, ext));
      if (after) { parent.appendChild(text(after)); }
      return parent;
    }
    function say(parts) {
      if (censusLine && censusLine.parentNode) { censusLine.parentNode.removeChild(censusLine); }
      censusLine = null;
      result.textContent = "";
      (parts || []).forEach(function (x) { result.appendChild(typeof x === "string" ? text(x) : x); });
    }
    function setBusy(on) {
      busy = on;
      find.textContent = on ? S("lookup.button-busy") : findText;
      if (on) { find.setAttribute("aria-disabled", "true"); } else { find.removeAttribute("aria-disabled"); }
    }
    function clearList() { list.textContent = ""; list.hidden = true; openCard = null; }
    function clearSaved() { saved.textContent = ""; saved.hidden = true; }

    // -- framed by another page (national/postmessage-hardening/framed-parent): the form stays hidden and nothing is
    // wired, so no address is typed under a parent we don't control. The no-script line instead says the lookup
    // works only on our own page, with a link that opens it as the top page. Defence in depth beside the CSP's
    // frame-src 'self' (sitegen/national_pages.py index_csp). Reading window.top can throw: that counts as framed.
    var framed;
    try { framed = win.top !== win.self; } catch (e) { framed = true; }
    if (framed) {
      form.hidden = true;
      if (noscript) {
        var fw = S("lookup.framed"), fm = /\[([^\[\]]+)\]/.exec(fw);
        noscript.textContent = "";
        if (fm) {
          var topLink = anchor(fm[1], "index.html");
          topLink.setAttribute("target", "_top");
          noscript.appendChild(text(fw.slice(0, fm.index)));
          noscript.appendChild(topLink);
          if (fw.slice(fm.index + fm[0].length)) { noscript.appendChild(text(fw.slice(fm.index + fm[0].length))); }
        } else {
          noscript.appendChild(text(fw));
        }
        noscript.hidden = false;
      }
      return null;
    }

    // -- the address form: a lookup starts only on a press of Find or Enter (no input, key or change listener) --
    function run() {
      if (busy) { return; }
      var address = input.value;
      if (typeof address !== "string" || !address.trim()) { say([S("lookup.empty")]); focus(input); return; }
      setBusy(true);
      clearList();
      say([S("lookup.looking")]);
      stillTimer = setT(function () { if (busy) { result.appendChild(text(" " + S("lookup.still"))); } }, STILL_MS);
      lookup({ document: doc, window: win, setTimeout: setT, clearTimeout: clearT, frameSrc: cfg.frame,
               timeoutMs: TIMEOUT_MS }, address, finish);
    }
    function finish(r) {
      clearT(stillTimer);
      setBusy(false);
      r = r || { kind: "error" };
      if (r.kind === "empty") { say([S("lookup.empty")]); focus(input); return; }
      if (r.kind === "nomatch") { say([S("lookup.not-found") + " " + S("lookup.not-found-tip")]); focus(input); return; }
      if (r.kind === "pick") { showPick(r.matches); return; }
      if (r.kind === "one") { showList(r.matched, r.units); return; }
      // error, timeout or a blocked frame: never a guessed place; Try again resends the text still in the box
      var retry = button(S("lookup.retry"), "more-btn digest-retry");
      // Try again: focus goes to the status line (the button is about to go), then once more after the result
      retry.addEventListener("click", function () { focus(result); run(); });
      say([S("lookup.down") + " ", retry, " "]);
      put(result, "lookup.down-browse", cfg.covered);
      if (cfg.census && result.parentNode) {
        censusLine = put(el("p", "digest-census"), "lookup.down-census", cfg.census, null, true);
        result.parentNode.insertBefore(censusLine, result.nextSibling);
      }
      focus(retry);
    }
    form.addEventListener("submit", function (e) { e.preventDefault(); run(); });

    // -- the picker (more than one match) --
    function showPick(matches) {
      say([]);
      clearSaved();
      clearList();
      list.hidden = false;
      var h = heading("h2", S("lookup.pick-h"));
      list.appendChild(h);
      var ul = el("ul", "digest-pick");
      matches.forEach(function (m) {
        if (!m.label) { return; }
        var b = button(m.label, "more-btn digest-pick-btn");
        b.addEventListener("click", function () { showList(m.label, m.units); });
        var li = el("li");
        li.appendChild(b);
        ul.appendChild(li);
      });
      list.appendChild(ul);
      var none = button(S("lookup.pick-none"), "more-btn");
      none.addEventListener("click", function () { clearList(); focus(input); });
      list.appendChild(none);
      focus(h);
    }

    // -- the list for this spot --
    function summary(govs) {
      var a = 0, b = 0, c = 0;
      govs.forEach(function (g) {
        if (g.status === "covered") { a += 1; } else if (g.status === "cant-cover") { c += 1; } else { b += 1; }
      });
      var one = govs.length === 1;
      var head = one ? S("lookup.summary-found-one") : fill(S("lookup.summary-found"), { n: govs.length });
      if (!a) {
        var tail = S(one ? "lookup.summary-none-one" : "lookup.summary-none");
        // "None are covered yet. Request the ones you want ...": with no email form, only the first sentence
        if (!cfg.formAction) { tail = tail.replace(/^([^.]*\.)\s.*$/, "$1"); }
        return head + " " + tail;
      }
      var parts = [fill(S("lookup.summary-covered"), { n: a })];
      if (b) { parts.push(fill(S("lookup.summary-not-yet"), { n: b })); }
      if (c) { parts.push(fill(S("lookup.summary-cant"), { n: c })); }
      return head + " " + parts.join(", ") + ".";
    }
    function showList(matched, units) {
      var r = governments(units, idx);
      say([]);
      clearSaved();
      clearList();
      list.hidden = false;
      var h = heading("h2", S("lookup.list-h"));
      list.appendChild(h);
      if (matched) { list.appendChild(el("p", "addr-matched", fill(S("lookup.matched"), { line: matched }))); }
      if (!r.govs.length) {
        list.appendChild(el("p", null, S("lookup.nothing-listable")));
        list.appendChild(el("p", "muted", S("lookup.under-list")));
        if (cfg.election) { list.appendChild(put(el("p", "muted"), "lookup.election-none", cfg.election, null, true)); }
      } else {
        list.appendChild(el("p", "coverage", summary(r.govs)));
        r.notes.forEach(function (k) { var t = label(idx, k); if (t) { list.appendChild(el("p", "note", t)); } });
        var kept = saveList(storage, r.govs);
        drawCards(list, r.govs);
        list.appendChild(el("p", "muted", S("lookup.under-list")));
        if (cfg.election) { list.appendChild(put(el("p", "muted"), "lookup.election", cfg.election, null, true)); }
        if (kept) { deviceLine(list); }
      }
      var again = button(S("lookup.another"), "more-btn");
      again.addEventListener("click", function () { clearList(); say([]); focus(input); });
      list.appendChild(again);
      focus(h);
    }

    // -- "Your saved list" (3.8): ids re-checked with layerOf (the layer's exact GEOID length) before a card --
    function showSaved() {
      clearSaved();
      var govs = loadList(storage).filter(function (g) { return !!layerOf(g.id) && !idx.hide.has(g.id); }).map(function (g) {
        return cardOf({ id: g.id, name: g.name, layer: layerOf(g.id) }, idx.govs.get(g.id));
      });
      if (!govs.length) { return; }
      saved.hidden = false;
      saved.appendChild(heading("h2", S("lookup.saved-h")));
      drawCards(saved, govs);
      deviceLine(saved);
    }
    function deviceLine(parent) {
      var box = el("div", "your-seats digest-device");
      box.appendChild(el("p", "your-seats-note", S("lookup.device-line")));
      var b = button(S("lookup.forget"), "your-seats-forget");
      b.addEventListener("click", function () {
        epoch += 1;
        forget(storage);
        clearList();
        clearSaved();
        say([]);
        focus(input);
      });
      box.appendChild(b);
      parent.appendChild(box);
    }

    // -- cards (UX section 3: slot, Census name, board, pill, then the status's actions) --
    function drawCards(parent, govs) {
      var view = new Map();      // the uncovered cards of this list: "Also request" and the Sent flip
      var requested = new Set(loadRequested(storage)), counted = new Set(loadCounted(storage));
      var ul = el("ul", "bodies-list digest-cards");
      govs.forEach(function (g) { ul.appendChild(card(g, view, requested.has(g.id), counted.has(g.id))); });
      parent.appendChild(ul);
    }
    function pill(st) {
      var key = st === "covered" ? "lookup.status-covered" : st === "cant-cover" ? "lookup.status-cant" : "lookup.status-not-yet";
      var mark = st === "covered" ? "✓" : st === "cant-cover" ? "⊘" : "○";
      var p = el("p", "digest-status");
      var chip = el("span", "chip digest-pill digest-pill-" + st);
      var icon = el("span", null, mark);
      icon.setAttribute("aria-hidden", "true");
      chip.appendChild(icon);
      chip.appendChild(text(S(key)));
      p.appendChild(chip);
      return p;
    }
    function card(g, view, wasRequested, wasCounted) {
      var li = el("li", "bodies-card digest-card");
      li.setAttribute("data-status", g.status);
      li.appendChild(el("p", "eyebrow", label(idx, "slot." + g.slot)));
      li.appendChild(el("h3", null, g.name));
      if (g.board) { li.appendChild(el("p", "digest-board", g.board)); }
      li.appendChild(pill(g.status));
      if (g.status === "covered") {
        if (g.page) { li.appendChild(linkLine(S("lookup.coming-up"), idx.root + g.page)); }
        if (g.full) {
          li.appendChild(linkLine(S("lookup.full"), idx.root + g.full));
          if (cfg.morning) { li.appendChild(linkLine(S("lookup.morning"), idx.root + cfg.morning)); }
        }
        return li;
      }
      if (g.status === "cant-cover") {
        var why = g.reason ? label(idx, "reason." + g.reason) : "";
        if (why) { li.appendChild(el("p", "digest-reason", why)); }
        if (dayWords(g.checked)) {
          li.appendChild(put(el("p", "digest-checked"), "lookup.checked", g.reason_url || null,
                             { date: dayWords(g.checked) }, true));
        }
      } else {
        li.appendChild(el("p", null, S("lookup.not-yet-line")));
      }
      if (g.official_url) {
        li.appendChild(linkLine(S("lookup.official"), g.official_url, true));
      } else if (g.status === "not-covered-yet") {
        li.appendChild(el("p", null, S("lookup.no-official")));
      }
      var c = { id: g.id, name: g.name, status: g.status, view: view };
      view.set(g.id, c);
      if (cfg.formAction) {
        c.req = el("div", "digest-request");
        c.msg = status("digest-msg");
        c.body = el("div");
        c.req.appendChild(c.msg);
        c.req.appendChild(c.body);
        li.appendChild(c.req);
        drawRequest(c, wasRequested ? "returning" : "ready");
      }
      if (count) {
        c.cnt = el("div", "digest-count");
        li.appendChild(c.cnt);
        drawCount(c, wasCounted);
      }
      return li;
    }

    // -- "Request it" and the in-card form (4.2) --
    function drawRequest(c, state) {
      if (openCard === c) { openCard = null; }
      c.body.textContent = "";
      c.form = null;
      c.msg.textContent = "";
      c.msg.removeAttribute("data-state");
      var words = "lookup.request";
      if (state === "returning") {
        c.msg.textContent = S("form.returning");
        c.msg.setAttribute("data-state", "returning");
        words = "form.again";
      } else if (state === "sent") {
        var mark = el("span", null, "✓ ");
        mark.setAttribute("aria-hidden", "true");
        c.msg.appendChild(mark);
        c.msg.appendChild(text(S("form.sent")));
        c.msg.setAttribute("data-state", "sent");
        words = "form.different";
      }
      var b = named(button(S(words), "more-btn digest-request-btn"), c.name);
      b.setAttribute("aria-expanded", "false");
      b.addEventListener("click", function () {
        if (c.sending) { return; }
        if (c.form) { closeForm(c); } else { openForm(c); }
      });
      c.body.appendChild(b);
      c.btn = b;
      if (state === "ready") { c.body.appendChild(el("p", "hint", S("lookup.request-hint"))); }
    }
    function closeForm(c) {
      if (c.form && c.form.parentNode) { c.form.parentNode.removeChild(c.form); }
      c.form = null;
      c.btn.setAttribute("aria-expanded", "false");
      if (openCard === c) { openCard = null; }
    }
    function openForm(c) {
      if (openCard && openCard !== c && openCard.form) { closeForm(openCard); }
      seq += 1;
      var n = "dr-" + seq;
      var f = el("form", "digest-req-form");
      f.setAttribute("method", "post");
      f.setAttribute("action", cfg.formAction);
      f.setAttribute("novalidate", "");
      var h = heading("h4", S("form.h"));
      f.appendChild(h);
      f.appendChild(el("p", null, S(c.status === "cant-cover" ? "form.honest-cant" : "form.honest-not-yet")));
      var lab = el("label", null, S("form.email-label"));
      lab.setAttribute("for", n + "-email");
      var box = el("input");
      box.setAttribute("id", n + "-email");
      box.setAttribute("type", "email");
      box.setAttribute("name", "email");
      box.setAttribute("autocomplete", "email");
      box.setAttribute("maxlength", String(MAX_EMAIL));
      box.setAttribute("required", "");
      box.setAttribute("aria-describedby", n + "-err");
      box.value = email;
      var err = el("p", "digest-err");
      err.setAttribute("id", n + "-err");
      err.hidden = true;
      var mine = el("input");
      mine.setAttribute("type", "hidden");
      mine.setAttribute("name", "tag");
      mine.setAttribute("value", "req-" + c.id);
      f.appendChild(lab);
      f.appendChild(box);
      f.appendChild(err);
      f.appendChild(mine);
      var ticks = [];
      c.view.forEach(function (o) {
        if (o === c || !layerOf(o.id)) { return; }
        var l = el("label", "mn-check");
        var t = el("input");
        t.setAttribute("type", "checkbox");
        t.setAttribute("name", "tag");
        t.setAttribute("value", "req-" + o.id);
        t.checked = false;
        l.appendChild(t);
        l.appendChild(el("span", null, o.name));
        ticks.push({ box: t, id: o.id, label: l });
      });
      if (ticks.length) {
        var fs = el("fieldset", "mn-picker digest-also");
        fs.appendChild(el("legend", null, S("form.also")));
        ticks.forEach(function (t) { fs.appendChild(t.label); });
        f.appendChild(fs);
      }
      f.appendChild(put(el("p", "hint"), "form.privacy-1", cfg.privacyUrl, null, true));
      f.appendChild(el("p", "hint", S("form.privacy-2")));
      var send = el("button", "more-btn digest-send", S("form.send"));
      send.setAttribute("type", "submit");
      var cancel = button(S("form.cancel"), "more-btn");
      cancel.addEventListener("click", function () { closeForm(c); focus(c.btn); });
      f.appendChild(send);
      f.appendChild(cancel);
      f.addEventListener("submit", function (e) {
        if (c.sending) { e.preventDefault(); return; }
        var addr = typeof box.value === "string" ? box.value.trim() : "";
        if (!goodEmail(addr)) {
          e.preventDefault();
          err.textContent = S("form.bad-email");
          err.setAttribute("data-state", "bad-email");
          err.hidden = false;
          box.setAttribute("aria-invalid", "true");
          focus(box);
          return;
        }
        err.textContent = "";
        err.hidden = true;
        box.removeAttribute("aria-invalid");
        // this card's id always; the others only when ticked (ids from this page's own cards, not the DOM values)
        var ids = [c.id];
        ticks.forEach(function (t) { if (t.box.checked === true && ids.indexOf(t.id) < 0) { ids.push(t.id); } });
        if (!post) {
          // no fetch: the browser posts this real form itself (method=post, action=form_action; fields email, tag)
          markRequested(storage, ids);
          return;
        }
        e.preventDefault();
        var body = new URLSearchParams();
        body.append("email", addr);
        ids.forEach(function (i) { body.append("tag", "req-" + i); });
        c.sending = true;
        c.btn.setAttribute("aria-disabled", "true");
        send.textContent = S("form.sending");
        send.setAttribute("aria-disabled", "true");
        var at = epoch;
        var p;
        try {
          p = Promise.resolve(post(cfg.formAction, { method: "POST", mode: "no-cors", credentials: "omit",
                                                     referrerPolicy: "no-referrer", body: body }));
        } catch (x) { p = Promise.reject(x); }
        p.then(function () {
          c.sending = false;
          c.btn.removeAttribute("aria-disabled");
          if (at !== epoch) { return; }        // "Forget this list" while it was in flight: nothing written or drawn
          email = addr;
          markRequested(storage, ids);
          ids.forEach(function (i) { var o = c.view.get(i); if (o && o.req) { drawRequest(o, "sent"); } });
          focus(c.msg);
        }, function () {
          c.sending = false;
          c.btn.removeAttribute("aria-disabled");
          if (at !== epoch) { return; }
          send.textContent = S("form.send");
          send.removeAttribute("aria-disabled");
          c.msg.textContent = S("form.failed");
          c.msg.setAttribute("data-state", "failed");
          focus(c.msg);
        });
      });
      c.msg.textContent = "";
      c.msg.removeAttribute("data-state");
      c.body.appendChild(f);
      c.form = f;
      c.btn.setAttribute("aria-expanded", "true");
      openCard = c;
      focus(h);
    }

    // -- "No email? Just count me." (4.2a): only while DaylightCount.available --
    function drawCount(c, done) {
      c.cnt.textContent = "";
      var msg = status("digest-msg");
      if (done) {
        msg.textContent = S("count.done");
        msg.setAttribute("data-state", "counted");
        c.cnt.appendChild(msg);
        return msg;
      }
      var b = named(button(S("count.button"), "more-btn digest-count-btn"), c.name);
      var counting = false;
      b.addEventListener("click", function () {
        if (counting) { return; }
        counting = true;
        b.setAttribute("aria-disabled", "true");
        var at = epoch;
        var p;
        try { p = Promise.resolve(count.send(c.id)); } catch (x) { p = Promise.reject(x); }
        p.then(function () {
          if (at !== epoch) { return; }        // forgotten while in flight
          markCounted(storage, c.id);
          focus(drawCount(c, true));
        }, function () {
          counting = false;
          b.removeAttribute("aria-disabled");
          if (at !== epoch) { return; }
          msg.textContent = S("count.failed");
          msg.setAttribute("data-state", "failed");
          focus(msg);
        });
      });
      c.cnt.appendChild(b);
      c.cnt.appendChild(msg);
      return msg;
    }

    if (noscript) { noscript.hidden = true; }
    form.hidden = false;
    showSaved();
    return { run: run };
  }

  var api = {
    jsonpUrl: jsonpUrl, classify: classify, governments: governments, indexPagedir: indexPagedir, label: label,
    loadList: loadList, saveList: saveList, forget: forget, markRequested: markRequested, markCounted: markCounted,
    loadRequested: loadRequested, loadCounted: loadCounted, storageOf: storageOf,
    frameMessage: frameMessage, resultOf: resultOf, cleanAddress: cleanAddress, lookup: lookup,
    mount: mount, dayWords: dayWords, goodEmail: goodEmail,
    KEYS: KEYS, CENSUS: CENSUS, CALLBACK: CALLBACK, TIMEOUT_MS: TIMEOUT_MS, MAX_ANSWER: MAX_ANSWER,
    MAX_ADDRESS: MAX_ADDRESS, MAX_MATCHES: MAX_MATCHES, LAYER_NAMES: LAYERS.map(function (l) { return l.name; })
  };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  root.DaylightNational = api;
  // The entry page (digest/index.html) loads this with defer, after us-count.js, so the page and DaylightCount exist.
  if (root.document && root.document.getElementById("digest-form")) {
    mount({ document: root.document, window: root, storage: storageOf(root),
            fetch: typeof root.fetch === "function" ? function (u, o) { return root.fetch(u, o); } : null,
            count: root.DaylightCount, setTimeout: function (f, ms) { return root.setTimeout(f, ms); },
            clearTimeout: function (t) { root.clearTimeout(t); } });
  }
})(typeof window !== "undefined" ? window : this);
