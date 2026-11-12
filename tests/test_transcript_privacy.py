"""Private details in transcript text (security review M1, privacy/transcript-private-addresses; sitegen/privacy.py).

Rules under test: street addresses and phone numbers are masked everywhere in transcript text before anything is
shown or quoted (transcript pages, call-on excerpts on member pages); never ordinance numbers, dates, dollar amounts or
resolution numbers; an address split over two lines is found; the line keeps its time link; transcript pages carry
robots noindex and one plain line linking the site's Report an error page; qa.site_checks fails a build that shows an
address in transcript text or carries a committed transcript line holding one in any file (pages, data/, search)."""
import json
import re
import shutil

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, ROOT
from qa import site_checks
from sitegen import privacy
from sitegen import transcripts as tx
from sitegen.build import build

A, P = privacy.ADDRESS_MASK, privacy.PHONE_MASK
TRANSCRIPTS = ROOT / "data" / "localities" / "clarksville-tn" / "transcripts"


# ------------------------------------------------------------------------------------------------- the masking rule

@pytest.mark.parametrize("text, masked", [
    # real lines from the committed transcripts (data/localities/clarksville-tn/transcripts)
    ("Yeah, everyone. Jeremy Wright. My address is 701 Anita Court, Clarksville, Tennessee, 37042.",
     f"Yeah, everyone. Jeremy Wright. My address is {A}, Clarksville, Tennessee, 37042."),
    ("you have five minutes. Calvin Ligon, 951 Crabapple Court. Just looking",
     f"you have five minutes. Calvin Ligon, {A}. Just looking"),
    ("My name is Eric Launch. I live at 724 R.S. Bradley Boulevard. It's", f"My name is Eric Launch. I live at {A}. It's"),
    ("I'm Lyle L. Jones. I live on 512 4th Street. In that lot", f"I'm Lyle L. Jones. I live on {A}. In that lot"),
    ("my name is Jeff Lloyd I live at 577 Waldorf Drive I've called Clarksville",
     f"my name is Jeff Lloyd I live at {A} I've called Clarksville"),
    ("sir name is mark remini i live at 266 cheshire since 2001.", f"sir name is mark remini i live at {A} since 2001."),
    ("I live at 377 so I'm right next to it", f"I live at {A} so I'm right next to it"),
    ("Um, I stayed at eight 25 Marion street and where he", f"Um, I stayed at {A} and where he"),
    ("for 62 years from five or five port street to a 25 Marion street", f"for 62 years from {A} to a {A}"),
    ("on property located at 3341 and 3351 Pembroke Road from R1", f"on property located at {A} from R1"),
    ("will be updated at 10 18 swift drive from 01 office", f"will be updated at {A} from 01 office"),
    ("I'm Jeff Fletcher. I live at. 1021 Pumping Station and 1111 South Montferry Road.",
     f"I'm Jeff Fletcher. I live at. {A} and {A}."),
    ("my address is seven oh one Anita Court", f"my address is {A}"),
    # phone numbers: every one, official lines included
    ("in contact with the director is 931-648-6133. Again,", f"in contact with the director is {P}. Again,"),
    ("a non-emergency number that is 931. 552. 1011. Our next", f"a non-emergency number that is {P}. Our next"),
    ("called the hotline and that said 931 472 3355. And", f"called the hotline and that said {P}. And"),
    ("call (931) 645-7400 or 648-6100 today", f"call {P} or {P} today"),
    ("my number is nine three one five five five one two one two", f"my number is {P}"),
])
def test_addresses_and_phone_numbers_are_masked(text, masked):
    assert privacy.mask(text) == masked


