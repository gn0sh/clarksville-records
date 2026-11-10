# Code review: Morning note T3 (+T2 feeds), origin/claude/sqv6p9-morning-t3 @ 0a7723d

Reviewer: code-reviewer (read-only). Diff: `git diff origin/claude/project-thread-sqv6p9...origin/claude/sqv6p9-morning-t3`
(15 files, +1158/-21). Compared against T1 at origin/claude/sqv6p9-morning-t1 (6aeb85a). Stub 8e89c21 logic not reviewed.

## Verdict: REQUEST CHANGES
One live regression in T2 (the rezoning feed loses every county/council entry). The rest is good work. The other
must-fixes are about the T1 merge: they are not bugs at 0a7723d, but the merge breaks unless they are handled.

## Tests
`python -m pytest -q` (full suite, in a scratch worktree, Python 3.13, node 22, Playwright chromium present):
**1956 passed, 5 skipped in 668.72s**. `tests/test_morning_page.py` + `tests/test_alerts.py`: 56 passed (the browser
test ran, no skips). Real-data builds: pages = 512 files, 41 feeds, every feed parses as Atom, no duplicate ids per
feed, every entry has id/title/updated/link. Preview = 478 files, headroom -6 with export (base branch already -3).

## Findings

1. **must-fix** `feeds/rezoning-keeps-every-body` (sitegen/feeds.py:301-302). RPC zoning cases join
   `topic-rezoning.xml`, and the feed keeps only the 50 entries with the newest meeting dates. Real data: before the
   change the feed had 50 county entries (2023-07-10..2026-04-13); after it, **50 RPC entries, 0 county**
   (2026-04-28..2026-10-27). RPC agendas are dated ahead and come often, while county minutes run months behind. So a
   county or council rezoning item added tomorrow sorts below the 50th RPC case and **never reaches readers of that
   feed**. Ids stay the same, but coverage silently drops. The T2 test passes only because the fixture is under
   max_entries. Fix (the architect picks one): keep RPC cases out of topic-rezoning in a separate
   `topic-zoning-cases.xml`; or let the rezoning feed keep max_entries per body; or sort feed entries by the date they
   were first added to the site. Add a test where RPC cases exceed max_entries and assert that a county entry stays.
2. **must-fix (at merge)** `morning-signup/seats-match-by-seat_body` (site/static/morning.js:19,
   site/templates/morning.html.j2:16, sitegen/morning.py stub :24, site/fixtures/morning.sample.json). T1's
   `_seat_match` decides the "seats" list by `e["seat_body"]` ("district"/"ward"). T3's JS (and the stub) uses
   `body === county_key`. The two give the same answer on T1's current entries, but: (a) the fixture has no `seat_body`,
   so T1's `select()` raises KeyError in the parity test; (b) the template emits `data-body`, not `data-seat-body`, so the
   JS cannot follow T1's rule once a non-county body is ever tied to a district. Fix: add `seat_body` to every fixture
   entry, emit `data-seat-body`, and have the JS `seatMatch("seats")` test `entry.seat_body === "district" ? d : w`
   (with the countyKey argument dropped).
3. **must-fix (at merge)** `morning-preview/pages-only` (sitegen/build.py:673-676). T1 writes the note only on the
   pages target, only with manifests (never for fixture builds), and after the feeds. T3 renders `morning/index.html`
   whenever `morning_page.on()`, on the preview target too, inside the alerts block. After the merge, the preview target
   has no note: either the page renders from nothing, or `alerts.html#note`'s "See today's note" link
   (`#mn-preview`, `data-preview`) points at a missing file and the link check fails. Fix: render the page from T1's
   returned `morning_note` after T1's block, only when it is not None. Drop the preview link and `data-preview` when
   there is no page. This also keeps the preview target 1 file lighter, and it is over its cap already.
4. **must-fix (at merge)** `morning-preview/no-None-text` (site/templates/morning.html.j2:17). T1 sets
   `meeting_date: None` on every budget-book, solicitation and contract-document entry. Jinja prints None as the text
   "None" (checked), so the page would read "Montgomery County, None". Fix: `{% if e.meeting_date %}` around the date
   span, and a fixture entry with `meeting_date: null`.
