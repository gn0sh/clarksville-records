"""python -m collector {fetch,build,run,export} [--offline] [--internal] [--allow-shrink] [--out build/site]
python -m collector fin {fetch,build,census}   (finance and contracts: collector/fin_run.py)
python -m collector city {fetch,build,run}     (City Council, Agenda Center: collector/city_run.py)
python -m collector rpc {fetch,build,run}      (Regional Planning Commission: collector/rpc.py)
python -m collector transcripts import <dir>   (meeting video transcripts: collector/transcripts.py)
run: discover -> fetch new (polite), and refetch any manifest minutes whose bytes the store lacks -> parse ->
resolve names -> verify -> shrink guard -> data/facts.json -> finance fetch and
build (fin_run.run_step: data/finance.json, build/report.json `finance`) -> county agendas (county_agenda.run_step:
the agenda page, new agenda PDFs, data/county-agendas/agendas.json) -> Regional Planning Commission (rpc.run_step:
the listing page, new documents, data/localities/cmc-rpc/rpc.json; all or nothing) -> sitegen -> export ->
build/report.json, build/run-log.json. Exit 0 ok, 2 on fetch/parse failures (votes or finance), 3 on a gate failure
(votes gates, or finance parity 'review needed'), 7 (KEPT, a warning) when the shrink guard kept a source document's
meetings as committed, or a correction lowered a document's verified count; everything else is published. The RPC
step has its own codes, used only when everything else is ok: 5 the RPC step failed (blocked by a 403/429, listing
not read, a gate, or a result that would shrink the record), 6 the RPC store is still being filled, a few documents
per run. On 5 and 6 the RPC files are exactly as committed and the site is built from them; the step's own code and
reason are in build/run-log.json `rpc` (under 7 too). Precedence 2 > 3 > 7 > 5/6.
On 2, 3, 5 or 7 it prints the `gh issue create` command it would run (task D1).
Shrink guard (docs/architecture/pipeline-limits-invariant.md "Rule 3: the shrink guard", G1-G4), per source
document and every meeting in it, compared by sha256 against the committed data/facts.json: the same document that
lost a verified roll call or a meeting, or a document missing from the result, keeps its committed records exactly
(exit 7, build/run-log.json `kept_meetings`); a document whose bytes changed is a correction, the new reading wins
(`corrections`). --allow-shrink lets the new result win for every meeting (still listed).
--offline skips discovery and fetching (votes and finance) and uses the store (data/store/, or RECORDS_STORE).
Offline guard (provenance/offline-run-overwrites-facts): an offline run (and `build`) refuses, exit 4, writing
nothing, when minutes PDFs the manifest lists are missing from the store, when no minutes parse, when the result
would drop a meeting data/facts.json has, or when the shrink guard would keep a document. --allow-shrink lets a
deliberate shrink through.
export: build/site/data/ from the committed files (county facts, each council's facts, finance), no parsing.
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import limits
from .config import YEARS
from .discover import DiscoveryError, classify, discover, fetch_index
from .facts import Builder, dumps, load_procedural, write_if_changed
from .meetings import choose
from .fetch import FetchFailed, HostBlocked, HostRefused, PoliteFetcher, ProxyRefused, RobotsDisallowed
from .names import NAMES, Resolver, load_roster
from .store import MANIFEST, Store, fetch_into_store
from .verify import gates

ROOT = Path(__file__).resolve().parent.parent
FACTS = ROOT / "data" / "facts.json"
FINANCE = ROOT / "data" / "finance.json"
BUILD = ROOT / "build"
REPO = "gn0sh/clarksville-records"


def load_seat_rows() -> list[dict] | None:
    """The seat holder rows for the export's seats.csv (none when the locality has no seats file yet)."""
    import yaml
    from sitegen import config
    p = Path(config.SEATS_PATH)
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or []) if p.is_file() else None


def doc_date(e: dict) -> str:
    return e.get("meeting_date") or (classify(e.get("label") or "") or {}).get("meeting_date") or ""


def in_range(e: dict) -> bool:
    d = doc_date(e)
    return e.get("kind", "minutes") == "minutes" and d[:4].isdigit() and int(d[:4]) in YEARS


# ------------------------------------------------------------------ fetch
def cmd_fetch(store: Store, log: dict, fetcher: PoliteFetcher | None = None) -> None:
    f = fetcher or PoliteFetcher()
    try:
        page = fetch_index(f)
        found, skipped = discover(page)
    except (DiscoveryError, HostBlocked, HostRefused, ProxyRefused, RobotsDisallowed, FetchFailed) as e:
        log["failures"].append({"stage": "discover", "error": f"{type(e).__name__}: {e}"})
        log["fetch_log"] = f.log
        return
    log["found"] = len(found)
    log["skipped_links"] = skipped
    for d in found:
        try:
            entry, status = fetch_into_store(f, store, d["url"], {"kind": "minutes", "meeting_date": d["meeting_date"],
                                                                  "label": d["label"]})
            log["fetched"][status] = log["fetched"].get(status, 0) + 1
            if status in ("new", "changed"):
                log["new"].append(d["url"])
        except (HostBlocked, HostRefused, ProxyRefused, RobotsDisallowed, FetchFailed) as e:
            log["failures"].append({"stage": "fetch", "url": d["url"], "error": f"{type(e).__name__}: {e}"})
    refetch_missing(store, log, f, {d["url"] for d in found})
    store.save()
    log["fetch_log"] = f.log


