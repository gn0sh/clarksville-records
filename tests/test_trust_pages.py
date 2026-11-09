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
    assert 'href="https://gnoshcodes.com/"' in html and "No payers yet." in html
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
