"""F5: source links (AC1.3), totals recount (AC2.2), unverified facts never shown, internal links resolve."""
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

from conftest import parse
from sitegen import build as sitegen_build, config


def fact_elements(html):
    return [n for n in parse(html).walk() if "data-fact-id" in n.attrs]


def test_every_fact_row_links_to_its_pdf_page(pages, facts):
    pages_of = {s["url"]: s["pages"] for s in facts["sources"]}
    total = 0
    for name, html in pages.items():
        for el in fact_elements(html):
            total += 1
            ok = False
            for a in (n for n in el.walk() if n.tag == "a"):
                href = a.attrs.get("href", "")
                m = re.match(r"^(.*)#page=(\d+)$", href)
                if m and m.group(1) in pages_of:
                    assert 1 <= int(m.group(2)) <= pages_of[m.group(1)], (name, href)
                    assert a.attrs.get("target") == "_blank"
                    ok = True
            assert ok, f"{name}: fact {el.attrs['data-fact-id']} has no #page= source link"
            assert "Report an error" in el.all_text(), (name, el.attrs["data-fact-id"])
    assert total > 20


def test_vote_rows_link_item_and_meeting(pages, facts):
    for o in facts["officials"]:
        html = pages[f"officials/{o['id']}.html"]
        for row in fact_elements(html):
            hrefs = [n.attrs.get("href", "") for n in row.walk() if n.tag == "a"]
            assert any(re.match(r"^\.\./meetings/.+\.html", h) for h in hrefs)
            if row.attrs["data-type"] in ("vote", "moved", "seconded"):
                assert any(re.match(r"^\.\./items/\d{4}\.html#.+", h) for h in hrefs), row.attrs["data-fact-id"]


def test_attendance_totals_match_meeting_pages(pages, facts):
    """AC2.2: recount from the built meeting pages, not from the facts."""
    counts = {}
    for name, html in pages.items():
        if not name.startswith("meetings/"):
            continue
        for tr in (n for n in parse(html).walk() if n.tag == "tr" and "data-fact-id" in n.attrs):
            _, _, oid = tr.attrs["data-fact-id"].partition("/att/")
            status = [c for c in tr.children if c.tag == "td"][0].all_text().strip()
            listed, absent = counts.get(oid, (0, 0))
            counts[oid] = (listed + 1, absent + (status == "Absent"))
    for o in facts["officials"]:
        html = pages[f"officials/{o['id']}.html"]
        m = re.search(r"Recorded absent at (\d+) of (\d+) meetings", html)
        assert m, o["id"]
        listed, absent = counts.get(o["id"], (0, 0))
        assert (int(m.group(1)), int(m.group(2))) == (absent, listed), o["id"]


def test_unverified_roll_calls_are_shown_marked(pages, facts):
    """CEO decision 2026-11-07: an unverified roll call is shown on its meeting page, item page and each resolved
    voter's page, marked "Not confirmed" with a link to the exact page; still listed on review.html."""
    note = "Not confirmed: this page was hard to read."
    unverified = [r for r in facts["roll_calls"] if r["verification"]["status"] == "unverified"]
    assert unverified
    src = {s["id"]: s for s in facts["sources"]}
    for rc in unverified:
        link = f'href="{src[rc["source_id"]]["url"]}#page={rc["page"]}"'
        meeting = pages[f"meetings/{rc['meeting_id']}.html"]
        assert f'id="{rc["id"]}"' in meeting and note in meeting and link in meeting
        assert "1 roll call at this meeting is not confirmed and marked *." in meeting
        for e in (e for e in facts["item_events"] if e["ref"] == rc["id"]):
            assert f'data-fact-id="{e["id"]}"' in pages["items/2024.html"]
        for v in rc["votes"]:
            page = pages[f"officials/{v['official_id']}.html"]
            assert f'data-fact-id="{rc["id"]}/{v["official_id"]}"' in page and note in page and link in page
        assert rc["id"] in pages["review.html"]
        assert rc["outcome_text"] not in "".join(v for k, v in pages.items() if k != "review.html")


def test_internal_links_resolve(built, pages):
    for name, html in pages.items():
        for a in (n for n in parse(html).walk() if n.tag == "a" and "href" in n.attrs):
            href = a.attrs["href"]
            u = urlparse(href)
            if u.scheme or href.startswith("#") and not u.path:
                if href.startswith("#"):
                    ids = {n.attrs["id"] for n in parse(html).walk() if "id" in n.attrs}
                    assert href[1:] in ids, (name, href)
                continue
            target = (Path(name).parent / unquote(u.path))
            parts = []
            for p in target.parts:
                if p == "..":
                    parts.pop()
                else:
                    parts.append(p)
            rel = "/".join(parts)
            if rel.startswith("data/"):
                continue  # written by the collector's export, not by sitegen
            assert (built / rel).is_file(), (name, href)
            if u.fragment and rel.endswith(".html"):
                ids = {n.attrs["id"] for n in parse((built / rel).read_text(encoding="utf-8")).walk() if "id" in n.attrs}
                assert u.fragment in ids, (name, href)


def test_every_page_has_operator_footer_fixture_banner_and_no_external_resources(pages):
    for name, html in pages.items():
        assert (f'Provided as a free service by <a data-ext="operator" href="{config.SITE["operator_url"]}" '
                f'rel="noopener noreferrer">{config.OPERATOR_NAME}</a>.') in html, name
        assert "Run by" not in html, name
        assert "About this site and its data rules." in html, name
        assert 'Data as of <time class="data-as-of" datetime="2026-11-07">November 7, 2026</time>' in html, name
        assert "FIXTURE" in html, name
        assert not re.search(r'<(script|link|img)[^>]+(src|href)="https?://', html), name
        assert f"<title>{config.SITE_NAME} (independent, unofficial) | " in html and config.SITE_NAME == "Daylight", name


def test_public_build_has_no_review_page(tmp_path):
    out = tmp_path / "build" / "site"
    sitegen_build.build(config.REPO_ROOT / "site" / "fixtures" / "facts.sample.json", out, internal=False)
    assert not (out / "review.html").exists()
    for p in out.rglob("*.html"):
        assert "review.html" not in p.read_text(encoding="utf-8")


def test_publish_manifest_and_file_limit(tmp_path, monkeypatch):
    out = tmp_path / "build" / "site"
    sitegen_build.build(config.REPO_ROOT / "site" / "fixtures" / "facts.sample.json", out)
    manifest = json.loads((tmp_path / "build" / "publish-files.json").read_text())
    assert "index.html" not in manifest and "about.html" in manifest and "static/style.css" in manifest
    assert all(Path(v).is_file() for v in manifest.values())
    monkeypatch.setitem(config.MAX_FILES_BY_TARGET, "preview", 5)
    with pytest.raises(sitegen_build.BuildError):
        sitegen_build.write_publish_manifest(out, "preview")


def test_invalid_facts_fail_the_build(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    with pytest.raises(sitegen_build.BuildError):
        sitegen_build.build(bad, tmp_path / "out")


def test_placeholder_operator_warns(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(config, "OPERATOR_NAME", config.OPERATOR_PLACEHOLDER)
    sitegen_build.build(config.REPO_ROOT / "site" / "fixtures" / "facts.sample.json", tmp_path / "b" / "site")
    assert "placeholder" in capsys.readouterr().err
