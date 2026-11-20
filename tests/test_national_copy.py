"""The D2 copy step (sitegen/national_copy.py; docs/architecture/daylight-national.md 4.6 "D2 copy step", 4.4.3 site 7,
11.1 row 16, 11.2; task D2): a national-data body file reaches digest/ only after parse, clean_feed, bind_feed against
the current directory entry, and the schema; anything else is "file missing" (page stale). Problem keys:
collector-input/json-depth-recursion, privacy-withhold/national-prefix, national/r5-not-enforced."""
import copy
import json
import os
import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml

from sitegen import build as build_mod
from sitegen import national as nat
from sitegen import national_copy as ncopy
from sitegen import national_pages as npg
from sitegen.national_clarksville import feed_errors

FIXTURE = Path(__file__).resolve().parent.parent / "site" / "fixtures" / "facts.sample.json"

GOV = "place-4799990"          # a made-up Tennessee place on Legistar (TN has page labels; no real body is named)
HOST_OK = {"date": "2026-11-18", "link": "https://github.com/gn0sh/clarksville-records/pull/1"}
ENTRY = {"gov": GOV, "also": [], "body_name": "Example Legistar Council", "state": "TN", "status": "covered",
         "official_url": "https://example.legistar.com/Calendar.aspx", "checked": "2026-11-18",
         "checked_url": "https://example.legistar.com/Calendar.aspx", "items": "withheld", "platform": "legistar",
         "legistar": {"client": "example", "body_id": 7, "tz": "America/Chicago"}, "host_ok": HOST_OK}
SENTINEL = "SENTINEL-ITEM-TEXT"


def _load(tmp_path, monkeypatch, entry, reviewed=False):
    """The entry as the directory loader returns it (shown entries get their review digest)."""
    if reviewed:
        monkeypatch.setattr(nat, "SHOWN_REVIEWED", nat.SHOWN_REVIEWED + (nat.ShownReview(entry["gov"],
                                                                                         nat.norm_entry(entry)),))
    p = tmp_path / "directory.yml"
    p.write_text(yaml.safe_dump({"schema": "daylight-directory/1", "govs": [entry]}, sort_keys=False),
                 encoding="utf-8")
    return nat.load_directory(p, nat.load_labels()).get(entry["gov"])


def _feed(review=None, items=True, **body):
    """A body file as the collector writes it (3.7: the 3.5 feed minus body.full_url)."""
    meeting = {"id": "e-101", "date": "2026-12-03", "time": "6:00 PM", "title": "City Council",
               "title_ours": False, "meeting_url": "https://example.legistar.com/MeetingDetail.aspx?ID=101",
               "agenda": {"state": "final", "url": "https://example.legistar.com/View.ashx?M=A&ID=101",
                          "status_as_posted": "Final"},
               "may_be_incomplete": True, "items_withheld": not items, "item_count": 1 if items else None,
               "items": [{"seq": 1, "number": "R-1", "text": SENTINEL,
                          "source": {"url": "https://example.legistar.com/View.ashx?M=A&ID=101", "page": None}}]
               if items else []}
    return {"schema": "daylight-upcoming/1", "review": review,
            "body": {"id": GOV, "name": "Example Legistar Council", "tz": "America/Chicago",
                     "official_url": "https://example.legistar.com/Calendar.aspx", "platform": "legistar", **body},
            "checked_at": "2026-11-20T04:30:00Z", "last_ok_at": "2026-11-20T04:30:00Z", "meetings": [meeting]}


def _root(tmp_path, doc=None, raw=None, name=f"{GOV}.json") -> Path:
    root = tmp_path / "national"
    (root / "bodies").mkdir(parents=True, exist_ok=True)
    if doc is not None or raw is not None:
        (root / "bodies" / name).write_bytes(raw if raw is not None else json.dumps(doc).encode())
    return root


def _is_stale(feed, entry):
    assert feed == ncopy.stale_feed(entry) and feed_errors(feed) == []
    assert feed["meetings"] == [] and feed["last_ok_at"] is None and feed["checked_at"] == ncopy.EPOCH_INSTANT


def test_data_root_comes_from_the_environment_only():
    assert ncopy.data_root({}) is None and ncopy.data_root({ncopy.ENV: ""}) is None
    assert ncopy.data_root({ncopy.ENV: "/x/national"}) == Path("/x/national")


