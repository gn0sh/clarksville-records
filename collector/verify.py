"""Verifier (architecture "Verifier"; spec P1-P4, G4, AC-P1).

Every attendance section, roll call and motion gets {status, checks[{check, ok, detail}]}. A fact is verified only
when every check passes. The parser's P2 readings (collector/parse.py) supply the per-reading reasons; this module
names them as checks, adds the name checks against data/names.yml, and computes the run's gates.
"""
from __future__ import annotations

import re
from statistics import median

from .config import MIN_ROLL_CALLS_FOR_SKEW, SKEW_FACTOR, SKEW_FLOOR, VERIFIED_RATE_MIN

# parser reason text -> named check (first matching pattern wins)
REASON_CHECKS = [
    (r"no roster|attendance header not verified", "roster_available"),
    (r"inside an earlier meeting", "in_meeting_record"),
    (r"sources disagree", "readings_agree"),
    (r"name not matched|roster members not found|matched \d+ times|absent name not on roster", "names_resolve"),
    (r"no vote read|listed absent but has vote|conflicting vote|unrecognised token", "one_vote_per_present_member"),
    (r"^outcome", "outcome_consistent"),
    (r"tally|counted", "tally_matches_stated"),
    (r"ABSENT", "absent_line_consistent"),
    (r"token .* before any name|stray token|matching table not found|OCR failed", "table_read"),
]
RC_CHECKS = ("roster_available", "in_meeting_record", "names_resolve", "one_vote_per_present_member",
             "tally_matches_stated", "absent_line_consistent", "outcome_consistent", "readings_agree", "table_read")


def reason_check(reason: str) -> str:
    r = re.sub(r"^\[[\w-]+\]\s*", "", reason)
    for pat, name in REASON_CHECKS:
        if re.search(pat, r, re.I):
            return name
    return "table_read"


def verification(checks: list[dict]) -> dict:
    return {"status": "verified" if checks and all(c["ok"] for c in checks) else "unverified",
            "checks": sorted(checks, key=lambda c: c["check"])}


def _check(name: str, ok: bool, detail: str | None = None) -> dict:
    d = {"check": name, "ok": bool(ok)}
    if detail:
        d["detail"] = detail[:500]
    return d


def attendance_verification(att, unresolved: list[str]) -> dict:
    present_ok = att.present_count is not None and att.present_count == len(att.present)
    absent_ok = att.absent_count is None or att.absent_count == len(att.absent)
    return verification([
        _check("present_count_matches_stated", present_ok, f"PRESENT {att.present_count}, {len(att.present)} names read"),
        _check("absent_count_matches_stated", absent_ok and "ABSENT line not found" not in att.reasons,
               f"ABSENT ({att.absent_count}), {len(att.absent)} names read"),
        _check("names_resolve", not unresolved, ("unmatched: " + "; ".join(unresolved)) if unresolved else None),
    ])


def roll_call_verification(rc, roster_unresolved: list[str]) -> dict:
    """Checks from the parser's decision (rc.reasons) plus roster names resolving to officials."""
    failed: dict[str, list[str]] = {}
    for r in (rc.reasons if rc.status != "Verified" else []):
        failed.setdefault(reason_check(r), []).append(r)
    if rc.status != "Verified" and not failed:
        failed["table_read"] = ["no reading passed"]
    if roster_unresolved:
        failed.setdefault("names_resolve", []).append("roster names not in names.yml: " + "; ".join(roster_unresolved))
    checks = [_check(c, c not in failed, "; ".join(failed.get(c, [])) or None) for c in RC_CHECKS]
    if rc.verified_by:
        checks.append(_check("reading_used", True, rc.verified_by))
    return verification(checks)


def source_inconsistent(rc) -> bool:
    """Written rule for G4: a hold is caused by the source document itself when at least two independent readings
    agree on every vote and on the stated tally, and each reports the same contradiction between a member's vote
    mark and the roll call's own ABSENT line. Such holds are reported separately and not counted in G4."""
    if rc.status == "Verified" or len(rc.readings) < 2:
        return False
    if any("sources disagree" in r for r in rc.reasons):
        return False
    sets = []
    for rd in rc.readings:
        contra = {r for r in rd.reasons if "listed absent but has vote" in r}
        if not contra:
            return False
        sets.append(contra)
    return all(s == sets[0] for s in sets)


