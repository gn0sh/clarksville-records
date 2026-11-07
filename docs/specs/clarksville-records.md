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

## Operator and governance (Brain Trust 2026-11-07, `docs/reviews/brain-trust-spec.md`)
- G0. **Update 2026-11-07:** the CEO is no longer a candidate (the election is over). The campaign-finance check was dropped from G6; disclosure (G1) and mechanical rules (G2) stay, since the site still names officials.
- G1. **Who runs it:** every page has a footer line naming the operator, linking to an About page that names him and states the data rules (CEO decision, 2026-11-07).
- G2. **Mechanical rules, no case-by-case calls:** held-back roll calls, name merges and corrections follow written rules applied identically to every official. The source document wins. Every change is logged in a public change history.
- G3. **The owner's own record**, if he holds office, appears under exactly the same rules.
- G4. **Skew check:** the held-back rate per official is measured each run. Release is blocked if an official with at least 50 roll calls in the period has a rate more than 2x the median of officials who sat in the same meetings. Holds caused by errors in the source document itself are reported separately and don't count. (Recalibrated after M0, 2026-11-07: on 11 PDFs the literal 2x-median rule flagged 8 commissioners only because one meeting's clerk error held back 3 roll calls for everyone in it. See `docs/research/m0-parse-spike.md`.)
- G5. **Open data:** all facts are exportable (CSV/JSON) with their sources, so the site is not the only copy.
- G6. **Before any public URL (hard stop):** G1 decided; correction intake working.
- G7. The private preview has no public URL (no public static hosting until G6).

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

**US6. As a resident, I want to click an elected official and see their whole record, so that I can see what they did.** (Brian, 2026-11-07: "vote and comment history")
- AC6.1 The official's page (US1) lists, in one date-ordered history, their recorded votes, attendance, and the motions and seconds the minutes attribute to them by name, labelled exactly "Moved" or "Seconded", with meeting date, item and source page. It is never labelled "comments": the county minutes record no spoken comments or discussion (platform-facts).
- AC6.2 Filterable by type and year; the same layout for every official (N1).
- AC6.3 Spoken comments need meeting video transcripts (Later list). If added, every line is labelled "transcript", links to its moment in the video, and is never paraphrased or summarised.

**US7. As a resident, I want to click a specific item and see its entire history, so that I can follow it from start to finish.** (Brian, 2026-11-07)
- AC7.1 An item page groups every appearance of the same item (resolution or ordinance number, e.g. "AB-4-2024", or the agenda item when unnumbered): each agenda listing, committee referral, reading, amendment, comment and roll call, in date order, each with its source page.
- AC7.2 Each roll call on the item page shows every member's recorded vote and the outcome.
- AC7.3 Items are linked by their official number; unnumbered items are linked only on an exact title match and show "linked by title" so a resident can judge it. Uncertain links are not made.
- AC7.4 Every vote row and comment on an official's page links to its item page.

## Parse accuracy and uncertain parses (top product risk)
A parse that misstates an official's vote or attendance is the worst failure. Rules:
- P1. Each extracted roll call is **Verified** (passes all automatic checks) or **Unverified** (any check fails or low confidence). Only Verified facts are shown as confirmed facts.
- P2. Checks per roll call: every member present has exactly one vote or an explicit non-vote; Yes/No/Abstain tallies equal the tally the minutes state; the passed/failed outcome agrees with the tally; names match the roster for that date. The roster comes from a source other than the vote being checked: the county's published commissioner list and terms where available, otherwise the same meeting's attendance header, with OCR name variants mapped by the written merge rules (G2).
- P3. **Unverified roll calls are shown, marked "*"** with "Not confirmed: this page was hard to read. Read it yourself" and a link to the exact source page, and are also listed on the internal review page for Brian. They are never shown with a guessed value: a vote whose name matches no official is placed under no one, and an unverified motion names no one ("Attribution under review"). (Decision: Brian, 2026-11-07, replacing the earlier hold-back rule; see `docs/status.md`.)
- P4. Each commissioner page states its roll call votes as two separate counts, confirmed and not confirmed (for example "12 Yes, 3 No confirmed; 2 Yes* not confirmed"), and one site-wide count of votes whose name could not be matched, with identical wording for everyone. A not confirmed vote never changes a confirmed count.
- AC-P1 The run reports Verified and held-back counts. For M1 to be done, at least 90% of roll calls are Verified; below that, parsing improves before anything widens.
- AC-P2 Spot check: 20 random shown votes across at least 4 commissioners and 4 years; all 20 match the PDF exactly (name, vote, motion, page). Any mismatch blocks release; the failing pattern gets a regression test, then a fresh 20.
- AC-P3 A hand-labelled test set of at least 15 roll calls (absences, abstentions, recusals, an oddly laid-out page) yields zero wrong votes; anything unparseable lands in Unverified, never as a wrong value.
- AC-P4 Scanned or image-only minutes are detected and marked "not extracted"; OCR output that fails P2 is shown only as not confirmed (marked "*", linked to its page), never as confirmed, and never with the raw OCR names or text.

## Milestones
- **M0 (parse spike):** about 10 county minutes PDFs across 2020-2024, deterministic parsing (no per-page LLM calls). Measure the Verified rate (P2) and held-back rate per official (G4). Below 90% Verified or skewed: back to the CEO before more build.
- **M1 (thin slice, real data, after M0 passes):** batch ingest of 2020-2024 commission minutes; official pages with votes, attendance, motions and seconds (US1, US2, US6) and item history pages (US7); every fact linked to its PDF page; automated scheduled collection (US4); private preview (G7). Done when Brian picks a commissioner and sees every shown vote with its source, opens an item and sees its full history, and the 20-vote spot check (AC-P2) all match.
- **M1.5 (before any public launch):** agenda search (US3), public correction intake (US5), find the 2025-2026 minutes, G6 checks.
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
None (G1 decided 2026-11-07). Non-blocking, with defaults: (1) hold back vs label uncertain votes: default hold back (P3); (2) private-preview access: architect proposes the cheapest no-spend option.

## Later (not scheduled)
Video links and transcripts (for spoken comments), committee assignments, handoff to a nonpartisan steward, linking a vote to its budget line, Spanish-language view, CSV export.
