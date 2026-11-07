"""View functions: turn the facts contract into plain dicts for the templates.

Neutrality (N1-N3): there is one function per page type, used for every official, meeting and item. Nothing here
takes an official-specific flag, ranks by a count, or derives a label other than the fixed mappings in config.py.
Only verified facts reach a public page; unverified facts appear only in `review()`.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict

from . import config


# ---------------------------------------------------------------------------------------------------------------
# Small shared helpers


def plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def vote_label(value: str, raw_value: str) -> str:
    """N2: one mapping. `other` keeps the minutes' own wording."""
    if value == "yes":
        return "Yes"
    if value == "no":
        return "No"
    if value == "abstain":
        return "Abstain"
    return f"Other: {raw_value}"


def name_key(o: dict) -> tuple:
    return (o["surname"].casefold(), o["given"].casefold(), o["id"])


def is_verified(fact: dict) -> bool:
    return fact["verification"]["status"] == "verified"


def attendance_shown(meeting: dict) -> bool:
    """Attendance is shown (and counted) only when extracted and verified."""
    return meeting["attendance_status"] == "extracted" and is_verified(meeting)


def attendance_state(meeting: dict) -> str:
    """One of `shown`, `not_extracted`, `under_review`. Same rule for the meeting page and the totals."""
    if meeting["attendance_status"] == "not_extracted":
        return "not_extracted"
    return "shown" if is_verified(meeting) else "under_review"


def normalise_name(raw: str) -> str:
    """Merge rule 1 (architecture, Names and merge rules): NFKC, trim, drop leading titles, drop `.` and `,`,
    collapse spaces, casefold."""
    s = unicodedata.normalize("NFKC", raw).strip()
    dropped = True
    while dropped:
        dropped = False
        for title in config.NAME_TITLES:
            if s.casefold().startswith(title.casefold()) and (len(s) == len(title) or s[len(title)].isspace()):
                s, dropped = s[len(title):].lstrip(), True
                break
    s = s.replace(".", "").replace(",", "")
    return re.sub(r"\s+", " ", s).strip().casefold()


class Index:
    """Lookup tables over one facts dict."""

    def __init__(self, facts: dict):
        self.facts = facts
        self.officials = {o["id"]: o for o in facts["officials"]}
        self.sources = {s["id"]: s for s in facts["sources"]}
        self.meetings = {m["id"]: m for m in facts["meetings"]}
        self.items = {i["id"]: i for i in facts["items"]}
        self.motions = {m["id"]: m for m in facts["motions"]}
        self.roll_calls = {r["id"]: r for r in facts["roll_calls"]}
        self.events_by_ref = {e["ref"]: e for e in facts["item_events"] if e["ref"]}
        self.events_by_item: dict[str, list] = defaultdict(list)
        for e in facts["item_events"]:
            self.events_by_item[e["item_id"]].append(e)
        self.rc_by_motion = {r["motion_id"]: r for r in facts["roll_calls"] if r["motion_id"] and is_verified(r)}
        # Merge rules 1-2 only (exact match after normalising). Used to place a raw name at a meeting for the
        # G4 held-back count; never used to attribute a shown fact.
        self.official_by_name: dict[str, set] = defaultdict(set)
        for o in facts["officials"]:
            for n in [o["name"], *o["aliases"]]:
                self.official_by_name[normalise_name(n)].add(o["id"])
        self.coverage = facts["coverage"]
        self.fixture = bool(facts.get("fixture"))

    # -- generic builders ------------------------------------------------------------------------------------
    def src(self, source_id: str, page: int) -> dict:
        s = self.sources[source_id]
        return {"url": f"{s['url']}#page={page}", "page": page, "fetched": s["fetched_at"], "kind": s["kind"]}

    def position(self, fact: dict) -> tuple:
        """Document order: page, then position on the page when an item event records it."""
        ev = self.events_by_ref.get(fact["id"])
        return (fact["page"], ev["order"] if ev else 0, fact["id"])

    def meeting_label(self, m: dict) -> str:
        return f"{m['date']}, {config.KIND_LABELS[m['kind']].lower()}"

    def person(self, ref: dict | None) -> dict | None:
        if ref is None:
            return None
        oid = ref["official_id"]
        if oid and oid in self.officials:
            return {"name": self.officials[oid]["name"], "href": f"officials/{oid}.html"}
        return {"name": ref["raw_name"], "href": None}

    def item_ref(self, item_id: str) -> dict:
        it = self.items.get(item_id)
        if it is None:
            return {"id": item_id, "number": None, "title": item_id, "href": None}
        return {"id": it["id"], "number": it["number"], "title": it["title"],
                "href": f"items/{it['year']}.html#{it['id']}"}

    def data_as_of(self) -> str:
        dates = [s["fetched_at"] for s in self.facts["sources"]]
        return max(dates) if dates else "unknown"

    def fetched_sentence(self) -> str:
        dates = sorted({s["fetched_at"] for s in self.facts["sources"]})
        if not dates:
            return "No minutes have been fetched yet."
        if len(dates) == 1:
            return f"Minutes fetched on {dates[0]}."
        return f"Minutes fetched between {dates[0]} and {dates[-1]}."

    def item_years(self) -> list[int]:
        return sorted({i["year"] for i in self.facts["items"]})


