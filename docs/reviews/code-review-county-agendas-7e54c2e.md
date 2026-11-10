# Code review: county agendas 7e54c2e (2026-11-10)
code-reviewer, opus/medium. Verdict: APPROVE WITH NITS. Real diff b515810..7e54c2e (7de0197 is a sibling). 126 pass.

1. should-fix provenance/agenda-revised-in-place, collector/county_agenda.py cmd_fetch: a stored agenda is never re-requested; revised PDFs at the same URL go stale. Fix: until the meeting date passes, re-request at most once per run (conditional GET if PoliteFetcher can); new bytes = new store version; test.
2. should-fix neutrality/unverified-county-claim, sitegen/county_agendas.py minutes_note: "The county clerk's minutes page lists no minutes for informal sessions" is unverified. Verify + record in platform-facts.md, or say "This site holds no minutes for informal sessions."
3. nit item-history/earlier-record-label, county_agendas.html.j2:180 "Earlier record of" links to a later vote; use "Record of {number} in the minutes".
4. nit neutrality/after-the-minutes-copy, meetings_index.html.j2:204: informal agendas never pruned; reword or drop old informal sessions.
5. nit verified-gate/agenda-card-chip, today.html.j2 county agenda card lacks the "Agenda" chip.
6. nit idempotence/special-hidden-by-same-day-formal, sitegen/county_agendas.py:390: match on meeting id or date+kind.
Holds: parsing, sources, no votes from agendas, politeness, idempotence, neutrality, locality.
