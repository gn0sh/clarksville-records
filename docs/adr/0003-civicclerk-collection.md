# ADR 0003: City Council records from CivicClerk (2024 on), joined with the Agenda Center

Status: accepted (backend-engineer, 2026-11-09). Collection approved by Brian on 2026-11-09 (docs/plan/one-week-finish.md,
"Needs Brian": "Collect City Council records from the CivicClerk portal", YES). Builds on ADR 0001 and on
`docs/architecture/city-council.md` (the vote-to-item link invariant is unchanged).

## Context
The city's Agenda Center ends in January 2024 (newest row 2024-01-11). Newer City Council agendas, minutes and video are
on CivicClerk: a portal at clarksvilletn.portal.civicclerk.com backed by an OData API at
clarksvilletn.api.civicclerk.com. Both hosts' robots.txt allow everything for `User-agent: *` and carry a
Content-Signal line (`search=yes, ai-train=no, use=reference`); a group of named AI crawlers (ClaudeBot, GPTBot, CCBot,
...) is disallowed.

## Decision
1. **Robots judgment.** Our collector is not one of the named AI crawlers: it sends its own honest User-Agent
   ("clarksville-records research collector ..."), which matches only the `*` group, and that group allows the API.
   Its use is reference (showing public records with a link to each source), never training, which is what the
   Content-Signal permits. It is not an AI search or training crawler, and no model is trained on the data. Brian
   approved collection on that basis on 2026-11-09. If the site later names us, disallows `*`, or answers 403/429,
   collection stops (the fetcher already stops a host on 403/429 and never works around it).
2. **Politeness.** GET only, through `collector/fetch.PoliteFetcher`: robots.txt read each run and checked before
   every request, 10 s between requests to the host, one retry on a server error or a dropped tunnel, no header tricks.
   Only the API host is on the allowlist; the portal, cityofclarksville.com and YouTube are never fetched.
3. **Endpoints.** Listing: `GET /v1/Events?$filter=categoryName eq 'City Council' and startDateTime ge 2024-01-01...
   &$orderby=startDateTime asc`, following `@odata.nextLink` (15 events a page) on the API host only. Files: each
   event's `publishedFiles[]` (type `Agenda` or `Minutes`, `fileId`), downloaded with
   `GET /v1/Meetings/GetMeetingFileStream(fileId=<id>,plainText=false)`, the call the portal itself makes. Everything
   is cached: listing pages as fetched under `data/store/civicclerk/<sha256>.json`, PDFs in the content-addressed store
   with the city manifest (`data/localities/clarksville-tn/manifest.json`).
4. **One meeting per date and kind across both sources.** `civicclerk.merge_sources` keeps one row for a meeting listed
   by both (same date, same kind from the same `kind_rules`): the one with minutes, then the Agenda Center's (its ids
   and citations were published first). Each meeting records `listing_source` (`agenda-center` or `civicclerk`). Rows
   within one source are never merged with each other.
5. **Video.** `mediaSourcePathMp4` is stored as the meeting's `video_url` only when it is a full https URL on a
   configured host (cpmedia.azureedge.net). A bare storage path ("stream/CLARKSVILLETN/<uuid>.mp4") has no documented
   public URL and is not guessed; it is reported as a listing problem. The video is a source link for transcripts
   later; it is not downloaded by the collector.
6. **Same reader and checks.** CivicClerk minutes go through `city_minutes.parse_minutes_pdf` and `city_build.build`
   unchanged in rules, so every roll call is verified or held by the same checks, and the link invariant holds. The
   build report gives counts and the verified rate per source and for 2024 on (`by_source`).

## Consequences
- Times: the API prints the local meeting time with a `Z` (the 6 PM session is `T18:00:00Z`), so the date is taken as
  printed, never converted.
- Config: `config/localities/clarksville-tn/civicclerk.yml`; the code holds no locality literal.
- A listing that fails part way is not written, so the last full `civicclerk-listing.json` stays.
