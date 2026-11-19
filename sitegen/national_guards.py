"""Daylight Digest shared guards (docs/architecture/daylight-national.md 3.5 and 6; task B14): the rules every outside
value passes before it reaches a digest page, a feed file, a path or a tag, in the builder and in the collector alike.

Security findings 4 (`national/url-scheme-untrusted`) and 12 (`national/untrusted-size`):
- `allowed_url`: an outside URL is kept only if `config.https_link` passes, it has no user name, password or port but
  443, and, for a platform other than daylight, its host is on that platform's allowlist. Else "" (the feed field
  becomes null and the page falls back to the directory's `official_url`: `link_or_official`).
- `checked_id` / `checked_meeting_id`: an id that becomes a path or a tag matches the id regex first.
- `clean_text`: control characters and bidi overrides stripped (and counted), whitespace joined.
- `clean_feed`: the above on every field of a `daylight-upcoming/1` feed, plus the caps: item text cut at 2,000
  characters (`"cut": true`), 150 items per meeting, 60 meetings per government. It cleans and never decides.
- `is_shown` / `bind_feed` (section 11.2, `privacy-withhold/national-prefix`): the one predicate every consumer calls
  before reading or publishing item text, and the last gate before any feed is written (BindError on a feed that is
  not the entry's; items stripped and counted unless the entry is shown under the feed's `review`).

`host_ok_problem` / `host_ok_valid` (Brian's rule R5, security finding 7, `national/r5-not-enforced`): an entry on any
platform but daylight is read only with a valid `host_ok: {date, link}` (exactly those keys, a strict YYYY-MM-DD date
no later than today, a link on github.com/gn0sh/ or claude.ai: `national/r5-self-attested`, S2a finding 7). The
directory loader and the collector both call it, so the two cannot drift. `allowed_url` also refuses any URL longer
than MAX_URL (`national/url-unbounded`, S2a finding 6).

Imports only `sitegen.config` (which imports no other sitegen module) and the standard library, so `sitegen.national`
and the collector (`collector/national/`, M2) both import it without a cycle.
"""
from __future__ import annotations

import copy
import re
import unicodedata
from dataclasses import dataclass, fields
from datetime import date, datetime
from urllib.parse import unquote, urlsplit

from . import config

# Ids (3.1): `<layer>-<GEOID>`, the GEOID's digit count fixed per layer (Census TIGER/Line GEOID structure:
# state 2 + place 5, state 2 + county 3, state 2 + county 3 + cousub 5, state 2 + LEA 5).
GEOID_DIGITS = {"place": 7, "county": 5, "cousub": 10, "sdu": 7, "sds": 7, "sde": 7}
ID_RE = re.compile(r"^(place|county|cousub|sdu|sds|sde)-([0-9]{5,10})$")
# A meeting id (3.5, e.g. `2026-12-14-formal`) becomes part of an ICS UID and may become a fragment or file name.
MEETING_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")

LEGISTAR_API_HOST = "webapi.legistar.com"

# C0 controls, DEL, C1 controls, the bidi marks, embeddings, overrides and isolates (LRM, RLM, ALM, LRE..RLO,
# LRI..PDI), invisible characters (soft hyphen, zero-width space/joiners, word joiner and invisible operators, BOM,
# tag characters) and lone surrogates. They never belong in a curated name (refused there) or a URL (refused), and
# are stripped from outside text (counted).
BAD_TEXT_RE = re.compile("[\x00-\x1f\x7f-\x9f\xad\u061c\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069"
                         "\ufeff\ud800-\udfff\U000e0000-\U000e007f]")
# Whitespace controls are word breaks in source text: they become a space (text is whitespace joined), not a strip.
_WS_CONTROLS = "\t\n\v\f\r"

MAX_ITEM_TEXT = 2_000        # characters per item text; longer is cut at the cap and marked "cut": true
MAX_TEXT = 2_000             # characters for any other text field read from outside (cut silently, counted)
MAX_ITEMS = 150              # items per meeting
MAX_MEETINGS = 60            # meetings per government
MAX_URL = 2_000              # characters of any outside URL kept (national/url-unbounded, S2a finding 6)


class UnsafeIdError(ValueError):
    """An id that would become a path or a tag does not match the id regex."""


