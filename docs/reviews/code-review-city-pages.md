# Code review: M4 slice 2 (city pages), f537938..89b94b2, 2026-11-09

Verdict: REQUEST CHANGES

- MED-HIGH city-pages/current-basis: the landing's "City wards" list sits under the county's "Current" basis line (2026-05-11). The city's "current" is 2023-10-05, so the list needs its own basis line.
- MED-HIGH city-pages/cross-body-name-link: build.py:279-281 `extra_names` links county officials' names found in city item titles. Example: the "sale of property ... to Tangi Smith" ordinance links to Commissioner Tangi Smith with no proof it is the same person. Same-body applicant names in zoning titles carry the same risk.
- MEDIUM city-pages/page-weight: the city member page is 3.8 MB (about 2,000 rows) and a meeting-year page is 2.6 MB.
- LOW city-pages/current-basis: the city home basis says "attendance lists", but the Mayor's seat comes from roll calls.
- LOW city-pages/ward-misprint: a run of 1 ending at the latest minutes would drop a newly seated member.
- OK: the Mayor seat from confirmed roll calls; Brian is rendered exactly like every other member; 3 roll calls spot-checked; held votes show Not confirmed*.

## Manager decision (2026-11-09)
Names inside item titles are text in the document (applicants, buyers, agents), not an official acting, so they do not link to an official's page in any body. Names link where the minutes record an official acting (attendance, motions, votes). This narrows "every official's name links" to names that identify the official. Recorded in docs/status.md.
