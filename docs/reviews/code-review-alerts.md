# Code review: Alerts v1 (d633b29..229e62f), 2026-11-09. Verdict: REQUEST CHANGES
1. MEDIUM alerts/xml-illegal-chars, sitegen/feeds.py:195, 162-166: XML 1.0 illegal characters (e.g. \x0c from PDF text) make a feed not well-formed. Strip them and add a test.
2. LOW alerts/topic-substring-mislabel: substring topic match ("appoint" in "disappointment"); shared with Search.
3. LOW alerts/privacy-claim: reword as "we keep no list of followers and run no sign-up".
4. LOW alerts/empty-item-title, views.py:151: give county items a fallback title.
5. LOW alerts/council-untested: council feed hrefs and multi-body ids have no tests.
6. INFO: set site_url before launch.
Checked OK: escaping, stable ids, determinism, no held values or official links in feeds, config validation, QA check.
