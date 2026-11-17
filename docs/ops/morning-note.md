# Morning note: runbook (T4.7)

The morning note is the daily email built from `build/site/morning/<D>.json` (architecture:
`docs/architecture/morning-note.md` "T4 sender"; tasks: `docs/tasks/morning-note.md` T4.0 to T4.8). This page is
the order of work from no account to a live send, and how to stop it. **Nothing on this page has been done yet.** The
team creates no account, key, secret, variable or environment; every step marked **Brian** is his (hard stops 1, 3
and 5).

## How it runs (`.github/workflows/daily-update.yml`)
- `update` job, step "Plan the morning note (dry run, no network)": `python -m sender plan --rehearse` every day,
  no secret, no network. It writes `build/morning-send/<D>/` (plan.json and the editions, no subscriber data) and
  uploads it as the `morning-send` artifact (2 days). `continue-on-error`: a plan failure never fails the daily
  job, the data commit or the deploy.
- `note` job: runs only when **all** of these hold, otherwise it is skipped:
  1. the run was started by the daily schedule (a manual "Run workflow" never sends);
  2. the run is on `main`;
  3. the repository variable `MORNING_NOTE_SEND` is exactly `true`;
  4. the `update` and `deploy` jobs both succeeded (so it never runs while the deploy is locked, and an email never
     links a page that is not live).
  Inside it: mask the canary ids, check out this run's commit (no token kept), stop if its `sender/`,
  `config/site.yml` or `.github/` differ from `main` (a re-run of an older run), stop unless every change outside
  `data/` on `main` after the baseline commit `MAIN_PR_BASELINE` was merged by a person's pull request (step 2.0; while the
  baseline is unset it always stops: section 4 item 7), Python with no pip step, stage `sender/*.py` and
  `config/site.yml` from the commit's git objects into a new folder outside the checkout (its sha256 digest is
  re-checked before each later Python step), download the plan to the runner's temp folder, check the files, a dry
  run that checks the plan, then the delivery. Every Python run is `python -I -S -c` with only that folder on
  `sys.path` and its staged `site.yml` as `--config`, so no file in the checkout can shadow a module or change the
  settings (docs/architecture/main-protect-invariant.md). `--live` is passed only when
  `MORNING_NOTE_SEND` is `true`. `permissions: contents: read` and `pull-requests: read` only (the job's
  `GITHUB_TOKEN` is given to the pull request check only). `BUTTONDOWN_API_KEY` is given to that last step only.
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
   and the sign-up form posts Buttondown **tags** instead (`note-zoning`, `note-district-5`, ...; 2026-11-17). Do
   **not** add `canary` or `note_edition` (canaries are ids in a secret; the stamp is written by the sender only).
7. **Brian:** Settings > API > New key: a **scoped** key, never the primary key. Emails: write. Sending: write.
   Subscribers: write for `stamp` mode, read for `ids` mode (set after the T4.0 probe). Every other area: none.
   Copy it once; it goes straight into the GitHub secret in step 2.3 and nowhere else (not a file, chat or issue).

