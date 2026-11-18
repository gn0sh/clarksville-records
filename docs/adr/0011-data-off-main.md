# ADR 0011: Collector data moves off `main`; no workflow can merge into `main`

Status: proposed (software-architect, 2026-11-18), **gated on U3** (`docs/ops/u3-positive-control.md`). Supersedes
ADR 0010 decisions 1 (CODEOWNERS), 2 (ruleset R1') and 5 (the V1' probe). ADR 0010 decisions 3 (R2 on, now
interim), 4 (canary removal, done by #52) and 6 (the gate stands) remain. Analysis, invariant and every consumer:
`docs/architecture/v1-fail-2026-11-18.md`. Panel: `docs/reviews/brain-trust-data-off-main.md` (Fix First, 5-1).
Tasks: `docs/tasks/data-off-main.md`. Amended 2026-11-18 for the PR #54 security review
(`docs/reviews/pr54-security-review.md`, findings 1-8 and settings drift). Amended 2026-11-18 (decision 2a) for the
person-run writers B1 found (`docs/architecture/data-inventory.md`).

## Context
The V1' probe (run 44354265953) FAILED. `GITHUB_TOKEN` squash-merged #49, which adds a workflow file, under
`require_code_owner_review: true` with 0 required approvals. Rule suites show the `pull_request` rule read `pass`,
not `bypass`, for #48, #49 and #52, so the code-owner requirement never applied. This is the second failed fix in
the `main-protect` family. With data on `main` and merged by a bot, I-main needs a path-aware merge rule that this
repository (public, user-owned, GitHub Free) doesn't offer: a branch ruleset's PR rule has no path condition, and
push rules are for private Team or internal Enterprise repositories. Verified on Brian's PC (2026-11-18): both
environments allow `main` only (custom policy), Pages build_type is workflow, and `morning-note` has no required
reviewer.

## Decision
1. **Collector output lives on branch `records-data`** (tree = `data/` only). Ruleset R-D: `deletion` and
   `non_fast_forward`, no bypass, no PR rule. The push job fast-forwards it with `GITHUB_TOKEN`. `main` tracks no
   `data/` (gitignored). The gate refuses a tracked `data/` on `S`.
2. **Curated inputs are code** (Brain Trust change 1). `data/names.yml`, `data/procedural-titles.yml` and
   `data/corrections-log.json` move to `config/`, reviewed like any code. `data/` keeps only what the collector
   writes. `SHAPE''` narrows to `*.json` and `changes.jsonl`, and the gate refuses the curated names in `D`. An
   inventory task confirms each remaining file's writer.
2a. **No person writes `records-data`** (invariant I-in, `docs/architecture/v1-fail-2026-11-18.md` section 2). B1
   found four person-run writers of `data/`. Under I-prov a person's new tree is refused, so each gets a reviewed
   path through `config/` on `main` instead (task B1b):
   - **Transcripts** (`collector/transcripts.py` `import` :274/:295 and `remask` :319/:322; 18 files, 2.5 MB) move
     to `config/localities/<locality>/transcripts/`. A person runs `fetch-data`, then the import on the Whisper
     output from Brian's PC (it reads the facts and event listing from the fetched `data/`), and opens a PR. The
     importer masks before it writes, so the PR carries masked text only and raw text never reaches a branch. The
     PR is the review point, including Brian's sample OK before any new batch goes live. `sitegen` and `qa` read
     transcripts only from `config/`, with no fallback to `data/`.
   - **Map manifest** (`tools/fetch_map.py` :25/:43) moves to `config/maps/manifest.json`. It is read at build
     time through `config/site.yml` `fetch_manifests` (:17), so that entry changes too.
   - **Kept city books** (`daily-update.yml` ~:581, `collector/fin_books.py` `worse_than_committed`): "a person
     runs `fin-books build` and commits" ends. A person reproduces the reading locally (`fetch-data`, `fin-books
     fetch`, `fin-books build`; `data/` is gitignored, so nothing is committed from it), then either fixes the
     reader by PR or lists the reviewed reading in the new `config/fin-books-accepted.yml` (`locality`, `book_id`,
     the new file's full `source_sha256`, `listed_on`, `reason`). The next daily run rebuilds. An entry lets the
     build replace that book only while the stored book's sha256 differs from the listed one, so it is spent once
     the new reading is on `records-data`.
   - **`tools/scrub_rpc_phones.py`**: its rewrite mode is removed (`collector rpc build` already strips phones, so
     the daily rebuild writes the same). `--check` stays, read-only, and the cutover runs it on the seed.
   `CURATED_NAMES` gains `fin-books-accepted.yml`, and `collector/data_shape.py` also refuses any path under
   `data/maps/` or a `transcripts/` folder in `D`. The seed leaves them out. Readers that list `data/` through
   git (`qa/pii_scan.py` `tracked_files`, `tests/test_committees_daily.py:26`) read the fetched tree instead and
   fail on an empty one.
3. **Provenance** (change 2). After pushing, the push job attests the new tree listing (`git ls-tree -r -z D -- data`
   as a file) with `actions/attest-build-provenance`. The gate reads the `records-data` head once (`D`) and accepts
   it only if that listing verifies, or `D` is the seed (below). Verify:
   `gh attestation verify <listing> --repo gn0sh/clarksville-records --cert-identity
   https://github.com/gn0sh/clarksville-records/.github/workflows/daily-update.yml@refs/heads/main --source-ref
   refs/heads/main --predicate-type https://slsa.dev/provenance/v1 --deny-self-hosted-runners`.
   **Signer scope (finding 3):** the certificate names the workflow file and ref, not the job, and the `deploy` job
   already holds `id-token: write` for `deploy-pages` (`daily-update.yml:990`). So the property is: only J2 holds
   `attestations: write`, so only J2 can store an attestation the gate will find, and only on `main`'s
   `daily-update.yml` at `refs/heads/main`. The predicate type pins it to the provenance J2 writes.
   **Seed scope (finding 7):** `RECORDS_DATA_SEED_DIGEST`, pinned by the cutover PR, is accepted only while `D` is
   the seed commit itself (the root of `records-data`, no parents). R-D refuses non-fast-forwards, so once a run has
   moved the branch, a tree equal to the seed is checked like any other. The seed itself is never attested, so a
   rollback to the seed tree after the first run fails closed (accepted). **No `data_sha` input.** Rollback: a
   person restores an earlier attested tree whole on `records-data`, then runs `collect=false`.
4. **Content tripwire** (change 2). J1 compares the votes, roll calls and outcomes in the `D` recorded in the live
   site's `build-info.json` with what this run will deploy. Any change or removal not listed in the reviewed
   `config/published-fact-changes.yml` opens one fixed-title issue and holds the deploy (`held=yes`). The data push
   still happens. `allow_shrink` never bypasses it (finding 7): only the reviewed list does. This extends ADR 0006's guards, which see only one run's collection.
5. **Ruleset R1'' on `main`:** `required_approving_review_count: 2`, `dismiss_stale_reviews_on_push: true`,
   `require_last_push_approval: true`, `require_code_owner_review: false`, squash only, bypass Repository admin role
   in `pull_request` mode. `.github/CODEOWNERS` is deleted. Every merge into `main` is a person's bypass merge via
   `merge-reviewed`, which refuses PRs not authored by gn0sh or with a head in another repository.
6. **R2 off from the cutover on, and load-bearing.** R1'' is unreachable for a bot only while there are exactly
   two writers (gn0sh and github-actions[bot]) and R2 is off. `protect-main` writes R1'' and R-D, turns R2 off, and
   reports NOT OK if R2 is on, or if anything besides gn0sh can write: a collaborator with write or more, an
   installed App with contents write, or a deploy key with write (finding 1). Both environments' `main` policy must
   be of type `branch`, and tag ruleset R-T blocks creating a tag named `main` (finding 2).
   **Settings drift (the review's most serious item):** this rests on settings no daily run can read, and the team
   proxy refuses the `actions/permissions`, `collaborators` and `environments` reads. So `protect-main` reports
   NOT OK on any refused or failed read, never OK by default. It runs from Brian's PC after any settings change and
   before `MAIN_PR_BASELINE` is set. `MORNING_NOTE_SEND` is unset before R2 goes back on or any ruleset changes.
7. **Order** (change 3). U3 runs first, as a scripted live toggle, before any rework. If it fails, this ADR is
   rejected and the fallback below applies. The cutover is one scripted session in the Operator's order (task list
   D3), with `protect-main` (R1'', R-D, R-T, R2 off) before the cutover merge (finding 5). After it, the V1'' probe (architecture note section 4) must pass before `MAIN_PR_BASELINE` or
   `MORNING_NOTE_SEND` is set.

## Alternatives considered
- **Required approvals 1-2 with data still on `main`:** the bot's data PR can't approve itself. A second identity
  is a new credential (hard stop 5). Rejected.
- **Push rule restricting paths outside `data/`:** the ideal fix, but not available for a public Free repository
  (GitHub changelog 2024-09-10). Rejected for now. Revisit if GitHub extends it.
- **B (status quo, R2 on, approvals 0, gate only) plus a separate sender repository holding the note's key**
  (Budget Hawk, Skeptic, Strategist): about 1 day versus 3-4. It loses because T7 needs only a branch push carrying
  an `on: push` workflow, which a prompt-injected agent could make. A bot-merged rewrite of `daily-update.yml` then
  runs on `main` with both environments, so the site stays deployable by that path (Opponent; medium confidence).
  **This is the fallback if U3 fails.**
- **Don't build; defer the note** (Skeptic): the site keeps T7 open, as above.
- **Person-run writers (decision 2a):** (i) a dispatched "import" job that attests a person's input: the input
  must be reviewed in the repository anyway, so it is `config/` with extra steps, and it puts `attestations: write`
  on a second job. (ii) Keep transcripts in `data/` and let J2 carry them forward: no path to add, remask or remove
  one. (iii) Commit the raw Whisper output and import it in the daily run: raw text holds unmasked addresses and
  must never reach a public branch (`docs/status.md` 2026-11-12). (iv) City books "fix the reader by PR" only: a
  replaced source file is a keep reason on its own, so a correct new reading would have no way in. (v) Drop the
  keep guard: reopens city-books/daily-overwrite-unguarded. All rejected.
- **Throwaway repository for U3:** needs Brian to create a repository and grant the team access to it, and it
  tests a different ruleset and token. Rejected in favour of the scripted live toggle.

## Consequences
- I-main becomes simpler (no data exception). I-run gains `D`, read once by the gate and attested.
- New residuals: (a) attested but wrong new facts from `main`'s own pipeline (a hostile PDF, T5) when they don't
  touch published facts. (b) Every merge is a bypass, so the bypass log stops being a signal; the gate's
  person-merge check and the rule-suite read in `merge-reviewed` replace it. (c) Brian is the sole admin, so `main`
  freezes if the team's bypass stops working. (d) Replay (finding 7): a write-token workflow on any branch can
  push an earlier attested tree to `records-data`. The gate accepts it, because a person's rollback needs exactly
  that. I-pub holds the deploy if it drops or changes a published fact; an old tree that differs only in facts not
  yet live deploys. Accepted: the data is still `main`'s own pipeline output. (e) Settings drift: R1'' holds only
  while the settings in decision 6 hold, and only a run of `protect-main` from Brian's PC can see them all.
- The push job gains `id-token: write` and `attestations: write`, and loses `pull-requests: write`. It is the only
  job with `attestations: write`; `deploy` keeps its own `id-token: write`. The gate gains `attestations: read`.
- **U3-0 = no** (finding 8): the team's cloud session got a proxy 403 on the no-op ruleset PUT at 17:37 UTC
  2026-11-18 (read-back unchanged). So every ruleset, R2, environment and R-D write is Brian's, run from his PC:
  U3, the cutover's settings steps and any rollback. Those writes are blocked today by the session proxy's
  policy, not by the token's permissions; if that changes, the team-token anchor returns. Re-check U3-0 whenever
  the proxy allowlist changes.
- Decision 2a: transcripts and the map manifest stay in `main`'s tree and grow it (about 140 KB per meeting, so
  about 9 MB for the 65-meeting backlog; judgment, acceptable). They were already in `main`'s history, so nothing
  new is published. A transcript PR is too long to read line by line: review checks the import log (counts,
  matches, skips), provenance and the masking tests, not every line (judgment). A meeting that leaves the facts
  makes a committed transcript stale and fails the build until a removal PR, as today, because the daily run has
  never imported transcripts.
- Local runs and preflight need `scripts/fetch-data`. The multi-city template inherits the two-branch setup through
  `protect-main`.
- Cost: about 3-4 engineer days plus security review. Brian: one U3 session, then one cutover session.
- Reversal: `scripts/cutover-data-off-main --rollback` refuses while `MORNING_NOTE_SEND` or `MAIN_PR_BASELINE` is
  set (finding 4: R2 on reopens the bot path), then re-applies R1' json, restores `data/` on `main` by a
  reviewed PR from `records-data`'s head (the moved transcripts and map manifest stay in `config/`, with readers
  as the cutover PR left them), and turns R2 on. The `records-data` branch is kept.
