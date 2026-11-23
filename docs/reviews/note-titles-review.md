# Reviews: morning note titles (PR #90)

Feature slug `note-titles`. Owner ask (Brian, 2026-11-22 1:40 PM CT): titles must tell a busy reader why to care.
Owner on the samples (4:48 PM CT): "This is the one."

## Agenda captions part (branch claude/note-titles-captions)

Code review, opus/high.
- 585e3aa5: REQUEST CHANGES. Must-fix `captions/uncited-title` (agenda captions rendered with no agenda cite on site and note) and `captions/non-caption-text` (bare-sponsor cut produced fragments: "A Resolution electing a"). Should-fix `captions/packet-read` (end line found in reprinted packet minutes), `captions/ambiguous-miss` (unsure entries dropped silently). Nits `captions/page-cite`, `captions/reread`, spacing.
- ed8dfe71 (delta): site cite fixed (item pages, item_link, search `ts`, feeds, items lede), sponsor cut fails closed, packet guard (end within max_pages=10, before first item-number page), unsure entries make a number ambiguous, start-page cite documented, captions reused by the second build. Open: morning note cite (on the note branch, below), should-fix capitalised word before a noted sponsor, nit comment example.
- b2a37b63: both follow-ups fixed (capitalised word before a noted sponsor gives no caption; comment example fixed). Fixture coverage 109 of 113 untitled items.

## Combined PR #90 (branch claude/note-titles-render)

Code review, opus/high.
- 1b2839a8: REQUEST CHANGES. Must-fix `captions/uncited-title/preview-page` (morning preview page printed captions citing only the minutes), `captions/uncited-title/row-wrong-agenda` (size-rule row named "the meeting's agenda" for another meeting's agenda). Should-fix `captions/uncited-title/card-level-only`, `note/unconfirmed-unflagged`, `neutrality/topic-phrase-overclaims` ("zone change" counted text amendments; "annexation" counted a progress report). Nit `neutrality/applicant-drop-best-effort`.
  Loop rule (family `captions/uncited-title` hit again): invariant and full consumer list written first, docs/architecture/agenda-title-cite-invariant.md.
- ff798e47 (delta): APPROVE WITH NITS. All six fixed; consumer list complete (adds CSV export, search index, feeds, build reference check, each with a test). Nits left: empty title on an uncitable caption with no item number in the preview; invariant doc says "earlier" agenda where "another meeting's" is meant.

Security review, opus/high.
- 1b2839a8: OK WITH FOLLOW-UPS. MEDIUM `note-privacy/lead-drop-misses-wording` (zoning lead-drop missed "zoning ordinance and map", so applicant names reached the email). LOW `sender/plan-untrusted/subject-count-unverified` (a tampered plan can mislabel counts, cannot add words). LOW `sender/subject-config-trust` (deliver did not re-check AUTHORITY). Checked sound: subject parse-back refuses 14 tampered subjects, CR/LF refused, new TAGs fixed strings, all record text through inert(), agenda URLs https + link_hosts, search.js/feeds escaping.
- ff798e47 (delta): OK. Lead-drop widened with a test over every fixture and facts title (one exception, 20-3-7, names no applicant); count risk documented as accepted; deliver.subject_ok refuses AUTHORITY. Per-line agenda cites pass the same URL checks.

Sending stays off; switching it on is a separate hard-stop ask with a test email first.

## Final head
- Full suite on ff798e47: 8856 passed, 547 skipped (1:03:09).
- 0e41843d merges main (PR #89 Digest switch-on) and 119e5ce3 adds the owner-approved sign-up pitch (Brian, 2026-11-22 5:41 PM CT: "nope, thats perfect."). Targeted tests after both: 2947 passed. Delta code review, sonnet/medium: APPROVE (merge clean in config/site.yml and sitegen/build.py; the removed "no picking" assertion was stale per "Decision: editions"; pitch accurate against lists, send_at and coming_up).
