# Platform facts: Murfreesboro, TN

Started 2026-11-16 by `python -m cities new`. Record here every fact the collection depends on, with how it was
verified (fetch date, page, who checked). Nothing below is checked yet. Copy each check into the host's `robots`
and `terms` lines in `city.yml`, so `python -m cities check murfreesboro-tn` can see it.

## Hosts

| Host | robots.txt | Terms of use | Notes |
|---|---|---|---|
| www.murfreesborotn.gov | not checked | not checked | Agenda Center: https://www.murfreesborotn.gov/agendacenter (link from the CEO, 2026-11-16; not opened) |

## Portal

- Portal type: agenda_center (reader: CivicPlus Agenda Center). Body names, vote labels and the earliest year: not checked.
- District lookup: GoVoteTN (https://web.go-vote-tn.elections.tn.gov/), Tennessee's statewide site, as for Clarksville.

## Never collect

- (hosts that block automated tools or whose terms forbid it; also listed in `denied_hosts` in `city.yml`)
