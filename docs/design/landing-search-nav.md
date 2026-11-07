# Landing map, seat pages, search and navigation: design spec

Feature slug: `landing-search-nav`. Designer: ux-designer, 2026-11-07. Status: draft for architect and frontend.
Builds on `docs/design/visual-refresh.md` (palette, type, chrome, components: keep its look). Neutrality rules
N1-N6 (`docs/specs/clarksville-records.md`) and "Invariant: held-back counts"
(`docs/architecture/clarksville-records.md`) stay in force on every screen below.

Trigger (owner, verbatim, abridged): "the landing screen should be no more than a single page.. maybe based on a map
of clarksville and MoCo, with city wards and county commission districts labeled. someone could click on their ward
or district to see that area's rep voted, whoever it may have been. we definitely need a customizable search too..
people are going to want to search for rezoning applicants ... make room for financial data and capital projects
... a way to visualize user-selected finance data over time ... any user can access any data in any format."
Added (owner, via coordinator): "i really like the 'click on the icon in the top left and open a panel of options'
motif." And: "you have a lot of commissioners that are no longer serving ... when the name assigned to a seat changes,
a new record starts and the previous name move into a section for those who served previously." Clarified: the method
is ours; required are (1) a clear current / former distinction and (2) a seat label ("District N", "Ward N",
"Mayor") wherever an official's name appears, with former members showing the seat(s) they held and the dates.
Map data facts: `docs/research/district-ward-map-data.md` (commit fe33350).

Constraints: static files only, no server, no third-party requests (N6), works at 375 px and on desktop, WCAG 2.2 AA.
The map is never the only way in: a full list of districts and wards is always present.

## 0. Summary of decisions

| # | Decision |
|---|---|
| D1 | `index.html` becomes the landing: purpose line, search box, map with a layer switch, list of districts. Nothing else. |
| D2 | Officials cards move to `officials.html`; the meetings timeline to `meetings.html`; the at-a-glance band and its note to `about.html#the-record`. |
| D3 | Map is an inline SVG drawn at build time from boundary files. Every district has the same fill. No basemap tiles, no map library. |
| D4 | Keyboard and screen readers use the district list, not the SVG. The SVG is `aria-hidden` and its links take `tabindex="-1"`, so nothing is announced twice. |
| D5 | One page per seat: `districts/<nn>.html` (21) and later `wards/<nn>.html` (12). Seat history comes from the minutes' own vote tables, which print the district number next to each name (`collector/parse.py` already splits "4 Rickey Ray"). |
| D6 | 2022 redistricting: one page per seat number, split into "line periods" with a fixed notice that the area changed. Never one combined total across periods. |
| D7 | Search page `search.html` with filters in the URL, so a search is shareable and bookmarkable (that is what "customizable" means here: no accounts). |
| D8 | Vote and outcome filters cover confirmed roll calls only, with a fixed sentence saying how many not-confirmed ones are left out and a link to see them. |
| D9 | Main nav is a top-left menu button opening a side drawer on every screen size, built on native `<dialog>`; without JS the button is a link to a full nav list in the footer. |
| D10 | Finance and Capital projects have nav places now, with empty "coming" pages. No numbers, no sample chart. |
| D11 | Each seat has a sequence of **holder records** (person, start, end, source) from a roster config file, cross-checked against the district numbers in the roll-call tables. A new holder starts a new record; the previous one moves to "Served previously". |
| D12 | A **seat label** ("District 7", "Ward 3", "County Mayor", "City Mayor", or the seat name the source uses for any at-large or other seat) appears next to every official's name in every list and on their page; former members show each seat held with dates. |
| D13 | The Officials page and every seat page split people into **Current** and **Served previously**, by one mechanical rule (6A.1). |
| D14 | The period before 2022-09-01 is labelled "Old district lines" everywhere, with a link to the old map PDF. |

## 1. Information architecture

```
index.html            Landing: map + search + district list            (new content, same filename)
search.html           Search with filters                               (new)
votes/<yyyy>.html     Every roll call by date, year-bucketed            (new, ~5 files, works without JS)
meetings.html         Meetings timeline (moved from index)              (new file, existing component)
officials.html        Officials: Current, then Served previously (6A)   (new file, existing card component)
officials/<id>.html   unchanged
districts/<nn>.html   Seat page, county commission district 01-21       (new, 21 files)
wards/<nn>.html       Seat page, city ward 01-12                        (later, M4; not generated before)
items/<yyyy>.html     unchanged
finance.html          "Coming" page                                     (new)
capital-projects.html "Coming" page                                     (new)
data.html             Downloads: every export file, plain list          (new; reuses G5 export)
about.html            gains #the-record (the moved at-a-glance band)
changes.html          unchanged
```
File budget: +~32 pages, inside the 250-file limit before search. Search index files are the open budget question
(section 5.6, Q3).

Where the old landing content goes:

| Was on `index.html` | Moves to | Why |
|---|---|---|
| h1 "Officials", lede, cards | `officials.html`, split Current / Served previously (6A) | Owner: too much on the main page |
| At-a-glance band + note | `about.html#the-record`, h2 "The record" | It describes data quality, which About already explains |
| Meetings timeline + year jump | `meetings.html` | Its own nav entry |
| Coverage kicker in masthead | stays on inner pages; on the landing it is folded into the purpose line | One line instead of two |

## 2. Navigation drawer (all pages, all screen sizes)

