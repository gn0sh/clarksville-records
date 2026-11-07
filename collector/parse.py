"""Deterministic parser for Montgomery County Commission minutes (text layer).

Input: list of page texts (pdftotext -layout). Output: meeting attendance and roll calls,
each roll call checked per spec P2 and marked Verified or Unverified with reasons.
No LLM calls; all rules are written down here so they apply identically to every official (G2).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from difflib import SequenceMatcher

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


DATE_RE = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})\s*[,.]?\s*(\d{4})", re.I)


def _int(s: str) -> int | None:
    s = s.strip()
    for a_, b_ in (("O", "0"), ("o", "0"), ("Q", "0"), ("D", "0"), ("I", "1"), ("l", "1")):
        s = s.replace(a_, b_)
    return int(s) if s.isdigit() else None


def parse_attendance(pages: list[str]) -> Attendance | None:
    """The meeting's own header: the first 'BE IT REMEMBERED' page (page 1 in all samples)."""
    for pno, text in enumerate(pages[:3], 1):
        if not re.search(r"BE\s+IT\s+REMEMBERED", text, re.I):
            continue
        reasons: list[str] = []
        m = DATE_RE.search(text[text.upper().find("REMEMBERED"):])
        date = None
        if m:
            date = f"{m.group(3)}-{MONTHS.index(m.group(1).lower()) + 1:02d}-{int(m.group(2)):02d}"
        lines = text.splitlines()
        start = next((i for i, l in enumerate(lines) if re.search(r"\w*ssioners\s*:\s*$", l, re.I)), None)
        pidx = next((i for i, l in enumerate(lines) if re.match(r"\s*PRESENT\s*:", l)), None)
        if start is None or pidx is None:
            return Attendance(date, pno, [], [], None, None, [], False, ["header layout not recognised"])
        present = []
        for l in lines[start + 1:pidx]:
            for cell in re.split(r"\s{2,}", l.strip()):
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
        else:
            reasons.append("ABSENT line not found")
        vacant = re.findall(r"VACANT\s*:\s*(.+)", rest)
        if present_count is None or present_count != len(present):
            reasons.append(f"PRESENT count {present_count} != {len(present)} names read")
        if absent_count is not None and absent_count != len(absent):
            reasons.append(f"ABSENT count {absent_count} != {len(absent)} names read")
        return Attendance(date, pno, present, absent, present_count, absent_count,
                          [v.strip() for v in vacant], not reasons, reasons)
    return None


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


# ---------------------------------------------------------------- roll calls

VOTE_TOKENS = {"y": "Yes", "n": "No", "a": "Abstain"}
ABSENT_MARK = re.compile(r"^[-—–_]{2,}$")
DISTRICT_LIKE = re.compile(r"^([0-9Iil|!]{1,2}|is|IS|S|O)$")
EDGE_NOISE = ",.;:'‘’`~|[](){}!\"“”*•=«»"
# Glyph rule (written, applies to every cell): a token made only of one letter's look-alikes is that
# letter, e.g. "¥", "YY", "Y¥" (tesseract reads the scanned Y this way). Mixed letters stay unknown.
VOTE_GLYPHS = {"y": set("Yy¥"), "n": set("Nn"), "a": set("Aa")}
TABLE_HEAD = re.compile(r"District\s+Commissioner\s+Vote", re.I)
TALLY = re.compile(r"Yes\w*\s*[^\w\n]*\s*(\w{1,3})\s*No\w*\s*[^\w\n]*\s*(\w{1,3})\s*Abst\w*\s*[^\w\n]*\s*(\w{1,3})",
                   re.I)
ITEM_RE = re.compile(r"(?<![\w-])(\d{2}\s?[-~_—–]\s?[\dIlO]{1,2}\s?[-~_—–]\s?[\dIlO]{1,2}"   # 24-12-1
                     r"|[A-Z]{1,3}\s?-\s?\d{1,3}\s?-\s?\d{4})(?![\w-])")                       # AB-4-2024
# outcome word: the one at most two lowercase words before "by the following roll call"
OUTCOME_RE = re.compile(r"((?i:Adopted|Approved|Failed|Defeated|Denied|Amended|Deferred|Withdrawn|Postponed"
                        r"|Tabled|Elected|Suspended))"
                        r"(?:\s+[^\sA-Z]\S*){0,2}\s+by\s+the\s+f\S{4,8}\s+(?i:roll\s+call)", re.S)
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


