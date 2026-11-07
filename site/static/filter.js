/* Type and year filter for the official history table. Vanilla JS, no dependencies.
   Without JavaScript the form stays hidden and the full table is shown. */
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
    var t = typeSel.value, y = yearSel.value, shown = 0;
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
    }
  }
  typeSel.addEventListener("change", apply);
  yearSel.addEventListener("change", apply);
})();
