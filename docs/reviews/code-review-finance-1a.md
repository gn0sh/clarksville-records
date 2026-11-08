# Code review: slice 1a Bids and awards (e809572, base 04f5a6c), opus/high

Verdict: REQUEST CHANGES (1 must-fix, 5 should-fix, 5 nits). Tests 983 passed. Spot check 5 read tabs: all match; scripted check of all 80 bidders in 16 read tabs: every name and total found in the PDF text.

Must-fix
1. config/finance_text.yml:6 coverage-count/fixed-claim-not-from-count: "award letters are scans" is false (42 of 70). Build from counts; exact-string test.
Should-fix
2. finance_text.yml:58, fin_facts.py:195 award-source/not-read-reason-misstated: layout sentence "lists prices by item" false for several tabs; dead/link-only mapped to layout.
3. fin_facts.py:169 scan-values/ocr-not-marked-scanned: scanned only when text_layer == none; OCR letters lack the chip. Use text_layer != "text".
4. fin_contracts_index.html.j2:63 award-source/index-drops-match-state: index awardee cell omits state.
5. fin_facts.py:218-226 award-source/award-letter-check-missing: AC-F4 award-letter agreement not implemented (26 text letters).
6. fin_contracts_index.html.j2:71 provenance/dead-export-link: export links before F8.
Nits
7. fin_bidtab.py:196 Notes column words dropped; treat non-empty Notes as not_read.
8. fin_bidtab.py:210 no NAME_GAP adjacency check in table layout.
9. fin_facts.py:150 doc-completeness/label-not-verbatim: shared URL label from first row.
10. fin_archive.py:93 restrict href schemes to http(s).
11. fin_views.py:194 `awardee_page or 1` hides a missing page.

Checked and sound: scan guard (read + build), shared URLs link-only, held totals, robots/Bonfire/403 handling, 316 links -> 295 documents, printed order, no cross-solicitation sums, banned-words lint, no locality literals, autoescape, determinism.

Manager decision: finding 5 deferred to slice 1a.2 (reading text award letters is new extraction); recorded in the spec and status.
