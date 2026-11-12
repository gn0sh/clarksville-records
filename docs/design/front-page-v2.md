# Front page v2: a friendlier landing (design, 2026-11-11)

Owner's problem: "With the map gone, the front page looks kind of intimidating." The landing today is one long scope
sentence, raw date ranges, the "Independent, unofficial" statement twice on one screen, two input boxes and three
collapsed lists. It says what the site holds but not what is happening or where to start.

Mock: `front-page-v2-mock.html` (static, real values copied from the 2026-11-11 build; never ship it).
Look: Daylight, unchanged (`daylight/README.md`, tokens in `site/static/style.css`). No new colours or fonts.
Build target: Friday 2026-11-13. No new data is collected; one small selection function is new.

## Who it is for
A first-time resident on a phone who does not know their ward, their district, or what a "formal meeting" is.
Three questions they arrive with: who represents me, what did they decide, what is coming up.

## Layout, top to bottom

| # | Section | What it shows | Data source | Existing or new |
|---|---|---|---|---|
| 0 | Header | Menu, name plate, "Independent, unofficial" tag, sky date linking `today.html` | `base.html.j2`, `index.html.j2` block `sky`, `static/sky.js` | Existing, unchanged |
| 1 | Welcome | h1, one lede sentence, one short unofficial line with a link to About | Copy in `config/site.yml` (new keys `welcome_h1`, `welcome_lede`); unofficial line from `unofficial.email_line` | New copy, replaces `site.purpose` h1, `purpose-sub` dates and `home_line` |
| 2 | Find who represents you | The address box in a bordered card; result and "Your seats" appear inside it | `views.address_context` (`address`), `static/address.js`, `static/seats.js` | Existing form, same ids; new heading, label and wrapper |
| 3 | Start here | Four doors, each with a title, one sentence and two links | Hrefs from `site.nav` / `site.councils` / `rpc.home_href()`; counts from `site.cfg.ward_count`, `district_count` | New component `door` |
| 4 | Meetings | "Coming up" (next 3) and "Most recent" (last 3) meetings, each row linking its day on `today.html` | `days.page()` cards (see below) | New component `meet-row`; new selection function |
| 5 | Search | One search box under a plain question | Existing `landing-search` form | Existing, moved down, new label |
| 6 | More about these records | Three collapsed details: freshness, wards and districts list, how the lookup works | `freshness.lines`, `views.district_rows`, `site.councils[].seats`, `views.lookup_sources` | Existing, moved to the bottom, content unchanged |
| 7 | Footer | Full notice, operator line, Buy Me a Coffee, gnoshcodes credit, About, data date, all-pages menu | `base.html.j2` | Existing; one change as built (owner's iPad check, 2026-11-11): "Data as of" prints its day in words ("November 7, 2026", like the page's other dates) in `<time class="data-as-of" datetime="2026-11-07">`, on every page; `qa/site_checks.py` dates/no-raw-utc-day reads the ISO day from it |

Order rationale: the address box is the one action that makes the site personal, so it leads. Doors come before the
meetings list because the list is short and can be empty; the doors never are.

### 3. The four doors
Each door is a card (not itself a link) holding two links, each a full-width 44px row. Where a door covers both
bodies the links are in alphabetical order (City, then County) in every door, so neither body leads by choice.

| Door | Sentence | Link 1 | Link 2 |
|---|---|---|---|
| Who's in office | The council member for each of {ward_count} city wards and the commissioner for each of {district_count} county districts. | City Council → `city/index.html` | County Commission → `officials.html` |
| How they voted | Each recorded vote, by meeting and by member, linked to the page of the minutes it came from. | City Council votes → `city/index.html` | County Commission votes → `votes/<newest year>.html` (the `Votes` nav href) |
| Meetings and agendas | The agenda before a meeting; the minutes and votes after it, once they are posted. | Day by day → `today.html` | Planning Commission → `rpc/index.html` |
| County money | Montgomery County's budget books, and the bids and awards its purchasing office lists. | County budget → `finance/index.html` | Bids and awards → `contracts/index.html` |

