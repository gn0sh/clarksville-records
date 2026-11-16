"""Static checks of the T4.0 probe Brian runs on Windows (scripts/morning-note-probe.ps1). No PowerShell here:
these pin the key-handling rules (docs/ops/morning-note.md section 3) so an edit cannot quietly break them."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PS1 = (ROOT / "scripts" / "morning-note-probe.ps1").read_text(encoding="utf-8")
CMD = (ROOT / "scripts" / "morning-note-probe.cmd").read_bytes()


def test_key_is_read_without_echo_and_never_printed_or_written():
    assert "Read-Host -AsSecureString" in PS1
    assert "ZeroFreeBSTR" in PS1
    for line in PS1.splitlines():
        if re.search(r"Write-Host|Write-Output|Out-File|Set-Content|Add-Content|WriteAllText|Say ", line):
            assert "$script:key" not in line and "$k " not in line and "$sec" not in line, line
    assert "Start-Transcript" not in PS1
    # the key goes only to the pinned API host, as the Authorization header
    assert PS1.count("$script:key\"") == 1 and "'Authorization' = \"Token $script:key\"" in PS1
    assert "$Api = 'https://api.buttondown.com/v1'" in PS1


def test_results_never_hold_key_addresses_or_ids():
    assert "$Secrets.Add($script:key)" in PS1
    assert "foreach ($x in @($addrA, $addrB, $addrC))" in PS1
    assert "function Note-Id" in PS1 and "$Secrets.Add($s)" in PS1
    w = PS1[PS1.index("function Write-Results"):]
    assert "$text.Replace($x, '<hidden>')" in w and "$text.Replace($script:key, '<hidden>')" in w
    assert "GetFolderPath('MyDocuments')) 'App Development'" in w
    assert "bezac" not in PS1 and b"bezac" not in CMD


def test_guard_runs_before_any_write_and_addresses_are_checked():
    guard = PS1.index("Step '2/9 Guard")
    first_write = min(i for i in (PS1.find("Ensure-Subscriber $addrA 'first'"), PS1.find("$p1 = Bd 'PATCH'")) if i > 0)
    assert guard < first_write
    assert "throw \"This newsletter has $others" in PS1
    assert "$EmailRe = " in PS1 and "-notmatch $EmailRe" in PS1
    assert "probe 3 deleted at once" in PS1


def test_probe_follows_no_redirect_and_uses_the_senders_filter_shape():
    assert "AllowAutoRedirect = $false" in PS1
    assert "$StampField = 'subscriber.metadata.note_edition'" in PS1
    from sender import deliver
    assert deliver.STAMP_FIELD == "subscriber.metadata.note_edition"
    assert "groups = @(); predicate = 'and'" in PS1


def test_powershell_51_compatible():
    code = "\n".join(line for line in PS1.splitlines() if not line.lstrip().startswith("#"))
    for bad in ("??", "-AsHashtable", "ConvertFrom-Json -Depth", "&&", "||"):
        assert bad not in code, bad


def test_cmd_wrapper():
    assert b"\r\n" in CMD
    assert b'"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0morning-note-probe.ps1"' in CMD
