# Platform facts: Murfreesboro, TN

Started 2026-11-16 by `python -m cities new`. Record here every fact the collection depends on, with how it was
verified (fetch date, page, who checked). Nothing below is checked yet. Copy each check into the host's `robots`
and `terms` lines in `city.yml`, so `python -m cities check murfreesboro-tn` can see it.

## Hosts

| Host | robots.txt | Terms of use | Notes |
|---|---|---|---|
| www.murfreesborotn.gov | **BLOCKED** 2026-11-19 (see below) | not read | Agenda Center: https://www.murfreesborotn.gov/agendacenter (link from the CEO, 2026-11-16) |

## 2026-11-19: our fetcher is blocked

- `GET https://www.murfreesborotn.gov/robots.txt` from the team's cloud session (one request, 2026-11-19 00:26 UTC,
  user agent `DaylightRecordsBot/0.1`): HTTP 403, `Server: cloudflare`, page "Sorry, you have been blocked. You are
  unable to access civicplus.io". CF-RAY a5cb154468665d13-IAD. The block is CivicPlus's Cloudflare service in front
  of the city's site, not our proxy (our proxy let the connection through).
- 2026-11-16: WebFetch and Gemini also got client errors on robots.txt and most pages (murfreesboro-notes.md).
- Clarksville's own CivicPlus site (clarksvilletn.gov) is not blocked for the same fetcher.
- Per the polite-collection rule we stopped after that one request and did not retry from another address or with
  another user agent. Nothing is collected until the owner decides how to proceed (permission from the city, or
  another source).

## Portal

- Portal type: agenda_center (reader: CivicPlus Agenda Center). Body names, vote labels and the earliest year: not checked.
- District lookup: GoVoteTN (https://web.go-vote-tn.elections.tn.gov/), Tennessee's statewide site, as for Clarksville.

## Never collect

- (hosts that block automated tools or whose terms forbid it; also listed in `denied_hosts` in `city.yml`)
