/* Bids and awards index (docs/design/finance-contracts.md 4). Filters, order and paging over the rows already in
   the page; first-party, no network. The choices live in the address (history.replaceState), like search, so a view
   can be shared; nothing about the visitor is stored. Order is by date or by name only, never by an amount.
   Without this script the form stays hidden and every row shows. */
(function () {
  var form = document.getElementById("sol-filters");
  var table = document.getElementById("sol-table");
  if (!form || !table) { return; }
  var tbody = table.tBodies[0];
  var rows = Array.prototype.slice.call(tbody.rows);
  var countEl = document.getElementById("sol-count");
  var noneEl = document.getElementById("sol-none");
  var moreBtn = document.getElementById("sol-more");
  var PAGE = +table.getAttribute("data-page") || 25;
  var KEYS = ["q", "dept", "year", "docs", "order"];
  var shown = PAGE;
  rows.forEach(function (r, i) { r._i = i; });
  form.hidden = false;

  function readURL() {
    var p = new URLSearchParams(location.search), st = {};
    KEYS.forEach(function (k) { st[k] = p.get(k) || ""; });
    st.order = st.order || "new";
    return st;
  }
  function writeURL(st) {
    var p = new URLSearchParams();
    KEYS.forEach(function (k) { if (st[k] && !(k === "order" && st[k] === "new")) { p.set(k, st[k]); } });
    var qs = p.toString();
    history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
  }
  function toControls(st) {
    form.q.value = st.q;
    ["dept", "year", "docs", "order"].forEach(function (k) {
      var el = form[k];
      el.value = st[k];
      if (el.value !== st[k]) { el.value = k === "order" ? "new" : ""; }  // an unknown value in the address
    });
  }
  function fromControls() {
    return { q: form.q.value.trim(), dept: form.dept.value, year: form.year.value, docs: form.docs.value,
             order: form.order.value || "new" };
  }
  function byText(attr) {
    return function (a, b) {
      var x = a.getAttribute(attr).toLowerCase(), y = b.getAttribute(attr).toLowerCase();
      return x < y ? -1 : x > y ? 1 : a._i - b._i;
    };
  }
  function byDate(dir) {  // rows without a date go last, in page order
    return function (a, b) {
      var x = a.getAttribute("data-date"), y = b.getAttribute("data-date");
      if (!x || !y) { return (!x) - (!y) || a._i - b._i; }
      return x === y ? a._i - b._i : (x < y ? -dir : dir);
    };
  }
  var ORDERS = { "new": byDate(-1), old: byDate(1), title: byText("data-title"), dept: byText("data-dept") };

  function apply(keepPage) {
    var st = fromControls();
    writeURL(st);
    if (!keepPage) { shown = PAGE; }
    var toks = st.q.toLowerCase().split(/\s+/).filter(Boolean);
    var hits = rows.filter(function (r) {
      if (st.dept && r.getAttribute("data-dept") !== st.dept) { return false; }
      if (st.year && r.getAttribute("data-year") !== st.year) { return false; }
      if (st.docs && r.getAttribute("data-tab") !== st.docs) { return false; }
      var hay = r.getAttribute("data-search");
      for (var i = 0; i < toks.length; i++) { if (hay.indexOf(toks[i]) < 0) { return false; } }
      return true;
    });
    hits.sort(ORDERS[st.order] || ORDERS["new"]);
    rows.forEach(function (r) { r.hidden = true; });
    hits.forEach(function (r, i) { tbody.appendChild(r); r.hidden = i >= shown; });
    var n = Math.min(shown, hits.length);
    countEl.textContent = hits.length ? "Showing " + n + " of " + hits.length +
      (hits.length === 1 ? " solicitation." : " solicitations.") : "";
    noneEl.hidden = hits.length > 0;
    table.parentNode.hidden = hits.length === 0;
    moreBtn.hidden = hits.length <= shown;
  }
  function clear() {
    var st = { q: "", dept: "", year: "", docs: "", order: "new" };
    toControls(st);
    apply();
  }

  toControls(readURL());
  form.addEventListener("submit", function (e) { e.preventDefault(); apply(); });
  ["dept", "year", "docs", "order"].forEach(function (k) {
    form[k].addEventListener("change", function () { apply(); });
  });
  document.getElementById("f-clear").addEventListener("click", clear);
  document.getElementById("sol-none-clear").addEventListener("click", function () { clear(); form.q.focus(); });
  moreBtn.addEventListener("click", function () { shown += PAGE; apply(true); });  // focus stays on the button
  apply();
})();
