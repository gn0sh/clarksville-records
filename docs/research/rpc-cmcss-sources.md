# Sources: Regional Planning Commission (RPC) and CMCSS school board (researched 2026-11-10)

Method: 13 requests in total, 10+ s apart, User-Agent `ClarksvilleRecordsBot/0.1 (+https://github.com/gn0sh/clarksville-records)`.
cmcrpc.com: 9 requests; cmcss.net: 3; one attempt at youtube.com (not an allowed host; the sandbox proxy refused it, nothing received).
Nothing was fetched from Google Drive, YouTube, Simbli or BoardDocs.

## Regional Planning Commission (www.cmcrpc.com, WordPress, Apache)
- robots.txt: `User-agent: *` / `crawl-delay: 10`, no Disallow. A WordPress `wp-json` media search would be allowed but was not used.
- The site was rebuilt in 2025: new pages and uploads live under `/wp2025/`; older pages (`/documents/`, `/calendar/`) still answer, and
  `/about/agenda-minutes/` 301-redirects to `/documents/agenda-minutes/`. The home page links `/wp2025/wp-content/uploads/2026/09/RPC-CURRENT-AGENDA.pdf`.
- Where: one HTML page, https://www.cmcrpc.com/documents/agenda-minutes/ (222 KB), lists every document as a link, grouped by meeting
  ("8/19/2024 - CDRB Agenda Minutes"). One GET gets the whole listing. Calendar: `/calendar/` plus `RPC-Calendar-2026-V3.pdf`.
- Bodies on it: RPC (monthly, last Tuesday, 2:00 PM, 329 Main St), Common Design Review Board (CDRB, monthly Monday), RPC Executive
  Committee (rare), special-called RPC meetings.
- Coverage: Jan 2022 to Oct 2026 (169 PDF/DOCX links: 80 agenda, 84 minutes, 48 of them CDRB; by upload year 2022 27, 2023 27, 2024 19, 2025 46,
  2026 50). Nothing before 2022 on that page (unverified whether older files exist elsewhere). Some meetings have an agenda but no
  minutes, or the reverse (2023 Mar-Jun and 2024 Feb-Apr lag). 16 links point at drive.google.com (mostly 2024); that host is not
  allowed, so those meetings would be listed with the link but not read.
- URL patterns (inconsistent, so take links from the page, never build them):
  `/wp-content/uploads/YYYY/MM/Agenda-M-DD-YYYY.pdf`, `RPC-MTG-MIN-M-DD-YYYY.pdf`, `RPC-AGENDA-MM-DD-YYYY.pdf`,
  2025+ under `/wp2025/wp-content/uploads/YYYY/MM/` as `Agenda-MM.DD.YYYY.pdf`, `MM.DD.YYYY_RPC-MTG-MINS.pdf`, `...CDRB...`.
  The upload month is the month after the meeting for minutes. Dates must be read from file names plus the document text.
- Format: PDF with a text layer (2024 minutes: 3 MB, scan with OCR errors: "rharz-70-2023" for Z-20-2023, "Z - os - 2024",
  "CZ-OI - 2OZ4"); 2024 agenda is a text PDF with a "DRAFT" watermark scattered through the text. 2022 agenda: text PDF. One DOCX (2022 exec
  committee agenda). Sizes seen 0.4 to 3 MB.
- Content: agendas list each case (number, applicant/owner, request R-x to R-y, location, tax map, acres, ward, district) and
  upcoming Council and Commission hearing dates. Minutes record attendance, motions with mover and seconder by surname, dissent by
  name ("Mr. Kimbrough voted nay all others were in favor"), and named speakers for and against each case. No staff reports or
  packets are on this page; there is no vote tally apart from "carried unanimously" and named dissent. Video: YouTube channel
  https://www.youtube.com/@CMCRPC (host not allowed here; robots unchecked, so link only).
- Case numbers: `Z-NN-YYYY` city rezoning, `CZ-NN-YYYY` county rezoning, `SR-NN-YYYY` subdivision (RPC agenda, 2024). The
  county commission data already has 90 distinct CZ- numbers in data/facts.json (2020 to 2026), so **CZ links to county
  ordinance/resolution items are straightforward**: exact match on a normalised number (`CZ-1-2021` vs `CZ-01-2024` zero-padding; OCR
  glyph errors need the same repair rule parse.py uses). The county zoning minutes name the same applicant, which gives a second check.
  **Z- (city) numbers do not link directly**: the city facts contain no Z- numbers (0 found; city ordinance titles carry no case
  number in what we hold), so a link would have to use applicant plus location text from the council ordinance body (unverified,
  fuzzy; mark such links "probable" or skip them). Subdivision SR- cases have no counterpart.

## CMCSS school board (www.cmcss.net)
- robots.txt (200): `Disallow: /wp-admin/` (allows admin-ajax) and `/wp-content/uploads/wpo/wpo-plugins-tables-list.json`; names
  `https://www.cmcss.net/wp-sitemap.xml`; no crawl-delay (we would still keep 10 s).
- **Blocked.** The home page and the sitemap both return HTTP 403 with `cf-mitigated: challenge` ("Just a moment...", Cloudflare managed
  challenge, 5.5 KB). That is a bot challenge, not a robots rule. Per our rules we stopped after 3 requests and did not retry,
  rotate agents or use a browser to pass it. robots.txt answered 200, so the challenge applies to pages only.
- Not found, so unknown: where agendas, minutes, packets and video live, formats, history, URL patterns. Typical for Tennessee districts
  (judgment, unverified): board documents on Simbli (eSBMeetings), BoardDocs or Finalsite pages, video on YouTube. None of these was
  fetched; no links could be read because the pages were challenged.
- Ways forward (owner decision needed): (a) ask CMCSS (Brian, a former councilman, may know the board clerk) for an
  allow-listing of our User-Agent or a documents feed; contacting them is acting outside the repo, so it is his call; (b) find the
  board-document host from a source we can read (a web search result, a PDF the board posted elsewhere), then check its robots.txt;
  (c) leave CMCSS out until (a) or (b) works.

## Effort (engineer-days, existing fetcher/OCR/names/verify pipeline reused)
| Item | Days |
|---|---|
| RPC listing parser (one page, group links by date/body, title from file name, fix wrong dates) | 1 |
| RPC meetings + agendas into facts with case rows (Z-, CZ-, SR-; applicant, request, location), tests | 2 |
| RPC minutes: motions, mover/second, nay-by-name, speakers; OCR repair; verification checks like the county's | 2.5 |
| CZ- link to county commission items, show on both sides, Z- probable link spike | 1 |
| Site pages (RPC body, meeting page, case page), QA and docs | 1.5 |
| **RPC total** | **about 8 (6 if it stops at agendas and links, minutes as listed documents)** |
| CMCSS: 1 day discovery once unblocked, then 5 to 8 days for the build; unknown format and host | 6 to 9, **not startable now** |
