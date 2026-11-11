/* Landing meetings list (docs/design/front-page-v2.md section 4, state "Data stale"). The list is fixed when the site
   is built and says so ("As of <build date>"). When the page is read on a later day (today in the site's zone, as on
   the sky line), a "Coming up" row whose day has passed moves to the top of "Most recent", which keeps its length; if
   the build is more than two days old a line says when it was built. No network calls, no storage, nothing sent.
   Without this script the list stays as built, which its "As of" line already says.
   Exposes CRLanding.split and daysBetween for tests (module.exports under node). */
(function (root) {
  "use strict";
  var STALE_DAYS = 2;

  /* Whole days from ISO date a to ISO date b (b - a). */
  function daysBetween(a, b) {
    var pa = String(a).split("-"), pb = String(b).split("-");
    var ta = Date.UTC(+pa[0], +pa[1] - 1, +pa[2]), tb = Date.UTC(+pb[0], +pb[1] - 1, +pb[2]);
    return Math.round((tb - ta) / 86400000);
  }

  /* upcoming: ISO dates soonest first; recent: newest first. -> {upcoming, recent} with every upcoming date before
     `today` moved to the front of recent (newest first), recent cut to n. Indexes into the inputs, so the caller
     moves the same rows. */
  function split(upcoming, recent, today, n) {
    var keep = [], moved = [];
    for (var i = 0; i < upcoming.length; i++) {
      if (upcoming[i] < today) { moved.unshift(i); } else { keep.push(i); }
    }
    var rec = moved.map(function (i) { return { from: "up", i: i }; })
      .concat(recent.map(function (_, i) { return { from: "recent", i: i }; }));
    return { upcoming: keep, recent: rec.slice(0, n) };
  }

  function todayIn(tz) {
    return new Intl.DateTimeFormat("en-CA", { timeZone: tz || undefined, year: "numeric", month: "2-digit", day: "2-digit" })
      .format(new Date());
  }

  function render() {
    var doc = root.document || (typeof document !== "undefined" ? document : null);
    if (!doc) { return; }
    var sec = doc.getElementById("meetings");
    var up = doc.getElementById("meet-up"), rec = doc.getElementById("meet-recent");
    if (!sec) { return; }
    var built = sec.getAttribute("data-built");
    var today;
    try { today = todayIn(sec.getAttribute("data-tz")); } catch (e) { return; }
    if (!built || !(today > built)) { return; }
    var stale = doc.getElementById("meet-stale");
    if (stale && daysBetween(built, today) > STALE_DAYS) { stale.hidden = false; }
    if (!up || !rec) { return; }
    var n = parseInt(sec.getAttribute("data-n"), 10) || 3;
    var upRows = Array.prototype.slice.call(up.children), recRows = Array.prototype.slice.call(rec.children);
    var iso = function (li) { return li.getAttribute("data-iso") || ""; };
    var plan = split(upRows.map(iso), recRows.map(iso), today, n);
    var keepUp = plan.upcoming.map(function (i) { return upRows[i]; });
    var newRec = plan.recent.map(function (p) { return p.from === "up" ? upRows[p.i] : recRows[p.i]; });
    upRows.concat(recRows).forEach(function (li) { if (li.parentNode) { li.parentNode.removeChild(li); } });
    keepUp.forEach(function (li) { up.appendChild(li); });
    newRec.forEach(function (li) { rec.appendChild(li); });
    var upEmpty = doc.getElementById("meet-up-empty"), recEmpty = doc.getElementById("meet-recent-empty");
    if (upEmpty) { upEmpty.hidden = keepUp.length > 0; }
    if (recEmpty) { recEmpty.hidden = newRec.length > 0; }
  }

  var api = { split: split, daysBetween: daysBetween, render: render, STALE_DAYS: STALE_DAYS };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  root.CRLanding = api;
  render();
}(typeof window !== "undefined" ? window : this));
