# U3 positive control (docs/ops/u3-positive-control.md; ADR 0011 decision 5; task U3-1). Brian runs this one;
# scripts/u3-toggle.sh is its tested bash twin (same steps, same lines, same verdicts).
#
# Question: under R1'' (2 required approvals, last-push approval, no code-owner review, squash only, admin bypass in
# pull_request mode) does the team's merge-reviewed merge of a docs-only PR go through as a bypass?
#
# Run (PowerShell, in the repository folder; local scripts are allowed in Settings > For developers):
#   .\scripts\u3-toggle.ps1 -Pr <P>                        Brian's path: opens the window, waits for main to move
#   .\scripts\u3-toggle.ps1 -Pr <P> -Merge -Report <R>     team path: runs scripts\merge-reviewed.ps1 <P> <head> <R>
#   .\scripts\u3-toggle.ps1 -Restore [-From <backup json>] PUTs scripts\main-ruleset.json (R1'), or that backup
#   .\scripts\u3-toggle.ps1 -Noop                          U3-0: PUTs the live ruleset back unchanged, reads it back
#   .\scripts\u3-toggle.ps1 -ShowBody <json>               prints the PUT body built from a file; no GitHub call
#
# Steps (it stops at the first failure):
#   1. Preflight, read-only: refuses (nothing changed) at 08:00-10:30 UTC, while a daily-update run is not completed,
#      unless ruleset 27502319 equals R1' (scripts\main-ruleset.json) on every written field, unless PR P is open into
#      main, authored by gn0sh, from a branch of this repository, not a draft, mergeable and docs-only, and unless
#      current_user_can_bypass is pull_requests_only or always. Saves the live ruleset to Documents.
#   2. PUTs R1'' (scripts\main-ruleset-r1pp.json) and reads it back; any difference closes the window at once.
#      Prints "U3 WINDOW OPEN <utc> backup <file>". From here on every exit (error, Ctrl+C) restores the backup.
#   3. Team path: runs merge-reviewed. Brian's path: checks main every 15 s for up to 20 minutes. If the team's merge
#      is refused, the manager comments "U3 merge refused: <gh's message>" on PR P; that ends the wait as FAIL-U3.
#   4. Reads PR P (merged, merged_by, merge_commit_sha), the ruleset again (still R1''?) and the rule suite whose
#      after_sha is the merge commit.
#   5. Restores the backup, reads it back, prints "RESTORED <utc>", then one line:
#      "U3 VERDICT <PASS|FAIL-U3|FAIL-RULE|INCONCLUSIVE> rule-suite <id|none>: <detail>".
# Every PUT body comes from one function (Wl below): only name, target, enforcement, conditions, bypass_actors
# (actor_id, actor_type, bypass_mode) and rules (type, parameters); never id, _links, source or
# current_user_can_bypass. Bodies are written as BOM-less UTF-8 files and passed with --input (never piped: Windows
# PowerShell 5.1 adds a BOM to piped text, v1-probe/ps51-stdin-bom), then re-read to prove they say the same.
# Exit: 0 PASS (or -Restore / -Noop verified), 1 refused before any write, 2 any other verdict (restored), 3 the
# restore (or -Noop) did not read back as written.
# Needs: GitHub CLI (winget install GitHub.cli), signed in as gn0sh (gh auth login).
# No double quotes are passed to gh (Windows PowerShell 5.1 mangles them): strings come in through $ENV.
param(
    [string]$Pr = '',
    [switch]$Merge,
    [string]$Report = '',
    [switch]$Restore,
    [string]$From = '',
    [switch]$Noop,
    [string]$ShowBody = ''
)
$ErrorActionPreference = 'Continue'   # 'Stop' turns gh's stderr into errors in PowerShell 5.1; exit codes are checked
# Windows PowerShell 5.1 can serialise arrays as {"value":[...],"Count":n}; the re-read below would catch it anyway
Remove-TypeData System.Array -ErrorAction SilentlyContinue
$repo = 'gn0sh/clarksville-records'
$owner = 'gn0sh'
$rid = '27502319'
$r1p = Join-Path $PSScriptRoot 'main-ruleset.json'
$r1pp = Join-Path $PSScriptRoot 'main-ruleset-r1pp.json'
$env:U3_OWNER = $owner
$env:U3_RULE = 'pull_request'
$env:U3_RID = $rid
$utf8 = New-Object Text.UTF8Encoding $false

