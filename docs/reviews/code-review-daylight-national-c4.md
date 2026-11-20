# Code review: daylight-national C4 ICS writer (b8a3396)
Reviewer: code-reviewer, opus/medium, 2026-11-19. Verdict: APPROVE WITH NITS (21 passed). UTC DTSTART contract change: right.
1. should-fix `national/feed-ics-dst-untested` (tests/test_national_feeds.py:133): add July (23:00Z) and post-Nov-1 cases.
2. nit `national/feed-ics-no-dtend` (national_feeds.py:158-162): add fixed DURATION or record zero length in 3.6.
3. nit `national/feed-atom-state-keyerror` (national_feeds.py:195): use .get with "not-posted" default.
4. nit `national/feed-ics-tz-unguarded` (national_feeds.py:152): document bind_feed precondition or fall back to all-day.
Checked and holds: injection via text(), UID/URL/DTSTART sources, 75-octet UTF-8-safe folding, CRLF, no item text,
UID stability, not wired into any page, DST conversion spot checks.
