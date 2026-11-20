# S1 security review: data-off-main milestone (ADR 0011) at 5fb948f2 vs origin/main 60167e4c

Reviewer: security-engineer (opus/high), 2026-11-18/19. **Recommendation: OK WITH FOLLOW-UPS.** No critical/high findings. Fix S1-1 and S1-3 in the cutover PR before C1 (its pins need a delta review anyway).

Tests run (scratch --basetemp): test_workflow_lock, test_protect_main, test_cutover_data_off_main, test_fetch_data, test_data_shape, test_person_inputs, collector/tests/test_tripwire: final run 888 passed. A first combined run had 2 failed + 92 errors (FileNotFoundError, tripwire and person_inputs) that did not recur on two reruns; needs verification (likely shared scratch clash). Not run: full suite, pwsh (twins read only), pip-audit (deps unchanged).

## Findings

- **S1-1 Medium `main-protect/approval-margin`** (scripts/main-ruleset.json:10; protect-main.sh:153, .ps1:212). R1'' needs exactly 2 approvals, so I-person rule 1 rests on the unenforced gn0sh COMMENT-only rule and on R2 off + one App. Exploit: an outside fork PR adds a workflow; gn0sh (or the team session as gn0sh) approves; claude[bot] approves and merges with no bypass; the workflow runs on main with github-pages and morning-note secrets before the gate can refuse. Fix: required_approving_review_count to the ruleset maximum (believed 10; else the highest accepted); update both protect-main scripts, tests, ADR wording. Nothing legitimate is lost (every real merge is a gn0sh bypass).
- **S1-2 Medium `golive-switch/app-scope-hand-check`** (hand-check text protect-main.sh:187,192; .ps1 ~242; cutover-data-off-main.{sh,ps1}). The hand check asks only about Administration write. Per Claude Tag docs the App acts as claude[bot] with Actions write (dispatch/re-run/enable/disable workflows, delete runs/logs/artifacts), can edit workflows and open PRs; Variables write unknown. With Variables write it could set MORNING_NOTE_SEND or RECORDS_DEPLOY_ENABLED (hard-stop switches). Fix: hand check also requires Variables, Secrets, Environments not Read and write; any other answer NOT OK. Record App Actions write as a residual (DoS, deleted logs, re-runs of older post-baseline runs; does not break I-person). Correct amendment (b)'s "the App's own installation identity is unused" (Claude Tag authors PRs as claude[bot]).
- **S1-3 Medium `data-off-main/rollback-unverified-data`** (cutover-data-off-main.sh:485, .ps1:636). The rollback open path builds PR R from records-data's head with no I-prov check; --merge doesn't check R's data/ either. A writer fast-forwarding records-data with an unattested tree (the very state that prompts a rollback) gets that data to main, unreadable in review, published once R2 is on. Fix: open path refuses unless the head passes verify_attested or is the pinned seed; else take --data-from <sha> (an attested ancestor on records-data); --merge requires R's data/ listing to equal that verified tree.
- **S1-4 Medium `i-pub/t5-same-job`** (daily-update.yml:382,545,943,950). Accept for cutover (no regression), follow-up. Tripwire, build-info.json and the Pages artifact are made in the job parsing untrusted PDFs; a parser RCE can defeat the tripwire, write any HTML, forge build-info, poison caches, and hand J2 a poisoned artifact. Under T5 I-pub gives no protection; ADR consequence (a) (line 118) understates it. Follow-up (backend-engineer): a fresh-runner verify job that downloads only the data artifact, rechecks shape, rebuilds with sitegen, runs the tripwire, writes build-info and uploads Pages; deploy needs only that job (verify sitegen builds without data/store). Architect: reword residual (a).
- **S1-5 Low `data-off-main/seed-window`** (cutover sh:648, step 5). records-data unprotected between seed push (step 3) and R-D (step 4); not rechecked before merge. Fix: re-read records-data just before the merge; stop unless still the seed.
- **S1-6 Low `main-protect/pages-source-unchecked`** (protect-main both). Pages build_type not read; a branch source would publish outside every gate. Fix: read repos/{r}/pages; NOT OK unless build_type is workflow; refused read is NOT OK.
- **S1-7 Low `main-protect/wf-shape-heuristic`** (protect-main.sh:238+, .ps1). Awk heuristic on job indents; only daily-update.yml read. Fix: list .github/workflows/ on main; NOT OK for any other file.
- **S1-8 Low `data-off-main/seed-data-unreviewed`** (cutover sh:353). Accept, pre-existing M-2: the 4.7.1 window excludes data-only commits, so the seed may carry data a bot merged pre-cutover; it equals what is live today and passes shape and phone checks.

