"""Finance and contracts views (docs/design/finance-contracts.md 2-5, architecture 7): finance.json -> plain dicts.

Neutrality (AC-F8, N1): one builder per page type, the same for every solicitation, vendor and department; no
vendor- or department-specific flag. Orders are by date or by name only, never by an amount or a count: bidders keep
the bid tab's printed order. Provenance (AC-F3): every shown amount, name and date carries its source page and fetch
date. Scan guard (scan-values/*): a value is shown only from a text-layer source; `check_references` refuses a file
that breaks this. Every fixed sentence comes from config/finance_text.yml (config.FIN_TEXT)."""
from __future__ import annotations

import datetime as dt
import re

from . import config

T = config.FIN_TEXT
C = T["contracts"]


# The CSV/JSON download links on the index wait for the export files (finance-contracts F8): set True there.
EXPORTS_READY = False


class FinanceError(Exception):
    pass


def check_references(fin: dict) -> None:
    """Every id finance.json points at exists, and no value cites a source without a text layer (scan-values/*), a
    shared link (award-source/*) or a non-bid-tab document. Raises FinanceError naming the first problem."""
    sources = {s["id"]: s for s in fin["sources"]}
    docs = {d["id"]: d for d in fin["documents"]}
    sols = {s["id"] for s in fin["solicitations"]}

    def need_source(sid, where):
        if sid not in sources:
            raise FinanceError(f"{where} refers to source id {sid!r}, which is not in the finance file")
        return sources[sid]

    def value_source(sid, where):
        s = need_source(sid, where)
        if s["text_layer"] != "text":
            raise FinanceError(f"{where} shows a value from {sid}, whose text layer is {s['text_layer']!r} "
                               "(scan-values: values come only from text documents)")

    for d in fin["documents"]:
        if d["source_id"] is not None:
            need_source(d["source_id"], f"document {d['id']}")
        if d["doc_date_text"] is not None:
            value_source(d["source_id"], f"document {d['id']} date")
        for other in d["shared_by"]:
            if other not in sols:
                raise FinanceError(f"document {d['id']} shared_by {other!r}, which is not a solicitation")
    for s in fin["solicitations"]:
        where = f"solicitation {s['id']}"
        need_source(s["archive_source_id"], where)
        for did in s["document_ids"]:
            if did not in docs:
                raise FinanceError(f"{where} refers to document id {did!r}, which is not in the finance file")
        if s["department"] is not None:
            value_source(s["department"]["source_id"], where + " department")
        tab = s["bid_tab"]
        if tab is not None:
            if tab["document_id"] not in s["document_ids"]:
                raise FinanceError(f"{where} bid tab {tab['document_id']} is not one of its documents")
            doc = docs[tab["document_id"]]
            if tab["tab_type"] == "lump_sum":
                if doc["status"] != "fetched" or doc["stage"] != "bid_tab":
                    raise FinanceError(f"{where} reads values from {doc['id']}, which is not a fetched bid tab")
                if doc["shared_by"]:
                    raise FinanceError(f"{where} reads values from {doc['id']}, a link shared by other solicitations "
                                       "(award-source: link only)")
                value_source(doc["source_id"], where + " bid tab")
        if s["documents_differ"] is not None:
            for did in s["documents_differ"]["document_ids"]:
                if did not in s["document_ids"]:
                    raise FinanceError(f"{where} documents_differ names {did!r}, which is not one of its documents")


def coverage_sentence(cov: dict) -> str:
    """AC-F15: the one coverage sentence, identical on every contracts page, from finance.json's coverage block.
    {n_tab} is n_bid_tab_links: solicitations with a bid tab (bid_tab not null), read or not. {n_scan} of
    {n_letters} is n_award_scanned of n_award_letters: award-type documents (fin_checks.AWARD_LETTER_STAGES), and of
    those the ones marked scanned (text layer none or a scanner's OCR, document.scanned)."""
    return T["coverage_contracts"].format(n_tab=cov["n_bid_tab_links"], n_total=cov["n_total"], n_read=cov["n_tab_read"],
                                          n_scan=cov["n_award_scanned"], n_letters=cov["n_award_letters"])


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().casefold()


