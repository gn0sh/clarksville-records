# Code reviews: daylight-national M1

## B7 (b0b5318, fix 027b1fbd) and F4 (ff27469), code-reviewer sonnet/medium, 2026-11-19
- F4 `site/static/us-count.js`: APPROVE. URL exactly `?p=count-<id>&e=true&rnd=`; fetch options equal count.js; id regex
  per 3.1; DNT, GPC, webdriver, non-https, no fetch, bad code each set `available` false and send nothing; guard lines
  equal count.js by test; storage/form reads trapped. Nits: guards in an IIFE read oddly (by design, no change);
  `tests/test_us_count.py` skips without node (CI must have node).
- B7: REQUEST CHANGES, should-fix `b7/req-lookalike-vacuous`: the only lookalike `req-note-budget` sat beside a base
  already holding `note-budget`; mutations (`read_tags` endswith, `_SEAT_TAG` search) survived. Fixed in 027b1fbd
  (LOOKALIKE set against a lean base, req-only lookalike subscribers). Delta re-review: APPROVE, both mutations now fail
  (6 and 1 failures), 19 passed. Ward-number nit left (not needed).
