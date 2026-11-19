# Code review: cutover pin commit and stdin BOM fix (PR #65)

Reviewer: code-reviewer (opus/high), 2026-11-19. Reviewed head for the cutover: **61e1110556ee0095a65dcda1ae446d01d5647ea0**.

## Round 1: 2af5731 vs 7934721 — APPROVE WITH NITS
- Pins: MAIN_PR_BASELINE 1922fda3 = `git ls-remote origin main`; RECORDS_DATA_SEED_DIGEST e873414c re-derived from git alone (45 data/ records, 22 moved inputs left out, 23 kept) and from a real seed tree built in a scratch object store (only entry `data`, listing byte-identical). Format matches the gate regexes, PinnedBaseline/PinnedSeedDigest (.ps1) and pinned_baseline/pinned_seed_digest (.sh), and step 1's checks.
- BOM fix correct on .NET Framework 4.8 (Process.Start's AutoFlush StreamWriter writes the preamble at once; the setter stores a clone that Start reads; no console = no preamble). BOM failure reproduced: "fatal: malformed index info", rc 128.
- should-fix `data-off-main/ps-stdin-bom-swap-fail-open`: a failed swap was swallowed; `hash-object -w --stdin` (GitignoreEdit, rollback) would store a BOM'd blob. Fix: refuse before Start.
- process: same family as `v1-probe/ps51-stdin-bom` (PR #48): second hit, architect states the invariant.
- nit: a preamble-bearing non-UTF-8 console encoding would leave cp 65001 after restore (cosmetic).
- Tests: test_cutover_data_off_main.py + test_workflow_lock.py 637 passed, 114 skipped (.ps1 twins, no pwsh).

## Round 2: ba3f63a + af45bf3 — APPROVE WITH NITS
- Fix correct: re-read after the swap, unreadable = BOM, Code 1 without Start on every call; all three stdin callers treat non-zero as a refusal.
- should-fix `ps51-stdin-bom/invariant-pin-gap`: the invariant doc claimed more pins than the cross-script test has. nit `pipe-regex-literal-only`. nit: startup message (accepted, fails closed). nit: stale line refs.
- Tests: 638 passed, 114 skipped.

## Round 3: 61e1110 (docs + one test line) — APPROVE
- No change in scripts/, .github/ or config/: pins, digest and GitRun fix stand. Doc now matches the pins; `| & $var` rejected. 123 passed, 114 skipped (cutover file).
- Leftover nit (no action before cutover): rows 1a-1c cite old line numbers; function names still identify them.