def parse_table_rows(rows: list[str], roster: list[str]) -> tuple[list[Cell], list[str]]:
    cells: list[Cell] = []
    problems: list[str] = []
    for row in rows:
        chunks = chunk_row(row)
        for ci, ch in enumerate(chunks):
            kind, val = classify_token(ch)
            if kind == "unknown" and ci + 1 < len(chunks) and classify_token(chunks[ci + 1])[0] == "name":
                continue                       # district position (just before a name): "‘J", "]"
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
    assign_names(cells, roster)
    return cells, problems


ASSIGN_MIN = 0.75       # 'Jerry Allbert' vs 'Randy Allbert' scores 0.70: two people, never paired


def assign_names(cells: list[Cell], roster: list[str]) -> None:
    """Written merge rule (G2): the table lists each roster member once, so OCR'd table names are
    matched to roster names one-to-one, best pairs first. A pair below ASSIGN_MIN is not matched
    (the roll call then fails P2). A cell whose best roster name is already taken is not matched."""
    todo = [c for c in cells if c.member is None]
    pairs = sorted(((name_similarity(c.raw_name, r), i, r) for i, c in enumerate(todo) for r in roster),
                   reverse=True)
    used_cells, used_names = set(), set()
    for score, i, r in pairs:
        if i in used_cells or r in used_names:
            continue
        if score < ASSIGN_MIN:
            break
        todo[i].member, todo[i].score = r, score
        used_cells.add(i)
        used_names.add(r)
    holder = {c.member: c for c in todo if c.member}
    for c in todo:
        if not c.member:
            continue
        for r in roster:
            if r != c.member and name_similarity(c.raw_name, r) > c.score and holder.get(r) \
                    and holder[r].score < 0.9:
                c.member = None          # its closest roster name went to another weak match
                break
    for i, c in enumerate(todo):
        if i not in used_cells:
            c.score = max((name_similarity(c.raw_name, r) for r in roster), default=0.0)


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


def _lines_with_pages(pages: list[str]) -> tuple[list[str], list[int]]:
    lines, page_of = [], []
    for pno, t in enumerate(pages, 1):
        for l in t.splitlines():
            lines.append(l)
            page_of.append(pno)
    return lines, page_of


def table_heads(lines: list[str]) -> list[int]:
    return [i for i, l in enumerate(lines) if TABLE_HEAD.search(l)]


def read_table(lines: list[str], h: int, nxt: int, roster: list[str], source: str) -> tuple[Reading, int]:
    """Read the vote table whose header is lines[h]; nxt bounds the search. Returns the reading
    and the index of the last line used."""
    reasons: list[str] = []
    tally_i = next((j for j in range(h + 1, min(nxt, h + 16)) if TALLY.search(lines[j])), None)
    rows_end = tally_i if tally_i is not None else min(nxt, h + 10)
    rows = [l for l in lines[h + 1:rows_end] if l.strip() and not l.startswith("=====")]
    tally = None
    if tally_i is None:
        reasons.append("stated tally not found")
    else:
        g = TALLY.search(lines[tally_i]).groups()
        vals = tuple(_int(x) for x in g)
        if None in vals:
            reasons.append(f"tally unreadable {g}")
        else:
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
    cells, problems = parse_table_rows(rows, roster)
    reasons.extend(problems)
    votes = cells_to_votes(cells, roster, reasons)
    check_votes(votes, set(absent), tally, roster, reasons)
    return Reading(source, votes, tally, sorted(set(absent)), reasons), last


def cells_to_votes(cells: list[Cell], roster: list[str], reasons: list[str]) -> dict:
    votes: dict[str, str] = {}
    seen: dict[str, int] = {}
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
    for m, n in seen.items():
        if n > 1:
            reasons.append(f"matched {n} times: {m}")
    missing = [r for r in roster if r not in seen]
    if missing:
        reasons.append(f"roster members not found in table: {missing}")
    return votes


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


def check_outcome(outcome_word: str | None, tally: tuple | None) -> list[str]:
    if not tally:
        return []
    oc = _outcome_class(outcome_word)
    if oc is None:
        return [f"outcome not stated or not recognised ({outcome_word})"]
    passes = tally[0] > tally[1] and tally[0] >= FULL_BODY // 2 + 1
    if (oc == "pass") != passes:
        return [f"outcome {outcome_word} disagrees with tally {tally}"]
    return []


def disagreements(a: Reading, b: Reading) -> list[str]:
    """Members for whom two readings both read a Yes/No/Abstain and they differ."""
    out = []
    for m in set(a.votes) & set(b.votes):
        va, vb = a.votes[m], b.votes[m]
        if va in ("Yes", "No", "Abstain") and vb in ("Yes", "No", "Abstain") and va != vb:
            out.append(f"sources disagree for {m}: {a.source}={va} {b.source}={vb}")
    if a.tally and b.tally and a.tally != b.tally:
        out.append(f"sources disagree on stated tally: {a.tally} vs {b.tally}")
    return out


