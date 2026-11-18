"""The school board's and the county finance committees' agenda pages (collector/county_committees.py writes the data).

Inputs: the agendas file named by config/localities/<loc>/committee-agendas.yml (`facts`), and the words in
config/site.yml `county_committees:`. Nothing here names a place or a body: the bodies come from the agendas file.

Pages (one per body and year, each meeting a section #<meeting id>, so the preview build stays near its file budget):
- the school board's hub, <school_board.page.slug>.html (it replaces the "coming" page while the school board has
  agendas), and <slug>/meetings/<yyyy>.html;
- the county finance committees' index, <finance.slug>/index.html, and <finance.slug>/<body key>/<yyyy>.html.

Videos (Brian 2026-11-18): each school board meeting links the district's own recording on YouTube when one is
matched by exact date (collector/school_videos.py by_date: the channel's feed, kept in its data file, and the config's
`known` list), one Watch line per video, labelled by kind from config `county_committees.videos`; a meeting with none,
or a date with more than one school board meeting (which video is whose is not guessed), links the channel instead.
Links only: nothing is fetched from YouTube here, and no video title is shown.

Rules: every entry is the agenda's own words, linked to the agenda page it is printed on; a resolution or case number
links the County Commission's record of the same number only on an exact match (the minutes' item page, else the
agenda-only meeting that lists it); these bodies post no minutes online, so every meeting says so in a dashed COMING
note that links the official page, and no vote, motion or outcome is ever shown.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml

from . import config, localdates

SCHEMA = "county-committees-1"
TEXT_KEYS = ("finance", "minutes", "older", "agenda_note", "no_text")


class CommitteesError(Exception):
    pass


def _date_text(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def settings(site: dict | None = None) -> dict | None:
    """config/site.yml `county_committees:` with the agendas config it names, or None (no block)."""
    cc = (config.SITE if site is None else site).get("county_committees") or {}
    if not cc.get("agendas"):
        return None
    missing = [k for k in TEXT_KEYS if k not in cc]
    if missing:
        raise CommitteesError(f"config/site.yml county_committees: missing {', '.join(missing)}")
    path = config.REPO_ROOT / cc["agendas"]
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    slug = (cc.get("finance") or {}).get("slug")
    if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9-]+", slug):   # a folder the build writes into
        raise CommitteesError(f"county_committees.finance.slug {slug!r}: only lowercase letters, digits and '-'")
    # which bodies' item text may be shown comes from the collector config, never from the data file: a body not in
    # it, or with text: false (the school board), shows no title and no item text (agenda-withhold-invariant.md)
    text = {b["key"]: b.get("text", True) is True for b in raw.get("bodies") or []}
    return {**cc, "facts_path": config.REPO_ROOT / raw["facts"], "listing_url": raw["listing_url"],
            "record_label": raw["record_label"], "text_bodies": text, "videos_spec": cc.get("videos")}


VIDEO_TEXT = ("link", "channel_lede", "channel_label")


def video_settings(spec: dict | None, fixture: bool = False, data_path: Path | None = None) -> dict | None:
    """The school board's video links: {body, channel_url, by_date, problems, link, labels, channel_lede,
    channel_label}, or None without a `videos:` block. A fixture build (made-up meetings) never links a real video:
    it reads only `data_path` (a test's videos file, with no `known` list), or none and links the channel only."""
    if not spec:
        return None
    from collector import school_videos as sv
    bad = [k for k in VIDEO_TEXT if not isinstance(spec.get(k), str) or not spec[k].strip()]
    if bad or not spec.get("file"):
        raise CommitteesError(f"config/site.yml county_committees.videos: missing or empty {', '.join(bad) or 'file'}")
    labels = spec.get("labels")
    if not isinstance(labels, dict) or any(not isinstance(labels.get(w), str) or not labels[w].strip()
                                           for w in sv.WHATS):
        raise CommitteesError(f"county_committees.videos.labels: one label for each of {', '.join(sv.WHATS)}")
    try:
        vc = sv.load_config(config.REPO_ROOT / spec["file"])
        if fixture:
            vc = {**vc, "known": []}
            data = json.loads(Path(data_path).read_text(encoding="utf-8")) if data_path else {"videos": []}
        else:
            data = sv.load_data(vc, config.REPO_ROOT)
        links, problems = sv.by_date(vc, data)
    except (sv.ConfigError, sv.FeedError, OSError, ValueError) as e:
        raise CommitteesError(f"county_committees.videos: {e}") from e
    return {"body": vc["body"], "channel_url": vc["channel_url"], "by_date": links, "problems": problems,
            "link": spec["link"], "labels": labels, "channel_lede": spec["channel_lede"],
            "channel_label": spec["channel_label"]}


class Committees:
    def __init__(self, cfg: dict, data: dict, today: date, school_slug: str | None):
        self.cfg = cfg
        self.data = data
        self.today = today
        self.sources = {s["id"]: s for s in data["sources"]}
        self.bodies = {b["key"]: b for b in data["bodies"]}
        for k in self.bodies:
            if not re.fullmatch(r"[a-z0-9-]+", k):
                raise CommitteesError(f"{cfg['facts_path']}: body key {k!r}")
        self.by_body: dict[str, list[dict]] = defaultdict(list)
        for m in data["meetings"]:
            if m["body"] not in self.bodies:
                raise CommitteesError(f"{cfg['facts_path']}: meeting {m['id']} of an unknown body {m['body']!r}")
            if m.get("source_id") and m["source_id"] not in self.sources:
                raise CommitteesError(f"{cfg['facts_path']}: meeting {m['id']} cites a missing source")
            for e in m.get("entries", []):
                pages = self.sources[m["source_id"]]["pages"] if m.get("source_id") else 0
                if not 1 <= e["page"] <= (pages or 0):
                    raise CommitteesError(f"{cfg['facts_path']}: {m['id']}: entry page {e['page']} outside the PDF")
            self.by_body[m["body"]].append(m)
        for ms in self.by_body.values():
            ms.sort(key=lambda m: (m["date"], m["id"]))
        self.school_slug = school_slug
        self.school = [k for k, b in self.bodies.items() if b["group"] == "school" and self.by_body.get(k)]
        self.finance = [k for k, b in self.bodies.items() if b["group"] == "county-finance" and self.by_body.get(k)]
        self.links: dict[str, dict] = {}       # number -> {href, label}: the County Commission's record of it
        vs = cfg.get("videos")
        self.video_body = vs["body"] if vs and vs["body"] in self.bodies else None
        dates = [m["date"] for m in self.by_body.get(self.video_body or "", [])]
        self.video_shared = {d for d in dates if dates.count(d) > 1}   # a date with two board meetings: no video

    # ------------------------------------------------------------------ paths
    @property
    def finance_slug(self) -> str:
        return self.cfg["finance"]["slug"]

    def school_home(self) -> str | None:
        return f"{self.school_slug}.html" if self.school and self.school_slug else None

    def finance_home(self) -> str | None:
        return f"{self.finance_slug}/index.html" if self.finance else None

    def years(self, key: str) -> list[str]:
        return sorted({m["date"][:4] for m in self.by_body.get(key, [])}, reverse=True)

    def year_href(self, key: str, year: str) -> str:
        if self.bodies[key]["group"] == "school":
            return f"{self.school_slug}/meetings/{year}.html"
        return f"{self.finance_slug}/{key}/{year}.html"

    def meeting_href(self, m: dict) -> str:
        return f"{self.year_href(m['body'], m['date'][:4])}#{m['id']}"

    def pages(self) -> list[tuple[str, str]]:
        """(body key, year) of every year page this build writes (the school board's only with its hub)."""
        keys = (self.school if self.school_home() else []) + self.finance
        return [(k, y) for k in keys for y in self.years(k)]

    # ------------------------------------------------------------------ County Commission links
    def link_county(self, ix, ax=None) -> int:
        """number -> the County Commission's record of the same number, exact match only: the item page of the
        minutes (ix), else the newest agenda-only meeting that lists it (ax, sitegen/county_agendas.py)."""
        self.links = {}
        for m in self.data["meetings"]:
            for e in m.get("entries", []):
                n = e.get("number")
                if not n or n in self.links:
                    continue
                it = ix.items.get(n)
                if it is not None and it.get("number") == n:
                    self.links[n] = {"href": ix.item_href(it), "label": f"County Commission record of {n}"}
                    continue
                for am in (ax.meetings if ax is not None else []):         # newest first
                    if any(x["number"] == n for x in am["items"]):
                        self.links[n] = {"href": f"{ax.href(am['id'])}-{n}",
                                         "label": f"County Commission agenda, {_date_text(am['date'])}"}
                        break
        return len(self.links)

    # ------------------------------------------------------------------ contexts
    def minutes_note(self, key: str) -> dict:
        from .bodies import official_link
        g = self.bodies[key]["group"]
        link = official_link((self.cfg.get("minutes_links") or {}).get(g))
        if link is None:      # the county's own page, where the agendas are posted and no minutes are
            link = {"url": self.data["listing_url"], "label": self.data["record_label"], "kind": "committee"}
        tag = (config.SITE.get("switch") or {}).get("not_collected_tag") \
            if g in (self.cfg.get("minutes_not_collected") or []) else None
        return {"text": self.cfg["minutes"][g], "link": link, "tag": tag}

    def shows_text(self, key: str) -> bool:
        return (self.cfg.get("text_bodies") or {}).get(key, False)

    def videos(self, m: dict) -> tuple[list[dict], dict | None]:
        """([a Watch link per matched video], the channel link when none): ([], None) for a body without videos."""
        vs = self.cfg.get("videos")
        if not vs or m["body"] != self.video_body:
            return [], None
        found = [] if m["date"] in self.video_shared else vs["by_date"].get(m["date"], [])
        watch = [{"url": v["url"], "link": vs["link"], "label": vs["labels"][v["what"]], "ext": "watch"}
                 for v in found]
        channel = None if watch else {"url": vs["channel_url"], "lede": vs["channel_lede"],
                                      "label": vs["channel_label"], "kind": "watch"}
        return watch, channel

    def video_count(self) -> int:
        """The school board meetings that link at least one video of their own."""
        return sum(1 for m in self.by_body.get(self.video_body or "", []) if self.videos(m)[0])

    def meeting(self, m: dict) -> dict:
        b = self.bodies[m["body"]]
        watch, channel = self.videos(m)
        src = self.sources.get(m.get("source_id") or "")
        text = self.shows_text(m["body"])
        entries = []
        for e in m.get("entries", []) if text else []:
            entries.append({**e, "src": f"{src['url']}#page={e['page']}",
                            "county": self.links.get(e["number"]) if e.get("number") else None})
        upcoming = m["date"] > self.today.isoformat()
        return {"id": m["id"], "date": m["date"], "date_text": _date_text(m["date"]), "time": m.get("time"),
                "kind_label": b["kind_labels"].get(m["kind"], m["kind"]), "body": b["name"], "short": b["short"],
                "printed": m["printed"], "notes": m.get("notes") or [], "cancelled": m.get("cancelled", False),
                "title": m.get("title") if text else None, "url": m["url"], "upcoming": upcoming,
                "doc": ({"url": src["url"], "pages": src["pages"], "fetched": localdates.fetched(src),
                         "no_text": src.get("text_layer") == "none"} if src else None),
                "entries": entries, "minutes": self.minutes_note(m["body"]), "href": self.meeting_href(m),
                "text": text, "lines": m.get("lines", len(m.get("entries") or [])), "no_text_note": self.cfg["no_text"],
                "videos": watch, "channel": channel}

    def year_page(self, key: str, year: str) -> dict:
        b = self.bodies[key]
        ms = [m for m in self.by_body[key] if m["date"][:4] == year]
        home = self.school_home() if b["group"] == "school" else self.finance_home()
        return {"key": key, "year": year, "years": self.years(key), "body": b["name"], "short": b["short"],
                "group": b["group"], "home": home,
                "home_label": self.cfg["school_label"] if b["group"] == "school" else self.cfg["finance"]["title"],
                "meetings": [self.meeting(m) for m in ms], "agenda_note": self.cfg["agenda_note"],
                "record": {"url": self.data["listing_url"], "label": self.data["record_label"]}}

    def _body_summary(self, key: str) -> dict:
        ms = self.by_body[key]
        b = self.bodies[key]
        years = self.years(key)
        return {"key": key, "name": b["name"], "short": b["short"], "n": len(ms),
                "n_read": sum(1 for m in ms if m.get("source_id")),
                "from": ms[0]["date"], "to": ms[-1]["date"],
                "years": [{"year": y, "href": self.year_href(key, y),
                           "meetings": [self.meeting(m) for m in reversed(ms) if m["date"][:4] == y]} for y in years]}

    def older(self) -> dict:
        first = min((m["date"][:4] for m in self.data["meetings"]), default=None)
        return {"text": self.cfg["older"]["text"].format(year=first) if first else None,
                "link": {"url": self.data["listing_url"], "label": self.data["record_label"], "kind": "committee"}}

    def coverage(self, keys) -> dict | None:
        ds = sorted(m["date"] for k in keys for m in self.by_body.get(k, []))
        return {"from": ds[0], "to": ds[-1]} if ds else None

    def school_hub(self) -> dict:
        return {"bodies": [self._body_summary(k) for k in self.school], "older": self.older(),
                "coverage": self.coverage(self.school), "agenda_note": self.cfg["agenda_note"],
                "minutes": self.minutes_note(self.school[0]), "record": {"url": self.data["listing_url"],
                                                                         "label": self.data["record_label"]},
                "fetched_to": (localdates.span([s for s in self.data["sources"]
                                                if any(m.get("source_id") == s["id"] for k in self.school
                                                       for m in self.by_body[k])]) or (None, None))[1]}

    def finance_index(self) -> dict:
        f = self.cfg["finance"]
        return {"title": f["title"], "lede": f["lede"], "bodies": [self._body_summary(k) for k in self.finance],
                "older": self.older(), "coverage": self.coverage(self.finance), "agenda_note": self.cfg["agenda_note"],
                "minutes": self.minutes_note(self.finance[0]),
                "record": {"url": self.data["listing_url"], "label": self.data["record_label"]}}

    # ------------------------------------------------------------------ search
    def search_records(self, school_key: str, county_key: str) -> list[dict]:
        out = []
        for key in self.school + self.finance:
            b = self.bodies[key]
            bk = school_key if b["group"] == "school" else county_key
            for m in self.by_body[key]:
                if b["group"] == "school" and not self.school_home():
                    continue
                kind = b["kind_labels"].get(m["kind"], m["kind"])
                out.append({"k": "meeting", "id": f"{key}-{m['id']}", "n": "",
                            "t": f"{b['short']}: {kind}" if kind != b["short"] else kind,
                            "d": m["date"], "y": [int(m["date"][:4])], "ty": [], "b": bk,
                            "h": self.meeting_href(m),
                            "z": " · ".join(e["text"][:120] for e in m.get("entries", [])
                                            if e.get("number") and self.shows_text(key))[:600]})
        return out


def load(site: dict | None, fixture: bool, today: date, facts_path: Path | None = None) -> Committees | None:
    """The pages' data, or None (no config block, no agendas file, or a fixture build: these are real records and are
    never shown beside made-up ones, unless a test names a fixture agendas file)."""
    cfg = settings(site)
    if cfg is None:
        return None
    p = Path(facts_path) if facts_path else cfg["facts_path"]
    if not p.is_file():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise CommitteesError(f"{p}: not a committee agendas file (schema {data.get('schema')!r})")
    if bool(data.get("fixture")) != bool(fixture):
        return None
    cfg = {**cfg, "facts_path": p,
           "videos": video_settings(cfg.get("videos_spec"), bool(fixture), data.get("fixture_videos") if fixture else None)}
    sb =((site or config.SITE).get("school_board") or {})
    pg = sb.get("page") or {}
    cfg["school_label"] = pg.get("title") or sb.get("label") or "School board"
    return Committees(cfg, data, today, pg.get("slug"))
