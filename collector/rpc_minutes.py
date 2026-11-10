"""Regional Planning Commission minutes: the motions on each case, as printed (milestone RPC-2).

83 of the 88 RPC minutes are image scans with no text layer. Their pages are read by the same OCR path the county
minutes use (collector/ocr.py: pdftoppm at 300 dpi, tesseract --psm 6, one page per process, its timeouts and its
cache); a minutes document with a full text layer is read from that layer. An OCR failure on any page leaves the
whole document unread and reported, never half read.

What is read (the minutes' own words, nothing summarised or reworded):
- the members present, from the minutes' own header ("Members Present ... Others Present" in two columns, or a
  "MEMBERS PRESENT:" list): only lines that read as a clean name ("Wade Hadley", "Richard Swift, Chairman");
- each case section: a line that starts "CASE NUMBER" (with or without an item number), or a case number alone at
  the start of a line (CDRB minutes: "DDR-14-2026"). The section runs to the next case or the end of the document;
- each motion: "Mr. Hadley made the motion for approval ... Mr. Powers seconded. Mrs. Streetman voted nay. All
  others were in favor. Motion passed.", "Bill Kimbrough made a motion for approval ..., seconded by Eric Huneycutt.
  All members voted in favor, except Stacey Streetman who voted against. Motion passes for approval 5-1." or
  "Mrs. Streetman moved to recommend approval. The motion was seconded by Mr. Kimbrough and carried unanimously.":
  the mover and seconder as printed, the motion's type from a fixed list (MOTION_KINDS, never the sentence), the
  outcome as printed (from a fixed vocabulary, OUTCOME) and every member named as voting nay or abstaining.

Case numbers (written rule, the same repair parse.norm_item applies to the county's case numbers): spaces around the
dashes are dropped and in the number part l, I and | read as 1, O as 0; the zero padding goes ("CZ-07-2024" is
CZ-7-2024). A prefix misread by OCR ("2-16-2022" for Z-16-2022, "§S-25-2025" for S-25-2025) is read as the agenda's
case only when that one change (PREFIX_GLYPHS) gives a case number printed on the same meeting's agenda; otherwise
the case number is not read, and its motions are shown as not confirmed. A number is never guessed.

Confirmed (written rule; anything else is shown "Not confirmed", values held back as for the county's roll calls):
1. the motion is under a case whose number was read, or is the minutes' own business: before the first case, after
   an "OTHER BUSINESS" / "PUBLIC COMMENT" / "ADJOURN" heading, or a motion to approve the minutes, elect or adjourn;
2. the mover and the seconder were both read, are different people, and each matches exactly one member present in
   the same minutes' header: a full name equal to a member's name, or "Mr./Mrs./Ms./Dr. Surname" equal to exactly one
   member's surname (case and spacing aside, nothing else forgiven: "Mr. Kinmbrough" matches no one);
   2a. a name that matches no member present at all (an OCR-garbled header line, "Bill Kimb   h") is matched by the
   same rule against the body's roster: the names read cleanly from the headers of the same body's minutes (the
   CDRB's, or the RPC's regular, special and Executive Committee meetings) within a year of the meeting. Two roster
   names with that surname ("Michael Long", "Micheal Long") match no one;
3. every member named as voting nay or abstaining matches a member present by the same rule;
4. one outcome from the fixed vocabulary is printed, ending its sentence, and it does not name another kind of motion
   ("made the motion for disapproval ... Motion for approval passed" is not confirmed). When no outcome sentence
   follows "All others were in favor." / "All members voted in favor.", that sentence is the outcome as printed; a
   motion that "falls for a lack of a second" has no seconder to read;
5. no wording the reader does not model is in the motion's sentences: a tie or a vote of the chair, members named
   as voting in favour, "except" a member without a vote word, an amendment, a substitute, a reconsideration, a
   second motion before the outcome;
6. a printed tally ("5-1") agrees with the members named as voting nay;
7. the minutes print the meeting's own date (minutes listed under another meeting are not attached to it).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import parse as P
from .rpc_agenda import case_number, iso_date

# OCR border marks at the start or end of a scanned line ("|", ":", "‘", "~", "»")
LEAD = re.compile(r"^[\s|:;!'‘’`~»«*•.,_—-]+(?=\S)")
TRAIL = re.compile(r"[\s|:;!‘’`~»«_—-]+$")
FOOTER = re.compile(r"^\s*(?:RPC\s+Meeting\s+Minutes\b.*|CMCRPC\s+MEETING\s+MINUTES.*|\d{1,3})\s*$", re.I)

HON = r"(?:(?:Mr|Mrs|Ms|Dr)\.?|Commissioners?|(?:Vice[\s-]+)?Chair(?:man|woman|person)?)"
SURNAME = r"(?:Mc|Mac|O['’])?[A-Z][a-z'’]+(?:-[A-Z][a-z'’]+)?"
NAME = (rf"(?:{HON}\s*{SURNAME}"
        rf"|[A-Z][a-z'’]+(?:\s+[A-Z]\.)?\s+{SURNAME})")
NAMES = rf"{NAME}(?:\s*,\s*{NAME})*(?:\s*,?\s+(?:and|&)\s+{NAME})?"
NAME_RX = re.compile(NAME)

# A case section starts at "CASE NUMBER" (any item number or letter before it) or at a case number that starts a line
CASE_HEAD = re.compile(r"^(?:[\[(]?(?:\d{1,3}|[A-Za-z])\s*[.,)]\s*)?CASE\s*N[UO]MBERS?\s*[:;.]?\s*(?P<rest>.*)$", re.I)
# a case number heading with no "CASE NUMBER": alone on its line (CDRB minutes: "DDR-14-2026"), or after an item
# number ("3. Z-5-2026 ..."). A line that merely starts with a case number ("SR-44-2024, SR-59-2024, and appeal ...",
# a list of deferrals wrapped onto a new line) is not a heading.
LINE_CASE = re.compile(r"^(?:\d{1,3}\s*\.\s+(?P<rest>[A-Z]{1,4}\s*-\s*[0-9OIl|]{1,3}[A-Z]?\s*-\s*20\d\d)\b(?!\s*,)"
                       r"|(?P<alone>[A-Z]{1,4}\s*-\s*[0-9OIl|]{1,3}[A-Z]?\s*-\s*20\d\d)\s*[:.]?\s*$)")
NUMBER = re.compile(r"^(?P<pre>[^\s\d-]{0,2}[A-Z]{0,4}|\d[A-Z]?)\s*-\s*(?P<n>[0-9OIl|]{1,3}[A-Z]?)\s*-\s*"
                    r"(?P<y>(?:19|20)\s?\d\s?\d)(?!\d)")
# Prefix misreads seen on the scans (each used only when it gives a case on the meeting's agenda): Z read as 2 or 7,
# S read as $ or 5 or with a stray mark ("§S", "$S", "S$"), SR as "5R"
PREFIX_GLYPHS = {"2": "Z", "7": "Z", "§S": "S", "$S": "S", "S$": "S", "§": "S", "$": "S", "5": "S", "5R": "SR"}

MOTION_START = re.compile(rf"(?P<mover>{NAME})\s+(?:(?:made|makes)\s+(?:the|a)\s+motion\b"
                          rf"|moved\b(?!\s+(?:forward|to\s+the)))")
SECOND_BY = re.compile(rf"\b[Ss]econded\s+by\s+(?P<name>{NAME})")
SECOND_AFTER = re.compile(rf"(?P<name>{NAME})\s+seconded\b|\bwith\s+(?P<name2>{NAME})\s+second\b|"
                          rf"\bsecond\s+from\s+(?P<name3>{NAME})")
OUTCOME = re.compile(r"\b(?:(?:the\s+)?(?:motion|consent\s+agenda|nomination)(?:\s+(?:for|to)\s+[a-z][a-z -]{0,60}?)?\s+"
                     r"(?:(?:was\s+)?(?:passed|approved|denied|defeated)|passes|failed|fails|falls|fell|carried|died)"
                     r"(?:\s+unanimously)?"
                     r"(?:\s+(?:for|to)\s+[a-z][a-z -]{0,60}?)?(?:\s+(?P<tally>\d{1,2}\s*-\s*\d{1,2}))?"
                     r"|(?:carried|approved)\s+unanimously"
                     r"|(?:the\s+)?(?:minutes|deferrals?|withdrawals?)\s+(?:were|was)\s+approved)"
                     r"(?=\s*(?:[.,;]|$|with\b|All\b))", re.I)
# "All others were in favor." / "All members voted in favor." with no outcome sentence after it: that sentence is the
# outcome as printed. FOLLOW_GAP: how far after it an outcome sentence may start and still be the outcome.
FAVOUR = re.compile(r"\ball\s+(?:(?:the\s+)?(?:others|other\s+members|members(?:\s+present)?)\s+)?(?:were|voted|was)\s+in\s+"
                    r"favou?r(?=\s*[.,;]|\s*$)", re.I)
FOLLOW_GAP = 40
LACK_OF_SECOND = re.compile(r"\black\s+of\s+(?:a\s+)?second\b", re.I)
# A section of the minutes after the cases ("OTHER BUSINESS:", "A. MONTHLY PROFIT AND LOSS", "ADJOURN"): its motions
# belong to no case
SECTION_END = re.compile(r"^(?:[A-Z]\s*[.)]\s*|[IVX]{1,4}\s*[.)]\s*)?(?:OTHER\s+BUSINESS|NEW\s+BUSINESS|OLD\s+BUSINESS|"
                         r"PUBLIC\s+COMMENT|ADJOURN|EXECUTIVE\s+SESSION)\b", re.I)
NAY = (re.compile(rf"(?P<names>{NAMES})\s+(?:voted|voting|votes)\s+(?:nay|no|against|in\s+opposition|in\s+disapproval)\b"),
       # "except Cindy Greene who abstained and Bill Kimbrough who voted against"
       re.compile(rf"(?P<names>{NAMES})\s*,?\s+who\s+(?:(?:voted|votes)\s+(?:against|nay|no|in\s+opposition)|"
                  rf"(?:was|were)\s+(?:against|opposed))\b"),
       re.compile(rf"(?P<names>{NAMES})\s+(?:were|was)\s+(?:in\s+opposition|opposed)\b"))
ABSTAIN = re.compile(rf"(?P<names>{NAMES})\s*,?\s+(?:who\s+)?abstain(?:ed|s)?\b")
UNMODELLED = (("a tie or a vote of the chair", re.compile(r"\btie\b|\bbroke\b", re.I)),
              ("members named as voting in favour", re.compile(rf"{NAME}\s+(?:were|was|voted)\s+in\s+favou?r\b")),
              ("'except' a member with no vote word",
               re.compile(rf"\bexcept\s+(?:for\s+)?{NAME}\b(?!\s*(?:,?\s+(?:and|&)\s+{NAME})?\s*,?\s+who\s+"
                          rf"(?:vote|abstain|was\s+against|were\s+against))")),
              ("an amendment, substitute or reconsideration",
               re.compile(r"\bamend|\bsubstitut|\breconsider|\brescind|\bearlier\s+made\s+motion", re.I)))
# The motion's type in plain words: the first pattern that matches the words right after "motion" / "moved" (up to the
# seconder or the sentence end) gives a fixed label. Never any part of the sentence.
MOTION_KINDS = (
    (r"consent\s+agenda", "Motion to approve the consent agenda"),
    (r"\bminutes\b", "Motion to approve the minutes"),
    (r"\bapprov\w*\s+(?:the\s+|all\s+)?(?:deferrals?|withdrawals?)", "Motion to approve the deferrals"),
    (r"\bdisapprov|\bden(?:y|ial)\b", "Motion for disapproval"),
    (r"\bdefer", "Motion to defer"),
    (r"\bwithdraw", "Motion to withdraw"),
    (r"\bapprov|\brecommend", "Motion for approval"),
    (r"\belect\b|\bnominat", "Motion to elect"),
    (r"\badjourn", "Motion to adjourn"),
)
MOTION_DEFAULT = "Motion"
MEETING_KINDS = {"Motion to elect", "Motion to adjourn", "Motion to approve the minutes"}
PARA_MAX = 900          # characters a motion's sentences may span before its outcome


def _clean(line: str) -> str:
    return TRAIL.sub("", LEAD.sub("", line.replace("—", "-").replace("–", "-")))


def _squash(s: str) -> str:
    return " ".join(s.split())


def _key(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.casefold())


# ------------------------------------------------------------------ members present
MEMBER_HEAD = re.compile(r"\bmembers?\s+present\b", re.I)
OTHERS_SAME_LINE = re.compile(r"\b(?:others|staff)\s+present\b|\bstaff\b", re.I)
MEMBERS_STOP = re.compile(r"called\s+(?:the\s+)?meeting\s+to\s+order|meeting\s+was\s+called|^\s*(?:others\s+present|"
                          r"(?:regional\s+planning\s+)?staff\b|members?\s+absent|absent\b|approval\s+of)", re.I)
MEMBER_NAME = re.compile(r"^(?P<name>[A-Z][a-z'’]+(?:\s+[A-Z]\.)?"
                         r"(?:\s+(?:Mc|Mac|O['’])?[A-Z][a-z'’]+(?:-[A-Z][a-z'’]+)?){1,2})"
                         r"(?:\s*,\s*(?:Vice[\s-]+)?Chair(?:man|woman|person)?|\s*,\s*Secretary)?$")
COLUMN_GAP = 20        # in a two-column header a member's cell starts left of this offset


def members_present(lines: list[str]) -> list[str]:
    """The members present, as printed in the minutes' header (first page or two). Clean names only."""
    out: list[str] = []
    for i, line in enumerate(lines[:80]):
        if not MEMBER_HEAD.search(line):
            continue
        two_col = bool(OTHERS_SAME_LINE.search(line[MEMBER_HEAD.search(line).end():]))
        for raw in lines[i + 1:i + 40]:
            if MEMBERS_STOP.search(raw):
                break
            if not raw.strip():
                continue
            cells = [(m.start(), m.group(0).strip()) for m in re.finditer(r"\S+(?: \S+)*", raw)]
            start, cell = cells[0]
            if two_col and start >= COLUMN_GAP:
                continue          # a line of the "Others Present" column only
            m = MEMBER_NAME.match(_clean(cell))
            if m and m.group("name") not in out:
                out.append(m.group("name"))
        break
    return out


