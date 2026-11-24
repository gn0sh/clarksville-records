# ADR 0014: A reliable 03:07 clock dispatches the morning-note run; GitHub's cron stays as a data backstop

Status: **accepted pending Brian's yes** (software-architect draft 2026-11-24; built on branch `claude/note-clock-build`).
Number 0012 is taken by the city-only site ADR on its unmerged branch (`d47c4b01`), so this is 0014.
Builds on ADR 0004 (sender), 0009/0011 (gate, data off `main`); runbook `docs/ops/morning-note.md`.

## Context
- `daily-update.yml` runs on `cron: "7 9 * * *"` (03:07 CST). All 11 scheduled runs from Nov 13 to 23 were *created*
  6.6 to 12.1 h late, median 8.6 h, none within 6 h (health check 2026-11-24, "Scheduler"; measured on `created_at`,
  so this is GitHub's queue, not our concurrency group). GitHub documents no upper bound on schedule delay.
- The `note` job runs only when `github.event_name == 'schedule'` (wf.yml:1661). `deliver` refuses after
  `latest_send` 10:00 ("missed", exit 3, which also opens the "morning note failed" issue) and schedules each email
  for `max(send_at 07:00, now + 5 min)` (sender/deliver.py:760). A run takes ~90 min (tests ~60).
- So with `MORNING_NOTE_SEND=true` (set 2026-11-23) the note is skipped on almost every day, and a failure issue is
  commented daily. Brian's promise is "one short email by 7 AM".
- Verified: the team's session acts on GitHub as `gn0sh` with admin rights (`gh api user`, 2026-11-24;
  platform-facts "GitHub repository settings"). So `github.actor == 'gn0sh'` means "Brian **or** a team session",
  never "Brian only". That is already true of `allow_shrink` and national collect.

## Decision (option A)
1. **The clock.** A claude.ai scheduled cloud task (team-created, 03:07 America/Chicago, so DST needs no cron edit)
   runs exactly one command: `gh workflow run daily-update.yml --ref main -f collect=true -f send_note=true`. Its
   prompt is committed at `docs/ops/morning-clock.md`. Fallback if it misses 2 of its first 5 mornings: a Windows
   Task Scheduler entry on Brian's PC running the same command (one copy-paste, `scripts/register-morning-clock.ps1`).
2. **New input** `send_note` (boolean, default **false**), so an ordinary "Run workflow" still never sends.
   `run-name` shows "Daily update (morning note)" when it is true.
3. **The note job's `if` becomes** (every existing check kept):
   `github.event_name == 'workflow_dispatch' && inputs.send_note == true && inputs.collect == true
   && github.actor == 'gn0sh' && github.triggering_actor == 'gn0sh' && vars.MORNING_NOTE_SEND == 'true'
   && github.ref == 'refs/heads/main' && needs.gate.outputs.verified == 'true'`.
   The **schedule no longer sends**: one send route, and a late cron run can't raise a daily "missed" issue.
   The Deliver step re-checks event, input and both actors in bash before passing `--live` (second lock, as
   `allow_shrink` does). The stale-run check, staged sender, gate, day claim and caps are unchanged.
