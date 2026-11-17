# main-protect invariant (loop rule re-plan, 2026-11-17)
software-architect, 2026-11-17. Replaces the 2026-11-11 version (devops-engineer; git history keeps it). The
`main-protect/` family has been hit twice since the no-bypass ruleset: M1 (the Actions bypass let a workflow on any
branch push `main`) and the bot-merge path that replaced it (security V1, M-A, L-A, L-C, L-D, L-E). Decision record:
ADR 0009. Tasks: `docs/tasks/morning-note.md` T4.10. Third hit (security S-1, L-a, L-b at 6e3c019): the data/ shape
check failed open on non-UTF-8 names; the shape is restated below as I-data, with every consumer.

## The invariant
**I-main (what reaches `main`).** After `MAIN_PR_BASELINE`, every commit on `main`'s first-parent line that changes
anything outside `data/` is the merge or squash commit of exactly one pull request into `main` that a person merged
(`merged_by.type == "User"`), and that PR's head at merge (`head.sha`) carries a person's review of that exact commit
(`user.type == "User"`, `author_association` `OWNER` or `COLLABORATOR` (M-1: the repo is public, so any account can
post a review), `commit_id == head.sha`, state `COMMENTED` or `APPROVED`, submitted no later than `merged_at`).
Every other first-parent commit changes only `data/`, whose tree meets I-data (below; the gate checks it on every run
on `main`, phase 0 included) and which is read as data, never executed. Who made a data-only commit is not checked
(residual M-2 below).

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

