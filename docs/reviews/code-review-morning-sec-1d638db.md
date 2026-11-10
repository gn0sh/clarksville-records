# Code review: morning-note security fixes, 1d638db

Target: origin/claude/sqv6p9-morning-sec, fa9e9b0..1d638db (4 commits, 16 files, +589/-28). Reviewed 2026-11-10.
Scope: correctness, maintainability, tests. Security was reviewed separately (security-review-morning-2b4796b.md, delta 1d638db) and is not repeated.

## Verdict: APPROVE WITH NITS (one should-fix as a follow-up; nothing blocks the merge)

## Most serious problem
**source-link-always/feed-drop-silent** (should-fix) sitegen/feeds.py:195-200 and :307; sitegen/morning_page.py:153-159; qa/site_checks.py:1283-1287.
- The fix drops a source URL that is not https, and nothing reports it. The feed entry and the preview entry are still published, with no source link.
- qa/site_checks.check_feeds only checks a `rel="related"` link when one exists. Tested: I removed all 12 source links from the fixture build's feeds and check_feeds returned no problems.
- Before this change a bad RPC URL reached the feed and QA failed it ("not a fetched source document"). Now the same data error passes silently, on a site whose rule is that every fact links to its source.
- Fix: in check_feeds, fail any entry without a `rel="related"` link (every entry in today's fixture feeds has one). Optionally have build_feeds/preview record dropped URLs in the build report. Add a test that a build with a bad RPC source URL fails qa.site_checks.
- Reach today: needs a malformed URL in the RPC facts; no committed data has one. That is why it is a follow-up and not a blocker.

## Other findings
- **seat-consent/state-recompute-on-submit** (nit, low confidence) site/static/morning.js:115-117. The seat fields' disabled state is recomputed only on `change` events and once at load. A browser that restores form state after the deferred script ran, without firing `change` (reload or history navigation), could show the box unticked while the fields stay enabled. Not reproduced; the Playwright test covers untick, re-tick, district-only and no-seats, not reload. Fix: also call updateNote on the form's `submit` and on `pageshow`. Only matters once enabled.
- **privacy-text/label-wording-drift** (nit) config/site.yml:117-120. `seats_sent` and `method_sent` quote the box's label ("Include my saved seats") as literal text, separate from `seats_include`. tests/test_morning_page.py:472 pins the literal for today's wording only. Fix: a `{box}` placeholder filled from seats_include in morning_page.privacy(), or a test that both sentences contain seats_include without its colon.
- **href-scheme/duplicate-helper** (nit) sitegen/feeds.py:195 and sitegen/morning_page.py:153. Two near-identical helpers, each with a function-level import of build._is_https_uri to dodge a circular import. Fix: move _is_https_uri to a leaf module (sitegen/config.py or a small urls module) and keep one helper.
- **qa-constants/mixed-sourcing** (nit) qa/site_checks.py:81 and :1193. PER_BODY_FEEDS is now imported from the build, while CONTRACTS_FEED is restated as a literal beside it (a test pins it). Either is fine; the comment at :1126 still says QA restates rather than imports. One line saying which rule applies would do.
- Known open item, unchanged: morning-security/qa-formaction-gap (low) qa/site_checks.py:439.

## What I checked and found sound
- form_origin (morning_page.py:46-57): None for a non-string, any shape outside morning._HTTPS, and when not enabled; tests cover bad actions and a good one.
- privacy() and the templates: `site["morning_note"]` is always set in build() (build.py:462), so StrictUndefined cannot trip on index/method; off build keeps the old sentences, enabled build replaces them; tests cover both states and that the text comes from config. New page keys are required by morning.PAGE_KEYS and present in config/site.yml and the architecture doc.
- Seat box: no `name`, starts hidden, shown only when seats exist; seatPost needs `include === true`; fields stay disabled without JS. `.mn-card [hidden]` (style.css:905) keeps the row hidden despite `.mn-check { display: flex }`.
- bad_scheme (site_checks.py:507-512): probed javascript:, mixed case, leading control char, tab inside, mailto, tel, `C:/x` (flagged); relative paths, `#a:b` fragments and `HTTP://` are not flagged. The report.html mailto exemption still runs first.
- check_external allowance: exact action match, alerts.html only, exact CSP list; off state is unchanged plus stricter scheme checks.
- PER_BODY_FEEDS: feed["file"] is "feeds/topic-rezoning.xml", so `in PER_BODY_FEEDS` selects the same feed as the old kind/key test; test proves the build reads the constant.
- Finance sources: known only to feeds/topic-contracts.xml; test proves another feed linking one fails.
- Committed config keeps `enabled: false` (test_committed_config_keeps_email_off).

## Tests and lint (scratch worktree /tmp/rv-sec, removed afterwards)
- tests/test_alerts.py + tests/test_morning_page.py: 153 passed, 0 skipped (node and Playwright tests ran), 9.8 s.
- tests/test_morning.py, test_csp.py, test_qa_tools.py, test_site_links.py, test_your_seats.py, test_rpc_pages.py, test_site_review_fixes.py: 177 passed, 0 skipped, 228 s.
- ruff on the 7 touched Python files: clean at 1d638db and at fa9e9b0. (ruff over all of sitegen, qa, tests reports 32 errors, all in files this diff does not touch.)
- Not run: the full suite, collector/tests, and a full qa.site_checks run on a real build.

## Assumptions
- A missing source link on a published entry counts as a defect QA should catch (from the repo's "every fact linked to its source document" rule).
