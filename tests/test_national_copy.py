"""The D2 copy step (sitegen/national_copy.py; docs/architecture/daylight-national.md 4.6 "D2 copy step", 4.4.3 site 7,
11.1 row 16, 11.2; task D2): a national-data body file reaches digest/ only after parse, clean_feed, bind_feed against
the current directory entry, and the schema; anything else is "file missing" (page stale). Problem keys:
collector-input/json-depth-recursion, privacy-withhold/national-prefix, national/r5-not-enforced."""
import copy
import json
import os
import re
import shutil
from datetime import date, datetime, timezone
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


def test_items_for_a_withheld_entry_give_a_stale_page_and_never_stop_the_build(tmp_path, monkeypatch, capsys):
    """11.2 as amended (security S2b finding 1, national-isolation/withheld-stop-holds-site): withheld_stripped > 0
    gives stale_feed, state withheld-items and one annotation with the id and count; nothing of the file is returned
    or printed, and nothing raises."""
    entry = _load(tmp_path, monkeypatch, ENTRY)
    counts = ncopy.CopyCounts()
    _is_stale(ncopy.copy_feed(_root(tmp_path, _feed(review="a" * 64)), entry, counts), entry)
    assert counts.state == ncopy.WITHHELD_ITEMS and counts.bind.withheld_stripped == 1
    out = capsys.readouterr().out
    assert out == f"::warning::National pages: {GOV}: withheld-items, withheld_stripped=1\n"
    directory = nat.Directory(govs=(entry,), alias={})
    states = {}
    feed = npg.build_feeds(directory, {}, None, date(2026, 11, 20), national_root=_root(tmp_path), states=states)
    _is_stale(feed[GOV], entry)
    assert states == {GOV: ncopy.WITHHELD_ITEMS}
    assert SENTINEL not in capsys.readouterr().out


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


def _fifo(tmp_path):
    root = _root(tmp_path)
    os.mkfifo(root / "bodies" / f"{GOV}.json")
    return root


def _folder(tmp_path):
    root = _root(tmp_path)
    (root / "bodies" / f"{GOV}.json").mkdir()
    return root


# No file to read (absent): state `missing`, silent (the page is stale; no root at all is code review nit 4's case).
ABSENT = {
    "no-root": lambda t: None,
    "root-absent": lambda t: t / "nowhere",
    "no-file": lambda t: _root(t),
    "symlinked-bodies": _symlinked_bodies,
    "symlinked-root": _symlinked_root,
}
# A file that is there but refused (B-ISO-9, national-isolation/refused-file-silent): state `bad-file`, one warning
# with the id, the word and a type name. {case: (make, type name)}
REFUSED = {
    "not-json": (lambda t: _root(t, raw=b"{not json"), "NotJson"),
    "not-utf8": (lambda t: _root(t, raw=b"\xff\xfe{}"), "NotJson"),
    "nested-arrays": (lambda t: _root(t, raw=b"[" * 60000), "NotJson"),
    "nested-objects": (lambda t: _root(t, raw=b'{"a":' * 500 + b"1" + b"}" * 500), "NotJson"),
    "not-an-object": (lambda t: _root(t, raw=b"[]"), "NotAnObject"),
    "null": (lambda t: _root(t, raw=b"null"), "NotAnObject"),
    "too-big": (lambda t: _root(t, raw=b" " * (ncopy.MAX_FILE_BYTES + 1) + b"{}"), "FileTooLarge"),
    "other-body-id": (lambda t: _root(t, dict(_feed(items=False), body=dict(_feed()["body"], id="place-4799991"))),
                      None),
    "bad-body-id": (lambda t: _root(t, dict(_feed(items=False), body=dict(_feed()["body"], id="../x"))), None),
    "other-platform": (lambda t: _root(t, dict(_feed(items=False), body=dict(_feed()["body"], platform="daylight"))),
                       None),
    "extra-key": (lambda t: _root(t, dict(_feed(items=False), votes=[])), "BindError"),
    "schema-fails": (lambda t: _root(t, dict(_feed(items=False), schema="daylight-upcoming/2")), "SchemaRefused"),
    "date-not-text": (lambda t: _root(t, dict(_feed(items=False), meetings=[
        dict(_feed(items=False)["meetings"][0], date=20261203)])), "SchemaRefused"),
    "symlinked-file": (_symlinked_file, "NotRegularFile"),
    "fifo": (_fifo, "NotRegularFile"),
    "folder": (_folder, "NotRegularFile"),
}


