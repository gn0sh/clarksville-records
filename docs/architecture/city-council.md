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
mayor when the roster book has that name as the Mayor seat. The roster book is the full-name attendance lists printed
since the council's latest seating, for members whose ward (or the mayor's seat) no later list in that window gives to
someone else, plus the configured, cited mayor whose term covers the meeting (`mayors` in `agenda-center.yml`). A
surname printed alone counts only against that book. **Titled prose in the minutes is never evidence**: a name after
a member's title in the text ("Councilman David Allen moved to Clarksville in 1985", "the Pledge was led by Councilman
X", "called to order by Mayor Wes Golden") never adds a person or a candidate, whatever the sentence around it
(`city-votes/titled-nonmember`, `city-votes/presiding-guest`, after repeated fixes that tried to tell a sitting member's
action from other prose and each let some prose through). Any other name (no match, two matches, a match only on a
list older than the window, a member since replaced, or a presiding mayor the book does not have) is held, never
guessed.

**The window: the council's seating.** Every wholesale change of members in the full-name attendance lists of
2016-2025 falls at the first January meeting of an odd year (2017-01-05, 2019-01-03, 2021-01-07, 2023-01-05,
2025-01-02: members elected in November of the even year take their seats), so a list from before the latest seating
is never used (`seating` in `config/localities/clarksville-tn/agenda-center.yml`; observed in the data, not taken from
the charter). Mid-term changes (2019-07, 2021-11, 2022-05, 2023-06, CLAUNCH 2026) are covered by the replaced-seat rule
when a later full-name list prints the successor, or by the successor's own surname (a surname on no list is held, as
CLAUNCH is: "no roster entry").

**The mayor's seat: configured, cited.** The mayor is on the attendance list of only 8 of the 192 read minutes that a
mayor called to order, so the lists alone cannot put the mayor on the roster, and the call-to-order sentence is prose.
`mayors` in `agenda-center.yml` lists each mayor with an inclusive term and the stored minutes that print the person as
the city's mayor (Kim McMillan 2015-01-01..2018-12-31, Joe Pitts 2019-01-01..2026-12-31; terms may not overlap, and the
config is refused otherwise). The presiding mayor joins the roster (check `presiding_resolves`) only when that entry,
a full-name list in the window printing the name as Mayor, or the meeting's own list printing it in full with the
Mayor title has the name; otherwise the presiding name is held, makes no official and is never put in the book, and
the meeting is held. On the stored data (2026-11-09) 168 presiding mayors resolve by the configured seat, 17 by a list
in the window and 7 by their own list; none is held. A mayor seated 2027-01-01 needs a new cited entry before those
meetings are built.

Residual risk, accepted and named (`city-votes/empty-book-2027`, review of 2026-11-09):
- **Any departed member's surname.** The attendance has printed surnames only since 2025-03-06, so no full-name list
  after 2025-02-06 can print a successor, and the replaced-seat rule cannot fire for any change after that date. A
  member who joins after 2025-02-06 and shares the surname of *any* member on the 2025-01-02 or 2025-02-06 lists who
  has since left (not only the predecessor in the same ward) resolves to that departed member, with verified votes.
  Prose that prints the newcomer's full name no longer holds the surname, since titled prose is never evidence either
  way. Nothing in the stored data shows such a case today; it would show only as a wrong name, not as a held check.
- **The 2027 empty book.** At the seating of 2027-01-01 the window restarts and, while the attendance stays surnames
  only, it holds no full-name list at all, and Joe Pitts's configured term ends 2026-12-31. From the first meeting of
  2027 every surname, and the presiding mayor, is held until a cited entry covers it, so most 2027 meetings and their
  roll calls will be unverified. That is safe (held, never guessed) but a large drop in the verified rate. Before the
  first 2027 meeting is built, a source of full names for the new council is needed (a seating list from the election
  results as a committed, cited config entry, like `mayors`); until one exists, the drop is expected and is not a
  regression.

Handled, no longer residual: **a former member, a guest or another body's officer named with a title.** "The Pledge
was led by Councilman David Allen, who served Ward 2 until 2021", "the Pledge was led by Mayor Wes Golden of Montgomery
County", "WHEREAS, Councilman David Allen moved to Clarksville in 1985", "presided over the Finance Committee", "A
presentation was made by Councilman X", "honoring Councilman X, seconded by the Council": each once matched the action
patterns and resolved the surname. With titled prose never evidence, ALLEN and GOLDEN stay held ("no roster entry"),
and a joint session "called to order by Mayor Wes Golden" makes no official and resolves no GOLDEN vote. The cost was
nil on the stored data: no roll call, motion, meeting or attendance entry changed status or attribution (the 16
surname-era meetings whose surnames resolved "by these minutes" all had the same member in the book).

The window is at most two years and needs no upkeep while the seating pattern holds; a change of pattern is a config
change.

