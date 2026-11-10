# RPC motion invariant (loop rule: `attribution` hit 2, `verified-gate` hit 3)
software-architect, 2026-11-10. Source: docs/reviews/code-review-rpc-m2-0927bfe.md (findings 1-7). Extends rule 6 of
"Invariant: held-back counts" in clarksville-records.md ("show motion type only when unverified") to RPC minutes motions.

## The invariant
A motion is `confirmed` only when every value it shows is read from the minutes' own words and **nothing in its
sentences is left unexplained**: (C1) its case, if any, is a heading read on its own line, on the same meeting's agenda,
the only disposing motion in its section, and the motion names no other case; a caseless motion is meeting business
only; (C2) mover and seconder each resolve to one distinct member present; (C3) every vote word in its sentences sits
inside a modelled nay, abstain, favour or outcome span, and no nay/abstainer is the mover or seconder; (C4) one
outcome as printed; (C5) the minutes print the meeting's date. Any doubt: not confirmed, with a reason.
- Confirmed shows: type label, case placement, mover, seconder, nays and abstainers as printed, outcome as printed,
  page link. Nays are shown **only** as named; an empty list shows nothing. No page, feed or note ever writes
  "unanimous", "no one voted nay" or a derived tally: unanimity is never inferred from a missing nay.
- Not confirmed shows: type label, "Not confirmed" note and the page link. No names, outcome, tally, **case number**, and
  no placement under a case when the doubt is about the case (C1). `case_id` is set only when C1 holds.

