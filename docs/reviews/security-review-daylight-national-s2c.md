# Security review S2c: national-isolation fixes, 85bd69a4..99105673

Reviewer: security-engineer (opus/high), 2026-11-20. Read-only, at commit 99105673 (branch claude/project-thread-ysvq9u).
Scope: devops D-ISO-1..9 (`.github/workflows/daily-update.yml`, `.github/workflows/national-update.yml`,
`docs/ops/u3-positive-control.md`) and backend B-ISO-1..7 (`sitegen/national_copy.py`, `sitegen/national_pages.py`,
`sitegen/build.py`, `sitegen/national_clarksville.py`, `qa/site_checks.py`, `collector/__main__.py`, schema). Checked
against architecture section 12, the amended 11.2 and ADR 0013 amendment C.

**Verdict: PASS WITH FINDINGS.** No critical, high or medium findings. One LOW reopens part of S2b finding 4; five nits.
**Release recommendation: OK WITH FOLLOW-UPS.** Nothing blocks the merge. Finding 1, S2b ruling 5 and 12.3 #12 should
land before `national.enabled: true` goes on with any collected Legistar entry.

**Tests.** tests/test_national_isolation.py, test_national_copy.py, test_national_workflow.py, test_workflow_lock.py,
test_national_pages.py: 796 passed, 3 failed, 2 errors. All 5 are environmental (need Clarksville `data/`, not fetched in
the read-only checkout): test_workflow_lock `test_tracked_data_files_fit_the_allowlist`, `test_the_seed_of_todays_data_meets_i_data`;
test_national_pages `test_real_*` (2).
Extra probe (scratch, not committed): `qa.site_checks` over bad-date, surrogates, fragment-anchors, null-everywhere,
huge-integers, fields-and-marks hostile builds and a forced tier-2 build: every result identical to the no-root baseline
(baseline's only failure is `links`, from the fixture build having no council pages).
Git probe (file://, git 2.43): `--depth=1` national-data fetch then `git fetch --unshallow origin main` leaves
`is-shallow-repository` false, so the D-ISO-4 gate path does not refuse forever.

## Findings
1. **LOW `national-budget/schedule-rerun-no-cap`** (same family as S2b finding 4). `.github/workflows/national-update.yml:175-177`,
   collect job `if:`. D-ISO-3 closes dispatch, but `github.event_name == 'schedule'` stays true on every re-run of a
   scheduled run. Any write-access account can "Re-run all jobs" back to back, each spending up to 360 requests on
   webapi.legistar.com (ADR 0013 ~200/day). Concurrency only queues. Fix: `(github.event_name == 'schedule' &&
   github.run_attempt == '1') || (github.actor == 'gn0sh' && github.triggering_actor == 'gn0sh')`; extend 12.3 #11.
   Owner devops-engineer.

## Nits
a. D-ISO-4 relies on `gh attestation verify --format json` printing only verified attestations (gh 2.89 help says so).
   Defence in depth: jq filter `select(.buildSignerURI == <pinned> and .sourceRepositoryRef == "refs/heads/main")`
   (daily-update.yml:338, national-update.yml:147). Wrong path fails closed; Clarksville unaffected. Verify on first real run. devops.
b. `dates/no-raw-utc-day` exemption covers all of `<main>` on digest pages (qa/site_checks.py:175-183, :3084-3085), so our
   own labels there go unchecked. Security holds (digest/<st>/*.html only; outside <main> checked; escaped data can't forge
   <main>). Later: a `data-feed` wrapper and exempt only that. backend.
c. Rebuild-only runs write no run-log.json, so a degraded rebuild opens no D-ISO-9 issue (warning/error lines only,
   daily-update.yml:1090-1091). Acceptable; record in 12.2 as built. devops.
d. National-update gate now unshallows national-data history (~730 commits/yr, blob:none) inside a 10-minute gate with
   no step timeouts; national runs only. Watch duration. devops.
e. Update job budget not summed like the gate's (3 + 2 + 5 min of national steps in a 355-min job whose cold run is 4-5 h).
   Residual, not a break; note in 12.1 row 4. architect.

Open gates carried from S2b: ruling 5 (">20% stale" issue) not implemented, required before switch-on with a collected
entry. 12.3 #12: "Clarksville site is not affected" line stays dropped (national-update.yml:410-411) until 12.3 #1-9 are on main.

## S2b findings: status
1. withheld-stop-holds-site: closed (national_copy.py:217-219 -> stale_feed, `withheld-items`, id + count only; CopyError
   only for reviewed config in load phase; test 12.3 #2).
2. date-crashes-build: closed (civil_day/instant_ok/date_problem national_copy.py:156-189; `[0-9]` in schema,
   HOST_OK_DATE_RE, adapter DATE_RE; test 12.3 #3: Arabic-Indic, fullwidth, 2026-02-30, pre-epoch, future).
3. gate-timeout-budget: closed (checkout 2 + history 8 + lookup 3, job 14; tested; history takes ~4 s today).
4. dispatch-no-daily-cap: closed for dispatch; regex 1-360 exact. Re-run route open (finding 1).
5. attest-source-commit-unchecked: closed with nit a (digest regex-checked 40 hex, `grep -Fxq --` against
   `git rev-list --first-parent HEAD`; national gate fails closed; daily lookup soft). Accepted residual: any earlier
   main commit's attestation counts (I-prov model).
6. collect-runtime-token-cache: accepted residual recorded in section 8.
S2b nits: a closed; b closed (12.3 #8: withheld, bad-date, missing path, symlink, `read_body_file` never called);
c still needs real-run verification; d closed (line dropped); e closed (runbook: reset is Brian's, hard stop 2; ruleset
blocks force-push and deletion).

## Checked and holding
- Off is byte-identical: build.py doesn't call `run` when off; `national`/`national_states` live only in build/run-log.json,
  never uploaded/deployed/committed.
- On, three phases hold: only load_phase errors (NationalConfigError, FeedError, CopyError from reviewed files) and the
  tier-2 no-data rebuild raise NationalBuildError, the only exception build.py maps to BuildError. Tier 1 per government
  rebuilds from stale_feed alone; tier 2 catches Exception after load, clears out/digest/, rebuilds stale with no
  Clarksville inputs.
- Tier-2 fallback cannot publish withheld text (stale_feed only; withheld check first; sentinel test; leftovers cleared).
- Annotations print only id_layer-valid ids, fixed state words, exception type names, integer counts (12.3 #13).
- D-ISO-9 issue step (daily-update.yml:1081-1126): no `${{ }}` in run:, fixed title, --body-file, anchored id regex,
  fixed state case list, github-actions-authored lookup only, continue-on-error, 5-min timeout, main only.
- Workflows: no `${{ }}` in any run:; every continue-on-error step has timeout-minutes; permissions unchanged; no
  coupling between the two workflows (12.3 #10).
- B-ISO-6 scope can't reach Clarksville pages or text outside <main>; multiple <main id="main"> -> checked whole.
- Zone labels and adapter route checks at load; unreadable council listing degrades only that council.

## Ledger keys
`national-budget/schedule-rerun-no-cap` (LOW; second hit in `national-budget` after S2b finding 4, so the architect states
the budget invariant before the fix). No new hit in `national-isolation` or `data-prov`.
