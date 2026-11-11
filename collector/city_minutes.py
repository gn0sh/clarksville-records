"""Read City Council minutes from their text layer (M4, slice 1): attendance, motions and roll-call votes by name.

The minutes print attendance as "PRESENT: Richard Garrett (Ward 1), ..., David Allen, Mayor Pro Tem (Ward 8), ..."
and each recorded vote as label lines ("AYE: Allen, Burkhart, ...", "NAY: Henley, Richmond") followed by an outcome
sentence ("The motion to adopt this ordinance on first reading passed."). Labels, item-number and outcome patterns
come from agenda-center.yml.

Rules (same as the county): values only from a born-digital text layer. A scan (no text, or text from a scanner or
OCR engine) is marked not read, and nothing is taken from it. Nothing is guessed: a vote name that does not match
exactly one member recorded present (or the presiding mayor) stays unresolved and holds its roll call back
(verification "unverified"), shown as printed. Consent-agenda votes are kept as one roll call on the consent motion,
linked to the Consent Agenda section and never to one of its items; abstentions on single consent items are noted in
prose by the minutes and are not expanded. A vote is linked to a numbered item only when its own words agree
(_item_for_vote): otherwise it goes to its section heading, and a contradiction also holds its roll call.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .agenda_center import AgendaCenterConfig
from .extract import extract_pages, image_only_pages

SCAN_MARKS = re.compile(r"scan|paper capture|konica|bizhub|ricoh|xerox|canon ir|sharp mx|kyocera|lexmark|"
                        r"\bocr\b|tesseract|abbyy|finereader|omnipage", re.I)
# "Councilperson" is the title printed from 2021 on
TITLES = (r"(?:Councilman|Councillady|Councilwoman|Councilperson|Councilmember|Council Member|Councilor|Mayor Pro Tem|"
          r"Mayor)")
MOTION_RE = re.compile(TITLES + r"\s+([A-Z][A-Za-z'’-]+)\s+made\s+a\s+motion")
NAMED_RE = re.compile(TITLES + r"\s+([A-Z][A-Za-z'’-]+)")
# A member speaking or moving: title, surname, then a verb ("Councilperson Allen made", "Mayor McMillan said",
# "Councilman Burkhart seconded"). Not "Councilman Jeff Burkhart, Chair" (a name, no verb).
SPEAKS = TITLES + r"\s+[A-Z][A-Za-z'’-]+\s+(?:made|said|felt|then|was|also|[a-z]+ed)\b"
BODY_IN_LINE_RE = re.compile(SPEAKS)
BODY_LINE_RE = re.compile(r"^(?:The|This|These|There|Because|In response)\b|^" + SPEAKS)
SECOND_RE = re.compile(r"seconded\s+by\s+" + TITLES + r"\s+([A-Z][A-Za-z'’-]+)")
# "(Ward 1)", "(Ward 10; arrived 5:05 p.m.)", and the minutes' own slips "Ward 3)" and "(Ward7)"
# "Ward N" with or without its parentheses, with a note after it ("Ward 2 - left early", "Ward 8, Excused")
WARD_RE = re.compile(r"\(?\s*\bWard\s*(\d{1,2})\b[^)]*\)?", re.I)
PAREN_RE = re.compile(r"\([^)]*\)?|\bWard\s*\d{1,2}\b[^)]*\)?", re.I)
DASH_NOTE_RE = re.compile(r"\s*[-–—‐]\s*[a-z][^()]*")        # "Trisha Butler - arrived late (Ward 12)"
# a late arrival ("arrived 4:44 p.m.", "joined late") or an early departure ("left early", "excused at 8 p.m.")
ARRIVED_RE = re.compile(r"\b(?:arrived|late|joined)\b", re.I)
LEFT_RE = re.compile(r"\b(?:left|departed|excused at)\b", re.I)
SECTION_RE = re.compile(r"^\d{1,2}\.\s+[A-Z]")                     # "3.   Planning Commission" (2023 minutes)
NOT_A_PERSON = {"vacant"}                                         # a seat listed as "Vacant": no one to record
WARD_ONLY_RE = re.compile(r"^\(?\s*Ward\s*\d{1,2}\b[^()]*\)?$", re.I)
NOT_PRESENT_RE = re.compile(r"\bnot\s+present\b|\babsent\b|\bleft\s+the\s+meeting\b|\bhad\s+left\b", re.I)
MAYOR_NOTE_RE = re.compile(r"\(\s*Mayor\s*\)", re.I)
PRO_TEM_RE = re.compile(r"^\s*Mayor\s+Pro\s+Te(?:a)?m\s*$", re.I)    # "Mayor Pro Team" is printed too
# A person's name as the attendance prints it: two or three capitalised words (an initial counts), maybe a suffix.
# Four or more ("Tim Chandler Valerie Guzman", a missing comma) is not one name.
NAME_RE = re.compile(r"^[A-Z][A-Za-z.'’-]*(?:\s+[A-Z][A-Za-z.'’-]*){1,2}(?:,?\s+(?:Jr|Sr|II|III|IV)\.?)?$")
SUFFIX_RE = re.compile(r"^(?:Jr|Sr|II|III|IV)\.?$")
HEADING_RE = re.compile(r"^[A-Z][A-Z&,'’/().\- ]{3,}(?:\s|$)")


@dataclass
class Line:
    page: int
    text: str             # stripped


@dataclass
class Person:
    raw_name: str
    ward: int | None
    page: int
    pro_tem: bool = False
    mayor: bool = False      # listed with the title Mayor ("Mayor Kim McMillan")
    arrived_late: bool = False  # the attendance notes a late arrival ("arrived 5:05 p.m.")
    left_early: bool = False    # ... or an early departure ("left early")
    line_cut: bool = False      # the name runs over a line end the list crosses: never joined by N9 (W2 rule 5)

    @property
    def part_time(self) -> bool:
        return self.arrived_late or self.left_early


@dataclass
class Vote:
    raw_name: str
    raw_value: str        # label as printed (AYE, NAY, ...)
    value: str
    line_cut: bool = False  # the name runs over a line end the list crosses: never joined by N9 (W2 rule 5)


@dataclass
class RollCall:
    page: int
    votes: list
    absent: list          # names on an ABSENT line inside the vote block
    outcome_text: str
    outcome: str
    item: dict            # {number|None, kind, title, heading}
    motion: dict | None   # {text, mover, seconder, page}
    order: int
    notes: list = field(default_factory=list)   # NOTE lines in the vote block, as printed
    # set by _item_for_vote; a roll call made without it is held, never linked on trust
    link: dict = field(default_factory=lambda: {"basis": "unset", "ok": False, "detail": "item link not checked"})
    absent_cut: set = field(default_factory=set)   # names in `absent` that run over a line end (never joined by N9)


@dataclass
class ParsedCityMinutes:
    text_layer: str                   # text | ocr | none
    pages: int
    present: list = field(default_factory=list)
    absent: list = field(default_factory=list)
    attendance_page: int | None = None
    presiding: str | None = None        # name as printed in the call-to-order sentence
    presiding_title: str | None = None  # its title there (Mayor, Mayor Pro Tem)
    roll_calls: list = field(default_factory=list)
    problems: list = field(default_factory=list)
    printed_date: str | None = None     # the date of the call-to-order sentence, ISO ("... on Thursday, August 1, 2024")


def pdf_layer(pdf: Path, pages: list[str]) -> str:
    """'none' when every page is image-only; 'ocr' when the producer, creator or fonts say a scanner or OCR engine
    made the text (e.g. tesseract's GlyphLessFont); else 'text'."""
    if not pages or len(image_only_pages(pages)) == len(pages):
        return "none"
    info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, timeout=120).stdout.decode("utf-8", "replace")
    made_by = " ".join(re.findall(r"^(?:Creator|Producer):\s*(.*?)\s*$", info, re.M))
    fonts = subprocess.run(["pdffonts", str(pdf)], capture_output=True, timeout=120).stdout.decode("utf-8", "replace")
    if SCAN_MARKS.search(made_by) or "GlyphLessFont" in fonts:
        return "ocr"
    return "text"


