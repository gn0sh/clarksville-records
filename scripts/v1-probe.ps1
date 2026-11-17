# V1 probe, one time (docs/architecture/main-protect-invariant.md "V1 probe"; runbook docs/ops/morning-note.md 2.0.4;
# task T4.10.1). Brian runs this one; scripts/v1-probe.sh is its tested bash twin (same steps, same verdicts).
#
# Question: does GitHub refuse GITHUB_TOKEN merging a pull request that adds a workflow file? The gate job's design
# rests on it. Signed in as the owner (gh auth login, with the workflow scope; the script asks for it if missing):
#   1. checks a daily data PR was merged by GitHub Actions (so bot merges work: a refusal below is about workflows);
#   2. pushes the throwaway branch probe/v1-target (main plus an inert .github/workflows/v1-canary.yml, two commits)
#      and opens its pull request into main (author: you);
#   3. posts a COMMENT review on it pinned to the OLDER commit and checks GitHub keeps that commit_id;
#   4. pushes probe/v1-runner (main plus .github/workflows/v1-probe.yml), which starts a run that tries to merge the
#      pull request with GITHUB_TOKEN: squash, then merge, then rebase (REST), then GraphQL mergePullRequest;
#   5. reads the run's answers, whether the probe PR merged, whether v1-canary.yml is on main, and main's sha before
#      and after; prints PASS, FAIL or INCONCLUSIVE, and cleans up (closes the PR, deletes both probe branches).
# FAIL means the probe PR merged (the run's own merge answer, or the PR reads merged) or v1-canary.yml is on main
# (v1-probe/verdict-from-main-sha): then it turns "Allow GitHub Actions to create and approve pull requests" off at
# once. main moving for another reason, or a read that failed, is INCONCLUSIVE and leaves that setting on.
# Writes the result to Documents\v1-probe-results-<time>.txt. Nothing is sent to anyone.
#
# Run (PowerShell, in the repository folder):  powershell -NoProfile -File scripts\v1-probe.ps1
# No double quotes are passed to gh (Windows PowerShell 5.1 mangles them).

$ErrorActionPreference = 'Continue'   # exit codes are checked
$repo = 'gn0sh/clarksville-records'
$target = 'probe/v1-target'
$runner = 'probe/v1-runner'
$results = Join-Path ([Environment]::GetFolderPath('MyDocuments')) ('v1-probe-results-' + (Get-Date -Format 'yyyyMMdd-HHmm') + '.txt')
$script:num = ''
function Log([string]$line) { Write-Host $line; Add-Content -Path $results -Value $line }
function Quiet { gh api @args --silent *> $null }
function Cleanup {
    if ($script:num) { Quiet -X PATCH "repos/$repo/pulls/$($script:num)" -f state=closed }
    Quiet -X DELETE "repos/$repo/git/refs/heads/$target"
    Quiet -X DELETE "repos/$repo/git/refs/heads/$runner"
}
function B64([string]$text) { [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($text)) }

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host 'GitHub CLI not found. Install it (winget install GitHub.cli), run gh auth login, then run this again.'; exit 1
}
gh auth status *> $null
if ($LASTEXITCODE -ne 0) { Write-Host 'Not signed in: run gh auth login (as the repository owner).'; exit 1 }
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
Quiet -X DELETE "repos/$repo/git/refs/heads/$target"     # leftovers of an earlier try
Quiet -X DELETE "repos/$repo/git/refs/heads/$runner"

