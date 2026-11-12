"""Deterministic parser for Montgomery County Commission minutes (text layer).

Input: list of page texts (pdftotext -layout). Output: meeting attendance and roll calls,
each roll call checked per spec P2 and marked Verified or Unverified with reasons.
No LLM calls; all rules are written down here so they apply identically to every official (G2).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from difflib import SequenceMatcher
from .config import OUTCOME_COMMA_PHRASES

# ---------------------------------------------------------------- names

MONTHS = ("january february march april may june july august september october "
          "november december").split()

NAME_MATCH_MIN = 0.78      # similarity needed to map an OCR name to a roster name
NAME_MATCH_MARGIN = 0.08   # best match must beat the runner-up by this much
FULL_BODY = 21             # seats on the Montgomery County Commission


def _letters(s: str) -> str:
    s = s.replace("0", "o")                     # "Jason 0. Knight"
    return re.sub(r"[^a-z]", "", s.lower())


def name_keys(name: str) -> tuple[str, str]:
    """(with initials, without single-letter initials), letters only, lowercase."""
    toks = re.findall(r"[A-Za-z0-9~'’]+\.?", name)
    full = _letters(name)
    short = _letters(" ".join(t for t in toks if len(_letters(t)) > 1))
    return full, short


def _first_last(name: str) -> tuple[str, str] | None:
    toks = [_letters(t) for t in re.split(r"[\s.]+", name) if len(_letters(t)) > 1]
    return (toks[0], toks[-1]) if len(toks) >= 2 else None


def name_similarity(a: str, b: str) -> float:
    """Whole-string similarity; for two-part names, the lower of that and the mean of first-name
    and surname similarity (so 'Jerry Allbert' and 'Randy Allbert' stay apart)."""
    af, as_ = name_keys(a)
    bf, bs = name_keys(b)
    whole = max(SequenceMatcher(None, x, y).ratio() for x in (af, as_) for y in (bf, bs) if x and y)
    fa, fb = _first_last(a), _first_last(b)
    if fa and fb:
        split = (SequenceMatcher(None, fa[0], fb[0]).ratio() + SequenceMatcher(None, fa[1], fb[1]).ratio()) / 2
        return min(whole, split)
    return whole


def match_name(ocr: str, roster: list[str]) -> tuple[str | None, float]:
    """Map an OCR'd name to one roster entry, or None if not confident (written rule G2)."""
    scored = sorted(((name_similarity(ocr, r), r) for r in roster), reverse=True)
    if not scored:
        return None, 0.0
    best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if best[0] >= NAME_MATCH_MIN and best[0] - second >= NAME_MATCH_MARGIN:
        return best[1], best[0]
    return None, best[0]


def surname(name: str) -> str:
    toks = [t for t in re.findall(r"[A-Za-z'’]+", name) if len(t) > 1]
    return toks[-1].lower() if toks else ""


def split_name_list(s: str) -> list[str]:
    s = re.sub(r"\(\s*\w{1,2}\s*\)", "", s)          # "(2)", OCR "(I)"
    parts = re.split(r",|\band\b|&", s)
    return [p.strip(" .;:") for p in parts if _letters(p)]


# ---------------------------------------------------------------- attendance header

@dataclass
class Attendance:
    date: str | None
    page: int
    present: list[str]
    absent: list[str]
    present_count: int | None
    absent_count: int | None
    vacant: list[str]
    verified: bool
    reasons: list[str]
    # header name -> other spellings of the same official (names.yml name and aliases), filled in by the caller when
    # the header name resolves exactly (collector.minutes); used only to pair vote-table cells with header names
    spellings: dict = field(default_factory=dict)


DATE_RE = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})\s*[,.]?\s*(\d{4})", re.I)


def _int(s: str, tally: bool = False) -> int | None:
    s = s.strip()
    # glyph rule (written): the text layer's look-alikes of 0 and 1. "U" for 0 was hand-checked on the page images
    # of stated tally counts only (Noes "—U" printed "– 0": March 2024 p56, May 2025 p44, November 2025 p47), so it
    # is mapped only there (tally=True), never in attendance counts, an ABSENT count or a date's day
    # (parse-accuracy/glyph-scope); "S" is not mapped: it stands for 5 (June 2022 p133) and for 8 (November 2024
    # p41), so it stays garbled
    glyphs = (("O", "0"), ("o", "0"), ("Q", "0"), ("D", "0"), ("I", "1"), ("l", "1")) + ((("U", "0"),) if tally else ())
    for a_, b_ in glyphs:
        s = s.replace(a_, b_)
    return int(s) if s.isdigit() else None


def parse_attendance(pages: list[str]) -> Attendance | None:
    """The meeting's own header: the first 'BE IT REMEMBERED' page (page 1 in all samples)."""
    for pno, text in enumerate(pages[:3], 1):
        if not re.search(r"BE\s+IT\s+REMEMBERED", text, re.I):
            continue
        return attendance_from_text(text, pno)
    return None


def name_cells(rows: list[str]) -> list[list[str]]:
    """Split the header's name table into cells.

    Written layout rule: cells are separated by two or more spaces. Where the text layer closed a column gap to one
    space ("Nathan Burkholder Jason Knight"), the row is also cut at a column start: an offset (within one character)
    where a cell starts in at least two other rows of the same table, when a word starts there after a single space."""
    starts: list[list[int]] = []
    for r in rows:
        starts.append([m.start() for m in re.finditer(r"(?:(?<=\s\s)|^)\S", r)])
    out = []
    for k, r in enumerate(rows):
        others = [c for j, cs in enumerate(starts) if j != k for c in cs]
        cols = sorted({c for c in others if sum(abs(c - o) <= 1 for o in others) >= 2})
        cuts = set()
        for c in cols:
            for w in (c, c - 1, c + 1):
                if 0 < w < len(r) and r[w] != " " and r[w - 1] == " " and (w < 2 or r[w - 2] != " "):
                    cuts.add(w)
                    break
        pieces, a = [], 0
        for w in sorted(cuts):
            pieces.append(r[a:w])
            a = w
        pieces.append(r[a:])
        out.append([c for piece in pieces for c in re.split(r"\s{2,}", piece.strip()) if c.strip()])
    return out


COMMISSIONERS_LINE = re.compile(r"\w*ssion\S{0,3}rs\s*:\s*$|following\s+Comm\S*\s*:\s*$", re.I)


