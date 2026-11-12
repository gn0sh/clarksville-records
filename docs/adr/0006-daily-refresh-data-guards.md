# ADR 0006: Data guards in the daily refresh (city, county, RPC, tests)

Status: accepted for launch (software-architect, 2026-11-12). Loop rule: `shrink/` and `pipeline/` hit again
(security `pipeline/shrink-guard-freezes-all`, G5 `pipeline/parse-failure-freezes-all`, QA a605d25
`shrink/city-listing-unguarded`, code review 4af570d `shrink/city-shrink-freezes-all-sources`). The county rule this
generalises is `docs/architecture/pipeline-limits-invariant.md` "Rule 3: the shrink guard" (G1-G4); it is unchanged.

## Context
At 4af570d the city guard turns any drop into exit 2, so the Collect step fails and nothing publishes. 126 of 174
CivicClerk rows have no minutes (70 dated in the future, to 2029); a cancelled event (`isDeleted`, civicclerk.py:277)
fires it daily. Its `--allow-shrink` accepts every drop, so a local run with an empty store would publish a gutted
city. The facts check compares meeting ids only: a re-posted or missing minutes file loses verified roll calls
silently. The daily `pytest -x` (daily-update.yml:233) reads live data, so legitimate change can halt it.
Verified on the committed city facts (unchanged since a605d25): 401 meetings, 586 sources, 2,354 roll calls; every
meeting has a `source_id` and every roll call, motion and item event carries its meeting's (0 mismatches); no
minutes source carries two meetings. So the county unit (one source document and its meetings) holds for the city.

## Invariants
- **I1 Published verified data never silently changes.** A committed meeting with minutes read, its verified roll
  calls, votes, motions and item events, are never dropped, unverified or changed by a transient cause (empty or
  partial listing, fetch/parse failure, store gap, timeout). Only a correction (the source itself replaced the file)
  or a person (I4) changes them, and both are reported.
- **I2 One source's anomaly never blocks another.** A guard firing for one source (city, county, RPC) is a warning:
  that source publishes its last good records for the affected meetings, raises its own issue, and every other
  source and the site commit and deploy. Known exception until Nov 18: hard failures (below) still stop all.
- **I3 The daily test gate fails only on a bug.** Tests that read live data assert only what the run guarantees by
  construction (I1 via the guards, schema, provenance, privacy, no leaks). Counts, ids, shas, pages, titles and
  "id X absent" are pinned on committed snapshots, never on live files.
- **I4 A deliberate drop names its ids.** No flag accepts "every drop". The scheduled run can never drop.

## Consumers and producers (exit codes; how daily-update.yml treats them)
| Step | Codes | Workflow (Collect step, daily-update.yml:126-202) |
|---|---|---|
| city run (Agenda Center + CivicClerk, `city_run.py`) | 0; 2 listing not read; 3 G4; 5 refused; **7 kept (new)** | 2/3/5 fail the step (hard); 7 -> `city_kept=yes`, city=0, own issue |
| county run (`__main__.cmd_run`: county facts, finance, agendas, RPC, sitegen, export) | 0; 2; 3; 4 offline; 7 kept; 5/6 RPC | 2/3/4 hard; 7 kept issue; 5 RPC issue; 6 warning |
| RPC (`rpc.run_step`, inside county) | step codes, mapped to 5/6; files restored unless ok | never hard |
| Site checks (`qa.site_checks`) and `pytest -q -x` on live data | pass/fail | fail = nothing uploaded, pushed or deployed |
| Issues | "Daily update failed" (hard), RPC, county kept, **city kept (new)**, stale-source | all `--app github-actions`, `--body-file` |
| push / deploy | `success()` of update; deploy LOCKED (`RECORDS_DEPLOY_ENABLED`) | unchanged; deploy stays locked |

## Decision: fix list (backend-engineer; one PR, before launch)
1. **`shrink/city-shrink-freezes-all-sources`.** `city_run.py`: add `KEPT = 7`; precedence 5 > 2 > 3 > 7 > 0; a
   guard firing is no longer a `failures` row. `guard_listing` (:78): a vanished row **without** `minutes_url` dated
   on or after the run date (UTC) is dropped and listed under `dropped_unminuted` (no code); any other vanished row is
   kept as committed (as now) and listed under `kept_listing_rows` (7). Workflow: `if [ "$city" = 7 ]` sets
   `city_kept=yes; city=0`; new step "Open or update the city meetings-kept issue", a copy of the county kept step
   (`always()`, continue-on-error, body from `build/city-report.json` via jq into a file, backticks stripped,
   `head -c 3000`). Update the step's comment block and runbook :21-30. Tests: rewrite
   `collector/tests/test_city_shrink_guard.py` :48, :92, :132 (exit 2 -> 7, committed rows/meetings written back);
   add `test_a_cancelled_future_event_without_minutes_drops_without_a_warning` and
   `test_a_vanished_row_with_minutes_is_kept_and_warns`; `tests/test_workflow_lock.py:342` cases add (7,0,0),
   (7,7,0), (7,5,0), (7,2,1), (7,3,1); `tests/test_rpc_daily.py:534-541` step text; the issue-step pattern test
   covers the new step. **Workflow change: yes** (Collect mapping + one issue step; no new input, deploy untouched).
   Needs a security-engineer delta review.
