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
| FX1 to FX6 Fixes from the PR #98 reviews (fourth `clock/` hit) | see "Fixes after the PR #98 reviews" | ADR 0015 as restated | FX1, FX2, FX3 in parallel |

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
Merge T1 and T2 after 10:00 site time, the PC clock on. The 14 days count from T (`cutoff_from`), not from the merge. Run `clock-report.py` each morning and log anything odd in
`docs/status.md`. At day 14, `data-analyst` writes the S1, S2 and S3 counts and the per-line lateness to
`docs/platform-facts.md`. The manager then applies ADR 0015's decision rule: S2 at least 12 makes A permanent and the
PC optional (tell Brian with an FYI line); S2 at 9 to 11 means re-tune the lines (a T2-sized PR) and measure 14 more
days; S2 at 8 or under means one decision card for Brian on option B.

## T8 Option B (conditional; hard stops 4 and 5)
Only after T7 says so, and only with Brian's yes. devops-engineer writes a Cloudflare Worker (in the repository,
with tests) that dispatches the existing `gn0sh` route at 03:07 Chicago time. Brian creates the account and the
fine-grained token as ADR 0015 "Options considered" B lists.

## Fixes after the PR #98 reviews (fourth `clock/` hit, 2026-11-27)
ADR 0015 "Invariant I-note-day" (restated: `cut(D) <= A(D)` on every route, and T later than the merge's site date)
and "Review of PR #98" give the decisions. All on branch `claude/permanent-clock`. A fifth hit in `clock/` goes to
the human per the loop limit if this re-plan's fix also fails twice.

| Task | Owner (model) | Files | Depends on | Parallel |
|---|---|---|---|---|
| FX1 Arm opens at `cut(D)`; attempt 1 and `ARM_DAY` locks | devops-engineer (opus/high: send path) | `.github/workflows/daily-update.yml` (`arm`, `note` `if`, Deliver re-check, comments), `tests/test_workflow_lock.py` | none | with FX2, FX3 |
| FX2 clock-report counts and robustness | devops-engineer (sonnet/medium) | `scripts/clock-report.py`, `tests/test_clock_report.py` | none (reads FX1's log format, unchanged) | with FX1, FX3 |
| FX3 Docs | technical-writer (sonnet/medium) | `docs/ops/morning-note.md` (l.59, l.404, the 13:07 wording, Nov 29/30), `docs/ops/morning-clock.md` (l.63, before-T behaviour of the PC clock), `docs/architecture/morning-note.md` (l.26), `docs/architecture/main-protect-invariant.md` (J4: attempt 1 on both routes) | ADR 0015 text | with FX1, FX2 |
| FX4 Outside watcher (follow-up, does not block PR #98) | devops-engineer (sonnet/medium) | `gn0sh/gnosh-uptime`: a freshness check for `https://daylight.gnoshcodes.com/build-info.json` | PR #98 merged | after merge |
| FX5 Merge-day check | manager | none (a command at merge) | FX1 to FX3 reviewed | at merge |
| FX7 Backend fixes | backend-engineer (sonnet/medium) | stamp guard after 07:00, `scripts/clock-report.py` AttributeError, config comment, workflow comments | none | with FX8 |
| FX8 Docs (review findings) | technical-writer (sonnet/medium) | arm-window wording (cut in force, not 00:00), ADR 0015 lock code block and decision 8, `docs/ops/morning-note.md` silent check, 14 days counted from T | none | with FX7 |
| FX6 Reviews and QA | code-reviewer and security-engineer (opus/high, **fresh** reviews: the fix touches CI and the send path), then qa-engineer | the fix commit SHA | FX1 to FX3 | after them |

### FX1 (devops-engineer)
- `arm` env: `SITE_TZ`, `CUTOFF: "00:00"`, `CUTOFF_FROM: "2026-11-30"`, `LEGACY_CUTOFF: "07:00"`, `ARM_UNTIL: "08:00"`;
  drop `ARM_FROM`. Bash: one `date` read gives `day` and `hm`; `cut = CUTOFF` if `day >= CUTOFF_FROM` (ISO dates,
  `LC_ALL=C` compare) else `LEGACY_CUTOFF`; `send=true` iff `cut <= hm < ARM_UNTIL`. Validate `CUTOFF_FROM` as
  `YYYY-MM-DD` and both cuts `< ARM_UNTIL`, else exit 1 as now. Keep the log format `arm window [<cut>, <until>):
  send=<x>` (clock-report's `ARM_LOG`). Add `cut` to the log line.
- `note` `if`: `github.run_attempt == '1'` on both routes (move it outside the route disjunction).
- Deliver: env `ARM_DAY: ${{ needs.arm.outputs.day }}` and `SITE_TZ`; in the `MORNING_NOTE_SEND == true` branch,
  require `GITHUB_RUN_ATTEMPT = 1` on both routes, `ARM_DAY = $(TZ="$SITE_TZ" date +%F)` and
  `ARM_DAY = $(jq -r .date "$PLAN")`; any mismatch: `::error::`, exit 2, nothing sent.
- Rewrite the `arm` and `note` header comments (l.1682-1688, l.1737-1742) and the file header (l.26-31) to say
  "opens at the cut in force for the day".
- Done when (tests in `tests/test_workflow_lock.py`):
  - `test_arm_from_is_the_notes_cutoff` (l.1708) is replaced by a pin test: `CUTOFF == morning_note.cutoff`,
    `CUTOFF_FROM == morning_note.cutoff_from`, `LEGACY_CUTOFF == sitegen.morning.LEGACY_CUTOFF`, both cuts
    `< ARM_UNTIL`; no `pytest.skip`;
  - the arm truth table through its bash with a fixed `date` adds T-1 03:07 false, T-1 06:59 false, T-1 07:00 true,
    T-1 07:59 true, T-1 08:00 false, T 00:00 true, T+1 00:00 true;
  - a property test: for days T-3 to T+3 and both DST change days, every minute at which the arm bash says
    `send=true` for day D has `sitegen.morning.note_day(t, cutoff, tz, cutoff_from) > D` (the invariant, part 3);
  - route table: dispatch attempt 2 skipped in `if` and refused in bash; `ARM_DAY` = yesterday refused; `ARM_DAY` !=
    plan date refused; each with nothing sent;
  - the T1 rehearsal (`sender plan --rehearse` for T-1, T, T+1) still lists each record once;
  - `tests/test_protect_main.py` and the pwsh twin pass unchanged; the full suite passes; output in the PR.

### FX2 (devops-engineer)
- A delivery counts as a send only when its line is `sent` with `emails created N` and N > 0. S3 "two plans" counts
  those. A deliver line "claimed (the day belongs to an earlier, different plan)" is an S3 problem "possible lost
  records" (it should never happen from T on).
- S1 counts a day only when a send (as above) ended by 06:55. Days whose only outcome is `no-send` leave both
  numerator and denominator (reported on their own line). `disabled`, `no-canary` and `wrong-date` never count as on
  time.
- Derived "armed" (no readable log) uses `cut(D)` (constants `CUTOFF`, `CUTOFF_FROM`, `LEGACY_CUTOFF`, pinned to the
  arm env by a test), not a fixed 00:00.
- `main` catches `ValueError`, `KeyError` and `TypeError` from the run and job JSON: one line naming the run id,
  exit 2.
- Done when fixture tests cover: one run sent and a second run on the same plan "sent; emails created 0" (no S3
  problem); "claimed" by a different plan (S3 problem); a `disabled` and a `no-canary` day (not S1); a `no-send`
  day (out of S1's count); a day before T derived as armed only 07:00 to 08:00; a run JSON with a bad date (exit 2,
  one line); the suite passes.

### FX3 (technical-writer)
- Correct the 26 h claim (`docs/ops/morning-note.md` l.59 and anywhere `grep -rn "26 h"` finds it): it catches a
  silent schedule only while dispatched runs still happen; a disabled workflow needs FX4.
- `docs/ops/morning-note.md` l.404: 09:07 UTC becomes the current lines. The 13:07 line is a send line like the
  others (it arms when it starts before 08:00 site time), not "backstop only".
- Write T in one place: docs say "the switch day (`morning_note.cutoff_from`, currently 2026-11-30)" instead of
  fixed Nov 29/30 (`docs/architecture/morning-note.md` l.26, `docs/ops/morning-clock.md` l.63).
- Runbook: before T, the note goes only from a run that starts 07:00 to 08:00 site time (the PC clock's 03:07 run
  skips it); the merge rule from FX5.
- Done when `grep -rn "09:07\|2026-11-29\|Nov 29\|disabled workflow" docs/` shows only history or the corrected
  text (output in the PR).

### FX4 (devops-engineer, follow-up in `gn0sh/gnosh-uptime`)
An outside watcher for a disabled or silent workflow: gnosh-uptime alarms when the live
`https://daylight.gnoshcodes.com/build-info.json` was built more than 26 h ago (read its build time; add a
freshness option to `monitor.config.json` if the monitor has none). Free, read-only, no secret. Done when a test in
gnosh-uptime shows a stale build-info opens the usual outage issue and a fresh one does not. Does not block PR #98.

### FX5 (manager, at merge)
Run `TZ=America/Chicago date '+%F %H:%M'` right before merging. Merge only when the date is before
`morning_note.cutoff_from` and the time is after 10:00 (a schedule edit drops that day's pending runs). The plan:
Sun 2026-11-29 after 10:00 CT, which keeps T = 2026-11-30 = merge day + 1. With FX1's guard, a merge on any earlier
day is also safe (those days send only from a run starting 07:00 to 08:00, else the alarm). On or after T 00:00,
move T to the merge day + 1 in `config/site.yml` and the `arm` env together (the pin test fails if only one moves),
and re-run the suite, before merging.

### FX6 (reviews and QA)
Fresh `code-reviewer` and `security-engineer` reviews at the fix SHA (CI and send path, so not deltas), with the
open keys `clock/cutoff-le-arm-from`, `clock/cutoff-switch-day`, `clock/arm-day-unused`,
`security/arm-stale-on-rerun`, `clock/report-s3-same-plan-sent`, `clock-alarm/silent-schedule-unwatched`,
`clock/alarm-green-not-sent`, `security/clock-report-robustness`. Ask both to attack the invariant as restated
(parts 3 and 4) and the consumer table. Then T6 (QA) as written, plus the T-1 arm cases.

## Follow-up for V1 (protect-main)
- `protect-main` should check that `BUTTONDOWN_API_KEY` and `MORNING_NOTE_CANARY_IDS` are not repository-level secrets (they belong to the protected environment only). Owner: devops-engineer.