def attendance_from_text(text: str, pno: int) -> Attendance:
    """Read one 'BE IT REMEMBERED' attendance header from text that starts at (or before) it."""
    reasons: list[str] = []
    k = text.upper().find("REMEMBERED")
    m = DATE_RE.search(text[k if k >= 0 else 0:])
    date = None
    if m:
        date = f"{m.group(3)}-{MONTHS.index(m.group(1).lower()) + 1:02d}-{int(m.group(2)):02d}"
    lines = text.splitlines()
    # "and the following Commissioners:" ends the preamble; OCR garbles letters ("Commissionçrs:")
    start = next((i for i, l in enumerate(lines) if COMMISSIONERS_LINE.search(l)), None)
    pidx = next((i for i, l in enumerate(lines) if re.match(r"\s*PRESENT\s*:", l)), None)
    if start is None or pidx is None:
        return Attendance(date, pno, [], [], None, None, [], False, ["header layout not recognised"])
    present = []
    for l in name_cells(lines[start + 1:pidx]):
        for cell in l:
            cell = cell.strip().rstrip("*").rstrip("1").strip()   # "* Present via Webex" marker, "Smith1"
            if len(_letters(cell)) >= 4 and not re.match(r"\*", cell):
                present.append(cell)
    pm = re.match(r"\s*PRESENT\s*:\s*(\S+)", lines[pidx])
    present_count = _int(pm.group(1)) if pm else None
    rest = "\n".join(lines[pidx + 1:])
    am = re.search(r"ABSENT\s*:\s*(.*?)(?:\n\s*\n|VACANT|When and where)", rest, re.S)
    absent, absent_count = [], None
    if am:
        raw = " ".join(am.group(1).split())
        cm = re.search(r"\((\s*\w+\s*)\)", raw)
        absent_count = _int(cm.group(1)) if cm else None
        absent = [] if re.match(r"none", raw, re.I) else split_name_list(raw)
        if absent_count is None and not absent:
            absent_count = 0
    elif present_count == len(present) == FULL_BODY:
        absent_count = 0             # written rule: all 21 seats present and named, no ABSENT line printed (May 2025)
    else:
        reasons.append("ABSENT line not found")
    vacant = re.findall(r"VACANT\s*:\s*(.+)", rest)
    if present_count is None or present_count != len(present):
        reasons.append(f"PRESENT count {present_count} != {len(present)} names read")
    if absent_count is not None and absent_count != len(absent):
        reasons.append(f"ABSENT count {absent_count} != {len(absent)} names read")
    return Attendance(date, pno, present, absent, present_count, absent_count,
                      [v.strip() for v in vacant], not reasons, reasons)


def embedded_spans(lines: list[str]) -> list[tuple[int, int]]:
    """Line spans of earlier meetings' minutes attached for approval (not this meeting)."""
    spans = []
    heads = [i for i, l in enumerate(lines) if re.search(r"BE\s+IT\s+REMEMBERED", l, re.I)]
    for h in heads[1:]:
        # a duplicate of this meeting's own header (Aug 2021 page 2) is followed by the agenda, not by
        # "Board was adjourned" within 400 lines, so its span ends at once
        end = next((j for j in range(h, min(len(lines), h + 400))
                    if re.search(r"Board was adjourned", lines[j], re.I)), None)
        spans.append((h, end if end is not None else h + 1))
    return spans


# ---------------------------------------------------------------- meetings inside one document

# "BE IT REMEMBERED that the Board of Commissioners ..."; the OCR layer garbles the word ("REM1EI~4BEREDthat",
# "REIVIEIVIBERED that the Board of C6mmissioners"), so a garbled RE... word counts when "that the Board of C..."
# follows. "BE IT RESOLVED that the Board of Montgomery County Commissioners" (resolution texts) never counts.
HEADER_RE = re.compile(r"BE\s+IT\s+REMEMBERED|BE\s+IT\s+RE(?!SOLV)\S*?\s*that\s+the\s+Board(?:\s+of\s+C|\s+of\s*$|\s*$)",
                       re.I)
WEEKDAYS = "monday tuesday wednesday thursday friday saturday sunday".split()
LOOSE_DATE_RE = re.compile(r"(?:\b(" + "|".join(WEEKDAYS) + r")\s*,?\s+)?\b(" + "|".join(MONTHS) +
                           r")\s+([\dIilO|]{1,2})\s*[,.]?\s*(\d{4})", re.I)
ADJOURN_RE = re.compile(r"Board\s+was\s+adjourn", re.I)
SESSION_RE = re.compile(r"met\s+in\s+(?:an?\s+)?([A-Za-z]+)(?:\s+called)?\s+session", re.I)
SUBMITTED_RE = re.compile(r"FOR\s+APPROVAL", re.I)      # "SUBMITTED" is often garbled ("SUBMIIYI'ED")
BANNER_RE = re.compile(r"MINUTES\s+FOR\s+(" + "|".join(MONTHS) + r")\s+(\d{1,2})\s*[,.]?\s*(\d{4})", re.I)
SESSION_KIND = {"regular": "formal", "special": "special", "adjourned": "formal"}


@dataclass
class Segment:
    """One meeting's minutes inside a document: from its 'BE IT REMEMBERED' header to 'The Board was adjourned'.

    Written rules (the same for every document):
    - The meeting date and kind come from the header text ("met in regular session, on Monday, December 9, 2024";
      "special session" -> special, otherwise formal), or from the "MINUTES FOR <date>" banner above it. Never from
      the index link label.
    - Headers and adjournment lines pair like brackets: minutes attached inside another meeting's minutes (the
      previous meeting's minutes, approved on the consent agenda) close before the outer minutes do.
    - A second header with the same date and session as the open one is a duplicate of it (Aug 2021 page 2).
    - A header that never closes is marked closed=False; its roll calls are held back (boundaries uncertain).
    - Lines outside every segment (an agenda packet's agenda and resolution texts) belong to no meeting and are
      never read as votes.
    role: "own" (top level, the document's record of the meeting), "for_approval" (top level under a "SUBMITTED FOR
    APPROVAL" banner, e.g. last month's minutes in an agenda packet), "attached" (nested in another meeting's minutes).
    """
    index: int
    start: int                 # line of the header
    end: int                   # line after the adjournment line (exclusive); len(lines) if not closed
    page: int
    end_page: int
    date: str | None
    session: str | None
    kind: str
    role: str
    parent: int | None
    closed: bool
    date_from: str             # header | banner | none
    date_how: str = ""         # how the date was read (header_date)
    certain: bool = True       # False when it or a meeting it sits in never closed

    def contains(self, i: int) -> bool:
        return self.start <= i < self.end


def _date_iso(m) -> str:
    return f"{m.group(3)}-{MONTHS.index(m.group(1).lower()) + 1:02d}-{int(m.group(2)):02d}"


def header_date(text: str) -> tuple[str | None, str]:
    """Meeting date in a header sentence ("on Monday, December Ii, 2023") -> (ISO date or None, how).

    Written rule: digits read as such are taken as printed. A day the OCR layer garbled (I, i, l, O, |) is mapped to
    digits only when the header also names the weekday and that weekday matches the mapped date; otherwise no date."""
    import datetime as _dt
    for m in LOOSE_DATE_RE.finditer(text):
        wd, mon, day_raw, year = m.groups()
        day = _int(day_raw.replace("i", "1").replace("|", "1"))
        if day is None or not 1 <= day <= 31:
            continue
        try:
            d = _dt.date(int(year), MONTHS.index(mon.lower()) + 1, day)
        except ValueError:
            continue
        weekday_ok = wd is not None and WEEKDAYS[d.weekday()] == wd.lower()
        if day_raw.isdigit():
            if wd is not None and not weekday_ok:
                return None, f"weekday {wd} does not match {d.isoformat()}"
            return d.isoformat(), "digits" + (", weekday matches" if weekday_ok else "")
        if weekday_ok:
            return d.isoformat(), f"day {day_raw!r} read as {day} (weekday matches)"
        return None, f"day {day_raw!r} unreadable and no matching weekday"
    return None, "no date"


