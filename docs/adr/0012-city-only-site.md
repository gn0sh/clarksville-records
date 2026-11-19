# ADR 0012: A city-only Daylight site (no county, at-large council)

Status: proposed (software-architect, 2026-11-18), feature `city-only-site`, Daylight template milestone 2.
Amended 2026-11-19: Salem, OR replaces Murfreesboro as the first city (the owner's switch, after Murfreesboro's host
blocked our fetcher); see "Amendment A1: Salem first" below. Decision 5 gains the member-gap rule and its invariant.
Murfreesboro stays a draft city and the at-large test case.
Builds on ADR 0007 ("Milestone 2"). Must fit ADR 0011 (data off `main`), which is being built now. Design only:
nothing here collects, deploys or changes product code. Tasks: `docs/tasks/city-only-site.md`.

## Context
Today `sitegen` builds one shape of site: the Montgomery County Commission is the primary body (top-level
`officials.html`, `meetings/`, `votes/`, `items/`, `districts/NN.html`, the address box), and councils sit beside it
under their own folder (`city/`, `sitegen/council.py`). `sitegen/config.py` reads `config/site.yml` at import time,
and some county words are code literals (`views.landing_doors` "County Commission", the Officials lede "by district
number"). The first new city, Murfreesboro, TN (`config/cities/murfreesboro-tn/`), has no county body and an
all at-large council. It reads from a CivicPlus Agenda Center, the reader Clarksville used for 2016-2024.

Facts this design rests on, verified or not (none of them changes the data model; each unverified one is a
`cities check` item, so the city stays NOT READY until it is recorded):

| Fact | State |
|---|---|
| "All members of the Murfreesboro City Council are elected at-large" | given in the brief; **source page unverified** (needed: `seat_basis` below) |
| Printed titles "Mayor", "Vice Mayor", "Councilmember"; about 7 members | **unverified** (no minutes read) |
| The Vice Mayor title moves between members | **unverified** ("likely"); the design works either way |
| Host `www.murfreesborotn.gov`, Clarksville's search URL pattern | **unverified** (`agenda_center.yml`) |
| robots.txt and terms for that host | **not checked**; nothing may be collected until they are |
| GitHub Pages serves one custom domain per repository | GitHub docs; ADR 0007 and the template plan rely on it |
| A public repo's attestations can be verified from another repo's workflow with its own `GITHUB_TOKEN` | **unverified**; checked before task D3 (fallback in decision 8) |

## Decisions

### 1. `--city <slug>` picks the settings, through the registry; Clarksville is the default and its build is unchanged
- `python -m sitegen --city <slug>` (default `clarksville-tn`). With `--city`, `--facts` defaults to
  `data/localities/<slug>/facts.json` and `--out` to `build/<slug>/site`. Without `--city`, the CLI behaves as today
  (`--facts` and `--out` required), so the daily workflow's command line does not change. *(T3 build note:
  the defaults apply to a new city only. `--city clarksville-tn` still requires both, because its county facts are
  `data/facts.json`, not `data/localities/clarksville-tn/facts.json`, which is the council's.)*
- `sitegen/config.py` reads settings once, at import, as now. It gets the slug from `DAYLIGHT_CITY` (default
  `clarksville-tn`). `sitegen/__main__.py` parses `--city` before it imports `config` or `build` and sets the
  variable; if both are set and differ, it exits 2. `config.CITY` records the slug, and `build()` refuses to run
  when the caller asks for another city ("sitegen was loaded for X; run a new process for Y"). This copies the
  pattern already used for `RECORDS_SITE_URL` and `RECORDS_BUILD_TARGET`.
- `config.py` calls `cities.registry.load_city(slug)`:
  - **Clarksville (legacy, `settings: config/site.yml`):** `SITE` is `yaml.safe_load` of that file, exactly as
    today. It is not the merged `site_settings()` dict, so key order and values stay the same.
  - **A new city:** `SITE = registry.site_settings(city, brand)`. It is built in this order: the place-free keys of
    `config/site.yml`, then the city's own `config/cities/<slug>/site.yml` (new city key `site_file`), then the fields in
    `city.yml` (timezone, `today_place`, `sky_place`, `geocoder_places`, `district_lookup`), then the brand. `live`
    is `status == "live"`, never typed twice. `alerts.site_url` defaults to `https://<domain>/`.
    The place-free keys are a named list of dotted paths, `registry.SHARED_SITE_KEYS`. Examples:
    `unofficial.notice`, `unofficial.tag`, `unofficial.short`, `unofficial.email_line`, `days`, `video_link`,
    `video_label`. Mixed keys are split by path. For example, `unofficial.bodies` and
    `item_types` (the rezoning prefixes `CZ-` are the county's) come from the city's own file. `tests/test_cities.py`
    fails if a shared path holds a Clarksville, Montgomery, CMCSS or RPC literal. One copy, no drift, and no edit to
    `config/site.yml`. *(T2 build note: a city's site file, or its `site:` block, that sets a shared path, a brand
    key or a `city.yml` field (`site_timezone`, `today_place`, `live`, ...) fails, naming the key.)*
- `config.PRIMARY`, one normalised dict that names the site's primary body: `key`, `name`, `label`,
  `meeting_title_body`, `record`, `kind_labels`, `held_sentences`, `seats` (`districts` | `wards` | `at_large`),
  `titles`, `member_title` (T5: Clarksville `[]` and None; seat labels read them).
  For Clarksville it is filled from today's keys (`county_key`, `county_body`, `meeting_title_body`, ...). Those
  values are equal to today's literals, so the bytes are equal. Code and templates that print a county word
  today read it from `PRIMARY` instead.
- **Guard (problem family `city-only/clarksville-identical`):** a golden test builds Clarksville from the pinned
  snapshot (`tests/pinned_data.py`) and from the test fixture, with a fixed `today`, and compares a digest of the
  whole output tree (sorted path + sha256) with one recorded at the base commit before any sitegen change (task
  T0). The build is also checked with `--city clarksville-tn`. Every M1 PR also pastes an empty `diff -r` of a
  build from one pinned data tree, before and after.

### 2. In a city-only site the council is the primary body, built by the existing top-level path
A city whose `site.yml` has a `primary:` block is built with that body as the primary index (`views.Index`), at the
top-level paths the county uses today. It is not built under a council folder. Reasons:
- The top-level path is already a complete site for one body: nav (Votes, Meetings, Officials, Items), search,
  feeds, Today, stats, About, data export. A fixture build already runs it with no councils, RPC, finance,
  committees or roster. So the city-only site comes from switching county extras off, not from making `ix`
  optional in about 15 view functions.
- The council's own rules travel with it through `PRIMARY`: city meeting kinds (`kind_labels`), per-check held
  sentences (`held_sentences`) and seat records (decision 5). `Index(facts, seat_rows, kind_labels=...,
  held_sentences=..., seat_wording=...)` takes them. The defaults are today's county values.
- One page per meeting (the county path) is fine for a launch year (about 40 meetings) on Pages (cap 3000 files).
  The existing preview fallbacks (transcripts off, then export off) still apply. Backfill growth is a risk (see
  Risks).

`primary:` block (in `config/cities/<slug>/site.yml`; every value marked `UNVERIFIED` until it is checked):
```yaml
primary:
  key: council                     # search body key ("b") and the export's body folder
  name: Murfreesboro City Council  # as the minutes print it (UNVERIFIED)
  label: City Council              # menu and door label; also "City Council regular session, May 1, 2026"
  record: {url: https://www.murfreesborotn.gov/agendacenter, label: City of Murfreesboro Agenda Center}
  kind_labels: {regular: Regular meeting, special: Special meeting, work-session: Workshop, other: Other meeting}
  held_sentences: {...}            # the same shape and checks as council.yml (config.load_council's rule)
  seats: at_large
  titles: [Mayor, Vice Mayor]      # printed words that are titles. Never who holds them.
  member_title: Councilmember      # what every official's facts `title` is (UNVERIFIED)
  seat_basis:                      # the official page that says the council is elected at large
    url: UNVERIFIED
    label: UNVERIFIED
    sentence: "Every member of the Murfreesboro City Council is elected at large, by voters across the city."
place_name: Murfreesboro           # header name plate and the named footer lines (decision 9)
```
The registry validates the block: unknown keys fail, `seats` is one of three words, `titles` is a list of plain
words, and `seat_basis.url` is https or `UNVERIFIED`. A `pages` build refuses an `UNVERIFIED` `seat_basis`. A
fixture build may use a fixture URL (`https://example.org/...`).
*(PR #62 review note: a city's file may set only `registry.CITY_SITE_KEYS` (`place_name`, `corrections_log`,
`primary`, `unofficial.bodies`, `item_types`, `alerts.feed_id`/`max_entries`/`topics`); anything else, e.g.
`corrections.github_repo`, `analytics`, geocoder URLs, `alerts.site_url` or `locality`, fails naming the key. Its
paths stay inside `config/cities/<slug>/`, no URL it sets may point at a denied host, and a `pages` build refuses a
city whose status is not `live`.)*

### 3. What a city-only build leaves out, and what it keeps
"Leaves out" means the page is not written, and no menu entry, door, card or link points at it. A test asserts
both halves.

| Piece | City-only build | How it is switched |
|---|---|---|
| `districts/NN.html`, district list, redistricting and swap notes | left out | `PRIMARY.seats != districts` (`district_count` unset) |
| County hub (`switch.bodies.county`), "Show records from" switch, hub cards | left out | no `switch:` in the city's settings |
| County agendas page, county committees, school board page | left out | no `county_agendas`, `county_committees`, `school_board` keys; build defaults are None, not Clarksville paths |
| RPC pages, finance, Bids and awards, capital, city budget | left out | no `rpc:`; no finance file found for the city |
| City committees (`city_committees:`) | left out | key absent |
| Menu entries Finance and Capital projects ("Coming") | left out | a `coming` menu entry is listed only when the settings' `coming:` has its page (Clarksville has both, so it is unchanged) |
| Morning note, its menu entry, the landing "never sent" lines | left out | no `morning_note:` |
| Visitor counter | off | no `analytics.code` (a new GoatCounter site is an account: hard stop 4) |
| Transcripts | none | no transcripts data |
| Kept | Home, Today, Search, Votes/<year>, Meetings, `meetings/<id>`, Officials, `officials/<id>` (+ votes), Items/<year>, Data downloads (one body), Alerts and feeds when `alerts.feed_id` is set, Who runs this, Our rules, Corrections (the city's own log), Method, About, Changes, Stats, Report | |
| Footer | the same footer, with the named lines (decision 9), "Data as of" from the city's sources | |

The settings defaults for the county-only pieces move from "Clarksville's path" to "absent": `config.COUNTY_AGENDAS`,
`DISTRICTS_PATH`, `SEATS_PATH`, `FIN_LOCALITY_PATH` and `COUNCILS` are None or empty for a city without those keys,
and they are unchanged for Clarksville. `operator_person` is checked only when it is set. The corrections log path
comes from the settings (`corrections_log`). For Clarksville it is `config/corrections-log.json` once ADR 0011's B1
has moved it; for a new city it is `config/cities/<slug>/corrections-log.json` (an empty list).

### 4. The front page
In order: the welcome (h1 `purpose` naming the one body, e.g. "Votes and records of the Murfreesboro City Council,
each linked to its source."), the lede, then the **"Who represents you" card** (decision 6), then the "Start here"
doors, then the meetings coming up and the most recent ones, the records search, and the three details. The doors
are built from `PRIMARY.label`: Who's in office (Officials), How they voted (Votes), Meetings and agendas, plus
Search. No door names a body this build does not make. The overview of hub cards is not drawn (there is no switch).

### 5. At-large seats, and titles read from each meeting's record
- **Membership record.** For `seats: at_large`, each member's record is the seat `at-large`: from the first to the
  last meeting whose attendance list prints them, observed dates, with the first and last source page. It is
  `council.ward_rows` with one constant seat instead of a ward number. `min_ward_prints` is 1, because a ward
  misprint cannot happen here. `extend_by_listings`, `held_over` and `unplaced_names` work as they do today. The
  label is `"<member_title>, at large"` (e.g. "Councilmember, at large").
- **Title records (the rotating Vice Mayor).** The collector stores the title each attendance list prints beside
  each name. It goes in the same per-meeting prints file the council collector already writes (`wards.json`, one
  row per printed name: `official_id`, `raw_name`, `meeting_id`, `date`, `source_id`, `page`), with `ward: null`
  and a new key `title` (the printed word from `primary.titles`, or null). Clarksville's rows get no `title` key,
  so its file and site do not change. The name `wards.json` stays (historical). For each title, the build makes
  one record per unbroken run of meetings that print it for the same member: seat `title-<slug>` (`title-vice-mayor`),
  first and last meeting, both source pages, evidence "attendance lists". A new holder printed starts a new
  record and closes the old one at its last print. So a Vice Mayor who changes every year shows as a list of
  records, each linked to the minutes that print it.
- **Never hard-coded.** Settings name which words are titles, never who holds them. The facts `title` of every
  official is `member_title`. `council.title_rows`, which reads `officials[].title`, is not used for at-large seats.
  A test fails if any city config file names an official id or a member's name, or if a title record comes from
  anything except a print. Two members printed with the same title at one meeting: no title record covers that
  meeting, the run log names the conflict (`at-large/title-conflict`), and the meeting page still links the source.
- **Per meeting.** `Index.person(ref, date)` already shows the seat held on the meeting date. For at-large that is
  the title record covering the date ("Vice Mayor"), or else the membership label. A meeting whose list prints no
  title for anyone shows only the membership label: nothing is carried across an unprinted gap, except inside one
  run, which is the existing rule for wards.
- **Member gaps (task T5b; must-fix `at-large/member-gap` from the PR #62 T5 code review).** A membership record is
  not simply "first to last print": a member who leaves and returns years later must not show one unbroken record
  across the gap. Rule: walk the member's prints in date order against the *complete* attendance lists between them.
  A list is complete when every name it prints resolves to an official (no unresolved row in the prints, no
  attendance entry without an `official_id`) and it is not a configured seating. A list "prints" a member when it
  names them present or absent (wards.json holds both). When a member is missing from **N = 2** consecutive
  complete lists, the record ends at their last print before the gap, and their next print starts a new record with
  its own first source page. Incomplete lists inside a gap neither count toward N nor break the streak. One missing
  complete list never splits a record. This mirrors holder_rows' one-list-drop rule (one list is not enough to
  close a record). N is a module constant (`AT_LARGE_GAP_LISTS = 2`), not a setting. The tail (after a member's last
  print, up to L) keeps the existing rule: the record reads "seen to" its last print, or is `held_over` when L's
  list is incomplete. A reprint after a one-list tail gap rejoins the same record on the next build.
- **Short lists (T5b review, `at-large/complete-list-truncated`).** A list that resolves fewer officials than the
  latest complete list before it is cut off, so it is not complete, unless `AT_LARGE_SHORT_CONFIRM` (= N + 1 = 3)
  short lists in a row confirm a smaller council (a vacancy); then that run is complete and its size is the new
  reference. So two cut-off lists never split a record, and a vacancy of three or more lists still does.
- **Review nits 3-5 (T5b).** (3) A print with `pro_tem: true` never carries a `title`. The collector never writes
  both, and `at_large_rows` refuses a prints file that has both (SeatsError naming the meeting), so "Mayor Pro Tem"
  can never become a Mayor title record. (4) `registry._check_primary` refuses two `primary.titles` with the same
  `title_slug` (e.g. "Vice Mayor" and "Vice-Mayor"), naming both, because they would share seat `title-vice-mayor`.
  (5) The title-run loop ends on a private sentinel (`_END = object()`), not `None`, so a print whose `meeting_id`
  is null is never read as the end of the lists.
- **Invariant (family `at-large/*`).** This is stated before the next fix because the member gap is the family's
  second hit (loop rule). Every at-large record is a maximal run of attendance-list prints. A membership record is
  one member's prints, with no N consecutive complete lists inside it that omit them. A title record is the lists
  that print that title beside exactly that one member, with no read list inside it that prints the title for
  nobody or for two. Its `start`, `seen_to`, `source` and `last_source` all come from prints inside the run.
  Nothing comes from `officials[].title`, roll calls, config naming a holder, or term dates. A title is a label in
  a member's own records, never an order between members.
- **Every consumer of `at_large_rows`** (each must hold the invariant; T5b checks each one):

  | Consumer | Reads | Check |
  |---|---|---|
  | `sitegen/council.py` `at_large_rows`, `printings()` | rows, prints | each split record keeps its own `printings` |
  | `sitegen/council.py` `title_conflicts` (run log in the T6 build) | prints | the sentinel fix covers its loop too |
  | `sitegen/seats.py` `Seats` (`dates_text`, `held_over_text`, `on`, `seat_text`, `header_text`, `of`, `for_seat`, `current_of_seat`, `is_current`, `is_held_over`, `covers_to`) with `AT_LARGE_WORDING` | rows, L | two records for one member: `on(date)` inside the gap is None (no label); `seat_text` reads the current record only |
  | `sitegen/seats.py` `at_large_seats`, `seat_label`, `seat_order` | PRIMARY | labels and one member's own record order only |
  | `sitegen/views.py` `Index.person` (meeting pages, ~line 300), `current_basis_lines` and `_card` (~574-595), `base` (~833), `roster_official` (~953), `body_records`, `_seat_on`, `search_index` (~1929-1998) | Seats | a meeting inside a gap shows no seat label; the search label comes from the current record |
  | `sitegen/views.py` `officials_page.seat_key` (~649) | `seat_order` of current records | **must change in T6**: for `at_large` it sorts by surname only. Today the title seats' order (-1, ...) would list the Mayor and Vice Mayor first, which breaks "titles never move a member up the list" |
  | `sitegen/build.py` (T6 builds `ix` from these rows), `qa/site_checks.py` at-large card checks (T9), `tests/test_at_large_seats.py` | rows | T6 and T9 are written against the gap rule |

### 6. "Who represents you" for an at-large council: no address box
Every member is elected by the whole city, so an address cannot narrow the answer. The card has:
- the heading "Who represents you";
- `seat_basis.sentence`, which describes the body, never a named official, followed by its source link
  (`seat_basis.url`), as every fact is;
- the members the latest minutes read list, **each shown the same way** (one row shape: name linked to their page,
  the seat label of the latest record, i.e. "Vice Mayor" or "Councilmember, at large", and the observed basis line
  with its source), in surname order, the same tie-break the Officials page uses today. Titles are data in the row,
  never a reason to move a member up the list;
- a link to the Officials page.

Not drawn: the address form, `address.js` config, the geocoder iframe and its CSP entries (`script-src` gets no
geocoder host or frame hash), the "Your seats" saved list, and the ward and district list. The `district_lookup` line
(GoVoteTN) is not drawn either (open question 2). The Officials page lede for at-large reads "Members of the
{name} seen in the latest minutes read, in surname order. Then everyone who served previously, by surname." There
are no scores, rankings, counts by member on the front page, or commentary.

### 7. Collectors read the city file; the import cycle is fixed first
- **Layering (the cycle ADR 0007 names).** Two leaf modules with no `cities` or `collector` imports:
  `collector/hosts.py` (`DENIED_HOSTS`, `host_matches`, `plain_hostname`) and `collector/windows.py` (`Window`,
  `launch_windows`, `WindowError(ValueError)`). `collector/fetch.py` re-exports the host names. `cities/plan.py`
  re-exports the window names and turns `WindowError` into `CityError`. `collector/legistar.py` imports
  `collector.windows`. `cities/registry.py` imports `collector.hosts`. Rule, tested with `ast`
  (`tests/test_import_layers.py`, plus a fresh-process import of each package in both orders): a `cities` module
  imports from `collector` only `hosts` and `windows` at module level (`readers` keeps its lazy imports); a
  `collector` module imports `cities` only inside the CLI entry functions that resolve `--city`.
- **`python -m collector city <fetch|build|run> --city <slug>`** (default `clarksville-tn`; `--locality` stays as an
  alias). It loads the city through the registry, takes the agenda_center and civicclerk sources' config files from
  `city.yml`, and builds `PoliteFetcher(allowed_hosts=registry.allowed_hosts(city), extra_denied=city denied)`.
  Data goes to `data/localities/<slug>/` (the existing `city_run.paths` layout). The fetcher itself takes hosts as
  arguments and never imports `cities`.
- **Refusals before any request:** a city that is not READY in `cities check` (hosts without dated robots and terms
  lines, `UNVERIFIED` portal values) gets exit 2 from `fetch` and `run`, naming the items. A host that blocks us stops
  the run (unchanged). There is no "force" flag. `build` from stored files needs no network and is always allowed.
- **Titles in the minutes reader:** `collector/city_minutes.py` takes its title words from `agenda_center.yml`
  (`printed_titles`). Clarksville's default equals today's `TITLES` and `PRO_TEM_RE`, so its facts and wards stay
  byte-identical. Vote and attendance names have the printed title removed before they are resolved.
- `collector/config.py` (`BODY`, `YEARS`) stays the county pipeline's. That pipeline is Clarksville-only
  (`county_minutes`, a non-shared reader), and `python -m collector run --city <other>` refuses. ADR 0007's
  "collector/config.py takes its body from the city file" is narrowed to the shared readers, which already read
  their body from the source file (`agenda_center.yml` `body`).

### 8. Per-city deploy: a small public repo per city that pulls an attested site (design only)
- **Where the site lives.** Each live city other than Clarksville gets a public repo `gn0sh/daylight-<place>`
  (e.g. `daylight-murfreesboro`) with Pages on, custom domain `<place>.daylight.gnoshcodes.com` (city.yml `domain`),
  HTTPS enforced. It holds one workflow and a README, and no site history.
- **Pull, not push.** The engine's daily run builds each live city (`--city`). The push job (J2 in ADR 0011,
  already the only job with `contents: write` and `attestations: write`) fast-forwards branch `site/<slug>` with the
  built tree and attests its tree listing, as it does for `records-data`. The city repo's workflow (schedule, plus
  manual) clones `site/<slug>` anonymously (a public repo needs no token), verifies the attestation with the same
  certificate identity and predicate pins as ADR 0011 decision 3, then uses `upload-pages-artifact` and
  `deploy-pages` in its own `github-pages` environment, limited to `main`. The city repo holds **no credential for
  the engine repo, and the engine repo holds none for the city repo**, so ADR 0011's two-writer property (decision
  6) is untouched. The only attester is still J2. The `site/*` branches get ruleset R-S (deletion,
  non_fast_forward, no bypass), written by `protect-main` like R-D.
