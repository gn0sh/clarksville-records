# U3 positive control: does the team's `merge-reviewed` merge go through as a bypass under R1''?

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

  The worst case, a restore that never runs, is a stricter `main` (section "Abort").
- Hard stops: none. It's a reversible repository setting, not a deploy, not data, not spend.

## Script: `scripts/u3-toggle.sh` and `.ps1` (same behaviour)
`u3-toggle --pr <P>` runs these steps in order and stops at the first failure.
1. **Preflight**, read-only. It refuses if any of these is true:
   - the UTC time is 08:00-10:30;
   - a `daily-update` run is queued or in progress;
   - the live ruleset 27502319 doesn't match R1' (`scripts/main-ruleset.json`) on every field `protect-main`
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
   `merge-reviewed` in the team session after Brian types `U3 go`.
4. **Read the verdict.** It reads PR P (`merged`, `merged_by`, `merge_commit_sha`) and the rule suite whose
   `after_sha` is that merge commit (`GET rulesets/rule-suites?ref=main`, then `rule-suites/<id>`).
5. **Restore R1'.** It PUTs the backup json through the same builder, reads it back, and stops loudly if it doesn't match. It prints
   `RESTORED <utc time>` and the verdict.

| Verdict | Condition | Meaning, next step |
|---|---|---|
| **PASS** | P merged, `merged_by` gn0sh, the rule suite's `pull_request` evaluation is **`bypass`**, the ruleset read during the window matched R1'', and restore verified | U3 holds. Build ADR 0011 (task list). Record it in `docs/platform-facts.md`. |
| **FAIL-U3** | `merge-reviewed`'s merge refused (e.g. 405 naming required approving reviews) | The team can't merge under R1''. ADR 0011 is rejected; take the fallback (B plus a sender repository). P stays open. |
| **FAIL-RULE** | P merged and the suite reads `pass` | 2 required approvals don't bind for this merge, so R1'' guards nothing. Stop and re-plan (third hit: escalate per the loop limit). |
| **INCONCLUSIVE** | No merge in the window, a read failed, `main` moved by another actor, or the ruleset didn't match | Nothing learned. Re-run once at a later time with the same PR. |

## Abort
- At any time, press Ctrl+C (Brian) or stop the step (team). The `finally`/`trap` restores R1' and verifies it.
- If the restore fails, run `u3-toggle --restore`, which PUTs `scripts/main-ruleset.json` (R1') through the same
  builder, or run `scripts/protect-main`. The backup at the printed `BACKUP` path is the exact pre-U3 body.
- If neither can run, `main` stays on R1'': the 09:07 data PR's merge fails loudly, the data stays on its
  `data/<date>` branch and the site skips one refresh. Team merges need the bypass. Nothing is lost. Restore it
  before the next run.
- The team doesn't merge P outside the window.

## Who runs it
- U3-0 = **no**: the team's cloud session got a proxy 403 on the no-op ruleset PUT at 17:37 UTC 2026-11-18 (read-back
  unchanged). So Brian runs the script from his PC, and the manager runs the merge.
- Brian gets one card: "U3 test today, about 20 minutes, any time outside 08:00-10:30 UTC? **yes** / no."
  His steps:
  1. In PowerShell in the repo folder, run `.\scripts\u3-toggle.ps1 -Pr <P>`. He should see `U3 WINDOW OPEN`.
  2. Type `U3 go` in the thread.
  3. Wait for `RESTORED` and the verdict line. Paste it in the thread.
