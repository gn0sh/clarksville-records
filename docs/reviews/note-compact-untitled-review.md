# Morning note: compact untitled votes (branch claude/note-compact-untitled)

Why: a rehearsal on records-data 9c43c7b (Nov 22 2026) showed the Nov 18 note would have mailed a "seats"
subscriber 51 council votes from four past meetings (Jul 2 to Oct 1, 2026; their minutes were first fetched Nov 18),
each titled "Title not read from the minutes" or "MINUTES": 319 lines. Sending was off, so nothing went out.

Change: in the email only, a meeting's untitled votes in the seats section collapse into one group: the meeting line,
"{n} votes in these minutes with no item title:", the record's own item numbers, the meeting page and the minutes
document. Entries with a case are never grouped; a lone untitled vote renders as before. The note JSON keeps every
entry (new additive fields `meeting_href`, `untitled`, `item_number`). Nov 18 seats email: 319 -> 37 lines.
Edition keys unchanged.

## Code review (code-reviewer, opus/high)
- Round 1 at 534f01d6: REQUEST CHANGES. `note-compact/hides-item-numbers` (should-fix), `note-compact/zoning-case-hidden`
  (should-fix, latent), `note-compact/copy-inaccurate` (should-fix), `note-compact/confirmation-dropped` (nit),
  `note-compact/config-text-test` (nit). tests/test_morning*.py 1069 passed.
- Delta at af9853c14c4d6de9ab36fca6f2823c87fb9bf301: **APPROVE**. All five closed (confirmation-dropped as a recorded
  decision in docs/architecture/morning-note.md). tests/test_morning*.py 1073 passed. Nits left: count is votes while
  the numbers line lists distinct items (`note-compact/count-vs-numbers`); `_keyed` keys sections by label
  (pre-existing, `note-compact/keyed-by-label`).

## Security review (security-engineer, opus/high)
- At 534f01d6: **OK**. Escaping via inert()/_attr(), link-host allowlist (javascript:, "..", off-host and
  fragment-trick URLs all dropped), deliver.py unchanged and body_ok still checks every edition, no names, outcomes or
  tracking. Low follow-ups: copy accuracy (fixed in af9853c), and the plain-text body is not inert-treated
  (pre-existing; text bodies are never sent).
- Delta at af9853c1: **OK**. 13 hostile item_number values escaped or broken up; every body passed deliver.body_ok; lines capped at 600 chars; seats-only and no-case limits confirmed. Morning and sender tests 795 passed.

## Tests (engineer)
- Full suite at 534f01d6: 8106 passed, 547 skipped (1:23:48). At af9853c1: tests/test_morning*.py 1073 passed; ruff
  clean on changed files.

Samples: /mnt/project-files/clarksville-records/morning-note-sample/2026-11-22/ (project files).

# Sunrise redesign (Brian, Nov 22: "celebrate civic pride... Your Local Government, in Broad Daylight")

Brian picked a blend of three concepts (/mnt/project-files/clarksville-records/morning-note-design/): concept A
"Sunrise" layout, C's plain-word definitions, and "You are invited." with the next meetings. Built 5f7e36d5..552c17a.

## Code review (code-reviewer, opus/high), fresh then delta
- At 75093b0: REQUEST CHANGES. must-fix `note-sunrise/cancelled-council-invited` (a council meeting called off on the
  city calendar stayed in "Coming up"); should-fix `note-sunrise/note-not-frozen` (coming_up changed the day-claim
  hash), `note-sunrise/intro-every-item-links`, `note-sunrise/executive-session-reads-closed`; nits
  `coming-kind-repeats-body`, `defs-of-hidden-items`, RFP wording. tests/test_morning*.py 1436 passed.
- Fix round 1 (f159fa2) froze coming_up at the cutoff, which emptied the list (defeats the invite); round 2 (0da3abc)
  keeps it current and takes it out of the day claim (common.note_digest, deliver.plan_digest strip only the two
  "Coming up" line forms).
- Delta at 0da3abc: **APPROVE**. All closed except nit `coming-kind-repeats-body`; 774 tests passed. Low notes: a
  coming_up change near the 80 KB budget can move the cut and make the claim read "other" (fails safe); first run after
  merge reads "other" for a day the old code started: don't merge 07:00-10:00 CT.
- Round 3 (552c17a): the nit fixed (label head the body name ends with is dropped; tested) and both low notes written
  into docs/architecture/morning-note.md. Manager read the 3-file diff; 1473 tests passed (engineer).

## Security review (security-engineer, opus/high), fresh then delta
- At 75093b0: **OK with follow-ups**. body_ok accepts only exact shared opening-tag strings; ~50 crafted bodies refused;
  deliver uses its own digest-checked copy of the constants. Low `note-sunrise/budget-unenforced` (check_plan didn't
  enforce BODY_BUDGET); info `note-sunrise/placement-unchecked` (body_ok checks nesting, not which block sits where).
- Delta at 0da3abc: **OK**. Budget enforced in check_plan and the plan stage; stripping removes only coming-up line
  forms; no double send (edition keys, subjects, entry ids, signatures still in the digest). Low, optional:
  `note-sunrise/claim-strip-placement` (strip by line form, not position). Not taken: unsent editions still pass body_ok.

## Tests
- Full suite at f159fa2: 8482 passed, 547 skipped. At 552c17a: tests/test_morning*.py + tests/test_days.py 1473 passed.
- Open before go-live (not code): whether Buttondown keeps inline styles; a person confirms the six definitions.
Samples: /mnt/project-files/clarksville-records/morning-note-sample/2026-11-22-sunrise/.
