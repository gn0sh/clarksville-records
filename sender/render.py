"""Subject and body of one edition of the morning note (architecture "T4 sender", Body). Pure: no clock, no file,
no connection.

The body is the site name and the date, then per list its config label and that list's entries (body name, the
connective text, the record's own title, a link to the site's page and a link to the source document), then the
note's unplaced line when set, then one config line saying why the reader got this. The site's independence
line (`unofficial.email_line`) stands under the date and its full notice (`unofficial.notice`) at the foot, then the
note's support line and link when the note carries them (render/no-independence-line). It adds nothing the preview
page (morning/index.html) does not show: no outcome, no tally, no person's name outside a verbatim title, no
summary. Every word that is ours is config text (`morning_note.sender.text`, `morning_note.page`, `unofficial:`,
`support_line`, the list labels). The subject never names a government body or says "official" (AUTHORITY).

A record's title is untrusted text (it comes from a parsed PDF) and the body goes through the provider's own
template and Markdown step, so inert() turns every character either of them could read as markup into an HTML
character reference. Links are only the site's own pages and source URLs that pass build._is_https_uri; anything
else gives no link. The unsubscribe link and footer are the provider's; nothing here adds one.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date

from .common import DOTS, MARKUP, ZWSP, exact_url_ok, link_ok, parse_hosts

TEXT_KEYS = {"subject": ("{site_name}", "{date}"), "why": (), "open_site": ()}
MAX_TITLE = 600         # a longer title is cut here and marked with CUT; the site's page carries all of it
CUT = "..."
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


def clean(text) -> str:
    """One line of plain text: control and format characters are dropped (whitespace ones stay, as word breaks),
    then runs of whitespace become one space, and anything past MAX_TITLE characters is cut. In that order
    (render/clean-order): collapsing first left "a \\xad b" as "a  b", a double space the deliver check refuses."""
    s = "".join(c for c in str(text if text is not None else "")
                if c.isspace() or unicodedata.category(c) not in ("Cc", "Cf"))
    s = " ".join(s.split())
    return s if len(s) <= MAX_TITLE else s[:MAX_TITLE].rstrip() + CUT


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


def day_words(iso: str) -> str:
    """"2026-11-11" -> "November 11, 2026" (as the preview page writes a day)."""
    d = date.fromisoformat(iso)
    return f"{d:%B} {d.day}, {d.year}"


def context(cfg: dict) -> dict:
    """What the renderer needs from config/site.yml, and nothing else."""
    from sitegen import unofficial          # the one source of the independence wording (config `unofficial:`)
    mn = cfg["morning_note"]
    u = unofficial.load(cfg)
    return {"site_name": cfg["site_name"], "site_url": (cfg.get("alerts") or {}).get("site_url") or "",
            "text": dict(mn["sender"]["text"]), "source_label": mn["page"]["source_label"],
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
    return [subject(ctx, note["date"]), ctx["text"]["why"], ctx["text"]["open_site"], ctx["source_label"],
            ctx["page_label"], ctx["email_line"], ctx["notice"]] + (list(support[:2]) if support else []) + \
        note_text(note)


def subject(ctx: dict, iso: str) -> str:
    """The subject line. ValueError when it would name a government body or say "official"."""
    s = clean(ctx["text"]["subject"].replace("{site_name}", ctx["site_name"]).replace("{date}", day_words(iso)))
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


def sections(note: dict, entries: list[dict]) -> list[tuple[str, list[dict]]]:
    """[(list label, entries)] in the note's own order. An entry stands once, under the first of its lists (the
    key the note is sorted by), so an edition reads the same for every subscriber who shares it."""
    labels = {x["key"]: x["label"] for x in note["lists"]}
    out: list[tuple[str, list[dict]]] = []
    for e in entries:
        label = labels.get(e["lists"][0], "")
        if not out or out[-1][0] != label:
            out.append((label, []))
        out[-1][1].append(e)
    return out


def _source_words(ctx: dict, page) -> str:
    return ctx["source_label"] + (f", {ctx['page_label']} {page}" if page else "")


def body_html(ctx: dict, note: dict, entries: list[dict]) -> str:
    """The HTML body. No blank line and no indented line, so a Markdown step sees one HTML block and nothing else."""
    out = [f"<h1>{inert(ctx['site_name'])}</h1>", f"<p>{inert(day_words(note['date']))}</p>",
           f"<p>{inert(ctx['email_line'])}</p>"]
    for label, rows in sections(note, entries):
        out += [f"<h2>{inert(label)}</h2>", "<ul>"]
        for e in rows:
            page_url = site_link(ctx["site_url"], e.get("href"), ctx.get("link_hosts", ()))
            src, page = source_link(e, ctx.get("link_hosts", ()))
            links = ([f'<a href="{_attr(page_url)}">{inert(ctx["text"]["open_site"])}</a>'] if page_url else []) + \
                    ([f'<a href="{_attr(src)}">{inert(_source_words(ctx, page))}</a>'] if src else [])
            parts = [inert(e.get("body_name")), inert(e.get("recorded")), f"<strong>{inert(e.get('title'))}</strong>"]
            out.append("<li>" + "<br>".join(parts + ([" &middot; ".join(links)] if links else [])) + "</li>")
        out.append("</ul>")
    if note.get("unplaced_text"):
        out.append(f"<p>{inert(note['unplaced_text'])}</p>")
    out += [f"<p>{inert(ctx['text']['why'])}</p>", f"<p>{inert(ctx['notice'])}</p>"]
    support = support_of(ctx, note)
    if support:
        out.append(f'<p>{inert(support[0])} <a href="{_attr(support[2])}">{inert(support[1])}</a></p>')
    return "\n".join(out) + "\n"


def body_text(ctx: dict, note: dict, entries: list[dict]) -> str:
    """The same edition as plain text, for a person reading the dry run. It is not what is sent."""
    out = [clean(ctx["site_name"]), day_words(note["date"]), clean(ctx["email_line"]), ""]
    for label, rows in sections(note, entries):
        out += [clean(label), ""]
        for e in rows:
            page_url = site_link(ctx["site_url"], e.get("href"), ctx.get("link_hosts", ()))
            src, page = source_link(e, ctx.get("link_hosts", ()))
            out += [f"  {clean(e.get('body_name'))}", f"  {clean(e.get('recorded'))}", f"  {clean(e.get('title'))}"]
            out += [f"  {clean(ctx['text']['open_site'])}: {page_url}"] if page_url else []
            out += [f"  {clean(_source_words(ctx, page))}: {src}"] if src else []
            out.append("")
    if note.get("unplaced_text"):
        out += [clean(note["unplaced_text"]), ""]
    out += [clean(ctx["text"]["why"]), "", clean(ctx["notice"])]
    support = support_of(ctx, note)
    if support:
        out += ["", f"{clean(support[0])} {clean(support[1])}: {support[2]}"]
    return "\n".join(out) + "\n"