@pytest.mark.parametrize("case", sorted(ABSENT))
def test_no_file_is_missing_silently_and_the_page_stale(tmp_path, monkeypatch, capsys, case):
    """4.4.3 site 7 and 11.1 row 16: no file = file missing (page stale), never an exception, no annotation."""
    entry = _load(tmp_path, monkeypatch, ENTRY)
    counts = ncopy.CopyCounts()
    _is_stale(ncopy.copy_feed(ABSENT[case](tmp_path), entry, counts), entry)
    assert counts.state == "missing"
    assert "::warning::" not in capsys.readouterr().out


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_a_file_that_is_there_but_refused_is_bad_file_with_one_warning(tmp_path, monkeypatch, capsys, case):
    """B-ISO-9: never an exception, never the file's text; the warning names the id, `bad-file` and a type name."""
    entry = _load(tmp_path, monkeypatch, ENTRY)
    counts = ncopy.CopyCounts()
    make, type_name = REFUSED[case]
    _is_stale(ncopy.copy_feed(make(tmp_path), entry, counts), entry)
    assert counts.state == ncopy.BAD_FILE == "bad-file"
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("::")]
    assert len(lines) == 1 and re.fullmatch(rf"::warning::National pages: {GOV}: bad-file \(([A-Za-z_]\w*)\)",
                                            lines[0]), lines
    if type_name:
        assert lines[0].endswith(f"({type_name})")


def test_read_body_file_tells_absent_from_refused(tmp_path):
    assert ncopy.read_body_file(None, GOV) == (None, None)
    assert ncopy.read_body_file(_root(tmp_path / "a"), GOV) == (None, None)
    assert ncopy.read_body_file(_root(tmp_path / "b"), "../x") == (None, None)       # an id it may not name
    assert ncopy.read_body_file(_root(tmp_path / "c", raw=b"{x"), GOV) == (None, "NotJson")
    assert ncopy.read_body_file(_root(tmp_path / "d", raw=b'{"a": 1}'), GOV) == ({"a": 1}, None)


def test_a_file_named_for_another_body_is_never_read(tmp_path, monkeypatch):
    entry = _load(tmp_path, monkeypatch, ENTRY)
    _is_stale(ncopy.copy_feed(_root(tmp_path, _feed(items=False), name="place-4799991.json"), entry), entry)


@pytest.mark.parametrize("change", [
    {"host_ok": None}, {"host_ok": {"date": "2026-11-18"}}, {"legistar": {"body_id": 7}}, {"platform": "boarddocs"}],
    ids=["no-host-ok", "host-ok-no-link", "no-client", "not-collected"])
def test_copy_feed_raises_copy_error_for_an_entry_the_collector_may_not_read(tmp_path, change):
    """national/r5-not-enforced: the copy step refuses, as the loader and the collector do, a hand-built entry with no
    valid host_ok (or no client), whatever national-data holds. This checks only that copy_feed raises; that the
    build stops in the load phase is test_national_pages.py::
    test_a_covered_entry_without_a_feed_source_is_refused_at_load (code review D1/D2/iso nit 6, B-ISO-11)."""
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


# --- security S2b finding 2 (national-isolation/date-crashes-build; architecture 12.3 #3) ---------------------------

BUILT = datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc)
BAD_DAYS = {"not-a-day": "2026-02-30", "arabic-indic": "٢٠٢٦-١٢-٠٣", "fullwidth": "２０２６-１２-０３",
            "short-month": "2026-1-05", "newline": "2026-12-03\n", "mixed": "2026-12-0٣"}
