"""Zoning case facts: applicant, property location, acreage and from/to zoning, read from the minutes' own text.

A rezoning case (CZ-22-2021) is printed several times in a minutes document: the agenda line ("Application of Mark
Ireland from AG to R-1"), the zoning resolution (its heading, "submitted by ...", "said property is identified as
..., containing .91 acres", "located ...", "the zone classification of the property of ... from AG to R-1 is hereby
approved") and the planning staff's review sheet. The printings and the county's district codes are per-locality
config (config/localities/<locality>/zoning.yml); this module holds only the rule.

The agreement rule (written, the same for every case and field):
1. Every match of a printing's pattern is one reading of each field it names, from one engine: the PDF's text layer
   (the county's own OCR, one engine wherever it appears) or tesseract's reading of the same page.
2. A reading is clean when it is well formed: a name or location of plain characters and a sane length, an acreage
   that is a number, zoning made only of the configured district codes exactly as printed (spaces around a dash
   dropped, nothing else changed) and, where the district's name is printed after its code, that district's name.
   A reading whose pattern matched but whose value fails that check is malformed: it is kept (key MALFORMED) and
   vetoes the field. Nothing is corrected or dropped: a misread is never repaired, and an over-wide pattern is fixed
   in zoning.yml. A group that did not match, or an engine that did not run, gives no reading at all.
3. Readings agree when they are equal after case, spaces and punctuation are ignored (names and locations), as
   numbers (acreage), or code for code (zoning).
4. Independent readings are counted by engine (architecture, "Invariant: independent readings"). A second printing,
   a reprint or the same pages in another document, read by the same engine, repeat that engine's glyph confusions,
   so they never corroborate: on CZ-01-2024 the text layer reads the printed "Johnathan Blick" as "Buck" in two of
   three places.
5. A field takes a value only when clean readings from both engines agree and no reading of any engine, printing or
   document dissents (a clean reading with another key, or a malformed one). One dissent leaves it null; there is
   no majority, ever. With --no-ocr or a failed OCR page there is one engine, so nothing is published from it.
   Readings of every document that cites the case are pooled.
6. The value shown, with its source page: a form both engines read character for character (whitespace collapsed);
   else the characters of the best-ranked reading (mixed case over capitals, "+/-" over its misread "+1-", no odd
   capitals like "BUck") with a word break only where at least one reading of each engine has one. The text layer
   drops spaces and tesseract adds them ("Mc Donald"), so a break only one engine saw is not shown. An acreage
   also keeps its printed form by the same rule (`printed`: "2.320 +/- acres", where the printing wraps the number
   in `acreage_printed`), beside the number, so "+/-", "approximately" and trailing zeros are not lost. The printed
   form is stated only from one printing that both engines read with the same key of the whole form ("+/-" and its
   known misreads one symbol); otherwise `printed` is null and only the number is shown, never as printed. A
   reading whose "+/-" is garbled ("-i-I-") still reads its number, which agrees or vetoes, but gives no printed form.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import parse as P

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ("applicant", "location", "acreage", "from_zoning", "to_zoning")
ENGINES = ("text-layer", "tesseract")
NAME_OK = re.compile(r"[A-Za-z0-9 .,&'’()/-]+")
LOCATION_OK = re.compile(r"[A-Za-z0-9 .,&'’()/#+:-]+")
MALFORMED = "\x00malformed"   # key of a reading whose pattern matched but whose value failed its check


def locality() -> str:
    return yaml.safe_load((ROOT / "config" / "site.yml").read_text(encoding="utf-8"))["locality"]


@dataclass
class Rules:
    case_prefixes: tuple
    districts: dict             # code -> {name keys} (letters only, casefolded)
    printings: list             # [{name, kind, regex, named_districts}]
    resolution_marker: re.Pattern
    resolution_end: re.Pattern
    staff_marker: re.Pattern
    entry_stop: re.Pattern


def _name_key(name: str) -> str:
    return re.sub(r"[^a-z]", "", re.sub(r"\band\b", "&", name.casefold()).replace("&", "and"))


def load_rules(path: Path | None = None) -> Rules | None:
    path = Path(path) if path else ROOT / "config" / "localities" / locality() / "zoning.yml"
    if not path.exists():
        return None
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    printings = [{"name": p["name"], "kind": p["kind"], "named_districts": bool(p.get("named_districts")),
                  "regex": re.compile(p["pattern"], 0 if p.get("case") else re.I)} for p in cfg["printings"]]
    districts = {c: {_name_key(x) for x in ([n] if isinstance(n, str) else n)} for c, n in cfg["districts"].items()}
    return Rules(tuple(cfg["case_prefixes"]), districts, printings,
                 re.compile(cfg["resolution_marker"]), re.compile(cfg["resolution_end"], re.I),
                 re.compile(cfg["staff_marker"], re.I), re.compile(cfg["entry_stop"]))


@dataclass(frozen=True)
class Reading:
    case: str
    field: str
    value: object               # str (applicant, location), float (acreage), tuple of codes (zoning); None if malformed
    shown: str                  # the reading as printed, whitespace collapsed
    key: str
    printing: str
    engine: str
    page: int
    nth: int = 0                # which printing of this kind for this case on this page (pairs the two engines)
    as_printed: bool = True     # acreage: the printed form is well formed (False: a garbled "+/-", number only)


# ---------------------------------------------------------------- values

def _squash(s: str) -> str:
    return " ".join(s.split())


# Glyph rule (written, like parse.VOTE_GLYPHS): the printed "+/-" after a distance or an acreage is read by the text
# layer as "+1-", "+!-", "+l-" or "+I-". In a key every such form is one symbol, so the readings can agree; the value
# shown is a reading that has "+/-" as printed (see _shown_rank). Nothing else in a reading is mapped.
PLUS_MINUS = re.compile(r"\+\s?[1/!lI]\s?-|±|\+/")
# The "+/-" forms an acreage's printed form may carry (the pattern's `acreage_suffix`). The pattern also takes a garbled
# suffix ("1.00 -i-I- acres", CZ-10-2022's text layer) so its number is still a reading that can veto (parse-accuracy/
# narrow-pattern-drops-veto); only that reading's printed form is dropped.
KNOWN_SUFFIX = re.compile(r"\+ ?[/1!lI] ?-|±")


def _text_key(s: str) -> str:
    return re.sub(r"[^a-z0-9&±]", "", PLUS_MINUS.sub("±", s).casefold())


def _applicant(raw: str):
    s = _squash(raw).strip(" ,;:.-")
    s = re.sub(r",? and$", "", s)
    if not (3 <= len(s) <= 150) or not NAME_OK.fullmatch(s) or re.search(r"whereas|resolution|district", s, re.I) \
            or len(re.sub(r"[^A-Za-z]", "", s)) < 3:
        return None
    return s, s, _text_key(s)


def _location(raw: str):
    s = _squash(raw).strip(" ,;:")
    if s.endswith(".") and not re.search(r"\b[A-Z][a-z]{0,3}\.$", s):     # keep the dot of "Ln.", "Rd.", "N."
        s = s.rstrip(".")
    if not (10 <= len(s) <= 300) or not LOCATION_OK.fullmatch(s) or re.search(r"whereas", s, re.I):
        return None
    return s, s, _text_key(s)


def _acreage(raw: str):
    s = raw.replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return None
    if not (0 < v < 100000):
        return None
    return v, raw, repr(round(v, 4))


def _code(tok: str, rules: Rules) -> str | None:
    c = re.sub(r"\s*-\s*", "-", tok.strip())
    return c if c in rules.districts else None


def _zoning(raw: str, rules: Rules, named: bool):
    s = _squash(raw)
    codes = []
    if named:
        # "C-5 Highway & Arterial Commercial District / AG Agricultural", "C-2 - - General Commercial"
        parts = re.split(r"\s+District\s*(?:/|and|&)\s*|\s*/\s*", s)
        for part in parts:
            # the code and the name are split where a configured code (spaces around its dashes allowed) is followed
            # by that district's name, so "C-5 - Highway & Arterial" is not read as the code "C-5-Highway"
            hits = []
            for code, names in rules.districts.items():
                pat = r"\s?-\s?".join(map(re.escape, code.split("-")))
                m = re.fullmatch(pat + r"(?![A-Za-z0-9])\s*(?:[-–—]\s*)*(.*)", part.strip())
                if m and (not m.group(1) or _name_key(m.group(1)) in names):
                    hits.append(code)
            if len(hits) != 1:
                return None
            codes.append(hits[0])
    else:
        for part in s.split("/"):
            code = _code(part, rules)
            if code is None:
                return None
            codes.append(code)
    if not codes:
        return None
    v = tuple(codes)
    return v, s, "/".join(v)


def _value(field: str, raw: str, rules: Rules, named: bool):
    if field == "applicant":
        return _applicant(raw)
    if field == "location":
        return _location(raw)
    if field == "acreage":
        return _acreage(raw)
    return _zoning(raw, rules, named)


# ---------------------------------------------------------------- readings

def page_case(text: str, rules: Rules) -> str | None:
    """The case a resolution or staff page belongs to: the first case number printed on it, when it reads as a valid
    number of a rezoning case prefix."""
    for m in P.ITEM_RE.finditer(text):
        n = P.norm_item(m.group(1))
        if not re.fullmatch(r"[A-Z]{1,3}-\d{1,3}-\d{4}", n):
            continue
        return n if n.split("-")[0] in rules.case_prefixes and P.valid_number(n) else None
    return None


def _match_fields(text: str, pr: dict, rules: Rules, case: str, engine: str, page: int, first: int = 0) -> list[Reading]:
    out = []
    for k, m in enumerate(pr["regex"].finditer(text)):
        gd = m.groupdict()
        for field, raw in gd.items():
            if field not in FIELDS or raw is None:
                continue
            got = _value(field, raw, rules, pr["named_districts"])
            # matched but malformed: kept as a reading that vetoes the field (rule 2), never dropped
            value, shown, key = got if got else (None, _squash(raw), MALFORMED)
            as_printed = True
            if field == "acreage":
                suffix = (gd.get("acreage_suffix") or "").strip()
                as_printed = bool(gd.get("acreage_printed")) and (not suffix or bool(KNOWN_SUFFIX.fullmatch(suffix)))
                if got and as_printed:
                    shown = _squash(gd["acreage_printed"])    # "2.320 +/- acres", "approximately .91 acres"
            out.append(Reading(case, field, value, shown, key, pr["name"], engine, page, first + k, as_printed))
    return out


def _entries(lines: list[str], rules: Rules):
    """(case, entry text, line index) for each listing line that starts with a rezoning case number."""
    i = 0
    while i < len(lines):
        m = re.match(r"\s*(\S{5,12}?)\*?\s+(\S.*)$", lines[i])
        if m and P.ITEM_RE.fullmatch(m.group(1)):
            n = P.norm_item(m.group(1))
            parts = [m.group(2)]
            j = i + 1
            while j < len(lines) and re.match(r"\s{6,}\S", lines[j]):
                t = lines[j].strip()
                if P.ITEM_RE.match(t.split(" ")[0].rstrip("*")) or rules.entry_stop.match(t):
                    break
                parts.append(t)
                j += 1
            if n.split("-")[0] in rules.case_prefixes and P.valid_number(n):
                yield n, _squash(" ".join(parts)), i
            i = j
            continue
        i += 1


def page_readings(pages: list[str], rules: Rules, engine: str = "text-layer",
                  only: set[int] | None = None) -> list[Reading]:
    """Every reading on the given pages (1-based page numbers in `only`, else all)."""
    out: list[Reading] = []
    entry_pr = [p for p in rules.printings if p["kind"] == "entry"]
    res_pr = [p for p in rules.printings if p["kind"] == "resolution"]
    staff_pr = [p for p in rules.printings if p["kind"] == "staff"]
    for k, text in enumerate(pages):
        pg = k + 1
        if only is not None and pg not in only:
            continue
        seen: dict[str, int] = {}
        for case, entry, _ in _entries(text.splitlines(), rules):
            for pr in entry_pr:
                out += _match_fields(entry, pr, rules, case, engine, pg, seen.get(case, 0))
            seen[case] = seen.get(case, 0) + 1
        if rules.resolution_marker.search(text):
            case = page_case(text, rules)
            if case:
                body = text
                if not rules.resolution_end.search(text) and k + 1 < len(pages) and page_case(pages[k + 1], rules) in (None, case):
                    body = text + "\n" + pages[k + 1]        # the resolution runs onto the next page
                for pr in res_pr:
                    out += _match_fields(_squash(body), pr, rules, case, engine, pg)
        if rules.staff_marker.search(text):
            case = page_case(text, rules)
            if case:
                for pr in staff_pr:
                    out += _match_fields(_squash(text), pr, rules, case, engine, pg)
    return out


def candidate_pages(pages: list[str], rules: Rules) -> set[int]:
    """Pages that can carry readings: a second engine reads only these."""
    out = set()
    for k, text in enumerate(pages):
        if rules.resolution_marker.search(text) or rules.staff_marker.search(text) or \
                any(True for _ in _entries(text.splitlines(), rules)):
            out.add(k + 1)
    return out


# ---------------------------------------------------------------- the agreement rule

def _shown_rank(r: Reading) -> tuple:
    s = r.shown if isinstance(r.shown, str) else str(r.shown)
    odd = len(re.findall(r"\b[A-Z]{2,}[a-z]", s))                      # "BUck": a misread capital
    misread = len(re.findall(r"\+\s?[1!lI]\s?-", s))                    # "+1-" for the printed "+/-"
    return (s != s.upper() or not re.search(r"[A-Za-z]", s), -misread, -odd, r.engine == "text-layer")


def _units(s: str) -> tuple[list[tuple[int, int]], set[int]]:
    """The spans of s that make up its key (_text_key: a letter, digit, "&", or one "+/-" form) and the set of unit
    positions k > 0 with whitespace between unit k-1 and unit k (a word break)."""
    spans, breaks, i, gap = [], set(), 0, False
    while i < len(s):
        m = PLUS_MINUS.match(s, i)
        j = m.end() if m else i + 1
        if m or re.fullmatch(r"[a-z0-9&]", s[i].casefold()):
            if gap and spans:
                breaks.add(len(spans))
            spans.append((i, j))
            gap = False
        elif s[i].isspace():
            gap = True
        i = j
    return spans, breaks


def _with_breaks(s: str, allowed: set[int]) -> str:
    """s with its own whitespace removed and one space put before each key unit in `allowed`: where s had a space in
    that gap, there; else just before the unit."""
    spans, _ = _units(s)
    out, prev = [], 0
    for k, (a, b) in enumerate(spans):
        gap = s[prev:a]
        if k > 0 and k in allowed:
            ws = re.search(r"\s", gap)
            gap = re.sub(r"\s+", "", gap[:ws.start()]) + " " + re.sub(r"\s+", "", gap[ws.start():]) if ws else \
                re.sub(r"\s+", "", gap) + " "
        elif k > 0:
            gap = re.sub(r"\s+", "", gap)
        out += [gap, s[a:b]]
        prev = b
    return "".join(out) + s[prev:]


def _order(x) -> tuple:
    return tuple(-v for v in _shown_rank(x[0])), x[2], x[0].page, x[1]


def _shown(g: list):
    """(shown form, the reading that supplies the page) among agreeing readings g (rule 6)."""
    forms: dict[str, set] = {}
    for r, _, _ in g:
        forms.setdefault(_squash(str(r.shown)), set()).add(r.engine)
    both = [x for x in g if forms[_squash(str(x[0].shown))] >= set(ENGINES)]
    if both:
        best = min(both, key=_order)
        return _squash(str(best[0].shown)), best
    best = min(g, key=_order)
    s = _squash(str(best[0].shown))
    n = len(_units(s)[0])
    per_engine = {e: set() for e in ENGINES}
    for r, _, _ in g:
        spans, breaks = _units(_squash(str(r.shown)))
        if len(spans) == n:                          # letters align by position (equal keys)
            per_engine[r.engine] |= breaks
    return _with_breaks(s, set.intersection(*per_engine.values())), best


def decide(readings: list) -> dict:
    """readings: [(Reading, source_id, date)] for one case -> {field: {"value", "source_id", "page"} | None}.
    Rules 4-6: clean readings from both engines with one key and no dissent, or null."""
    out = {}
    for field in FIELDS:
        g = [x for x in readings if x[0].field == field]
        keys = {x[0].key for x in g}
        if len(keys) != 1 or MALFORMED in keys or not set(ENGINES) <= {x[0].engine for x in g}:
            out[field] = None
            continue
        shown, (r, sid, _) = _shown(g)
        value = list(r.value) if isinstance(r.value, tuple) else (shown if isinstance(r.value, str) else r.value)
        out[field] = {"value": value, "source_id": sid, "page": r.page}
        if field == "acreage":                          # the number as printed, with its words (rule 6)
            got = _printed(g)
            if got is None:     # no printing both engines read alike: the number only, never an "as printed" form
                out[field] = {"value": value, "printed": None, "source_id": sid, "page": r.page}
            else:
                printed, (pr, psid, _) = got
                out[field] = {"value": value, "printed": printed, "source_id": psid, "page": pr.page}
    return out


def _printed(g: list):
    """(printed form, the reading that supplies its page) of an acreage, or None (rule 6). The printed form is stated
    only from one printing (one document, page, printing and match) that both engines read with one _text_key of the
    printed form ("+/-" and its misreads one symbol), no reading of that printing reads another, and none has a
    garbled "+/-" (Reading.as_printed). The shown form
    pools every such printing with that same key (the shown-form rule, as for any agreeing readings); among the keys,
    the best-ranked reading's. The number's agreement alone never makes its words stated
    (provenance/acreage-printed-uncorroborated)."""
    by: dict[tuple, list] = {}
    for x in g:
        r, sid, _ = x
        by.setdefault((sid, r.page, r.printing, r.nth), []).append(x)
    forms: dict[str, list] = {}
    for grp in by.values():
        keys = {_text_key(str(x[0].shown)) for x in grp}
        if {x[0].engine for x in grp} >= set(ENGINES) and len(keys) == 1 and all(x[0].as_printed for x in grp):
            forms.setdefault(keys.pop(), []).extend(grp)
    cands = [_shown(grp) for grp in forms.values()]
    return min(cands, key=lambda c: _order(c[1])) if cands else None