Replaces both `nav-wide` and `nav-narrow` `<details>` menus in `base.html.j2`.

### 2.1 Behaviour
- Top-left of the masthead: a menu button (three-line icon plus the visible word "Menu"; the word keeps it clear
  for people who do not know the icon, and is the accessible name). Site name to its right.
- **With JS:** the control is `<button type="button" id="nav-open" aria-controls="site-nav-drawer"
  aria-expanded="false" aria-haspopup="dialog">`. Pressing it calls `showModal()` on
  `<dialog id="site-nav-drawer" aria-labelledby="nav-title">`, styled as a panel sliding in from the left
  (width `min(20rem, 85vw)`, full height). Native modal dialog gives:
  - focus moves into the panel (to the Close button first, set with `autofocus`);
  - focus is trapped: the rest of the page is inert while open;
  - Esc closes it (`cancel` event);
  - focus returns to the menu button on close (set explicitly in the `close` handler as well, for older engines).
- Outside click closes: a click whose target is the `<dialog>` element itself (the backdrop area) calls `close()`.
- `aria-expanded` is set to `true` on open and `false` on close.
- Inside the panel, top to bottom: heading "Menu" (`#nav-title`), Close button ("Close menu", x icon plus text
  for screen readers), a search field (submits to `search.html?q=`), then the link list (2.2).
- Choosing a link closes the drawer by navigating. The current page has `aria-current="page"` and a 3px left rule.
- Motion: slide 200 ms; none when `prefers-reduced-motion: reduce`.
- Backdrop: `::backdrop` in `rgb(0 0 0 / .4)`.
- **Without JS:** the server-rendered control is `<a id="nav-open" href="#site-nav">Menu</a>`. It jumps to the
  footer, where the same list is rendered as `<nav id="site-nav" aria-label="All pages">`. The dialog markup is not
  rendered without JS: `static/nav.js` (vanilla, ~40 lines) clones the footer list into the dialog and swaps the
  link for the button. So the footer list is the single source and also serves people who scroll to the end.
- Script budget: N6 allows only `static/filter.js` today. `nav.js` (and `search.js`, `map.js`) need the architect
  to extend N6 to "first-party scripts in `static/` only" (Q6).

### 2.2 Link list (fixed order, the same on every page)
```
Map (home)
Search
Votes
Meetings
Officials
Items                 -> items index list of years (a nested list, not a second drawer)
Finance               COMING
Capital projects      COMING
Data downloads
About
Changes
Review (internal)     only in --internal builds
```
"COMING" is a small-caps chip (`.chip`, `--mark-soft` border, no colour fill). The link still works and opens the
coming page. Screen readers hear "Finance, coming".

### 2.3 Wireframes: drawer

Phone, 375 px, closed / open:
```
+-------------------------------------+     +---------------------------+---------+
| [=] Menu   Clarksville Records      |     | Menu              [x]     |/////////|
+=====================================+     |                           |/////////|
| ...page...                          |     | [ Search records...   ]   |/ page  /|
                                            |                           |/ dimmed/|
                                            | > Map (home)              |/ inert /|
                                            |   Search                  |/////////|
                                            |   Votes                   |/////////|
                                            |   Meetings                |/////////|
                                            |   Officials               |/////////|
                                            |   Items: 2024 2023 ...    |/////////|
                                            |   Finance        COMING   |/////////|
                                            |   Capital projects COMING |/////////|
                                            |   Data downloads          |/////////|
                                            |   About                   |/////////|
                                            |   Changes                 |/////////|
                                            +---------------------------+---------+
```
Desktop: the same panel, 20rem wide, over the left edge of the page; the page stays in place behind the backdrop.

## 3. Landing (`index.html`)

### 3.1 Content, nothing more
1. Masthead (compact: menu button + site name; no kicker on this page).
2. h1, visually the purpose line: "Votes and records of the Montgomery County Commission, linked to the county's
   own minutes." Under it, `--t-sm --muted`: "{{ coverage.from }} to {{ coverage.to }}. City of Clarksville records
   are coming." (Neutral: what the site holds, no claim about anyone.)
3. Search box: label "Search records" (visible), placeholder "Item title, number, name or street", button
   "Search". It is a plain `<form action="search.html" method="get">` with `name="q"`, so it works without JS
   (search.html then shows its no-JS state).
4. Layer switch, a `<fieldset>` with legend "Map shows" and two radios: "County commission districts" (checked)
   and "City wards (coming)".
5. Map (3.2).
6. District list (3.3), collapsed under the map on phones, beside it on desktop.
7. Footer (operator line, data as of, full nav list).

### 3.2 Map
- Built at build time: `sitegen` reads boundary files (GeoJSON) cached in `data/boundaries/` (APSU GIS
  MontElections layer 2 for the 21 districts, layer 1 for the 12 wards, each with source URL and fetch date in
  config; research doc), simplifies and projects them to an SVG `viewBox`, and inlines one `<svg>` in `index.html`
  (target under 60 KB). **No basemap and no tiles**, no library, no request at view time. The `commission` and
  `councilmem` name fields in those layers are stale and are never shown: names come from the roster (4.1).
- Layer `districts` (`<g id="layer-districts">`): 21 paths, each wrapped in `<a href="districts/07.html"
  tabindex="-1">`. All paths: fill `--surface`, stroke `--fg` 1px. Hover: stroke 3px `--focus` and fill
  `--surface-2`. **The fill never encodes anything** (no vote, attendance or count measure; no per-person colour).
  Labels: the district number at a point inside each shape (pole of inaccessibility, computed at build), serif,
  `--t-sm`, with a 3px `--bg` halo for contrast. Small districts in the city get a leader line to a label outside
  the shape when the shape is under ~24px at phone width.
