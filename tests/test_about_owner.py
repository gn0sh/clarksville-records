"""About page (Brian, 2026-11-11): the operator line (the official who runs the site, named and linked to their own
vote history page, with seat and body from the data and no typed date) and each council's confirmed rate, computed
from the facts at build time, with qa/site_checks.py check_about restating both from the facts.

Builds the county fixture beside the city fixture subset of tests/test_council_pages.py."""
import copy
import json
import re
import shutil
from html import unescape

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, ROOT
from qa import site_checks as SC
from sitegen import config, council, views
from sitegen.build import BuildError, build
from test_council_pages import cfg, city_facts, city_wards  # noqa: F401  (module fixtures)

PERSON = "city-brian-zacharias"


def plain(fragment: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", "", fragment)).split())


def qa_council(cfg_, facts):  # noqa: F811
    return {"slug": cfg_["slug"], "prefix": cfg_["slug"] + "/", "facts": facts}


@pytest.fixture(scope="module")
def about_site(tmp_path_factory, cfg):  # noqa: F811
    out = tmp_path_factory.mktemp("about") / "build" / "site"
    build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, councils=[cfg])
    return out


def test_shipped_config_names_an_official_of_the_city_facts():
    pid = config.SITE.get("operator_person")
    assert pid == PERSON
    city = json.loads((ROOT / "data/localities/clarksville-tn/facts.json").read_text(encoding="utf-8"))
    assert any(o["id"] == pid for o in city["officials"])


def test_operator_line_reads_name_seat_and_link_from_the_data(about_site, city_facts):  # noqa: F811
    raw = (about_site / "about.html").read_text(encoding="utf-8")
    lines = SC.OPERATOR_PERSON.findall(raw)
    assert len(lines) == 1
    o = next(o for o in city_facts["officials"] if o["id"] == PERSON)
    assert f'<a href="city/members/{PERSON}.html">{o["name"]}</a>' in lines[0]
    assert (about_site / f"city/members/{PERSON}.html").is_file()       # his vote history page, as every official's
    text = plain(lines[0])
    assert text.startswith(f"{config.OPERATOR_NAME} is run by {o['name']}, who ")
    assert not re.search(r"\b(19|20)\d\d\b", text)                    # no date the data lacks
    assert text.endswith("This member's votes are shown by the same rules as every other official's.")
    # no typed pronoun (site-polish/operator-pronoun-typed): the line reads the same for anyone
    assert not re.search(r"\b(he|his|him|she|her|hers|they|their|them)\b", text, re.I), text
    # the same line on Who runs this (site-polish/operator-disclosure-split)
    who = (about_site / "who-runs-this.html").read_text(encoding="utf-8")
    assert SC.OPERATOR_PERSON.findall(who) == lines
    # neutral: no praise, no campaign or donation link inside the line
    assert not re.search(r"vote for|elect|campaign|proud|honou?r|serv(es|ing) the people", text, re.I)
    assert raw.count("href=") and "buymeacoffee" not in lines[0]
    # the operator credit is still there
    assert f"This site is run by {config.OPERATOR_NAME}." in plain(raw)


def test_operator_line_seat_is_the_seat_records_current_seat(cfg, city_facts, city_wards):  # noqa: F811
    cix = council.load(cfg, city_facts, city_wards)
    p = views.operator_person(PERSON, [cix])
    current = [r["label"] for r in cix.seats.of(PERSON) if r["current"]]
    assert p["current"] == bool(current) and p["seat"] == (", ".join(current) or None)
    assert p["term_end"] is None             # the city's seat records are observed: no sourced term end
    assert p["href"] == f"city/members/{PERSON}.html" and p["body"] == cix.body_name
    assert views.operator_person(None, [cix]) is None and views.operator_person("nobody", [cix]) is None


def test_an_operator_person_no_council_has_fails_the_build(tmp_path, cfg, monkeypatch):  # noqa: F811
    monkeypatch.setitem(config.SITE, "operator_person", "city-nobody")
    with pytest.raises(BuildError, match="operator_person"):
        build(FIXTURE, tmp_path / "site", seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, councils=[cfg])


