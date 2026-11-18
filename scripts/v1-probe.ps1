# V1 probe, one time (docs/architecture/main-protect-invariant.md "V1 probe"; runbook docs/ops/morning-note.md 2.0.4;
# task T4.10.1). Brian runs this one; scripts/v1-probe.sh is its tested bash twin (same steps, same verdicts).
#
# Question (V1', ADR 0010 decision 5): with the code-owner rule R1' on, does GitHub refuse GITHUB_TOKEN merging a pull
# request that changes anything outside data/, even after the bot approved it? Signed in as the owner (gh auth login,
# with the workflow scope; asked for only after the guard below passed), the script:
#   1. checks R1' is on (guard) and a daily data PR was merged by GitHub Actions (so bot merges work);
#   2. pushes three throwaway branches and opens their pull requests into main (author: you): W probe/v1-target
#      (an inert .github/workflows/v1-canary.yml, two commits), N probe/v1-target-n (sitegen/v1-probe-canary.txt),
#      H1 probe/v1-target-h1 (only renames .github/CODEOWNERS to data/v1-probe-CODEOWNERS);
#   3. posts a COMMENT review on W pinned to the OLDER commit and checks GitHub keeps that commit_id (step 4);
#   4. pushes probe/v1-runner (main plus .github/workflows/v1-probe.yml), which starts a run that, for each target,
#      posts a GITHUB_TOKEN APPROVE review, then tries squash, merge, rebase (REST) and GraphQL mergePullRequest;
#   5. reads the run's answers, whether each probe PR merged, whether each probe file is on main, and main's sha
#      before and after; prints PASS, FAIL or INCONCLUSIVE, and cleans up (closes every probe PR, deletes every
#      probe branch).
# PASS: for every target, both squash tries refused naming code-owner review, merge and rebase refused. FAIL means a
# probe PR merged or a probe file is on main (v1-probe/verdict-from-main-sha): then it turns "Allow GitHub Actions to
# create and approve pull requests" off at once. main moving for another reason, or a read that failed, is
# INCONCLUSIVE and leaves that setting on.
# v1-probe/verdict-race (L-c): the run must read `completed` before its answers count (else INCONCLUSIVE), and a PASS
# or INCONCLUSIVE stands only if the probe PR, read again after cleanup closed it, is still unmerged.
# Writes the result to Documents\v1-probe-results-<time>.txt. Nothing is sent to anyone.
#
# Run (PowerShell, in the repository folder):  powershell -NoProfile -File scripts\v1-probe.ps1
# No double quotes are passed to gh (Windows PowerShell 5.1 mangles them).

