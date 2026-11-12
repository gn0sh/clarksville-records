"""The shrink guard (docs/architecture/pipeline-limits-invariant.md "Rule 3: the shrink guard", G1-G4), shared by the
county run (collector/__main__.py, which re-exports every name here) and the city run (collector/city_run.py,
docs/adr/0006-daily-refresh-data-guards.md fix 2). Moved from collector/__main__.py unchanged: per source document and
every meeting in it, by sha256."""
from __future__ import annotations

import json

from .facts import norm_title


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


def item_key(facts: dict) -> dict:
    """item id -> a key that does not depend on the document's bytes: its number when it is linked by number, else its
    normalised title. A `t-` id of a procedural or untitled item (e.g. "Consent Agenda") is salted with the roll call
    or source id, which a new sha256 renames (pipeline/votes-changed-salted-item-id)."""
    return {i["id"]: (i.get("number") if i.get("link_basis") == "number" and i.get("number")
                      else "title:" + norm_title(i.get("title") or "")) for i in facts.get("items", [])}


def vote_content(facts: dict, meeting_ids) -> list:
    """The votes of these meetings without ids, sources or pages (which a new sha256 renames): per roll call its item
    (item_key), outcome, stated tally and each vote's official, name and value, sorted. Equal lists: the correction
    kept every vote."""
    ms = set(meeting_ids)
    key = item_key(facts)
    return sorted(json.dumps([r.get("meeting_id"), key.get(r.get("item_id"), r.get("item_id")), r.get("outcome"),
                              r.get("stated_tally"),
                              sorted([v.get("official_id") or "", v.get("raw_name") or "", v.get("value") or ""]
                                     for v in r.get("votes") or [])], sort_keys=True)
                  for r in facts.get("roll_calls", []) if r.get("meeting_id") in ms)


def shrink_guard(new: dict, old: dict, name: str = "facts.json", superseded=(), unread=(),
                 drop_flag: str = "--allow-shrink") -> dict:
    """G1 (docs/architecture/pipeline-limits-invariant.md, "Rule 3: the shrink guard"): compare the new result with the
    committed facts `old` per source document S (and every meeting Ms it carries), by sha256.
    (a) S's bytes are in the result: a roll call of S verified in `old` and not verified (or absent) in `new`, or a
        meeting of Ms gone, keeps S (a limit trip, a lost OCR reading, a parser change).
    (b) S's bytes are not, but every meeting of Ms is, under another source, AND S was replaced: a new source carrying
        Ms has S's url, or the store marks S's sha256 superseded (`superseded`, from store.superseded()). That is a
        correction; the new reading wins (pipeline/correction-not-bytes-changed: a meeting that merely moved to
        another document, meetings.choose, while S is unchanged is not one, and keeps S). A meeting of Ms in `unread`
        (the new file was not read: not fetched, parse failed; the city passes these) is never a correction, so S is
        kept (shrink/city-correction-on-unread-file).
    (c) S's bytes are not and a meeting of Ms is absent too (not in the store, a fetch or parse failure, a timeout):
        transient, keeps S.
    Gains are never guarded. `drop_flag` is the flag a kept reason names for a deliberate drop (the county's
    --allow-shrink; the city passes its --allow-drop).
    Returns {'kept': [{source_id, meeting_ids, ids (lost verified roll calls), reason,
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
    unread = set(unread or ())
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
                           f"needs {drop_flag})")
            if why:
                kept.append({"source_id": sid, "meeting_ids": ms, "ids": lost,
                             "reason": f"same document (sha256 {h8}): " + "; ".join(why)})
        elif not gone:
            to = sorted({now_src[m] for m in ms})
            unread_ms = sorted(unread.intersection(ms))
            replaced = not unread_ms and ((bool(h) and h in superseded) or (
                bool(old_url.get(sid)) and any(url_of_new.get(t) == old_url[sid] for t in to)))
            if replaced:                                                                        # (b) correction
                n_new = sum(1 for r in new.get("roll_calls", []) if r.get("meeting_id") in ms and _verified(r))
                corrections.append({"meeting_ids": ms, "source_id": sid, "new_source_ids": to, "sha256": h,
                                    "new_sha256": [sha_of_new.get(t, t) for t in to], "verified": [len(was), n_new],
                                    "votes_changed": vote_content(old, ms) != vote_content(new, ms)})
            elif unread_ms:                                             # the new file was not read: not yet
                lost = [i for i in was if i not in now_verified]
                kept.append({"source_id": sid, "meeting_ids": ms, "ids": lost,
                             "reason": f"document sha256 {h8} not in the result and the new minutes of "
                                       f"{', '.join(unread_ms)} were not read (not fetched, or a parse failure): "
                                       f"not a correction until the new file reads"})
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
    added back when `new` lacks them, and new items only the replaced records named are dropped; an item's zoning
    field that cites a dropped source takes the committed field or None; officials come from `new`. Lists are sorted
    as Builder.facts sorts them, so a document kept two days running writes the same file."""
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
    # every item is named by a record (Builder.items); one only the replaced new records named goes with them
    used = {r.get("item_id") for k in ("roll_calls", "motions", "item_events") for r in out[k]}
    out["items"] = sorted([i for i in new.get("items", []) if i["id"] in used]
                          + [i for i in old.get("items", []) if i["id"] in named and i["id"] not in have],
                          key=lambda x: x["id"])
    # pipeline/keep-closure-dangling-zoning-ref: an item's zoning field may cite a new source the keep dropped (a
    # new-only document of the closure); it takes the committed item's field (when its source is published), else None
    published = {x["id"] for x in out["sources"]}
    was = {i["id"]: i for i in old.get("items", [])}
    for n, it in enumerate(out["items"]):
        z = it.get("zoning")
        if not z or all(f is None or f.get("source_id") in published for f in z.values()):
            continue
        oz = (was.get(it["id"]) or {}).get("zoning") or {}
        fixed = {}
        for name, f in z.items():
            if f is None or f.get("source_id") in published:
                fixed[name] = f
            else:
                o = oz.get(name)
                fixed[name] = o if o is not None and o.get("source_id") in published else None
        out["items"][n] = {**it, "zoning": fixed}
    dates = [m["date"] for m in out["meetings"] if m.get("date")]
    if dates and isinstance(new.get("coverage"), dict):       # the published meetings' range, kept ones included
        out["coverage"] = {**new["coverage"], "from": min(dates), "to": max(dates)}
    return out
