"""View functions: turn the facts contract into plain dicts for the templates.

Neutrality (N1-N3): there is one function per page type, used for every official, meeting and item. Nothing here
takes an official-specific flag, ranks by a count, or derives a label other than the fixed mappings in config.py.
Invariant: held-back counts (architecture): verified roll calls are "confirmed"; unverified ones are shown too, marked
"*" with a link to the source page, and are never added to a confirmed count. Raw OCR text never reaches a public page.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict

from . import config


# ---------------------------------------------------------------------------------------------------------------
# Small shared helpers


def plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def vote_label(value: str, raw_value: str) -> str:
    """N2: one mapping. `other` shows the minutes' wording only when it is one of the fixed words in config
    (raw-ocr-leak/vote-raw-value: raw_value is OCR text); anything else is plain "Other"."""
    if value == "yes":
        return "Yes"
    if value == "no":
        return "No"
    if value == "abstain":
        return "Abstain"
    word = config.OTHER_VOTE_WORDS.get(" ".join(re.sub(r"[^a-z ]", " ", raw_value.casefold()).split()))
    return f"Other: {word}" if word else "Other"


def name_key(o: dict) -> tuple:
    return (o["surname"].casefold(), o["given"].casefold(), o["id"])


def is_verified(fact: dict) -> bool:
    return fact["verification"]["status"] == "verified"


def values_shown(rc: dict) -> bool:
    """Whether a roll call's parsed values (each vote, the outcome, the tally, the bar) may be shown on a public page:
    always for a confirmed roll call; for an unconfirmed one only when config.SHOW_UNCONFIRMED_VALUES is on."""
    return is_verified(rc) or config.SHOW_UNCONFIRMED_VALUES


def attendance_shown(meeting: dict) -> bool:
    """Attendance is shown (and counted) only when extracted and verified."""
    return meeting["attendance_status"] == "extracted" and is_verified(meeting)


def attendance_state(meeting: dict) -> str:
    """One of `shown`, `not_extracted`, `under_review`. Same rule for the meeting page and the totals."""
    if meeting["attendance_status"] == "not_extracted":
        return "not_extracted"
    return "shown" if is_verified(meeting) else "under_review"


def motion_type_label(text: str) -> str:
    """Plain-words type of a motion, from the fixed list in config. Never returns any part of `text`."""
    for pattern, label in config.UNVERIFIED_MOTION_TYPES:
        if re.search(pattern, text, re.I | re.S):
            return label
    return config.UNVERIFIED_MOTION_DEFAULT


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
        # A motion's roll call: the confirmed one when there is one, otherwise an unconfirmed one (shown marked).
        self.rc_by_motion = {}
        for r in sorted(facts["roll_calls"], key=is_verified):
            if r["motion_id"]:
                self.rc_by_motion[r["motion_id"]] = r
        self.coverage = facts["coverage"]
        self.fixture = bool(facts.get("fixture"))

    def outcome(self, rc: dict) -> dict:
        """Passed/Failed/Other plus the tally counted from the verified votes (never the minutes' raw outcome text).
        Absent = members the meeting's verified attendance lists as absent who have no vote on this roll call.
        When the roll call's values are not shown (`values_shown`), only "Not confirmed": no label, tally or counts."""
        if not values_shown(rc):
            return {"label": config.NOT_CONFIRMED_LABEL, "tally": None, "counts": None, "hidden": True,
                    "confirmed": False, "src": self.src(rc["source_id"], rc["page"])}
        counts = {"yes": 0, "no": 0, "abstain": 0, "other": 0}
        for v in rc["votes"]:
            counts[v["value"]] += 1
        parts = [f"{counts['yes']} yes", f"{counts['no']} no"]
        if counts["abstain"]:
            parts.append(f"{counts['abstain']} abstain")
        if counts["other"]:
            parts.append(f"{counts['other']} other")
        m = self.meetings[rc["meeting_id"]]
        absent = 0
        if attendance_shown(m):
            voted = {v["official_id"] for v in rc["votes"]}
            absent = sum(1 for a in m["attendance"] if a["status"] == "absent" and a["official_id"] not in voted)
            if absent:
                parts.append(f"{absent} absent")
        # `counts` feeds the roll call's bar: the same numbers as the tally string. A roll call has no "no vote
        # recorded" segment of its own, so that one is always 0 here.
        return {"label": config.OUTCOME_LABELS[rc["outcome"]], "tally": ", ".join(parts),
                "counts": {**counts, "absent": absent, "novote": 0}, "hidden": False,
                "confirmed": is_verified(rc), "src": self.src(rc["source_id"], rc["page"])}

    def attribution(self, mo: dict) -> dict:
        """Who moved and seconded a motion, as shown everywhere (invariant rule 6). Resolved officials only, never the
        raw OCR names. Returns {"mover", "seconder"} as person dicts or None.
        - Verified motion: whichever names resolve.
        - Unverified motion: never any name; every page shows its type and "Attribution under review"."""
        if not is_verified(mo):
            return {"mover": None, "seconder": None}
        return {"mover": self.resolved_person(mo["moved_by"]), "seconder": self.resolved_person(mo["seconded_by"])}

    def motion_for(self, rc: dict) -> dict:
        """What a roll call may say about its motion: the motion's type in plain words (never its sentence) and
        'Moved by A, seconded by B' from the resolved officials' display names when the motion is verified."""
        mo = self.motions.get(rc["motion_id"]) if rc["motion_id"] else None
        if mo is None:
            return {"motion_text": None, "motion_label": None, "motion_by": None}
        att = self.attribution(mo)
        parts = [f"{w} by {p['name']}" for w, p in (("Moved", att["mover"]), ("seconded", att["seconder"])) if p]
        out = ", ".join(parts)
        return {"motion_text": None, "motion_label": motion_type_label(mo["text"]),
                "motion_by": (out[0].upper() + out[1:]) if out else None}

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
        return {"name": "Name not matched", "href": None}  # never the raw OCR name on a public page

    def resolved_person(self, ref: dict | None) -> dict | None:
        """The linked official, or None when the reference is absent or its official_id does not resolve."""
        oid = ref.get("official_id") if ref else None
        if oid and oid in self.officials:
            return self.person(ref)
        return None

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
        "item_years_desc": sorted(ix.item_years(), reverse=True),  # nav dropdown: newest first
        "coverage": ix.coverage,
        "show_unconfirmed_values": config.SHOW_UNCONFIRMED_VALUES,
        "internal": False,
    }


