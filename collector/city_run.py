"""City of Clarksville City Council from the Agenda Center (M4, slice 1): fetch and build.

python -m collector city fetch [--agendas] [--limit N] [--source S]   listings + minutes PDFs (+ agenda PDFs)
python -m collector city build                            read the stored minutes -> data/localities/<loc>/facts.json
python -m collector city run [--agendas]                  fetch then build
  --allow-drop ID[,ID]   let the named kept rows or meetings go (a deliberate removal at the source); never all

Two listings (M4 slice 3): the Agenda Center (2016 to January 2024, one GET per year) and CivicClerk (2024 on, the
API's events pages; collector/civicclerk.py, ADR 0003). The build joins them with civicclerk.merge_sources: one
meeting per date and kind, each naming its listing source.

Files (per locality, so the county's data/manifest.json and data/facts.json are never touched):
- data/localities/<loc>/listing.json   every listed meeting as printed (committed; a build reads it offline)
- data/localities/<loc>/civicclerk-listing.json   the same for the CivicClerk events (committed)
- data/localities/<loc>/manifest.json  one entry per fetched file (committed), bytes in the gitignored data/store
- data/localities/<loc>/facts.json     the facts (schema/facts.schema.json shape, city meeting kinds)
- data/localities/<loc>/wards.json     each member's ward as printed in each meeting's attendance, with its source
- build/city-report.json               counts, problems, the fetch log

Exit codes (the workflow's Collect step fails the run, and so opens the issue, on any non-zero code; spec AC4.4):
0 ok (a single file that is skipped, e.g. a .docx behind a PDF link, is logged and stays 0); 2 a listing could not be
read, or the shrink guard held a result back; 3 the G4 skew gate flagged an official (build/city-report.json
build.gates; the AC-P1 verified rate is reported there but sets no code); 5 a host or policy refused us at any stage
(HostBlocked 403/429, HostRefused, ProxyRefused, RobotsDisallowed: alerting/city-fetch-failures-exit-0). A refusal is
never retried and never worked around: the code only reports it. 7 (KEPT, a warning; precedence 5 > 2 > 3 > 7 > 0):
the shrink guard kept committed city rows or meetings; the workflow publishes everything and opens the city
meetings-kept issue (docs/adr/0006-daily-refresh-data-guards.md, I1 and I2).

Shrink guard (ADR 0006; the county's rule 3, docs/architecture/pipeline-limits-invariant.md, at the city's units): a
listing read without an error but missing rows the committed listing has (an empty page, a 200 with no heading and no
rows, an events page of `{"value": []}`) keeps the committed rows (`kept_listing_rows`, exit 7), except a row with no
minutes dated on or after the run's UTC day (a cancelled or rescheduled event): it is dropped and listed under
`dropped_unminuted`, no code. The build is then judged by the county's shrink guard (collector/shrink_guard.py,
guard_facts): each committed meeting read from its minutes that lost verified roll calls, is gone, or whose minutes
are missing from the run is kept exactly as committed (records, sources, agenda source, wards; exit 7), and so is
a committed agenda-only meeting the build lacks while its row is still listed (its agenda not in the store), and the
rest is published; a replaced file is a correction (7 only when its verified count fell or its votes changed).
The guard's findings are under `guard` in build/city-report.json; it is never a `failures` row.
--allow-drop ID[,ID] (ADR 0006 I4: a deliberate drop names its ids) lets the named ones go: a meeting id (or a
listing row key, as the kept entries print them); naming a meeting id also lets its listing row go. An id that
matches nothing is refused: exit 2, and the listings, facts.json and wards.json are left as they were. Each drop is
listed under `allowed_drop`. The workflow never passes it: the manual path is a local run, then a PR.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import civicclerk, limits
from .agenda_center import AgendaCenterConfig, ListingError, discover, load_config
from .fetch import FetchFailed, HostBlocked, HostRefused, PoliteFetcher, ProxyRefused, RobotsDisallowed
from .shrink_guard import keep_closure, keep_documents, shrink_guard
from .store import Store, fetch_into_store, store_dir

ROOT = Path(__file__).resolve().parent.parent
STOP = (HostBlocked, HostRefused, ProxyRefused, RobotsDisallowed)   # the host said no (or policy): stop, never retry
LISTING_FAILED = 2
GATE_FAILED = 3        # G4 flagged an official (spec G4: release blocked), as the county's gate failure code
BLOCKED = 5            # its own code, so the alert says "refused", not "failed" (4 is the county run's offline refusal)
KEPT = 7               # a warning: the shrink guard kept committed rows or meetings (the county's KEPT, ADR 0006)


def failure(stage: str, e: Exception, **extra) -> dict:
    """One log['failures'] row. `refused` marks a STOP error: exit_code turns any of them into BLOCKED."""
    row = {"stage": stage, **extra, "error": f"{type(e).__name__}: {e}"}
    if isinstance(e, STOP):
        row["refused"] = True
    return row


def exit_code(log: dict) -> int:
    """BLOCKED when any host or policy refused us (at the listing or at a file), else LISTING_FAILED when a listing
    could not be read, else 0. A lone FetchFailed on one file stays 0: it is logged and that file is skipped. The
    gate (3) and the guard's KEPT (7) are applied after the build, in that order (main)."""
    if any(f.get("refused") for f in log["failures"]):
        return BLOCKED
    return LISTING_FAILED if any(f["stage"] == "listing" for f in log["failures"]) else 0