def refetch_missing(store: Store, log: dict, f, listed: set[str]) -> None:
    """Minutes the manifest lists (in range) whose bytes are not in the store and that the index no longer lists (the
    2020-2021 packets came from the M0 index): requested again at the exact URL the manifest recorded, through the same
    polite fetcher. No other URL is tried (spec A4). Same bytes leave the manifest unchanged; new bytes are a new
    version, like any changed document. log['refetched']: {url: status or error}."""
    out = log.setdefault("refetched", {})
    for e in missing_inputs(store):
        if e["url"] in listed:
            continue                                 # discovery just tried it
        try:
            _, status = fetch_into_store(f, store, e["url"], {"kind": "minutes", "meeting_date": e["meeting_date"],
                                                              "label": e["label"]})
            out[e["url"]] = status
            if status in ("new", "changed"):
                log["new"].append(e["url"])
        except (HostBlocked, HostRefused, ProxyRefused, RobotsDisallowed, FetchFailed) as ex:
            out[e["url"]] = f"{type(ex).__name__}: {ex}"
            log["failures"].append({"stage": "refetch", "url": e["url"], "error": f"{type(ex).__name__}: {ex}"})


def finance_fetcher() -> PoliteFetcher:
    """One polite fetcher for the votes and finance fetches of a run (robots cache and per-host clock shared), which
    also hard-denies finance.yml bonfire_hosts."""
    from . import fin_config
    return PoliteFetcher(extra_denied=fin_config.load().bonfire_hosts)


def run_finance(store: Store, log: dict, offline: bool, **kw) -> int:
    from .fin_run import run_step
    return run_step(store, log, offline, **kw)


def run_agendas(log: dict, offline: bool, fetcher: PoliteFetcher | None = None) -> None:
    """County Commission agendas (collector/county_agenda.py): its own manifest and data/county-agendas/agendas.json."""
    from .county_agenda import run_step
    run_step(log, offline, fetcher=fetcher)


RPC_FAILED, RPC_FILLING = 5, 6       # `run` exit codes for the RPC step alone (everything else ok)
# `run` warning exit (shrink guard G2.4): a source document's meetings were kept as committed, or a correction lowered
# a document's verified count; everything else was published. Unused by city_run (0/2/5) and rpc.py's step codes.
KEPT = 7


def run_rpc(log: dict, offline: bool, fetcher: PoliteFetcher | None = None, allow_shrink: bool = False) -> int:
    """Regional Planning Commission (collector/rpc.py run_step): its own manifest, listing and rpc.json, its own exit
    code (0 ok). It never adds to log['failures'] and never raises: a refusal by cmcrpc.com does not fail the county
    run, and leaves every RPC file as committed."""
    from .rpc import run_step
    return run_step(log, offline, fetcher=fetcher, allow_shrink=allow_shrink)


# ------------------------------------------------------------------ build
def cmd_build(store: Store, log: dict, use_ocr: bool = True) -> tuple[dict, dict, Builder]:
    from .minutes import parse_minutes
    roster = load_roster(NAMES)
    b = Builder(Resolver(roster), load_procedural())
    # only the latest version of each URL is read; replaced versions stay in the manifest for citations only
    entries = sorted((e for e in store.current() if in_range(e)), key=lambda e: (doc_date(e), e["url"]))
    log["superseded"] = [{"url": e["url"], "sha256": e["sha256"], "superseded_by": e.get("superseded_by")}
                         for e in store.superseded()]
    seen_sha: set[str] = set()
    parsed_docs = []
    for e in entries:
        if e["sha256"] in seen_sha:
            continue                     # the same bytes listed under two URLs: one document
        seen_sha.add(e["sha256"])
        p = store.path_for(e["sha256"])
        if not store.has_bytes(e["sha256"]):
            log["failures"].append({"stage": "parse", "url": e["url"], "error": "not in the store (run without --offline)"})
            continue
        t0 = time.time()
        try:
            pd = parse_minutes(p, e, use_ocr=use_ocr)
        except Exception as ex:          # one bad document must not stop the run; it is logged and alerted
            log["failures"].append({"stage": "parse", "url": e["url"], "error": f"{type(ex).__name__}: {ex}"})
            continue
        parsed_docs.append(pd)
        log["parsed"] += 1
        rcs = [r for m in pd.meetings for r in m.roll_calls]
        print(f"  parsed {e.get('label') or e['url']}: meetings "
              f"{', '.join(f'{m.meeting_date} ({m.segment.role})' for m in pd.meetings) or 'none'}; {len(rcs)} roll "
              f"calls, {sum(r.status == 'Verified' for r in rcs)} verified ({time.time() - t0:.0f} s)", flush=True)
    if not log["parsed"]:
        log["failures"].append({"stage": "parse", "error": "no minutes documents parsed"})
    chosen, copies, undated = choose(parsed_docs)
    for pm in chosen:
        b.add(pm)
    for pd in parsed_docs:
        b.add_zoning(pd)
    for u in undated:
        b.problems.append({"source": u["source_id"], "problem": f"minutes on pp{u['pages'][0]}-{u['pages'][1]}: "
                                                                f"{u['problem']} ({u['date_how']})"})
    for p in b.problems:
        log["failures"].append({"stage": "assemble", **p})
    facts = b.facts(roster)
    report = {
        **gate_report(facts, b.source_errors, log),
        "consent_roll_calls_not_expanded": sorted(b.consent_unexpanded),
        "documents": documents_report(parsed_docs, b),
        "meeting_copies": copies,
        "consent_reprints": dict(sorted(b.consent_reprints.items())),
        "superseded_sources": log.get("superseded", []),
        "problems": b.problems,
    }
    return facts, report, b


