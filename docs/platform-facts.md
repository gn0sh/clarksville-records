# Platform facts (verified 2026-11-07 unless marked)

## Montgomery County, TN
- Site montgomerytn.gov (also mcgtn.org, d6.mcgtn.org for old files). robots.txt: `User-agent: * / Disallow:` (allows all). Verified by fetch.
- Commission agendas and resolutions: https://montgomerytn.gov/commission/agenda, monthly informal + formal PDFs, 2006 to 2026.
  Pattern (2016+): `mcgtn.org/storage/departments/commission/agendas-and-resolutions/YYYY/mon-informal.pdf` / `mon-formal.pdf`. Some links on the page are wrong (e.g. Oct 2023 formal points to informal).
- Commission minutes: listed at https://montgomerytn.gov/clerk/county-commission-minutes (production) for 2022 to May 2026
  (55 links on 2026-11-07), files on `montgomeryminutes.bisonline.com/viewpdf.php?id=<encoded>`; pre-2020 via that site's
  search. The dev2 host listed 2020-2024 but now answers 403 (see below). In the 59 documents read, every link label matched
  the meeting dated in the text; each 2022-2026 document also nests the previous meeting's minutes for approval.
- Minutes record roll-call votes per commissioner by name (e.g. "Rickey Ray Y") and absences ("ABSENT: ... (2)"). Verified on Dec 2024 minutes.
  Minutes do not name vendor awards. They name who moved and seconded each item, but record no spoken comments or discussion.
  Items carry numbers like 24-12-1 or AB-4-2024. The PDFs are scans with an OCR text layer, which has errors (verify numbers and names).
- Budget: https://montgomerytn.gov/account-budget (FY2025, FY2027 approved budget books). Audits: TN Comptroller, 2001-02 on.
- Purchasing: bids on https://mcgtn.bonfirehub.com/portal/ and https://montgomerytn.gov/purchasing/archive. Award visibility: unverified.
- Operator: Brian Zacharias serves on Clarksville City Council until the end of 2026 and leaves it after the new year (Brian, 2026-11-07). He is not a candidate.
- Video: YouTube. Brian (2026-11-07): the chair calls on each speaker by name; on City Council video the members' names are visible on screen (county unverified).

## City of Clarksville, TN
- Official site is **clarksvilletn.gov** (CivicPlus). `cityofclarksville.com` blocks automated tools: never collect from it or work around it.
- clarksvilletn.gov robots.txt: /AgendaCenter and /DocumentCenter allowed; RSS.aspx, Search, Bids.aspx, Calendar disallowed for AI bots;
  Crawl-delay 10 for `*`. Respect 10 s between requests for every bot name.
- Agenda Center: 39 boards incl. City Council and Finance Committee, year selectors to 2016; minutes only on some meetings; newest entry May 2024
  (newer council meetings are probably posted elsewhere: unverified, to find).

### Agenda Center, City Council (verified 2026-11-09 by the collector's fetcher, 10 s apart)
- robots.txt at https://www.clarksvilletn.gov/robots.txt (re-read 2026-11-09; a block was "added 2026-10-21 by Add-RobotsRules"):
  `User-agent: *` disallows /activedit, /admin, /OJA, /support, /search.asp(x), /Search, /CurrentEvents*, /map.asp(x),
  /RSS.aspx, /error.aspx, /404.aspx, /common/modules/icalendar/, /publiclogin.aspx; **Crawl-delay: 10**. Baiduspider and
  Yandex: Disallow /. A group of ~21 named AI and SEO crawlers (ClaudeBot, Claude-SearchBot, GPTBot, CCBot, ...) gets
  the same paths plus /calendar.aspx, /rssfeed.aspx, /civicalerts.aspx, /bids.aspx, /faq.aspx, and no Crawl-delay.
  Our User-Agent matches only `*`. /AgendaCenter (listing, search and ViewFile) is allowed; `/Search` is a prefix rule
  that does not cover /AgendaCenter/Search. The fetcher checks every URL with robotparser and waits 10 s per host.
- City Council is Agenda Center category 3. The category page shows the newest year only; other years load by a POST
  to /AgendaCenter/UpdateCategoryList (one GET of it reset the connection; not used). The Agenda Center's own search
  page answers a GET per year: `/AgendaCenter/Search/?term=&CIDs=3&startDate=01/01/YYYY&endDate=12/31/YYYY&dateRange=&dateSelector=`.
