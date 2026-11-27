# ADR 0015: A permanent morning clock: several GitHub schedule lines, an arm window, and a midnight cutoff

Status: **proposed** (software-architect, 2026-11-27, branch `claude/permanent-clock`). Design only, no code.
Supersedes ADR 0014 decisions 1 (the claude.ai cloud task), 3 (the schedule never sends), 4 (one cron) and 5 (the
`clock-missed` alarm). Keeps ADR 0014 decision 2 (`send_note`) and decision 6, and ADR 0004's sender, day claim and
send window. Tasks: `docs/tasks/permanent-clock.md`. Problem family: `clock/` (third hit: ADR 0014's two, and the
Nov 27 refusal), so the invariant and every consumer are stated below before any fix.

## Context
- ADR 0014's clock was a claude.ai scheduled cloud task. On **Nov 27** its AI safety check refused the dispatch
  ("Unsanctioned Communication"): no run, no note. The run list (`gh api .../daily-update.yml/runs`, 2026-11-27
  19:33 UTC) has no dispatched run on Nov 27. Temporary fix: Brian's PC runs the same `gh workflow run` at 03:07
  (`scripts/register-morning-clock.ps1`); it needs the PC on and Brian signed in. Brian wants a clock that depends
  on neither his PC nor an AI session.
- **Measured lateness (verified 2026-11-27 from the run lists, `created_at`):**
  - `daily-update.yml`, 13 scheduled runs Nov 13 to 25, created 15:42 to 21:10 UTC. These were all on the **09:07 UTC**
    cron: PR #94 moved it to 13:07 only on Nov 26 at 18:21 UTC. Lateness **6.6 to 12.1 h**, median 8.6 h (not 2.6 to
    8.1 h: that figure measured them against 13:07).
  - `national-update.yml` (same repository, never edited in this period): the 04:23 UTC line, 7 runs Nov 21 to 27,
    **8.3 to 10.5 h** late; the 16:23 UTC line, 6 runs, **5.3 to 10.6 h** late, arriving 21:43 to 02:57 UTC.
  - Together: 26 samples, **5.3 to 12.1 h**, at three different hours of the UTC day. The national 16:23 line
    arrives in the small hours UTC, so the delay is a lag after the cron time, not a fixed afternoon band (the
    09:07 data alone could not tell those apart). This holds for our repository in late November only.
  - **One drop:** no scheduled `daily-update` run exists for Nov 26. The 09:07 run was not yet created (it would have
    come at about 15:40 to 21:10 UTC) when PR #94 changed the cron at 18:21 UTC. Inference: changing a workflow's
    schedule discards its pending run. GitHub documents that schedules "can be delayed during periods of high
    loads" and that "some queued jobs may be dropped", with no bound.
  - Nov 27's 13:07 run was not yet created at 19:33 UTC (at least 6.4 h).
- Run time (successful runs Nov 16 to 26): 44 to 118 min, the recent ones 85 to 118 min. `deliver` schedules each email
  for `max(send_at 07:00, now + 5 min)` and refuses after `latest_send` 10:00 (exit 3, "missed").
- **The schedule's actor is not an identity.** Every scheduled run lists `actor` and `triggering_actor` `gn0sh`.
  GitHub's docs: for `schedule`, the actor is whoever last edited the cron (or changed the default branch). A
  schedule event is created only by GitHub's scheduler, only on the default branch, from "the latest commit on the
  default branch", with no inputs; `github.event.schedule` says which line fired.
- **The note's window loses items when two runs collect before the cutoff.** The plan for day D holds records first
  fetched in `[D-1 07:00, D 07:00)` (`sitegen/morning.py` `window()`). If a run sends D at 01:00 and a later run
  before 07:00 collects new records, those fall in D's window; D is already claimed by the first plan, the later run
  ends "claimed" (exit 0, silent), and the records are never mailed (ADR 0014 accepted this for a manual
  dispatch only). Any design with several possible send runs per night must fix this first.

