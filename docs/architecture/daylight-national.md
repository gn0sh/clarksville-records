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
| Labels | `config/national/labels.yml` | Every fixed string on digest pages (AC4.5, AC4.8), in "government" words | M1 |
| Coverage share | `config/national/share.yml` (optional) | `{pct, k, date}` for the What we cover sentence; absent = sentence omitted | M1.5 |
| National builder | `sitegen/national.py` (+ templates) | Writes `digest/` pages and per-government JSON from directory + data; the header variant, Menu group and front-page line | M1 |
| Geo frame | `digest/geo-frame.html` (static, built; own meta CSP) | The only page that may load the Census JSONP; sandboxed (`allow-scripts`, no `allow-same-origin`); gets the address by `postMessage`, answers by `postMessage` | M1 |
| Lookup script | `site/static/national.js` (+ the `address.js` message checks) | Drives the frame, classify, render list, picker, in-card request form, device list | M1 |
| Counter script | `site/static/us-count.js` (digest pages only) | The anonymous "Just count me" event; exposes `window.DaylightCount` | M1 |
| Header variant | `site/templates/_header.html.j2` (one switch) + `qa/site_checks.py` (two checks) | The digest plate and date line; scoped checks (7a) | M1 |
| Request report | `scripts/request_report.py` | Counts `req-<id>` tags from Buttondown's API; runs on Brian's PC with his key, never in Actions | M1 |
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
The slot label (CITY OR TOWN, COUNTY, TOWNSHIP OR TOWN, SCHOOL DISTRICT) comes from the id's layer, not the file. A
government not in this file is "Not covered yet" (AC2.8); it has no entry and no page.
Build checks (refuse to build): unknown key; bad id; duplicate id across `gov` and `also`; missing or unknown `state`;
`cant-cover` without `reason`, `reason_url`, `checked`; `covered` without `platform` keys; any URL not https; a
`reason` with no label in `labels.yml`. Added by security review (findings 5, 7), all by `yaml.safe_load` and strict
regex, each with a test:
- `items: shown` on any `sd*` id, or on any entry whose `body_name` the build cannot tie to a general-purpose
  government (see section 11), is refused; a missing `items` means `withheld`.
- a non-`daylight` platform without `host_ok: {date, link}` is refused (build and collector both).
- `daylight.full_url` and the pagedir `page` match `^[a-z0-9][a-z0-9/_.-]*$` (no scheme, no `..`, no leading slash);
  `legistar.client` matches `^[a-z0-9-]{2,40}$`; `tz` is a name in `zoneinfo.available_timezones()`;
  `final_statuses` is an exact list of strings from a fixed set; `state` is one of the USPS codes.
- every URL host on a non-daylight entry is on that platform's host allowlist (`config.https_link`, finding 4).

### 3.3 `config/national/gov-flags.yml`
```yaml
schema: daylight-govflags/1
hide: [{id: county-09110, why: "CT planning region, no county government", source: <url>}]   # by id
show: [{id: place-4752006, why: "Nashville-Davidson metro government (balance)", source: <url>}]
rules: [{state: "09", layer: county, show: false, why: ..., source: <url>},
        {state: "44", layer: county, show: false, why: ..., source: <url>}]
lines: [{id: place-4752006, line: consolidated, why: ..., source: <url>},    # "The city and county here are one government."
        {id: place-5181000, line: independent-city, why: ..., source: <url>}] # "This city is not part of any county."
```
Ids in this file are examples to be confirmed in task B2; none is verified yet. `line` must be a key in `labels.yml`.
The other fixed lines (no city or town, no county government listed) are computed, not flagged (4.1).

