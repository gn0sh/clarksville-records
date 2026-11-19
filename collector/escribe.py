"""eScribe source (ADR 0012 amendment A1.4): one city's council meetings from its public eScribe meetings portal.

NOT wired into the daily update (task E3 does that). Everything locality-specific comes from
config/cities/<city>/escribe.yml, loaded and checked by load_config(); the code holds no locality literal.

The one listing call is the one the portal's public calendar page makes:
    POST https://<host>/MeetingsCalendarView.aspx/GetCalendarMeetings   {"calendarStartDate", "calendarEndDate"}
answered {"d": [meeting, ...]}. The answer field names below are the ones in the recorded answer
(collector/tests/fixtures/escribe/escribe-GetCalendarMeetings-2026-06-01_2026-11-18.json, 2026-11-18/19); the body
key names are inferred (see the sibling .request.txt). The POST goes through PoliteFetcher.post_json, which only
sends to a (host, path) pair in post_paths(cfg).

listing_rows() turns an answer into listing rows in the shared row shape (collector/legistar.py listing_rows), plus
start_time. The answer is checked, never trusted: only meetings whose name is one of the config's body_names become
rows; agenda and minutes links resolve against the config host only (a document on any other host is dropped and
logged, unless it is in file_hosts); video is a link only, kept when its host is in video_hosts.
"""
from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from .hosts import host_matches, plain_hostname
from .windows import Window

SOURCE = "escribe"
CALENDAR_PATH = "/MeetingsCalendarView.aspx/GetCalendarMeetings"
POST_PATHS = (CALENDAR_PATH,)
REQUIRED = ("city", "host", "body_names", "agenda_types", "minutes_types", "kind_rules", "launch_days")
MAX_WINDOW_DAYS = 184                 # one POST per window of at most 6 months (A1.4)
GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
START_RE = re.compile(r"^(\d{4})/(\d{2})/(\d{2}) (\d{2}):(\d{2})(?::\d{2})?$")   # "2026/08/10 18:00:26", local time


class ConfigError(ValueError):
    pass


class AnswerError(ValueError):
    """The calendar answer is not the shape we recorded. Fails loudly; nothing is guessed."""


def _strs(cfg: dict, key: str, path, allow_empty: bool = False) -> tuple:
    v = cfg.get(key, [] if allow_empty else None)
    if not isinstance(v, list) or (not v and not allow_empty) or not all(isinstance(s, str) and s.strip() for s in v):
        raise ConfigError(f"{path}: {key} must be a list of non-empty strings")
    return tuple(s.strip() for s in v)


def _hosts(cfg: dict, key: str, path) -> tuple:
    out = []
    for h in _strs(cfg, key, path, allow_empty=True):
        if plain_hostname(h) != h.lower() or ":" in h:
            raise ConfigError(f"{path}: {key} entry {h!r} is not a plain host name")
        out.append(h.lower())
    return tuple(out)


def load_config(path: str | Path) -> dict:
    """Read and check a city's escribe.yml. A missing or malformed key fails loudly."""
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(cfg, dict):
        raise ConfigError(f"{path}: not a mapping")
    missing = [k for k in REQUIRED if k not in cfg]
    if missing:
        raise ConfigError(f"{path}: missing {', '.join(missing)}")
    host = cfg["host"]
    if not isinstance(host, str) or plain_hostname(host) != host.lower() or ":" in host:
        raise ConfigError(f"{path}: host must be a plain host name (the portal, e.g. pub-<city>.escribemeetings.com)")
    cfg["host"] = host.lower()
    if not isinstance(cfg["launch_days"], int) or not 30 <= cfg["launch_days"] <= 400:
        raise ConfigError(f"{path}: launch_days must be a whole number of days, 30 to 400")
    for key in ("body_names", "agenda_types", "minutes_types"):
        cfg[key] = _strs(cfg, key, path)
    cfg["body_names"] = tuple(_name(b) for b in cfg["body_names"])
    cfg["file_hosts"] = _hosts(cfg, "file_hosts", path)
    cfg["video_hosts"] = _hosts(cfg, "video_hosts", path)
    rules = []
    for rule in cfg["kind_rules"] if isinstance(cfg["kind_rules"], list) else [None]:
        if not (isinstance(rule, list) and len(rule) == 2 and all(isinstance(x, str) for x in rule)):
            raise ConfigError(f"{path}: each kind_rules entry is [kind, regex]")
        try:
            rules.append((rule[0], re.compile(rule[1], re.I)))
        except re.error as exc:
            raise ConfigError(f"{path}: kind_rules {rule[0]!r} is not a regex ({exc})") from None
    cfg["kind_rules"] = rules
    return cfg


def allowed_hosts(cfg: dict) -> tuple[str, ...]:
    """The hosts eScribe collection may ask: the portal plus any configured file host. Video hosts are never asked."""
    return (cfg["host"],) + tuple(cfg.get("file_hosts", ()))


def post_paths(cfg: dict) -> tuple[tuple[str, str], ...]:
    """The (host, path) pairs for PoliteFetcher(post_paths=...): the calendar call on the portal host only."""
    return tuple((cfg["host"], p) for p in POST_PATHS)


