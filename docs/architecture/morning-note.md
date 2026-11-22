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
   "body": "rpc", "body_name": "...", "meeting_date": "2026-11-24", "meeting": "meeting", "title": "<verbatim>", "recorded": "On the agenda",
   "district": 7, "ward": 6, "href": "rpc/meetings/2026.html#...", "source": {"url": "...", "page": 3}}],
 "unplaced_zoning": 0}
```
`data_as_of` is a plain YYYY-MM-DD, per note, see below; local days unless data_as_of_utc: the newest fetch day of
every body's sources on or before the note's day (`morning.as_of`), the America/Chicago day of its manifest instant
(docs/architecture/local-dates.md). Beside it, `data_as_of_utc` (bool, additive) is `true` when some
source has no manifest row, so the day is a stored UTC day instead (a fixture build).
T1 additions (additive; T3 and the sender may rely on them):
- every entry carries `watch` (2026-11-11, sitegen/watch.py): `{url, link, label, ext}` for an entry about a meeting
  of a body with a config/site.yml `video:` entry (a council meeting's own recording when exactly one meeting of that
  body that day carries a video_url `transcripts.video_ok` allows, else the body's official video page), else `null`
  (no such body entry, or no meeting: a solicitation). The preview page shows it; the mail render does not yet (its
  `link_hosts` would need the video hosts first);
- every entry carries `seat_body`: `"district"` (county entries), `"ward"` (council entries) or `null`; `select()`'s
  `seats` rule is "`seat_body` is district and a district is stored, or ward and a ward is stored";
- a `vote` entry also carries `confirmed` (bool), `outcome` and `tally` (both `null` unless confirmed; RPC: the minutes'
  own outcome text and tally; county/council: the Passed/Failed label and the printed tally "yes-no[-abstain]");
  no entry carries any person's name (no mover, seconder, nays or per-official votes);
- a county/council `vote` entry also carries `vote_on` (additive, 2026-11-10): what the roll call voted on
  ("Amendment", "Resolution, as amended"), the site's fixed "Vote on" label for the roll call's own outcome clause
  (`views.outcome_kind_label`, about.html#vote-on); `null` unless confirmed and a pattern matches, and absent on RPC
  votes. Two votes on one item share title, date and `recorded`; `vote_on` and `source.page` tell them apart. The
  preview prints it after `morning_note.page.vote_on_label`;
- `data_as_of` is per note: the newest source fetch date on or before the note's `date`, over every file the note
  reads (county minutes, councils, RPC, county agendas, finance); `""` when there is none;
- the note carries `unplaced_text` (config text with N filled in, `""` when 0); all connective text is
  `morning_note.text` in config;
- an agenda or minutes with no item or motion read gives one `document` entry ("Agenda posted"/"Minutes posted"),
  id `<body>/meeting/<meeting id>/<agenda|minutes>` (the feeds' scheme); votes are `<body>/vote/<roll call or motion
  id>`; county agenda-only items `county/item/<number>/<meeting id>`; RPC cases `<rpc body_key>/item/<case id>/<meeting
  id>`; budget books `finance/book/<book id>`; a solicitation is new on the day its first document is first fetched
  (`contracts/solicitation/<id>`), and each document first fetched on a later day is `contracts/document/<sol>/<doc>`;
- the manifest paths are config (`fetch_manifests`, the one list pages also use; they name localities); a fixture build writes no note
  unless a test passes `morning_manifests=`;
- file budget (manager decision 2026-11-10): `morning/` (JSON and T3's `morning/index.html`) is built on the `pages`
  target only; the preview writes none. A preview still over 500 with the export after leaving out transcript pages
  is built again without the open-data export (log line; then no page links a data/ file, data.html and about.html
  say the files are on the full site, and an earlier export left in the build's `data/` is removed);
- backfill guard: a day holding any document from a collector's initial run (first fetched within
  `morning_note.backfill.initial_run_hours` of its manifest's earliest row) or more than `backfill.max_entries`
  entries has `"backfill": true` and `entries: []`; `counts` (`entries`, `lists` per key, `unplaced_zoning`) is kept.
  The sender sends nothing for such a day;
- the neutrality scan (`BANNED`) runs over our own words only (`morning.own_text`: list labels, connective text,
  body names, and titles we make), not verbatim titles or URLs. Every entry carries `title_ours` (bool): true when
  the title is ours, not the record's (a meeting's label for minutes with nothing itemised or a vote with no item, an
  agenda-only meeting's date and kind, an untitled item's fallback);
- each entry's meeting (`meeting_date`, the id's meeting part, a fallback title and link) is the fact's own
  `meeting_id`; a source named by two meetings (minutes covering both) gives each fact its own meeting, and a
  `document` entry for each meeting when nothing in it is itemised;
- every entry from a meeting carries `meeting` (2026-11-17, note/entry-meeting): which meeting it is, in the site's
  own words for that body's meeting kinds (`kind_labels`, lower case: "formal meeting", "informal meeting", "regular
  session"), else config `morning_note.text.meeting` ("meeting", RPC); `null` with `meeting_date` (a budget book,
  a solicitation). The same item on two agendas (real data: 26-11-4 on the Nov 2 informal and Nov 9 formal county
  agendas) so reads as two meetings, not a duplicate. It is in `own_text`, so the neutrality scan reads it;
- every zoning entry carries `case`: the case number in its one comparable form (rpc_minutes.link_key), `null` on
  other entries; `unplaced_zoning` counts distinct cases (a case on an agenda and in the minutes is one case);
- every entry carries `untitled`, `meeting_href` and `item_number` (additive, 2026-11-22, note/compact-untitled):
  `untitled` is true
  when the record printed no title of its own (`title_ours`, or a county/council item whose printed title is only a
  document kind, `morning.DOCUMENT_KINDS`: "MINUTES"); `meeting_href` is the site's page of the entry's meeting for
  county and council entries, else `null`; `item_number` is the county/council item's own printed number
  ("ORDINANCE 95-2025-26"), else `null`. The email uses them (Body, below); the preview page ignores them;
- the note carries `coming_up` (additive, 2026-11-22, note/sunrise): the next `morning.COMING_N` (3) meetings the
  site lists on or after the note's `date`, soonest first, the same for every reader: `[{date, body, meeting, href}]`,
  a selection of the day page's own meeting cards (`days.meeting_rows`), so a council meeting only on the city
  calendar (no agenda yet) counts. Bid listings and cancelled meetings are left out; a council meeting the facts
  hold is cancelled when the city calendar now calls it off (`days.called_off`, the Digest's rule). `meeting` is the
  card's kind label in lower case, without its part before the first ", " when the body's name ends with that part
  ("Budget Committee, special called meeting" of "Montgomery County Budget Committee"), `null` when it has none or the body's name already
  says it; `href` is always the meeting's day on `today.html` (`today.html#d-<date>`; a meeting page's part number
  can move). No time or place (neither is collected). `[]` when none; the email reads a missing field as `[]`. Body
  names and kind labels are in `own_text`. **Current, not frozen**: it is the only part of a note that may differ
  between two builds of one day, and the day claim does not read it (Deliver stage, Day claim).

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
  form_fields: {email: "email", lists: "tag", district: "tag", ward: "tag"}   # 2026-11-17: Buttondown tags only
  privacy_url: ""       # the provider's privacy policy, required when enabled
