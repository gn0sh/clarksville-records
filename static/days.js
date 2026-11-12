/* Day by day (docs/design/daylight, M2; sitegen/days.py). Shows the week strip and one day at a time. Today is taken
   in the site's zone (data-tz on #days), the same zone the build used to choose its weeks. A #d-<date> in the address
   opens that day; a pick updates it (replaceState, no new history entry). No network calls, no storage, nothing sent.
   Without this script the page is a plain list of the days that have records.
   Exposes CRDays.isoInZone, pick and clamp for tests (module.exports under node). */
(function (root) {
  "use strict";

  /* YYYY-MM-DD of `now` in zone `tz`; the viewer's own zone when the browser does not know it. */
  function isoInZone(now, tz) {
    try {
      return new Intl.DateTimeFormat("en-CA", { timeZone: tz || undefined, year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
    } catch (e) {
      var m = now.getMonth() + 1, d = now.getDate();
      return now.getFullYear() + "-" + (m < 10 ? "0" : "") + m + "-" + (d < 10 ? "0" : "") + d;
    }
  }

  function clamp(iso, start, end) { return iso < start ? start : (iso > end ? end : iso); }

  /* The day to open: the address's #d-<date> when the page has it, else today, held inside the page's weeks. */
  function pick(hash, today, start, end, has) {
    var m = /^#d-(\d{4}-\d{2}-\d{2})$/.exec(hash || "");
    if (m && has(m[1])) { return m[1]; }
    return clamp(today, start, end);
  }

  function addDays(iso, n) {
    var p = iso.split("-"), d = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2] + n));
    return d.toISOString().slice(0, 10);
  }

  function init(doc) {
    var app = doc.getElementById("days");
    var strip = doc.getElementById("day-strip");
    if (!app || !strip) { return; }
    var tz = app.getAttribute("data-tz"), start = app.getAttribute("data-start"), end = app.getAttribute("data-end");
    var sheets = {}, buttons = {}, weekOf = {};
    Array.prototype.forEach.call(doc.querySelectorAll(".day-sheet"), function (s) { sheets[s.getAttribute("data-date")] = s; });
    var weeks = Array.prototype.slice.call(strip.querySelectorAll(".strip-week"));
    weeks.forEach(function (w, i) {
      Array.prototype.forEach.call(w.querySelectorAll("button.day"), function (b) {
        buttons[b.getAttribute("data-date")] = b;
        weekOf[b.getAttribute("data-date")] = i;
      });
    });
    var today = isoInZone(new Date(), tz);
    var status = doc.getElementById("day-status");
    var out = doc.getElementById("days-out");
    if (out) { out.hidden = !(today < start || today > end); }
    var current = null;

    Object.keys(sheets).forEach(function (iso) {
      var when = sheets[iso].querySelector(".day-when");
      if (when) {
        when.textContent = iso === today ? "Today" : (iso < today ? "Past" : "Coming up");
        when.removeAttribute("aria-hidden");
      }
      if (buttons[iso] && iso === today) {
        buttons[iso].classList.add("today");
        buttons[iso].setAttribute("aria-current", "date");
        buttons[iso].setAttribute("data-label-suffix", " (today)");   /* static/switch.js keeps it when it relabels */
        buttons[iso].setAttribute("aria-label", buttons[iso].getAttribute("aria-label") + " (today)");
      }
    });

    function show(iso, how) {
      if (!sheets[iso]) { return; }
      current = iso;
      Object.keys(sheets).forEach(function (k) { sheets[k].hidden = k !== iso; });
      Object.keys(buttons).forEach(function (k) {
        buttons[k].setAttribute("aria-pressed", String(k === iso));
        buttons[k].tabIndex = k === iso ? 0 : -1;
      });
      var wi = weekOf[iso];
      weeks.forEach(function (w, i) { w.hidden = i !== wi; });
      doc.getElementById("wk-prev").disabled = wi === 0;
      doc.getElementById("wk-next").disabled = wi === weeks.length - 1;
      if (how !== "load") {
        if (root.history && root.history.replaceState) { root.history.replaceState(null, "", "#d-" + iso); }
        var h = sheets[iso].querySelector("h2");
        if (status && h) { status.textContent = "Showing " + h.textContent + "."; }
        if (how === "key" || how === "step") { buttons[iso].focus(); }
      }
    }

    strip.addEventListener("click", function (ev) {
      var b = ev.target.closest ? ev.target.closest("button") : null;
      if (!b) { return; }
      if (b.id === "wk-prev" || b.id === "wk-next") {
        show(clamp(addDays(current, b.id === "wk-prev" ? -7 : 7), start, end), "step");
      } else if (b.getAttribute("data-date")) {
        show(b.getAttribute("data-date"), "click");
      }
    });
    /* arrow keys move a day, Home and End go to the week's ends (one tab stop for the whole strip) */
    strip.addEventListener("keydown", function (ev) {
      var b = ev.target;
      if (!b || !b.getAttribute || !b.getAttribute("data-date")) { return; }
      var iso = b.getAttribute("data-date"), next = null;
      if (ev.key === "ArrowRight") { next = addDays(iso, 1); }
      else if (ev.key === "ArrowLeft") { next = addDays(iso, -1); }
      else if (ev.key === "Home" || ev.key === "End") {
        var row = b.parentNode.querySelectorAll("button.day");
        next = row[ev.key === "Home" ? 0 : row.length - 1].getAttribute("data-date");
      }
      if (next && sheets[next]) { ev.preventDefault(); show(next, "key"); }
    });
    root.addEventListener("hashchange", function () {
      var iso = pick(root.location.hash, today, start, end, function (k) { return !!sheets[k]; });
      if (iso !== current) { show(iso, "hash"); }
    });

    app.classList.add("days-on");
    strip.hidden = false;
    show(pick(root.location.hash, today, start, end, function (k) { return !!sheets[k]; }), "load");
  }

  var api = { isoInZone: isoInZone, pick: pick, clamp: clamp, addDays: addDays };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  root.CRDays = api;
  if (root.document) { init(root.document); }
}(typeof window !== "undefined" ? window : this));
