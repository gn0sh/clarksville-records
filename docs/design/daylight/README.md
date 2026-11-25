# Daylight: chosen design (Brian, 2026-11-09 7:46 PM CT)

Brian picked "Daylight" out of six showcase designs: "Daylight wins for me."
- Live mock: https://claude.ai/artifact/HjVfKAzch7AeXL2ERFnfN8
- Source: `daylight-mock.html` in this folder. It holds sample data only, so never ship it as is.

## Decisions (manager, 2026-11-09)
- Daylight is the design target for the real site and replaces the A/B plan. The two contractor pitches in `../ab-candidates/` are kept for reference.
- "Daylight" is the working product name, shown with the locality ("Daylight / Clarksville-Montgomery County"). Assumption: the name still needs a trademark and domain check before go-live, which goes in the go-live asks.
- Build order:
  - M1: tokens, fonts, name plate, footer and landing (sky hero, address bar, Your seats) on the real data.
  - M2: week strip and day cards (agenda before, votes and roll call after), from data we already have.
  - M3: morning-note alerts sign-up, finance and contracts styling.
  - A mock feature with no real data behind it is left out, not faked.
- The rules don't change: every fact links its source, there's an "Unofficial copy. Official record:" line, votes come only from the record, there's no AI text about named officials, the CSP allows no inline script, and phone pages have no sideways scroll.

