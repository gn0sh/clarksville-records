# C1 pin-reader fix: code review (2026-11-19)

Reviewed head: **8e38008c72f70201fca6c80f57ccbcd99a3964c5** (PR #65, branch claude/data-off-main). Reviewer: code-reviewer (opus, high), fresh review of a170f9cf, then a delta review of 8e38008c.

Why: the third real cutover run refused at step 1 ("pins no single 64-hex RECORDS_DATA_SEED_DIGEST"). The pin readers counted every line containing `KEY:`, which also matched the workflow's bash `"${KEY:-}"` reads. BaselineEmpty (used by rollback) had the same bug on main.

## Round 1 at a170f9cf: approve with nits
1. should-fix `data-off-main/pin-reader-single-untested`: no test put a second key definition in the workflow (mutating every count to `-ge 1` left 124 tests passing).
2. should-fix (low) `data-off-main/pin-reader-flow-mapping`: anchoring the count stopped it seeing a second definition in a flow mapping, so BaselineEmpty could pass one empty block key plus a flow-form value.
3. nit `data-off-main/pin-reader-ps1-untested`: the .ps1 regexes are pinned by text only (no pwsh in the cloud session).

Also checked: PowerShell 5.1 `-cmatch` with a trailing CR, POSIX `grep -cE`, and every other workflow-key reader in scripts/ and tools/ (none unanchored; the rest compare whole files).

## Delta at 8e38008c: APPROVE
- Findings 1 and 2 are closed. The count is now every `KEY["']?\s*:` line after removing only the literal `${KEY:-}`, and the value is still read from the anchored line. New tests cover step 1 (2 keys x 4 forms) and rollback (4 forms), and a text pin keeps the exactly-one checks.
- Nit `pin-reader-fail-closed-drift`: a future comment written like `KEY: ...` would refuse. That is fail-safe, and the real-workflow test catches it first.
- Finding 3 is still open. The .ps1 readers run for the first time in step 1 on Brian's PC. That step is read-only and refuses before changing anything.
- Tests at 8e38008c: tests/test_cutover_data_off_main.py 136 passed, 126 skipped (.ps1 twins).
