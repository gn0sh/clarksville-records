"""Running a scripts/*.ps1 twin in the behavioural tests, when the environment variable PWSH names a pwsh binary.

Brian runs the .ps1 twins (docs/ops/morning-note.md); the tests run the .sh twins against stubs. With PWSH set, the
same tests also run each .ps1 against the same stubs (the `twin` parameter, "sh" or "ps1"; "ps1" is skipped when PWSH
is unset, so CI runs only the .sh as before). A Linux pwsh 7 run can't prove what only Windows PowerShell 5.1 does
(see PS51_ONLY below).

The .ps1 runs as `pwsh -File <script> <args>` (the binding Brian's `powershell -NoProfile -File` gets), with HOME in
the test's folder and a profile there that holds the only fakes a PATH stub can't be: Get-Date without arguments
(FAKE_HM and FAKE_S_STEP, as the .sh's stub date), Start-Sleep (as the .sh's stub sleep) and Invoke-RestMethod
(calls the stub curl).
A nested `powershell -NoProfile -File` (the cutover's protect-main and merge-reviewed calls) runs the shim
`powershell` on PATH, which is pwsh again, without that profile."""
import os
import re
from pathlib import Path

import pytest

PWSH = os.environ.get("PWSH", "")
TWINS = ["sh", pytest.param("ps1", marks=pytest.mark.skipif(not PWSH, reason="PWSH is not set: no PowerShell to run "
                                                                               "the .ps1 twin"))]

PROFILE = r'''# the test's fakes (tests/pwsh_twin.py): loaded only by the run under test, never by a nested -NoProfile run
function global:Get-Date {
    if ($args.Count -eq 0 -and $env:FAKE_HM -match '^[0-9]{4}$') {
        $d = [DateTime]::UtcNow.Date.AddHours([int]$env:FAKE_HM.Substring(0, 2))
        $d = $d.AddMinutes([int]$env:FAKE_HM.Substring(2, 2))
        if ($env:FAKE_S_STEP) {   # as the .sh's stub date +%s: each read is FAKE_S_STEP seconds after the one before
            $global:FakeReads++
            $d = $d.AddSeconds($global:FakeReads * [int]$env:FAKE_S_STEP)
        }
        return [DateTime]::SpecifyKind($d, [DateTimeKind]::Utc)
    }
    Microsoft.PowerShell.Utility\Get-Date @args
}
# as the .sh's stub sleep: logs the call to GH_CALLS; STUB_SLEEP seconds (a Ctrl+C test), else none
function global:Start-Sleep {
    $s = [string]$args[0]
    if ($args.Count -ge 2 -and [string]$args[0] -eq '-Seconds') { $s = [string]$args[1] }
    $line = '{"method": "SLEEP", "path": "Start-Sleep", "argv": ["' + $s + '"]}' + "`n"
    if ($env:GH_CALLS) { [IO.File]::AppendAllText($env:GH_CALLS, $line) }
    if ($env:STUB_SLEEP) { Microsoft.PowerShell.Utility\Start-Sleep -Milliseconds ([int]([double]$env:STUB_SLEEP * 1000)) }
}
function global:Invoke-RestMethod {
    param([string]$Uri, $TimeoutSec, [switch]$UseBasicParsing)
    $t = (& curl -s $Uri) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw "stub curl failed for $Uri" }
    return ($t | ConvertFrom-Json)
}
'''


def install(home: Path, bindir: Path):
    """The profile under <home> and the `powershell` shim in <bindir> (first on PATH)."""
    prof = home / ".config" / "powershell"
    prof.mkdir(parents=True, exist_ok=True)
    (prof / "profile.ps1").write_text(PROFILE)
    shim = bindir / "powershell"
    shim.write_text('#!/bin/sh\nexec "$PWSH" "$@"\n')
    shim.chmod(0o755)


def env(base: dict) -> dict:
    """<base> for a pwsh run: the profile is read from HOME (no XDG_CONFIG_HOME), no telemetry or update check."""
    e = {k: v for k, v in base.items() if k != "XDG_CONFIG_HOME"}
    e.update({"PWSH": PWSH, "POWERSHELL_TELEMETRY_OPTOUT": "1", "POWERSHELL_UPDATECHECK": "Off",
              "DOTNET_CLI_TELEMETRY_OPTOUT": "1"})
    return e


