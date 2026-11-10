# Zoning trail: invariant, link keys, data shape, consumers (task D0; feeds D1 and D2)

software-architect, 2026-11-10. Evidence and counts: `docs/research/zoning-trail.md` (O-numbers below point there).
Family: `attribution` (a link that says "this vote is that case" is an attribution). Extends, and does not replace,
`docs/architecture/rpc-motion-invariant.md`: every RPC motion on a trail follows that file.

## The invariant
**An RPC case is joined to a City Council or County Commission item only when that body's own document prints the
case number, prefix included, on that numbered item, the number is on an RPC agenda we hold, and the pairing is
one-to-one; anything else is shown side by side with no claimed link.**

Never used to make or to "confirm" a link: applicant, agent, location, acreage, districts, ward, meeting dates, the
order of items, or any combination of them. They are not a weaker key; they are not a key (O9, I6).

## Link keys
| Side | Key | Where it is printed | Compared with |
|---|---|---|---|
| County | the item's number, `CZ-n-yyyy` / `CZO-n-yyyy` | the Commission's minutes and agendas; already `items[].number` in `data/facts.json` | `collector.rpc_minutes.link_key` on both sides (as `Rpc.link_county` does today). Unchanged. |
| City | `zoning_case`: the bracket on the ordinance's heading | council minutes: `ORDINANCE 107-2022-23 [Z-22-2023] (First Reading)`, `ORDINANCE 30-2023-24 (First Reading) [Zoning Case #Z-51-2023]`, `ORDINANCE 05-2025-26 (FIRST READING) [ZONING CASE Z-29-2025]` (O3, O4) | `link_key` of the bracket's number against `link_key` of an RPC case with a city prefix |

### City key rules (K1 to K7). Any rule failing: no `zoning_case`, a reason in the build report, nothing shown.
- **K1 Same heading.** The bracket is on the line that starts (after an optional list marker such as `A.` or `1.`)
  with `ORDINANCE <number>`, or on the wrapped continuation of that same heading before the title text begins. The
  ordinance number on that line is the number of the item the record files the vote under. A bracket anywhere else
  (a motion sentence, a speaker's remark, another item's block) is not read.
- **K2 Prefix printed.** The bracket holds one case number with its letters: `Z-` or `ZO-` (config: the RPC's city
  prefixes, `rpc.yml`). `[Zoning Case #57-2023]` has no prefix: not a key (O5). Nothing is filled in.
- **K3 One form.** Only these shapes: `[<case>]`, `[Zoning Case <case>]`, `[Zoning Case #<case>]`, any letter case,
  spaces around hyphens allowed. `link_key` does the glyph repair it already does for county numbers and no more.
  Two case numbers in one bracket: no key.
- **K4 Text layer only.** The city minutes are read from the text layer; an OCR-only page yields no key.
- **K5 Agreement.** Every document that prints a bracket for an ordinance prints the same case. Two different cases
  for one ordinance: no key for that ordinance. One case under two ordinances: no key for either (a reapplication
  may be legitimate, unknown 4; relax only with a real example, a test and a QA spot check).
- **K6 On an RPC agenda.** Checked at page time, not in the collector: the case number must be a case on an RPC
  agenda in `rpc.json`. If it is not, the printed number may be shown on the council item as text with its source
  ("Case number as the minutes print it"), with no link and no trail.
- **K7 Order.** The first RPC agenda that lists the case is dated on or before the council meeting whose document
  prints the bracket. Otherwise no link (a misread year would show up here).

`ZONING_LINK_RULES = "zoning-trail-1"` is written into the city facts as `zoning_link_rules`. The pages and
`site_checks` restate it: a record without the current value shows no city link at all (the `motion_rules` pattern,
rule 8 of the RPC motion invariant). Change the value whenever a rule changes what links.

## Data shape for D1
`data/localities/clarksville-tn/facts.json`, schema version unchanged (additive):