def minutes_segments(lines: list[str], page_of: list[int]) -> list[Segment]:
    events = []
    for i, l in enumerate(lines):
        if HEADER_RE.search(l):
            events.append((i, "head"))
        elif ADJOURN_RE.search(l):
            events.append((i, "end"))
    segs: list[Segment] = []
    stack: list[Segment] = []
    for i, what in events:
        if what == "head":
            window = " ".join(" ".join(lines[i:i + 8]).split())
            window = window[HEADER_RE.search(window).start():]
            sm = SESSION_RE.search(window[:400])
            if not sm and not re.search(r"BE\s+IT\s+REMEMBERED", lines[i], re.I):
                continue                               # a garbled match without "met in ... session": not a header
            above = " ".join(" ".join(lines[max(0, i - 14):i]).split())
            bm = None
            for bm in BANNER_RE.finditer(above):
                pass
            # the date in the header sentence, after "met in ... session"
            date, how = header_date(window[sm.end():sm.end() + 120] if sm else window[:300])
            date_from = "header" if date else "none"
            if date is None and bm and bm.group(2).isdigit():
                date, date_from = _date_iso(bm), "banner"
            session = sm.group(1).lower() if sm else None
            kind = SESSION_KIND.get(session or "", "formal")
            if stack and stack[-1].date == date and stack[-1].session == session:
                continue                               # duplicate of the open meeting's own header
            role = "attached" if stack else ("for_approval" if SUBMITTED_RE.search(above) else "own")
            sg = Segment(len(segs), i, len(lines), page_of[i], page_of[-1] if page_of else 1, date, session, kind,
                         role, stack[-1].index if stack else None, False, date_from, how)
            segs.append(sg)
            stack.append(sg)
        elif stack:
            sg = stack.pop()
            sg.end, sg.end_page, sg.closed = i + 1, page_of[i], True
    for sg in segs:
        # The document's own minutes (top level, header on its first pages) may run to the end of the document
        # when its adjournment line is not read. Any other header left open is uncertain, and so is every meeting
        # nested in an open one: the adjournment line that closed it may have been the outer meeting's.
        a = sg
        while a is not None:
            open_ok = a.role == "own" and a.parent is None and a.page <= 3 and a is segs_top_last(segs)
            if not a.closed and not (a is sg and open_ok):
                sg.certain = False
                break
            a = segs[a.parent] if a.parent is not None else None
    return segs


def segs_top_last(segs: list[Segment]) -> Segment | None:
    top = [s for s in segs if s.parent is None]
    return top[-1] if top else None


def innermost(segs: list[Segment], i: int) -> Segment | None:
    inside = [s for s in segs if s.contains(i)]
    return max(inside, key=lambda s: s.start) if inside else None


# ---------------------------------------------------------------- roll calls

VOTE_TOKENS = {"y": "Yes", "n": "No", "a": "Abstain"}
ABSENT_MARK = re.compile(r"^[-—–_]{2,}$")
DISTRICT_LIKE = re.compile(r"^([0-9Iil|!]{1,2}|is|IS|S|O)$")
EDGE_NOISE = ",.;:'‘’`~|[](){}!\"“”*•=«»"
# Glyph rule (written, applies to every cell): a token made only of one letter's look-alikes is that
# letter, e.g. "¥", "YY", "Y¥" (tesseract reads the scanned Y this way). Mixed letters stay unknown.
VOTE_GLYPHS = {"y": set("Yy¥"), "n": set("Nn"), "a": set("Aa")}
TABLE_HEAD = re.compile(r"District\s+Commissioner\s+Vote", re.I)
ABSENT_REASON = re.compile(r"ABSENT|absent name not on roster")   # a reading's ABSENT-line problems
# a count may be blank ("Yeses - 20 Noes -  Abstentions - 1": the clerk printed no number); read_table derives a
# single blank count from the roster, never a garbled one. Groups: (marks, count) for Yes, No, Abstain; the marks
# between a label and its count decide whether a missing count is printed blank (TALLY_BLANK) or garbled.
# The label "Abstentions" with its "s" misread ("Abitentions", "Abétentions", "Ab~tentions") is the same label: only
# the label is read this way, never a count.
TALLY = re.compile(r"Yes\w*([^\w\n]*)(\w{1,3})?\s*No\w*([^\w\n]*)(\w{1,3})?\s*(?:Abst|Ab\Stent)\w*([^\w\n]*)(\w{1,3})?",
                   re.I)
TALLY_BLANK = re.compile(r"[\s\-—–~]*")         # only spaces and dashes: no number printed
TALLY_MARKS = re.compile(r"[\s\-—–~.,:;'’]*")    # what may sit before a printed count; "|", "]", "!" may be a digit
ITEM_RE = re.compile(r"(?<![\w-])(\d{2}\s?[-~_—–]\s?[\dIlO]{1,2}\s?[-~_—–]\s?[\dIlO]{1,2}"   # 24-12-1
                     r"|[A-Z]{1,3}\s?-\s?[\dIlO]{1,3}\s?-\s?\d(?:\s?\d){3})(?![\w-])")      # AB-4-2024, CZ-l1-2022, AB-7-2 023
# outcome word: the one at most two lowercase words before "by the following roll call". Between them the minutes may
# also print one comma-enclosed phrase from config.OUTCOME_COMMA_PHRASES ("was Adopted, in its original state, by",
# "Adopted, as Amended, by"; a fixed list, so the match never crosses a clause) or, after
# Suspended, the items the rules were suspended for ("Suspended for Resolutions 25-4-9 and 25-4-10 by"). OCR variants
# of "the" and "roll call" ("by th~ following", "rail call", "roll catl") and a lost space ("was electedby the") are
# read as those words; "by the following two-thirds (2/3) vote" heads a roll call table too.
OUTCOME_RE = re.compile(r"((?i:Adopted|Approved|Failed|Defeated|Denied|Amended|Deferred|Withdrawn|Postponed"
                        r"|Tabled|Elected|Suspended))"
                        r"(?:\s*,\s+(?i:" + "|".join(r"\s+".join(map(re.escape, p.split()))
                                                     for p in OUTCOME_COMMA_PHRASES) + r")\s*,)?"
                        r"(?:\s+for\s+(?:Resolutions?\s+)?[\w-]+(?:\s*(?:,|and)\s*[\w-]+)*)?"
                        r"(?:\s+[^\sA-Z]\S*){0,2}\s*by\s+t\S{1,2}\s+f\S{4,8}\s+"
                        r"(?i:r\S{2,3}\s+c\S{2,3}|two-thirds\s*\(2/3\)\s+vote)", re.S)
MOTION_RE = re.compile(r"Motion(?:\s+to\s+([A-Za-z]+(?:\s+[A-Za-z]+)?))?\s+by\s+~?Commissioner\s+"
                       r"([A-Z][\w.'’ ]{1,30}?)\s*,\s*"
                       r"seconded\s+by\s+~?Commissioner\s+([A-Z][\w.'’ ]{1,30}?)\s*[,.;]", re.S)


def norm_item(s: str) -> str:
    s = re.sub(r"\s", "", s)
    s = re.sub(r"[~_—–]", "-", s)
    if re.match(r"\d{2}-", s):
        s = s.replace("I", "1").replace("l", "1").replace("O", "0")
        a, b, c = s.split("-")
        s = f"{int(a)}-{int(b)}-{int(c)}"
    elif re.fullmatch(r"[A-Z]{1,3}-[\dIlO]{1,3}-\d{4}", s):
        # a case number (CZ-11-2022): the same glyph rule for its number part ("CZ-l1-2022")
        a, b, c = s.split("-")
        s = f"{a}-{b.replace('I', '1').replace('l', '1').replace('O', '0')}-{c}"
    return s


@dataclass
class Cell:
    raw_name: str
    member: str | None
    score: float
    tokens: list[str] = field(default_factory=list)


