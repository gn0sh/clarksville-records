/* Landing sky (docs/design/daylight, M1). Puts the sun where the viewer's own clock says it is: rising from the
   horizon at 6 AM, highest at half past noon, down at 7 PM, below the horizon at night (a rough day, not an
   almanac). Shows today's weekday and date from the same clock. No network calls, no storage, nothing sent.
   Without this script the sun stays at its CSS midday place and the date line stays hidden.
   Exposes CRSky.altitude for tests (module.exports under node). */
(function (root) {
  "use strict";
  var RISE = 6, SET = 19, NIGHT = -0.25;

  /* Hours since midnight (0 to 24) -> altitude: 0 on the horizon, 1 at the top of the arc, NIGHT below it. */
  function altitude(hours) {
    if (typeof hours !== "number" || !isFinite(hours) || hours <= RISE || hours >= SET) { return NIGHT; }
    return Math.round(Math.sin((hours - RISE) / (SET - RISE) * Math.PI) * 1000) / 1000;
  }

  function pad(n) { return n < 10 ? "0" + n : String(n); }

  var api = { altitude: altitude, RISE: RISE, SET: SET, NIGHT: NIGHT };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  root.CRSky = api;

  var doc = root.document;
  var now = new Date();
  var sun = doc.getElementById("sky-sun");
  if (sun) { sun.style.setProperty("--sun-alt", String(altitude(now.getHours() + now.getMinutes() / 60))); }

  var hero = doc.getElementById("sky-hero");
  var weekday = doc.getElementById("sky-weekday");
  var date = doc.getElementById("sky-date");
  if (!hero || !weekday || !date) { return; }
  try {
    weekday.textContent = now.toLocaleDateString("en-US", { weekday: "long" });
    date.textContent = now.toLocaleDateString("en-US", { month: "long", day: "numeric" });
  } catch (e) { return; }
  date.setAttribute("datetime", now.getFullYear() + "-" + pad(now.getMonth() + 1) + "-" + pad(now.getDate()));
  hero.hidden = false;
}(typeof window !== "undefined" ? window : this));
