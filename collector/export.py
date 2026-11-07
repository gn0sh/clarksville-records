"""Open-data export (G5): build/site/data/facts.json and CSVs, the facts the public pages show.

Invariant: held-back counts (architecture). Every roll call and vote is exported with `confirmed` (true when the roll
call passed its checks). A vote whose name did not resolve has `official_id: null` and no name, so no value is placed
under a guessed person (P3). Motions carry `confirmed` and only the attribution the pages show. Attendance of a meeting
whose attendance check failed is left out. Every fact row carries source_url, source_sha256, page and fetched_at.
Raw OCR fields (raw names, raw vote wording, outcome text, motion text, motion and roll call event labels) are in
internal builds only.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

CSV_FILES = ("officials", "meetings", "attendance", "roll_calls", "votes", "motions", "items", "item_events", "sources")


def is_verified(x: dict) -> bool:
    return x.get("verification", {}).get("status") == "verified"


def strip_raw(facts: dict, internal: bool = False) -> dict:
    """The public export carries no raw OCR text: ids, resolved official ids, verified status, type label and
    source links only. Raw name and motion-text fields exist only in internal builds."""
    from sitegen.views import motion_type_label

    def clean(row, drop=("raw_name",)):
        return row if internal or not row else {k: v for k, v in row.items() if k not in drop}

    out = dict(facts)
    out["motions"] = [dict({k: v for k, v in m.items() if internal or k != "text"}, type_label=motion_type_label(m["text"]),
                           moved_by=clean(m["moved_by"]), seconded_by=clean(m["seconded_by"]))
                      for m in facts["motions"]]
    out["roll_calls"] = [dict(clean(r, ("outcome_text",)), confirmed=is_verified(r),
                              votes=[dict(clean(v, ("raw_name", "raw_value")), confirmed=is_verified(r))
                                     for v in r["votes"]])
                         for r in facts["roll_calls"]]
    out["item_events"] = [e if internal or e["type"] not in ("motion", "roll_call") else dict(e, label="")
                          for e in facts["item_events"]]
    out["meetings"] = [dict(m, attendance=[clean(a) for a in m["attendance"]]) for m in facts["meetings"]]
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


def tables(facts: dict, all_facts: dict, internal: bool = False) -> dict[str, str]:
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
    out["roll_calls"] = _csv([dict(r, yes=(r["stated_tally"] or {}).get("yes"), no=(r["stated_tally"] or {}).get("no"),
                                   abstain=(r["stated_tally"] or {}).get("abstain"), **cite(r["source_id"], r["page"]))
                              for r in facts["roll_calls"]],
                             ["id", "meeting_id", "item_id", "motion_id", "confirmed", "outcome"]
                             + (["outcome_text"] if internal else []) + ["yes", "no", "abstain"] + SRC_COLS)
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
    return out


def export(facts: dict, out_dir: Path, internal: bool = False) -> list[Path]:
    out_dir = Path(out_dir) / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    sub = strip_raw(public_subset(facts, internal), internal)
    written = []
    p = out_dir / "facts.json"
    p.write_text(json.dumps(sub, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    written.append(p)
    for name, text in tables(sub, facts, internal).items():
        p = out_dir / f"{name}.csv"
        p.write_text(text, encoding="utf-8")
        written.append(p)
    return written
