"""Who runs this, Our rules, Corrections, Method (neutrality pages) and the "Unofficial copy. Official record:" line."""
import json
import re

import pytest

from conftest import parse
from sitegen import config, views
from test_council_pages import cfg, city_facts, city_wards, site, cpages  # noqa: F401  (fixtures)
from test_fin_pages import build_with, fpages  # noqa: F401  (fixtures)

NEW = {"who-runs-this.html": "Who runs this", "our-rules.html": "Our rules", "corrections.html": "Corrections",
       "method.html": "Method"}
LINE = "Unofficial copy. Official record:"


def record_line(html):
    m = re.search(r'<p class="official-record">(.*?)</p>', html, re.S)
    return m and re.sub(r"<[^>]+>", "", m.group(1))


def test_each_new_page_exists_and_is_in_the_footer_list_and_drawer_source(pages):
    for rel, label in NEW.items():
        assert rel in pages, rel
        for name, html in pages.items():
            nav = re.search(r'<nav id="site-nav".*?</nav>', html, re.S).group(0)   # the footer list the drawer is built from
            assert f'href="{"../" * name.count("/")}{rel}"' in nav and f">{label}" in nav, (name, rel)


def test_who_runs_this_has_no_personal_name_and_names_the_operator(pages):
    html = pages["who-runs-this.html"]
    text = re.sub(r"<[^>]+>", " ", html)
    assert "Brian" not in text and "Zacharias" not in text
    assert 'href="https://gnoshcodes.com/"' in html and "No one pays for what this site covers; tips do not buy anything." in html
    assert "not an official government site" in text


def test_rules_page_has_the_eight_rules(pages):
    li = re.findall(r"<li><strong>", re.search(r'<ol class="rules">.*?</ol>', pages["our-rules.html"], re.S).group(0))
    assert len(li) == 8
    assert "12 months" in pages["our-rules.html"] and "100 or more residents" in pages["our-rules.html"]


def test_corrections_log_empty_and_filled(tmp_path, pages):
    assert "No corrections yet." in pages["corrections.html"] and 'href="report.html"' in pages["corrections.html"]
    p = tmp_path / "log.json"
    p.write_text(json.dumps([{"date": "2026-11-10", "page": "meetings/x.html", "was": "A", "now": "B",
                              "source_url": "https://example.org/doc.pdf"}]), encoding="utf-8")
    assert views.corrections_log(p)[0]["now"] == "B"
    p.write_text(json.dumps([{"date": "2026-11-10", "page": "x"}]), encoding="utf-8")
    with pytest.raises(ValueError):
        views.corrections_log(p)
    assert views.corrections_log(tmp_path / "none.json") == []


def test_official_record_line_on_each_county_record_page_type(pages):
    kinds = {"meetings/": 0, "votes/": 0, "items/": 0, "officials/": 0, "districts/": 0}
    for name, html in pages.items():
        for k in kinds:
            if name.startswith(k) and name != "votes/index.html":
                kinds[k] += 1
                assert record_line(html) and record_line(html).startswith(LINE), name
    assert all(kinds.values()), kinds
    # a meeting page links its own minutes PDF, the others the clerk's listing
    meeting = next(h for n, h in pages.items() if n.startswith("meetings/"))
    assert re.search(r'Official record: <a href="https?://[^"]+\.pdf|Official record: <a href="https?://', meeting)
    votes = next(h for n, h in pages.items() if n.startswith("votes/20"))
    assert config.SITE["official_records"]["county"]["url"] in votes


def test_official_record_line_on_finance_and_contract_pages(fpages):
    for name, html in fpages.items():
        if name.startswith(("finance/", "capital/", "contracts/")):
            assert record_line(html) and record_line(html).startswith(LINE), name
    assert config.SITE["official_records"]["contracts"]["url"] in fpages["contracts/index.html"]


def test_official_record_line_on_council_pages_names_the_councils_own_record(cpages):
    url = config.load_council("clarksville-tn")["record_url"]
    seen = 0
    for name, html in cpages.items():
        if name.startswith("city/") and "data-fact-id" in html or name == "city/index.html":
            seen += 1
            assert record_line(html) and record_line(html).startswith(LINE), name
            assert url in html, name
    assert seen


