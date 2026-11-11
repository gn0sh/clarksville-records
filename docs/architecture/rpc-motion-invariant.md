# RPC motion invariant (loop rule: `attribution` hit 2, `verified-gate` hit 3, `rpc-votes` hits 1-4)
software-architect, 2026-11-10; restated 2026-11-11 for `rpc-votes` (QA hits `outcome-not-printed`,
`abstain-before-motion`; code review of bb7c6d1 `except-after-outcome`, `fav-rest-denylist`, `tail-outcome`,
`tests-not-pinning`). Source: docs/reviews/code-review-rpc-m2-0927bfe.md (findings 1-7). Extends rule 6 of
"Invariant: held-back counts" in clarksville-records.md ("show motion type only when unverified") to RPC minutes motions.

## The invariant
A motion is `confirmed` only when every value it shows is read from the minutes' own words and **every vote statement
in its whole scope is read and attributed to exactly one motion**: (C1) its case, if any, is a heading read on its own
line, on the same meeting's agenda, the only disposing motion in its section, and the motion names no other case; a
caseless motion is meeting business only; (C2) mover and seconder each resolve to one distinct member present; (C3) its
body is made only of the known sentence shapes (rule 10a), and its lead, tail and list scope hold no vote statement that
is not attributed (rules 10b-10e); no nay/abstainer is the mover or seconder; (C4) one outcome as printed, and none
after it; (C5) the minutes print the meeting's date. Any doubt: not confirmed, with a reason.

