"""Invariant `national-isolation` (docs/architecture/daylight-national.md section 12; ADR 0013 decision 6): national
data never holds a Clarksville build or deploy. Tests 12.3 #1, #2, #4-9 and #13 (#3 is in tests/test_national_copy.py,
plus the build-level date cases of the sweep here; #10-12 are the workflow tests, devops). Problem keys:
national-isolation/withheld-stop-holds-site (S2b finding 1), national-isolation/date-crashes-build (finding 2),
national-isolation/site-checks-read-feed-text (N2), S2b nit b (switch off).

Most tests build the fixture site (about a second each) for the pages target with config national.enabled on and a
copy of config/national/ that also lists a made-up Tennessee place on Legistar (GOV, items shown under its review),
its body file under a temporary RECORDS_NATIONAL_DATA. Each bad national input is compared with the same build with no
national root: every file outside digest/ is byte-identical, and inside digest/ only that government's files (and its
`stale` flag in the lookup page's directory) may differ."""
import copy
import html as html_mod
import functools
import json
import os
import re
import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS
from qa import site_checks as SC
from sitegen import build as build_mod, config
from sitegen import national as nat
from sitegen import national_copy as ncopy
from sitegen import national_pages as npg
from sitegen.national_guards import id_layer

RUN = npg.run                       # the build's call, before any test points it at another config folder
LOAD_DIRECTORY = nat.load_directory
TODAY = date(2026, 11, 19)
COUNCIL_ID, COUNTY_ID = "place-4715160", "county-47125"
GOV = "place-4799990"               # a made-up Tennessee place (TN has page labels; no real body is named)
PAGE, DATA, INDEX = f"digest/tn/{GOV}.html", f"digest/tn/{GOV}.json", "digest/index.html"
SENTINEL = "SENTINEL-ITEM-TEXT"
HOST_OK = {"date": "2026-11-18", "link": "https://github.com/gn0sh/clarksville-records/pull/1"}
ENTRY = {"gov": GOV, "also": [], "body_name": "Example Legistar Council", "state": "TN", "status": "covered",
         "official_url": "https://example.legistar.com/Calendar.aspx", "checked": "2026-11-18",
         "checked_url": "https://example.legistar.com/Calendar.aspx", "items": "shown", "platform": "legistar",
         "legistar": {"client": "example", "body_id": 7, "tz": "America/Chicago"}, "host_ok": HOST_OK}
AGENDA = "https://example.legistar.com/View.ashx?M=A&ID=101"


def body_file(review, *, title="City Council", time="6:00 PM", text=SENTINEL, date_="2026-12-03",
              checked_at="2026-11-19T04:30:00Z") -> dict:
    """A body file as the collector writes it (3.7), its one meeting final with one item."""
    meeting = {"id": "e-101", "date": date_, "time": time, "title": title, "title_ours": False,
               "meeting_url": "https://example.legistar.com/MeetingDetail.aspx?ID=101",
               "agenda": {"state": "final", "url": AGENDA, "status_as_posted": "Final"},
               "may_be_incomplete": False, "items_withheld": False, "item_count": 1,
               "items": [{"seq": 1, "number": "R-1", "text": text, "source": {"url": AGENDA, "page": 2}}]}
    return {"schema": "daylight-upcoming/1", "review": review,
            "body": {"id": GOV, "name": "Example Legistar Council", "tz": "America/Chicago",
                     "official_url": "https://example.legistar.com/Calendar.aspx", "platform": "legistar"},
            "checked_at": checked_at, "last_ok_at": checked_at, "meetings": [meeting]}


def write_folder(base: Path, entry: dict) -> Path:
    """A copy of config/national/ whose directory.yml also lists `entry`."""
    folder = base / "config-national"
    if not folder.exists():
        shutil.copytree(nat.NATIONAL_DIR, folder)
    p = folder / "directory.yml"
    doc = yaml.safe_load((nat.NATIONAL_DIR / "directory.yml").read_text(encoding="utf-8"))
    doc["govs"].append(entry)
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return folder


def point_at(mp: pytest.MonkeyPatch, folder: Path, reviewed: dict | None) -> None:
    """The build and the site checks read `folder` instead of config/national/; `reviewed` gets its review row."""
    if reviewed is not None:
        mp.setattr(nat, "SHOWN_REVIEWED", nat.SHOWN_REVIEWED + (nat.ShownReview(reviewed["gov"],
                                                                                nat.norm_entry(reviewed)),))
    mp.setattr(npg, "run", functools.partial(RUN, folder=folder))

    def load_directory(path=folder / "directory.yml", labels=None):
        return LOAD_DIRECTORY(path, labels)
    mp.setattr(nat, "load_directory", load_directory)


