# Agenda withhold invariant (loop rule: `privacy-withhold`, hit 3)
History: hit 1 `privacy-withhold/fail-open` (security review of r2-county), hit 2 `privacy-withhold/first-line-only`
(re-review 30de62d..dab7370), hit 3 `privacy-withhold/prefix-kept` (fresh review dab7370..716f0bb: names printed
before the award words, or with the award words on a later line, were stored: "6:02 Jane Doe and John Roe / Point of
Pride Award recipients", "4. Jane Doe, Student of the Month"). Every hit came from the same design: cutting private
names out of free text with a deny-list of award words. That design is retired.

## Decision (manager, 2026-11-16, ADR-style)
- **Context.** School board agendas print students' names in recognitions, before, after or around the award words,
  in layouts that vary meeting to meeting. A pattern list cannot tell a name from an item, and every fix left a gap.
- **Decision.** For the school board, store and publish **no agenda item text at all** for now. County finance
  committees are unchanged.
- **Consequences.** A school board meeting shows only its body, its meeting type and date as the county's listing
  prints them, the official agenda PDF link, the number of agenda lines (a count), and the dashed COMING minutes note
  linking cmcss.net. Readers open the PDF for the items. School board item text returns only after an architect re-plan
  with an **allow-list** design (show only item shapes known to be safe), reviewed by security first.

## The invariant
**School board: no item text is stored (no title, no entry, in any file or page), only the count of lines. County
finance committees: item text as printed, and no withhold is needed** (their agendas are resolutions, budget lines and
bids, not recognitions).

How it is held:
- `config/localities/montgomery-tn/committee-agendas.yml`: the school board body has `text: false`. A `withhold` key is
  a config error (the deny-list code is deleted: `cut_withheld`, the withhold rules and the section-dropping logic).
- `collector/committee_agenda_text.build`: for a `text: false` body the meeting keeps `title: null`, `entries: []` and
  `lines` (the count of entries read). The text is read in memory to count it and never written.
- `qa/site_checks.py` checks the output directly, without the reader's code: every school board meeting in
  agendas.json has no title, no entries and no key beyond the known ones, and no school board page (the hub and
  everything under `school-board/`) has a `data-item-title`, an agenda line list or an item.

## Every consumer
| Consumer | Reads for the school board | Holds the invariant because |
|---|---|---|
| `data/localities/montgomery-tn/committee-agendas/agendas.json` (committed, public repo) | written by `build` | `title: null`, `entries: []`, `lines` only (21 meetings, 301 lines, 2026-11-16) |
| Meeting pages (`site/templates/_committee.html.j2`, `school-board/meetings/<year>.html`) | `lines`, the listing label, the PDF link | a `text: false` body prints "This agenda has N lines." and the site.yml `county_committees.no_text` note, no items |
| School board hub (`school-board.html`) | meeting dates and types | lists meetings by date and type only |
| Search (`search_records`, the `z` field) | `entries` of numbered items | none for the school board, so `z` is empty |
| Day cards (`sitegen/days.py` `committee_card`, today page) | `lines` | a count and a link; no item text |
| Feeds (`sitegen/feeds.py`) | nothing | no feed includes these meetings |
| County Commission links (`Committees.link_county`) | `entries[].number` | none for the school board |
| Daily report (`build/county-committees-report.json`) | problems and counts | no item text |
| `qa/site_checks.py` `check_county_committees` | agendas.json and the built pages | the gate above |

The stored PDFs (`data/store`, gitignored, Actions cache) hold the full text; they are the county's own public files and
are linked, not reprinted. A history check of r2-county (every commit that wrote agendas.json: c97dd87, e21b5d8,
e69ed6a) found no student name stored in any version.
