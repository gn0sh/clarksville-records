"""One copy of each meeting: choose which document's minutes stand for a meeting (written rule, G2).

The same meeting's minutes can sit in more than one document: a meeting's own minutes document, and the next
meeting's document, which carries them again "SUBMITTED FOR APPROVAL" (as a short summary nested in the next
minutes, or as the whole minutes in an agenda packet). Facts are emitted for exactly one copy per meeting
(date + kind, both read from the minutes' own header text). The rule, applied the same way to every meeting:

1. The official copy wins: the document's own minutes (role "own": top level, no "for approval" banner) over a
   copy submitted for approval in another document ("for_approval", top level) over a copy nested inside another
   meeting's minutes ("attached").
2. A copy whose boundaries are certain beats one whose adjournment line was not read.
3. Then the copy with more vote tables, then more pages of minutes, then the lower source hash (only so the
   choice is deterministic).

Never by how many of its roll calls verify, and never by who is in it. Every choice with more than one copy is
written to build/report.json ("meeting_copies") with the copies it dropped.
"""
from __future__ import annotations

ROLE_RANK = {"own": 0, "for_approval": 1, "attached": 2}


def _key(pm) -> tuple:
    sg = pm.segment
    return (ROLE_RANK.get(sg.role, 3), 0 if sg.certain else 1, -len(pm.roll_calls), -(sg.end_page - sg.page + 1),
            pm.source["sha256"])


def describe(pm) -> dict:
    sg = pm.segment
    return {"source_id": f"src-{pm.source['sha256'][:12]}", "label": pm.source.get("label"),
            "pages": [sg.page, sg.end_page], "role": sg.role, "boundaries_certain": sg.certain,
            "roll_calls": len(pm.roll_calls)}


def choose(docs: list) -> tuple[list, list[dict], list[dict]]:
    """docs: [ParsedDocument]. Returns (chosen [ParsedMinutes] in document order, copies [decision records],
    undated [segments with no readable date, never emitted])."""
    groups: dict[tuple, list] = {}
    undated = []
    for d in docs:
        for pm in d.meetings:
            if not pm.meeting_date:
                undated.append({**describe(pm), "problem": "no readable meeting date in the header",
                                "date_how": pm.segment.date_how})
                continue
            groups.setdefault((pm.meeting_date, pm.kind), []).append(pm)
    chosen, copies = [], []
    for (date, kind), group in sorted(groups.items()):
        ranked = sorted(group, key=_key)
        chosen.append(ranked[0])
        if len(ranked) > 1:
            copies.append({"meeting_id": f"{date}-{kind}", "chosen": describe(ranked[0]),
                           "dropped": [describe(pm) for pm in ranked[1:]],
                           "rule": "collector/meetings.py: own > for_approval > attached; certain bounds; more vote "
                                   "tables; more pages; lower source hash"})
    order = {id(pm): (pm.source["sha256"], pm.segment.start) for pm in chosen}
    chosen.sort(key=lambda pm: order[id(pm)])
    return chosen, copies, undated
