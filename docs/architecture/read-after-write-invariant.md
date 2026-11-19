# Read-after-write invariant (loop rule: `data-off-main/read-after-write` hit 2)
software-architect, 2026-11-19, at `claude/data-off-main` adfd307 (PR #65). Hit 1: cutover run 4 stopped at step 2 (the
disable worked; the read in the same second said `active`), fixed in adfd307 (`wf_set`/`WfSet`). Hit 2: code review of
adfd307 found the same race at step 4 and elsewhere. This page states the invariant and lists every consumer before the
next fix. Scripts are not changed here. Line numbers are at adfd307.

## The invariant
After any write to GitHub, the read that confirms it must tolerate replica lag, and lag may only **delay** a result,
never **accept** a wrong one.
1. **Retry the read, never the write.** Read up to 10 times, 3 s apart (about 27 s). The write is sent once. One exception
   is a `POST pulls` that gets HTTP 422 (rule 6).
2. **Exact match only.** A read counts only if it exits 0 and prints exactly the expected string. A failed read, an empty
   read or any other value is "not yet", never a pass.
3. **The expected value is what the write set** (the PUT body, the file, the sha pushed or merged), never a separate
   notion. So a stale read can match only if the old state already equalled the write, and then it is true anyway. Each
   row below checks that the old value differs from the expected one or the write changed nothing.
4. **Fail closed after the bound.** After 10 reads the step fails as it does today: the cutover prints `STOPPED` and the
   undo line (exit 2), and protect-main counts one NOT OK. The message gives the last value read and says "after 10 reads".
5. **Listings become one string.** When the answer is a set (rules on main, ruleset ids), the read prints it normalised
   (sorted, joined by one fixed separator, the same in both twins), and the whole string must equal the whole expected
   string. A subset seen while rulesets propagate, a superset, or an empty or refused read never matches. **Retry
   cannot prove that something is gone**: never use it where the expected value is "none" after a write that removes
   something. Read a value that the removal sets instead.
6. **A 2xx write is its own read.** The response body of a 2xx write (review `commit_id`, merge `sha`, POST `id`/`number`)
   comes from the primary and needs no confirming read. Check the body's field exactly. `POST pulls` after a fresh
   `git push` may get 422 because the branch isn't visible yet. A 422 means nothing was created, so that POST alone may be
   retried, on 422 only, with the same bound. A 2xx is never retried: check that the response's `head.sha` equals the
   pushed commit. Any other failure (5xx, timeout) is ambiguous, because a PR may exist. Fail closed and tell Brian to
   check the open PRs for that branch before running it again.

## Every write-then-read consumer
`C` = scripts/cutover-data-off-main, `P` = scripts/protect-main, `M` = scripts/merge-reviewed. Each line number is sh / ps1.

