"""Landing address box (address pin M2): rendered only with a districts file that has a georef and a configured
geocoder; its settings come from config/site.yml, georef.json and the traced lines in districts.json (no map is drawn); the browser run (tests/address_browser.js, Playwright) checks the
stubbed geocoder answers, the blocked-script fallback, no request before submit, and the one-screen fit."""
import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import FIXTURE, ROOT, at_width, build, parse
from qa import site_checks
from sitegen import build as sitegen_build, config, georef, views
from test_georef import G
from test_ward_map import WG

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
    """The box's settings block, read the way qa/site_checks.check_external reads it (Page.json_blocks)."""
    pg = site_checks.Page()
    pg.feed(html)
    blocks = pg.json_blocks.get("addr-config", [])
    return json.loads(blocks[0]) if blocks else None


def test_box_is_hidden_until_the_script_shows_it_and_names_the_privacy_rule(real_map_site):
    raw = (real_map_site / "index.html").read_text(encoding="utf-8")
    html = at_width(raw, phone=False)                  # the wide wording; the phone's is in test_mobile_front_lite.py
    form = next(n for n in parse(html).walk() if n.attrs.get("id") == "addr-form")
    assert "hidden" in form.attrs and "action" not in form.attrs and "method" not in form.attrs
    text = " ".join(form.all_text().split())
    assert text.startswith("Enter your street address to see your city ward and county district.")   # the wards
    assert ("Your address is sent to the U.S. Census Bureau's geocoder to find where it is. "
            "This site doesn't store it. Census's privacy policy applies. Or look it up on GoVoteTN.") in text
    # the note on what is saved moved into "How the address lookup works, and what is saved" (front-page-v2)
    about = html[html.index('<details class="lookup-about">'):]
    about = about[:about.index("</details>")]
    assert "only the district and ward numbers are kept, in this browser on this device" in about
    assert "City ward lookup is coming" not in html
    assert f'<a data-ext="lookup" href="{config.SITE["district_lookup_url"]}" rel="noopener">GoVoteTN</a>' in html
    assert (f'<a data-ext="geocoder" href="{config.SITE["geocoder_privacy_url"]}" rel="noopener">'
            'Census\'s privacy policy</a><span class="phone-off"> applies.</span>') in html
    assert config.SITE["geocoder_privacy_url"] == "https://www.census.gov/about/policies/privacy.html"
    assert 'aria-describedby="addr-privacy"' in html and 'role="status"' in html
    assert re.search(r'static/georef\.js" defer></script>\s*<script src="static/address\.js" defer>', html)


def test_box_settings_come_from_config_and_georef(real_map_site):
    cfg = addr_config((real_map_site / "index.html").read_text(encoding="utf-8"))
    d = json.loads(REAL_DISTRICTS.read_text(encoding="utf-8"))
    wards = d["wards"]
    # the traced lines travel as data (no map is drawn): every district and ward path, each with its page
    assert cfg.pop("districts") == [{"number": x["number"], "path": x["path"],
                                     "href": f"districts/{int(x['number']):02d}.html"}
                                    for x in sorted(d["districts"], key=lambda x: x["number"])]
    got_wards = cfg.pop("wards")
    assert [(w["number"], w["path"]) for w in got_wards] == [(w["number"], w["path"])
                                                             for w in sorted(wards["wards"], key=lambda w: w["number"])]
    # a fixture build has no council pages, so no ward links (the browser run checks them on the real build)
    assert all(w["href"] is None for w in got_wards), [w["href"] for w in got_wards]
    assert cfg == {"georef": {"projection": G["projection"], "affine": G["affine"],
                              "boundary_margin_m": G["boundary_margin_m"]},
                   "geocoder": config.SITE["geocoder_url"], "geocoder_short": "Census",
                   "county": config.SITE["county_name"],
                   "district_label": config.SITE["district_label"], "lookup_url": config.SITE["district_lookup_url"],
                   "lookup_label": config.SITE["district_lookup_label"], "frame": views.geocode_frame_script(),
                   "ward_margin_m": wards["boundary_margin_m"], "ward_label": config.SITE["ward_label"],
                   "city": config.SITE["city_name"], "ward_map_owner": config.SITE["ward_map_owner"],
                   "ward_map_date": wards["source_updated"],
                   "places": config.SITE["geocoder_places"], "state": "TN", "state_name": "Tennessee"}
    # the county's mailing places a bare street is tried with (address-lookup-bare-street), Clarksville first
    assert config.SITE["geocoder_places"] == ["Clarksville", "Woodlawn", "Cunningham", "Southside", "Palmyra"]
    assert config.SITE["geocoder_url"] == "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"


