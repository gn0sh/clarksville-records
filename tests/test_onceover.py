"""The design once-over of 2026-11-14 (problem keys onceover/...): dates in words on the pages with ISO kept where
machines and qa/site_checks.py read it, the masthead without a coverage line, the current year pill, the day strip's
dot on the chosen day, touch targets, the smallest label size, one heading system, and navigation rows that stay navy.
"""
import re
import shutil
import subprocess

import pytest

from conftest import ROOT
from sitegen import localdates

CSS = (ROOT / "site" / "static" / "style.css").read_text(encoding="utf-8")
WORDS = r"(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}"
ISO = r"\d{4}-\d{2}-\d{2}"


def main_of(html: str) -> str:
    return html.split("<main", 1)[1].split("</main>")[0]


def rule(selector: str) -> str:
    """The declarations of the first rule whose selector list is exactly `selector`."""
    m = re.search(r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert m, selector
    return m.group(1)


# ---- onceover/dates/iso-in-page-text ------------------------------------------------------------------------------

@pytest.mark.parametrize("given, shown", [
    ("2026-05-11", "May 11, 2026"),
    ("2020-02-01", "February 1, 2020"),                                  # no leading zero
    ("2026-05-11, formal meeting", "May 11, 2026, formal meeting"),
    ("2020-02-10 to 2026-05-11.", "February 10, 2020 to May 11, 2026."),
    ("2026-05-11-formal", "2026-05-11-formal"),                          # an id is not a date in running text
    ("meetings/2026-05-11.html", "meetings/2026-05-11.html"),            # nor a file name
    ("rc-2026-05-11", "rc-2026-05-11"),
    ("2026-05-11T09:00:00+00:00", "2026-05-11T09:00:00+00:00"),          # an instant is not a day
    ("2026-13-40", "2026-13-40"),                                        # not a real date: left as it is
    ("No appearance listed", "No appearance listed"),
    ("", ""),
])
def test_words_is_the_one_display_form(given, shown):
    assert localdates.words(given) == shown


def test_words_leaves_what_is_not_text_alone():
    assert localdates.words(None) is None


def test_meeting_dates_are_in_words_and_machine_dates_stay_iso(pages):
    """Headings, lists and tables print "May 11, 2026"; a URL, an id and a fact id keep the ISO day."""
    rel = next(r for r in sorted(pages) if re.fullmatch(r"meetings/" + ISO + r"-\w+\.html", r))
    iso = re.search(ISO, rel).group(0)
    page = main_of(pages[rel])
    h1 = re.search(r"<h1>(.*?)</h1>", page, re.S).group(1)
    assert re.search(r'<span class="nowrap">' + WORDS + "</span>", h1) and not re.search(ISO, h1), h1
    assert localdates.words(iso) in h1
    ids = [i for r, pg in pages.items() if r.startswith("meetings/") for i in re.findall(r'data-fact-id="([^"]+)"', pg)]
    assert any(re.match(ISO + "-", i) for i in ids) and not any(re.search(WORDS, i) for i in ids)   # fact ids: ISO
    index = main_of(pages["meetings.html"])
    links = re.findall(r'<a class="date" href="([^"]+)">([^<]+)</a>', index)
    assert links
    for href, text in links:                       # the link's address keeps the ISO day its text shows in words
        assert re.fullmatch(WORDS, text), text
        assert localdates.words(re.search(ISO, href).group(0)) == text, (href, text)
    assert not re.search(ISO, re.sub(r"<[^>]+>", " ", re.search(r'<p class="lede">.*?</p>', index, re.S).group(0)))


def test_history_tables_and_vote_lists_print_dates_in_words(pages):
    official = next(pages[r] for r in sorted(pages) if re.fullmatch(r"officials/[\w-]+\.html", r)
                    and 'class="c-date"' in pages[r])
    dates = re.findall(r'<td role="cell" class="c-date" data-label="Date"><div><a class="date" href="[^"]+">([^<]+)</a>',
                       official)
    assert dates and all(re.fullmatch(WORDS, d) for d in dates), dates[:3]
    votes = next(pages[r] for r in sorted(pages) if re.fullmatch(r"votes/\d{4}\.html", r))
    dates = re.findall(r'<p class="tl-head"><a class="date" href="[^"]+">([^<]+)</a>', votes)
    assert dates and all(re.fullmatch(WORDS, d) for d in dates), dates[:3]


def test_the_lines_site_checks_read_keep_iso_days(pages):
    """Fetch days, seat records and the official totals sentences are read by qa/site_checks.py (dates/no-raw-utc-day,
    provenance, official-numbers) as ISO days, so they never pass through the display form."""
    official = next(pages[r] for r in sorted(pages) if re.fullmatch(r"officials/[\w-]+\.html", r)
                    and 'class="seat-line"' in pages[r])
    seat = re.sub(r"<[^>]+>", "", re.search(r'<p class="seat-line">.*?</p>', official, re.S).group(0))
    assert re.search(ISO, seat) and not re.search(WORDS, seat), seat
    assert re.search(r"Roll call votes, " + ISO + " to " + ISO + ":", official)
    assert re.search(r"Recorded absent at \d+ of \d+ meetings with an extracted attendance section, " + ISO, official)
    meeting = next(pages[r] for r in sorted(pages) if re.fullmatch(r"meetings/" + ISO + r"-\w+\.html", r))
    assert re.search(r"fetched " + ISO, meeting) and not re.search(r"fetched " + WORDS, meeting)


def test_search_results_print_dates_in_words_from_an_iso_index():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    js = (ROOT / "site" / "static" / "search.js").read_text(encoding="utf-8")
    fn = re.search(r"  var MONTHS = .*?\n  function dayWords\(s\) \{.*?\n  \}\n", js, re.S).group(0)
    script = fn + """
      var out = [dayWords("2026-05-11"), dayWords("2020-02-01"), dayWords("2026-05-11-formal"), dayWords(""),
                 dayWords(undefined), "2026-05-11, formal meeting, X 2020-01-01".replace(/^\\d{4}-\\d{2}-\\d{2}(?=, )/, dayWords)];
      console.log(JSON.stringify(out));
    """
    res = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    assert res.stdout.strip() == ('["May 11, 2026","February 1, 2020","2026-05-11-formal","","",'
                                  '"May 11, 2026, formal meeting, X 2020-01-01"]')
    # every date a result prints goes through it; the fetch day beside a source stays as the index has it
    assert js.count("esc(dayWords(r.d") == 4 and '", fetched " + esc(r.s.f)' in js
    assert "esc(r.d)" not in js and "esc(r.d2)" not in js


# ---- onceover/header/county-kicker-everywhere ---------------------------------------------------------------------

def test_no_masthead_prints_a_coverage_line(pages):
    for rel, page in pages.items():
        header = page[page.index("<header"):page.index("</header>")]
        assert 'class="kicker"' not in header and not re.search(ISO, header), rel


# ---- the style sheet ----------------------------------------------------------------------------------------------

def test_the_current_year_pill_is_filled():
    r = rule('.year-nav a[aria-current], .year-nav a[aria-current]:visited, .year-nav a[aria-current]:hover')
    assert "background: var(--blue)" in r and "color: var(--on-blue)" in r


def test_the_plain_dot_is_paper_coloured_on_the_chosen_day():
    r = rule('.day-strip .day[aria-pressed="true"] .dot:not(.dot-county):not(.dot-rpc):not(.dot-bids)')
    assert "background: var(--bg)" in r


def test_touch_targets_are_44px_in_one_coarse_pointer_block():
    block = CSS[CSS.index("/* Touch targets (onceover/touch/small-targets)"):]
    block = block[block.index("@media (pointer: coarse) {"):block.index("\n}\n") + 3]
    for sel in (".year-nav a", "dialog.drawer .nav-years a", ".chip-filter", ".filter-panel label"):
        m = re.search(r"(?m)^  " + re.escape(sel) + r" \{([^}]*)\}", block)
        assert m and "min-height: 44px" in m.group(1), sel
    hit = re.search(r"details\.row-details > summary::after, \.clamp-btn::after \{([^}]*)\}", block).group(1)
    assert "height: 44px" in hit and "position: absolute" in hit
    # the footer's rows are the owner's decision: still 28px on a touch screen
    assert ".site-footer .nav-years a { min-height: 28px; line-height: 26px; }" in CSS


def test_the_smallest_labels_share_one_size():
    assert re.search(r"--t-eyebrow: \.72rem;", CSS)
    for sel in (".day-dow", ".meet-date .dow, .meet-date .mon", ".fin .sol-filters label", ".day-when"):
        assert "font-size: var(--t-eyebrow)" in rule(sel), sel
    small = re.findall(r"(?m)^([^{}\n]+)\{[^}]*font-size: \.6\d*rem", CSS)
    assert [s.strip() for s in small] == [".plate-place"]      # the name plate's place line: it must fit at 375px


def test_one_heading_system():
    h1, h2 = rule("h1"), rule("h2")
    for r in (h1, h2):
        assert "font-weight: 800" in r and "letter-spacing: -.02em" in r
    assert "border" not in h2 and "padding" not in h2
    for sel in (".sec-h", "h2.section-h", ".fin > h1", ".day-head h2", ".mn-card h2"):   # no second set of weights
        assert "font-weight" not in rule(sel) and "letter-spacing" not in rule(sel), sel
    assert not re.search(r"(?m)^\.fin h2 \{", CSS)


def test_navigation_rows_keep_the_link_colour_after_a_visit():
    r = rule(".door a:visited, .hub-go a:not([data-ext]):visited, ol.districts a:visited, .crumb a:visited, "
             ".kicker-line a:visited")
    assert r.strip() == "color: var(--link);"
