# Platform facts (verified 2026-11-07 unless marked)

## Montgomery County, TN
- Site montgomerytn.gov (also mcgtn.org, d6.mcgtn.org for old files). robots.txt: `User-agent: * / Disallow:` (allows all). Verified by fetch.
- Commission agendas and resolutions: https://montgomerytn.gov/commission/agenda, monthly informal + formal PDFs, 2006 to 2026.
  Pattern (2016+): `mcgtn.org/storage/departments/commission/agendas-and-resolutions/YYYY/mon-informal.pdf` / `mon-formal.pdf`. Some links on the page are wrong (e.g. Oct 2023 formal points to informal).
  Verified 2026-11-10 by the collector's fetcher (collector/county_agenda.py): 482 agenda links in year tables (`<h3>YYYY</h3>`,
  then "January ( Informal | Formal )" cells; "YYYY Special Called Agendas" tables); some 2026 links are relative
  (`/storage/...`, so on montgomerytn.gov). Jun to Nov 2026 agendas are real PDFs (7 to 36 MB, 59 to 270 pages, a text
  layer); Dec 2026 informal and formal are 6,097-byte placeholders. Page 1 prints "BOARD OF COMMISSIONERS ... AGENDA
  <MONTH D, YYYY>" (formal) or "INFORMAL COMMISSION MEETING ... <MONTH D, YYYY>"; the agenda list (numbered resolutions
  and zoning cases) ends at ADJOURN on page 2 or 3. Dates do not always follow the Monday pattern (Oct 19 formal, Sep 8
  informal, a Tuesday).
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

## Regional Planning Commission (verified 2026-11-10 by the collector's fetcher, crawl-delay 10; RPC-1)
- Listing: one page, https://www.cmcrpc.com/documents/agenda-minutes/ (WordPress, 222 KB). robots.txt `User-agent: *`,
  `crawl-delay: 10`, no Disallow; the fetcher reads it every run. Tables of rows "date [– label] | Agenda | Minutes
  [| video]"; the label names the body (CDRB, Executive Committee, Special Called) and "*CANCELLED*". A cell that prints
  "Agenda" or "Minutes" with no link means not posted; "N/A" means none.
- Fetched 2026-11-10 (`python -m collector rpc fetch`): 97 listed meetings (58 RPC regular, 30 CDRB, 5 Executive
  Committee, 4 special called), 2022-01-25 to 2026-10-27; 187 links: 169 distinct PDF/DOCX URLs on www.cmcrpc.com
  (168 stored: 80 agendas, 88 minutes, one of them the DOCX; the 2022-08-23 minutes PDF is over the fetcher's 50 MB
  limit and was not stored), 16 on drive.google.com (listed, never requested; mostly 2024), 1 YouTube video (listed,
  not shown). About 30 s a file through the sandbox relay, so a full fetch took about 30 minutes.
- Source errors seen (kept as listed): the 2025-10-27 CDRB row's minutes link is the 2025-07-29 RPC minutes; the
  2026-07-28 row's minutes file is named 07.23.2026. A URL listed twice is fetched once.
- RPC agendas are text PDFs (FileMaker). Each case is a numbered paragraph "1. Z - 19 - 2026 OWNER(S): ... REQUEST: ...
  LOCATION: ... CO. COMM. DISTRICT: N CITY COUNCIL WARD: N NUMBER OF ACRES: ..." (2025: "1. CASE NUMBER: Z - 29 - 2025
  APPLICANT Name"). Prefixes seen: Z, ZO (city zoning), CZ, CZO (county zoning), S (subdivision), V (subdivision
  variance), SR (site review), LA (landscape appeal), AB (abandonment). "UPCOMING (ZONING) MEETINGS DATES/TIMES" lists the
  Council and Commission hearing dates. Some agendas leave out a "CASE TYPE:" heading (2026-08-25 prints S- plats under
  COUNTY ZONING), so the case type is read from the prefix. The one CDRB agenda with text (2025-02-24) numbers its
  design review cases MSCD- and DDR- ("APPLICATION OF :", "REASON FOR THE REQUEST:", "LOCATION OF REQUEST :").
