# ruff: noqa: E501
"""The morning note's digest (Daylight M3 T1, sitegen/morning.py; docs/architecture/morning-note.md): the window rule
on the collectors' first_fetched_at, the four lists and select(), the zoning rule (printed district or ward, the county
link by exact case number), unconfirmed motions, the manifest check, the provider seam and the file budget. FIXTURE
facts throughout: the county fixture, the RPC agenda reader's own output on a real agenda (test_rpc_pages.py) with
made-up motions, a made-up county agendas file and the finance fixture, each source given a made-up manifest row."""
import copy
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS
from sitegen import config, fin_views, morning, rpc, views
from sitegen.build import BuildError, build, site_url_problems
from test_rpc_pages import rpc_facts
from test_site_neutrality import BANNED

FIN = Path(__file__).resolve().parent.parent / "site" / "fixtures" / "finance.sample.json"
D = date(2026, 11, 11)                     # the note under test: window [Nov 10 07:00, Nov 11 07:00) Central (UTC-6)
IN_D = "2026-11-10T20:00:00+00:00"         # 14:00 Central on Nov 10: in D's window
AT_0659 = "2026-11-11T12:59:00+00:00"      # 06:59 Central on D: still D
AT_0700 = "2026-11-11T13:00:00+00:00"      # 07:00 Central on D: the next day's note
OLD = "2026-01-05T09:00:00+00:00"
LATE = "2026-11-11T15:00:00+00:00"         # D+1's window
MIN_0659 = "src-314626e69a4d"              # county fixture minutes (2024-12-09), first fetched 06:59 on D
MIN_0700 = "src-99d3ff2945a5"              # county fixture minutes (2024-11-04), first fetched 07:00 on D
MIN_REFETCHED = "src-14f3298444b4"         # first fetched long ago, fetched again on D (first_fetched_at unchanged)
RPC_MINUTES = "https://www.cmcrpc.com/wp2025/wp-content/uploads/2026/11/10.27.2026-RPC-Minutes.pdf"
COUNTY_AGENDA = "https://example.invalid/fixture/county-agenda-2026-11-16.pdf"
LATE_DOC = "src-ec95c284feb1"              # Riding Mowers award letter: first fetched a day after its solicitation


def mv(k, case, **kw):
    base = {"id": f"2026-10-27-regular-motion-{k}", "meeting_id": "2026-10-27-regular", "source_id": "src-fixturemin",
            "page": 2, "case": None, "case_id": f"2026-10-27-regular-{case.lower()}", "kind": "Motion for approval",
            "moved_by": "Fixture Mover", "seconded_by": "Fixture Seconder", "nays": ["Fixture Nay"], "abstained": [],
            "outcome": "Motion passes for approval 5-1", "tally": "5-1", "confirmed": True, "reasons": []}
    return {**base, **kw}


def manifest_rows(county, rpcf, agendas, fin):
    rows = []
    for s in county["sources"]:
        when = {MIN_0659: AT_0659, MIN_0700: AT_0700, MIN_REFETCHED: OLD}[s["id"]]
        rows.append({"url": s["url"], "first_fetched_at": when, "kind": s["kind"]})
    rows += [{"url": s["url"], "first_fetched_at": IN_D} for s in rpcf["sources"] + agendas["sources"]]
    rows += [{"url": s["url"], "first_fetched_at": LATE if s["id"] == LATE_DOC else IN_D} for s in fin["sources"]]
    return rows


@pytest.fixture(scope="module")
def inputs(tmp_path_factory):
    d = tmp_path_factory.mktemp("morning")
    rpcf = rpc_facts(d)
    rpcf["sources"].append({"id": "src-fixturemin", "url": RPC_MINUTES, "sha256": "0" * 64, "kind": "minutes",
                            "meeting_date": "2026-10-27", "fetched_at": "2026-11-10", "pages": 3,
                            "text_layer": "text", "format": "pdf", "read_by": "text layer"})
    m = next(m for m in rpcf["meetings"] if m["id"] == "2026-10-27-regular")
    m.update({"minutes_source_id": "src-fixturemin", "minutes_read_by": "text layer", "minutes_date": "2026-10-27"})
    rpcf["motions"] = [
        mv(1, "Z-19-2026"),                                                    # confirmed
        mv(2, "Z-30-2026", confirmed=False, reasons=["mover is not one member present"]),
        mv(3, "Z-31-2026", confirmed=None),                                    # anything but true: not confirmed
        mv(4, "ZO-2A-2026"),                                                   # prints neither district nor ward
    ]
    (d / "rpc.json").write_text(json.dumps(rpcf), encoding="utf-8")
    src = {"id": "src-bbbbbbbbbbbb", "url": COUNTY_AGENDA, "sha256": "b" * 64, "kind": "agenda",
           "label": "2026 November Formal", "fetched_at": "2026-11-10", "pages": 9}
    items = [{"id": "x/26-11-1", "number": "26-11-1", "printed": "26-11-1", "page": 2, "year": 2026,
              "title": "Resolution Amending the Fiscal Year 2027 Budget", "section": "RESOLUTIONS", "link_basis": "number"},
             {"id": "x/CZ-12-2026", "number": "CZ-12-2026", "printed": "CZ-12-2026", "page": 4, "year": 2026,
              "title": "FIXTURE: Application of a Fixture Applicant", "section": "ZONING", "link_basis": "number"}]
    agendas = {"body": "Montgomery County Commission", "index_url": "https://montgomerytn.gov/commission/agenda",
               "meetings": [{"id": "2026-11-16-formal", "date": "2026-11-16", "kind": "formal", "source_id": src["id"],
                             "date_page": 1, "items": items}],
               "sources": [src], "skipped": [], "problems": []}
    (d / "agendas.json").write_text(json.dumps(agendas), encoding="utf-8")
    county = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fin = json.loads(FIN.read_text(encoding="utf-8"))
    (d / "manifest.json").write_text(json.dumps(manifest_rows(county, rpcf, agendas, fin)), encoding="utf-8")
    return {"dir": d, "rpc": {**rpc.load_config("cmc-rpc"), "facts_path": d / "rpc.json"},
            "agendas": d / "agendas.json", "manifests": [d / "manifest.json"], "rpcf": rpcf, "county": county}


