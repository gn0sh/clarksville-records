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
    assert s.dates_text(obs) == "seen in vote records 2020-03-09 to 2022-08-08"
    assert s.dates_text({**OBSERVED, "start": "2022-09-12"}) == (
        "seen in vote records from 2022-09-12 to 2026-05-11, the latest meeting collected")
    assert s.dates_text({**OBSERVED, "official_id": None, "start": "2024-01-06"}) == (
        "shown as vacant in vote records from 2024-01-06 to 2026-05-11")
    assert s.dates_text(SOURCED) == "term 2022-2026, as the source prints it"
    assert s.basis({**OBSERVED, "current": True}) == "Current: in the vote records of the latest meeting collected, 2026-05-11"


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


@pytest.mark.parametrize("back", [0, 1])
def test_check_provenance_bans_the_cutover_value_written_in_words(tmp_path, built, facts, back):
    """onceover/dates/cutover-words-ban-untested: pages print dates in words ("August 30, 2022"), so the split key and
    the day before it are banned in that form too, each on its own."""
    import datetime as dt
    d = dt.date.fromisoformat(config.SITE["lines_effective"]) - dt.timedelta(days=back)
    words = f"{d.strftime('%B')} {d.day}, {d.year}"
    site = tmp_path / "site"
    shutil.copytree(built, site)
    pages = {p.relative_to(site).as_posix(): site_checks.parse(p) for p in site.rglob("*.html")}
    clean, _ = site_checks.check_provenance(site, pages, facts, [], site_checks._site_cfg())
    assert not any("banned" in p for p in clean)                 # the fixture itself prints neither day
    f = site / "about.html"
    f.write_text(f.read_text(encoding="utf-8").replace("</main>", f"<p>Lines changed on {words}.</p></main>"),
                 encoding="utf-8")
    problems, _ = site_checks.check_provenance(site, pages, facts, [], site_checks._site_cfg())
    assert [p for p in problems if "banned" in p] == [f"about.html: contains banned {words!r}"]


@pytest.mark.parametrize("text", [
    "Ward 2, 2026-02-19 to 2026-06-04",                                   # bare dates, no phrase
    "seen in the minutes 2026-02-19",                                     # a phrase that is not one of DATE_PHRASES
    "Ward 2, seen in the minutes that record the seating; 2026-02-19",    # the phrase, but its clause ended
    "Ward 2, in the minutes that record the seating 2026-02-19",          # the configured phrase without "seen"
])
def test_dates_worded_flags_a_date_outside_its_phrase(text):
    """site-checks/provenance-no-negative-test: each of these names a date no allowed phrase introduces."""
    assert site_checks.dates_worded(text) == ["2026-02-19"] + (["2026-06-04"] if "2026-06-04" in text else [])


def test_dates_worded_allows_the_configured_seating_phrase():
    assert site_checks.dates_worded("Ward 2, seen in the minutes that record the seating 2026-02-19") == []


def test_search_index_seat_strings_are_worded(built):
    raw = (built / "static" / "search-index.js").read_text(encoding="utf-8")
    ix = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    labels = {o["id"]: o["label"] for o in ix["officials"]}
    assert labels["a-example"] == "Example, A. (District 1)"
    assert labels["b-sample"] == "Sample, B. (District 2 (seen in vote records on 2024-11-04))"
    assert labels["e-fixture"] == "Fixture, E."
    for t in [o["label"] for o in ix["officials"]] + ix["seat_labels"]:
        assert site_checks.dates_worded(t) == [], t


# --- provenance/verbatim-title-trips-ban: a record's own words are not the site's seat wording -----------------------

# The 2021-12-02 agenda's caption for ORDINANCE 30-2021-22, verbatim (the Daily update of 2026-11-23 failed on it).
CAPTION = ("(Second Reading) Amending the official code Title 1, Chapter 2, Section 204 relative to presenting "
           "legislation and deliberation of City Council members to maximize efficiency Pg 201")


