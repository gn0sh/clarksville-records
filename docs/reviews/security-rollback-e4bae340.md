# Security review at e4bae340 (rollback trust fixes 9e64964e..99708913 + B4 workflow 1aeb9f4f), security-engineer opus/high, 2026-11-19
Verdict: OK WITH FOLLOW-UPS. N1 and T-R3 fixed in both twins. 307 tests passed. pwsh not installed (.ps1 read only).
- M1 Medium `data-off-main/ps-fetchmain-stale` cutover-data-off-main.ps1:285-288: FetchMain drops git fetch's exit code (| Out-Null) and returns stale refs/cutover/main; .sh (fetch_main sh:219) refuses. Stale $m breaks C13/C14/C15/C17; scenario: failed fetch after cutover -> plain -Rollback printed -> R1' back and R2 on over main without CODEOWNERS. Fix: return $null when (GitRun fetch).Code -ne 0; test a failed fetch.
- L1 Low `data-off-main/rollback-r-scope-unchecked` sh:494-526, ps1:646-680: R may change files beyond data/, workflow, CODEOWNERS. Fix: git diff --name-only $rp $sha limited to data/, the workflow, .github/CODEOWNERS, .gitignore; R's .gitignore equals the open path's edit. Both twins.
- L2 Low `data-off-main/rollback-checkout-unpinned` (residual X1): refuse unless hash-object of the running script and $r1p equal blobs at $m; better read r1p via git show $m:scripts/main-ruleset-r1p.json. Plus runbook line (devops).
- L3 Low `data-off-main/first-parent-untested`: add fixture with a true merge on main (second-parent commit as --cutover-merge / R's parent -> refused).
- I1 Info `pipeline/stop-commands-trailing-line` daily-update.yml:561-563: printf '\n' before the resume line.

## Deltas (security-engineer, 2026-11-19)
- ec6cdc14 (M1, L1, L2, L3, I1 fixes): OK. Info: trust-roots doc "Count:" line stale. 323 passed.
- a27239a2..1e00bc51 (.ps1 twins run under pwsh 7.4.6; named arguments only; u3-toggle Ctrl+C exit; I1 newline only when missing): OK WITH FOLLOW-UPS. L-a `data-off-main/ps-ctrlc-exit-zero` (cutover .ps1 exits 0 after Ctrl+C, no undo line). 717 passed.
- 1e00bc51..2073769e (L-a fix: plain script, dot-sourced named-only binding, done flag, STOPPED + Undo line, exit 2; .sh INT/TERM/HUP traps): OK. 235 passed both twins. Still unproved on Windows PowerShell 5.1: @args named binding under -File, exit code after console Ctrl+C. Cheap proof: `-Plan -Ref HEAD` on Brian's PC.
