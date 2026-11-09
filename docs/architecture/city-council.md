# Architecture: City Council (M4), Agenda Center minutes

The city collector reads Clarksville City Council minutes from the Agenda Center (`collector/agenda_center.py`,
`collector/city_minutes.py`, `collector/city_build.py`, `collector/city_run.py`) into
`data/localities/clarksville-tn/facts.json`, in the shape of `schema/facts.schema.json`. The county's parser
(`collector/parse.py`, `collector/facts.py`) has its own item rule and is not covered here.

## Vote-to-item link invariant (problem family `city-votes/item-link`)

Stated after the family's second hit (delta re-review of 1ea1e44..f1dedd8, 2026-11-09). Hit 1: votes linked to the
item they followed, so a Consent Agenda vote went to the one ordinance an abstention note named. Hit 2: the
section-only rule read the last sentence before the vote lines whatever it said, so a number in an abstention note
there still made a link.

**Invariant.** A roll call is linked to a numbered item only when the words that belong to that vote (its motion, its
outcome sentence, or a recognised vote lead-in sentence) identify that item, or the vote sits under that item's own
number line and those words name no other item, kind or several items. Otherwise it is linked to its section heading,
or, when those words contradict the item it follows, linked to the section and held.

Definitions (all in `collector/city_minutes.py`, patterns in `config/localities/clarksville-tn/agenda-center.yml`):
- **The vote's words** (`vote_words`): the motion (only when exactly one "made a motion" sentence sits between the
  item start or the previous vote and this vote, `_motion`), the lead-in (`lead_in`: the last sentence before the vote
  lines, only when it matches `vote_lead_in`, and only from the lead-in words on, so "Councilman Grubbs abstained ...;
  the following vote was recorded:" counts as "the following vote was recorded:"), and the outcome sentence after the
  vote lines. No other sentence of the paragraph is the vote's.
- **Identify**: the words name the item's number (any case), or, under a section heading only, they say "this
  ordinance" (singular, the same kind) and the paragraph before the motion (no single motion: before the last
  sentence; `_antecedent`) names exactly one item number outside an abstention or recusal sentence (`vote_asides`).
- A page's printed number (a digits-only last line of a page) is read as a blank line (`blank_page_numbers`), so it is
  never part of the vote's words, never ends a vote block and never starts an outcome sentence
  (`city-votes/outcome-text`).

### Code paths that set the link
| # | Where | Path | Result |
|---|---|---|---|
| 0 | `parse_text` | the item a vote follows: an item number line starting a paragraph sets `item` (title, or a prose line "RESOLUTION n was removed ..."); a section heading resets it to the heading only | input to `_item_for_vote`; never a link by itself |
| 1 | `_item_for_vote` | the vote's words match `not_item_votes` (Consent Agenda, adjourn, appoint) | section, `not_an_item_vote` |
| 2 | `_item_for_vote`, item line | the words name another number | section, `contradiction`, held |
| 3 | `_item_for_vote`, item line | the words name two or more numbers (its own among them) | section, `several_items` |
| 4 | `_item_for_vote`, item line | no number; the words name only another kind ("this resolution" under an ORDINANCE) | section, `contradiction`, held |
| 5 | `_item_for_vote`, item line | no number; the item's kind only in the plural ("these ordinances") | section, `several_items` |
| 6 | `_item_for_vote`, item line | otherwise | its item, `named` (its number in the words) or `heading` |
| 7 | `_item_for_vote`, section only | exactly one number in the words | that item, `named` |
| 8 | `_item_for_vote`, section only | no number; "this <kind>"; the antecedent names exactly one number of that kind | that item, `named` |
| 9 | `_item_for_vote`, section only | anything else (no kind word, several numbers, antecedent names 0 or 2+, plural, other kind) | section, `section` |
| 10 | `RollCall.link` default | a roll call made without `_item_for_vote` | held (`basis: unset`, ok False); `parse_text` always sets it |
| 11 | `city_build.build` | `rc.item["number"]` -> item id `<kind>-<number>` (`link_basis: number`); else `t-<hash(meeting, heading)>` (`link_basis: title`); `rc.link["ok"]` -> check `vote_matches_item` | the roll call's `item_id`; its motion's and item events' `item_id` are the same id |

Tests: `collector/tests/test_city_vote_link.py` has one test per path 1-11 (0 through the parse tests), each through `assert_invariant`,
which also checks that adding an abstention note before the lead-in never changes the result; plus the reviewer's
abstention case, the lead-in case and the page-number case. Older cases: `test_city_minutes.py` `LINKS`, `ZONING`.

### Consumers of a roll call's item link
None may re-derive the link; each reads `item_id` (or `rc.item` / `rc.link` before the build).
| Consumer | Where | Reads |
|---|---|---|
| Facts build | `collector/city_build.py` `build` (roll call loop) | `rc.item` -> `items[]`, `roll_calls[].item_id`, `motions[].item_id`, `item_events[].item_id`; `rc.link` -> `vote_matches_item` check and so the roll call's verification |
| Facts schema | `schema/facts.schema.json` `roll_call.item_id`, `motion.item_id`, `item_event.item_id`, `item.link_basis` (`number`/`title`) | shape only; the link itself is not checked by the schema |
| Reference check | `sitegen/build.py` `check_references` | every `item_id` of events, motions and roll calls names an item |
| Item pages | `sitegen/views.py` `items_year` ("Linked by number" / "Linked by title"), `Index.events_by_item` | the item's history of votes and motions |
| Official pages | `sitegen/views.py` `official` (vote and motion rows, `Index.item_ref`) | the item each vote is shown under |
| Meeting pages | `sitegen/views.py` `_roll_call_block`, `_motion_block` | the item each roll call is listed under |
| Votes by year | `sitegen/views.py` `votes_year` | item per vote row |
| Search index | `sitegen/views.py` search records (`k: "vote"`, `n`, `t` from the item) | item number and title in search |
| CSV export | `collector/export.py` `tables`: `roll_calls.csv`, `votes.csv`, `motions.csv` (`item_id`), `items.csv` (`link_basis`), `item_events.csv` | provenance "derived: item linking rule" |
| One-vote check | `collector/invariants.py` `consent_item_ids`, `one_vote_violations` | the Consent Agenda title item; one roll_call event per (item, roll call) |
| QA spot check | `qa/spot_check.py` `candidates` | the item label shown to the checker per sampled vote |
