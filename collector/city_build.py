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
import sys
import unicodedata
from collections import Counter, defaultdict

from . import limits
from .agenda_center import AgendaCenterConfig
from .city_minutes import (NAME_RE, ParsedCityMinutes, page_has, page_has_line, parse_minutes_pdf, pdf_layer, read_pages,
                           short_hash)
from .extract import extract_pages
from .store import Store
from .verify import gates

SCHEMA_VERSION = "1.0"
SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
# "failed due to lack of 2/3 majority": a motion can fail with more yes than no when the minutes say a larger
# majority was required. Only then is a yes > no failure consistent.
THRESHOLD_RE = re.compile(r"2/3|two[- ]thirds|majority", re.I)
MINUTES_STATUS = ("read", "scan_not_read", "not_posted", "not_fetched", "parse_failed", "other_meeting", "unreadable")


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


def break_free(s: str) -> str:
    """The break-free key of a printed name (W2, path N9): lowercased (str.lower, as every other resolution step
    compares), every whitespace character removed. Nothing else changes: no letter, apostrophe, hyphen or period is
    added, dropped, replaced or reordered (so no NFKC or casefold, which turn one letter into others: "ß" -> "ss",
    "ﬁ" -> "fi")."""
    return re.sub(r"\s+", "", s.lower())


def break_free_match(token: str, people: list[tuple[str, str]]) -> str | None:
    """Path N9, the last step of N1/N6, N7 and N8: the one key in `people` ([(key, full name)], that step's own closed
    set) whose full name or surname has the printed token's break-free key, else None (none, or two or more people:
    held as before). "H AYWOOD" -> HAYWOOD's member when exactly one roster member is Haywood; never a near spelling,
    never a person outside the set."""
    k = break_free(token)
    if not k:
        return None
    hits = {key for key, n in people if k in (break_free(n), break_free(name_parts(n)[1]))}
    return next(iter(hits)) if len(hits) == 1 else None


def resolve_with(token: str, roster: list[tuple[str, str]], aliases: dict | None = None,
                 cut: bool = False) -> tuple[str | None, bool]:
    """resolve(), and whether the match was the break-free key (N9), so each such use is listed. `cut`: the printed
    token runs over a line end of its list (Vote.line_cut, RollCall.absent_cut): N9 never joins across a line end
    (W2 rule 5), so only the exact steps are tried."""
    t = clean_name(token)
    t = (aliases or {}).get(t, t).lower()
    full = [oid for oid, n in roster if n.lower() == t]
    if len(full) == 1:
        return full[0], False
    sur = [oid for oid, n in roster if name_parts(n)[1].lower() == t]
    if len(sur) == 1:
        return sur[0], False
    m = re.match(r"^([a-z])\.?\s+(.+)$", t)
    if m:
        ini = [oid for oid, n in roster
               if name_parts(n)[1].lower() == m.group(2) and name_parts(n)[0][:1].lower() == m.group(1)]
        if len(ini) == 1:
            return ini[0], False
    if cut:
        return None, False
    oid = break_free_match(t, roster)                       # N9: last step, this meeting's roster only
    return oid, oid is not None


def resolve(token: str, roster: list[tuple[str, str]], aliases: dict | None = None, cut: bool = False) -> str | None:
    """A vote name as printed -> the one roster official it names, else None. roster: [(official_id, full name)].
    The printed name is read through the alias list first (whole printed names only, path N2: 'Amber Marquis' ->
    'Ambar Marquis'). Matches, in order: the full name; the surname; an initial plus surname ('W. Smith'); then, last,
    the break-free key ('H AYWOOD', path N9; not for a token cut at a line end). Never a near spelling."""
    return resolve_with(token, roster, aliases, cut)[0]


def word_break_note(printed: str, name: str) -> str:
    """How a break-free (N9) use is named in its check's detail and the run report. The same words whichever way the
    spaces differ: a break printed inside a name ("H AYWOOD read as Jerry Haywood ...") or a space left out
    ("StaceyStreetman read as Stacey Streetman ...")."""
    return f"{clean_name(printed)} read as {name} (same letters, spaces ignored)"


def _check(name: str, ok: bool, detail: str | None = None) -> dict:
    c = {"check": name, "ok": bool(ok)}
    if detail:
        c["detail"] = detail
    return c


def _verification(checks: list[dict]) -> dict:
    return {"status": "verified" if all(c["ok"] for c in checks) else "unverified",
            "checks": sorted(checks, key=lambda c: c["check"])}


PDFINFO_TIMEOUT = 120      # seconds (pipeline/parser-dos-untimed); a timeout fails that file, not the build


def pdf_pages(path) -> int:
    out = limits.run("city_build.PDFINFO_TIMEOUT", ["pdfinfo", str(path)], file=path, capture_output=True,
                     timeout=PDFINFO_TIMEOUT).stdout.decode("utf-8", "replace")
    m = re.search(r"^Pages:\s*(\d+)", out, re.M)
    return max(int(m.group(1)), 1) if m else 1


def source_record(entry: dict, pages: int, layer: str) -> dict:
    return {"id": f"src-{entry['sha256'][:12]}", "url": entry["url"], "sha256": entry["sha256"],
            "kind": entry["kind"], "meeting_date": entry["meeting_date"],
            "fetched_at": (entry["first_fetched_at"] or "")[:10], "pages": pages, "text_layer": layer}