- **Fallback** if cross-repo verification needs a token (the unverified fact above): the city repo verifies the
  tree listing's digest against a `site-digests.json` on `records-data`, which is itself attested. Still no new
  secret.
- **Fits ADR 0011.** The city's collector output is ordinary `data/localities/<slug>/*.json` on `records-data`
  (fits SHAPE''). Its tests use fixtures under `tests/fixtures/`, never `data/`. Nothing in M1 or M2 touches
  `.github/workflows/`, `scripts/`, `deploy/` or the data layout. The workflow, R-S and `protect-main` changes (tasks
  D1, D2) start only after ADR 0011's cutover (C1) and V1'' probe pass, as one reviewed change with
  security-engineer. Before a city goes live, ADR 0011's content tripwire must also cover that city's published
  facts (task D4).
- **Hard stops for the owner (Brian), in this order. The team prepares each one as copy-paste steps:**
  1. Create the public repo `gn0sh/daylight-murfreesboro` (hard stop 4: acting outside the repo on his behalf). The
     team pushes the template from `cities/templates/deploy-repo/`, not from `deploy/`.
  2. Add the DNS record `murfreesboro.daylight` CNAME `gn0sh.github.io` at the gnoshcodes.com DNS host (hard stops
     2 and 4: infrastructure outside the repo). Check that gnoshcodes.com is a verified domain on his GitHub
     account, which guards against subdomain takeover.
  3. In the city repo: Settings > Pages > Source "GitHub Actions", custom domain, Enforce HTTPS; environment
     `github-pages` limited to `main` (hard stop 2: repository infrastructure).
  4. The go-ahead to go live: `status: live` plus `go_ahead: {date, by: Brian}` in `city.yml` in the same PR, then
     enabling the city repo's workflow. Its first run is a production deploy (hard stop 1).
  5. After the deploy, the team adds the site to `gn0sh/gnosh-uptime` `monitor.config.json` (inside our repos). Adding
     it to Better Stack and drafting the Buy Me a Coffee post follow `docs/expansion/add-a-city.md` steps 7-8. Brian
     posts it himself, and not during the soft opening.
  No step costs money: public repos, Pages and Actions are free, and no paid domain is needed.