```
Off (M3): the form has no `action`, no email field and no submit; it shows the picker, "Email starts at launch;
follow by feed now", and the picked lists' feed links. On: the build renders the email field, posts directly to
`form_action` (CSP `form-action 'self'` gains that one origin, computed by the build), and the page says what is sent
and to whom, linking `privacy_url`. On, the stored seats are posted only by consent (security review finding 3):
the form shows a visible, ticked "Include my saved seats: District 5, Ward 3" box (no `name`, never posted itself,
shown only when seats are stored); unticked, or without the script, both seat fields stay disabled and nothing about
a seat is posted. On, the landing and Method pages also stop saying the seats are "never sent anywhere"
(`morning_page.privacy()`, text `page.seats_sent`) and the Method page gains a "Morning note" paragraph: what is
sent, to whom, how to unsubscribe, and the `privacy_url` link (`page.method_*`; finding 1). `page.seats_sent` and
`page.method_sent` must contain `{box}`, filled with `page.seats_include` without its colon, so they name the box by
the label it shows. `morning.js` recomputes the seat fields on `change`, `pageshow` and `submit`. `qa.site_checks`
allows that one off-site form action (a `formaction` attribute meets the same rule) and CSP origin on alerts.html
only while `enabled` is true, and fails any feed entry without its `rel="related"` source link (the build drops a
source URL that fails the one link rule, `config.https_link`). `build.problems()` refuses `enabled: true` without an
https `form_action` and a `privacy_url`, and refuses a non-empty `form_action` while `enabled` is false. The sender is
designed in "T4 sender" below: it reads `morning/<date>.json`, groups subscribers by (lists, district, ward) with
`select()` and mails non-empty results through the provider API. It and its secret stay off behind the CEO's go-ahead.

## Privacy and neutrality
- M3: nothing about the visitor leaves the device. Seats come from `localStorage["cr-your-seats"]`; picks live in the
  URL fragment (`morning/#lists=zoning,budget`), never sent. `morning.js` makes no network call (CSP `connect-src
  'none'` stays). No new storage key.
- Locality names, body names and list labels come from config; the existing template locality test covers the new
  templates, and `test_site_neutrality.BANNED` runs over the digest JSON and preview page.

## Feeds added (file budget)
`feeds/topic-contracts.xml` (one entry per solicitation, id `contracts/solicitation/<id>`); RPC zoning cases join
`topic-rezoning.xml` (new ids `rpc/item/<case id>/<meeting id>`; existing ids unchanged). Decision (manager,
2026-11-10, review `feeds/rezoning-keeps-every-body`): one rezoning feed URL, capped per body (each body keeps its
newest `alerts.max_entries`), so RPC cases dated ahead never push county or council items out. Per-seat zoning feeds
`feeds/zoning-district-NN.xml` (21) and `feeds/zoning-ward-NN.xml` (12) are built on the `pages` target only
(cap 3000); the `preview` target (cap 500) links the all-zoning feed instead. This reverses the feeds.py note "the
records place no item in a district or ward", which predates the RPC case fields; update that docstring and
`test_one_feed_per_body_and_per_topic`.

## Provider options for the CEO (all pricing unverified, checked from memory, not from vendor pages)
**Decided: A, Buttondown (Brian, 2026-11-10).** What its public docs say is in "T4 sender", "Buttondown: verified and assumed".
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
- ADR: `docs/adr/0004-morning-note-sender.md` (provider and sending approach).

## T4 sender (designed 2026-11-10; ADR 0004)

Provider: Buttondown (Brian, 2026-11-10). He creates the account, sets DNS and pays at go-live. The API key will be a
GitHub Actions secret that does not exist yet; no key, address or subscriber field is ever written to the repo.
Nothing in T4 sends until three separate switches are on (see "Switches").

### Decision: editions, not per-person mails and not fixed per-list segments
Each subscriber gets **at most one email a day, holding exactly what `select()` returns for their lists and seats**,
and nothing on a day when that is empty. Subscribers whose selection is identical share one email, an **edition**.
The sender creates one Buttondown email per edition (a handful a day), never one per person.

| Option | Why not |
|---|---|
| One API send per subscriber | N requests a day, and the body differs per person only through data the edition already captures. Same result as editions at higher cost and more failure points. |
| A fixed set of segment emails (one per list, per district, per ward) | Needs no subscriber read, which is its one real advantage. But a person on three lists gets three emails at once, and a city zoning case that prints both a ward and a district reaches the same person twice. That breaks "a short email ... quiet on every other day". |
| One email to everyone with per-person conditional content | Depends on template conditionals and OR filters we could not verify, and cannot stay quiet for a person whose sections are all empty. |

Cost of the choice: the sender must read each active subscriber's lists, district and ward (never the address; see
Privacy), so its key needs subscriber access. Recorded as threat point 2.

### Two stages, in two jobs
| Stage | Where | Network, secret | Does |
|---|---|---|---|
| `python -m sender plan` | `update` job, after "Site checks", every day, from launch day one | none, none | Reads `build/site/morning/<D>.json`; writes the would-send payloads to `build/morning-send/<D>/`. This is the dry run, and it runs daily as a rehearsal whether or not sending is on. |
| `sender deliver` (run isolated: `python -I -S -c` on a staged copy of `sender/`, see main-protect-invariant.md) | new `note` job, `needs: [update, deploy]` | `api.buttondown.com` only; `BUTTONDOWN_API_KEY` | Reads only the plan file; talks to the provider. Standard library only: no `pip install` and no `sitegen` import in the job that holds the key. Without `--live` it prints what it would do and opens no connection. |

New top-level package `sender/` (not under `sitegen/`, which must stay network-free): `plan.py` (pure), `render.py`
(subject and body), `deliver.py` (guards and day claim), `buttondown.py` (the only module that opens a connection;
host fixed to the config `api_base`, https only), `__main__.py`.

### Plan stage (the dry run)
Input guards, each ending in `send: false` with a `reason`, exit 0, unless marked fail:
- the note file for D is missing or not `schema: "morning-note/1"`: **fail** (exit 2, the run's failure issue opens);
- `note.date` is not D, where D is today in `site_timezone`: fail;
- `backfill` is true: `reason: "backfill"` (the T1 guard; a backfill day never mails);
- `entries` is empty: `reason: "quiet"`;
- the plan's files over `MAX_PLAN_BYTES` (32 MB, `sender/common.py`): fail (something is wrong with the data, not a
  busy day). As built, `sender.max_editions` is applied by the deliver stage to editions that have a recipient.

Otherwise, for every possible signature (each non-empty subset of the four lists x district none or 1..`district_count`
x ward none or 1..`ward_count`; 15 x 22 x 13 = 4,290 calls of `morning.select`, cheap), take the selected entry ids.
Signatures with the same email share an edition: the same entries, each under the same list heading
(`plan.placed()`: an entry stands under the first of its own lists that the shape picked and that selected it, grouped
in list order, the note's order kept within a list; render/section-not-picked, 2026-11-17). Its key is the first 12
hex of `sha256(date + "\n" + "<entry id>\t<list key>" rows joined by "\n")`. Signatures with an empty selection are
left out: those people get nothing.

`build/morning-send/<D>/plan.json` (and `edition-<key>.html` / `.txt` beside it for a person to read):
```
{"schema": "morning-send/1", "date": "2026-11-11", "note_sha256": "<of the note file>", "timezone": "America/Chicago",
 "send": true, "reason": "ok", "send_at": "2026-11-11T07:00:00-06:00", "latest_send": "2026-11-11T10:00:00-06:00",
 "editions": [{"key": "3fa9c1d2e07b", "subject": "...", "body": "<html>", "entry_ids": ["rpc/item/..."]}],
 "signatures": {"zoning|7|-": "3fa9c1d2e07b", "budget,zoning|7|3": "91c0..."}}
