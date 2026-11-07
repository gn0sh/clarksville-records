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
```

### Polite fetcher (`collector/fetch.py`)
- Host allowlist: `montgomerytn.gov`, `mcgtn.org`, `d6.mcgtn.org`, `dev2.montgomerytn.gov`, `montgomeryminutes.bisonline.com`
  (later `clarksvilletn.gov`). `cityofclarksville.com` is hard-denied in code, whatever the allowlist says.
- Per host: fetch and cache `robots.txt` once per run (`urllib.robotparser`; 404 means allow all, per RFC 9309; any other
  error means stop that host). `can_fetch(UA, url)` is checked before every request.
- Delay per host = max(robots Crawl-delay, host floor). Floors: `clarksvilletn.gov` 10 s, every other host 5 s.
  Enforced by one `HostClock` per host with an injectable clock, so tests run without sleeping.
- User-Agent: `clarksville-records/0.1 (private research preview)`. One plain GET, no header tricks.
- HTTP 403, 429 or a robots disallow raise `HostBlocked`: the host is skipped for the rest of the run, logged, and
  never retried by another host, header or proxy (AC4.3). 5xx: one retry after the delay, then logged as failed.
- Transport is injected (`requests.Session` by default) so tests use a fake.

### Document store and manifest (`collector/store.py`)
- Bytes stored at `data/store/<sha256>.pdf`. `data/manifest.json` (committed) has one entry per URL:
  `url, sha256, bytes, content_type, kind ("minutes"|"agenda"), meeting_date, first_fetched_at, etag, last_modified`.
- A document keeps its `first_fetched_at` while its hash is unchanged; that is the "fetch date" shown (N4). A new hash
  for the same URL becomes a new source (the old one stays, so old facts keep their citation) and is logged in
  `data/changes.jsonl`. "Last checked" times go only to `build/run-log.json`, so a run with nothing new leaves every
  committed file byte-identical (AC4.5).
- The store is a cache: if `data/store/` is empty (a fresh container), `fetch` re-downloads politely. At 5 s per
  request about 60 minutes PDFs take about 5 minutes.

### Parser (`collector/parse/`, from M0)
Contract only; the M0 spike owns the code. `parse_minutes(pdf_path, source) -> ParsedMinutes`, where `ParsedMinutes`
holds raw fragments in the shapes of `schema/facts.schema.json` but with names as raw strings (`raw_name`), no
`official_id` and no `verification`. Deterministic: same bytes in, same fragments out. Scanned PDFs with no usable text
layer return `text_layer: "none"` and no fragments (AC-P4: "not extracted").

### Names and merge rules (`collector/names.py`, `data/names.yml`)
`data/names.yml` is the roster: one entry per official, curated by the team from the county's published commissioner
list, each with `id` (slug), `name`, `surname`, `given`, optional `terms` (start/end, with source URL), and `aliases`
(each alias with the reason and an example source page). Brian never edits it (Goal 3). Merge rules, applied identically
to every official and printed on the About page (AC1.1, G2):
1. Normalise: NFKC, trim, drop leading titles from a fixed list (`Commissioner`, `Comm.`, `Chairman`, `Chairwoman`,
   `Mayor`, `Mr.`, `Mrs.`, `Ms.`, `Dr.`), drop `.` and `,`, collapse spaces, casefold.
2. Exact match of the normalised string against each official's normalised name and aliases.
3. Surname-only match, only when exactly one official on that meeting's roster has that surname.
4. Anything else is unmatched: the fact fails its name check and is held back. No fuzzy auto-merge, ever. The verifier
   writes edit-distance suggestions to `build/name-candidates.json`; a person adds an alias by PR, which is the log.

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
- G4 skew: per official, `eligible` = roll calls at meetings whose attendance lists them, `held` = the unverified ones.
  Gate fails if any official's held rate > `SKEW_FACTOR` x max(median rate, `SKEW_FLOOR`) with `SKEW_FACTOR = 2.0`,
  `SKEW_FLOOR = 0.02` (both provisional, set after M0). Also gates `verified_rate >= 0.90` (AC-P1). Results go to
  `build/report.json` and the internal review page. The manager publishes only when both gates pass.

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
| `index.html` | Officials index, alphabetical by surname then given name. Names only: no counts, no badges. [1] |
| `officials/<id>.html` | One date-ordered history: votes, attendance, Moved, Seconded; type and year filters. [~40] |
| `meetings/<meeting_id>.html` | Attendance table, then every motion and verified roll call in document order. [~60-120] |
| `items/<yyyy>.html#<item_id>` | One section per item: every appearance in date order. Bucketed by year so the file count stays small. [5] |
| `about.html` | Operator, data rules, merge rules (rendered from names.yml), neutrality rules, how to report errors, exports. [1] |
| `changes.html` | Public change history from `data/changes.jsonl`. [1] |
| `review.html` | Internal only (`--internal`): held-back facts with failed checks, gate results. Never in a public build. [1] |
| `data/*.csv`, `data/facts.json` | Open-data export (G5) of shown facts plus sources. [~10] |

Neutrality enforced by construction:
- **N1/AC1.5:** one `official.html.j2` and one `views.official(official_id, facts)` for everyone; templates get no
  official-specific flags. Every section renders for every official, with a fixed empty-state sentence. Test renders two
  officials, reduces each to its tag/heading/column skeleton, and asserts equality.
- **N2:** vote labels come from one mapping: `yes` Yes, `no` No, `abstain` Abstain, `other` "Other: <raw wording>".
  Attendance is Present or Absent. No other derived labels exist.
- **N3/P4/AC2.3:** totals are fixed sentences filled from one function, e.g. "Recorded absent at 4 of 61 meetings with
  an extracted attendance section, 2020-01-06 to 2024-12-09." Denominator = meetings whose extracted attendance lists
  the official. Also "N roll calls in this period are not shown because they are under review." and "N meetings in this
  period have no extracted attendance section and are not counted." No percentages, no sort by count, no highlight.
- **Ordering:** people always alphabetical by surname; history rows by date (newest first), ties by source page then
  position. A lint test fails on `sort(attribute=` with any count field and on banned words in templates
  (`rank`, `score`, `grade`, `missed`, `percent`, `%`, `best`, `worst`).
- **N4:** every fact row has a source link `<url>#page=<n>` (opens in a new tab), "p. n", and "fetched <date>".
- **N5:** every fact row shows its fact id and a "Report an error" link to `about.html#corrections`. In the preview,
  the About page tells Brian to comment on the page quoting the fact id; the public intake form is M1.5.
- **N6:** no third-party scripts, fonts, analytics or campaign links. Only `static/filter.js` (vanilla, ~50 lines).
- **G1:** `base.html.j2` footer on every page: "Run by {{ OPERATOR_NAME }}. About this site and its data rules."
  `OPERATOR_NAME` defaults to `"[OPERATOR NAME - CEO to confirm]"`; the build prints a warning while it is the
  placeholder, and a public build (`--public`, M1.5) refuses to run with it.
- CSS: colour tokens on `:root` with a `prefers-color-scheme: dark` variant, explicit `body` background, readable at
  phone width (16 px gutter, tables scroll inside their own box, never the page).

### Export (`collector/export.py`, G5)
Writes into `build/site/data/`: `facts.json` (verified facts only, plus sources and held-back counts),
`officials.csv`, `meetings.csv`, `attendance.csv`, `roll_calls.csv`, `votes.csv`, `motions.csv`, `items.csv`,
`item_events.csv`, `sources.csv`. Every row carries `source_url, source_sha256, page, fetched_at`. Unverified facts are
never exported: a guessed value under a named person is the harm P3 prevents.

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
