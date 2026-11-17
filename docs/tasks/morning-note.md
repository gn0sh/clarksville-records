# Tasks: Daylight M3, the morning note

Architecture: `docs/architecture/morning-note.md` (the output contract and seam there are fixed; T1-T3 build against
them in parallel). An RPC minutes motion in the note (a `vote` entry, the zoning list) follows
`docs/architecture/rpc-motion-invariant.md`: outcome/tally only when confirmed, else "Recorded in the minutes; not
confirmed"; joins the zoning list only via `case_id`, never an unconfirmed `case`. Tests run in session (`python -m pytest -q`); paste the output in the PR. No task in T1-T3 sends mail,
creates an account or stores an email. T4 (the sender, below) is built off and sends only after Brian's go-ahead.

| Task | Owner | Depends on | Parallel |
|---|---|---|---|
| T1 Digest generator | backend-engineer | none | yes |
| T2 Missing feeds | backend-engineer | none | yes (separate files from T1) |
| T3 Sign-up section, preview page, morning.js | frontend-engineer | contract only; integrates T1/T2 at the end | yes |
| T4 Sender (T4.0 to T4.10 below) | backend, devops, frontend, writer | T1-T3 merged (done) | see T4 |

## T1: digest generator (`sitegen/morning.py`, config, build hook)
- `config/site.yml` `morning_note:` block (lists with key/label, `cutoff`, `keep_days`, `zoning_prefixes`, seam keys,
  `enabled: false`); `morning.problems(cfg)` wired into `build.problems()` with the seam rules.
- `day(date, ...) -> dict` per the contract; `select(day, lists, seats)`; writes `morning/YYYY-MM-DD.json` for
  `keep_days` days and `morning/latest.json`; counts toward `MAX_FILES`.
- Window from `first_fetched_at` in the four collector manifests (architecture, window rule) in `site_timezone`; the zoning rule exactly as written (printed
  district/ward, `link_county` inheritance, `unplaced_zoning` count).
Done when tests show: a document fetched at 06:59 lands in today's note and at 07:00 in tomorrow's; a re-fetched
document does not reappear; an empty day writes `entries: []`; zoning matches by district, by ward, and never for a
case with neither; a linked county CZ item inherits its case's district; unconfirmed motions carry no outcome/tally;
every digest document resolves to a manifest row (else the build fails); BANNED scan clean; `enabled: true` without
`form_action`/`privacy_url` is refused; file count stays under the preview cap.

## T2: missing feeds (`sitegen/feeds.py`, `tests/test_alerts.py`)
- `feeds/topic-contracts.xml` from `data/finance.json` solicitations (verbatim titles, source link, stable ids).
- RPC zoning cases (prefixes from `morning_note.zoning_prefixes`) added to `topic-rezoning.xml`; existing entry ids
  byte-identical.
- `feeds/zoning-district-NN.xml` and `feeds/zoning-ward-NN.xml` on the `pages` target only; `feed_list()` exposes
  them with `kind: "zoning-seat"`, `seat`, `number` so T3 can link the right one.
- Update the feeds.py docstring and `test_one_feed_per_body_and_per_topic` (per-seat feeds now exist on pages only).
Done when tests show: valid Atom for every new feed; ids stable across two builds; old rezoning entry ids unchanged;
preview build has no per-seat feeds and stays under 500 files; pages build has 21 + 12; a per-seat feed holds only
cases whose printed district/ward equals its number.

