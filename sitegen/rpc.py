"""Regional Planning Commission pages (milestone RPC-1): the RPC's meetings with their documents, and each agenda's
case items as the agenda prints them.

Inputs: config/localities/<rpc>/rpc.yml (config/site.yml `rpc:` names the locality) and the facts file it names
(collector/rpc.py and collector/rpc_agenda.py write it). Nothing here names a place.

Pages (file budget, config.MAX_FILES): <slug>/index.html (the meetings by year, each with its documents) and one page
per year of meetings, <slug>/meetings/<yyyy>.html, each meeting a section (#<meeting id>) with its documents, its
upcoming hearing dates and its case items. Never one page per meeting: the preview build is near its file cap.

Rules: every case value is the agenda's own words (no summary, no wording about the people named); every case links
the agenda PDF page it is printed on; a document on a host we do not collect from (Google Drive) is listed with its
link and says it was not collected.
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


class RpcError(Exception):
    pass


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
        bad = [c["id"] for c in facts["cases"] if c["source_id"] not in self.sources
               or not 1 <= c["page"] <= (self.sources[c["source_id"]]["pages"] or 0)]
        if bad:
            raise RpcError(f"{cfg['facts_path']}: cases cite a missing source or a page outside it: {', '.join(bad[:5])}")

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
                    "fetched": s["fetched_at"], "no_text": s["format"] == "pdf" and s["text_layer"] == "none"}
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
            cases.append({**c, "anchor": self.case_anchor(c), "rows": rows,
                          "src": f"{agenda['url']}#page={c['page']}" if agenda else None})
        kinds_linked = {d["kind"] for d in m["documents"]}
        return {"id": m["id"], "date": m["date"], "date_text": _date_text(m["date"]),
                "kind_label": self.cfg["kind_labels"].get(m["kind"], m["kind"]), "printed": m["printed"],
                "cancelled": m["cancelled"],
                "docs": [self._doc(d) for d in m["documents"] if d["kind"] != "video"],
                "not_posted": [DOC_LABELS.get(k, k) for k in ("agenda", "minutes")
                               if k not in kinds_linked],
                "agenda": ({"url": agenda["url"], "pages": agenda["pages"], "fetched": agenda["fetched_at"],
                            "no_text": agenda["text_layer"] == "none"} if agenda else None),
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
