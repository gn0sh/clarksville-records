# Reviews: Digest browser test gate (b2d55c7, branch claude/digest-browser-test-gate)

Why: production daily-update.yml (CI set, no Playwright) failed every run since Nov 20 on
tests/test_national_browser.py::test_digest_privacy_in_a_browser, blocking Clarksville deploys. Fix: a missing browser
fails only when REQUIRE_BROWSER=1 or (CI and national.enabled); otherwise it skips. Test-only.

## Code review (sonnet/medium, 2026-11-21): APPROVE WITH NITS
Gate correct; reads config.SITE["national"]["enabled"] like the build (national_pages.enabled(), strict bool, so no
silent-skip route with the switch on). Parametrized gate test covers all branches. Nits:
1. `national-gate/divergent-parse`: call national_pages.enabled() instead of the .get chain.
2. `national-gate/wiring-untested`: test that _need_browser fails/skips per _browser_required.
3. Nothing enforces Playwright install when the switch flips (comment only).

## Security (opus/medium, 2026-11-21): PASS WITH FINDINGS (low only; release OK with follow-ups)
Holds: same switch source, no env override; strict enabled(); qa.site_checks fails any digest/ file while off;
national-update.yml never builds pages; no PR workflow path to production. Findings:
1. Low `digest-privacy-gate/no-pr-ci`: preflight docs should require REQUIRE_BROWSER=1 output for PRs touching national/digest.
2. Low `digest-privacy-gate/switch-on-blocks-clarksville`: switch on without Playwright in daily-update fails all deploys.
3. Low `digest-privacy-gate/off-ci-builds`: the Nov 20 private preview was a local switch-on build, screenshots only,
   never deployed (manager confirms); privacy run not proven for it, none needed.
Switch-on prerequisites (R1): (a) daily-update installs pinned Playwright+Chromium before Tests; (b) switch-on PR shows
`REQUIRE_BROWSER=1 pytest tests/test_national_browser.py` passing; (c) optional: gate via national_pages.enabled().