## Confirm or refute
- **F1 as amended by I-person: confirmed with conditions.** R2 off and only claude installed: approvers are gn0sh and at most the App; bypass lists read and compared (R1'' admin role in pull_request mode only; R-D, R-T none); no GITHUB_TOKEN/deploy key gets Administration. App permissions remain Brian's hand check (S1-2); margin thin (S1-1).
- **Only J2 on main mints accepted data: holds in substance**, exceptions: the pinned seed (while D is parentless); J2 of any post-baseline daily-update.yml version on main incl. re-runs; J2 attests what update hands it (S1-4); in theory a compromised pinned action in deploy/push could get a Fulcio cert (storing still needs attestations write). Ruled out: branch runs, tags (exact SAN + --source-ref), workflow_call (triggers pinned by test).
- **Phase-0 removal: confirmed.** Empty baseline on main refuses; push and deploy need verified == 'true'; step 1 needs exactly one 40-hex pin equal to origin/main; step 5 squash parent == pin. At 5fb948f2 both pins are "" and the pinning commit needs a delta review.
- **Residuals:** attested-but-unpushed (f) confirmed, accept (public artifacts downloadable 2 days, still J2's checked output, I-pub applies). T5 confirmed and wider (S1-4). App fast-forward of records-data confirmed: unattested refused (DoS), replay accepted and bounded by I-pub; accept. Comment-only rule unenforced; S1-1 makes it non-load-bearing.
- **Supply chain OK:** attest-build-provenance@96278af6 = v3.2.0 (git ls-remote), nested predicate@864457a5, actions/attest@e59cbc1a pinned; checkout@11d5960a = v4.4.0.
- **Workflow injection OK:** no ${{ }} in run blocks; issue text fixed or --body-file with ASCII-filtered tripwire lines.
- **Secrets OK:** note job unchanged and the only one with secrets; gate/update keep no token on disk; push keeps its token but runs no repo code; its artifact limited to *.json and changes.jsonl, no symlinks.
- **Rollback:** F4 ordering holds (R2 on only after both variables confirmed unset, over a commit with CODEOWNERS and one empty baseline); data source unverified (S1-3); rollback returns to the known pre-cutover T7-open state (R1' + R2): keep it time-boxed.
- **Also holds:** gate data/ shape check (top entry, SHAPE'', curated names, PERSON any case, counted as bytes); seed recognition from raw commit header; tripwire live_tree needs an ancestor on records-data, any failure holds; allow_shrink needs gn0sh as dispatcher and triggering actor; fetch-data refuses symlinks/submodules (both twins); merge-reviewed refusals and .sh/.ps1 parity.

## Decisions this changed

| Finding | Decision changed | Scope | Owner |
|---|---|---|---|
| S1-1 approval margin | yes: R1'' count 2 -> API max (10?) | adds (small) | devops-engineer; architect (ADR text) |
| S1-2 App hand-check scope | yes: hand check adds Variables, Secrets, Environments; App Actions write residual; ADR inference corrected | adds | devops-engineer; architect |
| S1-3 rollback data unverified | yes: rollback verifies I-prov on the restore source | adds | devops-engineer |
| S1-4 T5 same job | no for C1 (accepted, no regression); follow-up verify job; ADR residual (a) reworded | adds later | backend-engineer; architect |
| S1-5 seed window | yes: re-check seed before merge | adds (tiny) | devops-engineer |
| S1-6 Pages source | yes: protect-main reads build_type | adds (tiny) | devops-engineer |
| S1-7 workflow-shape heuristic | yes: list workflows folder on main | adds (tiny) | devops-engineer |
| S1-8 seed data from data-only bot merges | no: accepted, pre-existing M-2 | none | none |
| Residuals (f), App fast-forward, comment-only rule | no: accepted as stated | none | none |

Manager's ledger call: S1-1, S1-6, S1-7 are hardening of margins and drift checks, not breaks of I-person today; not counted as main-protect family hits.

Source: Claude Tag docs, Configure GitHub access: https://claude.com/docs/claude-tag/admins/configure-github