```json
{
  "zoning_link_rules": "zoning-trail-1",
  "items": [
    {"id": "ordinance-107-2022-23", "number": "ORDINANCE 107-2022-23", "title": "", "link_basis": "number", "year": 2023,
     "zoning_case": {"number": "Z-22-2023", "printed": "[Z-22-2023]",
                     "source_id": "src-fd3ce01ba1b2", "page": 3, "meeting_id": "2023-05-04-regular"}}
  ]
}
```

- `number`: `link_key` form. `printed`: the bracket as printed. `source_id`, `page`, `meeting_id`: the first document
  (by meeting date) that prints it. The field is absent when there is no key; there is no "probable" value.
- Held-back readings (K2, K5 and so on) go to the city build report (next to the existing city counts) under `zoning_link` as counts per reason plus
  the item ids. They are never written to facts or to the site.
- **The join is not stored.** `sitegen/zoning_trail.py` joins city items to RPC cases at page time, as
  `Rpc.link_county` does for the county. Reason: `rpc.json` and the city facts are rebuilt by separate steps on
  separate days; a stored join would go stale silently. K6 and K7 therefore live in sitegen and in `site_checks`.
- County: no data change.
- Export: `collector/export.py` city `items.csv` gains `zoning_case_number`, `zoning_case_source_id`,
  `zoning_case_page`, each with a provenance row (`value: "stated"`, cited page) in the registry that
  `tests/test_provenance.py` checks. `facts.json` export carries the object as is.

## The trail (what D2 builds from the data)
`sitegen/zoning_trail.py`: `build(rpx, county_ix, council_ixs) -> dict[case key, Trail]`, one `Trail` per distinct RPC
zoning case (prefixes `Z`, `ZO`, `CZ`, `CZO`). Steps in date order, each with its own source link:

| Step | From | Shown |
|---|---|---|
| RPC agenda | every `rpc.json` case entry with that key | date, agenda page link, the case fields as printed |
| RPC motion | `Rpc.motions` (`shown_motions`) with that `case_id` | only as `rpc_motion` renders it: confirmed values, or "Not confirmed" with the page link |
| Dates the RPC printed | `meetings[].hearings` of those agendas | "The agenda printed: City Council public hearing and first reading, May 4, 2023", with the agenda page; a link to our page for the meeting held on that date when we hold one. A meeting link, never an item link. |
| Council or Commission votes | linked item's roll calls and motions (`views` item rows) | each vote as the item page already shows it (verified and held-back rules unchanged), labelled with the reading **only as the minutes print it** |
| End | | see "Words the trail may not use" |

`Trail.link` is one of `county-number`, `city-bracket`, `none`. Canonical place: the case's entry on the RPC year
page (`Rpc.case_anchor`), newest agenda that lists it; the linked council or county item shows the same steps and
links back. (Judgment call: one macro in two places is the smallest thing that meets "one place that shows the trail
in order". A separate "all zoning cases" index is not in scope.)

### Fallback rule (no link)
For a city case with no `city-bracket` link, and a county case with no county item, the trail shows the RPC steps and
the printed dates, then exactly this, and nothing that suggests a result:

> "The City Council's records we hold do not print this case number, so this site does not link the case to a
> council vote. City Council zoning votes are on the council's pages: [meeting of <printed first-reading date>, when
> we hold it] · [City Council items, <year>]."

County wording: "No County Commission item with this case number is in our record (the record runs to <date>)."
The fallback never shows an ordinance number, a vote, an outcome, "pending", "approved" or "withdrawn".

### Words the trail may not use
- "Final vote", "adopted", "approved", "denied", "became law" as our own words. The last step is "Latest vote in our
  record", with the reading as printed. Reason (O10, I7): 12 of 14 linked ordinances have only the first reading
  attached; second readings are often adopted in a consent agenda vote filed under a heading.
- Where a linked city ordinance has no vote after first reading: "No later vote on this ordinance is in our record.
  Second readings are often adopted in a consent agenda vote, which the minutes record as one vote on several
  items." (A consent vote is attached to an ordinance only if the existing city rules already attach it.)
