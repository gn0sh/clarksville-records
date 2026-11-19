# Platform facts: Salem, OR

Draft city. Record here every fact the collection depends on, with how it was verified (fetch date, page, who
checked). Copy each check into the host's `robots` and `terms` lines in `city.yml`, so `python -m cities check
salem-or` can see it.

## Hosts

| Host | robots.txt | Terms of use | Notes |
|---|---|---|---|
| webapi.legistar.com | no robots.txt (404) 2026-11-19 | not read | Legistar's public Web API (`/v1/salem/...`) |
| salem.legistar.com | no robots.txt (404) 2026-11-19 | not read | the city's Legistar site; minutes files are on `salem.legistar1.com` (not yet checked) |
| pub-salem.escribemeetings.com | no robots.txt (404) 2026-11-19 | not read | eScribe, the city's meeting portal since July 2026 |
| www.cityofsalem.net | **BLOCKED** 2026-11-19 | not read | the city's main site: Akamai "Access Denied" 403 on /robots.txt and a page. Not needed for collection. |

## 2026-11-19 availability check (team cloud session, user agent DaylightRecordsBot/0.1, a few requests ~3 s apart)

- **Legistar (2016 to June 2026).** `GET /v1/salem/bodies`: 3 bodies (138 City Council, 180 Housing Authority, 181 Urban
  Renewal Agency). `GET /v1/salem/events?$filter=EventBodyId eq 138`: 350 City Council events, 2016-01-01 to
  2026-06-22. Minutes file on almost every one (per year events/minutes: 2016 22/20, 2017 37/35, 2018 33/33, 2019
  35/35, 2020 32/31, 2021 35/34, 2022 34/34, 2023 33/33, 2024 33/33, 2025 40/36, 2026 16/15). Last with minutes:
  2026-06-15 (event 1775). Nothing posted after 2026-06-22.
- **eScribe (July 2026 on).** `POST /MeetingsCalendarView.aspx/GetCalendarMeetings` (the call the public calendar page
  makes) for 2026-06-01..2026-11-18: 27 meetings; City Council meetings and work sessions from 2026-07-13 on, each with
  Agenda, PostMinutes (minutes) and Video, apart from the newest (Oct 26, Nov 9, Nov 12, Nov 16, Nov 17: minutes not
  yet posted).
- So the launch year needs two readers: Legistar (built) for Nov 2025 to June 2026, and eScribe (NOT built) from July
  2026. Vote format in either: not checked.
- Council shape: not checked here (expected wards plus a mayor, not at-large).

## Portal

- Legistar. Seen 2026-11-15: `https://webapi.legistar.com/v1/salem/matters/8174` answered JSON with
  `MatterBodyName` "City Council". Body list, vote labels, official title and earliest year: not checked.

## Never collect

- (none known yet)
