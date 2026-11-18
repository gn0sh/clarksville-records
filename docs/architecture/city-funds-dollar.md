# Architecture: the city budget dollar, by fund (city/finance)

Status: design, 2026-11-18 (software-architect). Built 2026-11-18 (backend-engineer, branch `claude/city-funds-dollar`;
section 5 notes the three as-built names). Base: origin/main 60167e4c.
Goal (CEO, 2026-11-18): on `city/finance/index.html` the only figure is "Where each dollar of the general fund budget
goes". He asked "what other spending does the city do?", then: "just break them up the same way you did with the
county stuff." Reading used here: one more bar on the city Finance index, in the style of the county's "Where a county
property tax dollar goes" (finance-contracts 12), that splits the city's whole budget in the newest adopted book across
its funds, in cents of each dollar, with an "Every fund" list and sources, placed above the general fund department bar.

Precedents reused: `sitegen/dollar_split.py` (finance-contracts 11: which book and column, printed totals only, the
`total_net` path for a book with no spending-only fund total) and `sitegen/property_tax.py` (finance-contracts 12:
fund rows in tenths of a cent, `_proptax.html.j2`, the row that links down to `#general-fund-dollar`).
All figures below were computed from `data/localities/clarksville-tn/finance.json` at 60167e4c with
`collector.fin_checks` (integer cents; the city books have `amount_unit: "cents"`).

## 1. Decisions

| # | Decision | Evidence |
|---|---|---|
| D1 | Book and column: `fy2026-final`, "2026 2nd Readin" (adopted, FY2026), the same book and column as the city general fund bar. The FY2027 file is not used and the bar says why, built from the data (reuse `dollar_split._newer_books_note`). A newer book printing an adopted budget for its own year fails the build (stale-book, as sections 11 and 12). | `fy2027-presented`'s own-year column is "2027 Mayor", kind `proposed`; it also prints no Debt Service Fund and no "Other Financing Uses" department, so it is not the whole budget either (its "2026 ORIG BUD" column adds up to 185,998,402.77 across 13 funds, not 221,059,845.77). |
| D2 | Each fund's amount: its printed spending section totals (`statement` expenditure, `row_role` total, `department` set) added with `fin_checks.total_of`, in that column. No city fund prints a spending-only total (its "TOTAL <fund>" line adds revenue and spending together, statement `net`), so each fund is checked the `total_net` way: section totals + the fund's printed revenue totals == its printed "TOTAL <fund>" to the cent. The bar's total is not a sum we invent: it equals the book's own printed "TOTAL EXPENSE" lines of its two report runs (p. 137 and p. 138), and the funds of each run must add up to that run's TOTAL EXPENSE exactly. | Table in section 2: all 14 funds pass both checks; 0 held, 0 not exact, every spending detail line under exactly one section total and exactly one run TOTAL EXPENSE. |
| D3 | Money moving between funds: shown as printed, not taken out. Each fund's amount is its own printed spending; a dollar the general fund pays into the health insurance fund (and that fund then spends) is in both, exactly as the book's own TOTAL EXPENSE counts it. One plain sentence at a glance says so, and the closed sources block lists, with links, the 10 revenue lines other funds print as received from the general fund ("GF"). No subtraction, no net figure. | Only one transfer prints on the paying side as its own line ("Tran to DS" 11,174,410.00, p. 107), and the receiving side prints "Tran In GF" 12,174,410.00 (p. 127), so netting would have to pick one of two printed figures. The general fund pays the internal-service funds inside each department's benefit and vehicle accounts (e.g. account 4211 "Health" 17,613,951.00 across departments vs the health fund's GF lines 18,844,039.80), so there is no line to take out. Taking out some and not others would be a figure the book does not print. |
| D4 | Fund rows in tenths of a cent (`fin_checks.tenths_of_dollar`, largest remainder), every fund its own row, no "Other". | In whole cents 7 of the 14 funds would print "0 cents"; in tenths the smallest is 0.1 and none is 0.0. Same rounding as the county fund bar (section 12). |
| D5 | Rows in the book's order (first page of each fund), never by amount (neutrality/*). The general fund row links down to `#general-fund-dollar` (as the county property tax bar does). | |
| D6 | County page: no "every fund" bar now (see section 8). | |

