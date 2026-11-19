# PowerShell 5.1 stdin invariant (problem family `ps51-stdin-bom`)

Second hit: (1) PR #48 `v1-probe/ps51-stdin-bom`(-throw): 5.1 adds a BOM and CRLF to text piped into `gh`, so gh got bad JSON. (2) `data-off-main/ps-stdin-bom`: .NET Framework's `Process.Start` writes `[Console]::InputEncoding`'s preamble (a BOM on a `chcp 65001` console) into a redirected stdin, so `git update-index --index-info` refused.

**Invariant.** Under Windows PowerShell 5.1, a native command gets on stdin exactly the bytes the script means it to get, and nothing else. Body text goes to `gh` only as a file (BOM-less UTF-8 or raw `WriteAllBytes`) named with `--input`. It is never piped. Raw bytes go to `git` only through `GitRun`. Any path that can't make that guarantee fails closed: it returns failure **before** the command starts, and every caller treats that failure as a refusal.

## Every consumer in `scripts/*.ps1` (grep: Process.Start, RedirectStandardInput, StandardInput, `| gh`, `| git`, `| &`, `--stdin`, `--input`, Out-File/Set-Content/WriteAll*)
| # | Where | Feeds | How it meets the invariant | Pinned by |
|---|---|---|---|---|
| 1 | cutover-data-off-main.ps1 `GitRun` (~190-212), the only `Process.Start` in scripts/ | git stdin | preamble-free `UTF8Encoding` swapped in around Start; **fail-closed check needed (below)** | `test_ps1_gitrun_starts_git_with_a_preamble_free_stdin_encoding` (text) |
| 1a | `GitignoreEdit` :361 `hash-object -w --stdin` (rollback) | `.gitignore` bytes | GitRun; caller checks `Code` and the 40-hex output | same, plus the new pin below |
| 1b | `BuildSeed` :393 `update-index -z --index-info` | NUL listing | GitRun; caller checks `$b.Code` | same |
| 1c | rollback :814 `update-index -z --force-remove --stdin` | ls-files output | GitRun; caller checks `Code` and calls Fail | same |
| 1d | the other GitRun/GitText calls (`$InBytes = $null`: read-tree, ls-files, cat-file, add, rm…) | nothing (stdin closed at once) | none of them reads stdin, so a stray BOM there changes nothing; still covered by the check if it is made unconditional | same |
| 2 | cutover :529 `gh api -X PUT … --input $path` | ruleset JSON | `WriteAllText` with BOM-less `$utf8` (:137), file + `--input` | `test_ps1_is_ascii_bom_less_and_51_safe` (no `\| gh`), stub at test :179 reads `--input` |
| 3 | cutover :402/:420/:616/:729/:776 listings, rpc.json; :634 `.gitignore` then `git add` | files read by python / git by path, not stdin | `WriteAllBytes` (raw) or BOM-less `$utf8` | listing digests are checked by the cutover tests; no stdin path |
| 4 | protect-main.ps1 :151/:156 `gh api … --input $file` | committed ruleset JSON | committed file, BOM-less ASCII | `test_protect_main.py` :362 (files BOM-less ASCII); **no no-pipe pin** |
| 5 | u3-toggle.ps1 :123/:154 (and the :365 hint) `--input $path` | ruleset JSON | BOM-less `$utf8` file + `--input` | `test_u3_toggle.py` :325-328 (every PUT is `--input`), :700 (no `\| gh`) |
| 6 | v1-probe.ps1 :207-208 `git/trees --input $treeFile` | tree JSON | BOM-less UTF8Encoding file + `--input` (the PR #48 fix) | **only the `--jq` quote pin** (test_workflow_lock :2859); no no-pipe or `--input` pin |
| - | fetch-data.ps1, merge-reviewed.ps1, morning-note-probe.ps1 | none | they read native output only (`git ls-files \| Select-Object` pipes *out of* git); :275 writes a results file nothing reads | not needed |

## Is the proposed fail-closed check sufficient?
Yes for 1a-1c, if it does three things. (a) It reads `[Console]::InputEncoding.GetPreamble()` again **after** the swap attempt and before `Start`. A setter that is silently ignored or throws then still shows up. (b) If that read throws, it counts as "has a preamble". (c) It returns `Code = 1` with an empty `Out` and never starts git. All three stdin callers already treat `Code -ne 0` as a refusal or Fail, so the empty `catch { }` around the swap can no longer fail open. Recommended: make the check unconditional, not only when `$InBytes` is set. This costs nothing, because the swap only fails when the console is broken. It also covers 1d by the letter of the invariant, and it keeps one rule with no exceptions.

New pin (test-only): in `GitRun`'s text, the re-check comes after the swap and before `Process]::Start`, and its branch returns `Code = 1` without Start.

## Other changes needed
No other script changes. One test gap: consumers 4 and 6 aren't pinned against a later edit that pipes into `gh` or `git`. Add one cross-script test over `scripts/*.ps1` that checks four things: no `\|\s*(gh|git)\b`; `Process]::Start` appears only in cutover's `GitRun`; every `--input` file is written with a BOM-less encoding or committed as BOM-less ASCII; no `Out-File`/`Set-Content`/`>` output is passed to a native command (v1-probe's `Set-Content -Path $results` is only its own log). This test turns the family's rule into one pin instead of one per script.
