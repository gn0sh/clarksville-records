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

## Round 2 at d0688187

### security-engineer, fresh (opus/high): OK to merge with follow-ups, no critical/high
- medium `clock/unattended-session-reach` (morning-clock.md:16-17): a project thread auto-loads project instructions, project memory and every cloned repo's CLAUDE.md ("default to action"), and has Gmail (send as Brian), Drive, Docs, Calendar, GitHub MCP, Claude Docs, TradingKit. Planted memory or a merged CLAUDE.md edit could steer the unattended 03:07 thread. Fix: name the reach in doc + ADR Risk; prompt overrides project instructions/memory; prefer a clock with no repos/connectors, else PC fallback primary.
- low `clock-prompt/lost-response-redispatch` (:39-41): retry after an accepted-but-reset dispatch makes a second run; day claim prevents double send. Accept or check `gh run list` first.
- low `cron-move/stale-window-comments`: cutover scripts, national-update.yml:40, v1pp-job-log-invariant.md:216 still say 09:07 cron; not exposed.
- nit `note-route/collect-not-rechecked`: Deliver bash re-check omits collect.
- Checked and holds: who can send, string/boolean, double/out-of-window, secrets, clock-missed, cron move vs protect-main/national, ps1, all round-1 fixes.

### code-reviewer delta (opus/high): APPROVE
- Closed from round 1 (4): `clock-alarm/early-schedule-blind` (cron 13:07 UTC), `clock-alarm/collect-false-counts` (run-name needs collect), `clock-alarm/body-wording`, `note-route/boolean-input-unverified` (s5 step 3 first-run check).
- New nit `clock-alarm/very-late-backstop`: the 16-22 h late case in ADR Risk should say what the alarm misses then.
- New nit `tests/cron-check-tautological`: the cron test should parse the hour from the cron string, not restate it.
- `cron-move/stale-window-comments`, left as is on purpose: `scripts/cutover-data-off-main.{sh,ps1}` (the one-time cutover ran 2026-11-19; their 05:00-10:30 UTC refusal and its tests pin a finished step) and `national-update.yml:40` (its blob sha is pinned by protect-main, and its "09:07 UTC" is still the clock's run in CST). Only `docs/architecture/v1pp-job-log-invariant.md:216` is reworded.
