"""Daylight Digest national collect entry point (collector/national/__main__.py; docs/architecture/daylight-national.md
4.6 "D1 fetcher", "D1 logs", "D1 data path"; 11.1 row 23). The real PoliteFetcher runs with its network faked (no
real network). The CLI prints body ids, 3.7 kinds and counts only: never the fetcher log, an exception's text or a
traceback, which can hold a 403 body snippet and the Server header."""
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from collector import fetch
from collector.fetch import HostBlocked, PoliteFetcher
from collector.national import __main__ as cli
from collector.national import legistar_upcoming as lu
from collector.national import run as nr
from sitegen import national as nat

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 12, 1, 18, 0, tzinfo=timezone.utc)
HOST_OK = {"date": "2026-11-18", "link": "https://github.com/gn0sh/clarksville-records/pull/1"}
SECRET = "SECRET-403-SNIPPET <html>Forbidden by policy</html>"
SERVER = "Server: secret-edge/9.9"


def body(n, client):
    return {"gov": f"place-41{n:05d}", "also": [], "body_name": f"Example Council {n}", "state": "OR",
            "status": "covered", "official_url": f"https://{client}.legistar.com/Calendar.aspx",
            "checked": "2026-12-01", "checked_url": f"https://{client}.legistar.com/Calendar.aspx", "items": "withheld",
            "platform": "legistar", "legistar": {"client": client, "body_id": 100 + n, "tz": "America/Los_Angeles"},
            "host_ok": HOST_OK}


GOVS = [body(1, "aa"), body(2, "bb"), body(3, "cc")]