## Decision (option A: no account, no secret)
1. **Several schedule lines** (all UTC, off the hour). Send lines `37 20`, `37 23`, `37 2`, `37 6`, plus the
   existing data backstop `7 13`. All five may send; time decides (item 3), not the line. Coverage: a run that
   **starts** by 05:00 site time ends by about 07:00. That is 06:00 to 10:00 UTC on every day of the year (CST and CDT
   both). Each line covers a 4 h band of lateness: 20:37 covers 9.4 to 13.4 h, 23:37 covers 6.4 to 10.4 h, 02:37 covers
   3.4 to 7.4 h, 06:37 covers 0 to 3.4 h. Together that is **0 to 13.4 h**. The 5.3 to 12.1 h measured is covered at
   least once, and twice for 6.4 to 7.4 h and 9.4 to 10.4 h. CST adds an hour at the top. A line that arrives before
   midnight site time is an ordinary collect-and-deploy run. The lines are tuned from the first 14 days' data (item 8).
2. **`run-name` names the line:** `Daily update (schedule <cron>)` for scheduled runs, so lateness per line can be
   read from the run list alone. The dispatch names are unchanged.
3. **New job `arm`** (no `needs`, so it starts when the run starts; `permissions: {}`, no checkout, no repository
   code, `date` only). It outputs `send=true` and `day=<YYYY-MM-DD>` when the site time (`TZ=America/Chicago`, a test
   keeps it equal to `config/site.yml` `site_timezone`) is in **`[ARM_FROM 00:00, ARM_UNTIL 08:00)`**, otherwise
   `send=false`. Its log names the site time and the line. 08:00 plus the slowest observed run (118 min) is just
   inside 10:00, and `deliver` still refuses after 10:00 on its own. Because the decision is taken when the run
   starts, a run that waited in the queue is judged by when it actually runs.
4. **The note job's `if` (two routes, one set of locks):**
   ```
   ( (github.event_name == 'schedule' && github.run_attempt == '1')
     || (github.event_name == 'workflow_dispatch' && inputs.send_note == true && inputs.collect == true
         && github.actor == 'gn0sh' && github.triggering_actor == 'gn0sh') )
   && needs.arm.outputs.send == 'true' && vars.MORNING_NOTE_SEND == 'true'
   && github.ref == 'refs/heads/main' && needs.gate.outputs.verified == 'true'
   ```
   `needs` gains `arm`. The Deliver step checks all of this again in bash before `--live` (the second lock):
   `GITHUB_EVENT_NAME`, `GITHUB_RUN_ATTEMPT` = `1` for the schedule route, `ARM` = `true`, and the existing
   dispatch checks. The arm window applies to the dispatch route too, so the PC clock or a by-hand recovery that
   fires before midnight or after 08:00 skips the note instead of failing "missed".
5. **The cutoff moves to midnight, from a dated switch day.** `morning_note.cutoff: "00:00"` with
   `cutoff_from: <T>`. Days before T keep 07:00. T's window is `[T-1 07:00, T 00:00)`. From T+1 on it is
   `[D-1 00:00, D 00:00)`: "everything first found yesterday". Each record still has one note day (no gap, no
   overlap), and past digest pages do not change. Because `cutoff (00:00) <= ARM_FROM (00:00)`, a run that may send
   D collects only into D+1. So every send run on D builds the same plan D, and any number of them is safe: the
   first sends, and the rest end "claimed" or finish the same plan's editions not yet created. ADR 0014's residual
   about an early dispatch claiming the day "with older data" goes away.
