"""city-verify/moved-row-note-ambiguous: a Moved or Seconded row is shown only for a verified motion; when the roll call
on that motion is held, the row's note names the roll call's outcome, never reads as if the motion were held."""
import re
from html import unescape

from qa import site_checks

MO = "mo-314626e6-p15-2"               # fixture: a verified motion (moved by E. Fixture) whose roll call is held
HELD_RC = "rc-314626e6-p16-1"


def rows(pages, fact_id):
    pat = re.compile(rf'<tr role="row"[^>]*data-fact-id="{re.escape(fact_id)}".*?</tr>', re.S)
    return [(rel, unescape(m.group(0))) for rel, html in pages.items() for m in pat.finditer(html)]


def test_the_fixture_has_the_case(facts):
    mo = next(m for m in facts["motions"] if m["id"] == MO)
    rc = next(r for r in facts["roll_calls"] if r["id"] == HELD_RC)
    assert mo["verification"]["status"] == "verified" and rc["motion_id"] == MO
    assert rc["verification"]["status"] != "verified"


def test_a_moved_row_of_a_held_roll_call_names_the_roll_call_not_the_motion(pages):
    found = rows(pages, f"{MO}/moved")
    assert found
    for rel, row in found:
        assert "Outcome not confirmed: the roll call on this motion is held." in row, rel
        assert "Who moved and seconded it is confirmed." in row, rel
        assert "Not confirmed: this page was hard to read." not in row, rel     # the roll call's own note
        assert 'class="fact nc"' not in row, rel                               # the row itself is not marked held


def test_the_vote_row_of_the_held_roll_call_keeps_its_own_note(pages):
    found = [(rel, row) for rel, row in rows(pages, "") if f'data-fact-id="{HELD_RC}/' in row] or \
        [(rel, unescape(h)) for rel, h in pages.items() if f'data-fact-id="{HELD_RC}/' in h]
    assert found and all("Not confirmed: this page was hard to read." in row for _, row in found)


def test_site_check_fails_a_moved_row_that_carries_the_roll_calls_note(tmp_path, facts):
    """qa/site_checks.py check_unverified restates the rule: a /moved or /seconded row never carries a held note."""
    row = (f'<table><tr role="row" class="fact" data-fact-id="{MO}/moved"><td>Moved</td><td><span class="unconfirmed">'
           '* {}</span></td></tr></table>')
    def problems(note):
        page = tmp_path / "officials" / "e-fixture.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(f"<html><body>{row.format(note)}</body></html>", encoding="utf-8")
        out = site_checks.check_unverified(tmp_path, {"officials/e-fixture.html": site_checks.parse(page)}, facts,
                                           internal=False, export=False)
        return [p for p in out if f"{MO}/moved" in p and "as if the motion were held" in p]
    assert problems("Not confirmed: this page was hard to read.")
    assert not problems("Outcome not confirmed: the roll call on this motion is held. This page was hard to read.")
