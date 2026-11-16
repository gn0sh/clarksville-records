"""Read the county committee and school board agendas (collector/county_committees.py) into agendas.json.

Each stored agenda's text layer (pdftotext -layout) is read as printed, nothing summarised or reworded:
- `title`: the agenda's top lines up to and including the first line that prints a date (at most HEAD_LINES lines),
  plus a lone "Agenda" line under it, joined with spaces. `date_printed`: that date. When it differs from the date in
  the file name the page lists, the meeting keeps the listed date and the difference is a problem in the report;
- `entries`: the rest of the agenda in order. A block of lines between blank lines is one entry; inside a block, a line
  that starts with an item mark (a resolution number such as 26-2-1, a case number such as CZ-22-2025, "1.", "a.",
  "A.", a bullet) starts a new entry and the lines under it join it. Each entry is {text, number, heading, page}:
  `text` the printed words with whitespace joined, `number` the resolution or case number it starts with (as printed,
  less a trailing "*"), `heading` an all-capitals line on its own;
- a one-word cell far right after a wide gap (a table's reference column) is not part of an entry's words;
- a body with `text: false` (the school board) stores no `title` and no entries, only `lines`, the number of entries
  read: its recognitions print students' names, so none of its item text is kept
  (docs/architecture/agenda-withhold-invariant.md). Every meeting carries `lines`;
- an agenda with no text layer (a scan) is kept as a source with no entries (`text_layer: none`); it is never OCR'd
  here, since a misread name or number on an agenda would be shown as printed.
These agendas print no votes and no minutes: nothing is read as either.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import limits
from .store import Store

SCHEMA = "county-committees-1"
MAX_PAGES = 12          # the agendas seen were 1 to 3 pages; a longer file's items are read from its first pages
HEAD_LINES = 6
PARSE_TIMEOUT = 60
MONTHS = ("january february march april may june july august september october november december").split()
DATE_RX = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*((?:19|20)\d\d)\b", re.I)
NUM_DATE_RX = re.compile(r"(?<![\d-])(\d{1,2})/(\d{1,2})/((?:19|20)?\d\d)(?![\d/])")
NUMBER_RX = re.compile(r"^((?:\d{2}-\d{1,2}-\d{1,3})|(?:[A-Z]{1,4}-\d{1,3}-(?:19|20)\d\d))(\*?)(?=\s|$)")
MARK_RX = re.compile(r"^(?:\d{2}-\d{1,2}-\d{1,3}\*?|[A-Z]{1,4}-\d{1,3}-(?:19|20)\d\d\*?|\d{1,2}[.)]|[A-Za-z][.)]"
                     r"|\d{1,2}:\d{2}(?:\s*[AaPp]\.?[Mm]\.?)?"
                     r"|[IVX]{1,4}\.|[••●▪◦o\-–])(?:\s|$)")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
# A right-hand table column (the school board's "Policy Reference" codes and presenters' surnames): one short word
# after a wide gap, far right. It is a separate cell, not part of the item's words, so it is left out of `text`.
RIGHT_CELL = re.compile(r"^(?P<left>.*\S)\s{6,}(?P<cell>\S{1,15})\s*$")
RIGHT_COL = 60


def read_pages(pdf: Path, n: int = MAX_PAGES) -> list[str]:
    out = limits.run("committee_agenda_text.PARSE_TIMEOUT",
                     ["pdftotext", "-f", "1", "-l", str(n), "-layout", "-enc", "UTF-8", str(pdf), "-"], file=pdf,
                     check=True, capture_output=True, timeout=PARSE_TIMEOUT).stdout.decode("utf-8", "replace")
    pages = out.split("\f")
    return pages[:-1] if pages and not pages[-1].strip() else pages


def page_count(pdf: Path) -> int | None:
    from .rpc_agenda import pdf_page_count
    return pdf_page_count(pdf)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def printed_date(text: str) -> str | None:
    from datetime import date
    m = DATE_RX.search(text)
    if m:
        try:
            return date(int(m.group(3)), MONTHS.index(m.group(1).lower()) + 1, int(m.group(2))).isoformat()
        except ValueError:
            return None
    m = NUM_DATE_RX.search(text)
    if m:
        y = int(m.group(3))
        try:
            return date(y + 2000 if y < 100 else y, int(m.group(1)), int(m.group(2))).isoformat()
        except ValueError:
            return None
    return None


def _lines(pages: list[str]) -> list[tuple[int, str]]:
    """(page, line) for every line, blank lines kept as "" (they end a block)."""
    out = []
    for pno, page in enumerate(pages, 1):
        for raw in page.splitlines():
            out.append((pno, CONTROL.sub("", raw).rstrip()))
        out.append((pno, ""))
    return out


def _heading(text: str) -> bool:
    letters = re.sub(r"[^A-Za-z]", "", text)
    return bool(letters) and letters.isupper() and len(text) <= 80 and not NUMBER_RX.match(text)


def _strip_right(ln: str) -> str:
    m = RIGHT_CELL.match(ln)
    if m and m.start("cell") >= RIGHT_COL and len(m.group("left").strip()) > 0:
        return m.group("left")
    return ln


def _heads_list(lines: list[tuple[int, str]], i: int, indent: int) -> bool:
    """The line at i (no mark) names a group: the next line is a marked line indented further."""
    nxt = lines[i + 1][1] if i + 1 < len(lines) else ""
    return bool(nxt.strip()) and bool(MARK_RX.match(nxt.strip())) and len(nxt) - len(nxt.lstrip()) > indent


def read_agenda(pages: list[str]) -> dict:
    """{title, date_printed, entries, text_layer} from an agenda's pages (see the module docstring)."""
    lines = [(p, _strip_right(ln)) for p, ln in _lines(pages)]
    words = sum(len(re.findall(r"[A-Za-z]{2,}", ln)) for _, ln in lines)
    if words < 5:
        return {"title": None, "date_printed": None, "entries": [], "text_layer": "none"}
    nonblank = [i for i, (_, ln) in enumerate(lines) if ln.strip()]
    head_end, when = -1, None
    for i in nonblank[:HEAD_LINES]:
        d = printed_date(lines[i][1])
        if d:
            head_end, when = i, d
            break
    title = None
    if head_end >= 0:
        # the heading runs on to the end of its block (a sentence broken after the date, a table's column heads),
        # up to a line with an item mark
        while head_end + 1 < len(lines) and lines[head_end + 1][1].strip() \
                and not MARK_RX.match(lines[head_end + 1][1].strip()):
            head_end += 1
        after = [i for i in nonblank if i > head_end][:1]
        if after and re.fullmatch(r"\s*agenda\s*", lines[after[0]][1], re.I):
            head_end = after[0]
        title = _clean(" ".join(lines[i][1] for i in nonblank if i <= head_end))
    entries: list[dict] = []
    cur = last = None
    for i, (pno, ln) in enumerate(lines):
        if i <= head_end:
            continue
        if not ln.strip():
            cur = None
            continue
        s = ln.strip()
        indent = len(ln) - len(ln.lstrip())
        mark = MARK_RX.match(s)
        if (cur is None and not mark and last is not None and indent > 0 and abs(indent - last["_col"]) <= 1
                and s[:1].islower()):
            cur = last          # a marked item's sentence carried on below a blank line, at the item's text column
        if cur is not None and not mark and (indent < cur["_col"] - 1 or _heads_list(lines, i, indent)):
            cur = None          # left of the item's words, or a group name over the marked lines below it
        if cur is None or mark:
            m = NUMBER_RX.match(s)
            rest = s[mark.end():] if mark else ""
            col = indent + mark.end() + len(rest) - len(rest.lstrip()) if mark else -9   # where the item's words start
            cur = {"text": s, "number": m.group(1) if m else None, "page": pno, "_lines": 1, "_col": col}
            entries.append(cur)
            last = cur
        else:
            sep = "" if re.search(r"[A-Za-z]-$", cur["text"]) else " "
            cur["text"] = f"{cur['text']}{sep}{s}"
            cur["_lines"] += 1
    out = [{"text": (t := _clean(e["text"])), "number": e["number"], "page": e["page"],
            "heading": e["_lines"] == 1 and _heading(t)} for e in entries]
    return {"title": title, "date_printed": when, "entries": out, "text_layer": "text"}


