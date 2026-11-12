# QA test plan and results: finance-contracts slices 1a (Bids and awards) and 1b (Budget books)

Owner: qa-engineer. Spec: `docs/specs/finance-contracts.md`. Architecture: `docs/architecture/finance-contracts.md`. Pattern: `docs/qa/m1-test-plan.md`.
Date: 2026-11-08. Code under test: `c61a550` (`claude/project-thread-lc34qg`), no network used.
Data: `data/finance.json` as committed (90 solicitations, 295 documents, 3,846 budget lines, 2 books). Site built with
`sitegen.build.build(facts, build/site, finance_path=data/finance.json)` plus the open-data export, and
`python -m collector fin build` for the run report (finance.json came out unchanged: deterministic).

**Verdict: PASS WITH MINOR ISSUES.** AC-F1 30/30 and a full 3,846-line sweep match the PDFs with zero mismatches; no wrong value found.
No blocker. Findings are note wording (one medium), a vacuous parity gate (medium), and coverage gaps (not errors). See "Bugs".

## Setup (runnable as written)
1. `git fetch origin && git checkout -B qa-fin origin/claude/project-thread-lc34qg`; `pip install -r requirements.txt pdfplumber`.
2. `cp -a <main checkout>/data/store data/ && cp -a <main checkout>/data/text data/`.
3. **Environment gap:** the two budget-book PDFs were NOT in that store (`data/store/f6538dd0...pdf`, `8f2a4166...pdf`), so a
   `collector run --offline` fails with `provenance/book-missing` and writes nothing. QA found hash-identical copies in the
   session scratch (`sha256sum` equals `sources[].sha256` in finance.json) and copied them into `data/store/` (gitignored).
   Note for the manager: a fresh checkout with only the committed store cannot rebuild the budget half.
4. Do not run `python -m collector run --offline` for the finance check: the minutes PDFs are also absent, and that command then
   overwrites `data/facts.json` with an empty roll-call set (QA restored it with `git checkout data/facts.json`).

