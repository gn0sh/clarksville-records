"""Regional Planning Commission export: build/site/data/<slug>/ facts.json, meetings.csv, cases.csv, motions.csv and
sources.csv, the RPC facts the public pages show (sitegen/rpc.py).

Rules, the same as the pages (docs/architecture/rpc-motion-invariant.md, "Committed record": a site export must strip
what the pages hold back):
- A motion is exported only when the pages show it confirmed: `Rpc.motions` (sitegen.rpc.shown_motions), never the
  stored `facts["motions"]`. A motion that is not confirmed is not a row at all: no mover, seconder, nay, abstainer,
  outcome or case number of it is in any public file. meetings.csv counts them (`motions_not_confirmed`), so a reader
  sees that the minutes hold more than the file. A record whose `motion_rules` is not the reader's current rules
  (written before them) exports no motion.
- Nays and abstainers only as the minutes name them; an empty cell says nothing was named. No column, key or value of
  ours says "unanimous" or carries a tally: the outcome is the minutes' own words.
- A case is the agenda's own words, with the agenda page that prints it. Names are as printed (the RPC's members have
  no pages of their own on this site, so there is no official id to resolve them to).
- Every case and motion row carries `source_url`, `source_sha256`, `page` and `fetched_at` of the document that prints
  it. A meeting row names the listing page it was taken from and its agenda and minutes files.
- The reader's reasons for not confirming a motion, and every value of an unconfirmed motion, are in an internal
  export only (`internal`), which writes every motion with `confirmed` and `reasons` beside the site, never in it
  (`internal_dir`, build/internal-data/<slug>/). data/<slug>/ holds the public files in every build, and nothing
  else: the export removes any file there it did not write.
- Order by date and id or printed order only.
"""
from __future__ import annotations

import json
from pathlib import Path

from .export import SRC_COLS, _csv

RPC_FILES = ("meetings", "cases", "motions", "sources")
SCHEMA_VERSION = "rpc-export-1"

_S = "stated"
_C = {"source_url": "derived: link to the source document the team fetched",
      "source_sha256": "derived: hash of the fetched file", "page": "derived: page of the source that prints it",
      "fetched_at": "derived: time the team fetched the file"}
_ID = "derived: id"
_COUNT = "derived: counted"
_RULE = "derived: the reader's checks on the minutes (every value read from the minutes' own words)"

MEETING_COLS = ["id", "date", "date_printed", "kind", "kind_label", "label", "cancelled", "source_url", "agenda_url",
                "agenda_collected", "agenda_source_sha256", "agenda_fetched_at", "agenda_read_as_meeting",
                "minutes_url", "minutes_collected", "minutes_source_sha256", "minutes_fetched_at",
                "minutes_read_as_meeting", "cases", "motions_confirmed", "motions_not_confirmed"]
CASE_FIELDS = ["number", "number_printed", "prefix", "case_type", "heading_printed", "agenda_part", "item",
               "applicant_label", "applicant", "agent", "request_label", "request", "proposed_use", "location",
               "ward_printed", "ward", "district", "acres", "note", "read_by"]
CASE_COLS = ["id", "meeting_id", "date"] + CASE_FIELDS + SRC_COLS
MOTION_COLS = ["id", "meeting_id", "date", "case_id", "case_number", "kind", "moved_by", "seconded_by", "nays",
               "abstained", "outcome"]
MOTION_INTERNAL = ["confirmed", "reasons"]
SOURCE_COLS = ["id", "kind", "meeting_date", "format", "pages", "text_layer", "read_by", "source_url", "source_sha256",
               "fetched_at"]

