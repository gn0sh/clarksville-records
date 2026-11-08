/* Runs inside the address box's hidden iframe (sandbox="allow-scripts", no allow-same-origin: an opaque origin with
   no access to the page). Loads the geocoder's JSONP from the URL in data-u and hands the answer to the parent as
   JSON text. Fixed text: the page's CSP allows exactly this script by its sha256. */
(function () {
  "use strict";
  var me = document.currentScript, url = me ? me.getAttribute("data-u") : "", sent = false;
  function send(m) {
    if (sent) { return; }
    sent = true;
    parent.postMessage(m, "*");
  }
  window.crGeocode = function (data) {
    var raw = null;
    try { raw = JSON.stringify(data); } catch (e) { raw = null; }
    try { delete window.crGeocode; } catch (e) { window.crGeocode = undefined; }
    send({ cr: "answer", json: typeof raw === "string" ? raw : null });
  };
  if (!url) { send({ cr: "blocked" }); return; }
  var sc = document.createElement("script");
  sc.referrerPolicy = "no-referrer";
  sc.onload = function () { setTimeout(function () { send({ cr: "loaded" }); }, 0); };
  sc.onerror = function () { send({ cr: "blocked" }); };
  sc.src = url;
  document.head.appendChild(sc);
})();