def _plant(tmp_path, built, page_html: str = "", index_record: dict | None = None) -> Path:
    site = tmp_path / "site"
    shutil.copytree(built, site)
    if page_html:
        f = site / "about.html"
        f.write_text(f.read_text(encoding="utf-8").replace("</main>", page_html + "</main>"), encoding="utf-8")
    if index_record is not None:
        f = site / "static" / "search-index.js"
        raw = f.read_text(encoding="utf-8")
        start, end = raw.index("{"), raw.rindex("}") + 1
        ix = json.loads(raw[start:end])
        ix["records"].append(index_record)
        f.write_text(raw[:start] + json.dumps(ix) + raw[end:], encoding="utf-8")
    return site


def _banned(site: Path, facts) -> list[str]:
    pages = {p.relative_to(site).as_posix(): site_checks.parse(p) for p in site.rglob("*.html")}
    problems, _ = site_checks.check_provenance(site, pages, facts, [], site_checks._site_cfg())
    return [p for p in problems if "banned" in p]


def _item_title_html(title: str) -> str:
    """The title as the real macro renders it (the markup VERBATIM_TITLE relies on)."""
    from sitegen.build import make_env
    return make_env().from_string('{% import "_macros.html.j2" as m %}{{ m.item_title(t) }}').render(t=title)


def test_the_item_title_macro_renders_the_bare_span_the_check_empties():
    out = _item_title_html(CAPTION + " & <b>")
    assert site_checks.VERBATIM_TITLE.fullmatch(out), out
    assert site_checks.VERBATIM_TITLE.sub(r"\1\2", out) == "<span data-item-title></span>"


@pytest.mark.parametrize("title", [CAPTION, "Resolution authorizing the Mayor to present the plan",
                                   "Lease of the old depot, vacant since 1998", "Held this seat? A plaque request",
                                   "Ordinance effective {cutover}"])
@pytest.mark.parametrize("kind", ["item", "vote"])
def test_a_verbatim_title_holding_a_banned_phrase_passes(tmp_path, built, facts, title, kind):
    """A title as its minutes or agenda print it (page and search index) is the record's words, never flagged; the
    lines_effective day in words is banned too, so a title that prints it is covered by the same rule."""
    import datetime as dt
    d = dt.date.fromisoformat(site_checks._site_cfg()["lines_effective"])
    title = title.format(cutover=f"{d.strftime('%B')} {d.day}, {d.year}")
    item = _item_title_html(title)
    site = _plant(tmp_path, built, f'<p><a href="items/2021.html"><strong>ORDINANCE 30-2021-22</strong> {item}</a></p>',
                  {"k": kind, "id": "x", "n": "ORDINANCE 30-2021-22", "t": title,
                   "ts": {"u": "https://example.gov/a.pdf#page=3", "p": 3, "l": "title as printed in the agenda, p. 3"}})
    assert _banned(site, facts) == []


@pytest.mark.parametrize("planted", [
    "<p>Seat 4, 2021 to present</p>",                                               # site-written, outside any title
    f'<span data-item-title>{CAPTION}</span> <span class="seat">2021 to present</span>',  # beside a title
    '<span data-item-title>Ward 2 <span class="seat">2021 to present</span></span>',  # markup inside: stays checked
    '<span data-item-title class="x">2021 to present</span>',                       # another attribute: stays checked
])
def test_site_written_to_present_still_fails_beside_a_verbatim_title(tmp_path, built, facts, planted):
    assert _banned(_plant(tmp_path, built, planted, None), facts) == ["about.html: contains banned 'to present'"]


@pytest.mark.parametrize("record", [
    {"k": "person", "id": "x", "n": "", "t": "Example, A.", "st": "District 1, 2021 to present"},   # a seat text
    {"k": "item", "id": "x", "n": "", "t": "", "ts": {"u": "u", "p": 1, "l": "2021 to present"}},  # the cite's words
    {"k": "meeting", "id": "x", "n": "", "t": "Meeting, held 2021 to present"},                     # another kind
])
def test_site_written_to_present_in_the_search_index_still_fails(tmp_path, built, facts, record):
    assert _banned(_plant(tmp_path, built, "", record), facts) == ["static/search-index.js: contains banned 'to present'"]


