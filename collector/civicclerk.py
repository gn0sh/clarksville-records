"""CivicClerk source: list one body's meetings from the portal's OData API (M4, slice 3).

The city moved its City Council agendas and minutes from the CivicPlus Agenda Center (to January 2024) to CivicClerk.
Everything locality-specific (API host, category, start date, file and video rules) comes from
config/localities/<locality>/civicclerk.yml, loaded and checked by load_config(). Decision: docs/adr/0003.

Requests go through collector.fetch.PoliteFetcher (allowlist, robots.txt before every request, 10 s per host,
honest User-Agent, GET only, a 403/429 stops the host for the run). Every listing page is cached as fetched under
<store>/civicclerk/<sha256>.json; agenda and minutes PDFs go to the content-addressed store like the Agenda Center's.

A listing row has the Agenda Center row's shape (date, title, kind, agenda_id, agenda_url, minutes_url) plus
source "civicclerk", the event id and the meeting's video URL, so collector/city_build.py builds both alike.
merge_sources() joins the two listings: one meeting per (date, kind), and each kept row names its source.
"""
from __future__ import annotations

import hashlib
import json
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCE = "civicclerk"
AGENDA_CENTER = "agenda-center"
MAX_PAGES = 200                     # a listing that pages on past this is not the API we know: stop, never loop


class CivicClerkConfigError(Exception):
    pass


class EventsError(Exception):
    """A listing page is not the OData page we know. Fails loudly; nothing is guessed."""


@dataclass(frozen=True)
class CivicClerkConfig:
    locality: str
    api_host: str
    category_name: str
    from_date: str
    events_url: str
    file_url: str
    agenda_types: tuple
    minutes_types: tuple
    video_hosts: tuple

    def first_url(self) -> str:
        return self.events_url.format(host=self.api_host, from_date=self.from_date,
                                      category=urllib.parse.quote(self.category_name.replace("'", "''")))

    def file(self, file_id: int) -> str:
        return self.file_url.format(host=self.api_host, file_id=int(file_id))


def config_path(locality: str = "clarksville-tn") -> Path:
    return ROOT / "config" / "localities" / locality / "civicclerk.yml"


def _need(cfg: dict, key: str, kind):
    if key not in cfg:
        raise CivicClerkConfigError(f"civicclerk.yml: missing key {key}")
    v = cfg[key]
    if not isinstance(v, kind):
        raise CivicClerkConfigError(f"civicclerk.yml: {key} must be {getattr(kind, '__name__', kind)}")
    return v


def _strs(cfg: dict, key: str) -> tuple:
    v = _need(cfg, key, list)
    if not v or not all(isinstance(s, str) and s for s in v):
        raise CivicClerkConfigError(f"civicclerk.yml: {key} must be a list of strings")
    return tuple(v)


def parse_config(cfg) -> CivicClerkConfig:
    if not isinstance(cfg, dict):
        raise CivicClerkConfigError("civicclerk.yml: not a mapping")
    host = _need(cfg, "api_host", str)
    out = CivicClerkConfig(
        locality=_need(cfg, "locality", str), api_host=host, category_name=_need(cfg, "category_name", str),
        from_date=str(_need(cfg, "from_date", str)), events_url=_need(cfg, "events_url", str),
        file_url=_need(cfg, "file_url", str), agenda_types=_strs(cfg, "agenda_types"),
        minutes_types=_strs(cfg, "minutes_types"), video_hosts=_strs(cfg, "video_hosts"))
    for key, url in (("events_url", out.first_url()), ("file_url", out.file(1))):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or parts.netloc != host:
            raise CivicClerkConfigError(f"civicclerk.yml: {key} must be https on api_host")
    if len(out.from_date) != 10 or out.from_date[4] != "-" or out.from_date[7] != "-":
        raise CivicClerkConfigError("civicclerk.yml: from_date must be YYYY-MM-DD")
    return out


