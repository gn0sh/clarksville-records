"""Private details in transcript text (security review M1, privacy/transcript-private-addresses; collector/privacy.py).

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
from collector import privacy
from sitegen import transcripts as tx
from sitegen.build import build

A, P = privacy.ADDRESS_MASK, privacy.PHONE_MASK
TRANSCRIPTS = ROOT / "data" / "localities" / "clarksville-tn" / "transcripts"


# ------------------------------------------------------------------------------------------------- the masking rule

@pytest.mark.parametrize("text, masked", [
    # synthetic lines (invented names, placeholder streets, 555-01xx numbers), one per rule: never real transcript text
    ("Yeah, everyone. Pat Example. My address is 418 Example Court, Clarksville, Tennessee, 37040.",
     f"Yeah, everyone. Pat Example. My address is {A}, Clarksville, Tennessee, 37040."),
    ("you have five minutes. Sam Sample, 236 Fixture Court. Just looking",
     f"you have five minutes. Sam Sample, {A}. Just looking"),
    # initials in the street name; an ordinal street name
    ("My name is Lee Example. I live at 312 J.Q. Sample Boulevard. It's", f"My name is Lee Example. I live at {A}. It's"),
    ("I'm Kim B. Sample. I live on 205 47th Street. In that lot", f"I'm Kim B. Sample. I live on {A}. In that lot"),
    ("my name is Alex Fixture I live at 580 Example Drive I've called Clarksville",
     f"my name is Alex Fixture I live at {A} I've called Clarksville"),
    # a cued house number with no suffix
    ("sir name is jo sample i live at 640 samplewood since 2003.", f"sir name is jo sample i live at {A} since 2003."),
    ("I live at 515 so I'm right next to it", f"I live at {A} so I'm right next to it"),
    # Whisper splits: a spelled word then digits, "or" for "oh", digits split in two
    ("Um, I stayed at nine 14 Example street and where he", f"Um, I stayed at {A} and where he"),
    ("for 62 years from six or six sample street to a 14 Example street", f"for 62 years from {A} to a {A}"),
    ("will be updated at 10 42 fixture drive from 01 office", f"will be updated at {A} from 01 office"),
    # two house numbers joined by "and"
    ("on property located at 1100 and 1110 Sample Road from R1", f"on property located at {A} from R1"),
    ("I reside at 77 and 79 Fixture Lane with my family", f"I reside at {A} with my family"),
    ("I'm Robin Example. I live at. 1020 Sample Station and 1130 North Fixture Road.",
     f"I'm Robin Example. I live at. {A} and {A}."),
    # spelled-out house numbers
    ("my address is four oh eight Example Court", f"my address is {A}"),
    ("the lot located at one two three four five six seven on the corner", f"the lot located at {A} on the corner"),
    # phone numbers, every form: every one is masked, official lines included
    ("in contact with the director is 931-555-0101. Again,", f"in contact with the director is {P}. Again,"),
    ("a non-emergency number that is 931. 555. 0102. Our next", f"a non-emergency number that is {P}. Our next"),
    ("called the hotline and that said 931 555 0103. And", f"called the hotline and that said {P}. And"),
    ("call (931) 555-0104 or 555-0105 today", f"call {P} or {P} today"),
    ("or text 931.555.0107 any time", f"or text {P} any time"),
    ("my number is nine three one five five five zero one zero six", f"my number is {P}"),
])
def test_addresses_and_phone_numbers_are_masked(text, masked):
    assert privacy.mask(text) == masked


@pytest.mark.parametrize("text", [
    # synthetic lines that must stay as they are
    "Ordinance 17-2025-26, second reading, an ordinance amending the zoning code",
    "Ordinance 104-2023-24 for a grant award",
    "the bill was $1,400 a year and $300 a square foot",
    "in 2027 the city will", "Resolution 14, a resolution approving", "resolution 51 2025 26 a resolution approving",
    "zero yes twelve no zero abstain ordinance 37 fails councilman street you're recognized",
    "They would try to come up further up 9 Mile Example Road, and", "Nine Mile Example Road",
    "approximately 300 feet north of Sample Road", "we're adding 90 cars to that road", "a substandard 18 foot wide road",
    "The 2045 Example Creek Parkway background traffic projections",
    "Mr. Sample did that in 2021 with the street improvement",
    "parcels north of Highway 79 and east of Fixture Road", "Example Road highway 380 and Sample Road",
    "between 1,600 and 2,500 square feet", "1.3 mile to the one point", "i can drive 25 minutes the other way",
    "council ward number 12 it's in the st. Example planning", "the paving contract on Sample Street",
    "will city court be open", "and this was voted on in 1983 by the way", "the 14th of March at 8 a.m.",
    "Resolution 3710 2526, a resolution", "the city website was from 2023 2023 it",
    "we went to the four city court sessions", "item 6 Example Street paving", "district 5 Sample Road widening",
])
def test_numbers_that_are_not_addresses_are_left(text):
    assert privacy.mask(text) == text


_RUN = "twenty-two and " * 60


@pytest.mark.parametrize("text", [
    _RUN, _RUN.rstrip(), _RUN + "Sample", _RUN + "Sample Court", "I live at " + _RUN, "my address is " + _RUN + "x",
    " ".join(["five"] * 60), " ".join(["five"] * 60) + " Example Street", "call " + " ".join(["nine"] * 60) + " now",
])
def test_long_number_word_runs_finish_quickly(text):
    """privacy/mask-regex-redos: a run of spelled-out numbers with no street (or a long spelled digit run) cannot make
    the masker or the site check's restated rule backtrack exponentially."""
    import time
    for f in (privacy.spans, privacy.mask, site_checks.private_details):
        t0 = time.perf_counter()
        f(text)
        assert time.perf_counter() - t0 < 0.5, f.__qualname__
    t0 = time.perf_counter()
    privacy.mask_segments([[0.0, 1.0, text], [1.0, 2.0, text]])
    assert time.perf_counter() - t0 < 0.5


