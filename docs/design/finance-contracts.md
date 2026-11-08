# Finance and contracts: design spec (slices 1a, 1b, capital projects)

Spec: `docs/specs/finance-contracts.md`. Look and patterns reused from `visual-refresh.md` and `landing-search-nav.md`
(drawer, filter toolbar, `.note`, `.chip`, `source_cell` macro with its Details toggle, `clamp` macro = Show more,
Not confirmed* via `not_confirmed`/`nc_mark`). Private preview, residents are the primary user. All locality text
(county name, book titles, fund names, archive URL, fiscal-year labels) comes from config; names in braces below are
template variables, not literals. Quoted strings are the exact fixed strings (tested by exact match).

## 1. Pages and nav
| Page | File | Nav slot | Slice |
|---|---|---|---|
| Bids and awards (index) | `contracts/index.html` | Bids and awards | 1a |
| Solicitation detail | `contracts/<slug>.html` | none (linked from index) | 1a |
| Finance | `finance/index.html`, `finance/<fund>.html`, `finance/<fund>/<dept>.html` | Finance | 1b |
| Capital projects | `capital/index.html` | Capital projects | 1b |
Drawer order: Finance, Bids and awards, Capital projects. The COMING chip goes away per page as it ships.

## 2. Fixed strings (one source `config/finance_text.yml`; exempt from the banned-words lint)
- **Coverage, contracts pages:** "{n_tab} of {n_total} solicitations have a bid tab; award letters are scans and are linked, not read." Identical on index, detail and anywhere contracts are mentioned.
- **Coverage, budget pages:** "{n_lines} budget lines from {n_books} books; {n_flag} totals do not add up as printed and are marked."
- **Note A:** "A bid total is the amount a bidder wrote on the bid tab. It is not the value of any contract."
- **Note B:** "Notice of intent, award letter and commission approval are separate events. Dates are shown per document."
- **Note C:** "This archive covers sealed solicitations only. Other purchases are not here, so nothing on this page adds up to what the county spent."
- **Note D (capital):** "Capital fund lines are yearly appropriations in the budget book, not the cost of a project."
- **Note E (finance):** "Amounts are whole dollars as printed in the book. Transfers and available funds are listed in their own section and are not revenue or spending. No county-wide total is shown."
- **Edition note** (two books print different figures for one line): "The two books print different figures for this line. Both are shown."
- Coverage sentence sits directly under the h1, always visible. Notes are `.note` blocks (plain border, no colour, no icon), never tooltips. Phone: Note C collapses to "Archive covers sealed solicitations only. More".
- Every page: "Report an error" in the footer line and per row (existing macro). G1 disclosure and vendor-correction link are public-launch gates: leave an empty include slot `_disclosure.html.j2`, not rendered in preview.

## 3. Glossary (`glossary.html`, plus a collapsed "Words used on this page" `<details>` per page, same text)
Alphabetical, one sentence each, no evaluation words. First use in a table links to its entry (`glossary.html#fund`), no tooltips.
- **Actual:** the amount the county's books show was received or spent in a finished fiscal year.
- **Adopted budget:** the budget the commission passed at the start of a fiscal year.
- **Amended budget:** the adopted budget after changes made during the year.
- **Award letter:** a letter from the county to the bidder it chose. Most are scanned images and are linked, not read.
- **Bid tab:** a table listing each bidder and the total it bid. Short for bid tabulation.
- **Capital project:** a building, road or equipment purchase the budget book lists under the capital projects fund.
- **Fund:** a separate set of accounts the county keeps for one purpose, with its own revenue and spending.
- **Notice of intent:** a notice that the county plans to award to a named bidder. It comes before an award letter.
- **RFP (request for proposals):** a document asking companies to propose how they would do work, and at what price.

