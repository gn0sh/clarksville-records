# Brain Trust: where Daylight's daily data lives (Nov 18 2026). Chair report
Panel held 2026-11-18 on `docs/architecture/v1-fail-2026-11-18.md` (branch `claude/v1-fail-plan`). The chair report
comes first, then each member's independent first-round report, verbatim. Follow-up: ADR 0011, `docs/tasks/data-off-main.md`.

Proposal (architect, docs/architecture/v1-fail-2026-11-18.md on claude/v1-fail-plan): option E. Data on a forward-only records-data branch; main at 2 required approvals with team merges by admin bypass; CODEOWNERS removed; R2 off for good.
Panel: Skeptic (devil's advocate, opus), Opponent/Actions attacker (opus), Operator (opus), Budget Hawk, User seat, Strategist (sonnet). Votes: Rethink 1 (Skeptic), Fix First 5. No Go.

## Verified during the review
- Both deploy environments (github-pages, morning-note) allow branch `main` only (custom policy, not "protected branches"). Pages build_type = workflow. Read on Brian's PC, Nov 18 11:30 AM CT. This closes the Opponent's top concern (a gh-pages deploy) for today. morning-note has NO required reviewer; the Operator assumed one.
- Rule suites: the pull_request rule read "pass" for #48, #49 and #52 (manager check), so the code-owner rule never bound.

## Agreement
1. Run the U3 positive control first: 2-approval rule, then a team merge whose rule suite reads `bypass`. Do it before any rework, on a throwaway public repo or as one scripted toggle away from 09:07. (All 6.)
2. R2 on in the interim. Done: Brian typed "R2 on", 11:22 AM CT.
3. "2 approvals can't be reached" holds only while there are exactly two writers. With R2 on, an outsider or app PR can reach 2 (gn0sh + bot). R2 off becomes load-bearing under E. (Opponent, Skeptic, Budget Hawk, User.)
4. Bad data on the live site (M-2) is the real harm, and E doesn't reduce it.

## Disagreement
- Do E at all? Skeptic, Budget Hawk and Strategist say no for now: keep B and move the note's key out of this repo (Budget Hawk: separate sender repo) or defer the note. Opponent and Operator say do E with fixes.
- The Opponent's rebuttal is the stronger argument: T7 doesn't need an admin, only a branch push carrying an `on: push` workflow, which a prompt-injected agent could make. Under B a bot-merged rewrite of daily-update.yml then runs on main with both environments. The sender split moves the key but leaves the site deployable by that path. Stronger side: E with fixes (medium confidence).

## Top 3 changes (to the architect, ADR 0011)
1. Curated inputs (names.yml, procedural-titles.yml, wards.json, corrections-log.json if hand-edited) move to config/ on main as reviewed code. records-data = collector output only; the gate allowlists D's tree and refuses tracked data/ on main. (Operator.)
2. Provenance on records-data: the push job attests the data tree (artifact attestations, free on public repos), and the gate refuses an unattested D. Drop the data_sha input; rollback = a revert commit on records-data plus collect=false. Add a content tripwire: any change to an already-published vote, roll call or outcome opens an issue and holds the deploy. (Opponent, Skeptic, Operator.)
3. U3 first, scripted and reversible, before building. The cutover is one scripted session in the Operator's order. protect-main treats R2 on as NOT OK after cutover.

## Steelmanned alternative
B + sender repo (Budget Hawk): about 1 day to a live note, versus 3-4. It loses because the site itself stays bot-deployable via T7, and the email links to the site. It's the fallback if U3 fails.

## Call: Fix First. Proceed with E plus changes 1-3, gated on U3.
Question before building: does U3 pass (the team's merge-reviewed works as a bypass under 2 required approvals)?

## Decisions this changed
| Finding | Changed | Scope | Owner |
|---|---|---|---|
| U3 unproven, load-bearing | yes: U3 first | adds probe | devops |
| Curated inputs in data/ | yes: move to config/ | adds | backend |
| records-data has no provenance | yes: attestations + tripwire | adds | backend + security |
| data_sha rollback input | yes: dropped | cuts | architect |
| R2 interim | yes: on (Brian) | none | manager |
| gh-pages env exposure | no: verified main-only | none | - |
| 2-approval fragility | yes: protect-main checks collaborator count | adds | devops |
| Sender-repo split | no: kept as fallback | none | architect |

---

# Skeptic, assigned devil's advocate (opus high): Rethink, medium
Most serious problem: E protects the minor asset (the morning-note key) and leaves the major one, bad data on the live site, open or slightly wider. Any write-token workflow can push straight to records-data with no PR record and no server-side file-list check (today's J2 L-C has one), and I-data checks shape, not content. New hole: the rollback `data_sha` input lets a dispatched run, even one started by GITHUB_TOKEN, deploy any commit's tree unless the sha must lie on records-data's first-parent line.
Other issues: a third unverified GitHub behaviour (U3); if every merge is a bypass, the bypass log stops flagging anything; 2 approvals is fragile. Permanent complexity cost across thread recycles. Not proportionate: B (R2 on) already covers data, and the note is locked separately.
Insist (if E goes ahead): U3 on a throwaway repo first; the gate pins D and refuses data_sha off the first-parent line; a content tripwire, so any change to an already-published roll call, vote or outcome opens an issue before deploy.
Pick: C on top of B. R2 on, note locked until the launch decision, and the 2-3 days spent on the content tripwire. Check whether the key needs to live in GitHub at all (for example, Buttondown RSS-to-email; plan tier unknown, paid = hard stop).

---

# Opponent / Actions attacker (opus high): Fix First
Most serious problem: the deploy environments' branch lists are now the whole boundary, and nobody has verified them. Any write-token workflow can merge a workflow into a non-main branch and dispatch it. If github-pages still allows gh-pages (unverified; T4.10.5 open), you could deploy any site today, under every option. "Protected branches only" might make records-data eligible.
Other issues: R2 off is load-bearing (with R2 on, outsider/app PRs can reach 2 approvals: gn0sh + bot). "A person" = anything holding gn0sh's token; prompt injection steering an agent is the realistic route, so refuse a bypass merge of a PR authored by a non-collaborator. data_sha must be an ancestor of records-data, with I-data run on it. M-2 open. T5 (PDF parser exploit in the update job, cache poisoning) rated too low.
Insist: both environments set to Selected branches = main only, gh-pages removed; Brian pastes the deployment-branch-policies; the V1'' probe checks a dispatched scratch-branch workflow is refused the environment.
Against B: T7 needs only a branch push by any agent (an on: push workflow merges a rewrite of daily-update.yml).
Pick: the proposal plus artifact attestations on the data/ tree, checked by the gate (free for public repos), ~half a day.

---

# Operator (opus high): Fix First, medium-high
Most serious problem: code and data stop being one atomic, reviewed change. data/ holds hand-curated inputs (names.yml roster, read by collector/names.py:29; procedural-titles.yml read by collector/facts.py:23; wards.json; probably corrections-log.json), and big code PRs ship data with them (#33, #25). On records-data, with no PR rule, they'd be pushed unreviewed, could fall out of step with the code (pytest -x at workflow:426 fails, or old roster + new parser), and rollback needs coordinated reverts on two branches.
Cutover traps: the gate refuses when HEAD:data is not a tree (line 122); the seed races the 09:07 run; a stale branch carrying data/ merges back; the caches sit under data/ (order inside J1 matters).
data_sha: drop it; rollback = a person pushes a revert to records-data, then runs collect=false. The U3 probe toggles the live ruleset twice; run it as one script, or make the cutover merge the positive control.
Insist: move the curated inputs to config/ on main (reviewed code); records-data = collector output only, with the gate allowlisting D's tree and refusing tracked data/ on S; migrations ship as code.
Cutover order: disable the workflow; merge the cutover PR (U3 control); seed; create R-D, apply R1'', R2 off; re-enable; collect=false then collect=true.
Alt: B now, and permanently if U3 fails.

---

# Budget Hawk (sonnet): Fix First leaning Rethink, ~65%
Most serious problem: 2-3 days and a data-model change (~20 consumers) only to keep GITHUB_TOKEN away from environment morning-note / BUTTONDOWN_API_KEY.
Cheaper design: move the secret out of this repo. A tiny separate public sender repo holds the Buttondown key and a schedule, fetches the public build/site/morning/<D>.json from Pages, validates it strictly, and sends only site links. Data PRs stay as before (R2 on, approvals 0). About half a day; repo creation is a one-click ask. Residual: a poisoned morning JSON, so validate hard.
Other issues: 2 approvals is fragile (exactly two writers); V1'' must run on a throwaway repo; records-data is writable by any write-token workflow.
Insist: run the U3 positive control (~20 min) before any rework.
Pick: C as the sender-repo split. Time to note live: ~1 day vs 3-4.

---

# User seat (sonnet): Fix First ~65%
Most serious problem: Brian's daily cost is hidden. Every non-data merge rides on his admin bypass (U3 unproven), and readers sit on stale data while R2 is off for a T7 risk that needs an admin writer.
Other issues: a fast-forward push fails on concurrent pushes, and deploy depends on push, with no recovery owner. Required approvals of 2 is fragile (it relies on exactly two writers), and records-data is checked at gate time, not push time (M-2). The cutover is hard to reverse and breaks local runs until fetch-data ships.
Insist: R2 on now; run the U3 positive control first, on a docs PR; run the V1'' probe on a throwaway repo, not live main; gate the rework on U3.
Pick: A-lite (R2 on, U3 first, then records-data + 2-approval rule if U3 passes).

---

# Strategist (sonnet): Fix First, medium-high
Most serious problem: it swaps one untested GitHub assumption for another. U3 (2 approvals is unmeetable, so every merge is a bypass) is load-bearing and untested; a capability flag isn't a rule-suite result. "A person's bypass" is really an agent with Brian's token, the same trust boundary as today. Brian as sole admin = main frozen if he's unreachable.
Other issues: opportunity cost (R2 on now, unconditionally). Template lock-in: the two-branch setup must be a scripted, tested protect-main per city. Two-commit pinning gap; bad data is the realistic harm.
Insist: U3 positive control + V1'' dry run on a throwaway public repo before any rework (~1 hour); R2 on in the interim.
Pick: B now (R2 on, note locked), then the records-data split after the throwaway probe passes; defer the note until the split is live. Flips to the full proposal now if Brian wants the note before launch.
