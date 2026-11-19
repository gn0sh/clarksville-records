# Protect main (ADR 0011 decisions 5-6; docs/tasks/data-off-main.md D1; consumer rows R1, R-D, R2, S1). Brian runs
# this one; scripts/protect-main.sh is its tested bash twin (same writes, same checks, same lines). Brian's PC only:
# every ruleset and settings write is his (U3-0 = no), and the team proxy refuses several of the reads below, so it
# refuses to run in a cloud session or CI.
#
# Writes (each ruleset is created, or updated if one of that name exists; never a second one):
#   R1''  scripts\main-ruleset.json         main: 10 approvals (API max), last-push approval, no code-owner review, squash only,
#                                           bypass = the admin role in pull_request mode
#   R-D   scripts\records-data-ruleset.json records-data: no deletion, no force push, no bypass
#   R-T   scripts\main-tag-ruleset.json     a tag named main: no creating, updating or deleting it (finding F2)
#   R2    "Allow GitHub Actions to create and approve pull requests" turned OFF (load-bearing for R1'')
# Then it reads everything back. OK only if: each ruleset reads back equal to its file, main's rules are deletion,
# non_fast_forward and one pull_request rule with 10 approvals and no code-owner review, R2 is off, auto-merge is off,
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
#   -Main <sha>: main's commit as the caller just merged it (cutover step 5): main's ref is read until it is <sha>
#   (read-after-write row 10), and main's .github/workflows/ files are read at <sha>, never at a lagging ?ref=main (a
#   failed read there is "not yet": up to 10 reads, 3 s apart; a sha never changes, so the first read that works holds).
# After this run's own writes, each read that confirms one (the rulesets, main's rules, R2 if this run turned it off)
#   is read until it shows what was written (up to 10 reads, 3 s apart: docs/architecture/read-after-write-invariant.md);
#   with -Check every read is read once.
# Main's .github/workflows/daily-update.yml is read too (ADR 0011 row J2, I-prov): after the cutover it must run the
#   gate step ("Check main's history and the records-data head") in job gate and only there, push must need gate,
#   push must be the only job with attestations: write (only J2 stores attestations) and with contents: write, no job
#   may hold pull-requests: write or set its permissions inline, and the workflow's own permissions are {}.
#   -PreCutover: cutover step 4 only, before the cutover merge. Main must then still hold the old step
#   "Open and merge the data pull request", and the post-cutover checks wait for the next run without it.
#   -Apps <names>|none: no token Brian holds can list installed GitHub Apps (user/installations needs a GitHub App
#   token: HTTP 403 for gh's OAuth token, 2026-11-18), so Brian reads https://github.com/settings/installations and
#   passes the Apps that can write this repository (or none). Without -Apps that check is NOT OK, never a silent pass.
#   Only the Claude App ($allowedApp, through which the team pushes branches) may be listed. With R2 off it is then
#   the only approver besides gn0sh, so R1'''s required approvals (the ruleset maximum, 10, S1-1) can't be met
#   without gn0sh (invariant I-person, ADR 0011 Amendment 2026-11-18 (b): at most one non-gn0sh approver counts; two
#   Apps, or R2 on plus one, would make 2 without gn0sh). No App may hold Administration write (it could edit the rulesets) or bypass, and only J2 on main stores
#   attestations. Nor may it hold Variables, Secrets or Environments write (S1-2: it could set MORNING_NOTE_SEND or
#   RECORDS_DEPLOY_ENABLED, or change an environment's policy); -Apps claude is Brian's answer that all four are not
#   Read and write, and any other answer is NOT OK. That no App can bypass R1'', R-D or R-T is read, not confirmed:
#   the bypass lists must equal the files. R1'' asks for 10 approvals, the ruleset API maximum (S1-1), so gn0sh plus
#   one App can't reach it either: every merge is a gn0sh bypass, and rule 1 no longer rests on the COMMENT-only rule.
# Also read (S1-6, S1-7): GitHub Pages must build from a workflow (build_type workflow, so nothing publishes outside
#   daily-update's gate), and .github/workflows/ on main must hold daily-update.yml and nothing else.
# No double quotes are passed to gh (Windows PowerShell 5.1 mangles them): strings come in through $ENV.
# named parameters only: an unknown or .sh-style argument (--check) stops here, never binds to a parameter by position
# (data-off-main/ps-unknown-args)
[CmdletBinding(PositionalBinding = $false)]
param([switch]$Check, [switch]$PreCutover, [string]$Apps = '', [string]$Main = '')
$ErrorActionPreference = 'Continue'   # 'Stop' turns gh's stderr into errors in PowerShell 5.1; exit codes are checked
$repo = 'gn0sh/clarksville-records'
$owner = 'gn0sh'
$allowedApp = 'claude'
$appsGiven = $PSBoundParameters.ContainsKey('Apps')
if ($PSBoundParameters.ContainsKey('Main') -and $Main -cnotmatch '^[0-9a-f]{40}$') {
    Write-Host "-Main takes main's full 40-hex commit sha ('$Main' is not one). Nothing was changed."
    exit 1
}
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
function IdsLine($file) {   # the ids as one string (sorted, joined by ','; rule 5), or $null if the list could not be read
    $x = IdsOf $file
    if ($null -eq $x) { return $null }
    return ((@(@($x | ForEach-Object { [string]$_ }) | Sort-Object)) -join ',')
}
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
    $wrote = @()   # per ruleset, in the order of $sets: the ids this run wrote, as IdsLine returns them
    foreach ($s in $sets) {
        $label = $s[0]; $file = Join-Path $PSScriptRoot $s[1]
        $ids = IdsOf $file
        if ($null -eq $ids) { Stop-Run "Could not list the rulesets (signed in as ${owner}?). $label was not written." }
        if ($ids.Count -eq 0) {
            Write-Host "${label}: no ruleset yet, creating it from scripts\$($s[1])."
            # a 2xx write is its own read (read-after-write rule 6): the new id comes from the answer, not from a list
            $newId = (gh api -X POST "repos/$repo/rulesets" --input $file --jq '.id') -join "`n"
            if ($LASTEXITCODE -ne 0) { Stop-Run "Creating $label failed (see the message above)." }
            if ($newId -cnotmatch '^[0-9]+$') { Stop-Run "Creating ${label}: GitHub's answer names no ruleset id ('$newId'); check Settings > Rules > Rulesets." }
            $wrote += $newId
        } else {
            foreach ($id in $ids) {
                Write-Host "${label}: ruleset $id exists, updating it from scripts\$($s[1])."
                gh api -X PUT "repos/$repo/rulesets/$id" --input $file --silent
                if ($LASTEXITCODE -ne 0) { Stop-Run "Updating $label (ruleset $id) failed (see the message above); it may be unchanged." }
            }
            $wrote += ((@(@($ids | ForEach-Object { [string]$_ }) | Sort-Object)) -join ',')
        }
    }
    $r2 = (gh api "repos/$repo/actions/permissions/workflow" --jq '.can_approve_pull_request_reviews') -join ''
    if ($LASTEXITCODE -ne 0) { $r2 = '' }
    if ($r2 -ceq 'false') {
        Write-Host 'R2 already off'
    } elseif ($r2 -ceq 'true') {
        gh api -X PUT "repos/$repo/actions/permissions/workflow" -F can_approve_pull_request_reviews=false --silent
        if ($LASTEXITCODE -ne 0) { Stop-Run "Turning off 'Allow GitHub Actions to create and approve pull requests' (R2) failed (see above); the rulesets are written." }
        $r2Put = $true
        Write-Host 'R2 was on: turned off'
    } else {
        Stop-Run "Could not read 'Allow GitHub Actions to create and approve pull requests' (R2) ('$r2'); it was not changed (the rulesets are written)."
    }
}

