/* Landing sky (docs/design/daylight, M1). Puts the sun where the viewer's own clock says it is: rising from the
   horizon at 6 AM, highest at half past noon, down at 7 PM, below the horizon at night (a rough day, not an
   almanac). Shows today's weekday and date in the site's zone. No network calls, no storage, nothing sent.
   Without this script the sun stays at its CSS midday place and the date line stays hidden.
   Exposes CRSky.altitude and render for tests (module.exports under node). */
(function (root) {
  "use strict";
  var RISE = 6, SET = 19, NIGHT = -0.25;

  /* Hours since midnight (0 to 24) -> altitude: 0 on the horizon, 1 at the top of the arc, NIGHT below it. */
  function altitude(hours) {
    if (typeof hours !== "number" || !isFinite(hours) || hours <= RISE || hours >= SET) { return NIGHT; }
    return Math.round(Math.sin((hours - RISE) / (SET - RISE) * Math.PI) * 1000) / 1000;
  }


  /* Today's weekday and date in the site's zone (data-tz on the hero), so "<weekday> in Clarksville <date>" is true
     for every viewer. The sun stays on the viewer's own clock. */
  function render() {
    var doc = root.document || (typeof document !== "undefined" ? document : null);
    if (!doc) { return; }
    var now = new Date();
    var sun = doc.getElementById("sky-sun");
    if (sun) { sun.style.setProperty("--sun-alt", String(altitude(now.getHours() + now.getMinutes() / 60))); }
    var hero = doc.getElementById("sky-hero");
    var weekday = doc.getElementById("sky-weekday");
    var date = doc.getElementById("sky-date");
    if (!hero || !weekday || !date) { return; }
    var tz = hero.getAttribute("data-tz") || undefined;
    try {
      var iso = new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
      weekday.textContent = now.toLocaleDateString("en-US", { weekday: "long", timeZone: tz });
      date.textContent = now.toLocaleDateString("en-US", { month: "long", day: "numeric", timeZone: tz });
      date.setAttribute("datetime", iso);
    } catch (e) { return; }
    hero.hidden = false;
  }
  var api = { altitude: altitude, render: render, RISE: RISE, SET: SET, NIGHT: NIGHT };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  root.CRSky = api;
  render();
  /* a page restored from the back/forward cache gets a fresh date and sun */
  if (root.addEventListener) { root.addEventListener("pageshow", function (ev) { if (ev && ev.persisted) { render(); } }); }
}(typeof window !== "undefined" ? window : this));
