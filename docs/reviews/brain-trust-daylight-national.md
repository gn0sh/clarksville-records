# Brain Trust: daylight-national spec (c7cb106), 2026-11-19

Six members, each a separate opus/high subagent, independent first round, neutral brief. Devil's advocate: the Strategist.
Verdicts: Skeptic Fix First (near Rethink), Opponent Rethink, Budget Hawk Fix First, User Fix First, Operator Fix First,
Strategist Rethink as devil's advocate / Fix First honestly. No Go, so no pre-mortem round was needed.

## Chair's summary
**Where they agree (6 of 6):**
1. In M1 and M2 almost every visitor sees a column of "Not covered yet" with nothing to do, and the plan learns nothing
   about demand. "Request it" must be in M1.
2. Email capacity is the real blocker, not code. Buttondown's free plan is 100 subscribers, its pricing page lists
   "Tagging & segmentation +$9/month" (our Nov 18 test only proved tags are accepted on a form), Brian has said he is on
   the free plan and won't pay (platform-facts, Nov 16), and requesters stored as subscribers would eat the same seats
   Clarksville's morning note needs.
3. Coverage will be thin where people care most (school boards on BoardDocs, townships, small towns with scanned PDFs),
   and TL;DR Gov already runs the same "Legistar + Municode, request a city" model.

**Where they disagree:** whether to build national now at all. Opponent, Skeptic, Strategist and Budget Hawk all argue
the strongest alternative is "don't build national yet": prove Clarksville in January and capture demand with a
request box. The Operator and User accept building, with fixes. The "wait" side has the stronger argument on demand
(no marketing until January, so no signal), but Brian has already chosen to build, and most of the work below is
reversible engineering that needs no spend or new host. Chair's call: build demand capture and the hardened collector
now; gate opening new hosts and any email spend on evidence and Brian's OK.

**Top 3 changes, in order:**
1. M1 = address lookup + honest statuses + "Request it" + Clarksville/Montgomery County covered. Requests must not use
   Buttondown seats (anonymous per-body counter by default; optional "email me when it opens" only after the email
   decision). Owner: product-manager.
2. Decide email capacity before any national email work: one card to Brian (capped spend path, or no national email
   for now and per-body calendar/RSS feeds instead). Nothing national may take a seat Clarksville needs. Owner: manager.
3. "National collector" architecture task before any Legistar code: per-client block state on the shared
   webapi.legistar.com host (one 403 must not stop every body), "token required"/"API not enabled" as body states,
   429 = stale not "can't cover", own workflow and request budget, decoupled weekly send, show items only when the
   agenda is final, Census government flags (FUNCSTAT plus a hand table for CT, RI, MA, NY towns), only
   webapi.legistar.com on the allowlist (one host OK from Brian, not hundreds). Owner: software-architect.

**Strongest alternative, steelmanned:** "Don't build national now." Daylight's only defensible edge is depth (votes
checked against minutes, finance), which is local. A thin national agenda layer competes on breadth with funded or free
players. Ship Clarksville in January, add a "Want Daylight here?" box, and build readers only for bodies people ask for.
It doesn't fully beat the proposal because Brian wants the national product built now, and change 1 captures the same
demand signal while the reversible engineering proceeds. It wins if requests stay near zero after January: then
national stays shelved (see gate below).

**One question before moving forward:** will Brian fund national email (and at what ceiling), or should the national
site launch with no email at first?

## Members (condensed; full text in the thread run ledger)

SKEPTIC: Fix First (near Rethink). Pre-mortem: Request-it clicks fill Buttondown's ~100 free seats shared with Clarksville's morning note; both "full for now"; Brian won't pay (platform-facts: "free plan and will not pay, 2026-11-16"); pricing page lists tagging +$9/mo. Plan's answer to its biggest limit is a spend Brian already refused. Other: most of an address stays Not covered for good (BoardDocs/townships never reached; R5 OKs gate growth; 3+ requests weak with no marketing); "zero wrong facts" relies on one-time QA of 10 items; API text may differ from PDF; API returns only public items (partial agenda shown as complete); builds on unshipped morning note, unverified tag sends, no geocoder SLA. Fix: settle email capacity in writing before M1: card (a) capped spend path, or (b, rec if no pay) national sends no email: per-body RSS/ICS feeds from the JSON feed, request list off Buttondown (anonymous counter); no national feature takes a Clarksville seat. Alternative: don't build national yet; prove Clarksville (morning note, January launch, one quarter of metrics); cheapest national later = address lookup + ICS/RSS, no email.

