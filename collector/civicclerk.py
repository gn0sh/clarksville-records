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
    # D1: other listings that may hold this body's meetings ({category_name, event_name, page1}, ...), each asked with
    # also_events_url; an event from one is kept only when page 1 of its agenda or minutes prints `page1`
    also_list: tuple = ()
    also_events_url: str = ""

    def first_url(self) -> str:
        return self.events_url.format(host=self.api_host, from_date=self.from_date,
                                      category=urllib.parse.quote(self.category_name.replace("'", "''")))

    def also_url(self, also: dict) -> str:
        q = lambda s: urllib.parse.quote(s.replace("'", "''"))        # noqa: E731 (an OData string literal)
        return self.also_events_url.format(host=self.api_host, from_date=self.from_date,
                                           category=q(also["category_name"]), event=q(also["event_name"]))

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
        minutes_types=_strs(cfg, "minutes_types"), video_hosts=_strs(cfg, "video_hosts"),
        also_list=_also(cfg.get("also_list") or []), also_events_url=str(cfg.get("also_events_url") or ""))
    if out.also_list and not out.also_events_url:
        raise CivicClerkConfigError("civicclerk.yml: also_list needs also_events_url")
    urls = [("events_url", out.first_url()), ("file_url", out.file(1))]
    urls += [("also_events_url", out.also_url(a)) for a in out.also_list]
    for key, url in urls:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or parts.netloc != host:
            raise CivicClerkConfigError(f"civicclerk.yml: {key} must be https on api_host")
    if len(out.from_date) != 10 or out.from_date[4] != "-" or out.from_date[7] != "-":
        raise CivicClerkConfigError("civicclerk.yml: from_date must be YYYY-MM-DD")
    return out


def _also(raw) -> tuple:
    """also_list: [{category_name, event_name, page1}], each a non-empty string (D1)."""
    if not isinstance(raw, list):
        raise CivicClerkConfigError("civicclerk.yml: also_list must be a list")
    out = []
    for i, a in enumerate(raw):
        if not (isinstance(a, dict) and set(a) == {"category_name", "event_name", "page1"}
                and all(isinstance(v, str) and v.strip() for v in a.values())):
            raise CivicClerkConfigError(f"civicclerk.yml: also_list[{i}] must be {{category_name, event_name, page1}}")
        out.append({k: v.strip() for k, v in a.items()})
    return tuple(out)


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


def parse_events(page: dict, cfg: CivicClerkConfig, kind_of, also: dict | None = None) -> tuple[list[dict], list[dict]]:
    """One OData page -> (rows, problems). kind_of(title) is the Agenda Center config's kind rule, so both sources
    name kinds alike. Events of another category are left out (the filter should already have done it).

    `also` (D1, one also_list entry): read the page of that listing instead: only events of exactly that category and
    event name, each row marked `listed_as` and `page1_required`, so the build keeps it only when page 1 of its stored
    agenda or minutes prints that text (city_build.page1_check); every other is skipped there and named."""
    if not isinstance(page, dict) or not isinstance(page.get("value"), list):
        raise EventsError("events page has no 'value' list: the API changed. Not guessing.")
    rows, problems = [], []
    for e in page["value"]:
        if not isinstance(e, dict) or e.get("isDeleted"):
            continue
        if also is None and e.get("categoryName") != cfg.category_name:
            continue
        if also is not None and (e.get("categoryName") != also["category_name"]
                                 or (e.get("eventName") or "").strip() != also["event_name"]):
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
        if also is not None:
            rows[-1]["listed_as"] = f"{also['category_name']} / {also['event_name']}"
            rows[-1]["page1_required"] = also["page1"]
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
    denied host) or a network error propagates: a partial listing is never written over a full one. Then each
    also_list listing (D1) the same way; its rows carry page1_required."""
    seen, out = set(), []
    _listing(fetcher, cfg, kind_of, log, cache_dir, cfg.first_url(), None, seen, out)
    for also in cfg.also_list:
        _listing(fetcher, cfg, kind_of, log, cache_dir, cfg.also_url(also), also, seen, out)
    out.sort(key=lambda r: (r["date"], r["event_id"]))
    return out


def _listing(fetcher, cfg: CivicClerkConfig, kind_of, log: dict, cache_dir: Path, url: str, also: dict | None,
             seen: set, out: list) -> None:
    for n in range(MAX_PAGES):
        status, body, _ = fetcher.get(url)
        if status != 200:
            raise EventsError(f"{url} answered HTTP {status}: the API may have moved. Not guessing.")
        try:
            page = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as ex:
            raise EventsError(f"{url}: not JSON ({ex})") from None
        digest = _cache(body, cache_dir)
        rows, problems = parse_events(page, cfg, kind_of, also)
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


# ------------------------------------------------------------------ both sources
def _rank(r: dict) -> tuple:
    """Which of two listings of one meeting is kept: the one with minutes, then the Agenda Center's (its meeting
    ids and citations were published first), then the one with an agenda."""
    return (bool(r.get("minutes_url")), r.get("source", AGENDA_CENTER) == AGENDA_CENTER, bool(r.get("agenda_url")))


def merge_sources(agenda_center: list[dict], civicclerk: list[dict],
                  page1_ok=None) -> tuple[list[dict], list[dict]]:
    """Join the two listings into one: a meeting listed by both (same date and same kind) is kept once.

    -> (rows, duplicates). Every row carries `source`. The kept row of a pair takes the other's video link when it
    has none, and lists the other row under `also_listed` (source and URLs), so nothing is lost. A source's own rows
    are never merged with each other (two meetings of one kind on one day are both real, e.g. two special sessions).

    A D1 row (`page1_required`, from an also_list listing) is paired only when `page1_ok(row)` says page 1 of its
    stored file prints the body's name (city_build.page1_check, run before pairing: city-verify/d1-merge-before-page1).
    Without page1_ok, or when it fails, the row is never paired: it stays a row of its own, and the build's own
    page1_check keeps or skips it alone, so another body's meeting never replaces or joins a council meeting."""
    ac = [{**r, "source": r.get("source") or AGENDA_CENTER} for r in agenda_center]
    by_key: dict[tuple, list[int]] = {}
    for i, r in enumerate(ac):
        by_key.setdefault((r["date"], r["kind"]), []).append(i)
    out, dups, taken = list(ac), [], set()
    for c in civicclerk:
        key = (c["date"], c["kind"])
        checked = not c.get("page1_required") or (page1_ok is not None and page1_ok(c))
        free = [i for i in by_key.get(key, []) if i not in taken] if checked else []
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
