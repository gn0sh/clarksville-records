# Agenda-sourced titles: the cite invariant (captions/uncited-title)

Problem family `captions/uncited-title` has been hit more than once (site pages on the captions branch; then the
morning preview page, the email's size-rule row and its card in PR #90 review). Under the loop rule, this page
states the invariant and lists every consumer of `items[].title` before the next fix.

## Invariant
An item's title may come from its meeting's agenda rather than the minutes: facts `item.title_source`
`{kind: "agenda", source_id, page, meeting_id}` (collector/city_build `agenda_titles`, docs/architecture/city-council.md).
**Wherever an agenda-sourced title's words are shown, the agenda that printed them is linked next to those words,
with its page, in wording that names the right meeting.** If that link cannot be made (the URL fails the https or
link-host rule, or the page is unknown), the agenda's words are not shown: the item shows its number, or it joins
its meeting's untitled votes.

"The right meeting's wording" means a cite never says "the meeting's agenda" for another meeting's agenda. The
site's cite (`title_source_text`, "title as printed in the agenda, p. {page}") names no meeting and links the exact
agenda page. The email says "the agenda" for the entry's own meeting's agenda and "the {date} agenda" for an
earlier one (config `title_agenda_page` / `title_agenda_page_dated`, `title_agenda` / `title_agenda_dated`; the
rule is `render._agenda_words`: `title_source.meeting_id[:10]` against the entry's meeting day).

## Consumers of `items[].title`

| Consumer | Shows the words? | Status | Test |
|---|---|---|---|
| Site item pages, meeting pages, `_macros.item_link` + `title_cite` | yes | OK (captions branch) | `tests/test_site_review_fixes.py::test_every_rendered_agenda_title_carries_its_agenda_link` |
| Search index (`ts` field) | yes | OK (captions branch) | same test (search-index records) |
| Atom feeds (`sitegen/feeds.py`) | yes | OK (captions branch) | same test (feeds) |
| CSV export (`collector/export.py` `title_source_url`, `title_source_page`) | yes | OK (captions branch) | `collector/tests/test_city_agenda_titles.py::test_the_export_cites_the_agenda_for_a_title_it_prints` |
| Build reference check (`title_source.source_id`, `.meeting_id` exist) | no | OK | `tests/test_site_review_fixes.py::test_dangling_title_source_fails_the_build` |
| `sitegen.morning._title_source` (the note's entry carries `title_source` + page URL) | no (data) | OK | `tests/test_morning_sender_titles.py::test_the_note_carries_the_facts_title_source_with_the_agenda_pages_url` |
| `morning_page.preview` + `site/templates/morning.html.j2` (preview page) | yes | **fixed** (PR #90 review 1): `_title_cite` passes the URL through `config.https_link` and renders `_macros.title_cite`; no link or no page shows the item number | `tests/test_morning_page.py::test_preview_cites_the_agenda_beside_a_title_it_printed`, `::test_preview_never_shows_an_agenda_title_it_cannot_cite` |
| `render.agenda_cite` / `_shown_title` (the email's gate) | gate | **fixed**: a cite now needs a known page, not only a link | `tests/test_morning_sender_titles.py::test_an_agenda_title_with_no_page_is_not_shown`, `::test_a_caption_whose_agenda_cannot_be_linked_is_never_shown` |
| `render.topic` (subject and kicker topic) | no: reads the words only to pick a config phrase, and only when citable | OK | `tests/test_morning_sender_titles.py::test_topics_also_come_from_the_lists_and_kinds_but_never_from_a_title_we_made` |
| `render.items` / `_flat` (untitled-vote compaction, merging one item's votes) | gate | OK: an uncitable caption stays untitled (compacted, or alone with its number) | `::test_a_caption_whose_agenda_cannot_be_linked_is_never_shown`, `::test_a_lone_vote_whose_agenda_cannot_be_linked_shows_its_number_only` |
| `render._line_of` (the card's item line) | yes | **fixed** (review 3): a muted "title from the agenda, p. N" link to that item's agenda page on the line itself; the card's document link stays | `::test_a_vote_titled_from_its_agenda_stands_as_itself_and_cites_the_agenda`, `::test_a_real_caption_card_reads_kicker_headline_meeting_and_both_sources` |
| `render._card` (the card's document links) | no (links only) | OK | `::test_a_vote_titled_from_its_agenda_stands_as_itself_and_cites_the_agenda` |
| `render._row` (size-rule rows) | yes | **fixed** (review 2): dated wording for another meeting's agenda, with the page | `::test_a_row_names_the_agenda_of_the_meeting_that_printed_the_title_with_its_page`, `::test_the_agenda_link_stays_in_a_row_when_the_size_rule_applies` |
| `render.body_text` (plain-text twin) | yes | **fixed**: the same per-line cite with its page URL | `::test_a_vote_titled_from_its_agenda_stands_as_itself_and_cites_the_agenda` |
| `render.headline_parts` (excerpt) | yes, as a fragment of the title | OK: the line that shows it carries the cite | as `_line_of` |
| `sitegen.morning.own_text` (neutrality scan input) | no: captions are the record's words, not ours (`title_ours` false), so they are left out of the scan | OK | `tests/test_morning_sender_render.py::test_every_word_outside_the_record_is_config_text` |
| `plan.json` (edition bodies and texts) | yes, through render | OK: bodies are render's output, covered by the rows above | as `_line_of`, `_row`, `body_text` |
| `morning/latest.json`, `morning/<date>.json` (the note data) | no (data: `title` with `title_source` and its URL side by side) | OK: every reader of these is listed above (preview page, sender); `static/morning.js` reads no title | n/a |

A new consumer of `items[].title` (or of a note entry's `title`) must be added to this table with its test before
it ships.
