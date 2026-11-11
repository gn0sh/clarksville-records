"""Regional Planning Commission agendas: the case items and the upcoming hearing dates, as printed (milestone RPC-1).

An RPC agenda (text PDF, e.g. https://www.cmcrpc.com/wp2025/wp-content/uploads/2026/10/Agenda-10.27.2026.pdf) lists
each case as a numbered paragraph:

    1. Z - 19 - 2026 OWNER(S): ... REQUEST: ... LOCATION: ... TAX MAP(S): ... CO. COMM. DISTRICT: 1
    CITY COUNCIL WARD: 11 NUMBER OF ACRES: 134.02 +/- ...

grouped under "CASE TYPE: CITY ZONING" (COUNTY ZONING, SUBDIVISION(S), SITE REVIEW(S)) headings, and a section
"UPCOMING ZONING MEETINGS DATES/TIMES" lists the Council and Commission hearing dates. Every value is the document's
own words with whitespace joined; nothing is summarised or reworded, and a field that is not printed is left empty.
Each case keeps the PDF page its number is printed on, so the site links straight to it.

2022-2024 agendas also print a case as "CASE NUMBER: SR-7-2022 ..." with its item number on a line of its own before
or after it, or with none. Every "CASE NUMBER:" line starts a case, and the build's completeness check reports any
agenda that prints "CASE NUMBER:" more often than cases were read from it (summary case_shortfalls; `python -m
collector rpc build` exits 1; qa.site_checks rpc-cases fails). The letters of a DRAFT watermark, each printed on a
line of its own, are skipped.

A scanned agenda (no text layer: 22 CDRB agendas) is read by OCR (ocr_document, the county minutes' OCR path) and
then by the same reader; the completeness check applies to it too. The minutes are read for motions by
collector/rpc_minutes.py (RPC-2). Numbered case lines ("1. Z - 19 - 2026") count in the completeness check as well.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .extract import MIN_CHARS_PER_PAGE, extract_pages

# A case starts at its number: a numbered agenda paragraph "1. Z - 19 - 2026", "12. S - 44 - 2026",
# "7. ZO - 2A - 2026", 2025 agendas "1.   CASE NUMBER: Z - 29 - 2025", or a "CASE NUMBER:" line with no item number
# on it (2022-2024: the number is on a line of its own before or after it, or not printed at all; a variance section
# may letter it "I. CASE NUMBER: V-1-2023."). Group 1 the agenda's item number (None when not on the line), 2 the
# prefix, 3 the case's number, 4 the year.
ITEM = re.compile(r"^\s*(?:(\d{1,3})\s*\.\s+(?:CASE\s+NUMBER\s*:\s*)?|(?:[IVX]{1,5}\s*\.\s+)?CASE\s+NUMBER\s*:\s*)"
                  r"([A-Z]{1,4})\s*-\s*([0-9]{1,3}[A-Z]?)\s*-\s*((?:19|20)\d\d)\b")
# Every printed "CASE NUMBER:", loosely (anywhere on a line, any number after it): the completeness check counts
# these against the cases read, so a case the reader misses is reported, never dropped silently.
CASE_NUMBER_LOOSE = re.compile(r"CASE\s+NUMBER\s*:", re.I)
# An item number on a line of its own ("5.", 2022 "4.   *****"): the next case's, or the current case's when it
# follows that case's unnumbered "CASE NUMBER:" line. TRAILING_ITEM: "10. REQUEST: ..." under such a line.
LONE_ITEM = re.compile(r"^\s*(\d{1,3})\s*\.\s*(?:\*{5,})?\s*$")
TRAILING_ITEM = re.compile(r"^\s*(\d{1,3})\s*\.\s+(?=[A-Z][A-Z .#()/]*:)")
# Every numbered case line ("1. Z - 19 - 2026", "12. SR-4..."), loosely: also counted against the cases read, so a
# numbered case whose number the reader cannot parse is reported too (code review 2026-11-10).
NUMBERED_LOOSE = re.compile(r"^\s*\d+\.\s+[A-Z]{1,4}\s*-\s*\d", re.M)
# The letters of a DRAFT watermark, each on a line of its own ("T", "AF", "R", "D"), 2022-2024 agendas. Only one or
# two letters of D, R, A, F, T, and never a zoning district code (config/localities/<county>/zoning.yml districts):
# a district printed alone on a line inside a case ("AG") is case text, not a watermark.
WATERMARK = re.compile(r"^\s*([DRAFT]{1,2})\s*$")


def _zoning_codes() -> frozenset:
    import yaml
    from .zoning import ROOT as _ROOT, locality
    p = _ROOT / "config" / "localities" / locality() / "zoning.yml"
    if not p.exists():
        return frozenset()
    return frozenset(str(c).upper() for c in (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("districts", {}))


ZONING_CODES = _zoning_codes()


def is_watermark(line: str) -> bool:
    m = WATERMARK.match(line)
    return bool(m) and m.group(1) not in ZONING_CODES
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
CASE_TYPE = re.compile(r"^\s*CASE\s+TYPE\s*:\s*(.+?)\s*$", re.I)
# The agenda's own section headings ("V. REGULAR AGENDA ITEMS: ...", "VII. OTHER BUSINESS"): a case ends at one.
SECTION = re.compile(r"^\s*(?:[IVX]{1,5})\s*\.\s+([A-Z][A-Z /&'-]+)")
# "REGULAR AGENDA ITEM(S): ..." printed without a numeral (2025 agendas)
PART = re.compile(r"^\s*(REGULAR|CONSENT)\s+AGENDA\b")
PAGE_NO = re.compile(r"^\s*\d{1,3}\s*$")
FOOTER = re.compile(r"^\s*[A-Z][A-Z &]{2,30}\s+-\s+\d{1,3}\s*$")          # 2022-2023: "ZONING - 1", "SUBDIVISION - 2"
RULE = re.compile(r"^\s*\*{5,}\s*$")                                       # 2022-2023: a line of asterisks ends a case
NOTE = re.compile(r"^\s{20,}((?:RECOMMENDED|DEFERRED|WITHDRAWN|POSTPONED)\b[A-Z ,/-]*)\s*$")
INLINE_NOTE = re.compile(r"^(.*?\S)\s{8,}((?:RECOMMENDED FOR DEFF?ERR?AL|DEFERRED|WITHDRAWN|POSTPONED))\s*$")
# Field labels as the agendas print them, every spelling seen 2022-2026 (longest first within a field). The value is
# the text up to the next label. A text layer sometimes splits a word ("APPLIC ANT/OWNER", "LOC ATION"), so one space is
# allowed between the letters of a label word.
LABELS = (
    ("applicant_owner", ("APPLICANT/OWNER:",)), ("owner", ("OWNER(S):", "OWNER(S)", "OWNER:")),
    ("applicant", ("APPLICANT(S):", "APPLICANT:", "APPLICANT", "APPLICATION OF:")),   # 2025: "APPLICANT Name"; CDRB
    ("agent", ("AGENT:",)), ("variance_request", ("VARIANCES REQUESTED:", "VARIANCE(S) REQUESTED:", "VARIANCE REQUEST:")),
    ("reason", ("REASON FOR THE REQUEST:", "REASON FOR REQUEST:")), ("request", ("REQUEST:",)),
    ("development", ("DEVELOPMENT:",)),
    ("location", ("LOCATION OF REQUEST:", "LOCATION:")), ("tax_map", ("TAX MAP(S):", "MAP:")),
    ("parcel", ("PARCEL #(S):", "PARCEL#:", "PARCEL:")), ("district", ("CO. COMM. DISTRICT:",)),
    ("ward", ("CITY COUNCIL WARD:",)), ("acres", ("NUMBER OF ACRES:", "ACREAGE:")),
    ("growth_plan", ("GROWTH PLAN AREA:", "GROWTH PLAN:")), ("civil_district", ("CIVIL DISTRICT(S):", "CIVIL DISTRICT:")),
    ("proposed_use", ("PROPOSED USE:",)), ("zoning", ("ZONING:",)), ("lots", ("# OF LOTS:",)),
    ("units", ("# OF UNITS:",)), ("sq_footage", ("SQ. FOOTAGE:", "SQ FOOTAGE:")),
)


def _label_rx(printed: str) -> str:
    """"APPLICANT/OWNER:" -> a pattern: letters of a word may have one space between them, other tokens any space."""
    toks = re.findall(r"[A-Z]+|\S", printed)
    rx = r"\s*".join(r"\s?".join(re.escape(ch) for ch in t) if t.isalpha() else re.escape(t) for t in toks)
    return r"(?<![A-Za-z])" + rx + (r"\b" if printed[-1].isalpha() else "")


LABEL_RX = re.compile("|".join(f"(?P<{k}>{'|'.join(_label_rx(v) for v in vs)})" for k, vs in LABELS))
HEARINGS = re.compile(r"UPCOMING\s+(?:ZONING\s+)?MEETINGS?\b", re.I)
# "1. CITY COUNCIL INFORMAL October 29, 2026 @ 4:30 P.M." (the 2026-07-28 agenda numbers them V. to VIII.)
HEARING_LINE = re.compile(r"^\s*(?:\d{1,2}|[IVX]{1,5})\s*\.\s+(.+?)\s*$")
# 2022-2023: "IV. CITY ZONING CASES: CITY COUNCIL INFORMAL: 10/27/2022 - 4:30 P.M." (two to a line, before the cases)
NUM_HEARING = re.compile(r"((?:CITY\s+COUNCIL|COUNTY\s+COMMISSION)[A-Z &]*?)\s*:\s*(\d{1,2})/(\d{1,2})/((?:19|20)\d\d)"
                         r"\s*-\s*(\d{1,2}:\d\d\s*[AP]\.?\s?M\.?)")
MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"), 1)}
DATE_WORDS = re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
                        r"\s+(\d{1,2})\s*,?\s*((?:19|20)\d\d)\b", re.I)
WARD_VALUE = re.compile(r"^\s*(\d{1,2})\b")


def _join(lines: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def iso_date(text: str) -> str | None:
    """The first written date ("October 29, 2026") in text as YYYY-MM-DD, or None."""
    m = DATE_WORDS.search(text or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))).isoformat()
    except ValueError:
        return None


def case_number(prefix: str, num: str, year: str) -> str:
    """"Z - 05 - 2024" -> "Z-5-2024": the number without zero padding, so the same case matches across documents."""
    n = num.lstrip("0") or "0"
    return f"{prefix}-{n}-{year}"


def fields(text: str) -> dict[str, str]:
    """{field: value} for every label printed in the case's text, in the document's words. A label printed twice keeps
    the first value."""
    out: dict[str, str] = {}
    marks = [(m.start(), m.end(), m.lastgroup) for m in LABEL_RX.finditer(text)]
    for i, (s, e, k) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        v = text[e:end].strip(" ;,")
        if k not in out:
            out[k] = v
    return out


def text_layer(pages: list[str]) -> str:
    good = sum(1 for p in pages if len(p.strip()) >= MIN_CHARS_PER_PAGE)
    return "none" if not good else "text" if good == len(pages) else "partial"


def parse_pages(pages: list[str]) -> dict:
    """{printed_date, hearings: [{printed, date, page}], cases: [...], case_numbers_printed, case_numbers_read} from an
    agenda's page texts (1-based pages). For the completeness check (build): case_numbers_printed is the loose count of
    "CASE NUMBER:" in the text, case_numbers_read the cases read from a "CASE NUMBER:" line."""
    # a text layer's control characters (a symbol-font bullet "\x14" before "CASE NUMBER:", "LOCATION:\x03East") are
    # spaces
    lines = [(n, CONTROL.sub(" ", line)) for n, p in enumerate(pages, 1) for line in p.splitlines()]
    printed_date = None
    for n, line in lines[:15]:
        d = iso_date(line)
        if d:
            printed_date = {"date": d, "printed": line.strip(), "page": n}
            break
    hearings, cases = [], []
    case_type = agenda_part = None
    cur = None
    # An item number printed on a line of its own, waiting for its case: (item, lines printed between them). Those
    # lines belong to that case (2022: "2." / "APPLICANT/OWNER: ..." / rule / "CASE NUMBER: S-99-2022"), never to
    # the case before; they are dropped if a heading comes first.
    pending = None
    in_hearings = False
    labelled = numbered = 0

    def close():
        nonlocal cur
        if cur is not None:
            body = _join(cur.pop("_lines"))
            # a "CASE NUMBER:" left in the body is a case whose number could not be read: its text (AGENT, WARD...)
            # is cut off so it is never credited to this case; the completeness check reports the missing case
            loose = CASE_NUMBER_LOOSE.search(body)
            if loose:
                body = body[:loose.start()].rstrip()
            cur["text"] = body
            cur["fields"] = fields(body)
            cases.append(cur)
        cur = None

    def add(line: str):
        nm = NOTE.match(line)
        if nm:
            cur["note"] = _join([nm.group(1)])
            return
        im = INLINE_NOTE.match(line)   # "REQUEST: C-5 ... District          DEFERRED" (2022)
        if im:
            cur["note"] = _join([im.group(2)])
            line = im.group(1)
        cur["_lines"].append(line)

    for n, line in lines:
        if PAGE_NO.match(line) or FOOTER.match(line) or is_watermark(line) or not line.strip():
            continue
        lone = LONE_ITEM.match(line)
        if lone:
            if cur is not None and cur["item"] is None and len(cur["_lines"]) <= 2:
                cur["item"] = int(lone.group(1))   # "CASE NUMBER: CZ - 07 - 2024 ..." / " 8." (2024-10-29)
            else:
                close()
                pending = (int(lone.group(1)), [])
            continue
        if RULE.match(line):
            if cur is not None and len(cur["_lines"]) > 1:   # a rule right under the number line (2022) does not end it
                close()
            continue
        if cur is None and not cases:
            for hm in NUM_HEARING.finditer(line):
                try:
                    d = date(int(hm.group(4)), int(hm.group(2)), int(hm.group(3))).isoformat()
                except ValueError:
                    continue
                hearings.append({"printed": _join([hm.group(0)]), "date": d, "page": n})
        if HEARINGS.search(line):
            in_hearings = True
            continue
        it = ITEM.match(line)
        sec = None if it else SECTION.match(line)    # "I. CASE NUMBER: V-1-2023." is a case, not a heading
        part = PART.match(line)
        ct = CASE_TYPE.match(line)
        if in_hearings:
            hm = HEARING_LINE.match(line)
            if hm and not it and iso_date(hm.group(1)):
                hearings.append({"printed": _join([hm.group(1)]), "date": iso_date(hm.group(1)), "page": n})
                continue
            if sec or ct or it or part:
                in_hearings = False
        if ct:
            close()
            pending = None
            case_type = _join([ct.group(1)])
            continue
        if part and not sec:
            close()
            pending = None
            agenda_part = "Regular agenda" if part.group(1) == "REGULAR" else "Consent agenda"
            continue
        if sec:
            close()
            pending = None
            word = sec.group(1).upper()
            agenda_part = ("Regular agenda" if "REGULAR" in word else "Consent agenda" if "CONSENT" in word
                           else agenda_part)
            if "REGULAR" not in word and "CONSENT" not in word:
                case_type = agenda_part = None   # e.g. OTHER BUSINESS: later numbered lines are not cases
            continue
        if it:
            close()
            if CASE_NUMBER_LOOSE.search(line[:it.start(2)]):
                labelled += 1
            elif it.group(1) and NUMBERED_LOOSE.match(line):
                numbered += 1
            item = int(it.group(1)) if it.group(1) else pending[0] if pending else None
            before = pending[1] if pending else []
            pending = None
            cur = {"item": item, "prefix": it.group(2),
                   "number": case_number(it.group(2), it.group(3), it.group(4)),
                   "number_printed": _join([line[it.start(2):it.end(4)]]),
                   "case_type": case_type, "agenda_part": agenda_part, "page": n, "note": None, "_lines": []}
            for b in before:
                add(b)
            cur["_lines"].append(line[it.end(4):])
            continue
        if pending is not None:
            pending[1].append(line)
            continue
        if cur is not None:
            tm = TRAILING_ITEM.match(line)
            if tm and cur["item"] is None and len(cur["_lines"]) <= 2:
                cur["item"] = int(tm.group(1))   # "CASE NUMBER: Z-28-2022 ..." / "10. REQUEST: ..." (2022-04-26)
                line = line[tm.end():]
            add(line)
    close()
    loose = sum(len(CASE_NUMBER_LOOSE.findall(p)) for p in pages)
    numbered_loose = sum(1 for _, line in lines if NUMBERED_LOOSE.match(line))
    return {"printed_date": printed_date, "hearings": hearings, "cases": cases,
            "case_numbers_printed": loose + numbered_loose, "case_numbers_read": labelled + numbered,
            "numbered_printed": numbered_loose, "numbered_read": numbered}


OTHER_CASE = "Other case"


def case_record(c: dict, meeting_id: str, source_id: str, case_types: dict | None = None) -> dict:
    f = c["fields"]
    if "owner" in f:
        who_label, who = "Owner(s)", f["owner"]
    elif "applicant_owner" in f:
        who_label, who = "Applicant/owner", f["applicant_owner"]
    elif "applicant" in f:
        who_label, who = "Applicant", f["applicant"]
    else:
        who_label, who = None, None
    request = f.get("request") or f.get("variance_request")
    request_label = "Variance request" if not f.get("request") and f.get("variance_request") else "Request"
    if not request and f.get("development"):
        request, request_label = f["development"], "Development"
    if not request and f.get("reason"):   # CDRB design review cases print only the reason
        request, request_label = f["reason"], "Reason for the request"
    wm = WARD_VALUE.match(f.get("ward") or "")
    dm = WARD_VALUE.match(f.get("district") or "")
    return {
        "meeting_id": meeting_id, "source_id": source_id, "page": c["page"], "item": c["item"],
        "number": c["number"], "number_printed": c["number_printed"], "prefix": c["prefix"],
        "case_type": (case_types or {}).get(c["prefix"], OTHER_CASE), "heading_printed": c["case_type"],
        "agenda_part": c["agenda_part"], "note": c["note"],
        "applicant_label": who_label, "applicant": who or None, "agent": f.get("agent") or None,
        "request_label": request_label if request else None, "request": request or None,
        "proposed_use": f.get("proposed_use") or None,
        "location": f.get("location") or None,
        "ward": int(wm.group(1)) if wm else None, "ward_printed": f.get("ward") or None,
        "district": int(dm.group(1)) if dm else None,
        "acres": f.get("acres") or None,
    }


def source_record(e: dict, pages: int | None, layer: str, fmt: str) -> dict:
    return {"id": f"src-{e['sha256'][:12]}", "url": e["url"], "sha256": e["sha256"], "kind": e.get("kind"),
            "meeting_date": e.get("meeting_date"), "fetched_at": (e.get("first_fetched_at") or "")[:10],
            "pages": pages, "text_layer": layer, "format": fmt}


# Whole-document OCR cap for RPC scans only (not shared with the county path): largest real RPC document 90 pp
# (cmc-rpc/rpc.json, 2026-11-11), cap 2.2x. A larger document is not read at all and is reported.
RPC_MAX_OCR_PAGES = 200


def pdf_page_count(p: Path) -> int | None:
    import subprocess
    try:
        out = subprocess.run(["pdfinfo", str(p)], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else None


# OCR of a scanned page reads the scan's border and table rules as marks at the start of a line ("| CASE NUMBER",
# "1. | CASE NUMBER: DDR - 18 - 2025"); only those marks are dropped, nothing else in the text is changed.
OCR_MARKS = re.compile(r"^(\s*(?:\d{1,3}\s*\.\s*)?)[|!‘'`~»]+\s+(?=\S)", re.M)


def ocr_clean(pages: list[str]) -> list[str]:
    return [OCR_MARKS.sub(lambda m: m.group(1).rstrip() + (" " if m.group(1).strip() else ""), p) for p in pages]


def ocr_document(pdf: Path, sha: str, pages: int) -> list[str]:
    """Every page of a scanned PDF read by the county minutes' OCR path (collector/ocr.py: its 300 dpi rendering,
    tesseract settings, per-call timeouts and cache; pages in parallel). Raises when any page fails, so a document is
    read whole or not at all."""
    from .minutes import ocr_pages_parallel
    from .ocr import PageRefused, cache_path
    if pages > RPC_MAX_OCR_PAGES:   # pipeline/parser-dos-untimed: refused whole before any page is rendered
        raise PageRefused(f"{pages} pages: RPC OCR reads at most {RPC_MAX_OCR_PAGES} pages of a document")
    errors = ocr_pages_parallel([(str(pdf), p, sha) for p in range(1, pages + 1)])
    bad = sorted(p for (_, p), err in errors.items() if err)
    if bad:
        raise RuntimeError(f"OCR failed on page {bad[0]} ({errors[(sha, bad[0])]})"
                           + (f" and {len(bad) - 1} more" if len(bad) > 1 else ""))
    return [cache_path(sha, p).read_text() for p in range(1, pages + 1)]


def build(cfg, rows: list[dict], store, extract=extract_pages, ocr=ocr_document,
          audit_path: Path | None = None) -> tuple[dict, dict]:
    """(facts, summary) from the committed listing and the stored files. A listed document whose bytes are not in
    the store is listed with its link and no source (never guessed). Agendas are read for cases (a scanned agenda by
    OCR), minutes for motions (collector/rpc_minutes.py). `audit_path` (build/rpc-motions-audit.jsonl): one JSON line
    per motion with its reasons and the sentences read, for QA sampling. Internal: never under build/site, never
    committed (build/ is gitignored), never exported."""
    by_url = {e["url"]: e for e in store.current()}
    sources: dict[str, dict] = {}
    meetings, cases, problems, shortfalls = [], [], [], []
    parsed = 0

    def scanned_texts(sid: str, e: dict) -> list[str] | None:
        """The OCR texts of a scanned source (cached on the source), or None with the failure reported."""
        s = sources[sid]
        if "_ocr" not in s:
            s["_ocr"] = None
            try:
                s["_ocr"] = ocr(store.path_for(e["sha256"]), e["sha256"], s["pages"] or 0) if s["pages"] else None
            except Exception as ex:   # an OCR failure is reported, never a half-read document
                problems.append(f"{s['url']}: OCR failed ({type(ex).__name__}: {ex})")
        return s["_ocr"]
    for r in sorted(rows, key=lambda r: (r["date"], r["id"])):
        docs = []
        agenda_src = None
        for d in r["docs"]:
            e = by_url.get(d["url"]) if d["fetch"] else None
            sid = None
            if e is not None and store.has_bytes(e["sha256"]):
                sid = f"src-{e['sha256'][:12]}"
                fmt = "docx" if d["url"].lower().endswith(".docx") else "pdf"
                if sid not in sources:
                    pages, layer, texts = None, "none", None
                    if fmt == "pdf":
                        try:
                            texts = extract(store.path_for(e["sha256"]))
                            pages = pdf_page_count(store.path_for(e["sha256"])) or len(texts)
                            layer = text_layer(texts)
                        except Exception as ex:   # one bad file must not stop the build; it is reported
                            problems.append(f"{d['url']}: text not read ({type(ex).__name__}: {ex})")
                    sources[sid] = {**source_record(e, pages, layer, fmt), "read_by": None, "_texts": texts}
                if d["kind"] == "agenda" and agenda_src is None and sources[sid]["format"] == "pdf":
                    agenda_src = sid
            elif d["fetch"]:
                problems.append(f"{r['id']}: {d['kind']} {d['url']} not in the store")
            docs.append({"kind": d["kind"], "url": d["url"], "host": d["host"], "fetched": sid is not None,
                         "source_id": sid, "link_text": d.get("link_text") or d["kind"].capitalize()})
        m = {"id": r["id"], "date": r["date"], "kind": r["kind"], "label": r["label"], "printed": r["printed"],
             "cancelled": r["cancelled"], "documents": docs, "not_linked": r.get("no_doc") or [],
             "agenda_source_id": agenda_src, "agenda_date": None, "hearings": [], "case_count": 0,
             "case_numbers_printed": None, "case_numbers_read": None, "agenda_read_by": None,
             "minutes_source_id": None, "minutes_date": None, "minutes_read_by": None,
             "minutes_case_heads_printed": None, "minutes_case_heads_read": None}
        texts = None
        if agenda_src and sources[agenda_src]["_texts"] and sources[agenda_src]["text_layer"] != "none":
            texts, m["agenda_read_by"] = sources[agenda_src]["_texts"], "text layer"
            sources[agenda_src]["read_by"] = "text layer"
        elif agenda_src and sources[agenda_src]["text_layer"] == "none":
            e = next(by_url[d["url"]] for d in r["docs"] if by_url.get(d["url"]) and
                     f"src-{by_url[d['url']]['sha256'][:12]}" == agenda_src)
            texts = scanned_texts(agenda_src, e)
            if texts is not None:
                texts = ocr_clean(texts)
                m["agenda_read_by"] = "OCR"
                sources[agenda_src]["read_by"] = "OCR"
        if texts:
            res = parse_pages(texts)
            parsed += 1
            if res["printed_date"]:
                m["agenda_date"] = res["printed_date"]["date"]
                if res["printed_date"]["date"] != r["date"]:
                    problems.append(f"{r['id']}: the agenda prints {res['printed_date']['printed']!r} "
                                    f"({res['printed_date']['date']}), the listing {r['printed']!r}")
            m["hearings"] = [{**h, "source_id": agenda_src} for h in res["hearings"]]
            seen: dict[str, int] = {}
            for c in res["cases"]:
                rec = case_record(c, r["id"], agenda_src, cfg.case_types)
                rec["read_by"] = m["agenda_read_by"]
                seen[rec["number"]] = seen.get(rec["number"], 0) + 1
                rec["id"] = f"{r['id']}-{rec['number'].lower()}" + ("" if seen[rec["number"]] == 1
                                                                    else f"-{seen[rec['number']]}")
                cases.append(rec)
            m["case_count"] = len(res["cases"])
            m["case_numbers_printed"], m["case_numbers_read"] = res["case_numbers_printed"], res["case_numbers_read"]
            if res["case_numbers_printed"] > res["case_numbers_read"]:   # a case the reader missed is never silent
                shortfalls.append(r["id"])
                problems.append(f"{r['id']}: the agenda prints {res['case_numbers_printed']} case numbers "
                                f"(CASE NUMBER: or a numbered case line), {res['case_numbers_read']} of those cases "
                                f"read (completeness check)")
        elif agenda_src:
            problems.append(f"{r['id']}: agenda has no text layer and was not read by OCR")
        meetings.append(m)
    audit: list[dict] = []
    motions, minutes_summary = read_all_minutes(cfg, rows, meetings, cases, sources, by_url, scanned_texts, problems,
                                                audit)
    if audit_path is not None:
        write_audit(Path(audit_path), audit)
    srcs = [{k: v for k, v in s.items() if not k.startswith("_")} for s in sorted(sources.values(), key=lambda s: s["id"])]
    dates = [m["date"] for m in meetings]
    from .rpc_minutes import MOTION_RULES
    # motion_rules: the reader's rules the motions were read by; the pages confirm no motion of a record without it
    facts = {"schema": "rpc-1", "motion_rules": MOTION_RULES, "body": cfg.body, "listing_url": cfg.listing_url,
             "coverage": {"from": min(dates) if dates else None, "to": max(dates) if dates else None},
             "meetings": meetings, "sources": srcs, "cases": cases, "motions": motions}
    summary = {"meetings": len(meetings), "documents_listed": sum(len(m["documents"]) for m in meetings),
               "sources": len(srcs), "link_only": sum(1 for m in meetings for d in m["documents"] if not d["fetched"]),
               "agendas_read": parsed, "agendas_read_by_ocr": sum(1 for m in meetings if m["agenda_read_by"] == "OCR"),
               "cases": len(cases), "case_shortfalls": shortfalls, **minutes_summary, "problems": problems}
    return facts, summary


def write_audit(path: Path, rows: list[dict]) -> None:
    """The internal motions audit (rule 6 of docs/architecture/rpc-motion-invariant.md): never inside a built site."""
    if "site" in path.parts:
        raise ValueError(f"{path}: the motions audit holds OCR text and is never written into a built site")
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def _family(kind: str) -> str:
    """The members' body a meeting kind belongs to: the CDRB has its own members; the RPC's regular, special and
    Executive Committee meetings share theirs."""
    return "cdrb" if kind == "cdrb" else "rpc"


ROSTER_YEARS = 1     # rule 2a: the roster of a meeting is every member read cleanly from the same body's headers
                     # within this many years of it


def read_all_minutes(cfg, rows, meetings, cases, sources, by_url, scanned_texts, problems,
                     audit: list | None = None) -> tuple[list, dict]:
    """Every listed minutes document read for motions (collector/rpc_minutes.py), attached to the meeting whose
    date the minutes print. Returns (motions, summary counts). `audit` gets one row per motion with the sentences
    read (OCR text: internal, for QA sampling; never published)."""
    from . import rpc_minutes as RM
    audit = [] if audit is None else audit
    row_of = {r["id"]: r for r in rows}
    texts_of: dict[str, list[str]] = {}
    pairs = []      # (meeting, minutes source id)
    for m in meetings:
        for d in m["documents"]:
            sid = d.get("source_id")
            if d["kind"] != "minutes" or not sid or sources[sid]["format"] != "pdf":
                continue
            s = sources[sid]
            if sid not in texts_of:
                if s["text_layer"] == "text":
                    texts_of[sid] = s["_texts"]
                    s["read_by"] = "text layer"
                else:
                    e = next(by_url[x["url"]] for x in row_of[m["id"]]["docs"] if by_url.get(x["url"])
                             and f"src-{by_url[x['url']]['sha256'][:12]}" == sid)
                    texts_of[sid] = scanned_texts(sid, e)
                    if texts_of[sid] is not None:
                        s["read_by"] = "OCR"
            if texts_of[sid]:
                pairs.append((m, sid))
    members = {sid: RM.members_present([ln for p in t for ln in p.splitlines() if ln.strip()])
               for sid, t in texts_of.items() if t}
    prefixes = set(cfg.case_types)
    agenda_numbers: dict[str, dict[str, str]] = {}
    for c in cases:
        agenda_numbers.setdefault(c["meeting_id"], {}).setdefault(c["number"], c["id"])
    out, read, attached = [], 0, 0
    for m, sid in pairs:
        y = int(m["date"][:4])
        roster = sorted({n for mm, s2 in pairs if _family(mm["kind"]) == _family(m["kind"])
                         and abs(int(mm["date"][:4]) - y) <= ROSTER_YEARS for n in members.get(s2, [])})
        on_agenda = agenda_numbers.get(m["id"], {})
        res = RM.read_minutes(texts_of[sid], set(on_agenda), prefixes, roster)
        read += 1
        printed = res.printed_date["date"] if res.printed_date else None
        if printed and printed != m["date"]:     # rule 7: minutes of another meeting, listed under this one
            problems.append(f"{m['id']}: the listed minutes print {res.printed_date['printed']!r} ({printed}); "
                            f"their motions are not shown under this meeting")
            m["minutes_date"] = printed
            continue
        attached += 1
        m.update({"minutes_source_id": sid, "minutes_date": printed, "minutes_read_by": sources[sid].get("read_by"),
                  "minutes_case_heads_printed": res.case_heads_printed,
                  "minutes_case_heads_read": res.case_heads_read})
        if res.case_heads_printed > res.case_heads_read:
            problems.append(f"{m['id']}: the minutes print {res.case_heads_printed} case headings, "
                            f"{res.case_heads_read} of their numbers read (motions under the others not confirmed)")
        if res.case_heads_read < len(on_agenda):    # reported, not a gate: a list of deferrals prints no heading
            problems.append(f"{m['id']}: the minutes read {res.case_heads_read} case headings, the agenda lists "
                            f"{len(on_agenda)} cases")
        for k, mv in enumerate(res.motions, 1):
            reasons = list(mv.reasons)
            if mv.case and mv.case not in on_agenda:    # rule 1 (C1): read cleanly, but not on this meeting's agenda
                reasons.append(RM.WHY_OFF_AGENDA)
            if not printed:
                reasons.append("the minutes' date was not read")
            # placed under its agenda case only while nothing doubts the case itself (C1)
            case_ok = mv.case and not RM.CASE_REASONS.intersection(reasons)
            rec = {"id": f"{m['id']}-motion-{k}", "meeting_id": m["id"], "source_id": sid, "page": mv.page,
                   "case": mv.case, "case_id": on_agenda.get(mv.case) if case_ok else None, "kind": mv.kind,
                   "moved_by": mv.mover, "seconded_by": mv.seconder, "nays": mv.nays, "abstained": mv.abstained,
                   "outcome": mv.outcome, "tally": mv.tally, "confirmed": not reasons, "reasons": reasons}
            out.append(rec)
            audit.append({"id": rec["id"], "source_id": sid, "page": mv.page, "confirmed": rec["confirmed"],
                          "reasons": reasons, "para": mv.para})
    why: dict[str, int] = {}
    for x in out:
        for r in x["reasons"]:
            why[r] = why.get(r, 0) + 1
    summary = {"minutes_read": read, "minutes_attached": attached, "motions": len(out),
               "motions_confirmed": sum(1 for x in out if x["confirmed"]),
               "motions_on_agenda_cases": sum(1 for x in out if x["case_id"]),
               "motions_not_confirmed_by_reason": dict(sorted(why.items(), key=lambda kv: (-kv[1], kv[0])))}
    return out, summary
