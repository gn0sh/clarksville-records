# Protect main: create the "main: pull request required" ruleset, or update it if it already exists
# (docs/ops/morning-note.md, step 2.0.1). Safe to run more than once: it never makes a second ruleset.
# The ruleset is R1' (ADR 0010): code-owner review (.github/CODEOWNERS owns everything outside data/), squash only,
# and one bypass, the Repository admin role for pull requests only, so nobody pushes main. The daily update reaches
# main by its own data-only pull request (the push job). It stops, changing nothing, if .github/CODEOWNERS is not on
# main or GitHub lists an error in it. This reads main's
# sha BEFORE writing the ruleset (R1) and prints "Main before the ruleset: <sha>"; after R1 it reads "Allow GitHub
# Actions to create and approve pull requests" (R2, Settings > Actions > General) and turns it on, printing "R2 was
# off; main was <sha>" (that same pre-R1 sha) or "R2 already on": record those lines in docs/platform-facts.md
# "Main protection" (the start of the runbook 4.7.1 window, L-b). If this needed more than one run, the window
# starts at the sha the FIRST run printed. It stops before changing anything if main's workflow does not open data
# pull requests yet or main cannot be read.
#
# Needs: GitHub CLI (winget install GitHub.cli), signed in as the repository owner: gh auth login
# Run (PowerShell, in the repository folder):
#   powershell -NoProfile -File scripts\protect-main.ps1   (local scripts are allowed in Settings > For developers; never -ExecutionPolicy Bypass)
# The rules (and the one bypass) are in scripts\main-ruleset.json.
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

# Without the bypass, a push job that still pushes main directly would fail every day: refuse until main's workflow
# opens its data pull request.
$wf = (gh api "repos/$repo/contents/.github/workflows/daily-update.yml?ref=main" -H 'Accept: application/vnd.github.raw') -join "`n"
if ($LASTEXITCODE -ne 0 -or $wf -notmatch 'Open and merge the data pull request') {
    Write-Host 'Main does not have the data pull request change yet. Nothing was changed. Merge that pull request first, then run this again.'
    exit 1
}

# ADR 0010 (R1'): code-owner review binds only through .github/CODEOWNERS on main; without it, or with a line GitHub
# could not read, a workflow's merge of a non-data pull request would need no review at all.
# Its rules (comments and blank lines aside) must be exactly "* @gn0sh" then "/data/" (no owner: data/ unowned).
$co = @(gh api "repos/$repo/contents/.github/CODEOWNERS?ref=main" -H 'Accept: application/vnd.github.raw' 2> $null)
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Main has no .github/CODEOWNERS yet. Nothing was changed. Merge the code-owner pull request first, then run this again.'
    exit 1
}
# (the same reading as scripts\v1-probe.ps1: runs of spaces or tabs made one space, ends trimmed; a later line would
# override an earlier one, so nothing else is allowed. Comparisons here are case-sensitive: -cne, -cnotmatch.)
$coRules = (@($co | ForEach-Object { $_ -split "`n" } | ForEach-Object { ($_ -replace '\s+', ' ').Trim() } |
              Where-Object { $_ -cnotmatch '^(#|$)' })) -join '|'
if ($coRules -cne '* @gn0sh|/data/') {
    Write-Host "Main's .github/CODEOWNERS is not '* @gn0sh' then '/data/' (it has: $coRules). Nothing was changed. Send this output to the team."
    exit 1
}
$coErrors = (gh api "repos/$repo/codeowners/errors?ref=main" --jq '.errors | length') -join ''
if ($LASTEXITCODE -ne 0 -or $coErrors -cne '0') {
    Write-Host "GitHub lists errors in main's .github/CODEOWNERS ('$coErrors'). Nothing was changed. Send this output to the team."
    exit 1
}

