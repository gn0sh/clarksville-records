# Where city and county committee records live (finance and budget first)

Researched 2026-11-11 by deep-researcher. Polite, read-only: robots.txt read on every host before any page; listing
pages, API listings and two sample files only; no bulk download. Never touched cityofclarksville.com.

## Question
Where do City of Clarksville and Montgomery County committee records (agendas, minutes, video) live, especially the
finance and budget committees? What years, counts and formats, and do the minutes carry votes by name? Feeds: what
to collect in the Nov 18 batch, and in what order.

## Short answer
- **City Finance Committee: CivicClerk is the source to collect.** Category "Finance Committee" (CivicClerk id 27)
  has 117 events from 2019-04-04 to 2026-12-28 (future ones listed with no files), with agendas and most minutes
  as text PDFs. The Agenda Center's Finance Committee board covers the same span only to Dec 2023 (2019 rows have
  the same titles as CivicClerk's), so it is a fallback, not a second source.
- **City Finance minutes record mostly voice votes.** Votes by name ("AYE: Holleman, McLaughlin, Streetman,
  Zacharias / NAY: Smith") appear only on divided items. Attendance is by name.
- **City Audit Committee:** CivicClerk id 44, 49 events, newest 2025-02-03; Agenda Center board to Oct 2023.
- **County Budget Committee: agendas only, 2026 only, on montgomerytn.gov.** The "Committee Agendas" page lists 11
  Budget Committee agendas (2026-01-21 to 2026-10-19) plus 10 Budget Hearing files, all under
  `montgomerytn.gov/storage/departments/mayor/calendar-files/<Folder>/`. No committee minutes and no video are
  posted on any county page we found. 2025 and earlier agendas show up in search on `d6.mcgtn.org`, whose
  robots.txt could not be read (see Robots).
- **Video:** the city's CivicClerk Finance events carry only bare `stream/CLARKSVILLETN/<uuid>.mp4` paths (no public
  URL); county committee video was not found (the county's YouTube channel is linked for Commission meetings only).

## Observations (each with a link)

### City: CivicClerk API (clarksvilletn.api.civicclerk.com)
- 40 event categories ([EventCategories](https://clarksvilletn.api.civicclerk.com/v1/EventCategories)). Event counts
  per category ([groupby page 1](https://clarksvilletn.api.civicclerk.com/v1/Events?$apply=groupby((categoryName),aggregate($count%20as%20n))),
  pages 2 and 3 with `&$skip=15`, `&$skip=30`). All rows, as id: name (events):
  40 Access Management Board of Appeals (64); 59 ACT Authority (25); 41 Adult Oriented Establishment Board (11);
  42 After Hours Establishment Board (11); 43 Airport Authority (22); 63 Arts & Heritage Board (9); **44 Audit
  Committee (49)**; 45 Beer Board (97); 34 Board of Zoning Appeals (102); 26 City Council (541); 46 Clarksville Housing
  Authority (4); 47 Common Design Review Board (28); 48 Convention & Visitors Bureau (16); 35 Designations Committee
  (5); 49 Economic Development Council (67); 50 Ethics Commission (17); 51 Fair Housing Board (3); **27 Finance
  Committee (117)**; 52 Gas & Plumbing Board (5); 28 Gas & Water Board (76); 24 General (404); 53 Housing & Community
  Development Committee (34); 36 Human Relations Commission (47); 54 Joint Economic & Community Development Board (14);
  55 Land Development Advisory Committee (3); 56 Legislative Liaison Committee (17); 61 Museum Board (12);
  29 Neighborhood and Community Services Committee (53); 37 Parking Commission (109); 30 Parks & Recreation Committee
  (86); 57 Power Board (79); 58 Public Art Commission (2); 31 Public Safety Committee (96); 38 Regional Planning
  Commission (95); 64 Restoring Clarksville (10); 62 Roxy Regional Board (22); 60 Senior Board (20); 32 Sustainability
  Board (23); 33 Transportation, Streets, Garage Committee (97); 39 Tree Board (66). (Counts include future events.)
- Finance Committee, oldest first ([asc](https://clarksvilletn.api.civicclerk.com/v1/Events?$filter=categoryName%20eq%20%27Finance%20Committee%27&$orderby=startDateTime%20asc&$count=true)):
  `@odata.count` 117; first event 2019-04-04 "Finance Committee Agenda 4-4-19", agenda + minutes ("136a-Finance
  Agenda 4-4-19", "136m-Finance Minutes 4-4-19"). Of the first 15 (2019-04-04 to 2019-10-03), 12 have minutes; none
  has media.
- Finance Committee, newest first ([desc](https://clarksvilletn.api.civicclerk.com/v1/Events?$filter=categoryName%20eq%20%27Finance%20Committee%27&$orderby=startDateTime%20desc&$count=true)):
  2026-12-28 and 2026-11-23 listed with no files; 2026-10-26, 09-21, 07-27, 06-22 agenda only; 2026-05-26, 04-27,
  03-23, 02-23, 01-23 and 2025-09-22, 08-25, 07-28, 06-23 agenda + minutes. No events between 2025-09-22 and
  2026-01-23. Meetings are monthly, 4:30 PM printed as `T16:30:00Z`. 9 of the 15 carry `mediaSourcePathMp4` as a bare
  path `stream/CLARKSVILLETN/<uuid>.mp4`; none a full URL.
- Sample Finance minutes, [fileId 3197](https://clarksvilletn.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=3197,plainText=false))
  (listed on the 2026-05-26 event): text; prints "Finance Committee ... May 27, 2025 at 5:00 PM", "Present:
  Streetman, Lovato, McLaughlin, Shakeenab, Zacharias (arrived at 5:10 pm)", "Absent: None"; votes as "A voice vote
  was taken and the motion passed"; items are ordinances and resolutions on first look before Council (e.g. Ordinance
  84-2024-25, Resolutions 59 and 60-2024-25) and department reports (Purchasing bid summary, monthly financials,
  Electricity, City Attorney invoices). The date printed does not match the event it is listed on (a mis-attached
  file, like the council's 2024-09-05 one; read by a summariser, so verify).
- Audit Committee, newest first ([desc](https://clarksvilletn.api.civicclerk.com/v1/Events?$filter=categoryName%20eq%20%27Audit%20Committee%27&$orderby=startDateTime%20desc&$count=true)):
  count 49; newest 2025-02-03; about quarterly; 2021-04-28 to 2025-02-03 shown, 10 of 15 with minutes, 2023-02-01
  and 2022-10-26 agenda only; one bare media path (2021-04-28).
- `$apply=groupby` with `$count` works on this API; `aggregate(... with min ...)` returned plain events or an empty
  array (not usable for first/last dates).

### City: Agenda Center (www.clarksvilletn.gov/AgendaCenter)
- [Agenda Center](https://www.clarksvilletn.gov/AgendaCenter) lists 39 boards. Newest entry per board, as listed:
  Access Board of Appeals 2024-01-18; Adult Oriented Establishment Board 2023-09-26; After Hours Establishment Board
  2023-07-11; Airport Authority 2023-10-25; Arts & Heritage Council 2024-02-09; **Audit Committee 2023-10-25**; Beer
  Board 2024-05-13; City Council 2024-01-11; Clarksville Housing Authority 2024-01-17; Common Design Review Board
  2023-11-20; Convention & Visitors Bureau 2024-03-01; Designations Committee 2023-10-23; Economic Development Council
  2024-01-18; Ethics Commission 2022-12-06; Fair Housing Board 2022-08-22; **Finance Committee 2023-12-18**; Gas &
  Plumbing Board 2023-05-02; Gas & Water Committee 2024-01-18; Housing & Community Development Committee 2024-01-08;
  Human Relations Commission 2023-12-06; Joint Economic & Community Development Board 2024-01-10; Land Development
  Advisory Committee 2021-08-20; Legislative Liaison Committee 2023-08-09; Miscellaneous Meetings 2021-08-13; Museum
  Board 2024-01-23; Parking Commission 2024-01-16; Parks & Recreation Committee 2024-01-09; Power Board 2024-01-16;
  Public Art Commission 2020-07-13; Public Safety Committee (Building & Codes, Fire, Police) 2024-01-17; Regional
  Planning Commission 2024-01-23; Senior Citizens Board 2024-03-12; Sports Authority 2019-09-18; Streets & Garage
  Committee 2021-03-23; Sustainability Board 2024-01-23; Transportation Committee 2020-10-28; Transportation-Streets-
  Garage Committee 2024-01-09; Tree Board 2024-05-08; Zoning Appeals Board 2024-01-03. Newest anywhere: 2024-05-13.
- **Category ids are not visible** through our fetch tool (it strips HTML attributes). Only City Council = 3 is known
  (collector fixture `collector/tests/fixtures/city/search_2019_excerpt.html`, `id="cat3"`). The ids are in the
  `id="catN"` / `aria-controls="category-panel-N"` attributes of the one /AgendaCenter page.
- Finance Committee years: [search 2016-2019](https://www.clarksvilletn.gov/AgendaCenter/Search/?term=Finance&CIDs=all&startDate=01/01/2016&endDate=12/31/2019&dateRange=&dateSelector=)
  shows 21 rows, all 2019 (first 2019-04-04 "Finance Committee Agenda 4-4-19", 14 with minutes); no earlier year tab.
  [Search, all dates](https://www.clarksvilletn.gov/AgendaCenter/Search/?term=Finance&CIDs=all&startDate=&endDate=&dateRange=&dateSelector=)
  shows the newest year only: 14 rows in 2023 (2023-01-24 to 2023-12-18), 10 with minutes; year tabs 2023, 2022,
  2021, "View More". Audit Committee: 2019-04-24 and 2019-10-30 (both with minutes), newest 2023-10-25 with minutes.
- Budget rows elsewhere: "CDE Budget & Finance Committee Mtg. Agenda - April 18, 2023" sits under Power Board
  (agenda only). City Council category already holds budget-review rows ("FY21 Amended Budget Committee Review -
  September 21/22/23, 2020", "Finance Committee Budget Review Mtg Notice", "Finance Committee Agenda - June 26, 2023";
  in `data/localities/clarksville-tn/listing.json`).
- Sample Finance minutes, [_10232023-1579](https://www.clarksvilletn.gov/AgendaCenter/ViewFile/Minutes/_10232023-1579)
  (2023-10-23): text; "PRESENT: Stacey Streetman, Travis Holleman, Deann McLaughlin, Wanda Smith, ..."; most votes
  "A voice vote was taken; the motion passed without objection."; one divided vote by name "AYE: Holleman,
  McLaughlin, Streetman, Zacharias" / "NAY: Smith"; mover and seconder named; items: prior minutes, pay tables, FY2024
  budget amendment ordinance (first reading), utilities fee ordinance, a $41.5M revenue bond resolution.
- Swagit ([clarksvilletn.new.swagit.com](https://clarksvilletn.new.swagit.com/)): "Clarksville, TN Video Archive";
  categories City Council, Committees/Specialty, Budget Meetings; the home page shows 2014 videos and
  [/specialty](https://clarksvilletn.new.swagit.com/specialty) only 2013-2014 promotional videos. No Finance
  Committee video seen.

### County: montgomerytn.gov
- [Committee Agendas](https://montgomerytn.gov/code/webshare/commission-committees-agendas.php) (linked from
  [public-calendar-info](https://montgomerytn.gov/gov/public-calendar-info)): one section per body, files under
  `https://montgomerytn.gov/storage/departments/mayor/calendar-files/<Folder>/<file>.pdf`, no year folders, 2026 dates
  only, **no minutes links, no video links**. Finance-related: **Budget Committee 11** (2026-01-21 to 2026-10-19,
  incl. a 07-23-2026 special called), **Budget Hearings 10** (2026-04-09 to 2026-05-12), **Audit Committee 1**
  (2026-06-02), **Committee on Investment 2** (2026-02-03, 2026-08-04), **Purchasing Committee 3** (2026-01-14 to
  2026-07-23), Delinquent Tax Sales and Release 1 (2026-09-29), Alternate Finance System Study 0. Others with files:
  County Commission 24, Building & Codes 6, Rules 4, Parks 3, Personnel Advisory 1, Nominating 8, Legislative Liaison
  7, Loss Control 6, EMS 12, Fire 7, Jail & Juvenile 3, Courts Center 2, Ethics 2, Public Records 2, Zoning Appeals 6,
  and outside boards (IDB 10, EDC 12, School System 20, Library 10, E-911 7, ...). File names mix date formats
  (MM-DD-YY, MM-DD-YYYY, MMDDYY, YYMMDD, YYYY-MM-DD) and carry labels like CANCELED or rescheduled.
- Sample [Budget Committee Agenda 01-21-2026](https://montgomerytn.gov/storage/departments/mayor/calendar-files/Budget%20Committee/Budget%20Committee%20Agenda%2001-21-2026.pdf):
  text (read as text); "BUDGET COMMITTEE MEETING JANUARY 21, 2026"; approval of the 2025-12-17 minutes (not
  attached); CZ-22-2025 and Resolutions 26-2-1 to 26-2-8 (the numbers the Commission's February agenda uses);
  consent and discussion items; no members named, no video.
- [Commission committees](https://montgomerytn.gov/code/webshare/commission-committees.php): one membership PDF per
  committee (e.g. "Budget Membership - January 2026.pdf", "Audit Committee Membership - September 2026.pdf") under
  `.../storage/departments/mayor/commission-committees/`; no schedules, agendas or minutes.
- [County Commission minutes](https://montgomerytn.gov/clerk/county-commission-minutes): only Commission minutes
  (55 links, Jan 2022 to May 2026); nothing for committees. [Commission agenda](https://montgomerytn.gov/commission/agenda):
  Commission agendas only; video link is the [YouTube channel](https://www.youtube.com/channel/UColCy-INQM4uZSqrJCeHTGg)
  "Commission Meeting Videos".
- Search results list 2025 Budget Committee agendas on d6.mcgtn.org, e.g.
  [1-21-2025](https://d6.mcgtn.org/sites/default/files/mayor/calendar-files/Budget%20Committee/Budget%20Committee%20Agenda%201-21-2025.pdf),
  3-26, 4-22, 7-22, 8-20, 9-24, 10-21, 11-19, 12-17-2025 (not fetched).
- Commission informal agendas already in our data carry sections "RESOLUTIONS ADDED AFTER BUDGET COMMITTEE (Must
  Suspend the Rules)" (`data/county-agendas/agendas.json`).

## Robots findings (all read 2026-11-11)
| Host | Result | Effect |
|---|---|---|
| www.clarksvilletn.gov | `*`: admin/search/RSS/map etc. disallowed, Crawl-delay 10; AI/SEO group (ClaudeBot, Claude-SearchBot, GPTBot, ...) same paths plus calendar/bids/faq, no delay; Baiduspider, Yandex `Disallow: /`; Siteimprove delay 20. /AgendaCenter not disallowed for any group. Claude-User not named. | Agenda Center OK at 10 s |
| clarksvilletn.api.civicclerk.com | `*` Allow /, Content-Signal search=yes, ai-train=no, use=reference; ~35 named AI crawlers `Disallow: /` (ClaudeBot, Claude-Web, anthropic-ai); no Crawl-delay | Collect as ADR 0003, own UA, 10 s |
| clarksvilletn.portal.civicclerk.com | Same shape: `*` Allow /, 32 named crawlers disallowed, no Crawl-delay | Not needed (API suffices) |
| montgomerytn.gov | `User-agent: *` / `Disallow:` (allow all), no Crawl-delay | OK, use 10 s anyway |
| mcgtn.org | 302 to montgomerytn.gov (page); robots not read separately | Treat as montgomerytn.gov |
| d6.mcgtn.org | robots.txt fetch failed at the site ("client_error"; status code not shown) | **Hold**: collector must read robots and get a clean answer first; a 403 stops it (as dev2) |
| clarksvilletn.new.swagit.com | robots.txt has only comments (`Disallow: /` commented out); clarksvilletn.swagit.com/robots.txt 302s there | Allowed, but nothing current to collect |

Pacing: about 30 requests in all (clarksvilletn.gov 6, CivicClerk API 10, montgomerytn.gov 9, others 6), one at a time
per host. The fetch tool cannot sleep, so the 10 s gap was not timed; each call waited for the previous one to finish
and be summarised (typically longer than 10 s, not measured).

## Table per body
"Votes by name" = do the minutes print each member's vote. "Format" from samples (text = text layer).

| Body | Source | Years | Count | Format | Votes by name in minutes |
|---|---|---|---|---|---|
| City Finance Committee | CivicClerk API, category 27 | 2019-04 to 2026-10 (+ future) | 117 events (incl. 2 future without files) | text PDFs | Partial: voice votes; by name only on divided items |
| City Finance Committee | Agenda Center (cat id unknown) | 2019-04 to 2023-12 | 2019: 21, 2023: 14, 2020-2022 not counted | text PDFs | Same as above (2023-10-23 sample) |
| City Audit Committee | CivicClerk, category 44 | to 2025-02-03 (start unverified) | 49 | not sampled | Unknown |
| City Audit Committee | Agenda Center | 2019 to 2023-10 | 2019: 2 | not sampled | Unknown |
| City budget reviews (Council) | Agenda Center cat 3 (already collected listing) | 2020, 2023 rows seen | few | text | Not checked |
| City other committees (Gas & Water 28, Parks 30, Public Safety 31, Transportation 33, Neighborhood 29, Housing 53, Legislative Liaison 56) | CivicClerk | unverified start | 76, 86, 96, 97, 53, 34, 17 | not sampled | Unknown |
| County Budget Committee | montgomerytn.gov calendar-files | 2026 only (Jan to Oct) | 11 agendas, 0 minutes | text PDF | No minutes online |
| County Budget Committee | d6.mcgtn.org calendar-files (search hits) | 2025 (at least 9 seen) | unknown | not fetched | No minutes online |
| County Budget Hearings | montgomerytn.gov calendar-files | 2026-04 to 05 | 10 | not sampled | No minutes online |
| County Audit / Investment / Purchasing | montgomerytn.gov calendar-files | 2026 | 1 / 2 / 3 | not sampled | No minutes online |
| County committee video | none found | - | - | - | - |

## Inferences
- CivicClerk is a superset of the Agenda Center for the Finance Committee (same first meeting, same titles
  "Finance Committee Agenda 4-4-19", minutes on both, CivicClerk continuing past Dec 2023). **High.** So collect the
  Finance Committee from CivicClerk only, and use the Agenda Center just to check for gaps.
- The city migrated its boards' history into CivicClerk, so CivicClerk ids replace Agenda Center ids for all boards.
  **Medium** (shown for Finance; other boards not compared).
- City committee minutes will give attendance by name for every meeting but votes by name only for split votes; most
  items read "voice vote ... passed". A committee vote should be shown as "voice vote, passed" with attendance, never
  as each present member voting yes. **High** (two samples, 2023 and 2025, agree).
- Extending `config/localities/clarksville-tn/civicclerk.yml` from one `category_name` to a list, plus committee
  kinds and a "voice vote" outcome, is most of the work; the fetcher, file URL and pagination are unchanged.
  **Medium** (based on the config, not the code).
- County Budget Committee minutes exist (agendas approve the prior meeting's minutes) but are not posted online; the
  Commission minutes may summarise committee reports. Getting them would need a records request, a hard stop
  (acting outside the repo). **Medium.**
- The county page shows only the current year; 2025 and earlier live on d6.mcgtn.org, and the 2026 page will likely
  roll over in January, so 2026 files should be collected before then. **Medium.**
- The 2026-05-26 CivicClerk event's minutes file prints 2025-05-27: a source mis-attachment to keep as listed and
  report, as the council collector does. **Medium** (one summarised read).

## Unknowns
- Agenda Center category ids for all boards except City Council (3); Finance Committee rows per year for 2020-2022.
- CivicClerk first year for Audit and the other committees; whether CivicClerk Finance minutes from 2019-2023 are the
  same files as the Agenda Center's.
- Why CivicClerk has no Finance events Oct to Dec 2025 (cancelled, or filed under another category such as General).
- Public URLs for the bare `stream/CLARKSVILLETN/...` media paths (not guessed, per civicclerk.yml).
- d6.mcgtn.org robots status code; whether committee agendas before 2025 exist anywhere online.
- Whether the county YouTube channel posts Budget Committee meetings (not checked: YouTube terms forbid download;
  a link-only listing would need its own check).
- Whether the Budget Committee agenda PDF has a true text layer (read through a converter, which hides scan vs text).

## Recommended collection order for the Nov 18 batch
1. **City Finance Committee, CivicClerk, 2019-04 on.** Generalise `civicclerk.yml` to several categories; add a
   committee minutes path that records attendance, mover/seconder, voice-vote outcomes, and name lists only when
   printed. About 117 events: ~8 listing pages plus ~180 files at ~30 s each through the relay = ~1.5 h fetch.
   Effort: 1 to 1.5 days (backend), QA half a day.
2. **City Audit Committee, CivicClerk** (49 events): config only once step 1 lands; ~25 min fetch; 1-2 h.
3. **County Budget Committee + Budget Hearings agendas, 2026, montgomerytn.gov** (21 files): new listing parser for
   `commission-committees-agendas.php` (folder per body, mixed date formats); link resolution numbers (26-2-1) to the
   Commission agendas we hold. Agendas only, no votes. ~15 min fetch; 0.5 to 1 day.
4. **Other city committees on CivicClerk** (Gas & Water, Parks, Public Safety, Transportation, Neighborhood, Housing,
   Legislative Liaison: ~460 events): config only; ~3 to 4 h fetch; run after step 1 is reviewed.
5. **Hold:** d6.mcgtn.org (robots unread), Agenda Center Finance (duplicate; gap check only), city committee video
   (bare paths), county committee minutes (not online; a records request is a hard stop).

Total for steps 1-3: about 2 to 3 engineer-days plus review and QA; fetch time about 2 h, run unattended.

## Sources
- https://www.clarksvilletn.gov/robots.txt
- https://www.clarksvilletn.gov/AgendaCenter
- https://www.clarksvilletn.gov/AgendaCenter/Search/?term=Finance&CIDs=all&startDate=&endDate=&dateRange=&dateSelector=
- https://www.clarksvilletn.gov/AgendaCenter/Search/?term=Finance&CIDs=all&startDate=01/01/2016&endDate=12/31/2019&dateRange=&dateSelector=
- https://www.clarksvilletn.gov/AgendaCenter/ViewFile/Minutes/_10232023-1579
- https://clarksvilletn.api.civicclerk.com/robots.txt
- https://clarksvilletn.portal.civicclerk.com/robots.txt
- https://clarksvilletn.api.civicclerk.com/v1/EventCategories
- https://clarksvilletn.api.civicclerk.com/v1/Events (Finance and Audit filters, groupby counts, as linked above)
- https://clarksvilletn.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=3197,plainText=false)
- https://clarksvilletn.new.swagit.com/ , /specialty , /robots.txt
- https://montgomerytn.gov/robots.txt
- https://montgomerytn.gov/commission/agenda
- https://montgomerytn.gov/mayor/committee-and-board-information
- https://montgomerytn.gov/code/webshare/commission-committees.php
- https://montgomerytn.gov/gov/public-calendar-info
- https://montgomerytn.gov/code/webshare/commission-committees-agendas.php
- https://montgomerytn.gov/storage/departments/mayor/calendar-files/Budget%20Committee/Budget%20Committee%20Agenda%2001-21-2026.pdf
- https://montgomerytn.gov/clerk/county-commission-minutes
- https://montgomerytn.gov/calendar
- d6.mcgtn.org Budget Committee 2025 agenda URLs (web search results only, not fetched)
- Repo: docs/platform-facts.md, config/localities/clarksville-tn/civicclerk.yml, agenda-center.yml,
  data/localities/clarksville-tn/listing.json, data/county-agendas/agendas.json