# ---------------------------------------------------------------------------------------------- checks
$script:problems = 0
function Problem($why) { Write-Host "  NOT OK: $why"; $script:problems++ }
function Unread($what) { Problem "could not read $what (a refused or failed read counts as NOT OK)" }
# a read that confirms this run's writes waits for them (ReadUntil); -Check reads once. Sets $script:readLast.
function Settled([string]$what, [string]$want, [scriptblock]$read) {
    if ($Check) { $script:readLast = & $read; return }
    $null = ReadUntil $what $want $read
}
function MainRef {   # main's commit, or $null on a failed read
    $v = (gh api "repos/$repo/git/ref/heads/main" --jq '.object.sha') -join "`n"
    if ($LASTEXITCODE -ne 0) { return $null }
    return $v
}
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
function LiveWl([string]$id) {   # the live ruleset into $script:liveRs, returned whitelisted; $null if unread
    $script:liveRs = $null
    $raw = (gh api "repos/$repo/rulesets/$id" 2> $null) -join "`n"
    if ($LASTEXITCODE -ne 0) { return $null }
    try { $o = $raw | ConvertFrom-Json } catch { return $null }
    if ($null -eq $o -or $null -eq $o.id) { return $null }
    $script:liveRs = $o
    return (CanonRs $o)
}
$k = 0
foreach ($s in $sets) {
    $label = $s[0]; $file = Join-Path $PSScriptRoot $s[1]
    $wantIds = ''
    if (-not $Check -and $k -lt @($wrote).Count) { $wantIds = [string]@($wrote)[$k] }
    $k++
    $name = [string](ReadJsonFile $file).name
    # read-after-write row 4: after a POST a lagging list shows no id, after a PUT a lagging GET the old body
    $script:rsFile = $file
    Settled "${label}: the rulesets named '$name'" $wantIds { IdsLine $script:rsFile }
    if ($null -eq $script:readLast) { Unread 'the rulesets'; continue }
    $idsText = [string]$script:readLast
    if (-not $Check -and $idsText -cne $wantIds) { Problem "${label}: the rulesets named '$name' read '$idsText', not the ruleset this run wrote ($wantIds)"; continue }
    $ids = @($idsText -split ',' | Where-Object { $_ })
    if ($ids.Count -ne 1) { Problem "${label}: $($ids.Count) rulesets named '$name', expected exactly 1"; continue }
    $id = $ids[0]
    $script:rsId = $id
    Settled "${label}: ruleset $id" (CanonRs (ReadJsonFile $file)) { LiveWl $script:rsId }
    $live = $script:liveRs
    if ($null -eq $script:readLast -or $null -eq $live) { Unread "ruleset $id ($label)"; continue }
    if (SameAs $live (ReadJsonFile $file) $s[1]) { Write-Host "${label}: ruleset $id matches scripts\$($s[1])" }
    else { Problem "${label}: ruleset $id does not match scripts\$($s[1])" }
}

