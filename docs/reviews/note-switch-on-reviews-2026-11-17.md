# Morning note switch-on: review log (2026-11-17)

## Security a23427e: OK WITH FOLLOW-UPS
- M1 note-key/writer-reach-whole-list (medium): Actions bypass lets a workflow on any branch push main and reach BUTTONDOWN_API_KEY. Fix: data PR instead of bypass (da68c8f).
- L1 audience/stamp-rerun-false-stray, L2 audience/form-tags-any-address (accept), L3 audience/stamp-wipe-race (accept), L4 signup/resubscribe-unverified (runbook 4a), L5 signup/abuse-cap (Buttondown firewall on), L6 note-key/scope-unverified (key made scoped per Brian's steps), L7 render/archival-not-echoed, L8 links/gov-open-redirect (runbook 4.2).

## Code review a23427e: REQUEST CHANGES
- CR1 note/privacy-url-unverified (must; resolved: security opened it). CR2 sender/tags-silent-zero, CR3 sender/run-time-budget, CR4 sender/claim-listing-unbounded, CR5 sender/tags-seat-change, CR6-8 nits, CR9 sender/claim-plan-identity. All fixed in 55c097a.

## Code review delta 55c097a: REQUEST CHANGES
- audience/stamp-rerun-false-stray (must, 2nd audience hit): re-stamp path can send two notes after 07:00. Invariant adopted: holder of a created edition's stamp is never placed in another edition that day.
- render/archival-not-echoed (check only when present), sender/stamp-idem-replay (nit), unticked-holder still mailed (accept).

## Security a23427e..f001eed: OK WITH FOLLOW-UPS, gate on switch-on
- V1 main-protect/bot-merge-workflow-file: needs verification, critical if false. GITHUB_TOKEN merge of a PR touching .github/workflows must be refused. MORNING_NOTE_SEND stays unset until verified.
- M-A main-protect/bot-merged-code-reaches-site (medium): gate job before update/deploy/note.
- L-A note-job/plan-built-on-unchecked-sha, L-B audience/done-stamp-restamped (= delta must-fix), L-C push/server-check-vacuous-zero, L-D main-protect/user-merge-launders-branch-push (merge only pinned head sha, auto-merge off), L-E main-protect/actions-approve-hazard.
- main-protect family 2nd hit -> architect invariant (r2-protect-inv).

## Code review delta 7a88126: APPROVE WITH NITS
- sender/ids-no-invariant (nit: ids mode unusable on Buttondown; add guard/comment).
- note/credit-logo-privacy (nit: remote footer image shows Pages the reader's IP/open time; add Method/privacy line or inline image). Owner: frontend, with the CMCSS note.

## CMCSS note r2-cmcss-note: REQUEST CHANGES -> delta APPROVE WITH NITS (63552b6, nit fixed bd336ba)

## Security gate ddf075f..402c0f0: OK WITH FOLLOW-UPS (no critical/high)
- M-1 main-protect/review-by-any-account (medium): gate accepts a review by any GitHub user; require author_association OWNER/MEMBER/COLLABORATOR or login allowlist. Fix BEFORE baseline is set.
- M-2 main-protect/bot-data-merge-unbound (medium): any branch workflow can bot-merge a data/-only PR; architect: record residual or bind to daily run.
- L-1 main-protect/baseline-reset-downgrade, L-2 v1-probe/verdict-from-main-sha, L-3 main-protect/baseline-blesses-phase0.
- Info: GraphQL merge path untested by V1 probe; do runbook 2.0.5 first.
- Closed: M-A (in code; ops once baseline set), L-A, L-C, L-D (merge-reviewed path), L-E.