- "RPC recommended X" on any council or county page: only from a confirmed motion with `case_id` (existing rule).
  The council minutes' own line "RPC: Approval/Approval" may be shown as the minutes' words with its page, never
  merged with the RPC motion.

## Every consumer and what it must do
| Consumer | Where | Must |
|---|---|---|
| City reader | `collector/city_minutes.py parse_text` (heading and item-number lines), `collector/civicclerk` minutes path | hand the heading block to `zoning_link.read_bracket`; K1 to K4 |
| City build | `collector/city_build.py _add_minutes`, facts writer, the city build report | one call; K5 across documents; write `zoning_case` and `zoning_link_rules`; report held-back counts |
| Committed record | `data/localities/clarksville-tn/facts.json` | additive field; never a held-back value |
| Export | `collector/export.py` (`CSV_FILES` city items), `tests/test_provenance.py`, `site/templates/data.html.j2` | three columns with provenance; Data page names them |
| RPC export (task B) | `collector/rpc_export.py` | no link column in B. If added later: only `county-number` / `city-bracket` links, via `zoning_trail` |
| Join | new `sitegen/zoning_trail.py` | K6, K7, stale-rules gate; the only place a city link is computed. `Rpc.link_county` keeps the county rule; `zoning_trail` calls it, never restates it |
| RPC pages | `sitegen/rpc.py Rpc.meeting` (`cases[]`), `rpc_meetings_year.html.j2`, `_rpc.html.j2` | trail block or fallback per zoning case; today's county line (`rpc.py:257`) moves into the block |
| RPC home | `Rpc.home`, `rpc_home.html.j2` | counts only if added ("n cases linked to a vote by printed case number"); no rate, no claim about the rest |
| Council items | `sitegen/council.py items_year`, `views.item` (`"rpc"` key), `council_items_year.html.j2` | linked ordinance: case number as printed with source, RPC agenda entries, trail. Unlinked: nothing |
| Council meetings | `council_meetings_year.html.j2`, `_meeting.html.j2` | no new text. If the shared item macro shows the case number, it is the printed bracket with its source only |
| County items | `views.item` (`views.py:903`), `items_year.html.j2:37` | same block as council items; wording stays "linked by its case number" |
| Days / today | `sitegen/days.py rpc_card`, `today.html.j2` | agenda cases only, as now; may link to the case anchor; no link claim on a card |
| Feeds: topic | `sitegen/feeds.py` `topic-rezoning.xml` (`_topic_entries`, `_rpc_entries`) | unchanged in D2. A city ordinance joins the rezoning topic by link only (never by title words alone being absent or present changing meaning); adding linked city votes is D2b, after Nov 18 |
| Feeds: per seat | `feeds.py` kind `zoning-seat` (21 district + 12 ward) | entries are RPC cases by printed district or ward, as now. A council vote inherits a case's ward **only** through `city-bracket`; D2b |
| Morning note | `sitegen/morning.py` `_Zoning` (`county_case`, `_seat_fields`), `_index_documents`, `morning_page.py` | today county items inherit district and ward by exact number. A city item inherits them only through `zoning_trail` (`city-bracket`). No new entry type in D2 |
| Search | `Rpc.search_records`, `views.search_index`, `site/static/search.js` | a linked ordinance may add its printed case number to its searchable words, and the case its ordinance number; nothing for unlinked |
| Address / seats | `site/static/seats.js`, `district.html.j2` "Zoning near me" | printed district and ward of RPC cases only; no change |
| Transcripts | `sitegen/transcripts.py` | none. Spoken case numbers are never a key |
| QA | `qa/site_checks.py` | new `zoning-trail` check, below |
| Method page | `site/templates/method.html.j2` | one paragraph: how cases are linked, and that unlinked cases are shown without a vote |