# ---------------------------------------------------------------------------------------------------------------
# F2: officials index and official page


VOTE_VALUES = ("yes", "no", "abstain", "other")
VOTE_WORDS = {"yes": "Yes", "no": "No", "abstain": "Abstain", "other": "Other"}


def unmatched_votes(ix: Index) -> int:
    """Invariant: held-back counts. Votes whose official_id does not resolve: counted once, site-wide, never
    under a name."""
    return sum(1 for rc in ix.facts["roll_calls"] for v in rc["votes"]
               if not v["official_id"] or v["official_id"] not in ix.officials)


def _zero_votes() -> dict:
    return {"rc_voted": 0, "yes": 0, "no": 0, "abstain": 0, "other": 0, "rc_absent": 0, "rc_novote": 0, "rc_total": 0}


def official_counts(ix: Index, official_id: str) -> dict:
    """The one place every per-official number is counted (visual-refresh section 6), so the home cards, the
    official page, the bars and the totals sentences cannot drift apart.

    Attendance: `meetings_listed` (shown attendance that lists the person), `absent` (listed absent), `present`
    (the rest), plus `moved` and `seconded` (motions whose attribution is shown).
    Votes, counted twice: confirmed (`yes`, `no`, ..., `rc_total`) and not confirmed (the same names ending `_nc`).
    `rc_voted` is the votes recorded under this official's resolved id; `rc_absent` and `rc_novote` are the roll calls
    at a meeting whose shown attendance lists the person absent / present with no vote for them. So
    `rc_total = rc_voted + rc_absent + rc_novote` and the bar's segments add up to it. No name is ever matched."""
    listed = absent = 0
    status: dict[str, str] = {}  # meeting id -> "present" or "absent" (absent wins when a meeting lists both)
    for m in ix.facts["meetings"]:
        if not attendance_shown(m):
            continue
        entries = [a["status"] for a in m["attendance"] if a["official_id"] == official_id]
        if entries:
            listed += 1
            status[m["id"]] = "absent" if "absent" in entries else "present"
            absent += status[m["id"]] == "absent"
    out = {"meetings_listed": listed, "absent": absent, "present": listed - absent}

    parts = {"": _zero_votes(), "_nc": _zero_votes()}
    for rc in ix.facts["roll_calls"]:
        c = parts["" if is_verified(rc) else "_nc"]
        mine = [v for v in rc["votes"] if v["official_id"] == official_id]
        if mine:
            for v in mine:
                c[v["value"]] += 1
                c["rc_voted"] += 1
                c["rc_total"] += 1
        elif status.get(rc["meeting_id"]) == "absent":
            c["rc_absent"] += 1
            c["rc_total"] += 1
        elif status.get(rc["meeting_id"]) == "present":
            c["rc_novote"] += 1
            c["rc_total"] += 1
    for suffix, c in parts.items():
        for k, n in c.items():
            out[k + suffix] = n

    moved = seconded = 0
    for mo in ix.facts["motions"]:
        att = ix.attribution(mo)  # the same rule as the meeting and item pages
        moved += att["mover"] is not None and mo["moved_by"]["official_id"] == official_id
        seconded += att["seconder"] is not None and mo["seconded_by"]["official_id"] == official_id
    out.update(moved=moved, seconded=seconded)
    return out


