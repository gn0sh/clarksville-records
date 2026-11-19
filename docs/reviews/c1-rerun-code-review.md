# C1 rerun fixes: code review (2026-11-19)

Reviewed head: **20c3b9726aed53f6e7e76d3e01b6cb3ee6f1b5ef** (PR #65). Reviewer: code-reviewer (opus), delta reviews of 2107789 and 20c3b97 on top of the reviewed 36e55feb.

## Background
- Run 5 stopped at step 2. GitHub refuses to disable a workflow that is not active (HTTP 403), and run 4 had left daily-update disabled.
- Run 6 passed steps 1-3, then stopped at step 4. GitHub stores the tag ruleset's update rule without the default `update_allows_fetch_and_merge: false`.

## 2107789: approve with nits
- The rerun from run 6's state was walked step by step, and every step passes. The early rollback from that state also works.
- Should-fix (`data-off-main/read-after-write`): the pre-read could skip an enable on a lagged read. Fixed in 20c3b97: only a disable is skipped.
- Assumption confirmed: run 6's live R-T rule is `{"type":"update"}` with no parameters key, so the new file matches.
- Nit: a workflow reading `disabled_inactivity` stops at step 2 without a hint. This fails closed; it is a follow-up.

## 20c3b97: approve with nits
- The skip is for disable only, in both twins. The step 5 re-check fails closed, and runs before the merge sha is recorded.
- Affected tests: 16 passed. Full cutover + protect-main suite: 291 passed (manager's run).
- Test nit, follow-up: `test_an_enable_is_always_sent` should make the stub read `active` once just before the enable.

PowerShell twins: Actions run 44637521763 at 20c3b972 (PowerShell 7.6.10): cutover + protect-main + u3 toggle, .sh and .ps1, **750 passed**, 0 skipped.
