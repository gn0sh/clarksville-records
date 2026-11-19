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

## B1/B2 (94bdb37, 3428c5d), code-reviewer opus/high, 2026-11-19: REQUEST CHANGES
- must-fix `privacy-withhold/body-name-word-check` (national.py 96-102, 255-259): whole-word denylist and unanchored
  allowlist let "Early Childhood Council", "Childcare Commission", "Schoolboard Commission", "Head Start Policy Council",
  "Junior Council", "Planning Commission", "Civil Service Commission", "Police Pension Board of Trustees" pass. Fix: stem
  denylist, end-anchored allowlist, a test per name.
- should-fix `privacy-withhold/also-cross-layer`: `also` accepts any layer (sdu id onto an items-shown entry).
- should-fix `contract/pagedir-example-stale`: 3.4 example still shows the old Nashville alias pattern.
- should-fix `census-facts/b2-unverified`: codes quoted from memory. Manager verified them via WebFetch (class codes,
  FUNCSTAT, county/place 2020 files for TN, MA, CT, RI, MD, MO, NV, VA) and handed the rows to the engineer.
- should-fix `govflags/line-without-card`: notes must fire when the county id was dropped for any reason; verified:
  independent-city county copies are C7|F, places C7|A; Davidson H6|C; MA/CT/RI counties H4|N.
- nits: legistar official_url host rule (architect to confirm), cross-file hide check, unhashable YAML types,
  BAD_TEXT_RE gaps. Contract changes judged right: Nashville pattern, `digest/tn/<id>.html`, namespaced labels,
  extra refusals, MAX_ANSWER 220000.

## B14 (7ac946b9), code-reviewer opus/high, 2026-11-19: REQUEST CHANGES
- must-fix `national/url-scheme-untrusted/urlsplit-raises`: `https://[x/`, `https://]x/`, NFKC-bad netlocs raise
  ValueError, so one bad outside URL stops a run instead of becoming null.
- should-fix `national/untrusted-size/lone-surrogate` (UnicodeEncodeError at page write),
  `national/url-scheme-untrusted/bidi-in-url`, `national/untrusted-size/items-cap-order` (cap before filter).
- nits: grapheme-safe cut, zero-width/invisible characters, dirty-feed no-mutation test, non-dict feed error type.
- Holds: scheme/host/userinfo/port/backslash cases, Legistar host checks, meeting filter-then-cap, deepcopy, fullmatch.
- Tracking: "called at collection and at build" carried into B3/B4 and the M2 collector.