def load_config(path: Path | None = None) -> CivicClerkConfig:
    p = Path(path) if path else config_path()
    return parse_config(yaml.safe_load(p.read_text(encoding="utf-8")))


# ------------------------------------------------------------------ listing
def video_url(event: dict, cfg: CivicClerkConfig) -> str | None:
    """The event's MP4 as a public https URL on a configured host, else None (a bare storage path is not guessed)."""
    raw = (event.get("mediaSourcePathMp4") or "").strip()
    parts = urllib.parse.urlsplit(raw)
    if parts.scheme == "https" and parts.netloc.lower() in cfg.video_hosts and parts.path.lower().endswith(".mp4"):
        return raw
    return None


def _pick(files: list[dict], types: tuple) -> tuple[dict | None, int]:
    """The newest published file of these types (by publishOn, then fileId), and how many there were."""
    c = [f for f in files if f.get("type") in types and isinstance(f.get("fileId"), int) and f["fileId"] > 0]
    if not c:
        return None, 0
    return max(c, key=lambda f: (f.get("publishOn") or "", f["fileId"])), len(c)


def parse_events(page: dict, cfg: CivicClerkConfig, kind_of) -> tuple[list[dict], list[dict]]:
    """One OData page -> (rows, problems). kind_of(title) is the Agenda Center config's kind rule, so both sources
    name kinds alike. Events of another category are left out (the filter should already have done it)."""
    if not isinstance(page, dict) or not isinstance(page.get("value"), list):
        raise EventsError("events page has no 'value' list: the API changed. Not guessing.")
    rows, problems = [], []
    for e in page["value"]:
        if not isinstance(e, dict) or e.get("categoryName") != cfg.category_name or e.get("isDeleted"):
            continue
        start, title, eid = e.get("startDateTime") or "", (e.get("eventName") or "").strip(), e.get("id")
        if len(start) < 10 or not title or not isinstance(eid, int):
            problems.append({"event": eid, "problem": "event without a date, name or id",
                             "snippet": json.dumps({k: e.get(k) for k in ("id", "eventName", "startDateTime")})})
            continue
        if start[:10] < cfg.from_date:
            continue
        files = e.get("publishedFiles") or []
        agenda, n_agenda = _pick(files, cfg.agenda_types)
        minutes, n_minutes = _pick(files, cfg.minutes_types)
        for what, n in (("agenda", n_agenda), ("minutes", n_minutes)):
            if n > 1:
                problems.append({"event": eid, "date": start[:10],
                                 "problem": f"{n} {what} files published; the newest is used"})
        raw_media = (e.get("mediaSourcePathMp4") or "").strip()
        video = video_url(e, cfg)
        if raw_media and not video:
            problems.append({"event": eid, "date": start[:10], "problem": "video path is not a public URL: not kept",
                             "snippet": raw_media[:120]})
        rows.append({
            # the API prints the local meeting time with a Z ("2024-01-04T18:00:00Z" is the 6 PM session), so the
            # date is the first ten characters as printed, never converted
            "date": start[:10], "title": title, "kind": kind_of(title), "source": SOURCE, "event_id": eid,
            "agenda_id": f"cc-{eid}",
            "agenda_url": cfg.file(agenda["fileId"]) if agenda else None,
            "minutes_url": cfg.file(minutes["fileId"]) if minutes else None,
            "agenda_name": agenda.get("name") if agenda else None,
            "minutes_name": minutes.get("name") if minutes else None,
            "video_url": video, "has_media": bool(e.get("hasMedia")), "has_previous_versions": False,
        })
    return rows, problems


def _cache(body: bytes, cache_dir: Path) -> str:
    digest = hashlib.sha256(body).hexdigest()
    cache_dir.mkdir(parents=True, exist_ok=True)
    p = cache_dir / f"{digest}.json"
    if not p.exists():
        tmp = p.with_suffix(".part")
        tmp.write_bytes(body)
        tmp.replace(p)
    return digest


