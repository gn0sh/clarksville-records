# Security review: correction intake + public surface + repo history (at 0282c9d), 2026-11-09
Verdict: PASS WITH FINDINGS (no critical/high). Repo safe to make public: YES (full history scanned: no secrets; data/store never committed).
1. MEDIUM csv-export/formula-injection, collector/export.py:212-218 `_csv()` (also fin_export.py:269-271): text cells starting with = + - @ TAB CR are not neutralised. Nothing exploitable today, but bidder names are chosen by bidders.
2. LOW report-frag/text-spoof, static/report.js:8,10,63-67: any well-formed made-up path or id is shown as "This report is about"; label it as unchecked or validate it against the built pages.
3. LOW hash-decode/finance-uncaught, static/finance.js:11: decodeURIComponent without try/catch; a malformed hash breaks the capital filters.
4. LOW nav-report/regex-overmatch, static/nav.js:59: off-site links ending in /report.html would get the fragment; rewrite same-origin links only.
5. INFO corr-config/repo-dot accepts "o/.". 6. INFO the CSP meta cannot set frame-ancestors; acceptable for a static site with no state changes. 7. INFO a public correction email draws spam; create the `correction` label; CLAUDE.md and docs/status.md would become public (private claude.ai links, API spend notes: not secrets).
Checked: report.js/nav.js against 13 hostile fragments in Playwright, config validation with 10 hostile values, CSP on 430 pages with and without the geocoder, injection through titles, names and search, 68,712 external links, all 28 export files, full history secret scan (323 commits).
