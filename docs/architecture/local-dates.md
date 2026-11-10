# Local dates (problem family `feeds/entry-date-is-local-day`, second hit)

**Invariant.** Every date the site shows to a reader is the America/Chicago (config/site.yml `site_timezone`)
calendar day of the instant; stored timestamps stay UTC; meeting dates are civil dates and are never shifted.

## What is stored

- Each collector manifest row has `first_fetched_at`, a full UTC instant (`2026-11-10T04:38:00+00:00`), per
  (url, sha256). Manifests: `data/manifest.json` (county minutes, finance), `data/county-agendas/manifest.json`,
  `data/localities/clarksville-tn/manifest.json`, `data/localities/cmc-rpc/manifest.json`, `data/maps/manifest.json`.
- Each facts file's source record has `fetched_at` = `first_fetched_at[:10]`, the **UTC day** (collector/facts.py,
  city_build.py, county_agenda.py, rpc_agenda.py, fin_facts.py). A UTC day alone cannot be converted: a fetch at
  22:38 in Clarksville (04:38Z) is stored as the next day.
- The map files (config/localities/montgomery-tn/districts.json) carry a hand-written `fetched` day. The wards
  poster has a manifest row (maps); the county districts PDF has none.

## The rule in code

One helper, `sitegen/localdates.py`:
- `local_day(ts)`: the site_timezone day of an aware instant (DST-safe via zoneinfo). A bare day or a naive
  timestamp raises: it is never converted.
- `fetched(src)`: the day a page prints for a source record. It looks up the manifest row with the same url and
  sha256 (`load()`, at build start, config/site.yml `fetch_manifests`), and uses it only when the stored day is
  that instant's UTC day (same fetch). No such row: the stored day **labelled** `"2026-11-10 (UTC day)"`. Never a
  guess.
- `span(srcs)`: earliest and latest of many sources: local days when every source has its instant, else every
  day as its UTC day, labelled (local and UTC days are never compared).

The conversion is done where a view picks the source (the template sees only a day string and no sha256), so the
templates keep `{{ src.fetched }}` unchanged. A template that ever prints an instant uses the Jinja filter
`local_day` (sitegen/build.py make_env; none does today). `qa/site_checks.py` `dates/no-raw-utc-day` checks the built pages and
feeds: every "fetched D" next to a source link is that source's local day, or is labelled (UTC day) when the
source has no recorded instant; every aggregate fetch day ("fetched between", "latest fetched", "Data as of") is
the local day of some recorded instant, or labelled.

## Consumers

