/* Finance and capital projects pages (docs/design/finance-contracts.md 6-7). First-party, no network, nothing stored.
   1. Each heading's lines sit in a <details>, open in the page. On a phone (640 px or less) they start closed, so
      the page is a short list of headings; the one a link points at (#anchor) is opened.
   2. Capital projects: "Project name" and "Book" filters over the headings already in the page, kept in the
      address like search. Without this script every heading is open and every line shows. */
(function () {
  var groups = Array.prototype.slice.call(document.querySelectorAll("details.fin-group"));
  if (!groups.length) { return; }

  function openTarget() {
    var id;
    try { id = decodeURIComponent(location.hash.slice(1)); } catch (e) { return; }   // a malformed hash is ignored
    var el = id && document.getElementById(id);
    for (var n = el; n; n = n.parentElement) {
      if (n.tagName === "DETAILS") { n.open = true; }
    }
    if (el && el.scrollIntoView) { el.scrollIntoView(); }
  }
  if (window.matchMedia && window.matchMedia("(max-width: 640px)").matches) {
    groups.forEach(function (d) { d.open = false; });
  }
  if (location.hash) { openTarget(); }
  window.addEventListener("hashchange", openTarget);

  var form = document.getElementById("cap-filters");
  if (!form) { return; }
  var q = document.getElementById("f-name"), book = document.getElementById("f-book");
  var none = document.getElementById("cap-none");
  var books = Array.prototype.slice.call(document.querySelectorAll("section.fin-book[data-book]"));
  form.hidden = false;

  function apply(write) {
    var text = q.value.trim().toLowerCase(), b = book.value, shown = 0;
    books.forEach(function (s) {
      var inBook = !b || s.getAttribute("data-book") === b;
      s.hidden = !inBook;
      s.querySelectorAll("details.fin-group").forEach(function (d) {
        var hit = inBook && (!text || d.getAttribute("data-search").indexOf(text) !== -1);
        d.hidden = !hit;
        if (hit) { shown++; if (text) { d.open = true; } }
      });
    });
    none.hidden = shown > 0;
    if (write) {
      var p = new URLSearchParams();
      if (q.value.trim()) { p.set("q", q.value.trim()); }
      if (b) { p.set("book", b); }
      var qs = p.toString();
      history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
    }
  }
  var params = new URLSearchParams(location.search);
  q.value = params.get("q") || "";
  book.value = params.get("book") || "";
  if (book.selectedIndex < 0) { book.value = ""; }
  form.addEventListener("submit", function (e) { e.preventDefault(); apply(true); });
  q.addEventListener("change", function () { apply(true); });
  q.addEventListener("search", function () { apply(true); });
  book.addEventListener("change", function () { apply(true); });
  document.getElementById("f-clear").addEventListener("click", function () {
    q.value = ""; book.value = ""; apply(true); q.focus();
  });
  if (q.value || book.value) { apply(false); }
})();