def gate_report(facts: dict, source_errors: set, log: dict) -> dict:
    """The build/report.json fields that depend on the facts as published: the gates (verify.gates), `pass` and the
    held-back lists. cmd_build calls it on the new result, and cmd_run again on the merged facts when the shrink guard
    kept a document (G2.3), so a kept meeting never fails a gate the published file would pass."""
    g = gates(facts, source_errors)
    log["held_back"] = g["held_back"]
    return {
        "generated_for": {"coverage": facts["coverage"], "sources": len(facts["sources"])},
        "gates": g,
        "pass": g["verified_rate_gate"]["pass"] and g["g4"]["pass"],
        "held_back_roll_calls": [
            {"id": r["id"], "meeting_id": r["meeting_id"], "page": r["page"],
             "source_error": r["id"] in source_errors,
             "failed": [c["check"] for c in r["verification"]["checks"] if not c["ok"]]}
            for r in facts["roll_calls"] if r["verification"]["status"] != "verified"],
        "meetings_attendance_unverified": [m["id"] for m in facts["meetings"]
                                           if m["verification"]["status"] != "verified"],
        "motions_held_back": sum(m["verification"]["status"] != "verified" for m in facts["motions"]),
        "meetings_by_year": meetings_by_year(facts),
    }


def merged_source_errors(facts: dict, b) -> set:
    """Source-document-error roll call ids among `facts`: the build's own (b.source_errors) plus a kept committed roll
    call's failed `source_consistent` check (collector/facts.py writes that check for exactly those ids)."""
    ids = {r["id"] for r in facts["roll_calls"]}
    own = set(getattr(b, "source_errors", None) or ()) & ids
    return own | {r["id"] for r in facts["roll_calls"]
                  if any(c.get("check") == "source_consistent" and not c.get("ok")
                         for c in (r.get("verification") or {}).get("checks", []))}


def documents_report(parsed_docs: list, b: Builder) -> list[dict]:
    """Per document: its index label (a hint only), the meetings found in its text and which of them it supplies."""
    used = {(d["source_id"], d["meeting_id"]): d for d in b.doc_summary}
    out = []
    for pd in parsed_docs:
        sid = f"src-{pd.source['sha256'][:12]}"
        label_hint = (classify(pd.source.get("label") or "") or {}).get("meeting_date")
        found = []
        for m in pd.meetings:
            mid = f"{m.meeting_date}-{m.kind}" if m.meeting_date else None
            found.append({"meeting_id": mid, "pages": [m.segment.page, m.segment.end_page], "role": m.segment.role,
                          "boundaries_certain": m.segment.certain, "date_read": m.segment.date_how,
                          "vote_tables": len(m.roll_calls),
                          # a used meeting counts its votes (consent reprints are one vote); an unused copy its tables
                          "roll_calls": used[(sid, mid)]["roll_calls"] if (sid, mid) in used else len(m.roll_calls),
                          "verified": (used[(sid, mid)]["verified"] if (sid, mid) in used else
                                       sum(r.status == "Verified" for r in m.roll_calls)),
                          "used": (sid, mid) in used})
        own = [f["meeting_id"] for f in found if f["role"] == "own"]
        out.append({"source_id": sid, "label": pd.source.get("label"), "label_month": label_hint,
                    "label_matches_text": bool(own and label_hint and own[0] and own[0].startswith(label_hint)),
                    "pages": pd.pages, "image_only_pages": len(pd.image_only_pages),
                    "vote_tables_outside_minutes": pd.tables_outside_minutes, "meetings_found": found})
    return sorted(out, key=lambda d: ((d["meetings_found"] or [{}])[0].get("meeting_id") or "", d["source_id"]))


