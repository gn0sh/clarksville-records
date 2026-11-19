# Code review: daylight-national D1 collect CLI (cbeaab4..f2102fe)
Reviewer: code-reviewer, 2026-11-19. Verdict: **APPROVE**. Finding 1 (should-fix) to be fixed before the D1 workflow passes `--budget` above 300.

Scope: collector/national/__main__.py (new), collector/national/run.py (`HostNotApproved.gov`), tests/test_national_cli.py, docs/architecture/daylight-national.md 4.6 "As built". Judged against arch 4.6 (D1 fetcher, D1 logs, D1 data path), 11.1 row 23 and ADR 0013 decision 6.

## Findings
| # | Severity | Key | Where | Problem | Fix |
|---|---|---|---|---|---|
| 1 | should-fix | national-budget/max-no-margin | __main__.py:39, :10-12; arch 4.6 :613 | 450 x 10 s is the whole 75 min, with no margin for setup, latency (120 s request timeout) or the commit step. A killed run writes nothing, so the order repeats and the data can stay stale indefinitely. | Cap at about 360-400, or derive it from timeout minus a setup margin over MIN_DELAY. State the margin in the docs and update the 451 test. |
| 2 | should-fix (architect, pre-existing) | national-budget/no-wall-deadline | run.py `run()`; fetch.py:620 | Only a request count limits the run. A robots.txt Crawl-delay above 10 s overruns even 300 requests. | Add a wall-clock deadline in `run()`: remaining bodies are recorded as budget-skipped and the outputs are still written. |
| 3 | nit | cli-exit/silent-all-failed | __main__.py:121-128 | A run where every body is collector-error or host-stopped exits 0. | Optional: a separate exit code after the writes when collector-error > 0 or ok == 0. |
| 4 | nit | cli-log/argparse-echo | __main__.py:66 | argparse echoes unknown argv (from the workflow, not fetched data) and allows abbreviations. | `allow_abbrev=False`. |
| 5 | nit | cli-test/usage-error-stderr | tests/test_national_cli.py:262-267 | The bad-budget test does not assert that stderr leaves the value out. | Assert the value is not in `capsys.readouterr().err`. |

## Checked and holding
- The fetcher kwargs are exact and asserted by a test. The Clarksville defaults never reach it.
- `check_data_root` and the not-a-file check run before any fetcher or request (tested for the root, `bodies/` and `cache/` cases, and a root that is a file).
- Output carries only ids that pass `id_layer`, 3.7 kinds and counts. Failures carry only the type name and a checked body id. Chained exceptions, KeyboardInterrupt (130), excepthook, unraisablehook and broken pipe were all checked.
- No print, logging, warnings or threads in fetch.py, collector/national, or sitegen national/national_guards.
- Budget default 300 matches ADR 0013 decision 6 (about 50 min). The 450 cap is finding 1.
- Exit codes 0/1/2/130 match the docs.
- Tests: the 403 test first proves the secret is in `fetcher.log`, then that it is absent from the output. A subprocess test runs `python -m`.
- 662 passed (`pytest tests/test_national_cli.py tests/test_national_*.py -q`); ruff clean on the changed files.

Assumption: the 75 min timeout applies to the whole job, including setup and commit (the workflow is not built yet).

## Delta re-review: 433a905..5dce3f3 (2026-11-19)
Verdict: **REQUEST CHANGES**.
- Closed: `national-budget/max-no-margin` (cap 360), `cli-exit/silent-all-failed` (exit 3), `cli-log/argparse-echo` (`allow_abbrev=False`), `cli-test/usage-error-stderr`.
- Partly closed: `national-budget/no-wall-deadline`. A long Crawl-delay is now bounded, but slow answers are not (finding 1).

| # | Severity | Key | Where | Problem | Fix |
|---|---|---|---|---|---|
| 1 | must-fix | national-budget/post-deadline-request | run.py:88-95, :415-417; fetch.py:434-436 | The guard is on `sleep`, which runs only when `gap < delay`. With answers of 10 s or more, the body in flight keeps sending after the deadline: up to 12 x 120 s, more than the 15 min margin. Shown by a probe: 5 requests at 30-90 s against a 20 s deadline. | Check the deadline before every request: a default-off `deadline` hook on PoliteFetcher (checked in `_raw_get` before `_wait`), or a run-scoped `remaining` wrapper. Add a slow-answer test. |
| 2 | should-fix | national-freshness/deadline-stamp-without-request | run.py:319-327, `_record`/`_kept_feed` | The body whose first wait is refused gets `last_attempt_at` and its kept feed's `checked_at` set although no request was sent. | When no request was sent, return stamp None, as the cap pre-check does. Test it. Second hit in the `national-freshness` family. |
| 3 | nit | national-budget/frozen-clock-deadline | run.py:393-395 | A `deadline` without `clock` compares against a fixed `now`. | Raise ValueError. |

What held: `sleep` restored on every path (try/finally); no budget used by a refused wait, rest of run `budget-skipped`; failure counts, streaks and `last_ok_at` unchanged for skipped bodies; fetch.py untouched; cap 360; exit-code cases correct; 676 tests passed; ruff clean.
