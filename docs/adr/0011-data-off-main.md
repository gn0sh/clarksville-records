# ADR 0011: Collector data moves off `main`; no workflow can merge into `main`

Status: **Accepted (U3 PASS 2026-11-18; cutover merged 2026-11-19, 8d69778).** Proposed by software-architect, 2026-11-18, gated on U3 (`docs/ops/u3-positive-control.md`). Supersedes
ADR 0010 decisions 1 (CODEOWNERS), 2 (ruleset R1') and 5 (the V1' probe). ADR 0010 decisions 3 (R2 on, now
interim), 4 (canary removal, done by #52) and 6 (the gate stands) remain. Analysis, invariant and every consumer:
`docs/architecture/v1-fail-2026-11-18.md`. Panel: `docs/reviews/brain-trust-data-off-main.md` (Fix First, 5-1).
Tasks: `docs/tasks/data-off-main.md`. Amended 2026-11-18 for the PR #54 security review
(`docs/reviews/pr54-security-review.md`, findings 1-8 and settings drift). Amended 2026-11-18 (decision 2a) for the
person-run writers B1 found (`docs/architecture/data-inventory.md`).
Amended again 2026-11-18 (writer set and the Claude GitHub App): see "Amendment 2026-11-18 (b)" at the end; it
supersedes decision 6's writer rule and finding F1's wording.
Amended 2026-11-18 (c) (phase 0 after the cutover, finding main-protect/phase0-attest): see "Amendment 2026-11-18
(c)" at the end; it supersedes decision 7's baseline order and the rollback's baseline check.

## Context
The V1' probe (run 44354265953) FAILED. `GITHUB_TOKEN` squash-merged #49, which adds a workflow file, under
`require_code_owner_review: true` with 0 required approvals. Rule suites show the `pull_request` rule read `pass`,
not `bypass`, for #48, #49 and #52, so the code-owner requirement never applied. This is the second failed fix in
the `main-protect` family. With data on `main` and merged by a bot, I-main needs a path-aware merge rule that this
repository (public, user-owned, GitHub Free) doesn't offer: a branch ruleset's PR rule has no path condition, and
push rules are for private Team or internal Enterprise repositories. Verified on Brian's PC (2026-11-18): both
environments allow `main` only (custom policy), Pages build_type is workflow, and `morning-note` has no required
reviewer.

## Decision
1. **Collector output lives on branch `records-data`** (tree = `data/` only). Ruleset R-D: `deletion` and
   `non_fast_forward`, no bypass, no PR rule. The push job fast-forwards it with `GITHUB_TOKEN`. `main` tracks no
   `data/` (gitignored). The gate refuses a tracked `data/` on `S`.
2. **Curated inputs are code** (Brain Trust change 1). `data/names.yml`, `data/procedural-titles.yml` and
   `data/corrections-log.json` move to `config/`, reviewed like any code. `data/` keeps only what the collector
   writes. `SHAPE''` narrows to `*.json` and `changes.jsonl`, and the gate refuses the curated names in `D`. An
   inventory task confirms each remaining file's writer.
2a. **No person writes `records-data`** (invariant I-in, `docs/architecture/v1-fail-2026-11-18.md` section 2). B1
   found four person-run writers of `data/`. Under I-prov a person's new tree is refused, so each gets a reviewed
   path through `config/` on `main` instead (task B1b):
   - **Transcripts** (`collector/transcripts.py` `import` :274/:295 and `remask` :319/:322; 18 files, 2.5 MB) move
     to `config/localities/<locality>/transcripts/`. A person runs `fetch-data`, then the import on the Whisper
     output from Brian's PC (it reads the facts and event listing from the fetched `data/`), and opens a PR. The
     importer masks before it writes, so the PR carries masked text only and raw text never reaches a branch. The
     PR is the review point, including Brian's sample OK before any new batch goes live. `sitegen` and `qa` read
     transcripts only from `config/`, with no fallback to `data/`.
   - **Map manifest** (`tools/fetch_map.py` :25/:43) moves to `config/maps/manifest.json`. It is read at build
     time through `config/site.yml` `fetch_manifests` (:17), so that entry changes too.
   - **Kept city books** (`daily-update.yml` ~:581, `collector/fin_books.py` `worse_than_committed`): "a person
     runs `fin-books build` and commits" ends. A person reproduces the reading locally (`fetch-data`, `fin-books
     fetch`, `fin-books build`; `data/` is gitignored, so nothing is committed from it), then either fixes the
     reader by PR or lists the reviewed reading in the new `config/fin-books-accepted.yml` (`locality`, `book_id`,
     the new file's full `source_sha256`, `listed_on`, `reason`). The next daily run rebuilds. An entry lets the
     build replace that book only while the stored book's sha256 differs from the listed one, so it is spent once
     the new reading is on `records-data`.
   - **`tools/scrub_rpc_phones.py`**: its rewrite mode is removed (`collector rpc build` already strips phones, so
     the daily rebuild writes the same). `--check` stays, read-only, and the cutover runs it on the seed.
   `CURATED_NAMES` gains `fin-books-accepted.yml`, and `collector/data_shape.py` also refuses any path under
   `data/maps/` or a `transcripts/` folder in `D`. The seed leaves them out. Readers that list `data/` through
   git (`qa/pii_scan.py` `tracked_files`, `tests/test_committees_daily.py:26`) read the fetched tree instead and
   fail on an empty one.
3. **Provenance** (change 2). After pushing, the push job attests the new tree listing (`git ls-tree -r -z D -- data`
   as a file) with `actions/attest-build-provenance`. The gate reads the `records-data` head once (`D`) and accepts
   it only if that listing verifies, or `D` is the seed (below). Verify:
   `gh attestation verify <listing> --repo gn0sh/clarksville-records --cert-identity
   https://github.com/gn0sh/clarksville-records/.github/workflows/daily-update.yml@refs/heads/main --source-ref
   refs/heads/main --predicate-type https://slsa.dev/provenance/v1 --deny-self-hosted-runners`.
   **Signer scope (finding 3):** the certificate names the workflow file and ref, not the job, and the `deploy` job
   already holds `id-token: write` for `deploy-pages` (`daily-update.yml:990`). So the property is: only J2 holds
   `attestations: write`, so only J2 can store an attestation the gate will find, and only on `main`'s
   `daily-update.yml` at `refs/heads/main`. The predicate type pins it to the provenance J2 writes.
   **Seed scope (finding 7):** `RECORDS_DATA_SEED_DIGEST`, pinned by the cutover PR, is accepted only while `D` is
   the seed commit itself (the root of `records-data`, no parents). R-D refuses non-fast-forwards, so once a run has
   moved the branch, a tree equal to the seed is checked like any other. The seed itself is never attested, so a
   rollback to the seed tree after the first run fails closed (accepted). **No `data_sha` input.** Rollback: a
   person restores an earlier attested tree whole on `records-data`, then runs `collect=false`.
4. **Content tripwire** (change 2). J1 compares the votes, roll calls and outcomes in the `D` recorded in the live
   site's `build-info.json` with what this run will deploy. Any change or removal not listed in the reviewed
   `config/published-fact-changes.yml` opens one fixed-title issue and holds the deploy (`held=yes`). The data push
   still happens. `allow_shrink` never bypasses it (finding 7): only the reviewed list does. This extends ADR 0006's guards, which see only one run's collection.
5. **Ruleset R1'' on `main`:** `required_approving_review_count: 10` (the ruleset maximum; was 2 before amendment (d), S1-1), `dismiss_stale_reviews_on_push: true`,
   `require_last_push_approval: true`, `require_code_owner_review: false`, squash only, bypass Repository admin role
   in `pull_request` mode. `.github/CODEOWNERS` is deleted. Every merge into `main` is a person's bypass merge via
   `merge-reviewed`, which refuses PRs not authored by gn0sh or with a head in another repository.
6. *(Writer rule superseded by Amendment 2026-11-18 (b); the rest stands.)* **R2 off from the cutover on, and load-bearing.** R1'' is unreachable for a bot only while there are exactly
   two writers (gn0sh and github-actions[bot]) and R2 is off. `protect-main` writes R1'' and R-D, turns R2 off, and
   reports NOT OK if R2 is on, or if anything besides gn0sh can write: a collaborator with write or more, an
   installed App with contents write, or a deploy key with write (finding 1). Both environments' `main` policy must
   be of type `branch`, and tag ruleset R-T blocks creating a tag named `main` (finding 2).
   **Settings drift (the review's most serious item):** this rests on settings no daily run can read, and the team
   proxy refuses the `actions/permissions`, `collaborators` and `environments` reads. So `protect-main` reports
   NOT OK on any refused or failed read, never OK by default. It runs from Brian's PC after any settings change and
   before `MAIN_PR_BASELINE` is set. `MORNING_NOTE_SEND` is unset before R2 goes back on or any ruleset changes.
7. **Order** (change 3). U3 runs first, as a scripted live toggle, before any rework. If it fails, this ADR is
   rejected and the fallback below applies. The cutover is one scripted session in the Operator's order (task list
   D3), with `protect-main` (R1'', R-D, R-T, R2 off) before the cutover merge (finding 5). The cutover PR itself
   sets `MAIN_PR_BASELINE` (Amendment 2026-11-18 (c)). After it, the V1'' probe (architecture note section 4) must
   pass before `MORNING_NOTE_SEND` is set.

## Alternatives considered
- **Required approvals 1-2 with data still on `main`:** the bot's data PR can't approve itself. A second identity
  is a new credential (hard stop 5). Rejected.
- **Push rule restricting paths outside `data/`:** the ideal fix, but not available for a public Free repository
  (GitHub changelog 2024-09-10). Rejected for now. Revisit if GitHub extends it.
- **B (status quo, R2 on, approvals 0, gate only) plus a separate sender repository holding the note's key**
  (Budget Hawk, Skeptic, Strategist): about 1 day versus 3-4. It loses because T7 needs only a branch push carrying
  an `on: push` workflow, which a prompt-injected agent could make. A bot-merged rewrite of `daily-update.yml` then
  runs on `main` with both environments, so the site stays deployable by that path (Opponent; medium confidence).
  **This is the fallback if U3 fails.**
- **Don't build; defer the note** (Skeptic): the site keeps T7 open, as above.
- **Person-run writers (decision 2a):** (i) a dispatched "import" job that attests a person's input: the input
  must be reviewed in the repository anyway, so it is `config/` with extra steps, and it puts `attestations: write`
  on a second job. (ii) Keep transcripts in `data/` and let J2 carry them forward: no path to add, remask or remove
  one. (iii) Commit the raw Whisper output and import it in the daily run: raw text holds unmasked addresses and
  must never reach a public branch (`docs/status.md` 2026-11-12). (iv) City books "fix the reader by PR" only: a
  replaced source file is a keep reason on its own, so a correct new reading would have no way in. (v) Drop the
  keep guard: reopens city-books/daily-overwrite-unguarded. All rejected.
- **Throwaway repository for U3:** needs Brian to create a repository and grant the team access to it, and it
  tests a different ruleset and token. Rejected in favour of the scripted live toggle.

## Consequences
- I-main becomes simpler (no data exception). I-run gains `D`, read once by the gate and attested.
- New residuals: (a) attested but wrong new facts from `main`'s own pipeline (a hostile PDF, T5) when they don't
  touch published facts. Under T5 proper (a parser RCE in the update job) I-pub gives no protection, because the
  tripwire, `build-info.json` and the Pages artifact are all made in the job that parses the untrusted PDFs. This
  is no regression (the same job did all of it before). Follow-up: a verify job on a fresh runner (see Amendment
  2026-11-19 (d)). (b) Every merge is a bypass, so the bypass log stops being a signal; the gate's
  person-merge check and the rule-suite read in `merge-reviewed` replace it. (c) Brian is the sole admin, so `main`
  freezes if the team's bypass stops working. (d) Replay (finding 7): a write-token workflow on any branch can
  push an earlier attested tree to `records-data`. The gate accepts it, because a person's rollback needs exactly
  that. I-pub holds the deploy if it drops or changes a published fact; an old tree that differs only in facts not
  yet live deploys. Accepted: the data is still `main`'s own pipeline output. (e) Settings drift: R1'' holds only
  while the settings in decision 6 hold, and only a run of `protect-main` from Brian's PC can see them all.
  (f) Attested but unpushed (the delta review of fb94f5be): the push job attests before it pushes, so a refused
  non-fast-forward push leaves an attestation of a listing that never reached `records-data`; that is harmless only
  because the listing is the workflow's own checked output (the same as residual (d) if it is ever pushed later).
- The push job gains `id-token: write` and `attestations: write`, and loses `pull-requests: write`. It is the only
  job with `attestations: write`; `deploy` keeps its own `id-token: write`. The gate gains `attestations: read`.
- **U3-0 = no** (finding 8): the team's cloud session got a proxy 403 on the no-op ruleset PUT at 17:37 UTC
  2026-11-18 (read-back unchanged). So every ruleset, R2, environment and R-D write is Brian's, run from his PC:
  U3, the cutover's settings steps and any rollback. Those writes are blocked today by the session proxy's
  policy, not by the token's permissions; if that changes, the team-token anchor returns. Re-check U3-0 whenever
  the proxy allowlist changes.
- Decision 2a: transcripts and the map manifest stay in `main`'s tree and grow it (about 140 KB per meeting, so
  about 9 MB for the 65-meeting backlog; judgment, acceptable). They were already in `main`'s history, so nothing
  new is published. A transcript PR is too long to read line by line: review checks the import log (counts,
  matches, skips), provenance and the masking tests, not every line (judgment). A meeting that leaves the facts
  makes a committed transcript stale and fails the build until a removal PR, as today, because the daily run has
  never imported transcripts.
