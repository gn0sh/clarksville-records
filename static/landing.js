/* Landing meetings list (docs/design/front-page-v2.md section 4, state "Data stale"). The list is fixed when the site
   is built and says so ("As of <build date>"). When the page is read on a later day (today in the site's zone, as on
   the sky line), a "Coming up" row whose day has passed moves to the top of "Most recent", which keeps its length; if
   the build is more than two days old a line says when it was built. A spare upcoming row (built hidden) takes the
   place of each one that moved, and a moved row drops its "Scheduled" chip. No network calls, no storage, nothing sent.
   Without this script the list stays as built, which its "As of" line already says.
   Exposes CRLanding.split, daysBetween, todayIn and render for tests (module.exports under node). */
(function (root) {
  "use strict";
  var STALE_DAYS = 2;

  /* Whole days from ISO date a to ISO date b (b - a). */
  function daysBetween(a, b) {
    var pa = String(a).split("-"), pb = String(b).split("-");
    var ta = Date.UTC(+pa[0], +pa[1] - 1, +pa[2]), tb = Date.UTC(+pb[0], +pb[1] - 1, +pb[2]);
    return Math.round((tb - ta) / 86400000);
  }

  /* upcoming: ISO dates soonest first (the shown rows, then the spare hidden ones); recent: newest first.
     -> {upcoming, recent}: the indexes of the upcoming rows to show (not passed, the first n), and the rows of
     "Most recent": every upcoming row before `today` (newest first), then the built recent ones, cut to n. */
  function split(upcoming, recent, today, n) {
    var keep = [], moved = [];
    for (var i = 0; i < upcoming.length; i++) {
      if (upcoming[i] < today) { moved.unshift(i); } else { keep.push(i); }
    }
    var rec = moved.map(function (i) { return { from: "up", i: i }; })
      .concat(recent.map(function (_, i) { return { from: "recent", i: i }; }));
    return { upcoming: keep.slice(0, n), recent: rec.slice(0, n) };
  }

  /* Today in the site's zone as YYYY-MM-DD, built from its parts (not from a locale's own date format). */
  function todayIn(tz, now) {
    var parts = {};
    new Intl.DateTimeFormat("en-US", { timeZone: tz || undefined, year: "numeric", month: "2-digit", day: "2-digit" })
      .formatToParts(now || new Date()).forEach(function (p) { parts[p.type] = p.value; });
    return parts.year + "-" + parts.month + "-" + parts.day;
  }

  function render(now) {
    var doc = root.document || (typeof document !== "undefined" ? document : null);
    if (!doc) { return; }
    var sec = doc.getElementById("meetings");
    var up = doc.getElementById("meet-up"), rec = doc.getElementById("meet-recent");
    if (!sec) { return; }
    var built = sec.getAttribute("data-built");
    var today;
    try { today = todayIn(sec.getAttribute("data-tz"), now); } catch (e) { return; }
    if (!built || !(today > built)) { return; }
    var stale = doc.getElementById("meet-stale");
    if (stale && daysBetween(built, today) > STALE_DAYS) { stale.hidden = false; }
    if (!up || !rec) { return; }
    var n = parseInt(sec.getAttribute("data-n"), 10) || 3;
    var upRows = Array.prototype.slice.call(up.children), recRows = Array.prototype.slice.call(rec.children);
    var iso = function (li) { return li.getAttribute("data-iso") || ""; };
    var plan = split(upRows.map(iso), recRows.map(iso), today, n);
    var show = plan.upcoming.map(function (i) { return upRows[i]; });
    var newRec = plan.recent.map(function (p) {
      var li = p.from === "up" ? upRows[p.i] : recRows[p.i];
      if (p.from === "up") {
        /* its day has passed: "Scheduled" said it was ahead, and whether it met is not in these records */
        var chip = li.querySelector('[data-chip="Scheduled"]');
        if (chip && chip.parentNode) { chip.parentNode.removeChild(chip); }
      }
      return li;
    });
    upRows.concat(recRows).forEach(function (li) { if (li.parentNode) { li.parentNode.removeChild(li); } });
    upRows.forEach(function (li) {   /* the rows not passed stay in order; the first n are shown, the rest spare */
      if (newRec.indexOf(li) < 0 && iso(li) >= today) { li.hidden = show.indexOf(li) < 0; up.appendChild(li); }
    });
    newRec.forEach(function (li) { li.hidden = false; rec.appendChild(li); });
    up.hidden = show.length === 0;
    rec.hidden = newRec.length === 0;
    var upEmpty = doc.getElementById("meet-up-empty"), recEmpty = doc.getElementById("meet-recent-empty");
    if (upEmpty) { upEmpty.hidden = show.length > 0; }
    if (recEmpty) { recEmpty.hidden = newRec.length > 0; }
  }

  var api = { split: split, daysBetween: daysBetween, todayIn: todayIn, render: render, STALE_DAYS: STALE_DAYS };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  root.CRLanding = api;
  render();
}(typeof window !== "undefined" ? window : this));