### Code paths that resolve a printed name
| # | Where | Path | Rule |
|---|---|---|---|
| N1 | `city_build._add_minutes` attendance loop, `Officials.add` | attendance printed in full (`NAME_RE`) | the printed full name is the member (id `city-<slug>`); not a name: no official, `names_well_formed` holds the meeting |
| N2 | `Officials.canonical` and `resolve(..., aliases)` (`aliases` in `agenda-center.yml`) | aliases: one printed full name -> another | whole printed names only, each the same ward in the same term (checked in wards.json); applied in N1 and N3, and in N7 and N8 by `resolve` canonicalizing the vote, absence, mover and seconder token before matching (a bare surname is never an alias key, so only a full-name token can change) |
| N3 | `city_build.presiding_mayor` from `_add_minutes`; `city_minutes.parse_people` `Person.mayor`; `mayors` in `agenda-center.yml` | the presiding mayor ("called to order by Mayor Joe Pitts") and a list entry with the Mayor title or "(Mayor)" | a list entry printed in full is N1, with the Mayor title. The presiding name joins this meeting's roster with the Mayor title only when the book (N5) has it as the Mayor seat (the configured, cited mayor for the date, or a list in the window printing it as Mayor) or this meeting's own list prints it in full as Mayor (`presiding_resolves` ok); else it is held: no official, not on the roster, never put in the book, and `presiding_resolves` holds the meeting (`city-votes/presiding-guest`: "called to order by Mayor Wes Golden"). A Mayor Pro Tem presiding is already on the PRESENT line and the sentence adds nobody |
| N4 | none (removed: `titled_names`, `pm.titled`, `pm.titled_acting` and their regexes, 2026-11-09) | titled prose: "Councilman Jimmy Brown made ...", "the Pledge was led by Councilman X", "Mayor Wes Golden" | **never evidence**: a name after a title in the text adds no person and no surname candidate, in an action of the meeting or not, sitting member or not (`city-votes/titled-nonmember`). The former member leading the Pledge, a guest, another body's mayor and every other prose form are handled by this rule: the surname resolves only through N5 or is held with "no roster entry" |
| N5 | `city_build.RosterBook.for_meeting` (fed by `printed_full_names` after each read meeting: the attendance printed in full only, never the call-to-order sentence) and `cfg.mayors_on` | the roster book | full-name lists dated from the latest seating up to the meeting; a member is kept when on the latest list in the window or still printed for their ward or as mayor by the latest list that prints that seat; else held with the reason. Plus the configured, cited mayor whose term covers the meeting (`"configured": True`, dated from the term's start) |
| N6 | `city_build.resolve_surnames` | attendance printed as surnames | exactly one full name on the book (N5), and a ward printed with the surname agrees; else no official and `surnames_resolve` holds the meeting (so all its roll calls), naming "no roster entry" and why any earlier printing was not used |
| N7 | `city_build.resolve` from `_add_minutes` | votes (`rc.votes`), block absences (`rc.absent`), `_out_of_room` | the token through the aliases (N2), then against this meeting's roster only (N1, N3, N6): full name, then surname, then initial plus surname, each exactly one match; else `names_resolve` holds the roll call |
| N8 | `resolve` from `_add_minutes` motion | mover and seconder | as N7; else `mover_resolves` / `seconder_resolves` holds the motion |

Tests: `collector/tests/test_city_names.py` has one test per path N1-N8, each through `assert_name_invariant` (every
resolved name of a meeting is on that meeting's attendance or is its presiding mayor when `presiding_resolves` is ok,
and every surname resolved from the book names a list dated inside the meeting's window), plus the reviewers' cases: a
departed member's surname reused by a new member; the delta re-review's six prose forms (ALLEN or GOLDEN stays held);
every form the titled-name scan once read (never a candidate); a joint session called to order by Mayor Wes Golden
(no official, no GOLDEN vote, in the surname and the full-name shapes); a configured mayor outside its term; and bad
`mayors` entries refused.

### Consumers of a resolved name (`official_id`)
None may re-resolve a printed name; each reads `official_id` (null when held).
| Consumer | Where | Reads |
|---|---|---|
| Facts build | `city_build._add_minutes` | `meetings[].attendance[].official_id`, `roll_calls[].votes[].official_id`, `motions[].moved_by/seconded_by`, `officials[]` (title from N3), the checks `names_resolve`, `surnames_resolve`, `presiding_resolves`, `one_entry_per_official`, `voters_recorded_present`, `one_vote_per_present_member`, `mover_*`, `seconder_*` |
| Wards | `city_build` `_wards` -> `data/localities/clarksville-tn/wards.json`; `sitegen/council.py` `ward_rows`, `CouncilIndex` seats | holder records per ward (an unresolved print is not used) |
| Member pages | `sitegen/views.py` `official`, `official_counts`, `totals_sentences`; `sitegen/build.py` member and history pages | votes, attendance, motions per member |
| Meeting, vote and item pages | `sitegen/views.py` `meeting`, `_roll_call_block`, `_motion_block`, `votes_year`, `items_year` | the name shown and linked per vote |
| Held counts | `sitegen/views.py` held-back counts (an unresolved vote counted once, never shown raw) | `official_id` null |
| Search index | `sitegen/views.py` search records (`officials`, votes) | member names |
| CSV export | `collector/export.py` `officials.csv`, `attendance.csv`, `votes.csv`, `motions.csv` (provenance "derived: name resolution") | `official_id` |
| One-vote check | `collector/invariants.py` `one_vote_violations` | votes per (item, roll call) |
| QA spot check | `qa/spot_check.py` `candidates` | the names shown to the checker |
