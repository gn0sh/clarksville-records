# Code review: M4 slice 1 (city Agenda Center collector), 904848b..8c17453

Verdict: REQUEST CHANGES (2026-11-09)

1. HIGH city-votes/item-link, collector/city_minutes.py:366-377, 341-353: votes are linked to the wrong numbered item. Example: the 2016-01-07 Consent Agenda vote is linked to ORD 46-2015-16 only because the paragraph says Grubbs abstained on it, so the facts show Grubbs voting yes on an item he abstained on. 6 Consent Agenda votes are linked to a single item. Procedural votes (e.g. a failed adjourn motion on 2021-03-04) inherit the previous item. Fix: link only when the motion or outcome sentence refers to the item; never for Consent Agenda, adjournment or appointments; hold the roll call on a kind contradiction; add negative tests.
2. MEDIUM city-motions/title-regex, city_minutes.py:27: TITLES lacks "Councilperson" (used from 2021), so motions drop to near 0 and NOTE absences are not read.
3. MEDIUM city-items/title-overrun, city_minutes.py:344-347: item titles absorb motion and vote text (7 items), and an AYE line inside such a paragraph is silently dropped.
4. LOW fetch/reset-retry, collector/fetch.py:208-212: no per-run cap on reset retries; the test does not assert the delay before the retry.
5. LOW city-votes/part-time-exempt, city_build.py:302: an arrived/left note exempts that member from the missing-vote check for the whole meeting.

Checked and sound: name resolution, the alias scope, outcome checks, additive schema (both facts files validate), no cityofclarksville.com or CivicClerk contact, neutrality, tests. 5 roll calls spot-checked against pdftotext: all correct by person.

## Delta re-review (1ea1e44..f1dedd8), 2026-11-09: APPROVE with follow-up
All 5 findings were fixed. 5 newly linked verified roll calls were spot-checked and are correct. 252 of the 258 new links print the item number in their own outcome sentence.
- MEDIUM city-votes/item-link (second hit in this family): the section-only branch of `_item_for_vote` uses `last_sentence(window)`, so a number mentioned in passing just before the AYE lines (an abstention note) still links. No verified roll call in the current data is affected. Under the loop limit, the architect states the invariant before the fix.
- LOW city-votes/outcome-text: rc-75d3ffaf-p10-2 has a vote block broken by a page number. It is held, not wrong.

## Delta re-review 2 (fa2ff3e..47c8eb1), 2026-11-09: APPROVE
The medium item-link and low outcome-text findings are fixed, and the code matches the invariant. 3 rejoined blocks were spot-checked: each is one vote split across a page. LOW (docs only): the `_item_for_vote` docstring overstates "never makes a link" for a speaker's mention before a "this ordinance" motion. Reword it.
