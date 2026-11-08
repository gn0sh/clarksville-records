"""Zoning case facts: applicant, property location, acreage and from/to zoning, read from the minutes' own text.

A rezoning case (CZ-22-2021) is printed several times in a minutes document: the agenda line ("Application of Mark
Ireland from AG to R-1"), the zoning resolution (its heading, "submitted by ...", "said property is identified as
..., containing .91 acres", "located ...", "the zone classification of the property of ... from AG to R-1 is hereby
approved") and the planning staff's review sheet. The printings and the county's district codes are per-locality
config (config/localities/<locality>/zoning.yml); this module holds only the rule.

The agreement rule (written, the same for every case and field):
1. Every match of a printing's pattern is one reading of each field it names, from one engine: the PDF's text layer,
   or tesseract's reading of the same page (a second, independent reading).
2. A reading counts only if it is well formed: a name or location of plain characters and a sane length, an acreage
   that is a number, zoning made only of the configured district codes exactly as printed (spaces around a dash
   dropped, nothing else changed) and, where the district's name is printed after its code, that district's name.
   Nothing is corrected: a misread is dropped, never repaired.
3. Readings agree when they are equal after case, spaces and punctuation are ignored (names and locations), as
   numbers (acreage), or code for code (zoning).
4. Independent readings are counted by (printing, engine): the same printing in two documents (an agenda packet and
   the minutes carry the same pages) counts once, so a misprint copied into both never agrees with itself.
5. One printing read by both engines with different results was misread by one of them: that printing counts
   neither for nor against any value, and the other printings decide. A printing only one engine read counts as is.
6. A field takes a value only when every remaining reading agrees and they are at least two independent readings.
   Any dissent leaves it null: on CZ-01-2024 the text layer reads the printed "Johnathan Blick" as "Buck" in two of
   three places, so a majority would have published the wrong name. Readings of every document that cites the
   case are pooled.
7. The value shown is one of the agreeing readings as printed (mixed case over capitals, "+/-" over its misread
   "+1-", then the one with the most word breaks, since the text layer drops spaces but never adds them), with its
   source page.
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
MIN_AGREE = 2


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
    value: object               # str (applicant, location), float (acreage), tuple of codes (zoning)
    shown: str                  # the reading as printed, whitespace collapsed
    key: str
    printing: str
    engine: str
    page: int
    nth: int = 0                # which printing of this kind for this case on this page (pairs the two engines)


# ---------------------------------------------------------------- values

def _squash(s: str) -> str:
    return " ".join(s.split())


# Glyph rule (written, like parse.VOTE_GLYPHS): the printed "+/-" after a distance or an acreage is read by the text
# layer as "+1-", "+!-", "+l-" or "+I-". In a key every such form is one symbol, so the readings can agree; the value
# shown is a reading that has "+/-" as printed (see _shown_rank). Nothing else in a reading is mapped.
PLUS_MINUS = re.compile(r"\+\s?[1/!lI]\s?-|±|\+/")


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
            m = re.fullmatch(r"([A-Z][A-Za-z0-9]*(?:\s?-\s?[A-Za-z0-9]+)*)\s*(?:[-–—]\s*)*(.*)", part.strip())
            if not m:
                return None
            code = _code(m.group(1), rules)
            if code is None or (m.group(2) and _name_key(m.group(2)) not in rules.districts[code]):
                return None
            codes.append(code)
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
        for field, raw in m.groupdict().items():
            if field not in FIELDS or raw is None:
                continue
            got = _value(field, raw, rules, pr["named_districts"])
            if got:
                value, shown, key = got
                out.append(Reading(case, field, value, shown, key, pr["name"], engine, page, first + k))
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
    return (s != s.upper() or not re.search(r"[A-Za-z]", s), -misread, -odd, s.count(" "), r.engine == "text-layer")


def decide(readings: list) -> dict:
    """readings: [(Reading, source_id, date)] for one case -> {field: {"value", "source_id", "page"} | None}."""
    out = {}
    for field in FIELDS:
        # rule 5a: one printing read by both engines with different results is a misread by one of them; that
        # printing then counts neither way (the other printings decide). A printing only one engine read counts as is.
        printings: dict[tuple, list] = {}
        for x in readings:
            r = x[0]
            if r.field == field:
                printings.setdefault((r.printing, x[1], r.page, r.nth), []).append(x)
        groups: dict[str, list] = {}
        for xs in printings.values():
            if len({x[0].engine for x in xs}) > 1 and len({x[0].key for x in xs}) > 1:
                continue
            for x in xs:
                groups.setdefault(x[0].key, []).append(x)
        units = {k: {(r.printing, r.engine) for r, _, _ in g} for k, g in groups.items()}
        if len(groups) != 1 or len(units[next(iter(groups))]) < MIN_AGREE:
            out[field] = None
            continue
        g = next(iter(groups.values()))
        best = min(g, key=lambda x: (tuple(-v for v in _shown_rank(x[0])), x[2], x[0].page, x[1]))
        r, sid, _ = best
        value = list(r.value) if isinstance(r.value, tuple) else r.value
        out[field] = {"value": value, "source_id": sid, "page": r.page}
    return out
