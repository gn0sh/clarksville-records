# Tasks: privacy invariant (problem family `privacy/transcript-private-addresses`, 2nd hit)

Invariant, consumers and controls: `docs/architecture/city-council.md`, section "Private details in transcript text".
Findings: security delta review of 72b7e35 (N1-N4). Branch: `claude/project-thread-8xjro9-privacy`. PR #1 to `main`
is squash-merged (manager decision, option (b)).

Rules for every task here:
- Never type a real resident's name, address, house number or phone number into any file, commit message, PR body
  or handoff. Use synthetic values: invented names (e.g. "Pat Example"), placeholder streets (e.g. "Example Street",
  "Sample Court", "Fixture Lane"), phone numbers in the fictional 931-555-0100..0199 range.
- Refer to existing real text by `path:line` only.
- Tests run in session (`python -m pytest -q`); paste the output in the PR. No Actions minutes until Dec 1.
- Owner of T1-T8: `backend-engineer` (opus/high: data integrity). T9: `devops-engineer`. T10: manager.

## Files in the tree that quote real resident details today (HEAD 72b7e35)

Found by searching tracked files for the real strings in the review's findings; listed by line only.
- `sitegen/privacy.py`: 10, 11, 12, 13, 18, 132 (module and `mask_segments` docstrings)
- `tests/test_transcript_privacy.py`: 28-44, 76, 97, 98, 104-106, 135, 156, 178, 179, 181
- `collector/tests/test_rpc.py`: 396-399, 413, 417, 428, 433
- `collector/rpc_agenda.py`: 107, 108 (comment above `PHONE`)
- `data/localities/clarksville-tn/transcripts/*.json`: 7 of 17 transcript files (raw text; T4)
- `data/localities/cmc-rpc/rpc.json`: 1151, 8249 (`agent` names), 16213, 16707, 28771, 29811, 29820 (`location`).
  These are case fields (agent name, subject property) that the architecture's scope note keeps as shown public case
  data; no phone. No change, but T8 confirms the 16213/16707 locations are subject properties, not an
  applicant's contact address.
- Not in the tree but public: branch `gh-pages` (43b1a9c) has unmasked transcript text in 9 `city/transcripts/*.html`
  pages and `static/search-index.js`, and the RPC phone in `data/rpc/cases.csv`, `data/rpc/facts.json`,
  `rpc/meetings/2024.html`, `static/search-index.js` (T9).
- Clean: `docs/**` (including `docs/reviews/`, `docs/status.md`), `qa/site_checks.py`, `site/fixtures/`.
- Outside the repo, before commit: the delta review report quotes a bare house number from a 2026-05-07 transcript
  line under N4; redact it before it is committed to `docs/reviews/` (T10).

## Tasks (in order; T1-T3 can run in parallel, T4 needs T1, T5-T7 need T4)

