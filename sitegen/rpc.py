"""Regional Planning Commission pages (milestones RPC-1, RPC-2): the RPC's meetings with their documents, each
agenda's case items as the agenda prints them, the minutes' motions on them (collector/rpc_minutes.py), and the
Planning Commission -> County Commission link of each county zoning case (link_county).

Inputs: config/localities/<rpc>/rpc.yml (config/site.yml `rpc:` names the locality) and the facts file it names
(collector/rpc.py and collector/rpc_agenda.py write it). Nothing here names a place.

Pages (file budget, config.MAX_FILES): <slug>/index.html (the meetings by year, each with its documents) and one page
per year of meetings, <slug>/meetings/<yyyy>.html, each meeting a section (#<meeting id>) with its documents, its
upcoming hearing dates and its case items. Never one page per meeting: the preview build is near its file cap.

Rules: every case value is the agenda's own words (no summary, no wording about the people named); every case links
the agenda PDF page it is printed on; a document on a host we do not collect from (Google Drive) is listed with its
link and says it was not collected. A motion the reader confirmed shows its values in the minutes' own words; one it
did not shows its type and the county's "Not confirmed" note, with no names, outcome or case number
(config.SHOW_UNCONFIRMED_VALUES). The invariant is docs/architecture/rpc-motion-invariant.md; the checks it allows
on the stored record alone are applied again here (record_doubts), so an older facts file never shows more, and a
facts file whose `motion_rules` is not the reader's current rules (MOTION_RULES) shows no motion confirmed and none
under a case.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml

from . import config

RPC_KEYS = ("body", "nav_label", "slug", "body_key", "listing_url", "record_url", "record_label", "facts",
            "kind_labels", "case_types")
DOC_LABELS = {"agenda": "Agenda", "minutes": "Minutes", "video": "Video", "other": "Document"}
CASE_FIELDS = (("applicant", None), ("agent", "Agent"), ("request", None), ("proposed_use", "Proposed use"),
               ("location", "Location"), ("ward_printed", "City council ward"), ("acres", "Acres"))


TITLE_MAX = 200
COUNTY_PREFIXES = ("CZ", "CZO")     # county zoning cases: the County Commission votes on them (link_county)
COUNTY_LABEL = "County Commission"


class RpcError(Exception):
    pass


# docs/architecture/rpc-motion-invariant.md, restated on the stored record so a facts file written before a rule
# existed is still shown under it: the meeting's own business (the only motions confirmed with no case), and the
# checks that need nothing but rpc.json. The rest (vote words left unread, loose case headings, another case named in
# the sentences, the roster fallback) need the minutes' text and apply when collector/rpc_agenda.py rebuilds it.
MEETING_BUSINESS = frozenset({"Motion to elect", "Motion to adjourn", "Motion to approve the minutes",
                              "Motion to approve the consent agenda", "Motion to approve the deferrals"})
# The reader's rules (collector/rpc_minutes.py MOTION_RULES), restated: a record whose `motion_rules` is not this was
# written before them (vote words, loose headings, another case named, the seconder and roster rules never ran on
# it), so none of its motions is shown confirmed and none is placed under a case (C1 is in doubt too)
MOTION_RULES = "rpc-motion-invariant-1"
WHY_STALE = "record written before the motion invariant"


def _surname(name: str) -> str:
    parts = (name or "").split()
    return "".join(ch for ch in parts[-1].casefold() if ch.isalpha()) if parts else ""


def record_doubts(motions: list[dict]) -> dict[str, tuple[list[str], bool]]:
    """{motion id: (reasons, whether a reason doubts its case)} for each motion the stored record already shows
    fails the invariant: C1 a case number off this meeting's agenda, more than one disposing motion read for one
    case at one meeting, a caseless motion that is not the meeting's own business; C3 a member named as voting nay or
    abstaining who is (by surname) the mover or seconder."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for mv in motions:
        if mv.get("case"):
            groups[(mv["meeting_id"], mv["case"])].append(mv)
    crowded = {mv["id"] for g in groups.values() if sum(1 for x in g if x["kind"] not in MEETING_BUSINESS) > 1
               for mv in g}
    out: dict[str, tuple[list[str], bool]] = {}
    for mv in motions:
        why = []
        if mv.get("case") and not mv.get("case_id"):
            why.append("case number not on this meeting's agenda")
        if mv["id"] in crowded:
            why.append("more than one motion on one case section")
        if not mv.get("case") and mv["kind"] not in MEETING_BUSINESS:
            why.append("subject not read")
        case_doubt = bool(why)
        movers = {_surname(x) for x in (mv.get("moved_by"), mv.get("seconded_by")) if x}
        if any(_surname(n) in movers for n in (mv.get("nays") or []) + (mv.get("abstained") or [])):
            why.append("a member named as voting nay is the mover or seconder")
        if why:
            out[mv["id"]] = (why, case_doubt)
    return out