function Utc { return (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
function Usage {
    Write-Host 'Usage: .\scripts\u3-toggle.ps1 -Pr <P> [-Merge -Report <review report>] | -Restore [-From <backup json>] | -Noop | -ShowBody <json>'
}

# The one whitelist: every PUT body and every comparison goes through it (order made canonical: rules by type).
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
# A canonical text of a value (keys sorted), for exact comparisons.
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
function CanonRs($o) { return (Canon (Wl $o)) }
# read-only or unknown fields inside a rule or bypass actor (the whitelist would hide them in a comparison)
function Extras($o) {
    $bad = @()
    foreach ($x in $o.rules) { foreach ($p in $x.PSObject.Properties) {
        if ($p.Name -cne 'type' -and $p.Name -cne 'parameters') { $bad += ('rules.' + $p.Name) } } }
    foreach ($a in $o.bypass_actors) { foreach ($p in $a.PSObject.Properties) {
        if (@('actor_id', 'actor_type', 'bypass_mode') -cnotcontains $p.Name) { $bad += ('bypass_actors.' + $p.Name) } } }
    return ($bad -join ',')
}
function ReadJsonFile($path) {
    try { return ([IO.File]::ReadAllText($path, $utf8) | ConvertFrom-Json) } catch { return $null }
}
# The whitelisted PUT body of $o, written to $path (BOM-less) and re-read: $true only if it says the same.
function WriteBody($o, $path) {
    try {
        $json = ConvertTo-Json -InputObject (Wl $o) -Depth 20 -Compress
        [IO.File]::WriteAllText($path, $json, $utf8)
        $back = ReadJsonFile $path
        if ($null -eq $back -or [string]::IsNullOrEmpty([string]$back.name)) { return $false }
        return ((CanonRs $back) -ceq (CanonRs $o))
    } catch { return $false }
}
$script:liveRaw = ''
function ReadLive {
    $script:liveRaw = (gh api "repos/$repo/rulesets/$rid" 2> $null) -join "`n"
    if ($LASTEXITCODE -ne 0) { return $null }
    try { $o = $script:liveRaw | ConvertFrom-Json } catch { return $null }
    if ($null -eq $o -or $null -eq $o.id) { return $null }
    return $o
}
# exact equality on every whitelisted field, and no unknown nested fields
function SameAs($live, $expected, $label) {
    $x = Extras $live
    if ($x) { Write-Host "The ruleset has fields this script does not write: $x"; return $false }
    $a = CanonRs $live
    $b = CanonRs $expected
    if ($a -ceq $b) { return $true }
    Write-Host "The ruleset differs from ${label}:"
    Write-Host "  expected: $b"
    Write-Host "  live:     $a"
    return $false
}
# PUT the whitelisted body of $src, read back, compare: 'ok', 'body', 'put', 'read' or 'differs'
function PutVerify($src) {
    $path = Join-Path ([IO.Path]::GetTempPath()) ('u3-body-' + [Guid]::NewGuid().ToString('N') + '.json')
    try {
        if (-not (WriteBody $src $path)) { Write-Host 'Could not build a ruleset body.'; return 'body' }
        gh api -X PUT "repos/$repo/rulesets/$rid" --input $path --silent
        if ($LASTEXITCODE -ne 0) { return 'put' }
        $after = ReadLive
        if ($null -eq $after) { Write-Host "Could not read ruleset $rid back."; return 'read' }
        if (-not (SameAs $after (ReadJsonFile $path) 'the body just written')) { return 'differs' }
        return 'ok'
    } finally {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }
}
$script:restored = $false
function RestoreFrom($srcPath, $label) {
    $src = ReadJsonFile $srcPath
    if ($null -ne $src) {
        for ($i = 1; $i -le 3; $i++) {
            if ((PutVerify $src) -ceq 'ok') {
                Write-Host ('RESTORED ' + (Utc) + " (ruleset $rid read back equal to $label)")
                $script:restored = $true
                return
            }
            if ($i -lt 3) { Start-Sleep -Seconds 5 }
        }
    }
    Write-Host "RESTORE FAILED: ruleset $rid may still be R1''. Run: .\scripts\u3-toggle.ps1 -Restore (or .\scripts\protect-main.ps1). Send this output to the team."
}

if ($ShowBody) {
    $o = ReadJsonFile $ShowBody
    if ($null -eq $o) { Usage; exit 1 }
    Write-Host (ConvertTo-Json -InputObject (Wl $o) -Depth 20 -Compress)
    exit 0
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host 'GitHub CLI not found. Install it (winget install GitHub.cli), run gh auth login, then run this again.'
    exit 1
}
gh auth status *> $null
if ($LASTEXITCODE -ne 0) { Write-Host "Not signed in: run gh auth login (as $owner). Nothing was changed."; exit 1 }

if ($Restore) {
    $srcPath = if ($From) { $From } else { $r1p }
    if (-not (Test-Path -LiteralPath $srcPath)) { Write-Host "No such file: $srcPath. Nothing was changed."; exit 1 }
    RestoreFrom $srcPath (Split-Path -Leaf $srcPath)
    if ($script:restored) { exit 0 } else { exit 3 }
}
if ($Noop) {
    $live = ReadLive
    if ($null -eq $live) { Write-Host "Could not read ruleset $rid. Nothing was changed."; exit 1 }
    $x = Extras $live
    if ($x) { Write-Host "The ruleset has fields this script does not write ($x). Nothing was changed. Send this output to the team."; exit 1 }
    $r = PutVerify $live
    if ($r -ceq 'ok') { Write-Host ('NOOP OK ' + (Utc) + ": ruleset $rid written with its own body and read back unchanged."); exit 0 }
    if ($r -ceq 'body') { Write-Host 'NOOP REFUSED: could not build the body. Nothing was changed.'; exit 1 }
    if ($r -ceq 'put') { Write-Host ('NOOP REFUSED ' + (Utc) + ": GitHub did not accept the PUT (see gh's message and HTTP status above). Nothing was changed."); exit 1 }
    Write-Host ('NOOP CHANGED ' + (Utc) + ": ruleset $rid did not read back as it was. Run: .\scripts\protect-main.ps1. Send this output to the team.")
    exit 3
}

# ---------------------------------------------------------------------------------------------- 1. preflight
function Refuse($why) { Write-Host "REFUSED: $why. Nothing was changed."; exit 1 }
if ($Pr -notmatch '^[0-9]+$') { Usage; exit 1 }
if ($Merge -and -not $Report) { Write-Host "-Merge needs -Report <review report of PR $Pr>."; Usage; exit 1 }
$now = (Get-Date).ToUniversalTime()
$hm = $now.Hour * 100 + $now.Minute
if ($hm -ge 800 -and $hm -le 1030) {
    Refuse ('it is ' + $now.ToString('HH:mm') + " UTC, inside 08:00-10:30 (the daily run's window); run it later")
}
$runs = @(gh api "repos/$repo/actions/workflows/daily-update.yml/runs?per_page=30" --jq '.workflow_runs[].status')
if ($LASTEXITCODE -ne 0) { Refuse 'could not read the daily-update runs' }
$busy = @($runs | Where-Object { $_ -and $_ -cne 'completed' })
if ($busy.Count -ne 0) { Refuse 'a daily-update run is queued or in progress; run it after that run completes' }
$live = ReadLive
if ($null -eq $live) { Refuse "could not read ruleset $rid" }
$bypass = [string]$live.current_user_can_bypass
if ($bypass -cne 'pull_requests_only' -and $bypass -cne 'always') {
    Refuse "current_user_can_bypass is '$bypass', not pull_requests_only or always"
}
if (-not (SameAs $live (ReadJsonFile $r1p) 'scripts\main-ruleset.json')) { Refuse "ruleset $rid is not R1' (scripts\main-ruleset.json)" }
$f = @()
for ($i = 1; $i -le 4; $i++) {
    $prLine = (gh api "repos/$repo/pulls/$Pr" --jq '[.state, .base.ref, .user.login, .head.repo.full_name, .head.sha, (.draft|tostring), (.mergeable|tostring), (.changed_files|tostring), (.merged|tostring)] | @tsv') -join ''
    if ($LASTEXITCODE -ne 0) { Refuse "could not read pull request #$Pr" }
    $f = @($prLine -split "`t")
    if ($f.Count -lt 9 -or $f[6] -cne 'null') { break }   # 'null': GitHub still computing, read again
    if ($i -lt 4) { Start-Sleep -Seconds 5 }
}
if ($f.Count -lt 9 -or $f[0] -cne 'open' -or $f[1] -cne 'main' -or $f[8] -cne 'false') { Refuse "pull request #$Pr is not open into main ($prLine)" }
if ($f[2] -cne $owner) { Refuse "pull request #$Pr is authored by '$($f[2])', not $owner" }
if ($f[3] -cne $repo) { Refuse "pull request #$Pr's branch is in '$($f[3])', not $repo" }
$head = $f[4]
if ($head -cnotmatch '^[0-9a-f]{40}$') { Refuse "pull request #$Pr's head could not be read" }
if ($f[5] -cne 'false') { Refuse "pull request #$Pr is a draft" }
if ($f[6] -cne 'true') { Refuse "pull request #$Pr is not mergeable ($($f[6]))" }
$files = @(gh api --paginate "repos/$repo/pulls/$Pr/files?per_page=100" --jq '.[] | [.filename, .previous_filename] | @tsv')
if ($LASTEXITCODE -ne 0) { Refuse "could not read pull request #$Pr's files" }
$n = 0
foreach ($line in $files) {
    if (-not $line) { continue }
    $n++
    foreach ($name in @($line -split "`t")) {
        if ($name -and -not $name.StartsWith('docs/', [StringComparison]::Ordinal)) {
            Refuse "pull request #$Pr changes $name, outside docs/ (P must be docs-only)"
        }
    }
}
if ($n -lt 1 -or [string]$n -cne $f[7]) { Refuse "pull request #$Pr lists $n file(s), GitHub counts '$($f[7])'" }
$mainBefore = (gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha') -join ''
if ($LASTEXITCODE -ne 0 -or $mainBefore -cnotmatch '^[0-9a-f]{40}$') { Refuse 'could not read main' }
$docs = [Environment]::GetFolderPath('MyDocuments')
$stamp = $now.ToString('yyyyMMdd-HHmmss')
$liveCopy = Join-Path $docs ('u3-ruleset-live-' + $stamp + '.json')
$backup = Join-Path $docs ('u3-ruleset-backup-' + $stamp + '.json')
$saved = $false
try { [IO.File]::WriteAllText($liveCopy, $script:liveRaw, $utf8); $saved = WriteBody $live $backup } catch { $saved = $false }
if (-not $saved) { Refuse "could not save the ruleset backup in $docs" }
Write-Host "Preflight passed. PR #$Pr head $head, main $mainBefore. Live ruleset saved to $liveCopy."

# ---------------------------------------------------------------------------------------------- 2-4. the window
$script:armed = $false
$script:verdict = ''
$script:detail = ''
$script:why = ''
$script:suiteId = ''
$script:code = 2
$script:prSt = @()
function PrState {   # sets $script:prSt to merged, merged_by, merge commit; $false if unread (no array returned)
    $s = (gh api "repos/$repo/pulls/$Pr" --jq '[(.merged|tostring), .merged_by.login, .merge_commit_sha] | @tsv') -join ''
    if ($LASTEXITCODE -ne 0) { return $false }
    $script:prSt = @($s -split "`t")
    return ($script:prSt.Count -ge 3)
}
function ReadMain {
    $s = (gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha' 2> $null) -join ''
    if ($LASTEXITCODE -ne 0 -or $s -cnotmatch '^[0-9a-f]{40}$') { return '' }
    return $s
}
function RunWindow {
    $script:armed = $true   # from here on, every exit restores (a PUT that failed half-way is restored too)
    if ((PutVerify (ReadJsonFile $r1pp)) -cne 'ok') { $script:why = "R1'' did not read back as written; the window closed at once"; return }
    $opened = Utc
    $env:U3_OPENED = $opened
    Write-Host "U3 WINDOW OPEN $opened backup $backup"
    Write-Host "If this window ever closes without a RESTORED line: gh api -X PUT repos/$repo/rulesets/$rid --input '$backup'"

    # 3. merge
    if ($Merge) {
        $out = (& (Join-Path $PSScriptRoot 'merge-reviewed.ps1') $Pr $head $Report *>&1 | Out-String)
        $mrc = $LASTEXITCODE
        Write-Host $out
        if ($mrc -ne 0) {
            if (-not (PrState)) { $script:why = "merge-reviewed failed and PR #$Pr could not be read"; return }
            if ($script:prSt[0] -cne 'true') {
                $line405 = @($out -split "`n" | Where-Object { $_ -match 'HTTP 405' } | Select-Object -First 1)
                if ($line405.Count -eq 1 -and $out -match '(?i)review|approv') {
                    $script:verdict = 'FAIL-U3'; $script:detail = "merge-reviewed's merge of PR #$Pr was refused: $($line405[0].Trim())"
                } else {
                    $last = @($out.Trim() -split "`n")[-1]
                    $script:why = "merge-reviewed failed without a ruleset refusal: $($last.Trim())"
                }
                return
            }
        }
    } else {
        Write-Host 'Waiting for main to move (checked every 15 s, up to 20 minutes). Now type U3 go in the team thread.'
        $moved = $false; $fails = 0; $refused = ''
        for ($i = 1; $i -le 80; $i++) {
            Start-Sleep -Seconds 15
            $cur = ReadMain
            if (-not $cur) {
                $fails++
                if ($fails -ge 4) { $script:why = 'main could not be read four times running'; return }
                continue
            }
            $fails = 0
            if ($cur -cne $mainBefore) { $moved = $true; break }
            $bodies = @(gh api --paginate "repos/$repo/issues/$Pr/comments?per_page=100" --jq '.[] | select(.user.login == $ENV.U3_OWNER and .created_at >= $ENV.U3_OPENED) | .body' 2> $null)
            if ($LASTEXITCODE -eq 0) {
                $hit = @($bodies | Where-Object { $_ -cmatch '^U3 merge refused' } | Select-Object -First 1)
                if ($hit.Count -eq 1) { $refused = $hit[0]; break }
            }
        }
        if ($refused) {
            if (-not (PrState)) { $script:why = "the team reported a refused merge but PR #$Pr could not be read"; return }
            if ($script:prSt[0] -cne 'false') { $script:why = "the team reported a refused merge but PR #$Pr reads merged=$($script:prSt[0])"; return }
            $script:verdict = 'FAIL-U3'; $script:detail = "the team's merge of PR #$Pr was refused (PR comment: $refused)"; return
        }
        if (-not $moved) { $script:why = 'no merge in the 20-minute window'; return }
    }

    # 4. verdict
    if (-not (PrState)) { $script:why = "PR #$Pr could not be read after the merge"; return }
    $st = $script:prSt
    $cur = ReadMain
    if ($st[0] -cne 'true') { $script:why = "main moved to $cur but PR #$Pr is not merged (another actor)"; return }
    if ($st[1] -cne $owner) { $script:why = "PR #$Pr was merged by '$($st[1])', not $owner"; return }
    $mergeSha = $st[2]
    if ($mergeSha -cnotmatch '^[0-9a-f]{40}$') { $script:why = "PR #$Pr's merge commit could not be read"; return }
    if ($cur -cne $mergeSha) { $script:why = "main is at $cur, not PR #$Pr's merge commit $mergeSha (another actor)"; return }
    $win = ReadLive
    if ($null -eq $win) { $script:why = "ruleset $rid could not be read at the end of the window"; return }
    if (-not (SameAs $win (ReadJsonFile $r1pp) 'scripts\main-ruleset-r1pp.json')) { $script:why = "ruleset $rid did not read R1'' at the end of the window"; return }
    $env:U3_AFTER = $mergeSha
    for ($i = 1; $i -le 8; $i++) {
        $ids = @(gh api "repos/$repo/rulesets/rule-suites?ref=main&time_period=hour&per_page=100" --jq '.[] | select(.after_sha == $ENV.U3_AFTER) | .id' 2> $null)
        if ($LASTEXITCODE -eq 0 -and $ids.Count -ge 1 -and [string]$ids[0] -match '^[0-9]+$') { $script:suiteId = [string]$ids[0]; break }
        if ($i -lt 8) { Start-Sleep -Seconds 15 }
    }
    if (-not $script:suiteId) { $script:why = "PR #$Pr merged by $owner as $mergeSha, but no rule suite lists it"; return }
    $ev = @(gh api "repos/$repo/rulesets/rule-suites/$($script:suiteId)" --jq '.result, (.rule_evaluations[]? | select(.rule_type == $ENV.U3_RULE and .rule_source.id == ($ENV.U3_RID | tonumber)) | .result)')
    if ($LASTEXITCODE -ne 0 -or $ev.Count -lt 1) { $script:why = "rule suite $($script:suiteId) could not be read"; return }
    $suiteResult = $ev[0]
    $prEval = (@($ev | Select-Object -Skip 1)) -join ','
    $shownEval = if ($prEval) { $prEval } else { 'none' }
    $script:detail = "PR #$Pr merged by $owner as $mergeSha; rule suite $($script:suiteId) result=$suiteResult pull_request=$shownEval"
    if (-not $prEval -or $prEval.Contains(',')) {
        $script:why = "$($script:detail) (expected one pull_request evaluation from ruleset $rid)"
    } elseif ($suiteResult -ceq 'bypass' -or $prEval -ceq 'bypass') {
        $script:verdict = 'PASS'
    } elseif ($suiteResult -ceq 'pass' -and $prEval -ceq 'pass') {
        $script:verdict = 'FAIL-RULE'
    } else {
        $script:why = "$($script:detail) (neither bypass nor pass)"
    }
}
function CloseWindow {
    Write-Host "Closing the window: restoring R1' from $backup (do not press Ctrl+C again)."
    RestoreFrom $backup 'the backup'
    if (-not $script:verdict) {
        $script:verdict = 'INCONCLUSIVE'
        $script:detail = if ($script:why) { $script:why } else { 'the run stopped before a verdict (Ctrl+C or an error)' }
    }
    if ($script:verdict -ceq 'PASS' -and -not $script:restored) {
        $script:verdict = 'INCONCLUSIVE'; $script:detail = "the restore was not verified; $($script:detail)"
    }
    $shownSuite = if ($script:suiteId) { $script:suiteId } else { 'none' }
    Write-Host "U3 VERDICT $($script:verdict) rule-suite ${shownSuite}: $($script:detail)"
    if (-not $script:restored) { $script:code = 3 } elseif ($script:verdict -ceq 'PASS') { $script:code = 0 } else { $script:code = 2 }
}
try {
    RunWindow
} finally {
    if ($script:armed) { CloseWindow }
}
exit $script:code
