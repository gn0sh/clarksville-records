# Committee words invariant (loop rule: `committees-privacy` hit 3)
Manager decision, 2026-11-16, after two security reviews of r2-committees (4fb62d0, then 4fb62d0..f67146f) found
private people's names getting past a deny-list (claim words and capitalised-word heuristics in
`collector/committee_minutes.py`). The design changes from "mask what looks private" to "publish only what is
allow-listed". Written by backend-engineer before the code.

**Hit 3 (third security review, 4e1b570):** the allow-list still had holes. Rule (a) "public legislation" let any
capitalised word through except right after a preposition ("Resolution 5-2025-26 appointing John Doe and Jane Roe to
the Housing Authority" passed: M1 `legislation-free-words`); name words sat in `words` ("al", "Court", "Sale": L3
`name-vocabulary`); tokens were ASCII only, single letters and Roman numerals were free (L4 `ascii-tokens`); QA
copied the gate's leniency and checked only rendered spans (L5 `qa-mirror`). Restated below before the fix; rule (a)
is gone (on the real data it published nothing rule (b) would not, so dropping it cost nothing).

**Fourth review (security re-review of 2ec457c, PASS WITH LOWS):** surnames still sat in `words` (bonds, block,
prior, holiday, east, hazard, reading, fort, bridge: L1 `name-vocabulary`), and a capital lone letter was free, so
"Settlement J. Bonds" passed (L2 `lone-initial`). Those words moved to `lowercase_only` with phrases for their real
capitalised uses ("First Reading", "Gas Bonds", "Natural Hazard Mitigation", "Pedestrian Bridge", "Juneteenth City
Holiday", ...); step 4 below now also catches letters split by any one or two other characters ("J/Q", "J-P"); a new
step 4a withholds an initial before a capitalised word. QA gained its own initial rule and a common-names deny-list
(L4). On the committed data these changes withheld nothing that was published before.

## The invariant
**Every capitalised or single-letter token shown is on the roster, in `words`, or inside a `phrase`; nothing else.**
"Shown" means every string of `data/localities/clarksville-tn/committees/committees.json`, of the committed
`listing.json` and of the manifest labels, whether or not a page renders it today. "On the roster" includes the
allowed spans built from it: "<title> <roster name or surname>", an AYE/NAY list of roster surnames. A date ("May 26",
"the August meeting") is an allowed span too. The only other letters allowed: a lowercase word of `lowercase_only`
outside a strict position, a lone single letter, a Roman numeral right after Title/Chapter/Phase/Part, and an
upper-case Roman item number at the very start ("IV. ADOPTION OF MINUTES"). A field that fails is `null` (motion words),
replaced by a fixed text (meeting title, document name) or dropped (attendance note), and the motion carries the
fixed note "Item words not shown (may name a private person); see the minutes" with the minutes page link. Names are
published only when on the roster. Reasons are codes, never quoted minutes text.

The allow-list lives in one file, `config/localities/clarksville-tn/committee-words.yml`:
- `officials`: the roster. Every city council member and mayor in `data/localities/clarksville-tn/facts.json`
  officials, plus every Finance and Audit Committee member the minutes print in a members-present line (the Audit
  Committee's appointed members). A test checks that each roster name has one of those sources, so no one else
  can be added.
- `titles`: words that put a roster surname in an official role (Councilman, Councilperson, Chairman, Mayor, ...).
- `words`: a fixed public vocabulary, matched without regard to case. It holds ordinary words, departments, funds,
  places and abbreviations (CDE, CGW, FY, ...). It never holds a word that is also a common given name or surname
  (hit 3 moved al, early, fine, court, minor, more, main, plant, card, sale, back, urban out).
- `lowercase_only`: ordinary words that are also names (grant, park, court, sale, ...). They are allowed only when
  printed in lowercase, and never as the first word after a preposition unless an article comes between them.
- `phrases`: fixed phrases that contain such a word ("Parks and Recreation", "City Court", "Jordan Rd", "et al").
  They are allowed only as the whole phrase (any case).
There is no organisation list: a company named in a motion is not on the list, so its words are not shown.

## The rule (one text, e.g. a subject; the same for every text, legislation included)
1. **Belt and braces first** (motions only). The field is withheld if `mask_private` finds a name in it, if
   `private_doubt` flags it, or if any of the motion's fields is a write-off or travel-waiver item (`WITHHOLD`, F5:
   every field of that motion).
2. **No hidden characters.** After NFKC, a format character (zero-width space, ...), a combining mark, a private-use
   or unassigned character withholds the text.
3. **Spans out.** Roster full names, "<title> <roster name or surname>", AYE/NAY surname lists, dates, `phrases`, and an
   upper-case Roman item number at the very start ("IV.") are replaced by one allowed token.
4. **No spelled-out letters.** Two or more single letters with only spaces or periods, or with any one or two other
   characters that are neither letters nor digits, between ("J. Q.", "J O H N D O E", "Z.Q.", "J/Q", "J-P") withhold
   the text.
4a. **No initial before a name.** A capital lone letter other than A or I, then one to three characters that are not
   letters, digits or an allowed token, then a capitalised word that is not an allowed token ("J. Bonds", "(J. East)",
   "Settlement J. Industrial") withholds the text, whatever `words` holds. A letter next to a digit ("E911", "K-9")
   is not an initial, nor a Roman numeral right after Title, Chapter, Phase or Part.
5. **Every token.** Tokens are runs of letters of any script (`[^\W\d_]+`, so "José" is one token), with a possessive
   "'s" dropped. Each must be: an allowed token (step 3); a word of `words`; a Roman numeral right after Title,
   Chapter, Phase or Part ("Title VI", "Phase III"; "Xi", "Vi" elsewhere fail); when all lowercase, a word of
   `lowercase_only`; or a lone single letter. A capitalised or upper-case word, or a word of a script without case,
   that is none of the first three fails.
6. **Strict positions.** The word after to/for/of/with/by/from and after ":", "–", "—", " - " (a/an/the skipped) must
   be an allowed token or a word of `words`; a `lowercase_only` word only in lowercase after an article; a lone
   letter never ("payment to Z.").
7. Anything else: withheld.

QA restates this from the yml alone and is **stricter**: "," is a strict mark too, and it runs over every string
field (below), not only the rendered spans. It also checks two things a different way from the gate: an initial is
any capital lone letter with a period ("A. Smith" too) or any other than A and I, before a capitalised word that is
not an allowed span, with no Roman exception; and any capitalised word that is a common US surname or given name
(`qa/common-us-names.txt`, about 1,200 from public-domain Census and SSA counts) fails unless an allowed span holds it,
whatever `words` says. A test keeps every word of `words` off that list.

Known residual risk (judgment call, low): a private name made only of ordinary lowercase words and printed in
lowercase, not right after a preposition or a mark ("to pay grant parks" passes; "payment to grant parks" does not).
The minutes print names capitalised. Also a URL (`https://` shape only): the portal's file links carry numeric ids.

Known residual risks of the phrases and the roster (fourth review, L3; judgment call, low; the phrases are kept
because the minutes print them as places and offices):
- **Street and place phrases that are also names**: "Madison Street", "Shelby Street", "Austin Peay" and "Austin Peay
  State University" are allowed whole. A private person named Madison Street or Austin Peay would be shown. Such a
  person would also have to be printed with exactly that spelling in a motion; none is in the data.
- **Office phrases**: "Urban Forester" (and the minutes' "Urban Forrester", "City Forester") name an office. A person
  surnamed Forester after "Urban" would pass.
- **Roster-name collisions**: a roster name or surname is an allowed span in any context, so a private person who
  shares a roster member's name ("Smith", "Allen", "Brown", "Norris", "Little", "Knight") is shown as if it were the
  member, and a claimant surnamed Smith passes as "Smith". The roster is the council and the committees' own members;
  the minutes print claimants rarely, and the belt-and-braces masking (step 1) still withholds claim wording it
  recognises.

## Every text field and what it must do
Every string of committees.json, listing.json and the manifest labels is in one of three classes: a **name** (roster
only), a **fixed value or shape** (enumerated, or an id/date/url/hash pattern), or **words** (the rule above). QA
(`cm_string_problems`) applies this by key to every string it finds, and any key it does not know is words, so a new
field is checked from the day it is added.

| Field | Source | Class and rule |
|---|---|---|
| `motions[].section`, `subject_printed`, `motion_printed` | minutes | words; a withheld field is `null`; `words_withheld` lists it; the pages show the fixed note |
| `motions[].vote.outcome_printed` | minutes | words; when withheld it is `null`, and the page shows the read outcome ("passed") without "(as printed)" |
| `motions[].mover_printed`, `seconder_printed` | minutes | name: a roster name, "<title> <roster name or surname>" or a roster surname; otherwise `null`, and the motion is not confirmed (code `name-not-on-roster`) |
| `motions[].mover`, `seconder` | attendance | name (a member present) |
| `motions[].vote.ayes_printed[]`, `nays_printed[]` | minutes | name, every one; otherwise the list is `null` and the motion is not confirmed |
| `motions[].reasons[]` | reader | fixed: codes only (`collector/committees.py REASON_CODES`, restated in QA `CM_REASON_CODES`); a reason no code matches becomes `other` |
| `motions[].vote.method`, `outcome` | reader | fixed: voice vote / unanimous / roll call / stated; passed / failed |
| `motions[].words_withheld[]`, `words_note` | build | fixed: field names; the one note text |
| `motions[].item` | minutes | shape: one capital letter or 1-3 digits (an item letter or number; QA `CM_SHAPES`) |
| `meetings[].attendance.present[].name`, `absent[].name` | minutes members line | name; if any is not, the whole attendance is `null` with `attendance_withheld: "name-not-on-roster"` |
| `meetings[].attendance.*[].note` | minutes | words; otherwise the note is dropped |
| `meetings[].title`, `documents[].name` | city portal listing | words; otherwise "<committee label> meeting" / the document kind |
| `meetings[].body`, `bodies[].label`, `category_name` | config | words (they pass) |
| `listing.json` rows: `title`, `agenda_name`, `minutes_name`, `body` | city portal | words, gated at fetch (`gate_listing_row`) before listing.json is written: a failing title becomes "<committee label> meeting", a failing name "Agenda"/"Minutes", and the row lists `words_replaced`. `cancelled`, `title_date`, `other_name` are read from the printed title first |
| manifest `label` | fetch, from the gated listing row | words |
| ids, `committee`, `slug`, `locality`, `kind`, `source_id`, dates, urls, hashes, `agenda_id`, `etag` | config, listing, store | shape (QA `CM_SHAPES`); no minutes text |

## Every consumer
| Consumer | Where | Must |
|---|---|---|
| Build | `collector/committees.py build` (`publish` per motion and meeting) | apply the table; the summary counts `words_withheld` per field and `names_withheld` |
| Gate | `collector/committee_words.py` (`publishable`, `roster_name`) | the rule; loads the yml; no other module decides what is published |
| Fetch | `collector/committees.py discover` → `gate_listing_row` | gates listing titles and document names before listing.json and the manifest labels are written |
| Masking | `collector/committee_minutes.py mask_private`, `private_names`, `private_doubt` | belt and braces only: a hit withholds the field |
| Pages | `sitegen/committees.py Committee.motion`, `meeting`; `site/templates/_city_committee.html.j2` | show only the published fields; a withheld field shows the fixed note and the minutes link; mover, seconder and outcome are shown only for a confirmed motion (unchanged); a confirmed voice vote reads "Voice vote (not recorded by name): passed." on every page (Brian, 2026-11-16) |
| Search | `Committee.search_records` | meeting titles only (already gated) |
| Official record / committees page | `sitegen` (committee labels, meeting titles) | gated titles only |
| Export | `collector/export.py` | does not export committees.json (unchanged) |
| QA | `qa/site_checks.py check_committee_motions`, `CmWords`, `cm_string_problems` | re-implements the rule from the yml without importing the collector, stricter ("," strict too; its own initial rule and the common-names deny-list, `qa/common-us-names.txt`). Every string of committees.json, listing.json and the manifest labels by class (above); every `data-item-title` text in a committee motion block and in an attendance block. A motion with withheld words must show the fixed note. The number of blocks must equal the number of motions |
| Tests | `collector/tests/test_committee_words.py`, `tests/test_committee_pages.py` | the reviewers' phrasings (all four rounds), with made-up names, withheld by both the gate and QA; QA passes every string of the committed committees.json, listing.json and manifest; QA rejects a tampered string in any field |
