# data-off-main trust roots (loop rule re-plan, 2026-11-19)
software-architect, 2026-11-19, at f4d88591. Family `data-off-main/rollback-*` hit twice: S1-3
`rollback-unverified-data`, then N1 `rollback-seedpin-untrusted` (`reviews/s1-reconfirm-f4d88591.md`). ADR 0011.

## The invariant (I-root)
Every trust root that `scripts/cutover-data-off-main.{sh,ps1}`, `protect-main`, `u3-toggle` and the gate compare
against (seed digest, `MAIN_PR_BASELINE`, attested identity, expected workflow and CODEOWNERS, ruleset JSON, bypass
lists, window start) is read from (a) a commit the script has itself confirmed is on fetched `main`'s first-parent
line, (b) a file in the script's own checkout, or (c) the platform (GitHub API about `main`, Sigstore). Never from a
PR-controlled commit (a PR head or its parents) or a ref a bot can move (`records-data`, `pull/*`). A value from a
PR head may be *checked against* a root (the cutover PR's pins), never *be* one. "On main" means the first-parent
line (the gate's own test, daily-update.yml:221), not any ancestor: a true merge would make a PR commit an ancestor.

## Consumers (S = .sh line, P = .ps1 line, after this fix)
| # | Consumer | Reads from | Trusted? |
|---|---|---|---|
| C1 | `WINDOW_START`, `KNOWN1/2`, `CURATED`, `ATTEST_ID`, `wl` (S101-117, P117-125) | constants, own checkout | yes (b) |
| C2 | `r1p` R1' JSON for `put_r1p` (S499, P663) | was own checkout | **fixed L2**: `git cat-file blob $m:scripts/main-ruleset-r1p.json`, fetched main (a); unreadable refuses at step 1 |
| C3 | cutover `pinned` seed digest (S662, P833) | PR head `$sha` = own HEAD, clean | yes: checked equal to the seed built from main `$m0` |
| C4 | cutover `base` MAIN_PR_BASELINE (S663, P835) | PR head | yes: checked equal to fetched main, steps 1, 3, 5 |
| C5 | `build_seed` config/ blobs | PR head = own checkout | yes (b) |
| C6 | `window_check` merged_by per commit | API, main's first-parent line | yes (c) |
| C7 | `gate_verified`, `build_info_data_sha`, `check_attested` | run on main, site, Sigstore vs `ATTEST_ID` | yes (c); compared to script-made seed |
| C8 | `--plan` pins (S445, P611) | `--ref` | n/a: advisory, writes nothing |
| C9 | rollback open: `--cutover-merge` (S525, P680) | fetched main | **fixed**: was `--is-ancestor`, now first-parent |
| C10 | rollback open: seed pin (S536, P693) | `$cmerge`, on main | yes (a) |
| C11 | rollback open: workflow, CODEOWNERS for R (S579, P743) | `$cmerge^1`, on main | yes (a) |
| C12 | rollback open: data/ source | `records-data` (bot-movable) | subject, not root: verified by C10/attestation |
| C13 | rollback merge: seed pin (S515, P667) | was `$sha^1` (PR) | **fixed N1**: now fetched main `$m` |
| C14 | rollback merge: R's parent (S520-521, P677) | was unchecked | **fixed N1**: one parent, on main's first-parent line |
| C15 | rollback merge: expected workflow, CODEOWNERS (S502-511, P654-664) | was R's own blobs | **fixed T-R3**: `--cutover-merge` on main, its parent's blobs |
| C16 | rollback merge step 4: main vs R blobs | R head, reviewed | yes: checks the merge landed R, after C13-C15 and C21 |
| C17 | rollback early: `restore_ok "$m"` | fetched main | yes (a) |
| C18 | protect-main: ruleset and bypass JSON (`$here/`), main's workflow (`contents?ref=main`) | own checkout, API on main | yes (b), (c) |
| C19 | u3-toggle: `r1p`, `r1pp`, `--restore <backup>` (S131-174, P205-259) | own checkout, checked equal to main's byte for byte (contents API, `ref=main`); operator's file | **fixed L2**: (b) checked against (c); unreadable refuses; `--restore <backup>` stays the operator's file |
| C21 | rollback merge: R's changed paths and `.gitignore` vs its parent `$rp` (S532-544, P702-713) | `$rp` (on main, C14); `gitignore_edit`, the open path's own edit | **new L1**: `git diff-tree -r --no-renames --name-only -z $rp $sha` lists only `data/**`, the workflow, CODEOWNERS, `.gitignore`; R's `.gitignore` blob equals `gitignore_edit $rp` |
| C22 | `fetch_main` / `FetchMain`, the source of `$m` for C9-C17 (S219, P285) | origin, fetched now | **fixed M1 (.ps1)**: a failed fetch returned the stale `refs/cutover/main`; now `$null`, and all 9 callers refuse or stop |
| C20 | gate: `RECORDS_DATA_SEED_DIGEST`, `MAIN_PR_BASELINE`, cert identity (daily-update.yml:121-123, 201, 221) | the run's own workflow file | yes (b): history check, push and deploy are main-only (:211, :974, :1168) |

Count: 22 consumers. 16 trusted as they were, 4 fixed (C9, C13, C14, C15). C13-C15 are the same shape: the
`--merge` path trusted R about R. Security review e4bae340 (`reviews/security-rollback-e4bae340.md`): C2 and C19
fixed (L2), C21 added (L1), C22 fixed (M1). L3: a fixture with true merges on main (second-parent commits as
`--cutover-merge` and as R's parent are refused) pins the first-parent test of C9, C14 and C15.

## T-R3 (new, found here)
`--merge` took the workflow and CODEOWNERS that R2 comes on over from R itself; `restore_ok` checks only one empty
baseline. A reviewed-but-wrong R workflow (an extra job, a changed gate) would get R2 on over it. Now `--merge` needs
`--cutover-merge <sha>` (the open path prints it in its "Next" line): on main's first-parent line, tracks no data/,
no CODEOWNERS, and R's two blobs must equal its parent's.

## Residuals (not fixed)
- **X1 rollback checkout unpinned.** The cutover refuses unless HEAD is the reviewed head with no change; rollback
  and u3-toggle do not, so "own checkout" (C1, C2, C19, and the script's own code) is whatever Brian runs. A
  script check can't fix this (a bad checkout skips it). Runbook line: run the rollback from the cutover's reviewed
  head or a clean `origin/main` (done: `docs/ops/morning-note.md` "Rollback and stopping"). Since L2 the ruleset
  JSON (C2, C19) no longer depends on the checkout; the script code and the scripts it calls still do.