# Unicode format characters (category Cf: U+200B zero width space, U+200C, U+200D, U+2060, U+FEFF, U+00AD soft
# hyphen, ...): some exports carry them in the text layer; they print as nothing (W1, "Verified-rate plan")
FORMAT_CHARS = "".join(chr(c) for c in range(sys.maxunicode + 1) if unicodedata.category(chr(c)) == "Cf")
INVISIBLE = re.compile(f"[{re.escape(FORMAT_CHARS)}]")
ABUT = 0.05                     # pt: two glyph boxes this close (or overlapping) touch, with no visible gap
_NOT_SPACE = rf"[^\s{re.escape(FORMAT_CHARS)}]"
# a word, then a run of format characters with blanks before or after it, then the next word (lookahead)
_FORMAT_BREAK = re.compile(rf"({_NOT_SPACE}+)([ \t\u00a0]*[{re.escape(FORMAT_CHARS)}]+[{re.escape(FORMAT_CHARS)} \t\u00a0]*)"
                           rf"(?=({_NOT_SPACE}+))")


def format_breaks(words) -> dict[int, set]:
    """W1, from the text layer's word boxes (pdfwords.Word, in pdftotext's order): per page, the (word before, word
    after) pairs that a word made only of format characters separates on one line when the two boxes abut
    (`next.x0 - prev.x1 <= ABUT`). 2020-10-01 page 1 prints "Jeff Henley" as "J", a U+200B word and "eff" whose box
    starts where "J" ends. A pair also seen with a visible gap on the same page is left out, so no gap is ever closed."""
    from .pdfwords import LINE_TOL
    join, gap = {}, {}
    pages: dict[int, list] = {}
    for w in words:
        pages.setdefault(w.page, []).append(w)
    for page, ws in pages.items():
        for i, w in enumerate(ws):
            if INVISIBLE.sub("", w.text) or (i and not INVISIBLE.sub("", ws[i - 1].text)):
                continue                                       # not a format-only word, or not the first of a run
            j, k = i - 1, i + 1
            while k < len(ws) and not INVISIBLE.sub("", ws[k].text):
                k += 1
            if j < 0 or k >= len(ws):
                continue
            a, b = ws[j], ws[k]
            if abs(a.yc - b.yc) > LINE_TOL * min(a.h, b.h) or b.x0 < a.x0:
                continue                                       # not one line, left to right
            key = (INVISIBLE.sub("", a.text), INVISIBLE.sub("", b.text))
            (join if b.x0 - a.x1 <= ABUT else gap).setdefault(page, set()).add(key)
    return {p: keys - gap.get(p, set()) for p, keys in join.items() if keys - gap.get(p, set())}