## 4. Bids and awards index (AC-F7, F8, F10, F13, F15, F16)
Order: h1 "Bids and awards"; coverage sentence; Notes A-C; filter toolbar; table; export links (CSV, JSON); glossary toggle.
- **Filters** (`--surface` toolbar, GET form, URL state like search): "Vendor or title" (one labelled box matching title, department and any bidder name), "Department" (alphabetical), "Year", "Documents" (Any / Has a bid tab / No bid tab), "Clear filters". Result count in `aria-live=polite`; no auto-submit while typing.
- **Sort:** default date, newest first. Select: Date newest / Date oldest / Title A-Z / Department A-Z. No amount or bidder-count sort.
- **Columns (wide):** Date | Solicitation (title, clamped 2 lines) | Department | Documents (links with stage label: "Bid", "Request for proposals", "Bid tab", "Notice of intent", "Award letter", "Questions and answers"; scanned ones add "Scanned") | Bid tab ("Has bid tab" / "No bid tab") | Awardee as printed on the bid tab (blank when no bid tab) | Source.
- **Phone 375px:** one card per row: date and department, title (clamped, Show more), document links wrapped, "Has bid tab / No bid tab", Details toggle holding awardee and fetch date. 25 rows then "Show 25 more" (no-JS fallback: `?page=` links). No horizontal scroll.
```
375px                          1280px
Bids and awards                Bids and awards
32 of 91 solicitations ...     32 of 91 solicitations ... (one line)
[Vendor or title ........]     [Vendor or title][Dept v][Year v][Docs v][Sort v]
[Dept v][Year v][Docs v]       Date  Solicitation  Dept  Documents  Bid tab  Awardee  Source
+---------------------+        2026-10-14 <title> ... Highway [Bid][Bid tab] Has bid tab <name> p.2
| 2026-10-14 Highway  |
| <title clamped> More|
| Bid, Bid tab, Scan  |
| Has bid tab Details |
+---------------------+
```

## 5. Solicitation detail (AC-F3 to F6, F15)
Header: title (h1), department, solicitation number. Coverage sentence. Then:
1. **Documents** table: Stage | Document | Date | Source. Order: document date ascending, ties by the stage order in section 4. Each row links the PDF; fetch date in the Details toggle. Scanned documents show "Scanned, read it yourself" beside the link and no value.
2. **Bid tab** (if one exists): "Bidders and totals as printed". Columns: Bidder | Bid total as printed | Source (p. n). Bidders in the tab's printed order, never by amount. Unit-price tabs: printed total row only, plus a link to the tab page. Below: "Awardee as printed on the bid tab: {name}. Source: bid tab p. n, fetched {date}." If none named: "The bid tab does not name an awardee."
3. Notes A and B. 4. "Related item" row only on an exact stretch match (empty slot now).
Any elected official named on a page links to their vote page via the `person` macro.

**States** (words only; no colour or icon signals good or bad)
| State | Display |
|---|---|
| Has bid tab | section 2 above; index says "Has bid tab" |
| No bid tab | section 2 replaced by "No bid tab was found for this solicitation. Documents are listed above." No amounts, no awardee, no "missing" styling |
| Scanned only | "Scanned, read it yourself" on the row; detail adds "This document is a scanned image. No amount, name or date has been read from it." |
| Documents differ (AC-F4) | `.note` above the bid tab: "Documents differ, read both." with both links and the names of the differing fields only (Awardee, Number of bidders); no explanation, no verdict |
| Total does not add up as printed | total shown as printed with "as printed, does not add up" and the lines it was checked against in a nested table |
| Not confirmed* | `not_confirmed` macro: "Not confirmed*" and "Read it yourself" link, no number |
| Link dead at fetch | row text "Link not available at fetch ({date})" with the archive page link |
| Empty filter result | "No solicitations match. Clear filters." Coverage sentence stays |