class Finance:
    """Lookup tables over one finance dict, plus the officials of the facts file (AC-F9: a name that is an official's
    name or alias links to their page)."""

    def __init__(self, fin: dict, officials: list[dict] | None = None):
        self.fin = fin
        self.fixture = bool(fin.get("fixture"))
        self.sources = {s["id"]: s for s in fin["sources"]}
        self.docs = {d["id"]: d for d in fin["documents"]}
        self.sols = {s["id"]: s for s in fin["solicitations"]}
        self.coverage = fin["coverage"]
        self.officials = {}
        for o in officials or []:
            for n in [o["name"], *o["aliases"]]:
                self.officials.setdefault(_norm(n), o)

    def src(self, source_id: str, page: int | None) -> dict:
        s = self.sources[source_id]
        pdf = s["content_type"] == "application/pdf"
        url = f"{s['url']}#page={page}" if pdf and page else s["url"]
        word = C["source_words"].get(s["kind"], C["source_words"]["other"])
        label = f"{word} p. {page}" if pdf and page else C["archive_link"]
        return {"url": url, "page": page, "label": label, "fetched": s["fetched_at"],
                "kind": C["archive_link"] if not pdf else word}

    def person(self, name: str) -> dict:
        """For the `person` macro: an official's name links to their page; any other name is plain text as printed."""
        o = self.officials.get(_norm(name))
        if o is not None:
            return {"name": name, "href": f"officials/{o['id']}.html", "seat": None}
        return {"name": name, "href": None, "seat": None}


# ---------------------------------------------------------------------------------------------------------------
# shared pieces


def stage_label(stage: str) -> str:
    return C["stages"][stage]


def _doc_date(text: str | None) -> str | None:
    """A document's own printed date as ISO, for ordering only (never shown in place of the printed text)."""
    if not text:
        return None
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _doc_link(fx: Finance, d: dict, sol: dict) -> dict:
    """One document link with its state words (design 5 states). `note` is shown beside the link."""
    # the row's own link text (schema solicitation.document_labels, parallel to document_ids), not the shared
    # document's first-row label
    label = sol["document_labels"][sol["document_ids"].index(d["id"])]
    note = None
    if d["status"] == "dead_at_fetch":
        note = C["dead_link"].format(date=d["fetched_at"])
    elif d["status"] == "not_pdf":
        note = C["not_pdf"]
    elif d["status"] == "link_only":
        note = C["link_only"]
    elif d["shared_by"]:
        note = C["shared"]
    return {"id": d["id"], "stage": d["stage"], "stage_label": stage_label(d["stage"]), "label": label,
            "href": None if d["status"] == "dead_at_fetch" else d["url"], "scanned": d["scanned"], "note": note,
            "fetched": d["fetched_at"]}


def _held_fields(sol: dict) -> dict[str, str]:
    """{held field: the check that held it}."""
    return {h["field"]: h["check"] for h in sol["held"]}


def held_check(check: str | None, where: str) -> str | None:
    """The check name the not_confirmed macro takes (provenance/held-sentence-misstates): each held value says why
    it is held in that check's own fixed sentence (config/finance_text.yml `held`). A check with no sentence there
    fails the build rather than fall back to a sentence that would misstate it."""
    if check is not None and check not in T["held"]:
        raise FinanceError(f"{where} is held by check {check!r}, which has no sentence in config/finance_text.yml "
                           "(held)")
    return check


def _department(fx: Finance, sol: dict) -> dict | None:
    dep = sol["department"]
    if dep is None:
        return None
    held = _held_fields(sol)
    check = held.get("department", held.get("department.text"))
    return {"text": dep["text"], "src": fx.src(dep["source_id"], dep["page"]),
            "held": check is not None, "check": held_check(check, f"solicitation {sol['id']} department")}


