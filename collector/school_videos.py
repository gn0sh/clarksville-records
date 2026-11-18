"""The school board's official meeting videos: links only (Brian 2026-11-18), from the district's YouTube channel.

python -m collector school-videos fetch      read the channel's RSS feed once and update the data file
python -m collector school-videos show       the meeting dates each video would link (offline, no request)

Rules (config/localities/montgomery-tn/school-board-videos.yml):
- the one URL requested is the config's feed_url, the channel's public RSS feed (YouTube's machine-readable listing),
  through collector.fetch.PoliteFetcher with an allowlist of www.youtube.com alone: robots.txt read first and obeyed
  (a Disallow for the feed stops the step with no request to it), 10 s between requests, our honest User-Agent, GET
  only, at most FEED_FETCH_CAP requests a run, no redirect off www.youtube.com. No video page, /youtubei/, internal API,
  video, caption or transcript is ever requested; nothing is fetched from cmcss.net;
- only entries of the configured channel whose title fits title_pattern whole are kept: {id, title, date, what,
  published}, the title and dates as printed. No other title is stored (a title can name a person). The feed lists the
  latest ~15 videos, so every kept entry stays in the data file after it leaves the feed;
- a video links a meeting only when the date in its title equals the meeting date (sitegen/county_committees.py);
  no fuzzy matching. The config's `known` list (date, id, kind) covers older videos; where the feed disagrees with
  it, the feed wins and the disagreement is reported.

Step outcome (`collector run`, after the committee agendas; never changes the run's exit code): log['school_videos']
{status, exit}: 0 ok, 2 not read (robots.txt, a refusal, a block, a network error or a non-200), 3 the feed is not
the feed we know (not parsed, wrong channel), 1 an unexpected error. On anything but 0 the data file is untouched.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import xml.parsers.expat
from datetime import date, datetime
from pathlib import Path

import yaml

from .fetch import (FetchFailed, HostBlocked, HostRefused, PoliteFetcher, ProxyRefused, RequestCapReached,
                    RobotsDisallowed)
from .rpc import write_json

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "localities" / "montgomery-tn" / "school-board-videos.yml"
SCHEMA = "school-board-videos-1"
FEED_HOST = "www.youtube.com"
FEED_PATH = "/feeds/videos.xml"
FEED_FETCH_CAP = 4                  # robots.txt, the feed, and room for one same-host redirect
MAX_FEED_BYTES = 2_000_000          # the feed is ~15 entries, tens of kB
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")
WATCH = "https://www.youtube.com/watch?v={}"
WHATS = ("meeting", "hearing", "budget-hearing")
KEYS = ("locality", "body", "channel_name", "channel_id", "channel_url", "feed_url", "facts", "title_pattern", "what",
        "known")
# a feed entry's <published> as YouTube prints it (2024-11-27T02:10:00+00:00); anything else is stored as ""
PUBLISHED = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})")
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


class ConfigError(Exception):
    pass


class FeedError(Exception):
    """The body is not the channel's feed as we know it. Nothing is written."""


def load_config(path: Path = CONFIG) -> dict:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    missing = [k for k in KEYS if k not in raw]
    if missing:
        raise ConfigError(f"{path}: missing {', '.join(missing)}")
    cid = str(raw["channel_id"])
    if not CHANNEL_ID.fullmatch(cid):
        raise ConfigError(f"{path}: channel_id {cid!r} is not a channel id")
    feed = urllib.parse.urlsplit(str(raw["feed_url"]))
    if (feed.scheme, feed.netloc, feed.path, feed.query, feed.fragment) != (
            "https", FEED_HOST, FEED_PATH, f"channel_id={cid}", ""):
        raise ConfigError(f"{path}: feed_url must be https://{FEED_HOST}{FEED_PATH}?channel_id=<channel_id>")
    ch = urllib.parse.urlsplit(str(raw["channel_url"]))
    if ch.scheme != "https" or ch.netloc != FEED_HOST or ch.query or ch.fragment:
        raise ConfigError(f"{path}: channel_url must be an https://{FEED_HOST}/ page")
    try:
        rx = re.compile(str(raw["title_pattern"]), re.I)
    except re.error as e:
        raise ConfigError(f"{path}: title_pattern: {e}") from e
    if not {"what", "m", "d", "y"} <= set(rx.groupindex):
        raise ConfigError(f"{path}: title_pattern needs the groups what, m, d and y")
    what = {_words(k): str(v) for k, v in (raw["what"] or {}).items()}
    if not what or any(v not in WHATS for v in what.values()):
        raise ConfigError(f"{path}: what: each value must be one of {', '.join(WHATS)}")
    known = []
    for k in raw["known"] or []:
        d, vid, w = str(k.get("date")), str(k.get("id")), str(k.get("what"))
        if not _iso(d) or not VIDEO_ID.fullmatch(vid) or w not in WHATS:
            raise ConfigError(f"{path}: known entry {k!r}: needs date YYYY-MM-DD, an 11-character id, what in "
                              f"{', '.join(WHATS)}")
        known.append({"date": d, "id": vid, "what": w})
    ids = [k["id"] for k in known]
    if len(ids) != len(set(ids)):
        raise ConfigError(f"{path}: known: an id is listed twice")
    return {**{k: raw[k] for k in KEYS}, "channel_id": cid, "title_rx": rx, "what": what, "known": known}


