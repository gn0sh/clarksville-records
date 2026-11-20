# Merge a reviewed pull request: the only way a person merges a PR that changes anything outside data/ (runbook
# docs/ops/morning-note.md 2.0.3; docs/architecture/main-protect-invariant.md S2; ADR 0009).
#
# Run (PowerShell, in the repository folder):
#   powershell -NoProfile -File scripts\merge-reviewed.ps1 <pr number> <reviewed head sha> <review report> [...]
#   <reviewed head sha>  the full 40-character commit the team's review and QA passed (the PR's head)
#   <review report>      a link or path to each review report (code review, security, QA)
# It refuses unless that sha is the PR's head now (L-D), posts a COMMENT review pinned to that sha naming the reports,
# squash-merges pinned to the same sha, deletes the head branch and prints the merge commit.
# ADR 0011 (R1'', consumer row S2): every merge into main is a bypass merge, so it also refuses a PR whose author is
# not gn0sh or whose head is in another repository, and after the merge it prints the rule suite GitHub recorded for
# the merge commit; its last line is "Rule suite <id> for <merge sha>: <result>", and the result must be bypass.
# Exit 0 merged with a bypass rule suite, 1 refused (nothing done), 2 merged but the rule suite is not bypass or was
# not found (tell the team). Needs GitHub CLI, signed in as gn0sh (gh auth login). No double quotes are passed to gh
# (Windows PowerShell 5.1): strings come in through $ENV.
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Pr,
    [Parameter(Mandatory = $true, Position = 1)][string]$Sha,
    [Parameter(Mandatory = $true, Position = 2, ValueFromRemainingArguments = $true)][string[]]$Reports
)
$ErrorActionPreference = 'Continue'   # exit codes are checked
$repo = 'gn0sh/clarksville-records'
$owner = 'gn0sh'

if ($Pr -notmatch '^[0-9]+$') { Write-Host 'The first argument is the pull request number. Nothing done.'; exit 1 }
if ($Sha -cnotmatch '^[0-9a-f]{40}$') {
    Write-Host 'The sha must be the full 40-character commit you reviewed (git rev-parse <branch>). Nothing done.'; exit 1
}
gh auth status *> $null
if ($LASTEXITCODE -ne 0) { Write-Host 'Not signed in: run gh auth login. Nothing done.'; exit 1 }

$got = (gh api "repos/$repo/pulls/$Pr" --jq '[(.state|tostring), (.base.ref|tostring), (.head.sha|tostring), (.head.ref|tostring), (.head.repo.full_name|tostring), (.user.login|tostring)] | @tsv') -join ''
if ($LASTEXITCODE -ne 0) { Write-Host "Could not read pull request #$Pr. Nothing done."; exit 1 }
$f = $got -split "`t"
if ($f.Count -lt 6 -or $f[0] -cne 'open' -or $f[1] -cne 'main') {
    Write-Host "Pull request #$Pr is not open into main ($($got -replace "`t", ' ')). Nothing done."; exit 1
}
if ($f[5] -cne $owner) {
    Write-Host "Pull request #$Pr is authored by '$($f[5])', not ${owner}: never bypass-merged (ADR 0011). Nothing done."; exit 1
}
if ($f[4] -cne $repo) {
    Write-Host "Pull request #$Pr's head is in '$($f[4])', not ${repo}: never bypass-merged (ADR 0011). Nothing done."; exit 1
}
if ($f[2] -cne $Sha) {
    Write-Host "Pull request #$Pr's head is $($f[2]), not ${Sha}: it changed after the review. Review the new head, then run this again with its sha. Nothing done."
    exit 1
}
$ref = $f[3]

$body = "Reviewed at $Sha. Review reports: " + ($Reports -join ' ')
$review = (gh api -X POST "repos/$repo/pulls/$Pr/reviews" -f commit_id=$Sha -f event=COMMENT -f body=$body --jq '.commit_id') -join ''
if ($review -ne $Sha) { Write-Host "The review was posted at '$review', not $Sha. Not merged: tell the team."; exit 1 }
$merged = (gh api -X PUT "repos/$repo/pulls/$Pr/merge" -f merge_method=squash -f sha=$Sha --jq '.sha') -join ''
if ($merged -cnotmatch '^[0-9a-f]{40}$') { Write-Host "The merge did not report a commit ('$merged'). Check pull request #$Pr."; exit 1 }
gh api -X DELETE "repos/$repo/git/refs/heads/$ref" --silent
if ($LASTEXITCODE -ne 0) { Write-Host "Could not delete the branch ${ref}: delete it on the pull request's page." }
Write-Host "Merged pull request #$Pr (reviewed at $Sha) as $merged."
# ADR 0011: under R1'' this merge must be a bypass; GitHub lists the rule suite a few seconds after the merge.
$env:MR_AFTER = $merged
$suite = ''
for ($i = 1; $i -le 5; $i++) {
    $suite = (@(gh api "repos/$repo/rulesets/rule-suites?ref=main&time_period=hour&per_page=100" --jq '.[] | select(.after_sha == $ENV.MR_AFTER) | [(.id|tostring), (.result|tostring)] | @tsv' 2> $null))[0]
    if ($LASTEXITCODE -ne 0) { $suite = '' }
    if ($suite) { break }
    if ($i -lt 5) { Start-Sleep -Seconds 10 }
}
if (-not $suite) { Write-Host "Rule suite for ${merged}: not found (Insights > Rule suites shows it). Tell the team."; exit 2 }
$sf = $suite -split "`t"
Write-Host "Rule suite $($sf[0]) for ${merged}: $($sf[1])"
if ($sf[1] -cne 'bypass') { Write-Host "The merge was not a bypass ($($sf[1])): tell the team."; exit 2 }