### 9. The city's name in the footer, Clarksville unchanged
`config/brand.yml` gains one locked block, `named_lines` (`footer: "{site_name} {place} is provided as a free
service by"`, `support: "{site_name} {place} is free and always will be, but web hosting and sending email cost
money. If it is useful to you, please consider supporting the project."`). `cities/brand.py` adds it to `LOCKED`.
`drift()` compares only the seven keys `config/site.yml` duplicates today (`LEGACY_DUPLICATES`), so `site.yml` needs
no edit. `brand.merge` (called by `registry.site_settings`) adds `footer_line` and `support_line` to the site
settings, so templates read `site.cfg.get("footer_line")` and `site.cfg.support_line`; this needs no change in
`views.site_context` (T8 built, 2026-11-18). When the settings set `place_name`, they are the named lines with
`site_name` and `place_name` filled in ("Daylight Murfreesboro is provided as a free service by gnoshcodes LLC.";
"Daylight Murfreesboro is free and always will be, ..."). Without it, `footer_line` is absent and the footer keeps
today's exact text ("Provided as a free service by"); `support_line` stays the brand's unnamed line. The
`base.html.j2` footer line changed in T8's PR (T7 had not merged). Clarksville sets no `place_name`, so its output is byte-identical (decision 1
guard). `place_name` must be a plain name (letters, spaces, hyphens, periods), at most 40 characters, and is never a
brand key. A city still can't change the wording or the coffee link.

