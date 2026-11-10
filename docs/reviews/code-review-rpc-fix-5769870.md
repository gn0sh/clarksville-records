# Code review: RPC motion fix 5769870 (2026-11-10)
code-reviewer, fresh independent review. Target origin/claude/sqv6p9-rpc-fix at 5769870, diff against
origin/claude/project-thread-sqv6p9. Judged against docs/architecture/rpc-motion-invariant.md (C1-C5, every consumer)
and docs/reviews/code-review-rpc-m2-0927bfe.md findings 1-7.

**Verdict: REQUEST CHANGES** (findings 1 and 2).

Tests: 117 RPC tests pass (collector/tests/test_rpc_minutes.py, collector/tests/test_rpc.py,
tests/test_rpc_minutes_pages.py, tests/test_rpc_pages.py). Full suite: 1972 passed, 5 skipped (11m23s).
`python -m qa.site_checks --site build/site --facts data/facts.json --target pages`: rpc-motions PASS
(1307 motion blocks, 825 shown confirmed, 1088 confirmed in rpc.json), rpc-cases PASS, all other checks PASS except
`links`. `links` failed only because data/*.csv and data/city/* were missing: I did not run the collector.export step.
That is not related to this diff.

## Findings

1. **must-fix** `rpc-motion/c3-stale-record`, sitegen/rpc.py:133 (shown_motions), collector/rpc_agenda.py:~470 (facts dict).
   The pages are built from the committed rpc.json, and that file was written at 0927bfe, before any of the reader's new
   rules existed. It holds no `para`, so rules 1 (vote words), 2a (loose headings), 2c (another case named),
   3 (seconder swallow) and 7 (roster) have not run on anything a reader sees. record_doubts can only re-check
   C1 and C3 from the stored fields. Of the 825 motions shown confirmed, 788 have no nays and no tally. Those are
   exactly the motions where an unread "Mr. Long opposed." would read as nobody voting nay, which is earlier finding 1.
   Even so, site_checks passes. The code fails closed, but the data shown does not. Fix: build writes a rules marker
   (e.g. `"motion_rules": "rpc-motion-invariant-1"`, or schema `rpc-2`). Rpc.__init__ treats every motion of a record
   without the marker as not confirmed (reason "record written before the motion invariant"). site_checks rpc-motions
   FAILs when the marker is missing and any block is shown confirmed. Until the rebuild the preview then shows
   0 confirmed, which is the honest number. The weaker alternative is to merge without republishing the preview until
   the rebuild, recorded in status.md, but that relies on discipline.

2. **must-fix** `rpc-motion/c3-vote-words`, collector/rpc_minutes.py:153 (LEFTOVER_VOTE), :438-446 (tail scan).
   The vote-word list is a denylist, so any phrasing missing from it is confirmed with nays=[].
   I ran these through read_motions under a read case. Each came back CONFIRMED with nays=[]:
   - `Mr. Long voted "no".` (also with curly quotes)
   - `Mr. Long was not in favor.` (before or after "Motion passed.")
   - `Mr. Long cast the only no vote.`
   - `Motion passed with one no vote.`
   - `Motion passed with Mr. Long voting in the negative.`
   - `Motion passed, Mr. Long objecting.`
   - `Motion passed. Mrs. Streetman thanked staff. Mr. Long voted nay.` (the nay is two sentences after the outcome)

   `voted "no"` is a common way for minutes to print a vote. Fix:
   - Extend LEFTOVER_VOTE with `vot\w*\s+["“'‘]?no\b|\bno\s+votes?\b|not\s+in\s+favou?r|negative|object`.
   - Scan from the outcome to the next motion start or section end (window[len(para):], bounded by PARA_MAX), not just
     one sentence. This changes the invariant's "one sentence", so the architect should edit row 1 in place.
   - Add one test per phrasing above.
   - Stronger option for later: an allowlist of sentence shapes (motion, second, nay, abstain, favour, outcome). Any
     other sentence in the motion's span is a doubt.

3. **should-fix** `rpc-motion/c1-case-heading`, collector/rpc_minutes.py:157 (LOOSE_HEAD), :505.
   LOOSE_HEAD forgives a mangled NUMBER but not a mangled CASE. Probe: under Z-5-2026, with Z-6-2026 on the agenda,
   a section with no motion of its own, followed by each of these headings. Each time the next motion was confirmed
   under Z-5-2026 and case_heads_printed stayed at 1:
   - `GASE NUMBER: Z-6-2026`
   - `CASF NUMBER: Z-6-2026`
   - `Case Numbr: Z-6-2026`
   - `CASE NO. Z-6-2026`
   - `CASE #: Z-6-2026`

   WHY_TWO catches this only when the earlier case already has a disposing motion, and 2c only scans the motion's own
   sentences. Fix:
   - (i) Widen LOOSE_HEAD to the CASE word, e.g. `[CG]\s*[A4]\s*[S5$§]\s*[EF]\s*(?:N\S{0,6}R?|NO\b|#)`, anchored near
     line start.
   - (ii) The robust guard: a case section whose text, anywhere and not just the motion's sentences, prints a case number
     on this meeting's agenda other than its own gives every motion in it WHY_OTHER_CASE.
   - Add tests for the five headings.

4. **nit** `rpc-motion/qa-guard`, qa/site_checks.py check_rpc_motions:
   - per_case collects lists. A motion block shown on two pages would be counted twice. Use sets keyed by motion id.
   - Check (e) scans only `<slug>/` pages. The invariant says "no page", and today.html and index carry RPC cards.
     Scan every page that has an RPC card.

5. **nit** `rpc-motion/c2-roster`, collector/rpc_minutes.py:220-221. Any line before MEMBERS_STOP that fails
   MEMBER_NAME marks the header garbled, including a heading such as "CALL TO ORDER", because MEMBERS_STOP matches
   only "called ... to order". This widens the rule 2a fallback beyond "a garbled member line". It is low risk, since
   the roster still needs an exact surname match. Fix: add `call\s+to\s+order` to MEMBERS_STOP and count only cells
   that look like a name with a defect (start with a capital letter and are made mostly of letters).

## Earlier findings (0927bfe)
1. verified-gate/unread-dissent-confirmed: **open**.
   - The listed phrasings are fixed and tested.
   - Gaps remain (finding 2).
   - The fix is not applied to the committed data (finding 1).
2. attribution/missed-heading-merges-cases: **partly closed**.
   - Fixed: NUMBER mangles, >1 disposing motion in a section, another case in the motion text, and the record-level
     crowded check (94 unconfirmed on the data).
   - Still open: CASE-word mangles (finding 3).
3. nay-list-swallows-seconder: **closed**. Nays are read only after the seconder, the mover/seconder-as-nay case is
   tested, and the record-level check catches 3 motions.
4. case-not-on-agenda-confirmed: **closed**. Reason added in rpc_agenda, repeated sections handled, record level 71.
5. caseless-approvals-confirmed: **closed**. "Subject not read" applies (211 at record level), and the business
   relabel is tested.
6. no-audit-trail: **closed**. build/rpc-motions-audit.jsonl is written, refuses a site path, and build/ is gitignored.
7. roster-fallback: **closed**. The fallback runs only for a garbled header (finding 5 is a nit on it). The rejection of
   the title-gender check is reasoned, and I agree with it.

## Checked and holds
- Rpc.motion: case is None unless shown. Placement comes from case_id only, so C1-doubtful motions go to
  "Other motions".
- The home count uses the shown motions. The template prints values and the case only inside `confirmed`, and never
  writes "unanimous".
- Search carries no motion fields. Feeds have no RPC entries. The morning-note task cites the invariant.
- Attach clears case_id on CASE_REASONS. C5 (the minutes' date) still gates.
- rpc.json carries no `para`. The MOTION_BLOCK regex is safe because the macro has no nested div.
- The site_checks leak, misplacement and "unanimous" checks are each exercised by tests.

## Delta re-review cf7a0ef (2026-11-10)
Range 5769870..cf7a0ef. **Verdict: APPROVE WITH NITS.** All 5 findings are closed. There are no new must-fix or
should-fix findings.

Tests: 168 RPC tests pass. site_checks --target pages: rpc-motions PASS (1307 blocks, 0 shown confirmed,
"motion_rules not current: None"), rpc-cases PASS, all other checks PASS except `links`. `links` fails only on the
missing data/*.csv export files, which is not related to this diff (same as before). I re-ran my probe from the first
review:
- All 10 dissent phrasings are now not confirmed.
- All 6 mangled CASE headings are not confirmed and carry no case. Each has two reasons: case heading not read, and
  the section prints another agenda case.
- The modelled nays stay confirmed.

1. c3-stale-record: **closed**.
   - The build writes `motion_rules`, and `shown_motions(motions, rules)` has no default for it.
   - A record that is stale (or has no marker) shows nothing confirmed and drops `case_id`.
   - site_checks (f) FAILs any block shown confirmed from such a record.
   - The three copies of MOTION_RULES are pinned equal by tests/test_rpc_minutes_pages.py:241.
2. c3-vote-words: **closed**. The word list is wider, the scan runs from the outcome to the next motion or the
   section's end with no cap, UNMODELLED is applied to the same span, row 1 of the invariant is edited, and there are
   19 tests.
3. c1-case-heading: **closed**. LOOSE_HEAD now also catches a mangled CASE word near the line's start, and a
   section-level guard (other_cases through read_number, so a misread prefix still counts) gives
   WHY_SECTION_OTHER_CASE, which is in CASE_REASONS.
4. qa-guard: **closed**. Motions are counted in sets by id. The "unanimous" check now covers index, today and any
   page with an RPC card.
5. c2-roster: **closed**. MEMBERS_STOP now stops at "call to order". Only a cell that `_name_like` accepts marks the
   header garbled. A name split across a line is no longer added as a member.

Wider-than-asked changes:
- These only add reasons, drop placements or shrink the members/roster lists, so they can only reduce confirmations:
  the extra vote words, the uncapped scan, UNMODELLED on the wider span, the stale record also losing its case
  placement, the MEMBERS_STOP change and the split-line rule.
- One exception in theory: a wider LOOSE_HEAD can split a section in two. That could clear WHY_TWO for the earlier
  motion, which then stays under its own correct heading. I could not trigger it with realistic prose; not a finding.

New, nit `rpc-motion/c3-vote-words-overreach`, collector/rpc_minutes.py:72-76. The bare `vote` word now also catches
modelled sentences that FAVOUR misses because a comma or "except" follows "in favor". Example: "All members voted in
favor except Mr. Long, who voted nay." is no longer confirmed. This under-confirms only. Measure the loss at the
rebuild with build/rpc-motions-audit.jsonl before narrowing anything.
