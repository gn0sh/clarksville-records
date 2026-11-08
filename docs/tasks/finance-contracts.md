# Tasks: finance-contracts (slice 1a bids and awards, then slice 1b budget books)

Architecture: `docs/architecture/finance-contracts.md` (sections cited as A2, A3...). ADR: `docs/adr/0002-finance-contracts-data.md`.
Design: `docs/design/finance-contracts.md`. Contract: `schema/finance.schema.json` (written in F0; the file wins over
any summary). Tests in session, `python -m pytest -q`, output pasted in each PR (no Actions minutes until Dec 1).
Every task ships with its tests; "done" = tests green, ruff clean, no new locality literal in code (AC-F12).
Review cut: one PR per group below, each under about 1,000 changed source lines (tests and fixtures excluded).

## Slice 1a: bids and awards
**PR 1a-A, collector base (backend-engineer), about 450 lines**
- F0. `schema/finance.schema.json` (A3, full field list and enums) + `site/fixtures/finance.sample.json` (FIXTURE,
  made-up vendors on `example.invalid`: a lump-sum tab, an awardee that is not a listed bidder, a scanned award letter,
  a shared URL, a held value, budget lines covering exact / within_rounding / does_not_add_up). Test: fixture validates.
  Deps: none. Unblocks F6-F8 at once (frontend builds on the fixture).
- F1. `config/localities/montgomery-tn/finance.yml` (archive URL, stage rules, status words, date formats, bid-tab
  labels, Bonfire hosts; budget keys may stay empty until F9) + loader with validation. Test: missing key fails loudly.
- F2. Fetcher and store: Bonfire hosts hard-denied (test: never requested); `store.put`/`fetch_into_store` accept
  `expect="html"` for the archive page and record `not_pdf` without storing for `.docx` links. Tests with the fake
  transport: CONNECT refusal vs site 403 still distinguished on the new hosts (AC-F11).
- F3. `collector/fin_archive.py` (A2 adapter 1). Fixture: trimmed real archive HTML (10 rows: every label form, every
  status word, "F EBRUARY", "OCTOBER 14. 2026", an empty date, a shared URL, a .docx). Tests: header change raises
  `StructureChanged`; link count per row = documents produced (AC-F7); stage per label; date repairs only the two rules.
- F4. `collector/pdfwords.py`: `pdftotext -bbox` words and lines (A1). Test on the bid-tab and p. 36 fixtures:
  line grouping, right edges stable to 1 pt.

