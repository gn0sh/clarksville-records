# Zoning trail spike (task D0): is there an exact key from an RPC case to the final vote?

software-architect, 2026-11-10. Base: integration tip 9014292. Read-only on product code and data. **No network
request was made.** Sources read: the committed data (`data/localities/cmc-rpc/rpc.json`,
`data/localities/clarksville-tn/facts.json`, `data/facts.json`), the committed test fixtures, and 7 RPC agenda PDFs from
the store copy at `/mnt/project-files/clarksville-records/rpc-store/`.

## Verdict
**Partly.** An exact key exists and it is the clerk's own: from May 2023 the City Council minutes print the RPC case
number in square brackets on the ordinance's heading line (`ORDINANCE 107-2022-23 [Z-22-2023] (First Reading) ...`).
It is not on every case, and most of what the stored minutes print could not be measured here, because **the city
document store is not in this container** (only the RPC store copy is).

| Side | Exact key | Measured now, committed data | Ambiguity |
|---|---|---|---|
| County | the Commission's item number is the RPC case number (`CZ-`, `CZO-`) | 69 of 92 county items link; 69 of 91 distinct RPC county cases link; sample 24 of 30 | none: 0 keys with two county items |
| City | case number printed in brackets on the ordinance heading in the council minutes | 13 of 268 distinct `Z-` cases and 1 of 14 `ZO-` cases; sample 1 of 40 | none in the 14 pairs: one case per ordinance, one ordinance per case |
| City, ceiling | same key, in stored minutes not readable here | between 14 and 131 of the 184 council zoning ordinances since 2022-02 | unknown until read |

So: the county trail is real today. The city trail is real for the cases whose minutes print the bracket, and D1 has to
read the stored minutes to find out how many that is. For every other city case there is no exact key in anything we
hold, and the fallback below applies.

## Observations (each is a count from a file, or a line in a file)

**O1. RPC side.** `rpc.json` holds 349 `Z-` agenda entries, which are 268 distinct case numbers (a case comes back on
later agendas after a deferral): 86 in 2022, 71 in 2023, 23 in 2024, 54 in 2025, 34 in 2026. 40 `ZO-` entries are 14
distinct text amendments. Every number passes `collector.rpc_minutes.link_key`. (M1)

**O2. City side, items.** None of the 1,501 `items[]` carries a case number, as the audit said. The reason is wider
than the audit stated: **from 2022 on the city items have no title at all** (empty title: 160 of 189 items in 2022, 90
of 106 in 2023, 95 of 105 in 2024, 100 of 111 in 2025, 53 of 60 in 2026). The applicant and location the audit saw in
titles are on 2016 to 2021 items, before RPC coverage starts (2022-01-25).

**O3. City side, the printed key.** The bracket survives in the committed record only where the heading line happened
to be kept in `motions[].text` / `item_events[].label`. 14 pairs are there (M2), all of them from three meetings in
2023:

| Council meeting | Pairs | Form printed |
|---|---|---|
| 2023-05-04 | 107, 109, 110, 111, 112-2022-23 with Z-22, 24, 25, 26, 27-2023 | `ORDINANCE 107-2022-23 [Z-22-2023] (First Reading)` |
| 2023-07-06 | 143, 144, 145-2022-23 with Z-34, 35, 36-2023; 147-2022-23 with ZO-1-2023 | same |
| 2023-10-05 | 30, 31, 32, 33, 34-2023-24 with Z-51, 52, 53, 54, 55-2023 | `ORDINANCE 30-2023-24 (First Reading) [Zoning Case #Z-51-2023]` |