$ErrorActionPreference = 'Continue'   # exit codes are checked
$repo = 'gn0sh/clarksville-records'
$target = 'probe/v1-target'
$targetN = 'probe/v1-target-n'
$targetH = 'probe/v1-target-h1'
$runner = 'probe/v1-runner'
$branches = @($target, $targetN, $targetH, $runner)
$fileW = '.github/workflows/v1-canary.yml'
$fileN = 'sitegen/v1-probe-canary.txt'
$fileH = 'data/v1-probe-CODEOWNERS'
$results = Join-Path ([Environment]::GetFolderPath('MyDocuments')) ('v1-probe-results-' + (Get-Date -Format 'yyyyMMdd-HHmm') + '.txt')
$script:nums = @()
function Log([string]$line) { Write-Host $line; Add-Content -Path $results -Value $line }
function Quiet { gh api @args --silent *> $null }
function Cleanup {   # every probe pull request closed, every probe branch deleted
    foreach ($n in $script:nums) { Quiet -X PATCH "repos/$repo/pulls/$n" -f state=closed }
    foreach ($b in $branches) { Quiet -X DELETE "repos/$repo/git/refs/heads/$b" }
}
function B64([string]$text) { [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($text)) }
function TurnR2Off {
    Log "FAIL (V1' false): GITHUB_TOKEN merged a probe pull request into main. Turning off Allow GitHub Actions to create and approve pull requests now."
    gh api -X PUT "repos/$repo/actions/permissions/workflow" -F can_approve_pull_request_reviews=false --silent
    if ($LASTEXITCODE -eq 0) { Log 'Turned off: workflows can no longer open pull requests, so the daily update stops saving data.' }
    else { Log 'Could NOT turn it off: Settings > Actions > General > Workflow permissions > untick Allow GitHub Actions to create and approve pull requests > Save. Now.' }
    Log 'Leave GitHub Actions on and open pull requests open: only someone with write access can start a workflow that merges (ADR 0010, invariant T1-T8).'
    Log "The canary is removed by a person's pull request (scripts\merge-reviewed.ps1); the team opens it."
    Log 'Leave MAIN_PR_BASELINE and MORNING_NOTE_SEND unset. Send this output to the team: the fallback, data off main, goes to a Brain Trust (ADR 0010).'
}
$verdict = ''

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host 'GitHub CLI not found. Install it (winget install GitHub.cli), run gh auth login, then run this again.'; exit 1
}
gh auth status *> $null
if ($LASTEXITCODE -ne 0) { Write-Host 'Not signed in: run gh auth login (as the repository owner).'; exit 1 }
# v1-probe/rerun-after-fail (ADR 0010): the probe found FAIL on 2026-11-18 (GitHub let GITHUB_TOKEN merge a workflow
# change into main). Turning "Allow GitHub Actions to create and approve pull requests" off does not stop merging, so
# running the probe again would put the canary on main again. It runs only once main's ruleset requires a code
# owner's review (R1', scripts\protect-main.ps1), which is what a new run tests. The rule is vacuous without an owner,
# so it also needs .github/CODEOWNERS on main whose rules are `* @gn0sh` first and nothing else but `/data/` (a later
# line overrides an earlier one: v1-probe/rerun-after-fail-codeowners-override), no CODEOWNERS errors, every ruleset
# that carries the rule active (not evaluate or disabled), and its bypass list empty or exactly the admin role in
# pull request mode (v1-probe/rerun-after-fail-bypass). Any failed read stops it (fail closed). It runs before
# gh auth refresh, so a refusal opens no browser. Comparisons are case-sensitive (-cmatch, -cne).
function RefuseRerun([string]$why) {
    Write-Host "Stopped: $why (ADR 0010: run scripts\protect-main.ps1 first). The probe found FAIL on 2026-11-18; running it now would merge the canary into main again. Nothing was changed."
    exit 1
}
$ownerRules = @(gh api "repos/$repo/rules/branches/main" --jq '.[] | select(.parameters.require_code_owner_review == true) | .ruleset_id' 2>$null)
if ($LASTEXITCODE -ne 0) { RefuseRerun "could not read main's rules" }
if ($ownerRules.Count -eq 0) { RefuseRerun "main's ruleset does not require a code owner's review yet" }
foreach ($id in $ownerRules) {
    if ($id -cnotmatch '^[0-9]+$') { RefuseRerun "could not read main's rules" }
    $enforcement = (gh api "repos/$repo/rulesets/$id" --jq '.enforcement' 2>$null) -join ''
    if ($LASTEXITCODE -ne 0) { RefuseRerun "could not read ruleset $id" }
    if ($enforcement -cne 'active') {
        RefuseRerun "ruleset $id requires a code owner's review but its enforcement is '$enforcement', not active"
    }
    $bypass = @(gh api "repos/$repo/rulesets/$id" --jq '.bypass_actors[] | [.actor_type, .actor_id, .bypass_mode] | @tsv' 2>$null)
    if ($LASTEXITCODE -ne 0) { RefuseRerun "could not read ruleset $id's bypass list" }
    $bypass = (@($bypass | Where-Object { $_ } | ForEach-Object { $_ -replace "`t", ':' })) -join ','
    if ($bypass -and $bypass -cne 'RepositoryRole:5:pull_request') {
        RefuseRerun "ruleset $id lets '$bypass' bypass it (only the admin role in pull request mode, RepositoryRole:5:pull_request, may)"
    }
}
$codeowners = @(gh api -H 'Accept: application/vnd.github.raw' "repos/$repo/contents/.github/CODEOWNERS?ref=main" 2>$null)
if ($LASTEXITCODE -ne 0) { RefuseRerun 'could not read .github/CODEOWNERS on main' }
# its rules: comments and blank lines dropped, runs of spaces or tabs made one space, ends trimmed
$coRules = (@($codeowners | ForEach-Object { $_ -split "`n" } | ForEach-Object { ($_ -replace '\s+', ' ').Trim() } |
              Where-Object { $_ -cnotmatch '^(#|$)' })) -join '|'