def join_format_breaks(pages: list[str], words) -> list[str]:
    """The layout text with each W1 pair (format_breaks) joined: "J\u200b eff" -> "Jeff" when the boxes of "J" and
    "eff" abut. Any other format character is left for lines_of to delete, and a visible gap stays a gap. The result
    is what the page shows: a better single reading, not a repair."""
    joins = format_breaks(words)
    out = []
    for n, text in enumerate(pages, 1):
        pairs = joins.get(n)
        if pairs:
            text = _FORMAT_BREAK.sub(lambda m: m.group(1) if (m.group(1), m.group(3)) in pairs
                                     and INVISIBLE.sub("", m.group(2)) else m.group(0), text)
        out.append(text)
    return out


def lines_of(pages: list[str]) -> list[Line]:
    """Page-numbered lines, stripped. Format characters (Cf) are removed (they print as nothing); no other change."""
    return [Line(i + 1, INVISIBLE.sub("", raw).replace(" ", " ").strip())
            for i, p in enumerate(pages) for raw in p.splitlines()]


PAGE_NUMBER_RE = re.compile(r"^\d{1,3}$")


def blank_page_numbers(lines: list[Line]) -> list[Line]:
    """A page's printed number (a line of digits only, the last non-blank line of its page) is read as a blank line,
    so it never breaks a vote block ("AYE: ..." on page 10, "NAY: ..." on page 11) or joins the next sentence."""
    last: dict[int, int] = {}
    for k, ln in enumerate(lines):
        if ln.text:
            last[ln.page] = k
    return [Line(ln.page, "") if last.get(ln.page) == k and PAGE_NUMBER_RE.match(ln.text) else ln
            for k, ln in enumerate(lines)]


def _label_of(text: str, labels) -> tuple[str, str] | None:
    m = re.match(r"^([A-Za-z][A-Za-z ]*?)\s*:\s*(.*)$", text)       # "AYE:", also "Nay:" and "Abstain:"
    if m and m.group(1).strip().upper() in labels:
        return m.group(1).strip().upper(), m.group(2)
    return None


def _collapse_keep_line_ends(text: str) -> str:
    """Each whitespace run -> one space, or one "\\n" when the run holds a line end (_block joins a list's lines with
    "\\n"), so a name that runs over a line end can be told from one printed on one line (W2 rule 5). Replacing each
    "\\n" by a space gives exactly the old one-space collapse."""
    return re.sub(r"\s+", lambda m: "\n" if "\n" in m.group() else " ", text)


def split_names(text: str) -> list[str]:
    """'Allen, Burkhart and Chandler' -> ['Allen', 'Burkhart', 'Chandler']; 'None' -> []. A name that runs over a
    line end of the list keeps a "\\n" where the line ended (the caller reads it as a space, and flags the cut)."""
    text = _collapse_keep_line_ends(text).strip().rstrip(".;")
    parts = []
    for chunk in re.split(r",|;|\band\b|&", text):
        c = chunk.strip()
        if c and c.lower() not in ("none", "n/a"):
            parts.append(c)
    return parts


_AND = re.compile(r"\sand\s")       # " and " (either space may be a line end: _collapse_keep_line_ends)


