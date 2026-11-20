# Code review: Daylight national D1, D2 and national-isolation (519b9c0c..99105673)

Reviewer: code-reviewer (opus/high, read-only), 2026-11-20. Commit 99105673 on claude/project-thread-ysvq9u, docs/reviews/
excluded. Checked against architecture 4.3, 4.6, 11, 12 (12.2 "As built") and ADR 0013 Amendment C.

**Verdict: REQUEST CHANGES.** The must-fix keeps invariant 12 from holding with the switch on (blocks switch-on). No harm
to Clarksville while the switch is off.

## Findings
1. **must-fix `national-isolation/site-checks-read-feed-text`** (N2 key again; first hit since the section 12 re-plan).
   `qa/site_checks.py:2140` check_name_links, `:2183` check_old_brand, `:2211` check_old_daylight_colors read the feed
   text of `digest/<st>/<id>.html`; the brand checks also scan its `.json` as bytes. 12.1 row 6 omits them; B-ISO-6
   exempts only `dates/no-raw-utc-day`. Probe (12.3 #9 harness, switch on, one Legistar body): "Resolution honoring
   A. Example" fails `name-links`; "Paint color #2B4BA5" / "rgb(43, 75, 165)" fail `brand/no-old-daylight-colors`;
   "gnoshcodes-mark-black" fails `brand/no-old-gnoshcodes`. Site checks is a hard step in daily-update.yml, so any
   agenda author can hold the Clarksville deploy. The county route already prints Montgomery County agenda titles that
   may name commissioners. Fix: `without_feed_text` in check_name_links for coming-up pages; skip `digest/<st>/<id>.json`
   in the brand scans and read the .html through `without_feed_text`; architect restates row 6 listing every check that
   reads page text/bytes; extend 12.3 #9 with the four probes in HTML and JSON.
2. **should-fix `national-isolation/refused-file-silent`** (`sitegen/national_copy.py:211-227`). A body file that exists
   but is refused (parse/clean/bind :216, schema :225/:227) gets state `missing`, no `::warning::`, not in
   `national_states`; schema drift would make every Legistar page stale while the run log says `built`/`{}`. The hostile
   sweep asserts `{}`, locking the gap in. Fix: `read_body_file` tells absent from unreadable; sixth word `bad-file` in
   `DEGRADED_STATES` and the D-ISO-9 case list (daily-update.yml:1103); print via `_refused(..., type name)`; update STATE_OF.
3. **should-fix `national-isolation/run-log-contract-untested`**. `collector/__main__.py:510-514` writes `national` /
   `national_states` untested; the shell word list and id regex (daily-update.yml:1102-1103) hand-copy
   `npg.DEGRADED_STATES` and `id_layer`. Fix: cmd_run test with stubbed site_build asserting both keys (as
   tests/test_rpc_daily.py:520 for `rpc`); test parsing the D-ISO-9 case list against `set(npg.DEGRADED_STATES)`.
4. nit `national-observability/no-root-silent`: lookup timeout or unattested head -> every page `missing`, no issue until
   S2b ruling 5's ">20% stale" issue exists. Land it with D-ISO-9 before switch-on.
5. nit: rebuild-only dispatch (daily-update.yml:656) writes no run-log.json; documented, acceptable.
6. nit: `tests/test_national_copy.py:193` name says "stops the build" but only checks copy_feed raises; load-phase stop is
   covered by test_national_pages.py::test_a_covered_entry_without_a_feed_source_is_refused_at_load. Rename or point.

## Checked and holding
- Run-log contract values; `{}` after tier-2 handled via status; off/absent opens nothing; ids/states filtered in shell.
- Three phases: only load-phase NationalBuildError reaches BuildError; tier 1 in build_feeds/build_national; tier 2
  clears digest/ and rebuilds stale; bad council listing degrades that council only; zone_of matches bind_feed.
- Timeouts: daily gate 2+8+3=13 in 14; collect 3+69+2=74 in 75, CLI 60+6+1=67 of 69; every continue-on-error step has a
  shorter step timeout; budget regex exactly 1-360.
- Switch off: fixture site at 519b9c0c vs 99105673 (with RECORDS_NATIONAL_DATA) `diff -r` identical; same with switch on
  and shipped config.
- Test quality: 12 mutations each undoing one fix were all caught.
- Ruff: 93 before and after, none new.

## Test runs
national_isolation/copy/workflow + workflow_lock: 737 passed, 3 failed (environmental: need data/). Other
test_national_*.py with CR_ALLOW_NO_DATA=1: 798 passed, 10 skipped.

## Delta re-review (32936af3..fbf1ba62), 2026-11-20
**Verdict: APPROVE WITH NITS.** Must-fix closed; fix the should-fix before switch-on.
- Closed: `site-checks-read-feed-text` (probes in 12.3 #14, tests/test_national_isolation.py:716-760; rows 6a-6r; digest/feed-text
  check); `refused-file-silent` (`bad-file` for every refused-present case, absent stays `missing`, in DEGRADED_STATES and shell
  list); `run-log-contract-untested` (cmd_run test in tests/test_rpc_daily.py, parity tests test_national_workflow.py:1076);
  rebuild-only no-issue (accepted, D-ISO-13); test name (3ca4dcc7). Kept: `national-observability/no-root-silent` (waits on S2b ruling 5).
- Deviation 1: equal-value attribute blanking and the JSON blanking are sound (feed URLs pass allowed_url so can't equal our
  relative links; `sources` reads hrefs via Page; our JSON fields stay checked). The page-wide replace is not:
- **should-fix `national-isolation/feed-attr-blanks-own-footer`** (qa/site_checks.py feed_text_removed: FEED_ATTR.sub and the
  `words` loop). Footer `<time class="data-as-of" datetime="D">` is blanked when any meeting is on day D (confirmed: FETCH_DAY
  matches 6 -> 3), so `dates/no-raw-utc-day` skips that page's "Data as of". Common (meetings from today on). Low impact (footer
  checked on other pages). Fix: blank only inside templated `<section class="digest-meeting">` blocks (or mark feed dates
  `<time data-feed-date>`); control test: meeting on as-of day + wrong footer day still fails.
- nit `national-isolation/feed-span-substring` (check_digest_feed_text rule iii): span passes if its text is a substring of any
  feed field; compare equality after whitespace normalisation.
- Holding: D-ISO-11 matches 12.6 routes 1-14; D-ISO-12 fails closed in gate, soft in lookup; D-ISO-14 2+8+1 in 11.
- Tests (CR_ALLOW_NO_DATA=1): 995 passed, 2 skipped, 4 failed + 1 error, all needing filled data/.
