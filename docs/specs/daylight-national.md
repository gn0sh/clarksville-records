# Spec: daylight-national (the national Daylight website)

Status: draft v1, 2026-11-19. Owner: product-manager. Priority: MVP is M1; the rest is ordered below.
Decisions so far: `docs/expansion/national-kickoff.md`. Memo: `docs/expansion/national-digest-memo.md` (sections 1-3, 7,
8b, 8c, 9). Clarksville rules this keeps: `docs/specs/clarksville-records.md`. Sources: `docs/platform-facts.md`.
Research: `docs/research/national-open-facts-2026-11-19.md`.

## Goal
Anyone in the US types their address and sees every local government that covers that spot: city or town, county,
township and school district. For each one, Daylight says plainly whether it covers it. For the ones it covers, the
person sees what is coming up (upcoming meetings, each agenda item in the government's own words, a link to the
official document) and can sign up for one weekly email about the bodies and topics they pick. For the ones it does
not cover, they can ask for it. When the gap is on the government's side, they can send a fixed, neutral letter from
their own email asking the government to post its records in a readable way. Daylight never sees the address. It
shows the official record only, with every fact linked to its source, and no AI text about named officials.
Clarksville and Montgomery County stay the full Daylight.

**Primary user:** anyone in the US following their own local governments (confirmed by CEO, 2026-11-18).

## Problem
Local agendas sit on hundreds of different sites. A resident has to know which bodies govern their address, find
each one's site, and check it every week. Existing services cover many places but mostly use AI summaries, which
have told towns things that did not happen (memo section 5). People want one place that tells them, from the
official record only, what their own governments will take up next.

## Users
- **Residents anywhere in the US** who want to follow their own city, county, township or school board.
- **Brian (CEO, operator)** approves every new host, every deploy, every send to real people and the letter wording.
- Not users now: journalists, campaigns, lobbyists, officials' staff. Nothing is built for them.

## Goals
1. A person finds every local body for their address in one step, with an honest status for each.
2. For a covered body, they see the coming-up record, verbatim and linked, and can get it by weekly email.
3. Demand shows us where to build next (the request list), with no marketing until January 2027.
4. Grow platform by platform (Legistar first), never by guessing or by working around a block.
5. Zero wrong facts: nothing shown is ours to get wrong.