Assumptions (recorded, not asked): the reader-facing label for the whole is "the city budget" with the scope stated in
the lede (the funds this site reads from the book); plain fund names are written in config with each printed name shown
under "Printed as" (as section 12 does); "GF" in a revenue label is read as "general fund" only in the sources list,
where each line's label is shown exactly as printed.

## 2. Per-fund amounts (fy2026-final, "2026 2nd Readin", cents book)

Order is the book's. "Sections" are the printed spending section totals added for the fund (line ids below the table).
"Fund total" is the printed net line each fund is checked against. Cents: tenths of a cent, largest remainder.

| Fund as printed | Plain name (config) | Spending | Sections | Fund total line (net, as printed) | Cents |
|---|---|---:|---:|---|---:|
| General Fund | General fund | 165,631,658.00 | 67 | p108/r17 3,421,568.00 | 74.9 |
| Drug Enforcement | Drug enforcement | 520,773.00 | 3 | p110/r21 194,073.00 | 0.2 |
| Police Special Revenue | Police special revenue | 456,923.00 | 3 | p115/r27 257,539.00 | 0.2 |
| Traffic Camera Pol SRF | Traffic camera, police | 324,785.00 | 2 | p116/r21 139,785.00 | 0.2 * |
| Traffic Camera Parks SRF | Traffic camera, parks | 500,000.00 | 1 | p117/r18 400,000.00 | 0.2 |
| Road Improvements Fund | Road improvements | 1,800,000.00 | 1 | p118/r16 1,800,000.00 | 0.8 |
| Parks Special Revenue | Parks special revenue | 843,437.00 | 4 | p124/r23 129,802.00 | 0.4 |
| Special Revenue Fund | Special revenue | 162,700.00 | 2 | p126/r11 .00 | 0.1 |
| Debt Service Fund | Debt service | 15,181,189.00 | 1 | p127/r25 .00 | 6.9 |
| Parking Commission | Parking commission | 1,094,227.00 | 3 | p131/r15 357,067.00 | 0.5 |
| Dental Fund | Dental insurance | 1,498,480.00 | 1 | p132/r19 114,202.00 | 0.7 |
| Health Insurance Fund | Health insurance | 27,252,761.77 | 2 | p135/r8 -234,832.53 | 12.3 |
| Self-Insurance Fund | Self-insurance | 1,349,000.00 | 2 | p137/r9 -40,000.00 | 0.6 |
| Vehicle Replacement Fund | Vehicle replacement | 4,443,912.00 | 1 | p138/r22 .00 | 2.0 |
| **Total** | | **221,059,845.77** | 93 | p137/r11 216,615,933.77 + p138/r24 4,443,912.00 (TOTAL EXPENSE) | 100.0 |

