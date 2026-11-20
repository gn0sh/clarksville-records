# Code review: daylight-national row 6s (B-ISO-12..15, D-ISO-16..17), a8c5430..e6172fe

Reviewer: code-reviewer (opus/high), 2026-11-20. Fresh review (diff touches CI workflows).

**Verdict: REQUEST CHANGES.** One must-fix (one-line). Everything else holds and is pinned by tests that fail on revert.

## Findings
1. **must-fix `national-isolation/copy-step-raises-on-input`** (sitegen/national_copy.py:184-185 `title_problem`).
   `m.get("title") not in ours` (frozenset) raises `TypeError: unhashable type` for a body file with `title_ours: true`
   and a list/dict title (`[]`, `{}`, `["Meeting"]`); clean_feed/bind_feed pass it through and the schema runs later.
   Reproduced at e6172fe; a8c5430 gives `bad-file (SchemaRefused)`, so a regression. Tier-1 try
   (national_pages.py:452-458) catches it (page stale, build continues), but it breaks the module's "nothing here raises on
   a national input" contract, misses B-ISO-12's `bad-file (TitleNotOurs)`, and logs `adapter-error (TypeError)`.
   Fix: `t = m.get("title")` ... `and m.get("title_ours") is True and not (isinstance(t, str) and t in ours)`; add `[]`
   and `{}` to the title parametrize lists (tests/test_national_copy.py:376) and to test_15a.
2. nit `national-isolation/import-cycle` (national_copy.py:265): call-time import in date_problem works; cleaner to move
   `newest_day`/`_local_date` into sitegen/national.py. Optional.
3. nit `national-isolation/doc-drift`: architecture 12.2 B-ISO-13 says "every covered entry's host_ok.date"; code applies
   it to collected platforms only (correct: directory.yml:14 needs host_ok only off daylight). Update the text.

## Engineer deviations, judged
1. Edge test checked_at moved to 2026-11-18T06:00Z: accept (first instant of host_ok day in America/Chicago).
2. Two unit tests wrapped in digest-meeting sections: accept (required; gained outside-section assertions).
3. Second 15c case: accept; the spec's case passes without the fix, the added case (meeting on the wrong footer day) is
   S2d finding 2 itself.
4. Call-time import: accept (nit 2). 5. host_ok load check for collected platforms only: accept (nit 3).

## Mutation runs (scratch worktree at e6172fe, one at a time)
Page-wide blanking; section opening tag excluded; title check off; checked_at floor off; floor `<`->`<=`; floor UTC day;
load-phase lines_effective check off; load `<=`->`<`; unordered substring span match; outside-section rule (iv) off;
D-ISO-17 `-z "$src"` branch off: every one caught by at least one test.

## Checked and holding
- Row 6s rule 1, every table value: Legistar title_ours title can only be "Meeting" (OURS_TITLES tested equal to
  FALLBACK_TITLE and WITHHELD_TITLE, keys = COLLECTED; collector sets title_ours only for FALLBACK_TITLE,
  legistar_upcoming.py:211). Printed checked_at day >= host_ok.date > lines_effective; provenance bans only
  lines_effective and the day before (qa/site_checks.py:2010). Ids/dates/links blanked only inside sections; source.page,
  review, instants pinned by 15e/15f. meeting_view keeps JSON order, so the ordered rule can't misfire.
- Rule 2: FEED_SECTION needs exact `class="digest-meeting"` and includes the opening tag; autoescaped text can't end the
  lazy match early; no `</section>` blanks nothing (fails safe). Footer, official link and newest line sit outside.
- Clarksville switch-off: fixture builds at a8c5430 and e6172fe byte-identical (diff -r, 95 files).
- Workflows: no `${{ }}` on added lines; only NPATHS/id= strings and the `-z "$src"` branch; permissions and timeouts
  untouched; BODY_FILE_RE used with fullmatch; nested group fine in grep -E; D-ISO-16 test builds the rule from
  GEOID_DIGITS and confirms `{5,10}` gone everywhere.
- ruff check on changed Python files: all passed.

## Tests
`CR_ALLOW_NO_DATA=1 pytest tests/test_national_copy.py tests/test_national_isolation.py tests/test_national_workflow.py
tests/test_digest_site_checks.py`: 406 passed, 0 failed.

Re-review: delta check on finding 1 is enough.