```
The plan is a pure function of the note and config: two runs on the same note give byte-identical files. It holds
no subscriber data, so it is safe as a build artifact in a public repository.

Body (`render.py`; layout since 2026-11-22 is note/sunrise, "Email body forms" below): the site name and date, then per picked list its config label and the entries placed under it: body name
and meeting (config `morning_note.text.meeting_line`, "{body}, {date} {meeting}": "Montgomery County Commission, November
9, 2026 formal meeting"; the body alone for an entry with no meeting), `recorded`, the verbatim title, a link to the site page (`alerts.site_url` + `href`) and the source link; then
`unplaced_text` when set; then one config line saying why the reader got this; the HTML edition then closes with the
site footer's gnoshcodes credit (`common.CREDIT_LINE`, note/credit-logo, Brian 2026-11-17: the hook wordmark PNG at
`https://daylight.gnoshcodes.com/static/brand/gnoshcodes-hook-light.png`, 160x32, alt "gnoshcodes", "A gnoshcodes
project."), the one image `deliver.body_ok` accepts, as that exact line. In the seats section only
(`render.COMPACT_LIST`), a meeting's untitled votes (`kind` vote, `untitled` true, a `meeting_href`, no `case`: a
zoning case is never compacted) stand as one item when the section holds `render.COMPACT_MIN` (2) or more of them from
one minutes document (note/compact-untitled; real data 2026-11-18: four past council meetings' minutes gave a seats
reader 51 entries, about 320 lines): the meeting line, config `morning_note.sender.text.untitled_votes` with `{n}` the
count ("{n} votes in these minutes with no item title:"), then one line of the record's own `item_number`s, each once,
in the record's order, joined with ", " and escaped like a title (none for a kind-only "MINUTES"; with no number at all
the count line drops its trailing colon), then a link to `site_url` + `meeting_href` and one to the minutes document
(its URL without `#page=`), at the place of the first of them; a lone untitled vote and every titled entry stand as
before. The group shows no outcome, tally or name, so a confirmed roll call's outcome, which the preview page shows,
is not in the email for these votes (the meeting page has it).
`plan.json` still lists every entry id, and the edition key is unchanged (over every row), since the email is a pure
function of its rows. Rules:
- every title and URL is HTML-escaped, and `{{`, `{%` and a leading `---` are neutralised, because the body goes
  through the provider's own template and Markdown step (a record's title is untrusted text);
- links are only `site_url` pages and `source.url` values that pass `build._is_https_uri`; anything else drops the link;
- every word that is ours comes from `morning_note.sender.text` in config and runs through the `BANNED` scan with
  `morning_note.sender.text` in config and runs through the `BANNED` scan with
  `morning.own_text`; no official's name outside a verbatim title; no summary. The email adds nothing the preview
  page (`morning/index.html`) does not already show, except the note's `coming_up` meetings (the landing's own
  "Coming up" selection from `today.html`) and the fixed plain-word definitions (note/sunrise);
- the unsubscribe link and footer are the provider's; we add no unsubscribe mechanism of our own.

### Email body forms (note/sunrise, 2026-11-22)
The owner chose design concept A "Sunrise" (`/mnt/project-files/clarksville-records/morning-note-design/concepts.md`)
with concept C's plain words and its "You are invited." line. Order of the HTML edition: the sky header (site name
with the sun mark, `site_place`, config `header_day` "{weekday} in {place}" over "November 18", the sun drawn with CSS),
`unofficial.email_line`, the greeting (`greeting`, `tagline`, `intro`), the `new_on_list` kicker, then per list an
`h2` and one white card per item (from a meeting: the site's date block, the meeting line as `h3` and link to the
site's page, `recorded`, the title in bold, the source link "Source document, {date} meeting[, page N]"; anything
else: body and `recorded` as a kicker, the title as `h3` and link, "Source document"), the unplaced line, "Read it in
plain words." (only the `define_*` texts whose kind is in the edition, `render.KINDS`: the entries' title, item
number or source file name; a vote means minutes), the navy "Take part" box (`take_part`, `take_part_heading`,
`take_part_line`, `invited`, then `coming_up` and one line per note `coming_up` row when there is one, and the
`all_meetings` button to `today.html`; "Read it in plain words." reads only the items shown after the size cut), then the footer (`why`, the notice, the support line, `CREDIT_LINE`
unchanged). Every word is `morning_note.sender.text` (placeholders checked by `morning.sender_problems`; each
`define_*` must read "Term. Definition."). `body_text` is the same content in the same order. The one image is still
the credit logo; the sun, mark and date blocks are text and CSS, so the email reads with images off.

