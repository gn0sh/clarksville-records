/* Landing map (design 3.2): focusing or hovering a district in the list lights its shape on the map, and hovering a
   shape lights its list row, so keyboard users can see where a district is. First-party, no network calls. */
(function () {
  var rows = document.querySelectorAll(".districts li[data-district]");
  var shapes = document.querySelectorAll("#layer-districts a[data-district]");
  if (!rows.length || !shapes.length) { return; }
  function light(n, on) {
    var all = document.querySelectorAll('[data-district="' + n + '"]');
    for (var i = 0; i < all.length; i++) { all[i].classList.toggle("is-lit", on); }
  }
  function wire(el) {
    var n = el.getAttribute("data-district");
    ["mouseenter", "focusin"].forEach(function (t) { el.addEventListener(t, function () { light(n, true); }); });
    ["mouseleave", "focusout"].forEach(function (t) { el.addEventListener(t, function () { light(n, false); }); });
  }
  for (var i = 0; i < rows.length; i++) { wire(rows[i]); }
  for (var j = 0; j < shapes.length; j++) { wire(shapes[j]); }
})();