def discover(fetcher, cfg: CivicClerkConfig, kind_of, log: dict, cache_dir: Path) -> list[dict]:
    """GET every listing page (politely), following @odata.nextLink on the API host only. Returns each event once,
    oldest first. Each page is cached as fetched; its URL and hash go to the run log. A refusal (403/429, robots,
    denied host) or a network error propagates: a partial listing is never written over a full one."""
    url, seen, out = cfg.first_url(), set(), []
    for n in range(MAX_PAGES):
        status, body, _ = fetcher.get(url)
        if status != 200:
            raise EventsError(f"{url} answered HTTP {status}: the API may have moved. Not guessing.")
        try:
            page = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as ex:
            raise EventsError(f"{url}: not JSON ({ex})") from None
        digest = _cache(body, cache_dir)
        rows, problems = parse_events(page, cfg, kind_of)
        log.setdefault("listings", []).append({"page": n, "url": url, "sha256": digest, "rows": len(rows)})
        log.setdefault("listing_problems", []).extend(problems)
        for r in rows:
            if r["event_id"] not in seen:
                seen.add(r["event_id"])
                out.append(r)
        nxt = page.get("@odata.nextLink")
        if not nxt:
            break
        if urllib.parse.urlsplit(nxt).netloc != cfg.api_host or urllib.parse.urlsplit(nxt).scheme != "https":
            raise EventsError(f"nextLink leaves the API host: {nxt[:200]}")
        url = nxt
    else:
        raise EventsError(f"more than {MAX_PAGES} listing pages: stopping")
    out.sort(key=lambda r: (r["date"], r["event_id"]))
    return out


# ------------------------------------------------------------------ both sources
def _rank(r: dict) -> tuple:
    """Which of two listings of one meeting is kept: the one with minutes, then the Agenda Center's (its meeting
    ids and citations were published first), then the one with an agenda."""
    return (bool(r.get("minutes_url")), r.get("source", AGENDA_CENTER) == AGENDA_CENTER, bool(r.get("agenda_url")))


def merge_sources(agenda_center: list[dict], civicclerk: list[dict]) -> tuple[list[dict], list[dict]]:
    """Join the two listings into one: a meeting listed by both (same date and same kind) is kept once.

    -> (rows, duplicates). Every row carries `source`. The kept row of a pair takes the other's video link when it
    has none, and lists the other row under `also_listed` (source and URLs), so nothing is lost. A source's own rows
    are never merged with each other (two meetings of one kind on one day are both real, e.g. two special sessions)."""
    ac = [{**r, "source": r.get("source") or AGENDA_CENTER} for r in agenda_center]
    by_key: dict[tuple, list[int]] = {}
    for i, r in enumerate(ac):
        by_key.setdefault((r["date"], r["kind"]), []).append(i)
    out, dups, taken = list(ac), [], set()
    for c in civicclerk:
        key = (c["date"], c["kind"])
        free = [i for i in by_key.get(key, []) if i not in taken]
        if not free:
            out.append(dict(c))
            continue
        i = free[0]
        taken.add(i)
        a = out[i]
        keep, drop = (a, c) if _rank(a) >= _rank(c) else (dict(c), a)
        keep = dict(keep)
        if not keep.get("video_url") and drop.get("video_url"):
            keep["video_url"] = drop["video_url"]
        keep["also_listed"] = [{"source": drop["source"], "title": drop["title"], "agenda_url": drop.get("agenda_url"),
                                "minutes_url": drop.get("minutes_url")}]
        out[i] = keep
        dups.append({"date": c["date"], "kind": c["kind"], "kept": keep["source"], "dropped": drop["source"],
                     "kept_title": keep["title"], "dropped_title": drop["title"]})
    out.sort(key=lambda r: (r["date"], r["source"] != AGENDA_CENTER, str(r["agenda_id"])))
    return out, dups