def inspect_pdf(path) -> tuple[int, str]:
    """(page count, text layer) of a stored PDF."""
    return pdf_pages(path), pdf_layer(path, extract_pages(path))


def page1_check(row: dict, store: Store, pages=read_pages) -> str | None:
    """D1: a row from an also-listing (civicclerk also_list, `page1_required`) is this body's meeting only when page 1
    of its stored minutes or agenda prints that text as a line of its own (city_minutes.page_has_line: never the same
    words inside a longer line). None when it does (or the row needs no check), else why the event is skipped.
    Nothing else about the event is read before it passes."""
    want = row.get("page1_required")
    if not want:
        return None
    read = []
    for kind in ("minutes", "agenda"):
        e = store.latest(row[f"{kind}_url"]) if row.get(f"{kind}_url") else None
        if not e or not store.has_bytes(e["sha256"]):
            continue
        read.append(kind)
        try:
            first = (pages(store.path_for(e["sha256"])) or [""])[0]
        except Exception as ex:                        # one bad file must not stop the build: skipped and named
            read[-1] = f"{kind} (unreadable: {type(ex).__name__})"
            continue
        if page_has_line(first, want):
            return None
    where = " or ".join(read) if read else "no stored agenda or minutes"
    return (f"listed as {row.get('listed_as') or 'another category'}; page 1 of its {where} does not print "
            f"'{want}' on a line of its own: skipped, not this body's meeting")


def minutes_identity(row: dict, path, cfg: AgendaCenterConfig, parse=parse_minutes_pdf, pages=read_pages) -> str | None:
    """D1 (d1-minutes-identity/agenda-heading-vouches-for-minutes): the stored minutes of a row from an also-listing
    (`page1_required`) are read for this meeting only when page 1 of the minutes themselves prints that text as a line
    of its own AND every meeting date they print is the row's date: the call-to-order sentence's and the page-1
    heading's (city_minutes.heading_date), at least one of them printed, none another day. Two dates that disagree
    (the 2026-07-09 minutes: heading "July 9, 2026", called to order "on Monday, July 6, 2026") do not say which
    meeting the votes are from, so the minutes are held. The agenda's page 1 (page1_check) may keep the meeting, but
    it never vouches for another file. None when the minutes pass (or the row needs no check), else why they are not
    read: the meeting is then built from its agenda alone (minutes_status other_meeting), or skipped when its agenda
    does not pass page1_check. A file that cannot be read for this check is not read at all (fail closed)."""
    want = row.get("page1_required")
    if not want:
        return None
    try:
        first = (pages(path) or [""])[0]
        if not page_has_line(first, want):
            return (f"listed as {row.get('listed_as') or 'another category'}; page 1 of its minutes does not print "
                    f"'{want}' on a line of its own: the minutes are not read for this meeting")
        pm = parse(path, cfg)
    except Exception as ex:                            # one bad file must not stop the build: not read, and named
        return f"its minutes could not be read to check which meeting they record ({type(ex).__name__}): not read"
    printed = [f"{d} in {where}" for d, where in ((pm.printed_date, "the call-to-order sentence"),
                                                  (pm.heading_date, "the page-1 heading")) if d]
    if not printed or {pm.printed_date, pm.heading_date} - {None} != {row["date"]}:
        return (f"listed as {row.get('listed_as') or 'another category'} for {row['date']}; its minutes print "
                f"{' and '.join(printed) or 'no meeting date'}: not read for this meeting")
    return None


def cited_members(cfg: AgendaCenterConfig, store: Store, pages=read_pages,
                  kept: set | None = None) -> tuple[list[dict], list[dict]]:
    """Build check `member_cited` for each configured member (path N10, M1): the stored bytes for its cite_url exist;
    the stored file is of the entry's kind (the manifest's kind equals `kind`; an agenda never qualifies); `seated` is
    not before the cited record's meeting (nor, for a roster page snapshot, before it was fetched), and a date that
    check needs is present; the quote names the person and prints "Ward {ward}" as whole words; the quote,
    whitespace collapsed, is printed on cite_page of the stored file's text; and, when `kept` is given (the source
    ids of the council meetings the build kept), the cited file is the source of one of them
    (city-verify/cited-member-body-unchecked: never another body's minutes). build() makes the last check once its
    meetings are known, and builds again without any entry that fails it.
    -> (entries that pass, each with the cited file's manifest entry; one report row per entry). An entry that fails
    is left out of the roster book for this build, so its surname is held as before: never resolved on trust."""
    ok, report = [], []
    for m in cfg.members:
        e = store.latest(m["cite_url"])
        why = None
        fetched = ((e or {}).get("first_fetched_at") or "")[:10]
        if not e or not store.has_bytes(e["sha256"]):
            why = "the cited file is not stored"
        elif e.get("kind") == "agenda":
            why = "the cited file is an agenda (it schedules an act and does not record it)"
        elif e.get("kind") != m["kind"]:
            why = f"the cited file is stored as {e.get('kind') or 'no kind'}, not {m['kind']}"
        elif m["kind"] != "roster_page" and not e.get("meeting_date"):
            why = "the cited record has no meeting date, so the seated date cannot be checked"
        elif e.get("meeting_date") and m["seated"] < e["meeting_date"]:
            why = f"seated {m['seated']} is before the cited record's meeting of {e['meeting_date']}"
        elif m["kind"] == "roster_page" and not fetched:
            why = "the roster page has no fetch date, so the seated date cannot be checked"
        elif m["kind"] == "roster_page" and m["seated"] < fetched:
            why = f"seated {m['seated']} is before the roster page was fetched ({fetched})"
        elif m["name"] not in m["quote"]:
            why = "the quote does not name the person"
        elif not re.search(rf"\bWard\s+{int(m['ward'])}\b", m["quote"]):
            why = f"the quote does not print Ward {m['ward']}"
        else:
            try:
                text = pages(store.path_for(e["sha256"]))
            except Exception as ex:                             # one bad file must not stop the build
                text, why = [], f"the cited file could not be read: {type(ex).__name__}"
            if why is None and not (m["cite_page"] <= len(text) and page_has(text[m["cite_page"] - 1], m["quote"])):
                why = f"the quote is not on page {m['cite_page']} of the cited file"
            if why is None and kept is not None and f"src-{e['sha256'][:12]}" not in kept:
                why = "the cited file is not the source of a council meeting this build kept"
        report.append({"check": "member_cited", "ok": why is None, "name": m["name"], "ward": m["ward"],
                       "seated": m["seated"], "cite_url": m["cite_url"], "cite_page": m["cite_page"],
                       "detail": why or f"quote found on page {m['cite_page']}"})
        if why is None:
            ok.append({**m, "entry": e})
    return ok, report


