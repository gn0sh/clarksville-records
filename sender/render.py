"""Subject and body of one edition of the morning note (architecture "T4 sender", Body). Pure: no clock, no file,
no connection.

The HTML body (note/sunrise, 2026-11-22: design concept A "Sunrise" with concept C's plain words and invitation) is
the site's sky header (the site name, its place, "<weekday> in <place>" over the date, the sun drawn with CSS), the
site's independence line (`unofficial.email_line`), a greeting, then per list its config label and one card per
entry (body name and meeting, the connective text, the record's own title, a link to the site's page on the
headline and a link to the source document; a meeting's votes with no title of their own as one count line,
items()), the note's unplaced line when set, the plain-word definitions of the kinds of record in the edition, the
"Take part" box (an invitation and the note's next meetings, `coming_up`), then why the reader got this, the full
notice (`unofficial.notice`) and the note's support line and link when the note carries them
(render/no-independence-line). Past common.BODY_BUDGET bytes the rest stands as rows (layout()). Apart from the next
meetings (the landing's own selection from today.html) it adds nothing the site does not show: no outcome, no tally,
no person's name outside a verbatim title, no summary. Every word that is ours is config text
(`morning_note.sender.text`, `morning_note.page`, `unofficial:`, `support_line`, the list labels, `site_place`,
`today_place`). Every opening tag is one of common.TAG and LINKS, which deliver.body_ok holds it to. The subject
never names a government body or says "official" (AUTHORITY).

note-titles (2026-11-22): each edition's subject says what is inside, a count per topic in config phrases
("3 zoning cases and a budget item: your {place} morning note", common.compose); the topics are the site's own
mechanical rules (topics(): the zoning, budget and contracts lists and the item type rule), never a reading of the
words. Each card leads with its topics' config labels (else its `recorded` words) over the record's title as the
headline. A vote whose minutes printed no title and whose meeting's agenda did (`title_source` "agenda") shows that
caption only beside a link to the agenda (agenda_cite); without one it stays untitled.

A record's title is untrusted text (it comes from a parsed PDF) and the body goes through the provider's own
template and Markdown step, so inert() turns every character either of them could read as markup into an HTML
character reference. Links are only the site's own pages and source URLs that pass build._is_https_uri; anything
else gives no link. The unsubscribe link and footer are the provider's; nothing here adds one.
"""
from __future__ import annotations

import re
from datetime import date

from .common import CUT, MAX_TITLE  # noqa: F401  common's since subject-unchecked, still importable from here
from .common import (BODY_BUDGET, COMING_N, CREDIT_LINE, DATE_RE, DOTS, LINKS, MARKUP, SUBJECT_KEYS, TAG,
                     TOPICS, ZWSP, clean, compose, day_words, exact_url_ok, link_ok, parse_hosts, subject_line)

# sitegen.morning.SENDER_TEXT_KEYS (a test keeps them equal): each key of morning_note.sender.text, the
# placeholders it must keep
TEXT_KEYS = {"subject": ("{site_name}", "{date}"), "why": (), "open_site": (), "untitled_votes": ("{n}",),
             "header_day": ("{weekday}", "{place}"), "greeting": ("{place}",), "tagline": (), "intro": (),
             "new_on_list": (), "source_meeting": ("{date}",), "source_document": (), "plain_words": (),
             "define_ordinance": (), "define_resolution": (), "define_minutes": (), "define_bid_tab": (),
             "define_award_letter": (), "define_rfp": (), "take_part": (), "take_part_heading": (),
             "take_part_line": (), "invited": (), "coming_up": (), "coming_meeting": ("{date}", "{body}", "{meeting}"),
             "coming_body": ("{date}", "{body}"), "all_meetings": (), "more": ("{n}",),
             # note-titles: the subject's phrases, the cards' topic kickers, the agenda link of an agenda's title
             **{k: ("{topics}",) if k == "subject_topics" else ("{n}",) if k.endswith("_many") else ()
                for k in SUBJECT_KEYS},
             **{f"topic_{k}": () for k in TOPICS}, "title_agenda": ()}
