"""Visual refresh (docs/design/visual-refresh.md section 6): the numbers behind the bars, cards and timelines.
1. official_counts sums, and agrees with totals_sentences. 2. Bar segments match the tallies, fixed structure.
3. Home cards in name_key order with one skeleton. 4. Not-confirmed marks and unmatched names."""
import copy
import re

from conftest import parse
from sitegen import views
from test_held_counts import RC_HELD, MEETING_DEC, by_id
from test_site_review_fixes import build_pages
from test_site_neutrality import skeleton

BAR_ORDER = ["yes", "no", "abstain", "other", "absent", "novote"]
VOTES = re.compile(r"Roll call votes, [0-9-]+ to [0-9-]+: (\d+) Yes, (\d+) No, (\d+) Abstain, (\d+) Other confirmed; "
                   r"(\d+) Yes\*, (\d+) No\*, (\d+) Abstain\*, (\d+) Other\* not confirmed\.")
# SHOW_UNCONFIRMED_VALUES = False (the default): a count of unconfirmed roll calls, no breakdown
VOTES_HIDDEN = re.compile(r"Roll call votes, [0-9-]+ to [0-9-]+: (\d+) Yes, (\d+) No, (\d+) Abstain, (\d+) Other "
                          r"confirmed; (\d+) roll calls? not confirmed\*, see each page\.")


def test_official_counts_sum_and_agree_with_the_totals_sentences(facts):
    ix = views.Index(facts)
    for o in facts["officials"]:
        c = views.official_counts(ix, o["id"])
        for s in ("", "_nc"):
            voted = sum(c[k + s] for k in views.VOTE_VALUES)
            assert voted == c["rc_voted" + s], (o["id"], s)
            assert voted + c["rc_absent" + s] + c["rc_novote" + s] == c["rc_total" + s], (o["id"], s)
        assert c["present"] + c["absent"] == c["meetings_listed"], o["id"]
        t = views.totals_sentences(ix, o["id"])
        assert f"Recorded absent at {c['absent']} of {c['meetings_listed']} meetings" in t[0]
        if views.config.SHOW_UNCONFIRMED_VALUES:
            n = [int(x) for x in VOTES.fullmatch(t[1]).groups()]
            assert n == [c[k] for k in views.VOTE_VALUES] + [c[k + "_nc"] for k in views.VOTE_VALUES], o["id"]
        else:
            n = [int(x) for x in VOTES_HIDDEN.fullmatch(t[1]).groups()]
            assert n == [c[k] for k in views.VOTE_VALUES] + [c["rc_voted_nc"]], o["id"]
        page = views.official(o["id"], ix)
        assert [s["n"] for s in page["vote_bar"]] == [c[k] for k in views.VOTE_VALUES] + [c["rc_absent"], c["rc_novote"]]
        assert [s["key"] for s in page["vote_bar"]] == BAR_ORDER
        assert [s["n"] for s in page["attendance_bar"]] == [c["present"], c["absent"]]


def test_official_bars_sum_to_their_stated_denominators(pages, facts):
    for o in facts["officials"]:
        tree = parse(pages[f"officials/{o['id']}.html"])
        bars = [n for n in tree.walk() if "bar" in n.attrs.get("class", "").split()]
        assert len(bars) == 2
        sums = [sum(int(re.search(r"--n: (\d+)", s.attrs["style"]).group(1)) for s in b.children) for b in bars]
        text = tree.all_text()
        att = re.search(r"Recorded present at (\d+) and absent at (\d+) of (\d+) meetings", text)
        assert sums[0] == int(att.group(3)) and int(att.group(1)) + int(att.group(2)) == sums[0], o["id"]
        total = int(re.search(r"(\d+) confirmed roll calls? at meetings", text).group(1))
        assert sums[1] == total, o["id"]
        assert [len(b.children) for b in bars] == [2, 6]


