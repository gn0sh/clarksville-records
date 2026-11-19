"""Daylight Digest page builder (sitegen/national_pages.py; docs/architecture/daylight-national.md 1a, 3.4, 3.5, 4.0,
4.3, 6, 7a, 11; task B4). Problem keys: privacy-withhold/national-prefix (consumer 3: the coming-up page prints items
only from the JSON, a withheld government the fixed label), national/csp-jsonp-gadget (the Census in no CSP but the
frame's), national-switch/byte-identical (off: nothing changes; on: only the three fixed fragments and new files).

The switch tests build the fixture site (about a second) for the pages target; the real-data tests make the feeds
from data/ through the build's loaders and skip only as tests/test_national_clarksville.py does."""
import html as html_mod
import json
import os
import re
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest

from sitegen import build as build_mod, config, county_agendas
from sitegen import national as nat
from sitegen import national_clarksville as ncl
from sitegen import national_pages as npg

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "site" / "fixtures" / "facts.sample.json"
FIXTURE_SEATS = ROOT / "site" / "fixtures" / "seats.sample.yml"
FIXTURE_DISTRICTS = ROOT / "site" / "fixtures" / "districts.sample.json"
COUNCIL_ID, COUNTY_ID = "place-4715160", "county-47125"
CENSUS = "geocoding.geo.census.gov"
BUILT_AT = datetime(2026, 11, 19, 18, 0, tzinfo=timezone.utc)
DIGEST_HTML = {"digest/index.html", "digest/covered.html", "digest/requested.html", "digest/how.html",
               "digest/geo-frame.html",
               f"digest/tn/{COUNCIL_ID}.html", f"digest/tn/{COUNTY_ID}.html"}
DIGEST_JSON = {f"digest/tn/{COUNCIL_ID}.json", f"digest/tn/{COUNTY_ID}.json"}


def _build(out: Path, national) -> Path:
    saved = config.SITE.get("national", "absent")
    try:
        if national == "absent":
            config.SITE.pop("national", None)
        else:
            config.SITE["national"] = {"enabled": national}
        build_mod.build(FIXTURE, out, internal=True, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS,
                        target="pages", today=date(2026, 11, 19))
    finally:
        if saved == "absent":
            config.SITE.pop("national", None)
        else:
            config.SITE["national"] = saved
    return out