def make(inputs, out, today=D + timedelta(days=1), target="pages", **kw):
    args = dict(seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, finance_path=FIN, rpc=inputs["rpc"],
                county_agendas=inputs["agendas"], morning_manifests=inputs["manifests"], today=today, target=target)
    args.update(kw)
    return build(FIXTURE, out, **args)


@pytest.fixture(scope="module")
def site(inputs, tmp_path_factory):
    out = tmp_path_factory.mktemp("msite") / "build" / "site"
    result = make(inputs, out)
    return {"out": out, "result": result}


def note(site, d: date) -> dict:
    return json.loads((site["out"] / "morning" / f"{d.isoformat()}.json").read_text(encoding="utf-8"))


def ids(entries) -> set:
    return {e["id"] for e in entries}


def by_id(n: dict) -> dict:
    return {e["id"]: e for e in n["entries"]}


# ------------------------------------------------------------------ files and the contract
def test_files_for_keep_days_and_latest(site):
    folder = site["out"] / "morning"
    keep = config.SITE["morning_note"]["keep_days"]
    tomorrow = D.toordinal() + 1
    want = {f"{date.fromordinal(tomorrow - k).isoformat()}.json" for k in range(keep)} | {"latest.json", "index.html"}
    assert {p.name for p in folder.iterdir()} == want
    assert (folder / "latest.json").read_text() == (folder / f"{date.fromordinal(tomorrow).isoformat()}.json").read_text()
    assert site["result"]["morning"]["date"] == date.fromordinal(tomorrow).isoformat()


def test_contract_shape(site):
    n = note(site, D)
    assert n["schema"] == "morning-note/1" and n["date"] == "2026-11-11"
    assert n["window"] == {"from": "2026-11-10T07:00-06:00", "to": "2026-11-11T07:00-06:00"}
    assert n["lists"] == [{"key": x["key"], "label": x["label"]} for x in config.SITE["morning_note"]["lists"]]
    assert n["entries"]
    for e in n["entries"]:
        assert set(e) >= {"id", "lists", "kind", "body", "body_name", "meeting_date", "title", "recorded", "district",
                          "ward", "seat_body", "href", "source"}
        assert e["kind"] in morning.KINDS and e["lists"] and set(e["lists"]) <= set(morning.LIST_KEYS)
        assert e["source"]["url"].startswith("https://")
    assert len(ids(n["entries"])) == len(n["entries"])


# ------------------------------------------------------------------ the window rule
def test_0659_is_today_and_0700_is_tomorrow(site, inputs):
    county = inputs["county"]
    at = {rc["id"]: rc["source_id"] for rc in county["roll_calls"]}
    today_ids, next_ids = ids(note(site, D)["entries"]), ids(note(site, date(2026, 11, 12))["entries"])
    seen = {MIN_0659: 0, MIN_0700: 0}
    for rc, sid in at.items():
        eid = f"county/vote/{rc}"
        if sid == MIN_0659:
            assert eid in today_ids and eid not in next_ids
        elif sid == MIN_0700:
            assert eid in next_ids and eid not in today_ids
        if sid in seen:
            seen[sid] += 1
    assert all(seen.values()), seen     # each side of the cutoff was checked on at least one roll call


def test_note_day_boundaries():
    tz = config.SITE["site_timezone"]
    assert morning.note_day(datetime.fromisoformat(AT_0659), "07:00", tz) == D
    assert morning.note_day(datetime.fromisoformat(AT_0700), "07:00", tz) == date(2026, 11, 12)


@pytest.mark.parametrize("d, hours, start, end, inside", [
    # clocks fall back at 02:00 on Nov 1: 01:30 happens twice (06:30 and 07:30 UTC), both in Nov 1's note
    (date(2026, 11, 1), 25, "2026-10-31T07:00-05:00", "2026-11-01T07:00-06:00",
     ["2026-11-01T06:30:00+00:00", "2026-11-01T07:30:00+00:00"]),
    # clocks spring forward at 02:00 on Mar 8: 01:30 CST is 07:30 UTC, 03:30 CDT is 08:30 UTC
    (date(2026, 3, 8), 23, "2026-03-07T07:00-06:00", "2026-03-08T07:00-05:00",
     ["2026-03-08T07:30:00+00:00", "2026-03-08T08:30:00+00:00"]),
])
def test_window_across_a_dst_change(d, hours, start, end, inside):
    tz = config.SITE["site_timezone"]
    a, b = morning.window(d, "07:00", tz)
    assert b.astimezone(timezone.utc) - a.astimezone(timezone.utc) == timedelta(hours=hours)
    assert (morning._stamp(a), morning._stamp(b)) == (start, end)
    # note_day agrees with window() on both edges and inside the repeated or skipped hour
    assert morning.note_day(a, "07:00", tz) == d and morning.note_day(b, "07:00", tz) == d + timedelta(days=1)
    assert morning.note_day(b - timedelta(minutes=1), "07:00", tz) == d
    for at in map(datetime.fromisoformat, inside):
        assert a <= at < b and morning.note_day(at, "07:00", tz) == d


