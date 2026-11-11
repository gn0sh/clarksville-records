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
- every zoning entry carries `case`: the case number in its one comparable form (rpc_minutes.link_key), `null` on
  other entries; `unplaced_zoning` counts distinct cases (a case on an agenda and in the minutes is one case).

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
| `python -m sender deliver` | new `note` job, `needs: [update, deploy]` | `api.buttondown.com` only; `BUTTONDOWN_API_KEY` | Reads only the plan file; talks to the provider. Standard library only: no `pip install` and no `sitegen` import in the job that holds the key. Without `--live` it prints what it would do and opens no connection. |

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
Signatures with the same non-empty id list share an edition; its key is the first 12 hex of
`sha256(date + "\n" + ids joined by "\n")`. Signatures with an empty selection are left out: those people get nothing.

`build/morning-send/<D>/plan.json` (and `edition-<key>.html` / `.txt` beside it for a person to read):
```
{"schema": "morning-send/1", "date": "2026-11-11", "note_sha256": "<of the note file>", "timezone": "America/Chicago",
 "send": true, "reason": "ok", "send_at": "2026-11-11T07:00:00-06:00", "latest_send": "2026-11-11T10:00:00-06:00",
 "editions": [{"key": "3fa9c1d2e07b", "subject": "...", "body": "<html>", "entry_ids": ["rpc/item/..."]}],
 "signatures": {"zoning|7|-": "3fa9c1d2e07b", "budget,zoning|7|3": "91c0..."}}
```
The plan is a pure function of the note and config: two runs on the same note give byte-identical files. It holds
no subscriber data, so it is safe as a build artifact in a public repository.

Body (`render.py`): the site name and date, then per picked list its config label and its entries: body name,
`recorded`, the verbatim title, a link to the site page (`alerts.site_url` + `href`) and the source link; then
`unplaced_text` when set; then one config line saying why the reader got this. Rules:
- every title and URL is HTML-escaped, and `{{`, `{%` and a leading `---` are neutralised, because the body goes
  through the provider's own template and Markdown step (a record's title is untrusted text);
- links are only `site_url` pages and `source.url` values that pass `build._is_https_uri`; anything else drops the link;
- every word that is ours comes from `morning_note.sender.text` in config and runs through the `BANNED` scan with
  `morning.own_text`; no official's name outside a verbatim title; no summary. The email adds nothing the preview
  page (`morning/index.html`) does not already show;
- the unsubscribe link and footer are the provider's; we add no unsubscribe mechanism of our own.

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
   - the listing fails, is cut short or cannot be read: send nothing, exit non-zero. **Fail closed.**
4. **Recipients**: page through subscribers, keep `type == "regular"` (confirmed; `unactivated`, `unsubscribed` and
   the rest are never mailed), and reduce each at the adapter boundary to `(id, lists, district, ward)`. The address
   and every other field are dropped there and never reach the rest of the program. Lists not in `LIST_KEYS`, and
   district or ward values that are not whole numbers in range, are ignored (treated as not set). More than
   `sender.max_recipients`: stop, send nothing.
5. **Per edition** (in key order): the subscribers whose signature maps to it. None: skip, no email is created.
   Otherwise deliver by the mode the T4.0 probe selected:
   - `stamp` (preferred): set each recipient's metadata `note_edition` to the stamp `"<D>.<key>.<mac>"` (as built; always writing back the whole
     metadata object, so district and ward survive), then create one email with `filters` = `subscriber.metadata.
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
`morning_note.enabled` is true and the site URL is set. `sender.canary_only: true` (the default) limits recipients to
the subscriber ids listed (comma separated) in `MORNING_NOTE_CANARY_IDS`, an environment secret of the `note` job, so
the first live days reach only the team's own addresses. Never subscriber metadata: the public form writes it. With
`canary_only` true and no list, the run sends to nobody ("no-canary", exit 0) and makes no provider call.

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
  must be raised** (to `MAX_PLAN_BYTES`). The shipped `max_editions: 80` is kept for the canary weeks; revisit it
  before `canary_only` goes false.
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
  output, not by parsing HTML: `<h1>` first, every line one of render's forms (`<h1>T</h1>`, `<h2>T</h2>`,
  `<p>…</p>`, `<ul>`, `</ul>`, `<li>…</li>`, inside them only `<br>`, `<strong>T</strong>`, `<a href="U">T</a>`),
  lists closed, the body ending in a complete line and a newline. Text holds no raw markup character
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
- **Each stamp write re-reads that subscriber first** (security L2): until the T4.0 probe shows that a metadata
  update merges keys, the write sends the whole object, so it is built from `Provider.subscriber(id)` read just
  before the write, not from the listing. Someone whose type or shape changed since the listing is not stamped (no
  email today). If the probe shows the provider merges, the adapter sends only `note_edition` instead.
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
  only); `permissions: contents: read, issues: write`; timeout 15 minutes. Steps: check out the commit the update job
  built on with `persist-credentials: false`, set up Python with no pip step, download `morning-send`, validate it
  (one `plan.json` and `edition-*` files only, regular files, under `MAX_PLAN_BYTES` in total (as built; was 2 MB), schema and field types checked, every link
  on the site origin or an https source), run `python -m sender deliver --plan ... --live`. The key is passed as
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
| `POST /v1/emails/{id}/send-draft` takes `subscribers` (ids) or `recipients` (addresses) | verified it exists (api-emails-send-draft). Whether it is a real send with the unsubscribe link or a test send: **assumed unknown**, probe |
| Hosted form: POST to `https://buttondown.com/api/emails/embed-subscribe/<username>` with `email`, `embed=1`, `tag`, `metadata__<key>` (the key must be set up in the account; multi-select allowed); must be a plain form post, not `fetch` | verified (building-your-subscriber-base). Matches the seam's `form_fields` |
| Subscriber `type` values include `regular`, `unactivated`, `unsubscribed`; API-created subscribers are double opt-in by default | verified (api-subscribers-create). Double opt-in for **form** sign-ups: not stated on the pages read, verify in the account |
| Listing subscribers can filter by metadata; listing emails cannot | verified (api-filtering). So the day claim reads `metadata` from the email list client-side; list order and date filters: **assumed**, probe |
| Tags are a paid feature; the pricing page shows "Tagging & segmentation" as a +$9 a month add-on, and the first 100 subscribers free | verified as shown on 2026-11-10. Whether metadata filters (the `stamp` mode) fall under that add-on: **assumed yes**. Brian owns the spend (hard stop 3) |
| Updating a subscriber's metadata keeps other keys | **assumed no** (we always write the whole object back), probe |
| The provider adds an unsubscribe link to every email; open and click tracking can be turned off | **assumed**, verify in the account (precondition 3) |
| Template variables in a body (`{{ ... }}`) are evaluated by the provider | **assumed yes**, which is why titles are neutralised |

Consequence for the sign-up form: set `form_fields.lists` to `metadata__lists` (a multi-select metadata key) instead of
`tags`. The sender reads lists from metadata, the form works without the tags add-on, and only `stamp` mode's filter
may need it. Config only; the seam already takes any plain field name.
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
7. T4.0 probe done on a test newsletter with team addresses only, and `sender.mode` set from it. It includes: the
   public form does not accept `metadata__note_edition` or `metadata__canary` (audience/stamp-self-set).
8. A scoped API key (not the primary key): email and sending write, subscribers write for `stamp` or read for `ids`,
   every other area none. Stored only as the `morning-note` environment secret.
9. Sending domain DNS (SPF, DKIM) set by Brian; one canary week with `canary_only: true` before he widens it.

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