def meetings_by_year(facts: dict) -> dict:
    """Actual meeting dates covered, per year, with roll-call counts (coverage is these dates, not a range)."""
    out: dict[str, dict] = {}
    by_m: dict[str, list] = {}
    for r in facts["roll_calls"]:
        by_m.setdefault(r["meeting_id"], []).append(r)
    for m in sorted(facts["meetings"], key=lambda m: m["id"]):
        y = out.setdefault(m["date"][:4], {"meetings": [], "roll_calls": 0, "verified": 0})
        rs = by_m.get(m["id"], [])
        y["meetings"].append(m["id"])
        y["roll_calls"] += len(rs)
        y["verified"] += sum(r["verification"]["status"] == "verified" for r in rs)
    for y in out.values():
        y["verified_rate"] = round(y["verified"] / y["roll_calls"], 4) if y["roll_calls"] else None
    return out


def name_candidates(b: Builder, roster: list[dict]) -> dict:
    r = Resolver(roster)
    return {
        "rules": "names.yml merge rules 1-4 (collector/names.py). Suggestions are never applied automatically.",
        "unmatched": [{"raw_name": k, "count": v["count"], "examples": v["examples"], "suggestions": r.suggestions(k)}
                      for k, v in sorted(b.unresolved.items(), key=lambda kv: (-kv[1]["count"], kv[0]))],
        "merges": [{"official_id": o["id"], "name": o["name"], "alias": a["alias"], "reason": a.get("reason"),
                    "example": a.get("example")} for o in roster for a in o["aliases"]],
    }


def issue_command(code: int, log: dict, report: dict | None) -> str:
    title = {2: "Collector run failed", RPC_FAILED: "Collector RPC step failed",
             KEPT: "Collector kept county meetings"}.get(code, "Collector gates failed")
    rpc = log.get("rpc") or {}
    body = {"exit": code, "failures": log["failures"][:20], "rpc": {"exit": rpc.get("exit"), "status": rpc.get("status")},
            "gates": (report or {}).get("gates", {}).get("verified_rate_gate"),
            "g4_flagged": (report or {}).get("gates", {}).get("g4", {}).get("flagged"),
            "finance_build_exit": log.get("fin_build"),          # 3: parity 'review needed' (A5)
            "kept_meetings": log.get("kept_meetings"), "corrections": log.get("corrections"),
            "limits": log.get("limits")}
    return (f"gh issue create --repo {REPO} --title {shlex.quote(title)} "
            f"--body {shlex.quote(json.dumps(body, indent=1))}")


# ------------------------------------------------------------------ offline guard
REFUSED = 4


def missing_inputs(store: Store) -> list[dict]:
    """Minutes entries the build would read (current, in range) whose bytes are not in the store."""
    return [e for e in store.current() if in_range(e) and not store.has_bytes(e["sha256"])]


def shrink_reason(facts: dict, log: dict, facts_path: Path) -> str | None:
    """Why an offline result must not replace facts_path, or None. Refused: no minutes parsed, a document not in the
    store, a meeting the current file has that the new result lacks (provenance/offline-run-overwrites-facts), or a
    source document the shrink guard would keep (G2.7: the same sha256 rule as online, so a correction, a document
    whose bytes changed, is not refused)."""
    gone = [f for f in log["failures"] if f.get("stage") == "parse" and "not in the store" in f.get("error", "")]
    if gone:
        return f"{len(gone)} minutes documents are not in the store, e.g. {gone[0].get('url')}"
    if not log.get("parsed") or not facts.get("meetings"):
        return "no minutes documents parsed"
    if not Path(facts_path).is_file():
        return None
    old = json.loads(Path(facts_path).read_text(encoding="utf-8"))
    dropped = sorted({m["id"] for m in old.get("meetings", [])} - {m["id"] for m in facts["meetings"]})
    if dropped:
        return (f"the result has {len(facts['meetings'])} meetings and would drop {len(dropped)} of the "
                f"{len(old.get('meetings', []))} in {Path(facts_path).name}, e.g. {', '.join(dropped[:3])}. "
                f"A parser change that renames meeting ids also causes this; pass --allow-shrink to override")
    kept = shrink_guard(facts, old, Path(facts_path).name, superseded_shas(log))["kept"]
    if kept:
        return lost_message(kept, facts_path)
    return None


# ------------------------------------------------------------------ the shrink guard (limits invariant rule 3)
def superseded_shas(log: dict) -> set:
    """sha256 of every document version the store marks replaced at its url (cmd_build: log['superseded'])."""
    return {e["sha256"] for e in log.get("superseded") or [] if e.get("sha256")}


class GuardUnitError(RuntimeError):
    """The guard's unit (a source document and every meeting in it) does not hold: a bug, never a run result."""


