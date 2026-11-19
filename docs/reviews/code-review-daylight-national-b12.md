# Code review: B12 tools/national/request_report.py at aafbe82

Reviewer: code-reviewer (opus/high), Nov 19 2026. Verdict: **REQUEST CHANGES** (1 must-fix). Tests: 10 passed.

Holds up: once-per-subscriber counting via set; regular rows only; malformed/unknown `req-` ids counted as ignored and the total printed; no tag or address echoed; fixed error text `from None`; header, --help, env key meet the Done-when; no GoatCounter.

1. must-fix `national/report-duplicates-adapter` (request_report.py:46-98): `_fetch` + paging re-implement `sender.buttondown.Buttondown` and lose its tested hardening: no `count == rows` check (fixture says count 9 vs 4-5 rows and passes, so a short listing silently undercounts), no `_UNSAFE_URL`/second parse, no pacing or 429/Retry-After, no Content-Type check, uncaught ValueError on a bad `next` port, full rows (email_address) kept in memory. Fix: `Buttondown(key).subscribers()`, filter `type == "regular"`; drop `?type=regular` (default listing omits unconfirmed, platform-facts:288); map ValueError/ProviderError to exit 1; delete `_fetch`, `_NoRedirect` and their tests; add a FakeHTTP-opener test through `Buttondown` (pattern: tests/test_morning_sender_buttondown.py).
2. should-fix `national/report-key-on-disk` (:3-4): bash run line fails on Windows and writes the key to shell history. Give PowerShell steps in docstring and --help: `$env:BUTTONDOWN_API_KEY = Read-Host -MaskInput "Buttondown key"`, then `python -I tools\national\request_report.py`.
3. should-fix `national/report-run-steps` (:9, :126): "Standard library only" is false (sitegen.national imports yaml, jinja2); under -I user-site is not seen. Correct the docstring; add `python -m pip install -r requirements.txt`.
4. nit `national/report-no-disk-proof` (tests:45-53): also patch `builtins.open`/`os.open` to fail on write modes during `main()`.
5. nit (:125-127): catch NationalConfigError, exit 1 with its message.
6. nit (:128): map `also` aliases to the canonical id.

Most serious: finding 1 (a second keyed HTTP client without the listing-count check gives silently wrong counts).

## Delta at 15e856d / 3fc6da1
APPROVE with nits at 15e856d: all 6 findings closed. Should-fix `national/report-run-steps` (delta): -MaskInput fails on stock Windows PowerShell 5.1; fixed in 3fc6da1 with the `-AsSecureString` + NetworkCredential form (manager-checked: --help text, 17 passed). Nit `national/report-test-coupling` (FakeHTTP imported from another test module) accepted as is.