@dataclass
class RollCall:
    source: str
    meeting_date: str | None
    page: int
    end_page: int
    line: int
    item: str | None
    item_title: str | None
    kind: str
    outcome_text: str | None
    motion: str | None
    mover: str | None
    seconder: str | None
    votes: dict
    tally: tuple | None
    absent: list
    status: str = "Unverified"
    reasons: list = field(default_factory=list)
    verified_by: str | None = None
    ordinal_on_page: int = 0
    context_reasons: list = field(default_factory=list)
    readings: list = field(default_factory=list)
    motion_text: str | None = None       # verbatim motion sentence, whitespace collapsed
    outcome_clause: str | None = None    # verbatim, e.g. "the foregoing Motion to Table was Approved by ..."
    raw_item: str | None = None          # item number as written, before normalisation
    raw_mover: str | None = None
    raw_seconder: str | None = None
    in_attached_minutes: bool = False
    segment: int | None = None           # index of the meeting (Segment) whose minutes hold this table
    motion_linked: bool = False          # the motion sentence leads straight into this vote's outcome clause
    follows_item: str | None = None      # consent tables: the resolution heading just before the consent list
    roster: list = field(default_factory=list)   # the meeting's header names the table was read against
    combined: "Reading | None" = None    # set by decide when the votes come from combine()
    # rc.tally as the minutes print it: a count printed blank is None (rc.tally holds the derived number, used only for
    # the checks; facts.stated_tally publishes this one). Set by decide.
    printed_tally: tuple | None = None
    two_thirds: bool = False             # the table is headed "by the following two-thirds (2/3) vote" (check_outcome)


def classify_token(tok: str) -> tuple[str, str]:
    """-> (kind, value): kind is vote|absent|skip|name|unknown."""
    core = tok.strip(EDGE_NOISE)
    if not core:
        return "skip", ""
    if ABSENT_MARK.match(core):
        return "absent", "---"
    if re.fullmatch(r"[-—–_]", core):
        return "absent", "-"          # weak mark: a collapsed "---" or a stray dash
    bare = core.strip("-_—–")
    if len(core) <= 3 and bare and len(core) - len(bare) <= 1:    # "Y-", "_Y": one stray stroke
        for v, glyphs in VOTE_GLYPHS.items():
            if set(bare) <= glyphs:
                return "vote", v
    if DISTRICT_LIKE.match(core):
        return "skip", core
    if len(_letters(core)) >= 4:
        return "name", tok
    return "unknown", core


def chunk_row(line: str) -> list[str]:
    out = []
    for c in re.split(r"\s{2,}", line.strip()):
        toks = c.split()
        if not toks:
            continue
        # split leading district numbers off a name chunk ("4 Rickey Ray")
        while len(toks) > 1 and classify_token(toks[0])[0] == "skip":
            out.append(toks.pop(0))
        # split trailing short tokens off a name chunk ("David Harper y", "Leverett YY")
        tail = []
        while len(toks) > 1 and len(toks[-1]) <= 3 and not re.fullmatch(r"[A-Z]\.", toks[-1]) \
                and classify_token(toks[-1])[0] != "name" \
                and not re.fullmatch(r"[A-Z][a-z]+", toks[-1]):        # "Ray", "Joe" are names
            tail.insert(0, toks.pop())
        out.append(" ".join(toks))
        out.extend(tail)
    return out


def parse_table_rows(rows: list[str], roster: list[str], spellings: dict | None = None) -> tuple[list[Cell], list[str]]:
    cells: list[Cell] = []
    problems: list[str] = []
    for row in rows:
        chunks = chunk_row(row)
        voted = named = False            # voted: the cell of the last name in this row already holds a vote mark
        for ci, ch in enumerate(chunks):
            kind, val = classify_token(ch)
            before_name = ci + 1 < len(chunks) and classify_token(chunks[ci + 1])[0] == "name"
            if before_name and (kind == "unknown" or (kind in ("vote", "absent") and ci == 0)):
                # district position (just before a name): "‘J", "]"; and a row's first chunk read as a vote mark
                # ("y)" for the district number 2) is never a vote of the previous row's last member
                continue
            if before_name and kind == "vote" and voted and ch != ch.strip(EDGE_NOISE):
                # mid-row district column (written rule): a vote letter with edge noise ("a)" for 9), just before a
                # name, after the previous name's own vote mark in this row, is that name's district number. A plain
                # letter there ("Y") still counts against the cell, so a printed second mark is never dropped
                continue
            if kind == "name":
                voted, named = False, True
            elif kind == "vote" and named:
                voted = True
            if kind in ("vote", "absent"):
                if not cells:
                    problems.append(f"vote token {ch!r} before any name")
                else:
                    cells[-1].tokens.append(val)
            elif kind == "skip":
                continue
            elif kind == "name":
                if re.fullmatch(r"vacan\w*", ch.lower().strip(EDGE_NOISE)):
                    cells.append(Cell(ch, "__vacant__", 1.0))
                    continue
                cells.append(Cell(ch, None, 0.0))
            else:
                if cells:
                    cells[-1].tokens.append(ch)       # unknown short token: counts against the cell
                else:
                    problems.append(f"stray token {ch!r}")
    assign_names(cells, roster, spellings)
    return cells, problems


ASSIGN_MIN = 0.75       # 'Jerry Allbert' vs 'Randy Allbert' scores 0.70: two people, never paired


def assign_names(cells: list[Cell], roster: list[str], spellings: dict | None = None) -> None:
    """Written merge rule (G2): the table lists each roster member once, so OCR'd table names are
    matched to roster names one-to-one, best pairs first. A pair below ASSIGN_MIN is not matched
    (the roll call then fails P2). A cell whose best roster name is already taken is not matched.
    A cell is matched only when its best roster name beats its second best by NAME_MATCH_MARGIN ("R. Allbert"
    scores the same against Randy and Jerry Allbert: not matched). Names already matched to another cell drop out
    of that comparison, so cells are matched in rounds, clearest first, until no cell can be matched.
    A header name that names.yml resolves exactly also counts as its official's names.yml name and aliases
    (`spellings`): a cell "John Gannon" pairs with the header's OCR spelling "JoIm Gaimon" through the curated alias,
    under the same threshold and margin."""
    todo = [c for c in cells if c.member is None]
    spellings = spellings or {}

    def similarity(raw: str, r: str) -> float:
        return max(name_similarity(raw, x) for x in [r] + list(spellings.get(r, ())))
    sim = {(i, r): similarity(c.raw_name, r) for i, c in enumerate(todo) for r in roster}
    used_cells, used_names = set(), set()
    changed = True
    while changed:
        changed = False
        free = [r for r in roster if r not in used_names]
        ranked = []
        for i in range(len(todo)):
            if i in used_cells:
                continue
            sc = sorted(((sim[(i, r)], r) for r in free), reverse=True)
            if not sc or sc[0][0] < ASSIGN_MIN:
                continue
            margin = sc[0][0] - sc[1][0] if len(sc) > 1 else 1.0
            if margin >= NAME_MATCH_MARGIN:
                ranked.append((sc[0][0], -i, sc[0][1]))
        if ranked:
            score, neg_i, r = max(ranked)
            todo[-neg_i].member, todo[-neg_i].score = r, score
            used_cells.add(-neg_i)
            used_names.add(r)
            changed = True
    holder = {c.member: c for c in todo if c.member}
    for c in todo:
        if not c.member:
            continue
        for r in roster:
            if r != c.member and similarity(c.raw_name, r) > c.score and holder.get(r) \
                    and holder[r].score < 0.9:
                c.member = None          # its closest roster name went to another weak match
                break
    for i, c in enumerate(todo):
        if i not in used_cells:
            c.score = max((similarity(c.raw_name, r) for r in roster), default=0.0)


