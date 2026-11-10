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
- The week strip and day cards are their own page, `today.html` ("Today" in the menu; today's date on the landing sky links it), not a band under the landing: the landing must still fit one screen (tests/test_address_box.py). Window: config/site.yml `days` (Sunday weeks, 4 before and 4 after today in `site_timezone`), rebuilt by the daily update.
- Left out, no data behind them: meeting times and places, "Your seat voted" lines, "near you" tags and the transcript, morning note and money bands (M3). The school board is a "Coming" line with one link (`school_board.url`, the district home page until a person confirms the board page's URL; cmcss.net is never fetched).
