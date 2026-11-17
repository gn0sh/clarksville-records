# Merge a reviewed pull request: the only way a person merges a PR that changes anything outside data/ (runbook
# docs/ops/morning-note.md 2.0.3; docs/architecture/main-protect-invariant.md S2; ADR 0009).
#
# Run (PowerShell, in the repository folder):
#   powershell -NoProfile -File scripts\merge-reviewed.ps1 <pr number> <reviewed head sha> <review report> [...]
#   <reviewed head sha>  the full 40-character commit the team's review and QA passed (the PR's head)
#   <review report>      a link or path to each review report (code review, security, QA)
# It refuses unless that sha is the PR's head now (L-D), posts a COMMENT review pinned to that sha naming the reports,
# squash-merges pinned to the same sha, deletes the head branch and prints the merge commit. Needs GitHub CLI, signed
# in as a person with write access (gh auth login). No double quotes are passed to gh (Windows PowerShell 5.1).
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Pr,
    [Parameter(Mandatory = $true, Position = 1)][string]$Sha,
    [Parameter(Mandatory = $true, Position = 2, ValueFromRemainingArguments = $true)][string[]]$Reports
)
$ErrorActionPreference = 'Continue'   # exit codes are checked
$repo = 'gn0sh/clarksville-records'

if ($Pr -notmatch '^[0-9]+$') { Write-Host 'The first argument is the pull request number. Nothing done.'; exit 1 }
if ($Sha -cnotmatch '^[0-9a-f]{40}$') {
    Write-Host 'The sha must be the full 40-character commit you reviewed (git rev-parse <branch>). Nothing done.'; exit 1
}
gh auth status *> $null
if ($LASTEXITCODE -ne 0) { Write-Host 'Not signed in: run gh auth login. Nothing done.'; exit 1 }

$got = (gh api "repos/$repo/pulls/$Pr" --jq '[.state, .base.ref, .head.sha, .head.ref, .head.repo.full_name] | @tsv') -join ''
if ($LASTEXITCODE -ne 0) { Write-Host "Could not read pull request #$Pr. Nothing done."; exit 1 }
$f = $got -split "`t"
if ($f.Count -lt 5 -or $f[0] -ne 'open' -or $f[1] -ne 'main') {
    Write-Host "Pull request #$Pr is not open into main ($got). Nothing done."; exit 1
}
if ($f[2] -ne $Sha) {
    Write-Host "Pull request #$Pr's head is $($f[2]), not ${Sha}: it changed after the review. Review the new head, then run this again with its sha. Nothing done."
    exit 1
}
$ref = $f[3]
$headRepo = $f[4]

$body = "Reviewed at $Sha. Review reports: " + ($Reports -join ' ')
$review = (gh api -X POST "repos/$repo/pulls/$Pr/reviews" -f commit_id=$Sha -f event=COMMENT -f body=$body --jq '.commit_id') -join ''
if ($review -ne $Sha) { Write-Host "The review was posted at '$review', not $Sha. Not merged: tell the team."; exit 1 }
$merged = (gh api -X PUT "repos/$repo/pulls/$Pr/merge" -f merge_method=squash -f sha=$Sha --jq '.sha') -join ''
if ($merged -cnotmatch '^[0-9a-f]{40}$') { Write-Host "The merge did not report a commit ('$merged'). Check pull request #$Pr."; exit 1 }
if ($headRepo -eq $repo) {
    gh api -X DELETE "repos/$repo/git/refs/heads/$ref" --silent
    if ($LASTEXITCODE -ne 0) { Write-Host "Could not delete the branch ${ref}: delete it on the pull request's page." }
}
Write-Host "Merged pull request #$Pr (reviewed at $Sha) as $merged."