## Rules, mapped to the review findings
| # | Decision | Rule the fix adds (collector/rpc_minutes.py unless named) |
|---|---|---|
| 1 | accept (widened by fix review 5769870 #2, `rpc-motion/c3-vote-words`) | `LEFTOVER_VOTE` (case-insensitive, a denylist, so wide on purpose) = `\bna[yv]s?\b\|against\|oppos\|dissent\|recus\|did not vote\|abstain\|voted no\|voting no` **plus** `vot\w*\s+["“”'‘’]?no\b` (voted "no", straight or curly quotes), `\bno\s+votes?\b`, any form of `vote` (`\bvot(e\|es\|ed\|ing)\b`), `not in favo(u)r`, `not support`, `negative`, `object`, `disagree`, `refrain`, `conflict of interest`, `ayes`/`noes`, and a tally (`5-1`, `5 to 1`) printed outside the outcome. Scan the motion's sentences (`after`) **plus everything after the outcome up to the next motion start or the section's end** (no character cap: a cap could only confirm more); any match outside a NAY/ABSTAIN/FAVOUR/outcome span of `after` -> reason "unmodelled wording: a vote word the reader does not read". The UNMODELLED patterns (tie, named in favour, except, amend) read the same span. "Nays: Mr. Long." is unmodelled, not parsed. Later option, not taken: an allowlist of sentence shapes. |
| 2 | accept | (a) `LOOSE_HEAD` = `C\s*A\s*S\s*E\s+N\S{3,6}R` on each line; a loose line the strict CASE_HEAD/LINE_CASE miss starts a new section with `case_ok=False` ("case heading not read"), so its motions never fall into the previous case, and it counts in `case_heads_printed`. (b) a case section with >1 disposing motion (kinds outside MEETING_KINDS and the consent/deferrals labels) -> every motion in it unconfirmed, "more than one motion on one case section", `case_id` None. No "modelled sequence" exception in this fix (any doubt); add one later only with a real-minutes test and a QA spot check. (c) a case number in the motion's sentences other than the section's -> unconfirmed, `case_id` None. (d) rpc_agenda.read_all_minutes: minutes headings read < agenda cases is reported in `problems` (not a gate: deferral lists carry no heading). |
| 3 | accept | NAY/ABSTAIN run only on text after the end of the seconder match (or the mover match when none); a nay/abstainer resolving to the mover or seconder -> "a member named as voting nay is the mover or seconder". |
| 4 | accept | rpc_agenda.read_all_minutes: `mv.case` not in `on_agenda` -> reason "case number not on this meeting's agenda". Two sections with the same case number in one minutes -> both unconfirmed, "case section repeated". |
| 5 | accept | A caseless section (before the first case, OTHER BUSINESS etc.) confirms only meeting-business kinds: MEETING_KINDS, consent agenda, deferrals/withdrawals list. Any other kind -> "subject not read". |
| 6 | accept (nit) | rpc_agenda.build writes `build/rpc-motions-audit.jsonl` (id, page, reasons, `para`): internal, never under build/site, never committed. data/ocr stays uncommitted (size). QA samples from it. |
| 7 | accept part | Rule 2a roster fallback only when the header shows a garbled member line (a member-column line that failed MEMBER_NAME); else "mover/seconder is not one member present". **Reject** the title-gender check: inferring gender from a first name is a guess and not neutral; a wrong title already fails exact surname matching often enough. |
| 8 | accept (fix review 5769870 #1, `rpc-motion/c3-stale-record`) | `rpc_minutes.MOTION_RULES` (`"rpc-motion-invariant-1"`): rpc_agenda.build writes it into rpc.json as `motion_rules` (schema stays `rpc-1`). sitegen/rpc.py `shown_motions` and qa/site_checks.py restate it: a record whose `motion_rules` is not the current value shows **every** motion not confirmed, reason "record written before the motion invariant", and `case_id` None (rules 1-3, 7 never ran on it, so C1 is in doubt too). Change the value whenever a rule changes what is confirmed. With the committed rpc.json (no marker) the pages show 0 confirmed motions until the rebuild: intended. |
Also: module docstring rules 1-6 restated with C1-C5; reasons stay plain text in `reasons` (never shown publicly).

## Every consumer and what it must do
| Consumer | Where | Must |
|---|---|---|
| Reader | `rpc_minutes.read_minutes`, `read_motions`, `Motion.confirmed`, `MinutesReading.case_heads_*`, `sections` | apply rules 1-5, 7; `confirmed` stays `not reasons` |
| Attach | `rpc_agenda.read_all_minutes` | rule 4; set `case_id` only if confirmed or the reasons carry no C1 reason; date gate; summary counts `motions_confirmed`, `motions_on_agenda_cases` follow |
| Report | `rpc_agenda.build` summary, `collector/rpc.py main` -> build/rpc-report.json | add count per reason; audit file (rule 6) |
| Committed record | `data/localities/cmc-rpc/rpc.json` | internal record like data/facts.json: keeps raw values of unconfirmed motions (repo is public: same accepted pattern as the county file). Any future site export must strip them as `collector/export.py` does. Carries `motion_rules` (rule 8); every page consumer goes through `Rpc.motions` (`shown_motions`), never `facts["motions"]` directly |
| Motion context | `sitegen/rpc.py Rpc.motion` | when not shown: `moved_by`, `seconded_by`, `nays`, `abstained`, `outcome` None/[] (as now) **and `case` None** (today it leaks an off-agenda case number on unconfirmed motions) |
| Placement | `Rpc.__init__` motions_by_case / motions_by_meeting; `Rpc.meeting` `cases[].motions`, `other_motions`, `n_motions` | placement from `case_id` only; C1-doubtful motions land in "Other motions" without a case |
| Home count | `Rpc.home` `n_motions_confirmed`; rpc_home.html.j2 line 8 | count only; wording claims nothing about unanimity |
| Templates | `_rpc.html.j2 rpc_motion`; `rpc_meetings_year.html.j2` lines 94-110 | values only inside `{% if mv.confirmed %}`; drop `({{ mv.case }})` from the unconfirmed line; never print "unanimous"/"no nays" |
| CZ -> county link | `Rpc.link_county`, `county_item`, `rpc_minutes.link_key`; `views.item` `"rpc"` (views.py:903); items_year.html.j2 37-41 | links agenda cases only, never a motion or outcome. Any future "RPC recommended X" on a county item uses only a confirmed motion with `case_id` |
| Days/today | `sitegen/days.py rpc_card`; today.html.j2 32-41 | shows agenda cases only; ctx carries motions, so any future motion line must use `rpc_motion` |
| Search | `Rpc.search_records`, `views.search_index` | no motion fields; must stay so |
| Feeds | `sitegen/feeds.py` (no RPC today); morning-note plan adds RPC cases to topic-rezoning.xml | agenda entries only; a motion entry follows the morning-note rule below |
| Morning note | docs/architecture/morning-note.md "New today" `vote` entries, "zoning" list | an RPC minutes `vote` entry carries outcome/tally only when confirmed, else "Recorded in the minutes; not confirmed"; joins the zoning list by district/ward only via `case_id` (C1), never via an unconfirmed `case`. Task list docs/tasks/morning-note.md must cite this file |
| QA | `qa/site_checks.py` (only `rpc-cases` today; `attribution_shown`/`check_unverified` cover county facts only) | new `rpc-motions` check below |
| Tests | collector/tests/test_rpc_minutes.py, tests/test_rpc_minutes_pages.py, test_rpc.py | `test_motions_after_other_business...` (P&L approval caseless) must flip to unconfirmed; deferrals-list test stays confirmed |

## Tests the fix must add (each asserts `not confirmed` and the reason unless noted)
- Finding 1, one each: "Mr. Long opposed.", "Voting nay were Mr. Long and Mrs. Streetman.", "Mr. Long voted nav.",
  "Mr. Long recused himself.", "Mr. Long dissenting.", "Nays: Mr. Long.", "Mr. Long did not vote.", a nay in the sentence
  after "Motion passed."; plus a control: "Mrs. Streetman voted nay. All others were in favor." stays confirmed.
  Fix review 5769870 #2, one each: voted "no" (straight and curly quotes), "was not in favor" (before and after the
  outcome), "cast the only no vote", "with one no vote", "voting in the negative", "objecting", a nay two sentences
  after the outcome; controls: words after the outcome with no vote word, and the scan stopping at the next motion.
- Mangled heading: "CASE NUMBFR: Z-6-2026" and "C ASE NUMRER" between two cases -> the second case's motion is not under
  the first; `case_heads_printed` counts it. A section with two approvals -> both unconfirmed, `case_id` None.
- Seconder swallow: "seconded by Mr. Powers and Mrs. Streetman voted nay" -> nays == ["Mrs. Streetman"] or unconfirmed,
  never Mr. Powers; mover named as nay -> unconfirmed. Motion text naming another case -> unconfirmed.
- Off-agenda case (read_all_minutes fixture: ZO-4-2024 not on agenda) -> unconfirmed; repeated case section -> both.
- Caseless: "Motion for approval" / "Motion to defer" / bare "Motion" before the first case or under OTHER BUSINESS ->
  "subject not read"; minutes, adjourn, elect, consent, deferrals list -> confirmed.
- Pages: an unconfirmed off-agenda motion block shows no case number; no page text "unanimous" from our templates.
- Finding 7: garbled-header fallback confirms; clean header with an absent member's name -> unconfirmed.

## site_checks guard (warranted: the family has hit 3 times and no RPC motion check exists)
`rpc-motions`, restated independently from rpc.json (no import from collector): (a) every block `#<motion id>` whose
motion lacks `confirmed: true` holds none of its moved_by/seconded_by/nays/abstained/outcome/case strings, nor
"Moved by"/"Outcome, as printed"; (b) no `case_id` with >1 confirmed disposing motion; (c) every confirmed motion has a
`case_id` on its meeting's agenda or a meeting-business kind; (d) no confirmed nay/abstainer equals its mover/seconder;
(e) no page with RPC content (every `<slug>/` page, index.html, today.html, any page with an RPC day card or motion
block) contains "unanimous" outside a `data-item-title` span; (f) when rpc.json's `motion_rules` is not the current
value, no block is shown confirmed and every block is held to (a). Per-case counts in (b) are sets of motion ids.

## Re-running the build (OCR needed)
`python -m collector rpc build` re-OCRs every scanned minutes page: the OCR cache (data/ocr, RECORDS_OCR_CACHE) is not
committed. The store is being refetched in this container at /home/user/clarksville-records/data/store (set
RECORDS_STORE); at writing it holds 19 files, tesseract is **not installed** (`apt-get install tesseract-ocr`;
pdftoppm is present). Do not commit a rebuilt rpc.json until the store is complete: a missing file is listed with no
source, so a partial store silently shrinks the data. Check 97 meetings / 168 sources before committing, and paste the
before/after confirmed counts (1307 motions, 1088 confirmed at 0927bfe) by reason into the PR.

## Implementation notes (backend-engineer, 2026-11-10; deviations called out)
- **Record-level re-check in sitegen** (`sitegen/rpc.py record_doubts`/`shown_motions`): the checks rpc.json alone
  allows are applied again at page time, so a record written before this fix never shows more: C1 off-agenda case
  (`case` set, `case_id` None), >1 disposing motion for one case at one meeting, caseless non-business kind; C3 a
  nay/abstainer whose surname is the mover's or seconder's. C1 doubts also drop the placement. Needs a rebuild:
  rule 1 vote words, 2a loose headings, 2c another case named, rule 3 seconder swallow, rule 7 roster.
- **site_checks `rpc-motions` (b)-(d) judge the blocks the pages show confirmed** (no `nc` class), not the raw record,
  and any block shown confirmed must be `confirmed: true` in rpc.json. On the committed record the stricter raw form
  would fail until the rebuild; the page form is what readers see and passes now.
- **Caseless relabel**: with no case, a "Motion for approval"/bare "Motion" whose outcome as printed is "deferrals
  were approved" / "minutes were approved" / "consent agenda passed" takes that fixed business label (keeps the
  deferrals-list test confirmed and site_checks (c) strict on kinds).
- **Rule 7 "garbled member line"**: a members'-column line whose first cell fails MEMBER_NAME, or a one-column line
  that splits into more than one cell ("Bill Kimb   h").
- **Rule 3** uses the same reason for an abstainer who is the mover/seconder.
- **Expected loss**: 2022-layout minutes approvals ("asked for a motion for approval of the minutes. Mrs. Streetman
  moved to recommend approval") read as "Motion for approval" with no case and become "subject not read". A later
  rule could read the "Approval of Minutes" heading; not added (any doubt).
