# ruff: noqa: E501
"""The QA tools themselves: they must pass on the clean fixture build and catch each planted defect."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from qa import site_checks, spot_check
from qa.common import FIXTURE, load_facts

FACTS = load_facts(FIXTURE)
UNVERIFIED_RC = next(r for r in FACTS["roll_calls"] if r["verification"]["status"] == "unverified")


@pytest.fixture()
def site(tmp_path, built):
    dst = tmp_path / "site"
    shutil.copytree(built, dst)
    (dst / "review.html").unlink()          # public build: no internal page
    # the public build the generator would make has no links to it; `built` was made --internal, so drop them
    for f in dst.rglob("*.html"):
        t = f.read_text(encoding="utf-8")
        f.write_text(t.replace('href="review.html"', 'href="about.html"').replace('href="../review.html"', 'href="../about.html"'),
                     encoding="utf-8")
    return dst


def run(site_dir, **kw):
    kw.setdefault("browser", False)
    kw.setdefault("no_export", True)
    return site_checks.run_checks(site_dir, FACTS, **kw)


def failed(rep):
    return {name for name, ok, _, _ in rep.results if not ok}


def edit(path, old, new, count=1):
    t = path.read_text(encoding="utf-8")
    assert old in t, f"{old!r} not in {path}"
    path.write_text(t.replace(old, new, count), encoding="utf-8")


def test_clean_fixture_build_passes(site):
    rep = run(site)
    assert rep.ok, rep.render()


def test_broken_internal_link_is_caught(site):
    edit(site / "officials.html", 'href="officials/a-example.html"', 'href="officials/nobody.html"')
    assert "links" in failed(run(site))


def test_broken_anchor_is_caught(site):
    edit(site / "officials" / "a-example.html", "../items/2024.html#AB-91-2024", "../items/2024.html#no-such-item")
    assert "links" in failed(run(site))


def test_page_beyond_page_count_is_caught(site):
    edit(site / "officials" / "a-example.html", "minutes-2024-12.pdf#page=10", "minutes-2024-12.pdf#page=26")
    assert "sources" in failed(run(site))


def test_fact_row_source_link_without_page_is_caught(site):
    edit(site / "officials" / "a-example.html", "minutes-2024-12.pdf#page=10", "minutes-2024-12.pdf")
    assert "sources" in failed(run(site))


def test_unknown_external_link_is_caught(site):
    edit(site / "about.html", "</main>", '<p><a href="https://campaign.example/donate">x</a></p></main>')
    assert "sources" in failed(run(site))


def test_missing_footer_is_caught(site):
    edit(site / "meetings" / "2024-12-09-formal.html", "Provided as a free service by Brian Zacharias", "Provided by someone")
    assert "footer" in failed(run(site))


def test_unverified_outcome_text_in_public_page_is_caught(site):
    edit(site / "items" / "2024.html", "</main>", f"<p>{UNVERIFIED_RC['outcome_text']}</p></main>")
    assert "unverified" in failed(run(site))


def test_unverified_outcome_text_in_export_is_caught(site):
    (site / "data").mkdir()
    (site / "data" / "roll_calls.csv").write_text("outcome\n" + UNVERIFIED_RC["outcome_text"] + "\n", encoding="utf-8")
    assert "unverified" in failed(run(site))


def test_vote_row_for_someone_not_in_the_roll_call_is_caught(site):
    voters = {v["official_id"] for v in UNVERIFIED_RC["votes"]}
    other = next(o["id"] for o in FACTS["officials"] if o["id"] not in voters)
    victim = f"{UNVERIFIED_RC['id']}/{other}"
    edit(site / "officials" / f"{other}.html", '<tbody role="rowgroup">', f'<tbody role="rowgroup"><tr data-fact-id="{victim}"><td>x</td></tr>')
    assert "unverified" in failed(run(site))


def test_unconfirmed_roll_call_without_its_note_is_caught(site):
    page = site / "meetings" / f"{UNVERIFIED_RC['meeting_id']}.html"
    edit(page, "Not confirmed: this page was hard to read.", "", count=-1)
    assert "unverified" in failed(run(site))


def test_note_outside_its_row_is_caught(site):
    """The note must sit in the row or block it belongs to; the same text elsewhere on the page does not count."""
    voter = next(v["official_id"] for v in UNVERIFIED_RC["votes"] if v["official_id"])
    edit(site / "officials" / f"{voter}.html", "Not confirmed: this page was hard to read.", "", count=-1)
    edit(site / "officials" / f"{voter}.html", "</main>", "<p>Not confirmed: this page was hard to read.</p></main>")
    rep = run(site)
    assert "unverified" in failed(rep)
    assert f"{UNVERIFIED_RC['id']}/{voter} shows an unconfirmed roll call without" in rep.render()


def test_star_on_a_confirmed_roll_call_is_caught(site):
    rc = next(r for r in FACTS["roll_calls"] if r["verification"]["status"] == "verified")
    page = site / "meetings" / f"{rc['meeting_id']}.html"
    edit(page, '<strong class="label">Outcome:</strong>', '<strong class="label">Outcome*:</strong>')
    assert "unverified" in failed(run(site))


def test_outcome_text_matching_a_roll_call_event_label_is_still_caught(site):
    """raw-ocr-leak/qa-outcome-benign: motion and roll call event labels are raw OCR no page shows, so an outcome text
    that also appears in one is still a leak."""
    facts = json.loads(json.dumps(FACTS))
    ev = next(e for e in facts["item_events"] if e["ref"] == UNVERIFIED_RC["id"])
    ev["label"] = "On roll call: " + UNVERIFIED_RC["outcome_text"]
    edit(site / "items" / "2024.html", "</main>", f"<p>{UNVERIFIED_RC['outcome_text']}</p></main>")
    rep = site_checks.run_checks(site, facts, browser=False, no_export=True)
    assert "unverified" in failed(rep)


def test_shown_fact_missing_from_official_page_is_caught(site):
    page = site / "officials" / "a-example.html"
    t = page.read_text(encoding="utf-8")
    page.write_text(t.replace('data-fact-id="rc-314626e6-p10-1/a-example"', 'data-x="1"'), encoding="utf-8")
    assert "unverified" in failed(run(site))


def test_review_page_in_public_build_is_caught(site, built):
    shutil.copy(built / "review.html", site / "review.html")
    assert "unverified" in failed(run(site))
    assert "unverified" not in failed(run(site, internal=True))


def test_missing_or_misordered_index_entry_is_caught(site):
    import re
    index = site / "officials.html"
    t = index.read_text(encoding="utf-8")
    t2 = re.sub(r'<li class="card"[^>]*>(?:(?!</li>).)*?officials/b-sample\.html.*?</li>', "", t, count=1, flags=re.S)
    assert t2 != t, "the b-sample card was not found on officials.html"
    index.write_text(t2, encoding="utf-8")
    assert "index" in failed(run(site))


def test_index_order_is_checked(site):
    """Current is in seat order (a-example District 1 before d-testperson District 2): swapping them is caught."""
    t = (site / "officials.html").read_text(encoding="utf-8")
    a, b = "officials/a-example.html", "officials/d-testperson.html"
    import re
    cards = re.findall(r'<li class="card"[^>]*>.*?</li>', t, re.S)
    ca = next(c for c in cards if a in c)
    cb = next(c for c in cards if b in c)
    (site / "officials.html").write_text(t.replace(ca, "@@").replace(cb, ca).replace("@@", cb), encoding="utf-8")
    assert "index" in failed(run(site))


def test_alphabetical_section_order_is_checked(tmp_path, facts):
    """Without a roster, one alphabetical list: swapping two names is caught."""
    from sitegen.build import build
    out = tmp_path / "plain"
    build(FIXTURE, out)
    t = (out / "officials.html").read_text(encoding="utf-8")
    a, b = "officials/a-example.html", "officials/b-sample.html"
    (out / "officials.html").write_text(t.replace(a, "@@").replace(b, a).replace("@@", b), encoding="utf-8")
    assert "index" in failed(run(out))


def test_unmarked_or_insecure_external_link_is_caught(site):
    edit(site / "districts" / "01.html", 'data-ext="roster" href="https://', 'href="https://')
    assert "sources" in failed(run(site))


def test_official_page_with_a_different_layout_is_caught(site):
    edit(site / "officials" / "b-sample.html", "<h2 id=\"totals-h\">Totals</h2>", "<h2 id=\"totals-h\">Totals and more</h2>")
    assert "layout" in failed(run(site))


def test_wrong_attendance_total_is_caught(site):
    edit(site / "officials" / "a-example.html", "Recorded absent at 0 of 2 meetings", "Recorded absent at 1 of 2 meetings")
    assert "totals" in failed(run(site))


def test_third_party_script_is_caught(site):
    edit(site / "search.html", "</head>", '<script src="https://cdn.example/x.js"></script></head>')
    assert "external" in failed(run(site))


def test_file_cap_is_enforced(site):
    for i in range(site_checks.MAX_FILES):
        (site / f"pad{i}.txt").write_text("x")
    assert "files" in failed(run(site))


def _browser_ok():
    try:
        site_checks.subprocess.run(["node", "--version"], capture_output=True, timeout=10, check=True)
        return Path("/opt/pw-browsers").exists() or bool(shutil.which("playwright"))
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_horizontal_scroll_check_passes_clean_and_catches_overflow(site):
    assert run(site, browser=True).ok
    edit(site / "meetings" / "2024-12-09-formal.html", "<main", '<div style="width:900px;height:10px;background:red"></div><main')
    rep = run(site, browser=True, all_pages=True)
    assert "hscroll" in failed(rep), rep.render()


def test_spot_check_self_test():
    assert spot_check.self_test() == 0


def test_spot_check_picks_are_stable_for_the_fixture():
    a = [c["fact_id"] for c in spot_check.pick(spot_check.candidates(FACTS), 20, spot_check.DEFAULT_SEED)]
    b = [c["fact_id"] for c in spot_check.pick(spot_check.candidates(FACTS), 20, spot_check.DEFAULT_SEED)]
    assert a == b and a
    assert not any(f.startswith(UNVERIFIED_RC["id"] + "/") for f in a)
    json.dumps(a)


def test_marked_external_link_to_an_unlisted_url_is_caught(site):
    """qa-weakened/ext-link-any-host: data-ext excuses only the exact URLs from the config, map and roster."""
    edit(site / "about.html", "</main>",
         '<p><a data-ext="county" href="https://evil.example.org/page">x</a></p></main>')
    assert "sources" in failed(run(site))


def test_one_allowed_link_does_not_excuse_an_unmarked_copy(site):
    """Each <a> is judged on its own: the same URL without data-ext on the same page still fails."""
    from sitegen import config
    url = config.SITE["redistricting_page"]
    edit(site / "about.html", "</main>", f'<p><a href="{url}">again</a></p></main>')
    assert "sources" in failed(run(site))


def test_layout_ignores_how_many_year_tables_a_page_has(site):
    """qa-tool/layout-counts-year-tables: one more year table with the same columns is the same layout; a changed
    column header is not."""
    page = site / "officials" / "a-example.html"
    t = page.read_text(encoding="utf-8")
    start = t.index('<details class="year-group"')
    end = t.index("</details>", start) + len("</details>")
    page.write_text(t[:end] + t[start:end].replace(" open", "") + t[end:], encoding="utf-8")
    assert "layout" not in failed(run(site))
    edit(page, ">Outcome</th>", ">Result</th>")
    assert "layout" in failed(run(site))


def test_name_links_check_catches_an_unlinked_official_name(site):
    """Standing rule: an official's name shown anywhere is a link to officials/<id>.html."""
    page = site / "meetings" / "2024-12-09-formal.html"
    t = page.read_text(encoding="utf-8")
    assert '<a href="../officials/a-example.html">A. Example</a>' in t
    assert "name-links" not in failed(run(site))
    edit(page, '<a href="../officials/a-example.html">A. Example</a>', "A. Example")
    assert "name-links" in failed(run(site))
    edit(page, "A. Example", '<a href="../officials/b-sample.html">A. Example</a>')   # linked, but to the wrong person
    assert "name-links" in failed(run(site))