@pytest.mark.parametrize("text", [
    "Ordinance 98-2025-26, second reading, an ordinance amending the zoning code",
    "Ordinance 103-2024-25 for a grant award",
    "the bill was $1,200 a year and $200 a square foot",
    "in 2026 the city will", "Resolution 12, a resolution approving", "resolution 46 2025 26 a resolution approving",
    "zero yes thirteen no zero abstain ordinance 42 fails councilman street you're recognized",
    "They would try to come up further up 7 Mile Ferry Road, and", "Seven Mile Ferry Road",
    "approximately 250 feet north of Dover Road", "we're adding 80 cars to that road", "a substandard 16 foot wide road",
    "The 2040 Spring Creek Parkway background traffic projections", "Mr. Pitts did that in 2020 with the street improvement",
    "parcels north of Highway 76 and east of Hornbuckle Road", "Lafayette Road highway 374 and Garrettsburg Road",
    "between 1,500 and 2,000 square feet", "1.1 mile to the one point", "i can drive 20 minutes the other way",
    "council ward number 11 it's in the st. Bethlehem planning", "the paving contract on Main Street",
    "is city court going", "and this was voted on in 1977 by the way", "the 13th of November at 9 a.m.",
    "Resolution 3620 2526, a resolution", "the city website was from 2022 2022 it",
])
def test_numbers_that_are_not_addresses_are_left(text):
    assert privacy.mask(text) == text


def test_an_address_split_over_two_lines_is_masked_on_both_and_times_kept():
    segs = [[10.0, 12.5, "Thank you. My address is 701"], [12.5, 15.0, "Anita Court, Clarksville, Tennessee."],
            [15.0, 18.0, "First of all, thank you."]]
    out, changed = privacy.mask_segments(segs)
    assert changed == [0, 1]
    assert out[0] == [10.0, 12.5, f"Thank you. My address is {A}"]
    assert out[1] == [12.5, 15.0, f"{A}, Clarksville, Tennessee."]
    assert out[2] is segs[2]
    assert privacy.mask_segments([[0, 1, "nothing here"]]) == ([[0, 1, "nothing here"]], [])


def test_the_qa_rule_agrees_with_the_masker_on_every_committed_line():
    """The restated rule in qa/site_checks.py finds nothing in any masked committed line (else the masker missed one
    the check would catch), and finds an address or phone number in at least the lines the review named."""
    found = 0
    for f in sorted(TRANSCRIPTS.glob("2*.json")):
        segs = json.loads(f.read_text(encoding="utf-8"))["segments"]
        out, changed = privacy.mask_segments(segs)
        found += len(changed)
        for s in out:
            assert site_checks.private_details(s[2]) == [], (f.name, s)
    assert found >= 77      # the security review counted 77 lines that pair a name with a home address
    assert site_checks.private_details("My address is 701 Anita Court, Clarksville")
    assert site_checks.private_details("Calvin Ligon, 951 Crabapple Court.")


# ------------------------------------------------------------------------------------------------------- the pages

ADDRESS_LINES = [
    (50.0, 55.0, "Thank you. Jeremy Wright. My address is 701"),
    (55.0, 60.0, "Anita Court, Clarksville, Tennessee. Call me at 931-555-0142."),
    (60.0, 65.0, "councilman Smith you're recognized thank you I live at 951 Crabapple Court and"),
    (65.0, 70.0, "ordinance 98-2025-26 costs $1,200 in 2026 under Resolution 12"),
]


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    from test_transcripts import CFG, LISTING, MEETING, SEGMENTS, city_facts, ctx, kind_of, raw_transcript, write_raw
    from test_council_pages import subset
    facts = city_facts()
    sub = subset(facts, ("2019-01-03-regular", MEETING))
    d = tmp_path_factory.mktemp("city")
    (d / "facts.json").write_text(json.dumps(sub), encoding="utf-8")
    city = ROOT / "data" / "localities" / "clarksville-tn"
    wards = [w for w in json.loads((city / "wards.json").read_text()) if w["meeting_id"] in ("2019-01-03-regular", MEETING)]
    (d / "wards.json").write_text(json.dumps(wards), encoding="utf-8")
    m = next(x for x in sub["meetings"] if x["id"] == MEETING)
    write_raw(d / "raw", raw_transcript(m, SEGMENTS + ADDRESS_LINES))
    ctx.import_dir(d / "raw", sub, d / "transcripts", kind_of, LISTING)
    cfg = {**CFG, "facts_path": d / "facts.json", "wards_path": d / "wards.json"}
    out = tmp_path_factory.mktemp("site") / "build" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, councils=[cfg])
    cs = [{"slug": "city", "prefix": "city/", "facts": sub, "transcripts_dir": d / "transcripts"}]
    return out, cs, MEETING, m["video_url"], len(SEGMENTS)


