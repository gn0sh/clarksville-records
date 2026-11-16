# ADR 0007: Daylight as a multi-city template (milestone 1)

Status: proposed (backend-engineer, 2026-11-16), feature `city-template`. Branch only: nothing collects from a new
city, deploys or merges. Plan: `docs/expansion/daylight-template.md`, "Making Daylight a template". Step by step:
`docs/expansion/add-a-city.md`.

## Context
The CEO's goal: "make future cities easy to add." First target city: Murfreesboro, TN (CEO, 2026-11-16), on the same
CivicPlus Agenda Center reader Clarksville used for 2016-2024; Salem, OR (Legistar) stays as a second draft.
Clarksville round 2 starts on main on 2026-11-16 and edits `sitegen/`, `site/templates/`, `config/site.yml` and the
daily workflow, so this milestone had to be additive and leave Clarksville's build unchanged.

## Decisions
1. **One folder per city, `config/cities/<slug>/city.yml`**, slug `<place>-<state>`. Fields: slug, name, state,
   timezone, status (`draft` | `live`), domain (`daylight.gnoshcodes.com` or `<name>.daylight.gnoshcodes.com`,
   unique), sources (portal type + config file), allowed_hosts (each with its robots.txt and terms check, or
   `UNVERIFIED`), denied_hosts, launch (`launch_days`, `earliest`), sky_place, district_lookup, geocoder_places,
   platform_facts, verification_notes. Loaded and checked by `cities/registry.py`; unknown keys fail.
2. **Clarksville points, it does not move.** `config/cities/clarksville-tn/city.yml` names `settings: config/site.yml`
   and its existing `config/localities/` files; sky place, district lookup and geocoder places are read from
   `site.yml` (one copy). Its timezone must equal `site.yml` `site_timezone`. No `launch` block: its own pipeline holds
   its history, so the planner gives it daily updates only and never writes a backfill state for it.
3. **Shared, locked brand: `config/brand.yml`** (site_name, operator, operator_url, support_url/label/line/enabled,
   corrections.email). A city file (top level or `site:` block) that sets any of them fails with a message naming the
   key. The Buy Me a Coffee link (`https://buymeacoffee.com/gnoshcodes`) and `support_enabled: true` are also pinned
   in code (`cities/brand.py` `BMAC_URL`), so neither a city nor an edit to brand.yml can change or switch it off;
   that takes a reviewed code change.
4. **Brand duplicates in `config/site.yml` stay for now.** The live build reads them there and round 2 is editing that
   file. `tests/test_cities.py` fails if they drift from brand.yml.
5. **Per-city hosts.** `registry.allowed_hosts(city)` gives a city's allowlist; Clarksville's equals
   `collector.fetch.ALLOWED_HOSTS` (tested). `collector.fetch.DENIED_HOSTS` plus a city's own `denied_hosts` can never
   be allowed: a city listing one (or a subdomain of one) fails to load, and `may_fetch` checks denied first. A
   reader that can name its hosts (Legistar) must find each on the city's allowlist.
6. **Portal readers by type** (`cities/readers.py`): agenda_center, civicclerk, legistar (shared); municode listed
   as not built, so validation and `check` say so plainly; county_minutes, county_agendas, rpc, finance, zoning marked
   Clarksville-only (their specifics sit in code or one locality's file), and `cities new` refuses them.
7. **Launch-and-backfill planner, portal-agnostic** (`cities/plan.py`; `launch_windows` and `Window` moved from
   `collector/legistar.py`, which re-exports both). Launch with the last 365 days; then one older 365-day window per
   city per run, newest first, down to `earliest`. Windows are fixed from the stored launch date, so they never shift
   day to day. One budget (minutes) for all cities: daily updates of live cities first, launch years next, backfill
   from what is left, the city with the fewest years done first. Draft cities get nothing. An `UNVERIFIED` earliest
   means the launch year only. State per city: `data/cities/<slug>/backfill.json`, written only by
   `plan.save_state`, which refuses a city without a launch block. Run costs (5 min daily, 30 min per year) are
   provisional until real runs are timed.
8. **UNVERIFIED marks are plain text.** `UNVERIFIED` as a value means missing; in a comment it means the value is set
   but not yet checked against a real source. `python -m cities check` lists both, per file and line, plus every
   host's robots and terms, every reader (built or not, config loads or not), then READY or NOT READY (exit 0/1;
   2 for an invalid file).
9. **No network in any `cities` command or test.** The tests refuse socket connections.
10. **Review fixes (code review on aa63844).**
    - A host's robots or terms check counts only when it names the date of the check (YYYY-MM-DD) and has no
      unverified mark, in any case.
    - A Clarksville-only reader is refused at load time for any other city.
    - The agenda_center and civicclerk readers name their hosts from their files: `host` and `search_url`;
      `api_host`, `events_url` and `file_url`. Each host must be on the city's allowlist and never denied.
      CivicClerk's `video_hosts` are links only, never fetched. They are not added to the allowlist (Clarksville's
      `cpmedia.azureedge.net` isn't on it), but they can never be a denied host.
    - `launch.earliest` can't be in the future, and `launch_windows` refuses an empty window.
    - A `live` city with a launch block needs `go_ahead: {date, by}`, the owner's go-ahead record.

## Edits to existing files
Only `collector/legistar.py` (proof-of-concept file, not used by the daily run): `Window`/`launch_windows` replaced
by an import from `cities/plan.py`; the public names stay. No change to `config/site.yml`, `sitegen/`, `site/`,
`.github/workflows/`, `collector/fetch.py`, `collector/config.py` or `docs/status.md`. A Clarksville build from
committed data (`python -m sitegen --facts data/facts.json --target pages`) is byte-identical before and after.

## Found on the way
Clarksville's `check` is NOT READY: no terms-of-use check is on record for any of its 7 hosts, and no robots.txt
reading is on record for `d6.mcgtn.org` or `montgomeryminutes.bisonline.com` (the fetcher still reads robots.txt on
every run and stops a host on a block). The checklist shows the gap; recording those checks is a follow-up.

## Milestone 2 (not done here)
- A council-only site build for cities with no county (Murfreesboro, Salem): today `sitegen` assumes a county body.
- The build and collectors read a city's settings through the registry (`--city <slug>`, Clarksville the default);
  `collector/fetch.py` and `collector/config.py` take their hosts and body from the city file.
- Per-city deploy repo and workflow (one GitHub Pages custom domain per repo), and the planner wired into the daily
  run with real run-cost numbers.
- Remove the duplicated brand keys from `config/site.yml` once round 2 lands (the drift test then goes too).
- The city's name in the footer line ("Daylight Murfreesboro is free..."): needs a `sitegen` change, so it waits.
- A `gnoshcodes.com/daylight/` city list built from `python -m cities list --json`.
- Record the Clarksville terms and robots checks listed above.
- Import direction: `collector/legistar.py` now imports `cities.plan` (collector -> cities), while `cities` imports
  `collector.fetch` and the readers. Before the collectors read city files, move the planner's `Window` and
  `launch_windows` to a module with no `collector` imports, or into `collector/`, so the two packages don't grow a
  cycle.