def test_a_shown_entry_s_file_is_cleaned_bound_and_kept(tmp_path, monkeypatch):
    shown = dict(ENTRY, items="shown")
    entry = _load(tmp_path, monkeypatch, shown, reviewed=True)
    doc = _feed(review=entry["review"])
    doc["body"]["name"] = "A name the file made up"              # body comes from the directory, never the file
    doc["meetings"][0]["title"] = "City‮ Council\x07"         # bidi and control characters stripped
    doc["meetings"][0]["meeting_url"] = "https://evil.example/x"   # not a Legistar host: dropped (finding 4)
    counts = ncopy.CopyCounts()
    feed = ncopy.copy_feed(_root(tmp_path, doc), entry, counts)
    assert counts.state == "copied" and feed_errors(feed) == []
    assert feed["body"] == {"id": GOV, "name": "Example Legistar Council", "tz": "America/Chicago",
                            "official_url": "https://example.legistar.com/Calendar.aspx", "platform": "legistar",
                            "full_url": None}
    m = feed["meetings"][0]
    assert m["title"] == "City Council" and m["meeting_url"] is None and m["items"][0]["text"] == SENTINEL
    assert counts.guards.chars_stripped == 2 and counts.guards.urls_dropped == 1
    assert "SENTINEL" not in counts.summary() and "City" not in counts.summary()


def test_a_withheld_entry_s_file_without_items_is_kept_with_fixed_titles(tmp_path, monkeypatch):
    entry = _load(tmp_path, monkeypatch, ENTRY)
    feed = ncopy.copy_feed(_root(tmp_path, _feed(items=False)), entry)
    m = feed["meetings"][0]
    assert feed["review"] is None and m["items"] == [] and m["items_withheld"] is True
    assert m["title"] == "Meeting" and m["time"] is None and m["agenda"]["status_as_posted"] is None


def test_items_for_a_withheld_entry_stop_the_build(tmp_path, monkeypatch):
    """11.2: D2 fails on withheld_stripped > 0 (a collector bug), and nothing of the file is returned."""
    entry = _load(tmp_path, monkeypatch, ENTRY)
    with pytest.raises(ncopy.CopyError, match="not shown") as exc:
        ncopy.copy_feed(_root(tmp_path, _feed(review="a" * 64)), entry)
    assert SENTINEL not in str(exc.value)
    directory = nat.Directory(govs=(entry,), alias={})
    states = {}                     # architecture 12 tier 1: the build degrades that entry, it never stops
    feed = npg.build_feeds(directory, {}, None, date(2026, 11, 20), national_root=_root(tmp_path), states=states)
    _is_stale(feed[GOV], entry)
    assert states == {GOV: npg.COPY_ERROR}


def test_a_shown_entry_read_under_another_review_loses_its_items_and_is_counted(tmp_path, monkeypatch):
    entry = _load(tmp_path, monkeypatch, dict(ENTRY, items="shown"), reviewed=True)
    counts = ncopy.CopyCounts()
    feed = ncopy.copy_feed(_root(tmp_path, _feed(review="b" * 64)), entry, counts)
    assert counts.state == "copied" and counts.bind.review_mismatch == 1
    assert feed["review"] is None and feed["meetings"][0]["items"] == []


def _symlinked_file(tmp_path):
    root = _root(tmp_path)
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps(_feed(items=False)))
    os.symlink(target, root / "bodies" / f"{GOV}.json")
    return root


def _symlinked_bodies(tmp_path):
    real = _root(tmp_path / "real", _feed(items=False))
    root = tmp_path / "national"
    root.mkdir()
    os.symlink(real / "bodies", root / "bodies")
    return root


def _symlinked_root(tmp_path):
    real = _root(tmp_path / "real", _feed(items=False))
    os.symlink(real, tmp_path / "link")
    return tmp_path / "link"


MISSING = {
    "no-root": lambda t: None,
    "root-absent": lambda t: t / "nowhere",
    "no-file": lambda t: _root(t),
    "not-json": lambda t: _root(t, raw=b"{not json"),
    "not-utf8": lambda t: _root(t, raw=b"\xff\xfe{}"),
    "nested-arrays": lambda t: _root(t, raw=b"[" * 60000),
    "nested-objects": lambda t: _root(t, raw=b'{"a":' * 500 + b"1" + b"}" * 500),
    "not-an-object": lambda t: _root(t, raw=b"[]"),
    "null": lambda t: _root(t, raw=b"null"),
    "too-big": lambda t: _root(t, raw=b" " * (ncopy.MAX_FILE_BYTES + 1) + b"{}"),
    "other-body-id": lambda t: _root(t, dict(_feed(items=False), body=dict(_feed()["body"], id="place-4799991"))),
    "bad-body-id": lambda t: _root(t, dict(_feed(items=False), body=dict(_feed()["body"], id="../x"))),
    "other-platform": lambda t: _root(t, dict(_feed(items=False), body=dict(_feed()["body"], platform="daylight"))),
    "extra-key": lambda t: _root(t, dict(_feed(items=False), votes=[])),
    "schema-fails": lambda t: _root(t, dict(_feed(items=False), checked_at="yesterday")),
    "symlinked-file": _symlinked_file,
    "symlinked-bodies": _symlinked_bodies,
    "symlinked-root": _symlinked_root,
}


