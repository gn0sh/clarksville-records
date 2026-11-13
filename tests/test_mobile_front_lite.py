# ruff: noqa: E501
"""The front page on a phone, lighter (mobile-front-lite, 2026-11-13; docs/design/front-page-v2.md "Phone"). Under
600px the landing shows a one-sentence lede, a shorter address label and privacy line, the meetings before the "Start
here" doors, the doors without their sentence, and the public bodies behind one line. Nothing leaves the page: the wide
wording, every "Coming" note, the unofficial line, the header tag and the footer notice are all still there, and a
screen of 600px or more looks as it did.

Builds the county fixture with the city and RPC fixtures (as tests/test_body_switch.py), on the real traced map so
the address box is on the page (as tests/test_address_box.py)."""
import json
import os
import re
import shutil
import subprocess
from datetime import date

import pytest

from conftest import FIXTURE, ROOT, at_width, parse
from qa import site_checks
from sitegen import config
from sitegen.build import build
from test_council_pages import cfg, city_facts, city_wards  # noqa: F401  (module fixtures)
from test_rpc_pages import rpc_cfg  # noqa: F401  (module fixture)

TODAY = date(2024, 12, 1)     # tests/test_days.py: the day window then holds two county fixture meetings
CSS = (ROOT / "site" / "static" / "style.css").read_text(encoding="utf-8")
LANDING_JS = ROOT / "site" / "static" / "landing.js"
PHONE_PRIVACY = "Sent to the U.S. Census Bureau's geocoder. This site doesn't store it. Census's privacy policy"
WIDE_PRIVACY = ("Your address is sent to the U.S. Census Bureau's geocoder to find where it is. This site doesn't store "
                "it. Census's privacy policy applies. Or look it up on GoVoteTN.")
FOOT = ("Only meetings in these records are listed: a meeting appears once its body posts an agenda or lists a date. "
        "Each body's own calendar is the official schedule. What is and is not collected")


@pytest.fixture(scope="module")
def site(tmp_path_factory, cfg, rpc_cfg):  # noqa: F811
    out = tmp_path_factory.mktemp("phone") / "build" / "site"
    build(FIXTURE, out, seats_path=None, districts_path=config.DISTRICTS_PATH, councils=[cfg], rpc=rpc_cfg, today=TODAY)
    return out


@pytest.fixture(scope="module")
def html(site):
    return (site / "index.html").read_text(encoding="utf-8")


def text_of(html, pred):
    node = next(n for n in parse(html).walk() if pred(n))
    return " ".join(node.all_text().split())


def phone_block():
    """The body of the landing's phone media query in style.css (comments removed)."""
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    start = css.index("@media (max-width: 599px) {\n  .phone-only { display: inline; }")
    return css[start:css.index("\n}\n", start)]


def test_each_width_reads_one_wording(html):
    phone, wide = at_width(html, phone=True), at_width(html, phone=False)
    lede = lambda n: n.tag == "p" and n.attrs.get("class") == "lede"  # noqa: E731
    assert text_of(phone, lede) == config.SITE["welcome_lede_phone"] == "Every fact links to its official document."
    assert text_of(wide, lede).startswith("See who represents you, how they voted")
    assert text_of(wide, lede).endswith("Every fact links to the official document it came from.")
    label = lambda n: n.tag == "label" and n.attrs.get("for") == "addr-q"  # noqa: E731
    assert text_of(phone, label) == "Enter your street address."
    assert text_of(wide, label) == "Enter your street address to see your city ward and county district."
    privacy = lambda n: n.attrs.get("id") == "addr-privacy"  # noqa: E731
    assert text_of(wide, privacy) == WIDE_PRIVACY
    # the phone line keeps both facts and the link; `.addr-alt` (the official lookup) is hidden there by the stylesheet
    assert text_of(phone, privacy) == PHONE_PRIVACY + " Or look it up on GoVoteTN."
    sub = lambda n: n.tag == "p" and n.attrs.get("class") == "sec-sub" and n.parent.attrs.get("id") == "meetings"  # noqa: E731
    assert text_of(phone, sub) == "As of December 1, 2024."
    assert text_of(wide, sub) == "As of December 1, 2024. Tap a meeting for its agenda, minutes and votes."
    foot = lambda n: n.attrs.get("class") == "meet-foot"  # noqa: E731
    assert text_of(phone, foot) == "What is and is not collected" and text_of(wide, foot) == FOOT
    assert '<a href="today.html#day-bodies-h">What is and is not collected</a>' in html


def test_nothing_is_taken_out_of_the_page(html):
    """The phone layout hides with the stylesheet only: the page a wide screen, a reader without CSS and the checks
    read still holds the door sentences, every body's card and its "Coming" line, and the unofficial line."""
    doors = html.count('<li class="door ')       # three in this build (no finance pages, so no "Public money")
    assert doors == 3 and len(re.findall(r'<li class="door [^>]*>\s*<h3>[^<]+</h3>\s*<p>[^<]+</p>', html)) == doors
    sec = re.search(r'<section class="bodies".*?</section>', html, re.S).group(0)
    assert '<details class="bodies-fold" id="bodies-fold" open>' in sec           # built open: no script, no fold
    assert f'<summary>{config.SITE["switch"]["overview"]["fold"]}</summary>' in sec
    assert sec.index('id="bodies-h"') < sec.index("<details") < sec.index("<summary>") < sec.index('class="bodies-list"') < sec.index("</details>")
    assert len(re.findall(r'<li class="bodies-card"', sec)) == 4 and sec.count('class="bodies-coming"') >= 3
    assert 'class="unofficial-intro" id="unofficial-short"' in html and '<p class="unofficial-tag">' in html


