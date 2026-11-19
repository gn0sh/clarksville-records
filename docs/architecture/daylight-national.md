# Architecture: daylight-national (national address lookup, statuses, requests, coming-up pages)

Status: draft v1 (software-architect, 2026-11-19). Decisions and alternatives: `docs/adr/0013-daylight-national.md`.
Tasks: `docs/tasks/daylight-national.md`. Spec: `docs/specs/daylight-national.md` (v1; v2 M1 scope assumed, see
Assumptions). **No UX draft existed when this was written**: contracts below are data contracts (what each page and
feed holds), not layouts; the ux-designer's draft may rename labels, never fields. Re-check after the UX draft lands.

## 1. Context
One national page at `/us/`: the person types an address, the browser asks the US Census geocoder, and the page lists
every local government at that spot with a status read from a directory shipped inside the page. Daylight receives
nothing about the address. Covered bodies get a coming-up page and feeds. Uncovered ones get "Request it" (email at
Buttondown, one tag per body). Clarksville and Montgomery County stay the full Daylight and are the M1 covered bodies.

## 2. Components
| Component | Where | Responsibility | Milestone |
|---|---|---|---|
| Directory | `config/national/directory.yml` (curated, reviewed) | Government id -> body, status, reason, sources, reader keys | M1 |
| Gov flags | `config/national/gov-flags.yml` (curated) | Show or hide a returned unit regardless of FUNCSTAT | M1 |
| Labels | `config/national/labels.yml` | Every fixed string on national pages and feeds (AC4.5) | M1 |
| National builder | `sitegen/national.py` (+ templates) | Writes `/us/` pages and per-body feeds from directory + data | M1 |
| Lookup script | `site/static/national.js` (+ the existing `_geocode_frame.js` pattern) | JSONP in a sandbox, classify, render list, request form | M1 |
| Clarksville adapter | inside `sitegen/national.py` | Clarksville council and county commission meetings -> the feed shape | M1 |
| Tenant rule | `collector/fetch.py` | Per-tenant block state on shared hosts | M2 |
| National collector | `collector/national/` (`run.py`, `legistar_upcoming.py`) | Read covered Legistar bodies within a budget; write feeds, health, proposals | M2 |
| National workflow | `.github/workflows/national-update.yml` (devops) | Schedule, concurrency, budget, push `national-data`, attest | M2 |
| Weekly sender | `sender/` (weekly edition mode) | Editions from `wk-` tags; merged metadata stamp | M4 |

## 3. Data model

### 3.1 Ids
`<layer>-<GEOID>`; layers `place`, `county`, `cousub`, `sdu`, `sds`, `sde`. Body id = government id (one body per
government until A13 changes; then `<gov id>.<slug>`). Ids appear in URLs, tags (`req-<id>`, `wk-<id>`) and feeds and
never change. A government whose GEOID changes (Census re-codes) keeps its id; the new GEOID goes in `also`.

### 3.2 `config/national/directory.yml`
```yaml
schema: daylight-directory/1
govs:
  - gov: place-4715160
    also: []                       # other <layer>-<GEOID> naming the same government
    body_name: Clarksville City Council
    status: covered                # covered | cant-cover
    official_url: https://www.clarksvilletn.gov/
    checked: 2026-11-19
    checked_url: https://www.clarksvilletn.gov/...   # where the status was checked
    platform: daylight             # daylight | legistar | (later) boarddocs, escribe, civicclerk
    daylight: {body: city, full_url: /city/}          # platform keys; legistar: {client, body_id, tz, final_statuses?}
  - gov: sdu-4703030
    body_name: Clarksville-Montgomery County School System Board of Education
    status: cant-cover
    reason: blocks-readers         # blocks-readers | robots-disallow | scanned-only | not-posted | token-required | api-not-enabled | terms
    reason_url: https://www.cmcss.net/
    official_url: https://www.cmcss.net/
    checked: 2026-11-19
    checked_url: docs/research/rpc-cmcss-sources.md
```
Build checks (refuse to build): unknown key; bad id; duplicate id across `gov` and `also`; `cant-cover` without
`reason`, `reason_url`, `checked`; `covered` without `platform` keys; any URL not https.