# Provenance registry (architecture, "Invariant: derived vs stated"): every column of the RPC CSVs ("rpc/<file>.<col>")
# and every key of its facts.json ("rpc/facts.json:<list>.<key>") is "stated" or "derived: <how>".
# tests/test_export_rpc.py fails on a column or key missing here.
_MEETING = {
    "id": "derived: date and kind", "date": _S, "date_printed": _S,
    "kind": "derived: fixed patterns on the listing row's label", "kind_label": "derived: fixed label per kind",
    "label": _S, "cancelled": "derived: the listing row says the meeting was cancelled",
    "source_url": "derived: link to the listing page the meeting was taken from",
    "agenda_url": "derived: link to the listed agenda file", "agenda_collected": "derived: whether the team fetched it",
    "agenda_source_sha256": _C["source_sha256"], "agenda_fetched_at": _C["fetched_at"],
    "agenda_read_as_meeting": "derived: whether the reader took the fetched file as this meeting's agenda",
    "minutes_url": "derived: link to the listed minutes file",
    "minutes_collected": "derived: whether the team fetched it",
    "minutes_source_sha256": _C["source_sha256"], "minutes_fetched_at": _C["fetched_at"],
    "minutes_read_as_meeting": "derived: whether the reader took the fetched file as this meeting's minutes (its "
                               "printed date)",
    "cases": _COUNT, "motions_confirmed": _COUNT, "motions_not_confirmed": _COUNT,
}
_CASE = {
    "id": _ID, "meeting_id": _ID, "date": _S, "number": "derived: number_printed with its spacing normalised",
    "number_printed": _S, "prefix": "derived: split from number",
    "case_type": "derived: fixed label per case-number prefix", "heading_printed": _S,
    "agenda_part": "derived: fixed patterns on the agenda's section heading", "item": _S, "applicant_label": _S,
    "applicant": _S, "agent": _S, "request_label": _S, "request": _S, "proposed_use": _S, "location": _S,
    "ward_printed": _S, "ward": "derived: ward_printed read as a number",
    "district": "derived: the printed county commission district read as a number", "acres": _S, "note": _S,
    "read_by": "derived: text layer or OCR", **_C,
}
_MOTION = {
    "id": "derived: content position", "meeting_id": _ID, "date": _S,
    "case_id": "derived: the case heading the minutes print over the motion, on the same meeting's agenda",
    "case_number": _S, "kind": "derived: fixed patterns on the motion's wording", "moved_by": _S, "seconded_by": _S,
    "nays": _S, "abstained": _S, "outcome": _S, "confirmed": _RULE, "reasons": _RULE, **_C,
}
_SOURCE = {
    "id": _ID, "kind": "derived: from the listing link's label", "meeting_date": "derived: from the listing row",
    "format": "derived: file type", "pages": _COUNT, "text_layer": "derived: whether the PDF has a text layer",
    "read_by": "derived: text layer or OCR", "source_url": _C["source_url"], "source_sha256": _C["source_sha256"],
    "fetched_at": _C["fetched_at"],
}
_DOC = {"kind": "derived: from the listing link's label", "link_text": _S, "url": "derived: link as listed",
        "host": "derived: from the link", "collected": "derived: whether the team fetched it", "source_id": _ID}
_HEARING = {"date": "derived: the printed date read as a date", "printed": _S, "page": _C["page"], "source_id": _ID}
_JSON = {
    "meetings": {**{k: _MEETING[k] for k in ("id", "date", "date_printed", "kind", "kind_label", "label", "cancelled",
                                              "cases", "motions_confirmed", "motions_not_confirmed")},
                 "agenda_source_id": _ID, "minutes_source_id": _ID, "documents": "derived: the listing row's links",
                 "hearings": _S},
    "meetings.documents": _DOC,
    "meetings.hearings": _HEARING,
    "cases": {**{k: _CASE[k] for k in ["id", "meeting_id"] + CASE_FIELDS}, "page": _C["page"], "source_id": _ID},
    "motions": {**{k: _MOTION[k] for k in ("id", "meeting_id", "case_id", "case_number", "kind", "moved_by",
                                            "seconded_by", "nays", "abstained", "outcome", "confirmed", "reasons")},
                "page": _C["page"], "source_id": _ID},
    "sources": {**{k: _SOURCE[k] for k in ("id", "kind", "meeting_date", "format", "pages", "text_layer", "read_by",
                                            "fetched_at")}, "sha256": _C["source_sha256"], "url": _C["source_url"]},
    "coverage": {"from": "derived: first meeting date collected", "to": "derived: last meeting date collected"},
}
RPC_PROVENANCE: dict[str, str] = {
    **{f"rpc/meetings.{k}": v for k, v in _MEETING.items()},
    **{f"rpc/cases.{k}": v for k, v in _CASE.items()},
    **{f"rpc/motions.{k}": v for k, v in _MOTION.items()},
    **{f"rpc/sources.{k}": v for k, v in _SOURCE.items()},
    **{f"rpc/facts.json:{lst}.{k}": v for lst, keys in _JSON.items() for k, v in keys.items()},
    "rpc/facts.json:schema_version": "derived: version of the export format",
    "rpc/facts.json:body": "derived: fixed per document series",
    "rpc/facts.json:listing_url": "derived: link to the listing page the meetings were taken from",
    "rpc/facts.json:motion_rules": "derived: version of the reader's rules the motions were confirmed by",
}


def placed(rpx, mv: dict) -> bool:
    """Whether the pages place the motion at all (sitegen.rpc.Rpc.meeting): its meeting is listed, and its case_id,
    if any, is a case on that meeting's agenda (a motion keyed to any other case is on no page)."""
    if not any(m["id"] == mv["meeting_id"] for m in rpx.facts["meetings"]):
        return False
    return not mv["case_id"] or any(c["id"] == mv["case_id"] for c in rpx.cases_by_meeting.get(mv["meeting_id"], []))


