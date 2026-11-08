"""Open-data export (G5): build/site/data/facts.json and CSVs, the facts the public pages show.

Invariant: held-back counts (architecture). Every roll call and vote is exported with `confirmed` (true when the roll
call passed its checks); while sitegen.config.SHOW_UNCONFIRMED_VALUES is off (the default, CEO 2026-11-07) an
unconfirmed roll call carries no parsed value (vote `value`, `outcome`, `stated_tally` are null). A vote whose name did not resolve has `official_id: null` and no name, so no value is placed
under a guessed person (P3). Motions carry `confirmed` and only the attribution the pages show. Attendance of a meeting
whose attendance check failed is left out. Every fact row carries source_url, source_sha256, page and fetched_at.
Raw OCR fields (raw names, raw vote wording, outcome text, motion text, motion and roll call event labels, and each
verification check's `detail`) are in internal builds only.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

CSV_FILES = ("officials", "meetings", "attendance", "roll_calls", "votes", "motions", "items", "item_events", "sources",
             "seats")

# Provenance registry (architecture, "Invariant: derived vs stated", check 5). Every CSV column ("<file>.<column>")
# and every public facts.json row key ("facts.json:<list>.<key>", nested rows as "<list>.<sub>.<key>") is either
# "stated" (a cited source prints it, as printed or through a fixed published mapping) or "derived: <how>". A derived
# name never starts "stated_", and a stated_ value is never filled from a derived one. tests/test_provenance.py
# fails on any column or key missing here, so a new field must say which it is before it can ship.
_CITE = {"source_url": "derived: link to the source document the team fetched",
         "source_sha256": "derived: hash of the fetched file", "page": "derived: page of the source that prints it",
         "fetched_at": "derived: time the team fetched the file"}
_VER = "derived: the team's verification checks"
PROVENANCE: dict[str, str] = {
    **{f"{f}.{k}": v for f in ("meetings", "attendance", "roll_calls", "votes", "motions", "items", "item_events")
       for k, v in _CITE.items()},
    "officials.id": "derived: slug of the resolved name", "officials.name": "derived: one spelling chosen per person "
    "(data/names.yml) from the names the minutes print", "officials.surname": "derived: split from name",
    "officials.given": "derived: split from name", "officials.title": "derived: same default title for everyone",
    "officials.aliases": "derived: other printed spellings matched to this person",
    "meetings.id": "derived: date and body", "meetings.body": "derived: fixed per document series",
    "meetings.date": "stated", "meetings.kind": "derived: fixed patterns on the minutes heading",
    "meetings.attendance_status": "derived: the team's attendance reading",
    "meetings.attendance_verified": _VER, "meetings.stated_absent_count": "stated",
    "meetings.unconfirmed_roll_calls": "derived: counted",
    "attendance.fact_id": "derived: id", "attendance.meeting_id": "derived: id", "attendance.date": "stated",
    "attendance.official_id": "derived: name resolution", "attendance.official_name": "derived: name resolution",
    "attendance.raw_name": "stated", "attendance.status": "stated",
    "roll_calls.id": "derived: content position", "roll_calls.meeting_id": "derived: id",
    "roll_calls.item_id": "derived: item linking rule", "roll_calls.motion_id": "derived: motion linking rule",
    "roll_calls.confirmed": _VER, "roll_calls.outcome": "stated", "roll_calls.outcome_text": "stated",
    "roll_calls.stated_yes": "stated", "roll_calls.stated_no": "stated", "roll_calls.stated_abstain": "stated",
    "votes.fact_id": "derived: id", "votes.roll_call_id": "derived: id", "votes.meeting_id": "derived: id",
    "votes.item_id": "derived: item linking rule", "votes.official_id": "derived: name resolution",
    "votes.official_name": "derived: name resolution", "votes.raw_name": "stated", "votes.value": "stated",
    "votes.raw_value": "stated", "votes.confirmed": _VER,
    "motions.id": "derived: content position", "motions.meeting_id": "derived: id",
    "motions.item_id": "derived: item linking rule", "motions.type_label": "derived: fixed patterns on the motion text",
    "motions.confirmed": _VER, "motions.moved_by": "derived: name resolution",
    "motions.seconded_by": "derived: name resolution", "motions.text": "stated", "motions.moved_by_raw": "stated",
    "motions.seconded_by_raw": "stated",
    "items.id": "derived: id", "items.number": "stated", "items.title": "stated",
    "items.link_basis": "derived: item linking rule", "items.year": "derived: year the item is first seen",
    "item_events.id": "derived: content position", "item_events.item_id": "derived: item linking rule",
    "item_events.meeting_id": "derived: id", "item_events.date": "stated",
    "item_events.type": "derived: fixed patterns", "item_events.label": "stated", "item_events.ref": "derived: id",
    "item_events.order": "derived: position on the page",
    "sources.id": "derived: id", "sources.kind": "derived: from the index page label",
    "sources.meeting_date": "derived: from the index page label", "sources.pages": "derived: counted",
    "sources.text_layer": "derived: whether the PDF has a text layer", "sources.source_url": _CITE["source_url"],
    "sources.source_sha256": _CITE["source_sha256"], "sources.fetched_at": _CITE["fetched_at"],
    # seats (config/localities/<locality>/seats.yml): `dates` says which kind each row's dates are
    "seats.official_id": "derived: name resolution", "seats.official_name": "derived: name resolution",
    "seats.seat": "derived: id", "seats.seat_label": "derived: fixed label",
    "seats.dates": "derived: observed (roll calls) or sourced (a source prints the term)",
    "seats.seen_first": "derived: first meeting whose roll-call table prints this holder in this seat (observed rows)",
    "seats.seen_last": "derived: last such meeting; empty = seen at the latest meeting collected (observed rows)",
    "seats.printed_term": "stated", "seats.dates_basis": "derived: fixed wording for the kind of dates",
    "seats.lines": "derived: split at the lines cutover",
    "seats.source_url": "derived: link to the page that prints it (observed: first meeting's roll call)",
    "seats.last_source_url": "derived: link to the last meeting's roll-call page (observed rows)",
    "seats.last_page": "derived: page of that roll call",
}
for _k, _v in _CITE.items():
    PROVENANCE.setdefault(f"seats.{_k}", _v)
# facts.json (public export) row keys
_J = {
    "officials": {k: PROVENANCE[f"officials.{k}"] for k in ("id", "name", "surname", "given", "title", "aliases")},
    "meetings": {"attendance": "stated", "attendance_status": PROVENANCE["meetings.attendance_status"],
                 "body": PROVENANCE["meetings.body"], "date": "stated", "id": "derived: id",
                 "kind": PROVENANCE["meetings.kind"], "source_id": "derived: id",
                 "stated_absent_count": "stated", "verification": _VER},
    "meetings.attendance": {"official_id": "derived: name resolution", "raw_name": "stated", "status": "stated",
                            "page": _CITE["page"]},
    "roll_calls": {"id": "derived: content position", "item_id": PROVENANCE["roll_calls.item_id"],
                   "meeting_id": "derived: id", "motion_id": PROVENANCE["roll_calls.motion_id"], "outcome": "stated",
                   "outcome_text": "stated", "page": _CITE["page"], "source_id": "derived: id",
                   "stated_tally": "stated", "verification": _VER, "votes": "stated", "confirmed": _VER},
    "roll_calls.votes": {"official_id": "derived: name resolution", "raw_name": "stated", "value": "stated",
                         "raw_value": "stated", "confirmed": _VER},
    "motions": {"id": "derived: content position", "item_id": PROVENANCE["motions.item_id"],
                "meeting_id": "derived: id", "moved_by": "derived: name resolution",
                "seconded_by": "derived: name resolution", "page": _CITE["page"], "source_id": "derived: id",
                "text": "stated", "verification": _VER, "type_label": PROVENANCE["motions.type_label"],
                "confirmed": _VER},
    "items": {**{k: PROVENANCE[f"items.{k}"] for k in ("id", "link_basis", "number", "title", "year")},
              # rezoning cases (collector/zoning.py): each field as printed on one cited page, or null
              "zoning": "stated"},
    # items.zoning.<field>: the value as the minutes print it (applicant, location verbatim; acreage the number with
    # `printed` its printed form; from/to zoning the printed district codes), with the cited source page
    **{f"items.zoning.{f}": {"value": "stated", "source_id": "derived: id", "page": _CITE["page"],
                             **({"printed": "stated"} if f == "acreage" else {})}
       for f in ("applicant", "location", "acreage", "from_zoning", "to_zoning")},
    "item_events": {"date": "stated", "id": "derived: content position", "item_id": PROVENANCE["item_events.item_id"],
                    "label": "stated", "meeting_id": "derived: id", "order": PROVENANCE["item_events.order"],
                    "page": _CITE["page"], "ref": "derived: id", "source_id": "derived: id",
                    "type": PROVENANCE["item_events.type"]},
    "sources": {"fetched_at": _CITE["fetched_at"], "id": "derived: id", "kind": PROVENANCE["sources.kind"],
                "meeting_date": PROVENANCE["sources.meeting_date"], "pages": "derived: counted",
                "sha256": _CITE["source_sha256"], "text_layer": PROVENANCE["sources.text_layer"],
                "url": _CITE["source_url"]},
}
PROVENANCE.update({f"facts.json:{lst}.{k}": v for lst, keys in _J.items() for k, v in keys.items()})


def is_verified(x: dict) -> bool:
    return x.get("verification", {}).get("status") == "verified"


def public_verification(v: dict) -> dict:
    """Status plus each check's name and ok flag. A check's `detail` quotes what the program read (raw OCR names such
    as "unmatched: 'R. Ailbert'"), so it is internal only (raw-ocr-leak/verification-detail)."""
    return {"status": v["status"], "checks": [{"check": c["check"], "ok": c["ok"]} for c in v["checks"]]}


def strip_raw(facts: dict, internal: bool = False) -> dict:
    """The public export carries no raw OCR text: ids, resolved official ids, verified status, check names, type label
    and source links only. Raw name, motion-text and check-detail fields exist only in internal builds."""
    from sitegen import config
    from sitegen.views import motion_type_label

    def clean(row, drop=("raw_name",)):
        return row if internal or not row else {k: v for k, v in row.items() if k not in drop}

    def ver(x):
        return x if internal else dict(x, verification=public_verification(x["verification"]))

    out = dict(facts)
    out["motions"] = [dict(ver({k: v for k, v in m.items() if internal or k != "text"}),
                           type_label=motion_type_label(m["text"]),
                           moved_by=clean(m["moved_by"]), seconded_by=clean(m["seconded_by"]))
                      for m in facts["motions"]]
    def values(r, row):
        """An unconfirmed roll call's parsed values (each vote's value, the outcome, the stated tally) are left out
        of the public export unless sitegen.config.SHOW_UNCONFIRMED_VALUES is on: the same rule as the pages."""
        if internal or is_verified(r) or config.SHOW_UNCONFIRMED_VALUES:
            return row
        if "votes" in row:
            return dict(row, outcome=None, stated_tally=None)
        return dict(row, value=None)

    out["roll_calls"] = [values(r, dict(ver(clean(r, ("outcome_text",))), confirmed=is_verified(r),
                                        votes=[values(r, dict(clean(v, ("raw_name", "raw_value")),
                                                              confirmed=is_verified(r)))
                                               for v in r["votes"]]))
                         for r in facts["roll_calls"]]
    out["item_events"] = [e if internal or e["type"] not in ("motion", "roll_call") else dict(e, label="")
                          for e in facts["item_events"]]
    out["meetings"] = [dict(ver(m), attendance=[clean(a) for a in m["attendance"]]) for m in facts["meetings"]]
    return out


def public_subset(facts: dict, internal: bool = False) -> dict:
    """What the public pages show: every roll call and motion; motion attribution only as `Index.attribution` allows
    (the same rule as the pages); attendance only when verified."""
    from sitegen.views import Index

    ix = Index(facts)
    mos = []
    for m in facts["motions"]:
        att = ix.attribution(m)
        mos.append(dict(m, confirmed=is_verified(m),
                        moved_by=m["moved_by"] if internal or att["mover"] else None,
                        seconded_by=m["seconded_by"] if internal or att["seconder"] else None))
    meetings = []
    for m in facts["meetings"]:
        m = dict(m)
        if not is_verified(m):
            m["attendance"] = []
        meetings.append(m)
    out = dict(facts)
    out.update(meetings=meetings, motions=mos)
    return out


def _csv(rows: list[dict], cols: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in cols})
    return buf.getvalue()


SRC_COLS = ["source_url", "source_sha256", "page", "fetched_at"]


def tables(facts: dict, all_facts: dict, internal: bool = False, seats: list[dict] | None = None) -> dict[str, str]:
    src = {s["id"]: s for s in facts["sources"]}

    def cite(source_id, page):
        s = src[source_id]
        return {"source_url": s["url"], "source_sha256": s["sha256"], "page": page, "fetched_at": s["fetched_at"]}

    unconfirmed = {}
    for r in all_facts["roll_calls"]:
        if not is_verified(r):
            unconfirmed[r["meeting_id"]] = unconfirmed.get(r["meeting_id"], 0) + 1
    names = {o["id"]: o["name"] for o in facts["officials"]}
    out = {}
    out["officials"] = _csv([dict(o, aliases="; ".join(o["aliases"])) for o in facts["officials"]],
                            ["id", "name", "surname", "given", "title", "aliases"])
    out["meetings"] = _csv([dict(m, unconfirmed_roll_calls=unconfirmed.get(m["id"], 0),
                                 attendance_verified=is_verified(m), **cite(m["source_id"], 1))
                            for m in facts["meetings"]],
                           ["id", "body", "date", "kind", "attendance_status", "attendance_verified",
                            "stated_absent_count", "unconfirmed_roll_calls"] + SRC_COLS)
    out["attendance"] = _csv([dict(a, meeting_id=m["id"], date=m["date"], official_name=names.get(a["official_id"]),
                                   fact_id=f"{m['id']}/att/{a['official_id']}", **cite(m["source_id"], a["page"]))
                              for m in facts["meetings"] for a in m["attendance"]],
                             ["fact_id", "meeting_id", "date", "official_id", "official_name"]
                             + (["raw_name"] if internal else []) + ["status"] + SRC_COLS)
    # the counts as printed only (null stays null); the derived counts the pages show are not exported here
    out["roll_calls"] = _csv([dict(r, **{f"stated_{k}": (r["stated_tally"] or {}).get(k) for k in ("yes", "no", "abstain")},
                                   **cite(r["source_id"], r["page"]))
                              for r in facts["roll_calls"]],
                             ["id", "meeting_id", "item_id", "motion_id", "confirmed", "outcome"]
                             + (["outcome_text"] if internal else []) + ["stated_yes", "stated_no", "stated_abstain"]
                             + SRC_COLS)
    out["votes"] = _csv([dict(v, fact_id=f"{r['id']}/{v['official_id']}", roll_call_id=r["id"],
                              meeting_id=r["meeting_id"], item_id=r["item_id"],
                              official_name=names.get(v["official_id"]), **cite(r["source_id"], r["page"]))
                         for r in facts["roll_calls"] for v in r["votes"]],
                        ["fact_id", "roll_call_id", "meeting_id", "item_id", "official_id", "official_name"]
                        + (["raw_name"] if internal else []) + ["value"] + (["raw_value"] if internal else [])
                        + ["confirmed"] + SRC_COLS)
    out["motions"] = _csv([dict(m, moved_by=(m["moved_by"] or {}).get("official_id"),
                                seconded_by=(m["seconded_by"] or {}).get("official_id"),
                                moved_by_raw=(m["moved_by"] or {}).get("raw_name"),
                                seconded_by_raw=(m["seconded_by"] or {}).get("raw_name"),
                                **cite(m["source_id"], m["page"])) for m in facts["motions"]],
                          ["id", "meeting_id", "item_id", "type_label", "confirmed", "moved_by", "seconded_by"]
                          + (["text", "moved_by_raw", "seconded_by_raw"] if internal else []) + SRC_COLS)
    first = {}
    for e in sorted(facts["item_events"], key=lambda e: (e["date"], e["page"], e["order"])):
        first.setdefault(e["item_id"], e)
    out["items"] = _csv([dict(i, **(cite(first[i["id"]]["source_id"], first[i["id"]]["page"]) if i["id"] in first
                                    else {})) for i in facts["items"]],
                        ["id", "number", "title", "link_basis", "year"] + SRC_COLS)
    out["item_events"] = _csv([dict(e, **cite(e["source_id"], e["page"])) for e in facts["item_events"]],
                              ["id", "item_id", "meeting_id", "date", "type", "label", "ref", "order"] + SRC_COLS)
    out["sources"] = _csv([dict(s, source_url=s["url"], source_sha256=s["sha256"]) for s in facts["sources"]],
                          ["id", "kind", "meeting_date", "pages", "text_layer", "source_url", "source_sha256",
                           "fetched_at"])
    out["seats"] = seats_csv(seats or [], facts, names)
    return out


SEAT_COLS = ["official_id", "official_name", "seat", "seat_label", "dates", "seen_first", "seen_last", "printed_term",
             "dates_basis", "lines", "source_url", "source_sha256", "page", "fetched_at", "last_source_url",
             "last_page"]
DATES_BASIS = {"observed": "first and last meetings whose roll-call tables print this holder in this seat; "
                           "not term dates",
               "sourced": "the term as the source prints it"}


def seats_csv(rows: list[dict], facts: dict, names: dict) -> str:
    """config/localities/<locality>/seats.yml rows as seats.csv. An observed row's dates are seen_first/seen_last
    (never named as a term); a sourced row carries only the source's own wording (printed_term). A source the team
    holds in the store gets its hash and fetch time."""
    import re
    from sitegen.seats import seat_label
    by_url = {s["url"]: s for s in facts["sources"]}

    def split(url):
        url = url or ""
        m = re.search(r"#page=(\d+)$", url)
        return url.split("#")[0], (int(m.group(1)) if m else None)

    out = []
    for r in rows:
        kind = r.get("dates")
        if kind not in DATES_BASIS:
            raise ValueError(f"seat row {r.get('official_id')} {r.get('seat')}: dates must be observed or sourced")
        base, page = split(r.get("source"))
        _, last_page = split(r.get("last_source"))
        s = by_url.get(base) or {}
        obs = kind == "observed"
        out.append({"official_id": r.get("official_id"),
                    "official_name": names.get(r.get("official_id")) or r.get("name"),
                    "seat": r["seat"], "seat_label": seat_label(r["seat"]), "dates": kind,
                    "seen_first": str(r["start"]) if obs and r.get("start") else None,
                    "seen_last": str(r["end"]) if obs and r.get("end") else None,
                    "printed_term": None if obs else r.get("printed"), "dates_basis": DATES_BASIS[kind],
                    "lines": r.get("lines"), "source_url": r.get("source"), "source_sha256": s.get("sha256"),
                    "page": page, "fetched_at": s.get("fetched_at"), "last_source_url": r.get("last_source"),
                    "last_page": last_page})
    return _csv(out, SEAT_COLS)


def export(facts: dict, out_dir: Path, internal: bool = False, seats: list[dict] | None = None) -> list[Path]:
    """`seats`: the raw seat holder rows (config/localities/<locality>/seats.yml); None writes a header-only
    seats.csv (fixture facts are never joined to the real roster)."""
    out_dir = Path(out_dir) / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    sub = strip_raw(public_subset(facts, internal), internal)
    written = []
    p = out_dir / "facts.json"
    p.write_text(json.dumps(sub, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    written.append(p)
    for name, text in tables(sub, facts, internal, seats).items():
        p = out_dir / f"{name}.csv"
        p.write_text(text, encoding="utf-8")
        written.append(p)
    return written
