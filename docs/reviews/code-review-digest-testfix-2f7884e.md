# Code review: digest-testfix 2f7884e (delta on 10e3e4e)

Reviewer: code-reviewer (sonnet, medium), 2026-11-22. **Verdict: APPROVE.** No must-fix.

Checked the full diff, the Tests step (`.github/workflows/daily-update.yml:835-841`) and the three target test files; 116 passed.

1. Offline opt-in guard (`collector/tests/test_run.py:144-151`) keeps its intent: `OFFLINE_RUN_ENV not in wf` is untouched;
   the env keys (NODE_PATH, BROWSERS) and the two pytest runs (`-q`, `-q --lf`) are pinned exactly, so an extra env key,
   flag, run or a different rerun still fails.
2. Issue-lookup guard (`tests/test_staleness.py:329-336`): count 12 -> 13 and every lookup still needs `--app github-actions`.
3. Locality-name guard (`site/static/national.js:102,292`): comment-only edits; `tests/test_landing_search_nav.py` passes.

Findings
- nit | `collector/tests/test_run.py:147` | `ci-tests/env-values-unpinned`: key names pinned, values not; `<=` allows an
  empty env. Harmless (the opt-in variable is excluded workflow-wide).
- nit (informational) | `.github/workflows/daily-update.yml:841` | `ci-tests/rerun-masks-flake`: the `--lf` rerun turns a
  one-off flaky failure into a warning; intended and visible, and a failed rerun still fails the run.