BAD_INSTANTS = {"arabic-indic": "٢٠٢٦-١١-٢٠T04:30:00Z", "fullwidth": "２０２６-11-20T04:30:00Z",
                "not-a-day": "2026-02-30T04:30:00Z", "hour-25": "2026-11-20T25:00:00Z", "words": "yesterday",
                "before-epoch": "1969-12-31T23:59:59Z", "far-past": "0001-01-01T00:00:00Z",
                "after-build": "2026-11-21T18:00:01Z", "far-future": "9999-12-31T23:59:59Z",
                "offset": "2026-11-20T04:30:00+00:00", "newline": "2026-11-20T04:30:00Z\n"}


@pytest.mark.parametrize("case", sorted(BAD_DAYS))
def test_a_meeting_date_the_pages_cannot_print_gives_a_stale_page(tmp_path, monkeypatch, capsys, case):
    entry = _load(tmp_path, monkeypatch, dict(ENTRY, items="shown"), reviewed=True)
    doc = _feed(review=entry["review"])
    doc["meetings"][0]["date"] = BAD_DAYS[case]
    counts = ncopy.CopyCounts()
    _is_stale(ncopy.copy_feed(_root(tmp_path, doc), entry, counts, built_at=BUILT), entry)
    assert counts.state == ncopy.BAD_DATE
    assert capsys.readouterr().out == f"::warning::National pages: {GOV}: bad-date\n"


@pytest.mark.parametrize("key", ["checked_at", "last_ok_at"])
@pytest.mark.parametrize("case", sorted(BAD_INSTANTS))
def test_an_instant_out_of_form_or_range_gives_a_stale_page(tmp_path, monkeypatch, capsys, case, key):
    entry = _load(tmp_path, monkeypatch, ENTRY)
    doc = dict(_feed(items=False), **{key: BAD_INSTANTS[case]})
    counts = ncopy.CopyCounts()
    _is_stale(ncopy.copy_feed(_root(tmp_path, doc), entry, counts, built_at=BUILT), entry)
    assert counts.state == ncopy.BAD_INSTANT
    assert capsys.readouterr().out == f"::warning::National pages: {GOV}: bad-instant\n"


@pytest.mark.parametrize("checked_at,last_ok_at", [
    (ncopy.EPOCH_INSTANT, None), ("2026-11-21T18:00:00Z", "2026-11-21T18:00:00Z"),
    ("2026-02-28T00:00:00Z", "2024-02-29T23:59:59Z")])
def test_instants_at_the_edges_of_the_range_are_kept(tmp_path, monkeypatch, checked_at, last_ok_at):
    """The epoch (a stale feed's own checked_at) up to one day after the build's instant, and a null last_ok_at."""
    entry = _load(tmp_path, monkeypatch, ENTRY)
    doc = dict(_feed(items=False), checked_at=checked_at, last_ok_at=last_ok_at)
    counts = ncopy.CopyCounts()
    feed = ncopy.copy_feed(_root(tmp_path, doc), entry, counts, built_at=BUILT)
    assert counts.state == ncopy.COPIED and feed["checked_at"] == checked_at


@pytest.mark.parametrize("field,value", [("date", "٢٠٢٦-١٢-٠٣"), ("date", "２０２６-１２-０３"),
                                         ("checked_at", "٢٠٢٦-١١-٢٠T04:30:00Z"),
                                         ("last_ok_at", "２０２６-11-20T04:30:00Z")])
def test_the_schema_refuses_non_ascii_digits(field, value):
    doc = _feed(items=False)
    doc["body"]["full_url"] = None
    assert feed_errors(doc) == []
    if field == "date":
        doc["meetings"][0]["date"] = value
    else:
        doc[field] = value
    assert feed_errors(doc)


def test_host_ok_dates_take_ascii_digits_only():
    from sitegen.national_guards import host_ok_valid
    assert host_ok_valid(HOST_OK)
    assert not host_ok_valid(dict(HOST_OK, date="٢٠٢٦-١١-١٨"))
