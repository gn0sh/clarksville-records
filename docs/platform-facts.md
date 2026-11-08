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
- Budget books: https://montgomerytn.gov/account-budget links two approved books: FY2027 (`/storage/departments/account-budget/FY%202027%20Approved%20Budget.pdf`, 119 pages, 4.5 MB, text layer, Adobe) and FY2024-2025 (mcgtn.org). Each "Estimated Revenue and Available Funds" / "Statement of Proposed Expenditures" page is a clean text table: account code, name, then three years (e.g. FY2025 Actuals, FY2026 Amended, FY2027 Budget), difference and percent; negatives in parentheses, "-" for zero. Funds: General, Drug Control, ARPA, General Roads (Highway), Debt Service, Capital Projects (fund 171, pp. 102-114; pp. 100-101 are Debt Service), Risk Management. So two books give actuals for FY2023 and FY2025 (FY2024 actuals only from the TN Comptroller audit: unverified).
- The FY2027 book also holds the property tax rate history (2007 on), appropriations to non-profits (Schedule 2) and the budget committee roster.
- Purchasing archive: https://montgomerytn.gov/purchasing/archive is one HTML table, 90 rows (architect's full count; my first rough count said 91) (2025-2026 dates), each row = solicitation title (e.g. "BID - WHEEL LOADER"), links (BID PDF, RFP PDF, BID TAB, AWARD LETTER, NOTICE OF INTENT TO AWARD, Q&A), and a date. 71 rows with an award-type document, 56 with a bid-tab link (2 are .docx); six file URLs are shared by more than one row. No department or solicitation number is printed. Summary pages and detail pages in the budget book can disagree (p.28 12,690,651 vs p.33 12,690,251); read detail pages.
- Bid tabs are text PDFs with each bidder and total, "Bid Awarded to" and "Date Bid Awarded" (e.g. Wheel Loader: McCoy Construction & Forestry $189,000.00, Thompson Machinery $211,887.00, awarded 2-26-25). Award letters and notices of intent sampled have NO text layer (scans): OCR needed, same confirmed/not-confirmed rules as votes.
- robots.txt: montgomerytn.gov allows all; mcgtn.bonfirehub.com `Disallow: /` for all agents, so Bonfire is NOT collected (link to it only); comptroller.tn.gov allows all.