- Layer `wards` (`<g id="layer-wards">`): the 12 ward shapes exist (APSU layer 1), so before M4 they are drawn as
  outlines with their numbers, **not links**, in `--mark-soft`, with a centred note "City wards: coming". After M4
  they become links to `wards/<nn>.html` with the same rules as districts.
- Context: the county outline, the Cumberland River as a thin `--muted` line, and the label "Clarksville" at the
  city's centre, so people can orient without a basemap. Nothing else (no roads, no pins).
- Layer switch without JS: CSS `:has()` on the fieldset (`.landing:has(#show-wards:checked) #layer-districts {
  display:none }`). Where `:has()` is unsupported, both layers draw (wards outline is light), which is acceptable.
- `map.js` (optional enhancement, ~30 lines): focusing or hovering a link in the district list adds `.is-lit` to
  the matching path, and vice versa, so keyboard users see where a district is.
- The `<svg>` has `aria-hidden="true"` and `focusable="false"`. A visually hidden sentence before it says: "Map of
  Montgomery County's 21 commission districts. The same districts are listed after the map." This is the honest
  text alternative; the list is the equivalent.
- Lines shown are the **current** lines (approved 2021-11-08, first used for the seats filled on 2022-09-01).
  Map caption, `--t-xs`: "Current district lines, in use since {{ lines.current.effective }}. Boundaries: {{
  lines.current.source_title }}, fetched {{ date }}. Old district lines (before {{ date }}): map (PDF)." (N4).

### 3.3 District list (the accessible equivalent)
`<nav aria-label="County commission districts">` with an `<ol>` in district-number order, 1 to 21:
```
District 1   Jane Doe
District 2   Seat vacant
District 3   John Roe
...
```
- Each row is one link to `districts/<nn>.html`; the name is the seat's **current holder** (rule 6A.1), from the
  same holder records as the district page. Same layout for every row (N1). No counts, no badges, no colour.
- If the current holder is not known from a source: "Current member not yet recorded" (same wording for all).
  A vacancy recorded in the source: "Seat vacant".
- Wards: a second list "City wards", with one line "City ward pages are coming." until M4, then 12 rows in the
  same form.
- Phone: inside `<details class="district-list">` with summary "All 21 districts, by number" so the landing fits
  one screen; desktop: always open in a side column (two columns of rows).

### 3.4 States
| State | What shows |
|---|---|
| Normal | As above |
| No boundary file at build | The map area is replaced by the list, open, with "The map is not available yet. Districts are listed by number." (Same template, no broken SVG.) |
| No seat data (roster not built yet) | Map and list draw; each list row reads "District 7"; each district page shows its empty state (4.5) |
| Wards layer before M4 | "City of Clarksville wards are coming. The city's records have not been collected yet." Radio stays enabled so people can see the notice |
| No JS | Everything works: map links are plain links, layer switch via CSS, search box submits to search.html |
| Loading | None: the page is static HTML with inline SVG |
| Fixture build | The existing FIXTURE banner above the masthead |

### 3.5 Wireframes: landing

Phone, 375 x ~600 px visible (everything above the fold):
```
+-------------------------------------+
| [=] Menu   Clarksville Records      |  masthead, 48px
+=====================================+
| Votes and records of the Montgomery |  h1 / purpose (serif, --t-lg on phone)
| County Commission, linked to the    |
| county's own minutes.               |
| 2020-01-06 to 2024-12-09. City      |  --t-sm --muted
| records are coming.                 |
| Search records                      |
| [ Item title, number, name.. ][Go]  |
| Map shows: (o) Districts ( ) Wards  |
|  +-------------------------------+  |
|  |   ____                        |  |
|  |  / 1  \___    __    ___       |  |
|  | |  2  | 3 \__/ 5\__/ 6 \      |  |  inline SVG, same fill for all,
|  | | _4_/Clarksville  7  |       |  |  numbers labelled
|  |  \ 8 |9|10|11|...  ~river~    |  |
|  |   \__ 12 __/  ...  21 _/      |  |
|  +-------------------------------+  |
|  Lines in use since 2022-09-01.     |  caption --t-xs, source link
|  Source: ..., fetched 2026-11-07    |
| > All 21 districts, by number       |  <details>, closed
+-------------------------------------+
  footer (below the fold): operator line, data as of, all pages
```

Desktop, 1280 x 800:
```
+--------------------------------------------------------------------------------------+
| [=] Menu   Clarksville Records                                                       |
+======================================================================================+
|  Votes and records of the Montgomery County Commission, linked to the county's own   |
|  minutes.  2020-01-06 to 2024-12-09. City records are coming.                        |
|  Search records [ Item title, number, name or street                   ] [Search]    |
|                                                                                      |
|  Map shows: (o) County commission districts  ( ) City wards (coming)                 |
|  +-----------------------------------------------+  County commission districts      |
|  |                                               |  District 1   Jane Doe            |
|  |         county outline, 21 districts,         |  District 2   Seat vacant         |
|  |         numbered; river line;                 |  District 3   John Roe            |
|  |         "Clarksville" label                   |  ...  (two columns, 1-11 | 12-21) |
|  |                                               |  District 21  ...                 |
|  |                                               |                                   |
|  +-----------------------------------------------+  City wards                       |
|  Lines in use since 2022-09-01. Source: ..., p. 3 |  City ward pages are coming.      |
+--------------------------------------------------------------------------------------+
```

