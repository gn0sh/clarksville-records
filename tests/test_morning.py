# ruff: noqa: E501
"""The morning note's digest (Daylight M3 T1, sitegen/morning.py; docs/architecture/morning-note.md): the window rule
on the collectors' first_fetched_at, the four lists and select(), the zoning rule (printed district or ward, the county
link by exact case number), unconfirmed motions, the manifest check, the provider seam and the file budget. FIXTURE
facts throughout: the county fixture, the RPC agenda reader's own output on a real agenda (test_rpc_pages.py) with
made-up motions, a made-up county agendas file and the finance fixture, each source given a made-up manifest row."""
import copy
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS
from sitegen import config, morning, rpc
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
    want = {f"{date.fromordinal(tomorrow - k).isoformat()}.json" for k in range(keep)} | {"latest.json"}
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
    for rc, sid in at.items():
        eid = f"county/vote/{rc}"
        if sid == MIN_0659:
            assert eid in today_ids and eid not in next_ids
        elif sid == MIN_0700:
            assert eid in next_ids and eid not in today_ids


def test_note_day_boundaries():
    tz = config.SITE["site_timezone"]
    assert morning.note_day(datetime.fromisoformat(AT_0659), "07:00", tz) == D
    assert morning.note_day(datetime.fromisoformat(AT_0700), "07:00", tz) == date(2026, 11, 12)


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
    # the agenda's ZO-2A and CZO-1 cases and the motion on ZO-2A print neither
    assert n["unplaced_zoning"] == 3
    assert n["unplaced_text"] == config.SITE["morning_note"]["text"]["unplaced_zoning"].format(n=3)


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


def test_no_names_and_no_banned_words(site, inputs):
    raw = "".join(p.read_text(encoding="utf-8") for p in (site["out"] / "morning").glob("*.json"))
    for name in ("Fixture Mover", "Fixture Seconder", "Fixture Nay"):
        assert name not in raw
    for o in inputs["county"]["officials"]:
        assert o["name"] not in raw and o["id"] not in raw   # (fixture surnames are "Example", a word titles print)
    assert not BANNED.search(raw)


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
    assert seam(enabled=True, form_action="https://example.org/subscribe", privacy_url="https://example.org/p") == []


def test_form_action_refused_while_disabled_and_shape_checks():
    assert any("must be empty" in p for p in seam(form_action="https://example.org/subscribe"))
    assert seam(enabled="yes")
    assert seam(cutoff="7am") and seam(keep_days=0) and seam(lists=[{"key": "everything", "label": "X"}])
    assert seam(form_fields={"email": "email"})
    cfg = copy.deepcopy(config.SITE)
    cfg["morning_note"]["form_action"] = "https://example.org/subscribe"
    assert any("morning_note" in p for p in site_url_problems(cfg))


# ------------------------------------------------------------------ file budget
def test_preview_build_keeps_today_only_and_stays_under_its_cap(inputs, tmp_path):
    result = make(inputs, tmp_path / "site", target="preview")
    folder = tmp_path / "site" / "morning"
    assert sorted(p.name for p in folder.iterdir()) == ["2026-11-12.json", "latest.json"]
    assert result["files_with_export"] <= config.max_files("preview")