def motion_order(mv: dict) -> tuple:
    """Within one meeting and page: the motion's number (`<meeting id>-motion-<n>`, its content position), so motion-10
    follows motion-9; the id itself only for an id of another shape."""
    n = mv["id"].rsplit("-", 1)[-1]
    return (mv["page"], 0, int(n), mv["id"]) if n.isdigit() else (mv["page"], 1, 0, mv["id"])


def exported_motions(rpx, internal: bool = False) -> list[dict]:
    """The motions that may leave in a file: those the pages show confirmed (`rpx.motions`, sitegen.rpc.shown_motions:
    the stored flag, the checks restated on the record, and the `motion_rules` marker), with no reason left on them,
    and place (`placed`).
    `internal` returns every placed motion. The stored record is never read here, so a record written before the
    reader's rules exports none."""
    return [mv for mv in rpx.motions
            if placed(rpx, mv) and (internal or (mv["confirmed"] is True and not mv.get("reasons")))]


def public_facts(rpx, internal: bool = False) -> dict:
    """The RPC facts as the files carry them: explicit keys only, so a field the reader adds to rpc.json later is
    never exported before it has a provenance row."""
    facts = rpx.facts
    shown = exported_motions(rpx, internal)
    n_ok: dict[str, int] = {}
    n_held: dict[str, int] = {}
    public = {mv["id"] for mv in exported_motions(rpx)}
    for mv in rpx.motions:      # not confirmed: every motion of the minutes a public file leaves out
        d = n_ok if mv["id"] in public else n_held
        d[mv["meeting_id"]] = d.get(mv["meeting_id"], 0) + 1
    n_cases = {mid: len(cs) for mid, cs in rpx.cases_by_meeting.items()}
    meetings = []
    for m in sorted(facts["meetings"], key=lambda m: (m["date"], m["id"])):
        meetings.append({
            "id": m["id"], "date": m["date"], "date_printed": m["printed"], "kind": m["kind"],
            "kind_label": rpx.cfg["kind_labels"].get(m["kind"], m["kind"]), "label": m["label"],
            "cancelled": m["cancelled"], "agenda_source_id": m.get("agenda_source_id"),
            "minutes_source_id": m.get("minutes_source_id"),
            "documents": [{"kind": d["kind"], "link_text": d["link_text"], "url": d["url"], "host": d["host"],
                           "collected": bool(d["fetched"]), "source_id": d.get("source_id")}
                          for d in m["documents"]],
            "hearings": [{k: h[k] for k in ("date", "printed", "page", "source_id")} for h in m.get("hearings", [])],
            "cases": n_cases.get(m["id"], 0), "motions_confirmed": n_ok.get(m["id"], 0),
            "motions_not_confirmed": n_held.get(m["id"], 0)})
    dates = {m["id"]: m["date"] for m in facts["meetings"]}
    cases = [{"id": c["id"], "meeting_id": c["meeting_id"], **{k: c.get(k) for k in CASE_FIELDS},
              "page": c["page"], "source_id": c["source_id"]}
             for c in sorted(facts["cases"], key=lambda c: (dates[c["meeting_id"]], c["meeting_id"], c["page"]))]
    motions = []
    for mv in sorted(shown, key=lambda mv: (dates[mv["meeting_id"]], mv["meeting_id"], *motion_order(mv))):
        row = {"id": mv["id"], "meeting_id": mv["meeting_id"], "case_id": mv["case_id"],
               # the case number only where the pages place the motion under that case (C1)
               "case_number": mv["case"] if mv["case_id"] else None, "kind": mv["kind"],
               "moved_by": mv["moved_by"], "seconded_by": mv["seconded_by"], "nays": list(mv.get("nays") or []),
               "abstained": list(mv.get("abstained") or []), "outcome": mv["outcome"], "page": mv["page"],
               "source_id": mv["source_id"]}
        if internal:
            row.update(confirmed=mv["confirmed"] is True, reasons=list(mv.get("reasons") or []))
        motions.append(row)
    sources = [{k: s.get(k) for k in ("id", "kind", "meeting_date", "format", "pages", "text_layer", "read_by",
                                      "sha256", "url", "fetched_at")}
               for s in sorted(facts["sources"], key=lambda s: s["id"])]
    return {"schema_version": SCHEMA_VERSION, "body": rpx.body, "listing_url": rpx.cfg["listing_url"],
            "motion_rules": facts.get("motion_rules"), "coverage": {k: facts["coverage"].get(k) for k in _JSON["coverage"]},
            "meetings": meetings, "cases": cases, "motions": motions, "sources": sources}