def split_outside_parens(text: str) -> list[str]:
    """Split on commas, semicolons and ' and ' outside parentheses: 'A (Ward 10; arrived 5 p.m.), B' -> 2 parts. As
    split_names, a part that runs over a line end keeps a "\\n" there."""
    text = _collapse_keep_line_ends(text).strip().rstrip(".;")
    parts, depth, cur, i = [], 0, "", 0
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth = 1                       # "((Ward 11)" is printed too: parentheses do not nest here
        elif ch == ")":
            depth = max(depth - 1, 0)
        if depth == 0 and ch in ",;":
            parts.append(cur)
            cur = ""
        elif depth == 0 and _AND.match(text, i):
            parts.append(cur)
            cur = ""
            i += 5
            continue
        else:
            cur += ch
            # a parenthesised group ("(Ward N)", "(11)") always ends a member's entry, even where the comma after
            # it was left out: "Tim Chandler (Ward 4) Valerie Guzman (Ward 5)" is two members
            if ch == ")" and depth == 0 and re.search(r"\([^()]*\)$", cur) \
                    and re.match(r"\s+[A-Z]", text[i + 1:]):
                parts.append(cur)
                cur = ""
        i += 1
    parts.append(cur)
    return [p.strip() for p in parts if p.strip() and p.strip().lower() not in ("none", "n/a")]


def parse_people(text: str, page: int) -> list[Person]:
    """Attendance names with their printed ward. 'David Allen, Mayor Pro Tem (Ward 8)' is one person; a note in the
    parentheses ('Ward 10; arrived 5:05 p.m.') is dropped from the name (the ward is kept)."""
    out: list[Person] = []
    for tok_nl in split_outside_parens(text):
        tok = tok_nl.replace("\n", " ")                  # read as before; tok_nl only says where a line ended
        ward = WARD_RE.search(tok)
        if WARD_ONLY_RE.match(tok) and out:          # "Wallace Redd, Ward 4)": the ward split off by a comma
            if out[-1].ward is None:
                out[-1].ward = int(ward.group(1))
            continue
        name = PAREN_RE.sub("", DASH_NOTE_RE.sub("", tok)).strip()
        arrived, left = bool(ARRIVED_RE.search(tok)), bool(LEFT_RE.search(tok))
        if name.lower() in NOT_A_PERSON:
            continue
        if SUFFIX_RE.match(name) and out:                # "Joe Smith, Jr." split on its comma
            out[-1].raw_name += ", " + name
            continue
        mayor = re.match(r"^Mayor\s+(?!Pro\s+Te)", name)
        if mayor:
            name = name[mayor.end():]
        mayor = mayor or MAYOR_NOTE_RE.search(tok)          # "Joe Pitts (Mayor)" (2025-01-02)
        if PRO_TEM_RE.match(name) and out:
            out[-1].pro_tem = True
            if ward and out[-1].ward is None:
                out[-1].ward = int(ward.group(1))
            continue
        at = tok.find(name)                              # tok and tok_nl differ only in "\n" for " ", index for index
        cut = "\n" in (tok_nl[at:at + len(name)] if at >= 0 else tok_nl)      # not found: count any line end (held)
        out.append(Person(name, int(ward.group(1)) if ward else None, page, mayor=bool(mayor), arrived_late=arrived,
                          left_early=left, line_cut=cut))
    return out


def _block(lines: list[Line], i: int, labels, prose_labels=()) -> tuple[str, str, int]:
    """Lines from i (a label line) until a blank line or another label line -> (label, text, next index). A name
    list also ends where a sentence starts; a prose label (NOTE) runs to the blank line. The lines are joined with
    "\\n", so a name list can tell a name cut at a line end (W2 rule 5); read as prose, each "\\n" is a space."""
    label, rest = _label_of(lines[i].text, labels)
    parts = [rest]
    j = i + 1
    while j < len(lines) and lines[j].text and not _label_of(lines[j].text, labels) \
            and not SECTION_RE.match(lines[j].text) \
            and (_list_goes_on(parts[-1], lines[j].text)
                 or (not (HEADING_RE.match(lines[j].text) and not re.search(r"[a-z]", lines[j].text))
                     and (label in prose_labels or not _ends_list(lines[j].text)))):
        parts.append(lines[j].text)
        j += 1
    return label, "\n".join(parts), j


# A line of names in capitals ("SHAKEENAB, SMITH, STREETMAN, ZACHARIAS", CivicClerk minutes from 2025 on)
CAPS_NAMES_RE = re.compile(r"^[A-Z][A-Za-z'’.-]*(?:\s*\([^)]*\))?(?:\s*,?\s*[A-Z][A-Za-z'’.-]*(?:\s*\([^)]*\))?)*\s*,?"
                           r"(?:\s*\([^)]*)?$")      # a note left open at the line's end: "SMITH (ARRIVED AT"


