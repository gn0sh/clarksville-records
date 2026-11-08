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
from .minutes import consent_numbers, pair_consent
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


SENTENCE = re.compile(r"\bMotion\b[^.]{0,80}\bby\s+~?Commissioner\b|\bseconded\s+by\b"
                      r"|\bby\s+the\s+f\S{4,8}\s+roll\s+call\b|\b(?:was|were)\s+(?:Adopted|Approved|Elected|Failed|Defeated"
                      r"|Denied|Suspended|Tabled|Deferred)\b", re.I)


def is_sentence(title: str) -> bool:
    """Written rule (items/title-is-motion): a motion sentence ("Motion by Commissioner A, seconded by ...") or an
    outcome sentence ("The Motion was Approved by the following roll call vote") is not an item title. The item is
    titled from the agenda's title for its number, else the number alone, else "(untitled)" (never title-linked)."""
    return bool(SENTENCE.search(title or ""))


def subject_of(clause: str | None) -> str | None:
    """'the foregoing County Clerk's Report was Approved by ...' -> "County Clerk's Report" (verbatim)."""
    if not clause:
        return None
    m = re.search(r"foregoing\s+(.*?)\s+(?:was|were|Failed|Passed)\b", clause, re.I | re.S)
    return m.group(1).strip(" ,") if m else None


def _reading_of(rc):
    """The reading that supplied rc's votes (or a stand-in built from them)."""
    for r in rc.readings + ([rc.combined] if getattr(rc, "combined", None) else []):
        if r.votes is rc.votes:
            return r
    return P.Reading("parsed", rc.votes, rc.tally, list(rc.absent), [], printed=getattr(rc, "printed_tally", None))


ATTACHED = "inside an earlier meeting"


def printing_key(rc) -> tuple:
    """(mover, seconder) of a consent table as resolved against its own meeting's roster; None where unread."""
    return (rc.mover, rc.seconder)


