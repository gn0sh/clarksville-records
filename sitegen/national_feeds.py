"""Daylight Digest calendar and feed writers (docs/architecture/daylight-national.md 3.6; task C4, finding 3,
`national/feed-ics-injection`). Both read one `daylight-upcoming/1` feed (3.5), already through
`national_guards.clean_feed`/`bind_feed`. Nothing builds these files yet: M4 ships them.

ICS (`digest/<st>/<body id>.ics`) is written here, line by line, never from a template:
- every TEXT value goes through `text()`: control characters removed first (`feeds.clean`, then the guards'
  BAD_TEXT_RE for what XML allows but a calendar must not carry: DEL, C1, bidi and invisible marks), whitespace
  controls are word breaks, then RFC 5545 3.3.11 escaping (backslash, semicolon, comma, newline). A value can never
  end its line, so `\\r\\nBEGIN:VEVENT` in a title is text inside one SUMMARY, not a second event;
- every content line is folded at 75 octets (RFC 5545 3.1), never inside a UTF-8 character;
- one VEVENT per meeting; UID `<body id>/<meeting id>@daylight.gnoshcodes.com` (both ids full-match the guards'
  regexes; a meeting with a bad id or date is left out), so it is the same on every run;
- no item text (3.6): SUMMARY is the body name and meeting title, DESCRIPTION a fixed label and the agenda link;
- SEQUENCE comes from `sequences()`: it bumps when a meeting's agenda state or URL changes from the previous run.
- A posted time that parses becomes a UTC DTSTART (deviation from 3.6's `TZID=`, recorded there: RFC 5545 3.2.19
  requires a VTIMEZONE for every TZID, which this writer does not emit); one that does not parse gives an all-day
  event with the time in the SUMMARY as posted.

Atom (`digest/<st>/<body id>.xml`) is built by `sitegen/feeds.py render` (its escaping, ids and date rules): one entry
per meeting whose agenda is posted, id `<feed id><body id>/meeting/<meeting id>/agenda`, dated when the agenda was
first seen.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from . import config, feeds
from . import national_guards as guards

UID_DOMAIN = "daylight.gnoshcodes.com"
PRODID = "-//Daylight Digest//daylight-upcoming/1//EN"
FOLD_OCTETS = 75
CRLF = "\r\n"

# Fixed labels (no outside text). DESCRIPTION is one of these, then the agenda link when there is one.
AGENDA_LABELS = {
    "final": "Agenda posted",
    "not-final": "Agenda posted, not final yet",
    "not-read": "Agenda posted",
    "not-posted": "Agenda not posted yet",
}
ATOM_ABOUT = "Each meeting agenda when it is posted."

_ESCAPES = str.maketrans({"\\": "\\\\", ";": "\\;", ",": "\\,", "\n": "\\n"})
_TIME_12 = re.compile(r"(\d{1,2})(?::([0-5]\d))?\s*([ap])\.?\s*m\.?", re.IGNORECASE)
_TIME_24 = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")


def text(value) -> str:
    """A TEXT property value, safe on one content line: controls removed (feeds.clean, then the guards' set),
    whitespace joined, then backslash, semicolon, comma and newline escaped (RFC 5545 3.3.11)."""
    if not isinstance(value, str):
        return ""
    cleaned = feeds.clean(value)
    cleaned = " ".join(guards.BAD_TEXT_RE.sub("", cleaned).split())
    return cleaned.translate(_ESCAPES)


def fold(line: str) -> str:
    """One content line folded at 75 octets (RFC 5545 3.1): each continuation starts with a space, so it carries at
    most 74 octets of the line; a break never falls inside a character's UTF-8 bytes."""
    parts, cur, size, limit = [], [], 0, FOLD_OCTETS
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > limit:
            parts.append("".join(cur))
            cur, size, limit = [], 0, FOLD_OCTETS - 1
        cur.append(ch)
        size += n
    parts.append("".join(cur))
    return (CRLF + " ").join(parts)


def uid(body_id: str, meeting_id: str) -> str:
    """The event's UID: the same for one meeting on every run. Raises guards.UnsafeIdError for a bad id."""
    return f"{guards.checked_id(body_id)}/{guards.checked_meeting_id(meeting_id)}@{UID_DOMAIN}"


def parse_time(posted) -> time | None:
    """A posted time string ("6:00 PM", "9 a.m.", "18:30") as a wall-clock time, else None (left as posted)."""
    if not isinstance(posted, str):
        return None
    s = posted.strip()
    m = _TIME_12.fullmatch(s)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if not 1 <= hour <= 12:
            return None
        return time(hour % 12 + (12 if m.group(3).lower() == "p" else 0), minute)
    m = _TIME_24.fullmatch(s)
    return time(int(m.group(1)), int(m.group(2))) if m else None


def _utc_stamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _instant(value) -> datetime:
    """checked_at as an aware datetime; 1970 when missing or unreadable (DTSTAMP is required, and must not move)."""
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _meetings(feed: dict) -> list[tuple[str, date, dict]]:
    """(uid, date, meeting) for each meeting with a good id and date, in the feed's order. A bad body id raises
    guards.UnsafeIdError (it would become every UID and the file name)."""
    body_id = guards.checked_id((feed.get("body") or {}).get("id"))
    out = []
    for m in feed.get("meetings") or []:
        if not isinstance(m, dict) or not isinstance(m.get("id"), str) or not guards.MEETING_ID_RE.fullmatch(m["id"]):
            continue
        try:
            day = date.fromisoformat(m.get("date") or "")
        except (TypeError, ValueError):
            continue
        out.append((uid(body_id, m["id"]), day, m))
    return out


def _agenda_key(m: dict) -> str:
    a = m.get("agenda") or {}
    return f"{a.get('state') or ''} {config.https_link(a.get('url'))}"


def sequences(feed: dict, previous: dict | None = None) -> dict[str, dict]:
    """{uid: {"sequence", "agenda"}} for this run: a meeting's SEQUENCE is its previous one, plus one when its agenda
    state or URL changed; a new meeting starts at 0. The caller keeps the result for the next run."""
    previous = previous or {}
    out = {}
    for u, _, m in _meetings(feed):
        key = _agenda_key(m)
        old = previous.get(u)
        seq = 0 if old is None else int(old.get("sequence", 0)) + (old.get("agenda") != key)
        out[u] = {"sequence": seq, "agenda": key}
    return out


def _vevent(u: str, day: date, m: dict, body: dict, stamp: str, page_url: str, seq: int) -> list[str]:
    title = m.get("title") or guards.WITHHELD_TITLE
    summary = f"{body.get('name') or ''}: {title}"
    at = parse_time(m.get("time"))
    if at is None:
        start = f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}"
        if isinstance(m.get("time"), str) and m["time"].strip():
            summary += f", {m['time']}"
    else:
        zone = ZoneInfo(body.get("tz") or config.SITE["site_timezone"])
        start = f"DTSTART:{_utc_stamp(datetime.combine(day, at, zone))}"
    agenda = m.get("agenda") or {}
    link = config.https_link(agenda.get("url"))
    description = AGENDA_LABELS.get(agenda.get("state"), AGENDA_LABELS["not-posted"]) + (f": {link}" if link else ".")
    lines = ["BEGIN:VEVENT", f"UID:{u}", f"DTSTAMP:{stamp}", start, f"SEQUENCE:{seq}",
             f"SUMMARY:{text(summary)}", f"DESCRIPTION:{text(description)}"]
    if config.https_link(page_url):
        lines.append(f"URL:{page_url}")
    return lines + ["END:VEVENT"]