\* Rounded to the nearest tenth the shares add up to 99.9; largest remainder gives Traffic camera, police (exact
0.147) 0.2, and the page names it (property_tax's `rounding_moved_one` wording). Exact shares: 74.926, 0.236, 0.207,
0.147, 0.226, 0.814, 0.382, 0.074, 6.868, 0.495, 0.678, 12.328, 0.610, 2.010.
The general fund row equals the general fund bar's total (165,631,658.00) to the cent: test it.
Plain names "Traffic camera, police / parks": the funds' org codes 3442xxx / 3545xxx carry the city's police (42) and
parks (45) function digits, as the general fund's 1042100 Police and 1045100 Parks do; "Dental insurance": the fund's
revenue lines are premiums by payer (Rev-GF, Rev-GWS, Rev-Trans), like the health insurance fund's. If the reviewer
prefers no reading of an abbreviation, use "Dental" and "Traffic camera (Pol)"; the printed name is shown either way.

Section totals per fund (line ids, amount as printed):
- General Fund: the 67 department section totals the general fund bar already lists (`dollar_split`, org codes 104xxxx);
  the row links down to that bar instead of repeating them.
- Drug Enforcement: p109/r13 180,200.00; p110/r9 207,173.00; p110/r20 133,400.00.
- Police Special Revenue: p112/r23 64,087.00; p115/r11 387,496.00; p115/r26 5,340.00.
- Traffic Camera Pol SRF: p116/r14 267,785.00; p116/r20 57,000.00.
- Traffic Camera Parks SRF: p117/r14 500,000.00.
- Road Improvements Fund: p118/r15 1,800,000.00.
- Parks Special Revenue: p119/r21 134,749.00; p122/r24 557,388.00; p124/r9 53,300.00; p124/r22 98,000.00.
- Special Revenue Fund: p125/r18 162,700.00; p126/r10 .00.
- Debt Service Fund: p127/r19 15,181,189.00.
- Parking Commission: p128/r24 369,181.00; p130/r17 559,046.00; p131/r14 166,000.00.
- Dental Fund: p132/r18 1,498,480.00.
- Health Insurance Fund: p134/r27 27,244,761.77; p135/r7 8,000.00.
- Self-Insurance Fund: p136/r17 1,349,000.00; p136/r26 .00.
- Vehicle Replacement Fund: p138/r21 4,443,912.00 (also its run's printed TOTAL EXPENSE p138/r24: the one fund whose
  spending-only total is printed, because it is the only fund in report run 2).
(All ids are `fy2026-final/<id>`.)

### Lines with `fund_name` None (report-run totals, never a fund row)
Per finance-contracts 10, `fund_name` is null only on a report-run total: each run of the Munis line-item report ends
in `TOTAL REVENUE` / `TOTAL EXPENSE` / `GRAND TOTAL`, scoped to every revenue, expense, or any line of that run.
- `fy2026-final` has 2 runs. Run 1 (funds General Fund to Self-Insurance Fund, pp. 33-137): p137/r10 TOTAL REVENUE
  -210,076,730.30, p137/r11 TOTAL EXPENSE 216,615,933.77 (scope: all 1,648 spending detail lines of its 13 funds),
  p137/r12 GRAND TOTAL 6,539,203.47. Run 2 (Vehicle Replacement Fund only, p. 138): p138/r23 -4,443,912.00,
  p138/r24 4,443,912.00, p138/r25 .00. The bar reads the two TOTAL EXPENSE lines as its printed total check.
- `fy2027-presented` prints one run per department or fund part: 39 runs, 117 such lines. The ~53.7M line is
  p285/r32 TOTAL EXPENSE 53,690,471.00 ("2027 Mayor"): the run that prints only the Police department's three
  general fund sections (10421001 / 10421003 / 10421004); it equals that run's "TOTAL General Fund" p285/r30 and
  GRAND TOTAL p286/r7. It is a page total of one department's report run, not a fund, and must never be a bar row.
  Rule: a fund row is built only from lines with `fund_name` set; a line with `fund_name` None is used only as a
  run TOTAL EXPENSE check.

## 3. Money moving between funds (D3)

Revenue lines other funds print as received from the general fund, "2026 2nd Readin" (the list the page shows):

| Fund | Line id | Label as printed | Account | Amount as printed |
|---|---|---|---|---:|
| Debt Service Fund | p127/r22 | Tran In GF | 39150 | -12,174,410.00 |
| Dental Fund | p132/r8 | Rev-GF | 34801 | -999,660.00 |
| Health Insurance Fund | p133/r9 | Rev-GF | 34801 | -11,885,120.10 |
| Health Insurance Fund | p133/r14 | Phar-GF | 34811 | -5,558,159.70 |
| Health Insurance Fund | p133/r19 | OSC GF-OSC | 34821 | -1,400,760.00 |
| Self-Insurance Fund | p136/r19 | Rev-GF | 34801 | -814,899.00 |
| Vehicle Replacement Fund | p138/r9 | Rev-GF | 34801 | -534,089.00 |
| Vehicle Replacement Fund | p138/r10 | 421 Rev-GF | 34801 | -2,337,823.00 |
| Vehicle Replacement Fund | p138/r11 | 422 Rev-GF | 34801 | -1,053,000.00 |
| Vehicle Replacement Fund | p138/r12 | 431 Rev-GF | 34801 | -519,000.00 |

The four Vehicle Replacement lines add up to that fund's printed revenue total, -4,443,912.00.

Not shown in this list: "Rev-GWS" / "Rev-Trans" lines (payments from Gas & Water and Transit, which this site does not
read from the book, so they are not in the bar twice) and "From other" lines (the payer is not printed). The list shows
each amount exactly as printed (revenue prints negative, as `budget_city.note_e` already tells the reader) and adds no
sum of them.

How the list is chosen (config, checked both ways, so a new book cannot drop or add one silently):
`from_general_fund.accounts: ["34801", "34811", "34821", "39150"]` and `label_token: "GF"`. The build fails when a
revenue detail line outside the general fund has one of those accounts but no "GF" token in its label (token regex
`(^|[^A-Za-z])GF([^A-Za-z]|$)`), or has the token but another account. Listed: such lines with a non-zero amount in
the column, in book order. The general fund's own side is not listed: its "Other Financing Uses" department (where
"Tran to DS" prints) is already a row of the general fund bar, with that bar's transfers note.