def source_record(e: dict, pages: int | None, layer: str) -> dict:
    return {"id": f"src-{e['sha256'][:12]}", "url": e["url"], "sha256": e["sha256"], "kind": "agenda",
            "label": e.get("label"), "fetched_at": (e.get("first_fetched_at") or "")[:10], "pages": pages,
            "text_layer": layer, "format": "pdf"}


def build(cfg, rows: list[dict], store: Store, root: Path | None = None, read=None, count=None) -> tuple[dict, dict]:
    """(agendas.json, summary) from the listing rows and the stored agendas, offline. One meeting per listed row
    (body, id); its agenda is the newest stored version of its URL. A row whose file is not stored yet is a meeting
    with no source (`agenda: null`), shown with the county's link only."""
    read = read or read_pages
    count = count or page_count
    sources: dict[str, dict] = {}
    problems: list[dict] = []
    bodies = {b.key: b for b in cfg.bodies}
    meetings = []
    for r in sorted(rows, key=lambda r: (r["body"], r["date"], r["id"])):
        b = bodies.get(r["body"])
        if b is None:
            problems.append({"url": r["url"], "problem": f"body {r['body']!r} is not in the config"})
            continue
        m = {"id": r["id"], "body": r["body"], "date": r["date"], "time": r.get("time"), "kind": r["kind"],
             "printed": r["printed"], "notes": r.get("notes") or [], "cancelled": bool(r.get("cancelled")),
             "url": r["url"], "on_page": r.get("on_page", True), "source_id": None, "title": None,
             "date_printed": None, "lines": 0, "entries": []}
        e = store.latest(r["url"]) if r.get("fetch") else None
        if e is None:
            if r.get("fetch"):
                problems.append({"url": r["url"], "problem": "listed, not fetched yet"})
            meetings.append(m)
            continue
        if not store.has_bytes(e["sha256"]):
            problems.append({"url": r["url"], "problem": "not in the store (run without --offline)"})
            meetings.append(m)
            continue
        p = store.path_for(e["sha256"])
        try:
            pages = read(p)
        except Exception as ex:          # one bad document must not stop the run; it is reported
            problems.append({"url": r["url"], "problem": f"text not read: {type(ex).__name__}: {ex}"})
            meetings.append(m)
            continue
        n = count(p)
        if not n:
            problems.append({"url": r["url"], "problem": "no page count (pdfinfo); agenda left unread"})
            meetings.append(m)
            continue
        got = read_agenda(pages)
        src = source_record(e, n, got["text_layer"])
        sources[src["id"]] = src
        if got["text_layer"] == "none":
            problems.append({"url": r["url"], "problem": "no text layer (a scan); entries not read"})
        if got["date_printed"] and got["date_printed"] != r["date"]:
            problems.append({"url": r["url"], "problem": f"the file name gives {r['date']}, the agenda prints "
                                                         f"{got['date_printed']}; the listed date is kept"})
        if n > MAX_PAGES:
            problems.append({"url": r["url"], "problem": f"{n} pages; entries read from the first {MAX_PAGES}"})
        m.update({"source_id": src["id"], "date_printed": got["date_printed"], "lines": len(got["entries"])})
        if b.text:          # text: false (the school board): no title and no item text, the count only
            m.update({"title": got["title"],
                      "entries": [{**x, "id": f"{r['id']}-e{k}"} for k, x in enumerate(got["entries"], 1)]})
        meetings.append(m)
    covered = sorted(m["date"] for m in meetings)
    out = {"schema": SCHEMA, "listing_url": cfg.listing_url, "record_label": cfg.record_label,
           "bodies": [{"key": b.key, "group": b.group, "name": b.name, "short": b.short, "folder": b.folder,
                       "kind_labels": b.kind_labels, "text": b.text} for b in cfg.bodies],
           "coverage": {"from": covered[0], "to": covered[-1]} if covered else None,
           "meetings": meetings, "sources": sorted(sources.values(), key=lambda s: s["id"])}
    summary = {"meetings": len(meetings), "sources": len(sources),
               "items": sum(len(m["entries"]) for m in meetings),
               "lines": sum(m["lines"] for m in meetings),
               "numbers": sum(1 for m in meetings for x in m["entries"] if x["number"]),
               "by_body": {b.key: sum(1 for m in meetings if m["body"] == b.key) for b in cfg.bodies},
               "problems": problems}
    return out, summary


def shrink_reason(old: dict, new: dict) -> str | None:
    """Why `new` must not replace the committed `old`: a meeting gone, or an agenda that had a source (or was read)
    and now has none (an evicted store, a reader failure). A revised agenda (a new source id) is not a loss."""
    now = {(m["body"], m["id"]): m for m in new.get("meetings", [])}
    gone = [f"{m['body']}/{m['id']}" for m in old.get("meetings", []) if (m["body"], m["id"]) not in now]
    if gone:
        return f"the result would drop {len(gone)} meetings, e.g. {', '.join(gone[:3])}"
    for m in old.get("meetings", []):
        n = now[(m["body"], m["id"])]
        if m.get("source_id") and not n.get("source_id"):
            return f"{m['body']}/{m['id']}: the agenda had a source in the committed record and would have none"
        if (m.get("entries") or m.get("lines")) and not (n.get("entries") or n.get("lines")):
            return f"{m['body']}/{m['id']}: the agenda was read in the committed record and would not be"
    return None