def resolve(printed: str, members: list[str], roster=()) -> str | None:
    """The one member present a printed name stands for (rule 2), or None. When no member present matches at all
    (an OCR-garbled header line), the body's roster is asked by the same rule (rule 2a)."""
    p = _squash(printed)
    hm = re.match(rf"^{HON}\s*(?P<s>\S+)$", p)

    def hits(names):
        if hm:
            return [m for m in names if _key(m.split()[-1]) == _key(hm.group("s"))]
        return [m for m in names if _key(m) == _key(p)]

    own = hits(members)
    if not own and roster:
        own = hits(roster)
    return own[0] if len(own) == 1 else None


# ------------------------------------------------------------------ case numbers
def read_number(rest: str, agenda: set[str], prefixes: set[str]) -> tuple[str | None, str]:
    """(case number or None, the characters read) from the text after "CASE NUMBER" (module rule)."""
    m = NUMBER.match(rest.strip())
    if not m:
        return None, _squash(rest[:24])
    printed = _squash(m.group(0))
    y = re.sub(r"\s", "", m.group("y"))
    pre = m.group("pre")
    n = m.group("n").replace("|", "1")
    if pre in prefixes:
        c = link_key(f"{pre}-{n}-{y}")
        # read as printed (only the parse.py glyph rule applied): kept even when the agenda did not list it
        return (c, printed) if c else (None, printed)
    fixed = PREFIX_GLYPHS.get(pre)
    if fixed is None and re.fullmatch(r"[^A-Z\d]{1,2}[A-Z]{1,4}", pre or "") and pre.lstrip("§$|!'‘") in prefixes:
        fixed = pre.lstrip("§$|!'‘")
    c = link_key(f"{fixed}-{n}-{y}") if fixed else None
    return (c, printed) if c and c in agenda else (None, printed)