if ($coRules -cne '* @gn0sh' -and $coRules -cne '* @gn0sh|/data/') {
    RefuseRerun ".github/CODEOWNERS on main is not '* @gn0sh' (then only '/data/'): its rules are '$coRules'"
}
$ownerErrors = (gh api "repos/$repo/codeowners/errors?ref=main" --jq '.errors | length' 2>$null) -join ''
if ($LASTEXITCODE -ne 0) { RefuseRerun "could not read GitHub's CODEOWNERS errors" }
if ($ownerErrors -cne '0') { RefuseRerun "GitHub lists '$ownerErrors' error(s) in .github/CODEOWNERS" }
$status = (gh auth status 2>&1) | Out-String
if ($status -notmatch 'workflow') {
    Write-Host 'Your GitHub CLI sign-in needs the workflow scope to push the probe workflow files: a browser opens.'
    gh auth refresh -h github.com -s workflow
}
$dataPrs = (gh pr list --repo $repo --state merged --app github-actions --search 'head:data/' --json number --jq 'length') -join ''
if ($dataPrs -notmatch '^[0-9]+$' -or [int]$dataPrs -lt 1) {
    Write-Host 'No daily data pull request merged by GitHub Actions yet: do the check run of runbook step 2.0 first. Nothing was changed.'
    exit 1
}