def _outcome_class(word: str | None) -> str | None:
    if not word:
        return None
    w = word.lower()
    if w in ("adopted", "approved", "amended", "elected", "suspended"):
        return "pass"
    if w in ("failed", "defeated", "denied"):
        return "fail"
    return None


@dataclass
class Reading:
    """One reading of a vote table (from one text source)."""
    source: str                      # "text-layer" or "tesseract"
    votes: dict
    tally: tuple | None
    absent: list
    reasons: list
    raw_names: dict = field(default_factory=dict)    # member -> table cell text as read
    clean: dict = field(default_factory=dict)        # member -> True when its cell read cleanly (see cells_to_votes)
    # the counts as the minutes print them: equal to tally, except that a count printed blank (derived from the
    # roster for the checks only) is None here. None (the default) means no count is stated; it never falls back to
    # tally, which may hold a derived count (provenance invariant).
    printed: tuple | None = None


def _lines_with_pages(pages: list[str]) -> tuple[list[str], list[int]]:
    lines, page_of = [], []
    for pno, t in enumerate(pages, 1):
        for l in t.splitlines():
            lines.append(l)
            page_of.append(pno)
    return lines, page_of


def table_heads(lines: list[str]) -> list[int]:
    return [i for i, l in enumerate(lines) if TABLE_HEAD.search(l)]


def read_table(lines: list[str], h: int, nxt: int, roster: list[str], source: str,
               spellings: dict | None = None) -> tuple[Reading, int]:
    """Read the vote table whose header is lines[h]; nxt bounds the search. Returns the reading
    and the index of the last line used."""
    reasons: list[str] = []
    tally_i = next((j for j in range(h + 1, min(nxt, h + 16)) if TALLY.search(lines[j])), None)
    rows_end = tally_i if tally_i is not None else min(nxt, h + 10)
    rows = [l for l in lines[h + 1:rows_end] if l.strip() and not l.startswith("=====")]
    tally = None
    g = vals = None
    if tally_i is None:
        reasons.append("stated tally not found")
    else:
        gm = TALLY.search(lines[tally_i]).groups()
        marks, g = gm[0::2], gm[1::2]
        vals = tuple(_int(x, tally=True) if x is not None else None for x in g)
        # a count is garbled when it does not read as a number, or a mark that may be (part of) a digit stands in
        # front of it or in place of it; only a count with nothing but spaces and dashes before the next label is
        # printed blank (neutrality/derived-count-shown-as-stated)
        garbled = [(x is not None and v is None) or not (TALLY_MARKS if x is not None else TALLY_BLANK).fullmatch(mk)
                   for x, v, mk in zip(g, vals, marks)]
        g = tuple(x if not bad else f"{mk.strip()}{x or ''}" for x, mk, bad in zip(g, marks, garbled))
        if any(garbled) or sum(x is None for x in g) > 1:
            reasons.append(f"tally unreadable {g}")
            g = None
        elif None not in vals:
            tally = vals
    last = tally_i if tally_i is not None else rows_end
    absent: list[str] = []
    found_absent = False
    for j in range(last + 1, min(len(lines), nxt, last + 10)):
        if lines[j].startswith("=====") and j > last + 1 and found_absent:
            break
        m = re.search(r"ABSENT\s*:\s*(.*)", lines[j])
        if not m:
            continue
        found_absent = True
        last = j
        raw = m.group(1).strip()
        k = j + 1
        while (raw.endswith(",") or raw.endswith("and")) and k < len(lines):
            raw += " " + lines[k].strip()
            k += 1
        if re.match(r"none", raw, re.I):
            break
        cm = re.search(r"\((\s*\w+\s*)\)", raw)
        cnt = _int(cm.group(1)) if cm else None
        names = split_name_list(raw)
        for nm in names:
            mem, _ = match_name(nm, roster)
            if mem is None:
                reasons.append(f"absent name not on roster: {nm!r}")
            else:
                absent.append(mem)
        if cnt is not None and cnt != len(names):
            reasons.append(f"ABSENT count ({cnt}) != {len(names)} names listed")
        break
    if not found_absent:
        reasons.append("ABSENT line not found")
    printed = tally
    if tally is None and g is not None and sum(x is None for x in g) == 1:
        # Written rule: exactly one count printed blank. With every present member voting once (checked below), the
        # three counts sum to the roster minus the absent, so the blank one is that remainder. Derived only from a
        # read ABSENT line whose names all resolve; a garbled count is never derived.
        if found_absent and roster and not any(ABSENT_REASON.search(x) for x in reasons):
            rest = len(roster) - len(set(absent)) - sum(v for v in vals if v is not None)
            if rest >= 0:
                tally = tuple(rest if v is None else v for v in vals)
                printed = vals            # the blank count stays None: it is not stated (export: null)
        if tally is None:
            reasons.append(f"tally unreadable {g}")
    cells, problems = parse_table_rows(rows, roster, spellings)
    reasons.extend(problems)
    clean: dict[str, bool] = {}
    votes = cells_to_votes(cells, roster, reasons, clean)
    check_votes(votes, set(absent), tally, roster, reasons)
    raw_names = {c.member: c.raw_name for c in cells if c.member and c.member != "__vacant__"}
    return Reading(source, votes, tally, sorted(set(absent)), reasons, raw_names, clean, printed), last


def cells_to_votes(cells: list[Cell], roster: list[str], reasons: list[str], clean: dict | None = None) -> dict:
    """Cell tokens -> {member: Yes|No|Abstain|---|none|?}. `clean` (optional, filled in) marks a member whose one cell
    holds exactly one vote token, or only absent marks, or nothing, and no other token: a cell another reading may
    rely on (combine)."""
    votes: dict[str, str] = {}
    seen: dict[str, int] = {}
    clean = {} if clean is None else clean
    for c in cells:
        if c.member is None:
            reasons.append(f"name not matched to roster: {c.raw_name!r} ({c.score:.2f})")
            continue
        if c.member == "__vacant__":
            continue
        seen[c.member] = seen.get(c.member, 0) + 1
        vt = [t for t in c.tokens if t in VOTE_TOKENS]
        weak = [t for t in c.tokens if t == "-"]
        marks = [t for t in c.tokens if t == "---"] or ([] if vt else weak)
        other = [t for t in c.tokens if t not in vt and t not in marks and t not in weak]
        if other:
            reasons.append(f"unrecognised token(s) {other} for {c.member}")
        if len(vt) > 1 or (vt and marks):
            reasons.append(f"conflicting vote marks {c.tokens} for {c.member}")
            votes[c.member] = "?"
        elif vt:
            votes[c.member] = VOTE_TOKENS[vt[0]]
        elif marks:
            votes[c.member] = "---"
        else:
            votes[c.member] = "none"
        clean[c.member] = not other and votes[c.member] != "?" and not (vt and weak)
    for m, n in seen.items():
        if n > 1:
            reasons.append(f"matched {n} times: {m}")
            clean[m] = False
    missing = [r for r in roster if r not in seen]
    if missing:
        reasons.append(f"roster members not found in table: {missing}")
    return votes


