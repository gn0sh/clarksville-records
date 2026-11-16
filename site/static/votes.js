/* An official's vote list (official_votes.html.j2): filter the rows by vote, and download exactly the rows shown as CSV.
   Vanilla JS, no dependencies. Without JavaScript the form stays hidden and every row is shown.
   ?vote=yes (no, abstain, other, absent) preselects a filter: the official page links each option that way. */
(function () {
  var form = document.getElementById("vote-filter");
  var table = document.getElementById("vote-table");
  if (!form || !table) { return; }
  var rows = table.querySelectorAll("tbody tr[data-vote]");
  var status = document.getElementById("vote-status");
  var button = document.getElementById("vote-csv");
  var radios = form.querySelectorAll("input[name=vote]");
  form.hidden = false;
  form.addEventListener("submit", function (e) { e.preventDefault(); });

  function chosen() {
    for (var i = 0; i < radios.length; i++) { if (radios[i].checked) { return radios[i]; } }
    return radios[0];
  }
  function labelOf(r) { return r.parentNode.textContent.replace(/\s*\(\d+\)\s*$/, "").trim(); }

  function apply(announce) {
    var r = chosen(), v = r.value, shown = 0;
    for (var i = 0; i < rows.length; i++) {
      var ok = !v || rows[i].getAttribute("data-vote") === v;
      rows[i].hidden = !ok;
      if (ok) { shown++; }
    }
    button.disabled = shown === 0;
    // the other pages of a long list (by year) keep the chosen vote
    var parts = document.querySelectorAll(".vote-parts a");
    for (var p = 0; p < parts.length; p++) {
      parts[p].search = v ? "?vote=" + encodeURIComponent(v) : "";
    }
    if (announce) {
      status.textContent = shown === 0 ? "No votes of this kind are listed."
        : "Showing " + shown + " of " + rows.length + (v ? " votes: " + labelOf(r) + "." : " votes.");
    }
  }

  function cell(s) {
    s = String(s == null ? "" : s).replace(/\s+/g, " ").trim();
    if (/^[=+\-@]/.test(s)) { s = "'" + s; }   // never a formula in a spreadsheet
    return '"' + s.replace(/"/g, '""') + '"';
  }

  button.addEventListener("click", function () {
    var lines = [["date", "item", "vote_on", "vote", "record_page", "source"].join(",")];
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      if (row.hidden) { continue; }
      var c = row.cells, src = c[3].querySelector("a"), title = c[1].cloneNode(true);
      var small = title.querySelector("small");
      var on = small ? small.textContent.replace(/^Vote on:\s*/, "").replace(/\.$/, "") : "";
      if (small) { small.remove(); }
      var meeting = c[0].querySelector("a") || c[1].querySelector("a");
      lines.push([row.getAttribute("data-date"), title.textContent, on, c[2].textContent,
                  meeting ? meeting.href : "", src ? src.href : ""].map(cell).join(","));
    }
    var v = chosen().value || "all";
    var blob = new Blob([lines.join("\r\n") + "\r\n"], { type: "text/csv;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = (button.getAttribute("data-name") || "votes") + "-" + v + ".csv";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 0);
  });

  for (var i = 0; i < radios.length; i++) { radios[i].addEventListener("change", function () { apply(true); }); }
  var want = (new URLSearchParams(location.search)).get("vote");
  for (var j = 0; j < radios.length; j++) { if (want && radios[j].value === want) { radios[j].checked = true; } }
  apply(!!want);
})();
