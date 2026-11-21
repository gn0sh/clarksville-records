# V1'' probe: the job-log read invariant (I-log)

Problem key `v1pp-probe/job-log-unreadable`, family `v1pp-probe` (3+ hits, so the loop rule applies: invariant and
every consumer before the next fix). Software architect, 2026-11-21. Trigger: try 3
(`try3-results-20261121-1321.md`, main 70094f6): `JobLog` returned `$null` for all three jobs, so 23 lines were
INCONCLUSIVE. Earlier hit in the same area: `v1pp-probe/run-log-missing` (try 1, `gh run view --log`), fixed by
`main-protect-invariant.md` "V1'' try 1 inconclusive" item 3, which added `JobLog`/`job_log`.

## 1. What we know (evidence, confidence)

| # | Fact or inference | Evidence | Confidence |
|---|---|---|---|
| F1 | On Brian's PC, `gh api repos/.../actions/jobs/<id>/logs` never exited 0 in 6 reads 10 s apart, for 3 jobs | `JobLog` returns `$null` only when no read exits 0 (`scripts/v1pp-probe.ps1:590-601`); the results file says "could not read" for all 3 | high |
| F2 | The logs exist and hold every expected line | cloud read (GitHub MCP `get_job_logs`) minutes later, recorded in the try-3 results doc | high |
| F3 | `gh api` follows the log redirect correctly in general | 2026-11-21, cloud session, gh 2.89.0 on Linux: the same call for job 136956882571 exited 0, 17,082 bytes, 26 `V1PP-RESULT` lines. The body starts with a UTF-8 BOM (`EF BB BF`) | high |
| F4 | JSON endpoints on api.github.com work from the PC in the same run | runs, jobs, check-run annotations (all four environment lines PASS), refs, contents, rule suites | high |
| I1 | The cause is on the PC side: the gh build there, or the network path from the PC to the storage host the 302 points to, or Windows handling | F3 + F4. The log endpoint is the only call in the script that answers 302 to another host. Try 1's `gh run view --log` also downloads through a 302 to storage, so the two failures share that path | medium |
| I2 | Not "logs not ready yet" | the environment jobs were older than the runner job when read, and all 18 reads failed | medium-high |
| I3 | Not PS 5.1 output decoding | `$LASTEXITCODE` is gh's own exit code. Decoding by `[Console]::OutputEncoding` can garble text (the BOM turns into 3 characters on line 1) but can't make gh exit non-zero | high |
| U1 | Which of these it is: a DNS filter, antivirus or firewall blocking the storage host; an old gh with a redirect bug; or something else | **unknown**: the script threw gh's stderr away (`2>$null`, `2>/dev/null`), so the results file can't tell | - |

**The real defect** is U1. A failed read leaves no trace, so a third try could fail the same way and still teach us
nothing. And the script starts writing before it has shown that it can read its own evidence.

## 2. The invariant (I-log)

1. **A read.** A job-log read *succeeded* only when gh exits 0 **and** its stdout holds at least one GitHub log line,
   meaning a line that contains the timestamp prefix `LOGLINE` =
   `[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z ` (unanchored, because the BOM sits in front of
   line 1). Exit 0 with no such line (an empty body, or an HTML or XML error page) is a **failed** read.
2. **Failed is not absent.** "Line absent" (`no answer in the run's log`) may be said only after a successful read.
   If any of a run's job logs was not read, every verdict line that depends on that log is INCONCLUSIVE and says
   `not judged: the run's log was not read`. A log that wasn't read never produces PASS or NOT-TRIED. A FAIL still
   comes from the checks that don't use logs (merged flags, files on main or records-data, the main sha, tag main,
   ListPrs), and those run whatever happens to the logs.
3. **Read before write.** Before its first write (the leftover deletes, `v1pp-probe.ps1:462`, `.sh:398`), the script
   proves that this machine can read a job log: the newest finished `daily-update.yml` job, read through the same
   function. If that read fails, it stops with `REFUSED: ... Nothing was changed.` and writes the same text to the
   results file. The self-check never prints that log's text.