## 2. GitHub settings (Brian, once; nothing runs yet)
0. **Brian: protect `main` first** (security-note-workflow M1, main-protect/actions-bypass-reopens-M1,
   note-key/writer-reach-whole-list). **Changed 2026-11-17: the ruleset has no bypass.** The daily `data/` commit
   now reaches `main` by its own pull request (the "Fallback" below is what the team built), so nobody, GitHub
   Actions included, can push `main` directly.
   **Plainly: anyone with write or admin access to this repository can reach the Buttondown key.** The ruleset
   below does not change that. With 0 required approvals a writer can open a pull request that changes the workflow
   and merge it themselves. The `morning-note` environment's "main only" rule (step 2.2) only says *which branch*
   may use the secret, not who changed it. So:
   - **Keep collaborators to the minimum** (https://github.com/gn0sh/clarksville-records/settings/access): every
     person or app with write access is someone who can reach the key. Add nobody for the morning note.
   - **The ruleset is accident prevention plus an audit trail**, not a lock: it stops every direct push and force
     push (no bypass), and it makes every change to `main` show up as a pull request. The note job adds a check on
     top: it refuses to send unless **every** commit on `main`'s first-parent line after the baseline
     `MAIN_PR_BASELINE` that touches anything outside `data/` is the merge of a pull request into `main` **merged by
     a person** (step "Check sender, config and workflow changes reached main by pull request"), so a later pull
     request never hides an earlier direct push, and a code PR merged by a bot (a workflow using `GITHUB_TOKEN`) is
     refused. The baseline is set once, at go-live (section 4 item 7); until then it is empty and the check refuses
     every send. The team merged earlier work without pull requests; **from go-live on, every change outside
     `data/` reaches `main` by a pull request merged with "Create a merge commit" or "Squash and merge"** (not
     "Rebase and merge": a rebased commit other than the last one is refused).
   - **The daily `data/` pull request.** The `push` job commits `data/` on a branch
     `data/<date>-run<run id>-<attempt>`, opens a pull request to `main` and squash-merges it with `GITHUB_TOKEN`
     (0 required approvals, so the ruleset allows it), then deletes the branch. Before merging it checks GitHub's
     copy of that PR: open, into `main`, from this run's branch and commit, and every file it adds, changes, removes
     or renames (both names) is under `data/`. Anything else fails the job loudly ("Daily update failed" issue) and
     leaves the PR unmerged: close it unmerged; the next run commits fresh data. The merge is pinned to the checked
     commit, so a push to the branch after the check makes the merge fail. These PRs touch only `data/`, so the
     note job's check skips them. A PR opened by `GITHUB_TOKEN` starts no other workflow (no workflow here listens
     to pull requests anyway).
   - What stops a writer who goes around all of this (merging their own code PR, or a pushed workflow that drops
     the PR check) is a person: the optional required reviewer on the `morning-note` environment (section 5,
     step 0), which holds every job that would get the key until Brian approves it.
   - **Gap closed by the no-bypass ruleset (main-protect/ff-push-marks-pr-merged):** GitHub may mark an open pull
     request as merged when its head commit is pushed straight to `main`. With no bypass nobody can push `main`, and
     a commit GitHub marked that way after a push by the Actions bot is refused by the "merged by a person" test.
     It reopens only if the ruleset is disabled or a bypass is put back: then treat a pull request shown as merged
     that nobody merged on its page as a direct push ("When the note job fails").
   `main` takes changes by pull request only; the daily `data/` commit is a pull request too.
   **Order:** the pull request that made the `push` job open data PRs must be on `main` first (the scripts below
   check this and change nothing otherwise); the old job pushed `main` directly and would fail under this ruleset.
   1. **Brian, from a terminal (recommended: one command does all of 2.0).** Prerequisite, once: install GitHub
      CLI (`winget install GitHub.cli`), then **open a new PowerShell window** so `gh` is found, and run
      `gh auth login`, signed in as the repository owner. Get the repository (once): `gh repo clone
      gn0sh/clarksville-records; cd clarksville-records`; if you already have it, `git pull` in that folder. Then,
      in PowerShell in that folder, one line:
      ```
      powershell -ExecutionPolicy Bypass -File scripts\protect-main.ps1
      ```
      (macOS or Linux: `bash scripts/protect-main.sh`.) It (a) stops with "Main does not have the data pull request
      change yet. Nothing was changed." if `main`'s workflow still pushes `main` directly; (b) turns on **Allow
      GitHub Actions to create and approve pull requests** (Settings > Actions > General > Workflow permissions);
      (c) creates the ruleset from `scripts/main-ruleset.json` (no bypass), or, if a ruleset named `main: pull
      request required` already exists, updates that one, which also removes any bypass it had (running it twice
      never makes a second ruleset); (d) prints **OK: main is protected** (rules on main
      `deletion,non_fast_forward,pull_request`, the ruleset `active`, `bypass none`, and `GitHub Actions may create
      pull requests: true`), or **NOT OK** with what it found: send that output to the team.
   2. **Or by hand, in the browser** (only if the terminal is not an option):
      1. https://github.com/gn0sh/clarksville-records/settings/actions > **Workflow permissions** > tick **Allow
         GitHub Actions to create and approve pull requests** > **Save**.
      2. https://github.com/gn0sh/clarksville-records/settings/rules: if `main: pull request required` is listed,
         open it, and under **Bypass list** remove **GitHub Actions** (the **...** or **x** next to it) so the list
         is empty, then **Save changes**. If it is not listed: **New ruleset** > **New branch ruleset**, name
         `main: pull request required`, **Enforcement status** **Active**, **Bypass list** left empty, **Target
         branches** > **Add target** > **Include default branch**, tick **Restrict deletions**, **Block force
         pushes** and **Require a pull request before merging** (required approvals: 0, since Brian is the only
         reviewer with write access; the team's review is the PR review). Leave every other rule off (no required
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
   - **If the merge is refused under the ruleset:** set the ruleset's Enforcement to **Disabled** (data collection
     resumes: the PR is still opened, and can be merged by hand), and tell the team. CODEOWNERS plus "require review
     from Code Owners" on its own is **not** a fix: it only applies to pull requests. A write-access deploy key as a
     bypass actor would also work but is a new secret (hard stop 5); not recommended.
   - Until this check passes, the note job must stay off (`MORNING_NOTE_SEND` unset): section 4 item 6.
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
1. T4.6 done (privacy text, seat consent) and the launch preconditions of the architecture ("Launch
   preconditions" 1 to 9) checked, each with a link in the PR.
2. Add the site's host (`daylight.gnoshcodes.com`) to `morning_note.sender.link_hosts`; check each government source
   host in `link_hosts` for an open redirect and record the result in `docs/platform-facts.md`.
3. T4.8 security review of the T4.5 commit passed.
4. `morning_note.enabled: true` and `morning_note.sender.enabled: true`, with `canary_only: false` (Brian,
   2026-11-16: no canary week). The switch-on PR (branch `r2-note-on`) does this, with `mode: stamp` and the form
   posting tags.
4a. **One real sign-up on the live form, after the switch-on PR is deployed** (a team member, a team address that
   is not yet subscribed; launch precondition 5): fill in the Alerts page form with two lists ticked and saved
   seats included. Check, and write each answer into `docs/platform-facts.md` "Morning note provider": the post
   lands on a buttondown.com page (no CSP error in the browser console); a confirmation email arrives (double
   opt-in); before confirming, the subscriber is `unactivated` in Buttondown; after confirming, it shows exactly the
   tags `note-<list>` for each ticked list plus `note-district-<n>` and `note-ward-<n>`. If the form answers an
   error or the tags are missing, stop: `MORNING_NOTE_SEND` stays unset, and the form goes back off by PR.
5. The site deploy is live (`RECORDS_DEPLOY_ENABLED` is `true`): the note job needs a successful deploy.
6. `main` is protected (step 2.0): `scripts/protect-main.ps1` (2.0.1) prints "OK: main is protected" (no
   bypass), and the last scheduled run's `push` job merged its `data/` pull request into `main` under the ruleset.
   Link the check output and that PR in the go-live PR.
7. **Set the baseline `MAIN_PR_BASELINE` (last item of the go-live list; main-protect/pr-check-last-commit-only).**
   It is in `.github/workflows/daily-update.yml`, the `env:` of step "Check sender, config and workflow changes
   reached main by pull request", and is empty until now: while it is empty, not a sha, or not a commit on `main`'s
   first-parent line, the note job refuses every send. The note job checks every change outside `data/` after the
   baseline; the baseline stands for "a person checked everything up to
   here".
   1. After every other PR of this list has merged: `git fetch origin main`, then
      `git log --first-parent --format='%h %an %s' origin/main -- . ':(exclude)data/'` and read it: each
      change outside `data/` was meant (the earlier ones were merged without pull requests). Then
      `git rev-parse origin/main` prints the baseline sha.
   2. A PR that changes only `MAIN_PR_BASELINE: ""` to `MAIN_PR_BASELINE: "<that sha>"`, reviewed, merged with
      "Create a merge commit" or "Squash and merge". That PR comes after the baseline, so the note job checks it too.
   3. Check before setting `MORNING_NOTE_SEND`:
      `git fetch origin main; git log --first-parent --format=%H <baseline>..origin/main -- . ':(exclude)data/'`
      lists that PR's commit (and any later ones); for each sha,
      `gh api repos/gn0sh/clarksville-records/commits/<sha>/pulls --jq '.[].merge_commit_sha'` prints the same sha.
   Never move the baseline later except by a reviewed PR, after a person has checked every commit it skips.

## 5. Go-live: every confirmed subscriber (Brian; hard stop 1)
0. **No canary week (Brian, 2026-11-16, 8:56 PM CT).** At launch the note goes to every confirmed subscriber who
   signed up (`canary_only: false`, shipped by the switch-on PR), once Brian approves the sample note
   (`morning-note-sample/` in the project files). The canary path (`canary_only: true` with the
   `MORNING_NOTE_CANARY_IDS` secret) stays built and tested for later trials; the secret is not required.
   Two calls the runbook had tied to widening still need Brian's answer (team recommendation marked):
   - **A. Required reviewer on the `morning-note` environment: OFF (recommended) or ON.** Risk while OFF: a writer
     who merges their own code PR (0 approvals) reaches the key, now with the whole list as the audience instead
     of the team's ids. (The direct-push gap through the Actions bypass is closed: since 2026-11-17 the ruleset has
     no bypass and the daily data goes by pull request, step 2.0.) What still stands: the `main` ruleset (pull
     request required, no bypass), the note job's checks (stale run, PR check merged by a person,
     `MAIN_PR_BASELINE`), code review of every PR, and `max_recipients` / `max_editions`. Why OFF: ON means Brian
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
1. **Brian**, only after section 4 is done, its item 7 (`MAIN_PR_BASELINE`) last, and after he approved the
   sample note: https://github.com/gn0sh/clarksville-records/settings/variables/actions > **New repository
   variable** > name `MORNING_NOTE_SEND`, value `true` > **Add variable**.
