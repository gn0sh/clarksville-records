# Architecture: clarksville-records, milestone 1

Status: v1, 2026-11-07. Owner: software-architect. Spec: `docs/specs/clarksville-records.md`. Facts: `docs/platform-facts.md`.
Decision record: `docs/adr/0001-static-site-and-data-model.md`. Tasks: `docs/tasks/m1.md`. Facts contract: `schema/facts.schema.json`.

## Context
M1 shows Montgomery County Commission votes, attendance, motions and seconds (2020-2024 minutes) on official, meeting
and item pages, every fact linked to its PDF page, as a private preview for Brian. Constraints: $0, no server, no public
URL (G7), deterministic parsing (no per-page LLM calls), polite collection (AC4.2/4.3), GitHub Actions minutes exhausted
until Dec 1, neutrality rules N1-N6 enforced in code, not by care.

## Components
One Python 3.11+ repo, two packages, one command. No web framework, no database server.

```
collector/            fetch -> store -> parse -> verify -> export   (backend-engineer)
  fetch.py            PoliteFetcher: robots.txt, crawl delay, host allowlist, stop-on-block
  discover.py         finds minutes PDFs on the county index page
  store.py            content-addressed document store + data/manifest.json
  parse/              M0 spike parser (minutes PDF -> raw fragments); owned by the M0 engineer
  names.py            name normaliser + resolver (data/names.yml)
  verify.py           P2 checks, verification status, G4 skew report
  facts.py            assembles data/facts.json (deterministic order, stable ids)
  export.py           CSV + JSON open-data export of shown facts (G5)
  __main__.py         CLI: python -m collector {fetch,parse,verify,build,run}
sitegen/              facts.json -> static HTML                     (frontend-engineer)
  config.py           OPERATOR_NAME placeholder, page constants
  views.py            one view-model builder per page type (same function for every official)
  build.py            renders templates, copies static, writes build/site/
site/                 non-Python assets (not a package: `site` would shadow the stdlib module)
  templates/*.html.j2 base, index, official, meeting, items_year, about, review, changes
  static/style.css, static/filter.js
  fixtures/facts.sample.json   FIXTURE data for frontend work and tests
data/                 committed: names.yml, manifest.json, facts.json, changes.jsonl
                      not committed: data/store/ (PDF bytes; path overridable by RECORDS_STORE)
build/                not committed: site/, report.json, run-log.json, name-candidates.json
schema/facts.schema.json   the parser/verifier -> sitegen contract
schema/changes.schema.json one line of data/changes.jsonl (collector -> sitegen); source_url must be https://
```

### Polite fetcher (`collector/fetch.py`)
- Host allowlist: `montgomerytn.gov`, `mcgtn.org`, `d6.mcgtn.org`, `montgomeryminutes.bisonline.com`
  (later `clarksvilletn.gov`). `cityofclarksville.com` and `dev2.montgomerytn.gov` (403 from the site, 2026-11-07) are
  hard-denied in code, whatever the allowlist says. Discovery reads the production index
  `https://montgomerytn.gov/clerk/county-commission-minutes`; link labels are hints only.
- Redirects are not followed automatically: each `Location` goes back through `get()` (allowlist, denied hosts,
  robots, per-host delay), at most 5 hops, or the fetch fails (politeness/redirect-bypass).
- Per host: fetch and cache `robots.txt` once per run (`urllib.robotparser`; 404 means allow all, per RFC 9309; any other
  error means stop that host). `can_fetch(UA, url)` is checked before every request.
- Delay per host = max(robots Crawl-delay, host floor). Floor: 10 s on every host (M1 build, 2026-11-07; was 5 s
  except `clarksvilletn.gov`). Enforced per host with an injectable clock, so tests run without sleeping.
- User-Agent: the M0 string `clarksville-records research collector (+https://github.com/gn0sh/clarksville-records;
  polite, 10s/host)`, unchanged so the sites see one consistent client. One plain GET, no header tricks.
- HTTP 403 or 429 **from the site** raises `HostBlocked`: the host is skipped for the rest of the run, logged, and
  never retried by another host, header or proxy (AC4.3). A robots disallow raises `RobotsDisallowed` for that URL.
  5xx: one retry after the delay, then logged as failed.
- Sandbox egress proxy refusals are not site blocks: a rejected CONNECT (`Tunnel connection failed: 403`, which the
  site never sees) or a 403 that the local proxy's status page (`$HTTPS_PROXY/__agentproxy/status`) records for that
  host since the request started raises `ProxyRefused`; the host is skipped after 3 in one run. Any 403 that cannot
  be attributed to the proxy is the site's.
- Transport is injected (stdlib `urllib` opener by default; no `requests` dependency) so tests use a fake.

### Document store and manifest (`collector/store.py`)
- Bytes stored at `data/store/<sha256>.pdf`. `data/manifest.json` (committed) has one entry per URL:
  `url, sha256, bytes, content_type, kind ("minutes"|"agenda"), meeting_date, first_fetched_at, etag, last_modified`.