def member_basis(m: dict) -> str:
    """How a surname read from a configured member is named: 'the configured member Eric Claunch (seated 2026-02-19,
    minutes p. 3)'."""
    return f"the configured member {m['name']} (seated {m['seated']}, {m['kind'].replace('_', ' ')} p. {m['cite_page']})"


def build(cfg: AgendaCenterConfig, rows: list[dict], store: Store, parse=parse_minutes_pdf,
          inspect=inspect_pdf, pages=read_pages, _kept: set | None = None) -> tuple[dict, dict]:
    """The city's facts from the listing rows and the stored files -> (facts with "_wards", run summary).

    A configured member counts only when its cited file is the source of a council meeting this build keeps
    (city-verify/cited-member-body-unchecked). Which meetings are kept never depends on the members, so when an entry
    fails that check the build runs once more with `_kept` (the kept meetings' source ids) and the entry left out:
    nothing it would have resolved stays in the facts. Fail closed; no second run when every entry passes."""
    officials = Officials(cfg)
    sources: dict[str, dict] = {}
    meetings, roll_calls, motions, items, events, wards = [], [], [], {}, [], []
    problems, unresolved = [], Counter()
    members, members_report = cited_members(cfg, store, pages, _kept)   # path N10: only entries whose cite checks out
    book = RosterBook(cfg, members)  # full-name attendance lists so far, bounded per meeting (resolve_surnames)
    word_breaks: list[dict] = []    # every break-free (N9) use, for the run report
    status_count = Counter()
    ids_used: Counter = Counter()
    skipped_events = []

    uninspectable: set = set()

    def unreadable(url: str | None) -> bool:
        """The file at url was fetched, but pdfinfo/pdftotext could not inspect it (collector-input/unread-file-
        mislabel: it is not 'not fetched')."""
        e = store.latest(url) if url else None
        return bool(e) and f"src-{e['sha256'][:12]}" in uninspectable

    def source_for(url: str | None):
        if not url:
            return None, None
        e = store.latest(url)
        if not e or not store.has_bytes(e["sha256"]):
            return None, None
        sid = f"src-{e['sha256'][:12]}"
        path = store.path_for(e["sha256"])
        if sid not in sources:
            if sid in uninspectable:
                return None, None
            try:
                sources[sid] = source_record(e, *inspect(path))
            except (OSError, subprocess.SubprocessError) as ex:
                # pipeline/parser-dos-untimed: pdfinfo/pdftotext timed out or failed on this file. Fail closed: the
                # file is not cited or read (as if not fetched), reported once, and the build goes on
                uninspectable.add(sid)
                msg = f"pdf inspection failed ({type(ex).__name__}: {ex}): file not read or cited"
                problems.append({"url": url, "sha256": e["sha256"], "problem": msg})
                print(f"city build: skipped {url}: {msg}", file=sys.stderr, flush=True)
                return None, None
        return sources[sid], path

    # Agenda Center rows first on a day (their meeting ids were published first), then CivicClerk rows; within a
    # source by its own id, so ids of one kind on one day (-2, -3) stay put
    # one minutes file posted for two meetings (CivicClerk posted the 2024-08-01 minutes again as the 2024-09-05
    # minutes): it is read only for the meeting whose date its call-to-order sentence prints, and only once
    posted = Counter(e["sha256"] for e in (store.latest(r["minutes_url"]) for r in rows if r["minutes_url"]) if e)
    read_shas: set = set()
    for r in sorted(rows, key=lambda r: (r["date"], r.get("source", "agenda-center") != "agenda-center",
                                         int(r["agenda_id"].split("-")[-1]))):
        skip = page1_check(r, store, pages)
        if skip:
            skipped_events.append({"date": r["date"], "title": r["title"], "event_id": r.get("event_id"),
                                   "listed_as": r.get("listed_as"), "reason": skip})
            problems.append({"meeting": r["date"], "title": r["title"], "problem": skip})
            continue
        # D1: an also-listed row's minutes are read only when they themselves print its heading and date; checked
        # before they are inspected or cited, so a file that fails is never this meeting's source
        e = store.latest(r["minutes_url"]) if r.get("page1_required") and r["minutes_url"] else None
        other_meeting = (minutes_identity(r, store.path_for(e["sha256"]), cfg, parse, pages)
                         if e and store.has_bytes(e["sha256"]) else None)
        if other_meeting:
            skip = page1_check({**r, "minutes_url": None}, store, pages)    # the agenda alone must keep it
            if skip:
                skip += f" (and {other_meeting})"
                skipped_events.append({"date": r["date"], "title": r["title"], "event_id": r.get("event_id"),
                                       "listed_as": r.get("listed_as"), "reason": skip})
                problems.append({"meeting": r["date"], "title": r["title"], "problem": skip})
                continue
            problems.append({"meeting": r["date"], "title": r["title"], "problem": other_meeting})
        agenda_src, _ = source_for(r["agenda_url"])
        minutes_src, minutes_path = (None, None) if other_meeting else source_for(r["minutes_url"])
        if minutes_src and (posted[minutes_src["sha256"]] > 1 or minutes_src["sha256"] in read_shas):
            other_meeting = _other_meeting(minutes_src, minutes_path, r, cfg, parse, read_shas)
            if other_meeting:
                problems.append({"meeting": r["date"], "title": r["title"], "problem": other_meeting})
                minutes_src, minutes_path = None, None
                if not agenda_src:
                    status_count["not_in_facts"] += 1
                    continue
        src = minutes_src or agenda_src
        if not src:
            status_count["not_in_facts"] += 1
            problems.append({"meeting": r["date"], "title": r["title"],
                             "problem": ("the fetched file could not be read and there is no other file to cite: "
                                         "left out of facts" if unreadable(r["minutes_url"]) or
                                         unreadable(r["agenda_url"]) else
                                         "no fetched agenda or minutes file to cite: left out of facts")})
            continue
        kind = cfg.kind_of(r["title"])            # from the title and the current config, not the stored listing
        base = f"{r['date']}-{kind}"
        ids_used[base] += 1
        mid = base if ids_used[base] == 1 else f"{base}-{ids_used[base]}"
        pm: ParsedCityMinutes | None = None
        if not r["minutes_url"]:
            mstatus = "not_posted"
        elif other_meeting:
            mstatus = "other_meeting"
        elif not minutes_src:
            mstatus = "unreadable" if unreadable(r["minutes_url"]) else "not_fetched"
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
        if r.get("also_listed"):            # the other listing of this meeting (merge_sources): its files stay cited
            meeting["also_listed"] = [also_listed(x, source_for) for x in r["also_listed"]]
        meetings.append(meeting)
        if pm is None or mstatus != "read":
            meeting["verification"] = _verification([_check("minutes_read", False, mstatus)])
            continue
        read_shas.add(minutes_src["sha256"])
        _add_minutes(cfg, officials, meeting, minutes_src, pm, roll_calls, motions, items, events, wards,
                     problems, unresolved, book.for_meeting(meeting["date"]), word_breaks)
        book.add(printed_full_names(cfg, officials, pm, meeting["date"]))

    kept = {x["source_id"] for x in meetings}
    if any(f"src-{m['entry']['sha256'][:12]}" not in kept for m in members):
        if _kept is not None:         # cannot happen (cited_members left them out): never publish on trust
            raise RuntimeError("city build: a configured member's cited file is not a kept meeting's source")
        return build(cfg, rows, store, parse, inspect, pages, _kept=kept)
    for m in members:                 # a configured member who resolved: the record that names them, and their seat
        oid = official_id(officials.canonical(m["name"]))
        if oid not in officials.by_id:
            continue
        src, _ = source_for(m["cite_url"])
        officials.by_id[oid]["name_source"] = {"source_id": src["id"], "page": m["cite_page"], "quote": m["quote"]}
        cited = next((x for x in meetings if src["id"] in (x["source_id"], x.get("agenda_source_id"))), None)
        # Ward holder record from the seating date, with its source (seat holder invariant, rule 1)
        wards.append({"official_id": oid, "raw_name": m["name"], "ward": m["ward"], "pro_tem": False,
                      "meeting_id": cited["id"] if cited else None, "date": m["seated"], "source_id": src["id"],
                      "page": m["cite_page"], "configured": True})
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
    problems += [{"member": r["name"], "problem": f"configured member left out: {r['detail']}"}
                 for r in members_report if not r["ok"]]
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
        "skipped_events": skipped_events,       # D1: also-listed events whose page 1 is not this body's
        "members": members_report,              # M1: the build check member_cited, one row per configured member
        # W2 (path N9): every name read by its break-free key, for QA's AC-P2 sample
        "word_break_matches": word_breaks,
        # AC-P1 verified rate and G4 skew, the county's gate code as is (collector/verify.gates, architecture
        # "Invariant: held-back counts"; city-verify/no-skew-gate). No city check marks a hold as an error of the
        # source document itself (the county's `source_consistent`), so none is left out of the rates.
        "gates": gates(facts, set()),
    }
    summary["pass"] = summary["gates"]["verified_rate_gate"]["pass"] and summary["gates"]["g4"]["pass"]
    return {**facts, "_wards": wards}, summary


