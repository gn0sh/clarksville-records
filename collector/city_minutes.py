"""Read City Council minutes from their text layer (M4, slice 1): attendance, motions and roll-call votes by name.

The minutes print attendance as "PRESENT: Richard Garrett (Ward 1), ..., David Allen, Mayor Pro Tem (Ward 8), ..."
and each recorded vote as label lines ("AYE: Allen, Burkhart, ...", "NAY: Henley, Richmond") followed by an outcome
sentence ("The motion to adopt this ordinance on first reading passed."). Labels, item-number and outcome patterns
come from agenda-center.yml.

Rules (same as the county): values only from a born-digital text layer. A scan (no text, or text from a scanner or
OCR engine) is marked not read, and nothing is taken from it. Nothing is guessed: a vote name that does not match
exactly one member recorded present (or the presiding mayor) stays unresolved and holds its roll call back
(verification "unverified"), shown as printed. Consent-agenda votes are kept as one roll call on the consent motion;
abstentions on single consent items are noted in prose by the minutes and are not expanded.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .agenda_center import AgendaCenterConfig
from .extract import extract_pages, image_only_pages

SCAN_MARKS = re.compile(r"scan|paper capture|konica|bizhub|ricoh|xerox|canon ir|sharp mx|kyocera|lexmark|"
                        r"\bocr\b|tesseract|abbyy|finereader|omnipage", re.I)
TITLES = r"(?:Councilman|Councillady|Councilwoman|Councilmember|Council Member|Councilor|Mayor Pro Tem|Mayor)"
MOTION_RE = re.compile(TITLES + r"\s+([A-Z][A-Za-z'’-]+)\s+made\s+a\s+motion")
NAMED_RE = re.compile(TITLES + r"\s+([A-Z][A-Za-z'’-]+)")
SECOND_RE = re.compile(r"seconded\s+by\s+" + TITLES + r"\s+([A-Z][A-Za-z'’-]+)")
# "(Ward 1)", "(Ward 10; arrived 5:05 p.m.)", and the minutes' own slips "Ward 3)" and "(Ward7)"
# "Ward N" with or without its parentheses, with a note after it ("Ward 2 - left early", "Ward 8, Excused")
WARD_RE = re.compile(r"\(?\s*\bWard\s*(\d{1,2})\b[^)]*\)?", re.I)
PAREN_RE = re.compile(r"\([^)]*\)?|\bWard\s*\d{1,2}\b[^)]*\)?", re.I)
DASH_NOTE_RE = re.compile(r"\s*[-–—‐]\s*[a-z][^()]*")        # "Trisha Butler - arrived late (Ward 12)"
PART_TIME_RE = re.compile(r"\b(?:arrived|left|late|departed|excused at)\b", re.I)
SECTION_RE = re.compile(r"^\d{1,2}\.\s+[A-Z]")                     # "3.   Planning Commission" (2023 minutes)
NOT_A_PERSON = {"vacant"}                                         # a seat listed as "Vacant": no one to record
WARD_ONLY_RE = re.compile(r"^\(?\s*Ward\s*\d{1,2}\b[^()]*\)?$", re.I)
NOT_PRESENT_RE = re.compile(r"\bnot\s+present\b|\babsent\b|\bleft\s+the\s+meeting\b|\bhad\s+left\b", re.I)
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
    part_time: bool = False  # the attendance notes a late arrival or early departure ("arrived 5:05 p.m.")


@dataclass
class Vote:
    raw_name: str
    raw_value: str        # label as printed (AYE, NAY, ...)
    value: str


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


def pdf_layer(pdf: Path, pages: list[str]) -> str:
    """'none' when every page is image-only; 'ocr' when the producer, creator or fonts say a scanner or OCR engine
    made the text (e.g. tesseract's GlyphLessFont); else 'text'."""
    if not pages or len(image_only_pages(pages)) == len(pages):
        return "none"
    info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True).stdout.decode("utf-8", "replace")
    made_by = " ".join(re.findall(r"^(?:Creator|Producer):\s*(.*?)\s*$", info, re.M))
    fonts = subprocess.run(["pdffonts", str(pdf)], capture_output=True).stdout.decode("utf-8", "replace")
    if SCAN_MARKS.search(made_by) or "GlyphLessFont" in fonts:
        return "ocr"
    return "text"


INVISIBLE = re.compile("[​‌‍⁠﻿­]")   # zero-width characters some exports carry


def lines_of(pages: list[str]) -> list[Line]:
    """Page-numbered lines, stripped. Zero-width characters are removed (they print as nothing); no other change."""
    return [Line(i + 1, INVISIBLE.sub("", raw).replace(" ", " ").strip())
            for i, p in enumerate(pages) for raw in p.splitlines()]


def _label_of(text: str, labels) -> tuple[str, str] | None:
    m = re.match(r"^([A-Za-z][A-Za-z ]*?)\s*:\s*(.*)$", text)       # "AYE:", also "Nay:" and "Abstain:"
    if m and m.group(1).strip().upper() in labels:
        return m.group(1).strip().upper(), m.group(2)
    return None