def test_refetched_document_does_not_reappear(site, tmp_path, inputs):
    """first_fetched_at never changes: a document fetched again (a newer fetched_at) is in no recent note. Should a URL
    sit in two manifests, the earliest first_fetched_at wins."""
    for k in range(7):
        n = json.loads((site["out"] / "morning" / f"{date.fromordinal(D.toordinal() + 1 - k)}.json").read_text())
        assert not [e for e in n["entries"] if e["source"]["url"].startswith(
            next(s["url"] for s in inputs["county"]["sources"] if s["id"] == MIN_REFETCHED))]
    url = "https://example.invalid/a.pdf"
    (tmp_path / "a.json").write_text(json.dumps([{"url": url, "first_fetched_at": OLD, "fetched_at": LATE}]))
    (tmp_path / "b.json").write_text(json.dumps([{"url": url, "first_fetched_at": LATE}]))
    first = morning.first_fetched([tmp_path / "b.json", tmp_path / "a.json"])
    assert first[url] == datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)


def test_empty_day_writes_empty_entries(site):
    n = note(site, date(2026, 11, 10))
    assert n["entries"] == [] and n["unplaced_zoning"] == 0


# ------------------------------------------------------------------ lists and the zoning rule
def test_lists(site):
    n = by_id(note(site, D))
    assert n["county/item/26-11-1/2026-11-16-formal"]["lists"] == ["seats", "budget"]
    assert n["contracts/solicitation/sol-road-salt-fixture"]["lists"] == ["contracts"]
    assert n["finance/book/" + json.loads(FIN.read_text())["books"][0]["id"]]["lists"] == ["budget"]
    assert all(e["lists"] == ["zoning"] for e in n.values() if e["body"] == "rpc")
    # subdivision and variance cases are in no list
    assert not [i for i in n if "-s-" in i or "-v-" in i or "-sr-" in i]
    later = by_id(note(site, date(2026, 11, 12)))
    assert later["contracts/document/sol-riding-mowers-fixture/doc-4c5912f33a"]["kind"] == "document"
    assert "contracts/solicitation/sol-riding-mowers-fixture" in n


def test_zoning_matches_by_district_and_by_ward_never_neither(site):
    n = note(site, D)
    z16 = "rpc/item/2026-10-27-regular-z-30-2026/2026-10-27-regular"      # district 16, ward 3
    zo = "rpc/item/2026-10-27-regular-zo-2a-2026/2026-10-27-regular"      # neither printed
    assert z16 in ids(morning.select(n, ["zoning"], {"district": 16, "ward": None}))
    assert z16 in ids(morning.select(n, ["zoning"], {"district": None, "ward": 3}))
    assert z16 not in ids(morning.select(n, ["zoning"], {"district": 15, "ward": 4}))
    assert z16 not in ids(morning.select(n, ["zoning"], {}))
    for d_ in range(1, 22):
        for w in range(1, 13):
            assert zo not in ids(morning.select(n, ["zoning"], {"district": d_, "ward": w}))
            assert zo not in ids(morning.select(n, ["zoning", "seats", "budget", "contracts"], {"district": d_, "ward": w}))
    # the agenda's ZO-2A and CZO-1 cases and the motion on ZO-2A print neither: three entries, two cases
    unplaced = [e for e in n["entries"] if "zoning" in e["lists"] and e["district"] is None and e["ward"] is None]
    assert len(unplaced) == 3 and {e["case"] for e in unplaced} == {"ZO-2A-2026", "CZO-1-2026"}
    assert n["unplaced_zoning"] == 2
    assert n["unplaced_text"] == config.SITE["morning_note"]["text"]["unplaced_zoning"].format(n=2)


def test_linked_county_cz_item_inherits_its_case_district(site):
    e = by_id(note(site, D))["county/item/CZ-12-2026/2026-11-16-formal"]
    assert e["lists"] == ["zoning", "seats"] and e["district"] == 6 and e["ward"] is None
    n = note(site, D)
    assert e["id"] in ids(morning.select(n, ["zoning"], {"district": 6}))
    assert e["id"] not in ids(morning.select(n, ["zoning"], {"district": 7}))
    # an unlinked county item is never a zoning entry
    assert "zoning" not in by_id(n)["county/item/26-11-1/2026-11-16-formal"]["lists"]


