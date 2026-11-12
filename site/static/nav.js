/* Navigation drawer (docs/design/landing-search-nav.md 2.1). First-party, vanilla, no network calls.
   Without JS the "Menu" link jumps to the footer list. With JS that list is cloned into a native modal <dialog>
   (focus moves in and is trapped, Esc closes, the page behind is inert) and the link becomes a button. */
(function () {
  var link = document.getElementById("nav-open");
  var list = document.querySelector("#site-nav .nav-list");
  var nav = document.getElementById("site-nav");
  if (!link || !list || typeof HTMLDialogElement !== "function") { return; }

  var dlg = document.createElement("dialog");
  dlg.id = "site-nav-drawer";
  dlg.className = "drawer";
  dlg.setAttribute("aria-labelledby", "nav-title");
  dlg.innerHTML = '<div class="drawer-panel">' +
    '<div class="drawer-head"><h2 id="nav-title">Menu</h2>' +
    '<button type="button" class="drawer-close" autofocus><span aria-hidden="true">&times;</span>' +
    '<span class="sr-only">Close menu</span></button></div>' +
    '<form class="drawer-search" role="search" method="get"><label for="drawer-q">Search records</label>' +
    '<div class="search-row"><input id="drawer-q" name="q" type="search" placeholder="Item title, number, name or street">' +
    '<button type="submit">Search</button></div></form></div>';
  dlg.querySelector("form").action = nav.getAttribute("data-search");
  var copy = list.cloneNode(true);
  dlg.firstChild.appendChild(copy);
  document.body.appendChild(dlg);

  var btn = document.createElement("button");
  btn.type = "button";
  btn.id = "nav-open";
  btn.className = link.className;
  btn.innerHTML = link.innerHTML;
  btn.setAttribute("aria-controls", "site-nav-drawer");
  btn.setAttribute("aria-expanded", "false");
  btn.setAttribute("aria-haspopup", "dialog");
  link.parentNode.replaceChild(btn, link);
  // The drawer now carries the full list, so the landing can hide the footer copy and fit one screen.
  document.documentElement.classList.add("has-drawer");

  btn.addEventListener("click", function () {
    dlg.showModal();
    btn.setAttribute("aria-expanded", "true");
  });
  dlg.querySelector(".drawer-close").addEventListener("click", function () { dlg.close(); });
  dlg.addEventListener("close", function () {
    btn.setAttribute("aria-expanded", "false");
    btn.focus();
  });
  // A click on the backdrop lands on the <dialog> element itself (the panel fills the dialog's box).
  dlg.addEventListener("click", function (e) { if (e.target === dlg) { dlg.close(); } });
})();

/* "Report an error" links (M1.5, docs/design/correction-intake.md): just before one is followed (pressed, touched,
   focused or clicked), its #fragment is set to this page's site path and the fact id of the row it sits in (or the
   #anchor the reader came to). Nothing is stored or sent; static/report.js checks both values again. */
(function () {
  var nav = document.getElementById("site-nav");
  if (!nav || typeof URL !== "function" || !document.addEventListener) { return; }
  var rootPath;
  try { rootPath = new URL(nav.getAttribute("data-root") || "./", window.location.href).pathname; } catch (e) { return; }
  var REPORT = /(^|\/)report\.html(#|$)/;
  // Only a link to this site's own report.html is rewritten (nav-report/regex-overmatch): resolved against this page,
  // it must have this page's scheme and host, and a path ending in /report.html.
  function ownReportLink(href) {
    if (!REPORT.test(href)) { return false; }
    try {
      var u = new URL(href, window.location.href);
      return u.protocol === window.location.protocol && u.host === window.location.host &&
        /(^|\/)report\.html$/.test(u.pathname);
    } catch (e) { return false; }
  }

  function prepare(e) {
    var a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
    if (!a || !ownReportLink(a.getAttribute("href"))) { return; }
    var path = window.location.pathname;
    var page = path.indexOf(rootPath) === 0 ? path.slice(rootPath.length) : "";
    if (page === "" || page.slice(-1) === "/") { page += "index.html"; }
    var holder = a.closest("[data-fact-id]");
    var id = holder ? holder.getAttribute("data-fact-id") : "";
    if (!id && window.location.hash) {
      try { id = decodeURIComponent(window.location.hash.slice(1)); } catch (err) { id = ""; }
    }
    var parts = ["page=" + encodeURIComponent(page)];
    if (id) { parts.push("id=" + encodeURIComponent(id)); }
    a.setAttribute("href", a.getAttribute("href").split("#")[0] + "#" + parts.join("&"));
  }
  ["mousedown", "touchstart", "focusin", "click"].forEach(function (type) {
    document.addEventListener(type, prepare, true);
  });
})();
