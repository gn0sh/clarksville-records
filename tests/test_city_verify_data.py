"""city-verify V6: the data regression on the committed city facts (docs/architecture/city-council.md, "Verified-rate
plan", Tests: Data). The rebuild with D1, W1, W2 and M1 changes only the listed roll calls from held to verified,
changes no vote of a roll call verified before, adds the one D1 meeting (2 roll calls), and no check was loosened:
every newly verified roll call passes every check it already had.

D1 widened (2026-11-11): the council meetings CivicClerk files under "General" by other names add 16 meetings (147 roll
calls, 110 verified); every roll call verified at V6 (1,823 of 2,237) is unchanged, votes included (V6_DIGEST).

D1 minutes identity (2026-11-12, d1-minutes-identity): an also-listed row's minutes are read only when their own page 1
prints the heading and every printed date is the row's date. 2026-07-09 is agenda-only (its minutes are called to order
"Monday, July 6, 2026": 30 roll calls, 21 verified, no longer read) and 2026-02-19 is skipped (its agenda's page 1 does
not print the heading on a line of its own; its file was the 2026-02-11 minutes, read once for 2026-02-11, no roll
calls). 15 meetings remain from the widening (117 roll calls, 89 verified); V6_DIGEST is unchanged.

pipeline/tests-pin-live-data (2026-11-12): the daily update runs this suite on the facts it is about to publish, so the
counts and digests of one rebuild are checked on a committed snapshot of the city facts at a605d25 (SNAPSHOT, only
the fields these tests read), never on the live file a new council meeting grows. The live file is checked for what
must hold however it grows: every snapshot meeting is kept, and a roll call verified in the snapshot whose source
document is still cited is still verified with the same votes. Rewrite the snapshot (write_snapshot) only with a
deliberate rebuild, and update the counts below with it."""
import gzip
import hashlib
import json

import pytest

from conftest import ROOT

CITY = ROOT / "data" / "localities" / "clarksville-tn"
SNAPSHOT = ROOT / "tests" / "fixtures" / "city-facts-a605d25.json.gz"
# The roll calls verified before (committed facts at 255039b: 1,756 of 2,235) and a digest of their votes
# [(id, [(official_id, value), ...])], sorted: none may change or be lost.
BEFORE_VERIFIED = 1756
BEFORE_DIGEST = "3acb687c1ac1b330ad13682bf45a8dc5bb49c61a13287d6d258daddf134aa888"
# Held before, verified now (66), plus the D1 meeting's one roll call that passes (rc-df53b5ec-p2-0): 2020-10-01 18
# (W1 "Jeff Henley"), 2022-04-07 6 (W2 "StaceyStreetman"), the four CLAUNCH meetings of 2026 39 (M1), and 3 vote
# tokens printed with a break (W2: "H olleman" 2022-08-04, "LOV ATO" 2025-01-02, "H OLLEMAN" 2025-05-01).
NEWLY_VERIFIED = [
    "rc-06cb9d66-p2-0",
    "rc-06cb9d66-p2-1",
    "rc-06cb9d66-p3-0",
    "rc-06cb9d66-p5-0",
    "rc-06cb9d66-p5-1",
    "rc-06cb9d66-p5-2",
    "rc-06cb9d66-p6-0",
    "rc-06cb9d66-p7-0",
    "rc-1c6813b9-p4-1",
    "rc-209ffc71-p2-0",
    "rc-209ffc71-p2-1",
    "rc-209ffc71-p3-1",
    "rc-209ffc71-p4-0",
    "rc-209ffc71-p4-1",
    "rc-209ffc71-p5-0",
    "rc-209ffc71-p5-2",
    "rc-209ffc71-p6-2",
    "rc-4fe6d48b-p12-0",
    "rc-4fe6d48b-p12-2",
    "rc-4fe6d48b-p3-0",
    "rc-4fe6d48b-p4-0",
    "rc-4fe6d48b-p4-1",
    "rc-4fe6d48b-p4-2",
    "rc-5ee078dd-p7-1",
    "rc-8bc059bb-p2-0",
    "rc-8bc059bb-p3-0",
    "rc-8bc059bb-p3-1",
    "rc-8bc059bb-p3-2",
    "rc-8bc059bb-p4-0",
    "rc-8bc059bb-p5-0",
    "rc-8bc059bb-p6-0",
    "rc-8bc059bb-p6-1",
    "rc-8bc059bb-p7-0",
    "rc-8bc059bb-p8-0",
    "rc-8bc059bb-p9-0",
    "rc-8bc059bb-p9-1",
    "rc-9f1eedb3-p2-0",
    "rc-9f1eedb3-p2-1",
    "rc-9f1eedb3-p2-2",
    "rc-9f1eedb3-p3-1",
    "rc-9f1eedb3-p3-2",
    "rc-9f1eedb3-p4-0",
    "rc-9f1eedb3-p4-1",
    "rc-9f1eedb3-p5-0",
    "rc-9f1eedb3-p8-0",
    "rc-9f1eedb3-p8-1",
    "rc-9f1eedb3-p9-0",
    "rc-cc5b9995-p5-1",
    "rc-da71ebde-p10-0",
    "rc-da71ebde-p10-1",
    "rc-da71ebde-p11-0",
    "rc-da71ebde-p11-1",
    "rc-da71ebde-p2-0",
    "rc-da71ebde-p4-0",
    "rc-da71ebde-p4-1",
    "rc-da71ebde-p4-2",
    "rc-da71ebde-p5-0",
    "rc-da71ebde-p5-1",
    "rc-da71ebde-p5-2",
    "rc-da71ebde-p5-3",
    "rc-da71ebde-p6-0",
    "rc-da71ebde-p6-1",
    "rc-da71ebde-p7-0",
    "rc-da71ebde-p8-0",
    "rc-da71ebde-p9-0",
    "rc-da71ebde-p9-1",
    "rc-df53b5ec-p2-0"
]


