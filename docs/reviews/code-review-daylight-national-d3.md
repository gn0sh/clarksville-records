# Code review: Daylight national D3 (18bace6 vs c112d34)

Reviewer: code-reviewer (opus/medium), 2026-11-19. Verdict: **APPROVE with nits** (no must-fix).

Checked: no path in collector/national sends a request (get, limit_hosts, robots, limit_tenant) for an entry without a
valid host_ok: `run()` checks first (run.py:347), `collect()` before data_root (run.py:486), `read_body` on its own
(legistar_upcoming.py:381). Shared predicate `host_ok_problem` (national_guards.py:111) matches the old loader check
step for step; config/national/directory.yml unaffected. Tests prove zero fetcher touches and no files written;
mutation check: removing run()'s check fails 9 tests, read_body's fails 1. 409 passed.

Nits (`national/r5-not-enforced`):
1. tests/test_national_run.py daylight/no-platform test did not assert `net.calls == []`. Fixed by manager.
2. collect()'s duplicate check: comment added saying it is deliberate. Fixed by manager.
3. sitegen/national.py:407-410 loader keeps its own isinstance check for error wording. Left as is.