def test_roll_call_bar_segments_match_the_tally(pages, facts):
    ix = views.Index(facts)
    seen = 0
    for m in facts["meetings"]:
        tree = parse(pages[f"meetings/{m['id']}.html"])
        for rc in (r for r in facts["roll_calls"] if r["meeting_id"] == m["id"]):
            block = next(n for n in tree.walk() if n.attrs.get("id") == rc["id"])
            if not views.values_shown(rc):  # SHOW_UNCONFIRMED_VALUES off: no bar, no tally for an unconfirmed one
                assert not any("bar" in n.attrs.get("class", "").split() for n in block.walk()), rc["id"]
                assert ix.outcome(rc)["counts"] is None and ix.outcome(rc)["tally"] is None
                seen += 1
                continue
            bar = next(n for n in block.walk() if "bar" in n.attrs.get("class", "").split())
            segs = [(s.attrs["class"].split()[-1], int(re.search(r"--n: (\d+)", s.attrs["style"]).group(1)))
                    for s in bar.children]
            assert [k for k, _ in segs] == [f"seg-{k}" for k in BAR_ORDER], rc["id"]  # same structure for every roll call
            out = ix.outcome(rc)
            assert [n for _, n in segs] == [out["counts"][k] for k in BAR_ORDER], rc["id"]
            assert out["counts"]["novote"] == 0
            tally = {w: int(n) for n, w in re.findall(r"(\d+) (yes|no|abstain|other|absent)", out["tally"])}
            assert all(out["counts"][k] == tally.get(k, 0) for k in ("yes", "no", "abstain", "other", "absent")), rc["id"]
            assert sum(n for _, n in segs) == len(rc["votes"]) + out["counts"]["absent"], rc["id"]
            seen += 1
    assert seen == len(facts["roll_calls"]) > 0


def test_officials_cards_follow_the_seat_rule_and_share_one_skeleton(pages, facts):
    """Design 6A.3 with the fixture roster: Current by seat (districts by number, then mayor), Served previously and
    Seat not yet recorded alphabetical; every card the same shape, wherever it is."""
    tree = parse(pages["officials.html"])
    sections = {n.attrs["id"]: n for n in tree.walk() if "data-order" in n.attrs}
    assert list(sections) == ["current", "previous", "unseated"]

    def hrefs(sec):
        return [a.attrs["href"] for c in sec.walk() if c.tag == "li" and c.attrs.get("class") == "card"
                for a in c.walk() if a.tag == "a"]

    assert hrefs(sections["current"]) == ["officials/a-example.html", "officials/d-testperson.html",
                                          "officials/c-placeholder.html", "officials/f-rosteronly.html"]  # District 1, District 2, County Mayor, City Mayor
    # the roster-only City Mayor (a page that says nothing is recorded, no counts): a card with the fixed sentence, last by seat order
    names = [" ".join(c.all_text().split()) for c in sections["current"].walk()
             if c.tag == "li" and c.attrs.get("class") == "card"]
    assert names[-1].startswith("FR F. Rosteronly, City Mayor") and "No votes or attendance are recorded" in names[-1]
    assert hrefs(sections["previous"]) == ["officials/b-sample.html"]
    assert hrefs(sections["unseated"]) == ["officials/e-fixture.html"]
    cards = [n for n in tree.walk() if n.tag == "li" and n.attrs.get("class") == "card"
             and n.attrs.get("data-official") != "f-rosteronly"]

    def shape(n):
        return (n.tag, n.attrs.get("class", ""), tuple(shape(c) for c in n.children if c.attrs.get("class") != "seat"))  # the seat label is data

    assert len({shape(c) for c in cards}) == 1
    for c in cards:
        text = " ".join(c.all_text().split())
        assert re.search(r"Present at \d+ of \d+ meetings? with attendance shown", text), text
        assert re.search(r"Recorded vote on \d+ confirmed and \d+ not confirmed\* roll calls?", text), text
    assert not [n for n in tree.walk() if "bar" in n.attrs.get("class", "").split()]
    text = " ".join(tree.all_text().split())
    assert "A. Example, District 1" in text and "B. Sample, District 2 (seen in roll calls 2024-11-04 to 2024-11-04)" in text
    assert "C. Placeholder, County Mayor" in text


