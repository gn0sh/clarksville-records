"""parse_minutes(pdf_path, source) -> ParsedDocument: the M0 parser plus what M1 needs around it.

A document can hold the minutes of more than one meeting: its own meeting's minutes, the previous meeting's minutes
attached for approval, or (an agenda packet) only an earlier meeting's minutes "submitted for approval" plus the
next meeting's agenda and resolution texts. collector.parse.minutes_segments splits the document into meetings by
their own header text; each becomes one ParsedMinutes with its own date, kind, attendance and roll calls. Pages
outside every meeting's minutes (a packet's agenda) are never read as votes or listings.

Raw fragments only (names as written, no official ids, no verification status beyond the parser's P2 readings):
- per meeting: attendance header and roll calls (collector.parse, the M0 spike code);
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
MAX_PAGES = 1000          # the Aug 2024 minutes run to 621 pages
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
    """One meeting's minutes inside a document."""
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
    segment: P.Segment | None = None

    @property
    def meeting_date(self) -> str | None:
        return self.segment.date if self.segment else (self.attendance.date if self.attendance else None)

    @property
    def kind(self) -> str:
        return self.segment.kind if self.segment else "formal"


@dataclass
class ParsedDocument:
    source: dict
    pages: int
    text_layer: str
    image_only_pages: list
    meetings: list                 # [ParsedMinutes], in document order
    tables_outside_minutes: list   # pages of vote-table headings outside every meeting's minutes (not read)
    page_of_line: list
    zoning: list = field(default_factory=list)   # [collector.zoning.Reading] of every page, both engines


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


GLYPH_RUN = re.compile(r"[\dIl|O](?:[\dIl|O~_—–\s-]*[\dIl|O])?")


def agenda_numbers_in(text: str, titles: dict) -> list:
    """Agenda numbers in OCR-garbled text, in order of appearance ("2 l-2-5j" -> 21-2-5 when 21-2-5 is on the agenda).

    Written rule (items/consent-ocr-number): a run of digits, dashes, spaces and the glyphs l, I, |, O is read with
    the spaces dropped, l/I/| as 1 and O as 0; it gives a number only when that reading contains a number on this
    meeting's agenda with no digit or dash touching it. Anything else gives no number: a number that is not on the
    agenda is never guessed."""
    out = []
    agenda = [n for n in (titles or {}) if re.fullmatch(r"\d{1,2}-\d{1,2}-\d{1,3}", n)]
    for m in GLYPH_RUN.finditer(text):
        c = re.sub(r"\s", "", m.group(0))
        c = re.sub(r"[~_—–]", "-", c.replace("l", "1").replace("I", "1").replace("|", "1").replace("O", "0"))
        hits = []
        for n in agenda:
            for k in [i for i in range(len(c)) if c.startswith(n, i)]:
                before, after = c[k - 1:k], c[k + len(n):k + len(n) + 1]
                if not re.match(r"[\d-]", before) and not re.match(r"[\d-]", after):
                    hits.append((k, n))
        out += [n for _, n in sorted(hits)]
    return out


def list_numbers(line: str, titles: dict | None = None) -> list:
    """One line of a comma-separated list of item numbers -> per comma token, its normalised numbers ([] for a
    token that gives none).

    Written rule: in such a list the commas delimit the numbers, so a space inside a token is OCR noise
    ("20-10-1 1", "20-1 0-10" are 20-10-11 and 20-10-10), and so is l, I or | read for the digit 1 inside it. A
    leading "Resolution(s)" word is dropped. A token that still matches no number pattern is read by
    agenda_numbers_in (only numbers on this meeting's agenda, e.g. "2 l-2-5j 21-2-6" -> 21-2-5, 21-2-6)."""
    x = re.sub(r"^\s*Resolutions?\s+", "", line.strip(), flags=re.I).rstrip(",")
    out = []
    for t in re.split(r"\s*,\s*", x):
        j = re.sub(r"\s+", "", t)
        if re.fullmatch(r"\d{2}-[\dIl|O]{1,2}-[\dIl|O]{1,3}", j):
            j = j.replace("|", "1")
        n = P.norm_item(j) if P.ITEM_RE.fullmatch(j) else None
        out.append([n] if P.valid_number(n) else agenda_numbers_in(t, titles or {}))
    return out


def number_line(line: str, titles: dict | None = None) -> list | None:
    """The numbers of a comma-separated number line, or None when the line is not one (a title such as "Clerk's
    Report"). A line is a number line when most of its comma tokens give a number; a token that gives none is
    skipped, never guessed."""
    toks = list_numbers(line, titles)
    good = sum(bool(t) for t in toks)
    if not toks or good * 2 < len(toks) or good == 0:
        return None
    return [n for t in toks for n in t]


