/* "No email? Just count me" counter for the national lookup pages (ADR 0013, architecture section 3.9). A page loads
   this only while config/site.yml analytics.code is set; the build writes the counter's address into this tag's
   data-goatcounter attribute, the same value count.js reads. It is a second small script so count.js stays untouched.

   Exposes window.DaylightCount = {available: boolean, send(govId) -> Promise<void>}. send() makes one request:
   GET https://<code>.goatcounter.com/count?p=count-<govId>&e=true&rnd=<random>, and nothing else is ever sent: no
   page path, no referrer, no screen size, no address, no email. The id must match the government id form
   (layer-GEOID); anything else rejects without a request. This script never reads a form field, the values in the
   address, a device store or cookies, and it sets none. Do Not Track, Global Privacy Control, automated browsers,
   non-https pages and an empty or malformed code send nothing and set available to false, so the page draws no
   button. The three guard lines below are a copy of count.js's; tests/test_us_count.py asserts they stay equal. */
(function () {
  "use strict";
  var ID = /^(place|county|cousub|sdu|sds|sde)-[0-9]{2,14}$/;
  var tag = document.querySelector("script[data-goatcounter]");
  var end = tag ? tag.getAttribute("data-goatcounter") : "";
  // Each guard line leaves this function early (undefined) when the counter must stay silent.
  var on = (function () {
  if (!/^https:\/\/[a-z0-9][a-z0-9-]{1,48}[a-z0-9]\.goatcounter\.com\/count$/.test(end || "")) { return; }
  if (location.protocol !== "https:" || typeof fetch !== "function") { return; }
  if (navigator.webdriver || navigator.doNotTrack === "1" || window.doNotTrack === "1" ||
      navigator.globalPrivacyControl === true) { return; }
    return true;
  }()) === true;

  function send(id) {
    if (!on) { return Promise.reject(new Error("counting is off")); }
    if (typeof id !== "string" || !ID.test(id)) { return Promise.reject(new Error("not a government id")); }
    var url = end + "?p=" + encodeURIComponent("count-" + id) + "&e=true&rnd=" +
      (Math.random().toString(36).slice(2, 10) || "0");
    try {
      return Promise.resolve(fetch(url, {method: "GET", mode: "no-cors", credentials: "omit", cache: "no-store",
        keepalive: true, referrerPolicy: "no-referrer"})).then(function () {});
    } catch (e) { return Promise.reject(e); }
  }

  window.DaylightCount = {available: on, send: send};
}());
