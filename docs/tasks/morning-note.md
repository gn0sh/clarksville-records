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
| T4 Sender (T4.0 to T4.8 below) | backend, devops, frontend, writer | T1-T3 merged (done) | see T4 |

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
more than `max_editions` exits 2; the module imports nothing that can open a connection (a test greps `sender/plan.py`
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
- only `type == "regular"` subscribers are recipients; with `canary_only` only those with `canary: "1"`; an edition
  with no recipient creates no email; hostile metadata (`district: "7; drop"`, `lists: ["zoning", "x"]`, a list of
  5,000 values) is ignored, not passed on;
- `stamp` writes the whole metadata object back with the other keys unchanged, and the filter value is exactly
  `"<D>.<key>"`; no code path can create an email with an empty filter while `sender.mode` is `stamp`;
- 429 with `Retry-After` is obeyed, three tries, then stop; over `max_recipients` sends nothing;
- **no personal data out**: with a fake that returns addresses, capture stdout, stderr and every raised exception
  text across success and each failure path, and assert no address, subscriber id or response body appears; the
  summary line has totals only.

### T4.5 Workflow (`.github/workflows/daily-update.yml`)
The plan step and artifact in `update`; the `note` job exactly as in the architecture ("Workflow changes"). Uses the
`workflow-check` skill's rules: actions pinned by SHA, least permissions, no secret in a job that parses PDFs.
Done when: `actionlint` passes; a test or a script asserts the `note` job's `if:` holds all three conditions, that
`needs` names `deploy`, that the secret appears in exactly one step's `env`, and that the job has no `pip` and no
artifact upload; a run on a branch with the variable unset shows the `note` job skipped (paste the run link).

### T4.6 Enable conditions on the site (security review findings 1 to 3)
`site/templates/method.html.j2`, `index.html.j2`, `alerts.html.j2`, `site/static/morning.js`, `seats.js` header,
`config/site.yml` `morning_note.page`. Wording by technical-writer.
Done when tests show: an enabled build has no "never sent anywhere" or "Nothing is sent anywhere" sentence and Method
has the Morning note paragraph with `privacy_url`; a disabled build is byte-identical to today's for those pages; the
form shows the seat values it will send (or the visible ticked box) and sends none when it is unticked; `sent_line`
names the IP address.

### T4.7 Runbook (`docs/ops/launch-runbook.md`, a "Morning note" section; `docs/platform-facts.md`)
Brian's steps as one-action lines with links: create the account, sending domain DNS, double opt-in on, tracking
off, metadata keys (`lists` multi-select, `district`, `ward`, `canary`), a scoped key, the `morning-note`
environment and secret, the variable. Then the canary week, how to widen (`canary_only: false` by PR), and rollback
(unset the variable; delete a scheduled email in the dashboard before 7:00). Record each provider setting in
`docs/platform-facts.md` once someone has seen it in the account.

### T4.0 Provider probe (needs the account; team addresses only)
On a test newsletter, answer each "assumed" row of the architecture's table and write the answers into
`docs/platform-facts.md`: does an email's `filters` take a `subscriber.metadata.<key> equals` rule and reach only
those subscribers; which `status` sends at once and does `scheduled` + `publish_date` hold until then; is
`send-draft` with `subscribers` a real send with the unsubscribe link; does a metadata update keep other keys; does
the email list return `metadata` and in what order; is `{{ }}` in a body evaluated; does the form's double opt-in
apply; does a re-submit by an existing subscriber update their lists; which features need the paid add-on. Then set
`sender.mode`. If neither mode passes, stop and return to the architect.

### T4.8 Security review
Fresh review at the T4.5 commit against the nine threat points in the architecture. The workflow job does not merge
before it passes.

### Order for T4
T4.1 + T4.2 + T4.3 + T4.6 in parallel now (T4.6 touches only templates and `morning_note.page`; T4.3 owns the rest of
the `morning_note` block). Then T4.4, then T4.5 and T4.7, then T4.8. T4.0 whenever the account exists; nothing before
it needs the account. Turning it on: precondition list in the architecture, then Brian's three switches.
