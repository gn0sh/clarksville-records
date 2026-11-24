/* The sky in every page's header (docs/design/daylight). It draws the sky over the site's place (data-lat and
   data-lon on #sky-moon, from config sky_place) as it is at this instant, from a small almanac worked out below:
     the sun   while it is above that place's horizon: low at sunrise and sunset, at the top of its arc at local noon;
     the moon  only while the sun is down and the moon is up: its real height, compass direction, phase and the tilt
               of its bright edge, and only its lit part (no dark disc; a new moon is nothing).
   The two are never on the page together (owner, 2026-11-18): at night with no moon up the sky is empty.
   It also shows today's weekday and date in the site's zone.
   The weather: where the page names an address (data-weather on #sky-moon, from config sky_weather), the script asks
   it once per page view for that place's latest weather observation (the National Weather Service's, for one
   station) and draws one quiet scene over the sky: cloud, rain, snow, fog, wind or a thunderstorm. That request is
   the script's only network call. It carries no credentials, no referrer and nothing about the visitor or the page
   (the service sees what any web request from a page shows: the IP address, the browser and this site's address).
   Nothing is stored by the script; the browser may cache the answer as it does any page.
   An observation over 90 minutes old, an error or no answer in 5 seconds draws nothing: the plain sky. A page
   with no address asks nothing.
   A page with no place has no moon, and its sun follows the viewer's own clock (the rough day below).
   Without this script the sun stays at its CSS midday place, and the date line and the moon stay hidden.
   Exposes CRSky.altitude, sunAltitude, render, the moon's pure functions and the weather's (weatherScene, SCENES)
   for tests (module.exports under node). */