def initials(o: dict) -> str:
    return (o["given"][:1] + o["surname"][:1]).upper()


def officials_index(facts) -> dict:
    ix = _ix(facts)
    officials = sorted(ix.facts["officials"], key=name_key)
    meetings = sorted(ix.facts["meetings"], key=lambda m: (m["date"], m["id"]), reverse=True)
    rcs, motions = ix.facts["roll_calls"], ix.facts["motions"]
    states = [attendance_state(m) for m in ix.facts["meetings"]]
    confirmed = sum(1 for rc in rcs if is_verified(rc))
    glance = {
        "meetings": len(ix.facts["meetings"]),
        "rc_confirmed": confirmed, "rc_unconfirmed": len(rcs) - confirmed, "rc_total": len(rcs),
        "motions_held": sum(1 for mo in motions if not is_verified(mo)),
        "att_not_shown": sum(1 for s in states if s != "shown"),
        "from": ix.coverage["from"], "to": ix.coverage["to"],
    }

    cards = []
    for o in officials:
        c = official_counts(ix, o["id"])
        cards.append({"name": o["name"], "title": o["title"], "href": f"officials/{o['id']}.html",
                      "initials": initials(o), "present": c["present"], "listed": c["meetings_listed"],
                      "rc_voted": c["rc_voted"], "rc_voted_nc": c["rc_voted_nc"]})

    rc_by_meeting: dict[str, list] = defaultdict(list)
    for rc in rcs:
        rc_by_meeting[rc["meeting_id"]].append(rc)
    motions_by_meeting: dict[str, int] = defaultdict(int)
    for mo in motions:
        motions_by_meeting[mo["meeting_id"]] += 1

    by_year: dict[str, list] = {}
    for m in meetings:  # newest first, by date only
        group = rc_by_meeting[m["id"]]
        shown = attendance_shown(m)
        by_year.setdefault(m["date"][:4], []).append({
            "label": ix.meeting_label(m), "date": m["date"], "href": f"meetings/{m['id']}.html",
            "kind_label": config.KIND_LABELS[m["kind"]],
            "rc_confirmed": sum(1 for rc in group if is_verified(rc)),
            "rc_unconfirmed": sum(1 for rc in group if not is_verified(rc)),
            "motions": motions_by_meeting[m["id"]],
            "att_state": attendance_state(m),
            "present": sum(1 for a in m["attendance"] if a["status"] == "present") if shown else 0,
            "listed": len(m["attendance"]) if shown else 0,
        })
    return {
        "officials": cards,
        "meetings": [{"label": ix.meeting_label(m), "date": m["date"], "href": f"meetings/{m['id']}.html"}
                     for m in meetings],
        "meetings_by_year": [{"year": y, "meetings": ms} for y, ms in by_year.items()],
        "glance": glance,
        "coverage": ix.coverage,
    }