## Non-goals
- No iPhone or Android app (later, after the website is complete; Brian's rule).
- No votes for any body outside Clarksville and Montgomery County unless checked against that body's minutes.
- No AI-written text about named officials, anywhere. No AI text in M1 at all.
- No scores, rankings, commentary, endorsements, campaign links, comments or user accounts.
- No lists of named officials, no officials' personal contacts, no bulk scraping of contacts.
- No state or federal bodies (Census returns congressional and state districts; we ignore them).
- No special districts (water, fire, transit): the Census geocoder does not return them.
- No marketing, ads or outreach before the January 2027 formal launch. No paid services.

## Rules (every milestone; carried over from Clarksville)
- R1. Official record only. Every fact on a page or in an email links to its official source document.
- R2. Every body and every official is shown with the same layout, fields and ordering rule.
- R3. Text we write is fixed labels only. Agenda text is shown verbatim, never paraphrased or summarized.
- R4. Polite collection: obey robots.txt and any crawl delay, public pages only, stop on 403, 429 or a disallow,
  never retry by another route. A blocked body is shown as "can't cover".
- R5. No request to a new government's host until Brian types his OK in the thread (one OK can cover a listed batch).
- R6. No spend, no deploy and no email to real people without Brian (hard stops 1, 3, 4).
- R7. The address never reaches Daylight. We keep only body IDs, topics and the email address (held by Buttondown).

## User stories and acceptance criteria
QA test addresses (kept in the test plan, real public places, not a person's home): one inside Clarksville city
limits, one in unincorporated Montgomery County, one in Salem, OR, one in Nashville (consolidated city-county), one in
a Virginia independent city, one in a state with township governments, and one that does not exist.

### US1. Address entry and lookup (M1)
As a resident, I want to type my address and learn which local governments cover it, so that I don't have to work
it out myself.
- AC1.1 The address page has one address box and a privacy line visible before the person submits (US9 text).
- AC1.2 With the browser's network log open, submitting a test address sends it to `geocoding.geo.census.gov` only.
  No request to any Daylight host, analytics host, Buttondown or any other host contains any part of the address
  (street number, street name, ZIP). QA checks all seven test addresses.
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

### US2. The list of bodies for that spot (M1)
As a resident, I want one list of every body that governs my address, each with a plain status, so that I know what
Daylight can and can't show me.
- AC2.1 The list shows each local government the Census returns for the spot: the incorporated place (city, town,
  village), the county, the county subdivision only where it is a working government (a township), and each school
  district (unified, elementary or secondary). Census designated places and congressional or state districts are
  never shown.
- AC2.2 Each body shows its name as the Census gives it and exactly one of three states:
  - **Covered**: a link to its coming-up page and, where an email covers it, a tick box to add it to the digest.
  - **Not covered yet**: a "Request it" button (from M3; in M1 and M2 the label shows with no button).
  - **Can't cover**: one plain sentence saying why (for example "Its records site blocks automated readers.") and a
    link to the body's official site.
- AC2.3 The order is fixed for every address: city or town, county, township, school districts.
- AC2.4 The Clarksville test address shows Clarksville City Council and Montgomery County Commission as Covered and
  the Clarksville-Montgomery County School System as Can't cover, linked to its official site.
- AC2.5 The unincorporated Montgomery County address shows the county and school system only, with no city.
- AC2.6 The Salem address shows every body as Not covered yet in M1 (Salem City Council turns Covered in M2 only if
  Brian OKs it).
- AC2.7 A consolidated city-county (Nashville) or independent city (Virginia) is listed once, not as two bodies.
- AC2.8 A body with no entry in our directory is shown as Not covered yet, never as Covered or Can't cover.
  Can't cover needs a directory entry with its reason, source link and the date checked.
- AC2.9 Under the list, one line says some bodies, such as water or transit boards, can't be found by address yet.

### US3. Choosing bodies and topics for a personal digest (M1 for Clarksville; M4 nationally)
As a resident, I want to pick the bodies and topics I care about, so that my email holds only what I want.
- AC3.1 Only Covered bodies whose coming-up record is in an email have a tick box. Others have none.
- AC3.2 Topics are a fixed list, the same for every body. M1 reuses the morning note's lists (zoning, budget,
  contracts, seats). M4 adds the national list (default: Zoning and land use, Budget and taxes, Contracts and
  purchases, Appointments) plus "Everything", which is ticked by default.
- AC3.3 A topic matches an agenda item by a fixed word list applied to the verbatim item text, identical for every
  body, published on the Method page. No AI decides a topic. QA checks 20 sampled items against the word list.
- AC3.4 Sign-up posts only the email, body IDs and topic choices to Buttondown, as tags. No address, district or
  location text is posted (network log check).
- AC3.5 Sign-up is double opt-in: nothing is sent except Buttondown's confirmation email until the person confirms.
- AC3.6 A person can change bodies or topics by signing up again with the same email, and unsubscribe in one click
  from any email.

### US4. The coming-up page for a covered body (M1)
As a resident, I want to see what a body will take up next, in its own words, so that I can follow it or show up.
- AC4.1 The page lists every meeting from today on that the body has posted, soonest first, each with date, time and
  meeting name as posted, in the body's local time zone.
- AC4.2 For a meeting with a posted agenda, each agenda item's text is shown character for character as the source
  prints it (QA compares 10 sampled items per body against the PDF or feed), and the meeting links to the official
  agenda document. Items held back by the existing rules (`docs/architecture/agenda-withhold-invariant.md`) stay held
  back.
- AC4.3 A meeting with no agenda yet reads "Agenda not posted yet" and links to the body's official meetings page.
- AC4.4 For bodies outside Clarksville and Montgomery County, the page shows no vote, outcome, tally, attendance or
  motion. Clarksville and Montgomery County pages link to the full Daylight pages for those.
- AC4.5 The only text on the page that is not verbatim source text is a fixed label (QA lists every string on the
  page and checks each is a source quote or a label in the label file).
- AC4.6 The page shows when Daylight last checked the source. If that is more than 3 days ago it says so in a plain
  line above the meetings.
- AC4.7 Every coming-up page has the same layout and fields (QA compares two bodies' pages).
- AC4.8 Each page has the existing "Report an error" control.
- AC4.9 The page's data is also published as a plain JSON feed with the same content and source links (the future
  app and the email read the same feed).

### US5. The request list (M3)
As a resident whose body isn't covered, I want to ask for it, so that I'm told when it opens.
- AC5.1 "Request it" asks for an email only, then double opt-in. The request is stored at Buttondown as a tag naming
  the body ID. No address is sent.
- AC5.2 The confirmation says, word for word from the label file, that we will email once if and when we cover it.
  It never promises a date.
- AC5.3 An internal report (not in the repo, no emails in it) lists bodies by request count.
- AC5.4 When a body opens, each requester gets one email saying so, after Brian OKs that send.
- AC5.5 A person can request any number of bodies, and each request needs no account.

### US6. The "ask them to open it" letter (M3)
As a resident whose body can't be covered because of how it posts records, I want a ready letter to its office, so
that I can ask them to fix it.
- AC6.1 The letter is offered only for Can't cover bodies whose reason is on the government's side: the site blocks
  automated readers, records are only scanned images, records are not posted, or the platform has its data feed off or
  behind a key. It is never offered for Not covered yet bodies (that gap is ours).
- AC6.2 The letter is offered only when the directory holds the body's official public contact (clerk's office or
  the body's general address), taken by hand from the body's own site, with its source link and date checked.
- AC6.3 The letter is one fixed template, the same for every body in every state. Fill-ins are only the body's name,
  the person's name and the person's town. The person can edit everything before sending.
- AC6.4 The template names and describes no official and takes no position on any issue (QA checks the template text
  against the directory's names and a list of issue words; the wording is approved by Brian before M3 goes live).
- AC6.5 "Open in my email" opens the person's own mail app addressed to the official contact, with subject and body
  filled. "Copy text" copies the same text. If the body only has a web form, the page shows "Copy text" and a link to
  the form.
- AC6.6 The filled letter body is under 1,800 characters so the mail link works in common mail apps.
- AC6.7 Daylight sends nothing, records nothing about the letter (no click count, no copy), and says so on the page.

### US7. The weekly email note (M4)
As a subscriber, I want one email a week with what's coming up for my bodies and topics, so that I don't have to check.
- AC7.1 Each subscriber gets at most one Daylight weekly email a week, on one fixed day, covering every body they
  ticked, each body in its own section. It is one Buttondown send with per-subscriber sections, not one send per body.
- AC7.2 Each section lists that body's meetings in the next 14 days, with the matching agenda items verbatim and a
  link to each official document, filtered by the person's topics.
- AC7.3 A body with nothing coming up says "No meetings posted for the next two weeks." A body whose source was not
  checked in the last 7 days says "We couldn't check this body this week." and links its official site.
- AC7.4 No votes, no AI text, no text about named officials (same checks as AC4.4 and AC4.5).
- AC7.5 Footer: one-click unsubscribe, the operator's mailing address, "Daylight is not a government service",
  and the privacy link.
- AC7.6 Brian approves a sample email before the first send to real people (hard stop).
- AC7.7 Clarksville morning note subscribers are not moved or changed (US10).

### US8. Clarksville stays the full Daylight (every milestone)
As a Clarksville or Montgomery County resident, I want everything I have today to keep working.
- AC8.1 Every existing Daylight page, URL, feed and the morning note work as before; the existing test suite passes.
- AC8.2 The front page stays Clarksville's until Brian decides otherwise. The national address page is a new page,
  linked from it.
- AC8.3 Clarksville City Council and Montgomery County Commission in the national list link to both their coming-up
  pages and their full Daylight pages.

### US9. Privacy line (M1)
As a resident, I want to know what happens to my address and email before I type them.
- AC9.1 The address page shows, before submit: "Your address goes from your browser straight to the US Census Bureau
  to find your area. Daylight never sees or keeps it." (final wording from the ux-designer; the facts stay.)
- AC9.2 The sign-up form says we keep only the bodies and topics picked, and that the email is held by Buttondown,
  linking its privacy policy.
- AC9.3 The Method page states the same and lists exactly what is stored and where.

## Milestones
- **M1: thin end-to-end slice on real data, no new collection.** Address lookup (US1) → body list (US2) with
  Clarksville City Council and Montgomery County Commission Covered (already collected, real) and CMCSS Can't cover →
  coming-up pages for those two (US4) → sign-up with body and topic tags (US3, M1 part) on the existing Buttondown form
  → privacy line (US9) → Clarksville unchanged (US8). Every other body in the country reads Not covered yet.
  Done when Brian enters a Clarksville address and an out-of-state address on his phone and sees the right list,
  opens a real coming-up page, and signs up with a team address. Putting it live needs Brian's OK (hard stop 1).
- **M2: Legistar wave 1, one body first.** Salem City Council (Legistar reader from PR #62), then a short batch.
  Needs Brian's typed OK before any request to a new host (R5); the probe of which Legistar sites answer without a
  key is itself requests to new hosts and needs the same OK. "Token required" and "API not enabled" are shown as
  Can't cover. Terms check before the first request.
- **M3: request list and letter** (US5, US6). Brian approves the letter wording before it goes live.
- **M4: national weekly email note** (US7, US3 national topics). Brian approves a sample and the first send.
- **M5: more platforms**: eScribe, then CivicClerk, then Municode. Each new platform: terms check, Brian's OK per host.

## Later (not scheduled)
iPhone app on the same feeds (after the website is complete and a lessons-learned list is written); wards or council
districts per city where the city publishes a map; votes for tier B bodies once checked against their minutes;
graduating a city to full Daylight when demand earns it; committees and boards beyond the main elected body; AI topic
tags (a spend, never about officials); public request counts; special districts; Spanish; Android.

## Success metrics
- 0 known wrong facts shown; 100% of shown items have a working official link (automated link check).
- 0 requests carrying any part of an address to a non-Census host (AC1.2, run on every release).
- 0 requests to hosts without Brian's OK; 0 robots or block violations (test-enforced, as today).
- After M3: request counts per body, used to pick what opens next. No sign-up targets before January 2027.

## Assumptions
- A1. Primary user is anyone in the US (verified: Brian, 2026-11-18).
- A2. The Census geocoder works from the browser by JSONP with no key and no CORS (verified: Daylight's address box,
  2026-11-08, and research 2026-11-19).
- A3. The geographies lookup returns place, county and county subdivision by default, and school districts with extra
  layers (layer IDs unverified: architect tests them).
- A4. The Census answer tells a working government from a Census designated place or a non-functioning township
  (unverified; if not, the directory marks them by hand and unknown ones are left off with a note).
- A5. Buttondown's free form accepts several tags on a new address and makes new tags on the fly (verified,
  2026-11-18 live test). Form sign-ups carry no metadata on the free plan (verified 2026-11-16).
- A6. One weekly send with per-subscriber sections by tag works on the free plan (research 2026-11-19 recommends it;
  unverified at our volume). Pricing assumes at most one email a day to the whole list.
- A7. Buttondown's free plan caps at 100 subscribers (unverified; memo cites a third-party price page). Above that is a
  spend: at the cap, sign-up shows a plain "full for now" line and the team asks Brian. Never auto-upgrade.
- A8. Clarksville City Council and County Commission upcoming agenda items are already read verbatim (county verified:
  142 items read, 2026-11-10; city item level unverified: architect checks).
- A9. Legistar has no public client list; "token required" and "API not enabled" are real per-body states (verified:
  research 2026-11-19). 1,000 rows per query (vendor docs).
- A10. There is no free lookup for local officials' contacts; Google's was retired 2025-04-30 (verified: research
  2026-11-19). Contacts are added by hand, one body at a time.
- A11. Code starts after Clarksville's data cutover (ADR 0011) (verified: Brian, 2026-11-19).
- A12. The morning note is live before M1 goes live; if not, M1 sign-ups join the same list and get the note when it
  starts (unverified; status shows go-live pending).
- A13. One body per government in M1 to M4: the main elected board (council, commission, school board).

## Open questions (recommended answers are the defaults)
1. Front door: does the national address page replace Clarksville's front page? **Default: no. New page, linked from
   the front page; Brian decides the swap at the January launch.**
2. Does the weekly note include Clarksville bodies? **Default: yes, if ticked. The daily morning note stays a separate,
   unchanged opt-in.**
3. Weekly send day? **Default: Monday, early morning Central time.**
4. When does a body open? **Default: on a supported platform, 3 or more requests, then Brian's typed OK.**
5. Show request counts publicly? **Default: no, internal only.**
6. Email when nothing is coming up? **Default: send it with the "No meetings posted" line, so silence never looks
   like a fault.**
7. Wave 1 batch size after Salem? **Default: up to 10 Legistar bodies, chosen by requests, in one OK card.**

## Risks
- **Buttondown limits** (100-subscriber cap, 100 API sign-ups a day, per-subscriber sections at volume). Mitigation:
  A6, A7; stop at the cap and ask Brian (spend).
- **Wrong body for an address** (rural geocoding error, townships, consolidated governments, annexations). Mitigation:
  AC2.7, AC2.8, test addresses; a plain "check with your local election office" link near the list.
- **Census lookup outage.** Mitigation: AC1.6; no fallback that would send the address to us.
- **Hosts that block us or need a key.** Mitigation: Can't cover state; never work around a block; letter only where
  the gap is theirs.
- **Letter read as advocacy.** Mitigation: one fixed, approved, neutral template to the clerk's office; no officials named.
- **Topic word list misses or mislabels items.** Mitigation: "Everything" is the default; the full agenda is linked.
- **Stale data looks like "nothing coming up".** Mitigation: AC4.6, AC7.3.
- **Load on Brian** (host OKs, deploy OKs, wording and sample approvals). Mitigation: batch into one card per milestone.

## Panels
The primary user includes real outside people, so a **Brain Trust (6 members)** and a **Focus Group** (simulated US
residents from different kinds of places: a big Legistar city, a small town, an unincorporated area, a township state)
will run on this spec before design starts. Findings fold into this spec; focus-group results are hypotheses.