def _ix(facts) -> Index:
    return facts if isinstance(facts, Index) else Index(facts)


def site_context(facts) -> dict:
    ix = _ix(facts)
    return {
        "site_name": config.SITE_NAME,
        "operator": config.OPERATOR_NAME,
        "data_as_of": ix.data_as_of(),
        "fixture": ix.fixture,
        "item_years": ix.item_years(),
        "internal": False,
    }


# ---------------------------------------------------------------------------------------------------------------
# F2: officials index and official page


def officials_index(facts) -> dict:
    ix = _ix(facts)
    officials = sorted(ix.facts["officials"], key=name_key)
    meetings = sorted(ix.facts["meetings"], key=lambda m: (m["date"], m["id"]), reverse=True)
    return {
        "officials": [{"name": o["name"], "title": o["title"], "href": f"officials/{o['id']}.html"} for o in officials],
        "meetings": [{"label": ix.meeting_label(m), "date": m["date"], "href": f"meetings/{m['id']}.html"}
                     for m in meetings],
        "coverage": ix.coverage,
    }


def meeting_people(ix: Index, m: dict) -> set:
    """Officials who appear at a meeting in any raw form: an attendance entry, a vote or a Moved/Seconded name, by
    resolved id or by a raw name that matches a name or listed variant exactly after normalising (merge rules 1-2).
    Used only for the G4 held-back count when the meeting's attendance is not usable."""
    refs = list(m["attendance"])
    refs += [v for r in ix.facts["roll_calls"] if r["meeting_id"] == m["id"] for v in r["votes"]]
    refs += [p for mo in ix.facts["motions"] if mo["meeting_id"] == m["id"]
             for p in (mo["moved_by"], mo["seconded_by"]) if p is not None]
    people = set()
    for ref in refs:
        if ref["official_id"] in ix.officials:
            people.add(ref["official_id"])
        people |= ix.official_by_name.get(normalise_name(ref["raw_name"]), set())
    return people


def held_eligibility(ix: Index) -> tuple[dict, int]:
    """G4 eligibility (architecture, Verifier): an unverified roll call counts for an official when the meeting's
    attendance lists them, whatever names the roll call's own votes resolved to. When that meeting's attendance is not
    usable (not extracted, or under review), it counts for every official who appears there in any raw form. When no
    official can be placed at the meeting at all, it goes into one site-wide total instead.
    Returns ({official_id: held count}, unplaced count)."""
    held: dict[str, int] = defaultdict(int)
    unplaced = 0
    for rc in ix.facts["roll_calls"]:
        if is_verified(rc):
            continue
        m = ix.meetings[rc["meeting_id"]]
        if attendance_shown(m):
            people = {a["official_id"] for a in m["attendance"]}
        else:
            people = meeting_people(ix, m)
        if not people:
            unplaced += 1
        for oid in people:
            held[oid] += 1
    return held, unplaced