def _list_goes_on(prev: str, text: str) -> bool:
    """The name list goes on, even when the names are printed in capitals (which would otherwise read as a heading):
    the line before ends with a comma and this line is only names ('AYE: BROWN, HAYWOOD, LOVATO,' / 'SHAKEENAB,
    SMITH'), or the line before left a note open ('SMITH (ARRIVED AT' / '6:03 PM), STREETMAN, ZACHARIAS')."""
    if prev.count("(") > prev.count(")"):
        return True
    return prev.rstrip().endswith(",") and bool(CAPS_NAMES_RE.match(text.strip()))


def _ends_list(text: str) -> bool:
    """A sentence or a heading starts here, so a name list without a blank line after it ends. A name list holds only
    capitalised words and 'and' (notes in parentheses aside): 'Mayor Pro Tem (Ward 9), Mike' continues the list,
    'The motion ... passed.' does not."""
    if HEADING_RE.match(text) and not re.search(r"[a-z]", text):
        return True
    words = re.findall(r"[A-Za-z]+", PAREN_RE.sub("", text))
    return any(w.islower() and len(w) > 2 and w != "and" for w in words)


def _sentence(lines: list[Line], j: int) -> tuple[str, int]:
    """The first sentence from line j on (skipping blank lines) -> (text, index after it)."""
    while j < len(lines) and not lines[j].text:
        j += 1
    parts = []
    while j < len(lines) and lines[j].text:
        parts.append(lines[j].text)
        j += 1
        if first_sentence(" ".join(parts)) is not None:
            break
    text = " ".join(parts)
    return first_sentence(text) or text, j


ABBREVIATIONS = {"no", "mr", "mrs", "ms", "dr", "st", "jr", "sr", "vs", "co", "inc", "p.m", "a.m", "ft", "ave", "rd"}


def first_sentence(text: str) -> str | None:
    """Text up to the first full stop that ends a sentence, or None. 'U.S.', 'No.', 'p.m.' do not end one."""
    for m in re.finditer(r"\.(?=\s|$)", text):
        word = re.search(r"([A-Za-z.]+)$", text[:m.start()])
        w = word.group(1).lower() if word else ""
        if re.fullmatch(r"(?:[a-z]\.)*[a-z]", w) and len(w.replace(".", "")) <= 2 or w in ABBREVIATIONS:
            continue
        return text[:m.end()]
    return None


def _para_start(lines: list[Line], i: int) -> bool:
    """Line i starts a paragraph: the first line, after a blank line, or the first line of a page."""
    return i == 0 or not lines[i - 1].text or lines[i - 1].page != lines[i].page


def _heading(text: str, cfg: AgendaCenterConfig, labels) -> bool:
    """A section heading: an all-capitals line ("CONSENT AGENDA"), or one that starts with two or more capitalised
    words ("FINANCE COMMITTEE Councilman Jeff Burkhart, Chair"). Never a label or an item line."""
    if _label_of(text, labels) or cfg.item_number.match(text) or not HEADING_RE.match(text):
        return False
    words = re.findall(r"[A-Za-z&]+", text)
    run = 0
    for w in words:
        if w.isupper() and (len(w) > 1 or w == "&"):
            run += 1
        else:
            break
    return run == len(words) or run >= 2


def _ends_title(text: str, cfg: AgendaCenterConfig, labels) -> bool:
    """An item's title runs over the lines after its number until one of these: a blank line, a heading, a label
    line ("AYE: ..."), or a line that starts the item's body: a sentence ("The ...", "There was no
    recommendation ...", "Because ...") or a member speaking or moving ("Councilperson Allen made a motion").
    Minutes often print the body right under the title with no blank line between them."""
    return (not text or _heading(text, cfg, labels) or bool(_label_of(text, labels)) or bool(BODY_LINE_RE.match(text))
            or bool(MOTION_RE.search(text)))


def _heading_text(text: str) -> str:
    """A heading as printed, without a sentence that runs on after it on the same line ("DELIBERATION PHASE:
    Councilman Garrett made a motion ..." -> "DELIBERATION PHASE")."""
    text = re.sub(r"\s+", " ", text)
    m = BODY_IN_LINE_RE.search(text)
    return text[:m.start()].strip(" :;,-") if m and m.start() > 0 else text


