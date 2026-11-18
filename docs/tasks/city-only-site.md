# Tasks: city-only site (ADR 0012)

Design: `docs/adr/0012-city-only-site.md` (decision numbers below are its own). Every task works in its own worktree
on its own branch from `origin/main`. It runs the preflight (`python -m pytest -q`, plus the site checks for the
sitegen tasks) in session and pastes the output in its PR. No task fetches anything, deploys, or writes under
`data/`. Every PR goes to `code-reviewer`. PRs touching the fetcher allowlist (T1, C1) or the workflow, rulesets or
deploy (D1-D3) also go to `security-engineer`. Problem families: `city-only/clarksville-identical`,
`city-only/no-county-leak`, `at-large/title-from-record`, `city-only/import-layers`.

**Clarksville byte-identical, every sitegen PR (T3-T9):** the T0 golden test passes. The PR also pastes
`diff -r before/ after/` (empty) of `python -m sitegen --facts <F> --out <D> --target pages`, run at the base
commit and at the head commit on the same data tree. Before ADR 0011's cutover that tree is `data/`; after it, one
`records-data` commit from `scripts/fetch-data`, named in the PR. The same check is repeated with
`--city clarksville-tn`.

## Milestone 1: thin end-to-end slice (fixture Murfreesboro builds locally; Clarksville unchanged)
Done when `python -m sitegen --city murfreesboro-tn --facts tests/fixtures/cities/murfreesboro-tn/facts.json --out
build/murfreesboro-tn/site` writes a site that passes `python -m qa.site_checks --city murfreesboro-tn`, the full
suite passes, and the T0 digests are unchanged.

| Task | Owner | Depends on | Parallel | Collides with ADR 0011 work? |
|---|---|---|---|---|
| T0 Clarksville golden digests | backend-engineer | none | yes (first) | no |
| T1 Import layering (hosts, windows) | backend-engineer | none | yes | no |
| T2 Registry: `site_file`, `primary`, `place_name`, shared keys | backend-engineer | T1 | with T4 | no |
| T3 sitegen `--city`, `config.CITY`, `config.PRIMARY` | backend-engineer | T0, T2 | no | no |
| T4 Murfreesboro fixture data | backend-engineer | none | yes | no |
| T5 At-large membership and title records | backend-engineer | T3, T4 | with T8 | no |
| T6 Build shape: county pieces off, nav, landing context | backend-engineer | T3, T5, **B1 merged** | no | **yes: `sitegen/views.py`** |
| T7 Templates: front-page card, Officials lede, guards | frontend-engineer | T6 | no | no |
| T8 Named footer lines (brand) | backend-engineer | T3 | with T5 | no |
| T9 Site checks `--city`, city-only end-to-end test | qa-engineer (checks) + backend-engineer (code) | T7, T8, **B1 merged** | no | **yes: `qa/site_checks.py`** |

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
- Tests: new `tests/test_city_only_build.py` (subprocess build of T4) asserts the pages written and not written per
  decision 3, that no link points at an unwritten page, the CSP has no geocoder host or frame hash, and the export
  has one body.
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
- Tests: `python -m qa.site_checks --city murfreesboro-tn build/murfreesboro-tn/site` passes on the T4 build;
  Clarksville's site checks give the same results as before.
- Done when: the M1 done-when at the top of this milestone holds, and `qa-engineer` verifies it against ADR 0012
  decisions 3-6, 9 and 10 at a commit SHA.

## Milestone 2: collectors read the city file (still no collection, no deploy)
| Task | Owner | Depends on | Parallel | Collides with ADR 0011 work? |
|---|---|---|---|---|
| C1 `collector city --city`, READY refusal | backend-engineer | T1, T2 | yes | no (the workflow's command line is unchanged) |
| C2 Printed titles from config in the minutes reader | backend-engineer | C1 | after C1 | **check:** B1 edits `collector/names.py`, `facts.py`, `verify.py`, `export.py`; C2 must not touch them (it touches `city_minutes.py`, `city_build.py`, `agenda_center.py`). If name resolution needs `names.py`, wait for B1. |
| C3 Murfreesboro launch checklist (robots, terms, portal values) | backend-engineer (manager runs the polite reads) | C1 | yes | no |

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

## Milestone 3: per-city deploy (after ADR 0011's cutover C1 and the V1'' probe pass)
| Task | Owner | Depends on | Parallel | Collides with ADR 0011 work? |
|---|---|---|---|---|
| P0 Brain Trust on decision 8 (subdomain repos vs subpath) | manager | none | yes | no |
| D0 Verify cross-repo attestation reads (the unverified fact) | devops-engineer | P0 | yes | no |
| D1 Workflow: build each live city; J2 pushes `site/<slug>` and attests | devops-engineer | ADR 0011 C1 + V1, P0, D0 | no | **yes: `.github/workflows/daily-update.yml`**, so only after the cutover, as one reviewed change |
| D2 `protect-main`: ruleset R-S for `site/*` | devops-engineer | ADR 0011 D1 merged | with D1 | **yes: `scripts/protect-main.*`**, after ADR 0011's D1 |
| D3 City deploy repo template | devops-engineer | D0 | yes | no (lives in `cities/templates/deploy-repo/`, never `deploy/`) |
| D4 Tripwire covers each live city's published facts | backend-engineer | ADR 0011 B4 merged | after B4 | **yes: B4's tripwire code**, extended after it lands |
| D5 Owner steps (decision 8, hard stops 1-4) | Brian, prepared by the manager | D1-D4, C3, launch year | no | no |
| D6 Uptime monitor and Better Stack entries | devops-engineer | D5 | no | no |

Security review for D1-D4 is in session (CI, deploy and hard-stop area), with a fresh review for the milestone.

## How the plan avoids colliding with ADR 0011
- No M1 or M2 task touches `.github/workflows/`, `scripts/`, `deploy/`, `data/` or the ADR 0011 config moves.
  Fixtures live in `tests/fixtures/`, and the Clarksville diff uses a named data tree.
- There are two file overlaps, each sequenced after B1 merges: `sitegen/views.py` (T6) and `qa/site_checks.py` (T9).
  B1's hunks are one-line path changes. T6 reads the moved log path from settings rather than moving it again.
- C2 stays out of the four collector files B1 edits.
- Deploy work (D1, D2, D4) starts only after the cutover, and rides on its pieces (J2, the attestation, R-D's
  pattern, the tripwire) rather than adding a writer or an attester.