### 3.4 Embedded page directory (built from 3.2 and 3.3; the browser's only data)
```json
{"schema": "daylight-pagedir/1", "built": "2026-11-19", "root": "../",
 "govs": {"place-4715160": {"board": "Clarksville City Council", "status": "covered", "page": "tn/place-4715160.html",
                            "full": "city/", "stale": false},
          "sdu-4703030": {"board": "Clarksville-Montgomery County School System Board of Education",
                          "status": "cant-cover", "reason": "blocks-readers", "checked": "2026-11-07",
                          "reason_url": "https://www.cmcss.net/", "official_url": "https://www.cmcss.net/"}},
 "alias": {"place-4752006": "county-47037"},
 "hide": ["county-09110"], "show": ["place-4752006"], "rules": [{"state": "09", "layer": "county", "show": false}],
 "lines": {"place-4752006": "consolidated"},
 "labels": {"reason.blocks-readers": "Its records site blocks automated readers.", "...": "..."}}
```
`stale` is computed at build time from the government's JSON `last_ok_at` (more than 3 days before the build).
`page` and `full` are relative to `root` (the page's own `data-root`), never absolute. The card's title is the Census
name from the lookup; `board` is the directory's board name on the next line (UX P4). A government with no `govs`
entry has no `board` line, status "not-covered-yet", and the "no official link" copy (the Census answer has none).
If the embedded directory passes about 60 KB, it moves to same-origin `digest/pagedir.json` fetched on first lookup
(`connect-src 'self'`); the shape is unchanged.

### 3.5 Per-government data `digest/<st>/<body id>.json` (schema `daylight-upcoming/1`)
The contract the coming-up page, the M4 ICS and Atom, the future app and the weekly email read. Written by the national
builder (M1, Clarksville) or copied from `national-data` (M2+). The M1 builder writes this JSON and the page only; the
ICS and Atom writers are M4 (spec v2.1).
```json
{"schema": "daylight-upcoming/1",
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
Field rules: `meetings` from today (body's time zone) on, soonest first. `agenda.state`: `final` (items may be
shown), `not-final` (Legistar status not final: no items), `not-read` (posted, items not read by us: Clarksville City
Council in M1), `not-posted`. `items` is empty unless `state == final` and `items_withheld == false`.
`items_withheld` is true unless the government's directory entry says `items: shown` (default withheld; never allowed
for `sd*` ids; invariant in section 11), and `item_count` is then null (Clarksville feeds may carry a count they
already store; M2 withheld bodies do not). `text` is the source's words,
whitespace joined, nothing else changed, capped at 2,000 characters per item (longer is cut at the cap and marked
`"cut": true`, the page then links the official agenda for the rest), at most 150 items per meeting and 60 meetings per
government, bidi-override and other control characters stripped and counted in the run log (finding 12). Every URL in
the file (`official_url`, `meeting_url`, `agenda.url`, `items[].source.url`) must pass `config.https_link` and, off
Daylight, the platform's host allowlist, at collection and again at build; a bad URL is dropped (field null) and the
page falls back to the directory's `official_url` (finding 4). `time` is the posted time string or null. `title_ours` marks
a title built from fixed labels (Clarksville meetings have a kind, not a posted title). No vote, outcome, tally,
attendance, motion or person's name field exists in this schema (AC4.4); a test fails on any extra key.

### 3.6 ICS and Atom (M4; contract fixed now so M1 ids and URLs hold)
- `digest/<st>/<body id>.ics`: one VEVENT per meeting. `UID: <body id>/<meeting id>@daylight.gnoshcodes.com`; `DTSTART;VALUE=DATE`
  when `time` is null, else `DTSTART;TZID=<tz>` from the parsed time (unparseable: all-day, time in the summary as
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
host-stopped | rate-limited | robots | budget-skipped | server-error | not-enabled-suspected | token-suspected"}}`),
`data/national/proposals.json` (`[{"body", "kind": "status" | "agenda-status-name", "observed", "evidence_url",
"first_seen", "count"}]`). Cache: `data/national/cache/<body id>/<event id>.json` (items keyed by
`EventAgendaLastPublishedUTC`).

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
  official_url?}], notes: [<label key>]}`; `notes` holds the fixed lines the list needs: `no-city` (no place kept:
  unincorporated), `no-county` (a county was hidden by a `rules` or `hide` entry), and each `lines` flag of a kept
  government (`consolidated`, `independent-city`). `govs` empty -> the "nothing listable" state. Apply in order
  (1) drop units by FUNCSTAT (place, county, cousub: keep A; school districts: keep A or E; codes confirmed in B2),
  (2) gov-flags `hide`, `show`, `rules`, (3) drop school district "not defined" units (GEOID ending 99999; B2
  confirms), (4) map through `alias`, then dedupe by id, (5) drop a county subdivision whose name equals the kept
  place's name in the same county (coextensive town or city; B2 confirms the class codes that prove it),
  (6) status from `govs`, else `not-covered-yet`, (7) order: place, county, cousub, sdu, sds, sde.
  Pure; unit-tested with recorded answers.
- Device list (3.8): `loadList(storage) -> [{id, name}]` (validates, drops bad), `saveList(storage, govs)`,
  `forget(storage)` (removes the three keys), `markRequested(storage, ids)`, `markCounted(storage, id)`. All take the
  storage object as an argument so node tests use a fake; every call is wrapped so a blocked or full storage never
  breaks the page (the list is then simply not saved).
- Rendering order and focus follow the UX states table: one focus move after each result. The Census matched line is
  page text only. No `history`, `location` or `document.title` writes anywhere in the script (F3 asserts).
- Errors: no answer in 15 s -> "The Census lookup is not answering" + Retry; iframe blocked -> the same, plus the
  official Census lookup link. Never a guessed place.

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

### 4.2a Counter button
- `window.DaylightCount = {available: boolean, send(govId) -> Promise<void>}` from `us-count.js` (3.9). `national.js`
  draws "No email? Just count me." in a card only when `available`; on success it calls `markCounted` and shows the
  Done text; on rejection the Failed text and the button stays. `us-count.js` loads before `national.js`; if it fails to
  load, `window.DaylightCount` is undefined and no button shows.
- Button and form are separate: the tap sends no email; the form sends no event. A person who does both is
  counted once as an email request (Buttondown) and once as a tap (GoatCounter); the report never adds them.

### 4.3 National builder (`sitegen/national.py`)
- `load_directory(path) -> Directory` (raises `NationalConfigError` naming the entry and key).
- `clarksville_feeds(facts_city, listing_city, county_agendas, today) -> dict[body_id, UpcomingFeed]`: council
  meetings with `agenda.state = not-read` (or `not-posted`), county agenda-only meetings with items as stored.
- `build_national(out_dir, directory, feeds, labels, share, counter_on) -> list[path]`: writes `digest/index.html`,
  `digest/covered.html` ("What we cover": covered and can't-cover entries by state, then name; share sentence only if
  `share` is given), `digest/requested.html`, and per covered government `digest/<st>/<body id>.html` and `.json`.
  Called from `sitegen.build` only when `national.enabled`. Pages render with the header variant (7a); the pages
  that load scripts are `digest/index.html` only (`national.js`, `us-count.js` when analytics is on); the others load
  none beyond the header's and `count.js`.
- `apply_site_fragments(pages) -> pages`: the two edits to existing pages, each a fixed string, each present only when
  `national.enabled`: the Menu group (footer list) and the front-page line. Anything else in an existing page is a bug.

### 4.4 Fetcher tenant rule (`collector/fetch.py`, M2)
- `SHARED_HOSTS = {"webapi.legistar.com": re.compile(r"^/v1/([a-z0-9-]{2,40})/")}`.
- `tenant_key(url) -> str | None`; the client path segment is lowercased before it is matched or stored (finding 10,
  `national/tenant-key-normalize`). `_blocked` gains tenant keys; `_raw_get` checks host and tenant blocks.
- On 403: robots.txt or non-tenant path or non-JSON body or second distinct tenant -> host block; else tenant block.
  On 429: host block. Exceptions: `TenantBlocked(HostBlocked)` so existing `except HostBlocked` callers still stop.
- `limit_tenant(url, n)`: per-tenant cap inside the host cap.

### 4.5 Legistar upcoming reader (`collector/national/legistar_upcoming.py`, M2)
- `events_url(client, body_id, start, end) -> str` (`$filter=EventBodyId eq N and EventDate ge ... lt ...`).
- `agenda_state(event, final_statuses) -> "final" | "not-final" | "not-posted"`.
- `meeting(event, items, tz) -> dict` in 3.5's shape; `items` only for final agendas of a government whose entry says
  `items: shown`; for any other the items request is never made and `item_count` is null (a count would need the same request; if the
  spec wants counts for school boards that is a separate decision, not a default). `may_be_incomplete = true`.
- `run(directory, fetcher, budget, now) -> (feeds, health, proposals)`; never raises on one body's failure.

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
  `frame-src 'self'`, `form-action https://buttondown.com`, `connect-src https://buttondown.com
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
footer of every existing page by the same fixed fragment (decision N1), and (d) `site/static/` gains `national.js` and
`us-count.js`. The golden test removes (b) and (c) by their exact strings and requires the rest to be equal.

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
  `scripts/request_report.py` ignores `req-` ids not in the directory.

