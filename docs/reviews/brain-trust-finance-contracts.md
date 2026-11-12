# Brain Trust: finance-contracts spec (2026-11-08)

Three members, independent, sonnet/medium, on `docs/specs/finance-contracts.md` at c31ca7a: devil's advocate, resident's seat, public-finance data expert. No member said Go as written, so no pre-mortem round was needed.

## Top findings
- **Devil's advocate (70%, judgment):** the real neutrality risk is selection and omission. Only 32 of 91 solicitations have bid tabs; which vendors appear with names and amounts depends on scan quality and on which department attached a tab, and readers will see a pattern. Steelmanned alternative: documents-first, with extracted amounts only from the 32 text bid tabs, no OCR amounts until a spike measures accuracy. Also: "reconcile to the cent" can collapse budgets into link-only; slice too big; no usefulness test.
- **Resident's seat (85%):** "contracts page" reads as "all county contracts" and "amount paid". Needs a fixed coverage sentence, "Bids and awards" naming, "bid total as printed", a neutral glossary (bid tab, RFP, fund, actual/amended/budget), plain wording for Not confirmed*, search across vendor/title/department.
- **Public-finance expert (80%, sample p.33):** unlike numbers side by side (actual vs amended vs adopted shown as a "years" series); subtotals double-counted; inter-fund transfers and "available funds" counted as revenue; bid total is not contract value; award stages (intent, letter, commission approval) are different events; archive covers sealed solicitations only, so per-vendor sums mislead; capital fund lines are yearly appropriations, not project cost; whole dollars, not cents.

The devil's advocate has the stronger argument on scope: OCR amounts in slice 1 add the most wrong-number risk for the least coverage.

## Decisions this changed
| Finding | Decision changed | Scope | Owner |
|---|---|---|---|
| OCR amounts risk wrong figures about named companies | Yes: slice 1a shows amounts only from text bid tabs; scanned award letters are linked, no value read; OCR spike later | Cuts | product-manager |
| Slice too big | Yes: split into 1a (bids and awards) and 1b (budget books, capital fund) with separate done-tests | Cuts | product-manager |
| Coverage gaps read as a pattern | Yes: fixed coverage sentence on every page; coverage-parity report by department and year (mirrors G4) | Adds (small) | product-manager, qa-engineer |
| "Contract amount" is wrong | Yes: page "Bids and awards"; column "Bid total as printed"; stage label and date per document; awardee only with its source named | Neutral | ux-designer |
| Per-vendor sums mislead | Yes: no sums across solicitations; no county-wide revenue or spending total | Cuts | product-manager |
| Actual/amended/adopted shown as a series | Yes: columns carry the book's header plus its kind; no trend lines; "three years" wording dropped | Neutral | ux-designer |
| Subtotals, transfers, fund balance | Yes: lines = detail rows; each printed subtotal checked against its rows; transfers and available-funds rows tagged by section | Neutral | software-architect |
| Reconcile to the cent | Yes: "to the printed dollar"; a total that does not reconcile is shown "as printed, does not add up" with its lines, not hidden | Neutral | software-architect |
| Restated actuals across books | Yes: store book edition per line; differing figures shown both, never overwritten | Neutral | software-architect |
| Jargon | Yes: fixed neutral glossary, exempt from the banned-words lint | Adds (small) | ux-designer |
| Vendor correction path and G1 disclosure on each page | Partly: both recorded as public-launch gates; preview unchanged | None now | manager |
| Usefulness test | Yes: Brian finds three named contracts by vendor (batched with his next check) | None | manager |
| Capital fund lines are not project cost | Yes: fixed note on the capital page | Neutral | ux-designer |