def parse_text(pages: list[str], cfg: AgendaCenterConfig, text_layer: str = "text") -> ParsedCityMinutes:
    out = ParsedCityMinutes(text_layer=text_layer, pages=max(len(pages), 1))
    if text_layer != "text":
        out.problems.append(f"text layer {text_layer}: not read")
        return out
    lines = blank_page_numbers(lines_of(pages))
    vote_labels = set(cfg.vote_labels)
    att_labels = set(cfg.present_labels) | set(cfg.absent_labels)
    note_labels = set(cfg.note_labels)
    all_labels = vote_labels | att_labels | note_labels
    joined = " ".join(l.text for l in lines)
    pm = cfg.presiding.search(re.sub(r"\s+", " ", joined))
    if pm:
        out.presiding, out.presiding_title = pm.group("name"), pm.group("title")
    out.printed_date = called_to_order_on(joined)

    item = {"number": None, "kind": None, "title": None, "heading": None}
    titles: dict = {}                  # (kind, number) -> title as first printed in this document
    window: list[Line] = []            # text since the last vote block or item start (for the motion)
    i, order = 0, 0
    seen_attendance = False
    attendance_closed = False          # the first heading after the attendance lines closes the section
    while i < len(lines):
        ln = lines[i]
        t = ln.text
        lab = _label_of(t, all_labels) if t else None
        if lab and lab[0] in att_labels and not out.roll_calls and not attendance_closed:
            # every attendance line of the ATTENDANCE section ("IN PERSON:" and "VIA GOOGLE MEETS:" in 2020); a
            # note after a name ("Trisha Butler - arrived late") does not end the list, a blank line does
            label, text, j = _block(lines, i, all_labels, att_labels)
            text = re.sub(rf"^\s*{re.escape(label)}\s*:\s*", "", text, flags=re.I)   # "PRESENT: PRESENT: ..." (2025-01-02)
            people = parse_people(text, ln.page)
            if label in cfg.present_labels:
                out.present.extend(people)
                out.attendance_page = out.attendance_page or ln.page
            else:
                out.absent.extend(people)
            seen_attendance = True
            i = j
            continue
        if lab and lab[0] in vote_labels:
            votes, absent, notes, page = [], [], [], ln.page
            absent_cut: set = set()
            j = i
            while True:
                label, text, j = _block(lines, j, all_labels, note_labels)
                if label in vote_labels:
                    votes += [Vote(n.replace("\n", " "), label, cfg.vote_labels[label], line_cut="\n" in n)
                              for n in split_names(text)]
                elif label in note_labels:
                    text = text.replace("\n", " ")       # prose: a line end is a space
                    notes.append(text)
                    if NOT_PRESENT_RE.search(text):      # "NOTE: Councilman Alexander was not present for this vote."
                        absent += [m.group(1) for m in NAMED_RE.finditer(text)]
                else:
                    names = split_names(text)
                    absent += [n.replace("\n", " ") for n in names]
                    absent_cut |= {n.replace("\n", " ") for n in names if "\n" in n}
                k = j
                while k < len(lines) and not lines[k].text:
                    k += 1
                if k < len(lines) and _label_of(lines[k].text, all_labels):
                    j = k
                    continue
                break
            sentence, j2 = _sentence(lines, j)
            outcome = ("failed" if cfg.outcome_failed.search(sentence) else
                       "passed" if cfg.outcome_passed.search(sentence) else "other")
            if cfg.outcome_failed.search(sentence) and cfg.outcome_passed.search(sentence):
                outcome = "other"
            motion = _motion(window)
            vote_item, link = _item_for_vote(item, window, titles, cfg, motion, sentence)
            out.roll_calls.append(RollCall(page, votes, absent, sentence, outcome, vote_item, motion, order,
                                           notes, link, absent_cut))
            order += 1
            window = []
            i = j
            continue
        if t and _para_start(lines, i) and cfg.item_number.match(t):
            m = cfg.item_number.match(t)
            kind, number = m.group(1).lower(), m.group(2)
            rest = t[m.end():].strip()
            window = []
            if re.match(r"[a-z]", rest):
                # a sentence about the item ("RESOLUTION 35-2018-19 was removed from the Consent Agenda.
                # Councilman Powers made a motion ..."): the item is taken up here, but the line is no title
                item = {"number": number, "kind": kind, "title": titles.get((kind, number)),
                        "heading": item["heading"]}
                window.append(ln)
                i += 1
                continue
            title_parts, j = [rest], i + 1
            while j < len(lines) and not _ends_title(lines[j].text, cfg, all_labels):
                title_parts.append(lines[j].text)
                j += 1
            item = {"number": number, "kind": kind,
                    "title": re.sub(r"\s+", " ", " ".join(title_parts)).strip(), "heading": item["heading"]}
            titles.setdefault((kind, number), item["title"])
            i = j
            continue
        if t and _para_start(lines, i) and _heading(t, cfg, all_labels):
            attendance_closed = attendance_closed or seen_attendance
            item = {"number": None, "kind": None, "title": None, "heading": _heading_text(t)}
            window = []
        if t:
            window.append(ln)
        i += 1
    if not seen_attendance:
        out.problems.append("no attendance lines found")
    return out