5. **should-fix** `morning-preview/backfill-day` (sitegen/morning_page.py:126-146). T1's `day()` returns
   `backfill: true, entries: []` on a first-collection day. The preview then says "Nothing new on your list. On a day
   like this no note is sent.", which is false on a day with hundreds of new records. Fix: a config line for backfill
   days (for example "The first collection of a source is not sent as a note"), shown when `day.backfill`.
6. **should-fix** `morning-text/one-source` (config/site.yml `page.unplaced`/`unplaced_one`,
   morning_page.py:134-146). T1 already has `text.unplaced_zoning` and returns `unplaced_text`. Two copies of the same
   connective text will drift. Fix: use `day["unplaced_text"]`, or move singular and plural into T1's `text:` block.
   Also add the `page:` keys to T1's `problems()` (TEXT_KEYS pattern): T3 indexes `m["page"][...]` with no validation.
7. **should-fix** `morning-signup/one-council` (morning_page.py:69-72, morning.js:19). "My two seats" and "zoning by
   ward" read a stored ward as a ward of the one council. `cr-your-seats` keeps no council key, and both T1
   (`seat_body="ward"` for every council) and T3 tag every non-county body feed as `ward`. With
   `councils: [clarksville-tn]` the two agree and give correct results today. A second council would match every
   council's items silently. Fix: a `problems()` rule or test that fails when there is more than one council, until
   seats name a body.
8. **nit** `morning-signup/no-js-feeds` (_morning.html.j2:23). Without JS the per-seat feeds in `#note` stay
   `hidden`. The task says "No-JS: all lists and all feed links shown", and the test asserts the opposite (test:130).
   They are listed in the "Zoning cases by district or ward" section, so this is fine, but record it as a deviation in
   the task or spec.
9. **nit** `morning-fixture/contract-shape`: the fixture council vote has `recorded: "Passed"` (fixture:36). T1 never
   puts an outcome in `recorded` (config `text.vote` / `vote_unconfirmed`). Align it with T1, so the fixture does not
   teach a pattern T1 forbids.
10. **nit** feeds.py:93 contracts `updated` falls back to `fetched_at`, which changes on a re-fetch for the 9
    solicitations with no archive_date. The title "Contracts: bids and awards" is code text, not config ("awards" is
    more than the feed holds). feeds.py:290 `DEFAULT_ZONING_PREFIXES` duplicates the config default.
11. **nit** morning_page.py:21-25: `title()` sits between the constants, and `SECTION` is unused. build.py:668-670
    computes `feed_list` twice (`alerts_page` builds it again). Enabled path: `sent_line` with an empty `provider`
    prints "gives  your email"; require `provider` when enabled.

## What I checked and found sound
- Off state: no `<form>`, no `action`, no email field, no submit, no `name=` on the boxes; no success text on any page,
  in the JS or in the config; the CSP is the same on every page. Enabled (test config only): form-action gains exactly
  one https origin, on alerts.html only; the privacy link and sent line render.
- morning.js: no fetch/XHR/beacon/storage writes; the `#lists=` parser keeps only known keys (regex-anchored); runs
  under node for the parity test; JS select == stub select over 16 list sets x 7 seat cases.
- Accessibility: fieldset + visible legend; the checkbox overlays its pill label (keyboard focus ring tested with
  Space/Tab in Playwright); `[hidden]` is overridden correctly in CSS for the picker and panels; aria-live on the quiet
  line; no sideways scroll at 360 px (browser test); new-tab source links say so to screen readers.
- Escaping: Jinja autoescape on html/j2; Atom built with ElementTree (escaped), XML-illegal characters stripped,
  RFC3339 updated stamps, stable `tag:` ids; 33 per-seat feeds on pages only, none on preview; per-seat membership
  is by printed int district/ward (real data: ints 1-21 / 1-12).
- Neutrality: list labels and connective text come from config; titles are verbatim; no locality name in the new
  templates (existing test); BANNED scan over the fixture day and the preview page.

## Merge-conflict hazards vs T1
- build.py: both branches edit the `from . import ...` lines and the `_clean()` folder tuple (T1 `morning_mod.FOLDER`,
  T3 `"morning"`): textual conflicts. Keep T1's.