function MainTypes {   # the rule types on main, sorted and joined by ','; $null if unread
    $t = Lines "repos/$repo/rules/branches/main" '.[].type'
    if ($null -eq $t) { return $null }
    return ((@($t | Sort-Object -Unique)) -join ',')
}
function MainPrr {   # main's pull_request rules, one line each joined by "`n"; $null if unread
    $t = Lines "repos/$repo/rules/branches/main" '.[] | select(.type == $ENV.PM_PR) | [(.parameters.required_approving_review_count|tostring), (.parameters.require_code_owner_review|tostring)] | @tsv'
    if ($null -eq $t) { return $null }
    return (@($t) -join "`n")
}
# read-after-write row 5: main's rules come from every active ruleset, so each listing must equal the whole expected
# string (a view while the rulesets propagate never matches)
Settled 'Rules on main' 'deletion,non_fast_forward,pull_request' { MainTypes }
$rules = $script:readLast
if ($null -eq $rules) { Unread 'the rules on main' } else {
    Write-Host "Rules on main: $rules"
    if ($rules -cne 'deletion,non_fast_forward,pull_request') { Problem "main's rules must be deletion,non_fast_forward,pull_request" }
}
# every pull_request rule on main, from any ruleset: exactly one, 10 approvals (the ruleset API maximum,
# S1-1 main-protect/approval-margin: GitHub's schema repository-rule-pull-request caps it at 10), no code-owner review
# (CODEOWNERS is gone)
Settled 'Pull request rules on main' "10`tfalse" { MainPrr }
$prr = $script:readLast
if ($null -eq $prr) { Unread "main's pull_request rules" } else {
    Write-Host ('Pull request rules on main (approvals, code-owner review): ' + (([string]$prr -replace "`t", ' ') -replace "`n", ';'))
    if ([string]$prr -cne "10`tfalse") { Problem 'main needs exactly one pull_request rule, with 10 approvals (the ruleset API maximum) and no code-owner review' }
}