## M2 as built (frontend, 2026-11-10)
- The week strip and day cards are their own page, `today.html` ("Today" in the menu; today's date on the landing sky links it), not a band under the landing: before any lookup the landing's welcome h1, its short unofficial line and the address input with its Find button are on the first screen at 375x667 and 1280x800 (front-page-v2, 2026-11-11: the whole `<main>` no longer has to fit), with the address answer on it after one, and the header's "Independent, unofficial" tag on it (tests/test_address_box.py, tests/test_unofficial_first_screen.py). Since 2026-11-10 the footer, which carries the full independent and unofficial notice on every page, may start below that first screen. Window: config/site.yml `days` (Sunday weeks, 4 before and 4 after today in `site_timezone`), rebuilt by the daily update.
- Left out, no data behind them: meeting times and places, "Your seat voted" lines, "near you" tags and the transcript, morning note and money bands (M3). The school board is a "Coming" line with one link (`school_board.url`, the district home page until a person confirms the board page's URL; cmcss.net is never fetched).

## Palette: gnoshcodes navy and orange (Brian, 2026-11-12)
Daylight's color is now the gnoshcodes brand pair, not the mock's Digital blue `#2B4BA5` and Human orange `#EF5E35`
(`daylight-mock.html` still shows the old pair; it is the layout reference only). Tokens live in
`site/static/style.css`; the contrast pairs are tested in `tests/test_daylight.py`, and the site check
`brand/no-old-daylight-colors` fails a build that still carries either old hex.

| Token | Light | Dark | Role |
|---|---|---|---|
| `--link` | `#0F1F3D` navy | `#A9BDE6` | links |
| `--blue` / `--on-blue` | `#0F1F3D` / `#FFFFFF` | `#4F6FB0` / `#FFFFFF` | buttons, pills |
| `--blue-hover` | `#33497A` | `#3F5C98` | a button under the pointer (plus an underline); white on it 8.84:1 light, 6.57:1 dark |
| `--band-bg` / `--band-fg` / `--band-muted` | `#0F1F3D` / `#FFFFFF` / `#D5DCEA` | `#1A2F5A` / `#EEF1F8` / `#C3CCDE` | at-a-glance band, morning-note card |
| `--sun`, `--focus` | `#D2561B` orange | `#D2561B` | the sun, plate dot, county dot, focus rings; never text |
| `--halo` | `#EFC4AF` | `#703420` | ring around the sun |
| `--seal` | `#C24A14` | `#E8702A` | orange for text and the initials ring (the hook logo's own dark and light oranges) |
| `--sky` | `#D5DFF0` | `#15294F` | top of the sky band |
| `--surface-2` | `#E9EDF5` | `#1B2443` | wash |

- Navy on the dark page would vanish (1.1:1 on `--bg`), so dark-mode links, buttons, band and sky are lighter navy tints.
- The orange is about 4:1 on the paper: enough for rings and dots (3:1), not for words. Orange text uses `--seal`.
- Paper, ink, muted, line and the vote-mark inks are unchanged: they were already navy-leaning neutrals.
- Navy links sit close to the ink, so a link is told apart by its underline, never by color alone: the landing's door links and the ward and district lists are underlined at rest too.

## "Show records from" switch (Brian, 2026-11-12)
Approved mock: https://claude.ai/artifact/S5MRzw7J6fi4sY2Kqm4GjB. Four public bodies share the site, and residents mix
them up, so every page carries one switch right under the header: All, Montgomery County, Clarksville, School board
(Coming tag), Planning (RPC). Words, cards and links: `config/site.yml` `switch:`. Code: `sitegen/bodies.py`,
`site/templates/_hub.html.j2`, `site/static/switch.js`. Site check: `switch/on-every-page`. Tests: `tests/test_body_switch.py`.

- Each option is a plain link to that body's hub page (All is the home page), so it works without script. Hubs: the
  county has its own page (`montgomery-county.html`); the City Council home, the RPC home and the school board's
  "coming" page are the other three, each with a kicker and section cards under its lede.
- A present card is shown only when the build makes the page it links. A coming card is dashed, carries the Coming tag,
  says what is not collected and links the body's own page: always a URL already in the config (a dotted path, never a
  second copy). No budget page of the city or the school system is in the config, so those cards and the Finance
  page's top line link each body's home page and say "website", not "budget page".
- Wide: a segmented pill group, the chosen option `--blue` with a `--sun` bar under it. Under 700px: one row of 44px
  chips that scrolls sideways inside its own box; "Planning (RPC)" shows as "RPC" (the full label stays for screen readers).
- One header on every body's landing page (Brian, 2026-11-14; `_hub.html.j2` `body_head`, `tests/test_body_switch.py`): the same header pane as every page (name plate, tag and date line, no coverage line), then kicker, h1, one-sentence lede, coverage line, "How recent the records are", Watch, then the cards; a row is left out only when the body has no such fact (the school board has no dates and no Watch).
- With script the choice is kept on the device (`localStorage["cr-body"]`, a body key only; inside try/catch, and the
  page still filters when storage is blocked). Rows that carry `data-body` are hidden by the class `bs-off`, never
  removed, under a "Showing Clarksville only / Show all" line. Visiting a body's hub makes it the choice.
  A click stays on the page only when the page has rows of that body; otherwise it goes to the hub.
- Tagged: the day page's cards and week-strip dots, the home page's meeting rows, Meetings, Votes (every year), the
  Finance index's books and funds, and Search (the choice applies while no Body box is ticked; it is not written to the
  URL). Not tagged, so never filtered: Items, Officials, district, member, meeting, fund, capital, bids and transcript
  pages, and each body's own pages.

## The moon (Brian, 2026-11-14; redrawn 2026-11-18, next section)
The moon is real: `static/sky.js` works out, for the current instant and for Clarksville (36.53 N, 87.36 W), the
moon's altitude, compass direction, lit fraction, waxing or waning, and the tilt of its bright edge, and draws it in
the header of every page.

- Open sky only (manager's design call, 2026-11-14): the moon never covers the header's words. A first version let a
  20px moon pass behind the date and the name plate, where it read as a glitch and its phase could not be seen. The
  script measures the header (each line's own extent and the Menu column) and takes the largest open rectangle of
  the band, which is right of the words. It is measured again on resize and when the web fonts arrive.
- Place inside that rectangle: height is the real altitude (its bottom is the horizon, its top straight overhead);
  across it, east is on the left, south in the middle, west on the right (azimuth 60 to 300 degrees), as the sun
  travels. Hidden below the horizon, and without script (a static page cannot know where the moon is).
- A phone's band is short, so there the rectangle is small (the moon moves a little). If it has no room the moon is
  drawn at 22px, and failing that not at all.
- The almanac is the Astronomical Almanac's short series, on the device: no network call, no storage, no location
  request. The whole sky (sun, date line, moon) is redrawn on page load, on `pageshow`, every five minutes and when
  the tab is looked at again.
- Checked against PyEphem in `tests/test_moon.py` (14 fixed instants in 2026): altitude and direction within 0.4
  degrees, lit fraction within 0.2%, bright edge within about 3 degrees. The same file checks in a browser, at 375
  and 1280, that the moon touches no word of the header.

## One header, and the sun or the moon (Brian, 2026-11-18)
Brian: "i really like the date at the top of the page, but it isn't on all the pages. i think the header pane should
be consistent across the whole site. Also, i don't like how the moon looks. The moon and sun should never be on the
page at the same time, and the moon should be represented as it looks.. not a whole moon with a shadow."

- One header pane: `site/templates/_header.html.j2`, included by `base.html.j2`, is the same markup on every page:
  the sky, Menu, the name plate, the unofficial tag and the date line ("Wednesday in Clarksville November 18",
  the date linked to `today.html`). Only the way back to the site's top folder differs with the page's depth. This
  replaces the three headers of 2026-11-16 (home with the date; a body's landing page with the full sun and no
  date; every other page with the small sun, `sky-small`, which is gone). Every page's head loads
  `static/js-flag.js`, so the date line keeps its space before the script fills it. The site has no error pages.
  Site check `header/same-on-every-page`; tests `tests/test_header.py`, `tests/test_daylight.py`,
  `tests/test_body_switch.py`.
- Never both. The sky is Clarksville's real sky at this instant. The sun is drawn from the almanac's sunrise to its
  sunset there (its top edge on the horizon: the disc's middle 0.833 degrees under it), 0 on the horizon and at the
  top of its arc at local noon, winter and summer alike. After sunset no sun is drawn at all, not its disc and not
  the ring that used to glow over the horizon (`data-at="down"`; with script the sun is also not drawn until the
  script has placed it), and the moon is drawn if it is above the horizon. By day there is no moon, even when the
  real one is up. At night with the moon down, or new, the sky is empty.
- This changes the sun's rule (manager's brief, 2026-11-18): it used to follow the viewer's own clock on a fixed
  6 AM to 7 PM day, which put a sun in the sky up to two and a half hours after the real sunset, so "never both"
  could not be decided from it. A reader in another time zone now sees Clarksville's sky, as the date line already
  showed Clarksville's date. A site with no `sky_place` has no moon and keeps the clock sun.
- The moon as it looks: only the lit part is drawn, a crescent, a half, a gibbous shape or the full disc, from the
  real lit fraction and turned to the real bright edge. The unlit part is not drawn: no faint disc and no ring
  around the whole moon. The shape is never padded (a thin crescent is thin; it was 6% at least), and under 1% lit,
  the day or so around new moon, nothing is drawn, as nothing can be seen in the real sky.
- The shape (manager review, 2026-11-18): the outer edge is always half of the moon's own circle, pole to pole. The
  terminator joins the same two poles: half an ellipse as tall as the disc and `|1 - 2 x lit fraction|` of its
  radius wide, bowing toward the bright edge for a crescent and away from it past half, and a straight line at
  half (a half disc). The drawn area is the lit share of the disc. The whole shape is then turned to the real
  bright edge, so a quarter moon is a half disc that leans toward where the sun is: nearly upright on an August
  evening (2026-08-19, bright edge 98 degrees from up), lit from below (a bowl) when a last quarter rises after
  midnight (2026-12-01, 2 AM, 164 degrees the other way; PyEphem agrees, `tests/test_moon.py` REFERENCE).
- Look: 28px on a phone, 40px at 1280. The lit part is `--moon` with a hairline `--moon-edge` (white with a navy
  edge on the light sky, pale on the dark one) and a soft glow that follows its shape (`--moon-ring`, a drop
  shadow). No animation; the sun slides only under `prefers-reduced-motion: no-preference`. Decorative:
  `aria-hidden`.
- Checked against PyEphem in `tests/test_moon.py`: the sun's altitude within 0.012 degrees through 2026 and its
  sunrise and sunset within 3 seconds on six days; a year of renders every 97 minutes never draws both; and in a
  browser, at 375 and 1280 on three pages, the sun or the moon or neither as the sky has it, the painted moon is
  about its lit share of the disc and its unlit side is plain sky.

## The weather in the sky (Brian, 2026-11-23)

Brian: "if it's raining in Clarksville, it would be cool if the top of the Daylight page had rain also", then: the
header should show whatever Clarksville's weather is, as a small set of scenes.

- **Source.** The National Weather Service's latest observation for Clarksville's airport (station KCKV), asked from
  the visitor's browser: `config/site.yml` `sky_weather` (station and address; `sitegen/weather.py`). The page carries
  the address as `data-weather` on `#sky-moon`, and the CSP's `connect-src` names that one origin (before the visitor
  counter's when both apply). Pages without the sky place (the Daylight Digest) ask nothing.
- **Scenes.** One table, `SCENES` in `site/static/sky.js`, in order of precedence: `storm`, `snow`, `rain`, `fog`,
  `overcast`, `partly`, `windy`, `clear`. `weatherScene(observation, now)` reads the reported weather codes (or the
  description's words when none are listed), the fullest cloud layer, the wind and the visibility, and returns the
  first scene that holds, with an intensity (light, moderate, heavy) for what falls and a `windy` modifier (sustained
  20 mph or gusts of 30) that makes any scene move faster. Freezing rain is rain; sleet and rain mixed with snow are
  snow; broken cloud counts as overcast, scattered as partly, a few clouds as clear. A new scene is one row in the
  table and one block in `style.css` under `.has-sky[data-wx="<id>"]`.
- **Never old weather.** An observation over 90 minutes old, an error, an answer that is not JSON or no answer in 5
  seconds draws the plain sky. One request per page view, never retried, and nothing stored (the browser's own
  cache answers the next page while the service's answer is current); an open tab stops drawing an observation once
  it is 90 minutes old.
- **Drawing: on the sun or the moon (Brian, 2026-11-24).** "I meant up in the top panel where the masthead is. It
  would incorporate the sun and moon that are already there." So the weather is not a sky of its own: the body that
  is up shows it. The script adds one small drawing (`#sky-wx`, aria-hidden, takes no room) inside the sun while the
  sun is up, or inside the drawn moon at night, and moves it as the sky turns; `data-wx-on` on the header says which
  (`sun`, `moon`, `sky`). A few clouds: one cloud drifting across the disc. Overcast: the disc dimmed, a cloud in
  front and one behind. Rain or snow: the cloud rides higher and three staggered rows of streaks or flakes fall from
  it across the disc (one, two or three rows show for light, moderate, heavy). Fog: a pale haze and two soft bands
  across the disc. Storm: the front cloud is the dark one, with a bolt under it (two flickers every 11 seconds).
  Wind under a clear sky: two streaks blowing past the disc; over any other scene it only speeds things up.
  On the sun the drawing's box is the part of the disc above the horizon, so a low sun keeps its cloud in view. The
  moon is still only its lit part: it gets no round haze (that would draw a disc around a crescent); behind cloud
  or in fog the lit part itself is drawn fainter. The moon still keeps clear of the header's words, and on a page
  that names a weather address it is first tried with more air around it, so its cloud keeps clear too where the
  band has room. That room is kept whether or not there is weather, so the moon does not move when the answer comes
  (review, moon-place/jump-on-weather). A moon with no room in the band is hidden, and its weather with it.
  A clear sky, an old observation or an error draws the plain sun or moon.
- **Colours on the moon (review, wx-visible/light-moon).** In the light theme the moon, the clouds and the rain were
  all white. What is drawn on the moon now has its own two tokens, `--wx-moon-cloud` and `--wx-moon-fall` (a pale
  grey and the cloud grey in the light theme; unchanged in the dark theme). They are as dark as the 4.5:1 rule
  against the muted ink allows (`--moon-edge` would be 1.5:1 against it), so on the white moon they are faint, 1.3
  to 1.6:1, but no longer the moon's own colour.
- **A sun on the horizon (review, wx-host/sun-at-horizon).** The sun's cloud never floats free of it: its top is at
  most a quarter of the cloud's height above the sun's top while something falls, else a bit under half, so over a
  rising or setting sun the cloud sits low on the horizon with it.
- **A night with no moon up.** The earlier design drew the scene over the empty sky too, so a quiet hint is kept:
  the same small cloud (moon-sized, 70% strength, no haze) alone in the open sky toward the right, clear of the
  words, with its rain or snow if any. Nothing else is added to an empty sky.
- **Contrast and motion.** Every colour in the drawing (`--wx-veil`, `--wx-cloud`, `--wx-fog`, `--wx-fall`) is 4.5:1
  or better against the ink and the muted ink in both themes, so a cloud's edge that reaches behind a word cannot
  take it below that; the dark theme's weather is therefore quieter than the light theme's. Motion is CSS transforms
  and opacity only, and only under `prefers-reduced-motion: no-preference`; with reduced motion the drawing is still
  (the rows of rain sit one under the other) and there is no lightning. The shapes are masks from `data:` SVGs in
  the stylesheet; no new file, and nothing new in the CSP.
- **Said on the site.** About (neutrality rule on outside requests) and Method ("What is never done") print
  `sky_weather.disclosure`. Tests: `tests/test_weather.py` (the decision, the request, and in a browser at 390 and
  1280 that the cloud is over the sun or the moon that is up).
- **Not checked from the build machine.** The service could not be reached from the sandbox, so the code follows its
  published observation schema and the tests use fixtures; that the service answers a browser on another site
  (CORS) should be confirmed on the preview before release.
- **After deploy.** Check one live `api.weather.gov` response for `Access-Control-Allow-Origin` and `Cache-Control`.

## Once-over fixes (design review, 2026-11-14)
Problem keys `onceover/...`; tests in `tests/test_onceover.py`.

- Dates: one display form, "May 11, 2026" (`sitegen/localdates.py` `words`, Jinja filter `day_words`, `dayWords` in
  `static/search.js`), for meeting and event dates in headings, ledes, lists and tables. ISO stays in `datetime`
  attributes, URLs, ids, fact ids, downloads, feeds and the search index, and in the lines `qa/site_checks.py` reads
  as ISO: fetch days ("fetched 2026-11-07"), seat records ("seen in roll calls ..."), the district-lines text, the
  "latest meeting collected" line and the official page's totals sentences. Page titles and the morning-note preview
  are unchanged. Text printed by a source is never reformatted.
- Masthead: name plate and tag only, on every page (and, since 2026-11-18, today's date under them). Each page
  names its body and dates in its own lede.
- Headings: base `h1`/`h2` are Outfit 800, tight tracking, no rule under an `h2`. A class sets size and margin only.
- Smallest type is `--t-eyebrow` (.72rem). The name plate's place line stays .62rem so the plate fits at 375px.
- Touch (`pointer: coarse`): year pills, filter chips and boxes, and a row's Details and Show more are 44px in the
  layout itself (rows are about 20px taller on a touch screen). No invisible hit area is laid over a neighbour: an
  earlier `::after` around Details covered part of the "p. N" source link (`onceover/touch/hit-area-covers-source-link`;
  `tests/touch_targets_browser.js` probes every source link with `elementFromPoint`). The footer's 28px rows are the
  owner's decision.
- Search finds a record by its date in words too ("May 11"), since that is what a result prints. So a bare month or
  number such as "may" or "2024" also matches records by their date; under Relevance those rank last.
- The bids table (`contracts/index.html`): as a table the date may break after the day ("September 30," / "2026") and
  Source is 8rem, so the table fits its box at 1280 (`tests/table_fit_browser.js`); on a phone the date is one line.
- The year or part a page shows is a filled pill (`aria-current`), like the chosen "Show records from" option.
- Rows that lead to a part of the site (doors, hub card rows, district and ward lists, crumbs) stay navy after a
  visit; links to outside sources keep the visited colour.
- A "coming" page says Coming once (the h1's tag) and does not repeat a link its cards already carry.
- The RPC's home: the full name in the kicker, "Regional Planning Commission" as the h1.

## Round 2 polish (Brian approved, 2026-11-14; built 2026-11-16)
Problem keys `onceover/...`; tests in `tests/test_round2_polish.py` unless named.

- The sun is on every page (`onceover/header/sun-on-every-page`; this reverses "other pages have none"). Since
  2026-11-18 it is the same full sky on every page, with the date line ("One header, and the sun or the moon"
  above); the small sun (`sky-small`) of this round is gone.
  Tests: `tests/test_body_switch.py`, `tests/test_daylight.py`, `tests/test_moon.py`, `tests/test_header.py`.
- Checking counts are one small sentence (`.stats-note`), never a big figure: under a meeting's figures "Roll calls not
  confirmed*: N. Names we could not match to an official: N.", under an official's "Votes in not confirmed* roll
  calls: N." The same words for every meeting and every official whatever the numbers are.
- Alerts before launch: the morning-note card (`.mn-card.mn-off`) is its heading, the "starts at launch" line, one
  sentence and a closed 44px "Feeds for your list" toggle that holds the list picker and each list's feeds. When the
  note is enabled the full form card is unchanged.
- Radii: `--radius` 6px (inputs, notes, toggles), `--radius-lg` 12px (every content card), `--radius-xl` 18px (the
  day card and the morning note only). Officials cards carry the doors' 4px top accent.
- One small label: a single grouped rule (`.eyebrow, .label, thead th, ...`) sets JetBrains Mono uppercase at
  `--t-eyebrow`; no small caps are left (the Coming chip is the same mono).
- Tables: the finance pages' ruled look is the base for every table (ink rule on top, hairlines, mono column heads,
  no box, no stripes). On a phone the holders table and the About and Corrections tables stack; nothing scrolls sideways.
- One crumb: every page but the home page and a body's landing page has one `.crumb` line above its h1
  (`sitegen/bodies.py` `crumbs`): a body's pages lead to that body's page, then to the section's list ("Montgomery
  County / Meetings"); finance and bid detail pages to "Home / Finance"; every other page to Home.
- RPC meeting rows are titled by their date, with the home page's date block; the kind of meeting is the line under.
- Search: "Clear all filters" shows only with a filter on, "Copy link to this search" only with a query or a filter.
- About has a jump list of its sections: a ruled list on a wide screen, one closed toggle on a phone.
- Plain words for the site's own process (fixed strings only, the same for everyone): "attendance list could not be
  read" for "not extracted", "meetings whose attendance list was read", "a news reader app (also called a feed
  reader)", "a scanned image" for "a scan with no text layer", and the RPC Votes card says votes are being checked
  against the minutes again.
