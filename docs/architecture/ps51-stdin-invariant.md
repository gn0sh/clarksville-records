# PowerShell 5.1 stdin invariant (problem family `ps51-stdin-bom`)

Second hit: (1) PR #48 `v1-probe/ps51-stdin-bom`(-throw): 5.1 adds a BOM and CRLF to text piped into `gh`, so gh got bad JSON. (2) `data-off-main/ps-stdin-bom`: .NET Framework's `Process.Start` writes `[Console]::InputEncoding`'s preamble (a BOM on a `chcp 65001` console) into a redirected stdin, so `git update-index --index-info` refused.

**Invariant.** Under Windows PowerShell 5.1, a native command gets on stdin exactly the bytes the script means it to get, and nothing else. Body text goes to `gh` only as a file (BOM-less UTF-8 or raw `WriteAllBytes`) named with `--input`. It is never piped. Raw bytes go to `git` only through `GitRun`. Any path that can't make that guarantee fails closed: it returns failure **before** the command starts, and every caller treats that failure as a refusal.

## Every consumer in `scripts/*.ps1` (grep: Process.Start, RedirectStandardInput, StandardInput, `| gh`, `| git`, `| &`, `--stdin`, `--input`, Out-File/Set-Content/WriteAll*)
| # | Where | Feeds | How it meets the invariant | Pinned by |
|---|---|---|---|---|
| 1 | cutover-data-off-main.ps1 `GitRun`, the only `Process.Start` in scripts/ | git stdin | preamble-free `UTF8Encoding` swapped in around Start; re-read before Start, unreadable = BOM, Code 1 without Start on every call (ba3f63a) | `test_ps1_gitrun_starts_git_with_a_preamble_free_stdin_encoding` (text) |
| 1a | `GitignoreEdit` :361 `hash-object -w --stdin` (rollback) | `.gitignore` bytes | GitRun; caller checks `Code` and the 40-hex output | same, plus the new pin below |
| 1b | `BuildSeed` :393 `update-index -z --index-info` | NUL listing | GitRun; caller checks `$b.Code` | same |
| 1c | rollback :814 `update-index -z --force-remove --stdin` | ls-files output | GitRun; caller checks `Code` and calls Fail | same |
| 1d | the other GitRun/GitText calls (`$InBytes = $null`: read-tree, ls-files, cat-file, add, rm…) | nothing (stdin closed at once) | none of them reads stdin, so a stray BOM there changes nothing; still covered by the check if it is made unconditional | same |
| 2 | cutover `PutR1p` `gh api -X PUT … --input $path` | ruleset JSON | `WriteAllText` with BOM-less `$utf8` (:137), file + `--input` | `test_ps1_is_ascii_bom_less_and_51_safe` (no `\| gh`), stub at test :179 reads `--input` |
| 3 | cutover :402/:420/:616/:729/:776 listings, rpc.json; :634 `.gitignore` then `git add` | files read by python / git by path, not stdin | `WriteAllBytes` (raw) or BOM-less `$utf8` | listing digests are checked by the cutover tests; no stdin path |
| 4 | protect-main.ps1 :151/:156 `gh api … --input $file` | committed ruleset JSON | committed file, BOM-less ASCII | `test_protect_main.py` :362 (files BOM-less ASCII); no-pipe: `test_no_ps1_pipes_text_into_a_native_command_and_only_gitrun_starts_a_process` |
| 5 | u3-toggle.ps1 :123/:154 (and the :365 hint) `--input $path` | ruleset JSON | BOM-less `$utf8` file + `--input` | `test_u3_toggle.py` :325-328 (every PUT is `--input`), :700 (no `\| gh`) |
| 6 | v1-probe.ps1 :207-208 `git/trees --input $treeFile` | tree JSON | BOM-less UTF8Encoding file + `--input` (the PR #48 fix) | the `--jq` quote pin (test_workflow_lock) and the cross-script no-pipe test; no `--input` encoding pin |
| - | fetch-data.ps1, merge-reviewed.ps1, morning-note-probe.ps1 | none | they read native output only (`git ls-files \| Select-Object` pipes *out of* git); :275 writes a results file nothing reads | not needed |

## The fail-closed check (done, ba3f63a)
GitRun re-reads `[Console]::InputEncoding.GetPreamble()` after the swap attempt and before `Start`; a read that throws counts as a preamble; then it returns `Code = 1` with an empty `Out` and never starts git, on every call (1a-1d). All stdin callers treat `Code -ne 0` as a refusal or Fail. Pinned by text in `test_ps1_gitrun_starts_git_with_a_preamble_free_stdin_encoding` (swap < check < refuse < Start). Not yet run under 5.1: the next `-Plan` or the cutover on the big PC is the live check (a swap that doesn't take refuses at the first git call, which is safe).

## What is pinned across scripts, and what is not
`test_no_ps1_pipes_text_into_a_native_command_and_only_gitrun_starts_a_process` (tests/test_cutover_data_off_main.py), over every `scripts/*.ps1` outside comments: no pipe into `gh`/`git` by name or into `& $var`, and `Process]::Start` only in the cutover script. Left out, as a follow-up after the cutover (owner: backend-engineer): a check that every `--input` file is written BOM-less or committed as BOM-less ASCII, and that no `Out-File`/`Set-Content`/`>` output reaches a native command. Reason: each script's own tests already pin its `--input` writes except v1-probe's (its probe is retired until R1'), and a text check of "which file feeds which command" needs per-script data flow, so it is better as one careful test than a quick regex today.