def calendar_request(cfg: dict, window: Window) -> tuple[str, dict]:
    """(url, payload) for one window: the calendar POST, with nothing in the body but the start and end dates.
    The window is half-open [start, end); the end date is sent as given (whether eScribe's end is inclusive is
    unknown), so a meeting on window.end may also come back: rows carry the meeting id, so a caller dedupes on it."""
    if not isinstance(window, Window) or window.end <= window.start:
        raise ValueError(f"not a window: {window!r}")
    if window.end - window.start > timedelta(days=MAX_WINDOW_DAYS):
        raise ValueError(f"window {window.start}..{window.end} is longer than {MAX_WINDOW_DAYS} days; split it")
    return (f"https://{cfg['host']}{CALENDAR_PATH}",
            {"calendarStartDate": window.start.isoformat(), "calendarEndDate": window.end.isoformat()})


def _name(s: str) -> str:
    """Whitespace trimmed and collapsed: the portal prints "City Council " with a trailing space."""
    return " ".join(str(s).split())


def _kind(cfg: dict, title: str) -> str:
    for kind, rx in cfg["kind_rules"]:
        if rx.search(title):
            return kind
    return "other"


def _doc_url(cfg: dict, raw, mid: str, log: list) -> str | None:
    """A document link resolved against the portal host. Kept only when it is https on the portal host (or a
    configured file host), with no user info or port; anything else is dropped and logged."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        url = urllib.parse.urljoin(f"https://{cfg['host']}/", raw.strip())
        p = urllib.parse.urlsplit(url)
        port = p.port
    except ValueError:
        log.append(f"escribe/bad-document-url: {raw!r} (meeting {mid})")
        return None
    host = plain_hostname(p.netloc)
    if p.scheme != "https" or port is not None or "@" in p.netloc or host is None:
        log.append(f"escribe/bad-document-url: {raw!r} (meeting {mid})")
        return None
    if host != cfg["host"] and host not in cfg.get("file_hosts", ()):
        log.append(f"escribe/off-host-document: {url} (meeting {mid})")
        return None
    return url


def _video_url(cfg: dict, raw, mid: str, log: list) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        p = urllib.parse.urlsplit(raw.strip())
        port = p.port
    except ValueError:
        port = -1
    host = plain_hostname(p.netloc) if port is None else None
    if p.scheme != "https" or host is None or "@" in p.netloc or not host_matches(host, cfg.get("video_hosts", ())):
        log.append(f"escribe/video-host-not-listed: {raw!r} (meeting {mid})")
        return None
    return raw.strip()


def _pick(cfg: dict, docs: list, types: tuple, mid: str, log: list) -> str | None:
    """The first document of the wanted types (in the config's order), a PDF before HTML."""
    for t in types:
        of_type = [d for d in docs if d.get("Type") == t]
        of_type.sort(key=lambda d: 0 if str(d.get("Format", "")).lower() == ".pdf" else 1)   # stable: answer order
        for d in of_type:
            url = _doc_url(cfg, d.get("Url"), mid, log)
            if url:
                return url
    return None


def listing_rows(cfg: dict, answer: dict, log: list | None = None) -> list[dict]:
    """A calendar answer -> listing rows (shared row shape, source "escribe"), in answer order, one per meeting id.
    Meetings of other bodies are skipped. `log` (optional) collects one line per dropped meeting or link."""
    log = [] if log is None else log
    if not isinstance(answer, dict) or not isinstance(answer.get("d"), list):
        raise AnswerError('calendar answer is not {"d": [meeting, ...]}')
    rows, seen = [], set()
    for m in answer["d"]:
        if not isinstance(m, dict):
            raise AnswerError("calendar answer: a meeting is not an object")
        title = _name(m.get("MeetingName") or "")
        if title not in cfg["body_names"]:
            continue
        mid = str(m.get("ID") or "").strip().lower()
        if not GUID_RE.match(mid):
            log.append(f"escribe/bad-meeting-id: {m.get('ID')!r} ({title})")
            continue
        start = START_RE.match(str(m.get("StartDate") or ""))
        try:
            when = datetime(*(int(x) for x in start.groups())) if start else None
        except ValueError:
            when = None
        if when is None:
            log.append(f"escribe/bad-start-date: {m.get('StartDate')!r} (meeting {mid})")
            continue
        if mid in seen:
            continue
        seen.add(mid)
        docs = [d for d in (m.get("MeetingDocumentLink") or []) if isinstance(d, dict)]
        video = next((d.get("Url") for d in docs if d.get("Type") == "Video"), None)
        rows.append({
            "date": when.date().isoformat(),
            "title": title,
            "kind": _kind(cfg, title),
            "agenda_id": f"escribe-{mid}",
            "agenda_url": _pick(cfg, docs, cfg["agenda_types"], mid, log),
            "minutes_url": _pick(cfg, docs, cfg["minutes_types"], mid, log),
            "video_url": _video_url(cfg, video, mid, log),
            "source": SOURCE,
            "event_id": mid,
            "official_page": _doc_url(cfg, m.get("Url"), mid, log),
            "start_time": when.strftime("%H:%M"),
        })
    return rows