def kept_anything(log: dict) -> bool:
    """Whether the shrink guard kept committed rows or meetings, or a correction lowered a verified count (KEPT)."""
    g = log.get("guard") or {}
    return bool(g.get("kept_listing_rows") or g.get("kept_meetings") or g.get("lowered"))


def _row_key(r: dict, key: str):
    return r.get(key) or (r.get("date"), r.get("title"), r.get("minutes_url"))


def _row_order(r: dict, key: str) -> tuple:
    v = _row_key(r, key)
    return (r.get("date") or "", (0, v, "") if isinstance(v, int) else (1, 0, str(v)))


def today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def guard_listing(rows: list[dict], previous: list[dict] | None, key: str, name: str, log: dict,
                  allow_drop: set | None = None, today: str | None = None, meetings: dict | None = None) -> list[dict]:
    """The listing to write (ADR 0006 fix 1): `rows` as read, plus every committed row (`previous`) the read lacks,
    kept as committed and listed under guard.kept_listing_rows (exit 7), except a row with no minutes dated on or after
    `today` (UTC): a cancelled or moved future event, dropped and listed under guard.dropped_unminuted (no code). A row
    is one meeting by `key` (agenda_id, event_id). Gains are never guarded; a row named in `allow_drop` goes and is
    listed under guard.allowed_drop: by its key, or by the id of the committed meeting with its date and minutes_url
    (`meetings`, committed_meetings), never by date and kind alone (shrink/city-allow-drop-row-match)."""
    have = {_row_key(r, key) for r in rows}
    gone = [r for r in previous or [] if _row_key(r, key) not in have]
    if not gone:
        return rows
    g = log.setdefault("guard", {})
    day = today or today_utc()
    future = [r for r in gone if not r.get("minutes_url") and (r.get("date") or "") >= day]
    if future:
        g.setdefault("dropped_unminuted", []).append({"listing": name,
                                                       "dropped": [_print(r, key, meetings) for r in future]})
    dropped = [r for r in gone if r not in future]
    if not dropped:
        return rows
    def names(r: dict) -> list:
        ids = (meetings or {}).get((r.get("date"), r.get("minutes_url"))) if r.get("minutes_url") else None
        return [_print(r, key)["key"], *(ids or [])]
    named = [r for r in dropped if allowed(log, allow_drop, *names(r))]
    if named:
        g.setdefault("allowed_drop", []).append({"listing": name, "dropped": [_print(r, key, meetings) for r in named]})
        print(f"collector city: ALLOWED (--allow-drop) {name}: {', '.join(_print(r, key)['key'] for r in named)}",
              file=sys.stderr, flush=True)
    dropped = [r for r in dropped if r not in named]
    if not dropped:
        return rows
    ids = [_print(r, key, meetings) for r in dropped]
    g.setdefault("kept_listing_rows", []).append({"listing": name, "kept": ids})
    print(f"collector city: KEPT {name}: the listing as read has {len(rows)} rows and lacks {len(dropped)} of the "
          f"{len(previous)} committed rows, e.g. {', '.join(i['key'] for i in ids[:5])}; kept as committed",
          file=sys.stderr, flush=True)
    return sorted(rows + dropped, key=lambda r: _row_order(r, key))