- A document keeps its `first_fetched_at` while its hash is unchanged; that is the "fetch date" shown (N4). A new hash
  for the same URL becomes a new source (the old one stays, so old facts keep their citation) and is logged in
  `data/changes.jsonl`. The replaced entry is marked `superseded_by`; builds read only the latest source per URL, and a
  missing old blob never fails a run (idempotence/superseded-source). "Last checked" times go only to `build/run-log.json`, so a run with nothing new leaves every
  committed file byte-identical (AC4.5).
- The store is a cache: if `data/store/` is empty (a fresh container), `fetch` re-downloads politely. At 10 s per
  request about 60 minutes PDFs take about 10 minutes. Manifest entries also carry `label` (the index link text).
- `data/changes.jsonl` lines follow `schema/changes.schema.json` (date, fact_id `src-<sha12>` of the replaced
  source, field `sha256`, old, new, note, source_url, page null).

### Parser (`collector/parse.py` from M0, wrapped by `collector/minutes.py`)
- Meetings are dated from each "BE IT REMEMBERED ... met in <x> session, on <weekday>, <date>" header, never from the
  link label. One PDF can hold several meetings: headers pair with "Board was adjourned" lines; a nested header
  (an earlier meeting's minutes attached for approval) is its own segment, and its roll calls belong to it. Vote tables
  outside every segment (agenda or resolution pages in a packet) are not parsed as votes. Uncertain bounds hold the
  segment's roll calls. `collector/meetings.py` keeps one copy per date + kind (own minutes > for approval >
  attached, then certain bounds, more tables, more pages, lower hash; never by how many verify) and logs each
  choice in `report.json` `meeting_copies`.
- Consent reprints (2020-2022 layout): every printing of a meeting's consent vote is one roll call. Rule and
  consumers in "Invariant: one vote, one roll call" below.
`parse_minutes(pdf_path, source) -> ParsedMinutes` (in `minutes.py`) holds raw fragments with names as raw strings,
no `official_id` and no fact-level `verification`. Deterministic: same bytes in, same fragments out. Scanned PDFs with
no usable text layer return `text_layer: "none"` and no fragments (AC-P4: "not extracted").
- Two readings (M0): text layer first; every roll call that fails P2 gets a tesseract reading of its pages (300 dpi,
  `--psm 6`), pages OCRed in parallel on all cores (`OMP_THREAD_LIMIT=1` each), cached in `data/ocr/`.
- Combined reading (`parse.combine`, 2026-11-07, key `parse-accuracy/verified-rate`): when no reading passes P2 alone,
  the readings are read cell by cell. A member's vote is a Yes/No/Abstain that some reading read cleanly in that
  member's own cell (one vote token, nothing else), with no reading reading a different vote or an explicit "---"
  there; a member with no clean vote has none when a reading read the cell cleanly blank or "---"; else unreadable.
  The stated tally and the ABSENT names must be read alike. The result passes only through the same P2 checks
  (`check_votes`); `reading_used` then reads "text-layer+tesseract".
- Blank tally count: "Yeses - 21 Noes -  Abstentions - 0" (no number printed) gives the one blank count as roster
  minus absent minus the other two, only from an ABSENT line whose names all resolve; a garbled count or two blanks
  stay unreadable.
- Table cells pair with a header name also through that official's `names.yml` name and aliases when the header name
  resolves exactly (rules 1-2), under the same threshold and margin (header "JoIm Gaimon", table "John Gannon").
- A row's first chunk read as a vote mark just before a name is the district column (tesseract reads "2" as "y)"),
  never a vote of the previous row's last member.
- Motion type: the motion sentence and the outcome clause are kept verbatim (`motions.text`, `roll_calls.outcome_text`,
  e.g. "The foregoing Motion to Defer was Approved by the following roll call vote:"), so a Yes on a motion to table,
  defer or suspend the rules is always shown with that wording, never as a Yes on the resolution. The parser's kind tag
  (`consent`, `resolution`, `amendment`, `suspend-rules`, `procedural`, `nominations`, `minutes`) is heuristic and is
  not shown.
- Consent agenda: the list "... Adopted and Approved as part of the Consent Agenda:" (2023-2024 layout) or a
  "Consent Agenda" line with comma-separated numbers just above the motion (2020-2022 layout) is paired with the next
  consent roll call at that meeting. Each listed item, minus items named as pulled or removed, gets a `roll_call`
  item event whose label is the list's verbatim heading (so it reads as a consent-agenda vote) and whose `ref` is
  that roll call. The roll call's own item is a per-meeting "Consent Agenda" item whose `other` events list what it
  covered. A list whose heading cannot be read is not expanded; such roll calls are listed in `build/report.json`
  (`consent_roll_calls_not_expanded`).