Rules for doors:
- A link is rendered only when its page is built (same conditions as `views._nav`). A door with no links is not
  rendered; the grid reflows (4, 3 or 2 across on desktop).
- The Planning Commission link says nothing about votes (its motions are hidden); the door sentence about votes is
  true for the county and the council only, and the "How they voted" door has no RPC link.
- "County money" says county because no city finance is collected. Do not relabel it "Where the money goes".
- No counts of votes, meetings or people's activity. The only numbers are the ward and district counts.
- Engineer: if `city/index.html` has anchors for its seats list and its meetings/votes list, point the two City
  links at them so they do not land on the same spot.

### 4. Meetings
Data: `days.page(ix, cixs, rpx, fx, today, ax)` already builds every card in the window (4 weeks either side of today)
for `today.html`. The landing needs a selection of it, nothing more. Proposed function (architect/engineer to name):

`days.landing_meetings(page_ctx, today, n=3) -> {"upcoming": [...], "recent": [...], "built": iso, "built_text": str}`

- Flatten `page_ctx["weeks"][].days[]`; take cards with `kind != "bids"`.
- `upcoming`: the first `n` with `day.iso >= today`, soonest first. `recent`: the last `n` with `day.iso < today`,
  newest first. Cancelled cards (`cancelled`) are kept and marked, not dropped.
- Each row carries: `iso`, `dow`, `n`, `month`, `day.text` (for the screen-reader label), `card.body`, `card.title`
  (may be None for RPC cards: show the body alone), `card.dot`, chip, and `href = "today.html#" + day.anchor`.
- Chip, from fields the card already has, in the words `today.html` uses: `cancelled` → "Cancelled";
  `state == "scheduled"` → "Scheduled"; `state == "votes"` → "Votes"; `state == "agenda"` → "Agenda"; else no chip.
- An RPC row can only ever show "Agenda", "Cancelled" or no chip, because `rpc_card` never sets `state == "votes"`.
  Nothing on the landing shows an RPC motion or vote.

Each row is one link (date block, body, kind, chip) to that day on `today.html`, where the card links the source PDF
and carries "Unofficial copy. Official record:". So every row's source is two taps away at most and nothing is
restated on the landing beyond the body, the meeting kind and the date.

Sample values in the mock (from `build/site/today.html`, built 2026-11-11):
- Coming up: Tue Dec 1 Clarksville City Council, Executive session, Scheduled; Thu Dec 3 Clarksville City Council,
  Regular session, Scheduled.
- Most recent: Mon Nov 9 Montgomery County Commission, Formal meeting, Agenda; Thu Nov 5 Clarksville City Council,
  Regular session, Agenda; Mon Nov 2 Montgomery County Commission, Informal meeting, Agenda.

Why not a literal "This week" strip: in the current build the week of Nov 8 to 14 holds one meeting (Nov 9) and
nothing after today, so a week strip would be six empty days. "Coming up / Most recent" always has something to show
when the records do, and says so plainly when they do not.

## States

| State | What the page does |
|---|---|
| Normal | As in the mock. |
| No upcoming meetings in the window | The "Coming up" column keeps its heading and shows: "No upcoming meetings are in these records yet. A meeting appears here once its body posts an agenda or lists a date." The footnote and the "All meetings, day by day" link stay. |
| No recent meetings in the window | Same pattern: "No meetings in the last four weeks are in these records." |
| Both empty | The section shows one line: "No meetings from the last four weeks or the next four are in these records." and the day-by-day link. The section is not hidden, so its absence is never ambiguous. |
| Data stale (page not rebuilt) | The sub-line always prints the build date ("As of November 11, 2026"), so the lists are honest without script. With script: a small addition to `static/sky.js` (or a new `landing.js`; no inline script, CSP) compares today in `site_timezone` with `data-built`. If they differ, it moves any "Coming up" row whose date has passed into "Most recent", and if the build is more than 2 days old it shows "This list was built on {built_text}; later meetings appear when it is built again." (same wording as `today.html` `#days-out`). The footer's "Data as of" line is unchanged. *As built:* the script is `static/landing.js`; up to 6 spare upcoming rows are built hidden and shown in turn as rows move, so "Coming up" stays full; a moved row drops its "Scheduled" chip (it said the meeting was ahead) and keeps "Agenda" (the agenda is still posted). |
| No script | Address form stays hidden (as today). The card then shows the heading, "Pick your ward or district from the list" linking `#wards-districts`, and the GoVoteTN link (`district_lookup_url`). Sky date line absent (as today). Meetings and doors are plain links and work. |
| No geocoder build (`address` is None) | Same as no script: the card shows the list link only, and the wards and districts details is open by default (as today). |
| Address lookup: loading, found, not found, outside the county, geocoder down | Unchanged: `static/address.js` and `#addr-result` (role="status"). The result renders inside the card, directly under the input. |
| Returning visitor with saved seats | "Your seats" (existing section, existing Forget button) renders at the top of the card, above the input. |
| A door's page is not built | That link is omitted; a door with no links is omitted. |
| Fixture build | Unchanged banner; same components on fixture data. |

