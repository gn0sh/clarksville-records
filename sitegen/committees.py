"""City of Clarksville committee pages (milestone C2): the Finance Committee and the Audit Committee, each its own
body, shaped like the Regional Planning Commission's pages (sitegen/rpc.py).

Inputs: config/site.yml `city_committees:` (the locality, the city's record page, and one entry per committee: its
slug in committees.json, its page folder and its hub card), config/localities/<loc>/committees.yml (hold_motions) and
the facts file collector/committees.py writes (data/localities/<loc>/committees/committees.json). Nothing here names a
place.

Pages (one committee each, under its own folder): <folder>/index.html (the meetings by year, newest first, each with
its documents) and <folder>/meetings/<yyyy>.html (one section per meeting, #<meeting id>: its documents, attendance
and motions). Never one page per meeting.

Rules (docs/research/committee-sources-2026-11-11.md; the Daylight product rules):
- every value is the minutes' own words, labelled "as printed"; every attendance list and motion links its page of
  the minutes;
- a voice vote is "Voice vote (not recorded by name): passed" plus the meeting's attendance, never per-member
  votes; names on a vote only as the minutes print them (a printed nay, an AYE/NAY list);
- committees.yml `hold_motions` (or the record's own `hold_motions`) holds every motion: its item and words as
  printed, "Not confirmed" and its minutes page, no mover, seconder or outcome (WHY_HELD). A motion the reader did
  not confirm is shown the same way while the hold is off;
- only the words and names the record keeps are shown (docs/architecture/committee-words-invariant.md): a field it
  withholds is replaced by WORDS_NOTE and the minutes page link;
- a meeting with no minutes posted links its agenda and says the minutes are not posted; minutes that print another
  meeting's date are linked and say so, with nothing read from them attached.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from . import config, localdates

SITE_KEYS = ("locality", "url", "label", "kicker", "pages")
PAGE_KEYS = ("committee", "folder", "card")
DOC_LABELS = {"agenda": "Agenda", "minutes": "Minutes"}
WHY_HELD = "held: committee votes are being checked against the minutes"
# The sentence of the "Not confirmed" note under a motion (site/templates/_macros.html.j2 not_confirmed, src.held_note)
HELD_NOTE = "Not confirmed: committee votes are being checked against the minutes."
NOT_READ_NOTE = "Not confirmed: the vote on this motion was not read with certainty."
# A motion whose section, item or motion words the record withholds (docs/architecture/committee-words-invariant.md;
# the same text as collector/committee_words.WORDS_NOTE, checked by tests/test_committee_pages.py)
WORDS_NOTE = "Item words not shown (may name a private person); see the minutes"
SUBJECT_MAX = 400          # collector/committee_minutes.py keeps at most this many characters of an item's words
# How a confirmed motion's outcome is shown. A voice vote and a recorded vote (a printed AYE list: "The following vote
# was recorded") in fixed words with the result, "Voice vote (not recorded by name): passed." (Brian's rule,
# 2026-11-16: the same words everywhere; qa/site_checks.py CM_VOICE_VOTE); any other method (the minutes' "The motion
# was approved unanimously.") only in the minutes' own words (outcome_printed).
VOICE_VOTE = "Voice vote (not recorded by name)"
METHOD_WORDS = {"voice vote": VOICE_VOTE, "roll call": "Recorded vote"}


class CommitteesError(Exception):
    pass


def _date_text(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def load_config(site: dict | None = None) -> dict | None:
    """config/site.yml `city_committees:` checked, or None when the block is absent."""
    cfg = (config.SITE if site is None else site).get("city_committees")
    if not cfg:
        return None
    missing = [k for k in SITE_KEYS if k not in cfg]
    if missing:
        raise CommitteesError(f"config/site.yml city_committees: missing {', '.join(missing)}")
    folders = set()
    for p in cfg["pages"]:
        if not isinstance(p, dict) or any(not isinstance(p.get(k), str) or not p[k] for k in PAGE_KEYS):
            raise CommitteesError(f"config/site.yml city_committees.pages: each needs {', '.join(PAGE_KEYS)}")
        if not re.fullmatch(r"[a-z0-9-]+", p["folder"]) or p["folder"] in folders:   # a folder the build empties
            raise CommitteesError(f"city_committees folder {p['folder']!r}: lowercase letters, digits, '-', once")
        folders.add(p["folder"])
    from collector.committees import config_path, paths, load_config as collector_config
    cc = collector_config(config_path(cfg["locality"]))
    return {**cfg, "hold_motions": cc.hold_motions, "facts_path": paths(cc, config.REPO_ROOT)["facts"]}


class Committee:
    """One committee's pages from committees.json (its meetings and motions only)."""

    def __init__(self, cfg: dict, page: dict, facts: dict, hold: bool):
        self.cfg = cfg
        self.key = page["committee"]
        body = next((b for b in facts["bodies"] if b["slug"] == self.key), None)
        if body is None:
            raise CommitteesError(f"committees.json has no committee {self.key!r}")
        self.label = body["label"]
        self.slug = page["folder"]
        self.card = page["card"]
        self.body_key = page["folder"]
        self.kicker = cfg["kicker"]
        self.held = hold
        self.today: str | None = None        # the build's day (ISO); a meeting after it is upcoming (build.py sets it)
        self.meetings = sorted((m for m in facts["meetings"] if m["committee"] == self.key),
                               key=lambda m: (m["date"], m["id"]))
        self.sources = {d["source_id"]: d for m in self.meetings for d in m["documents"] if d.get("source_id")}
        self.motions_by_meeting: dict[str, list[dict]] = defaultdict(list)
        for mv in facts["motions"]:
            if mv["committee"] == self.key:
                self.motions_by_meeting[mv["meeting_id"]].append(mv)
        bad = [mv["id"] for ms in self.motions_by_meeting.values() for mv in ms
               if mv["source_id"] not in self.sources
               or not 1 <= mv["page"] <= (self.sources[mv["source_id"]].get("pages") or 0)]
        bad += [m["id"] for m in self.meetings if m.get("attendance")
                and m["attendance"]["source_id"] not in self.sources]
        if bad:
            raise CommitteesError(f"committees.json: motions or attendance cite a missing source or a page outside "
                                  f"it: {', '.join(bad[:5])}")

    # ------------------------------------------------------------------ paths
    @property
    def nav_label(self) -> str:
        return self.label

    def home_href(self) -> str:
        return f"{self.slug}/index.html"

    def year_href(self, year: str) -> str:
        return f"{self.slug}/meetings/{year}.html"

    def meeting_href(self, mid: str, date_: str) -> str:
        return f"{self.year_href(date_[:4])}#{mid}"

    def page_name(self, rest: str = "") -> str:
        return f"{self.label}: {rest}" if rest else self.label

    def years(self) -> list[str]:
        return sorted({m["date"][:4] for m in self.meetings}, reverse=True)

    def record(self) -> dict:
        return {"url": self.cfg["url"], "label": self.cfg["label"]}

    def site_for(self, site: dict) -> dict:
        """The header's coverage line is the committee's own: its meetings, first to last listed."""
        if not self.meetings:
            return site
        return {**site, "coverage": {"body": f"{self.kicker} {self.label}", "from": self.meetings[0]["date"],
                                     "to": self.meetings[-1]["date"]}, "coverage_what": "meetings"}

    # ------------------------------------------------------------------ contexts
    def _doc(self, d: dict) -> dict:
        label = DOC_LABELS.get(d["kind"], "Document")
        if d.get("source_id"):
            pages = d.get("pages")
            what = f"PDF, {pages} {'page' if pages == 1 else 'pages'}" if pages else "PDF"
            return {"label": label, "url": d["url"], "collected": True, "what": what,
                    "fetched": localdates.fetched(d)}
        return {"label": label, "url": d["url"], "collected": False}

    def motion(self, mv: dict) -> dict:
        """A motion as the pages show it. Its item and words as printed (none when they may still name a private
        person). Confirmed and not held: who moved and seconded it and the outcome, as printed; a voice vote is
        "Voice vote (not recorded by name): passed" and never per-member votes; names on a vote only as printed.
        Otherwise "Not confirmed" and its minutes page only."""
        s = self.sources[mv["source_id"]]
        confirmed = bool(mv["confirmed"]) and not self.held
        src = {"url": f"{s['url']}#page={mv['page']}", "page": mv["page"], "kind": "minutes"}
        if not confirmed:
            src["held_note"] = HELD_NOTE if self.held else NOT_READ_NOTE
        hidden = bool(set(mv.get("words_withheld") or []) & {"section", "subject_printed", "motion_printed"})
        item = mv.get("subject_printed")
        if item and len(item) >= SUBJECT_MAX:          # cut by the reader: say so
            item = item.rstrip() + "\u2026"
        out = {"id": mv["id"], "src": src, "item": item, "words": mv.get("motion_printed"), "hidden": hidden,
               "withheld_note": WORDS_NOTE if hidden else None,
               "confirmed": confirmed, "held": self.held,
               "moved_by": None, "seconded_by": None, "vote_words": None, "outcome": None, "outcome_printed": None,
               "nays": [], "ayes": []}
        if not out["confirmed"]:
            return out
        v = mv["vote"] or {}
        words = METHOD_WORDS.get(v.get("method"))
        out.update(moved_by=mv["mover_printed"], seconded_by=mv["seconder_printed"],
                   # a voice or recorded vote in our words; otherwise the outcome as printed, or when its words are
                   # withheld, only the outcome read ("passed")
                   vote_words=words,
                   outcome=v.get("outcome") if words or not v.get("outcome_printed") else None,
                   outcome_printed=None if words else v.get("outcome_printed"),
                   nays=list(v.get("nays_printed") or []),
                   ayes=list(v.get("ayes_printed") or []) if v.get("method") == "roll call" else [])
        return out

    def meeting(self, m: dict) -> dict:
        docs = [self._doc(d) for d in m["documents"]]
        kinds = {d["kind"] for d in m["documents"]}
        mins = next((d for d in m["documents"] if d["kind"] == "minutes"), None)
        att = m.get("attendance")
        attendance = None
        if att and mins and mins.get("source_id"):
            src = {"url": f"{mins['url']}#page={att['page']}" if att.get("page") else mins["url"],
                   "page": att.get("page") or 1, "kind": "minutes"}
            attendance = {"confirmed": att["confirmed"], "src": src,
                          "present": [p["name"] + (f" ({p['note']})" if p.get("note") else "")
                                      for p in att["present"] or []],
                          "absent": None if att["absent"] is None else
                          [p["name"] + (f" ({p['note']})" if p.get("note") else "") for p in att["absent"]]}
        upcoming = bool(self.today and m["date"] > self.today)
        other_date = (m["minutes_printed_date"] if m.get("minutes_read") and m.get("minutes_printed_date")
                      and m["minutes_printed_date"] != m["date"] else None)
        return {"id": m["id"], "date": m["date"], "date_text": _date_text(m["date"]), "printed": m["title"],
                "cancelled": m["cancelled"], "docs": docs, "upcoming": upcoming,
                # a document not posted is said so for a meeting that has taken place; an upcoming one has none yet
                "not_posted": [] if upcoming else [DOC_LABELS[k] for k in ("agenda", "minutes") if k not in kinds],
                "minutes_unread": bool(mins and mins.get("source_id") and not m.get("minutes_read")),
                "other_date": _date_text(other_date) if other_date else None,
                "attendance": attendance,
                "motions": [self.motion(mv) for mv in sorted(self.motions_by_meeting.get(m["id"], []),
                                                             key=lambda x: (x["page"], x["id"]))],
                "href": self.meeting_href(m["id"], m["date"])}

    def meetings_year(self, year: str) -> dict:
        ms = [m for m in self.meetings if m["date"][:4] == year]
        return {"year": year, "years": self.years(), "body": self.label, "kicker": self.kicker,
                "meetings": [self.meeting(m) for m in ms], "motions_held": self.held}

    def home(self) -> dict:
        by_year: dict[str, list[dict]] = defaultdict(list)
        for m in reversed(self.meetings):
            by_year[m["date"][:4]].append(self.meeting(m))
        motions = [mv for ms in self.motions_by_meeting.values() for mv in ms]
        fetched = localdates.span(list(self.sources.values()))
        held = [m for m in self.meetings if not (self.today and m["date"] > self.today)]   # upcoming ones are not
        return {"body": self.label, "kicker": self.kicker, "record_label": self.cfg["label"],
                "coverage": {"from": held[0]["date"], "to": held[-1]["date"]} if held else None,
                "n_upcoming": len(self.meetings) - len(held),
                "n_meetings": len(self.meetings), "n_docs": len(self.sources),
                "n_minutes_read": sum(1 for m in self.meetings if m.get("minutes_read")),
                "n_no_minutes": sum(1 for m in held if not any(d["kind"] == "minutes" for d in m["documents"])),
                "n_motions": len(motions),
                "n_motions_confirmed": 0 if self.held else sum(1 for mv in motions if mv["confirmed"]),
                "motions_held": self.held, "fetched_to": fetched[1] if fetched else None,
                "years": [{"year": y, "href": f"meetings/{y}.html", "meetings": by_year[y]} for y in self.years()]}

    # ------------------------------------------------------------------ search
    def search_records(self) -> list[dict]:
        return [{"k": "meeting", "id": f"{self.body_key}-{m['id']}", "n": "",
                 "t": f"{self.label}, {m['title']}", "d": m["date"], "y": [int(m["date"][:4])], "ty": [],
                 "b": self.body_key, "h": self.meeting_href(m["id"], m["date"])} for m in self.meetings]


def load(cfg: dict | None, fixture: bool) -> list[Committee]:
    """The committees' pages, or [] (no config, or no committees.json yet). A FIXTURE committees file (`fixture`: true,
    tests only) is built only beside fixture county facts, and a real one only beside real facts (made-up records are
    never shown beside real ones)."""
    if cfg is None:
        return []
    p = Path(cfg["facts_path"])
    if not p.is_file():
        return []
    facts = json.loads(p.read_text(encoding="utf-8"))
    if bool(facts.get("fixture")) != bool(fixture):
        if not fixture:
            raise CommitteesError(f"{p}: a FIXTURE committees file cannot be built beside real county facts")
        return []                     # a fixture build with no fixture committees: none
    hold = bool(cfg["hold_motions"]) or facts.get("hold_motions") is not False   # either switch holds
    return [Committee(cfg, page, facts, hold) for page in cfg["pages"]]


def sources(cms: list[Committee]) -> list[dict]:
    """Every collected document of the committees (for the footer's "Data as of")."""
    return [s for c in cms for s in c.sources.values()]
