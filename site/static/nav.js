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
/* Desktop: the landing's district list is always open in its side column (design 3.3); phones keep it collapsed. */
(function () {
  if (!window.matchMedia || !window.matchMedia("(min-width: 900px)").matches) { return; }
  var open = document.querySelectorAll("details[data-open-wide]");
  for (var i = 0; i < open.length; i++) { open[i].open = true; }
})();
