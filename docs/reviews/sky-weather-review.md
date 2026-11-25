# Review: the sun and moon show the weather (PR 97)

Branch `claude/sky-weather-sun-moon`. Reviewer: code-reviewer (opus). Security review not required: front-end drawing only; the weather fetch to api.weather.gov is unchanged from PR 92 (already reviewed).

## Round 1, 4eb0608: APPROVE WITH NITS
Two should-fix items and nits, all fixed: moon colours now differ from the weather drawing (wx-visible/light-moon), the moon no longer jumps when the weather changes (moon-place/jump-on-weather), a low sun stays above the horizon (wx-host/sun-at-horizon). Commits 8045596, 8f3bb9f, e12c29c. The front-page alignment fix (landing-grid/digest-line-row) came in from PR 96.

## Since
Merged PR 96 (reviewed separately, docs/reviews/launch-polish-review.md) and main through PR 95; no weather code changed after the review.

## Preflight (head b23db1d)
pytest 9045 passed, 547 skipped, 4 failed (the `[sh]` Ctrl-C timing tests; fail only under full-suite load, pass alone here and on main; no file of this PR). Weather branch alone (b5178a8): 9036 passed, 0 failed. Pages build + export + `qa.site_checks --no-browser`: 38 checks, PASS.

Still unverified: live api.weather.gov CORS from the real site.