def allowed(log: dict, allow_drop: set | None, *ids) -> bool:
    """Whether --allow-drop names any of `ids`; the names it matched are remembered (an unmatched one is refused)."""
    hit = set(allow_drop or ()) & {str(i) for i in ids if i}
    log.setdefault("_allow_matched", set()).update(hit)
    return bool(hit)


def committed_meetings(facts_path: Path) -> dict:
    """(date, minutes_url) -> the committed meeting ids with those minutes (shrink/city-allow-drop-row-match): the only
    way a meeting id names a listing row, so naming 2026-07-09-special never drops a vanished -2 row of that day."""
    if not facts_path.exists():
        return {}
    out: dict = {}
    for m in json.loads(facts_path.read_text(encoding="utf-8")).get("meetings", []):
        if m.get("minutes_url"):
            out.setdefault((m.get("date"), m["minutes_url"]), []).append(m["id"])
    return out


def _print(r: dict, key: str, meetings: dict | None = None) -> dict:
    """A guarded row as the kept entries print it: its key (what --allow-drop takes for a row) and the committed
    meeting carrying its minutes_url (committed_meetings; that id names the row too), else None."""
    ids = (meetings or {}).get((r.get("date"), r.get("minutes_url"))) if r.get("minutes_url") else None
    return {"key": str(_row_key(r, key)), "meeting": ", ".join(ids) if ids else None, "date": r.get("date"),
            "title": r.get("title"), "minutes_url": r.get("minutes_url")}


# ------------------------------------------------------------------ the facts guard (ADR 0006 fix 2)
def minutes_units(old: dict) -> dict:
    """The committed facts the guard compares (ADR 0006 fix 2): only meetings whose source is a minutes source (a
    meeting read from its minutes), with their records.
    guarded_units adds the agenda-only meetings a build lost (shrink/city-agenda-only-meeting-dropped)."""
    kind = {s["id"]: s.get("kind") for s in old.get("sources", [])}
    ms = {m["id"] for m in old.get("meetings", []) if kind.get(m.get("source_id")) == "minutes"}
    return {**old, "meetings": [m for m in old.get("meetings", []) if m["id"] in ms],
            **{k: [r for r in old.get(k, []) if r.get("meeting_id") in ms] for k in ("roll_calls", "motions",
                                                                                     "item_events")}}


def guarded_units(old: dict, new: dict, listed: set | None = None, kind_of=None) -> dict:
    """The committed facts the guard compares: minutes_units, plus every committed meeting NOT read from its minutes
    (agenda-only: no minutes posted, or its minutes are another meeting's) that the new build lacks while its listing
    row is still listed (shrink/city-agenda-only-meeting-dropped). The listing guard keeps such a row, but the build
    can only make a meeting from a stored file: with an empty store (a cold cache, a run without --agendas, a fetch
    failure) the meeting would vanish though its row is kept. Kept by the same shrink_guard (its (a) or (c): exit 7).
    `listed` is the (date, kind) of every listing row the build read, `kind_of` the config's title -> kind (the
    committed meeting's kind is re-read from its title, as the rows' is); None: every such meeting is still listed
    (fail closed). A meeting whose row the listing guard let go (a cancelled future event, --allow-drop) drops."""
    units = minutes_units(old)
    have = {m["id"] for m in units["meetings"]}
    now = {m["id"] for m in new.get("meetings", [])}

    def still_listed(m: dict) -> bool:
        if listed is None:
            return True
        return (m.get("date"), kind_of(m.get("title") or "") if kind_of else m.get("kind")) in listed
    extra = [m for m in old.get("meetings", []) if m["id"] not in have and m["id"] not in now and still_listed(m)]
    return {**units, "meetings": units["meetings"] + extra}