def shown_motions(motions: list[dict], rules: str | None = MOTION_RULES) -> list[dict]:
    """The motions as the pages treat them: one the stored record shows failing the invariant is not confirmed, and
    one whose case is in doubt is placed under no case (record_doubts). `rules`: the record's `motion_rules`; any
    other than MOTION_RULES (a record written before the reader's rules) confirms none and places none under a case."""
    if rules != MOTION_RULES:
        return [{**mv, "confirmed": False, "reasons": list(mv.get("reasons") or []) + [WHY_STALE], "case_id": None}
                for mv in motions]
    doubts = record_doubts(motions)
    out = []
    for mv in motions:
        if mv["id"] in doubts:
            why, case_doubt = doubts[mv["id"]]
            mv = {**mv, "confirmed": False, "reasons": list(mv.get("reasons") or []) + why,
                  "case_id": None if case_doubt else mv["case_id"]}
        out.append(mv)
    return out


def load_config(locality: str | None) -> dict | None:
    if not locality:
        return None
    path = config.CONFIG_DIR / "localities" / locality / "rpc.yml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    missing = [k for k in RPC_KEYS if k not in cfg]
    if missing:
        raise RpcError(f"{path}: missing {', '.join(missing)}")
    return {**cfg, "locality": locality, "facts_path": config.REPO_ROOT / cfg["facts"]}


