"""The deliver stage's settings, read from config/site.yml with the standard library only.

The deliver job holds the mail key, so it installs nothing (no PyYAML) and imports no `sitegen`. It also must not
take its limits from the plan file, which comes from the job that parses untrusted PDFs: `enabled`, `canary_only`,
`max_recipients`, `mode` and `api_base` are read here, from the checked-out repository. This reader understands
only what it needs: top-level `key: scalar` lines and the scalar lines of the `morning_note:` -> `sender:` block
(4 spaces deep). Anything it cannot read as exactly that is an error, never a guess. A test keeps it equal to what
PyYAML reads from the shipped file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .common import MODES, TIME_RE

SCALARS = ("enabled", "provider", "api_base", "mode", "send_at", "latest_send", "max_editions", "max_recipients",
           "canary_only")
_LINE = re.compile(r"( *)([A-Za-z_][A-Za-z0-9_]*):(?:[ \t]+(.*))?")
_API_BASE = re.compile(r"https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?(?:/[A-Za-z0-9._~/-]*)?")


class SettingsError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    enabled: bool
    provider: str
    api_base: str
    mode: str
    send_at: str
    latest_send: str
    max_editions: int
    max_recipients: int
    canary_only: bool
    timezone: str
    district_count: int
    ward_count: int


def _scalar(raw: str | None):
    """One YAML scalar of the few kinds this file uses: true/false, a whole number, quoted or plain text."""
    s = (raw or "").strip()
    if s[:1] in ("\"", "'"):
        end = s.find(s[0], 1)
        if end < 0 or s[end + 1:].strip()[:1] not in ("", "#"):
            raise SettingsError("a quoted value is not closed")
        return s[1:end]
    s = re.split(r"\s+#", s, maxsplit=1)[0].strip()
    if s in ("true", "false"):
        return s == "true"
    if re.fullmatch(r"[0-9]+", s):
        return int(s)
    if not s or s[0] in "[{&*|>!%@`":
        raise SettingsError("not a plain value")
    return s


def parse(text: str) -> dict:
    """{"top": {key: value}, "sender": {key: value}} from the file's text."""
    top, sender, path = {}, {}, []      # path: the keys of the enclosing blocks, by indent
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or line.lstrip().startswith("- "):
            continue
        m = _LINE.fullmatch(line.rstrip())
        if m is None:
            continue
        indent, key, raw = len(m.group(1)), m.group(2), m.group(3)
        path = [(i, k) for i, k in path if i < indent] + [(indent, key)]
        keys = [k for _, k in path]
        has_value = raw is not None and raw.strip() and not raw.strip().startswith("#")
        if indent == 0 and has_value and key in ("site_timezone", "district_count", "ward_count"):
            if key in top:
                raise SettingsError(f"{key} is set twice")
            top[key] = _scalar(raw)
        elif keys[:2] == ["morning_note", "sender"] and len(keys) == 3 and key in SCALARS:
            if indent != 4 or not has_value:
                raise SettingsError(f"morning_note.sender.{key} must be one plain value, 4 spaces deep")
            if key in sender:
                raise SettingsError(f"morning_note.sender.{key} is set twice")
            sender[key] = _scalar(raw)
    return {"top": top, "sender": sender}


def _whole(v, name: str, low: int = 1) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or v < low:
        raise SettingsError(f"{name} must be a whole number >= {low}")
    return v


def from_values(top: dict, sender: dict) -> Settings:
    """Checked settings. A missing or malformed value is an error: the deliver stage then sends nothing."""
    missing = [k for k in SCALARS if k not in sender] + \
              [k for k in ("site_timezone", "district_count", "ward_count") if k not in top]
    if missing:
        raise SettingsError(f"config is missing {', '.join(missing)}")
    for k in ("enabled", "canary_only"):
        if not isinstance(sender[k], bool):
            raise SettingsError(f"morning_note.sender.{k} must be true or false")
    if sender["mode"] not in MODES:
        raise SettingsError("morning_note.sender.mode must be stamp or ids")
    if not (isinstance(sender["api_base"], str) and _API_BASE.fullmatch(sender["api_base"])):
        raise SettingsError("morning_note.sender.api_base must be an https URL")
    for k in ("send_at", "latest_send"):
        if not (isinstance(sender[k], str) and TIME_RE.fullmatch(sender[k])):
            raise SettingsError(f"morning_note.sender.{k} must be HH:MM")
    if not sender["send_at"] < sender["latest_send"]:
        raise SettingsError("morning_note.sender.send_at must be before latest_send")
    if not isinstance(top["site_timezone"], str) or not isinstance(sender["provider"], str):
        raise SettingsError("site_timezone and morning_note.sender.provider must be text")
    return Settings(
        enabled=sender["enabled"], provider=sender["provider"], api_base=sender["api_base"], mode=sender["mode"],
        send_at=sender["send_at"], latest_send=sender["latest_send"],
        max_editions=_whole(sender["max_editions"], "morning_note.sender.max_editions"),
        max_recipients=_whole(sender["max_recipients"], "morning_note.sender.max_recipients"),
        canary_only=sender["canary_only"], timezone=top["site_timezone"],
        district_count=_whole(top["district_count"], "district_count", 0),
        ward_count=_whole(top["ward_count"], "ward_count", 0))


def load(path) -> Settings:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        raise SettingsError(f"cannot read {path}") from None
    got = parse(text)
    return from_values(got["top"], got["sender"])
