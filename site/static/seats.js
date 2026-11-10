/* "Your seats" (landing). After an address lookup finds a district or ward, or a click on a map area, the visitor's
   district and ward numbers are kept in this browser only: one localStorage key, two small numbers,
   never sent anywhere by this script, no cookies. (The one way they can leave the device: the morning note's sign-up
   form, when it is enabled, posts them while its visible "include my saved seats" box is ticked; static/morning.js.) On a later visit the "Your seats" box links to those seats' pages, built from this
   page's own lists (a stored number that matches no list row shows nothing), and its Forget button clears the key.
   Every storage call is wrapped: if storage is blocked or full the box simply never shows and nothing breaks.
   First-party, no network calls. Exposes CRSeats for tests and for static/address.js (module.exports under node). */
(function (root) {
  "use strict";
  var KEY = "cr-your-seats";

  function store() { try { return root.localStorage || null; } catch (e) { return null; } }

  function num(v) { return typeof v === "number" && isFinite(v) && v >= 1 && v <= 999 && Math.floor(v) === v ? v : null; }

  /* Stored text -> {district, ward} (each a number or null), or null when there is nothing usable. */
  function parse(raw) {
    var o;
    try { o = JSON.parse(raw); } catch (e) { return null; }
    if (!o || typeof o !== "object" || Array.isArray(o)) { return null; }
    var d = num(o.district), w = num(o.ward);
    return d === null && w === null ? null : { district: d, ward: w };
  }

  function read() {
    var s = store();
    if (!s) { return null; }
    try { return parse(s.getItem(KEY)); } catch (e) { return null; }
  }

  /* Keep what is new, and what was kept for the other seat (a map click names one seat). With `replace` (an address
     lookup, which answers for both seats at once) a seat it did not find is cleared, never kept from an earlier
     address. Returns true when written. */
  function save(seats, replace) {
    var s = store();
    if (!s || !seats || typeof seats !== "object") { return false; }
    var old = replace === true ? { district: null, ward: null } : (read() || { district: null, ward: null });
    var d = num(seats.district) !== null ? seats.district : old.district;
    var w = num(seats.ward) !== null ? seats.ward : old.ward;
    if (d === null && w === null) { return false; }
    try { s.setItem(KEY, JSON.stringify({ district: d, ward: w })); return true; } catch (e) { return false; }
  }

  function forget() {
    var s = store();
    if (!s) { return false; }
    try { s.removeItem(KEY); return true; } catch (e) { return false; }
  }

  var api = { KEY: KEY, parse: parse, read: read, save: save, forget: forget };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  root.CRSeats = api;

  var doc = root.document;
  if (!doc) { return; }

  /* A click on a map area is a choice of district: keep it, and let the link go on to the district's page. */
  var areas = doc.querySelectorAll("#layer-districts a[data-district]");
  for (var i = 0; i < areas.length; i++) {
    areas[i].addEventListener("click", function (e) {
      save({ district: Number(e.currentTarget.getAttribute("data-district")) });
    });
  }
  var wardAreas = doc.querySelectorAll("#layer-wards a[data-ward]");   // the same for a ward, when wards are live
  for (var k = 0; k < wardAreas.length; k++) {
    wardAreas[k].addEventListener("click", function (e) {
      save({ ward: Number(e.currentTarget.getAttribute("data-ward")) });
    });
  }

  var box = doc.getElementById("your-seats");
  var list = box ? box.querySelector(".your-seats-list") : null;
  var button = doc.getElementById("seats-forget");
  if (!box || !list || !button) { return; }

  function rowLink(selector) {
    var a = doc.querySelector(selector + " > a");
    var label = a ? a.querySelector(".d-label") : null;
    var href = a ? a.getAttribute("href") : "";
    return a && label && href ? { href: href, label: label.textContent } : null;
  }

  function render() {
    var seats = read();
    var found = [];
    if (seats) {
      if (seats.ward !== null) { found.push(rowLink('li[data-seat="ward-' + seats.ward + '"]')); }
      if (seats.district !== null) { found.push(rowLink('li[data-district="' + seats.district + '"]')); }
    }
    found = found.filter(Boolean);
    while (list.firstChild) { list.removeChild(list.firstChild); }
    if (!found.length) { box.hidden = true; return; }
    found.forEach(function (f) {
      var li = doc.createElement("li");
      var a = doc.createElement("a");
      a.setAttribute("href", f.href);
      a.textContent = f.label;
      li.appendChild(a);
      list.appendChild(li);
    });
    box.hidden = false;
  }

  button.addEventListener("click", function () {
    forget();
    box.hidden = true;
    var status = doc.getElementById("seats-status");
    if (status) { status.textContent = "Saved seats forgotten"; }
    var q = doc.getElementById("addr-q");
    if (!q || q.closest("[hidden]")) { q = doc.getElementById("landing-q"); }
    if (q) { q.focus(); }
  });
  render();
})(typeof window !== "undefined" ? window : this);
