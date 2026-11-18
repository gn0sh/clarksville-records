# Morning note: runbook (T4.7)

The morning note is the daily email built from `build/site/morning/<D>.json` (architecture:
`docs/architecture/morning-note.md` "T4 sender"; tasks: `docs/tasks/morning-note.md` T4.0 to T4.8). This page is
the order of work from no account to a live send, and how to stop it. **Nothing on this page has been done yet.** The
team creates no account, key, secret, variable or environment; every step marked **Brian** is his (hard stops 1, 3
and 5).

## How it runs (`.github/workflows/daily-update.yml`)
- `gate` job, first, every run (T4.10.2; `docs/architecture/main-protect-invariant.md`, ADR 0009): step "Check every change outside data/ reached main by a reviewed pull request a person merged". On `main`, with `MAIN_PR_BASELINE` set, it refuses unless every commit on `main`'s first-parent line
  after the baseline that changes anything outside `data/` is the merge or squash commit of exactly one pull request
  into `main`, merged by a person, with a person's review (Comment or Approve; by the owner or a collaborator) of the
  PR's head commit before the merge (step 2.0.3 does both); a merge commit's merged-in side must be that head. It outputs the run's commit and
  `verified`. `update` builds exactly that commit, `deploy` needs the gate's success, and `note` needs
  `verified == 'true'`. While the baseline is empty (phase 0) or on any branch other than `main`, it passes with
  `verified=false`: the site updates and deploys as before, and the note never runs. Read-only token, no secret;
  it runs no file from the repository. A refusal opens one issue **"Daily update: main history check failed"**
  (job `gate-failed`) and stops the build, deploy and note: "When the gate fails" below.
- `update` job, step "Plan the morning note (dry run, no network)": `python -m sender plan --rehearse` every day,
  no secret, no network. It writes `build/morning-send/<D>/` (plan.json and the editions, no subscriber data) and
  uploads it as the `morning-send` artifact (2 days). `continue-on-error`: a plan failure never fails the daily
  job, the data commit or the deploy.
- `note` job: runs only when **all** of these hold, otherwise it is skipped:
  1. the run was started by the daily schedule (a manual "Run workflow" never sends);
  2. the run is on `main`;
  3. the repository variable `MORNING_NOTE_SEND` is exactly `true`;
  4. the `update` and `deploy` jobs both succeeded (so it never runs while the deploy is locked, and an email never
     links a page that is not live);
  5. the `gate` job verified `main`'s history (`verified` is `true`: never while `MAIN_PR_BASELINE` is empty).
  Inside it: mask the canary ids, check out the gate's commit (no token kept), stop if its `sender/`,
  `config/site.yml` or `.github/` differ from `main` (a re-run of an older run), Python with no pip step, stage `sender/*.py` and
  `config/site.yml` from the commit's git objects into a new folder outside the checkout (its sha256 digest is
  re-checked before each later Python step), download the plan to the runner's temp folder, check the files, a dry
  run that checks the plan, then the delivery. Every Python run is `python -I -S -c` with only that folder on
  `sys.path` and its staged `site.yml` as `--config`, so no file in the checkout can shadow a module or change the
  settings (docs/architecture/main-protect-invariant.md). `--live` is passed only when
  `MORNING_NOTE_SEND` is `true`. `permissions: contents: read` only, and no step uses the job's `GITHUB_TOKEN`
  (the history check is the gate's). `BUTTONDOWN_API_KEY` is given to that last step only.
- `note-failed` job: when the `note` job failed or was cancelled, opens one issue titled **"Daily update: morning note failed"**, or
  comments on it if it is open. A note failure never opens "Daily update failed" and never touches the site.
- Three switches must all be on before anything is sent: `morning_note.sender.enabled: true` in `config/site.yml`
  (a reviewed PR, after T4.8), the variable `MORNING_NOTE_SEND`, and the `BUTTONDOWN_API_KEY` secret. With
  `sender.enabled` false, `--live` is a dry run that says so.

## 1. Account setup (Brian, once; nothing is sent)
Buttondown's screens were not seen by the team (no account yet): the menu names below are from its documentation
and may be labelled differently. Record what each screen really says in `docs/platform-facts.md` as you go.
1. **Brian:** open https://buttondown.com/register and create the newsletter. Name: the site name only (the From
   name; nothing that reads as an authority: no "City of", "County", "CMCSS", "RPC" or "official").
2. **Brian:** Settings > Domains (sending domain): add the sending domain and add the SPF and DKIM records it shows
   at the DNS host. This may need the paid plan (hard stop 3: approve the spend first).
   **Skipped (2026-11-16):** the free plan sends from Buttondown's own address, so no spend. Whether to add a
   custom domain later is call B in section 5 step 0 (recommended: no).
3. **Brian:** Settings > Subscribing: double opt-in **on** for form sign-ups.
4. **Brian:** Settings > Tracking: open tracking **off**, click tracking **off**.
5. **Brian:** Settings > Email: reply-to = a team address (not a personal one).
6. **Brian:** Settings > Metadata: nothing to add. On the free plan the screen says metadata needs the Basic plan,
   and tags are paid too (2026-11-18: a real sign-up got none), so the form posts only the address and every
   confirmed subscriber gets the one note (`mode: all`; architecture "One edition for everyone"). Do **not** add
   `canary` or `note_edition` (canaries are ids in a secret; the stamp is written by the sender only).
7. **Brian:** Settings > API > New key: a **scoped** key, never the primary key. Emails: write. Sending: write.
   Subscribers: **none** for `mode: all` (from task N1, 2026-11-18); write only for a `stamp` canary trial. Every
   other area: none. A key already made with Subscribers write keeps working; narrow it at the next rotation.
   Copy it once; it goes straight into the GitHub secret in step 2.3 and nowhere else (not a file, chat or issue).