## Copy

| Where | Text |
|---|---|
| h1 | Your city and county government, on the record. |
| Lede | See who represents you, how they voted, when they meet and how the county spends money. Every fact links to the official document it came from. |
| Unofficial line | Independent, unofficial: not from or endorsed by any government body. [About this site] (→ `about.html#unofficial`). This is the existing `unofficial.email_line` wording. |
| Address heading | Find who represents you |
| Address label | Enter your street address to see your city ward and county district. (district only when wards are not live) |
| Address button, placeholder, privacy line | Unchanged: "Find", "Street address, city", "Your address is sent to ... This site doesn't store it. ... privacy policy applies." |
| Address alternative | Or pick from the list of 12 wards and 21 districts |
| Doors heading | Start here |
| Meetings heading / sub | Meetings / As of {built_text}. Tap a meeting for its agenda, minutes and votes. |
| Column heads | Coming up / Most recent |
| Meetings footnote | Only meetings in these records are listed: a meeting appears once its body posts an agenda or lists a date. Each body's own calendar is the official schedule. [What is and is not collected] (→ `today.html#day-bodies-h`) |
| Meetings link | All meetings, day by day |
| Search heading / label | Looking for something specific? / Search by street, name, topic or item number. |
| Search placeholder | Keep the current "Search: item, number, name or street" unless the Focus Group prefers an example; the mock shows "For example: Rossview Road" (a street in a real bid title). |
| Details summaries | How recent the records are / All 12 wards and 21 districts, as a list / How the address lookup works, and what is saved |

Alternative h1 for the Focus Group: "Local government records for Clarksville and Montgomery County." (plainer,
less of a slogan). Neither names or characterises any person or body.

Copy rules kept: no text about a named official anywhere on the landing; no adjectives about any body; meeting kinds
and body names are the record's own labels (`kind_labels`, `body_name`).

## Removed or moved

| Element today | v2 |
|---|---|
| h1 scope sentence (`site.purpose`) | Removed from the landing. Keep `purpose_line` for the meta description or About; the lede replaces it for readers. |
| Date ranges line (`purpose-sub`: "2020-02-10 to 2026-05-11. City Council: 2016 to 2026.") | Removed. The same facts are in "How recent the records are" and on About. |
| Bold "Independent, unofficial. Not affiliated with or endorsed by ..." line (`home_line`) | Replaced by the one short muted line in the welcome. The header tag stays. |
| Full notice box in the footer | Stays (every page). It is no longer on the first screen beside the short line, which is what read as "twice". |
| Address box label "Find your ward and county district by address" | Reworded; box moved into a card with its own heading. |
| Second address note ("After a lookup, only the district and ward numbers are kept ...") | Moved into the "How the address lookup works, and what is saved" details. The first privacy line stays under the input and stays `aria-describedby`. |
| "Not sure of your district? Look it up on GoVoteTN" line | Kept only inside the privacy line (where it already is) and in the no-script fallback. |
| Search box | Moved below the meetings, with a visible heading and label. |
| Freshness details, wards and districts details, lookup details | Moved to the bottom under one rule; content unchanged. |
| Landing-only compact footer CSS (`.page-landing .site-footer` one-screen rules) | Removed; the landing uses the normal footer, so Buy Me a Coffee is the pill button on phones too. |