def build(out: Path, *, on: bool = True, root=None) -> dict:
    """The fixture build with the switch `on` and RECORDS_NATIONAL_DATA `root` (None: unset)."""
    saved_switch, saved_env = config.SITE.get("national", "absent"), os.environ.get(ncopy.ENV)
    config.SITE["national"] = {"enabled": on}
    if root is None:
        os.environ.pop(ncopy.ENV, None)
    else:
        os.environ[ncopy.ENV] = str(root)
    try:
        return build_mod.build(FIXTURE, out, internal=False, seats_path=FIXTURE_SEATS,
                               districts_path=FIXTURE_DISTRICTS, target="pages", today=TODAY)
    finally:
        if saved_switch == "absent":
            config.SITE.pop("national", None)
        else:
            config.SITE["national"] = saved_switch
        if saved_env is None:
            os.environ.pop(ncopy.ENV, None)
        else:
            os.environ[ncopy.ENV] = saved_env


def tree(out: Path) -> dict[str, bytes]:
    return {p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}


def national_root(base: Path, doc=None, *, raw: bytes | None = None) -> Path:
    root = base / "national"
    (root / "bodies").mkdir(parents=True, exist_ok=True)
    if doc is not None or raw is not None:
        (root / "bodies" / f"{GOV}.json").write_bytes(raw if raw is not None else json.dumps(doc).encode())
    return root


PAGEDIR_RE = re.compile(r'(<script type="application/json" id="digest-pagedir">)(.*?)(</script>)', re.S)


def pagedir(html: bytes) -> dict:
    return json.loads(PAGEDIR_RE.search(html.decode("utf-8")).group(2))


def assert_only_gov_changed(got: dict[str, bytes], base: dict[str, bytes], gov: str = GOV, page: str = PAGE):
    """12.3 #4: every file outside digest/ byte-identical; inside, only `gov`'s page and JSON, and the lookup page
    only by `gov`'s stale flag in its embedded directory."""
    diff = {k for k in got.keys() | base.keys() if got.get(k) != base.get(k)}
    assert not [k for k in diff if not k.startswith("digest/")], sorted(diff)
    allowed = {page, page[:-len(".html")] + ".json", INDEX}
    assert diff <= allowed, sorted(diff - allowed)
    if INDEX in diff:
        a, b = pagedir(got[INDEX]), pagedir(base[INDEX])
        a["govs"][gov].pop("stale")
        b["govs"][gov].pop("stale")
        assert a == b
        assert PAGEDIR_RE.sub("", got[INDEX].decode()) == PAGEDIR_RE.sub("", base[INDEX].decode())


# --- annotation hygiene (12.3 #13) ----------------------------------------------------------------------------------

STATES = {npg.BUILT, ncopy.COPIED, ncopy.MISSING, *npg.DEGRADED_STATES}
COUNTS = r"[a-z_]+=[0-9]+(?:, [a-z_]+=[0-9]+)*"
TYPE = r"[A-Za-z_][A-Za-z0-9_]*"
LINE_RES = [re.compile(p) for p in (
    rf"sitegen: national: (?P<id>\S+): guards changed the feed: {COUNTS}",
    rf"sitegen: national: (?P<id>\S+): national-data (?P<state>[a-z-]+); {COUNTS}; review_mismatch=[0-9]+",
    rf"sitegen: national: (?P<id>\S+): bind_feed stripped items: {COUNTS}",
    rf"::warning::National pages: (?P<id>\S+): (?P<state>[a-z-]+)(?:, [a-z_]+=[0-9]+)?(?: \({TYPE}\))?",
    rf"::error::National pages: built with no data \({TYPE}\)")]


def national_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if "national" in ln.lower()]


def assert_clean_lines(text: str) -> list[str]:
    """Every line the national step printed is one of LINE_RES with an id id_layer accepts and a fixed state word:
    ids, fixed words, exception type names and name=<integer> counts only, never input text."""
    lines = national_lines(text)
    for ln in lines:
        m = next((r.fullmatch(ln) for r in LINE_RES if r.fullmatch(ln)), None)
        assert m is not None, ln
        groups = m.groupdict()
        assert groups.get("id") is None or id_layer(groups["id"]), ln
        assert groups.get("state") is None or groups["state"] in STATES, ln
        assert SENTINEL not in ln
    return lines