def _verified(rc: dict) -> bool:
    v = rc.get("verification")
    return (v.get("status") if isinstance(v, dict) else v) == "verified"


def check_unit(facts: dict, which: str) -> None:
    """G1 assertion: every meeting has a source_id, and every roll call, motion and item event names a meeting of the
    file and that meeting's source_id. The guard keeps whole documents by these two keys, so a file in which they
    disagree cannot be guarded: raise, and re-plan the guard before merging the change that broke it."""
    src = {}
    bad = []
    for m in facts.get("meetings", []):
        src[m.get("id")] = m.get("source_id")
        if not m.get("source_id"):
            bad.append(f"meeting {m.get('id')} has no source_id")
    for key in ("roll_calls", "motions", "item_events"):
        for r in facts.get(key, []):
            mid = r.get("meeting_id")
            if mid not in src:
                bad.append(f"{key} {r.get('id')} names meeting {mid}, which is not in the file")
            elif r.get("source_id") != src[mid]:
                bad.append(f"{key} {r.get('id')} names source {r.get('source_id')}, its meeting {mid} has {src[mid]}")
    if bad:
        raise GuardUnitError(
            f"shrink guard: the unit (one source document and every meeting in it) does not hold in {which}: "
            f"{len(bad)} records, e.g. {'; '.join(bad[:3])}. Re-plan the guard before merging "
            f"(docs/architecture/pipeline-limits-invariant.md, 'Rule 3: the shrink guard', G1)")


def vote_content(facts: dict, meeting_ids) -> list:
    """The votes of these meetings without ids, sources or pages (which a new sha256 renames): per roll call its item,
    outcome, stated tally and each vote's official, name and value, sorted. Equal lists: the correction kept every vote."""
    ms = set(meeting_ids)
    return sorted(json.dumps([r.get("meeting_id"), r.get("item_id"), r.get("outcome"), r.get("stated_tally"),
                              sorted([v.get("official_id") or "", v.get("raw_name") or "", v.get("value") or ""]
                                     for v in r.get("votes") or [])], sort_keys=True)
                  for r in facts.get("roll_calls", []) if r.get("meeting_id") in ms)


def shrink_guard(new: dict, old: dict, name: str = "facts.json", superseded=()) -> dict:
    """G1 (docs/architecture/pipeline-limits-invariant.md, "Rule 3: the shrink guard"): compare the new result with the
    committed facts `old` per source document S (and every meeting Ms it carries), by sha256.
    (a) S's bytes are in the result: a roll call of S verified in `old` and not verified (or absent) in `new`, or a
        meeting of Ms gone, keeps S (a limit trip, a lost OCR reading, a parser change).
    (b) S's bytes are not, but every meeting of Ms is, under another source, AND S was replaced: a new source carrying
        Ms has S's url, or the store marks S's sha256 superseded (`superseded`, from store.superseded()). That is a
        correction; the new reading wins (pipeline/correction-not-bytes-changed: a meeting that merely moved to
        another document, meetings.choose, while S is unchanged is not one, and keeps S).
    (c) S's bytes are not and a meeting of Ms is absent too (not in the store, a fetch or parse failure, a timeout):
        transient, keeps S.
    Gains are never guarded. Returns {'kept': [{source_id, meeting_ids, ids (lost verified roll calls), reason,
    closure: {meeting_ids, source_ids}, withheld_new}], 'corrections': [{meeting_ids, source_id, new_source_ids,
    sha256, new_sha256, verified: [old, new], votes_changed}]}. `closure` is every meeting and source keep_documents
    takes back with S; `withheld_new` the meetings in it that only the new result has (not published while S is
    kept: pipeline/keep-closure-hides-new-meetings)."""
    check_unit(new, "the new result")
    check_unit(old, name)
    new_sha = {s.get("sha256") for s in new.get("sources", []) if s.get("sha256")}
    new_ids = {s["id"] for s in new.get("sources", [])}
    sha_of_new = {s["id"]: s.get("sha256") or s["id"] for s in new.get("sources", [])}
    old_sha = {s["id"]: s.get("sha256") for s in old.get("sources", [])}
    old_url = {s["id"]: s.get("url") for s in old.get("sources", [])}
    url_of_new = {s["id"]: s.get("url") for s in new.get("sources", [])}
    superseded = set(superseded or ())
    now_src = {m["id"]: m["source_id"] for m in new.get("meetings", [])}
    now_verified = {r["id"] for r in new.get("roll_calls", []) if _verified(r)}
    units: dict[str, list] = {}
    for m in old.get("meetings", []):
        units.setdefault(m["source_id"], []).append(m["id"])
    verified: dict[str, list] = {}
    for r in old.get("roll_calls", []):
        if _verified(r):
            verified.setdefault(r["source_id"], []).append(r["id"])
    kept, corrections = [], []
    for sid in sorted(units):
        ms, was, h = sorted(units[sid]), sorted(verified.get(sid, [])), old_sha.get(sid)
        h8 = (h or sid.removeprefix("src-"))[:8]
        gone = [m for m in ms if m not in now_src]
        if (h in new_sha) if h else (sid in new_ids):                                          # (a) same bytes
            lost = [i for i in was if i not in now_verified]
            why = []
            if lost:
                why.append(f"{len(lost)} roll calls verified in {name} are no longer verified")
            if gone:
                why.append(f"meetings gone from the result: {', '.join(gone)} (a parser change that renames ids "
                           f"needs --allow-shrink)")
            if why:
                kept.append({"source_id": sid, "meeting_ids": ms, "ids": lost,
                             "reason": f"same document (sha256 {h8}): " + "; ".join(why)})
        elif not gone:
            to = sorted({now_src[m] for m in ms})
            replaced = (bool(h) and h in superseded) or (
                bool(old_url.get(sid)) and any(url_of_new.get(t) == old_url[sid] for t in to))
            if replaced:                                                                        # (b) correction
                n_new = sum(1 for r in new.get("roll_calls", []) if r.get("meeting_id") in ms and _verified(r))
                corrections.append({"meeting_ids": ms, "source_id": sid, "new_source_ids": to, "sha256": h,
                                    "new_sha256": [sha_of_new.get(t, t) for t in to], "verified": [len(was), n_new],
                                    "votes_changed": vote_content(old, ms) != vote_content(new, ms)})
            else:                                                       # moved to another document, S not replaced
                lost = [i for i in was if i not in now_verified]
                kept.append({"source_id": sid, "meeting_ids": ms, "ids": lost,
                             "reason": f"document sha256 {h8} not in the result and not replaced at its url (the "
                                       f"meetings are now read from {', '.join(to)}, a document posted at another "
                                       f"url): not a correction"})
        else:                                                                                   # (c) missing
            kept.append({"source_id": sid, "meeting_ids": ms, "ids": was,
                         "reason": f"document sha256 {h8} not in the result (not in the store, or a fetch or parse "
                                   f"failure) and meetings absent: {', '.join(gone)}"})
    had = {m["id"] for m in old.get("meetings", [])}
    for k in kept:
        cm, cs = keep_closure(new, old, [k])
        k["closure"] = {"meeting_ids": sorted(cm), "source_ids": sorted(cs)}
        k["withheld_new"] = sorted(cm - had)
    return {"kept": kept, "corrections": corrections}


