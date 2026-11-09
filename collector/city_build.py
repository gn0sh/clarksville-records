"""Assemble City Council facts from the Agenda Center listing and the stored files (M4, slice 1).

Output follows schema/facts.schema.json (the county's shape, with the city meeting kinds and the optional listing
fields title, agenda_url, minutes_url, minutes_status). Wards as printed in each meeting's attendance go to a
companion list (wards), because the attendance record has no seat field.

Neutral and mechanical: every official is built the same way from the attendance lines; a vote counts only as
printed; anything that does not resolve or check out is kept, marked unverified, with the failed checks named.
"""
from __future__ import annotations

import re
import subprocess
import unicodedata
from collections import Counter, defaultdict

from .agenda_center import AgendaCenterConfig
from .city_minutes import NAME_RE, ParsedCityMinutes, parse_minutes_pdf, pdf_layer, short_hash
from .extract import extract_pages
from .store import Store

SCHEMA_VERSION = "1.0"
SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
# "failed due to lack of 2/3 majority": a motion can fail with more yes than no when the minutes say a larger
# majority was required. Only then is a yes > no failure consistent.
THRESHOLD_RE = re.compile(r"2/3|two[- ]thirds|majority", re.I)
MINUTES_STATUS = ("read", "scan_not_read", "not_posted", "not_fetched", "parse_failed")


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def clean_name(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip(" ,.;")


def name_parts(name: str) -> tuple[str, str]:
    """'Richard Garrett' -> ('Richard', 'Garrett'); 'Joe Smith, Jr.' -> ('Joe', 'Smith')."""
    words = [w for w in re.split(r"[\s,]+", name) if w]
    while len(words) > 1 and words[-1].lower().strip(".") in SUFFIXES:
        words.pop()
    if not words:
        return "", ""
    return " ".join(words[:-1]), words[-1]


def official_id(name: str) -> str:
    return "city-" + slug(name)


class Officials:
    def __init__(self, cfg: AgendaCenterConfig):
        self.cfg = cfg
        self.by_id: dict[str, dict] = {}
        self.titles: dict[str, set] = defaultdict(set)

    def canonical(self, raw: str) -> str:
        name = clean_name(raw)
        return self.cfg.aliases.get(name, name)

    def add(self, raw: str, title: str) -> str:
        name = self.canonical(raw)
        oid = official_id(name)
        if oid not in self.by_id:
            given, surname = name_parts(name)
            self.by_id[oid] = {"id": oid, "name": name, "given": given, "surname": surname, "aliases": []}
        if clean_name(raw) != name and clean_name(raw) not in self.by_id[oid]["aliases"]:
            self.by_id[oid]["aliases"].append(clean_name(raw))
        self.titles[oid].add(title)
        return oid

    def records(self) -> list[dict]:
        order = (self.cfg.official_title, self.cfg.presiding_title)
        out = []
        for oid, o in sorted(self.by_id.items()):
            t = "; ".join(x for x in order if x in self.titles[oid])
            out.append({**o, "title": t, "aliases": sorted(o["aliases"])})
        return out


def resolve(token: str, roster: list[tuple[str, str]]) -> str | None:
    """A vote name as printed -> the one roster official it names, else None. roster: [(official_id, full name)].
    Matches, in order: the full name; the surname; an initial plus surname ('W. Smith'). Never a near spelling."""
    t = clean_name(token).lower()
    full = [oid for oid, n in roster if n.lower() == t]
    if len(full) == 1:
        return full[0]
    sur = [oid for oid, n in roster if name_parts(n)[1].lower() == t]
    if len(sur) == 1:
        return sur[0]
    m = re.match(r"^([a-z])\.?\s+(.+)$", t)
    if m:
        ini = [oid for oid, n in roster
               if name_parts(n)[1].lower() == m.group(2) and name_parts(n)[0][:1].lower() == m.group(1)]
        if len(ini) == 1:
            return ini[0]
    return None


def _check(name: str, ok: bool, detail: str | None = None) -> dict:
    c = {"check": name, "ok": bool(ok)}
    if detail:
        c["detail"] = detail
    return c


def _verification(checks: list[dict]) -> dict:
    return {"status": "verified" if all(c["ok"] for c in checks) else "unverified",
            "checks": sorted(checks, key=lambda c: c["check"])}


def pdf_pages(path) -> int:
    out = subprocess.run(["pdfinfo", str(path)], capture_output=True).stdout.decode("utf-8", "replace")
    m = re.search(r"^Pages:\s*(\d+)", out, re.M)
    return max(int(m.group(1)), 1) if m else 1


def source_record(entry: dict, pages: int, layer: str) -> dict:
    return {"id": f"src-{entry['sha256'][:12]}", "url": entry["url"], "sha256": entry["sha256"],
            "kind": entry["kind"], "meeting_date": entry["meeting_date"],
            "fetched_at": (entry["first_fetched_at"] or "")[:10], "pages": pages, "text_layer": layer}


def inspect_pdf(path) -> tuple[int, str]:
    """(page count, text layer) of a stored PDF."""
    return pdf_pages(path), pdf_layer(path, extract_pages(path))


def build(cfg: AgendaCenterConfig, rows: list[dict], store: Store, parse=parse_minutes_pdf,
          inspect=inspect_pdf) -> tuple[dict, dict]:
    officials = Officials(cfg)
    sources: dict[str, dict] = {}
    meetings, roll_calls, motions, items, events, wards = [], [], [], {}, [], []
    problems, unresolved = [], Counter()
    status_count = Counter()
    ids_used: Counter = Counter()

    def source_for(url: str | None):
        if not url:
            return None, None
        e = store.latest(url)
        if not e or not store.has_bytes(e["sha256"]):
            return None, None
        sid = f"src-{e['sha256'][:12]}"
        path = store.path_for(e["sha256"])
        if sid not in sources:
            sources[sid] = source_record(e, *inspect(path))
        return sources[sid], path

    # Agenda Center rows first on a day (their meeting ids were published first), then CivicClerk rows; within a
    # source by its own id, so ids of one kind on one day (-2, -3) stay put
    for r in sorted(rows, key=lambda r: (r["date"], r.get("source", "agenda-center") != "agenda-center",
                                         int(r["agenda_id"].split("-")[-1]))):
        agenda_src, _ = source_for(r["agenda_url"])
        minutes_src, minutes_path = source_for(r["minutes_url"])
        src = minutes_src or agenda_src
        if not src:
            status_count["not_in_facts"] += 1
            problems.append({"meeting": r["date"], "title": r["title"],
                             "problem": "no fetched agenda or minutes file to cite: left out of facts"})
            continue
        kind = cfg.kind_of(r["title"])            # from the title and the current config, not the stored listing
        base = f"{r['date']}-{kind}"
        ids_used[base] += 1
        mid = base if ids_used[base] == 1 else f"{base}-{ids_used[base]}"
        pm: ParsedCityMinutes | None = None
        if not r["minutes_url"]:
            mstatus = "not_posted"
        elif not minutes_src:
            mstatus = "not_fetched"
        elif minutes_src["text_layer"] != "text":
            mstatus = "scan_not_read"
        else:
            try:
                pm = parse(minutes_path, cfg)
                mstatus = "read" if pm.text_layer == "text" else "scan_not_read"
            except Exception as ex:                       # one bad file must not stop the build
                problems.append({"meeting": mid, "problem": f"parse failed: {type(ex).__name__}: {ex}"})
                mstatus = "parse_failed"
        status_count[mstatus] += 1
        meeting = {"id": mid, "body": cfg.body, "date": r["date"], "kind": kind, "source_id": src["id"],
                   "title": r["title"], "agenda_url": r["agenda_url"], "minutes_url": r["minutes_url"],
                   "minutes_status": mstatus, "attendance_status": "not_extracted", "attendance": [],
                   "stated_absent_count": None, "verification": _verification([])}
        if agenda_src:
            meeting["agenda_source_id"] = agenda_src["id"]
        if r.get("source"):
            meeting["listing_source"] = r["source"]
        if r.get("video_url"):
            meeting["video_url"] = r["video_url"]
        meetings.append(meeting)
        if pm is None or mstatus != "read":
            meeting["verification"] = _verification([_check("minutes_read", False, mstatus)])
            continue
        _add_minutes(cfg, officials, meeting, minutes_src, pm, roll_calls, motions, items, events, wards,
                     problems, unresolved)

    for s in sources.values():
        if not s["meeting_date"]:
            s["meeting_date"] = next((m["date"] for m in meetings if m["source_id"] == s["id"]), "1900-01-01")
    dates = sorted(m["date"] for m in meetings)
    facts = {
        "schema_version": SCHEMA_VERSION,
        "coverage": {"body": cfg.body, "from": dates[0] if dates else "1900-01-01",
                     "to": dates[-1] if dates else "1900-01-01"},
        "sources": sorted(sources.values(), key=lambda s: (s["meeting_date"], s["id"])),
        "officials": officials.records(),
        "meetings": meetings,
        "items": sorted(items.values(), key=lambda i: i["id"]),
        "item_events": events,
        "motions": motions,
        "roll_calls": roll_calls,
        "corrections": [],
    }
    rc_verified = sum(r["verification"]["status"] == "verified" for r in roll_calls)
    summary = {
        "listed_rows": len(rows),
        "listed_with_minutes": sum(1 for r in rows if r["minutes_url"]),
        "meetings_in_facts": len(meetings),
        "minutes_status": dict(status_count),
        "officials": len(facts["officials"]),
        "roll_calls": len(roll_calls),
        "roll_calls_verified": rc_verified,
        "votes": sum(len(r["votes"]) for r in roll_calls),
        "votes_in_verified_roll_calls": sum(len(r["votes"]) for r in roll_calls
                                            if r["verification"]["status"] == "verified"),
        "motions": len(motions),
        "items": len(items),
        "held_back_checks": dict(Counter(c["check"] for r in roll_calls for c in r["verification"]["checks"]
                                         if not c["ok"])),
        "unresolved_vote_names": dict(unresolved.most_common()),
        "by_source": by_source(meetings, roll_calls),
        "problems": problems,
    }
    return {**facts, "_wards": wards}, summary


def by_source(meetings: list[dict], roll_calls: list[dict]) -> dict:
    """Counts per listing source (and for meetings from 2024 on), so each source's verified rate is reported apart."""
    src_of = {m["id"]: m.get("listing_source", "agenda-center") for m in meetings}
    date_of = {m["id"]: m["date"] for m in meetings}
    out: dict[str, dict] = {}

    def add(key: str, ms: list[dict], rcs: list[dict]) -> None:
        ok = sum(r["verification"]["status"] == "verified" for r in rcs)
        out[key] = {"meetings": len(ms), "minutes_read": sum(m.get("minutes_status") == "read" for m in ms),
                    "with_video": sum(bool(m.get("video_url")) for m in ms), "roll_calls": len(rcs),
                    "roll_calls_verified": ok, "verified_rate": round(ok / len(rcs), 4) if rcs else None}

    for s in sorted(set(src_of.values())):
        add(s, [m for m in meetings if src_of[m["id"]] == s], [r for r in roll_calls if src_of[r["meeting_id"]] == s])
    add("2024_on", [m for m in meetings if m["date"] >= "2024"],
        [r for r in roll_calls if date_of[r["meeting_id"]] >= "2024"])
    return out


def _out_of_room(pm: ParsedCityMinutes, roster, part_time: dict) -> list[set]:
    """For each roll call of the meeting, the members its missing-vote check exempts: a member noted as arriving
    late, for the votes before their first recorded vote; one noted as leaving early, for the votes after their
    last. A noted member with no recorded vote at all cannot be placed, so is exempt from every vote."""
    voted = [{resolve(v.raw_name, roster) for v in rc.votes} for rc in pm.roll_calls]
    out = [set() for _ in pm.roll_calls]
    for oid, p in part_time.items():
        ks = [k for k, s in enumerate(voted) if oid in s]
        for k in range(len(voted)):
            if not ks or (p.arrived_late and k < ks[0]) or (p.left_early and k > ks[-1]):
                out[k].add(oid)
    return out


def _add_minutes(cfg, officials: Officials, meeting: dict, src: dict, pm: ParsedCityMinutes, roll_calls, motions,
                 items, events, wards, problems, unresolved) -> None:
    sha8 = src["sha256"][:8]
    roster: list[tuple[str, str]] = []
    present_ids, absent_ids, part_time = set(), set(), {}     # part_time: official -> Person (late or left)
    att = []
    malformed = []
    for status, people in (("present", pm.present), ("absent", pm.absent)):
        for p in people:
            if not NAME_RE.match(clean_name(p.raw_name)):       # not a person's name as printed: no official made
                malformed.append(p.raw_name)
                att.append({"official_id": None, "raw_name": p.raw_name, "status": status, "page": p.page})
                continue
            oid = officials.add(p.raw_name, cfg.presiding_title if p.mayor else cfg.official_title)
            att.append({"official_id": oid, "raw_name": p.raw_name, "status": status, "page": p.page})
            roster.append((oid, officials.by_id[oid]["name"]))
            (present_ids if status == "present" else absent_ids).add(oid)
            if p.part_time:
                part_time[oid] = p
            wards.append({"official_id": oid, "raw_name": p.raw_name, "ward": p.ward, "pro_tem": p.pro_tem,
                          "meeting_id": meeting["id"], "date": meeting["date"], "source_id": src["id"],
                          "page": p.page})
    presiding_id = None
    if pm.presiding and pm.presiding_title == cfg.presiding_title:
        presiding_id = officials.add(pm.presiding, cfg.presiding_title)
        if presiding_id not in present_ids:
            roster.append((presiding_id, officials.by_id[presiding_id]["name"]))
    dup = [n for n, c in Counter(a["official_id"] for a in att if a["official_id"]).items() if c > 1]
    att_checks = [_check("present_listed", bool(pm.present), f"{len(pm.present)} present, {len(pm.absent)} absent"),
                  _check("one_entry_per_official", not dup, ", ".join(dup) or None),
                  _check("names_well_formed", not malformed, ", ".join(malformed) or None)]
    if att:
        meeting["attendance_status"] = "extracted"
        meeting["attendance"] = att
    meeting["verification"] = _verification(att_checks)
    att_ok = meeting["verification"]["status"] == "verified"
    for msg in pm.problems:
        problems.append({"meeting": meeting["id"], "problem": msg})

    out_of_room = _out_of_room(pm, roster, part_time)
    per_page, motions_on_page = Counter(), Counter()
    for k, rc in enumerate(pm.roll_calls):
        n = per_page[rc.page]
        per_page[rc.page] += 1
        rid = f"rc-{sha8}-p{rc.page}-{n}"
        if rc.item["number"]:
            iid = f"{rc.item['kind']}-{rc.item['number']}"
            if iid not in items:
                items[iid] = {"id": iid, "number": f"{rc.item['kind'].upper()} {rc.item['number']}",
                              "title": rc.item["title"] or "", "link_basis": "number",
                              "year": int(meeting["date"][:4])}
            elif not items[iid]["title"] and rc.item["title"]:      # first printed title, once one is seen
                items[iid]["title"] = rc.item["title"]
        else:
            heading = rc.item["heading"] or "(no heading)"
            iid = "t-" + short_hash(meeting["id"], heading)
            items.setdefault(iid, {"id": iid, "number": None, "title": heading, "link_basis": "title",
                                   "year": int(meeting["date"][:4])})
        votes, seen = [], Counter()
        for v in rc.votes:
            oid = resolve(v.raw_name, roster)
            if oid is None:
                unresolved[v.raw_name] += 1
            else:
                seen[oid] += 1
            votes.append({"official_id": oid, "raw_name": v.raw_name, "value": v.value, "raw_value": v.raw_value})
        block_absent = {resolve(a, roster) for a in rc.absent}
        voted = set(seen)
        yes = sum(v["value"] == "yes" for v in votes)
        no = sum(v["value"] == "no" for v in votes)
        # a member noted as arriving late may miss the votes before their first vote, one noted as leaving early
        # the votes after their last; any other missing vote holds the roll call
        missing = sorted(present_ids - voted - block_absent - out_of_room[k] - {presiding_id})
        not_present = sorted(o for o in voted if o not in present_ids and o != presiding_id)
        unres = [v["raw_name"] for v in votes if v["official_id"] is None]
        if rc.outcome == "passed":
            consistent, why = yes > no, f"passed with {yes} yes and {no} no"
        elif rc.outcome == "failed" and yes > no and THRESHOLD_RE.search(rc.outcome_text):
            consistent, why = True, f"failed with {yes} yes and {no} no; the minutes state a required majority"
        elif rc.outcome == "failed":
            consistent, why = yes <= no, f"failed with {yes} yes and {no} no"
        else:
            consistent, why = False, "outcome not read"
        checks = [
            _check("attendance_verified", att_ok),
            _check("reading_used", True, "text-layer"),
            _check("votes_listed", bool(votes)),
            _check("names_resolve", not unres, ", ".join(unres) or None),
            _check("one_entry_per_official", all(c == 1 for c in seen.values()),
                   ", ".join(o for o, c in seen.items() if c > 1) or None),
            _check("voters_recorded_present", not not_present, ", ".join(not_present) or None),
            _check("one_vote_per_present_member", not missing, ", ".join(missing) or None),
            _check("outcome_consistent", consistent, why),
            # the vote's own words contradict the item it follows: linked to the section and held, never guessed
            _check("vote_matches_item", rc.link["ok"], rc.link["detail"]),
        ]
        motion_id = None
        if rc.motion:
            motion_id = f"mo-{sha8}-p{rc.motion['page']}-{motions_on_page[rc.motion['page']]}"
            motions_on_page[rc.motion["page"]] += 1
            mover = resolve(rc.motion["mover"], roster)
            sec = resolve(rc.motion["seconder"], roster) if rc.motion["seconder"] else None
            mchecks = [
                _check("attendance_verified", att_ok),
                _check("mover_resolves", mover is not None, rc.motion["mover"]),
                _check("seconder_resolves", sec is not None, rc.motion["seconder"] or "no seconder printed"),
                _check("mover_present", mover in present_ids or (mover is not None and mover == presiding_id)),
                _check("seconder_present", sec in present_ids),
                _check("mover_differs_from_seconder", mover is None or mover != sec),
            ]
            motions.append({"id": motion_id, "meeting_id": meeting["id"], "item_id": iid, "text": rc.motion["text"],
                            "moved_by": {"official_id": mover, "raw_name": rc.motion["mover"]},
                            "seconded_by": ({"official_id": sec, "raw_name": rc.motion["seconder"]}
                                            if rc.motion["seconder"] else None),
                            "source_id": src["id"], "page": rc.motion["page"], "verification": _verification(mchecks)})
            events.append({"id": f"ev-{sha8}-p{rc.motion['page']}-{2 * rc.order}", "item_id": iid,
                           "meeting_id": meeting["id"], "date": meeting["date"], "type": "motion",
                           "label": rc.motion["text"], "ref": motion_id, "source_id": src["id"],
                           "page": rc.motion["page"], "order": 2 * rc.order})
        roll_calls.append({"id": rid, "meeting_id": meeting["id"], "item_id": iid, "motion_id": motion_id,
                           "votes": votes, "stated_tally": None, "outcome": rc.outcome,
                           "outcome_text": rc.outcome_text, "source_id": src["id"], "page": rc.page,
                           "verification": _verification(checks)})
        events.append({"id": f"ev-{sha8}-p{rc.page}-{2 * rc.order + 1}", "item_id": iid, "meeting_id": meeting["id"],
                       "date": meeting["date"], "type": "roll_call", "label": rc.outcome_text, "ref": rid,
                       "source_id": src["id"], "page": rc.page, "order": 2 * rc.order + 1})