4. **Diagnosable from the results file alone.** Every failed read records one line: `gh exit <code>: <first
   non-blank stderr line, sanitized>`, plus the number of reads tried. The results file header records the first
   line of `gh --version` and the PowerShell version (bash: `bash --version` is not needed). Sanitizing, in order:
   strip control characters (CleanLog); reduce every URL to its scheme and host (`https://host/...`), so no path,
   query or signature remains; replace any run of 32 or more `[A-Za-z0-9%+/=_-]` characters with `<redacted>`; cut
   to 200 characters. **Never logged:** the stdout of a failed read (an Azure XML error can echo the request), any
   URL path or query (the 302 `Location` carries a signed, short-lived read token), or the text of the self-check
   log. `GH_DEBUG` is cleared for the script's process, so a debug line can't take the place of the error line.
5. **What each line tells us.** The diagnostic line sorts the cause: `no such host` / `lookup` means DNS on the PC;
   `connectex`, `i/o timeout`, `connection reset` or `refused` means a firewall, antivirus or network problem;
   `x509` / `certificate` means TLS interception; `HTTP 4xx` from a storage host means a gh redirect problem (upgrade
   gh); `HTTP 404/410` from api.github.com means the wrong job or an expired log; `exit 0, no log lines` means the
   body was empty or not a log.

## 3. Every consumer

| Consumer | Where | What it needs from the read |
|---|---|---|
| `JobLog` | `scripts/v1pp-probe.ps1:586-601` | is the producer: must follow I-log 1, 4 and keep the failure reason (`$script:jobLogWhy`) |
| `job_log` | `scripts/v1pp-probe.sh:506-520` | the same, in a subshell, so the reason goes back on stdout with return 1 |
| `CleanLog` / `clean_log` | ps1 :583, sh :499 | cleans the log text and the diagnostic line; leaves the BOM alone (harmless with an unanchored match) |
| `RunJobs` / `run_jobs` | ps1 :580, sh :502 | supplies job ids to the runner loop, `PagesRefused` and the new self-check (the self-check picks a row with status `completed` and conclusion `success` or `failure`) |
| Runner loop: `$script:lines`, `$errs` (V1PP-ERROR), `$script:ended` | ps1 :607-631, sh :526-544 | the text of every runner job, plus whether each one was read (new `logUnread` flag) |
| `Judge` / `JudgePr` / bot-open check / `judge` | ps1 :633-664, sh :546-575 | a "not read" state that is separate from "line absent" (I-log 2) |
| `PagesRefused` / `pages_refused` | ps1 :698-723, sh :612-631 | the text, or the failure reason for its INCONCLUSIVE line |
| `Finish` verdict | ps1 :409-457 | nothing new: unread lines count as INCONCLUSIVE (`others`), so the exit code is 1 |
| Results file | `Log`, ps1 :153 | the header (gh and PS versions), the self-check line, and the sanitized reasons |
| Producers of the lines | `scripts/v1pp-probe/v1pp-probe.yml`, `v1pp-env.yml` | unchanged; `test_the_runner_log_fixture_matches_the_runner` keeps the fixture in step with them |
| Stub | `tests/v1pp_stub_gh.py:278-295` (`log_lag` answers 404) | new failure modes: transport (stderr carries a signed URL), storage 403 (stdout carries an XML body), exit 0 with an empty body; the self-check run, jobs and log; `gh --version` |
| Tests | `tests/test_v1pp_probe.py`: the `INCONCLUSIVE` table :470-495 (`runner-log-never-ready`, `pages-log-never-ready`), `test_try_1_...` :511 (read counts for 600/605/606, `--log` ban), `test_pages_accepted_is_still_fail_when_the_log_lags` :663, `test_a_failed_pre_read_refuses_with_nothing_changed` :826, `test_the_workflow_scope_...` :832, `test_the_twins_agree` :847 (identical `--jq` filters, text pins, `--log` ban) | the existing prefixes still match (new text is only added after them), and the new cases in section 5 |
| `tests/pwsh_twin.py` `PS51_ONLY` | :96 | a new entry: the PC's network path to the storage host, and its gh build, can't be tested here; the self-check is the live check |
| Runbook | `docs/ops/morning-note.md` section 4 item 6a (:377-420) | what Brian sees when the self-check refuses: nothing changed, send the file |
| Earlier decision | `main-protect-invariant.md` "V1'' try 1 inconclusive" item 3 | a pointer to this note |
| Team relay | `/mnt/project-files/.../v1pp/try*-results-*.md` | the diagnostic line, which is safe to paste because it is sanitized |

## 4. Options weighed