- Item numbers: an OCR split such as "20-3-1 1" is joined only when the joined number is on that meeting's agenda;
  otherwise the line gives no number (never guessed). Inside a comma-separated consent list the commas delimit the
  numbers, so spaces and l/I/| for 1 inside a token are OCR noise ("20-1 0-10" is 20-10-10); a token still unread is
  matched only against the meeting's agenda numbers ("2 l-2-5j" is 21-2-5 when 21-2-5 is on the agenda), never
  guessed (`minutes.list_numbers`, `agenda_numbers_in`). Case numbers take the same glyph rule ("CZ-l1-2022",
  "AB-7-2 023"). Pulled sentences in the inline layout ("Resolution 2 1-2-6 was pulled ...") remove the item.
- Item titles: a motion or outcome sentence is never an item title (`facts.is_sentence`). A numbered item takes the
  agenda's title for its number, else the number alone; an unnumbered one with no other title is "(untitled)" and is
  never title-linked.

### Names and merge rules (`collector/names.py`, `data/names.yml`)
`data/names.yml` is the roster: one entry per official, curated by the team from the county's published commissioner
list, each with `id` (slug), `name`, `surname`, `given`, optional `terms` (start/end, with source URL), and `aliases`
(each alias with the reason and an example source page). Brian never edits it (Goal 3). Merge rules, applied identically
to every official and printed on the About page (AC1.1, G2):
1. Normalise: NFKC, trim, drop leading titles from a fixed list (`Commissioner`, `Comm.`, `Chairman`, `Chairwoman`,
   `Mayor`, `Mr.`, `Mrs.`, `Ms.`, `Dr.`), drop `.` and `,`, collapse spaces, casefold.
2. Exact match of the normalised string against each official's normalised name and aliases.
3. Surname-only match, only when exactly one official on that meeting's roster has that surname. "J. Smith" (one
   initial plus surname) matches only when exactly one official on the roster has that surname and initial. Used
   for Moved/Seconded names only; attendance header names need rule 2.
4. Anything else is unmatched: the fact fails its name check and is held back. No fuzzy auto-merge, ever. The verifier
   writes edit-distance suggestions to `build/name-candidates.json`; a person adds an alias by PR, which is the log.

Display names (M1, recorded in each entry's `name_source`): the county's commissioner list at
https://montgomerytn.gov/commission where the person is on it (it lists the current term only, so it covers 12 of the
2020-2024 commissioners); otherwise the spelling printed in the minutes' attendance header, read by eye from the page
image (`collector/hand_labels.json` rosters). No terms are recorded yet, so `roster_matches_terms` is not checked.
Vote-table cells are paired one-to-one with that meeting's header names by the M0 parser (P2); only header names and
motion names go through rules 1-4.

### Verifier (`collector/verify.py`)
Sets `verification.status` to `verified` or `unverified` with a list of named checks, each `ok` true/false.
- Meeting roster (P2): the meeting's own attendance section (present + absent). Cross-checked against `names.yml` terms
  where terms are known (a mismatch fails `roster_matches_terms`). No attendance section: attendance is
  `not_extracted`, and every roll call at that meeting is unverified (`roster_available` fails).
- Attendance checks: `names_resolve`, `absent_count_matches_stated` (the "ABSENT: ... (2)" count), `roster_matches_terms`.
- Roll call checks: `roster_available`; `names_resolve`; `one_vote_per_present_member` (every present member has
  exactly one vote or explicit non-vote, no absent member has a vote); `tally_matches_stated` (a missing stated tally
  fails, provisional until M0 says how often tallies are stated); `outcome_consistent` (passed means yes > no, failed
  means yes <= no; anything else is held back).
- Motion checks: `mover_resolves`, `seconder_resolves` (null is allowed only when the minutes name none), both present at
  the meeting, mover differs from seconder. A failed motion check holds back the Moved/Seconded attribution only.
- G4 skew: per official, `eligible` = roll calls at meetings whose **verified** attendance lists them, `held` = the
  unverified ones; roll calls anywhere else go into one unattributed count. Exact rule in "Invariant: held-back counts"
  below. Gate fails if any official's held rate > `SKEW_FACTOR` x max(median rate, `SKEW_FLOOR`) with `SKEW_FACTOR = 2.0`,
  `SKEW_FLOOR = 0.02` (both provisional, set after M0). Also gates `verified_rate >= 0.90` (AC-P1). Results go to
  `build/report.json` and the internal review page. The manager publishes only when both gates pass.

### Invariant: held-back counts (problem family `neutrality/held-count`)
Rewritten 2026-11-07 for the CEO's decision (docs/status.md, "Decisions (Brian, 2026-11-07 3:54 PM ET)"): unverified
roll calls are no longer held back on public pages. They are shown, marked "*" with the fixed text "Not confirmed: this
page was hard to read. Read it yourself", linked to the exact source page (`<url>#page=<n>`, as N4). P2 still decides
"confirmed"; G4 is still computed and reported (rule below). The earlier attendance-based placement of held counts is
retired, because no count is held back any more.

