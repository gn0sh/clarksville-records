"""City committee minutes (Finance, Audit): attendance and motions as printed (milestone C1).

The city's committee minutes are text PDFs (read with collector/extract.extract_pages, pdftotext -layout). What is
read, in the minutes' own words (nothing summarised or reworded; no text about anyone is written by us):
- the date the minutes print near the top ("May 27, 2025 at 5:00 PM", "DATE: October 30, 2024", "APRIL 4, 2019").
  When it is not the event's date the file is kept as listed and the mismatch is reported (the 2026-05-26 Finance
  event carries the 2025-05-27 minutes); nothing read from it is confirmed for that meeting;
- the members present and absent, as printed: "Present: Streetman, Lovato, Zacharias (arrived at 5:10 pm)",
  "PRESENT: Jeff Burkhart, Tim Chandler, ...", "Audit Committee members present: ...", "Absent: None". A note in
  brackets after a name ("arrived at 5:10 pm") is kept with it. "Also present" lists (staff, guests, other council
  members) are not members and are not read;
- each motion: "<mover> made a motion to <words>", its seconder ("<name> seconded the motion.", "<name> seconded.",
  "The motion was seconded by <name>."), and its outcome from a fixed vocabulary (OUTCOMES):
    "A voice vote was taken and the motion passed."       -> method "voice vote", outcome "passed"
    "...; Councilman Henley voted "nay." The motion passed." -> voice vote, passed, nays_printed [Councilman Henley]
    "...the motion passed (Councilman Lovato was a no vote)." -> voice vote, passed, nays_printed [Councilman Lovato]
    "The motion was approved unanimously."                 -> method "unanimous", outcome "passed"
    "AYE: a, b, c  NAY: d  The motion passed."             -> method "roll call", ayes_printed, nays_printed
  A voice vote never becomes per-member votes: no member is ever recorded as voting yes unless an AYE list prints the
  name. Names are kept as printed.

Confirmed (anything else is held "Not confirmed", with every reason in `reasons`, never shown publicly):
1. the minutes print the event's own date, and the members present were read;
2. the mover and the seconder were both read, are different people, and each is exactly one member present in the
   same minutes ("Councilman <surname>" or a full name equal to a member's printed name);
3. the outcome is one of OUTCOMES, and every name it prints (a nay, an AYE/NAY list) is a member present, none twice;
4. nothing else is printed between the motion and the next one (a second motion, a withdrawal, a "with no
   objections" ruling, a typo such as "seconded the meeting"): any words not read hold the motion.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december")
MONTH_DATE = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2}),\s*(\d{4})\b", re.I)
HEADER_LINES = 12                   # the printed date is looked for in the first non-blank lines of page 1
# Titles printed before a member's name. A mover or seconder must be printed as one of these and a name, or as a
# member's full name exactly as the attendance prints it
TITLES = ("Councilman", "Councilwoman", "Councillady", "Councilmember", "Council Member", "Chairman", "Chairwoman",
          "Chairperson", "Chair", "Mayor", "Mr.", "Mrs.", "Ms.", "Dr.")
TITLE_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in TITLES) + r")\s+", re.I)
SECTION = re.compile(r"^\s{0,2}(\d{1,2}|[IVX]{1,5})\.\s+(\S.*)$")      # "1.   Call to Order", "VI.  COMMITTEE ACTION"
ITEM = re.compile(r"^\s{3,}([A-Z])\.\s+(\S.*)$")                      # "     A.   ORDINANCE 84-2024-25 ..."
LABEL = re.compile(r"^\s*(?:[A-Za-z][A-Za-z ]{0,40}?\s+members\s+)?(present|absent)\s*:\s*(.*)$", re.I)
OTHER_LABEL = re.compile(r"^\s*[A-Za-z][A-Za-z ?]{0,40}:")             # "ALSO PRESENT:", "Quorum verified? Yes"
NAME = re.compile(r"^[A-Za-z][A-Za-z.'’-]*(?: [A-Za-z][A-Za-z.'’-]*){0,3}$")
WORD = r"[A-Z][A-Za-z.'’-]*"
MOTION = re.compile(r"(?P<mover>(?:" + WORD + r"\s+){0,4}" + WORD + r")\s+(?:then\s+)?made\s+a\s+motion\s+"
                    r"(?P<what>(?:to|for|that)\s.+?)(?=;\s|\.\s|\.?$)", re.S)
SECONDS = (re.compile(r"^(?P<who>[A-Z][A-Za-z.'’ -]{1,40}?)\s+seconded(?:\s+the\s+motion)?\s*[.;]\s*"),
           re.compile(r"^The\s+motion\s+was\s+seconded\s+by\s+(?P<who>[A-Z][A-Za-z.'’ -]{1,40}?)\s*\.\s*"))
Q = "[\"“”]?"
NAY_SAID = r"(?P<nay>[A-Z][A-Za-z.'’ -]{1,40}?)\s+voted\s+" + Q + r"nay\.?" + Q
OUTCOMES = (
    # (method, regex); group `res` passed/failed, optional `nay` (one printed dissent), `ayes`/`nays` (printed lists)
    ("voice vote", re.compile(r"^A\s+voice\s+vote\s+was\s+taken(?:\s+and|;)\s+the\s+motion\s+(?P<res>passed|failed)"
                              r"(?:\s+without\s+objection)?\s*\.\s*")),
    ("voice vote", re.compile(r"^A\s+voice\s+vote\s+was\s+taken;\s+" + NAY_SAID + r"\s*\.?\s*The\s+motion\s+"
                              r"(?P<res>passed|failed)\s*\.\s*")),
    ("voice vote", re.compile(r"^A\s+voice\s+vote\s+was\s+taken\s+and\s+the\s+motion\s+(?P<res>passed|failed)\s*"
                              r"\((?P<nay>[A-Z][A-Za-z.'’ -]{1,40}?)\s+was\s+a\s+no\s+vote\)\s*\.\s*")),
    ("unanimous", re.compile(r"^The\s+motion\s+(?:was\s+approved|passed|carried)\s+unanimously\s*\.\s*")),
    ("roll call", re.compile(r"^AYES?\s*:\s*(?P<ayes>[^:]+?)\s+NAYS?\s*:\s*(?P<nays>[^:]+?)\s+The\s+motion\s+"
                             r"(?P<res>passed|failed)\s*\.\s*")),
)
NONE_WORDS = {"none", "n/a", "no one"}


def clean(s: str) -> str:
    """Unicode format characters (U+200B and the like: the audit minutes print one after every heading number) go."""
    return "".join(ch for ch in s if unicodedata.category(ch) != "Cf")


@dataclass
class Text:
    """A block of lines joined into one string, with the page of each character (for each motion's page)."""
    text: str = ""
    pages: list = field(default_factory=list)       # [(offset, page)] in order

    def add(self, line: str, page: int) -> None:
        line = " ".join(line.split())
        if not line:
            return
        sep = "" if not self.text or (self.text.endswith("-") and line[:1].isdigit()) else " "
        self.pages.append((len(self.text) + len(sep), page))
        self.text += sep + line

    def page_at(self, i: int) -> int:
        p = self.pages[0][1] if self.pages else 1
        for off, page in self.pages:
            if off > i:
                break
            p = page
        return p


@dataclass
class Block:
    section: str | None             # "5. City Council Action Required" (number and heading as printed)
    item: str | None                # "A" (the item letter) or None for the section's own text
    body: Text = field(default_factory=Text)


def lines_of(pages: list[str]) -> list[tuple[int, str]]:
    return [(n, clean(line).rstrip()) for n, p in enumerate(pages, 1) for line in p.split("\n")]


def printed_date(lines: list[tuple[int, str]]) -> str | None:
    """The first "Month D, YYYY" in the first HEADER_LINES non-blank lines of page 1, as YYYY-MM-DD."""
    seen = 0
    for page, line in lines:
        if page != 1 or seen >= HEADER_LINES:
            break
        if not line.strip():
            continue
        seen += 1
        m = MONTH_DATE.search(line)
        if m:
            return f"{int(m.group(3)):04d}-{MONTHS.index(m.group(1).lower()) + 1:02d}-{int(m.group(2)):02d}"
    return None


# ------------------------------------------------------------------ attendance
def split_names(text: str) -> list[str]:
    """Split on commas, semicolons and " and " outside brackets."""
    out, depth, cur = [], 0, ""
    for ch in text:
        depth += ch == "("
        depth -= ch == ")"
        if ch in ",;" and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    names = []
    for part in out:
        names += re.split(r"\s+and\s+(?![^(]*\))", part)
    return [" ".join(n.split()) for n in names if n.strip()]


def parse_people(text: str) -> tuple[list[dict], list[str]]:
    """'Streetman, Zacharias (arrived at 5:10 pm)' -> ([{name, note}], problems)."""
    if " ".join(text.split()).strip(" .").lower() in NONE_WORDS:
        return [], []
    people, problems = [], []
    for part in split_names(text):
        m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*\.?$", part)
        name, note = (m.group(1), m.group(2).strip()) if m else (part.rstrip("."), None)
        if not NAME.match(name):
            problems.append(f"attendance: {part[:60]!r} does not read as a name")
            continue
        people.append({"name": name, "note": note} if note else {"name": name})
    return people, problems


def attendance(lines: list[tuple[int, str]]) -> dict:
    """{present: [...], absent: [...] | None, page, problems}. The first "Present:" and "Absent:" labels; each list runs
    on over the following lines until a blank line, another label, a line with a colon or question mark, or a
    heading."""
    out: dict = {"present": None, "absent": None, "page": None, "problems": []}
    i = 0
    while i < len(lines):
        page, line = lines[i]
        m = LABEL.match(line)
        if not m or out[m.group(1).lower()] is not None:
            i += 1
            continue
        text, j = m.group(2), i + 1
        while j < len(lines):
            nxt = lines[j][1]
            if (not nxt.strip() or LABEL.match(nxt) or OTHER_LABEL.match(nxt) or SECTION.match(nxt) or ITEM.match(nxt)
                    or re.search(r"[:?]", nxt)):          # "Quorum verified? Yes": not a name
                break
            text += " " + nxt.strip()
            j += 1
        people, problems = parse_people(text)
        out[m.group(1).lower()] = people
        out["problems"] += problems
        out["page"] = out["page"] or page
        i = j
    return out


def _surname(name: str) -> str:
    return name.split()[-1].lower()


def resolve(printed: str | None, members: list[str]) -> str | None:
    """The one member present that `printed` names, else None: "<title> <surname>" or "<title> <full name>", or a
    full name equal to a member's printed name (case-insensitive). A surname shared by two members resolves to none."""
    if not printed:
        return None
    printed = " ".join(printed.split())
    titled = TITLE_RE.match(printed)
    rest = printed[titled.end():] if titled else printed
    if not NAME.match(rest):
        return None
    full = [m for m in members if m.lower() == rest.lower()]
    if full:
        return full[0] if len(full) == 1 else None
    if not titled:
        return None
    if len(rest.split()) == 1:
        hits = [m for m in members if _surname(m) == rest.lower()]
    else:          # "Councilwoman Valerie Guzman" when the attendance prints the surname only
        hits = [m for m in members if len(m.split()) == 1 and m.lower() == _surname(rest)]
    return hits[0] if len(hits) == 1 else None


def resolve_listed(printed: str, members: list[str]) -> str | None:
    """A name in a printed vote list (AYE/NAY) or a nay sentence: as resolve(), and a bare surname ("Smith") too."""
    if " " not in printed.strip():
        hits = [m for m in members if _surname(m) == printed.strip().lower()]
        return hits[0] if len(hits) == 1 else None
    return resolve(printed, members)


def mover_of(run: str, members: list[str]) -> str:
    """The mover as printed, from the capitalised words before "made a motion" (the item's heading may run into it:
    "...Chief Freddie Montgomery Councilman Lovato"): from the last title on, else the longest ending of two or three
    words that is a member's printed name, else the last two words."""
    words = run.split()
    titled = list(TITLE_RE.finditer(run))
    if titled:
        return run[titled[-1].start():]
    for k in (3, 2):
        tail = " ".join(words[-k:])
        if len(words) >= k and resolve(tail, members):
            return tail
    return " ".join(words[-2:])


# ------------------------------------------------------------------ blocks and motions
def blocks(lines: list[tuple[int, str]]) -> list[Block]:
    """The minutes cut at each numbered (or roman) section and each lettered item. The 2019 format has no numbers:
    an unindented line in capitals ("CONSIDERATION OF CLAIM") starts a section."""
    out = [Block(section=None, item=None)]
    for page, line in lines:
        s, it = SECTION.match(line), ITEM.match(line)
        caps = (not s and not it and line.strip() and len(line) - len(line.lstrip()) <= 4 and len(line.strip()) > 3
                and line.strip() == line.strip().upper() and re.search(r"[A-Z]{3}", line))
        if s:
            out.append(Block(section=f"{s.group(1)}. {' '.join(s.group(2).split())}", item=None))
        elif caps:
            out.append(Block(section=" ".join(line.split()), item=None))
        elif it:
            out.append(Block(section=out[-1].section, item=it.group(1)))
            out[-1].body.add(it.group(2), page)
        else:
            out[-1].body.add(line, page)
    return out


def _who(printed: str, members: list[str], what: str, reasons: list[str]) -> str | None:
    hit = resolve(printed, members)
    if hit is None:
        reasons.append(f"{what} {printed!r} is not exactly one member present")
    return hit


def read_motion(text: str, m: re.Match, end: int, members: list[str], reasons: list[str]) -> dict:
    """One motion: the words from its "made a motion" to `end` (the next motion or the block's end)."""
    mover = mover_of(m.group("mover"), members)
    out = {"mover_printed": mover, "motion_printed": " ".join(m.group("what").split()),
           "mover": _who(mover, members, "mover", reasons), "seconder_printed": None, "seconder": None,
           "vote": None}
    rest = text[m.end():end].strip().lstrip(".;").strip()
    for rx in SECONDS:
        s = rx.match(rest)
        if s:
            out["seconder_printed"] = " ".join(s.group("who").split())
            out["seconder"] = _who(out["seconder_printed"], members, "seconder", reasons)
            rest = rest[s.end():]
            break
    else:
        reasons.append("seconder not read")
    for method, rx in OUTCOMES:
        o = rx.match(rest)
        if not o:
            continue
        g = o.groupdict()
        vote = {"method": method, "outcome": g.get("res") or "passed", "outcome_printed": " ".join(o.group(0).split())}
        names = []
        if g.get("nay"):
            vote["nays_printed"] = [" ".join(g["nay"].split())]
            names = [(n, "nay") for n in vote["nays_printed"]]
        if method == "roll call":
            ayes, p1 = parse_people(g["ayes"])
            nays, p2 = parse_people(g["nays"])
            vote["ayes_printed"] = [p["name"] for p in ayes]
            vote["nays_printed"] = [p["name"] for p in nays]
            reasons += [f"vote list: {p}" for p in p1 + p2]
            names = [(n, "aye") for n in vote["ayes_printed"]] + [(n, "nay") for n in vote["nays_printed"]]
        said = [resolve_listed(n, members) for n, _ in names]
        for (n, how), hit in zip(names, said):
            if hit is None:
                reasons.append(f"{how} {n!r} is not exactly one member present")
        found = [h for h in said if h]
        if len(set(found)) != len(found):
            reasons.append("a member is named twice in the vote")
        out["vote"] = vote
        rest = rest[o.end():]
        break
    else:
        reasons.append("outcome not read")
    if out["mover"] and out["mover"] == out["seconder"]:
        reasons.append("mover and seconder are the same member")
    left = " ".join(rest.split())
    if left:
        reasons.append(f"words not read: {left[:80]!r}")
    return out


def read_minutes(pages: list[str], event_date: str | None = None) -> dict:
    """Pages of one minutes PDF -> {printed_date, date_mismatch, attendance, motions, problems}. Each motion:
    {n, page, section, item, subject_printed, mover_printed, mover, seconder_printed, seconder, motion_printed, vote,
    confirmed, reasons}. `subject_printed` is the item's (or section's) own words up to the motion, as printed."""
    lines = lines_of(pages)
    date = printed_date(lines)
    att = attendance(lines)
    members = [p["name"] for p in att["present"] or []]
    meeting_reasons = []
    if date is None:
        meeting_reasons.append("the minutes print no date near the top")
    elif event_date and date != event_date:
        meeting_reasons.append(f"the minutes print {date}, the meeting is {event_date}")
    if not members:
        meeting_reasons.append("members present not read")
    meeting_reasons += att["problems"]
    bl = blocks(lines)
    motions = []
    for k, b in enumerate(bl):
        text = b.body.text
        found = list(MOTION.finditer(text))
        # the subject: the item's own words before its first motion; a motion in a section's own text with exactly
        # one item below it is that item's (the minutes print "motion ... A. March 23, 2026"); else the section
        later = [x for x in bl[k + 1:] if x.section == b.section and x.item]
        if b.item:
            first = found[0].start("mover") + found[0].group("mover").rfind(
                mover_of(found[0].group("mover"), members)) if found else len(text)
            subject, item = text[:first].strip(), b.item
        elif len(later) == 1 and not any(x.item is None for x in bl[k + 1:] if x.section == b.section):
            subject, item = later[0].body.text, later[0].item
        else:
            subject, item = None, None
        subject = subject or b.section       # a motion printed as the item itself, or under a section of its own
        for i, m in enumerate(found):
            end = found[i + 1].start("mover") if i + 1 < len(found) else len(text)
            reasons = list(meeting_reasons)
            mo = read_motion(text, m, end, members, reasons)
            motions.append({"n": len(motions) + 1, "page": b.body.page_at(m.start("mover")), "section": b.section,
                            "item": item, "subject_printed": (subject or "")[:400] or None, **mo,
                            "confirmed": not reasons, "reasons": reasons})
    return {"printed_date": date, "date_mismatch": bool(date and event_date and date != event_date),
            "attendance": {"present": att["present"], "absent": att["absent"], "page": att["page"]},
            "motions": motions, "problems": meeting_reasons}
