# V1'' probe try-4 fix: code review and security review (2026-11-21)

Range reviewed: 4a74f1a..6f0c512, then the test-only commit dfbf027 (manager). pwsh 7 twin runs: 44944071763 (9a083b3) success, 44947864469 (2d91149) success, 44949286041 (6f0c512) 2 failed (test expectation only: U+FFFD from ps1 UTF-8 decode, as the code reviewer predicted), 44951329073 (dfbf027) success, 274 tests.

## Security review, V1'' probe try-4 fix (4a74f1a..9a083b38), 2026-11-21
Verdict: OK WITH FOLLOW-UPS (no critical/high). Owner backend-engineer.
1. Low v1pp-probe/log-read-diag-query: URL cut only on literal https?://; schemeless or JSON-escaped URLs keep path + short query values (sig always redacted). Fix: also cut every query; test schemeless URL.
2. Low v1pp-probe/log-read-diag-userinfo: host class keeps user:pass@. Fix: exclude @ / strip userinfo.
3. Low v1pp-probe/log-read-diag-controls: C1 controls and bidi overrides pass CleanLog/clean_log. Fix: drop U+0080-009F, U+202A-202E, U+2066-2069.
4. Low (verify) v1pp-probe/gh-debug-legacy: clear DEBUG as well as GH_DEBUG.
5. Low v1pp-probe/selfcheck-before-scope: workflow scope is requested before the read-only self-check (scope is given back on refusal). Fix: move self-check before scope refresh, or document.
6. Verify: .ps1 twin tests must pass under pwsh, and 5.1 2>&1 gives one ErrorRecord per stderr line.
Checked and holds: no write before self-check (tests pin order); no failure path reports PASS; self-check can't be fooled into PASS; failed-read stdout and self-check text never logged; ids validated ^[0-9]+$.

## Code review, same diff: APPROVE (nits only)
1. Nit v1pp-probe/log-read-selfcheck: per_page=1 self-check refuses if newest completed daily run was cancelled; use per_page=5, first run with a usable job.
2. Nit v1pp-probe/log-read-diag: URL cut swallows a closing ")"; exclude ")".
3. Process: merge only after the pwsh 7 Actions run is green.

## Delta re-reviews of 9a083b3..2d91149 (2026-11-21)
Code: APPROVE. Nits: runbook 6a sentence order (selfcheck-before-scope); scope-failure line to Log too.
Security: OK WITH FOLLOW-UPS. 1,2,4,5 fixed; 3 fixed in .ps1. New lows: log-read-diag-controls-nested (sh one-pass byte strip), log-read-diag-paren-path (document). Item 6 accepted on green pwsh 7 run.
pwsh run at 9a083b3: 44944071763 success. Final nits batch sent to backend-engineer (sonnet/high).

## Final deltas 2d91149..6f0c512
Security: OK, no open findings (controls-nested closed; paren-path accepted and documented).
Code: REQUEST CHANGES on the test expectation only (ps1 U+FFFD); script changes correct. Fixed in dfbf027 (assert no live control; ps1 run green 44951329073), which makes it APPROVE by the reviewer's own condition.

## Escape-sequences flag (4fbf630..aea29a0), 2026-11-21
Root cause from a read-only check on Brian's PC (gh 2.104.0, Windows PowerShell 5.1): `gh api .../actions/jobs/<id>/logs` exits 1 with "the response contains terminal escape sequences; pass --allow-escape-sequences to output it anyway". Network, DNS and storage were fine; with the flag the read exits 0.
Code: APPROVE, no findings. Security: OK, no findings (log text is cleaned before any use; the flag is on job-log reads only; wrong detection fails closed).
pwsh 7 run 44956117018 at aea29a0: success.
