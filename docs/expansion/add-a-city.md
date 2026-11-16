# Add a city to Daylight

How to add a city, step by step. Worked example: **Murfreesboro, TN**, the first target city (CEO, 2026-11-16). Its
council posts on a CivicPlus Agenda Center, the same kind of site Daylight already reads for Clarksville 2016-2024.
Why it works this way: `docs/adr/0007-multi-city-template.md`.

None of the commands below fetch anything. Collecting from a city starts only after its checklist says READY, and
going live is the owner's call.

## The rules every city follows

- The official record only, and every fact linked to its source document.
- No AI-written text about named officials. Every official is shown the same way.
- Polite collection: obey robots.txt and its crawl delay, public pages only, never work around a block.
- Votes from a portal's data (Legistar) show as "not confirmed" until the same vote is read in the minutes.
- One Buy Me a Coffee link for every city, `https://buymeacoffee.com/gnoshcodes`, set in `config/brand.yml`. A city
  file can't change it or switch it off: if it tries, the check fails and names the key.

## 1. Make the city folder

```
python -m cities new murfreesboro-tn --name Murfreesboro --state TN --portal agenda_center --tz America/Chicago
```

This writes `config/cities/murfreesboro-tn/`:
- `city.yml`: the city's settings. It starts as `status: draft`, with domain `murfreesboro.daylight.gnoshcodes.com`.
- `agenda_center.yml`: the settings for the portal reader.
- `platform-facts.md`: where you write down every check you make (robots.txt, terms, page layout).

Anything not yet checked against a real source is marked `UNVERIFIED`. On its own, `UNVERIFIED` means the value is
still missing. In a comment after a value, it means the value is filled in but not yet checked.

Portal types: `agenda_center`, `civicclerk`, `legistar`. `municode` is not built yet: `new` accepts it, but the
checklist stays NOT READY until someone builds the reader.

## 2. See what is left

```
python -m cities check murfreesboro-tn
```

You get a plain checklist and a verdict at the end:

```
Murfreesboro, TN (murfreesboro-tn): draft, murfreesboro.daylight.gnoshcodes.com
  [x] brand: Daylight by gnoshcodes LLC; Buy Me a Coffee https://buymeacoffee.com/gnoshcodes (shared, locked)
  [ ] missing: config/cities/murfreesboro-tn/city.yml line 24: sky_place: UNVERIFIED ...
  [ ] UNVERIFIED: config/cities/murfreesboro-tn/agenda_center.yml line 6: host: www.murfreesborotn.gov ...
  [ ] host www.murfreesborotn.gov: robots.txt not checked
  [ ] host www.murfreesborotn.gov: terms of use not checked
  [ ] source agenda_center (...): shared reader built; config does not load yet: ... years must be list
NOT READY: 16 items to do
```

`python -m cities` checks every city file. `python -m cities list` (or `list --json`) shows every city with its
status and domain.

## 3. Do the per-city launch checklist

Most of the work. On a portal we already read, it takes about one session.

1. **robots.txt and terms, for every host.** Read each host's robots.txt and terms of use by hand. Write what you
   found and the date in `platform-facts.md`. Then change that host's `robots:` and `terms:` lines in `city.yml`
   from `UNVERIFIED` to a short note, for example `"/AgendaCenter allowed, crawl-delay 10; 2026-11-20
   (platform-facts.md)"`. If a host blocks automated tools, or its terms forbid collection, put it under
   `denied_hosts` and never collect from it. List every host that collection will touch under `allowed_hosts`. A
   denied host can never be added there: the check refuses it.
2. **Fill in the city folder.** For Murfreesboro:
   - `agenda_center.yml`: the council's name as the minutes print it, the official title, the Agenda Center
     category id and name, the first and last year listed, the meeting-kind rules and the vote words. Confirm the
     host (`www.murfreesborotn.gov`) and the search URL pattern on the live page.
   - `city.yml`:
     - `launch.earliest`: the oldest minutes the portal holds.
     - `sky_place`: city hall, to two decimal places, from an official source.
     - `geocoder_places`: up to 5 of the city's mailing places.
     - Time zone: confirm it.
     - The district lookup is already set to GoVoteTN, Tennessee's statewide lookup, as for Clarksville.
   - Each time you check a value, take its `UNVERIFIED` mark off and note where the value came from.
3. **Run the check again** until it says READY.
4. **Collect the launch year:** the last 365 days. Check the votes against the minutes, to the same 90%-verified bar
   as Clarksville. The site says plainly where its records start ("Records here start ..., older years are being
   added").
5. **Build, run the site checks, and get a code review.**
6. **Ask the owner for the go-ahead to go live.** Deploying is a hard stop. Only then set `status: live`.
7. **Add the city to both uptime monitors:** `monitor.config.json` in gn0sh/gnosh-uptime, and Better Stack.
8. **Draft the Buy Me a Coffee post** for the new city in `docs/bmac-posts/`. The owner posts it himself. Skip this
   while Daylight is in its no-marketing soft opening (until its formal launch in January 2027).

## 4. After launch: one older year per run

Each daily run shares one time budget across every live city. Daily updates come first. Then a new city's launch
year. Then each city gets one older year, newest first, back to its `launch.earliest`. To see what the next run
would do (it prints the plan and runs nothing):

```
python -m cities plan --budget 60
```

A city's progress is kept in `data/cities/<slug>/backfill.json`. Only the planner writes that file. Clarksville
doesn't have one, because its own pipeline already holds its history back to 2016.

## Second example: Salem, OR (Legistar)

`config/cities/salem-or/` is a draft too. Its `legistar.yml` came from the proof of concept. `python -m cities check
salem-or` lists what is left: robots.txt and terms for `webapi.legistar.com` and `salem.legistar.com`, the sky place,
the district lookup, the geocoder places, the official title, the vote labels and the earliest year.

## Not possible yet (milestone 2)

- A site for a city with no county: the build assumes a county body today.
- Building and deploying a city other than Clarksville: each city will get its own small deploy repo and workflow.
- Putting the city's name in the footer line.