def _tab_state(fx: Finance, sol: dict) -> dict | None:
    """The bid tab block (design 5.2). Lump-sum tabs: bidders in printed order and the awardee as printed, each with
    its page. Not-read tabs: a link and the fixed reason sentence, no values."""
    tab = sol["bid_tab"]
    if tab is None:
        return None
    doc = fx.docs[tab["document_id"]]
    out = {"kind": tab["tab_type"], "doc": _doc_link(fx, doc, sol), "reason": None, "bidders": [], "awardee": None,
           "bid_date": None, "award_date": None}
    if tab["tab_type"] != "lump_sum":
        reason = tab["not_read_reason"]
        if reason not in C["not_read"]:  # no silent default: a new reason needs its own sentence first
            raise FinanceError(f"solicitation {sol['id']} has not_read_reason {reason!r}, which has no sentence in "
                               "config/finance_text.yml (contracts.not_read)")
        out["reason"] = C["not_read"][reason]
        return out
    held = _held_fields(sol)
    sid = doc["source_id"]
    for key, label in (("bid_date", "bid_date"), ("award_date", "award_date")):
        if tab[key + "_text"]:
            out[key] = {"label": C[label], "text": tab[key + "_text"], "src": fx.src(sid, tab[key + "_page"])}
    # schema held.field: `bid_tab.bidders[i].total_cents`, i a 0-based index into the file's bidders list (not the
    # printed order, which starts at 1); the value is also null in the file
    held_idx = {int(m.group(1)): c for f, c in held.items()
                if (m := re.fullmatch(r"bid_tab\.bidders\[(\d+)\]\.total_cents", f))}
    for i, b in sorted(enumerate(tab["bidders"]), key=lambda ib: ib[1]["printed_order"]):  # printed order only (AC-F8)
        total_held = i in held_idx or b["total_cents"] is None or b["total_as_printed"] is None
        fact_id = f"{sol['id']}/bidder/{b['printed_order']}"
        # a null total with no held entry: amount-format is the check that leaves a printed total unread
        check = held_idx.get(i, "amount-format") if total_held else None
        out["bidders"].append({
            "order": b["printed_order"], "who": fx.person(b["name"]),
            "total": None if total_held else b["total_as_printed"], "check": held_check(check, fact_id),
            "src": fx.src(sid, b["page"]), "fact_id": fact_id})
    awardee_check = held_check(held.get("bid_tab.awardee_text"), f"solicitation {sol['id']} awardee")
    awardee_held = awardee_check is not None
    if tab["awardee_text"] is None or tab["awardee_match"] == "none_named":
        out["awardee"] = {"sentence": C["awardee_none"], "who": None, "src": None, "state": None, "held": False}
    else:
        state = {"not_a_listed_bidder": C["awardee_not_listed"], "ambiguous": C["awardee_ambiguous"]}.get(
            tab["awardee_match"])
        if not tab["awardee_page"]:
            raise FinanceError(f"solicitation {sol['id']} names an awardee but no page for it (awardee_page)")
        lead, _, tail = C["awardee"].partition("{name}")
        out["awardee"] = {"sentence": None, "lead": lead, "tail": tail, "who": fx.person(tab["awardee_text"]),
                          "src": fx.src(sid, tab["awardee_page"]), "state": state, "held": awardee_held,
                          "check": awardee_check}
    return out


def _differ(fx: Finance, sol: dict) -> dict | None:
    d = sol["documents_differ"]
    if d is None:
        return None
    return {"sentence": C["differ"], "fields": [C["differ_fields"][f] for f in d["fields"]],
            "docs": [_doc_link(fx, fx.docs[i], sol) for i in d["document_ids"]]}


def _words(ids: list[str]) -> list[dict]:
    by_id = {g["id"]: g for g in T["glossary"]}
    return [by_id[i] for i in sorted(ids, key=lambda i: by_id[i]["term"].casefold())]


def notes() -> dict:
    return T["notes"]


# ---------------------------------------------------------------------------------------------------------------
# pages


def _index_order(sols: list[dict]) -> list[dict]:
    """Default order (design 4): archive date, newest first (archive row for a tie); rows with no date after, in
    archive order."""
    dated = sorted((s for s in sols if s["archive_date"]), key=lambda s: s["row"])
    dated = sorted(dated, key=lambda s: s["archive_date"], reverse=True)  # stable: row order kept within a date
    return dated + sorted((s for s in sols if not s["archive_date"]), key=lambda s: s["row"])


