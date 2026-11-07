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
    edit(site / "index.html", 'href="officials/a-example.html"', 'href="officials/nobody.html"')
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
    edit(site / "meetings" / "2024-12-09-formal.html", "Run by Brian Zacharias", "Run by someone")
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
    edit(page, "<strong>Outcome:</strong>", "<strong>Outcome*:</strong>")
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
    edit(site / "index.html", '<li><a href="officials/b-sample.html">B. Sample</a> <span class="muted">Commissioner</span></li>', "")
    assert "index" in failed(run(site))


def test_index_order_is_checked(site):
    t = (site / "index.html").read_text(encoding="utf-8")
    a, b = "officials/a-example.html", "officials/b-sample.html"
    (site / "index.html").write_text(t.replace(a, "@@").replace(b, a).replace("@@", b), encoding="utf-8")
    assert "index" in failed(run(site))


def test_official_page_with_a_different_layout_is_caught(site):
    edit(site / "officials" / "b-sample.html", "<h2 id=\"totals-h\">Totals</h2>", "<h2 id=\"totals-h\">Totals and more</h2>")
    assert "layout" in failed(run(site))


def test_wrong_attendance_total_is_caught(site):
    edit(site / "officials" / "a-example.html", "Recorded absent at 0 of 2 meetings", "Recorded absent at 1 of 2 meetings")
    assert "totals" in failed(run(site))


def test_third_party_script_is_caught(site):
    edit(site / "index.html", "</head>", '<script src="https://cdn.example/x.js"></script></head>')
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
