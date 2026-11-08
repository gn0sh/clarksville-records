"""Landing address box (address pin M2): rendered only with a map that has a georef and a configured geocoder; its
settings come from config/site.yml and georef.json; the browser run (tests/address_browser.js, Playwright) checks the
stubbed geocoder answers, the blocked-script fallback, no request before submit, and the one-screen fit."""
import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import FIXTURE, FIXTURE_DISTRICTS, ROOT, build, parse
from qa import site_checks
from sitegen import build as sitegen_build, config
from test_georef import G

REAL_DISTRICTS = config.DISTRICTS_PATH


@pytest.fixture(scope="module")
def real_map_site(tmp_path_factory):
    """Fixture facts drawn on the real traced map (which has georef.json next to it)."""
    out = tmp_path_factory.mktemp("addr") / "build" / "site"
    build(FIXTURE, out, seats_path=None, districts_path=REAL_DISTRICTS)
    return out


@pytest.fixture(scope="module")
def real_site(tmp_path_factory):
    """The real data on the real map, for the one-screen fit (a fixture build carries the FIXTURE banner)."""
    out = tmp_path_factory.mktemp("real") / "build" / "site"
    build(ROOT / "data" / "facts.json", out)
    return out


def addr_config(html):
    m = site_checks.ADDR_CONFIG.search(html)
    return json.loads(m.group(1)) if m else None


def test_box_is_hidden_until_the_script_shows_it_and_names_the_privacy_rule(real_map_site):
    html = (real_map_site / "index.html").read_text(encoding="utf-8")
    form = next(n for n in parse(html).walk() if n.attrs.get("id") == "addr-form")
    assert "hidden" in form.attrs and "action" not in form.attrs and "method" not in form.attrs
    text = " ".join(form.all_text().split())
    assert text.startswith("Find your district")
    assert ("Your address is sent to the U.S. Census Bureau's geocoder to find it on the map. "
            "This site doesn't store it.") in text
    assert f'<a data-ext="lookup" href="{config.SITE["district_lookup_url"]}" rel="noopener">GoVoteTN</a>' in html
    assert 'aria-describedby="addr-privacy"' in html and 'role="status"' in html
    assert re.search(r'static/georef\.js" defer></script>\s*<script src="static/address\.js" defer>', html)


def test_box_settings_come_from_config_and_georef(real_map_site):
    cfg = addr_config((real_map_site / "index.html").read_text(encoding="utf-8"))
    assert cfg == {"georef": {"projection": G["projection"], "affine": G["affine"],
                              "boundary_margin_m": G["boundary_margin_m"]},
                   "geocoder": config.SITE["geocoder_url"], "county": config.SITE["county_name"],
                   "district_label": config.SITE["district_label"], "lookup_url": config.SITE["district_lookup_url"],
                   "lookup_label": config.SITE["district_lookup_label"]}
    assert config.SITE["geocoder_url"] == "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"


def test_settings_json_is_escaped_for_the_script_element(real_map_site, monkeypatch, tmp_path):
    monkeypatch.setitem(config.SITE, "county_name", "</script><b>X & Y</b>")
    out = tmp_path / "site"
    build(FIXTURE, out, seats_path=None, districts_path=REAL_DISTRICTS)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "</script><b>" not in html and addr_config(html)["county"] == "</script><b>X & Y</b>"


def test_no_box_without_georef_or_geocoder(pages, monkeypatch, tmp_path):
    assert 'id="addr-form"' not in pages["index.html"]                # fixture map: no georef.json beside it
    assert "address.js" not in pages["index.html"] and "georef.js" not in pages["index.html"]
    monkeypatch.setitem(config.SITE, "geocoder_url", "")
    out = tmp_path / "site"
    build(FIXTURE, out, seats_path=None, districts_path=REAL_DISTRICTS)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert 'id="addr-form"' not in html and "address.js" not in html
    assert "Not sure of your district?" in html                          # the plain lookup line stays


