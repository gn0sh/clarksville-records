"""Open-data export (G5): build/site/data/facts.json and CSVs, verified facts only.

A guessed value under a named person is the harm P3 prevents, so nothing unverified is exported: held-back roll
calls and motions are left out, attendance of a meeting whose attendance check failed is left out, and the meeting
rows carry the held-back counts instead. Every fact row carries source_url, source_sha256, page and fetched_at.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

CSV_FILES = ("officials", "meetings", "attendance", "roll_calls", "votes", "motions", "items", "item_events", "sources")


def is_verified(x: dict) -> bool:
    return x.get("verification", {}).get("status") == "verified"


def verified_subset(facts: dict) -> dict:
    rcs = [r for r in facts["roll_calls"] if is_verified(r)]
    mos = [m for m in facts["motions"] if is_verified(m)]
    keep_refs = {r["id"] for r in rcs} | {m["id"] for m in mos}
    events = [e for e in facts["item_events"] if e["ref"] is None or e["ref"] in keep_refs]
    item_ids = {e["item_id"] for e in events} | {r["item_id"] for r in rcs} | {m["item_id"] for m in mos}
    meetings = []
    for m in facts["meetings"]:
        m = dict(m)
        if not is_verified(m):
            m["attendance"] = []
        meetings.append(m)
    rcs = [dict(r, motion_id=r["motion_id"] if r["motion_id"] in keep_refs else None) for r in rcs]
    out = dict(facts)
    out.update(meetings=meetings, roll_calls=rcs, motions=mos, item_events=events,
               items=[i for i in facts["items"] if i["id"] in item_ids])
    return out


def _csv(rows: list[dict], cols: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in cols})
    return buf.getvalue()


SRC_COLS = ["source_url", "source_sha256", "page", "fetched_at"]


def tables(facts: dict, all_facts: dict) -> dict[str, str]:
    src = {s["id"]: s for s in facts["sources"]}

    def cite(source_id, page):
        s = src[source_id]
        return {"source_url": s["url"], "source_sha256": s["sha256"], "page": page, "fetched_at": s["fetched_at"]}

    held = {}
    for r in all_facts["roll_calls"]:
        if not is_verified(r):
            held[r["meeting_id"]] = held.get(r["meeting_id"], 0) + 1
    names = {o["id"]: o["name"] for o in facts["officials"]}
    out = {}
    out["officials"] = _csv([dict(o, aliases="; ".join(o["aliases"])) for o in facts["officials"]],
                            ["id", "name", "surname", "given", "title", "aliases"])
    out["meetings"] = _csv([dict(m, held_back_roll_calls=held.get(m["id"], 0),
                                 attendance_verified=is_verified(m), **cite(m["source_id"], 1))
                            for m in facts["meetings"]],
                           ["id", "body", "date", "kind", "attendance_status", "attendance_verified",
                            "stated_absent_count", "held_back_roll_calls"] + SRC_COLS)
    out["attendance"] = _csv([dict(a, meeting_id=m["id"], date=m["date"], official_name=names.get(a["official_id"]),
                                   fact_id=f"{m['id']}/att/{a['official_id']}", **cite(m["source_id"], a["page"]))
                              for m in facts["meetings"] for a in m["attendance"]],
                             ["fact_id", "meeting_id", "date", "official_id", "official_name", "raw_name", "status"]
                             + SRC_COLS)
    out["roll_calls"] = _csv([dict(r, yes=(r["stated_tally"] or {}).get("yes"), no=(r["stated_tally"] or {}).get("no"),
                                   abstain=(r["stated_tally"] or {}).get("abstain"), **cite(r["source_id"], r["page"]))
                              for r in facts["roll_calls"]],
                             ["id", "meeting_id", "item_id", "motion_id", "outcome", "outcome_text", "yes", "no",
                              "abstain"] + SRC_COLS)
    out["votes"] = _csv([dict(v, fact_id=f"{r['id']}/{v['official_id']}", roll_call_id=r["id"],
                              meeting_id=r["meeting_id"], item_id=r["item_id"],
                              official_name=names.get(v["official_id"]), **cite(r["source_id"], r["page"]))
                         for r in facts["roll_calls"] for v in r["votes"]],
                        ["fact_id", "roll_call_id", "meeting_id", "item_id", "official_id", "official_name", "raw_name",
                         "value", "raw_value"] + SRC_COLS)
    out["motions"] = _csv([dict(m, moved_by=(m["moved_by"] or {}).get("official_id"),
                                moved_by_raw=(m["moved_by"] or {}).get("raw_name"),
                                seconded_by=(m["seconded_by"] or {}).get("official_id"),
                                seconded_by_raw=(m["seconded_by"] or {}).get("raw_name"),
                                **cite(m["source_id"], m["page"])) for m in facts["motions"]],
                          ["id", "meeting_id", "item_id", "text", "moved_by", "moved_by_raw", "seconded_by",
                           "seconded_by_raw"] + SRC_COLS)
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


def export(facts: dict, out_dir: Path) -> list[Path]:
    out_dir = Path(out_dir) / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    sub = verified_subset(facts)
    written = []
    p = out_dir / "facts.json"
    p.write_text(json.dumps(sub, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    written.append(p)
    for name, text in tables(sub, facts).items():
        p = out_dir / f"{name}.csv"
        p.write_text(text, encoding="utf-8")
        written.append(p)
    return written