function R2Read {   # R2's value, or $null on a failed read
    $v = (gh api "repos/$repo/actions/permissions/workflow" --jq '.can_approve_pull_request_reviews') -join "`n"
    if ($LASTEXITCODE -ne 0) { return $null }
    return $v
}
# read-after-write row 2: the PUT ran only after a read of true, so a lagging read says true and is never accepted
if ($r2Put) { $null = ReadUntil 'R2' 'false' { R2Read } } else { $script:readLast = R2Read }
$r2 = $script:readLast
if ($null -eq $r2) { $r2 = 'unread' }
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
    Problem "installed Apps can't be read with this token (GitHub's user/installations needs a GitHub App token), so confirm them by hand: open https://github.com/settings/installations, click Configure on each App, and note each one that reaches clarksville-records (All repositories, or listed) with any Read and write permission. Then run this again with -Apps claude or -Apps none (one value; any other App must first lose its access to clarksville-records, or the team amends ADR 0011). Only $allowedApp may be listed, and only if none of its Administration, Variables, Secrets and Environments permissions is Read and write (any other answer is NOT OK)"
} elseif ($Apps -cnotmatch '^(none|[a-z0-9][a-z0-9-]*(,[a-z0-9][a-z0-9-]*)*)$') {
    Write-Host "Installed Apps with write on this repository: '$Apps' (not claude or none)"
    Problem "-Apps takes one value, claude or none ('$Apps' is not one; typed at a PowerShell prompt, a,b arrives as 'a b')"
} else {
    $today = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd')
    Write-Host "Installed Apps with write on this repository: $Apps (confirmed by hand by $owner on $today, not read by this script; none with Administration, Variables, Secrets or Environments write)"
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

# S1-6 main-protect/pages-source-unchecked: Pages builds only from a workflow (a branch source would publish outside
# every gate); a refused read, or Pages off, is NOT OK
$pages = Lines "repos/$repo/pages" '.build_type // empty'
if ($null -eq $pages) { Unread "the GitHub Pages settings (repos/$repo/pages)" } else {
    $pg = (@($pages)) -join ','
    Write-Host ('GitHub Pages build type: ' + $(if ($pg) { $pg } else { 'none' }))
    if ($pg -cne 'workflow') { Problem ("GitHub Pages must build from a workflow (build_type workflow, Settings > Pages > Source: GitHub Actions), not '" + $(if ($pg) { $pg } else { 'none' }) + "'") }
}
# read-after-write row 10 (-Main <sha>, cutover step 5): main's ref read until it is <sha>, and main's workflow files
# read at <sha>, never at a lagging ?ref=main
$wref = 'main'; $tries = 1
if ($Main) {
    if (ReadUntil 'main' $Main { MainRef }) { Write-Host "Main: $Main (-Main); its workflow files are read at that commit." }
    elseif ($null -ne $script:readLast) { Problem "main is at '$($script:readLast)', not $Main (-Main)" }
    else { Unread "main's commit (git/ref/heads/main)" }
    $wref = $Main; $tries = 10
}
# S1-7 main-protect/wf-shape-heuristic: daily-update.yml is the only workflow on main (any other file there runs with
# the environments and never meets daily-update's gate)
$wfs = $null
for ($i = 1; $i -le $tries; $i++) {   # one read, or with -Main up to 10, 3 s apart, until one works (a sha never changes)
    $wfs = Lines "repos/$repo/contents/.github/workflows?ref=$wref" '.[] | [.name, .type] | @tsv'
    if ($null -ne $wfs) { break }
    if ($i -lt $tries) { Start-Sleep -Seconds 3 }
}
if ($null -eq $wfs) { Unread "main's .github/workflows/ folder" } else {
    Write-Host ("Main's .github/workflows/: " + ((@($wfs | ForEach-Object { $_ -replace "`t", ':' })) -join ','))
    if ($wfs.Count -ne 1 -or $wfs[0] -cne "daily-update.yml`tfile") { Problem "main's .github/workflows/ must hold daily-update.yml and nothing else" }
}

# main's daily-update.yml (ADR 0011 row J2, I-prov): the post-cutover shape, or with -PreCutover the old one
$gateStep = "Check main's history and the records-data head"
$oldStep = 'Open and merge the data pull request'
# lists are job names joined by commas. Comment lines and trailing comments are dropped.
function WfShape($lines) {
    $r = [ordered]@{ top = ''; gate = @(); attw = @(); contw = @(); prw = @(); inl = @(); oldpr = @(); pn = '' }
    $inJobs = $false
    $job = ''
    foreach ($raw in $lines) {
        $ln = ([string]$raw).TrimEnd("`r")
        if ($ln -cmatch '^[ \t]*#') { continue }
        $ln = ($ln -creplace '[ \t]+#.*$', '') -creplace '[ \t]+$', ''
        if ($ln -cmatch '^[^ \t]') { $inJobs = ($ln -cmatch '^jobs:$') }
        if ($ln -cmatch '^permissions:') { $r.top = $ln }
        if (-not $inJobs) { continue }
        if ($ln -cmatch '^  ([A-Za-z0-9_-]+):$') { $job = $Matches[1]; continue }
        if ($ln -cmatch '^[ \t]+attestations:[ \t]*write$') { $r.attw += $job }
        if ($ln -cmatch '^[ \t]+contents:[ \t]*write$') { $r.contw += $job }
        if ($ln -cmatch '^[ \t]+pull-requests:[ \t]*write$') { $r.prw += $job }
        if ($ln -cmatch '^    permissions:[ \t]*[^ \t]' -and $ln -cnotmatch '^    permissions:[ \t]*[{][}]$') { $r.inl += $job }
        if ($ln -cmatch '^[ \t]+(- )?name:[ \t]*(.*)$') {
            $n = $Matches[2]
            if ($n -ceq $gateStep) { $r.gate += $job }
            if ($n -ceq $oldStep) { $r.oldpr += $job }
        }
        if ($job -ceq 'push' -and $ln -cmatch '^    needs:[ \t]*(.*)$') { $r.pn = $Matches[1] }
    }
    foreach ($k in @('gate', 'attw', 'contw', 'prw', 'inl', 'oldpr')) { $r[$k] = ($r[$k] -join ',') }
    return $r
}
$wfOk = $false
for ($i = 1; $i -le $tries; $i++) {
    $wf = @(gh api "repos/$repo/contents/.github/workflows/daily-update.yml?ref=$wref" -H 'Accept: application/vnd.github.raw')
    $wfOk = ($LASTEXITCODE -eq 0)
    if ($wfOk) { break }
    if ($i -lt $tries) { Start-Sleep -Seconds 3 }
}
if (-not $wfOk -or $wf.Count -eq 0) { Unread "main's .github/workflows/daily-update.yml" } else {
    $w = WfShape $wf
    $top = $w.top; $g = $w.gate; $aw = $w.attw; $cw = $w.contw; $pw = $w.prw; $ip = $w.inl; $op = $w.oldpr; $pn = $w.pn
    Write-Host "Main's daily-update.yml: workflow '$top'; gate step in '$g'; attestations: write in '$aw'; contents: write in '$cw'; pull-requests: write in '$pw'; inline job permissions in '$ip'; data pull request step in '$op'; push needs '$pn'"
    if ($PreCutover) {
        Write-Host "-PreCutover: main's daily-update.yml is checked as before the cutover (it still opens data pull requests); after the cutover merge, run this again without -PreCutover"
        if (-not $op) { Problem "-PreCutover, but main's daily-update.yml no longer has the data pull request step (the cutover is merged): run this again without -PreCutover" }
    } else {
        if ($top -cne 'permissions: {}') { Problem "main's daily-update.yml must set permissions: {} at the top (each job then names its own)" }
        if ($g -cne 'gate') { Problem "main's daily-update.yml must run the step '$gateStep' in job gate, and only there (the post-cutover gate, ADR 0011)" }
        if ($aw -cne 'push') { Problem "in main's daily-update.yml only job push may hold attestations: write (only J2 stores attestations, I-prov)" }
        if ($cw -cne 'push') { Problem "in main's daily-update.yml only job push may hold contents: write" }
        if ($pw) { Problem "no job in main's daily-update.yml may hold pull-requests: write" }
        if ($ip) { Problem "no job in main's daily-update.yml may set its permissions inline (write-all, read-all or a { } map)" }
        $pnl = ',' + ($pn -creplace '[\[\] ]', '') + ','
        if (-not $pnl.Contains(',gate,')) { Problem "job push in main's daily-update.yml must need gate" }
        if ($op) { Problem "main's daily-update.yml still opens data pull requests (before the cutover): use -PreCutover only at cutover step 4, before the cutover merge" }
    }
}

if ($script:problems -eq 0) {
    Write-Host "OK: main is protected (R1'', R-D, R-T as written, R2 off, auto-merge off, $owner the only writer, both environments main only)."
    exit 0
}
Write-Host "NOT OK: $($script:problems) problem(s) above. Run this from Brian's PC, signed in as $owner. Send this output to the team."
exit 1
