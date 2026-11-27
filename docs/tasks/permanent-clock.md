# Tasks: permanent morning clock (ADR 0015)

Design: `docs/adr/0015-permanent-morning-clock.md` (decisions 1 to 8, invariant I-note-day and its consumer table:
every task below names the parts it changes). Problem family `clock/`: this is its third hit, so any new finding
in the family goes back to the architect before the next fix. Tests run in session (`python -m pytest -q`, and the
pwsh twin where a `.ps1` changes), and their output goes in each PR. Every PR goes to `code-reviewer`. T2 (send path
and CI) also goes to `security-engineer`, in session, at opus/high, as a fresh review. Merge as usual by Brian's
`merge-reviewed.ps1` or the manager's equivalent, **after 10:00 site time with the PC clock on** (ADR 0015 Risk: a
schedule edit drops that day's pending runs).

| Task | Owner | Depends on | Parallel |
|---|---|---|---|
| T0 Retire the claude.ai cloud task; keep the PC clock on | manager | none | now |
| T1 Midnight cutoff from a dated switch day | backend-engineer | none | with T2, T3, T4 |
| T2 Workflow: schedule lines, `arm`, note routes, `note-missed` | devops-engineer | none (merges with or after T1) | with T1, T3, T4 |
| T3 Docs and facts | technical-writer | ADR 0015 (final text after T1 and T2 review) | drafts with T1, T2 |
| T4 `scripts/clock-report.py` | devops-engineer | ADR 0015 decision 2 (the `run-name` format) | with T1, T2 |
| T5 Reviews | code-reviewer, security-engineer | T1, T2 at a commit SHA | after T1, T2 |
| T6 Verification | qa-engineer | T5 pass | after T5 |
| T7 Merge and the 14-day measurement | manager, data-analyst | T6 pass | after T6 |
| T8 Option B (only if T7's decision says so) | devops-engineer, then Brian | T7 | conditional |

## T0 Retire the cloud task (manager)
Pause or delete the claude.ai scheduled task described in `docs/ops/morning-clock.md`. It is the team's own task, so
this is not a hard stop. Confirm the PC clock fired this morning (the `gh api` line in `morning-clock.md` "Check it").
Record both in `docs/status.md`. Done when: the cloud task no longer runs, and the run list shows the PC's run.

## T1 Midnight cutoff (backend-engineer, sonnet/medium; `sitegen/morning.py`, `config/site.yml`, `tests/test_morning.py`)
ADR 0015 decision 5, invariant part 3.
- Add `morning_note.cutoff_from: "<T>"` (a date) beside `cutoff: "00:00"`. `window(D)` is `[D-1 07:00, D 07:00)` for
  D < T, `[T-1 07:00, T 00:00)` for D == T, and `[D-1 00:00, D 00:00)` for D > T. `note_day()` uses the same rule
  (one function decides the window, as now). The validation in `problems()` refuses a bad date or a missing
  `cutoff_from` while `cutoff` differs from the legacy 07:00.
- T is set by the PR to the day after its planned merge date, and the reviewer checks it at merge. If the merge slips,
  move T so it stays in the future.
- Update the comments at `config/site.yml` around line 115 and in `sitegen/morning.py` (module docstring, `window`).
- Done when: tests show every instant falls in exactly one window across T-1, T and T+1 (no gap, no overlap); both
  DST change days; digest pages for days before T are byte-identical to before; `sender plan --rehearse --date` for
  T-1, T and T+1 on a fixture with records at 06:59, 07:00, 23:59 and 00:00 lists each record exactly once; and the
  full suite passes.

## T2 Workflow (devops-engineer, opus/high: send path; `.github/workflows/daily-update.yml`, `tests/test_workflow_lock.py`)
ADR 0015 decisions 1 to 4 and 6, invariant parts 1 and 2.
- `on.schedule`: `37 20 * * *`, `37 23 * * *`, `37 2 * * *`, `37 6 * * *`, `7 13 * * *`. Rewrite the comment (coverage
  0 to 13.4 h, lines tuned from `clock-report.py`).
- `run-name`: `Daily update (schedule <github.event.schedule>)` for scheduled runs; dispatch names unchanged.
- New job `arm`: no `needs`, `permissions: {}`, `timeout-minutes: 2`, no checkout, `date` only. Env `SITE_TZ`,
  `ARM_FROM: "00:00"`, `ARM_UNTIL: "08:00"`. Outputs `send` (`true` or `false`) and `day`. Its log line names the site
  time and `github.event.schedule`.
- `note`: `needs: [gate, update, deploy, arm]`. Use exactly the `if` in ADR 0015 decision 4. The Deliver bash
  re-check adds `ARM`, and `GITHUB_RUN_ATTEMPT` = `1` on the schedule route. Rewrite the job's header comment and the
  file header (lines 22-30).
- Replace `clock-missed` with `note-missed` (decision 6): every run on `main` with `MORNING_NOTE_SEND` exactly true,
  `actions: read` and `issues: write`, no checkout, fixed title "Daily update: no morning note", `--app
  github-actions`. It checks yesterday and, after 10:00 site time, today. It comments once per day (skip if the open
  issue already names that day). It also checks "no scheduled run created in 26 h". It fails loudly when it cannot
  count.
- Tests (replacing the ADR 0014 ones: `NOTE_IF`, l.979; `test_the_cron_is_the_data_backstop_off_the_clock_window`,
  l.1255; the `clock_missed` tests, l.1518-1640):
  - a route truth table: schedule attempt 1 sends and attempt 2 does not; the ADR 0014 dispatch cases; branch;
    verified false; arm false;
  - an `arm` truth table run through its bash with a fixed `date` (23:59, 00:00, 04:59, 07:59, 08:00, both DST days);
  - `SITE_TZ == site_timezone`, `ARM_FROM == morning_note.cutoff` (once T1 is in), and `ARM_UNTIL + 2 h <=
    latest_send`;
  - `note-missed` with fixture run and job lists: quiet, yesterday missed, today after 10:00, once per day, silent
    schedule, a count it cannot read;
  - least privilege for `arm` and `note-missed`.
- Run `tests/test_protect_main.py` and the pwsh twin. The expectation is no change (`WfShape` checks permissions and
  the gate). Report if not.
- Done when: the tests pass, the preflight output is in the PR, and the PR body lists every invariant consumer row
  touched.

## T3 Docs and facts (technical-writer, sonnet/medium)
Using ADR 0015's consumer table:
- `docs/ops/morning-note.md`: in "How it runs", note condition 1 (two routes, arm), and `note-missed` replaces
  `clock-missed`. In "Rules for manual runs", between 00:00 and 08:00 start only a `send_note` run, and never while
  one is queued; the 02:45-05:00 rule goes. "The clock": GitHub's lines plus the optional PC clock. "Rollback":
  never rotate the key between 00:00 and 07:00; stopping today's email now applies from 00:00. "When the note job
  fails": recovery before 08:00, a later line may retry on its own, and close `note-failed` when that day's note
  went out.
- `docs/ops/morning-clock.md`: rewrite. The cloud task is retired (remove its prompt). The PC clock is optional.
  Add how to read `clock-report.py`.
- `docs/architecture/morning-note.md`: the window rule (midnight cutoff, the switch day).
- `docs/architecture/main-protect-invariant.md`: row J4 (two routes), row J6 (`note-missed`), and R-clock rewritten
  (the schedule route; remove the unattended-session residual).
- `docs/adr/0014-morning-note-clock.md`: status line "superseded in part by ADR 0015 (decisions 1, 3, 4, 5)".
- `docs/platform-facts.md` "GitHub Actions scheduler": the 26 lateness samples (both workflows), the Nov 26 drop
  (inferred cause), the schedule actor fact and the GitHub docs quote, and the Nov 27 cloud refusal.
- Done when: no doc still says "the schedule never sends", "03:07 cloud task" or "clock-missed", except as history
  (checked with `grep -rn` and the output pasted in the PR).

## T4 Measurement script (devops-engineer, sonnet/medium; `scripts/clock-report.py`, `tests/test_clock_report.py`)
ADR 0015 decision 8 and the success signal. Standard library plus `gh api`, read-only, no token handling of its own.
For each site day it prints: each scheduled run's line (from `display_title`), created time and lateness; armed
yes or no (the `arm` job's output in its log, or derived from created time); the route of each `note` job and its
conclusion and `completed_at`; on time (by 06:55) or late; and the number of collecting runs. A `--summary N` flag
gives the S1, S2 and S3 counts over the last N days. Done when: tests on fixture JSON cover a day sent on time from
a schedule run, from the PC, late, none, and two send runs (one "claimed").

## T5 Reviews
`code-reviewer` (opus/high: cross-module and send path) on T1 and T2. `security-engineer` (opus/high, in session) on
T2. Its brief includes ADR 0015 "Is a schedule run as trustworthy", and asks it to attack the `run_attempt` lock,
the default-branch change, and the `arm` output's integrity. Problem keys under `clock/`, `clock-alarm/` and
`note-window/`.

## T6 Verification (qa-engineer, sonnet/medium)
Check the invariant against the code at the reviewed SHA: the route truth table, the arm table, and the alarm table.
Run the T1 transition on real `records-data` (each record in exactly one day's plan across T-1 to T+1). Done when:
PASS, or bugs filed back to T1 or T2 with problem keys.

## T7 Merge and measure (manager; data-analyst at day 14, sonnet/medium)
Merge T1 and T2 after 10:00 site time, the PC clock on. Run `clock-report.py` each morning and log anything odd in
`docs/status.md`. At day 14, `data-analyst` writes the S1, S2 and S3 counts and the per-line lateness to
`docs/platform-facts.md`. The manager then applies ADR 0015's decision rule: S2 at least 12 makes A permanent and the
PC optional (tell Brian with an FYI line); S2 at 9 to 11 means re-tune the lines (a T2-sized PR) and measure 14 more
days; S2 at 8 or under means one decision card for Brian on option B.

## T8 Option B (conditional; hard stops 4 and 5)
Only after T7 says so, and only with Brian's yes. devops-engineer writes a Cloudflare Worker (in the repository,
with tests) that dispatches the existing `gn0sh` route at 03:07 Chicago time. Brian creates the account and the
fine-grained token as ADR 0015 "Options considered" B lists.