def totals_sentences(ix: Index, official_id: str) -> list[str]:
    """N3/P4/AC2.3: four fixed sentences, same wording and order for everyone. Only the numbers differ."""
    cov = ix.coverage
    listed = [m for m in ix.facts["meetings"]
              if attendance_shown(m) and any(a["official_id"] == official_id for a in m["attendance"])]
    absent = sum(1 for m in listed
                 if any(a["official_id"] == official_id and a["status"] == "absent" for a in m["attendance"]))
    held, unplaced = held_eligibility(ix)
    held_rc = held.get(official_id, 0)
    states = [attendance_state(m) for m in ix.facts["meetings"]]
    not_extracted = states.count("not_extracted")
    under_review = states.count("under_review")
    held_sentence = (
        f"{held_rc} {plural(held_rc, 'roll call', 'roll calls')} in this period "
        f"{plural(held_rc, 'is', 'are')} not shown because {plural(held_rc, 'it is', 'they are')} under review.")
    if unplaced:
        # A site-wide number: the same clause, with the same number, on every official's page.
        held_sentence += (
            f" A further {unplaced} {plural(unplaced, 'roll call', 'roll calls')} under review "
            f"{plural(unplaced, 'is', 'are')} at meetings where no member's name could be read, and "
            f"{plural(unplaced, 'is', 'are')} not counted for anyone.")
    return [
        f"Recorded absent at {absent} of {len(listed)} meetings with an extracted attendance section, "
        f"{cov['from']} to {cov['to']}.",
        held_sentence,
        f"{not_extracted} {plural(not_extracted, 'meeting', 'meetings')} in this period "
        f"{plural(not_extracted, 'has', 'have')} no extracted attendance section and "
        f"{plural(not_extracted, 'is', 'are')} not counted.",
        f"{under_review} {plural(under_review, 'meeting', 'meetings')} in this period "
        f"{plural(under_review, 'has', 'have')} an attendance section that is under review and "
        f"{plural(under_review, 'is', 'are')} not counted.",
    ]


def official(official_id: str, facts) -> dict:
    ix = _ix(facts)
    o = ix.officials[official_id]
    rows: list[dict] = []

    def base(kind, meeting_id, fact_id, source_id, page, anchor=""):
        m = ix.meetings[meeting_id]
        return {
            "type": kind, "type_label": config.TYPE_LABELS[kind], "date": m["date"], "year": m["date"][:4],
            "meeting_label": ix.meeting_label(m), "meeting_href": f"meetings/{meeting_id}.html{anchor}",
            "fact_id": fact_id, "src": ix.src(source_id, page), "page": page,
            "item": None, "motion_text": None, "record": "", "outcome": None, "pos": 0,
        }

    for rc in ix.facts["roll_calls"]:
        if not is_verified(rc):
            continue
        for v in rc["votes"]:
            if v["official_id"] != official_id:
                continue
            r = base("vote", rc["meeting_id"], f"{rc['id']}/{official_id}", rc["source_id"], rc["page"],
                     f"#{rc['id']}")
            r["item"] = ix.item_ref(rc["item_id"])
            mo = ix.motions.get(rc["motion_id"]) if rc["motion_id"] else None
            r["motion_text"] = mo["text"] if mo else None  # a failed motion check holds back only the attribution
            r["record"] = vote_label(v["value"], v["raw_value"])
            r["outcome"] = {"label": config.OUTCOME_LABELS[rc["outcome"]], "text": rc["outcome_text"]}
            r["pos"] = ix.position(rc)[1]
            rows.append(r)

    for m in ix.facts["meetings"]:
        if not attendance_shown(m):
            continue
        for a in m["attendance"]:
            if a["official_id"] != official_id:
                continue
            r = base("attendance", m["id"], f"{m['id']}/att/{official_id}", m["source_id"], a["page"], "#attendance")
            r["record"] = "Present" if a["status"] == "present" else "Absent"
            rows.append(r)

    for mo in ix.facts["motions"]:
        if not is_verified(mo):
            continue
        for role, kind, ref in (("moved", "moved", mo["moved_by"]), ("seconded", "seconded", mo["seconded_by"])):
            if ref is None or ref["official_id"] != official_id:
                continue
            r = base(kind, mo["meeting_id"], f"{mo['id']}/{role}", mo["source_id"], mo["page"], f"#{mo['id']}")
            r["item"] = ix.item_ref(mo["item_id"])
            r["record"] = mo["text"]
            rc = ix.rc_by_motion.get(mo["id"])
            if rc:
                r["outcome"] = {"label": config.OUTCOME_LABELS[rc["outcome"]], "text": rc["outcome_text"]}
            r["pos"] = ix.position(mo)[1]
            rows.append(r)

    # Newest first; ties by source page then position, then type, then id (stable, no count involved).
    rows.sort(key=lambda r: (r["page"], r["pos"], config.HISTORY_TYPES.index(r["type"]), r["fact_id"]))
    rows.sort(key=lambda r: r["date"], reverse=True)

    cov = ix.coverage
    years = sorted({r["year"] for r in rows}, reverse=True)
    return {
        "official": o,
        "coverage_sentence": f"Shows {cov['body']} records from {cov['from']} to {cov['to']}. {ix.fetched_sentence()}",
        "totals": totals_sentences(ix, official_id),
        "rows": rows,
        "years": years,
        "types": [(t, config.TYPE_LABELS[t]) for t in config.HISTORY_TYPES],
    }