# provenance/verbatim-span-producers-unguarded: the check empties every bare <span data-item-title> site-wide, so each
# template that prints one is pinned here with its exact inner expression or literal. Each must print a record's words
# as printed (titles, names, motion and outcome words, printed dates), never the site's own seat or term wording. A new
# or changed one fails this test until it is reviewed and added. (file, element, inner text): count.
VERBATIM_SPAN_PRODUCERS = {
    ("_city_committee.html.j2", "span", '{{ a.present | join(", ") }}'): 1,                     # attendance, as printed
    ("_city_committee.html.j2", "span", '{% if a.absent %}{{ a.absent | join(", ") }}{% else %}none{% endif %}'): 1,
    ("_city_committee.html.j2", "span", "{{ mv.item }}"): 1,                                    # motion words, as printed
    ("_city_committee.html.j2", "span", "{{ mv.words }}"): 1,
    ("_city_committee.html.j2", "span", "{{ mv.moved_by }}"): 1,
    ("_city_committee.html.j2", "span", "{{ mv.seconded_by }}"): 1,
    ("_city_committee.html.j2", "span", '{{ mv.ayes | join(", ") }}'): 1,
    ("_city_committee.html.j2", "span", '{{ mv.nays | join(", ") }}'): 1,
    ("_city_committee.html.j2", "span", "{{ mv.outcome_printed }}"): 1,
    ("_committee.html.j2", "span", "{{ m.title }}"): 1,                                         # agenda heading
    ("_committee.html.j2", "span", "{{ e.text }}"): 2,                                          # agenda lines
    ("_macros.html.j2", "span", "{{ title }}"): 1,                                              # item_title: minutes/agenda
    ("_rpc.html.j2", "span", "{{ mv.moved_by }}"): 1,                                           # RPC motion words
    ("_rpc.html.j2", "span", "{{ mv.seconded_by }}"): 1,
    ("_rpc.html.j2", "span", '{{ mv.nays | join(", ") }}'): 1,
    ("_rpc.html.j2", "span", '{{ mv.abstained | join(", ") }}'): 1,
    ("_rpc.html.j2", "span", "{{ mv.outcome }}"): 1,
    ("county_agendas.html.j2", "span", "{{ it.title }}"): 1,                                    # agenda item titles
    ("rpc_meetings_year.html.j2", "span", "{{ h.printed }}"): 1,                                # case text, as printed
    ("rpc_meetings_year.html.j2", "dd", "{{ r.value }}"): 1,      # a <dd>: not emptied by VERBATIM_TITLE (stays checked)
    ("today.html.j2", "span", "{{ x.request }}"): 1,                                            # agenda/archive text
    ("today.html.j2", "span", "{{ x.title }}"): 1,
    ("today.html.j2", "span", "{{ c.cal_title }}"): 1,                                          # the city's calendar title
    ("today.html.j2", "span", "{{ s.date_text }}"): 1,                                          # a date as printed
}


def test_every_verbatim_span_producer_is_pinned():
    from collections import Counter
    tdir = config.TEMPLATE_DIR
    found, loose = Counter(), []
    for f in sorted(tdir.rglob("*.j2")):
        text = f.read_text(encoding="utf-8")
        rel = f.relative_to(tdir).as_posix()
        for m in re.finditer(r"<(\w+)\s+data-item-title>([^<]*)<", text):
            found[(rel, m[1], m[2])] += 1
        # any other use as an attribute (another attribute beside it, a value): not emptied, but pinned as none
        loose += [rel for m in re.finditer(r"<\w+[^>]*\sdata-item-title(?!>)[\s=/]", text)]
    assert dict(found) == VERBATIM_SPAN_PRODUCERS, sorted(set(found.items()) ^ set(VERBATIM_SPAN_PRODUCERS.items()))
    assert loose == []
    # HTML built in Python never prints the span (every producer is a template, pinned above)
    py = [p.relative_to(ROOT).as_posix() for d in ("sitegen", "sender") for p in (ROOT / d).rglob("*.py")
          if "<span data-item-title" in p.read_text(encoding="utf-8")]
    assert py == []



