"""How recent each body's records are (site-polish/freshness-line): one plain line per body on the landing and the
Regional Planning Commission's home, e.g. "Montgomery County Commission: minutes and votes through May 11, 2026;
agendas through November 9, 2026."

Every date is computed from the data at build time, never written by hand: the latest meeting whose minutes were read,
the latest meeting whose agenda was read, and for county finance the latest approved budget book's fiscal year and the
latest date the purchasing archive prints for a solicitation. Each date links to the site page of the meeting (or
record) that set it, which links its source document (site-polish/freshness-no-source-link). The same words for every
body; no reason is given for a gap.
"""
from __future__ import annotations

from datetime import date

from . import config

NOTE = "Agendas are posted before a meeting and minutes after it, so the minutes run behind the agendas."


def date_text(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def _part(what: str, iso: str | None, href: str | None = None) -> dict | None:
    """`href`: the page that set the date, relative to the site root (an https URL only for a source document)."""
    return {"what": what, "iso": iso, "text": date_text(iso), "href": href} if iso else None


def _newest(meetings) -> dict | None:
    """The meeting with the latest date (ties: the greater id, so the choice never depends on file order)."""
    ms = [m for m in meetings if m.get("date")]
    return max(ms, key=lambda m: (m["date"], m.get("id") or "")) if ms else None


def _line(body: str, parts: list) -> dict | None:
    parts = [p for p in parts if p]
    if not parts:
        return None
    # NOTE (minutes run behind agendas) is about a line with both minutes and agendas (site-polish/freshness-a11y)
    whats = {p["what"] for p in parts}
    return {"body": body, "parts": parts,
            "lagged": "agendas" in whats and any(w.startswith("minutes") for w in whats)}


def county(ix, agendas=None) -> dict | None:
    """Every county meeting in the facts is read from its minutes; agendas come from the agendas file (only those
    with a page count, as the agenda pages show them). The latest agenda links to its section on the agendas page
    while it has no minutes, else to the meeting page its minutes give it (Agendas.__init__: same id, or same date
    and kind)."""
    m = _newest(ix.facts["meetings"])
    minutes = _part("minutes and votes", m["date"], ix.meeting_href(m["id"])) if m else None
    agenda = None
    if agendas is not None:
        a = _newest(x for x in agendas.data.get("meetings", []) if x.get("source_id") in agendas.sources)
        if a:
            if any(x["id"] == a["id"] for x in agendas.meetings):
                href = agendas.href(a["id"])
            else:
                held = ix.meetings.get(a["id"]) or next(
                    (x for x in ix.facts["meetings"] if (x["date"], x["kind"]) == (a["date"], a.get("kind"))), None)
                href = ix.meeting_href(held["id"]) if held else None
            agenda = _part("agendas", a["date"], href)
    return _line(config.SITE.get("county_body") or ix.coverage["body"], [minutes, agenda])


def council(cix) -> dict | None:
    """A council meeting may be listed from its agenda alone (minutes not posted): minutes count only when the
    meeting's source is a minutes document."""
    def kind(m):
        return (cix.sources.get(m.get("source_id") or "") or {}).get("kind")
    mm = _newest(m for m in cix.facts["meetings"] if kind(m) == "minutes")
    am = _newest(m for m in cix.facts["meetings"] if m.get("agenda_source_id") or kind(m) == "agenda")
    return _line(cix.body_name, [mm and _part("minutes and votes", mm["date"], cix.meeting_href(mm["id"])),
                                 am and _part("agendas", am["date"], cix.meeting_href(am["id"]))])


def rpc(rpx) -> dict | None:
    """The commission's motions are not shown as confirmed votes while held, so its line names minutes only."""
    ms = rpx.facts["meetings"]
    mm = _newest(m for m in ms if m.get("minutes_source_id"))
    am = _newest(m for m in ms if m.get("agenda_source_id"))
    return _line(rpx.body, [mm and _part("minutes", mm["date"], rpx.meeting_href(mm["id"], mm["date"])),
                            am and _part("agendas", am["date"], rpx.meeting_href(am["id"], am["date"]))])


def finance(fin: dict | None, budget_href: str | None = None) -> dict | None:
    """Approved budget books only (site-polish/freshness-finance-edition: no other edition is called approved): the
    newest fiscal year, linked to the books on the budget page (`budget_href`, when built), else to the book itself.
    Bids and awards: the newest date the purchasing archive prints, linked to that solicitation's page."""
    if not fin:
        return None
    books = [b for b in fin.get("books") or [] if b.get("fiscal_year") and b.get("edition") == "approved"]
    parts = []
    if books:
        b = max(books, key=lambda b: (b["fiscal_year"], b.get("id") or ""))
        src = next((s for s in fin.get("sources") or [] if s.get("id") == b.get("source_id")), None)
        href = f"{budget_href}#books-h" if budget_href else (src or {}).get("url")
        parts.append({"what": "approved budget books", "iso": None, "text": f"fiscal year {b['fiscal_year']}",
                      "href": href})
    sols = [s for s in fin.get("solicitations") or [] if s.get("archive_date")]
    if sols:
        s = max(sols, key=lambda s: (s["archive_date"], s.get("id") or ""))
        parts.append(_part("bids and awards", s["archive_date"],
                           f"contracts/{s['slug']}.html" if s.get("slug") else None))
    return _line(f"{config.SITE.get('county_name') or 'County'} finance", parts)


def lines(ix, agendas=None, councils=(), rpx=None, fin: dict | None = None,
          budget_href: str | None = None) -> list[dict]:
    out = [county(ix, agendas), *(council(c) for c in councils), rpc(rpx) if rpx is not None else None,
           finance(fin, budget_href)]
    return [x for x in out if x]
