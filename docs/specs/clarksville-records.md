# Spec: clarksville-records

Status: draft v1, 2026-11-07. Owner: product-manager. Facts about sources: `docs/platform-facts.md`.

## Problem
Montgomery County and Clarksville, TN publish agendas, minutes, budgets and bids as scattered PDFs and web pages
on several sites. Residents cannot easily see how their representatives showed up and voted, where public money
goes, or who gets contracts. The one existing service (soar.com Citizen Portal) gives overall tallies, no
per-member votes, and paywalls video and transcripts.

## Users
- **Primary: residents of Clarksville and Montgomery County, TN** (confirmed by CEO, 2026-11-07: "for the public to review").
  They want to look up an official, a topic or a dollar figure and trust what they see.
- **Brian (CEO)** reviews a private preview first. Going public is his later decision (hard stop 1).
- Not users for now: journalists, campaigns, officials' staff. Nothing is built for them. No campaign link.

## Goals
1. Show each official's participation (present/absent) and recorded votes, each linked to its source document.
2. Show budget information and who receives contracts, from committee and commission records (later milestones).
3. Collection is fully automated; Brian does no manual data entry.
4. Neutral and verifiable: a resident can check any fact against the original in one click.
5. The set of facts shown evolves through testing; adding a fact type must be cheap.

## Non-goals
- No scores, grades, rankings, "missed votes" leaderboards, trend arrows, or commentary of any kind.
- No explanations of why an official voted, no AI-written prose about officials (item labels copied from the source are fine).
- No endorsements, campaign or donation links, voter guides, user accounts, comments.
- No collection from `cityofclarksville.com` (it blocks automated tools) and no circumventing any block.
- No video or transcript hosting.

