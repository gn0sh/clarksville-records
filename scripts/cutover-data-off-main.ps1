# Cut Daylight's collector data over from main to branch records-data (ADR 0011; docs/tasks/data-off-main.md D3, the
# Operator's order; consumer rows D, CFG, S4; PR #54 security review: drift, F2, F4, F5, F7). Brian runs this one;
# scripts/cutover-data-off-main.sh is its tested bash twin (same steps, same checks, same lines). Brian's PC only:
# every ruleset, settings and workflow write is his (U3-0 = no), so it refuses to run in a cloud session or CI
# (CLAUDE_CODE_REMOTE, GITHUB_ACTIONS, CI), except -Plan, which writes nothing on GitHub.
#
# Run it (PowerShell, in the repository folder; local scripts are allowed in Settings > For developers, never with
# an execution-policy bypass) from a checkout of the cutover PR at its reviewed head, so the checks run reviewed code:
#   git fetch origin pull/<P>/head
#   git checkout --detach <reviewed head>
#   powershell -NoProfile -File scripts\cutover-data-off-main.ps1 -Pr <P> -Sha <reviewed head> -Apps claude|none -Report <review>
#     -Apps: first open https://github.com/settings/installations and click Configure on each App: claude if the
#     Claude App (github.com/apps/claude) is the only one reaching this repository with any Read and write
#     permission and none of Administration, Variables, Secrets and Environments is Read and write (S1-2); none if no
#     App does. No token Brian holds can list Apps, so this is his hand check (ADR 0011 Amendment 2026-11-18 (b),
#     invariant I-person). Any other answer is refused before anything changes, and protect-main (which gets it in
#     step 4) reports any other answer NOT OK.
#   ... -Plan [-Ref <git rev>]    read-only: the seed step 3 would push from origin/main's data/, its checks,
#                                 "SEED DIGEST <sha256>" for the cutover PR's RECORDS_DATA_SEED_DIGEST, "BASELINE <sha>"
#                                 (origin/main) for its MAIN_PR_BASELINE, and the runbook 4.7.1 window listing from
#                                 WINDOW_START to that sha, to paste into the PR. Only gh reads, no push.
#   ... -Prepare                  on the cutover PR's branch (team, any machine): stages data/ out of the index
#                                 (git rm -r --cached: the files stay on disk), data/ into .gitignore and
#                                 .github/CODEOWNERS deleted. Commit that, then -Plan, and pin its SEED DIGEST in the
#                                 gate's RECORDS_DATA_SEED_DIGEST (sha256 of git ls-tree -r -z <seed> -- data).
#   ... -Rollback [-CutoverMerge <sha> [-DataFrom <sha>]]   undo (the .sh twin's --rollback --cutover-merge --data-from)
#   ... -Rollback -Merge <R> -Sha <reviewed head> -CutoverMerge <sha> -Report <review>
#   ... -CheckAttested            read-only: step 8's check again, for a later run
#
# Steps (it stops at the first failure and prints the exact -Rollback command):
#   1. Refuses, changing nothing, from 05:00 to 10:30 UTC (steps 7 and 8 must not meet the 09:07 cron), while a
#      daily-update run is not completed, or while the repository variable MORNING_NOTE_SEND exists (a refused or
#      failed read of actions/variables counts as set). Also unless PR <P> is open into main, authored by gn0sh,
#      from this repository, at <sha>, this checkout is at <sha> with no local change, the PR pins one 40-hex
#      MAIN_PR_BASELINE equal to origin/main (ADR 0011 Amendment (c)), its head contains that main, main still
#      tracks data/ and holds .github/CODEOWNERS and one empty MAIN_PR_BASELINE (what the early rollback needs),
#      the runbook 4.7.1 window listing from WINDOW_START to main passes (printed for the record), and the seed
#      (step 3) already passes its checks and equals the PR's pin. records-data must be absent, or exactly that
#      seed (a re-run).
#   2. Disables daily-update and reads it back; stops if a run started meanwhile.
#   3. Seeds records-data: main's data/ minus every moved input (the curated files incl. fin-books-accepted.yml,
#      data/localities/*/transcripts/ and data/maps/, I-in) whose config/ copy on the cutover head is the same blob,
#      as one parentless commit (read-tree, update-index --index-info, write-tree, commit-tree). Stops if main moved
#      off the pinned baseline, or unless its listing holds no transcripts/ folder, nothing under data/maps/ and no
#      curated name, passes
#      python -m collector.data_shape, its data/localities/cmc-rpc/rpc.json passes
#      python -m tools.scrub_rpc_phones --check --path, and its sha256 equals the PR's RECORDS_DATA_SEED_DIGEST.
#      Pushes it to refs/heads/records-data (never forced) and reads it back.
#   4. Runs scripts\protect-main.ps1 -PreCutover -Apps <answer> (the .sh: --pre-cutover); its last line must start
#      "OK: main is protected".
#   5. Merges the cutover PR with scripts\merge-reviewed.ps1 (main must still be the pinned baseline, and records-data
#      still the seed, read again just before: S1-5); its last line
#      must be "Rule suite <id> for <merge sha>: bypass", the squash's one parent must be the pinned baseline (this
#      merge sets it), and main must then track no data/. Then a plain scripts\protect-main.ps1 -Check -Apps
#      <answer> (no writes, main's new workflow) must print OK too.
#   6. Re-enables daily-update and reads it back.
#   7. Dispatches collect=false; the gate job must log its history line for exactly 1 commit after the baseline
#      (verified), the deploy job must succeed and build-info.json must name the seed as data_sha.
#   8. Dispatches collect=true (the first run after the baseline that pushes); the gate must log the same line, the
#      deploy must succeed, and records-data must then have moved past the seed with its listing verifying with
#      gh attestation verify --source-ref refs/heads/main --deny-self-hosted-runners (the gate's flags).
# -Rollback refuses at entry while the variable MORNING_NOTE_SEND or MAIN_PR_BASELINE exists (F4; a refused or
# failed read counts as set). It picks its path by where the cutover merge is, never by whether main tracks data/:
#   - -CutoverMerge <sha> on main's first-parent line: refuses unless that merge's parent tracks data/ and holds .github/CODEOWNERS and
#     one empty MAIN_PR_BASELINE, then disables daily-update and opens a PR from a new branch
#     rollback/data-on-main-<utc>: data/ from records-data's head, the workflow and .github/CODEOWNERS as before the
#     cutover merge, data/ out of .gitignore; config/ stays. The cutover merge must itself track no data/ and hold no
#     CODEOWNERS. S1-3: the data/ source must pass the gate's I-prov check (its listing attested by daily-update.yml
#     on main) or be the seed the merge's workflow pins; else it refuses, and -DataFrom <sha> picks an ancestor of
#     records-data's head that does.
#   - -Merge <R> -Sha <R's reviewed head> -CutoverMerge <sha>: refuses unless R's data/ listing is attested or the
#     seed pinned on main (S1-3; the pin is read from main, never from R or its parent: N1), R's head is one commit
#     whose parent is on main's first-parent line (N1), R's workflow and .github/CODEOWNERS are those of the commit
#     before the cutover merge (on main's first-parent line; never taken from R alone:
#     docs/architecture/data-off-main-trust-roots.md T-R3), and R's head tracks data/ and holds .github/CODEOWNERS and one empty MAIN_PR_BASELINE, disables daily-update,
#     merges R with merge-reviewed, then stops with R2 still off unless main is that merge, tracks data/, and holds
#     R's workflow, CODEOWNERS and data/ byte for byte with one empty
#     MAIN_PR_BASELINE (ADR 0011 Amendment (c) item 7). Only then R1' back, R2 on, workflow on.
#   - otherwise (the cutover merge is not on main): refuses unless main tracks data/ and holds .github/CODEOWNERS
#     and one empty MAIN_PR_BASELINE, then disables daily-update, main-ruleset-r1p.json (R1') back, R2 on
#     (can_approve_pull_request_reviews=true), workflow on.
# records-data is kept.
# Exit: 0 done, 1 refused (nothing changed), 2 stopped after a change (see the undo line; Ctrl+C from step 2 on too:
# "STOPPED at step N (interrupted)").
# Needs: git, GitHub CLI (winget install GitHub.cli) signed in as gn0sh, Python 3 with requirements.txt installed.
# No double quotes are passed to gh (Windows PowerShell 5.1 mangles them): strings come in through $ENV.
# Named parameters only: an unknown or .sh-style argument stops here, never binds to a parameter by position
# (data-off-main/ps-unknown-args). The binding is a dot-sourced advanced script block (its parameters become this
# script's variables) and the script itself is not advanced: in an advanced script the exit code set in the finally
# block below is lost after Ctrl+C, and the run exits 0 (data-off-main/ps-ctrlc-exit-zero; as u3-toggle.ps1). A
# binding failure exits 1 here, whatever the host does with one.
try {
    . {
        [CmdletBinding(PositionalBinding = $false)]
        param(
            [string]$Pr = '',
            [string]$Sha = '',
            [string]$Apps = '',
            [string[]]$Report = @(),
            [switch]$Plan,
            [switch]$Prepare,
            [string]$Ref = 'HEAD',
            [switch]$Rollback,
            [string]$CutoverMerge = '',
            [string]$DataFrom = '',
            [string]$Merge = '',
            [switch]$CheckAttested
        )
    } @args
} catch {
    Write-Host "REFUSED: $($_.Exception.Message) Named parameters only (-Pr <P> -Sha <sha> ...). Nothing was changed."
    exit 1
}
$ErrorActionPreference = 'Continue'   # 'Stop' turns gh's stderr into errors in PowerShell 5.1; exit codes are checked
Remove-TypeData System.Array -ErrorAction SilentlyContinue
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$repo = 'gn0sh/clarksville-records'
$owner = 'gn0sh'
$wfname = 'daily-update.yml'
$site = 'https://daylight.gnoshcodes.com'
$here = $PSScriptRoot
$r1p = Join-Path $here 'main-ruleset-r1p.json'
$me = 'powershell -NoProfile -File scripts\cutover-data-off-main.ps1'
$env:CO_OWNER = $owner
$env:CO_RULESET = 'main: pull request required'
$env:CO_DEPLOY = 'deploy'
$env:CO_BASE = 'main'
# ADR 0011 Amendment (c), runbook 4.7.1 (L-b, main-protect/window-start-gap): the window starts at main's sha read
# just before ruleset 27502319 (R1) was first written. That ruleset was created 2026-11-17T22:21:09Z (gh api
# rulesets/27502319 created_at). main was then 4c5cd910 (PR #31, merged 16:49:13Z by gn0sh) and did not move again
# until b5a3638d (PR #32, 00:02:13Z on 2026-11-18), so whatever the exact read, the start is 4c5cd910. Empty or wrong
# = step 1 refuses. Changed only by a reviewed PR (the same sha as the .sh twin's WINDOW_START).
$WINDOW_START = '4c5cd91022b74f5b7ad68ec94cdb863fcc444acd'
# The two known bot merges (ADR 0010; runbook 4.7.1): each its own PR, merged by a Bot, changing only v1-canary.yml
$KNOWN1 = '3ef440aea9e5ce7374cdb789a05d646d74a91ac3'; $KNOWN1_PR = '40'   # the V1 probe
$KNOWN2 = '2b207042a53e4d11dadfee978b029392df63c376'; $KNOWN2_PR = '49'   # the V1' probe (2026-11-18)
$utf8 = New-Object Text.UTF8Encoding $false
$latin1 = [Text.Encoding]::GetEncoding(28591)   # one char per byte: listings are matched and rebuilt byte for byte
$CURATED = 'names\.yml|procedural-titles\.yml|corrections-log\.json|published-fact-changes\.yml|fin-books-accepted\.yml'
$GUARD = "`tdata/(([^/]*/)*transcripts/|maps/|([^/]*/)*($CURATED)$)"
$MOVED = "^data/(localities/[^/]+/transcripts/|maps/|([^/]*/)*($CURATED)$)"
$RPC = 'data/localities/cmc-rpc/rpc.json'
$attestId = "https://github.com/$repo/.github/workflows/daily-update.yml@refs/heads/main"