def inline_consent_lists(lines: list[str], page_of: list[int], rcs, titles: dict) -> list[ConsentList]:
    """2021-2022 layout: a "Consent Agenda" line, then the item numbers separated by commas and one line per other
    item, then "On Motion ... the foregoing Consent Agenda items were Adopted ..." and the table."""
    out = []
    for rc in rcs:
        if rc.kind != "consent":
            continue
        head = next((j for j in range(rc.line - 1, max(rc.line - 30, -1), -1)
                     if re.fullmatch(r"Consent\W{0,3}Agenda[\s:.\-—–]*(?:\s{3,}[Il|1])?", lines[j].strip(), re.I)),
                    None)                       # ("Consent Agenda      I": a stray mark at the right margin)
        if head is None:
            continue
        cl = ConsentList(page_of[head], _line_order(page_of, head), head, " ".join(lines[head].split()))
        for j in range(head + 1, rc.line):
            x = lines[j].strip()
            if re.search(r"\bMotion\b", x):
                break
            if not x or re.fullmatch(r"[-—–_~•.]+", x):
                continue
            if PULLED.search(x):                # "Resolution 2 1-2-6 was pulled from the Consent Agenda ..."
                sent = " ".join(lines[j:min(j + 3, rc.line)])
                sent = sent[:sent.find(".", PULLED.search(sent).end()) + 1 or None]
                found = [P.norm_item(r) for r in P.ITEM_RE.findall(sent)] + agenda_numbers_in(sent, titles)
                cl.pulled += [n for n in dict.fromkeys(found) if P.valid_number(n) and n not in cl.pulled]
                continue
            nums = number_line(x, titles)
            if nums:
                for n in nums:
                    cl.entries.append(Entry(n, n, titles.get(n) or n, n, page_of[j], _line_order(page_of, j)))
            else:
                cl.entries.append(Entry(None, None, x, x, page_of[j], _line_order(page_of, j)))
        if cl.entries:
            out.append(cl)
    return out


def agenda_entries(lines: list[str], page_of: list[int], spans, max_page: int = 6, start: int = 0) -> list[Entry]:
    """Numbered items on the agenda printed at the front of the minutes (not attached earlier minutes)."""
    out = []
    i = start
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


def pair_consent(cls: list, rcs: list) -> dict:
    """{index in rcs of a consent roll call: its ConsentList}. A list pairs with the next consent roll call after
    it, unless another list sits between them."""
    out = {}
    consent = [(k, rc) for k, rc in enumerate(rcs) if rc.kind == "consent"]
    for cl in cls:
        nxt = next(((k, rc) for k, rc in consent if rc.line > cl.line), None)
        if nxt is None or any(cl.line < c.line < nxt[1].line for c in cls):
            continue
        out.setdefault(nxt[0], cl)
    return out


def consent_numbers(cl) -> frozenset:
    """The item numbers a consent list covers, minus those pulled for separate votes."""
    return frozenset(e.number for e in (cl.entries if cl else []) if e.number and e.number not in cl.pulled)


def heading_before(lines: list[str], i: int, lo: int) -> str | None:
    """The nearest resolution heading (an item number alone on its line) above line i, not above line lo."""
    for j in range(i - 1, max(lo, 0) - 1, -1):
        t = lines[j].strip().rstrip("*")
        if t and P.ITEM_RE.fullmatch(t):
            n = P.norm_item(t)
            if P.valid_number(n):
                return n
    return None


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


def _attendance(lines: list[str], page_of: list[int], sg: P.Segment) -> P.Attendance:
    """The segment's own header, read from its header line to the end of that page (and the next page when the
    PRESENT line is not on it)."""
    pno = page_of[sg.start]
    j = sg.start
    while j < len(lines) and page_of[j] == pno:
        j += 1
    text = "\n".join(lines[sg.start:j])
    if not re.search(r"^\s*PRESENT\s*:", text, re.M):
        k = j
        while k < len(lines) and page_of[k] == pno + 1:
            k += 1
        text = "\n".join(lines[sg.start:k])
    return P.attendance_from_text(text, pno)


def _other_spans(owner: list, index: int) -> list[tuple[int, int]]:
    """Line ranges NOT owned by segment `index` (owner[i] = innermost segment of line i, or None)."""
    spans, a = [], None
    for i, o in enumerate(owner + [index]):
        if o != index and a is None:
            a = i
        elif o == index and a is not None:
            spans.append((a, i))
            a = None
    return spans


def name_spellings(att: P.Attendance | None, officials: list[dict]) -> dict:
    """{header name: [names.yml name and aliases of the official it resolves to exactly]} (names rules 1-2 only). Lets
    a vote-table cell spelled like the official's curated name pair with an OCR-garbled header spelling."""
    from .names import Resolver
    if att is None:
        return {}
    r = Resolver(officials)
    by_id = {o["id"]: o for o in officials}
    out = {}
    for nm in att.present + att.absent:
        oid = r.exact_match(nm)
        if oid:
            out[nm] = [by_id[oid]["name"]] + [a["alias"] for a in by_id[oid]["aliases"]]
    return out


