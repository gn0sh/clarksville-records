# ADR 0012: A city-only Daylight site (no county, at-large council)

Status: proposed (software-architect, 2026-11-18), feature `city-only-site`, Daylight template milestone 2.
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
  (`--facts` and `--out` required), so the daily workflow's command line does not change.
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
    `config/site.yml`.
- `config.PRIMARY`, one normalised dict that names the site's primary body: `key`, `name`, `label`,
  `meeting_title_body`, `record`, `kind_labels`, `held_sentences`, `seats` (`districts` | `wards` | `at_large`).
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
no edit. `views.site_context` gives the templates `footer_line` and `support_line`. When the settings set
`place_name`, they are the named lines with `site_name` and `place_name` filled in ("Daylight Murfreesboro is
provided as a free service by gnoshcodes LLC."; "Daylight Murfreesboro is free and always will be, ..."). Without
it, they are today's exact text. Clarksville sets no `place_name`, so its output is byte-identical (decision 1
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