def printed_counts(r: "Reading") -> tuple | None:
    """r's counts as the minutes print them (None for a count printed blank); None when r read no tally."""
    return r.printed


def check_votes(votes: dict, absent: set, tally: tuple | None, roster: list[str], reasons: list[str]) -> None:
    """Spec P2: one vote per present member, none for absent members, tallies equal stated."""
    for m, v in votes.items():
        if m in absent and v not in ("none", "---"):
            reasons.append(f"listed absent but has vote {v}: {m}")
        if m not in absent and v in ("none", "---"):
            reasons.append(f"no vote read for present member: {m}")
    if tally:
        got = (sum(v == "Yes" for v in votes.values()), sum(v == "No" for v in votes.values()),
               sum(v == "Abstain" for v in votes.values()))
        if got != tally:
            reasons.append(f"counted {got} != stated {tally}")
        if roster and sum(tally) + len(absent) != len(roster):
            reasons.append(f"stated tally {sum(tally)} + absent {len(absent)} != roster {len(roster)}")


def check_outcome(outcome_word: str | None, tally: tuple | None, two_thirds: bool = False) -> list[str]:
    """The stated outcome against the stated tally. A table headed "by the following two-thirds (2/3) vote"
    (two_thirds) is tested against two-thirds, but the minutes never say two-thirds of what (the Rules of Procedure
    name "members present and voting" only for rescinding a vote), so it is tested against every base the rule could
    mean: the votes cast Yes or No, the members present (every one votes, checked by check_votes), and the full body.
    It passes only when every base gives the stated outcome; otherwise the roll call is held
    (parse-accuracy/two-thirds-majority)."""
    if not tally:
        return []
    oc = _outcome_class(outcome_word)
    if oc is None:
        return [f"outcome not stated or not recognised ({outcome_word})"]
    if two_thirds:
        bases = (tally[0] + tally[1], sum(tally), FULL_BODY)
        results = {3 * tally[0] >= 2 * b for b in bases}
        if len(results) > 1:
            return [f"two-thirds vote: the minutes do not say two-thirds of what, and the bases {bases} give "
                    f"different outcomes for tally {tally}"]
        passes = results.pop()
    else:
        passes = tally[0] > tally[1] and tally[0] >= FULL_BODY // 2 + 1
    if (oc == "pass") != passes:
        return [f"outcome {outcome_word} disagrees with tally {tally}" + (" (two-thirds)" if two_thirds else "")]
    return []


VOTES = ("Yes", "No", "Abstain")


def _cell(r: Reading, m: str) -> str | None:
    """r's reading of m's cell for the dissent rule: a vote, "---", "malformed" ("?": two vote marks or a vote with
    "---"; or a vote with an unrecognised token, or in a member's second cell), or None ("none": no cell, or read
    blank). A lone "-" beside a vote is a known weak mark, not malformed (cells_to_votes ignores it; combine still
    does not rely on that cell alone)."""
    v = r.votes.get(m)
    if v is None or v == "none":
        return None
    if v == "?" or (v in VOTES and any((x.startswith("unrecognised token") and x.endswith(f" for {m}")) or
                                       re.fullmatch(rf"matched \d+ times: {re.escape(m)}", x) for x in r.reasons)):
        return "malformed"
    return v


def cell_dissent(a: Reading, b: Reading, m: str) -> str | None:
    """Written rule (architecture, "Invariant: independent readings"): readings a and b dissent on member m's cell when
    either reads it malformed, or both read a value (a vote or an explicit "---") and the values differ. A cell not
    read, or read blank, is "none" and never dissent. The one cell rule used by combine, disagreements (so decide and
    the consent reprints) and verify.source_inconsistent. Returns the reason, or None."""
    ca, cb = _cell(a, m), _cell(b, m)
    if ca is None and cb is None:
        return None
    if "malformed" in (ca, cb):
        return f"sources disagree for {m}: {a.source}={a.votes.get(m)} {b.source}={b.votes.get(m)} (malformed cell)"
    if ca is not None and cb is not None and ca != cb:
        return f"sources disagree for {m}: {a.source}={ca} {b.source}={cb}"
    return None


def tally_malformed(r: Reading) -> bool:
    """The tally line was found but a count is garbled (read_table: "tally unreadable")."""
    return any(x.startswith("tally unreadable") for x in r.reasons)


def absent_malformed(r: Reading) -> bool:
    """The ABSENT line was found but has a problem (a name off the roster, a count that does not match the names).
    "ABSENT line not found" is "none", not malformed."""
    return any(ABSENT_REASON.search(x) and x != "ABSENT line not found" for x in r.reasons)


def absent_read(r: Reading) -> bool:
    return "ABSENT line not found" not in r.reasons and not absent_malformed(r)


def disagreements(a: Reading, b: Reading) -> list[str]:
    """Every dissent between two readings of one table: a cell (cell_dissent: a different vote, "---" against a vote,
    "?" or a malformed cell), a different stated tally or one read garbled, different ABSENT names or an ABSENT line
    with a problem. One dissent holds the roll call (decide), even when a reading passes P2 on its own."""
    out = [d for m in sorted(set(a.votes) | set(b.votes)) if (d := cell_dissent(a, b, m))]
    if a.tally and b.tally and a.tally != b.tally:
        out.append(f"sources disagree on stated tally: {a.tally} vs {b.tally}")
    elif tally_malformed(a) or tally_malformed(b):
        out.append(f"sources disagree on stated tally: {a.tally} vs {b.tally} (a count read garbled)")
    if absent_read(a) and absent_read(b) and sorted(a.absent) != sorted(b.absent):
        out.append(f"sources disagree on ABSENT names: {sorted(a.absent)} vs {sorted(b.absent)}")
    elif absent_malformed(a) or absent_malformed(b):
        out.append("sources disagree on the ABSENT line: a reading's ABSENT line has a problem")
    return out