def test_map_without_ward_shapes_keeps_the_district_lookup(tmp_path):
    """A districts file whose wards are not traced yet: the box and its settings stay district-only."""
    d = json.loads(REAL_DISTRICTS.read_text(encoding="utf-8"))
    d["wards"] = {"status": "coming", "note": "not traced"}
    (tmp_path / "districts.json").write_text(json.dumps(d), encoding="utf-8")
    shutil.copy(REAL_DISTRICTS.parent / "georef.json", tmp_path / "georef.json")
    out = tmp_path / "site"
    build(FIXTURE, out, seats_path=None, districts_path=tmp_path / "districts.json")
    html = (out / "index.html").read_text(encoding="utf-8")
    label = next(n for n in parse(html).walk() if n.tag == "label" and n.attrs.get("for") == "addr-q")
    assert label.all_text() == "Enter your street address to see your county district." and "your city ward" not in html
    assert "only the district number is kept" in html and "City ward lookup is coming" in html
    cfg = addr_config(html)
    assert "ward_margin_m" not in cfg and "wards" not in cfg and len(cfg["districts"]) == 21
    assert "Ward lines:" not in html


def test_landing_draws_no_map_and_names_the_lines_sources(real_map_site):
    """No map on the landing (CEO, 2026-11-10); the lines the lookup checks keep their sources, under the box."""
    html = (real_map_site / "index.html").read_text(encoding="utf-8")
    d = json.loads(REAL_DISTRICTS.read_text(encoding="utf-8"))
    wards = d["wards"]
    for gone in ("<svg", "county-map", "layer-switch", "Map shows", "map.js", "addr-pin", "About this map",
                 'data-ward="'):
        assert gone not in html, gone
    assert '<details class="district-list" id="wards-districts">' in html   # collapsed under the address box
    about = html[html.index('<details class="lookup-about">'):]
    about = about[:about.index("</details>")]
    assert "How the address lookup works" in about
    assert (f'District lines: <a data-ext="map" href="{d["source_url"]}" target="_blank" '
            f'rel="noopener noreferrer">{d["source_title"]}') in about and f'fetched {d["fetched"]}' in about
    assert (f'Ward lines: <a data-ext="map" href="{wards["source_url"]}" target="_blank" '
            f'rel="noopener noreferrer">{wards["source_title"]}') in about and f'fetched {wards["fetched"]}' in about
    assert "Elected Officials List" in about                                # the 19/20 numbering line


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


def _csp(html):
    m = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', html)
    return site_checks.parse_csp(m.group(1).replace("&#39;", "'")) if m else None


def test_landing_csp_allows_only_the_frame_script_and_the_exact_geocoder(real_map_site):
    html = (real_map_site / "index.html").read_text(encoding="utf-8")
    pol = _csp(html)
    assert pol["script-src"] == ["'self'", f"'{views.script_hash(views.geocode_frame_script())}'",
                                 config.SITE["geocoder_url"]]
    assert pol["connect-src"] == ["'none'"] and pol["object-src"] == ["'none'"] and pol["default-src"] == ["'self'"]
    assert pol["frame-src"] == ["'self'"] and pol["form-action"] == ["'self'"] and pol["base-uri"] == ["'none'"]
    other = (real_map_site / "about.html").read_text(encoding="utf-8")
    assert _csp(other)["script-src"] == ["'self'"]                       # only the landing names the geocoder
    assert html.index("Content-Security-Policy") < html.index("<link") < html.index("<script")


