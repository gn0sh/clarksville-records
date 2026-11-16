"""The "Show records from" switch and each body's hub cards (config/site.yml `switch:`; owner's mock 2026-11-12).

Four public bodies share this site: the county, the city, the school board and the planning commission. The switch is
on every page, right under the header: All, then one option per body whose hub page this build makes. Each option is a
plain link to that body's hub (All is the home page), so it works without script; static/switch.js remembers the
choice on the device and hides the rows of other bodies on the pages whose rows carry data-body.

A hub shows section cards. A card is "present" only when this build makes the page it links; a "coming" card is
dashed, says what is not collected yet, and links the body's own official page. Every such URL is read from the config
(a dotted path into config/site.yml, or the RPC's record page): none is written here, and a card whose link cannot be
resolved to an https URL is left without a link, never with a guessed one. A coming card with a `built:` block
(its text and `go` once collected) is shown present, with those words, when the build makes the page it links.
"""
from __future__ import annotations

import posixpath

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


def _hrefs(site: dict, councils, rpc, cmx=None, committees=()) -> dict[str, dict[str, str]]:
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
                       "finance": site.get("city_budget"),
                       "transcripts": f"{c.slug}/meetings/{years[-1]}.html"
                       if years and tx is not None and tx.pages and tx.by_meeting else None}
    for cm in committees:   # each city committee's own card (config city_committees.pages[].card)
        out.setdefault("city", {})[cm.card] = cm.home_href()
    if cmx is not None:   # agendas from the county's committee agendas page (sitegen/county_committees.py)
        if cmx.school_home():
            k = cmx.school[0]
            out["school"] = {"meetings": cmx.year_href(k, cmx.years(k)[0])}
        if cmx.finance_home():
            out["county"]["finance-committees"] = cmx.finance_home()
            if "budget-committee" in cmx.finance:
                out["county"]["budget-committee"] = f"{cmx.finance_home()}#budget-committee"
    if rpc is not None:
        years = rpc.years()
        out["rpc"] = {"meetings": f"{rpc.home_href()}#y{years[0]}-h" if years else None,
                      "cases": rpc.year_href(years[0]) if years else None}
    return {k: {a: b for a, b in v.items() if b} for k, v in out.items()}


def build(site: dict, councils=(), rpc=None, cmx=None, committees=()) -> dict | None:
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
    hrefs = _hrefs(site, councils, rpc, cmx, committees)
    votes_shown = rpc is not None and rpc.votes_shown
    options = [{"key": ALL, "label": cfg["all"]["label"], "short": None, "href": "index.html", "coming": False}]
    hubs = {}
    for key in ORDER:
        b = bodies.get(key)
        if not b or not home[key]:
            continue
        cards = []
        for c in b.get("cards") or []:
            if c.get("coming") and c.get("built") and hrefs.get(key, {}).get(c["key"]):
                # a coming card whose page this build makes (`built`: its text once collected) is shown present
                c = {**c, **c["built"], "coming": False}
            if c.get("coming"):
                if key == "rpc" and c["key"] == "votes" and votes_shown:
                    continue      # the hold is lifted: the card no longer applies
                cards.append({"key": c["key"], "title": c["title"], "text": c["text"], "coming": True, "href": None,
                              "link": official_link(c.get("link"), rpc),
                              "door": c.get("door")})   # the landing door that names it as coming (views.door_coming)
            elif hrefs.get(key, {}).get(c["key"]):
                text = c["text"]
                if "{books}" in text:          # the city budget card: the books read, from the data (no year list here)
                    if not site.get("city_budget_books"):
                        continue
                    text = text.format(books=site["city_budget_books"])
                cards.append({"key": c["key"], "title": c["title"], "text": text, "coming": False,
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


def finance_note(rpc=None, key: str = "finance_note", sibling: str | None = None) -> dict | None:
    """A budget index's top line (config `switch.finance_note` for the county's, `switch.city_finance_note` for the
    city's): the text, the other body's budget pages when they are built (`sibling`: their index path) and the
    official links."""
    fn = _cfg().get(key) or {}
    if not fn.get("text"):
        return None
    links = [x for x in (official_link(s, rpc) for s in fn.get("links") or []) if x]
    sib = ({"lede": fn["sibling"]["lede"], "label": fn["sibling"]["label"], "href": sibling}
           if sibling and isinstance(fn.get("sibling"), dict) else None)
    return {"text": fn["text"], "link_lede": fn.get("link_lede") or "", "links": links, "sibling": sib}


# The one "where am I" line (onceover/wayfinding/three-crumb-patterns): every page that is not the home page or a
# body's own landing page carries one .crumb line above its h1, a link up to where the page belongs. A page of one
# body's records leads to that body's landing page, then to its section's list where the page is one of many; every
# other page leads home. Labels are the switch's and the menu's own words.
COUNTY_SECTIONS = {"meetings/": "meetings.html", "officials/": "officials.html", "districts/": None, "votes/": None,
                   "items/": None, "meetings.html": None, "officials.html": None}
SITE_SECTIONS = {"finance/": "finance/index.html", "contracts/": "contracts/index.html"}
HOME = "index.html"


def crumbs(site: dict, rel: str, councils=(), rpc=None, cmx=None) -> list[dict]:
    """[{label, href}] for the page at `rel`, outermost first; [] on the home page and on a body's landing page."""
    sw = site.get("switch") or {}
    if rel == "index.html" or rel in (sw.get("current") or {}):
        return []
    hubs = sw.get("hubs") or {}
    nav = {e["href"]: e["label"] for e in site.get("nav") or [] if e.get("href")}
    home = {"label": nav.get(HOME, "Home"), "href": HOME}

    def hub(key: str) -> list[dict]:
        h = hubs.get(key)
        return [{"label": h["label"], "href": h["href"]}] if h else [dict(home)]

    for c in councils:
        if rel.startswith(f"{c.slug}/"):
            out = hub("city") if councils and c is councils[0] else [{"label": c.nav_label, "href": c.home_href()}]
            city_budget = site.get("city_budget")      # a city fund page: up to the city budget index (city/finance/)
            if city_budget and c is councils[0] and rel.startswith(posixpath.dirname(city_budget) + "/") \
                    and rel != city_budget:
                out.append({"label": config.FIN_TEXT["budget_city"]["title"], "href": city_budget})
            return out
    if rpc is not None and rel.startswith(f"{rpc.slug}/"):
        return hub("rpc")
    if cmx is not None:       # school board agendas: the school board's page; county finance committees: the county's
        if cmx.school_slug and rel.startswith(f"{cmx.school_slug}/"):
            return hub("school")
        if rel.startswith(f"{cmx.finance_slug}/"):
            out = hub("county")
            if rel != cmx.finance_home():
                out.append({"label": cmx.cfg["finance"]["title"], "href": cmx.finance_home()})
            return out
    for prefix, up in COUNTY_SECTIONS.items():
        if rel == prefix or (prefix.endswith("/") and rel.startswith(prefix)):
            out = hub("county")
            if up and up in nav and up != rel:
                out.append({"label": nav[up], "href": up})
            return out
    for prefix, up in SITE_SECTIONS.items():
        if rel.startswith(prefix) and rel != up and up in nav:
            return [dict(home), {"label": nav[up], "href": up}]
    return [dict(home)]
