"""Legistar source (expansion proof of concept, docs/expansion/daylight-template.md): one body's meetings and
roll-call votes from a city's public Legistar Web API (webapi.legistar.com/v1/<client>/...).

NOT wired into the daily update. Nothing here runs against a live host until a city pack passes the per-city launch
checklist (robots.txt, terms, the owner's go-ahead for the city). Everything locality-specific comes from
config/cities/<city>/legistar.yml, loaded and checked by load_config(); the code holds no locality literal.

Two pieces a new city needs:
- listing rows in the Agenda Center / CivicClerk row shape (date, title, kind, agenda_id, agenda_url, minutes_url,
  plus source, event id and video URL), so collector/city_build.py could build them alike;
- vote rows in schema/facts.schema.json `vote` shape (official_id null until names are matched, raw_name, value,
  raw_value as the clerk recorded it). Legistar's votes are the clerk's own entries, but the minutes stay the official
  record: a Legistar vote is shown "not confirmed" until the verifier reads the same vote in the minutes PDF.

launch_windows() is the "launch with a year, backfill as compute allows" plan: the newest year first, then one older
year per run until the configured earliest date. It now lives in cities/plan.py (shared by every portal type); the
names Window and launch_windows stay importable from here.
"""
from __future__ import annotations

import re
import urllib.parse
from datetime import date
from pathlib import Path

import yaml

from cities.plan import Window, launch_windows  # noqa: F401  (moved to the shared planner; names kept here)

ROOT = Path(__file__).resolve().parent.parent
SOURCE = "legistar"
API_HOST = "webapi.legistar.com"
CLIENT_RE = re.compile(r"^[a-z0-9-]{2,40}$")
VOTE_VALUES = ("yes", "no", "abstain", "other")        # schema/facts.schema.json vote.value
REQUIRED = ("city", "client", "body_name", "official_title", "launch_days", "earliest", "vote_values", "kind_rules")


class ConfigError(ValueError):
    pass


def load_config(path: str | Path) -> dict:
    """Read and check a city's legistar.yml. A missing or malformed key fails loudly."""
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    missing = [k for k in REQUIRED if k not in cfg]
    if missing:
        raise ConfigError(f"{path}: missing {', '.join(missing)}")
    if not CLIENT_RE.match(str(cfg["client"])):
        raise ConfigError(f"{path}: client must be the Legistar client name (lowercase letters, digits, -)")
    if not isinstance(cfg["launch_days"], int) or not 30 <= cfg["launch_days"] <= 400:
        raise ConfigError(f"{path}: launch_days must be a whole number of days, 30 to 400")
    cfg["earliest"] = _as_date(cfg["earliest"], path, "earliest")
    for raw, value in cfg["vote_values"].items():
        if value not in VOTE_VALUES:
            raise ConfigError(f"{path}: vote_values[{raw!r}] must be one of {VOTE_VALUES}")
    rules = []
    for rule in cfg["kind_rules"]:
        if not (isinstance(rule, list) and len(rule) == 2):
            raise ConfigError(f"{path}: each kind_rules entry is [kind, regex]")
        rules.append((rule[0], re.compile(rule[1], re.I)))
    cfg["kind_rules"] = rules
    return cfg


def _as_date(value, path, key) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ConfigError(f"{path}: {key} must be YYYY-MM-DD") from exc


def events_url(cfg: dict, window: Window) -> str:
    """The OData events query for one body and one window (Legistar's documented filter syntax)."""
    body = cfg["body_name"].replace("'", "''")
    flt = (f"EventBodyName eq '{body}' and EventDate ge datetime'{window.start.isoformat()}' "
           f"and EventDate lt datetime'{window.end.isoformat()}'")
    q = urllib.parse.urlencode({"$filter": flt, "$orderby": "EventDate asc"}, quote_via=urllib.parse.quote)
    return f"https://{API_HOST}/v1/{cfg['client']}/events?{q}"


def items_url(cfg: dict, event_id: int) -> str:
    return f"https://{API_HOST}/v1/{cfg['client']}/events/{int(event_id)}/eventitems?AgendaNote=1&MinutesNote=1"


def votes_url(cfg: dict, event_item_id: int) -> str:
    return f"https://{API_HOST}/v1/{cfg['client']}/eventitems/{int(event_item_id)}/votes"


def _kind(cfg: dict, title: str) -> str:
    for kind, rx in cfg["kind_rules"]:
        if rx.search(title):
            return kind
    return "other"


def _https(url) -> str | None:
    """Keep a document or video link only when it is a full https URL (a bare path is never guessed)."""
    if isinstance(url, str) and url.startswith("https://") and urllib.parse.urlsplit(url).hostname:
        return url
    return None


def listing_rows(cfg: dict, events: list[dict]) -> list[dict]:
    """Legistar events -> listing rows in the Agenda Center / CivicClerk row shape. An event of another body is
    skipped (the query asks for one body, but the API's answer is checked, never trusted)."""
    rows = []
    for ev in events:
        if ev.get("EventBodyName") != cfg["body_name"]:
            continue
        day = str(ev.get("EventDate", ""))[:10]
        try:
            date.fromisoformat(day)
        except ValueError:
            continue
        title = (ev.get("EventComment") or "").strip()
        title = f"{cfg['body_name']}{' - ' + title if title else ''}"
        rows.append({
            "date": day,
            "title": title,
            "kind": _kind(cfg, title),
            "agenda_id": f"legistar-{int(ev['EventId'])}",
            "agenda_url": _https(ev.get("EventAgendaFile")),
            "minutes_url": _https(ev.get("EventMinutesFile")),
            "video_url": _https(ev.get("EventVideoPath")),
            "source": SOURCE,
            "event_id": int(ev["EventId"]),
            "official_page": _https(ev.get("EventInSiteURL")),
        })
    return rows


def roll_call_items(items: list[dict]) -> list[dict]:
    """The agenda items the clerk marked as a roll call (EventItemRollCallFlag 1). Only these have per-member votes."""
    return [it for it in items if it.get("EventItemRollCallFlag") == 1]


def vote_rows(cfg: dict, votes: list[dict]) -> list[dict]:
    """Legistar votes -> schema `vote` rows. A vote label not in the city's vote_values map is kept as "other" with
    its raw label, so nothing is silently read as yes or no. official_id stays null until names are matched."""
    out = []
    for v in votes:
        name = (v.get("VotePersonName") or "").strip()
        raw = (v.get("VoteValueName") or "").strip()
        if not name or not raw:
            continue
        out.append({"official_id": None, "raw_name": name,
                    "value": cfg["vote_values"].get(raw, "other"), "raw_value": raw})
    return out


def allowed_hosts(cfg: dict) -> tuple[str, ...]:
    """The hosts a city's Legistar collection may ask: the API plus the city's file host (agenda/minutes PDFs)."""
    return (API_HOST, f"{cfg['client']}.legistar.com") + tuple(cfg.get("extra_hosts", ()))