def argv(script, args) -> list:
    """-NonInteractive: a missing mandatory parameter fails at once (Brian's console would prompt for it)."""
    return [PWSH, "-NonInteractive", "-File", str(script), *args]


def param_block(script: Path) -> str:
    """The `param(...)` block of a real .ps1, so a stub twin binds its arguments exactly as the real one does."""
    text = script.read_text(encoding="utf-8")
    m = re.search(r"(?m)^param\(", text)
    assert m, script
    depth, i = 0, m.start() + len("param")
    while True:
        depth += {"(": 1, ")": -1}.get(text[i], 0)
        i += 1
        if depth == 0:
            return text[m.start():i]


def flags(args, table: dict) -> list:
    """The .sh's --long flags as the .ps1's -Names; values pass through unchanged (an empty one stays empty)."""
    return [table.get(a, a) for a in args]


# What a pwsh 7 run on Linux can't prove about Brian's Windows PowerShell 5.1 (checked by hand or by text pins):
PS51_ONLY = (
    "native arguments: 5.1 drops an empty-string argument and mangles embedded double quotes (the scripts pass no "
    "double quote to gh: pinned by text); pwsh 7.4 on Linux passes both as given (PSNativeCommandArgumentPassing "
    "Standard), so these runs can't catch either",
    "GitRun's ProcessStartInfo.Arguments: on Windows it is one command line split by git's C runtime (QArg's "
    "quoting); on Linux .NET splits it itself",
    "-File argument binding: pwsh 7 binds '--check' as -Check; whether 5.1 does is unproved (named binding only "
    "now refuses anything that matches no parameter)",
    "stderr of native commands under 2>&1 or 2> $null: 5.1 wraps each line as a NativeCommandError record (and "
    "$ErrorActionPreference 'Stop' would throw); $PSNativeCommandUseErrorActionPreference is 7.3+ only (off here)",
    "ConvertFrom-Json and ConvertTo-Json: 5.1 does not enumerate a piped top-level array, serialises arrays as "
    "{value,Count} without Remove-TypeData System.Array, escapes <>&' as \\uXXXX, and types numbers differently",
    "file encoding: 5.1 reads a BOM-less .ps1 as the ANSI code page (the scripts are ASCII: pinned) and its "
    "Out-File, Set-Content and > write UTF-16LE or ANSI (the scripts write only through [IO.File] with a BOM-less "
    "UTF8Encoding)",
    "Invoke-RestMethod (cutover step 7's build-info.json read): faked here; 5.1 needs -UseBasicParsing and TLS 1.2",
    "the nested `powershell -NoProfile -File` calls: Windows runs 5.1 there even from a pwsh 7 console; here the "
    "shim runs pwsh 7",
    "Python discovery (py -3 first): Linux has only python3",
    "GitRun's stdin on a UTF-8 console: 5.1 writes [Console]::InputEncoding's BOM at Process.Start (pwsh 7 strips "
    "it), so the preamble-free swap around Start is pinned by text only",
    "Ctrl+C: a console CancelKeyPress on Windows, SIGINT here",
    "[Environment]::GetFolderPath('MyDocuments') (u3's backup): HOME here; on Windows possibly a OneDrive folder",
    "the exit code of `powershell -File` on a parameter binding failure: pwsh 7 exits 1 (protect-main.ps1, an "
    "advanced script, relies on it); cutover-data-off-main.ps1 catches the failure of its binding block and exits 1 "
    "itself, but what 5.1's host returns for an advanced script is unproved",
    "the cutover rollback's POST pulls tells a 422 from any other failure by gh's stderr line '(HTTP 422)' read "
    "through 2>&1 as strings (read-after-write rule 6): on 5.1 each stderr line is a NativeCommandError record whose "
    "text should be the line, but that it matches is unproved here",
    "ReadUntil's scriptblocks see the caller's variables by PowerShell's dynamic scoping (they avoid the helper's own "
    "names $what, $want, $read, $i); pwsh 7 and 5.1 scope the same way, but no 5.1 run proves it",
    "PositionalBinding=$false with -File on 5.1: pwsh 7 refuses a positional argument, and passes each '-Name' "
    "argument of `-File` into a non-advanced script's $args so that `. { [CmdletBinding(PositionalBinding = $false)] "
    "param(...) } @args` binds it by name (cutover-data-off-main.ps1); that 5.1 does both is unproved",
)
