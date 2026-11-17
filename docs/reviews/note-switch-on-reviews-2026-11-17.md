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

## Security re-derivation of the gate follow-ups at 33da134 (2026-11-17, opus/high): OK WITH FOLLOW-UPS
The earlier report's detail was lost with the old thread, so security re-derived each finding from the code.
- M-1 main-protect/review-by-any-account (medium): `daily-update.yml:144-145` accepts a review from any `User`; the repo is public, so any account's COMMENT review at head passes 5(d). Fix: also require `author_association` OWNER or COLLABORATOR (owner gn0sh is a User account, so MEMBER never applies; OWNER/COLLABORATOR chosen). Update `REVIEW_JQ` (tests:1204), `_review(assoc=)`, cases outsider/contributor refused, collaborator accepted.
- M-2 main-protect/bot-data-merge-unbound (medium): `daily-update.yml:122` excludes data-only commits, so a branch workflow's bot-merged data PR is never checked; the gate also never checks data/ file types (a symlink named `x.json` passes test 242).
- L-1 main-protect/baseline-reset-downgrade (low): an empty baseline on main passes with `verified=false` (`:111-114`); a PR resetting it to "" reopens phase 0 silently. Fix in the T4.10.8 baseline PR: empty baseline on main = refuse; tests drop the ("", main) pass case, add a refuse case, accept a sha only.
- L-2 v1-probe/verdict-from-main-sha (low): `v1-probe.sh:80,86`, `.ps1:94,101` say FAIL when main's sha moved, not when the probe PR merged; any other merge in the window gives a false FAIL that turns R2 off. `.ps1` also treats an empty main read as FAIL. Fix: FAIL only if the probe PR `.merged` is true or `v1-canary.yml` exists on main; main moved but PR unmerged, or empty read = INCONCLUSIVE, R2 untouched. Tighten `named` to `without .workflows. permission`.
- L-3 main-protect/baseline-blesses-phase0 (low): runbook 4.7.1 (`morning-note.md:297-300`) reads `%an`, which can't show a bot merge in phase 0. Fix: 4.7.1 lists `merged_by.type` for every non-data first-parent commit since the R1/R2 switch-on and stops on any Bot; paste the output in the baseline PR. Test: runbook text contains `merged_by`.
- Info: V1 probe should also try GraphQL `mergePullRequest` (expectedHeadOid, SQUASH); any GraphQL merge = FAIL; regexes take `graphql`, count 4.
- Checked and holds: gate 5(a)-(c) fail-closed paths, baseline moves, non-main runs can't push/deploy, no secrets in the gate.

## Architect decision on M-2 (2026-11-17, opus/high): (A) accept as residual, plus two checks
- Binding data merges to the daily run can't be made sound: no GitHub record links a PR or merge to the run that made it (branch name, body, message, author are all writable by any `GITHUB_TOKEN`), and a person with write can already merge a data-only PR by hand, which I-main deliberately doesn't check. data/ is untrusted input already (from public PDFs), read only via `json`/`yaml.safe_load`, rendered with autoescape.
- Add: (1) gate shape check, inline, after the not-main exit and before the baseline check (runs in phase 0 too), git only: every `git ls-tree -r` entry under data/ is mode 100644 and named `*.json`, `*.yml` or `changes.jsonl`, else refuse. Verify `ls-tree` works on the blob:none partial clone without fetching blobs. (2) Test: across `.github/workflows/*.yml`, only daily-update.yml's `push` job may grant `contents: write` or `pull-requests: write`.
- Residual paragraph added to `docs/architecture/main-protect-invariant.md`; I-main wording and row D say the gate checks data/'s shape; one line in ADR 0009 Consequences. Reopen if another workflow needs write permissions, or if the note ever sends without the E2 reviewer.

## Security r3-gate-fixes 0a70bbe..6e3c019 (2026-11-17, opus/high): OK WITH FOLLOW-UPS, S-1 before merge
- S-1 main-protect/shape-check-locale-fail-open (medium, 3rd main-protect hit): the gate's `grep -vE` on the data/ listing, under a UTF-8 locale, withholds lines with invalid UTF-8 ("binary file matches", exit 0), so a symlink named `data/\xff.json` passes. Reproduced with LC_ALL=C.UTF-8 (pass) vs LC_ALL=C (refuse). Fix: `LC_ALL=C grep -a`, plus count check (total lines == lines matching the allowed shape); test with non-UTF-8 names under C.UTF-8.
- L-a main-protect/shape-absent-data (low): a tree with no data/ passes (empty listing); refuse unless `HEAD:data` is a tree and the listing is non-empty.
- L-b main-protect/baseline-window-start (low): runbook 4.7.1 loop passes silently on a bad/placeholder sha; window should start when R2 was first turned on; record the sha, `set -e`, print "checked N commits", stop on N=0.
- L-c v1-probe/verdict-race (low): verdict can be read while the run is still going; require run status completed, re-read `.merged` after cleanup.
- Info: GraphQL refusal text unverified (record from first run); author_association is read-time (fail closed on removal); raw names in `::error::` (strip control chars); pre-existing `-ExecutionPolicy Bypass` in scripts/morning-note-probe.cmd/.ps1:4.
- Holds: M-1 jq, check placement, -z parsing, type refusals, failed reads, partial clone, probe verdicts, GraphQL step privileges, write-permission test.
- Loop rule: 3rd main-protect hit -> architect restates the data/ shape invariant (incl. encoding) before the fix.