## Acceptance criteria this satisfies (from the brief)
- Friendlier, less intimidating first screen: sections 1 and 2 (one sentence, one action).
- Sense of what is happening: section 4. Where to start: sections 2 and 3.
- Built from existing data: every section's source is listed above; one selection function over `days.page()`.
- Neutral, every official the same: no official is named on the landing except in the existing wards and districts
  list, where every seat has the same row. No scores, rankings or counts of activity.
- No RPC votes: RPC appears as a door link and as agenda rows only.
- No placeholder data: empty states say so; nothing is invented to fill a column.
- "Independent, unofficial" visible on the landing: header tag and welcome line on the first screen; full notice in the footer.
- Footer keeps Buy Me a Coffee and the gnoshcodes credit: unchanged.

## Accessibility (WCAG 2.2 AA)
- Heading order: h1 welcome; h2 Find who represents you, Start here, Meetings, Looking for something specific?;
  h3 for each door and for Coming up / Most recent. The freshness summary's h2 becomes plain summary text (or stays
  h2; not both patterns in one group).
- Keyboard order equals visual order: skip link, Menu, name plate, date, About link, address input, Find, list link,
  door links (left to right, top to bottom), meeting rows (Coming up, then Most recent), day-by-day link, search
  input, Search, three summaries, footer.
- Targets: every door link, meeting row, button, input and summary is at least 44px tall; meeting rows are 64px.
  Inline links in sentences (About, privacy policy) are exempt as inline text.
- Meeting row accessible name reads date first: "Monday, November 9: Montgomery County Commission, Formal meeting,
  Agenda" (visible date block is `aria-hidden`; a visually hidden full date precedes the body).
- Dots are decorative (`aria-hidden`); the body name is always in text. Chips are text, dashed border, ink on
  surface: no colour carries meaning.
- Contrast: ink on paper 15.9:1, muted on paper 7.0:1, link blue on paper and on white above 7:1, white on button
  blue 8.0:1; the same token pairs as the rest of the site, light and dark. Focus ring is the existing 3px sun ring
  (ink ring on the sky band).
- Focus is never moved on load. After a lookup, focus and the live region behave as today.
- 390px: one column; doors stack; the two meeting columns stack (Coming up first); no sideways scroll; inputs do not
  shrink below 44px height. Text reflows at 200% zoom and 320px.
- Reduced motion: nothing new animates.

## Components
- New: `door` (card with title, sentence, link rows), `meet-row` (date block, body, kind, chip), `find` card wrapper,
  section heading with sub-line (`sec-h`, `sec-sub`), `more` group for the three details.
- Reused: site header and sky hero, name plate, `unofficial-tag`, address form and `#addr-result`, "Your seats",
  `search-row` input and button, `chip chip-status`, `dot dot-*`, `details` blocks (freshness, district list, lookup),
  footer with notice, support pill and gnoshcodes credit.

## Proposed spec and test changes
1. The rule "the landing's `<main>` fits one screen before any lookup" (`daylight/README.md` M2 note;
   `tests/test_address_box.py` `mainBottom <= innerHeight`) cannot hold with doors and meetings. Replace it with: the
   h1, the unofficial line and the address input with its Find button are on the first screen at 375x667 and 1280x800,
   and after a lookup the result is on screen (the existing `resultBottom` check stays).
2. `tests/test_unofficial_first_screen.py`: keep checking the header tag and a short line on the first screen; the
   short line's text changes from `unofficial.short` to the `email_line` wording (id `unofficial-short` in the mock).
3. `site.purpose` stops being the landing h1. Any test asserting the h1 text needs the new copy keys.
4. Assumption recorded: "this week" is read as "coming up and most recent" for the reason given in section 4.

## Recommend
A Focus Group (the primary users are real outside residents) on: the h1 choice (two options above), whether "Start
here" doors or the meetings list should come first on a phone, and whether "Coming up" with only the city's scheduled
dates reads as "the county has no meetings".
