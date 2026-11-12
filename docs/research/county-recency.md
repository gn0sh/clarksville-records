# County Commission recency (checked 2026-11-10)

## Verdict
The gap is the county's posting lag, not a collector bug and not the "4 missing" minutes.

## Latest meeting each source shows
| Source | Latest | Notes |
|---|---|---|
| Our facts.json / store | meeting 2026-05-11 (formal) | 59 minutes PDFs, coverage 2020-02-10 to 2026-05-11 |
| Clerk minutes page (live, https://montgomerytn.gov/clerk/county-commission-minutes) | "May 2026 Minutes" | Same bisonline link we already hold (sha 93343719). No June to Oct 2026 links. Each packet is the meeting's own minutes plus the previous meeting's minutes for approval, so the county posts nothing until a packet is complete |
| Agendas page (https://montgomerytn.gov/commission/agenda) | Nov 2026 formal, posted 2026-11-09 | Informal Nov posted 2026-11-02 |

## Cause
- Collector discovery (collector/discover.py) lists every bisonline link on the clerk page; the live page has nothing newer than May 2026, so nothing is missed. Roughly 6 monthly meetings (Jun to Oct) have no minutes online.
- "4 missing" are the manifest minutes for 2020-03, 2020-10, 2021-02, 2021-08 (PDF absent from the store). They are old, so they cannot explain a 2026 gap. Refetching them is a low-priority completeness fix.
- Not verified: whether BIS Online's own search (montgomeryminutes.bisonline.com) holds later minutes the clerk page does not link. A search is a form request, and the collector never guesses routes (spec A4). Needs a decision before trying.

## Upcoming agendas we do not collect
- The agenda page lists informal and formal PDFs for all of 2026 (pattern .../agendas-and-resolutions/2026/<mon>-informal|formal.pdf).
- Live HEAD checks (5 requests, 11 s apart, robots.txt allows all): jun-formal 2026-06-08, oct-formal 2026-10-16, nov-informal 2026-11-02, nov-formal 2026-11-09 are real PDFs (6 to 19 MB). dec-formal is a 6 KB placeholder dated 2026-04-02 (not a real agenda; treat links with small size and old Last-Modified as "not yet posted").
- The collector has no county agenda adapter (discover.py is minutes only). Already-known caveats: some links are wrong (Oct 2023 formal points to the informal) and some are relative paths.
- Meeting dates are not on the page. Nov formal posted Mon 2026-11-09 suggests a meeting on or just after that date; the date must come from PDF text (cover page) or the second-Monday pattern (all 2026 minutes meetings fell on Mondays: Jan 12, Feb 9, Mar 9, Apr 13, May 11), never guessed.

## Fix and estimate
1. Day cards: for county days after 2026-05-11 show "Agenda" (link to the PDF) when an agenda exists, "Scheduled" when the page links a placeholder or nothing, and "Minutes not yet posted by the county" otherwise. About 0.5 day, no new host.
2. County agenda adapter (collector/county_agenda.py): fetch the agenda page once per run (1 request), parse links, HEAD or GET each new PDF politely (10 s delay), keep only PDFs over about 100 KB, read the meeting date from the first page text, store as kind agenda with kind informal|formal. About 1 to 1.5 days with tests. Cap: one index request plus new PDFs only.
3. Optional: BIS Online search check for June to Oct minutes. About 0.5 day after the policy decision.
4. Refetch the 4 old minutes: 1 hour, low.
5. Run the collector on the normal schedule; the minutes will appear by themselves once the county posts them. Show an "as of" date on county pages so the lag is visible.

## Done (2026-11-10)
- Fix 2: collector/county_agenda.py, run by `collector run` (so the daily update; workflow permissions and limits unchanged).
  First run: 1 page request, 16 links wanted (May to Dec 2026), 14 agendas stored (May to Nov, informal and formal),
  2 placeholders skipped (Dec informal and formal, 6,097 bytes), 142 items read, 0 problems. 13 meetings shown as
  agenda-only (May 11 formal is covered by its minutes).
- Fix 1: day cards and meetings/agendas.html (sitegen/county_agendas.py).
- The 4 missing minutes (2020-03, 2020-10, 2021-02, 2021-08) were requested again at their manifest URLs: all 4 landed,
  byte-identical to the manifest (status unchanged), so data/manifest.json and facts are unchanged.
- Decision recorded: no BIS Online search-form requests (fix 3 not done).