def id_layer(gov_id) -> str | None:
    """The layer of a well-formed id (`place-4715160` -> "place"), else None: the prefix and the layer's GEOID length."""
    m = ID_RE.fullmatch(gov_id) if isinstance(gov_id, str) else None
    if not m or len(m.group(2)) != GEOID_DIGITS[m.group(1)]:
        return None
    return m.group(1)


def checked_id(gov_id) -> str:
    """`gov_id` when it is a well-formed government (body) id and so may become a path or a tag; else UnsafeIdError."""
    if id_layer(gov_id) is None:
        raise UnsafeIdError(f"not a government id: {gov_id!r}")
    return gov_id


def checked_meeting_id(meeting_id) -> str:
    """`meeting_id` when it matches MEETING_ID_RE (it becomes part of a UID or a file name); else UnsafeIdError."""
    if not isinstance(meeting_id, str) or not MEETING_ID_RE.fullmatch(meeting_id):
        raise UnsafeIdError(f"not a meeting id: {meeting_id!r}")
    return meeting_id


def allowed_url(url, platform: str = "daylight", client: str | None = None) -> str:
    """`url` when a curated or outside URL may be linked: `config.https_link` passes, it has no user name or password
    and no port but 443, and, for a platform other than daylight, its host is one of that platform's hosts (finding 4).
    Else "". Legistar's hosts are `webapi.legistar.com` and `<client>.legistar.com`; an unknown platform has none. A
    URL longer than MAX_URL characters is refused too (national/url-unbounded, S2a finding 6), so free-text paths or
    queries from an answer cannot ride into a feed or a proposal at any length."""
    if not isinstance(url, str) or len(url) > MAX_URL or BAD_TEXT_RE.search(url):
        return ""
    try:                                    # urlsplit raises ValueError on a bad bracket host or an NFKC netloc
        if not config.https_link(url):
            return ""
        u = urlsplit(url)
        port, host = u.port, u.hostname
    except ValueError:
        return ""
    if u.username is not None or u.password is not None or port not in (None, 443) or not host:
        return ""
    if platform == "daylight":
        return url
    if platform == "legistar":
        hosts = {LEGISTAR_API_HOST} | ({f"{client.lower()}.legistar.com"} if isinstance(client, str) and client
                                       else set())
        return url if host.lower() in hosts else ""
    return ""


