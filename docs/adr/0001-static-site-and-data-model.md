# ADR 0001: Static site from one facts file; private preview as a claude.ai artifact

Status: accepted (architect, 2026-11-07). Architecture: `docs/architecture/clarksville-records.md`.

## Context
M1 must show named officials' votes and attendance with a source page for every fact, $0, no public URL (G7), no
server, neutral by construction (N1-N6), and run unattended later (US4) while GitHub Actions minutes are exhausted
until Dec 1. Parsing is deterministic code (Brain Trust). Two engineers build it in about two hours.

## Decision
1. **One facts file is the contract.** The collector writes `data/facts.json` (schema `schema/facts.schema.json`):
   sources, officials, meetings with inline attendance, items, item events, motions, roll calls with inline votes,
   each fact carrying `source_id` + `page` and, where it names a person, a `verification` block. Committed to git,
   deterministic ordering, so git history is the change history and a no-op run makes no diff.
2. **Only verified facts are rendered or exported.** Unverified facts exist only in `data/facts.json` and on the
   internal review page. Pages state held-back counts in one fixed sentence (P3, P4).
3. **Items are keyed by normalised official number**; unnumbered items link only on an exact normalised title, never
   for listed procedural titles, and are labelled "linked by title" (AC7.3).
4. **Static site:** Python + Jinja2 renders plain HTML with relative links; one template and one view builder per page
   type; no client framework, only a small vanilla filter script. Item pages are bucketed one file per year
   (`items/<yyyy>.html#<id>`) to keep the site under ~250 files.
5. **Private preview: one private multi-file claude.ai artifact** built from `build/site/`, republished to the same URL
   each run. Not a zip, not a single-file bundle.
6. **One command** (`python -m collector run`) is the unit of automation for every runner: in session now, a scheduled
   Claude Code session next (the only runner that can republish the artifact), GitHub Actions after Dec 1 for data
   refresh and failure issues.

## Alternatives considered
- **SQLite + server-rendered pages.** Better for ad-hoc queries, but needs a host (G7, $0) and adds a runtime. The data
  is small (a few MB); a JSON file plus CSV export is enough, and SQLite can be built from the CSVs later.
- **Zip in `/mnt/project-files/.../preview/`.** Free and private, but Brian reviews on iPhone, TV and PC: a zip must be
  downloaded and unpacked, and phones do not follow relative links between local HTML files well. Kept as the fallback
  if the artifact channel fails (risk 1).
- **Single self-contained HTML bundle.** One file is simple to publish, but either embeds every rendered page (estimated
  15-20 MB, over the 16 MB page limit) or renders client-side from embedded JSON, which means a second renderer and a
  second place where N1 must hold. Rejected.
- **Show unverified votes with a label.** Rejected by the spec (P3): a wrong vote under a named person is the harm.
- **One file per item.** About 1,500 files exceeds the artifact's 511-file version limit. Revisit for public hosting.
- **Fuzzy name merging.** Rejected: merges must be mechanical and identical for every official (G2); unmatched names
  hold the fact back and surface as alias candidates for a person to add by PR.

## Consequences
- The frontend builds against `site/fixtures/facts.sample.json` now; the parser only has to meet the schema.
- Republishing needs a Claude session; Actions alone cannot update the preview. US4's "no manual step" is met by a
  scheduled session, which uses plan usage but no money.
- The artifact is private by default; sharing it is Brian's act and counts as going public (hard stop 1).
- Item URLs change if public hosting moves to one file per item; acceptable before launch, nothing links to them yet.
- Expensive to reverse: the facts schema and id scheme. Recommend: Brain Trust (3 members) on the schema after M0, once
  real parse output shows whether the shapes fit.