def combine(readings: list[Reading], roster: list[str]) -> Reading | None:
    """Written rule (parse-accuracy/verified-rate): two or more readings of one table, none clean on its own, are
    read cell by cell. A member's vote is the Yes/No/Abstain that a reading read cleanly in that member's cell (one
    vote token and nothing else) when no other reading, clean or not, read a different vote, an explicit absent mark
    ("---") or conflicting marks ("?") there; a member with no vote read by any reading has no vote when some reading
    read the cell cleanly as blank or "---" and none read "?" there; anything else is unreadable. The stated tally is
    the one every reading that read a tally agrees on, and the ABSENT names the ones every reading that read its ABSENT line without a problem agrees
    on. The result is checked like any reading (check_votes: every present member exactly one vote, no absent member
    a vote, counted equals stated, stated plus absent equals the roster), and verifies only with no reason left.
    Each vote therefore rests on at least one clean reading of its own cell and no reading against it, and the
    stated tally checks the whole table. The cell rule is cell_dissent; a reading whose tally is garbled or whose ABSENT
    line has a problem is dissent and holds the combination (a reading that found no ABSENT line is "none").
    Returns None with fewer than two readings."""
    if len(readings) < 2:
        return None
    reasons: list[str] = []
    tallies = {r.tally for r in readings if r.tally}
    tally = next(iter(tallies)) if len(tallies) == 1 else None
    if tally is None:
        reasons.append("stated tally not read alike by any reading" if not tallies else
                       f"readings disagree on stated tally {sorted(tallies)}")
    if any(tally_malformed(r) for r in readings):
        reasons.append("a reading read the stated tally garbled")
    absents = {tuple(sorted(r.absent)) for r in readings if absent_read(r)}
    absent = list(next(iter(absents))) if len(absents) == 1 else []
    if len(absents) != 1:
        reasons.append("ABSENT line not read alike by any reading")
    if any(absent_malformed(r) for r in readings):
        reasons.append("a reading's ABSENT line has a problem")
    votes: dict[str, str] = {}
    raw: dict[str, str] = {}
    for m in roster:
        cells = [(r, r.votes[m]) for r in readings if m in r.votes]
        if not cells:
            reasons.append(f"roster members not found in table: {[m]}")
            continue
        clean = [(r, v) for r, v in cells if r.clean.get(m)]
        said = {v for _, v in clean if v in VOTES}
        # dissent counts from every reading, clean or not (cell_dissent): a "?" (two marks in one cell, typical of a
        # row read out of line), a vote with another token, a different vote, or a "---" against a vote
        said_any = {v for _, v in cells if v in VOTES}
        dissent = next((d for i, a in enumerate(readings) for b in readings[i + 1:] if (d := cell_dissent(a, b, m))),
                       None)
        if dissent or any(_cell(r, m) == "malformed" for r, _ in cells):
            r, v = cells[0][0], "?"
            reasons.append(f"a reading read conflicting marks for {m}" if any(x == "?" for _, x in cells) else
                           f"readings dissent for {m}: {dissent or 'a malformed cell'}")
        elif len(said) == 1:
            v = next(iter(said))
            r = next(r for r, x in clean if x == v)
        elif not said_any and clean:
            r, v = clean[0]
        else:
            r, v = cells[0][0], "?"
            reasons.append(f"no clean reading of the vote for {m}")
        votes[m] = v
        if m in r.raw_names:
            raw[m] = r.raw_names[m]
    check_votes(votes, set(absent), tally, roster, reasons)
    # a count is printed when some reading that read this tally read it printed (the others may have read it blank)
    printed = None
    if tally is not None:
        ps = [printed_counts(r) for r in readings if r.tally == tally]
        printed = tuple(tally[i] if any(p is not None and p[i] is not None for p in ps) else None for i in range(3))
        printed = printed if any(x is not None for x in printed) else None
    return Reading("+".join(r.source for r in readings), votes, tally, sorted(set(absent)), reasons, raw,
                   {m: True for m in votes}, printed)


def decide(rc: "RollCall") -> None:
    """Verified when the context checks pass, at least one reading passes P2 (or, when none does, their cell-by-cell
    combination passes it: combine), and no two readings dissent (disagreements: any cell, the tally or the ABSENT
    line), even when one reading passes P2 on its own. The passing reading supplies the votes."""
    good = [r for r in rc.readings if not r.reasons]
    conflicts = []
    for i in range(len(rc.readings)):
        for j in range(i + 1, len(rc.readings)):
            conflicts += disagreements(rc.readings[i], rc.readings[j])
    reasons = list(rc.context_reasons) + conflicts
    rc.combined = None
    if not good:
        comb = combine(rc.readings, rc.roster or sorted({m for r in rc.readings for m in r.votes}))
        if comb is not None and not comb.reasons:
            rc.combined = comb
            good = [comb]
    if good:
        best = good[0]
        reasons += check_outcome(rc.outcome_text, best.tally, rc.two_thirds)
    else:
        best = rc.readings[0]
        for r in rc.readings:
            reasons += [f"[{r.source}] {x}" for x in r.reasons]
    rc.votes, rc.tally, rc.absent = best.votes, best.tally, best.absent
    rc.printed_tally = printed_counts(best)
    rc.verified_by = best.source if good else None
    rc.reasons = reasons
    rc.status = "Verified" if good and not reasons else "Unverified"


def find_rollcalls(pages: list[str], source: str, att: Attendance | None,
                   titles: dict | None = None, segments: list | None = None) -> list[RollCall]:
    """Every vote table -> RollCall. With segments ([(Segment, Attendance|None, titles)], from minutes_segments), each
    table is read against the roster of the meeting whose minutes hold it, and a table outside every meeting's
    minutes (an agenda packet's agenda or resolution pages) is not a roll call at all. Without segments (M0 mode),
    one attendance header serves the whole document and attached earlier minutes are held back."""
    lines, page_of = _lines_with_pages(pages)
    spans = embedded_spans(lines) if segments is None else []
    segs = [s for s, _, _ in segments] if segments is not None else None
    roster0 = (att.present + att.absent) if att else []
    titles0 = titles or {}
    heads = table_heads(lines)
    out: list[RollCall] = []
    prev_end = 0
    for hi, h in enumerate(heads):
        nxt = heads[hi + 1] if hi + 1 < len(heads) else len(lines)
        seg_lo = 0
        if segs is None:
            seg, att_h, roster, titles = None, att, roster0, titles0
        else:
            seg = innermost(segs, h)
            if seg is None:
                continue                     # not inside any meeting's minutes: not a vote of any meeting
            _, att_h, titles = segments[seg.index]
            titles = titles or {}
            roster = (att_h.present + att_h.absent) if att_h else []
            seg_lo = seg.start
            nxt = min(nxt, seg.end) if seg.end > h else nxt
        reading, last = read_table(lines, h, nxt, roster, "text-layer", att_h.spellings if att_h else None)
        ctx_reasons: list[str] = []
        ctx_start = max(prev_end, h - 40, seg_lo)
        ctx = " ".join(" ".join(lines[ctx_start:h]).split())
        om = None
        for om in OUTCOME_RE.finditer(ctx):
            pass
        outcome_word = om.group(1) if om else None
        motions = list(MOTION_RE.finditer(ctx))
        mot = motions[-1] if motions else None
        linked = motion_linked(ctx, mot, om)
        motion_text, outcome_clause = motion_clauses(ctx, mot if linked else None, om)
        if mot is not None and not linked:
            motion_text = " ".join(mot.group(0).split())          # the motion as written, kept apart from this vote
        kind = "resolution"
        if re.search(r"foregoing\s+Amendment", ctx[-400:], re.I):
            kind = "amendment"
        elif re.search(r"Consent\W{0,3}Agenda\s+items", ctx[-400:], re.I):
            kind = "consent"
        elif re.search(r"Rules\s+were\s+Suspended|Suspend\s+the\s+Rules\s+\w+\s+by", ctx[-400:], re.I):
            kind = "suspend-rules"
        elif re.search(r"Motion\s+to\s+(Table|Postpone|Defer)\w*\s+(was|were)\s+\w+\s+by", ctx[-400:], re.I):
            kind = "procedural"
        elif re.search(r"Nominations[^.]{0,80}(Approved|Adopted)\s+by", ctx[-400:], re.I):
            kind = "nominations"
        elif re.search(r"Minutes[^.]{0,200}(Approved|Adopted)", ctx[-400:], re.I):
            kind = "minutes"
        item = raw_item = None
        if kind == "consent":
            item = "Consent Agenda"
        else:
            for j in range(h - 1, ctx_start - 1, -1):
                found = item_number_in(lines[j], titles)
                if found and item_link_ok(lines[j], found, titles):
                    raw_item, item = found
                    break
            # the vote on the resolution right after its amendment vote carries no number of its own
            if item is None and out and out[-1].kind == "amendment" and h - prev_end < 12 \
                    and out[-1].segment == (seg.index if seg else None):
                item = out[-1].item
        if not roster:
            ctx_reasons.append("no roster for this meeting")
        if att_h is None or not att_h.verified:
            ctx_reasons.append("meeting attendance header not verified")
        if any(a <= h < b for a, b in spans):
            ctx_reasons.append("inside an earlier meeting's attached minutes")
        if seg is not None and not seg.certain:
            ctx_reasons.append("meeting minutes boundaries uncertain (an adjournment line was not read)")
        mover = seconder = None
        if mot:
            mover = resolve_commissioner(mot.group(2), roster)
            seconder = resolve_commissioner(mot.group(3), roster)
        rc = RollCall(source=source, meeting_date=(seg.date if seg else (att.date if att else None)), page=page_of[h],
                      end_page=page_of[min(len(lines) - 1, last)], line=h,
                      item=item, item_title=titles.get(item) if item else None, kind=kind,
                      outcome_text=outcome_word,
                      motion=(mot.group(1) or "") if mot else None, mover=mover, seconder=seconder,
                      votes={}, tally=None, absent=[])
        rc.ordinal_on_page = sum(1 for x in heads[:hi] if page_of[x] == page_of[h])
        rc.motion_text, rc.outcome_clause, rc.raw_item = motion_text, outcome_clause, raw_item
        rc.motion_linked = linked
        rc.two_thirds = bool(om and re.search(r"two-thirds", om.group(0), re.I))
        rc.raw_mover = mot.group(2).strip() if mot else None
        rc.raw_seconder = mot.group(3).strip() if mot else None
        rc.in_attached_minutes = any(a <= h < b for a, b in spans)
        rc.segment = seg.index if seg else None
        rc.context_reasons = ctx_reasons
        rc.roster = list(roster)
        rc.readings = [reading]
        decide(rc)
        out.append(rc)
        prev_end = last + 1
    return out


