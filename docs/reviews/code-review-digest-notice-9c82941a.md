# Code review: Digest pages' unofficial notice (9c82941a)

Reviewer: code-reviewer (sonnet/medium), 2026-11-21. Verdict: **APPROVE WITH NITS**.
Why: Brian noticed the Digest preview said "not affiliated with" the Clarksville bodies; Digest pages now say "any
government it covers". Clarksville pages unchanged (checked in a switch-on real-data build: index.html keeps the
Clarksville notice, digest/index.html shows the digest notice).

Checked: Pages.__init__ (sitegen/national_pages.py:575-578) swaps on shallow copies, no write to config.SITE or the
load result; only footer_notice, header tag and meta description/og:description reach digest pages; site_checks stays
strict for non-digest pages and now fails a digest page with the Clarksville notice; wording in config.

Nits (carry into the switch-on PR):
1. qa/site_checks.py:3084 `unofficial/loop-var-shadow`: rename in-loop `notice` to `want`, drop the restore line.
2. sitegen/national_pages.py:577 `unofficial/short-overridden`: `short` set to the full notice; drop or add `digest_short`.
3. tests/test_national_pages.py:102 `unofficial/no-mutation-test`: assert config.SITE["unofficial"] unchanged after a build.
4. tests/test_national_pages.py:113 `unofficial/test-vacuous-bodies`: acceptable as written.

Tests: test_national_pages + isolation + digest_site_checks 228 passed, 2 skipped (CR_ALLOW_NO_DATA=1);
test_unofficial + test_unofficial_first_screen + test_workflow_lock 552 passed (with data/).
