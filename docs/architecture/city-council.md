# Architecture: City Council (M4), Agenda Center minutes

The city collector reads Clarksville City Council minutes from the Agenda Center (`collector/agenda_center.py`,
`collector/city_minutes.py`, `collector/city_build.py`, `collector/city_run.py`) into
`data/localities/clarksville-tn/facts.json`, in the shape of `schema/facts.schema.json`. The county's parser
(`collector/parse.py`, `collector/facts.py`) has its own item rule and is not covered here.

Since M4 slice 3 (ADR 0003) the CivicClerk listing (`collector/civicclerk.py`, 2024 on) feeds the same build: its
minutes go through the same reader, checks and link paths below, unchanged. Two additions sit before the roll calls and
never set a link: an attendance list printed as surnames is read against full names (`city_build.resolve_surnames`;
an unresolved surname holds the meeting's attendance), and a minutes file listed for two meetings is read only for the
meeting whose call-to-order date it prints (`minutes_status: other_meeting` for the other).

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

## Name resolution invariant (problem family `city-votes`, names)

Stated after the family's third hit (review of the CivicClerk slice, 1bc303c..e136a8b, 2026-11-09:
`city-votes/surname-stale-book`). The surname book kept each surname's latest full-name printing with no time limit,
so a new member sharing a departed member's surname (the data has David Allen out and Wanda Allen in on 2021-01-07)
would have been read as the departed member, with verified votes.

**Invariant.** A printed name resolves to a member only when exactly one member of that meeting's own roster matches
it, and the roster is the meeting's own attendance list as printed in full (through the alias list) plus its presiding
mayor, where a surname printed alone counts only against full names printed in the same minutes after a member's title
or on the full-name attendance lists printed since the council's latest seating, for members whose ward (or the
mayor's seat) no later list in that window gives to someone else. Any other name (no match, two matches, a match only
on a list older than the window, or a member since replaced) is held, never guessed.

**The window: the council's seating.** Every wholesale change of members in the full-name attendance lists of
2016-2025 falls at the first January meeting of an odd year (2017-01-05, 2019-01-03, 2021-01-07, 2023-01-05,
2025-01-02: members elected in November of the even year take their seats), so a list from before the latest seating
is never used (`seating` in `config/localities/clarksville-tn/agenda-center.yml`; observed in the data, not taken from
the charter). Mid-term changes (2019-07, 2021-11, 2022-05, 2023-06, CLAUNCH 2026) are covered by the replaced-seat rule
when a later full-name list prints the successor, by the successor's own surname (a surname on no list is held, as
CLAUNCH is), or by a titled full name in the minutes (a second full name for the surname holds it). Residual risk,
accepted and named: a mid-term successor with the predecessor's exact surname who is never printed with a full name,
title or ward before the next seating. The window is at most two years and needs no upkeep while the seating pattern
holds; a change of pattern is a config change.

### Code paths that resolve a printed name
| # | Where | Path | Rule |
|---|---|---|---|
| N1 | `city_build._add_minutes` attendance loop, `Officials.add` | attendance printed in full (`NAME_RE`) | the printed full name is the member (id `city-<slug>`); not a name: no official, `names_well_formed` holds the meeting |
| N2 | `Officials.canonical` (`aliases` in `agenda-center.yml`) | aliases: one printed full name -> another | whole printed names only, each the same ward in the same term (checked in wards.json); applied in N1, N3, N4, N7 |
| N3 | `_add_minutes` presiding; `city_minutes.parse_people` `Person.mayor` | the presiding mayor ("called to order by Mayor Joe Pitts") and a list entry with the Mayor title or "(Mayor)" | added to this meeting's roster with the Mayor title; a Mayor Pro Tem is already on the PRESENT line |
| N4 | `city_minutes.titled_names` -> `pm.titled` | titled-name scan: "Councilman Jimmy Brown made ..." | a full name after a member's title in these minutes; a title preceded by "former" or "late" is not a member of this meeting |
| N5 | `city_build.RosterBook.for_meeting` (fed by `printed_full_names` after each read meeting) | surname book | full-name lists dated from the latest seating up to the meeting; a member is kept when on the latest list in the window or still printed for their ward or as mayor by the latest list that prints that seat; else held with the reason |
| N6 | `city_build.resolve_surnames` | attendance printed as surnames | exactly one full name from N4 (plus the presiding mayor) and N5, and a ward printed with the surname agrees; else no official and `surnames_resolve` holds the meeting (so all its roll calls) |
| N7 | `city_build.resolve` from `_add_minutes` | votes (`rc.votes`), block absences (`rc.absent`), `_out_of_room` | against this meeting's roster only (N1, N3, N6): full name, then surname, then initial plus surname, each exactly one match; else `names_resolve` holds the roll call |
| N8 | `resolve` from `_add_minutes` motion | mover and seconder | as N7; else `mover_resolves` / `seconder_resolves` holds the motion |

Tests: `collector/tests/test_city_names.py` has one test per path N1-N8, each through `assert_name_invariant` (every
resolved name of a meeting is on that meeting's attendance or is its presiding mayor, and every surname resolved from
the book names a list dated inside the meeting's window), plus the reviewer's case: a departed member's surname reused
by a new member.

### Consumers of a resolved name (`official_id`)
None may re-resolve a printed name; each reads `official_id` (null when held).
| Consumer | Where | Reads |
|---|---|---|
| Facts build | `city_build._add_minutes` | `meetings[].attendance[].official_id`, `roll_calls[].votes[].official_id`, `motions[].moved_by/seconded_by`, `officials[]` (title from N3), the checks `names_resolve`, `surnames_resolve`, `one_entry_per_official`, `voters_recorded_present`, `one_vote_per_present_member`, `mover_*`, `seconder_*` |
| Wards | `city_build` `_wards` -> `data/localities/clarksville-tn/wards.json`; `sitegen/council.py` `ward_rows`, `CouncilIndex` seats | holder records per ward (an unresolved print is not used) |
| Member pages | `sitegen/views.py` `official`, `official_counts`, `totals_sentences`; `sitegen/build.py` member and history pages | votes, attendance, motions per member |
| Meeting, vote and item pages | `sitegen/views.py` `meeting`, `_roll_call_block`, `_motion_block`, `votes_year`, `items_year` | the name shown and linked per vote |
| Held counts | `sitegen/views.py` held-back counts (an unresolved vote counted once, never shown raw) | `official_id` null |
| Search index | `sitegen/views.py` search records (`officials`, votes) | member names |
| CSV export | `collector/export.py` `officials.csv`, `attendance.csv`, `votes.csv`, `motions.csv` (provenance "derived: name resolution") | `official_id` |
| One-vote check | `collector/invariants.py` `one_vote_violations` | votes per (item, roll call) |
| QA spot check | `qa/spot_check.py` `candidates` | the names shown to the checker |