def motion_verification(mover, seconder, present_ids: set, motion_named: bool) -> dict:
    checks = []
    for role, ref in (("mover", mover), ("seconder", seconder)):
        if ref is None:
            checks.append(_check(f"{role}_resolves", not motion_named, None if not motion_named else "not read"))
            continue
        checks.append(_check(f"{role}_resolves", ref["official_id"] is not None,
                             None if ref["official_id"] else f"unmatched: {ref['raw_name']!r}"))
        if ref["official_id"]:
            checks.append(_check(f"{role}_present", ref["official_id"] in present_ids))
    if mover and seconder and mover["official_id"] and seconder["official_id"]:
        checks.append(_check("mover_differs_from_seconder", mover["official_id"] != seconder["official_id"]))
    return verification(checks)


# ------------------------------------------------------------------ gates

def gates(facts: dict, source_error_ids: set) -> dict:
    """AC-P1 verified rate and G4 skew. Returns the gate block of build/report.json."""
    rcs = facts["roll_calls"]
    n = len(rcs)
    verified = sum(r["verification"]["status"] == "verified" for r in rcs)
    rate = verified / n if n else 0.0
    meetings = {m["id"]: m for m in facts["meetings"]}
    listed: dict[str, set] = {}
    for m in facts["meetings"]:
        for a in m["attendance"]:
            if a["official_id"]:
                listed.setdefault(a["official_id"], set()).add(m["id"])
    rc_by_meeting: dict[str, list] = {}
    for r in rcs:
        rc_by_meeting.setdefault(r["meeting_id"], []).append(r)

    def stats(oid: str, meeting_ids: set) -> tuple[int, int, int]:
        elig = held = src = 0
        for mid in meeting_ids & listed.get(oid, set()):
            for r in rc_by_meeting.get(mid, []):
                elig += 1
                if r["verification"]["status"] != "verified":
                    if r["id"] in source_error_ids:
                        src += 1
                    else:
                        held += 1
        return elig, held, src

    per = {}
    for oid in sorted(listed):
        elig, held, src = stats(oid, listed[oid])
        counted = elig - src
        per[oid] = {"eligible": elig, "held": held, "held_source_error": src,
                    "rate": round(held / counted, 4) if counted else 0.0}
    flagged = []
    for oid, s in per.items():
        if s["eligible"] < MIN_ROLL_CALLS_FOR_SKEW:
            s["peer_median"] = None
            continue
        peers = [p for p in listed if p != oid and listed[p] & listed[oid]]
        rates = []
        for p in peers:
            e, h, sr = stats(p, listed[oid])
            if e - sr:
                rates.append(h / (e - sr))
        med = median(rates) if rates else 0.0
        s["peer_median"] = round(med, 4)
        if s["rate"] > SKEW_FACTOR * max(med, SKEW_FLOOR):
            flagged.append(oid)
    _ = meetings
    return {
        "roll_calls": n, "verified": verified, "held_back": n - verified,
        "held_back_source_error": len([i for i in source_error_ids if any(r["id"] == i for r in rcs)]),
        "verified_rate": round(rate, 4),
        "verified_rate_gate": {"min": VERIFIED_RATE_MIN, "pass": rate >= VERIFIED_RATE_MIN},
        "g4": {"rule": (f"block if an official with >= {MIN_ROLL_CALLS_FOR_SKEW} roll calls has a held-back rate > "
                        f"{SKEW_FACTOR} x max(median rate of officials who sat in the same meetings, {SKEW_FLOOR}); "
                        "holds caused by source-document errors are excluded and reported separately"),
               "skew_factor": SKEW_FACTOR, "skew_floor": SKEW_FLOOR, "min_roll_calls": MIN_ROLL_CALLS_FOR_SKEW,
               "flagged": flagged, "pass": not flagged, "per_official": per},
    }
