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
- B14 delta re-review (0e325282): APPROVE, all 7 fixed, 149 passed. Nits kept open, accepted by manager: U+200C/200D
  are stripped (`national/untrusted-size/zwj-stripped`; US agenda text rarely needs them; revisit if a covered
  government publishes in a script that does), and a flag emoji can split at the 2,000 cut (marked `cut` anyway).

## B1/B2 delta re-review (81b02a6d, aaafec29), code-reviewer opus/high: APPROVE with two should-fixes
- Findings 1-8 fixed (9 at 0e325282); 189 passed; census rows agree.
- should-fix `privacy-withhold/body-name-word-check`: student-civics names ("Mock City Council", "Model County
  Commission", "Shadow City Council", "Pre-K City Council", Cyrillic homoglyph "Yоuth City Council") still pass.
- should-fix `privacy-withhold/body-name-false-refusal`: real places (College Station, Kidder County, ...) and real
  bodies ("Board of Commissioners", "County Legislature", "Selectboard") can never be shown, with no override.
- Manager decision: replace the allowlist heuristic with a code-reviewed `SHOWN_REVIEWED` (gov id, body_name) table as
  the primary control; keep the stem denylist and a non-ASCII refusal as a fail-closed second guard.
- Open for the architect: `contract/legistar-official-url`.

## B3 (baf0d3d3), code-reviewer opus/high: APPROVE (4 should-fix, 3 nits, sent back for fixing)
- Privacy-withhold holds: `_shown` reads only the directory `items` field; withheld items never read; schema allOf
  refuses items on withheld meetings; errors and counts carry no text. 180 passed on a clean archive (no skips).
- should-fix `tests/real-data/silent-skip`: real-data tests would all skip silently after the ADR 0011 data move.
- should-fix `national/council-misattribution`: any council body_key gets Clarksville's inputs.
- should-fix `council-listing/rules-drift`: re-implements `days.scheduled_cards` row rules via private `_CALLED_OFF`.
- should-fix `tests/cap-order`: cap test checks only the length.
- nits: cancelled listing vs facts meeting, refused URL labelled not-posted, 4.3 signature drift.
- SHOWN_REVIEWED delta (d3310033): REQUEST CHANGES. Closed: body-name-word-check, body-name-false-refusal.
  must-fix `privacy-withhold/reviewed-pair-unbound-source`: the reviewed pair pins only (gov, body_name); switching the
  entry to platform legistar with another client/body_id, or another `daylight.body`, still loads `items: shown`.
  nit `privacy-withhold/alias-on-shown`: `also` ids on a shown entry attach other governments' cards to it.
  Loop limit: this family has been hit repeatedly after section 11; architect re-plan (opus/xhigh) runs before the fix.

## F1 (1ad67c9b) and F5 (1eb3d584), code-reviewer opus/high: REQUEST CHANGES
- must-fix `national/csp-jsonp-gadget` (new hole): geo-frame.html doesn't check it is sandboxed; an outside site can
  embed it unsandboxed and drive the Census JSONP in our origin. Fix: bail unless `self.origin === "null"` and
  `parent !== self`.
- should-fix `contract/school-order` (UX order elementary, secondary, unified), `governments/show-rule` (a `show: true`
  state rule would keep N/F/S units; fail closed), `docs/contract-drift` (4.1, 3.3, gov-flags comment).
- nits: escape bidi characters in BAD_TEXT and add U+061C; fixture is a reconstruction, re-record before R1; stored id
  regex looser than layerOf (F2 renders through layerOf).
- Holds: frameMessage rejects (source, origin, type, size, JSON), lookup ordering and cleanup, single answer, callback
  fixed, address never in URL/title/history/Referer, CSP hash over the exact inlined text, prototype keys, storage
  hostile values, all classification cases (Clarksville, CT, MA, Richmond, Baltimore, Nashville, RI).
- F1/F5 delta (323a4d9c): APPROVE, all 7 closed; frame guard could not be bypassed (allow-same-origin, unsandboxed,
  top level, nested/srcdoc, old browsers fail safe). New nit for the backend: `load_gov_flags` should refuse
  `show: true` state rules (the browser now ignores them); also fix the stale LAYERS comment in sitegen/national.py.