def also_listed(x: dict, source_for) -> dict:
    """One other listing of a meeting (civicclerk.merge_sources `also_listed`) as the facts keep it: its source,
    title and file links, plus the fetched file's source id where the file was fetched (city-merge/dropped-citation).
    Nothing is read from those files."""
    out = {"source": x["source"], "title": x["title"], "agenda_url": x.get("agenda_url"),
           "minutes_url": x.get("minutes_url")}
    for kind in ("agenda", "minutes"):
        src, _ = source_for(out[f"{kind}_url"])
        if src:
            out[f"{kind}_source_id"] = src["id"]
    return out


def _other_meeting(src: dict, path, row: dict, cfg, parse, read_shas: set) -> str | None:
    """Why a minutes file listed for more than one meeting is not this meeting's, or None when it is. The date is the
    call-to-order sentence's, or, when that prints no full date, the page-1 heading's (the 2026-02-11 minutes, also
    posted for the meeting resumed 2026-02-19, print "Wednesday, February 11," and "February 11, 2026 at 4:30 PM")."""
    try:
        pm = parse(path, cfg)
        printed = pm.printed_date or pm.heading_date
    except Exception as ex:                                   # read again (and reported) in the main loop
        return f"the same minutes file is listed for another meeting and could not be read: {type(ex).__name__}"
    if printed != row["date"]:
        return (f"the minutes file listed for this meeting is also listed for another meeting and records the meeting "
                f"of {printed or 'an unprinted date'}: not read for this one")
    if src["sha256"] in read_shas:
        return "the same minutes file was already read for another meeting on this date: not read again"
    return None


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