def keep_closure(new: dict, old: dict, kept: list[dict]) -> tuple[set, set]:
    """The meetings and sources keep_documents takes back as committed: the kept documents and meetings, closed over
    both files (a kept meeting's source in either file, that source's other meetings, ...)."""
    ms = {m for k in kept for m in k["meeting_ids"]}
    sids = {k["source_id"] for k in kept}
    pairs = [(m["id"], m["source_id"]) for f in (new, old) for m in f.get("meetings", [])]
    grew = True
    while grew:
        grew = False
        for mid, sid in pairs:
            if (mid in ms) != (sid in sids):
                ms.add(mid)
                sids.add(sid)
                grew = True
    return ms, sids


def keep_documents(new: dict, old: dict, kept: list[dict]) -> dict:
    """G2.1: `new` with every kept document's records replaced by the committed ones, byte for byte. A record is the
    document's when its meeting is one of the kept meetings or its source is the kept source or a new source carrying
    one of them (closed over both files, so no meeting is ever shown twice). Committed items the kept records name are
    added back when `new` lacks them; officials come from `new`. Lists are sorted as Builder.facts sorts them, so a
    document kept two days running writes the same file."""
    ms, sids = keep_closure(new, old, kept)

    def mine(r: dict, key: str = "meeting_id") -> bool:
        return r.get(key) in ms or r.get("source_id") in sids
    out = dict(new)
    for k, key in (("meetings", "id"), ("roll_calls", "meeting_id"), ("motions", "meeting_id"),
                   ("item_events", "meeting_id")):
        out[k] = sorted([r for r in new.get(k, []) if not mine(r, key)] + [r for r in old.get(k, []) if mine(r, key)],
                        key=lambda x: x["id"])
    out["sources"] = sorted([s for s in new.get("sources", []) if s["id"] not in sids]
                            + [s for s in old.get("sources", []) if s["id"] in sids], key=lambda x: x["id"])
    have = {i["id"] for i in new.get("items", [])}
    named = {r.get("item_id") for k in ("roll_calls", "motions", "item_events") for r in old.get(k, []) if mine(r)}
    out["items"] = sorted(list(new.get("items", [])) + [i for i in old.get("items", [])
                                                         if i["id"] in named and i["id"] not in have],
                          key=lambda x: x["id"])
    dates = [m["date"] for m in out["meetings"] if m.get("date")]
    if dates and isinstance(new.get("coverage"), dict):       # the published meetings' range, kept ones included
        out["coverage"] = {**new["coverage"], "from": min(dates), "to": max(dates)}
    return out


