"""Alerts v1 (M5): static Atom feeds, written beside the pages (docs/plan/one-week-finish.md, item 3).

No accounts, no e-mail, no server: each feed is a plain file a feed reader fetches. We keep no list of followers
and run no sign-up. Which feeds exist comes from config, never from a place name in code (config/site.yml `alerts:`):
- one "new agendas and minutes" feed per body (the county, then each council in config.COUNCILS);
- one feed per topic in `alerts.topics`, each an item type of `item_types` (the same mechanical rule as the Search
  filter and the About page), across every body.

Zoning (Daylight M3, docs/architecture/morning-note.md): RPC agenda cases whose prefix is in
`morning_note.zoning_prefixes` join the rezoning topic feed (id <feed_id>rpc/item/<case id>/<meeting id>; the ids
of every earlier entry are unchanged). On the `pages` target only, there is also one feed per county commission
district and per city ward (`zoning-district-NN.xml`, `zoning-ward-NN.xml`): the cases whose agenda PRINTS that
district or ward, never a guess from the location text. The `preview` target (file cap 500) has no per-seat feeds.
`topic-contracts.xml` lists each purchasing solicitation (data/finance.json), id contracts/solicitation/<id>.

Entries (invariant: an id never changes, so a reader never alerts twice for one thing):
- a body feed has one entry per document: a meeting's agenda, and its minutes, each its own entry;
  id <feed_id><body>/meeting/<meeting id>/<agenda|minutes>;
- a topic feed has one entry per item per meeting it appears at; id <feed_id><body>/item/<item id>/<meeting id>.
`updated` is the meeting's date, which never changes (so a reader never marks an entry as changed); entries are
newest meeting first, at most `alerts.max_entries` per feed, except `topic-rezoning.xml`, which keeps the newest
max_entries of each body (RPC agendas are dated ahead and come often; one cap would push every county and council
entry out). A reader shows an entry it has not seen as new whatever its
date, so minutes posted weeks after their meeting still alert, as long as the meeting is within the newest entries.
Titles are the document's own text, escaped by the XML writer, and never link to an official (DECISION 2026-11-09):
an entry links only its page on this site and its source document.
"""
from __future__ import annotations

import posixpath
import re
import xml.etree.ElementTree as ET

from . import config, views

DEFAULT_ZONING_PREFIXES = ("Z", "ZO", "CZ", "CZO", "HZ")
SEAT_TARGET = "pages"

ATOM = "http://www.w3.org/2005/Atom"
ET.register_namespace("", ATOM)
FOLDER = "feeds"
PAGE = "alerts.html"

# A tag: URI prefix (RFC 4151): "tag:<domain>,<date>:". It names every feed and entry id, so it never changes.
_TAG = re.compile(r"tag:[a-z0-9.-]+\.[a-z]{2,},\d{4}(?:-\d{2}(?:-\d{2})?)?:")


def settings(cfg: dict | None = None) -> dict:
    cfg = config.SITE if cfg is None else cfg
    a = cfg.get("alerts") or {}
    return {"feed_id": a.get("feed_id") or "", "site_url": a.get("site_url") or "",
            "max_entries": a.get("max_entries"), "topics": list(a.get("topics") or []),
            "contracts_title": a.get("contracts_title")}


def problems(cfg: dict) -> list[str]:
    """config/site.yml `alerts:` shape; the build refuses anything else."""
    if cfg.get("alerts") is None:
        return []
    a = settings(cfg)
    out = []
    if not _TAG.fullmatch(a["feed_id"]):
        out.append(f"alerts.feed_id must be a tag: URI prefix like 'tag:example.org,2026-11-09:', got {a['feed_id']!r}")
    if a["site_url"] and not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?/(?:[A-Za-z0-9._~-]+/)*",
                                          a["site_url"]):
        out.append(f"alerts.site_url must be an https base ending in '/', got {a['site_url']!r}")
    if not isinstance(a["max_entries"], int) or not 1 <= a["max_entries"] <= 200:
        out.append(f"alerts.max_entries must be a whole number from 1 to 200, got {a['max_entries']!r}")
    keys = [t["key"] for t in cfg.get("item_types") or []]
    out += [f"alerts.topics names {t!r}, which is not an item_types key" for t in a["topics"] if t not in keys]
    if not (isinstance(a["contracts_title"], str) and a["contracts_title"].strip()):
        out.append("alerts.contracts_title must be set (the contracts feed's title)")
    return out