def test_non_record_pages_have_no_record_line(pages):
    for name in ("about.html", "search.html", "report.html", "who-runs-this.html", "index.html"):
        assert "Unofficial copy." not in pages[name], name


# ---------------------------------------------------------------- review fixes (record line, log, method, license)

from urllib.parse import urlsplit  # noqa: E402

from collector import fetch  # noqa: E402
from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, ROOT  # noqa: E402
from qa import site_checks  # noqa: E402
from sitegen.build import build  # noqa: E402
from test_transcripts import MEETING, city_dir  # noqa: E402,F401  (fixture)
from test_transcripts import CFG as TX_CFG  # noqa: E402

GOOD = {"url": "https://example.gov/record", "label": "Record"}


@pytest.mark.parametrize("url", [None, "", "   ", "http://example.gov/x.pdf", "https://", "https:///x", "ftp://a.gov/x",
                                 "/relative.pdf", 5, " https://example.gov/x"])
def test_official_record_needs_a_real_https_url(url):
    for tpl, ctx in (("meeting.html.j2", {"doc": {"url": url, "kind": "minutes"}}),
                     ("votes_year.html.j2", {})):
        site = {"record": {"url": url, "label": "x"}}
        assert views.official_record(tpl, site, ctx) is None, (tpl, url)
    # a missing key, and a missing doc, never raise
    assert views.official_record("meeting.html.j2", {}, {}) is None
    assert views.official_record("meeting.html.j2", {}, {"doc": {"kind": "minutes"}}) is None
    assert views.official_record("votes_year.html.j2", {}, {}) is None
    assert views.official_record("votes_year.html.j2", {"record": GOOD}, {}) == GOOD
    assert views.official_record("about.html.j2", {"record": GOOD}, {}) is None


def test_transcript_record_prefers_the_minutes_pdf_then_the_council_record():
    site = {"record": GOOD}
    pdf = views.official_record("transcript.html.j2", site, {"doc": {"url": "https://example.gov/m.pdf", "kind": "minutes"}})
    assert pdf == {"url": "https://example.gov/m.pdf", "label": "minutes PDF", "ext": False}
    assert views.official_record("transcript.html.j2", site, {"doc": None}) == GOOD
    assert views.official_record("transcript.html.j2", site, {}) == GOOD


@pytest.fixture(scope="module")
def tx_site(tmp_path_factory, city_dir):
    d, sub = city_dir
    cfg = {**TX_CFG, "facts_path": d / "facts.json", "wards_path": d / "wards.json"}
    out = tmp_path_factory.mktemp("txsite") / "build" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, councils=[cfg])
    return out, sub


def test_transcript_pages_carry_the_record_line_linking_the_meetings_minutes(tx_site):
    out, sub = tx_site
    pages = sorted((out / "city" / "transcripts").glob("*.html"))
    assert pages
    m = next(x for x in sub["meetings"] if x["id"] == MEETING)
    pdf = next(s["url"] for s in sub["sources"] if s["id"] == m["source_id"])
    for p in pages:
        html = p.read_text(encoding="utf-8")
        assert (record_line(html) or "").startswith(LINE), p.name
        assert f'Official record: <a href="{pdf}"' in html


def test_every_rendered_record_line_links_a_non_empty_https_url(pages, fpages, cpages, tx_site):
    seen = 0
    out, _ = tx_site
    tx = {p.relative_to(out).as_posix(): p.read_text(encoding="utf-8") for p in out.rglob("*.html")}
    for group in (pages, fpages, cpages, tx):
        for name, html in group.items():
            for m in re.finditer(r'<p class="official-record">(.*?)</p>', html, re.S):
                seen += 1
                href = re.search(r'<a [^>]*href="([^"]*)"', m.group(1)).group(1)
                sp = urlsplit(href)
                assert sp.scheme == "https" and sp.hostname, (name, href)
    assert seen > 50


def test_footer_operator_is_gnoshcodes_on_every_page(pages):
    for name, html in pages.items():
        m = re.search(r"Provided as a free service by (.*?)\.(?: <a|</p>)", html, re.S)
        assert m and re.sub(r"<[^>]+>", "", m.group(1)) == "gnoshcodes", name


def test_method_page_quotes_the_collectors_own_user_agent(pages):
    assert views.USER_AGENT is fetch.USER_AGENT
    assert f"<code>{fetch.USER_AGENT}</code>" in pages["method.html"]