2. The next scheduled run (09:07 UTC) schedules the day's emails for 7:00 (site time zone) to every confirmed
   subscriber whose lists have something new; nothing on a quiet or backfill day.
3. The first mornings (until one clean week), a team member checks: the run's `note` job is green, its log shows
   totals only (no address, no id), the team's own addresses got exactly the editions their lists and seats call
   for (nothing on a quiet day), the links open live pages, the unsubscribe link works, and the Buttondown
   dashboard's recipient count matches the log's total.
4. `max_editions` is 400 (was 80 until 2026-11-17: a busy real day plans up to 191 editions, and 80 would have
   sent nothing that day; basis in architecture "Switch-on"). Revisit `max_recipients` (2000) before the list passes
   about 1,000: a run over either sends nothing that day (loud), and 2,000 stamped subscribers take about 14 minutes,
   close to the note job's 15-minute timeout.

## Rules for manual runs and re-runs
- **Never re-run a Daily update run from an earlier day** ("Re-run all jobs" or "Re-run failed jobs" on yesterday's
  run). The run uses that day's workflow file, but the plan is built from today's `main`; the note job now stops with
  "an older run was re-run" when the sender code, config or workflow file differ. Only the workflow file is the old version: the
  `update` job checks out current `main`. Start a new run with **Run workflow** instead.
  This matters most for runs from before the note job's current checks merged (note-job/rerun-predates-fix):
  GitHub lets a run be re-run for 30 days, with that day's older note job and weaker checks (no workflow-file
  diff, no pull request check). Either keep to this rule (and the required reviewer of section 5 step 0 holds such a
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
A failure in "Check sender, config and workflow changes reached main by pull request" means either
`MAIN_PR_BASELINE` is unset or invalid (the log says so: section 4 item 7), or a commit on `main` after the
baseline that touches `sender/`, `config/site.yml` or `.github/` (its sha is in the log) is not the merge of a pull
request into `main`: someone or some workflow pushed `main` directly, or a PR was rebase-merged. Nothing was sent.
Find out who made that commit and why before anything else. A later pull request does **not** clear it: the job
refuses on every run until the baseline moves past it. If it was an honest mistake, a person checks that commit's
diff, then a reviewed PR (merge commit or squash) sets `MAIN_PR_BASELINE` to `main`'s commit at that time, as in
section 4 item 7.
