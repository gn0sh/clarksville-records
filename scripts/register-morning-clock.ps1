# Morning clock, PC fallback (ADR 0014 decision 1; docs/ops/morning-clock.md "Fallback"). Brian runs this one, and
# only if the cloud clock misses 2 of its first 5 mornings. It adds one Windows Task Scheduler task that runs, at
# 03:07 every day, exactly one command with Brian's existing gh sign-in:
#   gh workflow run daily-update.yml --repo gn0sh/clarksville-records --ref main -f collect=true -f send_note=true
# It reads, stores and prints no token, and changes nothing on GitHub when it is registered.
# Local scripts run under RemoteSigned. Only for files downloaded from this repository's GitHub page: they may need
# Unblock (right-click the file > Properties > tick Unblock > OK).
#
# Run (PowerShell, in the repository folder):
#   powershell -NoProfile -File scripts\register-morning-clock.ps1           add the task (or replace it)
#   powershell -NoProfile -File scripts\register-morning-clock.ps1 -Check    its state, next run, last run and result
#   powershell -NoProfile -File scripts\register-morning-clock.ps1 -Remove   delete it
#
# Refuses, registering nothing, unless this PC's time zone is Central (America/Chicago, the site's zone, so 03:07 here
# is 03:07 site time and daylight saving time needs no edit) and gh is signed in as gn0sh (the note job sends only for
# a run gn0sh dispatched). The task runs only while Brian is signed in to Windows (a locked screen is fine: gh's
# sign-in lives in his own credential store), wakes the PC from sleep, and never catches up a missed morning (a late
# start could only end after 10:00, latest_send). The workflow's clock-missed job reports a missed morning.
param([switch]$Check, [switch]$Remove)
$ErrorActionPreference = 'Stop'

$TaskName = 'Daylight morning clock'
$At = '03:07'
$GhArgs = 'workflow run daily-update.yml --repo gn0sh/clarksville-records --ref main -f collect=true -f send_note=true'
$Zone = 'Central Standard Time'   # Windows' name for America/Chicago (config/site.yml site_timezone)

if ($Check -and $Remove) {
    Write-Host 'Use -Check or -Remove, not both. Nothing changed.'
    exit 2
}

if ($Check) {
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $t) {
        Write-Host "NOT REGISTERED $TaskName"
        exit 1
    }
    $i = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "STATE $($t.State)"
    Write-Host "NEXT RUN $($i.NextRunTime)"
    Write-Host "LAST RUN $($i.LastRunTime) RESULT $($i.LastTaskResult) (0 is success)"
    Write-Host "RUNS $($t.Actions[0].Execute) $($t.Actions[0].Arguments)"
    exit 0
}

if ($Remove) {
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $t) {
        Write-Host "NOT REGISTERED $TaskName (nothing to remove)"
        exit 0
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "REMOVED $TaskName"
    exit 0
}

$tz = (Get-TimeZone).Id
if ($tz -cne $Zone) {
    Write-Host "This PC's time zone is '$tz', not '$Zone': 03:07 here is not 03:07 site time. Nothing registered."
    exit 2
}

$gh = Get-Command gh -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $gh) {
    Write-Host 'gh (GitHub CLI) is not on PATH. Install it and run gh auth login first. Nothing registered.'
    exit 2
}
$login = & $gh.Source api user --jq .login
if ($LASTEXITCODE -ne 0 -or [string]$login -cne 'gn0sh') {
    Write-Host "gh is not signed in as gn0sh (it said '$login'): the note job sends only for a run gn0sh dispatched. Nothing registered."
    exit 2
}

$action = New-ScheduledTaskAction -Execute $gh.Source -Argument $GhArgs
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$me = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive
$desc = 'Daylight morning clock (gn0sh/clarksville-records ADR 0014): starts the morning-note Daily update run. docs/ops/morning-clock.md'
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description $desc -Force | Out-Null
$i = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host "REGISTERED $TaskName, next run $($i.NextRunTime)"
Write-Host 'Pause the cloud clock now (never run two clocks): docs/ops/morning-clock.md "Pause it".'
