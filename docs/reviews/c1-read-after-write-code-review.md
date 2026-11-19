# C1 read-after-write fixes: code review (2026-11-19)

Reviewed head: **36e55feb9eaae6e2f6c659e14faa586f69487426** (PR #65). Spec: docs/architecture/read-after-write-invariant.md. Family `data-off-main/read-after-write`.

## Background
Cutover run 4 passed step 1, then stopped at step 2. The workflow disable had worked, but GitHub's read in the same second still said `active`.

## adfd307 (WfSet retry): approve with nits (code-reviewer, opus high)
- The fix is correct in both twins.
- F1, should-fix: step 4 had the same race on R2 (protect-main). It is the second hit in the family.
- F2/F3: the R2On and ruleset reads, the rollback PR POST, and others.
- F4: the "could not read" message. F5: sleeps were untested.
- All of these are handled by the architect's invariant and the fix below.

## 8579a63b..1b809c9b (read-after-write on every row): approve with nits (code-reviewer, opus xhigh, fresh)
- No must-fix.
- `gh api` 422 detection was checked live: stderr reads `gh: Validation Failed (HTTP 422)`.
- PS 5.1 semantics were read line by line: scoping, `$LASTEXITCODE`, `2>&1`, `-join "`n"`, `-Main` binding, ASCII. They hold.
- Tests: 898 passed, 359 skipped (.ps1 twins), 0 failed.
- 1 should-fix `data-off-main/ps51-unexecuted`: run the .ps1 twins under a real PowerShell before Brian's run. This was done: Actions run 44615432457 at 36e55feb ran the twin tests with PowerShell 7.6.10: 744 passed, 0 skipped, 0 failed (cutover, protect-main, u3 toggle; .sh and .ps1).
- Nits:
  - Fixed in 36e55feb: ps1 retry parity in protect-main, the doc's row-5 sentence, and E501.
  - Recorded as a follow-up: the step 7 dispatch does not pin head_sha (it fails closed).
