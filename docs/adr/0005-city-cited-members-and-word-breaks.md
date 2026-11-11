# ADR 0005: Cited members and word-break-free name matching for the city

Status: proposed (software-architect, 2026-11-11; problem family `city-verify`). Detail and tests:
`docs/architecture/city-council.md`, "Verified-rate plan". Builds on the name resolution invariant there and on
"Invariant: independent readings" in `docs/architecture/clarksville-records.md`.

## Context
City roll calls are 1,756 of 2,235 verified (78.6%); AC-P1 asks 90%. 62 roll calls at four 2026 meetings are held
because the attendance prints CLAUNCH and no stored record printed a Claunch as a member. 42 more are held by two
printed names the reader cannot match: "J eff Henley" (2020-10-01, a zero-width space in the text layer between
glyphs that touch) and "StaceyStreetman" (2022-04-07, printed with no space). Vote lists also print breaks inside
names ("H AYWOOD"). The rule is that a vote is verified only when the official record supports it; a check is never
loosened to raise the number.

## Decision
1. **`members` config entries** (like `mayors`): name, ward, `seated`, kind of record, URL, page and quote of an
   official record of the seating (minutes, resolution, oath record, the City's roster page snapshot, certified
   results). The build checks the quote is on that page of the stored file; otherwise the entry is ignored and the
   name stays held. Applicant lists, agendas, prose, transcripts, news and our inference never qualify. First entry:
   Eric Claunch, Ward 2, seated 2026-02-19, from the City Council Special Session minutes of 2026-02-11 (resumed
   2026-02-19) p. 3, which CivicClerk files under category "General" (the listing is widened for it).
2. **Format characters**: the city reader deletes Unicode Cf characters and joins words they separated only when the
   glyphs touch, so the text equals what the page shows.
3. **Break-free key** as the last resolution step: whitespace removed, nothing else changed, exactly one match in the
   meeting's own closed set (roster book for attendance, the meeting's roster for votes and motions), every P2 check
   unchanged after it, every use listed in the run report.

## Alternatives considered
- **Hold everything as printed** (do nothing): safest by construction, but it hides 66 roll calls whose every printed
  letter matches a member, and leaves Ward 2 "not yet recorded" for most of 2026 when an official record names him.
- **Per-name aliases** (the existing `aliases` list): works for "StaceyStreetman", but needs a hand entry for each
  break, and `aliases` is for full names only and deliberately never touches vote names.
- **Edit distance or near-spelling merges** (STRETMAN, AYWOOD, PITT): rejected. That is a guess, and it would turn
  source errors into confirmed votes.
- **Use the transcript or video to identify CLAUNCH**: rejected. It is our machine reading, not the official record.

## Consequences
- Estimated 1,822 of 2,235 verified (81.5%); 2026 from 14 to 53 of 83. 90% is still out of reach: the 413 still held
  are omissions and misspellings in the minutes themselves. The launch treatment for them is a decision for Brian
  (architecture doc, "Launch treatment"; recommended: ship with held votes shown link-only and a plain reason).
- Every configured member needs a stored, quoted official record, so the 2027 seating needs entries before its
  meetings are built (`city-votes/empty-book-2027`).
- Residual risk (judgment, medium confidence): a printed break-only difference could hide a real different person
  whose name differs from a member's only by spaces; the unique-in-the-meeting's-roster guard and the unchanged P2
  checks make that improbable, and each use is listed for QA's spot check.