def _words(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _iso(s: str) -> str | None:
    try:
        return date.fromisoformat(s).isoformat() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else None
    except ValueError:
        return None


def read_title(cfg: dict, title: str) -> tuple[str, str] | None:
    """(ISO date, what) when the title, as printed, fits title_pattern whole and names a real date; else None."""
    m = cfg["title_rx"].fullmatch((title or "").strip())
    if not m:
        return None
    what = cfg["what"].get(_words(m.group("what")))
    try:
        d = date(int(m.group("y")), int(m.group("m")), int(m.group("d"))).isoformat()
    except ValueError:
        return None
    return (d, what) if what else None


def no_dtd(body: bytes) -> None:
    """FeedError when the body declares a DOCTYPE or an entity anywhere, in any encoding expat reads (a UTF-16 body,
    a long leading comment): a first pass with expat's own handlers, before ElementTree parses it, so no DTD or entity
    is ever expanded."""
    def refuse(*_):
        raise FeedError("the feed declares a DTD or an entity")
    p = xml.parsers.expat.ParserCreate()
    p.StartDoctypeDeclHandler = refuse
    p.EntityDeclHandler = refuse
    try:
        p.Parse(body, True)
    except xml.parsers.expat.ExpatError as e:
        raise FeedError(f"not XML: {e}") from None


def published(text: str | None) -> str:
    """The entry's published time as printed when it is an ISO-8601 datetime, else "" (free feed text is never kept)."""
    t = (text or "").strip()
    if not PUBLISHED.fullmatch(t):
        return ""
    try:
        datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return t


def parse_feed(body: bytes, cfg: dict) -> list[dict]:
    """The feed's board-meeting entries: [{id, title, date, what, published}], in feed order. Entries of another
    channel, with a malformed id or with a title that does not fit the pattern are left out (their titles are never
    kept). FeedError when the body is not this channel's Atom feed."""
    no_dtd(body)
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise FeedError(f"not XML: {e}") from None
    if root.tag != f"{{{NS['a']}}}feed":
        raise FeedError(f"not an Atom feed (root {root.tag!r})")
    if (root.findtext("yt:channelId", default="", namespaces=NS) or "").strip() != cfg["channel_id"]:
        raise FeedError("the feed is not the configured channel's")
    out = []
    for e in root.findall("a:entry", NS):
        vid = (e.findtext("yt:videoId", default="", namespaces=NS) or "").strip()
        ch = (e.findtext("yt:channelId", default="", namespaces=NS) or "").strip()
        title = re.sub(r"\s+", " ", e.findtext("a:title", default="", namespaces=NS) or "").strip()
        if not VIDEO_ID.fullmatch(vid) or ch != cfg["channel_id"]:
            continue
        got = read_title(cfg, title)
        if got is None:
            continue
        out.append({"id": vid, "title": title, "date": got[0], "what": got[1],
                    "published": published(e.findtext("a:published", default="", namespaces=NS))})
    return out


def merge(old: list[dict], new: list[dict]) -> list[dict]:
    """The feed's entries plus every stored one the feed no longer lists, by id (the feed's reading wins), sorted
    by (date, id) so the file does not depend on the feed's order."""
    by_id = {v["id"]: v for v in old}
    by_id.update({v["id"]: v for v in new})
    return sorted(by_id.values(), key=lambda v: (v["date"], v["id"]))


def load_data(cfg: dict, root: Path = ROOT) -> dict:
    p = root / cfg["facts"]
    if not p.is_file():
        return {"schema": SCHEMA, "channel_id": cfg["channel_id"], "videos": []}
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise FeedError(f"{p}: not a school board videos file (schema {data.get('schema')!r})")
    return data


def by_date(cfg: dict, data: dict) -> tuple[dict[str, list[dict]], list[str]]:
    """{ISO date: [{id, url, what, source}]} from the feed's stored entries (titles re-read against the pattern, so a
    hand-edited file cannot link a title that does not fit) and the config's `known` list, and the problems: a known
    entry the feed disagrees with (the same id on another date or kind, or another id for the same date and kind)
    is left out, and reported. Two feed entries of one date and kind: the one published last is kept, the other
    reported."""
    problems, feed = [], []
    for v in data.get("videos") or []:
        got = read_title(cfg, v.get("title", ""))
        if not VIDEO_ID.fullmatch(str(v.get("id", ""))) or got is None or got != (v.get("date"), v.get("what")):
            problems.append(f"videos file: entry {v.get('id')!r} does not fit the title pattern or its date; not linked")
            continue
        feed.append({"id": v["id"], "date": got[0], "what": got[1], "source": "feed",
                     "published": published(v.get("published"))})
    groups: dict[tuple, list[dict]] = {}
    for v in feed:
        groups.setdefault((v["date"], v["what"]), []).append(v)
    feed = []
    for vs in groups.values():                          # the one published last wins its (date, kind)
        vs.sort(key=_published_key)
        win = vs[-1]
        problems += [f"videos file: {v['id']} and {win['id']} are both {win['what']} videos of {win['date']}; "
                     f"{win['id']}, published last, is linked" for v in vs[:-1]]
        feed.append({k: x for k, x in win.items() if k != "published"})
    fid = {v["id"]: v for v in feed}
    fkey = {(v["date"], v["what"]): v["id"] for v in feed}
    out = list(feed)
    for k in cfg["known"]:
        f = fid.get(k["id"])
        if f is not None:
            if (f["date"], f["what"]) != (k["date"], k["what"]):
                problems.append(f"known {k['id']} ({k['date']}, {k['what']}): the feed has it as {f['date']}, "
                                f"{f['what']}; the feed wins")
            continue
        other = fkey.get((k["date"], k["what"]))
        if other is not None:
            problems.append(f"known {k['id']} ({k['date']}, {k['what']}): the feed lists {other} for that date; "
                            "the feed wins")
            continue
        out.append({**k, "source": "known"})
    res: dict[str, list[dict]] = {}
    for v in sorted(out, key=lambda v: (v["date"], WHATS.index(v["what"]), v["id"])):
        res.setdefault(v["date"], []).append({**v, "url": WATCH.format(v["id"])})
    return res, problems


def _published_key(v: dict) -> tuple:
    """Order by published time (none first), then id, so the choice does not depend on the file's order."""
    t = v.get("published") or ""
    when = datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp() if t else float("-inf")
    return (when, v["id"])


# ------------------------------------------------------------------ the daily step
def feed_fetcher() -> PoliteFetcher:
    """The step's own fetcher: www.youtube.com only, so no other step's fetcher can ever reach YouTube."""
    f = PoliteFetcher(allowed_hosts=(FEED_HOST,), max_bytes=MAX_FEED_BYTES)
    f.limit_hosts({FEED_HOST}, FEED_FETCH_CAP)
    return f


def run_step(log: dict, offline: bool, fetcher=None, cfg: dict | None = None, root: Path = ROOT) -> int:
    """Read the feed once (unless offline) and write the data file when its entries changed. Never raises; the
    outcome goes to log['school_videos']. Returns 0 ok, 2 not read, 3 not the feed we know, 1 an unexpected error."""
    out: dict = {"offline": offline}
    code = 0
    try:
        cfg = cfg or load_config()
        if offline:
            out["status"] = "offline: the feed was not read; the data file is as committed"
        else:
            f = fetcher or feed_fetcher()
            try:
                status, body, _ = f.get(cfg["feed_url"])
            except RobotsDisallowed:
                status, body = None, b""
                rp = (getattr(f, "_robots", None) or {}).get(FEED_HOST)
                if rp is not None and getattr(rp, "disallow_all", False):   # a 5xx or a refused redirect: unread
                    out["status"] = ("robots.txt unreadable (treated as disallowing everything); the feed was not "
                                     "requested, the data file is as committed")
                else:
                    out["status"] = "robots.txt disallows the feed; not requested, the data file is as committed"
                code = 2
            except (HostBlocked, HostRefused, ProxyRefused, FetchFailed, RequestCapReached) as e:
                status, body = None, b""
                out["status"] = f"feed not read: {type(e).__name__}: {e}"[:400]
                code = 2
            out["fetch_log"] = list(getattr(f, "log", []))
            if status is not None and status != 200:
                out["status"] = f"feed not read: HTTP {status}"
                code = 2
            elif status == 200:
                new = parse_feed(body, cfg)
                data = load_data(cfg, root)
                videos = merge(data.get("videos") or [], new)
                changed = write_json(root / cfg["facts"], {"schema": SCHEMA, "channel_id": cfg["channel_id"],
                                                          "videos": videos})
                out["status"] = (f"{len(new)} board videos in the feed, {len(videos)} kept; "
                                 f"{Path(cfg['facts']).name} {'rewritten' if changed else 'unchanged'}")
    except (FeedError, ConfigError) as e:
        out["status"] = f"not the feed we know, nothing changed: {e}"[:400]
        code = 3
    except Exception as e:      # this step never takes the run down
        out["status"] = f"error, nothing changed: {type(e).__name__}: {e}"[:400]
        code = 1
    out["exit"] = code
    log["school_videos"] = {k: v for k, v in out.items() if k != "fetch_log"}
    print(f"collector: school board videos: exit {code}: {out['status']}", flush=True)
    return code


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m collector school-videos")
    ap.add_argument("command", choices=("fetch", "show"))
    a = ap.parse_args(argv)
    if a.command == "fetch":
        log: dict = {}
        return run_step(log, offline=False)
    cfg = load_config()
    links, problems = by_date(cfg, load_data(cfg))
    print(json.dumps({"dates": {d: [v["id"] for v in vs] for d, vs in links.items()}, "problems": problems}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