def test_transcript_page_masks_and_keeps_the_time_links(site):
    out, cs, mid, video, n = site
    page = (out / "city" / "transcripts" / f"{mid}.html").read_text(encoding="utf-8")
    for raw in ("701", "Anita Court", "951 Crabapple", "931-555-0142"):
        assert raw not in page
    assert page.count("[address omitted; hear it in the video at this time]") == 3
    assert "[phone number omitted; hear it in the video at this time]" in page
    assert "ordinance 98-2025-26 costs $1,200 in 2026 under Resolution 12" in page
    for i, (start, _, _) in enumerate(ADDRESS_LINES):
        href = f"{video}#t={int(start)}"
        assert re.search(rf'<li id="s{n + i}"[^>]*><a class="tx-time" data-ext="video" href="{re.escape(href)}"', page)
    head = page.split("</head>")[0]
    assert '<meta name="robots" content="noindex">' in head
    assert re.search(r'<p class="privacy-note">Street addresses and phone numbers spoken at the meeting are left out of '
                     r'this text; the video has them\. To ask for a removal or a correction, use <a href="\.\./\.\./report'
                     r'\.html">Report an error</a>\.</p>', page)
    # only transcript pages are noindex
    assert 'name="robots"' not in (out / "city" / "members" / "city-wanda-smith.html").read_text(encoding="utf-8")
    assert 'name="robots"' not in (out / "index.html").read_text(encoding="utf-8")


def test_call_on_excerpts_are_masked_too(site):
    out, *_ = site
    smith = (out / "city" / "members" / "city-wanda-smith.html").read_text(encoding="utf-8")
    assert "951 Crabapple" not in smith and "I live at [address omitted; hear it in the video at this time] and" in smith


def test_load_reports_the_masked_line_count(site):
    from sitegen.build import load_facts
    out, cs, mid, *_ = site
    folder = cs[0]["transcripts_dir"]
    t = tx.load(folder.parent / "facts.json", load_facts(folder.parent / "facts.json"))[mid]
    assert t["masked_segments"] == 3


def test_site_check_passes_and_catches_a_leak(site, tmp_path):
    out, cs, mid, *_ = site
    problems, note = site_checks.check_private_details(out, cs)
    assert problems == [] and "2 committed transcript lines" in note   # line 1 and line 2 (line 0 alone holds no address)
    problems, _ = site_checks.check_transcripts(out, cs)
    assert problems == []
    copy = tmp_path / "site"
    shutil.copytree(out, copy)
    # an unmasked address in a transcript line
    p = copy / "city" / "transcripts" / f"{mid}.html"
    body = p.read_text(encoding="utf-8")
    p.write_text(body.replace("Thank you. Jeremy Wright. My address is [address omitted; hear it in the video at this time]",
                              "Thank you. Jeremy Wright. My address is 701 Anita Court", 1), encoding="utf-8")
    problems, _ = site_checks.check_private_details(copy, cs)
    assert any("transcript text shows '701 Anita Court'" in x for x in problems)
    # a committed line copied into the export or the search index, outside any data-transcript text
    (copy / "data").mkdir(exist_ok=True)
    (copy / "data" / "extra.json").write_text(json.dumps({"t": ADDRESS_LINES[2][2]}), encoding="utf-8")
    js = copy / "static" / "search-index.js"
    js.write_text(js.read_text(encoding="utf-8") + "\n// " + ADDRESS_LINES[1][2], encoding="utf-8")
    problems, _ = site_checks.check_private_details(copy, cs)
    assert any(x.startswith("data/extra.json: carries an unmasked transcript line") for x in problems)
    assert any(x.startswith("static/search-index.js: carries an unmasked transcript line") for x in problems)
    # the noindex and the privacy line are required on every transcript page
    p.write_text(body.replace('<meta name="robots" content="noindex">', "").replace('class="privacy-note"', 'class="x"'),
                 encoding="utf-8")
    problems, _ = site_checks.check_transcripts(copy, cs)
    assert any("robots noindex" in x for x in problems) and any("privacy line" in x for x in problems)