def test_seats_follow_the_body_of_each_stored_seat(site):
    n = note(site, D)
    county = {e["id"] for e in n["entries"] if e["seat_body"] == "district"}
    assert county and ids(morning.select(n, ["seats"], {"district": 3})) == county
    assert ids(morning.select(n, ["seats"], {"ward": 3})) == set()     # no council in this build
    assert ids(morning.select(n, ["seats"], {})) == set()


def test_budget_and_contracts_by_membership_only(site):
    n = note(site, D)
    assert ids(morning.select(n, ["contracts"], {})) == {e["id"] for e in n["entries"] if "contracts" in e["lists"]}
    assert ids(morning.select(n, ["budget"], {})) == {e["id"] for e in n["entries"] if "budget" in e["lists"]}
    assert morning.select(n, [], {"district": 6, "ward": 3}) == []


# ------------------------------------------------------------------ votes: only from the record, only when confirmed
def test_unconfirmed_motions_carry_no_outcome_tally_or_names(site):
    n = by_id(note(site, D))
    text = config.SITE["morning_note"]["text"]
    ok = n["rpc/vote/2026-10-27-regular-motion-1"]
    assert ok["confirmed"] is True and ok["outcome"] == "Motion passes for approval 5-1" and ok["tally"] == "5-1"
    assert ok["recorded"] == text["vote"]
    for k in (2, 3):
        e = n[f"rpc/vote/2026-10-27-regular-motion-{k}"]
        assert e["confirmed"] is False and e["outcome"] is None and e["tally"] is None
        assert e["recorded"] == text["vote_unconfirmed"]
    county_unverified = n["county/vote/rc-314626e6-p16-1"]
    assert county_unverified["outcome"] is None and county_unverified["tally"] is None
    assert county_unverified["recorded"] == text["vote_unconfirmed"]


def test_no_names_in_any_note(site, inputs):
    raw = "".join(p.read_text(encoding="utf-8") for p in (site["out"] / "morning").glob("*.json"))
    for name in ("Fixture Mover", "Fixture Seconder", "Fixture Nay"):
        assert name not in raw
    for o in inputs["county"]["officials"]:
        assert o["name"] not in raw and o["id"] not in raw   # (fixture surnames are "Example", a word titles print)


def banned_in_own_text(n: dict) -> list[str]:
    """The neutrality scan over our own words only (morning.own_text): verbatim titles and URLs are the record's."""
    return [t for t in morning.own_text(n) if BANNED.search(t)]


def test_own_text_passes_the_neutrality_scan(site):
    for f in (site["out"] / "morning").glob("*.json"):
        n = json.loads(f.read_text(encoding="utf-8"))
        assert not banned_in_own_text(n), f
    assert morning.own_text(note(site, D))     # the scan reads something


@pytest.mark.parametrize("where", ["text", "label"])
def test_a_banned_word_in_our_own_text_still_fails(inputs, tmp_path, monkeypatch, where):
    """A record's title may print any word (left out of the scan); our own connective text or label may not."""
    mn = copy.deepcopy(config.SITE["morning_note"])
    if where == "text":
        mn["text"]["agenda_item"] = "Ranked on the agenda"
    else:
        mn["lists"][0]["label"] = "Best zoning near me"
    monkeypatch.setitem(config.SITE, "morning_note", mn)
    make(inputs, tmp_path / "site")
    n = json.loads((tmp_path / "site" / "morning" / f"{D.isoformat()}.json").read_text(encoding="utf-8"))
    assert banned_in_own_text(n)


def test_titles_we_make_are_scanned(site):
    """A meeting's label (minutes with nothing itemised) is our title, not the record's: the scan reads it."""
    n = {**note(site, D), "entries": [e for d in morning.documents(views.Index(shared_source_facts()["facts"]))
                                       for e in d["entries"]]}
    ours = [e for e in n["entries"] if e["title_ours"]]
    assert ours and all(e["kind"] == "document" for e in ours)
    assert all(e["title"] in morning.own_text(n) for e in ours)
    assert not [e for e in n["entries"] if not e["title_ours"] and e["title"] in morning.own_text(n)]
    assert banned_in_own_text({**n, "entries": [dict(ours[0], title="2024-12-09, best meeting")]})


def test_a_record_title_is_not_scanned(site):
    n = note(site, D)
    titled = dict(n["entries"][0], title="the best use of this land, 50%",
                  source={"url": "https://example.invalid/a%20b.pdf", "page": 1})
    assert not banned_in_own_text({**n, "entries": [titled]})


# ------------------------------------------------------------------ backfill guard
def test_a_collectors_initial_run_is_a_backfill_day(inputs, tmp_path):
    """The RPC, agendas and finance rows in a manifest of their own, all first fetched on D: that manifest's
    initial run, so D is a backfill day: no entries to send, the counts kept."""
    rows = json.loads(inputs["manifests"][0].read_text())
    county_urls = {s["url"] for s in inputs["county"]["sources"]}
    (tmp_path / "a.json").write_text(json.dumps([r for r in rows if r["url"] in county_urls]))
    (tmp_path / "b.json").write_text(json.dumps([r for r in rows if r["url"] not in county_urls]))
    out = tmp_path / "site"
    make(inputs, out, morning_manifests=[tmp_path / "a.json", tmp_path / "b.json"])
    n = json.loads((out / "morning" / "2026-11-11.json").read_text())
    assert n["backfill"] is True and n["entries"] == [] and n["unplaced_zoning"] == 0
    assert n["counts"]["entries"] > 0 and n["counts"]["lists"]["zoning"] > 0 and n["counts"]["unplaced_zoning"] == 2
    assert morning.select(n, morning.LIST_KEYS, {"district": 6, "ward": 3}) == []