function Utc { return [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ') }
function Shown([string]$s) { return ($s -replace '[^\x20-\x7E]', '?') }
$script:step = 0
$script:undo = "$me -Rollback"
$script:why = ''
# Set right before each intended exit; the finally block at the end treats a run that ends without it as
# interrupted (Ctrl+C, a stop signal or an error: data-off-main/ps-ctrlc-exit-zero)
$script:done = $false
function Refuse([string]$m) { Write-Host "REFUSED: $m. Nothing was changed."; $script:done = $true; exit 1 }
$script:mergeFrom = ''   # main's sha just before the cutover merge call; set from then on
function UndoLine {
    # After the merge call, main may have moved even when the call's output was not understood: the undo then needs
    # the merge sha (data-off-main/undo-line-after-merge).
    if ($script:mergeFrom -and $script:undo -ceq "$me -Rollback") {
        $now = FetchMain
        if ($now -and $now -cne $script:mergeFrom) { $script:undo = "$me -Rollback -CutoverMerge $now" }
    }
    return $script:undo
}
function Fail([string]$m) {
    $u = UndoLine
    Write-Host "STOPPED at step $($script:step) ($(Utc)): $m"
    Write-Host "Undo with: $u"
    $script:done = $true
    exit 2
}

if (-not $Plan -and -not $Prepare) {
    foreach ($v in @('CLAUDE_CODE_REMOTE', 'GITHUB_ACTIONS', 'CI')) {
        if ([Environment]::GetEnvironmentVariable($v)) {
            Refuse "$v is set: the cutover runs only from Brian's PC (ruleset, settings and workflow writes are his)"
        }
    }
}
$gitCmd = Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $gitCmd) { Refuse 'git not found: install it, then run this again' }
$gitExe = $gitCmd.Source

# git with raw bytes in and out (a PowerShell pipe would re-encode NUL-separated listings)
function QArg([string]$a) {
    if ($a -ne '' -and $a -notmatch '[\s"]') { return $a }
    $b = $a -replace '(\\*)"', '$1$1\"'
    $b = $b -replace '(\\+)$', '$1$1'
    return '"' + $b + '"'
}
function GitRun([string[]]$GitArgs, [byte[]]$InBytes = $null, [string]$Index = '') {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $gitExe
    $psi.Arguments = (@($GitArgs | ForEach-Object { QArg $_ }) -join ' ')
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardInput = $true
    if ($Index) { $psi.EnvironmentVariables['GIT_INDEX_FILE'] = $Index }
    # Windows PowerShell 5.1 (.NET Framework) wraps stdin in a StreamWriter of [Console]::InputEncoding and writes its
    # preamble at Start: on a UTF-8 console (chcp 65001) a BOM came before update-index's input ("malformed index
    # info", the 2026-11-19 -Plan run). So Start runs with a preamble-free InputEncoding, put back right after. If
    # that can't be set, git is not started at all: this call fails (Code 1), so no caller can take BOM'd input as
    # its own (hash-object --stdin would; ps51-stdin-bom-swap-fail-open). pwsh 7 strips the preamble itself.
    $ie = $null
    try { if ([Console]::InputEncoding.GetPreamble().Length -gt 0) { $ie = [Console]::InputEncoding; [Console]::InputEncoding = New-Object Text.UTF8Encoding($false) } } catch { }
    $bom = $true
    try { $bom = [Console]::InputEncoding.GetPreamble().Length -gt 0 } catch { $bom = $true }
    if ($bom) {
        if ($null -ne $ie) { try { [Console]::InputEncoding = $ie } catch { } }
        return New-Object PSObject -Property @{ Code = 1; Out = [byte[]]@() }
    }
    try { $p = [Diagnostics.Process]::Start($psi) } finally { if ($null -ne $ie) { try { [Console]::InputEncoding = $ie } catch { } } }
    $ms = New-Object IO.MemoryStream
    $copy = $p.StandardOutput.BaseStream.CopyToAsync($ms)
    if ($null -ne $InBytes) { $p.StandardInput.BaseStream.Write($InBytes, 0, $InBytes.Length) }
    $p.StandardInput.Close()
    $copy.Wait()
    $p.WaitForExit()
    return New-Object PSObject -Property @{ Code = $p.ExitCode; Out = $ms.ToArray() }
}
function GitText([string[]]$GitArgs, [string]$Index = '') {
    $r = GitRun $GitArgs $null $Index
    if ($r.Code -ne 0) { return $null }
    return ($utf8.GetString($r.Out)).TrimEnd("`r", "`n")
}
function Sha256Hex([byte[]]$b) {
    $h = [Security.Cryptography.SHA256]::Create().ComputeHash($b)
    return (-join @($h | ForEach-Object { $_.ToString('x2') }))
}
function Records([byte[]]$b) { return @($latin1.GetString($b).Split([char]0) | Where-Object { $_ -ne '' }) }

$top = GitText @('rev-parse', '--show-toplevel')
if (-not $top) { Refuse 'run this inside the clarksville-records checkout' }
try { Set-Location -LiteralPath $top -ErrorAction Stop } catch { Refuse "could not enter $top" }
$work = Join-Path ([IO.Path]::GetTempPath()) ('cutover-' + [Guid]::NewGuid().ToString('N'))
try { New-Item -ItemType Directory -Path $work -ErrorAction Stop | Out-Null } catch { Refuse 'could not make a temporary folder' }
$py = $null
foreach ($c in @(@('py', '-3'), @('python3'), @('python'))) {
    if (Get-Command $c[0] -CommandType Application -ErrorAction SilentlyContinue) {
        $pyArgs = @($c | Select-Object -Skip 1)
        & $c[0] @pyArgs -c 'import sys; sys.exit(sys.version_info < (3, 10))' *> $null
        if ($LASTEXITCODE -eq 0) { $py = $c; break }
    }
}
function PyRun([string[]]$PyArgs) {
    $pre = @($py | Select-Object -Skip 1)
    # Out-Host: the command's lines go to the screen, never into this function's output, so the return value is
    # only the exit code test (a failed check that prints a line would otherwise read as true in an if)
    & $py[0] @pre -B @PyArgs | Out-Host
    return ($LASTEXITCODE -eq 0)
}

# ---------------------------------------------------------------------------------------------- named calls
# Each call to another script or another branch's contract is one function, so a change there is one edit here.
function RunProtectMain([string]$a) {    # D1, before the merge: last line "OK: main is protected..."
    $out = @(& powershell -NoProfile -File (Join-Path $here 'protect-main.ps1') -PreCutover -Apps $a 2>&1 | ForEach-Object { "$_" })
    return New-Object PSObject -Property @{ Code = $LASTEXITCODE; Lines = $out }
}
function RunProtectCheck([string]$a) {   # D1, after the merge: no writes, same OK line
    $out = @(& powershell -NoProfile -File (Join-Path $here 'protect-main.ps1') -Check -Apps $a 2>&1 | ForEach-Object { "$_" })
    return New-Object PSObject -Property @{ Code = $LASTEXITCODE; Lines = $out }
}
function IsOkLine($lines) {
    $l = @($lines | Where-Object { $_ -match '\S' })
    return ($l.Count -gt 0 -and $l[-1].StartsWith('OK: main is protected', [StringComparison]::Ordinal))
}
function RunMergeReviewed([string]$p, [string]$s, [string[]]$r) {   # D1: last line "Rule suite <id> for <sha>: bypass"
    $out = @(& powershell -NoProfile -File (Join-Path $here 'merge-reviewed.ps1') $p $s @r 2>&1 | ForEach-Object { "$_" })
    return New-Object PSObject -Property @{ Code = $LASTEXITCODE; Lines = $out }
}
function RunDataShape([string]$f) { return (PyRun @('-m', 'collector.data_shape', $f)) }                       # B1/B1b
function RunScrubCheck([string]$f) { return (PyRun @('-m', 'tools.scrub_rpc_phones', '--check', '--path', $f)) } # B1b
function PinnedSeedDigest([string]$rev) {   # B2's gate env line RECORDS_DATA_SEED_DIGEST: "<64 hex>", exactly one
    $wf = GitText @('show', "${rev}:.github/workflows/$wfname")
    if ($null -eq $wf) { return $null }
    $lines = @($wf -split "`n" | Where-Object { $_ -cmatch '^\s*RECORDS_DATA_SEED_DIGEST:' })
    if ($lines.Count -ne 1) { return $null }
    if ($lines[0] -cmatch '^\s*RECORDS_DATA_SEED_DIGEST:\s*"([0-9a-f]{64})"') { return $Matches[1] }
    return $null
}
function PinnedBaseline([string]$rev) {   # the gate env line MAIN_PR_BASELINE: "<40 hex>", exactly one (Amendment (c))
    $wf = GitText @('show', "${rev}:.github/workflows/$wfname")
    if ($null -eq $wf) { return $null }
    $lines = @($wf -split "`n" | Where-Object { $_ -cmatch '^\s*MAIN_PR_BASELINE:' })
    if ($lines.Count -ne 1) { return $null }
    if ($lines[0] -cmatch '^\s*MAIN_PR_BASELINE:\s*"([0-9a-f]{40})"') { return $Matches[1] }
    return $null
}
function BaselineEmpty([string]$rev) {    # its workflow holds exactly one MAIN_PR_BASELINE line, and its value is "" (F4)
    $wf = GitText @('show', "${rev}:.github/workflows/$wfname")
    if ($null -eq $wf) { return $false }
    $keyLines = @($wf -split "`n" | Where-Object { $_ -cmatch '^\s*MAIN_PR_BASELINE:' })
    $emptyLines = @($wf -split "`n" | Where-Object { $_ -cmatch '^\s*MAIN_PR_BASELINE:\s*""(\s|$)' })
    return ($keyLines.Count -eq 1 -and $emptyLines.Count -eq 1)
}
function GateVerified([string]$id, [string]$base) {   # B2's gate job succeeded and logged its history line for exactly 1 commit
    $env:CO_JOB = 'gate'
    $g = (gh api "repos/$repo/actions/runs/$id/jobs?per_page=100" --jq '.jobs[] | select(.name == $ENV.CO_JOB) | [(.id|tostring), (.conclusion|tostring)] | @tsv') -join ''
    if ($LASTEXITCODE -ne 0) { return $false }
    $p = $g.Split("`t")
    if ($p.Count -ne 2 -or $p[0] -notmatch '^[0-9]+$' -or $p[1] -cne 'success') { Write-Host "The gate job reads '$g', not success."; return $false }
    $log = @(gh api "repos/$repo/actions/jobs/$($p[0])/logs")
    if ($LASTEXITCODE -ne 0) { return $false }
    $pat = 'Every commit on main after ' + $base + ' was merged by a person, reviewed at its head: *([0-9]+) commit\(s\)\.'
    $counts = @(foreach ($l in $log) { if ([string]$l -cmatch $pat) { $Matches[1] } })
    if (($counts -join ',') -cne '1') { Write-Host "The gate's history line after $base reads '$($counts -join ',')' commit(s), not exactly 1."; return $false }
    Write-Host "Gate: every commit on main after $base was merged by a person, reviewed at its head: 1 commit(s) (verified)."
    return $true
}
function BuildInfoDataSha {   # B4: the live site's build-info.json names D as data_sha (cache-busted)
    $t = [int64]([DateTime]::UtcNow - [DateTime]'1970-01-01').TotalSeconds
    try { $o = Invoke-RestMethod -Uri "$site/build-info.json?cutover=$t" -TimeoutSec 30 -UseBasicParsing } catch { return '' }
    return [string]$o.data_sha
}
function VerifyAttested([string]$f) {   # the gate's I-prov check (ADR 0011 decision 3)
    gh attestation verify $f --repo $repo --cert-identity $attestId --source-ref refs/heads/main --predicate-type https://slsa.dev/provenance/v1 --deny-self-hosted-runners | Out-Host   # as PyRun: only the exit code returns
    return ($LASTEXITCODE -eq 0)
}

# ---------------------------------------------------------------------------------------------- git helpers
function FetchMain {   # main's head on origin, fetched now; $null when the fetch failed (never a stale refs/cutover/main)
    if ((GitRun @('fetch', '--quiet', '--no-tags', 'origin', '+refs/heads/main:refs/cutover/main')).Code -ne 0) { return $null }
    return (GitText @('rev-parse', '--verify', '-q', 'refs/cutover/main^{commit}'))
}
function FetchRd {   # records-data's head on origin, '' when there is none, $null when it could not be read
    $r = GitRun @('ls-remote', 'origin', 'refs/heads/records-data')
    if ($r.Code -ne 0) { return $null }
    if ($r.Out.Length -eq 0) { return '' }
    $f = GitRun @('fetch', '--quiet', '--no-tags', 'origin', '+refs/heads/records-data:refs/cutover/records-data')
    if ($f.Code -ne 0) { return $null }
    return (GitText @('rev-parse', '--verify', '-q', 'refs/cutover/records-data^{commit}'))
}
function HasPath([string]$rev, [string]$path) {   # quiet, as the .sh's git cat-file -e 2>/dev/null: git's stderr
    # is not redirected here, and cat-file -e prints "fatal: path ... does not exist" on every correct rollback
    # (data-off-main/ps-fatal-noise)
    return [bool](GitText @('rev-parse', '--verify', '-q', "${rev}:$path"))
}
function TracksData([string]$rev) { $t = GitText @('ls-tree', '--name-only', $rev, '--', 'data'); return [bool]$t }
function OnMainLine([string]$rev, [string]$main) {   # $rev is a commit on main's first-parent line (the gate's own test);
    # every trust root the rollback reads comes from such a commit (docs/architecture/data-off-main-trust-roots.md)
    $c = GitText @('rev-parse', '--verify', '-q', "$rev^{commit}")
    if (-not $c) { return $false }
    $line = GitText @('rev-list', '--first-parent', $main)
    if ($null -eq $line) { return $false }
    return (@($line -split "`n" | Where-Object { $_ -ceq $c }).Count -eq 1)
}
function Parents([string]$c) {
    $t = GitText @('cat-file', 'commit', $c)
    if ($null -eq $t) { return -1 }
    $head = ($t -split "`n`n", 2)[0]
    return @($head -split "`n" | Where-Object { $_ -match '^parent ' }).Count
}
function ListingOf([string]$rev) { $r = GitRun @('ls-tree', '-r', '-z', $rev, '--', 'data'); if ($r.Code -ne 0) { return $null }; return ,$r.Out }
function GitignoreEdit([string]$rev) {   # the rollback's one .gitignore edit: $rev's .gitignore without its data/
    # lines, as a written blob sha (the same bytes as the .sh's grep -v); '' when $rev has none; $null on a failed
    # read. The open path writes it into R, the merge path checks R holds it (L1)
    $gi = GitText @('rev-parse', '--verify', '-q', "${rev}:.gitignore")
    if (-not $gi) { return '' }
    $r = GitRun @('cat-file', 'blob', $gi)
    if ($r.Code -ne 0) { return $null }
    $text = $latin1.GetString($r.Out)
    $lines = @()
    if ($text.Length -gt 0) {
        $lines = @($text -split "`n")
        if ($text.EndsWith("`n")) { $lines = @($lines | Select-Object -First ($lines.Count - 1)) }
    }
    $kept = @($lines | Where-Object { $_.TrimEnd("`r") -cnotmatch '^/?data/?(\*\*?)?\s*$' })
    $out = (@($kept | ForEach-Object { $_ + "`n" })) -join ''
    $hr = GitRun @('hash-object', '-w', '--stdin') $latin1.GetBytes($out)
    $nb = ($utf8.GetString($hr.Out)).Trim()
    if ($hr.Code -ne 0 -or $nb -cnotmatch '^[0-9a-f]{40}$') { return $null }
    return $nb
}

$script:seedTree = ''; $script:seedDigest = ''; $script:nSeed = 0; $script:nLeft = 0; $script:listing = $null
function BuildSeed([string]$mainRev, [string]$cfgRev, [switch]$Quiet) {
    $script:nSeed = 0; $script:nLeft = 0; $script:seedTree = ''; $script:seedDigest = ''
    $all = ListingOf $mainRev
    if ($null -eq $all) { $script:why = "could not read main's data/"; return $false }
    $keep = New-Object Text.StringBuilder
    foreach ($rec in (Records $all)) {
        $meta, $path = $rec.Split("`t", 2)
        $blob = $meta.Split(' ')[-1]
        if ($path -cmatch $MOVED) {
            $cfgPath = 'config/' + $path.Substring(5)
            $cb = GitText @('rev-parse', '--verify', '-q', "${cfgRev}:$cfgPath")
            if ($cb -ceq $blob) {
                $script:nLeft++
                if (-not $Quiet) { Write-Host (Shown "  left out (the cutover PR has it at $cfgPath): $path") }
                continue
            }
            if (-not $Quiet) { Write-Host (Shown "  kept, so refused below (the cutover PR has no same ${cfgPath}): $path") }
        }
        [void]$keep.Append($rec).Append([char]0)
        $script:nSeed++
    }
    $seedZ = $latin1.GetBytes($keep.ToString())
    $idx = Join-Path $work 'index'
    if (Test-Path -LiteralPath $idx) { Remove-Item -LiteralPath $idx -Force }
    $a = GitRun @('read-tree', '--empty') $null $idx
    $b = GitRun @('update-index', '-z', '--index-info') $seedZ $idx
    $t = GitText @('write-tree') $idx
    if ($a.Code -ne 0 -or $b.Code -ne 0 -or -not $t) { $script:why = 'could not build the seed tree'; return $false }
    $script:seedTree = $t
    $l = ListingOf $t
    if ($null -eq $l) { $script:why = "could not read the seed's listing"; return $false }
    if ((Sha256Hex $l) -cne (Sha256Hex $seedZ)) { $script:why = "the seed's listing is not main's data/ minus the moved inputs"; return $false }
    if ((GitText @('ls-tree', '--name-only', $t)) -cne 'data') { $script:why = 'the seed tree is not data/ only'; return $false }
    $script:listing = $l
    [IO.File]::WriteAllBytes((Join-Path $work 'listing'), $l)
    $script:seedDigest = Sha256Hex $l
    return $true
}
function CheckSeed {
    $bad = @(Records $script:listing | Where-Object { $_ -cmatch $GUARD })
    if ($bad.Count -gt 0) {
        foreach ($e in @($bad | Select-Object -First 20)) { Write-Host (Shown "  not allowed in the seed (I-in: it belongs in config/): $($e.Split("`t", 2)[1])") }
        $script:why = "the seed holds $($bad.Count) entries under a transcripts/ folder, data/maps/ or a curated name (I-in)"; return $false
    }
    Write-Host 'Seed names: no transcripts/ folder, nothing under data/maps/, no curated name.'
    if (-not (RunDataShape (Join-Path $work 'listing'))) { $script:why = "the seed's listing fails python -m collector.data_shape (I-data'')"; return $false }
    Write-Host 'Seed listing passes python -m collector.data_shape.'
    $b = GitText @('rev-parse', '--verify', '-q', "$($script:seedTree):$RPC")
    if (-not $b) { $script:why = "the seed has no $RPC for the phone check"; return $false }
    $r = GitRun @('cat-file', 'blob', $b)
    if ($r.Code -ne 0) { $script:why = "could not read the seed's $RPC"; return $false }
    $rpcFile = Join-Path $work 'rpc.json'
    [IO.File]::WriteAllBytes($rpcFile, $r.Out)
    if (-not (RunScrubCheck $rpcFile)) { $script:why = "the seed's $RPC has a phone number in a case location (tools/scrub_rpc_phones.py --check)"; return $false }
    Write-Host "Seed $RPC passes python -m tools.scrub_rpc_phones --check."
    return $true
}
function NeedPython {
    if ($null -eq $py) { Refuse 'Python 3.10 or later not found (py -3, python3 or python): install it and requirements.txt, then run this again' }
    $pre = @($py | Select-Object -Skip 1)
    & $py[0] @pre -B -c 'import collector.data_shape, tools.scrub_rpc_phones' *> $null
    if ($LASTEXITCODE -ne 0) { Refuse 'Python cannot load collector.data_shape and tools.scrub_rpc_phones here: run pip install -r requirements.txt, then this again' }
}

# ---------------------------------------------------------------------------------------------- GitHub helpers
function VarSet([string]$name) {   # $true when the repository variable exists or the list cannot be read (fail closed)
    $names = @(gh api --paginate "repos/$repo/actions/variables?per_page=100" --jq '.variables[].name' 2> $null)
    if ($LASTEXITCODE -ne 0) { return $true }
    return (@($names | Where-Object { $_ -ceq $name }).Count -gt 0)
}
function RunsBusy {   # the count of daily-update runs not completed; -1 on a failed read
    $st = @(gh api "repos/$repo/actions/workflows/$wfname/runs?per_page=30" --jq '.workflow_runs[].status')
    if ($LASTEXITCODE -ne 0) { return -1 }
    return @($st | Where-Object { $_ -and $_ -cne 'completed' }).Count
}
function WfSet([string]$what, [string]$want) {
    gh api -X PUT "repos/$repo/actions/workflows/$wfname/$what" --silent
    if ($LASTEXITCODE -ne 0) { return $false }
    $s = (gh api "repos/$repo/actions/workflows/$wfname" --jq '.state') -join ''
    if ($LASTEXITCODE -ne 0) { return $false }
    if ($s -cne $want) { Write-Host "daily-update reads '$s', not $want."; return $false }
    return $true
}
function DispatchRun([string]$collect) {   # dispatches on main; the new run's id, or ''
    $before = (gh api "repos/$repo/actions/workflows/$wfname/runs?event=workflow_dispatch&per_page=20" --jq '[.workflow_runs[].id] | max // 0') -join ''
    if ($LASTEXITCODE -ne 0 -or $before -notmatch '^[0-9]+$') { return '' }
    gh api -X POST "repos/$repo/actions/workflows/$wfname/dispatches" -f ref=main -f "inputs[collect]=$collect" --silent
    if ($LASTEXITCODE -ne 0) { return '' }
    $env:CO_BEFORE = $before
    for ($i = 1; $i -le 24; $i++) {
        Start-Sleep -Seconds 5
        $id = (gh api "repos/$repo/actions/workflows/$wfname/runs?event=workflow_dispatch&branch=main&per_page=20" --jq '[.workflow_runs[] | select(.id > ($ENV.CO_BEFORE | tonumber)) | .id] | min // empty' 2> $null) -join ''
        if ($LASTEXITCODE -eq 0 -and $id -match '^[0-9]+$') { return $id }
    }
    return ''
}
function WaitRun([string]$id, [int]$minutes) {   # its conclusion once completed, or $null
    $end = [DateTime]::UtcNow.AddMinutes($minutes)
    $fails = 0; $n = 0
    while ($true) {
        $st = (gh api "repos/$repo/actions/runs/$id" --jq '[.status, (.conclusion|tostring)] | @tsv' 2> $null) -join ''
        if ($LASTEXITCODE -ne 0 -or -not $st) { $fails++; if ($fails -ge 5) { return $null } }
        else {
            $fails = 0
            $parts = $st.Split("`t")
            if ($parts[0] -ceq 'completed') { return $parts[1] }
        }
        if ([DateTime]::UtcNow -ge $end) { return $null }
        $n++
        if ($n % 10 -eq 0) { Write-Host "  run $id still running ($(Utc))" }
        Start-Sleep -Seconds 30
    }
}
function Step8Wait {   # minutes step 8 may wait: at most 360, and the wait ends before 09:00 UTC (data-off-main/window-vs-duration)
    $now = (Get-Date).ToUniversalTime()
    $left = ((540 - ($now.Hour * 60 + $now.Minute) + 1440) % 1440) - 1
    if ($left -lt 1) { $left = 1 }
    if ($left -lt 360) { return $left }
    return 360
}
function JobConclusion([string]$id, [string]$job) {
    $env:CO_JOB = $job
    $c = (gh api "repos/$repo/actions/runs/$id/jobs?per_page=100" --jq '.jobs[] | select(.name == $ENV.CO_JOB) | .conclusion') -join ''
    if ($LASTEXITCODE -ne 0) { return '' }
    return $c
}
function Wl($o) {
    $actors = @(foreach ($a in $o.bypass_actors) {
        [ordered]@{ actor_id = $a.actor_id; actor_type = $a.actor_type; bypass_mode = $a.bypass_mode } })
    $actors = @($actors | Sort-Object -Property @{ Expression = { [string]$_.actor_type } }, @{ Expression = { [int64]$_.actor_id } }, @{ Expression = { [string]$_.bypass_mode } })
    $rules = @(foreach ($x in $o.rules) {
        if ($null -eq $x.parameters) { [ordered]@{ type = $x.type } }
        else { [ordered]@{ type = $x.type; parameters = $x.parameters } } })
    $rules = @($rules | Sort-Object -Property @{ Expression = { [string]$_.type } })
    return [ordered]@{ name = $o.name; target = $o.target; enforcement = $o.enforcement; conditions = $o.conditions;
                       bypass_actors = $actors; rules = $rules }
}
function Canon($v) {
    if ($null -eq $v) { return 'null' }
    if ($v -is [bool]) { if ($v) { return 'true' } else { return 'false' } }
    if ($v -is [string]) { return '"' + $v.Replace('\', '\\').Replace('"', '\"') + '"' }
    if ($v -is [System.Collections.IDictionary]) {
        $keys = @(@($v.Keys | ForEach-Object { [string]$_ }) | Sort-Object -CaseSensitive)
        return '{' + (@(foreach ($k in $keys) { (Canon $k) + ':' + (Canon $v[$k]) }) -join ',') + '}'
    }
    if ($v -is [System.Management.Automation.PSCustomObject]) {
        $keys = @(@($v.PSObject.Properties | ForEach-Object { $_.Name }) | Sort-Object -CaseSensitive)
        return '{' + (@(foreach ($k in $keys) { (Canon $k) + ':' + (Canon $v.$k) }) -join ',') + '}'
    }
    if ($v -is [System.Collections.IEnumerable]) { return '[' + (@(foreach ($x in $v) { Canon $x }) -join ',') + ']' }
    return [string]$v
}
function PutR1p {   # PUT main's scripts/main-ruleset-r1p.json (read at rollback step 1; whitelisted), read it back
    $ids = @(gh api --paginate "repos/$repo/rulesets?per_page=100" --jq '.[] | select(.name == $ENV.CO_RULESET) | .id')
    if ($LASTEXITCODE -ne 0) { Write-Host 'Could not list the rulesets.'; return $false }
    if ($ids.Count -ne 1 -or $ids[0] -notmatch '^[0-9]+$') { Write-Host "Expected exactly one ruleset named '$($env:CO_RULESET)', got: $($ids -join ',')"; return $false }
    $id = $ids[0]
    $want = $script:r1pWant   # main's, read at rollback step 1 (L2)
    if ($null -eq $want) { Write-Host 'Could not read scripts/main-ruleset-r1p.json.'; return $false }
    $path = Join-Path $work 'r1p.json'
    $json = ConvertTo-Json -InputObject (Wl $want) -Depth 20 -Compress
    [IO.File]::WriteAllText($path, $json, $utf8)
    gh api -X PUT "repos/$repo/rulesets/$id" --input $path --silent
    if ($LASTEXITCODE -ne 0) { return $false }
    $raw = (gh api "repos/$repo/rulesets/$id") -join "`n"
    if ($LASTEXITCODE -ne 0) { return $false }
    try { $live = $raw | ConvertFrom-Json } catch { return $false }
    if ((Canon (Wl $live)) -cne (Canon (Wl $want))) { Write-Host "Ruleset $id did not read back as R1'."; return $false }
    Write-Host "R1' back: ruleset $id reads back equal to scripts/main-ruleset-r1p.json."
    return $true
}
function R2On {
    gh api -X PUT "repos/$repo/actions/permissions/workflow" -F can_approve_pull_request_reviews=true --silent
    if ($LASTEXITCODE -ne 0) { return $false }
    $v = (gh api "repos/$repo/actions/permissions/workflow" --jq '.can_approve_pull_request_reviews') -join ''
    if ($LASTEXITCODE -ne 0 -or $v -cne 'true') { Write-Host "R2 reads '$v', not true."; return $false }
    Write-Host 'R2 on: GitHub Actions may create and approve pull requests (reads back true).'
    return $true
}
function NeedGh {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { Refuse 'gh not found: install it, then run this again' }
    gh auth status *> $null
    if ($LASTEXITCODE -ne 0) { Refuse "not signed in: run gh auth login (as $owner)" }
}
function MergedLineOk($lines) {   # the merge sha when the last line is a bypass rule suite for it, else ''
    $l = @($lines | Where-Object { $_ -match '\S' })
    if ($l.Count -eq 0) { return '' }
    if ($l[-1] -cmatch '^Rule suite [0-9]+ for ([0-9a-f]{40}): bypass$') { return $Matches[1] }
    return ''
}
function WindowCheck([string]$start, [string]$end) {   # the runbook 4.7.1 block; one line per commit and "checked N commits"
    if ($start -cnotmatch '^[0-9a-f]{40}$') { $script:why = "the window start '$start' is not a 40-hex sha (WINDOW_START in this script; runbook 4.7.1: the manager supplies it, else the architect picks the window)"; return $false }
    if ((GitRun @('merge-base', '--is-ancestor', $start, $end)).Code -ne 0) { $script:why = "the window start $start is not an ancestor of main $end"; return $false }
    $r = GitRun @('log', '--first-parent', '--format=%H', "${start}..${end}", '--', '.', ':(exclude)data/')
    if ($r.Code -ne 0) { $script:why = "could not list main's commits after $start"; return $false }
    $list = @(($utf8.GetString($r.Out)) -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    Write-Host "Window (runbook 4.7.1): every commit outside data/ on main's first-parent line from $start to ${end}:"
    $n = 0
    foreach ($c in $list) {
        $env:CO_COMMIT = $c
        $pr = (gh api "repos/$repo/commits/$c/pulls" --jq '[.[] | select(.merged_at != null and .base.ref == $ENV.CO_BASE and .merge_commit_sha == $ENV.CO_COMMIT) | .number] | first // empty') -join ''
        if ($LASTEXITCODE -ne 0) { $script:why = "could not read the pull requests of $c"; return $false }
        $t = 'none'
        if ($pr) {
            if ($pr -notmatch '^[0-9]+$') { $script:why = "could not read the pull requests of $c"; return $false }
            $t = (gh api "repos/$repo/pulls/$pr" --jq '.merged_by.type // empty') -join ''
            if ($LASTEXITCODE -ne 0) { $script:why = "could not read pull request #$pr"; return $false }
            if (-not $t) { $t = 'none' }
        } else { $pr = 'none' }
        $n++
        Write-Host "$c PR #$pr merged_by.type=$t"
        if ($t -ceq 'Bot' -and (($c -ceq $KNOWN1 -and $pr -ceq $KNOWN1_PR) -or ($c -ceq $KNOWN2 -and $pr -ceq $KNOWN2_PR))) {
            $files = GitText @('show', '--format=', '--name-only', $c)
            if ($null -eq $files) { $files = '' }
            if ($files.Trim() -ceq '.github/workflows/v1-canary.yml') {
                Write-Host "KNOWN EXCEPTION: $c is PR #$pr, a V1/V1' probe canary (only .github/workflows/v1-canary.yml); name it in the cutover PR"
                continue
            }
        }
        if ($t -cne 'User') { $script:why = "$c (PR #$pr) was not merged by a person (merged_by.type=$t): treat it as an incident; the baseline is not set"; return $false }
    }
    Write-Host "checked $n commits"
    if ($n -eq 0) { $script:why = "no commit in the window ${start}..$end (a wrong or placeholder start: the cutover PR's base at least is in it)"; return $false }
    return $true
}
function DataVerified([string]$file, [string]$seedPin) {   # J2's attestation (I-prov) or the pinned seed (S1-3); '' if neither
    if ($seedPin -and (Sha256Hex ([IO.File]::ReadAllBytes($file))) -ceq $seedPin) { return "the pinned seed (RECORDS_DATA_SEED_DIGEST $seedPin)" }
    if (VerifyAttested $file) { return 'attested by daily-update.yml on main' }
    return ''
}
function RestoreOk([string]$rev) {   # what R2 on needs there: data/ tracked, .github/CODEOWNERS, one empty MAIN_PR_BASELINE
    if (-not (TracksData $rev)) { $script:why = "$rev tracks no data/"; return $false }
    if (-not (HasPath $rev '.github/CODEOWNERS')) { $script:why = "$rev has no .github/CODEOWNERS"; return $false }
    if (-not (BaselineEmpty $rev)) { $script:why = "${rev}'s workflow sets MAIN_PR_BASELINE, or it is not exactly one empty value (counts as set)"; return $false }
    return $true
}
function CheckAttestedNow([string]$seed) {
    $d = FetchRd
    if ($null -eq $d) { $script:why = 'could not read records-data'; return $false }
    if (-not $d) { $script:why = 'records-data does not exist'; return $false }
    if ((Parents $d) -lt 1) { $script:why = "records-data $d is still a parentless commit (the seed): no run has pushed yet"; return $false }
    if ($seed) {
        $r = GitRun @('merge-base', '--is-ancestor', $seed, $d)
        if ($r.Code -ne 0) { $script:why = "records-data $d does not descend from the seed $seed"; return $false }
    }
    $l = ListingOf $d
    if ($null -eq $l) { $script:why = "could not read records-data's listing"; return $false }
    $f = Join-Path $work 'head-listing'
    [IO.File]::WriteAllBytes($f, $l)
    if (-not (VerifyAttested $f)) { $script:why = "records-data ${d}: its listing is not attested by daily-update.yml on main"; return $false }
    Write-Host "records-data $d (listing sha256 $(Sha256Hex $l)) is attested by daily-update.yml on main."
    return $true
}

try {
# ---------------------------------------------------------------------------------------------- -Prepare
if ($Prepare) {
    if (GitText @('ls-files', '--', 'data')) {
        if ((GitRun @('rm', '-r', '-q', '--cached', '--', 'data')).Code -ne 0) { Refuse 'git rm -r --cached data failed' }
        Write-Host 'Staged: data/ out of the index (the files stay on disk).'
    } else { Write-Host 'data/ is already out of the index.' }
    if ((GitRun @('check-ignore', '-q', 'data/')).Code -ne 0) {
        $gi = Join-Path $top '.gitignore'
        $old = ''
        if (Test-Path -LiteralPath $gi) { $old = [IO.File]::ReadAllText($gi, $utf8) }
        if ($old -and -not $old.EndsWith("`n")) { $old += "`n" }
        [IO.File]::WriteAllText($gi, $old + "# ADR 0011: collector output lives on branch records-data (scripts/fetch-data fills data/)`ndata/`n", $utf8)
        if ((GitRun @('add', '.gitignore')).Code -ne 0) { Refuse 'could not add data/ to .gitignore' }
        Write-Host 'Staged: data/ in .gitignore.'
    } else { Write-Host 'data/ is already ignored.' }
    if (GitText @('ls-files', '--', '.github/CODEOWNERS')) {
        if ((GitRun @('rm', '-q', '--', '.github/CODEOWNERS')).Code -ne 0) { Refuse 'git rm .github/CODEOWNERS failed' }
        Write-Host 'Staged: .github/CODEOWNERS deleted (ADR 0011 decision 5).'
    }
    if ((GitText @('ls-files', '--', 'data')) -or (GitRun @('check-ignore', '-q', 'data/')).Code -ne 0) {
        Refuse 'data/ is still tracked or not ignored after --prepare (-Prepare)'
    }
    Write-Host "PREPARED: commit this, then run $me -Plan and set RECORDS_DATA_SEED_DIGEST in the gate step's env to its SEED DIGEST."
    $script:done = $true; exit 0
}

# ---------------------------------------------------------------------------------------------- -Plan
if ($Plan) {
    NeedPython
    NeedGh
    $h = GitText @('rev-parse', '--verify', '-q', "$Ref^{commit}")
    if (-not $h) { Refuse "no commit '$Ref' here" }
    $m = FetchMain
    if (-not $m) { Refuse 'could not fetch main from origin' }
    if (-not (TracksData $m)) { Refuse "main $m tracks no data/: nothing to seed" }
    Write-Host "PLAN (nothing is pushed or written): the seed from main $m's data/, against the cutover head $h's config/."
    if (-not (BuildSeed $m $h)) { Refuse $script:why }
    Write-Host "Seed: $($script:nSeed) files ($($script:nLeft) moved inputs left out)."
    if (-not (CheckSeed)) { Refuse $script:why }
    Write-Host "SEED DIGEST $($script:seedDigest)"
    Write-Host "BASELINE $m"
    $stale = 0
    $p = PinnedSeedDigest $h
    if ($p) {
        if ($p -ceq $script:seedDigest) { Write-Host 'The cutover head pins this digest.' }
        else { Write-Host "The cutover head pins $p, not this digest: update RECORDS_DATA_SEED_DIGEST."; $stale = 1 }
    } else { Write-Host 'The cutover head pins no RECORDS_DATA_SEED_DIGEST yet: set it to the digest above.' }
    $p = PinnedBaseline $h
    if ($p) {
        if ($p -ceq $m) { Write-Host 'The cutover head pins this baseline.' }
        else { Write-Host "The cutover head pins MAIN_PR_BASELINE $p, not this baseline: update MAIN_PR_BASELINE."; $stale = 1 }
    } else { Write-Host 'The cutover head pins no single 40-hex MAIN_PR_BASELINE yet: set it to the BASELINE above.' }
    if ((GitRun @('merge-base', '--is-ancestor', $m, $h)).Code -ne 0) { Write-Host "The cutover head $h does not contain main ${m}: update its branch from main."; $stale = 1 }
    Write-Host "Paste everything from here to 'checked N commits' into the cutover PR (runbook 4.7.1):"
    if (-not (WindowCheck $WINDOW_START $m)) { Refuse "the window check stopped: $($script:why)" }
    $script:done = $true; exit $stale
}

# ---------------------------------------------------------------------------------------------- -CheckAttested
if ($CheckAttested) {
    NeedGh
    if (-not (CheckAttestedNow '')) { Write-Host "NOT ATTESTED: $($script:why)."; $script:done = $true; exit 1 }
    $script:done = $true; exit 0
}

# ---------------------------------------------------------------------------------------------- -Rollback
if ($Rollback) {
    NeedGh
    $script:step = 1
    Write-Host "Rollback step 1 ($(Utc)): refusals."
    if (VarSet 'MORNING_NOTE_SEND') { Refuse "MORNING_NOTE_SEND is set, or the variables could not be read (counts as set): Brian deletes it first (Settings > Secrets and variables > Actions > Variables), because R2 on reopens the bot path (F4)" }
    if (VarSet 'MAIN_PR_BASELINE') { Refuse 'the variable MAIN_PR_BASELINE is set, or the variables could not be read (counts as set): Brian deletes it first (F4)' }
    $m = FetchMain
    if (-not $m) { Refuse 'could not fetch main from origin' }
    # L2 data-off-main/rollback-checkout-unpinned: R1' is main $m's scripts/main-ruleset-r1p.json, never this checkout's
    $rr = GitRun @('cat-file', 'blob', "${m}:scripts/main-ruleset-r1p.json")
    $script:r1pWant = $null
    if ($rr.Code -eq 0) { try { $script:r1pWant = $utf8.GetString($rr.Out) | ConvertFrom-Json } catch { $script:r1pWant = $null } }
    if ($null -eq $script:r1pWant -or $script:r1pWant -is [Array] -or $null -eq $script:r1pWant.rules) { Refuse "main $m holds no readable scripts/main-ruleset-r1p.json (R1' is read from main)" }
    # The path is chosen by where the cutover merge is (main-protect/r2-on-without-codeowners), never by whether main
    # tracks data/. Every path checks, before any change, the commit R2 will come on over.
    if ($Merge) {
        $path = 'merge'
        if ($Merge -notmatch '^[0-9]+$' -or $Sha -cnotmatch '^[0-9a-f]{40}$' -or $CutoverMerge -cnotmatch '^[0-9a-f]{40}$' -or $Report.Count -lt 1) { Refuse '--merge needs <R> --sha <reviewed head> --cutover-merge <sha> --report <review> (the open path prints the line; -Merge, -Sha, -CutoverMerge, -Report)' }
        if ((GitRun @('fetch', '--quiet', '--no-tags', 'origin', "+refs/pull/$Merge/head:refs/cutover/rollback")).Code -ne 0) { Refuse "could not fetch pull request #$Merge's head" }
        if ((GitText @('rev-parse', '--verify', '-q', 'refs/cutover/rollback^{commit}')) -cne $Sha) { Refuse "origin's pull/$Merge/head is not $Sha" }
        if (-not (RestoreOk $Sha)) { Refuse "the restore PR #$Merge at $Sha does not give R2 what it needs: $($script:why) (F4)" }
        # Trust roots T-R3: the workflow and CODEOWNERS R2 comes on over are pinned to the commit before the cutover
        # merge, on main's first-parent line, never taken from R alone (R's author controls R)
        if (-not (OnMainLine $CutoverMerge $m)) { Refuse "--cutover-merge $CutoverMerge is not on main's first-parent line (give the merge sha step 5 printed; -CutoverMerge)" }
        if (TracksData $CutoverMerge) { Refuse "$CutoverMerge tracks data/: that is not the cutover merge (give the merge sha step 5 printed)" }
        if (HasPath $CutoverMerge '.github/CODEOWNERS') { Refuse "$CutoverMerge holds .github/CODEOWNERS: that is not the cutover merge (give the merge sha step 5 printed)" }
        $before = GitText @('rev-parse', '--verify', '-q', "$CutoverMerge^1")
        if (-not $before) { Refuse "could not read $CutoverMerge's parent" }
        foreach ($f in @(".github/workflows/$wfname", '.github/CODEOWNERS')) {
            $a = GitText @('rev-parse', '--verify', '-q', "${before}:$f")
            $b = GitText @('rev-parse', '--verify', '-q', "${Sha}:$f")
            if (-not $a -or $a -cne $b) { Refuse "the restore PR #$Merge's $f (blob '$b') is not the one before the cutover merge $CutoverMerge (blob '$a'; T-R3)" }
        }
        # S1-3 data-off-main/rollback-unverified-data: R's data/ must be a verified records-data tree (its listing
        # attested by J2, or the seed pinned on main). N1 data-off-main/rollback-seedpin-untrusted: the pin is read
        # from main $m (fetched above), never from R or its parent, which R's author controls
        $seedPin = PinnedSeedDigest $m
        $rl = ListingOf $Sha
        if ($null -eq $rl) { Refuse "could not read the restore PR's data/ listing" }
        $rlf = Join-Path $work 'r-listing'
        [IO.File]::WriteAllBytes($rlf, $rl)
        $srcOk = DataVerified $rlf $seedPin
        if (-not $srcOk) { Refuse "the restore PR #$Merge's data/ (listing sha256 $(Sha256Hex $rl)) is neither attested by daily-update.yml on main nor the pinned seed (S1-3): open a new one with --data-from <an attested records-data sha> (-DataFrom)" }
        # N1: R is one commit on main's first-parent line, so the squash merges exactly the reviewed head's diff
        $rp = GitText @('rev-parse', '--verify', '-q', "$Sha^1")
        if (-not $rp) { Refuse "could not read the restore PR's parent" }
        if ((Parents $Sha) -ne 1 -or -not (OnMainLine $rp $m)) { Refuse "the restore PR #$Merge's parent $rp is not on main's first-parent line (N1: R must be one commit on main, as --rollback --cutover-merge opens it; -CutoverMerge)" }
        # L1 data-off-main/rollback-r-scope-unchecked: against its parent, R changes only data/, the workflow, CODEOWNERS
        # and .gitignore (plumbing, no rename detection, NUL-separated), and its .gitignore is the open path's edit
        $sc = GitRun @('diff-tree', '-r', '--no-renames', '--name-only', '-z', $rp, $Sha)
        if ($sc.Code -ne 0) { Refuse "could not list the restore PR's changes" }
        $beyond = @(Records $sc.Out | Where-Object { -not ($_.StartsWith('data/', [StringComparison]::Ordinal) -or $_ -ceq ".github/workflows/$wfname" -or $_ -ceq '.github/CODEOWNERS' -or $_ -ceq '.gitignore') })
        if ($beyond.Count -gt 0) { Refuse (Shown "the restore PR #$Merge changes files beyond data/, the workflow, .github/CODEOWNERS and .gitignore: $($beyond -join ' ') (L1)") }
        $wantGi = GitignoreEdit $rp
        if ($null -eq $wantGi) { Refuse "could not read the .gitignore of the restore PR's parent $rp" }
        $haveGi = GitText @('rev-parse', '--verify', '-q', "${Sha}:.gitignore")
        if (-not $haveGi) { $haveGi = '' }
        if ($wantGi -cne $haveGi) {
            $shownHave = $haveGi; if (-not $shownHave) { $shownHave = 'none' }
            $shownWant = $wantGi; if (-not $shownWant) { $shownWant = 'none' }
            Refuse "the restore PR #$Merge's .gitignore (blob '$shownHave') is not its parent's without the data/ lines (blob '$shownWant'; L1)"
        }
        Write-Host "Restore PR #$Merge at $Sha tracks data/, holds .github/CODEOWNERS and one empty MAIN_PR_BASELINE; its data/ is $srcOk."
        Write-Host "Its workflow and .github/CODEOWNERS are those before the cutover merge $CutoverMerge; its parent $rp is on main."
    } elseif ($CutoverMerge -cmatch '^[0-9a-f]{40}$' -and (OnMainLine $CutoverMerge $m)) {
        $path = 'open'
        # main-protect/rollback-cutover-merge-unverified: the sha must look like the cutover merge itself
        if (TracksData $CutoverMerge) { Refuse "$CutoverMerge tracks data/: that is not the cutover merge (run $me -Rollback -CutoverMerge <sha> with the merge sha step 5 printed)" }
        if (HasPath $CutoverMerge '.github/CODEOWNERS') { Refuse "$CutoverMerge holds .github/CODEOWNERS: that is not the cutover merge (run $me -Rollback -CutoverMerge <sha> with the merge sha step 5 printed)" }
        $before = GitText @('rev-parse', '--verify', '-q', "$CutoverMerge^1")
        if (-not $before) { Refuse "could not read $CutoverMerge's parent" }
        if (-not (RestoreOk $before)) { Refuse "the commit before the cutover merge $CutoverMerge does not give R2 what it needs: $($script:why) (F4; is $CutoverMerge the cutover merge?)" }
        $d = FetchRd
        if ($null -eq $d) { Refuse 'could not read records-data' }
        if (-not $d) { Refuse 'records-data does not exist' }
        # S1-3 data-off-main/rollback-unverified-data: the data/ R restores must pass the gate's I-prov check (or be
        # the pinned seed): records-data's head, or -DataFrom, an ancestor of it on records-data
        $seedPin = PinnedSeedDigest $CutoverMerge
        if ($DataFrom) {
            if ($DataFrom -cnotmatch '^[0-9a-f]{40}$') { Refuse '--data-from needs a 40-hex sha on records-data (-DataFrom)' }
            if ((GitRun @('merge-base', '--is-ancestor', $DataFrom, $d)).Code -ne 0) { Refuse "--data-from $DataFrom is not on records-data (not an ancestor of its head $d)" }
            $src = $DataFrom
        } else { $src = $d }
        if (-not (TracksData $src)) { Refuse "records-data $src holds no data/" }
        $sl = ListingOf $src
        if ($null -eq $sl) { Refuse "could not read records-data $src's listing" }
        $slf = Join-Path $work 'src-listing'
        [IO.File]::WriteAllBytes($slf, $sl)
        $srcOk = DataVerified $slf $seedPin
        if (-not $srcOk) {
            if ($DataFrom) { Refuse "--data-from $DataFrom is neither attested by daily-update.yml on main nor the pinned seed (S1-3)" }
            Refuse "records-data's head $d is neither attested by daily-update.yml on main nor the pinned seed (S1-3): run $me -Rollback -CutoverMerge $CutoverMerge -DataFrom <sha> (the .sh: --data-from), an attested commit on records-data (for example the last head -CheckAttested accepted)"
        }
        Write-Host "The cutover merge $CutoverMerge is on main; its parent $before tracks data/, holds .github/CODEOWNERS and one empty MAIN_PR_BASELINE."
        Write-Host "R's data/ comes from records-data ${src}: $srcOk."
    } else {
        $path = 'early'
        if ($CutoverMerge) { Write-Host "--cutover-merge $CutoverMerge is not on main ${m}: taking the path for a cutover that is not merged." }
        if (-not (RestoreOk $m)) { Refuse "main $m does not give R2 what it needs: $($script:why). If the cutover merge is on main, run $me -Rollback -CutoverMerge <sha> (the .sh: --rollback --cutover-merge <sha>; the merge sha step 5 printed)" }
        Write-Host "main $m tracks data/, holds .github/CODEOWNERS and one empty MAIN_PR_BASELINE: the cutover merge is not on main."
    }
    Write-Host 'MORNING_NOTE_SEND and MAIN_PR_BASELINE are unset.'
    $script:step = 2
    if (-not (WfSet 'disable' 'disabled_manually')) { Fail 'could not disable daily-update' }
    Write-Host 'Rollback step 2: daily-update disabled (reads back disabled_manually).'
    if ($path -ceq 'early') {
        $script:step = 3
        $now = FetchMain
        if (-not $now) { Fail 'could not fetch main' }
        if ($now -cne $m) { Fail "main moved to $now since step 1 (was $m): run the rollback again" }
        if (-not (PutR1p)) { Fail "could not put R1' back" }
        if (-not (R2On)) { Fail 'could not turn R2 on' }
        if (-not (WfSet 'enable' 'active')) { Fail "could not re-enable daily-update (R1' and R2 are back)" }
        Write-Host "ROLLBACK DONE $(Utc): R1' back, R2 on, daily-update on. records-data is kept."
        $script:done = $true; exit 0
    }
    if ($path -ceq 'open') {
        $script:step = 3
        # main's tree, with data/ from records-data (anything main still tracks under data/ is replaced), the workflow
        # and CODEOWNERS from before the cutover, data/ un-ignored
        $idx = Join-Path $work 'index'
        if (Test-Path -LiteralPath $idx) { Remove-Item -LiteralPath $idx -Force }
        if ((GitRun @('read-tree', $m) $null $idx).Code -ne 0) { Fail 'could not build the restore tree' }
        $old = GitRun @('ls-files', '-z', '--', 'data') $null $idx
        if ($old.Code -ne 0) { Fail 'could not build the restore tree' }
        if ($old.Out.Length -gt 0 -and (GitRun @('update-index', '-z', '--force-remove', '--stdin') $old.Out $idx).Code -ne 0) { Fail 'could not build the restore tree' }
        if ((GitRun @('read-tree', '--prefix=data/', "${src}:data") $null $idx).Code -ne 0) { Fail 'could not build the restore tree' }
        foreach ($f in @(".github/workflows/$wfname", '.github/CODEOWNERS')) {
            $b = GitText @('rev-parse', '--verify', '-q', "${before}:$f")
            if (-not $b) { Fail "could not restore $f" }
            if ((GitRun @('update-index', '--add', '--cacheinfo', "100644,$b,$f") $null $idx).Code -ne 0) { Fail "could not restore $f" }
        }
        $nb = GitignoreEdit $m
        if ($null -eq $nb) { Fail 'could not edit .gitignore' }
        if ($nb -and (GitRun @('update-index', '--cacheinfo', "100644,$nb,.gitignore") $null $idx).Code -ne 0) { Fail 'could not edit .gitignore' }
        $t = GitText @('write-tree') $idx
        if (-not $t) { Fail 'could not write the restore tree' }
        $msg = "Roll back ADR 0011's cutover: data/ on main from records-data $src`n`ndata/ from records-data $src ($srcOk); .github/workflows/$wfname and .github/CODEOWNERS as before the cutover merge $CutoverMerge;`ndata/ out of .gitignore. Every config/ input and its readers stay as the cutover PR left them."
        $c = GitText @('commit-tree', $t, '-p', $m, '-m', $msg)
        if (-not $c) { Fail 'could not commit the restore (git user.name and user.email set?)' }
        if (-not (RestoreOk $c)) { Fail "the restore commit $c does not give R2 what it needs: $($script:why)" }
        $br = 'rollback/data-on-main-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')
        if ((GitRun @('push', '--quiet', 'origin', "${c}:refs/heads/$br")).Code -ne 0) { Fail "could not push $br (a workflow-file push needs: gh auth refresh -s workflow)" }
        Write-Host "Rollback step 3: pushed branch $br at $c (data/ from records-data $src)."
        $n = (gh api -X POST "repos/$repo/pulls" -f base=main -f head=$br -f 'title=Roll back the data cutover: data/ on main from records-data' -f "body=Restores data/ on main from records-data $src ($srcOk), and .github/workflows/$wfname and .github/CODEOWNERS as before the cutover merge $CutoverMerge (ADR 0011 rollback). config/ inputs stay. Opened by scripts/cutover-data-off-main.ps1 -Rollback." --jq '.number') -join ''
        if ($LASTEXITCODE -ne 0 -or $n -notmatch '^[0-9]+$') { Fail "could not open the pull request for $br" }
        Write-Host "ROLLBACK PR #$n opened for $br at $c. daily-update stays off; R2 stays off; the site stays as last deployed."
        Write-Host "Next, once PR #$n is reviewed at ${c}: $me -Rollback -Merge $n -Sha $c -CutoverMerge $CutoverMerge -Report <review>"
        $script:done = $true; exit 0
    }
    $script:step = 3
    $res = RunMergeReviewed $Merge $Sha $Report
    $res.Lines | ForEach-Object { Write-Host $_ }
    $ms = MergedLineOk $res.Lines
    if ($res.Code -ne 0 -or -not $ms) { Fail "merge-reviewed did not end with a bypass rule suite for PR #$Merge" }
    $m = FetchMain
    if (-not $m) { Fail 'could not fetch main after the merge' }
    if ($m -cne $ms -or -not (TracksData $m)) { Fail "main is at $m (merge $ms) and must track data/ after the restore" }
    Write-Host "Rollback step 3: PR #$Merge merged as $ms; main tracks data/ again."
    $script:step = 4
    # ADR 0011 Amendment (c) item 7 and main-protect/rollback-r2-unchecked-codeowners: before R2 goes on, main must
    # hold R's workflow and CODEOWNERS byte for byte, with one empty MAIN_PR_BASELINE. Else R2 stays off.
    foreach ($f in @(".github/workflows/$wfname", '.github/CODEOWNERS', 'data')) {
        $a = GitText @('rev-parse', '--verify', '-q', "${m}:$f")
        $b = GitText @('rev-parse', '--verify', '-q', "${Sha}:$f")
        if (-not $a -or $a -cne $b) { Fail "main $m does not hold the restore PR's $f (blob '$a', R has '$b'): R2 stays off" }
    }
    if (-not (RestoreOk $m)) { Fail "main $m does not give R2 what it needs: $($script:why). R2 stays off" }
    Write-Host "main $m holds R's workflow, .github/CODEOWNERS and data/ byte for byte, with one empty MAIN_PR_BASELINE."
    if (-not (PutR1p)) { Fail "could not put R1' back (the restore PR is merged)" }
    if (-not (R2On)) { Fail "could not turn R2 on (R1' is back)" }
    if (-not (WfSet 'enable' 'active')) { Fail "could not re-enable daily-update (R1' and R2 are back)" }
    Write-Host "ROLLBACK DONE $(Utc): data/ on main, R1' back, R2 on, daily-update on. records-data is kept."
    $script:done = $true; exit 0
}

# ---------------------------------------------------------------------------------------------- the cutover
if ($Pr -notmatch '^[0-9]+$' -or $Sha -cnotmatch '^[0-9a-f]{40}$' -or $Report.Count -lt 1) {
    Write-Host "Usage: $me -Pr <P> -Sha <reviewed head> -Apps claude|none -Report <review> | -Plan [-Ref <rev>] | -Rollback [-CutoverMerge <sha> [-DataFrom <sha>]] | -Rollback -Merge <R> -Sha <sha> -CutoverMerge <sha> -Report <review> | -CheckAttested"
    $script:done = $true; exit 1
}
NeedGh
NeedPython
$script:step = 1
Write-Host "Step 1 ($(Utc)): refusals and the planned seed (read-only)."
if (@('claude', 'none') -cnotcontains $Apps) {
    Refuse '--apps must be claude or none: first open https://github.com/settings/installations, click Configure on each App, and note each one that reaches clarksville-records with any Read and write permission; claude only if none of its Administration, Variables, Secrets and Environments permissions is Read and write (ADR 0011 Amendment (b), S1-2; -Apps here; protect-main needs the answer in step 4)'
}
Write-Host "Installed Apps with write on this repository, by Brian's hand check at https://github.com/settings/installations: $Apps."
$hm = [int](Get-Date).ToUniversalTime().ToString('HHmm')
if ($hm -ge 500 -and $hm -le 1030) {
    Refuse ("it is {0:D4} UTC, inside the daily run's window (05:00-10:30, so steps 7 and 8 end before the 09:07 run); run it later" -f $hm)
}
$busy = RunsBusy
if ($busy -lt 0) { Refuse 'could not read the daily-update runs' }
if ($busy -ne 0) { Refuse 'a daily-update run is queued or in progress; run it after that run completes' }
if (VarSet 'MORNING_NOTE_SEND') { Refuse 'MORNING_NOTE_SEND is set, or the variables could not be read (counts as set): Brian deletes it first (settings drift)' }
if (-not (Test-Path -LiteralPath $r1p)) { Refuse 'scripts/main-ruleset-r1p.json is missing (the rollback needs it)' }
$prline = (gh api "repos/$repo/pulls/$Pr" --jq '[(.state|tostring), (.base.ref|tostring), (.user.login|tostring), (.head.repo.full_name|tostring), (.head.sha|tostring), (.draft|tostring)] | @tsv') -join ''
if ($LASTEXITCODE -ne 0) { Refuse "could not read pull request #$Pr" }
$f = $prline.Split("`t")
if ($f.Count -ne 6) { Refuse "could not read pull request #$Pr" }
if ($f[0] -cne 'open' -or $f[1] -cne 'main') { Refuse "pull request #$Pr is not open into main" }
if ($f[2] -cne $owner) { Refuse "pull request #$Pr is authored by '$($f[2])', not $owner" }
if ($f[3] -cne $repo) { Refuse "pull request #$Pr's branch is in '$($f[3])', not $repo" }
if ($f[5] -cne 'false') { Refuse "pull request #$Pr is a draft" }
if ($f[4] -cne $Sha) { Refuse "pull request #$Pr's head is $($f[4]), not the reviewed $Sha" }
if ((GitRun @('fetch', '--quiet', '--no-tags', 'origin', "+refs/pull/$Pr/head:refs/cutover/pr")).Code -ne 0) { Refuse "could not fetch pull request #$Pr's head" }
if ((GitText @('rev-parse', '--verify', '-q', 'refs/cutover/pr^{commit}')) -cne $Sha) { Refuse "origin's pull/$Pr/head is not $Sha" }
if ((GitText @('rev-parse', 'HEAD')) -cne $Sha) { Refuse "this checkout is not at ${Sha}: git checkout --detach $Sha, then run this again" }
if (GitText @('status', '--porcelain', '--untracked-files=no')) { Refuse 'this checkout has local changes: the checks must run the reviewed code' }
if ((GitRun @('var', 'GIT_COMMITTER_IDENT')).Code -ne 0) { Refuse 'git has no user.name/user.email here (the seed commit needs them)' }
$pinned = PinnedSeedDigest $Sha
if (-not $pinned) { Refuse "the cutover PR's $wfname pins no single 64-hex RECORDS_DATA_SEED_DIGEST" }
$base = PinnedBaseline $Sha
if (-not $base) { Refuse "the cutover PR's $wfname pins no single 40-hex MAIN_PR_BASELINE (ADR 0011 Amendment (c): set it to the BASELINE that --plan prints; -Plan)" }
$m0 = FetchMain
if (-not $m0) { Refuse 'could not fetch main from origin' }
if ($m0 -cne $base) { Refuse "main is at $m0, but the cutover PR pins MAIN_PR_BASELINE $base (main moved: re-run --plan after it, update both pins and the window listing, and review again; -Plan)" }
if ((GitRun @('merge-base', '--is-ancestor', $m0, $Sha)).Code -ne 0) { Refuse "the cutover PR at $Sha does not contain main $m0 (update its branch from main, re-run --plan, review again; -Plan)" }
if (-not (TracksData $m0)) { Refuse "main $m0 tracks no data/: the cutover PR looks merged already" }
if (-not (RestoreOk $m0)) { Refuse "main $m0 is not a commit the early rollback can put R2 on over: $($script:why)" }
if (TracksData $Sha) { Refuse "the cutover PR at $Sha still tracks data/ (run --prepare on its branch; -Prepare)" }
if ((GitRun @('check-ignore', '-q', 'data/')).Code -ne 0) { Refuse "the cutover PR at $Sha does not gitignore data/ (run --prepare on its branch; -Prepare)" }
if (-not (WindowCheck $WINDOW_START $m0)) { Refuse "the window check stopped: $($script:why)" }
if (-not (BuildSeed $m0 $Sha)) { Refuse $script:why }
if (-not (CheckSeed)) { Refuse $script:why }
if ($script:seedDigest -cne $pinned) { Refuse "the seed from main $m0 has listing sha256 $($script:seedDigest), but the PR pins $pinned (main changed since: re-run -Plan and update the PR)" }
$rd = FetchRd
if ($null -eq $rd) { Refuse 'could not read records-data' }
if ($rd) {
    $rl = ListingOf $rd
    if ((Parents $rd) -ne 0 -or $null -eq $rl -or (Sha256Hex $rl) -cne $pinned) { Refuse "records-data already exists at $rd and is not this seed" }
    Write-Host "records-data already is this seed ($rd): step 3 keeps it."
}
Write-Host "Step 1 OK: PR #$Pr at $Sha, main $m0 = the PR's MAIN_PR_BASELINE, window checked, seed $($script:nSeed) files ($($script:nLeft) moved inputs left out), listing sha256 $($script:seedDigest) = the PR's pin."

$script:step = 2
if (-not (WfSet 'disable' 'disabled_manually')) { Fail 'could not disable daily-update' }
$busy = RunsBusy
if ($busy -lt 0) { Fail 'could not read the daily-update runs (daily-update is disabled)' }
if ($busy -ne 0) { Fail 'a daily-update run started before the disable; wait for it, then undo and start again' }
Write-Host 'Step 2 OK: daily-update disabled (reads back disabled_manually); no run active.'

$script:step = 3
$m = FetchMain
if (-not $m) { Fail 'could not fetch main' }
if ($m -cne $base) { Fail "main moved to $m since step 1, off the PR's MAIN_PR_BASELINE ${base}: undo, re-run --plan after it, update both pins, review again" }
if ($script:seedDigest -cne $pinned) { Fail "the seed from main $m has listing sha256 $($script:seedDigest), but the PR pins $pinned" }
if ($rd) { $seed = $rd }
else {
    $seed = GitText @('commit-tree', $script:seedTree, '-m', "records-data seed: data/ of main $m minus the moved inputs (ADR 0011)")
    if (-not $seed) { Fail 'could not commit the seed' }
    if ((GitRun @('push', '--quiet', 'origin', "${seed}:refs/heads/records-data")).Code -ne 0) { Fail 'could not push the seed to records-data' }
}
$got = FetchRd
if ($null -eq $got) { Fail 'could not read records-data back' }
$gl = $null
if ($got) { $gl = ListingOf $got }
if ($got -cne $seed -or (Parents $got) -ne 0 -or $null -eq $gl -or (Sha256Hex $gl) -cne $pinned) { Fail "records-data reads $got, not the parentless seed $seed" }
Write-Host "Step 3 OK: records-data = seed $seed (parentless, $($script:nSeed) files, listing sha256 $pinned), from main $m."

$script:step = 4
Write-Host "Step 4: scripts\protect-main.ps1 -PreCutover -Apps $Apps (R1'', R-D, R-T, R2 off; the .sh: --pre-cutover)."
$res = RunProtectMain $Apps
$res.Lines | ForEach-Object { Write-Host $_ }
if ($res.Code -ne 0 -or -not (IsOkLine $res.Lines)) { Fail 'protect-main did not print OK' }
Write-Host 'Step 4 OK: protect-main printed OK.'

$script:step = 5
$now = FetchMain
if (-not $now) { Fail 'could not fetch main' }
if ($now -cne $base) { Fail "main moved to $now since the seed was taken from $base, off the PR's MAIN_PR_BASELINE: nothing is merged" }
# S1-5 data-off-main/seed-window: records-data had no ruleset between step 3's push and step 4's R-D, so read it
# again right before the merge
$got = FetchRd
if ($null -eq $got) { Fail 'could not read records-data before the merge' }
if ($got -cne $seed -or (Parents $got) -ne 0) { Fail "records-data reads $got, no longer the seed $seed pushed in step 3 (S1-5): nothing is merged" }
Write-Host "records-data is still the seed $seed."
Write-Host "Step 5: scripts\merge-reviewed.ps1 $Pr $Sha (main $now = the pinned baseline)."
$script:mergeFrom = $now
$res = RunMergeReviewed $Pr $Sha $Report
$res.Lines | ForEach-Object { Write-Host $_ }
$ms = MergedLineOk $res.Lines
if ($res.Code -ne 0 -or -not $ms) { Fail 'merge-reviewed did not end with a bypass rule suite' }
$script:undo = "$me -Rollback -CutoverMerge $ms"
$m = FetchMain
if (-not $m) { Fail 'could not fetch main after the merge' }
if ($m -cne $ms) { Fail "main is at $m, not the merge $ms" }
$p1 = GitText @('rev-parse', '--verify', '-q', "$ms^1")
if ((Parents $ms) -ne 1 -or $p1 -cne $base) { Fail "the squash $ms has parent $p1, not the pinned MAIN_PR_BASELINE $base (the gate would check more than the cutover commit)" }
if (TracksData $m) { Fail "main $m still tracks data/ after the merge" }
Write-Host "Step 5: scripts\protect-main.ps1 -Check -Apps $Apps (main's new workflow, no writes; the .sh: --check)."
$res = RunProtectCheck $Apps
$res.Lines | ForEach-Object { Write-Host $_ }
if ($res.Code -ne 0 -or -not (IsOkLine $res.Lines)) { Fail 'protect-main --check did not print OK after the merge' }
Write-Host "Step 5 OK: PR #$Pr merged as $ms (rule suite bypass), parent = MAIN_PR_BASELINE $base; main tracks no data/; protect-main --check printed OK."
Write-Host "The undo from here on: $($script:undo)"

$script:step = 6
if (-not (WfSet 'enable' 'active')) { Fail "could not re-enable daily-update (or: gh workflow enable $wfname -R $repo)" }
Write-Host 'Step 6 OK: daily-update enabled (reads back active).'

$script:step = 7
$id = DispatchRun 'false'
if (-not $id) { Fail 'could not dispatch daily-update collect=false, or find its run' }
Write-Host "Step 7: run $id (collect=false): https://github.com/$repo/actions/runs/$id"
$c = WaitRun $id 120
if ($null -eq $c) { Fail "run $id did not complete within 120 minutes" }
if (-not (GateVerified $id $base)) { Fail "run $id's gate did not verify exactly the cutover commit after MAIN_PR_BASELINE $base" }
$dj = JobConclusion $id $env:CO_DEPLOY
if ($dj -cne 'success') { Fail "run $id ended $c; its deploy job is '$dj', not success" }
$bi = ''
for ($i = 1; $i -le 20; $i++) {
    $bi = BuildInfoDataSha
    if ($bi -ceq $seed) { break }
    if ($i -lt 20) { Start-Sleep -Seconds 30 }
}
if ($bi -cne $seed) { Fail "the site's build-info.json names data_sha '$bi', not the seed $seed" }
Write-Host "Step 7 OK: run $id deployed; $site/build-info.json names the seed $seed."

$script:step = 8
$id = DispatchRun 'true'
if (-not $id) { Fail 'could not dispatch daily-update collect=true, or find its run' }
Write-Host "Step 8: run $id (collect=true): https://github.com/$repo/actions/runs/$id"
$w = Step8Wait
Write-Host "Step 8: waiting up to $w minutes, so the wait ends before 09:00 UTC (the 09:07 daily run)."
$c = WaitRun $id $w
if ($null -eq $c) { Fail "run $id did not complete within $w minutes, and the wait ends before 09:00 UTC so it can't meet the 09:07 daily run (later: $me -CheckAttested)" }
Write-Host "Run $id ended $c."
if (-not (GateVerified $id $base)) { Fail "run $id's gate did not verify exactly the cutover commit after MAIN_PR_BASELINE $base" }
if (-not (CheckAttestedNow $seed)) { Fail $script:why }
$dj = JobConclusion $id $env:CO_DEPLOY
if ($dj -cne 'success') { Fail "run $id ended $c; its deploy job is '$dj', not success (records-data is attested)" }
Write-Host 'Step 8 OK.'
Write-Host "CUTOVER DONE $(Utc): PR #$Pr merged as $ms, seed $seed, records-data moved by run $id and attested."
Write-Host "Record in docs/status.md: the merge $ms, the seed $seed, run ids, and the first attested records-data head."
$script:done = $true; exit 0
} finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    # data-off-main/ps-ctrlc-exit-zero: after Ctrl+C PowerShell runs this block and then skips everything after it, so
    # the stop line, the undo line and the exit code are set here (the .sh: its INT/TERM/HUP trap). Steps 0 and 1
    # only read; from step 2 on, the undo line is the one Fail prints for the step.
    if (-not $script:done) {
        if ($script:step -lt 2) {
            Write-Host "STOPPED (interrupted) ($(Utc)) before any change. Nothing was written on GitHub."
            exit 1
        }
        $u = UndoLine
        Write-Host "STOPPED at step $($script:step) (interrupted) ($(Utc)): Ctrl+C, a stop signal or an error."
        Write-Host "Undo with: $u"
        exit 2
    }
}