- Text layers: 60 of the 167 PDFs have text on every page, 2 on some, 105 none (22 of the 23 stored CDRB agendas and 83 of
  the 88 minutes are image scans with no text; read by OCR since RPC-2, below). One agenda prints another year: the 2025-04-11 Executive Committee agenda says
  "April 11, 2023" (kept as listed, reported by the build).
- Read (`python -m collector rpc build`): 57 agendas with text, 1,260 case items (931 distinct case numbers; SR 447,
  Z 344, S 218, CZ 113, V 45, AB 38, ZO 38, CZO 8, LA 5, MSCD 2, DDR 2), each with its agenda page; 52 agendas list
  upcoming Council and Commission hearing dates. 2022-2023 agendas use another layout ("CASE NUMBER: Z-73-2022
  APPLICANT(S): ... AGENT: ...", hearing dates as "CITY COUNCIL INFORMAL: 10/27/2022 - 4:30 P.M.", cases separated by
  rows of asterisks, the text layer sometimes splitting a word: "APPLIC ANT/OWNER", "LOC ATION"). 61 cases lack an
  applicant, request or location as read (most are text amendments, which print no location).
- RPC-2 (verified 2026-11-10, `python -m collector rpc build` with the county minutes' OCR path, tesseract 300 dpi):
  1,514 scanned pages OCRed in about 16 minutes on 4 cores (cached in data/ocr/, so a rebuild takes about 30 s). The
  22 scanned CDRB agendas give 56 more cases (1,341 in all; the 1,285 text-layer cases are unchanged by the stricter
  watermark skip and the numbered-line completeness count); they also number cases DO- (corridor overlay design
  review, from 2025-11) and HZ- (historic zoning). 87 of 89 minutes read are attached to their meeting; two print
  another meeting's date (the 2025-10-27 CDRB row links the 2025-07-29 RPC minutes; the 2025-04-11 Executive
  Committee minutes print "April 25, 2025") and are not attached. 1,307 motions read, 1,088 confirmed by the written
  rule in collector/rpc_minutes.py (mover, seconder, nays and abstentions each match one member in the minutes' own
  header, an outcome from a fixed vocabulary, nothing unmodelled). Minutes layouts: 2022-2024 "Mr. Hadley made the
  motion ... Mr. Powers seconded. Mrs. Streetman voted nay. ... Motion passed."; 2024-06 "Commissioner X"; 2025-2026
  full names, "except X who voted against", "Motion passes for approval 5-1"; CDRB "DDR-14-2026" alone on a line.
  Seen on the scans: Z read as "2" ("CASE NUMBER 2-16-2022"), S as "S$" or "$", a member's name spelled two ways in
  one document ("Maria Jiminez" in the header, "Mrs. Jimenez" in a motion), a motion "for disapproval" whose
  outcome reads "Motion for approval passed" (2023-12-21, CZ-20-2023), a page printed in a shifted font
  ("YRWHG LQ IDYRU", 2025-05-27); none of these is repaired or confirmed. Of the 92 County Commission CZ-/CZO- items
  we hold, 69 match an RPC agenda case by exact number (87 RPC agenda entries link, a case appearing on several
  agendas); the 23 unmatched are 2020-2021 cases (before the RPC listing starts) and CZ-1 to CZ-6-2024 and CZO-1-2024,
  which are on no RPC agenda we read (why not checked).

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
- mcgtn.org redirect (verified by fetch 2026-11-12, `server: cloudflare`): every path, robots.txt included, answers `301` to `http://montgomerytn.gov/<same path>` (plain http). The collector requests that hop as https on the same host and path (fetch/redirect-http-upgrade); before that fix the http Location made mcgtn.org's robots.txt unreadable, so CI disallowed the whole host (county agenda PDFs, FY2024-25 book).
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

