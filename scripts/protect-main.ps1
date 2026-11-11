# Protect main: create the "main: pull request required" ruleset, or update it if it already exists
# (docs/ops/morning-note.md, step 2.0.6). Safe to run more than once: it never makes a second ruleset.
#
# Needs: GitHub CLI (winget install GitHub.cli), signed in as the repository owner: gh auth login
# Run (PowerShell, in the repository folder):
#   powershell -ExecutionPolicy Bypass -File scripts\protect-main.ps1
# The rules and the bypass (the GitHub Actions app, id 15368) are in scripts\main-ruleset.json.
# No double quotes are passed to gh (Windows PowerShell 5.1 mangles them): the name comes in through $ENV.

$ErrorActionPreference = 'Continue'   # 'Stop' turns gh's stderr into errors in PowerShell 5.1; exit codes are checked
$repo = 'gn0sh/clarksville-records'
$body = Join-Path $PSScriptRoot 'main-ruleset.json'
$env:RULESET_NAME = 'main: pull request required'
$find = '.[] | select(.name == $ENV.RULESET_NAME) | .id'

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host 'GitHub CLI not found. Install it (winget install GitHub.cli), run gh auth login, then run this again.'
    exit 1
}
gh auth status *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Not signed in. Run gh auth login (as the repository owner), then run this again.'
    exit 1
}

$ids = @(gh api "repos/$repo/rulesets" --jq $find | Where-Object { $_ })
if ($LASTEXITCODE -ne 0) { Write-Host 'Could not list the rulesets (signed in as the owner?).'; exit 1 }

if ($ids.Count -eq 0) {
    Write-Host 'No ruleset yet: creating it.'
    gh api -X POST "repos/$repo/rulesets" --input $body --silent
    if ($LASTEXITCODE -ne 0) { Write-Host 'Creating the ruleset failed (see the message above). Nothing was changed. Send this output to the team.'; exit 1 }
} else {
    foreach ($id in $ids) {
        Write-Host "Ruleset $id already exists: updating it."
        gh api -X PUT "repos/$repo/rulesets/$id" --input $body --silent
        if ($LASTEXITCODE -ne 0) { Write-Host "Updating ruleset $id failed (see the message above). Nothing was changed. Send this output to the team."; exit 1 }
    }
}

# The checks of step 2.0.
$rules = (@(gh api "repos/$repo/rules/branches/main" --jq '.[].type') | Sort-Object -Unique) -join ','
$ok = $rules -eq 'deletion,non_fast_forward,pull_request'
Write-Host "Rules on main: $rules"
foreach ($id in @(gh api "repos/$repo/rulesets" --jq $find | Where-Object { $_ })) {
    $enf = (gh api "repos/$repo/rulesets/$id" --jq '.enforcement') -join ''
    $actors = (@(gh api "repos/$repo/rulesets/$id" --jq '.bypass_actors[] | [.actor_type, .actor_id] | @tsv') |
               ForEach-Object { $_ -replace "`t", ':' }) -join ','
    Write-Host "Ruleset ${id}: $enf, bypass $actors"
    if ($enf -ne 'active' -or $actors -ne 'Integration:15368') { $ok = $false }
}
if ($ok) {
    Write-Host 'OK: main is protected. Next: Actions > Daily update > Run workflow (the check run of step 2.0).'
} else {
    Write-Host 'NOT OK: expected rules deletion,non_fast_forward,pull_request and active, bypass Integration:15368.'
    Write-Host 'Send this output to the team.'
    exit 1
}
