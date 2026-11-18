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
#   powershell -NoProfile -File scripts\cutover-data-off-main.ps1 -Pr <P> -Sha <reviewed head> -Apps <names>|none -Report <review>[,<review>]
#     -Apps: passed to protect-main (D1): the Apps https://github.com/settings/installations shows with write on this
#     repository, comma-separated, or none (no token Brian holds can list them).
#   ... -Plan [-Ref <git rev>]    read-only: the seed step 3 would push from origin/main's data/, its checks and
#                                 "SEED DIGEST <sha256>" for the cutover PR's RECORDS_DATA_SEED_DIGEST. No gh call.
#   ... -Rollback [-CutoverMerge <sha>]   undo (the .sh twin's --rollback --cutover-merge)
#   ... -Rollback -Merge <R> -Sha <reviewed head> -Report <review>
#   ... -CheckAttested            read-only: step 8's check again, for a later run
#
# Steps (it stops at the first failure and prints the exact -Rollback command):
#   1. Refuses, changing nothing, from 08:00 to 10:30 UTC, while a daily-update run is not completed, or while the
#      repository variable MORNING_NOTE_SEND exists (a refused or failed read of actions/variables counts as set).
#      Also unless PR <P> is open into main, authored by gn0sh, from this repository, at <sha>, this checkout is at
#      <sha> with no local change, main still tracks data/, and the seed (step 3) already passes its checks and
#      equals the PR's pin. records-data must be absent, or exactly that seed (a re-run).
#   2. Disables daily-update and reads it back; stops if a run started meanwhile.
#   3. Seeds records-data: main's data/ minus every moved input (the curated files incl. fin-books-accepted.yml,
#      data/localities/*/transcripts/ and data/maps/, I-in) whose config/ copy on the cutover head is the same blob,
#      as one parentless commit (read-tree, update-index --index-info, write-tree, commit-tree). Stops unless its
#      listing holds no transcripts/ folder, nothing under data/maps/ and no curated name, passes
#      python -m collector.data_shape, its data/localities/cmc-rpc/rpc.json passes
#      python -m tools.scrub_rpc_phones --check --path, and its sha256 equals the PR's RECORDS_DATA_SEED_DIGEST.
#      Pushes it to refs/heads/records-data (never forced) and reads it back.
#   4. Runs scripts\protect-main.ps1 -Apps <answer>; its last line must start "OK: main is protected".
#   5. Merges the cutover PR with scripts\merge-reviewed.ps1; its last line must be
#      "Rule suite <id> for <merge sha>: bypass", and main must then track no data/.
#   6. Re-enables daily-update and reads it back.
#   7. Dispatches collect=false; the deploy job must succeed and build-info.json must name the seed as data_sha.
#   8. Dispatches collect=true; records-data must then have moved past the seed and its listing must verify with
#      gh attestation verify --source-ref refs/heads/main --deny-self-hosted-runners (the gate's flags).
# -Rollback refuses while MORNING_NOTE_SEND or MAIN_PR_BASELINE is set (F4; a refused or failed read counts as set),
# then disables daily-update. If main still tracks data/: main-ruleset-r1p.json (R1') back, R2 on
# (can_approve_pull_request_reviews=true), workflow on. Otherwise (needs -CutoverMerge) it opens a PR from a new
# branch rollback/data-on-main-<utc>: data/ from records-data's head, the workflow and .github/CODEOWNERS as before
# the cutover merge, data/ out of .gitignore; config/ stays. Once reviewed, -Rollback -Merge merges it with
# merge-reviewed, then R1' back, R2 on, workflow on. records-data is kept.
# Exit: 0 done, 1 refused (nothing changed), 2 stopped after a change (see the undo line).
# Needs: git, GitHub CLI (winget install GitHub.cli) signed in as gn0sh, Python 3 with requirements.txt installed.
# No double quotes are passed to gh (Windows PowerShell 5.1 mangles them): strings come in through $ENV.
param(
    [string]$Pr = '',
    [string]$Sha = '',
    [string]$Apps = '',
    [string[]]$Report = @(),
    [switch]$Plan,
    [string]$Ref = 'HEAD',
    [switch]$Rollback,
    [string]$CutoverMerge = '',
    [string]$Merge = '',
    [switch]$CheckAttested
)
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
function Refuse([string]$m) { Write-Host "REFUSED: $m. Nothing was changed."; exit 1 }
function Fail([string]$m) {
    Write-Host "STOPPED at step $($script:step) ($(Utc)): $m"
    Write-Host "Undo with: $($script:undo)"
    exit 2
}