def test_the_run_log_contract_d_iso_9_reads():
    """build result and run-log.json: `national` is off | built | degraded; `national_states` maps a degraded
    government's id to one of these five words only (manager note, 2026-11-20)."""
    assert (npg.OFF, npg.BUILT, npg.DEGRADED) == ("off", "built", "degraded")
    assert set(npg.DEGRADED_STATES) == {"withheld-items", "bad-date", "bad-instant", "adapter-error", "render-error"}
    run = npg.NationalRun(pages=[], govs={GOV: ncopy.MISSING, COUNTY_ID: npg.BUILT, COUNCIL_ID: npg.RENDER_ERROR})
    assert run.degraded == {COUNCIL_ID: "render-error"}


# --- fixtures ---------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def _world(tmp_path_factory):
    """The config folder with GOV (shown), its review digest, and the build with no national root (the baseline)."""
    base = tmp_path_factory.mktemp("isolation")
    folder = write_folder(base, ENTRY)
    saved_env = os.environ.pop(ncopy.ENV, None)
    try:
        with pytest.MonkeyPatch.context() as mp:
            point_at(mp, folder, ENTRY)
            review = LOAD_DIRECTORY(folder / "directory.yml", nat.load_labels()).get(GOV)["review"]
            result = build(base / "baseline" / "site")
    finally:
        if saved_env is not None:
            os.environ[ncopy.ENV] = saved_env
    return {"base": base, "folder": folder, "review": review, "baseline": tree(base / "baseline" / "site"),
            "baseline_dir": base / "baseline" / "site", "result": result}


@pytest.fixture
def world(_world, monkeypatch):
    """_world, with the build and the site checks pointed at its config folder for this test only."""
    point_at(monkeypatch, _world["folder"], ENTRY)
    return _world


def test_the_baseline_build_has_the_stale_page_and_a_good_file_is_published(world, tmp_path, capsys):
    """Controls for the sweep: with no root GOV's page is its stale feed; a good shown file reaches only its files."""
    base = world["baseline"]
    stale = json.loads(base[DATA])
    assert stale["meetings"] == [] and stale["checked_at"] == ncopy.EPOCH_INSTANT
    assert world["result"]["national"] == npg.BUILT and world["result"]["national_states"] == {}
    got_dir = tmp_path / "site"
    result = build(got_dir, root=national_root(tmp_path, body_file(world["review"])))
    got = tree(got_dir)
    assert result["national"] == npg.BUILT and result["national_states"] == {}
    assert_only_gov_changed(got, base)
    assert json.loads(got[DATA])["meetings"][0]["items"][0]["text"] == SENTINEL
    assert SENTINEL in got[PAGE].decode()
    assert pagedir(got[INDEX])["govs"][GOV]["stale"] is False and pagedir(base[INDEX])["govs"][GOV]["stale"] is True
    assert_clean_lines(capsys.readouterr().out)


# --- 12.3 #1: shipped config, switch on ----------------------------------------------------------------------------

def test_shipped_config_switch_on_builds_every_covered_page(tmp_path, monkeypatch):
    monkeypatch.delenv(ncopy.ENV, raising=False)
    result = build(tmp_path / "site")
    assert result["national"] == npg.BUILT and result["national_states"] == {}
    covered = [g for g in nat.load_all()[0].govs if g["status"] == "covered"]
    assert covered
    for g in covered:
        page = tmp_path / "site" / nat.gov_page(g)
        assert page.is_file() and page.with_suffix(".json").is_file()


def test_shipped_config_with_every_covered_entry_stale_still_builds(tmp_path, monkeypatch, capsys):
    def broken(gov, *a, **k):
        raise TypeError("not today")
    monkeypatch.setattr(npg, "_adapter_feed", broken)
    result = build(tmp_path / "site")
    covered = [g for g in nat.load_all()[0].govs if g["status"] == "covered"]
    assert result["national"] == npg.BUILT
    assert result["national_states"] == {g["gov"]: npg.ADAPTER_ERROR for g in covered}
    for g in covered:
        feed = json.loads((tmp_path / "site" / nat.gov_page(g)).with_suffix(".json").read_text(encoding="utf-8"))
        assert feed == npg.bind_feed(ncopy.stale_feed(g), g)[0]
    lines = assert_clean_lines(capsys.readouterr().out)
    assert [ln for ln in lines if ln.startswith("::warning::")] == [
        f"::warning::National pages: {g['gov']}: adapter-error (TypeError)" for g in covered]


