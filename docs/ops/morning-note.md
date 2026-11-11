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
  Inside it: mask the canary ids, check out this run's commit (no token kept), Python with no pip step, download
  the plan to the runner's temp folder, check the files, a dry run that checks the plan, then
  `python -E -s -m sender deliver --plan ... --live`. `--live` is passed only when `MORNING_NOTE_SEND` is `true`.
  `permissions: contents: read` only. `BUTTONDOWN_API_KEY` is given to that last step only.
- `note-failed` job: when the `note` job failed, opens one issue titled **"Daily update: morning note failed"**, or
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
3. **Brian:** Settings > Subscribing: double opt-in **on** for form sign-ups.
4. **Brian:** Settings > Tracking: open tracking **off**, click tracking **off**.
5. **Brian:** Settings > Email: reply-to = a team address (not a personal one).
6. **Brian:** Settings > Metadata (subscriber fields): add `lists` (multi-select), `district` and `ward`. Do **not**
   add `canary` or `note_edition` (canaries are ids in a secret; the stamp is written by the sender only).
7. **Brian:** Settings > API > New key: a **scoped** key, never the primary key. Emails: write. Sending: write.
   Subscribers: write for `stamp` mode, read for `ids` mode (set after the T4.0 probe). Every other area: none.
   Copy it once; it goes straight into the GitHub secret in step 2.3 and nowhere else (not a file, chat or issue).

## 2. GitHub settings (Brian, once; nothing runs yet)
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
`docs/platform-facts.md` ("Morning note provider", with the date and who saw it). From the probe run with the
scoped key in a local shell variable, never in a file, a commit or a log:
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

## 4. Before the first send (team, by reviewed PRs)
1. T4.6 done (privacy text, seat consent) and the launch preconditions of the architecture ("Launch
   preconditions" 1 to 9) checked, each with a link in the PR.
2. Add the site's host (`daylight.gnoshcodes.com`) to `morning_note.sender.link_hosts`; check each government source
   host in `link_hosts` for an open redirect and record the result in `docs/platform-facts.md`.
3. T4.8 security review of the T4.5 commit passed.
4. `morning_note.enabled: true` and `morning_note.sender.enabled: true`, with `canary_only: true` (the default).
5. The site deploy is live (`RECORDS_DEPLOY_ENABLED` is `true`): the note job needs a successful deploy.

## 5. Go-live: Canary week (Brian; hard stop 1)
1. **Brian:** https://github.com/gn0sh/clarksville-records/settings/variables/actions > **New repository variable** >
   name `MORNING_NOTE_SEND`, value `true` > **Add variable**.
2. The next scheduled run (09:07 UTC) sends to the canary ids only (`canary_only: true`): stamp mode schedules the
   emails for 7:00 (site time zone); ids mode sends when the run ends.
3. Each morning of the canary week, a team member checks: the run's `note` job is green, its log shows totals only
   (no address, no id), the team addresses got exactly the editions their lists and seats call for (nothing on a
   quiet day), the links open live pages, the unsubscribe link works, and nobody outside the canary list got mail
   (the Buttondown dashboard's recipient count).
4. Widening: after one clean canary week, a reviewed PR sets `canary_only: false`. Revisit `max_editions` (80) and
   `max_recipients` (2000) in the same PR.

## Rollback and stopping
- **Stop all sending (one step, Brian or anyone with admin):**
  https://github.com/gn0sh/clarksville-records/settings/variables/actions > `MORNING_NOTE_SEND` > **Delete** (or
  set it to `false`). The next run skips the `note` job. Nothing else changes; the site and data keep updating.
- **Stop today's email before 7:00 (stamp mode):** in Buttondown, Emails > Scheduled > open today's emails (their
  metadata `note_date` is today) > **Delete**. A re-run of the same plan does not recreate them only if the day is
  still claimed; to be sure, also delete the variable first.
- **In code:** a PR setting `morning_note.sender.enabled: false` makes every `--live` a dry run.
- **Key leak or rotation:** Brian deletes the key in Buttondown (Settings > API), then replaces the
  `BUTTONDOWN_API_KEY` environment secret. Never rotate between a day's first run and 7:00 (the scheduled stamp
  emails would match nobody).

## When the note job fails
The issue "Daily update: morning note failed" opens (or gets a comment). The site, the data commit and the deploy
are not affected. Open the run's `note` job log: the deliver stage prints a fixed reason and its exit code
(2: a check failed, nothing sent; 3: "missed", past `latest_send`, nothing sent). A note is never sent the next day:
the records are on the site and in the feeds. Do not re-run the job after 10:00 site time. A failure in "Validate the
plan files" or "Check the plan" means the plan from the update job was missing or did not pass the checks: look at
that run's "Plan the morning note" step.