## site_checks guard `zoning-trail` (restated from the data files, no import from collector or sitegen)
(a) every page element marked `data-trail-link="city-bracket"` names an ordinance whose `zoning_case.number` equals
the case shown, the case is in `rpc.json` with a city prefix, and its first RPC agenda date is on or before the
council meeting of `zoning_case.meeting_id`; (b) no case and no ordinance appears in two city links; (c) every
`county-number` link has equal keys on both sides; (d) a fallback block contains no `ORDINANCE`/`RESOLUTION` number
and no outcome word; (e) no trail text from our templates contains "final vote", "adopted", "denied", "unanimous";
(f) with `zoning_link_rules` missing or not current, no `city-bracket` element exists on any page.

## Tests the build must add
- Reader: the three printed forms link (fixtures cut from the real 2023-05-04, 2023-10-05 and 2025-08-07 minutes);
  `[Zoning Case #57-2023]` does not; a bracket in a motion sentence does not; a bracket on another ordinance's
  heading does not attach to this one; two cases in one bracket; OCR-only page.
- Build: same ordinance, two different brackets across documents: none; one case on two ordinances: neither; held-back
  counts in the report; `zoning_link_rules` written.
- Join: case not in `rpc.json`: printed number shown, no link; RPC date after the council date: no link; stale rules:
  no link; county link unchanged (the existing `link_county` tests still pass untouched).
- Pages: fallback block has no number or outcome; a linked ordinance with first reading only shows the "no later
  vote" sentence and never "final"; an unconfirmed RPC motion on a trail shows no values (existing rule, new place).
- Applicant match must not exist: a test with two RPC cases of one applicant and an ordinance with no bracket asserts
  no link (the tempting rule, pinned shut).

## Tasks
Order: D2a can start now (it needs no new data). D1 runs in parallel. D2b after both. Nothing here deploys.

### D1. Zoning link in the data (backend-engineer; opus, high: attribution family)
| # | Step | Files | Done when |
|---|---|---|---|
| D1.0 | Get the city minutes into a store: polite refetch of the listed city documents with the existing fetcher (10 s apart; about 95 minutes for all 559, or minutes only), or use the CI store cache. No new sources. | none (store is not committed) | `collector city run --offline` rebuilds the committed facts byte for byte before any change (385 meetings, 2,235 roll calls). If it does not, stop and report: the diff must be the new field only. |
| D1.1 | Dump every `ORDINANCE n` heading line since 2022 with its page, and count brackets by month. Append the table to `docs/research/zoning-trail.md` (closes unknowns 1 and 5; says from when the bracket is routine). | `docs/research/zoning-trail.md` | counts in the doc; fixtures cut for D1.2 |
| D1.2 | `read_bracket(heading_lines) -> Reading \| None` and `decide(readings) -> dict \| None` (K1 to K5), `ZONING_LINK_RULES`. | new `collector/zoning_link.py`, new `collector/tests/test_zoning_link.py` | reader tests above pass |
| D1.3 | Pass the heading block from the minutes reader; one call in the build; write the field, the marker and the report. | `collector/city_minutes.py` (heading and item-number branches of `parse_text` only), `collector/city_build.py` (`_add_minutes`, one call; facts writer), `collector/tests/test_city_minutes.py`, `test_civicclerk_minutes.py` | build tests pass; the 14 known pairs are in the output; no other field of facts.json changes |
| D1.4 | Export columns and provenance rows. | `collector/export.py` (city items only), `tests/test_provenance.py`, `tests/test_export*.py` | provenance test passes |
| D1.5 | Rebuild and commit the city facts; paste linked and held-back counts by reason and by year into the PR. | `data/localities/clarksville-tn/facts.json` | counts in the PR; full suite and `site_checks` pass |

Not in D1: fixing the empty 2022+ titles (unknown 3; raise it as its own task if D1.1 shows the cause), reading agenda
packets (unknown 2), collecting the 2023-11 and 2023-12 CivicClerk minutes. Each is a follow-up with its own size.

