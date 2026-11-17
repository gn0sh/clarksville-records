# main-protect invariant (loop rule re-plan, 2026-11-17)
software-architect, 2026-11-17. Replaces the 2026-11-11 version (devops-engineer; git history keeps it). The
`main-protect/` family has been hit twice since the no-bypass ruleset: M1 (the Actions bypass let a workflow on any
branch push `main`) and the bot-merge path that replaced it (security V1, M-A, L-A, L-C, L-D, L-E). Decision record:
ADR 0009. Tasks: `docs/tasks/morning-note.md` T4.10.

## The invariant
**I-main (what reaches `main`).** After `MAIN_PR_BASELINE`, every commit on `main`'s first-parent line that changes
anything outside `data/` is the merge or squash commit of exactly one pull request into `main` that a person merged
(`merged_by.type == "User"`), and that PR's head at merge (`head.sha`) carries a person's review of that exact commit
(`user.type == "User"`, `author_association` `OWNER` or `COLLABORATOR` (M-1: the repo is public, so any account can
post a review), `commit_id == head.sha`, state `COMMENTED` or `APPROVED`, submitted no later than `merged_at`).
Every other first-parent commit changes only `data/`, which holds only regular files (mode 100644) named `*.json`,
`*.yml` or `changes.jsonl` (the gate checks this shape on every run on `main`, phase 0 included) and is read as data,
never executed. Who made a data-only commit is not checked (residual M-2 below).

**I-run (what may run with the credentials).** A job that holds the deploy credentials (`pages: write` and
`id-token: write` in environment `github-pages`) or `BUTTONDOWN_API_KEY` (environment `morning-note`), and every job
whose output such a job publishes or sends, runs only the workflow and code of one commit `S = github.sha`, fixed for
the whole run, which the `gate` job has checked against I-main on `main`.

**The one line the gate cannot hold.** The gate runs inside the workflow it judges, so a bad workflow on `main` skips
it. The workflow file at `S` meets I-main only because (a) the ruleset makes a pull request the only way into `main`,
and (b) GitHub refuses `GITHUB_TOKEN` any change under `.github/workflows/`, by push **and by merging a PR** (V1). (b)
is unverified for merges: the V1 probe (below) must pass before `MAIN_PR_BASELINE` or `MORNING_NOTE_SEND` is set.
For the same reason the gate's check is inline in the workflow file, never a script in the repository: only
`.github/workflows/` is out of a bot merge's reach, and a gate that runs `scripts/` code could be emptied by the very
merge it must catch.

Actors: a person with write (Brian, or the team acting as him): trusted, but a self-merge with 0 approvals passes
(residual L3). A workflow on any branch (its `GITHUB_TOKEN` can push branches and, with the Actions setting on, open
and merge PRs): must never produce a code commit that I-main accepts. Untrusted PDFs (parsed in `update`). Outsiders:
no write.