def contracts_index(fx: Finance) -> dict:
    rows = []
    for sol in _index_order(fx.fin["solicitations"]):
        tab = sol["bid_tab"]
        dep = _department(fx, sol)
        state = _tab_state(fx, sol)
        awardee = state["awardee"] if state and state["awardee"] and state["awardee"]["who"] else None
        cites = [fx.src(sol["archive_source_id"], None)]  # date, title and links; then department and awardee pages
        for c in (dep["src"] if dep else None, awardee["src"] if awardee else None):
            if c is not None and c["url"] not in {x["url"] for x in cites}:
                cites.append(c)
        names = [b["name"] for b in (tab["bidders"] if tab else [])]
        rows.append({
            "id": sol["id"], "href": f"contracts/{sol['slug']}.html", "title": sol["title"],
            "date": sol["archive_date"], "date_text": sol["archive_date_text"] or C["archive_date_empty"],
            "year": sol["year"], "dept": dep, "dept_key": dep["text"] if dep else C["no_department"],
            "docs": [_doc_link(fx, fx.docs[i], sol) for i in sol["document_ids"]],
            "has_tab": tab is not None, "awardee": awardee, "cites": cites,
            # what the "Vendor or title" box matches: title, department and every bidder name (design 11)
            "search": " ".join([sol["title"], dep["text"] if dep else "", *names]).casefold(),
        })
    depts = sorted({r["dept_key"] for r in rows}, key=str.casefold)
    years = sorted({r["year"] for r in rows if r["year"] is not None}, reverse=True)
    return {"rows": rows, "depts": depts, "years": years, "coverage_sentence": coverage_sentence(fx.coverage),
            "notes": notes(), "c": C, "words": _words(C["words"]), "disclosure": False,
            "exports": EXPORTS_READY}


def solicitation(sol_id: str, fx: Finance) -> dict:
    sol = fx.sols[sol_id]
    order = {s: n for n, s in enumerate(C["stage_order"])}
    docs = []
    for n, did in enumerate(sol["document_ids"]):
        d = fx.docs[did]
        link = _doc_link(fx, d, sol)
        date_src = fx.src(d["source_id"], d["doc_date_page"]) if d["doc_date_text"] else None
        docs.append(dict(link, date=d["doc_date_text"], date_src=date_src, n=n,
                         row_src=date_src or fx.src(sol["archive_source_id"], None),
                         fact_id=f"{sol['id']}/{d['id']}", _iso=_doc_date(d["doc_date_text"])))
    # design 5.1: document date ascending, ties (and undated documents) by the stage order, then archive order
    docs.sort(key=lambda r: (r["_iso"] is None, r["_iso"] or "", order[r["stage"]], r["n"]))
    seen = set()
    for r in docs:  # first use of a glossary word in the table links to its entry
        gid = C["stage_glossary"].get(r["stage"])
        r["glossary"] = gid if gid and gid not in seen else None
        seen.add(gid)
    return {"sol": sol, "title": sol["title"], "dept": _department(fx, sol), "docs": docs,
            "archive_src": fx.src(sol["archive_source_id"], None), "archive_date_text": sol["archive_date_text"],
            "tab": _tab_state(fx, sol), "differ": _differ(fx, sol), "number": sol["number"],
            "coverage_sentence": coverage_sentence(fx.coverage), "notes": notes(), "c": C,
            "words": _words(C["words"]), "disclosure": False}


def glossary() -> dict:
    return {"entries": sorted(T["glossary"], key=lambda g: g["term"].casefold())}


def search_records(fx: Finance, body: str) -> list[dict]:
    """Search index type `sol` (F7): title, department and every bidder name are searchable (`x`)."""
    out = []
    for sol in fx.fin["solicitations"]:
        tab = sol["bid_tab"]
        dep = sol["department"]["text"] if sol["department"] else ""
        names = [b["name"] for b in sorted(tab["bidders"], key=lambda b: b["printed_order"])] if tab else []
        out.append({"k": "sol", "id": sol["id"], "n": "", "t": sol["title"], "d": sol["archive_date"] or "",
                    "y": [sol["year"]] if sol["year"] else [], "ty": [], "b": body,
                    "h": f"contracts/{sol['slug']}.html", "x": " · ".join(p for p in [dep, *names] if p)})
    return out
