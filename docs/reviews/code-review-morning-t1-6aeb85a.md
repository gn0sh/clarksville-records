# Code review: morning note T1 (daily digest), commit 6aeb85a

Branch `origin/claude/sqv6p9-morning-t1`, diffed against the merge-base with `origin/claude/project-thread-sqv6p9`
(8 files, +1038/-9). Reviewer: code-reviewer (read-only), 2026-11-10.

**Verdict: REQUEST CHANGES** (2 must-fix, 2 should-fix, 6 nits)

## Most serious problem
`morning-digest/vote-meeting-date` (must-fix). On real data 59 county vote entries carry the wrong `meeting_date` (and
the fallback label/href comes from the wrong meeting). Evidence: in `data/facts.json` 5 minutes sources are shared by two
meetings (e.g. `src-7325525d58ca` is the `source_id` of both `2020-02-10-formal` and `2020-03-09-formal`).
`_index_documents` maps each source to the first meeting that names it (`sitegen/morning.py:237-240`), then stamps every
roll call and motion in that source with that meeting's date (`:264`, `:260` label, `:272` href). Example built note:
`county/vote/rc-7325525d-p7-0` says `meeting_date: 2020-02-10`; the roll call's own `meeting_id` is `2020-03-09-formal`.
On a site whose rule is that every fact matches its source, the note would tell a reader a vote happened on the
wrong date. (The fixture has no shared sources, so the tests can't catch this.)
Fix: take the meeting from each fact (`ix.meetings[fact["meeting_id"]]` for roll calls and motions, `e["meeting_id"]`
for item events) for `meeting_date`, the id suffix, the label and the href. Keep `by_source` only to find the document
URL. The "no entries" fallback should emit one `document` entry per (source, meeting). Add a fixture test with two
meetings on one source.

## Findings
1. must-fix `morning-digest/vote-meeting-date`, `sitegen/morning.py:237-240, 260, 264, 272, 284-285, 292-295`. See above.
2. must-fix `morning-digest/preview-export-links`, `sitegen/build.py:721-727` together with `sitegen/fin_views.py:294`
   and `sitegen/budget_views.py:264`. When the preview drops the export, `finance/index.html` and
   `contracts/index.html` still link `../data/{finance.json,budget_lines.csv,budget_checks.csv,solicitations.csv}`. The
   real data reaches this path today: the preview has 504 files with the export, 503 without the transcript pages, so it
   goes over the 500 cap and rebuilds with `export=False`. I built that preview with the cap lowered to 480; it took the
   same path and `qa.site_checks --target preview` returns **FAIL links** with 5 missing data/ files. The test only checks
   data.html and about.html. Fix: pass `export` into the finance/contracts contexts (`exports=EXPORTS_READY and not
   fixture and export`, or read `site.export_omitted`) and extend
   `test_preview_still_over_its_cap_leaves_the_export_out` to check that no page links `data/`, or run the links check.
3. should-fix `morning-digest/preview-stale-export`, `sitegen/build.py:176-184` (`_clean`) and `:712-713`. With
   `export=False`, an earlier export in `out/data/` is left in place. The documented preview recipe reuses `build/site`
   (status.md, preview v4: sitegen plus collector.export), so this is the normal case. I reproduced it: a fixture
   preview with 12 old files in `data/` and the cap set to `files_with_export - 1` raises `BuildError: site has 92
   files; the limit for the preview target is 90`. If the old files fit under the cap, `publish-files.json` publishes
   stale data that data.html says is not there. Fix: `shutil.rmtree(out / "data", ignore_errors=True)` when
   `export=False`. Optionally write a marker that makes `collector export` refuse that build dir, so the recipe can't
   undo the decision.
4. should-fix `morning-digest/unplaced-count-claims-cases`, `sitegen/morning.py:466, 477`. `unplaced_zoning` counts
   entries, but the config text says "{n} zoning cases printed no district or ward". A case on an agenda and in the
   minutes counts twice. On real data (2026-11-10 note with the guard off) it gives 120 entries but 36 distinct cases,
   so our own text would state a wrong number. Fix: count distinct case numbers (or case ids), or change the text to
   count entries. Test it with the same case on an agenda and in minutes.
5. nit `morning-digest/vote-entries-indistinct`, `sitegen/morning.py:260-273`. Several votes on one item (for example
   an amendment and then the main motion) give entries with the same title, date and "Recorded in the minutes", and
   possibly different outcomes. The 2026-11-08 note has 54 such duplicate keys. Consider carrying the record's own
   motion kind (it is stated in the record, so it doesn't break neutrality) so the sender/T3 can tell them apart.
6. nit `morning-digest/window-single-source`, `sitegen/morning.py:170-174`. `note_day` compares local wall-clock time
   while `window` uses aware instants. They disagree for a cutoff inside the repeated fall-back hour (01:00-01:59).
   That can't happen with "07:00", but derive `note_day` from `window()` so there is one rule. No test crosses a DST
   change; add one for 2026-11-01 (a 25 h window) and for 2026-03-08 (a 23 h window).
7. nit `morning-digest/own-text-scope`, `sitegen/morning.py:480-486`. `own_text` says it covers "every string of the
   note that is ours", but it leaves out titles we write: `ix.meeting_label(m)` (`:260, :293`) and the agenda-only
   fallback `f"{date}, {kind}"` (`:331`). The risk is low because both come from config labels. Add them, or flag a
   generated title so the scan can include it.
8. nit `morning-digest/tests-vacuous`, `tests/test_morning.py:139-148`. The 06:59/07:00 test passes even when neither
   branch runs. Assert that each branch matched at least one roll call. The preview tests build into a fresh directory,
   so they miss findings 2 and 3.
9. nit `morning-digest/data-as-of`, `sitegen/build.py:691-693`. `data_as_of` leaves out the county-agendas and finance
   fetch dates, and all 7 notes get the same build-wide value. Either document that or compute it per note.
10. nit `morning-digest/manifest-errors`, `sitegen/morning.py:138, 152-153`. A manifest row with no `url` raises a bare
    KeyError, not a MorningError/BuildError. `bulk_urls` re-parses the files without checking them. Have it reuse
    `first_fetched`'s parse.

## What I checked and found sound
- Window rule: [D-1 07:00, D 07:00) Central uses aware datetimes and `datetime.combine(..., zone)`. 07:00 is never in
  a DST gap; the stamps come out as `-06:00`/`-05:00`. The 09:07 UTC run (03:07 or 04:07 local) is inside the window.
- Empty day: writes `entries: []`. Real data, built for 2026-11-11: the 11-08, 11-09 and 11-10 notes are backfill
  (390, 2242 and 1548 entries held back), the 11-11 note is empty, and nothing would mail. The backfill guard works on
  all four real manifests. The per-document entry counts on real data (p90 at most 16, max 58) put normal days well
  under 100.
- Neutrality: no mover, seconder, nays or per-official vote in any note (fixture and real). Confirmed RPC outcomes are
  the minutes' own text, and I checked the distinct values for names. Unconfirmed votes carry no outcome or tally.
  Some verbatim titles name officials (e.g. "Honoring Councilman Bill Powers"). That is allowed: item titles are exempt
  from the name-links rule (`qa/site_checks.py:24-26`, data-item-title). T3 must render them with `data-item-title`.
- `select()` matches the architecture (seats by `seat_body`, zoning by printed district or ward only, budget and
  contracts by membership). `link_county` inheritance uses only exact keys from the county prefixes.
- Provider seam: `enabled: false`, any form_action refused while off, https URLs required when on. Wired into
  `site_url_problems`. Nothing sends mail.
- Pages-only: the preview writes no `morning/`. On pages, `morning/` counts toward the cap (512 of 3000 on real data).

## Tests
- `tests/test_morning.py`: 29 passed in 2.93s.
- Full `tests/` suite: 1051 passed, 4 skipped in 496s.
- `qa.site_checks` on the real-data preview built with `export=False`: FAIL links (finding 2).
- `collector/tests` not run (the diff doesn't touch collector/).

## Assumptions
- I reviewed against architecture "T1 additions" and the T1 task as written.
- I treated the preview's dead links as must-fix because the real data reaches that path today, not just in theory.
