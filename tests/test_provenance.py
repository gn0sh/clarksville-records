"""Problem family `provenance` (architecture, "Invariant: derived vs stated"): mechanical checks 1-4, plus the
wording rules of the seat, landing, officials, search and About pages. Fixture data only, except check 4, which runs
on the committed data/facts.json and the locality's seats.yml."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from qa import site_checks
from sitegen import config, views
from sitegen.seats import Seats, SeatsError, load_rows

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_SEATS = ROOT / "site" / "fixtures" / "seats.sample.yml"
OBSERVED = {"official_id": "x", "seat": "district-1", "dates": "observed", "start": "2024-11-04", "end": None,
            "source": "https://example.org/a.pdf#page=1", "last_source": "https://example.org/b.pdf#page=2"}
SOURCED = {"official_id": "y", "seat": "county-mayor", "dates": "sourced", "printed": "2022-2026",
           "start": "2022-09-01", "end": None, "source": "https://example.org/c.pdf#page=6"}


def write_rows(tmp_path, rows):
    p = tmp_path / "seats.yml"
    p.write_text(yaml.safe_dump(rows), encoding="utf-8")
    return p


# --- check 1: loader ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("row", [
    {k: v for k, v in OBSERVED.items() if k != "dates"},
    {**OBSERVED, "dates": "guessed"},
    {k: v for k, v in OBSERVED.items() if k != "last_source"},
    {**OBSERVED, "last_source": "http://example.org/b.pdf#page=2"},
    {k: v for k, v in SOURCED.items() if k != "printed"},
    {**SOURCED, "printed": "  "},
])
def test_loader_rejects_rows_that_break_the_shape(tmp_path, row):
    with pytest.raises(SeatsError):
        load_rows(write_rows(tmp_path, [row]))


def test_loader_keeps_the_shape(tmp_path):
    rows = load_rows(write_rows(tmp_path, [OBSERVED, SOURCED]))
    assert rows[0]["dates"] == "observed" and rows[0]["last_source"].endswith("#page=2")
    assert rows[1]["dates"] == "sourced" and rows[1]["printed"] == "2022-2026"


def test_the_committed_roster_loads():
    rows = load_rows(config.SEATS_PATH)
    assert rows and all(r["dates"] in ("observed", "sourced") for r in rows)


# --- dates_text: the one wording ---------------------------------------------------------------------------------

def test_dates_text_wording():
    s = Seats([], {}, "2026-05-11")
    obs = {**OBSERVED, "end": "2022-08-08", "start": "2020-03-09"}
    assert s.dates_text(obs) == "seen in roll calls 2020-03-09 to 2022-08-08"
    assert s.dates_text({**OBSERVED, "start": "2022-09-12"}) == (
        "seen in roll calls from 2022-09-12 to 2026-05-11, the latest meeting collected")
    assert s.dates_text({**OBSERVED, "official_id": None, "start": "2024-01-06"}) == (
        "shown as vacant in roll calls from 2024-01-06 to 2026-05-11")
    assert s.dates_text(SOURCED) == "term 2022-2026, as the source prints it"
    assert s.basis({**OBSERVED, "current": True}) == "Current: in the roll calls of the latest meeting collected, 2026-05-11"


# --- check 2: no bare seat dates in view contexts ------------------------------------------------------------------

def _keys(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield path + "/" + str(k), k
            yield from _keys(v, path + "/" + str(k))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _keys(v, f"{path}[{i}]")


@pytest.fixture(scope="module")
def ix(facts):
    return views.Index(facts, load_rows(FIXTURE_SEATS))


def test_view_contexts_carry_no_seat_start_or_end(ix):
    contexts = {"officials": views.officials_page(ix), "landing": views.landing(ix, None),
                "search": views.search_index(ix), "search_page": views.search_page(ix)}
    for n in range(1, config.SITE["district_count"] + 1):
        contexts[f"district {n}"] = views.district(n, ix, None)
    for name, ctx in contexts.items():
        bad = [p for p, k in _keys(ctx) if k in ("start", "end", "eff")]
        assert bad == [], (name, bad[:5])


# --- check 3: the built pages and the search index ---------------------------------------------------------------

def test_built_fixture_site_passes_check_provenance(built, facts):
    pages = {f.relative_to(built).as_posix(): site_checks.parse(f) for f in built.rglob("*.html")}
    problems, note = site_checks.check_provenance(built, pages, facts, site_checks.read_roster(FIXTURE_SEATS),
                                                  site_checks._site_cfg())
    assert problems == [], problems


@pytest.mark.parametrize("planted", [
    '<p class="holder-row">A. Example, from 2024-10-07</p>',
    '<span class="seat">District 1, 2024-10-07 to 2024-11-04</span>',
    '<p>Held this seat</p>',
    '<p>Current district lines, in use since 2024</p>',
    '<table class="holders"><tr><td>2024-10-07 to present</td></tr></table>',
])
def test_check_provenance_catches_a_planted_term_date(tmp_path, built, facts, planted):
    site = tmp_path / "site"
    shutil.copytree(built, site)
    f = site / "districts" / "01.html"
    f.write_text(f.read_text(encoding="utf-8").replace("</main>", planted + "</main>"), encoding="utf-8")
    pages = {p.relative_to(site).as_posix(): site_checks.parse(p) for p in site.rglob("*.html")}
    problems, _ = site_checks.check_provenance(site, pages, facts, site_checks.read_roster(FIXTURE_SEATS),
                                               site_checks._site_cfg())
    assert problems


def test_check_provenance_bans_the_cutover_value(tmp_path, built, facts):
    site = tmp_path / "site"
    shutil.copytree(built, site)
    f = site / "about.html"
    f.write_text(f.read_text(encoding="utf-8").replace("</main>", f"<p>{config.SITE['lines_effective']}</p></main>"),
                 encoding="utf-8")
    pages = {p.relative_to(site).as_posix(): site_checks.parse(p) for p in site.rglob("*.html")}
    problems, _ = site_checks.check_provenance(site, pages, facts, [], site_checks._site_cfg())
    assert any("banned" in p for p in problems)


def test_search_index_seat_strings_are_worded(built):
    raw = (built / "static" / "search-index.js").read_text(encoding="utf-8")
    ix = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    labels = {o["id"]: o["label"] for o in ix["officials"]}
    assert labels["a-example"] == "Example, A. (District 1)"
    assert labels["b-sample"] == "Sample, B. (District 2 (seen in roll calls 2024-11-04 to 2024-11-04))"
    assert labels["e-fixture"] == "Fixture, E."
    for t in [o["label"] for o in ix["officials"]] + ix["seat_labels"]:
        assert site_checks.dates_worded(t) == [], t


# --- check 4: cutover immaterial, on the committed data --------------------------------------------------------------

def test_cutover_is_immaterial_on_committed_data():
    facts = json.loads((ROOT / "data" / "facts.json").read_text(encoding="utf-8"))
    eff = config.SITE["lines_effective"]
    by_id = {m["id"]: m["date"] for m in facts["meetings"]}
    rc_dates = sorted({by_id[r["meeting_id"]] for r in facts["roll_calls"]})
    lo = max(d for d in rc_dates if d < eff)
    hi = min(d for d in rc_dates if d >= eff)
    assert [d for d in by_id.values() if lo < d < hi] == []
    ix = views.Index(facts, load_rows(config.SEATS_PATH))
    assert views.cutover_meetings(ix) == (lo, hi)
    for r in load_rows(config.SEATS_PATH):
        if r["dates"] != "observed" or not r["seat"].startswith("district-"):
            continue
        if r["lines"] == "old":
            assert r["end"] is not None and r["end"] <= lo, r
        else:
            assert r["start"] >= hi, r


# --- pages: wording rules ----------------------------------------------------------------------------------------

def test_seat_page_uses_observed_boundary_not_the_cutover(pages):
    p = pages["districts/02.html"]
    assert "Seen in roll calls</th>" in p and "Held this seat" not in p
    assert config.SITE["lines_effective"] not in p and "redrawn in" not in p
    assert "Current: in the roll calls of the latest meeting collected, 2024-12-09." in p
    assert re.search(r"<h3[^>]*><a [^>]*>D\. Testperson</a>, District 2: roll calls 2024-12-09 to 2024-12-09</h3>", p)
    assert config.SITE["redistricting_page"] in p


def test_swap_line_is_linked_on_19_and_20_only(pages):
    for n in (19, 20):
        assert f'href="{config.SITE["swap_source"]}"' in pages[f"districts/{n:02d}.html"]
    assert config.SITE["swap_source"] not in pages["districts/18.html"]


def test_tally_reads_counted(pages):
    assert "(counted: " in pages["meetings/2024-11-04-formal.html"]
    assert not re.search(r"\(\d+ yes, \d+ no", "".join(pages.values()))


def test_about_explains_seats_and_motion_kinds(pages):
    p = pages["about.html"]
    assert "from when, to when" not in p and "redrawn in" not in p
    assert "These are not term dates" in p
    assert 'id="motion-kinds"' in p
    for _, label in config.UNVERIFIED_MOTION_TYPES:
        assert f'<th scope="row">{label}</th>' in p


def test_officials_current_section_shows_its_basis(pages):
    p = pages["officials.html"]
    assert "Current: in the roll calls of the latest meeting collected, 2024-12-09." in p
    assert "County Mayor and City Mayor: the source prints no end to the term." in p
    assert not re.search(r"<summary[^>]*>\s*<h2", p)


def test_landing_caption_has_no_in_use_since(pages):
    p = pages["index.html"]
    assert "in use since" not in p
    # the fixture build has no address box, so the list is the way in and starts open (collapsed beside the box)
    assert 'id="addr-form"' not in p and '<details class="district-list" id="wards-districts" open>' in p


def test_meeting_names_without_a_record_read_seat_not_recorded(ix):
    # e-fixture has no holder record; on a meeting date the seat is never guessed
    who = ix.person({"official_id": "e-fixture"}, "2024-11-04")
    assert who["seat"] == "seat not recorded"
    assert ix.person({"official_id": "a-example"}, "2024-11-04")["seat"] == "District 1"


def test_vote_filter_rows_get_the_seat_on_that_date(ix):
    idx = views.search_index(ix)
    on = idx["seat_on"]["2024-11-04"]
    assert idx["seat_labels"][on["a-example"]] == "District 1"
    assert idx["seat_labels"][on["d-testperson"]] == "seat not recorded"   # d-testperson's record starts 2024-12-09
    assert idx["seat_labels"][idx["seat_on"]["2024-12-09"]["d-testperson"]] == "District 2"


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_search_mark_never_splits_an_entity():
    js = (ROOT / "site" / "static" / "search.js").read_text(encoding="utf-8")
    esc = re.search(r"  function esc\(s\) \{.*?\n  \}\n", js, re.S).group(0)
    mark = re.search(r"  function mark\(text, toks\) \{.*?\n  \}\n", js, re.S).group(0)
    code = esc + mark + "console.log(JSON.stringify([mark('Smith & amp <b>', ['amp']), mark('a&b', ['a', '&'])]));"
    out = json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)
    assert out[0] == "Smith &amp; <mark>amp</mark> &lt;b&gt;"
    assert out[1] == "<mark>a</mark><mark>&amp;</mark>b"


def test_build_refuses_a_non_https_link_in_site_config():
    from sitegen.build import site_url_problems
    assert site_url_problems(config.SITE) == []
    bad = {**config.SITE, "swap_source": "http://example.org/list.pdf#page=9", "old_lines_map_url": ""}
    assert [p for p in site_url_problems(bad) if p.startswith("swap_source")]


def test_about_lists_the_vote_on_rule_and_every_label_links_to_it(tmp_path, facts):
    """provenance/vote-on-rule-unpublished: "Vote on" is derived by config.OUTCOME_SUBJECTS; About lists each form in
    plain words from the same list, and every "Vote on" words on a page link to about.html#vote-on."""
    import copy
    from test_site_review_fixes import RC_SHOWN, build_pages, by_id
    rows = views.vote_on_rule()
    assert [r["label"] for r in rows] == [label for _, label in config.OUTCOME_SUBJECTS]
    for r in rows:      # no pattern syntax left: a new pattern the renderer cannot word fails here
        assert not re.search(r"\(\?|[|\\?()]|\.\*", r["clause"]), r["clause"]
        assert r["clause"].endswith(config.OUTCOME_TAIL_WORDS)
    f = copy.deepcopy(facts)
    by_id(f, "roll_calls", RC_SHOWN)["outcome_text"] = "The foregoing Amendment was Adopted by the following roll call vote:"
    pages = build_pages(tmp_path, f)
    about = pages["about.html"]
    assert 'id="vote-on"' in about and "How &ldquo;Vote on&rdquo; is decided" in about
    for r in rows:
        assert f'<th scope="row">{r["label"]}</th><td>{r["clause"]}</td>' in about
    shown = 0
    for name, html in pages.items():
        if name == "about.html":
            continue
        n = len(re.findall(r"Vote on</a>:", html))
        assert n == html.count("Vote on"), name            # never the words without the link
        assert n == len(re.findall(r'href="[./]*about\.html#vote-on">Vote on</a>:', html)), name
        shown += n
    assert shown >= 3       # the meeting block, the item event and the votes-by-year row at least