# ---------------------------------------------------------------------------------------------------------------
# F3: meeting and item pages


def _vote_rows(ix: Index, rc: dict) -> list[dict]:
    def key(v):
        o = ix.officials.get(v["official_id"])
        return name_key(o) if o else (v["raw_name"].casefold(), "", "")

    return [{"who": ix.person({"official_id": v["official_id"], "raw_name": v["raw_name"]}),
             "label": vote_label(v["value"], v["raw_value"])} for v in sorted(rc["votes"], key=key)]


def _motion_block(ix: Index, mo: dict) -> dict:
    """Architecture (Verifier): a failed motion check holds back the Moved/Seconded attribution only. The motion text
    is shown verbatim either way; when held, both names are replaced by one fixed sentence."""
    held = not is_verified(mo)
    return {
        "kind": "motion", "id": mo["id"], "item": ix.item_ref(mo["item_id"]), "text": mo["text"],
        "attribution_held": held,
        "moved_by": None if held else ix.person(mo["moved_by"]),
        "seconded_by": None if held else ix.person(mo["seconded_by"]),
        "src": ix.src(mo["source_id"], mo["page"]),
    }


def _roll_call_block(ix: Index, rc: dict) -> dict:
    mo = ix.motions.get(rc["motion_id"]) if rc["motion_id"] else None
    return {
        "kind": "roll_call", "id": rc["id"], "item": ix.item_ref(rc["item_id"]),
        "motion_text": mo["text"] if mo else None,  # verbatim even when the motion's attribution is held back
        "votes": _vote_rows(ix, rc),
        "outcome": {"label": config.OUTCOME_LABELS[rc["outcome"]], "text": rc["outcome_text"]},
        "src": ix.src(rc["source_id"], rc["page"]),
    }


def meeting(meeting_id: str, facts) -> dict:
    ix = _ix(facts)
    m = ix.meetings[meeting_id]
    src = ix.sources[m["source_id"]]

    att_state = attendance_state(m)
    attendance = []
    if att_state == "shown":
        def key(a):
            o = ix.officials.get(a["official_id"])
            return name_key(o) if o else (a["raw_name"].casefold(), "", "")

        for a in sorted(m["attendance"], key=key):
            attendance.append({
                "who": ix.person({"official_id": a["official_id"], "raw_name": a["raw_name"]}),
                "status": "Present" if a["status"] == "present" else "Absent",
                "fact_id": f"{m['id']}/att/{a['official_id']}", "src": ix.src(m["source_id"], a["page"]),
            })

    motions = [mo for mo in ix.facts["motions"] if mo["meeting_id"] == m["id"]]
    rcs = [rc for rc in ix.facts["roll_calls"] if rc["meeting_id"] == m["id"]]
    shown = [(ix.position(mo), _motion_block(ix, mo)) for mo in motions]
    shown += [(ix.position(rc), _roll_call_block(ix, rc)) for rc in rcs if is_verified(rc)]
    shown.sort(key=lambda t: t[0])
    held_rc = sum(1 for rc in rcs if not is_verified(rc))
    return {
        "meeting": m, "label": ix.meeting_label(m),
        "kind_label": config.KIND_LABELS[m["kind"]],
        "doc": {"url": src["url"], "kind": src["kind"], "fetched": src["fetched_at"], "pages": src["pages"]},
        "attendance_state": att_state, "attendance": attendance,
        "blocks": [b for _, b in shown],
        "held_roll_calls": held_rc,
        "held_roll_calls_text": (f"{held_rc} {plural(held_rc, 'roll call', 'roll calls')} at this meeting "
                                 f"{plural(held_rc, 'is', 'are')} under review and not shown." if held_rc else ""),
    }