# provenance/verbatim-span-producers-unguarded (hit 2): the `item_title` macro's span prints its own parameter, so the
# pin above holds only if every caller passes a record's title as printed. Each call's argument is pinned here, read
# with Jinja's own parser (whitespace, newlines and {% call %} blocks alike). Calls through a module import
# (`m.item_title(...)`) count as callers; an import alias (`import item_title as t`), a `set` or any other non-call use
# of the name fails, so it cannot be called under another name unpinned. Not caught: a subscript (`m["item_title"]`),
# which no template uses. (file, argument): count.
ITEM_TITLE_CALLERS = {
    ("_macros.html.j2", "item.title"): 2,           # item_link: an item's title, verbatim from the minutes
    ("items_year.html.j2", "it.title"): 2,          # year page: jump list and item heading
    ("today.html.j2", "s.title"): 1,                # today page: an item said at a meeting
}


def _jinja_expr(node):
    from jinja2 import nodes
    if isinstance(node, nodes.Name):
        return node.name
    if isinstance(node, nodes.Getattr):
        return f"{_jinja_expr(node.node)}.{node.attr}"
    if isinstance(node, nodes.Const):
        return repr(node.value)
    return repr(node)            # anything else (a filter, a concatenation, a call) is never in the registry


def test_every_item_title_caller_is_pinned():
    from collections import Counter
    from jinja2 import nodes
    from sitegen import build
    env, tdir = build.make_env(), config.TEMPLATE_DIR
    found, other = Counter(), []
    for f in sorted(tdir.rglob("*.j2")):
        rel = f.relative_to(tdir).as_posix()
        ast = env.parse(f.read_text(encoding="utf-8"), name=rel)
        calls = set()
        for c in ast.find_all(nodes.Call):
            callee = c.node
            if (isinstance(callee, nodes.Name) and callee.name == "item_title") or (
                    isinstance(callee, nodes.Getattr) and callee.attr == "item_title"):
                calls.add(id(callee))
                if len(c.args) == 1 and not (c.kwargs or c.dyn_args or c.dyn_kwargs):
                    found[(rel, _jinja_expr(c.args[0]))] += 1
                else:
                    other.append((rel, "call", repr(c)))
        # the name used any other way: passed on, `set` to a new name, or reached through a module import
        for n in ast.find_all((nodes.Name, nodes.Getattr)):
            if id(n) not in calls and getattr(n, "name", getattr(n, "attr", None)) == "item_title":
                other.append((rel, "use", repr(n)))
        for imp in ast.find_all(nodes.FromImport):
            for name in imp.names:
                if isinstance(name, tuple) and name[0] == "item_title" and name[1] != "item_title":
                    other.append((rel, "alias", name[1]))
    assert dict(found) == ITEM_TITLE_CALLERS, sorted(set(found.items()) ^ set(ITEM_TITLE_CALLERS.items()))
    assert other == []


def test_the_search_index_title_fallbacks_hold_no_banned_phrase():
    """provenance/index-t-producers-misdocumented: the `t` the search-index scan empties is a title as printed or one
    of these fallbacks; the site writes the fallbacks, so none may hold a banned phrase."""
    untitled = config.load_council("clarksville-tn")["untitled_item"]     # council.Council.item_title's fallback
    assert untitled == "Title not read from the minutes"
    # views.Index.item_title's two fixed forms (it reads no state, so it is called unbound)
    county = [views.Index.item_title(None, {"title": "", "number": "ORDINANCE 1-2021-22"}),
              views.Index.item_title(None, {"title": "", "number": ""})]
    assert county == ["Untitled item ORDINANCE 1-2021-22", "Untitled item"]
    for t in [untitled] + county:
        assert not [b for b in site_checks.BANNED if b in t], t


def test_an_unparseable_search_index_is_scanned_whole():
    raw = 'window.SEARCH_INDEX = {"records": [{"k": "item", "t": "x to present"}, ;'
    assert site_checks.search_index_own_text(raw) == raw


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
    assert "Seen in vote records</th>" in p and "Held this seat" not in p
    assert config.SITE["lines_effective"] not in p and "redrawn in" not in p
    assert "Current: in the vote records of the latest meeting collected, 2024-12-09." in p
    assert re.search(r"<h3[^>]*><a [^>]*>D\. Testperson</a>, District 2: vote records 2024-12-09 to 2024-12-09</h3>", p)
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
    assert "Current: in the vote records of the latest meeting collected, 2024-12-09." in p
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
