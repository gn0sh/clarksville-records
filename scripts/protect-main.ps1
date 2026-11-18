# Protect main (ADR 0011 decisions 5-6; docs/tasks/data-off-main.md D1; consumer rows R1, R-D, R2, S1). Brian runs
# this one; scripts/protect-main.sh is its tested bash twin (same writes, same checks, same lines). Brian's PC only:
# every ruleset and settings write is his (U3-0 = no), and the team proxy refuses several of the reads below, so it
# refuses to run in a cloud session or CI.
#
# Writes (each ruleset is created, or updated if one of that name exists; never a second one):
#   R1''  scripts\main-ruleset.json         main: 2 approvals, last-push approval, no code-owner review, squash only,
#                                           bypass = the admin role in pull_request mode
#   R-D   scripts\records-data-ruleset.json records-data: no deletion, no force push, no bypass
#   R-T   scripts\main-tag-ruleset.json     a tag named main: no creating, updating or deleting it (finding F2)
#   R2    "Allow GitHub Actions to create and approve pull requests" turned OFF (load-bearing for R1'')
# Then it reads everything back. OK only if: each ruleset reads back equal to its file, main's rules are deletion,
# non_fast_forward and one pull_request rule with 2 approvals and no code-owner review, R2 is off, auto-merge is off,
# gn0sh is the only writer (no other collaborator or pending invitation with write or more, no App installed on
# gn0sh's account with contents or administration write that reaches this repository, no deploy key with write:
# finding F1), and both environments (github-pages, morning-note) allow exactly one custom policy, main, of type
# branch (F2). Any refused or failed read is NOT OK, never skipped (the review's "settings drift").
# Run it after any settings change and right before MAIN_PR_BASELINE is set; it must print OK.
# Prints "Main before the rulesets: <sha>" first (main read before any write). Exit 0 OK, 1 refused or NOT OK.
#
# Needs: GitHub CLI (winget install GitHub.cli), signed in as gn0sh: gh auth login
# Run (PowerShell, in the repository folder):
#   powershell -NoProfile -File scripts\protect-main.ps1   (local scripts are allowed in Settings > For developers; never -ExecutionPolicy Bypass)
#   -Check: no writes, only the checks (for a settings-drift re-check, or a dry look before the cutover).
#   -Apps <names>|none: no token Brian holds can list installed GitHub Apps (user/installations needs a GitHub App
#   token: HTTP 403 for gh's OAuth token, 2026-11-18), so Brian reads https://github.com/settings/installations and
#   passes the Apps that can write this repository (or none). Without -Apps that check is NOT OK, never a silent pass.
#   Only the Claude App ($allowedApp, through which the team pushes branches) may be listed: one App adds at most one
#   approving identity, so 2 approvals stay out of reach with R2 off, and no App may hold Administration write (it
#   could edit the rulesets). That no App can bypass R1'', R-D or R-T is read, not confirmed: the bypass lists must
#   equal the files.
# No double quotes are passed to gh (Windows PowerShell 5.1 mangles them): strings come in through $ENV.
param([switch]$Check, [string]$Apps = '')
$ErrorActionPreference = 'Continue'   # 'Stop' turns gh's stderr into errors in PowerShell 5.1; exit codes are checked
$repo = 'gn0sh/clarksville-records'
$owner = 'gn0sh'
$allowedApp = 'claude'
$appsGiven = $PSBoundParameters.ContainsKey('Apps')
$env:PM_OWNER = $owner
$env:PM_REPO = $repo
$env:PM_PR = 'pull_request'
$env:PM_WRITE = 'write'
$env:PM_READ = 'read'
$env:PM_TRIAGE = 'triage'
$utf8 = New-Object Text.UTF8Encoding $false
foreach ($v in @('CLAUDE_CODE_REMOTE', 'GITHUB_ACTIONS', 'CI')) {
    if ([Environment]::GetEnvironmentVariable($v)) {
        Write-Host "REFUSED: $v is set. protect-main runs only from Brian's PC (ruleset and settings writes are his). Nothing was changed."
        exit 1
    }
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host 'GitHub CLI not found. Install it (winget install GitHub.cli), run gh auth login, then run this again.'
    exit 1
}
gh auth status *> $null
if ($LASTEXITCODE -ne 0) { Write-Host "Not signed in: run gh auth login (as $owner). Nothing was changed."; exit 1 }

