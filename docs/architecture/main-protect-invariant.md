# main-protect invariant (loop rule re-plan, 2026-11-17)
> Superseded in part by ADR 0011; see "After the cutover" below.

software-architect, 2026-11-17. Replaces the 2026-11-11 version (devops-engineer; git history keeps it). The
`main-protect/` family has been hit twice since the no-bypass ruleset: M1 (the Actions bypass let a workflow on any
branch push `main`) and the bot-merge path that replaced it (security V1, M-A, L-A, L-C, L-D, L-E). Decision record:
ADR 0009. Tasks: `docs/tasks/morning-note.md` T4.10. Third hit (security S-1, L-a, L-b at 6e3c019): the data/ shape
check failed open on non-UTF-8 names; the shape is restated below as I-data, with every consumer.
**2026-11-18: V1 is false** (probe run 44270476748: `GITHUB_TOKEN` squash-merged PR #40, which adds a workflow file).
The workflow line is now held by the code-owner rule R1' (ADR 0010), not V1; threats and re-plan in "V1 is false".

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
and (b') **R1'** (ADR 0010): `.github/CODEOWNERS` gives every path outside `data/` the owner gn0sh and the ruleset
requires a code owner's approving review, so a PR that changes anything outside `data/` merges only by an admin's
bypass merge, i.e. by a person; `GITHUB_TOKEN` is no code owner and holds no admin role. (b') replaces V1 ("GitHub
refuses `GITHUB_TOKEN` a workflow change by merge"), which the probe showed false on 2026-11-18. (b') is unverified
until the V1' probe passes, which must happen before `MAIN_PR_BASELINE` or `MORNING_NOTE_SEND` is set.
The gate's check stays inline in the workflow file, never a script in the repository (under R1' no bot merge reaches
`scripts/` either, but one copy in one place is simpler to review).

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

## After the cutover (ADR 0011; cutover merged 2026-11-19, 8d69778)
ADR 0011 supersedes the code-owner rule R1' and the data-only exception in I-main above (ADR 0010 decisions 1, 2
and 5). I-data and the gate's shape check remain as `SHAPE''` for `records-data`. The four invariants below are
stated in full, with every consumer, in `docs/architecture/v1-fail-2026-11-18.md` section 2 (and the table there);
this is the short form. The trust roots the scripts compare against are in `docs/architecture/data-off-main-trust-roots.md`
(I-root, consumers C1-C22); the I-pub detail is in `docs/architecture/ipub-tripwire-invariant.md`.

- **I-main''.** `main` moves only by a person's bypass merge of a reviewed PR. With R2 off, gn0sh the only writer, and R1'' needing 10 approvals with at most the `claude` App
  approving (ADR 0011 Amendment 2026-11-18 (b); `scripts/protect-main.sh`), as checked by `protect-main` from Brian's PC,
  no workflow token can satisfy `main`'s merge rule for any PR. `main` tracks no `data/`. Curated inputs are reviewed code under `config/`. Collector
  output lives on branch `records-data`, which only moves forward. There is no data-only exception: the gate refuses
  any first-parent commit after `MAIN_PR_BASELINE` that a person did not merge, and any tracked `data/` on `S`.
- **I-prov.** The gate accepts the `records-data` head `D` only if (a) its tree listing
  (`git ls-tree -r -z D -- data`, as a file) carries an artifact attestation signed by
  `.github/workflows/daily-update.yml` at `refs/heads/main` in this repository (GitHub-hosted runner, SLSA provenance
  v1), or (b) `D` is the parentless seed commit and its digest equals `RECORDS_DATA_SEED_DIGEST`, pinned by the
  cutover PR. Only the `push` job holds `attestations: write`. A person's whole-tree restore of an earlier attested
  tree is accepted; a hand edit is not. `D`'s tree must also meet `SHAPE''` and hold no config-owned names (I-data'').
- **I-pub.** A run deploys only if no vote, roll call or outcome already on the live site changes or disappears.
  "Live" is the `D` recorded in the site's `build-info.json`. Only a change listed in the reviewed
  `config/published-fact-changes.yml` passes; `allow_shrink` never counts. Otherwise the run opens an issue and holds
  the deploy; the data push still happens. I-pub gives no protection against a parser compromise in the update job
  itself (ADR 0011 consequence a).
- **I-in.** Every file a build or a credentialed job reads comes from exactly one of two places: (a) `D`, or (b) `S`,
  reviewed code and config that reached `main` by a person's merge. No person-run tool writes under `data/` for
  commit. What a person makes (a transcript batch, a map manifest row, an accepted city-book reading) reaches the
  build only as a reviewed file under `config/`, and no reader of a config-owned input falls back to `data/`.

| Consumer | Invariants it upholds | Where |
|---|---|---|
| `gate` job (G) | I-main'', I-data'', I-prov | Reads `D` once; no workflow input can set it. |
| `update` job (J1) | I-run'' (`S` plus `D`), I-pub | Checks out `S`, then `D`'s `data/`; runs the tripwire; sets `held`. |
| `push` job (J2) | I-prov, I-data'' | Fast-forwards `records-data`, then attests the listing. No PR, so R2 is not needed. |
| `deploy` job (J3) | I-pub | Also needs `held == no` (`daily-update.yml`). |
| `note` job (J4) | I-main'' | Reads no `data/`; skipped when the deploy is held. |
| Rulesets R1'', R-D, R-T; R2 off | I-main'' | R1'' on `main`; R-D on `records-data` (no deletion, no force push, no bypass); R-T blocks a tag named `main`. |
| `scripts/protect-main`, `merge-reviewed`, `u3-toggle`, `cutover-data-off-main` | I-main'', I-prov | Trust roots: `data-off-main-trust-roots.md`. |
| Curated files (CFG), transcripts (TR), map manifest (MP), kept city books (FB), scrub tool (SC), readers that list `data/` (LS) | I-in | `v1-fail-2026-11-18.md` rows CFG, TR, MP, FB, SC, LS; `data-inventory.md`. |

### Workflows on main (note 2026-11-20, software-architect; `main-protect/` 4th hit, loop rule)
PR #69 (ADR 0013 decision 6) put `.github/workflows/national-update.yml` on `main`, and `protect-main -Check` said
NOT OK, because S1-7 allowed `daily-update.yml` alone. Why S1-7 existed: any other workflow on `main` could reach the
`github-pages` or `morning-note` environment (both allow `main`) or a deploy credential without meeting
`daily-update`'s gate, or could hold a token that writes `main`, `records-data` or a tag, or sign attestations.
**I-wf.** `main`'s `.github/workflows/` holds exactly `daily-update.yml` and `national-update.yml`, both files, and
`national-update.yml` keeps these properties (checked by `protect-main`, both twins, both modes; at the strictness of
the `daily-update.yml` checks): (1) `permissions: {}` at the top, no inline job permissions; (2) its gate step
"Check the national-data head" in job `gate` only, and `push` needs `gate`; (3) `contents: write`, `id-token: write`
and `attestations: write` in job `push` only, and no other write but `issues: write` in job `report` (so no
`pull-requests`, `pages`, `actions` write); (4) no job names an `environment` or calls a reusable workflow (job-level
`uses:`), and no line reads `secrets`. Also held by tests, not by `protect-main`: the push job pushes only
`HEAD:refs/heads/national-data` and runs no repository file, and its attestations are verified only with
`--cert-identity .../national-update.yml@refs/heads/main` (`tests/test_national_workflow.py`, `test_workflow_lock.py`).
**Why it keeps I-main'', I-run'' and I-prov** (checked at 3b16c66): its push token (`contents: write`, persisted by
the checkout to push) cannot move `main`: R1'' (`scripts/main-ruleset.json`) needs a PR with 10 approvals and its
only bypass is the admin role in PR mode; the token has no `pull-requests` permission, and with R2 off it cannot
approve. It cannot create, move or delete the tag `main` (R-T). It *can* fast-forward `records-data` (R-D blocks only
deletion and force pushes) or create other tags, but only by running code in that job, which runs inline shell and
three pinned actions only. A new tree it made carries only a `national-update.yml` attestation, which the gate
refuses (`daily-update.yml` line 211 pins `daily-update.yml@refs/heads/main`): a held run. But the gate accepts any
head whose listing matches *any* past `daily-update.yml` attestation, so such a token could also fast-forward
`records-data` to a commit whose tree is an older attested tree: the site then deploys stale data, not held
(security review of 8bc835f7, `main-protect/replay-attested-listing`; I-prov already accepts a person's whole-tree
restore). The same holds for `daily-update.yml`'s own push job and for gn0sh, so this adds no new kind of exposure.
Every checkout uses a sha; fetches use `refs/heads/...`, except `git fetch ... origin main` in the daily gate
(`daily-update.yml` ~226) and the national gate (`national-update.yml`:162), which read main's history only: R-T
blocks a tag named `main`, and the history checks walk from `HEAD` = `github.sha`, not from the fetched ref.
Since the security review, `protect-main` also pins `national-update.yml`'s blob sha (the shape regexes above are a
heuristic: `main-protect/nat-shape-heuristic-bypass`): any change to the file is NOT OK until a reviewed PR updates
the pin in both twins, and a test keeps the pin equal to `git hash-object` of the checkout's file.
Residuals: replaying an older attested `records-data` tree (stale deploy; pre-existing; no gate change now).
 `national-data` has no ruleset until U3-0, so any `contents: write` token could move it (the daily
national lookup reads only attested commits and fails soft); a D3 rollback restores `daily-update.yml` and leaves
`national-update.yml` on `main`, which I-wf still allows.
Consumers of the old "only `daily-update.yml`" rule: `scripts/protect-main.sh` and `.ps1` (S1-7 and header; changed);
`tests/test_protect_main.py` (stub listing, S1-6/S1-7 lines, S1-7 cases, row-10 read order, the 403 list; changed);
`scripts/v1pp-probe.{sh,ps1}` step 0 and `scripts/cutover-data-off-main.{sh,ps1}` steps 4-5 and rollback (call
`protect-main`, hold no copy; tests stub it; unchanged); `docs/architecture/data-off-main-trust-roots.md` C18
(changed); `docs/ops/morning-note.md` 4 item 6/6a (only "prints OK"; unchanged); ADR 0011 S1-5..S1-8 paragraph and
`docs/reviews/s1-*.md`, `pr66-merged-security.md` (dated records; unchanged). Not consumers: the daily gate (does not
list the folder), `u3-toggle` (reads `daily-update.yml` runs only). A third workflow on `main` changes I-wf, both
twins and their tests in one PR, with this note.

