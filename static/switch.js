/* "Show records from" (sitegen/bodies.py). Without this script every option is a plain link to that body's hub page.
   With it the choice is remembered on this device (one localStorage key holding a body's short key; nothing is sent
   anywhere and no cookie is set) and, on a page whose rows carry data-body, the rows of other bodies are hidden by a
   class: nothing is removed, and a line above them (first on the home page) says what is shown and offers
   "Show all", so a choice remembered from an earlier visit is not missed. When storage is blocked
   the choice still works on the page being read. The search page filters its own results (static/search.js) from the
   data-body-choice attribute this script keeps on <html>, and hears each change as a "bodychoice" event.
   The choice is saved only when the visitor clicks an option (or "Show all"): opening a body's hub page shows that body
   as the choice on that page and leaves the saved one alone. A page that names the bodies it can filter
   (data-body-live) ignores a saved body it does not hold. An element with data-label-all (a day button) has its
   aria-label swapped for its data-label-<body> text, so a screen reader hears the count a sighted visitor sees; its
   data-label-suffix, if any, is kept at the end. A click on an option that filters in place (or on "Show all") is
   first announced as a "bodypick" event, so the search page can hand the decision to the switch. */
(function () {
  var nav = document.getElementById("body-switch");
  if (!nav) { return; }
  var KEY = "cr-body", ALL = "all";
  var main = document.getElementById("main");
  var here = nav.getAttribute("data-here") || "";
  var list = nav.querySelector(".bs-list");
  var links = {}, mem = null, line = null, cur = ALL, lineSig = null;
  var as = nav.querySelectorAll("a[data-switch]");
  for (var i = 0; i < as.length; i++) { links[as[i].getAttribute("data-switch")] = as[i]; }

  function store() { try { return window.localStorage || null; } catch (e) { return null; } }
  function read() {
    var v = mem;
    if (v === null) { try { var s = store(); v = s ? s.getItem(KEY) : null; } catch (e) { v = null; } }
    return v && Object.prototype.hasOwnProperty.call(links, v) ? v : ALL;
  }
  function save(v) {
    mem = v;
    try { var s = store(); if (s) { if (v === ALL) { s.removeItem(KEY); } else { s.setItem(KEY, v); } } } catch (e) { /* blocked: this page only */ }
  }
  function label(k) { return links[k].getAttribute("data-label"); }
  function tagged() { return main ? main.querySelectorAll("[data-body]") : []; }
  function live() { return document.querySelector("[data-body-live]"); }
  function liveHas(k) { var el = live(); return !!el && (" " + el.getAttribute("data-body-live") + " ").indexOf(" " + k + " ") >= 0; }

  function mark(choice) {
    for (var k in links) {
      if (!Object.prototype.hasOwnProperty.call(links, k)) { continue; }
      if (k === choice) { links[k].setAttribute("aria-current", k === here ? "page" : "true"); } else { links[k].removeAttribute("aria-current"); }
    }
    var a = links[choice];   // keep the chosen chip in view in the phone's scrolling row (the page itself never moves)
    if (list && a && list.scrollWidth > list.clientWidth) { list.scrollLeft = Math.max(0, a.offsetLeft - list.offsetLeft - 16); }
  }

  function showLine(choice, shown, first) {
    if (line && line.parentNode) { line.parentNode.removeChild(line); }
    line = null;
    if (choice === ALL || !first) { return; }
    line = document.createElement("p");
    line.className = shown ? "bs-line" : "bs-line bs-line-none";   // -none: the longer line, which may wrap
    line.id = "bs-line";
    line.setAttribute("role", "status");
    var b = document.createElement("strong");
    b.textContent = "Showing " + label(choice) + " only";
    line.appendChild(b);
    line.appendChild(document.createTextNode(" "));
    if (!shown) {
      var none = document.createElement("span");
      none.textContent = "Nothing on this page is from " + label(choice) + ".";
      line.appendChild(none);
      line.appendChild(document.createTextNode(" "));
      var go = document.createElement("a");
      go.href = links[choice].href;
      go.textContent = label(choice) + " page";
      line.appendChild(go);
      line.appendChild(document.createTextNode(" "));
    }
    var btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Show all";
    btn.addEventListener("click", function () { pick(ALL); (links[ALL] || nav).focus(); });
    line.appendChild(btn);
    var slot = main ? main.querySelector("[data-body-line]") : null;   // the page's own place for the line, if it has one
    if (slot) { slot.appendChild(line); } else { first.parentNode.insertBefore(line, first); }
  }

  function relabel(choice) {
    var els = main ? main.querySelectorAll("[data-label-all]") : [];
    for (var i = 0; i < els.length; i++) {
      var t = els[i].getAttribute("data-label-" + choice);
      if (choice === ALL || t === null) { t = els[i].getAttribute("data-label-all"); }
      els[i].setAttribute("aria-label", t + (els[i].getAttribute("data-label-suffix") || ""));
    }
  }

  // again: the same choice applied once more (after the other scripts ran). The status line is rebuilt, and the page
  // told, only when what the line says would change, so a screen reader hears it once and Search updates once.
  function apply(choice, again) {
    cur = choice;
    document.documentElement.setAttribute("data-body-choice", choice);
    relabel(choice);
    mark(choice);
    var items = tagged(), shown = 0, i;
    for (i = 0; i < items.length; i++) {
      var off = choice !== ALL && items[i].getAttribute("data-body") !== choice;
      items[i].classList.toggle("bs-off", off);
      if (!off) { shown++; }
    }
    var groups = main ? main.querySelectorAll("[data-body-group]") : [];
    for (i = 0; i < groups.length; i++) {
      var mine = groups[i].querySelectorAll("[data-body]"), any = false, left = false;
      for (var j = 0; j < mine.length; j++) {
        if (mine[j].hidden) { continue; }
        any = true;
        if (!mine[j].classList.contains("bs-off")) { left = true; }
      }
      groups[i].classList.toggle("bs-all-off", any && !left);
    }
    var lv = live(), has = lv ? liveHas(choice) : shown > 0, at = lv || (items.length ? items[0] : null);
    var sig = choice + "|" + (has ? 1 : 0) + "|" + (at ? 1 : 0);
    if (again && sig === lineSig && (!line || line.parentNode)) { return; }
    lineSig = sig;
    showLine(choice, has ? 1 : 0, at);
    try { document.dispatchEvent(new CustomEvent("bodychoice", { detail: choice })); } catch (e) { /* old browser: the page still filters */ }
  }

  // The visitor's own pick: saved, announced first as "bodypick" (static/search.js clears its Body boxes so the pick
  // decides), then applied.
  function pick(k) {
    save(k);
    try { document.dispatchEvent(new CustomEvent("bodypick", { detail: k })); } catch (e) { /* old browser */ }
    apply(k);
  }

  // A body's hub page shows that body as the choice, on that page only (nothing is saved by a visit). The home page
  // (All's own page) keeps whatever was chosen before. A page that lists the bodies it holds ignores any other.
  var first = here && here !== ALL ? here : read();
  if (live() && first !== ALL && !liveHas(first)) { first = ALL; }
  apply(first);
  // Scripts that run after this one may move or show rows (static/landing.js, static/days.js): once every deferred
  // script has run, apply the choice again so the "nothing of this body" flags and labels match the rows as shown.
  document.addEventListener("DOMContentLoaded", function () { apply(cur, true); });

  nav.addEventListener("click", function (e) {
    var a = e.target.closest ? e.target.closest("a[data-switch]") : null;
    if (!a || e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) { return; }
    var k = a.getAttribute("data-switch");
    save(k);
    // Stay and filter only on a list page that has rows of that body; anywhere else the link goes to the body's hub.
    if (here) { return; }
    var items = tagged(), has = false;
    for (var i = 0; i < items.length; i++) { if (items[i].getAttribute("data-body") === k) { has = true; break; } }
    if (live() ? (k === ALL || liveHas(k)) : (items.length && (k === ALL || has))) {
      e.preventDefault();
      pick(k);
    }
  });
})();