def _out_of_room(pm: ParsedCityMinutes, roster, part_time: dict, aliases: dict | None = None) -> list[set]:
    """For each roll call of the meeting, the members its missing-vote check exempts: a member noted as arriving
    late, for the votes before their first recorded vote; one noted as leaving early, for the votes after their
    last. A noted member with no recorded vote at all cannot be placed, so is exempt from every vote."""
    voted = [{resolve(v.raw_name, roster, aliases, v.line_cut) for v in rc.votes} for rc in pm.roll_calls]
    out = [set() for _ in pm.roll_calls]
    for oid, p in part_time.items():
        ks = [k for k, s in enumerate(voted) if oid in s]
        for k in range(len(voted)):
            if not ks or (p.arrived_late and k < ks[0]) or (p.left_early and k > ks[-1]):
                out[k].add(oid)
    return out


SURNAME_RE = re.compile(r"^[A-Za-z][A-Za-z'’-]+$")


def printed_full_names(cfg, officials: Officials, pm: ParsedCityMinutes, date: str) -> dict:
    """The full names these minutes print in their attendance list, by surname:
    {surname (lower case): {"date": date, "people": [{name, ward, mayor}]}}. Names that are not full names are
    left out, and so is the call-to-order sentence: a presiding name is never evidence of a member (path N3; the
    mayor's seat comes from the configured `mayors`, see RosterBook). A later surname-only attendance list is read
    against these through RosterBook, never directly."""
    out: dict[str, dict] = {}
    people = [{"name": officials.canonical(p.raw_name), "ward": p.ward, "mayor": p.mayor}
              for p in pm.present + pm.absent if NAME_RE.match(clean_name(p.raw_name))]
    for r in people:
        e = out.setdefault(name_parts(r["name"])[1].lower(), {"date": date, "people": []})
        if r["name"] not in [x["name"] for x in e["people"]]:
            e["people"].append(r)
    return out


def _seat(p: dict) -> str | None:
    """The seat a printing names: 'Ward 3', 'Mayor', or None (no ward printed)."""
    return "Mayor" if p["mayor"] else (f"Ward {p['ward']}" if p["ward"] is not None else None)