**Size rule.** Gmail clips a message at about 102 KB, which hides the notice, the support line and the provider's
unsubscribe link. `render.layout` keeps every edition's HTML at or under `common.BODY_BUDGET` (80,000 bytes): all
cards when they fit; else the first items as cards and the rest as one-line rows (`TAG["row"]`: the item's words,
its page link with `open_site` and its source link); else rows only, as many as fit, then one line `more` ("{n} more
on the site") linking `morning/index.html`. The header, "Take part" box and footer always stay. The plain text twin
carries the same cut.

**Accepted forms (`deliver.body_ok`, the security boundary).** Invariant: every opening tag in an emailed body is
one of the exact strings render writes, so no attribute and no style can come from anything but our own source.
- The strings are `common.TAG` (each opening tag with its fixed inline style; colors are site tokens, no `url()`,
  `position`, `background-image`, gradient, `!important`, brace, quote or double space) and `common.LINKS` (a link is
  `<a href="` + URL + one of three fixed endings: ink, white on navy, the button). render writes only these by name;
  deliver builds its sets from them once, at import, and compares whole strings. No style or attribute parser exists.
- The body's first line is exactly `TAG["page"]`; every line is either one container tag alone (`CONTAINERS`: div,
  table, tr, td forms), its lone closing tag, `CREDIT_LINE` exactly, or one block: a non-container, non-inline TAG,
  then text, `&middot;` and render's numeric references, `<br>`, the inline TAGs (`INLINE`: the sun spans, the day
  number span, `<strong>`) and links (text only inside a link), all closed in order, the block's close last.
  Containers close in order and nothing follows the last; exactly one `<h1>`; no blank or indented line.
- No text inside the sun or the name's mark (`EMPTY`): they are shapes.
- Unchanged from M3: text holds no raw `common.MARKUP` character and no format or control character; read as shown,
  no `common.ADDRESS`; every `href` is an https URL on `link_hosts` or exactly the support URL, `&` only as `&amp;`.
  Record text reaches the body only through `render.inert()`, in every slot (titles, item numbers, body names,
  meeting words, coming-up rows, `site_place`, `today_place`).
- Tests: `tests/test_morning_sender_sunrise.py` (hostile text in every new slot, random text, an unknown attribute or
  style, a changed link ending, words in the sun, two blocks on a line, a tampered constant failing the plan) and
  `tests/test_morning_sender_deliver.py` (the M3 cases, moved to the new forms).
Unverified before go-live: whether Buttondown's template and Markdown step pass `style`, `table`, `role` and
`aria-hidden` through unchanged, and what wrapper it adds (one test email to a team inbox answers both).

### Deliver stage
Order of work for `deliver --live` (any failed check stops before the first write, exit non-zero, nothing sent):
1. **No-send exits**: `plan.send` is false: exit 0 with no connection at all (the fail-safe for quiet and backfill days).
2. **Date guard**: `plan.date` must be today in `plan.timezone`. A re-run tomorrow of today's workflow run sends nothing.
   Now later than `latest_send`: exit 3 as "missed" (as built: a distinct non-zero code, so the job fails), open the failure issue, send nothing. The records still reach
   readers by the site and the feeds; a note is never sent the next day.
3. **Day claim (idempotence)**: list the provider's recent emails and keep those with `metadata.note_date == D`.
   - none: the day is unclaimed, go on;
   - some, all with `metadata.note_sha256 == plan.note_sha256`: a re-run of the same plan; go on, but only for editions
     whose key is not among them (finishes a run that died half way);
   - any with a different `note_sha256`: the day belongs to an earlier, different plan. Send nothing, exit 0. (A second
     collection before 7:00 that adds a document changes the note; its additions are on the site and feeds only.)
     So note D must not change after D's cutoff, except `coming_up` (note/sunrise): the next meetings stay current
     (a calendar change between the morning's builds), so the claim leaves them out. `note_sha256` is
     `common.note_digest`, sha256 over the note as canonical JSON without `common.CLAIM_FREE` (`coming_up`), and
     `deliver.plan_digest` reads each body without its "Coming up" lines (the lines that open with
     `TAG["coming_kicker"]` or `TAG["coming"]`, which render writes for nothing else). Safe, because who gets which
     email never depends on them: edition keys are rows only, and the entries, signatures, subjects and every other
     line of every body are still in both digests. A re-run whose build lists other meetings is the same plan for
     the claim and creates only the editions not yet created, with the newer list; nobody gets two. Two cases read
     "other" instead (send nothing more that day, fail safe): a `coming_up` change in an edition near the 80 KB budget
     (`common.BODY_BUDGET`) can move its card/row cut, so the rest of that body differs; and the first run after the
     note/sunrise merge, for a day the old code already started, has other digests. So do not merge it between
     07:00 and 10:00 Central (`send_at` to `latest_send`).
   - the listing fails, is cut short or cannot be read: send nothing, exit non-zero. **Fail closed.**
4. **Recipients**: page through subscribers, keep `type == "regular"` (confirmed; `unactivated`, `unsubscribed` and
   the rest are never mailed), and reduce each at the adapter boundary to `(id, lists, district, ward)`, read from
   the sender's own Buttondown tags only (`note-<list key>`, `note-district-<n>`, `note-ward-<n>`; 2026-11-17, see
   "Switch-on"). The address, every other tag and the metadata are dropped there and never reach the rest of the
   program. Tags that are not ours, and seats that are not one whole number in range, are ignored (two district
   tags: no district). More than `sender.max_recipients`: stop, send nothing.
5. **Per edition** (in key order): the subscribers whose signature maps to it. None: skip, no email is created.
   Otherwise deliver by the mode the T4.0 probe selected:
   - `stamp` (preferred): set each recipient's metadata to exactly `{"note_edition": "<D>.<key>.<mac>"}` (the
     provider's PATCH replaces the whole object, T4.0 probe; lists and seats are tags, so nothing else is kept), then create one email with `filters` = `subscriber.metadata.
     note_edition equals <stamp>`, `status: "scheduled"`, `publish_date` = `send_at` (as built: at least 5 minutes after
     the clock, read per edition just before its email is created; past `latest_send`, exit 2 "late" and the rest
     are not sent), `archival_mode: "disabled"`, `metadata: {note_date, note_edition, note_sha256}`. A stamp from an
     earlier day can never match, because the value carries the date. The email sits scheduled until 7:00, so a
     person can still delete it in the provider's dashboard.
   - `ids` (fallback): create the email as a draft with the same metadata, then `POST /v1/emails/{id}/send-draft` with
     `subscribers: [ids]`. Needs subscriber read only, but sends at once (about 4 AM local).
   Every write carries `X-Idempotency-Key` = `uuid5(namespace, "daylight-note/<D>/<key>/<step>")`.
6. **Log**: totals only (see Privacy).

Rate: one request at a time, at most 5 a second, obeying `Retry-After` on 429 and stopping after 3 tries. With 500
recipients on a busy day `stamp` makes about 510 requests, under the limit of 600 a minute.

Idempotence, in layers: the workflow's `concurrency: daily-update` group (one run at a time); the date guard; the
day claim read from the provider (the record of truth, because it survives a lost runner); the idempotency key on
each write. We keep no "sent" file in the repo: the `note` job would need a write token for it, and the provider's
own list answers the same question.

### Switches (all three must be on; each is off or absent today)
| Switch | Where | Who turns it |
|---|---|---|
| `morning_note.sender.enabled: true` | `config/site.yml`, by a reviewed PR | the team, after the security review |
| Repository variable `MORNING_NOTE_SEND == 'true'` | GitHub settings | Brian (hard stop 1: the first send) |
| Secret `BUTTONDOWN_API_KEY` in the `morning-note` environment | GitHub settings | Brian (hard stop 5) |
| Secret `MORNING_NOTE_CANARY_IDS` in the `morning-note` environment (the team's own subscriber ids) | GitHub settings | Brian, with the key |
The `note` job also needs the `deploy` job to have succeeded, so it cannot run while the deploy is locked, and an
email never links a page that is not live. `build.problems()` refuses `sender.enabled: true` unless
`morning_note.enabled` is true and the site URL is set. `sender.canary_only: true` limits recipients to
the subscriber ids listed (comma separated) in `MORNING_NOTE_CANARY_IDS`, an environment secret of the `note` job, so
the first live days reach only the team's own addresses. Never subscriber metadata: the public form writes it. With
`canary_only` true and no list, the run sends to nobody ("no-canary", exit 0) and makes no provider call.
**Shipped `canary_only: false` (Brian, 2026-11-16: no canary week; the note goes to every confirmed subscriber
once he approves the sample note).** The canary path stays built and tested for later trials.

```
morning_note:
  sender:
    enabled: false
    provider: buttondown
    api_base: https://api.buttondown.com/v1
    mode: stamp              # stamp | ids, set by the T4.0 probe
    send_at: "07:00"         # site_timezone
    latest_send: "10:00"
    max_editions: 80
    max_recipients: 2000
    canary_only: true
    text: {subject: "{site_name} morning note, {date}", why: "...", open_site: "..."}