## Results by criterion
| AC | Result | What was checked (and could have failed) |
|---|---|---|
| AC-F1 | **PASS** 30/30, 0 mismatches | Table below. Beyond the sample: every one of the 3,846 budget rows on the 7 fund pages was compared to `pdftotext -layout` of its linked page (label + account code + the shown values in column order): 3,846 match. Every column header shown (FY, header as printed, kind) is on the PDF page. All 80 bidder rows on the 16 read bid tabs: name and total aligned to the PDF (row layouts by vertical position; the 8 block-layout tabs, 55 rows, by block position plus the rule that the shown total is the last amount in the bidder's block, and base + alternates = printed total on 5 of them), 2 totals correctly held ("$ 765,790.00" has a space, shown as Not confirmed*). The 5 awardee names, bid dates and award dates equal the PDF text. Independent parse of every `as_printed` agrees with `dollars` (0 differences). |
| AC-F2 (extra) | PASS | Recomputed all 987 subtotal/total checks from the PDF-verified cells with the architecture rule: 769 exact, 192 within rounding, 26 does not add up; 0 disagreements with `check.state`. |
| AC-F3 | **PASS** | 4,900 budget rows and 486 contract-page rows carry a link (budget rows `#page=N`) and "fetched 2026-11-08" in Details; all 80 bidder rows `#page=1`; all 26 bid date/award date/awardee lines carry a page link and fetch date. 11 "The bid tab does not name an awardee" lines are statements, not values; verified true against the PDFs. No `$` amount outside a table on any contract page. `qa/site_checks.py` `sources` PASS (29,554 source links). |
| AC-F6 | **PASS** | `collector/fin_hand_labels.json`: 24 solicitations hand-labelled: 16 read tabs (2 to 15 bidders, a held total, wrapped names, 5 with a named awardee, 3 "Base Bid" only, 1 with a misprint "Huges"), 5 layout-not-read (unit prices, scoring column, "Not Complete" row), 1 shared URL, 1 not-a-PDF, 1 no tab; scanned award letters labelled on 2. `collector/tests/test_fin_hand_labels.py`: 25 tests, all pass; mutation check (one total changed in the labels) fails the matching test. Zero wrong values. |
| AC-F7 | **PASS** | Independent regex parse of the stored archive HTML: 90 rows, 316 document links. Contract pages show 316 document rows; per-row counts equal for all 90 rows. (finance.json has 295 distinct documents, 21 fewer than rows, because some rows link the same document; each row shows its own links.) `build/report.json` reports `docs_by_status` {fetched 292, not_pdf 3}. |
| AC-F8 | **PASS** | Banned-word scan of all finance, contracts, capital and glossary prose (list of 23 words incl. top, worst, rank, score, increase, trend, unusual): 0 hits. Contracts index orders are Date newest/oldest, Title A-Z, Department A-Z only; bidders in printed order (labels enforce it); no amount column on the index; no sum phrase on any page (the only "county-wide" is the note "No county-wide total is shown"). Existing tests `test_budget_pages.py` banned-word tests pass. Wording of notes is judged separately under "Bugs". |
| AC-F9 | **PASS (vacuous)** | None of the 33 roster names appears on any finance, contracts, capital or glossary page, so there is nothing to link; `site_checks` `name-links` PASS (44,100 links, 241 pages) and `tests/test_fin_pages.py::test_official_name_links_to_their_page` covers the mechanism. |
| AC-F10 | **PASS** | `python -m qa.site_checks`: `hscroll` PASS (36 page checks at 390 px, contracts, finance, capital also at 360 px), `row-height` PASS (60,120 rows on 27 pages at 375x667, 768x1024, 1000x800, 1280x800, 360x640). Full-suite `pytest`: 1,072 passed, 4 skipped. `--all-pages` run: `hscroll` PASS on 336 page checks at 390 px (every one of the 90 contract pages, 7 fund pages, finance index, capital, all also at 360 px), `row-height` PASS on 198,623 rows / 236 pages; `RESULT: PASS`. |
| AC-F15 | **PASS** | Exact string compared with the sentence rebuilt from `config/finance_text.yml` + `finance.json` coverage: contracts "56 of 90 solicitations have a bid tab; 44 of 70 award letters are scanned images. Award letters are linked, not read." on 91 pages (index + 90); budget "3846 budget lines from 2 books; 26 totals do not add up as printed and are marked." on 8 finance pages + capital. No finance/contracts/capital page lacks one. See bug B4 (the sentence never says how many tabs are read). |
| AC-F16 | **PASS (report present), gate weak** | `build/report.json` `finance.parity` present: overall read share 0.1778, status "ok", flagged []. See bug B4: the gate cannot fire on this data. |

## AC-F1: 30 random shown amounts (seed 20261108; script in QA scratch, not committed)
15 budget cells (7 funds 101, 122, 127, 131, 151, 171, 266; both books), 5 subtotals/totals (one flagged "does not add up"), 10 bid-tab totals from 10
different solicitations. "PDF line" is `pdftotext -layout` of the cited page, columns joined with `/`.

| # | Kind | Fund / solicitation | Source and page | Line | Column and kind | Shown | PDF line (pdftotext -layout) | Result |
|---|---|---|---|---|---|---|---|---|
| 1 | budget cell | 101 | FY2027 book p. 58 | 54500 TIRES & TUBES | FY 2026 Amended / Amended budget | `55,000` | `54500 TIRES & TUBES / 56,129 / 55,000 / 55,000 / - / -` | MATCH |
| 2 | budget cell | 122 | FY2024-25 book p. 74 | 54010 ANIMAL FOOD & SUPPLIES | FY 23 Actuals / Actual | `2,741` | `54010 ANIMAL FOOD & SUPPLIES / 2,741 / 3,400 / 3,500 / 100 / 2.94` | MATCH |
| 3 | budget cell | 127 | FY2027 book p. 86 | 53990 OTHER CONTRACTED SERVICES | FY 2026 Amended / Amended budget | `66,500` | `53990 OTHER CONTRACTED SERVICES / 27,000 / 66,500 / 24,500 / (42,000) / (63.16)` | MATCH |
| 4 | budget cell | 131 | FY2024-25 book p. 84 | 54050 ASPHALT - LIQUID | FY 24 Amended / Amended budget | `85,000` | `54050 ASPHALT - LIQUID / 54,709 / 85,000 / 85,000 / - / -` | MATCH |
| 5 | budget cell | 151 | FY2027 book p. 101 | 56130 INTEREST -OTHER LOANS PAYABLES | FY 2027 Budget / Adopted budget | `25,250` | `56130 INTEREST -OTHER LOANS PAYABLES / 303,000 / 303,000 / 25,250 / (277,750) / (91.67)` | MATCH |
| 6 | budget cell | 171 | FY2024-25 book p. 96 | 40130 CIRCUIT/CHANCERY COLLECT-PYR | FY 24 Amended / Amended budget | `45,000` | `40130 CIRCUIT/CHANCERY COLLECT-PYR / 80,327 / 45,000 / 65,000 / 20,000 / 44.44` | MATCH |
| 7 | budget cell | 266 | FY2027 book p. 118 | 53560 TUITION | FY 2025 Actuals / Actual | `-` | `53560 TUITION / - / 3,300 / 2,265 / (1,035) / (31.36)` | MATCH |
| 8 | budget cell | 101 | FY2024-25 book p. 37 | 54110 DATA PROCESSING SUPPLIES | FY 24 Amended / Amended budget | `750` | `54110 DATA PROCESSING SUPPLIES / 311 / 750 / 750 / - / -` | MATCH |
| 9 | budget cell | 122 | FY2027 book p. 80 | Estimated Ending Fund Balance June 30 | FY 2026 Projections / Projected | `46,540` | `Estimated Ending Fund Balance June 30 / 57,302 / 22,078 / 46,540 / 9,228` | MATCH |
| 10 | budget cell | 127 | FY2024-25 book p. 76 | Estimated Beginning Fund Balance July 1 | FY 23 Actuals / Actual | `41,093,795` | `Estimated Beginning Fund Balance July 1 / 41,093,795 / 42,056,046 / 22,181,026` | MATCH |
| 11 | budget cell | 131 | FY2027 book p. 91 | 46925 HYBRID/ELECTRIC VEHICLE REGIST | FY 2026 Amended / Amended budget | `-` | `46925 HYBRID/ELECTRIC VEHICLE REGIST / 55,939 / - / - / - / -` | MATCH |
| 12 | budget cell | 151 | FY2024-25 book p. 90 | 40110 CURRENT PROPERTY TAX | FY 24 Amended / Amended budget | `32,880,000` | `40110 CURRENT PROPERTY TAX / 39,281,999 / 32,880,000 / 40,230,000 / 7,350,000 / 22.35` | MATCH |
| 13 | budget cell | 171 | FY2027 book p. 111 | 57990 OTHER CAPITAL OUTLAY | FY 2026 Amended / Amended budget | `362,379` | `57990 OTHER CAPITAL OUTLAY / - / 362,379 / - / (362,379) / (100.00)` | MATCH |
| 14 | budget cell | 266 | FY2024-25 book p. 108 | 53550 TRAVEL | FY 25 Projection / Adopted budget | `8,000` | `53550 TRAVEL / 3,774 / 5,400 / 8,000 / 2,600 / 48.15` | MATCH |
| 15 | budget cell | 101 | FY2027 book p. 65 | 55110 VEHICLE & EQUIPMENT INSURANCE | FY 2025 Actuals / Actual | `1,618` | `55110 VEHICLE & EQUIPMENT INSURANCE / 1,618 / 1,800 / 1,800 / - / -` | MATCH |
| 16 | subtotal/total | 101 | FY2027 book p. 36 | Total BOARD OF EQUALIZATION [Adds up] | FY 2026 Amended / Amended budget | `10,770` | `Total BOARD OF EQUALIZATION / 8,612 / 10,770 / 10,765 / (5) / (.05)` | MATCH |
| 17 | subtotal/total | 171 | FY2027 book p. 110 | Total PUBLIC HEALTH /WELFARE PROJECT - ANIMAL [Adds up] | FY 2027 Budget / Adopted budget | `-` | `Total PUBLIC HEALTH /WELFARE PROJECT - ANIMAL / 12,107,956 / 1,502,620 / - / (1,502,620) / (100.00)` | MATCH |
| 18 | subtotal/total | 171 | FY2024-25 book p. 98 | Total GENERAL ADMINISTRATION PROJECT [Adds up] | FY 23 Actuals / Actual | `1,000,000` | `Total GENERAL ADMINISTRATION PROJECT / 1,000,000 / 2,611,177 / - / (2,611,177) / (100.00)` | MATCH |
| 19 | subtotal/total | 101 | FY2024-25 book p. 50 | Total DISTRICT ATTORNEY GENERAL [Adds up] | FY 24 Amended / Amended budget | `61,260` | `Total DISTRICT ATTORNEY GENERAL / 38,343 / 61,260 / 599,102 / 537,842 / 877.97` | MATCH |
| 20 | subtotal/total | 171 | FY2024-25 book p. 102 | Total SOCIAL/CULTURAL/REC PROJECTS - ROTARY [As printed, does not add up In the colum] | FY 24 Amended / Amended budget | `100,000` | `Total SOCIAL/CULTURAL/REC PROJECTS - ROTARY / - / 100,000 / - / (100,000) / (100.00)` | MATCH |
| 21 | bid-tab total | rfp-rossview-rd-rollow-ln-sightline-impr | bid tab p. 1 | Tugsun Group Inc | Bid total as printed | `$439,900.00` | `Tugsun Group Inc / $439,900.00` | MATCH |
| 22 | bid-tab total | bid-400-pageant-lane-building-emergency- | bid tab p. 1 | Eskola | Bid total as printed | `$68,450.00` | `$68,450.00` | MATCH |
| 23 | bid-tab total | bid-veterans-plaza-gutter-replacement | bid tab p. 1 | Modern Heating Cooling Roofing | Bid total as printed | `$91,700.00` | `$91,700.00` | MATCH |
| 24 | bid-tab total | bid-mcso-fire-system-upgrade | bid tab p. 1 | Integrated Protection Services | Bid total as printed | `$84,982.08` | `Integrated Protection / $84,982.08` | MATCH |
| 25 | bid-tab total | bid-hvac-replacement-lone-oak-community- | bid tab p. 1 | Action Air Conditioning Service, Inc. | Bid total as printed | `$108,505.00` | `Total Bid: / $108,505.00` | MATCH |
| 26 | bid-tab total | bid-sheriff-s-office-vehicle-equipment | bid tab p. 1 | Columbia CDJR | Bid total as printed | `$89,230.00` | `Columbia CDJR / $89,230.00` | MATCH |
| 27 | bid-tab total | bid-wheel-loader | bid tab p. 1 | McCoy Construction & Forestry | Bid total as printed | `$189,000.00` | `McCoy Construction & / $189,000.00` | MATCH |
| 28 | bid-tab total | request-for-bid-generator-electrical-alt | bid tab p. 1 | Stansell Electric | Bid total as printed | `$65,811.00` | `$65,811.00` | MATCH |
| 29 | bid-tab total | bid-palmyra-salt-shed-foundation | bid tab p. 1 | Tugsun Group Inc | Bid total as printed | `$341,487.00` | `Tugsun Group Inc / $341,487.00` | MATCH |
| 30 | bid-tab total | bid-full-depth-reclamation-project-of-ol | bid tab p. 1 | Mt. Carmel Stabilization Group | Bid total as printed | `$736,985.00` | `Mt. Carmel Stabilization / $736,985.00` | MATCH |

**Spot-check mismatch count: 0 of 30.** Five awardee names (AC-F1 "5 awardee names"): Mt. Carmel Stabilization Group, Integrated Protection Services,
Truckers Lighthouse, McCoy Construction &Forestry, Byard Construction, LLC: each is the exact "Bid Awarded to" text on the bid tab PDF page 1. 5/5 match.

## Bugs and findings
| # | Problem key | Severity | Owner | Finding |
|---|---|---|---|---|
| B1 | `neutrality/note-misstates-source` | medium | frontend-engineer (wording in `config/finance_text.yml` note `e`, shown on Finance index and all 7 fund pages) | The note says transfers and available funds "are not revenue or spending". The book prints them inside its own totals: FY2027 book p. 105 (fund 171) "Total Revenues 26,110,969 / 84,418,746 / 16,383,000" includes "Other Sources (Non-Revenue)" of 250,000 / 57,002,336 / -, which holds BOND PROCEEDS, INSURANCE RECOVERY and OPERATING TRANSFERS. The site itself marks 28 totals "This total also adds lines listed under Transfers and available funds". A resident reading the note would expect the printed Total Revenues to exclude them. Suggested: "...listed in their own section. Some printed totals include them; those totals say so." |
| B2 | `neutrality/note-misstates-source` | low | frontend-engineer | Capital page note: "Capital fund lines are yearly appropriations in the budget book" but the page shows "Actual" columns (money spent). Glossary "Capital project: a building, road or equipment purchase" but the capital page lists headings such as OTHER DEBT SERV-COUNTY GOVT and OTHER DEBT SERV.-EDUCATION as project names. |
| B3 | `neutrality/note-misstates-source` | low | frontend-engineer | Column "Bid total as printed" and note "A bid total is the amount a bidder wrote on the bid tab". Three tabs print only "Base Bid:" (courts-center-generator-replacement, interior-renovations-to-montgomery-co-purchasing-and-building-codes, 400-pageant-lane-building-emergency-reroof) with no total line; the EMS Station 28 tab's printed Total Bid adds "Add Alternate #1" to the base. The county's staff prepare the tab, bidders do not write on it. Suggested: "the amount printed for the bidder on the bid tab (a base bid where the tab prints no total)". |
| B4 | `coverage-parity/department-read-from-tab` | medium (process) | backend-engineer + product-manager | The parity gate (AC-F16) cannot fire. A department exists only when read from a bid tab, so every row with a department has a read tab (8 rows, share 1.0) and the other 82 rows are "not stated" (share 0.098, 0.55x of overall, just inside the 0.5x bound, and "not stated" is exempt). No department has 5 rows, so the rule never evaluates. Also the coverage sentence says "56 ... have a bid tab" while 16 are read (30 unit-price or unfamiliar layout, 8 shared URL, 2 not PDF); a resident can expect 56 sets of figures. Suggest adding "16 are read" to the fixed sentence, and a parity key that exists for unread rows (e.g. archive year or title prefix). |
| B5 | `kind-label/projection-shown-as-adopted` | low (doc) | software-architect | FY2024-25 book column "FY 25 Projection" is labelled "Adopted budget" by an override (ADR 0002 amendment); `docs/platform-facts.md` line 56 still says config maps it to `projected`. The site shows the book's own header beside the kind, so no wrong value, but the two docs disagree and the kind is an inference. |
| C1 | `coverage-count/readable-tabs-unread` | info | backend-engineer | Plain tabs a person can read but the collector (correctly, conservatively) does not: woodlawn-park-fencing (6 bidders and totals, one "Not Complete"), rfp-rfid-gates (5 bidders plus a scoring column), veterans-plaza-hvac-replacement (block layout, 3 alternates). They are labelled not_read in the hand labels so a later widening is a deliberate change. |

No wrong amount, name, date, page link or check state was found in slices 1a or 1b.

## Not covered here
AC-F4 award-letter half (deferred to 1a.2), AC-F5 (checked indirectly: 0 values from scanned documents; `scan-values` tests pass), AC-F11 to F14 and F17 (not in this assignment; AC-F13 export: `build/site/data/` has no finance CSVs in this build).