class RosterBook:
    """The full-name attendance lists read so far (printed_full_names, one per read meeting), and, for one meeting,
    the book its surname-only attendance is read against (name resolution invariant, docs/architecture/city-council.md):
    {surname: {"people": [{name, ward, mayor, date}], "held": [why a printing of that surname is not used]}}.

    Only lists dated from the council's latest seating (cfg.seated_on) up to the meeting are used, so a member who
    left at an earlier seating is never a candidate. A member on those lists is kept when printed on the latest of
    them, or when the latest of them that prints the member's seat (ward, or mayor) still prints this member there
    (a list cut short, like 2025-02-06's, does not drop the members after the cut). A member printed without a ward
    and not on the latest list, or whose seat a later list gives to someone else, is held with the reason. `date` is
    the member's own latest printing.

    The configured, cited mayor whose term covers the meeting (cfg.mayors_on) is in the book too, as the Mayor seat
    ({..., "mayor": True, "date": the term's start, "configured": True}): the only entry not read from a list."""

    def __init__(self, cfg, members: list[dict] | tuple = ()):
        self.cfg = cfg
        self.members = sorted(members, key=lambda m: m["seated"])    # cited_members: entries whose cite checked out
        self.lists: list[tuple[str, list[dict]]] = []

    def add(self, printed: dict) -> None:
        people = [p for e in printed.values() for p in e["people"]]
        if people:
            self.lists.append((next(iter(printed.values()))["date"], people))

    def for_meeting(self, date: str) -> dict:
        start = self.cfg.seated_on(date)
        inside = sorted((x for x in self.lists if start is not None and start <= x[0] <= date), key=lambda x: x[0])
        latest: dict[str, tuple[str, dict]] = {}
        seat: dict[str, tuple[str, set]] = {}            # seat -> (date of the latest list printing it, names there)
        for d, people in inside:
            for p in people:
                latest[p["name"]] = (d, p)
                k = _seat(p)
                if k:
                    if k not in seat or seat[k][0] != d:
                        seat[k] = (d, set())
                    seat[k][1].add(p["name"])
        last = inside[-1][0] if inside else None
        out: dict[str, dict] = {}

        def entry(name: str) -> dict:
            return out.setdefault(name_parts(name)[1].lower(), {"people": [], "held": []})

        for name, (d, p) in sorted(latest.items()):
            k = _seat(p)
            if d == last or (k and name in seat[k][1]):
                entry(name)["people"].append({**p, "date": d})
            elif k:
                entry(name)["held"].append(f"{name}: {k} printed for {', '.join(sorted(seat[k][1]))} on {seat[k][0]}")
            else:
                entry(name)["held"].append(f"{name}: printed without a ward on {d}, not on the list of {last}")
        before = {}
        for d, people in self.lists:
            if (start is None or d < start) and d <= date:
                for p in people:
                    if p["name"] not in latest:
                        before[p["name"]] = d
        for name, d in sorted(before.items()):
            entry(name)["held"].append(f"{name}: last printed {d}, before the seating of {start}" if start
                                       else f"{name}: last printed {d}; no seating rule, so no earlier list is used")
        self._add_members(date, start, inside, seat, out, entry)
        for m in self.cfg.mayors_on(date):
            e = entry(m["name"])
            if m["name"] not in [p["name"] for p in e["people"]]:
                e["people"].append({"name": m["name"], "ward": None, "mayor": True, "date": m["from"],
                                    "configured": True})
        return out

    def _add_members(self, date: str, start: str | None, inside: list, seat: dict, out: dict, entry) -> None:
        """Path N10: each configured, cited member seated from the window's start up to `date` joins the book as the
        holder of its ward (`"configured": True, "member": entry`), replacing the ward's earlier holders, unless a
        full-name list dated on or after `seated` gives that ward to someone else, or a later entry seats someone
        else there. Never carried past the next seating (a re-elected member needs a list or a new entry)."""
        active: dict[int, dict] = {}
        for m in self.members:
            if start is None or not start <= m["seated"] <= date:
                continue
            printed = seat.get(f"Ward {m['ward']}")
            if printed and printed[0] >= m["seated"] and m["name"] not in printed[1]:
                entry(m["name"])["held"].append(f"{m['name']}: Ward {m['ward']} printed for "
                                                f"{', '.join(sorted(printed[1]))} on {printed[0]}")
                active.pop(m["ward"], None)
                continue
            if m["ward"] in active:
                prev = active[m["ward"]]
                entry(prev["name"])["held"].append(f"{prev['name']}: Ward {m['ward']} given to {m['name']} by "
                                                   f"{member_basis(m)}")
            active[m["ward"]] = m
        for m in active.values():
            _replace_holders(out, inside, m, entry)
            e = entry(m["name"])
            if m["name"] not in [p["name"] for p in e["people"]]:
                e["people"].append({"name": m["name"], "ward": m["ward"], "mayor": False, "date": m["seated"],
                                    "configured": True, "member": m})


def _ward_of(inside: list, name: str) -> int | None:
    """The ward last printed for `name` by a list in the window (the latest printing may leave the ward out)."""
    return next((p["ward"] for _, people in reversed(inside) for p in people
                 if p["name"] == name and p["ward"] is not None), None)


def _replace_holders(out: dict, inside: list, m: dict, entry) -> None:
    """A configured member takes their ward from `seated`: each person of the book last printed for that ward
    before then is held with the reason (the replaced-seat rule, as if a full-name list had printed the successor)."""
    for e in list(out.values()):
        keep = []
        for p in e["people"]:
            if p["name"] != m["name"] and not p.get("configured") and p["date"] < m["seated"] \
                    and _ward_of(inside, p["name"]) == m["ward"]:
                e["held"].append(f"{p['name']}: Ward {m['ward']} given to {m['name']} by {member_basis(m)}")
            else:
                keep.append(p)
        e["people"] = keep