def _event(ix: Index, e: dict) -> dict:
    out = {
        "id": e["id"], "date": e["date"], "type_label": config.EVENT_TYPE_LABELS[e["type"]], "type": e["type"],
        "label": e["label"], "meeting_href": f"meetings/{e['meeting_id']}.html",
        "meeting_label": ix.meeting_label(ix.meetings[e["meeting_id"]]),
        "src": ix.src(e["source_id"], e["page"]), "held_back": False, "motion": None, "roll_call": None,
    }
    ref = e["ref"]
    if e["type"] == "roll_call" and ref in ix.roll_calls:
        rc = ix.roll_calls[ref]
        if is_verified(rc):
            out["roll_call"] = _roll_call_block(ix, rc)
            out["meeting_href"] += f"#{rc['id']}"
        else:
            out.update(held_back=True, id=None, label=None)
    elif e["type"] == "motion" and ref in ix.motions:
        mo = ix.motions[ref]
        out["motion"] = _motion_block(ix, mo)  # attribution held inside the block when the motion is unverified
        out["meeting_href"] += f"#{mo['id']}"
    return out


def items_year(year: int, facts) -> dict:
    ix = _ix(facts)
    entries = []
    for it in ix.facts["items"]:
        if it["year"] != year:
            continue
        events = sorted(ix.events_by_item[it["id"]], key=lambda e: (e["date"], e["page"], e["order"], e["id"]))
        entries.append({
            "id": it["id"], "number": it["number"], "title": it["title"],
            "basis": "Linked by number" if it["link_basis"] == "number" else "Linked by title",
            "events": [_event(ix, e) for e in events],
            "first": events[0]["date"] if events else "",
        })
    entries.sort(key=lambda i: (i["first"], (i["number"] or i["title"]).casefold(), i["id"]))
    return {"year": year, "items": entries}


# ---------------------------------------------------------------------------------------------------------------
# F4: about, changes, review


def about(facts) -> dict:
    ix = _ix(facts)
    officials = sorted(ix.facts["officials"], key=name_key)
    return {
        "officials": [{"name": o["name"], "title": o["title"], "aliases": o["aliases"]} for o in officials],
        "coverage": ix.coverage,
        "has_items": bool(ix.facts["items"]),
    }


def changes(entries: list[dict]) -> dict:
    return {"entries": entries}


def review(facts, report: dict | None) -> dict:
    ix = _ix(facts)
    unverified = []

    def failed(v):
        return [c for c in v["checks"] if not c["ok"]]

    for m in ix.facts["meetings"]:
        if not is_verified(m):
            unverified.append({"kind": "Attendance", "id": f"{m['id']}/att", "where": ix.meeting_label(m),
                               "failed": failed(m["verification"]),
                               "src": {"url": ix.sources[m["source_id"]]["url"], "page": None,
                                       "fetched": ix.sources[m["source_id"]]["fetched_at"]}})
    for mo in ix.facts["motions"]:
        if not is_verified(mo):
            unverified.append({"kind": "Motion attribution", "id": mo["id"], "where": mo["text"],
                               "failed": failed(mo["verification"]), "src": ix.src(mo["source_id"], mo["page"])})
    for rc in ix.facts["roll_calls"]:
        if not is_verified(rc):
            unverified.append({"kind": "Roll call", "id": rc["id"], "where": rc["outcome_text"],
                               "failed": failed(rc["verification"]), "src": ix.src(rc["source_id"], rc["page"])})
    return {"unverified": unverified,
            "report_json": json.dumps(report, indent=2, sort_keys=True) if report is not None else None}
