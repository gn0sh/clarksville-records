# I-pub tripwire invariant (loop rule re-plan, 2026-11-19)
software-architect, 2026-11-19. Second hit in `data-off-main/ipub-*`: S2 `ipub-list-never-spent` (B4 review), then
`ipub-entry-pins-only-before` (`reviews/b4fix-code-review-1aeb9f4f.md` finding 1). ADR 0011 decision 4; tasks B4 notes.

## The invariant
For each published fact key `k = (path, fact_id)`, let `B = view(live D, k)` and `A = view(this run's data/, k)`,
where `view` is `(copies, sorted shown values)` from `published()` (a value is shown only while verified/confirmed;
a fact absent on one side has the empty view `(0, [])`). The fact **changes** when `A.copies < B.copies` (`removed`)
or, otherwise, when `B.shown` is non-empty and `A.shown != B.shown` (`changed`). **A deploy passes the tripwire only
if, for every key that changes, the reviewed list holds an entry with that `path`, `fact_id`, `change` and
`value_sha256 = sha256(canonical JSON {"before": view(B), "after": view(A)})`, copy counts included, for both kinds.
Anything unreadable, malformed or unmatched holds (exit != 0, `held=yes`), and nothing else releases the hold.**
Consequences: an entry matches exactly one transition B -> A; it is spent as soon as the live site shows A (B moves);
it matches again only if the live site shows exactly B again and the run makes exactly A again (the same reviewed
transition). A new key, or a key whose values were never shown and are still not shown, is never a change.

## Consumers and producers
| # | Where | Role | Meets? |
|---|---|---|---|
| 1 | `collector/tripwire.py:184` `published()` | the view: copies and shown values per key; wrong shape raises NotRead | meets |
| 2 | `collector/tripwire.py:233-240` `hits()` | classifier: removed / changed / no change, as above | meets |
| 3 | `collector/tripwire.py:218` `change_sha256` | the digest of both views | **fixed** (was `value_view`: one side only) |
| 4 | `collector/tripwire.py:229` `allowed` | matcher: the exact 4-tuple | meets |
| 5 | `collector/tripwire.py:241` (spent) | B is the live view, so a deploy of A retires the entry | **fixed** (a `changed` entry for A->B let C->B pass; a `removed` entry let the surviving copy take any value) |
| 6 | `collector/tripwire.py:278` hit line | prints the very digest the matcher compares; non-ASCII ids only counted (not listable: hold) | meets |
| 7 | `collector/tripwire.py:264,269,272`; `read_live`/`read_disk`/`live_tree` | fail closed: bad list 4, not read 3, any exception 3 | meets |
| 8 | `collector/reviewed_lists.py:40,56` | schema with formats, one entry per (path, fact_id), invalid raises | meets |
| 9 | `collector/reviewed_lists.py:6-9` docstring | describes the pin | **fixed** |
| 10 | `schema/published-fact-changes.schema.json:38` (`$id` 2.1) | `value_sha256` meaning | **fixed** |
| 11 | `config/published-fact-changes.yml:1-14` header | how to copy an entry | **fixed** |
| 12 | `.github/workflows/daily-update.yml:545` tripwire step | `held=no` only on exit 0 | meets |
| 13 | `.github/workflows/daily-update.yml:603-608` held-issue text | asks for path, fact_id, change, value_sha256 from the hit line | **fixed** (finding 2: asked for fact_id, change only) |
| 14 | `.github/workflows/daily-update.yml:625-633` held-issue report | whole lines, at most 40, then a count | **fixed** (finding 4: `head -c 3000` could cut a digest) |
| 15 | `.github/workflows/daily-update.yml:1190` deploy `if` | `needs.update.outputs.held == 'no'` | meets |
| 16 | `docs/adr/0011-data-off-main.md:72` decision 4 | "any change or removal not listed" (no digest detail) | meets |
| 17 | `docs/tasks/data-off-main.md:157-166` B4 notes | the pin and its residual | **fixed** |
| 18 | `collector/tests/test_tripwire.py`, `tests/test_data_shape.py:200` | tests and comment | **fixed** (new: surviving copy changes after listing HITs; C->B after A->B HITs; digest canonical form; whole-line issue report) |

18 consumers: 9 met already, 9 fixed here. Out of family but in the same commit: `conftest.py` no longer unlinks
the held basetemp lock (`main-protect/test-flake-lock-unlink`); `tests/test_protect_main.py` now checks the lock is
free rather than gone.

Residual (accepted): one entry per (path, fact_id) means two different transitions of one fact can't both be listed
at once; the second waits for the next PR. Migration: none (the list is `[]` on every branch).