## Meeting video (checked 2026-11-09)
- City Council (CivicClerk API, verified): past events carry `mediaSourcePathMp4`, a public MP4 on https://cpmedia.azureedge.net/clarksvilletn/<id>.mp4 (e.g. Regular Sessions 2026-09-03, 10-01, 11-05; also Executive Sessions). `youtubeVideoId` is empty and there are no closed-caption files. The api host robots.txt: `User-agent: *` Allow /, `Content-Signal: search=yes, ai-train=no, use=reference`; named AI crawlers (ClaudeBot etc.) are disallowed. Our collector uses its own honest UA, reference use only, no training (Brian approved CivicClerk collection 2026-11-09).
- County Commission: YouTube (Brian 2026-11-07). The YouTube terms forbid downloading, so no county audio source yet (to research).

## CivicClerk, City Council 2024 on (verified 2026-11-09 by the collector's fetcher, 10 s apart; ADR 0003)
- Listing: `GET https://clarksvilletn.api.civicclerk.com/v1/Events?$filter=categoryName eq 'City Council' and startDateTime ge 2024-01-01T00:00:00Z&$orderby=startDateTime asc`; 15 events a page, `@odata.nextLink` with a `$skiptoken`. 154 City Council events 2024-01-04 to 2029-11-01 (future meetings are listed with no files). The API has events back to 2013 (video only for most).
- `startDateTime` is the local time printed with a `Z` (the 6 PM session is `T18:00:00Z`): take the date as printed.
- Files: `publishedFiles[]` (`type` Agenda, Minutes or Other, `fileId`, `name`, `publishOn`); bytes from `GET /v1/Meetings/GetMeetingFileStream(fileId=<id>,plainText=false)` (application/pdf). 2024 on: 81 agendas, 33 minutes, 2 Other ("Drainage Presentation" 2024-10-21, "Voting File" 2026-04-02; not fetched). `GET /v1/Meetings/{agendaId}` gives agenda items as JSON (not used).
- Video: `mediaSourcePathMp4` is a full https URL on cpmedia.azureedge.net for 65 of the 74 2024-on events with media; 9 carry a bare storage path ("stream/CLARKSVILLETN/<uuid>.mp4") with no documented public URL (not kept).
- Minutes are born-digital text (Aspose.Words). Shapes: 2024 to Feb 2025 as the Agenda Center's ("PRESENT: Brian Zacharias (Ward 1), ..."); 2025-03-06 surnames with wards; from 2025-04-03 surnames in capitals with the mayor in the list ("PRESENT: BROWN, CHANDLER (left at 7:22 pm), ..., PITTS, ...") and vote lists in capitals over several lines. Items print as "A.   ORDINANCE 05-2025-26 ..." (outline letter first), as the Agenda Center's 2022-2023 minutes do.
- Source errors seen: the 2024-09-05 event's Minutes file is the 2024-08-01 minutes (same bytes, fileIds 2223 and 2232); the 2025-02-06 attendance list stops after "Stacey Streetman"; "PRESENT: PRESENT:" (2025-01-02); misspelt names in vote lists (ZAHARIAS, CAHNDLER, H AYWOOD, ...); CLAUNCH (seated 2026) is never printed with a first name as a member (Feb 2026 lists "Mr. Eric Claunch" among Ward 2 applicants only).
- City Council Special Sessions can be filed under category **"General"**, event name "Special Session" (verified
  2026-11-11, one listing query 2026-02-06..03-04): the 2026-02-11 Special Session (resumed 2026-02-19) has agenda
  fileId 2887 and minutes fileId 3068, whose page 1 prints "City Council - Special Session" and page 3 "Eric Claunch was
  selected as the Ward 2 replacement and was sworn in by Mayor Pitts." Our `City Council` category filter misses it.
- More council meetings under "General", by other names (verified 2026-11-11: the full General listing 2024-01-18 to
  2027-01-19, 374 events, 25 pages, plus page 1 of each candidate's agenda and minutes): "City Council Special Session"
  (2025-02-18, 2026-02-19, 04-06, 05-07, 06-29, 07-06, 07-09), "... - First/Second Reading of the Budget"
  (2025-06-17, 06-24), "Special Called City Council Meeting" (2025-11-12, 2026-04-29), "Special Budget Session"
  (2026-06-16), "Special Session - 1st Reading of the Budget" (2026-06-22), all page 1 "City Council - Special
  Session"; "Special Session and First Reading of the Budget" (2026-06-11) and "Special Work Session - Budget"
  (2026-05-26), page 1 "City Council - Special Work Session"; "Regular Session" (2026-07-02, event 4252), page 1 "City
  Council - Regular Session". "One Time Event" is used by other bodies (2024-07-09 ACT Authority, 2025-04-16 Public
  Safety Committee). The 2026-02-19 event's minutes (fileId 3069) are the 2026-02-11 minutes again (same sha256), and
  its agenda heads "City Council - Special Session (Continuation of Special Session Meeting Recessed on ...". The
  events filter's `contains(eventName,'...')` is case-insensitive ('session' returns "Special Session").