- Local runs and preflight need `scripts/fetch-data`. The multi-city template inherits the two-branch setup through
  `protect-main`.
- Cost: about 3-4 engineer days plus security review. Brian: one U3 session, then one cutover session.
- Reversal: `scripts/cutover-data-off-main --rollback` refuses while `MORNING_NOTE_SEND` or `MAIN_PR_BASELINE` is
  set (finding 4: R2 on reopens the bot path), then re-applies R1' json, restores `data/` on `main` by a
  reviewed PR from `records-data`'s head (the moved transcripts and map manifest stay in `config/`, with readers
  as the cutover PR left them), and turns R2 on. The `records-data` branch is kept.

## Amendment 2026-11-18 (b): the writer set and the Claude GitHub App
Problem family `main-protect`, second hit, so the loop-limit rule applies: the invariant and every consumer come
before the next fix. Trigger: 01dc4d13 made the installed-App check a hand check (no token Brian holds can list
Apps: `user/installations` returns 403 to an OAuth token) and accepts one App, `claude`. Decision 6 and PR #54 F1 say
any App with contents write is NOT OK. The reason 01dc4d13 gave ("one App adds at most one approving identity besides
gn0sh, so no PR reaches 2") is wrong, because gn0sh plus the App is exactly 2. The code's rule is right; the reason
and the invariant behind it are restated here.

**Invariant I-person.** No path without a gn0sh action can move `main` or get a new `records-data` tree accepted by
the gate. A gn0sh action is one by Brian, or by the team's session using gn0sh's access under the playbook. A
compromised gn0sh is out of scope, because gn0sh is admin. Take every credential except gn0sh's together: every
`GITHUB_TOKEN`, every App installation, every deploy key and every outside account. Then:
1. **At most one of them can give an approval that counts toward R1'''s required count** (the ruleset maximum, 10,
   since Amendment (d) S1-1; it was 2). So the count can't be met without gn0sh.
2. **None of them is on a bypass list** of R1'', R-D or R-T, and none can write a ruleset or R2 (no Administration
   write).
3. **None of them can store an attestation the gate accepts.** Only J2, running `main`'s `daily-update.yml` at
   `refs/heads/main` (decision 3), can, and that code reached `main` under 1 and 2.

Team rule that goes with it: gn0sh posts COMMENT reviews only, never APPROVE (`merge-reviewed` already posts COMMENT).
A gn0sh APPROVE on a PR that gn0sh didn't author is the one act that lets a second identity merge without a bypass.

**Checked against each setting** (judgment, high confidence; that App approvals count is assumed, the worst case):
- **R1''** (the ruleset maximum, 10 approvals, was 2 before Amendment (d); the author can't approve, last-push
  approval, stale approvals dismissed, admin-role bypass in `pull_request` mode). With R2 off, the identities that can
  approve are gn0sh and at most the `claude` App. A PR authored or last pushed by gn0sh gets at most 1 (the App), so
  only a bypass merges it, and only gn0sh holds the admin role. Any other PR (an outside fork, the App's own, a
  Dependabot PR) gets at most 2 (gn0sh's and the App's), short of 10, so it too merges only by a gn0sh bypass.
  `pull_request` bypass mode means even gn0sh moves `main` only by merging a PR.
- **R2 off** takes github-actions[bot] out of the approvers. R2 on plus one App gives two non-gn0sh approvers, so
  rule 1 breaks; R2 on stays NOT OK. Two Apps break rule 1 the same way, even with R2 off. Example: Apps A and B
  approve an outside PR that adds a workflow, and any `GITHUB_TOKEN` merges it, with no person anywhere on the path.
- **R-D** (no deletion, no force push, no bypass, no PR rule). Any writer can fast-forward `records-data`: J2, a
  workflow on any branch, or the App. R-D doesn't give I-person; rule 3 does (I-prov).
- **R-T** stops anyone creating, moving or deleting a tag named `main`. With branch-type environment policies, no tag
  reaches an environment.
- **The gate alone is not enough.** A workflow file that reaches `main` runs there with both environments and never
  passes through `daily-update`'s gate. So rules 1 and 2 must hold at the ruleset level. The gate's person-merge check
  (`merged_by.type` User plus a User review at the head) is defence in depth: a bot merge never deploys through
  `daily-update`.

**The Claude GitHub App under each setting.**
- R1'': it can push branches, open PRs and give one approval if it holds pull-requests write. It can't reach the
  ruleset maximum (10) approvals (with gn0sh's it has 2; before Amendment (d) those 2 let it merge), approve its own
  last push, bypass (it isn't on the list and holds no role), or push to `main`.
- R2 governs `GITHUB_TOKEN` only, not the App. That is why the App takes the one approver place in rule 1.
- R-D: it can fast-forward `records-data`, but it can't force-push, delete the branch, or get a new tree accepted.
  **Leftover risk:** it can push an unattested tree, which the gate refuses: the deploy is held until a person
  restores an attested tree (fail closed, a denial of service). It can also replay an earlier attested tree, which is
  accepted (consequence d); I-pub holds the deploy if that changes a published fact. This is the same exposure as any
  write-token workflow and the team's own gn0sh access.
- With `workflows` permission it can push a workflow on a branch. That is exposure W2: both environments refuse it,
  and it can't sign as `main`.
- Inference: the team's PRs are authored and merged as gn0sh (`merge-reviewed` refuses other authors, and U3 read
  `merged_by` gn0sh), so the session most likely uses the App with gn0sh's user token, and the App's own installation
  identity is unused. The rules above still plan for it to act. *(The inference "unused" is corrected by Amendment 2026-11-19 (d).)*

**Unverified: Brian's hand checks, at every `protect-main` run.** (i) The App's slug is `claude`
(github.com/apps/claude). (ii) Its permissions on this repository include no Administration read and write. Both
come from Brian's reading of https://github.com/settings/installations. The script prints his answer and the date
but can't read either one. **A wrong slug fails closed:** any `-Apps` value other than `claude` or `none` is NOT OK,
so the cutover stops until the slug is confirmed and `$allowedApp` is changed by a reviewed PR. The count is what
holds rule 1, not the name, so one App without Administration write keeps rules 1 and 2 whatever it is called. If
(ii) is wrong, the App could edit R1'' or R2, and I-person fails; that is the residual of a hand check. Installing an
App, or widening one's access, is a settings change, so `protect-main` is re-run after it (drift rule, decision 6).

**Consumers of I-person.**
| Consumer | Relies on | Change |
|---|---|---|
| `protect-main` checks (S1) | Rules 1-2: approvals the ruleset maximum (10; Amendment (d)), last-push approval, dismiss stale; R2 off; collaborators and invitations with write: gn0sh only; no deploy key with write; Apps `none` or `claude` (by hand), no Administration write; each bypass list equals its file; R-D, R-T, environment policies of type `branch` | Logic of 01dc4d13 stands. The comments in both scripts carry the wrong reason and need the wording "the ruleset maximum (10) approvals can't be met without gn0sh" (Amendment (d)). |
| `merge-reviewed` (S2) | A gn0sh-authored PR has at most 1 approval, so every merge is a bypass, and `pass` is an alarm (exit 2). It refuses other authors and heads in other repositories, which are exactly the PRs that could reach 2. It posts COMMENT, never APPROVE. | None. |
| `u3-toggle` | Nothing: I-person isn't in force before the cutover (R2 on), and the window only tightens live (0 approvals to 2). U3 PASS is recorded; a re-run is the same. | None. |
| `fetch-data` | Nothing for publishing. It reads `records-data` unverified, for local tests and builds, and data is only read as data (I-run''). Leftover: the App or a branch workflow can put an unattested tree into a local preflight. | None. |
| Gate (G) | Rule 3 (I-prov on `D`); defence in depth for rule 1 (person merge and review) | None. |
| Push job (J2) | It is the only holder of `attestations: write`; fast-forward only (R-D) | None. |
| Cutover script (D3) | Step 4: `protect-main` must print OK, which now needs Brian's `-Apps` answer from the same session | D3 takes `-Apps` / `--apps` and passes it to `protect-main`. Brian's card gains the installations step. |
| Rollback | It leaves I-person on purpose: R1' plus R2 on reopen the bot path, which is why it refuses while `MORNING_NOTE_SEND` or `MAIN_PR_BASELINE` is set. The App changes nothing here. | None. |
| V1'' and `MAIN_PR_BASELINE` | `protect-main` prints OK just before the baseline is set | Brian's re-run passes `-Apps`. |

**Supersedes.**
- In decision 6, "reports NOT OK ... if anything besides gn0sh can write: ... an installed App with contents write"
  now reads: NOT OK unless all of these hold:
  - R2 is off.
  - No collaborator or pending invitation other than gn0sh has write, and no deploy key has write.
  - Installed Apps are `none`, or `claude` alone without Administration write (Brian's hand check).
  - Each bypass list equals its file.
- The "exactly two writers" premise (decision 6, and the note's row R1 "Why 2") is replaced by I-person rules 1-3.
- PR #54 F1's "NOT OK if any besides gn0sh" is replaced the same way. Security review S1 re-confirms this amendment,
  because one App approver is new since F1.

## Amendment 2026-11-18 (c): no phase 0 on `main` after the cutover
Trigger: the B2/B3 review finding main-protect/phase0-attest. Between the cutover merge and `MAIN_PR_BASELINE`, J2
would sign attestations that the gate accepts forever, on a `main` whose history the gate never checked. The fix at
fb94f5be (branch `claude/data-off-main-b23`) makes `push` need `needs.gate.outputs.verified == 'true'`. So in phase 0
no run pushes, and no scheduled or `collect=true` run deploys either (deploy needs push to succeed). That breaks D3
step 8, which expects the first run after the cutover to push and attest. B4 proposed running the tripwire in
report-only mode during phase 0.

**Ruling.**
1. **The cutover PR sets `MAIN_PR_BASELINE`.** Its value is the sha of `main` that the seed is cut from. That sha
   is also the PR's base, and the reviewers check it with the runbook 4.7.1 window listing, pasted into the PR. So
   the cutover squash commit is the first commit after the baseline, and the gate checks it like any other: merged by
   a person (`merge-reviewed`, a gn0sh bypass) and reviewed at its head (the COMMENT review that `merge-reviewed`
   posts). The new workflow never runs on `main` without a baseline. There is no separate baseline PR, and Brian
   has no extra step: his C1 "yes" covers the baseline, and the card says so (hard stop 1).
2. **Phase 0 on `main` is a refusal.** On `main`, with the new workflow, an empty `MAIN_PR_BASELINE` makes the gate
   refuse. Nothing is built, pushed, attested, deployed or sent, and `gate-failed` opens its issue. This takes the
   main-protect L-1 fix (an empty baseline on `main` is a refusal) out of the later baseline PR and puts it in the
   cutover PR. A PR that resets the baseline to `""` now freezes the pipeline instead of silently reopening phase 0.
   Runs on other branches stay as they are: `verified=false`, and push, deploy and note are `main` only.
3. **Belt and braces.** `push` keeps the `verified == 'true'` condition from fb94f5be. `deploy` gains the same
   condition, so no deploy ever comes from history the gate hasn't checked, whatever the gate's output path.
4. **The tripwire has one mode, and it always holds.** There is no report-only mode. A switch that runs I-pub without
   holding the deploy is a bypass, like `allow_shrink` (F7), and it has no use once phase 0 can't run on `main`. On a
   branch, the tripwire runs the same code, and `held` doesn't matter because deploy is `main` only.
5. **What the site shows.** It stays on the last deploy from before the cutover. It changes when D3 step 7 deploys
   the seed, after the merge and in the same session. If the session stops between the merge and step 7, the
   workflow is still disabled (step 2) and the site stays on that last deploy. That is fine for a day, and the C1
   card asks Brian to finish or roll back the same day.
6. **V1'' no longer gates the baseline.** It still gates `MORNING_NOTE_SEND`. Setting the baseline earlier is
   stricter, not weaker. If the V1'' probe gets a bot merge into `main` (FAIL), the gate refuses every later run
   until a person moves the baseline past that commit. Under the old order, the later baseline PR would have had to
   catch such a merge by hand (L-3). Drift rule: `protect-main` prints OK in step 4, just before the merge sets the
   baseline, and a plain `--check` must print OK just after it. Together these meet "re-run before
   `MAIN_PR_BASELINE` is set".
7. **Rollback.** After the cutover merge, the baseline is non-empty on `main` by design, so `--rollback` can't refuse
   on that at entry. It still refuses at entry while `MORNING_NOTE_SEND` is set, or while a `MAIN_PR_BASELINE`
   repository variable exists (a refused or failed read counts as set). The workflow-value check moves to the point
   just before R2 goes on: once restore PR R has merged, `main`'s workflow (the one from before the cutover) must hold
   exactly one empty `MAIN_PR_BASELINE`, or the rollback stops with R2 still off. F4 holds, because R2 never comes
   on while `main` carries a baseline. Before the cutover merge, the entry check is the same as today.

**Invariants.** I-person: unchanged. The baseline reaches `main` only inside a PR that gn0sh merges by bypass under
R1''. Amendment (b) rule 3 gets stronger: the gate checks the history behind every attestation J2 signs, from
the first one. Fail closed: an empty baseline, a missing or wrong window start, or `main` having moved off the
pinned baseline all stop the run before anything changes (D3 step 1) or refuse the gate.

**Alternatives considered.**
- *A separate one-line baseline PR right after the merge, in the same session* (the manager's example). This still
  leaves a phase-0 window between two merges. The PR can't be prepared or reviewed in advance, because its value is
  the squash sha. It also needs a second bypass merge and a review generated by the script. Rejected: it costs
  more for a weaker result.
- *Phase 0 with the tripwire in report-only mode* (the B4 proposal). Every phase-0 run would collect, build and throw
  away its result, and the mode flag would be a lasting bypass of I-pub. Rejected (item 4).
- *Revert fb94f5be and let phase 0 push and attest.* This reopens phase0-attest. Rejected.

**Cost.** The cutover PR pins one more value, and each refresh of the seed pin also refreshes the baseline pin (same
day, after the day's run, as for the seed digest). The window start (`R2 first on`, or the first `Main before the
ruleset` sha) isn't recorded in `docs/platform-facts.md` yet. The manager supplies it from the ledger before the
cutover PR's review. If it's unknown, the architect picks the window (runbook 4.7.1). Until then, D3 step 1 refuses.

**Note 2026-11-20 (baseline moved).** PR #66 (design fixes) was squash-merged into `main` by hand as
`eef6ed0643f42fd104ca2e0a463650066558e20f` on 2026-11-20 03:46 UTC, without `scripts/merge-reviewed` and with no
person's review of its head, so the gate refused every run after it (correctly). A revert cannot help (eef6ed0 stays on
the first-parent line) and a review posted now fails `submitted_at <= merged_at`. `MAIN_PR_BASELINE` therefore moves from
1922fda3 to eef6ed06, after code review and security review of eef6ed0 (docs/reviews/pr66-merged-*.md) checked that it
touches no trust root and that `1922fda3..eef6ed06` is exactly [8d69778, eef6ed0]. Past the new baseline the gate no
longer re-checks the cutover squash 8d69778 (item 1); its facts were verified by hand (PR #65 merged by gn0sh, a person's
review at head 20c3b972 before the merge). From now on every merge into `main` goes through `scripts/merge-reviewed`.

## Amendment 2026-11-19 (d): S1

Source: security review S1 of the data-off-main milestone (`reviews/s1-security-data-off-main-5fb948f2.md`, OK with
follow-ups, no critical or high findings). Four findings change this ADR.

**S1-1 (`main-protect/approval-margin`): R1'' requires the ruleset maximum number of approvals.** R1'' now sets
`required_approving_review_count` to the ruleset maximum (10, or the highest value the API accepts). It was 2.
With 2, I-person rule 1 rested on the unenforced comment-only rule for gn0sh and on R2 being off: gn0sh (or the
session acting as gn0sh) plus `claude[bot]` could meet the count, and `claude[bot]` could then merge with no bypass.
With the maximum, rule 1 rests on neither. Only a bypass merge by gn0sh can meet it, and every legitimate merge is
already a gn0sh bypass, so nothing real is lost. Wherever this ADR and amendments (b) and (c) say "approvals 2" or
"any 2 approvals include gn0sh's", read "the ruleset maximum" (reworded in place on 2026-11-19, N2); `protect-main` (both twins) and its tests check
that value. Margin hardening, not a break of I-person today.

**S1-2 (`golive-switch/app-scope-hand-check`): the App's own identity is used, and it has Actions write.**
Amendment (b)'s inference that "the App's own installation identity is unused" is wrong. Claude Tag authors its PRs
as `claude[bot]`. The App's Actions write is a new residual: it can dispatch, re-run, enable and disable workflows
and delete runs, logs and artifacts. Consequences: denial of service, deleted logs, and re-runs of older
post-baseline runs. It does not break I-person (it can't mint accepted data outside J2 on `main`, can't merge, and
can't edit R1'' or R2 without Administration). Accepted. The hand check (ii) now also covers Variables, Secrets and
Environments: each must be none or Read, never Read and write, and any other answer is NOT OK. Variables write
would let it set `MORNING_NOTE_SEND` or `RECORDS_DEPLOY_ENABLED`, which are hard-stop switches.

**S1-3 (`data-off-main/rollback-unverified-data`): the rollback verifies I-prov on the restore source.** The open
path no longer builds PR R from `records-data`'s head unchecked. It refuses unless that head passes the attestation
check or is the pinned seed; otherwise the operator gives `--data-from <sha>`, an attested ancestor on
`records-data`. `--merge` requires R's `data/` listing to equal that verified tree. N1 (re-confirm at f4d88591,
`rollback-seedpin-untrusted`): the seed pin `--merge` trusts is read from `main`, R must be one commit whose parent is
on `main`'s first-parent line, and `--merge` takes `--cutover-merge <sha>` so R's workflow and CODEOWNERS must equal
those before the cutover merge. Every trust root the scripts read: `docs/architecture/data-off-main-trust-roots.md`.

**S1-4 (`i-pub/t5-same-job`): accepted for the cutover; follow-up recorded.** See the reworded consequence (a). Follow-up
for `backend-engineer`: a verify job on a fresh runner that downloads only the data artifact, rechecks its shape,
rebuilds with sitegen, runs the tripwire, writes `build-info.json` and uploads the Pages artifact; deploy needs
only that job. Check first that sitegen builds without `data/store`.

Findings S1-5 to S1-8 (seed recheck before the merge, Pages `build_type`, listing the workflows folder, seed data
from pre-cutover bot merges) are script hardening or accepted and need no change to this ADR's decisions.