6. **The alarm** (job `note-missed`, replacing `clock-missed`): it runs on every scheduled **and** dispatched run on
   `main` with `MORNING_NOTE_SEND` exactly `true`, with `actions: read` and `issues: write` only, a fixed title and
   the `--app github-actions` lookup, as now. It checks every site day X in {yesterday, and today once it is past
   `latest_send` 10:00} that has no note yet. It reads the run list and its jobs, and asks whether a `note` job
   ended `success` with `completed_at` on X by 10:00. If none did, it opens or comments on **"Daily update: no
   morning note"** at most once per day X. It also opens or comments on that issue when **no scheduled run was
   created in the last 26 h** ("the schedule went silent": dropped lines, a disabled workflow, or 60 days with no
   activity). A run on X+1 catches a missed X, which closes `clock-alarm/very-late-backstop`.
7. **The PC clock stays, as an optional extra path that is on time** (`scripts/register-morning-clock.ps1`,
   unchanged). It is not required. It stays on through the 14-day measurement. After that Brian may remove it or
   keep it. **The claude.ai cloud task is retired** (paused or deleted). ADR 0014's "Invariant: the clock" (an
   unattended AI session holding `gn0sh`) and its residual leave with it.
8. **Measurement:** `scripts/clock-report.py` (standard library plus `gh api`, read-only). For each site day it
   prints each line's created time and lateness, whether it was armed, the route that sent, the `note` job's
   conclusion and completion time, on time (done by 06:55) or late, and how many runs collected. Results go to
   `docs/platform-facts.md`.

## Invariant I-note-day (stated before the fix; family `clock/`)
For each site date D:
1. **Who may send.** Emails for note D are created only by a `note` job whose run is on a send route (a first-attempt
   `schedule` run on `main`, or a `gn0sh`-dispatched and -triggered run with `send_note` and `collect`). The run must
   also be armed: its `arm` job saw site date D and a site time in `[00:00, 08:00)`. `MORNING_NOTE_SEND` must be
   exactly `true` and the gate must have verified main. `deliver` must see site date D and `now <= latest_send`.
2. **At most once.** At most one plan's editions for D are ever created (day claim, `sender/deliver.py` `_claim`).
3. **Nothing lost or doubled.** Plan D is built only from records first fetched in window(D). Windows tile time
   with no gap and no overlap. `cutoff(D) <= ARM_FROM`, so no run that can send D adds to window(D). This rests on
   `first_fetched_at` never changing and on runs being serial (one concurrency group).

Consumers (each relies on it, and the tasks change or test each):
| Consumer | Relies on | Change |
|---|---|---|
| `.github/workflows/daily-update.yml` `on.schedule`, `run-name`, `arm`, `note` `if` and Deliver re-check, `note-missed`, header comments, concurrency comment | 1, 3 | change (T2) |
| `sender/deliver.py` wrong-date, `latest_send` "missed", `_claim`, `plan_digest` | 1, 2 | none; tests run |
| `sender/plan.py` `today()` (plan date is the site date at plan time) | 1, 3 | none |
| `sitegen/morning.py` `window()`, `note_day()`, cutoff validation; the digest pages | 3 | change (T1) |
| `config/site.yml` `morning_note.cutoff`, `cutoff_from`, `site_timezone`, `sender.send_at`, `sender.latest_send` | 1, 3 | cutoff (T1); tests pin `ARM_FROM == cutoff`, `SITE_TZ == site_timezone`, `ARM_UNTIL + 2 h <= latest_send` |
| `tests/test_workflow_lock.py`, `tests/test_morning.py`, the sender tests | all | change (T1, T2) |
| `scripts/register-morning-clock.ps1`, `docs/ops/morning-clock.md` (PC clock) | 1 | docs only (T3) |
| `docs/ops/morning-note.md` (How it runs; Rules for manual runs; The clock; Rollback: the key-rotation window now opens at 00:00; When the note job fails) | 1, 2 | change (T3) |
| `docs/architecture/morning-note.md` (window rule), `main-protect-invariant.md` (J4, J6, R-clock) | 1, 3 | change (T3) |
| `scripts/protect-main.ps1`, `tests/test_protect_main.py` (`WfShape`) | workflow shape | expected none; T2 confirms |
| Buttondown scheduled emails (now created up to 7 h before 07:00) | 2 | none |
| ADR 0014, `docs/platform-facts.md` (scheduler) | context | status and facts (T3) |

