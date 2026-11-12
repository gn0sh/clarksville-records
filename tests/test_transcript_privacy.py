"""Private details in transcript text (security review M1, privacy/transcript-private-addresses; collector/privacy.py).

Rules under test: street addresses and phone numbers are masked everywhere in transcript text before anything is
shown or quoted (transcript pages, call-on excerpts on member pages); never ordinance numbers, dates, dollar amounts or
resolution numbers; an address split over two lines is found; the line keeps its time link; transcript pages carry
robots noindex and one plain line linking the site's Report an error page; the import masks before it writes and
`remask` re-masks committed JSON (idempotent); site load fails on a committed line that is not masked; qa.site_checks
fails a build that shows an address in transcript text, holds a committed line that is not masked, or carries any
committed transcript line in data/ or the search index. Every example is synthetic."""
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
    ("or call the hotline at 9 3 1 5 5 5 0 1 0 8 the hotline", f"or call the hotline at {P} the hotline"),
    ("is 5 5 5 0 1 0 9. this concludes", f"is {P}. this concludes"),
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
    "the vote was 7 0 0 and the motion carries", "items 1 2 3 4 5 and 6 on consent", "page 1 2 3 4 5 6 7.5 inches",
])
def test_numbers_that_are_not_addresses_are_left(text):
    assert privacy.mask(text) == text


_RUN = "twenty-two and " * 60