## 6. Finance page (slice 1b; AC-F1 to F3, F9, F10, F15)
`finance/index.html`: h1 "Finance"; budget coverage sentence; Note E; book list (title, fiscal year, edition, PDF link, from config; "FY2024 actuals are not in these books." with year from config); fund list in the book's order with account number, identical row layout, no amounts; links to each fund page. A committee roster, if shown, uses `person` so names link to vote pages (AC-F9). No chart, no total tile.
**Fund page** has three tables in this order: Revenue by source, Spending by department, Transfers and available funds (own section; Note E repeated).
- **Column headers** are the book's own header plus kind: `<th scope="col">{book header}<br><span class="kind">{Actual | Amended budget | Adopted budget}</span></th>`, in the book's column order. Caption: "From: {book title}, {edition}".
- Rows: Account | Line as printed (clamped) | one amount cell per column | Source (p. n). Subtotal rows read "Subtotal as printed" with text "Adds up" or "As printed, does not add up" (the latter expands the detail lines it was checked against). Whole dollars, parentheses kept as printed, `aria-label="minus 1,200"` for screen readers; no "K"/"M".
- No year-over-year column, arrow, sparkline or percent. Line absent in a book: en dash plus sr-only "not printed in this book".
- Phone: each line is a card: label (clamped), then definition list "{header} {kind}: $amount", Source link, Details for fetch date. Subtotal cards use a heavier border. Section tables are `<details>` (open on wide, closed on phone, summary = section name and row count).
- States: book not collected "Not collected yet" (no empty table); "This fund is not in {book}."; total mismatch and Not confirmed* as in section 5.
**Department page** uses the same table, with a link back to its fund.

## 7. Capital projects page (slice 1b)
h1 "Capital projects"; coverage sentence; Note D directly under h1; source line "{fund name} ({fund no.}, {book}, pp. {range})" from config. One table: Account | Project line as printed | amount columns as in section 6 | Source. Rows in book order. Filters: "Project name" text and "Book" select. No amount sort, no total across lines, no "cost" column. Name links to its book page; links to a commission item only on an exact "Related item" match. Phone uses cards as in section 6. Same mismatch and Not confirmed* states.

## 8. Accessibility (WCAG 2.2 AA)
- Real `<table>` with `<caption>`, `th scope="col"` and `scope="row"` on the label cell. Phone cards are CSS over the same markup (one DOM), so reading order matches.
- Amounts right-aligned, tabular figures, always text. State is carried by words: greyscale reads the same. Contrast 4.5:1 text, 3:1 borders, light and dark.
- Visible 2px focus ring; Details and Show more are buttons with `aria-expanded`; Show more keeps focus on its button. Tab order: filters, row links, export links, footer. Touch targets at least 44px on phone.
- Works without JS: GET filters, full text without clamp, paging by links.

## 9. QA and lint hooks
Exact-string tests for coverage, Notes A-E, edition note; banned-words lint skips `config/finance_text.yml` and `glossary.html` only; skeleton test (any two solicitations, funds, departments render the same structure); no template sorts by amount or count; every amount has a source link (AC-F3); every elected name links (AC-F9); no horizontal scroll at 360px and narrow side-panel width.

## 10. Data the architect must provide per row
- **Solicitation:** slug, title, number, department, dates; documents [stage, url, doc_date, scanned, fetched]; has_bid_tab; tab_type (lump sum / unit price); awardee_text and awardee_source page; bidders [name, total_as_printed, total_dollars, printed_order, page]; documents_differ [fields, links]; total_check_ok.
- **Budget line:** book_id, edition, fund, section (revenue / spending / transfer / available funds), department, account_no, label_as_printed, row_kind (detail / subtotal), per column [book header, kind, value_dollars, as_printed_text], page, url, fetched, subtotal_check {ok, rows}.
- **Capital line:** as budget line.
- **Live counts:** n_tab, n_total, n_lines, n_books, n_flag; coverage by department and year (AC-F16).

## 11. Decisions and proposed spec changes
- One "Vendor or title" box over title, department and bidder names; the architect's index must match bidder names.
- Unit-price bid tabs show the printed total only in 1a.
- Proposed spec change: awardee moves into Details on phone to meet AC-F10.
- Focus Group skipped (private preview, per spec A-F2); revisit before public launch.
