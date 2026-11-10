"""The deliver stage's settings, read from config/site.yml with the standard library only.

The deliver job holds the mail key, so it installs nothing (no PyYAML) and imports no `sitegen`. It also must not
take its limits from the plan file, which comes from the job that parses untrusted PDFs: `enabled`, `canary_only`,
`max_recipients`, `mode` and `api_base` are read here, from the checked-out repository. This reader understands
only what it needs: three top-level keys and the `morning_note:` -> `sender:` block (parse()), and is strict only
there; the rest of the file may be any YAML. parity() compares it with PyYAML, and the site build and
`python -m sender plan` fail on any difference, so the commit the deliver job reads has passed it.
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
_INT = re.compile(r"0|[1-9][0-9]*")                    # no leading zero: PyYAML reads 0100 as octal 64
_PLAIN = re.compile(r"[A-Za-z][A-Za-z0-9_./:~-]*")     # a word or URL; no space, no ": ", nothing PyYAML resolves
_YAML_WORDS = {"yes", "no", "on", "off", "true", "false", "null", "y", "n"}
_BAD_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}
_BREAKS = re.compile("\r\n|[\r\n\x85\u2028\u2029]")
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
    """The file's lines, split where PyYAML splits them: CR LF, LF, CR, NEL, U+2028, U+2029 (not VT, FF or FS, which
    str.splitlines() also splits on). A leading byte order mark is dropped, as PyYAML drops it."""
    text = text[1:] if text.startswith("\ufeff") else text
    return _BREAKS.split(text)


def _strict(n: int, line: str) -> None:
    """A line this reader takes a value from: no control or format character (one could hide a line or a key)."""
    for c in line:
        if c != "\t" and unicodedata.category(c) in _BAD_CATEGORIES:
            raise SettingsError(f"line {n}: a control or format character (U+{ord(c):04X}) in a line the deliver "
                                f"stage reads")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def parse(text: str) -> dict:
    """{"top": {key: value}, "sender": {key: value}} from the file's text.

    Strict only where it reads (settings-parity/too-strict-daily-outage): the three top-level keys it needs, and the
    `morning_note:` -> `sender:` block, whose direct lines must each be one plain `key: value` (or a `key:` with a
    sub-block, such as `text:`, which is not read), at one indent, each key once, with no line continuing a value.
    Everywhere else any valid YAML is accepted unread, apart from two checks: no top-level key twice and no second
    `sender:` under `morning_note:`. parity() then compares the values with PyYAML's, and the site build and
    `python -m sender plan` fail on any difference, so the commit the deliver job reads has passed it."""
    top, sender = {}, {}
    seen_top: set[str] = set()
    in_mn = False
    mn_child = None         # the indent of morning_note's direct keys
    seen_sender = False
    sender_at = None        # the indent of `sender:` while inside its block
    child = None            # the indent of sender's direct keys
    sub = None              # inside sender: the indent of a direct key with a sub-block (text:), whose lines are not read
    seen_child: set[str] = set()
    for n, line in enumerate(_lines(text), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = _indent(line)
        if indent == 0 and not line.startswith("\t"):
            sender_at = None
            m = _LINE.fullmatch(line.rstrip())
            if m is None:
                in_mn = False   # a top-level line this reader does not read (a quoted key, a flow mapping's rest)
                continue
            key, raw = m.group(2), (m.group(3) or "").strip()
            if key in seen_top:
                raise SettingsError(f"line {n}: {key} is set twice")
            seen_top.add(key)
            in_mn, mn_child = key == "morning_note", None
            if key in _TOP:
                _strict(n, line)
                if not raw or raw.startswith("#"):
                    raise SettingsError(f"line {n}: {key} must be one plain value")
                top[key] = _scalar(raw)
            continue
        if not in_mn:
            continue
        if sender_at is not None:
            if indent > sender_at:
                if child is None:
                    child = indent
                if sub is not None and indent > sub:
                    continue                    # inside a sub-block of sender (text:): not read
                sub = None
                if indent != child:
                    raise SettingsError(f"line {n}: inside morning_note.sender, a line at an indent no key has, "
                                        f"or one that continues a value")
                _strict(n, line)
                m = _LINE.fullmatch(line.rstrip())
                if m is None:
                    raise SettingsError(f"line {n}: inside morning_note.sender, a line that is not one plain "
                                        f"`key: value`")
                key, raw = m.group(2), (m.group(3) or "").strip()
                has_value = bool(raw) and not raw.startswith("#")
                if key in seen_child:
                    raise SettingsError(f"line {n}: morning_note.sender.{key} is set twice")
                seen_child.add(key)
                if key in SCALARS:
                    if not has_value:
                        raise SettingsError(f"line {n}: morning_note.sender.{key} must be one plain value")
                    sender[key] = _scalar(raw)
                elif not has_value:
                    sub = indent                # a sub-block (text:)
                elif not _closed(raw):
                    raise SettingsError(f"line {n}: morning_note.sender.{key} runs past its line")
                continue
            sender_at = None
        if mn_child is None:
            mn_child = indent
        if indent != mn_child:
            continue                            # deeper: a value, item or block of another morning_note key
        m = _LINE.fullmatch(line.rstrip())
        if m is None or m.group(2) != "sender":
            continue
        _strict(n, line)
        raw = (m.group(3) or "").strip()
        if seen_sender:
            raise SettingsError(f"line {n}: morning_note.sender is set twice")
        seen_sender = True
        if raw and not raw.startswith("#"):
            raise SettingsError(f"line {n}: morning_note.sender must be a block of `key: value` lines")
        sender_at, child, sub, seen_child = indent, None, None, set()
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
