"""County Commission agenda-only meetings (docs/research/county-recency.md, Fix 1 and Fix 2).

Input: data/county-agendas/agendas.json (collector/county_agenda.py). A meeting there is shown only while the county's
minutes do not cover it: a meeting drops out once data/facts.json holds a minutes meeting of the same date and kind
(its votes then come from the minutes, on its own meeting page). A special session on the day of a formal one stays
until its own minutes are read. This site holds no minutes for informal sessions, so theirs stay. A source without a
page count is left out (every item link cites a page). Copy: config/site.yml county_agendas.

Page (one, so the preview build stays near its file budget): meetings/agendas.html, one section per meeting
(#<meeting id>), newest first, with its agenda PDF, its items as the agenda prints them (each linked to the agenda page
it is printed on) and a line saying the minutes are not posted yet. Item titles carry data-item-title: the document's
words, never linked or reworded.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from . import config, localdates


PAGE = "meetings/agendas.html"
RECORD_LABEL = "the County Commission's agendas page"


def _date_text(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def load(path: Path | None) -> dict | None:
    p = Path(path) if path else None
    if p is None or not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


class Agendas:
    def __init__(self, data: dict, ix, today: date):
        self.data = data
        self.ix = ix
        self.today = today
        self.sources = {s["id"]: s for s in data.get("sources", [])}
        self.text = config.COUNTY_AGENDAS_TEXT
        self.sources = {k: s for k, s in self.sources.items() if s.get("pages")}   # agenda-data/pages-none
        # covered by the minutes: the same meeting id, or the same date and kind (idempotence/special-hidden-by-same-
        # day-formal: a special session on a formal meeting's day is its own meeting)
        covered = {(m["date"], m["kind"]) for m in ix.facts["meetings"]}
        self.meetings = [m for m in data.get("meetings", [])
                         if m["id"] not in ix.meetings
                         and (m["date"], m["kind"]) not in covered
                         and m["source_id"] in self.sources]
        self.meetings.sort(key=lambda m: (m["date"], m["id"]), reverse=True)

    @property
    def record(self) -> dict:
        return {"url": self.data["index_url"], "label": RECORD_LABEL}

    def href(self, mid: str) -> str:
        return f"{PAGE}#{mid}"

    def minutes_note(self, m: dict) -> str | None:
        """Past meetings only: what the county has not posted yet, as of the build date."""
        if m["date"] >= self.today.isoformat():
            return None
        when = _date_text(self.today.isoformat())
        key = "minutes_note_informal" if m["kind"] == "informal" else "minutes_note"
        return self.text[key].format(date=when)

    def meeting(self, m: dict) -> dict:
        src = self.sources[m["source_id"]]
        items, used = [], set()
        for it in m["items"]:
            known = self.ix.items.get(it["number"])
            anchor, n = f"{m['id']}-{it['number']}", 1
            while anchor in used:                        # a number printed twice on one agenda: ids stay unique
                n += 1
                anchor = f"{m['id']}-{it['number']}-{n}"
            used.add(anchor)
            items.append({**it, "anchor": anchor,
                          "src": f"{src['url']}#page={it['page']}",
                          "item_href": self.ix.item_href(known) if known else None})
        return {"id": m["id"], "date": m["date"], "date_text": _date_text(m["date"]), "kind": m["kind"],
                "kind_label": self.ix.kind_labels.get(m["kind"], m["kind"]), "href": self.href(m["id"]),
                "doc": {"url": src["url"], "pages": src["pages"], "fetched": localdates.fetched(src)},
                "entries": items, "minutes_note": self.minutes_note(m),
                "upcoming": m["date"] > self.today.isoformat(), "on_build_day": m["date"] == self.today.isoformat()}

    def page(self) -> dict:
        return {"meetings": [self.meeting(m) for m in self.meetings], "body": self.ix.coverage["body"],
                "minutes_to": self.ix.coverage["to"], "built_text": _date_text(self.today.isoformat()),
                "record": self.record}

    def list_entries(self) -> list[dict]:
        """For meetings.html: one line per agenda-only meeting, newest first."""
        return [{"date": m["date"], "href": self.href(m["id"]), "kind_label": self.ix.kind_labels.get(m["kind"], m["kind"]),
                 "n_items": len(m["items"]), "note": self.minutes_note(m)} for m in self.meetings]


def make(ix, today: date, path: Path | None) -> Agendas | None:
    """None when there is no agendas file (build.py passes none for a fixture build unless a test names one)."""
    data = load(path)
    return Agendas(data, ix, today) if data else None