def consent_groups(rcs: list) -> tuple[dict, set]:
    """Architecture "Invariant: one vote, one roll call" (problem family item-history). Written rule: in one
    meeting's minutes, consent-agenda tables are printings of one consent vote unless their motions name different
    movers or seconders. The 2020-2022 minutes reprint the consent vote after each consent resolution, and OCR garbles
    the item numbers, the names and sometimes the tally in some printings, so neither the item list nor the tally nor
    the raw name spelling decides which vote a printing belongs to. The mover and seconder resolved against the
    meeting's own roster do; a printing whose motion is unread (either name None) joins the one vote it is
    compatible with. Tables inside an earlier meeting's attached minutes are never grouped with this meeting's.

    The first printing that verifies (else the first) is the roll call; the others are reprints, kept only as item
    events that point at it. Printings that disagree (a member's Yes/No/Abstain, or the stated tally) hold the roll
    call (check reprints_agree): they are never split into separate votes. A printing compatible with two or more
    votes cannot be placed: it stays its own roll call and is held (check consent_printing_placed).

    Returns ({reprint index: index of the roll call it reprints}, {indexes of printings that could not be placed})."""
    cands = [k for k, rc in enumerate(rcs) if rc.kind == "consent"
             and not any(ATTACHED in x for x in rc.context_reasons)]
    # most completely read printings first, then document order: a fully read motion founds a vote before an unread
    # one is placed
    order = sorted(cands, key=lambda k: (-sum(f is not None for f in printing_key(rcs[k])), k))
    groups: list[dict] = []
    ambiguous: set[int] = set()
    for k in order:
        f = printing_key(rcs[k])
        fits = [g for g in groups if all(a is None or b is None or a == b for a, b in zip(f, g["key"]))]
        if len(fits) == 1:
            g = fits[0]
            g["members"].append(k)
            g["key"] = tuple(b if b is not None else a for a, b in zip(f, g["key"]))
        elif not fits:
            groups.append({"key": f, "members": [k]})
        else:
            ambiguous.add(k)
    reprints = {}
    for g in groups:
        ks = sorted(g["members"])
        c = next((k for k in ks if rcs[k].status == "Verified"), ks[0])
        for k in ks:
            if k != c:
                reprints[k] = c
    return reprints, ambiguous


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
        self.consent_unexpanded: list[str] = []     # consent roll calls whose item list could not be read
        self._ev_count: dict[tuple, int] = {}
        self.consent_reprints: dict[str, str] = {}   # reprinted consent roll call id -> the one vote it reprints
        self.zoning: dict[str, list] = {}            # case number -> [(zoning.Reading, source_id, meeting date)]

    # ------------------------------------------------------------ items
    def is_procedural(self, title: str) -> bool:
        t = norm_title(title)
        return any(p.search(t) for p in self.procedural)

    def item_for(self, number: str | None, title: str | None, key: tuple, unique_salt: str) -> str:
        """key = (date, page, order) of this appearance; the earliest appearance sets title and year."""
        if title and is_sentence(title):
            title = None                     # a motion or outcome sentence is never an item's title (nor links one)
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
            prior = self.items.get(iid, {}).get("title")
            if prior not in (None, number, "(untitled)") and title in (number, "(untitled)"):
                title = prior                                # keep a real title over the bare number
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
        # the meeting's date and kind come from its own header text (collector.parse.minutes_segments), never from
        # the index link label, which may name another month
        date = pm.meeting_date
        if not date:
            self.problems.append({"source": sid, "url": src["url"],
                                  "problem": f"no readable meeting date in the minutes header on p{att.page if att else 1}"})
            return
        kind = pm.kind
        mid = f"{date}-{kind}"
        if any(m["id"] == mid for m in self.meetings):
            raise ValueError(f"meeting {mid} added twice: collector.meetings.choose must pick one copy")
        if sid not in {s["id"] for s in self.sources}:
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
        rcs = pm.roll_calls
        pairs = pair_consent(pm.consent_lists, rcs)
        own_items = {rc.item for rc in rcs if rc.kind != "consent" and rc.item and P.valid_number(rc.item)}
        reprints, unplaced = consent_groups(rcs)
        groups: dict[int, list] = {}          # roll call index -> every printing of its vote, itself first
        for g, c in reprints.items():
            groups.setdefault(c, [c]).append(g)
        rid_of = {k: f"rc-{s8}-p{rc.page}-{rc.ordinal_on_page}" for k, rc in enumerate(rcs)}
        consent_iid: dict[int, str] = {}
        in_record = {k: not any(re.search(r"inside an earlier meeting|boundaries uncertain", x)
                                for x in rc.context_reasons) for k, rc in enumerate(rcs)}

        def order_of(rc):
            return rc.line - next(i for i, p in enumerate(lines_page) if p == rc.page) if lines_page else 0

        for k, rc in enumerate(rcs):
            if k in reprints:
                continue                 # a reprint of one consent vote: an event below, not another roll call
            rid = rid_of[k]
            order = order_of(rc)
            best = next((r for r in rc.readings + ([rc.combined] if getattr(rc, "combined", None) else [])
                         if r.votes is rc.votes), rc.readings[0] if rc.readings else None)
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
            extra = []
            if source_inconsistent(rc):
                self.source_errors.add(rid)
                extra.append({"check": "source_consistent", "ok": False,
                              "detail": "readings agree; the minutes contradict themselves (vote mark vs ABSENT line)"})
            vids = [v["official_id"] for v in votes if v["official_id"]]
            dup = sorted({o for o in vids if vids.count(o) > 1})
            # attribution/one-entry-per-official: two table entries for one official hold the roll call
            extra.append({"check": "one_entry_per_official", "ok": not dup,
                          **({"detail": "two entries resolve to: " + ", ".join(dup)} if dup else {})})
            group = sorted(g for g, c in reprints.items() if c == k)
            if k in unplaced:
                extra.append({"check": "consent_printing_placed", "ok": False,
                              "detail": "a consent table whose motion is unread fits more than one consent vote here"})
            if group:
                clash = [f"p{rcs[g].page}: {d}" for g in group
                         for d in P.disagreements(_reading_of(rc), _reading_of(rcs[g]))]
                extra.append({"check": "reprints_agree", "ok": not clash,
                              **({"detail": "; ".join(clash)[:500]} if clash else {})})
            rver = verification(rver["checks"] + extra)
            clause = rc.outcome_clause or rc.outcome_text or ""
            if rc.kind == "consent":
                iid = self.item_for(None, "Consent Agenda", (date, rc.page, order), rid)
                consent_iid[k] = iid
            else:
                # a numbered item: the agenda's title for that number, else the number alone (never the motion)
                title = (pm.titles.get(rc.item) if rc.item and P.valid_number(rc.item) else
                         subject_of(clause) or rc.motion_text)
                iid = self.item_for(rc.item, title, (date, rc.page, order), rid)
            moid = None
            if rc.raw_mover is not None:
                moid = f"mo-{s8}-p{rc.page}-{rc.ordinal_on_page}"
                refs = []
                for raw in (rc.raw_mover, rc.raw_seconder):
                    # rule 3 (surname at this meeting) only when every header name resolved: an unresolved header
                    # name could carry the same surname (attribution/motion-ignores-context)
                    oid, _rule = self.r.resolve(raw, roster_ids if not unresolved else None)
                    if oid is None:
                        self.note_unresolved(f"Commissioner {raw}", f"{sid} p{rc.page}")
                    refs.append({"official_id": oid, "raw_name": raw})
                att_ok = mver["status"] == "verified"
                context = {
                    "attendance_verified": (att_ok, None if att_ok else "the meeting's attendance is held back"),
                    "in_meeting_record": (in_record[k], None if in_record[k] else
                                          "the vote is not certainly inside this meeting's own minutes"),
                    "motion_precedes_vote": (rc.motion_linked, None if rc.motion_linked else
                                             "the motion sentence does not lead into this vote's outcome clause"),
                }
                self.motions.append({"id": moid, "meeting_id": mid, "item_id": iid, "text": rc.motion_text or "",
                                     "moved_by": refs[0], "seconded_by": refs[1], "source_id": sid, "page": rc.page,
                                     "verification": motion_verification(refs[0], refs[1], present_ids, True,
                                                                         context)})
                ev(iid, "motion", rc.motion_text, moid, rc.page, max(order - 1, 0), 1)
            self.roll_calls.append({
                "id": rid, "meeting_id": mid, "item_id": iid, "motion_id": moid, "votes": votes,
                # the counts as printed: a count printed blank is null, never the number derived for the check
                # (neutrality/derived-count-shown-as-stated)
                "stated_tally": (dict(zip(("yes", "no", "abstain"), rc.printed_tally or rc.tally))
                                 if rc.tally else None),
                "outcome": {"pass": "passed", "fail": "failed"}.get(oc, "other"),
                "outcome_text": " ".join(clause.split()), "source_id": sid, "page": rc.page, "verification": rver})
            ev(iid, "roll_call", clause, rid, rc.page, order, 2)

        # the items one consent vote covered: the item numbers of every printing's list (OCR garbles some numbers in
        # some printings), minus numbers any printing names as pulled
        nums_of: dict[int, frozenset] = {}
        for k in consent_iid:
            ks = groups.get(k, [k])
            pulled = {n for j in ks if j in pairs for n in pairs[j].pulled}
            nums_of[k] = frozenset(n for j in ks for n in consent_numbers(pairs.get(j))) - pulled

        # consent reprints: each printing becomes an event on the resolution it follows, pointing at the one vote
        for g, c in sorted(reprints.items()):
            rc = rcs[g]
            if rc.follows_item in nums_of[c] and rc.follows_item not in own_items:
                target = self.item_for(rc.follows_item, None, (date, rc.page, order_of(rc)), rid_of[g])
            else:
                target = consent_iid[c]
            ev(target, "roll_call", rc.outcome_clause or rc.outcome_text, rid_of[c], rc.page, order_of(rc), 2)
            self.consent_reprints[rid_of[g]] = rid_of[c]

        # consent lists: each item one vote covered gets that vote as an event on its own history. Numbered entries
        # come from every printing's list; unnumbered ones (minutes, reports, nominations, whose OCR spelling varies
        # between printings) only from the first printing that has a list.
        list_vote = {id(cl): k for k, cl in pairs.items()}
        done: set[int] = set()
        for cl in pm.consent_lists:
            k = list_vote.get(id(cl))
            if k is None:                       # a list paired with no consent roll call: listings only
                seen = set()
                for e in cl.entries:
                    if e.number and (e.number in cl.pulled or e.number in seen or e.number in own_items):
                        continue
                    seen.add(e.number)
                    iid = self.item_for(e.number, e.title, (date, e.page, e.order), f"{sid}-p{e.page}-{e.order}")
                    ev(iid, "other", cl.label, None, e.page, e.order, 3)
                continue
            c = reprints.get(k, k)
            if c in done:
                continue
            done.add(c)
            ks = sorted((j for j in groups.get(c, [c]) if j in pairs), key=lambda j: rcs[j].line)
            first = pairs[ks[0]]
            entries = list(first.entries)
            have = {e.number for e in entries if e.number}
            for j in ks[1:]:
                for e in pairs[j].entries:
                    if e.number and e.number not in have:
                        entries.append(e)
                        have.add(e.number)
            seen = set()
            for e in entries:
                key = e.number or norm_title(e.title)
                if (e.number and e.number not in nums_of[c]) or key in seen:
                    continue                   # pulled from the consent agenda, or listed twice
                seen.add(key)
                if e.number and e.number in own_items:
                    continue                   # item-history/consent-pulled: it had its own roll call here
                iid = self.item_for(e.number, e.title, (date, e.page, e.order), f"{sid}-p{e.page}-{e.order}")
                ev(iid, "roll_call", first.label, rid_of[c], e.page, e.order, 3)
                ev(consent_iid[c], "other", e.label, None, e.page, e.order, 4)

        # one event per (item, roll call): an item listed on the consent agenda and also followed by a reprint of the
        # vote, or a vote reprinted several times, still shows that vote once. The event kept is the vote's printing
        # nearest the item (the table itself, or the reprint right after the item's own resolution), else the first
        # list entry, in document order
        firsts: set[tuple] = set()
        drop = set()
        for n, x in sorted(enumerate(events), key=lambda t: (t[1]["_rank"] != 2, t[1]["page"], t[1]["order"])):
            if x["type"] == "roll_call":
                if (x["item_id"], x["ref"]) in firsts:
                    drop.add(n)
                firsts.add((x["item_id"], x["ref"]))
        events[:] = [x for n, x in enumerate(events) if n not in drop]

        consent_ids = {rid_of[k]: iid for k, iid in consent_iid.items()}
        paired = {e["ref"] for e in events if e["type"] == "roll_call" and e["ref"] in consent_ids
                  and e["item_id"] != consent_ids[e["ref"]]}
        self.consent_unexpanded += [rid for rid in consent_ids if rid not in paired]

        # ids: ev-<sha8>-p<page>-<n>, n by position on the page
        events.sort(key=lambda x: (x["page"], x["order"], x["_rank"], x["item_id"]))
        # (counted per source page across every meeting of the document, so two meetings sharing a page never
        # share an id)
        for x in events:
            k = self._ev_count.get((s8, x["page"]), 0)
            self._ev_count[(s8, x["page"])] = k + 1
            x["id"] = f"ev-{s8}-p{x['page']}-{k}"
            del x["_rank"]
            self.events.append(x)
        sg = getattr(pm, "segment", None)
        self.doc_summary.append({"source_id": sid, "label": src.get("label"), "meeting_id": mid, "pages": pm.pages,
                                 "minutes_pages": [sg.page, sg.end_page] if sg else None,
                                 "role": sg.role if sg else None,
                                 "roll_calls": len(pm.roll_calls) - len(reprints),
                                 "consent_reprints": len(reprints),
                                 "verified": sum(r.status == "Verified" for k, r in enumerate(pm.roll_calls)
                                                 if k not in reprints),
                                 "attendance": status, "image_only_pages": len(pm.image_only_pages)})

    # ------------------------------------------------------------ zoning cases
    def add_zoning(self, pd) -> None:
        """Pool one document's zoning readings (collector.zoning). Only a document cited by the facts counts, so
        every value links to a source page in `sources`."""
        sid = f"src-{pd.source['sha256'][:12]}"
        src = next((s for s in self.sources if s["id"] == sid), None)
        if src is None:
            return
        for r in getattr(pd, "zoning", []):
            self.zoning.setdefault(r.case, []).append((r, sid, src["meeting_date"]))

    def zoning_facts(self) -> dict:
        """item id -> its `zoning` object, for every item that is a rezoning case."""
        from . import zoning as Z
        rules = Z.load_rules()
        if rules is None:
            return {}
        return {iid: Z.decide(self.zoning.get(iid, [])) for iid, it in self.items.items()
                if it["number"] and it["number"].split("-")[0] in rules.case_prefixes}

    # ------------------------------------------------------------ output
    def facts(self, officials: list[dict]) -> dict:
        dates = [m["date"] for m in self.meetings]
        zf = self.zoning_facts()
        items = [dict(it, zoning=zf[it["id"]]) if it["id"] in zf else it for it in self.items.values()]
        return {
            "schema_version": "1.0",
            "coverage": {"body": BODY, "from": min(dates) if dates else "2020-01-01",
                         "to": max(dates) if dates else "2024-12-31"},
            "sources": sorted(self.sources, key=lambda x: x["id"]),
            "officials": public_officials(officials),
            "meetings": sorted(self.meetings, key=lambda x: x["id"]),
            "items": sorted(items, key=lambda x: x["id"]),
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
