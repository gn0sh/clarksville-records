# Architecture: finance-contracts (slice 1a bids and awards, slice 1b budget books and capital fund)

Status: v1, 2026-11-08. Owner: software-architect. Spec: `docs/specs/finance-contracts.md`. Design:
`docs/design/finance-contracts.md` (5f878fa). Decision: `docs/adr/0002-finance-contracts-data.md`. Tasks:
`docs/tasks/finance-contracts.md`. Parent: `docs/architecture/clarksville-records.md` (fetcher, store, sitegen, N1-N6
rules apply unchanged). Designed against real samples: FY2027 book, the archive page and one text bid tab (section 9).

## 1. Components
```
config/localities/<locality>/finance.yml   every URL, label, heading rule and word list below (AC-F12)
collector/pdfwords.py      `pdftotext -bbox` -> words {page, x0, x1, y0, y1, text}, grouped into lines (poppler, no new dep)
collector/fin_archive.py   adapter 1: purchasing-archive HTML -> solicitations + documents
collector/fin_bidtab.py    adapter 2: text bid-tab PDF -> bid tab fields + bidders
collector/fin_budget.py    adapter 3: budget-book PDF -> budget lines with row roles, scopes, tags
collector/fin_checks.py    subtotal reconciliation, awardee match, scan guard, edition compare, coverage + parity
collector/fin_facts.py     assembles data/finance.json (sorted keys, stable ids, no-op run = no diff)
collector/export.py        + finance tables (section 6)
sitegen/fin_views.py       one view builder per finance page type; templates site/templates/fin_*.html.j2
schema/finance.schema.json the collector -> sitegen contract (section 3)
```
CLI: `python -m collector fin {fetch,build}`; `run` calls both after the votes steps. Every rule is deterministic code
plus config. No LLM call per page or per document, ever; a layout the rules do not match fails loudly or holds the
value back as Not confirmed*.

## 2. Adapters and fetch politeness
All requests go through the existing `PoliteFetcher` (robots, 10 s floor, allowlist, `HostBlocked` vs `ProxyRefused`).
`finance.yml` adds `bonfire_hosts` (e.g. `mcgtn.bonfirehub.com`), which the fetcher hard-denies like `dev2`: Bonfire
links are kept as link-only documents and never requested (test). First full run is about 315 documents x 10 s,
roughly 55 minutes; later runs fetch only new URLs (store cache).

**Adapter 1, purchasing archive** (`archive_url` in config). The page is one `<table>`; cells are `<th>`, not `<td>`.
Row 1 is the header (Bid Name | Bid Documents | Award Date), checked by exact text: a changed header, a row without 3
cells, or zero rows raises `StructureChanged` (AC-F11). Per row: `title` (verbatim), `archive_date_text` (verbatim)
parsed by `date_formats` with two mechanical repairs only (spaces inside a month word, "." for ","); text in
`status_words` ("Currently Under Review", "No Award", "NOT AWARDED", "UNDER REVIEW") becomes `archive_status`, anything
else `date_unparsed`. Each `<a>`: `link_label` verbatim, absolute URL, `stage` from `stage_rules` (ordered regex on the
label, case-insensitive: bid tab, award letter, partial award, notice of intent, notice of award, bid, RFP, RFQ,
addendum, Q&A, forms, advertisement, drawings, other). The archive HTML itself is stored as a source (kind
`archive_index`, `store.put` with `expect="html"`) so every row cites the archive page and its fetch date.

**Adapter 2, bid tab** (documents with stage `bid_tab` and a text layer). Field labels from `bidtab.fields`
("Bid Project", "Department", "Bid Date", "Bid Awarded to", "Date Bid Awarded"); value = words after the label on the
same line with `_` fill removed. Bidder table: header line with `Bidder Name` and `Total`; column bands from header
word x-positions. A line with words in the name band and one amount in the Total band starts a bidder; following lines
with name-band words and no amount continue its name (real case: "McCoy Construction &" / "Forestry"). Amount must
match `^\$?\d{1,3}(,\d{3})*(\.\d{2})?$`, kept as text plus integer cents. `tab_type`: `lump_sum` when the table has
exactly these columns and every bidder has one amount; anything else `not_read` (link only, counted in coverage).