HOST_OK_KEYS = frozenset({"date", "link"})
HOST_OK_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Where Brian's OK can be recorded (national/r5-self-attested, S2a finding 7): the team's GitHub (a PR, issue or
# comment under github.com/gn0sh/) or a claude.ai page. Exact hosts, so a look-alike subdomain is refused.
HOST_OK_LINK_HOSTS = {"github.com": "/gn0sh/", "claude.ai": "/"}


def _host_ok_link(link) -> bool:
    if not allowed_url(link):
        return False
    u = urlsplit(link)
    prefix = HOST_OK_LINK_HOSTS.get((u.hostname or "").lower())
    return prefix is not None and u.path.startswith(prefix) and _path_segments_plain(u.path)


def _path_segments_plain(path: str) -> bool:
    """national/r5-self-attested: no `.`/`..` segment (also percent-encoded, even twice), no empty segment (one
    trailing slash is fine) and no backslash, so `/gn0sh/../other/x` cannot climb out of the team's prefix."""
    if "\\" in path:
        return False
    once = unquote(path)
    twice = unquote(once)
    if "\\" in once or "\\" in twice:
        return False
    segments = path.split("/")[1:]
    if segments and segments[-1] == "":
        segments = segments[:-1]
    for seg in segments:
        if not seg or unquote(unquote(seg)) in (".", ".."):
            return False
    return True


def host_ok_problem(host_ok, today: date | None = None) -> tuple[str, str] | None:
    """None when `host_ok` is Brian's recorded OK for a third-party host (R5, finding 7): a mapping of exactly `date`
    (a date, or a string matching exactly YYYY-MM-DD, never later than `today`, default `date.today()`) and `link` (an
    https link `allowed_url` keeps, on github.com under /gn0sh/ or on claude.ai: national/r5-self-attested, S2a
    finding 7). Else (key, problem), the first problem found, in the words the directory loader prints."""
    if not isinstance(host_ok, dict):
        return "host_ok", "must be {date, link} (Brian's OK, R5)"
    extra = sorted(str(k) for k in host_ok if k not in HOST_OK_KEYS)
    if extra:
        return extra[0], "unknown key"
    for k in sorted(HOST_OK_KEYS):
        if k not in host_ok:
            return k, "missing"
    day = host_ok["date"]
    if isinstance(day, datetime) or not isinstance(day, (date, str)):
        return "date", "must be a date (YYYY-MM-DD)"
    if isinstance(day, str):
        if not HOST_OK_DATE_RE.fullmatch(day):           # fromisoformat also takes 20261119 and 2026-W47-4
            return "date", "must be a date (YYYY-MM-DD)"
        try:
            day = date.fromisoformat(day)
        except ValueError:
            return "date", "must be a date (YYYY-MM-DD)"
    if day > (today if today is not None else date.today()):
        return "date", "must not be later than today"
    if not _host_ok_link(host_ok["link"]):
        return "link", "must be an https link on github.com/gn0sh/ or claude.ai"
    return None


def host_ok_valid(host_ok, today: date | None = None) -> bool:
    """True when `host_ok` is a valid recorded OK (`host_ok_problem` finds nothing)."""
    return host_ok_problem(host_ok, today) is None


def link_or_official(url, official_url: str, platform: str = "daylight", client: str | None = None) -> str:
    """The href a page shows for an outside link: `url` if `allowed_url` keeps it, else the directory's
    `official_url` (already checked by the directory loader)."""
    return allowed_url(url, platform, client) or official_url


@dataclass
class GuardCounts:
    """What the guards changed in one feed, for the run log (finding 12)."""
    chars_stripped: int = 0     # control and bidi characters removed
    texts_cut: int = 0          # item texts cut at MAX_ITEM_TEXT, other texts cut at MAX_TEXT
    items_dropped: int = 0      # items past MAX_ITEMS, and items that are not objects
    meetings_dropped: int = 0   # meetings past MAX_MEETINGS or with a bad id
    urls_dropped: int = 0       # URLs refused by allowed_url (field set to null)

    def any(self) -> bool:
        return any(getattr(self, f.name) for f in fields(self))

    def summary(self) -> str:
        """One log line, counts only (never the text itself)."""
        return ", ".join(f"{f.name}={getattr(self, f.name)}" for f in fields(self))


def clean_text(value) -> tuple[str, int]:
    """(text, stripped): control characters and bidi overrides removed (their number in `stripped`), whitespace
    controls turned into spaces, then whitespace joined. Nothing else changes (3.5: the source's words)."""
    if not isinstance(value, str):
        return "", 0
    spaced = value.translate({ord(c): " " for c in _WS_CONTROLS})
    text, stripped = BAD_TEXT_RE.subn("", spaced)
    return " ".join(text.split()), stripped


def _extends(c: str) -> bool:
    """True for a character that belongs to the one before it: a combining mark, a variation selector or an emoji
    skin-tone modifier."""
    o = ord(c)
    return (unicodedata.category(c) in ("Mn", "Mc", "Me") or 0xFE00 <= o <= 0xFE0F or 0xE0100 <= o <= 0xE01EF
            or 0x1F3FB <= o <= 0x1F3FF)


def cut_text(text: str, limit: int = MAX_ITEM_TEXT) -> tuple[str, bool]:
    """(text, cut): `text` cut at `limit` characters when longer, backed off so the cut never separates a combining
    mark, variation selector or modifier from its base, or splits a zero-width-joiner sequence."""
    if len(text) <= limit:
        return text, False
    i = limit
    while i > 0 and (_extends(text[i]) or text[i] == "\u200d" or text[i - 1] == "\u200d"):
        i -= 1
    return text[:i or limit].rstrip(), True


def _clean_str(obj: dict, key: str, counts: GuardCounts) -> None:
    if isinstance(obj.get(key), str):
        text, stripped = clean_text(obj[key])
        text, cut = cut_text(text, MAX_TEXT)
        counts.chars_stripped += stripped
        counts.texts_cut += cut
        obj[key] = text


def _clean_url(obj: dict, key: str, platform: str, client, counts: GuardCounts) -> None:
    if key in obj and obj[key] is not None:
        if not allowed_url(obj[key], platform, client):
            obj[key] = None
            counts.urls_dropped += 1


def _clean_item(item: dict, platform: str, client, counts: GuardCounts) -> dict:
    text, stripped = clean_text(item.get("text"))
    text, cut = cut_text(text)
    counts.chars_stripped += stripped
    item["text"] = text
    if cut:
        item["cut"] = True
        counts.texts_cut += 1
    _clean_str(item, "number", counts)
    if isinstance(item.get("source"), dict):
        _clean_url(item["source"], "url", platform, client, counts)
    return item


def _clean_meeting(m: dict, platform: str, client, counts: GuardCounts) -> dict:
    for key in ("title", "time"):
        _clean_str(m, key, counts)
    _clean_url(m, "meeting_url", platform, client, counts)
    agenda = m.get("agenda")
    if isinstance(agenda, dict):
        _clean_url(agenda, "url", platform, client, counts)
        _clean_str(agenda, "status_as_posted", counts)
    items = m.get("items")
    if isinstance(items, list):
        good = [i for i in items if isinstance(i, dict)]
        counts.items_dropped += len(items) - min(len(good), MAX_ITEMS)
        m["items"] = [_clean_item(i, platform, client, counts) for i in good[:MAX_ITEMS]]
    return m


def clean_feed(feed: dict, platform: str = "daylight", client: str | None = None) -> tuple[dict, GuardCounts]:
    """A cleaned copy of a `daylight-upcoming/1` feed and what changed. Called by the collector before it writes a feed
    and by the builder before it renders one (3.5), with the government's directory platform and client.

    Raises UnsafeIdError when `feed` is not an object or `body.id` is not a government id (it names the feed's file
    and page). A meeting with a bad id is dropped. Every URL (`official_url`, `meeting_url`, `agenda.url`,
    `items[].source.url`) that `allowed_url` refuses becomes null; every text field is stripped of control, bidi and
    invisible characters; item text is cut at 2,000 characters (`"cut": true`); items that are not objects are
    dropped, then at most 150 items per meeting and 60 meetings (the first ones, soonest first) are kept. Keys
    the guards do not know are copied unchanged (the schema check judges them)."""
    if not isinstance(feed, dict):
        raise UnsafeIdError(f"not a feed: {type(feed).__name__}")
    out = copy.deepcopy(feed)
    counts = GuardCounts()
    body = out.get("body") if isinstance(out.get("body"), dict) else {}
    checked_id(body.get("id"))
    _clean_str(body, "name", counts)
    _clean_url(body, "official_url", platform, client, counts)
    meetings = out.get("meetings")
    if isinstance(meetings, list):
        kept = []
        for m in meetings:
            if len(kept) == MAX_MEETINGS:
                counts.meetings_dropped += 1
                continue
            if not isinstance(m, dict) or not isinstance(m.get("id"), str) or not MEETING_ID_RE.fullmatch(m["id"]):
                counts.meetings_dropped += 1
                continue
            kept.append(_clean_meeting(m, platform, client, counts))
        out["meetings"] = kept
    return out, counts


# --- the shown gate (architecture 11.2; invariant privacy-withhold/national-prefix) -----------------------------

REVIEW_RE = re.compile(r"^[0-9a-f]{64}$")


class BindError(ValueError):
    """A feed is not the directory entry's: another body id or platform. Nothing of it may be written."""


def is_shown(entry) -> bool:
    """The one predicate every consumer calls (11.1 row 13): item text may be read and published for this loaded
    directory entry. True only for `items: shown` with a `review` digest (load_directory sets it only after the
    entry's whole-entry digest matched its SHOWN_REVIEWED row)."""
    return (isinstance(entry, dict) and entry.get("items") == "shown" and isinstance(entry.get("review"), str)
            and bool(REVIEW_RE.fullmatch(entry["review"])))


@dataclass
class BindCounts:
    """What bind_feed stripped, for the run log (counts only, never text). Each counts meetings that carried item
    content (items or an item_count) and were emptied."""
    withheld_stripped: int = 0   # the entry is not shown: a bug upstream (D2 fails the deploy on > 0)
    review_mismatch: int = 0     # the entry is shown, the feed was read under another review (expected once after a
                                 # reviewed change; logged)

    def summary(self) -> str:
        return ", ".join(f"{f.name}={getattr(self, f.name)}" for f in fields(self))


FEED_KEYS = ("schema", "review", "body", "checked_at", "last_ok_at", "meetings")   # daylight-upcoming/1, top level
WITHHELD_TITLE = "Meeting"      # the fixed title of every meeting of a government that is not shown
MAX_ECHO = 40                   # characters of an outside value an error message may repeat


def _echo_id(value) -> str:
    """An id for an error message: the id when id_layer accepts it, else `<bad id>` (security
    `privacy-withhold/error-echo`)."""
    return value if id_layer(value) else "<bad id>"


def _echo(value) -> str:
    text = repr(value)
    return text if len(text) <= MAX_ECHO else text[:MAX_ECHO] + "..."


def _body(entry: dict) -> dict:
    """The feed's `body`, every field from the directory entry (never from the feed)."""
    platform = entry.get("platform")
    keys = entry.get(platform) if isinstance(platform, str) and isinstance(entry.get(platform), dict) else {}
    return {"id": entry.get("gov"), "name": entry.get("body_name"),
            "tz": keys.get("tz") or config.SITE["site_timezone"], "official_url": entry.get("official_url"),
            "platform": platform, "full_url": keys.get("full_url") if platform == "daylight" else None}


def bind_feed(feed: dict, entry: dict) -> tuple[dict, BindCounts]:
    """The last gate before any write of a `daylight-upcoming/1` feed (11.2). Returns a copy and what was stripped.

    Raises BindError when `feed` is not an object with a `body` and a list of meeting objects, holds a top-level key
    the schema does not name, or its `body.id` or `body.platform` is not the entry's (`privacy-withhold/bind-shape`).
    `body` is rewritten from the directory entry (id, name, tz, official_url, platform, full_url). Items are kept only
    when `is_shown(entry)` and the feed's `review` equals the entry's; otherwise every meeting is emptied (`items: []`,
    `item_count: null`, `items_withheld: true`) and `review` set to null. For an entry that is not shown, each
    meeting's `title` is the fixed WITHHELD_TITLE (`title_ours: true`) and `time` and `agenda.status_as_posted` are
    null, so no free text from the source is published for it (`privacy-withhold/free-text-outside-items`). A written
    `review` is non-null only when the entry is shown under that review. Error messages repeat an id only when
    id_layer accepts it and any other value only up to MAX_ECHO characters."""
    if not isinstance(entry, dict):
        raise BindError("not a directory entry")
    gov = _echo_id(entry.get("gov"))
    body = feed.get("body") if isinstance(feed, dict) else None
    if not isinstance(body, dict):
        raise BindError(f"{gov}: not a feed with a body")
    extra = sorted(str(k) for k in feed if k not in FEED_KEYS)
    if extra:
        raise BindError(f"{gov}: unknown top-level key {_echo(extra[0])}")
    meetings = feed.get("meetings")
    if not isinstance(meetings, list) or not all(isinstance(m, dict) for m in meetings):
        raise BindError(f"{gov}: meetings must be a list of objects")
    if body.get("id") != entry.get("gov"):
        raise BindError(f"feed body.id {_echo_id(body.get('id'))} is not the entry's gov {gov}")
    if body.get("platform") != entry.get("platform"):
        raise BindError(f"{gov}: feed platform {_echo(body.get('platform'))} is not the entry's "
                        f"{_echo(entry.get('platform'))}")
    out = copy.deepcopy(feed)
    out["body"] = _body(entry)
    counts = BindCounts()
    shown = is_shown(entry)
    if shown and out.get("review") == entry["review"]:
        return out, counts
    for m in out["meetings"]:
        if m.get("items") or m.get("item_count") is not None:
            if shown:
                counts.review_mismatch += 1
            else:
                counts.withheld_stripped += 1
        m["items"], m["item_count"], m["items_withheld"] = [], None, True
        if not shown:
            m["title"], m["title_ours"], m["time"] = WITHHELD_TITLE, True, None
            if isinstance(m.get("agenda"), dict):
                m["agenda"]["status_as_posted"] = None
    out["review"] = None
    return out, counts