### 10. Rules that hold, as tests
- Every fact links its source: the at-large statement and every seat or title record carry a source URL. A
  `pages` build refuses an unsourced one.
- No AI-written text about named officials: every sentence on the card and the Officials page is a fixed settings
  template about the body, or a record's own fields.
- Every official is shown the same way: one row macro for every member; `test_site_neutrality` runs on the
  Murfreesboro fixture build too.
- Votes: Murfreesboro's come from minutes PDFs. Any later data-portal vote stays "Not confirmed" until it is read in
  minutes (unchanged rule, `SHOW_UNCONFIRMED_VALUES = False`).
- No network in tests (sockets refused, as in ADR 0007). No test writes under `data/` (`qa/published_guard.py`).
- No place leaks: the Murfreesboro fixture build contains no "Clarksville", "Montgomery", "County Commission",
  "district" or "ward" on any page (family `city-only/no-county-leak`).

## Amendment A1: Salem first (2026-11-19)
**Why.** `www.murfreesborotn.gov` answered our one robots.txt request with a Cloudflare block (2026-11-19,
`config/cities/murfreesboro-tn/platform-facts.md`). We don't work around a block, so the owner switched the first
city to Salem, OR. Records availability was one of the reasons Murfreesboro was picked, and Salem's records are
reachable: the 2026-11-19 check (`config/cities/salem-or/platform-facts.md`) found Salem's Legistar Web API with
350 City Council events from 2016-01-01 to 2026-06-22, nearly all with minutes, and Salem's eScribe portal
(`pub-salem.escribemeetings.com`) with council meetings from 2026-07-13 on, each with Agenda, PostMinutes and Video.
The city's main site (`www.cityofsalem.net`) blocks us (Akamai 403). It is not needed for collection, and nothing is
fetched from it. Murfreesboro stays a draft city: its at-large design (decisions 5 and 6) is kept and tested on its
fixture, and it waits on the owner (permission from the city, or another source).

