"""Adapter 1: the county purchasing archive page -> archive rows and their document links (architecture A2).

The page is one <table> whose cells are <th>. Row 1 is the header, checked by exact text against finance.yml
`archive_header`; a changed header, a row without 3 cells, more than one table or zero data rows raises
StructureChanged (AC-F11): the run fails loudly instead of guessing. Per row the title and the Award Date cell are
kept verbatim (whitespace collapsed); the date is parsed with finance.yml `date_formats` after two mechanical repairs
only (spaces inside a month word closed, "." before the year read as ","). A status word is kept as the status;
anything else that does not parse is held (check `date-unparsed`). Every <a href> in the documents cell is one
document (AC-F7) with its label verbatim, its absolute URL and a stage from `stage_rules`.
"""
from __future__ import annotations

import calendar
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser

from .fin_config import FinanceConfig

MONTHS = tuple(m.upper() for m in calendar.month_name if m)
WS = re.compile(r"\s+")


class StructureChanged(Exception):
    """The archive page no longer has the shape the adapter reads. Never guessed around."""


@dataclass
class Link:
    label: str           # verbatim link text, whitespace collapsed
    url: str             # absolute, normalised
    stage: str


@dataclass
class ArchiveRow:
    row: int             # 1 = first data row
    title: str
    date_text: str
    date: str | None     # ISO or None
    status: str | None   # status word as printed
    date_held: bool      # text present, not a status word, not parseable (check date-unparsed)
    links: list = field(default_factory=list)


def squash(s: str) -> str:
    return WS.sub(" ", s.replace("\xa0", " ")).strip()


class _Table(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.rows = 0, []
        self._cell = self._a = None
        self._depth = 0                       # table nesting

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self.tables += 1
            self._depth += 1
        elif self._depth and tag == "tr":
            self.rows.append([])
        elif self._depth and tag in ("th", "td") and self.rows:
            self._cell = {"text": "", "links": []}
            self.rows[-1].append(self._cell)
        elif tag == "a" and self._cell is not None and a.get("href"):
            self._a = {"href": a["href"], "text": ""}
            self._cell["links"].append(self._a)
        elif tag == "br" and self._cell is not None:
            self._cell["text"] += " "

    def handle_endtag(self, tag):
        if tag == "a":
            self._a = None
        elif tag in ("th", "td"):
            self._cell = None
        elif tag == "table":
            self._depth -= 1

    def handle_data(self, d):
        if self._cell is not None:
            self._cell["text"] += d
        if self._a is not None:
            self._a["text"] += d


LINK_SCHEMES = ("http", "https")


def absolute(base: str, href: str) -> str:
    """The link as a request URL: joined to the archive URL, path characters percent-encoded once (existing %XX kept;
    a quote mark, which the schema's uri rule refuses, becomes %27), fragment dropped. Only an http(s) link is a
    document: any other scheme (javascript:, data:, mailto:) raises StructureChanged, so it never reaches a page's
    href and is never silently dropped from the row (provenance/href-scheme)."""
    u = urllib.parse.urlsplit(urllib.parse.urljoin(base, href.strip()))
    if u.scheme.lower() not in LINK_SCHEMES or not u.netloc:
        raise StructureChanged(f"archive link {href!r} is not an http(s) URL")
    path = urllib.parse.quote(u.path, safe="/%()&+,;=~:@!$*-._")
    return urllib.parse.urlunsplit((u.scheme.lower(), u.netloc.lower(), path, u.query, ""))


def stage_of(label: str, cfg: FinanceConfig) -> str:
    text = squash(label)
    for stage, rx in cfg.stage_rules:
        if rx.search(text):
            return stage
    raise StructureChanged(f"no stage rule matches link label {label!r} (finance.yml stage_rules needs a catch-all)")


def repair_date(text: str) -> str:
    """The two mechanical repairs, nothing else: close spaces inside a month word ("F EBRUARY" -> "FEBRUARY") and read
    "." before the year as "," ("OCTOBER 30. 2025")."""
    out = text
    for m in MONTHS:
        spaced = r"\b" + r"\s*".join(re.escape(c) for c in m) + r"\b"
        out = re.sub(spaced, lambda mo: mo.group(0).replace(" ", ""), out, flags=re.I)
    return re.sub(r"(\d)\.\s+(\d{4})\b", r"\1, \2", out)


def parse_date(text: str, cfg: FinanceConfig) -> str | None:
    fixed = repair_date(text)
    for fmt in cfg.date_formats:
        try:
            return datetime.strptime(fixed, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_archive(html: str, cfg: FinanceConfig) -> list[ArchiveRow]:
    t = _Table()
    t.feed(html)
    t.close()
    if t.tables != 1:
        raise StructureChanged(f"archive page has {t.tables} tables, expected 1")
    if not t.rows:
        raise StructureChanged("archive table has no rows")
    header = tuple(squash(c["text"]) for c in t.rows[0])
    if header != cfg.archive_header:
        raise StructureChanged(f"archive header is {header!r}, expected {cfg.archive_header!r}")
    status = {w.casefold(): w for w in cfg.status_words}
    rows = []
    for i, cells in enumerate(t.rows[1:], start=1):
        if len(cells) != 3:
            raise StructureChanged(f"archive row {i} has {len(cells)} cells, expected 3")
        title = squash(cells[0]["text"])
        if not title:
            raise StructureChanged(f"archive row {i} has no title")
        dtext = squash(cells[2]["text"])
        st = dtext if dtext and dtext.casefold() in status else None
        iso = parse_date(dtext, cfg) if dtext and not st else None
        links = [Link(squash(a["text"]), absolute(cfg.archive_url, a["href"]), stage_of(a["text"], cfg))
                 for a in cells[1]["links"]]
        rows.append(ArchiveRow(i, title, dtext, iso, st, bool(dtext and not st and not iso), links))
    if not rows:
        raise StructureChanged("archive table has a header but no data rows")
    return rows
