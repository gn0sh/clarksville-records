# Weather scenes (PR #92) reviews

## Code review (code-reviewer, opus/high) at 743c94a: APPROVE
1. should-fix privacy-honesty/weather-disclosure config/site.yml:35-38 (Origin header names the site; HTTP cache keeps the answer). Same as security #1.
2. should-fix test-hygiene/weather-unrouted tests/csp_browser.js:33, tests/address_browser.js:51: route api.weather.gov in Playwright tests.
3. nit wx-mapping/blowing-snow sky.js:343 (BLSN/DRSN drew falling snow).
4. nit wx-mapping/rain-showers-word sky.js:310.
5. nit wx-mapping/vicinity-greedy sky.js:348.
6. nit wx-mapping/vis-zero sky.js:370.
7. nit test name test_analytics.py:46; style.css:84 indent.
Checked: NWS schema mapping, timer/abort, failure modes, CSP, no-network guards, header clipping, reduced motion. pytest 212+222 passed on touched files; full suite stopped at 37% (time limit) with no failures.

## Security review (security-engineer, opus/high) at 743c94a: OK WITH FOLLOW-UPS
1. weather-privacy/disclosure-overclaims (low) config/site.yml:18-21: "nothing kept" vs HTTP cache; Origin header names the site. Fix the wording.
2. weather-availability/cors-unverified (low) sky.js:487: verify ACAO and Cache-Control on a live response (device check).
3. weather-abuse/unbounded-body (low) sky.js:488: optional Content-Length cap ~64 KB.
4. weather-csp/landing-uses-global-cfg (info) views.py:1653.
Checked sound: CSP on all page types (landing, digest/national, alerts, counter), no DOM sinks from response data, data-weather URL validated at build, credentials omit + no-referrer pinned by test, hostile JSON type-checked and capped, guards (fetch pinned to one use, other scripts still ban fetch). Ran test_weather, test_csp, test_moon, test_national_pages, test_address_box: 196 passed.
Residual (owner's choice, disclosed): NWS sees IP and time of every page view.

Fixes for all items except security #2 (live CORS check after deploy, in docs/design/daylight/README.md) and #4 (info): 27b3047.

## Delta re-review (code-reviewer, opus/high) of 27b3047: APPROVE
All keys fixed; 64 KB cap tested at 65536/65537, no header, non-number. Nits left: wx-mapping/vicinity-one-word (sky.js:354, text-only "Rain Showers in Vicinity" draws rain; drop the clause to the last "and"/comma), lint/e501 tests/test_digest_site_checks.py:131. 196 passed on the six touched test files; pages build OK.
