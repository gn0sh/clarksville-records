# Tasks: city-only site (ADR 0012)

Design: `docs/adr/0012-city-only-site.md` (decision numbers below are its own). Every task works in its own worktree
on its own branch from `origin/main`. It runs the preflight (`python -m pytest -q`, plus the site checks for the
sitegen tasks) in session and pastes the output in its PR. No task fetches anything, deploys, or writes under
`data/`. Every PR goes to `code-reviewer`. PRs touching the fetcher allowlist (T1, C1) or the workflow, rulesets or
deploy (D1-D3) also go to `security-engineer`. Problem families: `city-only/clarksville-identical`,
`city-only/no-county-leak`, `at-large/title-from-record`, `city-only/import-layers`, and from ADR 0012 amendment A1
(2026-11-19, Salem first): `at-large/*` (second hit: `at-large/member-gap`; third hit: `at-large/short-confirm-blesses-cutoffs`, rule restated;
invariant and consumers in decision 5),
`stitch/*`, `escribe/*`. PRs touching `collector/fetch.py` (E1's `post_json`) also go to `security-engineer`.

**ADR 0011 overlap (checked 2026-11-19 against `origin/claude/data-off-main-b1` and `-b1b`).** B1 and B1b edit
`sitegen/views.py`, `sitegen/build.py`, `sitegen/config.py`, `qa/site_checks.py`, `qa/pii_scan.py`,
`sitegen/transcripts.py`, and in `collector/`: `names.py`, `facts.py`, `verify.py`, `export.py`, `transcripts.py`,
`fin_books.py`, new `data_shape.py`, `reviewed_lists.py`, plus `collector/tests/test_city_shrink_guard.py`. A task
that must touch one of these starts only after B1 (and B1b) merge, from that `main`.

**Clarksville byte-identical, every sitegen PR (T3-T9):** the T0 golden test passes. The PR also pastes
`diff -r before/ after/` (empty) of `python -m sitegen --facts <F> --out <D> --target pages`, run at the base
commit and at the head commit on the same data tree. Before ADR 0011's cutover that tree is `data/`; after it, one
`records-data` commit from `scripts/fetch-data`, named in the PR. The same check is repeated with
`--city clarksville-tn`.

## Milestone 1: thin end-to-end slice (fixture Salem-shaped city builds locally; Clarksville unchanged)
**Re-pointed 2026-11-19 (ADR 0012 A1):** the slice is a fixture Salem-shaped city (wards, a Mayor, two sources across
a cutover, made-up people), not Murfreesboro, whose host blocks us. Murfreesboro's fixture stays as the at-large
test case for T5, T5b, T7 and T9 (built in a test, not the slice).
Done when `python -m sitegen --city salem-or --facts tests/fixtures/cities/salem-or/facts.json --out
build/salem-or/site` writes a site that passes `python -m qa.site_checks --city salem-or`, the same pair for
`murfreesboro-tn` passes in `tests/test_city_only_build.py`, the full suite passes, and the T0 digests are
unchanged. Salem stays `status: draft`; the fixture build never uses `--target pages`.

| Task | Owner | Depends on | Parallel | Collides with ADR 0011 work? |
|---|---|---|---|---|
| T0 Clarksville golden digests | backend-engineer | none | yes (first) | no |
| T1 Import layering (hosts, windows) | backend-engineer | none | yes | no |
| T2 Registry: `site_file`, `primary`, `place_name`, shared keys | backend-engineer | T1 | with T4 | no |
| T3 sitegen `--city`, `config.CITY`, `config.PRIMARY` | backend-engineer | T0, T2 | no | no |
| T4 Murfreesboro fixture data | backend-engineer | none | yes | no |
| T5 At-large membership and title records | backend-engineer | T3, T4 | with T8 | no |
| T5b At-large member gaps, review nits 3-5, `title_runs` helper | backend-engineer (opus/high: state rule) | T5 | with T4b, E2 | no (`sitegen/council.py`, `sitegen/seats.py`, `cities/registry.py`) |
| T4b Salem-shaped fixture data (wards, two sources) | backend-engineer | none | yes | no (`tests/fixtures/` only) |
| E2 Salem config: `city.yml` sources and ranges, `site.yml`, `escribe.yml`, hosts | backend-engineer (manager runs the polite reads) | T2, E1 (the registry must know `portal: escribe`) | with T5b, T4b | no (`config/cities/salem-or/`, `cities/registry.py` source ranges, `tests/test_cities.py`) |
| T6 Build shape: county pieces off, nav, landing context; wards primary | backend-engineer | T3, T5b, T4b, E2, **B1 and B1b merged** | no | **yes: `sitegen/views.py`, `sitegen/build.py`, `sitegen/config.py`** |
| T7 Templates: front-page card (at-large and ward forms), Officials lede, guards | frontend-engineer | T6 | no | no |
| T8 Named footer lines (brand) | backend-engineer | T3 | with T5 | no |
| T9 Site checks `--city`, city-only end-to-end test (Salem slice + Murfreesboro) | qa-engineer (checks) + backend-engineer (code) | T7, T8, **B1 and B1b merged** | no | **yes: `qa/site_checks.py`** |

Done on the branch by 2026-11-19: T0-T5 and T8 (PR #62 work). Next order: T5b, T4b and E2 in parallel (and E1 from
milestone 2, which E2's check needs), then T6 once B1/B1b merge, then T7, T9.

Suggested order: T0, T1 and T4 in parallel, then T2, T3, then T5 and T8 in parallel, then T6, T7, T9. Send the
milestone to review in two PRs, at about 1,000 lines each: (T0-T4) and (T5-T9).

### T0: Clarksville golden digests
- Files: new `tests/test_clarksville_identical.py`, `tests/fixtures/clarksville-digests.json`.
- What: build Clarksville (a) from the pinned snapshot (`tests/pinned_data.py`, materialised to a temp dir) and (b)
  from the fixture facts the page tests use, both with a fixed `today` and `--target pages`. Record the
  sha256 of the sorted `(relpath, sha256)` list of the output tree, at the base commit, before any sitegen change.
- Tests: the digests match. Later tasks also run it with `--city clarksville-tn` (it skips until T3 lands).
- Done when: the test passes on `main` and the digests are committed with the commit they were taken at.

### T1: Import layering (ADR 0007's named cycle)
- Files: new `collector/hosts.py`, new `collector/windows.py`; `collector/fetch.py` (move `DENIED_HOSTS`,
  `host_matches`, `plain_hostname` out, re-export them), `collector/legistar.py` (import `collector.windows`),
  `cities/plan.py` (re-export; `WindowError` becomes `CityError`), `cities/registry.py` (import `collector.hosts`); new
  `tests/test_import_layers.py`.
- Tests: an `ast` rule over `cities/*.py` and `collector/*.py` (decision 7). A fresh-process `import cities.registry;
  import collector.fetch` and the reverse order both succeed. The existing `test_cities.py` and Legistar tests pass
  unchanged, and the public names are unchanged.
- Done when: the tests pass, and `ALLOWED_HOSTS`, `DENIED_HOSTS` and fetch behaviour are unchanged (the existing
  fetch tests pass).

### T2: Registry: the new city keys
- Files: `cities/registry.py` (`site_file`, `SHARED_SITE_KEYS`, `site_settings` order, `primary` and `place_name`
  validation, `live` from status, `alerts.site_url` from domain), `cities/check.py` (list `UNVERIFIED` in the site
  file; `seat_basis` unverified means NOT READY), `cities/scaffold.py` and new `cities/templates/site.yml.tmpl`,
  `config/cities/murfreesboro-tn/city.yml` (`site_file`), new `config/cities/murfreesboro-tn/site.yml` (the decision 2
  block, every unchecked value `UNVERIFIED`), new `config/cities/murfreesboro-tn/corrections-log.json` (`[]`),
  `tests/test_cities.py`.
- Tests: an unknown `primary` key fails; a bad `seats` word fails; `place_name` with markup fails; a shared key that
  holds "Clarksville" or "Montgomery" fails; a city site file that sets a brand key fails, naming the key;
  Clarksville's `load_city` result is unchanged; `cities check murfreesboro-tn` lists the new items and stays NOT
  READY.
- Done when: the tests pass, no network is used, and `python -m cities` exits 0 (all valid).

### T3: sitegen picks the city
- Files: `sitegen/__main__.py` (parse `--city` before the imports; set `DAYLIGHT_CITY`; exit 2 on a clash; default
  `--facts`/`--out` when `--city` is given), `sitegen/config.py` (`CITY`, `SITE` via the registry, `PRIMARY`; the
  county path constants None when their keys are absent), `sitegen/build.py` (the `config.CITY` guard only).
- Tests: subprocess `python -m sitegen --help` with and without `--city`; the env clash exits 2; `config.PRIMARY`
  for Clarksville equals today's literals; T0 passes with and without `--city clarksville-tn`.
- Done when: the tests pass, and the Clarksville diff is empty (see the top of this file).

### T4: Murfreesboro-shaped fixture data
- Files: new `tests/fixtures/cities/murfreesboro-tn/facts.json` (`fixture: true`, schema-valid) and `wards.json`
  (at-large prints with `ward: null` and `title`).
- Content: made-up people with obviously fictional names; 7 members; 5 meetings over 2 years; sources at
  `https://example.org/murfreesboro-fixture/...` (never a real city document). Vice Mayor printed for member A at
  meetings 1-2 and member B at 4-5. Meeting 3 prints no titles. A Mayor printed at every meeting. One member leaves
  after meeting 3, and one is new from meeting 4. Two confirmed roll calls and one held roll call. One meeting
  prints two Vice Mayors (the conflict case), or a separate small fixture covers it.
- Tests: schema validation, and `check_references` passes.
- Done when: the fixture loads and no name in it matches a real official in any committed facts file (a test
  checks against the pinned snapshot).

### T5: At-large membership and title records
- Files: `sitegen/council.py` (`at_large_rows`), `sitegen/seats.py` (labels for `at-large` and `title-<slug>` from
  `PRIMARY`; seat order: titles in `primary.titles` order, then `at-large`, used only for one member's own record
  list, never for ordering members), `sitegen/views.py` (`Index` keyword arguments only, defaults unchanged); new
  `tests/test_at_large_seats.py`.
- Tests (on T4): A's Vice Mayor record runs from meeting 1 to 2, and B's from 4 to open. Meeting 3 shows only
  membership labels. The conflict meeting gets no title record, and the run log names `at-large/title-conflict`.
  Records ignore `officials[].title`: changing it changes no record. The leaver's record ends at meeting 3, and the
  newcomer's starts at meeting 4. Every record has a first and last source URL.
- Done when: the tests pass, `test_city_seats.py` passes unchanged, and T0 passes.

### T5b: At-large member gaps, review nits 3-5 (must-fix `at-large/member-gap`)
- Second hit in the `at-large/*` family: the invariant and every consumer of `at_large_rows` are in ADR 0012 decision
  5. Run at opus/high (a state rule). The engineer reads that table first and checks each consumer.
- Files: `sitegen/council.py` (`AT_LARGE_GAP_LISTS`, now 3, see below; the gap split in `at_large_rows`; `_END` sentinel in the
  title loop; refuse `pro_tem` + `title` on one print; extract `title_runs(prints, facts, titles)`, used by
  `at_large_rows` and later by a wards primary), `cities/registry.py` (`_check_primary` refuses duplicate
  `title_slug`s), `tests/test_at_large_seats.py`, `tests/test_cities.py`. No `views.py` change here (the
  `officials_page.seat_key` fix is T6's).
- Tests (made-up prints on the T4 fixture people): a member missing from 2 consecutive complete lists gets two
  records, each with its own first and last source; missing from 1 complete list, one record; missing from 2 lists of
  which one is incomplete (an unresolved name), one record; `Seats.on` inside the gap is None; a tail gap of one
  list followed by a reprint gives one record; a print with `pro_tem: true` and a `title` raises SeatsError naming the
  meeting; `primary.titles: [Vice Mayor, Vice-Mayor]` fails naming both; a print with `meeting_id: null` does not end
  a title run; every T5 test still passes.
- Done when: the tests pass, T0 passes, and the reviewer confirms each row of the consumer table.
- **Third hit, restated rule (2026-11-19, `at-large/short-confirm-blesses-cutoffs`).** Read decision 5's "Member
  gaps" bullet, its worked examples and the consumer table first; run at opus/high. Code: `_complete_lists` returns
  `{list key: frozenset of officials}` for the complete lists only (every name resolves; no size test, no reference);
  `_member_runs` splits between two consecutive prints only when the complete lists between them hold
  `AT_LARGE_GAP_LISTS` = 3 in a row with equal sets (lists not complete are skipped). Delete `AT_LARGE_SHORT_CONFIRM`.
  `latest_list_incomplete` and the tail are unchanged. Fixture: T4's M1-M5 plus later copies of M5 (`_later`, y1-y5).
- Tests to change: the 2-list split test becomes D out at y1-y3, back at y4: records (M1, M5, M5) and (y4, y4, None),
  `on(D, y2)` None, its docstring saying the same input from a repeated page defect splits too (accepted cost 2); a
  member out of 2 lists of any kind keeps one record; "three missing lists with one incomplete" becomes D out at
  y1-y4 with y2 unresolved, back at y5: split, and D out at y1-y3 with y2 unresolved, back at y4: one record; the
  title-gap test gives A a 3-list gap with equal sets (A two membership records; the Vice Mayor records unchanged);
  `AT_LARGE_GAP_LISTS == 3` and `not hasattr(council, "AT_LARGE_SHORT_CONFIRM")`.
- Tests to add (each asserts every at-large record, not only the member named):
  1. Counterexample (a): G leaves for good after M3, no H anywhere; D cut at M5 and y1 (`_later(..., 4)`). D: one
     record (M1, y4, None); G: one record (M1, M3, M3); A, B, C, E, F one current record each.
  2. Counterexample (b): no vacancy change beyond the fixture's; D cut at M2 and M3, E cut at M4. D (M1, M5, None) and
     E (M1, M5, None), one record each; 8 at-large records in all; `on(D, M2)` is the at-large label.
  3. Real vacancy of 3+ lists: G leaves after M3, no H, back at y2: G (M1, M3, M3) and (y2, y4, None), each with its
     own first source, `on(G, M5)` None; back at y1 instead: one record (M1, y4). (Keep the existing test's cases.)
  4. Absence across a membership change: D out at M2-M5, back at y1 (sets {A-C,E-G} twice, then {A-C,E,F,H} twice):
     one record (M1, y4, None). Build the later lists first (`_later`), then remove D, so y1-y4 still print D.
- Done when (third hit): these tests pass with the earlier T5b and T5 tests, T0 passes, and the reviewer checks each
  consumer-table row, including `current_of_seat`/`held_over_of_seat` (T6 must not call them with `at-large`).

### T4b: Salem-shaped fixture data (the milestone 1 slice)
- Files: new `tests/fixtures/cities/salem-or/facts.json` (`fixture: true`, schema-valid) and `wards.json` (ward
  prints: `ward: <n>`, `pro_tem: false`, optional `title`).
- Content: made-up people with obviously fictional names (none matches a real official in any committed facts file;
  test against the pinned snapshot); 4 wards plus a Mayor printed at every meeting; 6 meetings, 3 before 2026-07-01
  with sources at `https://example.org/salem-fixture/legistar/...` and 3 after with sources at
  `https://example.org/salem-fixture/escribe/...` (never a real city document); meeting ids `legistar-<n>` and
  `escribe-<guid>`. Ward 2 changes holder at meeting 4. One member is printed with a wrong ward once (dropped by
  `min_ward_prints: 2`). One meeting's list prints an unresolved name (held-over case). A "Council President" title
  printed for member X at meetings 1-3 and Y at 4-6. Two confirmed roll calls, one held roll call, and one roll call
  marked as a portal vote not yet read in minutes (shows "Not confirmed").
- Tests: schema validation; `check_references`; every meeting's documents carry one portal's prefix only.
- Done when: the fixture loads and the name test passes.

### T6: Build shape for a city-only site
- Files: `sitegen/build.py` (the decision 3 table: skip district pages and every county extra when its key is
  absent; build `ix` with `PRIMARY` and at-large rows; one-body export count; `confirmed_rate` for a council
  primary; `operator_person` only when set; corrections log path from settings), `sitegen/views.py` (`_nav` drops
  a `coming` entry without its page; `landing` and `landing_doors` from `PRIMARY`, with no address context for
  `at_large`; `purpose_line` from `PRIMARY`; `officials_page` basis line; the card's member rows), `sitegen/bodies.py`
  (no switch without `switch:`).
- **Collision:** ADR 0011 task B1 (`claude/data-off-main-b1`) edits `sitegen/views.py` (`CORRECTIONS_LOG` at about
  line 1339) and moves the log to `config/`. Start T6 only after B1 is merged, branch from that `main`, and read the
  log path from settings, defaulting to B1's `config/corrections-log.json`. No other T6 file is touched by ADR 0011.
- **Wards primary (ADR 0012 A1.1, added 2026-11-19):** for `seats: wards`, `ix` gets `holder_rows` rows built from
  `primary.ward_records` (council.yml's keys) plus `title_runs` for `primary.titles`; the card gets one row per ward
  with a current record, in ward order, then the Mayor, and the `district_lookup` link only when verified; no address
  context. `officials_page.seat_key` never orders by a title seat: by surname for `at_large`, by ward then other
  seats for `wards` (decision 5's consumer table).
- **One holder per seat (review finding `at-large/seat-single-holder`):** `Seats.current_of_seat` and
  `held_over_of_seat` (sitegen/seats.py) return one record, so T6 never calls them for `AT_LARGE_SEAT` (e.g. as
  `council.seat_list` does per seat); every member holds `at-large` at once.
- **Collision (2026-11-19):** B1b also edits `sitegen/build.py` and `sitegen/config.py` (small hunks). Start after
  B1 and B1b merge.
- Tests: new `tests/test_city_only_build.py` (subprocess builds of T4b and T4) asserts the pages written and not
  written per decision 3, that no link points at an unwritten page, the CSP has no geocoder host or frame hash, and
  the export has one body. For Salem: the Officials page is in ward order and the Council President holder is not
  moved up; each meeting page's source links all carry that meeting's portal prefix.
- Done when: the tests pass, and T0 and the Clarksville diff are unchanged.

### T7: Templates
- Files: `site/templates/index.html.j2` (the "Who represents you" card for `at_large`: `seat_basis.sentence` with its
  source link, one row macro per member, the Officials link; no form, config JSON, "Your seats" or ward and district
  list), `site/templates/officials.html.j2` (the at-large lede), `site/templates/search.html.j2` (the "coming" body
  line only when `city_body` is set), `site/templates/method.html.j2` and `about.html.j2` (county-only blocks
  guarded by `PRIMARY.seats` or the presence of their key), `site/templates/base.html.j2` (the T8 lines); tests in
  `tests/test_city_only_build.py`.
- Tests: every member row on the card and the Officials page has the same fields in the same order; members are in
  surname order; "Vice Mayor" appears on meeting pages 1-2 next to A and 4-5 next to B, each linked to that
  meeting's source page; the no-leak word list (decision 10) finds nothing in the Murfreesboro build;
  `test_site_neutrality` runs on that build too; the `design:accessibility-review` skill is run on the card.
  The ward form of the card (A1.1) on the Salem fixture: one row per ward plus the Mayor, same row macro, no address
  form, the A1.1 no-leak list for `wards` finds nothing, and the About and Method pages name both portals with their
  date ranges from `city.yml`.
- Done when: the tests pass, and the Clarksville diff is empty.

### T8: Named footer lines
- Files: `config/brand.yml` (`named_lines`), `cities/brand.py` (`LOCKED`, `LEGACY_DUPLICATES` for `drift`),
  `cities/brand.py` (`merge` adds `footer_line`, `support_line`; no `views.py` change), `site/templates/base.html.j2`, `site/templates/alerts.html.j2` (reads
  `site.support_line`), `tests/test_brand.py`.
- Tests: Clarksville's `footer_line` and `support_line` equal today's text exactly; Murfreesboro's read "Daylight
  Murfreesboro is provided as a free service by" and "Daylight Murfreesboro is free and always will be, ...";
  a city that sets `named_lines` fails.
- Done when: the tests pass and T0 passes. The `base.html.j2` change is in T7's PR, or in this one if T7 has
  already merged.

### T9: Site checks and the slice's end-to-end test
- Files: `qa/site_checks.py` (`--city`; skip the district, ward, county agendas, RPC, finance and committee checks
  when the settings lack them; add the at-large card checks), `tests/test_qa_tools.py`.
- **Collision:** B1 edits `qa/site_checks.py` (`corrections_log_urls`, about line 1048). Start only after B1 is
  merged.
- Tests: `python -m qa.site_checks --city salem-or build/salem-or/site` passes on the T4b build (the slice) with the
  ward card checks, and `--city murfreesboro-tn` on the T4 build with the at-large card checks; Clarksville's site
  checks give the same results as before. B1b also edits `qa/site_checks.py`: start after B1 and B1b merge.
- Done when: the M1 done-when at the top of this milestone holds, and `qa-engineer` verifies it against ADR 0012
  decisions 3-6, 9 and 10 at a commit SHA.

## Milestone 2: collectors read the city file (still no collection, no deploy)
| Task | Owner | Depends on | Parallel | Collides with ADR 0011 work? |
|---|---|---|---|---|
| C1 `collector city --city`, READY refusal | backend-engineer | T1, T2 | yes | no (the workflow's command line is unchanged) |
| C2 Printed titles from config in the minutes reader | backend-engineer | C1 | after C1 | **check:** B1 edits `collector/names.py`, `facts.py`, `verify.py`, `export.py`; C2 must not touch them (it touches `city_minutes.py`, `city_build.py`, `agenda_center.py`). If name resolution needs `names.py`, wait for B1. |
| C3 Murfreesboro launch checklist (robots, terms, portal values) | backend-engineer (manager runs the polite reads) | C1 | yes | no. **Parked 2026-11-19:** the host blocks us (no retry, no workaround); waits on the owner |
| E0 Record sample answers (eScribe calendar POST, one FileStream document, one Legistar events and eventitems answer) | manager (polite reads), backend-engineer (fixtures) | none | yes (first) | no |
| E1 eScribe reader, fetcher `post_json`, registry entry, fixtures | backend-engineer | E0, T1 | with T5b, T4b | no (`collector/escribe.py` new, `collector/fetch.py`, `cities/readers.py`; none is a B1/B1b file) |
| E3 Date-stitch of two sources; both readers wired into `collector city fetch` | backend-engineer | E1, E2, C1 | after C1 | **check:** must not touch `collector/facts.py`, `export.py`, `names.py`, `verify.py` or `test_city_shrink_guard.py` (B1/B1b); it touches new `collector/stitch.py`, `city_run.py`, `city_build.py` (row intake only) |
| E4 Salem minutes reader (attendance with wards, votes), from recorded minutes samples | backend-engineer (opus/high) | E0 (plus 2-3 recorded minutes, one per portal and era), C2 | after C2 | **check:** name resolution may need `collector/names.py` (B1/B1b): if so, start after they merge |

- **C1.** Files: `collector/city_run.py` (`--city`, with `--locality` as an alias; registry sources and hosts; exit 2
  when not READY for `fetch`/`run`), `collector/__main__.py` (`run --city <other>` refused), tests with a stub
  fetcher. Tests: Murfreesboro `fetch` exits 2 naming the unverified items with no socket opened; `build` works
  offline on stored files; Clarksville's defaults are unchanged. Security review: yes (fetcher allowlist).
- **C2.** Files: `collector/city_minutes.py`, `collector/city_build.py`, `collector/agenda_center.py`
  (`printed_titles`), tests on a made-up minutes text. Tests: Clarksville's collector fixtures give byte-identical
  facts and wards; a fixture attendance line "Vice Mayor X" gives the row `title: Vice Mayor`, and the name resolves
  without the title.
- **C3.** Read robots.txt and terms for `www.murfreesborotn.gov` by hand (one polite request each; stop if blocked),
  record them in `platform-facts.md` and `city.yml`, and fill `agenda_center.yml`, `site.yml` `primary` and
  `seat_basis`. Done when `cities check murfreesboro-tn` lists only the items that need the owner (none expected) or
  real collection. Launch-year collection is a separate step after READY, and comes before any go-live ask.
  **Parked** (ADR 0012 A1): one request on 2026-11-19 got a Cloudflare block; nothing more is sent.

### Salem tasks (ADR 0012 amendment A1, 2026-11-19)
No task below opens a socket in its tests (sockets refused, as everywhere). Fixtures are recorded public answers,
trimmed to the fields used, with any personal data that is not an official's name removed; a fixture's file name
carries its date of capture.
- **E0. Record sample answers.** The manager makes, at our 10 s pace and only on hosts whose robots.txt was read
  2026-11-19: one `POST /MeetingsCalendarView.aspx/GetCalendarMeetings` on `pub-salem.escribemeetings.com` for
  2026-07-01..2026-08-31; one `FileStream.ashx?DocumentId=` GET for one council PostMinutes; one Legistar
  `events?$filter=EventBodyId eq 138` page for June 2026 and one `eventitems` answer. Before the minutes PDF on
  `salem.legistar1.com` is asked, its robots.txt is read and recorded. Each answer is saved under
  `collector/tests/fixtures/escribe/` or `.../legistar/` with the request in a sibling `.request.txt`, and the
  field names seen are written into `config/cities/salem-or/platform-facts.md` ("Portal"). Stop on any block. Done
  when the files are committed and platform-facts.md names the POST body keys and answer fields.
- **E1. eScribe reader.** Files: new `collector/escribe.py` (`load_config`, `calendar_request(cfg, window)`,
  `listing_rows(cfg, answer)`, `POST_PATHS`, `allowed_hosts`; field names exactly as in the E0 sample),
  `collector/fetch.py` (`post_json` and a `post_paths` constructor argument, default empty), `cities/readers.py`
  (the `escribe` Reader of A1.4), new `collector/tests/test_escribe.py`, `collector/tests/test_fetch.py` additions.
  Tests: on the E0 answer, only the configured body names become rows; agenda and minutes URLs resolve against the
  config host only, a document URL on another host is dropped and logged; video is a link only; meeting ids are
  `escribe-<guid lowercase>`; kinds come from `kind_rules`; a meeting without PostMinutes has `minutes_url: None`. The
  fetcher refuses a POST to an undeclared path or host with no request, refuses one when robots disallows it,
  treats a 3xx as a failure, caps the answer at 5 MB and waits `MIN_DELAY`; `get` behaviour is unchanged (existing
  fetch tests pass). Security review: yes (`collector/fetch.py`). Done when the tests pass and `python -m cities`
  exits 0.
- **E2. Salem config.** Files: `config/cities/salem-or/city.yml` (`sources` legistar `until: "2026-07-01"` and escribe
  `from: "2026-07-01"`; `site_file`; `allowed_hosts`: `webapi.legistar.com`, `salem.legistar.com`,
  `pub-salem.escribemeetings.com`, each with `robots: "404, no robots.txt (2026-11-19, team cloud session)"` and
  `terms: UNVERIFIED`; `salem.legistar1.com` with `robots: UNVERIFIED` until E0 reads it; `www.cityofsalem.net` is not
  listed, because nothing is fetched from it; `district_lookup: UNVERIFIED`), new `config/cities/salem-or/site.yml`
  (`place_name: Salem`; `primary:` `key: council`, `name: Salem City Council` UNVERIFIED, `label: City Council`,
  `record` = the eScribe portal, `seats: wards`, `ward_records` (council.yml's keys, `min_ward_prints: 2`,
  `title_seats: {Mayor: city-mayor}`), `titles: [Council President]` UNVERIFIED, `member_title: Councilor`
  UNVERIFIED, `seat_basis` UNVERIFIED), new `config/cities/salem-or/escribe.yml` (host, `body_names`,
  `agenda_types`, `minutes_types`, `kind_rules`, `video_hosts`, each UNVERIFIED until E0's sample confirms it), new
  `config/cities/salem-or/corrections-log.json` (`[]`); `cities/registry.py` (source `from`/`until`: dates, half-open,
  abutting, no overlap, no gap; `primary.ward_records` validated as `config.load_council`; `seat_basis` required for
  `wards`), `cities/check.py`, `tests/test_cities.py`. Tests: overlapping ranges, a gap, or two open-ended sources
  fail naming the sources; Salem loads; `cities check salem-or` is NOT READY and lists terms, `salem.legistar1.com`
  robots, `seat_basis`, `district_lookup` and the UNVERIFIED portal values. The manager reads each host's terms page
  once, if one exists, and records it (open question 9 of ADR 0012). Done when the tests pass and no network is used
  in them.
- **E3. Date-stitch.** Files: new `collector/stitch.py` (`stitch(rows_by_source, ranges)`, A1.3), `collector/city_run.py`
  (`fetch` runs each source's reader for the windows inside its range; `build` stitches before facts),
  `collector/city_build.py` (accepts stitched rows; no change to how rows become facts), new
  `collector/tests/test_stitch.py`, a stub-fetcher run test. Tests: rows on both sides of 2026-07-01 are kept from their
  owners; a same-date, same-kind pair where only one has minutes keeps that one and logs `stitch/seam-duplicate` with
  both URLs; a pair where both have minutes keeps the range owner; different start times keep both; a row outside
  its range with no match is kept and logged `stitch/out-of-range`; no kept row carries a URL of the other portal;
  the run is deterministic (same input, same bytes). `fetch` for Salem exits 2 while it is not READY (C1), with no
  socket opened. Done when the tests pass and Clarksville's collector fixtures give byte-identical output.
- **E4. Salem minutes reader.** Reads the attendance list (names, wards, present or absent, printed titles) and roll
  calls from Salem's minutes in both eras, writing `wards.json` prints in the A1 Interfaces shape and votes that go
  through the existing verifier. Shaped only by recorded minutes samples (E0 plus one minutes file per era), never
  by guesses about the format. Its own design note comes first (the minutes format is unknown today). Not needed
  for milestone 1, which runs on T4b.

## Milestone 3: per-city deploy (after ADR 0011's cutover C1 and the V1'' probe pass)
| Task | Owner | Depends on | Parallel | Collides with ADR 0011 work? |
|---|---|---|---|---|
| P0 Brain Trust on decision 8 (subdomain repos vs subpath) | manager | none | yes | no |
| D0 Verify cross-repo attestation reads (the unverified fact) | devops-engineer | P0 | yes | no |
| D1 Workflow: build each live city; J2 pushes `site/<slug>` and attests | devops-engineer | ADR 0011 C1 + V1, P0, D0 | no | **yes: `.github/workflows/daily-update.yml`**, so only after the cutover, as one reviewed change |
| D2 `protect-main`: ruleset R-S for `site/*` | devops-engineer | ADR 0011 D1 merged | with D1 | **yes: `scripts/protect-main.*`**, after ADR 0011's D1 |
| D3 City deploy repo template | devops-engineer | D0 | yes | no (lives in `cities/templates/deploy-repo/`, never `deploy/`) |
| D4 Tripwire covers each live city's published facts | backend-engineer | ADR 0011 B4 merged | after B4 | **yes: B4's tripwire code**, extended after it lands |
| D5 Owner steps (decision 8, hard stops 1-4; for Salem: repo `gn0sh/daylight-salem`, `salem.daylight` CNAME) | Brian, prepared by the manager | D1-D4, E2 READY, E4, launch year | no | no |
| D6 Uptime monitor and Better Stack entries | devops-engineer | D5 | no | no |

Security review for D1-D4 is in session (CI, deploy and hard-stop area), with a fresh review for the milestone.

## How the plan avoids colliding with ADR 0011
- No M1 or M2 task touches `.github/workflows/`, `scripts/`, `deploy/`, `data/` or the ADR 0011 config moves.
  Fixtures live in `tests/fixtures/`, and the Clarksville diff uses a named data tree.
- There are two file overlaps, each sequenced after B1 merges: `sitegen/views.py` (T6) and `qa/site_checks.py` (T9).
  B1's hunks are one-line path changes. T6 reads the moved log path from settings rather than moving it again.
- C2 stays out of the four collector files B1 edits.
- Salem tasks (2026-11-19): T5b, T4b, E0, E1 and E2 touch no B1/B1b file and can start now. T6 also waits for B1b
  (`sitegen/build.py`, `sitegen/config.py`), T9 for B1b (`qa/site_checks.py`). E3 avoids `facts.py`, `export.py`,
  `names.py`, `verify.py` and the shrink-guard test; E4 waits for B1/B1b if it needs `names.py`.
- Deploy work (D1, D2, D4) starts only after the cutover, and rides on its pieces (J2, the attestation, R-D's
  pattern, the tripwire) rather than adding a writer or an attester.
