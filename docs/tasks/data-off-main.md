# Tasks: data off `main` (ADR 0011)

Architecture: `docs/architecture/v1-fail-2026-11-18.md` (invariants I-main'', I-data'', I-prov, I-run'', I-pub, and
the consumer table; every task below names its rows). Gate: **nothing past U3 starts until U3 PASS.** Tests run in
session (`python -m pytest -q`), and the output goes in each PR. Each PR is reviewed by `code-reviewer`. Every PR
touching the workflow, rulesets or scripts is also reviewed by `security-engineer` (CI and hard-stop area: in
session, fresh review per milestone). Problem family `main-protect`. A third hit means the architect re-plans and
the manager escalates.

| Task | Owner | Depends on | Parallel |
|---|---|---|---|
| N1 Probe guard refuses unconditionally | devops-engineer | none | yes, now |
| N2 Baseline window lists 2b20704 | devops-engineer | none | yes, with N1 (same PR) |
| U3-0 Can the team token write the ruleset? | devops-engineer | none | yes |
| U3-1 `scripts/u3-toggle` + docs PR P | devops-engineer | U3-0 | after U3-0 |
| U3-2 Run the control | manager (+ Brian if U3-0 = no) | U3-1, N1 | no |
| B1 Data inventory and curated-input move | backend-engineer | U3 PASS | yes |
| B2 Gate: D, I-data'', I-prov, I-main'' | backend-engineer | U3 PASS | yes (workflow file conflicts with B3/B4: one branch, sequential commits) |
| B3 Push job: records-data + attestation | backend-engineer | U3 PASS | with B2 |
| B4 Update job: S+D checkout, tripwire, build-info | backend-engineer | B1 | after B1 |
| D1 `protect-main` R1'' + R-D + checks; `merge-reviewed` refusals | devops-engineer | U3 PASS | yes |
| D2 `fetch-data`, preflight | devops-engineer | U3 PASS | yes |
| D3 Cutover script (Operator's order) + rollback | devops-engineer | B1-B4, D1, D2 | no |
| S1 Security review of B+D milestone | security-engineer | B1-B4, D1-D3 | no |
| C1 Cutover session | manager + Brian | S1, review approve | no, away from 09:07 |
| V1 V1'' probe rewrite and run | devops-engineer | C1 | no |
| W1 Docs: invariant doc, platform facts, runbook, ADR status | technical-writer (architect checks) | C1 (V1 for final status) | yes |

## N1 + N2: containment (one small PR, now)
`scripts/v1-probe.{sh,ps1}` refuse unconditionally, naming ADR 0011 and that the 2026-11-18 V1' was FAIL. The test
asserts the refusal comes before any write. The runbook 4.7.1 window check lists 3ef440a (#40) and 2b20704 (#49) as
the known bot merges.
Done when: tests pass, and a dry run of each script prints the refusal and exits 1 without a GitHub write.

## U3-0: may the team's token write ruleset 27502319?
One PUT of the identical live body, then read it back unchanged. Record the result in `docs/platform-facts.md`.
Done when: yes or no is recorded with the HTTP status.

## U3-1: `scripts/u3-toggle.{sh,ps1}` and docs PR P
Per `docs/ops/u3-positive-control.md`: preflight, apply R1'', merge window, verdict, restore in `finally`/`trap`,
and `--restore`. Tests use a stub `gh` to cover the restore-on-every-exit path (merge refused, Ctrl+C, read failure)
and the time-window refusal. PR P is a real docs change: the `docs/platform-facts.md` entry "U1 false: rule suites
pass for #48, #49, #52".
Done when: tests pass, and code review and security review approve.

## U3-2: run the control
U3-0 yes: the team runs it. U3-0 no: Brian gets the card in `docs/ops/u3-positive-control.md`. The verdict goes in
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

## B2: gate (rows G, B)
Read the `records-data` head once and output `data_sha`. Then:
- I-data'' on `D`;
- I-prov: rebuild the listing file, then `gh attestation verify` with the four flags from the note, or match
  `RECORDS_DATA_SEED_DIGEST`;
- refuse a tracked `data/` on `S`;
- I-main'' with no data-only exception.

Permissions: `contents: read`, `pull-requests: read`, `attestations: read`. Fail closed on any read error.
Done when tests cover these cases:
- refused: unattested `D`; seed-digest mismatch; a partial hand edit; a tracked `data/` on `S`; a bot commit on
  `main` after the baseline; `records-data` missing;
- accepted: an attested `D`; the seed; a whole-tree restore of an earlier attested tree.

## B3: push job (rows J2, J5, T)
Commit on `D`, run the I-data'' checks, push `HEAD:refs/heads/records-data` (a non-fast-forward fails loudly), then
attest the listing with `actions/attest-build-provenance` pinned by sha (`subject-path`). Permissions:
`contents: write`, `id-token: write`, `attestations: write`, `issues: write`. No `pull-requests`. Remove the PR
open/merge step and the `data/<date>` branches. Update the failure text.
Done when the tests show: only this job holds `id-token`/`attestations: write`; no job holds `pull-requests: write`;
the listing bytes the push job attests equal the bytes the gate rebuilds (one shared helper, both run in the test).

## B4: update job (rows J1, J3, J4, K)
- Check out `S`, then `D`'s `data/` into `data/` before the cache restores.
- The I-pub tripwire: fetch the live `build-info.json`, check out that `D`, and compare the votes, roll calls and
  outcomes with this run's build, minus the listed changes. On a hit, output `held=yes` and open or comment on one
  fixed-title issue. A failed fetch also holds, with its own issue text. A missing `build-info.json` is accepted
  only when `D` is the seed.
- Write `build-info.json` (`S`, `D`, the listing digest) into the site.
- Deploy needs `held != yes`; the note follows deploy. Drop any `data_sha` input.

Done when tests show: a changed outcome holds; a removed roll call holds; a listed change passes; a new meeting
passes; a fetch failure holds; the seed bootstrap passes.

## D1: `protect-main` and `merge-reviewed` (rows R1, R-D, R2, S1, S2)
- `protect-main` writes R1'' (`scripts/main-ruleset.json`) and R-D (`scripts/records-data-ruleset.json`) and turns
  R2 off. Its OK check: approvals 2; R2 on = NOT OK; R-D present; exactly one collaborator with write or more
  (gn0sh, admin); no CODEOWNERS requirement. CODEOWNERS is deleted in the cutover PR.
- `merge-reviewed` refuses a PR whose author isn't gn0sh or whose head repo differs, and prints the rule-suite
  result after each merge.

Done when stub-`gh` tests cover each NOT OK and each refusal.

## D2: `scripts/fetch-data.{sh,ps1}` and preflight
Fill `data/` from `origin/records-data` (a worktree or `git archive`; never commits). Update the preflight docs and
`CLAUDE.md` "This repo" line. Before the cutover it is a no-op when `data/` is tracked.
Done when a fresh clone with `fetch-data` passes the full suite.

## D3: cutover script `scripts/cutover-data-off-main.{sh,ps1}` (Operator's order)
1. Refuse within 08:00-10:30 UTC or while a run is active.
2. Disable `daily-update`.
3. Seed `records-data` from `main`'s `data/` minus the curated files, and check that its digest equals the PR's
   `RECORDS_DATA_SEED_DIGEST`.
4. Merge the cutover PR (B1-B4, D1, D2, CODEOWNERS deleted) with `merge-reviewed`.
5. Run `protect-main` (R1'', R-D, R2 off).
6. Re-enable the workflow.
7. Dispatch `collect=false` and check that the deploy succeeded and `build-info.json` shows the seed.
8. Dispatch `collect=true` and check that `records-data` moved and is attested.

`--rollback`: R1' json back, R2 on, a reviewed PR restoring `data/` and the curated paths on `main`, and the
workflow re-enabled. Every step prints what it did, and a failure stops with the exact `--rollback` command.
Done when a stub-`gh` dry run walks every step and the rollback.

## S1: security review
Fresh review of the B1-D3 milestone at one sha, against I-main'', I-prov, I-pub, T1-T8 and the Brain Trust
findings (Opponent: dispatch on scratch branches, T5, author refusal).
Done when it approves, or its findings are fixed and re-reviewed by delta.

## C1: cutover session
Run D3. Brian's part is one card with the exact command, since the ruleset, R2 and workflow toggles need admin
unless U3-0 = yes.
Done when steps 1-8 are green, and `docs/status.md` records the shas, the run ids and the first attested `D`.

## V1: V1'' probe
Rewrite the probe per the note's section 4 (targets W, N, D0; gn0sh-opened and bot-opened; `NOT-TRIED` lines;
direct push; scratch-branch environment refusal). Run it, then remove its guard refusal for that one run only.
PASS gates `MAIN_PR_BASELINE` and `MORNING_NOTE_SEND`.
Done when the PASS output is recorded in platform facts.

## W1: docs
- `docs/architecture/main-protect-invariant.md`: I-main'', I-prov, I-pub, the consumer table from the note.
- `docs/platform-facts.md`: U1 false, the environment facts, the U3 verdict.
- `docs/ops/morning-note.md`: 2.0-2.0.4, 4.7.
- ADR 0010 status: superseded in part. ADR 0011 status: accepted after U3 PASS.

Done when a review confirms that each doc says what the note says, no stronger.

## Suggested order
1. Now: N1+N2 and U3-0 (parallel), then U3-1, then U3-2.
2. On PASS: B1, B2+B3 (one branch) and D1, D2 in parallel; then B4; then D3; then S1.
3. Then C1 (a day, outside 08:00-10:30 UTC), V1, W1.
