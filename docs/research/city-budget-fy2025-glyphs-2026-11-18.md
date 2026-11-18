# City FY2025 budget book: read through its glyph drawings (2026-11-18)

Book: "Fiscal Year 2025 Budget", https://www.clarksvilletn.gov/DocumentCenter/View/11392, sha256 `d6ce661d57d0...`
(the file in `data/localities/clarksville-tn/fin-manifest.json`). Line-item report pp. 43-133 (Munis "NEXT YEAR /
CURRENT YEAR BUDGET ANALYSIS", report date 06/27/2024). Earlier status: fetched, linked only (`books_not_read`,
`city-budget-build-2026-11-16.md` item 1). Contract: `docs/architecture/finance-contracts.md` section 10.

## Observations
- Producer Adobe Acrobat Pro 11.0.23. Every page 43-133 uses one Type 3 font of its own (91 fonts), glyph names
  `/0`, `/1`, ... and no ToUnicode, so pdftotext prints a cipher (`J!!` for `.00`). Each glyph is a vector drawing
  (a CharProc content stream). Across the 91 fonts there are 89 distinct drawings, and every one is used on these pages.
- The drawings are two faces: Lucida Console (68 glyphs, every advance 0.6025 em, the body and column headers) and
  Arial Bold (20, the page title "CITY OF CLARKSVILLE / NEXT YEAR / CURRENT YEAR BUDGET ANALYSIS"), plus one empty
  drawing (the space). The file gives every glyph width 1 and places each with its own `TD`. The only multi-glyph
  strings are the title's kerned pairs "OF" and "GE" (Tc -0.2223).
- Layout differences from the other three city books: a section total prints "<org> <section name, cut>" with no
  "TOTAL" (`100310 Taxes`); the fund line prints the number first (`1100 General Fund`); a fund starts mid-page right
  after the last fund's total (the page header still names the old fund); two funds open and close on one page and are
  named only by their cut total label (`TOTAL 2240 Vehicle Replaceme`). No TOTAL REVENUE / TOTAL EXPENSE lines; one
  GRAND TOTAL.

## How the table was made (`config/localities/clarksville-tn/fy2025-adopted-glyphs.json`)
1. Key: sha256 of each drawing. Every drawing was rendered on a sheet from the PDF's own glyph streams and labelled by
   eye.
2. Look-alikes were settled by the outline's size, not by eye: Lucida cap height 0.626, x-height 0.542, ascender 0.771,
   digits 0.741. So `O` (0.642) vs `o` (0.542) vs `0` (narrow, 0.741), `l` (0.771) vs `1` (0.741) vs `I` (0.626).
   Arial Bold glyphs are all capitals (cap height 0.716).
3. Advances measured from the book (the TD after each one-glyph string): 0.6025 for Lucida; for Arial Bold they equal
   the standard Arial Bold widths (A, B, C, D, K, N, R, U 0.722; E, S, V, X, Y 0.667; L, T 0.611; I, / 0.278), which
   confirms those labels independently. O and G keep width 1 (the file places the next glyph with Tc against width 1);
   F takes Arial Bold's 0.611.

## How it is read (collector/type3_decode.py, fin_facts.glyph_words)
A decoded copy (never stored) gives each Type 3 font a ToUnicode map, the table's widths and a sizing glyph `m` (so
poppler sizes words at the page's point size); then the usual `pdftotext -bbox` reader. Word positions match the
FY2026 book's to 0.01 pt (same report program). Fail closed: a glyph not in the table stops the book, and the book is
kept only if every printed total is exact to the cent and no line is held (`glyph-decode`, a guard: nothing written).

## Accuracy evidence (build of all four books, 2026-11-18)
| Check | Result |
|---|---|
| Printed totals over exactly their rows (115 section, 14 fund, 1 grand) | 130 of 130 exact to the cent, 0 held |
| Second reading without poppler: amounts each page draws (content stream through the table) vs cells read | 8,292 = 8,292, identical on all 91 pages |
| Rows with amounts, both readings | 1,382 = 1,382 (1,252 detail + 130 totals) |
| FY2025 "2025 2nd Readin" vs the FY2026 book's "2025 ORIG BUD" (lines that match one to one) | 314 of 314 equal |
| FY2025 "2024 ORIG BUD" vs the FY2024 book's "2024 2nd Readin" | 337 of 337 equal |
| ACTUAL columns vs other books | half differ, as expected (year to date at each report date vs final) |
| Section headings printed the same in another book | 53 of 112 identical letter for letter (others are cut differently) |
| Spot check, 10 lines (seed 20261118) against the rendered page | 10 of 10: code, label, six amounts |
| The other three books | every line and book record byte-identical to the committed reading (edition marks aside) |

Spot-check lines: p131 4340 Technical; p60 4540 Advertising; p110 4421 Waste Disposal; p106 4212 Dental Insurance;
p102 4214 Disability Insura; p43 31119 Property Tax 201; p66 4111 Full-Time Employe; totals p53 10411001, p96
10422001, p79 10419201 (all "Salaries and").

## Inferences and unknowns
- Letters in labels are not checked by any sum. They rest on the drawing labels (step 2) and the 53 identical
  headings; the account labels themselves are printed nowhere else (this book prints the long description, the others a
  short one).
- Fund numbers are printed in this book only; they are not stored (`fund_no` null, as in the other city books), so the
  four editions group and compare by fund name. The two cut fund names are completed from the other books' headers
  ("Traffic Camera Parks SRF", "Vehicle Replacement Fund"); the total's label stays as printed.
- If the city replaces the file, the daily run keeps the committed reading (sha256 rule); new drawings would stop the
  book until the table is extended by hand.