# The 15 meetings the D1 widening added (event names other than "Special Session" under "General"); 2026-02-19, the
# 16th, is skipped by the minutes identity check (SKIPPED).
WIDENED = ["2025-02-18-special", "2025-06-17-special", "2025-06-24-special", "2025-11-12-special",
           "2026-04-06-special", "2026-04-29-special", "2026-05-07-special", "2026-05-26-work-session",
           "2026-06-11-special", "2026-06-16-special", "2026-06-22-special", "2026-06-29-special", "2026-07-02-regular",
           "2026-07-06-special", "2026-07-09-special"]
# Every roll call verified at V6 (committed facts at e7cdcb5: 1,823 of 2,237), digested as BEFORE_DIGEST is
V6_VERIFIED = 1823
V6_DIGEST = "cefce9ab1c1dffb89766c7373d419eef57f3f911ca344d316992eb5590b2cebc"
SKIPPED = "2026-02-19-special"
# Meetings a deliberate-drop PR removed (python -m collector city run --allow-drop, docs/adr/0006): a PR that drops a
# meeting read from its minutes extends this tuple, so the live check below still holds.
DROPPED = ()


def facts():
    """The live city facts: what this run publishes."""
    return json.loads((CITY / "facts.json").read_text(encoding="utf-8"))


def live_wards() -> list:
    """The live wards.json: what this run publishes."""
    return json.loads((CITY / "wards.json").read_text(encoding="utf-8"))


def project(f: dict, wards: list | None = None) -> dict:
    """The fields of the city facts (and the configured wards.json entries) these tests read (no raw text of any
    document)."""
    return {
        "officials": [{"id": o["id"], "name_source": {k: o["name_source"][k] for k in ("source_id", "page")}}
                      for o in f.get("officials", []) if o.get("name_source")],
        "wards": [w for w in wards or [] if w.get("configured")],
        "meetings": [{k: m.get(k) for k in ("id", "date", "listing_source", "minutes_status", "minutes_url")}
                     | {"attendance": [a["official_id"] for a in m.get("attendance") or []]} for m in f["meetings"]],
        "roll_calls": [{"id": r["id"], "meeting_id": r["meeting_id"], "source_id": r["source_id"],
                        "verification": r["verification"],
                        "votes": [{"official_id": v["official_id"], "value": v["value"]} for v in r["votes"]]}
                       for r in f["roll_calls"]],
        "sources": [{k: s.get(k) for k in ("id", "kind", "meeting_date", "url", "sha256")} for s in f["sources"]],
    }