## 11. Invariant: item text is published only for governments we have said so for (`privacy-withhold/national-prefix`)
Problem family `privacy-withhold` (hit three times). Invariant: **a person's or child's name can reach a public page,
feed or email only through item text, and item text is read, stored or published only for a government whose directory
entry says `items: shown`.** The default is withheld; the build refuses `shown` for any `sd*` id and for any entry
the reviewer cannot tie to a general-purpose government (a school or youth board listed under a city, or on a city's
Legistar client, stays withheld even though its id is a `place-` id: its directory `body_name` is the source of that
call, and the Salem entry's PR names how it was checked). Consumers, each of which must read the directory field and
none of which may infer withholding from an id prefix:
1. `collector/national/legistar_upcoming.py`: makes no items request unless `shown` (M2, C2).
2. `sitegen/national.py clarksville_feeds` and the M2 copy step: set `items_withheld` and drop `items` and `item_count`
   from the JSON when not shown.
3. The coming-up page template: prints items only from the JSON's `items`; a withheld government shows the fixed
   "official agenda is the full record" label (UX withheld state).
4. The M4 ICS and Atom writers and the weekly email plan: read only the JSON, so they inherit it (a test builds all
   three outputs from a withheld fixture and finds no item text).
5. `national-data` cache (`data/national/cache/...`): never holds items for a withheld government.
6. The future app and any export: read only the JSON.
A test per consumer with one withheld `place-` entry (a "youth council") and one `sd*` entry.