**Link only (Brain Trust round 2, `docs/reviews/brain-trust-round2.md`; CEO confirmed 2026-11-07).** Behind one switch,
`sitegen/config.py` `SHOW_UNCONFIRMED_VALUES`, default `False`. A roll call's values (each vote's value, the outcome,
the tally, the bar) are **shown** when it is confirmed or the switch is on (`views.values_shown`). With the switch off
an unconfirmed roll call is still listed in every place below, with the note and link, but every vote and the outcome
read "Not confirmed*", there is no bar and no tally, an official page gives a count of unconfirmed roll calls
("N roll calls not confirmed*, see each page") and no Yes/No breakdown, and the public export has `value: null` on its
votes and `outcome: null`, `stated_tally: null` on the roll call. review.html and `--internal` exports show everything.
With the switch on, unconfirmed values are shown starred, as the rest of this section describes.

Definitions, for one facts file: a roll call is **confirmed** when its `verification.status` is `verified`, and
**unconfirmed** otherwise. A vote is **resolved** when its `official_id` names an official in the facts file. Unresolved
votes are never placed under a person: no name, alias or merge rule is consulted by any consumer below.

Invariant (each line is a test in `tests/test_held_counts.py`, which runs with the switch on; the switch-off
behaviour is `tests/test_unconfirmed_values.py`, both settings):
1. Confirmed only from confirmed: an official's confirmed counts (Yes, No, Abstain, Other) come only from their resolved
   votes in confirmed roll calls. Changing, adding or removing any unconfirmed roll call changes no confirmed count.
2. Unconfirmed only from their own resolved id: an official's unconfirmed counts (switch off: the one count of
   unconfirmed roll calls) come only from unconfirmed roll calls in which their resolved `official_id` has a vote. No name matching: rewriting every raw name and alias changes no count.
3. Same meeting, same treatment: whether a roll call is shown, and how it is marked, depends only on the roll call, never
   on the official. Every official with a resolved vote in a roll call gets that vote on their page, with the same mark.
4. Exactly once: every vote is counted once, either under its resolved official (confirmed or unconfirmed part) or in
   the site-wide unmatched count V, which reads word for word the same on every official's page. V votes appear only on
   the meeting and item views, as "Name not matched*" with the source link, never on an official's page.
5. No raw text: an unconfirmed roll call shows (switch on) Passed/Failed/Other, a tally counted from its votes and vote
   labels from the fixed mapping, or (switch off) only "Not confirmed*"; never `outcome_text`, raw names or unlisted raw vote wording (`tests/test_site_raw_leaks.py`).
6. Motions: an unverified motion never names anyone: every page shows its type label and "Attribution under review",
   whatever its roll call's status (manager decision 2026-11-07, review of a991a10). A verified motion shows its
   resolved names, unstarred. No "*" ever follows a name or a Moved/Seconded line, and a confirmed roll call's block or
   row carries no "*" and no note.

Consumers (every one must follow the definitions above; none may place a person by name):
| Consumer | Where | What it shows |
|---|---|---|
| Official page totals | `sitegen/views.py` `vote_counts`, `totals_sentences`; `official.html.j2` | "Roll call votes: a Yes, b No, c Abstain, d Other confirmed; N roll calls not confirmed*, see each page." (switch on: "e Yes*, ... not confirmed") and the site-wide V sentence; the unconfirmed Yes/No legend only with the switch on |
| Official page history rows | `views.official`; `official.html.j2` | one row per resolved vote; unconfirmed rows "Not confirmed*" (switch on: "Yes*") with the source link; Moved/Seconded rows only for verified motions |
| Meeting page | `views.meeting`, `_roll_call_block`, `_vote_rows`; `meeting.html.j2`, `_macros.html.j2` | every roll call in document order; unconfirmed ones marked, every vote and the outcome "Not confirmed*" and no bar (switch on: values starred), unresolved votes "Name not matched*" |
| Item pages | `views._event`; `items_year.html.j2` | the same roll call block; no raw event label for motion or roll call events |
| Outcome and tally | `Index.outcome` | label and tally counted from that roll call's own votes, starred when unconfirmed; `hidden`, label "Not confirmed", no tally or counts when `values_shown` is false |
| Internal review page | `views.review`, `review.html.j2` | every unverified fact with failed checks; G4 results from `report.json` |
| QA site checks | `qa/site_checks.py` `attribution_shown`, `check_unverified` | rule 6 restated independently; the note inside each unconfirmed row or block, no "*" in a confirmed one; switch off: no vote word, outcome or tally (`PARSED_VALUE`) in an unconfirmed row or block, and no value in the public `data/facts.json`; outcome-text scan with only item titles and non-motion/roll call event labels as benign |
| G4 gate | `collector/verify.py` -> `build/report.json` | eligible, held and rate per official by verified attendance (rule below); unchanged |
| Export | `collector/export.py` -> `build/site/data/` | every roll call and vote with `confirmed`; motions with `confirmed` and attribution only as rule 6; switch off: an unconfirmed roll call's vote `value`, `outcome` and `stated_tally` are null; `verification` as status plus check names and ok flags (no `detail`); no raw fields |
| About page | `about.html.j2` "Verified and not confirmed facts" | the rule in words (exact text tested) |
| Tests | `tests/test_held_counts.py`, `test_site_raw_leaks.py`, `test_site_links.py`, `test_site_neutrality.py`, `test_qa_tools.py`, `test_unconfirmed_values.py`, `test_visual_refresh.py`, `collector/tests/test_run.py`, `collector/tests/test_verify.py` | the lines above |

