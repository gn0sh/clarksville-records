# PR #62 review: T5b (fresh, independent; 2nd at-large hit)

Reviewer: code-reviewer (opus/high), 2026-11-19, diff d8a3fc86..b4f1d78.

**Verdict: APPROVE.** Tests at b4f1d78: test_at_large_seats + test_cities 171 passed; test_city_seats, test_council_pages,
test_your_seats, test_map_seats 126 passed, 1 skipped; T0 test_clarksville_identical 4 passed.

## Consumer table (ADR 0012 decision 5)
- `at_large_rows` / `printings()` (council.py:426): holds; split records keep their own printings (tested).
- `title_conflicts`: holds; now grouped by (date, meeting_id) via `_list_key` (council.py:336). Null-id case untested (finding 3).
- `Seats` (`on`, `seat_text`, `header_text`, `of`, `is_current`, `is_held_over`): holds; `on()` None inside a gap; held_over rule (council.py:411) cannot misfire.
- `at_large_seats`, `seat_label`, `seat_order`: unchanged; duplicate-slug check (registry.py:459) protects `at_large_seats()`.
- views.py `Index.person` :300, `current_basis_lines`/`_card` :574-595, `base` :833, `roster_official` :953, `body_records`/`_seat_on`/`search_index` :1929-1998: hold (all via `of`/`on`/`seat_text`).
- `officials_page.seat_key` :649: unchanged, still T6's.

Every T5b test case listed in the task exists and tests what it claims.

## Findings
1. should-fix `at-large/complete-list-truncated` council.py:262-272: a cut-off list whose printed names all resolve counts as complete, so two truncated lists in a row could wrongly split a member's record. `latest_list_incomplete` (:175) already treats "resolves fewer than the previous list" as incomplete. **Action: fixing in T5b (follow-up commit).**
2. should-fix (T6) `at-large/seat-single-holder` seats.py:364, :420: `current_of_seat` / `held_over_of_seat` return one record; T6 must never call them for the at-large seat. **Action: added to T6 in the task list.**
3. nit `at-large/conflict-null-id-untested` tests/test_at_large_seats.py:110. **Action: test added in the follow-up.**
4. nit `at-large/title-last-source` council.py:369: a title record's `last_source` is the first print at the last list. Unchanged behaviour. **Action: none (no ADR requirement).**