def write_snapshot(path=SNAPSHOT):
    """Rewrite SNAPSHOT from the live city facts (a deliberate rebuild only): byte-stable gzip, mtime 0."""
    raw = json.dumps(project(facts(), live_wards()), sort_keys=True, separators=(",", ":")).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(raw, compresslevel=9, mtime=0))


def snapshot():
    """The city facts of one rebuild (a605d25), projected: the exact counts and digests are checked here."""
    return json.loads(gzip.decompress(SNAPSHOT.read_bytes()))


def verified(r):
    return r["verification"]["status"] == "verified"


def test_only_the_listed_roll_calls_turned_verified_and_no_verified_vote_changed():
    f = snapshot()
    now = sorted(r["id"] for r in f["roll_calls"] if verified(r))
    assert set(NEWLY_VERIFIED) <= set(now)
    before = sorted((r["id"], [(v["official_id"], v["value"]) for v in r["votes"]]) for r in f["roll_calls"]
                    if verified(r) and r["id"] not in NEWLY_VERIFIED and r["meeting_id"] not in WIDENED)
    assert len(before) == BEFORE_VERIFIED
    assert hashlib.sha256(json.dumps(before).encode()).hexdigest() == BEFORE_DIGEST
    # 1,912 -> 1,921: the 2026-07-06 printing correction (CLAULNCH read as CLAUNCH) verifies 9 of its 11 roll calls
    assert (len(now), len(f["roll_calls"])) == (1921, 2354)


def test_the_d1_widening_adds_only_council_meetings_and_changes_no_verified_roll_call():
    f = snapshot()
    v6 = sorted((r["id"], [(v["official_id"], v["value"]) for v in r["votes"]]) for r in f["roll_calls"]
                if verified(r) and r["meeting_id"] not in WIDENED)
    assert len(v6) == V6_VERIFIED
    assert hashlib.sha256(json.dumps(v6).encode()).hexdigest() == V6_DIGEST
    ms = {m["id"]: m for m in f["meetings"]}
    assert set(WIDENED) <= set(ms) and len(ms) == 401
    assert {ms[i]["listing_source"] for i in WIDENED} == {"civicclerk"}
    rcs = [r for r in f["roll_calls"] if r["meeting_id"] in WIDENED]
    assert (len(rcs), sum(map(verified, rcs))) == (117, 98)       # 89 + 9 at 2026-07-06 (printing correction)
    r0706 = [r for r in rcs if r["meeting_id"] == "2026-07-06-special"]
    assert (len(r0706), sum(map(verified, r0706))) == (11, 9)
    assert sorted(r["id"] for r in r0706 if not verified(r)) == ["rc-ba3c3070-p2-0", "rc-ba3c3070-p4-2"]
    # the resumed session of 2026-02-19 has the 2026-02-11 minutes posted again: read once, for 2026-02-11; the
    # 2026-02-19 row's agenda page 1 does not vouch for it, so it is skipped
    assert SKIPPED not in ms
    assert ms["2026-02-11-special"]["minutes_status"] == "read"
    # 2026-07-09: the minutes print July 9 in the heading but are called to order "Monday, July 6, 2026": agenda-only
    m = ms["2026-07-09-special"]
    assert m["minutes_status"] == "other_meeting" and not m.get("attendance")
    assert not [r for r in f["roll_calls"] if r["meeting_id"] == m["id"]]
    assert not [s for s in f["sources"] if s["meeting_date"] == "2026-07-09" and s["kind"] == "minutes"]


def test_the_d1_meeting_is_built_with_its_two_roll_calls():
    f = snapshot()
    m = next(m for m in f["meetings"] if m["id"] == "2026-02-11-special")
    assert m["minutes_url"].endswith("fileId=3068,plainText=false)") and m["listing_source"] == "civicclerk"
    rcs = {r["id"]: r for r in f["roll_calls"] if r["meeting_id"] == m["id"]}
    assert sorted(rcs) == ["rc-df53b5ec-p2-0", "rc-df53b5ec-p2-1"]
    held = rcs["rc-df53b5ec-p2-1"]
    assert not verified(held) and {"check": "names_resolve", "ok": False, "detail": "HOLLEMNA"} in \
        held["verification"]["checks"]                                     # a misspelling stays held (never a guess)