**Adapter 3, budget book** (`books[]`: id, title, edition, fiscal year, URL, page range). Page role by exact title
line from `budget.page_titles`: revenue statement, expenditure statement, consolidated (fund-balance block only), or
skipped (synopsis, charts, summaries are linked as pages, never read). Column bands from the header words (two header
lines joined per band). Each header becomes `{header_as_printed, fiscal_year, kind}` with kind from `kind_words`
(Actuals -> actual, Amended -> amended, Budget -> adopted in an approved edition, Projections -> projected); an unknown
word fails the book. "Budgeted Difference" and "Percent Change" are read only to locate bands and are never stored or
shown (no year-over-year values; they also carry book sign and rounding slips, see 9). A number whose right edge lies
in no band, two numbers in one band, or a non-amount token raises check `column-align`: the line is held back.
"-" is 0 as printed; a blank cell is `null` ("not printed").

**Row roles and scopes** (all positional; labels in config `budget.rows`):
- Fund line `^(?P<name>.+ FUND) (?P<no>\d{3})$` opens a fund and carries across pages until the next one. A consolidated
  page belongs to the fund on the next statement page.
- Heading: a line with no amounts opens a scope (revenue section or department/project). Capital projects often print
  no heading: the scope opens after the previous total, and `heading_as_printed` comes from the total's label minus
  "Total " (flag `heading_from_total`; labels are truncated and repeat, so they are never keys).
- `detail`: an account-coded row, or a codeless row not listed below (e.g. "Salaries & Benefits").
- `subtotal` (labels `Other Expenditures`, `Capital Expenditures`): scope = the coded rows directly above it, back to the
  previous non-coded row.
- `total` (`^Total `): scope = every detail row since the scope opened; `Total Revenues`, `Total Revenues <fund>` and
  `Total Expenditures <fund>` scope the whole fund. A detail row is in exactly one scope per level (no double counting).
- Tags (`budget.tags`, by section heading, department heading or account code): `transfer` (e.g. 49800, 55900,
  "OPERATING TRANSFERS"), `non_revenue` ("Other Sources (Non-Revenue)"), `available_funds` (consolidated rows matching
  `fund_balance_labels`). Tagged lines stay in book order and in their printed totals; the view moves them to their
  own table and the checks still list them.

## 3. Data contract: `data/finance.json` (schema `schema/finance.schema.json`)
Every fact names `source_id` (existing `src-<sha12>` sources, now with `kind` in archive_index | bid | rfp | bid_tab |
award_letter | notice | other | budget_book) and `page`; sources carry `url, sha256, fetched_at, pages, text_layer,
content_type, creator`.
- **solicitations**: `id` (`sol-<slug>`; on a slug collision `-<sha1(first doc url)[:6]>`), `slug`, `title`,
  `archive_date_text`, `archive_date` (ISO or null), `archive_status` (or null), `year` (from archive_date, else null),
  `department` {`text`, `source_id`, `page`} or null (bid tab "Department", else null: the archive prints none),
  `number` null in 1a (the archive prints none), `document_ids[]` in archive order, `bid_tab` {`document_id`,
  `tab_type`, `project_text`, `bid_date_text`, `awardee_text`, `awardee_page`, `award_date_text`, `awardee_match`
  (`bidder:<n>` | `none_named` | `not_a_listed_bidder` | `ambiguous`), `bidders[]` {`printed_order`, `name`,
  `total_as_printed`, `total_cents`, `page`}} or null, `documents_differ` {`fields[]`, `document_ids[]`} or null,
  `held[]` {`field`, `check`} (values held as Not confirmed*), `row` (archive row index), `archive_source_id`.