## Every consumer, and how it upholds the invariant
| # | Consumer | How it upholds it |
|---|---|---|
| G | `gate` job (new, T4.10.2) | Runs first; `contents: read`, `pull-requests: read`, no secrets, no persisted token. Checks data/'s shape and I-main for `S` (design below), outputs `sha` (= `S`) and `verified`. Fails closed on any API error, shallow history, bad baseline, or an empty list of commits to check. |
| J1 | `update` job | `needs: gate`; checks out exactly `needs.gate.outputs.sha`, not `ref: main` (L-A). `contents: read`, token not persisted, `issues: write` only. Its build and plan come from the checked commit, so what `deploy` publishes and `note` sends was built by checked code. |
| J2 | `push` job | `needs: [gate, update]`; commits on `update.sha` (= `S`). Local check: one commit on top of main, `data/` only. Server check: the PR's file list equals the local list exactly and is not empty (L-C); every name under `data/`; merge pinned to the checked `sha`, squash. Its merges are the bot merges I-main expects (data only); a test keeps `contents: write` and `pull-requests: write` to this job alone across every workflow (M-2). |
| J3 | `deploy` job | `needs: [gate, update, push]`, plus `needs.gate.result == 'success'` in its `if:`. Publishes only this run's artifact from J1. Environment `github-pages`, main only (E1). |
| J4 | `note` job | `needs: [gate, update, deploy]`, `if:` adds `needs.gate.outputs.verified == 'true'`; checks out `needs.gate.outputs.sha`. Its own PR-check step is removed (one copy, in the gate); the stale-rerun step stays. Internals: table "Inside the note job" below. |
| J5 | `note-failed`, `gate-failed` (new), push's failure step | `issues: write` only, fixed text, no checkout, run no repo code. |
| W1 | The workflow file at `S` | Ruleset R1' (PR only, code-owner review outside `data/`, admin bypass for PRs only). V1 is false and no longer relied on. The gate also refuses a bot-merged `.github/` commit already in the history (3ef440a, PR #40, is before the baseline: see "V1 is false"), so a later good workflow stops until a person moves the baseline past it. |
| W2 | Workflows on any other branch | Only a writer can create or start one (T2, T7 in "V1 is false"). With `contents: write` it can merge an open PR (R2 does not govern merging) and, with R2 on, open its own, from any branch or fork. Under R1' it can merge into `main` only a PR that changes nothing outside `data/` (residual M-2, shape checked); before R1' a code or workflow change too, since V1 is false, which G refuses on later runs only if the workflow file still holds G. It can merge into unprotected branches (workflows included) and dispatch them: they reach no credential while E1 and E2 are main only. |
| E1 | Environment `github-pages` | Deployment branches **main only**. `gh-pages` is still allowed today (status: "optional hygiene"); under I-run it is not optional: a workflow a person pushes to `gh-pages` (the ruleset covers main only) would get `pages: write` outside the gate. Removed in T4.10.5. |
| E2 | Environment `morning-note` | Main only (runbook 2.0). Required reviewer optional (runbook 5.0 A): the only control against L3. |
| R1 | Main ruleset, `scripts/main-ruleset.json` (R1' from T4.11.2, ADR 0010) | `deletion`, `non_fast_forward`, `pull_request` with 0 approvals and (R1') `require_code_owner_review: true`, `allowed_merge_methods: ["squash"]`; bypass (R1'): Repository admin role, mode pull request only (nobody may push `main`). Approvals stay 0 (L-E): with R2 on, a workflow's approval would count toward any number above 0, and the data PR has no one to approve it; a bot's approval is never a code owner's. The gate counts no approvals, only a person's merge and a person's review at head. |
| CO | `.github/CODEOWNERS` (new, T4.11.2) | `* @gn0sh` then `/data/` with no owner: every path outside `data/` is owned, `data/` is not. Read by GitHub from `main` (the base); a change to it is itself owned. A syntax error silently drops a line, so S1 checks `codeowners/errors` is empty and a test pins the exact text. |
| R2 | Setting "Allow GitHub Actions to create and approve pull requests" | **Superseded (ADR 0011): OFF since the cutover and must stay off.** Pre-cutover: on, for J2 (off since the 2026-11-18 FAIL; back on per ADR 0010 decision 3). It governs creating and approving PRs with `GITHUB_TOKEN`, not merging (seen 2026-11-18: R2 off did not matter to the probe, whose PR a person opened). With R2 on a workflow can also open its own PR; under R1' it can merge it only if it is data-only. Turning R2 off stops J2 opening its data PR and nothing else of consequence. |
| R3 | Repo merge settings | `allow_auto_merge: false` (L-D: auto-merge merges whatever head the branch has later). Under R1' the ruleset allows squash only (S2 and J2 squash), so G's rebase-merge refusal becomes a second line. |
| S1 | `scripts/protect-main.sh`, `.ps1` | Create or update R1 (R1' from T4.11.2), then read R2 and `main`'s sha, then turn on R2 (in that order since L-b), printing `R2 was off; main was <sha>` or `R2 already on`; their OK check asserts approvals 0, `allow_auto_merge` false and (T4.11.2) code-owner review on, squash only, bypass exactly the admin role in pull-request mode, `.github/CODEOWNERS` on `main` with `codeowners/errors` empty; NOT OK otherwise. |
| S2 | `scripts/merge-reviewed.sh`, `.ps1` | The only way a person merges a non-data PR: `merge-reviewed <pr> <reviewed-sha>` posts a COMMENT review with `commit_id=<reviewed-sha>` (body: the review report links), merges with `sha=<reviewed-sha>` (refused if the head moved: L-D), then deletes the head branch. Under R1' its merge is an admin bypass (U3 in ADR 0010; fallback: the Merge button with "bypass rules" after the script posted its review). |
| B | `MAIN_PR_BASELINE` | **Superseded (ADR 0011 Amendment (c)): set by the cutover PR to 1922fda3, moved to eef6ed06 on 2026-11-20 (ADR 0011 note 2026-11-20); empty on main is a gate refusal.** Pre-cutover: lives in the gate step's `env` only (moved from J4). Empty = phase 0: gate outputs `verified=false` and passes, so J1-J3 run as they do today and J4 never runs. Set by a person's PR (T4.10.8) after the V1' probe passes, at or after the canary-removal merge; from then the test accepts only a sha. Before it is set, runbook 4.7.1 checks the window from the R2 switch-on (section "Baseline window check"), with 3ef440a (PR #40) and 2b20704 (PR #49) as its two known Bot merges. Moved later only by a reviewed PR after a person read every commit it skips. |
| D | `data/` | Meets I-data: checked by G on every run on main (phase 0 included; on a `blob:none` clone it reads no blob) and by J2 on the commit it pushes; consumers in section "I-data". Who merged a data-only commit is not checked (residual M-2). Read with `json` and `yaml.safe_load` only (grep, 2026-11-17: `sitegen/`, `collector/`); not read by J4. |
| K | Caches (`actions/cache` in J1) | Fetched documents and OCR: data, never executed; GitHub scopes them by branch (a branch run cannot write main's cache). |
| P | Runbook `docs/ops/morning-note.md` | 2.0 (protect main, R1' and CODEOWNERS from T4.11.4; 2.0.3 merge procedure S2, a bypass merge under R1'; 2.0.4 V1 probe: FAIL 2026-11-18, then the V1' probe), 4.6, 4.7 (baseline: now T4.10.8, check only), 5.0 A, "Rules for manual runs and re-runs", "When the note job fails" plus new "When the gate fails". Each says what this table says, no stronger. |
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
  `checked N commits`. Two known exceptions (ADR 0010): 3ef440a, PR #40, the V1 probe's bot merge, and 2b20704, PR #49, the V1' probe's
  bot merge (2026-11-18), each of which changed only `.github/workflows/v1-canary.yml` (`git show --stat <sha>`)
  and which the canary-removal PRs revert; the person
  checks both and names them in the baseline PR. Otherwise stop on any `Bot`, any `none` (no merged PR), any failed read, or **N = 0** (a wrong or
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

**Result, 2026-11-18 08:50 UTC: FAIL (V1 false).** The first try, REST squash pinned to the head, merged PR #40
(details: `docs/platform-facts.md` "Main protection"). The script turned R2 off. Step 4 held (`commit_id` c588924
kept). The 2026-11-17 FAIL steps (v1-fail-containment-incomplete: after R2 off, Disable actions, which stops the
daily data update until the architect re-plans; then close every open PR into `main`; then delete each closed PR's
head branch) were judged against the live state the same day and are **not needed** (section "V1 is false", T1-T8;
T4.11.3 rewrites the scripts' FAIL text and its test): the containment
for a FAIL is R2 off, the canary removed by a person's PR, and the baseline and `MORNING_NOTE_SEND` left unset. The
probe scripts now refuse to run until R1' is on (v1-probe/rerun-after-fail), since R2 off does not stop the runner's
merge of a PR a person opened.

**V1' probe (T4.11.7, after R1').** The same steps 1-5, target and runner unchanged. PASS: all four merges refused,
each message naming the ruleset or code-owner review (a refusal naming the `workflows` permission also counts: the
merge was refused), `main` unchanged, the PR unmerged after cleanup, the canary absent from `main`; any other refusal
reason is inconclusive. Positive controls, recorded with it: the next data PR merged by github-actions under R1'
(U2) and the next S2 merge went through (U3). FAIL: R2 off, canary removed again by a person's PR, and the fallback
"data off main" goes to a Brain Trust (ADR 0010). **The V1' probe gates `MORNING_NOTE_SEND`** through T4.10.8.

### V1'' try 1 inconclusive (2026-11-21)
software-architect. Try 1 (Brian's PC, 01:21 UTC, main cbe28ea2; probe run 44849699396, env runs 44849694291 and
44849694952): nothing went through, 9 lines not PASS. The rule the scripts keep: **a PASS line means GitHub refused for
the reason the invariant relies on, never "some error"**; every widening below is narrow and has a test that the
neighbouring wordings stay INCONCLUSIVE. Consumers of the verdict: `scripts/v1pp-probe.{sh,ps1}` (headers, `judge_pr`,
the tag main step, `pages_refused`, `mark`, the PASS line), `tests/test_v1pp_probe.py` and `tests/v1pp_stub_gh.py`,
runbook `docs/ops/morning-note.md` section 4 item 6a (the line kinds), ADR 0011 Amendment (c) item 6 (PASS gates
`MORNING_NOTE_SEND`; unchanged). The unlock moves to 2026-11-24 for the rerun.

1. **Squash and GraphQL (6 lines): PASS on the last-pusher wording, narrowly** (`v1pp-probe/squash-last-pusher`;
   confidence high). GitHub answered "Repository rule violations found / New changes require approval from someone
   other than the last pusher". That is the `require_last_push_approval` condition of the `pull_request` rule in R1''
   (`scripts/main-ruleset.json`), the same rule whose approval count the invariant relies on; GitHub names one unmet
   condition, not all. Accepted only as the full phrase together with "Repository rule violations found" (either
   alone stays INCONCLUSIVE); "approving review" still counts. Against: a message names a condition, not a ruleset
   id. Held because protect-main `-Check` proves R1'' is the only rule set on `main` just before the probe.
2. **Tag main (bare 422 "Reference update failed"): PASS only on GitHub's rule suite** (`v1pp-probe/tag-main-unnamed-422`;
   confidence medium that GitHub records it, high that the check is sound). A 422 naming no rule could be a refusal R-T
   plays no part in, which would not stop a `git push` of `refs/tags/main`, and "absent after" only shows it was not
   created this once. So right after the try the script reads `GET rulesets/rule-suites?ref=refs/tags/main&time_period=day`
   (fields and enums checked against GitHub's OpenAPI description: `actor_name`, `after_sha`, `pushed_at`, `result`
   pass/fail/bypass; `rule_evaluations[].rule_source.id`, `rule_type`, `result` pass/fail, `enforcement`
   active/evaluate/deleted ruleset) and needs exactly one suite with `after_sha` = main, `actor_name` = gn0sh and
   `pushed_at` no earlier than 60 s before the try, suite result `fail`, and exactly one R-T (27685093) `creation`
   evaluation with result `fail`, enforcement `active`. Before reading, the start time must read
   `YYYY-MM-DDTHH:MM:SSZ` (`v1pp-probe/tag-main-t0-unchecked`: the bash twin needs GNU `date -d`; otherwise the suite is
   not read). Not verified: that GitHub writes a rule suite for a refused REST ref creation (it does for API merges: U3).
   **Delta after review (same day): the git push line.** Right after the suite read, the script also tries
   `git push <main>:refs/tags/main` from a scratch clone as gn0sh (`tag main git`): GH013 or "rule violation" is PASS,
   success is FAIL, anything else INCONCLUSIVE. The suite is read first because the git push makes a second suite for
   the same sha, which the "exactly one" rule would refuse. **How the two lines combine** (so a missing rule suite cannot
   force a third run): the REST line is PASS on its own suite; or, only when no suite could be seen or read (none in 6
   reads, unreadable, or no start time), when the git line is PASS, because R-T has no bypass actor and is then shown
   refusing the same tag for the same admin account, and `tag main after` reads it absent. A suite that contradicts R-T
   (another ruleset, `evaluate`, result `pass`, two suites) stays INCONCLUSIVE whatever git says. The git line always
   counts by itself. **Round 2 (security follow-ups, `v1pp-probe/tag-git-*`):** only git's own answer from GitHub
   counts. Both twins refuse to start without git (a `git` that never ran must not read as exit 0: the .ps1 also sets
   `$LASTEXITCODE` to 99 before each call); the push uses `--no-verify`, an empty `core.hooksPath`, an empty
   `GIT_CONFIG_GLOBAL` (no url rewrite, hook path or helper from Brian's config), gh as the only credential helper,
   no `GIT_TRACE*`, `GIT_CURL_VERBOSE` or askpass, and `GIT_TRACE_REDACT=1` (the .ps1 puts the environment back).
   PASS needs a `remote: error: GH013: Repository rule violations found for refs/tags/main` line and git's
   `To https://github.com/gn0sh/clarksville-records.git`; a bare "rule violation" (a local hook could print it) or
   another `To` is INCONCLUSIVE. "Everything up-to-date" is FAIL only after the REST try created the tag. Requiring
   R-T's own wording ("creations being restricted") was considered and dropped: it is not in GitHub's docs.
3. **pages-api on the branch run, "no answer in the run's log": read each job's own log** (`v1pp-probe/run-log-missing`;
   confidence medium on the cause, high on the fix). `gh run view --log` builds its output from the run's log archive
   and the script threw away its error; the same-shaped tag run, read seconds later, worked, so the likely cause is the
   archive not ready yet just after completion. Both twins now list the run's jobs and read
   `GET actions/jobs/<id>/logs` (the plain-text job log, GitHub's documented 302 that `gh api` follows), up to 6 reads
   10 s apart until a read holds the expected line; never readable is INCONCLUSIVE with the job id. The runner's
   answers come the same way. `gh run view --log` is no longer used (a test pins it). Try 3 (2026-11-21) could read
   none of these logs on Brian's PC and kept no reason: the read rule, a read-only log self-check before any write,
   and a sanitized reason for each failed read are in `v1pp-job-log-invariant.md` (I-log, `v1pp-probe/job-log-unreadable`).
4. **pages-api with the made-up artifact: NOT-REACHABLE, not counted** (`v1pp-probe/pages-api-unreachable`; confidence
   medium; reverses part of security finding S1 `pages-api-coverage`, so security re-reviews it). GitHub checks the
   artifact before any branch or environment rule, so the step could never PASS. No safe input reaches the branch
   check: a real artifact could replace the live site (hard stop 1), another invalid input only meets another
   validation, and a scratch repository with its own Pages site would be a public site under Brian's account (hard
   stop 4). **Strongest case against:** the step was added because environment refusal of *jobs* does not prove the
   Pages *API* enforces the `github-pages` branch policy for a job that declares no environment; not counting it means
   V1'' PASS no longer covers that route. **Why it is still the call:** that route needs a *run* of a workflow that
   calls the API without an environment. A `GITHUB_TOKEN` can put such a file on a branch other than `main` (by a merge;
   W2), but it cannot start it: GitHub starts no run for a push or merge made with `GITHUB_TOKEN` (only
   `workflow_dispatch` and `repository_dispatch` are excepted), and no workflow on `main` grants `actions: write`, so no
   token can dispatch. The runs that do happen are the two workflows on `main` (I-wf, pinned by protect-main), on schedule
   or a person's dispatch, and both deploy only through the `github-pages` environment, whose main-only policy both env
   runs PASSed (branch and tag), with Pages build type `workflow`. A person's dispatch at another ref runs that ref's copy
   of the file, but a person started it. So only a workflow a writer authored or started can reach the Pages API
   outside `github-pages`, already in "Residual (people)" (corrected 2026-11-21 after security's low finding: the
   first text said `GITHUB_TOKEN` cannot create or change a workflow file, which W2 contradicts). Recorded there as
   **U-pages** (unverified: the Pages deployment API requires an OIDC token from a job in the `github-pages` environment).
   Reopen if any workflow on `main` gains `actions: write`. Exactly one answer is exempt: exit
   non-zero with "Unable to find artifact" and HTTP 400 (try 1's answer). It is marked NOT-REACHABLE and does not count
   against PASS. Exit 0 is still FAIL, and any other artifact wording, a 404, or no answer stays INCONCLUSIVE. The PASS
   line says how many pages-api lines were NOT-REACHABLE and that U-pages is not covered.

## V1 is false (2026-11-18): threats with Actions on, and what holds them
State that day (gh api and git, team session): R1 active, no bypass, 0 approvals, code-owner review off; R2 off;
Actions on; canary on `main` (inert); no open PR into `main` (#38 was merged at 08:54 by gn0sh with S2); every
workflow file on all 95 branches triggers only on `schedule` or `workflow_dispatch`.
| # | Path | Today | Under R1' |
|---|---|---|---|
| T1 | Outsider's fork PR runs its own `pull_request` workflow | Read-only token, no secrets (public repo; first-time contributors also need approval): cannot merge, push or open PRs. Closed. | Same. |
| T2 | Outsider triggers a base-branch workflow with a write token (`pull_request_target`, `workflow_run`, `issue_comment`, `issues`...) | No workflow on any branch listens to one (`pull_request_target` runs the PR's *base* branch file, and an outsider may target any branch). Closed. A new such workflow on **any** branch reopens it: forbidden (T4.11.2 adds a lint on the workflow files of the branch under test; review checks others). | Same. |
| T3 | Outsider opens a PR into `main` and waits for a bot to merge it | No workflow merges a PR it did not open (J2 checks number, branch, head, files). Closing PRs adds nothing. Closed. | Bot merge of anything outside `data/` refused. |
| T4 | J2 steered to merge code | Its `sha` input is rebased and must be exactly one commit on `main`, `data/` only; the server file list must equal it (L-C); merge pinned to head. Closed. | Same, plus R1'. |
| T5 | Malicious PDF runs code in J1 | `contents: read`, no persisted token; its artifact is shape-checked (I-data, M-2). Bad data at most. | Same. |
| T6 | A writer (Brian, the team as gn0sh) | Could merge anything already (0 approvals). Residual L3, unchanged. | Bypass merges, logged. |
| T7 | A workflow a writer pushes to any branch, or a pinned action inside one | Merges any open PR into `main`; with R2 on opens and merges its own, workflows included (V1 false), dropping G. Needs write plus the `workflow` scope to create, so it adds no reach beyond T6, but it breaks I-run silently for the note. **Open until R1'.** | Data-only into `main` (M-2). Can still merge and dispatch workflows on unprotected branches: no credential while E1, E2 are main only (T4.10.5 required). |
| T8 | The canary on `main` | `workflow_dispatch` only, `permissions: {}`, `if: false`: inert. Fails `test_the_v1_probe_workflows_are_inert_and_least_privilege` until removed. | Removed by PR. |
Verdict: **turning Actions off is not needed**; with R2 off nothing below a writer can reach `main`, and with R2 on
(needed for data) the same holds, because T7 needs a writer. R1' closes T7 before the note can send.

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
- U-pages (2026-11-21, "V1'' try 1 inconclusive" item 4): not shown that the Pages deployment API refuses an OIDC
  token from a job with no environment on a branch other than `main`. Such a job runs only if a person starts it or
  pushes it: a `GITHUB_TOKEN` can merge the file onto a branch (W2), but its pushes and merges start no run, and no
  workflow on `main` grants `actions: write` to dispatch one. Reopen if a workflow on `main` gains `actions: write` or
  ever calls the Pages API outside the `github-pages` environment.
- zip-slip-residual: a download that could write anywhere on the runner (toolcache, `GITHUB_ENV`) has better targets
  than `NOTE_LIB`; the defence is the pinned `download-artifact` (v4.3.0) and the plan coming only from this run's J1.
- Unverified GitHub behaviour: U1-U4 of ADR 0010 (code-owner review binds with 0 approvals: V1' probe; data/ unowned
  needs no review; S2's merge goes through as a bypass; the owner holds the admin role), each checked before the
  baseline; a merged PR's `head.sha` stays as merged (S2 deletes the head branch, so nothing can push it later).
  Verified 2026-11-18: an author's COMMENT review keeps the `commit_id` it was posted with (probe step 4); V1 is false.