## Neutrality rules (requirements, every milestone)
- N1. Every official is displayed with the same layout, fields and ordering rule (alphabetical by surname; other sorts only by neutral fields such as date).
- N2. Facts only: attendance is Present or Absent as recorded; votes are Yes, No, Abstain, or Other as recorded (with the minutes' wording, e.g. "Recused"). Nothing is computed into a judgment.
- N3. Counts appear only as plain totals with the denominator and date range stated (e.g. "Recorded absent at 4 of 61 meetings, 2020-2024"), identical for every official, with no sorting by or highlighting of counts.
- N4. Every fact shows a visible source link (document, page) and the date it was fetched.
- N5. A correction-report path exists on every fact page, and reports are visible to Brian.
- N6. No campaign link, no ads, no tracking of individual visitors beyond what Brian approves.

## User stories and acceptance criteria (Milestone 1)
Tests use the 2020-2024 minutes corpus unless stated.

**US1. As a resident, I want to pick a commissioner and see every recorded vote, so that I can see how they voted.**
- AC1.1 The commissioner list has every person who appears in a roll call in 2020-2024, one entry each, name variants merged (spelling, titles); merge rules are visible to Brian.
- AC1.2 A commissioner's page shows each shown vote as a row: meeting date, item/motion text as in the minutes, the commissioner's recorded vote, and the recorded outcome.
- AC1.3 Every row links to the minutes PDF opened at the page where the vote appears. 100% of rows have a working link (automated link and page check).
- AC1.4 The page states the date range covered and the fetch date of the minutes.
- AC1.5 Two commissioners' pages differ only in data, not layout or fields (N1).

**US2. As a resident, I want to see who was present or absent at each meeting, so that I know participation.**
- AC2.1 Each meeting page lists every member as Present or Absent exactly as the minutes' attendance section states, with source link and page.
- AC2.2 A commissioner's page shows a plain attendance total with denominator (N3). The total equals an automated recount from the meeting pages.
- AC2.3 Meetings with no parseable attendance section are listed as "attendance not extracted" and are excluded from totals and the denominator, stated on the page.

**US3. As a resident, I want to search agendas, so that I can find when a topic came up.**
- AC3.1 Full-text search across commission agendas (informal and formal, 2020 to newest available) returns meeting date, snippet, and a link to the PDF page.
- AC3.2 Searching a known phrase from each of 5 sampled agendas returns that agenda in the top 10 results.
- AC3.3 Agenda links known to be wrong (platform-facts: Oct 2023 formal points to the informal file) are caught by a content check and flagged, never shown under the wrong label.

**US4. As Brian, I want collection to run without me, so that I never enter data by hand.**
- AC4.1 One scheduled run discovers new agendas and minutes, downloads, parses, and updates the private preview with no manual step. A normal run asks Brian for nothing.
- AC4.2 The collector honours robots.txt on each host, any declared Crawl-delay, and at least 10 s between requests on clarksvilletn.gov; a test fails the build if the fetcher can request a disallowed path or skip the delay.
- AC4.3 On HTTP 403/429 or a robots disallow, the collector stops for that host, logs it, and does not retry by another route (no alternate hosts, headers or proxies).
- AC4.4 Each run writes a log: documents found, new, failed, parsed, held back. Failures raise an internal alert (issue), never a silent gap.
- AC4.5 A re-run with no new documents changes nothing (idempotent). Each stored fact carries source URL, file hash, page and fetch date.

**US5. As a resident, I want to report a mistake, so that errors get fixed.**
- AC5.1 Every vote, attendance and agenda result page has a "Report an error" control that records the fact id and a free-text note without an account.
- AC5.2 A report reaches Brian within one collection cycle; a corrected fact shows "Corrected on <date>" and the old value stays in the change history.

**US6. As a resident, I want to click an elected official and see their whole vote and comment history, so that I can see what they did and said.** (Brian, 2026-11-07)
- AC6.1 The official's page (US1) also lists their recorded comments: statements, motions and seconds attributed to them by name in the minutes, quoted verbatim with meeting date, item and source page. No paraphrase, no AI summary, no selection by tone.
- AC6.2 Comments, votes and attendance sit in one date-ordered history on the page, filterable by type and year; the same layout for every official (N1).
- AC6.3 If the minutes summarise discussion without naming speakers, nothing is attributed. Video transcripts are a later source (Later list) and, when added, are labelled as transcripts with a timestamp link.

**US7. As a resident, I want to click a specific item and see its entire history, so that I can follow it from start to finish.** (Brian, 2026-11-07)
- AC7.1 An item page groups every appearance of the same item (resolution or ordinance number, e.g. "AB-4-2024", or the agenda item when unnumbered): each agenda listing, committee referral, reading, amendment, comment and roll call, in date order, each with its source page.
- AC7.2 Each roll call on the item page shows every member's recorded vote and the outcome.
- AC7.3 Items are linked by their official number; unnumbered items are linked only on an exact title match and show "linked by title" so a resident can judge it. Uncertain links are not made.
- AC7.4 Every vote row and comment on an official's page links to its item page.

## Parse accuracy and uncertain parses (top product risk)
A parse that misstates an official's vote or attendance is the worst failure. Rules:
- P1. Each extracted roll call is **Verified** (passes all automatic checks) or **Unverified** (any check fails or low confidence). Only Verified facts are shown as facts.
- P2. Checks per roll call: every member present has exactly one vote or an explicit non-vote; Yes/No/Abstain tallies equal the tally the minutes state; the passed/failed outcome agrees with the tally; names match the roster for that date.
- P3. **Unverified roll calls are held back** from commissioner pages and listed on an internal review page for Brian. They are never shown with a guessed value. (Decision: hold back rather than show with an "unverified" label, because a wrong vote under a named person is the harm. Revisit if too many are held back; see AC-P1.)
- P4. Each commissioner page states how many roll calls in the covered period are not shown because they are under review, with identical wording for everyone.
- AC-P1 The run reports Verified and held-back counts. For M1 to be done, at least 90% of roll calls are Verified; below that, parsing improves before anything widens.
- AC-P2 Spot check: 20 random shown votes across at least 4 commissioners and 4 years; all 20 match the PDF exactly (name, vote, motion, page). Any mismatch blocks release; the failing pattern gets a regression test, then a fresh 20.
- AC-P3 A hand-labelled test set of at least 15 roll calls (absences, abstentions, recusals, an oddly laid-out page) yields zero wrong votes; anything unparseable lands in Unverified, never as a wrong value.
- AC-P4 Scanned or image-only minutes are detected and marked "not extracted"; OCR output is shown only if it passes P2.

## Milestones
- **M1 (thin slice, real data):** Montgomery County Commission attendance and roll-call votes per commissioner from 2020-2024 minutes, every vote linked to the minutes PDF and page; searchable commission agendas; fully automated collection; private preview. Includes official pages with vote and comment history (US6) and item history pages (US7). Done when Brian picks a commissioner and sees every shown vote and comment with its source, opens an item and sees its full history, and the 20-vote spot check (AC-P2) all match.
- **M2:** County budgets (approved budget books) and audits (TN Comptroller): what, how much, linked to page.
- **M3:** County contracts: Bonfire awards, commission resolutions with dollar amounts, and which committee approved each.
- **M4:** City Council and committees from the clarksvilletn.gov Agenda Center (10 s crawl delay), same neutral display; find where post-May-2024 council records live.
- **M5:** Keyword alerts on new documents (any delivery that contacts real people is a hard stop).
Public launch is a separate decision by Brian after the private preview, not a milestone.

## Assumptions
- A1. Primary user is residents (confirmed). Brian is the only viewer until he decides otherwise.
- A2. **Focus Group skipped for M1**: private preview for the CEO only; revisit before public launch. **Brain Trust will run on this spec** (the neutrality and named-person accuracy risks warrant it).
- A3. 2025-2026 minutes location is unknown; M1 covers 2020-2024 minutes and agendas to the newest available. Finding 2025+ minutes is a task, not a goal change.
- A4. The minutes index sits on a dev host (`dev2.montgomerytn.gov`) that may move; the collector fails loudly rather than guessing, and robots.txt is re-checked at build time for `montgomeryminutes.bisonline.com`.
- A5. Minutes do not name vendors; contracts need other sources (M3).
- A6. What is shown will change with testing; every new fact type ships under the same source, fetch-date and correction rules.
- A7. Public documents only; no records requests (hard stop 4), no accounts or paid services without Brian.
- A8. Votes attach to named people, so the corrections path and conservative display (P1-P4) are product requirements, not polish.

## Success metrics
- 0 known wrong votes shown; 20/20 spot check; at least 90% of roll calls Verified in M1.
- 100% of shown facts have a source link and fetch date.
- Zero manual steps in a normal collection run; the collector never requests a robots-disallowed path (test-enforced).

## Open questions (change the goal)
None. Non-blocking, with defaults: (1) hold back vs label uncertain votes: default hold back (P3); (2) private-preview access: architect proposes the cheapest no-spend option.

## Later (not scheduled)
Video links, committee assignments, linking a vote to its budget line, Spanish-language view, CSV export.
