# Design proposal: digest-warmth (a warmer Daylight Digest)

Status: proposal, 2026-11-22. No product code. Mockup: `docs/design/digest-warmth-mockup.html` (three screens,
phone width, light and dark by `prefers-color-scheme`). Builds on `docs/design/daylight-national.md` (sections 0,
0a, 1, 3, 5), which stays the reference for everything this page does not change. Clarksville pages are out of
scope.

Why: the owner's note on the sister morning email applies here: "the goal is to get people interested in their
local government. neither of these are very inviting. very sterile and utilitarian." The theme asked for is
"Your Local Government, in Broad Daylight".

## 1. Concept in plain words

The Digest today reads like a form and a list. The proposal makes it read like a morning: the sun comes up over a
plain horizon at the top of each page, the first words are about the reader's own town, and the page says in two
or three fixed sentences why a council agenda is worth a minute of their time.

Three ideas carry it:

1. **Daybreak.** A small rising-sun band under the header, a warm "morning paper" surface for the hero and the
   key cards, and the brand orange used as light (sun, rays, a card's top edge), never as text or status.
2. **Your town first.** The result greets the place by its Census name: "Clarksville, here's who governs you."
   The pride is in the reader's place and their seat in the room. Nothing on any page praises or rates a
   government or an official.
3. **An invitation, not a lecture.** Short fixed copy says what local governments decide, that meetings are
   generally public, and that reading the agenda is enough to start. The coming-up page leads with one "Next
   meeting" card instead of 45 identical rows.

Everything that makes the Digest trustworthy stays where it is: three plain statuses, verbatim government text,
official links, privacy lines, the Census notice, the unofficial notice.

## 2. Neutrality rules this proposal holds to (spec Rules R1 to R3, Non-goals)

| Rule | How the warm design keeps it |
|---|---|
| Same layout for every government and official (R2) | The greeting is one fixed sentence with a name slot. Every card has the same frame and the same sunrise edge whatever its status. The "Next meeting" card and "Thinking of going?" card appear on every coming-up page with the same words. |
| No scores, rankings, praise or criticism | Warm words are about the reader ("your street", "you can sit in") and about local government in general. No adjective is ever attached to a named place, government or official. No "great", "proud", "hard-working", no superlatives. Status pills stay navy: no green, no red, no orange. |
| Text we write is fixed labels only (R3); no AI text about named officials | Every new sentence below is a fixed label for `config/national/page-labels.yml`, approved once by Brian, identical for every place. The only variable in any of them is a name, date or count the builder or script fills in. No official is named anywhere. |
| Government text verbatim | Meeting names, item text and Census names are printed as today, inside the same `data-feed` spans. No case change. The greeting uses the Census base name as given (section 4). |
| No ads, money ask or campaign link | None added. The hero has no call to action other than the address box. |
| Privacy lines stay | "We never get your address and never sell anything." stays word for word under the address box; the Census line and notice stay word for word. |
| Unofficial notice stays | The header tag and the footer notice are unchanged: "It is not affiliated with, endorsed by, or operated by any government it covers." |

General claims in the new copy and why each holds for every reader:
- "decide things like roads, zoning, schools and local taxes": a description of local government in general,
  hedged with "things like"; it is not said of any one body.
- "Most local government meetings are open to the public": every state has an open meetings law with
  exceptions, so "most", never "all" and never "this meeting is open". The page never says a named meeting is
  open, because we don't hold that fact (a closed session is possible).
- "Where it meets and how to speak are set by the government": true everywhere, and it points to the official
  page instead of promising what that page says.

## 3. Screen 1: home and look-up (`digest/index.html`): US1, US9, AC1.7, AC1.9, AC1.10

Order on a phone:

```
[ existing header, unchanged ]
[ dawn band: sun rising over a horizon ]
DAYLIGHT DIGEST                       eyebrow
Your local government,                h1
in broad daylight.
A city council, a county commission   lede
and a school board meet near you...
+----------------------------------+
| Your street address              |  the address card, lifted onto the hero
| [ 100 Main St, City, State     ] |
| [  Find my local governments   ] |
| (lock) We never get your address |
|        and never sell anything.  |
+----------------------------------+
Your address goes from your browser straight to the Census...
See what we cover first, without typing anything
How it works   1  2  3
[ Why look? ]                         warm card
Daylight Digest is run and paid for by gnoshcodes LLC...  Who runs this
> How this works, and what is saved
Census notice (word for word)
Report an error on this page
[ unofficial notice, footer: unchanged ]
```

### Copy

| Label | Today | Proposed |
|---|---|---|
| `index.eyebrow` (new) | none | Daylight Digest |
| `index.h1` | Find your local governments | Your local government, in broad daylight. |
| `index.title` | Daylight Digest: Find your local governments | unchanged (the title stays the task, for search and tabs) |
| `index.lede` | See every local government for your address: city or town, county, township and school district. We show what we cover and say plainly what we don't. | A city council, a county commission and a school board meet near you, in public, and decide things like roads, zoning, schools and local taxes. Type your address to see who they are and what they take up next. |
| `index.input-label` | Your street address | unchanged |
| `index.placeholder` | 100 Main St, City, State | unchanged |
| `index.find` | Find | Find my local governments |
| `index.privacy` | We never get your address and never sell anything. | unchanged, word for word |
| `index.privacy-detail` | (Census line) | unchanged |
| `index.cover-link` | See what we cover first, without typing anything | unchanged |
| `index.steps-h` (new) | none | How it works |
| `index.step-1` (new) | none | **Type your address.** It goes to the Census Bureau, not to us. |
| `index.step-2` (new) | none | **Meet your local governments.** City or town, county, township and school district, each marked covered, not covered yet or can't cover. |
| `index.step-3` (new) | none | **See what's coming up.** Their next meetings and agendas, in their own words, each linked to the official document. |
| `index.why-h` (new) | none | Why look? |
| `index.why-1` (new) | none | These meetings are where your street, your schools and your local tax bill get decided. The agendas are public records, and most meetings are open to anyone who walks in. |
| `index.why-2` (new) | none | You don't have to speak. Knowing what's on the agenda is a good place to start. |
| `index.who` | (who runs and pays) | unchanged, word for word (Brian approves its facts) |
| `index.toggle-*`, `index.census-notice`, `index.noscript` | | unchanged |

Step 2 keeps the honest part of the old lede ("we say plainly what we don't") by naming all three statuses before
the reader types anything.

### States

| State | What shows |
|---|---|
| Default | As above. |
| No script | The card shows the existing `index.noscript` line in place of the form, on the same lifted card. |
| Empty submit | `lookup.empty`, unchanged, under the input. |
| Looking | Button reads "Looking up..." (`aria-disabled`), status line as today. No animation; the sun does not move. |
| Still looking | Unchanged. |
| Not found (AC1.4) | "We couldn't find that address." stays word for word. The tip line stays. |
| Census down (AC1.6) | Unchanged words and Retry. |
| More than one match | Unchanged picker, heading "Which one is yours?". |

Error and tip text sits on the white card in ink; no dawn colour, no icon that reads as a warning grade.

## 4. Screen 2: look-up result (same page): US2, US5, AC2.x

```
[ header ]
Address looked up. It was not sent to us.     [Look up another]
[ short dawn band ]
CENSUS MATCHED: 1 PUBLIC SQ, CLARKSVILLE, TN, 37040
Clarksville, here's who governs you.          h2, receives focus
We found 3 local governments. 2 covered, 1 we can't cover.
+-- sunrise edge (same on every card) --+
| CITY OR TOWN                          |
| Clarksville city                      |  h3, Census name as given
| Clarksville City Council              |
| (v) Covered                           |
| [      See what's coming up        ]  |  filled button
| Full Daylight pages (votes and ...)   |
| Get the morning note                  |
+---------------------------------------+
... County card, School district card (Can't cover: reason, Checked, official link, [Request it]) ...
Some governments, such as water or transit boards...
Not sure this list is right? ...
[ device box: Forget this list ]
```

### The greeting rule (one rule for every address)

`lookup.greet`: "{place}, here's who governs you."

`{place}` is the Census base name (the geocoder's `BASENAME`, which is the name without "city", "town" or
"village") of the first listed government in the fixed slot order, skipping school districts:

1. the incorporated place ("Clarksville");
2. else the township or town;
3. else the county, with its Census name in full ("Montgomery County");
4. else no name: `lookup.greet-none`, "Here's who governs this address."

The name is printed as the Census gives it. It is the same text already on the first card and already kept on
the device, so nothing new is stored. It is drawn in the page only: never in the URL, the `<title>`, a cookie or
storage beyond today's saved list (AC1.3). No time-of-day greeting ("Good morning") because the page can't know
the reader's hour honestly.

### Copy

| Label | Today | Proposed |
|---|---|---|
| `lookup.list-h` | Local governments for this address | replaced on screen by `lookup.greet`; kept as the heading's fallback (rule 4 uses `lookup.greet-none`) |
| `lookup.greet` (new) | none | {place}, here's who governs you. |
| `lookup.greet-none` (new) | none | Here's who governs this address. |
| `lookup.matched` | Census matched: {line} | unchanged, moved above the greeting as its eyebrow |
| `lookup.summary-*` | We found 3 local governments. 2 covered, 1 we can't cover. | unchanged |
| `lookup.looked-up` (new, only if the form is folded) | none | Address looked up. It was not sent to us. |
| `lookup.another` | Look up another address | unchanged (the mockup's "Look up another" is shortened for the drawing only) |
| `lookup.coming-up` | See what's coming up | unchanged words, now a filled button |
| `lookup.summary-none` (warm empty state: nothing covered) | None are covered yet. Request the ones you want and we'll email you if one opens. | We don't read any of these yet. Each card links to the government's own agenda page, so you can still see what's coming up there. Request the ones you want and we'll email you if one opens. |
| `lookup.summary-none-one` | It is not covered. Request it and we'll email you if it opens. | We don't read this one yet. Its card links to the government's own agenda page where we have the link. Request it and we'll email you if it opens. |
| `lookup.nothing-listable` (AC2.13) | The Census found this address, but we can't list a local government for it yet. | unchanged; shown under `lookup.greet-none` with the small sun mark, not as an error |
| All card labels, reason lines, `lookup.under-list`, `lookup.election`, device lines, the request form | | unchanged |

The warm empty state says "we don't read", so the gap is plainly ours and says nothing about the government.

### Card changes (same for all three statuses)

- A 5px sunrise edge (orange to pale) replaces the navy top edge on every card. It never varies by status.
- Card title one step larger (`--t-xl`).
- The one primary action is a full-width button: filled navy "See what's coming up" (Covered), outlined navy
  "Request it" (the other two, as today). Secondary links keep their 44px rows.
- Pills, reason line, "Checked {date}. Source", official link: unchanged.

### Folding the form after a result (optional, engineer's call with the architect)

Today the whole intro and form stay above the list, so the result starts two screens down. Proposal: once a list
is shown, the hero and form fold to one row ("Address looked up. It was not sent to us." and "Look up another
address", which unfolds the form and moves focus to the input). If that is more script than the team wants now,
skip it: the greeting, band and cards work without it, and focus already moves to the list.

## 5. Screen 3: a government's coming-up page (`digest/<st>/<id>.html`): US4

```
[ header ] [ short dawn band ]
DAYLIGHT DIGEST / WHAT WE COVER
TENNESSEE . CITY OR TOWN
Clarksville City Council                      h1
Coming up
Unofficial copy. Official record: clarksvilletn.portal.civicclerk.com.
We got our newest record on November 17, 2026.
+----------------------------------+
| (sun) NEXT MEETING               |
| Tuesday, December 1, 2026        |  h2
| Executive session                |
| We don't have a start time ...   |
| Agenda not posted yet. Official  |
| meetings page                    |
| [ items, verbatim, when posted ] |
+----------------------------------+
[ Thinking of going? ]                        warm card, same on every page
DECEMBER 2026
[Thu 3]  Thursday, December 3, 2026 / Regular session / Agenda not posted yet. Official meetings page
JANUARY 2027
[Tue 5] ... [Thu 7] ... [Thu 28] ...
> Show 40 later meetings, February 2027 to November 2029
Votes and past meetings are on the full Daylight pages.
[ Get the morning note ]
Report an error on this page
```

### What changes

1. **"Next meeting" card.** The soonest meeting is lifted into one card with the sun mark and the fixed label
   "Next meeting". Same fields, same order, same words as any other meeting; its agenda items print inside it
   exactly as today. Every government's page gets it (AC4.9). It carries no countdown ("in 9 days"): the page is
   built once a day and a stale count would be a wrong fact.
2. **Months.** Later meetings are grouped under month headings and drawn as compact rows with a small date
   chip. The chip repeats the date for the eye and is `aria-hidden`; the full date stays as heading text.
3. **Fold the far future.** Meetings after the first three calendar months that have a meeting sit in a native
   `<details>` ("Show {n} later meetings, {first month} to {last month}"). They remain page text and stay in
   order, so AC4.1 ("lists every meeting") still holds; see proposed spec change 3.
4. **Say "no start time" once.** When no meeting on the page has a start time, `body.no-time-all` shows once
   under the list instead of `body.no-time` under every meeting. When some have times, today's per-meeting line
   stays. One rule for every government.
5. **"Thinking of going?" card.** Fixed, identical on every coming-up page, linked to the government's official
   meetings page (omitted, like the official line, when the directory has no checked link).

### Copy

| Label | Today | Proposed |
|---|---|---|
| `body.next` (new) | none | Next meeting |
| `body.later-h` (new, screen readers only) | none | Later meetings |
| `body.more` (new) | none | Show {n} later meetings, {from} to {to} |
| `body.no-time-all` (new) | none | We don't have start times for this government's meetings. |
| `body.going-h` (new) | none | Thinking of going? |
| `body.going` (new) | none | Most local government meetings are open to the public, and you can sit in without speaking. Where it meets and how to speak are set by the government. Start at its [official meetings page]. |
| `body.no-meetings` (warm empty state) | No upcoming meetings are posted. [Official meetings page] | No upcoming meetings are posted. New ones show here after the government posts them and we read them. [Official meetings page] |
| `body.no-records` | We have no records for this government yet. | unchanged |
| `body.not-posted`, `body.incomplete`, `body.withheld`, `body.cut`, `body.official-record`, `body.newest`, `body.full`, `body.morning`, topic labels | | unchanged, word for word |

Empty state drawing: the "Next meeting" card is replaced by a card of the same size holding the small sun mark
and the `body.no-meetings` line; "Thinking of going?" still shows. The freshness line stays above, so silence
never looks like a fault.

"Agenda not posted yet" stays plain. It is a fact about the record; dressing it up would either blame the
government or promise a date.

## 6. Visual changes

### Colour

Three new tokens, in `digest.css` only (no change to `style.css`, so Clarksville pages are untouched):

| Token | Light | Dark | Use |
|---|---|---|---|
| `--dawn` | `#FFF3E4` | `#231A22` | hero, greeting and page-head surface; warm cards; date chips |
| `--dawn-2` | `#FFE3C7` | `#3A2420` | horizon glow in the band; step numbers; the soft shadow under lifted cards; the h1 underline wash |
| `--dawn-line` | `#F0C9A6` | `#5A3A2C` | decorative edge of a dawn surface |

Contrast (my arithmetic; the engineer re-runs the repo's contrast check before review):

| Pair | Light | Dark |
|---|---|---|
| `--fg` on `--dawn` | about 15.9:1 | about 14.8:1 |
| `--muted` on `--dawn` | about 6.9:1 | about 7.4:1 |
| `--link` on `--dawn` | about 15:1 | about 8:1 |
| `--fg` on `--dawn-2` | about 14:1 | about 12.7:1 |
| `--muted` on `--dawn-2` | about 6.1:1 | about 6.3:1 |

Orange rule, restated for the Digest: `--sun` may be the sun, its rays and the card edge (all decoration, all
`aria-hidden`), and stays the focus ring. It is still never text: `--seal` on `--dawn` is about 4.5:1, too close
to the line, so no orange type anywhere. It never marks a status. No red or green, as today.

### Type

Same families (Outfit, Inter, JetBrains Mono). Changes: hero `h1` and the greeting at about 2.1rem / 1.85rem,
weight 800; lede 1.125rem; card titles `--t-xl`; address label becomes a `--t-lg` Outfit heading; input and
primary buttons 52px tall with 1.0625rem text. Sentences a person must read (privacy, notice, reasons) are 1rem;
`--t-sm` (14.4px) stays only for hints that are muted today ("Checked", "We'll email you if it opens", the
device line, the Census notice).

### Imagery

No photographs, no stock art, no real skyline, seal or landmark. Two inline SVGs, both `aria-hidden`:

- **Dawn band** (96px on the home page, 56px elsewhere): a half sun with seven rays over one curved ground
  line. The home band adds a plain row of rooftops with one cupola, drawn from rectangles and triangles so it
  can't be read as any real building. If anyone on the Focus Group reads it as a specific courthouse, drop the
  rooftops; the sun and horizon carry the idea alone.
- **Sun mark** (32 by 20): the same half sun on a short horizon, beside "Why look?" and "Next meeting" and in
  the empty states.

The header's own sun and sky stay as they are. No animation anywhere (and so nothing to gate behind
`prefers-reduced-motion`).

### Accessibility (WCAG 2.2 AA)

- One `h1` per page. Result: the greeting is the list's `h2` and takes focus as `#digest-list` does today; the
  status region still announces the summary line. Coming-up: `h1` government, `h2` "Next meeting" date, `h2`
  "Later meetings" (visually hidden), `h3` each month, `h4` each meeting date; agenda items one level under
  their meeting. This is a heading-level change from today (meeting `h2`, item `h3`); tests that pin levels
  need updating.
- Every control 44px or taller; primary buttons 52px. Focus ring unchanged (3px `--focus`, 2px offset); it is
  about 3.8:1 on `--dawn`, above the 3:1 bar, to be confirmed by the check.
- Links stay underlined. Statuses stay told by word, mark and edge. Forced-colors: the band and edges drop out,
  borders and words remain.
- 320px and 200% text: the lifted card loses its overlap (margin 0), date chips drop above their rows, buttons
  stay full width. No sideways scroll.
- Dark mode: all three dawn tokens have dark values; the band becomes a dim pre-dawn glow, not a bright stripe.

## 7. What stays the same

- The header, Menu, "Independent, unofficial" tag, footer and the Digest unofficial notice, word for word.
- The three statuses, their pills, their order, and the fixed slot order of cards.
- Every privacy line, the Census line and notice, the how-it-works toggle, the request form and its honest
  lines, the counter, the device box, "Report an error".
- All government and Census text verbatim; every official link; the freshness line; topic chips.
- The address never reaching Daylight (R7): nothing new is sent, stored or put in a URL.
- `style.css`, the Clarksville pages, the morning note.
- No ads, no money ask on Digest content, no campaign link, no named officials.

## 8. Changes an engineer would make

`config/national/page-labels.yml`
- Change: `index.h1`, `index.lede`, `index.find`, `lookup.summary-none`, `lookup.summary-none-one`,
  `body.no-meetings`.
- Add: `index.eyebrow`, `index.steps-h`, `index.step-1..3` (bold lead plus sentence; either two keys each or a
  `**lead**` marker the builder understands), `index.why-h`, `index.why-1`, `index.why-2`, `lookup.greet`,
  `lookup.greet-none`, `lookup.looked-up` (only with the fold), `body.next`, `body.later-h`, `body.more`,
  `body.no-time-all`, `body.going-h`, `body.going`.
- `sitegen/national_pages.py`: add the new keys to the known-key list; `tests/test_national_pages.py` lists them.

`site/templates/digest/index.html.j2`
- Inline dawn-band SVG and a `.digest-hero` wrapper around eyebrow, `h1`, lede.
- Move `index.who` and `index.cover-link` below the address card (needs spec changes 1 and 2; if refused, leave
  both between the lede and the card at `--t-sm`).
- Add the steps list and the "Why look?" card after the privacy detail.

`site/static/national.js`
- Heading of the list: `lookup.greet` with the base name by the rule in section 4, else `lookup.greet-none`.
  The page directory or the Census answer must carry the base name; if only the full Census name is on hand,
  the architect decides whether to read `BASENAME` from the geocoder answer (already in the frame's response).
- Print `lookup.matched` above the heading. Make "See what's coming up" a `.digest-primary` button.
- Optional fold of the form after a result.

`site/templates/digest/body.html.j2` and `sitegen/national_pages.py`
- Short dawn band and `.digest-bodyhead` wrapper.
- `meeting_view` output split into `next` (first meeting), `months` (groups for the rows) and `later` (the
  folded rest), all still `section.digest-meeting` with the same `data-feed` spans, in the JSON's order, so the
  site checks that exempt feed text keep working.
- `no_time_all` flag; `body.going` card with the `official` link.
- Heading levels as in section 6.

`site/static/digest.css`
- The three dawn tokens (light and dark), `.digest-hero`, `.digest-dawn` (band), `.digest-warm` (card),
  `.digest-steps`, `.digest-next`, `.digest-month`, `.digest-datechip`, `.digest-primary`; the sunrise edge on
  `.digest-card`; larger `h1`/greeting; lifted `.digest-find`. Update the file's header comment: orange is now
  the sun, rays, card edge and focus ring; still never text or status.

Checks and docs
- `qa/site_checks.py`: heading-level and fixed-string expectations for digest pages; the label inventory
  (AC4.8) gains the new labels.
- `docs/design/daylight-national.md` 0a: note that this proposal supersedes "no orange fill or border on a
  digest page" for decoration only.
- Accessibility scan and contrast check on all three pages, light and dark.

## 9. Proposed spec changes (`docs/specs/daylight-national.md`)

1. **AC1.9** says the who-runs-it line sits above the address box. Proposed: "on the entry page, in view without
   opening anything, directly after the address card and its privacy lines". Reason: three paragraphs before the
   box is most of what makes the page read as a disclosure form. The words do not change. If the Brain Trust's
   reason for "above" was trust before typing, keep it above at small size instead; the design works either way.
2. **AC1.10** says the "What we cover" link sits above the address box. Proposed: "next to the address card"
   (the line directly under its privacy detail). Same fallback.
3. **AC4.1** "lists every meeting from today on". Proposed addition: "Meetings beyond the first three months
   shown may sit in a closed native toggle on the same page." All meetings remain page text.
4. **AC2.2 / design 0a** "no orange fill or border on a digest page": relax to "orange is decoration (sun, rays,
   card edge) and the focus ring; never text, never a status".
5. **AC4.9 / AC4.8**: no change needed, but note the "Next meeting" and "Thinking of going?" labels join the
   label file and appear on every coming-up page.

## 10. Assumptions and open points

- The Census geocoder answer includes `BASENAME` for places and county subdivisions. Unverified here; the
  architect confirms. Fallback: print the full Census name ("Clarksville city, here's who governs you." reads
  badly), so if `BASENAME` is unavailable use `lookup.greet-none` for every address rather than trimming names
  ourselves.
- Mockup data is read from the preview screenshots. The meeting count in the toggle (40) and the record host
  are illustrative.
- "here's who governs you" is the owner's example wording. A cooler alternative with the same rule: "{place}:
  your local governments." Worth putting both in front of the Focus Group.
- The preview screenshot of the look-up result shows the Clarksville version of the footer notice on a Digest
  page; the index shows the Digest version. The mockup uses the Digest version on all three. Not part of this
  proposal, but worth a check that every Digest page prints the Digest notice.
- The footer's long Clarksville page list makes every Digest page end in two screens of Clarksville links. Out
  of scope here; a later pass could fold it on Digest pages.

## 11. Recommended panel

Focus Group (6, public work), on the mockup and copy: residents outside Tennessee, one who distrusts
civic-tech sites, one screen-reader user, one local clerk or official on the receiving end, plus a devil's
advocate arguing the warm copy is advocacy. Questions: does the greeting feel welcoming or presumptuous; does
"Why look?" read as neutral; does anyone read the rooftops as a real building; "here's who governs you" against
"your local governments"; who line above or below the box.