def totals_sentences(ix: Index, official_id: str) -> list[str]:
    """N3/P4/AC2.3: five fixed sentences, same wording and order for everyone. Only the numbers differ."""
    cov = ix.coverage
    c = official_counts(ix, official_id)
    unmatched = unmatched_votes(ix)
    confirmed = ", ".join(f"{c[k]} {VOTE_WORDS[k]}" for k in VOTE_VALUES)
    if config.SHOW_UNCONFIRMED_VALUES:
        unconfirmed = ", ".join(f"{c[k + '_nc']} {VOTE_WORDS[k]}*" for k in VOTE_VALUES) + " not confirmed"
    else:  # a count of roll calls only, never a Yes/No breakdown of unconfirmed votes
        n = c["rc_voted_nc"]
        unconfirmed = f"{n} {plural(n, 'roll call', 'roll calls')} not confirmed*, see each page"
    states = [attendance_state(m) for m in ix.facts["meetings"]]
    not_extracted = states.count("not_extracted")
    under_review = states.count("under_review")
    return [
        f"Recorded absent at {c['absent']} of {c['meetings_listed']} meetings with an extracted attendance section, "
        f"{cov['from']} to {cov['to']}.",
        f"Roll call votes, {cov['from']} to {cov['to']}: {confirmed} confirmed; {unconfirmed}.",
        # A site-wide number: the same sentence, with the same number, on every official's page.
        f"{unmatched} {plural(unmatched, 'vote', 'votes')} in this period {plural(unmatched, 'has', 'have')} a name "
        f"that could not be matched to an official and {plural(unmatched, 'is', 'are')} not counted for any member.",
        f"{not_extracted} {plural(not_extracted, 'meeting', 'meetings')} in this period "
        f"{plural(not_extracted, 'has', 'have')} no extracted attendance section and "
        f"{plural(not_extracted, 'is', 'are')} not counted.",
        f"{under_review} {plural(under_review, 'meeting', 'meetings')} in this period "
        f"{plural(under_review, 'has', 'have')} an attendance section that is under review and "
        f"{plural(under_review, 'is', 'are')} not counted.",
    ]


BAR_SEGMENTS = (("yes", "Yes"), ("no", "No"), ("abstain", "Abstain"), ("other", "Other"), ("absent", "Absent"),
                ("novote", "No vote recorded"))
ATTENDANCE_SEGMENTS = (("present", "Present"), ("absent", "Absent"))


def _vote_segment_counts(c: dict, suffix: str) -> dict:
    """official_counts keys -> the vote bar's segment keys (confirmed: suffix "", not confirmed: "_nc")."""
    return {**{k: c[k + suffix] for k in VOTE_VALUES}, "absent": c["rc_absent" + suffix],
            "novote": c["rc_novote" + suffix]}


