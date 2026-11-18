# Tasks: morning note, one edition for everyone (2026-11-18)

Design: `docs/architecture/morning-note.md` "One edition for everyone"; ADR 0004 decision 6. Fact: platform-facts
"Morning note provider" (2026-11-18 sign-up: confirmed, no tags). Decision: Brian, 2026-11-18 (free plan, one note
with all topics, no topic picker or seat fields on the form).
Nothing here sends: `MORNING_NOTE_SEND` stays unset (hard stop 1). Until N1 merges, a live run would stop as `no-tags`.

| Task | Owner | Depends on | Parallel |
|---|---|---|---|
| N1 Sender: one edition, `mode: all` | backend-engineer (opus/high: audience logic) | none | yes, with N2 |
| N2 Form, preview page, Method and privacy text | frontend-engineer (sonnet/medium) | none | yes, with N1 |
| N3 Shared cleanup (tag helpers) | whichever of N1/N2 merges second, in that PR | the other merged | no |
| N4 Code review, one per PR | code-reviewer (N1 opus/high, N2 sonnet/medium) | N1 / N2 committed | yes |
| N5 Security review of N1 + N2 together | security-engineer (fresh, opus/high) | N1 and N2 committed | before either merges |
| N6 QA against the done-when lists | qa-engineer | N1-N3 merged | no |
| N7 Fresh sample for Brian | manager | N6 | attach to the `MORNING_NOTE_SEND` ask, not a new ask |

Shared files (separate hunks; the second to merge rebases): `config/site.yml` (N1: `morning_note.sender:` only;
N2: `lists` labels, `form_fields`, `page:`), `sitegen/morning.py` (N1: `SENDER_KEYS`, `SENDER_MODES`,
`sender_problems`; N2: `PAGE_KEYS`, `FORM_FIELD_KEYS`, the form part of `problems()`). N2 also meets
`claude/front-signup` in `site/templates/index.html.j2` and `method_sent`: rebase on whichever is on `main`.
Tests must read list labels and texts from config, never hard-code them, so N1 and N2 do not break each other.

## N1 Sender (`sender/`, backend-engineer)
Change:
- `sender/common.py`: `PLAN_SCHEMA = "morning-send/2"`; `MODES = ("all", "stamp", "ids")`; delete `read_tags`,
  `_SEAT_TAG`, `signature`, `SIGNATURE_RE` (keep `list_tag`, `seat_tag_prefix`, `TAG_FIELD`, `TAG_PREFIX` for N3).
- `sender/plan.py`: new `one_edition(note)`; `build()` writes one edition and no `signatures`; delete `signatures()`,
  `placed()`; docstring. `sender/__main__.py`: summary line without "subscriber shape(s)".
- `sender/render.py`: `body_html` / `body_text` drop the `unplaced_text` lines; docstrings.
- `sender/deliver.py`: `check_plan` (schema /2, one edition iff `send`, no `signatures`); `plan_digest` canon
  without `signatures`; `run()`: the `all` path (no subscriber call, one scheduled email, no `filters`), `canary_only`
  with a mode other than `stamp` -> exit 2 "bad-config"; stamp path routes every recipient to the one edition;
  `recipient()` -> id only; `stamp()` re-read compares id and type only; delete `_one_seat`, `MAX_LIST_VALUES`,
  the `no-tags` exit, the `max_editions` branch; `_check_audience` / `_check_echo` gain `all` (no filter sent; stored
  filter absent, null or exactly `{"filters": [], "groups": [], "predicate": "and"}`); `describe()`; module docstring.
- `sender/buttondown.py`: `_reduce_subscriber` keeps `{id, type, metadata}`, drops `tags` unread; docstring.
- `sender/settings.py`: drop `max_editions`, `district_count`, `ward_count` if only `_one_seat` used them; accept `all`.
- `sitegen/morning.py`: `SENDER_KEYS` without `max_editions`; `SENDER_MODES` = `("all", "stamp", "ids")`;
  `sender_problems()` refuses `canary_only: true` unless `mode: stamp`.
- `config/site.yml` `morning_note.sender:`: `mode: all` (comment: why), remove `max_editions` and its comment,
  `text.why` to the architecture's wording, the run-time comment re-derived.
