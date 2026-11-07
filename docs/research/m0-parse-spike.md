# M0 parse spike: Montgomery County Commission minutes

**Question.** Can deterministic code turn the County Commission minutes PDFs into accurate per-commissioner
roll-call votes and attendance?

**Answer.** Yes, if the scans are re-OCRed. On 11 minutes PDFs from 2020-2024 (144 roll calls), **138 (95.8%)
pass every spec P2 check (Verified)**. On a hand-labelled set of 21 roll calls read from the page images,
**0 wrong votes in 19 Verified roll calls (380 votes)**. The two roll calls held back were correctly held back. The
PDFs' own OCR text layer gets only 71/144 (49%) through on its own. A second reading made by re-OCRing the
page with tesseract brings the result to 95.8%. G4 as written (more than 2x the median held-back rate)
flags 8 officials. That is an artifact of this sample (explained below), and the rule needs a decision
before M1.

Date: 2026-11-07. Code: `collector/`. Reproduce: see the end of this file.

## Method

1. **Fetch** (`collector/fetch.py`, `collector/spike_fetch.py`). The fetcher reads robots.txt per host before
   anything else, waits at least 10 s between requests to a host (more if Crawl-delay says so), sends the
   User-Agent "clarksville-records research collector", and stops for a host on 403/429. Requests made:
   dev2.montgomerytn.gov robots.txt plus the index page; montgomeryminutes.bisonline.com robots.txt (404, so no
   rules) plus 11 PDFs. Hashes are in `data/manifest.json`; the picks are in `collector/spike_picks.json`.
   Index links for 2020-2021 are `http://`. They were fetched as `https://` on the same host because the
   sandbox proxy only carries HTTPS.