OPPONENT: Rethink (scope/launch shape; rules + privacy hold). Biggest: first screen = column of "Not covered yet"; TL;DR Gov already runs the same model (Legistar + Municode APIs, "Request a City" ranked by asks) https://tldrgov.pages.dev/coverage/expand. Other: "No AI" is a missing feature to users; verbatim lines ("Resolution 2026-114") useless; we hold back Legistar votes others show; pull real Salem item titles to test. Letter = residents lobbying for our bot access ("astroturfing"); clerk often can't fix a vendor WAF; brand risk. Coverage lands where rivals already are (big cities); school boards/townships on BoardDocs/custom = uncovered; 100-sub cap. Fix: coverage gate: ~200 population-weighted random addresses run offline; no public link until share with >=1 Covered body passes Brian's threshold (~25%); show "covers about X% of Americans"; add "why Daylight vs TL;DR Gov/Hamlet/Citizen Portal" section. Alternative: go dense regionally ("Daylight Middle Tennessee", full Daylight with verified votes); publish readers/feeds openly; "don't build" defensible.

BUDGET HAWK: Fix First. Biggest: digest depends on Buttondown tags; pricing page lists "Tagging & segmentation $9/mo" add-on, free = first 100 subs, no price shown above; Nov 18 test proved tags accepted on a form, not that tag-filtered/conditional sends are free. Memo cost table ($9/$29/$139) is stale third-party. Other: paid part built before demand measured (Request it only in M3); real cost = usage bar + Brian's approvals (up to 3 OKs per body); per-body hand work never ends vs $0 income; letter = worst ratio, unmeasured. Fix: demand capture first: Request it in M1; letter out until a body has real requests; before M4 re-check pricing on the real account and card Brian "approve up to $X/mo at N subs"; stop rule: <~25 Legistar requests within 6 weeks of Jan launch = M2+ shelved. Alternative: finish Clarksville for Jan; add "Want Daylight here?" email field to existing address box for out-of-area results (~1 day, $0); build Legistar only for requested bodies.

USER: Fix First. Biggest: first visit for almost everyone ends with nothing to do: M1/M2 show "Not covered yet" with no button (AC2.2), so no demand data for two milestones. Other: verbatim agenda text unreadable (R3) vs Citizen Portal/Hamlet that already cover towns; school boards (BoardDocs, CMCSS) most likely missing; weak promises (3-request threshold, hidden counts, 100-sub cap, weekly digest misses late-posted agendas). Fix: move Request it into M1, honest confirmation ("we may never reach yours"), measure lookup->request rate. Alternative: covered-bodies list + "tell us your town" box until coverage is dense; address lookup is right at 500 bodies, wrong at 2. Sound: privacy design, letter only for gov-side gap, double opt-in.
Decisions: Request it to M1 (yes, PM); verbatim stays, test (ux); BoardDocs in platform order (architect); "agenda just posted" add-on (open, PM); covered list + request box for M1 (weigh, manager).

