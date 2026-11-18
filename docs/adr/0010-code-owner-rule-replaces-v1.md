# ADR 0010: A code-owner rule on main, not V1, keeps workflows from changing main

Status: proposed (software-architect, 2026-11-18), feature `morning-note` (T4.11). Amends ADR 0009 (decision 3 and
the V1 premise; the gate itself stands). Invariant, threat list and consumers: `docs/architecture/main-protect-invariant.md`
("V1 is false"). Facts: `docs/platform-facts.md` "Main protection".

## Context
ADR 0009's gate runs inside the workflow it judges, so it relied on V1: GitHub refuses `GITHUB_TOKEN` any change under
`.github/workflows/`, by merge as well as by push. The V1 probe (2026-11-18 08:50 UTC, run 44270476748) showed V1 is
**false**: the runner's first try, a REST squash merge pinned to the head, merged probe PR #40 (it adds
`.github/workflows/v1-canary.yml`); `merged_by` github-actions[bot], `main` 551a483 -> 3ef440a. The script turned
"Allow GitHub Actions to create and approve pull requests" (R2) off, so the daily `push` job can no longer open its
data PR: data stops saving, and `deploy` (it needs `push` to succeed) stops refreshing the site. GitHub Actions is on.
The canary on `main` is inert (`workflow_dispatch`, `permissions: {}`, job `if: false`).

Threat assessment (full list T1-T8 in the invariant): a write-token job is the only thing that can merge, and every
workflow on all 95 branches triggers only on `schedule` (runs on `main` only) or `workflow_dispatch` (needs write);
fork PRs get a read-only token. The only write-token code that runs unattended is the `push` job, which merges only
the PR it opened, from its own branch, pinned to its head, every file under `data/` (L-C). So no one without write
access can use V1-false today, and **turning Actions off is not needed**; the runbook's FAIL containment over-reached.
V1-false widens what a write-token workflow a writer pushes can do (open and merge a workflow change into `main`,
dropping the gate), which is the line the morning note's key depends on.

## Decision
1. **`.github/CODEOWNERS`**: `* @gn0sh`, then `/data/` with no owner (GitHub: a pattern with no owners leaves those
   files unowned). Every path outside `data/` has a code owner.
2. **Ruleset R1'** (`scripts/main-ruleset.json`, written by `scripts/protect-main`): the `pull_request` rule gets
   `require_code_owner_review: true`; required approvals stay **0** (L-E); `allowed_merge_methods: ["squash"]`;
   bypass list: **Repository admin role, mode "pull request"** (admins may merge a PR without its requirements; nobody
   may push `main`). `deletion` and `non_fast_forward` unchanged; other parameters kept as GitHub returns them.
   Effect: a PR that changes anything outside `data/` needs an approving review by gn0sh, which nobody gives (he
   authors the PRs and cannot approve his own; `GITHUB_TOKEN` is no code owner and holds no admin role), so it merges
   only by an admin's bypass merge, i.e. by a person (`merged_by.type == "User"`). A PR that changes only `data/` has
   no owned file and needs nothing, so the `push` job merges it as today. This is V1' and replaces V1.
3. **R2 back on now**, before R1' (Brian, one command): with R2 off the data stops; with it on, the exposure is the
   accepted 2026-11-17 state without V1, and only a writer can create a workflow that uses it (T7). The morning note
   stays off (`MAIN_PR_BASELINE`, `MORNING_NOTE_SEND` unset) until 5.
4. **Remove the canary** by a person's merge-reviewed PR (`claude/remove-v1-canary`); the probe scripts refuse to run
   until R1' is on (a re-run today would merge the canary again: R2 off does not stop merging).
5. **V1' probe**, the same probe re-run after R1' with a new PASS: all four bot merges refused with a message naming
   the ruleset or code-owner review, `main` unchanged; plus two positive controls: the next data PR merges by
   github-actions (U2) and the next `merge-reviewed` merge goes through by bypass (U3). PASS gates the baseline
   (T4.10.8) and `MORNING_NOTE_SEND`. The baseline window check lists 3ef440a (PR #40) as its one known Bot merge.
6. The gate (ADR 0009) is unchanged and stays as the I-main check and defence in depth.

## Alternatives considered
- **L-C plus the gate only** (today's design minus V1; also a gate that accepts "merge-reviewed or data-only squash by
  github-actions"): restores data saving, but the gate cannot hold its own file: a bot merge that rewrites
  `daily-update.yml` removes the check before it runs. Kept as a layer, rejected as the guard.
- **Required status check**: the data PR, opened by `GITHUB_TOKEN`, starts no workflow, so the `push` job would have
  to post the status itself; any workflow on any branch can post the same context under the same GitHub Actions app,
  so it is forgeable by exactly the actor it guards against. Rejected.
- **Fine-grained token for the push job**: a new secret (hard stop 5, Brian); it sits where any workflow a writer
  pushes can read it; whether a token without the Workflows permission is refused a *merge* is the same untested
  question V1 just failed; and its merges show `merged_by` User, which blinds the gate. Rejected.
- **Data off `main`** (a `data` branch the build reads; R2 off for good; approvals 1 + admin bypass on `main`):
  structurally strongest, no bot ever merges into `main`. Cost: the build, collector, push job, gate's I-data,
  deploy and every test that reads `data/` on `main` change, and the run must pin two commits; several days, hard
  to reverse. Fallback if V1' fails; convene a Brain Trust first then.
- **Push ruleset restricting `.github/` paths**: GitHub offers push rulesets for private and internal repositories
  (judgment, medium confidence: from memory of GitHub's docs, not checked); this repo is public. Not available.
- **Turn Actions off until a full re-design**: stops the live site's data; buys nothing against T1-T8. Rejected.

## Consequences
- Cost: one 3-line file, one json change, the two `protect-main` scripts' checks, the probe's verdict, tests and
  runbook text: about one devops day plus security review. Brian: three commands (R2 on now; `protect-main` after the
  PR; the V1' probe).
- Every non-data merge is an admin bypass (GitHub logs it in rule insights). L3 (a writer self-merges) is unchanged.
- A bot can still merge into unprotected branches (V1 false, so workflows too) and start them by `workflow_dispatch`
  (GitHub lets `GITHUB_TOKEN` dispatch): such a run reaches no credential only while `github-pages` and
  `morning-note` deploy from `main` alone. T4.10.5 is a precondition of the baseline, not hygiene.
- Reversible in minutes: re-apply the 2026-11-17 ruleset json, delete CODEOWNERS by PR.
- Unverified, each checked before the note can send: U1 `require_code_owner_review` binds with 0 required approvals
  (V1' probe; if not, FAIL path); U2 an unowned `data/` path needs no review (next data PR; if not, the push job fails
  loudly, revert the ruleset); U3 the admin bypass lets `merge-reviewed`'s REST merge through (if not, Brian clicks
  Merge with "bypass rules" after the script posted its review; the gate is satisfied either way); U4 the owner of a
  personal repository holds the admin role for the bypass (S1 run shows it).