### 3.3 `config/national/gov-flags.yml`
```yaml
schema: daylight-govflags/1
hide: [{id: county-09110, why: "CT planning region, no county government", source: <url>}]   # by id
show: [{id: place-4752006, why: "Nashville-Davidson metro government (balance)", source: <url>}]
rules: [{state: "09", layer: county, show: false, why: ..., source: <url>},
        {state: "44", layer: county, show: false, why: ..., source: <url>}]
```
Ids in this file are examples to be confirmed in task B2; none is verified yet.

### 3.4 Embedded page directory (built from 3.2 and 3.3; the browser's only data)
```json
{"schema": "daylight-pagedir/1", "built": "2026-11-19",
 "govs": {"place-4715160": {"name": "Clarksville City Council", "status": "covered", "page": "/us/b/place-4715160/",
                            "full": "/city/", "stale": false},
          "sdu-4703030": {"name": "...", "status": "cant-cover", "reason": "blocks-readers",
                          "official_url": "https://www.cmcss.net/"}},
 "alias": {"place-4752006": "county-47037"},
 "hide": ["county-09110"], "show": ["place-4752006"], "rules": [{"state": "09", "layer": "county", "show": false}],
 "labels": {"reason.blocks-readers": "Its records site blocks automated readers.", "...": "..."}}
```
`stale` is computed at build time from the body feed's `last_ok_at` (more than 3 days before the build).

### 3.5 Per-body feed `/us/b/<body id>/upcoming.json` (schema `daylight-upcoming/1`)
The contract the coming-up page, ICS, Atom, the future app and the weekly email read. Written by the national builder
(M1, Clarksville) or copied from `national-data` (M2+).
```json
{"schema": "daylight-upcoming/1",
 "body": {"id": "county-47125", "name": "Montgomery County Commission", "tz": "America/Chicago",
          "official_url": "https://montgomerytn.gov/commission/agenda", "platform": "daylight",
          "full_url": "/meetings/agendas.html"},
 "checked_at": "2026-11-19T14:02:00Z", "last_ok_at": "2026-11-19T14:02:00Z",
 "meetings": [
   {"id": "2026-12-14-formal", "date": "2026-12-14", "time": null, "title": "Formal Session",
    "title_ours": true, "meeting_url": "https://...",
    "agenda": {"state": "final", "url": "https://mcgtn.org/...pdf", "status_as_posted": null},
    "may_be_incomplete": false, "items_withheld": false, "item_count": 11,
    "items": [{"seq": 1, "number": "CZ-12-2026", "text": "Application of Chris Blackwell from AG to E-1",
               "source": {"url": "https://mcgtn.org/...pdf#page=1", "page": 1}}]}]}
```
Field rules: `meetings` from today (body's time zone) on, soonest first. `agenda.state`: `final` (items may be
shown), `not-final` (Legistar status not final: no items), `not-read` (posted, items not read by us: Clarksville City
Council in M1), `not-posted`. `items` is empty unless `state == final` and `items_withheld == false`.
`items_withheld` is true for every school board (`sd*` ids) and `item_count` then carries the count only. `text` is the
source's words, whitespace joined, nothing else changed. `time` is the posted time string or null. `title_ours` marks
a title built from fixed labels (Clarksville meetings have a kind, not a posted title). No vote, outcome, tally,
attendance, motion or person's name field exists in this schema (AC4.4); a test fails on any extra key.

### 3.6 ICS and Atom
- `upcoming.ics`: one VEVENT per meeting. `UID: <body id>/<meeting id>@daylight.gnoshcodes.com`; `DTSTART;VALUE=DATE`
  when `time` is null, else `DTSTART;TZID=<tz>` from the parsed time (unparseable: all-day, time in the summary as
  posted); `SUMMARY` = body name + meeting title; `URL` = the coming-up page; `DESCRIPTION` = agenda link and a fixed
  label (no item text: keeps calendar entries small and avoids clipping verbatim text). `SEQUENCE` bumps when the
  agenda state or URL changes.
- `upcoming.xml`: Atom, one entry per meeting agenda posted, id `<feed id><body id>/meeting/<meeting id>/agenda`, built
  with `sitegen/feeds.py`'s rules (ids never change; `updated` when the agenda was first seen).

