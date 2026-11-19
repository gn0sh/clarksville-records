# Reviews: tools/national/tag_probe.py at 910c4b4 (Q2 prep, risk R-A)

## Code review (code-reviewer opus/high): REQUEST CHANGES, 2 must-fix
Most serious: metadata never checked after the form post or the restore PATCH; a wiped `note_edition` stamp would go unseen and RESTORED still printed.
1. must-fix `national/tag-probe/metadata-unverified` (:227, 275-303, 104): snapshot metadata; compare on every read and the PATCH echo; print `metadata: unchanged` / `metadata: CHANGED (n keys before, m after; note_edition kept/lost)`, no values; manual fix: next morning-note run re-stamps (deliver.py:643-651); fake that drops metadata.
2. must-fix `national/tag-probe/manual-fix-inexact` (:156-163): print every original tag name (team address, note-/req- vocabulary); add `--restore-tags a,b,c` through set_tags with echo check, printed as one copy-paste line.
3. should-fix `national/tag-probe/restore-not-reread` (:296-303): re-read after the PATCH; RESTORED only if tags and metadata equal the snapshot.
4. should-fix `national/tag-probe/python-vs-browser` (:109-115, 279-284): print the Location path only (refuse if it has "@" or a query); word the verdict as "server-side post"; NO-CHANGE is inconclusive until R-B's live-page post; optionally send the page's Origin.
5. should-fix `national/tag-probe/type-change-no-fix` (:269-271): exact fix step and non-zero exit.
6. should-fix `national/tag-probe/restore-skipped` (:285-290): catch Exception so the restore always runs after a post.
7-9 nits: wait on Retry-After before the PATCH; label the NO-CHANGE manual fix "only if a later --dry-run shows req-probe"; 404 may mean no lookup by address.

## Security review (security-engineer opus/high): OK with follow-ups, 3 low
1. `national/tag-probe-metadata-unchecked` (same as code 1).
2. `national/tag-probe-hidden-typo` (:205-212, :243): ask for the hidden address twice; refuse on mismatch.
3. `national/tag-probe-late-change-unrecoverable` (:156-163, :281-284): on NO-CHANGE offer one re-check after 2 minutes in the same process, restoring if needed.
4. Info: tag names printed unescaped (:149-153); print only names matching `[a-z0-9-]`, else ascii().
Holding: lookup URL encoding and host pin; wrong-subscriber guard; form post pinned, no key sent, no redirects; PATCH body only `{"tags": ...}`; failure paths restore; key and address never output or written.

Manager decision: fix all; for code 4 do (a), (b) and send the page's Origin header. Problem family `national/tag-probe` (hit 1).