def resolve_surnames(cfg, officials: Officials, pm: ParsedCityMinutes, book: dict | None,
                     word_breaks: list | None = None) -> tuple[dict, list]:
    """Attendance printed as surnames only ("PRESENT: BROWN, CHANDLER, ..., PITTS, ...", CivicClerk minutes from
    March 2025 on) -> ({id(person): (full name, is mayor)}, checks).

    A surname is read as a member's full name only when exactly one full name with that surname (any case) is on the
    meeting's roster book (`book`, RosterBook.for_meeting: the full-name attendance lists since the latest seating,
    members not replaced, and the configured, cited mayor), and a ward printed with the surname agrees with it.
    Nothing else in the minutes is evidence: a titled name in the text ("Councilman David Allen moved to Clarksville
    in 1985", "the Pledge was led by Councilman X", "called to order by Mayor Wes Golden") never adds a candidate
    (city-votes/titled-nonmember, city-votes/presiding-guest). Anything else stays as printed, with no official, and
    holds the meeting's attendance (check surnames_resolve), so its roll calls are held too. Never a near spelling
    ("ZAHARIAS"). The check's detail names the lists (or the configured mayor) used, and for a held surname that it
    has no roster entry and why its earlier printings were not used.

    Last step (path N9, W2): an entry printed neither in full nor as one surname that no other step resolved
    ("StaceyStreetman (Ward 10)", "J eff Henley") is read as the one person of the book whose full name or surname
    has its break-free key, when a printed ward agrees; each use is named in the check's detail and appended to
    `word_breaks` as (printed entry, person). Otherwise it stays as before (held)."""
    book = book or {}
    persons = {r["name"]: r for e in book.values() for r in e["people"]}

    def by_break(p):
        if p.line_cut:                                   # never a join across a line end (W2 rule 5): held
            return None
        hit = break_free_match(p.raw_name, [(n, n) for n in sorted(persons)])
        if hit and (p.ward is None or persons[hit]["ward"] is None or persons[hit]["ward"] == p.ward):
            return persons[hit]
        return None

    named = [p for p in pm.present + pm.absent if not NAME_RE.match(clean_name(p.raw_name))]
    people = [p for p in named if SURNAME_RE.match(clean_name(p.raw_name))]
    out, unresolved, basis, uses = {}, [], Counter(), []
    for p in named:
        if any(p is x for x in people):
            continue
        r = by_break(p)                                  # N9 on an entry that is not a surname ("J eff Henley")
        if r:
            out[id(p)] = (r["name"], r["mayor"])
            uses.append(word_break_note(p.raw_name, r["name"]))
            if word_breaks is not None:
                word_breaks.append((p, r["name"]))
    if not people and not uses:
        return {}, []
    for p in people:
        s = clean_name(p.raw_name).lower()
        cands: dict[str, str] = {}               # full name -> the roster entry it is read from
        earlier = book.get(s, {"people": [], "held": []})
        other_ward = []
        for r in earlier["people"]:
            if p.ward is None or r["ward"] is None or r["ward"] == p.ward:
                cands.setdefault(r["name"], member_basis(r["member"]) if r.get("member")
                                 else f"the configured mayor seat from {r['date']}" if r.get("configured")
                                 else f"the attendance of {r['date']}")
            else:
                other_ward.append(f"{r['name']}: Ward {r['ward']}, not Ward {p.ward} as printed")
        if len(cands) == 1:
            name, why = next(iter(cands.items()))
            mayor = any(r["mayor"] for r in earlier["people"] if r["name"] == name)
            out[id(p)] = (name, mayor)
            if why.startswith("the configured member "):        # named per printing: "CLAUNCH: by the configured ..."
                uses.append(f"{clean_name(p.raw_name)}: by {why}")
            else:
                basis[why] += 1
        elif not cands and by_break(p):                 # N9, the last step: "StaceyStreetman (Ward 10)"
            r = by_break(p)
            out[id(p)] = (r["name"], r["mayor"])
            uses.append(word_break_note(p.raw_name, r["name"]))
            if word_breaks is not None:
                word_breaks.append((p, r["name"]))
        elif cands:
            unresolved.append(f"{p.raw_name} ({len(cands)} full names)")
        else:
            unresolved.append(f"{p.raw_name} ({'; '.join(['no roster entry'] + earlier['held'] + other_ward)})")
    detail = "; ".join([f"{n} by {why}" for why, n in sorted(basis.items())] + uses)
    if unresolved:
        detail = (detail + "; " if detail else "") + "not resolved: " + ", ".join(unresolved)
    return out, [_check("surnames_resolve", not unresolved, f"{len(people)} printed as surnames: {detail}")]


def presiding_mayor(cfg, officials: Officials, pm: ParsedCityMinutes, book: dict | None) -> tuple[str | None, list]:
    """The presiding mayor of the call-to-order sentence ("called to order by Mayor Joe Pitts") -> (full name, checks)
    when the name is on the meeting's roster book as the Mayor seat (the configured, cited mayor whose term covers
    the meeting, or a full-name attendance list since the latest seating that prints the name as Mayor) or on this
    meeting's own attendance printed in full with the Mayor title. Otherwise (None, a failed presiding_resolves
    check): the sentence alone never adds a person (city-votes/presiding-guest: a joint session "called to order by
    Mayor Wes Golden", the County Mayor). No check when no presiding mayor is printed (a Mayor Pro Tem presiding is
    on the PRESENT line already)."""
    if not (pm.presiding and pm.presiding_title == cfg.presiding_title):
        return None, []
    name = officials.canonical(pm.presiding)
    own = [p for p in pm.present + pm.absent
           if p.mayor and NAME_RE.match(clean_name(p.raw_name)) and officials.canonical(p.raw_name) == name]
    seat = [r for r in (book or {}).get(name_parts(name)[1].lower(), {"people": []})["people"]
            if r["name"] == name and r["mayor"]]
    if own:
        why = "this meeting's attendance"
    elif seat:
        why = (f"the configured mayor seat from {seat[0]['date']}" if seat[0].get("configured")
               else f"the attendance of {seat[0]['date']}")
    else:
        return None, [_check("presiding_resolves", False,
                             f"{name}: no roster entry for the Mayor seat (no configured mayor and no full-name list "
                             f"since the seating prints them as Mayor): held, not added")]
    return name, [_check("presiding_resolves", True, f"{name} by {why}")]


