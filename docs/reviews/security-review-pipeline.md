# Security review: daily-update pipeline (1802b97)

Date 2026-11-09. security-engineer (opus/high), read-only. **Verdict: PASS WITH FINDINGS.** Nothing blocks merging while the deploy lock is off; F1 must be fixed before go-live.

Holds: deploy lock (vars.RECORDS_DEPLOY_ENABLED, implicit success() of update, update job has no pages/id-token), workflow-level permissions {}, no secrets, no pull_request triggers, no script injection (inputs only in if:, outputs are integers, commit message from date), all 5 action pins verified by git ls-remote, env overrides constant and fail closed, one concurrency group.

| # | Sev | Key | Where | Action |
|---|---|---|---|---|
| F1 | MEDIUM | domain/dangling-cname | launch-runbook.md:89-93,119-121 | Fix before go-live: step 0 verify gnoshcodes.com at github.com/settings/pages (TXT `_github-pages-challenge-gn0sh` at Porkbun); set custom domain and CNAME back to back; rollback deletes the CNAME unless verified |
| F2 | MEDIUM | pipeline/token-exposure-untrusted-parse | daily-update.yml:46 | persist-credentials: false; token only in the push step, or a separate push job |
| F3 | LOW | pipeline/cache-integrity | daily-update.yml:64-69,122-127; collector/store.py:61-62 | re-hash restored store files against data/manifest.json; refetch mismatches |
| F4 | LOW | pipeline/parser-dos | extract.py:18, ocr.py:37-40, pdfwords.py:100, city_minutes.py:129-131 | subprocess timeouts; timeout = parse failure |
| F5 | LOW | deploy/env-branch-policy | launch-runbook.md:82-83 | github-pages environment deploys from main only |
| F6 | INFO | pipeline/failure-issue | daily-update.yml:107-115 | accept |

Runbook note at :134 about two unverified pins is stale.