## 4. Seat page (`districts/<nn>.html`; later `wards/<nn>.html`)

"See how that area's rep voted, whoever it may have been": the page is about the seat, and lists each person who
held it with the votes they cast while they held it.

### 4.1 Holder records (where seat history comes from)
- **Roster file** `config/seats.yml` (per locality, per the ZIP-code note in `docs/status.md`): one row per holder
  record: `seat` (e.g. `county-commission/07`, `county-mayor`), `official_id`, `start`, `end` (empty while
  current), `source_url`, `source_page`, `fetched_at`. Vacancies are rows with `official_id: null` and a source.
  Every row needs a source (N4, G2): the county Elected Officials List, certified election results, or the minutes
  where a member is sworn in or appointed. No row without one.
- **Cross-check** against the minutes: each "District Commissioner Vote" table prints the district number before
  each name, and the parser already splits it off ("4 Rickey Ray"). Keep it per vote (`votes[].district`). The
  build checks, for every confirmed roll call, that the resolved `official_id` in district slot N matches the
  roster's holder of seat N on that date. A mismatch is a build warning listed on `review.html`, never silently
  fixed. Same check for everyone.
- **New record rule:** when the holder of a seat changes (different `official_id`, or a vacancy), the old record ends
  and a new one starts. The date shown is the roster row's date with its source; the roll calls only check it.
- If a seat has no roster rows yet, the page falls back to "Seen in the record from {{ first }} to {{ last }}",
  derived from the vote tables and labelled as such, so no term date is claimed without a source.
- Unresolved names never form a holder record (P3); their district slot reads "Name not matched*" on the meeting
  page only, as now.

### 4.2 Redistricting: old district lines (before 2022-09-01)
County lines were approved on 2021-11-08 (21 districts kept; numbers 19 and 20 swapped by amendment), first used at
the 2022-08-04 election, with seating on about 2022-09-01 (research doc; date to confirm from the minutes, Q1). The
seat number continued, the area did not.
- Seat pages are split into two periods with fixed headings: **"Current district lines (from 2022-09-01)"** and
  **"Old district lines (before 2022-09-01)"**. The old period has no SVG (pre-2022 lines exist only as PDFs); it
  has a link "Map of the old district lines (PDF)" from config. The old county map PDF has not been found yet: until
  it is, the link reads "The map of the old district lines has not been found yet. County redistricting page:"
  followed by the link to `montgomerytn.gov/election/2021-redistricting`. Same text on all 21 pages.
- A fixed notice at the top of every seat page, same words for all 21 (`.note`, not a warning colour): "District
  lines were redrawn in 2022. Before 2022-09-01, District {{ n }} covered a different area. Votes under the old
  district lines are listed separately." For Districts 19 and 20 add the fixed line "Under the new map, District 19
  and District 20 swapped numbers." (stated as the amendment did, both pages the same).
- A holder record that spans the change (same person, same number) is split into two at 2022-09-01, one per period,
  each with its own totals. Totals are never added across periods.
- The landing map always shows current lines; it never implies a past member represented today's area.
- City wards: the same pattern applies when M4 adds ward pages (new wards likely from the Nov 2022 election, terms
  from Jan 2023; to verify then).

### 4.3 Content, top to bottom
1. h1 "County Commission District 7". Under it the fixed redistricting notice (4.2).
2. Small outline map: the county outline with this district drawn in `--mark` hatch; caption with source (N4).
   `aria-hidden`; text before it: "District 7 is shown on the county map."
3. **"Current"** (h2): the current holder record (6A.1), one row: name (link), "District 7", "from 2022-09-01"
   with its source. Or "Seat vacant since {{ date }}" with source, or "Current member not yet recorded".
