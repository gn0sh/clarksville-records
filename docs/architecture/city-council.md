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

**Gates (problem family `city-verify`, 2026-11-11).** The city build reports AC-P1 (verified rate >= 90%) and G4 (skew)
with the county's own code, `collector/verify.gates`, unchanged ("Invariant: held-back counts" in
`docs/architecture/clarksville-records.md`), in `build/city-report.json` under `build.gates`, with `build.pass` true
only when both pass, and one line on stdout. No city check marks a hold as an error of the source document itself, so
none is left out of the rates. A G4 flag is a release block (spec G4): `collector city build|run` exits 3, the county's
gate code, after any fetch code (2, 5) is settled, and the workflow's Collect step fails on it like any non-zero city
code. The AC-P1 rate is reported only and sets no city code (the county's 3 covers both): at 79% today it would stop
every daily refresh, so whether it blocks the city is the manager's call. What can raise it without loosening a check,
and the launch treatment for the rest: "Verified-rate plan" below.

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
CLAUNCH was: "no roster entry"), or by a configured, cited member (`members`, path N10, "Verified-rate plan" below:
Eric Claunch, Ward 2, from the 2026-02-11 Special Session minutes).

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
  first 2027 meeting is built, a source of full names for the new council is needed: `members` entries (path N10),
  each citing a qualifying record of the seating (the 2027-01 minutes recording the oath, or certified results, see
  N10's list); until they exist, the drop is expected and is not a regression.

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
| N9 | `city_build.break_free_match`, the last step of N1, N6, N7 and N8 (new, `city-verify`) | a printed name no other step resolved | its break-free key (whitespace removed, nothing else changed) equals the key of exactly one candidate of that step's own closed set; else held as before. Rule and guards: "Verified-rate plan", W2 |
| N10 | `cfg.members_on(date)` into `RosterBook.for_meeting` (N5) (new, `city-verify`) | the configured, cited member | `members` in `agenda-center.yml`: a member seated between full-name lists, from `seated` on, replacing any earlier holder of that ward; the cite is checked against the stored file. Rule: "Verified-rate plan", M1 |

Note: W1 (invisible format characters, "Verified-rate plan") is a reading step in `city_minutes`, before any path: it
changes what is read to what the page shows, and resolves nothing by itself.

Tests: `collector/tests/test_city_names.py` has one test per path N1-N10, each through `assert_name_invariant` (every
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
| Member name source (new, N10) | `officials[].name_source` (schema: optional `{source_id, page, quote}`); `sitegen/views.py` `official` header; `collector/export.py` `officials.csv` `name_source_*` (provenance "stated: configured member") | the cited record for a configured member |
| Facts build | `city_build._add_minutes` | `meetings[].attendance[].official_id`, `roll_calls[].votes[].official_id`, `motions[].moved_by/seconded_by`, `officials[]` (title from N3), the checks `names_resolve`, `surnames_resolve`, `presiding_resolves`, `one_entry_per_official`, `voters_recorded_present`, `one_vote_per_present_member`, `mover_*`, `seconder_*` |
| Wards | `city_build` `_wards` -> `data/localities/clarksville-tn/wards.json`; `sitegen/council.py` `ward_rows`, `CouncilIndex` seats | holder records per ward (an unresolved print is not used) |
| Member pages | `sitegen/views.py` `official`, `official_counts`, `totals_sentences`; `sitegen/build.py` member and history pages | votes, attendance, motions per member |
| Meeting, vote and item pages | `sitegen/views.py` `meeting`, `_roll_call_block`, `_motion_block`, `votes_year`, `items_year` | the name shown and linked per vote |
| Held counts | `sitegen/views.py` held-back counts (an unresolved vote counted once, never shown raw) | `official_id` null |
| Search index | `sitegen/views.py` search records (`officials`, votes) | member names |
| CSV export | `collector/export.py` `officials.csv`, `attendance.csv`, `votes.csv`, `motions.csv` (provenance "derived: name resolution") | `official_id` |
| One-vote check | `collector/invariants.py` `one_vote_violations` | votes per (item, roll call) |
| QA spot check | `qa/spot_check.py` `candidates` | the names shown to the checker |

## Verified-rate plan (problem family `city-verify`, 2026-11-11)

Baseline (committed facts at 255039b): 1,756 of 2,235 city roll calls verified (78.6%); 2026 14 of 83. AC-P1 needs 90%.
The meeting-level `attendance_verified` hold covers 163 roll calls: 62 at the four 2026 meetings that print CLAUNCH,
24 at 2022-04-07 ("StaceyStreetman"), 18 at 2020-10-01 ("J eff Henley"), and the rest at 2016-07-07 (a member listed
twice), 2020-12-03 (attendance not parsed), 2023-07-06 ("DaJaun Little (Ward 3)m, arrived at 6:04)", a source typo)
and 2025-09-04 (ZAHARIAS). Three changes below (M1, W1, W2), one listing fix (D1), then the estimate and the launch
treatment. ADR 0005 records the decision. **Nothing here loosens a check:** every P2 check runs unchanged after them,
and every name still resolves only by an exact match against a closed set.

### M1. Configured, cited members (`members`, path N10)
For a member seated between full-name attendance lists, as `mayors` is for the Mayor seat. In
`config/localities/clarksville-tn/agenda-center.yml`:
```yaml
members:
  - name: Eric Claunch
    ward: 2
    seated: "2026-02-19"
    kind: minutes          # minutes | resolution | oath | roster_page | certified_results
    cite_url: "https://clarksvilletn.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=3068,plainText=false)"
    cite_page: 3
    quote: "Eric Claunch was selected as the Ward 2 replacement and was sworn in by Mayor Pitts."
```
**Claunch: a qualifying record exists.** The City Council Special Session minutes of 2026-02-11 (resumed 2026-02-19),
CivicClerk fileId 3068 (3 pages, Aspose.Words, text layer, sha256 df53b5ec7368...), page 3: "The following votes were
then taken: Round 33. Eric Claunch was selected as the Ward 2 replacement and was sworn in by Mayor Pitts." Page 1
prints "City Council - Special Session" and the 7 applicants; page 2 shows no one was seated on 2026-02-11 ("Because
the vote was recessed to February 19, there was no Oath of Office"). Read 2026-11-11 by the architect's labelled spike
(the collector's PoliteFetcher, robots.txt checked, 10 s apart, API host allowed by ADR 0003; bytes kept only in a
scratch folder). We did not hold it because CivicClerk files this meeting under category "General", event name
"Special Session", and our listing asks only for `categoryName eq 'City Council'` (D1). So the hold on the four 2026
meetings ends, and Ward 2's seat record starts 2026-02-19.

**What qualifies** (`kind`), each a record of the City or the Election Commission, stored by the collector:
- `minutes`: City Council minutes (any session) recording the person's election, appointment or oath to that seat.
- `resolution`: a council resolution or ordinance appointing or declaring the person to the seat.
- `oath`: an oath-of-office record posted by the City.
- `roster_page`: a stored snapshot of the City's official council roster page on clarksvilletn.gov naming the person
  and ward. It gives no seating date, so `seated` may not be earlier than the snapshot's fetch date.
- `certified_results`: the Election Commission's certified results, for a member elected at a regular election, with
  `seated` the `seating` date. Its host is not on the allowlist; adding it is a decision before 2027 (residual risk
  `city-votes/empty-book-2027`).
A full name printed in a later attendance list needs no entry: N1/N5 already read it.

**Not acceptable**: an applicant or candidate list (2026-02-05 and page 1 of 2026-02-11 list Claunch among seven), an
agenda (it schedules an act and does not record it: the 2026-02-11 agenda lists an "Oath of Office" that did not
happen), titled prose ("Councilman Claunch made a motion", N4), our transcripts or the video, news, social media,
campaign sites, and any inference of ours (a vacant ward plus a new surname, the votes a surname casts).

**Config check** (`agenda_center._members`, refused at load like a bad `mayors` entry): name is a full name
(`NAME_RE`); ward in 1-12; `kind` in the list; `seated` a date; `cite_url` https, `cite_page` a page, `quote` not
empty; two entries may not seat one ward on one date (a later entry for the same ward replaces an earlier one, as a
second mid-term change would). **Build check** (`city_build.cited_members`, `member_cited` per entry; the checks that
need the manifest are made here, since the config is loaded without it): the stored bytes for `cite_url` exist (so it
is in the city manifest); the stored file's manifest `kind` equals the entry's `kind`, and an agenda never qualifies
(review `city-verify/cited-member-kind-unchecked`); `seated` is on or after the cited record's meeting date (and the
fetch date for `roster_page`), and a missing date that check needs fails it (`cited-member-fail-open`); the quote
contains the name and prints "Ward {ward}" as whole words (`cited-member-ward-unchecked`); and the `quote`,
whitespace collapsed, is on `cite_page` of the stored
file's text (the city reader's, W1 applied); and the cited file is the `source_id` of a council meeting the build
kept (review `city-verify/cited-member-body-unchecked`: never another body's minutes, e.g. a D1 event whose page 1
fails). That last check needs the kept meetings, which never depend on the members, so when an entry fails it the
build runs once more without it and the first run is discarded. In effect only `minutes` entries can pass today; the
other kinds need a rule of their own before use. If any fails, the entry is left out of the book for that build (so the
surname is held as before) and the run report lists it (`build.members`, and `problems`); it never resolves anyone on
trust.

**How it feeds resolution.** `RosterBook.for_meeting(date)` adds each entry with `seated <= date` as the holder of its
ward, `"configured": True`, and drops any earlier holder of that ward from that date (the replaced-seat rule, as if a
full-name list had printed the successor). It stays in the book through later seatings only while no full-name list
or later entry gives the ward to someone else, and is never carried past the next `seating` date (a re-elected member
needs a list or a new entry). N6 then resolves CLAUNCH by exactly one book entry, a printed ward agreeing; N7/N8 read
the meeting's roster as before. Official id `city-eric-claunch`, name and ward as configured.

**How it is shown.** The member page header gets one line, the same for every configured member: "Name and ward from
the minutes of 2026-02-11, p. 3, fetched <date>: "<quote>"", the page linked as every source is (`views.name_source`;
the quote itself says the seating was on the resumed date). The
attendance check detail on meeting pages and in the run report reads "CLAUNCH: by the configured member Eric
Claunch (seated 2026-02-19, minutes p. 3)". Ward 2's seat history starts the record on 2026-02-19 with the same source
(seat holder invariant, rule 1); `officials.csv` and `seats.csv` carry the source.