def test_method_held_back_sentence_follows_the_unconfirmed_values_setting(tmp_path, monkeypatch, pages):
    assert config.SHOW_UNCONFIRMED_VALUES is False and "but with no value" in pages["method.html"]
    monkeypatch.setattr(config, "SHOW_UNCONFIRMED_VALUES", True)
    shown = build_with(tmp_path)["method.html"]
    assert "with no value" not in shown and "counted apart from the confirmed ones" in shown


def test_rules_page_payer_rule_is_true_today(pages):
    text = re.sub(r"<[^>]+>", " ", pages["our-rules.html"])
    assert "Before any payer agreement, we check for conflicts and publish the result." in text
    assert "Conflicts are checked before an agreement is signed" not in text
    assert "fixed within 2 business days" in pages["corrections.html"] or \
        "within 2 business days" in pages["corrections.html"]


BAD_ROWS = [
    {"date": "11/10/2026"}, {"date": "2026-13-45"}, {"date": "2026-1-5"}, {"date": 20261110},
    {"source_url": "http://example.org/doc.pdf"}, {"source_url": "https://"}, {"source_url": "https:///doc"},
    {"extra": "field"}, {"was": 5}, {"was": " "},
]


@pytest.mark.parametrize("change", BAD_ROWS)
def test_corrections_log_rejects_bad_rows(tmp_path, change):
    row = {"date": "2026-11-10", "page": "meetings/x.html", "was": "A", "now": "B", "source_url": "https://example.org/d.pdf",
           **change}
    p = tmp_path / "log.json"
    p.write_text(json.dumps([row]), encoding="utf-8")
    with pytest.raises(ValueError):
        views.corrections_log(p)
    p.write_text(json.dumps(["not an object"]), encoding="utf-8")
    with pytest.raises(ValueError):
        views.corrections_log(p)


def test_a_real_log_row_builds_and_passes_the_link_check(tmp_path, monkeypatch):
    log = tmp_path / "corrections-log.json"
    url = "https://www.montgomerytn.gov/example/corrected-minutes.pdf"
    log.write_text(json.dumps([{"date": "2026-11-10", "page": "meetings/x.html", "was": "A", "now": "B",
                                "source_url": url}]), encoding="utf-8")
    monkeypatch.setattr(views, "CORRECTIONS_LOG", log)
    out = tmp_path / "build" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS)
    html = (out / "corrections.html").read_text(encoding="utf-8")
    assert f'<a data-ext="corrections" href="{url}"' in html
    facts = json.loads(FIXTURE.read_text(encoding="utf-8"))
    corr_page = {"corrections.html": site_checks.parse(out / "corrections.html")}
    allowed = site_checks.allowed_external(config.SITE, None, None, corrections_path=log)
    problems, _ = site_checks.check_sources(out, corr_page, facts, None, allowed)
    assert problems == []
    assert site_checks.check_external(corr_page) == []
    # without the log's URLs in the allow-list the same page is flagged: the check is real
    bare, _ = site_checks.check_sources(out, corr_page, facts, None, site_checks.allowed_external(
        config.SITE, None, None, corrections_path=tmp_path / "none.json"))
    assert any(url in x for x in bare)


def test_meeting_page_minutes_pdf_host_is_still_validated_as_a_source(built):
    """The record line's minutes-PDF link has no data-ext, so it must be one of the facts' sources."""
    facts = json.loads(FIXTURE.read_text(encoding="utf-8"))
    name = "meetings/" + next(p.name for p in sorted((built / "meetings").glob("*.html")))
    pg = {name: site_checks.parse(built / name)}
    allowed = site_checks.allowed_external(config.SITE, None, None)
    ok, _ = site_checks.check_sources(built, pg, facts, None, allowed)
    assert not any("external link" in x for x in ok)
    bad, _ = site_checks.check_sources(built, pg, {**facts, "sources": []}, None, allowed)
    assert any("not a known source document" in x for x in bad)


def test_ofl_text_ships_with_the_fonts():
    brand = ROOT / "site" / "static" / "brand"
    text = (brand / "OFL.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in text and "PERMISSION & CONDITIONS" in text
    assert "The Inter Project Authors" in text and "The Outfit Project Authors" in text
    assert "OFL.txt" in (brand / "NOTICE.txt").read_text(encoding="utf-8")