if (-not $Plan) {
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
    $p = [Diagnostics.Process]::Start($psi)
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
    & $py[0] @pre -B @PyArgs
    return ($LASTEXITCODE -eq 0)
}

# ---------------------------------------------------------------------------------------------- named calls
# Each call to another script or another branch's contract is one function, so a change there is one edit here.
function RunProtectMain([string]$a) {    # D1: last line "OK: main is protected..."
    $out = @(& powershell -NoProfile -File (Join-Path $here 'protect-main.ps1') -Apps $a 2>&1 | ForEach-Object { "$_" })
    return New-Object PSObject -Property @{ Code = $LASTEXITCODE; Lines = $out }
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
    $lines = @($wf -split "`n" | Where-Object { $_ -match 'RECORDS_DATA_SEED_DIGEST:' })
    if ($lines.Count -ne 1) { return $null }
    if ($lines[0] -cmatch '^\s*RECORDS_DATA_SEED_DIGEST:\s*"([0-9a-f]{64})"') { return $Matches[1] }
    return $null
}
function BuildInfoDataSha {   # B4: the live site's build-info.json names D as data_sha (cache-busted)
    $t = [int64]([DateTime]::UtcNow - [DateTime]'1970-01-01').TotalSeconds
    try { $o = Invoke-RestMethod -Uri "$site/build-info.json?cutover=$t" -TimeoutSec 30 -UseBasicParsing } catch { return '' }
    return [string]$o.data_sha
}
function VerifyAttested([string]$f) {   # the gate's I-prov check (ADR 0011 decision 3)
    gh attestation verify $f --repo $repo --cert-identity $attestId --source-ref refs/heads/main --predicate-type https://slsa.dev/provenance/v1 --deny-self-hosted-runners
    return ($LASTEXITCODE -eq 0)
}