def _add_minutes(cfg, officials: Officials, meeting: dict, src: dict, pm: ParsedCityMinutes, roll_calls, motions,
                 items, events, wards, problems, unresolved, surname_book: dict | None = None,
                 word_breaks: list | None = None) -> None:
    sha8 = src["sha256"][:8]
    roster: list[tuple[str, str]] = []
    present_ids, absent_ids, part_time = set(), set(), {}     # part_time: official -> Person (late or left)
    att = []
    malformed = []
    word_breaks = [] if word_breaks is None else word_breaks

    def used(where: str, page, printed: str, oid: str) -> str:
        """One break-free (N9) use: listed for the run report (build/city-report.json word_break_matches)."""
        name = officials.by_id[oid]["name"]
        word_breaks.append({"meeting": meeting["id"], "page": page, "where": where, "printed": printed,
                            "official_id": oid, "name": name})
        return word_break_note(printed, name)

    att_breaks: list = []
    by_surname, surname_checks = resolve_surnames(cfg, officials, pm, surname_book, att_breaks)
    presiding, presiding_checks = presiding_mayor(cfg, officials, pm, surname_book)
    for status, people in (("present", pm.present), ("absent", pm.absent)):
        for p in people:
            full = by_surname.get(id(p))
            if full is None and not NAME_RE.match(clean_name(p.raw_name)):   # not a name as printed: no official
                malformed.append(p.raw_name)
                att.append({"official_id": None, "raw_name": p.raw_name, "status": status, "page": p.page})
                continue
            name, mayor = full if full else (p.raw_name, p.mayor)
            oid = officials.add(name, cfg.presiding_title if mayor else cfg.official_title)
            att.append({"official_id": oid, "raw_name": p.raw_name, "status": status, "page": p.page})
            roster.append((oid, officials.by_id[oid]["name"]))
            (present_ids if status == "present" else absent_ids).add(oid)
            if p.part_time:
                part_time[oid] = p
            wards.append({"official_id": oid, "raw_name": p.raw_name, "ward": p.ward, "pro_tem": p.pro_tem,
                          "meeting_id": meeting["id"], "date": meeting["date"], "source_id": src["id"],
                          "page": p.page})
    for p, name in att_breaks:
        used("attendance", p.page, p.raw_name, official_id(officials.canonical(name)))
    presiding_id = None
    if presiding:                       # on the roster book as the Mayor seat, or this meeting's own list (path N3)
        presiding_id = officials.add(presiding, cfg.presiding_title)
        if presiding_id not in present_ids:
            roster.append((presiding_id, officials.by_id[presiding_id]["name"]))
    dup = [n for n, c in Counter(a["official_id"] for a in att if a["official_id"]).items() if c > 1]
    att_checks = [_check("present_listed", bool(pm.present), f"{len(pm.present)} present, {len(pm.absent)} absent"),
                  _check("one_entry_per_official", not dup, ", ".join(dup) or None),
                  _check("names_well_formed", not malformed, ", ".join(malformed) or None)] + surname_checks + \
        presiding_checks
    if att:
        meeting["attendance_status"] = "extracted"
        meeting["attendance"] = att
    meeting["verification"] = _verification(att_checks)
    att_ok = meeting["verification"]["status"] == "verified"
    for msg in pm.problems:
        problems.append({"meeting": meeting["id"], "problem": msg})

    out_of_room = _out_of_room(pm, roster, part_time, cfg.aliases)
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
        votes, seen, breaks = [], Counter(), []
        for v in rc.votes:
            oid, via_break = resolve_with(v.raw_name, roster, cfg.aliases, v.line_cut)
            if oid is None:
                unresolved[v.raw_name] += 1
            else:
                seen[oid] += 1
            if via_break:
                breaks.append(used("vote", rc.page, v.raw_name, oid))
            votes.append({"official_id": oid, "raw_name": v.raw_name, "value": v.value, "raw_value": v.raw_value})
        block_absent = set()
        for a in rc.absent:
            oid, via_break = resolve_with(a, roster, cfg.aliases, a in rc.absent_cut)
            block_absent.add(oid)
            if via_break:
                breaks.append(used("absent", rc.page, a, oid))
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
            _check("names_resolve", not unres, "; ".join(([", ".join(unres)] if unres else []) + breaks) or None),
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
            mover, mover_break = resolve_with(rc.motion["mover"], roster, cfg.aliases)
            sec, sec_break = (resolve_with(rc.motion["seconder"], roster, cfg.aliases) if rc.motion["seconder"]
                              else (None, False))
            mchecks = [
                _check("attendance_verified", att_ok),
                _check("mover_resolves", mover is not None,
                       used("mover", rc.motion["page"], rc.motion["mover"], mover) if mover_break
                       else rc.motion["mover"]),
                _check("seconder_resolves", sec is not None,
                       used("seconder", rc.motion["page"], rc.motion["seconder"], sec) if sec_break
                       else rc.motion["seconder"] or "no seconder printed"),
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