## 4. Copy (`config/finance_text.yml`, new block `fund_split`, after `budget_city`)

US English, plain words, no evaluation words (checked by `FIN_BANNED`: no "percent", "%", "top", "best", "highest").
Amounts in prose use `usd()` (new, in `budget_views`): "$" + the cents text with a ".00" dropped ("$165,631,658",
"$221,059,845.77"); table cells keep the amount exactly as printed.

```yaml
# The city budget dollar, by fund (sitegen/fund_split.py, docs/architecture/city-funds-dollar.md; CEO 2026-11-18:
# "just break them up the same way you did with the county stuff"). Plain and factual: each fund's spending as the
# book prints it, nothing about whether it is enough. {year}: the column's fiscal year; {n}: funds; {amount}: "$..."
fund_split:
  heading: Where each dollar of the city budget goes, by fund
  lede: "How the city's FY{year} adopted budget splits across the {n} funds this site reads from its budget book, in cents of each dollar. A fund is a separate set of accounts the city keeps for one purpose."
  between: "When one of these funds pays another, such as the general fund paying into the health insurance fund, that money is in both funds' spending, as the book prints each fund's budget."
  key_label: "Funds named on the bar, left to right"
  key_note: "Funds that get {n} cents or more of each dollar are named, left to right in the book's order."
  total_line: "This bar is {amount}, the spending the book prints for these {n} funds."   # shown first, then key_note
  list_heading: Every fund
  list_order: in the book's order
  to_dollar: "How the general fund splits across departments"
  sources_toggle: Where these numbers come from
  source: "From {book}, column \"{header}\". No fund in this book prints a total of its spending alone, so each fund's amount is its printed spending totals added up here; each is listed with its page."
  total: "Total: {amount}, the book's own \"TOTAL EXPENSE\" lines of its {runs} report runs added up {cites}. The funds' amounts add up to it exactly."
  fund_check: "Each fund's amount and its printed revenue totals together give the fund's printed \"TOTAL\" line to the cent."
  measures: "These are the funds in the book's line-item report. Other parts of the book are not read here (see the note above), so this is not every dollar the city spends."
  between_list: "Revenue lines that other funds print as received from the general fund (\"GF\"), as printed. They are not taken out of the total, because the book does not print a matching general fund line for each of them:"
  # rounding, then rounding_exact or rounding_moved(_one) ({sum}: the shares rounded to the nearest tenth, added up;
  # {names}: the rows shown other than their nearest tenth; {way}: way_less or way_more)
  rounding: "Cents are each fund's share of the total in tenths of a cent: each share is cut to the tenth below, and the tenths left over go to the shares with the largest remainders (a tie to the larger share), so they add up to exactly 100.0 and each is less than a tenth of a cent from its exact share."
  rounding_exact: "Each is also its share rounded to the nearest tenth."
  rounding_moved: "Rounded to the nearest tenth they would add up to {sum}, so these rows each show one tenth {way} than their nearest tenth: {names}."
  rounding_moved_one: "Rounded to the nearest tenth they would add up to {sum}, so this row shows one tenth {way} than its nearest tenth: {names}."
  way_less: less
  way_more: more
  order: "Funds are in the order the book prints them. The bar, the list and the table show the same rows in that order."
  zero: "Printed with no spending in \"{header}\" ({n}):"
  members: "Spending totals as printed ({n})"
  member_one: "Spending total as printed"
  dollar_members: "Its {n} department totals are listed under the general fund bar below."
  caption: "Cents of each city budget dollar, in tenths of a cent, by fund, FY{year} adopted budget"
  col_fund: Fund
  col_cents: Cents of each dollar
  col_source: Source
  total_row: Total of these funds
  printed_as: "Printed as"
  cents_many: "{n} cents"
  bar_label: "The city budget dollar as a bar, 100 cents wide. The list below holds the same figures."
```