def test_a_legistar_entry_whose_zone_has_no_label_is_refused_at_load(tmp_path, monkeypatch):
    """12.1 row 13 (N3): decided from reviewed files before any data, so the PR's own checks fail."""
    entry = dict(ENTRY, items="withheld", legistar=dict(ENTRY["legistar"], tz="America/Los_Angeles"))
    folder = write_folder(tmp_path, entry)
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(npg.NationalBuildError, match=r"no label tz\.America/Los_Angeles"):
        RUN(out, build_mod.make_env(), {}, councils=[], county_agendas=None, built_day=TODAY, counter=None,
            fixture=True, folder=folder)
    assert list(out.rglob("*")) == []
    point_at(monkeypatch, folder, None)
    with pytest.raises(build_mod.BuildError, match=r"national: .*tz\.America/Los_Angeles"):
        build(tmp_path / "site")


# --- 12.3 #2: finding 1, the narrowing PR ----------------------------------------------------------------------------

def test_a_file_collected_while_shown_and_read_after_narrowing_gives_a_stale_page(world, tmp_path, monkeypatch,
                                                                                    capsys):
    """S2b finding 1: the directory says `items: withheld` now, the file still carries the shown review and items."""
    folder = write_folder(tmp_path, dict(ENTRY, items="withheld"))
    point_at(monkeypatch, folder, None)
    out = tmp_path / "site"
    result = build(out, root=national_root(tmp_path, body_file(world["review"])))
    assert result["national"] == npg.BUILT and result["national_states"] == {GOV: ncopy.WITHHELD_ITEMS}
    got = tree(out)
    assert json.loads(got[DATA])["meetings"] == []
    assert not [k for k, v in got.items() if SENTINEL.encode() in v]
    text = capsys.readouterr().out
    assert f"::warning::National pages: {GOV}: withheld-items, withheld_stripped=1" in text.splitlines()
    assert_clean_lines(text)
    base = tmp_path / "base"
    build(base)
    assert got == tree(base)                    # exactly the build with no national root


# --- 12.3 #4 (and #3 at build level): the hostile national-data sweep ----------------------------------------------

def _deep(n: int) -> bytes:
    return b'{"a":' * n + b"1" + b"}" * n


def _all_strings(value, fn):
    if isinstance(value, dict):
        return {k: _all_strings(v, fn) for k, v in value.items()}
    if isinstance(value, list):
        return [_all_strings(v, fn) for v in value]
    return fn(value) if isinstance(value, str) else value


def _nulls(value):
    if isinstance(value, dict):
        return {k: (_nulls(v) if k in ("body", "meetings", "agenda", "items", "source") else None)
                for k, v in value.items()}
    if isinstance(value, list):
        return [_nulls(v) for v in value]
    return None


def _surrogates(doc: dict) -> bytes:
    """Every string field carries a lone surrogate escape (not valid UTF-8 text once decoded)."""
    text = json.dumps(_all_strings(doc, lambda s: s + "\x00MARK"))
    return text.replace("\\u0000MARK", "\\ud800").encode()


def _symlinked(base: Path, review) -> Path:
    root = national_root(base)
    real = base / "real.json"
    real.write_text(json.dumps(body_file(review)), encoding="utf-8")
    os.symlink(real, root / "bodies" / f"{GOV}.json")
    return root


def _fifo(base: Path, review) -> Path:
    root = national_root(base)
    os.mkfifo(root / "bodies" / f"{GOV}.json")
    return root


