"""How recent each body's records are (site-polish/freshness-line): one plain line per body on the landing and the
Regional Planning Commission's home, e.g. "Montgomery County Commission: minutes and votes through May 11, 2026;
agendas through November 9, 2026."

Every date is computed from the data at build time, never written by hand: the latest meeting whose minutes were read,
the latest meeting whose agenda was read, and for county finance the latest budget book's fiscal year and the latest
date the purchasing archive prints for a solicitation. The same words for every body; no reason is given for a gap.
"""
from __future__ import annotations

from datetime import date

from . import config

NOTE = "Agendas are posted before a meeting and minutes after it, so the minutes run behind the agendas."


def date_text(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def _part(what: str, iso: str | None) -> dict | None:
    return {"what": what, "iso": iso, "text": date_text(iso)} if iso else None


def _latest(dates) -> str | None:
    ds = [d for d in dates if d]
    return max(ds) if ds else None


def _line(body: str, parts: list) -> dict | None:
    parts = [p for p in parts if p]
    return {"body": body, "parts": parts} if parts else None


def county(ix, agendas=None) -> dict | None:
    """Every county meeting in the facts is read from its minutes; agendas come from the agendas file (only those
    with a page count, as the agenda pages show them)."""
    minutes = _latest(m["date"] for m in ix.facts["meetings"])
    agenda = None
    if agendas is not None:
        agenda = _latest(m["date"] for m in agendas.data.get("meetings", []) if m.get("source_id") in agendas.sources)
    return _line(config.SITE.get("county_body") or ix.coverage["body"],
                 [_part("minutes and votes", minutes), _part("agendas", agenda)])


def council(cix) -> dict | None:
    """A council meeting may be listed from its agenda alone (minutes not posted): minutes count only when the
    meeting's source is a minutes document."""
    minutes = _latest(m["date"] for m in cix.facts["meetings"]
                      if (cix.sources.get(m.get("source_id") or "") or {}).get("kind") == "minutes")
    agenda = _latest(m["date"] for m in cix.facts["meetings"]
                     if m.get("agenda_source_id")
                     or (cix.sources.get(m.get("source_id") or "") or {}).get("kind") == "agenda")
    return _line(cix.body_name, [_part("minutes and votes", minutes), _part("agendas", agenda)])


def rpc(rpx) -> dict | None:
    """The commission's motions are not shown as confirmed votes while held, so its line names minutes only."""
    ms = rpx.facts["meetings"]
    return _line(rpx.body, [_part("minutes", _latest(m["date"] for m in ms if m.get("minutes_source_id"))),
                            _part("agendas", _latest(m["date"] for m in ms if m.get("agenda_source_id")))])


def finance(fin: dict | None) -> dict | None:
    if not fin:
        return None
    years = [b["fiscal_year"] for b in fin.get("books") or [] if b.get("fiscal_year")]
    parts = []
    if years:
        parts.append({"what": "approved budget books", "iso": None, "text": f"fiscal year {max(years)}"})
    parts.append(_part("bids and awards", _latest(s.get("archive_date") for s in fin.get("solicitations") or [])))
    return _line(f"{config.SITE.get('county_name') or 'County'} finance", parts)


def lines(ix, agendas=None, councils=(), rpx=None, fin: dict | None = None) -> list[dict]:
    out = [county(ix, agendas), *(council(c) for c in councils), rpc(rpx) if rpx is not None else None,
           finance(fin)]
    return [x for x in out if x]