## 2. GitHub settings (Brian, once; nothing runs yet)
0. **Brian: protect `main` first** (security-note-workflow M1, main-protect/actions-bypass-reopens-M1,
   note-key/writer-reach-whole-list). **Changed 2026-11-18 (ADR 0010): the ruleset is R1'.** The daily `data/`
   commit reaches `main` by its own pull request, and nobody, GitHub Actions included, can push `main` directly.
   R1' adds: **code-owner review** (`.github/CODEOWNERS`: `* @gn0sh`, then `/data/` with no owner, so every path
   outside `data/` is owned and `data/` is not), **squash only**, and one bypass, the **Repository admin role in
   "pull request" mode** (an admin may merge a pull request without its requirements; nobody may push `main`).
   So a pull request that changes anything outside `data/` merges only by an admin's bypass merge, i.e. by a
   person: `GITHUB_TOKEN` is no code owner and holds no admin role, and nobody approves (gn0sh authors the pull
   requests and cannot approve his own). A pull request that changes only `data/` needs no review, so the `push`
   job merges it as before.
   **Plainly: anyone with write or admin access to this repository can reach the Buttondown key.** The ruleset
   below does not change that. With 0 required approvals a writer can open a pull request that changes the workflow
   and merge it themselves. The `morning-note` environment's "main only" rule (step 2.2) only says *which branch*
   may use the secret, not who changed it. So:
   - **Keep collaborators to the minimum** (https://github.com/gn0sh/clarksville-records/settings/access): every
     person or app with write access is someone who can reach the key. Add nobody for the morning note.
   - **The ruleset is accident prevention plus an audit trail**, not a lock: it stops every direct push and force
     push (its one bypass is for pull requests only), and it makes every change to `main` show up as a pull
     request. The `gate` job adds a check
     on top, before anything is built, deployed or sent (step "Check every change outside data/ reached main by a reviewed pull request a person merged"): **every** commit on `main`'s first-parent
     line after the baseline `MAIN_PR_BASELINE` that touches anything outside `data/` must be the merge of exactly
     one pull request into `main`, **merged by a person**, with **a person's review of the PR's head commit** (the owner's
     or a collaborator's) posted before the merge. So a later pull request never hides an earlier direct push, and a code PR merged by a bot (a
     workflow using `GITHUB_TOKEN`, which the setting below allows) is refused. The baseline is set once, the day
     the V1' probe passes (2.0.4, section 4 item 7); until then it is empty, the gate checks nothing and the note
     never runs. The team merged earlier work without pull requests; **from the baseline on, every change outside
     `data/` reaches `main` by `scripts/merge-reviewed.ps1` (2.0.3)**, never the Merge button, never auto-merge,
     never "Rebase and merge" (a rebased commit other than the last one is refused).
   - **Required approvals stay 0 (main-protect L-E).** With "Allow GitHub Actions to create and approve pull
     requests" on, a workflow's own approval would count toward any number above 0, so raising it adds nothing; the
     gate counts a person's merge and a person's review instead. Changing it needs ADR 0009 changed first;
     `protect-main.ps1` says NOT OK if it is not 0, or if auto-merge is on (L-D: auto-merge merges whatever head the
     branch has later).
   - **The daily `data/` pull request.** The `push` job commits `data/` on a branch
     `data/<date>-run<run id>-<attempt>`, opens a pull request to `main` and squash-merges it with `GITHUB_TOKEN`
     (0 required approvals, so the ruleset allows it), then deletes the branch. Before merging it checks GitHub's
     copy of that PR: open, into `main`, from this run's branch and commit, and every file it adds, changes, removes
     or renames (both names) is under `data/`, and the PR's set of file names is not empty and equals the local
     commit's (main-protect L-C; GitHub's list is re-read up to 5 times, 10 s apart, while it fills in). Anything
     else fails the job loudly ("Daily update failed" issue) and leaves the PR unmerged: close it unmerged; the next
     run commits fresh data. The merge is pinned to the checked commit, so a push to the branch after the check
     makes the merge fail. These PRs touch only `data/`, so the gate skips them; they are the only bot merges the
     gate allows. A PR opened by `GITHUB_TOKEN` starts no other workflow (no workflow here listens
     to pull requests anyway).
   - What stops a writer who goes around all of this (merging their own code PR with a review of their own, or a
     pushed workflow that drops the gate) is a person: the optional required reviewer on the `morning-note` environment (section 5,
     step 0), which holds every job that would get the key until Brian approves it.
   - **Gap closed by the ruleset (main-protect/ff-push-marks-pr-merged):** GitHub may mark an open pull
     request as merged when its head commit is pushed straight to `main`. The only bypass is in "pull request"
     mode, so nobody can push `main`, and a commit GitHub marked that way after a push by the Actions bot is refused
     by the gate's "merged by a person" test. It reopens only if the ruleset is disabled or a bypass in "always"
     mode is added: then treat a pull request shown as merged that nobody merged on its page as a direct push
     ("When the gate fails").
   - **V1 is false (2026-11-18), so the code-owner rule holds the workflows.** The gate runs inside the workflow it
     judges, so it cannot hold its own file: a bot merge that rewrote `daily-update.yml` would remove the check
     before it ran. The team had relied on V1 (GitHub refuses `GITHUB_TOKEN` a workflow change by merge too); the
     V1 probe showed GitHub does not (2.0.4). What keeps a workflow's merge out of `main` now is R1' above (V1',
     ADR 0010): outside `data/` only a person's bypass merge goes through. The V1' probe (2.0.4) checks it, and
     must pass before `MAIN_PR_BASELINE` or `MORNING_NOTE_SEND` is set.
   `main` takes changes by pull request only; the daily `data/` commit is a pull request too.
   **Order:** the pull request that made the `push` job open data PRs must be on `main` first (the scripts below
   check this and change nothing otherwise); the old job pushed `main` directly and would fail under this ruleset.
   1. **Brian, from a terminal (recommended: one command does all of 2.0).** Prerequisite, once: install GitHub
      CLI (`winget install GitHub.cli`), then **open a new PowerShell window** so `gh` is found, and run
      `gh auth login`, signed in as the repository owner. Get the repository (once): `gh repo clone
      gn0sh/clarksville-records; cd clarksville-records`; if you already have it, `git pull` in that folder. Then,
      in PowerShell in that folder, one line:
      ```
      powershell -NoProfile -File scripts\protect-main.ps1
      ```
      (Local scripts are allowed in Windows Settings > For developers; never add `-ExecutionPolicy Bypass`.)
      (macOS or Linux: `bash scripts/protect-main.sh`.) It (a) stops with "Main does not have the data pull request
      change yet. Nothing was changed." if `main`'s workflow still pushes `main` directly, and with "Main has no
      .github/CODEOWNERS yet" or "Main's .github/CODEOWNERS is not '* @gn0sh' then '/data/'" or "GitHub lists
      errors in main's .github/CODEOWNERS" (each "Nothing was changed") unless `main` has exactly the reviewed
      CODEOWNERS and GitHub found no error in it (a line GitHub cannot read is silently dropped); (b) reads `main`'s commit
      before touching anything and prints **`Main before the ruleset: <sha>`** (it stops, changing nothing, if
      that read fails); then creates the ruleset
      from `scripts/main-ruleset.json` (R1'), or, if a ruleset named `main: pull request required` already
      exists, updates that one to R1', which also replaces any bypass it had with the admin role in pull request
      mode (running it twice never makes a second ruleset); (c) then turns on **Allow GitHub Actions to create and approve pull requests** (Settings > Actions >
      General > Workflow permissions) and prints **`R2 was off; main was <sha>`** (or `R2 already on`), where
      `<sha>` is the one read in (b), before the ruleset was written: send both lines to the team; they record it
      in `docs/platform-facts.md` "Main protection" as `R2 first on: <sha>`, the start of the 4.7.1 window (L-b).
      If it needed more than one run, send every run's output: the start is the `Main before the ruleset` sha of
      the **first** run (main-protect/window-start-gap); (d) prints **OK: main is protected** (rules on main
      `deletion,non_fast_forward,pull_request`, `GitHub Actions may create pull requests: true`, `Auto-merge
      allowed: false`, the ruleset `active, bypass RepositoryRole:5:pull_request, required approvals 0` and
      `Code-owner review: true, merge methods: squash, dismiss stale reviews: true`), or **NOT OK** with what it found: send that output to the
      team. (U4 of ADR 0010: the bypass line shows the owner's admin role is the one that bypasses.)
   2. **Or by hand, in the browser** (only if the terminal is not an option). First, before 2, open
      https://github.com/gn0sh/clarksville-records/commits/main and send the team the first commit's full sha (the
      copy button), as `R2 was off; main was <sha>` (L-b; main-protect/window-start-gap: read before the ruleset is
      written). Then do 2 (the ruleset), then 1:
      1. https://github.com/gn0sh/clarksville-records/settings/actions > **Workflow permissions** > tick **Allow
         GitHub Actions to create and approve pull requests** > **Save**.
      2. https://github.com/gn0sh/clarksville-records/settings/rules: if `main: pull request required` is listed,
         open it; if it is not listed: **New ruleset** > **New branch ruleset**, name `main: pull request
         required`, **Enforcement status** **Active**, **Target branches** > **Add target** > **Include default
         branch**. Either way: **Bypass list** holds only **Repository admin** with **For pull requests only**
         (remove anything else, such as **GitHub Actions**); tick **Restrict deletions**, **Block force pushes**
         and **Require a pull request before merging** (required approvals: **0**, see L-E above; tick **Require
         review from Code Owners**; **Allowed merge methods**: **Squash** only; the team's review is the PR
         review, recorded by 2.0.3). `.github/CODEOWNERS` must already be on `main`. Leave every other rule off (no required
         status checks: the data PR, opened by `GITHUB_TOKEN`, starts no workflow, so a required check would never
         report and the PR could never merge). **Create**.
   Check run: **Actions** > **Daily update** > **Run workflow** (collect on): the `push` job must go green, its log
   must say "Merged pull request #<n> into main.", and https://github.com/gn0sh/clarksville-records/pulls?q=is%3Apr+head%3Adata%2F
   must show that PR as merged by `github-actions`. If the run logs **"No data changes."** it committed nothing, so
   the data PR is not checked yet: wait for a later run (scheduled or manual) that does commit `data/`. If the
   `push` job fails with "GitHub Actions is not permitted to create or approve pull requests", step 2.0.1 (b) or
   2.0.2.1 did not take: tick that box and re-run the failed job. If the merge fails, the "Daily update failed"
   issue says so; data collection is unaffected (the next run commits again), and the site keeps its last deploy.
   - **Verified (2026-11-17, `gh api` from the team's session as the owner):** `main` has no ruleset and no branch
     protection yet (`rulesets` is `[]`, `rules/branches/main` is `[]`, `branches/main` says `protected: false`);
     the repository allows squash, merge-commit and rebase merges, and does not delete merged branches by itself.
   - **Unverified (2026-11-17):** that `GITHUB_TOKEN` (with `contents: write` and `pull-requests: write`) can
     squash-merge the PR it opened under this ruleset (0 approvals). Team judgment, medium confidence: bots merging
     their own PRs under a 0-approval rule is a common pattern, but the team could not read GitHub's docs pages from
     its session (only search snippets of `github/docs`) and has not tried it on this repository.
     Also unverified: that the REST field `can_approve_pull_request_reviews` is the **Allow GitHub Actions to create
     and approve pull requests** box (GitHub's docs say the box controls whether `GITHUB_TOKEN` can create and
     approve pull requests). The check run above settles both; record what was seen in `docs/platform-facts.md`.
   - **If the data PR's merge is refused under R1' (U2 of ADR 0010: an unowned `data/` path should need no
     review):** the `push` job fails loudly ("Daily update failed" issue). Re-apply the previous ruleset json from
     git, in the repository folder after `git pull` (one line, piped, no file written; 91d2ecc is `main` before
     R1'):
     ```
     git show 91d2ecc:scripts/main-ruleset.json | gh api -X PUT repos/gn0sh/clarksville-records/rulesets/27502319 --input -
     ```
     then re-run the failed job, and tell the architect. A write-access deploy key as a bypass actor would also work but is a new secret (hard stop 5);
     not recommended.
   - Until this check passes, the note job must stay off (`MORNING_NOTE_SEND` unset): section 4 item 6.
   3. **Merging every pull request that changes anything outside `data/` (team, from now on; S2, main-protect L-D).**
      After code review, security (when the rules call for it) and QA pass at the PR's head commit `<sha>`
      (`git rev-parse origin/<branch>`), in the repository folder:
      ```
      powershell -NoProfile -File scripts\merge-reviewed.ps1 <pr number> <sha> <review report link> [<more links>]
      ```
      (bash: `bash scripts/merge-reviewed.sh ...`.) It refuses if the PR's head is no longer `<sha>` (a push after
      the review is never merged unreviewed: review the new head and run it again), posts a **Comment** review pinned
      to `<sha>` naming the reports, squash-merges pinned to `<sha>`, deletes the branch and prints the merge commit.
      Never the Merge button and never auto-merge (repository auto-merge stays off): a PR merged any other way has no
      review at its head, and from the baseline on the gate refuses it and every run after it ("When the gate fails").
      **Under R1' this merge is an admin bypass merge** (the PR has no code owner's approval; GitHub logs the bypass
      in the ruleset's insights). U3 of ADR 0010 is whether GitHub lets the script's REST merge bypass: if it
      refuses with a message naming the ruleset or code-owner review, the script has already posted its review
      pinned to `<sha>`; then, and only then, open the PR page, check its head is still `<sha>`, and click **Merge
      without waiting for requirements to be met (bypass rules)** > **Squash and merge**, then delete the branch.
      The gate is satisfied either way (a person merged, a person's review at the head). Record the first S2
      merge's result in `docs/platform-facts.md` "Main protection" (U3).
   4. **V1 probe: FAIL on 2026-11-18; next, the V1' probe (T4.10.1, T4.11.7; architecture
      `docs/architecture/main-protect-invariant.md` "V1 probe").** The first V1 probe (2026-11-18 08:50 UTC, run
      44270476748) ended **FAIL (V1 false)**: the runner's REST squash merge, pinned to the head, merged probe PR
      #40 (`main` 551a483 -> 3ef440a, `merged_by` github-actions[bot]). The script turned **Allow GitHub Actions to
      create and approve pull requests** (R2) off; R2 went back on the same day (ADR 0010 decision 3), the inert
      canary is removed by a person's PR, and `MAIN_PR_BASELINE` and `MORNING_NOTE_SEND` stay unset. The probe
      scripts refuse to run again (changing nothing) until R1' is on: `main` has the reviewed CODEOWNERS with no
      error, and `rules/branches/main` shows code-owner review on in an active ruleset.
      **The V1' probe (once, after 2.0.1 printed OK with R1' and the next data PR merged under it).** In the
      repository folder (after `git pull`):
      ```
      powershell -NoProfile -File scripts\v1-probe.ps1
      ```
      (bash, Linux only: `bash scripts/v1-probe.sh`; it uses GNU `base64 -w0`, so not the macOS default.) It may open a browser once to add the `workflow` scope to your GitHub CLI
      sign-in. It pushes three throwaway target branches and opens their pull requests into `main` (ADR 0010
      decision 5): **W** `probe/v1-target` (an inert workflow file), **N** `probe/v1-target-n` (one inert file in
      `sitegen/`) and **H1** `probe/v1-target-h1` (only renames `.github/CODEOWNERS` into `data/`); then
      `probe/v1-runner`, which starts a run that, for each target, posts a `GITHUB_TOKEN` approval and then tries to
      merge it: squash, merge, rebase, then GraphQL `mergePullRequest`. It takes about 3 minutes, cleans up after
      itself (closes every probe pull request, deletes all four branches), saves
      `Documents\v1-probe-results-<time>.txt`, and ends with one of the verdicts below. If it added the
      `workflow` scope, it removes it again at the very end, after the verdict: a browser may open a second time
      then (approve it; if that fails it prints the one command to run).
      - **PASS (V1')**: for W, N and H1, the bot's approval was posted and did not count: REST squash and GraphQL
        squash were both refused with a message naming code-owner review, merge and rebase were refused ("method
        refused": squash only); `main` unchanged, every probe pull request unmerged after cleanup, no probe file
        on `main`, and the review's `commit_id` kept. Send the output to the team; they record it in
        `docs/platform-facts.md` "Main protection", with the two positive controls (the next data PR merged by
        `github-actions` under R1', U2; the next 2.0.3 merge went through with `merged_by` gn0sh, U3) and Brian's
        two hand checks (Settings > Collaborators: no other admin; the ruleset page shows **Require review from
        Code Owners** and the repository's CODEOWNERS view shows no errors), and set the baseline (section 4 item 7).
      - **FAIL**: a probe pull request merged, or a probe file is on `main`. **If the H1 pull request merged or
        `data/v1-probe-CODEOWNERS` is on `main`, the output says first: main has lost `.github/CODEOWNERS`**, so
        the code-owner rule binds nothing. The first fix is one pull request that restores `.github/CODEOWNERS`
        and deletes `data/v1-probe-CODEOWNERS`, merged by a person with `scripts/merge-reviewed.ps1` (2.0.3; the
        team opens it); then wait for the team. Do not run `scripts\protect-main.ps1` on your own: it turns R2 back on,
        so run it only after the team says so (v1-probe/h1-recovery-reenables-r2). In every FAIL the script has already
        turned R2 off (the daily data stops saving). Leave `MAIN_PR_BASELINE` and `MORNING_NOTE_SEND` unset and send the
        output to the team; what merged is removed by a person's PR, and the fallback "data off `main`" goes to a
        Brain Trust (ADR 0010). Actions stays on and open pull requests stay open: only a writer can start a
        workflow that merges (invariant "V1 is false", T1-T8).
      - **INCONCLUSIVE**: a squash try refused for another reason than code-owner review, an answer missing, the
        bot approval not posted, the run did not start or had not finished, a probe pull
        request could not be read again after cleanup, `main` moved during the probe while
        the probe pull requests stayed unmerged (another merge in the window), or a read failed: the Actions setting
        is left on. Send the output; the team fixes the cause and you run it again.
      `MORNING_NOTE_SEND` waits on the V1' PASS (section 4 item 6a).
   5. **`github-pages` deploys from `main` only (T4.10.5; Brian, one click; the live site keeps deploying).** The
      site deploys today from the `deploy` job on `main` (Pages source: GitHub Actions, since go-live 2026-11-13);
      the old `gh-pages` branch preview is no longer served, but the `github-pages` environment may still allow
      deploys from `gh-pages`, so a workflow a person pushes to that branch could publish the site without the gate.
      Open https://github.com/gn0sh/clarksville-records/settings/environments > **github-pages** > **Deployment
      branches and tags**: if `gh-pages` is listed, click its **trash** icon (or **...** > **Delete**) and confirm.
      **Leave `main` listed** (removing it would stop the live deploy). Do not delete the `gh-pages` branch itself
      (launch runbook "Retire the gh-pages preview"). Check, in PowerShell:
      `gh api repos/gn0sh/clarksville-records/environments/github-pages/deployment-branch-policies --jq '.branch_policies[].name'`
      prints only `main`. If the next Daily update's `deploy` job fails with "not allowed to deploy to github-pages",
      add `main` back the same way (**Add deployment branch or tag rule** > `main`) and re-run the failed jobs.
1. **Brian:** https://github.com/gn0sh/clarksville-records/settings/environments > **New environment** > name
   `morning-note` > **Configure environment**.
2. **Brian:** in `morning-note`, **Deployment branches and tags** > **Selected branches and tags** > **Add deployment
   branch or tag rule** > `main` > **Add rule**. Check: `gh api repos/gn0sh/clarksville-records/environments/morning-note --jq .deployment_branch_policy`
   shows `custom_branch_policies: true`, and
   `gh api repos/gn0sh/clarksville-records/environments/morning-note/deployment-branch-policies --jq '.branch_policies[].name'`
   prints only `main`.
3. **Brian:** in `morning-note`, **Environment secrets** > **Add environment secret** > name `BUTTONDOWN_API_KEY`,
   value the scoped key from 1.7 > **Add secret**.
4. **Brian:** in `morning-note`, **Add environment secret** > name `MORNING_NOTE_CANARY_IDS`, value the Buttondown
   subscriber ids of the team's own addresses, comma separated (ids, not addresses) > **Add secret**.
5. Do **not** create the variable `MORNING_NOTE_SEND` yet (that is go-live, section 5).

## 3. T4.0 probe (team addresses only; devops with Brian's account)
On a separate **test** newsletter, with only team addresses subscribed, answer each item and write the answer into
`docs/platform-facts.md` ("Morning note provider", with the date and who saw it). The probe uses its own scoped key
made on the **test** newsletter only (never the live newsletter's key from 1.7), entered without echo or shell
history, never in a file, a commit or a log:
```
read -rs BUTTONDOWN_API_KEY && export BUTTONDOWN_API_KEY    # paste the key, then Enter; nothing is shown
# the probe calls; the header goes in on stdin, so the key is not in the process list either:
printf 'Authorization: Token %s\n' "$BUTTONDOWN_API_KEY" | curl -sS -H @- https://api.buttondown.com/v1/emails
unset BUTTONDOWN_API_KEY
```
**Brian's way (Windows):** `scripts/morning-note-probe.cmd` runs `scripts/morning-note-probe.ps1`, which does the
automatable items below with the key read by `Read-Host -AsSecureString`, asks the inbox questions, and writes answers
only (no key, address or id) to his OneDrive "App Development" folder. His clicks: `docs/ops/morning-note-brian-steps.md`.
When the probe is finished, delete that key in the test newsletter's Settings > API. Answer each item:
1. An email's `filters` takes `subscriber.metadata.note_edition equals <value>` and reaches only the matching
   subscribers (stamp one of two team subscribers: the other gets nothing).
2. `status: "scheduled"` with `publish_date` holds until then; which `status` sends at once. Creating a draft sends
   nothing.
3. `POST /v1/emails/{id}/send-draft` with `subscribers` is a real send with the unsubscribe link (or a test send).
4. `PATCH /v1/subscribers/{id}` with `metadata`: merges or replaces; the answer echoes the stored metadata.
5. `GET /v1/emails` lists drafts and scheduled emails with `metadata`, newest first, far enough back for today.
6. `GET /v1/subscribers` lists every type; which types a filtered email reaches.
7. `{{ subscriber.email }}` in a body renders literally (no template evaluation), or is evaluated (titles are
   neutralised either way).
8. The public form does **not** accept `metadata__note_edition` or `metadata__canary`: post each to the embed form
   from a team address; the subscriber's metadata must not get it. If it does, `stamp` mode is unsafe: stop.
9. Re-submitting an existing address does not change a confirmed subscriber's metadata; no preferences page lets a
   subscriber edit metadata; double opt-in applies to form sign-ups.
10. The 14 "Verify in T4.0 probe" items of `docs/tasks/morning-note.md` T4.4 (listing shape, `count`, `next`,
    status codes, `Retry-After`, `Content-Type`, id shape, key length of 32 bytes or more, idempotency on PATCH).
11. Which features need the paid add-on (tagging and segmentation; metadata filters).
Then set `morning_note.sender.mode` (`stamp` or `ids`) by PR. If neither mode passes, stop and return to the
architect.
**Done 2026-11-16** on the live newsletter (`daylight`, free plan, team addresses only): `stamp` works, `ids` cannot
(send-draft only previews), and the form refused `metadata__` fields on a new address, so the form posts tags.
Results and corrections to the probe file's manual answers: `docs/platform-facts.md` "Morning note provider".

## 4. Before the first send (team, by reviewed PRs)
1. T4.6 done (privacy text) and the launch preconditions of the architecture ("Launch preconditions" 1 to 9)
   checked, each with a link in the PR. Seat consent is moot since 2026-11-18 (the form posts no seat).
1b. **One edition (2026-11-18): tasks N1 to N5 of `docs/tasks/morning-note-one-edition.md` merged** (sender
   `mode: all`, the form posting only the address, their security review). Until then the shipped sender still
   plans per-tag editions, and a live run would stop as `no-tags` (exit 2, nothing sent), because the free plan
   keeps no tags.
2. Add the site's host (`daylight.gnoshcodes.com`) to `morning_note.sender.link_hosts`; check each government source
   host in `link_hosts` for an open redirect and record the result in `docs/platform-facts.md`.
3. T4.8 security review of the T4.5 commit passed.
4. `morning_note.enabled: true` and `morning_note.sender.enabled: true`, with `canary_only: false` (Brian,
   2026-11-16: no canary week). The switch-on PR (branch `r2-note-on`) did this with `mode: stamp` and tags; task
   N1 sets `mode: all`.
4a. **The real sign-up on the live form.** Done 2026-11-18 (platform-facts "Morning note provider"): a team
   address with every list ticked was confirmed by double opt-in (verified) and got **no tags** (verified), which
   is why the note is one edition and the tag checks that stood here (each `note-<list>` and seat tag, and the
   unsubscribe-and-sign-up-again check behind the Method page's old `method_change` line) are dropped. Still to
   check, once N2 is deployed, with a team address not yet subscribed: the post (address only) lands on a
   buttondown.com page with no CSP error in the browser console; before confirming, the subscriber is
   `unactivated`; leave it unconfirmed through the first send and check it gets no note (an unfiltered email must
   skip unconfirmed addresses). Write each answer into `docs/platform-facts.md`. If the form answers an error,
   stop: `MORNING_NOTE_SEND` stays unset and the form goes back off by PR.
5. The site deploy is live (`RECORDS_DEPLOY_ENABLED` is `true`): the note job needs a successful deploy.
6. `main` is protected (step 2.0): `scripts/protect-main.ps1` (2.0.1) prints "OK: main is protected" (R1':
   code-owner review, squash only, admin bypass for pull requests only, approvals 0, auto-merge off), and the last scheduled run's `push` job merged its `data/` pull request
   into `main` under the ruleset. Link the check output and that PR in the go-live PR.
6a. **V1' probe passed (link)** (step 2.0.4, T4.11.7; the 2026-11-18 V1 probe was FAIL): the PASS output, the
   run link and the U2 and U3 positive controls are in `docs/platform-facts.md` "Main protection". Without the V1'
   PASS, `MAIN_PR_BASELINE` and `MORNING_NOTE_SEND` stay unset.
   And `github-pages` deploys from `main` only (step 2.0.5).
7. **The baseline `MAIN_PR_BASELINE` (T4.10.8; main-protect/pr-check-last-commit-only).** Set by the team the day
   the V1' probe passes (not at note go-live), after 2.0.5 and the gate's pull request merged; at note go-live this
   item is only the check in 7.3. It is in `.github/workflows/daily-update.yml`, the `env:` of the `gate` job's step
   "Check every change outside data/ reached main by a reviewed pull request a person merged", and is empty until then (phase 0: the gate checks nothing and passes with `verified=false`, so the note
   job never runs). Set to a commit that is not a 40-hex sha on `main`'s first-parent line, the gate fails every
   run. The gate checks every change outside `data/` after the baseline; the baseline stands for "a person checked
   everything up to here".
   1. `git fetch origin main`, then
      `git log --first-parent --format='%h %an %s' origin/main -- . ':(exclude)data/'` and read it: each
      change outside `data/` was meant (the earlier ones were merged without pull requests). `%an` is the commit's
      author and cannot show a bot merge (main-protect L-3), so also list who merged each such commit in the window
      that starts at `main`'s commit read just before 2.0.1 wrote the ruleset (architecture "Baseline window
      check", L-b; from then on only merged pull requests reach `main`): `<R2-on sha>` is the
      `R2 first on: <sha>` line in `docs/platform-facts.md` "Main protection" (from 2.0.1's
      `R2 was off; main was <sha>`). If 2.0.1 needed more than one run, the window starts at `main`'s sha before
      the **first** run (that run's `Main before the ruleset: <sha>`), not at a later run's
      (main-protect/window-start-gap). If 2.0.1's first run said `R2 already on`, the start is unknown: stop, the
      architect picks the window. Paste the whole output into the baseline PR:
      ```bash
      bash -s "<R2-on sha>" <<'WINDOW'
      set -euo pipefail
      start=$1; R=repos/gn0sh/clarksville-records
      known=3ef440aea9e5ce7374cdb789a05d646d74a91ac3; known_pr=40   # ADR 0010: the V1 probe's bot merge
      known2=2b207042a53e4d11dadfee978b029392df63c376; known_pr2=49   # the V1' probe's bot merge (2026-11-18)
      git fetch -q origin main
      [[ "$start" =~ ^[0-9a-f]{40}$ ]] || { echo "STOP: the start '$start' is not a 40-hex sha"; exit 1; }
      git merge-base --is-ancestor "$start" origin/main || { echo "STOP: $start is not an ancestor of origin/main"; exit 1; }
      list=$(git log --first-parent --format=%H "$start..origin/main" -- . ':(exclude)data/')
      n=0
      for c in $list; do
        pr=$(COMMIT=$c gh api "$R/commits/$c/pulls" --jq '[.[] | select(.merged_at != null and .base.ref == "main" and .merge_commit_sha == $ENV.COMMIT) | .number] | first // "none"') \
          || { echo "STOP: could not read the pull requests of $c"; exit 1; }
        t=none
        if [ "$pr" != none ]; then
          t=$(gh api "$R/pulls/$pr" --jq '.merged_by.type // "none"') || { echo "STOP: could not read pull request #$pr"; exit 1; }
        fi
        n=$((n + 1))
        echo "$c PR #$pr merged_by.type=$t"
        if [ "$t" = Bot ] && { { [ "$c" = "$known" ] && [ "$pr" = "$known_pr" ]; } || { [ "$c" = "$known2" ] && [ "$pr" = "$known_pr2" ]; }; } \
           && [ "$(git show --format= --name-only "$c")" = .github/workflows/v1-canary.yml ]; then
          echo "KNOWN EXCEPTION: $c is PR #$pr, a V1/V1' probe canary (only .github/workflows/v1-canary.yml); name it in the baseline PR"
          continue
        fi
        [ "$t" = User ] || { echo "STOP: $c was not merged by a person"; exit 1; }
      done
      echo "checked $n commits"
      [ "$n" -gt 0 ] || { echo "STOP: no commit in the window (a wrong or placeholder start: the gate's own PR at least is in it)"; exit 1; }
      WINDOW
      ```
      It must end `checked N commits` with N at least 1 and every line `merged_by.type=User`, with **two known
      exceptions (ADR 0010)**: 3ef440a, PR #40, the V1 probe's bot merge of `.github/workflows/v1-canary.yml` (V1
      FAIL, 2026-11-18), and 2b20704, PR #49, the V1' probe's bot merge of the same file (V1' FAIL, 2026-11-18). The
      block lets each of these through only if it is its own PR (#40, #49), merged by a `Bot` and
      changes nothing but that file, and prints `KNOWN EXCEPTION`; the person also checks that the canary-removal
      pull request (a later line, `merged_by.type=User`) removed it, and names both in the baseline PR.
      **Otherwise it stops on any `Bot`** (a workflow merged code: treat it as an incident, `MAIN_PR_BASELINE` stays empty), on `none` (no
      merged PR, which R1 should have made impossible), on any failed read, and on N = 0: a person reads why before
      anything else. Then `git rev-parse origin/main` prints the baseline sha.
   2. A PR that changes only `MAIN_PR_BASELINE: ""` to `MAIN_PR_BASELINE: "<that sha>"` (and makes
      `test_the_committed_baseline_is_unset_or_a_sha` accept only a sha), reviewed, merged with
      `scripts/merge-reviewed.ps1` (2.0.3). That PR comes after the baseline, so the gate checks it too. The same
      PR makes an empty baseline on `main` a refusal instead of phase 0 (main-protect L-1: otherwise a later PR
      resetting it to `""` reopens phase 0 silently); the exact change and tests are in `docs/tasks/morning-note.md`
      T4.10.8.
   3. Check (the day it merges, and again before setting `MORNING_NOTE_SEND`): the next Daily update run's `gate`
      job logs "Every change outside data/ on main after <baseline> was merged by a person, reviewed at its head:
      <n> commit(s)." and `update`, `push` and `deploy` are green. Link that run.
   Never move the baseline later except by a reviewed PR, after a person has checked every commit it skips.

## 5. Go-live: every confirmed subscriber (Brian; hard stop 1)
0. **No canary week (Brian, 2026-11-16, 8:56 PM CT).** At launch the note goes to every confirmed subscriber who
   signed up (`canary_only: false`, shipped by the switch-on PR), once Brian approves the sample note
   (`morning-note-sample/` in the project files). The canary path (`canary_only: true` with the
   `MORNING_NOTE_CANARY_IDS` secret) stays built and tested for later trials; the secret is not required.
   Two calls the runbook had tied to widening still need Brian's answer (team recommendation marked):
   - **A. Required reviewer on the `morning-note` environment: OFF (recommended) or ON.** Risk while OFF: a writer
     who can get a code PR onto `main` reaches the key, now with the whole list as the audience instead of the
     team's ids. Under R1' (ADR 0010, since 2026-11-18) that is a repository admin's bypass merge or a PR gn0sh
     approved as code owner; nobody, GitHub Actions included, can push `main` (the one bypass is the admin role for
     pull requests only), and the daily data goes by pull request (step 2.0). What still stands: the `main`
     ruleset R1' (pull request required, code-owner review outside `data/`, squash only, stale approvals
     dismissed, admin bypass for pull requests only), the gate (every code change a reviewed PR a person merged, after
     `MAIN_PR_BASELINE`), the note job's stale-run check, code review of every PR, and the one-edition plan check (2026-11-18; was `max_recipients` / `max_editions`). Why OFF: ON means Brian
     approves a deployment every morning between 03:07 and about 07:00 CT; a missed approval skips that day, and a
     run left waiting blocks the next day's data and deploy. If ON: the steps are below.
   - **B. Custom sending domain (SPF, DKIM): NO (recommended) or YES.** The free plan sends from Buttondown's own
     address; a custom domain costs money (a domain and, per Buttondown's pricing page, a paid plan: hard stop 3,
     and Brian will not pay). Risk of NO: mail comes from a Buttondown address, which may land in spam more often
     and reads less like "Daylight"; the From name stays the site name (section 1 item 1).
   Steps for the required reviewer, only if Brian answers A with ON:
   1. Open https://github.com/gn0sh/clarksville-records/settings/environments > **morning-note**.
   2. Under **Deployment protection rules**, tick **Required reviewers**, type your own GitHub username in the box
      and pick it. Leave **Prevent self-review** unticked (the scheduled run may count as yours, and you could not
      approve it). **Save protection rules**.
   3. Each morning after 09:07 UTC (03:07 CST): the email "Deployment review requested" (or Actions > **Daily
      update** > today's run) > **Review deployments** > tick **morning-note** > **Approve and deploy**. Approve
      before 7:00 site time to get that day's note (stamp mode schedules it for 7:00; after 10:00, `latest_send`,
      the note job stops with "missed").
   4. **Never leave a run waiting.** A run waiting for approval keeps the one-run-at-a-time group, so the next day's
      run (data, deploy and note) queues behind it. If you will not approve, click **Reject**: the note job fails,
      the "morning note failed" issue opens, nothing is sent, and the next run is free.
   5. To stop approving later: same page, untick **Required reviewers** > **Save protection rules**.
   Check: `gh api repos/gn0sh/clarksville-records/environments/morning-note --jq '.protection_rules[].type'`
   prints `required_reviewers` (and `branch_policy`).
1. **Brian**, only after section 4 is done (6a V1' PASS and 7 checked last), and after he approved the
   sample note: https://github.com/gn0sh/clarksville-records/settings/variables/actions > **New repository
   variable** > name `MORNING_NOTE_SEND`, value `true` > **Add variable**.
2. The next scheduled run (09:07 UTC) schedules the day's one email for 7:00 (site time zone) to every confirmed
   subscriber (`mode: all`, 2026-11-18); nothing on a quiet or backfill day.
3. The first mornings (until one clean week), a team member checks: the run's `note` job is green, its log shows
   totals only ("emails created 1"; no address, no id), every confirmed team address got the one note with every
   entry of the preview page (`morning/index.html`), in the same order (nothing on a quiet day), the unconfirmed
   address of section 4 item 4a got nothing, the links open live pages, the unsubscribe link works, and the
   Buttondown dashboard's recipient count for that email equals its number of confirmed subscribers.
4. `max_editions` is gone (2026-11-18: a plan holds at most one edition, so a run creates at most one email).
   `max_recipients` (1000) bounds only a `stamp` canary trial; `mode: all` reads no subscriber, and the free
   plan's 100-subscriber limit is the provider's own bound. A `mode: all` run is a few requests.

## Rules for manual runs and re-runs
- **Never re-run a Daily update run from an earlier day** ("Re-run all jobs" or "Re-run failed jobs" on yesterday's
  run). The run uses that day's workflow file, but the plan is built from today's `main`; the note job now stops with
  "an older run was re-run" when the sender code, config or workflow file differ. The whole re-run builds that
  day's commit (the gate's commit, main-protect L-A), so a re-run of a collecting run would also deploy that day's
  older site code with today's data. Start a new run with **Run workflow** instead.
  This matters most for runs from before the note job's current checks merged (note-job/rerun-predates-fix):
  GitHub lets a run be re-run for 30 days, with that day's older note job and weaker checks (no workflow-file
  diff, no gate). Either keep to this rule (and the required reviewer of section 5 step 0 holds such a
  run too), or set `MORNING_NOTE_SEND` no sooner than 30 days after the last change to the note job's checks merged.
- **Don't merge changes to `sender/`, `config/site.yml` or `.github/workflows/daily-update.yml` while a Daily update
  run is in progress.** The note job's stale check compares exactly those with `main` and would stop, and no note
  would be sent that day. Other `.github/` files are not compared (they still need a pull request: step 2.0).
- **Before you click Run workflow, open Actions. If a Daily update run is Queued, don't start one.** All runs share
  one concurrency group with one pending slot: a manual run queued then replaces the pending scheduled run (09:07
  UTC), and only a scheduled run sends the note, so that day gets no email.

## Rollback and stopping
- **Stop all sending (one step, Brian or anyone with admin):**
  https://github.com/gn0sh/clarksville-records/settings/variables/actions > `MORNING_NOTE_SEND` > **Delete** (or
  set it to `false`). The next run skips the `note` job. Nothing else changes; the site and data keep updating.
- **Stop today's email before 7:00 (stamp mode):** delete the variable `MORNING_NOTE_SEND` first (above), then
  delete the scheduled emails: in Buttondown, Emails > Scheduled > open today's emails (their metadata `note_date`
  is today) > **Delete**. Deleting the variable first means no later run can recreate them.
- **In code:** a PR setting `morning_note.sender.enabled: false` makes every `--live` a dry run.
- **Key leak or rotation:** Brian deletes the key in Buttondown (Settings > API), then replaces the
  `BUTTONDOWN_API_KEY` environment secret. Never rotate between a day's first run and 7:00 (the scheduled stamp
  emails would match nobody).

## When the note job fails
The issue "Daily update: morning note failed" opens (or gets a comment). The site, the data commit and the deploy
are not affected. Open the run's `note` job log: the deliver stage prints a fixed reason and its exit code
(2: a check failed, nothing sent; 3: "missed", past `latest_send`, nothing sent). A note is never sent the next day:
the records are on the site and in the feeds. Do not re-run the job after 10:00 site time, and never re-run a run from an earlier day. A
cancelled `note` job opens the same issue. A failure in "Download the morning note plan", "Validate the plan files"
or "Check the plan" means the plan from the update job was missing or did not pass the checks: look at that run's
"Plan the morning note" step. A failure in "Check this commit's sender and config are main's" means an older run was
re-run, or a change to `sender/`, `config/site.yml` or the workflow file merged during the run (see "Rules for
manual runs and re-runs"): nothing was sent.
A note job skipped with the gate green but `verified` false means phase 0 (`MAIN_PR_BASELINE` empty) or a run not
on `main`: nothing to fix until section 4 item 7.

## When the gate fails
The issue "Daily update: main history check failed" opens (or gets a comment). Nothing was built, deployed or sent;
the live site keeps its last deploy and the data waits for the next run. Open the run's `gate` job log; it says one of:
- `MAIN_PR_BASELINE` is not a sha, not on `main`'s first-parent line, or no commit after it changes anything outside
  `data/`: the baseline PR was wrong. Fix it by a PR merged with `scripts/merge-reviewed.ps1` (2.0.3).
- A commit (its sha is in the log) is not the merge of exactly one PR into `main`; was merged by a bot or with no
  `merged_by`; is a merge whose merged-in side is not the PR's head; or has no review of the PR's head by the owner
  or a collaborator before the merge. Read that commit first (`git show <sha>`, and its PR page): who merged it, how, and what it
  changed. A later pull request does **not** clear it: the gate refuses on every run until the baseline moves past
  it. If it was meant (for example a PR merged with the Merge button instead of 2.0.3): a person reads its whole
  diff, then a PR merged with `scripts/merge-reviewed.ps1` sets `MAIN_PR_BASELINE` to `main`'s commit at that time
  (as in section 4 item 7). If it was **not** meant (a workflow or someone merged code nobody reviewed): treat it
  as an incident; delete the variable `MORNING_NOTE_SEND`, and do not move the baseline until it is understood.
- "data/ must hold only regular files with plain names ending .json or .yml, or named changes.jsonl (I-data): <m>
  of <n> entries fit." (it checks on every run on `main`, phase 0 included), after up to 20 lines
  "not allowed in data/: <entry>" (mode, object and name; any byte outside plain ASCII shown as `?`). A symlink,
  submodule, executable file, a name with a space, a leading dot or a non-ASCII byte, or any other name under
  `data/` is never something the collector writes. Read the commit that added it (`git log --first-parent -- data/`
  on `main`, then `git show <sha> --stat`) and treat it as an incident if nobody meant it; otherwise remove it by a
  PR merged with `scripts/merge-reviewed.ps1`.
- "data/ is not a folder in this commit (missing, a file or a link), or could not be read (I-data)." `data/` was
  deleted, emptied or replaced by a file or link (a data PR merged from an empty refresh, or a hand edit). Restore it
  from the last commit whose `data/` was good, by a PR merged with `scripts/merge-reviewed.ps1`:
  `git fetch origin main`, `git log --first-parent --format='%h %s' origin/main -- data` and pick the newest commit
  before the bad one (`<good>`); then on a new branch from `origin/main`: `git rm -r -q --cached data; rm -rf data;
  git checkout <good> -- data`, commit "Restore data/ from <good>", open the PR, review it, merge it with 2.0.3. The
  next run collects again on top of it. If the same thing repeats, treat it as an incident.
- "could not read data/ in this commit's tree.", "could not check data/'s names.", "could not read main's full
  history." or a GitHub API error: re-run the failed jobs once; if it repeats, tell the team.
