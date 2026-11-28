# Permanent morning clock (ADR 0015, PR #98): reviews and QA

## Security review: PR #98 at cc59aa8 (security-engineer, opus/high, 2026-11-27)
Verdict: OK WITH FOLLOW-UPS. No critical/high.
- F1 clock/cutoff-switch-day (medium): cutoff_from must be merge day + 1; between merge and T, old 07:00 cutoff with several armed runs loses records. Test compares ARM_FROM to `cutoff` key, not the cut in force before T. Optional guard: hold schedule route until T.
- F2 security/arm-stale-on-rerun (low): re-run failed jobs reuses arm send=true; arm.day unused. Fix: ARM_DAY == plan date; dispatch route attempt==1.
- F3 clock/alarm-green-not-sent (low): deliver exits 0 on wrong-date/claimed(other plan); note-missed counts it as handled.
- F4/F5 informational (accepted residuals R-clock, queue replacement).
- F6 security/clock-report-robustness (low): catch ValueError/KeyError in main.
Checked: triggers, ref gate, env, permissions, protect-main WfShape, injection in note-missed, concurrency/claim, clock-report gh calls.

## Code review: PR #98 at cc59aa8 (code-reviewer, opus/high, 2026-11-27)
Verdict: REQUEST CHANGES.
1. must-fix clock/cutoff-le-arm-from: before cutoff_from T, window ends 07:00 but all lines arm from 00:00 -> records lost (merge before T-1 10:00) or doubled (merge after T 00:00). Test pins ARM_FROM==cutoff ignoring cutoff_from. Fix: arm gets CUTOFF_FROM env (test = config), send=false on schedule route before T. Docs morning-note.md (arch):26, morning-clock.md:63 hard-code Nov 29/30.
2. should clock/report-s3-same-plan-sent: second run on same plan ends "sent; emails created 0", report flags as double. Parse N>0; fixture; docs morning-clock.md:14, morning-note.md:32,610.
3. should clock-alarm/silent-schedule-unwatched: scheduled run counts itself; disabled workflow not caught once PC clock removed. Correct ADR line 125 / morning-note.md:59; follow-up outside watcher (gnosh-uptime build-info age).
4. should clock/arm-day-unused: ARM_DAY to Deliver; dispatch route attempt==1.
5-7 nits: morning-note.md:404 09:07 UTC; 13:07 "backstop" can send; S1 counts disabled/no-canary/wrong-date.

## Code review r2: PR #98 at 6d6fee0 (code-reviewer, opus/high, 2026-11-27/28)
Verdict: APPROVE. I-note-day parts 1-4 hold. 1169 passed, 1 skipped.
1. should clock/cutoff-le-arm-from (docs): "00:00 to 08:00" remnants at main-protect-invariant.md:410 (+ARM_DAY at :406), architecture/morning-note.md:31,:595, platform-facts.md:368, daily-update.yml:87,:90 (send_note input description).
2. should clock-alarm/silent-schedule-unwatched: daily-update.yml:2042 and ops/morning-note.md:61 claim silent check catches disabled/60-day stop; point to FX4.
3. should clock/past-never-moves: config/site.yml:127-132 comment "never change cutoff_from after it has passed"; pin literal after merge.
4. nit ADR 0015:68-70 code block attempt on schedule branch only. ADR l.116 "collects only after arm" wrong (update doesn't need arm).
5. nit daily-update.yml:65 "data backstop".
6. nit clock/measure-window: 14-day measurement counts from T, not merge.

## Security review r2: PR #98 at 6d6fee0 (security-engineer, opus/high)
OK WITH FOLLOW-UPS. No critical/high.
- L1 security/stamp-cleared-after-publish (low): same-plan run after 07:00 could create a new edition for a subscriber whose stamp a form post overwrote. Fixed in d81a5a8 ("published" status).
- L2 clock/cutoff-switch-day (low, process): FX5 merge-day check is manual; merge must be on a site date before cutoff_from and after 10:00.
- N1 security/clock-report-robustness: AttributeError uncaught. Fixed in d81a5a8.
- V1 (follow-up): protect-main should check BUTTONDOWN_API_KEY and MORNING_NOTE_CANARY_IDS are not repository-level secrets.
- V2: exit-0 outcomes keep the alarm quiet (accepted, ADR 0015 F3).

## Security delta re-review at db18816
OK WITH FOLLOW-UPS. L1 and N1 closed; "published" needs an email of this plan already on the provider, and every partial first run exits non-zero so note-failed opens. No new findings. 1063 passed.

## QA at db18816 (qa-engineer, opus/high)
PASS WITH MINOR ISSUES. Full suite 9276 passed, 548 skipped, 0 failed. Arm shim truth table incl. 2027 DST days, 6930-instant property check (0 violations), real-data switch-day rehearsal (0 doubled, 0 lost), clock-report fixture, published guard all PASS.
1. clock-alarm/partial-send-green (minor): a first run that created 1 of 3 editions then failed, re-run at 07:10 ends "published": 3 of 4 subscribers get nothing; note-failed opens but note-missed and clock-report stay quiet, and runbook morning-note.md:659 says to close note-failed once a later job is green. Follow-up FX9.
2. clock/pr-body-stale (minor): PR body updated by the manager.
3. clock/report-counts-unfinished-today (nit): follow-up FX9.