How the copy renders with today's data (for review; the engineer checks the built page reads exactly so):
- Heading: "Where each dollar of the city budget goes, by fund"
- Lede: "How the city's FY2026 adopted budget splits across the 14 funds this site reads from its budget book, in cents
  of each dollar. A fund is a separate set of accounts the city keeps for one purpose." then `between`.
- Under the bar: key "74.9¢ General fund · 6.9¢ Debt service · 12.3¢ Health insurance"; keynote, total first as
  under the general fund bar (2026-11-18): "This bar is $221,059,845.77, the spending the book prints for these 14
  funds. Funds that get 5 cents or more of each dollar are named, left to right in the book's order."
- Sources: "From Fiscal Year 2026 Budget (Final Submission), column "2026 2nd Readin". ..."; "Total: $221,059,845.77,
  the book's own "TOTAL EXPENSE" lines of its 2 report runs added up (p. 137; p. 138). ..."; the FY2027 note from
  `dollar.newer_note`: "The newest book read here, FY2027 (as presented 5/29/2026), prints a proposed budget for that
  year, not an adopted one, so this uses the FY2026 adopted budget."; rounding: "... Rounded to the nearest tenth they
  would add up to 99.9, so this row shows one tenth more than its nearest tenth: Traffic camera, police."

The fund definition is the glossary's `fund` entry, worded for the city.

## 5. Components and contract

No schema change; reads `finance.json` as is. New and changed files:
- `config/localities/clarksville-tn/fund-split.yml` (new):
  ```yaml
  book: fy2026-final
  column: "2026 2nd Readin"
  body: city
  dollar_fund: general-fund          # budget_views.fund_key of the fund the general fund bar splits
  from_general_fund: {accounts: ["34801", "34811", "34821", "39150"], label_token: "GF"}
  funds:                             # every fund the book prints, in its order: name as printed -> plain name
    - {printed: "General Fund", name: "General fund"}
    - {printed: "Drug Enforcement", name: "Drug enforcement"}
    - {printed: "Police Special Revenue", name: "Police special revenue"}
    - {printed: "Traffic Camera Pol SRF", name: "Traffic camera, police"}
    - {printed: "Traffic Camera Parks SRF", name: "Traffic camera, parks"}
    - {printed: "Road Improvements Fund", name: "Road improvements"}
    - {printed: "Parks Special Revenue", name: "Parks special revenue"}
    - {printed: "Special Revenue Fund", name: "Special revenue"}
    - {printed: "Debt Service Fund", name: "Debt service"}
    - {printed: "Parking Commission", name: "Parking commission"}
    - {printed: "Dental Fund", name: "Dental insurance"}
    - {printed: "Health Insurance Fund", name: "Health insurance"}
    - {printed: "Self-Insurance Fund", name: "Self-insurance"}
    - {printed: "Vehicle Replacement Fund", name: "Vehicle replacement"}
  ```