def test_ordinary_day_is_not_backfill_and_counts_match(site):
    n = note(site, D)
    assert n["backfill"] is False and n["entries"]
    assert n["counts"]["entries"] == len(n["entries"]) <= config.SITE["morning_note"]["backfill"]["max_entries"]
    assert n["counts"]["lists"]["contracts"] == sum(1 for e in n["entries"] if "contracts" in e["lists"])


def test_more_than_max_entries_is_a_backfill_day(site, inputs):
    n = note(site, D)
    first = {"https://example.invalid/bulk.pdf": datetime.fromisoformat(IN_D)}
    many = [dict(n["entries"][0], id=f"x/{k}") for k in range(config.SITE["morning_note"]["backfill"]["max_entries"] + 1)]
    big = morning.day(D, [{"url": "https://example.invalid/bulk.pdf", "entries": many}], first)
    assert big["backfill"] is True and big["entries"] == [] and big["counts"]["entries"] == len(many)
    ok = morning.day(D, [{"url": "https://example.invalid/bulk.pdf", "entries": many[:-1]}], first)
    assert ok["backfill"] is False and len(ok["entries"]) == len(many) - 1


def test_bulk_urls_are_the_first_hours_of_each_manifest(tmp_path):
    rows = [{"url": "https://example.invalid/1.pdf", "first_fetched_at": "2026-11-01T10:00:00+00:00"},
            {"url": "https://example.invalid/2.pdf", "first_fetched_at": "2026-11-03T09:59:00+00:00"},
            {"url": "https://example.invalid/3.pdf", "first_fetched_at": "2026-11-03T10:00:00+00:00"}]
    (tmp_path / "m.json").write_text(json.dumps(rows))
    assert morning.bulk_urls([tmp_path / "m.json"], 48) == {"https://example.invalid/1.pdf", "https://example.invalid/2.pdf"}


# ------------------------------------------------------------------ every document has a manifest row
def test_document_without_a_manifest_row_fails_the_build(inputs, tmp_path):
    rows = json.loads(inputs["manifests"][0].read_text())
    (tmp_path / "m.json").write_text(json.dumps([r for r in rows if r["url"] != COUNTY_AGENDA]))
    with pytest.raises(BuildError, match="no row in any collector manifest.*county-agenda-2026-11-16"):
        make(inputs, tmp_path / "site", morning_manifests=[tmp_path / "m.json"])


def test_manifest_row_without_first_fetched_at_fails(tmp_path):
    (tmp_path / "m.json").write_text(json.dumps([{"url": "https://example.invalid/x.pdf", "first_fetched_at": None}]))
    with pytest.raises(morning.MorningError, match="first_fetched_at"):
        morning.first_fetched([tmp_path / "m.json"])


def test_manifest_row_without_url_fails_clearly(tmp_path):
    (tmp_path / "m.json").write_text(json.dumps([{"first_fetched_at": IN_D}]))
    for read in (morning.first_fetched, lambda p: morning.bulk_urls(p, 48)):
        with pytest.raises(morning.MorningError, match="row 1 has no url"):
            read([tmp_path / "m.json"])
    (tmp_path / "n.json").write_text(json.dumps([{"url": "https://example.invalid/x.pdf", "first_fetched_at": "x"}]))
    with pytest.raises(morning.MorningError, match="first_fetched_at"):
        morning.bulk_urls([tmp_path / "n.json"], 48)     # bulk_urls checks rows the same way


def test_fixture_build_without_manifests_writes_no_note(built):
    assert not (built / "morning").exists()


# ------------------------------------------------------------------ the provider seam
def seam(**kw):
    cfg = copy.deepcopy(config.SITE)
    cfg["morning_note"].update(kw)
    return morning.problems(cfg)


def test_config_as_shipped_is_off_and_clean():
    assert config.SITE["morning_note"]["enabled"] is False and not config.SITE["morning_note"]["form_action"]
    assert morning.problems(config.SITE) == [] and site_url_problems(config.SITE) == []


def test_enabled_needs_https_form_action_and_privacy_url():
    assert any("form_action" in p for p in seam(enabled=True, privacy_url="https://example.org/privacy"))
    assert any("privacy_url" in p for p in seam(enabled=True, form_action="https://example.org/subscribe"))
    assert any("form_action" in p for p in seam(enabled=True, form_action="http://example.org/s",
                                                  privacy_url="https://example.org/privacy"))
    assert seam(enabled=True, form_action="https://example.org/subscribe", privacy_url="https://example.org/p",
                provider="Example Mail") == []


def test_form_action_refused_while_disabled_and_shape_checks():
    assert any("must be empty" in p for p in seam(form_action="https://example.org/subscribe"))
    assert seam(enabled="yes")
    assert seam(cutoff="7am") and seam(keep_days=0) and seam(lists=[{"key": "everything", "label": "X"}])
    assert seam(form_fields={"email": "email"})
    cfg = copy.deepcopy(config.SITE)
    cfg["morning_note"]["form_action"] = "https://example.org/subscribe"
    assert any("morning_note" in p for p in site_url_problems(cfg))


