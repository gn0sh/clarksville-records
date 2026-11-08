# ADR 0002: Finance and contracts data: a second facts file, three config-driven adapters, rounding-aware checks

Status: accepted (architect, 2026-11-08); point 4 needs the manager's or PM's sign-off because it reads AC-F2.
Architecture: `docs/architecture/finance-contracts.md`. Builds on ADR 0001 (one committed facts file, static site).

## Context
Slice 1a shows every solicitation in the county purchasing archive with its documents, and bidders, totals and
awardee from text bid tabs only. Slice 1b shows budget lines from two budget books with every subtotal checked. Named
companies and named departments are on the page, so a wrong figure is the harm (Brain Trust 2026-11-08). The real
FY2027 book shows rounded actuals, totals printed with no lines, sign slips in derived columns and summary pages that
disagree with detail pages (architecture section 9).

## Decision
1. **A second committed facts file, `data/finance.json`** with `schema/finance.schema.json`, beside `facts.json`. It
   shares the source store, manifest, `src-<sha12>` ids and the change log. The votes contract stays untouched, and a
   finance parser change makes no diff in the votes facts.
2. **One adapter per source (archive HTML, bid-tab PDF, budget-book PDF), driven by `config/localities/<locality>/
   finance.yml`.** URLs, stage-label rules, status words, field labels, page titles, row-role labels, tag rules, column
   kind words and the capital fund number all live in that file. Code holds no locality literal (AC-F12).
3. **Deterministic parsing on word positions** from `pdftotext -bbox` (poppler, already required): columns are bands
   from the printed header, so a blank cell stays blank instead of shifting values left. No LLM per page or document.
   Anything the rules do not match is held back as Not confirmed*, or the run fails loudly on a changed structure.
4. **Reconciliation has three outcomes: `exact`, `within_rounding`, `does_not_add_up`.** `within_rounding` means
   |sum - printed| <= floor((n+1)/2) dollars over n detail lines, because the book prints every line rounded to the
   dollar. A strict check flags 99 of 515 FY2027 totals on rounding alone, which would read as county error. The exact
   sum and diff are always stored and exported, so the strict reading is still visible.
5. **Only detail statement pages are read** (plus the fund-balance block of each consolidated page, tagged
   `available_funds`). Synopsis, consolidated summary lines and charts are linked, never read, so one book never shows
   two figures for one thing. Difference and percent columns are never stored or shown.
6. **Positional ids**: budget lines `<book_id>/p<page>/r<index>` (a book is a fixed edition), documents by URL hash,
   solicitations by title slug. Lines from different books are never merged; an exact key match with different dollars
   is marked on both lines.
7. **Link-only by construction**: a scanned document, a non-PDF file, a Bonfire link or a URL that more than one row
   shares yields no value; a build check fails on any value whose source has no text layer.
8. **File budget**: one page per solicitation (about 90), department sections as anchors in a fund page, about 270 site
   files in all (ADR 0001's 250 rises to 400, still under the 511-file artifact limit).

## Alternatives considered
- **Extend `facts.json`.** One file is simpler for sitegen, but it couples two milestones' schemas and makes every
  finance re-parse a votes diff that reviewers must read. Rejected.
- **Strict "to the printed dollar" only.** Matches the spec text, but marks about 1 in 5 totals "does not add up" from
  rounding the county did correctly; on named departments that reads as a pattern (the risk AC-F16 exists to stop).
  Kept as stored data, not as the shown state.
- **Read the consolidated summary pages too.** They give the function categories, but in the FY2027 book they print
  different FY2025 figures from the detail pages for the same lines. Deferred; can come later as a cross-check report.
- **`pdftotext -layout` plus regex** (the votes parser's approach). Works for most rows but blank cells silently shift
  amounts into the wrong year (seen on p. 103). Rejected for amounts; fine for bid-tab labels.
- **pdfplumber.** Good tables, but a new runtime dependency for what `-bbox` already gives. Rejected.
- **OCR award letters now.** Out of scope by the Brain Trust decision (AC-F5).

## Consequences
- AC-F2's "to the printed dollar" is met as stored data, and the page shows "within rounding" in its own words; UX
  needs one more fixed string. If the manager prefers strict display, it is a one-line view change.
- Department on solicitations comes only from text bid tabs, so the parity report has a large "not stated" bucket.
- A new locality is a new `finance.yml` plus fixtures; layouts that differ need new rules, not new adapters.
- Expensive to reverse: the finance schema and id scheme. Recommend a delta review of the schema by the code-reviewer
  once slice 1a's real run output exists, rather than a panel.

## Amendment 2026-11-08: a book's own column kinds
The column kind comes from the header's words (`kind_words`), but one word can mean different things in different
books. The approved FY2024-25 book prints its budget-year column as "FY 25 Projection": in an approved book that column
is the adopted FY2025 budget. The FY2027 approved book's "FY 2026 Projections" is an estimate of the year in progress
and stays `projected`. Decision (manager, from review 1b finding 4, column-kind/budget-year-kind): a book in
`finance.yml` may list `kind_overrides` (header as printed -> kind); FY2025 "FY 25 Projection" is `adopted`. The header
is still stored and shown as printed. An override that matches no header in its book fails the book, so a re-printed
header cannot silently drop it. Alternative rejected: a global rule "Projection in an approved edition = adopted",
which would also turn FY2027's "FY 2026 Projections" into an adopted budget.

Same review (nit 7, budget-reconcile/rounding-n-counts-dashes): the rounding bound's n is counted per column over
the scope lines with a printed amount there; a "-" (an exact 0) and a blank cell no longer widen it. No check in
either book changed state.
