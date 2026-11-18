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

**The pinned snapshot** is `tests/fixtures/real-data-b5a3638.json.gz` (`tests/pinned_data.py`): the data files exactly
as committed at `PINNED_COMMIT = b5a3638`, in one byte-stable gzip (mtime 0, sorted keys), read offline:

| key | file at b5a3638 | kept |
|---|---|---|
| `city_facts` | `data/localities/clarksville-tn/facts.json` | whole |
| `city_wards` | `data/localities/clarksville-tn/wards.json` | whole |
| `county_facts` | `data/facts.json` | whole |
| `city_finance` | `data/localities/clarksville-tn/finance.json` | books, sources, coverage; budget lines of `CITY_FUNDS` (parking commission) only |
| `county_finance` | `data/finance.json` | budget lines `COUNTY_LINES` only |

574 KB compressed. A committed copy, not `git show b5a3638:...`: the update job's checkout is shallow, and a copy keeps
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
runs every live seat test on five kinds of growth of the live data (a later list; an earlier list posted late, as
hit 2; both; a later list leaving a member out; a later list printing a name the record cannot place), as
`test_city_verify_data.py::test_a_new_council_meeting_in_the_live_facts_fails_none_of_these_tests` already does for
its module. A new live seat test is added to `LIVE_TESTS` and so proven against growth on every run.

### Re-pinning
Only by a deliberate pull request: check out the commit whose data the pinned tests should read, run
`pinned_data.write()`, change `PINNED_COMMIT` and the file name, and update the pinned tests' expected values in the
same PR. Never re-pin to make a daily update pass.

### Residual risks
- **Privacy scrub.** The snapshot holds published records only (what `data/` publishes), but `qa/pii_scan.py` cannot
  read gzip. A scrub of `data/` (e.g. `tools/scrub_rpc_phones.py`) must re-pin the snapshot in the same PR. Mitigation:
  the snapshot holds no RPC file and no transcript (the two sources the privacy work masks).
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
| test_city_seats.py | `live_city` → the 4 tests of the latest list, ward carry-on, Served previously, latest minutes read | city facts, wards | L |
| test_city_seats.py | `test_the_live_tests_hold_on_any_valid_growth` (new: runs those 4 on 5 kinds of growth) | city facts, wards | L |
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
| test_city_budget_pages.py | `site`, `fin` → one page per fund, every total's check state, every row's source, report totals, county and city link each other, official record, books phrase from the data, preview over its cap | city finance, all data/ (real build) | L |
| test_city_budget_pages.py | `pinned_pages`, `pinned_fin` → books listed (FY2027 as presented 5/29/2026, FY2025 linked only), FY2027 proposed, report-date columns, amounts and source page, the books phrase's wording | city finance, county and city facts | P |
| test_budget_pages.py | `test_real_trustee_note_text` (line fy2027-approved/p47/r37) | county finance | P |
| test_map_seats.py | `test_committed_seats_pass_the_seat_check`, `..._after_one_new_meeting` | county facts | P |
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

Counts: 33 consumers: 19 L, 12 P (11 moved by this change, 1 already pinned), 2 split into a live rule and a pinned
check (the call-on rule, CZ-01-2024). By tests: 15 in test_city_seats.py, 5 in test_city_budget_pages.py, 6 more named
tests, about 60 on the council fixture site and about 30 on the transcript fixtures now read the pinned snapshot.

## Proof
PROOF
