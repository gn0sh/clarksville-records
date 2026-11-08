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
import datetime as dt

from .seats import Seats, seat_order


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

    def __init__(self, facts: dict, seat_rows: list[dict] | None = None):
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
        dates = [m["date"] for m in facts["meetings"]]
        self.latest = max(dates) if dates else self.coverage["to"]
        # Holder records (design 4.1): seat labels and the current / served previously split. Empty without a roster.
        self.seats = Seats(seat_rows, self.officials, self.latest)

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
        date = self.meetings[mo["meeting_id"]]["date"]
        return {"mover": self.resolved_person(mo["moved_by"], date),
                "seconder": self.resolved_person(mo["seconded_by"], date)}

    def motion_for(self, rc: dict) -> dict:
        """What a roll call may say about its motion: the motion's type in plain words (never its sentence) and
        'Moved by A, seconded by B' from the resolved officials' display names when the motion is verified."""
        mo = self.motions.get(rc["motion_id"]) if rc["motion_id"] else None
        if mo is None:
            return {"motion_text": None, "motion_label": None, "motion_by": None}
        att = self.attribution(mo)
        parts = [f"{w} by {p['name']}" + (f" ({p['seat']})" if p.get("seat") else "")
                 for w, p in (("Moved", att["mover"]), ("seconded", att["seconder"])) if p]
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

    def person(self, ref: dict | None, date: str | None = None) -> dict | None:
        """A linked official with the seat held on `date` (design 6A.2), or the fixed unmatched text."""
        if ref is None:
            return None
        oid = ref["official_id"]
        if oid and oid in self.officials:
            return {"name": self.officials[oid]["name"], "href": f"officials/{oid}.html",
                    "seat": self.seats.on(oid, date) if date else None}
        return {"name": "Name not matched", "href": None, "seat": None}  # never the raw OCR name on a public page

    def resolved_person(self, ref: dict | None, date: str | None = None) -> dict | None:
        """The linked official, or None when the reference is absent or its official_id does not resolve."""
        oid = ref.get("official_id") if ref else None
        if oid and oid in self.officials:
            return self.person(ref, date)
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


NAV = (  # design 2.2: fixed order, the same on every page. (label, href, page_name that marks it current, coming)
    ("Map (home)", "index.html", "Map", False),
    ("Search", "search.html", "Search", False),
    ("Votes", "votes/index.html", "Votes", False),
    ("Meetings", "meetings.html", "Meetings", False),
    ("Officials", "officials.html", "Officials", False),
    ("Items", None, None, False),  # a nested list of years
    ("Finance", "finance.html", "Finance", True),
    ("Capital projects", "capital-projects.html", "Capital projects", True),
    ("Data downloads", "data.html", "Data downloads", False),
    ("About", "about.html", "About", False),
    ("Changes", "changes.html", "Changes", False),
)


def _nav(ix: "Index") -> list[dict]:
    years = sorted({ix.meetings[rc["meeting_id"]]["date"][:4] for rc in ix.facts["roll_calls"]}, reverse=True)
    out = []
    for label, href, page, coming in NAV:
        if label == "Votes":  # the newest year's page; each votes page links every year
            href = f"votes/{years[0]}.html" if years else "search.html"
        out.append({"label": label, "href": href, "page": page, "coming": coming})
    return out