### 3.7 Collector output on `national-data` (M2)
`data/national/bodies/<body id>.json` (3.5 minus `full_url`), `data/national/health.json`
(`{"<body id>": {"last_attempt_at", "last_ok_at", "consecutive_failures", "last_error": "tenant-blocked |
host-stopped | rate-limited | robots | budget-skipped | server-error | not-enabled-suspected | token-suspected"}}`),
`data/national/proposals.json` (`[{"body", "kind": "status" | "agenda-status-name", "observed", "evidence_url",
"first_seen", "count"}]`). Cache: `data/national/cache/<body id>/<event id>.json` (items keyed by
`EventAgendaLastPublishedUTC`).

## 4. Function contracts

### 4.1 Lookup script (`site/static/national.js`, node-testable like `address.js`)
- `jsonpUrl(address) -> string`: the geographies URL of ADR 0013 decision 2; `address` is the only variable part.
- `classify(answer) -> {kind: "error" | "nomatch" | "pick", matches: [{label, units}]} | {kind: "one", units}`.
  `units` = `[{id, layer, name, funcstat, state}]` from the six layers, read by exact layer name; any other layer is
  ignored. More than 20 matches: "add the city and ZIP".
- `governments(units, pagedir) -> [{id, name, status, reason?, page?, full?, official_url?}]`: apply in order
  (1) drop units by FUNCSTAT (place, county, cousub: keep A; school districts: keep A or E; codes confirmed in B2),
  (2) gov-flags `hide`, `show`, `rules`, (3) drop school district "not defined" units (GEOID ending 99999; B2
  confirms), (4) map through `alias`, then dedupe by id, (5) drop a county subdivision whose name equals the kept
  place's name in the same county (coextensive town or city; B2 confirms the class codes that prove it),
  (6) status from `govs`, else `not-covered-yet`, (7) order: place, county, cousub, sdu, sds, sde.
  Pure; unit-tested with recorded answers.
- Errors: no answer in 15 s -> "The Census lookup is not answering" + Retry; iframe blocked -> the same, plus the
  official Census lookup link. Never a guessed place.

### 4.2 Request form
HTML form, `method=post`, `action=https://buttondown.com/api/emails/embed-subscribe/daylight`, fields `email` and one
hidden `tag` per requested body: `req-<body id>`. Nothing else. Several bodies can be ticked into one post (A5,
verified for a new address). The page stores the requested body ids in `localStorage` key `daylight.us.requested`
(ids only) so the button reads "Requested" on return. Unverified (task Q2): tags added on a post from an existing
subscriber.

### 4.3 National builder (`sitegen/national.py`)
- `load_directory(path) -> Directory` (raises `NationalConfigError` naming the entry and key).
- `clarksville_feeds(facts_city, listing_city, county_agendas, today) -> dict[body_id, UpcomingFeed]`: council
  meetings with `agenda.state = not-read` (or `not-posted`), county agenda-only meetings with items as stored.