def _stamp(date: str) -> str:
    return f"{date[:10]}T00:00:00Z"


def _bodies(county, councils) -> list[tuple[str, str, views.Index]]:
    """(body key, body name, Index): the county first, then each council in config order."""
    return [(config.SITE["county_key"], config.SITE["county_body"], county)] + \
        [(c.body_key, c.body_name, c) for c in councils]


def zoning_prefixes(cfg: dict | None = None) -> set[str]:
    cfg = config.SITE if cfg is None else cfg
    return set((cfg.get("morning_note") or {}).get("zoning_prefixes") or DEFAULT_ZONING_PREFIXES)


def feed_list(councils=(), cfg: dict | None = None, rpc=None, fin: dict | None = None,
              target: str | None = None) -> list[dict]:
    """Every feed, in the Alerts page's order: {file, title, kind, about}. `councils`: anything with body_key and
    body_name (council.CouncilIndex). `fin`: finance.json (adds the contracts feed). `rpc` and target "pages" add
    the per-seat zoning feeds (kind "zoning-seat", with seat "district"|"ward" and number)."""
    cfg = config.SITE if cfg is None else cfg
    a = settings(cfg)
    if not a["feed_id"]:
        return []
    bodies = [(cfg["county_key"], cfg["county_body"])] + [(c.body_key, c.body_name) for c in councils]
    names = " and ".join(n for _, n in bodies) if len(bodies) < 3 else \
        ", ".join(n for _, n in bodies[:-1]) + " and " + bodies[-1][1]
    out = [{"file": f"{FOLDER}/{key}-meetings.xml", "kind": "body", "key": key,
            "title": f"{name}: new agendas and minutes",
            "about": "Each agenda and each set of minutes when it is added to this site."}
           for key, name in bodies]
    labels = {t["key"]: t["label"] for t in cfg["item_types"]}
    for t in a["topics"]:
        out.append({"file": f"{FOLDER}/topic-{t}.xml", "kind": "topic", "key": t,
                    "title": f"{labels[t]} items: {names}",
                    "about": f"Each item the {labels[t]} type rule matches, at each meeting it appears at."})
    if fin is not None:
        out.append({"file": f"{FOLDER}/topic-contracts.xml", "kind": "topic", "key": "contracts",
                    "title": a["contracts_title"],
                    "about": "Each purchasing solicitation (bid or request for proposals) when it is added to this site."})
    if rpc is not None and target == SEAT_TARGET:
        for seat, label_key, count_key in (("district", "district_label", "district_count"),
                                           ("ward", "ward_label", "ward_count")):
            for n in range(1, int(cfg.get(count_key) or 0) + 1):
                out.append({"file": f"{FOLDER}/zoning-{seat}-{n:02d}.xml", "kind": "zoning-seat", "seat": seat,
                            "number": n, "key": f"zoning-{seat}-{n:02d}",
                            "title": f"Zoning cases, {cfg[label_key]} {n}",
                            "about": f"Each zoning case whose agenda prints {cfg[label_key]} {n}, at each "
                                     f"meeting it appears at. Cases that print no {seat} are in the Rezoning feed."})
    return out


def _body_entries(key: str, ix: views.Index) -> list[dict]:
    out = []
    for m in ix.facts["meetings"]:
        docs = {m["source_id"]}
        if m.get("agenda_source_id"):
            docs.add(m["agenda_source_id"])
        for sid in docs:
            s = ix.sources.get(sid)
            if s is None:
                continue
            word = "Agenda" if s["kind"] == "agenda" else "Minutes"
            out.append({
                "id": f"{key}/meeting/{m['id']}/{s['kind']}", "body": key,
                "title": f"{word}: {ix.meeting_label(m)}",
                "updated": m["date"],
                "href": ix.meeting_href(m["id"]),
                "source": s["url"],
                "summary": f"{m['body']}, {ix.meeting_label(m)}. {word} ({s['pages']} "
                           f"{views.plural(s['pages'], 'page', 'pages')}), fetched {s['fetched_at']}.",
                "sort": (m["date"], m["id"], s["kind"] == "minutes"),
            })
    return out


def _item_title(ix: views.Index, it: dict) -> str:
    title = ix.item_title(it)
    return f"{it['number']}: {title}" if it.get("number") and title != it["number"] else title


