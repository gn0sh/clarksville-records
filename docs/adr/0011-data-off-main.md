# ADR 0011: Collector data moves off `main`; no workflow can merge into `main`

Status: proposed (software-architect, 2026-11-18), **gated on U3** (`docs/ops/u3-positive-control.md`). Supersedes
ADR 0010 decisions 1 (CODEOWNERS), 2 (ruleset R1') and 5 (the V1' probe). ADR 0010 decisions 3 (R2 on, now
interim), 4 (canary removal, done by #52) and 6 (the gate stands) remain. Analysis, invariant and every consumer:
`docs/architecture/v1-fail-2026-11-18.md`. Panel: `docs/reviews/brain-trust-data-off-main.md` (Fix First, 5-1).
Tasks: `docs/tasks/data-off-main.md`. Amended 2026-11-18 for the PR #54 security review
(`docs/reviews/pr54-security-review.md`, findings 1-8 and settings drift).
Amended again 2026-11-18 (writer set and the Claude GitHub App): see "Amendment 2026-11-18 (b)" at the end; it
supersedes decision 6's writer rule and finding F1's wording.

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
5. **Ruleset R1'' on `main`:** `required_approving_review_count: 2`, `dismiss_stale_reviews_on_push: true`,
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
   D3), with `protect-main` (R1'', R-D, R-T, R2 off) before the cutover merge (finding 5). After it, the V1'' probe (architecture note section 4) must pass before `MAIN_PR_BASELINE` or
   `MORNING_NOTE_SEND` is set.

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
- **Throwaway repository for U3:** needs Brian to create a repository and grant the team access to it, and it
  tests a different ruleset and token. Rejected in favour of the scripted live toggle.

## Consequences
- I-main becomes simpler (no data exception). I-run gains `D`, read once by the gate and attested.
- New residuals: (a) attested but wrong new facts from `main`'s own pipeline (a hostile PDF, T5) when they don't
  touch published facts. (b) Every merge is a bypass, so the bypass log stops being a signal; the gate's
  person-merge check and the rule-suite read in `merge-reviewed` replace it. (c) Brian is the sole admin, so `main`
  freezes if the team's bypass stops working. (d) Replay (finding 7): a write-token workflow on any branch can
  push an earlier attested tree to `records-data`. The gate accepts it, because a person's rollback needs exactly
  that. I-pub holds the deploy if it drops or changes a published fact; an old tree that differs only in facts not
  yet live deploys. Accepted: the data is still `main`'s own pipeline output. (e) Settings drift: R1'' holds only
  while the settings in decision 6 hold, and only a run of `protect-main` from Brian's PC can see them all.
- The push job gains `id-token: write` and `attestations: write`, and loses `pull-requests: write`. It is the only
  job with `attestations: write`; `deploy` keeps its own `id-token: write`. The gate gains `attestations: read`.
- **U3-0 = no** (finding 8): the team's cloud session got a proxy 403 on the no-op ruleset PUT at 17:37 UTC
  2026-11-18 (read-back unchanged). So every ruleset, R2, environment and R-D write is Brian's, run from his PC:
  U3, the cutover's settings steps and any rollback. Those writes are blocked today by the session proxy's
  policy, not by the token's permissions; if that changes, the team-token anchor returns. Re-check U3-0 whenever
  the proxy allowlist changes.
- Local runs and preflight need `scripts/fetch-data`. The multi-city template inherits the two-branch setup through
  `protect-main`.
- Cost: about 3-4 engineer days plus security review. Brian: one U3 session, then one cutover session.
- Reversal: `scripts/cutover-data-off-main --rollback` refuses while `MORNING_NOTE_SEND` or `MAIN_PR_BASELINE` is
  set (finding 4: R2 on reopens the bot path), then re-applies R1' json, restores `data/` on `main` by a
  reviewed PR from `records-data`'s head, and turns R2 on. The `records-data` branch is kept.

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
1. **At most one of them can give an approval that counts toward R1'''s 2.** So any 2 counted approvals include
   gn0sh's.
2. **None of them is on a bypass list** of R1'', R-D or R-T, and none can write a ruleset or R2 (no Administration
   write).
3. **None of them can store an attestation the gate accepts.** Only J2, running `main`'s `daily-update.yml` at
   `refs/heads/main` (decision 3), can, and that code reached `main` under 1 and 2.

Team rule that goes with it: gn0sh posts COMMENT reviews only, never APPROVE (`merge-reviewed` already posts COMMENT).
A gn0sh APPROVE on a PR that gn0sh didn't author is the one act that lets a second identity merge without a bypass.

**Checked against each setting** (judgment, high confidence; that App approvals count is assumed, the worst case):
- **R1''** (2 approvals, the author can't approve, last-push approval, stale approvals dismissed, admin-role bypass in
  `pull_request` mode). With R2 off, the identities that can approve are gn0sh and at most the `claude` App. A PR
  authored or last pushed by gn0sh gets at most 1 (the App), so only a bypass merges it, and only gn0sh holds the
  admin role. Any other PR (an outside fork, the App's own, a Dependabot PR) reaches 2 only with gn0sh's approval.
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
- R1'': it can push branches, open PRs, give one approval if it holds pull-requests write, and merge a PR that
  already has gn0sh's approval plus its own. It can't reach 2 approvals without gn0sh, approve its own last push,
  bypass (it isn't on the list and holds no role), or push to `main`.
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
  identity is unused. The rules above still plan for it to act.

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
| `protect-main` checks (S1) | Rules 1-2: approvals 2, last-push approval, dismiss stale; R2 off; collaborators and invitations with write: gn0sh only; no deploy key with write; Apps `none` or `claude` (by hand), no Administration write; each bypass list equals its file; R-D, R-T, environment policies of type `branch` | Logic of 01dc4d13 stands. The comments in both scripts carry the wrong reason and need the wording "any 2 approvals include gn0sh's". |
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