4. **"Served previously"** (h2): every earlier holder record of this seat, newest first by end date (this is a
   seat's own timeline, so date order; the site-wide list in 6A is alphabetical). Columns, same for every row:
   | Person | Held this seat | Lines | Source |
   |---|---|---|---|
   | John Roe (link) | 2018-09-01 to 2022-08-31 | Old district lines | Elected Officials List, p. 1 |
   | Seat vacant | ... | ... | minutes 2019-04-08, p. 2 |
   Vacancy rows only where a source records it. Empty state: "No earlier holders are recorded for this seat."
5. Per holder record, an h3 "Jane Doe, District 7, 2022-09-01 to present" (former: "... to 2022-08-31"), placed
   under its period heading (4.2), then:
   - the totals sentence from `views.totals_sentences`, scoped to the record's dates (N3 wording, denominator and
     date range stated; confirmed and not confirmed never added; switch off: "N roll calls not confirmed*, see each
     page");
   - the official page's history table (existing macro and rows), filtered to the record's dates and to votes cast
     in this district's slot. Unconfirmed rows stay "Not confirmed*" with the link, no value. Collapsed by year with
     the existing `year-group` `<details>`, newest year open.
   - a link "All of Jane Doe's records" to her official page.
6. Report-an-error and source rules as on every fact row (N4, N5).

Every holder-record block has the same structure, whoever it is (N1); order is by date only.

### 4.4 Wireframe: seat page (phone)
```
+-------------------------------------+
| [=] Menu   Clarksville Records      |
+=====================================+
| County Commission District 7        |  h1
| | District lines were redrawn in    |  .note, same for all seats
| | 2022. Before 2022-09-01, District |
| | 7 covered a different area. Votes |
| | before and after are separate.    |
|  [ small county outline, D7 hatched]|
|  Source: ..., fetched ...           |
| Current                             |  h2
| Jane Doe  District 7  from          |
| 2022-09-01  Source: list p. 1       |
| Served previously                   |  h2
| +---------------------------------+ |
| | John Roe   2018-09-01-2022-08-31| |  table scrolls in its box
| |  Old district lines  Source ... | |
| +---------------------------------+ |
| == Current district lines (from     |  h2
|    2022-09-01) ==                   |
| Jane Doe, District 7, 2022-09-01    |  h3
| to present                          |
| Roll call votes, 2022-09-12 to      |
| 2024-12-09: 210 Yes, 6 No, 1        |
| Abstain, 0 Other confirmed; 4 roll  |
| calls not confirmed*, see each page.|
| v 2024                              |  year-group, open
|   2024-12-09  24-12-2 ...   Yes     |
|   Source: minutes p. 41, fetched .. |
|   2024-11-04  CZ-9-2024 ... Not     |
|               confirmed* (p. 12)    |
| > 2023                              |
| All of Jane Doe's records ->        |
| == Old district lines (before      |  h2
|    2022-09-01) ==                   |
| Map of the old district lines (PDF) |  link from config, or the "not found yet" line
| John Roe, District 7, 2020-01-06 to |  h3 (dates of the record, clipped to the data)
| 2022-08-31                          |
| ...                                 |
+-------------------------------------+
```
Desktop: same order, `--measure` width, table un-stacked.

### 4.5 States
| State | Text |
|---|---|
| No holder records for this district | "No votes are recorded for District 7 in the minutes collected so far." (fixed, all seats) |
| Old lines map PDF not found | "The map of the old district lines has not been found yet. County redistricting page: <link>" |
| Holder record with no roll calls | totals sentence with zeros, then "No roll call votes in this period." |
| Ward page before M4 | not generated; the landing's ward notice covers it |

## 5. Search (`search.html`)

### 5.1 What is searchable (records)
One search record per:
- **Item** (`items/<yyyy>.html#<item_id>`): number, verbatim title (rezoning applicants and addresses appear here),
  every appearance's verbatim label. This is how "search for rezoning applicants" works: full text over titles.
- **Roll call** (anchor on its meeting page): item number and title, date, body, outcome (confirmed only).
- **Meeting**: date, body, kind.
- **Official** and **District**: name / number, so a name search also finds their page.

### 5.2 Filters (all optional, combinable, all stored in the URL)
| Filter | Control | Values, order | Notes |
|---|---|---|---|
| Show | checkboxes | Items, Votes, Meetings, People and districts | record kind |
| Body | checkboxes | County Commission; City Council (coming, disabled) | |
| Years | two selects "From" / "To" | each year in the data | sent as "any of" the years in the range (5.6) |
| Item type | checkboxes | Rezoning, Budget and finance, Resolution, Ordinance, Appointment, Other | mechanical rule, 5.4 |
| Official | select | "Anyone", then everyone alphabetical by surname | |
| How they voted | radios | Any, Yes, No, Abstain, Other | enabled only when an Official is chosen; confirmed roll calls only |
| Outcome | checkboxes | Passed, Failed, Other | confirmed roll calls only |
| Sort | select | Best match, Newest first, Oldest first | no sort by any count |

- URL form: `search.html?q=smith&kind=item&type=rezoning&from=2021&to=2023&official=jane-doe&vote=no&sort=new`.
  Changing a filter updates the URL (`history.replaceState`), so Back, bookmarks and sharing work. A "Copy link to
  this search" button copies it. This is the "customizable" part; nothing is stored about the visitor (N6).
- "Clear all filters" button; active filters shown as removable chips above results ("Type: Rezoning x").
- **Confirmed only:** when How they voted or Outcome is set, a fixed line appears above the results: "Filtering by
  vote or outcome uses confirmed roll calls only. {{ n }} roll calls that match the other filters are not confirmed
  and are left out. [Show them without the vote filter]" The link removes only the vote/outcome filters. Not
  confirmed records carry no vote or outcome filter value, so they can never match one (invariant rule 1 and 5).
- **No counts next to official names** in the Official select or anywhere in filters: a per-person result count is a
  count beside a name, which N3 does not allow outside the fixed sentences. Counts next to Body, Type and Year values
  are allowed (they are about records, not people); recommend showing them (Q5).

### 5.3 Result row
```
ITEM · Rezoning · County Commission                         <- small caps, --muted
CZ-18-2020  Application of [verbatim title with <mark>smith</mark> highlighted ...]
Appears 3 times, 2020-03-09 to 2020-05-11  ·  items/2020.html
```
- Roll call row, when an Official + How they voted filter is set: adds "Jane Doe: No" with "Source: minutes p. 12,
  fetched 2026-11-07" (N4). Without a vote filter, no vote value is shown in results; the item/meeting page has it.
- Outcome only for confirmed roll calls ("Passed"); unconfirmed: "Not confirmed*" and the page link.
- Every kind uses one row layout; highlight is `<mark>` in `--banner-bg`, never a colour per official.

### 5.4 Item type rule (mechanical, written on the About page)
From the official item number prefix where one exists (e.g. `CZ-` rezoning, `AB-` per the county's numbering,
to be confirmed from the agendas, Q4), else from fixed words in the verbatim title ("rezone", "rezoning", "budget",
"appropriat", "resolution", "ordinance", "appoint"), else "Other". Same rule for every item; the rule table is
rendered on About from config so it is checkable. Items can match more than one type.

### 5.5 Layout and states

Phone:
```
+-------------------------------------+
| [=] Menu   Clarksville Records      |
+=====================================+
| Search records                      |  h1
| [ smith rezoning              ][Go] |
| [Filters (2)]  Sort [Newest first v]|  Filters opens an in-page panel
| Type: Rezoning x   2021-2023 x      |  active chips
| Clear all   Copy link to this search|
| 14 results                          |  aria-live polite
| ----------------------------------- |
| ITEM · Rezoning · County Commission |
| CZ-18-2021 Application of ...Smith..|
| Appears 3 times, 2021-03-08 to ...  |
| ----------------------------------- |
| ...                                 |
| [ Show more results ]               |
+-------------------------------------+
```
Phone filter panel: a `<details>` "Filters" expanding in place above results (not a second drawer, so it never
competes with the nav drawer), with an "Apply" button that collapses it and moves focus to the result count.

Desktop: filters in a left column (16rem) always open, results on the right, query box full width on top.
```
+--------------------------------------------------------------------------------------+
| [=] Menu   Clarksville Records                                                       |
+======================================================================================+
| Search records  [ smith rezoning                                    ] [Search]       |
| +-- Filters ---------+  14 results     Sort [Newest first v]  Copy link to search    |
| | Show               |  Type: Rezoning x  2021-2023 x  Clear all                     |
| | [x] Items [ ] Votes|  ---------------------------------------------------------    |
| | Body               |  ITEM · Rezoning · County Commission                          |
| | [x] County Comm.   |  CZ-18-2021  Application of ... Smith ...                     |
| | [ ] City (coming)  |  Appears 3 times, 2021-03-08 to 2021-05-10                    |
| | Years [2021v]-[2023v]  ---------------------------------------------------------   |
| | Item type          |  ...                                                          |
| | [x] Rezoning (31)  |                                                               |
| | Official [Anyone v]|                                                               |
| | How they voted     |                                                               |
| |  (disabled until an official is chosen)                                            |
| | Outcome [ ]P [ ]F  |                                                               |
| +--------------------+                                                               |
+--------------------------------------------------------------------------------------+
```

| State | What shows |
|---|---|
| Empty query, no filters | Short help: "Search item titles, numbers, names and streets. Example: an item number like CZ-18-2020, or a street name." Examples never name an official. Browse links: Votes, Items by year, Meetings. |
| Loading index | "Loading search..." in the results region (`aria-live="polite"`, `aria-busy="true"`); controls usable |
| No results | "No records match. Try fewer filters or a different spelling." + the active chips with remove buttons |
| Index fails to load (e.g. opened from a file or zip) | "Search could not load here. It works when the site is opened from a web address. You can browse Items by year or download the data." |
| No JS | `<noscript>`: "Search needs JavaScript. Browse instead:" + links to Votes, Meetings, Officials, Items, Data downloads. The `q` from the landing form is echoed: "You searched for: smith." |
| Fixture build | FIXTURE banner as now |

Accessibility: one `<form role="search">`; every control has a visible label; filter groups are fieldsets with
legends; result count in a polite live region; "Show more" keeps focus on the first new result; the disabled vote
radios carry the hint text "Choose an official first" via `aria-describedby`.

### 5.6 Pagefind fit and limits (for the architect)
Pagefind is the planned tool. The design above uses only what it does:
- **Full text + excerpts with highlights:** yes.
- **Filters:** `data-pagefind-filter` per record, combined in the JS API with `any` within a filter and AND across
  filters. Year range: sent as `{year: {any: [2021, 2022, 2023]}}`. **No numeric or date-range filters**, so ranges
  are by whole year; a month range is not possible (accepted limit).
- **Sort:** `data-pagefind-sort="date"` with ISO dates: Newest/Oldest work. Best match is the default.
- **Metadata:** `data-pagefind-meta` for kind, number, date, body, outcome, used to draw the result row.
- **Filter counts:** Pagefind returns counts per filter value; we hide them for the Official filter (5.2).
- **Granularity limit:** filters belong to a *page*, not a section. Items live in year-bucketed pages with many items
  each, so page-level filters would tag a whole year. Use Pagefind's custom records (`addCustomRecord`, Python or
  Node API) with anchor URLs, one per item / roll call.