4. **The cron stays** as a data backstop, moved to **13:07 UTC** (07:07 CST / 08:07 CDT; was 09:07, the clock's own
   minute: PR #94 review, `clock-alarm/early-schedule-blind`): when it arrives (early afternoon at the observed delays)
   it collects and deploys again. Off the clock's window, an on-time schedule can't take the queue's one waiting slot
   from a clock run still queued, and `clock-missed` runs after 05:00 site time unless GitHub is about 16 to 22 h late
   (then it lands before 05:00 the next day, checks nothing, and a missed clock on the day it was meant for goes
   unreported: Risk, Reliability).
   Its new items fall in the next day's window: it runs after the 07:00 cutoff even when on time, so their
   `first_fetched_at` is in `[D 07:00, D+1 07:00)`, note D+1; the windows are disjoint and `first_fetched_at` never
   changes, so nothing is lost or doubled.
5. **Alarm `clock-missed`** (new job, scheduled runs on `main` with `MORNING_NOTE_SEND` true only): `actions: read`
   plus `issues: write`, no checkout, no repo code. If no "Daily update (morning note)" run (`run-name`: `send_note`
   and `collect` both true) by `gn0sh`, not cancelled, was created since 00:00
   site time (and it is past 05:00 site time), it opens or comments on one fixed-title issue "Daily update: the
   morning clock did not fire" (`--app github-actions` lookup, as the other fixed-title issues).
6. `send_at`, `latest_send`, `config/site.yml` and `sender/` are unchanged. Moving the test suite off the nightly
   path (option C) is good separate work: it widens the same-day retry window, but is not needed for this.

## Risk of the pick (most serious)
**Security: who can trigger a send to the whole list.** The send route widens from "GitHub's cron" to "any token or
app session authorized as `gn0sh` with `actions: write`": Brian's `gh` on his PC, every team session, the cloud
task, any PAT Brian makes, and any GitHub App's user-to-server token acting for `gn0sh` (it reports `gn0sh` as the
actor and passes; only an App's installation token, `<app>[bot]`, fails). What it can do: make today's note go out
on a day it otherwise would not, from the data as of its run. A `gn0sh` dispatch with `send_note` between 00:00 and
the clock's run claims the day with that earlier run's data, and the clock's run then ends "claimed" (exit 0, no
issue), so the day's note silently misses the hours between them. What it cannot: change content or audience
(today's plan from main's gate-verified commit), send twice (day claim), send before 07:00 (in stamp mode,
`publish = max(send_at, ...)`; `ids` mode is not usable with Buttondown) or after 10:00, or run from a branch (ref
and `verified`). Collaborators, App installation tokens (`claude[bot]`), `github-actions` and other users fail the
actor checks, and a gn0sh re-run of someone else's dispatch fails `github.actor`.
Judgment: a small residual next to "a gn0sh credential can already merge code" (confidence medium).

**Security: an unattended session with gn0sh's reach** (PR #94 review, `clock/unattended-admin-session`, then
`clock/unattended-session-reach`). The clock is a claude.ai scheduled task: each morning it starts a fresh thread in
the gnoshcodes project, and that thread loads instructions and holds tools no prompt can remove (the next
paragraph lists them). The task is only *told* to run one command (`docs/ops/morning-clock.md`); its prompt says it
overrides every other instruction and forbids every connector, message and edit, but nothing enforces that. A
planted memory entry or a merged CLAUDE.md change ("default to action") could steer the 03:07 thread, with no person
watching. Judgment: the same reach every team session already has, now unattended once a day (confidence medium).
Kept as primary because Brian chose this design. **Preferred upgrade:** if V1 shows the cloud clock reliable but
this residual is judged too high, make the PC Task Scheduler entry (`scripts/register-morning-clock.ps1`: `gh` only,
no model in the loop) the primary clock and pause the cloud task.

**Invariant: the clock** (`clock/` family, 2nd hit, so stated before the fix). The clock may cause at most one
dispatch of `daily-update.yml` on `main` per night (two only through the one guarded retry, when no run was created
in the last 5 minutes) and nothing else: no other command, connector, message or edit.
- Instruction sources the session loads on its own: the gnoshcodes project's instructions; the project's memory;
  the `CLAUDE.md` of every repository cloned into the thread (the gnoshcodes playbook and each product repository's).
  Any of them can be changed by whoever can write the project or merge into those repositories.
- Reach: GitHub as `gn0sh`, admin, on every repository `gn0sh` reaches (`gh` and the GitHub MCP); the project's
  connectors: Gmail (including send as Brian), Google Drive, Google Docs, Google Calendar, GitHub MCP, Claude Docs,
  TradingKit.
- Consumers that rely on it: the note's one send route (decision 3: a dispatch by `gn0sh` sends today's note) and
  residual R-clock (`docs/architecture/main-protect-invariant.md`), which count the clock as one more `gn0sh`
  credential that dispatches once a night and does nothing else.
- What holds it: the prompt only (first line overrides the loaded instructions; one command; one guarded retry);
  V1's daily check of the run list; the alarm. Nothing technical.

**Reliability:** the clock is a new single point; its timing and whether the cloud proxy allows
`POST .../dispatches` are unverified (V1 below); the alarm makes a miss loud the same day, except on a day the
backstop schedule is about 16 to 22 h late (it then runs before 05:00 the next day and checks nothing:
`clock-alarm/very-late-backstop`).

