"""The deliver stage's settings, read from config/site.yml with the standard library only.

The deliver job holds the mail key, so it installs nothing (no PyYAML) and imports no `sitegen`. It also must not
take its limits from the plan file, which comes from the job that parses untrusted PDFs: `enabled`, `canary_only`,
`max_recipients`, `mode` and `api_base` are read here, from the checked-out repository. This reader understands
only what it needs: top-level `key:` lines and the `morning_note:` block, line by line (parse()). Anything it
cannot read as exactly that is an error, never a guess or a skipped line. parity() compares it with PyYAML, and the
site build and `python -m sender plan` fail on any difference, so the commit the deliver job reads has passed it.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .common import MODES, TIME_RE

SCALARS = ("enabled", "provider", "api_base", "mode", "send_at", "latest_send", "max_editions", "max_recipients",
           "canary_only")
_TOP = ("site_timezone", "district_count", "ward_count")
_LINE = re.compile(r"( *)([A-Za-z_][A-Za-z0-9_]*):(?: +(.*))?")
_ITEM = re.compile(r"( *)-(?: +(.*))?")
_INT = re.compile(r"0|[1-9][0-9]*")                    # no leading zero: PyYAML reads 0100 as octal 64
_PLAIN = re.compile(r"[A-Za-z][A-Za-z0-9_./:~-]*")     # a word or URL; no space, no ": ", nothing PyYAML resolves
_YAML_WORDS = {"yes", "no", "on", "off", "true", "false", "null", "y", "n"}
_BAD_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}
# settings/api-base-host: the one host each provider's key may be sent to, fixed here rather than read from config
PROVIDER_HOSTS = {"buttondown": "api.buttondown.com"}
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


def _closed(v: str) -> bool:
    """True when a value that starts with a quote or a flow bracket ends on its own line (then only a comment may
    follow). Every value in the blocks this reader walks is one line; a value that runs on could hide a key."""
    if v[:1] in ("\"", "'"):
        q, n = v[0], 1
        while n < len(v):
            if q == "\"" and v[n] == "\\":
                n += 2
                continue
            if v[n] == q:
                if q == "'" and v[n + 1:n + 2] == "'":
                    n += 2
                    continue
                return v[n + 1:].strip()[:1] in ("", "#")
            n += 1
        return False
    if v[:1] in ("{", "["):
        return re.split(r"\s+#", v, maxsplit=1)[0].rstrip()[-1:] == {"{": "}", "[": "]"}[v[0]]
    return True


def _scalar(raw: str | None):
    """One value this reader takes: true/false, a whole number written plainly, quoted text with no escape, or a
    plain word such as `stamp` or an https URL. Every other spelling (`yes`, `null`, `0100`, `1_000`, `10:00`
    unquoted, an anchor or tag) reads differently in PyYAML, so it is an error here."""
    s = (raw or "").strip()
    if s[:1] in ("\"", "'"):
        end = s.find(s[0], 1)
        if end < 0 or s[end + 1:].strip()[:1] not in ("", "#"):
            raise SettingsError("a quoted value is not closed, or has a doubled quote")
        if s[0] == "\"" and "\\" in s[1:end]:
            raise SettingsError("a quoted value has an escape")
        return s[1:end]
    s = re.split(r"\s+#", s, maxsplit=1)[0].strip()
    if s in ("true", "false"):
        return s == "true"
    if _INT.fullmatch(s):
        return int(s)
    if not _PLAIN.fullmatch(s) or s.lower() in _YAML_WORDS:
        raise SettingsError("not one plain value (quote text that is not a word or a URL)")
    return s


def _lines(text: str) -> list[str]:
    """The file's lines as PyYAML splits them. A control or format character (VT, FS, NEL, U+2028, a lone CR, a
    zero-width space) splits or hides a line differently in different readers, so any of them is an error."""
    text = text[1:] if text.startswith("﻿") else text
    text = text.replace("\r\n", "\n")
    for c in text:
        if c not in "\t\n" and unicodedata.category(c) in _BAD_CATEGORIES:
            raise SettingsError(f"the file has a control or format character (U+{ord(c):04X})")
    return text.split("\n")


def parse(text: str) -> dict:
    """{"top": {key: value}, "sender": {key: value}} from the file's text.

    Every top-level line must be a plain `key:` line, each key once. Inside `morning_note:` every line must be a
    `key: value`, `key:` or `- item` line, nested the way PyYAML nests it (a deeper line only under a `key:` with no
    value, siblings at one indent, no key twice in one block), with each value on its own line. Anything else is an
    error, never a skipped line, so the file cannot say one thing to PyYAML and another to this reader. The build and
    `python -m sender plan` also compare the two readers (parity()), so a file that slips past this fails there."""
    top, sender = {}, {}
    seen_top: set[str] = set()
    stack: list[list] = []      # inside morning_note: [indent, key or "-", has_value, {child keys}]
    in_mn = False
    for n, line in enumerate(_lines(text), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            m = _LINE.fullmatch(line.rstrip())
            if m is None:
                raise SettingsError(f"line {n}: a top-level line must be a plain `key:` line")
            key, raw = m.group(2), (m.group(3) or "").strip()
            has_value = bool(raw) and not raw.startswith("#")
            if key in seen_top:
                raise SettingsError(f"line {n}: {key} is set twice")
            seen_top.add(key)
            if has_value and not _closed(raw):
                raise SettingsError(f"line {n}: the value of {key} runs past its line")
            in_mn = key == "morning_note"
            if in_mn and has_value:
                raise SettingsError(f"line {n}: morning_note must be a block of `key:` lines")
            if key in _TOP:
                if not has_value:
                    raise SettingsError(f"line {n}: {key} must be one plain value")
                top[key] = _scalar(raw)
            stack = [[0, key, has_value, set()]]
            continue
        if not in_mn:
            continue            # another top-level block: not read
        m = _LINE.fullmatch(line.rstrip())
        item = _ITEM.fullmatch(line.rstrip()) if m is None else None
        if m is None and item is None:
            raise SettingsError(f"line {n}: inside morning_note, a line that is not `key: value` or `- item`")
        key = m.group(2) if m else "-"
        raw = ((m.group(3) if m else item.group(2)) or "").strip()
        has_value = bool(raw) and not raw.startswith("#")
        if has_value and not _closed(raw):
            raise SettingsError(f"line {n}: a value runs past its line")
        if indent > stack[-1][0]:
            if stack[-1][2]:
                raise SettingsError(f"line {n}: a deeper line under a key that already has a value")
        else:
            while stack[-1][0] > indent:
                stack.pop()
            if stack[-1][0] != indent:
                raise SettingsError(f"line {n}: an indent no sibling has")
            if (stack[-1][1] == "-") != (key == "-"):
                raise SettingsError(f"line {n}: a list item and a key side by side")
            stack.pop()
        parent = stack[-1]
        if key != "-":
            if key in parent[3]:
                raise SettingsError(f"line {n}: {key} is set twice in one block")
            parent[3].add(key)
        stack.append([indent, key, has_value, set()])
        path = [e[1] for e in stack]
        if path == ["morning_note", "sender"] and has_value:
            raise SettingsError(f"line {n}: morning_note.sender must be a block of `key: value` lines")
        if path[:2] == ["morning_note", "sender"] and len(path) == 3:
            if key == "-":
                raise SettingsError(f"line {n}: morning_note.sender holds no list item")
            if key in SCALARS:
                if not has_value:
                    raise SettingsError(f"line {n}: morning_note.sender.{key} must be one plain value")
                sender[key] = _scalar(raw)
    return {"top": top, "sender": sender}


def _same(a, b) -> bool:
    return type(a) is type(b) and a == b


def parity(text: str, loaded) -> list[str]:
    """Every value the deliver stage reads where this reader and PyYAML (`loaded`, the same text through
    yaml.safe_load) disagree, or the reason this reader refuses the file. [] when they agree. The site build and
    `python -m sender plan` fail on any of these, so a config the deliver job would read differently never merges."""
    try:
        got = parse(text)
    except SettingsError as exc:
        return [f"config/site.yml: the deliver stage's reader (sender/settings.py) refuses the file: {exc}"]
    mn = loaded.get("morning_note") if isinstance(loaded, dict) else None
    s = mn.get("sender") if isinstance(mn, dict) else None
    s = s if isinstance(s, dict) else {}
    out = []
    missing = object()
    pairs = [(f"morning_note.sender.{k}", got["sender"].get(k, missing), s.get(k, missing)) for k in SCALARS]
    pairs += [(k, got["top"].get(k, missing), loaded.get(k, missing) if isinstance(loaded, dict) else missing)
              for k in _TOP]
    for name, ours, theirs in pairs:
        if not _same(ours, theirs):
            a, b = ("nothing" if v is missing else repr(v) for v in (ours, theirs))
            out.append(f"config/site.yml: {name}: the deliver stage's reader (sender/settings.py) reads {a}, "
                       f"PyYAML reads {b}")
    return out


def api_base_problem(provider, api_base) -> str:
    """"" when `api_base` is an https URL on exactly the host PROVIDER_HOSTS names for `provider`, with no port."""
    if not isinstance(provider, str) or provider not in PROVIDER_HOSTS:
        return f"morning_note.sender.provider must be one of {', '.join(sorted(PROVIDER_HOSTS))}"
    if not (isinstance(api_base, str) and _API_BASE.fullmatch(api_base)):
        return "morning_note.sender.api_base must be an https URL"
    if api_base[len("https://"):].split("/", 1)[0] != PROVIDER_HOSTS[provider]:
        return f"morning_note.sender.api_base must be on {PROVIDER_HOSTS[provider]}, the provider's own host"
    return ""


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
    problem = api_base_problem(sender["provider"], sender["api_base"])
    if problem:
        raise SettingsError(problem)
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