def test_name_links_check_ignores_title_option_footer_and_own_page(site):
    edit(site / "about.html", "</main>", "<p hidden></p></main>")
    page = site / "about.html"
    t = page.read_text(encoding="utf-8")
    page.write_text(t.replace("<title>", "<title>A. Example ", 1), encoding="utf-8")
    edit(page, "</main>", '<select><option>A. Example</option></select></main>')
    assert "name-links" not in failed(run(site))
    # an item title is text in the document (manager decision 2026-11-09): a name in it is not checked
    edit(page, "</main>", '<p><a href="items/2024.html#x"><span data-item-title>Sale to A. Example</span></a></p></main>')
    assert "name-links" not in failed(run(site))
    edit(page, "</main>", '<p>Sale to A. Example</p></main>')   # outside a title the rule still holds
    assert "name-links" in failed(run(site))


def test_roster_only_official_has_a_page_that_says_nothing_is_recorded(site):
    page = (site / "officials" / "f-rosteronly.html").read_text(encoding="utf-8")
    assert "No votes or attendance are recorded for this person in the minutes collected so far." in page
    assert "F. Rosteronly" in page and 'data-ext="roster"' in page
    cards = (site / "officials.html").read_text(encoding="utf-8")
    assert '<a class="card-name" href="officials/f-rosteronly.html">F. Rosteronly</a>' in cards


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_row_height_check_passes_clean_and_catches_a_tall_row(site):
    assert "row-height" not in failed(run(site, browser=True))
    page = site / "officials" / "a-example.html"
    edit(page, '<td role="cell" class="c-item" data-label="Item"><div>',
         '<td role="cell" class="c-item" data-label="Item"><div><div style="height:900px"></div>')
    rep = run(site, browser=True, all_pages=True)
    assert "row-height" in failed(rep), rep.render()


def test_allowed_external_has_the_district_lookup_url():
    cfg = site_checks._site_cfg()
    assert cfg["district_lookup_url"] in site_checks.allowed_external(cfg, None, None)
    assert cfg["district_lookup_url"] not in site_checks.allowed_external({**cfg, "district_lookup_url": ""}, None, None)
    assert cfg["geocoder_url"] not in site_checks.allowed_external(cfg, None, None)   # never a link, only the box's call


def test_lookup_link_to_another_url_is_caught(site):
    """data-ext="lookup" excuses only the configured district_lookup_url, exactly."""
    from sitegen import config
    url = config.SITE["district_lookup_url"]
    edit(site / "about.html", "</main>", f'<p><a data-ext="lookup" href="{url}">ok</a></p></main>')
    assert "sources" not in failed(run(site))
    edit(site / "about.html", "</main>", f'<p><a data-ext="lookup" href="{url}x/">lookalike</a></p></main>')
    assert "sources" in failed(run(site))