# note/compact-untitled: a meeting's untitled votes stand as one line from this many on (a lone one stays itself)
COMPACT_MIN = 2
COMPACT_LIST = "seats"      # the one list whose untitled votes are compacted (morning.LIST_KEYS; a fixed key)
_INERT = {ord(c): f"&#{ord(c)};" for c in MARKUP}       # common.MARKUP: every markup character
_LINE_START = re.compile(r"^[-+\s]+")       # a leading "---" (a rule or front matter), a "+" or "-" list mark
# Words that would let a reader take the note for a government's own mail. Never in the subject (nor in the From
# name, which is the provider account's setting: the site name). "official" also catches "unofficial".
AUTHORITY = re.compile(r"city of|county|cmcss|\brpc\b|official", re.IGNORECASE)
# common.ADDRESS, broken: a zero-width space after the colon of "://", inside "www.", after a dot between words
_SCHEME = re.compile(r":(?=//)")
_WWW = re.compile(r"(?i)(www)\.")
_DOT = re.compile(rf"(?<=[\w-])[{DOTS}](?=\w)")
_HREF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~/%-]*(?:#[A-Za-z0-9._~%:-]*)?")


def _https(url) -> bool:
    from sitegen.build import _is_https_uri     # the one rule for a link (sitegen/build.py)
    return isinstance(url, str) and bool(url) and _is_https_uri(url)


def inert(text) -> str:
    """`text` as it may stand in the HTML body: clean(), then every markup character as a character reference."""
    # A mail client links a bare "www.", "scheme://" or "evil.example/login" in the text: a zero-width space keeps
    # the words on screen and leaves nothing to link (clean() has dropped every format character, so the only
    # zero-width spaces are these)
    s = _SCHEME.sub(":" + ZWSP, clean(text))
    s = _DOT.sub(lambda m: m.group(0) + ZWSP, _WWW.sub(r"\1" + ZWSP + ".", s))
    lead = _LINE_START.match(s)
    head = "".join(f"&#{ord(c)};" for c in lead.group(0)) if lead else ""
    s = head + s[len(lead.group(0)) if lead else 0:].translate(_INERT)
    return s.replace(ZWSP, f"&#{ord(ZWSP)};")


def _attr(url: str) -> str:
    """An already-checked https URL inside href="...": braces can never reach the provider's template step."""
    return (url.replace("&", "&amp;").replace("{", "%7B").replace("}", "%7D").replace("\"", "%22")
            .replace("'", "%27").replace("<", "%3C").replace(">", "%3E"))


def site_link(site_url, href, hosts=()) -> str:
    """The site's page for an entry, `site_url` + `href`, or "" when either is not what we wrote ourselves: the
    base must be an https URL ending in "/" on one of `hosts`, the href a plain relative path with no "..", scheme
    or host."""
    if not (_https(site_url) and site_url.endswith("/") and "#" not in site_url and "?" not in site_url
            and link_ok(site_url, hosts)):
        return ""
    if not (isinstance(href, str) and _HREF.fullmatch(href)) or ".." in href or "//" in href:
        return ""
    url = site_url + href
    return url if _https(url) and link_ok(url, hosts) else ""


def source_link(entry: dict, hosts=()) -> tuple[str, int | None]:
    """(the entry's source URL, its page) when the URL passes the https rule and is on one of `hosts`, else
    ("", None). The deliver stage refuses a body with a link to any other host (plan-untrusted/body-unchecked)."""
    src = entry.get("source") or {}
    url = src.get("url")
    if not (_https(url) and link_ok(url, hosts)):
        return "", None
    page = src.get("page")
    return url, page if isinstance(page, int) and not isinstance(page, bool) and page > 0 else None


def context(cfg: dict) -> dict:
    """What the renderer needs from config/site.yml, and nothing else."""
    from sitegen import days, morning_page, unofficial   # unofficial: the one source of the independence wording
    mn = cfg["morning_note"]
    u = unofficial.load(cfg)
    return {"site_name": cfg["site_name"], "site_url": (cfg.get("alerts") or {}).get("site_url") or "",
            # note/sunrise: the header's place words (the site's own), and the two site pages the email links
            "place": cfg.get("today_place") or "", "site_place": cfg.get("site_place") or "",
            "today_href": days.PAGE, "note_href": morning_page.PAGE,
            "text": dict(mn["sender"]["text"]), "source_label": mn["page"]["source_label"],
            "meeting_line": mn["text"]["meeting_line"],
            # note-titles: the site's item type rule (sitegen.views.item_types), read for the cards' topics
            "item_types": list(cfg.get("item_types") or []),
            "page_label": mn["page"]["page_label"], "notice": u["notice"], "email_line": u["email_line"],
            "support_label": cfg.get("support_label") or "",
            "link_hosts": parse_hosts(mn["sender"]["link_hosts"]),
            # the support link, allowed as this one URL and never as its host (Low (a)); settings.link_urls
            "link_urls": (cfg["support_url"],) if exact_url_ok(cfg.get("support_url")) else ()}


def own_text(ctx: dict, note: dict) -> list[str]:
    """Every string of an email that is ours and not the record's, for the neutrality scan: the sender's config
    text, the labels it borrows from the page, and the note's own (sitegen.morning.own_text)."""
    from sitegen.morning import own_text as note_text
    support = support_of(ctx, note)
    return [subject(ctx, note["date"]), subject(ctx, note["date"], note["entries"], note.get("coming_up"))] + \
        [v for k, v in ctx["text"].items() if k != "subject"] + \
        [ctx["source_label"], ctx["meeting_line"], ctx["page_label"], ctx["email_line"], ctx["notice"],
         ctx.get("place") or "", ctx.get("site_place") or ""] + (list(support[:2]) if support else []) + \
        note_text(note)


def subject(ctx: dict, iso: str, entries: list[dict] | None = None, coming_up=None) -> str:
    """The subject line of an edition of day `iso` (note-titles): what is inside, counted from its `entries` by
    topic (topic_counts) in config phrases, with the "meeting today" lead when the note's `coming_up` holds a meeting
    on `iso` (common.compose). With no entries given, the day's template (config `subject`). ValueError when it
    would name a government body or say "official"."""
    if entries is None:
        s = subject_line(ctx["text"]["subject"], ctx["site_name"], iso)
    else:
        today = sum(1 for r in _coming_rows(coming_up) if r["date"] == iso)
        s = compose(ctx["text"], ctx["site_name"], ctx.get("place") or "", iso, topic_counts(ctx, entries),
                    len(entries), today)
    if AUTHORITY.search(s):
        raise ValueError("the subject would name a government body or say official")
    return s


def support_of(ctx: dict, note: dict) -> tuple[str, str, str] | None:
    """(line, link label, https URL) when the note carries a support line and a link that passes the https rule
    and is exactly the configured support URL, as the site's own note does (sitegen.morning: only while
    support_enabled); else None."""
    line, url = note.get("support_line"), note.get("support_url")
    if not (isinstance(line, str) and clean(line) and ctx.get("support_label") and _https(url)
            and url in ctx.get("link_urls", ())):
        return None
    return line, ctx["support_label"], url


def sections(note: dict, entries: list[dict], under: dict | None = None) -> list[tuple[str, list[dict]]]:
    """[(list label, entries)] in the given order. An entry stands once, under `under[id]` (plan.placed: the first
    of its lists the reader picked and that selected it), else under the first of its lists (the key the note is
    sorted by). The edition key covers both, so an edition reads the same for every subscriber who shares it."""
    return [(label, rows) for _, label, rows in _keyed(note, entries, under)]


def _keyed(note: dict, entries: list[dict], under: dict | None = None) -> list[tuple[str, str, list[dict]]]:
    """sections(), each with the list key it stands under: [(key, label, entries)]."""
    labels = {x["key"]: x["label"] for x in note["lists"]}
    out: list[tuple[str, str, list[dict]]] = []
    for e in entries:
        key = under[e["id"]] if under else e["lists"][0]
        label = labels.get(key, "")
        if not out or out[-1][1] != label:
            out.append((key, label, []))
        out[-1][2].append(e)
    return out


def who_when(ctx: dict, e: dict) -> str:
    """An entry's first line: the body, and the meeting it is from ("<body name>, November 9, 2026
    formal meeting", config morning_note.text.meeting_line), so two agendas of one item never read as a duplicate
    (note/entry-meeting). Only the record's body, its meeting date and the meeting words the note carries; an entry
    with no meeting (a budget book, a solicitation) is its body alone."""
    body, day, meeting = e.get("body_name"), e.get("meeting_date"), e.get("meeting")
    if not (isinstance(day, str) and DATE_RE.fullmatch(day) and isinstance(meeting, str) and meeting.strip()
            and ctx.get("meeting_line")):
        return clean(body)
    try:
        words = day_words(day)
    except ValueError:
        return clean(body)
    line = ctx["meeting_line"]
    if not clean(body) and "{date}" in line:     # CR6: no body name, so "<date> <meeting>", the line's own tail
        line = line[line.index("{date}"):]
    return clean(line.replace("{body}", clean(body)).replace("{date}", words).replace("{meeting}", clean(meeting)))


def _source_words(ctx: dict, page) -> str:
    return ctx["source_label"] + (f", {ctx['page_label']} {page}" if page else "")


# ------------------------------------------------------------------------------------------------ note-titles
def topics(ctx: dict, e: dict) -> tuple[str, ...]:
    """The entry's topics, in common.TOPICS order, by the site's own mechanical rules (nothing is read for meaning):
    "rezoning" when it is on the zoning list (an RPC zoning case of morning_note.zoning_prefixes, a county item
    linked to one) or the item type rule (config item_types, sitegen.views.item_types: the number's prefix, else
    fixed words in the title) says rezoning; "budget" on the budget list or by the rule; "contracts" on the
    contracts list (a purchasing solicitation and its documents); "ordinance", "resolution", "appointment" by the
    rule. The rule reads the record's item number and its own title, never a title we made (`title_ours`)."""
    from sitegen.views import item_types     # the one rule (Search, the topic feeds)
    lists = set(e.get("lists") or [])
    title = "" if e.get("title_ours") else clean(_shown_title(e, ctx.get("link_hosts")))
    typed = set(item_types({"number": clean(e.get("item_number")), "title": title}, ctx.get("item_types") or []))
    on = {"rezoning": "zoning" in lists, "budget": "budget" in lists, "contracts": "contracts" in lists}
    return tuple(k for k in TOPICS if on.get(k) or (k != "contracts" and k in typed))


def _counted_as(e: dict) -> tuple:
    """What one item is, for a count: a zoning case once however many entries print it, a body's numbered item
    once (its two readings, or one item on two agendas), a solicitation once with its new documents (the ids
    `contracts/solicitation/<id>` and `contracts/document/<id>/<doc>`, sitegen.morning), else the entry itself."""
    if e.get("case"):
        return ("case", e["case"])
    parts = str(e.get("id") or "").split("/")
    if len(parts) >= 3 and parts[0] == "contracts" and parts[1] in ("solicitation", "document"):
        return ("solicitation", parts[2])
    if clean(e.get("item_number")):
        return ("item", e.get("body"), clean(e["item_number"]))
    return ("entry", e.get("id"))


def topic_counts(ctx: dict, entries: list[dict]) -> dict[str, int]:
    """{topic: distinct items} over the edition's entries, each item counted once, under its first topic (an
    ordinance that amends the budget is one budget item, not also an ordinance): the subject's numbers."""
    seen: dict[str, set] = {}
    for e in entries:
        got = topics(ctx, e)
        if got:
            seen.setdefault(got[0], set()).add(_counted_as(e))
    return {k: len(v) for k, v in seen.items()}


def agenda_cite(e: dict, hosts=None) -> tuple[str, int | None] | None:
    """(the agenda's URL, its page) when the entry's title is its meeting's agenda caption (`title_source`
    "agenda", sitegen.morning; the minutes printed none) and the agenda's link passes the https rule (and, given
    `hosts`, is on one of them); else None. Words from the agenda are never shown without a link to it."""
    if e.get("title_source") != "agenda":
        return None
    url, page = e.get("title_source_url"), e.get("title_source_page")
    if not (_https(url) and (hosts is None or link_ok(url, hosts))):
        return None
    return url, page if isinstance(page, int) and not isinstance(page, bool) and page > 0 else None


def _shown_title(e: dict, hosts=None) -> str:
    """The title the email may show: the record's, or its agenda's caption only with a link to that agenda; else
    the item's own number, or nothing."""
    if e.get("title_source") == "agenda" and agenda_cite(e, hosts) is None:
        return e.get("item_number") or ""
    return e.get("title") or ""


def untitled_vote(e: dict, hosts=None) -> bool:
    """True for a vote whose record printed no title of its own (the note's `untitled`: our fallback words, a
    meeting's label, or only the document's kind such as "MINUTES") and that names its meeting's page. Never a
    zoning case (`case` set): a reader looks for one by its number (note-compact/zoning-case-hidden). A vote titled
    from its meeting's agenda (agenda_cite) has a title and stands as itself; one whose agenda link fails stays
    untitled."""
    if agenda_cite(e, hosts) is not None:
        return False
    untitled = e.get("untitled") is True or e.get("title_source") == "agenda"
    return e.get("kind") == "vote" and untitled and isinstance(e.get("meeting_href"), str) \
        and bool(e["meeting_href"]) and not e.get("case")


def _document(e: dict):
    """The entry's source document without its page (`#page=N`): the one link a meeting's untitled votes share."""
    url = (e.get("source") or {}).get("url")
    return url.split("#", 1)[0] if isinstance(url, str) else None


def items(rows: list[dict], list_key: str | None = COMPACT_LIST, hosts=None) -> list[dict | list[dict]]:
    """A section's entries as the email prints them (note/compact-untitled): each entry as itself, except that in
    the COMPACT_LIST section a meeting's untitled votes (untitled_vote), when there are COMPACT_MIN or more of them
    from one minutes document, stand as one list at the place of the first of them. Any other section (a list the
    reader picked by topic) keeps every entry. A pure function of the rows and their list, so two shapes with the
    same rows (one edition key, plan.edition_key) still read the same."""
    def key(e):
        return (e.get("body"), e["meeting_href"], _document(e)) \
            if list_key == COMPACT_LIST and untitled_vote(e, hosts) else None
    groups: dict[tuple, list[dict]] = {}
    for e in rows:
        if key(e):
            groups.setdefault(key(e), []).append(e)
    out: list[dict | list[dict]] = []
    for e in rows:
        k = key(e)
        if k is None or len(groups[k]) < COMPACT_MIN:
            out.append(e)
        elif groups[k][0] is e:
            out.append(groups[k])
    return out


def untitled_words(ctx: dict, n: int) -> str:
    """Config text `morning_note.sender.text.untitled_votes` with {n} filled in: a count, never an outcome."""
    return ctx["text"]["untitled_votes"].replace("{n}", str(n))


def item_numbers(group: list[dict]) -> str:
    """The record's own item numbers of a group, each once, in the record's order, joined with ", "
    (note-compact/hides-item-numbers); "" when none of them has one (a kind-only "MINUTES" item)."""
    nums = [n for n in (e.get("item_number") for e in group) if isinstance(n, str) and clean(n)]
    return ", ".join(dict.fromkeys(nums))




# ------------------------------------------------------------------------------------------------ note/sunrise
def _day(e: dict) -> str | None:
    """The entry's meeting day (ISO) when it is a real one, else None."""
    d = e.get("meeting_date")
    if not (isinstance(d, str) and DATE_RE.fullmatch(d)):
        return None
    try:
        date.fromisoformat(d)
    except ValueError:
        return None
    return d


def _source_words(ctx: dict, day: str | None, page) -> str:
    """"Source document, July 2, 2026 meeting" (config source_meeting) for an entry from a meeting, else config
    source_document; then ", page N" (the page's page_label) when the link names a page."""
    t = ctx["text"]
    words = t["source_meeting"].replace("{date}", day_words(day)) if day else t["source_document"]
    return words + (f", {ctx['page_label']} {page}" if page else "")


def _labels(ctx: dict, entries: list[dict]) -> list[str]:
    """The config kicker labels (`topic_<key>`) of the topics of these entries, each once, in TOPICS order."""
    got = {k for e in entries for k in topics(ctx, e)}
    return [ctx["text"][f"topic_{k}"] for k in TOPICS if k in got]


def _item(ctx: dict, x) -> dict:
    """What one item of a section shows, the same for both bodies and every layout (note-titles): `kick` (the topic
    labels, else the entry's `recorded` words), `head` (the headline: the record's title, else the meeting line),
    `sub` (the meeting line and `recorded` when the headline and kicker do not already say them), `texts` [(kind,
    raw text)], kind "text" or "numbers", `day` (ISO or None), `page` (the site's page or ""), `src` and `agenda`
    ((words, URL) or None). An entry: its title as the headline. A meeting's untitled votes (items): the meeting
    line as the headline, then the count line and the record's item numbers, the meeting's page and the minutes
    document, each once."""
    hosts = ctx.get("link_hosts", ())
    agenda = None
    if isinstance(x, list):
        e = x[0]
        nums = item_numbers(x)
        # the count line leads into the numbers line; with no number to follow, it ends without its colon
        words = untitled_words(ctx, len(x))
        texts = [("text", words if nums else words.rstrip().rstrip(":"))] + ([("numbers", nums)] if nums else [])
        page_url = site_link(ctx["site_url"], e.get("meeting_href"), hosts)
        src, page = source_link({"source": {"url": _document(e), "page": None}}, hosts)
        kick, head, sub = _labels(ctx, x), who_when(ctx, e), []
    else:
        e = x
        texts = []
        page_url = site_link(ctx["site_url"], x.get("href"), hosts)
        src, page = source_link(x, hosts)
        kick = _labels(ctx, [x])
        said = clean(x.get("recorded"))
        title, who = clean(_shown_title(x, hosts)), who_when(ctx, x)
        head = title or who
        sub = ([who] if title and who else []) + ([said] if kick and said else [])
        kick = kick or ([said] if said else [])
        cite = agenda_cite(x, hosts)
        if cite and title:
            t = ctx["text"]
            agenda = (t["title_agenda"] + (f", {ctx['page_label']} {cite[1]}" if cite[1] else ""), cite[0])
    day = _day(e)
    return {"kick": kick, "head": head, "sub": [t for t in sub if clean(t)], "who": who_when(ctx, e), "day": day,
            "texts": [(k, t) for k, t in texts if clean(t)], "page": page_url,
            "src": (_source_words(ctx, day, page), src) if src else None, "agenda": agenda,
            "entries": x if isinstance(x, list) else [x]}


def _a(url: str, words: str, style: str = "ink") -> str:
    """A link: the checked URL between `<a href="` and one of common.LINKS' fixed endings."""
    return f'<a href="{_attr(url)}{LINKS[style]}{inert(words)}</a>'


def _p(name: str, inner: str, close: str = "p") -> str:
    return f"{TAG[name]}{inner}</{close}>"


def _card(ctx: dict, it: dict) -> list[str]:
    """One white card (note-titles): the topic kicker, the headline (the record's title, cut at a word, as the link
    to the site's page), the meeting line and `recorded`, the record's words, the source link and, for a title from
    the agenda, the agenda's link. From a meeting, all of it beside the site's date block (month, day, year; hidden
    from screen readers, the meeting line says the day)."""
    links = [_p("source", _a(x[1], x[0])) for x in (it["src"], it["agenda"]) if x]
    inner = [_p("kicker", " &middot; ".join(inert(k) for k in it["kick"]))] if it["kick"] else []
    head = _a(it["page"], it["head"]) if it["page"] else inert(it["head"])
    inner.append(_p("h3_after" if it["kick"] else "h3", head, "h3"))
    inner += [_p("line", " &middot; ".join(inert(t) for t in it["sub"]))] if it["sub"] else []
    inner += [_p("numbers" if k == "numbers" else "line", inert(t)) for k, t in it["texts"]]
    inner += links
    if not it["day"]:
        return [TAG["card"], *inner, "</div>"]
    d = date.fromisoformat(it["day"])
    return [TAG["card"], TAG["table"], TAG["tr"],
            f"{TAG['day_td']}{d:%b}<br>{TAG['day_n']}{d.day}</span><br>{d.year}</td>", TAG["card_td"],
            *inner, "</td>", "</tr>", "</table>", "</div>"]


def _row(ctx: dict, it: dict) -> list[str]:
    """The size rule's compact form of an item: its kicker, headline, words and links on one line."""
    parts = [inert(" / ".join(it["kick"]))] if it["kick"] else []
    parts += [f"{TAG['strong']}{inert(it['head'])}</strong>"] + [inert(t) for t in it["sub"]]
    parts += [inert(t) for _, t in it["texts"]]
    parts += [_a(it["page"], ctx["text"]["open_site"])] if it["page"] else []
    parts += [_a(x[1], x[0]) for x in (it["src"], it["agenda"]) if x]
    return [_p("row", " &middot; ".join(parts))]


# Which plain-word definitions an edition carries (concept C): a kind is in the edition when one of its entries'
# title, item number or source file name names it (the record's own words; a vote always comes from minutes). Only
# which fixed config sentences are printed depends on the record, never what they say.
KINDS = (("ordinance", re.compile(r"\bordinances?\b", re.IGNORECASE)),
         ("resolution", re.compile(r"\bresolutions?\b", re.IGNORECASE)),
         ("minutes", re.compile(r"\bminutes\b", re.IGNORECASE)),
         ("bid_tab", re.compile(r"\bbid[\s_-]*tab", re.IGNORECASE)),
         ("award_letter", re.compile(r"\baward[\s_-]*letter", re.IGNORECASE)),
         ("rfp", re.compile(r"\brfps?\b|\brequest[\s_-]+for[\s_-]+proposals?\b", re.IGNORECASE)))


def _said(e: dict) -> str:
    """An entry's own words the kinds are read from: its title, item number and source file name."""
    url = (e.get("source") or {}).get("url")
    name = url.split("#", 1)[0].split("?", 1)[0].rsplit("/", 1)[-1] if isinstance(url, str) else ""
    name = re.sub(r"%20|%2[dD]|%5[fF]|[+_-]", " ", name)       # "Bid%20Tab.pdf": the words, no URL library
    return " ".join(clean(v) for v in (e.get("title"), e.get("item_number"), name) if isinstance(v, str))


def definitions(ctx: dict, entries: list[dict]) -> list[str]:
    """The config definitions (`morning_note.sender.text.define_<kind>`) whose kind is in these entries, in KINDS
    order, each once."""
    said = " ".join(_said(e) for e in entries)
    votes = any(e.get("kind") == "vote" or str(e.get("id") or "").endswith("/minutes") for e in entries)
    return [ctx["text"][f"define_{k}"] for k, rx in KINDS if rx.search(said) or (k == "minutes" and votes)]


def _term(text: str) -> tuple[str, str]:
    """"Ordinance. A local law." -> ("Ordinance.", "A local law.") (sitegen.morning checks the form)."""
    s = clean(text)
    head, sep, rest = s.partition(". ")
    return (head + ".", rest) if sep else ("", s)


# COMING_N (common's since note-titles, sitegen.morning.COMING_N; a test keeps them equal): the meetings the "Take
# part" box lists


def coming(ctx: dict, note: dict) -> list[tuple[str, str]]:
    """[(words, site URL or "")] for the note's coming_up (sitegen.morning.coming_up: the next meetings in the records
    on or after the note's day, the same for every reader): config coming_meeting, or coming_body when the row has
    no meeting kind. A row that is not a {date, body} pair is left out; one whose page is not a site page keeps its
    words without a link."""
    out: list[tuple[str, str]] = []
    for r in _coming_rows(note.get("coming_up")):
        when = day_words(r["date"])
        meeting = clean(r["meeting"]) if isinstance(r.get("meeting"), str) else ""
        t = ctx["text"]
        line = (t["coming_meeting"] if meeting else t["coming_body"]).replace("{date}", when)
        line = line.replace("{body}", clean(r["body"])).replace("{meeting}", meeting)
        out.append((clean(line), site_link(ctx["site_url"], r.get("href"), ctx.get("link_hosts", ()))))
    return out


def _coming_rows(rows) -> list[dict]:
    """The first COMING_N rows of a note's coming_up that are {date, body} pairs with a real day."""
    out = []
    for r in rows if isinstance(rows, list) else []:
        if len(out) == COMING_N:
            break
        if not (isinstance(r, dict) and isinstance(r.get("date"), str) and DATE_RE.fullmatch(r["date"])
                and isinstance(r.get("body"), str) and clean(r["body"])):
            continue
        try:
            day_words(r["date"])
        except ValueError:
            continue
        out.append(r)
    return out


def _fill(ctx: dict, key: str, day: str | None = None) -> str:
    """Config text `key` with {site_name}, {place} and {weekday} filled in."""
    s = ctx["text"][key].replace("{site_name}", clean(ctx["site_name"])).replace("{place}", clean(ctx.get("place")))
    return clean(s.replace("{weekday}", f"{date.fromisoformat(day):%A}") if day else s)


def _more(ctx: dict, n: int) -> str:
    return ctx["text"]["more"].replace("{n}", str(n))


def _flat(ctx: dict, note: dict, entries: list[dict], under: dict | None):
    """[(list label, [shown item])] for the edition, each item already _item()."""
    hosts = ctx.get("link_hosts", ())
    return [(label, [_item(ctx, x) for x in items(rows, key, hosts)])
            for key, label, rows in _keyed(note, entries, under)]


def _shown_entries(secs, shown: int) -> list[dict]:
    """The entries of the first `shown` items: what the email shows (defs-of-hidden-items)."""
    return [e for it in [it for _, xs in secs for it in xs][:shown] for e in it["entries"]]


def _compose(ctx: dict, note: dict, entries: list[dict], secs, full: int, shown: int) -> str:
    """The HTML body: the first `full` items as cards, the next ones up to `shown` as rows, then "N more"."""
    iso = note["date"]
    d = date.fromisoformat(iso)
    hosts = ctx.get("link_hosts", ())
    out = [TAG["page"], TAG["sheet"], TAG["sky"], TAG["table"], TAG["tr"], TAG["sky_td"],
           f"{TAG['h1']}{TAG['mark_ring']}{TAG['mark']}</span></span>{inert(ctx['site_name'])}</h1>"]
    out += [_p("plate", inert(ctx["site_place"]))] if clean(ctx.get("site_place")) else []
    out += [_p("weekday", inert(_fill(ctx, "header_day", iso))), _p("date", f"{d:%B} {d.day}"), "</td>",
            TAG["sun_td"], f"{TAG['sun_box']}{TAG['sun_ring']}{TAG['sun']}</span></span></div>", "</td>",
            "</tr>", "</table>", "</div>", _p("unofficial", inert(ctx["email_line"])), TAG["intro_box"],
            _p("greeting", inert(_fill(ctx, "greeting"))), _p("tagline", inert(_fill(ctx, "tagline"))),
            _p("intro", inert(_fill(ctx, "intro"))), "</div>"]
    n, total = 0, sum(len(xs) for _, xs in secs)
    for label, xs in secs:
        if n >= shown:
            break
        out += [TAG["section"]] + ([_p("kicker", inert(ctx["text"]["new_on_list"]))] if n == 0 else [])
        out.append(_p("h2", inert(label), "h2"))
        for it in xs:
            if n >= shown:
                break
            out += _card(ctx, it) if n < full else _row(ctx, it)
            n += 1
        if n >= shown and shown < total:
            more = site_link(ctx["site_url"], ctx.get("note_href"), hosts)
            words = _more(ctx, total - shown)
            out.append(_p("row", _a(more, words) if more else inert(words)))
        out.append("</div>")
    if shown == 0 and total:        # not even one row fits: the "N more" line alone
        more = site_link(ctx["site_url"], ctx.get("note_href"), hosts)
        out += [TAG["section"], _p("row", _a(more, _more(ctx, total)) if more else inert(_more(ctx, total))), "</div>"]
    if note.get("unplaced_text"):
        out += [TAG["section"], _p("note", inert(note["unplaced_text"])), "</div>"]
    defs = definitions(ctx, _shown_entries(secs, shown))
    if defs:
        out += [TAG["words"], _p("words_h2", inert(ctx["text"]["plain_words"]), "h2")]
        for term, rest in map(_term, defs):
            out.append(_p("define", (f"{TAG['strong']}{inert(term)}</strong> " if term else "") + inert(rest)))
        out.append("</div>")
    out += [TAG["part_box"], TAG["part"], _p("part_kicker", inert(ctx["text"]["take_part"])),
            _p("part_h2", inert(_fill(ctx, "take_part_heading")), "h2"),
            _p("part_line", inert(_fill(ctx, "take_part_line"))), _p("invited", inert(_fill(ctx, "invited")))]
    rows = coming(ctx, note)
    if rows:
        out.append(_p("coming_kicker", inert(ctx["text"]["coming_up"])))
        out += [_p("coming", _a(url, words, "white") if url else inert(words)) for words, url in rows]
    today = site_link(ctx["site_url"], ctx.get("today_href"), hosts)
    out += [_p("button_p", _a(today, ctx["text"]["all_meetings"], "button"))] if today else []
    out += ["</div>", "</div>", TAG["foot"], _p("foot_first", inert(ctx["text"]["why"])),
            _p("foot_p", inert(ctx["notice"]))]
    support = support_of(ctx, note)
    if support:
        out.append(_p("foot_p", f"{inert(support[0])} {_a(support[2], support[1])}"))
    out += [CREDIT_LINE, "</div>", "</div>", "</div>"]   # the site footer's gnoshcodes credit (note/credit-logo)
    return "\n".join(out) + "\n"


def _size(html: str) -> int:
    return len(html.encode("utf-8"))


def layout(ctx: dict, note: dict, entries: list[dict], under: dict | None = None):
    """(sections, full, shown) for an edition (note/sunrise size rule; Gmail clips a message at about 102 KB, which
    would hide the notice, the support line and the provider's unsubscribe link): every item a card when the body
    fits ctx["budget"] (common.BODY_BUDGET) bytes; else as many cards as fit with every later item as a row; else
    rows only, as many as fit, then one "N more on the site" line linking the day's note on the site. A pure
    function of the rows, so an edition still reads the same for every subscriber who shares it."""
    budget = ctx.get("budget") or BODY_BUDGET
    secs = _flat(ctx, note, entries, under)
    total = sum(len(xs) for _, xs in secs)

    def fits(full: int, shown: int) -> bool:
        return _size(_compose(ctx, note, entries, secs, full, shown)) <= budget

    def most(ok, hi: int) -> int:        # the largest k in [0, hi] with ok(k); ok holds up to a point, then fails
        lo = 0
        while lo < hi:
            mid = (lo + hi + 1) // 2
            lo, hi = (mid, hi) if ok(mid) else (lo, mid - 1)
        return lo
    if fits(total, total):
        return secs, total, total
    if fits(0, total):
        return secs, most(lambda k: fits(k, total), total), total
    return secs, 0, most(lambda m: fits(0, m), total)


def body_html(ctx: dict, note: dict, entries: list[dict], under: dict | None = None) -> str:
    """The HTML body (note/sunrise): the sky header, the greeting, one section per list, the plain words, the "Take
    part" box and the footer, every opening tag one of common.TAG or LINKS. No blank line and no indented line, so
    a Markdown step sees one HTML block and nothing else."""
    secs, full, shown = layout(ctx, note, entries, under)
    return _compose(ctx, note, entries, secs, full, shown)


def body_text(ctx: dict, note: dict, entries: list[dict], under: dict | None = None) -> str:
    """The same edition as plain text, in the same order (with the same "N more" cut), for a person reading the dry
    run. It is not what is sent."""
    secs, _, shown = layout(ctx, note, entries, under)
    iso, hosts = note["date"], ctx.get("link_hosts", ())
    out = [clean(ctx["site_name"])] + ([clean(ctx["site_place"])] if clean(ctx.get("site_place")) else [])
    out += [_fill(ctx, "header_day", iso), day_words(iso), clean(ctx["email_line"]), "", _fill(ctx, "greeting"),
            _fill(ctx, "tagline"), _fill(ctx, "intro"), "", clean(ctx["text"]["new_on_list"]), ""]
    n, total = 0, sum(len(xs) for _, xs in secs)
    for label, xs in secs:
        if n >= shown:
            break
        out += [clean(label), ""]
        for it in xs:
            if n >= shown:
                break
            out += [f"  {clean(' / '.join(it['kick']))}"] if it["kick"] else []
            out += [f"  {clean(it['head'])}"] + [f"  {clean(t)}" for t in it["sub"]]
            out += [f"  {clean(t)}" for _, t in it["texts"]]
            out += [f"  {clean(ctx['text']['open_site'])}: {it['page']}"] if it["page"] else []
            out += [f"  {clean(x[0])}: {x[1]}" for x in (it["src"], it["agenda"]) if x]
            out.append("")
            n += 1
    if shown < total:
        more = site_link(ctx["site_url"], ctx.get("note_href"), hosts)
        out += [clean(_more(ctx, total - shown)) + (f": {more}" if more else ""), ""]
    if note.get("unplaced_text"):
        out += [clean(note["unplaced_text"]), ""]
    defs = definitions(ctx, _shown_entries(secs, shown))
    if defs:
        out += [clean(ctx["text"]["plain_words"])] + [f"  {clean(x)}" for x in defs] + [""]
    out += [clean(ctx["text"]["take_part"]), _fill(ctx, "take_part_heading"), _fill(ctx, "take_part_line"),
            _fill(ctx, "invited")]
    rows = coming(ctx, note)
    if rows:
        out += [clean(ctx["text"]["coming_up"])] + [f"  {w}" + (f": {u}" if u else "") for w, u in rows]
    today = site_link(ctx["site_url"], ctx.get("today_href"), hosts)
    out += [f"{clean(ctx['text']['all_meetings'])}: {today}"] if today else []
    out += ["", clean(ctx["text"]["why"]), "", clean(ctx["notice"])]
    support = support_of(ctx, note)
    if support:
        out += ["", f"{clean(support[0])} {clean(support[1])}: {support[2]}"]
    return "\n".join(out) + "\n"
