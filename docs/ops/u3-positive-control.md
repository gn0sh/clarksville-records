# U3 positive control: does the team's `merge-reviewed` merge go through as a bypass under R1''?

**Result (2026-11-18): PASS**, rule suite 5212430938; see `docs/platform-facts.md` "Main protection".

Owner: devops-engineer (script), Brian (runs it; U3-0 = no), manager (merge and verdict). Gates ADR 0011. Analysis: `docs/architecture/v1-fail-2026-11-18.md`.

## Choice: scripted live toggle on this repository, not a throwaway repository
- A throwaway repository needs Brian to create it and to give the team's GitHub access to it: two asks. It would
  also test a different repository, ruleset and token. The question is about this ruleset (27502319) and the token
  the team merges with every day.
- The live toggle is safe because it changes one rule's parameters for at most 20 minutes, away from the daily
  run, and every side effect fails closed:
  - no bot merge into `main` can pass, so the data PR waits on its own branch;
  - nothing is deleted, no history changes, R2 is not touched;
  - the restore is idempotent from a committed json.

  The worst case, a restore that never runs, is a stricter `main` (section "Abort"). That holds only while gn0sh
  and github-actions[bot] are the only writers: R1'' drops `require_code_owner_review`, so a third writer's approval
  pair could merge a PR no code owner reviewed.
- Hard stops: none. It's a reversible repository setting, not a deploy, not data, not spend.

## Script: `scripts/u3-toggle.sh` and `.ps1` (same behaviour)
`u3-toggle --pr <P>` runs these steps in order and stops at the first failure.
1. **Preflight**, read-only. It refuses if any of these is true:
   - the UTC time is 07:30-10:30 (a run lasts at most 30 minutes, so it can't reach 08:00-10:30);
   - `scripts/main-ruleset.json` isn't R1' with only decision 5's three `pull_request` changes;
   - `scripts/main-ruleset-r1p.json` or `scripts/main-ruleset.json` isn't `main`'s copy byte for byte, or `main`'s
     can't be read (GitHub contents API, `ref=main`; `--restore` without a backup file checks R1' the same way);
   - a `daily-update` run is queued or in progress;
   - the live ruleset 27502319 doesn't match R1' (`scripts/main-ruleset-r1p.json`) on every field `protect-main`
     checks;
   - PR P isn't open, authored by gn0sh, from a branch in this repository, and docs-only (every file under
     `docs/`);
   - `current_user_can_bypass` isn't `pull_requests_only` or `always`.

   It records `main`'s sha and saves the live ruleset json to a backup file outside the repo, and prints that
   file's full path (`BACKUP <path>`). Every restore and failure message repeats it.
2. **Apply R1''.** One body builder makes every PUT (apply, restore, `--restore`). It copies only the whitelisted
   fields `name`, `target`, `enforcement`, `conditions`, `rules` and `bypass_actors`, drops anything else (ids,
   timestamps, links), and here changes only the `pull_request` parameters to R1'' (ADR 0011 decision 5). It reads
   the ruleset back and stops (and restores) unless those fields match the body it sent exactly. It prints `U3 WINDOW OPEN <utc time>`. From here on, the restore runs on every exit (`trap` /
   `try { } finally { }`).
3. **Merge.** It waits for `main` to move, checking every 15 s for up to 20 minutes, while the manager runs
   `merge-reviewed` in the team session after Brian types `U3 go`. If that merge is refused, the manager comments
   `U3 merge refused: <gh's error line>` on PR P (as gn0sh). The script sees it, ends the wait and reports FAIL-U3.
   The suite's `result` reads pass / fail / bypass; a rule evaluation reads only pass / fail. A real bypass reads
   suite `bypass` with the `pull_request` evaluation `fail`.
   `--noop` repeats U3-0. The team path (`--merge`) works only where ruleset writes are allowed (not the cloud session today).
4. **Read the verdict.** It reads PR P (`merged`, `merged_by`, `merge_commit_sha`) and the rule suite whose
   `after_sha` is that merge commit (`GET rulesets/rule-suites?ref=main`, then `rule-suites/<id>`).
5. **Restore R1'.** It PUTs the backup json through the same builder, reads it back, and stops loudly if it doesn't match. It prints
   `RESTORED <utc time>` and the verdict.

