# Launch runbook: records.gnoshcodes.com on GitHub Pages

Owner: devops-engineer. Go-live is the CEO's hard stop 1: nothing below marked **CEO** happens without his go-ahead.
Repo: https://github.com/gn0sh/clarksville-records (public; Actions minutes are free). Workflow:
`.github/workflows/daily-update.yml` (daily 09:07 UTC and on demand).

## How it works
- `update` job: city collect, county collect + finance + site build, `qa.site_checks` (browser checks off in CI),
  `pytest`, commit refreshed `data/` to `main` if it changed, upload `build/site` (plus `CNAME`) as the Pages artifact.
  It never publishes. A failure opens one "Daily update failed" issue and leaves the live site as it was.
- `deploy` job: publishes the artifact. **Locked:** runs only when repo variable `RECORDS_DEPLOY_ENABLED` is `true`.
- Collection keeps the collector's rules: honest User-Agent, robots.txt, 10 s between requests per host.
- The downloaded PDFs (about 3 GB, not in git) live in the Actions cache (`records-store-v1-*`, 10 GB repo limit, evicted
  after 7 days unused; the daily run keeps it warm). A cold cache refetches about 930 documents at 10 s each: 3 to 5
  hours. The job limit is 355 minutes.
- Build overrides set by the workflow: `RECORDS_SITE_URL=https://records.gnoshcodes.com/` (feeds carry absolute links;
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
4. Pre-launch security checks the manager owns: fresh history secret scan, QA pass, CEO phone check.

## Go-live (CEO, about 5 minutes; do in this order)
1. Pages source. Open https://github.com/gn0sh/clarksville-records/settings/pages > Build and deployment > Source:
   **GitHub Actions** (replaces the gh-pages branch preview). Expected: the page shows "Your site is ready to be published".
2. DNS at Porkbun (https://porkbun.com/account/domains > gnoshcodes.com > DNS): add one record only:
   Type **CNAME**, Host **records**, Answer **gn0sh.github.io**, TTL 600. Leave every existing MX and TXT record alone.
   Check: `dig +short records.gnoshcodes.com CNAME` prints `gn0sh.github.io.` (a few minutes).
3. Custom domain. On the same Pages settings page, Custom domain: `records.gnoshcodes.com` > Save. Wait for the green
   "DNS check successful" (up to 15 minutes), then tick **Enforce HTTPS** (certificate issues within about an hour).
4. Enable the deploy lock: https://github.com/gn0sh/clarksville-records/settings/variables/actions > New repository
   variable, Name `RECORDS_DEPLOY_ENABLED`, Value `true`. (Or: `gh variable set RECORDS_DEPLOY_ENABLED --body true
   --repo gn0sh/clarksville-records`.)
5. Deploy now instead of waiting for 09:07 UTC: Actions > Daily update > Run workflow > main. With a warm cache it takes
   minutes. Collect = false rebuilds and deploys from the committed data with no fetching.
6. Look: https://records.gnoshcodes.com/ loads over HTTPS, footer shows the operator, alerts.html feeds link to
   `https://records.gnoshcodes.com/...`. Then do the uptime step below.

## Add to the uptime monitor (after the first deploy is live; devops, separate PR in gn0sh/gnosh-uptime)
Described diff for `monitor.config.json`, add one entry to `targets` (not applied; that repo is not touched here):
```diff
     { "name": "gnoshcodes.com", "url": "https://gnoshcodes.com/" }
+    ,{ "name": "Clarksville Records", "url": "https://records.gnoshcodes.com/" }
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
- **Take the site down:** Pages settings > Unpublish site (or set Source to None). DNS record can stay.
- **Domain trouble:** the site also answers at https://gn0sh.github.io/clarksville-records/ only while no custom
  domain is set; to fall back, remove the Custom domain in Pages settings.

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
- Two action pins (`actions/setup-python`, `actions/cache`) could not be verified from the build sandbox; the pre-launch
  dry run (step 2) proves them.
