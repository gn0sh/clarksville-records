"""tools/national/request_report.py (task B12): counts, aliases, ignored ids, no key or email out, no file written,
errors. No network: the Buttondown adapter gets the FakeHTTP opener of the adapter's own tests, and any socket use
fails."""
import builtins
import io
import os
import socket
from collections import Counter

import pytest

import sitegen.national as national
from test_morning_sender_buttondown import FakeHTTP, Resp
from tools.national import request_report as rr

KEY = "bd_secretkey_0123456789abcdef"
KNOWN = {"place-4748000": "place-4748000", "county-47125": "county-47125", "place-1": "place-1",
         "place-1old": "place-1"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a test tried to open a real connection")
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, refuse)


def row(n, tags, type_="regular"):
    return {"id": f"sub_{n:04d}", "email_address": f"person{n}@example.com", "type": type_, "tags": tags,
            "metadata": {}, "creation_date": "2026-11-18T10:00:00Z"}


def run(http, capsys, env=None):
    code = rr.main([], env={rr.KEY_ENV: KEY} if env is None else env, opener=http)
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def test_counts_confirmed_only_aliases_once_and_ignores_unknown():
    rows = [row(1, ["req-place-4748000", "note-x"]),
            row(2, ["req-place-4748000", "req-county-47125", "req-place-4748000"]),
            row(3, ["req-place-4748000"], "unactivated"),
            row(4, ["req-bogus", "req-"]),
            row(5, ["req-county-47125", "req-evil-1"]),
            row(6, ["req-place-1", "req-place-1old"]),       # an id and its `also` alias: one request
            row(7, ["req-place-1old"]),
            {"junk": 1}]
    counts, ignored, subs = rr.count_requests(rows, KNOWN)
    assert dict(counts) == {"place-4748000": 2, "county-47125": 2, "place-1": 2}
    assert ignored == 3 and subs == 6


def test_render_header_and_order():
    out = rr.render(Counter({"b": 1, "a": 3}), 2, 5, {"a": "A town"})
    assert "advisory: anyone can tag a known email" in out.splitlines()[0]
    assert "ignored req- tags not in the directory: 2" in out
    assert out.index("A town") < out.index("  b")


def test_through_the_adapter_every_page_regular_only(capsys):
    http = FakeHTTP([row(1, ["req-county-47125"]), row(2, ["req-county-47125", "req-zzz"]),
                     row(3, ["req-county-47125"], "unactivated"), row(4, [])], page_size=2)
    code, out, err = run(http, capsys)
    assert code == 0, err
    assert "confirmed subscribers read: 3" in out and "ignored req- tags not in the directory: 1" in out
    assert "    2  county-47125  Montgomery County Commission" in out
    assert len(http.calls("GET", "/subscribers")) == 2
    for method, url, headers, _body, _t in http.requests:
        assert method == "GET" and url.startswith("https://api.buttondown.com/v1/subscribers")
        assert "type=" not in url and headers["authorization"] == f"Token {KEY}"


def test_a_short_listing_fails_and_does_not_undercount(capsys):
    # the provider says 9 subscribers but the pages hold 2: the report must fail, never print a smaller count
    short = Resp(200, {"results": [row(1, ["req-county-47125"]), row(2, ["req-county-47125"])], "next": None,
                       "count": 9})
    code, out, err = run(FakeHTTP(faults={("GET", "/subscribers"): [short]}), capsys)
    assert code == 1 and out == ""
    assert err == "error: could not read the subscriber list from Buttondown\n"


