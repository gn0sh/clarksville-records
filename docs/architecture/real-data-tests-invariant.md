# real-data-tests invariant (loop rule re-plan, 2026-11-18)
software-architect, 2026-11-18. Problem family `real-data-tests/`, second hit, so the invariant and every consumer
are stated before the fix (playbook loop rule).

- Hit 1 (run 44189282077): a new 2026-10-01 attendance list became the latest; tests that read "the latest list" as
  2026-07-06 failed. PR #32 (b5a3638) cut the live data at 2026-07-06 (`_until`, `_at`).
- Hit 2 (run 44204467365, at b5a3638): the same collection also read the 2026-07-02 minutes, an EARLIER list that
  names Claunch, so "last listed 2026-06-22" read "2026-07-02" even after the cut. Cutting by date cannot pin the past:
  late-posted minutes add lists before the cut. `pytest -x` stopped there, hiding whatever else would fail.

Each hit blocked the whole daily update (no data committed, no deploy), though nothing was wrong with the data.

## Why it happens
The daily update (`.github/workflows/daily-update.yml`, update job) collects into `data/` and then runs
`python -m pytest -q -x` on that same checkout. Every test that opens a file under `data/` (directly, or through a
real build, a default config path or a shared fixture) reads today's collection, not the data the test was written
against. The update job's checkout is `actions/checkout` with its default `fetch-depth: 1` (shallow, no history), so a
test cannot read "data/ at commit X" from git.

## The invariant
**I-live.** A test may read `data/` as collected (live) only if what it asserts holds for every valid growth of the
records, that is for any mix of:
1. new meetings, lists, roll calls, items, sources, books, cases, bids after the latest one;
2. records dated BEFORE the latest one, collected late (minutes posted late, a meeting added to a listing);
3. new members, officials, seats or funds;
4. a deliberate correction or re-read of an existing record (new bytes of a re-posted document: the shrink guards of
   ADR 0006 keep or flag it, they do not freeze it).

Such a test states a rule over the whole file ("every member in the latest list holds their last printed ward",
"every committed transcript matches its meeting", "every fund has a page") or derives its expected values from the
live file itself. These tests are the point of running the suite on fresh data: their failure means the data about to
be published breaks a rule, and the update should stop.

**I-pin.** Every test that asserts a specific date, name, id, count, total, page count, wording or "the latest / the
last / the first" of the real records reads the **pinned snapshot**, never `data/`. "Latest" and "last" are counts in
disguise: (1) and (2) move them.