CALLED_ON_RE = re.compile(r"called\s+to\s+order\b.{0,160}?\b(January|February|March|April|May|June|July|August|"
                          r"September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})", re.I | re.S)
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december")


def called_to_order_on(text: str) -> str | None:
    """The date the minutes say the meeting was called to order, as YYYY-MM-DD, or None."""
    m = CALLED_ON_RE.search(re.sub(r"\s+", " ", text))
    if not m:
        return None
    return f"{int(m.group(3)):04d}-{MONTHS.index(m.group(1).lower()) + 1:02d}-{int(m.group(2)):02d}"


def sentences(text: str) -> list[str]:
    """text split into its sentences, the words after the last full stop as the last one ("... passed. The following
    vote on the motion to postpone was recorded:" -> 2 sentences). 'U.S.', 'No.', 'p.m.' do not end one."""
    out, rest = [], text.strip()
    while rest:
        s = first_sentence(rest)
        if s is None or not rest[len(s):].strip():
            out.append(rest)
            break
        out.append(s)
        rest = rest[len(s):].strip()
    return out


def last_sentence(text: str) -> str:
    """The last sentence of text, or the words after its last full stop."""
    parts = sentences(text)
    return parts[-1] if parts else ""


def lead_in(text: str, cfg: AgendaCenterConfig) -> str | None:
    """The words that lead into a vote: the last sentence before the vote lines when it is a vote lead-in
    (cfg.vote_lead_in), from the lead-in words on ("With no objections, the following vote was recorded:" -> "the
    following vote was recorded:"). Any other last sentence (an abstention note, a speaker) gives None."""
    s = last_sentence(text)
    m = cfg.vote_lead_in.search(s)
    return s[m.start():] if m else None


def vote_words(window: list[Line], cfg: AgendaCenterConfig, motion: dict | None, sentence: str) -> list[str]:
    """The words that belong to a vote (docs/architecture/city-council.md, "Vote-to-item link invariant"): its motion
    (when exactly one is linked), its lead-in sentence and its outcome sentence. Nothing else in the paragraph."""
    text = re.sub(r"\s+", " ", " ".join(l.text for l in window))
    return [x for x in ((motion or {}).get("text"), lead_in(text, cfg), sentence) if x]


def _antecedent(text: str, motion: dict | None) -> str:
    """The paragraph text a "this ordinance" in the vote's words can refer back to: what comes before the motion
    sentence (when one is linked), else everything before the last sentence. A number named after the motion, or in
    the sentence right before the vote lines, is never the item the vote is on."""
    mtext = (motion or {}).get("text")
    pos = text.find(mtext) if mtext else -1
    if pos < 0:
        last = last_sentence(text)
        pos = len(text) - len(last) if last and text.endswith(last) else 0
    return text[:pos]