## T3: sign-up section and preview (`alerts.html.j2` `#note`, `morning.html.j2`, `static/morning.js`)
- `#note` on alerts.html: picker with the four config lists, state line "Email starts at launch; follow by feed now"
  (config text), and per picked list the matching feed links (zoning: the per-seat feed for the stored district/ward
  on pages, else all-zoning; seats: the county/council body feed). With `enabled: false` there is no email field, no
  submit and no form `action`. No-JS: all lists and all feed links shown, except the per-seat zoning feeds, which stay
  hidden in `#note` without JS (deviation, review nit `morning-signup/no-js-feeds`: they need the stored seat, and
  each is listed in the page's "Zoning cases by district or ward" section).
- Nav "Morning note" links `alerts.html#note`; landing still fits one screen.
- `morning/index.html`: today's entries from `latest.json` data rendered server-side with `data-lists`,
  `data-seat-body`, `data-district`, `data-ward` (built on the pages target only, from the note `write()` returns;
  nothing links to it otherwise); `morning.js` filters by `#lists=` and `cr-your-seats`, mirrors `select()`.
- Enabled path rendered only in a test config: email field, `action=form_action`, CSP `form-action` gains exactly
  that origin, privacy line with `privacy_url`.
Done when tests show: no success text anywhere while disabled; no `fetch`/`XMLHttpRequest`/beacon in morning.js; JS
`select` matches Python `select` on the fixture for every list/seat combination; CSP unchanged when disabled; no
locality name in the new templates; no sideways scroll at 360 px; picker usable by keyboard with a visible legend.

## Order
T1 and T2 in parallel, then T3 integration (T3 can start on fixtures at once). Review per task; security review on
T3 (form, CSP) and on the later sender job. Going live is a separate CEO decision (provider pick, account, secret).

## T4: the sender (architecture "T4 sender"; ADR 0004)
Built off: `morning_note.sender.enabled: false`, no secret, no repository variable. No task here creates an account,
handles a real key or mails a real person; T4.0 and the switches are Brian's go-live steps. Tests use only fixture
notes and `example.org` addresses, and no test opens a connection.

| Task | Owner | Depends on | Parallel |
|---|---|---|---|
| T4.1 Plan stage (dry run) | backend-engineer | none | yes |
| T4.2 Renderer | backend-engineer | none (same worker as T4.1, or a second on `render.py` only) | yes |
| T4.3 Config block and build guards | backend-engineer | none | with T4.1 (same worker) |
| T4.4 Deliver stage against a fake provider | backend-engineer | T4.1 | after T4.1 |
| T4.5 Workflow: plan step and `note` job | devops-engineer | T4.1, T4.4; after the RPC workflow change merges (same file) | no |
| T4.6 Privacy text and seat consent (enable conditions) | frontend-engineer, technical-writer | none | yes |
| T4.7 Runbook: account setup, probe, canary, go-live, rollback | devops-engineer | T4.4 | yes |
| T4.0 Provider probe | devops-engineer with Brian's account | Brian creates the account (go-live) | blocks only `sender.mode` and going live |
| T4.8 Security review of T4 | security-engineer (fresh, opus/high) | T4.5 | before T4.5 merges |

### T4.1 Plan stage (`sender/plan.py`, `sender/__main__.py plan`, `tests/test_morning_sender_plan.py`)
`python -m sender plan --date D --site build/site --out build/morning-send` writes `<out>/<D>/plan.json` and
`edition-<key>.html|.txt` per the architecture. Uses `sitegen.morning.select` as the only filter.
Done when tests show: a quiet day and a backfill day give `send: false` and no edition; a missing note file, a wrong
schema or a note for another date exits 2; a signature with an empty selection is absent from `signatures`; two
signatures with the same entries share one edition and two with different entries do not; every signature's edition
holds exactly `select()`'s ids for it (checked over all 4,290 on the fixture); two runs give byte-identical output;
a plan over `MAX_PLAN_BYTES` exits 2 (as built: `max_editions` is the deliver stage's, over editions with a
recipient; a disabled sender's rehearsal prints the error and exits 0); the module imports nothing that can open a connection (a test greps `sender/plan.py`
and `render.py` for `urllib`, `socket`, `http`, `requests`, `subprocess`).

### T4.2 Renderer (`sender/render.py`, `tests/test_morning_sender_render.py`)
Subject and body from an edition's entries and `morning_note.sender.text`.
Done when tests show: a title holding `<script>`, `{{ x }}`, `{% y %}`, a Markdown link and a leading `---` comes out
inert; a `javascript:` or `http:` source URL gives no link; site links are `site_url` + `href`; the `BANNED` scan
passes over our own words; no locality name is hard-coded (the template locality test covers it); the body's entries
and order equal the preview page's for the same lists and seats; an unconfirmed vote shows no outcome or tally.

### T4.3 Config and guards (`config/site.yml` `morning_note.sender:`, `sitegen/morning.py problems()`)
Add the block from the architecture, all off. Set `form_fields.lists` to `metadata__lists`; change `page.about` to
"by 7:00 AM".
Done when tests show: `sender.enabled: true` is refused without `morning_note.enabled: true`, an https `api_base`, a
`mode` of `stamp` or `ids`, and a site URL; times parse as HH:MM with `send_at` before `latest_send`; unknown keys
are refused.

### T4.4 Deliver stage (`sender/deliver.py`, `sender/buttondown.py`, `tests/test_morning_sender_deliver.py`)
Standard library only (a test imports `sender.deliver` with `sitegen`, `yaml` and `jinja2` blocked). The provider is
an interface with two implementations: `buttondown.py` (the only file allowed to open a connection) and an in-memory
fake for tests. Both modes (`stamp`, `ids`) are written; `sender.mode` picks one.
Done when tests against the fake show:
- without `--live`: no provider call at all; with `--live` and `send: false`: no provider call at all;
- plan dated yesterday or tomorrow: nothing sent; now past `latest_send`: nothing sent, exit says "missed";
- **never twice**: a second run of the same plan sends nothing new; a run that died after edition 1 of 3, run again,
  sends editions 2 and 3 only; a day claimed with a different `note_sha256` sends nothing; a failed or short listing
  sends nothing and exits non-zero;
- only `type == "regular"` subscribers are recipients; with `canary_only` only the ids in `MORNING_NOTE_CANARY_IDS`
  (as built; never subscriber metadata); an edition
  with no recipient creates no email; hostile metadata (`district: "7; drop"`, `lists: ["zoning", "x"]`, a list of
  5,000 values) is ignored, not passed on;
- `stamp` writes the whole metadata object back with the other keys unchanged, and the filter value is exactly
  the stamp `"<D>.<key>.<mac>"` (as built); no code path can create an email with an empty filter while `sender.mode` is `stamp`;
- 429 with `Retry-After` is obeyed, three tries, then stop; over `max_recipients` sends nothing;
- **no personal data out**: with a fake that returns addresses, capture stdout, stderr and every raised exception
  text across success and each failure path, and assert no address, subscriber id or response body appears; the
  summary line has totals only.

As built (adapter and `--live`, 2026-11-11, `claude/hu3mew-sender-live`; tests `tests/test_morning_sender_buttondown.py`
against a fake HTTP layer, sockets refused):
- `sender/buttondown.py` is the only sender module importing a network library (a test checks every module). It uses
  `urllib.request` with an opener holding only an https handler and the unknown-scheme handler: no proxy, no redirect
  (a 3xx is an error), no error processor; TLS verified; 30 s timeout; at most 5 requests a second. Every URL, and
  every pagination `next` link, must be https on `api.buttondown.com` under `/v1/`. Ids must match `[A-Za-z0-9_-]{1,64}`
  before they go in a path. Listings are rows reduced at the boundary to `id`, `type`, `metadata` (subscribers) or
  `id`, `status`, `metadata` (emails). A listing whose rows do not add up to its first page's `count` fails. Writes
  are exactly `PATCH {"metadata"}`, `POST /emails` (known fields only), `PATCH {"status": "draft"}`,
  `POST send-draft {"subscribers"}`. Errors say method, path template and status only, never chained to urllib's.
- `python -m sender deliver --live` with `sender.enabled` false is a dry run with a fixed `::warning`, exit 0. With
  `sender.enabled` true, a missing or malformed `BUTTONDOWN_API_KEY` exits 2 with a fixed message that names the
  variable, never its value, so a forgotten secret at go-live fails the job. The key is passed to `deliver.run` as
  `stamp_secret`. The adapter is imported only on the live path (a subprocess test checks a dry run loads no
  `socket`, `ssl`, `http` or `urllib`).

- T4.8 review of a4b3571 (APPROVE; fixed before go-live, each with a test): the deliver stage rebuilds every
  edition's subject from the repository's `site_name` and `text.subject` (now read by the stdlib reader, held to
  PyYAML parity; `site_name` must stay one word or be quoted) and refuses any other (subject-unchecked); `ids` mode
  rechecks `latest_send` before each draft and each send (ids-no-recheck); `http.client.HTTPException` is wrapped
  like every other transport error (httpexception-unwrapped); a URL with a control, space, non-ASCII or backslash
  character is refused before parsing, and urllib's own `Request` must agree on scheme, host and `/v1/` path
  (parse-differential). Point 5 (the provider ignores `filters`) is the T4.0 negative probe, not code: nothing the
  API answers before the send can show who a filter reached.

Verify in T4.0 probe (built from the documented or assumed shape; every one fails closed if wrong, so a wrong guess
stops the send rather than widening it):
1. Listings are `{"results": [...], "next": <url or null>, "count": n}` and `next` is an absolute
   `https://api.buttondown.com/v1/...` URL. Another form (relative, another host) fails every run.
2. `count` equals the rows over all pages. If it counts something else, every run fails at the listing.
3. `GET /v1/subscribers` with no parameters lists every type (regular, unactivated, unsubscribed, premium, gifted,
   ...). The stray-stamp check needs all of them. If it lists only some, the adapter must ask for each type.
4. `GET /v1/emails` with no parameters lists drafts and scheduled emails, with `metadata` on each row, back far
   enough to hold today's. **Never-twice rests on this.** Also: whether a date filter can shorten the listing.
5. `GET /v1/subscribers/{id}` takes the id (not only the address) and answers 404 for no such subscriber.
6. `PATCH /v1/subscribers/{id}` with `{"metadata": {...}}`: does it replace or merge, and does the answer hold
   exactly the stored metadata, values unchanged? The adapter refuses a write whose echo differs from what it sent.
7. `POST /v1/emails` answers 200 or 201 with `id`, `status`, `metadata` and `filters` as sent, without added fields
   inside `filters`. An `ids` draft must come back with no `filters` key (or null). An empty filter object fails
   the echo check, so every `ids` run would fail closed.
8. `PATCH /v1/emails/{id}` with `{"status": "draft"}` takes a scheduled email back to a draft.
9. `POST /v1/emails/{id}/send-draft` with `{"subscribers": [...]}`: which status it answers (200, 201, 202 or 204
   accepted). Whether it is a real send is already in the T4.0 list.
10. The 429 `Retry-After` form (seconds or an HTTP date; both read; anything else waits 5 s).
11. Every JSON answer has `Content-Type: application/json`, and no page is over 16 MB.
12. Subscriber and email ids fit `[A-Za-z0-9_-]{1,64}` (UUIDs do).
13. The scoped key is printable ASCII with no space, 32 bytes or more: `stamp` mode needs at least 32 for the HMAC.
14. `X-Idempotency-Key` is honoured on PATCH as well as POST.

### T4.5 Workflow (`.github/workflows/daily-update.yml`)
The plan step and artifact in `update`; the `note` job exactly as in the architecture ("Workflow changes"). Uses the
`workflow-check` skill's rules: actions pinned by SHA, least permissions, no secret in a job that parses PDFs.
Done when: `actionlint` passes; a test or a script asserts the `note` job's `if:` holds all three conditions, that
`needs` names `deploy`, that the secret appears in exactly one step's `env`, and that the job has no `pip` and no
artifact upload; a run on a branch with the variable unset shows the `note` job skipped (paste the run link).
Go-live checklist from the security review of afdb0f0 (each one checked in the PR, by a test or a pasted line):
- the `note` job runs on the `schedule` trigger only; never `pull_request_target` or `workflow_run`;
- the `morning-note` environment is limited to branch `main`; the job has `permissions: contents: read` only;
- the failure issue is opened by a separate `if: failure()` job with fixed text, not by the job holding the key;
- the job checks out `github.sha`, not `needs.update.outputs.sha` (L6);
- the `morning-send` artifact is downloaded to `$RUNNER_TEMP`, never into the checkout; no cache; no `pip install`;
  the step runs `python -E -s -m sender deliver ...`; (superseded 2026-11-11 by main-protect N1/L1: an isolated
  `python -I -S -c` launch of a staged copy, docs/architecture/main-protect-invariant.md)
- each canary id is masked with `::add-mask::` before anything else runs;
- the artifact check allows up to `MAX_PLAN_BYTES` (`sender/common.py`), not 2 MB;
- `sender/buttondown.py` (T4.4's adapter) uses `http.client` (as built: `urllib.request` with an https-only
  opener, which runs on `http.client`; see T4.4 "As built") to the pinned host only, with timeouts, follows no
  redirect, and refuses a pagination `next` link off that host; it passes the API key to `deliver.run` as
  `stamp_secret`.
- (security delta at a168d24) no government source host in `link_hosts` has an open redirect an allowed-host link
  could use to land elsewhere (unverified so far: check each host, record the result in `docs/platform-facts.md`).

### T4.6 Enable conditions on the site (security review findings 1 to 3)
`site/templates/method.html.j2`, `index.html.j2`, `alerts.html.j2`, `site/static/morning.js`, `seats.js` header,
`config/site.yml` `morning_note.page`. Wording by technical-writer.
Done when tests show: an enabled build has no "never sent anywhere" or "Nothing is sent anywhere" sentence and Method
has the Morning note paragraph with `privacy_url`; a disabled build is byte-identical to today's for those pages; the
form shows the seat values it will send (or the visible ticked box) and sends none when it is unticked; `sent_line`
names the IP address.

### T4.7 Runbook (`docs/ops/launch-runbook.md`, a "Morning note" section; `docs/platform-facts.md`)
Brian's steps as one-action lines with links: create the account, sending domain DNS, double opt-in on, tracking
off, metadata keys (`lists` multi-select, `district`, `ward`; no `canary` key: canaries are the ids in the
`MORNING_NOTE_CANARY_IDS` environment secret), a scoped API key (the least access the chosen mode needs), reply-to
set to a team address, the `morning-note` environment (branch `main` only) and its secrets, the variable. Add the
site's host to `morning_note.sender.link_hosts` before enabling. Then the canary week, how to widen (`canary_only: false` by PR), and rollback
(unset the variable; delete a scheduled email in the dashboard before 7:00). Record each provider setting in
`docs/platform-facts.md` once someone has seen it in the account.

### T4.0 Provider probe (needs the account; team addresses only)
On a test newsletter, answer each "assumed" row of the architecture's table and write the answers into
`docs/platform-facts.md`: does an email's `filters` take a `subscriber.metadata.<key> equals` rule and reach only
those subscribers; which `status` sends at once and does `scheduled` + `publish_date` hold until then; is
`send-draft` with `subscribers` a real send with the unsubscribe link; does a metadata update keep other keys; does
the email list return `metadata` and in what order; is `{{ }}` in a body evaluated; does the form's double opt-in
apply; does a re-submit by an existing subscriber update their lists; which features need the paid add-on; and
(audience/stamp-self-set) **the public form must not accept `metadata__note_edition` or `metadata__canary`**: post
each to the embed form from a team address and confirm the subscriber's metadata does not get it. If it does, `stamp`
mode is unsafe (deliver also stops on a stray stamp, but the form must not offer the field). Also: re-submitting an
existing address must not change a confirmed subscriber's metadata; `{{ subscriber.email }}` in a body renders
literally; no preferences page lets a subscriber edit metadata; the negative tests pass (stamp one of two team
subscribers and the other gets nothing; creating a draft sends nothing); which subscriber types a filtered email
reaches. Then set `sender.mode`.
If neither mode passes, stop and return to the architect.

### T4.9 Switch-on PR (2026-11-17, backend-engineer; branch `r2-note-on`)
After the T4.0 probe (done 2026-11-16, `docs/platform-facts.md` "Morning note provider"): the form posts Buttondown
tags (no `metadata__` field; the free plan refused them on a new sign-up), the sender reads tags and writes only
`{"note_edition": <stamp>}`, each entry stands under a list the reader picked (render/section-not-picked), config
switched on with `mode: stamp` and `canary_only: false` (Brian, 2026-11-16: no canary week), and the tests that
assumed the shipped config was off build their own (`conftest.note_off`, `conftest.shipped_with`). Security notes:
architecture "Switch-on: tags, and the security notes". Before `MORNING_NOTE_SEND`: runbook section 4 item 4a (one
real sign-up shows the tags) and Brian's approval of the sample note.
Before review (2026-11-17): each entry names its meeting day and kind (`meeting`, `text.meeting_line`;
note/entry-meeting), and `max_editions` is 400, was 80 (sender/max-editions-busy-day; a 190-edition day is sent whole).
Review fixes (branch `r2-note-fix`, from a23427e): L1, L7, CR2 to CR9 and `privacy_url` checked; architecture
"Switch-on", "Review fixes (2026-11-17)".

### T4.8 Security review
Fresh review at the T4.5 commit against the nine threat points in the architecture. The workflow job does not merge
before it passes.
Launch precondition (security-note-workflow M1, Nov 11 2026): `main` is protected by a ruleset requiring a pull
request, with only the GitHub Actions bot (the daily `push` job's `data/` commit) as bypass, or the runbook's
fallback (the push job opens and merges its own PR) is merged. Without it the `morning-note` environment's main-only
rule can be bypassed by a direct push. Steps: `docs/ops/morning-note.md` step 2.0 (create-or-update script
`scripts/protect-main.ps1`, with its checks); checked in section 4 item 6 before `MORNING_NOTE_SEND` is set.

### T4.10 Gate job and main history (2026-11-17; architecture `main-protect-invariant.md`, ADR 0009)
Owner: devops-engineer unless named. One branch for T4.10.2 to T4.10.4 and T4.10.6 (same files and tests).
| Task | Depends on | Parallel |
|---|---|---|
| T4.10.1 V1 probe | runbook 2.0.1 done (Brian), one data PR merged by `push` | yes, with .2-.6 |
| T4.10.2 Gate job and wiring | none | branch A |
| T4.10.3 Push job L-C | none | branch A |
| T4.10.4 Scripts S1, S2 | none | branch A |
| T4.10.5 `github-pages` main only | none | yes |
| T4.10.6 Runbook | .2-.4 drafted | branch A |
| T4.10.7 Security review (fresh, opus/high) | branch A committed | before branch A merges |
| T4.10.8 Set `MAIN_PR_BASELINE` | .1 PASS, .5, branch A merged | last |

- **T4.10.1 V1 probe.** Exactly the steps in the architecture "V1 probe" (canary, runner, three merge methods, the
  `commit_id` check, cleanup). Done when: `docs/platform-facts.md` "Main protection" has the run link, the three
  refusal messages, the `commit_id` result and `main`'s sha before and after. If a merge goes through: the "V1 false"
  steps there, at once, then stop T4.10.8 and hand back to the architect.
- **T4.10.2 Gate job.** New first job `gate` as in the architecture "The gate job" (steps 1-6, inline, outputs `sha`,
  `verified`); `MAIN_PR_BASELINE` moves into its env; `update` `needs: gate` and checks out `needs.gate.outputs.sha`
  (output `sha` unchanged); `push` `needs: [gate, update]`; `deploy` `needs: [gate, update, push]` with
  `needs.gate.result == 'success'` in its `if:`; `note` `needs: [gate, update, deploy]`, `if:` adds
  `needs.gate.outputs.verified == 'true'`, checks out `needs.gate.outputs.sha`, and its PR-check step and `GH_TOKEN`
  are removed; new `gate-failed` job (`issues: write`, fixed title "Daily update: main history check failed",
  `--app github-actions` lookup). Header comment updated. Done when: `actionlint` passes; tests: every `PR_CASES` case
  runs against the gate step with its old verdict; new cases refuse a code PR with no review, a review only at an
  older commit, a review by a Bot, a review after `merged_at`, a DISMISSED review, two PRs for one commit, a merge
  commit whose second parent is not `head.sha`, and accept a COMMENTED review at head; a non-main ref and an empty
  baseline give `verified=false` with success; the gate's permissions are exactly the two reads and it runs no file
  from the checkout; `needs`, `ref` and `if:` of `update`, `deploy`, `note` asserted; full suite output pasted.
- **T4.10.3 Push job (L-C).** The PR's file list (both names of a rename) must equal the local
  `git diff --name-status` of `main_sha..SHA`, sorted, and be non-empty; if `changed_files` is 0 or the lists differ,
  re-read up to 5 times 10 s apart, then fail without merging. Done when: tests refuse a 0-file PR, a list missing a
  file, a list with an extra `data/` file, and still merge the normal case.
- **T4.10.4 Scripts.** `protect-main.sh`/`.ps1`: the OK check adds "required approvals 0" and `allow_auto_merge`
  false (NOT OK names what differs and says raising approvals needs ADR 0009 changed). New `merge-reviewed.sh`/`.ps1
  <pr> <sha>`: refuses unless `<sha>` is 40 hex and the PR's head; posts a COMMENT review with `commit_id=<sha>` and a
  body naming the review reports; merges `merge_method=squash`, `sha=<sha>`; deletes the head branch; prints the
  merge sha. Done when: a test runs each `.sh` against a fake `gh` (refusal on a moved head; the exact API calls), and
  `main-ruleset.json` is asserted to have approvals 0 and no bypass.
- **T4.10.5 `github-pages` main only.** Remove `gh-pages` from the environment's deployment branches (owner session;
  if the proxy blocks the API, a one-click card for Brian: Settings > Environments > github-pages > remove `gh-pages`).
  Done when: `gh api repos/gn0sh/clarksville-records/environments/github-pages/deployment-branch-policies --jq
  '.branch_policies[].name'` prints only `main`, pasted into `docs/platform-facts.md`.
- **T4.10.6 Runbook.** `docs/ops/morning-note.md`: "How it runs" (gate first; note no longer has a PR check);
  2.0.3 merge procedure (S2, every non-data PR, auto-merge off); 2.0.4 V1 probe (link to the architecture);
  section 4 new item "V1 probe passed (link)" before item 7; item 7 becomes T4.10.8 (check only at note go-live);
  "When the gate fails" (read the refused commit; if meant, move the baseline by S2-merged PR); the stale
  `main-protect/` comments in the workflow that cite the Actions bypass updated. Done when: the doc test passes and
  no line still says `GITHUB_TOKEN` cannot merge a workflow change as a fact.
- **T4.10.7 Security review.** security-engineer, fresh, opus/high, at branch A's commit, against V1, M-A, L-A, L-C,
  L-D, L-E and the consumer table. REQUEST CHANGES returns to devops.
- **T4.10.8 Baseline.** After .1 PASS, .5 and branch A merged: the runbook 4.7 steps (read every first-parent change
  outside `data/`, take `origin/main`), one PR setting `MAIN_PR_BASELINE` and making
  `test_the_committed_baseline_is_unset_or_a_sha` accept only a sha, merged with `merge-reviewed`. Done when: the next
  scheduled run's gate logs `verified=true` with a count, and `update`, `push`, `deploy` are green (link it).

Order: .1, .5 and branch A (.2, .3, .4, .6) in parallel; .7 on branch A; merge A; .8 the same day .1 passes, to
close phase 0. `MORNING_NOTE_SEND` waits on .1 PASS and .8 (runbook section 4).

### Order for T4
T4.1 + T4.2 + T4.3 + T4.6 in parallel now (T4.6 touches only templates and `morning_note.page`; T4.3 owns the rest of
the `morning_note` block). Then T4.4, then T4.5 and T4.7, then T4.8. T4.0 whenever the account exists; nothing before
it needs the account. Turning it on: precondition list in the architecture, then Brian's three switches.
