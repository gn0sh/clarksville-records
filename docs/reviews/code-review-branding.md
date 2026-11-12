# Code review: gnoshcodes branding and trust pages (7f8ce11, c72d82e; merge a9348df)

2026-11-09, code-reviewer (sonnet/medium). Verdict: REQUEST CHANGES (1 must-fix).
- Clean: no operator mention of a person (Brian Zacharias appears only as the Ward 1 member in records data); merge kept both EXT_KINDS sets and both CSS blocks; contrast passes in light and dark (#B8401A text on light 5.23, #EF5E35 only on dark).
- must: record-line/meeting-url-unchecked (views.py ~958).
- should: transcript pages lack the Official record line (rule 6 false); record-line/no-data-ext-on-pdf check; trust/rules wording (rule 7 conflict checks have no mechanism yet); method/claim-vs-config (show_unconfirmed_values); method/duplicated-ua; corrections/log-validation-gaps; license/ofl-text-missing.
- nits: whole-build footer guard; unused contexts; RFN check on subset fonts.
Manager decisions: keep the 8 rules and the 2-business-day correction promise (CEO-approved plan, Nov 9); reword rule 7 as a pre-agreement commitment since no payers exist.

## Delta re-review of 46655f1: APPROVE WITH NITS
All must/should items closed; OFL text matches canonical 1.1. Nits: alerts per-ward sentence came from a separate ask (fine); rule 6 now says "Every record page" (manager fix).
