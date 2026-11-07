# QA test plan: clarksville-records M1 (private preview)

Owner: qa-engineer. Spec: `docs/specs/clarksville-records.md` (Milestone 1 stories, neutrality N1-N6, parse accuracy P1-P4).
Architecture: `docs/architecture/clarksville-records.md` ("Invariant: held-back counts", Run flow). Written 2026-11-07 before the
full-corpus facts exist; the Result columns are blank until QA runs against the real `data/facts.json`.

Scope: M1 = US1, US2, US4, US6, US7, AC-P1..P4, N1-N6, G1-G7. Not in M1, not tested here: US3 (agenda search) and US5 (public
correction form) are M1.5; G6 is a pre-public-URL gate. N5 is tested only as "link present and the About page says how"
(the preview has no form).

## How the final pass runs (about 10 minutes, 8 steps)
Run on a clean worktree at the SHA the manager names (`git worktree add --detach <path> <sha>`), then `pip install -r requirements.txt pdfplumber`.

| # | Step | Command / action | Expect |
|---|---|---|---|
| 1 | Record the SHA | `git rev-parse HEAD` | write it in the report |
| 2 | Data and site exist | `python -m collector run --offline --internal` (store in `data/store/`, or `RECORDS_STORE`; offline means no network) | exit 0, `build/report.json`, `build/site/` |
| 3 | Scripted pass | `bash qa/final.sh` (tests, gates, hand labels, site checks, spot-check sheet) | every section PASS |
| 4 | Public build | `python -m collector run --offline` (no `--internal`), then `python -m qa.site_checks --site build/site --facts data/facts.json` | PASS, no `review.html` |
| 5 | Spot check by eye | open `build/qa/spot/sheet.md`, fill `y`/`n` x 4 for 20 rows (about 6 minutes) | all `y` |
| 6 | Score | `python -m qa.spot_check --score build/qa/spot/sheet.md` | `PASS: 20/20` (exit 0) |
| 7 | Manual looks | the 5 manual rows below (AC1.4, AC6.1 labels, AC7.3, N5/N6/G1, phone look) | as written |
| 8 | Verdict | fill the Result column; any FAIL = bug report with a problem key | PASS / PASS WITH MINOR ISSUES / FAIL |