**T1. Move the masker and make it ReDoS-safe (N3, `privacy/mask-regex-redos`).**
Move `sitegen/privacy.py` to `collector/privacy.py` (sitegen already imports collector; the collector must not import
sitegen) and update `sitegen/transcripts.py`. Make the number-word token an atomic group (`(?>...)`, Python 3.11+,
the repo's floor) at `_NUM_WORD` / `_NUM_SEQ` (old lines 67, 71-72), so a run of spelled-out numbers with no street
cannot backtrack exponentially.
Done: (a) a timed test feeds `'twenty-two and ' * 60` (and the same with no suffix after it, and a 60-word spelled
digit run) to `privacy.spans` and to `site_checks.private_details` and asserts each finishes under 0.5 s;
(b) the masker finds exactly the same spans as before on every committed transcript (compare counts before and after
in the session; the review measured 129, record the number only); (c) all existing tests pass.

**T2. Synthetic examples in the masker and its tests (N1).**
Replace every real example in `collector/privacy.py` docstrings (old `sitegen/privacy.py:10-19,132`) and in
`tests/test_transcript_privacy.py` (lines listed above) with synthetic lines that exercise the same rule: digits and
spelled-out house numbers, Whisper splits, "five or five"-style "or" for "oh", two house numbers joined by "and",
initials in a street name, ordinal street names, cued house numbers with no suffix, an address split over two lines,
each phone form. Keep every false-positive case. Rewrite the `:178` site-check test and `ADDRESS_LINES` on synthetic
lines only. Replace the `found >= 77` assertion (it counts real committed lines) with the at-rest test of T5.
Done: no line in the file holds text from a real transcript; same number of masking and non-masking cases or more;
tests pass.

**T3. Synthetic RPC phone fixtures (N2, `privacy/rpc-applicant-phone`).**
In `collector/tests/test_rpc.py` (396-399, 413, 417, 428, 433), any fixture it reads, and the `PHONE` comment in
`collector/rpc_agenda.py:107-108`, use 931-555-0100 (and 555-0100 for the 3-4 form) and a placeholder street.
Add a test that every string in the committed `data/localities/cmc-rpc/rpc.json` has no match for `rpc_agenda.PHONE`
(a regex check, no stored number). Done: tests pass; the real number appears in no tracked file (check with T6).

**T4. Mask at import and re-mask the committed JSON (decision (b), new commit, no history rewrite).**
In `collector/transcripts.py import_dir`, run `privacy.mask_segments` on `rec["segments"]` before `render`; refuse to
write (skip with a reason) a file whose segments still match after masking. Add `python -m collector.transcripts remask`
that rewrites every committed transcript JSON through the masker with no raw input (for this commit and for future
rule changes, e.g. N4). Run it and commit the masked JSON in its own commit.
Done: tests for import-masks, `remask` idempotent (`mask(mask(x)) == mask(x)`, second run changes no byte), segment
times and count unchanged; the commit touches only `transcripts/*.json`; `git grep` for the mask string shows the
expected files.

**T5. Masked at rest: site load and site check (needs T4).**
`sitegen/transcripts.py load` keeps masking and raises `TranscriptLoadError` when masking changes a committed line.
`qa/site_checks.py check_private_details`: (a) data-transcript text and call-on excerpts pass the restated rule;
(b) every committed transcript segment passes it; (c) `data/` and `static/search-index.js` carry no transcript segment
text at all (needles: committed masked lines). Update its docstring and the check list comment at lines 63-66.
Done: tests on synthetic transcripts for each of (a)-(c) and for the load error; a full build passes with 0 problems.

**T6. Out-of-repo leak scan (replaces a grep guard test, which would commit the needles).**
`qa/pii_scan.py --raw <folder outside the repo> [--site <built site>]`: reads raw transcripts (and optionally raw RPC
text layers) from outside the repo, takes the spans `privacy.spans` would mask, keeps them in memory only, scans every
`git ls-files` file (and the built site) for them case-insensitively with whitespace normalised, and prints
`path:line` and counts only, never the matched text. Refuses a `--raw` folder inside the repo. Writes no file.
Done: unit test with a synthetic raw folder in `tmp_path` proves a planted synthetic address is reported by path:line
without its text and the output never contains it; run once on the real raw folder after T2-T5, result in the PR as
counts only (expected: 0 hits).

**T7. Docs.** Update the architecture's "Every producer and consumer" table if the code differs from the plan
(`docs/status.md` is the manager's). Done: the section matches the code.

**T8. Confirm RPC location scope.** Check the two RPC `location` lines at `rpc.json:16213,16707` against their source
agenda: subject property or applicant contact address? Report the answer by line, no text. Done: one line in the PR.

**T9. Replace the public preview (`devops-engineer`, after T1-T6 merge).** Rebuild and redeploy the preview to
`gh-pages` from the masked build, then run T6 with `--site` on it. A normal new commit only: no force-push or branch
deletion (hard stop). The preview is not production; if its deploy job is locked, unlocking it is a hard stop for the manager to ask.
Done: T6 reports 0 hits on the deployed tree.

**T10. Manager.** Redact the review report's quoted house number before committing it; record in `docs/status.md`
the accepted residual (history of public `claude/*` branches and of `gh-pages`); squash-merge PR #1.

## Follow-up after go-live

**F1. N4 `privacy/transcript-street-only`** (`backend-engineer`): first-person "I live on/off <street>" with no house
number (about 7 lines), and a bare house number with no street after a pause. Extend the rule with synthetic tests,
then `remask` the committed JSON (T4) in a new commit and re-run T6.