class Resp(io.BytesIO):
    status, headers = 200, {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Net:
    """The faked network. `fail[client]` answers that client's events query with (code, body bytes, headers)."""

    def __init__(self, fail=None):
        self.fail, self.calls = fail or {}, []

    def __call__(self, req, timeout):
        url = req.full_url
        self.calls.append(url)
        u = urlsplit(url)
        if u.path == "/robots.txt":
            raise urllib.error.HTTPError(url, 404, "x", {}, io.BytesIO(b""))
        client = u.path.split("/")[2]
        if client in self.fail:
            code, payload, headers = self.fail[client]
            raise urllib.error.HTTPError(url, code, "x", headers, io.BytesIO(payload))
        assert parse_qs(u.query)["$filter"]
        return Resp(b"[]")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """A directory of GOVS (labels.yml beside it), a data root, a fixed clock and a recorded fetcher constructor."""
    conf = tmp_path / "conf"
    conf.mkdir()
    shutil.copy(nat.NATIONAL_DIR / "labels.yml", conf / "labels.yml")
    directory = conf / "directory.yml"
    directory.write_text(yaml.safe_dump({"schema": "daylight-directory/1", "govs": GOVS}, sort_keys=False),
                         encoding="utf-8")
    data_root = tmp_path / "nd" / "data" / "national"
    monkeypatch.setattr(cli, "_wall", lambda: NOW)
    state = {"net": Net(), "built": []}

    def recording_fetcher(**kwargs):
        state["built"].append(kwargs)
        f = PoliteFetcher(**kwargs, opener=state["net"], sleep=lambda s: None, proxy_failures=lambda: [])
        state["fetcher"] = f
        return f
    monkeypatch.setattr(cli, "PoliteFetcher", recording_fetcher)
    state.update(directory=directory, data_root=data_root)
    return state


def run_cli(setup, *extra):
    return cli.main([str(setup["data_root"]), "--directory", str(setup["directory"]), *extra])


# --- the fetcher (4.6 "D1 fetcher") --------------------------------------------------------------------------------

def test_the_fetcher_is_built_for_webapi_only_with_the_reader_size_cap(setup, capsys):
    assert run_cli(setup) == 0
    assert setup["built"] == [{"allowed_hosts": ("webapi.legistar.com",), "max_bytes": lu.MAX_RESPONSE_BYTES}]
    f = setup["fetcher"]
    assert f.allowed_hosts == ("webapi.legistar.com",) and f.allowed_hosts != fetch.ALLOWED_HOSTS
    assert f.max_bytes == lu.MAX_RESPONSE_BYTES < fetch.MAX_BYTES
    assert f.min_delay == fetch.MIN_DELAY                              # the politeness floor is the fetcher's own


def test_build_fetcher_never_uses_the_clarksville_defaults():
    f = cli.build_fetcher()
    assert f.allowed_hosts == ("webapi.legistar.com",)
    assert not any(fetch.host_matches(h, f.allowed_hosts) for h in fetch.ALLOWED_HOSTS)
    assert f.max_bytes == lu.MAX_RESPONSE_BYTES


# --- output (4.6 "D1 logs") ----------------------------------------------------------------------------------------

def test_a_completed_run_prints_only_ids_kinds_and_counts_and_writes_the_outputs(setup, capsys):
    assert run_cli(setup, "--budget", "50") == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert out.splitlines() == ["body place-4100001 ok", "body place-4100002 ok", "body place-4100003 ok",
                                "counts ok=3 bodies=3 feeds=3 proposals=0 requests=4/50"]
    root = setup["data_root"]
    assert sorted(p.name for p in (root / "bodies").iterdir()) == [f"{g['gov']}.json" for g in GOVS]
    assert set(json.loads((root / "health.json").read_text())) == {g["gov"] for g in GOVS}


def test_a_403_body_and_server_header_reach_the_fetcher_log_but_never_the_output(setup, capsys):
    setup["net"].fail = {"bb": (403, SECRET.encode(), {"Server": "secret-edge/9.9"})}
    assert run_cli(setup) == 0
    out, err = capsys.readouterr()
    log = json.dumps(setup["fetcher"].log)
    assert "SECRET-403-SNIPPET" in log and "secret-edge" in log         # the test is meaningful: the log holds them
    for text in ("SECRET-403-SNIPPET", "Forbidden", "secret-edge", "Server", "Traceback", "webapi", "http"):
        assert text not in out + err
    assert out.splitlines() == ["body place-4100001 ok", "body place-4100002 host-stopped",
                                "body place-4100003 host-stopped",
                                "counts ok=1 host-stopped=2 bodies=3 feeds=1 proposals=0 requests=3/300"]


def test_a_reader_exception_text_is_never_printed(setup, capsys, monkeypatch):
    def boom(entry, fetcher, now, cache_root):
        raise RuntimeError(f"HTTP 403 from the site: {SECRET} {SERVER}")
    monkeypatch.setattr(lu, "read_body", boom)
    assert run_cli(setup) == 0                                          # one body's failure is never the run's
    out, err = capsys.readouterr()
    for text in ("SECRET", "Forbidden", "secret-edge", "Server", "RuntimeError", "Traceback"):
        assert text not in out + err
    assert out.splitlines()[-1] == "counts collector-error=3 bodies=3 feeds=0 proposals=0 requests=0/300"


@pytest.mark.parametrize("exc", [HostBlocked, fetch.TenantBlocked, OSError, RecursionError, KeyError, ValueError])
def test_a_run_failure_prints_the_type_name_only_and_exits_1(setup, capsys, monkeypatch, exc):
    def failing(*a, **k):
        try:
            raise ValueError(f"inner {SECRET}")
        except ValueError:
            raise exc(f"HTTP 403 from the site on https://webapi.legistar.com/v1/bb/events: {SECRET} {SERVER}")
    monkeypatch.setattr(nr, "collect", failing)
    assert run_cli(setup) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert err == f"python -m collector.national: failed: {exc.__name__}\n"


def test_an_exception_while_loading_the_directory_prints_the_type_name_only(setup, capsys, monkeypatch):
    def bad(path=None):
        raise nat.NationalConfigError(f"{path}: {SECRET}")
    monkeypatch.setattr(nat, "load_directory", bad)
    assert run_cli(setup) == 1
    out, err = capsys.readouterr()
    assert (out, err) == ("", "python -m collector.national: failed: NationalConfigError\n")
    assert setup["built"] == []                                         # no fetcher was built


def test_report_never_echoes_an_unknown_kind_or_a_bad_id():
    r = nr.RunResult(feeds={}, health={}, proposals=[],
                     outcomes={"place-4100001": "ok", "place-4100002": SECRET, "../etc": "ok", 7: "ok"})
    lines = cli.report(r, 2, 300)
    assert lines == ["body place-4100001 ok", "counts ok=1 unprintable=3 bodies=4 feeds=0 proposals=0 requests=2/300"]


def test_keyboard_interrupt_exits_130_with_one_line(setup, capsys, monkeypatch):
    def interrupted(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(nr, "collect", interrupted)
    assert run_cli(setup) == 130
    assert capsys.readouterr() == ("", "python -m collector.national: interrupted\n")


def test_the_last_resort_hook_prints_the_type_name_only(capsys):
    try:
        raise RuntimeError(SECRET)
    except RuntimeError as e:
        cli._last_resort(type(e), e, e.__traceback__)
    assert capsys.readouterr().err == "python -m collector.national: failed: RuntimeError\n"


# --- host_ok (R5) -------------------------------------------------------------------------------------------------

def test_host_not_approved_prints_the_type_and_body_id_and_sends_nothing(setup, capsys, monkeypatch):
    monkeypatch.setattr(nr, "host_ok_problem", lambda v, today: ("host_ok", SECRET))   # as if Brian's OK were missing
    assert run_cli(setup) == 1
    out, err = capsys.readouterr()
    assert (out, err) == ("", "python -m collector.national: failed: HostNotApproved body place-4100001\n")
    assert setup["net"].calls == []
    assert not setup["data_root"].exists()                              # nothing read or written


def test_host_not_approved_with_a_bad_id_carries_no_id():
    e = nr.HostNotApproved("x", "../../etc")
    assert e.gov is None and cli._failure(e) == "python -m collector.national: failed: HostNotApproved"


# --- the data root (4.6 "D1 data path") ---------------------------------------------------------------------------

@pytest.mark.parametrize("where", ["root", "bodies", "cache"])
def test_a_symlink_in_the_data_tree_is_refused_before_any_request(setup, capsys, tmp_path, where):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    root = setup["data_root"]
    if where == "root":
        root.parent.mkdir(parents=True)
        os.symlink(elsewhere, root)
    else:
        root.mkdir(parents=True)
        os.symlink(elsewhere, root / where)
    assert run_cli(setup) == 1
    assert capsys.readouterr() == ("", "python -m collector.national: failed: ValueError\n")
    assert setup["built"] == [] and setup["net"].calls == []
    assert list(elsewhere.iterdir()) == []


def test_a_data_root_that_is_a_file_is_refused(setup, capsys):
    setup["data_root"].parent.mkdir(parents=True)
    setup["data_root"].write_text("x")
    assert run_cli(setup) == 1
    assert capsys.readouterr().err == "python -m collector.national: failed: ValueError\n"
    assert setup["built"] == []


# --- arguments ----------------------------------------------------------------------------------------------------

def test_the_default_budget_is_300_and_the_default_directory_is_the_loader_s(setup, monkeypatch):
    seen = {}
    loaded = []
    monkeypatch.setattr(nat, "load_directory", lambda *a: loaded.append(a) or "the directory")

    def fake_collect(root, directory, fetcher, budget, now, *, clock):
        seen.update(directory=directory, budget=budget, now=now, clock=clock())
        return nr.RunResult({}, {}, [], {})
    monkeypatch.setattr(nr, "collect", fake_collect)
    assert cli.main([str(setup["data_root"])]) == 0
    assert loaded == [()]                                               # load_directory() with its own default path
    assert seen == {"directory": "the directory", "budget": 300, "now": NOW, "clock": NOW}


@pytest.mark.parametrize("value", ["0", "-1", "451", "ten", "1e3"])
def test_a_bad_budget_is_a_usage_error(setup, value, capsys):
    with pytest.raises(SystemExit) as e:
        run_cli(setup, "--budget", value)
    assert e.value.code == 2
    assert setup["built"] == []


def test_python_dash_m_runs_the_entry_point_without_a_traceback(tmp_path):
    """The package runs as `python -m collector.national`; a refused data root fails before any fetcher exists."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.symlink(elsewhere, tmp_path / "national")
    p = subprocess.run([sys.executable, "-m", "collector.national", str(tmp_path / "national")], cwd=ROOT,
                       capture_output=True, text=True, timeout=120)
    assert (p.returncode, p.stdout, p.stderr) == (1, "", "python -m collector.national: failed: ValueError\n")
