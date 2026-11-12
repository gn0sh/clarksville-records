/* Morning note (Daylight M3, docs/architecture/morning-note.md), on the Alerts page's #note section and the preview
   page (morning/index.html). Everything happens on this device: the seats come from static/seats.js (CRSeats, the
   one "cr-your-seats" key it keeps), the picked lists from the checkboxes and the preview page's own #lists= fragment.
   This script makes no network call, stores nothing new, and never submits or claims to have sent anything.
   The enabled sign-up form (a later decision) posts the stored seats only while its visible "include my saved
   seats" box is ticked: seatPost() decides the two fields, seatWords() the numbers printed beside the box.
   select() mirrors sitegen/morning.py select(): an entry is kept when one of its lists is picked and, for "zoning",
   its printed district or ward equals a stored seat, for "seats", the stored seat its seat_body names is set (the
   county's documents need a district, a council's a ward). tests/test_morning_page.py runs both over the same
   fixture.
   Exposes CRMorning (module.exports under node). */
(function (root) {
  "use strict";

  function num(v) { return typeof v === "number" && isFinite(v) && Math.floor(v) === v ? v : null; }

  /* An entry's seat_body ("district": the county's, "ward": a council's; anything else: no seat) names which stored
     seat a "seats" entry needs, as sitegen/morning.py _seat_match decides it. */
  function seatMatch(entry, key, seats) {
    var d = seats ? num(seats.district) : null, w = seats ? num(seats.ward) : null;
    if (key === "zoning") {
      return (d !== null && num(entry.district) === d) || (w !== null && num(entry.ward) === w);
    }
    if (key === "seats") {
      return (entry.seat_body === "district" && d !== null) || (entry.seat_body === "ward" && w !== null);
    }
    return true;
  }

  function matches(entry, lists, seats) {
    var own = entry.lists || [];
    for (var i = 0; i < own.length; i++) {
      if (lists.indexOf(own[i]) >= 0 && seatMatch(entry, own[i], seats)) { return true; }
    }
    return false;
  }

  function select(day, lists, seats) {
    return (day.entries || []).filter(function (e) { return matches(e, lists || [], seats); });
  }

  /* "#lists=zoning,budget" -> ["zoning", "budget"] (known keys only, in the given order), or null when absent. */
  function parseLists(hash, keys) {
    var m = /^#?lists=([a-z0-9,_-]*)$/.exec(hash || "");
    if (!m) { return null; }
    var picked = m[1].split(",");
    return keys.filter(function (k) { return picked.indexOf(k) >= 0; });
  }

  /* The enabled form's two seat fields: each stored seat as text, or null (the field stays disabled and empty, so it
     is not posted). Nothing unless `include` is exactly true: the visible box is there and ticked. */
  function seatPost(seats, include) {
    var d = seats && include === true ? num(seats.district) : null;
    var w = seats && include === true ? num(seats.ward) : null;
    return { district: d === null ? null : String(d), ward: w === null ? null : String(w) };
  }

  /* The stored seats as the form prints them beside the box: "District 5, Ward 3", or "" when none is stored. */
  function seatWords(seats, labels) {
    var d = seats ? num(seats.district) : null, w = seats ? num(seats.ward) : null, out = [];
    if (d !== null) { out.push(labels.district + " " + d); }
    if (w !== null) { out.push(labels.ward + " " + w); }
    return out.join(", ");
  }

  var api = { select: select, matches: matches, parseLists: parseLists, seatPost: seatPost, seatWords: seatWords };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  root.CRMorning = api;

  var doc = root.document;
  if (!doc) { return; }
  var seats = root.CRSeats ? root.CRSeats.read() : null;

  function boxes(scope) { return Array.prototype.slice.call(scope.querySelectorAll(".mn-picker input[type=checkbox]")); }
  function picked(scope) { return boxes(scope).filter(function (b) { return b.checked; }).map(function (b) { return b.value; }); }
  function each(scope, sel, fn) { Array.prototype.forEach.call(scope.querySelectorAll(sel), fn); }
  function showPicker(scope) { var f = scope.querySelector(".mn-picker"); if (f) { f.hidden = false; } }

  /* Alerts page: the picked lists' feeds, the per-seat feed for the stored seats, and the preview link's picks. */
  var note = doc.getElementById("note");
  if (note) {
    showPicker(note);
    var seatsBox = doc.getElementById("note-seats"), seatsRow = doc.getElementById("mn-seats");
    var updateNote = function () {
      var lists = picked(note);
      each(note, ".mn-lists > li[data-list]", function (li) {
        li.hidden = lists.indexOf(li.getAttribute("data-list")) < 0;
        var seatShown = false;
        each(li, "li[data-seat]", function (f) {
          var seat = f.getAttribute("data-seat"), n = f.getAttribute("data-number");
          var mine = seats ? num(seats[seat]) : null;
          if (n !== null) { f.hidden = mine === null || mine !== Number(n); seatShown = seatShown || !f.hidden; }
          else { f.hidden = seats !== null && mine === null; }
        });
        each(li, "li[data-fallback]", function (f) { f.hidden = seatShown; });
        each(li, "[data-hint=seats]", function (h) { h.hidden = seats !== null; });
      });
      var link = doc.getElementById("mn-preview");
      var base = note.getAttribute("data-preview");
      if (link && base) { link.setAttribute("href", base + "#lists=" + lists.join(",")); }
      // The enabled form only: the stored seats, shown beside a visible box and posted only while it is ticked.
      var words = doc.getElementById("mn-seats-values");
      var said = words ? seatWords(seats, { district: words.getAttribute("data-district-label") || "",
                                            ward: words.getAttribute("data-ward-label") || "" }) : "";
      if (words) { words.textContent = said; }
      if (seatsRow) { seatsRow.hidden = said === ""; }
      var post = seatPost(seats, !!seatsBox && !!seatsRow && said !== "" && seatsBox.checked);
      each(note, "input[data-seat-field]", function (inp) {
        var v = post[inp.getAttribute("data-seat-field")];
        v = typeof v === "string" ? v : null;
        inp.value = v === null ? "" : v;
        inp.disabled = v === null;
      });
    };
    boxes(note).forEach(function (b) { b.addEventListener("change", updateNote); });
    if (seatsBox) { seatsBox.addEventListener("change", updateNote); }
    /* A browser can restore the form's state (reload, back or forward) after this script ran, without a "change"
       event: recompute when the page is shown and again at submit, so the seat fields follow the box as it stands
       (seat-consent/state-recompute-on-submit). */
    note.addEventListener("submit", updateNote);
    root.addEventListener("pageshow", updateNote);
    updateNote();
  }

  /* Preview page: today's entries for the picked lists and the stored seats. */
  var page = doc.getElementById("mn-day");
  if (page) {
    var keys = boxes(page).map(function (b) { return b.value; });
    showPicker(page);
    each(page, ".mn-mine", function (p) { p.hidden = false; });
    var entryOf = function (li) {
      var d = li.getAttribute("data-district"), w = li.getAttribute("data-ward");
      return { lists: (li.getAttribute("data-lists") || "").split(" ").filter(Boolean),
               seat_body: li.getAttribute("data-seat-body"),
               district: d === null ? null : Number(d), ward: w === null ? null : Number(w) };
    };
    var show = function (lists) {
      boxes(page).forEach(function (b) { b.checked = lists.indexOf(b.value) >= 0; });
      var shown = 0;
      each(page, ".mn-entry", function (li) {
        li.hidden = li.hasAttribute("data-unplaced") ? lists.indexOf("zoning") < 0
          : !matches(entryOf(li), lists, seats);
        if (!li.hidden && !li.hasAttribute("data-unplaced")) { shown++; }
      });
      each(page, ".mn-quiet", function (p) { p.hidden = shown > 0; });
      each(page, "[data-hint=seats]", function (h) {
        h.hidden = seats !== null || (lists.indexOf("zoning") < 0 && lists.indexOf("seats") < 0);
      });
    };
    var fromHash = function () { var l = parseLists(root.location.hash, keys); show(l === null ? keys : l); };
    boxes(page).forEach(function (b) {
      b.addEventListener("change", function () {
        var lists = picked(page);
        try { root.history.replaceState(null, "", "#lists=" + lists.join(",")); } catch (e) { /* file:// may refuse */ }
        show(lists);
      });
    });
    root.addEventListener("hashchange", fromHash);
    fromHash();
  }
})(typeof window !== "undefined" ? window : this);
