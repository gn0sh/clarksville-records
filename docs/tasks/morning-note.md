# Tasks: Daylight M3, the morning note

Architecture: `docs/architecture/morning-note.md` (the output contract and seam there are fixed; T1-T3 build against
them in parallel). Tests run in session (`python -m pytest -q`); paste the output in the PR. No task sends mail,
creates an account or stores an email.

| Task | Owner | Depends on | Parallel |
|---|---|---|---|
| T1 Digest generator | backend-engineer | none | yes |
| T2 Missing feeds | backend-engineer | none | yes (separate files from T1) |
| T3 Sign-up section, preview page, morning.js | frontend-engineer | contract only; integrates T1/T2 at the end | yes |

## T1: digest generator (`sitegen/morning.py`, config, build hook)
- `config/site.yml` `morning_note:` block (lists with key/label, `cutoff`, `keep_days`, `zoning_prefixes`, seam keys,
  `enabled: false`); `morning.problems(cfg)` wired into `build.problems()` with the seam rules.
- `day(date, ...) -> dict` per the contract; `select(day, lists, seats)`; writes `morning/YYYY-MM-DD.json` for
  `keep_days` days and `morning/latest.json`; counts toward `MAX_FILES`.
- Window from `first_fetched_at` in the four collector manifests (architecture, window rule) in `site_timezone`; the zoning rule exactly as written (printed
  district/ward, `link_county` inheritance, `unplaced_zoning` count).
Done when tests show: a document fetched at 06:59 lands in today's note and at 07:00 in tomorrow's; a re-fetched
document does not reappear; an empty day writes `entries: []`; zoning matches by district, by ward, and never for a
case with neither; a linked county CZ item inherits its case's district; unconfirmed motions carry no outcome/tally;
every digest document resolves to a manifest row (else the build fails); BANNED scan clean; `enabled: true` without
`form_action`/`privacy_url` is refused; file count stays under the preview cap.

## T2: missing feeds (`sitegen/feeds.py`, `tests/test_alerts.py`)
- `feeds/topic-contracts.xml` from `data/finance.json` solicitations (verbatim titles, source link, stable ids).
- RPC zoning cases (prefixes from `morning_note.zoning_prefixes`) added to `topic-rezoning.xml`; existing entry ids
  byte-identical.
- `feeds/zoning-district-NN.xml` and `feeds/zoning-ward-NN.xml` on the `pages` target only; `feed_list()` exposes
  them with `kind: "zoning-seat"`, `seat`, `number` so T3 can link the right one.
- Update the feeds.py docstring and `test_one_feed_per_body_and_per_topic` (per-seat feeds now exist on pages only).
Done when tests show: valid Atom for every new feed; ids stable across two builds; old rezoning entry ids unchanged;
preview build has no per-seat feeds and stays under 500 files; pages build has 21 + 12; a per-seat feed holds only
cases whose printed district/ward equals its number.

## T3: sign-up section and preview (`alerts.html.j2` `#note`, `morning.html.j2`, `static/morning.js`)
- `#note` on alerts.html: picker with the four config lists, state line "Email starts at launch; follow by feed now"
  (config text), and per picked list the matching feed links (zoning: the per-seat feed for the stored district/ward
  on pages, else all-zoning; seats: the county/council body feed). With `enabled: false` there is no email field, no
  submit and no form `action`. No-JS: all lists and all feed links shown, except the per-seat zoning feeds, which stay
  hidden in `#note` without JS (deviation, review nit `morning-signup/no-js-feeds`: they need the stored seat, and
  each is listed in the page's "Zoning cases by district or ward" section).
- Nav "Morning note" links `alerts.html#note`; landing still fits one screen.
- `morning/index.html`: today's entries from `latest.json` data rendered server-side with `data-lists`,
  `data-seat-body`, `data-district`, `data-ward` (built on the pages target only, from the note `write()` returns;
  nothing links to it otherwise); `morning.js` filters by `#lists=` and `cr-your-seats`, mirrors `select()`.
- Enabled path rendered only in a test config: email field, `action=form_action`, CSP `form-action` gains exactly
  that origin, privacy line with `privacy_url`.
Done when tests show: no success text anywhere while disabled; no `fetch`/`XMLHttpRequest`/beacon in morning.js; JS
`select` matches Python `select` on the fixture for every list/seat combination; CSP unchanged when disabled; no
locality name in the new templates; no sideways scroll at 360 px; picker usable by keyboard with a visible legend.

## Order
T1 and T2 in parallel, then T3 integration (T3 can start on fixtures at once). Review per task; security review on
T3 (form, CSP) and on the later sender job. Going live is a separate CEO decision (provider pick, account, secret).
