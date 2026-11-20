# Security review S2d: national-isolation fixes, 32936af3..fbf1ba62

Reviewer: security-engineer (opus/high), 2026-11-20. Read-only at fbf1ba62; probes in a `git archive` scratch copy.
Scope: D-ISO-10..14 (both workflows, docs/ops/u3-positive-control.md), B-ISO-8..11 (site/templates/digest/body.html.j2,
qa/site_checks.py, sitegen/national_copy.py, sitegen/national_pages.py, collector/__main__.py). Against 12.1 rows 6a-6r,
12.2 "As built, v2", 12.6, section 11.

**Verdict: PASS WITH FINDINGS.** No critical/high/medium. Two LOW (row 6 of `national-isolation`), three nits.
**Release: OK WITH FOLLOW-UPS.** Nothing blocks the merge (switch off, byte-identical). Finding 1 (and 2) land before
`national.enabled: true` with a collected Legistar entry, with S2c finding 1, S2b ruling 5 and 12.3 #12.
Tests: test_national_isolation/copy/workflow 312 passed. Switch-off fixture build 32936af3 vs fbf1ba62 `diff -rq`
identical; on with shipped config also identical.

## Findings
1. **LOW `national-isolation/feed-value-outside-wrapper`.** body.html.j2:29, :22; qa/site_checks.py:220 (`feed_texts`
   drops title when `title_ours`); sitegen/national_copy.py:257-273 (copy_feed never checks `title_ours`), :210-219
   (`instant_ok` lower bound = epoch). Two body-file values print outside `<span data-feed>` unblanked: (a) a meeting
   `title` with `title_ours: true`; (b) `checked_at` as a day in words in `body.newest`. Proven: a file that passes copy
   (`built`, `{}`) with `title_ours: true, title: "Paint color #2B4BA5"` fails brand/no-old-daylight-colors (.html+.json);
   "gnoshcodes-mark-black" fails brand/no-old-gnoshcodes; "a request to present the budget" fails provenance;
   `checked_at: "2022-08-30T16:00:00Z"` fails provenance. Not reachable by an agenda author (collector sets
   `title_ours = comment is None`; checked_at is the run stamp); reachable by a buggy/tampered body file, which holds the
   Clarksville deploy while the switch is on. Availability only. Fix (backend): copy_feed refuses a meeting as `bad-file`
   when `title_ours` and title != platform FALLBACK_TITLE; bound `instant_ok` below by entry `host_ok.date` (or blank the
   checked_at day words); 12.3 #14 probes for both. Architect: row 6s, every feed-derived value printed outside a span is
   validated or blanked.
2. **LOW `national-isolation/exemption-blanks-own-text`** (same as code review delta should-fix
   feed-attr-blanks-own-footer). qa/site_checks.py:261-263: FEED_ATTR.sub and date-words replace run page-wide. A meeting
   on the "Data as of" day blanks the footer datetime and words, so `dates/no-raw-utc-day` skips the footer (probe: wrong
   footer day passes with a meeting on that day). Also our `official` links lose href in check text when a feed
   `meeting_url` equals the directory `official_url` (common on Legistar). Fix: blank only inside
   `<section class="digest-meeting">`; test meeting on as-of day + wrong footer day still fails.

## Nits
a. `digest/feed-text` binding loose (qa/site_checks.py:2829-2831): substring match, empty spans pass, order unchecked.
   Require exact equality after unescape + whitespace normalisation; spans <= fields. backend.
b. Push job validate regex (national-update.yml:319), tree helper NPATHS and schema still allow `[0-9]{5,10}`; harmless;
   one exact rule from id_layer. devops.
c. daily-update.yml:346-347 warning text misleads when jq select drops every certificate; reword. devops.

## S2c status
- Finding 1 schedule-rerun-no-cap: closed (national-update.yml:199-202; every 12.6 route checked; truth-table test
  tests/test_national_workflow.py:83,162; skipped collect skips push).
- Nit a closed (jq names checked against sigstore-go certificate Summary/Extensions; gate fails closed, lookup soft;
  40-hex + `grep -Fxq --`). Nit b closed (finding 2 is a new gap in the replacement). Nits c, d, e closed.
- Carried gates still open: S2b ruling 5, 12.3 #12.

## Checked and holding
- FEED_SPAN blanks only bare template-emitted spans; our labels never inside one (11 probes on PAGE and about.html).
- own_text/own_bytes touch only digest/<st>/<id>.html|.json; Clarksville read raw; a feed can't reach another
  government's page (gov_json_of reads the page's own JSON).
- `sources`/`links` read raw hrefs. Binding fails closed (no/bad JSON -> every span alien; spans in comment/script fail;
  data-feed off coming-up pages fails; problems print indices/counts only).
- Agenda-author route closed (11 probes in every feed field, links, ids, dates = baseline).
- feed_json_without_text blanks every free-text and URL field; unparseable JSON scanned whole.
- bad-file: stale_feed, id + fixed word + class name only, never raises; withheld/date order kept; no new withheld path.
- D-ISO-10 id regex + six words held equal to id_layer/DEGRADED_STATES by test; B-ISO-10 run-log contract tested.
- Workflows: no `${{ }}` in run:, permissions unchanged, static jq, every continue-on-error step timed.

## Ledger keys
`national-isolation/feed-value-outside-wrapper`, `national-isolation/exemption-blanks-own-text` (LOW, row 6).
Recommend counting with the code review delta should-fix as one hit; fix in-band (architect row 6s + backend); a
switch-on gate, not a release blocker. No new hit in national-budget or data-prov.