## Every consumer, and how it upholds the invariant
| # | Consumer | How it upholds it |
|---|---|---|
| G | `gate` job (new, T4.10.2) | Runs first; `contents: read`, `pull-requests: read`, no secrets, no persisted token. Checks data/'s shape and I-main for `S` (design below), outputs `sha` (= `S`) and `verified`. Fails closed on any API error, shallow history, bad baseline, or an empty list of commits to check. |
| J1 | `update` job | `needs: gate`; checks out exactly `needs.gate.outputs.sha`, not `ref: main` (L-A). `contents: read`, token not persisted, `issues: write` only. Its build and plan come from the checked commit, so what `deploy` publishes and `note` sends was built by checked code. |
| J2 | `push` job | `needs: [gate, update]`; commits on `update.sha` (= `S`). Local check: one commit on top of main, `data/` only. Server check: the PR's file list equals the local list exactly and is not empty (L-C); every name under `data/`; merge pinned to the checked `sha`, squash. Its merges are the bot merges I-main expects (data only); a test keeps `contents: write` and `pull-requests: write` to this job alone across every workflow (M-2). |
| J3 | `deploy` job | `needs: [gate, update, push]`, plus `needs.gate.result == 'success'` in its `if:`. Publishes only this run's artifact from J1. Environment `github-pages`, main only (E1). |
| J4 | `note` job | `needs: [gate, update, deploy]`, `if:` adds `needs.gate.outputs.verified == 'true'`; checks out `needs.gate.outputs.sha`. Its own PR-check step is removed (one copy, in the gate); the stale-rerun step stays. Internals: table "Inside the note job" below. |
| J5 | `note-failed`, `gate-failed` (new), push's failure step | `issues: write` only, fixed text, no checkout, run no repo code. |
| W1 | The workflow file at `S` | Ruleset (R1) + V1. The gate also refuses a bot-merged `.github/` commit already in the history, so a later good workflow stops until a person moves the baseline past it. |
| W2 | Workflows on any other branch | Can open and merge a PR to main (R2): any code commit that makes is refused by G on every later run (fail closed, `gate-failed` issue); a data-only one is not detected, only its shape is checked (residual M-2). Cannot change a workflow on main (V1). Cannot enter `github-pages` or `morning-note` (main-only deployment branches, E1, E2). |
| E1 | Environment `github-pages` | Deployment branches **main only**. `gh-pages` is still allowed today (status: "optional hygiene"); under I-run it is not optional: a workflow a person pushes to `gh-pages` (the ruleset covers main only) would get `pages: write` outside the gate. Removed in T4.10.5. |
| E2 | Environment `morning-note` | Main only (runbook 2.0). Required reviewer optional (runbook 5.0 A): the only control against L3. |
| R1 | Main ruleset, `scripts/main-ruleset.json` | `deletion`, `non_fast_forward`, `pull_request` with 0 approvals, no bypass. Approvals stay 0 (L-E): with R2 on, a workflow's approval would count toward any number above 0. The gate counts no approvals, only a person's merge and a person's review at head, so a bot approval never satisfies it. |
| R2 | Setting "Allow GitHub Actions to create and approve pull requests" | On, for J2. It is what lets a workflow on any branch merge to main (W2), which is why G exists. |
| R3 | Repo merge settings | `allow_auto_merge: false` (L-D: auto-merge merges whatever head the branch has later). Squash and merge commits allowed; a rebase merge of more than one commit leaves commits whose sha is no PR's `merge_commit_sha`, so G refuses it: merge with squash or a merge commit (S2 uses squash). |
| S1 | `scripts/protect-main.sh`, `.ps1` | Create or update R1, turn on R2; their OK check also asserts approvals 0 and `allow_auto_merge` false, and says NOT OK otherwise. |
| S2 | `scripts/merge-reviewed.sh`, `.ps1` (new) | The only way a person merges a non-data PR: `merge-reviewed <pr> <reviewed-sha>` posts a COMMENT review with `commit_id=<reviewed-sha>` (body: the review report links), merges with `sha=<reviewed-sha>` (refused if the head moved: L-D), then deletes the head branch. |
| B | `MAIN_PR_BASELINE` | Lives in the gate step's `env` only (moved from J4). Empty = phase 0: gate outputs `verified=false` and passes, so J1-J3 run as they do today and J4 never runs. Set by a person's PR (T4.10.8) after the V1 probe passes; from then the test accepts only a sha. Moved later only by a reviewed PR after a person read every commit it skips. |
| D | `data/` | Validated by J2 (types, size, no symlinks); G's shape check refuses, on every run on main (phase 0 included), any `git ls-tree -r` entry under `data/` that is not mode 100644 named `*.json`, `*.yml` or `changes.jsonl` (no symlink, submodule or executable; tested, and on a `blob:none` clone it reads no blob). Who merged a data-only commit is not checked (residual M-2). Read with `json` and `yaml.safe_load` only (grep, 2026-11-17: `sitegen/`, `collector/`); not read by J4. |
| K | Caches (`actions/cache` in J1) | Fetched documents and OCR: data, never executed; GitHub scopes them by branch (a branch run cannot write main's cache). |
| P | Runbook `docs/ops/morning-note.md` | 2.0 (protect main; new 2.0.3 merge procedure S2; new 2.0.4 V1 probe), 4.6, 4.7 (baseline: now T4.10.8, check only), 5.0 A, "Rules for manual runs and re-runs", "When the note job fails" plus new "When the gate fails". Each says what this table says, no stronger. |
| T | Tests, `tests/test_workflow_lock.py` | `PR_CASES` run against the gate step, plus the new review cases (M-1: outsider and contributor refused, collaborator and owner accepted); the data/ shape cases (M-2: symlink, submodule, 100755, other names refused; also on a `blob:none` clone with no blob fetched); only J2 grants `contents: write` or `pull-requests: write` in any workflow; `needs`, `ref` and `if:` of J1-J4; J2's L-C cases; R1 json (approvals 0, no bypass); G's permissions exactly the two reads; G runs no file from the checkout (allowlist lint, as `NOTE_STEP_COMMANDS`); baseline is "" or a sha (sha only after T4.10.8). |

## The gate job
Placed first in `jobs:`; `timeout-minutes: 10`; outputs `sha`, `verified`. Steps: checkout `ref: ${{ github.sha }}`,
`persist-credentials: false`; one inline `run:` step with `GH_TOKEN`, `SHA: ${{ github.sha }}`,
`REF: ${{ github.ref }}`, `MAIN_PR_BASELINE` in `env:`, `set -euo pipefail`:
1. `git rev-parse HEAD` must equal `$SHA`.
2. `REF` is not `refs/heads/main`: output `sha=$SHA`, `verified=false`, stop with success (push, deploy and note
   are main-only already; update builds the branch's own commit, which a branch run's own workflow could do anyway).
2a. Shape of `data/` (M-2, phase 0 too): every `git ls-tree -r -z HEAD -- data` entry is
   `100644 blob <sha>	data/...` named `*.json`, `*.yml` or `changes.jsonl`; anything else (symlink, submodule,
   executable, other name, `data` not a folder) or a failed read: fail. Tree objects only, no file contents.
3. Baseline empty: same outputs plus a `::warning::` (phase 0). Not 40 lowercase hex: fail.
4. As today's note step: full history (`--filter=blob:none`, unshallow), baseline on HEAD's first-parent line,
   `shas=$(git log --first-parent --format=%H "$base..HEAD" -- . ':(exclude)data/')`; empty: fail (vacuous pass).
5. For each sha: (a) exactly one PR from `commits/<sha>/pulls` with `merged_at`, base `main`,
   `merge_commit_sha == sha` (more than one: fail); (b) `merged_by.type == "User"`; (c) if the commit has two
   parents, the second is the PR's `head.sha`; (d) `gh api --paginate pulls/<n>/reviews` has a review with
   `user.type == "User"`, `author_association` `OWNER` or `COLLABORATOR`, `commit_id == head.sha`, state `COMMENTED` or `APPROVED`, `submitted_at <= merged_at`.
6. Output `sha=$SHA`, `verified=true`.

On main with a baseline, success implies `verified=true`, so J3 needs only `needs.gate.result == 'success'`. The
result depends only on `S` and immutable PR records (a review dismissed later makes a re-run fail: closed). Cost: 3
API calls per code commit since the baseline; move the baseline forward by reviewed PR if it grows past a few hundred.
`gate-failed` opens or comments on one "Daily update: main history check failed" issue (`--app github-actions`
lookup). Recovery: a person reads the refused commit; if it was meant, a PR (merged with S2) moves the baseline to it.

## V1 probe (one time, T4.10.1)
Preconditions: runbook 2.0.1 done (R1 active, R2 on) and one data PR merged by J2 (proves bot merges work, so a
refusal below means the workflow rule, not a general refusal). Run by devops with the owner's session.
1. A person pushes `probe/v1-target`: main plus one new file `.github/workflows/v1-canary.yml` (inert:
   `on: workflow_dispatch`, `permissions: {}`, one job with `if: false`).
2. A person pushes `probe/v1-runner`: main plus `.github/workflows/v1-probe.yml`, `on: push` to that branch only,
   `permissions: contents: write, pull-requests: write`. Its one step opens a PR `probe/v1-target` into `main`,
   posts nothing else, then tries `PUT pulls/<n>/merge` pinned to the head sha with `squash`, then `merge`, then
   `rebase`, then GraphQL `mergePullRequest` (`expectedHeadOid` = the head, `SQUASH`), printing each answer; it
   stops at the first merge that goes through.
3. Expected: all four refused, with a message naming the `workflows` permission (for example "refusing to allow a
   GitHub App to create or update workflow ... without `workflows` permission"); `main`'s sha unchanged
   (`git ls-remote origin main` before and after). A refusal for any other reason (not mergeable, ruleset) is
   inconclusive: fix and re-run. The verdict FAIL comes only from the probe PR reading `merged` (or the run's own
   merge answer) or `v1-canary.yml` being on `main`; `main` moving while the PR stays unmerged, or a failed read, is
   inconclusive and leaves R2 on (v1-probe/verdict-from-main-sha).
4. Same session, on the probe PR: post a COMMENT review as the PR's author with an explicit older `commit_id` and
   check the API returns that `commit_id` (S2 and gate 5(d) depend on it).
5. Clean up: close the PR unmerged, delete both probe branches (throwaway branches the team made), record the run
   link, the four messages and step 4's result in `docs/platform-facts.md` "Main protection".

If any merge goes through (V1 false): turn R2 off at once (`gh api -X PUT
repos/gn0sh/clarksville-records/actions/permissions/workflow -F can_approve_pull_request_reviews=false`; J2 then
fails and the site stops updating, which is the safe state); remove the inert canary by a person's PR; leave
`MAIN_PR_BASELINE` and `MORNING_NOTE_SEND` unset; the architect re-plans the data path (the leading candidate: data
leaves `main` for a branch the build reads, so no workflow needs to merge to main). **The probe gates
`MORNING_NOTE_SEND`:** runbook section 4 gets an item "V1 probe passed (link)" before item 7, and T4.10.8 depends on
it.

## Inside the note job (rows 3-15 and 18 of the 2026-11-11 version, still in force)
"Code" is anything the job executes or that can change what it executes. Everything the job loads is taken from
`S`'s git objects outside `data/`, staged outside the checkout and re-checked before each use; nothing is loaded from
`data/`, the repository root or the working folder.
| # | Consumer | Guard |
|---|---|---|
| 3 | Actions (`checkout`, `setup-python`, `download-artifact`) | Pinned by full commit sha (test `test_no_secrets_and_pinned_actions`); only these three are used (test). |
| 4 | Bash for `run:` steps | Default `bash -e {0}`; every Python or staging step starts `set -euo pipefail`; each step runs only allowlisted programs (test `NOTE_STEP_COMMANDS`, a lint, not a boundary). `GITHUB_ENV`/`GITHUB_PATH` written only by `setup-python` (pinned), the stage step (`NOTE_LIB`, `NOTE_LIB_SUM`) and "Validate the plan files" (`PLAN`). |
| 5 | Tools `git`, `gh`, `jq`, `find`, `sort`, `xargs`, `sha256sum` | From the runner image. Staging uses `git ls-tree`/`git cat-file blob` (no `.gitattributes` rule applies). |
| 6 | `sys.path` and imports | Every Python run is `python -I -S -X pycache_prefix="$pc" -c` with only `$NOTE_LIB/py` added (tested). |
| 7 | `sender/*.py` and the staged folder | Staged from `S`'s objects (top-level `sender/<name>.py` and `config/site.yml`, regular files only) into a new `NOTE_LIB`; its digest is re-checked before validate, dry run and deliver (tested). |
| 8 | Working folder | Never read by Python, never on `sys.path`. |
| 9 | `config/site.yml` | Read only as the staged `$NOTE_LIB/site.yml`, parsed by `sender/settings.py`; `api_base` pinned in code. |
| 10 | The plan artifact `morning-send` | Untrusted data from J1: downloaded after staging to `$RUNNER_TEMP`, layout and size checked, schema and links checked by `sender.deliver.check_plan`; never executed. |
| 12 | Environment secrets | `BUTTONDOWN_API_KEY`, `MORNING_NOTE_CANARY_IDS` only in the deliver step's env. The job's `GH_TOKEN` is no longer used (the PR check moved to G). |
| 13 | Repository variables | `MORNING_NOTE_SEND`, `RECORDS_DEPLOY_ENABLED` only switch jobs on; never put into `run:` by `${{ }}` (test). |
| 14 | Code-loading environment variables | `LD_PRELOAD`, `LD_LIBRARY_PATH`, `OPENSSL_CONF`, `OPENSSL_MODULES`, `SSL_CERT_FILE`, `SSL_CERT_DIR`, `BASH_ENV`, `PYTHONTZPATH`: set by nothing but `setup-python`'s `LD_LIBRARY_PATH`. |
| 15 | Packages and interpreter | No pip, no cache; `-S`; interpreter from the pinned `setup-python`. |
| 18 | Stale-rerun check | `sender/ config/site.yml .github/` must equal main's tip, so an older run's sender never meets today's plan. |

## Residual (people, not checks)
- L3: a person who merges their own code PR with 0 approvals and a COMMENT review passes. S2's review body links the
  team's review report; only the required reviewer on `morning-note` (E2) stops it before the key.
- A person who pushes a workflow that drops the gate, or a repo admin who changes R1, R2, R3, E1 or E2: outside any
  check in the repository. S1 re-verifies R1-R3 when run.
- M-2 (main-protect/bot-data-merge-unbound, accepted 2026-11-17): a workflow on any branch can still open and
  bot-merge a data-only PR, and the gate never checks who merged a commit that changes only `data/`. It cannot be
  bound to the daily run: no GitHub record links a PR or merge to the run that made it (branch name, body, message
  and author are all writable by any `GITHUB_TOKEN`), and a person with write can already merge a data-only PR by
  hand, which I-main deliberately does not check. The exposure is bounded: `data/` is untrusted input already (it
  comes from public PDFs), is read only with `json` and `yaml.safe_load`, and is rendered with autoescape; the gate's
  shape check (step 2a) keeps it to regular `*.json`, `*.yml` and `changes.jsonl` files; and a test keeps
  `contents: write` and `pull-requests: write` to J2 alone. Reopen if another workflow needs either permission, or if
  the note ever sends without the E2 reviewer.
- zip-slip-residual: a download that could write anywhere on the runner (toolcache, `GITHUB_ENV`) has better targets
  than `NOTE_LIB`; the defence is the pinned `download-artifact` (v4.3.0) and the plan coming only from this run's J1.
- Unverified GitHub behaviour, each failing closed if wrong except V1: V1 (probe step 3); an author's COMMENT review
  keeps the `commit_id` it was posted with (probe step 4); a merged PR's `head.sha` stays as merged (S2 deletes the
  head branch, so nothing can push it later).
