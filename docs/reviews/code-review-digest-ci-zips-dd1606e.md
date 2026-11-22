# Code review: Digest CI zip check (ee3764b..dd1606e)

Reviewer: code-reviewer (opus, high), 2026-11-22. Read-only. **Verdict: APPROVE WITH NITS.**
Tests: test_browser_install_step.py + test_workflow_lock.py 575 passed. `pip download --require-hashes --only-binary :all:`
(cp312 manylinux) resolves all 15 locked packages to hashed wheels, so F-pip can't newly break the Clarksville run.

Checked and sound: `set -euo pipefail` handler pattern; list shape/CRLF; retry cleanup and `missing`; step order
(shape, curl, zip hash, unzip, tree check, ok); `browsers` output plumbing to Tests and issue step; R2 sum 3,990 s < 70 min;
pin 7ce9473d; issue step copies HELD/AGE/RPC pattern; switch-OFF Clarksville run downloads same bytes minus ffmpeg;
tests exercise real zips/unzip, stubbed curl, escapes, retries, no-retry paths.

**Most serious:** CfT version and Playwright revision are hand-copied and never checked against the installed Playwright.

| # | Sev | Key | Where | Finding / fix |
|---|---|---|---|---|
| 1 | should-fix | `ci-browser/revision-not-bound-to-lock` | daily-update.yml:772-797 | A wrong-but-consistent revision passes tests and tree check; launch then fails and blocks the Clarksville publish. Fix: after npm ci, hard-fail unless `playwright-core/browsers.json` chromium + chromium-headless-shell have revision 1243 and browserVersion 153.0.8010.12; behaviour test. |
| 2 | should-fix | `docs/version-bump-unclear` | browsers-sha256.sh:9-15, daily-update.yml:711-713 | Google publishes no sha256 (trust on first use): say how to record provenance (fetch twice from separate networks). Name browsers.json (`revision`, `browserVersion`) as the source. |
| 3 | nit | `ci-browser/hardcoded-revision` | :792-797 | `rev=1243`, `cftv=` set once. |
| 4 | nit | `ci-browser/unzip-fail-cleanup` | :795 | Also `rm -rf -- "$br"` on unzip failure. |
| 5 | nit | `ci-browser/environmental-unzip-hard-fails` | :795 | Unzip failure on checked bytes (full disk) blocks the publish; record as accepted risk in the invariant doc. |
| 6 | nit | `ci-browser/issue-never-closes` | :826-851 | No auto-close on later `ok`; matches siblings. Optional, later. |
| 7 | nit | `tests/shell-comment` | test_browser_install_step.py:43 | Default shell is `bash -e {0}`, not `-eo pipefail`. |

## Decisions this changed
| Finding | Changed | Scope | Owner |
|---|---|---|---|
| 1, 2, 3, 4, 5, 7 | yes, fixed in this PR | small adds | devops-engineer |
| 6 | no (matches sibling steps; revisit if on-call noise) | none | - |