**The pinned snapshot** is `tests/fixtures/real-data-b35f129.json.gz` (`tests/pinned_data.py`): the data files exactly
as committed at `PINNED_COMMIT = b35f129` (main after PR #33; re-pinned from b5a3638 at the merge, below), in one
byte-stable gzip (mtime 0, sorted keys), read offline:

| key | file at b35f129 | kept |
|---|---|---|
| `city_facts` | `data/localities/clarksville-tn/facts.json` | whole |
| `city_wards` | `data/localities/clarksville-tn/wards.json` | whole |
| `county_facts` | `data/facts.json` | whole |
| `city_finance` | `data/localities/clarksville-tn/finance.json` | books, sources, coverage; budget lines of `CITY_FUNDS` (parking commission, vehicle replacement) only |
| `county_finance` | `data/finance.json` | budget lines `COUNTY_LINES` only |

584 KB compressed. A committed copy, not `git show b35f129:...`: the update job's checkout is shallow, and a copy keeps
every run offline and identical. `pinned_data.get()` returns deep copies, so no test changes what another reads.

**Precedent kept.** `tests/test_city_verify_data.py` already does this for its counts and digests
(`tests/fixtures/city-facts-a605d25.json.gz`, projected, `pipeline/tests-pin-live-data`). It is left as is: it pins a
different commit for a different purpose (the V6 rebuild), and its live test is a correct I-live rule.

**Third option: rewrite as a rule.** A specific-fact check may stay live if it is rewritten as a rule that cannot
fail on growth, with the snapshot keeping the specific check: `test_cz_01_2024_applicant_is_null_in_the_committed_facts`
("no CZ-01-2024 item is published with an applicant", and the pinned facts hold the item, so it is not vacuous),
`test_every_resolved_call_on_is_on_the_meetings_own_shown_attendance` (the rule on live and pinned data, the named
call-ons on pinned only), and the transcript-privacy needle (any item title long enough, not `items[0]`).

**Enforced in the suite, not only here.** `tests/test_city_seats.py::test_the_live_tests_hold_on_any_valid_growth`
runs every live seat test on eight kinds of growth of the live data, covering I-live 1-3 (a later list; an earlier
list posted late, as hit 2; both; a later list leaving a member out; a later list printing a name the record cannot
place; three new members; a later list that prints wards again; new members then printed wards), as
`test_city_verify_data.py::test_a_new_council_meeting_in_the_live_facts_fails_none_of_these_tests` already does for
its module. A new live seat test is added to `LIVE_TESTS` and so proven against growth on every run.

### Re-pinning
Only by a deliberate pull request: check out the commit whose data the pinned tests should read, run
`pinned_data.write()`, change `PINNED_COMMIT` and the file name, and update the pinned tests' expected values in the
same PR. Never re-pin to make a daily update pass.

**Re-pin 1 (2026-11-18, merge of main into PR #34).** PR #33 read the FY2025 city budget book (Type 3 glyphs) and
changed only `data/localities/clarksville-tn/finance.json`; its tests name the four books, FY2025's report date and the
Vehicle Replacement Fund's name completed from FY2024. The snapshot was re-pinned at b35f129: `city_finance` now holds
four books and adds the vehicle replacement fund; `city_facts`, `city_wards`, `county_facts` and `county_finance` are
byte-for-byte what b5a3638 held (checked). PR #33's fund-name test was split: the rule (every completed name has its
one sentence, no other fund page has it) stays live on the books as collected; the named Vehicle Replacement case,
the four book ids, the FY2025 report date and the hub card's book list read the pinned books.

### Residual risks
- **Privacy scrub.** The snapshot holds published records only (what `data/` publishes). `qa/pii_scan.py` reads
  tracked `*.json.gz` by decompressing it (review finding privacy/pii-scan-gzip-blind; an unreadable one is refused,
  never skipped), so a leaked span in the snapshot is a hit like any other. A scrub of `data/` (e.g.
  `tools/scrub_rpc_phones.py`) must still re-pin the snapshot in the same PR. The snapshot holds no RPC file and no
  transcript (the two sources the privacy work masks).
- **Pinned tests no longer see a regression that only today's data shows.** That is the I-live tests' job, and the
  site checks' (`qa/site_checks.py`, run in the update job before the tests).
- **A test added later that reads `data/`.** The consumer list below is the review checklist: a reviewer classifies
  any new reader of `data/` as I-live or I-pin. A guard test that fails on every new reader was considered and left
  out (too many legitimate live readers to allowlist cheaply; revisit on a third hit).
- **`-x` hides later failures.** The update job keeps `-x` (a failed run should stop early), so the proof below runs
  without it on simulated growth.
- **The live CivicClerk listing in the transcript importer tests.** They find MEETING's event (2618) in
  `civicclerk-listing.json`, which the city run rewrites. The listing re-lists every event since 2024-01-01, so 2618
  stays; if it ever went, `test_committed_transcripts_match_their_meetings` fails too, and rightly. Accepted, not pinned.
- **Cost.** The pinned city-budget build (`pinned_pages`) adds about 1.5 minutes to the suite on a quiet machine.

## Consumers (tests/, every reader of data/, 2026-11-18)
L = I-live (reads data/ as collected), P = pinned snapshot (moved by this change unless marked "already").

Found by grepping `tests/` for `data/` paths (`ROOT / "data"`, `REPO_ROOT / "data"`, `CITY`, `REAL`, `TRANSCRIPTS`,
`json.loads` of a data file), for real builds (`build(ROOT / "data" / "facts.json", ...)`, which read every file
under `data/` through the config defaults), for default-config loaders (`rpc.load(rpc.load_config(...))`) and for
fixtures imported from other modules. `collector/tests/` also reads `data/` (13 modules); it is out of this list's
scope and passed the growth run below unchanged.

| module | consumer (fixture, helper or test) | reads | class |
|---|---|---|---|
| test_city_seats.py | `live_city` → the 4 tests of the latest list, ward carry-on, Served previously, latest minutes read (non-vacuity derived from the data: a holder is required only where a latest-list member has a ward print, a carried vote only where a verified roll call follows the last print) | city facts, wards | L |
| test_city_seats.py | the same two rules' counts on `real_city`: 10 or more wards held, some vote carried | city facts, wards | P |
| test_city_seats.py | `test_the_live_tests_hold_on_any_valid_growth` (runs those 4 on 8 kinds of growth) | city facts, wards | L |
| test_city_seats.py | `test_every_district_has_a_holder_on_the_live_county_facts` (and with one more meeting) | county facts | L |
| test_city_seats.py | `real_city` (pinned), `_at`, `_until`, `_cut`, `_next_list` → 9 city tests (McLaughlin 2026-02-05, Zacharias 2026-06-04, the 07-06 list as printed and corrected, seats CSV, site-check names, Ward 2 seating) | city facts, wards | P |
| test_city_seats.py | `_county_plus_one_meeting` and 5 more county tests (seats.yml current, district page agrees, stale-seat warnings, seats CSV printed_last) | county facts | P |
| test_council_pages.py | `city_facts`, `city_wards` (`pinned_subset()`: 5 historical meetings) → the council fixture site, also imported by test_about_owner, test_body_switch, test_trust_pages, test_mobile_front_lite, test_watch, test_your_seats (about 60 tests) | city facts, wards | P |
| test_council_pages.py | `test_real_city_pages_fit_the_file_budget` (207 pages at the pin; each new year adds about 15) | city facts | P |
| test_corrections.py | `full` (the same subset) | city facts, wards | P |
| test_days.py | `test_council_cards_show_votes_when_read_and_the_agenda_when_not` | city facts, wards | P |
| test_transcripts.py | `city_facts()`, `city_wards()` → the import and page tests (MEETING 2026-02-05, 2019-01-03) | city facts, wards | P |
| test_transcripts.py | `test_committed_transcripts_match_their_meetings` (`live_city_facts()`) | city facts, transcripts, listing | L |
| test_transcripts.py | `test_every_resolved_call_on_...[live]` (the rule) / `[pinned]` (the rule and MEETING's named call-ons) | city facts, wards, transcripts | L / P |
| test_transcripts.py | `LISTING` (the importer tests find event 2618 in it) | civicclerk-listing.json | L (residual, below) |
| test_transcript_privacy.py | `site`, `_import` (through test_transcripts' pinned `city_facts()` and `city_wards()`) | city facts, wards | P |
| test_transcript_privacy.py | committed transcripts masked at rest; QA rule agrees with the masker | transcripts | L |
| test_transcript_privacy.py | the source-text needle: now any item title long enough, not `items[0]` | county facts | L |
| test_city_budget_pages.py | `site`, `fin` → one page per fund, every total's check state, every row's source, report totals, county and city link each other, official record, books phrase from the data, every completed fund name disclosed once (PR #33's rule), preview over its cap | city finance, all data/ (real build) | L |
| test_city_budget_pages.py | `pinned_pages`, `pinned_fin` → the four books listed (FY2025 read, report date 06/27/2024), FY2027 proposed, report-date columns, amounts and source page, the books phrase's wording, the Vehicle Replacement name completed from FY2024 | city finance, county and city facts | P |
| test_budget_pages.py | `test_real_trustee_note_text` (line fy2027-approved/p47/r37) | county finance | P |
| test_map_seats.py | `test_committed_seats_pass_the_seat_check`, `..._after_one_new_meeting` | county facts | P |
| test_map_seats.py | `test_committed_seats_pass_the_seat_check_on_the_live_facts_they_are_read_to` (seat_check on the roll calls up to `read_to`; a later meeting with an unknown voter is outside it) | county facts | L |
| test_independent_readings.py | `test_cz_01_2024_applicant_is_null_in_the_committed_facts` (rewritten: no CZ-01-2024 published with an applicant; the pin proves it is not vacuous) | county facts | L + P |
| test_city_verify_data.py | `snapshot()` → counts, digests, D1, Claunch record | city facts at a605d25 | P (already) |
| test_city_verify_data.py | `facts()`, `live_wards()` → Claunch configured once, every snapshot meeting and verified vote kept; its own growth self-test | city facts, wards | L |
| test_about_owner.py | `test_shipped_config_names_an_official_of_the_city_facts` | city facts | L |
| test_provenance.py | `test_cutover_is_immaterial_on_committed_data` | county facts | L |
| test_address_box.py | `real_site` → the box in a browser, each seat's holder as the landing list shows it | all data/ (real build) | L |
| test_csp.py | `served_site` → the site under its CSP in a browser | all data/ (real build) | L |
| test_unofficial_first_screen.py | `real_site` → the tag on the first screen | all data/ (real build) | L |
| test_site_raw_leaks.py | `real_public` → status and check names only, no check detail, no unmatched raw name | all data/ (real build, export) | L |
| test_rpc_hold.py | `test_run_checks_fails_a_real_pages_build_without_its_morning_note` | all data/ (real build) | L |
| test_export_rpc.py | the committed RPC record: default export, exports only what its pages show, meeting rows agree with documents | rpc.json | L |
| test_staleness.py | every source dated; newest dates match the freshness line | all data/ | L |
| test_topic_typing.py | every numbered ordinance and resolution typed | county and city facts | L |
| test_committees_daily.py | the committees files are tracked JSON | git ls-files data/…/committees | L |

Counts: 36 consumers: 21 L, 13 P (12 moved by this change, 1 already pinned), 2 split into a live rule and a pinned
check (the call-on rule, CZ-01-2024). By tests: 17 in test_city_seats.py, 5 in test_city_budget_pages.py, 6 more named
tests, about 60 on the council fixture site and about 30 on the transcript fixtures now read the pinned snapshot.
(Review of PR #34 added the derived non-vacuity, the two live guards and three growth cases.)

## Proof
Run 2026-11-18 on a shared, loaded machine (CI runs the suite in about 15 minutes).

**Normal tree** (this change, `python -m pytest -q`, no `-x`): 5299 passed, 5 skipped in 47m59s.
`tests/test_pinned_data.py`, added after that run started: 3 passed.

**Simulated growth.** A scratch copy of the repository (not committed) with `data/` grown the way a daily update grows
it, written in the collectors' own format (indent 2, sorted keys, UTF-8) with manifest rows for every new document:
- city: the 2026-07-02 minutes read late, an EARLIER list (the 2026-06-22 list again, naming Claunch: hit 2); the
  2026-10-01 and 2026-11-05 minutes read (the 2026-07-06 list again, with its roll calls; 2026-11-05 has a committed
  transcript, so its call-ons now resolve);
- county: a 2026-06-08 meeting after the latest (2026-05-11), its roll calls those of 2026-05-11 again.

| suite on the grown copy | result |
|---|---|
| the tests at b5a3638, `tests/` | 8 failed: 7 in test_city_seats.py (hit 2's `test_the_07_06_list_read_as_printed_...` and the 6 county seat tests) and test_map_seats.py's `..._after_one_new_meeting`. The real run showed one, because of `-x`. |
| this change: every pinned test and the live seat tests (test_city_seats, test_map_seats, test_transcripts, test_transcript_privacy, test_independent_readings, test_city_verify_data, the trustee note, the file budget, the council day card) | 233 passed, 3 skipped |
| this change, full suite, no `-x` | `tests/`: 0 failed. `collector/tests/`: 12 failed, all in checks that the committed files are exactly what the collectors write (ids sorted, byte-identical after a keep: test_verify, test_shrink_guard, test_city_shrink_guard, test_run). With the grown county lists and city sources put in the writers' order, 8 of the 12 pass; the 4 left (`test_city_reposted_minutes_not_read_keeps_the_committed_meeting`, byte identity of the city facts) need the city writer's meeting order, which a hand-made growth does not reproduce. Judged a simulation artifact (medium confidence): the real hit-2 run passed every collector test on real growth. collector/tests is outside this list (follow-up below). |

The 22 `test_morning.py` errors in the b5a3638 run were `OSError: [Errno 28] No space left on device` from the shared
machine; the module passes alone on both trees (84 passed).

## Follow-up
- `collector/tests/` reads `data/` in 13 modules (shrink guards, run, verify, finance, committees, one-vote,
  provenance). They passed every real daily run so far; classify them against I-live/I-pin the next time any of them is
  touched, or at once on a hit there (owner: backend-engineer). The code review of PR #34 judged them safe (the
  writers rewrite `data/`) and flagged named records to derive or pin: `test_shrink_guard.py:26` (BOOK
  src-7325525d58ca), `test_one_vote.py:245` (rc-90320418-p138-*), `test_city_shrink_guard.py:494/507`
  (`2026-01-06-executive` must stay agenda-only, more than 100 agenda-only meetings: posting those minutes fails it).