**Rule for the collector's G4 code** (`collector/verify.py`; G4 is a quality gate on the report, not a site count):
- For each meeting compute `shown(m)` and `listed(m)` exactly as defined above. Use only the resolved `official_id`
  on the verified attendance entries; never call the name normaliser, aliases or merge rules for G4.
- Per official `o`: `eligible(o)` = roll calls (verified or not) at meetings with `shown(m)` and `o in listed(m)`;
  `held(o)` = the unverified ones among them; `rate(o) = held(o) / eligible(o)`. An official with `eligible(o) == 0`
  has no rate and is left out of the median and the gate.
- Every roll call at a meeting with `not shown(m)` or empty `listed(m)` goes to `eligible_unattributed`, and the
  unverified ones to `held_unattributed`. They are added to no official.
- Holds the spec's G4 excludes as source-document errors are excluded per roll call (from every official listed
  there alike), and only from the rates; they still count in `held(o)` and `held_unattributed` as shown on the site.
- Write to `build/report.json`: `g4.per_official = {id: {eligible, held, rate}}`, `g4.held_unattributed`,
  `g4.eligible_unattributed`, `g4.held_total`. Before writing, assert
  `held_total == held_unattributed + (held roll calls at meetings with attributed holds, each counted once)` and
  `held_total == number of unverified roll calls`; a failed assertion is a bug (raise), not a gate result.
- `g4.held_total` must equal the number of roll calls the site shows as not confirmed (a cross-module test). A large
  `held_unattributed` means G4 cannot see skew there; the `verified_rate >= 0.90` gate (AC-P1) bounds it.

### Invariant: one vote, one roll call (problem family `item-history`)
Stated after the family's second hit (2026-11-07, review of e80ec75). The 2020-2022 minutes reprint the consent vote
after every consent resolution (up to 18 printings per meeting). Grouping printings by an exact item-number set
failed because OCR garbles numbers in some printings ("20-1 0-10", "22l-6"), so 2020-10-12 published 6 identical
verified consent roll calls and items got the same vote 2 to 9 times.

Invariant (each line is checked by `collector/invariants.py` `one_vote_violations` on every facts file the tests
build and on the committed `data/facts.json`; `python -m collector.invariants` prints it for a run):
1. One vote, one roll call: each vote taken at a meeting appears as exactly one `roll_calls` entry. All printings of
   one vote are one roll call; the others are recorded only in `report.json` `consent_reprints` (printing id -> roll
   call id).
2. One row per official: an official has at most one vote row in a roll call (two table entries that resolve to one
   official fail `one_entry_per_official` and hold the roll call).