**PR 1a-B, bid tabs and checks (backend-engineer), about 450 lines**
- F5. `collector/fin_bidtab.py` (A2 adapter 2) and the scan guard in `fin_checks.py`. Regression test on the real
  wheel-loader tab: 2 bidders in printed order, "McCoy Construction & Forestry" joined from two lines, $189,000.00 =
  18900000 cents, awardee "McCoy Construction &Forestry" matches bidder 1, award date text "2-26-25". Tests: an
  itemised layout gives `not_read`; a bad amount token holds the value; a scan yields no value; a `shared_by`
  document yields no value; property test: no value cites a non-`text` source (scan-values/*).
- F5b. Before widening F5: after the first real fetch, `python -m collector fin census` prints each bid tab's layout
  class (lump_sum / not_read / scan) and the award-letter scan count. Paste it in the PR; it sets the coverage numbers.
- F5c. `fin_checks.coverage()` and parity (A5), `fin_facts.py` (sorted, stable ids, two runs byte-identical), report
  block, `python -m collector fin {fetch,build,census}`. Tests: parity flags a 5-row department at 0.4x; "not stated"
  bucket reported; determinism.

**PR 1a-C, pages (frontend-engineer), about 600 lines, can start after F0 on the fixture**
- F6. `sitegen/fin_views.py` + `fin_contracts_index`, `fin_solicitation`, `glossary` templates, `config/finance_text.yml`
  (design 2-5). Tests: coverage sentence exact string from `coverage` (AC-F15); skeleton equality of two solicitations
  (N1); bidders in printed order, no amount sort (lint, AC-F8); every amount, name and date has a source link and
  fetch date (AC-F3); "Scanned, read it yourself" on scans and no value; documents-differ and not-a-listed-bidder
  states; banned-words lint skips only `finance_text.yml` and glossary.
- F7. Search index type `sol` (title, department, every bidder name) and the index filter toolbar (GET, URL state).
  Test: a bidder name finds its solicitation.
- F8. Export tables `solicitations.csv`, `fin_documents.csv`, `bidders.csv`, `finance.json` with source columns (A6).
  Test: every row has `source_url`, `page`, `fetched_at`; held values are null with the check name. Owner: backend.
- F8b. Remove the "coming" slot for Bids and awards; nav order per design 1; `qa/site_checks.py` row-height and
  no-horizontal-scroll at 360 px on the new pages (AC-F10).

**1a gate (manager):** QA hand-labels at least 10 solicitations in `collector/fin_hand_labels.json` (AC-F6) and runs
the 30-value spot check slice for bid tabs (AC-F1); parity report reviewed (AC-F16); Brian's done-test and AC-F17 go
in his next batched device check.

## Slice 1b: budget books and capital fund
**PR 1b-A, budget adapter and checks (backend-engineer, opus/high: data integrity), about 700 lines**
- F9. Layout check of the FY2024-25 book (A9 risk 10): run `pdfwords` on its statement pages, record page titles,
  header words and column kinds in `finance.yml` and `docs/platform-facts.md`. No parser change until this is done.
- F10. `collector/fin_budget.py` (A2 adapter 3): page roles, fund carry-over, column bands, kinds, row roles and
  scopes, tags. Regression tests on fixtures: p. 33 (section totals), pp. 36-37 (Salaries & Benefits as a codeless
  detail, Other and Capital Expenditures subtotals across a page break), p. 105 (header "FY 2025 Actuals" on one line),
  a blank cell stays null (synthetic line modelled on p. 103), pp. 107-108 (projects with no heading; truncated, repeated total labels), p. 28 (only
  the fund-balance block read, fund from the next statement page), p. 114 (transfers tagged). Unknown kind word fails.
- F11. Reconciliation in `fin_checks.py` (A4 budget-reconcile/*). Tests: p. 36 County Commission exact; p. 37 County
  Mayor within_rounding (diff 1, n 20); p. 107 PUBLIC ART total with no lines does_not_add_up; p. 47 Trustee's office
  amended does_not_add_up (diff 3,900); property test: each detail line in exactly one scope per level; no sum of lines
  outside `fin_checks.py` (lint). Run report counts exact / within_rounding / does_not_add_up.
- F12. Edition compare across books (budget-edition/*). Test: same key, different dollars, both lines marked, neither
  changed.

**PR 1b-B, finance pages (frontend-engineer), about 600 lines, can start after F0 on the fixture**
- F13. `finance/index.html`, `finance/<fund_no>.html` (revenue, spending by department as anchors, transfers and
  available funds), column headers = header as printed + kind (design 6). Tests: no difference or percent column, no
  arrow or sparkline (lint); subtotal states in words incl. "within rounding"; tagged lines listed under their checks
  even when moved; edition note; whole dollars with parentheses kept; committee names link (AC-F9).
- F14. `capital/index.html` from `capital_fund` (design 7, Note D). Test: no total across lines, no cost column.
- F15. Export `budget_lines.csv` and `budget_checks.csv` (A6). Owner: backend. Test: one row per cell with source.

**1b gate (manager):** QA spot check of 10 budget and 5 cross-book amounts (AC-F1); reconcile counts reviewed;
Brian's 1b done-test batched.

## Order and parallelism
F0 first (backend, short). Then in parallel: backend F1-F5c, frontend F6-F7 on the fixture. F8, F8b after F5c.
Slice 1b: F9 before F10; F10 then F11, F12; frontend F13-F14 on the fixture in parallel; F15 last.