# ---------------------------------------------------------------------------------------------- git helpers
function FetchMain {
    GitRun @('fetch', '--quiet', '--no-tags', 'origin', '+refs/heads/main:refs/cutover/main') | Out-Null
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
function TracksData([string]$rev) { $t = GitText @('ls-tree', '--name-only', $rev, '--', 'data'); return [bool]$t }
function Parents([string]$c) {
    $t = GitText @('cat-file', 'commit', $c)
    if ($null -eq $t) { return -1 }
    $head = ($t -split "`n`n", 2)[0]
    return @($head -split "`n" | Where-Object { $_ -match '^parent ' }).Count
}
function ListingOf([string]$rev) { $r = GitRun @('ls-tree', '-r', '-z', $rev, '--', 'data'); if ($r.Code -ne 0) { return $null }; return ,$r.Out }

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
function PutR1p {   # PUT scripts\main-ruleset-r1p.json (whitelisted) into main's ruleset, read it back
    $ids = @(gh api --paginate "repos/$repo/rulesets?per_page=100" --jq '.[] | select(.name == $ENV.CO_RULESET) | .id')
    if ($LASTEXITCODE -ne 0) { Write-Host 'Could not list the rulesets.'; return $false }
    if ($ids.Count -ne 1 -or $ids[0] -notmatch '^[0-9]+$') { Write-Host "Expected exactly one ruleset named '$($env:CO_RULESET)', got: $($ids -join ',')"; return $false }
    $id = $ids[0]
    try { $want = [IO.File]::ReadAllText($r1p, $utf8) | ConvertFrom-Json } catch { Write-Host 'Could not read scripts/main-ruleset-r1p.json.'; return $false }
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
# ---------------------------------------------------------------------------------------------- -Plan
if ($Plan) {
    NeedPython
    $h = GitText @('rev-parse', '--verify', '-q', "$Ref^{commit}")
    if (-not $h) { Refuse "no commit '$Ref' here" }
    $m = FetchMain
    if (-not $m) { Refuse 'could not fetch main from origin' }
    if (-not (TracksData $m)) { Refuse "main $m tracks no data/: nothing to seed" }
    Write-Host "PLAN (nothing is pushed): the seed from main $m's data/, against the cutover head $h's config/."
    if (-not (BuildSeed $m $h)) { Refuse $script:why }
    Write-Host "Seed: $($script:nSeed) files ($($script:nLeft) moved inputs left out)."
    if (-not (CheckSeed)) { Refuse $script:why }
    Write-Host "SEED DIGEST $($script:seedDigest)"
    $p = PinnedSeedDigest $h
    if ($p) {
        if ($p -ceq $script:seedDigest) { Write-Host 'The cutover head pins this digest.' }
        else { Write-Host "The cutover head pins $p, not this digest: update RECORDS_DATA_SEED_DIGEST."; exit 1 }
    } else { Write-Host 'The cutover head pins no RECORDS_DATA_SEED_DIGEST yet: set it to the digest above.' }
    exit 0
}

# ---------------------------------------------------------------------------------------------- -CheckAttested
if ($CheckAttested) {
    NeedGh
    if (-not (CheckAttestedNow '')) { Write-Host "NOT ATTESTED: $($script:why)."; exit 1 }
    exit 0
}

# ---------------------------------------------------------------------------------------------- -Rollback
if ($Rollback) {
    NeedGh
    if (-not (Test-Path -LiteralPath $r1p)) { Refuse 'scripts/main-ruleset-r1p.json is missing' }
    $script:step = 1
    Write-Host "Rollback step 1 ($(Utc)): refusals."
    if (VarSet 'MORNING_NOTE_SEND') { Refuse "MORNING_NOTE_SEND is set, or the variables could not be read (counts as set): Brian deletes it first (Settings > Secrets and variables > Actions > Variables), because R2 on reopens the bot path (F4)" }
    if (VarSet 'MAIN_PR_BASELINE') { Refuse 'the variable MAIN_PR_BASELINE is set, or the variables could not be read (counts as set): Brian deletes it first (F4)' }
    $m = FetchMain
    if (-not $m) { Refuse 'could not fetch main from origin' }
    $wf = GitText @('show', "${m}:.github/workflows/$wfname")
    if ($null -eq $wf) { Refuse "could not read main's workflow (MAIN_PR_BASELINE counts as set)" }
    $keyLines = @($wf -split "`n" | Where-Object { $_ -match 'MAIN_PR_BASELINE:' })
    $emptyLines = @($wf -split "`n" | Where-Object { $_ -cmatch '^\s*MAIN_PR_BASELINE:\s*""(\s|$)' })
    if ($keyLines.Count -ne 1 -or $emptyLines.Count -ne 1) {
        Refuse "main's workflow sets MAIN_PR_BASELINE, or it is not exactly one empty value (counts as set): a reviewed PR empties it first (F4)"
    }
    Write-Host 'MORNING_NOTE_SEND and MAIN_PR_BASELINE are unset.'
    $script:step = 2
    if (-not (WfSet 'disable' 'disabled_manually')) { Fail 'could not disable daily-update' }
    Write-Host 'Rollback step 2: daily-update disabled (reads back disabled_manually).'
    if (TracksData $m) {
        $script:step = 3
        Write-Host "main $m still tracks data/: the cutover PR was not merged, so nothing on main to restore."
        if (-not (PutR1p)) { Fail "could not put R1' back" }
        if (-not (R2On)) { Fail 'could not turn R2 on' }
        if (-not (WfSet 'enable' 'active')) { Fail "could not re-enable daily-update (R1' and R2 are back)" }
        Write-Host "ROLLBACK DONE $(Utc): R1' back, R2 on, daily-update on. records-data is kept."
        exit 0
    }
    if (-not $Merge) {
        $script:step = 3
        if ($CutoverMerge -cnotmatch '^[0-9a-f]{40}$') { Fail "main tracks no data/: run $me -Rollback -CutoverMerge <sha> with the merge sha step 5 printed" }
        if ((GitRun @('merge-base', '--is-ancestor', $CutoverMerge, $m)).Code -ne 0) { Fail "$CutoverMerge is not on main" }
        $before = GitText @('rev-parse', '--verify', '-q', "$CutoverMerge^1")
        if (-not $before) { Fail "could not read $CutoverMerge's parent" }
        if (-not (TracksData $before)) { Fail "$CutoverMerge's parent tracks no data/: that is not the cutover merge" }
        $d = FetchRd
        if ($null -eq $d) { Fail 'could not read records-data' }
        if (-not $d) { Fail 'records-data does not exist' }
        if (-not (TracksData $d)) { Fail "records-data $d holds no data/" }
        # main's tree, with data/ from records-data, the workflow and CODEOWNERS from before the cutover, data/ un-ignored
        $idx = Join-Path $work 'index'
        if (Test-Path -LiteralPath $idx) { Remove-Item -LiteralPath $idx -Force }
        if ((GitRun @('read-tree', $m) $null $idx).Code -ne 0) { Fail 'could not build the restore tree' }
        if ((GitRun @('read-tree', '--prefix=data/', "${d}:data") $null $idx).Code -ne 0) { Fail 'could not build the restore tree' }
        foreach ($f in @(".github/workflows/$wfname", '.github/CODEOWNERS')) {
            $b = GitText @('rev-parse', '--verify', '-q', "${before}:$f")
            if ($b) { $r = GitRun @('update-index', '--add', '--cacheinfo', "100644,$b,$f") $null $idx }
            else { $r = GitRun @('update-index', '--force-remove', '--', $f) $null $idx }
            if ($r.Code -ne 0) { Fail "could not restore $f" }
        }
        $gi = GitText @('rev-parse', '--verify', '-q', "${m}:.gitignore")
        if ($gi) {
            $text = $latin1.GetString((GitRun @('cat-file', 'blob', $gi)).Out)
            $kept = @($text -split "`n" | Where-Object { $_.TrimEnd("`r") -notmatch '^/?data/?(\*\*?)?\s*$' })
            $hr = GitRun @('hash-object', '-w', '--stdin') $latin1.GetBytes(($kept -join "`n"))
            $nb = ($utf8.GetString($hr.Out)).Trim()
            if ($hr.Code -ne 0 -or (GitRun @('update-index', '--cacheinfo', "100644,$nb,.gitignore") $null $idx).Code -ne 0) { Fail 'could not edit .gitignore' }
        }
        $t = GitText @('write-tree') $idx
        if (-not $t) { Fail 'could not write the restore tree' }
        $msg = "Roll back ADR 0011's cutover: data/ on main from records-data $d`n`ndata/ from records-data $d; .github/workflows/$wfname and .github/CODEOWNERS as before the cutover merge $CutoverMerge;`ndata/ out of .gitignore. Every config/ input and its readers stay as the cutover PR left them."
        $c = GitText @('commit-tree', $t, '-p', $m, '-m', $msg)
        if (-not $c) { Fail 'could not commit the restore (git user.name and user.email set?)' }
        $br = 'rollback/data-on-main-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')
        if ((GitRun @('push', '--quiet', 'origin', "${c}:refs/heads/$br")).Code -ne 0) { Fail "could not push $br (a workflow-file push needs: gh auth refresh -s workflow)" }
        Write-Host "Rollback step 3: pushed branch $br at $c (data/ from records-data $d)."
        $n = (gh api -X POST "repos/$repo/pulls" -f base=main -f head=$br -f 'title=Roll back the data cutover: data/ on main from records-data' -f "body=Restores data/ on main from records-data $d, and .github/workflows/$wfname and .github/CODEOWNERS as before the cutover merge $CutoverMerge (ADR 0011 rollback). config/ inputs stay. Opened by scripts/cutover-data-off-main.ps1 -Rollback." --jq '.number') -join ''
        if ($LASTEXITCODE -ne 0 -or $n -notmatch '^[0-9]+$') { Fail "could not open the pull request for $br" }
        Write-Host "ROLLBACK PR #$n opened for $br at $c. daily-update stays off; the site stays as last deployed."
        Write-Host "Next, once PR #$n is reviewed at ${c}: $me -Rollback -Merge $n -Sha $c -Report <review>"
        exit 0
    }
    $script:step = 3
    if ($Merge -notmatch '^[0-9]+$' -or $Sha -cnotmatch '^[0-9a-f]{40}$' -or $Report.Count -lt 1) { Fail '--merge needs <R> --sha <reviewed head> --report <review> (-Merge, -Sha, -Report)' }
    $res = RunMergeReviewed $Merge $Sha $Report
    $res.Lines | ForEach-Object { Write-Host $_ }
    $ms = MergedLineOk $res.Lines
    if ($res.Code -ne 0 -or -not $ms) { Fail "merge-reviewed did not end with a bypass rule suite for PR #$Merge" }
    $m = FetchMain
    if (-not $m) { Fail 'could not fetch main after the merge' }
    if ($m -cne $ms -or -not (TracksData $m)) { Fail "main is at $m (merge $ms) and must track data/ after the restore" }
    Write-Host "Rollback step 3: PR #$Merge merged as $ms; main tracks data/ again."
    $script:step = 4
    if (-not (PutR1p)) { Fail "could not put R1' back (the restore PR is merged)" }
    if (-not (R2On)) { Fail "could not turn R2 on (R1' is back)" }
    if (-not (WfSet 'enable' 'active')) { Fail "could not re-enable daily-update (R1' and R2 are back)" }
    Write-Host "ROLLBACK DONE $(Utc): data/ on main, R1' back, R2 on, daily-update on. records-data is kept."
    exit 0
}

# ---------------------------------------------------------------------------------------------- the cutover
if ($Pr -notmatch '^[0-9]+$' -or $Sha -cnotmatch '^[0-9a-f]{40}$' -or $Report.Count -lt 1) {
    Write-Host "Usage: $me -Pr <P> -Sha <reviewed head> -Apps <names>|none -Report <review>[,<review>] | -Plan [-Ref <rev>] | -Rollback [-CutoverMerge <sha>] | -Rollback -Merge <R> -Sha <sha> -Report <review> | -CheckAttested"
    exit 1
}
NeedGh
NeedPython
$script:step = 1
Write-Host "Step 1 ($(Utc)): refusals and the planned seed (read-only)."
if ($Apps -cnotmatch '^(none|[a-z0-9][a-z0-9-]*(,[a-z0-9][a-z0-9-]*)*)$') {
    Refuse '--apps takes the App names https://github.com/settings/installations shows with write on this repository, comma-separated, or none (protect-main needs them in step 4; -Apps here)'
}
$hm = [int][DateTime]::UtcNow.ToString('HHmm')
if ($hm -ge 800 -and $hm -le 1030) {
    Refuse ("it is {0:D4} UTC, inside the daily run's window (08:00-10:30); run it later" -f $hm)
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
$m0 = FetchMain
if (-not $m0) { Refuse 'could not fetch main from origin' }
if (-not (TracksData $m0)) { Refuse "main $m0 tracks no data/: the cutover PR looks merged already" }
if (TracksData $Sha) { Refuse "the cutover PR at $Sha still tracks data/" }
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
Write-Host "Step 1 OK: PR #$Pr at $Sha, main $m0, seed $($script:nSeed) files ($($script:nLeft) moved inputs left out), listing sha256 $($script:seedDigest) = the PR's pin."

$script:step = 2
if (-not (WfSet 'disable' 'disabled_manually')) { Fail 'could not disable daily-update' }
$busy = RunsBusy
if ($busy -lt 0) { Fail 'could not read the daily-update runs (daily-update is disabled)' }
if ($busy -ne 0) { Fail 'a daily-update run started before the disable; wait for it, then undo and start again' }
Write-Host 'Step 2 OK: daily-update disabled (reads back disabled_manually); no run active.'

$script:step = 3
$m = FetchMain
if (-not $m) { Fail 'could not fetch main' }
if ($m -cne $m0) {
    Write-Host "main moved to $m since step 1: building the seed again."
    if (-not (BuildSeed $m $Sha)) { Fail $script:why }
    if (-not (CheckSeed)) { Fail $script:why }
}
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
Write-Host "Step 4: scripts\protect-main.ps1 -Apps $Apps (R1'', R-D, R-T, R2 off)."
$res = RunProtectMain $Apps
$res.Lines | ForEach-Object { Write-Host $_ }
$last = @($res.Lines | Where-Object { $_ -match '\S' })
if ($res.Code -ne 0 -or $last.Count -eq 0 -or -not $last[-1].StartsWith('OK: main is protected', [StringComparison]::Ordinal)) { Fail 'protect-main did not print OK' }
Write-Host 'Step 4 OK: protect-main printed OK.'

$script:step = 5
$now = FetchMain
if (-not $now) { Fail 'could not fetch main' }
if ($now -cne $m) {
    if (-not (BuildSeed $now $Sha -Quiet) -or $script:seedDigest -cne $pinned) {
        Fail "main moved to $now since the seed was taken from $m, and its data/ no longer gives the seed"
    }
}
Write-Host "Step 5: scripts\merge-reviewed.ps1 $Pr $Sha (main $now)."
$res = RunMergeReviewed $Pr $Sha $Report
$res.Lines | ForEach-Object { Write-Host $_ }
$ms = MergedLineOk $res.Lines
if ($res.Code -ne 0 -or -not $ms) { Fail 'merge-reviewed did not end with a bypass rule suite' }
$script:undo = "$me -Rollback -CutoverMerge $ms"
$m = FetchMain
if (-not $m) { Fail 'could not fetch main after the merge' }
if ($m -cne $ms) { Fail "main is at $m, not the merge $ms" }
if (TracksData $m) { Fail "main $m still tracks data/ after the merge" }
Write-Host "Step 5 OK: PR #$Pr merged as $ms (rule suite bypass); main tracks no data/."
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
$c = WaitRun $id 360
if ($null -eq $c) { Fail "run $id did not complete within 6 hours (later: $me -CheckAttested)" }
Write-Host "Run $id ended $c (deploy: $(JobConclusion $id $env:CO_DEPLOY))."
if (-not (CheckAttestedNow $seed)) { Fail $script:why }
Write-Host 'Step 8 OK.'
Write-Host "CUTOVER DONE $(Utc): PR #$Pr merged as $ms, seed $seed, records-data moved by run $id and attested."
Write-Host "Record in docs/status.md: the merge $ms, the seed $seed, run ids, and the first attested records-data head."
exit 0
} finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