- Listed City Council rows 2016-2024: 314 (2016 32, 2017 32, 2018 32, 2019 33, 2020 44, 2021 52, 2022 33, 2023 54,
  2024 2; the newest is 2024-01-11). 168 rows have a minutes link (none after Oct 2023). The category also lists
  executive sessions, special and work sessions, Ethics Code Review committee meetings and budget-review notices.
- Files: `/AgendaCenter/ViewFile/Agenda/_MMDDYYYY-<id>` and `/ViewFile/Minutes/_MMDDYYYY-<id>`, served as PDFs.
  All 168 minutes fetched 2026-11-09 are born-digital text (no scans). Of 292 agendas fetched, 237 have a text layer,
  41 are OCR text (scanner producer or OCR font) and 1 has none; 13 agenda packets are over the collector's 50 MB limit
  and were not stored. The 314 listed meetings span 2016-01-04 to 2024-01-11.
- Collected 2026-11-09 (`python -m collector city fetch --agendas`, then `build`): 305 meetings in facts (9 left out:
  no fetched file to cite), 168 minutes read, 1,859 roll calls (1,526 verified, 82.1%), 22,327 votes by name, 767
  motions, 31 officials. Held roll calls name the failed check (misspelt names, members missing from a vote with no
  note, outcomes the text contradicts, attendance lines that do not parse).
- Minutes format: "PRESENT: Name (Ward N), ..., Name, Mayor Pro Tem (Ward N)" and "ABSENT: ..."; the mayor presides
  ("called to order by Mayor Joe Pitts") and votes. Votes: "AYE: Allen, Burkhart, ..." / "NAY: ..." by surname, then a
  sentence "The motion to ... passed/failed." "NOTE: Councilman X was not present for this vote." marks a member out
  of the room. Consent agendas pass on one vote; per-item abstentions are noted in prose. No tallies are printed.
- Source errors seen (kept as printed, held): misspelled names ("Alllen", "Garett", "Ereb", "Wallace4"), a member
  listed both present and absent (2016-07-07), "passed" on a 5-5 vote, "failed" on an 11-0 vote.
- Connection resets: the sandbox relay drops a tunnel when a page takes more than ~10 s (proxy status
  ws_closed_mid_exchange, nothing received from the site). Not a refusal; the fetcher retries once.

## Existing services
- soar.com "Citizen Portal": AI summaries of Clarksville council meetings with overall tallies, no per-member votes, paywalled video/transcripts.

## Cloud environment
- Default environment allowlist now includes the county, city, BIS Online, Bonfire and comptroller hosts (added 2026-11-07, Brian approved).

## Update 2026-11-07 afternoon
- dev2.montgomerytn.gov index now answers 403 from the site (Cloudflare) to our collector: stopped, never retry by another route.
- Production page https://montgomerytn.gov/clerk/county-commission-minutes lists minutes 2022 to May 2026 (bisonline links). Link labels may not match contents: "Dec 2025" held the Dec 8 2025 packet containing Nov 10 2025 minutes. Date meetings from the text.
- 2025 minutes keep per-commissioner Y/N roll-call tables (verified on the Dec 2025 packet).
- City Council moved to CivicClerk: portal https://clarksvilletn.portal.civicclerk.com/, OData API https://clarksvilletn.api.civicclerk.com/v1/Events (events with publishedFiles Agenda/Minutes). Portal robots.txt: User-agent * Allow /, Content-Signal ai-train=no, use=reference; ~35 named AI crawlers (incl. ClaudeBot) disallowed. Minutes are text PDFs with votes by name ("AYE: BROWN, MARQUIS, PITTS, STREETMAN, ZACHARIAS"); some items list only no votes. Earliest year unverified. Hosts not yet on the allowlist. Policy question before collecting: our collector is not a training or AI search crawler, uses an honest UA, and doesn't train on the data; record that judgment in an ADR before M4.

