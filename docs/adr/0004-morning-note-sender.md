# ADR 0004: Morning note sender: Buttondown, one edition email per identical selection

Status: proposed (software-architect, 2026-11-10). Provider chosen by Brian on 2026-11-10 (docs/status.md,
Decisions). Not built; needs the T4 security review and Brian's go-ahead before anything is sent. Details:
`docs/architecture/morning-note.md`, "T4 sender".

## Context
The site writes each day's "what's new" as `morning/<date>.json` (ADR-free M3 work, off by default). Subscribers pick
lists (zoning, my two seats, budget, contracts) and may store a county district and a city ward. The promise on the
page is one short email on a day when something on your list is new, and nothing otherwise. The repository and its
Actions logs are public. Sending, the account, the key and any cost are hard stops owned by Brian.

## Decision
1. Buttondown holds the list and does sign-up, double opt-in, unsubscribe and delivery. We keep no copy of any address.
2. The sender computes, for each active subscriber, exactly what `morning.select()` returns for their lists and
   seats, groups subscribers with an identical non-empty result into an **edition**, and creates one provider email
   per edition. Nobody gets more than one email a day; nobody gets an empty one.
3. It runs as two stages: a pure, network-free **plan** in the job that builds the site (also the dry run, run
   daily), and a standard-library **deliver** step in its own job that alone holds the key.
4. The day is claimed in the provider (email metadata `note_date`, `note_sha256`), not in a file in the repository;
   if that record cannot be read, nothing is sent.
5. Delivery mode (`stamp`: per-day metadata value plus a filtered, scheduled email; or `ids`: send-draft to subscriber
   ids) is chosen by a probe on a test newsletter, because the public docs do not settle it.

## Alternatives considered
- **A fixed set of segment emails** (per list, per district, per ward). Strongest case: the sender never reads a
  subscriber, so its key needs no subscriber access and no personal data ever enters CI. Rejected because one person
  can match several segments on the same morning (three lists; a city case that prints both a ward and a district)
  and would get several emails, some repeating the same case.
- **One send per subscriber.** Same content as editions with N requests a day and N chances to fail half way.
- **One email with per-person conditional content.** Rests on unverified template and filter features, and cannot be
  quiet for a person with nothing new.
- **Do not send email; feeds only.** Already shipped (Atom feeds per body, topic and seat). It stays the fallback if
  the probe fails or Brian does not go ahead; the sign-up section already says "follow by feed now".
- **A "sent" ledger file committed to the repository.** Rejected: the job holding the mail key would also need a
  write token, and the provider's own record survives a lost runner.

## Consequences
- The key needs subscriber access (write for `stamp`, read for `ids`). This is the main thing the security review
  must weigh; `max_recipients` and `canary_only` bound a mistake.
- `stamp` may need Buttondown's paid "Tagging & segmentation" add-on (+$9 a month as shown on 2026-11-10; unverified
  for metadata filters). The free tier covers the first 100 subscribers. Both are Brian's spend decisions.
- A document collected between the first send and 7:00 is not mailed that day or the next; it is on the site and feeds.
- A run that finishes after `latest_send` skips the day rather than sending late.
- Reversible: the sender is one package and one workflow job behind three switches. Changing provider means a new
  adapter file and a new sign-up form target; subscribers would have to be moved by the provider's export, which is
  the costly part. That is why the provider choice is recorded here.