def _item_for_vote(item: dict, window: list[Line], titles: dict, cfg: AgendaCenterConfig, motion: dict | None,
                   sentence: str) -> tuple[dict, dict]:
    """The vote's item and how it was linked -> (item, {basis, ok, detail}). Never guessed: when the minutes do not
    show which numbered item a vote is on, the vote goes to its section heading; when they contradict the item it
    follows, the vote also goes to the section and its roll call is held (ok False).

    Invariant (docs/architecture/city-council.md, "Vote-to-item link invariant"): a roll call is linked to a numbered
    item only when the vote's own words (vote_words: its motion, its lead-in sentence, its outcome sentence) identify
    that item, or the vote sits under that item's own number line and its words name no other item, kind or several
    items. A number elsewhere in the paragraph is never read as the vote's own words; the one place it counts is the
    "this ordinance" rule below, where a single number in the paragraph before the motion (a speaker's mention among
    them) is the antecedent the motion refers to. An abstention or recusal note never counts.
    - Words that name a Consent Agenda, an adjournment or appointments (not_item_votes) are never on one item.
    - Under an item's own number line, the vote is on that item unless its words name another item number, only
      another kind ("adopt this resolution" under an ORDINANCE: held), or several items ("these ordinances").
    - Under a section heading only ("ZONING"), the vote is on a numbered item only when its words name the number,
      or they say "this ordinance" and the paragraph before the motion (no motion: before the last sentence) names
      exactly one ordinance outside an abstention note (vote_asides)."""
    section = {"number": None, "kind": None, "title": None, "heading": item["heading"]}
    text = re.sub(r"\s+", " ", " ".join(l.text for l in window))
    subject = " ".join(vote_words(window, cfg, motion, sentence))
    if cfg.not_item_votes.search(subject):
        return section, {"basis": "not_an_item_vote", "ok": True, "detail": None}
    # in a sentence the number may be printed in any case ("adopt Resolution 42-2021-22")
    in_text = re.compile(cfg.item_number.pattern, cfg.item_number.flags | re.I)
    nums = {(m.group(1).lower(), m.group(2)) for m in in_text.finditer(subject)}
    kinds = [(m.group(1).lower(), bool(m.group(2))) for m in cfg.item_kind_word.finditer(subject)]
    kind_set = {k for k, _ in kinds}
    if item["number"]:
        me = (item["kind"], item["number"])
        label = f"{item['kind']} {item['number']}"
        if nums and me not in nums:
            return section, {"basis": "contradiction", "ok": False,
                             "detail": f"vote names {', '.join(sorted(' '.join(n) for n in nums))}; item {label}"}
        if len(nums) > 1:
            return section, {"basis": "several_items", "ok": True, "detail": None}
        if not nums and kind_set and item["kind"] not in kind_set:
            return section, {"basis": "contradiction", "ok": False,
                             "detail": f"vote is on a {', '.join(sorted(kind_set))}; item {label}"}
        if not nums and kinds and all(plural for k, plural in kinds if k == item["kind"]):
            return section, {"basis": "several_items", "ok": True, "detail": None}
        return dict(item), {"basis": "named" if nums else "heading", "ok": True, "detail": None}
    if len(nums) == 1:
        kind, number = next(iter(nums))
    else:
        if nums or not kinds:
            return section, {"basis": "section", "ok": True, "detail": None}
        named = {(m.group(1).lower(), m.group(2)) for s in sentences(_antecedent(text, motion))
                 if not cfg.vote_asides.search(s) for m in in_text.finditer(s)}
        if len(named) != 1:
            return section, {"basis": "section", "ok": True, "detail": None}
        kind, number = next(iter(named))
        if kind_set != {kind} or any(plural for _, plural in kinds):
            return section, {"basis": "section", "ok": True, "detail": None}
    return ({"number": number, "kind": kind, "title": titles.get((kind, number)), "heading": item["heading"]},
            {"basis": "named", "ok": True, "detail": None})


def _motion(window: list[Line]) -> dict | None:
    """The motion behind a vote: only when exactly one 'made a motion' sentence sits between the item start (or the
    previous vote) and this vote. Two or more (e.g. a motion to postpone, then the main motion) link none."""
    text = re.sub(r"\s+", " ", " ".join(l.text for l in window))
    movers = list(MOTION_RE.finditer(text))
    if len(movers) != 1:
        return None
    m = movers[0]
    sec = SECOND_RE.search(text, m.end())
    end = sec.end() if sec else m.end()
    start = text.rfind(".", 0, m.start()) + 1
    page = next((l.page for l in window if m.group(1) in l.text and "motion" in l.text), window[0].page)
    return {"text": text[start:end].strip(), "mover": m.group(1), "seconder": sec.group(1) if sec else None,
            "page": page}


def read_pages(pdf: Path) -> list[str]:
    """The city reader's text of each page of a stored PDF: its text layer (`pdftotext -layout`), with the words a
    format-character-only word separated joined where their glyphs touch (W1, join_format_breaks; the word boxes are
    read only when the text carries a format character)."""
    pages = extract_pages(pdf)
    if any(INVISIBLE.search(p) for p in pages):
        from .pdfwords import pdf_words
        pages = join_format_breaks(pages, pdf_words(pdf))
    return pages


def _flat(s: str) -> str:
    return re.sub(r"\s+", " ", INVISIBLE.sub("", s).replace("\u00a0", " ")).strip()


def page_has(page: str, text: str) -> bool:
    """True when `text` is printed on `page`, whitespace collapsed on both sides and invisible characters removed."""
    return bool(_flat(text)) and _flat(text) in _flat(page)


def page_has_line(page: str, text: str) -> bool:
    """True when one line of `page` is exactly `text` (each whitespace collapsed, invisible characters removed): a
    heading printed as its own line, never the same words inside a longer line ("Joint City Council - Special Session
    with ...")."""
    want = _flat(text)
    return bool(want) and any(_flat(line) == want for line in page.splitlines())


def parse_minutes_pdf(pdf: Path, cfg: AgendaCenterConfig) -> ParsedCityMinutes:
    pages = read_pages(pdf)
    return parse_text(pages, cfg, pdf_layer(pdf, pages))


def short_hash(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:10]