def test_georef_for_another_pdf_stops_the_build(tmp_path):
    d = json.loads(REAL_DISTRICTS.read_text(encoding="utf-8"))
    (tmp_path / "districts.json").write_text(json.dumps(d), encoding="utf-8")
    (tmp_path / "georef.json").write_text(json.dumps(dict(G, source_sha256="0" * 64)), encoding="utf-8")
    with pytest.raises(sitegen_build.BuildError):
        build(FIXTURE, tmp_path / "site", seats_path=None, districts_path=tmp_path / "districts.json")


def test_geocoder_url_must_be_an_https_base():
    ok = dict(config.SITE)
    assert not sitegen_build.site_url_problems(ok)
    for bad in ("http://geocoding.geo.census.gov/x", "https://geocoding.geo.census.gov/x?benchmark=1",
                "https://geocoding.geo.census.gov/x#a", "javascript:alert(1)"):
        assert sitegen_build.site_url_problems({**ok, "geocoder_url": bad}), bad


def test_site_checks_hold_the_geocoder_to_the_exact_config_value(real_map_site, tmp_path):
    site = tmp_path / "site"
    shutil.copytree(real_map_site, site)
    pages = {p.relative_to(site).as_posix(): site_checks.parse(p) for p in site.rglob("*.html")}
    cfg = site_checks._site_cfg()
    assert site_checks.check_external(pages, site, cfg) == []
    idx = site / "index.html"
    idx.write_text(idx.read_text(encoding="utf-8").replace(cfg["geocoder_url"], "https://evil.example/geo"),
                   encoding="utf-8")
    assert site_checks.check_external(pages, site, cfg)


def _browser_ok():
    if not shutil.which("node"):
        return False
    return os.path.exists("/opt/pw-browsers") or bool(shutil.which("playwright"))


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_address_box_in_a_browser(real_site, tmp_path):
    pts = {k: next(p["lonlat"] for p in G["check_points"] if p["id"] == pid)
           for k, pid in (("district", "franklin-2nd"), ("near", "hwy48-loneoak"))}
    pts["outside"] = [-87.44, 36.665]
    f = tmp_path / "pts.json"
    f.write_text(json.dumps(pts), encoding="utf-8")
    env = dict(os.environ)
    if "NODE_PATH" not in env:
        env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    res = subprocess.run(["node", str(ROOT / "tests" / "address_browser.js"), str(real_site / "index.html"), str(f)],
                         capture_output=True, text=True, timeout=300, env=env)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    for vp, m in out["fit"].items():
        assert m["formShown"] and m["scrollHeight"] <= m["innerHeight"] and m["scrollWidth"] <= m["innerWidth"], (vp, m)
    c = out["cases"]
    assert c["district"]["text"].startswith("This address is in District 5.") and c["district"]["href"] == "districts/05.html"
    assert c["district"]["pin"] and c["district"]["found"] == ["5"]
    assert c["near"]["text"].startswith("This address is near a district line. Check GoVoteTN to be sure.")
    assert c["near"]["href"] == config.SITE["district_lookup_url"]
    assert c["outside"]["text"].startswith("This address is outside Montgomery County.")
    assert c["nomatch"]["text"].startswith("No match was found for that address.") and c["nomatch"]["href"]
    for k in ("badshape", "nocallback"):
        assert c[k]["text"] == "The address lookup did not answer. Look it up on GoVoteTN.", k
    for k in ("blocked", "servererror"):
        assert c[k]["text"] == "Address lookup isn't available here. Look it up on GoVoteTN.", k
    for k, v in c.items():
        assert v["typedRequests"] == 0 and len(v["requests"]) == 1, k        # nothing sent until submit, once
        q = v["requests"][0]
        assert q.startswith("?address=1%20Test%20St%2C%20Clarksville%20TN%20%3Cb%3E%26%22&benchmark=Public_AR_Current"
                            "&format=jsonp&callback=crGeocode"), q
        assert v["storage"] == 0 and v["scripts"] == 0, k                     # nothing stored, script removed
        assert "<b>" not in v["html"], k                                      # census text is never markup