## I-data: the shape of `data/` (restated 2026-11-17 after S-1, L-a)
**I-data.** In every commit the gate passes on `main`: `HEAD:data` is a tree; `git ls-tree -r -z HEAD -- data` lists
at least one entry; and every entry, compared **as bytes**, matches the one shape literal `SHAPE`
(ERE, matched whole):
`^100644 blob [0-9a-f]{40}<TAB>data/([A-Za-z0-9_][A-Za-z0-9._-]*/)*([A-Za-z0-9_][A-Za-z0-9._-]*\.(json|yml)|changes\.jsonl)$`
So: regular non-executable files only (no symlink 120000, executable 100755, submodule 160000), names in printable
ASCII from that set only (no byte >= 0x80, no control character or newline, no path part starting with `.`), ending
`.json`, `.yml`, or exactly `changes.jsonl`. All 45 tracked entries fit today (checked at 506ae79). Sizes are not
in I-data (reading them needs blobs); J2 caps them at 50 MB.
**Rule for every check of it:** pass only by counting entries that match (`total == matched`, `total >= 1`), never by
finding no entry that fails; a tool that can withhold a line (grep under a UTF-8 locale prints "binary file
matches" and exits 0: S-1) must then fail, not pass.

| Consumer | What it checks or relies on |
|---|---|
| G, step 2a (inline; after the not-main exit, before the baseline) | (1) `git cat-file -t HEAD:data` prints `tree`, else refuse (absent, a symlink or file, failed read: L-a). (2) `git ls-tree -r -z HEAD -- data` into a file under `$RUNNER_TEMP` (a bash variable cannot hold NUL); failed read refuses. (3) `total` = NUL bytes in it; `matched` = `LC_ALL=C grep -zacE -- "$SHAPE"` on it (NUL-separated records, so a name with a newline stays one record and fails; exit 1 on zero matches is allowed only there, and `matched` must then be a number). Refuse unless `total >= 1` and `matched == total`. (4) On refusal print at most 20 failing records (`LC_ALL=C grep -zavE`), each on its own `::error::` line with every byte outside 0x20-0x7E replaced by `?` (`LC_ALL=C tr -c '\040-\176\000' '?'`, then NUL to newline); never a raw name. |
| J2, push job | Before `git add` (kept): no symlink or special file, 50 MB cap; new: the artifact holds at least one file (otherwise the merge empties `data/` and G refuses every later run). After the rebase, on the commit it is about to push: G's checks (1)-(4) with the same `SHAPE`, which also catches an executable bit that `cp -a` carried over. The `case` name allowlist may stay as a first filter but is no longer the check. |
| Tests | `test_tracked_data_files_fit_the_allowlist`: reads `SHAPE` from the gate step, lists `git ls-tree -r -z HEAD -- data` as bytes (`text=False`), asserts entries non-empty and every entry `re.fullmatch`es (bytes); a test asserts G and J2 carry the identical `SHAPE` text. Gate and J2 cases: list in row T. |
| sitegen (J1; local builds) | Reads named files and `glob("*.json")` under `data/` with `json` and `yaml.safe_load`; `open` follows symlinks. Relies on G: J1 `needs: gate` and checks out exactly `S`, so on `main` no symlink or odd name reaches it. No own guard. |
| collector (J1) | Reads and rewrites `data/`; relies on G as sitegen does. Keeps its own refusal of a symlinked `data/<slug>` folder (`collector/rpc_export.py:278`) because it deletes files there. What it writes re-enters only through J2 and the next run's G. |
| sender (J4) | Does not read `data/`: loads only the staged `sender/`, `config/site.yml` and the plan artifact (rows 7-10). Nothing to do. |
| Branch runs, local runs | Outside I-data (G exits before 2a off `main`; such runs hold no deploy or send credential). |

A new reader that runs with a credential outside a gated `main` run, or that writes or deletes inside `data/`, must
refuse symlinks itself (`os.lstat`/`is_symlink`), as `rpc_export` does; a change to `SHAPE` changes G, J2 and the
test in one PR.

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
| W2 | Workflows on any other branch | Can open a PR to main (with R2 on) and, with `contents: write`, merge an open PR to main, including one a person opened (R2 does not govern merging): any code commit that makes is refused by G on every later run (fail closed, `gate-failed` issue); a data-only one is not detected, only its shape is checked (residual M-2). Cannot change a workflow on main (V1). Cannot enter `github-pages` or `morning-note` (main-only deployment branches, E1, E2). |
| E1 | Environment `github-pages` | Deployment branches **main only**. `gh-pages` is still allowed today (status: "optional hygiene"); under I-run it is not optional: a workflow a person pushes to `gh-pages` (the ruleset covers main only) would get `pages: write` outside the gate. Removed in T4.10.5. |
| E2 | Environment `morning-note` | Main only (runbook 2.0). Required reviewer optional (runbook 5.0 A): the only control against L3. |
| R1 | Main ruleset, `scripts/main-ruleset.json` | `deletion`, `non_fast_forward`, `pull_request` with 0 approvals, no bypass. Approvals stay 0 (L-E): with R2 on, a workflow's approval would count toward any number above 0. The gate counts no approvals, only a person's merge and a person's review at head, so a bot approval never satisfies it. |
| R2 | Setting "Allow GitHub Actions to create and approve pull requests" | On, for J2. It governs creating and approving PRs with `GITHUB_TOKEN`, not merging (security main-protect/r2-does-not-gate-merge, needs verification): a workflow with `contents: write` can merge any open PR into main, R2 on or off. With R2 on it can also open its own, so W2 can put a commit on main by itself, which is why G exists. Turning R2 off stops J2 opening its data PR; it does not stop merges of PRs already open. |
| R3 | Repo merge settings | `allow_auto_merge: false` (L-D: auto-merge merges whatever head the branch has later). Squash and merge commits allowed; a rebase merge of more than one commit leaves commits whose sha is no PR's `merge_commit_sha`, so G refuses it: merge with squash or a merge commit (S2 uses squash). |
| S1 | `scripts/protect-main.sh`, `.ps1` | Create or update R1, then read R2 and `main`'s sha, then turn on R2 (in that order since L-b), printing `R2 was off; main was <sha>` or `R2 already on`; their OK check also asserts approvals 0 and `allow_auto_merge` false, and says NOT OK otherwise. |
| S2 | `scripts/merge-reviewed.sh`, `.ps1` (new) | The only way a person merges a non-data PR: `merge-reviewed <pr> <reviewed-sha>` posts a COMMENT review with `commit_id=<reviewed-sha>` (body: the review report links), merges with `sha=<reviewed-sha>` (refused if the head moved: L-D), then deletes the head branch. |
| B | `MAIN_PR_BASELINE` | Lives in the gate step's `env` only (moved from J4). Empty = phase 0: gate outputs `verified=false` and passes, so J1-J3 run as they do today and J4 never runs. Set by a person's PR (T4.10.8) after the V1 probe passes; from then the test accepts only a sha. Before it is set, runbook 4.7.1 checks the window from the R2 switch-on (section "Baseline window check"). Moved later only by a reviewed PR after a person read every commit it skips. |
| D | `data/` | Meets I-data: checked by G on every run on main (phase 0 included; on a `blob:none` clone it reads no blob) and by J2 on the commit it pushes; consumers in section "I-data". Who merged a data-only commit is not checked (residual M-2). Read with `json` and `yaml.safe_load` only (grep, 2026-11-17: `sitegen/`, `collector/`); not read by J4. |
| K | Caches (`actions/cache` in J1) | Fetched documents and OCR: data, never executed; GitHub scopes them by branch (a branch run cannot write main's cache). |
| P | Runbook `docs/ops/morning-note.md` | 2.0 (protect main; new 2.0.3 merge procedure S2; new 2.0.4 V1 probe), 4.6, 4.7 (baseline: now T4.10.8, check only), 5.0 A, "Rules for manual runs and re-runs", "When the note job fails" plus new "When the gate fails". Each says what this table says, no stronger. |
| T | Tests, `tests/test_workflow_lock.py` | `PR_CASES` run against the gate step, plus the new review cases (M-1: outsider and contributor refused, collaborator and owner accepted); the I-data cases, each run with `LC_ALL=C.UTF-8` and with `LC_ALL` unset as well as `C` (refused: symlink, submodule, 100755, other suffix, names `data/\xff.json`, `data/a\nb.json`, `data/x\x1b.json`, `data/.x.json`, `data/a/../b.json`, a tree with no `data/`, `data` as a symlink or file, `data/` emptied; passed: today's tree, `data/changes.jsonl`, `data/a/b/changes.jsonl`; a refusal's `::error::` lines hold no byte outside 0x20-0x7E; also on a `blob:none` clone with no blob fetched); J2 runs the same checks after the rebase (an executable or `\xff` name refused, an empty artifact refused) with the identical `SHAPE` text; only J2 grants `contents: write` or `pull-requests: write` in any workflow; `needs`, `ref` and `if:` of J1-J4; J2's L-C cases; R1 json (approvals 0, no bypass); G's permissions exactly the two reads; G runs no file from the checkout (allowlist lint, as `NOTE_STEP_COMMANDS`); baseline is "" or a sha (sha only after T4.10.8). |

## The gate job
Placed first in `jobs:`; `timeout-minutes: 10`; outputs `sha`, `verified`. Steps: checkout `ref: ${{ github.sha }}`,
`persist-credentials: false`; one inline `run:` step with `GH_TOKEN`, `SHA: ${{ github.sha }}`,
`REF: ${{ github.ref }}`, `MAIN_PR_BASELINE` in `env:`, `set -euo pipefail`:
1. `git rev-parse HEAD` must equal `$SHA`.
2. `REF` is not `refs/heads/main`: output `sha=$SHA`, `verified=false`, stop with success (push, deploy and note
   are main-only already; update builds the branch's own commit, which a branch run's own workflow could do anyway).
2a. I-data (M-2, phase 0 too): checks (1)-(4) of section "I-data", all under `LC_ALL=C`. Tree objects only, no
   file contents.
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

## Baseline window check (runbook 4.7.1, L-3 and L-b)
Before the baseline is set, a person lists `merged_by.type` for every non-data first-parent commit in the window
`<R2-on sha>..origin/main`, because the gate checks nothing in phase 0.
- **Start.** `<R2-on sha>` is `main`'s sha read (`gh api repos/gn0sh/clarksville-records/git/ref/heads/main`)
  just before S1 writes R1 (main-protect/window-start-gap, 2026-11-17; S1 prints it as `Main before the ruleset:
  <sha>`). The start is sound because `main` is read before R1 is written: anything that reached `main` between
  the read and R1 (even a direct push) is after the start and so in the window, and from R1 on nothing reaches
  `main` but a merged PR, which, by a person or by a workflow, is after the start too. If S1 needed more than one
  run, the start is the sha read before the **first** run wrote R1 (a later run's read would leave the commits
  between the runs out of the window). It does not rely on R2: R2 governs creating PRs, not merging
  them, and a workflow could merge a PR a person opened even with R2 off. S1 prints `R2 was off; main was <sha>` (the pre-R1 sha) when it turns R2 on, and `R2 already
  on` if it finds it on. The person records that line, the date and the S1 output in `docs/platform-facts.md` "Main protection" as
  `R2 first on: <sha>`. If S1's first run found R2 already on, the start is unknown: do not set the baseline; the architect
  picks the window.
- **Loop.** `set -euo pipefail`; the recorded sha must be 40 hex and an ancestor of `origin/main`
  (`git merge-base --is-ancestor`); the commit list is assigned to a variable first (a failing `git log` inside
  `for c in $(...)` would not stop the loop); each line prints `sha PR #n merged_by.type=t`; the end prints
  `checked N commits`. Stop on any `Bot`, any `none` (no merged PR), any failed read, or **N = 0** (a wrong or
  placeholder sha, since the gate's own PR at least is in the window). The whole output is pasted into the baseline
  PR; a test keeps `merged_by`, `merge-base --is-ancestor` and `checked` in the runbook text.

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
   (`gh api repos/gn0sh/clarksville-records/git/ref/heads/main` before and after, as the probe scripts read it). A refusal for any other reason (not mergeable, ruleset) is
   inconclusive: fix and re-run. The verdict FAIL comes only from the probe PR reading `merged` (or the run's own
   merge answer) or `v1-canary.yml` being on `main`; `main` moving while the PR stays unmerged, or a failed read, is
   inconclusive and leaves R2 on (v1-probe/verdict-from-main-sha).
4. Same session, on the probe PR: post a COMMENT review as the PR's author with an explicit older `commit_id` and
   check the API returns that `commit_id` (S2 and gate 5(d) depend on it).
5. Clean up: close the PR unmerged, delete both probe branches (throwaway branches the team made), record the run
   link, the four messages and step 4's result in `docs/platform-facts.md` "Main protection".

If any merge goes through (V1 false): turn R2 off at once (`gh api -X PUT
repos/gn0sh/clarksville-records/actions/permissions/workflow -F can_approve_pull_request_reviews=false`; J2 then
can no longer open its data PR, so the site's data stops updating); then, as the first manual step, turn off
GitHub Actions (Settings > Actions > General > Disable actions; required, since the repository is public and anyone
can open a PR at any time; v1-probe/v1-fail-containment-incomplete, v1-fail-containment-order); this stops the
daily data update until the architect re-plans. R2 off stops workflows opening PRs, not merging them, so then close
every open PR into `main` (a workflow can still merge one a person opened), then delete each closed PR's head
branch (a closed PR whose branch still exists can be reopened and merged); remove the inert canary by a person's PR; leave
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
  shape check (step 2a, I-data) keeps it to regular `*.json`, `*.yml` and `changes.jsonl` files with plain ASCII names; and a test keeps
  `contents: write` and `pull-requests: write` to J2 alone. Reopen if another workflow needs either permission, or if
  the note ever sends without the E2 reviewer.
- zip-slip-residual: a download that could write anywhere on the runner (toolcache, `GITHUB_ENV`) has better targets
  than `NOTE_LIB`; the defence is the pinned `download-artifact` (v4.3.0) and the plan coming only from this run's J1.
- Unverified GitHub behaviour, each failing closed if wrong except V1: V1 (probe step 3); an author's COMMENT review
  keeps the `commit_id` it was posted with (probe step 4); a merged PR's `head.sha` stays as merged (S2 deletes the
  head branch, so nothing can push it later).
