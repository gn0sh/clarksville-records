"""parse_minutes(pdf_path, source) -> ParsedMinutes: the M0 parser plus what M1 needs around it.

Raw fragments only (names as written, no official ids, no verification status beyond the parser's P2 readings):
- attendance header and roll calls (collector.parse, the M0 spike code);
- a second reading by tesseract for every roll call that fails on the text layer, pages OCRed in parallel;
- consent-agenda lists ("... Adopted and Approved as part of the Consent Agenda:"), so one consent roll call
  becomes a vote event on each item it covered, minus items pulled for separate votes;
- agenda listings (the agenda printed in the minutes), as `listed` events.
Deterministic: the same bytes give the same fragments.
"""
from __future__ import annotations

import os
import re
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import parse as P
from .extract import cached_pages, image_only_pages

ROOT = Path(__file__).resolve().parent.parent
TEXT_CACHE = ROOT / "data" / "text"
MAX_PAGES = 500
OCR_WORKERS = 4


@dataclass
class Entry:
    """One line-item of an agenda or consent list."""
    number: str | None        # normalised, or None
    raw_number: str | None
    title: str                # verbatim (whitespace collapsed)
    label: str                # verbatim line(s) as listed
    page: int
    order: int                # line position on the page


@dataclass
class ConsentList:
    page: int
    order: int
    line: int                 # global line index, to pair with the next consent roll call
    label: str                # verbatim heading sentence
    entries: list = field(default_factory=list)
    pulled: list = field(default_factory=list)   # normalised numbers named as pulled/removed


@dataclass
class ParsedMinutes:
    source: dict              # manifest entry
    pages: int
    text_layer: str           # text | none
    image_only_pages: list
    attendance: P.Attendance | None
    roll_calls: list          # [P.RollCall]
    consent_lists: list       # [ConsentList]
    agenda: list              # [Entry]
    titles: dict
    page_of_line: list


CONSENT_HEAD = re.compile(r"as\s+part\s+of\s+(?:the\s+)?Consent\W{0,3}Agenda\s*:", re.I)
PULLED = re.compile(r"(?:pulled|removed)\s+from\s+the\s+Consent", re.I)
BULLET = re.compile(r"^\s*[•●·]\s*(\S.*)$")


def _line_order(lines_page: list[int], i: int) -> int:
    """Position of global line i within its page (0-based)."""
    p = lines_page[i]
    j = i
    while j > 0 and lines_page[j - 1] == p:
        j -= 1
    return i - j


def _collect_entry(lines: list[str], i: int, first_text: str, stop) -> tuple[str, int]:
    parts = [first_text.strip()]
    j = i + 1
    while (j < len(lines) and re.match(r"\s{6,}\S", lines[j]) and not stop(lines[j])
           and not P.ITEM_RE.fullmatch(lines[j].strip())):         # a resolution's page-header number
        t = lines[j].strip()
        if re.fullmatch(r"[-—–_~•.]+", t):
            j += 1
            continue
        parts.append(t)
        j += 1
    return " ".join(" ".join(parts).split()).rstrip(" -—"), j


def _number_at_start(line: str):
    m = re.match(r"\s*(\S{5,12}?)\*?\s{2,}(\S.*)$", line)
    if not m:
        return None
    tok = m.group(1).rstrip("*")
    if not P.ITEM_RE.fullmatch(tok):
        return None
    n = P.norm_item(tok)
    return (tok, n if P.valid_number(n) else None, m.group(2))


def consent_lists(lines: list[str], page_of: list[int], spans) -> list[ConsentList]:
    out = []
    for i, l in enumerate(lines):
        alone = CONSENT_HEAD.search(l)
        prev = lines[i - 1] if i > 0 else ""
        split = not alone and CONSENT_HEAD.search(prev + " " + l) and not CONSENT_HEAD.search(prev)
        if not (alone or split):
            continue
        if any(a <= i < b for a, b in spans):
            continue                                   # an earlier meeting's attached minutes
        start = i - 1 if split else i
        label = " ".join((prev + " " + l).split()) if split else " ".join(l.split())
        cl = ConsentList(page_of[i], _line_order(page_of, start), i, label)
        j = i + 1
        blank = 0

        def stop(x):
            return bool(_number_at_start(x) or BULLET.match(x) or PULLED.search(x))
        while j < len(lines) and j < i + 120:
            x = lines[j]
            if not x.strip():
                blank += 1
                if blank > 3 and cl.entries:
                    break
                j += 1
                continue
            blank = 0
            if PULLED.search(x):
                sent = x
                k = j + 1
                while k < len(lines) and "." not in sent.split("Consent")[-1] and k < j + 3:
                    sent += " " + lines[k]
                    k += 1
                for raw in P.ITEM_RE.findall(sent):
                    n = P.norm_item(raw)
                    if P.valid_number(n):
                        cl.pulled.append(n)
                if cl.entries:
                    break
                j += 1
                continue
            num = _number_at_start(x)
            bul = BULLET.match(x)
            if num:
                raw, n, rest = num
                title, nj = _collect_entry(lines, j, rest, stop)
                cl.entries.append(Entry(n, raw, title, " ".join(x.split()) if nj == j + 1 else
                                        f"{raw} {title}", page_of[j], _line_order(page_of, j)))
                j = nj
                continue
            if bul:
                title, nj = _collect_entry(lines, j, bul.group(1), stop)
                title = title.strip(" —-")
                if title:
                    cl.entries.append(Entry(None, None, title, title, page_of[j], _line_order(page_of, j)))
                j = nj
                continue
            if cl.entries:
                break                                  # list ended: next paragraph or a resolution text
            j += 1
        out.append(cl)
    return out