def link_key(number: str) -> str | None:
    """A case number in its one comparable form, or None when it is not one: parse.norm_item's glyph rule for the
    number part (l, I as 1, O as 0, spaces dropped), then no zero padding ("CZ-07-2024" -> "CZ-7-2024"). The same key
    links an RPC case to a County Commission item (sitegen/rpc.py)."""
    s = P.norm_item(number or "")
    m = re.fullmatch(r"([A-Z]{1,4})-(\d{1,3}[A-Z]?)-((?:19|20)\d\d)", s)
    return case_number(*m.groups()) if m else None


# ------------------------------------------------------------------ motions
@dataclass
class Motion:
    page: int
    case: str | None
    case_printed: str | None
    kind: str
    mover: str | None
    seconder: str | None
    mover_member: str | None = None
    seconder_member: str | None = None
    nays: list = field(default_factory=list)
    abstained: list = field(default_factory=list)
    outcome: str | None = None
    tally: str | None = None
    reasons: list = field(default_factory=list)
    para: str = ""              # the sentences read (OCR text: internal, never shown or exported)

    @property
    def confirmed(self) -> bool:
        return not self.reasons


def motion_kind(words: str) -> str:
    for pattern, label in MOTION_KINDS:
        if re.search(pattern, words, re.I):
            return label
    return MOTION_DEFAULT


