"""third-party-script/no-csp: every page carries one Content-Security-Policy <meta>, before any script or stylesheet;
script-src is 'self' everywhere but the landing with the address box (tests/test_address_box.py covers that one).
The browser run (tests/csp_browser.js, Playwright, over a local http server) checks the site still works under it:
nav drawer, landing search submit and results, Show more, the map highlight, the bar widths, the address box's
iframe path, and no CSP violation on any page visited."""
import functools
import http.server
import json
import os
import re
import shutil
import subprocess
import threading

import pytest

from conftest import ROOT, build
from qa import site_checks
from sitegen import views

META = re.compile(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">')


def test_every_page_has_one_csp_meta_first(pages):
    for rel, html in pages.items():
        found = META.findall(html)
        assert len(found) == 1, rel
        pol = site_checks.parse_csp(found[0].replace("&#39;", "'"))
        assert pol["script-src"] == ["'self'"] and pol["default-src"] == ["'self'"], rel
        assert pol["connect-src"] == ["'none'"] and pol["object-src"] == ["'none'"] and pol["base-uri"] == ["'none'"], rel
        assert pol["style-src-elem"] == ["'self'"] and pol["form-action"] == ["'self'"], rel
        head = html[:html.index("</head>")]
        assert head.index("Content-Security-Policy") < min(i for i in (head.find("<link"), head.find("<script"),
                                                                         len(head)) if i >= 0), rel


def test_csp_text_is_the_one_views_makes():
    assert views.csp() == ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                           "style-src-elem 'self'; connect-src 'none'; img-src 'self' data:; object-src 'none'; "
                           "base-uri 'none'; form-action 'self'; frame-src 'self'")


def test_no_inline_script_or_style_element_in_any_page(pages):
    """Under the CSP an inline <script> (other than JSON data) or a <style> element would silently not run."""
    for rel, html in pages.items():
        for attrs in re.findall(r"<script\b([^>]*)>", html):
            assert "src=" in attrs or 'type="application/json"' in attrs, (rel, attrs)
        assert "<style" not in html, rel


def _browser_ok():
    if not shutil.which("node"):
        return False
    return os.path.exists("/opt/pw-browsers") or bool(shutil.which("playwright"))


@pytest.fixture(scope="module")
def served_site(tmp_path_factory):
    out = tmp_path_factory.mktemp("csp") / "build" / "site"
    build(ROOT / "data" / "facts.json", out)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield out, f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_site_works_under_its_csp_in_a_browser(served_site):
    out, base = served_site
    clamp_page = next(p.relative_to(out).as_posix() for p in sorted((out / "districts").glob("*.html"))
                      if 'class="clamp"' in p.read_text(encoding="utf-8"))
    official = next(p.relative_to(out).as_posix() for p in sorted((out / "officials").glob("*.html"))
                    if 'class="bar"' in p.read_text(encoding="utf-8"))
    env = dict(os.environ)
    if "NODE_PATH" not in env:
        env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    res = subprocess.run(["node", str(ROOT / "tests" / "csp_browser.js"), base, clamp_page, official],
                         capture_output=True, text=True, timeout=300, env=env)
    assert res.returncode == 0, res.stderr
    pg = json.loads(res.stdout)["pages"]
    for name, r in pg.items():
        assert r["violations"] == [] and r["refused"] == [], (name, r["violations"], r["refused"])
    land = pg["landing"]
    assert "census.gov" in land["landingCsp"] and land["drawerOpen"] and land["addrShown"] and "5" in land["mapLit"]
    assert land["addrResult"].startswith("No match was found")            # the iframe path answered under the CSP
    assert land["searchHits"] > 0                                          # form-action 'self' lets the search go
    assert pg["landing-phone"]["drawerOpen"] and pg["meeting"]["clampButtons"] > 0
    widths, ns = pg["official"]["segWidths"], [int(n) for n in pg["official"]["segN"]]
    assert len(set(widths)) > 1 and all((w == 0) == (n == 0) for w, n in zip(widths, ns))   # --n style attrs apply