def render_ics(feed: dict, page_url: str, seqs: dict[str, dict] | None = None) -> bytes:
    """The calendar file for one government's feed. `page_url`: the coming-up page's absolute https URL (left out
    otherwise). `seqs`: `sequences()` for this run (every SEQUENCE 0 without it)."""
    body = feed.get("body") or {}
    stamp = _utc_stamp(_instant(feed.get("checked_at")))
    seqs = seqs or {}
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for u, day, m in _meetings(feed):
        lines += _vevent(u, day, m, body, stamp, page_url, (seqs.get(u) or {}).get("sequence", 0))
    lines.append("END:VCALENDAR")
    return "".join(fold(line) + CRLF for line in lines).encode("utf-8")


def atom_entries(feed: dict, page_href: str, first: dict | None = None) -> list[dict]:
    """feeds.render entries: one per meeting whose agenda is posted. `first`: {agenda URL: when first seen}; without
    a row, the feed's checked_at."""
    body = feed.get("body") or {}
    out = []
    for _, day, m in _meetings(feed):
        agenda = m.get("agenda") or {}
        if agenda.get("state") in (None, "not-posted"):
            continue
        link = config.https_link(agenda.get("url"))
        when = (first or {}).get(link) or _instant(feed.get("checked_at"))
        title = m.get("title") or guards.WITHHELD_TITLE
        out.append({
            "id": f"{guards.checked_id(body.get('id'))}/meeting/{guards.checked_meeting_id(m['id'])}/agenda",
            "body": body["id"],
            "title": f"{body.get('name') or ''}: {title}",
            "updated": when,
            "href": page_href,
            "source": link,
            "summary": f"{body.get('name') or ''}, {day.isoformat()}. {AGENDA_LABELS[agenda['state']]}.",
            "sort": (day.isoformat(), m["id"]),
        })
    return out


def render_atom(feed: dict, st: str, cfg: dict | None = None, first: dict | None = None) -> bytes:
    """The Atom file `digest/<st>/<body id>.xml`, through feeds.render (ids, escaping and dates as every feed)."""
    body_id = guards.checked_id((feed.get("body") or {}).get("id"))
    if not re.fullmatch(r"[a-z]{2}", st or ""):
        raise guards.UnsafeIdError(f"state code {st!r} is not two lowercase letters")
    base = f"digest/{st}/{body_id}"
    info = {"file": f"{base}.xml", "title": f"{feed['body'].get('name') or ''}: meeting agendas", "about": ATOM_ABOUT}
    return feeds.render(info, atom_entries(feed, f"{base}.html", first), cfg, feed.get("checked_at") or "")