# The one whitelist (the same as scripts\u3-toggle.ps1): every comparison goes through it.
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

$sets = @(@('R1''''', 'main-ruleset.json'), @('R-D', 'records-data-ruleset.json'), @('R-T', 'main-tag-ruleset.json'))
foreach ($s in $sets) {
    $o = ReadJsonFile (Join-Path $PSScriptRoot $s[1])
    if ($null -eq $o -or [string]::IsNullOrEmpty([string]$o.name)) { Write-Host "Could not read scripts\$($s[1]). Nothing was changed."; exit 1 }
}
function Stop-Run($why) {
    Write-Host $why
    Write-Host 'NOT OK: stopped before the checks. Run this again; send this output to the team if it repeats.'
    exit 1
}
# the ids of the rulesets with this file's name (any target); $null if the list could not be read
function IdsOf($file) {
    $env:PM_NAME = [string](ReadJsonFile $file).name
    $ids = @(gh api --paginate "repos/$repo/rulesets?per_page=100" --jq '.[] | select(.name == $ENV.PM_NAME) | .id' | Where-Object { $_ })
    if ($LASTEXITCODE -ne 0) { return $null }
    return ,$ids
}

# ---------------------------------------------------------------------------------------------- writes
if ($Check) {
    Write-Host 'CHECK ONLY: nothing is written; the checks below read the live settings.'
} else {
    # main is read before anything is written, so the printed sha is where main stood when protection began.
    $mainSha = (gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha') -join ''
    if ($LASTEXITCODE -ne 0 -or $mainSha -cnotmatch '^[0-9a-f]{40}$') {
        Write-Host "Could not read main's commit. Nothing was changed. Run this again; send this output to the team if it repeats."; exit 1
    }
    Write-Host "Main before the rulesets: $mainSha"
    foreach ($s in $sets) {
        $label = $s[0]; $file = Join-Path $PSScriptRoot $s[1]
        $ids = IdsOf $file
        if ($null -eq $ids) { Stop-Run "Could not list the rulesets (signed in as ${owner}?). $label was not written." }
        if ($ids.Count -eq 0) {
            Write-Host "${label}: no ruleset yet, creating it from scripts\$($s[1])."
            gh api -X POST "repos/$repo/rulesets" --input $file --silent
            if ($LASTEXITCODE -ne 0) { Stop-Run "Creating $label failed (see the message above)." }
        } else {
            foreach ($id in $ids) {
                Write-Host "${label}: ruleset $id exists, updating it from scripts\$($s[1])."
                gh api -X PUT "repos/$repo/rulesets/$id" --input $file --silent
                if ($LASTEXITCODE -ne 0) { Stop-Run "Updating $label (ruleset $id) failed (see the message above); it may be unchanged." }
            }
        }
    }
    $r2 = (gh api "repos/$repo/actions/permissions/workflow" --jq '.can_approve_pull_request_reviews') -join ''
    if ($LASTEXITCODE -ne 0) { $r2 = '' }
    if ($r2 -ceq 'false') {
        Write-Host 'R2 already off'
    } elseif ($r2 -ceq 'true') {
        gh api -X PUT "repos/$repo/actions/permissions/workflow" -F can_approve_pull_request_reviews=false --silent
        if ($LASTEXITCODE -ne 0) { Stop-Run "Turning off 'Allow GitHub Actions to create and approve pull requests' (R2) failed (see above); the rulesets are written." }
        Write-Host 'R2 was on: turned off'
    } else {
        Stop-Run "Could not read 'Allow GitHub Actions to create and approve pull requests' (R2) ('$r2'); it was not changed (the rulesets are written)."
    }
}

# ---------------------------------------------------------------------------------------------- checks
$script:problems = 0
function Problem($why) { Write-Host "  NOT OK: $why"; $script:problems++ }
function Unread($what) { Problem "could not read $what (a refused or failed read counts as NOT OK)" }
# every line of a gh read, or $null if the read failed (a refused read is never an empty answer)
function Lines([string]$path, [string]$jq, [switch]$Paginate) {
    if ($Paginate) { $out = @(gh api --paginate $path --jq $jq | Where-Object { $_ -ne '' }) }
    else { $out = @(gh api $path --jq $jq | Where-Object { $_ -ne '' }) }
    if ($LASTEXITCODE -ne 0) { return $null }
    return ,$out
}
function SameAs($live, $expected, $label) {
    $x = Extras $live
    if ($x) { Write-Host "  The ruleset has fields this script does not write: $x"; return $false }
    $a = CanonRs $live
    $b = CanonRs $expected
    if ($a -ceq $b) { return $true }
    Write-Host "  It differs from ${label}:"
    Write-Host "    expected: $b"
    Write-Host "    live:     $a"
    return $false
}
foreach ($s in $sets) {
    $label = $s[0]; $file = Join-Path $PSScriptRoot $s[1]
    $ids = IdsOf $file
    if ($null -eq $ids) { Unread 'the rulesets'; continue }
    if ($ids.Count -ne 1) { Problem "${label}: $($ids.Count) rulesets named '$((ReadJsonFile $file).name)', expected exactly 1"; continue }
    $id = $ids[0]
    $raw = (gh api "repos/$repo/rulesets/$id" 2> $null) -join "`n"
    $live = $null
    if ($LASTEXITCODE -eq 0) { try { $live = $raw | ConvertFrom-Json } catch { $live = $null } }
    if ($null -eq $live -or $null -eq $live.id) { Unread "ruleset $id ($label)"; continue }
    if (SameAs $live (ReadJsonFile $file) $s[1]) { Write-Host "${label}: ruleset $id matches scripts\$($s[1])" }
    else { Problem "${label}: ruleset $id does not match scripts\$($s[1])" }
}

$rules = Lines "repos/$repo/rules/branches/main" '.[].type'
if ($null -eq $rules) { Unread 'the rules on main' } else {
    $rules = (@($rules | Sort-Object -Unique)) -join ','
    Write-Host "Rules on main: $rules"
    if ($rules -cne 'deletion,non_fast_forward,pull_request') { Problem "main's rules must be deletion,non_fast_forward,pull_request" }
}
# every pull_request rule on main, from any ruleset: exactly one, 2 approvals, no code-owner review (CODEOWNERS is gone)
$prr = Lines "repos/$repo/rules/branches/main" '.[] | select(.type == $ENV.PM_PR) | [(.parameters.required_approving_review_count|tostring), (.parameters.require_code_owner_review|tostring)] | @tsv'
if ($null -eq $prr) { Unread "main's pull_request rules" } else {
    Write-Host ('Pull request rules on main (approvals, code-owner review): ' + ((@($prr | ForEach-Object { $_ -replace "`t", ' ' })) -join ';'))
    if ($prr.Count -ne 1 -or $prr[0] -cne "2`tfalse") { Problem 'main needs exactly one pull_request rule, with 2 approvals and no code-owner review' }
}

$r2 = (gh api "repos/$repo/actions/permissions/workflow" --jq '.can_approve_pull_request_reviews') -join ''
if ($LASTEXITCODE -ne 0) { $r2 = 'unread' }
Write-Host "GitHub Actions may create and approve pull requests (R2): $r2"
if ($r2 -ceq 'true') { Problem 'R2 is on: with R2 on, gn0sh plus the bot can approve a pull request (ADR 0011 decision 6)' }
elseif ($r2 -cne 'false') { Unread 'R2 (actions/permissions/workflow)' }
$auto = (gh api "repos/$repo" --jq '.allow_auto_merge') -join ''
if ($LASTEXITCODE -ne 0) { $auto = 'unread' }
Write-Host "Auto-merge allowed: $auto"
if ($auto -ceq 'true') { Problem 'auto-merge must be off: Settings > General > Pull Requests > untick Allow auto-merge' }
elseif ($auto -cne 'false') { Unread 'the repository settings (allow_auto_merge)' }

# finding F1: gn0sh the only writer
$w = Lines "repos/$repo/collaborators?affiliation=all&per_page=100" '.[] | select(.permissions.admin or .permissions.maintain or .permissions.push) | .login' -Paginate
if ($null -eq $w) { Unread 'the collaborators' } else {
    $w = (@($w | Sort-Object -Unique)) -join ','
    Write-Host ('Collaborators with write or more: ' + $(if ($w) { $w } else { 'none' }))
    if ($w -cne $owner) { Problem "the collaborators with write or more must be exactly $owner" }
}
$inv = Lines "repos/$repo/invitations?per_page=100" '.[] | select(.permissions != $ENV.PM_READ and .permissions != $ENV.PM_TRIAGE) | [(.invitee.login // (.id|tostring)), .permissions] | @tsv' -Paginate
if ($null -eq $inv) { Unread 'the pending invitations' } else {
    $inv = (@($inv | ForEach-Object { $_ -replace "`t", ':' })) -join ','
    Write-Host ('Pending invitations with write or more: ' + $(if ($inv) { $inv } else { 'none' }))
    if ($inv) { Problem "a pending invitation with write or more: $inv" }
}
# installed Apps: confirmed by hand (-Apps), never read (no read an OAuth token can make lists them)
if (-not $appsGiven) {
    Write-Host 'Installed Apps with write on this repository: not confirmed'
    Problem "installed Apps can't be read with this token (GitHub's user/installations needs a GitHub App token), so confirm them by hand: open https://github.com/settings/installations, click Configure on each App, and note each one that reaches clarksville-records (All repositories, or listed) with any Read and write permission. Then run this again with -Apps claude or -Apps none (one value; any other App must first lose its access to clarksville-records, or the team amends ADR 0011). Only $allowedApp may be listed, and only if its Administration permission is not Read and write"
} elseif ($Apps -cnotmatch '^(none|[a-z0-9][a-z0-9-]*(,[a-z0-9][a-z0-9-]*)*)$') {
    Write-Host "Installed Apps with write on this repository: '$Apps' (not claude or none)"
    Problem "-Apps takes one value, claude or none ('$Apps' is not one; typed at a PowerShell prompt, a,b arrives as 'a b')"
} else {
    $today = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd')
    Write-Host "Installed Apps with write on this repository: $Apps (confirmed by hand by $owner on $today, not read by this script; none with Administration write)"
    if ($Apps -cne 'none' -and $Apps -cne $allowedApp) {
        Problem "an installed App other than $allowedApp alone can write this repository ($Apps): remove its access to clarksville-records, or the team amends ADR 0011 first"
    }
}
$keys = Lines "repos/$repo/keys?per_page=100" '.[] | select(.read_only != true) | [(.id|tostring), .title] | @tsv' -Paginate
if ($null -eq $keys) { Unread 'the deploy keys' } else {
    $keys = (@($keys | ForEach-Object { $_ -replace "`t", ':' })) -join ','
    Write-Host ('Deploy keys with write: ' + $(if ($keys) { $keys } else { 'none' }))
    if ($keys) { Problem "a deploy key with write: $keys" }
}

# finding F2: each environment deploys from main only, by a branch-type policy (a tag named main is not main)
foreach ($envName in @('github-pages', 'morning-note')) {
    $pol = Lines "repos/$repo/environments/$envName" '.deployment_branch_policy | [(.protected_branches|tostring), (.custom_branch_policies|tostring)] | @tsv'
    if ($null -eq $pol) { Unread "environment $envName" } else {
        Write-Host ("Environment $envName (protected branches, custom policies): " + ((@($pol) -join ';') -replace "`t", ' '))
        if ($pol.Count -ne 1 -or $pol[0] -cne "false`ttrue") { Problem "environment $envName must use custom deployment policies only (not protected branches, not all)" }
    }
    $bp = Lines "repos/$repo/environments/$envName/deployment-branch-policies?per_page=100" '.branch_policies[] | [.name, (.type|tostring)] | @tsv' -Paginate
    if ($null -eq $bp) { Unread "environment $envName's deployment policies" } else {
        $shown = (@($bp | ForEach-Object { $_ -replace "`t", ':' })) -join ','
        Write-Host ("Environment $envName policies: " + $(if ($shown) { $shown } else { 'none' }))
        if ($bp.Count -ne 1 -or $bp[0] -cne "main`tbranch") { Problem "environment $envName must allow exactly main, of type branch" }
    }
}

if ($script:problems -eq 0) {
    Write-Host "OK: main is protected (R1'', R-D, R-T as written, R2 off, auto-merge off, $owner the only writer, both environments main only)."
    exit 0
}
Write-Host "NOT OK: $($script:problems) problem(s) above. Run this from Brian's PC, signed in as $owner. Send this output to the team."
exit 1