# ------------------------------------------------------------------ file budget
def test_preview_build_writes_no_note_and_stays_under_its_cap(inputs, tmp_path):
    result = make(inputs, tmp_path / "site", target="preview")
    assert not (tmp_path / "site" / "morning").exists() and result["morning"] is None
    assert result["export"] is True and result["files_with_export"] <= config.max_files("preview")


def test_preview_still_over_its_cap_leaves_the_export_out(inputs, tmp_path, monkeypatch, capsys):
    full = make(inputs, tmp_path / "a", target="preview")
    monkeypatch.setitem(config.MAX_FILES_BY_TARGET, "preview", full["files_with_export"] - 1)
    out = tmp_path / "b"
    r = make(inputs, out, target="preview")
    assert r["export"] is False and r["files_with_export"] <= config.max_files("preview")
    assert "building again without the open-data export" in capsys.readouterr().err
    for page in ("data.html", "about.html"):
        html = (out / page).read_text(encoding="utf-8")
        assert 'href="data/' not in html and "left out of this preview" in html
    assert 'href="data/' in (tmp_path / "a" / "data.html").read_text(encoding="utf-8")


def test_preview_without_the_export_links_no_data_file_on_any_page(inputs, tmp_path, monkeypatch):
    """morning-digest/preview-export-links: the finance and contracts indexes link data/ only when the export goes
    with the build. The finance fixture links none in any build, so it is built here as if it were real."""
    init = fin_views.Finance.__init__

    def as_real(self, *a, **kw):
        init(self, *a, **kw)
        self.fixture = False
    monkeypatch.setattr(fin_views.Finance, "__init__", as_real)
    link = re.compile(r'href="(?:\.\./)*data/')
    full = make(inputs, tmp_path / "a", target="preview")
    for page in ("contracts/index.html", "finance/index.html"):
        assert link.search((tmp_path / "a" / page).read_text(encoding="utf-8")), page    # the check bites
    monkeypatch.setitem(config.MAX_FILES_BY_TARGET, "preview", full["files_with_export"] - 1)
    out = tmp_path / "b"
    assert make(inputs, out, target="preview")["export"] is False
    pages = list(out.rglob("*.html"))
    assert len(pages) > 50
    assert not [p.relative_to(out).as_posix() for p in pages if link.search(p.read_text(encoding="utf-8"))]


def test_preview_without_the_export_removes_an_earlier_export(inputs, tmp_path, monkeypatch):
    """morning-digest/preview-stale-export: the preview recipe reuses build/site, so an earlier export may sit in
    data/. A build without the export removes it: nothing stale is published, nor counted against the cap."""
    full = make(inputs, tmp_path / "a", target="preview")
    out = tmp_path / "build" / "site"
    for k in range(12):
        (out / "data" / "old").mkdir(parents=True, exist_ok=True)
        (out / "data" / ("old" if k % 2 else "") / f"stale-{k}.csv").write_text("x\n")
    monkeypatch.setitem(config.MAX_FILES_BY_TARGET, "preview", full["files_with_export"] - 1)
    r = make(inputs, out, target="preview")
    assert r["export"] is False and not (out / "data").exists()
    published = json.loads((out.parent / "publish-files.json").read_text(encoding="utf-8"))
    assert not [k for k in published if k.startswith("data/")]


def test_a_preview_with_the_export_keeps_data(inputs, tmp_path):
    """The collector's export in data/ is still left alone when the export goes with the build."""
    out = tmp_path / "site"
    (out / "data").mkdir(parents=True)
    (out / "data" / "facts.json").write_text("{}")
    assert make(inputs, out, target="preview")["export"] is True
    assert (out / "data" / "facts.json").read_text() == "{}"


# ------------------------------------------------------------------ one source, two meetings
def shared_source_facts() -> dict:
    """The county fixture with its 2024-12-09 minutes also named by a made-up 2025-01-13 meeting that holds one of
    its roll calls (real data: src-7325525d58ca is the source of 2020-02-10-formal and 2020-03-09-formal), its
    2024-10-07 minutes (no roll call) named by a second meeting too, and one agenda named by two meetings."""
    f = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ms = {m["id"]: m for m in f["meetings"]}
    f["meetings"].append({**ms["2024-12-09-formal"], "id": "2025-01-13-formal", "date": "2025-01-13"})
    f["meetings"].append({**ms["2024-10-07-formal"], "id": "2024-10-21-formal", "date": "2024-10-21"})
    rc = next(r for r in f["roll_calls"] if r["source_id"] == MIN_0659)
    rc["meeting_id"] = "2025-01-13-formal"
    f["sources"].append({**next(s for s in f["sources"] if s["id"] == MIN_0659), "id": "src-agenda000001",
                         "kind": "agenda", "url": "https://example.invalid/fixture/agenda-two-meetings.pdf"})
    for mid in ("2024-11-04-formal", "2025-01-13-formal"):
        next(m for m in f["meetings"] if m["id"] == mid)["agenda_source_id"] = "src-agenda000001"
    ev = next(e for e in f["item_events"] if e["meeting_id"] == "2024-11-04-formal")
    f["item_events"] += [{**ev, "id": f"ev-agenda-{mid}", "ref": None, "meeting_id": mid, "source_id": "src-agenda000001",
                          "page": 3} for mid in ("2024-11-04-formal", "2025-01-13-formal")]
    return {"facts": f, "rc": rc, "item": ev["item_id"]}


