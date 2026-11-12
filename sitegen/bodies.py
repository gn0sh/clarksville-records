"""The "Show records from" switch and each body's hub cards (config/site.yml `switch:`; owner's mock 2026-11-12).

Four public bodies share this site: the county, the city, the school board and the planning commission. The switch is
on every page, right under the header: All, then one option per body whose hub page this build makes. Each option is a
plain link to that body's hub (All is the home page), so it works without script; static/switch.js remembers the
choice on the device and hides the rows of other bodies on the pages whose rows carry data-body.

A hub shows section cards. A card is "present" only when this build makes the page it links; a "coming" card is
dashed, says what is not collected yet, and links the body's own official page. Every such URL is read from the config
(a dotted path into config/site.yml, or the RPC's record page): none is written here, and a card whose link cannot be
resolved to an https URL is left without a link, never with a guessed one.
"""
from __future__ import annotations

from . import config
from .views import https_url

ALL = "all"
ORDER = ("county", "city", "school", "rpc")


def _cfg() -> dict:
    return config.SITE.get("switch") or {}


def _path(ref: str):
    """config/site.yml value at a dotted path ("committees.links.1"), or None."""
    cur = config.SITE
    for part in ref.split("."):
        if isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def official_link(spec: dict | None, rpc=None) -> dict | None:
    """{url, label, kind} for a card's or note's official link, or None. `spec`: {from, label?, kind}; `from` is a
    dotted config path to a mapping with `url` (and `label` or `link_label`), or "rpc" for the RPC's record page."""
    if not spec:
        return None
    if spec.get("from") == "rpc":
        src = {"url": rpc.cfg["record_url"], "label": rpc.cfg["record_label"]} if rpc is not None else None
    else:
        src = _path(spec.get("from") or "")
    if not isinstance(src, dict) or not https_url(src.get("url")):
        return None
    label = spec.get("label") or src.get("link_label") or src.get("label")
    return {"url": src["url"], "label": label, "kind": spec["kind"]} if label else None


def _hrefs(site: dict, councils, rpc) -> dict[str, dict[str, str]]:
    """{body: {card key: href}} of the section pages this build makes."""
    nav = {e["label"]: e for e in site["nav"]}

    def built(label):
        e = nav.get(label)
        return e["href"] if e and e.get("href") and not e["coming"] else None

    out: dict[str, dict[str, str | None]] = {
        "county": {"meetings": built("Meetings"), "votes": built("Votes") if site.get("vote_years_desc") else None,
                   "finance": built("Finance"), "bids": built("Bids and awards"),
                   "capital": built("Capital projects")}}
    if councils:
        c = councils[0]
        years = c.meeting_years()
        tx = getattr(c, "tx", None)
        out["city"] = {"meetings": c.home_href() + "#meetings-h", "votes": c.home_href() + "#members-h",
                       "transcripts": f"{c.slug}/meetings/{years[-1]}.html"
                       if years and tx is not None and tx.pages and tx.by_meeting else None}
    if rpc is not None:
        years = rpc.years()
        out["rpc"] = {"meetings": f"{rpc.home_href()}#y{years[0]}-h" if years else None,
                      "cases": rpc.year_href(years[0]) if years else None}
    return {k: {a: b for a, b in v.items() if b} for k, v in out.items()}


def build(site: dict, councils=(), rpc=None) -> dict | None:
    """site["switch"]: {label, line, options, hubs, current}. None when config/site.yml has no `switch:` block.
    options: [{key, label, short, href, coming}], All first. hubs: {key: {kicker, title, lede, note, cards}}.
    current: {page path: option key} for the pages that are an option's own destination."""
    cfg = _cfg()
    bodies = cfg.get("bodies") or {}
    if not cfg.get("label") or not bodies:
        return None
    school = next((e for e in site["nav"] if e.get("school")), None)
    home = {"county": f"{bodies['county']['slug']}.html" if "county" in bodies else None,
            "city": councils[0].home_href() if councils else None,
            "school": school["href"] if school else None,
            "rpc": rpc.home_href() if rpc is not None else None}
    hrefs = _hrefs(site, councils, rpc)
    votes_shown = rpc is not None and rpc.votes_shown
    options = [{"key": ALL, "label": cfg["all"]["label"], "short": None, "href": "index.html", "coming": False}]
    hubs = {}
    for key in ORDER:
        b = bodies.get(key)
        if not b or not home[key]:
            continue
        cards = []
        for c in b.get("cards") or []:
            if c.get("coming"):
                if key == "rpc" and c["key"] == "votes" and votes_shown:
                    continue      # the hold is lifted: the card no longer applies
                cards.append({"key": c["key"], "title": c["title"], "text": c["text"], "coming": True, "href": None,
                              "link": official_link(c.get("link"), rpc)})
            elif hrefs.get(key, {}).get(c["key"]):
                cards.append({"key": c["key"], "title": c["title"], "text": c["text"], "coming": False,
                              "href": hrefs[key][c["key"]], "go": c.get("go") or c["title"], "link": None})
        hubs[key] = {"key": key, "label": b["label"], "href": home[key], "kicker": b.get("kicker"),
                     "title": b.get("title"), "lede": b.get("lede"), "note": b.get("note"), "cards": cards,
                     "about": b.get("about"),
                     "present": [c["title"] for c in cards if not c["coming"]],
                     "coming": [c["title"] for c in cards if c["coming"]]}
        options.append({"key": key, "label": b["label"], "short": b.get("short"), "href": home[key],
                        "coming": bool(cards) and all(c["coming"] for c in cards)})
    return {"label": cfg["label"], "options": options, "hubs": hubs,
            "overview": cfg.get("overview") or {},
            "current": {o["href"]: o["key"] for o in options}}


def finance_note(rpc=None) -> dict | None:
    """The Finance page's top line (config `switch.finance_note`): the text and its official links."""
    fn = _cfg().get("finance_note") or {}
    if not fn.get("text"):
        return None
    links = [x for x in (official_link(s, rpc) for s in fn.get("links") or []) if x]
    return {"text": fn["text"], "link_lede": fn.get("link_lede") or "", "links": links}
