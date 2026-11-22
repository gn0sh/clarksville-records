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

A record's title is untrusted text (it comes from a parsed PDF) and the body goes through the provider's own
template and Markdown step, so inert() turns every character either of them could read as markup into an HTML
character reference. Links are only the site's own pages and source URLs that pass build._is_https_uri; anything
else gives no link. The unsubscribe link and footer are the provider's; nothing here adds one.
"""
from __future__ import annotations

import re
from datetime import date

from .common import CUT, MAX_TITLE  # noqa: F401  common's since subject-unchecked, still importable from here
from .common import (BODY_BUDGET, CREDIT_LINE, DATE_RE, DOTS, LINKS, MARKUP, TAG, ZWSP, clean, day_words,
                     exact_url_ok, link_ok, parse_hosts, subject_line)

# sitegen.morning.SENDER_TEXT_KEYS (a test keeps them equal): each key of morning_note.sender.text, the
# placeholders it must keep
TEXT_KEYS = {"subject": ("{site_name}", "{date}"), "why": (), "open_site": (), "untitled_votes": ("{n}",),
             "header_day": ("{weekday}", "{place}"), "greeting": ("{place}",), "tagline": (), "intro": (),
             "new_on_list": (), "source_meeting": ("{date}",), "source_document": (), "plain_words": (),
             "define_ordinance": (), "define_resolution": (), "define_minutes": (), "define_bid_tab": (),
             "define_award_letter": (), "define_rfp": (), "take_part": (), "take_part_heading": (),
             "take_part_line": (), "invited": (), "coming_up": (), "coming_meeting": ("{date}", "{body}", "{meeting}"),
             "coming_body": ("{date}", "{body}"), "all_meetings": (), "more": ("{n}",)}
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
    return [subject(ctx, note["date"])] + [v for k, v in ctx["text"].items() if k != "subject"] + \
        [ctx["source_label"], ctx["meeting_line"], ctx["page_label"], ctx["email_line"], ctx["notice"],
         ctx.get("place") or "", ctx.get("site_place") or ""] + (list(support[:2]) if support else []) + \
        note_text(note)


def subject(ctx: dict, iso: str) -> str:
    """The subject line. ValueError when it would name a government body or say "official"."""
    s = subject_line(ctx["text"]["subject"], ctx["site_name"], iso)
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


def untitled_vote(e: dict) -> bool:
    """True for a vote whose record printed no title of its own (the note's `untitled`: our fallback words, a
    meeting's label, or only the document's kind such as "MINUTES") and that names its meeting's page. Never a
    zoning case (`case` set): a reader looks for one by its number (note-compact/zoning-case-hidden)."""
    return e.get("kind") == "vote" and e.get("untitled") is True and isinstance(e.get("meeting_href"), str) \
        and bool(e["meeting_href"]) and not e.get("case")


def _document(e: dict):
    """The entry's source document without its page (`#page=N`): the one link a meeting's untitled votes share."""
    url = (e.get("source") or {}).get("url")
    return url.split("#", 1)[0] if isinstance(url, str) else None


def items(rows: list[dict], list_key: str | None = COMPACT_LIST) -> list[dict | list[dict]]:
    """A section's entries as the email prints them (note/compact-untitled): each entry as itself, except that in
    the COMPACT_LIST section a meeting's untitled votes (untitled_vote), when there are COMPACT_MIN or more of them
    from one minutes document, stand as one list at the place of the first of them. Any other section (a list the
    reader picked by topic) keeps every entry. A pure function of the rows and their list, so two shapes with the
    same rows (one edition key, plan.edition_key) still read the same."""
    def key(e):
        return (e.get("body"), e["meeting_href"], _document(e)) \
            if list_key == COMPACT_LIST and untitled_vote(e) else None
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


def _item(ctx: dict, x) -> dict:
    """What one item of a section shows, the same for both bodies and every layout: `who` (the meeting line, already
    clean), `day` (ISO or None), `texts` [(kind, raw text)], kind "text", "title" (the record's own title) or
    "numbers", `page` (the site's page or ""), `src` ((words, URL) or None). An entry: its `recorded` words and its
    title. A meeting's untitled votes (items): the count line and the record's item numbers, the meeting's page and
    the minutes document, each once."""
    hosts = ctx.get("link_hosts", ())
    if isinstance(x, list):
        e = x[0]
        nums = item_numbers(x)
        # the count line leads into the numbers line; with no number to follow, it ends without its colon
        words = untitled_words(ctx, len(x))
        texts = [("text", words if nums else words.rstrip().rstrip(":"))] + ([("numbers", nums)] if nums else [])
        page_url = site_link(ctx["site_url"], e.get("meeting_href"), hosts)
        src, page = source_link({"source": {"url": _document(e), "page": None}}, hosts)
    else:
        e = x
        texts = [("text", x.get("recorded")), ("title", x.get("title"))]
        page_url = site_link(ctx["site_url"], x.get("href"), hosts)
        src, page = source_link(x, hosts)
    day = _day(e)
    return {"who": who_when(ctx, e), "day": day, "texts": [(k, t) for k, t in texts if clean(t)],
            "page": page_url, "src": (_source_words(ctx, day, page), src) if src else None,
            "entries": x if isinstance(x, list) else [x]}


def _a(url: str, words: str, style: str = "ink") -> str:
    """A link: the checked URL between `<a href="` and one of common.LINKS' fixed endings."""
    return f'<a href="{_attr(url)}{LINKS[style]}{inert(words)}</a>'


def _p(name: str, inner: str, close: str = "p") -> str:
    return f"{TAG[name]}{inner}</{close}>"


def _card(ctx: dict, it: dict) -> list[str]:
    """One white card. From a meeting: the site's date block (month, day, year; hidden from screen readers, the
    headline says the day), the meeting line as the headline and link to the site's page, the record's words, the
    source link. Anything else: body and `recorded` as a kicker, the title as the headline and link."""
    out = [TAG["card"]]
    src = [_p("source", _a(it["src"][1], it["src"][0]))] if it["src"] else []
    if it["day"]:
        d = date.fromisoformat(it["day"])
        head = _a(it["page"], it["who"]) if it["page"] else inert(it["who"])
        body = [_p("line", f"{TAG['strong']}{inert(t)}</strong>") if k == "title" else
                _p("numbers" if k == "numbers" else "line", inert(t)) for k, t in it["texts"]]
        out += [TAG["table"], TAG["tr"],
                f"{TAG['day_td']}{d:%b}<br>{TAG['day_n']}{d.day}</span><br>{d.year}</td>", TAG["card_td"],
                _p("h3", head, "h3"), *body, *src, "</td>", "</tr>", "</table>"]
    else:
        said = [t for k, t in it["texts"] if k == "text"]
        title = next((t for k, t in it["texts"] if k == "title"), "")
        kick = " &middot; ".join(inert(t) for t in [it["who"], *said] if clean(t))
        out += [_p("kicker", kick)] if kick else []
        if title:
            out.append(_p("h3_after", _a(it["page"], title) if it["page"] else inert(title), "h3"))
        out += src
    return out + ["</div>"]


def _row(ctx: dict, it: dict) -> list[str]:
    """The size rule's compact form of an item: its words and both links on one line."""
    parts = [inert(it["who"])] if clean(it["who"]) else []
    parts += [f"{TAG['strong']}{inert(t)}</strong>" if k == "title" else inert(t) for k, t in it["texts"]]
    parts += [_a(it["page"], ctx["text"]["open_site"])] if it["page"] else []
    parts += [_a(it["src"][1], it["src"][0])] if it["src"] else []
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


COMING_N = 3        # sitegen.morning.COMING_N: the meetings the "Take part" box lists


def coming(ctx: dict, note: dict) -> list[tuple[str, str]]:
    """[(words, site URL or "")] for the note's coming_up (sitegen.morning.coming_up: the next meetings in the records
    on or after the note's day, the same for every reader): config coming_meeting, or coming_body when the row has
    no meeting kind. A row that is not a {date, body} pair is left out; one whose page is not a site page keeps its
    words without a link."""
    rows = note.get("coming_up")
    out: list[tuple[str, str]] = []
    for r in rows if isinstance(rows, list) else []:
        if len(out) == COMING_N:
            break
        if not (isinstance(r, dict) and isinstance(r.get("date"), str) and DATE_RE.fullmatch(r["date"])
                and isinstance(r.get("body"), str) and clean(r["body"])):
            continue
        try:
            when = day_words(r["date"])
        except ValueError:
            continue
        meeting = clean(r["meeting"]) if isinstance(r.get("meeting"), str) else ""
        t = ctx["text"]
        line = (t["coming_meeting"] if meeting else t["coming_body"]).replace("{date}", when)
        line = line.replace("{body}", clean(r["body"])).replace("{meeting}", meeting)
        out.append((clean(line), site_link(ctx["site_url"], r.get("href"), ctx.get("link_hosts", ()))))
    return out


def _fill(ctx: dict, key: str, day: str | None = None) -> str:
    """Config text `key` with {site_name}, {place} and {weekday} filled in."""
    s = ctx["text"][key].replace("{site_name}", clean(ctx["site_name"])).replace("{place}", clean(ctx.get("place")))
    return clean(s.replace("{weekday}", f"{date.fromisoformat(day):%A}") if day else s)


def _more(ctx: dict, n: int) -> str:
    return ctx["text"]["more"].replace("{n}", str(n))


def _flat(ctx: dict, note: dict, entries: list[dict], under: dict | None):
    """[(list label, [shown item])] for the edition, each item already _item()."""
    return [(label, [_item(ctx, x) for x in items(rows, key)]) for key, label, rows in _keyed(note, entries, under)]


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
            out += [f"  {it['who']}"] + [f"  {clean(t)}" for _, t in it["texts"]]
            out += [f"  {clean(ctx['text']['open_site'])}: {it['page']}"] if it["page"] else []
            out += [f"  {clean(it['src'][0])}: {it['src'][1]}"] if it["src"] else []
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
