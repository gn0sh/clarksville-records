# Launch runbook: daylight.gnoshcodes.com on GitHub Pages

Owner: devops-engineer. Go-live is the CEO's hard stop 1: nothing below marked **CEO** happens without his go-ahead.
Repo: https://github.com/gn0sh/clarksville-records (public; Actions minutes are free). Workflow:
`.github/workflows/daily-update.yml` (daily 09:07 UTC and on demand).

## How it works
- `update` job: city collect, county collect + finance + site build, `qa.site_checks` (browser checks off in CI),
  `pytest`, upload the refreshed `data/` and `build/site` (plus `CNAME`) as artifacts. Read-only repo access, no
  persisted token (it parses downloaded PDFs). It never publishes.
- `push` job: the only job with `contents: write`; it commits the refreshed `data/` to `main` if it changed, and parses
  nothing. It validates the artifact first (only `*.json`/`*.yml` and the `changes.jsonl` change logs, no symlinks,
  50 MB cap), commits on the SHA the
  `update` job built on, then rebases onto `main`: a concurrent edit to `data/` fails the job instead of being
  reverted. A failure in `update` or `push` opens (or comments on) one "Daily update failed" issue and leaves the live
  site as it was. Both `push` and `deploy` run on `main` only.
- `deploy` job: publishes the artifact. **Locked:** runs only when repo variable `RECORDS_DEPLOY_ENABLED` is `true`.
  `deploy` needs both other jobs: `update` green, and `push` green too (so the site never goes live from data that is
  not on `main`). Only a manual run with collect = false, where there is nothing to commit and `push` is skipped,
  deploys without a push.
- Exit codes (shown in the failure issue as `city=` and `county=`). **Hard failure** (the Collect step fails: nothing
  is uploaded, committed or deployed; data/ on `main` and the live site stay as they were; one issue opens):
  - city: 2 a listing not read or fetch/parse failures, 5 a host or robots.txt refused the collector (403/429 and the
    like). On 5 do not re-run to "try again" and do not change the fetcher: read `build/city-report.json` in the run
    log and ask the manager.
  - county: 2 fetch/parse failures (votes or finance), 3 gate failure, 4 offline run refused.
- **RPC only** (not a failure of the run; one source must not freeze the daily refresh). The RPC step's codes are used
  only when everything else is ok, and the RPC files (`data/localities/cmc-rpc/`) are restored byte for byte unless
  the step succeeds, so the city, county and finance data still commit and deploy:
  - **Partial**: county 6, the RPC document store is still being filled (at most 40 requests to cmcrpc.com per run,
    robots.txt and the listing included). A `::warning::`; the next runs fill it on their own.
  - **RPC failed**: county 5 the RPC step failed (cmcrpc.com blocked us, listing not read, an RPC gate, a result that
    would shrink the RPC record, or an RPC backlog, below; reason in `build/run-log.json` `rpc`). A `::warning::` and
    one open "Daily update: RPC step failed" issue (a comment on it each later day, never a new issue). A 429 from
    cmcrpc.com is never retried in that run; the next try is the next day's run, so do not dispatch a manual run to
    "try again" the same day.
- **RPC backlog** (rpc-daily/stall-needs-human): the RPC failure says `TooManyNew` (more newly listed documents than
  one run may request) or "the cap of 40 requests ran out" with no stored gap filled. Neither clears by itself: it
  **repeats every day until someone acts**, because a daily run that cannot finish keeps no manifest entry. Recovery,
  capped like the daily step (40 requests per call, robots.txt crawl-delay obeyed, a 403/429 stops it): look at
  https://www.cmcrpc.com/documents/agenda-minutes/ first (did the site move its files?), then on a checkout of `main`
  with the store restored, run `python -m collector rpc fetch --limit 30` once a day until it no longer prints
  "documents still to fetch", then commit `data/localities/cmc-rpc/` (listing.json, manifest.json). The next daily
  run fetches any bytes its cache lacks as gaps and rebuilds rpc.json; the RPC issue can be closed when it is green.
- A failed fetch never deletes data: the RPC step is all or nothing on its committed files; a hard failure stops the
  push job, so no partial result reaches `main`; the document store and caches are only ever added to.
- Collection keeps the collector's rules: honest User-Agent, robots.txt, 10 s between requests per host.
- The downloaded PDFs (about 3 GB, not in git) live in the Actions cache (`records-store-v1-*`, 10 GB repo limit, evicted
  after 7 days unused; the daily run keeps it warm). A cold cache refetches about 930 documents at 10 s each: 3 to 5
  hours. The job limit is 355 minutes.