## Options rejected (steelmanned, with each one's most serious risk)
- **Do nothing / accept later sends** (relax `latest_send` to ~17:00). Strongest case: zero new parts, the send route
  stays the cron, nothing to secure or verify. Risk: the promise breaks every day; arrival is random, 10:00 to 17:00
  CT (median ~13:00); keeping 10:00 instead skips the note daily and the failure issue becomes noise that hides
  real failures.
- **B. Cron much earlier** (~02:24 UTC so 12.1 h + 90 min ends before 10:00). Strongest case: no new trigger, no
  security change. Risk: the delay is undocumented and unbounded, and outcomes are bimodal: on a day GitHub is on
  time the run lands at ~20:30 CT the evening before, its plan is for that day and `deliver` says "missed". Making it
  work needs a "tomorrow" plan mode in the key-holding sender and a new window, and data is 10-15 h older at send.
- **C. Shorten the run / relax `latest_send`.** Strongest case: fixes the health check's top weakness too. Risk: even
  a zero-minute run starts after 09:43 CT at the *smallest* observed delay, so C alone never meets 7 AM.
- **D1. External cron service** (cron-job.org) with a PAT. Risk: a new account (hard stop 4) and a token with
  `actions: write` stored at a third party (hard stop 5): the widest reach of all options.
- **D2. Cron in another GitHub repo.** Same scheduler, same lateness, plus a PAT secret.
- **D3. Today's late run schedules tomorrow's 07:00 note.** Strongest case: no clock, 19 h of retry room. Risk: the
  note is always a day behind, and it rewrites the date, window and claim rules inside the code that holds the key.
- **A on Brian's PC as primary.** Deterministic, uses his existing `gh` login. Risk: home power, sleep, and Windows
  Update restarts, which default to the small hours (~03:00); and it costs Brian PC steps. Kept as the fallback.

## Consumers that must change
| File | Change | Size |
|---|---|---|
| `.github/workflows/daily-update.yml` | `send_note` input, `run-name`, note `if`, Deliver bash re-check, `clock-missed` job, header and note comments (lines 25-28, 1644-1657), cron comment ("data backstop") | M, ~80 lines |
| `tests/test_workflow_lock.py` | `NOTE_IF`; replace "a manual run never sends" (l.1047) with a route truth table like `COLLECT_ROUTES` (schedule never sends; dispatch without input; collect=false; mallory; gn0sh re-run of mallory's dispatch; branch; verified false); Deliver lock; `clock-missed` permissions, fixed title, `--app` | M, ~150 lines |
| `scripts/protect-main.ps1`, `tests/test_protect_main.py` | **No change expected**: daily-update.yml is shape-checked, not blob-pinned (`WfShape`, l.419-450: permissions and gate only); `.github/workflows/` stays exactly two files; national-update.yml's pin is untouched. Engineer confirms by running both test files and the pwsh twin | none |
| `docs/ops/morning-note.md` | "How it runs" (note condition 1, new alarm); 5 step 2; "Rules for manual runs" (do not start a run 02:45-05:00 CT; if "Daily update (morning note)" is queued, do not start one, it would replace it; `send_note=true` by hand only to recover before 08:30); "When the note job fails" (recovery = one gn0sh dispatch with `send_note=true`); new "The clock" (check, pause); "Rollback" (pause the clock) | S, ~40 lines |
| `docs/architecture/morning-note.md` | "Workflow changes" bullet "a manual run never sends"; window rule sentence on 09:07 UTC | S |
| `docs/architecture/main-protect-invariant.md` | send routes and a residual R-clock (above) | S |
| `docs/ops/morning-clock.md` (new), `scripts/register-morning-clock.ps1` (fallback only, with tests) | the task's prompt and the PC fallback | S |
| `docs/platform-facts.md` | scheduler lateness (verified), clock timing after V1 | S |

## Verification before the switch
- V1 (before the PR merges): the cloud task dispatches a plain run (`collect=true`, no `send_note`; the input does
  not exist yet) at 03:07 for 3 mornings. PASS: each run created within 15 min, `actor` and `triggering_actor` gn0sh.
  This is the same kind of run the team already starts by hand (26 of 37 so far).
- Security review of the workflow PR (touches the send path and CI). Merge by Brian's `merge-reviewed.ps1` as usual.