def test_officials_without_a_roster_are_one_alphabetical_list_with_no_seat_labels(tmp_path, facts):
    pages = build_pages(tmp_path, facts)  # no seats file
    tree = parse(pages["officials.html"])
    sections = [n for n in tree.walk() if "data-order" in n.attrs]
    assert len(sections) == 1 and sections[0].attrs["data-order"] == "surname"
    hrefs = [next(a for a in c.walk() if a.tag == "a").attrs["href"]
             for c in tree.walk() if c.tag == "li" and c.attrs.get("class") == "card"]
    assert hrefs == [f"officials/{o['id']}.html" for o in sorted(facts["officials"], key=views.name_key)]
    assert 'class="seat"' not in "".join(pages.values())
    assert "Current" not in [n.all_text().strip() for n in tree.walk() if n.tag == "h2"]


def test_meetings_timeline_lines_have_one_shape(pages):
    tree = parse(pages["meetings.html"])
    items = [n for n in tree.walk() if n.tag == "li" and n.attrs.get("class") == "ev-meeting"]
    assert items
    for li in items:
        text = " ".join(li.all_text().split())
        assert re.search(r"\d+ roll calls? \(\d+ not confirmed\*\) · \d+ motions? · (\d+ of \d+ members present|attendance not shown)",
                         text), text


def test_not_confirmed_roll_calls_carry_the_asterisk_words_and_page_link(tmp_path, facts):
    f = copy.deepcopy(facts)
    for v in by_id(f, "roll_calls", RC_HELD)["votes"]:
        if v["official_id"] == "a-example":
            v.update(official_id=None, raw_name="Qq A. Exarnple")
    pages = build_pages(tmp_path, f)
    rc = by_id(f, "roll_calls", RC_HELD)
    link = f'#page={rc["page"]}"'
    html = pages[f"meetings/{MEETING_DEC}.html"]
    block = next(n for n in parse(html).walk() if n.attrs.get("id") == RC_HELD)
    assert "nc" in block.attrs["class"].split()
    text = " ".join(block.all_text().split())
    assert "Not confirmed" in text and "*" in text and "(not confirmed)" in text
    assert any(a.attrs.get("href", "").endswith(link.rstrip('"')) for a in block.walk() if a.tag == "a")
    # every vote chip is starred and dashed (nc ancestor); the unmatched name is plain text with the fixed words
    assert "Name not matched*" in text
    names = [li for li in block.walk() if li.tag == "li"]
    unmatched = [li for li in names if "Name not matched" in li.all_text()]
    assert len(unmatched) == 1 and not [a for a in unmatched[0].walk() if a.tag == "a"]
    assert all("*" in li.all_text() for li in names)
    assert "Exarnple" not in html


def test_nav_lists_every_items_year_newest_first(pages, facts):
    """Design 2.2: the one nav list (footer, cloned into the drawer by nav.js) links every items year, newest first,
    on every page, in the fixed order."""
    import re
    years = sorted({i["year"] for i in facts["items"]}, reverse=True)
    assert years
    for name, html in pages.items():
        nav = html[html.index('<nav id="site-nav"'):]
        nav = nav[:nav.index("</nav>")]
        assert [int(y) for y in re.findall(r'href="(?:\.\./)*items/(\d{4})\.html"', nav)] == years, name
        labels = [" ".join(re.sub(r"<[^>]+>", " ", x).split()) for x in re.findall(r'<li><(?:a [^>]*|span class="nav-group")>(.*?)</(?:a|span)>', nav)]
        labels = [x for x in labels if not x.isdigit()]
        want = ["Home", "Today", "Search", "Votes", "Meetings", "Officials", "School board Coming", "Items",
                "Finance Coming",
                "Capital projects Coming", "Data downloads", "Alerts", "Morning note", "Who runs this", "Our rules", "Corrections", "Method", "About", "Changes", "Review (internal)"]
        assert labels == want, (name, labels)
