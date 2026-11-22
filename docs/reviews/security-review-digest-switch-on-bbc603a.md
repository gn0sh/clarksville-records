# Security review: Daylight Digest national switch-on, bbc603a vs main (aabf7c9)

Reviewer: security-engineer (opus, high), 2026-11-22. Read-only.

**Verdict: OK with fixes.** Nothing critical or high. Fix F1 and F2 before main and switch-on.

## Findings

| # | Sev | Key | Where | Fix |
|---|---|---|---|---|
| F1 | medium | `ci-supply/browser-bytes-unverified` | daily-update.yml install step (~696-705) | Playwright 1.63 checks only size (coreBundle.js downloadFile); CfT zips come from one cdn.playwright.dev URL each, no mirror. Bytes run in the update job before artifact upload and cache save, so a poisoned zip could tamper data/, build/site/ (then attested and deployed) or poison restore-key caches. Fix: commit `tests/playwright/browsers.sha256` (tree hash of the pinned revisions), set `PLAYWRIGHT_BROWSERS_PATH=$RUNNER_TEMP/pw-browsers` via GITHUB_ENV, install with `PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS=1` (verify it skips ldd), then `sha256sum --quiet -c` plus no-extra-files check; fail closed. Consider `--only-shell` (needs `_browser_ok` probe to do a real launch). Retry install 3x (30 s, 90 s); optional cache behind the same hash check. Do not fail open. Optional later: browser tests in their own job with `permissions: {}`. |
| F2 | medium (verify) | `ci-browser/probe-skips-silently` | tests/test_csp.py:53-56 and ~15 copies (test_address_box, test_analytics, test_body_switch, test_corrections, test_daylight, test_days, test_fin_pages, test_front_page_v2, test_mobile_front_lite, test_moon, test_morning_page, test_onceover, test_qa_tools...) | Probes look for /opt/pw-browsers or `playwright` on PATH; on the runner neither exists, so the CSP-in-browser gate likely still skips. Fix: Tests step `PATH="$RUNNER_TEMP/playwright/node_modules/.bin:$PATH"` (step-scoped, not GITHUB_PATH); better, one shared Node probe in conftest that fails instead of skipping when CI and Playwright installed; first run with `-rs`. |
| F3 | low | `ci-test/x-flag-and-rerun` | daily-update.yml:710 | `-x` hides later failures; `-x || --lf` would be a gate bypass. Fix: `python -m pytest -q \|\| { echo "::warning::..."; python -m pytest -q --lf; }` without -x (or `--sw` twice). |
| F4 | low | `ci-supply/node-unpinned` | install step | Keep runner Node; add Node >= 20 check and print version. No setup-node. |
| F5 | low | `ci-supply/install-step-unguarded` | tests/test_national_workflow.py | Add a test pinning the step's shape (npm ci --prefix --ignore-scripts, only the two lock files, no `${{` in run, timeout, no token env, hash check present). |
| F6 | low | `national-observability/alarm-says-degraded` | daily-update.yml:1156 | Issue opening line says "built degraded" when only the stale alarm fired; choose the line by cause. |

## Checked and clean
- Pin: `git hash-object` of national-update.yml = c12483be..., matches protect-main.sh:408 and .ps1:513. national-update.yml diff is comment + fixed echo text only. No permissions, inline permission blocks or `uses:` added; only `${{ runner.temp }}`. Exactly two workflows.
- npm lock integrity matches the registry; no install scripts; no .npmrc.
- Digest pages: BASENAME cleaned (control/bidi stripped, 120 cap), kept only if it has a letter and is a substring of NAME; drawn via textContent only; single-pass fill; SVG via createElementNS; no innerHTML/document.write/title/history/location writes; saveList still `{id, name}` only; address only to sandboxed frame. Jinja autoescape on; CSP unchanged; no new inline script/style or outside requests.
- D-ISO-9 stale step: alarm fixed yes/no, counts regex-checked, ids sanitized and regex-matched, body via --body-file, GH_TOKEN step-scoped, continue-on-error, 5-min timeout; test covers injected newlines.
- Apt via sudo accepted (signed Ubuntu packages, same as existing poppler/tesseract).

## Not verified
Workflow never ran on this branch; runner image contents, cache-poisoning behaviour on today's cache service, and the skip-validate variable are "needs verification".
