"""site-polish/official-totals-consistent: an official page shows one consistent, labelled set of numbers. Before,
the stats band counted roll calls with a vote (329), the section all roll calls at the person's meetings (354), and
"Absent" meant 5 meetings in one place and 25 roll calls in the next. The check is qa/site_checks.py official-numbers."""
import re

from qa.site_checks import check_official_numbers, official_number_problems
from sitegen import views


def test_every_official_page_agrees_with_itself(built, facts):
    problems, note = check_official_numbers(built, facts)
    assert not problems, problems
    assert note.startswith(f"{len(facts['officials'])} official pages")


def test_each_number_matches_official_counts(pages, facts):
    ix = views.Index(facts)
    for o in facts["officials"]:
        c = views.official_counts(ix, o["id"])
        html = pages[f"officials/{o['id']}.html"]
        shown = {k: int(n) for k, n in re.findall(r'data-n="([a-z_]+)"[^>]*>(\d+)<', html)}
        for k in ("meetings_listed", "present", "absent", "rc_total", "rc_voted", "rc_absent", "rc_novote",
                  "rc_total_nc", "rc_voted_nc", "rc_absent_nc", "rc_novote_nc", "moved", "seconded"):
            assert shown[k] == c[k], (o["id"], k)


def test_the_check_catches_the_old_contradiction(pages, facts):
    html = pages[f"officials/{facts['officials'][0]['id']}.html"]
    # a stats band number that disagrees with the same number in the section
    bad = re.sub(r'(<span class="stat-num" data-n="rc_voted">)(\d+)<', lambda m: f"{m.group(1)}{int(m.group(2)) + 25}<",
                 html, count=1)
    assert any("rc_voted shows" in p for p in official_number_problems(bad))
    # roll calls while absent that no longer add up to the total
    bad = re.sub(r'(<span data-n="rc_absent">)(\d+)<', lambda m: f"{m.group(1)}{int(m.group(2)) + 20}<", html)
    assert any("= rc_total:" in p for p in official_number_problems(bad))
    assert official_number_problems(html) == []


def test_bars_name_their_unit(pages, facts):
    html = pages[f"officials/{facts['officials'][0]['id']}.html"]
    assert "Meetings absent: " in html and "Roll calls while recorded absent: " in html
