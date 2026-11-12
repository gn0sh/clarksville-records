# Code review: M4 slice 3, CivicClerk 2024+ (1bc303c..e136a8b), 2026-11-09
Verdict: REQUEST CHANGES.
- MEDIUM city-votes/surname-stale-book, collector/city_build.py:216, 349-353: the surname book keeps each surname's latest full-name printing with no time limit, and the capital-letter lists carry no wards. A new member who shares a surname with a departed member (ALLEN, REDD, LITTLE, REYNOLDS...) would resolve silently to the departed member, with verified votes. That breaks "ambiguity must hold". The current data is unaffected.
- LOW city-pages/year-run-label, sitegen/build.py pack_years: a page labelled "2018-2023" holds only 2018 and 2023, which implies service in the years between.
- LOW city-merge/dropped-citation: the 2024-01-04 Agenda Center agenda URL is no longer cited in the facts.
- LOW city-votes/titled-scan: safe direction (holds only).
Checked and fine: no roll call or meeting lost or changed against 1bc303c; ZAHARIAS/CLAUNCH meetings held; Amber->Ambar alias justified; shared minutes file not double-read; 2024-01-04 deduped; ADR and politeness; 65 https video URLs; 0 broken member links; 5 roll calls from 2025 match the PDFs.