# main-protect/window-start-gap: main's sha is read BEFORE R1 is written, so no commit can land on main between the
# window start and R1 (a direct push in that gap would be inside the window and caught by the 4.7.1 check).
$mainSha = (gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha') -join ''
if ($mainSha -notmatch '^[0-9a-f]{40}$') {
    Write-Host 'Could not read the main commit. Nothing was changed. Run this again; send this output to the team if it repeats.'; exit 1
}
Write-Host "Main before the ruleset: $mainSha"

$ids = @(gh api "repos/$repo/rulesets" --jq $find | Where-Object { $_ })
if ($LASTEXITCODE -ne 0) { Write-Host 'Could not list the rulesets (signed in as the owner?).'; exit 1 }

if ($ids.Count -eq 0) {
    Write-Host 'No ruleset yet: creating it.'
    gh api -X POST "repos/$repo/rulesets" --input $body --silent
    if ($LASTEXITCODE -ne 0) { Write-Host 'Creating the ruleset failed (see the message above). Nothing was changed. Send this output to the team.'; exit 1 }
} else {
    foreach ($id in $ids) {
        Write-Host "Ruleset $id already exists: updating it."
        Write-Host "Not the first run: the window starts at the first run's 'Main before the ruleset' sha."
        gh api -X PUT "repos/$repo/rulesets/$id" --input $body --silent
        if ($LASTEXITCODE -ne 0) { Write-Host "Updating ruleset $id failed (see the message above). The ruleset may be unchanged. Send this output to the team."; exit 1 }
    }
}

# R1 first, then R2 (L-b): with R1 on nobody pushes main directly, so from now on main changes only by a merged
# pull request, and main's sha read just before R1 was written is where the window of runbook 4.7.1 starts. R2
# governs creating and approving pull requests, not merging them, so the start does not rely on R2 being off. Then the push job's
# GITHUB_TOKEN may open and merge its data pull request.
$r2 = (gh api "repos/$repo/actions/permissions/workflow" --jq '.can_approve_pull_request_reviews') -join ''
if ($r2 -eq 'true') {
    Write-Host 'R2 already on'
} elseif ($r2 -eq 'false') {
    gh api -X PUT "repos/$repo/actions/permissions/workflow" -F can_approve_pull_request_reviews=true --silent
    if ($LASTEXITCODE -ne 0) { Write-Host 'Turning on "Allow GitHub Actions to create and approve pull requests" failed (see above); the ruleset is written. Send this output to the team.'; exit 1 }
    Write-Host "R2 was off; main was $mainSha"
} else {
    Write-Host "Could not read Allow GitHub Actions to create and approve pull requests ('$r2'); it was not changed (the ruleset is written). Send this output to the team."; exit 1
}

# The checks of step 2.0.
$rules = (@(gh api "repos/$repo/rules/branches/main" --jq '.[].type') | Sort-Object -Unique) -join ','
$ok = $rules -eq 'deletion,non_fast_forward,pull_request'
Write-Host "Rules on main: $rules"
$prs = (gh api "repos/$repo/actions/permissions/workflow" --jq '.can_approve_pull_request_reviews') -join ''
Write-Host "GitHub Actions may create pull requests: $prs"
if ($prs -ne 'true') { $ok = $false }
# main-protect L-D: auto-merge merges whatever head a branch has later, unreviewed; it stays off.
$auto = (gh api "repos/$repo" --jq '.allow_auto_merge') -join ''
Write-Host "Auto-merge allowed: $auto"
if ($auto -ne 'false') { Write-Host 'Auto-merge must be off: Settings > General > Pull Requests > untick Allow auto-merge.'; $ok = $false }
$found = @(gh api "repos/$repo/rulesets" --jq $find | Where-Object { $_ })
if ($found.Count -eq 0) { Write-Host 'No ruleset named main: pull request required found after writing it.'; $ok = $false }
foreach ($id in $found) {
    $enf = (gh api "repos/$repo/rulesets/$id" --jq '.enforcement') -join ''
    $actors = (@(gh api "repos/$repo/rulesets/$id" --jq '.bypass_actors[] | [.actor_type, .actor_id, .bypass_mode] | @tsv') |
               ForEach-Object { $_ -replace "`t", ':' }) -join ','
    # ADR 0010 (R1'): code-owner review on, squash only. jq's // would turn false into empty, so select() instead.
    $owner = (@(gh api "repos/$repo/rulesets/$id" --jq '.rules[].parameters | select(. != null) | .require_code_owner_review')) -join ','
    $methods = (@(gh api "repos/$repo/rulesets/$id" --jq '.rules[].parameters | select(. != null) | .allowed_merge_methods[]?')) -join ','
    # main-protect L-E: approvals stay 0 (a workflow's approval would count toward any number above 0; ADR 0009).
    $appr = (@(gh api "repos/$repo/rulesets/$id" --jq '.rules[].parameters.required_approving_review_count // empty')) -join ','
    $shown = if ($actors) { $actors } else { 'none' }
    Write-Host "Ruleset ${id}: $enf, bypass $shown, required approvals $appr"
    Write-Host "Code-owner review: $owner, merge methods: $methods"
    if ($enf -cne 'active') { $ok = $false }
    # ADR 0010: exactly one bypass, the Repository admin role (id 5), for pull requests only (nobody pushes main).
    if ($actors -cne 'RepositoryRole:5:pull_request') { Write-Host 'The bypass must be exactly the admin role in pull request mode (RepositoryRole:5:pull_request).'; $ok = $false }
    if ($owner -cne 'true') { Write-Host 'Code-owner review must be on (ADR 0010).'; $ok = $false }
    if ($methods -cne 'squash') { Write-Host 'Squash must be the only merge method (ADR 0010).'; $ok = $false }
    if ($appr -ne '0') { Write-Host 'Required approvals must be 0 (raising them needs ADR 0009 changed first: a workflow approval would count).'; $ok = $false }
}
if ($ok) {
    Write-Host 'OK: main is protected. Next: Actions > Daily update > Run workflow (the check run of step 2.0).'
} else {
    Write-Host 'NOT OK: expected rules deletion,non_fast_forward,pull_request, active, bypass RepositoryRole:5:pull_request only, required approvals 0, code-owner review on, squash only, auto-merge off, and Actions may create pull requests.'
    Write-Host 'Send this output to the team.'
    exit 1
}
