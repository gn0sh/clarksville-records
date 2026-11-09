/* Report an error (M1.5, docs/design/correction-intake.md). First-party, vanilla, no network calls, no storage.
   Reads this page's #fragment (page=<site path>&id=<fact id>, set by static/nav.js on the link the reader followed),
   keeps a value only when it matches a strict pattern, shows it with textContent (never innerHTML), and adds it,
   URL-encoded, to the GitHub issue and mailto links the page already has. Anything else in the fragment is dropped. */
(function () {
  "use strict";
  // A site path: letters, digits, '_', '-', '/' segments, ending .html; no '..', no '//', no scheme, no leading '/'.
  var PAGE_RE = /^(?!.*\.\.)(?!.*\/\/)[A-Za-z0-9][A-Za-z0-9_\/-]{0,200}\.html$/;
  // A fact or record id as the site prints them (e.g. rc-2024-01-08-3/o-smith, 2024-01-08/att/o-smith).
  var ID_RE = /^[A-Za-z0-9][A-Za-z0-9_.:\/-]{0,159}$/;
  // encodeURIComponent, plus the five characters it leaves as they are (RFC 3986 strict), so no quote survives.
  function enc(s) {
    return encodeURIComponent(s).replace(/[!'()*]/g, function (c) {
      return "%" + c.charCodeAt(0).toString(16).toUpperCase();
    });
  }

  function parseHash(hash) {
    var out = {};
    String(hash || "").replace(/^#/, "").split("&").forEach(function (kv) {
      var i = kv.indexOf("=");
      if (i < 1) { return; }
      var key = kv.slice(0, i), value;
      try { value = decodeURIComponent(kv.slice(i + 1)); } catch (e) { return; }
      if (key === "page" && PAGE_RE.test(value)) { out.page = value; }
      if (key === "id" && ID_RE.test(value)) { out.id = value; }
    });
    return out;
  }

  // pageUrl: the absolute address of `page` (only on an http(s) site, so a local file path is never put in a report).
  function links(params, pageUrl, issueBase, mailBase) {
    var title = "Correction: " + (params.id || params.page || "");
    var body = "Page: " + (pageUrl || "") + "\nFact id: " + (params.id || "") +
      "\n\nWhat the page shows:\n\nWhat the source document says (link and page number):\n";
    var issue = "", mail = "";
    if (issueBase && issueBase.indexOf("https://github.com/") === 0) {
      issue = issueBase + "&title=" + enc(title) + (pageUrl ? "&page_url=" + enc(pageUrl) : "") +
        (params.id ? "&fact_id=" + enc(params.id) : "");
    }
    if (mailBase && mailBase.indexOf("mailto:") === 0 && mailBase.indexOf("?") < 0) {
      mail = mailBase + "?subject=" + enc(title) + "&body=" + enc(body);
    }
    return { issue: issue, mail: mail };
  }

  // "known" when `page` is one of `list` (the built page paths static/pages.js carries), "unknown" when the list is
  // there and it is not, "unchecked" when there is no list. Only "known" may be shown without a warning.
  function pageStatus(page, list) {
    if (!page) { return "none"; }
    if (!Array.isArray(list)) { return "unchecked"; }
    return list.indexOf(page) >= 0 ? "known" : "unknown";
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { parseHash: parseHash, links: links, pageStatus: pageStatus, PAGE_RE: PAGE_RE, ID_RE: ID_RE };
  }
  if (typeof document === "undefined") { return; }

  var params = parseHash(window.location.hash);
  // Nothing in the link is a fact: the page path is checked against the list of built pages, the id cannot be.
  var status = pageStatus(params.page, window.BUILT_PAGES);
  var pageUrl = "";
  if (status === "known" && /^https?:$/.test(window.location.protocol)) {
    try { pageUrl = new URL(params.page, window.location.href).href; } catch (e) { pageUrl = ""; }
  }
  var linkParams = { page: status === "known" ? params.page : undefined, id: params.id };
  var issueA = document.getElementById("report-issue");
  var mailA = document.getElementById("report-mail");
  var got = links(linkParams, pageUrl, issueA && issueA.getAttribute("href"), mailA && mailA.getAttribute("href"));
  if (issueA && got.issue) { issueA.setAttribute("href", got.issue); }
  if (mailA && got.mail) { mailA.setAttribute("href", got.mail); }

  var box = document.getElementById("report-about");
  if (box && (params.page || params.id)) {
    var pageText = pageUrl || params.page || "Not given";
    if (status === "unknown") { pageText += " (not a page of this site)"; }
    if (status === "unchecked") { pageText += " (not checked)"; }
    document.getElementById("report-page-url").textContent = pageText;
    document.getElementById("report-fact-id").textContent = params.id || "Not given";
    box.hidden = false;
  }
})();
