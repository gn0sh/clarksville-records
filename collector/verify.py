"""Verifier (architecture "Verifier"; spec P1-P4, G4, AC-P1).

Every attendance section, roll call and motion gets {status, checks[{check, ok, detail}]}. A fact is verified only
when every check passes. The parser's P2 readings (collector/parse.py) supply the per-reading reasons; this module
names them as checks, adds the name checks against data/names.yml, and computes the run's gates.
"""
from __future__ import annotations

import re
from statistics import median

from .config import MIN_ROLL_CALLS_FOR_SKEW, SKEW_FACTOR, SKEW_FLOOR, UNIFORM_SHARE_REVIEW, VERIFIED_RATE_MIN

# parser reason text -> named check (first matching pattern wins)
REASON_CHECKS = [
    (r"no roster|attendance header not verified", "roster_available"),
    (r"inside an earlier meeting|boundaries uncertain", "in_meeting_record"),
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


def motion_verification(mover, seconder, present_ids: set, motion_named: bool, context: dict | None = None) -> dict:
    """context (attribution/motion-ignores-context): {"attendance_verified", "in_meeting_record",
    "motion_precedes_vote"} -> (ok, detail). A motion is verified only when its meeting's attendance is verified,
    its vote sits in that meeting's own minutes, and its sentence leads straight into the vote it is filed with."""
    checks = [_check(name, ok, detail) for name, (ok, detail) in sorted((context or {}).items())]
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

class HeldCountError(AssertionError):
    """The held-back count invariant failed: a bug, never a gate result."""


def attendance_shown(m: dict) -> bool:
    return m["attendance_status"] == "extracted" and m["verification"]["status"] == "verified"


def listed(m: dict, official_ids: set) -> frozenset:
    """Architecture "Invariant: held-back counts": the distinct resolved official ids in a shown attendance, present
    and absent. Only the resolved ids are used; no name normalising, aliases or merge rules."""
    if not attendance_shown(m):
        return frozenset()
    return frozenset(a["official_id"] for a in m["attendance"] if a["official_id"] in official_ids)


def gates(facts: dict, source_error_ids: set) -> dict:
    """AC-P1 verified rate and G4 skew, following "Invariant: held-back counts". Returns the gate block of
    build/report.json."""
    rcs = facts["roll_calls"]
    n = len(rcs)
    verified = sum(r["verification"]["status"] == "verified" for r in rcs)
    rate = verified / n if n else 0.0
    oids = {o["id"] for o in facts["officials"]}
    listed_by_meeting = {m["id"]: listed(m, oids) for m in facts["meetings"]}
    meetings_of: dict[str, set] = {o: set() for o in sorted(oids)}
    for mid, people in listed_by_meeting.items():
        for o in people:
            meetings_of[o].add(mid)
    rc_by_meeting: dict[str, list] = {}
    for r in rcs:
        rc_by_meeting.setdefault(r["meeting_id"], []).append(r)

    def is_held(r):
        return r["verification"]["status"] != "verified"

    eligible_unattributed = held_unattributed = 0
    held_attributed_once = 0
    for mid, group in rc_by_meeting.items():
        if listed_by_meeting.get(mid):
            held_attributed_once += sum(is_held(r) for r in group)
        else:
            eligible_unattributed += len(group)
            held_unattributed += sum(is_held(r) for r in group)

    def stats(o: str, within: set) -> tuple[int, int, int, int]:
        """(eligible, held, eligible for the rate, held for the rate) over o's shown meetings in `within`.
        Source-document-error holds are left out of the rate only, for everyone listed alike."""
        el = he = rel = rhe = 0
        for mid in meetings_of[o] & within:
            for r in rc_by_meeting.get(mid, []):
                el += 1
                he += is_held(r)
                if r["id"] not in source_error_ids:
                    rel += 1
                    rhe += is_held(r)
        return el, he, rel, rhe

    everywhere = set(listed_by_meeting)
    per = {}
    for o in sorted(oids):
        el, he, rel, rhe = stats(o, everywhere)
        per[o] = {"eligible": el, "held": he, "held_source_error": he - rhe,
                  "rate": round(rhe / rel, 4) if rel else None, "peer_median": None}
    flagged = []
    for o, st in per.items():
        if st["eligible"] < MIN_ROLL_CALLS_FOR_SKEW or st["rate"] is None:
            continue
        rates = []
        for p in sorted(oids - {o}):
            if per[p]["eligible"] == 0 or not (meetings_of[p] & meetings_of[o]):
                continue
            _, _, rel, rhe = stats(p, meetings_of[o])
            if rel:
                rates.append(rhe / rel)
        med = median(rates) if rates else 0.0
        st["peer_median"] = round(med, 4)
        if st["rate"] > SKEW_FACTOR * max(med, SKEW_FLOOR):
            flagged.append(o)
    held_total = n - verified
    # cross-checks (not restatements of the sums above): every roll call belongs to a meeting in the facts, and
    # the held count recounted from the checks themselves equals the count from the status field
    orphans = sorted(r["id"] for r in rcs if r["meeting_id"] not in listed_by_meeting)
    if orphans:
        raise HeldCountError(f"roll calls of no meeting in the facts: {orphans[:5]}")
    held_by_checks = sum(1 for r in rcs if not r["verification"]["checks"]
                         or not all(c["ok"] for c in r["verification"]["checks"]))
    if held_by_checks != held_total:
        raise HeldCountError(f"status says {held_total} held, the checks say {held_by_checks}")
    for mid, people in listed_by_meeting.items():
        h = sum(is_held(r) for r in rc_by_meeting.get(mid, []))
        if any(stats(o, {mid})[1] != h for o in people):
            raise HeldCountError(f"officials listed at {mid} got different held counts")
    held_src = sum(1 for r in rcs if r["id"] in source_error_ids and is_held(r))
    # holds at meetings whose attendance is not shown count for no official, so G4 cannot see them: report how
    # large that share is and which meetings carry it (reviewer finding neutrality/g4-blind-to-uniform)
    uniform_share = round(held_unattributed / held_total, 4) if held_total else 0.0
    unshown = []
    for m in sorted(facts["meetings"], key=lambda m: m["id"]):
        if listed_by_meeting.get(m["id"]):
            continue
        held_here = sorted(r["id"] for r in rc_by_meeting.get(m["id"], []) if is_held(r))
        unshown.append({"meeting_id": m["id"],
                        "attendance": "not_extracted" if m["attendance_status"] != "extracted" else
                        ("under_review" if not attendance_shown(m) else "lists_no_official"),
                        "held_roll_calls": held_here})
    review_needed = uniform_share > UNIFORM_SHARE_REVIEW
    status = "fail" if flagged else ("review needed" if review_needed else "pass")
    return {
        "roll_calls": n, "verified": verified, "held_back": held_total, "held_back_source_error": held_src,
        "verified_rate": round(rate, 4),
        "verified_rate_gate": {"min": VERIFIED_RATE_MIN, "pass": rate >= VERIFIED_RATE_MIN},
        "g4": {"rule": (f"block if an official with >= {MIN_ROLL_CALLS_FOR_SKEW} eligible roll calls has a held-back "
                        f"rate > {SKEW_FACTOR} x max(median rate of officials who sat in the same meetings, "
                        f"{SKEW_FLOOR}). Eligible = roll calls at meetings whose verified attendance lists the "
                        "official (architecture 'Invariant: held-back counts'); source-document-error holds are left "
                        "out of the rates only"),
               "skew_factor": SKEW_FACTOR, "skew_floor": SKEW_FLOOR, "min_roll_calls": MIN_ROLL_CALLS_FOR_SKEW,
               "flagged": flagged, "pass": not flagged, "status": status, "review_needed": review_needed,
               "uniform_share": uniform_share, "uniform_share_review_above": UNIFORM_SHARE_REVIEW,
               "meetings_attendance_not_shown": unshown, "per_official": per,
               "held_total": held_total, "held_unattributed": held_unattributed,
               "eligible_unattributed": eligible_unattributed},
    }