2. **`shrink/city-rollcall-unguarded`.** Move `shrink_guard`, `check_unit`, `keep_closure`, `keep_documents`,
   `vote_content` from `collector/__main__.py` to `collector/shrink_guard.py` (re-exported, county tests unchanged)
   and run them in `city_run.main` (:233-246) on the city facts, guarding committed meetings whose source is a
   minutes source. City specifics: `superseded` = store-superseded shas plus the old sha of any meeting whose listing
   row now names a different `minutes_url` (the listing replaced the file: correction), on both paths only when the
   new file was read (`minutes_status` read; else the meeting is kept, 7, until it reads or `--allow-drop`:
   `shrink/city-correction-on-unread-file`); a kept meeting also takes back
   its committed `agenda_source_id` source and its `wards.json` entries; gates (AC-P1, G4) recomputed on the merged
   facts. Write the merged facts and wards (never "write nothing"). Report `kept_meetings`, `corrections`. Tests:
   `test_city_missing_minutes_keeps_that_meeting_only` (store lacks one file: its records and wards byte-identical,
   another meeting's new data written, exit 7), `test_city_reposted_minutes_is_a_correction` (new url + sha: new
   reading wins; 7 only if verified fell or votes changed),
   `test_city_reposted_minutes_not_read_keeps_the_committed_meeting` (not fetched, parse failed: kept, 7),
   `test_city_kept_twice_is_byte_identical`,
   `test_city_kept_meeting_agenda_source_is_published`, `test_city_unit_holds_on_committed_facts`.
3. **`shrink/city-allow-shrink-unscoped`.** Replace city `--allow-shrink` with `--allow-drop ID[,ID]` (meeting ids, or
   listing row keys, as printed in the kept entries); an id matching nothing exits 2 and writes nothing; each drop is
   listed under `allowed_drop`. Not wired into the workflow. Runbook: the manual path is
   `python -m collector city run --allow-drop <id> --limit 0` locally, then a PR. Tests:
   `test_allow_drop_with_an_empty_store_drops_only_the_named_meeting` (empty store, two rows gone, one named: the
   other is kept, exit 7), `test_allow_drop_unknown_id_is_refused`, `test_city_allow_shrink_flag_is_gone`.
4. **`pipeline/tests-pin-live-data`** (hit 3). `tests/test_city_verify_data.py`: delete the live `:255` line
   (snapshot already covers it at :172, :181); `:245` keep only snapshot meetings with `minutes_status` read, minus a
   `DROPPED = ()` tuple a deliberate-drop PR extends; `:212-226` move the sha, page and exact `wards` entry to the
   snapshot (extend `project` with officials' `name_source` and configured wards; facts unchanged since a605d25), keep
   on live only "configured once, ward 2, cites a live source, no attendance before seating", and scope the
   "J eff Henley" text check to snapshot meetings. Extend the `:275` harness to four live changes: a new meeting, a
   cancelled future meeting, a re-posted document (one meeting's roll calls under a new sha), a renamed D1 title; all
   tests pass on each. `collector/tests/test_civicclerk.py:474`: for known event ids compare id and `page1` only;
   extend the `:480` test with a renamed title and a removed unminuted row (pass) and the existing bad row (fail).
5. **Nit (`city-verify/moved-row-note-ambiguous`).** `site/templates/_macros.html.j2:25` says "Who moved and seconded
   it is confirmed" but 726 of 1,724 city motions have no seconder: say "Who moved it" when `seconded_by` is empty.
   Test: a no-seconder case in `tests/test_moved_row_note.py`.

## Alternatives considered
- Reviewer (c), pass the workflow's boolean `allow_shrink` to the city: rejected; it re-creates the unscoped drop (I4).
- City guard as exit 2 with `--allow-shrink` (4af570d): rejected; breaks I2 daily on a cancelled event.
- Don't guard unminuted rows at all: rejected for past rows; an empty page would silently remove published agendas.

## Consequences
A cancelled future event drops quietly; anything else that vanishes publishes as last committed and opens one city
issue that repeats daily until it clears or a person runs `--allow-drop`. Run time unchanged.

## Nov 18 batch (not before launch)
- G5 `pipeline/parse-failure-freezes-all`, widened: city 2 (listing not read), 5 (refused), 3 (G4) and county 2 still
  stop every source (I2 exception). Decide per stage: keep-and-warn vs hard.
- County `--allow-shrink` and the `allow_shrink` input are still boolean: scope to ids (I4).
- A workflow input for city drop ids, only if the local `--allow-drop` path proves clumsy.
- I3 sweep of the other live-data tests and `qa.site_checks` (about 25 test files read live data; checked here:
  city_verify_data, civicclerk, council_pages, city_seats, days). Known: `tests/test_council_pages.py:188`
  `n <= 230` is 207 today and grows each year; tie it to `config.MAX_FILES`.
- Unverified: whether the city ever refetches a known minutes url, so a same-url re-post is seen as a correction.
- RPC per-meeting keep and RPC correction warning (already listed in the limits invariant, before `hold_motions` off).
