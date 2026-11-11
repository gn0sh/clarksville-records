"""Morning note, the visitor's side (Daylight M3 T3, docs/architecture/morning-note.md): the sign-up section on the
Alerts page (alerts.html#note) and the preview page (morning/index.html). The digest itself is sitegen/morning.py.

While `morning_note.enabled` is false (M3) there is no email field, no submit, no form action and no success text: the
section shows the list picker, the state line and, per picked list, the feeds that follow it now. Nothing about the
visitor leaves the device: static/morning.js reads the seats static/seats.js keeps and the picks in the page's own
#fragment, and makes no network call. The enabled path (a later CEO decision) posts straight to `form_action`, and
only the Alerts page's CSP form-action gains that one origin. Enabled, the stored seats are posted only while the
form's visible "include my saved seats" box is ticked (it prints the numbers), and privacy() gives the landing and
Method pages the text that replaces "never sent anywhere". Every word around a record's own title is config text
(`morning_note.page`).
"""
from __future__ import annotations

from datetime import date, datetime
from urllib.parse import urlsplit

from . import config, morning

PAGE = "morning/index.html"
DEFAULT_PICKS = ("zoning", "seats")   # the mock's two checked lists


def settings(cfg: dict | None = None) -> dict | None:
    cfg = config.SITE if cfg is None else cfg
    return cfg.get("morning_note") or None


def title(cfg: dict | None = None) -> str:
    """The preview page's name (config `page.preview_title`). Never "Morning note ...": base.html.j2 would then mark
    the nav's alerts.html#note link as the current page."""
    return settings(cfg)["page"]["preview_title"]


def on(cfg: dict | None = None) -> bool:
    """The sign-up section and the preview page are built: the block is set and the Alerts page is built."""
    cfg = config.SITE if cfg is None else cfg
    return settings(cfg) is not None and bool((cfg.get("alerts") or {}).get("feed_id"))


def enabled(cfg: dict | None = None) -> bool:
    m = settings(cfg) or {}
    return m.get("enabled") is True and bool(m.get("form_action")) and bool(m.get("privacy_url"))


def form_origin(cfg: dict | None = None) -> str | None:
    """The one origin the Alerts page's CSP form-action gains when the note is enabled, else None. It checks the
    value itself (morning-security/csp-origin-self-validating): the origin goes into a CSP, so anything but the
    https URL shape morning.problems() accepts (no space, `;`, `*` or userinfo in the host) gives None, whether or
    not the caller ran problems() first."""
    if not enabled(cfg):
        return None
    action = settings(cfg)["form_action"]
    if not (isinstance(action, str) and morning._HTTPS.fullmatch(action)):
        return None
    u = urlsplit(action)
    return f"{u.scheme}://{u.netloc}" if u.scheme == "https" and u.netloc else None


def privacy(cfg: dict | None = None) -> dict | None:
    """What the landing and Method pages say about the sign-up form, or None while the note is not enabled
    (morning-security/privacy-text-matches-data-flow). Off, those pages say the stored seats are never sent anywhere,
    which is true: there is no form. Enabled, the form can post them to the provider, so the pages print
    `seats_sent` instead and the Method page gains a paragraph: what is sent, to whom, how to stop, and the
    provider's privacy policy. Every word is config text (`morning_note.page`)."""
    cfg = config.SITE if cfg is None else cfg
    if not (on(cfg) and enabled(cfg)):
        return None
    m = settings(cfg)
    t, provider = m["page"], m.get("provider") or ""
    return {"provider": provider, "privacy_url": m["privacy_url"], "privacy_label": t["privacy_label"],
            "seats_sent": t["seats_sent"].format(provider=provider), "heading": t["method_heading"],
            "sent": t["method_sent"].format(provider=provider), "unsubscribe": t["method_unsubscribe"],
            "signup_link": t["method_signup_link"], "signup_href": "alerts.html#note"}


def _feeds_for(key: str, feeds: list[dict], cfg: dict) -> list[dict]:
    """The feeds that follow one list now, each with what static/morning.js needs to pick it for the stored seats:
    `seat` ("district"/"ward") and `number` for a per-seat feed (hidden until it matches), `seat` alone for a body
    feed (shown unless the stored seats name only the other seat), `fallback` for the all-zoning feed (shown when no
    per-seat feed matches)."""
    by_file = {f["file"]: f for f in feeds}
    out = []
    if key == "zoning":
        f = by_file.get("feeds/topic-rezoning.xml")
        if f:
            out.append({**f, "fallback": True})
        seat_feeds = sorted((f for f in feeds if f.get("kind") == "zoning-seat"),
                            key=lambda f: (f["seat"] != "district", f["number"]))
        out += [{**f, "per_seat": True} for f in seat_feeds]
    elif key == "seats":
        for f in feeds:
            if f.get("kind") == "body":
                out.append({**f, "seat": "district" if f["key"] == cfg["county_key"] else "ward"})
    elif key == "budget":
        out += [f for f in (by_file.get("feeds/topic-budget.xml"),) if f]
    elif key == "contracts":
        out += [f for f in (by_file.get("feeds/topic-contracts.xml"),) if f]
    return out


