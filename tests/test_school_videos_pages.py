"""The school board's meeting videos on its pages (sitegen/county_committees.py, Brian 2026-11-18): a meeting whose
date has a matched video links it (a Watch line per video, the hearing labelled as a hearing), any other meeting links
the district's channel; every word is config, no video title is shown, the day card carries the meeting's own video,
and the site check allows exactly these YouTube URLs. Built from the county fixture with FIXTURE agendas and a
FIXTURE videos file (a fixture build never links a real video)."""
import json
import re
from html import unescape

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS
from collector import school_videos as sv
from qa import site_checks as SC
from sitegen import config, county_committees as cmx_mod
from sitegen.build import build
from test_county_committee_pages import TODAY, agendas, main_of

FEED = (config.REPO_ROOT / "collector" / "tests" / "fixtures" / "school_videos" / "feed.xml").read_bytes()
VC = sv.load_config()
WATCH = re.compile(r'<a class="watch" data-ext="watch" href="([^"]+)"[^>]*>([^<]+)<span class="sr-only">'
                   r' \(opens in a new tab\)</span></a> <span class="watch-note">([^<]+)</span>')


def videos_file(tmp):
    p = tmp / "videos.json"
    p.write_text(json.dumps({"schema": sv.SCHEMA, "videos": sv.parse_feed(FEED, VC)}), encoding="utf-8")
    return p


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cmxv")
    path, data = agendas(tmp)
    vids = videos_file(tmp)
    data["fixture_videos"] = str(vids)
    path.write_text(json.dumps(data), encoding="utf-8")
    out = tmp / "build" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, today=TODAY, county_committees=path)
    return out, vids


def section(main: str, mid: str) -> str:
    return main.split(f'id="{mid}"', 1)[1].split("</section>", 1)[0]


def test_a_matched_meeting_links_its_videos_labelled_by_kind(built):
    out, _ = built
    v = config.SITE["county_committees"]["videos"]
    sec = section(main_of(out / "school-board" / "meetings" / "2024.html"), "2024-11-26-formal")
    got = [tuple(unescape(x) for x in m) for m in WATCH.findall(sec)]
    assert got == [("https://www.youtube.com/watch?v=FIXTUREvid1", v["link"], v["labels"]["meeting"] + "."),
                   ("https://www.youtube.com/watch?v=FIXTUREhrg2", v["link"], v["labels"]["hearing"] + ".")]
    assert "data-channel" not in sec
    # no video title is ever shown (a title can name a person); the labels are config words
    assert "CMCSS School Board" not in sec and "Public Hearing" not in sec


def test_an_unmatched_meeting_links_the_channel(built):
    out, _ = built
    v = config.SITE["county_committees"]["videos"]
    sec = section(main_of(out / "school-board" / "meetings" / "2024.html"), "2024-11-12-study")
    assert WATCH.findall(sec) == []
    line = sec.split("data-channel>", 1)[1].split("</p>", 1)[0]
    assert re.findall(r'href="([^"]+)"', line) == [VC["channel_url"]] and 'data-ext="watch"' in line
    assert " ".join(unescape(re.sub(r"<[^>]+>", " ", line)).split()) == (
        f'{v["channel_lede"]} {v["channel_label"]} (opens in a new tab) .')


def test_finance_committee_meetings_link_no_school_video(built):
    out, _ = built
    page = main_of(out / "county-committees" / "budget-committee" / "2024.html")
    assert "youtube.com" not in page


def test_the_day_card_carries_the_meetings_own_video(built):
    out, _ = built
    today = main_of(out / "today.html")
    card = today.split('id="school-board-2024-11-26-formal"', 1)[1].split("</article>", 1)[0]
    assert [m[0] for m in WATCH.findall(card)] == ["https://www.youtube.com/watch?v=FIXTUREvid1"]
    other = today.split('id="school-board-2024-11-12-study"', 1)[1].split("</article>", 1)[0]
    assert "youtube.com" not in other


def test_site_check_allows_exactly_the_configured_and_collected_video_urls(built):
    out, vids = built
    allowed = SC.school_video_urls(config.SITE, vids)
    assert VC["channel_url"] in allowed
    assert "https://www.youtube.com/watch?v=FIXTUREvid1" in allowed
    assert "https://www.youtube.com/watch?v=bmfHTL6mAeE" in allowed            # a known id
    assert not any("FIXTUREnot3" in u for u in allowed)                         # never kept, never allowed
    hrefs = [h for p in (out / "school-board" / "meetings").glob("*.html")
             for h in re.findall(r'href="(https://www\.youtube\.com[^"]*)"', p.read_text(encoding="utf-8"))]
    assert len(hrefs) == 3 and set(hrefs) <= allowed
    # any other YouTube link fails
    assert "https://www.youtube.com/watch?v=FIXTUREoth6" not in allowed


def test_a_fixture_build_never_links_a_real_video():
    vs = cmx_mod.video_settings(config.SITE["county_committees"]["videos"], fixture=True)
    assert vs["by_date"] == {} and vs["channel_url"] == VC["channel_url"]
    real = cmx_mod.video_settings(config.SITE["county_committees"]["videos"])
    assert real["by_date"]["2026-11-17"][0]["url"] == "https://www.youtube.com/watch?v=_-H2GdRHnj0"


@pytest.mark.parametrize("spec, why", [
    ({"labels": {"meeting": "x", "hearing": "y"}}, "labels"),
    ({"link": ""}, "empty"),
    ({"file": "config/localities/montgomery-tn/no-such.yml"}, "videos"),
])
def test_a_bad_videos_block_stops_the_build(spec, why):
    with pytest.raises(cmx_mod.CommitteesError, match=why):
        cmx_mod.video_settings({**config.SITE["county_committees"]["videos"], **spec})


def test_the_explanation_says_why_in_plain_neutral_words():
    lim = config.SITE["switch"]["bodies"]["school"]["limits"]
    assert lim["why"] == ("The school district blocks automated visitors to cmcss.net, and YouTube's terms do not allow "
                          "copying videos. This site follows those rules: it shows the agendas the county posts and "
                          "links each meeting to the district's own recording instead of transcribing it.")
    assert "videos" in lim["shown"]
