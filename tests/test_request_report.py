"""tools/national/request_report.py (task B12): counts, ignored ids, no key or email out, errors. No network."""
import io
import urllib.error
from collections import Counter

import pytest

from tools.national import request_report as rr

KEY = "bd_secretkey_0123456789abcdef"
KNOWN = {"place-4748000", "county-47125", "place-1"}


def row(email, tags, type_="regular"):
    return {"id": "sub_" + email[:3], "email_address": email, "type": type_, "tags": tags,
            "metadata": {}, "creation_date": "2026-11-18T10:00:00Z"}


def pages(*rows_by_page):
    def fetch(url):
        i = 0 if url == rr.FIRST_URL else int(url.rsplit("page=", 1)[1]) - 1
        more = i + 1 < len(rows_by_page)
        nxt = f"https://api.buttondown.com/v1/subscribers?type=regular&page={i + 2}" if more else None
        return {"results": rows_by_page[i], "next": nxt, "count": 9}
    return fetch


def test_counts_confirmed_only_and_ignores_unknown():
    p1 = [row("a@example.com", ["req-place-4748000", "note-x"]),
          row("b@example.com", ["req-place-4748000", "req-county-47125", "req-place-4748000"]),
          row("c@example.com", ["req-place-4748000"], "unactivated"),
          row("d@example.com", ["req-bogus", "req-"])]
    p2 = [row("e@example.com", ["req-county-47125", "req-evil-1"]), {"junk": 1}, row("f@example.com", None)]
    counts, ignored, subs = rr.count_requests(pages(p1, p2), KNOWN)
    assert dict(counts) == {"place-4748000": 2, "county-47125": 2}
    assert ignored == 3 and subs == 5


def test_render_header_and_order():
    out = rr.render(Counter({"b": 1, "a": 3}), 2, 5, {"a": "A town"})
    assert "advisory: anyone can tag a known email" in out.splitlines()[0]
    assert "ignored req- tags not in the directory: 2" in out
    assert out.index("A town") < out.index("  b")


def test_main_output_has_no_email_or_key_and_writes_nothing(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    emails = ["a@example.com", "b@example.com"]
    f = pages([row(emails[0], ["req-bogus"]), row(emails[1], ["req-bogus-2"])])
    assert rr.main([], env={rr.KEY_ENV: KEY}, fetch=f) == 0
    cap = capsys.readouterr()
    for s in (*emails, KEY, "@"):
        assert s not in cap.out + cap.err
    assert list(tmp_path.iterdir()) == []


def test_main_needs_key(capsys):
    assert rr.main([], env={}) == 2
    assert rr.main([], env={rr.KEY_ENV: "short"}) == 2
    assert "short" not in capsys.readouterr().out


def test_error_exit_does_not_echo_key(capsys):
    def boom(url):
        raise rr.ReportError("Buttondown answered HTTP 401 (check the key)")
    assert rr.main([], env={rr.KEY_ENV: KEY}, fetch=boom) == 1
    cap = capsys.readouterr()
    assert KEY not in cap.out + cap.err


def test_help_says_brians_pc(capsys):
    with pytest.raises(SystemExit):
        rr.main(["--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "Brian's PC" in out and rr.KEY_ENV in out and "anyone can tag" in out


def test_foreign_or_plain_http_links_refused():
    with pytest.raises(rr.ReportError):
        rr._fetch("https://evil.example/v1/subscribers", KEY)
    with pytest.raises(rr.ReportError):
        rr._fetch("http://api.buttondown.com/v1/subscribers", KEY)


def test_pagination_that_does_not_advance_fails():
    with pytest.raises(rr.ReportError):
        rr.count_requests(lambda url: {"results": [], "next": rr.FIRST_URL}, KNOWN)


def test_http_error_hides_key_and_body(monkeypatch):
    class Op:
        def open(self, req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(b"body a@example.com"))
    monkeypatch.setattr(rr.urllib.request, "build_opener", lambda *a: Op())
    with pytest.raises(rr.ReportError) as e:
        rr._fetch(rr.FIRST_URL, KEY)
    assert KEY not in str(e.value) and "@" not in str(e.value) and "401" in str(e.value)
    assert e.value.__cause__ is None


def test_real_directory_loads_and_unknown_counted(capsys):
    assert rr.main([], env={rr.KEY_ENV: KEY}, fetch=pages([row("a@example.com", ["req-zzz"])])) == 0
    assert "ignored req- tags not in the directory: 1" in capsys.readouterr().out