def _topic_entries(topic: str, key: str, ix: views.Index) -> list[dict]:
    out = []
    for it in ix.facts["items"]:
        if topic not in views.item_types(it):
            continue
        by_meeting: dict[str, list[dict]] = {}
        for e in ix.events_by_item[it["id"]]:
            by_meeting.setdefault(e["meeting_id"], []).append(e)
        for mid, evs in by_meeting.items():
            m = ix.meetings[mid]
            evs.sort(key=lambda e: (e["page"], e["order"], e["id"]))
            first = evs[0]
            src = ix.src(first["source_id"], first["page"])
            labels = list(dict.fromkeys(config.EVENT_TYPE_LABELS[e["type"]] for e in evs))
            out.append({
                "id": f"{key}/item/{it['id']}/{mid}", "body": key,
                "title": _item_title(ix, it),
                "updated": m["date"],
                "href": ix.item_href(it),
                "source": src["url"],
                "summary": f"{m['body']}, {ix.meeting_label(m)}. Recorded: {', '.join(labels)}. "
                           f"Source: {src['kind']}, page {src['page']}.",
                "sort": (m["date"], mid, -min(e["page"] for e in evs), it["id"]),
            })
    return out


def _rpc_cases(rpc, cfg: dict) -> list[tuple[dict, dict]]:
    """(case, meeting) for each RPC agenda case of a zoning prefix."""
    want = zoning_prefixes(cfg)
    meetings = {m["id"]: m for m in rpc.facts["meetings"]}
    return [(c, meetings[c["meeting_id"]]) for c in rpc.facts["cases"]
            if c["prefix"] in want and c["meeting_id"] in meetings]


def _rpc_entries(rpc, cases: list[tuple[dict, dict]]) -> list[dict]:
    out = []
    for c, m in cases:
        s = rpc.sources[c["source_id"]]
        kind = rpc.cfg["kind_labels"].get(m["kind"], m["kind"])
        title = c["number_printed"] + (f": {c['request']}" if c.get("request") else "")
        out.append({
            "id": f"{rpc.body_key}/item/{c['id']}/{m['id']}", "body": rpc.body_key,
            "title": title,
            "updated": m["date"],
            "href": f"{rpc.year_href(m['date'][:4])}#{rpc.case_anchor(c)}",
            "source": f"{s['url']}#page={c['page']}",
            "summary": f"{rpc.body}, {kind} agenda, {m['date']}. {c['case_type']}. Source: agenda, page {c['page']}.",
            "sort": (m["date"], m["id"], -c["page"], c["id"]),
        })
    return out


def _contract_entries(fin: dict) -> list[dict]:
    docs = {d["id"]: d for d in fin["documents"]}
    out = []
    for s in fin["solicitations"]:
        first = next((docs[i] for i in s["document_ids"] if i in docs), None)
        if first is None:
            continue
        when = s.get("archive_date") or first.get("fetched_at") or "1970-01-01"
        out.append({
            "id": f"contracts/solicitation/{s['id']}", "body": "contracts",
            "title": s["title"],
            "updated": when,
            "href": f"contracts/{s['slug']}.html",
            "source": first["url"],
            "summary": f"Purchasing solicitation{' ' + s['number'] if s.get('number') else ''}, "
                       f"{len(s['document_ids'])} {views.plural(len(s['document_ids']), 'document', 'documents')}.",
            "sort": (when, s["id"]),
        })
    return out


def _abs(href: str, feed_rel: str, site_url: str) -> str:
    """A site page's link as the feed carries it: absolute under alerts.site_url when set, else relative to the
    feed file (RFC 4287 resolves it against the feed's own address)."""
    if site_url:
        return site_url + href
    return posixpath.relpath(href.split("#")[0], posixpath.dirname(feed_rel)) + \
        (f"#{href.split('#', 1)[1]}" if "#" in href else "")


