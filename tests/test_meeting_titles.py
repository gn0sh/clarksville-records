"""onceover/meeting/title-names-body (Brian, Nov 14): a meeting's title names its body ("County Commission formal
meeting, May 11, 2026"), in the h1, the page title and the share card, the same way for every meeting."""
import re

from sitegen import config, localdates


def test_meeting_pages_name_the_body_in_h1_title_and_share_card(pages, facts):
    body = config.SITE["meeting_title_body"]
    assert body
    for m in facts["meetings"]:
        html = pages[f"meetings/{m['id']}.html"]
        kind = config.KIND_LABELS[m["kind"]].lower()
        want = f"{body} {kind}, {localdates.words(m['date'])}"
        h1 = re.sub(r"<[^>]+>", "", re.search(r"<h1>(.*?)</h1>", html, re.S).group(1))
        assert h1 == want, (m["id"], h1)
        assert re.search(rf"<title>[^<]*\| {re.escape(want)}</title>", html), m["id"]
        assert f'<meta property="og:title" content="' in html and f"| {want}\">" in html, m["id"]


def test_official_header_card_holds_name_and_title_and_the_seat_line_follows_it(pages, facts):
    """onceover/official/header-seat-line: the seat history and coverage sit under the header card, for everyone."""
    for o in facts["officials"]:
        html = pages[f"officials/{o['id']}.html"]
        head = re.search(r'<header class="official-head">.*?</header>', html, re.S).group(0)
        assert "seat-line" not in head and "coverage" not in head, o["id"]
        sub = re.search(r'</header>\s*<div class="official-sub">(.*?)</div>', html, re.S)
        assert sub and 'class="muted coverage"' in sub.group(1), o["id"]


def test_votes_year_rows_keep_the_source_link_and_put_the_fact_id_behind_details(pages):
    """onceover/cite/fact-id-always-visible: on votes/<year>.html the page link shows; fetch date, fact id and the
    report link sit in the row's Details toggle (the source_cell pattern)."""
    years = [k for k in pages if re.fullmatch(r"votes/\d{4}\.html", k)]
    assert years
    for k in years:
        for li in re.findall(r'<li class="fact[^"]*" data-fact-id="[^"]+">(.*?)</li>', pages[k], re.S):
            cite = re.search(r'<div class="meta vote-cite">(.*?)</div>\s*$', li, re.S).group(1)
            visible = re.sub(r"<details.*?</details>", "", cite, flags=re.S)
            assert 'href="' in visible and "#page=" in visible and "Fact id" not in visible
            assert re.search(r'<details class="row-details"><summary>Details</summary>.*Fact id', cite, re.S)