- The text layers and OCR readings (`data/text`, `data/ocr`, keyed by document sha256 and page) live in their own
  cache (`records-derived-v1-<hash of the tesseract and pdftotext versions>-<hash of collector/extract.py,
  collector/ocr.py, requirements.txt>-*`), restored before
  Collect and saved when it grew, even after a failed step, by the scheduled run on `main` only (a manual run, which
  may be on another ref, never saves it; it still saves the document store). A change to those files starts a fresh
  cache. A truncated text cache file is deleted and read again. A document
  whose hash is unchanged is never OCR'd again. Worst case per warm run: only documents first fetched in that run are
  OCR'd (RPC at most 38: 40 requests less robots.txt and the listing; county and city minutes as many as were newly
  posted, usually 0 to 3), each page at most once. A cold OCR cache (first run, or evicted after 7 days unused)
  re-OCRs every scanned page once, then keeps them.
- Build overrides set by the workflow: `RECORDS_SITE_URL=https://daylight.gnoshcodes.com/` (feeds carry absolute links;
  `alerts.site_url` in `config/site.yml` stays empty, so no config edit is needed at launch) and `RECORDS_BUILD_TARGET=pages` (3000-file cap)
  (the 500-file cap is the claude.ai preview limit; Pages has none).

## Before launch (devops, no CEO needed)
1. Merge this branch to `main` (scheduled workflows run only from the default branch). The first daily cron then
   runs by itself and does everything except deploy.
2. **Seed the cache early (Wed or Thu):** Actions > Daily update > Run workflow (branch `main`, collect = true). Expect 3 to
   5 hours cold. Confirm: green run, a "Daily update: refreshed records data" commit only if data changed, an artifact
   named `github-pages`, and no deploy job (skipped = the lock works).
3. Check the Pages environment is unprotected by default: `gh api repos/gn0sh/clarksville-records/environments/github-pages`
   (404 or no required reviewers). Optional: add the CEO as required reviewer there for a second lock.
   **Deployment branches: main only.** https://github.com/gn0sh/clarksville-records/settings/environments > github-pages >
   Deployment branches and tags > Selected branches and tags > add `main` (remove any other). Check:
   `gh api repos/gn0sh/clarksville-records/environments/github-pages --jq .deployment_branch_policy` shows
   `custom_branch_policies: true`, and
   `gh api repos/gn0sh/clarksville-records/environments/github-pages/deployment-branch-policies --jq '.branch_policies[].name'`
   prints only `main` (ci/pages-env-branch: a settings check only, nothing in the workflow changes; the deploy job's
   own `github.ref == 'refs/heads/main'` term is the first lock, this is the second).
4. Pre-launch security checks the manager owns: fresh history secret scan, QA pass, CEO phone check.