def test_each_entry_takes_its_own_meeting_when_two_meetings_share_a_source():
    """morning-digest/vote-meeting-date: a vote's date, label and link are its own meeting's, not those of the first
    meeting naming the minutes."""
    x = shared_source_facts()
    ix = views.Index(x["facts"])
    docs = morning.documents(ix)
    entries = {e["id"]: e for d in docs for e in d["entries"]}
    moved = entries[f"county/vote/{x['rc']['id']}"]
    assert moved["meeting_date"] == "2025-01-13"
    if not ix.items.get(x["rc"].get("item_id") or ""):
        assert moved["title"] == "2025-01-13, formal meeting" and moved["href"] == "meetings/2025-01-13-formal.html"
    stayed = [e for e in entries.values() if e["kind"] == "vote" and e["source"]["url"].startswith(
        ix.sources[MIN_0659]["url"]) and e["id"] != moved["id"]]
    assert stayed and all(e["meeting_date"] == "2024-12-09" for e in stayed)
    # every vote entry: the date of its roll call's or motion's own meeting
    facts = {f"county/vote/{f['id']}": f for f in x["facts"]["roll_calls"] + x["facts"]["motions"]}
    for eid, e in entries.items():
        if e["kind"] == "vote":
            assert e["meeting_date"] == ix.meetings[facts[eid]["meeting_id"]]["date"], eid
    # an agenda named by two meetings: one entry for each meeting's printing of the item, each with its own date
    item = {k: v for k, v in entries.items() if k.startswith(f"county/item/{x['item']}/")}
    assert {(k, v["meeting_date"]) for k, v in item.items()} == {
        (f"county/item/{x['item']}/2024-11-04-formal", "2024-11-04"),
        (f"county/item/{x['item']}/2025-01-13-formal", "2025-01-13")}
    # minutes with nothing itemised, named by two meetings: the document once for each meeting
    old = next(d for d in docs if d["url"] == ix.sources[MIN_REFETCHED]["url"])
    assert sorted((e["meeting_date"], e["title"], e["href"]) for e in old["entries"]) == [
        ("2024-10-07", "2024-10-07, formal meeting", "meetings/2024-10-07-formal.html"),
        ("2024-10-21", "2024-10-21, formal meeting", "meetings/2024-10-21-formal.html")]
    assert len({e["id"] for d in docs for e in d["entries"]}) == sum(len(d["entries"]) for d in docs)


# ------------------------------------------------------------------ one source of text, config guards
def test_unplaced_text_is_singular_for_one_case_and_comes_from_text():
    # morning-text/one-source: the preview page prints the note's own unplaced_text; the page block has no copy
    t = config.SITE["morning_note"]["text"]
    assert morning.unplaced_text(0) == ""
    assert morning.unplaced_text(1) == t["unplaced_zoning_one"]
    assert morning.unplaced_text(3) == t["unplaced_zoning"].format(n=3)
    page = config.SITE["morning_note"]["page"]
    assert not [k for k in page if k.startswith("unplaced") and k != "unplaced_link"]


@pytest.mark.parametrize("key", sorted(morning.PAGE_KEYS))
def test_every_page_key_is_validated(key):
    cfg = copy.deepcopy(config.SITE)
    del cfg["morning_note"]["page"][key]
    assert f"morning_note.page.{key} must be set" in morning.problems(cfg)


def test_page_text_keeps_its_placeholders_and_must_be_a_mapping():
    cfg = copy.deepcopy(config.SITE)
    cfg["morning_note"]["page"]["preview_lede"] = "The note for {date}."
    assert {p for p in morning.problems(cfg) if "preview_lede" in p} == \
        {"morning_note.page.preview_lede must contain {from}", "morning_note.page.preview_lede must contain {to}"}
    assert any("page must be a mapping" in p for p in seam(page="text"))
    assert seam(text={**config.SITE["morning_note"]["text"], "unplaced_zoning_one": ""})


def test_a_second_council_fails_until_seats_name_a_body():
    # morning-signup/one-council: cr-your-seats keeps a ward but not its council
    cfg = copy.deepcopy(config.SITE)
    assert len(cfg["councils"]) == 1 and morning.problems(cfg) == []
    cfg["councils"] = cfg["councils"] + ["another-council"]
    assert any("supports one council" in p for p in morning.problems(cfg))
    del cfg["morning_note"]
    assert morning.problems(cfg) == []


def test_enabled_needs_a_provider_name():
    on = dict(enabled=True, form_action="https://example.org/subscribe", privacy_url="https://example.org/p")
    assert any("provider" in p for p in seam(**on))
    assert any("provider" in p for p in seam(**on, provider="  "))
    assert seam(**on, provider="Example Mail") == []


# ------------------------------------------------------------------ two votes on one item; data as of, per day
AMENDMENT = "The foregoing Amendment was Adopted by the following roll call vote:"
AS_AMENDED = "The foregoing Resolution, as Amended, was Adopted by the following roll call vote:"