def split_names(text: str) -> list[str]:
    """'Allen, Burkhart and Chandler' -> ['Allen', 'Burkhart', 'Chandler']; 'None' -> []."""
    text = re.sub(r"\s+", " ", text).strip().rstrip(".;")
    parts = []
    for chunk in re.split(r",|;|\band\b|&", text):
        c = chunk.strip()
        if c and c.lower() not in ("none", "n/a"):
            parts.append(c)
    return parts


def split_outside_parens(text: str) -> list[str]:
    """Split on commas, semicolons and ' and ' outside parentheses: 'A (Ward 10; arrived 5 p.m.), B' -> 2 parts."""
    text = re.sub(r"\s+", " ", text).strip().rstrip(".;")
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
        elif depth == 0 and text.startswith(" and ", i):
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
    for tok in split_outside_parens(text):
        ward = WARD_RE.search(tok)
        if WARD_ONLY_RE.match(tok) and out:          # "Wallace Redd, Ward 4)": the ward split off by a comma
            if out[-1].ward is None:
                out[-1].ward = int(ward.group(1))
            continue
        name = PAREN_RE.sub("", DASH_NOTE_RE.sub("", tok)).strip()
        part_time = bool(PART_TIME_RE.search(tok))
        if name.lower() in NOT_A_PERSON:
            continue
        if SUFFIX_RE.match(name) and out:                # "Joe Smith, Jr." split on its comma
            out[-1].raw_name += ", " + name
            continue
        mayor = re.match(r"^Mayor\s+(?!Pro\s+Te)", name)
        if mayor:
            name = name[mayor.end():]
        if PRO_TEM_RE.match(name) and out:
            out[-1].pro_tem = True
            if ward and out[-1].ward is None:
                out[-1].ward = int(ward.group(1))
            continue
        out.append(Person(name, int(ward.group(1)) if ward else None, page, mayor=bool(mayor), part_time=part_time))
    return out


def _block(lines: list[Line], i: int, labels, prose_labels=()) -> tuple[str, str, int]:
    """Lines from i (a label line) until a blank line or another label line -> (label, text, next index). A name
    list also ends where a sentence starts; a prose label (NOTE) runs to the blank line."""
    label, rest = _label_of(lines[i].text, labels)
    parts = [rest]
    j = i + 1
    while j < len(lines) and lines[j].text and not _label_of(lines[j].text, labels) \
            and not SECTION_RE.match(lines[j].text) \
            and not (HEADING_RE.match(lines[j].text) and not re.search(r"[a-z]", lines[j].text)) \
            and (label in prose_labels or not _ends_list(lines[j].text)):
        parts.append(lines[j].text)
        j += 1
    return label, " ".join(parts), j


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


def parse_text(pages: list[str], cfg: AgendaCenterConfig, text_layer: str = "text") -> ParsedCityMinutes:
    out = ParsedCityMinutes(text_layer=text_layer, pages=max(len(pages), 1))
    if text_layer != "text":
        out.problems.append(f"text layer {text_layer}: not read")
        return out
    lines = lines_of(pages)
    vote_labels = set(cfg.vote_labels)
    att_labels = set(cfg.present_labels) | set(cfg.absent_labels)
    note_labels = set(cfg.note_labels)
    all_labels = vote_labels | att_labels | note_labels
    joined = " ".join(l.text for l in lines)
    pm = cfg.presiding.search(re.sub(r"\s+", " ", joined))
    if pm:
        out.presiding, out.presiding_title = pm.group("name"), pm.group("title")

    item = {"number": None, "kind": None, "title": None, "heading": None}
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
            j = i
            while True:
                label, text, j = _block(lines, j, all_labels, note_labels)
                if label in vote_labels:
                    votes += [Vote(n, label, cfg.vote_labels[label]) for n in split_names(text)]
                elif label in note_labels:
                    notes.append(text)
                    if NOT_PRESENT_RE.search(text):      # "NOTE: Councilman Alexander was not present for this vote."
                        absent += [m.group(1) for m in NAMED_RE.finditer(text)]
                else:
                    absent += split_names(text)
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
            out.roll_calls.append(RollCall(page, votes, absent, sentence, outcome, dict(item),
                                           _motion(window), order, notes))
            order += 1
            window = []
            i = j
            continue
        if t and _para_start(lines, i) and cfg.item_number.match(t):
            m = cfg.item_number.match(t)
            title_parts, j = [t[m.end():].strip()], i + 1
            while j < len(lines) and lines[j].text and not _heading(lines[j].text, cfg, all_labels) \
                    and not lines[j].text.startswith(("The ", "This ")):
                title_parts.append(lines[j].text)
                j += 1
            item = {"number": m.group(2), "kind": m.group(1).lower(),
                    "title": re.sub(r"\s+", " ", " ".join(title_parts)).strip(), "heading": item["heading"]}
            window = []
            i = j
            continue
        if t and _para_start(lines, i) and _heading(t, cfg, all_labels):
            attendance_closed = attendance_closed or seen_attendance
            item = {"number": None, "kind": None, "title": None, "heading": re.sub(r"\s+", " ", t)}
            window = []
        if t:
            window.append(ln)
        i += 1
    if not seen_attendance:
        out.problems.append("no attendance lines found")
    return out


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


def parse_minutes_pdf(pdf: Path, cfg: AgendaCenterConfig) -> ParsedCityMinutes:
    pages = extract_pages(pdf)
    return parse_text(pages, cfg, pdf_layer(pdf, pages))


def short_hash(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:10]