### D1. Listing: City Council meetings filed under "General"
CivicClerk files some City Council meetings under category "General", under names that vary: "Special Session" (the
2026-02-11 session), "City Council Special Session", "City Council Special Session - First Reading of the Budget",
"Special Called City Council Meeting", "Special Budget Session", "Special Session and First Reading of the Budget",
"Special Work Session - Budget", "Regular Session" (2026-07-02). Other "General" events are other boards, some under
council-like names ("Special Called Senior Board Meeting", "Arts & Heritage Council", "One Time Event"). Evidence: the
full General listing 2024-01-18 to 2027-01-19 (374 events, read 2026-11-11) and page 1 of every candidate's agenda and
minutes.

**Contract** (`config/localities/clarksville-tn/civicclerk.yml` `also_list`, checked at load by `civicclerk._also`): one
entry per category, `{category_name, name_words, events}`; `events` is a list of `{event_name, page1}`.
- Discovery asks for `categoryName eq '<category>' and startDateTime ge <from_date> and (contains(eventName,'<w1>') or
  ...)` over `name_words` (one paged listing per category; `contains` is case-insensitive, checked 2026-11-11). A word
  is letters, digits and single spaces only (it goes into the OData filter).
- An event of that category is listed only when its whole name, whitespace collapsed, matches one `event_name` regex
  (`re.fullmatch`, case-insensitive; the first match wins). Its row carries `listed_as` ("General / <name as
  printed>") and `page1_required` = that pattern's `page1`. Any other event of the listing is not listed.
- The build keeps a listed event only when page 1 of its stored minutes or agenda prints that pattern's `page1` as a
  line of its own (whitespace and format characters aside; never the same words inside a longer line, review
  `d1-page1-substring`); any other is skipped and named in the run report. So a pattern's name never decides alone:
  "One Time Event" is listed, and the two with files (2024-07-09 ACT Authority, 2025-04-16 Public Safety Committee)
  are skipped on their page 1.
- The minutes of a kept event are read only when they vouch for themselves (`city_build.minutes_identity`, review
  `d1-minutes-identity/agenda-heading-vouches-for-minutes`): page 1 of the minutes prints the pattern's `page1` as a
  line of its own, AND every meeting date they print is the row's date: the call-to-order sentence's and the page-1
  heading's (`city_minutes.heading_date`, the first 8 printed lines of page 1), at least one printed, none another
  day. The agenda's page 1 can keep the meeting, never vouch for its minutes. Minutes that fail are not inspected,
  read or cited: the meeting is built from its agenda alone (`minutes_status: other_meeting`), or skipped when its
  agenda's page 1 does not print `page1` either.
- Each `event_name` must print one of `name_words` as plain letters at its top level (outside any group or class,
  no top-level alternation, no quantifier on the word's last letter, no inline flag), so the listing asks for every
  name the pattern can match; `civicclerk.load_config` refuses any other. Each URL template names only its own
  fields, bare (`events_url` {host} {from_date} {category}; `also_events_url` those and {names}, required;
  `file_url` {host} and {file_id}, required).
- Configured patterns and headings (each heading as page 1 prints it): the Special Session names, "Special Called City
  Council Meeting", "Special Budget Session" and "One Time Event" need "City Council - Special Session"; "Special
  Session and First Reading of the Budget" and "(City Council) Special Work Session (- Budget)" need "City Council -
  Special Work Session"; "(City Council) Regular Session" needs "City Council - Regular Session". "City Council
  Training Session" (2025-01-23, agenda only, page 1 "City Council Training Session") is not listed: not a meeting of
  the council's business. A new name needs a config line, found by re-running the full General listing (as fetched
  2026-11-11: `docs/research/civicclerk-general-listing-2026-11-11.json`, 374 events, 2024-01-18 to 2027-01-19;
  `test_the_committed_general_listing_lists_exactly_the_d1_rows` replays it against the config).
- The day page's "scheduled" cards (`sitegen/days.scheduled_cards`, from `civicclerk-listing.json`) never show a row
  with `page1_required`: a future General event has no stored file, so nothing has shown it is the council's.

The check runs before the two listings are joined (`civicclerk.merge_sources(page1_ok=)`,
review `city-verify/d1-merge-before-page1`): a D1 row is paired with an Agenda Center meeting of the same date and kind
only after it passes, so a failing row never replaces a council meeting nor is cited under its `also_listed`; with no
check (no store), a D1 row is never paired.
This stores fileId 3068 (needed by M1's build check) and adds that meeting: 2 roll calls (one prints "HOLLEMNA", held).

**One minutes file for two meetings** (`city_build._other_meeting`): the 2026-02-19 event is the session of 2026-02-11
resumed, and its Minutes file (fileId 3069) is the same bytes as 3068. The existing rule reads such a file only for the
meeting whose date it prints, once. The 2026-02-11 call-to-order sentence prints no year ("on Wednesday, February
11, at 4:30 PM"), so the date falls back to the page-1 heading's date line (`city_minutes.heading_date`: a page-1 line
before the "MINUTES" title that is a date and nothing else, "February 11, 2026 at 4:30 PM"). Without it neither meeting
read the file, and the 2026-02-11 roll calls and M1's cited record (so 39 CLAUNCH roll calls) were lost.

**Widened (2026-11-11):** 16 meetings added (2025-02-18, 06-17, 06-24, 11-12; 2026-02-19, 04-06, 04-29, 05-07,
05-26, 06-11, 06-16, 06-22, 06-29, 07-02, 07-06, 07-09; 12 with minutes, 11 read), 147 roll calls, 110 verified.
City roll calls 1,823 of 2,237 verified -> 1,933 of 2,384 (81.1%); every roll call verified before is unchanged,
votes included (`tests/test_city_verify_data.py`, V6 digest). Held in the new meetings: source typos such as
"CLAULNCH" (2026-07-06 attendance, so all 11 of its roll calls) and "SSTREETMAN".

**Minutes identity (2026-11-11, after review of acc8832):** of the 13 D1 rows with minutes, 11 pass. Two do not:
2026-02-19 (its file is the 2026-02-11 minutes; its agenda's page 1 prints "City Council - Special Session
(Continuation" on one line, not the heading alone, so the event is now skipped; it had no roll calls) and 2026-07-09
(page-1 heading "July 9, 2026 at 4:30 PM", but called to order "on Monday, July 6, 2026": two dates, so held; its
agenda keeps the meeting, `other_meeting`, and its 30 roll calls, 21 verified, are not read). Rebuilt from the store
(2026-11-12, all 608 manifest files byte-identical): 1,912 of 2,354 verified (81.2%), 401 meetings; the 1,823 of the
V6 digest are not touched (none is in a D1 meeting). The latest attendance list is now 2026-07-06. Its page 1
(fileId 3254, text layer) prints "PRESENT: BROWN, CHANDLER, CLAULNCH, HAYWOOD, ..." (13 names, "ABSENT: NONE"), but
the same page prints CLAUNCH in its votes ("AYE: CHANDLER, CLAUNCH, HAYWOOD, ..."). As printed, CLAULNCH resolves to
no one, so Ward 2's Eric Claunch was held over, and a held-over note says what the list prints ("the attendance lists
of 2026-07-06 print a name the record cannot place: CLAULNCH"), never "not named", unless the list truly leaves the
member out (city-seats/held-over-note-says-not-named).

**Printing corrections (2026-11-12, city-seats/printed-misspelling-of-seated-member).** `agenda-center.yml
printing_corrections` holds curated, per-meeting, attendance-only corrections, each `{meeting, minutes_url, page,
printed, reads}`; the one entry is `{2026-07-06, fileId 3254, p. 1, CLAULNCH, CLAUNCH}`. The build
(`city_build.printing_corrections`) applies an entry only to the meeting whose date and minutes file it names, and
only when: that page prints `printed` once in its PRESENT list and it does not resolve as printed; the attendance does
not also print `reads`; a vote line of that page prints `reads`; and `reads` is exactly one full name on the meeting's
roster book, which no other attendance entry resolves to (the one member the list otherwise leaves out). Otherwise it
is not applied (fail closed: the token stays held), with a failed `printing_correction` check, a run-report problem
and a `printing_corrections` report row. Vote, absent, mover and seconder tokens are never corrected, nor any other
meeting or page. The attendance entry keeps `raw_name` as printed; its wards.json row adds `reads`. A seat record
read through it says so plainly wherever its dates are worded, and the council home's seat line shows 'the attendance
lists of 2026-07-06 print the name as "CLAULNCH"', linked to that page.

### W1. Invisible format characters in the text layer (a reading fix)
2020-10-01 page 1 prints "Jeff Henley"; its text layer has "J", a zero-width word (U+200B ZERO WIDTH SPACE, x0 = x1 =
427.74) and "eff" whose box starts exactly where "J" ends (x 432.410154 both). Our line assembly turns that into
"J eff Henley". Rule, in the city reader's line assembly: delete Unicode format characters (category Cf: U+200B,
U+200C, U+200D, U+2060, U+FEFF, U+00AD) from every word; a word left empty is dropped; and the two words it separated
on one line are joined only when they abut (`next.x0 - prev.x1 <= 0.05` pt). A visible gap is never closed. The
result is exactly what the page shows, so this is a better single reading, not a repair: it keeps the independent
readings rule trivially. Scope: the city reader only (the county's and RPC's text layers are OCR and have none seen).

### W2. Printed word breaks: the break-free key (path N9)
"StaceyStreetman (Ward 10)" (2022-04-07, page 1) is printed with no gap: its one glyph box, 80.6 pt, is the width of
"Stacey" plus "Streetman" with no space, so the source itself omits the space. CivicClerk vote lists print the
opposite, a break inside a name: "H AYWOOD" (a 3.3 pt gap), "H olleman", "LOV ATO". Every letter is printed, in
order; only a word break differs.

**Decision: yes, with these guards.** It keeps the rule. A name is one reading resolved against a closed set by exact
match with no fuzzy merge ("Invariant: independent readings", `docs/architecture/clarksville-records.md`); the county's
rule 1 already collapses spaces; and the shown-form rule already treats word breaks as the unreliable part of a reading
("the text layer drops spaces, tesseract adds them"). The key compares every printed letter exactly; no reading is
combined, outvoted or corrected. Rule:
1. **Last step only.** Tried only for a printed name (attendance entry N1/N6, vote or absence token N7, mover or
   seconder N8) that every other step left unresolved.
2. **Key.** `break_free(s)`: lowercase (`str.lower`, as every other step compares) and remove whitespace. Nothing
   else changes: no letter, apostrophe, hyphen or period is added, dropped, replaced or reordered (so no NFKC or
   casefold, which turn one letter into others: "ß" -> "ss"; review `break-free-casefold`).
3. **Closed set of that step.** N1/N6: the full names and the surnames of the meeting's roster book (N5, N10). N7/N8:
   that meeting's own roster (its resolved attendance plus the presiding mayor), full name or surname.
4. **Unique.** The token's key equals the key of exactly one person in that set; two or more, or none, is held as
   before. A printed ward must agree (N6).
5. **Never** edit distance or near spellings (STRETMAN, AYWOOD, ZAHARIAS, HOLLEMNA, PITT, "R reynolds" stay held),
   never a join across a comma, line end or other token boundary the parser drew (a lone "H" stays held), never a split
   of one token into two votes ("Burkhart Erb", "Alexander. Allen" stay held), never a person outside the set. A
   name list that wraps keeps its line ends (`_block` joins lines with "\n"): a token printed over a line end
   ("Hay" / "Wood") is flagged (`Vote.line_cut`, `Person.line_cut`, `RollCall.absent_cut`) and N9 is not tried for
   it, so it is held; the exact steps still read a full name wrapped at its space ("Jerry" / "Haywood").
6. **Checks unchanged.** P2 runs after it as before, so a join that gives a member a second vote is held by
   `one_vote_per_present_member`.
7. **Auditable.** The `names_resolve` (or `surnames_resolve`) check detail names each use, the same words whichever
   way the spaces differ ("H AYWOOD read as Jerry Haywood (same letters, spaces ignored)", "StaceyStreetman read as
   Stacey Streetman (same letters, spaces ignored)"); `build/city-report.json` lists every use
   (`word_break_matches`: meeting, page, printed form, member); QA's AC-P2 sample includes at least 3 of them.

### Tests (all through `assert_name_invariant`, plus a data regression)
- W1: the real 2020-10-01 page 1 boxes ("J", the U+200B word, "eff", "Henley") read as "Jeff Henley" and resolve (N1);
  the same with a 3 pt gap after the zero-width word stays "J eff Henley" (held); a soft hyphen inside a word is removed.
- W2: "StaceyStreetman (Ward 10)" with Stacey Streetman (Ward 10) on the book resolves; with "(Ward 9)" printed it is
  held; "H AYWOOD", "H olleman", "LOV ATO" resolve against the meeting's roster; STRETMAN, AYWOOD, HOLLEMNA, PITT,
  "R reynolds", "Burkhart Erb", "Alexander. Allen" and a lone "H" stay held; two roster people whose keys collide
  ("Mary Ann Lee" and "Maryann Lee") hold the token; a key matching only someone outside the meeting's roster is held;
  a join that duplicates a member's vote holds the roll call; for every N9 match, `break_free(printed) ==
  break_free(name or surname)` (added to `assert_name_invariant`).
- M1: the real 2026-02-11 page 3 text with the `members` entry resolves CLAUNCH at 2026-03-05 and no meeting before
  2026-02-19; the applicants page alone (2026-02-05, 2026-02-11 p.1) resolves nothing; a quote not on the cited page,
  a `cite_url` not stored, a `seated` before the cited meeting, a non-full name and two overlapping Ward 2 entries are
  each refused or left out with the reason; the entry replaces Deanna McLaughlin in Ward 2 from 2026-02-19.
- D1: a "General" "Special Session" whose page 1 prints "City Council - Special Session" is kept; one that prints
  another board is skipped and reported. Widened: each real council name under "General" is listed with its own
  heading and kept only on that heading (another council heading is not enough); other bodies' General names (and a
  council name in another category) are not listed; a "One Time Event" whose page 1 is another body's is skipped and
  named; a bad `also_list` (old flat form, a word with a quote, a bad regex, a category twice) is refused at load;
  minutes posted for a session and its resumption are read once, for the heading date.
- Data: the build on the committed store changes only the expected roll calls from held to verified (ids listed in the
  test), changes no vote of an already verified roll call, and adds the one D1 meeting.

### Estimate (simulated on the committed facts, 2026-11-11)
Each held roll call counted as cleared only when every failing check is one these changes clear (a token resolved by
M1/W1/W2, the attendance hold at the four CLAUNCH meetings, 2020-10-01 or 2022-04-07, and a `one_vote_per_present_member`
naming only members whose token now resolves) and, at the CLAUNCH meetings, CLAUNCH votes in it:
| | Verified | Rate |
|---|---|---|
| Now | 1,756 / 2,235 | 78.6% |
| + M1 CLAUNCH | +39 | |
| + W1/W2 attendance (2020-10-01: 18; 2022-04-07: 6; the other 18 there also lack a vote for DaJuan Little, 13 of them for Vondell Richmond too, both printed "left early") | +24 | |
| + W2 vote tokens elsewhere | +3 | |
| After | 1,822 / 2,235 (D1: about 1,823 / 2,237) | 81.5% |
2026 goes from 14 to 53 of 83. **Built (V6, 2026-11-11):** 1,823 of 2,237 (81.5%), 2026 54 of 85: the 66 estimated
plus the D1 meeting's 2 roll calls (one verified, one held: "HOLLEMNA"); no verified vote changed
(`tests/test_city_verify_data.py`). **90% is not reachable this way**: it needs 2,012, 190 more. Of the 413 still held,
272 fail `one_vote_per_present_member` (a member on the attendance list with no vote and no NOTE, often printed
"left early" or "arrived at"), 248 have a misspelt or unparsed vote name, 100 sit at meetings whose attendance is held,
52 fail `outcome_consistent`. Each is a printed fact we cannot confirm without guessing who voted how or when a
member left, so no rule we would accept closes the gap.

### Launch treatment (a decision for Brian)
Recommendation: **show city roll calls at the verified rate they reach (about 82%), the held ones as the spec's P3
already does (listed, link only, no value read from them), with a plain reason per hold**; report the city's rate
on the About page and in the run report; AC-P1 stays the county gate (it passes) and is reported, not blocking, for
the city. Alternatives: (B) leave City Council votes off the public launch until 90% (the meetings, documents and
attendance still ship); (C) hold the whole city section. Default if no answer: (B). Today every held vote reads "Not
confirmed: this page was hard to read", which is wrong for most city holds (the page reads fine; the minutes leave
something out). Per-check sentences, the same for every member (`config/finance_text.yml` `held`, or a city copy):
| Check | Shown |
|---|---|
| `one_vote_per_present_member` | "Not confirmed: the minutes list a member as present but give no vote for them here." |
| `names_resolve` / `surnames_resolve` | "Not confirmed: a name in this vote does not match a member on the official record." |
| `attendance_verified` (wins whenever it failed) | "Not confirmed: this meeting's attendance list could not be matched to the official record." |
| `outcome_consistent`, an outcome read (passed or failed) | "Not confirmed: the stated outcome could not be matched to the votes listed." |
| other or several (incl. `outcome_consistent` "outcome not read") | "Not confirmed: the automatic checks did not pass." |

Rules (review `city-verify/held-sentence-accuracy`, 2026-11-11): no sentence says the minutes are wrong, since a hold
may be our reading's (a mispaired outcome, an outcome sentence not read). `attendance_verified` wins over any other
failed check, because every other check of the roll call reads that attendance (before, it never showed: all its
roll calls fail another check too). `outcome_consistent` gets its sentence only when an outcome was read; with
"outcome not read" (outcome `other`) the sentence about a stated outcome would be untrue, so it counts as no sentence.
`sitegen/views.held_key`, mirrored in `qa/site_checks.held_sentence`; pinned on the committed facts by
`tests/test_council_pages.py`.

## Seat holder invariant (problem family `city-seats`, keys `current-holder-matches-latest-attendance`, M1 `pipeline/seats-stale-on-new-county-meeting`)

**Invariant.** A seat's current holder is the member recorded in that seat (a printed ward, a confirmed roll call for
a title seat, a district in the county's roll-call tables) who is still listed at L, the latest meeting read, unless
the record shows a successor; when the record cannot place anyone in a seat, the seat says "Current member not yet
recorded".

**Why it broke (2026-11-10).** `council.holder_rows` took L as the latest end over all records. Ward records end at
the last attendance list that printed a ward (2025-03-06: the CivicClerk minutes from 2025-04 print names only) and
the mayor's at the last confirmed roll call (2026-02-05), so every ward record was closed while the same lists still
listed each member to 2026-06-04. The county had the same shape: an open row of the hand-derived `seats.yml` was
worded "to L, the latest meeting collected" with L from the facts, so one new meeting dated every open row past the
page it cites.

**Rule.** (1) `council.extend_by_listings`: a record runs on through later attendance lists that list its holder by
name, until another record of the same seat, or another seat of the same member, starts; it keeps `printed_to` (the
last print) and the page wording says both ("seen in attendance lists from X to P; listed by name in attendance lists
to L, the latest minutes read"). L is the latest attendance list read (never a roll call at a meeting with no
list). A name that resolves to no official (CLAUNCH, held by the name-resolution invariant) is never placed, so Ward 2
says "not yet recorded". One list does not close a record, nor keep it current: a member last listed at the list
before L whom L's list does not name is held over (`held_over`) when L's list is incomplete (an unresolved name, or
fewer members than the list before) and no successor starts. A held-over record is neither current nor former: its
seat reads "Current member not yet recorded" with the line "last listed in attendance lists X; not named in the
attendance lists of L", the member is listed under "Not named in the latest minutes" (never as a seat's holder; the site check fails a
held-over member shown as holder, or a note naming someone not held over in that seat), and the member page keeps the dates. A
wrong current member is the worst failure; "not recorded" is acceptable (re-review of 7895b63).
`seats.csv` gives `printed_last` (+ source) for the last page printing the seat and `listed_last` (+ source) for the
last names-only list. (2) `seats.stamp_seen`: a
county row is seen to its end, or to the meeting of its `last_source` page; when that is before the latest meeting
collected, L is that meeting, worded "the latest meeting read for seats", and no seat covers a later vote.
`tools/seat_check.py` check 4 judges open rows against the same L (`read_to`), so a new meeting no longer fails the
suite; a new voter with no seat still does (a successor to read: re-run `tools/derive_seats.py`).

| Consumer of seat ranges | Where | Reads |
|---|---|---|
| City home: seats list, Current / Served previously, basis line | `council.seat_list`, `home`; `views.officials_page`, `observed_basis` | `Seats.current_of_seat`, `is_current`, `latest` |
| Landing: county districts, council seats, ward map links, "Your seats" (`static/seats.js`, reads the landing rows), address lookup (links `#seat-ward-N`) | `views.district_rows`, `council.landing` | `current_of_seat` |
| County seat pages `districts/NN.html` | `views` district context | `for_seat`, `current_of_seat`, `view`, `basis` |
| Officials page and member page headers | `views.officials_page`, `official` (`header_text`, `seat_text`) | `dates_text` |
| Seat beside each vote and attendance row (meeting, vote-history and year pages) | `views` (`Seats.on`) | record start/end (`seen_to` for an open county row) |
| Search index (`st`, officials labels) | `views.search_index` | `seat_text` |
| CSV export `seats.csv` | `collector/export.py` `seats_csv` (county: raw `seats.yml`; city: `cix._rows`) | `start`, `end`, `last_source` |
| Seat check | `tools/seat_check.py` | `seats.yml` against the facts |
| Site check `current-holders` | `qa/site_checks.py` `check_current_holders` | built pages vs `wards.json` / roll calls |
| Feeds, morning note | none: they read a case's printed district or ward, never holder records | — |

Tests: `tests/test_city_seats.py` (the rule, the committed city data, the county with one new meeting),
`tests/test_map_seats.py` (seat check with a new meeting), `tests/test_council_pages.py`.

## Call-on invariant (problem family `transcripts/call-on-misattribution`)

Stated after the family's second hit (review of the transcript feature, 2026-11-09). A "call-on" is the moment the
chair gives a member the floor, read from the automatic (Whisper) transcript TEXT only (`sitegen/transcripts.py`);
member pages list it as "Called on in meetings". **Never attribute words or an action to the wrong named person: if in
doubt, hold (no call-on, no link).**

**Accepted forms (exactly these; case and `'`/`’` free).**
1. `<title> <surname>[,] you're | you are | you recognized` (also "recognised"), all in ONE clause: between the
   surname and "you" only spaces and commas (`[\s,]*`); a full stop, `;`, `:`, `?`, `!` or `-` there breaks the match.
   The recognition phrase must END the clause: what follows it is `. ; : ! ?`, a comma only after "you're" / "you
   are" (never after a bare "you recognized": "you recognized, I think, the problem" is held), or the member's reply
   starting a new sentence, which Whisper often leaves unpunctuated and which is accepted only as the words "thank
   you" / "thanks" (never "thanks to"). The end of a segment's text ends the clause only when it is the last segment
   or the next segment's text starts with one of these ("you recognized" | "that the budget was short" is held).
   Anything else after it ("you recognized that the budget...", "you're recognized on the consent agenda", "you are
   recognized for your service") is held.
2. `the chair recognizes <title> <surname>` (also "recognises").

`<title>`: Councilman/-woman/-person/-member/-lady, Chair(man/woman/person), Vice Chair(...). `<surname>`: the one
word after the title, never a word in `NOT_A_NAME`.

**Never accepted.** A bare "recognized"/"recognizes" after a name ("Councilwoman Smith recognized the students"); "you
recognize"; a recognition in the next sentence ("Thank you Councilman Smith. You are recognized, Councilwoman Jones.",
"I yield to Councilman Smith. You recognized me earlier."); "you recognized" followed by an object; a title with no
surname; a mention ("I agree with Councilman Smith"); any near spelling.

**Resolution (already in force, `resolve`/`roster`).** The surname links a member only when exactly one entry of that
meeting's own attendance, as shown on the site, has it, and that entry resolved to a member listed present. An entry
listed absent blocks its surname and never links; an entry that did not resolve blocks every word of its printed name
and every registered surname inside it. No attendance shown (no minutes read, or under review), no match or two
matches: no link.

### Consumers of call-on data
None may re-detect or re-resolve; each reads `Transcripts.call_ons` (resolved entries only).
| Consumer | Where | Reads |
|---|---|---|
| Member pages "Called on in meetings" | `sitegen/council.py` `member` -> `Transcripts.member_rows`; `site/templates/official.html.j2` | date, time, video `#t=` link, transcript line link, matched words, excerpt |
| Transcript page markers | `Transcripts.lines`, `Transcripts.page` (`call_on_count`); `site/templates/transcript.html.j2` | per-line member name and link; the count |
| Site checks | `qa/site_checks.py` transcript check (`ul.call-ons` entries) | each entry's meeting and video link |
| CSV/JSON export | none: `collector/export.py` exports no transcript or call-on data | — |
| Search index | none | — |

Tests: `tests/test_transcripts.py` (forms accepted and held, including the reviewer's sentences; resolution rules;
every resolved call-on on the meeting's own shown attendance).