# Characters XML 1.0 forbids (everything outside its Char range): PDF text carries some (form feed, NUL).
_XML_ILLEGAL = re.compile("[^\u0009\u000a\u000d\u0020-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


def clean(text: str) -> str:
    """Text safe for an XML 1.0 element: illegal characters dropped, runs of whitespace collapsed to one space."""
    return " ".join(_XML_ILLEGAL.sub("", text).split())


def _sub(parent, tag: str, text: str | None = None, **attrs) -> ET.Element:
    el = ET.SubElement(parent, f"{{{ATOM}}}{tag}", attrs)
    if text is not None:
        el.text = clean(text)
    return el


def newest(entries: list[dict], cap: int, per_body: bool = False) -> list[dict]:
    """Entries newest meeting first (then the meeting, then document order): at most `cap`, or with `per_body` at
    most `cap` of each entry's `body`, so one body's many entries never push another body's out."""
    entries = sorted(entries, key=lambda e: e["sort"], reverse=True)
    if not per_body:
        return entries[:cap]
    kept: dict[str, int] = {}
    out = []
    for e in entries:
        if kept.get(e["body"], 0) < cap:
            kept[e["body"]] = kept.get(e["body"], 0) + 1
            out.append(e)
    return out


def render(feed: dict, entries: list[dict], cfg: dict | None = None, data_as_of: str = "",
           per_body: bool = False) -> bytes:
    """One Atom document. Entries newest meeting first (then the meeting, then document order), at most
    max_entries (of each body, with `per_body`). The feed's `updated` is its newest entry's date or the data date,
    whichever is later."""
    a = settings(cfg)
    entries = newest(entries, a["max_entries"], per_body)
    root = ET.Element(f"{{{ATOM}}}feed")
    _sub(root, "id", a["feed_id"] + feed["file"][:-len(".xml")])
    _sub(root, "title", f"{config.SITE_NAME}: {feed['title']}")
    _sub(root, "subtitle", feed["about"])
    updated = max([e["updated"] for e in entries] + ([data_as_of] if data_as_of else []), default="1970-01-01")
    _sub(root, "updated", _stamp(updated))
    author = _sub(root, "author")
    _sub(author, "name", config.SITE_NAME)
    _sub(root, "link", rel="self", type="application/atom+xml",
         href=(a["site_url"] + feed["file"]) if a["site_url"] else posixpath.basename(feed["file"]))
    _sub(root, "link", rel="alternate", type="text/html", href=_abs(PAGE, feed["file"], a["site_url"]))
    for e in entries:
        en = _sub(root, "entry")
        _sub(en, "id", a["feed_id"] + e["id"])
        _sub(en, "title", e["title"])
        _sub(en, "updated", _stamp(e["updated"]))
        _sub(en, "published", _stamp(e["updated"]))
        _sub(en, "link", rel="alternate", type="text/html", href=_abs(e["href"], feed["file"], a["site_url"]))
        _sub(en, "link", rel="related", type="application/pdf", href=e["source"], title="Source document")
        _sub(en, "summary", e["summary"])
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def build_feeds(county: views.Index, councils=(), cfg: dict | None = None, rpc=None, fin: dict | None = None,
                target: str | None = None) -> dict[str, bytes]:
    """{site-relative path: Atom bytes} for every feed in feed_list."""
    cfg = config.SITE if cfg is None else cfg
    bodies = _bodies(county, councils)
    zoning = _rpc_cases(rpc, cfg) if rpc is not None else []
    out = {}
    for feed in feed_list(councils, cfg, rpc, fin, target):
        as_of = max(b.data_as_of() for _, _, b in bodies)
        if feed["kind"] == "body":
            ix = next(b for k, _, b in bodies if k == feed["key"])
            entries = _body_entries(feed["key"], ix)
            as_of = ix.data_as_of()
        elif feed["kind"] == "zoning-seat":
            field = feed["seat"]
            entries = _rpc_entries(rpc, [(c, m) for c, m in zoning if c.get(field) == feed["number"]])
        elif feed["key"] == "contracts":
            entries = _contract_entries(fin)
            as_of = ""
        else:
            entries = [e for k, _, b in bodies for e in _topic_entries(feed["key"], k, b)]
            if feed["key"] == "rezoning" and rpc is not None:
                entries += _rpc_entries(rpc, zoning)
        out[feed["file"]] = render(feed, entries, cfg, "" if as_of == "unknown" else as_of,
                                   per_body=feed["kind"] == "topic" and feed["key"] == "rezoning")
    return out


def alerts_page(councils=(), cfg: dict | None = None, rpc=None, fin: dict | None = None,
                target: str | None = None, feeds: list[dict] | None = None) -> dict:
    """The Alerts page's feed lists. `feeds`: feed_list()'s result, when the caller has it already."""
    a = settings(cfg)
    feeds = feed_list(councils, cfg, rpc, fin, target) if feeds is None else feeds
    return {"body_feeds": [f for f in feeds if f["kind"] == "body"],
            "topic_feeds": [f for f in feeds if f["kind"] == "topic"],
            "site_url": a["site_url"], "max_entries": a["max_entries"]}
