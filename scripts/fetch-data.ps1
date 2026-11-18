# Fill data/ from origin/records-data (ADR 0011 decision 1; docs/tasks/data-off-main.md D2). scripts/fetch-data.sh
# is its tested bash twin (same steps, same lines). From the cutover on, main tracks no data/ (it is gitignored); the
# collector's output lives on branch records-data, whose tree is data/ only. Run this before the tests, a site build
# or a collector run.
#   - Before the cutover (data/ tracked on this checkout) it is a no-op and says so.
#   - It fetches records-data into refs/remotes/origin/records-data, refuses a tree holding anything besides data/,
#     extracts it with git archive into the git folder, checks the file count, then swaps it in for data/. The data/
#     that was there is kept at <git folder>\fetch-data\previous until the next run.
#   - It never commits, pushes, checks out a branch or touches the index, and refuses when data/ is neither tracked
#     nor ignored here (it could then be committed by mistake).
# Exit 0 done or no-op, 1 refused or failed (data/ unchanged). Needs git and tar (built into Windows 10 and 11).
# Run (PowerShell, in the repository folder):
#   powershell -NoProfile -File scripts\fetch-data.ps1   (local scripts are allowed in Settings > For developers; never -ExecutionPolicy Bypass)
# The archive goes to a file (--output), never through a PowerShell pipe, which would re-encode the bytes.

$ErrorActionPreference = 'Continue'   # 'Stop' turns git's stderr into errors in PowerShell 5.1; exit codes are checked
$top = (git rev-parse --show-toplevel 2> $null) -join ''
if ($LASTEXITCODE -ne 0 -or -not $top) { Write-Host 'Run this inside the clarksville-records checkout. Nothing was changed.'; exit 1 }
Set-Location -LiteralPath $top
$tracked = @(git ls-files -- data | Select-Object -First 1)
if ($tracked.Count -gt 0 -and $tracked[0]) {
    Write-Host 'data/ is tracked on this checkout (before the ADR 0011 cutover): nothing to fetch. Nothing was changed.'
    exit 0
}
git check-ignore -q data/
if ($LASTEXITCODE -ne 0) {
    Write-Host 'data/ is neither tracked nor ignored on this checkout, so it could be committed by mistake. Nothing was changed. Send this output to the team.'
    exit 1
}
git fetch --quiet --no-tags origin '+refs/heads/records-data:refs/remotes/origin/records-data'
if ($LASTEXITCODE -ne 0) { Write-Host 'Could not fetch records-data from origin. Nothing was changed.'; exit 1 }
$d = (git rev-parse --verify --quiet 'refs/remotes/origin/records-data^{commit}') -join ''
if ($LASTEXITCODE -ne 0 -or $d -cnotmatch '^[0-9a-f]{40}$') { Write-Host 'origin has no records-data commit. Nothing was changed.'; exit 1 }
$names = (@(git ls-tree --name-only $d)) -join ','
if ($names -cne 'data') {
    Write-Host "records-data $d holds '$names', not only data/. Nothing was changed. Send this output to the team."; exit 1
}
# data must be a real folder, and nothing under it a symlink (120000) or a submodule (160000): a symlinked data/ or
# file would point the site build, the tests or the collector outside the checkout
$topMode = ((@(git ls-tree $d data)) -join '').Split(' ')[0]
if ($topMode -cne '040000') {
    Write-Host "records-data $d has data as mode $topMode, not a folder (040000). Nothing was changed. Send this output to the team."; exit 1
}
# decide on the count of matching lines, never on the names derived from them (fail closed)
$tree = @(git ls-tree -r $d -- data)
if ($LASTEXITCODE -ne 0) { Write-Host "Could not list records-data $d. Nothing was changed. Send this output to the team."; exit 1 }
$m = @($tree | Where-Object { $_ -cmatch '^(120000|160000) ' })
if ($m.Count -gt 0) {
    $links = (@($m | Select-Object -First 5) | ForEach-Object { ($_ -split "`t", 2)[-1] }) -join ','
    Write-Host "records-data $d holds a symlink or submodule under data/ ($links). Nothing was changed. Send this output to the team."; exit 1
}
$want = @(git ls-tree -r --name-only $d -- data).Count
$gd = (git rev-parse --absolute-git-dir) -join ''
if ($LASTEXITCODE -ne 0 -or -not $gd) { Write-Host 'Could not find the git folder. Nothing was changed.'; exit 1 }
$work = Join-Path $gd 'fetch-data'
$new = Join-Path $work 'new'
$tar = Join-Path $work 'data.tar'
$previous = Join-Path $work 'previous'
Remove-Item -LiteralPath $new, $tar -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $new | Out-Null
if (-not (Test-Path -LiteralPath $new)) { Write-Host "Could not make $work. Nothing was changed."; exit 1 }
git archive --format=tar "--output=$tar" $d data
if ($LASTEXITCODE -ne 0) { Write-Host "git archive of records-data $d failed. Nothing was changed."; exit 1 }
tar -xf $tar -C $new
if ($LASTEXITCODE -ne 0) { Write-Host "Could not unpack records-data $d. Nothing was changed."; exit 1 }
Remove-Item -LiteralPath $tar -Force -ErrorAction SilentlyContinue
$got = @(Get-ChildItem -LiteralPath (Join-Path $new 'data') -Recurse -Force -ErrorAction SilentlyContinue | Where-Object { -not $_.PSIsContainer }).Count
if ($got -ne $want) {
    Write-Host "Unpacked $got files from records-data $d, expected $want. Nothing was changed. Send this output to the team."; exit 1
}
if (Test-Path -LiteralPath 'data') {
    Remove-Item -LiteralPath $previous -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $previous) {
        Write-Host "Could not remove the old $previous. Nothing was changed. Send this output to the team."; exit 1
    }
    Move-Item -LiteralPath 'data' -Destination $previous
    if (-not $?) { Write-Host 'Could not move the current data/ aside. Nothing was changed.'; exit 1 }
    Write-Host "The data/ that was here is now at $previous (replaced on the next run)."
}
Move-Item -LiteralPath (Join-Path $new 'data') -Destination 'data'
if (-not $?) { Write-Host "Could not move the new data/ in place: the old one is at $previous. Send this output to the team."; exit 1 }
Write-Host "data/ is now records-data $d ($want files). Nothing was committed."
