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
- One header on every body's landing page (Brian, 2026-11-14; `_hub.html.j2` `body_head`, `tests/test_body_switch.py`): the same masthead as the home page (name plate and tag, no coverage line), then kicker, h1, one-sentence lede, coverage line, "How recent the records are", Watch, then the cards; a row is left out only when the body has no such fact (the school board has no dates and no Watch).
- With script the choice is kept on the device (`localStorage["cr-body"]`, a body key only; inside try/catch, and the
  page still filters when storage is blocked). Rows that carry `data-body` are hidden by the class `bs-off`, never
  removed, under a "Showing Clarksville only / Show all" line. Visiting a body's hub makes it the choice.
  A click stays on the page only when the page has rows of that body; otherwise it goes to the hub.
- Tagged: the day page's cards and week-strip dots, the home page's meeting rows, Meetings, Votes (every year), the
  Finance index's books and funds, and Search (the choice applies while no Body box is ticked; it is not written to the
  URL). Not tagged, so never filtered: Items, Officials, district, member, meeting, fund, capital, bids and transcript
  pages, and each body's own pages.
