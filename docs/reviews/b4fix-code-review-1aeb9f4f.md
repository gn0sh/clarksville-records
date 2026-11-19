# Code review of B4 fixes 1aeb9f4f (code-reviewer, opus/high, 2026-11-19): REQUEST CHANGES

1. MUST-FIX `data-off-main/ipub-entry-pins-only-before` collector/tripwire.py:224-225. Duplicate id losing a copy (after[key][0] < copies) is classed `removed` with digest value_view(before[key]); the surviving copy's new value is never pinned, so after listing it can take any value and still pass (reproduced: live rc x twice passed/passed; run1 one copy failed -> listed; run2 one copy tabled-unreviewed -> hits == []). Latent (0 duplicate ids in 4663 facts). Fix: digest = sha256 of canonical {"before": view(before), "after": view(after) or (0,[])} for both kinds; test where surviving copy changes after listing must HIT.
2. SHOULD-FIX `data-off-main/held-issue-stale-fields` daily-update.yml:605: hit issue text still asks for (fact_id, change, listed_on, reason); schema 2.0 needs path and value_sha256; point to the hit line to copy.
3. NIT `main-protect/test-flake-lock-unlink` conftest.py:52: don't unlink the held lock (flock/unlink race); a leftover file blocks nothing.
4. NIT `data-off-main/held-issue-truncation` daily-update.yml:623: head -c 3000 can cut a digest; cut whole lines (head -n).
Holds: S1, S1b, S2 otherwise, N1 (token 16 bytes urandom, fail closed), N2 apart from #1, N3 (CI unaffected). 181 + 2 tests passed, ruff clean.
