# Pipeline limits invariant (loop rule: `pipeline/` hit 2)
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
3. **Reported, not just logged.** A trip appears in the run summary as `limit <NAME>: <file> [page] <value> > <cap>`.
   A trip that turns a published fact from verified/confirmed to not, or drops a meeting, must fail the shrink guard
   like a dropped meeting does (`--allow-shrink` to accept it deliberately).
   Each step's summary and report list only that step's own trips (`limits.mark()` at the step's start), and a
   timeout's value is the cap reached (`120s+`), so the same trip twice in a step is one line.
   **Decision (manager, 2026-11-11), online runs too:** when a county run (online or offline) would turn a roll call
   verified in the committed `data/facts.json` into unverified or drop it, the committed facts file is kept
   (not written; the export and site steps use it), the ids are named, and the run exits 3 so it fails loudly and
   opens the usual issue (`kept_facts` in its body). Offline, the run is refused before anything is written, as
   before. `--allow-shrink` accepts the change. RPC: the daily step refuses a result that unconfirms a committed
   confirmed motion, except while rpc.yml `hold_motions` is on (nothing is published confirmed).
4. **Bound the cost, not the position.** A cap limits what one unit can cost (memory, time). It never limits *where* in
   a real document we may read (a page index, a byte offset), because position is not cost.

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
D. **L7** to 1500, **L16** to 200 MiB, each comment citing its measured largest input.
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
  `--allow-shrink` lets it through.
- Meta: a test lists every `timeout=` and `MAX_*`/`*_CAP` in collector/ and fails when one is not in this table
  (grep-based), so a new limit cannot skip the margin check. Done: collector/tests/test_pipeline_limits.py
  `test_every_limit_is_in_the_invariant_table` (2026-11-11).