def inline_consent_lists(lines: list[str], page_of: list[int], rcs, titles: dict) -> list[ConsentList]:
    """2021-2022 layout: a "Consent Agenda" line, then the item numbers separated by commas and one line per other
    item, then "On Motion ... the foregoing Consent Agenda items were Adopted ..." and the table."""
    out = []
    for rc in rcs:
        if rc.kind != "consent":
            continue
        head = next((j for j in range(rc.line - 1, max(rc.line - 30, -1), -1)
                     if re.fullmatch(r"Consent\W{0,3}Agenda[\s:.\-—–]*", lines[j].strip(), re.I)), None)
        if head is None:
            continue
        cl = ConsentList(page_of[head], _line_order(page_of, head), head, " ".join(lines[head].split()))
        for j in range(head + 1, rc.line):
            x = lines[j].strip()
            if re.search(r"\bMotion\b", x):
                break
            if not x or re.fullmatch(r"[-—–_~•.]+", x):
                continue
            nums = [P.norm_item(t) if P.ITEM_RE.fullmatch(t) else None for t in re.split(r"\s*,\s*", x.rstrip(","))]
            if nums and all(P.valid_number(n) for n in nums):
                for n in nums:
                    cl.entries.append(Entry(n, n, titles.get(n) or n, n, page_of[j], _line_order(page_of, j)))
            else:
                cl.entries.append(Entry(None, None, x, x, page_of[j], _line_order(page_of, j)))
        if cl.entries:
            out.append(cl)
    return out


def agenda_entries(lines: list[str], page_of: list[int], spans, max_page: int = 6) -> list[Entry]:
    """Numbered items on the agenda printed at the front of the minutes (not attached earlier minutes)."""
    out = []
    i = 0
    while i < len(lines) and page_of[i] <= max_page:
        if any(a <= i < b for a, b in spans):
            i += 1
            continue
        if re.search(r"BE\s+IT\s+REMEMBERED", lines[i], re.I) and page_of[i] > 1:
            break
        if CONSENT_HEAD.search(lines[i]) or re.search(r"The\s+following\s+Resolution", lines[i], re.I):
            break                                      # proceedings started: the agenda is over
        num = _number_at_start(lines[i])
        if num:
            raw, n, rest = num
            title, nj = _collect_entry(lines, i, rest, lambda x: bool(_number_at_start(x)))
            if n is None or n not in {e.number for e in out}:
                out.append(Entry(n, raw, title, f"{raw} {title}", page_of[i], _line_order(page_of, i)))
            i = nj
            continue
        i += 1
    return out


# ------------------------------------------------------------------ OCR second reading

def _ocr_job(args):
    pdf, page, sha = args
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    from .ocr import ocr_page
    try:
        ocr_page(Path(pdf), page, sha)
        return page, None
    except Exception as e:      # recorded as a failed reading, never a guessed one
        return page, str(e)


def ocr_pages_parallel(jobs: list[tuple[str, int, str]], workers: int = OCR_WORKERS) -> dict:
    """OCR (pdf, page, sha) jobs into the cache using all cores. Returns {(sha, page): error|None}."""
    from .ocr import cache_path
    todo = [j for j in jobs if not cache_path(j[2], j[1]).exists()]
    errors = {}
    if todo:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for (pdf, page, sha), (_, err) in zip(todo, ex.map(_ocr_job, todo, chunksize=2)):
                errors[(sha, page)] = err
    return errors


def parse_minutes(pdf_path: Path, source: dict, use_ocr: bool = True, text_cache: Path = TEXT_CACHE) -> ParsedMinutes:
    pdf_path = Path(pdf_path)
    pages = cached_pages(pdf_path, text_cache)
    if len(pages) > MAX_PAGES:
        raise ValueError(f"{pdf_path.name}: {len(pages)} pages, over the {MAX_PAGES}-page cap")
    img = image_only_pages(pages)
    lines, page_of = P._lines_with_pages(pages)
    if len(img) == len(pages):
        return ParsedMinutes(source, len(pages), "none", img, None, [], [], [], {}, page_of)
    spans = P.embedded_spans(lines)
    att = P.parse_attendance(pages)
    titles = P.item_titles(pages)
    label = source.get("label") or source["sha256"][:12]
    rcs = P.find_rollcalls(pages, label, att, titles)
    if use_ocr:
        from .ocr import reverify
        failing = [rc for rc in rcs if rc.status != "Verified"]
        jobs = sorted({(str(pdf_path), p, source["sha256"]) for rc in failing for p in range(rc.page, rc.end_page + 1)})
        ocr_pages_parallel(jobs)
        rcs = [reverify(rc, pdf_path, source["sha256"], att) if rc.status != "Verified" else rc for rc in rcs]
    cls = sorted(consent_lists(lines, page_of, spans) + inline_consent_lists(lines, page_of, rcs, titles),
                 key=lambda c: c.line)
    return ParsedMinutes(source, len(pages), "text", img, att, rcs, cls,
                         agenda_entries(lines, page_of, spans), titles, page_of)