3. One event per (item, roll call): each item gets at most one `roll_call` item event per roll call, however many
   times the vote is printed or listed. The event kept is the printing nearest the item (the table itself, or the
   reprint right after the item's own resolution), else its first consent-list entry.
4. Disagreement holds, never splits: printings of one vote that read differently on any member's Yes/No/Abstain or on
   the stated tally fail `reprints_agree` and hold the one roll call. They never become two votes.

Rule that decides "printings of one vote" (`collector/facts.py` `consent_groups`, written, the same for every
meeting): within one meeting's minutes, consent-agenda tables are printings of one consent vote unless their motions
name different movers or seconders, as resolved against that meeting's own roster. Item lists, tallies and raw name
spellings are not part of the key (OCR garbles all three). A printing whose motion is unread joins the one vote it is
compatible with; if it fits two or more, it stays its own roll call and is held (`consent_printing_placed`). Tables
inside an earlier meeting's attached minutes are never grouped with this meeting's. The first printing that verifies
(else the first) is the roll call. The vote covers the union of the item numbers on every printing's list, minus any
number a printing names as pulled; unnumbered entries come from the first printing's list only.

Consumers (each counts or shows roll calls and item events, so each relies on the invariant; none may re-derive
votes from printings):
| Consumer | Where | Relies on |
|---|---|---|
| Facts assembly | `collector/facts.py` `Builder.add` | writes one roll call per vote, one event per (item, roll call) |
| Verifier and AC-P1 rate | `collector/verify.py` `gates` (`roll_calls`, `verified`, `verified_rate`) | each vote counted once in numerator and denominator |
| G4 eligible and held counts | `verify.gates` per official, `held_unattributed` | a reprint never adds an eligible or held roll call |
| Run report | `collector/__main__.py` `documents[].meetings_found[].roll_calls` (votes) vs `vote_tables` (tables), `consent_reprints`, `consent_roll_calls_not_expanded` | documents count votes, not printings |
| Official pages | `sitegen/views.py` vote rows, totals sentences, held counts | one row per vote per official |
| Item pages | `views` item history, `items_year.html.j2` | one roll-call event per vote per item |
| Meeting pages | `views.meeting` roll call list and held sentence | each vote listed once |
| CSV export | `collector/export.py` `roll_calls`, `votes`, `item_events` CSVs | one row per vote, one vote row per official |
| QA spot check sampling | `qa/spot_check.py` `candidates` | a vote is sampled once, not once per printing |
| Hand-label comparison | `collector/compare_labels.py` | a labelled reprint page resolves to its roll call through the kept reprint event |

### Run report (`build/report.json`, written by `python -m collector run`)
```
{generated_for {coverage, sources},
 pass,                                   # verified_rate_gate.pass and g4.pass ("review needed" does not block)
 gates {roll_calls, verified, held_back, held_back_source_error, verified_rate,
        verified_rate_gate {min, pass},
        g4 {rule, skew_factor, skew_floor, min_roll_calls, flagged[], pass, status "pass"|"review needed"|"fail",
            review_needed, uniform_share, uniform_share_review_above (0.25),
            meetings_attendance_not_shown [{meeting_id, attendance not_extracted|under_review|lists_no_official,
                                            held_roll_calls[]}],
            per_official {id: {eligible, held, held_source_error, rate|null, peer_median|null}},
            held_total, held_unattributed, eligible_unattributed}},
 held_back_roll_calls [{id, meeting_id, page, source_error, failed[check names]}],
 meetings_attendance_unverified [], consent_roll_calls_not_expanded [], motions_held_back,
 documents [{source_id, label, meeting_id, pages, roll_calls, verified, attendance, image_only_pages}],
 problems []}
```
`build/run-log.json`: started_at, finished_at, offline, found, new[], fetched {status: n}, failures[], parsed,
held_back, facts_changed, fetch_log[]. `build/name-candidates.json`: unmatched raw names with counts, examples and
edit-distance suggestions (never applied), and every merge in `names.yml`.

Source-document errors (G4): a hold is caused by the source itself when at least two independent readings agree on
every vote and on the tally and each reports the same member with a vote mark who is on that roll call's ABSENT line.

### Facts assembly (`collector/facts.py`)
Writes `data/facts.json` (committed, all facts including unverified, so git history is the change history). Lists are
sorted by id; JSON is written with sorted keys and 2-space indent, so a re-run with no new data produces no diff.
IDs are derived from content position, not run order (see the schema), so a parser fix moves few ids.

### Static site generator (`sitegen/`)
`python -m sitegen --facts <facts.json> --out build/site [--internal]` renders Jinja2 templates to plain HTML files with
relative links. Works from a file system, a zip, any static host, or a private claude.ai page.
Pages (count estimate for 2020-2024 in brackets; the whole site must stay under 250 files):
| File | Content |
|---|---|
| `index.html` | Landing (docs/design/landing-search-nav.md 3): purpose line, search box, inline SVG district map from `config/localities/<locality>/districts.json` (a list and a "map is not available yet" note when absent), district list with each seat's current holder. [1] |
| `officials.html` | Officials (design 6A.3). With `config/seats.yml`: Current by seat (districts by number, then the configured other seats), Served previously and Seat not yet recorded alphabetical by surname; one card template, a seat label after every name. Without the roster: one alphabetical list, no labels. No sorting by count. [1] |
| `meetings.html` | Meetings timeline, newest first (moved from the old home page). [1] |
| `districts/<nn>.html` | Seat page per county commission district (design 4): Current, Served previously, then holder records split into current and old district lines, each with its own totals sentence and vote rows. [21] |
| `votes/<yyyy>.html` | Every roll call by year, newest first; unconfirmed ones "Not confirmed*" with the page link. [~7] |
| `search.html` + `static/search-index.js` | Search with filters in the URL (manager decision Q3: one first-party index written as a script, so it also works from files; no Pagefind for now). Unconfirmed roll calls carry no outcome or votes in the index. [1 + 1] |
| `finance.html`, `capital-projects.html`, `data.html` | "Coming" pages with no numbers; the export file list. [3] |
| `officials/<id>.html` | One date-ordered history: votes, attendance, Moved, Seconded; type and year filters. [~40] |
| `meetings/<meeting_id>.html` | Attendance table, then every motion and roll call in document order (unconfirmed marked *). [~60-120] |
| `items/<yyyy>.html#<item_id>` | One section per item: every appearance in date order. Bucketed by year so the file count stays small. [5] |
| `about.html` | Operator, data rules, merge rules (rendered from names.yml), neutrality rules, how to report errors, exports. [1] |
| `changes.html` | Public change history from `data/changes.jsonl`. [1] |
| `review.html` | Internal only (`--internal`): unverified facts with failed checks, gate results. Never in a public build. [1] |
| `data/*.csv`, `data/facts.json` | Open-data export (G5) of shown facts plus sources. [~10] |

Neutrality enforced by construction:
- **N1/AC1.5:** one `official.html.j2` and one `views.official(official_id, facts)` for everyone; templates get no
  official-specific flags. Every section renders for every official, with a fixed empty-state sentence. Test renders two
  officials, reduces each to its tag/heading/column skeleton, and asserts equality.
- **N2:** vote labels come from one mapping: `yes` Yes, `no` No, `abstain` Abstain, `other` "Other: <raw wording>".
  Attendance is Present or Absent. No other derived labels exist.
- **N3/P4/AC2.3:** totals are fixed sentences filled from one function, e.g. "Recorded absent at 4 of 61 meetings with
  an extracted attendance section, 2020-01-06 to 2024-12-09." Denominator = meetings whose extracted attendance lists
  the official. Also "Roll call votes, 2020-01-06 to 2024-12-09: 12 Yes, 3 No, 0 Abstain, 0 Other confirmed; 2 Yes*,
  0 No*, 0 Abstain*, 0 Other* not confirmed." (confirmed and unconfirmed never added together, per "Invariant: held-back
  counts"), the site-wide "V votes in this period have a name that could not be matched to an official and are not
  counted for any member.", "N meetings in this period have no extracted attendance section and are not counted." and
  "N meetings in this period have an attendance section that is under review and are not counted." No percentages, no
  sort by count, no highlight.
- **Ordering:** people always alphabetical by surname; history rows by date (newest first), ties by source page then
  position. A lint test fails on `sort(attribute=` with any count field and on banned words in templates
  (`rank`, `score`, `grade`, `missed`, `percent`, `%`, `best`, `worst`).
- **N4:** every fact row has a source link `<url>#page=<n>` (opens in a new tab), "p. n", and "fetched <date>".
- **N5:** every fact row shows its fact id and a "Report an error" link to `about.html#corrections`. In the preview,
  the About page tells Brian to comment on the page quoting the fact id; the public intake form is M1.5.
- **N6** (amended 2026-11-08, manager decision Q6): no third-party scripts, fonts, analytics or campaign links. First-party
  scripts from `static/` only (`filter.js`, `nav.js`, `map.js`, `search.js`, and the generated `search-index.js`),
  vanilla, making no network requests and storing nothing about the visitor. Every page works without them.
- **G1:** `base.html.j2` footer on every page: "Provided as a free service by {{ operator }}." (CEO, 2026-11-07), then
  "About this site and its data rules." and the full nav list. The operator and all locality and branding text live in
  `config/site.yml`. The optional support link (`support_url`, `support_label`) renders only when `support_enabled` is
  true; it stays false until the pre-public ethics check (G6).
  `OPERATOR_NAME` defaults to `"[OPERATOR NAME - CEO to confirm]"`; the build prints a warning while it is the
  placeholder, and a public build (`--public`, M1.5) refuses to run with it.
- CSS: colour tokens on `:root` with a `prefers-color-scheme: dark` variant, explicit `body` background, readable at
  phone width (16 px gutter, tables scroll inside their own box, never the page).

### Export (`collector/export.py`, G5)
Writes into `build/site/data/`: `facts.json` (every roll call and vote with a `confirmed` boolean, motions with
`confirmed`, verified attendance only, plus sources),
`officials.csv`, `meetings.csv`, `attendance.csv`, `roll_calls.csv`, `votes.csv`, `motions.csv`, `items.csv`,
`item_events.csv`, `sources.csv`. Every row carries `source_url, source_sha256, page, fetched_at`. Unconfirmed roll
calls are exported with `confirmed: false` and, while `SHOW_UNCONFIRMED_VALUES` is off, with no parsed value
(vote `value`, `outcome`, `stated_tally` null); an unresolved vote has `official_id: null` and no name, so no value is ever
placed under a guessed person (P3). Raw OCR fields (`raw_name`, `raw_value`, `outcome_text`, motion `text`, motion and
roll call event labels, and each verification check's `detail`) are in internal builds only; the public `verification`
is `{status, checks: [{check, ok}]}`.

## Data model
Full field list and enums: `schema/facts.schema.json`. Summary:
- **sources**: `id` (`src-<sha256[:12]>`), `url`, `sha256`, `kind`, `meeting_date`, `fetched_at`, `pages`, `text_layer`.
- **officials**: `id` (slug), `name` (as on the county list), `surname`, `given`, `title`, `aliases[]`. No party, no
  photo, no district unless the county list states it.
- **meetings**: `id` (`<date>-<kind>`), `body`, `date`, `kind` (`formal`, `informal`, `special`), `source_id`,
  `attendance_status` (`extracted` | `not_extracted`), `attendance[]` {`official_id`, `raw_name`, `status`
  (`present`|`absent`), `page`}, `stated_absent_count`, `verification`.
- **items**: `id` (normalised official number, e.g. `24-12-1`, `AB-4-2024`; or `t-<sha1(normalised title)[:10]>`),
  `number` (or null), `title` (verbatim, from first appearance), `link_basis` (`number` | `title`), `year`.
- **item_events**: every appearance of an item: `id`, `item_id`, `meeting_id`, `date`, `type` (`listed`,
  `referral`, `reading`, `amendment`, `motion`, `roll_call`, `postponed`, `withdrawn`, `other`), `label` (verbatim),
  `ref` (motion or roll call id, when the type is one), `source_id`, `page`, `order`.
- **motions**: `id`, `meeting_id`, `item_id`, `text` (verbatim), `moved_by` / `seconded_by` {`official_id`,
  `raw_name`} or null, `source_id`, `page`, `verification`.
- **roll_calls**: `id`, `meeting_id`, `item_id`, `motion_id`, `votes[]` {`official_id`, `raw_name`, `value`
  (`yes`|`no`|`abstain`|`other`), `raw_value`}, `stated_tally` {yes,no,abstain} or null, `outcome`
  (`passed`|`failed`|`other`), `outcome_text` (verbatim), `source_id`, `page`, `verification`.
- **verification** (on meetings' attendance, motions, roll calls): `status` (`verified`|`unverified`),
  `checks[]` {`check`, `ok`, `detail`}.
- **corrections** (reserved, empty in M1): `fact_id`, `on`, `field`, `old`, `new`, `source_id`, `page`.

Fact ids for corrections: vote `<roll_call_id>/<official_id>`, attendance `<meeting_id>/att/<official_id>`,
Moved/Seconded `<motion_id>/moved` and `<motion_id>/seconded`.

## Item history (US7)
1. The parser emits each appearance of an item with its raw number and title.
2. `normalise_number(raw)`: uppercase, unify dashes (en/em dash, spaced hyphen) to `-`, strip spaces, then match the known
   patterns `^\d{2}-\d{1,2}-\d{1,3}$` (resolution, e.g. 24-12-1) and `^[A-Z]{1,4}-\d{1,3}-\d{4}$` (e.g. AB-4-2024). M0
   adds patterns it finds. A raw number matching no pattern is treated as no number (never guessed).
3. Numbered items: all appearances with the same normalised number share one item (`link_basis: number`).
4. Unnumbered items: title normalised by casefold, collapsed whitespace and trailing punctuation removed, nothing else.
   Appearances link only when normalised titles are identical (`link_basis: title`, shown as "linked by title"). Any
   other difference makes a separate item (AC7.3). Recurring procedural titles listed in `data/procedural-titles.yml`
   (e.g. approval of the minutes, invocation, pledge) are never title-linked: each appearance is its own item, otherwise
   one "item" would collect every meeting's minutes approval.
5. Item page = `item_events` for the item sorted by (date, source page, order); `roll_call` events expand to the full
   member vote table (alphabetical) and outcome; unverified roll calls show "1 roll call is under review and not shown".
6. Every vote and Moved/Seconded row on an official's page links to `items/<year>.html#<item_id>` (AC7.4). The year is
   the item's first appearance year, so an item spanning Dec 2023 and Jan 2024 lives in one place.
Agenda listings (`listed` events from agenda PDFs) join the same way once agendas are ingested (M1.5, with search).

## Key flows
- **Run** (`python -m collector run [--offline] [--internal]`): discover -> fetch new (manifest, polite) -> parse new or
  changed documents -> resolve names -> verify -> write `data/facts.json` -> export -> `sitegen` -> `build/report.json`
  and `build/run-log.json` (found, new, failed, parsed, held back; AC4.4). Exit 0 ok, 2 on fetch/parse failures,
  3 on a gate failure. `--offline` skips discover/fetch and uses the store.
- **Preview publish** (manager, in session): run, check `build/report.json` gates, publish `build/site/` as one private
  multi-file claude.ai artifact to the same URL each time (ADR 0001). `sitegen` writes `build/publish-files.json`
  (published path -> local path) for the Artifact `files` map.
- **Schedule** (US4, later): the same `run` command. Now: in session. Next: a scheduled Claude Code session (remote
  trigger) that runs it and republishes, which is the only runner that can update a claude.ai artifact. After Dec 1:
  a GitHub Actions workflow can run it to refresh `data/` and open an issue on failure, but cannot publish the preview.
  Failures open an internal GitHub issue in this private repo (`gh issue create`), never a silent gap.

## Non-functional
- Size: about 60-120 meetings, ~40 officials, ~1,500 items, ~25,000 votes. facts.json a few MB; built site well under
  the artifact limits (16 MB per file, 255 files per publish).
- Security: no secrets, no user input in M1 (no form), no server. Source PDFs are untrusted input: parse with a pure
  Python library, never execute embedded content, cap file size (50 MB) and pages (500).
- Observability: run log and report per run; gate failures and fetch blocks visible on the review page.

## Risks
1. **Preview channel unproven**: relative links between pages of a multi-file claude.ai artifact and `#page=` links to
   the county PDFs opened from inside it are expected to work but are untested. First publish verifies with 3 pages; the
   fallback is the zip of `build/site/` in `/mnt/project-files/clarksville-records/preview/`.
2. **Tally not stated / supermajority rules**: strict checks may hold back many correct roll calls; M0 numbers decide.
3. **Item numbering in OCR**: `0`/`O` and `1`/`l` errors split one item into two. Never auto-fixed; only exact
   normalised matches link, so the failure is a split history, not a wrong link.
4. **Index on a dev host** (A4): discovery fails loudly if the page moves; no guessing of alternate hosts.
5. **Per-year item files** grow to ~1 MB each; fine for the preview, revisit for public hosting (one file per item).
