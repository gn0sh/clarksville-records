# Security review S1: Daylight Digest M1 build (12af5ed1), 2026-11-19

security-engineer, opus/high. Scope: `git diff 1922fda3..12af5ed1` (sitegen/national*.py, digest templates, `_geo_frame.js`, national.js, us-count.js, digest.css, config/national/*, build.py/days.py/header changes, schema, qa/site_checks exemptions). Read-only; builds and tests in throwaway worktrees.

**Verdict: OK WITH FOLLOW-UPS.** No critical, high or medium findings. M1 may go on to Q1 and Q2. R1 stays blocked by the open Q2 items (design findings 2 and 11). Close findings 1 and 2 before R1.

**Most serious problem:** the lookup page can be framed by any site (GitHub Pages cannot send `frame-ancestors` or `X-Frame-Options`). In a Chromium proof of concept, an outer page on another origin framing digest/index.html can navigate the nested geo frame; a document loaded there keeps origin "null" (sandbox persists), so it would pass national.js's `e.source` and origin checks and receive `{address}`. Only `frame-src 'self'` on the index page stops this (Chromium blocked outside-origin and `data:` navigations). The defence holds but is a single point of failure (finding 2).

## Findings

1. **Low** `national/privacy-claims/id-leaves-device` (before R1). config/national/page-labels.yml:145 (`how.device-after`) says a government's ID leaves the device only on a request or "Just count me". Opening a card's "Coming up" link requests `digest/<st>/<id>.html`; the host sees it with the IP, and with analytics on, GoatCounter gets the path. Fix: reword to "...only when you send a request, tap 'Just count me', or open its coming-up page (that page's address names it; see Visits below)". Owner: ux-designer / technical-writer.
2. **Low** `national/postmessage-hardening/framed-parent`. site/static/national.js:376 (`postMessage({address}, "*")`) and :963 (mount runs in any frame); load-bearing token sitegen/national_pages.py:280-292 (`frame-src 'self'`). Fix: in `mount()`, do nothing when `window.top !== window.self` (form stays hidden; show a `target="_top"` link); comment at `index_csp` that `frame-src 'self'` guards the address and must never widen. Owner: frontend-engineer.
3. **Low, needs verification** `national/shared-origin` (R1 checklist). If the digest is ever served from https://gn0sh.github.io/clarksville-records/, `'self'` and the `daylight.us.*` localStorage keys are shared with every gn0sh Pages site. Fix: in R1 confirm github.io 301-redirects to daylight.gnoshcodes.com; never build a github.io preview with `national.enabled: true`. Owner: devops-engineer.
4. **Low, M2** `privacy-withhold/free-text-outside-items`. sitegen/national_guards.py:323-334: withheld entries keep meeting `id` (up to 80 chars of source slug), `meeting_url`, `agenda.url`. No M1 exposure. Fix in C2/B4 copy step: rewrite `id` to `<date>-<n>`, null `meeting_url`, keep `agenda.url` only on the source host; copied files pass `clean_feed` before `bind_feed`. Owner: backend-engineer.

## Open gates (already in docs/tasks)
- Design finding 2 `national/tags-existing-subscriber`: Q2(a) add-vs-replace unverified. If a post REPLACES tags this becomes high and R1 stays blocked.
- Design finding 11 `national/form-abuse`: Buttondown firewall/IP filtering unproven (docs/platform-facts.md:294). B12 not in this diff.
- Mailto clerk letter: M3; needs its own review (fixed recipient, validated address, `encodeURIComponent`, no CR/LF).

## Prior findings checked in code
Design review: 1 closed (static frame, meta CSP with script hash + exact path, `default-src 'none'`, `base-uri`/`form-action 'none'`, refuses to run unless sandboxed; parent `script-src 'self'`; site check digest/csp); 2 open; 3 M4; 4 closed (`allowed_url` everywhere, build re-check, JS `httpsUrl`/`safePath`/`setAttribute`); 5 closed; 6, 7 M2/H1; 8 closed except finding 1; 9 closed; 10 closed; 11 open; 12 closed (caps; bidi/controls/invisibles/lone surrogates stripped in Python and JS); 13 closed.
Withhold v3: 1, 2, 4, 5, 6, 7 closed in code; 3 accepted M2 item; delta low carried as finding 4.

## Checked and holding
- Item text: adapter reads stored items only when `is_shown`; `review` not settable from YAML; `bind_feed` in adapter and `build_national`; schema forces withheld on null review; writes only after every feed passes; no item text in pagedir, covered.html or logs; sender imports no national module.
- Off switch: built at 1922fda3 and 12af5ed1, switch off, real data, `diff -rq` over 684 files: identical. Non-bool `enabled` stops the build.
- XSS: Jinja autoescape; `label_html` via Markup.format; JS uses textContent only, no innerHTML; JSON via htmlsafe_json_dumps.
- postMessage: frame takes one string ≤200 chars from `parent`; parent sends only after "ready" from `fr.contentWindow` with origin "null"; fresh frame per lookup, 15 s timeout; answers >220k chars not parsed.
- Storage: three keys, validated on read, 8 KB cap, Forget clears all; no address/email/time stored.
- Network: Buttondown post sends only `email` and `tag`, credentials omitted, no referrer; us-count sends `p`, `e`, `rnd` with DNT/GPC/webdriver guards; outbound links `noopener noreferrer`.
- Supply chain / secrets: no new dependency, workflow or third-party script; no secrets.
- Info: Census JSONP may carry census.gov cookies if third-party cookies allowed; covered by "your address goes to the Census".

## Tests run (12af5ed1)
10 national/digest test files: 480 passed. test_national_browser.py with REQUIRE_BROWSER=1: passed in Chromium. site_checks on switch-on build: every digest check passed (2 unrelated data-export failures from the ad hoc build). Full suite not run to completion.

## Decisions this changed
| Finding | Decision changed | Scope | Owner |
|---|---|---|---|
| 1 id-leaves-device | yes: copy reworded now | none | ux-designer/technical-writer |
| 2 framed-parent | yes: top-frame guard added now | adds small | frontend-engineer |
| 3 shared-origin | yes: R1 checklist item | none | devops-engineer |
| 4 free-text-outside-items | yes: M2 copy-step task | M2 | backend-engineer |

Recommend: no panel needed.