HOSTILE = {
    "not-json": lambda b, r: national_root(b, raw=b"{not json"),
    "too-big": lambda b, r: national_root(b, raw=b" " * (ncopy.MAX_FILE_BYTES + 1) + b"{}"),
    "depth-33": lambda b, r: national_root(b, raw=_deep(33)),
    "symlink": _symlinked,
    "fifo": _fifo,
    "wrong-body-id": lambda b, r: national_root(b, dict(body_file(r), body=dict(body_file(r)["body"],
                                                                                 id="place-4799991"))),
    "wrong-platform": lambda b, r: national_root(b, dict(body_file(r), body=dict(body_file(r)["body"],
                                                                                  platform="daylight"))),
    "extra-key": lambda b, r: national_root(b, dict(body_file(r), votes=[{"name": SENTINEL}])),
    "meetings-not-a-list": lambda b, r: national_root(b, dict(body_file(r), meetings={"e-101": SENTINEL})),
    "items-not-a-list": lambda b, r: national_root(b, dict(body_file(r), meetings=[
        dict(body_file(r)["meetings"][0], items={"text": SENTINEL})])),
    "surrogates": lambda b, r: national_root(b, raw=_surrogates(body_file(r))),
    "fields-and-marks": lambda b, r: national_root(b, body_file(r, title="{name} [x] {date}", time="{x} [y]",
                                                                text=f"{SENTINEL} {{name}} [link] {{}}")),
    "fragment-anchors": lambda b, r: national_root(b, body_file(r, title=npg.MENU_ANCHOR + "</main>",
                                                                time="</footer>", text=npg.FRONT_START)),
    "huge-integers": lambda b, r: national_root(b, raw=json.dumps(body_file(r)).replace(
        '"seq": 1', '"seq": ' + "9" * 4000).replace('"page": 2', '"page": ' + "9" * 4000).encode()),
    "huge-integers-past-the-limit": lambda b, r: national_root(b, raw=json.dumps(body_file(r)).replace(
        '"seq": 1', '"seq": ' + "9" * 5000).encode()),
    "null-everywhere": lambda b, r: national_root(b, _nulls(body_file(r))),
    "bad-date": lambda b, r: national_root(b, body_file(r, date_="2026-02-30")),
    "arabic-indic-date": lambda b, r: national_root(b, body_file(r, date_="٢٠٢٦-١٢-٠٣")),
    "bad-instant": lambda b, r: national_root(b, body_file(r, checked_at="2026-11-21T18:00:01Z")),
    "instant-before-epoch": lambda b, r: national_root(b, body_file(r, checked_at="1969-12-31T23:59:59Z")),
}
STATE_OF = {"bad-date": ncopy.BAD_DATE, "arabic-indic-date": ncopy.BAD_DATE, "bad-instant": ncopy.BAD_INSTANT,
            "instant-before-epoch": ncopy.BAD_INSTANT}


@pytest.mark.parametrize("case", sorted(HOSTILE))
def test_a_hostile_body_file_changes_only_its_own_page(world, tmp_path, capsys, case):
    out = tmp_path / "site"
    result = build(out, root=HOSTILE[case](tmp_path, world["review"]))
    got = tree(out)
    assert_only_gov_changed(got, world["baseline"])
    assert result["national"] == npg.BUILT
    assert result["national_states"] == ({GOV: STATE_OF[case]} if case in STATE_OF else {})
    feed = json.loads(got[DATA])
    assert npg.ncl.feed_errors(feed) == []
    assert_clean_lines(capsys.readouterr().out)
    if got[DATA] != world["baseline"][DATA]:    # copied: the page prints the JSON's item text, escaped
        assert case in {"surrogates", "fields-and-marks", "fragment-anchors", "huge-integers"}, case
        printed = " ".join(html_mod.unescape(got[PAGE].decode("utf-8")).split())
        for m in feed["meetings"]:
            for it in m["items"]:
                assert " ".join(it["text"].split()) in printed


def test_the_fragment_anchors_in_feed_text_are_escaped_and_added_once(world, tmp_path):
    out = tmp_path / "site"
    build(out, root=HOSTILE["fragment-anchors"](tmp_path, world["review"]))
    page = (out / PAGE).read_text(encoding="utf-8")
    assert page.count(npg.MENU_ANCHOR) == 1 and page.count("</footer>") == 1 and page.count("</main>") == 1
    assert page.count(npg.menu_fragment("../../", npg.load_page_labels())) == 1


# --- 12.3 #5: tier 1 backstop -----------------------------------------------------------------------------------------

def test_a_render_error_for_one_government_leaves_the_others_built(world, tmp_path, monkeypatch, capsys):
    real = npg.meeting_view

    def flaky(m, gov, tz, labels):
        if gov["gov"] == GOV:
            raise TypeError(SENTINEL)
        return real(m, gov, tz, labels)
    monkeypatch.setattr(npg, "meeting_view", flaky)
    out = tmp_path / "site"
    result = build(out, root=national_root(tmp_path, body_file(world["review"])))
    assert result["national"] == npg.BUILT and result["national_states"] == {GOV: npg.RENDER_ERROR}
    assert tree(out) == world["baseline"]       # GOV stale, the Clarksville pages as always
    lines = assert_clean_lines(capsys.readouterr().out)
    assert f"::warning::National pages: {GOV}: render-error (TypeError)" in lines


# --- 12.3 #6: tier 2 ----------------------------------------------------------------------------------------------------