def lost_message(kept: list[dict], facts_path: Path) -> str:
    """One line for every kept document (the offline refusal and the online issue)."""
    docs = "; ".join(kept_line(k) for k in kept[:10]) + (" ..." if len(kept) > 10 else "")
    return (f"{len(kept)} source documents in {Path(facts_path).name} would lose verified roll calls or meetings: "
            f"{docs} (a limit trip, a lost OCR reading, a missing document or a parser change); pass --allow-shrink "
            f"to accept it")


def kept_line(k: dict) -> str:
    ids = k.get("ids") or []
    withheld = k.get("withheld_new") or []
    return (f"{k['source_id']} ({', '.join(k['meeting_ids'])}): {k['reason']}"
            + (f": {', '.join(ids[:20])}{' ...' if len(ids) > 20 else ''}" if ids else "")
            + (f"; new meetings withheld with it: {', '.join(withheld)}" if withheld else ""))


def correction_line(c: dict) -> str:
    """G1(b): `correction: <meeting ids> source <old8> -> <new8>, verified <n_old> -> <n_new>`."""
    old8 = (c.get("sha256") or c["source_id"].removeprefix("src-"))[:8]
    votes = "; votes changed" if c.get("votes_changed") else ""
    new8 = "+".join((h or "")[:8] or t.removeprefix("src-")[:8] for h, t in zip(c["new_sha256"], c["new_source_ids"]))
    return (f"correction: {', '.join(c['meeting_ids'])} source {old8} -> {new8}, "
            f"verified {c['verified'][0]} -> {c['verified'][1]}{votes}")


def refuse(why: str, since: int = 0) -> int:
    print(limits.summary("collector", since), flush=True)     # a limit trip may be why the result shrank
    print(f"collector: REFUSED (offline run): {why}. {FACTS.name} and the build were left unchanged. Restore the "
          "store (data/store/ or RECORDS_STORE), run without --offline, or pass --allow-shrink if the smaller result "
          "is meant.", file=sys.stderr, flush=True)
    return REFUSED


def cmd_export(args) -> int:
    """build/site/data/ from the committed files only: the county facts, each council's, finance (no parsing)."""
    from .export import export_site
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    out = Path(args.out)
    written = export_site(facts, out, internal=args.internal, seats=load_seat_rows(), finance_path=FINANCE)
    try:
        from sitegen.build import write_publish_manifest
    except ImportError:
        write_publish_manifest = None
    if write_publish_manifest is not None:
        write_publish_manifest(out)
    print(f"collector export: {len(written)} files, {sum(p.stat().st_size for p in written):,} bytes, to {out}/data")
    return 0