2. **Sample.** Two meetings per year where possible: Mar and Oct 2020, Feb and Aug 2021, Jan and Jul 2022,
   Mar and Oct 2023, the Apr 1 2024 special called meeting, Apr 8 2024 and Dec 2024. That is 11 PDFs and
   1,818 pages (the minutes PDFs include every resolution's full text).
3. **Extract** (`collector/extract.py`). `pdftotext -layout` reads the existing text layer, one entry per page.
   21 of 1,818 pages have almost no text (under 40 characters; mostly last pages and exhibits). No roll call
   was found on them, but tesseract-only detection was not run on them (spec AC-P4: mark them "not extracted").
4. **Parse** (`collector/parse.py`). Attendance comes from the meeting's own "BE IT REMEMBERED" header on page 1
   (present names, PRESENT n, ABSENT names (k), VACANT). Each roll call is a "District Commissioner Vote" table.
   For each one the parser reads the 21 cells (name, vote), the stated tally "Yeses - a Noes - b Abstentions - c",
   the per-vote ABSENT line, the outcome word ("was Adopted by the following roll call vote"), the mover and
   seconder, the item number (24-12-2, AB-4-2024, CZ-18-2020) and its title from the agenda.
5. **Verify (spec P2), per reading.** The roster comes from the attendance header (present plus absent), which
   is a source other than the vote table. The rules are written in code and apply the same way to everyone:
   - table names are matched one-to-one to the roster. Each pair must score at least 0.75 on name
     similarity, and the first name is compared too, so "Jerry Allbert" and "Randy Allbert" never merge;
   - every present member has exactly one Y/N/A, and members on the ABSENT line have none;
   - the counted Y/N/A equals the stated tally, and the tally plus the absences equals the roster size;
   - the outcome agrees with the tally ("pass" = Yes > No and Yes >= 11 of 21 seats).
6. **Second reading** (`collector/ocr.py`). Only for roll calls that fail on the text layer: the page is rendered
   at 300 dpi and run through tesseract 5.3.4 (installed here with `apt-get install tesseract-ocr`, free).
   The same table on that page is read the same way. A roll call is **Verified** only if at least one reading
   passes every check and no two readings disagree on any vote or on the stated tally. The cache keeps both
   readings for audit.
7. **Hand labels** (`collector/hand_labels.json`). 21 roll calls, read by eye from 200 dpi page images rather
   than from OCR text, compared by `collector/compare_labels.py`. The set covers absences, abstentions,
   failed votes, amendments, a vacant seat, a motion to table, suspending the rules, the special called
   meeting, an oddly laid-out page and a source document with an error in it. No recusal appears in the
   sample. The minutes record abstentions as "A" and show no other non-vote code.

## Observations

### Per document

| Minutes | Roll calls | Verified | Attendance header |
|---|---:|---:|---|
| March 2020 | 22 | 22 | passes count check |
| October 2020 | 25 | 24 | passes |
| February 2021 | 18 | 18 | passes |
| August 2021 | 22 | 22 | passes (vacancy) |
| January 2022 | 15 | 15 | passes |
| July 2022 | 21 | 20 | passes |
| March 2023 | 3 | 3 | passes |
| October 2023 | 4 | 4 | passes |
| April 1, 2024 (special) | 1 | 1 | passes |
| April 8, 2024 | 4 | 4 | passes |
| December 2024 | 9 | 5 | passes |
| **Total** | **144** | **138 (95.8%)** | 11/11 |

- Verified by which reading: text layer 71, tesseract 67. No Verified roll call has the two readings
  disagreeing; any disagreement holds the roll call back.
- Roll-call kinds found: consent agenda 68, resolution 57, amendment 12, procedural (motion to table and the
  like) 3, suspend the rules 2, minutes 1, nominations 1.
- Mover and seconder were resolved to a roster member for 127 and 128 of 144 roll calls. The rest are
  unresolved because the name is ambiguous or garbled, and they are left blank rather than guessed.
- An item number was found for 62 of 74 non-consent roll calls and a title for 54 of 62. Numbers are OCR'd
  ("20-3-1 1" read as 20-3-1) and need a check against the agenda list in M1.
- Detection coverage: every "by the following roll call vote" phrase in the text layer either has a table or
  is a parenthetical note on an attached resolution that points to a vote recorded elsewhere. No missed
  tables were found. This is a text-layer check only (see Unknowns).

### Hand labels (target: zero wrong votes among Verified)

| Result | Count |
|---|---|
| Labelled roll calls | 21 (9 documents, 2020-2024) |
| Verified | 19, covering 380 Y/N/A votes |
| **Wrong votes among Verified** | **0** |
| Held back (correctly) | 2: Oct 2020 p143 (table split by a blank gap); Dec 2024 p90 (source error, below) |

### The six held back (G4 input)

| Roll call | Cause |
|---|---|
| Dec 2024 p76, p87, p90 | **The source document contradicts itself.** Jason Knight is marked "Y" and Joe Smith "---", but the ABSENT line names Knight and Walker. Confirmed by eye on p76 and p90; both readings agree on p87. No automatic rule can resolve this, and it is correct to hold these back. |
| Oct 2020 p143 #2 | The table is pasted up with a blank band in the middle. The text layer drops 7 marks, and tesseract mis-segments the rows. |
| Dec 2024 p64 | One vote mark: the text layer drops it, and tesseract reads it as "©". |
| Jul 2022 p90 | The text layer drops marks, and tesseract misreads the stated tally ("0Q", "s"). |

Main failure causes on the text layer alone, as roll calls affected: a vote mark missing for a present member
(the cause for most of the 73 failures); counted tally not equal to stated (follows from the same drops);
garbled names (rare; one-to-one matching handles most).

### G4: held-back rate per official

Median 0.042. Twenty-three officials are at 0.02-0.06. **Eight are at 0.19 (4 of 21)**: Burkholder, Frye,
Gallant, Lankford, Padro, Shelton, Simmons and J. Walker, all first seated in 2022. Each has only 21 roll
calls in the sample, and 4 of their 21 were held back, 3 of them by the Dec 2024 source error. The literal
G4 rule (more than 2x median) flags all eight.

## Inferences

- **90% Verified is reachable, and this sample already shows 95.8%** (judgment, medium-high confidence; the
  sample is 144 roll calls, and 2023-2024 meetings have few roll calls because most items pass on consent).
  The step that makes it work is the second OCR reading. With the text layer alone it would be about 50%.
- **Wrong votes look very unlikely to reach a commissioner page** (medium-high confidence). Each Verified
  roll call has to satisfy four independent constraints (per-member marks, tally, ABSENT line, outcome) and
  agree across two readings. For one wrong value to pass, two errors would have to cancel exactly. The hand
  set found none. AC-P2's 20-vote spot check in M1 is still needed.
- **Holds are per roll call, so G4's per-official rate measures which meetings someone sat in, not bias
  against a person.** Within one roll call every official is held back together. Differences between
  officials come only from term membership and the sample. The 8 flags are this artifact. A per-person
  signal would be how often an official's own cell causes a hold. Here that is 0-4 per official, too few to
  judge.
- **Vote kind matters for neutrality (N2).** A "Yes" on a motion to table, or on suspending the rules, is not a
  "Yes" on the resolution. M1 must show the motion type next to every vote. The parser tags it, but the tag
  is heuristic.
- **Consent agenda votes (68 of 144) cover many items each.** M1 has to expand each one into per-item votes from
  the consent list, minus items pulled for separate votes, so that item history pages (US7) are right.
- **Attendance:** the meeting header gives attendance per meeting, and the ABSENT line under each roll call gives
  it per vote. In all 138 Verified roll calls the per-vote absences equal the header's. They could differ if
  a member arrives late or leaves, so M1 should keep both facts.
- **Display names need an authoritative roster.** Headers carry OCR errors too ("Randy Alibert" is the most
  frequent spelling in this sample). The merge rule groups the variants correctly, but the display name
  should come from the county's commissioner list.

## Unknowns

- Verified rate on the remaining ~51 meetings of 2020-2024, and on pre-2020 or 2025-2026 minutes (the
  location of the 2025-2026 minutes is still unknown).
- Roll calls whose table header is garbled in the text layer would not be detected. None were seen, but
  tesseract-only detection was not run on all pages (cost: about 2 s per page).
- Whether the county publishes historical commissioner rosters with districts and terms. That list would be
  the better P2 roster source.
- Voice votes or unanimous votes recorded without a table: none seen in the sample. Whether they exist
  elsewhere is not known.
- Attendance headers are count-checked (names read = PRESENT n, ABSENT (k)) for 11/11 but were not
  hand-labelled one name at a time.

## Recommendations

1. **Proceed to M1** with the two-reading pipeline (text layer, then tesseract for failures). Add tesseract
   (`tesseract-ocr`, free) to the environment setup.
2. **Decide G4 before M1 release (spec owner).** Proposal: keep reporting the per-official rate, but block only
   if an official has at least 50 roll calls in the period and their rate is more than 2x the median of
   officials who served in the same meetings. Also report holds caused by source errors separately. Under the
   literal rule this sample is "skewed", which the spec routes back to the CEO.
3. A path to about 97-98%: a third reading made by OCRing just the vote column at 400 dpi for the remaining
   OCR-noise holds (p64, Jul 2022 p90), and splitting tables at blank bands (Oct 2020 p143). Source-error holds
   stay held, with the reason "source document is internally inconsistent" on the review page.
4. Fetcher: an origin 403 means stop for good, but a 403 from the sandbox egress proxy is a different case.
   During this spike the first index request got a 403. The proxy status log recorded it as a rejected
   CONNECT ("gateway answered 403 to CONNECT"), so the county server never saw it. The fetcher stopped as
   designed. After checking the proxy log, one retry through the same fetcher and User-Agent succeeded. M1
   should tell the two cases apart automatically, and treat any 403 it cannot attribute as an origin block.

## Decisions and assumptions (recorded, reversible)

- "Pass" means Yes > No and Yes >= 11 (a majority of the 21 seats). Items needing two-thirds would still
  pass this check; it guards against contradiction, not against misreading voting rules.
- The glyph rule: a vote token made only of one letter's look-alikes is that letter ("¥", "YY", "Y-"). Mixed
  letters, and any token that is not a vote ("g", "q", "©", "WN"), fail the roll call. Nothing is mapped by
  guess.
- A single dash with no vote counts as an absence mark (OCR collapses "---"). With a vote, it is ignored as
  noise. Either way the ABSENT line and the tally must agree.
- The embedded previous-meeting minutes ("SUBMITTED FOR APPROVAL") are excluded from attendance. They hold no
  roll-call tables.
- Using tesseract adds no LLM. Everything is deterministic.

## Reproduce

```
pip install pytest ruff            # tests and lint only; the collector is stdlib-only
apt-get install -y poppler-utils tesseract-ocr
python3 -m collector.spike_fetch index && python3 -m collector.spike_fetch pick   # ~2 min, 10 s/request
python3 -m collector.run_spike --ocr      # ~2 min; writes data/out/rollcalls.json
python3 -m collector.compare_labels
python3 -m pytest -q && ruff check collector
```

Test output (2026-11-07): `39 passed in 0.46s`; `ruff check collector`: `All checks passed!`
