# PR 94 review: morning-note clock (ADR 0014)

## Round 1 at 60b92612 (vs b5934c6), 2026-11-24

### code-reviewer (opus/high): APPROVE, 0 must-fix
- should-fix `clock-alarm/early-schedule-blind` (daily-update.yml:1936): cron 09:07 UTC = clock's minute; an on-time schedule can replace a queued clock run, and clock-missed checks nothing before 05:00. Fix: move cron off the clock window (e.g. `7 13 * * *`) or record residual.
- should-fix `clock-alarm/collect-false-counts` (daily-update.yml:43): run-name must need send_note && collect.
- nit `clock-alarm/body-wording` (:1943): "has started" -> "was created".
- nit `note-route/boolean-input-unverified`: add first-morning check that the clock run is titled "(morning note)" and note job not skipped (morning-note.md s5 step 3).
- Checked: note `if` uses typed `inputs.*`; schedule can't send; other actors/re-runs/branches can't; bash re-check exact; tests evaluate the real workflow text; clock-missed perms; DST midnight math; protect-main WfShape unaffected. Tests: 723 passed, 163 skipped (pwsh twin; no pwsh).
- Deviations 1-4 accepted.

### security-engineer (opus/high): OK with follow-ups, no critical/high
- medium `clock/unattended-admin-session` (morning-clock.md): the task runs unattended with gn0sh's admin credential; doc must say "told to", not "can"; state setup limits. Fact: a claude.ai project scheduled task starts a new project thread with the project's repos and connectors (the connectors parameter isn't available for this org).
- low `clock/residual-wording` (main-protect-invariant.md R-clock, ADR 0014 Risk): user-to-server app tokens act as gn0sh and pass; "not before 07:00" holds in stamp mode only; an early gn0sh send_note dispatch claims the day with older data and the clock run exits "claimed" silently.
- low `clock-missed/false-quiet`: same as collect-false-counts.
- Checked: who can send, string/boolean, twice/out of window, secret exposure unchanged, clock-missed hardening, prompt, register-morning-clock.ps1.