def unread_meetings(old: dict, new: dict) -> set:
    """The committed meetings whose minutes were read and whose minutes the new build did not read (minutes_status
    other than read: not fetched, parse failed, a scan, ...). Their committed minutes are never replaced by a
    correction (shrink/city-correction-on-unread-file, ADR 0006 I1): the guard keeps them until the new file reads or
    --allow-drop names them. A meeting gone from the build is the guard's (c), not listed here."""
    was = {m["id"] for m in old.get("meetings", []) if m.get("minutes_status") == "read"}
    return {m["id"] for m in new.get("meetings", []) if m["id"] in was and m.get("minutes_status") != "read"}


def city_superseded(store: Store, old: dict, new: dict) -> set:
    """The sha256 of every committed document replaced (shrink_guard (b), a correction): the store's superseded
    versions, plus the committed minutes of any meeting whose listing row now names a different minutes_url (the
    listing replaced the file), on both paths only when the new file was read: the sha of a committed meeting whose
    new minutes are unread (unread_meetings) is left out, so the guard keeps that meeting (exit 7)."""
    shas = {e["sha256"] for e in store.superseded() if e.get("sha256")}
    sha = {s["id"]: s.get("sha256") for s in old.get("sources", [])}
    now = {m["id"]: m for m in new.get("meetings", [])}
    unread = unread_meetings(old, new)
    held = set()
    for m in old.get("meetings", []):
        n, h = now.get(m["id"]), sha.get(m.get("source_id"))
        if not n or not h:
            continue
        if m["id"] in unread:
            held.add(h)
        elif m.get("minutes_url") and n.get("minutes_url") and n["minutes_url"] != m["minutes_url"]:
            shas.add(h)
    return shas - held


def splice(new: list, old: list, from_old, ident) -> list:
    """`new` without the records `from_old` claims, plus those records from `old`, each placed right after the record
    it follows in `old` (the city's lists keep listing and document order, not id order). A record kept two days
    running lands in the same place, so the written file is byte-identical."""
    out = [x for x in new if not from_old(x)]
    present = {ident(x) for x in out}
    after: dict = {}
    anchor = None
    for x in old:
        if from_old(x):
            after.setdefault(anchor, []).append(x)
        elif ident(x) in present:
            anchor = ident(x)
    res = list(after.pop(None, []))
    for x in out:
        res.append(x)
        res.extend(after.pop(ident(x), []))
    return res


def keep_city(new: dict, old: dict, wards_new: list, wards_old: list, kept: list[dict]) -> tuple[dict, list]:
    """The county's keep_documents on the city facts (ADR 0006 fix 2), in the city's own order: every kept meeting's
    records, sources and items exactly as committed, its committed agenda source (agenda_source_id) too, and its
    wards.json entries; everything else as built."""
    ms, sids = keep_closure(new, old, kept)
    base = keep_documents(new, old, kept)            # items, sources and coverage as the county keeps them

    def mine(r: dict, key: str = "meeting_id") -> bool:
        return r.get(key) in ms or r.get("source_id") in sids
    out = dict(base)
    out["meetings"] = splice(new.get("meetings", []), old.get("meetings", []), lambda m: mine(m, "id"), lambda m: m["id"])
    for k in ("roll_calls", "motions", "item_events"):
        out[k] = splice(new.get(k, []), old.get(k, []), mine, lambda r: r["id"])
    have = {s["id"] for s in base["sources"]}
    agenda = {m.get("agenda_source_id") for m in old.get("meetings", []) if m["id"] in ms} - {None}
    out["sources"] = sorted(base["sources"] + [s for s in old.get("sources", []) if s["id"] in agenda - have],
                            key=lambda s: (s.get("meeting_date") or "", s["id"]))
    wards = splice(wards_new, wards_old, lambda w: w.get("meeting_id") in ms,
                   lambda w: json.dumps(w, sort_keys=True))
    return out, wards


def paths(cfg: AgendaCenterConfig, root: Path = ROOT) -> dict:
    d = root / "data" / "localities" / cfg.locality
    return {"dir": d, "listing": d / "listing.json", "manifest": d / "manifest.json", "facts": d / "facts.json", "wards": d / "wards.json",
            "cc_listing": d / "civicclerk-listing.json", "report": root / "build" / "city-report.json"}


def write_json(p: Path, obj) -> bool:
    text = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if p.exists() and p.read_text(encoding="utf-8") == text:
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return True