def _lists(feeds: list[dict], cfg: dict) -> list[dict]:
    m = settings(cfg)
    return [{"key": x["key"], "label": x["label"], "checked": x["key"] in DEFAULT_PICKS,
             "feeds": _feeds_for(x["key"], feeds, cfg), "needs_seats": x["key"] in ("zoning", "seats")}
            for x in m["lists"]]


def _section(feeds: list[dict], cfg: dict, preview: bool = False) -> dict:
    """The #note section. `preview`: the preview page is built (pages target, a note written), so the section links
    it; otherwise nothing links to it."""
    m = settings(cfg)
    fields = m.get("form_fields") or {}
    on_ = enabled(cfg)
    return {"lists": _lists(feeds, cfg), "text": m["page"], "enabled": on_,
            "action": m["form_action"] if on_ else "", "fields": fields if on_ else {},
            "sent_line": m["page"]["sent_line"].format(provider=m.get("provider") or "") if on_ else "",
            "privacy_url": m.get("privacy_url") if on_ else "",
            "preview": PAGE if preview else ""}


def alerts_context(feeds: list[dict], cfg: dict | None = None, preview: bool = False) -> dict:
    """Extra context for alerts.html.j2: `note` (None when the block is out) and, when enabled, the page's CSP.
    `preview`: morning/index.html is built beside it (build.py: only from the note sitegen/morning.py wrote)."""
    from . import views
    cfg = config.SITE if cfg is None else cfg
    if not on(cfg):
        return {"note": None}
    ctx = {"note": _section(feeds, cfg, preview)}
    origin = form_origin(cfg)
    if origin:
        ctx["csp"] = views.csp(form_origin=origin)
    return ctx


def _day_words(iso: str) -> str:
    """"2024-12-10" -> "December 10, 2024"."""
    d = date.fromisoformat(iso[:10])
    return f"{d:%B} {d.day}, {d.year}"


def _when(stamp: str) -> str:
    """A window edge as the contract writes it ("2024-12-09T07:00-06:00", the site's zone) -> "December 9, 7:00 AM".
    Anything else is shown as given."""
    try:
        t = datetime.fromisoformat(stamp)
    except ValueError:
        return stamp
    hour = t.hour % 12 or 12
    return f"{t:%B} {t.day}, {hour}:{t:%M} {'AM' if t.hour < 12 else 'PM'}"


def _source_url(url) -> str:
    """A source link as the preview page may render it in an href, else "" (the entry then shows no source link).
    morning-security/href-scheme-defense: the RPC facts and the county agendas are not schema-checked the way
    facts.json and finance.json are, so the one rule for a link (build._is_https_uri: absolute https, a host, no
    whitespace, quote or angle bracket) is applied here, where the URL becomes a link."""
    from .build import _is_https_uri   # build imports this module
    return url if isinstance(url, str) and url and _is_https_uri(url) else ""


def preview(day: dict, feeds: list[dict], cfg: dict | None = None) -> dict:
    """Context for morning.html.j2 from one day of the digest (the contract's day dict, as in latest.json: the note
    sitegen/morning.py write() returns). The unplaced line is the note's own `unplaced_text`; a backfill day (no
    entries: a source's first collection) says so in config text instead of the quiet line."""
    cfg = config.SITE if cfg is None else cfg
    m = settings(cfg)
    t = m["page"]
    w = day.get("window") or {}
    lede = t["preview_lede"].format(date=_day_words(day["date"]), **{"from": _when(w["from"]), "to": _when(w["to"])}) \
        if w.get("from") and w.get("to") else ""
    n = int(day.get("unplaced_zoning") or 0)
    all_zoning = next((f for f in feeds if f["file"] == "feeds/topic-rezoning.xml"), None)
    entries = []
    for e in day.get("entries") or []:
        src = e.get("source") or {}
        url = _source_url(src.get("url"))
        entries.append({**e, "href": e.get("href") or "",
                        "lists_attr": " ".join(e.get("lists") or []), "seat_body": e.get("seat_body"),
                        "district": e.get("district"), "ward": e.get("ward"),
                        "source": {"url": url, "page": src.get("page") if url else None}})
    return {"day": day, "entries": entries, "lede": lede, "backfill": day.get("backfill") is True,
            "unplaced": {"n": n, "text": day.get("unplaced_text") or "",
                         "feed": all_zoning["file"] if all_zoning else ""} if n else None,
            "note": _section(feeds, cfg, preview=True), "text": t}