def _tree(out: Path) -> dict[str, bytes]:
    return {p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def sites(tmp_path_factory):
    base = tmp_path_factory.mktemp("national")
    return {k: _tree(_build(base / k / "site", v)) for k, v in (("absent", "absent"), ("off", False), ("on", True))}


@pytest.fixture(scope="module")
def page_labels():
    return npg.load_page_labels()


@pytest.fixture(scope="module")
def loaded():
    return nat.load_all()


# --- the switch ----------------------------------------------------------------------------------------------------

def test_shipped_switch_is_off():
    assert config.SITE["national"] == {"enabled": False}
    assert npg.enabled() is False


@pytest.mark.parametrize("block", [{"enabled": "yes"}, {"enabled": 1}, {"enable": True}, {"enabled": True, "x": 1},
                                   "on", []])
def test_switch_refuses_anything_but_true_or_false(block):
    with pytest.raises(npg.NationalBuildError):
        npg.enabled({"national": block})


def test_switch_off_writes_no_digest_file_and_changes_no_page(sites):
    """national-switch/byte-identical: off is byte for byte the build without the block, writes nothing under digest/,
    copies neither digest script, and leaves the Menu and the front page alone (B5 proves it against main)."""
    off = sites["off"]
    assert off == sites["absent"]
    assert not [p for p in off if p.startswith("digest/")]
    assert "static/national.js" not in off and "static/us-count.js" not in off and "static/digest.css" not in off
    assert not any(b"digest/" in body for p, body in off.items() if p.endswith(".html"))
    assert not any(b"digest.css" in body for body in off.values())
    assert b'class="digest-line"' not in off["index.html"]
    assert off["method.html"].count(npg.METHOD_SENTENCE.encode()) == 1


def test_switch_on_writes_the_page_set_and_no_feeds(sites):
    on = sites["on"]
    digest = {p for p in on if p.startswith("digest/")}
    assert digest == DIGEST_HTML | DIGEST_JSON
    assert not [p for p in on if p.endswith((".ics", ".xml")) and p.startswith("digest/")]      # M4
    assert "static/national.js" in on and "static/us-count.js" in on and "static/digest.css" in on
    assert set(on) - set(sites["off"]) == digest | {f"static/{n}" for n in npg.STATIC_ONLY}


def test_digest_stylesheet_is_linked_by_digest_pages_only(sites):
    """Design 0a, architecture 7a (d): static/digest.css is the digest pages' own stylesheet. Each digest page links it
    once, after style.css; the Census frame and every page outside digest/ never name it; style.css is the same file
    with the switch on or off."""
    on = sites["on"]
    assert on["static/digest.css"] == (ROOT / "site" / "static" / "digest.css").read_bytes()
    assert on["static/style.css"] == sites["off"]["static/style.css"]
    for rel, body in on.items():
        if not rel.endswith(".html"):
            assert b"digest.css" not in body or rel == "static/digest.css", rel
            continue
        html = body.decode()
        if rel in DIGEST_HTML - {"digest/geo-frame.html"}:
            root = "../" * rel.count("/")
            link = f'<link rel="stylesheet" href="{root}static/digest.css">'
            assert html.count(link) == 1 and html.count("digest.css") == 1, rel
            assert html.index(f'href="{root}static/style.css"') < html.index(link) < html.index("</head>"), rel
        else:
            assert "digest.css" not in html, rel


def test_digest_stylesheet_adds_no_colour_and_loads_nothing():
    """Design 0a: every colour is a style.css token (no hex, rgb or hsl of its own, no red or green), and the file
    names no URL and no @import, so the pages' style-src-elem 'self' is all it needs (architecture section 6)."""
    css = (ROOT / "site" / "static" / "digest.css").read_text(encoding="utf-8")
    rules = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\b(rgb|hsl)a?\(", rules)
    assert not re.search(r"\b(red|green)\b|@import|url\(|//", rules)
    tokens = set(re.findall(r"var\((--[a-z0-9-]+)\)", rules))
    style = (ROOT / "site" / "static" / "style.css").read_text(encoding="utf-8")
    assert tokens and all(re.search(rf"^\s*{t}:", style, re.M) for t in tokens), tokens
    assert "var(--sun)" not in rules and "var(--seal)" not in rules          # orange is the focus ring only
    assert all("outline" in line for line in rules.splitlines() if "var(--focus)" in line)
    for hook in (".digest-pill-covered", ".digest-pill-not-covered-yet", ".digest-pill-cant-cover",
                 ".digest-count-btn", ".digest-err", ".digest-msg", ".digest-pick", ".digest-req-form",
                 '[data-state="sent"]', '[data-state="counted"]', '[data-state="failed"]'):
        assert hook in rules, hook


def test_switch_on_changes_existing_pages_only_by_the_three_fragments(sites, page_labels):
    """7a: removing the Menu group (once per page) and the front-page line (once), and putting the Method page's
    off-build sentence back in place of its on-build one (once, design 9a), leaves every existing file equal;
    static/pages.js gains only the digest pages."""
    off, on = sites["off"], sites["on"]
    front = npg.front_fragment(page_labels)
    method = npg.method_fragment(page_labels)
    for rel, before in off.items():
        after = on[rel]
        if rel == "static/pages.js":
            listed = set(json.loads(after.decode()[len("window.BUILT_PAGES = "):-2]))
            assert listed - set(json.loads(before.decode()[len("window.BUILT_PAGES = "):-2])) == DIGEST_HTML - {
                "digest/geo-frame.html"}
            continue
        if not rel.endswith(".html") or after == before:
            assert after == before, rel
            continue
        text = after.decode()
        root = "../" * rel.count("/")
        menu = npg.menu_fragment(root, page_labels)
        assert text.count(menu) == 1, rel
        text = text.replace(menu, "", 1)
        if rel == "index.html":
            assert text.count(front) == 1
            text = text.replace(front, "", 1)
        if rel == "method.html":
            assert text.count(method) == 1 and npg.METHOD_SENTENCE not in text
            text = text.replace(method, npg.METHOD_SENTENCE, 1)
        assert text == before.decode(), rel
    changed = [r for r in off if r.endswith(".html") and on[r] != off[r]]
    assert "index.html" in changed and "about.html" in changed and "method.html" in changed


def test_method_page_names_the_digest_keys_and_links_how(sites, page_labels):
    """AC9.3, design 9a (QA national/method-page-claims): with the switch on the Method page no longer says its two
    keys are all the site keeps; it says the Clarksville pages keep two and the digest pages three more, linked to
    how.html, which lists those three keys by name."""
    on = sites["on"]["method.html"].decode()
    assert npg.METHOD_SENTENCE not in on
    assert ('These two keys are all the Clarksville pages keep in your browser. Daylight Digest pages keep three '
            'more, listed on <a href="digest/how.html">How Daylight Digest works</a>.') in on
    assert "digest/how.html" in sites["on"]
    how = sites["on"]["digest/how.html"].decode()
    for key in ("daylight.us.list", "daylight.us.requested", "daylight.us.counted"):
        assert key in how, key


def test_front_line_sits_right_after_the_address_card(sites, page_labels):
    html = sites["on"]["index.html"].decode()
    assert '</section>\n  <p class="digest-line"><a href="digest/index.html">' + page_labels["front.line"] in html


def test_fragment_insertion_fails_closed():
    labels = npg.load_page_labels()
    with pytest.raises(npg.NationalBuildError):
        npg.apply_site_fragments({"index.html": "<html>no card</html>"}, labels)
    page = '<nav id="site-nav" class="site-nav" aria-label="All pages" data-root="../">' + npg.MENU_ANCHOR * 2
    with pytest.raises(npg.NationalBuildError):
        npg.apply_site_fragments({"a/b.html": page}, labels)
    assert npg.apply_site_fragments({"x.html": "<p>no footer</p>"}, labels) == {"x.html": "<p>no footer</p>"}
    with pytest.raises(npg.NationalBuildError):
        npg.apply_site_fragments({"method.html": "<p>no sentence</p>"}, labels)
    with pytest.raises(npg.NationalBuildError):
        npg.apply_site_fragments({"method.html": npg.METHOD_SENTENCE * 2}, labels)
    with pytest.raises(npg.NationalBuildError):
        npg.menu_fragment("/", labels)


# --- CSP per file (section 6, 4.0) ---------------------------------------------------------------------------------

def _csp(html: str) -> str:
    m = re.findall(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', html)
    assert len(m) == 1
    return html_mod.unescape(m[0])


def test_csp_per_file(sites):
    on = {k: v.decode() for k, v in sites["on"].items() if k in DIGEST_HTML}
    site_csp = _csp(sites["on"]["about.html"].decode())
    index = _csp(on["digest/index.html"])
    origin = "https://buttondown.com"       # the shipped morning note's form (morning_page.form_origin)
    assert index == npg.index_csp(None, origin)
    assert "script-src 'self';" in index and "frame-src 'self'" in index
    assert f"form-action 'self' {origin}" in index and f"connect-src {origin}" in index
    for rel in ("digest/covered.html", "digest/requested.html", f"digest/tn/{COUNCIL_ID}.html",
                f"digest/tn/{COUNTY_ID}.html"):
        assert _csp(on[rel]) == site_csp, rel
    frame = on["digest/geo-frame.html"]
    assert frame == nat.geo_frame_html()
    for rel, html in on.items():
        assert (CENSUS in _csp(html)) == (rel == "digest/geo-frame.html"), rel


def test_index_csp_names_the_counter_only_while_on():
    gc = "https://daylight-gnosh.goatcounter.com"
    assert "connect-src https://buttondown.com " + gc in npg.index_csp(gc, "https://buttondown.com")
    assert "connect-src 'none'" in npg.index_csp(None, None)
    assert "form-action 'self';" in npg.index_csp(None, None)


# --- the pages ------------------------------------------------------------------------------------------------------

def test_scripts_only_on_the_entry_page(sites):
    on = {k: v.decode() for k, v in sites["on"].items() if k in DIGEST_HTML}
    for rel, html in on.items():
        if rel == "digest/geo-frame.html":
            continue
        has = "static/national.js" in html
        assert has == (rel == "digest/index.html"), rel
        assert 'id="body-switch"' not in html, rel            # 7a: no "Show records from" on digest pages
    assert "static/us-count.js" not in on["digest/index.html"]   # fixture build: analytics off


def test_header_variant_on_digest_pages(sites, page_labels):
    clark = sites["on"]["about.html"].decode()
    assert 'id="sky-moon"' in clark and 'class="sky-in"' in clark
    for rel in DIGEST_HTML - {"digest/geo-frame.html"}:
        html = sites["on"][rel].decode()
        assert f'<span class="plate-place">{page_labels["digest.place"]}</span>' in html, rel
        assert 'id="sky-moon"' not in html and 'class="sky-in"' not in html, rel


def test_report_an_error_on_fact_pages(sites):
    for rel in ("digest/index.html", "digest/covered.html", f"digest/tn/{COUNCIL_ID}.html",
                f"digest/tn/{COUNTY_ID}.html"):
        assert "Report an error on this page" in sites["on"][rel].decode(), rel


def test_entry_page_embeds_the_page_directory_and_strings(sites, loaded, page_labels):
    html = sites["on"]["digest/index.html"].decode()
    blobs = dict(re.findall(r'<script type="application/json" id="(digest-[a-z]+)">(.*?)</script>', html, re.S))
    assert set(blobs) == {"digest-pagedir", "digest-strings", "digest-config"}
    pagedir = json.loads(blobs["digest-pagedir"])
    assert pagedir["schema"] == nat.PAGEDIR_SCHEMA and pagedir["root"] == "../"
    assert set(pagedir["govs"]) == {g["gov"] for g in loaded[0].govs}
    assert pagedir["govs"][COUNTY_ID]["page"] == f"digest/tn/{COUNTY_ID}.html"
    assert json.loads(blobs["digest-strings"]) == {k: v for k, v in page_labels.items()
                                                   if k.startswith(npg.SCRIPT_GROUPS)}
    cfg = json.loads(blobs["digest-config"])
    assert cfg["frame"] == "geo-frame.html" and cfg["form_action"].startswith("https://buttondown.com/")
    # the two outside links (design section 3, "Outside links"): settings from config/national/links.yml
    assert cfg["election_url"] == "https://www.usa.gov/state-election-office"
    assert cfg["census_url"] == "https://geocoding.geo.census.gov/geocoder/"
    assert {k: cfg[k] for k in npg.LINK_KEYS} == npg.load_links()
    form = re.search(r'<form class="addr-form" id="digest-form" hidden>(.*?)</form>', html, re.S).group(1)
    assert " name=" not in form and "action=" not in form


def test_links_file_keys_are_optional_and_checked(tmp_path):
    """links.yml: a key left out is None (the script then leaves that line out whole); an unknown key, a value that
    is not a plain https URL, a wrong schema or a missing file stops the build."""
    path = tmp_path / "links.yml"

    def write(links, schema=npg.LINKS_SCHEMA, **extra):
        path.write_text(json.dumps({"schema": schema, "links": links, **extra}), encoding="utf-8")
        return path
    assert npg.load_links(write({})) == {"election_url": None, "census_url": None}
    assert npg.load_links(write({"census_url": "https://example.gov/x"})) == {
        "election_url": None, "census_url": "https://example.gov/x"}
    for bad in ({"election_url": "http://www.usa.gov/"}, {"election_url": "javascript:alert(1)"},
                {"census_url": "https://user:pw@example.gov/"}, {"census_url": "https://example.gov:8443/"},
                {"census_url": ""}, {"census_url": 3}, {"other_url": "https://example.gov/"}, ["x"]):
        with pytest.raises(npg.NationalBuildError):
            npg.load_links(write(bad))
    with pytest.raises(npg.NationalBuildError):
        npg.load_links(write({}, schema="daylight-links/2"))
    with pytest.raises(npg.NationalBuildError):
        npg.load_links(write({}, more=1))
    with pytest.raises(npg.NationalBuildError):
        npg.load_links(tmp_path / "absent.yml")


def test_no_links_given_means_null_settings(tmp_path, loaded, page_labels):
    """build_national without `links` (or with a bad value) writes both settings as null, never a bad href."""
    directory, flags, labels = loaded
    feeds = npg.build_feeds(directory, npg.council_inputs([], True), None, date(2026, 11, 19))
    for links in (None, {"election_url": "http://x.example/", "census_url": None}):
        out = tmp_path / str(bool(links))
        npg.build_national(out, build_mod.make_env(), _SITE_CTX(), directory, flags, labels, page_labels, feeds,
                           built_at=BUILT_AT, counter=None, links=links)
        html = (out / "digest" / "index.html").read_text(encoding="utf-8")
        cfg = json.loads(re.search(r'id="digest-config">(.*?)</script>', html, re.S).group(1))
        assert cfg["election_url"] is None and cfg["census_url"] is None


def test_feed_json_validates_with_no_extra_key(sites):
    for rel in DIGEST_JSON:
        feed = json.loads(sites["on"][rel])
        assert ncl.feed_errors(feed) == [], rel
        assert feed["body"]["id"] == Path(rel).stem


# --- every visible string is a label or source text (AC4.5, AC4.8) ---------------------------------------------------

BLOCKS = {"p", "h1", "h2", "h3", "h4", "li", "ul", "ol", "section", "div", "nav", "summary", "details", "label",
          "form", "button", "dt", "dd", "main", "table", "tr", "td", "th"}


class _Main(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth, self.skip, self.out = 0, 0, []

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.depth += 1
        if tag in ("script", "style"):
            self.skip += 1
        if tag in BLOCKS:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag == "main":
            self.depth -= 1
        if tag in ("script", "style"):
            self.skip -= 1
        if tag in BLOCKS:
            self.out.append("\n")

    def handle_data(self, data):
        if self.depth and not self.skip:
            self.out.append(data)


def main_text(html: str) -> str:
    p = _Main()
    p.feed(html)
    return "\n".join(" ".join(line.split()) for line in "".join(p.out).split("\n") if line.strip())


# Words base.html.j2 prints in every page's <main> (the shared frame, UX section 0), not digest labels.
FRAME_WORDS = ("Report an error on this page", "daylight.us.list", "daylight.us.requested", "daylight.us.counted")


def leftover(text: str, labels, sources) -> str:
    for s in sorted({s for s in sources if s}, key=len, reverse=True):
        text = text.replace(s, "\x00")         # a placeholder may stand where a source value was
    for lab in sorted(labels, key=len, reverse=True):
        plain = npg.LINK_RE.sub(lambda m: m.group(1), lab)
        pattern = re.sub(r"\\\{[a-z]+\\\}", ".{0,160}?", re.escape(plain))
        text = re.sub(pattern, "\n", text)
    return text.replace("\x00", "\n")


def _sources(directory, feeds) -> set[str]:
    out = {g["body_name"] for g in directory.govs} | {npg._host(g.get("official_url")) for g in directory.govs}
    for f in feeds:
        out.add(f["body"]["name"])
        for m in f["meetings"]:
            out |= {m["title"], npg.long_day(m["date"])}
            for it in m["items"]:
                out |= {it["text"], it["number"] or "", str((it.get("source") or {}).get("page") or "")}
    return out


def test_every_visible_string_is_a_label_or_source_text(sites, loaded, page_labels):
    directory, _flags, labels = loaded
    feeds = [json.loads(sites["on"][r]) for r in DIGEST_JSON]
    allowed = [*page_labels.values(), *labels.values(), *FRAME_WORDS]
    for rel in DIGEST_HTML - {"digest/geo-frame.html"}:
        rest = leftover(main_text(sites["on"][rel].decode()), allowed, _sources(directory, feeds))
        assert re.fullmatch(r"[\s.,·:/]*", rest), (rel, rest.strip()[:300])


def test_the_strings_check_catches_an_unlabelled_word(loaded, page_labels):
    text = main_text("<main><p>Coming up</p><p>Breaking news</p></main>")
    assert "Breaking news" in leftover(text, list(page_labels.values()), set())


# --- How Daylight Digest works ---------------------------------------------------------------------------------------

def test_how_page_exists_only_with_the_switch_on_and_lists_the_three_keys(sites):
    """T1: the Daylight Digest method text is its own page (the Clarksville Method page is untouched). It names the
    three storage keys, the counter event and the rough-location disclosure; the entry page and What we cover link it."""
    assert "digest/how.html" not in sites["off"] and "digest/how.html" not in sites["absent"]
    html = sites["on"]["digest/how.html"].decode()
    for key in ("daylight.us.list", "daylight.us.requested", "daylight.us.counted"):
        assert f"<code>{key}</code>" in html
    assert "IP address" in html and "show roughly where you are" in html        # the request paragraph: always
    assert "GoatCounter" not in html and "count-" not in html       # fixture build: no counter, so no counting text
    assert "Visits to Daylight Digest pages" not in html
    for rel in ("digest/index.html", "digest/covered.html"):
        assert 'href="how.html"' in sites["on"][rel].decode(), rel


def test_how_page_describes_the_counter_only_while_it_is_on(loaded, page_labels, tmp_path):
    """national/privacy-claims: the "Just count me" and page-visit paragraphs print exactly when `counter` is set."""
    directory, flags, labels = loaded
    feeds = ncl.clarksville_feeds(directory, {"city": ({}, [])}, _agendas("Item"), date(2026, 11, 19),
                                  checked_at=BUILT_AT)
    gc = "https://daylight-gnosh.goatcounter.com"
    text = {}
    for k, counter in (("off", None), ("on", {"origin": gc, "endpoint": gc + "/count"})):
        out = tmp_path / k
        npg.build_national(out, build_mod.make_env(), _SITE_CTX(), directory, flags, labels, page_labels, feeds,
                           built_at=BUILT_AT, counter=counter)
        text[k] = (out / npg.HOW).read_text(encoding="utf-8")
    assert "GoatCounter" not in text["off"] and "count-" not in text["off"]
    assert "Visits to Daylight Digest" not in text["off"] and "IP address" in text["off"]
    assert "GoatCounter" in text["on"] and "count-" in text["on"]
    assert "page address" in text["on"] and "screen size" in text["on"]


# --- labels and their links ---------------------------------------------------------------------------------------

def test_label_html_escapes_values_and_makes_one_link():
    out = npg.label_html("Checked {date}. [Source]", "https://e.gov/?a=1&b=<2>", ext=True, date="<b>x</b>")
    assert str(out) == ('Checked &lt;b&gt;x&lt;/b&gt;. <a href="https://e.gov/?a=1&amp;b=&lt;2&gt;" '
                        'rel="noopener noreferrer">Source</a>')
    assert str(npg.label_html("See [it]", None)) == "See it"
    assert npg.label_text("A [b] {n}", n=3) == "A b 3"
    with pytest.raises(npg.NationalBuildError):
        npg.label_text("{n} days")


def _labels_file(tmp_path, extra: str) -> Path:
    text = npg.PAGE_LABELS_PATH.read_text(encoding="utf-8") + extra
    p = tmp_path / "page-labels.yml"
    p.write_text(text, encoding="utf-8")
    return p


@pytest.mark.parametrize("extra", ["  Bad.key: x\n", "  body.two: '[a] and [b]'\n", "  body.ctl: \"a\\u202eb\"\n",
                                   "  body.empty: ' '\n", "  body.open: 'a [b'\n"])
def test_page_labels_refuse_bad_entries(tmp_path, extra):
    with pytest.raises(npg.NationalBuildError):
        npg.load_page_labels(_labels_file(tmp_path, extra))


def test_page_labels_refuse_a_missing_key(tmp_path):
    text = npg.PAGE_LABELS_PATH.read_text(encoding="utf-8").replace("  body.withheld:", "  body.unused:")
    p = tmp_path / "page-labels.yml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(npg.NationalBuildError, match="body.withheld"):
        npg.load_page_labels(p)


# --- staleness and the collection instant ----------------------------------------------------------------------------

def test_newest_record_is_the_newest_fetch_never_invented():
    srcs = [{"fetched_at": "2026-11-08"}, {"fetched_at": "2026-11-10"}, {"fetched_at": None}, "x"]
    assert npg.newest_record_at(srcs) == datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
    assert npg.newest_record_at([]) == npg.EPOCH
    assert npg.newest_day("2026-11-10T12:00:00Z") == "2026-11-10"
    assert npg.newest_day("1970-01-01T00:00:00Z") is None and npg.newest_day(None) is None


def test_feeds_claim_no_check_time(loaded):
    """national-freshness/checked-at-is-first-fetch: M1 records no check run, so every feed has last_ok_at null and
    checked_at the newest record's first fetch; the pagedir marks no daylight government stale; the page says
    "We got our newest record on" (or "no records yet"), never "Last checked" or a stale line."""
    directory, _f, _l = loaded
    feeds = npg.build_feeds(directory, {"city": ({}, [])}, _agendas("x"), date(2026, 11, 19))
    assert {f["last_ok_at"] for f in feeds.values()} == {None}
    assert feeds[COUNTY_ID]["checked_at"] == "2026-11-18T12:00:00Z"
    assert feeds[COUNCIL_ID]["checked_at"] == "1970-01-01T00:00:00Z"


def test_pages_say_newest_record_and_mark_nothing_stale(sites, page_labels):
    on = sites["on"]
    pagedir = json.loads(re.search(r'id="digest-pagedir">(.*?)</script>', on["digest/index.html"].decode(),
                                   re.S).group(1))
    assert pagedir["govs"][COUNCIL_ID]["stale"] is False and pagedir["govs"][COUNTY_ID]["stale"] is False
    council = main_text(on[f"digest/tn/{COUNCIL_ID}.html"].decode())       # a fixture build: no council records
    assert page_labels["body.no-records"] in council
    county = json.loads(on[f"digest/tn/{COUNTY_ID}.json"])
    text = main_text(on[f"digest/tn/{COUNTY_ID}.html"].decode())
    assert page_labels["body.newest"] == "We got our newest record on {date}."      # Q11 decision
    if county["checked_at"] != "1970-01-01T00:00:00Z":
        assert "We got our newest record on " in text
    for rel in DIGEST_HTML:
        assert "Last checked" not in on[rel].decode() and "couldn't check" not in on[rel].decode(), rel


# --- consumer 3 of section 11: items only from the JSON; withheld shows the fixed label ------------------------------

SENTINEL = "Approve the contract SENTINEL-ITEM-TEXT"


def _agendas(*titles):
    return {"index_url": "https://montgomerytn.gov/commission/agenda",
            "sources": [{"id": "src-1", "url": "https://mcgtn.org/a.pdf", "pages": 3, "fetched_at": "2026-11-18"}],
            "meetings": [{"id": "2026-12-14-formal", "date": "2026-12-14", "kind": "formal", "source_id": "src-1",
                          "items": [{"number": f"26-12-{n}", "title": t, "page": 1}
                                    for n, t in enumerate(titles, 1)]}]}


def _entry(directory, gov_id, **changes):
    e = dict(directory.get(COUNTY_ID))
    e.update(gov=gov_id, also=[], review=None, **changes)
    return e


def test_shown_county_prints_its_items_from_the_json(tmp_path, loaded, page_labels, monkeypatch):
    directory, flags, labels = loaded
    feeds = ncl.clarksville_feeds(directory, {"city": ({}, [])}, _agendas(SENTINEL, "Second item"),
                                  date(2026, 11, 19), checked_at=BUILT_AT)
    feeds[COUNTY_ID]["meetings"][0]["items"][1]["text"] = "Edited in the JSON only"
    html = _render_one(tmp_path, directory, flags, labels, page_labels, feeds, COUNTY_ID)
    assert SENTINEL in html and "Edited in the JSON only" in html and "Second item" not in html


def _render_one(tmp_path, directory, flags, labels, page_labels, feeds, gov_id):
    out = tmp_path / "site"
    _build_pages_into(out, directory, flags, labels, page_labels, feeds)
    st = directory.get(gov_id)["state"].lower()
    return (out / "digest" / st / f"{gov_id}.html").read_text(encoding="utf-8")


def _build_pages_into(out, directory, flags, labels, page_labels, feeds):
    env = build_mod.make_env()
    npg.build_national(out, env, _SITE_CTX(), directory, flags, labels, page_labels, feeds, built_at=BUILT_AT,
                       counter=None)


def _SITE_CTX():  # noqa: N802
    """A site context from the fixture facts, as build() makes it (views.site_context)."""
    from sitegen import views
    facts = build_mod.load_facts(FIXTURE)
    ix = views.Index(facts, [])
    site = views.site_context(ix)
    site.update(internal=False, analytics=None, morning_note=None, data_as_of="2026-11-18")
    return site


@pytest.mark.parametrize("gov_id,name", [("place-4799999", "Clarksville Youth Council"),
                                          ("sdu-4799999", "Example County School Board")])
def test_withheld_government_prints_the_label_and_no_item_text(tmp_path, loaded, page_labels, gov_id, name):
    directory, flags, labels = loaded
    withheld = _entry(directory, gov_id, body_name=name, items="withheld")
    d = nat.Directory(govs=(*directory.govs, withheld), alias={})
    feeds = ncl.clarksville_feeds(d, {"city": ({}, [])}, _agendas(SENTINEL), date(2026, 11, 19),
                                  checked_at=BUILT_AT)
    assert feeds[gov_id]["meetings"][0]["items_withheld"] is True
    html = _render_one(tmp_path, d, flags, labels, page_labels, feeds, gov_id)
    assert SENTINEL not in html
    assert npg.label_text(page_labels["body.withheld"]) in " ".join(main_text(html).split())
    assert npg.label_text(page_labels["body.withheld"]) not in _render_one(
        tmp_path / "c", d, flags, labels, page_labels, feeds, COUNTY_ID)


def test_page_prints_no_items_the_json_marks_withheld_or_not_final(loaded, page_labels):
    body = {"gov": COUNTY_ID, "official_url": "https://montgomerytn.gov/commission/agenda", "platform": "daylight"}
    m = {"id": "2026-12-14-formal", "date": "2026-12-14", "time": None, "title": "Formal", "title_ours": True,
         "agenda": {"state": "final", "url": None, "status_as_posted": None}, "may_be_incomplete": False,
         "items_withheld": True, "item_count": None,
         "items": [{"seq": 1, "number": None, "text": SENTINEL, "source": {"url": None, "page": None}}]}
    assert npg.meeting_view(m, body, "America/Chicago", page_labels)["entries"] == []
    assert npg.meeting_view(m, body, "America/Chicago", page_labels)["withheld"] is True
    m2 = dict(m, items_withheld=False, agenda=dict(m["agenda"], state="not-final"))
    assert npg.meeting_view(m2, body, "America/Chicago", page_labels)["entries"] == []
    m3 = dict(m, items_withheld=False)
    v = npg.meeting_view(m3, body, "America/Chicago", page_labels)
    assert [e["text"] for e in v["entries"]] == [SENTINEL] and v["agenda_url"] == body["official_url"]


def test_links_come_from_the_entry_and_are_rechecked(loaded, page_labels):
    """national-pages/body-from-feed-not-directory: a meeting link is kept only on the entry's platform hosts, else
    the entry's official link; with no usable link at all the words print with no link (never href="")."""
    m = {"id": "2026-12-14-formal", "date": "2026-12-14", "time": None, "title": "Formal", "title_ours": True,
         "agenda": {"state": "final", "url": "https://evil.example/a.pdf", "status_as_posted": None},
         "may_be_incomplete": False, "items_withheld": False, "item_count": 1,
         "items": [{"seq": 1, "number": None, "text": "t", "source": {"url": "https://evil.example/a.pdf#page=1",
                                                                      "page": 1}}]}
    legistar = {"gov": "place-4799999", "platform": "legistar", "legistar": {"client": "salem"},
                "official_url": "https://salem.legistar.com/Calendar.aspx"}
    v = npg.meeting_view(m, legistar, "America/Chicago", page_labels)
    assert v["agenda_url"] == legistar["official_url"] and v["entries"][0]["url"] == legistar["official_url"]
    bad = dict(legistar, official_url="https://evil.example/")
    assert npg.official_of(bad) is None
    v = npg.meeting_view(m, bad, "America/Chicago", page_labels)
    assert v["agenda_url"] is None and v["entries"][0]["url"] is None
    assert str(npg.label_html("[Official agenda]", v["agenda_url"])) == "Official agenda"
    assert str(npg.label_html("[Official agenda]", "")) == "Official agenda"


def test_morning_note_and_full_pages_only_on_clarksville_bodies(tmp_path, loaded, page_labels):
    """national-pages/morning-gate: "Get the morning note" and the full Daylight link are per entry (daylight only)."""
    directory, flags, labels = loaded
    feeds = ncl.clarksville_feeds(directory, {"city": ({}, [])}, _agendas("x"), date(2026, 11, 19),
                                  checked_at=BUILT_AT)
    site = _SITE_CTX()
    site["morning_note"] = {"signup_href": "alerts.html#note"}
    out = tmp_path / "site"
    npg.build_national(out, build_mod.make_env(), site, directory, flags, labels, page_labels, feeds,
                       built_at=BUILT_AT, counter=None)
    html = (out / "digest" / "tn" / f"{COUNTY_ID}.html").read_text(encoding="utf-8")
    assert 'href="../../alerts.html#note"' in html and 'href="../../meetings/agendas.html"' in html
    # a covered Legistar government (M2's shape) in the same build: neither link
    other = {"gov": "place-4799999", "also": [], "body_name": "Example City Council", "state": "TN",
             "status": "covered", "official_url": "https://example.legistar.com/Calendar.aspx",
             "checked": date(2026, 11, 19), "items": "withheld", "review": None, "platform": "legistar",
             "legistar": {"client": "example", "body_id": 1, "tz": "America/Chicago"},
             "host_ok": {"date": date(2026, 11, 19), "link": "https://example.org/ok"}}
    feed = json.loads(json.dumps(feeds[COUNTY_ID]))
    feed["body"].update(id=other["gov"], platform="legistar", full_url=None)
    d = nat.Directory(govs=(*directory.govs, other), alias={})
    out2 = tmp_path / "site2"
    npg.build_national(out2, build_mod.make_env(), site, d, flags, labels, page_labels,
                       {**feeds, other["gov"]: feed}, built_at=BUILT_AT, counter=None)
    html = (out2 / "digest" / "tn" / f"{other['gov']}.html").read_text(encoding="utf-8")
    assert "alerts.html#note" not in html.split("<main", 1)[1].split("</main>")[0]
    assert "meetings/agendas.html" not in html and 'href=""' not in html


# --- real data ------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real():
    cfg = ncl.council_cfg("city")
    if cfg is None or not cfg["facts_path"].is_file() or not config.COUNTY_AGENDAS.is_file():
        why = "the Clarksville data is not in this checkout; set CR_ALLOW_NO_DATA=1 to skip locally"
        if os.environ.get("CR_ALLOW_NO_DATA") == "1" and not os.environ.get("CI"):
            pytest.skip(why)
        pytest.fail(why)
    agendas = county_agendas.load(config.COUNTY_AGENDAS)
    paged = {s["id"] for s in agendas["sources"] if s.get("pages")}
    today = min(date.fromisoformat(m["date"]) for m in agendas["meetings"] if m["source_id"] in paged)
    councils = {"city": (build_mod.load_facts(cfg["facts_path"]), ncl.load_listing(cfg))}
    return {"councils": councils, "agendas": agendas, "today": today}


def test_real_coming_up_pages_print_exactly_the_json_items(tmp_path, loaded, page_labels, real):
    directory, flags, labels = loaded
    feeds = npg.build_feeds(directory, real["councils"], real["agendas"], real["today"])
    assert set(feeds) == {COUNCIL_ID, COUNTY_ID}
    assert feeds[COUNTY_ID]["checked_at"] == npg.newest_record_at(real["agendas"]["sources"]).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    out = tmp_path / "site"
    _build_pages_into(out, directory, flags, labels, page_labels, feeds)
    for gid, feed in feeds.items():
        html = (out / "digest" / "tn" / f"{gid}.html").read_text(encoding="utf-8")
        printed = [main_text("<main>" + h + "</main>") for h in re.findall(r"<h3>(.*?)</h3>", html, re.S)]
        want = [" ".join(f"{it['number'] or ''} {it['text']}".split())
                for m in feed["meetings"] for it in m["items"]]
        assert printed == want, gid
        rest = leftover(main_text(html), [*page_labels.values(), *labels.values(), *FRAME_WORDS],
                        _sources(directory, [feed]))
        assert re.fullmatch(r"[\s.,·:/]*", rest), (gid, rest.strip()[:300])
    assert any(m["items"] for m in feeds[COUNTY_ID]["meetings"])          # the county page has items to check
    assert not any(m["items"] for m in feeds[COUNCIL_ID]["meetings"])     # the council's are not stored (7)


def test_a_covered_entry_without_a_feed_stops_the_build(loaded):
    directory, _f, _l = loaded
    with pytest.raises(npg.NationalBuildError):
        npg.build_feeds(nat.Directory(govs=tuple(g for g in directory.govs if g["gov"] != COUNTY_ID)
                                      + (dict(directory.get(COUNTY_ID), platform="legistar"),), alias={}),
                        {"city": ({}, [])}, None, date(2026, 11, 19))


@pytest.mark.parametrize("moved,slot", [(True, "CITY OR TOWN"), (False, "TOWNSHIP OR TOWN")])
def test_page_slot_follows_the_gov_flags_slot_rule(tmp_path, loaded, page_labels, moved, slot):
    """national/new-england-town-slot (AC2.11): the coming-up page's eyebrow and its What we cover row print the slot
    nat.slot_of gives (a gov-flags `slots` rule for the id's state moves a cousub to the city-or-town slot)."""
    import dataclasses
    directory, flags, labels = loaded
    feeds = ncl.clarksville_feeds(directory, {"city": ({}, [])}, _agendas("x"), date(2026, 11, 19),
                                  checked_at=BUILT_AT)
    town = {"gov": "cousub-4712590887", "also": [], "body_name": "Example Town Board", "state": "TN",
            "status": "covered", "official_url": "https://example.legistar.com/Calendar.aspx",
            "checked": date(2026, 11, 19), "items": "withheld", "review": None, "platform": "legistar",
            "legistar": {"client": "example", "body_id": 1, "tz": "America/Chicago"},
            "host_ok": {"date": date(2026, 11, 19), "link": "https://example.org/ok"}}
    feed = json.loads(json.dumps(feeds[COUNTY_ID]))
    feed["body"].update(id=town["gov"], name=town["body_name"], platform="legistar", full_url=None)
    rule = ({"state": "47", "layer": "cousub", "slot": "place"},) if moved else ()
    f2 = dataclasses.replace(flags, slots=rule)
    d = nat.Directory(govs=(*directory.govs, town), alias={})
    out = tmp_path / "site"
    npg.build_national(out, build_mod.make_env(), _SITE_CTX(), d, f2, labels, page_labels,
                       {**feeds, town["gov"]: feed}, built_at=BUILT_AT, counter=None)
    body = main_text((out / "digest" / "tn" / f"{town['gov']}.html").read_text(encoding="utf-8"))
    assert f"Tennessee · {slot}" in body
    covered = main_text((out / "digest" / "covered.html").read_text(encoding="utf-8"))
    row = covered[covered.index("Example Town Board"):][:200]
    assert slot in row and ("TOWNSHIP OR TOWN" in row) is not moved


# --- topic labels (AC4.7, AC4.8): the morning note's lists by the published item type word list ----------------------

ITEM_LI_RE = re.compile(r"<li>\s*<h3>(.*?)</h3>\s*(?:<p class=\"digest-topics\">(.*?)</p>)?", re.S)
CHIP_RE = re.compile(r'<span class="chip digest-topic"><span class="sr-only">[^<]*</span>([^<]*)</span>')


def _printed_topics(html: str) -> list[tuple[str, list[str]]]:
    """(item heading text, [topic label text]) for each item on a coming-up page, in page order."""
    return [(main_text("<main>" + h + "</main>"), [html_mod.unescape(c) for c in CHIP_RE.findall(chips or "")])
            for h, chips in ITEM_LI_RE.findall(html)]


def _word_list_topics(number: str | None, text: str, page_labels) -> list[str]:
    """The expected labels, read straight from config/site.yml item_types (independent of views.item_types): a
    number prefix, or a word at the start of a word of the text, any case."""
    types = {t["key"]: t for t in config.SITE["item_types"]}
    out = []
    for key, item_type in npg.TOPICS:
        t = types[item_type]
        if any((number or "").upper().startswith(p.upper()) for p in t["prefixes"]) or \
                any(re.search(r"(?<!\w)" + re.escape(w.casefold()), text.casefold()) for w in t["words"]):
            out.append(page_labels[f"body.topic-{key}"])
    return out


def test_topics_are_the_morning_note_lists_with_a_word_rule(page_labels):
    from sitegen import morning
    types = {t["key"]: t for t in config.SITE["item_types"]}
    item_types = set(types)
    assert [k for k, _ in npg.TOPICS] == ["zoning", "budget"]
    for key, item_type in npg.TOPICS:
        assert key in morning.LIST_KEYS and item_type in item_types
        # the chip is the About page's name for the item type it links to (about.html#item-types), word for word
        assert page_labels[f"body.topic-{key}"] == types[item_type]["label"]
    assert (page_labels["body.topic-zoning"], page_labels["body.topic-budget"]) == ("Rezoning", "Budget and finance")
    assert npg.item_topics(None, "Rezone 5 acres on Main St") == ["body.topic-zoning"]
    assert npg.item_topics("CZ-12-2026", "Application of A. Owner") == ["body.topic-zoning"]
    assert npg.item_topics(None, "FY27 Budget amendment") == ["body.topic-budget"]
    assert npg.item_topics(None, "A resolution appropriating funds") == ["body.topic-budget"]
    assert npg.item_topics(None, "Budget for a rezoning study") == ["body.topic-zoning", "body.topic-budget"]
    assert npg.item_topics(None, "Appoint a member") == []            # appointments are not a morning note list
    assert npg.item_topics(None, "Disbudgeted and prezoned") == []    # a word must start a word
    assert npg.item_topics(None, SENTINEL) == []


def test_topic_labels_follow_shown_items_and_never_a_withheld_meeting(tmp_path, loaded, page_labels):
    directory, flags, labels = loaded
    withheld = _entry(directory, "place-4799999", body_name="Clarksville Youth Council", items="withheld")
    d = nat.Directory(govs=(*directory.govs, withheld), alias={})
    titles = ("Resolution amending the FY27 budget", "Rezoning request for 5 acres", "Approve the minutes")
    feeds = ncl.clarksville_feeds(d, {"city": ({}, [])}, _agendas(*titles), date(2026, 11, 19), checked_at=BUILT_AT)
    out = tmp_path / "site"
    _build_pages_into(out, d, flags, labels, page_labels, feeds)
    html = (out / "digest" / "tn" / f"{COUNTY_ID}.html").read_text(encoding="utf-8")
    assert [t for _h, t in _printed_topics(html)] == [["Budget and finance"], ["Rezoning"], []]
    assert html.count('class="digest-topic-note"') == 1
    assert 'href="../../about.html#item-types"' in html
    assert '<span class="sr-only">Topic: </span>Rezoning' in html       # accessible name "Topic: ..."
    rest = leftover(main_text(html), [*page_labels.values(), *labels.values(), *FRAME_WORDS],
                    _sources(d, [feeds[COUNTY_ID]]))
    assert re.fullmatch(r"[\s.,·:/]*", rest), rest.strip()[:300]
    other = (out / "digest" / "tn" / "place-4799999.html").read_text(encoding="utf-8")
    assert "digest-topic" not in other and "Budget and finance" not in other
    # a page with no matching item prints no note
    feeds2 = ncl.clarksville_feeds(directory, {"city": ({}, [])}, _agendas("Approve the minutes"), date(2026, 11, 19),
                                   checked_at=BUILT_AT)
    html2 = _render_one(tmp_path / "n", directory, flags, labels, page_labels, feeds2, COUNTY_ID)
    assert "digest-topic" not in html2


def test_real_county_page_20_sampled_items_match_the_word_list(tmp_path, loaded, page_labels, real):
    """AC3.3 / AC4.7 QA sample: 20 items spread over the real county page, each item's printed labels equal the
    labels the word list gives its verbatim number and text, and at least one sampled or printed item has a label."""
    directory, flags, labels = loaded
    feeds = npg.build_feeds(directory, real["councils"], real["agendas"], real["today"])
    out = tmp_path / "site"
    _build_pages_into(out, directory, flags, labels, page_labels, feeds)
    html = (out / "digest" / "tn" / f"{COUNTY_ID}.html").read_text(encoding="utf-8")
    items = [it for m in feeds[COUNTY_ID]["meetings"] for it in m["items"]]
    printed = _printed_topics(html)
    assert len(printed) == len(items) >= 20
    step = len(items) / 20
    for i in sorted({int(n * step) for n in range(20)}):
        it, (heading, chips) = items[i], printed[i]
        assert heading == " ".join(f"{it['number'] or ''} {it['text']}".split())
        assert chips == _word_list_topics(it["number"], it["text"], page_labels), heading
    assert any(chips for _h, chips in printed)
    assert html.count('class="digest-topic-note"') == 1


# --- 11.3 item 7: the builder sweep ------------------------------------------------------------------------------------

def _sweep(out: Path) -> set[str]:
    return {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()
            and SENTINEL in p.read_text(encoding="utf-8")}


def test_builder_sweep_sentinel_only_in_the_bound_shown_government(tmp_path, loaded, page_labels):
    """privacy-withhold/national-prefix 11.3 item 7: from fixtures holding SENTINEL-ITEM-TEXT in every source, the text
    reaches only the shown county's .json and .html. A withheld "Youth Council" under a place id and a school district
    get the county's own items handed to them as copied M2 files (the shown review stamped on): bind_feed strips them.
    The page's items equal its JSON's."""
    directory, flags, labels = loaded
    youth = _entry(directory, "place-4799999", body_name="Clarksville Youth Council", items="withheld")
    school = _entry(directory, "sdu-4799999", body_name="Example County School Board", items="withheld")
    d = nat.Directory(govs=(*directory.govs, youth, school), alias={})
    agendas = _agendas(SENTINEL)
    facts = {"meetings": [{"id": "2026-12-03-regular", "date": "2026-12-03", "kind": "regular",
                           "title": SENTINEL}], "sources": []}
    feeds = ncl.clarksville_feeds(directory, {"city": (facts, [])}, agendas, date(2026, 11, 19), checked_at=BUILT_AT)
    county = feeds[COUNTY_ID]
    assert county["review"] and any(SENTINEL in it["text"] for m in county["meetings"] for it in m["items"])
    for e in (youth, school):                       # a copied M2 file for a withheld entry, carrying items
        copied = json.loads(json.dumps(county))
        copied["body"].update(id=e["gov"], name=e["body_name"])
        feeds[e["gov"]] = copied
    out = tmp_path / "site"
    binds = {}
    npg.build_national(out, build_mod.make_env(), _SITE_CTX(), d, flags, labels, page_labels, feeds,
                       built_at=BUILT_AT, counter=None, bind_counts=binds)
    assert _sweep(out) == {f"digest/tn/{COUNTY_ID}.json", f"digest/tn/{COUNTY_ID}.html"}
    assert binds["place-4799999"].withheld_stripped == 1 and binds["sdu-4799999"].withheld_stripped == 1
    for e in (youth, school):
        written = json.loads((out / "digest" / "tn" / f"{e['gov']}.json").read_text(encoding="utf-8"))
        assert written["review"] is None and all(m["items"] == [] and m["items_withheld"] for m in
                                                 written["meetings"])
    html = (out / "digest" / "tn" / f"{COUNTY_ID}.html").read_text(encoding="utf-8")
    printed = [main_text("<main>" + h + "</main>") for h in re.findall(r"<h3>(.*?)</h3>", html, re.S)]
    data = json.loads((out / "digest" / "tn" / f"{COUNTY_ID}.json").read_text(encoding="utf-8"))
    assert printed == [" ".join(f"{it['number'] or ''} {it['text']}".split())
                       for m in data["meetings"] for it in m["items"]]


def test_builder_sweep_a_stale_review_publishes_no_item(tmp_path, loaded, page_labels):
    """A copied M2 file for the shown county read under another review: stripped, counted, no sentinel anywhere."""
    directory, flags, labels = loaded
    feeds = ncl.clarksville_feeds(directory, {"city": ({}, [])}, _agendas(SENTINEL), date(2026, 11, 19),
                                  checked_at=BUILT_AT)
    feeds[COUNTY_ID]["review"] = "0" * 64
    out = tmp_path / "site"
    binds = {}
    npg.build_national(out, build_mod.make_env(), _SITE_CTX(), directory, flags, labels, page_labels, feeds,
                       built_at=BUILT_AT, counter=None, bind_counts=binds)
    assert _sweep(out) == set()
    assert binds[COUNTY_ID].review_mismatch == 1


def test_a_feed_for_another_body_stops_the_build(tmp_path, loaded, page_labels):
    directory, flags, labels = loaded
    feeds = ncl.clarksville_feeds(directory, {"city": ({}, [])}, _agendas(SENTINEL), date(2026, 11, 19),
                                  checked_at=BUILT_AT)
    feeds[COUNCIL_ID] = feeds[COUNTY_ID]
    with pytest.raises(npg.NationalBuildError):
        npg.build_national(tmp_path, build_mod.make_env(), _SITE_CTX(), directory, flags, labels, page_labels,
                           feeds, built_at=BUILT_AT, counter=None)


def test_only_sitegen_national_reads_the_directory_file():
    """11.3 item 10, for this module: the page builder reads the directory only through sitegen.national."""
    src = (ROOT / "sitegen" / "national_pages.py").read_text(encoding="utf-8")
    assert "directory.yml" not in src and "DIRECTORY_PATH" not in src


def test_covered_page_cmcss_official_label_names_the_county_site(sites):
    # national/official-link-label-wrong-site: the entry's own `official_label`, else the generic page label
    page = sites["on"]["digest/covered.html"].decode()
    row = page[page.index("Clarksville-Montgomery County School System Board of Education"):]
    row = row[:row.index("</li>")]
    assert "Official agenda page (opens the county&#39;s site, which posts the school board&#39;s agendas)" in row
    assert "opens the government&#39;s own site" not in row
