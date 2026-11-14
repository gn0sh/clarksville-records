/* Landing sky (docs/design/daylight, M1). Puts the sun where the viewer's own clock says it is: rising from the
   horizon at 6 AM, highest at half past noon, down at 7 PM, below the horizon at night (a rough day, not an
   almanac). Shows today's weekday and date in the site's zone. No network calls, no storage, nothing sent.
   Without this script the sun stays at its CSS midday place and the date line stays hidden.
   The moon (owner, 2026-11-14) is different: it is drawn where it really is at this instant over the site's place
   (data-lat and data-lon on #sky-moon, from config sky_place): altitude, compass direction, phase and the tilt of
   its bright edge, from a small almanac worked out below. Without this script there is no moon. Hidden while the
   moon is below the horizon.
   Exposes CRSky.altitude, render and the moon's pure functions for tests (module.exports under node). */
(function (root) {
  "use strict";
  var RISE = 6, SET = 19, NIGHT = -0.25;

  /* Hours since midnight (0 to 24) -> altitude: 0 on the horizon, 1 at the top of the arc, NIGHT below it. */
  function altitude(hours) {
    if (typeof hours !== "number" || !isFinite(hours) || hours <= RISE || hours >= SET) { return NIGHT; }
    return Math.round(Math.sin((hours - RISE) / (SET - RISE) * Math.PI) * 1000) / 1000;
  }


  /* ---- The moon over the site's place ----------------------------------------------------------------------
     A low-precision almanac: the Astronomical Almanac's short series for the sun and the moon (the same family as
     Meeus ch. 25 and 47, cut to the largest terms). Checked against PyEphem in tests/test_moon.py: under 0.5
     degrees in altitude and direction and under 1% in the lit fraction through 2026. All angles in degrees. */
  var RAD = Math.PI / 180;
  function sin(a) { return Math.sin(a * RAD); }
  function cos(a) { return Math.cos(a * RAD); }
  function atan2(y, x) { return Math.atan2(y, x) / RAD; }
  function asin(x) { return Math.asin(Math.max(-1, Math.min(1, x))) / RAD; }
  function turn(a) { return ((a % 360) + 360) % 360; }                    /* into 0..360 */
  function half(a) { return turn(a + 180) - 180; }                        /* into -180..180 */

  /* Days since 2000-01-01 12:00 UTC (J2000.0) for a Date.now() value. UTC stands in for dynamical time: the 70
     seconds between them move the moon by 0.01 degrees. */
  function j2000(ms) { return ms / 86400000 - 10957.5; }

  /* Ecliptic longitude and latitude -> right ascension and declination, by the tilt of the Earth's axis. */
  function equatorial(lon, lat, d) {
    var e = 23.4393 - 3.56e-7 * d;
    return { ra: turn(atan2(sin(lon) * cos(e) - Math.tan(lat * RAD) * sin(e), cos(lon))),
             dec: asin(sin(lat) * cos(e) + cos(lat) * sin(e) * sin(lon)) };
  }

  /* The sun: ecliptic longitude, distance in Earth radii, right ascension and declination. */
  function sunPosition(ms) {
    var d = j2000(ms), g = 357.528 + 0.9856003 * d;                         /* mean anomaly */
    var lon = turn(280.460 + 0.9856474 * d + 1.915 * sin(g) + 0.020 * sin(2 * g));
    var eq = equatorial(lon, 0, d);
    return { lon: lon, dist: (1.00014 - 0.01671 * cos(g) - 0.00014 * cos(2 * g)) * 23455, ra: eq.ra, dec: eq.dec };
  }

  /* The moon seen from the Earth's centre: ecliptic longitude and latitude, horizontal parallax (how far an
     observer's place on the globe shifts it), distance in Earth radii, right ascension and declination. */
  function moonPosition(ms) {
    var d = j2000(ms), T = d / 36525;
    var a = 135.0 + 477198.87 * T, b = 259.3 - 413335.36 * T, c = 235.7 + 890534.22 * T, e = 269.9 + 954397.74 * T;
    var lon = turn(218.32 + 481267.881 * T + 6.29 * sin(a) - 1.27 * sin(b) + 0.66 * sin(c) + 0.21 * sin(e)
      - 0.19 * sin(357.5 + 35999.05 * T) - 0.11 * sin(186.5 + 966404.03 * T));
    var lat = 5.13 * sin(93.3 + 483202.02 * T) + 0.28 * sin(228.2 + 960400.89 * T)
      - 0.28 * sin(318.3 + 6003.15 * T) - 0.17 * sin(217.6 - 407332.21 * T);
    var par = 0.9508 + 0.0518 * cos(a) + 0.0095 * cos(b) + 0.0078 * cos(c) + 0.0028 * cos(e);
    var eq = equatorial(lon, lat, d);
    return { lon: lon, lat: lat, par: par, dist: 1 / sin(par), ra: eq.ra, dec: eq.dec };
  }

  /* The moon from a place on the ground (lat degrees north, lon degrees east) at an instant (a Date.now() value):
       alt       degrees above the horizon, from the ground (parallax taken off; no bending by the air)
       az        compass direction, degrees clockwise from north (90 east, 180 south, 270 west)
       fraction  share of the disc that is lit, 0 (new) to 1 (full)
       waxing    true from new to full
       limb      which way the middle of the bright edge points on the sky: degrees clockwise from straight up, as
                 the viewer sees it facing the moon (90 = lit on the right, -90 = lit on the left) */
  function moon(ms, lat, lon) {
    var d = j2000(ms), m = moonPosition(ms), s = sunPosition(ms);
    var H = turn(280.46061837 + 360.98564736629 * d + lon) - m.ra;        /* hour angle: sidereal time minus RA */
    var alt = asin(sin(lat) * sin(m.dec) + cos(lat) * cos(m.dec) * cos(H));
    var az = turn(atan2(sin(H), cos(H) * sin(lat) - Math.tan(m.dec * RAD) * cos(lat)) + 180);
    alt -= m.par * cos(alt);                                              /* seen from the surface, not the centre */
    /* phase: the angle sun-moon-Earth, from the sun-Earth-moon angle and the two distances */
    var elong = Math.acos(Math.max(-1, Math.min(1, cos(m.lat) * cos(m.lon - s.lon)))) / RAD;
    var phase = atan2(s.dist * sin(elong), m.dist - s.dist * cos(elong));
    /* bright edge: its direction from celestial north (toward east), less the tilt of north against straight up */
    var chi = atan2(cos(s.dec) * sin(s.ra - m.ra),
                    sin(s.dec) * cos(m.dec) - cos(s.dec) * sin(m.dec) * cos(s.ra - m.ra));
    var q = atan2(sin(H), Math.tan(lat * RAD) * cos(m.dec) - sin(m.dec) * cos(H));
    return { alt: alt, az: az, fraction: (1 + cos(phase)) / 2, waxing: half(m.lon - s.lon) > 0, limb: half(q - chi) };
  }

  /* Where the moon sits across the sky band, 0 (left) to 1 (right): east on the left, south in the middle, west on
     the right, as for someone facing south. Rising and setting points north of east and west are kept on the band. */
  var AZ_LEFT = 60, AZ_RIGHT = 300;
  function moonX(az) {
    return Math.round(Math.max(0, Math.min(1, (az - AZ_LEFT) / (AZ_RIGHT - AZ_LEFT))) * 1000) / 1000;
  }

  /* The lit part of a disc of radius r about (0, 0), bright edge on the right, as an SVG path: the right half of the
     circle, closed by the terminator, which is half an ellipse (the lit/dark line seen at an angle). */
  function moonPath(fraction, r) {
    r = r || 10;
    var k = Math.max(0, Math.min(1, fraction)), rx = Math.round(Math.abs(1 - 2 * k) * r * 100) / 100;
    return "M0 " + (-r) + "A" + r + " " + r + " 0 0 1 0 " + r + "A" + rx + " " + r + " 0 0 " + (k > 0.5 ? 1 : 0) + " 0 " + (-r) + "Z";
  }

  /* The moon's drawing inside #sky-moon, made once: a faint outline of the whole disc and the lit part over it. */
  var SVG = "http://www.w3.org/2000/svg";
  function moonDrawing(doc, el) {
    var lit = doc.getElementById("sky-moon-lit");
    if (lit) { return lit; }
    var svg = doc.createElementNS(SVG, "svg"), disc = doc.createElementNS(SVG, "circle");
    lit = doc.createElementNS(SVG, "path");
    svg.setAttribute("viewBox", "-12 -12 24 24"); svg.setAttribute("focusable", "false");
    disc.setAttribute("class", "moon-disc"); disc.setAttribute("r", "10");
    lit.setAttribute("class", "moon-lit"); lit.setAttribute("id", "sky-moon-lit");
    svg.appendChild(disc); svg.appendChild(lit); el.appendChild(svg);
    return lit;
  }

  /* Draws the moon for this instant: its place (--moon-x, --moon-alt), its lit shape and its tilt. `sunUp`: the drawn
     sun is in the sky, so the moon is paler. Below the horizon, with no place on the page, or on any error, the
     moon stays hidden. */
  function renderMoon(doc, ms, sunUp) {
    var el = doc.getElementById("sky-moon");
    if (!el) { return; }
    var lat = parseFloat(el.getAttribute("data-lat")), lon = parseFloat(el.getAttribute("data-lon"));
    var m = isFinite(lat) && isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? moon(ms, lat, lon) : null;
    if (!m || !(m.alt > 0) || !isFinite(m.az + m.fraction + m.limb)) { el.setAttribute("hidden", ""); return; }
    var lit = moonDrawing(doc, el);
    el.style.setProperty("--moon-x", String(moonX(m.az)));
    el.style.setProperty("--moon-alt", String(Math.round(m.alt / 90 * 1000) / 1000));
    lit.setAttribute("d", moonPath(m.fraction));
    lit.setAttribute("transform", "rotate(" + Math.round(m.limb - 90) + ")");
    if (sunUp) { el.setAttribute("data-day", ""); } else { el.removeAttribute("data-day"); }
    el.removeAttribute("hidden");
  }

  /* Today's weekday and date in the site's zone (data-tz on the hero), so the "<weekday> in <place> <date>" line is true
     for every viewer. The sun stays on the viewer's own clock. */
  function render() {
    var doc = root.document || (typeof document !== "undefined" ? document : null);
    if (!doc) { return; }
    var now = new Date();
    var sun = doc.getElementById("sky-sun");
    var sunAlt = altitude(now.getHours() + now.getMinutes() / 60);
    if (sun) { sun.style.setProperty("--sun-alt", String(sunAlt)); }
    try { renderMoon(doc, now.getTime(), sunAlt > 0); } catch (e) { /* no moon */ }
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
  /* the moon alone, for the timer: the sun and the date line keep to page load and pageshow */
  function tick() {
    var doc = root.document, now = new Date();
    if (!doc || doc.hidden) { return; }
    try { renderMoon(doc, now.getTime(), altitude(now.getHours() + now.getMinutes() / 60) > 0); } catch (e) { /* no moon */ }
  }
  var api = { altitude: altitude, render: render, RISE: RISE, SET: SET, NIGHT: NIGHT,
              moon: moon, moonPosition: moonPosition, sunPosition: sunPosition, moonX: moonX, moonPath: moonPath,
              renderMoon: renderMoon };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  root.CRSky = api;
  render();
  /* a page restored from the back/forward cache gets a fresh date and sun */
  if (root.addEventListener) { root.addEventListener("pageshow", function (ev) { if (ev && ev.persisted) { render(); } }); }
  /* the moon moves about a degree every four minutes, so it is redrawn every five while the page is open */
  if (root.setInterval && root.document && root.document.getElementById("sky-moon")) { root.setInterval(tick, 300000); }
}(typeof window !== "undefined" ? window : this));
