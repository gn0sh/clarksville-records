# V1'' probe, one time (ADR 0011 decision 7 and Amendment (c) item 6; docs/architecture/v1-fail-2026-11-18.md
# section 4; task V1 in docs/tasks/data-off-main.md; runbook docs/ops/morning-note.md section 4 item 6a). Brian runs
# this one; scripts/v1pp-probe.sh is its tested bash twin (same steps, same verdicts). Brian's PC only: refused in a
# cloud session or CI.
#
# Question: after the cutover (R1'' on main: the ruleset maximum of approvals, squash only, bypass = the admin role in
# pull request mode; R-D; R-T; R2 off), can GITHUB_TOKEN get anything into main, and can a branch or tag other than
# main reach an environment? Signed in as gn0sh (the workflow scope is asked for only after step 0 passed), it:
#   0. refuses unless scripts\protect-main.ps1 -Check -Apps <answer> prints OK (no writes), main and records-data read
#      as commits and no tag named main exists; then, still before any write, reads a finished job's log (the newest
#      finished daily-update job; v1pp-probe/log-read-selfcheck) and stops, changing nothing, if it can't;
#   1. pushes three targets, twice, each one commit on main: W (an inert .github/workflows/v1pp-canary.yml), N
#      (sitegen/v1pp-probe-canary.txt), D0 (data/v1pp-probe-canary.txt, data/ now refused on main too). Set G
#      (probe/v1pp-w, probe/v1pp-n, probe/v1pp-d0): you open their pull requests into main. Set B (probe/v1pp-w-bot,
#      probe/v1pp-n-bot, probe/v1pp-d0-bot): the runner's GITHUB_TOKEN tries to open them, and must be refused;
#   2. tries to create a tag named main (R-T must refuse it: PR #54 finding 2), by the REST API and by git push;
#   3. pushes probe/v1pp-env (.github/workflows/v1pp-env.yml: one job per environment, github-pages and morning-note,
#      each only an echo, and a pages-api job with no environment that calls POST pages/deployments with a made-up
#      artifact), then the tag v1pp-probe at the same commit: GitHub must refuse both runs both environments, and the
#      Pages API on branch or environment grounds (v1pp-probe/pages-api-unreachable: GitHub's own "Unable to find
#      artifact" 400 is NOT-REACHABLE, not counted: the fake artifact is refused before the branch check, by design);
#   4. pushes probe/v1pp-runner (.github/workflows/v1pp-probe.yml): its GITHUB_TOKEN run tries steps 1-3 of section 4
#      (bot pull requests, then per pull request a bot APPROVE, REST squash, merge, rebase, GraphQL squash, then a
#      direct push to main by the REST ref update and by git push); a merge or push that goes through ends the run;
#   5. reads every answer, every probe pull request's merged flag, each probe file on main and on records-data, the
#      tag main and main's sha; then cancels any probe run not completed, cleans up (closes every probe pull request,
#      deletes every probe branch and tag, and the tag main) and reads each one again. A cleanup step is PASS only
#      when its write answered (a close: closed and unmerged; a delete: done, or "Reference does not exist") and the
#      read after it agrees; else INCONCLUSIVE with the command to run.
# Waits are bounded: 3 minutes for a run to start, 12 minutes for it to finish (then it is cancelled, INCONCLUSIVE).
# Run it again after an INCONCLUSIVE: it deletes the probe branches and tag of an earlier try first.
# Every step prints one line: PASS (the expected refusal), FAIL (it went through), NOT-TRIED (skipped because an
# earlier merge or push ended the run), NOT-REACHABLE (only the pages-api step, on GitHub's artifact 400: nothing was
# deployed, and the branch check behind it cannot be reached without a real artifact; not counted) or INCONCLUSIVE (a
# read failed, or a refusal for another reason). Verdict: FAIL
# if any line is FAIL (a probe pull request merged, a probe file on main or records-data, a push to main, a tag main,
# a bot pull request or approval, a job inside an environment): then "Allow GitHub Actions to create and approve pull
# requests" is turned off at once, before cleanup. Else INCONCLUSIVE if any line is not PASS or NOT-REACHABLE. Else PASS.
# Decisions after try 1 (2026-11-21): docs/architecture/main-protect-invariant.md "V1'' try 1 inconclusive".
# Exit 0 PASS, 1 INCONCLUSIVE or refused, 2 FAIL.
# A PASS gates MORNING_NOTE_SEND only (ADR 0011 Amendment (c) item 6). A FAIL that put a commit on main makes the gate
# refuse every later run until a person moves MAIN_PR_BASELINE past that commit.
# Not here (section 4): item 5, an unattested push to records-data, is a gate unit test on a fixture repo; item 7 is the
# first scheduled run after the cutover (D3 step 8).
# Expected refusal wordings (read from GitHub's docs and the U3 control, not yet seen live for every step; any other
# wording is INCONCLUSIVE, never PASS): bot open and approve "not permitted to ... pull requests", squash and GraphQL
# "approving review", or "Repository rule violations found" with "New changes require approval from someone other
# than the last pusher" (require_last_push_approval in R1'', seen live in try 1), merge and rebase "not allowed",
# "approving review" or "rule violation", direct push "rule violation", tag main (and its git push) "rule violation", or a 422 naming no
# rule that GitHub's rule suite for this try records as R-T's creation rule failing (active), environments "not
# allowed to deploy to <env>", the Pages API "not allowed to deploy" or "protection rule".
# Writes the result to Documents\v1pp-probe-results-<time>.txt. Nothing is sent to anyone. Needs git. Takes about 5 minutes.
#
# Run (PowerShell, in the repository folder):  powershell -NoProfile -File scripts\v1pp-probe.ps1 -Apps claude
# (-Apps is the same answer protect-main takes: claude or none.) No double quotes are passed to gh (Windows PowerShell
# 5.1 mangles them), nothing is piped into a native command, and every comparison is case-sensitive unless it says so.
[CmdletBinding(PositionalBinding = $false)]
param([string]$Apps = '')
# BEGIN-REFUSAL-LOCK (v1pp-probe/run-once, v1pp-probe/lock-window): the probe pushes workflows and tries merges, so it
# runs once, by a reviewed PR. To enable that run, the PR changes exactly one line in each twin to the last UTC day it
# may run (a few days after the merge), and the PR that records the result changes it back:
#   scripts/v1pp-probe.sh:   v1pp_unlocked_until=none   ->   v1pp_unlocked_until=YYYY-MM-DD
#   scripts/v1pp-probe.ps1:  $v1ppUnlockedUntil = 'none'   ->   $v1ppUnlockedUntil = 'YYYY-MM-DD'
# Nothing below runs while it is locked, or after that day (an unlock left in place expires by itself).
$v1ppUnlockedUntil = '2026-11-24'
if ($v1ppUnlockedUntil -cnotmatch '^[0-9]{4}-[0-9]{2}-[0-9]{2}$') {
    Write-Host "REFUSED: the V1'' probe is locked (v1pp-probe/run-once). The team enables it for one run by a reviewed PR. Nothing was changed."
    exit 1
}
$today = [DateTime]::UtcNow.ToString('yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
if ([string]::CompareOrdinal($today, $v1ppUnlockedUntil) -gt 0) {
    Write-Host "REFUSED: the V1'' probe's unlock expired after $v1ppUnlockedUntil (UTC) (v1pp-probe/lock-window). Ask the team for a new one. Nothing was changed."
    exit 1
}
# END-REFUSAL-LOCK
$ErrorActionPreference = 'Continue'   # 'Stop' turns gh's stderr into errors in PowerShell 5.1; exit codes are checked
$repo = 'gn0sh/clarksville-records'
$owner = 'gn0sh'
$here = $PSScriptRoot
$utf8 = New-Object Text.UTF8Encoding $false
$usage = 'Usage: powershell -NoProfile -File scripts\v1pp-probe.ps1 -Apps claude|none'
if ($Apps -cne 'claude' -and $Apps -cne 'none') {
    Write-Host "${usage}: -Apps is the same answer protect-main takes (open https://github.com/settings/installations first). Nothing was changed."
    exit 1
}
foreach ($v in @('CLAUDE_CODE_REMOTE', 'GITHUB_ACTIONS', 'CI')) {
    if ([Environment]::GetEnvironmentVariable($v)) {
        Write-Host "REFUSED: $v is set. The V1'' probe runs only from Brian's PC. Nothing was changed."
        exit 1
    }
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host 'GitHub CLI not found. Install it (winget install GitHub.cli), run gh auth login, then run this again.'; exit 1
}
gh auth status *> $null
if ($LASTEXITCODE -ne 0) { Write-Host "Not signed in: run gh auth login (as $owner). Nothing was changed."; exit 1 }
if (-not (Get-Command git -CommandType Application -ErrorAction SilentlyContinue)) {   # v1pp-probe/tag-git-no-git-precheck
    Write-Host 'git not found: install it (winget install Git.Git), then run this again. Nothing was changed.'; exit 1
}

# ---------------------------------------------------------------------------------------------- guard (reads only)
Write-Host "Guard: scripts\protect-main.ps1 -Check -Apps $Apps (no writes) must print OK first."
$pmOut = @(& powershell -NoProfile -File (Join-Path $here 'protect-main.ps1') -Check -Apps $Apps 2>&1 | ForEach-Object { "$_" })
$pmCode = $LASTEXITCODE
$pmOut | ForEach-Object { Write-Host $_ }
$pmLines = @($pmOut | Where-Object { $_ -match '\S' })
if ($pmCode -ne 0 -or $pmLines.Count -eq 0 -or -not $pmLines[-1].StartsWith('OK: main is protected', [StringComparison]::Ordinal)) {
    Write-Host "REFUSED: protect-main --check did not print OK, so main is not as the probe assumes (R1'', R-D, R-T, R2 off). Nothing was changed. Send this output to the team."
    exit 1
}
function ShaOf([string]$ref) {   # a ref (heads/main, tags/main): its sha, 'absent' on a 404, $null on any other answer
    $out = (@(gh api "repos/$repo/git/ref/$ref" --jq '.object.sha' 2>&1 | ForEach-Object { "$_" })) -join "`n"
    if ($LASTEXITCODE -eq 0) {
        if ($out -cmatch '^[0-9a-f]{40}$') { return $out }
        return $null
    }
    if ($out -match 'HTTP 404') { return 'absent' }
    return $null
}
$mainBefore = ShaOf 'heads/main'
$rdBefore = ShaOf 'heads/records-data'
$tagBefore = ShaOf 'tags/main'
if ($mainBefore -cnotmatch '^[0-9a-f]{40}$') { Write-Host 'REFUSED: could not read main. Nothing was changed.'; exit 1 }
if ($rdBefore -cnotmatch '^[0-9a-f]{40}$') { Write-Host 'REFUSED: could not read records-data. Nothing was changed.'; exit 1 }
if ($tagBefore -cne 'absent') {
    $shown = if ($tagBefore) { $tagBefore } else { 'unread' }
    Write-Host "REFUSED: a tag named main exists or could not be read ('$shown'): R-T should make that impossible. Nothing was changed. Send this output to the team."
    exit 1
}

$script:scopeAdded = $false
function GiveBackScope {   # the workflow scope this run added (a browser may open); runs last, after the verdict
    if ($script:scopeAdded) {
        $script:scopeAdded = $false
        Write-Host 'Removing the workflow scope this probe added to your GitHub CLI sign-in (a browser may open).'
        gh auth refresh -h github.com --remove-scopes workflow
        if ($LASTEXITCODE -ne 0) { Write-Host 'Could not remove it: run gh auth refresh -h github.com --remove-scopes workflow' }
    }
}
$script:started = $false
$script:finished = $false
try {   # ends at the bottom: finally cleans up after an early stop, and gives the scope back
$results = Join-Path ([Environment]::GetFolderPath('MyDocuments')) ('v1pp-probe-results-' + (Get-Date -Format 'yyyyMMdd-HHmm') + '.txt')
try { [IO.File]::WriteAllText($results, '', $utf8) } catch { Write-Host "Could not write $results. Nothing was changed."; exit 1 }

# ---------------------------------------------------------------------------------------------- the record
function Log([string]$line) { Write-Host $line; [IO.File]::AppendAllText($results, $line + [Environment]::NewLine, $utf8) }
$script:fails = 0
$script:others = 0
$script:unreach = 0
function Mark([string]$kind, [string]$step, [string]$seen) {   # PASS|FAIL|NOT-TRIED|NOT-REACHABLE|INCONCLUSIVE, the step, what was seen
    Log "$kind ${step}: $seen"
    if ($kind -ceq 'FAIL') { $script:fails++; TurnR2Off }
    elseif ($kind -ceq 'NOT-REACHABLE') { $script:unreach++ }   # PagesRefused only (v1pp-probe/pages-api-unreachable)
    elseif ($kind -cne 'PASS') { $script:others++ }
}
function Quiet { gh api @args --silent *> $null }
function Flat([string]$text) { return ($text -replace '[\r\n]', ' ') }
# read-after-write (docs/architecture/read-after-write-invariant.md): after a write to GitHub, its confirming read may
# lag. ReadUntil runs $read up to 10 times, 3 s apart (never after the last), and returns $true on the first read that
# returns exactly $want (-ceq); $null (a failed read) or any other value is "not yet". Else it says what it read last
# and returns $false. The write is never retried. $read returns one [string] (multi-line output joined with "`n") or
# $null, so $LASTEXITCODE is never trusted across the call; it must not use the names $what, $want, $read or $i (this
# function's). Sets $script:readLast. The same text in every script that uses it (tests pin that).
function ReadUntil([string]$what, [string]$want, [scriptblock]$read) {
    $script:readLast = $null
    for ($i = 1; $i -le 10; $i++) {
        $script:readLast = & $read
        if ($null -ne $script:readLast -and ([string]$script:readLast) -ceq $want) { return $true }
        if ($i -lt 10) { Start-Sleep -Seconds 3 }
    }
    if ($null -eq $script:readLast) { Write-Host "${what}: could not read the state, not '$want', after 10 reads." }
    else { Write-Host "$what reads '$($script:readLast)', not '$want', after 10 reads." }
    return $false
}

# v1pp-probe/tag-main-unnamed-422 (try 1: POST git/refs answered a bare 422 "Reference update failed"). Right after
# the REST try, TagSuite reads GitHub's own record of it, its rule suite (GET rulesets/rule-suites, fields per GitHub's
# OpenAPI description): exactly one suite on refs/tags/main with after_sha = main, actor_name = owner and pushed_at at
# or after $tagT0 (checked to be YYYY-MM-DDTHH:MM:SSZ first: v1pp-probe/tag-main-t0-unchecked), suite result fail, and
# exactly one evaluation from R-T (ruleset id $rtId) of rule_type creation, with result fail and enforcement active.
# It is read before the git push try, whose own suite would otherwise be a second match. Then TagGit tries the same
# tag by git push (GH013 names the rule). How the lines combine (main-protect-invariant.md "V1'' try 1 inconclusive"
# item 2): a bare 422 is PASS on its rule suite; or, only when no suite could be seen or read (tagSoft), when the git
# push line is PASS; a suite that contradicts R-T, or two suites, stays INCONCLUSIVE whatever git says.
$rtId = '27685093'   # R-T "tag main: blocked" (docs/platform-facts.md "Main protection"); a recreated R-T = INCONCLUSIVE
$script:tagT0 = ''
$script:tagProof = ''
$script:tagWhy = ''
$script:tagSoft = $false
$script:tagGitKind = ''
function TagSuite {   # sets tagProof (it proves R-T), else tagWhy (why not) and tagSoft (no suite seen or read)
    $script:tagProof = ''; $script:tagWhy = ''; $script:tagSoft = $false
    if ($script:tagT0 -cnotmatch '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$') {
        $script:tagWhy = "the rule suite was not read: the start time could not be computed ('$($script:tagT0)')"; $script:tagSoft = $true; return
    }
    $env:V1PP_SHA = $mainBefore; $env:V1PP_T0 = $script:tagT0; $env:V1PP_RT = $rtId; $env:V1PP_RULE = 'creation'; $env:V1PP_ACTOR = $owner
    $sid = ''
    for ($k = 1; $k -le 6; $k++) {
        $ids = @(gh api "repos/$repo/rulesets/rule-suites?ref=refs/tags/main&time_period=day&per_page=100" --jq '.[] | select(.after_sha == $ENV.V1PP_SHA and .actor_name == $ENV.V1PP_ACTOR and .pushed_at >= $ENV.V1PP_T0) | .id' 2>$null)
        if ($LASTEXITCODE -ne 0) { $ids = @() }
        $ids = @($ids | Where-Object { [string]$_ -cmatch '^[0-9]+$' })
        if ($ids.Count -eq 1) { $sid = [string]$ids[0]; break }
        if ($ids.Count -gt 1) { $script:tagWhy = "$($ids.Count) rule suites match this try, not one"; return }
        if ($k -lt 6) { Start-Sleep -Seconds 10 }
    }
    if (-not $sid) { $script:tagWhy = 'no rule suite recorded this try'; $script:tagSoft = $true; return }
    # line 1: the suite's result; then result and enforcement of each creation evaluation from R-T
    $evl = @(gh api "repos/$repo/rulesets/rule-suites/$sid" --jq '.result, (.rule_evaluations[]? | select(.rule_source.id == ($ENV.V1PP_RT | tonumber) and .rule_type == $ENV.V1PP_RULE) | .result, .enforcement)' 2>$null)
    if ($LASTEXITCODE -ne 0) { $script:tagWhy = "rule suite $sid could not be read"; $script:tagSoft = $true; return }
    $evl = @($evl | ForEach-Object { [string]$_ })
    $shown = @(0, 1, 2) | ForEach-Object { if ($_ -lt $evl.Count -and $evl[$_]) { $evl[$_] } else { 'none' } }
    $detail = "rule suite ${sid}: result=$($shown[0]), R-T $rtId creation=$($shown[1]) enforcement=$($shown[2])"
    if ($evl.Count -eq 3 -and $evl[0] -ceq 'fail' -and $evl[1] -ceq 'fail' -and $evl[2] -ceq 'active') { $script:tagProof = $detail }
    else { $script:tagWhy = "not shown to be R-T: $detail" }
}
# TagGit: the same tag by git push from a scratch clone (v1pp-probe/tag-git-*). Only git's own answer counts: no
# hooks (--no-verify, core.hooksPath = an empty folder), no global config (GIT_CONFIG_GLOBAL = an empty file: no url
# rewrite, hook path or helper of yours), gh as the only credential helper, no trace, askpass or prompt, and secrets
# redacted; the process environment is put back afterwards. Each git call's exit code is its own ($LASTEXITCODE is set
# to 99 first, so a git that did not run never reads 0). PASS needs a line from GitHub ("remote: error: GH013:
# Repository rule violations found for refs/tags/main") and git's "To https://github.com/<repo>.git" (the push went
# there); exit 0 with that line is FAIL; "Everything up-to-date" after the REST try created the tag is FAIL (it
# exists); anything else is INCONCLUSIVE.
$script:tagRestCreated = $false
function TGit {   # one git call with the clean settings; returns its output lines, the exit code in $script:gitRc
    $global:LASTEXITCODE = 99
    $lines = @(git -c ('core.hooksPath=' + (Join-Path $script:tagDir 'no-hooks')) -c 'credential.helper=' -c 'credential.helper=!gh auth git-credential' @args 2>&1 | ForEach-Object { ([string]$_).TrimEnd("`r") })
    $script:gitRc = $LASTEXITCODE
    return ,$lines
}
function TagGit {
    $script:tagGitKind = 'INCONCLUSIVE'
    $url = "https://github.com/$repo.git"
    $script:tagDir = Join-Path ([IO.Path]::GetTempPath()) ('v1pp-tagpush-' + [Guid]::NewGuid().ToString('N'))
    $names = @(@(Get-ChildItem Env: | Where-Object { $_.Name -like 'GIT_TRACE*' } | ForEach-Object { $_.Name }) +
        @('GIT_TRACE_REDACT', 'GIT_CURL_VERBOSE', 'GIT_ASKPASS', 'SSH_ASKPASS', 'GIT_TERMINAL_PROMPT', 'GIT_CONFIG_GLOBAL') | Where-Object { $_ } | Select-Object -Unique)
    $saved = @{}
    # removed, not emptied: on .NET Core/Unix an empty value stays set (Windows removes it); $null = was not set
    foreach ($n in $names) {
        $saved[$n] = [Environment]::GetEnvironmentVariable($n)
        Remove-Item -LiteralPath ('Env:' + $n) -ErrorAction SilentlyContinue
    }
    try {
        $null = New-Item -ItemType Directory -Path (Join-Path $script:tagDir 'no-hooks') -Force
        [IO.File]::WriteAllText((Join-Path $script:tagDir 'empty.gitconfig'), '')
        $env:GIT_TRACE_REDACT = '1'; $env:GIT_TERMINAL_PROMPT = '0'; $env:GIT_CONFIG_GLOBAL = (Join-Path $script:tagDir 'empty.gitconfig')
        $clone = Join-Path $script:tagDir 'clone'
        $o = TGit init -q $clone
        if ($script:gitRc -eq 0) { $o = TGit -C $clone fetch -q --depth=1 $url $mainBefore }
        if ($script:gitRc -ne 0) { Mark 'INCONCLUSIVE' 'tag main git' "could not fetch main to push from: $(Flat ($o -join ' '))"; return }
        $o = TGit -C $clone push --no-verify $url "${mainBefore}:refs/tags/main"
        $rc = $script:gitRc
        $shown = Flat ($o -join ' ')
        if ($rc -eq 0 -and $script:tagRestCreated -and @($o | Where-Object { $_.Contains('Everything up-to-date') }).Count -gt 0) {
            $script:tagGitKind = 'FAIL'; Mark 'FAIL' 'tag main git' "tag main exists (git answered up-to-date after the REST try created it): $shown"
        } elseif (@($o | Where-Object { $_ -ceq "To $url" }).Count -eq 0) {
            Mark 'INCONCLUSIVE' 'tag main git' "git answered $rc, but not from $url (no 'To $url' line): $shown"
        } elseif ($rc -eq 0) {
            $script:tagGitKind = 'FAIL'; Mark 'FAIL' 'tag main git' "git push created it: $shown"
        } elseif (@($o | Where-Object { $_ -cmatch '^remote: error: GH013: Repository rule violations found for refs/tags/main' }).Count -gt 0) {
            $script:tagGitKind = 'PASS'; Mark 'PASS' 'tag main git' "refused: $shown"
        } else { Mark 'INCONCLUSIVE' 'tag main git' "refused, but no 'remote: error: GH013' line from GitHub: $shown" }
    } catch {
        Mark 'INCONCLUSIVE' 'tag main git' "could not run git: $(Flat ([string]$_))"
    } finally {
        foreach ($n in $saved.Keys) {
            if ($null -eq $saved[$n]) { Remove-Item -LiteralPath ('Env:' + $n) -ErrorAction SilentlyContinue }
            else { Set-Item -LiteralPath ('Env:' + $n) -Value $saved[$n] }
        }
        Remove-Item -LiteralPath $script:tagDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$gBranches = @('probe/v1pp-w', 'probe/v1pp-n', 'probe/v1pp-d0')
$bBranches = @('probe/v1pp-w-bot', 'probe/v1pp-n-bot', 'probe/v1pp-d0-bot')
$runner = 'probe/v1pp-runner'
$envBranch = 'probe/v1pp-env'
$ptag = 'v1pp-probe'
$fileW = '.github/workflows/v1pp-canary.yml'
$fileN = 'sitegen/v1pp-probe-canary.txt'
$fileD = 'data/v1pp-probe-canary.txt'
$filePush = 'sitegen/v1pp-push.txt'
$fileRunner = '.github/workflows/v1pp-probe.yml'
$fileEnv = '.github/workflows/v1pp-env.yml'
$envs = @('github-pages', 'morning-note')
$probeRefs = @()
foreach ($b in ($gBranches + $bBranches + @($runner, $envBranch))) { $probeRefs += "heads/$b" }
$probeRefs += "tags/$ptag"
$cleanRefs = $probeRefs + @('tags/main')   # v1pp-probe/tag-main-cleanup: the guard read tags/main absent, so always
$script:nums = @()          # every probe pull request into main: yours, and any the bot opened
$script:mergedRead = @()    # the pull requests whose merged flag has been read (and marked)
$script:r2Done = $false
# the three probe runs: name, pushed head, run id, looked up (v1pp-probe/inflight-run-at-cleanup)
$script:rNames = @($runner, $envBranch, $ptag)
$script:rHeads = @('', '', '')
$script:rIds = @('', '', '')
$script:rLooked = @($false, $false, $false)

function R2Read {
    $x = @(gh api "repos/$repo/actions/permissions/workflow" --jq '.can_approve_pull_request_reviews' 2>$null)
    if ($LASTEXITCODE -ne 0) { return $null }
    return ($x -join "`n")
}
function TurnR2Off {   # at once on the first FAIL (Mark calls it), so always before cleanup (as V1')
    if ($script:r2Done) { return }
    $script:r2Done = $true
    Log "A FAIL was found: turning off 'Allow GitHub Actions to create and approve pull requests' now (R2 should already be off)."
    gh api -X PUT "repos/$repo/actions/permissions/workflow" -F can_approve_pull_request_reviews=false --silent
    if ($LASTEXITCODE -eq 0 -and (ReadUntil 'R2' 'false' { R2Read })) { Log 'R2 reads off.' }
    else { Log 'Could NOT confirm it is off: Settings > Actions > General > Workflow permissions > untick Allow GitHub Actions to create and approve pull requests > Save. Now.' }
}
function PrState([string]$n) {
    $x = @(gh api "repos/$repo/pulls/$n" --jq '[.state, (.merged|tostring)] | @tsv' 2>$null)
    if ($LASTEXITCODE -ne 0) { return $null }
    return ($x -join "`n")
}
function RefState([string]$r) {
    $s = ShaOf $r
    if ($null -eq $s) { return $null }
    if ($s -ceq 'absent') { return 'absent' }
    return 'present'
}
function CleanupQuiet {   # an early stop: cancel known runs, close, delete; nothing recorded
    foreach ($rid in $script:rIds) { if ($rid) { Quiet -X POST "repos/$repo/actions/runs/$rid/cancel" } }
    foreach ($n in $script:nums) { Quiet -X PATCH "repos/$repo/pulls/$n" -f state=closed }
    foreach ($r in $cleanRefs) { Quiet -X DELETE "repos/$repo/git/refs/$r" }
}
$script:closeRes = @()
$script:delRes = @()
function Cleanup {   # v1pp-probe/cleanup-absence-read: each write's own answer is kept (read-after-write rule 6)
    $script:closeRes = @()
    $script:delRes = @()
    foreach ($n in $script:nums) {   # a merged one stays merged: its answer says so
        $o = @(gh api -X PATCH "repos/$repo/pulls/$n" -f state=closed --jq '[.state, (.merged|tostring)] | @tsv' 2>&1 | ForEach-Object { "$_" })
        if ($LASTEXITCODE -eq 0) { $script:closeRes += ($o -join "`n") }
        else { $script:closeRes += ('failed: ' + (Flat ($o -join ' '))) }
    }
    foreach ($r in $cleanRefs) {
        $o = (@(gh api -X DELETE "repos/$repo/git/refs/$r" 2>&1 | ForEach-Object { "$_" })) -join ' '
        $rc = $LASTEXITCODE
        if ($rc -eq 0 -or $o -cmatch 'Reference does not exist') { $script:delRes += 'done' }
        elseif ($r -ceq 'tags/main' -and $o -match 'rule violation') { $script:delRes += 'done' }   # R-T refusing it
        else { $script:delRes += ('failed: ' + (Flat $o)) }
    }
}
function AddNum($list) {
    foreach ($n in @($list)) {
        if ($n -and -not ($script:nums -contains [string]$n)) { $script:nums += [string]$n }
    }
}
function ListPrs([string]$b) {   # the numbers of every pull request from $b into main, or $null when unread
    $x = @(gh api "repos/$repo/pulls?state=all&base=main&head=${owner}:$b" --jq '.[].number' 2>$null)
    if ($LASTEXITCODE -ne 0) { return $null }
    return , @($x | Where-Object { $_ } | ForEach-Object { [string]$_ })
}
function ReadMerged([string]$n) {   # its merged flag, read and marked once
    if ($script:mergedRead -contains $n) { return }
    $script:mergedRead += $n
    $m = (@(gh api "repos/$repo/pulls/$n" --jq '.merged' 2>$null)) -join ''
    if ($LASTEXITCODE -ne 0) { $m = '' }
    if ($m -ceq 'false') { Mark 'PASS' "pull request #$n" 'unmerged' }
    elseif ($m -ceq 'true') { Mark 'FAIL' "pull request #$n" 'merged into main' }
    else { Mark 'INCONCLUSIVE' "pull request #$n" 'could not read whether it merged' }
}
function RunOnce([string]$name, [string]$head) {   # one read of the push run's id: '' none yet, $null unread
    $env:H = $head
    $id = (@(gh run list --repo $repo --branch $name --event push --json 'databaseId,headSha' `
             --jq '[.[] | select(.headSha == $ENV.H)][0].databaseId // empty' 2>$null)) -join ''
    if ($LASTEXITCODE -ne 0) { return $null }
    if ($id -cmatch '^[0-9]+$') { return $id }
    return ''
}
function RunState([string]$id) {   # the run's status, or $null when unread
    $x = (@(gh run view $id --repo $repo --json status --jq '.status' 2>$null)) -join "`n"
    if ($LASTEXITCODE -ne 0) { return $null }
    return $x
}
function SettleRuns {   # v1pp-probe/inflight-run-at-cleanup: no probe run may still be running when cleanup starts
    for ($k = 0; $k -lt 3; $k++) {
        if (-not $script:rIds[$k] -and $script:rHeads[$k] -and -not $script:rLooked[$k]) {
            $found = RunOnce $script:rNames[$k] $script:rHeads[$k]
            $script:rIds[$k] = [string]$found
            $script:rLooked[$k] = $true
            if (-not $found) {
                Mark 'INCONCLUSIVE' "run $($script:rNames[$k])" "pushed, but no run seen yet: if one starts, cancel it at https://github.com/$repo/actions"
            }
        }
        $rid = $script:rIds[$k]
        if (-not $rid) { continue }
        $s = RunState $rid
        if ($s -ceq 'completed') { continue }
        $shown = if ($s) { $s } else { 'unread' }
        Log "Run $rid ($($script:rNames[$k])) reads '$shown': cancelling it before cleanup."
        $o = (@(gh api -X POST "repos/$repo/actions/runs/$rid/cancel" 2>&1 | ForEach-Object { "$_" })) -join ' '
        if ($LASTEXITCODE -ne 0) { Log "  The cancel answered: $(Flat $o)" }
        if (-not (ReadUntil "Run $rid" 'completed' { RunState $rid })) {
            $shown = if ($null -ne $script:readLast) { $script:readLast } else { 'unread' }
            Mark 'INCONCLUSIVE' "run $rid" "still '$shown' after the cancel: cancel it at https://github.com/$repo/actions/runs/$rid"
        }
    }
}
function Finish {   # cancel, cleanup, the reads after it, the verdict; never returns
    $script:started = $false
    $script:finished = $true
    foreach ($b in ($gBranches + $bBranches)) {   # pull requests whose number this run did not learn
        $x = ListPrs $b
        if ($null -eq $x) { Mark 'INCONCLUSIVE' "cleanup $b" 'could not list its pull requests' } else { AddNum $x }
    }
    SettleRuns   # first: a late run's merge is then seen by the reads below, and R2 goes off before cleanup
    foreach ($n in $script:nums) { ReadMerged $n }   # before cleanup closes them (v1pp-probe/r2-after-cleanup)
    Log "Cleanup: closing $($script:nums.Count) probe pull request(s), deleting $($cleanRefs.Count) ref(s)."
    Cleanup
    for ($k = 0; $k -lt $script:nums.Count; $k++) {
        $n = $script:nums[$k]
        $c = [string]$script:closeRes[$k]
        $ok = ReadUntil "Pull request #$n" "closed`tfalse" { PrState $n }
        $last = if ($null -ne $script:readLast) { [string]$script:readLast } else { '' }
        if (($c -split "`t", 2)[1] -ceq 'true' -or ($last -split "`t", 2)[1] -ceq 'true') {
            Mark 'FAIL' "after cleanup #$n" 'merged into main'
        } elseif ($c -ceq "closed`tfalse" -and $ok) {
            Mark 'PASS' "after cleanup #$n" 'closed, unmerged'
        } else {
            $shown = if ($last) { $last } else { 'unread' }
            Mark 'INCONCLUSIVE' "after cleanup #$n" "the close answered '$c', it reads '$shown': close it with gh pr close $n --repo $repo"
        }
    }
    for ($k = 0; $k -lt $cleanRefs.Count; $k++) {
        $r = $cleanRefs[$k]
        $d = [string]$script:delRes[$k]
        $ok = ReadUntil $r 'absent' { RefState $r }
        if ($d -ceq 'done' -and $ok) { Mark 'PASS' "after cleanup $r" 'deleted' }
        elseif ($r -ceq 'tags/main') {
            $shown = if ($null -ne $script:readLast) { $script:readLast } else { 'unread' }
            Mark 'INCONCLUSIVE' "after cleanup $r" "the delete answered '$d', it reads '$shown': R-T refuses a plain DELETE, so a person removes it by editing the R-T ruleset (tag main: blocked) to allow deletion, deleting the tag, then running protect-main again"
        } else {
            $shown = if ($null -ne $script:readLast) { $script:readLast } else { 'unread' }
            Mark 'INCONCLUSIVE' "after cleanup $r" "the delete answered '$d', it reads '$shown': delete it with gh api -X DELETE repos/$repo/git/refs/$r"
        }
    }
    if ($script:fails -ne 0) {
        Log "FAIL (V1''): $($script:fails) step(s) above went through. 'Allow GitHub Actions to create and approve pull requests' is off (see above)."
        Log "If a probe commit is on main, the gate now refuses every daily run until a person moves MAIN_PR_BASELINE past it (ADR 0011 Amendment (c) item 6); the team removes the probe file by a person's pull request (scripts\merge-reviewed.ps1)."
        Log "Leave MORNING_NOTE_SEND unset, and do not run anything else. Send this output to the team. Saved to $results"
        GiveBackScope; exit 2
    }
    if ($script:others -ne 0) {
        Log "INCONCLUSIVE (V1''): $($script:others) step(s) above are not PASS (a read failed, a refusal for another reason, or a step not tried); nothing was seen to go through. MORNING_NOTE_SEND stays unset. Send this output to the team. Saved to $results"
        GiveBackScope; exit 1
    }
    Log "PASS (V1''): every step above was refused as expected: no pull request or push from GITHUB_TOKEN reached main, the bot could not open or approve a pull request, no tag main, no environment job and no Pages deployment for a branch or tag other than main, main unchanged, no probe file on main or records-data, and every probe pull request, branch and tag is gone. $($script:unreach) pages-api line(s) NOT-REACHABLE by design: the Pages API's own branch check is not covered (U-pages in the invariant note). Send this output to the team. Saved to $results"
    GiveBackScope; exit 0
}

function CleanLog($text) {   # untrusted text: ANSI colour codes, then control characters, are dropped; one string per line
    # the control characters include the C1 controls U+0080-U+009F and the bidi controls U+202A-U+202E, U+2066-U+2069
    # (v1pp-probe/log-read-diag-controls)
    return @($text | ForEach-Object { ([string]$_ -replace '\x1b\[[0-9;?]*[ -/]*[@-~]', '') -replace '[\x00-\x08\x0B-\x1F\x7F\u0080-\u009F\u202A-\u202E\u2066-\u2069]', '' })
}
function RunJobs([string]$id) {   # one line per job, name TAB id TAB status TAB conclusion, joined with `n; $null when unread
    $x = @(gh api "repos/$repo/actions/runs/$id/jobs" --jq '.jobs[] | [.name, (.id|tostring), .status, (.conclusion|tostring)] | @tsv' 2>$null)
    if ($LASTEXITCODE -ne 0) { return $null }
    return ($x -join "`n")
}
# v1pp-probe/job-log-unreadable (docs/architecture/v1pp-job-log-invariant.md, I-log): a job-log read succeeded only
# when gh exits 0 and its output holds a GitHub log line ($logLine, unanchored: a BOM may sit before line 1); a failed
# read leaves one sanitized line, never its output (v1pp-probe/log-read-diag). GH_DEBUG (or the legacy DEBUG) would
# put a debug line first (v1pp-probe/gh-debug-legacy).
Remove-Item Env:GH_DEBUG -ErrorAction SilentlyContinue
Remove-Item Env:DEBUG -ErrorAction SilentlyContinue
$logLine = '[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z '
function ReadWhy([string]$rc, $err, [int]$outCount) {   # "gh exit <rc>: <first stderr line, sanitized>"
    $first = @(CleanLog $err | Where-Object { $_ -match '\S' }) | Select-Object -First 1
    if (-not $first) { return "gh exit ${rc}: no error text, $outCount line(s) out" }
    # URLs, also JSON-escaped (https:\/\/), cut to scheme and host, any userinfo dropped (-replace: any case; the signed
    # read token is in the path and query; a closing ")" is kept); then a host/path with no scheme cut to the host;
    # then any query left cut (v1pp-probe/log-read-diag-query, -userinfo); then long tokens redacted
    $s = [string]$first -replace '(https?:(\\?/){2})([^/\s"''?#@\\]*@)?([^/\s"''?#@\\)]+)[^\s"'')]*', '$1$4/...'
    $s = $s -replace '([^/\s"''?#@\\]+@)?(([A-Za-z0-9-]+\.)+[A-Za-z]{2,}(:[0-9]+)?)\\?/[^\s"'')]*', '$2/...'
    $s = ($s -replace '\?[^\s"'']+', '?...') -creplace '[A-Za-z0-9%+/=_-]{32,}', '<redacted>'
    if ($s.Length -gt 200) { $s = $s.Substring(0, 200) }
    return "gh exit ${rc}: $s"
}
# v1pp-probe/run-log-missing (try 1: gh run view --log gave nothing for a finished run whose job log held the line):
# each job's own log (GET actions/jobs/<id>/logs), read up to 6 times, 10 s apart (never after the last), until a read
# succeeds and holds $want (a regex, case-sensitive); returns the last log read, cleaned, joined with `n; $null if no
# read succeeded, and then $script:jobLogWhy holds the last failed read's ReadWhy line. 2>&1 keeps gh's stderr: in 5.1
# and 7 each stderr line arrives as an ErrorRecord, so the type splits it from the log text; $LASTEXITCODE is read
# at once, in this function.
$script:jobLogWhy = ''
function JobLog([string]$jid, [string]$want) {
    $text = $null
    $script:jobLogWhy = ''
    for ($k = 1; $k -le 6; $k++) {
        $all = @(gh api "repos/$repo/actions/jobs/$jid/logs" @logFlag 2>&1)
        $rc = $LASTEXITCODE
        $got = @($all | Where-Object { $_ -isnot [Management.Automation.ErrorRecord] })
        $err = @($all | Where-Object { $_ -is [Management.Automation.ErrorRecord] })
        $t = (CleanLog $got) -join "`n"
        if ($rc -eq 0 -and $t -cmatch $logLine) {
            $text = $t
            $script:jobLogWhy = ''
            if ($text -cmatch $want) { break }
        } else {
            $n = @($got | Where-Object { [string]$_ -match '\S' }).Count
            $script:jobLogWhy = ReadWhy $rc $err $n
        }
        if ($k -lt 6) { Start-Sleep -Seconds 10 }
    }
    return $text
}

Log ("V1'' probe " + (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') + ". main before: $mainBefore. records-data before: $rdBefore.")
$ghVer = [string](@(CleanLog ([string](@(gh --version 2>$null) | Select-Object -First 1))) | Select-Object -First 1)
if ($ghVer.Length -gt 200) { $ghVer = $ghVer.Substring(0, 200) }
if (-not $ghVer) { $ghVer = 'unread' }
Log "gh: $ghVer. PowerShell $($PSVersionTable.PSVersion)."
# v1pp-probe/log-read-escape-flag (I-log 6): gh 2.104 refuses to print a body holding terminal escape sequences (a job
# log's ANSI colours) unless --allow-escape-sequences is passed; older gh (2.89) has no such flag and rejects it. So
# ask this gh's own help, once and locally (no network), and pass the flag on the job-log reads only. Safe: CleanLog
# strips ANSI and control characters from the log text before any use, and no log text is ever printed raw.
$logFlag = @()
$ghShort = 'gh'
if ($ghVer -cmatch '^gh version ([0-9][0-9.]*[0-9])') { $ghShort = "gh $($Matches[1])" }
$ghHelp = (@(gh api --help 2>$null | ForEach-Object { "$_" })) -join "`n"
if ($ghHelp.Contains('--allow-escape-sequences')) {
    $logFlag = @('--allow-escape-sequences')
    Log "${ghShort}: log reads pass --allow-escape-sequences (log text is cleaned before any use)."
} else {
    Log "${ghShort}: log reads do not pass --allow-escape-sequences (this gh does not know it)."
}
$ghHelp = ''
# v1pp-probe/log-read-selfcheck (I-log 3): every answer is read from job logs, so before the first write (the leftover
# deletes below are writes) show that this machine can read one: the newest finished daily-update job's, through
# JobLog. Reads only; its text is never shown. Refused here, nothing was changed ($script:started is still false, and
# the workflow scope is not asked for yet). The newest 5 completed runs, newest first: the first with a completed
# success or failure job is used (the newest may have been cancelled).
$scRuns = @(gh api "repos/$repo/actions/workflows/daily-update.yml/runs?status=completed&per_page=5" --jq '.workflow_runs[].id' 2>$null)
if ($LASTEXITCODE -ne 0) { $scRuns = @() }
$scRun = ''
$scJid = ''
foreach ($r in $scRuns) {
    if ([string]$r -cnotmatch '^[0-9]+$') { continue }
    $scJobs = RunJobs ([string]$r)
    if ($null -eq $scJobs) { continue }
    $scRow = @($scJobs -split "`n" | Where-Object { [string]$_ -cmatch "^[^`t]*`t[0-9]+`tcompleted`t(success|failure)$" }) | Select-Object -First 1
    if ($scRow) { $scJid = ([string]$scRow -split "`t")[1]; $scRun = [string]$r; break }
}
if (-not $scJid) {
    Log 'REFUSED: could not find a finished daily-update job to test the log read. Nothing was changed.'
    exit 1
}
$scText = JobLog $scJid $logLine
if ($null -eq $scText) {
    Log "REFUSED: could not read the log of finished job $scJid (daily-update run $scRun) after 6 reads (last: $($script:jobLogWhy)); every answer is read from job logs, so the probe stops here (v1pp-probe/job-log-unreadable). Nothing was changed. Send this file to the team."
    exit 1
}
Log "Log read check: job $scJid of daily-update run $scRun read ($(@($scText -split "`n" | Where-Object { $_ -ne '' }).Count) lines)."
$scText = ''
# v1pp-probe/selfcheck-before-scope: the workflow scope is asked for only now, after the read-only checks passed
$authText = (@(gh auth status 2>&1 | ForEach-Object { "$_" })) -join "`n"
if ($authText -notmatch 'workflow') {
    Write-Host "Your GitHub CLI sign-in needs the workflow scope to push the probe's workflow files: a browser opens."
    gh auth refresh -h github.com -s workflow
    if ($LASTEXITCODE -ne 0) { Log 'Could not add the workflow scope (see above). Nothing was changed.'; exit 1 }
    $script:scopeAdded = $true
}
foreach ($r in $probeRefs) { Quiet -X DELETE "repos/$repo/git/refs/$r" }   # leftovers of an earlier try
$script:started = $true

# ---------------------------------------------------------------------------------------------- setup (writes)
function SetupFailed([string]$why) { Mark 'INCONCLUSIVE' 'setup' "$why (see the messages above)"; Finish }
function FileB64([string]$name) {
    try { return [Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path (Join-Path $here 'v1pp-probe') $name))) }
    catch { return $null }
}
function B64([string]$text) { return [Convert]::ToBase64String($utf8.GetBytes($text)) }
$script:pushed = ''
function PushFile([string]$branch, [string]$path, [string]$content, [string]$message) {   # the branch at main plus one commit
    $script:pushed = ''
    gh api -X POST "repos/$repo/git/refs" -f ref=refs/heads/$branch -f sha=$mainBefore --silent
    if ($LASTEXITCODE -ne 0) { return $false }
    $c = (@(gh api -X PUT "repos/$repo/contents/$path" -f "message=$message" -f content=$content -f branch=$branch --jq '.commit.sha')) -join ''
    if ($LASTEXITCODE -ne 0 -or $c -cnotmatch '^[0-9a-f]{40}$') { return $false }
    $script:pushed = $c
    return $true
}
$script:prNum = ''
function OpenPr([string]$branch, [string]$name, [string]$head) {   # its pull request into main (read-after-write rule 6)
    $script:prNum = ''
    for ($k = 1; $k -le 10; $k++) {
        $res = @(gh api -X POST "repos/$repo/pulls" -f head=$branch -f base=main -f "title=V1pp probe $name (do not merge)" `
            -f "body=One-time V1'' probe (ADR 0011; runbook section 4 item 6a). Closed by the probe script; never merge it." `
            --jq '[(.number|tostring), (.head.sha|tostring)] | @tsv' 2>&1 | ForEach-Object { "$_" })
        if ($LASTEXITCODE -eq 0) {
            $parts = ((@($res | Where-Object { $_ -match '\S' }) | Select-Object -First 1) + '') -split "`t"
            if ($parts[0] -cnotmatch '^[0-9]+$') { return $false }
            AddNum $parts[0]
            if ($parts.Count -lt 2 -or $parts[1] -cne $head) { Write-Host "Pull request #$($parts[0]) has head '$($parts[1])', not the pushed $head."; return $false }
            $script:prNum = $parts[0]
            return $true
        }
        $res | ForEach-Object { Write-Host $_ }
        # anything but a 422 is ambiguous: a pull request may exist (cleanup lists them)
        if (@($res | Where-Object { $_ -match '[(]HTTP 422[)]' }).Count -eq 0) { return $false }
        if ($k -lt 10) { Start-Sleep -Seconds 3 }
    }
    return $false
}
$canary = FileB64 'v1pp-canary.yml'
if (-not $canary) { SetupFailed 'could not read scripts\v1pp-probe\v1pp-canary.yml' }
$envWf = FileB64 'v1pp-env.yml'
if (-not $envWf) { SetupFailed 'could not read scripts\v1pp-probe\v1pp-env.yml' }
$runWf = FileB64 'v1pp-probe.yml'
if (-not $runWf) { SetupFailed 'could not read scripts\v1pp-probe\v1pp-probe.yml' }
$textN = B64 "V1pp probe: inert, never merge.`n"
$textD = B64 "V1pp probe: a data/ file, never on main.`n"
$targetFiles = @($fileW, $fileN, $fileD)
$targetTexts = @($canary, $textN, $textD)
$heads = @()
$all = $gBranches + $bBranches
for ($k = 0; $k -lt $all.Count; $k++) {
    $f = $targetFiles[$k % 3]
    if (-not (PushFile $all[$k] $f $targetTexts[$k % 3] "V1pp probe: $f")) { SetupFailed "could not push $($all[$k])" }
    $heads += $script:pushed
}
$gNames = @('W', 'N', 'D0')
$gNums = @()
for ($k = 0; $k -lt 3; $k++) {
    if (-not (OpenPr $gBranches[$k] $gNames[$k] $heads[$k])) { SetupFailed "could not open the pull request for $($gBranches[$k])" }
    $gNums += $script:prNum
}
Log "Probe pull requests (yours): W #$($gNums[0]), N #$($gNums[1]), D0 #$($gNums[2]). Bot branches: $($bBranches -join ' ')."
# F2 (R-T): a tag named main must not be creatable, by anyone: by the REST API, then by git push
$script:tagT0 = [DateTime]::UtcNow.AddSeconds(-60).ToString('yyyy-MM-ddTHH:mm:ssZ', [Globalization.CultureInfo]::InvariantCulture)   # rule suites of this try are pushed at or after it (skew margin)
$tagBare = ''
$out = Flat ((@(gh api -X POST "repos/$repo/git/refs" -f ref=refs/tags/main -f sha=$mainBefore --jq '.ref' 2>&1 | ForEach-Object { "$_" })) -join ' ')
if ($LASTEXITCODE -eq 0) {
    $script:tagRestCreated = $true; Mark 'FAIL' 'tag main' "GitHub created it: $out"
} elseif ($out -match 'rule violation') {
    Mark 'PASS' 'tag main' "refused ($out)"
} elseif ($out -cmatch 'HTTP 422') {
    $tagBare = $out; TagSuite   # its rule suite, read now: before the git push adds a second one
} else {
    Mark 'INCONCLUSIVE' 'tag main' "failed without naming a rule: $out"
}
TagGit
if ($tagBare) {
    if ($script:tagProof) { Mark 'PASS' 'tag main' "refused ($tagBare); $($script:tagProof)" }
    elseif ($script:tagSoft -and $script:tagGitKind -ceq 'PASS') {
        Mark 'PASS' 'tag main' "refused ($tagBare), naming no rule, and $($script:tagWhy); R-T, which has no bypass actor, is shown refusing the same tag on the git line above, and 'tag main after' reads that it is absent"
    } elseif ($script:tagWhy -ceq 'no rule suite recorded this try') {
        Mark 'INCONCLUSIVE' 'tag main' "failed without naming a rule, and no rule suite recorded this try, and the git line is not PASS: $tagBare (see https://github.com/$repo/rules/insights)"
    } else { Mark 'INCONCLUSIVE' 'tag main' "refused ($tagBare), but $($script:tagWhy)" }
}
if (-not (PushFile $envBranch $fileEnv $envWf 'V1pp probe: environment refusal')) { SetupFailed "could not push $envBranch" }
$envHead = $script:pushed
$script:rHeads[1] = $envHead
gh api -X POST "repos/$repo/git/refs" -f ref=refs/tags/$ptag -f sha=$envHead --silent
if ($LASTEXITCODE -ne 0) { SetupFailed "could not create the tag $ptag" }
$script:rHeads[2] = $envHead
if (-not (PushFile $runner $fileRunner $runWf 'V1pp probe: runner workflow')) { SetupFailed "could not push $runner" }
$runHead = $script:pushed
$script:rHeads[0] = $runHead

# ---------------------------------------------------------------------------------------------- the runs (reads)
function RunOf([string]$name, [string]$head) {   # the push run's id, or '' after 3 minutes
    for ($k = 1; $k -le 18; $k++) {
        $id = RunOnce $name $head
        if ($id) { return $id }
        if ($k -lt 18) { Start-Sleep -Seconds 10 }
    }
    return ''
}
function WaitRun([string]$id) {   # v1pp-probe/unbounded-watch: up to 12 minutes (72 reads, 10 s apart); the last status
    $s = $null
    for ($k = 1; $k -le 72; $k++) {
        $s = RunState $id
        if ($s -ceq 'completed') { break }
        if ($k -lt 72) { Start-Sleep -Seconds 10 }
    }
    return $s
}
$runId = RunOf $runner $runHead
$script:rIds[0] = [string]$runId
$script:rLooked[0] = $true
$script:lines = @()
$script:logUnread = $false   # v1pp-probe/unread-not-absent (I-log 2): a runner job's log not read, so no line may read as absent
if (-not $runId) {
    Mark 'INCONCLUSIVE' 'runner' 'the probe run did not start within 3 minutes'
} else {
    Log "Probe run: https://github.com/$repo/actions/runs/$runId"
    $st = WaitRun $runId
    if ($st -ceq 'completed') { Mark 'PASS' 'runner' 'the run completed' }
    else {
        $shown = if ($st) { $st } else { 'unread' }
        Mark 'INCONCLUSIVE' 'runner' "the run reads '$shown', not completed after 12 minutes, so its answers are not final (it is cancelled before cleanup)"
    }
    $logText = @()
    $jobs = RunJobs $runId
    $jids = @()
    if ($null -ne $jobs) { $jids = @($jobs -split "`n" | ForEach-Object { ([string]$_ -split "`t")[1] } | Where-Object { [string]$_ -cmatch '^[0-9]+$' }) }
    if ($jids.Count -eq 0) { $script:logUnread = $true; Mark 'INCONCLUSIVE' 'runner log' "could not read the run's jobs" }
    foreach ($jid in $jids) {
        $t = JobLog $jid 'V1PP-(RESULT|MERGED|NOPR) (W|N|D0|WB|NB|D0B|PUSH) '
        if ($null -eq $t) { $script:logUnread = $true; Mark 'INCONCLUSIVE' 'runner log' "could not read job $jid's log after 6 reads (last: $($script:jobLogWhy))" }
        else { $logText += @($t -split "`n") }
    }
    $script:lines = @($logText | ForEach-Object {
        if ($_ -cmatch 'V1PP-(RESULT|MERGED|NOPR) (W|N|D0|WB|NB|D0B|PUSH)( .*)?$') { $Matches[0] } })
    foreach ($l in $script:lines) { Log "  $l" }
    $errs = @($logText | Where-Object { $_ -notmatch 'echo "V1PP-ERROR' } | ForEach-Object {
        if ($_ -cmatch 'V1PP-ERROR: .*') { $Matches[0] } })
    foreach ($l in $errs) { Log "  $l" }
}
$script:ended = @($script:lines | Where-Object { $_ -cmatch '^V1PP-MERGED ' }).Count -gt 0
function Judge([string]$t, [string]$s, [string]$want) {   # what the refusal must name: a regex, any case ('' = any refusal)
    $l = @($script:lines | Where-Object { $_ -cmatch "^V1PP-RESULT $t $s exit=[0-9]+( |$)" }) | Select-Object -First 1
    if (-not $l) {
        if ($script:ended) { Mark 'NOT-TRIED' "$t $s" 'skipped: an earlier merge or push ended the run' }
        elseif ($script:logUnread) { Mark 'INCONCLUSIVE' "$t $s" "not judged: the run's log was not read (see the runner log line)" }
        else { Mark 'INCONCLUSIVE' "$t $s" "no answer in the run's log" }
        return
    }
    $rest = $l.Substring($l.IndexOf('exit=') + 5)
    $code = ($rest -split ' ', 2)[0]
    if ($code -ceq '0') { Mark 'FAIL' "$t $s" "GitHub accepted it: $rest" }
    elseif (-not $want -or $rest -match $want) { Mark 'PASS' "$t $s" "refused: $rest" }
    else { Mark 'INCONCLUSIVE' "$t $s" "refused, but not naming '$want': $rest" }
}
# v1pp-probe/squash-last-pusher: the pull_request rule of R1'' may name its require_last_push_approval condition, not
# the approval count; both are that one rule, so both count, the last-pusher one only with the ruleset header
$prRule = 'approving review|Repository rule violations found.*New changes require approval from someone other than the last pusher'
function JudgePr([string]$t) {   # the bot approval and every merge try on its pull request
    Judge $t 'approve' 'not permitted to (create or )?approve pull requests'
    Judge $t 'squash' $prRule
    Judge $t 'merge' 'not allowed|approving review|rule violation'    # v1pp-probe/unobserved-refusal-pass
    Judge $t 'rebase' 'not allowed|approving review|rule violation'
    Judge $t 'graphql' $prRule
}
$bNames = @('WB', 'NB', 'D0B')
for ($k = 0; $k -lt 3; $k++) {
    $t = $bNames[$k]
    Judge $t 'open' 'not permitted to create'
    if (@($script:lines | Where-Object { $_ -cmatch "^V1PP-RESULT $t open exit=0( |$)" }).Count -gt 0) { JudgePr $t }
    $x = ListPrs $bBranches[$k]
    if ($null -eq $x) { Mark 'INCONCLUSIVE' "$t pull request" "could not list the pull requests from $($bBranches[$k])" }
    elseif ($x.Count -gt 0) { AddNum $x; Mark 'FAIL' "$t pull request" "a pull request from $($bBranches[$k]) exists: #$($x -join ',')" }
    else { Mark 'PASS' "$t pull request" "none from $($bBranches[$k])" }
}
foreach ($t in $gNames) { JudgePr $t }
Judge 'PUSH' 'rest' 'rule violation'
Judge 'PUSH' 'git' 'rule violation'

function EnvRefused([string]$label, [string]$id) {   # each environment's job refused before it started
    if (-not $id) {
        foreach ($e in $envs) { Mark 'INCONCLUSIVE' "$label $e" 'the run did not start within 3 minutes' }
        return
    }
    Log "Environment run (${label}): https://github.com/$repo/actions/runs/$id"
    $null = WaitRun $id
    $jobsText = RunJobs $id
    $jobs = if ($null -ne $jobsText) { @($jobsText -split "`n") } else { @() }
    foreach ($e in $envs) {
        $row = @($jobs | Where-Object { ([string]$_ -split "`t")[0] -ceq $e }) | Select-Object -First 1
        if (-not $row) { Mark 'INCONCLUSIVE' "$label $e" 'could not read the job'; continue }
        $f = ([string]$row) -split "`t"
        $jid = $f[1]; $st = $f[2]; $concl = $f[3]
        if ($concl -ceq 'success') { Mark 'FAIL' "$label $e" "the job ran inside environment $e"; continue }
        if ($st -cne 'completed' -or $concl -cne 'failure') { Mark 'INCONCLUSIVE' "$label $e" "the job reads '$st' '$concl', not refused"; continue }
        $ann = $null
        if ($jid -cmatch '^[0-9]+$') {
            $got = @(gh api "repos/$repo/check-runs/$jid/annotations" --jq '.[].message' 2>$null)
            if ($LASTEXITCODE -eq 0) { $ann = $got }
        }
        if ($null -eq $ann) { Mark 'INCONCLUSIVE' "$label $e" "could not read the job's annotations"; continue }
        $hit = @($ann | Where-Object { ([string]$_).IndexOf("not allowed to deploy to $e", [StringComparison]::OrdinalIgnoreCase) -ge 0 }) | Select-Object -First 1
        if ($hit) { Mark 'PASS' "$label $e" "refused: $hit" }
        else { Mark 'INCONCLUSIVE' "$label $e" "the job failed without the environment refusal: $(Flat ($ann -join ' '))" }
    }
}
function PagesRefused([string]$label, [string]$id) {   # v1pp-probe/pages-api-coverage: the pages-api job's answer
    if (-not $id) { Mark 'INCONCLUSIVE' "$label pages-api" 'the run did not start within 3 minutes'; return }
    $jobsText = RunJobs $id
    $jid = ''
    if ($null -ne $jobsText) {
        $row = @($jobsText -split "`n" | Where-Object { ([string]$_ -split "`t")[0] -ceq 'pages-api' }) | Select-Object -First 1
        if ($row) { $jid = ([string]$row -split "`t")[1] }
    }
    if ($jid -cnotmatch '^[0-9]+$') { Mark 'INCONCLUSIVE' "$label pages-api" 'could not read the job'; return }
    $t = JobLog $jid 'V1PP-RESULT PAGES api exit=[0-9]'
    if ($null -eq $t) { Mark 'INCONCLUSIVE' "$label pages-api" "could not read the job's log (job $jid) after 6 reads (last: $($script:jobLogWhy))"; return }
    $l = @($t -split "`n" | ForEach-Object { if ($_ -cmatch 'V1PP-RESULT PAGES api exit=[0-9]+( .*)?$') { $Matches[0] } }) | Select-Object -First 1
    if (-not $l) { Mark 'INCONCLUSIVE' "$label pages-api" "no answer in the job's log"; return }
    $rest = $l.Substring($l.IndexOf('exit=') + 5)
    $code = ($rest -split ' ', 2)[0]
    if ($code -ceq '0') { Mark 'FAIL' "$label pages-api" "GitHub accepted a Pages deployment: $rest" }
    elseif ($rest -match 'not allowed to deploy|protection rule') { Mark 'PASS' "$label pages-api" "refused: $rest" }
    elseif ($rest.Contains('Unable to find artifact') -and $rest -cmatch '\(HTTP 400\)|"status":"400"') {
        # v1pp-probe/pages-api-unreachable: GitHub's own answer to the made-up artifact (try 1); the fake artifact stays,
        # since a real one could replace the live site, so the branch check behind it is never reached: not counted
        Mark 'NOT-REACHABLE' "$label pages-api" "by design, not counted: the made-up artifact was refused (HTTP 400) before any branch check, so nothing was deployed and the Pages API's own branch check is not covered: $rest"
    }
    elseif ($rest -match 'artifact') { Mark 'INCONCLUSIVE' "$label pages-api" "artifact refused first; branch check not reached: $rest" }
    else { Mark 'INCONCLUSIVE' "$label pages-api" "refused, but not on branch or environment grounds: $rest" }
}
$envRun = RunOf $envBranch $envHead
$script:rIds[1] = [string]$envRun
$script:rLooked[1] = $true
EnvRefused "branch $envBranch" $envRun
PagesRefused "branch $envBranch" $envRun
$tagRun = RunOf $ptag $envHead
$script:rIds[2] = [string]$tagRun
$script:rLooked[2] = $true
EnvRefused "tag $ptag" $tagRun
PagesRefused "tag $ptag" $tagRun

# every probe pull request's merged flag (yours and any the bot opened)
foreach ($b in $gBranches) { $x = ListPrs $b; if ($null -ne $x) { AddNum $x } }
foreach ($n in $script:nums) { ReadMerged $n }
foreach ($f in @($fileW, $fileN, $fileD, $filePush, $fileRunner, $fileEnv)) {
    foreach ($ref in @('main', 'records-data')) {
        $out = (@(gh api "repos/$repo/contents/$($f)?ref=$ref" --jq '.sha' 2>&1 | ForEach-Object { "$_" })) -join "`n"
        $rc = $LASTEXITCODE
        if ($rc -eq 0) {
            if ($out -cmatch '^[0-9a-f]{40}$') { Mark 'FAIL' "$f on $ref" 'it is there' }
            else { Mark 'INCONCLUSIVE' "$f on $ref" 'unreadable answer' }
        } elseif ($out -match 'HTTP 404') { Mark 'PASS' "$f on $ref" 'absent' }
        else { Mark 'INCONCLUSIVE' "$f on $ref" 'could not read it' }
    }
}
$tagAfter = ShaOf 'tags/main'
if ($tagAfter -ceq 'absent') { Mark 'PASS' 'tag main after' 'absent' }
elseif (-not $tagAfter) { Mark 'INCONCLUSIVE' 'tag main after' 'could not read it' }
else { Mark 'FAIL' 'tag main after' "a tag named main exists at $tagAfter" }
$mainAfter = ShaOf 'heads/main'
if ($mainAfter -ceq $mainBefore) { Mark 'PASS' 'main' "unchanged at $mainBefore" }
elseif ($mainAfter -cmatch '^[0-9a-f]{40}$') { Mark 'INCONCLUSIVE' 'main' "moved during the probe: $mainBefore -> $mainAfter (the lines above say whether a probe change went in)" }
else { Mark 'INCONCLUSIVE' 'main' 'could not read it after the probe' }
$rdAfter = ShaOf 'heads/records-data'
$rdShown = if ($rdAfter) { $rdAfter } else { 'unread' }
Log "records-data after: $rdShown (the daily run may move it; only the probe files above count)."
Finish
} finally {
    if ($script:started -and -not $script:finished) { $script:started = $false; CleanupQuiet }   # an early stop (Ctrl+C)
    GiveBackScope
}