OPERATOR: Fix First. Biggest: collector/fetch.py keys block flag and 10 s delay on host (lines 30-31, 57, 345-352); every Legistar client shares webapi.legistar.com, so one 403/429 from one token client (e.g. NYC) stops all Legistar bodies and the probe. Other: daily schedule late/unreliable (cron 09:07 UTC; last 6 runs started 15:42-19:29 UTC, 3 of 6 failed; 44-80 min); ~30 s per body on shared host caps ~120 bodies/hour in the same job as Clarksville. collector/legistar.py ignores EventAgendaStatusName and EventTime (draft agendas shown as official breaks R1). Counties not governments in CT, RI, parts of MA; New England/NY towns are the government; TIGER yearly so annexations lag. One send with per-subscriber sections at hundreds of bodies likely breaks Buttondown size/render limits; tags may be $9 add-on; CAN-SPAM needs a postal address (not in sitegen/morning.py today); JSONP runs as script, CSP must allow, record accepted risk. Fix: architect task "national collector": per-client block state; token/not-enabled as per-body states; 429 or host-wide 403 = stale, never Can't cover; only webapi.legistar.com on allowlist (one OK from Brian, not hundreds; link PDFs, never fetch); separate workflow + concurrency group + per-run request budget; send decoupled from collection; show items only when agenda final; FUNCSTAT government flags + hand table for New England/NY/CT; recorded-fixture tests; add CT and New England test addresses. Order: cutover + morning note -> architect -> frontend + backend -> devops -> security -> QA. Brian's asks on one card: one host OK, tags spend, mailing address. Alternative: ship M1 + M3 only (lookup, statuses, request list, letter), Covered = Clarksville/MoCo; national collection only when requests name bodies.

STRATEGIST (devil's advocate): DA verdict Rethink; honest verdict Fix First. Biggest: scales the part with no edge (verbatim coming-up, which TL;DR Gov and Voterheads give away) while the edged part (verified votes, Clarksville) is unfinished; M1 tests nothing national (only user is Brian). Other: request list burns free seats (AC5.1) -> hard stop 3 as soon as it works; "website complete" undefined, M5 open-ended, so app gate never opens; lock-in to Granicus API policy and to Brian's per-body OKs; letter = residents lobbying for our access. Fix: M1 = address lookup + request list (US1, US2, US5); verify Buttondown cap/tag pricing on the real account, keep requesters out of the count if possible; build Legistar only if >=25 confirmed requests on supported platforms within 6 weeks; define "website complete" (e.g. M1-M4) so the app gate is fixed. Alternative: don't build national now; make Clarksville the best local records site, add a static request-your-area box in January, grow by neighboring TN counties.
(Manager: one point about the operator's council seat was dropped per the standing rule not to factor it in.)

## Decisions this changed
| Finding | Decision changed | Scope | Owner |
|---|---|---|---|
| First screen is all "Not covered yet"; no demand data | Yes: "Request it" moves to M1 | adds (small) | product-manager |
| Requesters would eat Buttondown seats Clarksville needs | Yes: anonymous per-body request counter by default | cuts email use | product-manager |
| Tags may be a paid add-on; free cap 100; Brian won't pay | Yes: email capacity decision card before national email | none now | manager (Brian decides) |
| One send with per-subscriber sections may break at scale | Yes: architect evaluates; per-body calendar/RSS feeds as fallback | adds (small) | software-architect |
| Shared-host block flag would stop all Legistar bodies | Yes: per-client state in national collector design | adds | software-architect |
| Draft agendas could show as official | Yes: show items only when agenda final; read EventAgendaStatusName/EventTime | adds | backend-engineer |
| Counties/towns not governments in New England, NY | Yes: government flags + hand table; CT and New England test addresses | adds | software-architect, qa-engineer |
| Late, failing daily schedule | Yes: national collection in its own workflow and budget | adds | devops-engineer |
| CAN-SPAM needs a postal address | Yes: add to email decision (LLC address) | none | manager (Brian decides) |
| JSONP runs as script | Yes: CSP allowance + recorded accepted risk | adds | security-engineer |
| "Website complete" undefined, so app gate never opens | Yes: define complete = M1 to M4 done | none | product-manager |
| Letter reads as lobbying for our bot access | Yes: letter asks only for records posted readably (open feed or text), never "unblock our reader"; stays M3 and only after real requests | cuts | product-manager |
| Verbatim agenda text can be unreadable | No (R3 stands); test real Legistar titles with users after M1 | none | ux-designer |
| School boards mostly uncovered | Yes: BoardDocs added to platform-order question | none now | software-architect |
| Go/kill gate on demand | Yes: no new hosts opened past Salem without at least a few real requests; review after January | cuts | manager |
| Weekly note misses late-posted agendas | Open: "agenda just posted" alerts considered after email decision | adds | product-manager |
| Coverage gate (share of Americans covered) before public link | Yes: compute offline, show the number honestly; public link waits for Jan launch anyway | adds (small) | product-manager |
