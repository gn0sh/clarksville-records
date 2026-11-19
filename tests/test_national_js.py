"""Node tests for static/national.js, the Daylight Digest lookup's pure part (daylight-national F1, F5), and the
numbers it copies from sitegen/national.py. Problem keys: national/postmessage-hardening, national/csp-jsonp-gadget."""
import base64
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sitegen import national as nat

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "site" / "static" / "national.js").read_text(encoding="utf-8")


@pytest.mark.skipif(not shutil.which("node"), reason="node not available")
def test_national_node_tests_pass():
    res = subprocess.run(["node", str(ROOT / "tests" / "national.test.js")], capture_output=True, text=True,
                         timeout=120, cwd=ROOT, env={**os.environ, "PYTHON": sys.executable})
    assert res.returncode == 0, res.stdout + res.stderr


@pytest.mark.skipif(not shutil.which("node"), reason="node not available")
def test_national_page_wiring_node_tests_pass():
    """F2: mount() on a fake digest/index.html (tests/national_page.test.js)."""
    res = subprocess.run(["node", str(ROOT / "tests" / "national_page.test.js")], capture_output=True, text=True,
                         timeout=120, cwd=ROOT, env={**os.environ, "PYTHON": sys.executable})
    assert res.returncode == 0, res.stdout + res.stderr


def test_page_wiring_uses_the_builder_mount_points_and_label_groups():
    """The ids national.js mounts on are the ones site/templates/digest/index.html.j2 writes, and the string groups
    it reads are the builder's SCRIPT_GROUPS (so a renamed id or group fails here, not silently in a browser)."""
    from sitegen import national_pages as npg
    tpl = (ROOT / "site" / "templates" / "digest" / "index.html.j2").read_text(encoding="utf-8")
    for i in ("digest-form", "digest-q", "digest-result", "digest-list", "digest-saved", "digest-noscript",
              "digest-pagedir", "digest-strings", "digest-config"):
        assert f'id="{i}"' in tpl and f'"{i}"' in JS, i
    assert re.search(r'var STRING_RE = /\^\(lookup\|form\|count\)', JS)
    assert set(npg.SCRIPT_GROUPS) == {"lookup.", "form.", "count."}
    assert 'var CONFIG_SCHEMA = "daylight-digest-config/1";' in JS
    assert '"schema": "daylight-digest-config/1"' in (ROOT / "sitegen" / "national_pages.py").read_text(encoding="utf-8")
    labels = npg.load_page_labels()
    used = set(re.findall(r'S\("((?:lookup|form|count)\.[a-z0-9-]+)"\)', JS))
    used |= set(re.findall(r'"((?:lookup|form|count)\.[a-z0-9-]+)"', JS))
    missing = sorted(k for k in used if k not in labels)
    assert not missing, missing


def js_number(name: str) -> int:
    m = re.search(rf"^\s*var {name} = (\d+);", JS, re.MULTILINE)
    assert m, f"national.js has no `var {name} = <number>;`"
    return int(m.group(1))


def test_max_answer_matches_the_build():
    assert js_number("MAX_ANSWER") == nat.MAX_ANSWER


def test_max_matches_matches_the_build():
    assert js_number("MAX_MATCHES") == nat.MAX_MATCHES


def test_storage_id_pattern_is_us_count_s():
    us = (ROOT / "site" / "static" / "us-count.js").read_text(encoding="utf-8")
    pat = r"/\^\(place\|county\|cousub\|sdu\|sds\|sde\)-\[0-9\]\{2,14\}\$/"
    assert re.search(r"var ID_RE = " + pat, JS) and re.search(r"var ID = " + pat, us)


def test_layers_and_geoid_lengths_match_the_build():
    got = dict(re.findall(r'layer: "(\w+)", name: "[^"]+", digits: (\d+)', JS))
    assert {k: int(v) for k, v in got.items()} == nat.GEOID_DIGITS
    assert list(got) == list(nat.LAYERS)


# --- digest/geo-frame.html (F5; architecture 4.0; security finding 1, national/csp-jsonp-gadget) --------------------

def frame_parts(html: str):
    csp = re.findall(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', html)
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", html, re.DOTALL)
    return csp, scripts


def test_geo_frame_csp_allows_only_its_inline_script_by_hash_and_the_census_path():
    html = nat.geo_frame_html()
    csp, scripts = frame_parts(html)
    assert len(csp) == 1 and len(scripts) == 1
    attrs, js = scripts[0]
    assert attrs == ""                                   # inline, no src
    assert js == nat.geo_frame_script()
    digest = "sha256-" + base64.b64encode(hashlib.sha256(js.encode("utf-8")).digest()).decode("ascii")
    assert csp[0] == (f"default-src 'none'; script-src '{digest}' "
                      "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress; base-uri 'none'; "
                      "form-action 'none'")
    from sitegen import views
    assert nat.script_hash(js) == views.script_hash(js) == digest
    # the CSP meta comes before the script, and the frame names no other host anywhere
    assert html.index("Content-Security-Policy") < html.index("<script")
    assert set(re.findall(r"[a-z]+://[^\s\"'/]+", html)) == {"https://geocoding.geo.census.gov"}
    assert '<meta name="referrer" content="no-referrer">' in html


def test_geo_frame_is_fixed_and_the_hash_follows_the_script(tmp_path):
    assert nat.geo_frame_html() == nat.geo_frame_html()
    p = tmp_path / "_geo_frame.js"
    p.write_text(nat.geo_frame_script().replace("var asked = false", "var asked  = false"), encoding="utf-8")
    other = nat.geo_frame_html(p)
    assert frame_parts(other)[0][0] != frame_parts(nat.geo_frame_html())[0][0]
    js = frame_parts(other)[1][0][1]
    assert nat.script_hash(js) in frame_parts(other)[0][0]


@pytest.mark.parametrize("bad", ["x = '</script>';", "/* <!-- */", 'var u = "https://evil.example/x.js";',
                                 'var v = "http://geocoding.geo.census.gov/x";'])
def test_geo_frame_script_refuses_end_tags_and_other_hosts(tmp_path, bad):
    p = tmp_path / "_geo_frame.js"
    p.write_text(nat.geo_frame_script() + "\n" + bad + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        nat.geo_frame_html(p)


def test_geo_frame_script_must_name_the_census_path(tmp_path):
    p = tmp_path / "_geo_frame.js"
    p.write_text("(function () { parent.postMessage('\"ready\"', '*'); })();\n", encoding="utf-8")
    with pytest.raises(ValueError):
        nat.geo_frame_html(p)


def test_only_the_frame_names_the_census_in_a_csp():
    """The parent pages' CSP keeps script-src 'self' (B13 adds the site-wide digest/csp check once B4 builds the
    pages): the shared CSP without the Clarksville address box names no Census host, and national.js loads the frame
    from the fixed geo-frame.html with the address in no URL."""
    from sitegen import views
    for kw in ({}, {"counter": "https://daylight-gnosh.goatcounter.com"}, {"form_origin": "https://buttondown.com"}):
        assert "census.gov" not in views.csp(**kw)
    assert "geocoding.geo.census.gov" in nat.geo_frame_csp(nat.geo_frame_script())
    assert nat.GEO_FRAME_PAGE == "digest/geo-frame.html"
    assert re.search(r'fr\.setAttribute\("src", env\.frameSrc \|\| "geo-frame\.html"\);', JS)
    assert re.search(r'fr\.setAttribute\("sandbox", "allow-scripts"\);', JS)
    assert "allow-same-origin" not in JS.split("*/", 1)[1]
