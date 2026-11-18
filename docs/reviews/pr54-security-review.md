# PR #54 security review (76f83c71): APPROVE WITH FOLLOW-UPS
security-engineer, opus/high, 2026-11-18. No critical or high. U3 safe on the live repo once finding 6 is in U3-1.

Most serious: main-protect/settings-drift (medium). The design rests on repo settings no daily run can see (R1'',
bypass list, R2 off, single writer, env policies), and the team proxy refuses actions/permissions, collaborators and
environments reads. Fix (D1 + runbook): protect-main NOT OK on any refused read; unset MORNING_NOTE_SEND before R2 on
or a ruleset change; re-run protect-main from Brian's PC after any settings change and before MAIN_PR_BASELINE.

| # | Sev | Key | Fix | Owner |
|---|---|---|---|---|
| 1 | M (verify) | main-protect/writer-set | count installed Apps with write + deploy keys as writers; NOT OK if any besides gn0sh | devops (D1) |
| 2 | M (verify) | main-protect/env-ref-type | env policy `main` must be type branch; tag ruleset blocking `main` tag; V1'' item; platform-facts:380 reconcile | devops, writer |
| 3 | M | main-protect/attest-signer-scope | deploy already has id-token (daily-update.yml:990); restate as only J2 has attestations:write; verify with --cert-identity ...@refs/heads/main + predicate type | backend (B3), architect |
| 4 | M | main-protect/rollback-reopens | rollback refuses while MORNING_NOTE_SEND or MAIN_PR_BASELINE set | devops (D3) |
| 5 | L | main-protect/cutover-order | apply R1'', R-D, R2 off before the cutover merge | devops (D3) |
| 6 | L | v1-probe/u3-worst-case | one whitelisting PUT-body builder; exact read-back; backup path printed | devops (U3-1) |
| 7 | L | main-protect/replay-scope | seed digest only while head is seed; allow_shrink never bypasses I-pub; residual in ADR | backend, architect |
| 8 | L | main-protect/team-token-anchor | moot: U3-0 = no (proxy 403); record that ruleset writes are Brian's | architect |

Hard stop: C1 cutover is a production change (hard stop 1): explicit "Cut over Daylight's data today? yes / no".
Checked and holding: no administration scope on GITHUB_TOKEN; R1'' blocks direct push/merge; no PR reaches 2
approvals with gn0sh sole writer and R2 off (subject to 1); bypass admin-role only; triggers schedule+dispatch only;
gate reads D once; caches outside D; public Sigstore log fine.