**Scope** of motion m in section S. S runs from its heading line (a case heading, a loose heading or a SECTION_END
heading; the first section from the document's first line) to the next such heading or the document's end.
- body(m): m's sentences, from the mover's name to the end of its outcome sentence (`para`).
- lead(m): S's start to m's start for S's first motion; else the text after the previous motion's body.
- tail(m): end of body(m) to the next motion's start in S, or S's end. tail(m_k) and lead(m_k+1) are the same text: a
  doubt there counts for both motions; a statement there is attributed to neither (10c's only lead attribution needs
  m to be S's first motion).
- list scope, only for a list motion (kind "Motion to approve the consent agenda" or "Motion to approve the
  deferrals"): also the whole text of every case section of the same minutes that holds no motion of its own (the
  cases a list motion disposes are not otherwise read; a meeting with two list motions puts such a section in both).

**Consent agenda and per-case abstentions.** A list motion is one vote that disposes several cases. "Cindy Greene
abstained from SR-42-2026." means she abstained on that case only. rpc-1 holds one `abstained` list per motion:
writing her there says she abstained on the whole list, leaving her out says she voted for SR-42-2026; neither is as
printed. So: an abstention naming the case the motion is placed under (its section's case) is that motion's
abstention ("Mr. Powers abstained from S-81-2022" on the consent motion under S-81-2022); an abstention naming any
other case of a list motion makes it not confirmed, reason WHY_LIST_PART ("a member abstained on one case of a list
the motion approved"). **Shown:** the list motion as Not confirmed everywhere (type label, note, page link; no export
row, counted in `motions_not_confirmed`; morning note "Recorded in the minutes; not confirmed"); SR-42-2026 shows its
agenda entry only. Later option, not taken (1 known case): schema rpc-2 with `abstained_on: [{name, case}]` shown as
"Abstained on SR-42-2026, as printed: Cindy Greene."
- Confirmed shows: type label, case placement, mover, seconder, nays and abstainers as printed, outcome as printed,
  page link. Nays are shown **only** as named; an empty list shows nothing. No page, feed or note ever writes
  "unanimous", "no one voted nay" or a derived tally: unanimity is never inferred from a missing nay.
- Not confirmed shows: type label, "Not confirmed" note and the page link. No names, outcome, tally, **case number**, and
  no placement under a case when the doubt is about the case (C1). `case_id` is set only when C1 holds.

## Rules, mapped to the review findings
| # | Decision | Rule the fix adds (collector/rpc_minutes.py unless named) |
|---|---|---|
| 1 | accept (widened by fix review 5769870 #2, `rpc-motion/c3-vote-words`) | `LEFTOVER_VOTE` (case-insensitive, a denylist, so wide on purpose) = `\bna[yv]s?\b\|against\|oppos\|dissent\|recus\|did not vote\|abstain\|voted no\|voting no` **plus** `vot\w*\s+["“”'‘’]?no\b` (voted "no", straight or curly quotes), `\bno\s+votes?\b`, any form of `vote` (`\bvot(e\|es\|ed\|ing)\b`), `not in favo(u)r`, `not support`, `negative`, `object`, `disagree`, `refrain`, `conflict of interest`, `ayes`/`noes`, and a tally (`5-1`, `5 to 1`) printed outside the outcome. Scan the motion's sentences (`after`) **plus everything after the outcome up to the next motion start or the section's end** (no character cap: a cap could only confirm more); any match outside a NAY/ABSTAIN/FAVOUR/outcome span of `after` -> reason "unmodelled wording: a vote word the reader does not read". The UNMODELLED patterns (tie, named in favour, except, amend) read the same span. "Nays: Mr. Long." is unmodelled, not parsed. Later option, not taken: an allowlist of sentence shapes. |
| 2 | accept (widened by fix review 5769870 #3, `rpc-motion/c1-case-heading`) | (a) `LOOSE_HEAD` = `C\s*A\s*S\s*E\s+N\S{3,6}R` anywhere on a line, **or**, near the line's start (after an item number), a mangled CASE word in any case, `[CG]\s*[A4]\s*[S5$§]\s*[EF]\s*(N\S{0,6}\|#)` ("GASE NUMBER", "CASF NUMBER", "Case Numbr", "CASE NO.", "CASE #"); a loose line the strict CASE_HEAD/LINE_CASE miss starts a new section with `case_ok=False` ("case heading not read"), so its motions never fall into the previous case, and it counts in `case_heads_printed`. (b) a case section with >1 disposing motion (kinds outside MEETING_KINDS and the consent/deferrals labels) -> every motion in it unconfirmed, "more than one motion on one case section", `case_id` None. No "modelled sequence" exception in this fix (any doubt); add one later only with a real-minutes test and a QA spot check. (c) a case number in the motion's sentences other than the section's -> unconfirmed, `case_id` None. (d) rpc_agenda.read_all_minutes: minutes headings read < agenda cases is reported in `problems` (not a gate: deferral lists carry no heading). (e) a case section whose text, **anywhere** (not only a motion's sentences), prints another case number on this meeting's agenda (read by `read_number`, so a misread prefix is repaired only onto the agenda: "2-6-2026", "Z - 06 - 2026") -> every motion in it unconfirmed, "the case section prints another case on this meeting's agenda" (a C1 reason, `case_id` None). A case number not on the agenda ("an earlier rezoning, Z-3-2015") outside the motion's sentences does not count. |
| 3 | accept | NAY/ABSTAIN run only on text after the end of the seconder match (or the mover match when none); a nay/abstainer resolving to the mover or seconder -> "a member named as voting nay is the mover or seconder". |
| 4 | accept | rpc_agenda.read_all_minutes: `mv.case` not in `on_agenda` -> reason "case number not on this meeting's agenda". Two sections with the same case number in one minutes -> both unconfirmed, "case section repeated". |
| 5 | accept | A caseless section (before the first case, OTHER BUSINESS etc.) confirms only meeting-business kinds: MEETING_KINDS, consent agenda, deferrals/withdrawals list. Any other kind -> "subject not read". |
| 6 | accept (nit) | rpc_agenda.build writes `build/rpc-motions-audit.jsonl` (id, page, reasons, `para`): internal, never under build/site, never committed. data/ocr stays uncommitted (size). QA samples from it. |
| 7 | accept part | Rule 2a roster fallback only when the header shows a garbled member line (a member-column line that failed MEMBER_NAME); else "mover/seconder is not one member present". **Reject** the title-gender check: inferring gender from a first name is a guess and not neutral; a wrong title already fails exact surname matching often enough. |
| 8 | accept (fix review 5769870 #1, `rpc-motion/c3-stale-record`) | `rpc_minutes.MOTION_RULES` (`"rpc-motion-invariant-1"`): rpc_agenda.build writes it into rpc.json as `motion_rules` (schema stays `rpc-1`). sitegen/rpc.py `shown_motions` and qa/site_checks.py restate it: a record whose `motion_rules` is not the current value shows **every** motion not confirmed, reason "record written before the motion invariant", and `case_id` None (rules 1-3, 7 never ran on it, so C1 is in doubt too). Change the value whenever a rule changes what is confirmed. With the committed rpc.json (no marker) the pages show 0 confirmed motions until the rebuild: intended. |
| 9 | accept (QA vote sample 2026-11-11, `rpc-votes/outcome-not-printed`, `rpc-votes/outcome-phrase-choice`; MOTION_RULES -> `"rpc-motion-invariant-2"`) | C4: an "All ... in favor" sentence is the outcome as printed only when the rest of its sentence names no exception (except, but, save, other than, excluding, apart from, "and the motion"), no member and no vote word ("All members voted in favor, meeting was adjourned at 4:48 p.m." stays), no member is read as voting nay or abstaining, and no vote word follows it up to the next motion. "All members voted in favor, except Cindy Greene who abstained and Bill Kimbrough who voted against." (no outcome sentence) stores **no** outcome and is not confirmed, reason "no outcome printed: the 'in favor' sentence goes on or members are named as voting nay or abstaining"; this also covers "Mrs. Streetman voted nay. All others were in favor." with no outcome sentence (stricter than the earlier control). OUTCOME also reads "Motion was approved on (the) consent agenda", so that printed sentence is preferred to the "All others voted in favor." before it. Recall (`rpc-votes/recall-miss`): FAVOUR also reads "All others voted in favor and the motion passed ..." (the outcome must follow in that sentence, else no outcome), and an outcome's "for ..." words may hold a count of days ("passed for a 30 day deferral"); no other number, so a tally is never swallowed and always meets the tally check. |
| 10 | accept (`rpc-votes` hits 1-4: QA 2026-11-11 `abstain-before-motion`; review of bb7c6d1 `except-after-outcome`, `fav-rest-denylist`, `tail-outcome`, `tests-not-pinning`; MOTION_RULES -> `"rpc-motion-invariant-3"` in rpc_minutes.py:207, sitegen/rpc.py:58, qa/site_checks.py:217) | **(a) body allowlist** (supersedes rule 1's "Later option, not taken"): body(m) is the mover clause, then only clauses from a fixed `SHAPES` list, in this order: one *second* (`seconded by M`, `Motion was seconded by M`, `M seconded[ it\| the motion]`, `with M second[ing]`, `second from M`); any *vote* clauses (`M[, M and M] voted nay\|no\|against\|in opposition`, `M abstained[ from voting\| from the vote\| from <case>\| on <case>]`, `All [others\|other members\|members[ present]] were\|voted in favor`, `[All ]others [were ]in favor`, `except [for ]M who abstained\|voted against\|nay\|no\|was against [and M who ...]`, `but M who ...` same verbs); exactly one *outcome* (OUTCOME, `consent agenda passes with approval`, `cases were approved for deferral[s]`, `meeting was adjourned at H:MM p.m.`, optionally `with M[ and M] voting nay\|against`); joined only by `. `, `, `, `; ` or ` and `; then the end. The mover clause's own words (type, "stating that ...", "based on ...") are free text but hold no member surname, no titled name (`HON` + capital), no LEFTOVER_VOTE word, no except/but/exception; sole exception, `to nominate\|elect M as\|for [Vice ]Chair[man\|woman\|person][ for 20NN]`. Anything else -> WHY_UNLISTED "a sentence of the vote is not one the reader knows". FAVOUR_EXCEPT, the NAME_RX/LEFTOVER_VOTE checks on the "in favor" rest and the `\bexcept\b` loop (rpc_minutes.py:123, :410-416, :491-497) are then dead and are deleted. **(b) tail**: LEFTOVER_VOTE as now, **plus** any OUTCOME, FAVOUR or `\bmotion\b` match -> WHY_TAIL_OUTCOME "an outcome, 'in favor' or a motion is printed after the outcome" (no FOLLOW_GAP limit; closes `tail-outcome`). **(c) lead and list scope**: free prose (staff report, public hearing), so a trigger list, narrower than LEFTOVER_VOTE: `MEMBER_VOTE` = `abstain\|recus\|conflict\|did\s+not\s+vote\|not\s+vot\|refrain\|\bna[yv]s?\b\|\bvot(e\|es\|ed\|ing)\b`. Not against/oppos/negative/in favor/except/but/motion: in the four OCR fixtures both lead hits of the wide list were prose ("Russell Harris spoke against", "can negatively affect"). Every match outside an attributed sentence -> WHY_LEAD_VOTE "a vote statement outside the motion is not read". Attributed: a lead sentence that is exactly the abstain shape, when S is a case section, m is S's **first** motion and disposing, and the sentence names no case or S's case -> m.abstained. **(d) case-named abstentions** (lead or body): S's case -> attributed; another case and m a list motion -> WHY_LIST_PART; else WHY_OTHER_CASE / WHY_LEAD_VOTE. No nay, recusal, conflict or "did not vote" is ever attributed from a lead or tail. **(e) attributed abstainers** pass the same checks as body ones (member present, not mover/seconder, rule 9 "in favor" outcome). Cost estimate below. |
Also: module docstring rules 1-6 restated with C1-C5; reasons stay plain text in `reasons` (never shown publicly).

## Every consumer and what it must do (re-listed with file:line at bb7c6d1, 2026-11-11)
"Assumes" is what the consumer takes `confirmed`, `outcome`, `nays`, `abstained` to mean today. Rule 10 changes only
what the reader confirms; the record shape (rpc-1) is unchanged. 21 consumers; **1 needs a change beyond the parser**
(#15, marked **change**); #6 and #20 need the MOTION_RULES bump; the rest need only the rebuild. No new site_checks check: rule 10
is about the minutes' text, which rpc.json does not hold, so its guard is the mutation table below, not a page check.

| # | Consumer | Where | Assumes | Rule 10 |
|---|---|---|---|---|
| 1 | Reader | collector/rpc_minutes.py:396 `read_motions`, :536 `read_minutes`, :350 `Motion.confirmed`, :135 ABSTAIN, :170 LEFTOVER_VOTE | `confirmed` = `not reasons`; nays/abstained from body after the seconder only | the fix: rules 10a-e; `read_motions` needs the section's lead and, for list motions, the motionless case sections (read_minutes:575 loop builds them) |
| 2 | Attach | collector/rpc_agenda.py:501 `read_all_minutes`, :559-571 | a motion's reasons are final; `case_id` only with no CASE_REASONS | WHY_LIST_PART and WHY_LEAD_VOTE are not CASE_REASONS (placement stays); none |
| 3 | Record writer | collector/rpc_agenda.py:464-474 `build` (`motion_rules`), :483 audit | — | writes `rpc-motion-invariant-3`; recommended, not required: audit rows add the lead text scanned (`lead`), so QA can sample it |
| 4 | Report | collector/rpc.py:290 `main` -> build/rpc-report.json `motions_not_confirmed_by_reason` | reasons are plain strings | new reasons counted automatically |
| 5 | Committed record | data/localities/cmc-rpc/rpc.json | all page consumers read it through `Rpc.motions` | rebuild (OCR) and commit with before/after counts |
| 6 | Stale gate + record re-check | sitegen/rpc.py:58 MOTION_RULES, :67 `record_doubts`, :96 `shown_motions` | a record under other rules shows nothing confirmed | bump :58 |
| 7 | Placement | sitegen/rpc.py:148-153 `Rpc.__init__`, :246 `meeting` (`cases[].motions`, `other_motions`) | placement from `case_id` only | none |
| 8 | Motion block | sitegen/rpc.py:201-213 `motion`; site/templates/_rpc.html.j2:18-27; rpc_meetings_year.html.j2:69, :82 | confirmed => nays/abstained are complete for the placed case; empty list prints nothing | none (holds once the parser enforces 10d) |
| 9 | RPC home count | sitegen/rpc.py:301; rpc_home.html.j2:8 | count only | none |
| 10 | County zoning trail | sitegen/rpc.py:167 `link_county`, :195 `county_item`; views.py:921; items_year.html.j2:37-41 | agenda cases only, never a motion | none; must stay so |
| 11 | Official vote history | views.py:401 `official_counts`, :650 `official`; official.html.j2 | county/council roll calls only; RPC has no officials in the facts (views.py:1539) | none; an RPC motion must never be counted for an official until a spec says so |
| 12 | Day cards | sitegen/days.py:177 `rpc_card` (ctx from `rpx.meeting`); today.html.j2:15, :32-41 | agenda cases only | none |
| 13 | Search | sitegen/rpc.py:309 `search_records`; views.py:1517, :1539 | no motion fields | none |
| 14 | Feeds | sitegen/feeds.py:258 `_rpc_cases`, :274 `_rpc_entries` | agenda cases only | none |
| 15 | **Morning note** | sitegen/morning.py:484 `_rpc_documents`, **:492** reads `rpx.facts["motions"]`, **:499** raw `case_id`, **:511** raw `confirmed` | that the raw record's `confirmed` and `case_id` are what pages show | **change**: iterate `rpx.motions` (shown_motions), not `rpx.facts["motions"]`. Today a stale record or a `record_doubts` motion is "confirmed" with its outcome/tally in the note while the page says Not confirmed, and is joined to the zoning list by a case_id the pages dropped. Rebuilding does not fix it |
| 16 | Zoning list | sitegen/morning.py:337 `_Zoning`, :356 `is_zoning` | cases, joined to motions via `case_id` | follows #15 |
| 17 | Sender | sender/render.py:9 (module rule), sender/plan.py, sender/deliver.py | renders the note's entries, no outcome, tally or names | none; inherits #15 |
| 18 | Public export | collector/rpc_export.py:142 `exported_motions`, :152 `public_facts`, :183-190 rows, :232 CSV; views.py:1606 `data_page`, data.html.j2:20 | rows only for `rpx.motions` confirmed and placed; `abstained` complete | none |
| 19 | Export file count | sitegen/build.py:234 | file list only | none |
| 20 | QA guard | qa/site_checks.py:217 RPC_MOTION_RULES, :231 `check_rpc_motions`, :333 `check_rpc_export` | restates the gate and the held fields | bump :217 |
| 21 | Tests | collector/tests/test_rpc_minutes.py, tests/test_rpc_minutes_pages.py (:193, :241 pin MOTION_RULES), tests/test_export_rpc.py, tests/test_morning.py, collector/tests/test_rpc.py, collector/tests/test_provenance.py | — | add the rule 10 tests below; bump the pins; tests/test_morning.py adds a stale-record and a `record_doubts` case (#15) |

## Allowlist or denylist (decision, 2026-11-11)
Four `rpc-votes` hits came from denylists of words that make a motion unsafe; each fix added words and the next review
found another ("exception", "excepted", "minus one"). **Decision: the motion's body is an allowlist (rule 10a); lead,
tail and list scope stay trigger lists (10b, 10c)**, because they are free prose (staff reports, public hearing,
discussion) that no small set of shapes covers; there the trigger is the narrow test "does any sentence state a
member's vote", and a later outcome or motion in a tail is now a trigger too.
- Alternative steelmanned, a pure denylist with the review's words added: cheapest, keeps every confirmed motion, but
  the family shows the list is never finished, and a miss is a wrong public vote. Rejected.
- Alternative, an allowlist over every sentence in scope: safest, but it would confirm almost no case motion (every
  staff report and public-hearing sentence fails it). Rejected.
- **Cost, measured** (spike, scratchpad only, not committed: the rule 10a shapes run over the sentences of the 638
  motions confirmed at bb7c6d1, taken from the a678890 audit): **599 of 638 stay confirmed (94%)**, 39 lost. 27 of the
  39 have a member's name, a vote word, "except" or "favor" in the unlisted text (unsafe or ambiguous anyway); 12 are
  benign (OCR noise "ue"/"eee" after the outcome, a commissioner's comment inside the vote). Rule 10c adds 2 benign
  losses (QA's sweep: "not voting on the cell tower", a denied conflict of interest), 1 WHY_LIST_PART (2026-06-23-
  regular-motion-3) and 1 gain of an abstainer (2024-10-29-regular-motion-13). Expect about 595 confirmed.
- **Found by the spike: a live wrong record.** 2022-03-29-regular-motion-10 is confirmed with nays [] and abstained []
  at bb7c6d1, but prints "All were in favor with the exception of Mr. Powers." (Powers' vote is not stated). Rule 10a
  makes it not confirmed. QA: add it to the next sample.
- Reversible (a parser rule plus a rebuild), internal, no hard-stop area: no Brain Trust needed.

## Rule 10 tests the fix must add
Harness: the probe's page (scratchpad/probe.py `one()`: a members header with Wade Hadley, Bryce Powers, Stacey
Streetman, Bill Kimbrough, Michael Long, then "CASE NUMBER: Z-5-2026" on an agenda holding Z-5-2026), M = "Mr. Hadley
made the motion for approval. Mr. Powers seconded. ". Each asserts the confirmed flag, the reason, and nays/abstained; a name outside that roster (Cindy Greene, Joe Smith,
Jeff Henley ...) is added to that test's header, and a case it names to that test's agenda unless it says "off the agenda".
**Not confirmed** (reason in brackets), M + each of:
- review #1 [WHY_UNLISTED]: "All others voted in favor and the motion passed with the exception of Mr. Long." / "All
  others voted in favor. Motion passed with the exception of Mr. Long." / "All members voted in favor and the motion
  passed, Mr. Long excepted." / real 2022-03-29-regular-motion-10: "All were in favor with the exception of Mr.
  Powers. Motion for disapproval passed." (mover Mr. Rocconi, seconder Mrs. Streetman in its own header).
- review #2 [WHY_UNLISTED]: "All members voted in favor, minus one." / ", apart from one member." / ", other than
  one." / ", but one." / ", except one." / "All members present voted in favor, with one member not voting." / "All
  voted in favor, 6-1." / "All members voted in favor, while Mr. Long was absent." / "All members voted in favor;
  Long was absent." / "...passed for a 30 day deferral, 5 to 1." / "...deferral 5 1." / "...to the 4-1 meeting."
- review #3 [WHY_TAIL_OUTCOME]: "All members voted in favor. Staff then presented the next case about the road
  widening plan. The motion failed." / "All others were in favor. Motion passed. Mr. Long asked to reconsider the
  motion." / "All others were in favor and the motion failed." stays a single outcome and is **confirmed** (control).
- consent wording [WHY_UNLISTED]: "Motion was approved on the consent agenda, Mr. Long abstaining." / "... except for
  Mr. Long." / "All members were in favor. Motion was approved on the consent agenda pulled by Mr. Long for separate
  vote." / "... with Mr. Long recused." / "The case was removed from the consent agenda. Motion was approved on the
  consent agenda." / "All members were in favor and the motion passed unanimously 4-1." [tally mismatch].
- mover clause [WHY_UNLISTED]: "Mr. Hadley made the motion for approval stating Mr. Long agreed. Mr. Powers seconded.
  All others were in favor. Motion passed." / "...for approval with Mr. Long voting against. ..."
- `abstain-before-motion`, lead [as noted]: in Z-5-2026's section, before M: "Mr. Long voted nay." / "Mr. Long recused
  himself." / "Mrs. Streetman declared a conflict of interest." / "Mr. Long did not vote." [WHY_LEAD_VOTE each]; in the
  section before the first case, "Mr. Long abstained." then a minutes approval [WHY_LEAD_VOTE]; "Mr. Long abstained."
  between two motions of one case section [WHY_LEAD_VOTE + WHY_TWO]; a caseless consent motion and a later case
  section with no motion that prints "Mr. Long abstained." [WHY_LEAD_VOTE, list scope].
- real 2026-06-23-regular-motion-3 [WHY_LIST_PART, abstained == [], its page block shows no name]: before any case,
  "Cindy Greene abstained from SR-42-2026. Joe Smith made a motion to approve the consent agenda, seconded by Stacey
  Streetman. All members voted in favor. Motion passes for approval." (SR-42-2026 on the agenda); same with
  SR-42-2026 off the agenda [WHY_LEAD_VOTE]; the consent motion under S-81-2022 with "Mr. Powers abstained from
  S-79-2022." in its body, S-79-2022 on the agenda [WHY_LIST_PART].
- negative controls, no nay or abstainer is ever read from them (nays == abstained == []) and the motion is not
  confirmed [WHY_LEAD_VOTE; cost accepted, no benign-phrase allowlist]: "Mrs. Streetman stated she has no conflict of
  interest." (2025-06-24-regular-motion-23) and "Mr. Powers noted the Commission is not voting on the cell tower."
  (2022-05-24-regular-motion-22), each in the lead.
**Confirmed** (pins each shape and the narrow lead list):
- real 2024-10-29-regular-motion-13: section S-73-2024, "Stacey Streetman abstained from voting. Bill Kimbrough made a
  motion for approval, seconded by Jeff Henley. All others voted in favor. Motion was approved on consent agenda." ->
  abstained == ["Stacey Streetman"], outcome "Motion was approved on consent agenda". Same with "abstained from
  S-73-2024." -> same. Real 2022-09-27-regular-motion-16: "Mr. Powers abstained from S-81-2022." in the body of the
  consent motion under S-81-2022 -> abstained == ["Mr. Powers"].
- lead prose with no member vote: "Russell Harris spoke against stating concerns such as traffic." / "The proposed
  C-5 zoning can negatively affect the area." / "No one spoke in opposition." / "Chairman Swift asked for a motion."
- one test per SHAPES entry, each from a real para: "Mr. Powers seconded." / "Motion was seconded by Mrs. Jiminez." /
  ", seconded by Jeff Henley." / "Seconded by David Smith." / "with Mrs. Streetman second" / "Stacey Streetman
  seconded it." / "Mrs. Streetman voted nay." / "Mr. Powers abstained and all others were in favor." / "All members
  voted in favor, except Cindy Greene who abstained and Bill Kimbrough who voted against. Motion passes for approval
  4-1." / "All members voted in favor, but Michael Long who was against. Motion passes for approval 4-1."
  (2026-09-22-regular-motion-6) / "but Bert Singletary who abstained" (2026-07-27-cdrb-motion-7) / "All were in favor
  and motion passed." / "All others voted in favor, consent agenda passes with approval." / "All voted in favor, cases
  were approved for deferral." / "Motion for disapproval passed 4-2 with Mr. Kimbrough and Mr. Long voting nay."
  (2023-08-29-regular-motion-4, nays both) / "the motion passed for a 30 day deferral" / "Minutes were approved." /
  "All members voted in favor, meeting was adjourned at 4:48 p.m." / election: "Mr. Kimbrough made the motion to
  nominate Mr. Swift as Chairman for 2024. Mr. Long seconded. All others were in favor. Motion passed." / reason
  clause: "made the motion for approval stating it is consistent with the adopted Land Use Plan." / tail control:
  "All others were in favor and the motion passed. Mr. Long left the meeting."
**Mutation pinning (closes `tests-not-pinning`)**: the PR pastes a table from a mutation run (scratchpad/mut.py
pattern, reviewer re-runs it): delete each SHAPES entry, each of 10b's tail triggers, each MEMBER_VOTE alternative,
each 10c/10d attribution branch, the "first motion" condition and the list-scope sections, one at a time; every
mutant must fail at least one test. A surviving mutant is either pinned by a new test or its clause is deleted.

## Earlier tests (rules 1-9; each asserts `not confirmed` and the reason unless noted)
- Finding 1, one each: "Mr. Long opposed.", "Voting nay were Mr. Long and Mrs. Streetman.", "Mr. Long voted nav.",
  "Mr. Long recused himself.", "Mr. Long dissenting.", "Nays: Mr. Long.", "Mr. Long did not vote.", a nay in the sentence
  after "Motion passed."; plus a control: "Mrs. Streetman voted nay. All others were in favor. Motion passed." stays confirmed (rule 9: without
  "Motion passed." it has no outcome and is not confirmed).
  Fix review 5769870 #2, one each: voted "no" (straight and curly quotes), "was not in favor" (before and after the
  outcome), "cast the only no vote", "with one no vote", "voting in the negative", "objecting", a nay two sentences
  after the outcome; controls: words after the outcome with no vote word, and the scan stopping at the next motion.
- Mangled heading: "CASE NUMBFR: Z-6-2026" and "C ASE NUMRER" between two cases -> the second case's motion is not under
  the first; `case_heads_printed` counts it. A section with two approvals -> both unconfirmed, `case_id` None.
  Fix review 5769870 #3: "GASE NUMBER", "CASF NUMBER", "Case Numbr", "CASE NO.", "CASE #" after a section with no
  motion of its own -> the next motion is not under the first case; another agenda case printed in a case section's
  text (as printed, zero padded, prefix misread) -> unconfirmed; its own case or an old non-agenda case -> confirmed.
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
  that splits into more than one cell ("Bill Kimb   h"). Fix review 5769870 #5 (`rpc-motion/c2-roster`): only a cell
  that looks like a name with a defect counts (starts with a capital, mostly letters, not all capitals), so a heading
  ("PLEDGE OF ALLEGIANCE") or a line of marks never opens the fallback; MEMBERS_STOP also stops at "call to order";
  a split line adds no member (it was not read whole as one clean name).
- **Rule 3** uses the same reason for an abstainer who is the mover/seconder.
- **Expected loss**: 2022-layout minutes approvals ("asked for a motion for approval of the minutes. Mrs. Streetman
  moved to recommend approval") read as "Motion for approval" with no case and become "subject not read". A later
  rule could read the "Approval of Minutes" heading; not added (any doubt).
- **Fix review 5769870 (backend-engineer, 2026-11-10), deviations from the review, each toward under-confirming:**
  (1) a stale record (no current `motion_rules`) also drops every `case_id`, not only `confirmed`, since rule 2a/2c
  never ran on it; `shown_motions` takes `rules` with no default. (2) The vote-word list is wider than the review
  asked (any form of "vote", a tally outside the outcome, ayes/noes, refrain, disagree, not support, conflict of
  interest), the scan after the outcome has no PARA_MAX cap, and the UNMODELLED patterns read the same span. (3) The
  section-level guard uses its own C1 reason ("the case section prints another case on this meeting's agenda"), not
  WHY_OTHER_CASE, so the reason counts in build/rpc-report.json tell the two apart. Measured on the four real OCR
  minutes fixtures: 9 of 16 motions confirmed before and after (no real-data cost visible there; the full effect
  shows only at the rebuild).

## Rule 10 implementation notes (backend-engineer, 2026-11-11; deviations called out)
- **Measured cost (full rebuild, 168/168 store): 638 -> 568 confirmed, not the ~595 estimated.** 70 lost, 0 gained:
  27 by 10a only (WHY_UNLISTED), 4 by 10b only, 34 by 10c only and 5 by 10a and 10c together. The 39 lost to 10c
  break down as follows:
  - **24 by list scope alone.** The spike did not measure list scope. A consent or deferrals motion is held to every
    case section with no motion of its own. That covers sections whose own vote the reader did not read ("All members
    voted in favor." x28 hits) and prose ("vote to recommend disapproval" in a speaker's letter; a CZO resolution
    text). 2026-07-28 alone loses 12 consent motions to one such section.
  - **15 by their own lead.** "conflicting traffic movements" and "in conflict with the adopted Future Land Use Plan"
    in staff reports hit `conflict`; "asked that the Commission vote no" and "would appreciate a vote in favor" hit
    `vote`.
  - All of these losses are toward under-confirming, as the rule says. A later option, not taken: limit list scope to
    the case sections whose case the list motion names. That needs the consent list read first.
  Changed-motion list: build-time file, not committed. The architect should judge the list-scope cost.
- **2026-06-23-regular-motion-3 is WHY_LEAD_VOTE, not WHY_LIST_PART.** SR-42-2026 is not on that meeting's agenda in
  rpc.json (the agenda lists SR-44 to SR-59), so 10d's "off the agenda" branch applies. The motion is not confirmed
  either way, and the test pins both branches.
- **2022-09-27-regular-motion-16 reads Mr. Powers as abstaining on its own case, but is not confirmed in the data**:
  list scope (a speaker's letter in AB-6-2022's section, "vote to recommend disapproval").
- **Joins**: JOIN also takes ", and " (2024-10-29 p1: "All others voted in favor, and deferrals were approved.") and a
  plain space before "with" (the outcome's "... 4-2 with Mr. Kimbrough and Mr. Long voting nay", a listed shape). The
  first join after the mover clause also takes "and" ("... the plan and Mr. Spigner seconded").
- **"second from M" is "[with a ]second from M"**, and SECOND_AHEAD ends the mover clause there. Without it, the shape
  could never be reached after a mover clause (real: "with a second from Mr. Kimbrough").
- **The heading line is a sentence of its own in the lead.** Otherwise "CASE NUMBER: S-73-2024" with no period would
  run into "Stacey Streetman abstained from voting." and the exact-abstention test would fail.
- **MEMBER_VOTE drops "did not vote" and "not vot"**: any vote form already matches them. The mutation run showed
  that deleting either fails no test.
- **10c's "S is a case section" is `case is not None`**: `case_ok` adds nothing, because a section's case is set only
  when its number was read.
- **10d in the body**: for a list motion, a case it names in "abstained from <case>" (another case on the agenda) is
  not counted again as WHY_OTHER_CASE. The member is left out of `abstained`, so they are written nowhere. Rule 2e
  (another agenda case printed in the section) still applies.
- **MOTION_RULES**: `sitegen/rpc.py` imports `collector.rpc_minutes.MOTION_RULES`, so there is one constant.
  `qa/site_checks.py` keeps its own copy, because the guard imports nothing from the code it checks.
  `tests/test_rpc_minutes_pages.py` pins all three equal.
- **Audit**: each row adds `lead`, the text scanned before the motion. The list-scope text is not written.
- **Mutation table**: docs/reviews/rpc-votes-rule10-mutation.md (`tools/rpc_rule10_mutation.py`), 49 of 49 killed.
