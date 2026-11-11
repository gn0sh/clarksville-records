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

Confirmed (written rule, docs/architecture/rpc-motion-invariant.md C1-C5; anything else is shown "Not confirmed",
values held back as for the county's roll calls). Every value is read from the minutes' own words and nothing in the
motion's sentences is left unexplained; any doubt is a reason, in plain words, in `reasons` (never shown publicly):
1. (C1) the motion's case, if any, is a heading read on its own line (a loosely printed heading the reader cannot
   read, "CASE NUMBFR", "C ASE NUMRER", or near a line's start "GASE NUMBER", "Case Numbr", "CASE NO.", "CASE #",
   starts a section of its own whose motions are not confirmed, so they never fall into the case before it), the
   case is on the same meeting's agenda (collector/rpc_agenda.py), its section appears once in the minutes, it is the
   only disposing motion in that section (the meeting's business, CASE_KINDS aside), the motion's sentences name no
   other case number, and the section's text, anywhere, prints no other case on the meeting's agenda (a heading the
   reader missed may have merged two cases' sections). A motion with no case is the meeting's own business
   only (MEETING_BUSINESS: the minutes, electing, adjourning, the consent agenda, the deferrals and withdrawals list),
   before the first case or after an "OTHER BUSINESS" / "PUBLIC COMMENT" / "ADJOURN" heading; any other motion with
   no case is "subject not read";
2. (C2) the mover and the seconder were both read, are different people, and each matches exactly one member present
   in the same minutes' header: a full name equal to a member's name, or "Mr./Mrs./Ms./Dr. Surname" equal to exactly
   one member's surname (case and spacing aside, nothing else forgiven: "Mr. Kinmbrough" matches no one);
   2a. only when the header shows a garbled member line (a line of the members' column that does not read as a clean
   name, "Bill Kimb   h"), a name that matches no member present at all is matched by the same rule against the
   body's roster: the names read cleanly from the headers of the same body's minutes (the CDRB's, or the RPC's
   regular, special and Executive Committee meetings) within a year of the meeting. Two roster names with that
   surname ("Michael Long", "Micheal Long") match no one. A clean header is never second-guessed by the roster;
3. (C3) every member named as voting nay or abstaining is read only after the seconder (so "seconded by Mr. Powers
   and Mrs. Streetman voted nay" names Mrs. Streetman alone), matches a member present by the same rule, and is
   neither the mover nor the seconder. Every vote word (LEFTOVER_VOTE: nay, nav, against, opposed, dissent, recused,
   did not vote, abstain, any form of "vote", voted "no", no vote, not in favor, negative, object, ayes, noes, a
   tally) in the motion's sentences sits inside a nay, abstention, "in favor" or outcome phrase the reader models,
   and none is printed after the outcome up to the next motion or the section's end; "Mr. Long opposed.",
   "Nays: Mr. Long.", 'Mr. Long voted "no".', "Motion passed. Mrs. Streetman thanked staff. Mr. Long voted nay." are
   not read, they are doubts. No other wording the reader does not model is there either: a tie or a vote of the
   chair, members named as voting in favour, "except" a member without a vote word, an amendment, a substitute, a
   reconsideration, a second motion before the outcome. A printed tally ("5-1") agrees with the members named as
   voting nay. Unanimity is never inferred from a missing nay;
4. (C4) one outcome from the fixed vocabulary is printed, ending its sentence, and it does not name another kind of
   motion ("made the motion for disapproval ... Motion for approval passed" is not confirmed). When no outcome
   sentence follows "All others were in favor." / "All members voted in favor.", that sentence is the outcome as
   printed, but only when the rest of its sentence names no exception ("except", "but"), no member and no vote word,
   no member is named as voting nay or abstaining, and no vote word follows it up to the next motion ("All members
   voted in favor, except Cindy Greene who abstained and Bill Kimbrough who voted against." prints no outcome: the
   motion has none and is not confirmed); an outcome sentence ("Motion was approved on the consent agenda.") is
   preferred to the "in favor" sentence before it; a motion that "falls for a lack of a second" has no seconder to read;
5. (C5) the minutes print the meeting's own date (minutes listed under another meeting are not attached to it).
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
# the words of an outcome's "for ..." / "to ...": letters, and a number only as a count of days ("for a 30 day
# deferral"), so a tally ("5-1") is never swallowed into the words and always meets the tally check
OUTCOME_WORDS = r"[a-z](?:[a-z -]|\d{1,3}(?=[\s-]*days?\b)){0,60}?"
OUTCOME = re.compile(r"\b(?:(?:the\s+)?(?:motion|consent\s+agenda|nomination)(?:\s+(?:for|to)\s+" + OUTCOME_WORDS + r")?\s+"
                     r"(?:(?:was\s+)?(?:passed|approved|denied|defeated)|passes|failed|fails|falls|fell|carried|died)"
                     r"(?:\s+unanimously)?(?:\s+on\s+(?:the\s+)?consent\s+agenda)?"
                     r"(?:\s+(?:for|to)\s+" + OUTCOME_WORDS + r")?(?:\s+(?P<tally>\d{1,2}\s*-\s*\d{1,2}))?"
                     r"|(?:carried|approved)\s+unanimously"
                     r"|(?:the\s+)?(?:minutes|deferrals?|withdrawals?)\s+(?:were|was)\s+approved)"
                     r"(?=\s*(?:[.,;]|$|with\b|All\b))", re.I)
# "All others were in favor." / "All members voted in favor." with no outcome sentence after it: that sentence is the
# outcome as printed; "All others voted in favor and the motion passed ..." is the same sentence followed by its
# outcome. FOLLOW_GAP: how far after it an outcome sentence may start and still be the outcome.
FAVOUR = re.compile(r"\ball\s+(?:(?:the\s+)?(?:others|other\s+members|members(?:\s+present)?)\s+)?(?:were|voted|was)\s+in\s+"
                    r"favou?r(?=\s*[.,;]|\s*$|\s+and\s+(?:the\s+)?motion\b)", re.I)
FOLLOW_GAP = 40
# rule 4: words that make an "in favor" sentence a part of the vote, not all of it ("..., except ...", "..., but ...")
FAVOUR_EXCEPT = re.compile(r"\b(?:except|but|save|other\s+than|excluding|apart\s+from|exception|and\s+(?:the\s+)?motion)\b",
                           re.I)
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
# the meeting's own business (rule 1): the only motions confirmed with no case; every other kind disposes of a case
MEETING_BUSINESS = MEETING_KINDS | {"Motion to approve the consent agenda", "Motion to approve the deferrals"}
# an outcome as printed that names the meeting's business it approved ("deferrals were approved")
BUSINESS_OUTCOME = ((re.compile(r"^(?:the\s+)?minutes\s+(?:were|was)\s+approved$", re.I), "Motion to approve the minutes"),
                    (re.compile(r"^(?:the\s+)?(?:deferrals?|withdrawals?)\s+(?:were|was)\s+approved$", re.I),
                     "Motion to approve the deferrals"),
                    (re.compile(r"^(?:the\s+)?consent\s+agenda\s+(?:was\s+)?(?:passed|approved|passes|carried)"
                                r"(?:\s+unanimously)?$", re.I), "Motion to approve the consent agenda"))
# rule 3: a vote word anywhere in the motion's sentences, or after its outcome up to the next motion or the section's
# end, that no modelled nay, abstention, "in favor" or outcome phrase explains. A denylist, so it is wide on purpose:
# any form of "vote" ('voted "no"', "cast the only no vote", "a vote of 5 to 1"), a tally printed outside the outcome,
# "not in favor", "negative", "object", "ayes"/"noes", and the recusal words. Any match is a doubt (under-confirm).
LEFTOVER_VOTE = re.compile(r"\bna[yv]s?\b|against|oppos|dissent|recus|did\s+not\s+vote|abstain|voted\s+no|voting\s+no"
                           r"|\bvot\w*\s+[\"“”'‘’]?\s*no\b|\bno\s+votes?\b|\bvot(?:e|es|ed|ing)\b"
                           r"|not\s+in\s+favou?r|not\s+support|negative|object|disagree|refrain"
                           r"|conflict\s+of\s+interest|\bayes?\b|\bnoes\b"
                           r"|(?<![\w-])\d{1,2}\s*(?:-|to)\s*\d{1,2}(?![\w-])", re.I)
# rule 1: a case heading printed too loosely for CASE_HEAD to read: "CASE NUMBFR", "C ASE NUMRER" anywhere on the
# line, or near the line's start (after an item number) a mangled CASE word, any case, then N... / NO / #:
# "GASE NUMBER", "CASF NUMBER", "Case Numbr", "CASE NO.", "CASE #"
LOOSE_HEAD = re.compile(r"C\s*A\s*S\s*E\s+N\S{3,6}R"
                        r"|^\W{0,4}(?:[\[(]?(?:\d{1,3}|[A-Za-z])\s*[.,)]\s*)?"
                        r"(?i:[CG]\s*[A4]\s*[S5$§]\s*[EF]\s*(?:N\S{0,6}|#))")
# rule 1: a case number in the motion's own sentences
CASE_IN_TEXT = re.compile(r"\b[A-Z]{1,4}\s*-\s*[0-9OIl|]{1,3}[A-Z]?\s*-\s*(?:19|20)\d\d\b")
# rule 1: a case number anywhere in a case section's text, its prefix as printed (read_number repairs a misread
# prefix only onto the meeting's agenda)
CASE_TOKEN = re.compile(r"(?<![A-Za-z0-9§$|])(?P<pre>[A-Za-z0-9§$|]{1,5})\s*-\s*(?P<n>[0-9OIl|]{1,3}[A-Z]?)\s*-\s*"
                        r"(?P<y>(?:19|20)\s?\d\s?\d)(?!\d)")
# the reasons that are doubts about the motion's case (C1): a motion with one of them is placed under no case
WHY_HEAD = "case heading not read"
WHY_NUMBER = "case number not read"
WHY_TWO = "more than one motion on one case section"
WHY_REPEATED = "case section repeated"
WHY_OTHER_CASE = "the motion's sentences name another case number"
WHY_SECTION_OTHER_CASE = "the case section prints another case on this meeting's agenda"
WHY_OFF_AGENDA = "case number not on this meeting's agenda"       # collector/rpc_agenda.read_all_minutes
WHY_SUBJECT = "subject not read"
WHY_VOTE_WORD = "unmodelled wording: a vote word the reader does not read"
WHY_FAVOUR_NOT_OUTCOME = ("no outcome printed: the 'in favor' sentence goes on or members are named as voting nay or "
                          "abstaining")
WHY_NAY_IS_MOVER = "a member named as voting nay is the mover or seconder"
CASE_REASONS = frozenset({WHY_HEAD, WHY_NUMBER, WHY_TWO, WHY_REPEATED, WHY_OTHER_CASE, WHY_SECTION_OTHER_CASE,
                          WHY_OFF_AGENDA, WHY_SUBJECT})
PARA_MAX = 900          # characters a motion's sentences may span before its outcome
# The rules this reader applies (docs/architecture/rpc-motion-invariant.md). rpc_agenda.build writes it into rpc.json
# as `motion_rules`; sitegen/rpc.py and qa/site_checks.py restate it and show every motion of a record without it as
# not confirmed. Change it whenever a rule changes what is confirmed, so an older record is never shown under rules
# it was not read by.
MOTION_RULES = "rpc-motion-invariant-2"


def _clean(line: str) -> str:
    return TRAIL.sub("", LEAD.sub("", line.replace("—", "-").replace("–", "-")))


def _squash(s: str) -> str:
    return " ".join(s.split())


def _key(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.casefold())


# ------------------------------------------------------------------ members present
MEMBER_HEAD = re.compile(r"\bmembers?\s+present\b", re.I)
OTHERS_SAME_LINE = re.compile(r"\b(?:others|staff)\s+present\b|\bstaff\b", re.I)
MEMBERS_STOP = re.compile(r"called\s+(?:the\s+)?meeting\s+to\s+order|meeting\s+was\s+called|\bcall\s+to\s+order|"
                          r"^\s*(?:others\s+present|(?:regional\s+planning\s+)?staff\b|members?\s+absent|absent\b|"
                          r"approval\s+of)", re.I)
MEMBER_NAME = re.compile(r"^(?P<name>[A-Z][a-z'’]+(?:\s+[A-Z]\.)?"
                         r"(?:\s+(?:Mc|Mac|O['’])?[A-Z][a-z'’]+(?:-[A-Z][a-z'’]+)?){1,2})"
                         r"(?:\s*,\s*(?:Vice[\s-]+)?Chair(?:man|woman|person)?|\s*,\s*Secretary)?$")
COLUMN_GAP = 20        # in a two-column header a member's cell starts left of this offset


def members_present(lines: list[str]) -> list[str]:
    """The members present, as printed in the minutes' header (first page or two). Clean names only."""
    return members_header(lines)[0]


def members_header(lines: list[str]) -> tuple[list[str], bool]:
    """(the members present, whether a line of the members' column failed to read as a clean name: rule 2a's
    garbled header line)."""
    out: list[str] = []
    garbled = False
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
            split = not two_col and len(cells) > 1      # one name printed in pieces ("Bill Kimb   h")
            if m and not split and m.group("name") not in out:
                out.append(m.group("name"))             # a line read whole as one clean name only
            # a members' line not read whole as one clean name ("Bill Kimb   h", "Mich@el L0ng"); a heading or a
            # line of marks is not a member's name, so it never opens the roster fallback
            if _name_like(_clean(cell)) and (not m or split):
                garbled = True
        break
    return out, garbled


def _name_like(cell: str) -> bool:
    """A cell that looks like a member's name with a defect: it starts with a capital letter, is mostly letters and
    is not all capitals (a heading such as "PLEDGE OF ALLEGIANCE" is not a name)."""
    chars = [ch for ch in cell if not ch.isspace()]
    return (bool(chars) and cell[:1].isupper() and any(ch.islower() for ch in chars)
            and sum(ch.isalpha() for ch in chars) >= 0.7 * len(chars))


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


def other_cases(text: str, agenda: set[str], prefixes: set[str]) -> list[str | None]:
    """Every case number printed in `text`, each read by read_number (a misread prefix repaired only onto the
    agenda; None when it is not read)."""
    return [read_number(f"{x.group('pre')}-{x.group('n')}-{x.group('y')}", agenda, prefixes)[0]
            for x in CASE_TOKEN.finditer(text)]


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


def _surname(name: str) -> str:
    return _key(_squash(name).split()[-1]) if name and name.split() else ""


def read_motions(text: str, page_at, case: str | None, case_printed: str | None,
                 case_ok: bool, members: list[str], roster=(), case_why: str = WHY_NUMBER) -> list[Motion]:
    """Every motion in one section's text. `page_at(i)` is the page of character i. `case_ok` False: the section's
    case heading was not read (`case_why` says how)."""
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
        # rule 4: the "in favor" sentence stands as the outcome only when the rest of its sentence names no exception,
        # no member and no vote word ("All members voted in favor, except Cindy Greene who abstained and ..." is not
        # one: its first words alone read as unanimous; "All members voted in favor, meeting was adjourned." is)
        rest = window[fav.end():_sentence_end(window, fav.end())] if fav else ""
        fav_goes_on = bool(oc is not None and oc is fav
                           and (FAVOUR_EXCEPT.search(rest) or NAME_RX.search(rest) or LEFTOVER_VOTE.search(rest)))
        para = window[:_sentence_end(window, oc.end())] if oc else window[:400]
        after = para[at:]
        cut = re.search(r",?\s*seconded|\.\s|stating|based|because", after)
        kind = motion_kind(after[:cut.start()] if cut else after[:120])
        if case is None and case_ok and kind in (MOTION_DEFAULT, "Motion for approval") and oc:
            # with no case, "made a motion of approval ... deferrals were approved": the outcome as printed names the
            # meeting's business the motion approved (a fixed label, never the sentence)
            kind = next((label for rx, label in BUSINESS_OUTCOME if rx.search(oc.group(0))), kind)
        own = kind in MEETING_KINDS        # adjourning or electing officers belongs to no case
        mv = Motion(page=page_at(m.start()), case=None if own else case, case_printed=None if own else case_printed,
                    kind=kind, mover=_squash(m.group("mover")), seconder=None, para=_squash(para))
        reasons = mv.reasons
        no_second = bool(oc and LACK_OF_SECOND.search(oc.group(0)))
        sec_matches = list(SECOND_BY.finditer(after)) + list(SECOND_AFTER.finditer(after))
        sb = [_squash(x.group("name")) for x in SECOND_BY.finditer(after)]
        sa = [_squash(x.group("name") or x.group("name2") or x.group("name3")) for x in SECOND_AFTER.finditer(after)]
        seconders = list(dict.fromkeys(sb + sa))
        if len(seconders) == 1:
            mv.seconder = seconders[0]
        elif seconders:
            reasons.append("more than one seconder read")
        if not case_ok and not own:
            reasons.append(case_why)
        if case is None and case_ok and kind not in MEETING_BUSINESS:
            reasons.append(WHY_SUBJECT)     # rule 1: a motion with no case is the meeting's own business only
        if case is not None and not own:    # rule 1: the motion's sentences name no other case number
            if any(link_key(x.group(0)) != case for x in CASE_IN_TEXT.finditer(para)):
                reasons.append(WHY_OTHER_CASE)
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
        modelled: list[tuple[int, int]] = []     # spans of `after` the reader models (rule 3)
        if oc:
            mv.outcome = _squash(oc.group(0))
            modelled.append((oc.start() - at, oc.end() - at))
            tally = oc.groupdict().get("tally")
            mv.tally = re.sub(r"\s", "", tally) if tally else None
            if len(list(OUTCOME.finditer(after))) > 1:
                reasons.append("more than one outcome")
            a, b = _polarity(kind), _polarity(mv.outcome)
            if a and b and a != b:      # "made the motion for disapproval ... Motion for approval passed"
                reasons.append("the outcome names another kind of motion")
        else:
            reasons.append("no outcome read")
        modelled += [(x.start(), x.end()) for x in FAVOUR.finditer(after)]
        # rule 3: nays and abstentions are read only after the seconder, so a seconder joined by "and" to a member
        # voting nay is never read as voting nay
        start = max((x.end() for x in sec_matches), default=0)
        votes = after[start:]
        for rx in NAY:
            for x in rx.finditer(votes):
                modelled.append((start + x.start(), start + x.end()))
                mv.nays += [n for n in _names(x.group("names")) if n not in mv.nays]
        for x in ABSTAIN.finditer(votes):
            modelled.append((start + x.start(), start + x.end()))
            mv.abstained += [n for n in _names(x.group("names")) if n not in mv.abstained]
        # rule 4: an "in favor" sentence is never the outcome when its sentence goes on to an exception, a member or a
        # vote word ("..., except ...", "..., but ..."), when members are named as voting nay or abstaining, or when a
        # vote word follows it up to the next motion ("All members voted in favor. Mr. Long voted against."): with no
        # outcome sentence printed, the motion has no outcome as printed and is not confirmed
        tail = text[m.start() + len(para):nxt]
        if oc is not None and oc is fav and (fav_goes_on or mv.nays or mv.abstained or LEFTOVER_VOTE.search(tail)):
            mv.outcome, mv.tally = None, None
            reasons.append(WHY_FAVOUR_NOT_OUTCOME)
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
        movers = {x for x in (mv.mover_member, mv.seconder_member) if x}
        mover_names = {_surname(x) for x in (mv.mover, mv.seconder) if x}
        for n in mv.nays + mv.abstained:
            if resolve(n, members, roster) in movers or _surname(n) in mover_names:
                reasons.append(WHY_NAY_IS_MOVER)
                break
        # rule 3: every vote word in the motion's sentences sits inside a modelled phrase, and none is printed after
        # its outcome up to the next motion or the section's end ("Motion passed. Mrs. Streetman thanked staff.
        # Mr. Long voted nay."): no character cap, since a cap could only ever confirm more
        scan = after + tail
        if any(not any(a <= x.start() and x.end() <= b for a, b in modelled) for x in LEFTOVER_VOTE.finditer(scan)):
            reasons.append(WHY_VOTE_WORD)
        for why, rx in UNMODELLED:
            if rx.search(scan):
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
    case_heads_printed: int     # every "CASE NUMBER" the text prints (loosely: LOOSE_HEAD lines count)
    case_heads_read: int        # those whose number was read
    sections: list              # [(case, case_printed, page)], one per case heading printed
    header_garbled: bool = False    # rule 2a: a line of the header's members column not read as a clean name


def read_minutes(pages: list[str], agenda: set[str], prefixes: set[str], roster=()) -> MinutesReading:
    """Read one minutes document's page texts (1-based pages). `agenda`: the case numbers on the same meeting's
    agenda; `prefixes`: the case-number prefixes (rpc.yml case_types); `roster`: rule 2a's names, asked only when
    the header shows a garbled member line."""
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
    members, garbled = members_header(plain)
    roster = roster if garbled else ()
    # sections: (line index, case, printed, read, why not read, a case heading?); a section after the cases
    # (OTHER BUSINESS) is (i, None, None, True, None, False)
    heads: list[tuple[int, str | None, str | None, bool, str | None, bool]] = []
    for i, (n, raw) in enumerate(lines):
        c = _clean(raw)
        if SECTION_END.match(c):
            heads.append((i, None, None, True, None, False))
            continue
        hm = CASE_HEAD.match(c)
        lm = None if hm else LINE_CASE.match(c)
        if hm or lm:
            rest = hm.group("rest") if hm else (lm.group("rest") or lm.group("alone"))
            num, printed = read_number(rest, agenda, prefixes)
            if lm and num is None:
                continue          # a line that merely starts with something number-like is not a heading
            heads.append((i, num, printed, num is not None, None if num else WHY_NUMBER, True))
        elif LOOSE_HEAD.search(c):
            # a case heading printed too loosely to read: a section of its own, so its motions never fall into the
            # case before it, and counted as printed
            heads.append((i, None, _squash(c[:40]), False, WHY_HEAD, True))
    case_heads = [h for h in heads if h[5]]
    times: dict[str, int] = {}
    for h in case_heads:
        if h[1]:
            times[h[1]] = times.get(h[1], 0) + 1
    motions: list[Motion] = []
    bounds = [(0, None, None, True, None, False)] + heads
    for k, (i, num, printed, ok, why, is_case) in enumerate(bounds):
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

        got = read_motions(text, page_at, num, printed, ok, members, roster, why or WHY_NUMBER)
        if is_case:
            doubts = []
            if num and times[num] > 1:
                doubts.append(WHY_REPEATED)     # the same case number heads two sections
            if sum(1 for mv in got if mv.kind not in MEETING_BUSINESS) > 1:
                doubts.append(WHY_TWO)          # no "modelled sequence" exception: any doubt
            # another case on this meeting's agenda printed anywhere in the section (not only in a motion's
            # sentences): a heading the reader missed may have merged two cases' sections
            if any(c and c in agenda and c != num for c in other_cases(text, agenda, prefixes)):
                doubts.append(WHY_SECTION_OTHER_CASE)
            for mv in got:
                mv.reasons += [d for d in doubts if d not in mv.reasons]
        motions += got
    return MinutesReading(printed_date, members, motions, len(case_heads), sum(1 for h in case_heads if h[1]),
                          [(h[1], h[2], lines[h[0]][0]) for h in case_heads], garbled)