- `sitegen/fund_split.py` (new): `load(locality) -> dict | None` (every key present, as property_tax.load; two funds
  may not share `printed` or `name`); `split(bg: Budget, cfg: dict | None, dollar: dict | None = None) -> dict | None`
  (None only when cfg is None; a config whose book is missing raises: fund-split/silent-hide; `dollar`: the general
  fund bar's view, for the dollar-match check and the link down, as built: 2026-11-18); `fact_ids(fin, locality) ->
  set[str]`.
  Reuses `dollar_split._cell`, `_exact_in_column`, `_newer_books_note`, `slug`, `T_LABEL_MIN`, `T_PHONE_MIN`,
  `property_tax.tenths_text`, `fin_checks.total_of`, `parts_add_up`, `tenths_of_dollar`. No `sum()`, no sort by
  amount (the existing `test_no_sum_or_amount_sort_*` pattern).
- View returned by `split` (template contract): `heading, lede, between, key, key_note, total_line, source, total_before,
  total_after, total_srcs (one per run TOTAL EXPENSE), fund_check, measures, between_list, between_lines [{fund, label,
  amount (as printed), href, src}], rounding, order, note (newer book, or None), zero, rows, total (usd), total_cents
  ("100.0"), caption, t, book_id, total_fact_id`. Row: `key (slug of printed), name, printed, printed_as (bool), value
  (cents), amount (usd), amount_printed (cents_text), tenths, cents ("74.9"), cents_words, moved, labelled (>= 50
  tenths), narrow (< 100 tenths), short, href (its fund page, the printed TOTAL <fund> row), fund_src (PDF page of that
  line), members [{label, amount, page, href, src, line_id}] ([] for the dollar fund), to_dollar (bool), fact_id`.
- Fact ids: `funds/<book>/<printed fund slug>` and `funds/<book>/total`; `qa/site_checks.finance_fact_ids` adds
  `fund_split.fact_ids` beside the other two.
- `site/templates/_funds.html.j2` (new): a copy of `_proptax.html.j2`'s structure and `.dollar` styles (no new CSS
  expected): lede + `between`; bar; key; keynote with total line; "Every fund" list (general fund row links to
  `#general-fund-dollar` with `to_dollar`, others link to their fund page); closed sources block with source, total
  line and its two PDF cites, notes (fund_check, measures, rounding, order, note), the between-funds list, and the table
  (fund, cents, amount as printed under the column header with its kind link, source: member totals with pages, or
  `dollar_members` for the general fund). Section `id="city-funds-dollar"`, `aria-labelledby="city-funds-h"` (as
  built: `funds-h` is already the id of the index's Funds table heading).
- `site/templates/fin_index.html.j2`: include `_funds.html.j2` after the property tax include and before `_dollar`.
  The view is passed as `fundsplit` (as built: `funds` is already the index's fund list).
- `sitegen/build.py` `render_budget`: a `funds_cfg` argument, `fund_split.load(<city locality>)` for the city call
  only, the same silent-hide guard as the other two bars; `general_fund_dollar=False` builds also skip it.
- `sitegen/budget_views.py`: `usd(cents: int) -> str` ("$" + cents_text, ".00" dropped; never negative here).

## 6. Invariants (problem-key family `fund-split/*`; the build fails otherwise)
1. `fund-split/fund-list`: the config's `funds` are exactly the book's fund names (lines with `fund_name` set), in the
   book's order (first page, then row), each once.
2. `fund-split/covered-once`: per fund, every spending detail line is in exactly one section total's
   `scope_line_ids`; across the book, every spending detail line is in exactly one run TOTAL EXPENSE's scope.
3. `fund-split/exact`: every section total, fund net total and run TOTAL EXPENSE used is not held and is `exact` in the
   column (`_exact_in_column`); no section total is negative; every cell read is `adopted`, of one fiscal year.
4. `fund-split/fund-net`: per fund, for each printed fund net total N: `parts_add_up(the fund's revenue and spending
   section totals whose scope lies inside N's scope, N)`. Per-run form, so a book that prints one fund over several
   runs (FY2027) still checks.
5. `fund-split/run-total`: for each run TOTAL EXPENSE E (fund_name None, statement expenditure): the spending section
   totals inside E's scope add up to E exactly; the bar total is the run TOTAL EXPENSE amounts added
   (`total_of`), and equals the funds' amounts added. A book with no run TOTAL EXPENSE fails (FY2025's glyph book
   prints none; it is not used).
6. `fund-split/no-double-count`: a row's amount is built only from spending section totals (`row_role` total,
   statement expenditure, `fund_name` set): never a revenue, subtotal, net or run total line; no line id feeds two rows.
7. `fund-split/between-list`: the account/label cross-check of section 3 holds both ways.
8. `fund-split/stale-book` and `fund-split/silent-hide`: as sections 11 and 12.
9. `fund-split/dollar-match`: the `dollar_fund` row's amount equals the general fund bar's `value_total` when both are
   built from the same book and column (they are today); a mismatch fails the build.

## 7. Tests (new `tests/test_fund_split.py`, real data, as the other two bar tests do)
- Book/column: uses `fy2026-final` "2026 2nd Readin", kind adopted FY2026; never "2027 Mayor"; the newer-book note
  names FY2027 and "proposed budget".
- Amounts: the 14 rows equal the section 2 table to the cent, in that order, each with the listed section line ids.
- Sums exact: rows add up to 22,105,984,577 cents == p137/r11 + p138/r24; each fund + its revenue totals == its net
  line; tenths add up to 1000, each within a tenth of its exact share, Traffic camera, police named as moved; key is
  exactly General fund, Debt service, Health insurance.
- General fund row == the general fund bar's total (165,631,658.00) and links to `#general-fund-dollar`.
- No double count: every spending detail line of the book is reached once through the rows' members (plus the
  general fund bar's members for the general fund); no row uses a `fund_name` None line; the bar total equals the
  printed TOTAL EXPENSE lines, not a figure with anything taken out; the between-funds list is exactly the 10 lines of
  section 3 and none of them changes any row amount.
- Failure cases (mutated copies of the real data, as `test_dollar_split.py` does): a held, not-exact or negative
  section total; a detail line left out or counted twice; a fund in the book missing from config or out of order; a
  run TOTAL EXPENSE that does not add up; a "GF" label under another account, and an account 34801 line without "GF";
  a newer adopted book; config book missing -> raises; partial config fails to load.
- Page (built site): the section is on `city/finance/index.html` only, before `#general-fund-dollar`; every row and the
  total have a `data-fact-id` known to `qa/site_checks.finance_fact_ids`; every amount in the table links to its fund
  page row and its PDF page (each member, each between-funds line, both TOTAL EXPENSE cites); the list has 14 items in
  book order; `FIN_BANNED` finds nothing in the section; no `sum(` or amount sort in `sitegen/fund_split.py`.

## 8. County page (question 6)
Recommendation: not now, no scope added. Mechanically it is small (the county book `fy2027-approved` reads 7 funds,
each with its own printed "Total Expenditures <FUND>" line, adding up to 284,899,917: the `printed` path, no checks
to invent). But the county budget book read here does not carry the school funds (the property tax bar's config has
`fund: null` for both school funds), and schools are the largest part of county spending; an "every fund" county bar
would show the county general fund as most of each dollar with schools absent, right below a bar showing schools at
17.6 cents of each property tax dollar. That needs the school budget read first. Recorded as a follow-up, not asked.

## 9. Risks
- Readers may add the city's general fund and health insurance figures and think the city spends both; mitigated by the
  `between` sentence at a glance and the list in the sources block. If review finds that insufficient, the next step
  is a second, clearly labelled figure (each fund's spending less its printed GF receipts) only after the CEO says so:
  it is a figure the book does not print.
- "City budget" overstates scope if read alone (Gas & Water, CDE and others are not read); the lede says "the 14 funds
  this site reads", and the existing not_covered note sits right above.
- The FY2027 file has one run per department and no Debt Service Fund; when an adopted FY2027 book arrives, the
  per-run checks (invariants 4-5) are written to hold for that layout (verified: all 40 FY2027 fund net totals and 39
  run TOTAL EXPENSE lines pass the per-run form today), but the fund list will differ and the config must move.
- Page weight: 14 rows and about 40 member links; well under the index page budget (the general fund bar lists more).

## 10. Task list (one engineer: `backend-engineer`, also doing the template; sequential)
| # | Task | Depends | Done when |
|---|---|---|---|
| T1 | `fund-split.yml` and `fund_split` text block, exactly as sections 4-5 | - | files committed; `yaml.safe_load` clean |
| T2 | `sitegen/fund_split.py` (load, split, fact_ids) + `budget_views.usd` | T1 | invariants 1-9 enforced; split of the real data equals section 2 |
| T3 | `_funds.html.j2`, `fin_index` include, `build.render_budget` wiring and guard, `site_checks.finance_fact_ids` | T2 | city/finance shows the bar above the general fund bar; county page unchanged byte for byte |
| T4 | `tests/test_fund_split.py` (section 7) | T2, T3 | all pass; full suite, typecheck, lint, build green |
| T5 | Docs: a short section 13 in `docs/architecture/finance-contracts.md` pointing here; glossary unchanged (fund entry exists) | T4 | preflight output (tests, build, page smoke, accessibility scan, link check) pasted in the PR |
Review: `code-reviewer` (sonnet/medium is enough: no auth, secrets, CI or deploy); the bar is a new public number on a
Daylight page, so `qa-engineer` checks the rendered copy against section 4 and the figures against section 2.