def test_an_address_split_over_two_lines_is_masked_on_both_and_times_kept():
    segs = [[10.0, 12.5, "Thank you. My address is 418"], [12.5, 15.0, "Example Court, Clarksville, Tennessee."],
            [15.0, 18.0, "First of all, thank you."]]
    out, changed = privacy.mask_segments(segs)
    assert changed == [0, 1]
    assert out[0] == [10.0, 12.5, f"Thank you. My address is {A}"]
    assert out[1] == [12.5, 15.0, f"{A}, Clarksville, Tennessee."]
    assert out[2] is segs[2]
    assert privacy.mask_segments([[0, 1, "nothing here"]]) == ([[0, 1, "nothing here"]], [])


def test_the_qa_rule_agrees_with_the_masker():
    """The restated rule in qa/site_checks.py finds nothing in a masked committed line (else the masker missed one the
    check would catch), and finds the synthetic addresses and phone numbers the masker masks."""
    for f in sorted(TRANSCRIPTS.glob("2*.json")):
        out, _ = privacy.mask_segments(json.loads(f.read_text(encoding="utf-8"))["segments"])
        for i, s in enumerate(out):
            assert site_checks.private_details(s[2]) == [], (f.name, i)
    assert site_checks.private_details("My address is 418 Example Court, Clarksville")
    assert site_checks.private_details("Sam Sample, 236 Fixture Court.")
    assert site_checks.private_details("call (931) 555-0104 today")


# ------------------------------------------------------------------------------------------------------- the pages

ADDRESS_LINES = [
    (50.0, 55.0, "Thank you. Pat Example. My address is 418"),
    (55.0, 60.0, "Example Court, Clarksville, Tennessee. Call me at 931-555-0142."),
    (60.0, 65.0, "councilman Smith you're recognized thank you I live at 236 Fixture Court and"),
    (65.0, 70.0, "ordinance 17-2025-26 costs $1,400 in 2027 under Resolution 14"),
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
    for raw in ("is 418", "Example Court", "236 Fixture", "931-555-0142"):
        assert raw not in page
    assert page.count("[address omitted; hear it in the video at this time]") == 3
    assert "[phone number omitted; hear it in the video at this time]" in page
    assert "ordinance 17-2025-26 costs $1,400 in 2027 under Resolution 14" in page
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
    assert "236 Fixture" not in smith and "I live at [address omitted; hear it in the video at this time] and" in smith


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
    p.write_text(body.replace("Thank you. Pat Example. My address is [address omitted; hear it in the video at this time]",
                              "Thank you. Pat Example. My address is 418 Example Court", 1), encoding="utf-8")
    problems, _ = site_checks.check_private_details(copy, cs)
    assert any("transcript text shows '418 Example Court'" in x for x in problems)
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
