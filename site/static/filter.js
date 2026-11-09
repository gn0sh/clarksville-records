/* Dropdown menus: Escape or a click outside closes any open nav/year menu. Then the history filter (official pages). Vanilla JS, no dependencies.
   Without JavaScript the form stays hidden and the full table is shown. */
(function () {
  var menus = document.querySelectorAll("details.menu");
  function closeMenus(except) {
    for (var i = 0; i < menus.length; i++) { if (menus[i] !== except) { menus[i].open = false; } }
  }
  if (menus.length) {
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") { return; }
      for (var i = 0; i < menus.length; i++) {
        if (menus[i].open) { menus[i].open = false; menus[i].querySelector("summary").focus(); break; }
      }
    });
    document.addEventListener("click", function (e) {
      var inside = e.target.closest ? e.target.closest("details.menu") : null;
      closeMenus(inside);
    });
  }
})();
(function () {
  var form = document.getElementById("filters");
  var table = document.getElementById("history");
  if (!form || !table) { return; }
  var typeSel = document.getElementById("filter-type");
  var yearSel = document.getElementById("filter-year");
  var none = document.getElementById("no-match");
  var rows = table.querySelectorAll("tbody tr[data-type]");
  form.hidden = false;
  form.addEventListener("submit", function (e) { e.preventDefault(); });

  function apply() {
    var t = typeSel.value, y = yearSel ? yearSel.value : "", shown = 0;  // a one-year page has no year filter
    for (var i = 0; i < rows.length; i++) {
      var ok = (!t || rows[i].dataset.type === t) && (!y || rows[i].dataset.year === y);
      rows[i].hidden = !ok;
      if (ok) { shown++; }
    }
    none.hidden = !(rows.length > 0 && shown === 0);
    // Year groups (<details>): hide a group with no matching rows; open the group when a year is chosen.
    var groups = table.querySelectorAll("details.year-group");
    for (var g = 0; g < groups.length; g++) {
      var any = groups[g].querySelector("tbody tr:not([hidden])");
      groups[g].hidden = !any;
      if (y && any) { groups[g].open = true; }
      else if (!y && !t) { groups[g].open = (g === 0); }  // filter cleared: back to newest year open
    }
  }
  typeSel.addEventListener("change", apply);
  if (yearSel) { yearSel.addEventListener("change", apply); }
})();