| Verdict | Condition | Meaning, next step |
|---|---|---|
| **PASS** | P merged, `merged_by` gn0sh, the rule suite reads **suite `bypass`, `pull_request` `fail`** (evaluation of ruleset 27502319, enforcement `active`), the ruleset read during the window matched R1'', and restore verified | U3 holds. Build ADR 0011 (task list). Record it in `docs/platform-facts.md`. |
| **FAIL-U3** | `merge-reviewed`'s merge refused with HTTP 405 naming "approving review", P unmerged at the same head, `main` unmoved | The team can't merge under R1''. ADR 0011 is rejected; take the fallback (B plus a sender repository). P stays open. |
| **FAIL-RULE** | P merged and the `pull_request` evaluation reads `pass` (suite `bypass` or `pass`) | 2 required approvals don't bind for this merge, so R1'' guards nothing. Stop and re-plan (third hit: escalate per the loop limit). |
| **INCONCLUSIVE** | No merge in the 20 minutes (rule-suite reads included), a read failed, `main` moved by another actor, the ruleset didn't match, or any other suite shape | Nothing learned. Re-run once at a later time with the same PR. |

## Abort
- At any time, press Ctrl+C (Brian) or stop the step (team). The `finally`/`trap` restores R1' and verifies it.
- If the restore fails, run `u3-toggle --restore`, which PUTs `scripts/main-ruleset-r1p.json` (R1') through the same
  builder (`scripts/protect-main` writes R1'' since D1, so it is no fallback here). The backup at the printed `BACKUP` path is the exact pre-U3 body.
- If neither can run, `main` stays on R1'': the 09:07 data PR's merge fails loudly, the data stays on its
  `data/<date>` branch and the site skips one refresh. Team merges need the bypass. Nothing is lost. Restore it
  before the next run.
- The team doesn't merge P outside the window.

## Who runs it
- U3-0 = **no**: the team's cloud session got a proxy 403 on the no-op ruleset PUT at 17:37 UTC 2026-11-18 (read-back
  unchanged). So Brian runs the script from his PC, and the manager runs the merge.
- Brian gets one card: "U3 test today, about 20 minutes, any time outside 07:30-10:30 UTC (not 1:30-4:30 AM CT)? **yes** / no."
  His steps:
  1. In PowerShell in the repo folder, run `.\scripts\u3-toggle.ps1 -Pr <P> -Rehearse`, press Ctrl+C after
     `U3 REHEARSAL WINDOW OPEN`, and check he sees `RESTORED` and `U3 REHEARSAL DONE` (nothing changes).
  2. Run `.\scripts\u3-toggle.ps1 -Pr <P>`. He should see `U3 WINDOW OPEN`.
  3. Type `U3 go` in the thread.
  4. Wait for `RESTORED` and the verdict line. Paste it in the thread. Keep the PC awake and don't close the
     PowerShell window until you see RESTORED.

## `national-data`: an unattested head stops national collection until a reset (S2b nit e)
Architecture `docs/architecture/daylight-national.md` 12.1 row 23, task D-ISO-7. For the U3-0 step that creates
`national-data` and its ruleset.
- `national-update.yml`'s gate reads only the head of `national-data`. If that head is neither the pinned seed nor
  attested by `national-update.yml` on `main` (a hand push, a push by another workflow, a half-finished run), the
  gate refuses on **every later run**: nothing is collected or pushed, and the report job opens its issue each time.
  It never clears by itself.
- Clarksville is not held by it: the daily deploy's lookup (`daily-update.yml`, "Find the newest attested
  national-data") skips an unattested head, reads the newest attested commit among the last 10, and is soft.
- **Recovery is a reset of `national-data` to its last attested commit** (or to the seed). That moves a shared
  branch's history, so it is **hard stop 2: Brian's decision**, never the team's. The team prepares the exact
  commit and command; Brian runs it.
- So the `national-data` ruleset must **block force-push and deletion** (rules `non_fast_forward` and `deletion`;
  the push job's fast-forward pushes still pass), with no bypass for the team's token or GitHub Actions, so only
  Brian can make that reset (he lifts the rule for it, then restores it). This is Brian's PC step, batched with the
  U3-0 ruleset ask (no second card).
