"""Facts assembly: ParsedMinutes + names.yml -> data/facts.json (schema/facts.schema.json).

Deterministic: lists sorted by id, keys sorted, 2-space indent, trailing newline. Ids come from content position
(source hash, page, position on the page), never from run order.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml

from . import parse as P
from .config import BODY
from .discover import classify
from .names import Resolver, public_officials
from .verify import (attendance_verification, motion_verification, roll_call_verification, source_inconsistent,
                     verification)

ROOT = Path(__file__).resolve().parent.parent
PROCEDURAL = ROOT / "data" / "procedural-titles.yml"
VALUE = {"Yes": ("yes", "Y"), "No": ("no", "N"), "Abstain": ("abstain", "A")}


def norm_title(t: str) -> str:
    return re.sub(r"[\s.,;:!?\-—–]+$", "", " ".join((t or "").split()).casefold())


def load_procedural(path: Path = PROCEDURAL) -> list[re.Pattern]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return [re.compile(p) for p in data.get("patterns", [])]


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def subject_of(clause: str | None) -> str | None:
    """'the foregoing County Clerk's Report was Approved by ...' -> "County Clerk's Report" (verbatim)."""
    if not clause:
        return None
    m = re.search(r"foregoing\s+(.*?)\s+(?:was|were|Failed|Passed)\b", clause, re.I | re.S)
    return m.group(1).strip(" ,") if m else None