| Where (file:line at 66f8d5f) | Prints | Status |
|---|---|---|
| sitegen/views.py:221 `Index.src` -> _macros.html.j2:4 (`source`), :31 (`source_cell` Details) | "p. N, fetched D" / "Fetched D." on meeting, items, votes, official pages (county and councils) | fixed |
| sitegen/views.py:1470 search index `s.f` -> static/search.js:156 | ", fetched D" in search results | fixed (via `Index.src`) |
| sitegen/views.py:1094 review (internal) -> review.html.j2:35 | "fetched D" | fixed |
| sitegen/views.py:826 meeting doc -> meeting.html.j2:7, council_meetings_year.html.j2:31,33 | "PDF, N pages, fetched D." | fixed |
| sitegen/council.py:322 year-page agenda | (agenda link; day not printed today) | fixed (same helper, for consistency) |
| sitegen/county_agendas.py:86 -> county_agendas.html.j2:23 | "Agenda: PDF, fetched D." | fixed |
| sitegen/days.py:98 today page docs | (not printed by today.html.j2) | fixed (same helper) |
| sitegen/rpc.py:241 -> _rpc.html.j2:7 (RPC pages, today page cards) | "fetched D" per RPC document | fixed |
| sitegen/rpc.py:275 RPC agenda | (agenda link) | fixed (same helper) |
| sitegen/rpc.py:296 -> rpc_home.html.j2:7 | "(latest fetched D)" | fixed (`span`) |
| sitegen/views.py:258 `data_as_of` -> base.html.j2:57, council.py:266 | footer "Data as of D" on every page | fixed (`span`) |
| sitegen/views.py:262 `fetched_sentence` -> council_home.html.j2:9, views.py:714,738 (official pages) | "Minutes fetched between A and B." | fixed (`span`) |
| sitegen/fin_views.py:115 `Finance.src` -> _fin_macros.html.j2:12,17, fin_solicitation.html.j2:63 | "bid tab p. 1, fetched D" | fixed |
| sitegen/fin_views.py:162 -> fin_solicitation.html.j2:26 | "Document fetched D." | fixed for fetched documents; a link never fetched (not_pdf, dead) prints no fetch day (provenance/docx-not-fetched) |
| sitegen/fin_views.py:153 dead link note | "Link not available at fetch (D)" | labelled (UTC day): no instant (no such document in today's data) |
| sitegen/budget_views.py:259 -> fin_index.html.j2:14 | "FY.., fetched D" per budget book | fixed |
| sitegen/views.py:1151 -> district.html.j2:30; views.py:1226,1228 -> index.html.j2:87 (landing, not edited) | map lines "fetched D" | wards: fixed (maps manifest row); county districts PDF: no manifest row, labelled (UTC day) |
| sitegen/views.py:1057 `changes` -> changes.html.j2:9 | change date | fixed for source replacements (collector/store.py logs `first_fetched_at[:10]`; looked up by url and the new sha256); hand-written rows are civil dates, left |
| sitegen/build.py:726 morning note `data_as_of` (JSON for the sender) | machine field | fixed (`localdates.latest`: a plain day, the local day when every source has its instant, else the UTC day with `data_as_of_utc: true`; morning-digest/as-of-contract) |
| sitegen/feeds.py `_day`, `_instant`, `_added` | entry summaries "fetched D", updated | kept from the first hit (instant from the manifests). Its fallback with no manifest row (fixture builds only) printed the bare UTC day: now `_fetched_day`, the day pages print for the source (labelled). The entry's `updated` there stays noon of the stored day (machine value) |
| sitegen/morning.py window, note_day; morning_page.py | note day, window stamps | left: already site_timezone instants |
| sitegen/days.py today, county_agendas.py on_build_day | the build day | left: `today_in_zone` is already the local day |
| Meeting dates, coverage from/to, item years, seats seen_to, record_glance | civil dates | left: never shifted (test) |
| collector/export.py, rpc_export.py, fin_export.py `fetched_at`, `*_fetched_at` columns | data | left: machine data, the UTC day as stored; data.html.j2 and data/README.txt now say so |
| about.html.j2:17,120; method.html.j2:6; data.html.j2:19 | wording | about and data: one sentence on what day is shown; method points to about |
| config/localities/montgomery-tn/georef.json, wards-georef.json `fetched` | not shown on any page | left |

Count: 26 rows. Fixed 19 (3 are not printed today and use the helper so they cannot drift; the finance document
row and the map row convert what has an instant and label the rest). Labelled only, no instant exists: 1 (dead link
note). Left with a reason: 5 (morning window, build day, civil dates, export columns, georef files). Wording: 1.

## Days that cannot be made exact

- **County districts PDF** (districts.json `fetched: 2026-11-08`, hand-written, no manifest row). Shown as
  "fetched 2026-11-08 (UTC day)". Derivation: if that day is a UTC day, the fetch was at or after 2026-11-08 00:00Z;
  the trace was committed at 2026-11-08 00:43Z (ee4a48f), so the fetch was between 18:00 and 18:43 on 2026-11-07 in
  Clarksville, and the Clarksville day is 2026-11-07. That rests on the hand-written day being a UTC day, which no
  record states, so the page still shows the stored day labelled (UTC day). Fix: fetch it through the collector (a
  manifest row) the next time the map is re-traced.
- **Finance links never fetched** (3 `.docx` bid tabs, status not_pdf, "not requested" in data/fin_fetch_status.json):
  `fetched_at` is the day of the fetch run (collector/fin_run.py, a UTC day). They were never fetched, so the row
  prints no "Document fetched" line. A dead link keeps the day the fetch was tried in its note, labelled (UTC day).
- **Fixture builds**: made-up sources have no manifest rows, so every fetch day is labelled (UTC day).

## One manifest list; why feed summaries use the earliest row

config/site.yml `fetch_manifests` is the one list: the pages' fetch days (localdates.load) and the morning note and
feeds (morning.manifest_paths -> first_fetched) read the same files (dates/two-manifest-lists). The pages take the row of
the source's own sha256 (the copy the page cites); the feeds and the morning note take the earliest row per URL
(morning.first_fetched), on purpose: a feed entry and a note entry are "when this document was added to the site",
must not move or re-alert when the county replaces the file, and the summary's "fetched <day>" is the day of the
entry's own `updated`. The two differ only for a URL with two copies (none in today's manifests); the replacement then
has its own row on the Changes page. The site check accepts any row of the URL for a feed summary.

## Wording

The About page says the date shown is the day in Clarksville (config `today_place`) and what "(UTC day)" means. The
Data page and data/README.txt say `fetched_at` in the files is the UTC day. The Method page points to About for dates
and is unchanged.
