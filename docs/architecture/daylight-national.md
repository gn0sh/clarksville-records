# Architecture: daylight-national (national address lookup, statuses, requests, coming-up pages)

Status: draft v2 (software-architect, 2026-11-19; v1 was written before the UX draft, v2 reconciles with
`docs/design/daylight-national.md` draft v1 sections 2-4, 10, 11). Decisions and alternatives:
`docs/adr/0013-daylight-national.md` (deltas this version needs are listed in section 10). Tasks:
`docs/tasks/daylight-national.md`. Spec: `docs/specs/daylight-national.md` (v2.1 assumed: request by email is the main
path; weekly email and feeds are M4). Contracts below are data contracts, not layouts; the UX draft owns labels.
User-facing words say "government", never "body"; "body id" stays the internal and URL name.

## 1. Context
One national entry page at `/digest/`: the person types an address, the browser asks the US Census geocoder, and the
result is drawn on that same page (URL and title never change) as a list of every local government at that spot with
a status read from a directory shipped inside the page. Daylight receives nothing about the address. Covered
governments get a coming-up page. Uncovered ones get "Request it": an in-card email form at Buttondown, one `req-<id>`
tag per government, several per post. An optional anonymous "Just count me" tap sends one GoatCounter event named for
the government, no address and no email. Clarksville and Montgomery County stay the full Daylight and are the M1
covered governments.

## 1a. Pages and URLs (the contract the frontend, builder and checks share)
All under the existing Pages site; `digest/` is the folder (UX D4). Links are relative with the site's `root` prefix, as
every page does today (`../` per folder depth); `/digest/` below means `digest/index.html`.
| Page | File | Notes |
|---|---|---|
| Entry and lookup result | `digest/index.html` | The lookup result is drawn here; `location` and `document.title` are never written (no pushState, no hash, no query). |
| What we cover | `digest/covered.html` | Static, no script needed, no storage (AC12.1). Optional share sentence from `config/national/share.yml` when it exists. |
| Coming-up page | `digest/<st>/<body id>.html` | `<st>` = lowercase USPS code from the directory entry (`tn`). Static. |
| Per-government data | `digest/<st>/<body id>.json` | `daylight-upcoming/1` (3.5), the page's own data, published; linked from Method in M4. |
| Request confirmed | `digest/requested.html` | Static thank-you (UX section 3). Reached only if Buttondown can redirect after confirmation (Q-A below); built either way. |
| M3 / M4 (not built in M1) | `digest/letter.html`, `digest/signup.html`, `digest/<st>/<body id>.ics`, `.xml` | Names reserved so M1 links never move. |
The Menu drawer (the footer list on every page) gains one group, "Daylight Digest": two links (entry, What we
cover). Clarksville's front page gains the one line "Not in Clarksville?..." under its address card. Nothing else on
existing pages changes (see 7a for what "byte-identical" means with the switch on).

## 2. Components
| Component | Where | Responsibility | Milestone |
|---|---|---|---|
| Directory | `config/national/directory.yml` (curated, reviewed) | Government id -> board, state, status, reason, sources, reader keys | M1 |
| Gov flags | `config/national/gov-flags.yml` (curated) | Show or hide a returned unit regardless of FUNCSTAT; the fixed lines (consolidated, independent city) | M1 |
| Labels | `config/national/labels.yml` (card labels, embedded in the pagedir) and `config/national/page-labels.yml` (every other fixed string; B4) | Every fixed string on digest pages (AC4.5, AC4.8), in "government" words | M1 |
| Coverage share | `config/national/share.yml` (optional) | `{pct, k, date}` for the What we cover sentence; absent = sentence omitted | M1.5 |
| National builder | `sitegen/national.py` (loaders, pagedir, frame) + `sitegen/national_pages.py` and `site/templates/digest/` (pages; B4) | Writes `digest/` pages and per-government JSON from directory + data; the header variant, Menu group and front-page line | M1 |
| Shared guards | `sitegen/national_guards.py` (imports only `sitegen.config`; the builder and `collector/national/` both import it) | `allowed_url` (https_link + no credentials/port + platform host allowlist), `link_or_official`, `checked_id`/`checked_meeting_id`, `clean_text`, `clean_feed` (3.5 caps, stripping, URL nulling; returns counts for the run log) | M1 (B14) |
| Geo frame | `digest/geo-frame.html` (static, built; own meta CSP) | The only page that may load the Census JSONP; sandboxed (`allow-scripts`, no `allow-same-origin`); gets the address by `postMessage`, answers by `postMessage` | M1 |
| Lookup script | `site/static/national.js` (+ the `address.js` message checks) | Drives the frame, classify, render list, picker, in-card request form, device list | M1 |
| Counter script | `site/static/us-count.js` (digest pages only) | The anonymous "Just count me" event; exposes `window.DaylightCount` | M1 |
| Header variant | `site/templates/_header.html.j2` (one switch) + `qa/site_checks.py` (two checks) | The digest plate and date line; scoped checks (7a) | M1 |
| Request report | `tools/national/request_report.py` | Counts `req-<id>` tags from Buttondown's API; runs on Brian's PC with his key, never in Actions | M1 |
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
    state: TN                      # USPS code; names the folder digest/tn/ (lowercased)
    status: covered                # covered | cant-cover
    official_url: https://www.clarksvilletn.gov/
    checked: 2026-11-19
    checked_url: https://www.clarksvilletn.gov/...   # https page where the status was checked (or `checked_doc:`)
    items: shown                   # shown | withheld; DEFAULT withheld (security finding 5; invariant in section 11)
    platform: daylight             # daylight | legistar | (later) boarddocs, escribe, civicclerk
    daylight: {body: city, full_url: city/}           # platform keys; legistar: {client, body_id, tz, final_statuses?}
    # non-daylight platforms also require (finding 7, enforces Brian's R5 host OK):
    # host_ok: {date: 2026-12-01, link: <the thread message or PR where Brian said yes>}
  - gov: sdu-4703030
    body_name: Clarksville-Montgomery County School System Board of Education
    status: cant-cover
    reason: blocks-readers         # blocks-readers | robots-disallow | scanned-only | not-posted | token-required | api-not-enabled | terms
    reason_url: https://www.cmcss.net/
    official_url: https://www.cmcss.net/
    checked: 2026-11-19
    checked_doc: docs/research/rpc-cmcss-sources.md   # a repo file, instead of `checked_url` (which is https only)
