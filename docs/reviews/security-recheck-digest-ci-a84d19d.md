# Security re-check: Digest CI hardening (79f1287, merged a84d19d)

Reviewer: security-engineer (opus, high), 2026-11-22. Read-only. **Verdict: OK with fixes. Don't merge to main or switch on until R1 is fixed.**

| # | Sev | Key | Where | Finding / fix |
|---|---|---|---|---|
| R1 | medium | `ci-supply/browser-bytes-unverified` (2nd hit) | daily-update.yml ~739-742 | Playwright's own extractor unpacks three unverified zips before the tree check. Reproduced with real oopBrowserDownload.js: symlink entry + same-name file entry writes through the symlink outside `$br` (coreBundle.js:10429-10435 guard misses it). A poisoned zip that omits the chrome binary is read as `missing` (warning, job continues); outside writes also survive into `if: always()` cache saves; could replace oopBrowserDownload.js and run code pre-check. Fix: stop using `playwright install chromium`; curl (`--fail --location --proto '=https' --proto-redir '=https' --max-time 300`, 3 tries) the CfT zips from storage.googleapis.com/chrome-for-testing-public/153.0.8010.12/linux64/ into an empty dir; check `tests/playwright/browser-zips.sha256` (chrome-linux64.zip 8aac35011c18f6e2d10696154af89a5728ac2ddd6dc6fad24ffdf243c3fcfd5a; chrome-headless-shell-linux64.zip a9da028861a0cf789ff25c2fed45f5f1aaf969ed9247835b6a7821a4f7af9d1d); curl fail = missing, mismatch = hard fail; only then unzip into chromium-1243 / chromium_headless_shell-1243 + INSTALLATION_COMPLETE; keep tree check (no .links, no ffmpeg); keep install-deps. Verify REQUIRE_BROWSER=1 launch in-session. |
| R2 | low | `daily-run/install-step-hard-dependency` | :710 | timeout-minutes 50 < worst-case retries (~53 min); re-derive after R1. |
| R3 | low | `ci-browser/probe-skips-silently` | install step | `missing` only an annotation; on main open/update one issue (step-scoped token, --body-file). |

Checked and holding: tree check (exact set, no links/special files, strict sha256), PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS skips ldd (coreBundle.js:33624-33627), no TOCTOU, PATH Tests-scoped, no -x, `--lf` can't skip the gate (`--lfnf=all`), F4-F6 and CR #2/#6/#7 fixed (188 tests pass), no new permissions/uses/secrets, two workflows, nat_blob c12483be matches. 17 ungated browser files: no fix needed (switch on -> `_need_browser` fails closed). Hash list: independently rebuilt from Google zips, byte-identical 592 lines. cdn.playwright.dev mismatch risk low and fail-closed; R1 makes it moot.

De-risk without an agent workflow run: Brian may run Daily update on branch claude/project-thread-107kju with collect unchecked (push/deploy main-only, ~1342/~1537); look for "Chromium checked: 592 files match". Gate job on non-main dispatch: unverified.

Family `ci-supply/browser-bytes-unverified` second hit: architect states the invariant and lists every consumer before the fix.