def cmd_fetch(cfg: AgendaCenterConfig, store: Store, listing_path: Path, log: dict, fetcher=None,
              agendas: bool = False, limit: int | None = None, allow_drop: set | None = None,
              today: str | None = None, meetings: dict | None = None) -> list[dict]:
    f = fetcher or PoliteFetcher()
    previous = json.loads(listing_path.read_text(encoding="utf-8")) if listing_path.exists() else None
    try:
        rows = discover(f, cfg, log, previous)
    except (ListingError, FetchFailed) + STOP as e:
        log["failures"].append(failure("listing", e))
        log["fetch_log"] = f.log
        return []
    write_json(listing_path, guard_listing(rows, previous, "agenda_id", listing_path.name, log, allow_drop, today,
                                           meetings))
    return fetch_files(f, store, rows, log, agendas, limit)


def cmd_fetch_civicclerk(cc: civicclerk.CivicClerkConfig, kind_of, store: Store, listing_path: Path, log: dict,
                         fetcher=None, agendas: bool = False, limit: int | None = None,
                         cache_dir: Path | None = None, allow_drop: set | None = None,
                         today: str | None = None, meetings: dict | None = None) -> list[dict]:
    """The CivicClerk listing (every events page, cached) then its minutes (and agendas). A listing that fails part
    way is not written, so the last full civicclerk-listing.json stays."""
    f = fetcher or PoliteFetcher()
    try:
        rows = civicclerk.discover(f, cc, kind_of, log, cache_dir or store_dir() / "civicclerk")
    except (civicclerk.EventsError, FetchFailed) + STOP as e:
        log["failures"].append(failure("listing", e, source=civicclerk.SOURCE))
        log["fetch_log"] = f.log
        return []
    previous = json.loads(listing_path.read_text(encoding="utf-8")) if listing_path.exists() else None
    write_json(listing_path, guard_listing(rows, previous, "event_id", listing_path.name, log, allow_drop, today,
                                           meetings))
    return fetch_files(f, store, rows, log, agendas, limit)


def fetch_files(f, store: Store, rows: list[dict], log: dict, agendas: bool, limit: int | None) -> list[dict]:
    jobs = [(r, "minutes", r["minutes_url"]) for r in rows if r["minutes_url"]]
    # a D1 row (page1_required) is kept by the build only when page 1 of its agenda or minutes prints the body's
    # name, so its agenda is fetched too
    jobs += [(r, "agenda", r["agenda_url"]) for r in rows if r["agenda_url"] and (agendas or r.get("page1_required"))]
    if limit is not None:
        jobs = jobs[:limit]
    stopped = False
    for r, kind, url in jobs:
        if stopped:
            log["fetched"]["not_tried"] = log["fetched"].get("not_tried", 0) + 1
            continue
        try:
            _, status = fetch_into_store(f, store, url, {"kind": kind, "meeting_date": r["date"], "label": r["title"]})
            log["fetched"][status] = log["fetched"].get(status, 0) + 1
            store.save()                      # saved as it goes, so a stopped run keeps what it fetched
        except STOP as e:
            log["failures"].append(failure("fetch", e, url=url))
            stopped = isinstance(e, (HostBlocked, HostRefused))
        except FetchFailed as e:              # one file (e.g. a .docx behind a PDF link) is logged and skipped
            log["failures"].append(failure("fetch", e, url=url))
    store.save()
    log["fetch_log"] = f.log
    return rows


def listing_rows(p: dict, cfg: AgendaCenterConfig, store: Store | None = None) -> tuple[list[dict], list[dict]]:
    """Both committed listings joined (civicclerk.merge_sources). The meeting kind is re-read from each title with
    the current config, as the build does, so the de-duplication and the meeting ids agree. A D1 row is paired only
    after its page 1 check passes on the stored files (city-verify/d1-merge-before-page1); with no store, never."""
    ac = json.loads(p["listing"].read_text(encoding="utf-8")) if p["listing"].exists() else []
    cc = json.loads(p["cc_listing"].read_text(encoding="utf-8")) if p["cc_listing"].exists() else []
    ac = [{**r, "kind": cfg.kind_of(r["title"])} for r in ac]
    cc = [{**r, "kind": cfg.kind_of(r["title"])} for r in cc]
    if store is None:
        return civicclerk.merge_sources(ac, cc)
    from .city_build import page1_check
    return civicclerk.merge_sources(ac, cc, page1_ok=lambda r: page1_check(r, store) is None)


