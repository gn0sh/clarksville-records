"""What the site holds, in numbers (stats.html; Daylight round 2 item I, ADR 0008 "content stats").

Every number is counted from the data files at build time, never typed: per body the meetings, agenda items, votes
and source documents loaded, the first and last meeting date, and the last day a source was fetched; then what is
still COMING (the nav's coming pages). Counts of records only: no count is ever made per person, and nothing is
ranked or compared. The same words for every body. The later private dashboard can read this page.
"""
from __future__ import annotations

from . import config, localdates

PAGE = "stats.html"
TITLE = "The site in numbers"


def _dates(meetings) -> tuple[str, str] | None:
    ds = sorted(m["date"] for m in meetings if m.get("date"))
    return (ds[0], ds[-1]) if ds else None


def _fetched(sources) -> str | None:
    sp = localdates.span(list(sources))
    return sp[1] if sp else None


def _row(body: str, href: str | None, counts: list, meetings, sources) -> dict:
    return {"body": body, "href": href, "counts": [{"label": k, "n": n} for k, n in counts if n is not None],
            "dates": _dates(meetings), "fetched": _fetched(sources)}


def page(ix, cixs=(), rpx=None, ax=None, fx=None, nav=(), budget_href: str | None = None) -> dict:
    """`ix`: the county's views.Index; `cixs`: each council; `rpx`: the Regional Planning Commission; `ax`: the
    county's agenda-only meetings; `fx`: county finance (fin_views.Finance); `nav`: the site's nav entries (the
    coming ones are listed); `budget_href`: the finance index when its budget pages are built."""
    f = ix.facts
    county_sources = list(f["sources"]) + (list(ax.sources.values()) if ax else [])
    rows = [_row(config.SITE.get("county_body") or ix.coverage["body"], "meetings.html",
                 [("Meetings with minutes", len(f["meetings"])),
                  ("Meetings with an agenda only so far", len(ax.meetings) if ax else None),
                  ("Agenda items", len(f["items"])), ("Motions", len(f["motions"])),
                  ("Votes taken", len(f["roll_calls"])), ("Source documents", len(county_sources))],
                 f["meetings"], county_sources)]
    for c in cixs:
        cf = c.facts
        rows.append(_row(c.body_name, c.home_href(),
                         [("Meetings", len(cf["meetings"])), ("Agenda items", len(cf["items"])),
                          ("Motions", len(cf["motions"])), ("Votes taken", len(cf["roll_calls"])),
                          ("Source documents", len(cf["sources"]))],
                         cf["meetings"], cf["sources"]))
    if rpx is not None:
        rf = rpx.facts
        rows.append(_row(rpx.body, rpx.home_href(),
                         [("Meetings", len(rf["meetings"])), ("Cases", len(rf.get("cases") or [])),
                          ("Motions", len(rf.get("motions") or [])), ("Source documents", len(rf["sources"]))],
                         rf["meetings"], rf["sources"]))
    if fx is not None:
        fin = fx.fin
        rows.append(_row(f"{config.SITE.get('county_name') or 'County'} budget and purchasing", budget_href or
                         "contracts/index.html",
                         [("Budget books", len(fin.get("books") or []) or None),
                          ("Budget lines", len(fin.get("budget_lines") or []) or None),
                          ("Purchasing solicitations", len(fin.get("solicitations") or [])),
                          ("Source documents", len(fin.get("sources") or []))],
                         [], fin.get("sources") or []))
    coming = [{"label": e["label"], "href": e["href"]} for e in nav if e.get("coming") and e.get("href")]
    totals = [{"label": k, "n": sum(c["n"] for r in rows for c in r["counts"] if c["label"] == k)}
              for k in ("Meetings", "Agenda items", "Votes taken", "Source documents")]
    totals[0]["n"] += sum(c["n"] for r in rows for c in r["counts"] if c["label"] == "Meetings with minutes")
    return {"rows": rows, "coming": coming, "totals": totals, "title": TITLE}