```
The slot label (CITY OR TOWN, COUNTY, TOWNSHIP OR TOWN, SCHOOL DISTRICT) comes from the id's layer, not the file,
except where a gov-flags `slots` entry moves a layer for a state (3.3; AC2.11: New England towns outside Connecticut
show as CITY OR TOWN; `national.slot_of(id, flags)`). A
government not in this file is "Not covered yet" (AC2.8); it has no entry and no page.
Build checks (refuse to build): unknown key; bad id; duplicate id across `gov` and `also`; missing or unknown `state`;
`cant-cover` without `reason`, `reason_url`, `checked`; `covered` without `platform` keys; any URL not https; a
`reason` with no label in `labels.yml`. Added by security review (findings 5, 7), all by `yaml.safe_load` and strict
regex, each with a test:
- `items: shown` is refused unless `SHOWN_REVIEWED` in `sitegen/national.py` has a row for that `gov` whose
  `entry` (the readable canonical entry, every key; 11.2) equals the entry's `norm_entry`, so any edit to a shown
  entry is refused until a reviewed code change updates the row (the error prints the changed keys and the whole new
  row). The loaded entry carries `review` (`review_digest` of that canonical entry when shown, else null). Two
  covered entries with one source (`daylight:<body>`, `legistar:<client>:<body_id>`) are refused; a can't-cover
  entry carries no `platform`, platform keys or `host_ok`, and `host_ok` is refused on a daylight entry. Only plain
  YAML values load (text, whole numbers, true/false, null, dates as values, lists, mappings with text keys). See section 11. A missing `items` means `withheld`.
- a non-`daylight` platform without `host_ok: {date, link}` is refused (build and collector both).
- `daylight.full_url` and the pagedir `page` match `^[a-z0-9][a-z0-9/_.-]*$` (no scheme, no `..`, no leading slash);
  `legistar.client` matches `^[a-z0-9-]{2,40}$`; `tz` is a name in `zoneinfo.available_timezones()`;
  `final_statuses` is an exact list of strings from a fixed set; `state` is one of the USPS codes.
- every URL host on a non-daylight entry is on that platform's host allowlist (`config.https_link`, finding 4).
- Also refused (B1, 2026-11-19): a `state` that does not match the id's GEOID state code (it names the folder); a
  `reason`/`reason_url` on a covered entry; both `checked_url` and `checked_doc` (the doc must be an existing
  `docs/*.md` file); a URL with a user name, password or a port other than 443; a body name with control or bidi
  characters; an unknown `platform` (boarddocs, escribe, civicclerk join with their own key checks). Legistar's hosts
  are `webapi.legistar.com` and `<client>.legistar.com`. A reviewed `shown` entry must also pass a fail-closed
  guard (`shown_refusal`): no `sd*` id, a `place`, `county` or `cousub` id, an ASCII-only `body_name`, and no school,
  youth, child, mock, model, shadow, pension or similar stem unless the row says `denylist_ok=True` (a place-name hit
  such as College Station; `privacy-withhold/body-name-word-check`, `privacy-withhold/body-name-false-refusal`). An `also` id must
  be in the same layer as `gov` (a re-coded GEOID; `privacy-withhold/also-cross-layer`). A list or mapping where a
  word belongs is refused. `load_all` refuses a directory `gov` or `also` id that gov-flags hides. A gov-flags
  state rule only hides (`show: true` is refused; use an id-level `show`).
- Architect to confirm (code review, `contract/legistar-official-url`): a Legistar entry's `official_url`,
  `checked_url` and `reason_url` must today be on `<client>.legistar.com` or `webapi.legistar.com`; a government whose
  official agenda page is on its own site cannot be listed until this is decided.

### 3.3 `config/national/gov-flags.yml`
```yaml
schema: daylight-govflags/1
hide: [{id: county-25017, why: "Middlesex County, MA: no county government (H4|N)", source: <url>},
       {id: place-4752006, why: "Nashville (balance): same government as county-47037 (C8|F)", source: <url>},
       {id: county-51760, why: "Richmond city, VA: independent city (C7|F)", source: <url>}]   # by id
show: [{id: county-47037, why: "Nashville-Davidson metropolitan government (H6|C)", source: <url>}]
rules: [{state: "09", layer: county, show: false, why: ..., source: <url>},
        {state: "44", layer: county, show: false, why: ..., source: <url>}]
lines: [{id: place-4752006, line: consolidated, why: ..., source: <url>},    # "The city and county here are one government."
        {id: county-51760, line: independent-city, why: ..., source: <url>}] # "This city is not part of any county."
slots: [{state: "25", layer: cousub, slot: place, why: ..., source: <url>}]   # AC2.11; also 23, 33, 44, 50
```
`slots` (added 2026-11-19, QA `national/new-england-town-slot`): in a listed state, every card of `layer` shows in
`slot`: label `slot.<slot>`, ordered as that slot (4.1 step 7), and a kept unit in slot `place` counts as the city
or town for `no-city`. Only `cousub` -> `place` is accepted (`SLOT_MOVES`; anything else, a duplicate state or a
non-FIPS state stops the build). Seeded for ME, MA, NH, RI and VT; Connecticut is not listed. The pagedir carries it
as `slots: [{state, layer, slot}]`.
Seeded in B2; codes (class code|FUNCSTAT) verified 2026-11-19 from the Census 2020 code files (`docs/platform-facts.md`
"Census TIGER/Line codes"). A `line` needs the label `note.<line>` in `labels.yml`. A `lines` entry applies when the
Census returns its id for the address, whether the id is kept or dropped (by FUNCSTAT at step 1 or by gov-flags), so
a line rides on a dropped duplicate: an independent city's county-equivalent copy is C7|F, dropped at step 1 (the
place, C7|A, is the one card), and carries `independent-city`; Nashville's "(balance)" place is C8|F, dropped at
step 1, and carries `consolidated`; Metro is `county-47037`, H6|C, which step 1 would drop, so `show` keeps it. An
address in Belle Meade (its own city inside Metro) gets Belle Meade and Metro and no line. The `hide` entries for
those F copies and for the N counties (MA) are redundant with step 1 and stay as a second guard against a later
vintage changing a FUNCSTAT. Step 1 keeps FUNCSTAT A or B (4.1). `rules` only hide: the browser ignores a
`show: true` rule (fail closed; only an id-level `show` keeps a unit step 1 drops). Coextensive town and city
duplicates go by class code (COUSUBCC T5, C2, C5, C7), never by name (4.1 step 5).
The other fixed lines (no city or town, no county government listed) are computed, not flagged (4.1).

### 3.4 Embedded page directory (built from 3.2 and 3.3; the browser's only data)
```json
{"schema": "daylight-pagedir/1", "built": "2026-11-19", "root": "../",
 "govs": {"place-4715160": {"board": "Clarksville City Council", "status": "covered", "page": "digest/tn/place-4715160.html",
                            "full": "city/", "stale": false},
          "sdu-4703030": {"board": "Clarksville-Montgomery County School System Board of Education",
                          "status": "cant-cover", "reason": "blocks-readers", "checked": "2026-11-10",
                          "reason_url": "https://www.cmcss.net/", "official_url": "https://www.cmcss.net/"}},
 "alias": {},
 "hide": ["county-25017", "place-4752006", "county-51760"], "show": ["county-47037"],
 "rules": [{"state": "09", "layer": "county", "show": false}, {"state": "44", "layer": "county", "show": false}],
 "lines": {"place-4752006": "consolidated", "county-51760": "independent-city"},
 "slots": [{"state": "25", "layer": "cousub", "slot": "place"}, "..."],
 "labels": {"reason.blocks-readers": "Its records site blocks automated readers.", "...": "..."}}
```
`stale` is computed at build time from the government's JSON `last_ok_at` (more than 3 days before the build).
`page` and `full` are relative to `root` (the page's own `data-root`), never absolute (so `page` starts with
`digest/`). `alias` maps an `also` id to its entry's id, same layer only (3.2). Label keys are `slot.<layer>`, `reason.<reason>` and `note.<key>` (`config/national/labels.yml`). The card's title is the Census
name from the lookup; `board` is the directory's board name on the next line (UX P4). A government with no `govs`
entry has no `board` line, status "not-covered-yet", and the "no official link" copy (the Census answer has none).
If the embedded directory passes about 60 KB, it moves to same-origin `digest/pagedir.json` fetched on first lookup
(`connect-src 'self'`); the shape is unchanged.

### 3.5 Per-government data `digest/<st>/<body id>.json` (schema `daylight-upcoming/1`)
The contract the coming-up page, the M4 ICS and Atom, the future app and the weekly email read. Written by the national
builder (M1, Clarksville) or copied from `national-data` (M2+). The M1 builder writes this JSON and the page only; the
ICS and Atom writers are M4 (spec v2.1).
```json
{"schema": "daylight-upcoming/1", "review": "<64 hex: the entry's review digest, or null>",
 "body": {"id": "county-47125", "name": "Montgomery County Commission", "tz": "America/Chicago",
          "official_url": "https://montgomerytn.gov/commission/agenda", "platform": "daylight",
          "full_url": "meetings/agendas.html"},
 "checked_at": "2026-11-19T14:02:00Z", "last_ok_at": "2026-11-19T14:02:00Z",
 "meetings": [
   {"id": "2026-12-14-formal", "date": "2026-12-14", "time": null, "title": "Formal Session",
    "title_ours": true, "meeting_url": "https://...",
    "agenda": {"state": "final", "url": "https://mcgtn.org/...pdf", "status_as_posted": null},
    "may_be_incomplete": false, "items_withheld": false, "item_count": 11,
    "items": [{"seq": 1, "number": "CZ-12-2026", "text": "Application of Chris Blackwell from AG to E-1",
               "source": {"url": "https://mcgtn.org/...pdf#page=1", "page": 1}}]}]}
```
**M1 (Clarksville, B4 review `national-freshness/checked-at-is-first-fetch`):** no check run is recorded, so
`checked_at` is the newest source record's first fetch (manifest instant, else noon UTC of its stored day; 1970 when
there is none) and `last_ok_at` is null; the page prints "Newest record we have: {date}." (or "We have no records for
this government yet."), no stale line, and the pagedir marks daylight entries `stale: false`. A true `checked_at`
comes from the M2 collector's run stamp (task C3).
Field rules: `meetings` from today (body's time zone) on, soonest first. `agenda.state`: `final` (items may be
shown), `not-final` (Legistar status not final: no items), `not-read` (posted, items not read by us: Clarksville City
Council in M1), `not-posted`. `items` is empty unless `state == final` and `items_withheld == false`.
`review` (required) is the directory entry's review digest when it is shown, else null; null forces every meeting
withheld (schema `allOf`), and every write goes through `national_guards.bind_feed` (section 11.2).
`items_withheld` is true unless `national_guards.is_shown(entry)` (default withheld; never allowed for `sd*` ids;
invariant in section 11), and `item_count` is then null (Clarksville feeds may carry a count they
already store; M2 withheld bodies do not). `text` is the source's words,
whitespace joined, nothing else changed, capped at 2,000 characters per item (longer is cut at the cap and marked
`"cut": true`, the page then links the official agenda for the rest), at most 150 items per meeting and 60 meetings per
government, bidi-override and other control characters stripped and counted in the run log (finding 12). Every URL in
the file (`official_url`, `meeting_url`, `agenda.url`, `items[].source.url`) must pass `config.https_link` and, off
Daylight, the platform's host allowlist, at collection and again at build; a bad URL is dropped (field null) and the
page falls back to the directory's `official_url` (finding 4). A meeting `id` matches `^[a-z0-9][a-z0-9-]{0,79}$` (a meeting that does not is dropped and
counted); every id and path rule is a full match (no trailing newline). `date` and the instants take ASCII digits
only (schema `[0-9]`, never `\d`, which takes any Unicode digit); the copy step also requires each `date` to be a
calendar day and each instant to lie from the epoch to one day after the build (section 12, B-ISO-2). Whitespace controls (tab, CR, LF, VT, FF) are
word breaks, not stripped characters; any other text field read from outside is stripped the same way and capped at
2,000 characters without a `cut` mark (B14). `time` is the posted time string or null. `title_ours` marks
a title built from fixed labels (Clarksville meetings have a kind, not a posted title). No vote, outcome, tally,
attendance, motion or person's name field exists in this schema (AC4.4); a test fails on any extra key.

### 3.6 ICS and Atom (M4; contract fixed now so M1 ids and URLs hold)
- `digest/<st>/<body id>.ics`: one VEVENT per meeting. `UID: <body id>/<meeting id>@daylight.gnoshcodes.com`; `DTSTART;VALUE=DATE`
  when `time` is null, else a UTC `DTSTART:<yyyymmdd>T<hhmmss>Z` from the parsed time in `<tz>` (C4, 2026-11-19: RFC 5545 3.2.19 requires a VTIMEZONE for every TZID, which the writer does not emit); a timed event carries `DURATION:PT1H`, since a posting gives no end (unparseable: all-day, time in the summary as
  posted); `SUMMARY` = body name + meeting title; `URL` = the coming-up page; `DESCRIPTION` = agenda link and a fixed
  label (no item text: keeps calendar entries small and avoids clipping verbatim text). `SEQUENCE` bumps when the
  agenda state or URL changes. **Written in Python by our own writer** (never a template), with RFC 5545 3.3.11 text
  escaping (backslash, semicolon, comma, newline), control characters removed first (`feeds.clean`), lines folded at 75
  octets, and a fixture whose title holds `\r\nBEGIN:VEVENT` that must come out as one escaped line (finding 3, gates
  H1; M4 for shipping, but the writer and its test are built when the first non-Clarksville text could reach it).
- `digest/<st>/<body id>.xml`: Atom, one entry per meeting agenda posted, id `<feed id><body id>/meeting/<meeting id>/agenda`, built
  with `sitegen/feeds.py`'s rules (ids never change; `updated` when the agenda was first seen).

### 3.7 Collector output on `national-data` (M2)
`data/national/bodies/<body id>.json` (3.5 minus `full_url`), `data/national/health.json`
(`{"<body id>": {"last_attempt_at", "last_ok_at", "consecutive_failures", "last_error": "tenant-blocked |
host-stopped | rate-limited | robots | budget-skipped | server-error | not-enabled-suspected | token-suspected |
collector-error", "failure_streak": {"kind", "count"} | null}}`; `last_error` and `failure_streak` null after a good
read; `collector-error` (C3): the reader refused its own output or cache, e.g. `cache-confine/put-error-kind`;
`budget-skipped`, `host-stopped` and `rate-limited` are not the body's failure: `consecutive_failures` and the streak
of runs failing with one kind stay as they were; `last_attempt_at`, `last_ok_at` and the body file's `checked_at`
move only per 4.4.5),
`data/national/proposals.json` (`[{"body", "kind": "status" | "agenda-status-name", "observed", "evidence_url",
"first_seen", "count"}]`). Cache: `data/national/cache/<body id>/<event id>.json` (items keyed by
`EventAgendaLastPublishedUTC`). Body files and cache files carry `review`; rules in section 11.1 rows 16, 18-19 (M2).

### 3.8 Device storage (`localStorage`, digest pages only; the whole list of what this site keeps on a device)
| Key | Value | Written when | Read by |
|---|---|---|---|
| `daylight.us.list` | `{"v":1,"govs":[{"id":"place-4715160","name":"Clarksville city"}, ...]}` (max 20) | a lookup shows a list | entry page: "Your saved list" |
| `daylight.us.requested` | `{"v":1,"ids":["sdu-4703030", ...]}` | the email form was sent for those governments | cards: "Request sent from this device" |
| `daylight.us.counted` | `{"v":1,"ids":[...]}` | "Just count me" succeeded for that government | cards: the done state |
Never stored: the typed address, the Census matched line, the email, the time. `name` is the Census's name for the id
(public data tied to the id, no address); it is stored because a government not in the directory has no name anywhere
else (decision N2). Reads validate every value (id regex `^(place|county|cousub|sdu|sds|sde)-[0-9]{2,14}$`, name at
most 120 characters, at most 20 entries, bad entry dropped) and names are drawn with `textContent`. "Forget this list"
removes all three keys and redraws; the line under the list says so. The Census request, the page URL and the title
never hold an address (F3 asserts it). `/digest/covered.html` and coming-up pages read and write no key.

### 3.9 Counter event (the one thing `us-count.js` sends)
`GET https://<code>.goatcounter.com/count?p=count-<gov id>&e=true&rnd=<random>`, `mode: no-cors`, `credentials: omit`,
`referrerPolicy: no-referrer`, the same transport as `count.js` (ADR 0008). Sent only on a tap of "No email? Just count
me" for one government; one request per tap. No address, no email, no screen size, no referrer, no path. What
GoatCounter sees: the event name (a government id the person chose from a list), and what any request shows (IP,
browser) which it states it does not keep. Same opt-outs as `count.js` (Do Not Track, Global Privacy Control, automated
browsers, non-https) plus: if the analytics code is empty or an opt-out is on, the button is not shown at all, so the
page never says "Counted" for something not sent. A blocked request (an ad blocker) rejects the `fetch`, which shows
the design's "We couldn't count that. Try again." The counter is a lower bound and can be inflated by anyone with a
script; the report labels it "anonymous taps, unverifiable, never added to email requests" (R8).
Event name is a new namespace `count-<id>` (ADR 0013 decision 5 named it `request-<id>`; see section 10).
Mechanism choice: a second small script (not an edit to `count.js`) so every Clarksville page's `count.js` stays
byte-identical; its opt-out guard is a copy of `count.js`'s, and a node test asserts both files hold the same guard
lines.

## 4. Function contracts

### 4.0 Geo frame (security finding 1, `national/csp-jsonp-gadget`; supersedes the srcdoc frame of ADR 0013 decision 2)
- `digest/geo-frame.html` is a static file the builder writes once. Its `<meta http-equiv="Content-Security-Policy">`
  allows only: `default-src 'none'; script-src 'sha256-<hash of its one inline script>'
  https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress`. Parent pages never list the Census in
  `script-src` (it stays `'self'`); the parent's `frame-src` is `'self'`. No other page, and no `digest/<st>/*`,
  `covered.html` or `requested.html`, names the Census in its CSP or carries the frame.
- The parent creates `<iframe sandbox="allow-scripts" src="geo-frame.html" referrerpolicy="no-referrer">` per lookup.
  The frame posts `"ready"`; the parent replies `{address}` (string, at most 200 characters) to `"*"` (origin is `null`),
  the frame builds the JSONP script tag with a fixed callback name and `encodeURIComponent(address)`, and posts the
  Census answer back as a string. The parent accepts a message only if `e.source === frame.contentWindow`,
  `e.origin === "null"`, `typeof e.data === "string"`, length at most `MAX_ANSWER` (sized for 20 matches x 6 layers,
  Q1-check), and `JSON.parse` succeeds: the checks `address.js` already makes. The frame is removed after each lookup.
- As built (F5, 2026-11-19): `sitegen/national.py` `geo_frame_html()` returns the whole file from
  `site/templates/_geo_frame.js`; its CSP also closes `base-uri 'none'; form-action 'none'` (default-src does not
  cover them; nothing more is allowed). Every message the frame posts is JSON text: `"ready"`, the answer object,
  `"blocked"` (script error) or `"loaded"` (loaded, no object passed to the callback). The parent posts
  `{address}` (an object) once, after "ready"; national.js `frameMessage(e, frameWindow)` makes the four checks, and a
  string over `MAX_ANSWER` from the frame is `too-big` (not parsed; the "more than 20 matches" tips), anything else
  failing a check is ignored. `lookup(env, address, done)` creates and removes the frame and runs the 15 s timeout.
  Callback name: the frame's is the fixed `crGeocode`, and the address is URL-encoded into the one `address`
  parameter, so no Census-side callback check is needed for this design (see F5 note in the PR).
  Sandbox check (code review, `national/csp-jsonp-gadget`): a meta CSP cannot set `frame-ancestors` or `sandbox` and
  Pages sends no headers, so any site could embed geo-frame.html unsandboxed and drive the JSONP in our origin. The
  frame script's first statement is `if (self.origin !== "null" || parent === self) { return; }`: unless it runs
  sandboxed (opaque origin) inside a frame, it posts nothing, listens to nothing and loads no script.
- Follow-up outside M1 (so Clarksville pages stay byte-identical): move the existing landing-page address box to the
  same static frame (task F7).

### 4.1 Lookup script (`site/static/national.js`, node-testable like `address.js`)
- `jsonpUrl(address) -> string`: the geographies URL of ADR 0013 decision 2; `address` is the only variable part. Used
  by the frame's script (the frame file is built from the same function so a test holds one URL shape).
- Hardening (finding 9, `national/postmessage-hardening`): GEOIDs must match `^\d{5,10}$` (state part `^\d{2}$`)
  before they become ids; lookups into the directory, `alias`, `hide` and flag tables use null-prototype objects or
  `Map` (so an id of `__proto__` or `constructor` finds nothing); the pagedir is written into the page with `|tojson`,
  never string-built; every Census string is drawn with `textContent`.
- `classify(answer) -> {kind: "error" | "nomatch" | "pick", matches: [{label, units}]} | {kind: "one", units}`.
  `units` = `[{id, layer, name, funcstat, state}]` from the six layers, read by exact layer name; any other layer is
  ignored. More than 20 matches: "add the city and ZIP".
- `governments(units, pagedir) -> {govs: [{id, name, slot, status, board?, reason?, checked?, reason_url?, page?, full?,
  official_url?}], notes: [<label key>]}`; `notes` holds the fixed lines the list needs (each drawn from label
  `note.<key>`): `no-city` (no place kept: unincorporated), `no-county` (the Census returned a county and it was
  dropped for any reason: FUNCSTAT at step 1, as for the H4|N counties of CT, RI and MA, or `hide`/`rules` at step 2),
  and the `lines` flag of each returned unit, kept or dropped (`consolidated`, `independent-city`; the independent
  city's line rides on its dropped C7|F county copy); neither `no-city` nor `no-county` is added when one of those two
  lines is (3.3). `govs` empty -> the "nothing listable" state. Apply in order
  (1) drop units by FUNCSTAT (place, county, cousub: keep A or B, B being partially consolidated with its own
  officials; C, F, N, S and the rest dropped; school districts: keep A or E; manager, 2026-11-19, codes verified in
  B2), (2) gov-flags: `hide` by id drops, else `show` by id keeps (whatever the FUNCSTAT), else a `rules` entry with
  `show: false` drops; state rules only ever hide (a `show: true` rule is ignored, so a rule can never bring back an
  N, F or S unit: fail closed), (3) drop school district "not defined" units (GEOID ending 99999), (4) map through
  `alias`, then dedupe by id, (5) when a place is kept, drop a county subdivision whose COUSUBCC is T5, C2, C5 or C7
  (the class code says it is the same area as an incorporated place; names are not compared),
  (6) status from `govs`, else `not-covered-yet`, (7) order: place, county, cousub, then school districts
  elementary, secondary, unified (sde, sds, sdu; UX section 3).
  Pure; unit-tested with recorded answers.
- Device list (3.8): `loadList(storage) -> [{id, name}]` (validates, drops bad), `saveList(storage, govs)`,
  `forget(storage)` (removes the three keys), `markRequested(storage, ids)`, `markCounted(storage, id)`. All take the
  storage object as an argument so node tests use a fake; every call is wrapped so a blocked or full storage never
  breaks the page (the list is then simply not saved).
- Rendering order and focus follow the UX states table: one focus move after each result. The Census matched line is
  page text only. No `history`, `location` or `document.title` writes anywhere in the script (F3 asserts).
- Errors: no answer in 15 s -> "The Census lookup is not answering" + Retry; iframe blocked -> the same, plus the
  official Census lookup link. Never a guessed place.
- As built (F1, 2026-11-19; additive): `classify` "one" also returns `matched` (the Census matched line, page text
  only), and more than 20 matches is `{kind: "nomatch", many: true}` (the not-found tips); each unit also carries `cc`
  (PLACECC, COUNTYCC or COUSUBCC). `slot` is the layer name (the card draws label `slot.<slot>`), or the pagedir
  `slots` entry's `slot` for that unit's state and layer (3.3, AC2.11; to wire in national.js: step 7 orders by
  slot, and `no-city` is not added when a kept unit's slot is `place`; step 5 still compares real layers); `notes` holds full
  label keys (`note.no-city`). Bad pagedir (wrong schema): every kept unit is "not covered yet" with no flags. Storage also has `loadRequested`, `loadCounted` and `storageOf(win)`;
  `markRequested` keeps at most 200 ids; a stored value over 8,192 characters is not read.

### 4.2 Request form (in-card, several governments, one post)
- One form element is drawn inside the card whose "Request it" was tapped (the list itself needs script, so the form
  does too). Fields: `email` (type=email), a hidden `tag` = `req-<this card's id>`, and
  one checkbox named `tag` per other Not covered yet or Can't cover government in the current list, value
  `req-<id>`, unticked. The browser sends one `tag` field per ticked box, so one post carries several tags. Nothing
  else is posted. Values are built from ids that passed the id regex; a hand-edited form can only add a junk tag to
  that person's own subscription, and the report ignores unknown ids.
- Transport: `fetch(action, {method: "POST", mode: "no-cors", credentials: "omit", referrerPolicy: "no-referrer",
  body: new URLSearchParams(form)})` to `https://buttondown.com/api/emails/embed-subscribe/daylight` (a simple
  request: no preflight). The response is opaque, so "Sent" means "the post left the browser"; a rejected `fetch`
  shows the design's Failed state with the text kept. A Buttondown refusal (a 400, as seen for metadata on 2026-11-17)
  would look like success, and no email would arrive: this is risk R-B below and what Q2 tests.
  Fallback (if Q2 says the no-cors post does not subscribe): the same form as a plain `method=post` that navigates to
  Buttondown's own page, as the morning-note form already does; the device list means nothing is lost on return.
  The form is a real `<form method=post action=...>`, so if `fetch` is missing the browser posts it natively.
- On Sent: every government ticked in that form flips to the Sent state and its id goes to `daylight.us.requested`;
  the email stays only in a page variable so a second card's form is prefilled. The email is never written anywhere
  by us. The success text is the same for a new and an existing address (the page cannot tell).
- Confirmation landing: `digest/requested.html` if Buttondown's confirmation redirect can point there, else the
  newsletter-wide confirmation email carries the AC5.2 label (UX section 3). Which one is Q-A, tested in Q2. Both are
  settings in Brian's Buttondown dashboard, not code.
- Unverified before M1 goes live (Q2): that an existing confirmed subscriber's re-submit adds the new `req-` tags
  (platform-facts says a re-submit changes metadata, tags unrecorded); the no-cors post is accepted; the redirect.
- As built (F2, 2026-11-19; additive): the wiring is `national.js` `mount(env)` (no new static file), run on load
  when the page has `#digest-form`. The body is built from the page's own card ids (`email`, then `tag` = own id, then
  each ticked id), not from the form's DOM values, so a hand-edited checkbox value is not sent. "Request it" shows
  only when `#digest-config` has an https `form_action` and `privacy_url` (else the card has no form; the counter can
  still show). With no `fetch` the real form posts natively and its ids are marked requested before it leaves (the
  device list then holds them on return). If Q2 says the no-cors post does not subscribe, the switch to native post
  is one line in `mount` (`post = null`). Saved-list ids pass `layerOf` (the layer's exact GEOID length) before a card.

### 4.2a Counter button
- `window.DaylightCount = {available: boolean, send(govId) -> Promise<void>}` from `us-count.js` (3.9). `national.js`
  draws "No email? Just count me." in a card only when `available`; on success it calls `markCounted` and shows the
  Done text; on rejection the Failed text and the button stays. `us-count.js` loads before `national.js`; if it fails to
  load, `window.DaylightCount` is undefined and no button shows.
- Button and form are separate: the tap sends no email; the form sends no event. A person who does both is
  counted once as an email request (Buttondown) and once as a tap (GoatCounter); the report never adds them.

### 4.3 National builder (`sitegen/national.py`)
- `load_directory(path) -> Directory` (raises `NationalConfigError` naming the entry and key).
- `clarksville_feeds(directory, councils, county_agendas, today, *, checked_at, counts=None, bind_counts=None)
  -> dict[body_id, UpcomingFeed]` (B3: `sitegen/national_clarksville.py`): council meetings with `agenda.state =
  not-read` (or `not-posted`), county agenda-only meetings with items as stored. `councils` is `{council.yml body_key:
  (facts, listing)}`. `directory` supplies each feed's body and its `items` field (section 11); an entry gets the
  county feed or that council's feed by its `daylight.body` key, not its id, and a covered daylight entry whose key is
  neither the county's nor a council with inputs and a council.yml stops the build (`FeedError`). `checked_at`
  (aware) is when the inputs were collected (both `checked_at` and `last_ok_at`); `counts` receives the guards'
  counts per body for the run log. The inputs are loaded by the caller with the build's loaders; listing rows pass
  `sitegen/days.py calendar_rows` (the day page's rule). A posted council agenda whose link `allowed_url` refuses is
  `not-read` with a null `agenda.url`; a facts meeting whose only listing rows are called off is left out. Stored
  items are read only when `is_shown(entry)` and only on the county route (`COUNTY_BODY_KEY = "county"`, fixed in
  code; `FeedError` unless `config.SITE["county_key"]` equals it and no council's `body_key` does); each feed carries
  `review` and passes `bind_feed` before the schema check (section 11). Titles are
  the body's kind labels, or the fixed `Meeting` for an unlabelled kind (`title_ours` stays true). Each feed is
  checked against `schema/daylight-upcoming.schema.json` (`FeedError`). `meeting_url` is null for both bodies (no
  per-meeting source page; the page uses `official_url`).
- `build_national(out_dir, directory, feeds, labels, share, counter_on) -> list[path]`: writes each `.json` and
  `.html` only from `bind_feed(feed, entry)` output, only for a feed whose `body.id` is a covered directory entry, and
  prints items only from that bound object (section 11.1 row 15). Writes `digest/index.html`,
  `digest/covered.html` ("What we cover": covered and can't-cover entries by state, then name; share sentence only if
  `share` is given), `digest/requested.html`, and per covered government `digest/<st>/<body id>.html` and `.json`.
  Called from `sitegen.build` only when `national.enabled`. Pages render with the header variant (7a); the pages
  that load scripts are `digest/index.html` only (`national.js`, `us-count.js` when analytics is on); the others load
  none beyond the header's and `count.js`.
- `apply_site_fragments(pages) -> pages`: the three edits to existing pages, each a fixed string, each present only
  when `national.enabled`: the Menu group (footer list), the front-page line, and on `method.html` the browser-keys
  sentence swapped for label `method.keys` (design 9a, linking `digest/how.html`; QA national/method-page-claims).
  Anything else in an existing page is a bug.
- As built (B4, 2026-11-19), in `sitegen/national_pages.py`: `run(...)` is the build's one call;
  `build_national(out_dir, env, site, directory, flags, labels, page_labels, feeds, *, built_at, counter)`;
  `apply_site_fragments(pages, labels)` (pure) with `menu_fragment(root, labels)` and `front_fragment(labels)` for
  B5; the switch is `config/site.yml national: {enabled: false}`. Each feed's `checked_at` is its newest record
  (`newest_record_at`, see the M1 note in 3.5) and `last_ok_at` null; coming-up pages take the name and links from
  the directory entry (links re-checked on its platform's hosts; none usable: words with no link), and the full
  Daylight and morning-note links only for daylight-platform entries. Topic labels (AC4.7, QA
  `national/topic-labels-missing`, 2026-11-19): each shown item gets page label `body.topic-<list>` for each pair of
  `national_pages.TOPICS` (morning note list `zoning` by item type `rezoning`, `budget` by `budget`) whose item type
  `views.item_types` gives its verbatim number and text (config/site.yml `item_types`, published on the About page);
  a page with any label prints `body.topic-note` once, linked to `about.html#item-types`. Withheld meetings have no
  items, so no labels. Not in the JSON (derived, page only). `digest/index.html` embeds `#digest-pagedir`, `#digest-strings` (page labels `lookup.*`, `form.*`,
  `count.*`) and `#digest-config` (`frame`, `covered`, `requested`, `form_action`, `privacy_url`, `morning`, and the
  two outside links `election_url` and `census_url` from `config/national/links.yml`: each an https URL or null, and
  the script leaves a line out whole when its link is null; UX section 3 "Outside links"), and
  has the mounts `#digest-form`, `#digest-result`, `#digest-list`, `#digest-saved`, `#digest-noscript` for F2.
- As built (B-ISO, 2026-11-20; section 12): `run(...)` returns a `NationalRun` (`pages`, `state` `built` or
  `degraded`, `govs`) in three phases. `load_phase(folder)` loads and runs `check_load` (state, slot and `tz.` labels,
  `gov_page`, `national_copy.check_entry` for collected entries, `national_clarksville.route_checks` for daylight
  ones); its `NationalBuildError` is the only national exception `build.py` turns into `BuildError`. Tier 1:
  `build_feeds` (copy step or adapter per entry) and `build_national`'s per-government bind and render each run in a
  `try`; any exception gives `stale_feed(entry)`, a word of `DEGRADED_STATES` and `::warning::National pages: <id>:
  <state> (<type name>)`. Tier 2: anything else clears `digest/`, prints `::error::National pages: built with no data
  (<type name>)` and rebuilds all stale; a raise there stops the build. `council_inputs` carries an unreadable
  listing as its exception, raised in that council's tier-1 step. The build result and `build/run-log.json` carry
  `national` (`off`, `built`, `degraded`) and `national_states` ({body id: `withheld-items` | `bad-date` |
  `bad-instant` | `adapter-error` | `render-error`}, degraded governments only; D-ISO-9 reads both).

### 4.4 Fetcher tenant rule (`collector/fetch.py`, M2)
- `SHARED_HOSTS = {"webapi.legistar.com": re.compile(r"^/v1/([a-z0-9-]{2,40})/")}`.
- `tenant_key(url) -> str | None`; the client path segment is lowercased before it is matched or stored (finding 10,
  `national/tenant-key-normalize`). `_blocked` gains tenant keys; `_raw_get` checks host and tenant blocks.
- On 403: robots.txt or non-tenant path or non-JSON body or second distinct tenant -> host block; else tenant block.
  On 429: host block. Exceptions: `TenantBlocked(HostBlocked)` so existing `except HostBlocked` callers still stop.
- `limit_tenant(url, n)`: per-tenant cap inside the host cap.

#### 4.4.1 Invariant: one tenant key per server-side client (`national/tenant-block-escape`, stated after the 2nd hit)
**Invariant.** For a shared host, every URL the fetcher sends either has a tenant key equal to that of every other
spelling the server may treat as the same client, or is refused before any request. A blocked or capped tenant is
then unreachable by any spelling, because no un-keyed spelling of it is ever sent.

**Design: refuse anything not already canonical; never rewrite.** One parser, `shared_path(url) -> (site, tenant |
None)`, run on the raw path exactly as it will be sent (urllib sends `Request(url)`'s path unchanged; the proxy is a
CONNECT tunnel). On a shared host the raw path must match `^/(SEG(/SEG)*/?)?$` with
`SEG = [A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*` (empty path counts as `/`); else `TenantPathRefused`. That one grammar
closes every family member at once: no `%` (so no `%73`, `%2f`, `%2e`, double encoding), no empty segment (`//v1/`),
no dot segment or leading/trailing dot (`..`, IIS `salem.`), no backslash, `;`, `+` or non-ASCII. Then, if segment 1
case-folds to `v1`: segment 2 must fullmatch `[A-Za-z0-9-]{2,40}` (else refused) and the tenant is
`site + "/" + seg2.lower()`, with or without further segments (`/v1/salem` is salem's too). Case is the only variation
mapped rather than refused: it is ASCII-only by the grammar, and Legistar (IIS) treats it as one client. The query is
not part of the key (the client comes from the route). Why refuse rather than canonicalise and send the canonical
form: we cannot know every normalisation the server does, sending a URL other than the one asked for changes what a
redirect meant, and our own readers (4.5 `events_url`) only ever build canonical paths, so refusal costs nothing
legitimate. `ambiguous_tenant_path` and the split/regex in `tenant_key` are replaced by `shared_path`;
`tenant_key(url)` returns its tenant, None for a non-shared host or a malformed URL, and raises `TenantPathRefused`
for a non-canonical shared path (None must only ever mean "host-level and allowed").

**Every consumer in `collector/fetch.py` and how it uses the key** (all through `tenant_key`, never their own parse):
1. `check_url`: calls `shared_path` on every URL and every hop (`get`, `_raw_get`, `_location`); refused = no request,
   log `refused` with the raw URL.
2. `_raw_get` block check: `tenant_key` after `check_url`; looked up in `_tenant_blocked`; with `_tenant_ok=False` a
   hit is a host block (unchanged).
3. `_raw_get` cap check and count: `remaining_tenant(url)` and `_tenant_sent[tenant]` use that same key; retries
   re-enter `_raw_get`, so they are re-checked and counted.
4. `limit_tenant` / `remaining_tenant`: same key; a non-canonical URL raises `TenantPathRefused`, a non-tenant
   URL `ValueError` (unchanged).
5. `check_tenant_redirect`: origin and target keys; the target has already passed `check_url` in `_location`.
6. `robots()`: robots.txt has tenant None (host-level); every hop goes through `_raw_get(_tenant_ok=False)`. Any
   `HostRefused` (`TenantPathRefused` included) or `RequestCapReached` on the first request or a hop caches
   `disallow_all` for that exact host for the run and logs `robots_refused` (reviewer nit 6). Caps only ever lower,
   so nothing would become fetchable later; without the cache every `get()` re-asks.
7. `_tenant_only_block` (403 classifier): gets the key from `_raw_get`; "second distinct tenant" compares keys by the
   `site + "/"` prefix, so spellings of one client never count as two tenants.
8. Log: `blocked` and `cap` events carry `tenant` as the canonical key, so health and C3 group by it.

#### 4.4.2 Invariant: classify fails closed (`fetch/403-body-*`, stated after the 2nd hit)
software-architect, 2026-11-19. Hits: `fetch/403-body-read-escapes` (C1 code review: a failing `e.read()` escaped),
`fetch/403-body-parse-escapes` (S2a security finding 1: a nested JSON 403 body raised RecursionError in
`_json_object`). Both are one gap: the refusal branch assumed it knew every error type its own steps can raise.

**Invariant.** When the site answers a request with a refusal (HTTP 403 or 429, on any URL, robots.txt and redirect
hops included), the fetcher leaves `_raw_get` only by raising `TenantBlocked`, `HostBlocked` or `ProxyRefused`, and
for the first two the block is already recorded (`_tenant_blocked[tenant]` or `_blocked[site]`) before the raise.
Any error of any type (`Exception` and every subclass: OSError, ValueError, UnicodeDecodeError, RecursionError,
MemoryError, TypeError, AttributeError, KeyError) raised while reading, decoding, parsing or classifying that answer
(body read, body decode, JSON parse, header read, proxy attribution, the tenant-or-host decision) makes the answer a
**host block** for the run (`_blocked[site]`, reason `HTTP <code> from the site on <url> (answer not classifiable:
<type name>)`, a `blocked` log event, `HostBlocked`). It never escapes the classifier with no block recorded, and it
never yields a tenant block: a tenant block needs positive evidence (a 403 on a tenant path whose body parsed as a
JSON object, no other tenant of the site blocked), and an error is the absence of evidence. Consequence: after any
refusal answer, no further request goes to that host (or, for a clean tenant block, to that tenant) this run,
whatever the answer's bytes or headers are.

**Design (owner backend-engineer, opus/high).** One method decides and one place records. `_refusal_decision(e,
host, key, tenant, url, started, tenant_ok) -> ("proxy" | "tenant" | "host", reason)` does every read, decode, parse
and the decision inside `try: ... except Exception as x: return "host", <not-classifiable reason>`; it raises
nothing. The 403/429 branch of `_raw_get` then records the block for the decision and raises, outside that `try`
(so the guard can never swallow the `TenantBlocked`/`HostBlocked` it is meant to raise). Nothing that can raise sits
between the decision and the record: the dict write is the first statement, then `log.append`, then the raise
(`from None`, so the body never rides along as `__context__`). `BaseException` that is not an `Exception`
(KeyboardInterrupt, SystemExit) is not caught: the run stops and writes nothing.

**Every site in `collector/fetch.py` that reads or classifies an error answer** (lines at 20c073d):
1. `:490-492` proxy attribution, `_proxy_said_403` (`:432-441`): catches only ValueError from `fromisoformat`; a
   non-dict entry (AttributeError) or a `ts` without a zone compared with the aware `since` (TypeError) escapes. Must:
   inside the decision guard; any error = not attributed to the proxy, so the answer is the site's (block).
2. `:493-495` body read `e.read(BLOCK_BODY_BYTES)`: catches OSError and HTTPException; a ValueError (read on a
   closed response) or any other type escapes, because the sibling `except` clauses at `:514`/`:528` do not cover
   code inside an `except` block. Must: any error -> body `b""` (not JSON, so host block).
3. `:496` snippet decode (`errors="replace"`): cannot fail today; inside the guard anyway.
4. `:497-498` header read `e.headers.get('Server')`: AttributeError when `e.headers` is None (`:513` already allows
   for None). Must: inside the guard; read through `(e.headers or {})`.
5. `:499` and `:536-542` `_tenant_only_block` -> `_json_object` (`:255-259`): catches UnicodeDecodeError and
   ValueError only; RecursionError (finding 1) or MemoryError escapes. Must: `_json_object` returns False on any
   `Exception` (defence in depth), and the call is inside the guard.
6. `:500-506` record and raise: already in the right order (dict write, log, raise); must stay so, outside the guard.
7. `:507-509` 5xx retry: re-enters `_raw_get`, so a 403/429 on the retry goes through 1-6; no rule of its own.
8. `:513` every other error answer (4xx other than 403/429, a 5xx after its retry, 304): not a refusal, so outside
   this invariant, but the same shape. Must (finding 3, `fetch/error-body-unbounded`): `e.read(self.max_bytes + 1)`
   with the same size trip as `:484-487`, and any error reading it -> `FetchFailed` (logged `error`), never a raw
   exception.
9. `robots()` `:544-584`: robots.txt goes through `_raw_get(_tenant_ok=False)`, so its 403/429 is 1-6 and always a
   host block (`HostBlocked` is not a `HostRefused`, so it leaves `robots()` uncached, but `_blocked` already stops
   the host). A 200 robots.txt: `rp.parse` (`:575`) and the crawl delay (`:581-583`) must treat any error as
   unreadable: cache `disallow_all`, set `_robots_unreadable[exact] = "unparseable"`, log `robots_refused` (as a
   server error does), never leave `_robots[exact]` unset so every `get()` re-asks. Other `_raw_get` failures on
   robots.txt (`FetchFailed`, `ProxyRefused`) are not refusals and keep today's behaviour.
10. `get()` `:618-635` and `_location` `:592-616`: redirect hops are requested through `_raw_get` (so 1-6 apply);
    Location parsing already maps to `SchemeRefused`/`FetchFailed`. No change.
11. Caller, `collector/national/run.py` `_read_one` `:286`: keeps `except Exception` (one body's failure is never
    the run's) and tests `TenantBlocked` before `HostBlocked`; with this invariant the classifier can no longer hand
    it an unclassified error after a refusal.

**Tests (C1 follow-up):** for each of a nested 403 body (`[` * 60000), a 403 whose `e.read` raises ValueError, a 403
with `e.headers` None, a proxy status entry that is not a dict and one with a zone-less `ts`, and a 429: the call
raises `HostBlocked`, `_blocked[site]` is set, and a following `get()` to another tenant of the same host sends zero
requests (opener call count). A table test patches the decision's helpers to raise each of the exception types named
above and asserts the same. A 200 robots.txt whose parse raises (patched) caches `disallow_all` and is not re-asked.

#### 4.4.3 Invariant: outside or on-disk JSON that fails to parse is unreadable (`collector-input/json-depth-recursion`)
**Invariant.** Every parse of JSON that came from outside (an answer) or from disk (`national-data` files, the cache)
treats any `Exception` from read, decode or `json.loads` (RecursionError included) as "unreadable", with that site's
existing unreadable outcome; the same holds for any later recursive walk of a value so parsed (`copy.deepcopy`,
`bind_feed`, `clean_feed`, schema validation), because `json.loads` accepts nesting that `deepcopy` cannot copy
(checked: 500 levels parse and then make `copy.deepcopy` raise RecursionError at the default limit). Recommended
shape: one helper, `parse_json(raw) -> object | None`, that catches `Exception` and refuses a value nested deeper
than 32 levels (an iterative check; our deepest real document is about 6), so later walks never see deep values.
**Sites** (lines at 20c073d):
1. `collector/fetch.py:255-259` `_json_object`: 4.4.2 site 5.
2. `collector/national/legistar_upcoming.py:350-353` `_get_json`: any error -> `ReadError("not-enabled-suspected")`
   (today a RecursionError becomes `collector-error` via `_read_one`; harmless but the wrong kind).
3. `legistar_upcoming.py:268-271` `_sweep`: any error -> `doc = None` (the file is deleted as a miss).
4. `legistar_upcoming.py:288-291` `_cache_get`: any error -> a miss and the file deleted (today one nested file
   fails that body on every run).
5. `collector/national/run.py:406-409` `_load_json` (`read_previous`: `bodies/`, `health.json`, `proposals.json`):
   any error -> None (today a nested `health.json` aborts `collect()`).
6. `run.py:184-189` `_kept_feed`: `copy.deepcopy` and `bind_feed` of a previous feed that parsed but nests deeply:
   any error -> None (page stale) and the body keeps its real outcome; today `_record` raises and the run loop
   (`:377`) records `collector-error` instead. Covered by the depth cap in the helper.
7. D2 copy step (4.6, not built yet): reading each `national-data` body file -> any error = file missing (page stale),
   per 11.1 row 16.
8. Not in scope, recorded: `fetch.py:275` (the local proxy status page; already `except Exception`),
   `sitegen/national_clarksville.py:80` (a listing committed in this repo; an error fails the build, which is the
   closed outcome there) and `:233` (our own schema file).
Tests: a nested document (`[` * 60000 and `{"a":` * 500) at each of sites 2-6 gives that site's unreadable outcome,
and `collect()` completes and writes its outputs.

#### 4.4.4 Invariant: nothing is sent at or after the run deadline (`national-budget/*`, stated after the 2nd hit)
Family hits: `max-no-margin`, `no-wall-deadline`, `post-deadline-request` (docs/reviews/code-review-daylight-national-cli.md).
**Invariant.** With a deadline `D`, no request (an answer request, robots.txt, a 5xx or reset retry, a redirect hop)
is sent at or after `D`, and no wait is slept that would end at or after `D`. At most one request is in flight at
`D` (the fetcher is single-threaded), so the overrun past `D` is that one request's duration, bounded by
**X = max(T_open, A) + T = 360 s**: `T` = 120 s, the fetcher's per-operation socket `timeout`; `T_open` (connect, TLS,
status line and headers) is at most 2T = 240 s for a server that sends each within one socket timeout; `A` = 120 s,
the new total-answer cap below, checked between body chunks, so one more blocking read of at most T can follow it.
Retries and redirect hops are new requests, so they do not add to X: each goes back through `_raw_get` and is refused.

**Why today's guard breaks it.** `_deadline_sleep` wraps `sleep`, which `_wait` calls only when `gap < delay`. When
an answer takes 10 s or more, the gap is already past the delay, nothing sleeps and nothing checks: the body in
flight goes on sending up to its tenant cap (12 x up to 120 s), past the 15 min margin. The reviewer's probe shows 5
requests sent at 30-90 s against a 20 s deadline. The check also uses `>`, so a wait ending exactly at `D` is sent.

**Decision: a default-off hook on PoliteFetcher, not a run-scoped wrapper.**
- `PoliteFetcher.past_deadline: Callable[[float], bool] | None = None`: "would a request sent `pause` seconds from
  now be at or after the deadline?" `_wait` (the one function every request goes through: `_raw_get` calls it after
  the block and cap checks, and robots.txt, retries and redirect hops all go through `_raw_get`) becomes: compute
  `pause` (0, or `delay - gap`) exactly as today; if the hook is set and `past_deadline(pause)` -> log
  `{"event": "deadline", "host", "url"}` and raise `DeadlineReached` (moved to `fetch.py`, still a
  `RequestCapReached`; `run.py` re-exports it) before sleeping and before `_last`, `_sent` or `_tenant_sent` change;
  sleep; if the hook is set and `past_deadline(0)` (a sleep that overshot) -> the same raise; then set `_last`. With
  the hook `None` the calls to `clock()` and `sleep` are exactly today's, so Clarksville is byte-identical.
- `run()` installs `fetcher.past_deadline = lambda pause: clock() + timedelta(seconds=pause) >= deadline` (one time
  source: the run's own `clock`, the same one `_read_one` checks the body start against) and restores the previous
  value in `finally`. `_deadline_sleep` and the `fetcher.sleep` swap are deleted. `deadline` without `clock` raises
  `ValueError` before any fetcher call or file access (`frozen-clock-deadline`); so does a naive `deadline` (today).
- Why not the wrapper: a run-scoped wrapper has to patch two public methods on the instance (`remaining` to read 0
  past `D` and `sleep` to refuse a crossing wait) and relies on `_raw_get` calling `remaining()` before `_wait` and
  never sending between the two. A later fetch.py edit can break that silently, which is how this hit happened. The
  hook sits in the one place a request is sent, and costs one `is not None` test on the Clarksville path.
- **Total-answer cap** (`PoliteFetcher.max_answer_seconds: float | None = None`; the national CLI passes 120.0 and the
  4.6 fetcher-kwargs test is updated). Without it a server that drips its body one segment just under `T` apart keeps
  one request open far past `D` (5 MiB at that pace would take days), and urllib's `timeout` is per operation, not per
  request. When set, every body read in `_raw_get` (the 200 answer, the error answer, and `_refusal_decision`'s 64 KiB
  block read, which fails closed to a host block) reads in 64 KiB chunks and raises `FetchFailed` ("answer slower
  than A s", the body's `server-error`) once `clock()` minus the request's start passes `A`. `None` keeps today's
  single `read(max_bytes + 1)`.
- Residual (accepted, recorded in 8): a server that drips its TLS handshake or headers can stretch `T_open` beyond
  2T; the job timeout is the backstop (nothing written, the pages show stale). Legistar is an approved API, not a
  hostile one; the D1 job flags a run killed by its timeout so a repeat is seen. The same holds for **chunked
  framing** (`national-budget/chunked-framing-drip`): on `Transfer-Encoding: chunked`, `read1` also reads the
  chunk-size lines (with extensions, up to 64 KiB) and the trailer with `readline`, many socket reads each up to `T`,
  which the per-read check cannot cut short. The reader checks `clock() - t0 > A` once more after its last read, so
  such an answer fails the fetch (never accepted), but only after the drip ends: X = 360 s does not bound it. The job
  timeout is the backstop; enforcing `A` below http.client (a raw reader, or a per-request watchdog that shuts the
  socket) is in the backlog.

**Margin check (the 15 of 75 min).** The deadline is `start + RUN_SECONDS` where `start` is taken inside the CLI, so
the margin covers: job setup before the CLI starts (checkout of `national-data`, Python, install: at most 3 min, D1
step timeouts), X = 6 min, the writes (about 100 small files, under 1 min), and commit, attest and push after (at
most 3 min, D1 step timeouts). 3 + 6 + 1 + 3 = 13 <= 15, so **`MARGIN_MINUTES = 15`, `RUN_SECONDS = 3600` and
`MAX_BUDGET = 360` hold**. The deadline, not the budget, now bounds time; `MAX_BUDGET` only keeps a full-spend run at
the 10 s floor from always ending on the deadline. D1 requirement: those step timeouts are set (setup <= 3 min, after
<= 3 min); if D1 cannot keep them, the CLI's margin grows by the difference, never the other way.

**Consumers (11).** `fetch.py`: `_wait` (the check), `_raw_get` (calls `_wait` after the cap checks, so a capped or
blocked host never consults the hook; the three body reads take the cap), `robots()` (a `DeadlineReached` on
robots.txt is a `RequestCapReached`: robots cached as capped for the run, later `get()`s raise the cap), `get()`
(redirect hops), the reset and 5xx retries. `run.py`: `run()` (installs and restores the hook; `clock` required),
`_read_one` (body-start check `when >= deadline`; `_classify` maps `DeadlineReached` to `budget-skipped` and stops
the host for the rest of the run), `collect()` (passes both through). `__main__.py`: `_main` (passes `clock=_wall`
and `deadline=start + RUN_SECONDS`), `build_fetcher` (adds `max_answer_seconds=120.0`), and the module docstring
(margin items as above, "the body in flight" bounded by X).

#### 4.4.5 Invariant: freshness stamps move only when a request for that body was sent (`national-freshness/*`)
Family hits: `checked-at-is-first-fetch` (M1), `deadline-stamp-without-request` (CLI delta review).
**Meanings.** Each is the run stamp `s` of one body's read: `clock()` when that read starts (before its first wait).
- `last_attempt_at` (health): `s` of the last read in which at least one request to the body's **tenant** was sent
  (any outcome, including a reset, a 5xx, a 403, or a retry refused by the deadline). robots.txt is a host request,
  not one for the body, so it does not count.
- `checked_at` (feed): the same condition and the same value as `last_attempt_at` ("when we last asked this
  government's source"). The page's "last checked" line (AC4.6) shows it.
- `last_ok_at` (feed and health): `s` of the last read whose outcome is `ok` (every answer the read needed came back
  and the feed bound). Always `<= checked_at`. The stale flag (`STALE_AFTER`, 3 days) is computed from it: data age,
  not check age.
**Rule.** A read sent a tenant request iff `fetcher.remaining_tenant(url)` after the read is lower than before it
(public API; `run()` always caps every tenant first, so neither is None). `_read_one` returns stamp `s` only then,
and `None` otherwise, on every path: the cap pre-check, the deadline before the read, a first wait refused by the
deadline, `RobotsDisallowed`, `HostRefused`/`ProxyRefused` before sending, `TenantBlocked` raised before sending, a
reader refusal before its first `get` (`host_ok`, cache), and `collector-error`. With stamp `None` all three values
stay byte-equal to the last run's (health carried over, kept feed's `checked_at` untouched); outcome, failure count
and streak still follow 3.7 (so `robots` counts as a failure while its stamps do not move: the stale line then
tells the truth that the source was not asked). An `ok` outcome with no tenant request is a bug: recorded
`collector-error`. A previous stamp that is not a valid instant is dropped (`_old_instant`), which is not a change.

**Consumers (17), file:function.**
Writers: (1) `collector/national/legistar_upcoming.py:read_body` writes `checked_at = last_ok_at = s` on `ok` only;
(2) `run.py:_read_one` decides `s` or `None` (the rule above; today it stamps before the read, the bug);
(3) `run.py:_record` `ok` branch (both health stamps = `s`) and failure branch (`last_attempt_at = s or previous`,
`last_ok_at` previous, else the previous feed's); (4) `run.py:_kept_feed` sets `checked_at` only when `s` is not
None; (5) `run.py:run` bare `collector-error` fallback record: must carry each previous valid stamp (`_old_instant`,
each in its own guard) instead of `None`, which today erases a good `last_ok_at` without a request;
(6) `run.py:write_outputs`/`body_file` (pass-through); (7) `sitegen/national_clarksville.py:clarksville_feeds` and
`sitegen/national_pages.py:build_feeds` (M1 Clarksville: `checked_at` is the newest record, `last_ok_at` null; 3.5,
unchanged).
Readers: (8) `run.py:read_previous`; (9) `run.py:budget_order` (health `last_ok_at`: never read or oldest first, so a
body the deadline cut keeps its place at the front); (10) `run.py:_record` / `merge_proposals` (`first_seen = s or
now`, earliest kept); (11) D2 copy step (4.6, not built): copies `checked_at`/`last_ok_at` through `clean_feed`,
`bind_feed` and the schema, never restamps; (12) `sitegen/national_guards.py:bind_feed` and
`schema/daylight-upcoming.schema.json` (instant format, `last_ok_at` nullable); (13) `sitegen/national_pages.py:
build_national` (`last_ok` map -> page directory; forces `stale: false` for daylight only); (14)
`sitegen/national.py:page_directory` (`stale` from `last_ok_at`); (15) `site/static/national.js` card loader
(`g.stale`); (16) `sitegen/national_pages.py:newest_day` + `site/templates/digest/body.html.j2` (`body.newest` from
`checked_at`): **gap for M2**: on a Legistar page `checked_at` is a check time, not the newest record, so D2's page
work (owner frontend-engineer, label from ux-designer) shows "last checked {date}" from `checked_at` and the AC4.6
stale line from `last_ok_at` for non-daylight bodies; Clarksville keeps `body.newest`; (17)
`sitegen/national_feeds.py:render_ics` (DTSTAMP), `atom_entries` (fallback `updated`) and `render_atom` (feed
`updated`), all from `checked_at`, which now moves only when the source was asked.

#### 4.4.6 Tests the fix must add (owner backend-engineer, opus/high: data integrity)
1. Slow answers, one body, several requests: a fake net where each answer advances the wall 15 s and a 20 s deadline
   (the reviewer's probe as a test; the fetcher built with `wall`/`clock` from the same fake): every request starts
   before `D`, at most one ends after it, the body records `budget-skipped`, later bodies too, outputs written.
   Parametrised so the deadline falls before robots.txt, between a 5xx and its retry, between a reset and its retry,
   and between a 3xx and its hop: none of those is sent.
2. A wait that would end exactly at `D` (`>=`) and one that would cross it (Crawl-delay 30 s): `sleep` never called,
   no request, `_sent` and `_tenant_sent` unchanged.
3. Refused first wait keeps stamps: a body with previous health and feed whose first wait is refused: health
   `last_attempt_at`/`last_ok_at`, failures and streak, and the kept feed (`checked_at` included) equal the last
   run's. Same for the cap pre-check, `robots` (failure count +1, stamps unchanged) and a `collector-error` raised
   before any `get`.
4. First tenant request sent, its retry refused by the deadline: `last_attempt_at` and `checked_at` = the read's start,
   `last_ok_at` unchanged, outcome `budget-skipped`.
5. `ok` read: all three equal the read's start stamp, not the run's `now`.
6. `_record` raising: the fallback record keeps the previous valid `last_ok_at` and `last_attempt_at`.
7. `run()` and `collect()` with `deadline` and no `clock` raise `ValueError` before any fetcher call or file access;
   the hook is restored after `run()` returns and after it raises.
8. Slow body: with `max_answer_seconds` set, a fake answer whose chunks each advance the clock 50 s raises
   `FetchFailed` (body `server-error`); with it `None` the same answer is read whole.
9. Clarksville unchanged: every non-national test that uses the fetcher (`grep -l "collector.fetch\|PoliteFetcher"
   tests/`, e.g. test_cities, test_days, test_rpc_daily, test_rpc_backfill, test_county_committees, test_daylight,
   test_round2_polish) passes with no edits; a spy test shows that with both new fields `None`, `_wait` makes the
   same `clock()` and `sleep` calls as before and the body is read with one `read(max_bytes + 1)`; the full suite
   passes; the reviewer's probe (`probe2.py`) shows no request at or after 20 s.

### 4.5 Legistar upcoming reader (`collector/national/legistar_upcoming.py`, M2)
- `events_url(client, body_id, start, end) -> str` (`$filter=EventBodyId eq N and EventDate ge ... lt ...`).
- `agenda_state(event, final_statuses) -> "final" | "not-final" | "not-posted"`.
- `meeting(event, items, tz) -> dict` in 3.5's shape; `items` only for final agendas of a government whose entry says
  `items: shown`; for any other the items request is never made and `item_count` is null (a count would need the same request; if the
  spec wants counts for school boards that is a separate decision, not a default). `may_be_incomplete = true`.
- `run(directory, fetcher, budget, now) -> (feeds, health, proposals)`; never raises on one body's failure.
- Items only when `is_shown(entry)`, only for the entry's `client`/`body_id` (events with another `EventBodyId`
  dropped and counted), `review` stamped, `bind_feed` before writing; cache rules in section 11.1 rows 18-19 (M2).
- As built (C2, 2026-11-19): `read_body(entry, fetcher, now, cache_root) -> BodyRead(feed, proposals, counts)` reads
  one body and raises (`ReadError.kind` is a 3.7 `last_error` value; fetcher exceptions pass through); `run` (budget
  order, health, never raising) is C3's, around it. `prune_cache(directory, cache_root)` is row 19's first step.
  `final` is an exact match of `EventAgendaStatusName` against `final_statuses` (default all of
  `LEGISTAR_FINAL_STATUSES`), not ADR 0013's `^final\b` regex: fail closed. Proposals for a name that is neither
  final nor `Draft`. Meeting id `<date>-e<EventId>`; `title` is `EventComment` or the fixed `Meeting`. Cache file
  `{schema: daylight-legistar-cache/1, review, body, event_id, last_published, items}`, written only from the bound
  feed.
- As built (C3, 2026-11-19): `collector/national/run.py`. `run(directory, fetcher, budget, now, *, previous_feeds,
  previous_health, previous_proposals, cache_root, clock, tenant_budget=12) -> RunResult(feeds, health, proposals,
  outcomes)` (`outcomes`: body id -> `ok` or its `last_error`, the run log); `collect(data_root, ...)` reads the last
  outputs, runs and writes `bodies/`, `health.json`, `proposals.json`. `prune_cache` runs first. Each read is stamped
  by `clock()` as it starts (default `now`): `checked_at`, and on success `last_ok_at`, but only when the read sent a
  request to the body's tenant (4.4.5); a failed read keeps its last good feed rebound to the current entry with the
  new `checked_at`; a body not read, or read without a tenant request, keeps its stamps and feed unchanged. A
  `TenantBlocked` (tested before `HostBlocked`) stops its tenant and denies `<client>.legistar.com` for the run;
  another `HostBlocked`, or robots.txt that could not be read (`robots_refused` in the log), marks the rest
  `host-stopped`, as does robots.txt answering a server error (fetcher `robots_unreadable(host)`); a cap marks them
  `budget-skipped`, as does the run's wall-clock `deadline` (4.6, invariant 4.4.4). After 3 failures in a row of the same one of
  `not-enabled-suspected` / `token-suspected` / `robots` (`failure_streak`), a `status` proposal names the `cant-cover` reason it suggests; a good read clears it. Proposals
  read back are re-checked (status name pattern, `allowed_url` for the body's client). `collect` refuses a symlinked
  data root, `bodies/` or `cache/` before reading anything; body files drop `body.full_url`. The directory is never
  written.

### 4.6 M2 workflow requirements (D1 `national-update.yml`, D2 copy step; from security review S2a)
These were "needs verification in D1/D2" in `docs/reviews/security-review-daylight-national-s2a.md`; they are
requirements, and S2's D1/D2 review checks each.
- **D1 fetcher.** The collect job builds the fetcher as `PoliteFetcher(allowed_hosts=("webapi.legistar.com",),
  max_bytes=lu.MAX_RESPONSE_BYTES, ...)`. The defaults (`ALLOWED_HOSTS`, `MAX_BYTES` = 200 MiB, 40 times
  `MAX_RESPONSE_BYTES`) are the Clarksville collector's and must not reach the national job.
- **D1 logs.** Never print `fetcher.log`, an exception's `str(err)`/`repr(err)` or a traceback of a fetcher or reader
  exception to the public CI log, a step summary or an artifact, and never commit them: they carry up to 200
  characters of a 403 body and the Server and Location headers (4.4.2's block reason). The job prints only
  `RunResult.outcomes` (body ids and 3.7 kinds) and counts; its entry point catches `Exception` and prints only the
  exception's type name and the body id.
- **As built (D1 entry point, 2026-11-19):** `python -m collector.national DATA_ROOT [--budget N] [--directory
  PATH]` (`collector/national/__main__.py`; no option abbreviations). Budget default 300, 1 to 360: the job's 75
  min timeout less a 15 min margin (setup, the body in flight, writes, commit and attest) is 60 min, at the 10 s
  floor (`national-budget/max-no-margin`). **Deadline** (`national-budget/no-wall-deadline`): the run stops reading
  60 min after it starts by the wall clock, whatever the request count (a robots.txt Crawl-delay above 10 s
  stretches every wait): `run`/`collect(..., deadline=)` record the bodies not read, and a body whose fetcher wait
  would end past it (`DeadlineReached`, a `RequestCapReached`, raised before the request is sent), `budget-skipped`,
  and the outputs are still written. **Superseded in part by 4.4.4** (`post-deadline-request`): the check moves from
  a `sleep` wrapper into the fetcher's `_wait` (hook `past_deadline`, every request), `>=` not `>`, `clock` required
  with `deadline`, and `max_answer_seconds=120` bounds the request in flight; margin and 360 cap re-checked there. stdout: `body <id> <kind>` per body and one `counts ...` line; a failed run
  prints `failed: <type name>` (plus `body <id>` for `HostNotApproved`, which carries a checked `gov`) to stderr and
  exits 1. Exit 0 a completed run with a body read `ok` (or none to read); **3** a completed run, outputs written,
  with any `collector-error` or no body `ok` (`cli-exit/silent-all-failed`: D1 commits the outputs and flags the
  run); 2 bad arguments; 130 interrupted.
- **D1 data path.** The job checks `national-data` out at a path it creates itself (a fresh `actions/checkout` with
  `path:` into a new directory), never through an existing `data/` tree, because `check_data_root` checks the data
  root, `bodies/` and `cache/` but not their parent `data/`.
- **D2 copy step.** For each kept body file: parse per 4.4.3 (any error = file missing), then `clean_feed`, then
  `bind_feed` against the current directory entry, then the schema; only that output is written to `digest/`. The
  collector's files are not trusted as cleaned: `_kept_feed` (`run.py:178-191`) rebinds but does not re-run
  `clean_feed` or `allowed_url`. The copy step never raises on data (section 12): after `bind_feed`,
  `withheld_stripped > 0` gives `withheld-items`, a bad `date` `bad-date`, a bad instant `bad-instant` (each
  `stale_feed`, one `::warning::` with id, word and count); only the reviewed entry's R5 keys raise `CopyError`, and
  those are checked in the load phase. It runs inside tier 1 of the three phases (4.3 "As built (B-ISO)").
- **M4 writers.** The ICS and Atom writers trust their input, so M4 passes them only feeds that came out of the D2
  step above (bound feeds).
- **As built (D1, D2; devops-engineer, 2026-11-20).** `.github/workflows/national-update.yml`: `gate` (contents
  and attestations read: national-data's head N is the pinned seed or attested by `national-update.yml@refs/heads/main`;
  no branch yet = clean no-op), `collect` (main only, contents read, no token; code and N in new folders `code/` and
  `national/`; step timeouts 1+1+1 before the CLI, 69 for it, 2 after, job 75 = `JOB_MINUTES`; the CLI runs with
  workflow commands stopped and without GITHUB_OUTPUT/ENV/PATH/STEP_SUMMARY), `push` (the only writer: one commit on
  N, data/national/** only, attest, then fast-forward push), `report` (one fixed-title issue on failure, timeout or
  exit 3). One tree helper (`national_check`) in both jobs and in `daily-update.yml`. D2: the daily gate's soft step
  "Find the newest attested national-data" (first-parent, at most 10 commits, same pinned identity; the seed is never
  read) feeds `national_sha`; the update job checks N out into `.national-data`, moves `data/national` to
  `$RUNNER_TEMP/national` (never into `data/`), and passes it as `RECORDS_NATIONAL_DATA` to the two build steps;
  `sitegen/national_copy.py` is the copy step, called by `national_pages.build_feeds` only while the switch is on.
  Tests: `tests/test_national_workflow.py`, `tests/test_national_copy.py`.

## 5. Key flows
1. **Lookup (M1):** `/digest/` loads (directory embedded; a page-view count if counting is on, path only; the saved
   list is drawn from `daylight.us.list` if present) -> submit -> sandboxed `geo-frame.html` (4.0) JSONP to Census -> answer posted
   to the page -> `classify` -> (pick if several) -> `governments` -> list drawn on the same page (URL and title unchanged) ->
   `saveList`. Requests carrying the address: one, to `geocoding.geo.census.gov`.
2. **Request it (M1):** "Request it" on a card opens the in-card form -> email (+ optional ticked others) -> one
   no-cors POST to Buttondown with `email` and one `req-<id>` per government -> Sent state on each ticked card,
   `markRequested` -> Buttondown's confirmation email -> person taps the link -> (`digest/requested.html` or the
   email's own label) -> confirmed subscriber with `req-` tags. The morning note ignores them (B7).
2a. **Just count me (M1, only if `DaylightCount.available`):** tap -> one GoatCounter event `count-<id>` -> Done
   state, `markCounted`. No email, no address, no Buttondown call.
2b. **Forget this list:** removes the three storage keys, redraws the entry page empty.
3. **Coming-up page (M1):** static page built from the government's JSON; "last checked" line from `checked_at`; stale
   line when `last_ok_at` is more than 3 days old (UX has a second wording past 7 days: both are build-time).
4. **Collection (M2):** `national-update.yml` -> fetcher with tenant rule and budget -> per body: events -> state ->
   items if final and changed -> feeds, health, proposals -> push `national-data` -> attest. Daily deploy reads the
   newest attested `national-data`.
5. **Weekly email (M4):** sender plan reads feeds + subscribers' `wk-`/`wkt-` tags -> editions -> merged stamp ->
   one filtered email per edition. Brian approves the sample and first send.

## 6. Non-functional
- **Privacy:** AC1.2 to AC1.3 are tested in a browser test (the existing `tests/address_browser.js` pattern) for the
  seven spec addresses plus CT, MA, NY, PA and VA ones: request log has the address only in the Census request; the
  page URL and title never hold it; storage holds only the three keys of 3.8 with the shapes there (no address text);
  after a form send the Buttondown post holds exactly `email` and `tag` fields; after a count tap the GoatCounter
  request holds exactly `p`, `e`, `rnd`. Outbound links use `rel="noopener noreferrer"`. The Method page's section
  "Daylight Digest" lists the three keys, the counter event and what GoatCounter sees (UX section 9).
- **CSP on `digest/index.html`** (delta to ADR 0013 decision 2): `script-src 'self'` (the Census is not in it),
  `frame-src 'self'`, `form-action 'self' https://buttondown.com` ('self' for the Menu drawer's search form, as on
  every page; Buttondown only while the morning note's form is enabled, its origin), `connect-src https://buttondown.com
  https://<code>.goatcounter.com` (the second only while analytics is on). `digest/geo-frame.html` carries the
  frame CSP of 4.0. Static digest pages carry the site's normal CSP (`connect-src 'none'` or GoatCounter only, as
  `count.js` needs). A site check (`digest/csp`) holds each of these per file.
- **Performance:** digest pages under 100 KB with the directory embedded in M1; one Census request per lookup.
- **Politeness and scale:** ADR 0013 decision 6 budget; capacity about 100 bodies a run, 200 a day.
- **Observability:** `health.json` and `proposals.json`; a fixed-title issue when more than 20% of covered bodies are
  stale (devops, M2). Census outages show in the browser only (we can't see them; accepted).
- **Security:** CSP per page (above); verbatim text escaped (Jinja autoescape) and `{{`/`{%` neutralised in anything
  an email template will hold (as the morning sender does); ICS by our own escaping writer (3.6); every outside URL
  through `https_link` plus a host allowlist (3.5); every id that becomes a path or tag matches the id regex first,
  in collector and builder; item text only for `items: shown` governments (section 11). M2 workflow
  (`national-update.yml`, finding 6, `national/writer-token-scope`): the collect job has `contents: read` and no
  token; a separate push job holds `contents: write`, writes only `data/national/**` to `national-data`, and the
  deploy gate pins `--cert-identity` per workflow and branch. Tag consent (finding 2): anyone can post any tag for a
  known email, so `req-` counts are advisory input to Brian's decision, never an entitlement; `wk-` tags need their
  own consent design before M4.

## 7. Clarksville checks (done 2026-11-19, from code and data on this branch)
- County Commission: `data/county-agendas/agendas.json` meetings hold `items[].title` as printed, whitespace joined,
  hyphenated line-end words joined (`collector/county_agenda.py` lines 365-393, 451), with `number`, `printed`,
  `section`, `page`, and `sources[].url`. Usable as is for AC4.2.
- City Council: `facts.json` meetings carry `agenda_url` and `agenda_source_id`, but `item_events` come from minutes
  only (1,759 motions and 2,405 roll calls, 0 events from agenda sources). Upcoming council items are **not** stored.
- Neither stores a meeting time. `time` is null for both in M1 ("Time not listed here").
- Data on this branch was last collected 2026-11-10; the live `records-data` copy is newer.

## 7a. The header, the switch and "Clarksville stays byte-identical"
Facts read from `site/templates/_header.html.j2` and `qa/site_checks.py` (`check_header` line 2242, `check_switch` line
2159): the header is one template, identical on every page except for a `root` prefix; `header/same-on-every-page`
fails any page whose header differs from the most common one, and requires the moon (`sky_place`), the date line and
the `sky-in` "in <place>" text; `switch/on-every-page` requires exactly one "Show records from" switch between the
header and `<main>` on every page, with options from `config/site.yml`.
**Digest header variant (UX D1).** `_header.html.j2` reads one optional variable, `digest_header` (default false; set
only by the national builder's templates). When true: the plate place reads the label `digest.place` ("United States");
the moon frame is omitted; the date line prints the date with no " in <place>" span. When false the template renders
exactly as today (the new code sits inside `{% if %}` tags written so Clarksville output is unchanged byte for byte;
B13's golden test proves it).
**Check changes, scoped by path prefix `digest/` (task B13), never a blanket skip:**
- `header/same-on-every-page`: pages outside `digest/` are checked exactly as now. Pages under `digest/` must each hold
  one header equal to the usual header after three named substitutions (plate place -> `digest.place`; moon frame
  removed; the `sky-in` span removed). A digest page with the Clarksville header, or with any other difference, fails;
  the `want` list for digest pages drops only the moon. The two scripts and the date link rule still apply to all.
- `switch/on-every-page`: pages outside `digest/` keep exactly one switch and the same options (no Digest option is
  added: the switch lists Clarksville bodies, and its all-pages comparison is unchanged). Pages under `digest/` must
  have zero switches. The "coming cards" and hub loop reads only non-digest targets.
- Any other `qa/site_checks.py` check that flags a digest page when the build runs with `national.enabled` is listed by
  B13 with a proposed scoped exemption in the PR; the manager decides, and each exemption names the prefix.
**What "byte-identical" means.** `national.enabled: false`: every output file equals a build of `main` at the same data.
`national.enabled: true`: the diff from the off build is exactly (a) new files under `digest/`, (b) the one front-page
line, (c) the Menu group, which is in the footer list that `nav.js` copies into every page's drawer, so it changes the
footer of every existing page by the same fixed fragment (decision N1), (d) `site/static/` gains `national.js`,
`us-count.js` and `digest.css` (off, the build does not copy them; `digest.css` is the digest pages' own stylesheet,
linked after `style.css` by the pages under `digest/` only and never by the Census frame or an existing page, so
`style.css` is the same file either way; it names no URL, so the pages' `style-src-elem 'self'` covers it), and (e) `static/pages.js` also lists the digest pages (so a report
from a digest page names it). The golden test removes (b) and (c) by their exact strings and requires the rest to be equal.

## 8. Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| FUNCSTAT or class codes behave differently than assumed outside TN | medium | B2 confirms from TIGER docs; hand table; QA addresses in 6 states |
| Census layer names change with a new vintage | low-medium | read by exact name; a browser test with a recorded answer; the page shows the error state, never a guess |
| Buttondown re-submit does not add tags for existing subscribers (R-A) | medium | Q2 tests before M1 live (gates R1). If a re-submit ADDS tags: security finding 2 stays medium (anyone can tag a known email; counts advisory). If it REPLACES tags: high, blocks R1, and the morning-note subscribers' `note-` tags are at risk; then M1 ships the counter only, or requests use a second Buttondown newsletter (a Brian decision, check cost first, hard stop 3) |
| The no-cors form post looks sent but Buttondown refused it (R-B) | medium | Q2 posts from the live page with a team address and checks the email and tag arrive; fallback is the plain native post (4.2) |
| Confirmation cannot redirect to `digest/requested.html` (R-C) | medium | the newsletter-wide confirmation email carries the label; Brian sets it in his dashboard |
| `count-<id>` taps inflated by a script, blocked by ad blockers (R-D) | certain | report labels them "anonymous taps, unverifiable, a lower bound in one way and inflatable in the other"; never added to email counts; Brian's R8 judgment only |
| One newsletter's confirmation email reads wrong for requests | medium | ux-designer rewrites the newsletter-wide confirmation text to fit both |
| Menu group changes the footer of every Clarksville page (N1) | certain | fixed fragment, exact-string golden test; or drop the group in M1 and keep the front-page line only |
| Legistar 403 body shapes unknown | high | first contact for a new body runs alone (probe mode) and is recorded as a fixture |
| Shared `national-data` provenance doubles ADR 0011 surface | medium | security review of D1 and D2 |
| Metadata clobber between morning and weekly senders | high if built separately | one sender package, merged object, shared concurrency (ADR 0013 decision 8) |
| City Council shows no items in M1 | certain | plain label and agenda link; B9 later |
| `national-update.yml` collect job: code execution there (a parser bug on a hostile Legistar answer) could read `ACTIONS_RUNTIME_TOKEN` and save a main-scoped Actions cache that `daily-update.yml`'s update job later restores (security S2b finding 6, `national-ci/collect-runtime-token-cache`) | low | **accepted residual** (S2b): the collect job has no repository token and contents read only; the update job's own PDF parsing carries the same exposure today; `national-update.yml` saves no cache (test 12.3 #10 keeps it so); revisit if a cache step is ever added to either workflow |
| A national step degrades every day and nobody looks (section 12 tier 1 and 2 turn failures into stale pages) | medium | each degrade prints a fixed `::warning::`/`::error::` line; before the switch goes on with a collected entry, the daily run opens one fixed-title issue on `national: degraded` or any degraded government state (task D-ISO-9, with S2b ruling 5's >20% stale issue) |
| A server drips its TLS handshake, headers or chunked framing (chunk-size lines, extensions, trailer), stretching the request in flight past X = 360 s (4.4.4) | low (Legistar is an approved API) | job timeout is the backstop (nothing written, pages go stale); a dripped chunked answer still fails the fetch by the reader's final `A` check; D1 flags a run killed by its timeout so a repeat is seen; then the margin grows or `A` is enforced below http.client (backlog). **Accepted residual** (`max_answer_seconds` is checked above http.client, between reads, not inside one; S2b re-confirmed): it can only fail a national run, never a Clarksville one (section 12 row 23) |

## 9. Assumptions
- AS1. Spec v2's M1 scope is as the manager's brief states (lookup, statuses, Request it, What we cover, Clarksville and
  Montgomery County covered, coming-up pages); national email waits.
- AS2. Brian's capacity decision (manager relay, 2026-11-18 11:32 PM CT) holds; the upgrade itself stays his action.
- AS3. The pages live under `digest/` on the existing Pages site and domain (UX D4). The security review's `/us/`
  names (`/us/geo-frame.html`, `/us/b/*`) map to `digest/geo-frame.html` and `digest/<st>/*`.
- AS4. CMCSS stays "can't cover" in M1 (AC2.4). Note for the PM: Daylight already lists CMCSS board meetings with
  agenda links and line counts from the county's page; a "covered, meetings only" status is possible later.
- AS5. Counter event name `count-<gov id>`, sent only by the no-email tap (not by the email form, which Buttondown
  already counts by tag). Chosen so the two signals are never added together.
- AS6. M1 writes the per-government JSON and the page; ICS and Atom are M4 (UX header, spec v2.1).
- AS7. The state folder is the lowercase USPS code from a `state` field in the directory.

## 10. Decisions and deltas this version needs (owner: manager unless named)
- N1. **Menu group on every existing page.** The design's D3 adds a "Daylight Digest" group to the Menu, which is the
  footer list on every page. With the switch on, every Clarksville page's footer changes by one fixed fragment.
  Recommended: accept (the exact-string golden test keeps it honest). Alternative: no Menu group in M1, front-page
  line only; zero change to other pages. Default if no answer: accept.
- N2. **Device storage holds id and Census name, not ids only.** Design Q3 says ids only, but a government with no
  directory entry (most of them) has no name anywhere else, so the saved list could not be redrawn. The name is the
  public name of the id; no address is kept. Recommended: accept; the Method page says "the names and IDs of the
  governments". Needs the ux-designer's copy check ("only that list of governments is kept" stays true).
- N3. **ADR 0013 deltas (the ADR is not edited here; PM or manager records them).** Decision 2: the lookup frame is the
  static `digest/geo-frame.html` with its own CSP, parent `script-src 'self'` (security finding 1), and the Buttondown
  post adds `connect-src https://buttondown.com`. Decision 5: the counter is in M1 (not "after M1"), the event is
  `count-<id>` from the no-email tap, and it is built as `us-count.js` rather than a `count.js` edit. Decision 9/C2:
  withheld is a directory field, not an `sd*` rule (section 11).
- N4. **Copy note for the ux-designer.** The counter's Done text "Counted, with nothing about you" is stronger than 3.9
  supports (the government's name is sent, and GoatCounter sees the request's IP). Suggested: "Counted. Only the name of
  the government was sent."
- Q-A (needs Brian's Buttondown dashboard, free if the setting exists): can the confirmation redirect point to
  `digest/requested.html`, and can the newsletter-wide confirmation text be edited? Recommended: yes, Q2 checks both;
  default if not possible: the label goes in the confirmation email or the page says nothing more than the design's
  "Check your email" text.
- Security note (finding 11): Q2 also confirms Buttondown's firewall and IP filtering are on (free), and
  `tools/national/request_report.py` ignores `req-` ids not in the directory.

## 11. Invariant: item text is published only for governments we have said so for (`privacy-withhold/national-prefix`)
v3, software-architect, 2026-11-19: loop-limit re-plan after the fourth hit in family `privacy-withhold` (id prefix;
body-name heuristic; cross-layer `also`; reviewed pair with an unbound source, `privacy-withhold/reviewed-pair-unbound-
source` and `privacy-withhold/alias-on-shown`, `docs/reviews/code-review-daylight-national-m1.md`). Where 3.2, 3.5, 3.7,
4.3 or 4.5 differ from this section, this section wins; 11.5 lists the edits they need.

**Invariant.** A person's or child's name reaches published bytes (a page, a JSON file, a feed, an email, the
`national-data` branch) only through item text (`items[].text`, `items[].number`). Item text is read, stored or
published for a government only when (a) its directory entry says `items: shown`, (b) that whole entry, normalized,
has the digest pinned for that government in `SHOWN_REVIEWED` by a reviewed code change, and (c) the text was read
from the source that entry names, under that digest. Everything else is withheld, and `shown` stays refused for every
`sd*` id. Consequence, true by construction: **an edit to `directory.yml`, `gov-flags.yml`, `labels.yml`, `site.yml`,
`council.yml` or `data/` alone can narrow what is published, never widen it.** Why the earlier fixes failed: each
pinned one field (prefix, name, then the (gov, name) pair) while the meaning of `shown` depended on other fields
(`platform`, source keys, `also`, the `daylight.body` mapping). The digest pins every field, including ones added later.

### 11.1 Every input and consumer, config to published bytes
| # | Input or consumer | Decides or carries | Bound by (v3) | Checked at |
|---|---|---|---|---|
| 1 | `directory.yml` `items` | decides | `shown` needs a `SHOWN_REVIEWED` row whose `entry` equals the entry's canonical form; missing = withheld; `withheld` needs no review (narrowing) | load |
| 2 | `gov`, `body_name`, `state`, `status` | whose page | in the digest; `shown_refusal` still runs (no `sd*`, a general layer, ASCII, stem denylist unless `denylist_ok`) | load |
| 3 | `also` | attaches other Census ids' cards to this entry (pagedir `alias`, read by `national.js`) | in the digest (sorted); same layer; unique across `gov` and `also` | load |
| 4 | `platform`, `daylight.{body,full_url}`, `legistar.{client,body_id,tz,final_statuses}`, `host_ok` | which source | in the digest; one covered entry per source key (`daylight:<body>`, `legistar:<client>:<body_id>`) | load |
| 5 | `official_url`, `checked`, `checked_url`, `checked_doc` | links only | in the digest (cost: re-checking a shown entry needs a digest update; accepted, shown entries are few) | load |
| 6 | any key added later | unknown | in the digest automatically (every key is hashed; unknown keys stay refused) | load |
| 7 | `SHOWN_REVIEWED` (`sitegen/national.py`) | decides | a code change reviewed by `code-reviewer`; checklist: read the row's own `entry` text in the diff (every field it vouches for, above all `platform`, `daylight.body` or `legistar.client`/`body_id`, and `also`), whatever earlier PRs did to the YAML, and its source comment (one source per `also` id); one row per `gov` (security `privacy-withhold/review-row-opaque`) | review, test |
| 8 | `gov-flags.yml` hide, show, rules, lines | only whether a Census unit makes a card | never maps a unit to an entry and never names `items`: closed key sets (`_unknown`); pagedir `alias` is built only from directory `also` | load, test |
| 9 | `labels.yml`, `body_name` text | curated words, not item text | reviewed as text in their own PR; outside this invariant | - |
| 10 | `site.yml` `county_key`, `council.yml` `body_key`, `calendar` | map `daylight.body` to stored data | items flow only by the county route: the adapter fixes `COUNTY_BODY_KEY = "county"` in code and raises `FeedError` unless `config.SITE["county_key"]` equals it and no council's `body_key` equals it; council feeds never carry items (`not-read`) | adapter |
| 11 | `data/county-agendas/agendas.json`, council facts and listing | carry text | already published by Clarksville's own pages; national republishes the stored titles byte for byte (B3 test) for the entry bound by 1-4 and 10 | adapter |
| 12 | `sitegen/national_clarksville.py clarksville_feeds` | reads text | reads stored items only when `is_shown(gov)`; stamps `review` (11.2) | adapter |
| 13 | `sitegen/national_guards.py` | the shared gate | `is_shown(entry)` is the one predicate every consumer calls; `bind_feed(feed, entry)` is the last gate before any write; `clean_feed` cleans and never decides | build, collect |
| 14 | `schema/daylight-upcoming.schema.json` | shape | top-level `review` required, null or `^[0-9a-f]{64}$`; `allOf`: `review` null means every meeting has `items_withheld: true`, `items: []`, `item_count: null` (existing `allOf`s stay) | every write |
| 15 | builder B4 `build_national` (`sitegen/national_pages.py`) | writes | `.json` and `.html` only from `bind_feed` output, only for a feed whose `body.id` is a covered directory entry; the page prints items only from that bound object | build |
| 16 | M2 copy step (`national-data` to `digest/`) | carries text, untrusted | `bind_feed` strips items unless the entry is shown now and the file's `review` equals the current digest (covers the runs between a reviewed source change and the next collect); a `body.id` or `platform` mismatch makes the file missing (page stale) | build |
| 17 | embedded page directory, `national.js` | no text; card mapping | `alias` only from row 3; `national.js` maps a unit only through pagedir `alias` | build, test |
| 18 | M2 Legistar collector (`collector/national/`) | reads text | loads only through `load_directory`; items request only when `is_shown` and only to the entry's `client` and `body_id`; drops (counts) any event whose `EventBodyId` is not `body_id`; stamps `review`; `bind_feed` before writing `bodies/<id>.json` | collect |
| 19 | `national-data` cache `data/national/cache/<id>/` | stores text | each file records `review`; a file with another `review` is a miss and is deleted; each run first deletes `cache/<id>/` for every body not shown | collect |
| 20 | `national-data` git history | stores text | a body shown under a review later found wrong keeps its old text in branch history; removal is a history rewrite (hard stop 2, Brian). Accepted residual: the review is the gate | - |
| 21 | M4 ICS; M4 Atom, weekly email, future app, exports | publish | ICS carries no item text (3.6); the others read only the bound published JSON | test |
| 22 | Clarksville morning note | not a consumer | reads Clarksville data and `note-` tags only (AC3.7, B7); must stay so: the sender imports no `sitegen.national*` module | test |
| 23 | run logs, errors, health, proposals | ids, fixed kinds (3.7), instants and counts; a proposal also carries `observed`, which may be a source status name (`STATUS_NAME_RE`: at most 60 characters, `[A-Za-z0-9 ._()/&-]`, per 3.7), and `evidence_url` (an `allowed_url` for the body's client, capped at `MAX_URL`, security S2a finding 6) | no other answer text, never item text (B3 review holds); the fetcher's in-process `log` and exception text do hold a 403 body snippet and headers, so they never reach `national-data`, a commit or a public CI log (4.6) | test |
| 24 | integrity of `national-data` files | forged text with a correct digest (the digest is public, not a MAC) | D1/D2 attestation, not this invariant | deploy |

### 11.2 The fix (owner backend-engineer, opus/high per the data-integrity rule)
- `sitegen/national.py`: `ShownReview(gov: str, entry: dict, denylist_ok: bool = False)`, one row per `gov`, `entry`
  the readable canonical entry (`norm_entry`, so the row's own diff shows every field it vouches for; security
  `privacy-withhold/review-row-opaque`), `digest` a property (`review_digest(entry)`), each row commented with its
  source link, the source for each `also` id, and the review date. `review_digest(e)`:
  `sha256` hex of `json.dumps({"schema": DIRECTORY_SCHEMA, "entry": norm(e)}, sort_keys=True, separators=(",", ":"),
  ensure_ascii=True)`, where `norm` is the raw `safe_load` mapping with every key kept, `also` defaulted to `[]` and
  sorted, `items` defaulted, and every `date` written as ISO text (so YAML key order, `also` order and a quoted date
  do not change it; `norm_entry` of a loaded entry leaves out its `review`). `load_directory` computes the
  canonical entry after every other per-entry check; for `items: shown` it calls `shown_refusal(gov, body_name,
  canonical)`, which adds "the row's `entry` must equal it" to today's checks; the error names the changed keys and
  prints the whole canonical entry as the row to review and paste. The loaded entry gains `review`: the digest when
  shown, else `None`. After the entries: refuse two covered entries with one source key (row 4).
- `sitegen/national_guards.py`: `is_shown(entry) -> bool` (`items == "shown"` and `review` is a 64-hex string);
  `bind_feed(feed, entry) -> (feed, BindCounts)`: raises `BindError` (new, in the guards module, which imports only
  `config`) unless `meetings` is a list of objects and every top-level key is one the schema names, and if `body.id
  != entry["gov"]` or `body.platform != entry["platform"]` (an error repeats an id only when `id_layer` accepts it,
  else `<bad id>`, and any other value only up to 40 characters); rewrites `body` (id, name, tz, official_url,
  platform, full_url) from the entry; keeps items only when `is_shown(entry)` and `feed["review"] == entry["review"]`,
  else empties every meeting (`items: []`, `item_count: null`, `items_withheld: true`) and sets `review: null`; for
  an entry that is not shown also sets each meeting's `title` to the fixed `Meeting` (`title_ours: true`) and nulls
  `time` and `agenda.status_as_posted` (security `privacy-withhold/free-text-outside-items`); counts
  `withheld_stripped` (entry not shown) and `review_mismatch` (shown, other digest). So a published `review` is
  non-null exactly when the file carries items read under that review.
- Adapter: `_shown` becomes `is_shown`; `_feed` writes `review`; `COUNTY_BODY_KEY` check (row 10).
- Checks run at load (rows 1-7, source uniqueness), adapter (10-12), build (`bind_feed` then the schema, 14-17),
  collect (18-19, `bind_feed` again). D2's copy step (`national_copy.copy_feed`) never raises on
  `withheld_stripped > 0` (a collector bug, or a file collected while the entry was shown and read after a PR narrowed
  it to `items: withheld`): it returns `stale_feed(entry)`, sets `CopyCounts.state = "withheld-items"` and prints one
  `::warning::National pages: <id>: withheld-items, withheld_stripped=<n>` (id and count only, never the file's
  text); the build completes and nothing of the file is published (security S2b finding 1,
  `national-isolation/withheld-stop-holds-site`; section 12). Raising would un-publish nothing (`national-data` is
  public, 11.1 row 20) and would hold the narrowing PR's own deploy. It only logs `review_mismatch` (expected for one
  run after a reviewed change).

### 11.3 Tests (each route closed; fixtures: a withheld `place-` "Youth Council", an `sd*` entry, and the sentinel
item text `SENTINEL-ITEM-TEXT` in every source fixture)
1. Shipped: every shown entry's digest equals its row; one row per `gov` (`tests/test_national_directory.py`).
2. Mutation sweep, a one-entry directory per shipped shown entry: change each key in turn to another valid value
   (body_name, official_url, checked, checked_url to checked_doc, `daylight.body`, `daylight.full_url`), add one
   same-layer `also` id, and swap the `daylight` block for a `legistar` block with `host_ok`: each is refused naming
   the digest. The same edits with `items: withheld` load.
3. Digest canonical form: YAML key order, `also` order and quoted vs plain `checked` give one digest.
4. Two covered entries with one `daylight.body`, or one Legistar `client` and `body_id`: refused.
5. Adapter: `county_key` monkeypatched to `city`, or a council `body_key` of `county`: `FeedError`, no feed; feeds
   carry `review` (digest when shown, null when withheld); the schema refuses `review: null` with any item.
6. `bind_feed`: withheld entry with items, stripped and counted; shown entry with a stale `review`, stripped and
   counted; `body.id` or `platform` mismatch, `BindError`; shown and matching, unchanged.
7. Builder sweep (B4): build every output from the fixtures, including a copied M2 file with a stale `review`;
   `SENTINEL-ITEM-TEXT` appears only in the bound shown government's `.json` and `.html` (never the pagedir,
   `index`, `covered`, `requested` or another government's files); the page's items equal its JSON's. M4 extends
   the sweep to `.ics`, `.xml` and the weekly email.
8. Pagedir `alias` equals the union of loaded `also` sets; a gov-flags entry with an `alias` or `items` key is
   refused.
9. Collector (C2, C3): a withheld entry makes no items request (recorded fetcher) and leaves no cache files; a stale
   `cache/<id>/` for a now-withheld body is deleted; items are requested only for the entry's `client`/`body_id`; an
   event with another `EventBodyId` is dropped; a cache file with another `review` is a miss.
10. Single reader: no module but `sitegen/national.py` opens `directory.yml` (a source scan of `sitegen/`,
    `collector/`, `scripts/`); the morning-note sender imports no `sitegen.national*` module.

### 11.4 Alternatives considered
Explicit pins in `ShownReview` (platform, source keys, `also` set): readable, but every new key must be remembered,
which is how this family reopened. Treating a mismatch as withheld instead of refusing: safe, but silent; refusing
fails the PR's own checks before merge, as every other 3.2 rule does. Signing the file: needs a key in CI (hard stop
5) for no gain over code review.

### 11.5 Edits other sections need (manager or the engineer, in the fix PR)
3.2: the pair rule becomes the digest rule plus source-key uniqueness. 3.5 and 3.7: top-level `review` (11.2); 3.7
cache files carry `review`. 4.3: `build_national` writes only `bind_feed` output. 4.5: the `EventBodyId` check and
cache rule. Tasks B1, B3, B14, B4, C2, C3 and D2 gain the matching tests of 11.3.

## 12. Invariant: national data never holds a Clarksville build or deploy (`national-isolation`)
v1, software-architect, 2026-11-20: loop-limit re-plan after three hits in family `national-isolation` in one review
(security S2b findings 1-3, `docs/reviews/security-review-daylight-national-s2b.md`), from ADR 0013 decision 6 ("a
national failure never holds a Clarksville build or deploy"). Where 3.7, 4.3, 4.6 or 11.2 differ from this section,
this section wins. Line numbers are at 85bd69a4.

**National inputs** are: (1) any bytes under `national-data`, or in the folder `RECORDS_NATIONAL_DATA` names, or their
absence (missing, partial, oversized, malformed, hostile, stale, or collected while an entry was shown and read after
a PR narrowed it); (2) the Clarksville data files *as the national step reads them* (`data/county-agendas/agendas.json`,
council facts and listings, through the adapter); (3) any outcome of a national step in `daily-update.yml` (failure,
timeout, cancellation, a missing output); (4) anything at all that `national-update.yml` does or fails to do.

**Invariant.** For every combination of national inputs and every reviewed national config state on `main`:
- (a) **Off** (`national.enabled: false`): the Clarksville build completes and is byte-identical to a build with no
  national input at all (7a), whatever `RECORDS_NATIONAL_DATA` names.
- (b) **On**: the build completes and writes every Clarksville page. A bad national input changes only national
  output, and only by degrading: that government's page and JSON are built from `stale_feed(entry)` (no meetings,
  "no records yet", pagedir `stale`), with one `::warning::` naming the government id, a fixed state word and counts
  or an exception's type name, never the input's text. Every file outside `digest/` is byte-identical to the same
  build with no national root. Nothing raises out of the national step because of a national input.
- (c) **Deploy**: every `daily-update.yml` job and step the Clarksville deploy depends on (gate, update, push,
  deploy, note) ends with the result it would have with no national input. A national step may fail, time out or be
  skipped without changing any of them.

**Allowed raises (the only ones).** The build may stop on the national side only for a problem that is a function of
reviewed repository files alone (`config/national/*.yml`, `config/site.yml` `national`, `schema/`, `site/templates/`,
code) and is decided in the **load phase**, before any national input is read: the loaders' `NationalConfigError`
(`load_all`, `load_page_labels`, `load_links`), `enabled()`'s switch typo (`national_pages.py:127-128`), the
adapter's route checks (`national_clarksville.py:190-194`, `:207`), `_platform_keys` (`national_copy.py:75`, `:79`,
`:81`), a missing page label for a covered entry's state, slot or zone, `gov_page` (`national.py:636`), and the
fragment anchors of `apply_site_fragments` (`national_pages.py:253`, `:262`, `:269`, `:275`). This does not break the
invariant because such a state never reaches `main`: test 12.3 #1 builds the shipped config with the switch on in
every PR, and the daily build runs the same code on the same files, so a raise there fails the PR's own checks
first, as every other 3.2 rule does. It holds only under two conditions, which are part of the invariant: (i) the
check is decidable from repository files at load, never first triggered by data (today `_tz_label` is not: row 13);
(ii) any clock dependence is monotone toward valid (`host_ok.date` no later than today: once true, it stays true).

**How it is held by construction, not by finding each raise.** `national_pages.run` gets three phases:
- **Load phase** (allowed raises only): every load and every config cross-check, including the new ones of rows 9,
  13 and 14. Its `NationalBuildError` is the only national exception `build.py` turns into `BuildError`.
- **Tier 1, per government**: everything that reads a national input for one covered entry (`copy_feed`, or the
  Clarksville adapter for that entry; bind; schema; the date and instant checks; `meeting_view`; rendering its page
  and JSON text) runs inside one `try/except Exception`. Any exception: that entry's page and JSON come from
  `stale_feed(entry)` instead, `CopyCounts.state` is a fixed word (`withheld-items`, `bad-date`, `bad-instant`,
  `adapter-error`, `render-error`), and one line `::warning::National pages: <id>: <state> (<type name>)` is
  printed. Rendering `stale_feed` depends only on config (test 12.3 #1).
- **Tier 2, the whole data phase**: anything else that raises after the load phase (`council_inputs`/`load_listing`,
  `page_directory`, the index, What we cover, the writes) clears `out/digest/`, re-runs the data phase with no
  national root and no Clarksville inputs (every covered entry `stale_feed`), prints
  `::error::National pages: built with no data (<type name>)`, and the build result and `build/run-log.json` say
  `national: degraded` (else `built`, or `off`). Its inputs are reviewed files only, so a raise in that re-run is an
  allowed raise and stops the build (test 12.3 #6). "Fall back to the off build" is not used: `digest/csp`
  (`qa/site_checks.py:2648-2659`) fails a switch-on build with no digest pages, and the Menu group on every page
  would link missing files; an all-stale digest keeps both true.

### 12.1 Every input and consumer, national input to the Clarksville deploy
| # | Consumer or route | Current behaviour at 85bd69a4 | Holds? | Fix (task) |
|---|---|---|---|---|
| 1 | `daily-update.yml` gate job budget | `timeout-minutes: 10` (:102) covers checkout, the history check (:120, no step timeout) and the D2 lookup (:267-271, `continue-on-error`, step timeout 3). A job timeout fails the job whatever `continue-on-error` says, so a slow lookup on a slow history day fails the gate and skips update, push and deploy, **even with the switch off** | **breaks** (S2b finding 3) | every gate step gets `timeout-minutes`; job timeout >= the sum of step timeouts + 1 (e.g. checkout 1, history 8, lookup 3, job 13); test (D-ISO-1) |
| 2 | gate lookup step outputs | `set -uo pipefail` (no `-e`); `found`/`none` (:277-278) write `sha` once and exit 0; a timeout or failure leaves `national_sha` empty, so update skips N | holds | - |
| 3 | update job: check out N (:394-403) | `continue-on-error`, step timeout 3; a failure gives `CHECKOUT != success`, no root | holds | - |
| 4 | update job: "Put N's data/national beside the build" (:405-426) | `continue-on-error` but **no `timeout-minutes`**: a hang (`mv`, or the `rm -rf` trap on a large tree) runs to the update job's 355-minute timeout and fails the update job, **switch off or on** | **breaks** (new, N1) | `timeout-minutes: 2`; test: every `continue-on-error` step in `daily-update.yml` has a step timeout (D-ISO-2) |
| 5 | Collect step (:506-512) and Rebuild step (:633-638) | both build with `RECORDS_NATIONAL_DATA`. `collector/__main__.py:508` calls `site_build` with no handler, so a national raise ends the county run non-zero before `run-log.json` is written: the step and the update job fail, and **the day's records-data push is lost too**, not only the deploy | holds only as far as rows 7-19 hold | none here; rows 7-19 remove the raises |
| 6 | Site checks step (:643-647) on `build/site` | runs every check on digest pages too. `dates/no-raw-utc-day` (`qa/site_checks.py:2876-2882` `FETCH_DAY`, `check_local_dates` :3058-3090) fails any page whose text holds "Fetched/Collected/Added/Downloaded/Retrieved (on) YYYY-MM-DD" or "Data as of YYYY-MM-DD" that is not a manifest fetch day. A Legistar title or item text such as "Item added 2026-01-05" on `digest/<st>/<id>.html` fails the step, the update job and the deploy. Other checks: `sources` (:1395-1412, URLs from `digest_link_urls` :2592-2632) holds by construction (page links are the JSON's, through the same `allowed_url`); `links` skips http(s); `digest/csp`, `header`, `switch`, `footer` and `unofficial` read structure; `private_details` reads `data-transcript` only; `notcollected` and `freshness` read classed blocks | **breaks** (new, N2, `national-isolation/site-checks-read-feed-text`) | `dates/no-raw-utc-day` skips the feed text of `digest/<st>/` pages (a scoped exemption naming `DIGEST`; those pages print no fetch day); test 12.3 #9 runs every site check over a hostile-text build (B-ISO-6) |
| 7 | `sitegen/build.py:1049-1057` | `NationalBuildError` becomes `BuildError`; any other exception (the `ValueError` of row 11, a `TypeError`, a `UnicodeError`) passes up uncaught | **breaks** for every data raise | only load-phase `NationalBuildError` becomes `BuildError`; tiers 1 and 2 (B-ISO-3) |
| 8 | `national_pages.run` (:637-664) | the `try` (:642-651) wraps loads and `build_feeds` together and turns every `ValueError`, data or config, into `NationalBuildError`; `build_national` (:658) and the log lines run outside it | **breaks** (the mechanism of findings 1 and 2) | split into load phase, tier 1 and tier 2 (B-ISO-3) |
| 9 | `national_copy.copy_feed` (:122-147), every raise path | `_platform_keys` :75, :79, :81 (allowed: a reviewed entry; moves to the load phase); `read_body_file` :93-108 `except Exception` -> missing (holds); `clean_feed`/`bind_feed`/`feed_errors` :131-139 `except Exception` -> missing (holds; `checked_id` is inside the `try`); **`withheld_stripped` :141-143 raises `CopyError`** | **breaks** (S2b finding 1) | 11.2 as amended: `stale_feed`, state `withheld-items`, warning with id and count, never raises (B-ISO-1) |
| 10 | `build_feeds` (:368-403) | `CopyError` -> `NationalBuildError` (:386-387); "covered, but no feed" (:401) is a code assert | breaks via row 9 | per-entry tier 1 (B-ISO-3) |
| 11 | meeting dates | schema `date` `^\d{4}-\d{2}-\d{2}$` (`schema/daylight-upcoming.schema.json:45`): `\d` takes any Unicode digit and there is no calendar check, so `2026-02-30` or Arabic-Indic digits pass `copy_feed`; then `long_day` (`national_pages.py:439-442`, `date.fromisoformat`, called from `meeting_view` :490) raises `ValueError` inside `build_national`, outside `run()`'s `try`, and row 7 lets it out. `day_words` (`localdates.words`) catches `ValueError` (holds) | **breaks** (S2b finding 2) | in `copy_feed` after `feed_errors`: every `meetings[].date` fullmatches `[0-9]{4}-[0-9]{2}-[0-9]{2}` and `date.fromisoformat` accepts it, else `stale_feed`, state `bad-date`; schema `\d` -> `[0-9]` in `date` and `instant`; also `HOST_OK_DATE_RE` (`national_guards.py:114`) (B-ISO-2) |
| 12 | instants `checked_at`, `last_ok_at` | schema `instant` (:37) has the same `\d`; read by `newest_day` (:431-436) and `page_directory` (`national.py:654`) through `_parse_instant` (`national.py:620-628`, `ValueError` -> None): the page says no records, the pagedir says stale. `0001-...Z` stops at `<= EPOCH` before `astimezone`; `9999-12-31T23:59:59Z` converts only because `site_timezone` is west of UTC; a future `last_ok_at` would never go stale | holds today (degrades), fragile | in `copy_feed`: both (when not null) parse with `_parse_instant` and lie in `[EPOCH, built_at + 1 day]`, else `stale_feed`, state `bad-instant` (B-ISO-2) |
| 13 | meeting `time` and `_tz_label` (:458-461, called at :491 only when `time` is not null) | a covered Legistar entry whose zone has no `tz.<zone>` page label passes every PR test without a timed-meeting fixture, then raises `NationalBuildError` on the first collected meeting with a time | **breaks** (new, N3: a config defect first triggered by data) | load phase: every covered entry's zone (`<platform>.tz`, else `site_timezone`) has a `tz.` label (an allowed raise); the render-time raise stays as a code assert inside tier 1 (B-ISO-4) |
| 14 | Clarksville adapter on Clarksville data (`national_clarksville.py:176-222`; `build_feeds` :389-402; `council_inputs` :356-365 `load_listing`) | route checks :190-194 and :207 are allowed raises. Data-driven: `BindError` (:212-213) and schema errors (:215-216) become `FeedError` -> `NationalBuildError` -> `BuildError`; a malformed `agendas.json` meeting (an unhashable `source_id` is a `TypeError` at :151) or a listing file that is not JSON raises too. These files also build Clarksville's own pages, which tolerate shapes the national schema refuses, so one odd record holds the whole site once the switch is on | **breaks** (new, N4, latent) | the adapter call per entry runs in tier 1 (state `adapter-error`); `council_inputs` in tier 2; the route checks move to the load phase (B-ISO-5) |
| 15 | `build_national` (:527-634) | `BindError` (:551-554) cannot fire on feeds already bound by `copy_feed` or the adapter, and `feed_json`'s schema raise (:406-411) cannot fire on feeds already checked (code asserts). `_state_label` (:451-455), `labels["slot..."]` and `gov_page` are reviewed config (load phase). Item text reaches `item_topics` at 2,000 characters at most. `label_html` fills fields in one pass (a `{x}` in data is never read as a field). Writes (:629-633): text fields carry no lone surrogate after `clean_text` (`BAD_TEXT_RE` :49-50), URLs pass `allowed_url`, ids are ASCII; `date` is the one uncleaned free string, closed by row 11 | holds after rows 11 and 13; tier 1 is the backstop for anything missed | B-ISO-3 |
| 16 | `stale_feed` (`national_copy.py:111-119`) | built from the entry only; must pass the schema and render | holds (test 12.3 #1 renders every covered entry stale) | - |
| 17 | `apply_to_tree` (:293-306) on every `.html`, digest pages included | the anchors come from Clarksville templates (reviewed; B5 golden test); data on a digest page is autoescaped, so it can never hold `</ul>`, `</footer>` or the address-card tag | holds | the hostile-text sweep includes the anchors (12.3 #4) |
| 18 | ICS and Atom (`sitegen/national_feeds.py`, M4, not called yet) | bad ids and dates are left out (:107, :122, :153 catch `TypeError`/`ValueError`); the state-code raise (:214) is config | holds | M4 rule: the writers run inside tier 1 per government; an exception omits that government's `.ics`/`.xml` and every link to them |
| 19 | `page_directory` (`national.py:640-669`) | the two `ValueError`s (:646, :648) are code asserts; `last_ok_at` parsing as row 12 | holds | inside tier 2 |
| 20 | switch off | `build.py:1051-1052`: `run` is not called, so `national_copy` never reads the root | holds, untested for a bad root | test 12.3 #8 (S2b nit b; B-ISO-7) |
| 21 | update job, later steps: Tests (:662), I-pub tripwire (:671), data age (:775), uploads, push job, deploy (:1301-1320), note job | read `data/` and the Clarksville part of `build/site`; national data lives in `$RUNNER_TEMP/national`, never in `data/` (:415-424); deploy's `if:` tests each needed job by name | holds | keep: no daily job may `needs` a national-only job (test 12.3 #10) |
| 22 | `national-update.yml` coupling to `daily-update.yml` | triggers schedule and `workflow_dispatch` only (:37-48); concurrency `national-collect` (:49-50), not `daily-update`; no `workflow_run`, no cross-workflow `needs`; pushes only `national-data` with `GITHUB_TOKEN` (which starts no workflow). Shared surfaces: `national-data` (read softly, rows 2-4), the Actions cache scope (S2b finding 6, accepted residual, section 8; it saves no cache), the API rate limit (at most 10 attestation lookups a daily run) | holds | test 12.3 #10 keeps it so |
| 23 | `national-update.yml` failures | any job failing or timing out (including the dripped-answer residual of section 8) changes nothing on `national-data`; its gate refuses forever after an unattested head (S2b nit e): national stops, Clarksville is not touched; recovery is a branch reset (hard stop 2, Brian) | holds | runbook note (D-ISO-7) |
| 24 | report issue text (`national-update.yml:403-408`) | says "The Clarksville site is not affected", untrue until rows 1, 4 and 6-14 land | **wrong today** (S2b nit d) | until then drop that sentence; the PR that lands 12.3 restores it (D-ISO-6) |
| 25 | run log and annotations | counts and fixed words only (11.1 row 23) | holds | every new line matches 12.3 #13 |

**Summary.** Holds: rows 2, 3, 15-23 and 25. Break today: 1 (finding 3), 4 (N1), 6 (N2), 7, 8, 9 (finding 1), 10,
11 (finding 2), 13 (N3), 14 (N4) and 24 (nit d); row 12 is fragile. Rows 1 and 4 hold the Clarksville deploy **with
the switch off** and land now. The rest are switch-on paths and gate `national.enabled: true` with any collected
entry, as S2b gates findings 1 and 2.

### 12.2 Fixes and owners
**backend-engineer** (opus/high under the data-integrity rule; one PR; B-ISO-3 first, the others may follow in any
order):
- B-ISO-1 S2b finding 1 (row 9): 11.2 as amended; `_platform_keys` checked for every covered collected entry in the
  load phase; rewrite point 4 of the `national_copy.py` docstring.
- B-ISO-2 S2b finding 2 (rows 11, 12): ASCII date and instant checks in `copy_feed`; schema `[0-9]`.
- B-ISO-3 the boundary (rows 7, 8, 10, 15, 19): load phase, tier 1, tier 2; `build.py` turns only load-phase
  `NationalBuildError` into `BuildError`; the build result and `run-log.json` carry `national` and each degraded
  government's state (for D-ISO-9).
- B-ISO-4 N3 (row 13): zone labels checked at load.
- B-ISO-5 N4 (row 14): the adapter per entry in tier 1; route checks in the load phase.
- B-ISO-6 N2 (row 6): the scoped `dates/no-raw-utc-day` exemption for `digest/<st>/` feed text.
- B-ISO-7 S2b nit b, plus tests 12.3 #1-9 and #13.

*As built (backend-engineer, 2026-11-20), where it differs from the text above:* (1) the copy step runs the date and
instant checks after `bind_feed` and before the schema (not after `feed_errors`), so a non-ASCII digit the schema
also refuses is reported as `bad-date`/`bad-instant` (12.3 #3), not "missing"; `withheld-items` is checked first.
(2) An exception escaping the copy step itself is `adapter-error` (no separate word); the tier-2 rebuild marks no
government (`national: degraded` says every page is stale). (3) `council_inputs` stays in tier 2, but an unreadable
listing file degrades only its council (`adapter-error`, 12.3 #7). (4) In 12.3 #7, a county meeting with no id and an
item with a null title do not degrade the county: the B14 guards drop the meeting (counted) and print an empty item
text, so the page builds; a list `source_id` and a non-JSON or non-UTF-8 listing give `adapter-error`.

**devops-engineer** (sonnet/medium; a CI workflow diff goes to a fresh security review):
- D-ISO-1 S2b finding 3 (row 1): gate step timeouts and job budget; test 12.3 #10. Chosen over moving the lookup to
  its own job: a job-level `success()` reads every ancestor, so a failed lookup job would skip `push` (whose `if:`
  calls no status function), and every downstream `if:` would need rewriting by name.
- D-ISO-2 N1 (row 4): `timeout-minutes: 2` on "Put N's data/national"; every `continue-on-error` step has a timeout.
- D-ISO-3 S2b finding 4 (`national-budget/dispatch-no-daily-cap`): the collect `if:` adds `&& (github.event_name ==
  'schedule' || (github.actor == 'gn0sh' && github.triggering_actor == 'gn0sh'))`; the shell budget regex allows 1
  to 360 only; tests.
- D-ISO-4 S2b finding 5 (optional, shared with records-data I-prov): `--format json`, require
  `sourceRepositoryDigest` in `git rev-list --first-parent HEAD`, in both lookups.
- D-ISO-5 S2b nit a: `env -u GITHUB_STATE` on the collect CLI step.
- D-ISO-6 S2b nit d (row 24).
- D-ISO-7 S2b nit e (row 23): a note in `docs/ops/u3-positive-control.md` (the U3-0 runbook) that an unattested
  `national-data` head stops the national gate until a reset, and that the reset is Brian's (hard stop 2); the
  `national-data` ruleset must block force-push and deletion (Brian's PC step, batched with the U3-0 ruleset ask).
- D-ISO-8 tests 12.3 #10 (coupling) and #11 (dispatch).
- D-ISO-9 (before the switch goes on with a collected entry, with S2b ruling 5's >20% stale issue): one fixed-title
  daily issue when `run-log.json` says `national: degraded` or any government is in a degraded state.

### 12.3 Tests (each route closed)
1. **Shipped config, switch on, every PR**: `config/site.yml` patched on, fixture data, no national root: the build
   completes, `national == "built"`, every covered entry has its page and JSON; the same with every covered entry
   forced to `stale_feed` completes too. A Legistar fixture entry whose zone has no `tz.` label is refused at load.
2. **Finding 1**: a file collected while the entry was shown, read after it is narrowed to `items: withheld`: the
   build completes; that page is stale; state `withheld-items`; the warning holds the id and count and no file text;
   `SENTINEL-ITEM-TEXT` appears in no output file.
3. **Finding 2**: `2026-02-30`, Arabic-Indic and fullwidth digits, and `2026-1-05` as a meeting date -> stale,
   `bad-date`; the same for `checked_at`/`last_ok_at`, plus an instant before the epoch and one a day after the build
   -> `bad-instant`; the schema refuses non-ASCII digits.
4. **Hostile national-data sweep**, one bad file per case (not JSON, 8 MiB + 1, depth 33, symlink, FIFO, wrong
   `body.id`, wrong platform, an extra key, `meetings` or `items` not a list, `\ud800` escapes in every string field,
   `{name}` and `[x]` in text, the `MENU_ANCHOR` and `</footer>` text, huge integers in `seq` and `page`, `null`
   everywhere): each build completes; only that entry's page and JSON change; every file outside `digest/` is
   byte-identical to the build with no national root.
5. **Tier 1 backstop**: `meeting_view` monkeypatched to raise `TypeError` for one entry: that entry is stale with
   `render-error`, the others are built normally, the build completes.
6. **Tier 2**: `page_directory` monkeypatched to raise once: `digest/` is built all stale, `national == "degraded"`,
   one `::error::` line; raising on the re-run too: `BuildError` (tier 2 never hides a config or code fault).
7. **Adapter (N4)**: an `agendas.json` meeting with a list `source_id`, an item with a null title, a meeting with no
   id, and a council listing file that is not JSON: the Montgomery County or City Council entry is stale with
   `adapter-error`; files outside `digest/` are as in #4.
8. **Switch off (nit b)**: `RECORDS_NATIONAL_DATA` naming a withheld-items file, a bad-date file, a missing path and
   a symlink: the build output is byte-identical to the build with it unset, and nothing is under `digest/`.
9. **Site checks (N2)**: the #4 build with feed text "Item added 2026-01-05", "Fetched 2026-01-05", "Data as of
   2026-01-05", "meeting collected 2026-01-05", the not-collected tag word and "Coming" passes
   `python -m qa.site_checks`; the same raw day on a page outside `digest/` still fails.
10. **Workflows (devops)**: in `daily-update.yml` every gate step has `timeout-minutes` and the job's is >= their sum
    + 1; every `continue-on-error` step in any job has `timeout-minutes`; no job `needs` a national-only job; the
    lookup keeps `continue-on-error` and `if: success()` (existing test `test_national_workflow.py:498`).
    `national-update.yml` has no `actions/cache` step, no `workflow_run` trigger, no concurrency group shared with
    `daily-update.yml`, and writes only `national-data`.
11. **Dispatch cap (finding 4)**: the collect job's `if:` holds the schedule-or-gn0sh clause; the budget regex refuses
    0 and 361.
12. **Issue text (nit d)**: the report job's body is the fixed text, without the "not affected" sentence until #1-9
    pass on `main`.
13. **Annotation hygiene**: every line sitegen's national step prints (tests capture stdout and stderr) holds only
    ids that `id_layer` accepts, fixed state words, exception type names and `name=<integer>` counts; a test feeds
    the sentinel text through every degrade path and finds it in no printed line.

### 12.4 Alternatives considered
- **Keep raising and fix each raise path** (the current shape): every review has found another (S2a, S2b, and rows
  4, 6, 13 and 14 here); without a boundary the next unknown `ValueError` reopens the family. Rejected.
- **Wrap the whole national step and fall back to the off build**: the simplest code, but `digest/csp` fails a
  switch-on build with no digest pages and the Menu links break on every page, so the deploy is held anyway.
  Rejected for tier 2's all-stale rebuild.
- **Treat every national exception as a degrade, config errors included**: a broken reviewed config would then ship
  silently as a stale digest. Rejected: reviewed-config faults raise in the load phase, where PR tests catch them.
- **Move the D2 lookup to its own job** (finding 3's second option): see D-ISO-1. Allowed later if every downstream
  job's `if:` is rewritten with `!cancelled()` and named results, with a test.
- **Do nothing until the switch goes on**: rows 1 and 4 already hold the Clarksville deploy with the switch off, so
  they cannot wait; the rest can, and are gated on the switch.

### 12.5 Edits other sections need (the engineer, in the fix PR)
4.3 and 4.6 "D2 copy step": the copy step never raises on data; the three phases. 3.5: `date` and `instant` are ASCII
`[0-9]`. Tasks D2 and B13 gain 12.3 #8 and #9. ADR 0013 decision 6 gains a delta line pointing here (manager, as N3
of section 10 does for the other deltas).
