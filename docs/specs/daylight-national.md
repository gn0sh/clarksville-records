# Spec: daylight-national (Daylight Digest, the national website)

Status: draft v2.3, 2026-11-19 (v2.3: AC4.6 moved to M2 after the B4 freshness decision; AC2.11 confirmed. v2.2: v2 plus UX proposals P1-P8 accepted, the architect's email "editions" decision and the
city-items finding; v2 was v1 plus Brain Trust and Focus Group findings and Brian's email capacity answer of 2026-11-18). Owner: product-manager. Priority: MVP is M1; the rest is ordered below. Product name: **Daylight Digest**
(Brian, 2026-11-18). "Daylight" alone still means the full Clarksville and Montgomery County site.
Decisions so far: `docs/expansion/national-kickoff.md`. Memo: `docs/expansion/national-digest-memo.md` (sections 1-3, 7,
8b, 8c, 9). Clarksville rules this keeps: `docs/specs/clarksville-records.md`. Sources: `docs/platform-facts.md`.
Research: `docs/research/national-open-facts-2026-11-19.md`.

## Goal
Anyone in the US can browse what Daylight Digest covers, or type their address and see every local government for
that spot (city or town, county, township or New England town, school district), each with a plain status. Covered
bodies show what is coming up, verbatim and linked to the official document. For the rest, the person can ask to be
emailed when it opens and still gets the official agenda page. Later milestones add a weekly email, per-body calendar
and RSS feeds, and a neutral letter asking a government to post records readably. Daylight Digest never sees the
address, shows the official record only, and has no AI text about named officials. Clarksville stays the full Daylight.

**Primary user:** anyone in the US following their own local governments (confirmed by CEO, 2026-11-18).

## Problem
Local agendas sit on hundreds of different sites. A resident has to know which bodies govern their address, find
each one's site, and check it every week. Existing services cover many places but mostly use AI summaries, which
have told towns things that did not happen (memo section 5). People want one place that tells them, from the
official record only, what their own governments will take up next, and tells them honestly what it can't cover.

## Users
- **Residents anywhere in the US** who want to follow their own city, county, township or school board.
- **Brian (CEO, operator)** approves every new host, every deploy, every send to real people and the letter wording.
- Not users now: journalists, campaigns, lobbyists, officials' staff. Nothing is built for them.

## Goals
1. A person sees what we cover without giving anything, and finds every local body for their address in one step,
   with an honest status for each.
2. For a covered body, they see the coming-up record, verbatim and linked.
3. Demand shows us where to build next (requests per body), with no marketing until January 2027.
4. Grow platform by platform (Legistar first), only where requests point, never by guessing or working around a block.
5. Zero wrong facts: nothing shown is ours to get wrong.

## Non-goals
- No iPhone or Android app until the website is complete (Brian's rule). "Website complete" means M1 to M4 are done.
  M5 is not part of it.
- No votes for any body outside Clarksville and Montgomery County unless checked against that body's minutes.
- No AI-written text about named officials, anywhere. No AI text in M1 at all.
- No scores, rankings, commentary, endorsements, campaign links, comments or user accounts.
- No lists of named officials, no officials' personal contacts, no bulk scraping of contacts.
- No state or federal bodies (Census returns congressional and state districts; we ignore them).
- No special districts (water, fire, transit): the Census geocoder does not return them.
- No marketing, ads or outreach before the January 2027 formal launch. No paid services without Brian's OK.
- No change to the content or sending of Clarksville's morning note from any national feature.

## Rules (every milestone; carried over from Clarksville)
- R1. Official record only. Every fact on a page or in an email links to its official source document.
- R2. Every body and every official is shown with the same layout, fields and ordering rule.
- R3. Text we write is fixed labels only. Agenda text is shown verbatim, never paraphrased or summarized.
- R4. Polite collection: obey robots.txt and any crawl delay, public pages only, stop on 403, 429 or a disallow,
  never retry by another route. A body that blocks us is shown as "can't cover". A rate limit or a block of a whole
  shared host (for example `webapi.legistar.com`) makes the data stale, never "can't cover" (see AC4.6).
- R5. No request to a new government's host until Brian types his OK in the thread (one OK can cover a listed batch).
- R6. No spend, no deploy and no email to real people without Brian (hard stops 1, 3, 4).
- R7. The address never reaches Daylight Digest. We keep only body IDs, topics, request tags and the email address,
  held by Buttondown (plus anonymous counts if the optional counter is built).
- R8. Demand gate: no new hosts are opened past Salem unless real requests name those bodies. The team reviews the
  counts after the January launch (open question 8).

## User stories and acceptance criteria
QA test addresses (kept in the test plan, real public places, not a person's home): one inside Clarksville city
limits, one in unincorporated Montgomery County, one in Salem, OR, one in Nashville (consolidated city-county), one in
a Virginia independent city, one in a state with township governments, one in Connecticut, one in a New England town
outside Connecticut (for example Massachusetts or Vermont), and one that does not exist.

### US0. Every page (every milestone)
- AC0.1 Every new page passes an automated accessibility scan with zero serious or critical issues, reads in order
  with a screen reader (real headings, real text), and stays usable at 200% zoom. Agenda items we show are page text.

### US1. Address entry and lookup (M1)
As a resident, I want to type my address and learn which local governments cover it, so that I don't have to work
it out myself.
- AC1.1 The address page has one address box and the privacy lines (US9) visible before the person submits.
- AC1.2 With the browser's network log open, submitting a test address sends it to `geocoding.geo.census.gov` only.
  No request to any Daylight host, analytics host, Buttondown, the request counter or any other host contains any
  part of the address (street number, street name, ZIP). QA checks all nine test addresses.
- AC1.3 The address never appears in the page URL, the page title, cookies, localStorage or sessionStorage before or
  after the lookup. Only body IDs may be saved on the device.
- AC1.4 No match: the page says "We couldn't find that address." with one line of tips and lets the person edit
  and retry. Nothing else is sent.
- AC1.5 More than one match: the page lists the matches and the person picks one. Nothing is sent until they pick.
- AC1.6 No answer from the Census in 15 seconds, or an error: the page says the Census lookup is not answering and
  offers Retry. It never guesses a place.
- AC1.7 The page shows the Census notice word for word: "This product uses the Census Bureau Data API but is not
  endorsed or certified by the Census Bureau."
- AC1.8 No account and no sign-in are needed to look up an address.
- AC1.9 On the entry page, in view without opening anything, directly after the address card and its privacy lines,
  one or two plain sentences say who runs Daylight Digest and who pays for it, and that it takes no ads and no
  political money (changed by digest-warmth, 2026-11-22: was "above the address box"; see A16). Brian confirms each fact in that line before M1 goes live. The line says
  nothing about the operator's personal roles.
- AC1.10 The address page links to the "What we cover" list (US12) next to the address card: the line directly
  under its privacy detail (changed by digest-warmth, 2026-11-22: was "above the address box"; see A16).

### US2. The list of bodies for that spot (M1)
As a resident, I want one list of every body that governs my address, each with a plain status, so that I know what
Daylight Digest can and can't show me.
- AC2.1 The list shows each local government the Census returns for the spot: the incorporated place (city, town,
  village), the county only where it is a working government, the county subdivision only where it is a working
  government (a township, or a town in New England or New York), and each school district (unified, elementary or
  secondary). Census designated places and congressional or state districts are never shown.
- AC2.2 Each government shows its Census name as the card title, the directory's board name (for example "City
  Council") on the next line where the directory has one, and exactly one of three states. User-facing labels say
  "government", not "body":
  - **Covered**: a link to its coming-up page.
  - **Not covered yet**: a "Request it" button (US5) and a link to the body's official agenda or meetings page when
    the directory has one.
  - **Can't cover**: one plain sentence saying why (for example "Its records site blocks automated readers."), a
    link to the body's official agenda or meetings page (always), and a "Request it" button.
- AC2.3 The order is fixed for every address: city or town, county, township or town, school districts.
- AC2.4 The Clarksville test address shows Clarksville City Council and Montgomery County Commission as Covered and
  the Clarksville-Montgomery County School System as Can't cover, linked to its official agenda page.
- AC2.5 The unincorporated Montgomery County address shows the county and school system only, and one plain line
  saying the address is not inside a city or town.
- AC2.6 The Salem address shows every body as Not covered yet in M1 (Salem City Council turns Covered in M2 only if
  Brian OKs it).
- AC2.7 A consolidated city-county (Nashville) or independent city (Virginia) is listed once, not as two bodies,
  with a fixed line saying why there is no separate county, so it never looks like a missing county.
- AC2.8 A body with no entry in our directory is shown as Not covered yet, never as Covered or Can't cover.
  Can't cover needs a directory entry with its reason, official agenda page link, source link and the date checked.
- AC2.9 Under the list, one line says some bodies, such as water or transit boards, can't be found by address yet.
- AC2.10 The Connecticut address shows its town and school district and no county (Connecticut counties are not
  governments). Rhode Island and Massachusetts counties with no county government are not shown either.
- AC2.11 The New England town address outside Connecticut shows the town as a government, in the city or town slot. (Confirmed by manager 2026-11-19 after Q1; outside Connecticut, a New England town is never put in the township
  or town slot. Connecticut towns stay in the township or town slot.)
- AC2.12 Whether a Census unit is a working government comes from the Census status flag plus a hand-kept table for
  the states the flag gets wrong; a unit not known either way is left off, with the AC2.9 line covering it.
- AC2.13 If the Census matches the address but returns no listable government, the page says so in one fixed line
  (not an error), shows the AC2.9 line and lets the person try another address.

### US3. Choosing bodies and topics for a personal digest (M4)
As a resident, I want to pick the bodies and topics I care about, so that my email holds only what I want.
- AC3.1 Only Covered bodies whose coming-up record is in an email have a tick box. Others have none.
- AC3.2 Topics are a fixed list, the same for every body (default: Zoning and land use, Budget and taxes, Contracts
  and purchases, Appointments) plus "Everything", which is ticked by default.
- AC3.3 A topic matches an agenda item by a fixed word list applied to the verbatim item text, identical for every
  body, published on the Method page. No AI decides a topic. QA checks 20 sampled items against the word list.
- AC3.4 Sign-up posts only the email, body IDs and topic choices to Buttondown, as tags. No address, district or
  location text is posted (network log check).
- AC3.5 Sign-up is double opt-in: nothing is sent except the confirmation email until the person confirms.
- AC3.6 A person can change bodies or topics by signing up again with the same email, and unsubscribe in one click
  from any email.
- AC3.7 National sign-ups never change the content or sending of Clarksville's morning note. Email capacity is not a
  constraint: Brian upgrades Buttondown when it is needed (Brian, 2026-11-18).
In M1, a Covered Clarksville or Montgomery County body links to the existing morning note sign-up, unchanged.

### US4. The coming-up page for a covered body (M1)
As a resident, I want to see what a body will take up next, in its own words, so that I can follow it or show up.
- AC4.1 The page lists every meeting from today on that the body has posted, soonest first, each with date and
  meeting name as posted. Neither Clarksville City Council nor County Commission data stores a meeting time today, so
  M1 shows no time; the page shows a time only where the source posts one (never guessed). Meetings beyond the first
  three months shown may sit in a closed native toggle on the same page (added by digest-warmth, 2026-11-22; every
  meeting stays page text, in the same order; see A17).
- AC4.2 Agenda items show only when the source marks the agenda final or published. In M1, County Commission shows
  its stored items. Clarksville City Council upcoming agenda items are not stored today, so M1 shows each city meeting
  with a link to its official agenda and no items; the items come in task B9 (architecture task list), and until
  then QA checks the city page shows the meeting and agenda link only. Each item's text is shown
  character for character as the source prints it (QA compares 10 sampled items per body against the PDF or feed),
  and the meeting links to the official agenda document. Items held back by the existing rules
  (`docs/architecture/agenda-withhold-invariant.md`) stay held back.
- AC4.3 A meeting with no agenda, or only a draft agenda, reads "Agenda not posted yet" and links to the body's
  official meetings page. QA checks with a recorded draft-agenda fixture.
- AC4.4 When the source shows that some items are not public, or the architect finds the source can't confirm the
  list is complete, the meeting shows "This list may be incomplete. The official agenda is the full record." linked
  to the official agenda. QA checks with a recorded fixture of each case.
- AC4.5 For bodies outside Clarksville and Montgomery County, the page shows no vote, outcome, tally, attendance or
  motion. Clarksville and Montgomery County pages link to the full Daylight pages for those.
- AC4.6 The page shows when Daylight Digest last checked the source. If that is more than 3 days ago it says so in a
  plain line above the meetings.
  (M2, with task C3. Until a real check stamp exists, M1 shows "Newest record we have: {date}" and makes no
  stale claim: `checked_at` is a first-fetch date, see `national-freshness/checked-at-is-first-fetch`.)
- AC4.7 An item whose verbatim text matches the published topic word list (AC3.3; in M1 the morning note's lists)
  shows that fixed topic label next to it. The rule is the same for every body; no AI.
  Digest titles, Proposal A (Brian, 2026-11-24, with counts): the page opens with one summary line, "From today on:
  2 meetings · Rezoning (3) · Budget and finance (1)" (the page has no end date, see AC4.1, so it names no period;
  with no topic match the item count instead). Each meeting with shown items leads with "On this agenda: Rezoning (3)
  · Budget and finance (1) · 14 more items" above its date and name; with no topic match "On this agenda: 18 items";
  with no items shown, no such line. Topics in topic-list order; an item counts once under each topic it shows a label
  for, and "more items" counts only items with no label, so nothing is counted twice there. Labels and counts only.
- AC4.8 The only text on the page that is not verbatim source text is a fixed label (QA lists every string on the
  page and checks each is a source quote or a label in the label file).
- AC4.9 Every coming-up page has the same layout and fields (QA compares two bodies' pages).
- AC4.10 Each page has the existing "Report an error" control.
- AC4.11 The page's data is also published as a plain JSON feed with the same content and source links (the future
  app, the email and the per-body feeds read the same feed).

### US5. Request it (M1)
As a resident whose body isn't covered, I want to ask for it and be told if it opens, so that I don't have to check.
- AC5.1 "Request it" asks for an email only, then double opt-in. One form can carry several governments picked from
  the same list: one email typed, one confirmation email. The request is stored at Buttondown as a tag naming each
  body ID. No address, name or location text is sent (network log check). No account is needed.
- AC5.2 The confirmation is one fixed label that says honestly what happens next, shown on the page the confirm link
  lands on and in the confirmation email. For Not covered yet: "Thanks. We'll email you once if we open it. We open a
  government only after real requests, one at a time, and we may never reach yours." For Can't cover (second fixed
  label): "We can't cover this government unless the way it posts its records changes. If that happens and we open it,
  we'll email you once. Your request also tells us people want it." Neither promises a date. A form that mixes both
  kinds shows both labels.
- AC5.3 A requester gets only the confirmation email and, if the body opens, one "it's open" email sent after Brian
  OKs that send. They never get the morning note or the weekly note unless they sign up for it.
- AC5.4 The team can see confirmed requests per body (an internal report, kept out of the repo, with no emails in
  it). Counts are not shown publicly (open question 5).
- AC5.5 A person can request any number of bodies; a repeat request for the same body adds no second count.
- AC5.6 M1 includes a one-tap anonymous "just count me" counter beside the email request, for people who won't give an
  email (the focus group's skeptic and retiree would not). It sends only the body ID (no address, email or device ID),
  needs no server we run and no new account, and is counted separately from confirmed email requests (A14). The
  architect picks the mechanism; if none meets these limits, the manager brings it to Brian before M1 ships.

### US6. The "post your records readably" letter (M3)
As a resident whose body can't be covered because of how it posts records, I want a ready letter to its office, so
that I can ask them to post records anyone can read.
- AC6.1 The letter is offered only for Can't cover bodies whose reason is on the government's side and is about how
  records are posted: records are only scanned images, records are not posted, or the platform's open data feed is
  off or behind a key. It is never offered for "blocks automated readers" or for Not covered yet bodies.
- AC6.2 The letter is offered only for a body with real requests (open question 4) whose official public contact
  (clerk's office or general address) the directory holds, taken by hand from its own site, with source and date.
- AC6.3 The letter is one fixed template, the same for every body in every state. It asks only that the body post its
  agendas and minutes in a readable form (searchable text or an open data feed). It never mentions Daylight Digest's
  reader, bots or access. Fill-ins are only the body's name, the person's name and the person's town. The person can
  edit everything before sending.
- AC6.4 The template names and describes no official and takes no position on any issue (QA checks the template text
  against the directory's names and a list of issue words; the wording is approved by Brian before M3 goes live).
- AC6.5 "Open in my email" opens the person's own mail app addressed to the official contact, with subject and body
  filled. "Copy text" copies the same text. If the body only has a web form, the page shows "Copy text" and a link to
  the form.
- AC6.6 The filled letter body is under 1,800 characters so the mail link works in common mail apps.
- AC6.7 Daylight Digest sends nothing, records nothing about the letter (no click count, no copy), and says so.

### US7. The weekly email note (M4)
As a subscriber, I want one email a week with what's coming up for my bodies and topics, so that I don't have to check.
- AC7.1 Each subscriber gets at most one Daylight Digest email a week, on one fixed day, covering every government
  they ticked, each in its own section. It is sent as "editions": one email per group of subscribers who picked the
  same governments and topics, sent through the existing sender, not one send with per-subscriber sections (ADR 0013).
  A subscriber is in exactly one edition per week (QA checks no one gets two).
- AC7.2 Each section lists that government's meetings in the next 14 days, with the matching agenda item titles
  verbatim and a link to each official document, filtered by the person's topics. At most 15 items show per meeting,
  then a link to the rest on the official agenda.
- AC7.3 A government with nothing coming up says "No meetings posted for the next two weeks." One whose source was not
  checked in the last 7 days says "We couldn't check this government this week." and links its official site.
- AC7.4 No votes, no AI text, no text about named officials (same checks as AC4.5 and AC4.8).
- AC7.5 Footer: one-click unsubscribe, the LLC's business postal address (Brian provides it and approves the wording
  before the first national send), "Daylight Digest is not a government service", and the privacy link.
- AC7.6 Brian approves a sample email before the first send to real people (hard stop).
- AC7.7 Clarksville morning note subscribers are not moved or changed (US8).

### US8. Clarksville stays the full Daylight (every milestone)
As a Clarksville or Montgomery County resident, I want everything I have today to keep working.
- AC8.1 Every existing Daylight page, URL, feed and the morning note work as before; the existing test suite passes.
  A morning note sent after national sign-ups and requests exist has the same recipients and content rules as before.
- AC8.2 The front page stays Clarksville's until Brian decides otherwise. The national address page is a new page,
  linked from it.
- AC8.3 Clarksville City Council and Montgomery County Commission in the national list link to both their coming-up
  pages and their full Daylight pages.

### US9. Privacy lines (M1)
As a resident, I want to know what happens to my address and email before I type them.
- AC9.1 The address page shows, before submit, a plain sentence first: "We never get your address and never sell
  anything." Then the detail: "Your address goes from your browser straight to the US Census Bureau to find your
  area. Daylight Digest never sees or keeps it." (Final wording from the ux-designer; the facts stay.)
- AC9.2 Every email form (US5 request, US3 sign-up) says we keep only the bodies and topics picked and that the email
  is held by Buttondown, linking its privacy policy.
- AC9.3 The Method page states the same and lists exactly what is stored and where, including request tags.

### US11. Per-body calendar and RSS feeds (M4)
As a resident, I want to follow a covered body in my own calendar or feed reader, so that I get updates with no email.
- AC11.1 Each coming-up page links a calendar feed (meetings) and an RSS feed (meetings and agenda items), built from
  the AC4.11 JSON feed, with the same verbatim text and official links.
- AC11.2 A feed item appears in the next build after an agenda turns final (AC4.2); drafts never appear.
- AC11.3 Feeds carry no tracking pixels or links that identify the reader.

### US12. What we cover (M1)
As a resident, I want to see which governments are covered without typing my address or email, so that I can decide
whether to use it.
- AC12.1 A "What we cover" page lists every Covered body by state, then name, each linked to its coming-up page.
  It needs no address, email, account or cookie.
- AC12.2 The page states the number of Covered bodies and, once computed, the share of US addresses with at least
  one Covered body, estimated offline from about 200 population-weighted random addresses. The number is shown as
  computed, however small.
- AC12.3 The page lists Can't cover bodies with reason and official agenda link, and says in one line how a body
  gets added (requests, then "our owner approves", never a person's name), with no promised dates.

## Milestones
- **M1: demand capture and a thin slice on real data, no new collection.** "What we cover" (US12) and address lookup
  (US1) → body list with honest statuses (US2), Clarksville City Council and Montgomery County Commission Covered
  (already collected, real) and CMCSS Can't cover → "Request it" by email, plus the anonymous "just count me"
  counter (US5, AC5.6) → coming-up pages for the two covered bodies (US4: County Commission with items; City Council
  with meetings and agenda links, items in task B9; no meeting times) → who-runs-it and privacy lines (AC1.9, US9) → Clarksville unchanged (US8). Every other body in the
  country reads Not covered yet. Done when Brian enters a Clarksville address and an out-of-state address on his
  phone, sees the right list, opens a real coming-up page, requests a body with a team address, confirms, and the
  request shows in the internal report. Putting it live needs Brian's OK (hard stop 1). Dependency, not a blocker:
  Brian upgrades Buttondown when capacity is needed.
- **M2: Legistar wave 1, one body first.** The architect's "national collector" design comes first (per-client block
  state on the shared host, token-required and API-not-enabled as body states, its own workflow and request budget).
  Then Salem City Council (Legistar reader from PR #62). Needs Brian's typed OK before any request to a new host (R5);
  the probe of which Legistar sites answer without a key is itself requests and needs the same OK. "Token required"
  and "API not enabled" are shown as Can't cover. Terms check before the first request. Past Salem, R8 applies.
- **M3: the letter** (US6), only for bodies with real requests. Brian approves the letter wording before it goes live.
- **M4: national weekly email** (US7, US3) plus the per-body calendar and RSS feeds (US11). Brian upgrades Buttondown
  when capacity is needed, provides the postal address, and approves a sample and the first send (hard stop).
- **M5: more platforms**, ordered by request counts: eScribe, CivicClerk, Municode, and BoardDocs placed per open
  question 9. Each new platform: terms check, Brian's OK per host, R8 applies.

## Later (not scheduled)
iPhone app on the same feeds (after the website is complete, per Non-goals, and a lessons-learned list is written);
"agenda just posted" email alerts (open question 10); wards or council districts per city where the city publishes a
map; keyword or street alerts; votes for tier B bodies once checked against their minutes; graduating a city to full
Daylight when demand earns it; committees and boards beyond the main elected body; AI topic tags (a spend, never
about officials); public request counts; special districts; Spanish; Android.

## Success metrics
- 0 known wrong facts shown; 100% of shown items have a working official link (automated link check).
- 0 requests carrying any part of an address to a non-Census host (AC1.2, run on every release).
- 0 requests to hosts without Brian's OK; 0 robots or block violations (test-enforced, as today).
- 0 draft agenda items shown (AC4.2 fixture test, every release).
- From M1 live: confirmed requests per body, and lookups that end in at least one request (GoatCounter page counts
  and the request report), used to pick what opens next. No sign-up targets before January 2027.

## Assumptions
- A1. Primary user is anyone in the US (verified: Brian, 2026-11-18).
- A2. The Census geocoder works from the browser by JSONP with no key and no CORS (verified: Daylight's address box,
  2026-11-08, and research 2026-11-19). JSONP runs as script: security-engineer records it as an accepted risk.
- A3. The geographies lookup returns place, county and county subdivision by default, and school districts with extra
  layers (layer IDs unverified: architect tests them).
- A4. The Census status flag tells a working government from a Census designated place or a non-functioning unit in
  most states, but not in Connecticut, Rhode Island, parts of Massachusetts, and New England and New York towns
  (Brain Trust operator, 2026-11-19; unverified: architect checks and builds the hand table in AC2.12).
- A5. Buttondown's free form accepts several tags on a new address and makes new tags on the fly (verified,
  2026-11-18 live test). Its pricing page lists tag segmentation as a paid add-on; that is covered by A6.
- A6. Email capacity and plan features are not a constraint: "i'll upgrade to get more outgoing mail capacity if its
  determined we need it. assume that is not an issue" (Brian, 2026-11-18 11:32 PM CT). The upgrade itself is Brian's
  action; the manager sends him one card when the team finds it is needed.
- A7. Requesters and national subscribers can share Buttondown with the morning note without changing who gets the
  morning note (unverified: architect picks the mechanism, for example a separate list or tag filters).
- A8. County Commission upcoming agenda items are stored and read verbatim (verified: 142 items read, 2026-11-10).
  Clarksville City Council items are not stored today, only meetings and agenda links; items come in task B9
  (architect's finding, 2026-11-19). Neither stores a meeting time.
- A9. Legistar has no public client list; "token required" and "API not enabled" are real per-body states (verified:
  research 2026-11-19). 1,000 rows per query (vendor docs). Legistar shows an agenda status per meeting
  (EventAgendaStatusName); whether it flags non-public items is unverified (architect checks for AC4.4).
- A10. There is no free lookup for local officials' contacts; Google's was retired 2025-04-30 (verified: research
  2026-11-19). Contacts are added by hand, one body at a time.
- A11. Code starts after Clarksville's data cutover (ADR 0011) (verified: Brian, 2026-11-19).
- A12. If the morning note is not live when M1 goes live, the Covered bodies' sign-up link is hidden until it is.
- A13. One body per government in M1 to M4: the main elected board (council, commission, school board, select board).
- A15. CMCSS meetings are already listed by Daylight, so it may later be shown as covered for meetings only (open
  question 12). Default: Can't cover for items, with meeting dates shown and the official agenda linked.
- A14. Requests are a signal, not a vote. Confirmed email requests are the count that matters; anonymous counts, if
  built, are shown separately. Brian's OK per host still decides every opening.
- A16. digest-warmth (pending Brian's approval at his preview test; switch-on prerequisite) (`docs/design/digest-warmth.md` section 9, changes 1 and 2; applied 2026-11-22 on the manager's
  brief, not yet confirmed by Brian): AC1.9 and AC1.10 no longer say "above the address box". The who-runs-it line
  and the "What we cover" link now follow the address card and its privacy lines, in view without opening anything.
  The words of both lines are unchanged. Assumed: the Brain Trust's reason for "above" was that the reader can see
  who runs the page before typing, and "in view, directly after the card" keeps that. If it was "read before the
  box", the fallback is the design's: both lines between the lede and the card at small size.
- A17. digest-warmth (pending Brian's approval at his preview test; switch-on prerequisite) (section 9, change 3): AC4.1 gains the closed toggle. The first three calendar months that have a
  meeting print open (the next meeting's month counts); the rest sit in one native `<details>`, closed, as page text
  in the feed's order. The toggle is used only when the rest is more than one meeting over two or more months,
  because its one fixed label ("Show {n} later meetings, {from} to {to}") has no singular; a smaller rest prints
  open.
- A18. digest-warmth (pending Brian's approval at his preview test; switch-on prerequisite) (section 9, change 4): this spec has no line about orange; the rule was design 0a's ("no orange
  text, fill or border on a digest page"). It is relaxed there to: orange is decoration (the sun, its rays, the card
  edge) and the focus ring; never text and never a status. Status pills stay navy, and R2 (no red or green) is
  unchanged. A test pins it (`test_orange_is_decoration_only_never_text_and_never_a_status`).
- A19. digest-warmth: the new labels (lede, how it works, Why look?, greeting, Next meeting, Thinking of going?) are pending Brian's approval at his preview test; switch-on prerequisite. The design's recommended Focus Group is skipped for now: Brian's hands-on preview test comes first; re-decide after it.
- A19. digest-warmth (section 9, change 5): AC4.8 and AC4.9 are unchanged. The "Next meeting" and "Thinking of
  going?" labels are in `config/national/page-labels.yml` and print on every coming-up page with the same words;
  "Thinking of going?" is left out only where the directory has no checked official link (never an empty link).
- A20. The greeting's place name (digest-warmth section 4) is the Census answer's own `BASENAME`, read as given: the
  geocoder's geographies answer carries it for Incorporated Places ("Clarksville") and County Subdivisions
  (`docs/platform-facts.md`, "Census geocoder, geographies", verified 2026-11-19 from one live answer; not
  re-checked on raw bytes on 2026-11-22, because this build environment cannot reach the geocoder). The page never
  trims a Census NAME itself: a unit whose `BASENAME` is missing, holds no letter ("5" for "District 5") or is not
  part of its NAME gets `lookup.greet-none`; a county is named in full by its NAME. The name is drawn in the page
  only, never in a URL, title, cookie or storage.

## Open questions (recommended answers are the defaults)
1. Front door: does the national address page replace Clarksville's front page? **Default: no. New page, linked from
   the front page; Brian decides the swap at the January launch.**
2. Does the weekly note include Clarksville bodies? **Default: yes, if ticked. The daily morning note stays a
   separate, unchanged opt-in.**
3. Weekly send day? **Default: Monday, early morning Central time.**
4. When does a body open, or get the letter? **Default: on a supported platform, 3 or more confirmed requests, then
   Brian's typed OK.**
5. Show request counts publicly? **Default: no, internal only.**
6. Email when nothing is coming up? **Default: send it with the "No meetings posted" line, so silence never looks
   like a fault.**
7. Wave 1 batch size after Salem? **Default: up to 10 Legistar bodies, chosen by requests, in one OK card.**
8. Demand review after launch: what count keeps national collection going? **Default: review 6 weeks after the
   January launch; if fewer than 25 confirmed requests name bodies on supported platforms, M2 widening and M5 are
   shelved and the manager brings it to Brian.**
9. Where does BoardDocs (most school boards) sit in the platform order? **Default: architect checks its terms and
   whether it has a public feed during M2; it is then ranked with the others by request counts after January.**
10. "Agenda just posted" alerts, which panelists wanted over a weekly note? **Default: the RSS feed (AC11.2) gives
    this from M4; email alerts when an agenda posts are Later.**
11. Email capacity: **decided (Brian, 2026-11-18 11:32 PM CT): "i'll upgrade to get more outgoing mail capacity if
    its determined we need it. assume that is not an issue."** Not a design constraint. Postal address: the LLC's
    business address, provided and approved by Brian before the first national send.

12. Show CMCSS as covered for meetings only (dates, no items)? **Default: no; Can't cover for items, meeting dates
    shown, until Brian decides.**

## Risks
- **Thin coverage where people care most** (school boards, townships, small towns with scanned PDFs). Mitigation:
  US12 up front, Can't cover always links the official agenda page, honest Request it.
- **A free rival runs the same model** (TL;DR Gov: Legistar, Municode, "request a city"). Mitigation: R8 gate; our edge
  is the one-address, all-governments view, the official record only and honesty about coverage.
- **Email limits** (send size with many per-subscriber sections, 100 API sign-ups a day). Mitigation: architect's
  send design; Brian upgrades when capacity is needed.
- **National email touching the morning note.** Mitigation: AC5.3, AC8.1, A7.
- **Asking for an email lowers requests** (a Focus Group skeptic would give none). Mitigation: AC5.6 counter, built in M1.
- **Wrong body for an address** (geocoding error, New England, consolidations, annexations lag a year). Mitigation:
  AC2.7, AC2.10 to AC2.12, test addresses; a "check with your local election office" link near the list.
- **Census lookup outage.** Mitigation: AC1.6; no fallback that would send the address to us.
- **One block on the shared Legistar host stopping every body.** Mitigation: R4 stale rule; per-client block state.
- **Draft or partial agendas shown as final.** Mitigation: AC4.2 to AC4.4 with recorded fixtures.
- **Letter read as lobbying for our access.** Mitigation: US6 (readable records only, after requests, no names).
- **Verbatim text hard to read.** R3 stands. Topic labels (AC4.7); ux tests real Legistar titles with people after M1.
- **Stale data looks like "nothing coming up".** Mitigation: AC4.6, AC7.3.
- **Late, failing daily schedule.** Mitigation: national collection in its own workflow and request budget.
- **Load on Brian.** Mitigation: one card per milestone; one OK for the shared Legistar host if the design allows.

## Panels
Both ran on v1 (c7cb106), 2026-11-19; findings are folded into v2 (decision tables in each report).
- **Brain Trust, 6 members:** `docs/reviews/brain-trust-daylight-national.md`. No Go (four Fix First, two Rethink).
  Minority view kept: four members argued "don't build national yet"; the chair judged that side stronger on demand,
  but Brian chose to build, and R8 shelves national if requests stay near zero. Superseded by Brian's 2026-11-18
  answer: the email capacity gate and the anonymous-counter-by-default for requests (email requests are now the main
  path; the counter is optional).
- **Focus Group, 5 simulated personas:** `docs/research/focus-group-daylight-national.md`. Results are hypotheses to
  check with real people after the January launch. Not changed: the letter stays optional, in M3.