For all 14: the item id the vote is recorded under is that ordinance; the case is on an RPC agenda we hold; the RPC
agenda date is before the council meeting (9 days before for the 13 `Z-` cases); no ordinance has two cases and no
case has two ordinances. For the 2023-05-04 and 2023-10-05 groups the RPC agenda itself prints that council date as
"CITY COUNCIL PUBLIC HEARING & FIRST READING". The applicant printed beside the bracket equals the RPC's applicant
string for 7 of the 14; the others differ in punctuation or wording (council "Reda Home Builders, Inc", RPC "Reda
Home Builders Inc") or the kept text is cut short. The printed number links all 14; the name alone would not.

**O4. A third printed form, from the CivicClerk years.** The committed fixture in
`collector/tests/test_civicclerk_minutes.py` (lines 83 and 100, the 2025-08-07 Regular Session minutes) prints
`ORDINANCE 05-2025-26 (FIRST READING) [ZONING CASE Z-29-2025]` and `ORDINANCE 06-2025-26 (FIRST READING) [ZONING CASE
Z-30-2025]`. Both cases are on the RPC agenda of 2025-07-29 with the same applicants as the fixture (Charles Thomas
Jerles; Donny Ray Plaster, Jr.), and that agenda prints "CITY COUNCIL PUBLIC HEARING & FIRST READING August 7, 2025".
Both ordinances are items in the city facts. Neither pair is in the committed record: the reader did not keep the
heading. (M8)

**O5. A bracket without a prefix.** The 2024-01-04 minutes print `ORDINANCE 41-2023-24 (Second Reading) [Zoning Case
#57-2023]` and `49-2023-24 ... [Zoning Case #65-2023]`: a number with no `Z-`. (M2)

**O6. How often the bracket is printed, as far as the committed record shows.** 184 council ordinances since 2022-02
have a kept motion text that reads as a zoning case (81 in 2022, 49 in 2023, 34 in 2024, 23 in 2025; none of them has
a title). By what the kept text shows (M8):

| Half-year | Bracket printed | Heading kept, no bracket | Heading not kept (unknown) |
|---|---|---|---|
| 2022 H1 | 0 | 12 | 30 |
| 2022 H2 | 0 | 13 | 25 |
| 2023 H1 | 5 | 15 | 4 |
| 2023 H2 | 9 | 12 | 2 |
| 2024 H1 | 2 (no prefix) | 1 | 26 |
| 2024 H2 | 0 | 0 | 5 |
| 2025 H1 | 0 | 0 | 20 |
| 2025 H2 | 0 | 0 | 3 |
| **Total** | **16** | **53** | **115** |

The 53 are observed absences: the heading is there and prints no case number (all of 2022; 2023-06-01, 2023-08-03 and
2023-09-07 print none, between meetings that do). The 115 are unknown, not absent.

**O7. The RPC never prints the council's number.** 7 RPC agendas sampled across 2023 to 2026 (text layer, M9): 0
ordinance numbers in any. Each prints, per case, a tax map and parcel, and once per agenda the dates of the City
Council informal session and "PUBLIC HEARING & FIRST READING" and of the two County Commission meetings. Those dates
are already in `rpc.json` (`meetings[].hearings`, with page and source): 52 RPC agendas print a council first-reading
date, we hold a regular council meeting on that date for 50 of them, and its minutes are read for 37. (M8)

**O8. The council side has no parcel.** No kept council text prints a tax map or parcel number. The council prints
applicant, location in words and the from/to districts.

**O9. Applicant name as a key, measured so it can be ruled out.** Of 63 first-reading zoning motions since 2022-02
whose kept text prints the applicant, the applicant string (case and punctuation folded, otherwise exact) matches one
RPC case heard in the 3 months before for 29, several for 8, none for 26. 33 RPC applicants hold more than one `Z-`
case: 84 of the 268 cases (Terrence Burney six, Hunter Winn five). (M5)

**O10. What the council record attaches to a linked ordinance.** Of the 14 linked ordinances, 12 have roll calls at
one meeting only (the first reading); 2 have a later reading attached. 144 roll calls since 2022-02 are recorded on a
heading (consent agenda and grouped votes), not on a numbered ordinance. Of the 810 city roll calls since 2022-02,
520 are verified and 290 are not. (M7)

**O11. County side.** 92 county items carry a `CZ-`/`CZO-` number, 92 distinct, none shared. 69 match an RPC agenda
case by `link_key` (87 RPC agenda entries link). The 23 that do not: 8 from 2020 and 8 from 2021 (before the RPC
listing starts, 2022-01), and CZ-1 to CZ-6-2024 and CZO-1-2024. From the RPC side, 69 of 91 distinct county cases
have a county item; of the 22 without, 11 were first heard at the RPC in or after May 2026 (the county record ends
2026-05-11) and 11 earlier: CZ-12, 18, 23-2022, CZ-1, 9, 11-2023, CZ-7, 8-2024, CZ-1-2025, CZ-1-2026, CZ-4-2026.
91 of the 92 county items have a roll call. (M6, M7) The audit's "68 of 92" is 69 by `link_key`; the difference is one
number the plain normalisation missed.

## Inferences (reasoned, not measured; confidence stated)
- **I1. The minutes are where the key is, and D1 can only raise the count.** High confidence. O3, O4 and O6 show the
  clerk printing the bracket in three forms across 2023 to 2025, and the reader dropping the heading in most
  CivicClerk-era motions. Reading the bracket from the stored minutes will link more than 14; how many is unknown.
- **I2. From some point in 2024 or 2025 the bracket is routine.** Medium confidence, on thin evidence: one 2025
  meeting, 2 of 2 (O4), and the two 2024-01 brackets (O5). If true, most of the 115 unknown link and the last two
  years of city cases get a trail. If false, the city trail stays thin and the fallback carries the page.
- **I3. 2022 and part of 2023 have no exact key in the minutes.** High confidence for the 53 observed absences. The
  council agenda packets for those meetings may still print it (see Unknowns).
- **I4. The seven 2024 county cases with no RPC agenda fall in the RPC's missing months.** Medium confidence:
  `docs/research/rpc-cmcss-sources.md` records that 2024 Feb to Apr agendas lag and that 16 links, mostly 2024, point
  at Google Drive, a host we do not collect from. Not checked case by case.
- **I5. The 11 older RPC county cases with no county item were withdrawn, deferred without return, or heard at a
  Commission meeting whose minutes we lack.** Low confidence; a reason per case needs the RPC minutes motion
  (confirmed only) and is D2 work, shown as "no County Commission item with this number in our record", never as an
  outcome.
- **I6. Applicant, location and date are not an exact key and must not be used as one.** High confidence, from O9:
  a third of the cases share an applicant with another case, and 26 of 63 printed applicants match no RPC string
  exactly, so any rule loose enough to match them is a fuzzy rule. It also happens to agree with the printed key on
  every pair where both exist, which is exactly why it is tempting and why it is ruled out in writing.
- **I7. "Final vote" is often not attached to the ordinance on the city side.** High confidence, from O10: second
  readings are commonly adopted in a consent agenda vote, which the record files under a heading. A linked city trail
  will usually end at first reading. The page has to say so and must never label the last vote it holds as final.

## Unknowns
1. How many of the 115 "heading not kept" ordinances print a bracket, and from which month it is routine. Needs the
   city minutes PDFs (already collected: 200 minutes sources in the city manifest; not in this container).
2. Whether the council **agenda** PDFs (359 stored sources, some of them packets of 100+ pages) print the case number
   for the 2022 to 2023 cases whose minutes do not. Same store.
3. Why the 2022+ item titles are empty (O2). It is the same lost heading; D1 will meet it. Out of scope here, but the
   fallback's "council zoning items" list cannot rely on titles while it stands.
4. Whether a case can lawfully come back under a second ordinance number (a reapplication; RESOLUTION 05-2024-25
   "authorizing reapplication for zone change" suggests it can). None seen in 14 pairs. The invariant holds both back
   until someone reads a real example.
5. Whether `[Zoning Case #57-2023]` always means `Z-57-2023`. Not assumed: no link.
6. Whether the RPC minutes or a staff report print the ordinance number. 7 agendas say no for agendas; 83 of 88
   minutes are scans read by OCR and were not searched for this.

## Where a key might exist that we have not collected (not fetched; for a later decision)
| Source | URL pattern | What collecting it would take |
|---|---|---|
| City minutes and agendas already listed | `https://www.clarksvilletn.gov/AgendaCenter/ViewFile/...`, `https://clarksvilletn.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=N,plainText=false)` | Not new collection: a refetch of documents in `manifest.json` into an empty store by the existing polite fetcher. clarksvilletn.gov robots: `/AgendaCenter` allowed, Crawl-delay 10. All 559 city sources at 10 s is about 95 minutes; the 45 regular-session minutes since 2022-02 alone are about 8 minutes. The CI Actions cache also holds the store. |
| CivicClerk minutes for 2023-11 and 2023-12 | same API, events before `from_date` 2024-01-01 | `docs/platform-facts.md` line 162 records they exist and are not collected. A config change (`from_date`) and two or three more files. Would close a gap right where the bracket becomes common. Needs its own small task; not in D1. |
| CivicClerk agenda item records | the OData API under `https://clarksvilletn.api.civicclerk.com/v1/` (per-event items; exact path unverified) | Unverified that item records exist or carry a case number. One polite request to find out, in a later spike. |
| RPC staff reports and case files | not on the one listing page we read (`https://www.cmcrpc.com/documents/agenda-minutes/`); location unknown | Unknown. cmcrpc.com is crawl-delay 10 and answered 429 during the refetch on 2026-11-10; nothing should be added there until that settles. |

None of these is needed for the Nov 18 scope.

## How to reproduce
From the repo root, at 9014292 or later, no network:

```
python3 -B docs/research/zoning-trail-spike/m1_m6_link_counts.py     # M1-M6: cases, printed pairs, samples, county
python3 -B docs/research/zoning-trail-spike/m7_readings.py           # M7: readings attached to linked items
python3 -B docs/research/zoning-trail-spike/m8_bracket_seen.py       # M8: bracket seen / absent / unknown; hearing dates
python3 -B docs/research/zoning-trail-spike/m9_rpc_agenda_sample.py /mnt/project-files/clarksville-records/rpc-store/
```

The scripts are labelled spike scripts: read-only, standard library plus `collector.rpc_minutes.link_key`, `pdftotext`
for M9. Samples use `random.seed(20261110)` over the sorted distinct case numbers: 40 `Z-` cases (1 linked:
Z-52-2023) and 30 `CZ-`/`CZO-` cases (24 linked; not linked: CZ-9-2023, CZ-4, 7, 8, 9, 13-2026). M9 names eight
agenda dates and reads the seven that have a text layer (2023-04-25, 2023-09-26, 2024-08-27, 2025-07-29, 2025-09-23,
2026-03-24, 2026-09-22). Delete the scripts when D1 merges; its tests replace them.

## Limits of this spike
- The city PDFs were not read. Every city number above is from the text the committed record kept.
- "Reads as a zoning case" (O6) is a pattern on kept text (`zone change`, `RPC:`, `Zoning Ordinance and Map`, `zoning
  code and map`). It is a measuring device for this note, not a rule for the product.
- 2026 council zoning votes do not appear in O6: their kept text matches none of those words. Unknown, not zero.