- Text-layer quirks (verified 2026-11-11 with `pdftotext -bbox`): 2020-10-01 p.1 has a U+200B zero-width word between
  touching glyphs "J" and "eff" (the page shows "Jeff Henley"); 2022-04-07 p.1 prints "StaceyStreetman" with no gap
  (a source typo); 2026-03-05 prints "H AYWOOD" with a 3.3 pt gap.
- Overlap with the Agenda Center: one meeting (2024-01-04 Regular Session; the Agenda Center has its agenda only, CivicClerk its minutes). CivicClerk also holds minutes for 2023 meetings the Agenda Center lacks (2023-11-02, 2023-12-07 at least; not collected, from_date is 2024-01-01).

## CivicClerk, city Finance and Audit committees (verified 2026-11-16 by the collector's fetcher, 10 s apart; C1)
- Same API, listing and file URLs as the council (`categoryName eq 'Finance Committee'` / `'Audit Committee'`,
  15 events a page). From 2019-01-01: Finance 117 events (2019-04-04 to 2026-12-28; 105 with an agenda, 57 with
  minutes), Audit 29 events (2019-01-17 to 2025-02-03; 23 with minutes). The survey's 49 Audit events include ones
  before 2019 (not collected: from_date 2019-01-01). Some events carry an "Agenda Packet" file type (not fetched).
- Finance minutes 2019-2026 and Audit minutes 2024 are text PDFs (6 sampled). Finance votes are voice votes ("A voice
  vote was taken and the motion passed"), with a dissent printed now and then ("Councilman Henley voted "nay."",
  "(Councilman Lovato was a no vote)"); Audit prints "The motion was approved unanimously." No AYE/NAY name list was
  seen in the sample. Attendance by name: "Present: Streetman, ... Zacharias (arrived at 5:10 pm)", 2019 full names,
  Audit "Audit Committee members present: ...". Audit headings carry U+200B after each number.
- The 2026-05-26 Finance event's minutes (fileId 3197) are byte-identical to the 2025-05-27 event's (fileId 2590,
  sha256 d5277eb0...): a mis-attached file, printing "May 27, 2025".
- Event names may print another date than the event (2020-04-27 "Audit Committee Agenda 4-24-20", 2021-05-25
  "... May 24, 2021"), and the Finance category holds other bodies' budget reviews (2024-05-07 "Public Safety
  Committee FY25 Budget Review", "Gas & Water Committee FY25 Budget Review Mtg", 2024-05-10 Parks & Recreation).
- Video: 61 events carry only bare `stream/CLARKSVILLETN/<uuid>.mp4` paths (no public URL): none kept.

