# One-week finish plan (target: Fri 2026-11-13 ready for Brian's review; go-live when he judges it matches his vision (Brian 2026-11-09); was Sun 2026-11-15, go-live on Brian's go-ahead)

Brian (2026-11-09): "a finished product for MoCo and Clarksville within a week." Priority: complete and on the web; the national any-ZIP product comes later (build nothing for it; keep locality data-driven).

## What "finished" means (manager decision, change if Brian disagrees)
1. County: votes, meetings, officials, items (done), finance and bids (done in preview v8), exports (CSV/JSON downloads).
2. City of Clarksville: City Council meetings, votes by name and minutes from CivicClerk (2024+) and the Agenda Center (2016 to May 2024), same neutral rules. Ward map only if a usable vector source turns up; otherwise a ward list.
3. Alerts v1: free feeds (RSS/Atom) per district, per ward and for zoning items, plus a "new agendas" page. Email sign-up is v2: it needs a sending service (an account and maybe cost, a hard stop) and stores people's emails.
4. Public launch gates: correction intake (a Report-an-error path that reaches Brian), fresh security review, public-launch Brain Trust (6), QA, Brian's phone check.
5. Hosting: public repo plus GitHub Pages at a gnoshcodes.com subdomain, scheduled collection on GitHub Actions (free for public repos). Going public is hard stop 1: Brian's explicit go-ahead.

## Schedule (one agent at a time where pacing requires)
- Mon 11/9 to Tue 11/10: city collector (Agenda Center now; CivicClerk once its hosts are allowed); finance exports; guard `collector run --offline`.
- Wed 11/11: city pages and votes, QA spot check; correction intake design and build.
- Thu 11/12: alerts v1 feeds; scheduled collection workflow; hosting setup on a branch.
- Fri 11/13: security review, public-launch Brain Trust, fixes.
- Sat 11/14: QA full pass, Brian's phone check (batched), final fixes.
- Sun 11/15: go-live on Brian's go-ahead.

## Needs Brian (batched)
- (Done 11/9) CivicClerk hosts allowed in the cloud environment.
- (YES, Brian 11/9) Collect City Council records from the CivicClerk portal.
- (YES, Brian 11/9) Public repo plus GitHub Pages at records.gnoshcodes.com, flipped at launch.
- Final go-live go-ahead (hard stop 1).
