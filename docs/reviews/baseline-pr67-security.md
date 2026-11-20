# Security review: PR #67 (baseline move to eef6ed06) at 2fd191d2

Reviewer: security-engineer (opus/high), 2026-11-20. Verdict: **OK with follow-ups.** No critical, high or medium findings. Merge only through `scripts/merge-reviewed`.

Conditions from docs/reviews/pr66-merged-security.md finding 2: (a) first-parent 1922fda3..eef6ed06 = 8d69778, eef6ed0: holds. (b) `git diff --quiet eef6ed06 b0b3ffc1`; eef6ed0's 17 paths in docs/design, site/, sitegen/build.py, sitegen/freshness.py, tests/: holds. (d) the workflow diff is one line (daily-update.yml:122, value and comment); RECORDS_DATA_SEED_DIGEST unchanged; exactly one anchored `MAIN_PR_BASELINE:` line: holds. (e) value exactly eef6ed0643f42fd104ca2e0a463650066558e20f: holds. daily-update.yml is the only path outside docs/.

Gate after a merge-reviewed squash: eef6ed06..HEAD is the one squash, mapped to #67; merged_by User; one parent; an OWNER COMMENTED review at the final head before merged_at (merge-reviewed posts it, then merges pinned to that head). Any other merge method refuses again.

Findings: (1) low `baseline-pr/head-moves-after-review`: after the last commit, `git diff --name-only 2fd191d2 <newhead>` must list only docs/, and merge-reviewed takes the new head. (2) low `baseline-pr/state-now-stale`: morning-note 4.7 and invariant row B named 1922fda3 as current: fixed in this PR. (3) low `baseline-pr/r2-contradictory-text`: morning-note "tick that box" rephrased: fixed in this PR.

Brian's PC: (f) `protect-main --check --apps claude` ends "OK: main is protected (R1'', R-D, R-T as written, R2 off, auto-merge off, gn0sh the only writer, both environments main only)." exit 0; any NOT OK = stop. (g) merge-reviewed prints "Merged pull request #67 (reviewed at <head>) as <squash>." and "Rule suite <id> for <squash>: bypass", exit 0. After: the gate logs 1 commit checked after eef6ed06.
