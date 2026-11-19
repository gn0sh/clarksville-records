# C1 pin-reader fix: security review (2026-11-19)

Reviewed head: **8e38008c72f70201fca6c80f57ccbcd99a3964c5** (PR #65). Reviewer: security-engineer (opus, high), fresh review of a170f9cf, then a delta review of 8e38008c.

## Round 1 at a170f9cf: OK with follow-ups
- **L1 (low) `data-off-main/pin-reader-flow-key`:** the anchored count missed a second definition that doesn't start its line, such as a flow mapping `env: { KEY: "<other>" }`. A decoy anchored line could then pass step 1 while the gate used the flow value (an I-prov bypass, gated by a person's review of the PR head). The old selector had an equivalent bypass through a quoted key.
- **I1 (info) `data-off-main/pin-reader-ps1-case`:** `-cmatch` now matches the .sh's case-sensitivity.
- **Checked and holding:** a second key at workflow, job or step level; duplicate keys; anchors and aliases; `${{ }}` values; trailing comments and tabs; tab indentation; CRLF; NBSP. BaselineEmpty in rollback was broken on main before this fix (lines 104 and 135 were both counted) and is correct after it.

## Delta at 8e38008c: OK
- L1 is closed. Flow mappings, block scalars, other levels, quoted keys and `KEY :` all count and refuse. The strip removes only the exact `${KEY:-}`. `${KEY:-x}` fails closed, and a key split across lines is a YAML parse error.
- The real workflows give 1 line per key at 8e38008c. On origin/main the count is 1 for MAIN_PR_BASELINE and 0 for RECORDS_DATA_SEED_DIGEST.
- Info `data-off-main/pin-reader-yaml-residual`, old and not caused by this change: an explicit `? KEY` key and escaped double-quoted keys are still not counted. The control is a person's review of the PR head (C3, C4, C20). Optional hardening is a YAML parse; owner backend-engineer, no deadline.
- Release: OK, with no open findings at low severity or above.