Tools written for this pass (all read-only on product code; self-tested, see "Tool self-tests"):
- `qa/site_checks.py` black-box checks of a built site directory (links, anchors, `#page=`, unverified leak, footer, N1, totals, 390 px).
- `qa/spot_check.py` seeded 20-vote pick, page PNGs under `build/qa/spot/`, `sheet.md`, `--score`.
- `qa/final.sh` runs steps 3 in order. `python -m collector.compare_labels` is the AC-P3 comparison (backend's).

## Criteria
Kind: **A** automated test that exists (file::test), **S** script in this plan, **M** manual look. Result: PASS / FAIL / n/a, plus evidence (command output, file, SHA).

### US1 commissioner pages
| AC | Criterion | Kind | How it is checked | Result | Evidence |
|---|---|---|---|---|---|
| AC1.1 | One list entry per person in a roll call 2020-2024; variants merged; merge rules visible | A+S | `qa/site_checks.py` check `index` (every official in facts listed once, alphabetical by surname); `collector/tests/test_names.py` rules 1-4; `test_names::test_committed_roster_loads_and_every_alias_has_a_reason`. M: read the merge rules on `about.html` and scan `data/names.yml` aliases for two different people merged (Allbert/Ailbert, Smith x3 are the known traps) | | |
| AC1.2 | Each vote row: date, item/motion text, recorded vote, recorded outcome | A+S | `tests/test_site_links.py::test_vote_rows_link_item_and_meeting`; `site_checks` `layout` (identical column headers: Date, Type, Item, Record, Outcome, Source); spot check rows (AC-P2) compare content to the PDF | | |
| AC1.3 | 100% of rows link to the PDF at the page; link and page check | A+S | `site_checks` `sources`: every fact row has a link with `#page=N`, 1 <= N <= page count in facts, and N <= real page count from `pdfinfo` when the PDF is cached; `tests/test_site_links.py::test_every_fact_row_links_to_its_pdf_page`. Note: meeting-page header links name the whole document and carry no `#page`; reported, not failed | | |
| AC1.4 | Page states date range and fetch date | A+M | fixture: `tests/test_site_review_fixes.py` and the "Period covered" sentence; M: open 2 real official pages (earliest and latest meeting years), read "Shows ... from X to Y. Minutes fetched on D." and compare X, Y with `coverage` in facts | | |
| AC1.5 | Two commissioners' pages differ only in data | A | `tests/test_site_neutrality.py::test_official_pages_have_identical_skeleton`, `::test_official_with_no_data_has_same_skeleton`; `site_checks` `layout` on every official page of the real build | | |

### US2 attendance
| AC | Criterion | Kind | How it is checked | Result | Evidence |
|---|---|---|---|---|---|
| AC2.1 | Meeting page lists each member Present/Absent as in minutes, with source and page | A+S | `site_checks` `sources` and `unverified` (every attendance row is a shown fact and appears on the official's page); spot check: while viewing a roll-call page also note the "ABSENT:" line against the meeting page (extra, 3 meetings, M) | | |
| AC2.2 | Attendance total with denominator equals a recount from meeting pages | A+S | `tests/test_site_links.py::test_attendance_totals_match_meeting_pages` (fixture); `site_checks` `totals` recounts every official on the real build | | |
| AC2.3 | No parseable attendance: "attendance not extracted", excluded from totals, stated | A | `tests/test_site_review_fixes.py::test_not_extracted_and_under_review_are_separate_sentences`, `::test_fixture_counts_each_attendance_state`; `site_checks` `totals` (denominator excludes them). M: pick one real meeting with `attendance_status: not_extracted` if any (`python -c` over facts) and read its page | | |

### US4 collection
| AC | Criterion | Kind | How it is checked | Result | Evidence |
|---|---|---|---|---|---|
| AC4.1 | One run discovers, downloads, parses, updates the preview; asks Brian for nothing | S+M | `python -m collector run` is the one command (`collector/tests/test_run.py::test_exit_codes`); QA runs it once with network, once `--offline`, and confirms no prompt and exit 0. The scheduled runner is a later step (architecture "Schedule"): record as "one command, in-session" | | |
| AC4.2 | robots.txt, Crawl-delay, >= 10 s on clarksvilletn.gov; test fails if a disallowed path or the delay can be skipped | A | `collector/tests/test_fetch.py::test_robots_disallow_is_obeyed_and_crawl_delay_raises_wait`, `::test_delay_is_never_skipped_across_many_requests_and_hosts`, `::test_clarksvilletn_floor_and_robots_crawl_delay_larger_wins`, `::test_cityofclarksville_is_refused_without_any_request`, `::test_host_not_on_allowlist_is_refused`. Mutation try: set `HOST_FLOORS` to 0 and `min_delay` to 0 locally, confirm tests fail, revert | | |
| AC4.3 | 403/429 or robots disallow: stop that host, log, no other route | A | `test_fetch.py::test_403_or_429_stops_the_host`, `::test_unattributed_403_is_the_sites_block`, `::test_proxy_tunnel_refusal_does_not_block_the_host` (proxy refusal is not a site block); `collector/tests/test_run.py::test_discovery_block_is_a_logged_failure_not_a_crash` | | |
| AC4.4 | Run log: found, new, failed, parsed, held back; failures raise an internal alert | S | after step 2 read `build/run-log.json`: keys `found`, `new`, `failures`, `parsed`, `held_back` present and numeric; on forced failure (`RECORDS_STORE=/nonexistent python -m collector run --offline`) exit code 2 and the `gh issue create` command is printed (wiring to a real issue is task D1, so print-only is the M1 bar) | | |
| AC4.5 | Re-run with no new docs changes nothing; facts carry URL, hash, page, fetch date | A+S | `collector/tests/test_run.py::test_second_offline_run_changes_no_committed_file`, `collector/tests/test_store.py::test_restoring_identical_bytes_leaves_manifest_byte_identical`; S: after step 2 run it again and `git status --porcelain data/` is empty; `site_checks` `sources` shows every fact link is a known source with page | | |

### US6 whole record, US7 item history
| AC | Criterion | Kind | How it is checked | Result | Evidence |
|---|---|---|---|---|---|
| AC6.1 | One date-ordered history: votes, attendance, Moved/Seconded (exact labels, never "comments"), with date, item, source page | A+M | `tests/test_site_neutrality.py::test_template_has_no_banned_words`; `tests/test_site_review_fixes.py::test_failed_motion_check_holds_back_only_attribution`; `tests/test_site_links.py::test_vote_rows_link_item_and_meeting`. M: on one real official page confirm types are only Vote / Attendance / Moved / Seconded, newest first, and search the page text for "comment" (expect none) | | |
| AC6.2 | Filter by type and year; same layout for all | A+M | `layout` check (filter form identical); M: in a browser on one real page choose Type = Moved and Year = 2022, rows change, "No rows match" works. (`site/static/filter.js` has no automated test.) | | |
| AC6.3 | Transcript lines only if added | n/a | not in M1; confirm no "transcript" text on any page: `grep -ril transcript build/site` empty | | |
| AC7.1 | Item page groups every appearance, date order, each with source page | A+M | `tests/test_site_links.py::test_every_fact_row_links_to_its_pdf_page` (event rows are fact rows); `collector/tests/test_verify.py::test_item_numbers_normalise`, `::test_every_consent_roll_call_reaches_the_items_it_covered`. M: open 3 items: a numbered resolution seen at 2+ meetings, one ordinance with a reading, one consent-agenda item; compare the event list with the PDF pages cited | | |
| AC7.2 | Roll call on an item page shows every member's vote and outcome | A+M | fixture: roll-call tables in `tests/test_site_links.py`; M: for the same 3 items, count member rows equals members present for that meeting | | |
| AC7.3 | Linked by official number; unnumbered only by exact title and marked "linked by title"; uncertain links not made | A+M | `collector/tests/test_verify.py::test_title_normalisation_is_conservative`, `::test_split_number_is_joined_only_when_on_the_agenda_else_unnumbered`; M: list 5 items with `link_basis: title` from facts, open each, confirm the label "linked by title" and that the titles are identical; open 2 numbered items where the number has an OCR variant (`0`/`O`, `1`/`l`) and confirm they are NOT merged (split history is accepted, a wrong merge is a bug) | | |
| AC7.4 | Every vote row and comment on an official's page links to its item page | A | `tests/test_site_links.py::test_vote_rows_link_item_and_meeting`; `site_checks` `links` (anchors on `items/<year>.html` resolve) | | |

### Parse accuracy and held-back facts
| AC | Criterion | Kind | How it is checked | Result | Evidence |
|---|---|---|---|---|---|
| P1/P3 | Only Verified shown; Unverified held back, never guessed | A+S | `tests/test_site_links.py::test_unverified_facts_only_on_review_page`, `tests/test_site_review_fixes.py::test_unverified_text_fields_appear_on_no_public_page`; `collector/tests/test_run.py::test_export_contains_no_unverified_fact`; `site_checks` `unverified`: unverified ids and outcome text in no page, no CSV/JSON export, no `review.html` in a public build, every fact id on a page is a shown fact and every shown fact is on its official page | | |
| P2 | Per-roll-call checks (one vote per present member, tally, outcome, roster) | A | `collector/tests/test_verify.py` (`test_clean_roll_call_is_verified_with_every_named_check`, `test_dropped_mark_fails_one_vote_per_member_and_tally`, `test_unresolved_roster_name_holds_the_roll_call`, `test_source_error_needs_two_agreeing_readings`) | | |
| P4 | Each page states the count under review, same wording for everyone | A | `tests/test_held_counts.py` (all), `tests/test_site_neutrality.py::test_totals_wording_is_fixed`, `collector/tests/test_verify.py::test_site_held_numbers_equal_the_g4_report`, `::test_held_total_equals_unverified_count_on_committed_facts`. S: sum check from the architecture invariant: the sum of the meeting pages' "N roll calls under review" equals `build/report.json` `g4.held_total` | | |
| AC-P1 | Verified >= 90%; counts reported | S | `build/report.json` `gates.verified_rate` and `verified_rate_gate.pass` (printed by `qa/final.sh` step 3). M0 baseline: 95.8% (138/144) on 11 PDFs | | |
| G4 | Skew gate: no official with >= 50 roll calls over 2x the median held rate | S | `build/report.json` `gates.g4.status` is `pass` (or `review needed`, which QA reads: `uniform_share` large means G4 cannot see skew, then AC-P1 alone bounds it); `collector/tests/test_verify.py::test_g4_*` | | |
| AC-P2 | 20 random shown votes, >= 4 commissioners, >= 4 years, all match the PDF (name, vote, motion, page) | S+M | `python -m qa.spot_check --facts data/facts.json` picks with seed 20261107 and renders `build/qa/spot/*.png`; fill `sheet.md`; `--score` must print `PASS: 20/20`. Any `n`: bug with key `parse-accuracy/<pattern>`, backend adds a regression test, rerun with a new `--seed` for a fresh 20 | | |
| AC-P3 | Hand-labelled set (>= 15 roll calls) gives zero wrong votes; unparseable goes to Unverified | A+S | `collector/tests/test_verify.py::test_hand_labelled_set_gives_zero_wrong_votes`; `python -m collector.compare_labels data/facts.json` prints `wrong votes: 0` (baseline: 21 labelled, 380 votes checked, 0 wrong). Adversarial add-on: QA hand-labels 2 more roll calls from pages the labels do not cover (an absence, a recusal if any) and adds them to `collector/hand_labels.json` only if the backend agrees | | |
| AC-P4 | Scanned/image-only minutes marked "not extracted"; OCR shown only if it passes P2 | A+M | `collector/tests/test_parse.py::test_clean_table_passes_p2_despite_ocr_name_errors`, `test_dropped_vote_marks_are_unverified_not_guessed`; `tests/test_site_review_fixes.py::test_not_extracted_and_under_review_are_separate_sentences`. M: count sources with `text_layer` other than `text` in facts; for 2 of them spot-check that every shown vote passes the AC-P2 look | | |

### Neutrality, governance, site-wide
| ID | Criterion | Kind | How it is checked | Result | Evidence |
|---|---|---|---|---|---|
| N1 | Same layout, fields, ordering for every official; alphabetical | A+S | AC1.5 tests; `site_checks` `index` (alphabetical by surname) and `layout`; `tests/test_site_neutrality.py::test_views_sort_keys_are_not_counts` | | |
| N2 | Facts only: Present/Absent; Yes/No/Abstain/Other-with-wording | A+M | `tests/test_site_review_fixes.py` label tests; M: list distinct "Record" cell values across all official pages (`grep -oh` the Record column) and confirm only the allowed labels | | |
| N3 | Counts are plain totals with denominator and date range, no sort/highlight | A | `tests/test_site_neutrality.py::test_totals_wording_is_fixed`, `::test_template_never_sorts_by_a_count`, `::test_template_has_no_banned_words` | | |
| N4 | Every fact shows source link (doc, page) and fetch date | A+S | `site_checks` `sources`; `tests/test_site_links.py::test_every_fact_row_links_to_its_pdf_page` ("p. N, fetched <date>") | | |
| N5 | Correction path on every fact page | A+M | `tests/test_site_links.py::test_every_fact_row_links_to_its_pdf_page` ("Report an error" on every fact row); M: `about.html#corrections` tells Brian how to report, quoting the fact id | | |
| N6 | No campaign link, ads, third-party scripts or tracking | A+S | `site_checks` `external` (no third-party script/link/img/form) and `sources` (any external link that is not a known source document fails); `tests/test_site_links.py::test_every_page_has_operator_footer_fixture_banner_and_no_external_resources` | | |
| G1 | Footer "Run by Brian Zacharias" + About page naming him, every page | S | `site_checks` `footer` on every page; M: About page names him and states the data rules | | |
| G2 | Written mechanical rules; changes logged | A+M | `tests/test_held_counts.py::test_about_page_explains_the_held_count_rule`; M: `changes.html` renders; merge rules on About match `data/names.yml` | | |
| G5 | Open data export of shown facts with sources | A+S | `collector/tests/test_run.py::test_export_contains_no_unverified_fact`; S: `ls build/site/data/` has the 10 files named in the architecture, every CSV row has `source_url, source_sha256, page, fetched_at`; `site_checks` `links` (no `--no-export`) fails if a linked `data/` file is missing | | |
| G7 | No public URL for the preview | M | confirm the preview is the private artifact only and the repo is private (`gh repo view --json isPrivate`) | | |
| Site | Built site under 250 files; internal links, `#anchors`, assets resolve | A+S | `tests/test_site_links.py::test_publish_manifest_and_file_limit`, `::test_internal_links_resolve`; `site_checks` `files`, `links` | | |
| Phone | No horizontal scroll at 390 px for index, official, meeting, items pages | S | `site_checks` `hscroll` (Playwright, sampled 3 per type; `--all-pages` once for the final pass). M: open one official page on a real phone or the 390 px emulator and read a row | | |

## Edge cases and adversarial tries (QA's own, beyond the criteria)
Each can fail, so a PASS needs the output. Run the ones the data allows; record result and evidence.
1. **Same-surname officials** (Smith x3 in 2020, Allbert/Ailbert): pick one vote by each in the spot check and make sure no vote is attached to the wrong Smith. Key family: `names/merge`.
2. **Vacant seat / "V"** columns: a vote under a person that was not seated at that meeting would be a hard fail. `site_checks` cannot see it; use the term dates in `data/names.yml`: for every shown vote, the meeting date must be inside that official's term if `terms` is set (script: `python - <<EOF` over facts; add to `qa/` if it finds anything).
3. **Held-back sum**: sum of per-meeting held numbers equals `held_total` equals number of unverified roll calls (invariant 3 in the architecture). Different numbers on two officials who sat the same meeting is the `neutrality/held-count` family's third hit and goes straight to the architect.
4. **HTML injection / escaping**: source text with `<`, `&`, quotes (item titles often have them): `tests/test_site_review_fixes.py::test_text_fields_are_escaped` covers the fixture; on real data `grep -c '<script' build/site -r` is 0.
5. **Idempotence at byte level**: `python -m collector run --offline` twice, then `git diff --stat data/` empty and `sha256sum build/site/**/*.html` identical between runs.
6. **Robots re-check**: `curl https://www.montgomerytn.gov/robots.txt` and `https://montgomeryminutes.bisonline.com/robots.txt` still allow the paths in the manifest (read-only, polite, once).
7. **Source page truth for tallies**: for the 20 picks also read the "Yeses - N Noes - N" line and compare with the counts on the item page (extra column in the notes).
8. **Huge item page**: largest `items/<year>.html` loads in Chromium without hanging (the hscroll check opens it; note the load time and size, `ls -l build/site/items/`). Over 16 MB or 255 files blocks publishing (ADR 0001).
9. **No-network behaviour**: `qa/spot_check.py` without PDFs and without `--download` reports "PDF not in store" per pick rather than crashing.

## Tool self-tests (run in `python -m pytest`)
`tests/test_qa_tools.py` (21 tests): `qa/site_checks.py` passes on the clean fixture build and fails on each planted defect (broken link,
broken anchor, `#page` beyond the count, fact-row link without `#page`, unknown external link, missing footer, unverified id in a page,
unverified outcome text in a CSV, hidden vote row, shown fact missing from its official page, review page in a public build, third-party
script, file cap, missing index entry, wrong index order, different official layout, wrong attendance total, 900 px overflow at 390 px).
`python -m qa.spot_check --self-test` (also run by pytest) covers pick spread (>= 4 commissioners, >= 4 years), determinism for one seed,
a fresh set for another seed, Verified-only picks, PNG rendering from a generated PDF, a page beyond the PDF, and `--score`.

## Dry-run results (before the real data, 2026-11-07, worktree at the merged `claude/project-thread-adnnrd`)
| Run | Input | Result |
|---|---|---|
| `qa.site_checks` fixture build | `site/fixtures/facts.sample.json` -> `build/site` | PASS all 10 checks, 8 pages at 390 px |
| `qa.site_checks` internal build run as public | `--internal` build checked without `--internal` | FAIL as intended (review.html present and linked) |
| `qa.site_checks` M0 spike data | committed `data/facts.json` (11 PDFs, 138/144 verified) -> 50 pages, store from the main checkout | PASS all 10 checks; 5,696 source links; 11 of 11 PDFs cross-checked with `pdfinfo`; 48 pages (all) at 390 px |
| `qa.spot_check` M0 spike data | same facts, 11 cached PDFs | 20 votes, 14 commissioners, 5 years, 20 PNGs, legible (pick 3, Johnson 2020-10-12 p. 37, read by eye: Y matches; the other 19 are step 5) |
| `qa.spot_check --self-test` | none | PASSED |
| `bash qa/final.sh` M0 spike data | steps 1-6 end to end | SCRIPTED PARTS: PASS (192 tests passed; gates 95.8%, G4 pass; 380 labelled votes, 0 wrong) |
Findings from the dry run (for the frontend engineer, minor, not blocking): meeting pages link the whole minutes PDF without `#page` in the
header sentence (document-level link, reported by `site_checks` as a note, not a failure). Decide whether AC1.3 should cover it: this plan
treats AC1.3 as fact rows only.

## Bug report template
Title | severity (blocker/major/minor) | problem key `<family>/<invariant>` | steps | expected vs actual | evidence | owner role.
