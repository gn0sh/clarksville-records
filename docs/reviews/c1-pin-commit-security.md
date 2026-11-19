# Security re-confirm: cutover pin commit and stdin BOM fix (PR #65)

Reviewer: security-engineer (opus/high), 2026-11-19. Reviewed head for the cutover: **61e1110556ee0095a65dcda1ae446d01d5647ea0** (round 3 is docs/test only, confirmed by code review: no change to scripts/, .github/, config/ after ba3f63a).

## Round 1: 2af5731 vs 7934721 — OK WITH FOLLOW-UPS
- Seed digest re-derived from git alone: 45 entries, 22 moved inputs dropped (all matched config/), 23 kept, sha256 e873414ce8de2d811b9e7e53403e02920bd7af174aeb8740a3e34e2f2139951a = pin; real tree b7cd0199 re-lists identically.
- Seed content: no transcripts/, maps/ or curated names; gate regexes total 23, curated 0, person 0; `collector.data_shape` exit 0; `tools.scrub_rpc_phones --check` 0 phone numbers; phone-pattern grep over all 23 blobs 0 hits.
- Gate use of pins: seed path needs parentless + I-data'' + listing hash = pin, so it admits only byte-identical checked content. records-data absent on origin. Step 1 refuses unless main is still at the baseline; later commits get the per-PR merged_by=User + reviewed-head check; earlier ones are covered by the window from WINDOW_START.
- Canaries #40 (3ef440ae) and #49 (2b207042) each change only .github/workflows/v1-canary.yml; removed by #41 and #52; absent at 1922fda3. merged_by.type rests on the -Plan output (no gh here).
- L1 (low) `data-off-main/ps-stdin-bom`: swap failure fell open for `hash-object --stdin` only. N1: same family as PR #48. N2: window has 27 first-parent commits; 551a483 and 581b197 are data-only bot pushes excluded by `:(exclude)data/` by design (now noted in the PR body).
- Tests: 637 passed, 114 skipped.

## Round 2: ba3f63a — OK
- L1 closed: re-check after swap, unreadable = BOM, Code 1 without Start; every GitRun/GitText caller treats non-zero as return/refuse/fail (Prepare's check-ignore falls through to a git add that also refuses). pwsh 7 not refused (no preamble). Tests 638 passed, 114 skipped.
- Remaining (low, needs verification, no fix): not yet run under 5.1; a swap that doesn't take refuses at the first git call (safe). The cutover run on the big PC is the live check.
