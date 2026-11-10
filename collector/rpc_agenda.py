"""Regional Planning Commission agendas: the case items and the upcoming hearing dates, as printed (milestone RPC-1).

An RPC agenda (text PDF, e.g. https://www.cmcrpc.com/wp2025/wp-content/uploads/2026/10/Agenda-10.27.2026.pdf) lists
each case as a numbered paragraph:

    1. Z - 19 - 2026 OWNER(S): ... REQUEST: ... LOCATION: ... TAX MAP(S): ... CO. COMM. DISTRICT: 1
    CITY COUNCIL WARD: 11 NUMBER OF ACRES: 134.02 +/- ...

grouped under "CASE TYPE: CITY ZONING" (COUNTY ZONING, SUBDIVISION(S), SITE REVIEW(S)) headings, and a section
"UPCOMING ZONING MEETINGS DATES/TIMES" lists the Council and Commission hearing dates. Every value is the document's
own words with whitespace joined; nothing is summarised or reworded, and a field that is not printed is left empty.
Each case keeps the PDF page its number is printed on, so the site links straight to it.

Not read here (follow-ups): the minutes' motions and votes, and links from CZ- cases to county commission items.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .extract import MIN_CHARS_PER_PAGE, extract_pages

# A case number at the start of a numbered agenda paragraph: "1. Z - 19 - 2026", "12. S - 44 - 2026",
# "7. ZO - 2A - 2026", 2025 agendas "1.   CASE NUMBER: Z - 29 - 2025". Group 1 the agenda's item number, 2 the
# prefix, 3 the case's number, 4 the year.
ITEM = re.compile(r"^\s*(\d{1,3})\s*\.\s+(?:CASE\s+NUMBER\s*:\s*)?"
                  r"([A-Z]{1,4})\s*-\s*([0-9]{1,3}[A-Z]?)\s*-\s*((?:19|20)\d\d)\b")
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
    """{printed_date, hearings: [{printed, date, page}], cases: [...]} from an agenda's page texts (1-based pages)."""
    lines = [(n, line) for n, p in enumerate(pages, 1) for line in p.splitlines()]
    printed_date = None
    for n, line in lines[:15]:
        d = iso_date(line)
        if d:
            printed_date = {"date": d, "printed": line.strip(), "page": n}
            break
    hearings, cases = [], []
    case_type = agenda_part = None
    cur = None
    in_hearings = False

    def close():
        nonlocal cur
        if cur is not None:
            body = _join(cur.pop("_lines"))
            cur["text"] = body
            cur["fields"] = fields(body)
            cases.append(cur)
        cur = None

    for n, line in lines:
        if PAGE_NO.match(line) or FOOTER.match(line) or not line.strip():
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
        sec = SECTION.match(line)
        part = PART.match(line)
        ct = CASE_TYPE.match(line)
        it = ITEM.match(line)
        if in_hearings:
            hm = HEARING_LINE.match(line)
            if hm and not it and iso_date(hm.group(1)):
                hearings.append({"printed": _join([hm.group(1)]), "date": iso_date(hm.group(1)), "page": n})
                continue
            if sec or ct or it or part:
                in_hearings = False
        if ct:
            close()
            case_type = _join([ct.group(1)])
            continue
        if part and not sec:
            close()
            agenda_part = "Regular agenda" if part.group(1) == "REGULAR" else "Consent agenda"
            continue
        if sec:
            close()
            word = sec.group(1).upper()
            agenda_part = ("Regular agenda" if "REGULAR" in word else "Consent agenda" if "CONSENT" in word
                           else agenda_part)
            if "REGULAR" not in word and "CONSENT" not in word:
                case_type = agenda_part = None   # e.g. OTHER BUSINESS: later numbered lines are not cases
            continue
        if it:
            close()
            cur = {"item": int(it.group(1)), "prefix": it.group(2),
                   "number": case_number(it.group(2), it.group(3), it.group(4)),
                   "number_printed": _join([line[it.start(2):it.end(4)]]),
                   "case_type": case_type, "agenda_part": agenda_part, "page": n, "note": None,
                   "_lines": [line[it.end(4):]]}
            continue
        if cur is not None:
            nm = NOTE.match(line)
            if nm:
                cur["note"] = _join([nm.group(1)])
                continue
            im = INLINE_NOTE.match(line)   # "REQUEST: C-5 ... District          DEFERRED" (2022)
            if im:
                cur["note"] = _join([im.group(2)])
                line = im.group(1)
            cur["_lines"].append(line)
    close()
    return {"printed_date": printed_date, "hearings": hearings, "cases": cases}


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


def pdf_page_count(p: Path) -> int | None:
    import subprocess
    try:
        out = subprocess.run(["pdfinfo", str(p)], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else None


def build(cfg, rows: list[dict], store, extract=extract_pages) -> tuple[dict, dict]:
    """(facts, summary) from the committed listing and the stored files. A listed document whose bytes are not in
    the store is listed with its link and no source (never guessed). Only agendas are read for cases."""
    by_url = {e["url"]: e for e in store.current()}
    sources: dict[str, dict] = {}
    meetings, cases, problems = [], [], []
    parsed = 0
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
                    sources[sid] = {**source_record(e, pages, layer, fmt), "_texts": texts}
                if d["kind"] == "agenda" and agenda_src is None and sources[sid]["format"] == "pdf":
                    agenda_src = sid
            elif d["fetch"]:
                problems.append(f"{r['id']}: {d['kind']} {d['url']} not in the store")
            docs.append({"kind": d["kind"], "url": d["url"], "host": d["host"], "fetched": sid is not None,
                         "source_id": sid, "link_text": d.get("link_text") or d["kind"].capitalize()})
        m = {"id": r["id"], "date": r["date"], "kind": r["kind"], "label": r["label"], "printed": r["printed"],
             "cancelled": r["cancelled"], "documents": docs, "not_linked": r.get("no_doc") or [],
             "agenda_source_id": agenda_src, "agenda_date": None, "hearings": [], "case_count": 0}
        if agenda_src and sources[agenda_src]["_texts"] and sources[agenda_src]["text_layer"] != "none":
            res = parse_pages(sources[agenda_src]["_texts"])
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
                seen[rec["number"]] = seen.get(rec["number"], 0) + 1
                rec["id"] = f"{r['id']}-{rec['number'].lower()}" + ("" if seen[rec["number"]] == 1
                                                                    else f"-{seen[rec['number']]}")
                cases.append(rec)
            m["case_count"] = len(res["cases"])
        elif agenda_src:
            problems.append(f"{r['id']}: agenda has no text layer (not read; OCR is a follow-up)")
        meetings.append(m)
    srcs = [{k: v for k, v in s.items() if k != "_texts"} for s in sorted(sources.values(), key=lambda s: s["id"])]
    dates = [m["date"] for m in meetings]
    facts = {"schema": "rpc-1", "body": cfg.body, "listing_url": cfg.listing_url,
             "coverage": {"from": min(dates) if dates else None, "to": max(dates) if dates else None},
             "meetings": meetings, "sources": srcs, "cases": cases}
    summary = {"meetings": len(meetings), "documents_listed": sum(len(m["documents"]) for m in meetings),
               "sources": len(srcs), "link_only": sum(1 for m in meetings for d in m["documents"] if not d["fetched"]),
               "agendas_read": parsed, "cases": len(cases), "problems": problems}
    return facts, summary