def test_newly_verified_roll_calls_pass_every_check_and_name_each_word_break():
    f = snapshot()
    by_id = {r["id"]: r for r in f["roll_calls"]}
    for rid in NEWLY_VERIFIED:
        assert all(c["ok"] for c in by_id[rid]["verification"]["checks"]), rid
    details = [(r["meeting_id"] in WIDENED, c.get("detail", "")) for r in f["roll_calls"]
               for c in r["verification"]["checks"] if c["check"] == "names_resolve"]
    assert sum("(same letters, spaces ignored)" in d for w, d in details if not w) == 10
    assert sum("(same letters, spaces ignored)" in d for w, d in details if w) == 3       # 2026-06-16, D1 widening


def test_claunch_seating_record_on_the_snapshot():
    """The cited seating record as the rebuild wrote it: its source, sha, page and the exact wards.json entry."""
    f = snapshot()
    [ns] = [o["name_source"] for o in f["officials"] if o["id"] == "city-eric-claunch"]
    src = next(s for s in f["sources"] if s["id"] == ns["source_id"])
    assert src["url"].endswith("fileId=3068,plainText=false)") and src["sha256"].startswith("df53b5ec7368")
    assert ns["page"] == 3
    assert f["wards"] == [{
        "official_id": "city-eric-claunch", "raw_name": "Eric Claunch", "ward": 2, "pro_tem": False,
        "meeting_id": "2026-02-11-special", "date": "2026-02-19", "source_id": src["id"], "page": 3,
        "configured": True}]


def test_claunch_is_the_configured_member_from_the_seating_and_jeff_henley_reads_whole():
    """On the live files, only what the run keeps true (ADR 0006 I3): Claunch is configured once, in ward 2, citing a
    source the facts publish, with no attendance before the seating; no snapshot meeting's records print the broken
    "J eff Henley"."""
    f, snap = facts(), snapshot()
    ms = {m["id"] for m in snap["meetings"]}
    text = json.dumps([r for k in ("meetings", "roll_calls", "motions", "item_events") for r in f[k]
                       if (r["id"] if k == "meetings" else r["meeting_id"]) in ms])
    assert "J eff Henley" not in text and "J\\u200b" not in text
    [w] = [w for w in live_wards() if w.get("configured") and w["official_id"] == "city-eric-claunch"]
    claunch = next(o for o in f["officials"] if o["id"] == "city-eric-claunch")
    sources = {s["id"] for s in f["sources"]}
    assert w["ward"] == 2 and w["source_id"] in sources and claunch["name_source"]["source_id"] in sources
    before = [m for m in f["meetings"] if m["date"] < w["date"]]
    assert not any(a["official_id"] == "city-eric-claunch" for m in before for a in m["attendance"])


def test_the_snapshot_is_the_projection_of_the_committed_facts_it_names():
    """The snapshot is byte-stable and holds only the projected fields (no text of any document)."""
    snap = snapshot()
    assert sorted(snap) == ["meetings", "officials", "roll_calls", "sources", "wards"]
    assert snap == project(snap | {"meetings": [{**m, "attendance": [{"official_id": a} for a in m["attendance"]]}
                                                for m in snap["meetings"]]}, snap["wards"])
    assert (len(snap["meetings"]), len(snap["roll_calls"]), sum(map(verified, snap["roll_calls"]))) == (401, 2354, 1921)


def test_the_live_facts_keep_every_snapshot_meeting_and_every_verified_vote_of_an_unchanged_document():
    """What holds however the live file changes (a new meeting, minutes posted late, a re-posted document, a
    cancelled agenda-only meeting): no snapshot meeting read from its minutes is lost (the city shrink guard keeps
    them; DROPPED lists deliberate drops), and a roll call verified in the snapshot whose source document is still
    cited (same sha256, so the same id) is still verified with the same votes. The roll calls of a re-posted
    document get new ids (collector/facts.py) and are judged by the shrink guard, not here."""
    live, snap = facts(), snapshot()
    meetings = {m["id"] for m in live["meetings"]}
    assert {m["id"] for m in snap["meetings"] if m["minutes_status"] == "read"} - set(DROPPED) <= meetings
    sources = {s["id"] for s in live["sources"]}
    by_id = {r["id"]: r for r in live["roll_calls"]}
    for r in snap["roll_calls"]:
        if not verified(r) or r["source_id"] not in sources:
            continue
        now = by_id.get(r["id"])
        assert now is not None and verified(now), r["id"]
        assert [(v["official_id"], v["value"]) for v in now["votes"]] == \
            [(v["official_id"], v["value"]) for v in r["votes"]], r["id"]