NUMBER_PATTERNS = (re.compile(r"^\d{2}-\d{1,2}-\d{1,3}$"), re.compile(r"^[A-Z]{1,4}-\d{1,3}-\d{4}$"))


def valid_number(n: str | None) -> bool:
    return bool(n) and any(p.match(n) for p in NUMBER_PATTERNS)


def item_number_in(line: str, titles: dict | None = None) -> tuple[str, str] | None:
    """First item number on a line -> (raw, normalised), or None.

    Written rule for OCR splits ("20-3-1 1"): when the number is followed by one space and one digit, the joined
    form is used only if it is on this meeting's agenda list; if it is not, the number is ambiguous and the line
    gives no number (never guessed). A normalised number matching no known pattern is no number."""
    for m in ITEM_RE.finditer(line):
        raw = m.group(1)
        n = norm_item(raw)
        tail = re.match(r" (\d)(?![\w-])", line[m.end():])
        if tail:
            joined = n + tail.group(1)
            if titles and joined in titles:
                return raw + " " + tail.group(1), joined
            return None
        if valid_number(n):
            return raw, n
    return None


def motion_linked(ctx: str, mot, om) -> bool:
    """Written rule: a motion belongs to a roll call only when its sentence runs straight into that roll call's
    outcome clause ("On Motion ... by Commissioner A, seconded by Commissioner B, the foregoing Resolution was
    Adopted by the following roll call vote"): the motion comes before the outcome word, ends with a comma or
    semicolon (not a full stop), and no sentence ends and no voice vote sits between them. Anything else (the last
    motion in the window belonging to an earlier voice vote) is not this vote's motion."""
    if mot is None or om is None or mot.start() >= om.start():
        return False
    if mot.group(0).rstrip()[-1:] == ".":
        return False
    gap = ctx[mot.end():om.start()]
    return len(gap) <= 200 and not re.search(r"\.\s+[A-Z]|voice\s+vote", gap)


def item_link_ok(line: str, found: tuple[str, str], titles: dict) -> bool:
    """Written rule: a roll call links to an item number only when the number is on this meeting's agenda, or the
    line is the resolution's own heading (the number alone on its line, or the number then two spaces and a title,
    as the resolution and agenda pages print it). A number cited inside running text does not link."""
    raw, n = found
    if titles and n in titles:
        return True
    t = line.strip()
    return t == raw.strip() or bool(re.match(re.escape(raw.strip()) + r"\*?(?:\s{2,}\S|$)", t))


def motion_clauses(ctx: str, mot, om) -> tuple[str | None, str | None]:
    """Verbatim motion sentence and outcome clause just before a vote table (ctx is whitespace-collapsed)."""
    if om is None:
        return None, None
    end = len(ctx)
    start = None
    if mot is not None and mot.start() < om.start():
        start = mot.start()
        on = ctx.rfind("On ", max(0, start - 4), start + 1)
        if on != -1:
            start = on
    if start is None:
        start = max(ctx.rfind(". ", 0, om.start()) + 2, 0) if ". " in ctx[:om.start()] else 0
    motion_text = ctx[start:end].strip()
    outcome = None
    if mot is not None and mot.start() < om.start():
        rest = ctx[mot.end():end].strip()
        outcome = rest
    else:
        outcome = motion_text
    return motion_text or None, (outcome or None)


def resolve_commissioner(text: str, roster: list[str]) -> str | None:
    """'J. Smith' / 'Smith' -> roster entry, only when exactly one matches (else None)."""
    t = text.strip()
    toks = [x for x in re.findall(r"[A-Za-z'’]+", t)]
    if not toks:
        return None
    sur = toks[-1].lower()
    initial = toks[0][0].lower() if len(toks) > 1 else None
    cands = [r for r in roster if SequenceMatcher(None, surname(r), sur).ratio() >= 0.85]
    if initial:
        cands = [r for r in cands if r.strip()[0].lower() == initial]
    return cands[0] if len(cands) == 1 else None


# ---------------------------------------------------------------- titles

def item_titles(pages: list[str], max_pages: int = 6) -> dict:
    """Item number -> title as written in the agenda (first pages)."""
    titles: dict[str, str] = {}
    for text in pages[:max_pages]:
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            m = re.match(r"\s*(\S{5,12}?)\*?\s{2,}(\S.*)$", lines[i])
            if m and ITEM_RE.fullmatch(m.group(1).rstrip("*")):
                key = norm_item(m.group(1).rstrip("*"))
                parts = [m.group(2).strip()]
                j = i + 1
                while (j < len(lines) and re.match(r"\s{6,}\S", lines[j])
                       and not ITEM_RE.match(lines[j].strip().split(" ")[0].rstrip("*"))):
                    parts.append(lines[j].strip())
                    j += 1
                titles.setdefault(key, " ".join(" ".join(parts).split()).rstrip(" -—"))
                i = j
                continue
            i += 1
    return titles


CANON_MIN = 0.80


def canonical_officials(names: list[str]) -> dict:
    """Merge rule (G2) across meetings: header spellings with name_similarity >= CANON_MIN are one
    official; the most frequent spelling (with middle initial dropped) is the display name.
    Returns {spelling: display name}."""
    from collections import Counter
    counts = Counter(names)
    clusters: list[list[str]] = []
    for n, _ in counts.most_common():
        for cl in clusters:
            if name_similarity(n, cl[0]) >= CANON_MIN:
                cl.append(n)
                break
        else:
            clusters.append([n])
    out = {}
    for cl in clusters:
        rep = max(cl, key=lambda x: counts[x])
        fl = _first_last(rep)
        disp = " ".join(t for t in rep.split() if len(_letters(t)) > 1) if fl else rep
        for n in cl:
            out[n] = disp
    return out


def as_dict(rc: RollCall) -> dict:
    return asdict(rc)
