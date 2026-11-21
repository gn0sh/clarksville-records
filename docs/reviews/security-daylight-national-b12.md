# Security review: B12 tools/national/request_report.py at aafbe82

Reviewer: security-engineer (opus/high), Nov 19 2026. Verdict: **OK with follow-ups**. No critical, high or medium findings.

Most serious problem: the docstring usage line (request_report.py:4) puts the key on the command line in bash syntax, which lands in shell history.

## Findings (all low; owner backend-engineer)
1. `national/report-key-shell-history` (request_report.py:4): use the morning-note pattern (docs/ops/morning-note.md:293, `read -rs` + `export`) and add the PowerShell form `$env:BUTTONDOWN_API_KEY = Read-Host -MaskInput`, run, then `Remove-Item Env:BUTTONDOWN_API_KEY`.
2. `national/report-url-pin-parity` (request_report.py:47-53): weaker than sender/buttondown.py:166-182 (no `_UNSAFE_URL` control-char check, no `..`/fragment refusal, no second parse of req.host/selector). No bypass found. A malformed `next` port (`:abc`, `:99999`) raises an uncaught ValueError. Reuse the sender's checks; wrap urlsplit/.port to raise ReportError.
3. `national/report-uncaught-errors` (request_report.py:60, 65): catch `http.client.HTTPException` and `RecursionError` as the sender does (line 188).
4. Info: no Content-Type check (sender does, line 211). `type=regular` filter unverified, but rows are re-filtered (line 82).

## Checked and holding
Key validated (16-256 printable, no space), Authorization header only, fixed error strings raised `from None`, no file writes; only `type` and `tags` read per row; host pinned (https, api.buttondown.com, 443, /v1/, no userinfo) on every `next`; proxies off; redirects refused; 2,000-page cap, repeat-next refused, 16 MB cap; default TLS; unknown ids counted never printed; one count per subscriber per id; advisory line in output and --help (finding 2 framing; finding 11 script part closed; firewall still Q2).

Tests: `python -m pytest tests/test_request_report.py -q` 10 passed.

## Delta at 15e856d / 3fc6da1
OK. All 3 lows closed (adapter reuse; fixed error text; key typed at a hidden prompt, not in history). New low `national/report-key-transcript` (Read-Host answers may land in a PowerShell transcript): closed in 3fc6da1 by the `-AsSecureString` form, which transcripts do not record.
