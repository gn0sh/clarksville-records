# City committees: spot check of confirmed motions (2026-11-16)

Purpose: decide whether `config/localities/clarksville-tn/committees.yml` `hold_motions` may be lifted (milestone C2).
Rule set by the manager: lift only if a 10-motion spot check is 10/10 **and** every confirmed motion that carries names
has those names printed in its minutes.

Record checked: `data/localities/clarksville-tn/committees/committees.json` built by `python -m collector committees build`
after the reader commits on branch `r2-committees` (146 meetings, 73 minutes read, 315 motions, 160 read as confirmed).
Source: the city's CivicClerk minutes PDFs (fetched 2026-11-16, 10 s per request), read with `pdftotext -layout`.

## 1. Spot check: 10 confirmed motions against their PDF pages

Sample: one confirmed motion from each of 10 meetings chosen at random (seed 20261116) among the meetings with a
confirmed motion. For each: the PDF page the record cites was extracted and read by eye for the mover, seconder,
outcome, any printed names on the vote, and the motion's words.

| # | Motion id | Page | Record (mover / seconder / outcome) | On the PDF page | Result |
|---|---|---|---|---|---|
| 1 | 2019-04-04-finance-motion-3 | 2 | Councilman Burkhart / Councillady Streetman / Voice vote (not recorded by name): passed; nay as printed: Councilman Henley | "A voice vote was taken; Councilman Henley voted "nay." The motion passed." | match |
| 2 | 2021-02-23-finance-motion-4 | 3 | Councilperson Streetman / Councilperson Knight / Recorded vote: passed; AYE Holleman, Knight, Redd, Reynolds, Streetman | "The following vote was recorded: AYE: Holleman, Knight, Redd, Reynolds, Streetman The motion to postpone unanimously passed." | match |
| 3 | 2021-03-23-finance-motion-6 | 4 | Councilperson Redd / Councilperson Holleman / Recorded vote: passed; same AYE list | as recorded, "...unanimously passed." | match |
| 4 | 2021-12-28-finance-motion-1 | 1 | Councilperson Zacharias / Councilperson Holleman / Voice vote (not recorded by name): passed | "A voice vote was taken; the motion passed without objection." (the minutes print "adopt the December 28 minutes"; kept as printed) | match |
| 5 | 2022-02-22-finance-motion-1 | 1 | Councilperson Holleman / Councilperson Redd / Voice vote (not recorded by name): passed | as recorded | match |
| 6 | 2022-07-26-finance-motion-3 | 3 | Councilperson Holleman / Councilperson Smith / Voice vote (not recorded by name): passed | "...the motion passed without objection" (no period in the PDF) | match |
| 7 | 2024-10-28-finance-motion-7 | 3 | Councilperson McLaughlin / Councilperson Lovato / Voice vote (not recorded by name): passed | "...RESOLUTION 22-2024- 25. Councilperson Lovato seconded the motion. A voice vote was taken and the motion was approved." | match |
| 8 | 2025-03-24-finance-motion-3 | 2 | Councilman McLaughlin / Councilman Zacharias / Voice vote (not recorded by name): passed | as recorded | match |
| 9 | 2025-06-23-finance-motion-9 | 4 | Councilman Zacharias / Councilman Lovato / Voice vote (not recorded by name): passed | as recorded; the item heading's party name is masked in the record | match |
| 10 | 2026-04-27-finance-motion-1 | 1 | Councilman Zacharias / Councilman Shakeenab / Voice vote (not recorded by name): passed | as recorded | match |

Result: **10/10**. The item shown with a motion is the item or section heading as printed; where a lettered item is
not printed under a section the section heading is shown (e.g. #6 "FINANCE COMMITTEE ACTION"), which is less specific
but not wrong.

## 2. Every confirmed motion: names printed, page right

A script (not committed; reproducible from the record and the store) checked all 160 confirmed motions:

- every name the record would show (mover, seconder, each printed nay, each printed aye: 441 names) appears verbatim
  on the cited PDF page or the next one: **441/441**;
- "<mover> made a motion <first words>" is on the cited page for 156/160; the other 4 are explained: one has a
  private claimant's name masked in the record (2019-04-04 #1), three are reference numbers broken over a line in the
  PDF ("05-2024- 25") that the reader joins;
- for all 315 motions (confirmed or held), the mover's "made a motion" is on the cited page: **315/315**. This check
  found a real miss first (two motions cited the page before, when a heading at the foot of a page ran into the
  mover's words); fixed in the reader with a fixture before this result.

## 3. What a confirmed motion shows on the site (with the hold off)

Item and motion words as printed; "Moved by <as printed>, seconded by <as printed>"; outcome "Voice vote (not recorded by name): passed" or
"Recorded vote: passed" in fixed words, or the minutes' own sentence for any other form (e.g. "The motion was approved
unanimously."); a printed dissent ("voted nay") as printed. A voice vote never shows names voting aye, even where the
2022 minutes print an AYE list after "A voice vote was taken:" (kept in the record as `ayes_printed`, not shown). The
meeting's attendance, as printed, sits above its motions. 155 motions stay "Not confirmed" with their reasons
(name or title typos in the minutes, discussion printed between a motion and its vote, blank PRESENT lists, 7 Audit
minutes that are scans and are not read).

## 4. Decision

Both conditions are met, so `hold_motions` is set to `false` in its own commit on `r2-committees` (with this file as
its evidence). The manager can drop that one commit to keep the hold. Recommend: security/code review of the lift
together with the private-name masking (`collector/committee_minutes.py` mask_private), since the masking is what
keeps claimants' names off the pages.

## Unknowns

- Pre-2019 Audit events (20) are not collected (`from_date: 2019-01-01`).
- 7 Audit minutes (2019-07-31 to 2022-07-27) are image scans: linked, not read, no OCR in this milestone.
- One settlement motion (2019-04-25) names a party as "<company>/<family name>". After the security review
  (2026-11-16, F1/F3/F5) party names learned in any minutes are masked in every motion, plurals too, so that family
  name is masked there. `private_doubt` is now fail-closed, and its motions keep no words in the record at all
  (section, subject and words null, a fixed note). It covers claims, settlements, appeals, payments to someone,
  reimbursements, indemnities and "<Name>'s request" with any unknown capitalised word left. Write-off items and
  travel-waiver lists are always withheld. After the rebuild 5 motions are withheld. One of them is spot-check #8
  (2025-03-24 #3, a write-off): its words are now withheld, while its mover, seconder and outcome, checked above,
  are still shown. The spot-check result stands.