## Questions the brief asked, answered
- **Is a schedule run on protected `main` as trustworthy as ADR 0014's `gn0sh` dispatch lock?** Yes, and its reach is
  narrower. A `gn0sh` dispatch is any `gn0sh` credential choosing any moment. A schedule run has no principal
  choosing anything: GitHub's clock, main's latest reviewed commit (gate-verified history), and no inputs. The ways to
  influence it: merge to main (full control already), change the default branch (fails the `github.ref` check),
  re-run (fails `run_attempt == 1`), or disable the workflow (denial only, caught by the alarm's 26 h check). The
  `actor` field on a schedule run is not authentication, so the lock must never test it. Before ADR 0014 the schedule
  was the only send route (ADR 0004), and it was reviewed as such. The schedule route adds no new principal. It only
  adds *when*, inside the arm window.
- **Delays and drops.** Covered by four lines over 0 to 13.4 h, the late window (start 05:00 to 08:00: the note goes
  out 07:00 to 10:00), and the PC clock while it stays on. A line dropped on a day loses that line only.
- **A run before midnight site time:** `arm` says no. The run collects and deploys, and its records (with the new
  cutoff) fall in the next day's note, which is still unsent. No "missed" failure and no issue.
- **The one-waiting-slot queue:** a newer run replaces a pending one before it starts, so the replacement starts at
  the same moment and `arm` judges it the same way. Among send runs, a replacement never loses the day. Only a run
  that cannot send (an ordinary "Run workflow") can still take the slot. The manual-run rule stays, reworded:
  between 00:00 and 08:00 site time start only a `send_note` run, and never while one is queued.
- **Alarm semantics:** "no successful `note` job on day X by 10:00", and "no scheduled run in 26 h". It is checked on
  every run, including the next day's, so a very late or missing backstop no longer blinds it. Cancelled and
  replaced runs no longer matter.
- **DST:** `arm` and the cutoff use site wall-clock time (midnight always exists in Chicago; the change is at 02:00).
  The cron lines are UTC, and their coverage above is computed for the DST-safe band, so no edit at a DST change.
- **The "by 7 AM" promise on bad days:** if a send line arrives (or queues) to start by 05:00, the note goes at 07:00.
  If one starts 05:00 to 08:00, it goes late, between 07:00 and 10:00 (inside `latest_send`, the owner's "never late"
  bound). If none starts by 08:00 (GitHub later than 13.4 h on every line, or drops, and the PC clock off or missed),
  no note that day. It is never sent after 10:00 and never the next day. The records stay on the site, and the alarm
  opens. Honest promise: "by 7 AM most days, by 10 AM on a bad day, otherwise none, with an alarm".

## Risk of the pick (most serious)
**The measured lag may not hold.** 26 samples from two weeks of late November, from one repository. If GitHub
gets busier (lag over 13.4 h on every line) or drops more, A loses days. Without the PC clock nothing in A can make
GitHub on time. Mitigations: the late window, the 14-day measurement with a decision rule (Success signal), and
option B ready to go. Confidence that A meets 13 of 14 days on time without the PC: medium.

Other risks:
- **More collection.** Up to 5 scheduled collect runs a day plus the PC run, against 2 now. Each obeys robots.txt
  and the crawl delays, but the load on small government sites roughly triples. The report counts collecting runs
  a day. If that is too many, a follow-up lets a run that comes after the day's note already succeeded skip
  collection (it touches the update, push and deploy conditions, so it is out of scope here).
- **A schedule edit drops that day's pending runs** (Nov 26, inferred). So merge the T2 PR, and any later line
  change, after 10:00 site time, with the PC clock on.
- **What the note covers changes.** Records first found overnight move to the next day's note, so a record posted in
  the evening and found at 00:30 waits one more day. A reader gets "everything new yesterday". The change is
  reversible in config (`cutoff`). Assumption: acceptable to Brian (FYI, not an ask).
- **Retries are automatic but noisy.** A later line can finish a failed note. The `note-failed` issue may then be open
  for a day that did get its note; the runbook says to close it when the alarm stays quiet.

## Options considered (steelmanned)
- **B. External free cron calling `workflow_dispatch`** (Cloudflare Workers Cron Triggers, free plan). The strongest
  case is that it is on time to the minute, and the existing `gn0sh` route passes unchanged (a fine-grained PAT reports its owner
  as actor). It costs a new account (hard stop 4) and a new secret at a third party (hard stop 5). The token, with
  Actions read and write on this repository only, can dispatch, re-run, cancel and delete runs and logs (never
  push code or read secrets). It needs yearly renewal. The Worker must convert UTC to Chicago time itself. **What
  Brian would do (only if A fails its signal):** (1) create a free Cloudflare account, or say he has one; (2) create a
  fine-grained token at https://github.com/settings/personal-access-tokens/new: repository `gn0sh/clarksville-records`
  only, Actions: Read and write, expiry 1 year; (3) paste it once into the Worker's secret (the devops-engineer
  gives the exact clicks). The team writes the Worker code in the repository and a test.
