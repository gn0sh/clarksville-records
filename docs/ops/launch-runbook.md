# Launch runbook: daylight.gnoshcodes.com on GitHub Pages

Owner: devops-engineer. Go-live is the CEO's hard stop 1: nothing below marked **CEO** happens without his go-ahead.
Repo: https://github.com/gn0sh/clarksville-records (public; Actions minutes are free). Workflow:
`.github/workflows/daily-update.yml` (daily 09:07 UTC and on demand).

## How it works
- `update` job: city collect, county collect + finance + site build, `qa.site_checks` (browser checks off in CI),
  `pytest`, upload the refreshed `data/` and `build/site` (plus `CNAME`) as artifacts. Read-only repo access, no
  persisted token (it parses downloaded PDFs). It never publishes.
- `push` job: the only job with `contents: write`; it commits the refreshed `data/` to `main` if it changed, and parses
  nothing. It validates the artifact first (only `*.json`/`*.yml`, no symlinks, 50 MB cap), commits on the SHA the
  `update` job built on, then rebases onto `main`: a concurrent edit to `data/` fails the job instead of being
  reverted. A failure in `update` or `push` opens (or comments on) one "Daily update failed" issue and leaves the live
  site as it was. Both `push` and `deploy` run on `main` only.
- `deploy` job: publishes the artifact. **Locked:** runs only when repo variable `RECORDS_DEPLOY_ENABLED` is `true`.
- Collection keeps the collector's rules: honest User-Agent, robots.txt, 10 s between requests per host.
- The downloaded PDFs (about 3 GB, not in git) live in the Actions cache (`records-store-v1-*`, 10 GB repo limit, evicted
  after 7 days unused; the daily run keeps it warm). A cold cache refetches about 930 documents at 10 s each: 3 to 5
  hours. The job limit is 355 minutes.
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
   `custom_branch_policies: true`.
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
   `https://daylight.gnoshcodes.com/...`. Then do the uptime step below.

## Add to the uptime monitor (after the first deploy is live; devops, separate PR in gn0sh/gnosh-uptime)
Described diff for `monitor.config.json`, add one entry to `targets` (not applied; that repo is not touched here):
```diff
     { "name": "gnoshcodes.com", "url": "https://gnoshcodes.com/" }
+    ,{ "name": "Clarksville Records", "url": "https://daylight.gnoshcodes.com/" }
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
