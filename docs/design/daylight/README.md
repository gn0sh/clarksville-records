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
