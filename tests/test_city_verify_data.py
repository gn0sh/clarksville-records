"""city-verify V6: the data regression on the committed city facts (docs/architecture/city-council.md, "Verified-rate
plan", Tests: Data). The rebuild with D1, W1, W2 and M1 changes only the listed roll calls from held to verified,
changes no vote of a roll call verified before, adds the one D1 meeting (2 roll calls), and no check was loosened:
every newly verified roll call passes every check it already had."""
import hashlib
import json

from conftest import ROOT

CITY = ROOT / "data" / "localities" / "clarksville-tn"
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


def facts():
    return json.loads((CITY / "facts.json").read_text(encoding="utf-8"))


def verified(r):
    return r["verification"]["status"] == "verified"


def test_only_the_listed_roll_calls_turned_verified_and_no_verified_vote_changed():
    f = facts()
    now = sorted(r["id"] for r in f["roll_calls"] if verified(r))
    assert set(NEWLY_VERIFIED) <= set(now)
    before = sorted((r["id"], [(v["official_id"], v["value"]) for v in r["votes"]]) for r in f["roll_calls"]
                    if verified(r) and r["id"] not in NEWLY_VERIFIED)
    assert len(before) == BEFORE_VERIFIED
    assert hashlib.sha256(json.dumps(before).encode()).hexdigest() == BEFORE_DIGEST
    assert (len(now), len(f["roll_calls"])) == (1823, 2237)


def test_the_d1_meeting_is_built_with_its_two_roll_calls():
    f = facts()
    m = next(m for m in f["meetings"] if m["id"] == "2026-02-11-special")
    assert m["minutes_url"].endswith("fileId=3068,plainText=false)") and m["listing_source"] == "civicclerk"
    rcs = {r["id"]: r for r in f["roll_calls"] if r["meeting_id"] == m["id"]}
    assert sorted(rcs) == ["rc-df53b5ec-p2-0", "rc-df53b5ec-p2-1"]
    held = rcs["rc-df53b5ec-p2-1"]
    assert not verified(held) and {"check": "names_resolve", "ok": False, "detail": "HOLLEMNA"} in \
        held["verification"]["checks"]                                     # a misspelling stays held (never a guess)


def test_newly_verified_roll_calls_pass_every_check_and_name_each_word_break():
    f = facts()
    by_id = {r["id"]: r for r in f["roll_calls"]}
    for rid in NEWLY_VERIFIED:
        assert all(c["ok"] for c in by_id[rid]["verification"]["checks"]), rid
    details = [c.get("detail", "") for r in f["roll_calls"] for c in r["verification"]["checks"]
               if c["check"] == "names_resolve"]
    assert sum("(same letters, spaces ignored)" in d for d in details) == 10


def test_claunch_is_the_configured_member_from_the_seating_and_jeff_henley_reads_whole():
    f = facts()
    text = json.dumps(f)
    assert "J eff Henley" not in text and "J\\u200b" not in text
    claunch = next(o for o in f["officials"] if o["id"] == "city-eric-claunch")
    src = next(s for s in f["sources"] if s["id"] == claunch["name_source"]["source_id"])
    assert src["url"].endswith("fileId=3068,plainText=false)") and src["sha256"].startswith("df53b5ec7368")
    assert claunch["name_source"]["page"] == 3
    before = [m for m in f["meetings"] if m["date"] < "2026-02-19"]
    assert not any(a["official_id"] == "city-eric-claunch" for m in before for a in m["attendance"])
    wards = json.loads((CITY / "wards.json").read_text(encoding="utf-8"))
    assert [w for w in wards if w.get("configured")] == [{
        "official_id": "city-eric-claunch", "raw_name": "Eric Claunch", "ward": 2, "pro_tem": False,
        "meeting_id": "2026-02-11-special", "date": "2026-02-19", "source_id": src["id"], "page": 3,
        "configured": True}]