Facts for Salem (nothing here is verified unless it says so; each unverified one is a `cities check` item):

| Fact | State |
|---|---|
| Legistar `salem`: body 138 "City Council", events 2016-01-01..2026-06-22, minutes files | **verified** 2026-11-19 (team check, platform-facts.md) |
| eScribe `pub-salem.escribemeetings.com`: calendar POST answers; council meetings from 2026-07-13 with Agenda, PostMinutes, Video | **verified** 2026-11-19 (same check). The JSON field names are **not recorded** yet (task E0) |
| robots.txt: 404 on `webapi.legistar.com`, `salem.legistar.com`, `pub-salem.escribemeetings.com` | **verified** 2026-11-19. Terms of use: **not read** on any host |
| Legistar minutes files are on `salem.legistar1.com` | **unverified** (robots not checked) |
| The council is elected by ward: 8 wards, one councilor each, plus a mayor elected citywide | **UNVERIFIED** (the ward count and the mayor's seat; no minutes read) |
| Printed titles ("Mayor", "Councilor", a rotating "Council President") | **UNVERIFIED** |
| Last Legistar meeting 2026-06-22, first eScribe meeting 2026-07-13, so the cutover date is 2026-07-01 | the dates are verified; the cutover is our choice between them |
| Salem's "find my ward" page (city of Salem or Marion County, which with Polk County covers the city) | **UNVERIFIED**; the city's own page is on the blocked host, so it is only ever linked, never fetched |
| Timezone `America/Los_Angeles` | **UNVERIFIED** in `city.yml` (expected) |

**A1.1 Seat basis: wards, reusing Clarksville's ward machinery.** Salem's `primary:` block says `seats: wards`. Every
seat record comes from the same code Clarksville's council pages use (`sitegen/council.py` `holder_rows`, i.e.
`ward_rows`, `title_rows`, `extend_by_listings`, the one-list-drop rule, `unplaced_names`), called from the
top-level primary path of decision 2 instead of the council folder. The settings the council reads from
`council.yml` (`seat_word: ward`, `min_ward_prints: 2`, `title_seats: {Mayor: city-mayor}`, `evidence`,
`latest_words`) go in a `primary.ward_records:` sub-block with the same keys and the same validation
(`config.load_council`'s rule); seat ids stay `ward-<n>`. A rotating printed title (e.g. "Council President", if the
minutes print one) uses decision 5's title-run reader, which T5b extracts as a shared helper
(`council.title_runs(prints, facts, titles)`) so ward and at-large cities read titles the same way. The ward count is
never configured: the wards are the ones the attendance lists print. The Mayor is the `city-mayor` seat from
`title_seats`, as in Clarksville. The prints file is `wards.json` with `ward: <n>`, written by the Salem minutes
reader (task E4).
- Officials page order for a wards primary: ward number, then the Mayor and other seats in the configured order, as
  Clarksville's council does today (`seat_order`). Title seats never take part in that order (the `seat_key` change
  in decision 5's consumer table covers wards too).
