# Daylight nationwide: one site, any US city. Decision memo

Written 2026-11-19 for Brian. Research and recommendation only; nothing built, nothing spent, nothing published.

## The recommendation, in plain words

**Yes, switch the plan to one national site, but grow it platform by platform, not city by city, and start small.**

1. One site (daylight.gnoshcodes.com), one sign-up form. Anyone types their city. If we cover it, they pick topics and get
   the weekly note. If we don't, they join a "request your city" list and we email them when it opens.
2. First wave: cities whose records sit on **Legistar**, because Legistar has a public data feed (agendas, items, votes as
   data). Granicus says 70% of the largest US cities and counties use it. One reader covers all of them.
3. The national note is a **"what's coming up" note**: each upcoming meeting, its agenda items in the city's own words,
   and a link to the official document. **No votes** in the national note until a city's votes are checked against its
   minutes, the same rule Clarksville follows today. **No AI text about named officials.** That keeps quality first at
   scale, because nothing in the note is ours to get wrong.
4. Clarksville stays the "full Daylight" city. Other cities can graduate to full Daylight (votes, finance, maps) later,
   when enough people there sign up.
5. **Timing:** start after Clarksville's morning note is live. No marketing before the January 2027 launch anyway, so the
   request list can open quietly and tell us where demand is.

Why: the city-by-city template costs about one session per city plus a deploy each, and every city has quirks (Salem's
at-large seats took three review rounds). A platform reader costs that once and then covers hundreds of cities. The
"what's coming up" note needs no per-city vote parsing, which is the part that doesn't scale.

## 1. How much of the country the big platforms cover

