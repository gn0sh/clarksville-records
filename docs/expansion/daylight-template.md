# Daylight in more cities: shortlist and template plan

Written 2026-11-15 for Brian. Status: plan plus a small proof of concept on a branch. Nothing deployed, nothing merged, no outreach.

## The short answer

**Start with Salem, Oregon.** It is about Clarksville's size, its council runs on Legistar, which has an open data feed that hands us agendas, items and votes as clean data instead of PDFs, and residents there have been packing council chambers over AI data centers since July, with hearings still going this month.

Daylight is already most of the way to a template. Templates hold no place names, and each source is a config file. What's left is a few hard-coded Clarksville bits, one new "portal reader" per portal type, and a deploy that can build more than one city. Plan below: my estimate is about **2 to 3 working sessions to get Salem live with one year of data**, then about **1 session per extra city** on a portal we already read.

## Top 5 cities

Populations are rounded Census estimates (Clarksville is about 180K). I checked each portal by finding the city's live pages; I did not run any collector against them.

| # | City | People | Records portal | Why it's a fit | Something residents are following now |
|---|---|---|---|---|---|
| 1 | **Salem, OR** | ~180K | **Legistar**, with its public data feed working ([sample](https://webapi.legistar.com/v1/salem/matters/8174)) | Cheapest votes we'll ever get: per-member votes come as data. State capital, so local news covers council closely. | AI data centers: a [packed council hearing in July](https://www.kptv.com/2026/07/28/wont-back-down-salem-residents-fill-city-council-chambers-data-center-testimony/), a [4-month pause in September](https://www.kptv.com/2026/09/22/salem-pauses-data-center-projects-4-months/), and a [hearing on data center rules](https://www.salemreporter.com/2026/11/12/public-notice-salem-city-council-public-hearing-data-centers-2/) noticed Nov 12. Also a [utility rate hearing](https://www.salemreporter.com/2026/11/10/city-meeting-salem-city-councilors-schedule-public-hearing-on-utility-rate-increase/). |
| 2 | **Killeen, TX** | ~160K | **Legistar** ([calendar](https://killeen.legistar.com/Default.aspx), 859 meetings listed) plus a CivicPlus Agenda Center | Army town next to Fort Cavazos, the closest match to Clarksville and Fort Campbell. Same reader as Salem. | Voters [passed all 8 charter amendments on Nov 3](https://www.kwtx.com/2026/11/04/all-8-killeen-charter-amendments-pass-nov-3-special-election/), which change how leaders are elected and recalled; a [homeless shelter decision in December](https://kdhnews.com/news/local/killeen-council-to-mull-options-on-homeless-shelter-at-december-meeting/article_9c17af09-b75c-4887-a6eb-90e57625e126.html). |
| 3 | **Murfreesboro, TN** | ~170K | **CivicPlus Agenda Center** ([link](https://www.murfreesborotn.gov/agendacenter)), the same system Daylight already reads for Clarksville 2016-2024 | Biggest reuse: same reader, same state (GoVoteTN lookup, Tennessee meeting law), and the Census address box works the same. | Fast-growth rezoning fights, e.g. a [Kroger rezoning deferred after residents raised drainage](https://citizenportal.ai/articles/7923962/Tennessee/Rutherford-County/Murfreesboro-City/City-Council-Meetings/Council-defers-Kroger-rezoning-after-residents-press-drainage-concerns). Steady, not one big story. |
| 4 | **Savannah, GA** | ~148K | **CivicPlus Agenda Center** ([link](https://savannahga.gov/AgendaCenter)) plus HTML [agendas and minutes](https://agenda.savannahga.gov/publishing/december-11-2025-city-council-regular-meeting/minutes.html) | Minutes published as web pages, not just PDFs, so they read cleanly. Big visitor audience. | Paid parking: council [tabled the Midtown paid parking zone on Nov 12](https://www.wtoc.com/2026/11/12/savannah-city-council-tables-proposed-midtown-paid-parking-zone/); housing ordinances [split council in September](https://www.wtoc.com/2026/09/14/savannah-council-split-housing-ordinances/). |
| 5 | **Columbus, GA** | ~200K | **Municode Meetings** ([minutes](https://columbus-ga.municodemeetings.com/sites/default/files/fileattachments/city_council/meeting/2975/cg_meeting_minutes._05-12-2026.pdf)) | Army town (Fort Moore). City and county are one government, so one body covers what takes two in Clarksville. Needs a new reader. | I found no clear current story (searches mostly returned Columbus, Ohio). |

Cities I looked at and passed on for now: Chattanooga and Knoxville (in range, but plain PDF folders or a custom portal, so more work), Fayetteville NC (a bit big, own website), Springfield MO (video site, no clear portal), Fort Collins (Municode, no current hook found).

**Why Salem over Murfreesboro:** Murfreesboro is the cheapest to build, but Salem has the strongest "people are checking the news" pull right now, and building the Legistar reader for it also unlocks Killeen and the many other mid-size cities on Legistar. If you'd rather stay in Tennessee first, Murfreesboro is the pick, and it can launch on today's code with config only.

**Worth knowing:** a site called Citizen Portal already posts AI-written meeting summaries for Salem, Killeen, Murfreesboro and Knoxville. Daylight's difference is the thing it already does: the official record only, every fact linked to its source document, no AI text about named officials. That difference should be the first line on each city's front page.

## Making Daylight a template

### What already works for any city
- Every place name, body name and branding line comes from `config/site.yml`; the templates hold none.
- Each source is a config file plus a reader: the CivicPlus Agenda Center and CivicClerk readers already have no Clarksville text in their code.
- The polite fetcher (robots.txt, 10 seconds between requests, honest name, stop on a block) takes its allowed hosts as an input.

### What needs changing
Milestone 1 of the template is done on branch `claude/project-thread-tj2xc5-cities` (2026-11-16; `docs/adr/0007-multi-city-template.md`, how-to in `docs/expansion/add-a-city.md`). Marked **Done**, **Part done** or **Still to do** below.

1. **One folder per city.** **Done:** `config/cities/<slug>/city.yml`, checked by `python -m cities`. Clarksville's file points at today's settings (`config/site.yml`, `config/localities/`) instead of moving them, so its live build is byte-identical. Murfreesboro (first target, CEO 2026-11-16) and Salem are drafts. **Still to do:** the build takes a `--city` setting, with Clarksville the default.
2. **Shared brand file.** **Done:** `config/brand.yml` holds the name, operator, Buy Me a Coffee link and wording, and the correction email. A city file that sets one fails. The coffee link and its switch are also pinned in code. **Still to do:** the same keys stay in `config/site.yml` (a test keeps them equal) until Clarksville round 2 lands, then they are removed. The city's name in the footer line needs a site build change.
3. **The last hard-coded bits.** **Part done:** each city file now lists its own hosts, and Clarksville's list is tested equal to `collector/fetch.py`. A denied host can never be allowed for any city. **Still to do:** `collector/fetch.py` and `collector/config.py` (which names the Montgomery County Commission and its years) read from the city file.
4. **Readers by portal type**, so a city is config only:
   - CivicPlus Agenda Center: have it (Murfreesboro, Savannah, Killeen's older records).
   - CivicClerk: have it.
   - **Legistar: new, started in the proof of concept** (Salem, Killeen).
   - Municode Meetings: new, later (Columbus, Fort Collins).
   - **Done:** a registry of these readers (`cities/readers.py`). The check says plainly when a city's portal has no reader yet (Municode). It also marks Clarksville's county readers as Clarksville-only.
5. **Vote reading per city.** Minutes print votes differently in every city. Each city folder gets its own vote words ("AYE:", "Nay"), name list and checks. Legistar cities often enter votes as data, which we show as "not confirmed" until the same vote is read in the minutes (the minutes stay the official record).
6. **One deploy per city.** GitHub Pages allows one custom domain per repo, so each city gets a small public repo that only holds its built site, at a subdomain like `salem.daylight.gnoshcodes.com`. The engine repo builds every city in its daily run. Clarksville stays at `daylight.gnoshcodes.com`.
7. **City list page.** `gnoshcodes.com/daylight/` lists every live city.

### Launch with a year, then backfill
- A new city launches with the **last 365 days**. Its pages say plainly where records start ("Records here start Nov 16, 2025; older years are being added"), in line with the rule to show only what's real.
- After launch, each daily run takes **one older year** if time is left in its run budget, newest first, until the city's earliest year. **Done** for every portal type (`cities/plan.py`, `python -m cities plan`). It runs daily updates first, then launch years, then backfill from what is left. It keeps per-city progress in `data/cities/<slug>/backfill.json`. **Still to do:** wire it into the daily run.
- Compute stays free: public repos get free GitHub Actions minutes, and every city shares one capped run budget so a big backfill can't crowd out daily updates.
- What a city gets at launch: council meetings, agendas, minutes, votes, video links, search, alert feeds, the address box if the city publishes ward maps. Finance, contracts, planning and school board come later per city, as they did here.

### Buy Me a Coffee in every city
- The same link, [buymeacoffee.com/gnoshcodes](https://buymeacoffee.com/gnoshcodes), and the same wording in every city's footer and beside the alert sign-up, set once in the shared brand file. Each city's line can name the city ("Daylight Salem is free...") from its own settings.
- No new account or cost. One Buy Me a Coffee page covers every city.
- Optional later: a per-city "supporters" count, if BMAC's notes show where people came from. Not needed to start.

### Per-city launch checklist (about one session for a portal we already read)
1. Check robots.txt and the portal's terms for every host; record them in the city's `platform-facts.md`. Never work around a block.
2. Fill the city folder: bodies, portal settings, time zone, sky place, state election lookup link, mailing places for the address box, ward map if published.
3. Collect the launch year; check votes against the minutes (same 90% verified bar as Clarksville).
4. Build, run the site checks, code review.
5. **Your go-ahead to go live** (deploy is a hard stop), then add the city to both uptime monitors.
6. Draft the Buy Me a Coffee post for the new city; you post it.

### Rules that carry over unchanged
Neutral and factual, every official shown the same way, votes only from the official record, no AI text about named officials, polite collection only, every fact linked to its source. A city picked because of a hot issue gets no issue page and no framing; residents find the issue through plain search ("data center"). No marketing or outreach for any city until Daylight's formal launch in January 2027.

## Proof of concept (branch only)

On branch [`claude/project-thread-jv6uwr`](https://github.com/gn0sh/clarksville-records/tree/claude/project-thread-jv6uwr) of clarksville-records. Not merged, not wired into the daily update, nothing collected from Salem.
- `collector/legistar.py`: a Legistar reader that turns events into the same meeting rows the Clarksville readers make, turns roll-call votes into Daylight's vote shape (keeping the clerk's own label, never guessing yes/no), and plans the one-year launch plus yearly backfill.
- `config/cities/salem-or/legistar.yml`: a draft Salem city folder, with every unchecked value marked UNVERIFIED.
- `collector/tests/test_legistar.py`: 8 tests on made-up data shaped like Legistar's documented answers; all 8 pass.

## Suggested order
1. You pick the first city (recommended: Salem).
2. Round 2 work for Clarksville goes first (starts Mon Nov 16); this waits behind it.
3. Then: city folders + shared brand file (Clarksville unchanged, checked against its live build), the Legistar reader on real Salem data after its robots/terms check, the per-city deploy repo, and Salem's launch year, held for your go-ahead.