def test_frame_script_is_fixed_text_that_cannot_close_its_element():
    js = views.geocode_frame_script()
    assert "</" not in js and "<!--" not in js and "parent.postMessage" in js and 'getAttribute("data-u")' in js
    assert "crGeocode" in js and 'referrerPolicy = "no-referrer"' in js and "delete window.crGeocode" in js
    for banned in ("parent.document", "top.", "localStorage", "cookie", "fetch(", "XMLHttpRequest", "innerHTML"):
        assert banned not in js, banned


def test_no_geocoder_build_draws_no_box_and_names_no_geocoder(tmp_path):
    out = tmp_path / "site"
    build(FIXTURE, out, seats_path=None, districts_path=REAL_DISTRICTS, geocoder=False)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert 'id="addr-form"' not in html and "address.js" not in html and "addr-config" not in html
    assert "Not sure of your district?" in html and "census" not in html.lower()
    assert _csp(html)["script-src"] == ["'self'"]
    pages = {p.relative_to(out).as_posix(): site_checks.parse(p) for p in out.rglob("*.html")}
    assert site_checks.check_external(pages, out, site_checks._site_cfg()) == []


def test_sitegen_cli_has_no_geocoder_option(tmp_path):
    from sitegen.__main__ import main
    out = tmp_path / "site"
    assert main(["--facts", str(FIXTURE), "--out", str(out), "--districts", str(REAL_DISTRICTS), "--no-geocoder"]) == 0
    assert 'id="addr-form"' not in (out / "index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("missing", ["geocoder_label", "geocoder_short", "geocoder_privacy_url"])
def test_geocoder_words_and_privacy_link_are_required(missing):
    cfg = dict(config.SITE)
    cfg[missing] = ""
    assert any(missing in p for p in sitegen_build.site_url_problems(cfg))
    cfg["geocoder_url"] = ""                                               # no geocoder: nothing needed
    assert not sitegen_build.site_url_problems(cfg)


def test_lookup_label_is_required_with_the_lookup_link_and_never_defaulted(monkeypatch, tmp_path):
    cfg = dict(config.SITE, district_lookup_label="")
    assert any("district_lookup_label" in p for p in sitegen_build.site_url_problems(cfg))
    for path in ("sitegen/views.py", "site/templates/index.html.j2", "site/static/address.js"):
        assert "GoVoteTN" not in (ROOT / path).read_text(encoding="utf-8"), path
    monkeypatch.setitem(config.SITE, "district_lookup_label", "")
    with pytest.raises(sitegen_build.BuildError):
        build(FIXTURE, tmp_path / "site", seats_path=None, districts_path=REAL_DISTRICTS)


@pytest.mark.parametrize("edit", [{"geocoder_places": ["A", "B", "C", "D", "E", "F"]},      # more than 5 requests
                                  {"geocoder_places": "Clarksville"}, {"geocoder_places": ["Clark<b>sville"]},
                                  {"geocoder_places": [""]}, {"geocoder_state": ""}, {"geocoder_state": "Tenn"},
                                  {"geocoder_state_name": "Tenn<b>"},
                                  {"geocoder_places": ["Clarksville", "Woodlawn", "clarksville"]}])      # a duplicate
def test_geocoder_places_are_plain_names_at_most_five_with_a_state(edit):
    assert not sitegen_build.site_url_problems(dict(config.SITE))
    assert sitegen_build.site_url_problems(dict(config.SITE, **edit)), edit
    assert not sitegen_build.site_url_problems(dict(config.SITE, geocoder_places=[], geocoder_state=""))   # off


def test_place_names_come_from_config_not_the_script():
    js = (ROOT / "site" / "static" / "address.js").read_text(encoding="utf-8")
    for word in (*config.SITE["geocoder_places"], "Tennessee", '"TN"'):
        assert word not in js, word


TRIES = r"""
const a = require(process.argv[1]);
const inp = JSON.parse(require("fs").readFileSync(0, "utf8"));
const out = {};
for (const t of inp.typed) {
  const l = a.tries(t, inp.places, "TN", "Tennessee");
  out[t] = { list: l, guessed: l.guessed === true };
}
out.capped = a.tries("1 Test St", inp.places.concat(["Extra One", "Extra Two"]), "TN", "Tennessee");
out.noplaces = a.tries("1 Test St", [], "TN", "Tennessee");
out.nostate = a.tries("1 Test St", inp.places, "", "");
out.max = a.MAX_TRIES;
const kinds = ["nomatch", "outside", "district", "near", "ambiguous", "error", "unavailable"];
out.next = kinds.filter(k => a.tryNext({ kind: k }));
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node not available")
def test_bare_street_is_tried_with_each_county_place_and_a_full_address_as_typed():
    places = config.SITE["geocoder_places"]
    typed = ["2861 McManus Circle", "2861 McManus Circle, Clarksville TN", "2861 McManus Circle 37042",
             "1 Main St, Clarksville, Tennessee", "1 Main St tn", "10000 Main St", "1 Main St Woodlawn",
             "100 Woodlawn Rd", "1 Main St 37042-1234", "1 Main St, Clarksville, TN 37042", "1234 TN-48",
             "100 Tennessee Ave", "100 Main St Apt 12345", "2861 McManus Circle, Clarksville", "100 Main St, Nashville"]
    res = subprocess.run(["node", "-e", TRIES, str(ROOT / "site" / "static" / "address.js")],
                         input=json.dumps({"typed": typed, "places": places}), capture_output=True, text=True,
                         timeout=60)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    lists = {t: out[t]["list"] for t in typed}

    def guesses(t):
        return [f"{t}, {p}, TN" for p in places]
    for t in ("2861 McManus Circle", "10000 Main St", "100 Woodlawn Rd",   # a 5-digit house number is not a ZIP
              "1234 TN-48", "100 Tennessee Ave", "100 Main St Apt 12345"):   # only the end names a state or ZIP
        assert lists[t] == guesses(t) and out[t]["guessed"], t           # each county place in turn, Clarksville first
    for t in ("2861 McManus Circle, Clarksville TN", "2861 McManus Circle 37042", "1 Main St, Clarksville, Tennessee",
              "1 Main St tn", "1 Main St 37042-1234", "1 Main St, Clarksville, TN 37042"):
        assert lists[t] == [t] and not out[t]["guessed"], t              # a state or ZIP: sent once, as typed
    # a place the visitor typed (listed or not): the state added, once, and no guess
    for t in ("1 Main St Woodlawn", "2861 McManus Circle, Clarksville", "100 Main St, Nashville"):
        assert lists[t] == [f"{t}, TN"] and not out[t]["guessed"], t
    assert out["max"] == 5 == sitegen_build.GEOCODER_MAX_PLACES and len(out["capped"]) == 5   # the retry cap
    assert out["noplaces"] == ["1 Test St"] and out["nostate"] == ["1 Test St"]
    assert out["next"] == ["nomatch", "outside"]     # an out-of-county match is a wrong guess: try the next place


def test_privacy_url_must_be_https():
    assert sitegen_build.site_url_problems(dict(config.SITE, geocoder_privacy_url="http://www.census.gov/p"))


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
                "https://geocoding.geo.census.gov/x#a", "javascript:alert(1)", "https://geo.example/x;script-src *",
                "https://geo.example/x 'unsafe-inline'", "https://geo.example/x,y", "https://geo.example/x'"):
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
    pages["index.html"] = site_checks.parse(idx)
    assert site_checks.check_external(pages, site, cfg)


def _site_copy(src, dst):
    shutil.copytree(src, dst)
    return {p.relative_to(dst).as_posix(): site_checks.parse(p) for p in dst.rglob("*.html")}


def test_site_checks_fail_address_js_without_its_settings_block(real_map_site, tmp_path):
    """qa-guard/addr-config-silent-miss: a page that loads address.js must carry addr-config, found by parsing (any
    attribute order), not by a regex on one spelling."""
    cfg = site_checks._site_cfg()
    site = tmp_path / "a"
    _site_copy(real_map_site, site)
    idx = site / "index.html"
    html = idx.read_text(encoding="utf-8")
    swapped = html.replace('<script type="application/json" id="addr-config">',
                           '<script id="addr-config" type="application/json">')
    assert swapped != html
    idx.write_text(swapped, encoding="utf-8")
    pages = {p.relative_to(site).as_posix(): site_checks.parse(p) for p in site.rglob("*.html")}
    assert site_checks.check_external(pages, site, cfg) == []              # attribute order does not matter
    idx.write_text(re.sub(r'<script id="addr-config"[^>]*>.*?</script>', "", swapped, flags=re.S), encoding="utf-8")
    pages["index.html"] = site_checks.parse(idx)
    assert any("without its addr-config" in p for p in site_checks.check_external(pages, site, cfg))
    about = site / "about.html"                                            # any page, not only the landing
    about.write_text(about.read_text(encoding="utf-8").replace("</body>",
                                                               '<script src="static/address.js"></script></body>'),
                     encoding="utf-8")
    pages["about.html"] = site_checks.parse(about)
    assert any(p.startswith("about.html: loads static/address.js") for p in site_checks.check_external(pages, site, cfg))


@pytest.mark.parametrize("edit", ["drop", "geocoder-other", "hash-other", "wild", "connect",
                                  "frame-src", "img-src", "form-action", "frame-src-gone"])
def test_site_checks_hold_every_page_to_the_csp(real_map_site, tmp_path, edit):
    cfg = site_checks._site_cfg()
    site = tmp_path / "c"
    _site_copy(real_map_site, site)
    on_about = ("drop", "wild", "connect", "frame-src", "img-src", "form-action", "frame-src-gone")
    target = site / ("about.html" if edit in on_about else "index.html")
    html = target.read_text(encoding="utf-8")
    if edit == "drop":
        new = re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>', "", html)
    elif edit == "geocoder-other":
        new = html.replace("&#39;sha256-", "https://evil.example &#39;sha256-")
        new = new.replace(" https://geocoding.geo.census.gov/geocoder/locations/onelineaddress;", ";")
    elif edit == "hash-other":
        new = re.sub(r"&#39;sha256-[A-Za-z0-9+/]{43}=&#39;", "&#39;sha256-" + "A" * 43 + "=&#39;", html)
    elif edit == "wild":
        new = html.replace("script-src &#39;self&#39;;", "script-src &#39;self&#39; https:;")
    elif edit == "frame-src":
        new = html.replace("frame-src &#39;self&#39;", "frame-src &#39;self&#39; https://evil.example")
    elif edit == "img-src":
        new = html.replace("img-src &#39;self&#39; data:", "img-src &#39;self&#39;")
    elif edit == "form-action":
        new = html.replace("form-action &#39;self&#39;", "form-action https:")
    elif edit == "frame-src-gone":
        new = html.replace("frame-src &#39;self&#39;", "")
    else:
        new = html.replace("connect-src &#39;none&#39;", "connect-src *")
    assert new != html, edit
    target.write_text(new, encoding="utf-8")
    pages = {p.relative_to(site).as_posix(): site_checks.parse(p) for p in site.rglob("*.html")}
    assert site_checks.check_external(pages, site, cfg), edit


def test_privacy_link_is_an_allowed_external_link():
    cfg = site_checks._site_cfg()
    assert cfg["geocoder_privacy_url"] in site_checks.allowed_external(cfg, None, None)
    assert "geocoder" in site_checks.EXT_KINDS
    assert cfg["geocoder_privacy_url"] not in site_checks.allowed_external(dict(cfg, geocoder_url=""), None, None)


def _browser_ok():
    if not shutil.which("node"):
        return False
    return os.path.exists("/opt/pw-browsers") or bool(shutil.which("playwright"))


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_address_box_in_a_browser(real_site, tmp_path):
    pts = {k: next(p["lonlat"] for p in G["check_points"] if p["id"] == pid)
           for k, pid in (("district", "franklin-2nd"), ("near", "hwy48-loneoak"))}
    pts["outside"] = [-87.44, 36.665]
    pts["other"] = next(p["lonlat"] for p in G["check_points"] if p["id"] == "rossview-wilma")   # District 14
    # the ward lookup (tests/test_ward_map.py): on the ward 6 / 7 line in District 4, and District 6 outside the city
    pts["wardnear"] = next(p["lonlat"] for p in WG["control_points"] if p["id"] == "ashlandcity-sevenmileferry")
    pts["outsidecity"] = next(p["lonlat"] for p in G["check_points"] if p["id"] == "slayden-hwy13")
    for k, d in (("wardnear", 4), ("outsidecity", 6)):
        got = georef.district_for(*pts[k])
        assert got["district"] == d and not got["near_boundary"], k
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
        assert m["formShown"] and m["scrollWidth"] <= m["innerWidth"], (vp, m)
        assert m["svgs"] == 0, (vp, m)                                   # no map (CEO, 2026-11-10)
        if vp.endswith("answered"):     # privacy line + answer shown: the answer is on the first screen
            assert m["resultBottom"] <= m["innerHeight"], (vp, m)
        else:   # before any lookup the welcome h1, the unofficial line and the address input with its Find button are on
            #     the first screen (front-page-v2: doors and meetings follow below, so the whole landing no longer fits)
            for key in ("h1Bottom", "introBottom", "inputBottom", "findBottom"):
                assert 0 < m[key] <= m["innerHeight"], (vp, key, m)
    assert set(out["fit"]) == {"375x667", "1280x800", "375x667 answered", "1280x800 answered"}
    rv = out["revealed"]     # 320x568, right after the lookup: the whole answer is in view (address.js reveal())
    assert rv["innerHeight"] == 568 and 0 <= rv["resultTop"] < rv["resultBottom"] <= rv["innerHeight"], rv
    c = out["cases"]
    census = "The Census places this address in "
    both = census + "District 5 and Ward 6."                 # the combined lookup: the real map holds the wards
    assert c["district"]["text"].startswith(both) and c["district"]["href"] == "districts/05.html"
    assert c["district"]["hrefs"][1].endswith("#seat-ward-6")             # the ward's seat on the council page
    assert "Census match: 1 TEST ST" in c["district"]["text"]
    assert c["twosame"]["text"].startswith(both)
    assert c["reachout"]["text"].startswith(both) and not c["reachout"]["pwned"]
    assert c["near"]["text"].startswith("This address is near a district line. Check GoVoteTN to be sure. "
                                        "It is outside the City of Clarksville wards on the Regional Planning "
                                        "Commission's map of 2026-02-25.")
    assert c["near"]["href"] == config.SITE["district_lookup_url"]
    assert c["wardnear"]["text"].startswith(census + "District 4. It is near a ward line. Check with the Election "
                                            "Commission or look it up on GoVoteTN to be sure.")
    assert c["wardnear"]["hrefs"] == ["districts/04.html", config.SITE["district_lookup_url"]]
    assert c["outsidecity"]["text"].startswith(census + "District 6. It is outside the City of Clarksville wards on the "
                                          "Regional Planning Commission's map of 2026-02-25. Annexations since then are "
                                          "not on it. Check with the Election Commission or look it up on GoVoteTN.")
    assert c["outsidecity"]["hrefs"] == ["districts/06.html", config.SITE["district_lookup_url"]]
    assert c["outside"]["text"].startswith("This address is outside Montgomery County.")
    assert c["spoof"]["text"].startswith("This address is outside Montgomery County.")   # the page's own message ignored
    ambiguous = "More than one address matched. Add the city and ZIP, or check GoVoteTN."
    for k in ("ambiguous", "ambiguousnear"):
        assert c[k]["text"] == ambiguous and c[k]["href"] == config.SITE["district_lookup_url"], k
    assert c["nomatch"]["text"].startswith("No match was found for that address.") and c["nomatch"]["href"]
    for k in ("badshape", "nocallback"):
        assert c[k]["text"] == "The address lookup did not answer. Look it up on GoVoteTN.", k
    for k in ("blocked", "servererror"):
        assert c[k]["text"] == "Address lookup isn't available here. Look it up on GoVoteTN.", k
    for k, v in c.items():
        assert v["typedRequests"] == 0 and len(v["requests"]) == 1, k        # nothing sent until submit, once
        q = v["requests"][0]
        assert q == ("?address=1%20Test%20St%20%3Cb%3E%26%22%2C%20Clarksville%20TN&benchmark=Public_AR_Current"
                     "&format=jsonp&callback=crGeocode"), q
        # the address is never stored; only the found district and ward numbers, under the one key (the reachout's
        # own write failed); a seat the lookup could not place is stored as null, never guessed
        seats = {"district": {"district": 5, "ward": 6}, "twosame": {"district": 5, "ward": 6},
                 "reachout": {"district": 5, "ward": 6}, "wardnear": {"district": 4, "ward": None},
                 "outsidecity": {"district": 6, "ward": None}}
        want = ["cr-your-seats"] if k in seats else []
        assert v["storage"] == want and v["scripts"] == 0 and v["frames"] == 0 and v["svgs"] == 0, k
        if want:
            assert v["seats"] == seats[k], k
            assert "Test St" not in v["storageText"], k
        assert "<b>" not in v["html"], k                                      # census text is never markup
        assert v["frame"] == [{"sandbox": "allow-scripts", "referrerpolicy": "no-referrer", "hidden": True,
                               "src": None, "srcdoc": v["frame"][0]["srcdoc"]}], k   # one opaque-origin iframe
        assert v["frame"][0]["srcdoc"].startswith('<!doctype html><meta charset="utf-8"><meta name="referrer" '
                                                  'content="no-referrer"><script data-u="https://geocoding.'), k
        assert v["csp"] == [] and v["refused"] == [], (k, v["csp"], v["refused"])   # nothing blocked by the CSP
    # address-lookup-bare-street: a street typed with no state or ZIP is tried with each county place, in order, one
    # request at a time (one iframe at each request), at most 5, stopping at the first match inside the county
    b = out["bare"]
    places = config.SITE["geocoder_places"]
    assert b["bare"]["requests"] == ["2861 McManus Circle, Clarksville, TN"]
    assert b["bare"]["text"].startswith(both) and "Census match: 1 TEST ST" in b["bare"]["text"]
    assert b["bare"]["seats"] == {"district": 5, "ward": 6} and "McManus" not in b["bare"]["storageText"]
    assert b["outofcounty"]["requests"] == ["100 Test Rd, Clarksville, TN", "100 Test Rd, Woodlawn, TN"]
    assert b["outofcounty"]["text"].startswith(both)                     # the out-of-county Clarksville match rejected
    assert b["cap"]["requests"] == [f"1 Nowhere Ln, {p}, TN" for p in places] and len(places) == 5   # the cap
    assert b["cap"]["text"] == ("No match was found for that address in Montgomery County. Check the spelling, or add "
                                "the city and ZIP, or look it up on GoVoteTN.")
    assert b["cap"]["hrefs"] == [config.SITE["district_lookup_url"]] and b["cap"]["seats"] is None
    assert b["blocked"]["requests"] == ["2861 McManus Circle, Clarksville, TN"]       # a dead geocoder: no more tries
    assert b["blocked"]["text"] == "Address lookup isn't available here. Look it up on GoVoteTN."
    full = "2861 McManus Circle, Clarksville, TN 37042"
    assert b["full"]["requests"] == [full]                               # a full address: once, as typed (not retried)
    assert b["full"]["text"].startswith("No match was found for that address. Check the spelling, or look it up")
    assert b["fulloutside"]["requests"] == ["1 Test St, Oak Grove, KY 42262"]
    assert b["fulloutside"]["text"].startswith("This address is outside Montgomery County.")
    assert b["owntown"]["requests"] == ["1 Test St, Nashville, TN"]      # the visitor's own town: once, and no guess
    assert b["owntown"]["text"].startswith("This address is outside Montgomery County.")
    # a new submit while places are still being tried: the old lookup stops, only the new one's answer shows
    assert b["resubmit"]["requests"] == ["1 Nowhere Ln, Clarksville, TN", "1 Nowhere Ln, Woodlawn, TN", full]
    assert b["resubmit"]["text"].startswith(both)
    for k, v in b.items():
        assert v["framesAtRequest"] == [1] * len(v["requests"]), k       # sequential: never two requests at once
        assert v["frames"] == 0 and not v["busy"] and not v["disabled"], k
        assert v["csp"] == [] and v["refused"] == [], (k, v["csp"], v["refused"])
        assert v["placeholder"] == "Street address, like 100 Main St", k
        assert v["privacy"].startswith("Your address is sent to the U.S. Census Bureau's geocoder to find where it is. "
                                       "This site doesn't store it."), k