def two_votes_facts() -> dict:
    """The county fixture with a second roll call on item 24-11-91 at the same meeting: the amendment, then the
    resolution as amended, each with the minutes' own outcome clause (real data: 2026-02-09, p138)."""
    f = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rc = next(r for r in f["roll_calls"] if r["id"] == "rc-99d3ff29-p8-1")
    rc["outcome_text"] = AS_AMENDED
    f["roll_calls"].append({**copy.deepcopy(rc), "id": "rc-99d3ff29-p8-0", "motion_id": None, "outcome_text": AMENDMENT})
    return f


def test_two_votes_on_one_item_carry_what_each_voted_on():
    """morning-digest/vote-entries-indistinct: the same title, date and "Recorded in the minutes", told apart by
    `vote_on`, the site's fixed label for the roll call's own outcome clause; never for an unconfirmed roll call."""
    f = two_votes_facts()
    entries = {e["id"]: e for d in morning.documents(views.Index(f)) for e in d["entries"]}
    a, b = entries["county/vote/rc-99d3ff29-p8-0"], entries["county/vote/rc-99d3ff29-p8-1"]
    same = ("title", "meeting_date", "recorded", "body_name", "href")
    assert [a[k] for k in same] == [b[k] for k in same] and a["confirmed"] and b["confirmed"]
    assert (a["vote_on"], b["vote_on"]) == ("Amendment", "Resolution, as amended")
    labels = {label for _, label in config.OUTCOME_KINDS}
    votes = [e for e in entries.values() if e["kind"] == "vote"]
    assert all("vote_on" in e and (e["vote_on"] is None or e["vote_on"] in labels) for e in votes)
    # a clause no pattern matches gives no label; an unconfirmed roll call gives none whatever its clause says
    assert entries["county/vote/rc-314626e6-p10-1"]["vote_on"] is None
    held = next(r for r in f["roll_calls"] if not views.is_verified(r))
    held["outcome_text"] = AMENDMENT
    again = {e["id"]: e for d in morning.documents(views.Index(f)) for e in d["entries"]}
    assert again[f"county/vote/{held['id']}"]["vote_on"] is None and again[f"county/vote/{held['id']}"]["outcome"] is None
    # the label is our text (config), so the neutrality scan reads it
    n = {"lists": [], "unplaced_text": "", "entries": [a]}
    assert "Amendment" in morning.own_text(n)


def test_the_preview_prints_what_a_vote_was_on(inputs, tmp_path):
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps(two_votes_facts()), encoding="utf-8")
    out = tmp_path / "build" / "site"
    args = dict(seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, finance_path=FIN, rpc=inputs["rpc"],
                county_agendas=inputs["agendas"], morning_manifests=inputs["manifests"], today=D + timedelta(days=1),
                target="pages")
    build(facts, out, **args)
    html = (out / "morning" / "index.html").read_text(encoding="utf-8")
    label = config.SITE["morning_note"]["page"]["vote_on_label"]
    assert f"{label}: Amendment</span>" in html and f"{label}: Resolution, as amended</span>" in html
    assert html.count(f"{label}: ") == 2


def test_data_as_of_is_each_days_own_newest_fetch_date():
    """morning-digest/data-as-of: the newest fetch date on or before the note's day, from every file's sources."""
    dates = ["2026-11-05", "2026-11-09", "2026-11-10T08:00:00+00:00", "2026-11-12", "", None, "unknown"]
    assert morning.as_of(date(2026, 11, 11), dates) == "2026-11-10"
    assert morning.as_of(date(2026, 11, 9), dates) == "2026-11-09"
    assert morning.as_of(date(2026, 11, 8), dates) == "2026-11-05"
    assert morning.as_of(date(2026, 11, 4), dates) == "" and morning.as_of(D, []) == ""
    assert morning.as_of(D, "2026-11-30") == "2026-11-30"          # one string: the same for every day, as given


def test_data_as_of_counts_agendas_and_finance_and_differs_by_day(inputs, tmp_path):
    # the county agendas file and the finance file each hold the only source fetched on their day
    agendas = json.loads(inputs["agendas"].read_text(encoding="utf-8"))
    agendas["sources"][0]["fetched_at"] = "2026-11-09"
    (tmp_path / "agendas.json").write_text(json.dumps(agendas), encoding="utf-8")
    fin = json.loads(FIN.read_text(encoding="utf-8"))
    for s in fin["sources"]:
        s["fetched_at"] = "2026-11-08"
    (tmp_path / "fin.json").write_text(json.dumps(fin), encoding="utf-8")
    out = tmp_path / "build" / "site"
    make(inputs, out, county_agendas=tmp_path / "agendas.json", finance_path=tmp_path / "fin.json")
    got = {p.stem: json.loads(p.read_text(encoding="utf-8"))["data_as_of"]
           for p in (out / "morning").glob("2026-*.json")}
    others = {s["fetched_at"] for s in inputs["county"]["sources"] + inputs["rpcf"]["sources"]}
    assert not others & {"2026-11-08", "2026-11-09"}
    assert got["2026-11-08"] == "2026-11-08"                               # the finance file
    assert got["2026-11-09"] == "2026-11-09"                               # the county agenda
    assert got["2026-11-12"] == max(x for x in others | {"2026-11-09"} if x <= "2026-11-12")
    assert all(v <= k for k, v in got.items()) and len(set(got.values())) > 1
