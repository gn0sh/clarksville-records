# `data/` inventory (task B1, rows D and CFG)

Every tracked file under `data/` at `origin/main` 4c57587 (45 files), with its writer. Method: `git ls-files data`;
the writers found by grepping `collector/`, `sitegen/`, `qa/`, `tools/` and `.github/workflows/daily-update.yml` for
each path; authors from `git log --format=%an -- <file>` (full, unshallow history, 49 commits). "Daily run" means the
`update` job of `daily-update.yml` (`python -m collector city run --agendas` :331, `python -m collector committees run`
:273, `python -m collector run` :332), whose `data/` the `push` job commits.

Result: three files were curated and moved to `config/` (B1). Every other tracked file is collector output written
by the daily run, except two person-run groups (transcripts, map manifest) that need a decision before the cutover
(see "Open for B2 / the cutover" below).

| File or glob | Writer (file:line) | Class | Evidence |
|---|---|---|---|
| `data/names.yml` | none; read by `collector/names.py:30` | **curated, moved to `config/names.yml`** | Hand-kept roster ("a person adds an alias by PR", `collector/names.py:12`); no code writes it; only gn0sh commits (1). |
| `data/procedural-titles.yml` | none; read by `collector/facts.py:23` | **curated, moved to `config/procedural-titles.yml`** | Hand-kept patterns; no code writes it; only gn0sh commits (1). |
| `data/corrections-log.json` | none; read by `sitegen/views.py:1339`, `qa/site_checks.py:1053` | **curated, moved to `config/corrections-log.json`** | "Entries are written by hand after a report is checked" (`sitegen/views.py:1345`); only gn0sh commits (1). |
| `data/manifest.json` | `collector/store.py:146` (`Store(MANIFEST)`, `collector/__main__.py:446`) | collector output | Daily run; github-actions[bot] 3, gn0sh 1. |
| `data/changes.jsonl` | `collector/store.py:137` (append beside the manifest) | collector output | Daily run; github-actions[bot] 3. |
| `data/facts.json` | `collector/__main__.py:484` | collector output | Daily run (county); gn0sh 1 (no bot change since). |
| `data/finance.json` | `collector/fin_run.py:211` (path `collector/fin_facts.py:26`) | collector output | Daily run (`run_finance`, `collector/__main__.py:488`); bot 3, gn0sh 1. |
| `data/fin_fetch_status.json` | `collector/fin_run.py:60` (path :30) | collector output | Daily run; gn0sh 1 (no status change since). |
| `data/county-agendas/agendas.json` | `collector/county_agenda.py:473` (path :53) | collector output | Daily run (`run_agendas`, `collector/__main__.py:154`); gn0sh 1. |
| `data/county-agendas/manifest.json` | `collector/store.py:146` via `collector/county_agenda.py:482` | collector output | Daily run; gn0sh 1. |
| `data/localities/clarksville-tn/listing.json` | `collector/city_run.py:303` | collector output | Daily run (`city run`); gn0sh 1. |
| `data/localities/clarksville-tn/civicclerk-listing.json` | `collector/city_run.py:322` | collector output | Daily run; bot 2, gn0sh 1. |
| `data/localities/clarksville-tn/manifest.json` | `collector/store.py:146` via `collector/city_run.py:436` | collector output | Daily run; bot 2, gn0sh 1. |
| `data/localities/clarksville-tn/facts.json` | `collector/city_run.py:462` | collector output | Daily run; bot 2, gn0sh 1. |
| `data/localities/clarksville-tn/wards.json` | `collector/city_run.py:461` | collector output | Daily run; bot 1, gn0sh 1 (as the architecture note found). |
| `data/localities/clarksville-tn/committees/{listing,committees,manifest}.json` | `collector/committees.py:278`, `:606`, `collector/store.py:146` via `:328` | collector output | Daily run (`committees run`); bot 1, gn0sh 1 each. |
| `data/localities/clarksville-tn/fin-manifest.json`, `.../finance.json` | `collector/store.py:146` via `collector/fin_books.py:210`; `collector/fin_books.py:156` | collector output | Daily run (`run_city_books`, `collector/__main__.py:147`). When the build is kept, the issue asks a person to run `fin-books build` and commit (`daily-update.yml:581`): that person path ends at the cutover (see below). gn0sh 1-2. |
| `data/localities/cmc-rpc/{listing,manifest,rpc.json}` | `collector/rpc.py:520`, `collector/store.py:146` via `:858`/`:900`, `collector/rpc.py:791`/`:916` | collector output | Daily run (county `run` RPC step); bot 1-3, gn0sh 1. Second writer: `tools/scrub_rpc_phones.py:48`, a one-off dev tool (rewrites `location` only). |
| `data/localities/montgomery-tn/committee-agendas/{listing,agendas,manifest}.json` | `collector/county_committees.py:364`, `:467`/`:518`, `collector/store.py:146` via `:445`/`:508` | collector output | Daily run (county `run` committee step); gn0sh 1 each. |
| `data/localities/clarksville-tn/transcripts/*.json` (17), `.../transcripts/index.json` | `collector/transcripts.py:274`, `:295` (import), `:319`, `:322` (remask) | **person-run tool output** | `python -m collector transcripts import <dir>` on Whisper output made outside the repo; the daily run never calls it (`daily-update.yml` has no `transcripts`). Only gn0sh commits (1 each). Fits SHAPE''; stays in `data/` in B1. |
| `data/maps/manifest.json` | `collector/store.py:146` via `tools/fetch_map.py:43` (path :25) | **person-run tool output** | "Dev tool; nothing at build time runs it" (`tools/fetch_map.py:11`); no reader outside the tool. Only gn0sh commits (1). Fits SHAPE''; stays in `data/` in B1. |

Untracked under `data/` (gitignored caches, restored by the workflow, row K): `data/store/`, `data/text/`, `data/ocr/`,
`data/raw/`.

No `sitegen/` or `qa/` module writes under `data/`: both only read it (sitegen writes `build/site/`), and
`qa/published_guard.py` fails any test session that changes `data/`.

## Open for B2 / the cutover
1. **Person-run writers have no path to `records-data`.** Under I-prov a person's push of a new tree is refused
   (only a J2-attested tree or the seed passes). Today three person paths write `data/`: `transcripts import`
   (and `remask`), `tools/fetch_map.py`, and the kept-city-books fallback (`fin-books build`, `daily-update.yml:581`),
   plus the one-off `tools/scrub_rpc_phones.py`. Recommended: treat transcripts and the map manifest as reviewed
   inputs and move them to `config/` (they are not re-derived by the daily run), and change the city-books
   fallback to "fix the reader by PR; the next daily run rebuilds". The architect decides before D3; B1 leaves them
   in `data/` because the docs name only the three files above as curated.
2. The gate and push job SHAPE lines still allow `.yml` (`daily-update.yml:121`, `:849`) and the push validator's
   `*.yml` case (`:797`); B2 narrows them to `collector.data_shape.SHAPE_BASH` and adds `CURATED_NAMES`.