## Finance and contracts sources (verified 2026-11-08 by fetch with the collector's User-Agent, 10 s apart)
- Budget books: https://montgomerytn.gov/account-budget links two approved books: FY2027 (`/storage/departments/account-budget/FY%202027%20Approved%20Budget.pdf`, 119 pages, 4.5 MB, text layer, Adobe) and FY2024-2025 (mcgtn.org). (Note 2026-11-08: the FY2024-25 book heads its budget-year column "FY 25 Projection"; ADR 0002 amendment stores it as kind adopted, header shown as printed.) Each "Estimated Revenue and Available Funds" / "Statement of Proposed Expenditures" page is a clean text table: account code, name, then three years (e.g. FY2025 Actuals, FY2026 Amended, FY2027 Budget), difference and percent; negatives in parentheses, "-" for zero. Funds: General, Drug Control, ARPA, General Roads (Highway), Debt Service, Capital Projects (fund 171, pp. 102-114; pp. 100-101 are Debt Service), Risk Management. So two books give actuals for FY2023 and FY2025 (FY2024 actuals only from the TN Comptroller audit: unverified).
- The FY2027 book also holds the property tax rate history (2007 on), appropriations to non-profits (Schedule 2) and the budget committee roster.
- Purchasing archive: https://montgomerytn.gov/purchasing/archive is one HTML table, 90 rows (architect's full count; my first rough count said 91) (2025-2026 dates), each row = solicitation title (e.g. "BID - WHEEL LOADER"), links (BID PDF, RFP PDF, BID TAB, AWARD LETTER, NOTICE OF INTENT TO AWARD, Q&A), and a date. 71 rows with an award-type document, 56 with a bid-tab link (2 are .docx); six file URLs are shared by more than one row. No department or solicitation number is printed. Summary pages and detail pages in the budget book can disagree (p.28 12,690,651 vs p.33 12,690,251); read detail pages.
- Bid tabs are text PDFs with each bidder and total, "Bid Awarded to" and "Date Bid Awarded" (e.g. Wheel Loader: McCoy Construction & Forestry $189,000.00, Thompson Machinery $211,887.00, awarded 2-26-25). Award letters and notices of intent sampled have NO text layer (scans): OCR needed, same confirmed/not-confirmed rules as votes.
- robots.txt: montgomerytn.gov allows all; mcgtn.bonfirehub.com `Disallow: /` for all agents, so Bonfire is NOT collected (link to it only); comptroller.tn.gov allows all.

## Budget book layouts (task F9, verified 2026-11-08 by `pdfwords` on every statement page of both books)
- Both books fetched by the collector's polite fetcher into the store (kind `budget_book`, first fetch 2026-11-08):
  FY2027 `src-f6538dd0321b` (119 pages, Adobe Acrobat, text layer) and FY2024-25
  `https://mcgtn.org/storage/departments/account-budget/MONTGOMERY%20COUNTY%202024-2025%20BUDGET%20BOOK%20AS%20APPROVED.pdf`
  `src-8f2a41668955` (108 pages, Microsoft Print To PDF, text layer; mcgtn.org redirects to montgomerytn.gov, robots allows all).
- FY2024-25 matches the FY2027 layout in what the parser rests on: the same three page titles ("Estimated Revenue and
  Available Funds", "Statement of Proposed Expenditures", "... - Consolidated"), fund lines "COUNTY GENERAL FUND 101",
  5-digit account codes, codeless "Salaries & Benefits", "Other Expenditures" / "Capital Expenditures" subtotals,
  "Total <section>", "Total Revenues", "Total Revenues <FUND> <no>", "Total Expenditures <FUND> <no>", right-aligned
  amounts with "-" for zero and parentheses for negatives, capital projects with no heading line.
- It differs in: two-digit years ("FY 23 Actuals", "FY 24 Amended", "FY 25 Projection"); the budget-year column is
  headed "Projection", not "Budget" (config maps it to kind `projected` as printed; see the run report); the derived
  columns are "Increase/Decrease Amount" and "Percentage Change" (FY2027: "Budgeted Difference", "Percent Change");
  consolidated pages have 3 value columns (FY2027: 4, adding "FY 2026 Projections"; ARPA p. 84 prints "FY 2026
  Projected"); pp. 33-34 print one carried-over row above the page title; ARPA consolidated p. 76 says "For the Fiscal
  Year June 30, 2024"; fund 127 is "ARP GRANT FUND" and 266 "WORKER'S COMPENSATION FUND" (FY2027: "RISK MANAGEMENT FUND").
- Pages: FY2024-25 statement pages 29-108 (66 read: 7 consolidated, rest revenue and expenditure; fund dividers and
  summary/chart pages skipped), capital fund 171 on pp. 94-104. FY2027: 78 pages read in 28-119, capital fund pp. 103-114.
- The two books share only fiscal year 2025, as FY2024-25's "FY 25 Projection" and FY2027's "FY 2025 Actuals":
  different kinds, so the edition compare (same fund, code or label, heading, year and kind) finds no pair to compare.
