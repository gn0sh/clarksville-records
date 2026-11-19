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
- B3 delta (7eff9acb): APPROVE, all 7 fixed, 63 passed with 0 skips. days.py `calendar_rows` refactor checked against
  the old loop on 214 build days (2025-2029, two windows): 0 mismatches.

## B4 (a10cc2eb), code-reviewer opus/high: REQUEST CHANGES
- Verified: switch OFF byte-identical to main (fixture and real-data builds, `diff -rq` clean incl. pages.js, header,
  footers). Privacy-withhold: no leak (HTML/JSON only from bound feed; writes after all checks; sentinel sweeps real).
  CSP per section 6; Census only in the frame CSP; autoescape on; embed_json for data blocks; no ICS/Atom.
- must-fix `national-freshness/checked-at-is-first-fetch`: `checked_at` is the newest first-fetch date, so a quiet week
  says "We couldn't check this government this week" (real build, county page) although the daily job checked.
  Manager decision: M1 shows "Newest record we have: {date}" and drops stale claims; a real check stamp comes in M2 (C3).
- should-fix `national-pages/body-from-feed-not-directory` (fallback URLs and allowlist re-check from the feed, not the
  entry; `href=""` possible), `national-pages/morning-gate` (morning-note link on every covered page; UX says TN only).
- nits: enabled() outside try; `body.no-time` undocumented draft; test_header regex; index_csp duplicates views.csp.
- B4 delta (309d957a): APPROVE. Switch OFF byte-identical to main 1922fda3 in three builds (fixture pages, real-data
  preview, real-data pages). Freshness, links-from-entry and morning gate closed; no `href=""` in the on build.
  Note: JSON `checked_at` holds the newest record's first fetch; M2/M4 must not print it as "last checked" until C3.

## F2 (73893f19, 6d77211a), code-reviewer opus/high: APPROVE with one should-fix
- should-fix `national-storage/forget-then-late-write`: Forget during an in-flight post/count lets the key be rewritten
  when the promise resolves (reproduced in Chromium).
- nits: Try again moves focus twice; second post possible after Cancel + reopen; election-office line missing (now in
  UX v1.2); "Request the ones you want" without a form; saved list ignores later gov-flags hides.
- Held in Chromium with all outside hosts stubbed: address only in the Census request (not URL, title, history,
  Referer); post body exactly email + own/ticked tags; native fallback clean; counter guards; double submit; hostile
  stored values drawn as text; timeout; failed post stores nothing; no CSP violations; one focus move per result.
- F2 delta (013f4d66): APPROVE; race closed (storage stays empty after Forget + late resolve); new links can't carry the address. Nit kept: card B can tick card A while A is sending (duplicate tag, harmless).

## F3 (6f3de179), code-reviewer sonnet/medium: APPROVE with one should-fix
- Mutations caught: extra post field, extra storage key, page title holding the street, address in the URL.
- should-fix `tests/browser-silent-skip`: the hook skips silently without node/Playwright; fail when CI or
  REQUIRE_BROWSER is set, and assert the node summary shows failed 0 with checks run.
- nits: STOP list drops "main"/"street"; CSP violations also seen via console text only.
- F3 fix (cherry-picked as HEAD after 6f3de179): manager verified pass with Playwright and fail (not skip) with REQUIRE_BROWSER=1 and no node.

## digest.css + links.yml (a76cf74b), code-reviewer sonnet/medium: APPROVE
- digest.css only on digest pages and only copied when on; style.css untouched; links.yml strict (https, known keys,
  null allowed); URLs reach #digest-config via allowed_url; CSS matches design 0a; no outside hosts; CSP unaffected.
- nit (open, low): the contrast figures live in a CSS comment; a token-pair contrast test would catch future changes.