def test_the_phone_rules_are_all_inside_the_phone_query():
    """A screen of 600px or more keeps its look: outside the media query there are only the two wording classes and
    the fold's hidden summary."""
    block = phone_block()
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    outside = css.replace(block, "")
    assert re.search(r"^\.phone-only \{ display: none; \}$", outside, re.M)
    assert re.search(r"^\.bodies-fold > summary \{ display: none; \}", outside, re.M)
    assert ".phone-off" not in outside
    for rule in (".phone-off { display: none; }", ".door p:not(.door-coming) { display: none; }", ".addr-alt { display: none; }",
                 ".landing > .welcome, .landing > .find, .landing > .meetings { order: -1; }",
                 ".bodies-fold > summary { display: list-item;"):
        assert rule in block and rule not in outside, rule
    # and nothing in it names the notice, the tag or the footer (qa/site_checks.py check_unofficial reads the same)
    assert "unofficial" not in block and "footer" not in block


def test_the_checks_still_see_the_notice(site):
    pages = {p.relative_to(site).as_posix(): site_checks.parse(p) for p in [site / "index.html"]}
    problems, _ = site_checks.check_unofficial(site, pages)
    assert not [x for x in problems if x.startswith(("index.html", "static/style.css"))], problems


def _node():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    return shutil.which("node")


def test_fold_closes_on_a_phone_and_opens_again_when_the_window_grows():
    probe = ("const L = require(process.argv[1]); const d = { open: true }; let grow;"
             "global.document = { getElementById: (id) => (id === 'bodies-fold' ? d : null) };"
             "const mq = (m) => ({ matches: m, addEventListener: (t, f) => { grow = f; } });"
             "const out = [L.PHONE];"
             "L.fold(mq(true)); out.push(d.open); grow({ matches: true }); out.push(d.open);"
             "grow({ matches: false }); out.push(d.open);"
             "d.open = true; L.fold(mq(false)); out.push(d.open);"
             "console.log(JSON.stringify(out))")
    res = subprocess.run([_node(), "-e", probe, str(LANDING_JS)], capture_output=True, text=True, check=True)
    assert json.loads(res.stdout) == ["(max-width: 599px)", False, False, True, True]
    assert "@media (max-width: 599px) {\n  .phone-only" in CSS                  # the script and the stylesheet agree


def _browser_ok():
    return bool(shutil.which("node")) and (os.path.exists("/opt/pw-browsers") or bool(shutil.which("playwright")))


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_phone_and_wide_in_a_browser(site):
    env = dict(os.environ)
    if "NODE_PATH" not in env:
        env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    res = subprocess.run(["node", str(ROOT / "tests" / "mobile_front_browser.js"), str(site / "index.html")],
                         capture_output=True, text=True, timeout=300, env=env)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert set(out) == {"phone", "opened", "turned", "phone-noscript", "wide"}
    for name, m in out.items():
        assert m["scrollWidth"] <= m["innerWidth"], (name, m)                   # the page never scrolls sideways
        assert m["tag"] and m["intro"] and m["notice"], (name, m)               # unofficial: tag, short line, footer
        assert m["doors"] == m["doorTitles"] == 3 and len(m["doorLinks"]) >= 3, (name, m)
        assert min(m["doorLinks"]) >= 44 and m["moreLink"] >= 44, (name, m)     # tap targets
        assert m["searchName"] == "Search by street, name, topic or item number.", (name, m)

    p = out["phone"]
    assert p["lede"] == "Every fact links to its official document."
    assert p["label"] == "Enter your street address." and p["privacy"] == PHONE_PRIVACY
    assert p["privacyLink"] and p["listLink"]
    assert p["meetSub"] == "As of December 1, 2024." and p["meetFoot"] == "What is and is not collected"
    assert p["footLink"] >= 44 and p["summaryHeight"] >= 44
    t = p["tops"]
    assert t["find"] < t["meetings"] < t["doors"] < t["bodies"] < t["search"], t    # the meetings come before the doors
    assert p["doorTexts"] == 0                                                   # titles and links only
    assert p["summary"] and p["foldOpen"] is False and p["cards"] == 0 and p["coming"] == 0
    assert p["searchLabel"] <= 1                                                 # read out, not shown

    o = out["opened"]                                                            # one tap: every body and its Coming line
    assert o["foldOpen"] is True and o["cards"] == 4 and o["coming"] >= 3

    n = out["phone-noscript"]                                                    # no script: the list is simply open
    assert n["summary"] and n["foldOpen"] is True and n["cards"] == 4 and n["coming"] >= 3
    assert n["lede"] == p["lede"] and n["doorTexts"] == 0 and n["tops"]["meetings"] < n["tops"]["doors"]

    for name in ("wide", "turned"):                                              # 600px and wider: as it was
        w = out[name]
        assert w["lede"].startswith("See who represents you") and w["lede"].endswith("the official document it came from.")
        assert w["label"] == "Enter your street address to see your city ward and county district."
        assert w["privacy"] == WIDE_PRIVACY and w["meetFoot"] == FOOT
        assert w["meetSub"] == "As of December 1, 2024. Tap a meeting for its agenda, minutes and votes."
        t = w["tops"]
        assert t["find"] < t["doors"] < t["bodies"] < t["meetings"] < t["search"], (name, t)
        assert w["doorTexts"] == 3 and w["searchLabel"] > 1
        assert w["summary"] is False and w["foldOpen"] is True and w["cards"] == 4 and w["coming"] >= 3, (name, w)