Tests (update or add):
- `tests/test_morning_sender_plan.py`: `test_plan_shape` (schema /2, 0 or 1 edition, no `signatures`); replace
  `test_every_signature_gets_exactly_what_select_returns`, `test_same_entries_share_an_edition_and_different_entries_do_not`,
  `test_an_entry_stands_under_a_list_the_reader_picked_and_that_selected_it` with
  `test_the_one_edition_holds_every_entry_of_the_note_in_order` and `test_each_entry_stands_under_its_first_list`;
  update `test_editions_print_each_entry_under_its_placed_list`, the rehearsal and disabled tests; add
  `test_zoning_cases_with_no_printed_seat_are_in_the_edition` and `test_a_100_entry_day_fits_one_body`.
- `tests/test_morning_sender_render.py`: `test_an_editions_entries_and_order_equal_the_preview_pages` unparametrised
  (the one edition's titles equal the preview page's server-rendered rows, same order);
  `test_at_least_one_preview_comparison_has_entries` (one edition); `test_unplaced_line_and_why_line_close_the_entries_then_the_notice`
  (no unplaced line; the why line from config).
- `tests/test_morning_sender_deliver.py`: delete `test_max_editions_counts_only_editions_with_a_recipient_before_the_first_write`,
  `test_a_signature_with_non_ascii_digits_sends_nothing`, `test_confirmed_subscribers_none_with_a_note_tag_end_the_run_non_zero`,
  `test_hostile_tags_are_ignored_not_passed_on`; replace `test_a_190_edition_day_is_sent_whole_with_the_shipped_limits`
  with `test_a_busy_day_is_one_email` (both `all` and `stamp`); rework
  `test_a_busy_day_cut_off_part_way_is_finished_by_a_rerun_without_sending_twice` and
  `test_a_run_that_died_after_edition_1_of_3_finishes_2_and_3_only` for one edition (stamp: died part way through the
  stamps; all: died after the create, re-run creates nothing); adapt the stamp tests
  (`test_stamp_sends_one_scheduled_email_per_edition_to_exactly_its_people`, the three stray tests,
  `test_a_rerun_after_a_stamped_subscriber_changed_lists_is_not_a_stray` -> changed type,
  `test_a_holder_of_a_created_edition_is_left_out_of_a_new_one_with_other_people`) to one edition with canaries.
  Add: `test_all_mode_creates_one_scheduled_email_with_no_filter_and_calls_no_subscriber_endpoint` (the fake
  provider raises on `subscribers`, `subscriber`, `set_metadata`), `test_all_mode_takes_back_a_stored_email_with_a_filter`,
  `test_tags_and_metadata_never_change_the_audience_or_the_body`, `test_canary_only_without_stamp_mode_is_refused_before_any_call`,
  `test_a_plan_with_two_editions_or_signatures_is_refused`; extend `test_the_audience_check_accepts_only_the_editions_own_filter`
  with `all`; re-derive the run-time-budget test.
- `tests/test_morning_sender_buttondown.py`: `test_stamp_mode_end_to_end_reaches_exactly_each_editions_people` (one
  edition, canaries); `test_a_subscriber_keeps_its_tag_names_and_a_tags_field_of_another_shape_fails_closed` ->
  `test_a_subscribers_tags_are_dropped_whatever_their_shape`; add `test_all_mode_end_to_end_makes_no_subscriber_request`.
- `tests/test_morning_sender_config.py`: modes parity, `max_editions` gone, `canary_only` needs `stamp`.
Done when: the full preflight passes (paste it in the PR); `python -m sender plan --rehearse` on the fixture's busy
day writes exactly one `edition-*.html` and `.txt`; the deliver dry run says one email; `grep -rn "no-tags\|
max_editions\|signatures\|read_tags" sender/ config/` finds nothing; architecture "As built" notes any deviation.

## N2 Form, preview, Method (`site/`, `sitegen/morning_page.py`, frontend-engineer)
Change:
- `config/site.yml`: `form_fields: {email: email}` and its comment; `lists` labels `Zoning`, `County Commission and
  City Council` (refine if needed, config only); `page:` remove `seats_include`, `seats_sent`, `method_change`,
  `preview_mine`; change `about`, `legend`, `sent_line`, `method_sent` (no `{box}`), `quiet` (architecture wording).