### D2a. Trail and fallback on the pages (frontend-engineer; opus, high; needs no D1)
| # | Step | Files | Done when |
|---|---|---|---|
| D2a.1 | `zoning_trail.build`: county trails by `link_county`, city trails by `zoning_case` when present and current, fallback otherwise; K6, K7. | new `sitegen/zoning_trail.py`, `sitegen/build.py` (one hook after `rpx.link_county(ix)`, line 433), new `tests/test_zoning_trail.py` | join tests pass on fixtures with and without `zoning_case` |
| D2a.2 | Trail macro; RPC case entries render it; county and council item pages render it and link back. | `site/templates/_rpc.html.j2` (new `zoning_trail` macro), `rpc_meetings_year.html.j2`, `items_year.html.j2` (lines 37 to 41), `council_items_year.html.j2`, `sitegen/rpc.py` (`Rpc.meeting` only), `sitegen/council.py` (`items_year` only), `sitegen/views.py` (`item`, the `"rpc"` key only), `site/static/style.css` (one block) | page tests above pass; on the committed data: 69 county items show a trail, city cases show the fallback |
| D2a.3 | `zoning-trail` check; Method paragraph. | `qa/site_checks.py` (new check only), `site/templates/method.html.j2`, `tests/test_qa_tools.py` | check passes on a real build and fails on a planted bad link |

### D2b. After D1 merges (frontend-engineer, small)
Turn on city links from the rebuilt facts (no code if D2a was built against the data shape), search words for linked
pairs, and decide whether linked council votes join the rezoning and per-seat feeds and the morning note's zoning
list. The feed change can wait until after Nov 18.

Shared files with other waves: `sitegen/views.py` (B and E touch `data_page` and `_nav`; D2a touches `item` only),
`collector/export.py` (B touches `export_site`; D1.4 touches the city items table), `_rpc.html.j2` and `sitegen/rpc.py`
(task A's rebuild changes data, not these files). Merge B before D1.4.

## Non-functional
- Performance: the join is a dictionary lookup over about 1,500 items and 1,341 cases at build time. No page weight
  concern: a trail is a short list on pages that already exist.
- Observability: the city build report, `zoning_link` (linked, held back by reason); the build summary prints
  "city zoning links: n of m cases". A drop in n between runs is reported like other shrink guards, not silently
  accepted.
- Security and privacy: no new input, host or secret. Applicant names are already printed public record on both
  sides; the trail adds none.
- Neutrality: the trail states what each document prints. It does not describe a case as contested, stalled or
  successful.

## Risks
| Risk | Effect | Mitigation |
|---|---|---|
| The city store is not where D1 runs (not in this container) | D1 cannot start | D1.0; D2a does not wait for it |
| The byte-for-byte rebuild in D1.0 differs (parser drift since the facts were committed) | D1 turns into a wider data change needing its own review | stop at D1.0 and report; ship D2a with the fallback |
| The bracket is rare in 2024 to 2026 (I2 wrong) | few city trails; the page is mostly fallback | fallback is designed as the normal case, not an error state |
| A reader pulls a bracket from the wrong heading | a wrong attribution, the worst failure of this site | K1, K5, K7, the 1:1 rule, `site_checks` (a), and a QA spot check of 20 linked pairs against the PDFs before merge |
| Pressure to link the other 250 city cases by applicant | fuzzy attribution | the invariant, the pinned test, I6 |
| RPC motions still unconfirmed until the RPC rebuild (task A) | trails show "Not confirmed" on the RPC motion step | intended; no dependency for merge |

## Decisions and assumptions
- Assumption: the city prefixes are `Z` and `ZO` (from `rpc.yml` case types). `HZ` (historic zoning, 5 entries) is not
  linked until a council document is seen printing one.
- Decision: join at page time, not in the data (reversible; see Data shape).
- Decision: no "probable" tier. `docs/research/rpc-cmcss-sources.md` floated one; it is withdrawn here.
- No ADR: this is an invariant for an existing family and an additive field, both reversible. No Brain Trust
  recommended for the same reason; a QA spot check of linked pairs is the control that matters.
