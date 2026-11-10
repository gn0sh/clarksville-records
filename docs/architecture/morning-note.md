# Architecture: Daylight M3, the morning note (alerts sign-up)

Design: `docs/design/daylight/README.md`, mock section "Get the morning note" (`daylight-mock.html` ~line 200).
Plan: `docs/plan/one-week-finish.md` item 3 (alerts v1 = Atom feeds; email is v2). Spec: M5 in
`docs/specs/clarksville-records.md`. Builds on `sitegen/feeds.py` (Alerts v1) and `site/static/seats.js`.

## Context and goal
The mock offers "A short email at 7:00 AM on days when something on your list is on an agenda or was voted on.
Quiet on every other day." Sending mail, opening a provider account, spending money and storing anyone's email are
hard stops. So M3 ships everything except the sender: (1) the list picker, honest about state ("Email starts at
launch; follow by feed now") and linking the matching Atom feeds; (2) the missing feeds; (3) a digest generator that
writes each day's "what's new" as static JSON and a preview page, so a future sender only mails it; (4) a config seam,
off by default, so going live is a config change after the CEO picks a provider. No fake success message, ever.

## Components
| Part | File | Responsibility |
|---|---|---|
| Digest generator | `sitegen/morning.py` (new) | From facts + the collectors' manifests, compute per-day entries; `select()` filters them for one set of lists and seats |
| Feeds | `sitegen/feeds.py` | Add a contracts feed, RPC zoning cases in the rezoning feed, per-district and per-ward zoning feeds (pages target) |
| Sign-up section | `site/templates/alerts.html.j2` `#note` | Picker, state line, feed links; nav "Morning note" points here (the landing must stay one screen) |
| Preview page | `site/templates/morning.html.j2` -> `morning/index.html` | Today's note as it would read, all lists, filtered on-device |
| Client | `site/static/morning.js` (new) | Reads `cr-your-seats` (seats.js), shows/hides entries and feed links per picked list; no network calls |
| Config | `config/site.yml` `morning_note:` | Lists, window, retention, provider seam (`enabled: false`) |

## "New today": the window rule
A digest for date D (in `site_timezone`) holds every document whose **`first_fetched_at`** falls in `[D-1 cutoff, D cutoff)`, cutoff `morning_note.cutoff` = `"07:00"`. `first_fetched_at` never changes on
re-fetch, so an item never alerts twice. It is read, by source URL, from each collector's own manifest:
`data/manifest.json` (county minutes, finance), `data/county-agendas/manifest.json`,
`data/localities/clarksville-tn/manifest.json`, `data/localities/cmc-rpc/manifest.json` (checked: every current
source URL in facts/finance/RPC resolves to one of these). The daily update runs 09:07 UTC (03:07/04:07 local), before the cutoff, so
the 7:00 note covers that morning's collection. A document maps to entries:
- an agenda (county, county agenda-only, council, RPC): one `agenda_item` entry per item / case printed on it;
- minutes: one `vote` entry per motion recorded on it (outcome and tally only as printed and confirmed; an unconfirmed
  motion says "Recorded in the minutes; not confirmed" with no values, per `config.SHOW_UNCONFIRMED_VALUES`);
- a finance document (budget book) or a new solicitation row: one `document` / `solicitation` entry.
Entry ids reuse the feed id scheme (`<body>/item/<item id>/<meeting id>`, etc.), so feed and note agree.

## The four lists (keys are config, labels are config)
- `budget`: entries whose item matches the `budget` item type (views.item_types), plus new budget books.
- `contracts`: new solicitations in `data/finance.json` (and their new documents).
- `seats` ("My two seats"): agenda and minutes entries of the body each stored seat sits on: county documents when
  `district` is set, the council's when `ward` is set. M3 shows **no per-official vote line** ("your seat voted"): the
  M2 decision left it out, and it is a claim about a named person; it needs its own design and QA spot check.
- `zoning` ("Zoning near me"), precise rule:
  1. Candidate entries: RPC agenda cases whose `prefix` is in `morning_note.zoning_prefixes` (`[Z, ZO, CZ, CZO, HZ]`,
     the rpc.yml "City/County/Historic zoning" case types), and County Commission items linked to such a case by
     `Rpc.link_county` (exact case-number match, never fuzzy). A linked county item inherits that case's district/ward.
  2. Match: `case.district == seats.district` (agenda's printed "CO. COMM. DISTRICT:") **or**
     `case.ward == seats.ward` (printed ward). Printed values only; the `location` text is never geocoded.
  3. A case with neither printed (27 of the 471 Z/CZ/CZO cases in current data; the 8 CZO cases print neither) never
     matches "near me"; the note adds one neutral line "N zoning cases printed no district or ward" linking the
     all-zoning feed. City Council zoning items carry no ward and are not linked to RPC cases today, so they match
     only via the all-zoning feed (a council<->RPC case link is a later task, not M3).
  So: by district for county and city cases, by ward for city cases; never by distance or address.

## Output contract (the future sender's only input)
`build/site/morning/YYYY-MM-DD.json` for the last `keep_days` days (default 7), `morning/latest.json` (a copy of
today's), `morning/index.html`. Files are always written, an empty `entries` meaning a quiet day (send nothing).
```
{"schema": "morning-note/1", "date": "2026-11-11", "window": {"from": "2026-11-10T07:00-06:00", "to": "...T07:00-06:00"},
 "data_as_of": "2026-11-11", "lists": [{"key": "zoning", "label": "Zoning near me"}, ...],
 "entries": [{"id": "rpc/case/Z-12-2026/rpc-2026-11-24", "lists": ["zoning"], "kind": "agenda_item|vote|document|solicitation",
   "body": "rpc", "body_name": "...", "meeting_date": "2026-11-24", "title": "<verbatim>", "recorded": "On the agenda",
   "district": 7, "ward": 6, "href": "rpc/meetings/2026.html#...", "source": {"url": "...", "page": 3}}],
 "unplaced_zoning": 0}
```
T1 additions (additive; T3 and the sender may rely on them):
- every entry carries `seat_body`: `"district"` (county entries), `"ward"` (council entries) or `null`; `select()`'s
  `seats` rule is "`seat_body` is district and a district is stored, or ward and a ward is stored";
- a `vote` entry also carries `confirmed` (bool), `outcome` and `tally` (both `null` unless confirmed; RPC: the minutes'
  own outcome text and tally; county/council: the Passed/Failed label and the printed tally "yes-no[-abstain]");
  no entry carries any person's name (no mover, seconder, nays or per-official votes);
- the note carries `unplaced_text` (config text with N filled in, `""` when 0); all connective text is
  `morning_note.text` in config;
- an agenda or minutes with no item or motion read gives one `document` entry ("Agenda posted"/"Minutes posted"),
  id `<body>/meeting/<meeting id>/<agenda|minutes>` (the feeds' scheme); votes are `<body>/vote/<roll call or motion
  id>`; county agenda-only items `county/item/<number>/<meeting id>`; RPC cases `<rpc body_key>/item/<case id>/<meeting
  id>`; budget books `finance/book/<book id>`; a solicitation is new on the day its first document is first fetched
  (`contracts/solicitation/<id>`), and each document first fetched on a later day is `contracts/document/<sol>/<doc>`;
- the manifest paths are config (`morning_note.manifests`, they name localities); a fixture build writes no note
  unless a test passes `morning_manifests=`;
- file budget (manager decision 2026-11-10): `morning/` (JSON and T3's `morning/index.html`) is built on the `pages`
  target only; the preview writes none. A preview still over 500 with the export after leaving out transcript pages
  is built again without the open-data export (log line; data.html and about.html link no data/ file then);
- backfill guard: a day holding any document from a collector's initial run (first fetched within
  `morning_note.backfill.initial_run_hours` of its manifest's earliest row) or more than `backfill.max_entries`
  entries has `"backfill": true` and `entries: []`; `counts` (`entries`, `lists` per key, `unplaced_zoning`) is kept.
  The sender sends nothing for such a day;
- the neutrality scan (`BANNED`) runs over our own words only (`morning.own_text`: list labels, connective text,
  body names), not verbatim titles or URLs.

`select(day, lists, seats) -> list[entry]` (Python, `sitegen/morning.py`) is the one filter: `seats` and `budget`/
`contracts` membership is by `lists`; `zoning` and `seats` also need the seat match above. `morning.js` mirrors it;
a parity test runs both over the fixture (as `test_georef_js.py` does). Titles are the record's own words; all
connective text comes from config; no name of an official appears outside a verbatim title; no summarising text.

## Provider seam (off by default)
```
morning_note:
  enabled: false        # true only after the CEO picks a provider (hard stops 3-5)
  provider: ""          # label for the record only; code never branches on it
  form_action: ""       # https URL the sign-up form POSTs to (the provider's hosted endpoint)
  form_fields: {email: "email", lists: "tags", district: "metadata__district", ward: "metadata__ward"}
  privacy_url: ""       # the provider's privacy policy, required when enabled
```
Off (M3): the form has no `action`, no email field and no submit; it shows the picker, "Email starts at launch;
follow by feed now", and the picked lists' feed links. On: the build renders the email field, posts directly to
`form_action` (CSP `form-action 'self'` gains that one origin, computed by the build), and the page says what is sent
and to whom, linking `privacy_url`. `build.problems()` refuses `enabled: true` without an https `form_action` and a
`privacy_url`, and refuses a non-empty `form_action` while `enabled` is false. The sender (later) is a scheduled job
that reads `morning/latest.json`, groups subscribers by (lists, district, ward), calls `select()` per group and mails
non-empty results through the provider API; that job and its secret are a later task behind the CEO's go-ahead.

## Privacy and neutrality
- M3: nothing about the visitor leaves the device. Seats come from `localStorage["cr-your-seats"]`; picks live in the
  URL fragment (`morning/#lists=zoning,budget`), never sent. `morning.js` makes no network call (CSP `connect-src
  'none'` stays). No new storage key.
- Locality names, body names and list labels come from config; the existing template locality test covers the new
  templates, and `test_site_neutrality.BANNED` runs over the digest JSON and preview page.

## Feeds added (file budget)
`feeds/topic-contracts.xml` (one entry per solicitation, id `contracts/solicitation/<id>`); RPC zoning cases join
`topic-rezoning.xml` (new ids `rpc/item/<case id>/<meeting id>`; existing ids unchanged). Per-seat zoning feeds
`feeds/zoning-district-NN.xml` (21) and `feeds/zoning-ward-NN.xml` (12) are built on the `pages` target only
(cap 3000); the `preview` target (cap 500) links the all-zoning feed instead. This reverses the feeds.py note "the
records place no item in a district or ward", which predates the RPC case fields; update that docstring and
`test_one_feed_per_body_and_per_topic`.

## Provider options for the CEO (all pricing unverified, checked from memory, not from vendor pages)
| Option | Cost (unverified) | Personal data it holds | Fit |
|---|---|---|---|
| A. Buttondown (newsletter service, API, tags + metadata, double opt-in) | free tier for a small list (~100 subscribers), paid above | email, tags (lists), district/ward metadata, open/click data unless turned off | Hosted form endpoint, one-tap unsubscribe, API send per tag group; smallest surface |
| B. Brevo (transactional + marketing email, free tier) | free tier with a daily send cap (~300/day) | email, contact attributes, send logs | Higher free volume; heavier account, marketing tracking on by default |
| C. Double-opt-in form service (e.g. a static-form backend) + our own sender via a free SMTP/API tier | free tiers on both, two vendors | email in the form service and the mail sender | Most moving parts; two privacy policies |
**Recommend A (Buttondown)**: one vendor, built-in double opt-in and unsubscribe, metadata fields match the seam.
Going live needs: the CEO's pick, account creation by the CEO, an API key secret, a privacy notice, and a security
review of the sender job (hard stops 3, 4, 5, and 1 for the first send).

## Risks
- Window rule depends on every collector manifest keeping `first_fetched_at`; T1 must assert every digest document resolves to a manifest row (fail the build, do not skip).
- RPC printed district is the agenda's claim; a case near a line still matches one district only. Say "as printed".
- Digest wording drift into commentary: guarded by config-only connective text and the BANNED scan.
- No ADR: every choice here is reversible (static files, config off by default). Write one when a provider is chosen.