(function (root) {
  "use strict";
  var RISE = 6, SET = 19, NIGHT = -0.25;

  /* The rough day, for a page with no place: rising at 6 AM, highest at half past noon, down at 7 PM.
     Hours since midnight (0 to 24) -> altitude: 0 on the horizon, 1 at the top of the arc, NIGHT below it. */
  function altitude(hours) {
    if (typeof hours !== "number" || !isFinite(hours) || hours <= RISE || hours >= SET) { return NIGHT; }
    return Math.round(Math.sin((hours - RISE) / (SET - RISE) * Math.PI) * 1000) / 1000;
  }


  /* ---- The sun and the moon over the site's place -----------------------------------------------------------
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

  /* The sun from a place on the ground (lat degrees north, lon degrees east) at an instant (a Date.now() value):
       alt   degrees above the horizon (the disc's middle; no bending by the air)
       noon  its height at that day's local noon, the top of its arc */
  function sun(ms, lat, lon) {
    var d = j2000(ms), s = sunPosition(ms);
    var H = turn(280.46061837 + 360.98564736629 * d + lon) - s.ra;        /* hour angle: sidereal time minus RA */
    return { alt: asin(sin(lat) * sin(s.dec) + cos(lat) * cos(s.dec) * cos(H)), noon: 90 - Math.abs(lat - s.dec) };
  }

  /* The drawn sun's altitude over a place: NIGHT while the sun is down, else 0 (on the horizon) to 1 (local noon).
     Up means what an almanac's sunrise and sunset mean: the disc's top edge on the horizon, the air's bending
     included, which is its middle 0.833 degrees under it. */
  var SUN_UP = -0.833;
  function sunAltitude(ms, lat, lon) {
    var s = sun(ms, lat, lon);
    if (!(s.alt > SUN_UP)) { return NIGHT; }
    return Math.round(Math.max(0, Math.min(1, s.alt / Math.max(1, s.noon))) * 1000) / 1000;
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

  /* Where the moon sits across its stretch of sky, 0 (left) to 1 (right): east on the left, south in the middle, west
     on the right, as for someone facing south. Rising and setting points north of east and west are kept on it. */
  var AZ_LEFT = 60, AZ_RIGHT = 300;
  function moonX(az) {
    return Math.round(Math.max(0, Math.min(1, (az - AZ_LEFT) / (AZ_RIGHT - AZ_LEFT))) * 1000) / 1000;
  }

  /* The lit part of a disc of radius r about (0, 0), bright edge on the right, as an SVG path. Two edges that meet at
     the disc's two poles, (0, -r) and (0, r):
       the limb        the right half of the moon's own circle, radius r, whatever the phase;
       the terminator  the lit/dark line: half an ellipse through the same two poles, r high and r * |1 - 2k| wide
                       (r * |cos| of the phase angle). For a crescent it bows toward the limb (the half disc less
                       the half ellipse), past half it bows away from it (the half disc plus the half ellipse), and
                       at half it is a straight line from pole to pole, drawn as one.
     So the outer edge is always part of one circle, and the drawn area is the lit fraction of the disc. */
  function moonPath(fraction, r) {
    r = r || 10;
    var k = Math.max(0, Math.min(1, fraction)), rx = Math.round(Math.abs(1 - 2 * k) * r * 100) / 100;
    var limb = "M0 " + (-r) + "A" + r + " " + r + " 0 0 1 0 " + r;
    if (rx === 0) { return limb + "Z"; }                       /* half lit: the straight line back to the top pole */
    return limb + "A" + rx + " " + r + " 0 0 " + (k > 0.5 ? 1 : 0) + " 0 " + (-r) + "Z";
  }

  /* ---- Where the moon may sit: open sky only (manager's design call, 2026-11-14) --------------------------------
     The moon never covers the header's words. Rectangles are {left, top, right, bottom} in pixels. */
  function overlaps(a, b) { return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom; }

  /* The largest rectangle inside `band` that touches none of `blocks` and is at least `min` wide and high, or null.
     Its sides can only lie on the band's sides or a block's, so every such pair is tried (a dozen blocks at most).
     Of two equal ones the one further right wins: the side of the band the words leave open. */
  function freeRect(band, blocks, min) {
    var xs = [band.left, band.right], ys = [band.top, band.bottom], best = null, bestArea = 0;
    blocks.forEach(function (o) { xs.push(o.left, o.right); ys.push(o.top, o.bottom); });
    function inside(lo, hi) { return function (v) { return v >= lo && v <= hi; }; }
    function up(p, q) { return p - q; }
    xs = xs.filter(inside(band.left, band.right)).sort(up);
    ys = ys.filter(inside(band.top, band.bottom)).sort(up);
    xs.forEach(function (x1) { xs.forEach(function (x2) { if (x2 - x1 < min) { return; }
      ys.forEach(function (y1) { ys.forEach(function (y2) { if (y2 - y1 < min) { return; }
        var r = { left: x1, top: y1, right: x2, bottom: y2 }, area = (x2 - x1) * (y2 - y1);
        if (area < bestArea || (area === bestArea && best && x1 <= best.left)) { return; }
        if (blocks.some(function (o) { return overlaps(r, o); })) { return; }
        best = r; bestArea = area;
      }); });
    }); });
    return best;
  }

  /* The moon's box (its top left corner) inside the open sky: `x` 0 to 1 runs east to west across the free rectangle,
     `alt` 0 to 1 from its bottom (the horizon) to its top (straight overhead). Null when there is no room. */
  function moonSpot(band, blocks, size, x, alt) {
    var r = freeRect(band, blocks, size);
    if (!r) { return null; }
    return { left: Math.round(r.left + x * (r.right - r.left - size)),
             top: Math.floor(r.bottom - size - alt * (r.bottom - r.top - size)) };
  }

  /* The moon's drawing inside #sky-moon, made once: the lit part and nothing else. The unlit part of the disc is
     not drawn (owner, 2026-11-18: "as it looks, not a whole moon with a shadow"). */
  var SVG = "http://www.w3.org/2000/svg";
  function moonDrawing(doc, el) {
    var lit = doc.getElementById("sky-moon-lit");
    if (lit) { return lit; }
    var svg = doc.createElementNS(SVG, "svg");
    lit = doc.createElementNS(SVG, "path");
    svg.setAttribute("viewBox", "-10.5 -10.5 21 21"); svg.setAttribute("focusable", "false");
    lit.setAttribute("class", "moon-lit"); lit.setAttribute("id", "sky-moon-lit");
    svg.appendChild(lit); el.appendChild(svg);
    return lit;
  }

  /* What the moon must keep clear of, in the sky band's own pixels: the header's words (each line's own extent, not
     its full-width box) with `gap` around them, and the Menu button's column. The sun is not among them: the moon is
     drawn only while the sun is down, and a sun that is down is not drawn. */
  var WORDS = "#nav-open, .site-header .site-name, .site-header .unofficial-tag, .site-header .kicker, #sky-hero .sky-day";
  function skyBlocks(doc, f, gap) {
    var blocks = [], nodes = doc.querySelectorAll(WORDS), i, n, r, range;
    for (i = 0; i < nodes.length; i += 1) {
      n = nodes[i];
      if (n.id === "nav-open") {                /* the Menu button, and the whole column under it: the left edge */
        r = n.getBoundingClientRect();
        if (r.width > 0) { blocks.push({ left: -1e6, top: -1e6, right: r.right - f.left + gap, bottom: 1e6 }); }
        continue;
      }
      range = doc.createRange(); range.selectNodeContents(n); r = range.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) {
        blocks.push({ left: r.left - f.left - gap, top: r.top - f.top - gap, right: r.right - f.left + gap, bottom: r.bottom - f.top + gap });
      }
    }
    return blocks;
  }

  /* Puts the drawn moon in the open sky, or hides it when the band has no room. Tried in turn: its own size, then a
     smaller moon (a phone's band is short). */
  var drawn = null;                       /* the last moon drawn: { x, alt }, kept for a resize */
  function placeMoon(doc) {
    var el = doc.getElementById("sky-moon");
    if (!el || !drawn) { return; }
    el.style.removeProperty("--moon-size");
    el.removeAttribute("hidden");
    var f = el.parentNode.getBoundingClientRect(), size = el.offsetWidth;
    var band = { left: 8, top: 6, right: f.width - 8, bottom: f.height - 4 };
    var sizes = [size, Math.max(22, Math.round(size * 0.8))], i, spot, gap;
    for (i = 0; size && i < sizes.length; i += 1) {
      gap = Math.round(sizes[i] * 0.14) + 1;                                /* the moon's glow, and a little air */
      spot = moonSpot(band, skyBlocks(doc, f, gap), sizes[i], drawn.x, drawn.alt);
      if (spot) {
        if (sizes[i] !== size) { el.style.setProperty("--moon-size", sizes[i] + "px"); }
        el.style.setProperty("--moon-left", spot.left + "px");
        el.style.setProperty("--moon-top", spot.top + "px");
        return;
      }
    }
    el.setAttribute("hidden", "");
  }

  /* The place whose sky is drawn: { lat, lon } from #sky-moon, or null when the page names none (or a bad one). */
  function skyPlace(doc) {
    var el = doc.getElementById("sky-moon");
    if (!el) { return null; }
    var lat = parseFloat(el.getAttribute("data-lat")), lon = parseFloat(el.getAttribute("data-lon"));
    return isFinite(lat) && isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? { lat: lat, lon: lon } : null;
  }

  /* Draws the moon for this instant: its lit shape and tilt, then its place in the open sky. It stays hidden while
     the sun is up (`sunUp`: never both), while the moon is below the horizon, at new moon (under NEW of the disc lit:
     it cannot be seen in the real sky either), with no place on the page, and on any error. The shape is the real lit
     fraction, never padded: a thin crescent is drawn thin. */
  var NEW = 0.01;
  function renderMoon(doc, ms, where, sunUp) {
    var el = doc.getElementById("sky-moon");
    if (!el) { return; }
    var m = where && !sunUp ? moon(ms, where.lat, where.lon) : null;
    if (!m || !(m.alt > 0) || !(m.fraction >= NEW) || !isFinite(m.az + m.fraction + m.limb)) {
      drawn = null; el.setAttribute("hidden", ""); return;
    }
    var lit = moonDrawing(doc, el);
    lit.setAttribute("d", moonPath(m.fraction));
    lit.setAttribute("transform", "rotate(" + Math.round(m.limb - 90) + ")");
    drawn = { x: moonX(m.az), alt: Math.round(m.alt / 90 * 1000) / 1000 };
    placeMoon(doc);
  }

  /* The whole sky for this instant: the sun (over the site's place; by the viewer's clock on a page with no place),
     today's date in the site's zone, then the moon (it needs the date line in place to keep clear of it). The sun's
     data-at says whether it is up or down; the stylesheet draws no sun that is down, and the moon is drawn only
     then, so the two are never on the page together. */
  function render() {
    var doc = root.document || (typeof document !== "undefined" ? document : null);
    if (!doc) { return; }
    var now = new Date(), ms = now.getTime(), where = null, moonEl;
    try { where = skyPlace(doc); } catch (e) { /* no place: the viewer's clock */ }
    var sunEl = doc.getElementById("sky-sun");
    var sunAlt = where ? sunAltitude(ms, where.lat, where.lon) : altitude(now.getHours() + now.getMinutes() / 60);
    var sunUp = sunAlt > NIGHT;
    if (sunEl) {
      sunEl.style.setProperty("--sun-alt", String(sunAlt));
      sunEl.setAttribute("data-at", sunUp ? "up" : "down");
    }
    renderDate(doc, now);
    try { renderMoon(doc, ms, where, sunUp); } catch (e) {
      moonEl = doc.getElementById("sky-moon");                 /* no moon */
      if (moonEl) { moonEl.setAttribute("hidden", ""); }
    }
  }

  /* Today's weekday and date in the site's zone (data-tz on the hero), so the "<weekday> in <place> <date>" line is true
     for every viewer. */
  function renderDate(doc, now) {
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
  /* ---- The weather over the site's place --------------------------------------------------------------------
     One observation (the National Weather Service's latest for one station: GeoJSON, read from `properties`) is
     boiled down to a few plain facts, and SCENES, the one table of scenes, picks the scene to draw from them.
     Everything down to weatherOnly is pure: an observation and an instant in, a scene or null out. */
  var WX_MAX_AGE = 90 * 60000;   /* an observation older than this is not drawn: the plain sky, never old weather */
  var WX_AHEAD = 10 * 60000;     /* nor one stamped later than this past the viewer's clock (one of the two is wrong) */
  var WIND_MPH = 20, GUST_MPH = 30;         /* windy: sustained wind or gusts from here up, miles an hour */
  var LOW_VIS_M = 4800;                      /* fog without a fog report: seeing under about 3 miles, in metres */
  var COVER = { SKC: 0, CLR: 0, FEW: 1, SCT: 2, BKN: 3, OVC: 4, VV: 4 };   /* how much sky a cloud layer covers */
  /* the observation's words for what is falling or hanging in the air -> the METAR code of the same thing */
  var WX_WORD = { rain: "RA", drizzle: "DZ", snow: "SN", snow_grains: "SG", snow_pellets: "GS", ice_pellets: "PL",
                  ice_crystals: "IC", hail: "GR", unknown: "UP", thunderstorms: "TS", fog: "FG", fog_mist: "BR",
                  haze: "HZ", showers: "SH", rain_showers: "RA", freezing: "FZ" };
  /* miles an hour (or metres) from a { unitCode, value } quantity; null when there is no number */
  var TO_MPH = { "km_h-1": 0.621371, "m_s-1": 2.236936, "kn": 1.150779, "kt": 1.150779, "mi_h-1": 1 };
  var TO_M = { "m": 1, "km": 1000, "mi": 1609.344 };
  function quantity(q, table) {
    if (!q || typeof q !== "object" || typeof q.value !== "number" || !isFinite(q.value)) { return null; }
    var unit = String(q.unitCode || "").replace(/^[a-z]+:/i, "");
    return Object.prototype.hasOwnProperty.call(table, unit) ? q.value * table[unit] : null;
  }
  function own(table, key) { return Object.prototype.hasOwnProperty.call(table, key) ? table[key] : undefined; }

  /* The facts of one observation's `properties`:
       has        the METAR codes reported at the station, as keys (RA, SN, TS, FG ...). From presentWeather: its
                  rawString in two-letter groups, and its weather and modifier words; an entry "in the vicinity" (VC)
                  is not at the station and is left out, and so is snow that is blowing or drifting (BLSN, DRSN):
                  it is lifted off the ground by the wind, not falling. Only when presentWeather lists nothing are
                  the words of textDescription read instead ("Light Rain", "Thunderstorms and Rain", "Fog/Mist").
       intensity  "light", "heavy" or "moderate": of what is falling
       cover      the fullest cloud layer, 0 (clear) to 4 (overcast); from textDescription when no layer is listed
       windy      sustained wind of WIND_MPH or gusts of GUST_MPH (the word "Windy" or "Breezy" when neither is given)
       lowVis     seeing under LOW_VIS_M (a reported 0 is taken as no reading, not as fog) */
  function weatherFacts(p) {
    var has = {}, light = false, heavy = false, cover = 0, listed = 0, i, e, raw, text;
    var pw = Array.isArray(p.presentWeather) ? p.presentWeather : [];
    function word(w) { if (typeof w === "string" && own(WX_WORD, w)) { has[own(WX_WORD, w)] = true; } }
    function code(c) { has[c] = true; }
    for (i = 0; i < pw.length && i < 12; i += 1) {
      e = pw[i];
      if (!e || typeof e !== "object") { continue; }
      raw = typeof e.rawString === "string" ? e.rawString.toUpperCase() : "";
      if (e.inVicinity === true || /^VC/.test(raw)) { continue; }
      listed += 1;
      if (/^[+-]?(BL|DR)/.test(raw) || e.modifier === "blowing" || e.modifier === "low_drifting") { continue; }
      if (/^[+-]?([A-Z]{2})+$/.test(raw)) { (raw.replace(/^[+-]/, "").match(/[A-Z]{2}/g) || []).forEach(code); }
      word(e.weather); word(e.modifier);
      if (e.intensity === "heavy" || raw.charAt(0) === "+") { heavy = true; }
      if (e.intensity === "light" || raw.charAt(0) === "-") { light = true; }
    }
    /* the description's words, less the one thing said to be "in vicinity" (the word just before it) and less snow
       that is only blowing or drifting */
    text = typeof p.textDescription === "string"
      ? p.textDescription.toLowerCase().replace(/[a-z]+ in vicinity/g, " ").replace(/(blowing|drifting) snow/g, " ") : "";
    if (!listed && text) {
      if (/thunder/.test(text)) { has.TS = true; }
      if (/snow|flurr|sleet|ice pellets|wintry/.test(text)) { has.SN = true; }
      if (/rain|drizzle/.test(text) || (/shower/.test(text) && !has.SN)) { has.RA = true; }
      if (/fog|mist/.test(text)) { has.FG = true; }
      if (/haze/.test(text)) { has.HZ = true; }
      heavy = /heavy/.test(text); light = /light/.test(text);
    }
    var layers = Array.isArray(p.cloudLayers) ? p.cloudLayers : [], known = false;
    for (i = 0; i < layers.length && i < 12; i += 1) {
      e = layers[i] && typeof layers[i].amount === "string" ? own(COVER, layers[i].amount.toUpperCase()) : undefined;
      if (typeof e === "number") { known = true; cover = Math.max(cover, e); }
    }
    if (!known && text) {
      cover = /mostly cloudy/.test(text) ? 3 : /overcast|cloudy/.test(text) && !/partly/.test(text) ? 4
        : /partly (cloudy|sunny)/.test(text) ? 2 : 0;
    }
    var wind = quantity(p.windSpeed, TO_MPH), gust = quantity(p.windGust, TO_MPH), vis = quantity(p.visibility, TO_M);
    return { has: has, intensity: heavy ? "heavy" : light ? "light" : "moderate", cover: cover,
             windy: (wind !== null && wind >= WIND_MPH) || (gust !== null && gust >= GUST_MPH)
               || (wind === null && gust === null && /windy|breezy/.test(text)),
             lowVis: vis !== null && vis > 0 && vis < LOW_VIS_M };
  }

  /* The scenes, in one place. The first whose `when` holds is the scene, so the order is the precedence: a
     thunderstorm beats snow beats rain beats fog beats cloud beats wind, and "clear" (the plain sky) is what is left.
     `falls`: something may be falling, so the scene carries an intensity. Freezing rain is rain; sleet (ice pellets)
     and rain mixed with snow are snow. Wind is a scene of its own only under a clear sky; over any other scene it is
     a modifier (`windy`) that makes the scene drift faster. To add a scene: a row here, in its place in the order,
     and its drawing in style.css under `.has-sky[data-wx="<id>"]`. */
  function any(f, codes) { return codes.some(function (c) { return f.has[c] === true; }); }
  var FALLING = ["RA", "DZ", "SN", "SG", "GS", "PL", "IC", "GR", "UP"];
  var SCENES = [
    { id: "storm",    falls: true,  when: function (f) { return any(f, ["TS"]); } },
    { id: "snow",     falls: true,  when: function (f) { return any(f, ["SN", "SG", "GS", "PL", "IC"]); } },
    { id: "rain",     falls: true,  when: function (f) { return any(f, ["RA", "DZ", "GR", "UP"]); } },
    { id: "fog",      falls: false, when: function (f) { return any(f, ["FG", "BR", "HZ"]) || f.lowVis; } },
    { id: "overcast", falls: false, when: function (f) { return f.cover >= 3; } },           /* broken or overcast */
    { id: "partly",   falls: false, when: function (f) { return f.cover === 2; } },          /* scattered */
    { id: "windy",    falls: false, when: function (f) { return f.windy; } },
    { id: "clear",    falls: false, when: function () { return true; } }
  ];

  /* The scene for one observation at an instant (a Date.now() value), or null: the plain sky. Null for anything that
     is not a fresh observation: not an object, no readable timestamp, older than WX_MAX_AGE, or stamped in the future.
       scene      a SCENES id
       intensity  "light", "moderate" or "heavy" while something is falling, else null (a dry thunderstorm: null)
       windy      true when the wind is up */
  function weatherScene(obs, ms) {
    var p = obs && typeof obs === "object" ? obs.properties : null;
    if (!p || typeof p !== "object" || typeof p.timestamp !== "string") { return null; }
    var at = Date.parse(p.timestamp);
    if (!isFinite(at) || typeof ms !== "number" || !(ms - at <= WX_MAX_AGE) || !(at - ms <= WX_AHEAD)) { return null; }
    var f = weatherFacts(p), i;
    for (i = 0; i < SCENES.length; i += 1) {
      if (SCENES[i].when(f)) {
        return { scene: SCENES[i].id, intensity: SCENES[i].falls && any(f, FALLING) ? f.intensity : null, windy: f.windy };
      }
    }
    return null;
  }

  /* Only the weather of an observation: the fields weatherFacts reads and nothing else. This is all the page holds. */
  function weatherOnly(obs) {
    var p = obs && typeof obs === "object" && obs.properties && typeof obs.properties === "object" ? obs.properties : null;
    if (!p) { return null; }
    function str(v, n) { return typeof v === "string" ? v.slice(0, n) : null; }
    function q(v) {
      return v && typeof v === "object" ? { unitCode: str(v.unitCode, 24), value: typeof v.value === "number" ? v.value : null } : null;
    }
    return { properties: {
      timestamp: str(p.timestamp, 40), textDescription: str(p.textDescription, 120),
      presentWeather: (Array.isArray(p.presentWeather) ? p.presentWeather : []).slice(0, 12).map(function (e) {
        e = e && typeof e === "object" ? e : {};
        return { rawString: str(e.rawString, 16), weather: str(e.weather, 24), modifier: str(e.modifier, 24),
                 intensity: str(e.intensity, 12), inVicinity: e.inVicinity === true };
      }),
      cloudLayers: (Array.isArray(p.cloudLayers) ? p.cloudLayers : []).slice(0, 12).map(function (e) {
        return { amount: str(e && e.amount, 8) };
      }),
      windSpeed: q(p.windSpeed), windGust: q(p.windGust), visibility: q(p.visibility) } };
  }

  /* Draws a scene (or, for null and "clear", takes any scene away). The scene is three attributes on the header,
     which the stylesheet draws from; the layer it draws in (#sky-wx: decoration, aria-hidden, behind the words, laid
     over the sky without taking any room) is made the first time a scene needs it. */
  function drawWeather(doc, w) {
    var moonEl = doc.getElementById("sky-moon"), frame = moonEl && moonEl.parentNode, header = frame && frame.parentNode;
    if (!header) { return; }
    if (!w || w.scene === "clear") {
      header.removeAttribute("data-wx"); header.removeAttribute("data-wx-fall"); header.removeAttribute("data-wx-wind");
      return;
    }
    if (!doc.getElementById("sky-wx")) {
      var layer = doc.createElement("div");
      layer.id = "sky-wx"; layer.className = "sky-wx"; layer.setAttribute("aria-hidden", "true");
      ["wx-veil", "wx-clouds", "wx-fall wx-far", "wx-fall wx-near", "wx-flash"].forEach(function (name) {
        var part = doc.createElement("span"); part.className = name; layer.appendChild(part);
      });
      header.insertBefore(layer, frame.nextSibling);
    }
    header.setAttribute("data-wx", w.scene);
    if (w.intensity) { header.setAttribute("data-wx-fall", w.intensity); } else { header.removeAttribute("data-wx-fall"); }
    if (w.windy) { header.setAttribute("data-wx-wind", ""); } else { header.removeAttribute("data-wx-wind"); }
  }

  /* The observation this page view holds (weather only), judged again at every redraw: a tab left open stops
     drawing it once it is WX_MAX_AGE old. It is asked for once per page view and never again. */
  var held = null;
  function showWeather() {
    var doc = root.document, w = null;
    if (!doc) { return; }
    try { w = held ? weatherScene(held, Date.now()) : null; } catch (e) { w = null; }
    try { drawWeather(doc, w); } catch (e2) { /* the plain sky */ }
  }

  /* Asks for the observation: one request per page view, to the one address the page names (data-weather on
     #sky-moon; the page's CSP allows that origin only), with no credentials and no referrer. Nothing is stored: a
     later page asks again, and the browser's own cache answers it while the service's answer is still current. Any
     failure (no answer in WX_TIMEOUT, an error status, an answer that says it is over WX_MAX_BYTES, not JSON,
     anything thrown) leaves the plain sky; nothing is tried twice. */
  var WX_TIMEOUT = 5000, WX_MAX_BYTES = 65536, asked = false;       /* an observation is a few thousand bytes */
  function tooBig(res) {
    var n = res.headers && typeof res.headers.get === "function" ? parseInt(res.headers.get("content-length"), 10) : NaN;
    return isFinite(n) && n > WX_MAX_BYTES;
  }
  function loadWeather() {
    var doc = root.document, el = doc && doc.getElementById("sky-moon"), url = el && el.getAttribute("data-weather");
    if (asked || !url || !/^https:\/\//.test(url) || typeof root.fetch !== "function") { return; }
    asked = true;
    var done = false, timer = 0, ctl = typeof root.AbortController === "function" ? new root.AbortController() : null;
    function finish(obs) {
      if (done) { return; }
      done = true; root.clearTimeout(timer);
      held = obs ? weatherOnly(obs) : null;
      showWeather();
    }
    timer = root.setTimeout(function () {
      finish(null);
      try { if (ctl) { ctl.abort(); } } catch (e) { /* already over */ }
    }, WX_TIMEOUT);
    try {
      root.fetch(url, { credentials: "omit", referrerPolicy: "no-referrer", signal: ctl ? ctl.signal : undefined })
        .then(function (res) { if (!res || !res.ok || tooBig(res)) { throw new Error("status"); } return res.json(); })
        .then(function (obs) { finish(obs); }, function () { finish(null); });
    } catch (e3) { finish(null); }
  }

  /* The timer, and a tab coming back into view: the whole sky again (sun, date line, moon), so the sun, the date
     and the moon always agree in a tab left open across a sunset or a sunrise. Nothing is drawn while hidden. */
  function tick() {
    var doc = root.document;
    if (!doc || doc.hidden) { return; }
    render();
    showWeather();
  }
  /* the same moon put back in the open sky after the layout changes (a resize, the web fonts arriving) */
  function replace() {
    try { if (root.document) { placeMoon(root.document); } } catch (e) { /* the moon stays where it was */ }
  }
  var api = { altitude: altitude, render: render, RISE: RISE, SET: SET, NIGHT: NIGHT,
              sun: sun, sunAltitude: sunAltitude, SUN_UP: SUN_UP, NEW: NEW, moon: moon, moonPosition: moonPosition, sunPosition: sunPosition, moonX: moonX, moonPath: moonPath,
              freeRect: freeRect, moonSpot: moonSpot, renderMoon: renderMoon, tick: tick,
              weatherScene: weatherScene, weatherFacts: weatherFacts, weatherOnly: weatherOnly, drawWeather: drawWeather,
              loadWeather: loadWeather, showWeather: showWeather,
              SCENES: SCENES, WX_MAX_AGE: WX_MAX_AGE, WX_TIMEOUT: WX_TIMEOUT };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  root.CRSky = api;
  render();
  /* a page restored from the back/forward cache gets a fresh date and sun */
  if (root.addEventListener) { root.addEventListener("pageshow", function (ev) { if (ev && ev.persisted) { render(); showWeather(); } }); }
  try { loadWeather(); } catch (e) { /* the plain sky */ }
  if (root.document && root.document.getElementById("sky-moon")) {
    /* the sky turns about a degree every four minutes, so it is redrawn every five while the page is open,
       and at once when the tab is looked at again */
    if (root.setInterval) { root.setInterval(tick, 300000); }
    if (root.document.addEventListener) { root.document.addEventListener("visibilitychange", tick); }
    var waiting = false;
    if (root.addEventListener) {
      root.addEventListener("resize", function () {
        if (waiting) { return; }
        waiting = true;
        (root.requestAnimationFrame || root.setTimeout)(function () { waiting = false; replace(); });
      });
    }
    if (root.document.fonts && root.document.fonts.ready) { root.document.fonts.ready.then(replace, function () {}); }
  }
}(typeof window !== "undefined" ? window : this));
