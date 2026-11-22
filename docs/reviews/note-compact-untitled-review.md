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
