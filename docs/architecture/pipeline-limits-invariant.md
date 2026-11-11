# Pipeline limits invariant (loop rule: `pipeline/` hit 2; rule 3 restated at hit 3)
software-architect, 2026-11-11. Trigger: code review of tip45 d55c1ea, must-fix `pipeline/ocr-page-cap-drops-real-readings`
(first hit: `pipeline/parser-dos-untimed`). This page states the invariant and lists every limit before the next fix.

## The invariant
A safety limit on collecting or parsing (a timeout, a size, page, byte or count cap) may **refuse a file, a page or a
listing**, but it must never change a fact we publish unless that change is **visible and reported**:
1. **Above real use, with margin.** Every limit sits at least 2x above the largest real input, measured from the
   committed data and the store (say where and when), and the code comment states that measurement. A limit with no
   measured margin is a bug, not a setting.
2. **Fail closed, whole unit.** A trip refuses one well-defined unit (a fetch, a page reading, a document) and the result
   is "not read", never a partial or guessed value.
3. **Reported, not just logged; a downgrade is kept per source document, never frozen for all.** A trip appears in the run
   summary as `limit <NAME>: <file> [page] <value> > <cap>`. Each step's summary and report list only that step's own
   trips (`limits.mark()` at the step's start), and a timeout's value is the cap reached (`120s+`), so the same trip
   twice in a step is one line. The shrink guard that protects published facts is specified in full in
   "Rule 3: the shrink guard" below (restated at `pipeline/` hit 3, 2026-11-11; it replaces the manager's decision
   of the same day that kept the whole facts file and exited 3).
4. **Bound the cost, not the position.** A cap limits what one unit can cost (memory, time). It never limits *where* in
   a real document we may read (a page index, a byte offset), because position is not cost.

## Rule 3: the shrink guard (loop rule: `pipeline/` hit 3)
software-architect, 2026-11-11. Trigger: security review of tip45 7ae5fb3, MEDIUM
`pipeline/shrink-guard-freezes-all` (collector/__main__.py:372-417, daily-update.yml:141-155): one lost verified
roll call made the county run exit 3, the Collect step failed, and nothing (city, county, finance, RPC) committed or
deployed, every day, until `--allow-shrink`, which the workflow could not pass. Earlier hits: `parser-dos-untimed`,
`ocr-page-cap-drops-real-readings` (then `shrink-guard-offline-only`, `limits-reported-misattributed` on 7ae5fb3).

**The invariant (two halves, both must hold):**
- **I-1 No silent downgrade.** A roll call verified, or a motion confirmed, in the committed file is never turned
  unverified/unconfirmed or dropped by a limit trip or a transient failure (timeout, OCR error, missing store file,
  fetch or parse hiccup). Only a **correction** (the source document's bytes changed) or a person
  (`--allow-shrink`) may change it, and both are reported.
- **I-2 No collateral freeze.** One source's or one meeting's problem never blocks any other meeting, source or
  pipeline (city, county, finance, RPC) from committing and deploying. The guard firing is a **warning**, not a
  failure of the run.

**Facts the design rests on (verified 2026-11-11 on data/facts.json at 7ae5fb3):** 64 meetings, 59 sources, 390 roll
calls. Every meeting has exactly one `source_id`, and every roll call, motion and item event carries its meeting's
`source_id` (0 mismatches). A source can carry **two** meetings (5 minutes books, e.g. `src-7325525d58ca` =
2020-02-10 + 2020-03-09), so the unit is the **source document and every meeting in it**. Source ids are `src-<sha256[:12]>` and roll call/motion ids are
`rc|mo-<sha256[:8]>-p<page>-<n>` (collector/facts.py:198,268; __main__.py:216). Meeting ids are `<date>-<kind>` and do
not depend on the bytes. So today's id-based `lost_verified` (__main__.py:313-317) sees a **correction as the loss of
every roll call in that meeting**: the first half of the bug.

**G1 Scope: per source document, matched through its meeting ids, compared by sha256.** For each source `S` in the
committed `data/facts.json`, let `Ms` be the meeting ids it carries (one or two today) and `h_old` its sha256. In the
new result:
- (a) **Same source** (a source with sha256 `h_old` is present): roll call ids are stable, so compare by id. If any
  roll call of `S` verified in the committed file is not verified (or absent) in the new result, or a meeting of `Ms`
  is gone, the guard **fires for `S`**.
- (b) **Correction** (no source with `h_old`, but the meetings of `Ms` are present under a source with another
  sha256): the county posted different bytes. The new reading wins and the guard does not fire. The run summary
  prints `correction: <meeting ids> source <old8> -> <new8>, verified <n_old> -> <n_new>` and run-log.json
  `corrections` lists it. If `n_new < n_old` it also raises the warning exit below (published, but a person looks),
  because a truncated or wrong file served for the same meetings would otherwise pass silently as a correction. Same
  rule for RPC (G4).
- (c) **Missing** (no source with `h_old` and the meetings of `Ms` absent: not in the store, fetch/parse failure,
  timeout): transient; the guard **fires for `S`**. If `h_old` was parsed but yields other meeting ids (a parser
  change), the guard also fires and the new records from `h_old` are dropped, so one document is never shown twice;
  renaming ids on purpose needs `--allow-shrink`.
- Gaining verification, new meetings, new sources and new roll calls are never guarded.
- New assertion: a result in which a meeting has no source, or a roll call, motion or item event names a
  `source_id` other than its meeting's, raises in the guard with a clear message (the unit stopped holding; re-plan
  before merging).

**G2 What the run does when the guard fires (online, which is what the daily workflow runs):**
1. **Keep that document's meetings exactly.** In the facts to be written, every record whose `meeting_id` is in
   `Ms` or whose `source_id` is `S` or any new source carrying a meeting of `Ms` (meetings, roll_calls, motions,
   item_events, sources) is replaced by the committed records, byte for byte; committed `items` they reference are
   added back if the new result lacks them. `officials` and `coverage` come from the new result. Lists are sorted
   as `Builder.facts` sorts them, so a run that keeps the same document two days running writes an identical file
   (no churn commit).
2. **Publish everything else.** The merged facts are written to `data/facts.json` and are what `sitegen` and
   `export_site` read (__main__.py:381,401,403). City, finance, agendas and RPC proceed as normal.
3. **Gates on what is published.** `verify.gates` runs again on the merged facts (verify.py:136), and `report.pass`
   and exit 3 use that, so a kept meeting never fails a gate the published file would pass.
4. **Warning exit `KEPT = 7`** (new constant beside `RPC_FAILED, RPC_FILLING` at __main__.py:131). Codes in use:
   county `run` 0 ok, 2 fetch/parse failures, 3 gate or finance failure, 4 offline refused, 5 RPC failed, 6 RPC
   filling; city 0 ok, 2 listing/fetch/parse, 5 blocked; `rpc.py` step codes 0-4 and 6 (internal, mapped to 5/6).
   7 is unused everywhere. **Precedence:** 2 > 3 > 7 > 5/6 (hard failures still win; an RPC outcome under 7 is
   carried in run-log.json, item 6). 7 is returned when `kept_meetings`, or a `corrections` entry that lowers the
   verified count, is non-empty and nothing hard failed.
5. **run-log.json** gets `kept_meetings: [{source_id, meeting_ids, ids: [lost roll calls], reason}]` and
   `corrections: [...]` (replacing `kept_facts`); stderr prints one `collector: KEPT <source> (<meeting ids>): ...` line per kept document.
6. **Workflow** (daily-update.yml Collect step): `7` sets output `kept=yes` and `county=0`; it also reads `.rpc.exit`
   from build/run-log.json (jq; unreadable counts as failed) to set `rpc=failed|filling|ok`, because one exit code
   cannot carry both. A new step "Open or update the county kept-meetings issue"
   (`if: always() && steps.collect.outputs.kept == 'yes'`, title `Daily update: county meetings kept`) copies the
   RPC issue step: body from `build/run-log.json .kept_meetings, .corrections` into a file, backticks stripped,
   `head -c`, `--body-file`, one open issue then a comment each later day. The job succeeds, so upload, push and
   deploy run.
7. **Offline** (`python -m collector build` / `run --offline`; CI never runs it): unchanged, refuses with exit 4
   before writing, but `shrink_reason` applies the same sha256 rule, so a correction is not refused.

**G3 Override.** `--allow-shrink` (existing flag) skips G1: the new result wins for every meeting, still listed in the
summary. Workflow: a new `workflow_dispatch` input `allow_shrink` (boolean, default false, description "Accept a
result that unverifies committed roll calls or unconfirms motions (county and RPC); manual runs only"). The Collect
step reads it through `env` (`ALLOW_SHRINK: ${{ inputs.allow_shrink }}`), never interpolated into `run:`, and adds
`--allow-shrink` to `python -m collector run` only when `GITHUB_EVENT_NAME` is `workflow_dispatch` and the value is
exactly `true`; a scheduled run can never pass it. It is not passed to `python -m collector city run` (no guard
there). Its result commits only from main (push job `if`, daily-update.yml:312). **This is a CI change: it needs a
fresh security-engineer review** (a new input, and a path by which a manual run publishes a downgrade).

**G4 RPC (`rpc.py`) interaction.** RPC stays its own all-or-nothing step with exit 5 and its own issue
(rpc.py:404-431, 477-480; daily-update.yml:209-242); its failure already never blocks the other sources. Changes in
this fix: (i) the confirmed-motion check honours G1(b): a motion whose meeting's minutes `source_id` changed is a
correction, not a loss (RPC motion ids are `<meeting>-motion-<n>`, stable across bytes, so compare `source_id`);
(ii) `hold_motions: true` (config/localities/cmc-rpc/rpc.yml:28, as today) still skips the motion check, because
nothing is published confirmed; (iii) `--allow-shrink` from G3 reaches it as now (__main__.py:390-391).
**Known gap, not in this fix:** inside RPC one meeting's shrink still holds back every RPC meeting (whole-step
refusal), which breaks I-2 within RPC. Tolerable while `hold_motions` is on and listing/manifest are all-or-nothing
too; before `hold_motions` is turned off, give RPC the per-meeting keep (architect task then).

**G5 Known gap, not in this fix (proposed key `pipeline/parse-failure-freezes-all`):** a fetch or parse failure on one
county document (e.g. an L8 `pdftotext` timeout, which is not cached and so repeats daily) still sets exit 2 and
freezes every pipeline, which breaks I-2. Fixing it changes the runbook's hard-failure contract for every failure
stage, so it is its own decision. Recommended: the same G2 keep for a committed meeting whose source failed (exit 7),
exit 2 only for a failure with no committed meeting to fall back on. The manager decides whether to bundle it.

**Every consumer of the guard and its exit codes (checklist, file:line at 7ae5fb3; 33 items; all done 2026-11-11 by backend-engineer, G1-G4):**
- [x] 1 collector/__main__.py:1,20 module docstring (`--allow-shrink`, the guard)
- [x] 2 collector/__main__.py:131 exit constants: add `KEPT = 7`
- [x] 3 collector/__main__.py:185-191 `cmd_build` gates and `report.pass` (recomputed on merged facts, G2.3)
- [x] 4 collector/__main__.py:265-273 `issue_command`: title for 7; body `kept_meetings`, `corrections` (drop `kept_facts`)
- [x] 5 collector/__main__.py:278 `REFUSED = 4` (unchanged; stays distinct from 7)
- [x] 6 collector/__main__.py:286-305 `shrink_reason` (offline): sha256 correction rule
- [x] 7 collector/__main__.py:308-317 `_verified`, `lost_verified`: per source document, sha-aware (G1)
- [x] 8 collector/__main__.py:320-323 `lost_message`: per kept document
- [x] 9 collector/__main__.py:326-331 `refuse` (offline message)
- [x] 10 collector/__main__.py:355,369-372 `allow` and the offline guard call
- [x] 11 collector/__main__.py:373-381 online keep: replace `facts = old` with the per-meeting merge; write the merge
- [x] 12 collector/__main__.py:390-391 `run_rpc(..., allow_shrink=allow)`
- [x] 13 collector/__main__.py:401,403 `site_build(FACTS)`, `export_site(facts)`: both must see the merged facts
- [x] 14 collector/__main__.py:406-409 run-log fields (`facts_changed`, `kept_meetings`, `corrections`)
- [x] 15 collector/__main__.py:417-429 exit precedence, KEPT stderr lines, RPC mapping, issue print
- [x] 16 collector/__main__.py:452-453 `--allow-shrink` help (says offline only; now online too)
- [x] 17 collector/verify.py:136 `gates(facts, source_error_ids)` called on the merged facts
- [x] 18 collector/facts.py:198,268 id scheme (read only: why a correction renames ids; unit assertion here or in the guard)
- [x] 19 collector/rpc.py:61 step codes (unchanged; must not collide with 7)
- [x] 20 collector/rpc.py:105-108,140 `hold_motions` (unchanged; G4)
- [x] 21 collector/rpc.py:404-431 `shrink_reason`: motion correction rule (G4 i)
- [x] 22 collector/rpc.py:477-480,532-536 guard call and `--allow-shrink` arg (unchanged)
- [x] 23 .github/workflows/daily-update.yml:23-28 `workflow_dispatch.inputs`: add `allow_shrink`
- [x] 24 .github/workflows/daily-update.yml:117-155 Collect step: code comments 128-140, `env`, command 142, mapping 146-154 (7 and `.rpc.exit`), outputs, final check 155
- [x] 25 .github/workflows/daily-update.yml:190-205 failure issue: 7 must never reach it (the step succeeds)
- [x] 26 .github/workflows/daily-update.yml:209-242 RPC issue step: also fires on 7 with `rpc=failed`
- [x] 27 .github/workflows/daily-update.yml (new step after 242): county kept-meetings issue
- [x] 28 .github/workflows/daily-update.yml:271-272,312 upload `if: success()` and push `if` (7 still publishes; `allow_shrink` commits from main only)
- [x] 29 docs/ops/launch-runbook.md:21-36 exit codes: add 7, the kept-meetings issue, when to dispatch `allow_shrink`
- [x] 30 docs/architecture/pipeline-limits-invariant.md: this rule, fix item C, test plan C
- [x] 31 collector/tests/test_run.py:116-118,161,213,231-264,285 (231-264 asserts exit 3 and the whole file kept: rewrite)
- [x] 32 collector/tests/test_pipeline_limits.py:137,230-256 (249-256 asserts `cmd_run` source text: update), 262-300 RPC guard; collector/tests/test_fin_export.py:196-206,232-247 offline `shrink_reason`/REFUSED
- [x] 33 tests/test_rpc_daily.py:483-519 (518 asserts code disjointness: add 7), 530-541 Collect step lines, 544-568 RPC issue `if`; tests/test_workflow_lock.py:77-126 (expression evaluator: `inputs.allow_shrink`), 404-415 issue-step pattern

Checked, no change: .github/ISSUE_TEMPLATE/correction.yml (the public correction form, not a run issue),
collector/rpc_export.py:10 and qa/site_checks.py:47 (read `hold_motions`, not exit codes), collector/city_run.py:38-39
(the city's own 2/5).

**Tests the fix must add (one line each):**
- `test_guard_correction_new_sha_wins`: same meeting, new source sha256 -> new reading written, `corrections` entry;
  exit 7 when the verified count fell, 0 when it held.
- `test_guard_transient_loss_keeps_only_that_document`: same sha, one roll call unverified -> that document's records (both meetings of a two-meeting book)
  byte-identical to committed, another document's change is written.
- `test_guard_missing_source_kept`: committed document absent because it failed to parse or is not in the store -> kept.
- `test_guard_other_sources_still_publish`: guard fires -> finance, agendas, RPC and city files written, site built
  from merged facts, exit 7 not 3.
- `test_guard_gates_run_on_merged_facts`: a kept meeting cannot fail `verified_rate_gate`.
- `test_kept_exit_7_and_issue`: exit 7 and run-log `kept_meetings`; the Collect step maps 7 to `kept=yes`,
  `county=0`; the kept-meetings issue step opens then comments (`--body-file`, backticks stripped, no `${{` in `run`).
- `test_kept_with_rpc_failed_opens_both_issues`: exit 7 with run-log `rpc.exit` 5 -> `rpc=failed` too.
- `test_allow_shrink_dispatch_only`: the input defaults false; `--allow-shrink` is added only for workflow_dispatch
  with `true`, never on schedule; with it the new result wins and the exit is 0.
- `test_repeated_trip_day_n_plus_1_not_frozen`: two runs in a row with the same trip -> both exit 7, facts.json
  bytes identical after run 2, other sources' new data published both days, issue commented, not recreated.
- `test_rpc_motion_correction_not_a_loss`: an RPC motion whose minutes `source_id` changed is not refused.
- `test_guard_unit_assertion`: a roll call whose `source_id` differs from its meeting's raises with a clear message.

**Implementation notes (backend-engineer, 2026-11-11; G1-G4 done, G5 and item E not in this change).**
`collector/__main__.py`: `shrink_guard` (G1, with `check_unit`, the unit assertion, raising `GuardUnitError`),
`keep_documents` (G2.1), `gate_report` (G2.3, shared with `cmd_build`), `KEPT = 7`; `collector/rpc.py`:
`minutes_corrections` (G4 i, also reported as `rpc.corrections` in run-log.json). Tests:
`collector/tests/test_shrink_guard.py` (the 11 above). Choices the text left open:
- A document whose sha256 is gone while only **some** of its meetings are present is treated as (c), kept: one of its
  meetings would otherwise be dropped (I-1).
- The kept set is closed over both files (a kept meeting's new source, that source's other meetings, ...), so a meeting
  is never shown twice when a meeting moves between documents.
- `coverage.from/to` are recomputed over the merged meetings (body from the new result), so a kept first or last
  meeting stays inside the stated coverage. Identical to the new result's whenever no kept meeting lies outside it.
- Under `--allow-shrink` a correction that lowers the verified count does not raise 7 either (a person accepted the
  downgrade); the would-be kept documents go to run-log.json `allowed_shrink` and stderr `ALLOWED` lines.
- The committed file is checked by `check_unit` too, so a hand edit that breaks the unit fails loudly.

`check_page`'s `page > MAX_OCR_PAGES` breaks rules 1, 3 and 4: a page index is not a cost, the comment's
"largest real document: 51 pages" was measured on RPC files only, and the trip only adds a reason to the roll call.

## Every limit, its consumers and its margin
Measured 2026-11-11 from the committed `data/` on this branch (sources' `pages`, manifests' `bytes`, roll calls'
`reading_used`). No store was reachable from this sandbox (`data/store/`, `RECORDS_STORE` absent) and tesseract is not
installed here, so wall-clock times are **unmeasured**: the test plan measures them.

| # | Limit (file:line) | Consumer of its result | Largest real input | Cap | When it trips, published facts | Verdict |
|---|---|---|---|---|---|---|
| L1 | `check_page` page index `> MAX_OCR_PAGES` (ocr.py:42); **removed 2026-11-11** (only `page < 1` is refused) | `ocr_page` <- `reverify` (county roll calls, minutes.py:436), `zoning_readings` (minutes.py:481), `rpc_agenda.ocr_document` | county minutes 621 pp (16 of 59 sources > 200 pp); OCR read used on page 519 | 200 | verified roll call -> unverified silently: rc-30a9df8f-p519-0, rc-7325525d-p241-0, rc-facc1d25-p308-0 today; zoning tesseract readings past p200 lost | **Must-fix: remove** |
| L2 | `check_page` box `> MAX_PAGE_PTS` 2592 pt (ocr.py:55) | same as L1 | 804 pt (ocr.py comment, store, 2026-11-11; not re-measured here) | 2592 pt (3.2x) | that page not OCRed; roll call keeps text-layer status, reason added | keep; add report (rule 3) |
| L3 | `pdftoppm -x0 -y0 -W/-H` = `ocr.MAX_PAGE_PX` 10800 px (ocr.py:77) | the PNG tesseract reads | 804 pt = 3350 px at 300 dpi | 10800 px (3.2x) | none for pages within L2 (byte-identical render, reviewer checked on poppler 24.02) | keep |
| L4 | `PAGE_INFO_TIMEOUT` 60 s, pdfinfo -box (ocr.py:44) | `check_page` | unmeasured (one page) | 60 s | page refused, as L2 | keep; measure |
| L5 | `OCR_TIMEOUT` 600 s, pdftoppm and tesseract (ocr.py:78,81) | `ocr_page` | ~2 s/page tesseract (docs/research/m0-parse-spike.md:145); render unmeasured | 600 s | that roll call's OCR reading missing; reason added | keep; add report |
| L6 | `rpc_agenda.ocr_document` whole-doc `pages > rpc_agenda.RPC_MAX_OCR_PAGES` (rpc_agenda.py:363) | RPC scanned agendas/minutes (107 OCR sources) | 90 pp (cmc-rpc/rpc.json) | 200 (2.2x) | whole document not read; `problems` gets "OCR failed"; its cases/motions missing | keep, but rename `RPC_MAX_OCR_PAGES` in rpc_agenda.py (not shared with ocr.py) |
| L7 | `minutes.MAX_PAGES` 1500 (minutes.py:31; was 1000) | `parse_minutes` (county) | 621 pp | 1500 (2.4x) | document is a parse failure; its meetings drop -> shrink guard refuses offline | raised to 1500 2026-11-11, comment cites 621 |
| L8 | `extract.PARSE_TIMEOUT` 120 s, pdftotext -layout (extract.py:20) | county `cached_pages`, city build, finance, rpc text | 621 pp county; 493 pp city; time unmeasured | 120 s | document parse failure (county: shrink guard; city/fin/rpc: logged) | keep; measure |
| L9 | `pdfwords.PARSE_TIMEOUT` 120 s, pdftotext -bbox (pdfwords.py:101) | `fin_facts.pdf_words` -> fin_budget, fin_bidtab | finance 176 pp; time unmeasured | 120 s | book/bid tab not read; budget-book guard problem | keep; measure |
| L10 | `county_agenda.first_pages` 120 s, pdftotext -f1 -l6 (county_agenda.py:333) | county agenda items (agendas.json) | 6 pp of 270-pp agendas | 120 s | agenda not read | keep |
| L11 | `LIST_PAGES` 6 (county_agenda.py:318) | agenda item list | items end on page 2 (agendas.json, 14 agendas) | 6 (3x) | items after page 6 missing silently | parse window, not a safety cap; keep, add report when no `ADJOURN`/end is found within it |
| L12 | city `pdf_layer` pdfinfo + pdffonts `city_minutes.LAYER_TIMEOUT` 120 s (city_minutes.py:123,125) | `text_layer` of city sources | 493 pp; time unmeasured | 120 s | file left out of the city build (test_parser_caps:72) | keep; name the constant; add report |
| L13 | `city_build.PDFINFO_TIMEOUT` 120 s (city_build.py:118) | `pages` of city sources | as L12 | 120 s | as L12 | keep |
| L14 | `fin_facts.PDFINFO_TIMEOUT` 120 s (fin_facts.py:29) | `pages`, `text_layer` of finance sources | 176 pp | 120 s | `text_layer: unreadable`, no values, guard problem, not cached | keep |
| L15 | `rpc_agenda.pdf_page_count` `rpc_agenda.PAGE_COUNT_TIMEOUT` 60 s (rpc_agenda.py:341) | `pages` of RPC sources; L6 input | 90 pp | 60 s | `pages: None` -> document not OCRed, no cases | keep; add report |
| L16 | `fetch.MAX_BYTES` 200 MiB = 209,715,200 (fetch.py:65; was 50 MiB) | every fetch: store, all pipelines | **52,041,095 B** (city agenda 2021-10-28; next 50,499,119 B), clarksville-tn manifest | 200 MiB (4x; was 50 MiB, 1.007x) | `FetchFailed`: file not stored; city run logs and exits 0 | raised to 200 MiB 2026-11-11 (body held in memory, fine on runner); trips reported |
| L17 | `MAX_REDIRECTS` 5 (fetch.py:63) | every fetch | not recorded in manifests | 5 | `FetchFailed` | keep (politeness/security, not a parse cap) |
| L18 | `PoliteFetcher.timeout` 120 s per request (fetch.py:180) | every fetch | not recorded | 120 s | `FetchFailed` after one retry path | keep |
| L19 | `civicclerk.MAX_PAGES` 200 listing pages (civicclerk.py:28) | city CivicClerk listing | ~11 pages (154 events, ~15 per page per docs/research/committee-sources-2026-11-11.md:199) | 200 (18x) | `EventsError`, listing failure, exit LISTING_FAILED, old listing kept | keep (already rule 3) |
| L20 | `rpc.DAILY_FETCH_CAP` 40 requests (rpc.py:66) | RPC store fill | n/a (politeness) | 40 | exit 6 "store still being filled", rpc.json unchanged | keep (already rule 3) |
| L21 | `rpc_minutes.PARA_MAX` 900 chars (rpc_minutes.py:189) | RPC motion window | not measured | 900 | a motion whose outcome is farther is not confirmed (fails toward "not confirmed") | parse window; keep (rpc-motion-invariant rule 1 already scans past it) |
| L22 | `proxy_status_failures` `timeout=5` (fetch.py) | attributing a 403 to the sandbox proxy | local status page | 5 s | status unread: a 403 counts as the site's (fails toward stopping the host) | keep (not a parse cap) |

Out of scope (not on the parse path; each already fails loudly or marks a cut): `sitegen/config.py` PAGE_BYTES (splits,
drops nothing), sender `MAX_PLAN_BYTES`, `MAX_RESPONSE`, `MAX_PAGES`, `MAX_TITLE` (marked CUT), `MAX_BODY`,
`MAX_SUBJECT`; `qa/` timeouts; `tools/` map extractors (maps are 1728 pt, never OCRed).

## Recommended fix (backend-engineer)
A. **L1 must-fix.** Delete the page-index cap from `check_page` (keep `page < 1`). Per-page cost is already bounded by
   L2, L3 and L5. **No per-document OCR job cap** in the county path: jobs per document are at most its page count,
   which L7 already bounds; a second number would have to track L7 and adds a new way to drop readings. Move the
   whole-document cap into rpc_agenda.py as `RPC_MAX_OCR_PAGES = 200` (real 90). Fix the ocr.py comment: "real stored
   pages: letter/legal, largest side 804 pt; largest documents 621 pp county minutes, 90 pp RPC (2026-11-11)".
B. **Rule 3 report.** `PageRefused` and every `TimeoutExpired` raise or record `limit <NAME>` with file, page, value and
   cap; the county, city, RPC and finance run summaries print a `limits tripped: N` line (0 is printed too).
C. **Rule 3 guard.** Extend `collector/__main__.py:shrink_reason` (and `rpc.py:shrink_reason`) to refuse a result in
   which a roll call (motion, for RPC) verified/confirmed in the committed file is no longer, listing the ids;
   `--allow-shrink` overrides. This is what turns any future too-tight limit into a refusal instead of a silent drop.
   **Superseded at hit 3:** per source document, with warning exit 7; see "Rule 3: the shrink guard" G1-G5.
D. **L7** to 1500, **L16** to 200 MiB, each comment citing its measured largest input.
E. **Later, separate PR (two LOWs from the same security review):** `pipeline/ocr-run-time-unbounded`: a per-run
   OCR deadline in `minutes.ocr_pages_parallel` (minutes.py:353), jobs past it skipped uncached and reported as
   `limit minutes.OCR_RUN_DEADLINE`; `pipeline/child-memory-unbounded`: `RLIMIT_AS` about 2 GiB on each child in
   `limits.run` (limits.py:84, `preexec_fn` or a `prlimit` wrapper). **Not bundled now:** each diff is small (about
   20-40 lines with tests), but each is a *new* limit that rule 1 says needs a measured 2x margin (cold-cache OCR
   wall time; tesseract's peak address space on the largest 804 pt page), neither can be measured here (no
   tesseract, no store), and a too-tight one unverifies real votes, which is only safe once the per-meeting keep has
   merged. Land them after it, measured on the runner, under their own keys.
A is the must-fix; D's L16 is a new must-fix under the same key family (`pipeline/fetch-cap-no-margin`). B and C can
land in the same PR or the next; the manager decides. Assumption: 2x margin is enough for this corpus (judgment call,
medium confidence). The bigger lesson from L1 is to measure across **every** consumer of a shared constant: 51 pages
was true for RPC and wrong for county minutes.

## Test plan: "real largest input passes", one per limit
Fixture-light: synthetic PDFs where noted; `@pytest.mark.store` tests skip without the store and run on Brian's PC/CI.
- L1: `check_page(pdf, 519)` on a 621-page synthetic PDF (letter pages) does not raise; `reverify` of a roll call on
  page 519 calls `ocr_page` (no `PageRefused`). Store test: rc-30a9df8f-p519-0 stays verified on a rebuild with an
  empty `data/ocr/`.
- L2/L3: a 612x1008 pt (legal) and an 804 pt page pass and render byte-identical to the uncropped call (exists; keep).
- L4/L5/L8/L9/L10/L12-L15 (timeouts): store test times each tool on the largest stored file of its consumer (621-pp
  county minutes, 493-pp city, 176-pp finance, 270-pp agenda first 6 pages, 90-pp RPC, slowest OCR page) and asserts
  it finishes in under half its timeout; record the times in the constant's comment.
- L6: `ocr_document` with 90 pages renders all 90 (mocked `ocr_pages_parallel`), 201 is refused (exists).
- L7: `parse_minutes` accepts a 621-page text cache; 1501 is refused.
- L11: every committed agenda's last item page <= LIST_PAGES - 2 (data/county-agendas/agendas.json).
- L16: a mocked 52,041,095-byte body is stored; cap + 1 raises `FetchFailed` and is reported as a limit trip.
- L19: a 154-event, 11-page mocked listing is read whole (exists in spirit; assert page count).
- C: a rebuild that turns one committed verified roll call unverified is refused offline with its id named;
  `--allow-shrink` lets it through. Online: the tests listed under "Rule 3: the shrink guard".
- Meta: a test lists every `timeout=` and `MAX_*`/`*_CAP` in collector/ and fails when one is not in this table
  (grep-based), so a new limit cannot skip the margin check. Done: collector/tests/test_pipeline_limits.py
  `test_every_limit_is_in_the_invariant_table` (2026-11-11).