@pytest.mark.parametrize("fault, text", [
    (Resp(401, {"detail": "bad token person1@example.com"}), "Buttondown refused the key (check it)"),
    (Resp(500, {"detail": "person1@example.com"}), "could not read the subscriber list from Buttondown"),
    (Resp(429, {}, headers={"Retry-After": "30"}), "Buttondown asked to slow down; try again in a minute"),
    (Resp(200, raw=b"<html>person1@example.com</html>", ctype="text/html"),
     "could not read the subscriber list from Buttondown"),
    (Resp(200, {"results": [], "next": "https://api.buttondown.com:abc/v1/subscribers?page=2", "count": 0}),
     "could not read the subscriber list from Buttondown"),
    (Resp(200, {"results": [], "next": "https://evil.example/v1/subscribers?page=2", "count": 0}),
     "could not read the subscriber list from Buttondown"),
    (OSError("connection reset to person1@example.com " + KEY), "could not read the subscriber list from Buttondown"),
])
def test_adapter_errors_exit_1_with_fixed_text(capsys, fault, text):
    code, out, err = run(FakeHTTP(faults={("GET", "/subscribers"): [fault]}), capsys)
    assert code == 1 and out == "" and err == f"error: {text}\n"


def test_main_output_has_no_email_or_key_and_writes_nothing(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    national.load_directory()              # warm imports first, so no import writes a cache while open is patched
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open
    writes = []

    def guard(real):
        def opener(file, mode="r", *a, **k):
            if any(c in mode for c in "wax+"):
                writes.append(str(file))
                raise AssertionError("main() opened a file for writing")
            return real(file, mode, *a, **k)
        return opener

    def os_guard(path, flags, *a, **k):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
            writes.append(str(path))
            raise AssertionError("main() opened a file for writing")
        return real_os_open(path, flags, *a, **k)

    monkeypatch.setattr(builtins, "open", guard(real_open))
    monkeypatch.setattr(io, "open", guard(real_io_open))
    monkeypatch.setattr(os, "open", os_guard)
    http = FakeHTTP([row(1, ["req-bogus"]), row(2, ["req-county-47125"])])
    code, out, err = run(http, capsys)
    monkeypatch.undo()
    assert code == 0 and writes == []
    for s in ("person1@example.com", "person2@example.com", KEY, "@"):
        assert s not in out + err
    assert list(tmp_path.iterdir()) == []


def test_main_needs_key(capsys):
    assert rr.main([], env={}) == 2
    assert rr.main([], env={rr.KEY_ENV: "short"}) == 2
    assert "short" not in capsys.readouterr().err


def test_a_bad_directory_exits_1_with_its_message(capsys, monkeypatch):
    def bad(*a, **k):
        raise national.NationalConfigError("config/national/directory.yml: entry 1: gov: bad id 'x'")
    monkeypatch.setattr(national, "load_directory", bad)
    code, out, err = run(FakeHTTP(), capsys)
    assert code == 1 and out == ""
    assert err == "error: config/national/directory.yml: entry 1: gov: bad id 'x'\n"


def test_an_also_alias_counts_for_its_canonical_id(capsys, monkeypatch):
    real = national.load_directory()
    gov = real.govs[0]["gov"]
    monkeypatch.setattr(national, "load_directory",
                        lambda *a, **k: national.Directory(govs=real.govs, alias={"place-0000001": gov}))
    code, out, _err = run(FakeHTTP([row(1, ["req-place-0000001", f"req-{gov}"]), row(2, ["req-place-0000001"])]),
                          capsys)
    assert code == 0
    assert f"    2  {gov}  " in out and "place-0000001" not in out
    assert "ignored req- tags not in the directory: 0" in out


def test_help_says_brians_pc_and_the_powershell_steps(capsys):
    with pytest.raises(SystemExit):
        rr.main(["--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "Brian's PC" in out and rr.KEY_ENV in out and "anyone can tag" in out
    assert 'Read-Host -MaskInput "Buttondown key"' in out and "Remove-Item Env:BUTTONDOWN_API_KEY" in out
    assert "python -I tools\\national\\request_report.py" in out and "pip install -r requirements.txt" in out
    assert "BUTTONDOWN_API_KEY=" not in out


def test_docstring_steps_never_put_the_key_on_a_command_line():
    doc = rr.__doc__
    assert "BUTTONDOWN_API_KEY=" not in doc and "Standard library only" not in doc
    for step in ('$env:BUTTONDOWN_API_KEY = Read-Host -MaskInput "Buttondown key"',
                 "python -I tools\\national\\request_report.py", "Remove-Item Env:BUTTONDOWN_API_KEY",
                 "python -m pip install -r requirements.txt"):
        assert step in doc
