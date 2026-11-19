# Security review: privacy-withhold v3 (a8e8c740), security-engineer opus/high, 2026-11-19

Verdict: OK WITH CHANGES (no critical or high). No config or data edit could widen what M1 publishes; 322 tests passed.

Checked and holding: the digest covers the whole parsed entry (YAML merge keys, duplicate keys, dates vs strings,
int/str/bool, NFC/NFD and homoglyphs, defaults); `daylight.body: county` and the county collector URL are fixed in code;
site.yml/council.yml redirection; two covered entries sharing a source refused; gov-flags closed keys, show rules hide
only; `review` can't be set from YAML; schema requires `review` and null forces withheld; errors print no item text.

Findings:
1. Medium `privacy-withhold/review-row-opaque` (national.py 107-125, arch 11.1 row 7): rows pin an opaque hash; a
   two-PR sequence can hide a source change from the reviewer. Fix: pin the readable canonical entry in the row.
2. Medium `privacy-withhold/free-text-outside-items` (national_guards.py 265-293): withheld bodies keep `title`, `time`,
   `status_as_posted`, `body.name` (2,000 chars each). Fix: fixed title, null the rest, overwrite `body.*` from the entry.
3. Medium (residual judged differently), arch 11.1 row 20: the repo is public, so `national-data` git history is
   published bytes. Fix in M2: keep item text out of git (Actions cache/artifact keyed by `review`); commit counts/ids.
4. Low `privacy-withhold/bind-shape`: bind_feed fails open when `meetings` is a dict; unknown top-level keys survive.
5. Low `national/host-ok-unchecked`: host_ok on daylight entries unchecked; odd YAML types crash with a bare TypeError.
6. Low `privacy-withhold/source-unique-covered-only`: a cant-cover entry can carry `body: county`.
7. Low `privacy-withhold/error-echo`: BindError echoes untrusted ids without a length cap.
Accepted residual (agreed): the public digest is not a signature; D1/D2 attestation is the integrity control in M2.