def tables(pub: dict, internal: bool = False) -> dict[str, str]:
    """The CSVs of `public_facts`' output: a list cell (nays, abstained, reasons) is its entries joined by "; "."""
    src = {s["id"]: s for s in pub["sources"]}
    dates = {m["id"]: m["date"] for m in pub["meetings"]}

    def cite(source_id, page):
        s = src[source_id]
        return {"source_url": s["url"], "source_sha256": s["sha256"], "page": page, "fetched_at": s["fetched_at"]}

    def doc(m, kind):
        """The meeting's listed `kind` file: its link, and its hash and fetch time when the team holds it, from the
        listed file's own source (as facts.json's documents and sources.csv), whether or not the reader took it as
        this meeting's own (`<kind>_read_as_meeting`: the meeting's `<kind>_source_id`, set only when its date
        matched). With no file of that kind listed, the file the meeting was read from, if any."""
        attached = m.get(f"{kind}_source_id")
        ds = [d for d in m["documents"] if d["kind"] == kind]
        d = next((d for d in ds if attached and d.get("source_id") == attached), ds[0] if ds else None)
        s = (src.get(d.get("source_id") or "") if d else src.get(attached or "")) or {}
        listed = bool(s or d)
        return {f"{kind}_url": d["url"] if d else s.get("url"), f"{kind}_collected": bool(s) if listed else None,
                f"{kind}_source_sha256": s.get("sha256"), f"{kind}_fetched_at": s.get("fetched_at"),
                f"{kind}_read_as_meeting": (bool(attached) and (d is None or d.get("source_id") == attached))
                if listed else None}

    def joined(names):
        return "; ".join(names) if names else None

    out = {}
    out["meetings"] = _csv([dict(m, source_url=pub["listing_url"], **doc(m, "agenda"), **doc(m, "minutes"))
                            for m in pub["meetings"]], MEETING_COLS)
    out["cases"] = _csv([dict(c, date=dates[c["meeting_id"]], **cite(c["source_id"], c["page"]))
                         for c in pub["cases"]], CASE_COLS)
    out["motions"] = _csv([dict(mv, date=dates[mv["meeting_id"]], nays=joined(mv["nays"]),
                                abstained=joined(mv["abstained"]), reasons=joined(mv.get("reasons")),
                                **cite(mv["source_id"], mv["page"])) for mv in pub["motions"]],
                          MOTION_COLS + (MOTION_INTERNAL if internal else []) + SRC_COLS)
    out["sources"] = _csv([dict(s, source_url=s["url"], source_sha256=s["sha256"]) for s in pub["sources"]],
                          SOURCE_COLS)
    return out


def rpc_dir(rpx) -> str:
    """Where the RPC's export lives under data/: its page folder (rpc.yml `slug`), e.g. data/rpc/."""
    return rpx.slug


def internal_dir(rpx, out_dir: Path) -> Path:
    """Where an internal export puts every motion with the reader's checks: beside the site, never in it
    (<out_dir>/../internal-data/<slug>/, e.g. build/internal-data/rpc/, as build/rpc-motions-audit.jsonl), so no
    build ever ships it and no public build is left with it at the public names."""
    return Path(out_dir).resolve().parent / "internal-data" / rpc_dir(rpx)


def _write(pub: dict, d: Path, internal: bool) -> list[Path]:
    d.mkdir(parents=True, exist_ok=True)
    p = d / "facts.json"
    p.write_text(json.dumps(pub, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    written = [p]
    for name, text in tables(pub, internal).items():
        p = d / f"{name}.csv"
        p.write_text(text, encoding="utf-8")
        written.append(p)
    return written


def export_rpc(rpx, out_dir: Path, internal: bool = False) -> list[Path]:
    """The RPC's public files into <out_dir>/data/<slug>/, in every build, and any other file there (an earlier
    export's) removed; `internal` also writes every motion with `confirmed` and `reasons` to `internal_dir`, outside
    the site. `rpx`: the pages' own view of the RPC facts (sitegen.rpc.Rpc)."""
    data_dir = Path(out_dir) / "data" / rpc_dir(rpx)
    written = _write(public_facts(rpx), data_dir, False)
    keep = set(written)
    for p in sorted(data_dir.rglob("*"), reverse=True):     # deepest first, so an emptied folder goes too
        if p.is_dir():
            if not any(p.iterdir()):
                p.rmdir()
        elif p not in keep:
            p.unlink()
    if internal:
        written += _write(public_facts(rpx, internal=True), internal_dir(rpx, out_dir), True)
    return written