| # | Write | Confirming read | Expected | Today | Retry? |
|---|---|---|---|---|---|
| 1 | C `wf_set` PUT disable/enable :321 / :451 (steps 2, 6; rollback 2, end) | `wf_state` :323-326 / :454-458 | `disabled_manually` / `active` | 10x3 s | Done (hit 1). Move it onto the shared helper. |
| 2 | P R2 PUT false :116 / :166 (cutover step 4) | :164 / :225 | `false` | **once** | **Yes**: hit 2. The PUT runs only after a read of `true`, so a stale read is `true` and is never accepted. |
| 3 | C `r2_on` PUT true :380 / :551 | :381 / :553 | `true` | **once** | **Yes**: same race. It is called only while R2 is off. |
| 4 | P ruleset POST :102 / :151, PUT :107 / :156 | `ids_of` :140 / IdsOf :198, then GET :143 / :202 | ids = the one id (from the POST response `.id`, or the id PUT); ruleset = the whitelisted file | once | **Yes**. A lagged list after a POST shows 0 ids, and a lagged GET shows the old body. Both are false NOT OKs today. An old body equal to the file means the PUT changed nothing (rule 3). |
| 5 | P the same ruleset writes | rules/branches/main :150, :158 / :210, :219 | `deletion,non_fast_forward,pull_request`, and exactly one line `10<TAB>false` | once | **Yes**, under rule 5. This is the listing case: main's rules come from every active ruleset, so mid-propagation views (1 approval, a missing rule) must not match. |
| 6 | C `put_r1p` PUT :373 / :541 | GET :374-375 / :543-546 | the whitelisted R1' file | once | **Yes** (lower risk). Same shape as row 4. |
| 7 | C step 3 `git push` seed :741 / :953 | `fetch_rd` :743 / FetchRd :955 | the pushed `$seed` (the stale value is "" or no branch) | once | **Yes** (cheap). Git acks after the ref update (judgment, medium confidence), but a false stop here leaves records-data pushed. |
| 8 | C step 5 merge (inside M) | `fetch_main` :771 / :986 | `$ms`, the sha in the merge output (stale value: `$base`) | once | **Yes**: the most costly false stop, because it happens after the merge. |
| 9 | C rollback merge (inside M) | `fetch_main` :652 / :855 | `$ms` | once | **Yes**: same as row 8. |
| 10 | C step 5 merge | P `--check` contents reads :234, :259 / :295, :331 (`?ref=main`) | main's new workflow shape | once | **Yes, by pinning**: add `--main <sha>` to P. P reads `git/ref/heads/main` through the helper until it equals `<sha>`, then reads the contents at `?ref=<sha>`. A sha never changes, so the shape is read once. A 404 there means "not yet". |
| 11 | C any merge | `refresh_undo` :150 / UndoLine :159 | unknown (the merge output wasn't understood) | once | **No retry possible** (there is no exact value). If the read still shows `merge_from`, print both undo lines. Today the early path fails closed, because `restore_ok` refuses a main without data/. |
| 12 | C rollback `git push` branch :639 / :842 | POST pulls :641 / :844 (a write that needs the push to be visible) | 2xx, then `head.sha` = `$c` | once | **Retry on 422 only** (rule 6). Today it reads only `.number`: add the `head.sha` check. |
| 13 | M review POST :50 / :51 | its own response `.commit_id` | `$sha` | n/a | **No** (rule 6). The merge PUT :54 / :53 doesn't read the review: it is a bypass pinned to `sha`. The PUT is never retried. |
| 14 | M merge PUT :54 / :53 | rule-suites list :62-68 / :61-66 | an entry with `after_sha` = the merge; its result must be `bypass` | 5x10 s | Conforms: it retries only while the entry is missing, and a non-bypass result exits 2 at once. Keep its own bound: GitHub writes rule suites asynchronously. |
| 15 | C dispatch POST :334 / :465 | runs list :337-341 / :468-472 | the lowest run id above `before` | 24x5 s | Conforms. This waits for a new object to exist, not for lag. A missing run only delays. Keep as is. |
| 16 | C step 7 deploy | build-info :797-801 / ~:1012-1017 | `data_sha` = `$seed` | 20x30 s | Conforms (exact match, then fail closed). |
| 17 | C step 2 disable | `runs_busy` :729 / :939 | 0 runs not completed | once | **Residual, and retry can't fix it** (rule 5: it confirms an absence). A run queued just before the disable may be missing from a lagged list. The 05:00-10:30 refusal in step 1 covers the scheduled run. Suggestion: read again 30 s after the disable is confirmed, and both reads must be 0. |
| 18 | C step 3 push (minutes earlier) | step 5 `fetch_rd` :761 / :975 | still `$seed` | once | **No** (S1-5 checks for someone else's push, and a retry would accept on the first match). It runs minutes after the write, and `check_attested` checks again later. |

Reads that come before any write (P main :94, R2 :112; C step 1; M :32) and `wait_run` (polling a run, not lag) are out of
scope. scripts/u3-toggle.{sh,ps1} also writes rulesets. Check it against this table when it is next touched.

## One helper per twin
Use the same text in C, P and M, with a test that the definitions are byte-identical (as the whitelist `wl`/`Wl` is
today). Use fixed constants, not environment variables.
- sh: `read_until <what> <expected> <cmd...>` runs `<cmd>` up to 10 times. It returns 0 on the first read where `<cmd>`
  exits 0 and its stdout equals `<expected>` exactly. It runs `sleep 3` between reads, never after the last one. On
  failure it echoes `<what> reads '<last>', not '<expected>', after 10 reads.` and returns 1.
- ps1: `ReadUntil([string]$what, [string]$want, [scriptblock]$read)`. The scriptblock returns a `[string]` or `$null`
  (unread), so `$LASTEXITCODE` is never trusted across the call. The match is `-ceq`, multi-line output is joined with
  `"`n"` (never `-join ''`), and the wait is `Start-Sleep -Seconds 3`.
- In P, retries run only for reads of what this run wrote (not `--check`), plus the `--main <sha>` ref read. A plain
  `--check` reads once, so real drift isn't slowed by 10 x 27 s.

## How tests prove it
- **A stub lag for each endpoint.** Generalise the stub gh's `wf_lag` into `lag: {<path>: N}`, set on each write to that
  path: GETs return the pre-write body N times. Add a stub `git` wrapper on PATH that serves the old ref to `ls-remote`
  and `fetch` N times, for rows 7-9.
- **A sleep stub that logs.** `sleep` and `Start-Sleep` (pwsh_twin.py) append each call to `GH_CALLS`.
- For each row marked Yes, in both twins: lag 9 passes. Lag 10 fails closed with "after 10 reads", and the step's
  STOPPED or NOT OK line. The write appears exactly once in `GH_CALLS`. The sleep count equals the lag (9 when the bound
  runs out), with no sleep after the last read. A read that keeps returning a third value fails closed and never passes.
  A failed read (exit 1) then the right value passes.
- Row 12: a 422 then a 2xx gives exactly one PR. A 502 gives one POST and a stop. A wrong `head.sha` stops.
