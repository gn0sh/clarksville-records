# City budget books: first build (2026-11-16)

`python -m collector fin-books build --locality clarksville-tn` -> `data/localities/clarksville-tn/finance.json`
(schema `schema/finance.schema.json`, validated by the build). Layout notes: `city-budget-layout-2026-11-16.md`.
Contract: `docs/architecture/finance-contracts.md` section 10.

## Reconcile counts (every printed TOTAL, checked over exactly its rows)

| Book | Pages read | Lines | Detail | Totals checked | Adds up (exact) | Within rounding | Does not add up | Held / not checked |
|---|---|---|---|---|---|---|---|---|
| fy2024-adopted | 107 (50-156) | 2,088 | 1,954 | 134 | 134 | 0 | 0 | 0 |
| fy2026-final | 106 (33-138) | 2,071 | 1,932 | 139 | 139 | 0 | 0 | 0 |
| fy2027-presented | 114 (9-434) | 2,075 | 1,808 | 267 (5 project subtotals) | 267 | 0 | 0 | 0 |
| fy2025-adopted | not read | | | | | | | link only |

Totals by level: section totals, project subtotals (FY2027 Self-Insurance only), fund totals (14, 14, 40: FY2027 has
one report run per department, so a fund's total there covers that run), report-run totals TOTAL REVENUE / TOTAL
EXPENSE / GRAND TOTAL (1, 2, 39 runs). Amounts are checked to the cent, so "adds up" means exact to the cent.

Completeness: an independent count on the pdftotext layout text of the same pages (rows that start with an org code
and an account code and print amounts; lines that start with TOTAL / GRAND TOTAL) gives 1,954 / 1,932 / 1,808 detail
rows and 134 / 139 / 267 totals: the same as read. No row was held (column-align or derived-spill): every touching
amount (100 M and up) split back onto its column's right edge.

Edition compare: 362 line pairs differ between FY2026 and FY2027 on the same key (fund, code, heading, fiscal year,
kind), all in the `2025 ACTUAL` column: the FY2026 report ran 07/08/2025, the FY2027 one 05/29/2026 (final FY2025
actuals). Lines are marked `edition_differs`, never merged.

## Spot check, 10 lines by hand against the PDF text (seed 20261116, 7 detail + 3 totals)
All 10 match the printed line (account code, label and all six amounts in order):
fy2024 p88 4111 Full-Time; fy2024 p89 4450 Const.Svcs; fy2027 p375 34804 Rev-Other; fy2026 p72 4231 TCRS;
fy2026 p44 4712 Other Debt; fy2027 p147 4221 Social Sec; fy2027 p398 33110 PD094 FGrantOper; fy2027 p177 TOTAL
EXPENSE (exact); fy2024 p125 TOTAL Other Financing Uses (exact); fy2027 p46 GRAND TOTAL (exact; the run is one
board's operating budget, so its section, fund and grand totals print the same amounts).

## Held or uncertain (for the manager and UX)
1. FY2025 book not read: its line-item pages use Type 3 fonts with no Unicode map (pdftotext gives a cipher). Its
   FY2025 budget is still printed in the FY2026 book's `2025 ORIG BUD` / `2025 REVISED BUD` columns. Options: leave
   link only (recommended), or a glyph map checked cell by cell against the FY2026 book, or OCR.
2. FY2027 file is labelled "as presented 5/29/2026" (kind `proposed`, column "2027 Mayor"); not confirmed whether the
   city later replaced it with the adopted book.
3. "ACTUAL" columns of the year in progress are as of the report date (FY2024 book: 06/28/2023; FY2026: 07/08/2025):
   year to date or before that year's books closed, not final (FY2027 prints final FY2025 actuals that differ).
   Stored as printed with kind `actual`; the page should show the header and the report date.
4. Revenue prints negative (credits) and fund / grand totals are net (revenue + expense); stored as printed.
5. Not read: Gas & Water comparison report, CDE electric and broadband, transit, agencies, CDBG, debt schedules,
   cash-flow summaries, the FY2027 detail report (vendor and staff notes), signed-ordinance scans.
6. No fund numbers (the books print none on these pages): `fund_no` null, fund by printed name.