def test_a_raise_after_the_load_phase_builds_the_digest_all_stale(world, tmp_path, monkeypatch, capsys):
    real, calls = nat.page_directory, []

    def once(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError(SENTINEL)
        return real(*a, **k)
    monkeypatch.setattr(nat, "page_directory", once)
    out = tmp_path / "site"
    result = build(out, root=national_root(tmp_path, body_file(world["review"])))
    assert len(calls) == 2
    assert result["national"] == npg.DEGRADED
    directory = nat.load_all(world["folder"])[0]
    covered = [g for g in directory.govs if g["status"] == "covered"]
    assert result["national_states"] == {}            # `national: degraded` says every page is stale
    got = tree(out)
    for g in covered:
        rel = nat.gov_page(g)[:-len(".html")] + ".json"
        assert json.loads(got[rel]) == npg.bind_feed(ncopy.stale_feed(g), g)[0]
    assert not [k for k, v in got.items() if SENTINEL.encode() in v]
    assert {k for k in got if k.startswith("digest/")} == {k for k in world["baseline"] if k.startswith("digest/")}
    assert {k: v for k, v in got.items() if not k.startswith("digest/")} == \
        {k: v for k, v in world["baseline"].items() if not k.startswith("digest/")}
    lines = assert_clean_lines(capsys.readouterr().out)
    assert [ln for ln in lines if ln.startswith("::error::")] == [
        "::error::National pages: built with no data (ValueError)"]


def test_a_raise_in_the_no_data_rebuild_stops_the_build(world, tmp_path, monkeypatch):
    def always(*a, **k):
        raise ValueError("a code or config fault")
    monkeypatch.setattr(nat, "page_directory", always)
    with pytest.raises(build_mod.BuildError, match="even with no data: ValueError"):
        build(tmp_path / "site", root=national_root(tmp_path, body_file(world["review"])))


def test_the_tier_2_rebuild_clears_what_the_first_attempt_wrote(world, tmp_path, monkeypatch):
    real, calls = npg.build_national, []

    def write_then_fail(out_dir, *a, **k):
        calls.append(1)
        if len(calls) == 1:
            (Path(out_dir) / "digest" / "tn").mkdir(parents=True, exist_ok=True)
            (Path(out_dir) / "digest" / "tn" / "leftover.json").write_text(SENTINEL, encoding="utf-8")
            raise OSError("disk")
        return real(out_dir, *a, **k)
    monkeypatch.setattr(npg, "build_national", write_then_fail)
    out = tmp_path / "site"
    assert build(out)["national"] == npg.DEGRADED
    assert not (out / "digest" / "tn" / "leftover.json").exists()


# --- 12.3 #7: the adapter on odd Clarksville data (N4) ---------------------------------------------------------------

class Council:
    def __init__(self, cfg, facts):
        self.cfg, self.facts = cfg, facts


def _agendas(meetings):
    return {"index_url": "https://mcgtn.org/commission/agendas",
            "sources": [{"id": "s1", "url": "https://mcgtn.org/a.pdf", "pages": 3, "fetched_at": "2026-11-18"}],
            "meetings": meetings}


GOOD_MEETING = {"id": "2026-12-01-formal", "date": "2026-12-01", "kind": "formal", "source_id": "s1",
                "items": [{"number": "R-1", "title": "Roads", "page": 1}]}
ADAPTER_CASES = {
    "list-source-id": (COUNTY_ID, lambda t: (_agendas([dict(GOOD_MEETING, source_id=["s1"])]), None)),
    "null-item-title": (COUNTY_ID, lambda t: (_agendas([dict(GOOD_MEETING, items=[{"number": "R-1", "title": None,
                                                                                  "page": 1}])]), None)),
    "meeting-without-id": (COUNTY_ID, lambda t: (_agendas([{k: v for k, v in GOOD_MEETING.items() if k != "id"}]),
                                                 None)),
    "meetings-not-a-list": (COUNTY_ID, lambda t: ({"sources": [], "meetings": {"x": 1}}, None)),
    "listing-not-json": (COUNCIL_ID, lambda t: (_agendas([GOOD_MEETING]), b"[not json")),
    "listing-not-utf8": (COUNCIL_ID, lambda t: (_agendas([GOOD_MEETING]), b"\xff\xfe[]")),
}
# The adapter drops what it cannot read in one record (a meeting with no id is dropped and counted, B14) rather than
# degrade the whole government: those cases build that government's page normally.
ADAPTER_BUILT = {"meeting-without-id", "null-item-title"}


def _run_adapter(out: Path, tmp_path: Path, agendas, listing: bytes | None):
    cfg = dict(next(c for c in config.COUNCILS if c.get("body_key") == "city"))
    if listing is not None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        path = tmp_path / "listing.json"
        path.write_bytes(listing)
        cfg["calendar"] = str(path)
    else:
        cfg.pop("calendar", None)
    out.mkdir(parents=True)
    return RUN(out, build_mod.make_env(), _site(), councils=[Council(cfg, {"meetings": [], "sources": []})],
               county_agendas=agendas, built_day=TODAY, counter=None, fixture=False)


@functools.lru_cache(maxsize=1)
def _site_ctx():
    from sitegen import views
    facts = build_mod.load_facts(FIXTURE)
    site = views.site_context(views.Index(facts, []))
    site.update(internal=False, analytics=None, morning_note=None, data_as_of="2026-11-18")
    return site


def _site():
    return copy.deepcopy(_site_ctx())


@pytest.mark.parametrize("case", sorted(ADAPTER_CASES))
def test_odd_clarksville_records_degrade_only_their_government(tmp_path, monkeypatch, capsys, case):
    monkeypatch.delenv(ncopy.ENV, raising=False)
    gov, make = ADAPTER_CASES[case]
    agendas, listing = make(tmp_path)
    good = _run_adapter(tmp_path / "good", tmp_path / "g", _agendas([GOOD_MEETING]), b"[]" if listing else None)
    bad = _run_adapter(tmp_path / "bad", tmp_path, agendas, listing)
    assert good.state == bad.state == npg.BUILT and good.degraded == {}
    got, base = tree(tmp_path / "bad"), tree(tmp_path / "good")
    assert all(k.startswith("digest/") for k in got)            # nothing outside digest/ is written by run
    other = COUNCIL_ID if gov == COUNTY_ID else COUNTY_ID
    for suffix in (".html", ".json"):
        assert got[f"digest/tn/{other}{suffix}"] == base[f"digest/tn/{other}{suffix}"]
    if case in ADAPTER_BUILT:
        assert bad.degraded == {}
        assert npg.ncl.feed_errors(json.loads(got[f"digest/tn/{gov}.json"])) == []
    else:
        assert bad.degraded == {gov: npg.ADAPTER_ERROR}
        entry = nat.load_all()[0].get(gov)
        assert json.loads(got[f"digest/tn/{gov}.json"]) == npg.bind_feed(ncopy.stale_feed(entry), entry)[0]
    assert_clean_lines(capsys.readouterr().out)


# --- 12.3 #8: switch off (S2b nit b) -----------------------------------------------------------------------------------

def _switch_off_roots(base: Path, review) -> dict:
    withheld = national_root(base / "w", body_file(review))
    return {"withheld-items": withheld, "bad-date": national_root(base / "d", body_file(review, date_="2026-02-30")),
            "missing-path": base / "nowhere", "symlink": _symlinked(base / "s", review)}


def test_switch_off_ignores_any_national_root(tmp_path, monkeypatch):
    folder = write_folder(tmp_path, dict(ENTRY, items="withheld"))       # the narrowed entry of #2
    point_at(monkeypatch, folder, None)

    def never(*a, **k):
        raise AssertionError("the copy step read national data with the switch off")
    monkeypatch.setattr(ncopy, "read_body_file", never)
    build(tmp_path / "unset", on=False)
    want = tree(tmp_path / "unset")
    assert not [k for k in want if k.startswith("digest/")]
    for name, root in _switch_off_roots(tmp_path / "roots", "a" * 64).items():
        out = tmp_path / name
        result = build(out, on=False, root=root)
        assert result["national"] == npg.OFF and result["national_states"] == {}
        assert tree(out) == want, name


# --- 12.3 #9: the site checks on feed text (N2) ------------------------------------------------------------------------

FEED_DAYS = ("Item added 2026-01-05", "Fetched 2026-01-05", "Data as of 2026-01-05", "meeting collected 2026-01-05")


def _checks(site: Path, monkeypatch) -> dict:
    facts = json.loads(FIXTURE.read_text(encoding="utf-8"))
    site_cfg = SC._site_cfg
    monkeypatch.setattr(SC, "_site_cfg", lambda: {**site_cfg(), "national": {"enabled": True}})
    rep = SC.run_checks(site, facts, browser=False, no_export=True, target="pages")
    return {name: (ok, problems) for name, ok, problems, _ in rep.results}


def test_site_checks_pass_a_build_whose_feed_text_holds_raw_days(world, tmp_path, monkeypatch):
    tag = config.SITE["switch"]["not_collected_tag"]
    text = " ".join([*FEED_DAYS, tag, "Coming"])
    doc = body_file(world["review"], title=f"{FEED_DAYS[0]} Coming", time=FEED_DAYS[1], text=text)
    doc["meetings"][0]["agenda"]["status_as_posted"] = f"{FEED_DAYS[2]} {tag}"
    out = tmp_path / "site"
    build(out, root=national_root(tmp_path, doc))
    page = (out / PAGE).read_text(encoding="utf-8")
    assert all(d in page for d in FEED_DAYS) and tag in page
    got = _checks(out, monkeypatch)
    want = _checks(world["baseline_dir"], monkeypatch)
    assert got == want                                    # the same results as the build with no national root
    assert got["dates/no-raw-utc-day"] == (True, [])
    assert got["notcollected/never-coming"][0] and got["sources"][0]


@pytest.mark.parametrize("rel", ["about.html", "digest/covered.html"])
def test_the_same_raw_day_outside_a_coming_up_page_still_fails(world, tmp_path, monkeypatch, rel):
    out = tmp_path / "site"
    shutil.copytree(world["baseline_dir"], out)
    p = out / rel
    html = p.read_text(encoding="utf-8")
    p.write_text(html.replace('<main id="main">', '<main id="main"><p>Item added 2026-01-05</p>', 1),
                 encoding="utf-8")
    ok, problems = _checks(out, monkeypatch)["dates/no-raw-utc-day"]
    assert not ok and any(rel in pr for pr in problems)


def test_a_raw_day_in_a_coming_up_page_s_footer_still_fails(world, tmp_path, monkeypatch):
    out = tmp_path / "site"
    shutil.copytree(world["baseline_dir"], out)
    p = out / PAGE
    html = p.read_text(encoding="utf-8")
    p.write_text(html.replace("</main>", "</main><p>Fetched 2026-01-05</p>", 1), encoding="utf-8")
    ok, problems = _checks(out, monkeypatch)["dates/no-raw-utc-day"]
    assert not ok and any(PAGE in pr for pr in problems)


def test_feed_text_exemption_is_scoped_to_coming_up_pages():
    assert SC.digest_gov_page(PAGE) and not SC.digest_gov_page(INDEX) and not SC.digest_gov_page("about.html")
    assert not SC.digest_gov_page("city/digest/tn/x.html")
    two = '<main id="main">a</main><main id="main">b</main>'
    assert SC.without_feed_text(two) == two              # not where base.html.j2 puts it: checked whole
    assert SC.without_feed_text('x<main id="main">Fetched 2026-01-05</main>y') == "xy"


# --- 12.3 #13: the sentinel through every degrade path ---------------------------------------------------------------

def test_no_degrade_path_prints_input_text(world, tmp_path, monkeypatch, capsys):
    """withheld-items, bad-date, bad-instant, adapter-error (the copy step or the adapter), render-error and tier 2,
    each with the sentinel in the input or the exception's own text: every printed line is ids, fixed words, type
    names and counts."""
    review = world["review"]
    seen = set()

    def one(name, root, patch=None):
        with monkeypatch.context() as mp:
            if patch:
                patch(mp)
            out = tmp_path / name
            result = build(out, root=root)
        lines = assert_clean_lines(capsys.readouterr().out)
        seen.update(result["national_states"].values())
        if result["national"] == npg.DEGRADED:
            seen.add(npg.DEGRADED)
        return lines

    narrowed = write_folder(tmp_path / "narrowed", dict(ENTRY, items="withheld"))
    with monkeypatch.context() as mp:
        point_at(mp, narrowed, None)
        one("withheld", national_root(tmp_path / "w", body_file(review)))
    one("bad-date", national_root(tmp_path / "d", body_file(review, date_=f"2026-02-30 {SENTINEL}")))
    one("bad-instant", national_root(tmp_path / "i", body_file(review, checked_at=SENTINEL)))
    good = national_root(tmp_path / "g", body_file(review))

    def boom(*a, **k):
        raise ValueError(SENTINEL)
    one("copy-step-error", good, lambda mp: mp.setattr(ncopy, "copy_feed", boom))
    one("adapter-error", good, lambda mp: mp.setattr(npg.ncl, "clarksville_feeds", boom))
    one("render-error", good, lambda mp: mp.setattr(npg, "meeting_view", boom))
    real, calls = nat.page_directory, []

    def first(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError(SENTINEL)
        return real(*a, **k)
    one("tier-2", good, lambda mp: mp.setattr(nat, "page_directory", first))
    assert seen == {ncopy.WITHHELD_ITEMS, ncopy.BAD_DATE, ncopy.BAD_INSTANT, npg.ADAPTER_ERROR,
                    npg.RENDER_ERROR, npg.DEGRADED}