def parse_minutes(pdf_path: Path, source: dict, use_ocr: bool = True, text_cache: Path = TEXT_CACHE,
                  officials: list[dict] | None = None) -> ParsedDocument:
    pdf_path = Path(pdf_path)
    pages = cached_pages(pdf_path, text_cache)
    if len(pages) > MAX_PAGES:
        raise ValueError(f"{pdf_path.name}: {len(pages)} pages, over the {MAX_PAGES}-page cap")
    img = image_only_pages(pages)
    lines, page_of = P._lines_with_pages(pages)
    if len(img) == len(pages):
        return ParsedDocument(source, len(pages), "none", img, [], [], page_of)
    segs = P.minutes_segments(lines, page_of)
    owner: list = [None] * len(lines)
    for sg in sorted(segs, key=lambda x: x.start):          # inner (later) segments overwrite outer ones
        for i in range(sg.start, sg.end):
            owner[i] = sg.index
    atts, titles = {}, {}
    if officials is None:
        from .names import NAMES, load_roster
        officials = load_roster(NAMES)
    for sg in segs:
        atts[sg.index] = _attendance(lines, page_of, sg)
        atts[sg.index].spellings = name_spellings(atts[sg.index], officials)
        # the document's own minutes read titles from the agenda at the front of the document, as in M0
        titles[sg.index] = (P.item_titles(pages) if sg.role == "own" and sg.page <= 3 else
                            P.item_titles(pages[sg.page - 1:sg.page + 5]))
    label = source.get("label") or source["sha256"][:12]
    rcs = P.find_rollcalls(pages, label, None, None,
                           segments=[(sg, atts[sg.index], titles[sg.index]) for sg in segs])
    if use_ocr:
        from .ocr import reverify
        failing = [rc for rc in rcs if rc.status != "Verified"]
        jobs = sorted({(str(pdf_path), p, source["sha256"]) for rc in failing for p in range(rc.page, rc.end_page + 1)})
        ocr_pages_parallel(jobs)
        rcs = [reverify(rc, pdf_path, source["sha256"], atts[rc.segment]) if rc.status != "Verified" else rc
               for rc in rcs]
    zoning = zoning_readings(pdf_path, source, pages, use_ocr)
    outside = sorted({page_of[h] for h in P.table_heads(lines) if owner[h] is None})
    meetings = []
    for sg in segs:
        spans = _other_spans(owner, sg.index)
        mine = [rc for rc in rcs if rc.segment == sg.index]
        cls = sorted(consent_lists(lines, page_of, spans) + inline_consent_lists(lines, page_of, mine, titles[sg.index]),
                     key=lambda c: c.line)
        # 2020-2022 layout: the consent vote is reprinted after each consent resolution; note which resolution each
        # printing follows (its heading, between the previous vote table and the reprinted consent list)
        prev_end = sg.start
        pairs = pair_consent(cls, mine)
        for k, rc in enumerate(mine):
            cl = pairs.get(k)
            if rc.kind == "consent" and cl is not None:
                rc.follows_item = heading_before(lines, cl.line, max(prev_end, cl.line - 120))
            prev_end = rc.line + 1
        # agenda listings only from a document's own minutes (a packet's agenda is another meeting's)
        agenda = (agenda_entries(lines, page_of, spans, max_page=sg.page + 5,
                                 start=0 if sg.page == 1 else sg.start + 1) if sg.role == "own" else [])
        meetings.append(ParsedMinutes(source, len(pages), "text", img, atts[sg.index], mine, cls, agenda,
                                      titles[sg.index], page_of, sg))
    return ParsedDocument(source, len(pages), "text", img, meetings, outside, page_of, zoning)


def zoning_readings(pdf_path: Path, source: dict, pages: list[str], use_ocr: bool) -> list:
    """Zoning case readings (collector.zoning) from the text layer and, with OCR on, tesseract's reading of the same
    pages. A tesseract reading counts only for a case the text layer places on that page, so a misread case number
    never moves a reading to another case."""
    from . import zoning as Z
    rules = Z.load_rules()
    if rules is None:
        return []
    text = Z.page_readings(pages, rules)
    if not use_ocr or not text:
        return text
    from .ocr import cache_path
    on_page = {(r.page, r.case) for r in text}
    want = sorted({r.page for r in text})
    errors = ocr_pages_parallel([(str(pdf_path), p, source["sha256"]) for p in want])
    ocr = [""] * len(pages)
    for p in want:
        c = cache_path(source["sha256"], p)
        if not errors.get((source["sha256"], p)) and c.exists():
            ocr[p - 1] = c.read_text()
    tess = [r for r in Z.page_readings(ocr, rules, engine="tesseract", only=set(want)) if (r.page, r.case) in on_page]
    return text + tess