| Option | For | Against | Call |
|---|---|---|---|
| A. Read-only log self-check before any write | turns "can't read logs" into a refusal that costs nothing and carries a diagnostic; tests the PC's exact read path | about 60 s more if it fails; one extra `--jq` filter | **take** |
| B. Diagnostic line on every failed read (I-log 4) | this is what was missing; without it, a failed try teaches us nothing | sanitizing carries real risk (signed URL), so a test must pin it | **take** |
| C. Longer or backed-off retries | cheap | I2: time was not the cause; costs minutes of Brian's time for nothing | reject (keep 6 x 10 s) |
| D. Fall back to `gh run view <run> --job <jid> --log` | a different gh code path | goes through the same 302-to-storage download (try 1 failed on it); a test bans `--log` (`run-log-missing`) | reject |
| E. `gh api -i` | shows the status line | only the final response; puts headers into the log text; a failure at the transport level has no response to show | reject (B's stderr line already carries `(HTTP nnn)`) |
| F. PowerShell-native download (`Invoke-WebRequest` with `gh auth token`) | a different TLS stack and proxy | the script would hold the token; the 5.1 redirect/Authorization behaviour and the TLS 1.2 default would need their own review; a different twin per OS | reject |
| G. Annotation channel: the runner and pages-api jobs also echo `::notice::` copies; the script reads `check-runs/<jid>/annotations` | avoids storage entirely; try 3 showed that annotations read fine on the PC | changes the pushed workflows (a new security review); untrusted text inside workflow commands needs `%`/CR/LF escaping; 10 notices per step means splitting the runner's single step; a larger diff | **plan B only**: if try 4's self-check shows the PC can't reach storage and that can't be fixed before the window closes |

**Chosen plan: A + B, plus the "not judged" wording (I-log 2).** It's a small diff and doesn't touch the pushed
workflows. If logs are readable, try 4 judges normally. If they aren't, try 4 changes nothing and names the cause.

## 5. Fix plan (backend-engineer; both twins; one PR)

1. **Move the helpers up.** Define `CleanLog`, `RunJobs`, `JobLog` (ps1) and `clean_log`, `run_jobs`, `job_log` (sh)
   before the header `Log`/`log` (ps1 :461, sh :397). PowerShell and bash both need a function defined before it
   is called. Do this as a move with no edits, so the diff is easy to review. In the same place, clear `GH_DEBUG`
   (`Remove-Item Env:GH_DEBUG -ErrorAction SilentlyContinue`; `unset GH_DEBUG`).
2. **`LOGLINE` and `ReadWhy`/`read_why`.** Define one shared regex string, `$logLine` / `log_line` (text in section 2,
   the same in both twins and pinned). `ReadWhy(rc, stderr, outCount)` returns
   `gh exit <rc>: <sanitized first non-blank stderr line>`, or `gh exit <rc>: no error text, <n> line(s) out`. The
   sanitizer regexes: .NET `(https?://[^/\s"'?#]+)[^\s"']*` -> `$1/...`; ERE
   `(https?://[^/[:space:]"'?#]+)[^[:space:]"']*` -> `\1/...`; then `[A-Za-z0-9%+/=_-]{32,}` -> `<redacted>`; cut to
   200 characters.
3. **`JobLog`.**
   ps1: `$all = @(gh api "repos/$repo/actions/jobs/$jid/logs" 2>&1); $rc = $LASTEXITCODE`. Split the result:
   `-isnot [Management.Automation.ErrorRecord]` gives stdout, `-is` gives stderr (works in 5.1 and 7; stderr no
   longer reaches the log text). It is a success only when `$rc -eq 0 -and $t -cmatch $logLine`. Otherwise set
   `$script:jobLogWhy = ReadWhy ...`. Clear it on success. Keep 6 reads 10 s apart, `$want`, and the return values.
   sh: `t=$(gh api ... 2>"$errf") && rc=0 || rc=$?`, with `errf=$(mktemp)` removed on every return. On failure,
   print the reason and `return 1`.
4. **Callers.**
   - The runner loop sets `logUnread` and marks
     `could not read job <jid>'s log after 6 reads (last: <why>)`.
   - In `Judge`/`judge`, when the line is absent: `ended` first (NOT-TRIED, unchanged); else, if `logUnread`, mark
     INCONCLUSIVE `not judged: the run's log was not read (see the runner log line)`; else the current
     `no answer in the run's log`.
   - `PagesRefused` appends `after 6 reads (last: <why>)` to its existing text.
5. **Self-check** (`v1pp-probe/log-read-selfcheck`), placed after the header log line and before the leftover
   deletes:
   - `gh api "repos/$repo/actions/workflows/daily-update.yml/runs?status=completed&per_page=1" --jq '.workflow_runs[0].id // empty'`.
   - Then `RunJobs` on that run. Pick the first row with status `completed` and conclusion `success|failure`.
   - Then `JobLog <jid> $logLine`.
   - If there is no run or job: `REFUSED: could not find a finished daily-update job to test the log read. Nothing was changed.`
   - If the read fails: `REFUSED: could not read the log of finished job <jid> (daily-update run <rid>) after 6 reads (last: <why>); every answer is read from job logs, so the probe stops here (v1pp-probe/job-log-unreadable). Nothing was changed. Send this file to the team.`
   - On success: `Log read check: job <jid> of daily-update run <rid> read (<n> lines).` This is not a Mark.
   - Exit 1 inside the `try` block, so `finally` gives the scope back. `started` is still false, so no cleanup runs.
   - Also log `gh: <gh --version line 1>` and (ps1) `PowerShell <$PSVersionTable.PSVersion>` with the header.
6. **Stub** (`tests/v1pp_stub_gh.py`):
   - `--version`.
   - `actions/workflows/daily-update.yml/runs?...` gives run 700 (cfg `selfcheck_run: none` gives `[]`).
   - `actions/runs/700/jobs` gives `gate` 701, completed/success.
   - The log for 701 is timestamped text containing `SELFCHECK-BODY`.
   - cfg `log_fail: {jid: mode}`, with these modes:
     - `dns`: stderr `gh: Get "https://productionresultssa1.blob.core.windows.net/actions-results/x/y.txt?sv=2025-01-05&sig=SECRETSIG%2Babc": dial tcp: lookup productionresultssa1.blob.core.windows.net: no such host`, exit 1.
     - `s403`: stdout `<?xml ...><Error><Code>AuthenticationFailed</Code>SECRETBODY</Error>`, stderr `gh: HTTP 403 (https://productionresultssa1.blob.core.windows.net/...?...sig=SECRETSIG)`, exit 1.
     - `empty`: exit 0 with no body.
     - `bom`: the normal log text with `﻿` in front.
7. **Tests** (both twins, `twin` parameter):
   - (a) `log_fail {701: dns}`: refused before any write. `Nothing was changed`; `run.writes()` is empty; the scope
     is given back. The results file holds `gh exit 1:` and `productionresultssa1.blob.core.windows.net/...`. Neither
     the output nor the results file holds `sig=`, `SECRETSIG`, `?sv`, `SECRETBODY` or `SELFCHECK-BODY`.
   - (b) `selfcheck_run: none`: refused, nothing changed.
   - (c) The self-check log read comes before the first DELETE in `run.calls`.
   - (d) `log_fail {600: dns}` (6 reads, then fail): `INCONCLUSIVE runner log: could not read job 600's log after 6
     reads (last: gh exit 1: ...no such host)`; every W/N/D0/WB/NB/D0B/PUSH line says `not judged`; no secret
     strings.
   - (e) `log_fail {605: s403}` gives a pages-api INCONCLUSIVE with `HTTP 403`, with no `SECRETBODY` and no `sig=`.
   - (f) `log_fail {600: empty}` counts as unread, not `no answer`.
   - (g) `bom` on 600 still gives PASS.
   - (h) `test_the_twins_agree` pins: the `$logLine` text, `log-read-selfcheck`, `not judged: the run's log was not
     read`, the self-check `--jq` filter (the identical-filter check covers it), `GH_DEBUG`, `<redacted>`; the
     `--log` ban stays.
   - Existing prefixes keep passing. Update the `try_1` read counts only if the self-check's job id collides
     (it uses 701, so they shouldn't change).
8. **Docs** (same PR):
   - The ps1/sh header (step 0 gains "reads a finished job's log").
   - Runbook 6a: one sentence for the new refusal ("it reads one finished job's log first; if it can't, it stops and
     changes nothing: send the file").
   - The `main-protect-invariant.md` item 3 pointer.
   - The `PS51_ONLY` entry.
   - Do **not** touch the lock line (the unlock to 2026-11-24 is already on main).
9. **Preflight:** `pytest tests/test_v1pp_probe.py` with and without `PWSH`, plus the repo preflight
   (`docs/ops/preflight.md`), pasted into the PR. Review: `code-reviewer` and `security-engineer`, because the PR
   touches secret-adjacent logging and a script with admin writes.

## 6. May the team's cloud read stand in for try 3's verdict?

**Strongest case for yes.**
- The job logs are GitHub's own records, kept 90 days, and can be deleted but not edited.
- The cloud read covered exactly the job ids the script recorded.
- Every line matches the wording the try-2 rules accept, and the pages-api lines are NOT-REACHABLE under those rules.
- Every check that doesn't use logs PASSed: no PR merged, no canary file on main or records-data, main unchanged,
  no tag main, and no bot PR, so nothing went through.
- The INCONCLUSIVE lines came only from transport. Another try means pushing workflows again, a scope round-trip,
  and Brian's time, all inside a window that closes on 11-24.

**Strongest case for no.**
- The gate is script-judged by design: pinned regexes, tested against fixtures, so no reader's judgment enters it.
  A cloud read is that reader's judgment. The MCP tool's output is a different transformation of the log (it may
  trim or reformat), and no test covers it.
- One FAIL is visible *only* in the log: a bot APPROVE that went through. The script reads no reviews, so the
  checks without logs can't stand in for that line.
- Accepting a team read sets a precedent: an INCONCLUSIVE could then be settled by hand. The gate exists to stop
  exactly that, and it guards `MORNING_NOTE_SEND` (the first real send is hard stop 1).
- The fix is cheap and try 4 is cheap. A stand-in saves about 10 minutes of Brian's time and costs the gate's
  integrity.

**Decision: no.** The "no" side is stronger: the approval line is only in the log, and so is the precedent risk.
Confidence high. Try 3 stays INCONCLUSIVE.

Record the cloud read in the try-3 results doc as **corroboration**: it predicts that try 4 PASSes once logs are
readable, and it narrows the fix to transport. If try 4 PASSes, that PASS is the gate. A middle path, a read-only
"re-judge try 3's runs" mode inside the script, was considered and rejected: it needs the same log read on the same
PC and adds a new code path to a gate script, while a full try 4 also re-proves the current state of main.

## 7. What could make try 4 unsafe, and the guard for each

1. **The window.** The unlock expires after 2026-11-24 UTC (the script compares the UTC date). The fix PR needs
   review and security before Brian runs it, so aim to run on 11-22 or 11-23 and keep a day for one rerun. If the
   window is missed, a new unlock PR is needed, not an edit to the date.
2. **The daily run** (09:07 UTC; GitHub can start it hours late).
   - It never writes to main (it pushes only to records-data, and the probe already ignores records-data moving).
     An overlap is therefore not unsafe, but a main move from any other source makes `main` INCONCLUSIVE.
   - The self-check reads only *completed* runs, so a run in progress is skipped.
   - Runbook: start only after today's `daily-update` run shows completed on the Actions page (afternoon CST, as now).
3. **Leaking the signed URL.** The risk is real if sanitizing is wrong: the results file is pasted into project
   files and docs. Mitigations:
   - Test (a)/(d)/(e) pins that none of `sig=`, `?`, the body, or the self-check text reaches the output or the
     results file.
   - Security reviews the sanitizer.
   - Even if the URL leaked, the token is short-lived and reads one log of a public repo, so the impact is low but
     not zero.
4. **The self-check placement.** It must come before the leftover deletes. Those deletes *are* writes, on refs left
   by earlier tries, so a self-check placed after them would break "Nothing was changed". Test (c) pins the order.
5. **The scope round-trip.** The workflow scope is added before the self-check. If the self-check refuses, Brian
   sees two browser prompts for nothing. This is accepted: moving the scope step after the self-check is a larger
   reorder, and `finally` still gives the scope back.
6. **A slow failure.** A blocked host can make each read hang for the length of a TCP timeout, so the self-check
   could take about 3 minutes before it refuses. This is harmless: nothing has been written yet.
7. **If the self-check refuses in try 4.** Read the line (section 2 item 5).
   - Storage host blocked: one device check for Brian, to allow the host in his DNS filter or antivirus.
   - Storage 4xx: `winget upgrade GitHub.cli`.
   - Either way, rerun the same day.
   - If it still can't be fixed by about 11-23 UTC: plan B (option G) and a new unlock, both reviewed. Never a team
     read (section 6).

## Problem keys this note adds

- `v1pp-probe/job-log-unreadable`: the invariant and the plan above.
- `v1pp-probe/log-read-selfcheck`: I-log 3.
- `v1pp-probe/log-read-diag`: I-log 4.
- `v1pp-probe/unread-not-absent`: I-log 2.

All are in family `v1pp-probe`. The next hit in this family, after this plan has been carried out, goes to Brian
under the loop rule.
