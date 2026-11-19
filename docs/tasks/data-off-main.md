# Tasks: data off `main` (ADR 0011)

Architecture: `docs/architecture/v1-fail-2026-11-18.md` (invariants I-main'', I-data'', I-prov, I-run'', I-pub, and
the consumer table; every task below names its rows). Gate: **nothing past U3 starts until U3 PASS.** Tests run in
session (`python -m pytest -q`), and the output goes in each PR. Each PR is reviewed by `code-reviewer`. Every PR
touching the workflow, rulesets or scripts is also reviewed by `security-engineer` (CI and hard-stop area: in
session, fresh review per milestone). Problem family `main-protect`. A third hit means the architect re-plans and
the manager escalates. Amended 2026-11-18 for the PR #54 security review (`docs/reviews/pr54-security-review.md`):
its findings are in the done-when of U3-1, B2-B4, D1, D3, V1 and W1, tagged `F<n>`; "drift" is its most serious item.
Amended 2026-11-18 for B1's person-run writers (ADR 0011 decision 2a, invariant I-in, note rows TR, MP, FB, SC, LS):
new task B1b; B4, D3, S1 and W1 gained items.

| Task | Owner | Depends on | Parallel |
|---|---|---|---|
| N1 Probe guard refuses unconditionally | devops-engineer | none | **done** (#53) |
| N2 Baseline window lists 2b20704 | devops-engineer | none | **done** (#53) |
| U3-0 Can the team token write the ruleset? | manager | none | **done: no** (proxy 403) |
| U3-1 `scripts/u3-toggle` + docs PR P | devops-engineer | U3-0 | now |
| U3-2 Run the control | Brian (manager runs the merge) | U3-1, N1 | no |
| B1 Data inventory and curated-input move | backend-engineer | U3 PASS | **done** (branch `claude/data-off-main-b1`) |
| B1b Person-run inputs to `config/` (I-in) | backend-engineer | B1 | yes, with B2/B3 and D1/D2 (no workflow edit) |
| B2 Gate: D, I-data'', I-prov, I-main'' | backend-engineer | U3 PASS | yes (workflow file conflicts with B3/B4: one branch, sequential commits) |
| B3 Push job: records-data + attestation | backend-engineer | U3 PASS | with B2 |
| B4 Update job: S+D checkout, tripwire, build-info, city-books issue text | backend-engineer | B1, B1b | after B1b |
| D1 `protect-main` R1'' + R-D + checks; `merge-reviewed` refusals | devops-engineer | U3 PASS | yes |
| D2 `fetch-data`, preflight | devops-engineer | U3 PASS | yes |
| D3 Cutover script (Operator's order) + rollback | devops-engineer | B1, B1b, B2-B4, D1, D2 | no |
| S1 Security review of B+D milestone | security-engineer | B1, B1b, B2-B4, D1-D3 | no |
| C1 Cutover session | manager + Brian | S1, review approve | no, away from 09:07 |
| V1 V1'' probe rewrite and run | devops-engineer | C1 | no |
| W1 Docs: invariant doc, platform facts, runbook, ADR status | technical-writer (architect checks) | C1 (V1 for final status) | yes |

## N1 + N2: containment (done, PR #53)
`scripts/v1-probe.{sh,ps1}` refuse unconditionally, naming ADR 0011 and that the 2026-11-18 V1' was FAIL. The test
asserts the refusal comes before any write. The runbook 4.7.1 window check lists 3ef440a (#40) and 2b20704 (#49) as
the known bot merges.
Done when: tests pass, and a dry run of each script prints the refusal and exits 1 without a GitHub write.

## U3-0: may the team's token write ruleset 27502319? (done: no)
One PUT of the identical live body, then read it back unchanged. Result: **no**. The team's cloud session got a
proxy 403 at 17:37 UTC 2026-11-18, and the read-back was unchanged (`docs/status.md` run ledger). So every ruleset,
R2, environment and R-D write is Brian's, from his PC (U3, D3, C1, any rollback). W1 adds it to platform facts.

## U3-1: `scripts/u3-toggle.{sh,ps1}` and docs PR P
Per `docs/ops/u3-positive-control.md`: preflight, apply R1'', merge window, verdict, restore in `finally`/`trap`,
and `--restore`. F6: one PUT-body builder that copies only the whitelisted fields (`name`, `target`,
`enforcement`, `conditions`, `rules`, `bypass_actors`) and changes only the `pull_request` parameters; the read-back
must match the expected body exactly on those fields; the backup file's full path is printed when it's written and
in every restore or failure message. Tests use a stub `gh` to cover the restore-on-every-exit path (merge refused,
Ctrl+C, read failure), the time-window refusal, a live body with an extra field (dropped, not sent) and a read-back
that differs in one field (restore, then stop). PR P is a real docs change: the `docs/platform-facts.md` entry "U1 false: rule suites
pass for #48, #49, #52".
Done when: tests pass, and code review and security review approve.

## U3-2: run the control
U3-0 = no, so Brian runs it: the card in `docs/ops/u3-positive-control.md` "Who runs it". The verdict goes in
`docs/status.md` and platform facts. FAIL-U3: the architect writes the fallback (B plus a sender repository) as an
ADR 0011 amendment. FAIL-RULE: the architect re-plans (third hit).
Done when: the verdict is recorded, with the rule-suite id and the restored ruleset read.

## B1: inventory and curated inputs (rows D, CFG)
- List every tracked `data/` file with its writer: grep the writers in `collector/`, `sitegen/` and `qa/`, plus
  `git log` authors. Verified so far: `names.yml` (`collector/names.py:29`), `procedural-titles.yml`
  (`collector/facts.py:23`) and `corrections-log.json` (`sitegen/views.py:1339`, `qa/site_checks.py:1053`; only
  gn0sh commits) are curated. `wards.json` is collector output (`collector/city_run.py:461`).
- Move the curated files to `config/` and update the readers and tests. Narrow `SHAPE''` to json and
  `changes.jsonl`, and add the curated-name refusal list.
- Add `config/published-fact-changes.yml` (empty list) and its schema.

Done when: the inventory table is in the PR, every reader uses `config/`, and tests pass with `data/` holding only
collector output.

## B1b: person-run inputs to `config/` (I-in; rows TR, MP, FB, SC, LS, T)
No workflow edit (the issue text is B4's), so it runs beside B2/B3 on its own branch.
- **Transcripts (TR):** `git mv` the folder to `config/localities/clarksville-tn/transcripts/`. `import` and
  `remask` write there and read the facts and `civicclerk-listing.json` from `data/` (filled by `fetch-data`).
  `sitegen/transcripts.py` `load`, `sitegen/build.py:549` and `qa/site_checks.py:234` read only the config folder,
  with no fallback to `data/`. Update the module docstrings and the tests that name the old path.
- **Map manifest (MP):** `git mv` to `config/maps/manifest.json`; `tools/fetch_map.py` default and
  `config/site.yml:17` follow.
- **City books (FB):** `config/fin-books-accepted.yml` (empty list) and `schema/fin-books-accepted.schema.json`
  (`locality`, `book_id`, `source_sha256` as 64 hex, `listed_on`, `reason`). `worse_than_committed` drops a book's
  keep reasons only when an entry names that locality and book and the new build's `source_sha256`, and the stored
  book's sha256 differs from it.
- **Scrub tool (SC):** remove the rewrite mode of `tools/scrub_rpc_phones.py`; keep `--check` (read-only).
- **Shape (T):** `collector/data_shape.py`: `CURATED_NAMES` gains `fin-books-accepted.yml`, plus a refusal of any
  entry under `data/maps/` or inside a `transcripts/` folder (shown safely, like the others). B2 copies it into the
  workflow with the test that keeps the two equal.
- **Git-listed readers (LS):** `qa/pii_scan.py` and `tests/test_committees_daily.py:26` read the `data/` tree on
  disk, not `git ls-files`, and fail on an empty `data/`.

Done when tests show: an import and a remask write only under `config/`; the build finds the transcripts with no
`data/.../transcripts/` present, and a copy left in `data/` is not read; `fetch_map` writes only under
`config/maps/` (stub fetcher); an accepted entry lets a replaced book through once, a stale entry (stored sha256
equals the listed one) and an entry for another book change nothing; the scrub tool has no write path and
`--check` exits 1 on a phone; `data_shape` refuses `data/maps/manifest.json`,
`data/localities/x/transcripts/a.json` and `fin-books-accepted.yml` at any depth; the leak scan fails on an empty
`data/` and finds a planted needle in a fetched `data/` file; the full suite passes. `git grep -n
'data/maps\|/transcripts/\|scrub_rpc_phones'` output is in the PR, each hit explained.

## B2: gate (rows G, B)
Read the `records-data` head once and output `data_sha`. Then:
- I-data'' on `D`;
- I-prov: rebuild the listing file, then `gh attestation verify` with the flags from the note (`--cert-identity`
  `...daily-update.yml@refs/heads/main`, `--source-ref`, `--predicate-type`, `--deny-self-hosted-runners`), or
  accept the seed: `D` has no parents and matches `RECORDS_DATA_SEED_DIGEST` (F7);
- refuse a tracked `data/` on `S`;
- I-main'' with no data-only exception.

Permissions: `contents: read`, `pull-requests: read`, `attestations: read`. Fail closed on any read error.
Done when tests cover these cases:
- refused: unattested `D`; seed-digest mismatch; the seed tree on a commit with a parent (F7); an attestation
  with another predicate type or signed at another ref (F3); a partial hand edit; a tracked `data/` on `S`; a bot commit on
  `main` after the baseline; `records-data` missing;
- accepted: an attested `D`; the seed; a whole-tree restore of an earlier attested tree.

## B3: push job (rows J2, J5, T)
Commit on `D`, run the I-data'' checks, push `HEAD:refs/heads/records-data` (a non-fast-forward fails loudly), then
attest the listing with `actions/attest-build-provenance` pinned by sha (`subject-path`). Permissions:
`contents: write`, `id-token: write`, `attestations: write`, `issues: write`. No `pull-requests`. Remove the PR
open/merge step and the `data/<date>` branches. Update the failure text.
Done when the tests show: only this job holds `attestations: write`; `id-token: write` is held only by this job
and `deploy` (F3); no job holds `pull-requests: write`;
the listing bytes the push job attests equal the bytes the gate rebuilds (one shared helper, both run in the test).

## B4: update job (rows J1, J3, J4, K)
- Check out `S`, then `D`'s `data/` into `data/` before the cache restores.
- The I-pub tripwire: fetch the live `build-info.json`, check out that `D`, and compare the votes, roll calls and
  outcomes with this run's build, minus the listed changes. On a hit, output `held=yes` and open or comment on one
  fixed-title issue. A failed fetch also holds, with its own issue text. A missing `build-info.json` is accepted
  only when `D` is the seed.
- Write `build-info.json` (`S`, `D`, the listing digest) into the site.
  Contract (B4, D3): `{"schema": "build-info/1", "sha": S, "data_sha": D, "listing_sha256": <sha256 of
  `git ls-tree -r -z <deployed commit> -- data`>}` at `<site>/build-info.json` (`collector/tripwire.py` `build_info`).
- Deploy needs `held != yes`; the note follows deploy. Drop any `data_sha` input.
- `allow_shrink` never bypasses the tripwire (F7); only the reviewed list does.
- City-books issue (row FB, `daily-update.yml:566-596`): the text drops "before it is committed" and names the
  path: `fetch-data`, `fin-books fetch` and `fin-books build --locality <id>` locally, review
  `build/fin-books-<id>.json`, then a reader fix by PR or an entry in `config/fin-books-accepted.yml` by PR; the
  next daily run rebuilds. Fixed text only, as today (no run-log text in an expression).
- **No phase 0 on `main` (ADR 0011 Amendment (c); on the B2/B3 branch, after fb94f5be):** on `main`, the gate refuses
  an empty `MAIN_PR_BASELINE` (L-1; fixed text, through `gate-failed`). Branch runs stay `verified=false`. `push` keeps
  `verified == 'true'`, and `deploy` gains `needs.gate.outputs.verified == 'true'`. The tripwire has one mode and
  always holds: no report-only or phase switch, and no input or variable that turns the hold off.
  `test_the_committed_baseline_is_unset_or_a_sha` accepts only a 40-hex sha on the cutover branch, and the workflow
  carries the value the cutover PR pins (D3 `--plan`). Update the gate's "Phase 0" comment, the deploy comment
  ("in phase 0 it passes ... deploys as before") and `docs/ops/morning-note.md` lines 10-15 and 29.

Done when tests show: a changed outcome holds; a removed roll call holds; a listed change passes; a new meeting
passes; a fetch failure holds; the seed bootstrap passes; an `allow_shrink` run that drops a published roll call
holds; the city-books issue text names `config/fin-books-accepted.yml` and asks for no commit of `data/`; on `main`
an empty baseline refuses (nothing built, pushed or deployed) and a set baseline with the cutover squash as the
only later commit verifies; on a branch the gate passes with `verified=false` and push and deploy are skipped; deploy
is skipped whenever `verified` isn't `'true'`, including `collect=false`; no tripwire code path outputs `held=no`
after a hit.

**B4 notes (review of 2bfd7eb9, decisions).**
- S2 `data-off-main/ipub-list-never-spent` (manager's decision, 2026-11-18): each `config/published-fact-changes.yml`
  entry is pinned to `path` + `fact_id` + `change` + `value_sha256` and lets through only that exact transition.
  B4 fix 2 (`data-off-main/ipub-entry-pins-only-before`, second hit; invariant and consumers in
  `docs/architecture/ipub-tripwire-invariant.md`): `value_sha256` is `collector/tripwire.py` `change_sha256`, the
  sha256 of `{"before": live view, "after": this run's view or the empty view}` for both kinds, so a duplicate id's
  surviving copy (or a fact changed again from another live value) can't ride on an old entry. Once the live
  `build-info.json` shows the new view, the entry matches nothing new; a later change of the same fact needs a new
  entry. The hit line prints the four values to copy. One entry per (`path`, `fact_id`). Residual: an entry matches
  again only if the live site shows the very same before view again and the run makes the very same after view (the
  transition a person already reviewed); spent entries are deleted in any later PR.
- S1b: the live tree is always `D` or `D+1` (`MAX_WALK` 2). A stuck "could not read" hold is left by a reviewed code
  PR, not by a rebuild-only run (which runs the same check).
- S1: the deploy-held issue opens on `main` only. N1: the report is replayed between `::stop-commands::<token>` and
  `::<token>::`. N2: a duplicate id's lost copy is a removal.

## D1: `protect-main` and `merge-reviewed` (rows R1, R-D, R2, S1, S2)
- `protect-main` writes R1'' (`scripts/main-ruleset.json`), R-D (`scripts/records-data-ruleset.json`) and R-T
  (`scripts/main-tag-ruleset.json`: blocks creating, updating or deleting a tag named `main`, F2) and turns R2 off.
  Its OK check: approvals 2; R2 on = NOT OK; R-D and R-T present; no CODEOWNERS requirement; no collaborator or
  invitation with write or more besides gn0sh, no deploy key with write, and installed Apps `none` or `claude` alone
  without Administration write (F1 as amended: ADR 0011 Amendment 2026-11-18 (b), invariant I-person);
  both environments' `main` deployment policy of type `branch` (F2). **Any refused or failed read is NOT OK**, never
  skipped (drift: the team proxy refuses `actions/permissions`, `collaborators` and `environments`). CODEOWNERS is
  deleted in the cutover PR.
- `merge-reviewed` refuses a PR whose author isn't gn0sh or whose head repo differs, and prints the rule-suite
  result after each merge.

Done when stub-`gh` tests cover each NOT OK (including an extra App, a write deploy key, a `tag`-type environment
policy and a 403 on each read) and each refusal.

**D1 notes for S1 (installed Apps, 2026-11-18).** Brian's `protect-main.ps1 -Check` at 2f1b0162 got HTTP 403 on
`user/installations` ("must authenticate with an access token authorized to a GitHub App"). The other installation
endpoints (`repos/{r}/installation`, `users/{u}/installation`) need an App JWT, and `orgs/{o}/installations` is for
organisations, so no token Brian holds can list Apps (from the REST docs; judgment, high confidence). The script no
longer reads them: Brian confirms them by hand at https://github.com/settings/installations and passes
`-Apps <names>|none`; without it the check is NOT OK, and the line it prints records his answer and the date.
Treatment of the Claude GitHub App (`claude`): ADR 0011 Amendment 2026-11-18 (b) states the invariant (I-person) and
every consumer. The reason first given here ("one App adds at most one approving identity besides gn0sh, so no PR
reaches 2") was wrong: gn0sh plus the App is exactly 2. The correct reason is that, with R2 off, the App is the only
approver besides gn0sh. So any 2 counted approvals include gn0sh's, and a path with no gn0sh action can't reach 2.
A gn0sh-authored PR has at most 1 approval and merges only by bypass. Two Apps (or R2 on plus one App) make 2 without
gn0sh, so they are NOT OK. Any App with Administration write could edit the rulesets, so that is NOT OK too. The
slug `claude` and "no Administration write" are both unverified hand checks by Brian. A wrong slug fails closed
(NOT OK, and the cutover stops). That no App can **bypass** R1'', R-D or R-T is read: each ruleset's bypass list must
equal its file (admin role only on R1'', none on R-D and R-T). Team rule: gn0sh posts COMMENT reviews only, never
APPROVE. Residual for S1: the App can fast-forward `records-data`. The gate refuses an unattested `D` (fail closed,
a held deploy). An earlier attested tree is accepted, and I-pub catches it if it changes a published fact. This is the
same exposure as any write-token workflow and the team's own gn0sh access.
Code follow-ups: fix the reason in the `protect-main.{sh,ps1}` header comments to "any 2 approvals include gn0sh's".
D3 passes `-Apps` / `--apps` through to `protect-main`.

**D1 note: main's workflow (2026-11-18, raised by B2/B3).** `protect-main` reads `main`'s `daily-update.yml` and is OK
only for the post-cutover shape: the step "Check main's history and the records-data head" in job `gate` only, `push`
needing `gate`, `push` the only job with `attestations: write` and with `contents: write`, no `pull-requests: write`,
no inline job permissions, `permissions: {}` at the top, and no "Open and merge the data pull request" step.
Cutover step 4 runs before the cutover merge, while `main` still has the old workflow, so D3 passes
`-PreCutover` / `--pre-cutover` there (with `-Apps`). That flag is OK only while the old step is on `main`, so both
directions fail closed. Every later run (V1, drift re-checks) goes without it.

## D2: `scripts/fetch-data.{sh,ps1}` and preflight
Fill `data/` from `origin/records-data` (a worktree or `git archive`; never commits). Update the preflight docs and
`CLAUDE.md` "This repo" line. Before the cutover it is a no-op when `data/` is tracked.
Done when a fresh clone with `fetch-data` passes the full suite.

## D3: cutover script `scripts/cutover-data-off-main.{sh,ps1}` (Operator's order)
Brian runs it from his PC (U3-0 = no). `main` is protected before the cutover merge (F5).
1. Refuse within 05:00-10:30 UTC (D3 review: steps 7 and 8 must not meet the 09:07 cron), while a run is active, or while `MORNING_NOTE_SEND` is set (drift). A refused
   or failed read of `actions/variables` counts as set. Also refuse unless `origin/main` equals the PR's pinned
   `MAIN_PR_BASELINE` (Amendment (c)), and the runbook 4.7.1 window listing, from the pinned window start
   to that sha, passes. A refused read, an empty or non-ancestor start, a `Bot` that isn't a known exception, or
   N = 0 all refuse. The listing is printed for the record.
2. Disable `daily-update`.
3. Seed `records-data` from `main`'s `data/` minus the curated files and the moved person-run inputs
   (`data/localities/*/transcripts/`, `data/maps/`; I-in), as one parentless commit. Stop unless its listing passes
   `python -m collector.data_shape`, `python -m tools.scrub_rpc_phones --check` passes on it, and its digest equals
   the PR's `RECORDS_DATA_SEED_DIGEST`.
4. Run `protect-main` (R1'', R-D, R-T, R2 off) and stop unless it prints OK.
5. Merge the cutover PR (B1-B4, D1, D2, CODEOWNERS deleted, `MAIN_PR_BASELINE` pinned) with `merge-reviewed`,
   which must print `bypass`. The squash's parent must equal the pinned baseline. This merge sets the baseline.
6. Re-enable the workflow.
7. Dispatch `collect=false`. Check that the gate logged the history line for exactly 1 commit (verified), the
   deploy succeeded and `build-info.json` shows the seed.
8. Dispatch `collect=true`. Check that the gate verified, `records-data` moved and is attested, and the deploy
   succeeded. This is the first run after the baseline that pushes. No phase-0 run exists to wait for.

`--rollback`: refuses at entry while `MORNING_NOTE_SEND`, or a `MAIN_PR_BASELINE` variable, is set (F4: R2 on reopens
the bot path). A refused or failed variables read counts as set. After the cutover merge, the baseline in
`main`'s workflow is set by design. So, per Amendment (c) item 7, the check that `main`'s workflow holds exactly one
empty `MAIN_PR_BASELINE` runs after restore PR R merges and before R2 goes on. If it fails, the rollback stops with R2
off. Before the merge, the check runs at entry, as today. Then R1' json back, R2 on, a reviewed PR restoring `data/` on
`main` from `records-data`'s head (every `config/` input, curated or person-run, stays where the cutover PR put it,
with its readers), and the workflow re-enabled. Every step prints what it did, and a failure stops with the exact `--rollback`
command.
Done when a stub-`gh` dry run walks every step in this order and the rollback, and tests show step 1 and
`--rollback` refusing with each variable set and with a 403 on the variables read, and step 3 stopping on a seed
that holds a `transcripts/` folder, `data/maps/` or a phone in an RPC location. Also (B1 review
main-protect/data-test-breaks-at-cutover): step 7's run passes the update job's `python -m pytest -q -x` on S+D,
where the tests that read collector output take it from the `data/` folder on disk, never `git ls-files` or
`git ls-tree HEAD -- data` (`tests/test_data_shape.py::test_data_on_disk_holds_only_collector_output`,
`tests/test_committees_daily.py`, `qa/pii_scan.py`); on a checkout with an empty `data/` they fail, not pass.

Built (devops-engineer, 2026-11-18, branch `claude/data-off-main-d3`; tests `tests/test_cutover_data_off_main.py`).
Choices the reviewers should check:
- Step 1 already builds and checks the seed and compares the pin, so a bad seed stops with nothing changed; step 3
  stops if `main` moved off the pinned baseline after step 1 (Amendment (c)). A moved input is left out only when the cutover head
  has its `config/` copy as the same blob; otherwise it stays in and the I-in guard refuses it (no silent drop).
- Brian runs it from a checkout of the cutover PR at the reviewed sha (the python checks are then reviewed code).
  `--plan` (gh reads only) prints `SEED DIGEST` and `BASELINE` for the PR's pins: run it after the day's run, cut over the same day.
- `--apps claude|none` (Amendment (b)): Brian reads https://github.com/settings/installations first; any other
  answer is refused before anything changes, and it is passed to `protect-main`. His PC needs Python 3.10+ with
  `requirements.txt`.
- Rollback order: after the cutover merge it is two calls. `--rollback --cutover-merge <sha>` opens the restore PR
  (also restores the workflow and CODEOWNERS from before the merge, else the gate would refuse every run);
  `--rollback --merge <R> --sha <head> --report <r>` merges it, then R1', then R2 on, then the workflow, so R2 never
  comes on while CODEOWNERS is absent. Before the merge it is R1', R2 on, workflow on. Both disable the workflow first.
- The cutover PR's own change (B2 refuses a tracked `data/`): `--prepare` on its branch stages `git rm -r --cached
  data`, `data/` in `.gitignore` and CODEOWNERS deleted; then `--plan` gives the pin, the sha256 of `git ls-tree -r -z
  <seed> -- data` (the gate's bytes). Step 1 refuses a head that tracks or does not ignore `data/`.
- Step 4 runs `protect-main --pre-cutover --apps` (`-PreCutover -Apps`); after the merge, step 5 runs a plain
  `protect-main --check --apps` (no writes, main's new workflow), which must print OK before the workflow is re-enabled.
- Contract with B4: the site's `build-info.json` names `D` as `data_sha` (`build_info_data_sha`).
- **ADR 0011 Amendment (c), done (devops-engineer, 2026-11-18).** `--plan` prints `BASELINE <sha>` beside `SEED
  DIGEST`, says whether the head pins both and contains `main`, and prints the 4.7.1 listing to paste into the PR
  (gh reads only; it exits 1 on a stale pin). Step 1 refuses unless the PR's one 40-hex `MAIN_PR_BASELINE` equals
  `origin/main` and the 4.7.1 block (ported into both scripts, same jq filters) passes from `WINDOW_START`. Step 3
  and step 5 stop if `main` moved off the pin (no seed rebuild any more). Step 5 checks that the squash has one
  parent, the pin. Steps 7 and 8 read the `gate` job's log and need B2's line "Every commit on main after <pin>
  was merged by a person, reviewed at its head: 1 commit(s)." with the job `success`. Step 8 also needs the deploy
  to succeed. Contract with B2: that line's text and the job name `gate` (`gate_verified`).
- **Window start `WINDOW_START=4c5cd91022b74f5b7ad68ec94cdb863fcc444acd` (PR #31).** No `R2 first on` or `Main
  before the ruleset` line was ever recorded (platform facts, status ledger). Ruleset 27502319, the first R1, was
  created 2026-11-17T22:21:09Z (`gh api repos/gn0sh/clarksville-records/rulesets/27502319`, `created_at`). On
  `main`'s first-parent line, 4c5cd910 (#31) merged at 16:49:13Z, and the next commit, b5a3638d (#32), merged at
  00:02:13Z on Nov 18 (`gh api pulls/31`, `pulls/32`). So `main` was 4c5cd910 for the whole time S1 could have read
  it before writing R1, and anything after R1 is in the window. "R2 back ON 11:22 AM CT Nov 18" (status) was R2
  being turned on again after the V1' probe. Starting there would be a later start and would leave out #40 and #49,
  the two known bot merges, so it was not used. Check run 2026-11-18 (team session, the runbook 4.7.1 block from
  4c5cd910 to `origin/main` 60167e4c): `checked 23 commits`, every line `User` apart from the two `KNOWN EXCEPTION`
  lines (#40, #49). Changing the start needs a reviewed PR.
- **Review of e05c5242 (REQUEST CHANGES), fixed in the same round:**
  - main-protect/r2-on-without-codeowners: step 1 refuses a head that doesn't contain `main`
    (`merge-base --is-ancestor`), and also a `main` without CODEOWNERS or one empty baseline. The rollback now picks
    its path by whether `--cutover-merge` is on `main`, never by `data/`. Each path refuses at entry unless the commit
    R2 will come on over tracks `data/` and has CODEOWNERS and one empty `MAIN_PR_BASELINE`: `main` for the early
    path, the merge's parent for R's opening (f4-wrong-workflow, call 1), R's head for `--merge` (call 2).
  - rollback-r2-unchecked-codeowners: after R merges, `main`'s workflow and CODEOWNERS must equal R's blobs, with
    one empty baseline. Otherwise it stops with R2 off. The restore tree also drops anything `main` still tracks
    under `data/` before adding `records-data`'s copy.
  - undo-line-after-merge: after the merge call, any stop fetches `main`, and if it moved, the undo line names
    `--cutover-merge <new main>`.
  - window-vs-duration: step 1 refuses 05:00-10:30 UTC. ps1-case: the `.gitignore` filter uses `-cnotmatch`.
  - Checked against the I-person consumers. Rollback is the only consumer that changes. R2 still comes on only
    after both variables are confirmed unset, and only over a commit with CODEOWNERS and an empty baseline (F4).
    The squash-parent check keeps the gate's first count at 1. `protect-main`, `merge-reviewed`, the gate and J2
    are unchanged.

## S1: security review
Fresh review of the B1-D3 milestone (B1b included) at one sha, against I-main'', I-prov, I-pub, I-in, T1-T8 and
the Brain Trust findings (Opponent: dispatch on scratch branches, T5, author refusal).
Done when it approves, or its findings are fixed and re-reviewed by delta.

## C1: cutover session (hard stop 1: a production change)
Brian runs D3 from his PC (U3-0 = no). His card: "**Cut over Daylight's data to records-data today? yes / no**",
plus "This also sets `MAIN_PR_BASELINE`" (ADR 0011 Amendment (c): the cutover PR pins it, so his yes covers the
baseline, hard stop 1). It gives the exact PowerShell command, the time window (outside 05:00-10:30 UTC, after
`-Plan` on the same day's `main`) and what he should see (`OK` from `protect-main`, `bypass` from the merge, then
each step green). Default if no answer: wait; nothing changes.
Done when steps 1-8 are green, and `docs/status.md` records the shas, the run ids and the first attested `D`.

## V1: V1'' probe
Rewrite the probe per the note's section 4 (targets W, N, D0; gn0sh-opened and bot-opened; `NOT-TRIED` lines;
direct push; scratch-branch environment refusal). F2: creating a tag named `main` is refused (R-T), and a run at
probe tag `v1pp-probe` is refused both environments. Run it, then remove its guard refusal for that one run only.
PASS gates `MORNING_NOTE_SEND` only. Since ADR 0011 Amendment (c) item 6, the cutover PR sets `MAIN_PR_BASELINE`,
and V1'' no longer gates it. A FAIL (a bot merge into `main`) then makes the gate refuse every run until a person
moves the baseline past that commit. The drift rule for the baseline is met inside D3: `protect-main` prints OK in
step 4, just before the merge sets the baseline, and a plain `--check` prints OK just after it.
Done when the PASS output is recorded in platform facts.

## W1: docs
- `docs/architecture/main-protect-invariant.md`: I-main'', I-prov, I-pub, I-in, the consumer table from the note.
- Operator docs that tell a person to commit `data/` (transcripts import, `fetch_map`, `fin-books build`): name the
  `config/` path and the PR instead (`git grep -n 'transcripts import\|fetch_map\|fin-books build' docs`).
- `docs/platform-facts.md`: U1 false, the environment facts, U3-0 = no (proxy 403, 17:37 UTC), the U3 verdict.
  F2: replace the "`github-pages` deployment branches after runbook 2.0.5: not checked yet" line with the
  2026-11-18 PC read (both environments `main` only), plus the policy type once `protect-main` reads it.
- `docs/ops/morning-note.md`: 2.0-2.0.4, 4.7. Drift rules: unset `MORNING_NOTE_SEND` before R2 goes on or any
  ruleset changes; re-run `protect-main` from Brian's PC after any settings change and before `MAIN_PR_BASELINE`.
- ADR 0010 status: superseded in part. ADR 0011 status: accepted after U3 PASS.

Done when a review confirms that each doc says what the note says, no stronger.

## Suggested order
1. Done: N1+N2, U3-0 (no). Now: U3-1, then U3-2 (Brian).
2. On PASS: B1 (done); now B1b, B2+B3 (one branch) and D1, D2 in parallel; then B4; then D3; then S1.
3. Then C1 (a day, outside 05:00-10:30 UTC), V1, W1.