- **File-count limit:** Pagefind writes a fragment file per record plus index and filter chunks. Thousands of records
  means thousands of files, over the 250-file budget and the claude.ai artifact limits (ADR 0001). (Q3.)
- **Opened from file:// or a zip:** Pagefind loads WASM and chunks by fetch, which fails from the file system. The
  error state covers it.
- Vote-by-person filter: an `official` filter plus a `vote` filter on one roll-call record would also match records
  where a *different* person voted that way. To be exact, the vote filter value is the pair: `vote: "jane-doe:no"`.
  The UI hides this; the index stores pairs, confirmed roll calls only.

## 6A. Current and former officials, and seat labels

### 6A.1 The rule (mechanical, the same for everyone; written on the About page)
- A holder record is **current** when it has no `end` date in the roster, or its `end` is after the latest meeting
  in the data. Everyone else with at least one holder record is **served previously**.
- A person who is current in one seat and held another earlier is listed once, under Current, with both seats.
- A person in the facts with votes but no holder record yet: listed under "Seat not yet recorded" (fixed text, same
  for all), so nobody is placed by guess. This list should be empty once the roster is complete; the build warns
  while it is not.

### 6A.2 Seat label (on every list and page that names an official)
- Text from the seat: "District 7" (county commission), "Ward 3" (city council, M4), "County Mayor", "City Mayor",
  or the seat's name as the source states it for any at-large or other seat. Plain text after the name, same style
  for everyone (`--muted`, body font, no chip colour, no icon). It is not a link to avoid two links per row; the
  seat page is linked from the official page instead.