## County Committee Agendas page: school board and county finance committees (verified 2026-11-16 by the collector's fetcher, 10 s apart)
- https://montgomerytn.gov/code/webshare/commission-committees-agendas.php, one HTML page (47 KB): `<dl><dt>Folder</dt>
  <dd><ul><li><a href=...>` per body; the Regional Planning Commission's `<dd>` nests three empty sub-folders before its
  one link. Links are relative paths with spaces (`/storage/departments/mayor/calendar-files/School System/...`).
  robots.txt: allow all, no crawl-delay (10 s kept). Current calendar year only (2026 on 2026-11-16).
- Collected folders and counts: School System 21 (Study Session + Formal Board, 2026-01-13 to 2026-11-17), Budget
  Committee 12 (to 2026-11-18, one SPECIAL CALLED), Budget Hearings 10 (2026-04-09 to 05-12; 05-05 at 9AM and 1PM),
  Audit 1, Committee on Investment 2, Purchasing 3 (one "(rescheduled)"), Delinquent Tax Sales and Release 1. All 50
  are text PDFs of 1 page (45) or 2 pages (5), 57 to 238 KB; every printed date matched the file name.
- File-name dates seen across the page: MM-DD-YY, MM-DD-YYYY, M-D-YYYY, YYYY-MM-DD, MMDDYY, YYMMDD, "01 08 2026",
  "5-19- 26", "November 12, 2026"; one name has no day ("Sports Authority Liaison - September 2026", not collected).
- Budget Committee agendas print County Commission resolution numbers (26-2-1 ...) and county zoning cases
  (CZ-22-2025, with the applicants' names). School board formal agendas print a "Point of Pride Awards" list naming
  students and staff, presenters' names on study-session items, and a right-hand "Policy Reference" column (GP-5,
  EL-3, presenters' surnames). No school board item text is stored, only the count of lines
  (docs/architecture/agenda-withhold-invariant.md).
- No minutes and no votes for any of these bodies on montgomerytn.gov. CMCSS minutes: cmcss.net (Cloudflare challenge,
  not collected). 2025 agendas: d6.mcgtn.org (blocked by this environment's network policy; not fetched).

## City ward map (verified 2026-11-10; traced for the landing's ward lookup)
- Source: RPC "City Council Wards" 36x36 poster, https://www.cmcrpc.com/wp2025/wp-content/uploads/2026/02/ClarksvilleCityWardsPoster.pdf (listed on https://www.cmcrpc.com/maps/, "Updated February 25, 2026"; Last-Modified 2026-02-25). Fetched once with the collector's PoliteFetcher (robots.txt, then the PDF, crawl-delay 10 obeyed; 2 requests) by `tools/fetch_map.py`; bytes in the Store, listed in `data/maps/manifest.json` (sha256 742f2c13...). Not used: APSU/county ArcGIS (needs written permission).
- The poster is an ArcGIS Pro vector export in Tennessee State Plane, north up (no rotation, x/y scale ratio 1.00005, 9.83 m per pt). Each ward is one filled ring per part (16 parts, outline colour 0/0.149/0.451), each fill colour repeated once in the legend beside "N - <member>". Ward numbers are read two ways that must agree: the legend's leading number per colour, and the large printed ward number inside each fill. Member names are never read or stored.
- Method (`tools/extract_ward_poster.py`): affine fit, projected metres to poster page, from 11 control points (crossings of two named roads, TIGER node vs the crossing of the drawn centre lines), 14 held-out check points (`config/localities/montgomery-tn/wards-georef.json`, `tools/georef_fit.py`). RMS 0.9 m, worst leave-one-out 2.3 m, worst check point 1.8 m. The ward rings are moved into the county map's page space (poster page -> State Plane -> `georef.json`), so one georef places an address on both layers and the district fit's own error cancels. Simplified to 0.12 pt and rounded to 0.1 pt: max 4.8 m from the unsimplified trace.
- Independent checks: the 32,002 sampled points of the poster's drawn roads lie a median 0.38 m (p90 2.2 m) from TIGER road lines; the 2025 TIGER Clarksville place outline lies a median 0.3 m from the poster's city outline, 93.5% within 10 m. The rest is annexation timing (0.36 km2 in the wards but not in TIGER 2025, 0.06 km2 the other way, of 261.5 km2).
- Expected error and margin: 76 m = transform 3 + trace 5 + poster export 3 (judgment) + Census geocoder 65 (judgment call, as for the districts: no measurement of the geocoder's error against known addresses backs the 65 m, and rural and new-subdivision segments, where the Census address ranges are interpolated or missing, may be worse). An address within 76 m of a ward line or the city line is answered "near a ward line": check with the Election Commission or GoVoteTN.
- Accuracy evidence: no public record we hold ties an address to a ward (city agendas and minutes print no ward for zoning cases or property items; council members' addresses are not used). So the tests use the poster: each ward's printed number plus 3 named-street crossings per ward, all at least 250 m inside the ward, 48 points, all answered with the poster's ward (`tests/test_ward_map.py`); 8 were also checked by eye on rendered crops. Confidence: high that the lookup reproduces the poster to within about 10 m; medium that the poster matches the legal ward lines everywhere (it is RPC's map, not the Election Commission's; annexations after 2026-02-25 are not on it).

## Morning note provider (Buttondown; seen 2026-11-16 by Brian with the team)
The T4.0 probe (`scripts/morning-note-probe.ps1`, run once on 2026-11-16 at 18:54 CT on the **live** newsletter,
username `daylight`, free plan, team addresses only; results file `results-20261116-1854.json` in the project files,
no address or id in it) plus Brian's inbox checks. Brian is on the free plan and will not pay (2026-11-16).
- **API, free plan:** no paid-feature refusal from any call. Subscriber `metadata` can be written: `PATCH
  /v1/subscribers/{id}` answers 200, **replaces** the whole object (does not merge) and echoes the stored metadata.
  `X-Idempotency-Key` is honoured on PATCH and POST. A scoped key read `/tags` (200) and was refused
  `/newsletters` (403).
- **Settings UI:** "Subscriber metadata is only available for accounts on the Basic plan or higher" (Settings >
  Metadata). The API accepted metadata anyway. There is no preferences page where a subscriber can edit fields.
- **Stamp mode works.** A `scheduled` email filtered on `subscriber.metadata.note_edition equals <value>` reached
  exactly one recipient (analytics: recipients 1, deliveries 1); Gmail showed it reached only the second address.
  The probe file's manual answer "runbook-1 ... => no" is wrong; the right answer is yes.
- **A scheduled email holds:** status `scheduled` with 337 s to go, `sent` after `publish_date`. `PATCH` with
  `{"status": "draft"}` takes a scheduled email back to a draft.
- **`ids` mode does not work.** `POST /v1/emails/{id}/send-draft` sends only a "[PREVIEW]" copy to the account
  owner; the email stays a draft. (The probe's "probe 4 reached the first address" is most likely that preview:
  inference, not checked.) Also, an `ids` draft comes back with `filters: {"filters":[],"groups":[],"predicate":"and"}`,
  not without filters, so the probe's ids checks fail on that too.
- **Templates are on.** `{{ subscriber.email }}` in a body showed the address (Brian answered "renders literally",
  but the email showed the address). The sender neutralises `{{` and `{%` in every record title (already built).
- **Listings:** `GET /v1/subscribers` and `/v1/emails` are `{results, next, count}`; count equals rows; the email
  listing holds drafts and scheduled emails with their `metadata`, oldest first. The **default subscriber listing
  does not include unconfirmed (form) sign-ups**: to see every type, ask for each type.
- **Public form** (`https://buttondown.com/api/emails/embed-subscribe/daylight`):
  - an **existing** subscriber: 302 to buttondown.com, and the post **does** set `metadata__note_edition` and
    `metadata__canary`; re-submitting changes a confirmed subscriber's metadata;
  - a **new** address with `metadata__lists`, `metadata__district`, `metadata__ward`, `metadata__note_edition` and
    `metadata__canary`: HTTP 400, no subscriber created. Likely cause: the free plan refuses metadata on form
    sign-ups. Unproven: the Buttondown firewall had IP filtering off at the time.
- **Consequence (2026-11-17):** the sign-up form posts no `metadata__` field. Lists, district and ward go as
  Buttondown tags (`tag` fields: `note-zoning`, `note-district-5`, `note-ward-3`); the sender reads only those tags,
  and metadata holds only the sender's stamp. **Unverified until the first real sign-up:** that the free plan's form
  accepts `tag` on a new address (and adds several when several `tag` fields are posted), that a new tag name is
  created on the fly, that a form sign-up gets double opt-in, and that the API returns `tags` as a list of names.
- **Probe scoring (not changed):** the script scored `stamp_checks_pass: false` for three reasons: the wrong manual
  runbook-1 answer above; `runbook-8` (the form sets `note_edition` on an existing subscriber), which the design
  now accepts because the stamp carries a MAC (architecture "Switch-on: tags, and the security notes"); and the
  new-subscriber form check, which never ran (the 400). The probe has done its job and is not run again, so the
  scoring is left as is; read it with this section.
- **Privacy policy (seen 2026-11-17 by the security reviewer):** `https://buttondown.com/legal/privacy` is
  Buttondown's privacy policy; for subscriber data it points to their data processing agreement (DPA). Config
  `privacy_url` is that address.
- **Unverified: `archival_mode` in the create answer** (render/archival-not-echoed). Nothing on record shows that
  `POST /v1/emails` answers with `archival_mode`, so the echo check compares it only when present (it must then be
  `disabled`). Check it on the first real send (the stored email in the dashboard is off the public archive).
- **Email listing filter (sender/claim-listing-unbounded):** the probe's `GET /emails?creation_date__start=<that
  day>` answered 200 with all 4 of that day's emails, so the filter keeps the day's rows. Whether it leaves older
  rows out is unproven (there were none). The sender asks for emails created since yesterday; ignored, the listing
  is the whole history (still correct, bounded by the adapter's page limit).

## GitHub repository settings (checked 2026-11-17 by `gh api` from the team's session, signed in with admin rights)
- `main` has **no ruleset and no branch protection** yet: `repos/gn0sh/clarksville-records/rulesets` is `[]`,
  `rules/branches/main` is `[]`, `branches/main` says `protected: false` (runbook `docs/ops/morning-note.md` 2.0 not
  done yet).
- The repository is public and allows squash, merge-commit and rebase merges; `delete_branch_on_merge` and
  `allow_auto_merge` are off (so the daily `push` job deletes its own `data/` branch after merging).
- Not readable from the team's session: the Actions settings (`actions/permissions/workflow`, so whether **Allow
  GitHub Actions to create and approve pull requests** is on) and the environments list (both refused by the
  session's proxy).
- From `github/docs` search snippets (the docs site itself was unreachable): the **Allow GitHub Actions to create
  and approve pull requests** setting is used "to configure whether `GITHUB_TOKEN` can create and approve pull
  requests"; events caused by `GITHUB_TOKEN` "will not create a new workflow run" (newer docs: a PR it opens creates
  `pull_request` runs in an approval-required state; this repository has no `pull_request` workflow).
- **Unverified:** that `GITHUB_TOKEN` can squash-merge its own PR under the 0-approval "pull request required"
  ruleset with no bypass, and that the REST field `can_approve_pull_request_reviews` is that same box. The check
  run in runbook 2.0 settles both.
- **How the live site deploys (checked 2026-11-17 for T4.10.5):** the `deploy` job of `daily-update.yml`, on `main`
  only, publishes with `actions/deploy-pages` into environment `github-pages`; Pages source is **GitHub Actions**
  since go-live (2026-11-13, `docs/status.md`), custom domain `daylight.gnoshcodes.com`. Branch `gh-pages` still
  exists (last commit 90ded2e, 2026-11-13, "Preview: build of main 0b01310") but is no longer served. The
  `github-pages` environment's deployment branch list could not be read (the session's proxy refuses
  `environments/` and `pages`), so whether `gh-pages` is still allowed is unverified. Removing `gh-pages` from that
  list leaves `main`'s deploy unchanged; removing `main` would stop it. Brian's step: runbook 2.0.5.

## Main protection (V1 probe, T4.10.1)
- R2 first on: 4c5cd91022b74f5b7ad68ec94cdb863fcc444acd (2026-11-17 ~4:25 PM CT, `scripts/protect-main.ps1` first run on
  Brian's PC, exit 0: `Main before the ruleset` and `R2 was off; main was` both this sha). Ruleset 27502319 active, bypass
  none, rules deletion, non_fast_forward, pull_request (0 approvals); Actions may create pull requests: true;
  auto-merge allowed: false. The baseline window (runbook 4.7.1) starts here.
- Not run yet. When it runs (runbook 2.0.4): the run link, the four merge answers (REST squash, merge, rebase; GraphQL), the review `commit_id` result,
  and `main`'s sha before and after go here.
- `github-pages` deployment branches after runbook 2.0.5: not checked yet.