class Builder:
    def __init__(self, resolver: Resolver, procedural: list[re.Pattern]):
        self.r = resolver
        self.procedural = procedural
        self.sources, self.meetings, self.motions, self.roll_calls, self.events = [], [], [], [], []
        self.items: dict[str, dict] = {}
        self.item_first: dict[str, tuple] = {}
        self.source_errors: set[str] = set()
        self.unresolved: dict[str, dict] = {}       # raw header/motion name -> {count, examples}
        self.problems: list[dict] = []
        self.doc_summary: list[dict] = []

    # ------------------------------------------------------------ items
    def is_procedural(self, title: str) -> bool:
        t = norm_title(title)
        return any(p.search(t) for p in self.procedural)

    def item_for(self, number: str | None, title: str | None, key: tuple, unique_salt: str) -> str:
        """key = (date, page, order) of this appearance; the earliest appearance sets title and year."""
        if number and P.valid_number(number):
            iid, basis = number, "number"
        else:
            number = None
            t = norm_title(title or "")
            if not t or self.is_procedural(t):
                iid = "t-" + _sha1(f"{t}|{unique_salt}")[:10]
            else:
                iid = "t-" + _sha1(t)[:10]
            basis = "title"
        title = " ".join((title or number or "").split()) or "(untitled)"
        if iid not in self.items or key < self.item_first[iid]:
            self.items[iid] = {"id": iid, "number": number, "title": title, "link_basis": basis,
                               "year": int(key[0][:4])}
            self.item_first[iid] = key
        elif self.items[iid]["title"] in (number, "(untitled)") and title not in (number, "(untitled)"):
            self.items[iid]["title"] = title                 # a later appearance supplies the first real title
        return iid

    def note_unresolved(self, raw: str, where: str) -> None:
        u = self.unresolved.setdefault(raw, {"count": 0, "examples": []})
        u["count"] += 1
        if len(u["examples"]) < 3:
            u["examples"].append(where)

    # ------------------------------------------------------------ one document
    def add(self, pm) -> None:
        src = pm.source
        sha = src["sha256"]
        sid, s8 = f"src-{sha[:12]}", sha[:8]
        att = pm.attendance
        cls = classify(src.get("label") or "") or {}
        date = (att.date if att and att.date else None) or (src.get("meeting_date") if re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", src.get("meeting_date") or "") else None)
        if not date:
            self.problems.append({"source": sid, "url": src["url"], "problem": "no meeting date in header or index"})
            return
        if att and att.date and cls.get("year") and int(att.date[:4]) != cls["year"]:
            self.problems.append({"source": sid, "url": src["url"],
                                  "problem": f"header date {att.date} disagrees with index label {src.get('label')!r}"})
        kind = cls.get("kind", "formal")
        mid = f"{date}-{kind}"
        n = 2
        while any(m["id"] == mid for m in self.meetings):
            mid = f"{date}-{kind}-{n}"
            n += 1
        self.sources.append({"id": sid, "url": src["url"], "sha256": sha, "kind": src.get("kind") or "minutes",
                             "meeting_date": date, "fetched_at": (src.get("first_fetched_at") or "")[:10],
                             "pages": pm.pages, "text_layer": pm.text_layer})
        where = f"{sid} p{att.page if att else 1}"

        # attendance
        hmap: dict[str, str | None] = {}
        attendance, unresolved = [], []
        if att and (att.present or att.absent):
            for status, names in (("present", att.present), ("absent", att.absent)):
                for nm in names:
                    oid = self.r.exact_match(nm)
                    hmap[nm] = oid
                    if oid is None:
                        unresolved.append(nm)
                        self.note_unresolved(nm, where)
                    attendance.append({"official_id": oid, "raw_name": nm, "status": status, "page": att.page})
            mver = attendance_verification(att, unresolved)
            status = "extracted"
        else:
            mver = verification([{"check": "attendance_section_found", "ok": False,
                                  "detail": "; ".join(att.reasons) if att else "no BE IT REMEMBERED header"}])
            status = "not_extracted"
        ids = [a["official_id"] for a in attendance]
        if len(set(i for i in ids if i)) != len([i for i in ids if i]):
            mver = verification(mver["checks"] + [{"check": "one_entry_per_official", "ok": False,
                                                   "detail": "two header names resolve to one official"}])
        self.meetings.append({"id": mid, "body": BODY, "date": date, "kind": kind, "source_id": sid,
                              "attendance_status": status,
                              "attendance": sorted(attendance, key=lambda a: (a["status"], a["raw_name"])),
                              "stated_absent_count": att.absent_count if att and status == "extracted" else None,
                              "verification": mver})
        roster_ids = {i for i in ids if i}
        present_ids = {a["official_id"] for a in attendance if a["status"] == "present" and a["official_id"]}

        events: list[dict] = []          # without ids yet: {sort, ...}

        def ev(item_id, etype, label, ref, page, order, rank):
            events.append({"item_id": item_id, "meeting_id": mid, "date": date, "type": etype,
                           "label": " ".join((label or "").split()) or etype, "ref": ref, "source_id": sid,
                           "page": page, "order": order, "_rank": rank})

        # agenda listings
        for e in pm.agenda:
            iid = self.item_for(e.number, e.title, (date, e.page, e.order), f"{sid}-p{e.page}-{e.order}")
            ev(iid, "listed", e.label, None, e.page, e.order, 0)

        # roll calls and motions
        lines_page = pm.page_of_line
        consent_rcs = []
        for rc in pm.roll_calls:
            rid = f"rc-{s8}-p{rc.page}-{rc.ordinal_on_page}"
            order = rc.line - next(i for i, p in enumerate(lines_page) if p == rc.page) if lines_page else 0
            best = next((r for r in rc.readings if r.votes is rc.votes), rc.readings[0] if rc.readings else None)
            votes = []
            for member, v in sorted(rc.votes.items()):
                raw = best.raw_names.get(member, member) if best else member
                if v in VALUE:
                    votes.append({"official_id": hmap.get(member), "raw_name": raw, "value": VALUE[v][0],
                                  "raw_value": VALUE[v][1]})
                elif v == "?":
                    votes.append({"official_id": hmap.get(member), "raw_name": raw, "value": "other",
                                  "raw_value": "unreadable"})
            oc = P._outcome_class(rc.outcome_text)
            rver = roll_call_verification(rc, unresolved)
            if source_inconsistent(rc):
                self.source_errors.add(rid)
                rver["checks"].append({"check": "source_consistent", "ok": False,
                                       "detail": "readings agree; the minutes contradict themselves (vote mark vs "
                                                 "ABSENT line)"})
                rver = verification(rver["checks"])
            clause = rc.outcome_clause or rc.outcome_text or ""
            if rc.kind == "consent":
                iid = self.item_for(None, "Consent Agenda", (date, rc.page, order), rid)
                consent_rcs.append((rc, rid, iid))
            else:
                title = (pm.titles.get(rc.item) if rc.item else None) or subject_of(clause) or rc.motion_text
                iid = self.item_for(rc.item, title, (date, rc.page, order), rid)
            moid = None
            if rc.raw_mover is not None:
                moid = f"mo-{s8}-p{rc.page}-{rc.ordinal_on_page}"
                refs = []
                for raw in (rc.raw_mover, rc.raw_seconder):
                    oid, _rule = self.r.resolve(raw, roster_ids)
                    if oid is None:
                        self.note_unresolved(f"Commissioner {raw}", f"{sid} p{rc.page}")
                    refs.append({"official_id": oid, "raw_name": raw})
                self.motions.append({"id": moid, "meeting_id": mid, "item_id": iid, "text": rc.motion_text or "",
                                     "moved_by": refs[0], "seconded_by": refs[1], "source_id": sid, "page": rc.page,
                                     "verification": motion_verification(refs[0], refs[1], present_ids, True)})
                ev(iid, "motion", rc.motion_text, moid, rc.page, max(order - 1, 0), 1)
            self.roll_calls.append({
                "id": rid, "meeting_id": mid, "item_id": iid, "motion_id": moid, "votes": votes,
                "stated_tally": ({"yes": rc.tally[0], "no": rc.tally[1], "abstain": rc.tally[2]} if rc.tally else None),
                "outcome": {"pass": "passed", "fail": "failed"}.get(oc, "other"),
                "outcome_text": " ".join(clause.split()), "source_id": sid, "page": rc.page, "verification": rver})
            ev(iid, "roll_call", clause, rid, rc.page, order, 2)

        # consent lists: each listed item gets the consent roll call as an event on its own history
        for cl in pm.consent_lists:
            nxt = next(((rc, rid, iid) for rc, rid, iid in consent_rcs if rc.line > cl.line), None)
            for e in cl.entries:
                if e.number and e.number in cl.pulled:
                    continue
                iid = self.item_for(e.number, e.title, (date, e.page, e.order), f"{sid}-p{e.page}-{e.order}")
                if nxt:
                    ev(iid, "roll_call", cl.label, nxt[1], e.page, e.order, 3)
                    ev(nxt[2], "other", e.label, None, e.page, e.order, 4)
                else:
                    ev(iid, "other", cl.label, None, e.page, e.order, 3)

        # ids: ev-<sha8>-p<page>-<n>, n by position on the page
        events.sort(key=lambda x: (x["page"], x["order"], x["_rank"], x["item_id"]))
        count: dict[int, int] = {}
        for x in events:
            k = count.get(x["page"], 0)
            count[x["page"]] = k + 1
            x["id"] = f"ev-{s8}-p{x['page']}-{k}"
            del x["_rank"]
            self.events.append(x)
        self.doc_summary.append({"source_id": sid, "label": src.get("label"), "meeting_id": mid, "pages": pm.pages,
                                 "roll_calls": len(pm.roll_calls),
                                 "verified": sum(r.status == "Verified" for r in pm.roll_calls),
                                 "attendance": status, "image_only_pages": len(pm.image_only_pages)})

    # ------------------------------------------------------------ output
    def facts(self, officials: list[dict]) -> dict:
        dates = [m["date"] for m in self.meetings]
        return {
            "schema_version": "1.0",
            "coverage": {"body": BODY, "from": min(dates) if dates else "2020-01-01",
                         "to": max(dates) if dates else "2024-12-31"},
            "sources": sorted(self.sources, key=lambda x: x["id"]),
            "officials": public_officials(officials),
            "meetings": sorted(self.meetings, key=lambda x: x["id"]),
            "items": sorted(self.items.values(), key=lambda x: x["id"]),
            "item_events": sorted(self.events, key=lambda x: x["id"]),
            "motions": sorted(self.motions, key=lambda x: x["id"]),
            "roll_calls": sorted(self.roll_calls, key=lambda x: x["id"]),
            "corrections": [],
        }


def dumps(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_if_changed(path: Path, text: str) -> bool:
    path = Path(path)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True
