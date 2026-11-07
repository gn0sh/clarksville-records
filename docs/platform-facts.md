# Platform facts (verified 2026-11-07 unless marked)

## Montgomery County, TN
- Site montgomerytn.gov (also mcgtn.org, d6.mcgtn.org for old files). robots.txt: `User-agent: * / Disallow:` (allows all). Verified by fetch.
- Commission agendas and resolutions: https://montgomerytn.gov/commission/agenda, monthly informal + formal PDFs, 2006 to 2026.
  Pattern (2016+): `mcgtn.org/storage/departments/commission/agendas-and-resolutions/YYYY/mon-informal.pdf` / `mon-formal.pdf`. Some links on the page are wrong (e.g. Oct 2023 formal points to informal).
- Commission minutes: listed at https://dev2.montgomerytn.gov/clerk/county-commission-minutes (dev host) for 2020-2024, files on
  `montgomeryminutes.bisonline.com/viewpdf.php?id=<encoded>`; pre-2020 via that site's search. 2025-2026 minutes: location unknown.
- Minutes record roll-call votes per commissioner by name (e.g. "Rickey Ray Y") and absences ("ABSENT: ... (2)"). Verified on Dec 2024 minutes.
  Minutes do not name vendor awards. They name who moved and seconded each item, but record no spoken comments or discussion.
  Items carry numbers like 24-12-1 or AB-4-2024. The PDFs are scans with an OCR text layer, which has errors (verify numbers and names).
- Budget: https://montgomerytn.gov/account-budget (FY2025, FY2027 approved budget books). Audits: TN Comptroller, 2001-02 on.
- Purchasing: bids on https://mcgtn.bonfirehub.com/portal/ and https://montgomerytn.gov/purchasing/archive. Award visibility: unverified.
- Video: YouTube.

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