def guard_facts(facts: dict, wards: list, p: dict, store: Store, log: dict, summary: dict,
                allow_drop: set | None = None, listed: set | None = None, kind_of=None) -> tuple[dict, list]:
    """ADR 0006 fix 2: the county's shrink guard (collector/shrink_guard.py) on the city facts. Each committed meeting
    read from its minutes is compared, by its minutes' sha256, with the new build: lost verified roll calls, a meeting
    gone, or its minutes missing from the run keep that meeting exactly as committed (records, sources, agenda source,
    wards); a replaced file that was read is a correction (the new reading wins, a warning only when its verified count
    fell or its votes changed), one that was not read (unread_meetings) keeps the meeting. A committed agenda-only
    meeting the build lacks while its row is still listed is kept the same way (guarded_units). The merged facts and
    wards are returned (always written), the gates recomputed on them."""
    from .verify import gates
    if not p["facts"].exists():
        return facts, wards
    old = json.loads(p["facts"].read_text(encoding="utf-8"))
    wards_old = json.loads(p["wards"].read_text(encoding="utf-8")) if p["wards"].exists() else []
    res = shrink_guard(facts, guarded_units(old, facts, listed, kind_of), p["facts"].name,
                       city_superseded(store, old, facts), unread_meetings(old, facts))
    g = log.setdefault("guard", {})
    kept = res["kept"]
    if res["corrections"]:
        g["corrections"] = res["corrections"]
        g["lowered"] = [c for c in res["corrections"] if c["verified"][1] < c["verified"][0] or c.get("votes_changed")]
        if not g["lowered"]:
            del g["lowered"]
    named = [k for k in kept if allowed(log, allow_drop, *k["meeting_ids"])]
    if named:
        g.setdefault("allowed_drop", []).append({"facts": p["facts"].name, "kept_meetings": named})
        print(f"collector city: ALLOWED (--allow-drop) {', '.join(m for k in named for m in k['meeting_ids'])}",
              file=sys.stderr, flush=True)
    kept = [k for k in kept if k not in named]
    if not kept:
        return facts, wards
    g["kept_meetings"] = kept
    g["withheld_new"] = sorted({m for k in kept for m in k.get("withheld_new") or []})
    for k in kept:
        print(f"collector city: KEPT {k['source_id']} ({', '.join(k['meeting_ids'])}): {k['reason']}",
              file=sys.stderr, flush=True)
    merged, wards = keep_city(facts, old, wards, wards_old, kept)
    summary["gates"] = gates(merged, set())          # the gates judge what is published (the county's G2.3)
    summary["pass"] = summary["gates"]["verified_rate_gate"]["pass"] and summary["gates"]["g4"]["pass"]
    return merged, wards


def unmatched_drops(log: dict, drop: set) -> list[str]:
    """The --allow-drop ids no kept row or meeting matched (sorted)."""
    return sorted(set(drop) - log.get("_allow_matched", set()))


