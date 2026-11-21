# Security review S2(b): Daylight Digest D1 `national-update.yml`, D2 copy step @ c7aa77a

Reviewer: security-engineer (opus/high), 2026-11-20. Read-only. Diff 519b9c0c..c7aa77a0 (D1 `.github/workflows/national-update.yml`; D2 `.github/workflows/daily-update.yml`, `sitegen/national_copy.py`, `sitegen/national_pages.py`; tests).
**Verdict: PASS WITH FINDINGS.** No critical/high. OK WITH FOLLOW-UPS: findings 1 and 2 must land before `national.enabled: true` with any collected (Legistar) entry; finding 3 should land with this PR.
Tests: tests/test_national_workflow.py, test_national_copy.py, test_workflow_lock.py: 624 passed.

## Findings
1. **MEDIUM `national-isolation/withheld-stop-holds-site`** (proposed family `national-isolation`: ADR 0013 decision 6, "a national failure never holds a Clarksville deploy").
   sitegen/national_copy.py:141-143 raises CopyError on `withheld_stripped > 0` -> NationalBuildError (national_pages.py:388) -> BuildError (build.py:1056): the whole site build fails and the Clarksville deploy is held. Proven: a file collected while the entry was shown, read after the entry is narrowed to `items: withheld`, raises CopyError. Impact: a narrowing PR (the privacy safety valve) cannot deploy until a national run rewrites the file; the stop un-publishes nothing (national-data is public, 11.1 row 20).
   Fix: on `withheld_stripped > 0`, return `stale_feed(entry)`, set `CopyCounts.state = "withheld-items"`, print `::warning::` with id and count only; never raise. Keep CopyError only for reviewed-config problems (`_platform_keys`). Edit 11.2 in place. Test: narrowing case -> stale page, build completes.
2. **LOW `national-isolation/date-crashes-build`**. Schema `\d` patterns accept any Unicode digit and no calendar check. Proven: `2026-02-30` or Arabic-Indic digits pass `copy_feed`, then `national_pages.long_day` (:441, outside `run()`'s try) raises ValueError and fails the build. Fix: after `feed_errors`, every `meetings[].date` fullmatches `[0-9]{4}-[0-9]{2}-[0-9]{2}` and parses with `date.fromisoformat`; `checked_at`/`last_ok_at` (when not null) parse with `nat._parse_instant`; else `stale_feed`. Optionally schema `\d` -> `[0-9]`. Tests for both.
3. **LOW `national-isolation/gate-timeout-budget`**. daily-update.yml gate `timeout-minutes: 10` now holds the history check and the D2 lookup (step timeout 3); `continue-on-error` doesn't survive a job timeout, so a timeout blocks the Clarksville deploy even with the switch off. Fix: gate timeout 13 with a test that it is >= 10 + lookup timeout (or move the lookup to its own job read with `!cancelled()`).
4. **LOW `national-budget/dispatch-no-daily-cap`**. Any write-access actor can dispatch back to back (360 requests per run vs ADR 0013's ~200 a day). Fix: collect `if:` adds `&& (github.event_name == 'schedule' || (github.actor == 'gn0sh' && github.triggering_actor == 'gn0sh'))`, as daily-update does; test. Nit: shell regex allows 1-999 (argparse caps 360).
5. **LOW `data-prov/attest-source-commit-unchecked`** (optional, shared with records-data I-prov). `--cert-identity` pins workflow, ref and repo, not the source commit; a ruleset-bypass race lets one daily run accept an attestation from a main commit pushed after S. Fix: `--format json`, require `sourceRepositoryDigest` in `git rev-list --first-parent HEAD`, both lookups.
6. **LOW `national-ci/collect-runtime-token-cache`** (accepted residual; record in architecture section 8). RCE in the collect job could read ACTIONS_RUNTIME_TOKEN and poison main-scoped caches the update job restores; the update job's PDF parsing already carries the same exposure.

## Rulings on the engineer's open items
1. No second history check in national-update: accepted (ADR 0011 I-prov model; residual is finding 5).
2. Update job builds `digest/` from national-data: same trust as records-data, accepted (no new privilege; data outside `data/`; `copy_feed` treats every byte as untrusted).
3. Withheld items stop the build: change it (finding 1).
4. Budget via `vars.NATIONAL_REQUEST_BUDGET`, CLI caps 360: OK (see finding 4).
5. >20% stale issue: defer while the switch is off; required before it goes on with a collected entry (devops).

## Nits
a. Collect step: `env -u GITHUB_STATE` too. b. Add a test: switch off + `RECORDS_NATIONAL_DATA` pointing at a bad/withheld file leaves the build byte-identical. c. Attestation refusals tested only with a fake `gh`: verify on the first real run after U3-0 (a branch dispatch must not be read). d. Report issue text "The Clarksville site is not affected" is untrue until finding 1 lands. e. An unattested national-data head makes the gate refuse forever; recovery is a reset (hard stop 2): note it in the U3-0 runbook; ruleset must block force-push and deletion.

## Needs verification
- Action SHAs vs upstream tags (no GitHub API here): all five pins are byte-identical to those daily-update.yml already used at 519b9c0c, all 40-hex.
- Real `gh attestation verify` behaviour (nit c).

## Checked and holding
- Tokens: workflow `permissions: {}`; collect has contents read only, no token in any step env, `persist-credentials: false`; push is the only writer and runs only git/cp/find; report has issues write only.
- Push: only `data/national/**`; tree checked; one commit on N; artifact validated (no symlinks/special files, path allowlist, 20 MB/file); fast-forward only; attest before push.
- Identity pinning in gate and lookup (`national-update.yml@refs/heads/main`, source-ref, repo, slsa v1, `--deny-self-hosted-runners`); records and national gates don't accept each other's attestations; no `workflow_call`/`pull_request` trigger.
- Tree helper (NUL records, LC_ALL=C, data/ only, mode 100644 only); seed accepted only parentless with pinned digest; lookup never reads the seed, caps at 10 commits.
- Copy step: symlinks and FIFOs refused, 8 MiB cap, depth 32, any exception -> stale, body rewritten from the directory, logs ids and counts only.
- Logs (4.6): stop-commands with random token; GITHUB_OUTPUT/ENV/PATH/STEP_SUMMARY unset for the CLI; CLI output never captured or uploaded; issue body fixed text.
- No `${{ }}` in any `run:` block; inputs via env, regex-checked.
- Concurrency `national-collect`, no cancel.
- Switch off: `national_pages.run` not called; national steps `continue-on-error`, write outside `data/` (except finding 3).
- Time budget 4.4.4: 1+1+1, CLI 69, then 2; job 75 = JOB_MINUTES (tested).
