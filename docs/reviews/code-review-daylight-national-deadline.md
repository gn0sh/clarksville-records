# Code review: daylight-national run deadline and freshness stamps (4.4.4-4.4.6)
Reviewer: code-reviewer (independent, opus/xhigh), 2026-11-19. Diff dc435ed..8fcdf6d (f57a5e4, 09cab61, 8fcdf6d), judged against the 4.4.4-4.4.6 invariants.
Verdict: **APPROVE WITH NITS.** Finding 1 lands in this PR (option a); option b goes to the backlog.

## Tests and lint (run by the reviewer)
- Targeted (`test_fetch*.py`, `tests/test_national_*.py`, `test_pipeline_limits.py`): 1103 passed.
- Full suite: 6991 passed, 5 skipped (3251 s). Clarksville fetcher users: 643 passed, 1 skipped. ruff clean on 6 changed files. No non-national test edited.

## Findings
| # | Severity | Key | Where | Problem | Fix |
|---|---|---|---|---|---|
| 1 | should-fix | national-budget/chunked-framing-drip | fetch.py:467-483 `_read_answer`, comments :104/:469; arch 4.4.4 X, section 8 risk row | On `Transfer-Encoding: chunked`, `read1` reads chunk-size lines/extensions (up to 64 KiB) and the whole trailer with `readline`: many socket reads, each up to T. No clock check after the last empty read. Probe (T=A=1 s, drip 0.5 s): Content-Length FetchFailed at 1.0 s; chunk-extension and trailer drips returned `b'[]'` at 6.0 s. Send invariant holds; the X = 360 s bound and margin don't for chunked answers. | (a) section 8 / 4.4.4 residual covers chunked framing; fix the two comments; add a final `clock() - t0 > A` check after the loop. (b) backlog: enforce A below http.client (raw reader or per-request watchdog with `sock.shutdown`). |
| 2 | nit | national-budget/hook-overflow | run.py:410 | `timedelta(seconds=pause)` overflows on a huge robots Crawl-delay: collector-error instead of budget-skipped (pre-existing). | `pause >= (deadline - stamp_of()).total_seconds()`. |
| 3 | nit | national-freshness/fallback-drops-kept-feed | run.py:462-468 | When `_read_one`/`_record` raises, the kept feed is dropped and `bodies/<id>.json` deleted with no request sent (pre-existing; unreachable with a valid directory). | `feed = _kept_feed(previous_feeds.get(gov), entry, None)` in the except branch; document the `consecutive_failures: 1` fallback. |
| 4 | nit | fetch/clarksville-spy-200-only | test_fetch_deadline.py:60-69 | Spy pins only the 200 read. | Add spied 404 and 403: `("read", max_bytes+1)`, `("read", BLOCK_BODY_BYTES)`. |
| 5 | nit | fetch/slow-log-misplaced | fetch.py:573-575 | `except FetchFailed` logs "answer too slow" for any error-body FetchFailed; a slow 200 logs nothing. | Log inside `_read_answer` when it raises; drop the clause. |

Family count: only finding 1 counts as a national-budget hit (2 and 3 predate this diff).

## What held
- Clarksville identical with both fields None: same clock()/sleep calls in `_wait`, no t0 clock call, `_read_answer` is one `r.read(limit)` for all three reads, `read1` untouched, new fields after `reset_retries`.
- No request at or after D on every path (robots and hops, 5xx/reset retries, redirect hops all re-enter `_raw_get` after `_wait`; `>=` before and after sleep; caps raise before `_wait`). Tested incl. probe2, exact-D and 25/30/31 s.
- Refused requests change nothing (`_last`, `_sent`, `_tenant_sent`). Hook installed after prune, restored in finally (return and raise tested). `_check_deadline` before `check_host_ok` and any file access.
- Freshness: stamps only when `remaining_tenant` dropped; every pre-send path returns None; retry refused after a sent request stamps the attempt only; `ok` stamped at its start; `_fallback_record` keeps previous valid stamps (except finding 3).
- `ok` with no tenant request -> collector-error is right (4.4.5; unreachable with the real reader; exit 3 surfaces it).
- 4.6 D1 logs: new text carries only host and URL and goes only to `fetcher.log`/exception text, never printed by the CLI.
- Observation: a sandbox ProxyRefused counts as "sent" (`_tenant_sent` bumped before `_open`); Actions has no agent proxy.

## Delta re-review (50e8215..6729e88; f3280cf, 6729e88), 2026-11-19
Verdict: **APPROVE WITH NITS.** Targeted suite: 1109 passed. Clarksville fetcher users: 888 passed, 1 skipped. ruff clean.
- Finding 1, `national-budget/chunked-framing-drip`: closed. The clock is checked after the last read, so a dripped chunked answer fails the fetch (real-socket test, both modes). Comments corrected. Residual recorded in 4.4.4 and section 8; enforcing `A` below http.client is on the backlog.
- Finding 2, `national-budget/hook-overflow`: closed. The hook compares seconds and gives the same answer at `D`.
- Finding 3, `national-freshness/fallback-drops-kept-feed`: closed (test); count-of-1 rule documented.
- Finding 4, `fetch/clarksville-spy-200-only`: closed (404 and 403 reads pinned).
- Finding 5: closed. "answer too slow" logged once, in `_read_answer`.
- Clarksville with both fields None: unchanged (`r.read(limit)` returns before any new code).
- New nit, `national-freshness/fallback-checked-at-lags-attempt` (run.py:470): if `_record` raises after a read that sent requests, health `last_attempt_at` moves while the kept feed's `checked_at` stays old. Fix: `_kept_feed(..., stamp)` instead of `None`.