def _date_text(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


class Rpc:
    def __init__(self, cfg: dict, facts: dict):
        self.cfg = cfg
        self.facts = facts
        self.slug = cfg["slug"]
        self.nav_label = cfg["nav_label"]
        self.body = cfg["body"]
        self.body_key = cfg["body_key"]
        self.sources = {s["id"]: s for s in facts["sources"]}
        self.cases_by_meeting: dict[str, list[dict]] = defaultdict(list)
        for c in facts["cases"]:
            self.cases_by_meeting[c["meeting_id"]].append(c)
        # minutes motions (collector/rpc_minutes.py), as the pages treat them (shown_motions): on their agenda case
        # when the record places them there (case_id: only while nothing doubts the case), else in the meeting's own
        # list, with no case number
        self.motions = shown_motions(facts.get("motions", []), facts.get("motion_rules"))
        self.motions_by_case: dict[str, list[dict]] = defaultdict(list)
        self.motions_by_meeting: dict[str, list[dict]] = defaultdict(list)
        for mv in self.motions:
            if mv["case_id"]:
                self.motions_by_case[mv["case_id"]].append(mv)
            else:
                self.motions_by_meeting[mv["meeting_id"]].append(mv)
        self.county = None              # the county Index, once link_county has run
        self.county_items: dict[str, dict] = {}     # link key -> county item (CZ-, CZO- cases)
        bad = [c["id"] for c in facts["cases"] if c["source_id"] not in self.sources
               or not 1 <= c["page"] <= (self.sources[c["source_id"]]["pages"] or 0)]
        bad += [mv["id"] for mv in self.motions if mv["source_id"] not in self.sources
                or not 1 <= mv["page"] <= (self.sources[mv["source_id"]]["pages"] or 0)]
        if bad:
            raise RpcError(f"{cfg['facts_path']}: cases or motions cite a missing source or a page outside it: "
                           f"{', '.join(bad[:5])}")

    # ------------------------------------------------------------------ Planning Commission -> County Commission
    def link_county(self, ix) -> int:
        """Link each county-zoning case (CZ-, CZO-) to the County Commission item with the same case number: exact
        match of collector.rpc_minutes.link_key on both sides (parse.norm_item's glyph rule, no zero padding), never
        fuzzy. Sets ix.rpc_links (county item id -> the RPC agenda entries of that case) for the county item pages.
        Returns the number of linked RPC case entries."""
        from collector.rpc_minutes import link_key
        self.county = ix
        self.county_items = {}
        for it in ix.facts["items"]:
            k = link_key(it.get("number") or "")
            if k and k.split("-")[0] in COUNTY_PREFIXES:
                self.county_items.setdefault(k, it)
        links: dict[str, list[dict]] = defaultdict(list)
        dates = {m["id"]: m for m in self.facts["meetings"]}
        n = 0
        for c in sorted(self.facts["cases"], key=lambda c: (dates[c["meeting_id"]]["date"], c["id"])):
            it = self.county_item(c)
            if it is None:
                continue
            n += 1
            m = dates[c["meeting_id"]]
            links[it["id"]].append({"href": f"{self.year_href(m['date'][:4])}#{self.case_anchor(c)}",
                                    "number": c["number_printed"], "date": m["date"],
                                    "label": f"{self.cfg['kind_labels'].get(m['kind'], m['kind'])} agenda, "
                                             f"{_date_text(m['date'])}"})
        ix.rpc_links = dict(links)
        return n

    def county_item(self, c: dict) -> dict | None:
        if c["prefix"] not in COUNTY_PREFIXES:
            return None
        from collector.rpc_minutes import link_key
        return self.county_items.get(link_key(c["number"]) or "")

    def motion(self, mv: dict) -> dict:
        """A motion as the minutes print it. Confirmed (collector/rpc_minutes.py rule): its type, who moved and
        seconded it, who voted nay or abstained and the outcome, each as printed. Not confirmed: its type and the
        "Not confirmed" note only, while config.SHOW_UNCONFIRMED_VALUES is off (as for the county's roll calls): no
        names, outcome or case number. Nays only as named; nothing here ever says a vote was unanimous."""
        s = self.sources[mv["source_id"]]
        shown = mv["confirmed"] or config.SHOW_UNCONFIRMED_VALUES
        src = {"url": f"{s['url']}#page={mv['page']}", "page": mv["page"], "kind": "minutes"}
        return {"id": mv["id"], "kind": mv["kind"], "confirmed": mv["confirmed"], "src": src,
                "case": mv["case"] if shown and not mv["case_id"] else None,
                "moved_by": mv["moved_by"] if shown else None, "seconded_by": mv["seconded_by"] if shown else None,
                "nays": mv["nays"] if shown else [], "abstained": mv["abstained"] if shown else [],
                "outcome": mv["outcome"] if shown else None}

    def home_href(self) -> str:
        return f"{self.slug}/index.html"

    def page_name(self, rest: str = "") -> str:
        return f"{self.nav_label}: {rest}" if rest else self.nav_label

    def years(self) -> list[str]:
        return sorted({m["date"][:4] for m in self.facts["meetings"]}, reverse=True)

    def year_href(self, year: str) -> str:
        return f"{self.slug}/meetings/{year}.html"

    def meeting_href(self, mid: str, date_: str) -> str:
        return f"{self.year_href(date_[:4])}#{mid}"

    def case_anchor(self, c: dict) -> str:
        return f"case-{c['id']}"

    # ------------------------------------------------------------------ contexts
    def _doc(self, d: dict) -> dict:
        s = self.sources.get(d.get("source_id") or "")
        label = DOC_LABELS.get(d["kind"], "Document")
        if s:
            what = "DOCX" if s["format"] == "docx" else "PDF"
            pages = f", {s['pages']} {'page' if s['pages'] == 1 else 'pages'}" if s.get("pages") else ""
            return {"label": label, "url": d["url"], "collected": True, "what": f"{what}{pages}",
                    "fetched": s["fetched_at"], "no_text": s["format"] == "pdf" and s["text_layer"] == "none",
                    "ocr": s.get("read_by") == "OCR"}
        host = d["host"].removeprefix("www.")
        return {"label": label, "url": d["url"], "collected": False, "host": host}

    def meeting(self, m: dict) -> dict:
        agenda = self.sources.get(m.get("agenda_source_id") or "")
        cases = []
        # by page, then as printed (the facts keep agenda order; an item number may be unprinted, or restart per section)
        for c in sorted(self.cases_by_meeting.get(m["id"], []), key=lambda c: c["page"]):
            rows = []
            for key, label in CASE_FIELDS:
                if not c.get(key):
                    continue
                if key == "applicant":
                    label = c["applicant_label"]
                elif key == "request":
                    label = c["request_label"]
                rows.append({"key": key, "label": label, "value": c[key]})
            it = self.county_item(c) if self.county is not None else None
            cases.append({**c, "anchor": self.case_anchor(c), "rows": rows,
                          "src": f"{agenda['url']}#page={c['page']}" if agenda else None,
                          "motions": [self.motion(mv) for mv in sorted(self.motions_by_case.get(c["id"], []),
                                                                       key=lambda x: (x["page"], x["id"]))],
                          "county": ({"href": self.county.item_href(it), "number": it["number"],
                                      "label": COUNTY_LABEL} if it else None)})
        minutes = self.sources.get(m.get("minutes_source_id") or "")
        kinds_linked = {d["kind"] for d in m["documents"]}
        return {"id": m["id"], "date": m["date"], "date_text": _date_text(m["date"]),
                "kind_label": self.cfg["kind_labels"].get(m["kind"], m["kind"]), "printed": m["printed"],
                "cancelled": m["cancelled"],
                "docs": [self._doc(d) for d in m["documents"] if d["kind"] != "video"],
                "not_posted": [DOC_LABELS.get(k, k) for k in ("agenda", "minutes")
                               if k not in kinds_linked],
                "agenda": ({"url": agenda["url"], "pages": agenda["pages"], "fetched": agenda["fetched_at"],
                            "no_text": agenda["text_layer"] == "none",
                            "ocr": m.get("agenda_read_by") == "OCR"} if agenda else None),
                "minutes": ({"url": minutes["url"], "ocr": m.get("minutes_read_by") == "OCR"} if minutes else None),
                "other_motions": [self.motion(mv) for mv in sorted(self.motions_by_meeting.get(m["id"], []),
                                                                   key=lambda x: (x["page"], x["id"]))],
                "n_motions": len(self.motions_by_meeting.get(m["id"], []))
                + sum(len(c["motions"]) for c in cases),
                "hearings": [{**h, "src": f"{self.sources[h['source_id']]['url']}#page={h['page']}"}
                             for h in m.get("hearings", [])],
                "cases": cases, "href": self.meeting_href(m["id"], m["date"])}

    def meetings_year(self, year: str) -> dict:
        ms = sorted((m for m in self.facts["meetings"] if m["date"][:4] == year), key=lambda m: (m["date"], m["id"]))
        return {"year": year, "years": self.years(), "body": self.body, "meetings": [self.meeting(m) for m in ms]}

    def home(self) -> dict:
        by_year: dict[str, list[dict]] = defaultdict(list)
        for m in sorted(self.facts["meetings"], key=lambda m: (m["date"], m["id"]), reverse=True):
            by_year[m["date"][:4]].append(self.meeting(m))
        cov = self.facts["coverage"]
        fetched = sorted(s["fetched_at"] for s in self.facts["sources"] if s.get("fetched_at"))
        return {"body": self.body, "coverage": cov, "listing_url": self.cfg["listing_url"],
                "record_label": self.cfg["record_label"],
                "n_meetings": len(self.facts["meetings"]), "n_cases": len(self.facts["cases"]),
                "n_motions": len(self.motions),
                "n_motions_confirmed": sum(1 for mv in self.motions if mv["confirmed"]),
                "n_docs": len(self.facts["sources"]),
                "n_link_only": sum(1 for m in self.facts["meetings"] for d in m["documents"]
                                   if not d["fetched"] and d["kind"] != "video"),
                "fetched_to": fetched[-1] if fetched else None,
                "years": [{"year": y, "href": f"meetings/{y}.html", "meetings": by_year[y]} for y in self.years()]}

    # ------------------------------------------------------------------ search
    def search_records(self) -> list[dict]:
        out = []
        for m in self.facts["meetings"]:
            out.append({"k": "meeting", "id": f"{self.body_key}-{m['id']}", "n": "",
                        "t": f"{self.cfg['kind_labels'].get(m['kind'], m['kind'])}, {m['printed']}",
                        "d": m["date"], "y": [int(m["date"][:4])], "ty": [], "b": self.body_key,
                        "h": self.meeting_href(m["id"], m["date"])})
        by_number: dict[str, list[dict]] = defaultdict(list)
        for c in self.facts["cases"]:
            by_number[c["number"]].append(c)
        dates = {m["id"]: m["date"] for m in self.facts["meetings"]}
        for number, cs in sorted(by_number.items()):
            cs = sorted(cs, key=lambda c: (dates[c["meeting_id"]], c["id"]))
            first, last = cs[0], cs[-1]
            ds = [dates[c["meeting_id"]] for c in cs]
            title = last.get("request") or last.get("case_type") or number
            if len(title) > TITLE_MAX:   # a long variance text: the search line shows its start, the page all of it
                title = title[:TITLE_MAX].rstrip() + "\u2026"
            out.append({"k": "item", "id": f"{self.body_key}-{number}", "n": number,
                        "t": title, "d": ds[0], "d2": ds[-1], "a": len(cs),
                        "y": sorted({int(d[:4]) for d in ds}),
                        "ty": ["rezoning"] if first["prefix"] in ("Z", "CZ") else [], "b": self.body_key,
                        "h": f"{self.year_href(dates[last['meeting_id']][:4])}#{self.case_anchor(last)}",
                        "z": " · ".join(p for p in (last.get("case_type"), last.get("applicant"), last.get("location"))
                                        if p)})
        return out


def load(cfg: dict | None, fixture: bool) -> Rpc | None:
    """The RPC pages' data, or None (no config, or no facts file yet). A FIXTURE RPC facts file is built only beside
    fixture county facts, and a real one only beside real facts (made-up records are never shown beside real ones)."""
    if cfg is None:
        return None
    p = Path(cfg["facts_path"])
    if not p.is_file():
        return None
    facts = json.loads(p.read_text(encoding="utf-8"))
    if facts.get("schema") != "rpc-1":
        raise RpcError(f"{p}: not an RPC facts file (schema {facts.get('schema')!r})")
    if bool(facts.get("fixture")) != bool(fixture):
        raise RpcError(f"{p}: a {'FIXTURE' if facts.get('fixture') else 'real'} RPC facts file cannot be built beside "
                       f"{'FIXTURE' if fixture else 'real'} county facts")
    return Rpc(cfg, facts)