- `sitegen/morning.py`: `FORM_FIELD_KEYS = ("email",)`; `problems()` form part (exactly `email`, not `tag`, not
  `metadata*`); `PAGE_KEYS` as above.
- `sitegen/morning_page.py`: `_lists` without `tag`; `_section` without `seat_tags`, fields email only; `privacy()`
  without `seats_sent`, `{box}`, `change`; drop the `list_tag` / `seat_tag_prefix` import; module docstring.
- `site/templates/alerts.html.j2`: the enabled form holds only `email`, `embed=1`, `sent_line`, privacy link and
  submit; seat inputs, `#mn-seats` and the in-form picker removed; feed panel in a `<details>` outside the form.
- `site/templates/_morning.html.j2`: `picker()` never names a box or posts a tag; header comment.
- `site/templates/morning.html.j2`: no picker, `preview_mine`, seats hint or unplaced row; every entry shown.
- `site/templates/method.html.j2:20,28` and `index.html.j2:40,169`: the off-state seat sentences always; no
  `change` line.
- `site/static/morning.js`: delete `seatPost`, `seatWords`, `select`, `matches`, `parseLists`, the seat-field and
  consent code, the `submit` listener, the preview filter and the `#lists=` preview link; header comment.
Tests (update or add):
- `tests/test_morning_page.py`: replace `test_enabled_form_shows_a_visible_seats_box_and_keeps_the_seat_fields_off_without_the_script`
  with `test_enabled_form_posts_only_the_address_and_embed` (named controls are exactly `email` and `embed`; no
  `tag`, no `metadata__`, no `data-seat-field`); delete `test_js_seat_post_sends_nothing_unless_the_box_is_ticked`
  and `test_js_select_matches_python_select_for_every_list_and_seat_combination`; invert
  `test_enabled_build_never_says_the_seats_are_never_sent` -> `test_enabled_build_says_the_seats_never_leave_the_device`;
  replace `test_seat_consent_in_a_browser` with `test_the_form_posts_only_the_address_in_a_browser` (same harness);
  add `test_preview_page_shows_every_entry_with_no_picker`, `test_method_page_has_no_change_line`.
- `tests/test_morning.py`: `test_form_action_refused_while_disabled_and_shape_checks` (new `form_fields` shape;
  a `lists`, `district` or `ward` key is refused).
- `tests/test_morning_sender_config.py`: `test_shape_checks_apply_even_while_off` parameters for `form_fields`.
Done when: preflight passes, including the smoke test, accessibility scan and link check of `alerts.html`,
`morning/index.html`, `method.html` and `index.html` (paste output in the PR); a built enabled `alerts.html` has no
`name="tag"` anywhere; the Method page names only the address as sent; `grep -rn "seats_sent\|seats_include\|
method_change\|data-tag-prefix" site/ sitegen/ config/` finds nothing.

## N3 Shared cleanup (in the second of N1/N2 to merge)
Delete `common.list_tag`, `seat_tag_prefix`, `TAG_FIELD`, `TAG_PREFIX`, `morning.TAG_FIELD`, and replace
`tests/test_morning_sender_config.py::test_tag_names_are_fixed_and_shared_by_the_form_and_the_sender` with
`test_neither_the_form_nor_the_sender_names_a_tag` (no `note-` tag string in `site/`, `sitegen/`, `sender/`).
Done when: `grep -rn "list_tag\|seat_tag\|TAG_FIELD\|TAG_PREFIX" sender/ sitegen/ tests/` finds nothing.

## N5 Security review (fresh, opus/high)
Scope: N1 and N2 commits. Weigh: the unfiltered email's audience (echo check, unconfirmed addresses), `canary_only`
refusal, key scope (Subscribers none), that no subscriber field reaches the note job in `all` mode, that the form
and the privacy text match the data flow (address only), the front-page card's form when it lands.
Done when: approve, or findings fixed and re-confirmed.

## N6 QA
Against the architecture's done-when: rehearsal plan on a real busy day = one edition whose entries equal the
preview page; the enabled form's request carries only `email` and `embed` (browser devtools on a local build); the
Method, landing and Alerts pages say the seats stay on the device. Tag problem keys under `one-edition/`.

## Order
N1 and N2 at once -> N4 per PR, N5 on both -> merge N2 first if ready (it is what the public form posts), then N1
with N3 -> N6 -> N7 with the go-ahead ask (hard stop 1).