- **documents**: `id` (`doc-<sha1(url)[:10]>`), `url`, `link_label`, `stage`, `source_id` or null (not fetched:
  Bonfire, non-PDF, dead link), `status` (`fetched` | `not_pdf` | `link_only` | `dead_at_fetch`), `scanned` (bool;
  true when the source's `text_layer` is `none`, the existing enum), `doc_date_text` + `doc_date_page` (only a text
  document's own labelled date; else null), `shared_by` (other solicitation ids linking the same URL), `fetched_at`.
- **books**: `id` (e.g. `fy2027-approved`), `title`, `edition`, `fiscal_year`, `source_id`, `pages_read[]`, `columns[]`.
- **budget_lines**: `id` (`<book_id>/p<page>/r<line index>`), `book_id`, `edition`, `fund_no`, `fund_name`, `statement`
  (revenue | expenditure | fund_balance), `heading_as_printed`, `department` (expenditure heading or null),
  `account_code` or null, `label_as_printed`, `row_role` (detail | subtotal | total), `tags[]`, `cells[]`
  {`header_as_printed`, `fiscal_year`, `kind`, `as_printed`, `dollars` (int or null)}, `page`, `scope_line_ids[]`
  (subtotal/total only), `check` {`state` exact | within_rounding | does_not_add_up, `per_cell[]` {`printed`, `sum`,
  `diff`}} or null, `edition_differs` [line ids in other books] , `held` (check name) or null.
- **coverage** (one function, every page and the report): `n_total`, `n_bid_tab_links`, `n_tab_read`, `n_tab_not_read`
  by reason, `n_award_letters`, `n_award_scanned`, `n_docs`, `n_docs_scanned`, `n_lines`, `n_books`, `n_flag`,
  `by_department_year` {dept or "not stated": {year: {rows, with_tab, tab_read}}}.

UX field map (design section 10): `doc_date` = `doc_date_text` (mostly null, see 9), `total_dollars` = `total_cents`,
`awardee_source` = `bid_tab.document_id` + `awardee_page`, `total_check_ok` = null for lump-sum tabs (nothing to add),
`section` = `statement` + `tags`, `subtotal_check` = `check` + `scope_line_ids`. Rejected: per-department files (anchors
`finance/<fund>.html#<dept>` instead, file budget); a solicitation number (not printed anywhere read in 1a).

## 4. Checks and invariants (problem-key families for reviewers)
- **budget-reconcile/***: every subtotal and total gets a check over exactly its `scope_line_ids`; printed values are
  never altered; `exact` when sum = printed in every cell; `within_rounding` when |diff| <= floor((n+1)/2) dollars for n
  detail rows (each printed line is rounded to the dollar; the book's actuals are rounded from cents); otherwise
  `does_not_add_up`, shown as printed with its lines. A total with no detail rows in scope is `does_not_add_up`. No
  county-wide or cross-fund sum exists in code (lint: no `sum(` over lines outside `fin_checks.py`).
- **award-source/***: an awardee, bidder or total is shown only from a `bid_tab` document with a text layer, with its
  page; `awardee_match` compares names after one normalisation (casefold, collapse whitespace, remove spaces around
  "&", strip `_` and end punctuation); not exactly one match -> flagged, shown as printed. Never from a document whose
  `shared_by` is non-empty (one URL linked from several rows cannot be attributed: link only).
- **scan-values/***: no value of any kind (amount, name, date) has a `source_id` whose `text_layer` is not `text`. Build
  fails otherwise (sitegen reference check + property test over `finance.json`).
- **doc-completeness/***: per archive row, documents shown = links in the archive (count equal, AC-F7).
- **coverage-count/***: every page and the report read `coverage` from one function; fixed sentences from
  `config/finance_text.yml`, exact-string tests.
- **budget-edition/***: lines from different books are never merged or overwritten; a match on (fund_no, account_code
  or label, heading, fiscal_year, kind) with different `dollars` sets `edition_differs` both ways.
- **column-kind/***: every shown amount carries header as printed, fiscal year and kind; a misaligned number is held.
- Existing families still apply: `provenance/*`, `neutrality/*` (no amount sort, banned words), `politeness/*`.

## 5. Coverage parity (AC-F16)
`build/report.json` gains `finance` {coverage, parity {rule, departments [{dept, rows, tab_read_share}],
flagged[], status}, reconcile {exact, within_rounding, does_not_add_up}, held[], docs_by_status}. Parity rule
(provisional, in `collector/config.py`): a department with at least 5 rows whose `tab_read` share is below 0.5x or above
2x the overall share is flagged; status `review needed` blocks release until the manager records the reason in
`docs/status.md`. "Not stated" is its own bucket and is reported, not hidden.

## 6. Export (G5, AC-F13)
`build/site/data/`: `solicitations.csv`, `fin_documents.csv`, `bidders.csv`, `budget_lines.csv` (one row per line per
cell: line id, book, fund, heading, code, label, role, tags, header, fiscal year, kind, as_printed, dollars, page),
`budget_checks.csv` (check state per cell with sum and diff), `finance.json`. Every row: `source_url`, `source_sha256`,
`page`, `fetched_at`. Held values export as null with the check name.

## 7. Site generation
`sitegen/build.py` loads `data/finance.json` when present (schema-validated, reference-checked) and renders:
`contracts/index.html`, `contracts/<slug>.html` (about 90), `finance/index.html`, `finance/<fund_no>.html` (one per fund;
departments as anchors), `capital/index.html` (fund from `finance.yml` `capital_fund`), `glossary.html`. The "coming"
entries for those slots are removed. Search index adds type `sol` with title, department and every bidder name. The
`fin_views` builders take no vendor- or department-specific flags; skeleton tests as N1. Site total about 270 files.

## 8. Tests
Fixtures in `collector/tests/fixtures/finance/`: `pdftotext -bbox` extracts (text, not PDFs) of FY2027 pp. 28, 30, 33,
34, 36-37, 101, 105, 107-108 and 114, the wheel-loader bid tab, a trimmed archive HTML (10 rows covering every label
and status form), and a no-text scan. Regression tests per real case in section 9. Hand labels:
`collector/fin_hand_labels.json` (QA, at least 10 solicitations, AC-F6) and `qa/fin_spot_check.py` (30 random shown
amounts, AC-F1). Property tests: scan guard, scope partition (each detail row in exactly one scope per level),
determinism (two runs, byte-identical `finance.json`).

## 9. Risks found in the real samples
1. **Rounding:** a throwaway spike over all FY2027 detail statements found 515 subtotal/total checks: 410 exact, 99 off
   by 1-4 dollars (within the rounding bound, almost all in the Actuals column), 6 beyond it. A strict "to the printed
   dollar" rule would mark about 1 in 5 totals "does not add up" from rounding alone. Hence `within_rounding` (ADR 0002).
2. **Real non-reconciling totals:** capital fund p. 107 prints "Total ... PUBLIC ART" and "Total ... PARKING" with no
   lines above them; Trustee's office (p. 47) amended differs by 3,900. These must show as printed and flagged.
3. **Book slips in derived columns:** 20 rows whose printed Difference has the wrong sign or is off by 1 (pp. 43-114). We neither show nor check that column.
4. **Consolidated pages disagree with detail pages** in the same book (p. 28 FY2025 State of Tennessee 12,690,651 vs
   p. 33 12,690,251; p. 103 Federal 1,336,889 vs p. 105 1,336,689). Slice 1b reads detail pages only, plus the
   fund-balance block.
5. **Capital fund pages are 102-114**, not 100-112 as the spec says (100-101 are Debt Service). Fix the spec and config.
6. **Archive counts differ from platform facts:** the sample has 90 rows, 56 rows with a bid-tab link (2 are .docx), 71
   with an award-type document, versus 91 / 32 / 39 recorded. Coverage must stay live; text vs scan split of bid tabs is
   unknown until fetched (one text sample seen), so the fixed
   sentence "award letters are scans" must come from `n_award_scanned`, not be assumed.
7. **Shared URLs:** `Bid Tab.pdf`, `Bid Tab Sheet.pdf`, `Notice of Award Signed.pdf` and three more are linked from
   more than one row; a later upload replaces the file for every row. Link only, never read.
8. **No department or number in the archive, one date per row.** Department comes only from text bid tabs, so parity
   by department is weak and "not stated" will be large. Per-document dates are mostly null; design Note B ("Dates are
   shown per document") needs rewording by UX.
9. **Design Note E** says transfers "are not revenue or spending", but the book's printed Total Revenues includes 49800
   OPERATING TRANSFERS. Suggest UX wording that the book counts them in its totals and the site tags them.
10. FY2024-25 book layout is unverified (not sampled). Task 1b-1 checks it before any parser work assumes it matches.
