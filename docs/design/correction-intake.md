# Correction intake ("Report an error", M1.5)

Status: built 2026-11-09 (frontend-engineer). Manager decision; spec N5, G2, G6 (docs/specs/clarksville-records.md).

## Constraints
- No server, no account of ours, no new service. The site stays static.
- Nothing about the reader is stored or sent by the site. No form posts, no cookies, no storage, `connect-src 'none'`.
- Neutral: the same link and the same wording on every fact, for every official.

## What the reader sees
1. **Links.** Every fact row keeps its "Report an error" link (macro `report` in `_macros.html.j2`), now pointing at
   `report.html` instead of `about.html#corrections`. Every fact-bearing page also ends with a small
   "Report an error on this page" line (`base.html.j2`, shown for the templates in `sitegen/build.py`
   `REPORT_TEMPLATES`): meeting, items, votes, official (county and council member, and member year pages), roster
   official, district, council home, council meetings and items, finance index, fund, capital, Bids and awards index
   and solicitation pages. The landing, About, Search, Data, Changes and the report page have none (the landing must
   still fit 375x667).
2. **Fragment.** `static/nav.js` sets the link's `#fragment` just before it is followed (mousedown, touchstart,
   focusin, click): `page=<site path>&id=<fact id>`. The fact id is the `data-fact-id` of the row the link sits in;
   for the page-level link it is the `#anchor` the reader arrived at (e.g. an item on a year page), if any. A fragment
   is never sent to a server, so the static host's logs see only `report.html`.
3. **report.html** (one new page; `static/report.js` is the one new script). Says what to include (page address, the
   fact or its id, the source document and page), then offers the channels in `config/site.yml` `corrections:`.
   With both empty (the default) it says "Corrections open when the site launches." Without scripts the page still
   works: the instructions show and the channel links open the empty issue form or a plain mailto.
4. **About** (`#corrections`, `#how-corrections-work`): a report is checked against the source document it names; the
   site shows what the source says, never a changed value without a source; the same rule for every official and
   record; every fix is recorded on the Changes page.

## Channels (config/site.yml `corrections:`)
| key | value | link |
|---|---|---|
| `github_repo` | `owner/name` of the **public** repo | `https://github.com/<repo>/issues/new?template=correction.yml`, prefilled by report.js with `title`, `page_url`, `fact_id` (issue-form field ids) |
| `email` | a plain address | `mailto:<address>`, prefilled with `subject` and `body` |

The issue form is `.github/ISSUE_TEMPLATE/correction.yml` (fields `page_url`, `fact_id`, `shown`, `source`; label
`correction`, which GitHub applies only if the label exists in the repo). GitHub ignores a `body=` parameter when a
form template is used, so the prefill uses the form's field ids instead. A GitHub report needs the reader's own free
GitHub account and is public; the form asks for no personal details. The build refuses any other value shape
(`build.corrections_problems`): the repo must be `owner/name`, the email a plain address (no `?`, quotes, spaces or
angle brackets), and no other key.

## Security notes (for the security review)
- report.js reads `location.hash` only. Each value is decoded in a try/catch and kept only when it matches a strict
  pattern (`PAGE_RE`: a relative `*.html` site path, no `..`, `//`, scheme or leading `/`; `ID_RE`: letters, digits
  and `_ . : / -`, at most 160 characters). Anything else is dropped.
- Kept values are written with `textContent` only (no `innerHTML` anywhere in report.js; a test checks this).
- Every value put into a link is encoded with `encodeURIComponent` plus `!'()*`. The link bases come from the page's
  own HTML (built from validated config) and must start with `https://github.com/` or `mailto:` (without `?`).
- The absolute page address is added only on an http(s) site, so a local file path never goes into a report.
- No new CSP source: report.js is `'self'`. The GitHub and mailto links are marked `data-ext="corrections"` and
  site_checks allows exactly the configured URL (and `mailto:` only on report.html).

## Turning it on (Brian)
In `config/site.yml`, for example:
```yaml
corrections:
  github_repo: "gn0sh/clarksville-records"   # only once the repo is public
  email: ""                                  # or the address Brian chooses
```
