# Code review: Daylight Digest switch-on bundle plus digest-warmth, bbc603a vs main (aabf7c9)

Reviewer: code-reviewer (opus, high), 2026-11-22. Read-only. **Verdict: APPROVE** (no must-fix).

Verified: Clarksville byte-identical (real records-data build, switch off: 0 differing files; on: only digest/*, digest.css, national.js). 1141 tests passed (national/digest/unofficial/rpc_daily/workflow sets); 525 passed with CI=1 REQUIRE_BROWSER=1 (18 browser-gated files, Playwright from the lock via npm ci --ignore-scripts; lock sha512s match registry); 175 passed / 162 skipped protect_main + header (no pwsh). nat_blob c12483b = blob of national-update.yml. Greeting: BASENAME kept only if it has a letter and is part of NAME, else greet-none; county full NAME; textContent only; never in title/URL/storage. Notices word for word. Orange decoration only (test-pinned). Stale alarm arithmetic and id sanitising tested.

| # | Sev | Key | Where | Finding / fix |
|---|---|---|---|---|
| 1 | should-fix | `daily-run/install-step-hard-dependency` | daily-update.yml:696-705, push.needs :1255 | apt + CDN failure fails update, so push/deploy skip and Clarksville misses a day, while the switch is off. Fix: retries; tolerate install failure while off (`_browser_required()` still fails closed once on). |
| 2 | should-fix | `daily-run/install-step-untested` | daily-update.yml:691-710 | No lock test pins the step (ignore-scripts, npm ci, prefix outside checkout, NODE_PATH, before Tests, no secret env). |
| 3 | should-fix | `copy/lede-overclaims` | config/national/page-labels.yml:52 | "A city council, a county commission and a school board meet near you" is false for many addresses (unincorporated, CT/RI, DC, VA independent cities). Reword as general: "Local governments like city councils, county commissions and school boards meet in public and decide things like roads, zoning, schools and local taxes. Type your address to see which ones govern you and what they take up next." |
| 4 | should-fix (process) | `copy/approval-not-recorded` | digest-warmth.md s2; spec A16-A18 | ~25 public labels and the A16-A18 rule changes lack Brian's recorded approval; make it a switch-on prerequisite. Record the recommended Focus Group as run or skipped with reason. |
| 5 | should-fix (low) | `digest-fold/no-browser-check` | tests/national_browser.js | Fold only tested in fake DOM; add a real-browser case (form hidden after lookup, "Look up another address" restores it and focuses #digest-q). |
| 6 | nit | `daily-run/install-comment-overclaims` | daily-update.yml:691 | Only test_national_browser.py finds Playwright via NODE_PATH; the other 17 still skip. |
| 7 | nit | `national-observability/stale-issue-wording` | daily-update.yml:1156 | Alarm-only issue says "built degraded". |
| 8 | nit | `lint/e501-unofficial` | sitegen/unofficial.py:19, :29 | Two new E501 (126 -> 128). |

Manager's resolution of #1 vs security F1/F3 (2026-11-22): download/apt failure after retries -> warning, browser tests skip while the switch is off (fail closed once on via `_browser_required()`); browser hash mismatch -> hard fail always. Security F2 (PATH) taken with F3 (no -x, one --lf rerun) so flakes don't block deploys.
