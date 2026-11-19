# C1 rerun fixes: security review (2026-11-19)

Reviewed head: **20c3b9726aed53f6e7e76d3e01b6cb3ee6f1b5ef** (PR #65). Reviewer: security-engineer (opus), delta reviews of 2107789 and 20c3b97.

## 2107789: OK with follow-ups
- Low `cutover/wf-skip-stale-preread`: a lagged pre-read could skip a needed disable. Fixed in 20c3b97: step 5 re-reads the state before the merge and stops unless it is `disabled_manually`.
- The R-T file change does not alter the rule. The parameter only affects fork syncing, and false is the default. Read-back still fails closed.

## 20c3b97: OK
- The step 5 re-check fails closed, and only disable is skipped. The twins match.
- Accepted: a window of seconds between the step 5 read and the merge, which needs gn0sh or an App with Actions write.
- Residual (low, optional follow-up for backend-engineer): the rollback's merge path has no step 5-style re-check. This is a data-consistency risk only.