@pytest.mark.parametrize("case", sorted(MISSING))
def test_any_unreadable_or_wrong_file_is_missing_and_the_page_stale(tmp_path, monkeypatch, case):
    """4.4.3 site 7 and 11.1 row 16: any error = file missing (page stale), never an exception, never the file."""
    entry = _load(tmp_path, monkeypatch, ENTRY)
    counts = ncopy.CopyCounts()
    _is_stale(ncopy.copy_feed(MISSING[case](tmp_path), entry, counts), entry)
    assert counts.state == "missing"


def test_a_file_named_for_another_body_is_never_read(tmp_path, monkeypatch):
    entry = _load(tmp_path, monkeypatch, ENTRY)
    _is_stale(ncopy.copy_feed(_root(tmp_path, _feed(items=False), name="place-4799991.json"), entry), entry)


@pytest.mark.parametrize("change", [
    {"host_ok": None}, {"host_ok": {"date": "2026-11-18"}}, {"legistar": {"body_id": 7}}, {"platform": "boarddocs"}],
    ids=["no-host-ok", "host-ok-no-link", "no-client", "not-collected"])
def test_an_entry_the_collector_may_not_read_stops_the_build(tmp_path, change):
    """national/r5-not-enforced: the copy step refuses, as the loader and the collector do, a hand-built entry with no
    valid host_ok (or no client), whatever national-data holds."""
    entry = {**copy.deepcopy(ENTRY), **change}
    if entry.get("host_ok") is None:
        entry.pop("host_ok")
    with pytest.raises(ncopy.CopyError):
        ncopy.copy_feed(_root(tmp_path, _feed(items=False)), entry)


def _folder_with(tmp_path, entry) -> Path:
    folder = tmp_path / "config-national"
    shutil.copytree(nat.NATIONAL_DIR, folder)
    p = folder / "directory.yml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    doc["govs"].append(entry)
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return folder


def _site_ctx():
    """A site context from the fixture facts, as build() makes it (as tests/test_national_pages.py does)."""
    from sitegen import views
    facts = build_mod.load_facts(FIXTURE)
    site = views.site_context(views.Index(facts, []))
    site.update(internal=False, analytics=None, morning_note=None, data_as_of="2026-11-18")
    return site


@pytest.mark.parametrize("with_data", [True, False], ids=["copied", "no-national-data"])
def test_the_build_writes_the_copied_feed_or_a_stale_page(tmp_path, monkeypatch, with_data, capsys):
    """The build's one call reads RECORDS_NATIONAL_DATA: the copied feed is what digest/ publishes; with no national
    data the government is still listed and its page says there are no records (stale), and the build goes on. The
    run log carries the id and counts only."""
    folder = _folder_with(tmp_path, ENTRY)
    if with_data:
        monkeypatch.setenv(ncopy.ENV, str(_root(tmp_path, _feed(items=False))))
    else:
        monkeypatch.delenv(ncopy.ENV, raising=False)
    out = tmp_path / "site"
    out.mkdir()
    npg.run(out, build_mod.make_env(), _site_ctx(), councils=[], county_agendas=None,
            built_day=date(2026, 11, 20), counter=None, fixture=True, folder=folder)
    published = json.loads((out / "digest" / "tn" / f"{GOV}.json").read_text(encoding="utf-8"))
    directory = nat.load_directory(folder / "directory.yml", nat.load_labels())
    entry = directory.get(GOV)
    if with_data:
        assert published == ncopy.copy_feed(_root(tmp_path, _feed(items=False)), entry)
        assert published["meetings"][0]["id"] == "e-101" and published["last_ok_at"] == "2026-11-20T04:30:00Z"
    else:
        _is_stale(published, entry)
    pagedir = (out / "digest" / "index.html").read_text(encoding="utf-8")
    assert GOV in pagedir
    log = capsys.readouterr().out
    assert f"sitegen: national: {GOV}: national-data {'copied' if with_data else 'missing'};" in log
    assert "City Council" not in log and SENTINEL not in log
