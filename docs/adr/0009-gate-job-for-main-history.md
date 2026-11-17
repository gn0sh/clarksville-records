# ADR 0009: A gate job checks main's history before any job that builds, deploys or sends

Status: proposed (software-architect, 2026-11-17), feature `morning-note` (T4.10). Invariant and consumers:
`docs/architecture/main-protect-invariant.md`.

## Context
The no-bypass ruleset moved the daily `data/` commit to a pull request the `push` job opens and merges with
`GITHUB_TOKEN`, which needs "Allow GitHub Actions to create and approve pull requests". With that setting any
workflow on any branch can merge a PR to main. Only the `note` job checked who merged each code commit; `update`
built and `deploy` published bot-merged `sitegen/` or `collector/` code unchecked (M-A), and `update` checked out
`main` at job time, not the run's commit (L-A). Workflow files are held only by GitHub refusing `GITHUB_TOKEN` a
workflow change (V1), unverified for merges.

## Decision
1. A first job, `gate` (`contents: read`, `pull-requests: read`), checks that every first-parent commit outside
   `data/` after `MAIN_PR_BASELINE` is exactly one PR's merge, merged by a User, with a User review at the PR's head
   sha; it outputs `sha` (= `github.sha`) and `verified`. `update` checks out that sha; `deploy` needs the gate's
   success; `note` needs `verified == 'true'`. One copy of the check, inline in the workflow file.
2. Every non-data PR is merged with `scripts/merge-reviewed` (COMMENT review pinned to the reviewed sha, merge pinned
   to it, head branch deleted). Auto-merge stays off; ruleset approvals stay 0.
3. A one-time V1 probe must pass before `MAIN_PR_BASELINE` or `MORNING_NOTE_SEND` is set.

## Alternatives considered
- **Keep the check in `note` only** (simplest): leaves M-A open for the public site. Rejected.
- **Copy the check into each job**: same strength, three copies to drift. Rejected for one gate whose outputs the
  others consume.
- **Data off `main`** (a `data` branch or repo the build reads; no workflow merges to main, the setting goes off):
  removes the bot-merge path entirely, so V1 and the gate's bot cases stop mattering. Strongest; it changes the
  build, the push job, the collector's committed-state reads and every test that assumes `data/` on main. Held as the
  fallback if V1 is false. Recommend a short Brain Trust if V1 fails, since it is costly to reverse.
- **A GitHub App or deploy key for the data commit**: a new credential (hard stop 5) and rulesets cannot limit a
  bypass to `data/`. Rejected.
- **Required reviewer on both environments**: strong, but Brian approves every morning (runbook 5.0 A). Stays his call.

## Consequences
- A PR merged without the procedure stops the daily update and deploy (fail closed, one issue) until a person moves
  the baseline past it. Merging becomes one script call for the team.
- Until the baseline is set (phase 0) `update` and `deploy` run as today; that window should end the day the probe
  passes.
- `github-pages` must lose its `gh-pages` deployment branch.
- Data-only merges by any workflow stay unchecked by design (M-2, 2026-11-17: no GitHub record ties a merge to the run
  that made it); the gate checks data/'s shape instead (100644 `*.json`, `*.yml`, `changes.jsonl` only), and a test
  keeps `contents: write` and `pull-requests: write` to the push job alone.