```

### As built (T4.1 to T4.4, 2026-11-10; no provider client yet)
- **A disabled sender plans nothing.** With `sender.enabled: false`, `python -m sender plan` writes a `plan.json` with
  `send: false`, `reason: "disabled"`, no edition and no signature, and does not read the note. The daily rehearsal
  is `python -m sender plan --rehearse`: it writes the editions for a person to read and still says `send: false`.
  T4.5's plan step should pass `--rehearse`. While the sender is disabled, a plan error (a missing or wrong note,
  the size ceiling) is printed and the command exits 0: a rehearsal never fails the daily site job.
- **The deliver stage reads its limits from the repository, not from the plan.** `sender/settings.py` reads
  `enabled`, `mode`, `canary_only`, `max_recipients`, `api_base` and the two times from `config/site.yml` with the
  standard library (no PyYAML in the job that holds the key). The plan file comes from the job that parses untrusted
  PDFs, so it may not carry them. Each value in the block must stay one plain value on its own line.
- **`ids` mode: a draft is the claim.** A run that dies between creating a draft and sending it does not send that
  edition on a re-run (never twice before never missed).
- **`max_editions` counts editions that have a recipient**, in the deliver stage, before the first write (exit 2,
  "over-limit"). The plan stage instead caps the size of what it writes (`MAX_PLAN_BYTES`, 32 MB), and the deliver
  command refuses a larger plan file. The fixture's real RPC agenda (27 cases printing 7 districts and 3 wards)
  gives 191 editions and about 2.7 MB of files (plan.json about 1.1 MB), so **T4.5's "under 2 MB" artifact check
  must be raised** (to `MAX_PLAN_BYTES`). `max_editions` was 80 for the canary weeks; it is **400** since
  2026-11-17 (see "Switch-on").
- **Open: the unplaced line** is printed in every edition of a day that has one, as "Body" above says; the preview
  page shows it only to a reader who picked zoning.
- **Every edition says the site is independent and unofficial** (review `render/no-independence-line`): the
  `unofficial.email_line` under the date, the full `unofficial.notice` at the foot, then the note's `support_line`
  and link when the note carries them (the site's note does only while `support_enabled`). The subject may not
  contain "City of", "County", "CMCSS", "RPC" or "official" (`render.AUTHORITY`; the build and the plan both
  refuse it). The From name is the provider account's setting: the site name only, set at go-live (T4.7).
- **Canary ids come from the environment** (`MORNING_NOTE_CANARY_IDS`; review `audience/canary-self-set`), not
  from subscriber metadata, which any subscriber can set through the form. No id is in the repository.
- **The stamp is unguessable** (security `audience/stamp-self-set-race`): `note_edition` is
  `<D>.<key>.<HMAC-SHA256(API key, "<D>.<key>")[:16]>`, since `<D>.<key>` alone is computable from the public
  `morning/<D>.json`. It is deterministic, so a re-run writes and filters the same value; do not rotate the key
  between a day's first run and 7:00 (the scheduled emails would match nobody). `stamp` mode refuses to run without
  the secret, or with one under 32 bytes, and tries nothing in its place ("no-secret", exit 2; security Low (b)). `ids` emails carry `<D>.<key>` only (no filter reads it).
- **The deliver stage checks each body** (security `plan-untrusted/body-unchecked`, M3) against render's exact
  output, not by parsing HTML: since note/sunrise (2026-11-22) the exact opening tags of `common.TAG` and `LINKS`,
  one construct per line, as "Email body forms" above lists; the body ending in a complete line and a newline. Text holds no raw markup character
  (`common.MARKUP`, braces included) and only the references render writes; read as a reader sees it, it holds no
  `www.`, no `://` and no dot between two word characters (`evil.example/login`; CJK and full-width dots too),
  which render breaks with a zero-width space (`common.ADDRESS`). Each `href` is one https URL on a host in
  `morning_note.sender.link_hosts` (read from the repository). The plan stage runs the same `body_ok` on every
  edition it writes, so a render/deliver gap fails the plan (the rehearsal's warning while the sender is off), and
  `clean()` drops format characters before it collapses whitespace (render/clean-order). The plan stage links only to the
  same hosts (sources, site pages). `link_hosts` ships with the collectors' source hosts only; the build refuses
  `enabled: true` until it also holds the site's host. The support link is allowed as exactly the top-level
  `support_url` (`Settings.link_urls`, read by the stdlib reader and held to parity), never as its host: anyone can
  host a page on `buymeacoffee.com` (security Low (a)). Unverified: whether any government source host has an open
  redirect that would let an allowed-host link land elsewhere; check before go-live (T4.5).
- **Each stamp write re-reads that subscriber first** (security L2): `Provider.subscriber(id)` just before the
  write; someone whose type or tags changed since the listing is not stamped (no email today). The probe showed the
  PATCH **replaces** the metadata, so the write is exactly `{"note_edition": <stamp>}` and the adapter refuses any
  other object (sender/stamp-write-replaces, 2026-11-17).
- **A stray stamp stops a `stamp` run** (review `audience/stamp-self-set`): before any write the deliver stage exits
  2 ("stray-stamp") if any subscriber holds exactly one of today's stamps and is not in that edition's audience. Any
  other value is ignored (the filter does not match it), so one subscriber cannot stop every send. The check reads
  every row of the listing whatever its `type` (security L3): the filter may also reach paying, gifted or trial
  subscribers, who are never recipients here (there is no paid tier; such a subscriber gets nothing, never a
  wrong email). The T4.0 probe should confirm which types a filtered email reaches. The T4.0 probe also checks that the public form
  does not accept `metadata__note_edition` or `metadata__canary`.
- `--live` (2026-11-11, T4.4 adapter): the adapter `sender/buttondown.py` exists. `deliver --live` with `sender.enabled` false
  in the repository's config is a dry run that says why, with a fixed `::warning`, and exits 0. With it true, a
  missing or malformed `BUTTONDOWN_API_KEY` exits 2 with a fixed message naming the variable, never its value. The key is also the stamps' HMAC secret. `sender.enabled` stays
  false until T4.8 (the security review of the adapter and the workflow job) passes. The adapter's assumptions about
  response shapes are listed as "Verify in T4.0 probe" in `docs/tasks/morning-note.md` T4.4. Each fails closed.

### Workflow changes (`.github/workflows/daily-update.yml`)
- `update` job: after "Site checks", `python -m sender plan --date <D> --site build/site --out build/morning-send`,
  then upload `build/morning-send` as artifact `morning-send` (2 days). No secret; this job still parses untrusted PDFs.
- new `note` job: `needs: [update, deploy]`; `if: github.event_name == 'schedule' && vars.MORNING_NOTE_SEND == 'true'
  && github.ref == 'refs/heads/main'`; `environment: morning-note` (secret scoped to it, deployment branch `main`
  only); `permissions: contents: read, pull-requests: read` (as built: issues are opened by the separate
  `note-failed` job); timeout 15 minutes. Steps (as built): mask the canary ids, check out this run's `github.sha`
  (not the update job's commit, security L6) with `persist-credentials: false`, the stale-rerun and PR checks
  (main-protect-invariant.md), set up Python with no pip step, download `morning-send`, validate it
  (one `plan.json` and `edition-*` files only, regular files, under `MAX_PLAN_BYTES` in total (as built; was 2 MB), schema and field types checked, every link
  on the site origin or an https source), run the sender's `deliver --plan ... --live` (as built: `python -I -S -c` on a digest-checked copy of `sender/*.py`
  and `config/site.yml` staged from git objects; docs/architecture/main-protect-invariant.md). The key is passed as
  `env:` on that one step only. On failure, the same one-issue step as the other jobs, with a fixed text.
- A manual run (`workflow_dispatch`) never sends.

### Privacy (no personal data in the repo or the logs)
- The repository is public, so its Actions logs and artifacts are public. The `note` job uploads no artifact.
- `buttondown.py` never logs a request or response body, a subscriber id or an address. An error prints the method,
  the path template (`/subscribers/{id}`) and the status code. No `set -x`; no debug flag that prints payloads.
- The run prints totals only: editions sent, recipients in total. Never a per-edition count or a signature, since
  "1 recipient: contracts, district 7, ward 3" could point at a person.
- The address is dropped at the adapter boundary (step 4) and no test fixture holds a real one (`example.org` only).
- Sign-up, double opt-in, unsubscribe, bounces and the stored list are the provider's. We hold no copy.

### Buttondown: verified and assumed
Read from docs.buttondown.com and buttondown.com/pricing on 2026-11-10. Nothing was tested against an account (there
is none), so "verified" means "the public documentation says so".

| Fact | Status |
|---|---|
| Base `https://api.buttondown.com/v1`; header `Authorization: Token <key>` | verified (api-authentication) |
| Keys can be scoped per area (`subscriber_access`, `email_access`, `sending_access`, ...; write, read or none); the primary key is always full access | verified (api-authentication) |
| 600 requests a minute on every endpoint; 429 with `Retry-After`; `X-RateLimit-*` headers on every response | verified (api-rate-limits) |
| `POST /v1/subscribers` is capped at 100 a day (answers 400 beyond it). We never call it; sign-ups go through the hosted form | verified (api-rate-limits) |
| `X-Idempotency-Key` on any request, a string up to 200 characters; a repeat returns the first response | verified (api-idempotency-keys). How long a key is remembered: not stated |
| `POST /v1/emails` fields: `subject`, `body`, `status`, `publish_date`, `filters`, `metadata`, `archival_mode` (`disabled` keeps it off the public archive) | verified (api-emails-create) |
| Creating an email through the API "will instantly trigger sending"; a `scheduled` email goes out at its `publish_date` | verified as documented (api-emails-introduction). Which `status` to post for an immediate send: **assumed**, probe |
| Filter shape `{"filters": [{"field": "subscriber.metadata.<key>", "operator": "equals", "value": "..."}], "groups": [], "predicate": "and"}` | verified for segments (api-segments-create). That an email's `filters` takes the same rule: **assumed**, probe. The field name for a tag and any operator but `equals`: not found |
| `POST /v1/emails/{id}/send-draft` takes `subscribers` (ids) or `recipients` (addresses) | exists, but **only sends a "[PREVIEW]" to the account owner** and the email stays a draft (probe 2026-11-16): `ids` mode cannot work |
| Hosted form: POST to `https://buttondown.com/api/emails/embed-subscribe/<username>` with `email`, `embed=1`, `tag`, `metadata__<key>` (the key must be set up in the account; multi-select allowed); must be a plain form post, not `fetch` | verified (building-your-subscriber-base). **Probe 2026-11-16:** a new address with `metadata__` fields got 400 on the free plan, so the form posts `tag` fields only. Several `tag` fields adding several tags, and a new tag name created on the fly: **assumed**, check at the first real sign-up |
| Subscriber `type` values include `regular`, `unactivated`, `unsubscribed`; API-created subscribers are double opt-in by default | verified (api-subscribers-create). Double opt-in for **form** sign-ups: not stated on the pages read, verify in the account |
| Listing subscribers can filter by metadata; listing emails cannot | verified (api-filtering). So the day claim reads `metadata` from the email list client-side; list order and date filters: **assumed**, probe |
| Tags are a paid feature; the pricing page shows "Tagging & segmentation" as a +$9 a month add-on, and the first 100 subscribers free | as shown on 2026-11-10. **Probe 2026-11-16 on the free plan:** a metadata-filtered email reached exactly its one subscriber and no API call was refused as paid; `/tags` answered 200. Whether the free plan keeps tags from a form sign-up: **assumed**, first real sign-up. Brian will not pay (2026-11-16) |
| Updating a subscriber's metadata keeps other keys | **no: it replaces** (probe 2026-11-16) |
| The provider adds an unsubscribe link to every email; open and click tracking can be turned off | **assumed**, verify in the account (precondition 3) |
| Template variables in a body (`{{ ... }}`) are evaluated by the provider | **yes** (probe 2026-11-16: `{{ subscriber.email }}` showed the address), which is why titles are neutralised |

Consequence for the sign-up form (superseded 2026-11-17, see "Switch-on"): it was `metadata__lists`; the probe showed
the free plan refuses `metadata__` fields on a new sign-up, so lists, district and ward are Buttondown tags.
Consequence for the copy: `page.about` says "at 7:00 AM"; with `ids` mode the mail leaves when the run ends (about
4 AM). Change it to "by 7:00 AM", which is true in both modes.

### Launch preconditions (before `morning_note.enabled` or `sender.enabled` is set to true)
From `docs/reviews/security-review-morning-2b4796b.md`:
1. Finding 1 (medium, blocks enabling): the "never sent anywhere" sentences in `method.html.j2:20` and
   `index.html.j2:26,37` depend on `note.enabled`; Method gains a Morning note paragraph (what is sent, to whom, how
   to unsubscribe, `privacy_url`); a test proves an enabled build has neither sentence; `seats.js` header updated.
2. Finding 3: the form shows the seat values it will send, or a visible ticked "include my saved seats" box.
3. Finding 2, at account setup, recorded in `docs/platform-facts.md`: double opt-in on for form sign-ups, open and
   click tracking off, and `sent_line` extended ("...and, like any website, your IP address").
4. Findings 4 and 5: source URLs checked with `build._is_https_uri` before they become links (the sender's renderer
   does this too), `site_checks` fails on any other href scheme, `form_origin()` validates its own input. Commit
   1d638db on `claude/sqv6p9-morning-sec` claims these; its security delta is pending and it is not on this branch.
5. Item 6: one real form submit on the live origin, to see that the provider's redirect stays within the CSP
   `form-action` origin (fix on the provider's side, never by widening the CSP).
6. "Not checked: the sender job and API key": a fresh security review of T4 before the workflow job merges.
Added by this design:
7. T4.0 probe done with team addresses only, and `sender.mode` set from it (done 2026-11-16 on the live newsletter:
   `stamp`; `docs/platform-facts.md` "Morning note provider"). The form **does** accept `metadata__note_edition` and
   `metadata__canary` on an existing subscriber; accepted, with the reasons in "Switch-on" below.
8. A scoped API key (not the primary key): email and sending write, subscribers write for `stamp` or read for `ids`,
   every other area none. Stored only as the `morning-note` environment secret.
9. Sending domain DNS (SPF, DKIM) set by Brian; one canary week with `canary_only: true` before he widens it.
   **Changed 2026-11-16 (Brian):** no canary week, and no custom sending domain on the free plan (the note goes
   from Buttondown's own sending address); the runbook section 5 records both calls.

### Switch-on: tags, and the security notes (2026-11-17)
What changed for the switch-on PR, after the T4.0 probe (`docs/platform-facts.md` "Morning note provider"):
- **Form:** `form_fields: {email: email, lists: tag, district: tag, ward: tag}`. Each list box posts
  `tag=note-<key>`; the two seat fields post `tag=note-district-<n>` / `tag=note-ward-<n>` (the script adds the
  number to the field's `data-tag-prefix`, only while "Include my saved seats" is ticked, as before). No field
  is a `metadata__` field; `morning.problems()` refuses `form_fields` that name anything but `tag` for lists and
  seats, or `tag`/metadata for the email. The tag names are fixed in `sender/common.py` (`list_tag`,
  `seat_tag_prefix`, `read_tags`), shared by the form and the sender.
- **Sender:** reads lists and seats from tags (`deliver.recipient`), never from metadata; the adapter keeps `tags`
  (a list of names, else the run fails closed) and drops the rest. A `stamp` write is exactly
  `{"note_edition": <stamp>}`; `Recipient` no longer holds metadata.
- **Config:** `enabled: true`, `form_action` `.../embed-subscribe/daylight`, `sender.enabled: true`, `mode: stamp`,
  `canary_only: false`, `alerts.site_url` set. `privacy_url` checked 2026-11-17 (platform-facts).

Notes for the security review (each is a judgment call unless marked):
- **(a) The form can set any tag, on anyone's existing address.** Anyone who knows a subscriber's address can post
  the form with it and add tags: more lists (more mail they did not pick), or a second district or ward tag. The
  sender ignores every tag it did not define, and two district (or two ward) tags count as none: a forged seat on
  someone with no seat gives them that seat's zoning (unwanted mail, like a forged list); on someone with a seat it
  cancels both (less zoning). A tag cannot add a recipient: only `type == regular`
  (double opt-in confirmed) subscribers are mailed, and every email carries the provider's unsubscribe link.
  Whether a form post can *remove* tags is **unverified** (if it replaces tags, an attacker could empty a victim's
  lists: they then get nothing). This is the same class as before: with metadata, the probe showed a re-submit
  already rewrote a confirmed subscriber's fields. No email names a subscriber or their seats.
- **(b) The form can set `metadata__note_edition` on an existing subscriber** (probe: yes). The stamp is
  `<D>.<key>.<HMAC-SHA256(API key, "<D>.<key>")[:16]>`: 64 bits keyed with a secret that never leaves the note job,
  so a forged value matches no email's filter. The stamp is not in any email body, URL or public file: it is only in
  the provider's metadata and the scheduled email's filter, which only the account sees (no preferences page;
  archival disabled). Templates are on, but titles are neutralised and no body references metadata. Each send's
  PATCH **replaces** the whole metadata object with the stamp alone (probe: PATCH replaces), so whatever the form
  wrote before the run is gone for the stamped subscribers. Left open: a form post *after* the stamp and before
  7:00 can overwrite one subscriber's stamp with junk (they miss that day's email; the attacker needs their
  address), and the stray-stamp check reads only the default listing, which leaves out unconfirmed sign-ups; a
  stamp can only reach such a row by the sender writing it to a subscriber who then changed type, and the
  provider does not mail an unconfirmed or unsubscribed address.
- **(c) The sender ignores what it did not define:** tags other than `note-<list>`, `note-district-<n>`,
  `note-ward-<n>` (exact names, lower case, numbers in range, no leading zero); every metadata key except
  `note_edition`, which only the stray-stamp check reads. Tests: `test_hostile_tags_are_ignored_not_passed_on`,
  `test_metadata_never_names_an_audience`, `test_a_metadata_write_other_than_one_stamp_is_refused_before_any_request`.
- **`canary_only: false`:** the first live morning reaches every confirmed subscriber. Bounds that stay:
  `max_recipients` 1000 (was 2000) and `max_editions` (a run over either sends nothing, loud).
- **`max_editions` 400 (was 80; sender/max-editions-busy-day).** A busy real day plans up to 191 editions (day D's
  RPC agenda), so with the whole list on and many shapes, 80 would have sent nothing that morning. Every edition
  with a recipient has at least one, so the editions a run creates are never more than its recipients; 400 is
  about twice the busiest day measured and is a guard against a runaway, not a daily limit. Based on: Buttondown's
  documented limit of 600 requests a minute on every endpoint (table below; the client paces 5 a second and
  honours a 429's Retry-After); no per-day or per-run email limit in the docs read on 2026-11-10 or seen in the
  probe (none known, not proven absent); and run time: an email per edition plus 2 requests per stamped subscriber
  (re-read, stamp), so a run at the cap is at least 1,200 requests, about 4 minutes at 5 a second, inside the note
  job's 15-minute timeout and the 07:00 to 10:00 window. Tests: `test_a_190_edition_day_is_sent_whole_with_the_
  shipped_limits` (both modes, each edition once, a second run sends nothing) and `test_a_busy_day_cut_off_part_
  way_is_finished_by_a_rerun_without_sending_twice`. **Run-time budget (sender/run-time-budget):** 2 listings, 1
  request per email and 2 per stamped recipient, so at both caps (2 + 400 + 2 x 1000) x 0.2 s = 8 minutes, inside
  the job's 15; the test asserts it from the workflow file and the client's pace. `max_recipients` was 2000
  (about 14 minutes); the free plan stops at 100 subscribers anyway.
- **Review fixes (2026-11-17, review of a23427e; branch `r2-note-fix`):**
  - *audience/stamp-rerun-false-stray (L1):* the stray check (`_strays`) skips a holder whose held edition is
    already created (`done`: a re-run after a stamped subscriber changed lists) or has nobody to mail this run. A
    holder of a not-yet-created edition's stamp who is in another not-yet-created edition's audience is stamped for
    that edition before any email is created (written over); otherwise, or if they changed again, the run stops.
    Superseded for a created edition by the invariant below (delta review of 55c097a).
  - *render/archival-not-echoed (L7):* the adapter keeps `archival_mode`; the echo check compares it when the
    stored email carries it (it must then be `disabled`). That the create answer carries it is unverified.
- **Invariant: one stamp, one email a day (audience/ family, 2nd hit; never-twice over never-missed).** A
  subscriber who holds the stamp of an edition already created today is never placed in another edition that day;
  they get only the edition they hold, or nothing. Consumers, each keeping it:
  1. `_claim`: which editions are created (`done`, the plan's own emails by note and plan digest);
  2. `held_stamps`: who holds which of today's stamps, every row of the listing, whatever its type;
  3. `run`, `by_key`: holders of a created edition's stamp are dropped from every audience before any write;
  4. `_strays`: a stray of a created edition is skipped; one of a not-created edition is written over or stops the run;
  5. `stamp()`: the only stamp write (re-read first; the idempotency key carries the stamp held, sender/stamp-idem-replay);
  6. the edition loop: a `done` edition is never created again, and an edition is created only after its stamps;
  7. the provider's filter (`stamp_filter`), which decides at send time who holds the stamp;
  8. `buttondown.set_metadata`: the write replaces the whole object with the one stamp.
  Accepted (nit 4): a holder of a created, still-scheduled edition who has since unticked every list still gets
  that morning's email (their stamp is never removed: no write but a stamp exists); from the next day, nothing.
  - *sender/tags-silent-zero (CR2):* confirmed subscribers of whom none carries a `note-` tag end the run with
    exit 2, status `no-tags`, totals only.
  - *sender/claim-listing-unbounded (CR4):* the claim lists `GET /emails?creation_date__start=<yesterday>`. The
    listing is oldest first (probe), so stopping at old rows is impossible. Relied on: the probe's call of that
    filter answered 200 and kept all of the day's emails; that it drops older rows is unproven. Ignored, it is the
    whole history: still correct, bounded by `MAX_PAGES`.
  - *sender/claim-plan-identity (CR9):* every email's claim metadata carries `note_plan`, `deliver.plan_digest`
    (sha256 over the note digest, every edition's key, subject, body and entry ids, and the signatures). An email
    of the day is ours only with both digests, so another plan of the same note claims nothing of ours.
  - *sender/tags-seat-change (CR5):* the Method page says how to change lists or seats (unsubscribe, sign up
    again; config `page.method_change`), which depends on runbook check 4a.
  - CR6 an entry with no body name reads "<date> <meeting>"; CR7 the preview page prints the meeting day as the
    email does ("November 9, 2026"); CR8 the form posts Buttondown's hidden `embed=1`.
- **Not changed and still open:** the open-redirect check of the government source hosts in `link_hosts`
  (runbook section 4 item 2).

### Threat points for the security review
1. **The key.** Scope, storage in an environment limited to `main`, exposure to exactly one step, no pip install and
   no third-party action beyond the pinned checkout and download in that job, no run on pull requests or manual runs.
2. **Subscriber access.** `stamp` needs subscriber write: a bug could change or blank metadata for the whole list.
   Check that the adapter can only PATCH `metadata`, writes the whole object back, never creates, deletes or changes
   `type`, and that `max_recipients` and `canary_only` bound the damage. Weigh this against `ids` (read only).
3. **Untrusted text in the body.** Record titles come from parsed PDFs. HTML, Markdown and provider template syntax
   in a title; a hostile `source.url`; a very long title. The plan artifact crosses from the job that parses untrusted
   PDFs to the job that holds the key: is its validation enough, and can anything in it steer the request (host,
   path, headers, filter value)?
4. **Wrong audience.** A filter that matches more people than intended (an empty or malformed filter means everyone);
   a stale stamp; a signature parsed from hostile metadata (a subscriber can post any `metadata__district` through the
   public form). Wrong type handling, so an unconfirmed address is mailed.
5. **Double send and replay.** Re-run of a failed job, re-run of an old run on a later day, two runs in one morning,
   a listing call that fails or is paged short, clock and timezone edges around 7:00 and the DST change.
6. **Personal data in public logs.** Exception text and tracebacks that carry a response body, the HTTP library's
   debug output, per-edition counts, subscriber ids in URLs, the failure issue's text.
7. **Sending when we should not.** Backfill day, quiet day, a first run after a long outage, a note built from a
   fixture, sender enabled while the form is off.
8. **Sign-up abuse** (carried over from finding 2): someone else's address entered in the form; double opt-in is the
   only control, so it must be confirmed on.
9. **Neutrality.** Subject and connective text are config and scanned; the email must not add wording the site does
   not carry, and must treat every body and seat the same way.

### Risks
- Three provider behaviours the design rests on are unverified (email filters on metadata, send-draft semantics, the
  email list as a claim record). T4.0 exists to settle them before any delivery code is written; if both modes fail
  the probe, come back to the architect, do not improvise a third.
- GitHub's scheduler can start late. With `stamp` the email still leaves at 7:00; past `latest_send` the day is skipped.
- The free tier ends at 100 subscribers (as shown today). Past that it costs money: Brian's call, not the sender's.