## Go-live (CEO, about 5 minutes; do in this order)
0. **Verify gnoshcodes.com** (once, before any DNS change): open https://github.com/settings/pages > Add a domain >
   `gnoshcodes.com` > add the TXT record it shows (host `_github-pages-challenge-gn0sh`) at Porkbun
   (https://porkbun.com/account/domains > gnoshcodes.com > DNS) > Verify. This stops anyone else claiming a dangling
   `records` CNAME. Expected: gnoshcodes.com shows as Verified.
1. Pages source. Open https://github.com/gn0sh/clarksville-records/settings/pages > Build and deployment > Source:
   **GitHub Actions** (replaces the gh-pages branch preview). Expected: the page shows "Your site is ready to be published".
2. Custom domain, then DNS, back to back (never leave the CNAME pointing at Pages with no custom domain set):
   a. On the same Pages settings page, Custom domain: `daylight.gnoshcodes.com` > Save.
   b. Straight away, at Porkbun > gnoshcodes.com > DNS > add one record only:
      Type **CNAME**, Host **daylight**, Answer **gn0sh.github.io**, TTL 600. Leave every existing MX and TXT record alone.
      Check: `dig +short daylight.gnoshcodes.com CNAME` prints `gn0sh.github.io.` (a few minutes).
3. Wait for the green "DNS check successful" on the Pages settings page (up to 15 minutes), then tick **Enforce HTTPS**
   (certificate issues within about an hour).
4. Enable the deploy lock: https://github.com/gn0sh/clarksville-records/settings/variables/actions > New repository
   variable, Name `RECORDS_DEPLOY_ENABLED`, Value `true`. (Or: `gh variable set RECORDS_DEPLOY_ENABLED --body true
   --repo gn0sh/clarksville-records`.)
5. Deploy now instead of waiting for 09:07 UTC: Actions > Daily update > Run workflow > main. With a warm cache it takes
   minutes. Collect = false rebuilds and deploys from the committed data with no fetching.
6. Look: https://daylight.gnoshcodes.com/ loads over HTTPS, footer shows the operator, alerts.html feeds link to
   `https://daylight.gnoshcodes.com/...`. The footer of every page, and the top of About, say the site is independent
   and unofficial (wording: `unofficial:` in `config/site.yml`; check: `qa.site_checks` line
   `unofficial/notice-on-every-page` must PASS). Then do the uptime step below.

## Before the morning note's email is switched on (not part of go-live; email is OFF)
`morning_note.enabled` stays `false` in `config/site.yml` at launch: the site sends nothing. Switching it on is a
separate CEO decision (provider pick, account, cost: hard stops 3 to 5). Every box below must be ticked first; they
come from `docs/reviews/security-review-morning-2b4796b.md`.
- [ ] **Double opt-in is ON at the provider** (finding 2). The form is an open cross-origin POST, so without it anyone
      can sign up someone else's address. Check: sign up a test address; no note arrives until its confirmation link
      is used. Owner: devops.
- [ ] **Open and click tracking are OFF at the provider** (finding 2). Check: a received note has no tracking pixel and
      its links go straight to daylight.gnoshcodes.com. Owner: devops.
- [ ] **`morning_note.page.sent_line` is extended** (finding 2) to say the provider also receives, like any website,
      the visitor's IP address and browser details, and that the saved district and ward go only while "Include my
      saved seats" is ticked. Keep `method_sent` on the Method page in step with it. Owner: technical-writer.
- [ ] The two settings above are recorded as verified, with the date and how, in `docs/platform-facts.md`.
- [ ] Every note carries the provider's unsubscribe link (the Method page says so: `page.method_unsubscribe`).
- [ ] `page.preview_lede` ("Nothing is emailed yet.") and `page.state_off` are reworded for a site that does send.
- [ ] One real submit from the built Alerts page reaches the provider's confirm page (finding 6): Chrome applies CSP
      `form-action` to the redirect after the POST. If it is blocked, fix the provider's redirect, never widen the CSP.
- [ ] `python -m qa.site_checks` passes on the enabled build, and `pytest tests/test_morning_page.py` passes: an
      enabled build has no "never sent anywhere" sentence (finding 1) and posts no seat unless the box is ticked
      (finding 3).
- [ ] The sender job and its API key have had their own security review (T4.8, at the T4.5 commit).

The sender itself (account setup, GitHub environment and secrets, the T4.0 probe, canary week, go-live and
rollback) has its own runbook: `docs/ops/morning-note.md`. Its `note` job is locked by the repository variable
`MORNING_NOTE_SEND` (unset today) and runs only after a successful deploy.

## Add to the uptime monitor (after the first deploy is live; devops, separate PR in gn0sh/gnosh-uptime)
Described diff for `monitor.config.json`, add one entry to `targets` (not applied; that repo is not touched here):
```diff
     { "name": "gnoshcodes.com", "url": "https://gnoshcodes.com/" }
+    ,{ "name": "Daylight", "url": "https://daylight.gnoshcodes.com/" }
   ]
```
(JSON needs the comma after the previous last entry; put it there rather than on a new line.)

## Rollback
- **Stop all publishing at once** (CEO or devops, 10 seconds): set `RECORDS_DEPLOY_ENABLED` to `false` or delete it:
  https://github.com/gn0sh/clarksville-records/settings/variables/actions . Daily runs continue to build and check but
  deploy nothing; the site stays as last deployed.
- **Bad data on the live site:** revert the "Daily update" commit on `main` (`gh pr create` a revert, or
  `git revert <sha>`), then Actions > Daily update > Run workflow with collect = **false**. That redeploys the
  reverted committed data without fetching.
- **Bad code:** revert the merge commit on `main`, run the workflow with collect = false.
- **Take the site down:** Pages settings > Unpublish site (or set Source to None), **then delete the Porkbun `records`
  CNAME** so it never dangles.
- **Domain trouble:** the site also answers at https://gn0sh.github.io/clarksville-records/ only while no custom
  domain is set; to fall back, remove the Custom domain in Pages settings **and delete the Porkbun `records` CNAME in the
  same sitting** (a CNAME with no custom domain set is a takeover risk, even with gnoshcodes.com verified).

## Retire the gh-pages preview (after the live site checks out; CEO says go, devops does it)
Old preview: branch `gh-pages`, https://gn0sh.github.io/clarksville-records/ (it redirects to the custom domain once
that is set). After go-live step 1 it is no longer served. Delete the branch (irreversible, so a CEO yes first):
`gh api -X DELETE repos/gn0sh/clarksville-records/git/refs/heads/gh-pages`
Do not touch it before then.

## Notes and known limits
- First daily deploy contains whatever `main` holds: merge the launch-ready branch first.
- Browser checks (`hscroll`, `row-height`, 390 px) need Playwright and are not run in CI (`--no-browser`): QA runs them
  by hand before launch (`qa/final.sh`); a daily data refresh does not change layout.
- Pushes made with `GITHUB_TOKEN` do not start other workflows, so the data commit never re-triggers this one.
- Feeds (claude/hu3mew-qa-majors): this release changes `updated` and `published` once on all 1,246 existing entries,
  from the meeting date at 00:00Z to the date the document was added (America/Chicago). Entry ids are unchanged, so
  readers do not re-alert; a reader that shows changed entries may mark them updated once. The county feed also gains
  13 agenda-only meeting entries, which push its 13 oldest minutes entries past the 50-entry cap.
- Corrections go to GitHub issues (`corrections.github_repo`). GitHub shows the issue form only once
  `.github/ISSUE_TEMPLATE/correction.yml` is on `main`; until then the link opens a blank issue prefilled by report.js.
  The form's `correction` label does not exist on the repo yet (manager: create it at go-live).