def cmd_run(args) -> int:
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log = {"started_at": started, "offline": args.offline, "found": None, "new": [], "fetched": {}, "failures": [],
           "parsed": 0, "held_back": None}
    store = Store(MANIFEST)
    allow = getattr(args, "allow_shrink", False)
    since = limits.mark()                       # the county step's own trips (limits invariant rule 3)
    if args.offline and not allow:
        missing = missing_inputs(store)
        if missing:
            return refuse(f"{len(missing)} minutes PDFs listed in the manifest are not in the store "
                          f"({store.root}), e.g. {missing[0]['url']}", since)
    fetcher = None
    if not args.offline:
        fetcher = finance_fetcher()
        print("collector: discover and fetch (10 s between requests per host)", flush=True)
        cmd_fetch(store, log, fetcher=fetcher)
    print("collector: parse, verify, assemble", flush=True)
    facts, report, b = cmd_build(store, log, use_ocr=not args.no_ocr)
    if args.offline and not allow:
        why = shrink_reason(facts, log, FACTS)
        if why:
            return refuse(why, since)
    # the shrink guard, online and offline (docs/architecture/pipeline-limits-invariant.md "Rule 3", G1-G3): per
    # source document, by sha256. A kept document's records are the committed ones; everything else is published,
    # and the gates run on what is published. --allow-shrink lets the new result win for every meeting (still listed).
    old = json.loads(FACTS.read_text(encoding="utf-8")) if FACTS.is_file() else None
    guard = (shrink_guard(facts, old, FACTS.name, superseded_shas(log)) if old is not None
             else {"kept": [], "corrections": []})
    kept = [] if allow else guard["kept"]
    log["kept_meetings"] = kept
    log["corrections"] = guard["corrections"]
    if allow and guard["kept"]:
        log["allowed_shrink"] = guard["kept"]
    if kept:
        facts = keep_documents(facts, old, kept)
        report.update(gate_report(facts, merged_source_errors(facts, b), log))      # G2.3
    for c in guard["corrections"]:
        print(f"collector: {correction_line(c)}", flush=True)
    county_trips = limits.tripped(since)       # the county build; the agendas step is added below
    changed = write_if_changed(FACTS, dumps(facts))
    BUILD.mkdir(parents=True, exist_ok=True)
    write_if_changed(BUILD / "report.json", dumps(report))
    write_if_changed(BUILD / "name-candidates.json", dumps(name_candidates(b, load_roster(NAMES))))
    fin_code = run_finance(store, log, args.offline, fetcher=fetcher, finance_path=FINANCE,
                           report_path=BUILD / "report.json")
    agendas_since = limits.mark()
    run_agendas(log, args.offline, fetcher=fetcher)
    county_trips += limits.tripped(agendas_since)
    rpc_code = run_rpc(log, args.offline, fetcher=fetcher,      # before the site build, which reads rpc.json
                       allow_shrink=allow)
    site = BUILD / "site"
    try:
        from sitegen.build import build as site_build, write_publish_manifest
    except ImportError:
        print("collector: sitegen is not installed in this checkout; skipping the site step", flush=True)
        site_build = None
    from .export import export_site
    log["warnings"] = []
    if site_build:
        res = site_build(FACTS, site, internal=args.internal, report_path=BUILD / "report.json")
        log["warnings"] = list((res or {}).get("warnings") or [])   # e.g. seats.yml older than the facts (M1)
    export_site(facts, site, internal=args.internal, seats=load_seat_rows(), finance_path=FINANCE)
    if site_build:
        write_publish_manifest(site)
    log["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log["facts_changed"] = changed
    log["limits"] = county_trips
    (BUILD / "run-log.json").write_text(dumps(log))
    g = report["gates"]
    print(f"collector: {log['parsed']} documents parsed, {g['roll_calls']} roll calls, {g['verified']} verified "
          f"({100 * g['verified_rate']:.1f}%), {g['held_back']} held back "
          f"({g['held_back_source_error']} by source errors); G4 {g['g4']['status']} "
          f"(uniform share {g['g4']['uniform_share']}); "
          f"failures {len(log['failures'])}", flush=True)
    print(limits.render("collector", county_trips), flush=True)
    code = 2 if log["failures"] else (0 if report["pass"] and fin_code == 0 else 3)
    for k in kept:
        print(f"collector: KEPT {kept_line(k)}", file=sys.stderr, flush=True)
    for k in log.get("allowed_shrink", []):
        print(f"collector: ALLOWED (--allow-shrink) {kept_line(k)}", file=sys.stderr, flush=True)
    lowered = [] if allow else [c for c in guard["corrections"]
                                if c["verified"][1] < c["verified"][0] or c.get("votes_changed")]
    if code == 0 and (kept or lowered):          # precedence 2 > 3 > 7 > 5/6; the RPC outcome is in run-log `rpc`
        code = KEPT
    if code == 0 and rpc_code:
        from .rpc import STEP_FILLING
        code = RPC_FILLING if rpc_code == STEP_FILLING else RPC_FAILED
    if code == RPC_FILLING:
        print("collector: the RPC store is still being filled; the RPC files are unchanged", flush=True)
    elif code:
        for fl in log["failures"][:10]:
            print("  failure:", json.dumps(fl)[:300])
        print("collector: would open an internal issue (D1 wires this):")
        print("  " + issue_command(code, log, report))
    return code


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["city"]:
        from .city_run import main as city_main
        return city_main(argv[1:])
    if argv[:1] == ["rpc"]:
        from .rpc import main as rpc_main
        return rpc_main(argv[1:])
    if argv[:1] == ["transcripts"]:
        from .transcripts import main as tx_main
        return tx_main(argv[1:])
    if argv[:1] == ["fin"]:
        from .fin_run import main as fin_main
        return fin_main(argv[1:])
    ap = argparse.ArgumentParser(prog="python -m collector")
    ap.add_argument("command", choices=["run", "fetch", "build", "export"])
    ap.add_argument("--offline", action="store_true", help="skip discovery and fetching; use the store")
    ap.add_argument("--internal", action="store_true", help="build the internal review page too")
    ap.add_argument("--no-ocr", action="store_true", help="text layer only (no tesseract second reading)")
    ap.add_argument("--allow-shrink", action="store_true",
                    help="let a result with fewer meetings or verified roll calls replace data/facts.json, online and "
                         "offline (the shrink guard keeps no document; offline: missing store files too); RPC: "
                         "unconfirmed motions too")
    ap.add_argument("--out", default=str(BUILD / "site"), help="export: the site folder (default build/site)")
    args = ap.parse_args(argv)
    if args.command == "export":
        return cmd_export(args)
    if args.command == "fetch":
        log = {"found": None, "new": [], "fetched": {}, "failures": []}
        store = Store(MANIFEST)
        cmd_fetch(store, log)
        print(json.dumps({k: v for k, v in log.items() if k != "fetch_log"}, indent=1))
        return 2 if log["failures"] else 0
    if args.command == "build":
        args.offline = True
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