- **"Who represents you" for wards (decision 6's ward form).** The heading; `seat_basis.sentence` with its source link
  (a wards city needs `seat_basis` too: `cities check` adds it when `seats` is `wards`); one row per ward that has
  a current record, in ward-number order, then the Mayor row, every row the same macro; a "Find your ward" link to
  `district_lookup` once it is verified; the Officials link. **No address box** in this milestone: it needs ward
  shapes from an official source (Clarksville's are traced from the city's ward poster). A Salem ward map from an
  official GIS host is a later task with its own host check. No geocoder CSP entries are added.
- **No-leak words (decision 10) depend on the seat basis.** For `wards`: "Clarksville", "Montgomery", "County
  Commission", "district" (the word "ward" is expected). For `at_large`: the list as written. For `districts`:
  unchanged.
- **seat_basis for Salem is UNVERIFIED.** The city charter or a city page that says councilors are elected by ward
  is on the blocked host. Recommended: the owner opens one page in a browser and pastes its URL and the sentence it
  supports. A `pages` build refuses an `UNVERIFIED` `seat_basis` (decision 2), so this cannot slip.

**A1.2 No county.** Salem's site is city-only (decision 3, unchanged). There is no county body, switch, hub,
district page, RPC, finance or committee data. Salem's `site.yml` sets only the keys in `registry.CITY_SITE_KEYS`.

**A1.3 Two sources, stitched by date.** `city.yml` lists both sources, each with the date range it owns:
```yaml
sources:
  - {portal: legistar, config: config/cities/salem-or/legistar.yml, until: "2026-07-01"}
  - {portal: escribe,  config: config/cities/salem-or/escribe.yml,  from:  "2026-07-01"}
```
- The registry checks the ranges: the dates are YYYY-MM-DD, at most one source is open-ended at each end, and the
  ranges abut with no gap and no overlap (`until` of one equals `from` of the next). A city with one source needs
  neither key. The ranges are half-open: Legistar owns `[earliest, 2026-07-01)`, eScribe owns `[2026-07-01, ...)`.
- Each reader returns listing rows in the shared row shape (`collector/legistar.py` `listing_rows`: date, title,
  kind, agenda_id, agenda_url, minutes_url, video_url, source, event_id, official_page). A new pure module,
  `collector/stitch.py`, joins them before `city_build` turns rows into facts:
  `stitch(rows_by_source: dict[str, list[dict]], ranges: dict[str, tuple[date|None, date|None]]) -> (rows, log)`.
- **Ids never collide.** Meeting and source ids carry their portal: `legistar-<EventId>`, `escribe-<meeting GUID,
  lowercase>`. A document's source id is built from its own URL.
- **Duplicates at the seam.** Two rows from different portals are the same meeting when they share the date and the
  kind, and their start times match where both give one. Of a matched pair, the row with a minutes file is kept. If
  both have minutes, or neither does, the row whose source owns that date is kept. The other row is dropped and the
  log names it (`stitch/seam-duplicate`, with both URLs). A row outside its source's range with no match is kept
  (a meeting only one portal lists must not vanish) and logged `stitch/out-of-range`.
- **Each meeting cites its own source; fields are never merged.** A kept row's agenda, minutes, video and official
  page all come from its own portal. We never take Legistar's minutes and eScribe's video for one meeting, so every
  fact on a meeting page links a document of the source the meeting came from. The meeting page's "official record"
  link is the row's own `official_page`. The About and Method pages name both portals with their date ranges, read
  from `city.yml` (`primary.record` is the current portal, eScribe).
- The stitch log goes in the collector run log (the existing build warnings path). `qa/site_checks.py` gets no stitch
  check; the unit tests hold the rule (family `stitch/*`).

**A1.4 The eScribe reader (`portal: escribe`, new `collector/escribe.py`).**
- **Hosts it asks:** `pub-salem.escribemeetings.com` only (config `host`). Document links of the form
  `FileStream.ashx?DocumentId=<n>` resolve against that host. An absolute document URL on any other host is dropped,
  and the log names it, unless the host is in the config's `file_hosts` (empty for Salem). Video links are stored as
  links only (`video_hosts`, the registry's `link_keys`) and never fetched. Every host goes in `city.yml`
  `allowed_hosts` with its dated robots and terms lines, as for every portal.
- **Public calls it uses, and nothing else:**
  1. `POST https://<host>/MeetingsCalendarView.aspx/GetCalendarMeetings` with a JSON body holding only a start and an
     end date: the call the public calendar page makes. One POST per window of at most 6 months (a 6-month window
     answered 27 meetings on 2026-11-19), and each daily run asks again only the last 60 days, so minutes posted
     late are picked up. The body's key names and the answer's field names (meeting GUID, name, start date and
     time, document list with type, format and URL, video) are taken from a recorded answer (task E0), never guessed.
  2. `GET https://<host>/FileStream.ashx?DocumentId=<n>` for the documents the calendar answer lists, only those of the
     types the config names (`agenda_types: [Agenda]`, `minutes_types: [PostMinutes]`, UNVERIFIED until the
     recorded answer is read). A PDF is preferred when the answer lists both PDF and HTML; the HTML minutes page
     (`Meeting.aspx?Id=<guid>&Agenda=PostMinutes`, same host) is the fallback, read with GET. A document already
     stored (by DocumentId and its validator) is not asked again.
- **Body filter.** The calendar lists every board. A row is kept only when its meeting name matches one of the
  config's `body_names` exactly (UNVERIFIED: "City Council", "City Council Work Session"); kinds come from
  `kind_rules` as in `legistar.yml`. The answer is checked, never trusted, as `legistar.listing_rows` does.
- **The fetcher gains one narrow POST.** `PoliteFetcher.post_json(url, payload)` sends JSON only to a (host, path)
  pair the reader declares (`escribe.POST_PATHS = ("/MeetingsCalendarView.aspx/GetCalendarMeetings",)`, passed in
  by `city_run`, never read from the city file). It uses the same allowlist, denied hosts, robots check (a 404
  robots.txt allows all), per-host delay (`MIN_DELAY`, 10 s), request cap and user agent as `get`. Any 3xx answer
  is a failure, never followed. The answer is capped at 5 MB, no cookies are kept, and nothing is sent but the date
  window. This changes `collector/fetch.py`, so security-engineer reviews it.
- **Votes.** The minutes stay the official record. Votes are read from the minutes document of each source
  (Legistar's `EventMinutesFile`, eScribe's PostMinutes). A vote from a portal's structured data (Legistar's
  `/votes`, or any vote table eScribe may expose) is shown "Not confirmed" until the verifier reads the same vote in
  the minutes, the rule of decision 10, unchanged for both portals (`SHOW_UNCONFIRMED_VALUES = False`).
- **Registry.** `cities/readers.py` gains `"escribe": Reader("eScribe meetings portal", "collector.escribe",
  "load_config", ("city", "host", "body_names", "agenda_types", "minutes_types", "kind_rules", "launch_days"),
  host_keys=("host",), link_keys=("video_hosts",))`.
- **Alternatives considered.** (a) GET the calendar page's HTML: the list is drawn in the browser from the POST, so the
  HTML holds no meetings. (b) Guess `Meeting.aspx?Id=` pages: the GUIDs come only from the POST. (c) Wait for a
  municipal export or RSS feed: none was seen; we'd re-check in E0. (d) Leave July 2026 onward out of the launch
  year: the site would stop five months before launch, which fails "the latest minutes read". Rejected.

**A1.5 District lookup.** `district_lookup` for Salem is a page where a resident finds their ward (the city's own
ward finder, or Marion County's or Polk County's elections lookup). It is **UNVERIFIED**. It is a link only, and the
card leaves it out until a person has opened it in a browser and recorded the URL and date in `platform-facts.md`.

**A1.6 What changes in the tasks.** Milestone 1's end-to-end slice uses a fixture Salem-shaped city (wards, two
sources across a cutover, made-up people) instead of Murfreesboro. The at-large work (T5, T5b) stays, tested on the
Murfreesboro fixture. New tasks E0-E4 and T4b are in `docs/tasks/city-only-site.md`.