- **Keep the PC clock as the primary.** No new parts, on time. But it fails Brian's requirement (PC power, sleep,
  sign-in, and Windows Update restarts at about 03:00). Kept as the optional extra path.
- **Keep the 07:00 cutoff and dedupe instead** (later runs that see a send run today do not send). Fewer changes to
  sitegen. But later runs still collect into today's window, so records are lost from the note silently, on most
  nights. Rejected: it breaks invariant part 3.
- **A third, tiny workflow that dispatches the daily run.** It keeps the daily run's routes as they are. But it needs `actions: write` in a
  workflow (the U-pages concern), a bot actor on the send route, and a third file under `.github/workflows/`
  (protect-main pins two). It costs more security for the same scheduler.
- **Another repository's cron, or an iPhone Shortcuts automation with a PAT.** The first uses the same scheduler and
  needs a secret. The second needs a new secret on a phone, with no measurement. Rejected.
- **Do nothing** (the PC clock only). Zero work, but a missed note on every PC-off night, and Brian has asked for this
  to be fixed.

## Success signal and how we measure it (first 14 site days after T2 merges)
`scripts/clock-report.py` daily, summarized at day 14 by `data-analyst` into `docs/platform-facts.md`:
- **S1 (the promise):** on at least 13 of 14 days a `note` job succeeded and its deliver ran by 06:55 site time
  (emails at 07:00).
- **S2 (independent of the PC):** on at least 12 of 14 days an armed *schedule* run was created by 05:00 site time,
  whether or not the PC also ran.
- **S3 (safety, every day):** no day with emails from two plans (one "sent" deliver line a day; the others "claimed"
  or the same plan), no send after 10:00, no `note-failed` caused by `arm` or the route, the alarm fired exactly on
  the days with no successful note job, and no record lost or doubled across the T switch day (QA check).
- **Decision at day 14:** S2 at least 12, so A is the permanent clock and the PC clock is optional. S2 at 9 to 11,
  so keep the PC, re-tune the lines from the per-line lateness, and measure 14 more days. S2 at 8 or under, so
  recommend B to Brian as one decision card.

## Verification before the switch
- Truth tables in tests: routes (schedule attempt 1 and 2, the dispatch cases kept from ADR 0014, branch, verified
  false), `arm` at 23:59, 00:00, 04:59, 07:59, 08:00 and on both DST change days, and the alarm (yesterday or
  today, once per day, a silent schedule).
- The cutoff transition: `sender plan --rehearse` for T-1, T and T+1 on a fixture whose records sit on each side of
  07:00 and 00:00. Every record must appear exactly once.
- Security review of the T2 PR (send path, CI), in session. Merge after 10:00 site time with the PC clock on.