def _polarity(text: str) -> str | None:
    """approve / disapprove / defer, as a motion's type or an outcome names it ("Motion passes to approve the
    deferrals" approves), or None when it names none."""
    t = text.lower()
    if re.search(r"disapprov|\bden(?:y|ial|ied)\b", t):
        return "disapprove"
    if re.search(r"approv\w*\s+(?:the\s+|all\s+)?(?:deferrals?|withdrawals?|consent)|consent\s+agenda|deferrals|"
                 r"withdrawals", t):     # the list of deferrals and withdrawals is approved as one
        return "approve"
    if "defer" in t:
        return "defer"
    if "approv" in t:
        return "approve"
    return None


def _names(s: str) -> list[str]:
    return [_squash(m.group(0)) for m in NAME_RX.finditer(s)]


def _sentence_end(text: str, i: int) -> int:
    """The end of the sentence running at i: the next '.' not part of an honorific or an initial."""
    for m in re.finditer(r"\.", text[i:]):
        j = i + m.start()
        before = text[max(0, j - 4):j]
        if re.search(r"(?:\bMrs?|\bMs|\bDr|\b[A-Z])$", before):
            continue
        return j + 1
    return len(text)


def read_motions(text: str, page_at, case: str | None, case_printed: str | None,
                 case_ok: bool, members: list[str], roster=()) -> list[Motion]:
    """Every motion in one section's text. `page_at(i)` is the page of character i."""
    out = []
    found = list(MOTION_START.finditer(text))
    for k, m in enumerate(found):
        nxt = found[k + 1].start() if k + 1 < len(found) else len(text)
        window = text[m.start():min(nxt, m.start() + PARA_MAX)]
        at = m.end() - m.start()
        oc = OUTCOME.search(window, at)
        fav = FAVOUR.search(window, at)
        # the vote sentence is the outcome as printed when no outcome sentence follows it straight away
        if fav and (oc is None or oc.start() - _sentence_end(window, fav.end()) > FOLLOW_GAP):
            oc = fav
        para = window[:_sentence_end(window, oc.end())] if oc else window[:400]
        after = para[at:]
        cut = re.search(r",?\s*seconded|\.\s|stating|based|because", after)
        kind = motion_kind(after[:cut.start()] if cut else after[:120])
        own = kind in MEETING_KINDS        # adjourning or electing officers belongs to no case
        mv = Motion(page=page_at(m.start()), case=None if own else case, case_printed=None if own else case_printed,
                    kind=kind, mover=_squash(m.group("mover")), seconder=None, para=_squash(para))
        reasons = mv.reasons
        no_second = bool(oc and LACK_OF_SECOND.search(oc.group(0)))
        sb = [_squash(x.group("name")) for x in SECOND_BY.finditer(after)]
        sa = [_squash(x.group("name") or x.group("name2") or x.group("name3")) for x in SECOND_AFTER.finditer(after)]
        seconders = list(dict.fromkeys(sb + sa))
        if len(seconders) == 1:
            mv.seconder = seconders[0]
        elif seconders:
            reasons.append("more than one seconder read")
        if not case_ok and not own:
            reasons.append("case number not read")
        mv.mover_member = resolve(mv.mover, members, roster)
        if mv.mover_member is None:
            reasons.append("mover is not one member present")
        if mv.seconder is None:
            if not no_second:      # "Motion falls for a lack of a second": none is printed, as it says
                reasons.append("no seconder read")
        elif no_second:
            reasons.append("a seconder read for a motion that died for lack of a second")
        else:
            mv.seconder_member = resolve(mv.seconder, members, roster)
            if mv.seconder_member is None:
                reasons.append("seconder is not one member present")
            elif mv.seconder_member == mv.mover_member:
                reasons.append("mover and seconder are the same")
        if oc:
            mv.outcome = _squash(oc.group(0))
            tally = oc.groupdict().get("tally")
            mv.tally = re.sub(r"\s", "", tally) if tally else None
            if len(list(OUTCOME.finditer(after))) > 1:
                reasons.append("more than one outcome")
            a, b = _polarity(kind), _polarity(mv.outcome)
            if a and b and a != b:      # "made the motion for disapproval ... Motion for approval passed"
                reasons.append("the outcome names another kind of motion")
        else:
            reasons.append("no outcome read")
        for rx in NAY:
            for x in rx.finditer(after):
                mv.nays += [n for n in _names(x.group("names")) if n not in mv.nays]
        for x in ABSTAIN.finditer(after):
            mv.abstained += [n for n in _names(x.group("names")) if n not in mv.abstained]
        # every member named after "except" in the vote sentence is read as voting nay or abstaining
        for x in re.finditer(r"\bexcept\b", after):
            named = _names(after[x.end():_sentence_end(after, x.end())])
            if any(n not in mv.nays + mv.abstained for n in named):
                reasons.append("a member named after 'except' is not read as voting nay or abstaining")
                break
        for n in mv.nays + mv.abstained:
            if resolve(n, members, roster) is None:
                reasons.append("a member named as voting nay or abstaining is not one member present")
                break
        for why, rx in UNMODELLED:
            if rx.search(after):
                reasons.append(f"unmodelled wording: {why}")
        if mv.tally:
            a, b = (int(x) for x in mv.tally.split("-"))
            if b != len(mv.nays):
                reasons.append("the printed tally does not match the members named as voting nay")
        out.append(mv)
    return out


