/* Search (docs/design/landing-search-nav.md 5). First-party, vanilla, no network calls: the index is
   window.SEARCH_INDEX from static/search-index.js, written by the site build. Every filter lives in the URL
   (history.replaceState), so a search can be bookmarked or shared; nothing about the visitor is stored (N6).
   Unconfirmed roll calls carry no outcome and no votes in the index, so a vote, outcome or official filter can never
   match one; a fixed line says how many were left out. */
(function () {
  var form = document.getElementById("search-form");
  if (!form) { return; }
  var results = document.getElementById("results");
  var countEl = document.getElementById("count");
  var moreBtn = document.getElementById("more");
  var chipsEl = document.getElementById("chips");
  var noteEl = document.getElementById("confirmed-only");
  var panel = document.getElementById("filter-panel");
  var IX = window.SEARCH_INDEX;
  var PAGE = 50;
  var shown = PAGE;
  var KIND = { item: "Item", vote: "Roll call", meeting: "Meeting", person: "Person or district", sol: "Bids and awards" };
  var OUTCOME = { passed: "Passed", failed: "Failed", other: "Other" };
  var VOTE = { yes: "Yes", no: "No", abstain: "Abstain", other: "Other" };
  var MULTI = ["kind", "type", "outcome", "body"];
  var SINGLE = ["q", "from", "to", "official", "vote", "order"];

  if (!IX) {
    results.setAttribute("aria-busy", "false");
    results.innerHTML = "<p>Search could not load here. It works when the site is opened from a web address. " +
      "You can browse Items by year or download the data.</p>";
    return;
  }
  var TYPES = {};
  IX.types.forEach(function (t) { TYPES[t.key] = t.label; });
  var OFFICIALS = {};
  IX.officials.forEach(function (o) { OFFICIALS[o.id] = o.label; });
  var BODIES = {};
  (IX.bodies || []).forEach(function (b) { BODIES[b.key] = b.label; });
  // Each official's page: a council's members live under its own folder (sitegen/council.py).
  function officialHref(id) { return (IX.hrefs && IX.hrefs[id]) || "officials/" + id + ".html"; }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function tokens(q) { return q.toLowerCase().split(/\s+/).filter(Boolean); }
  // Highlight on the raw text, then escape each piece, so a match never splits an entity like &amp;.
  function mark(text, toks) {
    text = String(text);
    if (!toks.length) { return esc(text); }
    var re = new RegExp(toks.map(function (t) {
      return t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }).join("|"), "gi");
    var out = "", last = 0, m;
    while ((m = re.exec(text)) !== null) {
      if (!m[0].length) { re.lastIndex++; continue; }
      out += esc(text.slice(last, m.index)) + "<mark>" + esc(m[0]) + "</mark>";
      last = m.index + m[0].length;
    }
    return out + esc(text.slice(last));
  }

  // ---- state <-> URL <-> controls
  function readURL() {
    var p = new URLSearchParams(location.search), st = {};
    SINGLE.forEach(function (k) { st[k] = p.get(k) || ""; });
    MULTI.forEach(function (k) { st[k] = p.getAll(k); });
    return st;
  }
  function writeURL(st) {
    var p = new URLSearchParams();
    SINGLE.forEach(function (k) { if (st[k]) { p.set(k, st[k]); } });
    MULTI.forEach(function (k) { st[k].forEach(function (v) { p.append(k, v); }); });
    var qs = p.toString();
    history.replaceState(null, "", location.pathname + (qs ? "?" + qs : ""));
  }
  function toControls(st) {
    form.q.value = st.q;
    ["from", "to", "official", "order"].forEach(function (k) { form[k].value = st[k]; });
    MULTI.forEach(function (k) {
      form.querySelectorAll('input[name="' + k + '"]').forEach(function (el) { el.checked = st[k].indexOf(el.value) >= 0; });
    });
    form.querySelectorAll('input[name="vote"]').forEach(function (el) { el.checked = el.value === st.vote; });
  }
  function fromControls() {
    var st = {};
    SINGLE.forEach(function (k) { st[k] = ""; });
    st.q = form.q.value.trim();
    ["from", "to", "official", "order"].forEach(function (k) { st[k] = form[k].value; });
    MULTI.forEach(function (k) {
      st[k] = [];
      form.querySelectorAll('input[name="' + k + '"]:checked').forEach(function (el) { st[k].push(el.value); });
    });
    var v = form.querySelector('input[name="vote"]:checked');
    st.vote = st.official && v ? v.value : "";
    return st;
  }

  // ---- matching
  // r.x: a solicitation's department and every bidder name (finance-contracts F7)
  function hay(r) { return (r.n + " " + r.t + " " + (r.st || "") + " " + (r.z || "") + " " + (r.x || "")).toLowerCase(); }
  // The header's "Show records from" choice (static/switch.js keeps it on <html>): used only while no Body box is
  // ticked and only for a body this index holds (the form's data-body-live), never written to the URL, and shown by
  // the switch's own "Showing ... only" line above the form. While a Body box is ticked that line is hidden, since
  // the boxes, not the choice, then decide what is shown.
  var LIVE = " " + (form.getAttribute("data-body-live") || "") + " ";
  function chosenBody() {
    var v = document.documentElement.getAttribute("data-body-choice");
    return v && v !== "all" && LIVE.indexOf(" " + v + " ") >= 0 ? v : "";
  }
  function bodyLine(st) {
    var el = document.getElementById("bs-line");
    if (el) { el.hidden = st.body.length > 0; }
  }
  function baseMatch(r, st, toks) {  // every filter except official, vote and outcome
    if (st.kind.length && st.kind.indexOf(r.k) < 0) { return false; }
    if (st.body.length && st.body.indexOf(r.b) < 0) { return false; }
    if (!st.body.length && st.pref && r.b !== st.pref) { return false; }
    if (st.from || st.to) {
      var lo = st.from ? +st.from : -Infinity, hi = st.to ? +st.to : Infinity;
      if (!r.y.some(function (y) { return y >= lo && y <= hi; })) { return false; }
    }
    if (st.type.length && !r.ty.some(function (t) { return st.type.indexOf(t) >= 0; })) { return false; }
    var h = hay(r);
    for (var i = 0; i < toks.length; i++) { if (h.indexOf(toks[i]) < 0) { return false; } }
    return true;
  }
  function confirmedOnly(st) { return !!(st.official || st.vote || st.outcome.length); }
  function confirmedMatch(r, st) {
    if (st.outcome.length && !(r.o && st.outcome.indexOf(r.o) >= 0)) { return false; }
    if (st.official) {
      if (r.k === "person" && r.id === st.official && !st.vote && !st.outcome.length) { return true; }
      if (!r.v || !(st.official in r.v)) { return false; }
      if (st.vote && r.v[st.official] !== st.vote) { return false; }
    }
    return true;
  }
  function score(r, toks) {
    var t = r.t.toLowerCase(), n = r.n.toLowerCase(), s = 0;
    toks.forEach(function (k) { if (n === k) { s += 10; } if (n.indexOf(k) >= 0) { s += 3; } if (t.indexOf(k) >= 0) { s += 1; } });
    return s;
  }

  // The seat an official held on a roll-call date (design 6A.2); the fixed words when no record covers it.
  function seatOn(d, id) {
    var day = IX.seat_on && IX.seat_on[d];
    return day && (id in day) ? IX.seat_labels[day[id]] : "seat not recorded";
  }

  // ---- rendering
  function row(r, st, toks) {
    var parts = [KIND[r.k]];
    if (r.k === "item" || r.k === "vote") {
      r.ty.forEach(function (t) { parts.push(TYPES[t] || t); });
      parts.push(BODIES[r.b] || IX.county_body);
    }
    var html = '<li class="result"><p class="r-kind">' + esc(parts.join(" · ")) + "</p>";
    html += '<p class="r-title"><a href="' + esc(r.h) + '">' + (r.n ? "<strong>" + mark(r.n, toks) + "</strong> " : "") +
      mark(r.t, toks) + "</a>" + (r.st ? ' <span class="seat">' + (r.ho ? '<a href="' + esc(officialHref(r.ho)) + '">' + mark(r.st, toks) + "</a>" : mark(r.st, toks)) + "</span>" : "") + "</p>" +
      (r.z ? '<p class="r-zoning">' + mark(r.z, toks) + "</p>" : "") +
      (r.x ? '<p class="r-zoning">' + mark(r.x, toks) + "</p>" : "");
    var meta = "";
    if (r.k === "item") {
      meta = r.a ? "Appears " + r.a + (r.a === 1 ? " time" : " times") + ", " + esc(r.d) + (r.d2 !== r.d ? " to " + esc(r.d2) : "")
        : "No appearance listed";
    } else if (r.k === "vote") {
      meta = esc(r.d) + " · Outcome: " + (r.c && r.o ? esc(OUTCOME[r.o]) : 'Not confirmed<span aria-hidden="true">*</span><span class="sr-only"> (not confirmed)</span>, see the page');
      if (st.official && st.vote && r.v && r.s) {
        meta += '<br><a href="' + esc(officialHref(st.official)) + '">' + esc(IX.names[st.official]) + '</a><span class="seat">, ' + esc(seatOn(r.d, st.official)) + "</span>: " +
          esc(VOTE[r.v[st.official]]) +
          ' · Source: <a href="' + esc(r.s.u) + '" target="_blank" rel="noopener noreferrer">minutes p. ' + esc(r.s.p) +
          ", fetched " + esc(r.s.f) + "</a>";
      }
    } else if (r.k === "meeting" || r.k === "sol") {
      meta = esc(r.d);
    }
    return html + (meta ? '<p class="r-meta">' + meta + "</p>" : "") + "</li>";
  }
  function chip(label, onRemove) {
    var li = document.createElement("li");
    var b = document.createElement("button");
    b.type = "button";
    b.className = "chip chip-filter";
    b.innerHTML = esc(label) + ' <span aria-hidden="true">&times;</span><span class="sr-only"> (remove)</span>';
    b.addEventListener("click", function () { onRemove(); toControls(state); update(); });
    li.appendChild(b);
    return li;
  }
  function renderChips(st) {
    chipsEl.innerHTML = "";
    st.kind.forEach(function (k) { chipsEl.appendChild(chip("Show: " + KIND[k], function () { state.kind = state.kind.filter(function (x) { return x !== k; }); })); });
    if (st.from || st.to) { chipsEl.appendChild(chip("Years: " + (st.from || "any") + "-" + (st.to || "any"), function () { state.from = state.to = ""; })); }
    st.type.forEach(function (t) { chipsEl.appendChild(chip("Type: " + TYPES[t], function () { state.type = state.type.filter(function (x) { return x !== t; }); })); });
    st.body.forEach(function (b) { chipsEl.appendChild(chip("Body: " + (BODIES[b] || b), function () { state.body = state.body.filter(function (x) { return x !== b; }); })); });
    if (st.official) { chipsEl.appendChild(chip("Official: " + (OFFICIALS[st.official] || st.official), function () { state.official = ""; state.vote = ""; })); }
    if (st.vote) { chipsEl.appendChild(chip("Voted: " + VOTE[st.vote], function () { state.vote = ""; })); }
    st.outcome.forEach(function (o) { chipsEl.appendChild(chip("Outcome: " + OUTCOME[o], function () { state.outcome = state.outcome.filter(function (x) { return x !== o; }); })); });
    var n = st.kind.length + st.type.length + st.outcome.length + st.body.length + (st.from || st.to ? 1 : 0) + (st.official ? 1 : 0) + (st.vote ? 1 : 0);
    document.getElementById("filter-count").textContent = n ? "(" + n + ")" : "";
  }

  var state = readURL();
  function empty(st) {
    return !st.q && !st.kind.length && !st.type.length && !st.outcome.length && !st.body.length && !st.from && !st.to && !st.official;
  }
  function update(keepPage) {
    state = fromControls();
    writeURL(state);
    state.pref = chosenBody();
    bodyLine(state);
    form.querySelectorAll('input[name="vote"]').forEach(function (el) { el.disabled = !state.official; });
    renderChips(state);
    if (!keepPage) { shown = PAGE; }
    results.setAttribute("aria-busy", "false");
    if (empty(state)) {
      noteEl.hidden = true;
      countEl.textContent = "";
      results.innerHTML = document.getElementById("help").innerHTML;
      moreBtn.hidden = true;
      return;
    }
    var toks = tokens(state.q), hits = [], left = 0, strict = confirmedOnly(state);
    IX.records.forEach(function (r) {
      if (!baseMatch(r, state, toks)) { return; }
      if (strict && r.k === "vote" && !r.c) { left++; return; }
      if (strict && !confirmedMatch(r, state)) { return; }
      hits.push(r);
    });
    if (strict) {
      noteEl.hidden = false;
      noteEl.innerHTML = "Filtering by official, vote or outcome uses confirmed roll calls only. " + left +
        (left === 1 ? " roll call that matches the other filters is not confirmed and is left out. "
          : " roll calls that match the other filters are not confirmed and are left out. ") +
        '<a href="#" id="drop-strict">Show them without the official, vote and outcome filters</a>';
      document.getElementById("drop-strict").addEventListener("click", function (e) {
        e.preventDefault();
        state.official = ""; state.vote = ""; state.outcome = [];
        toControls(state); update();
      });
    } else {
      noteEl.hidden = true;
    }
    if (state.order === "new" || state.order === "old") {  // by date only, never by a count
      var dir = state.order === "new" ? -1 : 1;
      hits.sort(function (a, b) { return a.d === b.d ? 0 : (a.d < b.d ? -dir : dir); });
    } else if (toks.length) {
      hits.forEach(function (r) { r._s = score(r, toks); });
      hits.sort(function (a, b) { return b._s - a._s || (a.d < b.d ? 1 : a.d > b.d ? -1 : 0); });
    }
    countEl.textContent = hits.length + (hits.length === 1 ? " result" : " results");
    if (!hits.length) {
      results.innerHTML = "<p>No records match. Try fewer filters or a different spelling.</p>";
      moreBtn.hidden = true;
      return;
    }
    var before = results.querySelectorAll("li.result").length;
    results.innerHTML = '<ol class="result-list">' + hits.slice(0, shown).map(function (r) { return row(r, state, toks); }).join("") + "</ol>";
    moreBtn.hidden = hits.length <= shown;
    if (keepPage) {  // "Show more" keeps focus on the first new result
      var first = results.querySelectorAll("li.result a")[before];
      if (first) { first.focus(); }
    }
  }

  toControls(state);
  form.addEventListener("submit", function (e) { e.preventDefault(); update(); });
  form.addEventListener("change", function (e) { if (e.target.id !== "q") { update(); } });
  form.q.addEventListener("input", function () { update(); });
  moreBtn.addEventListener("click", function () { shown += PAGE; update(true); });
  document.getElementById("clear").addEventListener("click", function () {
    var q = form.q.value;
    state = readURL();
    SINGLE.forEach(function (k) { state[k] = ""; });
    MULTI.forEach(function (k) { state[k] = []; });
    state.q = q;
    toControls(state); update();
  });
  document.getElementById("apply").addEventListener("click", function () {
    if (!window.matchMedia("(min-width: 900px)").matches) { panel.open = false; }
    countEl.focus();
  });
  document.getElementById("copy").addEventListener("click", function () {
    var done = function () { document.getElementById("copied").textContent = "Link copied."; };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(location.href).then(done, function () {
        document.getElementById("copied").textContent = "Copy this address: " + location.href;
      });
    } else {
      document.getElementById("copied").textContent = "Copy this address: " + location.href;
    }
  });
  document.addEventListener("bodychoice", function () { update(); });
  // A click in the "Show records from" switch decides: the Body boxes (and the URL's body) are cleared, and the
  // bodychoice event that follows updates the results. Ticking a box later decides again, as before.
  document.addEventListener("bodypick", function () {
    form.querySelectorAll('input[name="body"]').forEach(function (el) { el.checked = false; });
  });
  update();
})();