- `build_national(out_dir, directory, feeds, labels, counter) -> list[path]`: writes `/us/index.html`,
  `/us/cover/index.html` ("What we cover": covered and can't-cover entries by state, then name), `/us/b/<id>/index.html`,
  `upcoming.json|ics|xml`. Called from `sitegen.build` only when `national.enabled`.

### 4.4 Fetcher tenant rule (`collector/fetch.py`, M2)
- `SHARED_HOSTS = {"webapi.legistar.com": re.compile(r"^/v1/([a-z0-9-]{2,40})/")}`.
- `tenant_key(url) -> str | None`. `_blocked` gains tenant keys; `_raw_get` checks host and tenant blocks.
- On 403: robots.txt or non-tenant path or non-JSON body or second distinct tenant -> host block; else tenant block.
  On 429: host block. Exceptions: `TenantBlocked(HostBlocked)` so existing `except HostBlocked` callers still stop.
- `limit_tenant(url, n)`: per-tenant cap inside the host cap.

### 4.5 Legistar upcoming reader (`collector/national/legistar_upcoming.py`, M2)
- `events_url(client, body_id, start, end) -> str` (`$filter=EventBodyId eq N and EventDate ge ... lt ...`).
- `agenda_state(event, final_statuses) -> "final" | "not-final" | "not-posted"`.
- `meeting(event, items, tz) -> dict` in 3.5's shape; `items` only for final agendas; `may_be_incomplete = true`.
- `run(directory, fetcher, budget, now) -> (feeds, health, proposals)`; never raises on one body's failure.

## 5. Key flows
1. **Lookup (M1):** page load (directory embedded; a page-view count if counting is on, path `/us/` only) -> submit
   -> iframe JSONP to Census -> answer posted to the page -> `classify` -> (pick if several) -> `governments` ->
   list rendered as text. Requests carrying the address: one, to `geocoding.geo.census.gov`.
2. **Request it (M1):** tick one or more not-covered bodies -> email -> post to Buttondown with `req-` tags ->
   Buttondown confirmation email -> confirmed subscriber with `req-` tags. The morning note ignores them.
3. **Coming-up page (M1):** static page built from the feed; "last checked" line from `checked_at`; stale line when
   `last_ok_at` is more than 3 days old.
4. **Collection (M2):** `national-update.yml` -> fetcher with tenant rule and budget -> per body: events -> state ->
   items if final and changed -> feeds, health, proposals -> push `national-data` -> attest. Daily deploy reads the
   newest attested `national-data`.
5. **Weekly email (M4):** sender plan reads feeds + subscribers' `wk-`/`wkt-` tags -> editions -> merged stamp ->
   one filtered email per edition. Brian approves the sample and first send.

## 6. Non-functional
- **Privacy:** AC1.2 to AC1.3 are tested in a browser test (the existing `tests/address_browser.js` pattern) for the
  seven spec addresses plus CT, MA, NY, PA and VA ones: request log has the address only in the Census request; no
  storage key but `daylight.us.requested`. Outbound links use `rel="noopener noreferrer"`.
- **Performance:** page under 100 KB with the directory embedded in M1; one Census request per lookup.
- **Politeness and scale:** ADR 0013 decision 6 budget; capacity about 100 bodies a run, 200 a day.
- **Observability:** `health.json` and `proposals.json`; a fixed-title issue when more than 20% of covered bodies are
  stale (devops, M2). Census outages show in the browser only (we can't see them; accepted).
- **Security:** CSP per page (ADR 0013 decision 2); verbatim text escaped (Jinja autoescape) and `{{`/`{%` neutralised
  in anything an email template will hold (as the morning sender does).

## 7. Clarksville checks (done 2026-11-19, from code and data on this branch)
- County Commission: `data/county-agendas/agendas.json` meetings hold `items[].title` as printed, whitespace joined,
  hyphenated line-end words joined (`collector/county_agenda.py` lines 365-393, 451), with `number`, `printed`,
  `section`, `page`, and `sources[].url`. Usable as is for AC4.2.
- City Council: `facts.json` meetings carry `agenda_url` and `agenda_source_id`, but `item_events` come from minutes
  only (1,759 motions and 2,405 roll calls, 0 events from agenda sources). Upcoming council items are **not** stored.
- Neither stores a meeting time. `time` is null for both in M1 ("Time not listed here").
- Data on this branch was last collected 2026-11-10; the live `records-data` copy is newer.

## 8. Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| FUNCSTAT or class codes behave differently than assumed outside TN | medium | B2 confirms from TIGER docs; hand table; QA addresses in 6 states |
| Census layer names change with a new vintage | low-medium | read by exact name; a browser test with a recorded answer; the page shows the error state, never a guess |
| Buttondown re-submit does not add tags for existing subscribers | medium | Q2 tests before M1 live; fallback copy "use a new address or reply to the confirmation" |
| One newsletter's confirmation email reads wrong for requests | medium | ux-designer rewrites the newsletter-wide confirmation text to fit both |
| Legistar 403 body shapes unknown | high | first contact for a new body runs alone (probe mode) and is recorded as a fixture |
| Shared `national-data` provenance doubles ADR 0011 surface | medium | security review of D1 and D2 |
| Metadata clobber between morning and weekly senders | high if built separately | one sender package, merged object, shared concurrency (ADR 0013 decision 8) |
| City Council shows no items in M1 | certain | plain label and agenda link; B9 later |

## 9. Assumptions
- AS1. Spec v2's M1 scope is as the manager's brief states (lookup, statuses, Request it, What we cover, Clarksville and
  Montgomery County covered, coming-up pages); national email waits.
- AS2. Brian's capacity decision (manager relay, 2026-11-18 11:32 PM CT) holds; the upgrade itself stays his action.
- AS3. The national page lives at `/us/` on the existing Pages site and domain. Path is the ux-designer's to rename.
- AS4. CMCSS stays "can't cover" in M1 (AC2.4). Note for the PM: Daylight already lists CMCSS board meetings with
  agenda links and line counts from the county's page; a "covered, meetings only" status is possible later.
