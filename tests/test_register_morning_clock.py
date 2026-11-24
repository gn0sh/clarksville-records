"""Static checks of the morning clock's PC fallback Brian runs on Windows (scripts/register-morning-clock.ps1, ADR 0014
decision 1) and of the clock's prompt (docs/ops/morning-clock.md). Task Scheduler exists only on Windows, so nothing
here registers a task: these pin the one command, the refusals and the no-token rule so an edit cannot quietly break
them. With PWSH set (tests/pwsh_twin.py), the script is also parsed by PowerShell."""
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from pwsh_twin import PWSH

ROOT = Path(__file__).resolve().parents[1]
PS1_PATH = ROOT / "scripts" / "register-morning-clock.ps1"
PS1 = PS1_PATH.read_text(encoding="utf-8")
DOC = (ROOT / "docs" / "ops" / "morning-clock.md").read_text(encoding="utf-8")
WF = yaml.safe_load((ROOT / ".github" / "workflows" / "daily-update.yml").read_text(encoding="utf-8"))

COMMAND = ("gh workflow run daily-update.yml --repo gn0sh/clarksville-records --ref main -f collect=true "
           "-f send_note=true")
V1_COMMAND = "gh workflow run daily-update.yml --repo gn0sh/clarksville-records --ref main -f collect=true"


def _code() -> str:
    return "\n".join(line for line in PS1.splitlines() if not line.lstrip().startswith("#"))


def test_the_task_runs_exactly_the_one_command():
    assert f"$GhArgs = '{COMMAND.removeprefix('gh ')}'" in PS1
    assert "New-ScheduledTaskAction -Execute $gh.Source -Argument $GhArgs" in PS1
    assert PS1.count("New-ScheduledTaskAction") == 1 and "-Daily -At $At" in PS1 and "$At = '03:07'" in PS1
    # the inputs it sets are the workflow's own, so the dispatch is the note job's one send route
    inputs = (WF.get("on") or WF[True])["workflow_dispatch"]["inputs"]
    assert {"collect", "send_note"} <= set(inputs) and inputs["send_note"]["type"] == "boolean"


def test_the_prompt_and_the_runbook_give_the_same_command():
    blocks = re.findall(r"```text\n(.*?)```", DOC, re.S)
    prompt = blocks[0]
    assert prompt.startswith("Run exactly this one command and nothing else:\n\n" + COMMAND + "\n")
    assert prompt.count("gh ") == 1 and "Never run it a third time" in prompt
    assert blocks[1].strip() == V1_COMMAND                              # V1: main has no send_note input yet
    for line in ("powershell -NoProfile -File scripts\\register-morning-clock.ps1",
                 "powershell -NoProfile -File scripts\\register-morning-clock.ps1 -Check",
                 "powershell -NoProfile -File scripts\\register-morning-clock.ps1 -Remove"):
        assert line in DOC and line in PS1, line
    flat = " ".join(DOC.split())
    assert "Daily update: the morning clock did not fire" in flat and "Daily update (morning note)" in flat
    assert "03:07 America/Chicago" in flat


def test_it_refuses_before_registering_unless_central_time_and_gn0sh():
    reg = PS1.index("Register-ScheduledTask -TaskName")
    assert PS1.index("$tz -cne $Zone") < reg and "$Zone = 'Central Standard Time'" in PS1
    assert PS1.index("[string]$login -cne 'gn0sh'") < reg and "& $gh.Source api user --jq .login" in PS1
    assert PS1.count("Nothing registered.") == 3


def test_no_token_and_no_catch_up():
    code = _code()
    for bad in ("Read-Host", "token", "Token", "GH_TOKEN", "--show-token", "auth token", "Set-Content", "Out-File",
                "Start-Transcript", "StartWhenAvailable", "-RunLevel Highest", "Password"):
        assert bad not in code, bad
    assert "-LogonType Interactive" in PS1 and "-WakeToRun" in PS1 and "-MultipleInstances IgnoreNew" in PS1


def test_check_and_remove_change_nothing_else():
    check = PS1[PS1.index("if ($Check) {"):PS1.index("if ($Remove) {")]
    remove = PS1[PS1.index("if ($Remove) {"):PS1.index("$tz = (Get-TimeZone).Id")]
    assert "Register-ScheduledTask" not in check + remove and "Unregister" not in check
    assert remove.count("Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false") == 1
    assert not re.search(r"\bgh\b", re.sub(r"#.*", "", check + remove).replace("$gh", ""))


def test_powershell_51_compatible_and_no_bypass():
    code = _code()
    for bad in ("??", "-AsHashtable", "ConvertFrom-Json -Depth", "&&", "||", "?."):
        assert bad not in code, bad
    assert "Bypass" not in PS1 and "Unblock-File" not in PS1 and "-ExecutionPolicy" not in PS1
    assert "Only for files downloaded from this repository's GitHub page" in PS1
    assert PS1.isascii()


@pytest.mark.skipif(not PWSH, reason="PWSH is not set: no PowerShell to parse the script")
def test_powershell_parses_it():
    cmd = ("$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile($args[0], [ref]$null, "
           "[ref]$e); if ($e.Count) { $e | ForEach-Object { $_.Message }; exit 1 }")
    r = subprocess.run([PWSH, "-NoProfile", "-Command", cmd, str(PS1_PATH)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