- Current: "Jane Doe, District 7". Former: "John Roe, District 7, 2018-09-01 to 2022-08-31". More than one seat:
  each seat with dates, newest first, separated by "; ".
- Where it appears: officials page cards, landing district list, seat pages, official page header ("District 7,
  from 2022-09-01" under the name and title), meeting attendance tables and roll-call rows (the seat held **on that
  meeting's date**), item history roll-call blocks, search result rows and the Official filter options ("Doe, Jane
  (District 7)"), the Votes pages. The export gains `seat` on each vote and a `seats.csv` of holder records.
- Old-lines seats keep their number with "(old lines)" where a date-specific label is shown for a meeting before
  2022-09-01: "District 7 (old lines)". Same for everyone.

### 6A.3 Officials page (`officials.html`)
```
Officials                                                       <- h1
Current members of the County Commission, by district number. Then everyone who served previously, by surname.

Current                                                         <- h2
[JD] Jane Doe              District 1                            <- existing card, seat label added
     County Commissioner
     Present at 58 of 61 meetings with attendance shown
     Recorded vote on 290 confirmed and 3 not confirmed* roll calls
[..] ...                   District 2 ... District 21
     County Mayor card (seat label "County Mayor") listed after the districts

Served previously                                               <- h2
[JR] John Roe              District 7, 2018-09-01 to 2022-08-31
     County Commissioner
     Present at ... (same two lines, counts over their own dates)
...  alphabetical by surname

Seat not yet recorded                                           <- h2, only when non-empty
```
- Order: **Current** by seat (district number 1-21, then mayor and any other seats in a fixed config order) because
  that is how residents look up "my district" and it is a neutral field (N1 allows neutral-field sorts);
  **Served previously** alphabetical by surname. One card template for both sections (same lines, same fields); the
  section heading is the only difference. Recommendation flagged as Q10 (alternative: both alphabetical).
- Phone: one column; each section is a `<details>` open by default for Current, closed for Served previously
  ("Served previously (14)": a count of people in a section, not a count next to a person).
- No "former" styling (no greying out, no strike, no badge colour): former members look exactly like current ones.

## 6. Coming pages: Finance, Capital projects

Same template, `coming.html.j2`, two pages:
```
Finance                                                   <- h1
Coming. County budget books and audits (TN Comptroller) are planned. Nothing is shown here until it is collected
from the source documents, and every figure will link to its page.
What is planned: [plain list from config: approved budgets, audits, contracts]
Get notified: not available (no accounts).               <- omit; see note
See the data rules on the About page.
```
- Capital projects: "Coming. Capital projects named in county budget books and commission resolutions are
  planned..." Same structure.
- No numbers, no sample chart, no placeholder table, no "example" values (owner rule: no fake data). Drop the
  "Get notified" line entirely (M5 is a hard stop); it is shown above only to mark that it is deliberately absent.

## 7. Later (sketch only, not scheduled): finance over time, and downloads

**Finance explorer** (`finance/compare.html`, after M2 data exists). The visitor picks one or more series from a
list (for example: Montgomery County total expenditures, by fund; City of Clarksville total expenditures; other
Tennessee counties from the Comptroller's audited financial statements, which share a format) and a unit (dollars as
reported; optionally per resident, with the population source cited). Each series is drawn as a line by fiscal year.
Lines are told apart by direct end labels and dash pattern in the one `--mark` ink plus up to three neutral greys,
never by party-coded or good/bad colours; no trend arrows, no computed "increase" labels; values only, each point
linked to its source page. The page starts empty ("Choose series to compare") so no comparison is chosen for the
visitor. A data table under the chart is the accessible equivalent and always present. "Download these series" gives
CSV and JSON of exactly what is drawn, with source columns. A comparability note is fixed text: "Counties group
spending differently; the Comptroller categories are used where available."
```
+----------------------------------------------------------------+
| Compare spending over time                                     |
| Series: [+ Add series v]  Montgomery County total x  City x    |
| Unit: (o) Dollars as reported  ( ) Per resident                |
|  $ |                                   ___ Montgomery County   |
|    |                          ____----                         |
|    |            ____-----''''  - - - - - - City of Clarksville |
|    |  ___----''   - - - - -                                    |
|    +----+----+----+----+----+----+--> fiscal year              |
|     2019 2020 2021 2022 2023 2024                              |
| [Table of values, each with source link]                       |
| Download: CSV  JSON                                            |
+----------------------------------------------------------------+
```
**Any data in any format.** Now: `data.html` lists every G5 export file (CSV and JSON) with a one-line description
and its row count, plus a link to the schema. Later: each search and each seat page gets "Download these results as
CSV / JSON", generated in the browser from the records already loaded (no server).

## 8. Components

| Component | New or reused |
|---|---|
| Masthead, footer, `.note`, `.chip`, `.badge`, `year-group`, timeline, history table, roll-call block, totals sentences, citation line | reused (`visual-refresh.md`) |
| Officials cards, meetings timeline | reused, moved to `officials.html`, `meetings.html`; cards gain the seat label and split Current / Served previously |
| Seat label (`.seat`) | new, plain text after every official name |
| Holder records table (Current, Served previously) | new |
| Nav drawer (`<dialog>`) + footer nav list | new, replaces `nav-wide`/`nav-narrow` |
| Landing map (inline SVG) + layer switch | new |
| District list | new (plain `ol` of links) |
| Seat page | new; holder-record blocks reuse history rows |
| Search form, filter panel, active-filter chips, result row | new (chips reuse `.chip`) |
| Coming page | new, one template |
| Data downloads page | new, plain list |

## 9. Accessibility checks (QA)
- Landing at 375 x 667: purpose, search, layer switch, map and the district-list summary are visible without
  scrolling. No horizontal page scroll at 320 px.
- Every district is reachable by keyboard through the list alone; the SVG produces no tab stops and no screen-reader
  output beyond the one sentence.
- District labels and ward notice meet 4.5:1 against the map fill in light and dark themes.
- Drawer: Tab cycles inside it while open; Esc closes; outside click closes; focus returns to the menu button;
  `aria-expanded` matches the state; with JS off, "Menu" jumps to the footer list.
- Search: all filters operable by keyboard; result count announced; disabled vote control explains why.
- No colour carries meaning anywhere (map, results, chips). Greyscale screenshot reads the same.
- Template lint (banned words, no count sorts) also runs on the new templates.

## 10. Neutrality checks (QA)
- Map fills are one value for all districts (test: every district `<path>` has the same class and no inline fill).
- District list, seat pages and holder-record blocks render the same skeleton for any two seats (extend the N1 skeleton
  test to `districts/*.html`).
- Official select is alphabetical by surname and shows no counts.
- Vote/outcome filters never match an unconfirmed roll call (test on the built index).
- Example text and empty states name no official.

## 11. Open questions (recommended answer first; work proceeds on it)
1. **Effective date of the 2022 lines.** Recommended: 2022-09-01 (research, medium-high), confirmed from the first
   meeting after the 2022-08-04 election, where new members appear in the vote table. Backend checks; no CEO input.
2. **Seat history source.** Recommended: roster file `config/seats.yml`, a source per row, cross-checked against the
   district numbers printed in each roll call table (4.1); the "seen in the record" fallback only for seats with no
   roster row yet. Architect confirms the parser keeps `district` per vote.
3. **Search index vs the 250-file budget.** Recommended: architect decides; my recommendation is Pagefind custom
   records only when hosting allows thousands of files, and for the private preview a single first-party JSON index
   (`data/search.json`, one record per item/roll call, filtered in `search.js`). Same UI either way; the JSON index
   also allows exact date ranges.
4. **Item type rule.** Recommended: number prefixes from the county agendas plus the fixed title words in 5.4,
   rendered on About. Backend confirms the prefix meanings (e.g. `CZ`, `AB`) from source documents before release.
5. **Counts next to Body/Type/Year filter values.** Recommended: show them (records, not people); never next to
   official names.
6. **First-party scripts.** Recommended: architect amends N6 to "first-party scripts from `static/` only, no
   third-party" so `nav.js`, `map.js` and `search.js` are allowed. Without it, the drawer falls back to the footer
   list and search is unavailable.
7. **Boundary files.** Recommended: APSU GIS MontElections layers 2 (districts) and 1 (wards), fetched once and
   cached with source URL and fetch date (research doc); old lines link to PDFs only. Neither service states reuse
   terms: treat as public record for the private preview; confirming reuse before public launch would need an email
   from Brian (hard stop 4), so raise it at the G6 check, not now.
8. **"Find my district" by address.** Recommended: not now (needs a geocoder, which is a third-party request or a
   large local dataset). Add a plain link to the county election commission's own lookup page if one exists.
9. **Focus Group.** Recommended: skip while the preview is for the CEO only (playbook); run one on the landing and
   search before any public launch (G6).
10. **Order of Current officials.** Recommended: by district number (neutral field, matches the map); Served
    previously alphabetical by surname. Alternative: both alphabetical. Not a CEO question unless he objects.
11. **Old county district map PDF** (not found by research). Recommended: link the county redistricting page until a
    PDF is found; backend looks for it on montgomerytn.gov during M1.5. No email to the county (hard stop 4).

## 12. Proposed spec changes
- Add D1-D10 to the spec as M1.5 scope: landing map, seat pages, search with filters (replaces "agenda search (US3)"
  with the wider search), coming pages for Finance and Capital projects, data downloads page.
- Data model: `votes[].district` (sourced, per roll call); `config/seats.yml` holder records with a source per row;
  `data/boundaries/` with source and fetch date; export `seats.csv` and `seat` on each vote.
- Officials (US1 area): add the Current / Served previously split and the seat label (6A) as acceptance criteria.
- Architecture "Static site generator" page table: `index.html` is now the landing; officials index moves to
  `officials.html` (tests that assume `index.html` is the officials list must move with it).
- Later list: add the finance explorer (section 7) under M2 follow-on, and per-result CSV/JSON downloads.