def bar(counts: dict, spec) -> list[dict]:
    """Every segment of the bar type, always, in the fixed order, so the markup is identical for everyone."""
    return [{"key": k, "label": label, "n": counts[k]} for k, label in spec]


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
            "item": None, "motion_text": None, "motion_label": None, "motion_by": None,
            "record": "", "key": None, "outcome": None, "pos": 0, "confirmed": True,
        }

    for rc in ix.facts["roll_calls"]:
        for v in rc["votes"]:
            if v["official_id"] != official_id:  # resolved id only: an unmatched vote is on no official's page
                continue
            r = base("vote", rc["meeting_id"], f"{rc['id']}/{official_id}", rc["source_id"], rc["page"],
                     f"#{rc['id']}")
            r["item"] = ix.item_ref(rc["item_id"])
            r.update(ix.motion_for(rc))
            shown = values_shown(rc)
            r["record"] = vote_label(v["value"], v["raw_value"]) if shown else config.NOT_CONFIRMED_LABEL
            r["key"] = v["value"] if shown else None
            r["confirmed"] = is_verified(rc)
            r["outcome"] = ix.outcome(rc)
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
            r["key"] = a["status"]
            rows.append(r)

    for mo in ix.facts["motions"]:
        att = ix.attribution(mo)  # the same rule as the meeting and item pages
        for role, kind, ref, shown in (("moved", "moved", mo["moved_by"], att["mover"]),
                                       ("seconded", "seconded", mo["seconded_by"], att["seconder"])):
            if shown is None or ref["official_id"] != official_id:
                continue
            r = base(kind, mo["meeting_id"], f"{mo['id']}/{role}", mo["source_id"], mo["page"], f"#{mo['id']}")
            r["item"] = ix.item_ref(mo["item_id"])
            r["record"] = motion_type_label(mo["text"])  # the type only, never the minutes' sentence
            rc = ix.rc_by_motion.get(mo["id"])
            if rc:
                r["outcome"] = ix.outcome(rc)
            r["pos"] = ix.position(mo)[1]
            rows.append(r)

    # Newest first; ties by source page then position, then type, then id (stable, no count involved).
    rows.sort(key=lambda r: (r["page"], r["pos"], config.HISTORY_TYPES.index(r["type"]), r["fact_id"]))
    rows.sort(key=lambda r: r["date"], reverse=True)

    cov = ix.coverage
    years = sorted({r["year"] for r in rows}, reverse=True)
    c = official_counts(ix, official_id)
    return {
        "official": o, "initials": initials(o), "stats": c,
        "attendance_bar": bar(c, ATTENDANCE_SEGMENTS),
        "vote_bar": bar(_vote_segment_counts(c, ""), BAR_SEGMENTS),
        # text only, no bar; and no breakdown at all unless unconfirmed values are shown
        "vote_legend_nc": (bar(_vote_segment_counts(c, "_nc"), BAR_SEGMENTS) if config.SHOW_UNCONFIRMED_VALUES
                           else None),
        "coverage": cov,
        "coverage_sentence": f"Shows {cov['body']} records from {cov['from']} to {cov['to']}. {ix.fetched_sentence()}",
        "totals": totals_sentences(ix, official_id),
        "rows": rows,
        # one group per year, newest first; with no rows at all, one empty group so the page keeps its skeleton
        "row_groups": ([{"year": y, "rows": [r for r in rows if r["year"] == y]} for y in years]
                       or [{"year": "", "rows": []}]),
        "years": years,
        "types": [(t, config.TYPE_LABELS[t]) for t in config.HISTORY_TYPES],
    }


# ---------------------------------------------------------------------------------------------------------------
# F3: meeting and item pages


def _vote_rows(ix: Index, rc: dict) -> list[dict]:
    """Members alphabetically; votes whose name did not match come last as "Name not matched" (never the raw name).
    In an unconfirmed roll call every row is starred, and reads "Not confirmed" unless its values are shown."""
    def key(iv):
        i, v = iv
        o = ix.officials.get(v["official_id"])
        return (0, *name_key(o)) if o else (1, "", "", str(i))

    star, shown = not is_verified(rc), values_shown(rc)
    return [{"who": ix.person({"official_id": v["official_id"], "raw_name": v["raw_name"]}),
             "label": vote_label(v["value"], v["raw_value"]) if shown else config.NOT_CONFIRMED_LABEL,
             "key": v["value"] if shown else "nc", "star": star}
            for _, v in sorted(enumerate(rc["votes"]), key=key)]


def _motion_block(ix: Index, mo: dict) -> dict:
    """The minutes' sentence is OCR text that can carry misread names, so it is never shown: only the motion's type
    in plain words, and the resolved names by `Index.attribution`, or a fixed sentence in their place."""
    att = ix.attribution(mo)
    held = not (att["mover"] or att["seconder"])
    return {
        "kind": "motion", "id": mo["id"], "item": ix.item_ref(mo["item_id"]),
        "text": motion_type_label(mo["text"]),
        "attribution_held": held,
        "moved_by": att["mover"], "seconded_by": att["seconder"],
        "src": ix.src(mo["source_id"], mo["page"]),
    }