def test_confirmed_rate_is_computed_from_the_facts(about_site, city_facts):  # noqa: F811
    rcs = city_facts["roll_calls"]
    n = sum(1 for rc in rcs if views.is_verified(rc))
    assert 0 < n < len(rcs)                   # the subset has a held roll call, so the rate is not trivially 100%
    raw = (about_site / "about.html").read_text(encoding="utf-8")
    rates = {unescape(m.group("body")): plain(m.group("text")) for m in SC.ABOUT_RATE.finditer(raw)}
    county = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cn = sum(1 for rc in county["roll_calls"] if views.is_verified(rc))
    ct = len(county["roll_calls"])
    tail = " are confirmed against the official minutes; the rest are shown as not confirmed, each with its reason and a link to the source."
    # every body's line in the same words (site-polish/about-rate-unlabelled), in alphabetical order of body
    assert rates == {
        "Clarksville City Council": f"{n:,} of {len(rcs):,} Clarksville City Council roll calls ({100 * n / len(rcs):.1f}%)" + tail,
        "Montgomery County Commission": f"{cn:,} of {ct:,} Montgomery County Commission roll calls ({100 * cn / ct:.1f}%)" + tail}
    assert list(rates) == sorted(rates)


def test_confirmed_rate_follows_a_new_facts_file(cfg, city_facts, city_wards):  # noqa: F811
    """The rate is never typed: confirming one more roll call (as the city branch's reader does) moves it."""
    before = views.confirmed_rate(council.load(cfg, city_facts, city_wards))
    more = copy.deepcopy(city_facts)
    rc = next(rc for rc in more["roll_calls"] if not views.is_verified(rc))
    rc["verification"]["status"] = "verified"
    after = views.confirmed_rate(council.load(cfg, more, city_wards))
    assert after["confirmed"] == before["confirmed"] + 1 and after["total"] == before["total"]
    assert after["text"] != before["text"]
    big = {"rc_confirmed": 1823, "rc_total": 2237}
    pct = f"{100 * big['rc_confirmed'] / big['rc_total']:.1f}"
    assert (f"{big['rc_confirmed']:,} of {big['rc_total']:,}", pct) == ("1,823 of 2,237", "81.5")


def test_site_checks_about_passes_and_catches_drift(about_site, tmp_path, cfg, city_facts):  # noqa: F811
    cs = [qa_council(cfg, city_facts)]
    site_cfg = {"operator_person": PERSON}
    county = json.loads(FIXTURE.read_text(encoding="utf-8"))
    problems, note = SC.check_about(about_site, cs, site_cfg, county=county)
    assert problems == [] and "Clarksville City Council" in note and f"members/{PERSON}.html" in note, problems
    assert "Montgomery County Commission" in note and "who-runs-this.html" in note
    bad = tmp_path / "site"
    shutil.copytree(about_site, bad)
    page = bad / "about.html"
    raw = page.read_text(encoding="utf-8")
    m = SC.ABOUT_RATE.search(raw)
    raw = raw.replace(m.group("text"), "1,999 of 2,235" + m.group("text").split(" ", 3)[3], 1)
    raw = raw.replace(f'href="city/members/{PERSON}.html"', 'href="city/index.html"', 1)
    raw = raw.replace(" votes are shown by the same rules", " votes (since 2027) are shown by the same rules", 1)
    raw = re.sub(r"is on the Clarksville City Council \(Ward \d+\)", "has served on the Clarksville City Council", raw, count=1)
    page.write_text(raw, encoding="utf-8")
    (bad / "who-runs-this.html").write_text(
        re.sub(r'<p id="operator-person">.*?</p>', "", (bad / "who-runs-this.html").read_text(encoding="utf-8"), flags=re.S),
        encoding="utf-8")
    problems, _ = SC.check_about(bad, cs, site_cfg, county=county)
    text = "\n".join(problems)
    assert "Clarksville City Council rate reads" in text, problems
    assert "does not link" in text and "prints a year" in text, problems
    assert "does not say 'is on the Clarksville City Council (Ward" in text, problems     # tense and seat vs the records
    assert "who-runs-this.html: 0 operator lines" in text, problems
    problems, _ = SC.check_about(about_site, cs, site_cfg)                  # no county facts: its line is extra
    assert any("Montgomery County Commission, which this build has no facts for" in p for p in problems), problems


def test_the_rate_is_the_only_percentage_and_never_on_an_official_page(about_site):
    """test_site_neutrality bans "%" in templates (no score about a person); the About rate's share is written by
    views.confirmed_rate and is about the body's record. No official's page, nor any page but About, shows one."""
    for p in about_site.rglob("*.html"):
        rel = p.relative_to(about_site).as_posix()
        body = re.sub(r"<(script|style)\b.*?</\1>", "", p.read_text(encoding="utf-8"), flags=re.S)
        shown = re.findall(r"\d%", plain(body))
        if rel == "about.html":
            assert len(shown) == 2, shown          # one per body: the county and the city
        else:
            assert not shown, (rel, shown)
