/* Cookie-free visitor counting (ADR 0008, docs/ops/analytics.md). A page loads this only while config/site.yml
   analytics.code is set; the build writes the counter's address into this tag's data-goatcounter attribute.

   Sent, and nothing else: the page's path (never its ?query or #fragment), the origin of an outside page that linked
   here (never its path), the screen size, and two events: "support-click" (a Buy Me a Coffee link) and "search"
   (once per page view, without the words). This script never reads a form field, the values in the address, storage
   or cookies, so nothing a visitor types (a search, an address) can be sent. It sets no cookies and stores nothing.
   Do Not Track, Global Privacy Control, automated browsers and non-https pages send nothing. */
(function () {
  "use strict";
  var tag = document.querySelector("script[data-goatcounter]");
  var end = tag ? tag.getAttribute("data-goatcounter") : "";
  if (!/^https:\/\/[a-z0-9][a-z0-9-]{1,48}[a-z0-9]\.goatcounter\.com\/count$/.test(end || "")) { return; }
  if (location.protocol !== "https:" || typeof fetch !== "function") { return; }
  if (navigator.webdriver || navigator.doNotTrack === "1" || window.doNotTrack === "1" ||
      navigator.globalPrivacyControl === true) { return; }

  function send(fields) {
    var q = [];
    Object.keys(fields).forEach(function (k) { q.push(k + "=" + encodeURIComponent(fields[k])); });
    q.push("rnd=" + Math.random().toString(36).slice(2, 10));
    try {
      fetch(end + "?" + q.join("&"), {method: "GET", mode: "no-cors", credentials: "omit", cache: "no-store",
        keepalive: true, referrerPolicy: "no-referrer"}).catch(function () {});
    } catch (e) { /* counting never breaks a page */ }
  }

  // An outside page's origin only ("https://example.com"); nothing for a link from inside this site.
  function outsideOrigin() {
    var u;
    try { u = new URL(document.referrer); } catch (e) { return ""; }
    if (!/^https?:$/.test(u.protocol) || u.host === location.host) { return ""; }
    return u.protocol + "//" + u.host;
  }

  var view = {p: location.pathname};
  var ref = outsideOrigin();
  if (ref) { view.r = ref; }
  if (window.screen) { view.s = [screen.width, screen.height, window.devicePixelRatio || 1].join(","); }
  send(view);

  function event(name) { send({p: name, e: "true"}); }

  // Buy Me a Coffee: every link the build marks data-ext="support" (footer, Alerts page)
  document.addEventListener("click", function (e) {
    var a = e.target && e.target.closest ? e.target.closest('a[data-ext="support"]') : null;
    if (a) { event("support-click"); }
  }, true);

  // A search, once per page view: the search page opened with a query (from the home page box or a shared link) or
  // its form used. Only that it happened is sent; the words are never read.
  var form = document.getElementById("search-form");
  if (form) {
    var counted = false, timer = null;
    var once = function () {
      if (!counted) { counted = true; event("search"); }
    };
    if (location.search.length > 1) { once(); }
    form.addEventListener("submit", once);
    form.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(once, 1500);   // typing pauses: one search, not one per key
    });
  }
}());