## Interfaces (contract for the build tasks)
- CLI: `python -m sitegen [--city SLUG] [--facts F] [--out D] [...existing flags]`; exit 2 on a city or env clash.
  `python -m collector city {fetch,build,run} [--city SLUG]`; `python -m qa.site_checks --city SLUG ...`.
- `cities.registry`: `load_city(slug)` also loads `site_file` (new key) and validates `primary` and `place_name`;
  `site_settings(city, brand) -> dict` as in decision 1; `SHARED_SITE_KEYS: tuple[str, ...]`.
- `sitegen.config`: `CITY: str`, `SITE: dict`, `PRIMARY: dict` (decision 1 keys); the path constants may be None.
- `sitegen.council`: `at_large_rows(prints, facts, primary) -> tuple[list[dict], str | None]`. It returns the same
  record shape as `holder_rows`, and the same `(rows, latest)`.
- `sitegen.views.Index(facts, seat_rows=None, *, kind_labels=None, held_sentences=None, seat_wording=None)`.
- Prints row (at-large): `{official_id, raw_name, meeting_id, date, source_id, page, ward: null, title: str|null}`.
  A build refuses a prints file whose non-null `official_id`s are not all in the facts, which also stops a real
  file from sitting beside fixture facts.
- Prints row (wards, Salem): `{official_id, raw_name, meeting_id, date, source_id, page, ward: int, pro_tem: false,
  title: str|null}` (Clarksville's shape plus the optional `title`).
- `sitegen.council.title_runs(prints, facts, titles) -> list[dict]` (T5b; shared by at-large and ward primaries).
- `collector.escribe`: `load_config(path) -> dict`; `calendar_request(cfg, window) -> (url, payload)`;
  `listing_rows(cfg, answer: dict) -> list[dict]` (the shared row shape, `source: "escribe"`); `POST_PATHS`;
  `allowed_hosts(cfg) -> tuple[str, ...]`.
- `collector.fetch.PoliteFetcher.post_json(url: str, payload: dict) -> tuple[int, bytes, dict]` (only to declared
  POST paths; `post_paths` is a constructor argument, default empty, so every existing caller can't POST).
- `collector.stitch.stitch(rows_by_source, ranges) -> tuple[list[dict], list[str]]`; log lines start
  `stitch/seam-duplicate:` or `stitch/out-of-range:`.
- `city.yml` `sources[]`: optional `from` and `until` (YYYY-MM-DD, half-open, abutting).

## Alternatives considered
- **Make the county index optional and keep the council under `council/`:** every view that takes `ix` (site
  context, nav, landing, search, feeds, Today, stats, About, export, morning) would need a None path, the top-level
  menu would point at nothing, and Clarksville's code would change at about 15 call sites. More risk to its bytes
  for no gain to readers. Rejected.
- **An empty county facts file as a null object:** county words would still appear in feeds, search filters and the
  export. Rejected.
- **A fork or separate generator per city:** it drifts, which ADR 0007 exists to avoid. Rejected.
- **Thread a settings object through every sitegen function instead of import-time selection:** the cleaner end
  state, but it touches 17 modules and many tests while Clarksville work continues. Deferred until a second
  city-only site, or the first bug caused by module state.
- **Keep the address box for at-large, answering "all members":** it sends an address to the Census geocoder for an
  answer that doesn't depend on it, which costs privacy and a third-party CSP entry for nothing. Rejected.
- **Show titles by hard-coded holders (`title_seats` on `officials[].title`):** a rotating Vice Mayor would be wrong
  for every meeting outside the current term. Rejected.
- **Deploy by subpath (`daylight.gnoshcodes.com/murfreesboro/`) from the engine repo, no city repos (the simplest
  thing):** no new repos and no DNS. The built pages already use relative links, so a subpath works. It loses
  because `city.yml` `domain` and the template plan promise subdomains, one city's failed build would hold every
  city's deploy, and moving a city to its own domain later breaks its links. This is an expensive-to-reverse hosting
  choice, so a Brain Trust is recommended before D1 (handoff).
- **Push from the engine to each city repo with a deploy key or token:** a new secret (hard stop 5) and a second
  writer path out of the engine. Rejected in favour of pull.

## Consequences and risks
- Clarksville's output must stay byte-identical across T1-T9. The golden digest test is the gate, and any
  difference is a must-fix in that PR.
- File growth: one page per meeting at the top level. At about 40 meetings a year, 10 backfilled years plus members
  and items fit Pages' 3000 cap, but not the 500-file preview. The preview build of a city drops transcripts, then
  the export, as today. Re-check when backfill passes 5 years.
- Import-time settings: a process builds one city. Tests that need two cities use subprocesses (slower, isolated).
- `wards.json` now holds at-large prints. The name is misleading but avoids touching the shrink guard and splice
  code (`city_run.keep_city`). A rename is a later cleanup.
- Two folders per city in `data/` (`localities/<slug>/` for collector output, `cities/<slug>/backfill.json` for the
  planner, per ADR 0007). Accepted.
- New residual: a city file's hosts widen what the fetcher may ask. This is covered by registry validation, the
  denied-host rule and R1'' review of every merge.

## Open questions (the design proceeds on the recommended answer)
1. **Is Murfreesboro's Mayor listed in the council's attendance lists and roll calls?** Recommended: show what the
   minutes print. A Mayor printed in the list is a member row like every other, with the title "Mayor" from
   the record. The team checks this in the first minutes it reads (task C3). Nothing is decided in config.
2. **Keep the GoVoteTN line on an at-large site?** Recommended: **no**. Nothing on the site is organised by district,
   so "Not sure of your district?" would point visitors to offices the site doesn't cover. `district_lookup` stays in
   `city.yml`, unused, for a later ward city.
3. **Subdomain repos (decision 8) or one site with subpaths?** Recommended: **subdomain repos**. A 3-member Brain
   Trust (devil's advocate, a resident who reads the site, a hosting and ops lens) should meet before task D1,
   because this is hard to reverse. It does not block M1 or M2.
4. **Alerts feeds for a new city?** Recommended: **yes** once `alerts.feed_id` is set. They are static Atom files
   with no account. The morning note stays Clarksville-only.
5. **Visitor counter for a new city?** Recommended: **off**. A new GoatCounter site is a new account (hard stop 4),
   so it waits until Brian asks for it.
6. **(A1) Salem's seat basis source, given that `www.cityofsalem.net` blocks us?** Recommended: the owner opens the
   city's council or charter page in a browser once and pastes the URL and the sentence; we link it, never fetch it.
   Until then Salem stays NOT READY (a `pages` build refuses it), and the fixture slice is unaffected.
7. **(A1) Cutover date 2026-07-01?** Recommended: **yes**. It sits between the last Legistar meeting (2026-06-22)
   and the first eScribe one (2026-07-13); the seam rule keeps any meeting one portal lists and the other lacks.
8. **(A1) Launch year for Salem: 365 days back from launch, spanning both portals?** Recommended: **yes**, Legistar
   for the months before July 2026 and eScribe after. Backfill (2016 onward) is Legistar only and runs as compute
   allows.
9. **(A1) Terms of use for the three hosts?** Not read yet. Recommended: the manager reads each host's terms page
   once (if one exists) in task E2, and records "none published" with the date when there is none.