$code = 1
try {
    $canaryText = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'v1-probe\v1-canary.yml'))
    $probeText = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'v1-probe\v1-probe.yml'))
    gh api -X POST "repos/$repo/git/refs" -f ref=refs/heads/$target -f sha=$mainBefore --silent
    $first = (gh api -X PUT "repos/$repo/contents/.github/workflows/v1-canary.yml" -f 'message=V1 probe: inert canary workflow' `
              -f content=$(B64 $canaryText) -f branch=$target --jq '[.commit.sha, .content.sha] | @tsv') -join ''
    $c1, $blob = $first -split "`t"
    $c2 = (gh api -X PUT "repos/$repo/contents/.github/workflows/v1-canary.yml" -f 'message=V1 probe: second commit' `
           -f content=$(B64 ($canaryText + "# second commit of the probe`n")) -f sha=$blob -f branch=$target --jq '.commit.sha') -join ''
    $script:num = (gh api -X POST "repos/$repo/pulls" -f head=$target -f base=main -f 'title=V1 probe (do not merge)' `
                   -f 'body=One-time V1 probe (runbook 2.0.4). Closed by the probe script; never merge it.' --jq '.number') -join ''
    if ($script:num -notmatch '^[0-9]+$' -or $c1 -notmatch '^[0-9a-f]{40}$' -or $c2 -notmatch '^[0-9a-f]{40}$') {
        Log 'INCONCLUSIVE: could not set up the probe branch or pull request (see the messages above). Send this output to the team.'
        exit 1
    }
    Log "Probe pull request #$($script:num): commits $c1 (older) and $c2 (head)"
    $kept = (gh api -X POST "repos/$repo/pulls/$($script:num)/reviews" -f commit_id=$c1 -f event=COMMENT `
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
    if (-not $run) { Log 'INCONCLUSIVE: the probe run did not start within 3 minutes. Send this output to the team.'; exit 1 }
    Log "Probe run: https://github.com/$repo/actions/runs/$run"
    gh run watch $run --repo $repo *> $null
    $lines = @(gh run view $run --repo $repo --log 2>$null | ForEach-Object {
        if ($_ -match 'V1-(RESULT|MERGED) (squash|merge|rebase|graphql).*') { $Matches[0] } })
    $mainAfter = (gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha') -join ''
    foreach ($l in $lines) { Log $l }
    Log "main after: $mainAfter"
    # The verdict comes from the probe PR and the canary file, not from main's sha (any other merge moves main).
    $prMerged = (gh api "repos/$repo/pulls/$($script:num)" --jq '.merged' 2>$null) -join ''
    $canaryOut = (gh api "repos/$repo/contents/.github/workflows/v1-canary.yml?ref=main" --jq '.sha' 2>&1) -join ' '
    $canaryRc = $LASTEXITCODE
    $canary = 'unread'
    if ($canaryRc -eq 0) { if ($canaryOut -match '^[0-9a-f]{40}$') { $canary = 'on-main' } }
    elseif ($canaryOut -match 'HTTP 404') { $canary = 'absent' }
    $prShown = if ($prMerged) { $prMerged } else { 'unread' }
    Log "Probe pull request merged: $prShown. v1-canary.yml on main: $canary"

    $refusedLines = @($lines | Where-Object { $_ -match '^V1-RESULT (squash|merge|rebase|graphql) exit=[1-9]' })
    $named = @($refusedLines | Where-Object { $_ -match 'without .workflows. permission' }).Count
    $merged = @($lines | Where-Object { $_ -match '^V1-MERGED (squash|merge|rebase|graphql)' }).Count
    if ($merged -gt 0 -or $prMerged -eq 'true' -or $canary -eq 'on-main') {
        Log 'FAIL (V1 false): GITHUB_TOKEN merged a workflow change into main. Turning off Allow GitHub Actions to create and approve pull requests now.'
        gh api -X PUT "repos/$repo/actions/permissions/workflow" -F can_approve_pull_request_reviews=false --silent
        if ($LASTEXITCODE -eq 0) { Log 'Turned off. The daily update now stops saving data (the safe state).' }
        else { Log 'Could NOT turn it off: Settings > Actions > General > Workflow permissions > untick Allow GitHub Actions to create and approve pull requests > Save. Now.' }
        Log 'Leave MAIN_PR_BASELINE and MORNING_NOTE_SEND unset. Send this output to the team.'
        if ($prMerged -eq 'true') { $script:num = '' }   # the pull request is merged: nothing to close
        $code = 2
    } elseif ($prMerged -ne 'false' -or $canary -ne 'absent' -or $mainAfter -notmatch '^[0-9a-f]{40}$' -or $mainAfter -ne $mainBefore) {
        Log 'INCONCLUSIVE: the probe pull request is not shown merged, but main moved during the probe or a read failed (see above). Allow GitHub Actions to create and approve pull requests is left on. Send this output to the team.'
        $code = 1
    } elseif ($refusedLines.Count -eq 4 -and $named -eq 4 -and $reviewOk -eq 'yes') {
        Log 'PASS: all four merges (squash, merge, rebase, GraphQL) refused for the workflows permission, main unchanged, review commit_id kept. Send this output to the team.'
        $code = 0
    } else {
        Log "INCONCLUSIVE: refused $($refusedLines.Count) of 4, $named naming the workflows permission, review commit_id kept: $reviewOk. Send this output to the team."
        $code = 1
    }
} finally {
    Cleanup
    Write-Host "Saved to $results"
}
exit $code
