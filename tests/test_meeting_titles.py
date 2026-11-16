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