| Platform | Who uses it | Public data feed? | Our reader |
|---|---|---|---|
| **Legistar** (Granicus) | "70% of the largest cities and counties" ([Granicus](https://granicus.com/pdfs/product_legistar.pdf)); Granicus overall: 5,500+ agencies | **Yes**, Web API, JSON, no key for most cities. "Some clients require use of API tokens" ([API docs](https://webapi.legistar.com/Home/Examples)); 1,000 rows per reply; only items marked public | Built (PR #62 branch, proof of concept) |
| **CivicPlus** (Agenda Center, CivicClerk) | 13,000+ customers across all CivicPlus products ([CivicPlus](https://www.civicplus.com/history/)); mostly small and mid-size towns | Agenda Center: web pages + PDFs. CivicClerk: JSON behind its portal | Both built (Clarksville). But Murfreesboro's CivicPlus site **blocks us** (Cloudflare), and CivicPlus hosts many towns behind the same firewall |
| **eScribe** | Mid-size US and Canadian cities (Salem since July 2026) | JSON calendar | Built (PR #62, E1) |
| **Municode Meetings**, **PrimeGov**, **Granicus Peak/iQM2**, **BoardDocs**, **Novus** | Many smaller places | Varies; Municode is readable, others under evaluation by competitors too | None |
| Custom site / PDFs only | The long tail | No | Not worth it |

For scale: the US has **35,705 municipal and township governments** and 3,031 counties ([St. Louis Fed, 2022 Census of
Governments](https://www.stlouisfed.org/publications/regional-economist/2024/march/local-governments-us-number-type)).
"Every city" is not reachable; "most people" is, because the big cities concentrate on a few platforms.

**Unknown worth checking first (free, one session):** the exact list of Legistar cities that answer the API without a
key. Nobody publishes it. We'd build it from public Legistar site names and one polite request each, obeying robots.

## 2. Coverage tiers

| Tier | What a subscriber gets | Which cities | When |
|---|---|---|---|
| **A: Full Daylight** | Votes checked against minutes, officials pages, finance, maps | Clarksville now; others when demand is proven | As today |
| **B: Coming-up note** | Upcoming meetings, agenda items verbatim, links to official documents, topic filter | Every city on a supported platform that allows us | Wave 1 Legistar; wave 2 eScribe, CivicClerk, Municode |
| **C: Request list** | "We'll email you when your city opens" | Everyone else | From day one |

## 3. Cost at scale (stays modest)

| Subscribers | Buttondown (email) | AI (optional) | Hosting and collecting |
|---|---|---|---|
| up to 100 | free | $0 | $0 (GitHub Pages + Actions, public repo) |
| 1,000 | $9/mo | under $15/mo | $0 |
| 5,000 | $29/mo | under $15/mo | $0 |
| 20,000 | $139/mo | under $15/mo | $0 |

- Buttondown prices from [toolradar](https://toolradar.com/tools/buttondown/pricing) (not Buttondown's own page; check before buying). Above 20K it's custom; a cheaper bulk sender would be a new account (hard stop).
- **AI:** the coming-up note needs none. If we add plain-language topic tags for agenda items (never about officials),
  Haiku 5.5 costs $0.10 per million input tokens. About 4,000 agendas a month for 1,000 cities is roughly $14/month.
- **Open question to verify before building:** whether Buttondown handles one separate send per city per week (hundreds
  of small sends) or needs one send with per-subscriber content. If not, the fix may cost money (hard stop, ask first).
- Any paid tier is a spend: Brian approves each step up.

## 4. Start on demand? Yes

A request list is the cheapest way to learn where to build next, and it fits "show only what's real": a city page says
"not covered yet, get told when it is" instead of pretending. Open a city when it has, say, 3+ requests and sits on a
supported platform. Caveat: with no marketing until January, the list will be small at first; that's fine.

## 5. Legal and terms risk (low, if we keep our rules)

- **Public records and facts** aren't copyrightable; linking to the official document is safe.
- **Vendor terms:** Legistar's API page shows no terms of use, only a Granicus copyright. Salem's eScribe and Legistar
  pages showed no terms either (checked Nov 19). Each new platform gets a terms check before its first request.
- **Blocks:** some platforms block automated readers (Murfreesboro). Our rule stands: never work around a block. A
  blocked city goes to the request list as "can't cover yet".
- **Defamation risk lives in AI summaries.** A competitor's AI note wrongly told Concord, NH that its council approved
  two projects ([CJR](https://www.cjr.org/analysis/ai-local-news-civic-sunlight-maine.php)). Verbatim agenda text and
  no AI text about officials avoids this.
- **Email law (CAN-SPAM):** double opt-in (already working), one-click unsubscribe, the LLC's mailing address in the
  footer. **Privacy:** a city choice reveals roughly where someone lives; keep subscriber lists out of the repo (rule
  already in place) and say so in the privacy line.
- **Neutrality:** every official shown the same way, in every city. Same as today.

## 6. Competitors (the field is busy; our edge is trust, not coverage)

| Who | What | Coverage | Price |
|---|---|---|---|
| [Citizen Portal](https://aichief.com/ai-productivity-tools/citizen-portal/) | AI transcripts and articles, topic alerts | Many states (already covers Salem, Killeen, Murfreesboro) | Free; Pro $15/mo |
| [Hamlet](https://www.publicceo.com/2026/02/hamlet-launches-nationwide-public-meeting-coverage-over-3000-local-governments-videos-now-discoverable/) | Searchable meeting transcripts, keyword alerts | 3,000+ bodies | Free search; alerts on trial/paid |
| [Voterheads](https://govfresh.com/signal/voterheads-wants-make-easier-follow-government-council-meetings) | Agenda topic alerts | 1,500+ cities and counties (2017 figure) | Free for 5 bodies |
| [TL;DR Gov](https://tldrgov.pages.dev/coverage/expand) | Aims to cover every US local government; adds cities on request | Legistar + Municode | Unknown |
| [Civic Sunlight](https://www.cjr.org/analysis/ai-local-news-civic-sunlight-maine.php) | AI meeting newsletters, added human review after errors | ~20 Maine towns | Free |
| MultiState, Quorum, Stateside | Paid tracking for lobbyists | National | Enterprise |

Several of these use AI summaries. Daylight's line stays: **the official record only, every fact linked, no AI text about
named officials, free.** That should be the first sentence of the national page.

## 7. What this does to Salem and the template (PR #62)

- **Keep it paused.** Nothing is wasted: the Legistar reader and the eScribe reader on PR #62 are exactly the readers wave 1
  and 2 need.
- **Shelve** the per-city site pieces (one deploy repo and subdomain per city, the per-city launch checklist). One site
  replaces them.
- **Salem becomes a tier B city** in wave 1 (it spans Legistar and eScribe, a good test). Its at-large and vote work moves
  to tier A, later, only if Salem's demand earns it.
- **New pieces needed (no code yet):** a city directory (city to platform to reader), the request list, the coming-up note
  template, and the "which Legistar cities answer" probe.

## 8. Addendum (Nov 19): national Daylight will be the next iPhone app

Brian, Nov 18 9:01 PM CT: "This will be our next iphone app." The platform-by-platform plan stays the same. Here's what
changes:

- **Build data-first.** Each city's coming-up note gets a plain JSON feed on the site. The site, the email and the app
  all read that same feed, so the app needs no separate collector.
- **Push notifications cut the email bill.** Apple's push service is free, and so is Expo's push service, which Quick
  Invoice's toolchain already uses. Each app user who picks push over email is one fewer paid Buttondown seat. Email stays
  for people without iPhones. Unverified: whether Expo's free push service fits our volume.
- **New cost and hard stops.** Sending pushes means storing device tokens and city choices on a small server. That is
  personal data, likely a new account (free tier first), and a new push key (a new secret). Each one needs Brian's OK.
  The Apple Developer account and the Expo/EAS setup already exist from Quick Invoice.
- **App Store review.** Apple rejects apps that are just a website in a wrapper (guideline 4.2), so the app needs real
  native value: push alerts, saved cities and topics, and possibly an optional "use my location" to pick a city. It must
  also say plainly that Daylight is not a government app, explain the location permission and fill in the privacy label.
  Submitting is Brian's call.
- **Order (DECIDED, Brian Nov 18 9:31 PM CT): finish the website to completion first, with no app work in parallel.**
  "Develop one to completion first to avoid running into the same issue by two different sessions operating in
  vacuums." The site, request list and email note ship first; the app starts only after that, and its plan starts with
  a written lessons-learned list from the website. Site and request list first, then the email note, then the app on the same feeds. The request list doubles
  as the app's launch audience. No marketing before the January 2027 launch either way.
- **Android:** possible later from the same Expo code; not assumed.

## 8b. Sign-up by address, not a city list (Brian, Nov 18 9:36 PM CT)

Brian: "Is there a way someone could put in their address, we tell them whats available, and they include what they want
in their personal digest?" Yes. This replaces the "type your city" sign-up in section 1.

- **How it works:** the person types an address. The free US Census geocoder (no key, no account, no cost; Daylight's
  address box already uses it) returns that spot's city, county, county subdivision (township) and school districts,
  plus congressional and state legislative districts. We look up each one in our directory of bodies.
- **What they see:** one list of every body that governs that spot, each marked as one of:
  - **Covered:** a tick box to add it to their digest, with topic choices.
  - **Not covered yet:** a "Request it" button that adds them to that body's request list.
  - **Can't cover:** the site blocks automated readers, said plainly with a link to the official site (like CMCSS today).
  Unincorporated addresses show the county and school board only, which is correct.
- **Gaps the Census can't fill:** city wards and council districts aren't in Census data. Where a city publishes ward
  maps we add them per city, as Clarksville has. Otherwise the digest covers the whole council, which is fine for a
  coming-up note.
- **Directory change:** bodies are keyed by Census IDs (place, county, school district) rather than city names. The
  Legistar probe must also map each Legistar site to its Census ID. That's a one-time list, checked by hand for odd
  cases such as consolidated city-counties.
- **Address privacy:** the lookup runs in the person's browser, straight to census.gov. We never receive or store the
  address. We keep only the body IDs they ticked (and their email or, later, their device). The privacy line says this
  in one sentence, including that the address goes to the US Census Bureau to look up their area.
- **Bonus:** county and school-board coverage comes for free wherever those bodies are on a supported platform. Many
  counties use Legistar too.
- **Timeline change:** about +1 to 2 days on the website phase (the directory keyed by Census ID, and an address page in
  place of a city list). The web total becomes about 10 to 15 days.

## 8c. "Ask them to open it" letter (Brian, Nov 18 9:37 PM CT)

Brian: "when someone requests it, we can generate a letter they can send to their elected officials requesting the
participate." Plan:

- **When it shows:** only when the reason is on the government's side: the site blocks automated readers, or records are
  posted only as scanned PDFs or not at all. When the gap is ours (a platform we haven't built a reader for yet), the
  person just joins the request list. Asking officials to fix our backlog would be unfair.
- **The letter:** one fixed template, written once and reviewed (plain-language and slop-stopper passes, then Brian
  approves the wording). It is not AI-written per person, and it never names or describes any official. It asks
  neutrally for agendas, minutes and votes to be posted in a way the public and tools can read: an open data feed, or
  letting polite automated readers through the firewall. It takes no position on any issue. Fill-ins: the body's name,
  the person's own name and town. The person can edit anything before sending.
- **Who it goes to:** the body's official public contact (the clerk's office or the council's general address), taken
  from the body's own website and recorded in our directory with its source link and the date checked. The clerk is
  usually who controls how records are posted, and this avoids keeping lists of named officials. Contact details are
  added by hand when a body first gets a request, never scraped in bulk. (Google's free officials-lookup service was
  retired in 2025; the paid alternatives would be a spend.)
- **How it's sent:** a "Open in my email" button (a mailto link) plus "Copy text". It goes from the person's own email;
  Daylight never sends it, never sees whether it was sent, and keeps no copy. That keeps us out of acting on anyone's
  behalf.
- **Neutrality check:** same letter for every body in every state; QA checks no official's name appears in the template.
- **Timeline change:** about +1 day in the website phase (template, review, mailto page, contact field in the directory).
  The web total becomes about 11 to 16 days, still about 2 weeks at the low end.

## 9. Rough timeline (Nov 19; judgment call, medium-low confidence)

Calendar days at full speed, with reviews, security and QA kept. The clock starts after Clarksville's morning note is live.
Evidence: Clarksville went from start to soft live in about 6 days (Nov 7 to 13). Salem's template took 3+ days without
going live; one rule bounced through review three times.

| Phase | Days | Notes |
|---|---|---|
| 0. Spec, 3-member panel, Legistar city probe, architecture | 1-2 | Probe shows how many cities wave 1 really has |
| 1. Site with Legistar cities (city finder, coming-up pages, a feed per city) | 4-6 | Reuses the PR #62 Legistar reader. Going live needs Brian's OK |
| 2. Request-your-city list | 1 | Runs alongside phase 1 on the existing sign-up |
| 3. National email note | 3-5 | Reuses the morning note. Biggest unknown: hundreds of per-city sends on Buttondown. Brian OKs a sample |
| **Web total** | **about 11-16 (2 to 2.5 weeks), incl. +1-2 address sign-up (8b) and +1 letter (8c)** | |
| *Gate: website complete; lessons-learned note written (Brian's rule: no app work before this)* | | |
| 4. iPhone app (Expo, push, saved cities) | 5-8 | Plus 2-3 days for Brian's batched iPhone checks |
| 5. App Review | 1-3 | A rejection adds about 3-5 |
| **To the App Store** | **about 4-5 weeks** | |

**Usage:** roughly 35-45% of a weekly bar for each week the web phases run alongside other work, and 30-40% a week during
the app phases. About 1.5 weeks of a full bar in total. These figures are judgment calls; the pace log will show real burn
within a day of starting.

**Main risks to the timeline:** Buttondown per-city sends (may need a different approach or a spend); Legistar cities that
need a key, and hosts that block us; review bounces (one problem family has cost Salem 3 rounds); waiting on Brian for
deploy, account and push-key OKs; App Review rejection (web-wrapper or government-look concerns); and a slip in
Clarksville's note, since this phase starts only after it.

## Risks to watch

- **Scope creep from "any city".** Mitigation: tiers above; never promise a city we can't read.
- **Platform-wide block** (one vendor's firewall blocks all its towns). Mitigation: Legistar's API is the anchor, not
  scraped pages.
- **Load on Brian.** Each new platform still needs a first-request OK and a deploy OK (hard stops). Batch them.

## If Brian says yes: next steps (no spend)

1. Finish Clarksville's morning note (top priority, unchanged).
2. Spec + one 3-member panel on the national coming-up note (product-manager).
3. Legistar probe: list which cities answer without a key (one polite request each).
4. Architect: re-scope PR #62 to readers + city directory; shelve per-city deploys.
5. Build the request list behind the existing sign-up (deploy needs Brian's OK).
