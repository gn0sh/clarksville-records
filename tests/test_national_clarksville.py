"""Daylight Digest, the Clarksville adapter (sitegen/national_clarksville.py; docs/architecture/daylight-national.md
3.5, 4.3, 7 and 11; task B3). Problem keys: privacy-withhold/national-prefix (items_withheld from the directory's
`items` field, never an id prefix), national/untrusted-size and national/url-scheme-untrusted (the B14 guards).

The real-data tests read data/ through the loaders the build uses (build.load_facts on the council's council.yml
`facts_path`, county_agendas.load on config.COUNTY_AGENDAS, load_listing on its `calendar`) and assert only rules
that hold for any valid growth of the records (docs/architecture/real-data-tests-invariant.md, I-live): `today` is
derived from the live file. Missing data fails them (after the ADR 0011 data move a silent skip would hide every
real-data check); they skip only when CR_ALLOW_NO_DATA=1 and CI is not set."""
import copy
import dataclasses
import json
import os
from datetime import date, datetime, timezone

import pytest
from jsonschema import Draft202012Validator

from sitegen import build, config, county_agendas
from sitegen import national as nat
from sitegen import national_clarksville as nc
from sitegen import national_guards as g

CHECKED = datetime(2026, 11, 10, 4, 33, tzinfo=timezone.utc)
COUNCIL_ID, COUNTY_ID = "place-4715160", "county-47125"
SCHEMA = json.loads(nc.UPCOMING_SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def directory():
    return nat.load_directory()


@pytest.fixture(scope="module")
def real():
    cfg = nc.council_cfg("city")
    if cfg is None or not cfg["facts_path"].is_file() or not config.COUNTY_AGENDAS.is_file():
        why = (f"the Clarksville data is not in this checkout ({config.COUNTY_AGENDAS} and the council facts); "
               "check out the data, or set CR_ALLOW_NO_DATA=1 to skip the real-data tests locally")
        if os.environ.get("CR_ALLOW_NO_DATA") == "1" and not os.environ.get("CI"):
            pytest.skip(why)
        pytest.fail(why)
    agendas = county_agendas.load(config.COUNTY_AGENDAS)
    paged = {s["id"] for s in agendas["sources"] if s.get("pages")}
    eligible = [m for m in agendas["meetings"] if m["source_id"] in paged]
    today = min(date.fromisoformat(m["date"]) for m in eligible)      # every stored county agenda is "coming up"
    return {"facts": build.load_facts(cfg["facts_path"]), "listing": nc.load_listing(cfg), "agendas": agendas,
            "eligible": eligible, "today": today}


@pytest.fixture(scope="module")
def feeds(directory, real):
    counts = {}
    out = nc.clarksville_feeds(directory, {"city": (real["facts"], real["listing"])}, real["agendas"], real["today"],
                               checked_at=CHECKED, counts=counts)
    return out, counts


def facts_with(*meetings, sources=()):
    return {"meetings": list(meetings), "sources": list(sources)}


def agendas_with(*items, date_="2026-12-14", url="https://mcgtn.org/a.pdf", pages=3):
    return {"index_url": "https://montgomerytn.gov/commission/agenda",
            "sources": [{"id": "src-1", "url": url, "pages": pages}],
            "meetings": [{"id": f"{date_}-formal", "date": date_, "kind": "formal", "source_id": "src-1",
                          "items": [{"number": f"26-12-{n}", "title": t, "page": 1} for n, t in enumerate(items, 1)]}]}


def run(directory, facts=None, listing=(), agendas=None, today=date(2026, 11, 19)):
    return nc.clarksville_feeds(directory, {"city": (facts or facts_with(), list(listing))}, agendas, today,
                                checked_at=CHECKED)


def entry(directory, gov_id, **changes):
    e = dict(directory.get(gov_id))
    e.update(changes)
    return e


def with_govs(directory, *govs):
    return dataclasses.replace(directory, govs=tuple(govs))


# --- the real data (I-live) ---------------------------------------------------------------------------------------

def test_real_feeds_are_the_council_and_the_county(feeds):
    assert set(feeds[0]) == {COUNCIL_ID, COUNTY_ID}


def test_real_feeds_validate_against_the_schema(feeds):
    for feed in feeds[0].values():
        assert nc.feed_errors(feed) == []
        assert feed["schema"] == "daylight-upcoming/1"


def _no_extra_keys(value, schema, where="(root)"):
    """Every key in `value` is a property the schema names, recursively (refs, arrays and allOf followed)."""
    if "$ref" in schema:
        schema = SCHEMA["$defs"][schema["$ref"].rsplit("/", 1)[1]]
    if isinstance(value, dict):
        props = schema.get("properties", {})
        extra = set(value) - set(props)
        assert not extra, f"{where}: fields outside the schema: {sorted(extra)}"
        for k, v in value.items():
            _no_extra_keys(v, props[k], f"{where}/{k}")
    elif isinstance(value, list) and "items" in schema:
        for n, v in enumerate(value):
            _no_extra_keys(v, schema["items"], f"{where}/{n}")


def test_real_feeds_carry_no_field_outside_the_schema(feeds):
    for feed in feeds[0].values():
        _no_extra_keys(feed, SCHEMA)


def _property_names(node) -> set[str]:
    names = set()
    if isinstance(node, dict):
        names |= set(node.get("properties", {}))
        for v in node.values():
            names |= _property_names(v)
    elif isinstance(node, list):
        for v in node:
            names |= _property_names(v)
    return names


def test_schema_fields_are_exactly_the_contract():
    """3.5's field list and nothing else: no vote, outcome, tally, attendance, motion or person's name (AC4.4)."""
    Draft202012Validator.check_schema(SCHEMA)
    assert _property_names(SCHEMA) == {
        "schema", "review", "body", "checked_at", "last_ok_at", "meetings", "id", "name", "tz", "official_url", "platform",
        "full_url", "date", "time", "title", "title_ours", "meeting_url", "agenda", "state", "url",
        "status_as_posted", "may_be_incomplete", "items_withheld", "item_count", "items", "seq", "number", "text",
        "cut", "source", "page"}


def test_contract_example_validates():
    """The guards' copy of the 3.5 example feed passes the schema (the schema is no tighter than the contract)."""
    from tests.test_national_guards import feed as example
    assert nc.feed_errors(example()) == []


def test_real_time_is_null_and_titles_are_ours(feeds):
    for feed in feeds[0].values():
        for m in feed["meetings"]:
            assert m["time"] is None and m["title_ours"] is True and m["title"]


def test_real_council_meetings_are_not_read_or_not_posted(feeds, real):
    meetings = feeds[0][COUNCIL_ID]["meetings"]
    assert meetings, "the council listing runs years ahead, so some meeting is coming up"
    for m in meetings:
        assert m["agenda"]["state"] in ("not-read", "not-posted")
        assert m["items"] == [] and m["item_count"] is None
        assert (m["agenda"]["url"] is None) == (m["agenda"]["state"] == "not-posted")
        assert m["date"] >= real["today"].isoformat()


def test_real_county_items_equal_agendas_titles_byte_for_byte(feeds, real):
    meetings = feeds[0][COUNTY_ID]["meetings"]
    assert len(meetings) == min(len(real["eligible"]), g.MAX_MEETINGS)
    stored = {m["id"]: m for m in real["agendas"]["meetings"]}
    exact = 0
    for m in meetings:
        assert m["agenda"]["state"] == "final" and m["items_withheld"] is False
        src = stored[m["id"]]
        assert m["item_count"] == len(src["items"])
        assert len(m["items"]) == min(len(src["items"]), g.MAX_ITEMS)
        for item, it in zip(m["items"], src["items"]):
            clean = not g.BAD_TEXT_RE.search(it["title"]) and " ".join(it["title"].split()) == it["title"]
            if clean and len(it["title"]) <= g.MAX_ITEM_TEXT:
                assert item["text"].encode() == it["title"].encode()
                assert "cut" not in item
                exact += 1
            else:                                           # only the B14 guards may change it
                text, _ = g.clean_text(it["title"])
                assert item["text"] == g.cut_text(text)[0]
            assert item["number"] == it["number"]
            assert item["source"]["page"] == it["page"]
            assert item["source"]["url"].endswith(f"#page={it['page']}")
    assert exact, "no county item was compared byte for byte"


def test_real_meetings_are_soonest_first(feeds):
    for feed in feeds[0].values():
        keys = [(m["date"], m["id"]) for m in feed["meetings"]]
        assert keys == sorted(keys)


def test_real_body_is_the_directory_entry(feeds, directory):
    for gov_id, feed in feeds[0].items():
        e = directory.get(gov_id)
        assert feed["body"] == {"id": gov_id, "name": e["body_name"], "tz": "America/Chicago",
                                "official_url": e["official_url"], "platform": "daylight",
                                "full_url": e["daylight"]["full_url"]}
        assert feed["checked_at"] == feed["last_ok_at"] == "2026-11-10T04:33:00Z"


# --- privacy-withhold/national-prefix: the directory's `items` field decides, never the id ------------------------

def _no_item_text(feed, *texts):
    blob = json.dumps(feed)
    for m in feed["meetings"]:
        assert m["items_withheld"] is True and m["items"] == [] and m["item_count"] is None
    for t in texts:
        assert t not in blob


def test_withheld_place_entry_publishes_no_items(directory):
    """A `place-` id is no licence to publish: a youth council withheld under a city id gets no item text."""
    youth = entry(directory, COUNTY_ID, gov="place-4799999", body_name="Clarksville Youth Council", items="withheld")
    feeds = run(with_govs(directory, youth), agendas=agendas_with("Recognition of Jane Doe"))
    _no_item_text(feeds["place-4799999"], "Jane Doe")
    assert nc.feed_errors(feeds["place-4799999"]) == []


def test_withheld_school_entry_publishes_no_items(directory):
    sd = entry(directory, COUNTY_ID, gov="sdu-4703030",
               body_name="Clarksville-Montgomery County School System Board of Education", items="withheld")
    feeds = run(with_govs(directory, sd), agendas=agendas_with("Student of the Month Jane Doe"))
    _no_item_text(feeds["sdu-4703030"], "Jane Doe")


def test_missing_items_field_means_withheld(directory):
    county = entry(directory, COUNTY_ID)
    del county["items"]
    feeds = run(with_govs(directory, county), agendas=agendas_with("Resolution on Roads"))
    _no_item_text(feeds[COUNTY_ID], "Resolution on Roads")


def test_withheld_county_entry_with_its_real_id(directory):
    """The same county id, the field set to withheld: no items, though the id is the one that shows them."""
    county = entry(directory, COUNTY_ID, items="withheld")
    feeds = run(with_govs(directory, county), agendas=agendas_with("Resolution on Roads"))
    _no_item_text(feeds[COUNTY_ID], "Resolution on Roads")
    assert feeds[COUNTY_ID]["meetings"][0]["agenda"]["state"] == "final"


def test_withheld_items_are_never_read(directory):
    """Withheld: the stored items are not touched at all (a malformed list would raise if they were read)."""
    county = entry(directory, COUNTY_ID, items="withheld")
    agendas = agendas_with()
    agendas["meetings"][0]["items"] = object()
    feeds = run(with_govs(directory, county), agendas=agendas)
    _no_item_text(feeds[COUNTY_ID])


def test_shown_county_entry_publishes_items(directory):
    feeds = run(directory, agendas=agendas_with("Resolution on Roads"))
    m = feeds[COUNTY_ID]["meetings"][0]
    assert m["items_withheld"] is False and m["item_count"] == 1
    assert m["items"] == [{"seq": 1, "number": "26-12-1", "text": "Resolution on Roads",
                           "source": {"url": "https://mcgtn.org/a.pdf#page=1", "page": 1}}]


def test_schema_refuses_items_on_a_withheld_meeting(directory):
    feed = run(directory, agendas=agendas_with("Resolution on Roads"))[COUNTY_ID]
    bad = copy.deepcopy(feed)
    bad["meetings"][0]["items_withheld"] = True
    assert nc.feed_errors(bad)
    bad["meetings"][0]["items"], bad["meetings"][0]["item_count"] = [], 1
    assert nc.feed_errors(bad)


def test_schema_refuses_items_on_an_agenda_not_final(directory):
    feed = run(directory, agendas=agendas_with("Resolution on Roads"))[COUNTY_ID]
    feed["meetings"][0]["agenda"]["state"] = "not-read"
    assert nc.feed_errors(feed)


def test_feed_is_chosen_by_the_daylight_key_not_the_id(directory):
    """An entry with the council's key gets the council feed (no items), whatever its id's layer."""
    other = entry(directory, COUNCIL_ID, gov="county-47999", body_name="Some County Commission")
    feeds = run(with_govs(directory, other), facts=facts_with({"id": "2026-12-03-regular", "date": "2026-12-03",
                                                                 "kind": "regular"}),
                agendas=agendas_with("Resolution on Roads"))
    assert [m["agenda"]["state"] for m in feeds["county-47999"]["meetings"]] == ["not-posted"]


def test_cant_cover_entry_gets_no_feed(directory):
    assert run(with_govs(directory, directory.get("sdu-4703030")), agendas=agendas_with("x")) == {}


def test_unknown_daylight_key_stops_the_build(directory):
    stray = entry(directory, COUNTY_ID, gov="county-47998", daylight={"body": "rpc", "full_url": "rpc/"})
    with pytest.raises(nc.FeedError, match="county-47998"):
        run(with_govs(directory, stray), agendas=agendas_with("x"))


def test_council_entry_never_gets_another_councils_inputs(directory, monkeypatch):
    """national/council-misattribution: a second council (its own council.yml) with no inputs of its own stops the
    build instead of being given Clarksville's facts and listing."""
    other_cfg = {**nc.council_cfg("city"), "body_key": "town"}
    monkeypatch.setattr(config, "COUNCILS", [*config.COUNCILS, other_cfg])
    town = entry(directory, COUNCIL_ID, gov="place-4799998", body_name="Some Town Council",
                 daylight={"body": "town", "full_url": "town/"})
    facts = facts_with({"id": "2026-12-03-regular", "date": "2026-12-03", "kind": "regular"})
    with pytest.raises(nc.FeedError, match="place-4799998"):
        run(with_govs(directory, directory.get(COUNCIL_ID), town), facts=facts)
    feeds = nc.clarksville_feeds(with_govs(directory, directory.get(COUNCIL_ID), town),
                                 {"city": (facts, []), "town": (facts_with(), [])}, None, date(2026, 11, 19),
                                 checked_at=CHECKED)
    assert [m["id"] for m in feeds[COUNCIL_ID]["meetings"]] == ["2026-12-03-regular"]
    assert feeds["place-4799998"]["meetings"] == []


def test_inputs_without_a_council_yml_stop_the_build(directory):
    town = entry(directory, COUNCIL_ID, gov="place-4799998", daylight={"body": "town", "full_url": "town/"})
    with pytest.raises(nc.FeedError):
        nc.clarksville_feeds(with_govs(directory, town), {"town": (facts_with(), [])}, None, date(2026, 11, 19),
                             checked_at=CHECKED)


def test_council_cfg_of_no_key_is_none():
    assert nc.council_cfg(None) is None and nc.council_cfg("") is None and nc.council_cfg("city")["body_key"] == "city"


def test_unknown_kind_gets_the_fixed_fallback_title(directory):
    ms = council(directory, listing=[{"date": "2026-12-03", "kind": "brand-new", "title": "<b>Whatever</b>"}])
    assert [(m["title"], m["title_ours"]) for m in ms] == [(nc.FALLBACK_TITLE, True)]
    agendas = agendas_with("x")
    agendas["meetings"][0]["kind"] = "retreat"
    assert run(directory, agendas=agendas)[COUNTY_ID]["meetings"][0]["title"] == nc.FALLBACK_TITLE


# --- the council: not-read or not-posted, days.py's listing rules -------------------------------------------------

AGENDA = {"id": "src-a", "url": "https://clarksvilletn.api.civicclerk.com/v1/a.pdf", "pages": 4}


def council(directory, facts=None, listing=(), today=date(2026, 11, 19)):
    return run(directory, facts=facts, listing=listing, today=today)[COUNCIL_ID]["meetings"]


def test_council_facts_meeting_with_agenda_is_not_read(directory):
    ms = council(directory, facts_with({"id": "2026-12-03-regular", "date": "2026-12-03", "kind": "regular",
                                        "agenda_source_id": "src-a"}, sources=[AGENDA]))
    assert ms == [{"id": "2026-12-03-regular", "date": "2026-12-03", "time": None, "title": "Regular session",
                   "title_ours": True, "meeting_url": None,
                   "agenda": {"state": "not-read", "url": AGENDA["url"], "status_as_posted": None},
                   "may_be_incomplete": False, "items_withheld": False, "item_count": None, "items": []}]


def test_council_listing_rows(directory):
    listing = [
        {"date": "2026-12-03", "kind": "regular", "title": "Regular Session", "agenda_url": AGENDA["url"]},
        {"date": "2026-12-03", "kind": "regular", "title": "Regular Session (copy)", "agenda_url": None},
        {"date": "2026-12-10", "kind": "special", "title": "Special Session CANCELLED", "agenda_url": None},
        {"date": "2026-12-11", "kind": "other", "title": "One Time Event", "page1_required": True},
        {"date": "2026-11-18", "kind": "regular", "title": "Regular Session"},
        {"date": "2026-12-17", "kind": "work-session", "title": "Work Session", "agenda_url": "http://x.test/a"},
        {"date": "2026-12-18", "kind": "work-session", "title": "Work Session", "agenda_url": None},
        {"date": None, "kind": "regular"}, {"date": "2026-13-40", "kind": "regular"}, {"date": "2026-12-20"},
        {"date": 20261221, "kind": "regular"}, "not a row",
    ]
    ms = council(directory, listing=listing)
    assert [(m["id"], m["agenda"]["state"], m["agenda"]["url"]) for m in ms] == [
        ("2026-12-03-regular", "not-read", AGENDA["url"]),
        ("2026-12-17-work-session", "not-read", None),        # posted, but allowed_url refuses the link
        ("2026-12-18-work-session", "not-posted", None)]


def test_council_facts_agenda_refused_link_is_not_read_with_null_url(directory):
    ms = council(directory, facts_with({"id": "2026-12-03-regular", "date": "2026-12-03", "kind": "regular",
                                        "agenda_source_id": "src-a"},
                                       sources=[{**AGENDA, "url": "http://clarksvilletn.gov/a.pdf"}]))
    assert [(m["agenda"]["state"], m["agenda"]["url"]) for m in ms] == [("not-read", None)]


def test_council_facts_meeting_called_off_on_the_listing_is_dropped(directory):
    facts = facts_with({"id": "2026-12-03-regular", "date": "2026-12-03", "kind": "regular"},
                       {"id": "2026-12-04-special", "date": "2026-12-04", "kind": "special"})
    listing = [{"date": "2026-12-03", "kind": "regular", "title": "Regular Session CANCELLED"},
               {"date": "2026-12-04", "kind": "special", "title": "Special Session POSTPONED"},
               {"date": "2026-12-04", "kind": "special", "title": "Special Session"}]
    assert [m["id"] for m in council(directory, facts, listing)] == ["2026-12-04-special"]


def test_council_facts_meeting_wins_over_its_listing_row(directory):
    ms = council(directory, facts_with({"id": "2026-12-03-regular", "date": "2026-12-03", "kind": "regular"}),
                 listing=[{"date": "2026-12-03", "kind": "regular", "title": "Regular Session",
                           "agenda_url": AGENDA["url"]}])
    assert [(m["id"], m["agenda"]["state"]) for m in ms] == [("2026-12-03-regular", "not-posted")]


def test_meetings_before_today_are_left_out(directory):
    ms = council(directory, facts_with({"id": "2026-11-18-regular", "date": "2026-11-18", "kind": "regular"},
                                       {"id": "2026-11-19-regular", "date": "2026-11-19", "kind": "regular"}))
    assert [m["id"] for m in ms] == ["2026-11-19-regular"]
    assert run(directory, agendas=agendas_with("x", date_="2026-11-18"))[COUNTY_ID]["meetings"] == []


# --- the county: as stored, B14 guards only ------------------------------------------------------------------------

def test_county_source_without_pages_is_left_out(directory):
    assert run(directory, agendas=agendas_with("x", pages=None))[COUNTY_ID]["meetings"] == []


def test_county_bidi_and_controls_are_stripped_and_counted(directory):
    counts = {}
    feeds = nc.clarksville_feeds(directory, {"city": (facts_with(), [])}, agendas_with("Roads‮ and\x00 bridges"),
                                 date(2026, 11, 19), checked_at=CHECKED, counts=counts)
    assert feeds[COUNTY_ID]["meetings"][0]["items"][0]["text"] == "Roads and bridges"
    assert counts[COUNTY_ID].chars_stripped == 2


def test_county_long_item_is_cut(directory):
    m = run(directory, agendas=agendas_with("a" * 2_500))[COUNTY_ID]["meetings"][0]
    assert len(m["items"][0]["text"]) == g.MAX_ITEM_TEXT and m["items"][0]["cut"] is True
    assert nc.feed_errors(run(directory, agendas=agendas_with("a" * 2_500))[COUNTY_ID]) == []


def test_county_items_and_meetings_capped(directory):
    many = agendas_with(*[f"Item {n}" for n in range(200)])
    m = run(directory, agendas=many)[COUNTY_ID]["meetings"][0]
    assert len(m["items"]) == g.MAX_ITEMS and m["item_count"] == 200
    listing = [{"date": f"2027-{1 + n // 28:02d}-{1 + n % 28:02d}", "kind": "regular", "title": "Regular Session"}
               for n in range(80)]
    kept = council(directory, listing=listing)
    days_ = sorted(r["date"] for r in listing)
    assert len(kept) == g.MAX_MEETINGS
    assert (kept[0]["date"], kept[-1]["date"]) == (days_[0], days_[g.MAX_MEETINGS - 1])     # the 60 soonest


def test_county_bad_agenda_url_becomes_null(directory):
    for url in ("http://mcgtn.org/a.pdf", "javascript:alert(1)", "https://u:p@mcgtn.org/a.pdf"):
        m = run(directory, agendas=agendas_with("x", url=url))[COUNTY_ID]["meetings"][0]
        assert m["agenda"]["url"] is None and m["items"][0]["source"]["url"] is None


def test_checked_at_must_be_aware(directory):
    with pytest.raises(ValueError):
        nc.clarksville_feeds(directory, {"city": (facts_with(), [])}, None, date(2026, 11, 19),
                             checked_at=datetime(2026, 11, 19))


def test_bad_feed_stops_the_build(directory, monkeypatch):
    monkeypatch.setattr(nc, "_feed", lambda *a: {"schema": "daylight-upcoming/1", "body": {"id": COUNTY_ID},
                                                 "meetings": [], "extra": 1})
    with pytest.raises(nc.FeedError):
        run(directory)


# --- section 11.3 item 5: the county route and the review stamp (privacy-withhold/national-prefix) --------------

def test_11_3_5_county_key_other_than_county_stops_the_build(directory, monkeypatch):
    monkeypatch.setitem(config.SITE, "county_key", "city")
    with pytest.raises(nc.FeedError, match="county_key"):
        run(directory, agendas=agendas_with("SENTINEL-ITEM-TEXT"))


def test_11_3_5_council_body_key_county_stops_the_build(directory, monkeypatch):
    monkeypatch.setattr(config, "COUNCILS", [*config.COUNCILS, {**nc.council_cfg("city"), "body_key": "county"}])
    with pytest.raises(nc.FeedError, match="body_key is 'county'"):
        run(directory, agendas=agendas_with("SENTINEL-ITEM-TEXT"))


def test_11_3_5_feeds_carry_review(directory):
    feeds = run(directory, agendas=agendas_with("SENTINEL-ITEM-TEXT"))
    rows = {r.gov: r.digest for r in nat.SHOWN_REVIEWED}
    assert feeds[COUNTY_ID]["review"] == rows[COUNTY_ID] and feeds[COUNCIL_ID]["review"] == rows[COUNCIL_ID]
    withheld = nat.Directory(govs=tuple(entry(directory, i, items="withheld", review=None)
                                        for i in (COUNCIL_ID, COUNTY_ID)))
    feeds = run(withheld, agendas=agendas_with("SENTINEL-ITEM-TEXT"))
    assert feeds[COUNTY_ID]["review"] is None and feeds[COUNCIL_ID]["review"] is None
    assert "SENTINEL-ITEM-TEXT" not in json.dumps(feeds)


def test_11_3_5_shown_without_a_review_reads_no_items(directory):
    """items: shown but no review digest (an entry not from load_directory): not shown, nothing read."""
    d = nat.Directory(govs=(entry(directory, COUNTY_ID, review=None),))
    feed = run(d, agendas=agendas_with("SENTINEL-ITEM-TEXT"))[COUNTY_ID]
    assert feed["review"] is None and "SENTINEL-ITEM-TEXT" not in json.dumps(feed)
    assert all(m["items_withheld"] and m["item_count"] is None for m in feed["meetings"])


def test_11_3_5_schema_refuses_review_null_with_items(directory):
    feed = run(directory, agendas=agendas_with("SENTINEL-ITEM-TEXT"))[COUNTY_ID]
    assert nc.feed_errors(feed) == []
    bad = copy.deepcopy(feed)
    bad["review"] = None
    assert nc.feed_errors(bad)                              # items present, review null
    bad["meetings"][0].update(items=[], item_count=None)
    assert nc.feed_errors(bad)                              # items_withheld still false
    bad["meetings"][0]["items_withheld"] = True
    assert nc.feed_errors(bad) == []
    for review in ("x" * 64, "ABC", 1):
        assert nc.feed_errors(dict(feed, review=review))
    assert nc.feed_errors({k: v for k, v in feed.items() if k != "review"})


def test_11_3_5_bind_counts_reported(directory):
    bind = {}
    nc.clarksville_feeds(directory, {"city": (facts_with(), [])}, agendas_with("SENTINEL-ITEM-TEXT"),
                         date(2026, 11, 19), checked_at=CHECKED, bind_counts=bind)
    assert set(bind) == {COUNCIL_ID, COUNTY_ID}
    assert all(b.withheld_stripped == 0 and b.review_mismatch == 0 for b in bind.values())