- build.py: T3's `morning_mod.day(built_day, ix=..., ...)` vs T1 `day(d: date, docs, first, cfg, data_as_of, bulk)`.
  Use T1's `write()` return value; do not call `day()` again (see finding 3).
- tests/test_morning_page.py:42,178 monkeypatch `morning.day` as `lambda date, **kw`. After the merge the page comes
  from `write()`'s result, and fixture builds produce none, so these tests must patch `morning.write` or pass
  `morning_manifests` plus a fixture manifest.
- Entry shape: `seat_body` (finding 2), `meeting_date: None` (finding 4), `backfill`/`counts`/`unplaced_text`
  (findings 5-6), `href: None` (already handled by `or ""`), `source.url` already carries `#page=N` (fine).
- config/site.yml: T1's block adds `backfill`, `manifests`, `text`. Carry T3's `page:` over. T1's `problems()`
  ignores unknown keys, so `page` passes, but it is not validated.
- Preview target file cap: already 3 over before T3, 6 over after. T1 handles that by rebuilding without the export.
  T3's preview-target morning page goes against T1's pages-only decision.

## Delta re-review 2b4796b
Branch origin/claude/sqv6p9-morning @ 2b4796b (T1 0deb62c + T3 merged in d2986b6, fixes 6968c62 and 89cea87, plus
2b4796b). **Verdict: APPROVE WITH NITS.**

Tests: test_morning_page + test_morning + test_alerts: **132 passed**. test_visual_refresh + test_site_neutrality:
108 passed. Real pages build: 520 files, morning/ has 7 days, latest.json and index.html. `qa.site_checks --target
pages --no-export --no-browser`: **RESULT: PASS** (feeds: 41 feeds, 1246 entries). Without `--target pages` the files
check uses the preview cap and fails, which is expected. Real preview build: 477 files, headroom +23, no morning/,
and alerts.html no longer links the preview page.

| Finding | Status | Evidence |
|---|---|---|
| feeds/rezoning-keeps-every-body | closed | `newest(per_body)` (6968c62); real feed has rpc 50, county 50, city 50; a new test pushes many RPC cases past the cap and the county ids stay |
| morning-signup/seats-match-by-seat_body | closed | JS matches on `seat_body`; `data-seat-body` emitted; fixture in T1's shape; parity test runs against T1's `select()` |
| morning-preview/pages-only | closed | page rendered from `write()`'s note, after T1's block (build.py:704-715); preview target has no page and no link |
| morning-preview/no-None-text | closed | date span guarded; fixture has null dates; real page has 0 "None" |
| morning-preview/backfill-day | closed | today's real note is a backfill day (1548 held); the page prints the `page.backfill` line |
| morning-text/one-source | closed | page prints `unplaced_text`; `text.unplaced_zoning_one` added; `PAGE_KEYS` checked in `problems()`, placeholders included |
| morning-signup/one-council | closed | `problems()` refuses more than one council |
| merge hazards (imports, `_clean`, `day()` signature, test patches, config `page:`) | handled | single import path; `morning_mod.FOLDER`; tests patch `morning.write` and make a second `day()` call fail |
| nits 8-11 | closed or recorded | contracts title is now config `alerts.contracts_title`; provider required when enabled; no-JS deviation written in the tasks doc |

Commit 2b4796b (qa.site_checks): correct and needed. Without it the pages build fails its own feeds check (150
rezoning entries; the contracts feed links finance sources). Its tests copy the site to a fresh folder for each test,
so nothing leaks between them. New findings, nits only:
- `qa-feeds/per-body-list-one-source` (nit, qa/site_checks.py:1065): `PER_BODY_FEEDS` repeats the rule in
  sitegen/feeds.py:322 (`kind == topic and key == rezoning`). Export a `feeds.PER_BODY_FEEDS` and use it in both
  places, so they cannot drift apart.
- `qa-feeds/finance-sources-scope` (nit, qa/site_checks.py:1457): finance sources are now allowed for every feed,
  not only topic-contracts.xml. A body feed that wrongly linked a finance PDF would pass. Low risk; scope them to the
  contracts feed if it is cheap.
