# The morning clock (ADR 0015)

The morning note is sent by GitHub's own schedule. No account, secret or AI session is involved. This page covers
the optional PC clock and how to read the report that shows whether the schedule worked. The runbook is
`docs/ops/morning-note.md` ("How it runs", "The clock").

## How the note gets sent
- `.github/workflows/daily-update.yml` has five schedule lines (UTC): `37 20`, `37 23`, `37 2`, `37 6` and the data
  `7 13`. GitHub creates scheduled runs hours late (5.3 to 12.1 h measured, `docs/platform-facts.md`
  "GitHub Actions scheduler"), so four lines cover the night.
- Each run starts with the `arm` job. It says `send=true` only when the run starts inside the arm window: from the cut in force for the day (00:00 from the
  switch day `morning_note.cutoff_from`, currently 2026-11-30; 07:00 before it) to 08:00 site time.
  A run that starts at another time only collects and deploys.
- The first armed run sends today's note (emails scheduled for 07:00, never earlier). A later run on the same plan ends "sent; emails created 0"
  and sends nothing more. Before the switch day, only a run that starts 07:00 to 08:00 sends, so the PC clock's 03:07
  run skips the note.
- The note covers everything first found yesterday (midnight to midnight site time: `docs/architecture/morning-note.md`
  "New today").
- If a day gets no note, the next run opens or comments on the issue **"Daily update: no morning note"**.

## The PC clock (optional)
`scripts/register-morning-clock.ps1` adds one Windows Task Scheduler task, "Daylight morning clock", that starts a run
at 03:07 every day with Brian's `gh` sign-in. It is an extra, on-time path: it is not required, and the schedule works
without it. It stores no token and refuses unless the PC's time zone is Central. It runs only while Brian is signed in
to Windows (a locked screen is fine) and wakes the PC from sleep. It does not catch up a missed morning.

It runs this command, which makes a run named "Daily update (morning note)" (the note job's dispatch route needs
`gn0sh` as both actors):

```text
gh workflow run daily-update.yml --repo gn0sh/clarksville-records --ref main -f collect=true -f send_note=true
```

Brian, in PowerShell, in the repository folder:
- **Add:** `powershell -NoProfile -File scripts\register-morning-clock.ps1` prints `REGISTERED Daylight morning clock,
  next run <date> 03:07`.
- **Check:** `powershell -NoProfile -File scripts\register-morning-clock.ps1 -Check` prints the task's state, next
  run, last run and last result (0 is success).
- **Remove:** `powershell -NoProfile -File scripts\register-morning-clock.ps1 -Remove` prints `REMOVED`.

The PC clock stays on through the first 14 days of measurement. After that Brian may remove it or keep it.

## Read the report
`scripts/clock-report.py` reads the run list through your own `gh` sign-in (read-only; it handles no token). Run it
from the repository folder:

```text
python scripts/clock-report.py              # the last 3 site days
python scripts/clock-report.py --days 14    # the last 14
python scripts/clock-report.py --summary 14 # S1, S2 and S3 counts over the last 14 site days
```

For each site day (America/Chicago) it prints, for each run that started that day:
- the schedule line (from the run's name, "Daily update (schedule 37 2 * * *)"), when GitHub created the run and how
  late that was;
- armed yes or no;
- each `note` job: its route (schedule or dispatch), result, completion time and the delivery status ("sent",
  "sent; emails created 0", "claimed" and so on);
- on time (delivered by 06:55 site time), late, or none;
- how many runs collected.

The summary counts: **S1** days with a note delivered by 06:55; **S2** days with an armed scheduled run created by
05:00 site time; **S3** days with a safety problem the report can see (two plans with "sent; emails created N>0", a "claimed" by a different plan, a note finishing after
10:00, or a note refused by the route or arm check). The alarm firing exactly on days with no note, and no record
lost or doubled at the cutoff switch (the switch day, `morning_note.cutoff_from`), are checked by hand.

Without GitHub: `--from-json FILE` reads saved API answers (see the script's header).

## Check it by hand
The last five scheduled runs, with when they were created:

```text
gh api "repos/gn0sh/clarksville-records/actions/workflows/daily-update.yml/runs?event=schedule&per_page=5" --jq '.workflow_runs[] | [.created_at, .display_title, .status, .conclusion // ""] | @tsv'
```

Times are UTC. Or open https://github.com/gn0sh/clarksville-records/actions/workflows/daily-update.yml.

## Changing the schedule
Edit the lines only after 10:00 site time, with the PC clock on: a schedule edit drops that day's pending scheduled
runs. The lines are tuned from the first 14 days of `clock-report.py` output. The send promise rests on the arm
window (the cut in force to 08:00) and `latest_send` (10:00); read `docs/adr/0015-permanent-morning-clock.md` first.

## History
ADR 0014's claude.ai scheduled cloud task (03:07, one `gh workflow run` command) is retired. On 2026-11-27 its AI
safety check refused the dispatch ("Unsanctioned Communication") and no run was made. Its prompt is removed from
this page; git history has it.