def new_log() -> dict:
    return {"failures": [], "fetched": {}}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m collector city")
    ap.add_argument("command", choices=("fetch", "build", "run"))
    ap.add_argument("--agendas", action="store_true", help="also fetch agenda PDFs (minutes are always fetched)")
    ap.add_argument("--limit", type=int, default=None, help="fetch at most N files (testing)")
    ap.add_argument("--locality", default="clarksville-tn")
    ap.add_argument("--source", choices=("all", "agenda-center", "civicclerk"), default="all",
                    help="which listing to fetch (the build always reads both)")
    ap.add_argument("--allow-drop", action="append", default=[], metavar="ID[,ID]",
                    help="let these kept meetings (meeting ids) or listing rows (row keys) go, as the kept entries in "
                         "build/city-report.json print them (a meeting id names a listing row only when the row has "
                         "that meeting's committed minutes_url); an id that matches nothing is refused (exit 2)")
    a = ap.parse_args(argv)
    cfg = load_config(Path(ROOT / "config" / "localities" / a.locality / "agenda-center.yml"))
    cc_path = civicclerk.config_path(a.locality)
    cc = civicclerk.load_config(cc_path) if cc_path.exists() else None
    p = paths(cfg)
    store = Store(manifest_path=p["manifest"])
    log = new_log()
    since = limits.mark()                      # this step's own trips only (limits invariant rule 3)
    drop = {i.strip() for v in a.allow_drop for i in v.split(",") if i.strip()}
    # an --allow-drop id that matches nothing writes nothing (ADR 0006 fix 3): the listings are put back as they were
    before = {k: (p[k].read_bytes() if p[k].exists() else None) for k in ("listing", "cc_listing")} if drop else {}
    if a.command in ("fetch", "run"):
        fetcher = PoliteFetcher()
        meetings = committed_meetings(p["facts"])
        if a.source in ("all", "agenda-center"):
            cmd_fetch(cfg, store, p["listing"], log, fetcher=fetcher, agendas=a.agendas, limit=a.limit,
                      allow_drop=drop, meetings=meetings)
        if cc and a.source in ("all", "civicclerk"):
            cmd_fetch_civicclerk(cc, cfg.kind_of, store, p["cc_listing"], log, fetcher=fetcher, agendas=a.agendas,
                                 limit=a.limit, allow_drop=drop, meetings=meetings)
    report = {"fetch": {k: v for k, v in log.items() if k not in ("fetch_log", "_allow_matched")}}
    if a.command in ("build", "run"):
        from .city_build import build
        rows, dups = listing_rows(p, cfg, store)
        facts, summary = build(cfg, rows, store)
        summary["duplicates"] = dups
        wards = facts.pop("_wards")
        listed = {(r["date"], r["kind"]) for r in rows}
        facts, wards = guard_facts(facts, wards, p, store, log, summary, drop, listed, cfg.kind_of)
        if not unmatched_drops(log, drop):
            write_json(p["wards"], wards)
            write_json(p["facts"], facts)
        report["build"] = summary
        report["fetch"] = {k: v for k, v in log.items() if k not in ("fetch_log", "_allow_matched")}
    report["guard"] = log.get("guard") or {}
    report["limits"] = limits.tripped(since)
    write_json(p["report"], {**report, "fetch_log": log.get("fetch_log", [])})
    print(json.dumps({k: v for k, v in report.items()}, indent=1, default=str)[:4000])
    print(limits.summary("collector city", since), flush=True)
    code = exit_code(log)
    unmatched = unmatched_drops(log, drop)
    if unmatched:
        for k, b in before.items():
            if b is None:
                p[k].unlink(missing_ok=True)
            else:
                p[k].write_bytes(b)
        print(f"collector city: REFUSED --allow-drop {', '.join(unmatched)}: no kept row or meeting has that id, so "
              f"nothing was written (the listings, {p['facts'].name} and {p['wards'].name} are as they were). Use "
              f"the ids printed under guard in {p['report'].name}", file=sys.stderr, flush=True)
        return BLOCKED if code == BLOCKED else LISTING_FAILED
    if "build" in report:              # the gates (AC-P1, G4) with the county's code: see GATE_FAILED
        g = report["build"]["gates"]
        print(f"collector city: {g['roll_calls']} roll calls, {g['verified']} verified "
              f"({100 * g['verified_rate']:.1f}%, AC-P1 {'pass' if g['verified_rate_gate']['pass'] else 'FAIL'}); "
              f"G4 {g['g4']['status']}, flagged {g['g4']['flagged'] or 'none'} "
              f"(uniform share {g['g4']['uniform_share']})", flush=True)
        if code == 0 and not g["g4"]["pass"]:
            print(f"collector city: G4 skew gate FAILED (exit {GATE_FAILED}): {', '.join(g['g4']['flagged'])}",
                  file=sys.stderr, flush=True)
            code = GATE_FAILED
    if code == 0 and kept_anything(log):       # precedence 5 > 2 > 3 > 7 > 0 (ADR 0006)
        print(f"collector city: KEPT (exit {KEPT}): committed rows or meetings kept, see guard in "
              f"{p['report'].name}; everything else is published", file=sys.stderr, flush=True)
        code = KEPT
    if code == BLOCKED:
        print(f"collector city: REFUSED by a host or by policy (exit {BLOCKED}); not retried. See the failures above.",
              file=sys.stderr, flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