@dataclass
class MinutesReading:
    printed_date: dict | None
    members: list
    motions: list
    case_heads_printed: int     # every "CASE NUMBER" the text prints (loosely)
    case_heads_read: int        # those whose number was read
    sections: list              # [(case, case_printed, page)]


def read_minutes(pages: list[str], agenda: set[str], prefixes: set[str], roster=()) -> MinutesReading:
    """Read one minutes document's page texts (1-based pages). `agenda`: the case numbers on the same meeting's
    agenda; `prefixes`: the case-number prefixes (rpc.yml case_types)."""
    lines: list[tuple[int, str]] = []
    for n, p in enumerate(pages, 1):
        for raw in p.splitlines():
            if not raw.strip() or FOOTER.match(_clean(raw)):
                continue
            lines.append((n, raw))
    plain = [raw for _, raw in lines]
    printed_date = None
    for n, raw in lines[:20]:
        d = iso_date(raw)
        if d:
            printed_date = {"date": d, "printed": _squash(_clean(raw)), "page": n}
            break
    members = members_present(plain)
    # sections
    # (line index, case, printed, read); a section after the cases (OTHER BUSINESS) is (i, None, None, True)
    heads: list[tuple[int, str | None, str | None, bool]] = []
    for i, (n, raw) in enumerate(lines):
        c = _clean(raw)
        if SECTION_END.match(c):
            heads.append((i, None, None, True))
            continue
        hm = CASE_HEAD.match(c)
        lm = None if hm else LINE_CASE.match(c)
        if hm or lm:
            rest = hm.group("rest") if hm else (lm.group("rest") or lm.group("alone"))
            num, printed = read_number(rest, agenda, prefixes)
            if lm and num is None:
                continue          # a line that merely starts with something number-like is not a heading
            heads.append((i, num, printed, num is not None))
    case_heads = [h for h in heads if h[2] is not None or not h[3]]
    motions: list[Motion] = []
    bounds = [(0, None, None, True)] + heads
    for k, (i, num, printed, ok) in enumerate(bounds):
        j = bounds[k + 1][0] if k + 1 < len(bounds) else len(lines)
        sec = lines[i:j]
        text, offs = "", []
        for n, raw in sec:
            offs.append((len(text), n))
            text += _clean(raw) + " "

        def page_at(pos, offs=offs):
            pg = offs[0][1] if offs else 1
            for o, n in offs:
                if o > pos:
                    break
                pg = n
            return pg

        motions += read_motions(text, page_at, num, printed, ok, members, roster)
    return MinutesReading(printed_date, members, motions, len(case_heads), sum(1 for h in case_heads if h[1]),
                          [(h[1], h[2], lines[h[0]][0]) for h in case_heads])