def _roll_call_block(ix: Index, rc: dict) -> dict:
    outcome = ix.outcome(rc)
    return {
        "kind": "roll_call", "id": rc["id"], "item": ix.item_ref(rc["item_id"]),
        "confirmed": is_verified(rc),
        **ix.motion_for(rc),
        "votes": _vote_rows(ix, rc),
        "outcome": outcome,
        "bar": bar(outcome["counts"], BAR_SEGMENTS) if outcome["counts"] else None,
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
    shown += [(ix.position(rc), _roll_call_block(ix, rc)) for rc in rcs]
    shown.sort(key=lambda t: t[0])
    unconfirmed = sum(1 for rc in rcs if not is_verified(rc))
    shown_att = att_state == "shown"
    stats = {
        "present": sum(1 for a in m["attendance"] if a["status"] == "present") if shown_att else 0,
        "listed": len(m["attendance"]) if shown_att else 0,
        "motions": len(motions),
        "rc_confirmed": len(rcs) - unconfirmed, "rc_unconfirmed": unconfirmed,
        # votes in this meeting's roll calls whose name did not resolve to an official: never guessed, never shown raw
        "unmatched": sum(1 for rc in rcs for v in rc["votes"]
                         if not v["official_id"] or v["official_id"] not in ix.officials),
    }
    return {
        "stats": stats, "meeting": m, "label": ix.meeting_label(m),
        "kind_label": config.KIND_LABELS[m["kind"]],
        "doc": {"url": src["url"], "kind": src["kind"], "fetched": src["fetched_at"], "pages": src["pages"]},
        "attendance_state": att_state, "attendance": attendance,
        "blocks": [b for _, b in shown],
        "unconfirmed_roll_calls": unconfirmed,
        "unconfirmed_text": (f"{unconfirmed} {plural(unconfirmed, 'roll call', 'roll calls')} at this meeting "
                             f"{plural(unconfirmed, 'is', 'are')} not confirmed and marked *."
                             if unconfirmed else ""),
    }


def _event(ix: Index, e: dict) -> dict:
    out = {
        "id": e["id"], "date": e["date"], "type_label": config.EVENT_TYPE_LABELS[e["type"]], "type": e["type"],
        "label": e["label"], "meeting_href": f"meetings/{e['meeting_id']}.html",
        "meeting_label": ix.meeting_label(ix.meetings[e["meeting_id"]]),
        "src": ix.src(e["source_id"], e["page"]), "motion": None, "roll_call": None,
    }
    ref = e["ref"]
    if e["type"] in ("roll_call", "motion"):
        out["label"] = None  # the event label is the raw OCR sentence (it can carry misread names); the block shows it
    if e["type"] == "roll_call" and ref in ix.roll_calls:
        rc = ix.roll_calls[ref]
        out["roll_call"] = _roll_call_block(ix, rc)  # marked * inside the block when unconfirmed
        out["meeting_href"] += f"#{rc['id']}"
    elif e["type"] == "motion" and ref in ix.motions:
        mo = ix.motions[ref]
        out["motion"] = _motion_block(ix, mo)  # attribution held inside the block when the motion is unverified
        out["meeting_href"] += f"#{mo['id']}"
    return out


MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December")


def _toc_groups(entries: list[dict]) -> list[dict]:
    """Table of contents grouped by the month of each item's first appearance, oldest first (entries are already in
    that order). An item with no appearance goes in a last "No appearance listed" group. Collapsed on the page."""
    groups: list[dict] = []
    for it in entries:
        key = it["first"][:7]
        if not groups or groups[-1]["key"] != key:
            label = f"{MONTH_NAMES[int(key[5:7]) - 1]} {key[:4]}" if key else "No appearance listed"
            groups.append({"key": key, "label": label, "entries": []})
        groups[-1]["entries"].append(it)
    return groups


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
    return {"year": year, "items": entries, "toc_groups": _toc_groups(entries)}


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
