# Brain Trust: Daylight public launch (2026-11-11)

Six members, opus/high, each answered alone from a neutral brief (`docs/reviews/brain-trust-launch-brief.md`). Devil's advocate: the Skeptic. Full answers below the chair's summary.

| Member | Verdict |
|---|---|
| Skeptic (devil's advocate) | Rethink (timing and disclosure, not the product) |
| Opponent | Fix First |
| User | Fix First |
| Operator | Fix First |
| Budget Hawk | Fix First |
| Strategist | Fix First (timing and disclosure) |

No member said Go, so no pre-mortem round was needed.

## Chair's summary
**Where they agree.**
- *Launch smaller* was the alternative every member steelmanned on their own: county (best verified) first; RPC either left out or shown only as a case finder until motion results can be confirmed.
- *Freshness is invisible*: county minutes end May 11 (the county posts late), RPC shows 370 "Not confirmed" chips, and nothing alerts when a source goes stale (uptime checks only that the page loads). (User, Operator, Budget Hawk, Opponent.)
- *Corrections need a GitHub account*, which breaks spec AC5.1 ("without an account"); `corrections.email` is empty. (Skeptic, Opponent, User.)

**The split, reported in full.** Three members (Skeptic, Strategist, Opponent) say the biggest risk isn't code: the owner sits on City Council until the end of 2026 (`docs/platform-facts.md:23`), his votes are in the data, and the site credits only "gnoshcodes LLC". The standing decision ("seat not a factor") rested on "he leaves before anything goes live" (spec:41), which a November go-live breaks. They want either the owner and his council service named on About, or go-live after his term ends. The other three didn't raise it, because their lenses didn't cover it. **The stronger side is the three**: this is a goal-level call, so it goes to Brian.

**Top 3 changes, in priority order.**
1. Decide on owner disclosure vs. a January go-live (Brian's call; the build continues either way).
2. Make the newest city data trustworthy: 69 of 83 roll calls from 2026 are unverified, 60 of them on one `attendance_verified` check. Add the G4 skew gate to the city build. Merge each official's totals into one consistent set (the User found contradictory counts on an official's page).
3. Freshness and operations: a per-body "data through" line on home and the RPC page; a data-age check that opens an issue; merge to `main` and get green scheduled runs (deploy still locked) before the review; fix the runbook rollback, which deletes the `records` CNAME instead of `daylight`; a corrections email address.

**Strongest alternative.** Launch county-only (votes 91% verified, plus finance, feeds and exports), with city and RPC added once they pass the same 90% and skew gates. It beats the plan on trust, because a first impression can't be redone. It loses on the goal: city council is where most residents live. The chair's view: keep the city if fix 2 lands by Friday; otherwise hold city votes back.

**One question first:** name the owner on the site, or wait until January?

## Decisions this changed
| Finding | Decision changed | Scope | Owner |
|---|---|---|---|
| Owner seated on council, unnamed | Yes: goes to Brian as a decision card | none until decided | manager / Brian |
| 2026 city roll calls 83% unverified | Yes: new task before Friday | adds | backend-engineer |
| No city skew gate (G4) | Yes: release block | adds | backend-engineer |
| Official totals contradict | Yes: fix | adds (small) | frontend-engineer |
| No freshness line or data-age check | Yes: add both | adds (small) | frontend + devops |
| Home heading names county only; RPC subtitle wrong; About says "private preview" | Yes: copy fixes | adds (small) | frontend-engineer |
| Runbook rollback deletes the wrong CNAME | Yes: fix | adds (small) | devops-engineer |
| Pipeline never run on `main` | Yes: merge after collector review + 2 green runs, deploy locked (runbook "Before launch", no CEO step) | none | devops-engineer |
| Corrections need GitHub | Yes: add a corrections email to Brian's go-live list | adds (small) | manager |
| Brief listed email note as a launch feature; runbook says off | No: email stays off at launch per the runbook; brief corrected | none | manager |
| Scheduled workflows auto-disable after 60 days | No: track after launch (medium confidence, check) | none | devops-engineer |
| Weekly upkeep cap, "paused since" rule | Yes: write one rule in the runbook | adds (small) | manager |
| RPC shown as case finder only | No: already held; revisit with the Nov 18 RPC re-plan | none | architect |
| "Daylight" trademark check; clerk courtesy notice | No: already on Brian's go-live list | none | manager |

---
# Skeptic (devil's advocate): Daylight public launch

**Verdict: Rethink (the timing and the operator disclosure, not the product).**

**Most serious problem.** Pre-mortem headline: "Sitting council member secretly ran 'independent' site publishing his colleagues' votes." The plan launches mid-November, but Brian sits on City Council until the end of 2026 (docs/platform-facts.md:23). The premise that he leaves "before anything goes live" (config/site.yml:42, docs/status.md:235) is false on these dates. Meanwhile the site names no person, and the Who-runs-this copy dropped "any official" from its list of who does not run it (old wording: docs/reviews/unofficial-status-audit-2026-11-10.md:15; now: site/templates/who.html.j2:6). Two earlier panels made disclosure of his council service a decision (docs/reviews/brain-trust-round2.md:38). That decision has been quietly reversed. TN LLC filings are public, so this anonymity lasts one records search (judgment call; check what the SOS filing shows, high confidence). A tip jar paid to his company worsens it. Check the city ethics code (unknown).

**Other issues**
- **Corrections need a GitHub account and are public.** AC5.1 requires "without an account" (docs/specs/clarksville-records.md:78). Claims about named officials become public issues, triaged by one person (launch-runbook.md "Notes").
- **Machine text under named officials.** Official pages quote about 20 s of Whisper transcript after each "called on" (site/templates/official.html.j2:55-56). That is AI-generated text attributed to named people, which strains the "no AI-written text" rule. The call-on misattribution family has already been hit twice (docs/status.md, 2026-11-09). Lawyer item 5 (video and derived-text terms) is open (unofficial-status-audit:88-95).
- **Fragile accuracy and operations with one owner.** RPC votes failed QA 77/78, and the re-plan is already at failure count 1 (status.md:32,40). A cold cache means a 3 to 5 hour refetch after 7 days of eviction (runbook). The "Daylight" trademark and map-reuse permission are unresolved (audit:88-95, status.md:119). Medium confidence that one of these surfaces in the first month.

**One fix I'd insist on before go-live.** Pick one, explicitly: (a) go live after Brian's seat ends in January, or (b) the Who-runs-this page names Brian, states his council service and its end date, and restores "not run by any official" only once that is true.

**Strongest alternative: launch smaller, later.** Publish county records, finance and CSV/JSON exports in January, after he leaves the council. City Council pages, transcripts and RPC votes follow once their accuracy families close. County data carries no conflict and the most proven parsing (92%+ verified, 20/20 spot checks). A conflict story at launch would permanently discredit the "neutral" claim that is the product's only asset.

---
# Brain Trust, launch review: THE OPPONENT (2026-11-11)

Preview URL unreachable from my sandbox (proxy 403). I read the committed data at branch claude/project-thread-8xjro9 instead.

**Verdict: Fix First**

**Most serious problem.** The current City Council looks unreadable. 69 of 83 roll calls from 2026 are unverified (83%), versus 1,756 of 2,235 (79%) across all years, below the spec's 90% gate. So every sitting member's 2026 history is mostly "* Not confirmed". Some members hit the G4 skew line: Peters 53%, Brown 51%, Haywood 49%, against a crude all-years median of 18%. I found no skew gate in the city build. On day one, a council member screenshots their own page full of asterisks, and a reporter writes "new site can't read this year's votes." *Evidence: data/localities/clarksville-tn/facts.json, verification counts; spec AC-P1 and G4; `grep skew collector/city_build.py` finds nothing. High confidence on the numbers. The "same meetings" peer median is not computed, so check it.*

**Other issues**
- **Stale county data.** County minutes end 2026-05-11 (data/facts.json), six months behind, while our county agendas run to 2026-11-09 (data/county-agendas/agendas.json). Check whether the county has posted minutes since May. Coverage lines state the dates, but "out of date" is the first one-star review. *High.*
- **Corrections need a GitHub account.** corrections.email is "" and the only channel is GitHub issues (config/site.yml:56-57). That breaks AC5.1 ("without an account"). A resident must sign up for a developer site to report an error. *High.*
- **Who runs it.** "gnoshcodes LLC, no personal name" plus an owner who was on the City Council (status.md:235) is the HN or local-paper angle: "anonymous site run by a councilman grades colleagues." The TN SOS filing is public, so check what it shows. Also, about.html.j2:9 still says "private preview, no public address yet." *Judgment, medium-high.*

**One fix I'd insist on.** Before go-live, either get 2026 city roll calls to at least 90% verified (60 of the 69 failures are `attendance_verified`, which looks like one fixable pattern), or launch the city votes section only after that. Run the G4 skew gate on city data as a release block.

**Strongest alternative: launch smaller.** Launch the county only: commission votes at 91% verified, plus agendas search, finance and bids, feeds and exports. Add one email corrections address, and put the owner's name and his former seat on Who runs this. The city and RPC sections come later, once they pass the same 90% and skew gates. A smaller site that is all right beats a bigger one whose newest year is mostly asterisks, and the first impression can't be redone.

---
# Brain Trust, launch review: THE USER (resident seat)

Basis: the preview was blocked (proxy 403), so I built from committed data (as of 2026-11-07). If RPC data was rebuilt since, re-check the top point.

**Verdict: Fix First**

**Most serious problem.** The two questions residents arrive with ("what happened with the rezoning near me?", "how did my rep vote last month?") mostly dead-end. County votes stop at 2026-05-11 because the county posts minutes late (meetings.html shows six months as agenda only). Every Planning Commission motion is held: rpc/index.html says "none is shown confirmed", and rpc/meetings/2026.html carries 370 "Not confirmed" chips. A rezoning visitor gets a case with no outcome, only a PDF link. (Built output; high confidence.)

**Other issues**
- The home heading reads "Votes and records of the Montgomery County Commission" (config/site.yml:181), although the city, the RPC and finance are all in scope. A city renter reads that as "not for me". (High confidence.)
- Official pages contradict themselves. Joe Smith's page shows "329 confirmed roll calls with a recorded vote" and "354 confirmed roll calls", "29" and "36" not confirmed, and "absent at 5 of 64 meetings" next to "Absent: 25" (official.html.j2:17-50). Mismatched numbers read as untrustworthy. (High confidence.)
- Jargon the glossary doesn't cover: "roll call", "Attribution under review", "Fact id rc-92adf0a4-p18-0/...", and zoning codes like "AG/C-S to M-1" (glossary.html covers finance only). Corrections need a GitHub account (report.html). Search loads a 3.1 MB index on a phone (static/search-index.js). (Evidence; the effect on users is a judgment call, medium confidence.)

**Fix I'd insist on.** Add a plain freshness line for each body on the home page and the RPC page. For example: "County votes through May 11, 2026; the county has not posted later minutes. Planning Commission: agendas through Oct 27; vote results not shown yet." Rewrite the home heading to name everything covered. Merge each official's totals into one consistent set.

**Strongest alternative: launch smaller.** Ship county and city votes plus finance. Present the RPC only as a case finder: search a street, see its cases and agenda pages. The data is there: the search index holds case locations such as "1811 Madison Street". Leave outcomes off until they are confirmed. A first visit that meets 370 "Not confirmed" chips on the topic people care about most teaches residents the site has no answers. A smaller site that fully answers what it shows earns return visits.

---
# Brain Trust, launch review: THE OPERATOR

**Verdict: Fix First**

**Most serious problem.** The production pipeline has never run. GitHub's `main` is still the first commit (4908dbe, 2026-11-07); the branch is 743 commits ahead, `.github/workflows/` does not exist on `main`, and the only Actions runs are gh-pages preview builds (`gh api`, 2026-11-11). Runbook pre-launch steps 1-2 (merge; 3-5 hour cold seed vs a 355-minute limit; launch-runbook.md:50-52, 72-76) haven't started. Day one would be the collector's first run from GitHub datacenter IPs against all three source sites.

**Other issues**
- **The rollback steps delete the wrong DNS record.** Go-live creates CNAME `daylight` (launch-runbook.md:92). But "Take the site down" (:147-148), "Domain trouble" (:152) and step 0 (:86) all say delete the `records` CNAME. Following it under pressure leaves `daylight` dangling: the takeover case the runbook warns about.
- **Nobody is named to watch failures.** "Daily update failed", "RPC step failed" and city exit 5 ("ask the manager", :28-29) all go to GitHub issues in this repo. Agents never poll, and the uptime monitor (:131) checks that the homepage loads, not that data is fresh. A silent RPC backlog repeats daily "until someone acts" (:41-42). Judgment call, high confidence: stale data goes unnoticed for days.
- **The brief contradicts the runbook on email.** The brief lists the Buttondown note as a launch feature. The runbook says email is OFF (:107-110), and morning-note.md:5 says no Buttondown account, key or step exists yet; the sending domain may need a paid plan (:43, hard stop 3). Separately, both clarksvilletn.gov and CivicClerk disallow ClaudeBot by name (platform-facts.md:34-38, 121). The team's view that this doesn't cover our honest-UA collector (ADR 0003) should be stated on the Method page. Judgment call, medium confidence.

**One fix I'd insist on.** Merge to `main` now and complete two consecutive green scheduled runs, deploy still locked, before the Friday review. Then fix the rollback CNAME names and name who checks failure issues daily, plus a data-freshness check in gnosh-uptime.

**Strongest alternative: launch smaller and later.** Go live with county meetings, votes and finance only, which are the most-verified sources. Leave RPC out, not merely held as "Not confirmed" (it took 3+ review rounds and a QA fail on 2026-11-11), and leave email off and out of the brief. Flip DNS only after a week of green unattended daily runs. A civic-records site loses trust fastest with stale or wrong votes on day one; a quiet week costs nothing, since nobody is waiting.

---
# Budget Hawk: Daylight public launch

**Verdict: Fix First**

**Most serious problem.** The cash cost is about zero, but there is no limit on upkeep. Five source families go live (CivicClerk, Agenda Center, county clerk, county finance, RPC), with CMCSS on Nov 18. Building them took dozens of opus/high runs, and the rpc-votes re-plan has already failed review once (docs/status.md run ledger, 11-10 and 11-11). No plan caps the weekly agent effort for upkeep or says what happens when a source breaks.

**Other issues**
- **Stale data goes unnoticed.** gnosh-uptime only checks that the page loads (launch-runbook.md, uptime section). Failures land as GitHub issues that nobody is paged for, and the RPC backlog "repeats every day until someone acts" (runbook, RPC backlog). Nothing checks data age (a grep for stale/freshness found none). Confidence: high.
- **Scheduled runs can switch themselves off.** GitHub disables scheduled workflows in public repos after 60 days without repository activity, and a data commit only happens when data changed (daily-update.yml push job). To check: whether github-actions[bot] commits count as activity. Judgment call. Confidence: medium.
- **Recurring costs.** An evicted cache means a 3 to 5 hour refill against a 355-minute limit (daily-update.yml:48), and the refill grows with the corpus. A cold OCR cache redoes every scanned page. Email "may need the paid plan" for a sending domain (morning-note.md:42-43), a bill against tip-only income, and RSS already does alerts for free. Judgment call. Confidence: medium.

**Fix before go-live.** Show a "last collected" date for each source on the site. Add a check that opens an issue (or fails uptime) when any source is more than N days old. Write one rule: a broken source shows "paused since <date>" and gets fixed within a capped weekly agent budget, never as an unplanned opus emergency.

**Strongest alternative: launch smaller.** Launch only County Commission and City Council meetings and votes, with exports and RSS. These are the best-verified sources and most of the civic value. Hold RPC, which shows no confirmed motion results and has a backlog that needs a human every day, and hold finance until the core has run quietly for a few weeks. That halves the scrapers that can break, keeps "free forever" realistic for a one-person LLC, and lets real usage show whether RPC and finance are worth their upkeep.

---
# Brain Trust, launch review: THE STRATEGIST (2026-11-11)

**Verdict: Fix First** (the fix is about timing and disclosure, not code).

**Most serious problem.** The owner is a sitting Clarksville council member until the end of 2026 (`docs/platform-facts.md:23`), and his own votes are in the data (1,927 "Zacharias" hits in `data/localities/clarksville-tn/facts.json`). Yet the site credits only "gnoshcodes LLC", with "no personal credit" (`config/site.yml:16`). The spec's own premise was "he leaves it before anything goes live" (`docs/specs/clarksville-records.md:41`), and a Nov 15 launch breaks it. The repo is already public, and its docs name him as operator and council member. The first story could easily be "councilman secretly runs a site tracking his colleagues' votes." That undoes the neutrality promise. (Evidence: the cited lines. Reaction: judgment call, high confidence.)

**Other issues**
- **Source access is fragile and political.** The city added robots rules on 2026-10-21 (`platform-facts.md:34`). CivicClerk signals `ai-train=no` (`:121`). Our own rule is to stop on any block (spec AC4.3). One unhappy colleague asking city IT for a rule would freeze the council half for good. No relationship with either clerk exists before launch. Judgment call, medium confidence.
- **Weak first impression in the newest section.** Every RPC motion shows "Not confirmed" site-wide, transcripts cover 1 meeting, school board is a placeholder, and committees come Nov 18 (brief:5; `scope-gap-2026-11-10.md` items 8 and 9). Launch press happens once. High confidence.
- **Lock-ins.** The name "Daylight" has no trademark check (scope-gap item 1). Feed ids have already changed once (`one-week-finish.md`), and after launch subscribers pin URLs. The status notes plan a later paid national product (`docs/status.md` 11-09). A paid product spun off a "free public service" brand invites a "bait" reading, so decide now whether Daylight stays the free brand. Medium confidence.

**Fix I'd insist on before go-live.** Put one honest line on About: who owns gnoshcodes LLC, that he serves on City Council until his term ends, and that his record follows the same rules. The other option is to set go-live after his term ends. Either is fine. Launching while seated and unnamed is not.

**Strongest alternative: launch in January, after he leaves office.** About seven weeks costs little. December is probably a light meeting month (unverified: check the 2025 calendars), no rival offers per-member votes (spec:9), and the daily collector can keep running privately so nothing is lost. A January start lands with the new council term (judgment call, medium confidence). It also removes the conflict and leaves time to confirm RPC votes, check the name and give both clerks a courtesy notice.

---