Set-Content -Path $results -Value ''
$mainBefore = (gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha') -join ''
Log ("V1 probe " + (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') + ". main before: $mainBefore")
if ($mainBefore -notmatch '^[0-9a-f]{40}$') { Log 'INCONCLUSIVE: could not read main. Nothing was changed.'; exit 1 }
foreach ($b in $branches) { Quiet -X DELETE "repos/$repo/git/refs/heads/$b" }     # leftovers of an earlier try

function OpenPr([string]$branch, [string]$name) {
    (gh api -X POST "repos/$repo/pulls" -f head=$branch -f base=main -f "title=V1 probe $name (do not merge)" `
        -f "body=One-time V1' probe (runbook 2.0.4). Closed by the probe script; never merge it." --jq '.number') -join ''
}
function SetupFailed {
    Log 'INCONCLUSIVE: could not set up the probe branches or pull requests (see the messages above). Send this output to the team.'
    exit 1
}

$code = 1
try {
    $canaryText = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'v1-probe\v1-canary.yml'))
    $probeText = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'v1-probe\v1-probe.yml'))
    # W: an inert workflow file, two commits (the older one carries the step 4 review)
    gh api -X POST "repos/$repo/git/refs" -f ref=refs/heads/$target -f sha=$mainBefore --silent
    if ($LASTEXITCODE -ne 0) { SetupFailed }
    $first = (gh api -X PUT "repos/$repo/contents/$fileW" -f 'message=V1 probe: inert canary workflow' `
              -f content=$(B64 $canaryText) -f branch=$target --jq '[.commit.sha, .content.sha] | @tsv') -join ''
    $c1, $blob = $first -split "`t"
    $c2 = (gh api -X PUT "repos/$repo/contents/$fileW" -f 'message=V1 probe: second commit' `
           -f content=$(B64 ($canaryText + "# second commit of the probe`n")) -f sha=$blob -f branch=$target --jq '.commit.sha') -join ''
    $num = OpenPr $target 'W'
    $script:nums += $num
    # N (M2): one non-workflow file outside data/
    gh api -X POST "repos/$repo/git/refs" -f ref=refs/heads/$targetN -f sha=$mainBefore --silent
    if ($LASTEXITCODE -ne 0) { SetupFailed }
    gh api -X PUT "repos/$repo/contents/$fileN" -f 'message=V1 probe: inert non-workflow file' `
        -f content=$(B64 "V1 probe: inert, never merge.`n") -f branch=$targetN --silent
    if ($LASTEXITCODE -ne 0) { SetupFailed }
    $script:nums += (OpenPr $targetN 'N')
    # H1 (main-protect/codeowners-rename-vacuous): only renames .github/CODEOWNERS into data/ (same blob, new path)
    $coBlob = (gh api "repos/$repo/contents/.github/CODEOWNERS?ref=$mainBefore" --jq '.sha') -join ''
    if ($LASTEXITCODE -ne 0) { SetupFailed }
    $baseTree = (gh api "repos/$repo/git/commits/$mainBefore" --jq '.tree.sha') -join ''
    if ($LASTEXITCODE -ne 0) { SetupFailed }
    # the tree goes in on stdin (no double quotes in any argument: Windows PowerShell 5.1 mangles them)
    $treeJson = '{"base_tree":"' + $baseTree + '","tree":[{"path":".github/CODEOWNERS","mode":"100644","type":"blob","sha":null},{"path":"' + $fileH + '","mode":"100644","type":"blob","sha":"' + $coBlob + '"}]}'
    $tree = ($treeJson | gh api -X POST "repos/$repo/git/trees" --input - --jq '.sha') -join ''
    if ($LASTEXITCODE -ne 0) { SetupFailed }
    $commitH = (gh api -X POST "repos/$repo/git/commits" -f 'message=V1 probe: rename CODEOWNERS into data/' -f tree=$tree `
                -f "parents[]=$mainBefore" --jq '.sha') -join ''
    if ($LASTEXITCODE -ne 0) { SetupFailed }
    gh api -X POST "repos/$repo/git/refs" -f ref=refs/heads/$targetH -f sha=$commitH --silent
    if ($LASTEXITCODE -ne 0) { SetupFailed }
    $script:nums += (OpenPr $targetH 'H1')
    foreach ($n in $script:nums) { if ($n -cnotmatch '^[0-9]+$') { SetupFailed } }
    if ($script:nums.Count -ne 3 -or $c1 -cnotmatch '^[0-9a-f]{40}$' -or $c2 -cnotmatch '^[0-9a-f]{40}$') { SetupFailed }
    Log "Probe pull requests: W #$num (commits $c1 older, $c2 head), N #$($script:nums[1]), H1 #$($script:nums[2])"
    $kept = (gh api -X POST "repos/$repo/pulls/$num/reviews" -f commit_id=$c1 -f event=COMMENT `
             -f 'body=V1 probe step 4: a review pinned to the older commit.' --jq '.commit_id') -join ''
    $reviewOk = if ($kept -eq $c1) { 'yes' } else { 'no' }
    Log "Step 4, review commit_id: asked $c1, GitHub kept $kept ($reviewOk)"

    gh api -X POST "repos/$repo/git/refs" -f ref=refs/heads/$runner -f sha=$mainBefore --silent
    $r = (gh api -X PUT "repos/$repo/contents/.github/workflows/v1-probe.yml" -f 'message=V1 probe: runner workflow' `
          -f content=$(B64 $probeText) -f branch=$runner --jq '.commit.sha') -join ''
    $env:R = $r
    $run = ''
    for ($i = 0; $i -lt 18 -and -not $run; $i++) {
        $run = (gh run list --repo $repo --branch $runner --event push --json databaseId,headSha `
                --jq '[.[] | select(.headSha == $ENV.R)][0].databaseId // empty') -join ''
        if (-not $run) { Start-Sleep -Seconds 10 }
    }
    if (-not $run) {
        $verdict = 'INCONCLUSIVE: the probe run did not start within 3 minutes. Send this output to the team.'
        $code = 1
    } else {
        Log "Probe run: https://github.com/$repo/actions/runs/$run"
        gh run watch $run --repo $repo *> $null
        $status = (gh run view $run --repo $repo --json status --jq '.status' 2>$null) -join ''
        $statusShown = if ($status) { $status } else { 'unread' }
        Log "Probe run status: $statusShown"
        # v1-probe/log-raw-to-console: the run's log is untrusted text; drop ANSI colour codes, then control
        # characters, before any of it is matched or printed.
        $logText = @(gh run view $run --repo $repo --log 2>$null | ForEach-Object {
            ($_ -replace '\x1b\[[0-9;?]*[ -/]*[@-~]', '') -replace '[\x00-\x08\x0B-\x1F\x7F]', '' })
        $lines = @($logText | ForEach-Object {
            if ($_ -cmatch 'V1-(RESULT|MERGED|APPROVE) (W|N|H1) .*') { $Matches[0] } })
        # v1-probe/node-read-under-e: the run's own V1-ERROR lines reach Brian too (not the step's echo text the log shows).
        $errors = @($logText | Where-Object { $_ -notmatch 'echo "V1-ERROR' } | ForEach-Object {
            if ($_ -match 'V1-ERROR: .*') { $Matches[0] } })
        $mainAfter = (gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha') -join ''
        foreach ($l in $lines) { Log $l }
        foreach ($l in $errors) { Log $l }
        Log "main after: $mainAfter"
        # The verdict comes from the probe PRs and the probe files, not from main's sha (any other merge moves main).
        $anyMerged = $false; $allUnmerged = $true; $notMerged = @()
        foreach ($n in $script:nums) {
            $m = (gh api "repos/$repo/pulls/$n" --jq '.merged' 2>$null) -join ''
            $mShown = if ($m) { $m } else { 'unread' }
            Log "Probe pull request #$n merged: $mShown"
            if ($m -ceq 'true') { $anyMerged = $true } else { $notMerged += $n }
            if ($m -cne 'false') { $allUnmerged = $false }
        }
        $onMain = $false; $allAbsent = $true
        foreach ($f in @($fileW, $fileN, $fileH)) {
            $out = (gh api "repos/$repo/contents/$($f)?ref=main" --jq '.sha' 2>&1) -join ' '
            $rc = $LASTEXITCODE
            $state = 'unread'
            if ($rc -eq 0) { if ($out -cmatch '^[0-9a-f]{40}$') { $state = 'on-main' } }
            elseif ($out -match 'HTTP 404') { $state = 'absent' }
            Log "$f on main: $state"
            if ($state -ceq 'on-main') { $onMain = $true }
            if ($state -cne 'absent') { $allAbsent = $false }
        }

        $merged = @($lines | Where-Object { $_ -cmatch '^V1-MERGED (W|N|H1) ' }).Count
        if ($merged -gt 0 -or $anyMerged -or $onMain) {
            TurnR2Off
            $script:nums = $notMerged   # a merged pull request is not closed again
            $code = 2
        } elseif ($status -cne 'completed') {
            $verdict = "INCONCLUSIVE: the probe run had not finished ($statusShown), so its answers are not final. Allow GitHub Actions to create and approve pull requests is left on. Send this output to the team."
            $code = 1
        } elseif (-not $allUnmerged -or -not $allAbsent -or $mainAfter -cnotmatch '^[0-9a-f]{40}$' -or $mainAfter -cne $mainBefore) {
            $verdict = 'INCONCLUSIVE: no probe pull request is shown merged, but main moved during the probe or a read failed (see above). Allow GitHub Actions to create and approve pull requests is left on. Send this output to the team.'
            $code = 1
        } else {
            # V1' (ADR 0010 decision 5; M1 v1-probe/pass-not-proving-u1): for every target, the bot's approval was
            # posted, REST squash and GraphQL squash were both refused naming code-owner review, and merge and rebase
            # were refused (method refused: squash only). Anything else is INCONCLUSIVE.
            $proven = 0; $summary = ''
            foreach ($t in @('W', 'N', 'H1')) {
                $ok = @($lines | Where-Object { $_ -cmatch "^V1-APPROVE $t exit=0( |$)" }).Count -gt 0
                foreach ($m in @('squash', 'graphql')) {
                    if (@($lines | Where-Object { $_ -cmatch "^V1-RESULT $t $m exit=[1-9]" -and $_ -match 'code owner' }).Count -eq 0) { $ok = $false }
                }
                foreach ($m in @('merge', 'rebase')) {
                    if (@($lines | Where-Object { $_ -cmatch "^V1-RESULT $t $m exit=[1-9]" }).Count -eq 0) { $ok = $false }
                }
                if ($ok) { $proven++; $summary += " ${t}:proven" } else { $summary += " ${t}:not-proven" }
            }
            if ($proven -eq 3 -and $reviewOk -ceq 'yes') {
                $verdict = "PASS (V1'): for W, N and H1, the bot's approval did not count: REST squash and GraphQL squash refused for code-owner review, merge and rebase refused (method refused); main unchanged, every probe pull request unmerged, no probe file on main, review commit_id kept. Send this output to the team."
                $code = 0
            } else {
                $verdict = "INCONCLUSIVE:$summary (each needs the bot approval posted, both squash tries refused naming code-owner review, merge and rebase refused); review commit_id kept: $reviewOk. Send this output to the team."
                $code = 1
            }
        }
    }
} finally {
    Cleanup
}
# v1-probe/verdict-race (L-c): a PASS or INCONCLUSIVE is final only after cleanup closed every probe pull request and
# a fresh read still shows each unmerged; a merge that landed meanwhile turns it into FAIL.
if ($code -ne 2) {
    $unread = $false
    foreach ($n in $script:nums) {
        $again = (gh api "repos/$repo/pulls/$n" --jq '.merged' 2>$null) -join ''
        $againShown = if ($again) { $again } else { 'unread' }
        Log "Probe pull request #$n merged, read again after cleanup: $againShown"
        if ($again -ceq 'true') { $code = 2 }
        elseif ($again -cne 'false') { $unread = $true }
    }
    if ($code -eq 2) {
        TurnR2Off
    } elseif ($code -eq 0 -and $unread) {
        Log 'INCONCLUSIVE: a probe pull request could not be read again after cleanup. Send this output to the team.'
        $code = 1
    } else {
        Log $verdict
    }
}
Write-Host "Saved to $results"
exit $code