@pytest.mark.parametrize("text", [
    _RUN, _RUN.rstrip(), _RUN + "Sample", _RUN + "Sample Court", "I live at " + _RUN, "my address is " + _RUN + "x",
    " ".join(["five"] * 60), " ".join(["five"] * 60) + " Example Street", "call " + " ".join(["nine"] * 60) + " now",
    " ".join(["5"] * 60), " ".join(["5"] * 60) + ".5", "1 " * 60 + "Example Street",
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


@pytest.mark.parametrize("unit", ["1 and ", "twenty-two and ", "1, "])
def test_long_joined_number_lists_finish_quickly(unit):
    """privacy/mask-regex-redos (security review L3): the join of house numbers ("1100 and 1110 Sample Road") is bounded,
    so 4000 repetitions of a joinable number with no street after it finish in well under half a second, in the masker
    and in the site check's restated rule."""
    import time
    text = unit * 4000
    for f in (privacy.spans, privacy.mask, site_checks.private_details):
        t0 = time.perf_counter()
        f(text)
        assert time.perf_counter() - t0 < 0.5, f.__qualname__


def test_the_bounded_join_still_masks_a_list_of_four_house_numbers():
    assert privacy.mask("we own 1100 and 1110 Sample Road") == f"we own {A}"
    assert privacy.mask("lots 1, 3, 5 and 7 Example Street") == f"lots {A}"


def test_an_address_split_over_two_lines_is_masked_on_both_and_times_kept():
    segs = [[10.0, 12.5, "Thank you. My address is 418"], [12.5, 15.0, "Example Court, Clarksville, Tennessee."],
            [15.0, 18.0, "First of all, thank you."]]
    out, changed = privacy.mask_segments(segs)
    assert changed == [0, 1]
    assert out[0] == [10.0, 12.5, f"Thank you. My address is {A}"]
    assert out[1] == [12.5, 15.0, f"{A}, Clarksville, Tennessee."]
    assert out[2] is segs[2]
    assert privacy.mask_segments([[0, 1, "nothing here"]]) == ([[0, 1, "nothing here"]], [])


def test_committed_transcripts_are_masked_at_rest():
    """Every committed transcript segment is already masked: masking changes no line, and the site check's restated
    rule finds nothing in any line or in the lines joined (privacy/transcript-private-addresses, decision (b))."""
    files = sorted(TRANSCRIPTS.glob("2*.json"))
    assert files
    for f in files:
        segs = json.loads(f.read_text(encoding="utf-8"))["segments"]
        # counts computed outside the assert (pytest prints the operands of a failing one), so a failure names the
        # file and never prints the matched text (privacy/test-output-prints-match)
        joined = " ".join(s[2] for s in segs)
        n_changed = len(privacy.mask_segments(segs)[1])
        n_spans = len(privacy.spans(joined))
        n_lines = sum(1 for s in segs if site_checks.private_details(s[2]))
        n_joined = len(site_checks.private_details(joined))
        assert n_changed == 0, f"{f.name}: {n_changed} segments not masked"
        assert n_spans == 0, f"{f.name}: {n_spans} masker spans"
        assert n_lines == 0, f"{f.name}: {n_lines} segments match the site check's rule"
        assert n_joined == 0, f"{f.name}: {n_joined} matches in the joined text"


def test_the_qa_rule_agrees_with_the_masker():
    """The restated rule in qa/site_checks.py finds nothing in a masked committed line (else the masker missed one the
    check would catch), and finds the synthetic addresses and phone numbers the masker masks."""
    for f in sorted(TRANSCRIPTS.glob("2*.json")):
        out, _ = privacy.mask_segments(json.loads(f.read_text(encoding="utf-8"))["segments"])
        for i, s in enumerate(out):
            n = len(site_checks.private_details(s[2]))      # a count, never the text (privacy/test-output-prints-match)
            assert n == 0, f"{f.name} segment {i}"
    assert site_checks.private_details("My address is 418 Example Court, Clarksville")
    assert site_checks.private_details("Sam Sample, 236 Fixture Court.")
    assert site_checks.private_details("call (931) 555-0104 today")
    assert site_checks.private_details("the hotline at 9 3 1 5 5 5 0 1 0 8 the hotline")


# ------------------------------------------------------------------------------------- masked at import and at rest

def _import(tmp_path, lines):
    from collector import transcripts as ctx
    from test_transcripts import LISTING, MEETING, city_facts, kind_of, raw_transcript, write_raw
    facts = city_facts()
    m = next(x for x in facts["meetings"] if x["id"] == MEETING)
    write_raw(tmp_path / "raw", raw_transcript(m, lines))
    log = ctx.import_dir(tmp_path / "raw", facts, tmp_path / "out", kind_of, LISTING)
    return log, tmp_path / "out" / f"{MEETING}.json"


def test_the_import_masks_before_it_writes(tmp_path):
    log, out = _import(tmp_path, ADDRESS_LINES)
    assert log["imported"][0]["masked_segments"] == 3
    text = out.read_text(encoding="utf-8")
    for raw in ("is 418", "Example Court", "236 Fixture", "931-555-0142"):
        assert raw not in text
    segs = json.loads(text)["segments"]
    assert [s[:2] for s in segs] == [[a, b] for a, b, _ in ADDRESS_LINES]     # times and count kept
    assert segs[0][2] == f"Thank you. Pat Example. My address is {A}"
    assert segs[3][2] == ADDRESS_LINES[3][2]                                  # nothing else changes
    assert privacy.mask_segments(segs)[1] == []                               # masked at rest


def test_the_import_refuses_a_file_still_matching_after_masking(tmp_path, monkeypatch):
    monkeypatch.setattr(privacy, "mask_segments", lambda segs: (list(segs), []))     # a masker that misses
    log, out = _import(tmp_path, ADDRESS_LINES)
    assert log["imported"] == [] and not out.exists()
    assert "still holds an address or phone number" in log["skipped"][0]["why"]
    assert "418" not in json.dumps(log)                                      # the reason never quotes the text


def test_mask_is_idempotent():
    for text, _ in [(t[2], None) for t in ADDRESS_LINES] + [("call (931) 555-0104 or 555-0105 today", None),
                                                           ("my address is four oh eight Example Court", None)]:
        once = privacy.mask(text)
        assert privacy.mask(once) == once
    segs = [list(x) for x in ADDRESS_LINES]
    once, _ = privacy.mask_segments(segs)
    assert privacy.mask_segments(once) == (once, [])


def test_remask_rewrites_committed_json_and_a_second_run_changes_nothing(tmp_path):
    from collector import transcripts as ctx
    folder = tmp_path / "transcripts"
    folder.mkdir()
    raw = {"created_at": "2026-11-09T21:17:07Z", "event_id": "2618", "event_name": "Regular Session",
           "matched_by": "video_url", "meeting_id": "2026-02-05-regular", "model": "small.en",
           "model_version": "faster-whisper 1.2.1", "source_file": "2026-02-05_2618.json", "source_sha256": "0" * 64,
           "start": "2026-02-05", "video_url": "https://example.invalid/v.mp4",
           "segments": [[a, b, t] for a, b, t in ADDRESS_LINES]}
    (folder / "2026-02-05-regular.json").write_text(ctx.render(raw), encoding="utf-8")
    log = ctx.remask(folder)
    assert [x["file"] for x in log["remasked"]] == ["2026-02-05-regular.json"] and log["refused"] == []
    assert log["remasked"][0]["masked_segments"] == 3
    first = {p.name: p.read_bytes() for p in folder.iterdir()}
    t = json.loads(first["2026-02-05-regular.json"])
    assert [s[:2] for s in t["segments"]] == [[a, b] for a, b, _ in ADDRESS_LINES]
    assert {k: v for k, v in t.items() if k != "segments"} == {k: v for k, v in raw.items() if k != "segments"}
    assert json.loads(first["index.json"])["2026-02-05-regular"]["segments"] == len(ADDRESS_LINES)
    log = ctx.remask(folder)
    assert log["remasked"] == [] and len(log["unchanged"]) == 1
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == first
    # the command line: exit 0, and exit 1 with the file left as it is when one is refused
    assert ctx.main(["remask", "--dir", str(folder)]) == 0
    (folder / "broken.json").write_text("{not json", encoding="utf-8")
    assert ctx.main(["remask", "--dir", str(folder)]) == 1
    assert (folder / "broken.json").read_text(encoding="utf-8") == "{not json"


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


def test_load_fails_on_a_committed_line_that_is_not_masked(site, tmp_path):
    from sitegen.build import load_facts
    out, cs, mid, *_ = site
    folder = cs[0]["transcripts_dir"]
    t = tx.load(folder.parent / "facts.json", load_facts(folder.parent / "facts.json"))[mid]
    assert t["masked_segments"] == 0          # the import masked them: nothing left for load to change
    # a committed transcript with a raw address (data not masked at rest): load raises, never quoting the text
    d = tmp_path / "city"
    shutil.copytree(folder.parent, d)
    f = d / "transcripts" / f"{mid}.json"
    body = json.loads(f.read_text(encoding="utf-8"))
    body["segments"][-2][2] = "I live at 236 Fixture Court and"
    f.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(tx.TranscriptLoadError) as exc:
        tx.load(d / "facts.json", load_facts(d / "facts.json"))
    assert "1 committed lines hold an address or phone number" in str(exc.value) and "remask" in str(exc.value)
    assert "236" not in str(exc.value) and "Fixture" not in str(exc.value)     # build.py turns it into a BuildError


def _cs_with(cs, tmp_path, segments):
    """cs with a synthetic committed transcripts folder holding one file of these segments."""
    folder = tmp_path / "tx"
    folder.mkdir()
    (folder / "2026-01-01-regular.json").write_text(json.dumps({"segments": segments}), encoding="utf-8")
    return [{**cs[0], "transcripts_dir": folder}]


def test_site_check_passes_and_catches_a_leak(site, tmp_path):
    out, cs, mid, *_ = site
    problems, note = site_checks.check_private_details(out, cs)
    n_lines = len(json.loads((cs[0]["transcripts_dir"] / f"{mid}.json").read_text(encoding="utf-8"))["segments"])
    assert problems == [] and f"{n_lines} committed transcript lines checked at rest" in note
    problems, _ = site_checks.check_transcripts(out, cs)
    assert problems == []
    copy = tmp_path / "site"
    shutil.copytree(out, copy)
    # (a) an unmasked address in a transcript line, and in a call-on excerpt on a member page
    p = copy / "city" / "transcripts" / f"{mid}.html"
    body = p.read_text(encoding="utf-8")
    p.write_text(body.replace("Thank you. Pat Example. My address is [address omitted; hear it in the video at this time]",
                              "Thank you. Pat Example. My address is 418 Example Court", 1), encoding="utf-8")
    member = copy / "city" / "members" / "city-wanda-smith.html"
    mbody = member.read_text(encoding="utf-8")
    assert "I live at [address omitted; hear it in the video at this time] and" in mbody
    member.write_text(mbody.replace("I live at [address omitted; hear it in the video at this time] and",
                                    "I live at 236 Fixture Court and"), encoding="utf-8")
    problems, _ = site_checks.check_private_details(copy, cs)
    assert any(x.startswith(f"city/transcripts/{mid}.html: transcript text #") for x in problems)
    assert any(x.startswith("city/members/city-wanda-smith.html: transcript text #") for x in problems)
    assert not any("418" in x or "Example Court" in x or "236" in x for x in problems)     # never the text
    # (c) any committed transcript line (masked or not) copied into the export or the search index
    (copy / "data").mkdir(exist_ok=True)
    masked = json.loads((cs[0]["transcripts_dir"] / f"{mid}.json").read_text(encoding="utf-8"))["segments"]
    (copy / "data" / "extra.json").write_text(json.dumps({"t": "x " + masked[-1][2]}), encoding="utf-8")
    js = copy / "static" / "search-index.js"
    js.write_text(js.read_text(encoding="utf-8") + "\n// " + masked[-3][2], encoding="utf-8")
    problems, _ = site_checks.check_private_details(copy, cs)
    assert any(x.startswith("data/extra.json: carries 1 committed transcript lines") for x in problems)
    assert any(x.startswith("static/search-index.js: carries 1 committed transcript lines") for x in problems)
    assert "static/search-index.js: carries 2 transcript placeholders (transcript text outside the pages)" in problems
    assert not any(x.startswith("data/extra.json: carries") and "placeholders" in x for x in problems)
    assert not any("omitted" in x for x in problems)
    # (b) a committed transcript that is not masked at rest: a raw line, and an address split over two lines
    # a line that is also a string of the committed source data (an item title read aloud) is not a needle
    title = json.loads((ROOT / "data" / "facts.json").read_text(encoding="utf-8"))["items"][0]["title"]
    assert len(" ".join(title.split())) >= site_checks.NEEDLE_MIN
    titled = _cs_with(cs, tmp_path, [[0, 1, " ".join(title.split())]])
    (copy / "data" / "extra.json").write_text(json.dumps({"t": title}), encoding="utf-8")
    js.write_text(js.read_text(encoding="utf-8").split("\n// ")[0], encoding="utf-8")
    problems, note = site_checks.check_private_details(copy, titled)
    assert not any(x.startswith("data/extra.json") for x in problems) and "(1 more are also source text)" in note
    (tmp_path / "tx").rename(tmp_path / "tx0")
    raw = _cs_with(cs, tmp_path, [[0, 1, "Thank you. I live at 236 Fixture Court and"], [1, 2, "nothing here at all"]])
    problems, _ = site_checks.check_private_details(out, raw)
    assert problems == ["city/transcripts/2026-01-01-regular.json#s0: committed transcript line holds 1 address or phone "
                        "number matches (not masked at rest)"]
    (tmp_path / "tx").rename(tmp_path / "tx1")
    split = _cs_with(cs, tmp_path, [[0, 1, "Thank you. My address is 418"], [1, 2, "Example Court, Clarksville."]])
    problems, _ = site_checks.check_private_details(out, split)
    assert problems == ["city/transcripts/2026-01-01-regular.json: an address or phone number split over two committed "
                        "lines (not masked at rest)"]
    # the noindex and the privacy line are required on every transcript page
    p.write_text(body.replace('<meta name="robots" content="noindex">', "").replace('class="privacy-note"', 'class="x"'),
                 encoding="utf-8")
    problems, _ = site_checks.check_transcripts(copy, cs)
    assert any("robots noindex" in x for x in problems) and any("privacy line" in x for x in problems)