def decide(rc: "RollCall") -> None:
    """Verified when the context checks pass, at least one reading passes P2, and no two readings
    disagree on any vote. The passing reading supplies the votes."""
    good = [r for r in rc.readings if not r.reasons]
    conflicts = []
    for i in range(len(rc.readings)):
        for j in range(i + 1, len(rc.readings)):
            conflicts += disagreements(rc.readings[i], rc.readings[j])
    reasons = list(rc.context_reasons) + conflicts
    if good:
        best = good[0]
        reasons += check_outcome(rc.outcome_text, best.tally)
    else:
        best = rc.readings[0]
        for r in rc.readings:
            reasons += [f"[{r.source}] {x}" for x in r.reasons]
    rc.votes, rc.tally, rc.absent = best.votes, best.tally, best.absent
    rc.verified_by = best.source if good else None
    rc.reasons = reasons
    rc.status = "Verified" if good and not reasons else "Unverified"


def find_rollcalls(pages: list[str], source: str, att: Attendance | None,
                   titles: dict | None = None) -> list[RollCall]:
    lines, page_of = _lines_with_pages(pages)
    spans = embedded_spans(lines)
    roster = (att.present + att.absent) if att else []
    titles = titles or {}
    heads = table_heads(lines)
    out: list[RollCall] = []
    prev_end = 0
    for hi, h in enumerate(heads):
        nxt = heads[hi + 1] if hi + 1 < len(heads) else len(lines)
        reading, last = read_table(lines, h, nxt, roster, "text-layer")
        ctx_reasons: list[str] = []
        ctx_start = max(prev_end, h - 40)
        ctx = " ".join(" ".join(lines[ctx_start:h]).split())
        om = None
        for om in OUTCOME_RE.finditer(ctx):
            pass
        outcome_word = om.group(1) if om else None
        motions = list(MOTION_RE.finditer(ctx))
        mot = motions[-1] if motions else None
        kind = "resolution"
        if re.search(r"foregoing\s+Amendment", ctx[-400:], re.I):
            kind = "amendment"
        elif re.search(r"Consent\s+Agenda\s+items", ctx[-400:], re.I):
            kind = "consent"
        elif re.search(r"Rules\s+were\s+Suspended|Suspend\s+the\s+Rules\s+\w+\s+by", ctx[-400:], re.I):
            kind = "suspend-rules"
        elif re.search(r"Motion\s+to\s+(Table|Postpone|Defer)\w*\s+(was|were)\s+\w+\s+by", ctx[-400:], re.I):
            kind = "procedural"
        elif re.search(r"Nominations[^.]{0,80}(Approved|Adopted)\s+by", ctx[-400:], re.I):
            kind = "nominations"
        elif re.search(r"Minutes[^.]{0,200}(Approved|Adopted)", ctx[-400:], re.I):
            kind = "minutes"
        item = None
        if kind == "consent":
            item = "Consent Agenda"
        else:
            for j in range(h - 1, ctx_start - 1, -1):
                ims = ITEM_RE.findall(lines[j])
                if ims:
                    item = norm_item(ims[0])
                    break
            # the vote on the resolution right after its amendment vote carries no number of its own
            if item is None and out and out[-1].kind == "amendment" and h - prev_end < 12:
                item = out[-1].item
        if not roster:
            ctx_reasons.append("no roster for this meeting")
        if att is None or not att.verified:
            ctx_reasons.append("meeting attendance header not verified")
        if any(a <= h < b for a, b in spans):
            ctx_reasons.append("inside an earlier meeting's attached minutes")
        mover = seconder = None
        if mot:
            mover = resolve_commissioner(mot.group(2), roster)
            seconder = resolve_commissioner(mot.group(3), roster)
        rc = RollCall(source=source, meeting_date=att.date if att else None, page=page_of[h],
                      end_page=page_of[min(len(lines) - 1, last)], line=h,
                      item=item, item_title=titles.get(item) if item else None, kind=kind,
                      outcome_text=outcome_word,
                      motion=(mot.group(1) or "") if mot else None, mover=mover, seconder=seconder,
                      votes={}, tally=None, absent=[])
        rc.ordinal_on_page = sum(1 for x in heads[:hi] if page_of[x] == page_of[h])
        rc.context_reasons = ctx_reasons
        rc.readings = [reading]
        decide(rc)
        out.append(rc)
        prev_end = last + 1
    return out


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