def site_context(facts) -> dict:
    ix = _ix(facts)
    cfg = config.SITE
    return {
        "cfg": cfg,
        "nav": _nav(ix),
        # the footer link exists only when it is switched on and has an address (CEO, 2026-11-08)
        "support_url": (cfg.get("support_url") or "") if cfg.get("support_enabled") is True else "",
        "support_label": cfg.get("support_label") or "",
        "vote_years_desc": sorted({ix.meetings[rc["meeting_id"]]["date"][:4] for rc in ix.facts["roll_calls"]},
                                  reverse=True),
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


def _in_range(date: str, start: str | None, end: str | None) -> bool:
    return (start is None or date >= start) and (end is None or date <= end)


def official_counts(ix: Index, official_id: str, start: str | None = None, end: str | None = None) -> dict:
    """The one place every per-official number is counted (visual-refresh section 6), so the home cards, the
    official page, the bars and the totals sentences cannot drift apart.

    Attendance: `meetings_listed` (shown attendance that lists the person), `absent` (listed absent), `present`
    (the rest), plus `moved` and `seconded` (motions whose attribution is shown).
    Votes, counted twice: confirmed (`yes`, `no`, ..., `rc_total`) and not confirmed (the same names ending `_nc`).
    `rc_voted` is the votes recorded under this official's resolved id; `rc_absent` and `rc_novote` are the roll calls
    at a meeting whose shown attendance lists the person absent / present with no vote for them. So
    `rc_total = rc_voted + rc_absent + rc_novote` and the bar's segments add up to it. No name is ever matched.
    `start`/`end` (inclusive dates) scope every count to one holder record's dates (seat pages, design 4.3)."""
    listed = absent = 0
    status: dict[str, str] = {}  # meeting id -> "present" or "absent" (absent wins when a meeting lists both)
    for m in ix.facts["meetings"]:
        if not attendance_shown(m) or not _in_range(m["date"], start, end):
            continue
        entries = [a["status"] for a in m["attendance"] if a["official_id"] == official_id]
        if entries:
            listed += 1
            status[m["id"]] = "absent" if "absent" in entries else "present"
            absent += status[m["id"]] == "absent"
    out = {"meetings_listed": listed, "absent": absent, "present": listed - absent}

    parts = {"": _zero_votes(), "_nc": _zero_votes()}
    for rc in ix.facts["roll_calls"]:
        if not _in_range(ix.meetings[rc["meeting_id"]]["date"], start, end):
            continue
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
        if not _in_range(ix.meetings[mo["meeting_id"]]["date"], start, end):
            continue
        att = ix.attribution(mo)  # the same rule as the meeting and item pages
        moved += att["mover"] is not None and mo["moved_by"]["official_id"] == official_id
        seconded += att["seconder"] is not None and mo["seconded_by"]["official_id"] == official_id
    out.update(moved=moved, seconded=seconded)
    return out


def initials(o: dict) -> str:
    return (o["given"][:1] + o["surname"][:1]).upper()


def record_glance(ix: Index) -> dict:
    """The at-a-glance band (moved from the old home page to about.html#the-record, design D2)."""
    rcs, motions = ix.facts["roll_calls"], ix.facts["motions"]
    states = [attendance_state(m) for m in ix.facts["meetings"]]
    confirmed = sum(1 for rc in rcs if is_verified(rc))
    return {
        "meetings": len(ix.facts["meetings"]),
        "rc_confirmed": confirmed, "rc_unconfirmed": len(rcs) - confirmed, "rc_total": len(rcs),
        "motions_held": sum(1 for mo in motions if not is_verified(mo)),
        "att_not_shown": sum(1 for s in states if s != "shown"),
        "from": ix.coverage["from"], "to": ix.coverage["to"],
    }


def _card(ix: Index, o: dict) -> dict:
    """One card template for everyone, current or former (design 6A.3: the section heading is the only difference)."""
    c = official_counts(ix, o["id"])
    return {"id": o["id"], "name": o["name"], "title": o["title"], "href": f"officials/{o['id']}.html",
            "initials": initials(o), "present": c["present"], "listed": c["meetings_listed"],
            "rc_voted": c["rc_voted"], "rc_voted_nc": c["rc_voted_nc"], "seat": ix.seats.seat_text(o["id"])}


def officials_page(facts) -> dict:
    """officials.html (design 6A.3). With a roster: Current by seat (districts by number, then the configured other
    seats), Served previously and Seat not yet recorded alphabetical by surname. Without one: everyone in one
    alphabetical list, no seat labels. Never placed by guess."""
    ix = _ix(facts)
    officials = sorted(ix.facts["officials"], key=name_key)
    if not ix.seats.loaded:
        return {"seats_loaded": False, "sections": [
            {"key": "all", "heading": None, "order": "surname", "cards": [_card(ix, o) for o in officials]}]}
    current, former, unseated = [], [], []
    for o in officials:
        recs = ix.seats.of(o["id"])
        if not recs:
            unseated.append(o)
        elif ix.seats.is_current(o["id"]):
            current.append(o)
        else:
            former.append(o)

    def seat_key(o):  # the lowest current seat they hold, then name for a tie (two holders of one seat)
        return (min(seat_order(r["seat"]) for r in ix.seats.of(o["id"]) if r["current"]), *name_key(o))

    current.sort(key=seat_key)
    sections = [
        {"key": "current", "heading": "Current", "order": "seat", "cards": [_card(ix, o) for o in current]},
        {"key": "previous", "heading": "Served previously", "order": "surname", "cards": [_card(ix, o) for o in former]},
    ]
    if unseated:
        sections.append({"key": "unseated", "heading": "Seat not yet recorded", "order": "surname",
                         "cards": [_card(ix, o) for o in unseated]})
    return {"seats_loaded": True, "sections": sections}


def meetings_page(facts) -> dict:
    """meetings.html: the timeline moved from the old home page (design D2), newest first, by date only."""
    ix = _ix(facts)
    meetings = sorted(ix.facts["meetings"], key=lambda m: (m["date"], m["id"]), reverse=True)
    rc_by_meeting: dict[str, list] = defaultdict(list)
    for rc in ix.facts["roll_calls"]:
        rc_by_meeting[rc["meeting_id"]].append(rc)
    motions_by_meeting: dict[str, int] = defaultdict(int)
    for mo in ix.facts["motions"]:
        motions_by_meeting[mo["meeting_id"]] += 1
    by_year: dict[str, list] = {}
    for m in meetings:
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
    return {"meetings_by_year": [{"year": y, "meetings": ms} for y, ms in by_year.items()], "coverage": ix.coverage}


def vote_sentence(c: dict, start: str, end: str) -> str:
    """The one roll call totals sentence (N3), used by the official page and every seat page holder record."""
    confirmed = ", ".join(f"{c[k]} {VOTE_WORDS[k]}" for k in VOTE_VALUES)
    if config.SHOW_UNCONFIRMED_VALUES:
        unconfirmed = ", ".join(f"{c[k + '_nc']} {VOTE_WORDS[k]}*" for k in VOTE_VALUES) + " not confirmed"
    else:  # a count of roll calls only, never a Yes/No breakdown of unconfirmed votes
        n = c["rc_voted_nc"]
        unconfirmed = f"{n} {plural(n, 'roll call', 'roll calls')} not confirmed*, see each page"
    return f"Roll call votes, {start} to {end}: {confirmed} confirmed; {unconfirmed}."


def totals_sentences(ix: Index, official_id: str) -> list[str]:
    """N3/P4/AC2.3: five fixed sentences, same wording and order for everyone. Only the numbers differ."""
    cov = ix.coverage
    c = official_counts(ix, official_id)
    unmatched = unmatched_votes(ix)
    states = [attendance_state(m) for m in ix.facts["meetings"]]
    not_extracted = states.count("not_extracted")
    under_review = states.count("under_review")
    return [
        f"Recorded absent at {c['absent']} of {c['meetings_listed']} meetings with an extracted attendance section, "
        f"{cov['from']} to {cov['to']}.",
        vote_sentence(c, cov["from"], cov["to"]),
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
        "seat_header": ix.seats.header_text(official_id),  # None without a roster; never guessed
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
    date = ix.meetings[rc["meeting_id"]]["date"]
    return [{"who": ix.person({"official_id": v["official_id"], "raw_name": v["raw_name"]}, date),
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
                "who": ix.person({"official_id": a["official_id"], "raw_name": a["raw_name"]}, m["date"]),
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
    # Items with no appearance (first == "") go last, so their group is last too.
    entries.sort(key=lambda i: (i["first"] == "", i["first"], (i["number"] or i["title"]).casefold(), i["id"]))
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


# ---------------------------------------------------------------------------------------------------------------
# Landing map, seat pages, votes, search, coming and data pages (docs/design/landing-search-nav.md)


def _district_seat(n: int) -> str:
    return f"district-{n}"


def district_rows(ix: Index) -> list[dict]:
    """The landing's district list (design 3.3), 1 to N. Same row for every seat (N1): the current holder's name,
    or one of two fixed sentences, or (no roster yet) the seat label alone."""
    cfg = config.SITE
    rows = []
    for n in range(1, cfg["district_count"] + 1):
        holder = None
        if ix.seats.loaded:
            rec = ix.seats.current_of_seat(_district_seat(n))
            if rec is None:
                holder = "Current member not yet recorded"
            elif rec["official_id"] is None:
                holder = "Seat vacant"
            else:
                holder = ix.officials[rec["official_id"]]["name"]
        rows.append({"number": n, "label": f"{cfg['district_label']} {n}", "holder": holder,
                     "href": f"districts/{n:02d}.html"})
    return rows


def map_context(districts: dict | None, highlight: int | None = None) -> dict | None:
    """The inline SVG's data. Every district path gets the same class; the fill never encodes anything (design 3.2)."""
    if districts is None:
        return None
    wards = districts.get("wards") or {}
    return {
        "viewBox": districts["viewBox"],
        "outline": districts.get("outline_path"),
        "river": districts.get("river_path"),
        "districts": [{"number": d["number"], "path": d["path"], "x": d["label_xy"][0], "y": d["label_xy"][1],
                       "href": f"districts/{int(d['number']):02d}.html", "this": d["number"] == highlight}
                      for d in sorted(districts["districts"], key=lambda d: d["number"])],
        "wards": [{"number": w["number"], "path": w["path"], "x": w["label_xy"][0], "y": w["label_xy"][1]}
                  for w in sorted(wards.get("wards") or [], key=lambda w: w["number"])],
        "wards_status": wards.get("status", config.SITE["wards_status"]),
        "source_url": districts["source_url"], "source_title": districts.get("source_title") or "county map",
        "fetched": districts["fetched"], "effective": districts.get("effective") or config.SITE["lines_effective"],
        "note": districts.get("note"),
    }


def landing(facts, districts: dict | None) -> dict:
    ix = _ix(facts)
    return {"rows": district_rows(ix), "map": map_context(districts), "coverage": ix.coverage,
            "district_count": config.SITE["district_count"]}


def _day_before(date: str) -> str:
    return (dt.date.fromisoformat(date) - dt.timedelta(days=1)).isoformat()


def _official_rows(ix: Index, cache: dict, official_id: str) -> list[dict]:
    if official_id not in cache:
        cache[official_id] = official(official_id, ix)["rows"]
    return cache[official_id]


def _holder_block(ix: Index, cache: dict, rec: dict, start: str, end: str | None, period: str) -> dict:
    """One holder record inside one line period (design 4.3 item 5): totals scoped to its dates, its vote rows."""
    o = ix.officials[rec["official_id"]]
    shown_end = end or ix.latest
    c = official_counts(ix, o["id"], start, end)
    rows = [r for r in _official_rows(ix, cache, o["id"])
            if r["type"] == "vote" and _in_range(r["date"], start, end)]
    years = sorted({r["year"] for r in rows}, reverse=True)
    label = rec["label"]
    return {
        "name": o["name"], "href": f"officials/{o['id']}.html", "seat": label, "period": period,
        "heading": f"{o['name']}, {label}, {start} to {'present' if end is None and rec['current'] else shown_end}",
        "sentence": vote_sentence(c, start, shown_end),
        "row_groups": [{"year": y, "rows": [r for r in rows if r["year"] == y]} for y in years],
        "has_rows": bool(rows),
    }


def district(n: int, facts, districts: dict | None) -> dict:
    """districts/<nn>.html (design 4). One template and one function for all seats (N1); order is by date only."""
    ix = _ix(facts)
    cfg = config.SITE
    seat = _district_seat(n)
    eff = cfg["lines_effective"]
    recs = ix.seats.for_seat(seat)
    cur = ix.seats.current_of_seat(seat)

    def holder_row(r):
        who = ({"name": ix.officials[r["official_id"]]["name"], "href": f"officials/{r['official_id']}.html"}
               if r["official_id"] else None)
        if r["end"] is not None and r["end"] < eff:
            lines = "Old district lines"
        elif r["start"] >= eff:
            lines = "Current district lines"
        else:
            lines = "Old and current district lines"
        return {"who": who, "start": r["start"], "end": r["end"], "lines": lines, "source": r["source"],
                "src_label": r["src_label"], "label": r["label"]}

    # every earlier holder record, newest first by end date (a seat's own timeline, design 4.3 item 4)
    previous = sorted((r for r in recs if r is not cur), key=lambda r: (r["end"] or "9999", r["start"]), reverse=True)
    cache: dict = {}
    current_blocks, old_blocks = [], []
    lo, hi = ix.coverage["from"], ix.latest
    for r in sorted(recs, key=lambda r: r["start"], reverse=True):  # newest first, by date only
        if r["official_id"] is None:
            continue
        end = r["end"]
        # current lines: [max(start, eff), end]; old lines: [start, min(end, eff - 1 day)]; clipped to the data
        if end is None or end >= eff:
            s0 = max(r["start"], eff, lo)
            if end is None or s0 <= end:
                current_blocks.append(_holder_block(ix, cache, r, s0, end, "current"))
        if r["start"] < eff:
            e0 = min(end, _day_before(eff)) if end else _day_before(eff)
            s0 = max(r["start"], lo)
            if s0 <= e0 and s0 <= hi:
                old_blocks.append(_holder_block(ix, cache, r, s0, min(e0, hi), "old"))
    swapped = cfg.get("swapped_districts") or []
    return {
        "n": n, "nn": f"{n:02d}", "title": f"{cfg['district_page_title']} {n}",
        "label": f"{cfg['district_label']} {n}",
        "seats_loaded": ix.seats.loaded, "has_records": bool(recs),
        "notice": (f"District lines were redrawn in 2022. Before {eff}, {cfg['district_label']} {n} covered a "
                   f"different area. Votes under the old district lines are listed separately."),
        "swap_line": (f"Under the new map, {cfg['district_label']} {swapped[0]} and {cfg['district_label']} "
                      f"{swapped[1]} swapped numbers." if n in swapped and len(swapped) == 2 else None),
        "eff": eff, "old_map_url": cfg.get("old_lines_map_url") or "", "redistricting_page": cfg["redistricting_page"],
        "current": holder_row(cur) if cur else None,
        "previous": [holder_row(r) for r in previous],
        "current_blocks": current_blocks, "old_blocks": old_blocks,
        "map": map_context(districts, highlight=n),
    }


def votes_year(year: str, facts) -> dict:
    """votes/<yyyy>.html: every roll call that year, newest first by date, then document order (design 1)."""
    ix = _ix(facts)
    rows = []
    for rc in ix.facts["roll_calls"]:
        m = ix.meetings[rc["meeting_id"]]
        if m["date"][:4] != year:
            continue
        rows.append({"id": rc["id"], "date": m["date"], "item": ix.item_ref(rc["item_id"]),
                     "meeting_href": f"meetings/{m['id']}.html#{rc['id']}", "meeting_label": ix.meeting_label(m),
                     "outcome": ix.outcome(rc), "confirmed": is_verified(rc),
                     "src": ix.src(rc["source_id"], rc["page"]), "pos": ix.position(rc)})
    rows.sort(key=lambda r: r["pos"])
    rows.sort(key=lambda r: r["date"], reverse=True)
    years = sorted({ix.meetings[rc["meeting_id"]]["date"][:4] for rc in ix.facts["roll_calls"]}, reverse=True)
    return {"year": year, "rows": rows, "years": years}


def item_types(item: dict) -> list[str]:
    """Design 5.4: number prefix, else fixed words in the verbatim title; can match several; else "other"."""
    number, title = (item.get("number") or "").upper(), (item.get("title") or "").casefold()
    out = [t["key"] for t in config.SITE["item_types"]
           if any(number.startswith(p.upper()) for p in t["prefixes"]) or any(w in title for w in t["words"])]
    return out or ["other"]


def _search_name(o: dict) -> str:
    return f"{o['surname']}, {o['given']}"


def search_index(facts) -> dict:
    """The one first-party search index (manager decision Q3), loaded by static/search.js. Unconfirmed roll calls
    carry no outcome and no votes, so a vote or outcome filter can never match one (invariant rules 1 and 5)."""
    ix = _ix(facts)
    cfg = config.SITE
    records = []
    for it in ix.facts["items"]:
        evs = sorted(ix.events_by_item[it["id"]], key=lambda e: e["date"])
        dates = [e["date"] for e in evs]
        records.append({"k": "item", "id": it["id"], "n": it["number"] or "", "t": it["title"],
                        "d": dates[0] if dates else "", "d2": dates[-1] if dates else "", "a": len(evs),
                        "y": sorted({int(d[:4]) for d in dates} or {it["year"]}), "ty": item_types(it), "b": "county",
                        "h": f"items/{it['year']}.html#{it['id']}"})
    for rc in ix.facts["roll_calls"]:
        m = ix.meetings[rc["meeting_id"]]
        it = ix.items.get(rc["item_id"], {})
        rec = {"k": "vote", "id": rc["id"], "n": it.get("number") or "", "t": it.get("title") or rc["item_id"],
               "d": m["date"], "y": [int(m["date"][:4])], "ty": item_types(it) if it else ["other"], "b": "county",
               "h": f"meetings/{m['id']}.html#{rc['id']}", "c": is_verified(rc), "o": None, "v": None, "s": None}
        if values_shown(rc) and is_verified(rc):  # confirmed only, whatever the display switch says
            rec["o"] = rc["outcome"]
            rec["v"] = {v["official_id"]: v["value"] for v in rc["votes"]
                        if v["official_id"] and v["official_id"] in ix.officials}
            src = ix.src(rc["source_id"], rc["page"])
            rec["s"] = {"u": src["url"], "p": src["page"], "f": src["fetched"]}
        records.append(rec)
    for m in ix.facts["meetings"]:
        records.append({"k": "meeting", "id": m["id"], "n": "", "t": f"{ix.meeting_label(m)}, {m['body']}",
                        "d": m["date"], "y": [int(m["date"][:4])], "ty": [], "b": "county",
                        "h": f"meetings/{m['id']}.html"})
    officials = sorted(ix.facts["officials"], key=name_key)
    for o in officials:
        records.append({"k": "person", "id": o["id"], "n": "", "t": o["name"], "st": ix.seats.seat_text(o["id"]) or "",
                        "d": "", "y": [], "ty": [], "b": "county", "h": f"officials/{o['id']}.html"})
    for row in district_rows(ix):
        records.append({"k": "person", "id": f"district-{row['number']}", "n": "",
                        "t": f"{cfg['district_page_title']} {row['number']}", "st": row["holder"] or "",
                        "d": "", "y": [], "ty": [], "b": "county", "h": row["href"]})
    years = sorted({y for r in records for y in r["y"]})
    return {
        "records": records,
        # alphabetical by surname, no counts (design 5.2, N3); the seat label is the current one
        "officials": [{"id": o["id"], "label": _search_name(o) + (f" ({ix.seats.seat_text(o['id'])})"
                                                                  if ix.seats.is_current(o["id"]) else "")}
                      for o in officials],
        "names": {o["id"]: o["name"] for o in officials},
        "years": years,
        "types": [{"key": t["key"], "label": t["label"]} for t in cfg["item_types"]] + [{"key": "other", "label": "Other"}],
        "county_body": cfg["county_body"],
    }


def search_page(facts) -> dict:
    ix = _ix(facts)
    idx = search_index(ix)
    return {"years": idx["years"], "types": idx["types"], "officials": idx["officials"]}


def coming(slug: str) -> dict:
    page = next(c for c in config.SITE["coming"] if c["slug"] == slug)
    return {"page": page}


EXPORT_FILES = (
    ("facts.json", "All shown facts and their sources, in one file."),
    ("officials.csv", "One row per official."),
    ("meetings.csv", "One row per meeting."),
    ("attendance.csv", "Verified attendance, one row per member per meeting."),
    ("roll_calls.csv", "One row per roll call, with whether it is confirmed."),
    ("votes.csv", "One row per vote in a roll call."),
    ("motions.csv", "One row per motion, with its kind."),
    ("items.csv", "One row per agenda item."),
    ("item_events.csv", "Each appearance of an item at a meeting."),
    ("sources.csv", "Every source document, with its address and fetch date."),
)


def data_page() -> dict:
    return {"files": [{"name": n, "about": a} for n, a in EXPORT_FILES]}