def grown(f: dict) -> dict:
    """The live facts after the next council meeting: one new meeting whose minutes give two verified roll calls (one
    with a vote token printed with a break), as a daily update adds them."""
    f = json.loads(json.dumps(f))
    last = next(r for r in reversed(f["roll_calls"]) if verified(r))
    f["meetings"].append({**next(m for m in f["meetings"] if m["id"] == last["meeting_id"]),
                          "id": "2099-01-07-regular", "date": "2099-01-07"})
    for n in range(2):
        rc = json.loads(json.dumps(last))
        rc.update(id=f"rc-99999999-p2-{n}", meeting_id="2099-01-07-regular")
        rc["verification"]["checks"] = [c | ({"detail": "H olleman (same letters, spaces ignored)"}
                                             if c["check"] == "names_resolve" else {})
                                        for c in rc["verification"]["checks"]]
        f["roll_calls"].append(rc)
    return f


def cancelled(f: dict) -> dict:
    """The live facts after a cancelled meeting with no minutes leaves the listing (the city guard drops it quietly)."""
    f = json.loads(json.dumps(f))
    gone = next(m["id"] for m in reversed(f["meetings"]) if m["minutes_status"] != "read")
    f["meetings"] = [m for m in f["meetings"] if m["id"] != gone]
    return f


def reposted(f: dict) -> dict:
    """The live facts after the city re-posted one meeting's minutes: new bytes, so a new sha256, source id and roll
    call, motion and item event ids (collector/facts.py), the same meeting."""
    f = json.loads(json.dumps(f))
    m = next(m for m in f["meetings"] if m["minutes_status"] == "read" and m["date"] < "2017")
    old8 = m["source_id"][4:12]
    text = json.dumps([r for k in ("roll_calls", "motions", "item_events") for r in f[k] if r["meeting_id"] == m["id"]])
    moved = json.loads(text.replace(old8, "f" * 8))
    for k in ("roll_calls", "motions", "item_events"):
        f[k] = [r for r in f[k] if r["meeting_id"] != m["id"]] + [r for r in moved if r["id"].startswith(
            {"roll_calls": "rc-", "motions": "mo-", "item_events": "ev-"}[k])]
    src = next(s for s in f["sources"] if s["id"] == m["source_id"])
    f["sources"].append({**src, "id": "src-" + "f" * 8 + src["id"][12:], "sha256": "f" * 64})
    f["sources"].remove(src)
    m["source_id"] = "src-" + "f" * 8 + src["id"][12:]
    return f


def renamed(f: dict) -> dict:
    """The live facts after a D1 meeting's listed title changed (CivicClerk renamed the event)."""
    f = json.loads(json.dumps(f))
    m = next(m for m in f["meetings"] if m["id"] == WIDENED[9])
    m["title"] = (m.get("title") or "") + " (Rescheduled)"
    return f


@pytest.mark.parametrize("change", [grown, cancelled, reposted, renamed], ids=lambda c: c.__name__)
def test_a_new_council_meeting_in_the_live_facts_fails_none_of_these_tests(monkeypatch, change):
    """pipeline/tests-pin-live-data (ADR 0006 fix 4, I3): the daily update runs this suite before it commits; what a
    daily update may legitimately do to the live facts must not halt it. Every other test of this module passes on
    the live facts after each change: a new meeting, a cancelled future meeting, a re-posted document and a renamed
    D1 title."""
    import sys
    module = sys.modules[__name__]
    live = facts()
    changed = change(live)
    assert changed != live
    monkeypatch.setattr(module, "facts", lambda: changed)
    for name, test in sorted(vars(module).items()):
        if name.startswith("test_") and name != "test_a_new_council_meeting_in_the_live_facts_fails_none_of_these_tests":
            test()
