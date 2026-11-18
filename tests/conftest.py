import json
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sitegen.build import build  # noqa: E402

FIXTURE = ROOT / "site" / "fixtures" / "facts.sample.json"
FIXTURE_SEATS = ROOT / "site" / "fixtures" / "seats.sample.yml"
FIXTURE_DISTRICTS = ROOT / "site" / "fixtures" / "districts.sample.json"


def note_off(cfg: dict) -> dict:
    """A copy of `cfg` with the morning note switched off, as config/site.yml shipped it before the switch-on PR:
    no sign-up form (enabled false, no provider, form_action or privacy_url), the sender off and no alerts.site_url
    (feeds carry relative links). Tests of the off state and of the relative feed links build from this, so they
    hold whatever the repository ships; the shipped switches are pinned by
    test_morning_page.test_committed_config_is_the_switch_on."""
    import copy
    c = copy.deepcopy(cfg)
    if "alerts" in c:
        c["alerts"]["site_url"] = ""
    mn = c.get("morning_note")
    if mn:
        mn.update(enabled=False, provider="", form_action="", privacy_url="")
        if "sender" in mn:
            mn["sender"]["enabled"] = False
    return c


def shipped_with(tmp_path, enabled=None, canary_only=None, mode=None, hosts="") -> Path:
    """The shipped config/site.yml with the sender block's one-line switches set as asked, written to `tmp_path`
    (the shipped file is unchanged), so a test of the off state, or of canary_only, does not depend on what the
    repository ships today (test_morning_page.test_committed_config_is_the_switch_on pins that)."""
    import re
    text = (ROOT / "config" / "site.yml").read_text(encoding="utf-8")
    for key, value in (("enabled", enabled), ("canary_only", canary_only)):
        if value is not None:
            text, n = re.subn(rf"(?m)^(    {key}: )(?:true|false)\b", rf"\g<1>{'true' if value else 'false'}", text,
                              count=1)
            assert n == 1, key
    if mode is not None:
        text, n = re.subn(r"(?m)^(    mode: )(?:all|stamp|ids)\b", rf"\g<1>{mode}", text, count=1)
        assert n == 1
    if hosts:
        text, n = re.subn(r'(?m)^(    link_hosts: ")', rf"\g<1>{hosts},", text, count=1)
        assert n == 1
    out = tmp_path / "site.yml"
    out.write_text(text, encoding="utf-8")
    return out


def rpc_config_unheld(locality: str = "cmc-rpc") -> dict:
    """The RPC's rpc.yml (sitegen.rpc.load_config) with `hold_motions` off: the tests of the reader's rules on fixture
    motions. The hold itself, as shipped, is tested in tests/test_rpc_hold.py."""
    from sitegen import rpc
    return {**rpc.load_config(locality), "hold_motions": False}


@pytest.fixture(scope="session")
def facts():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    """The fixture site, built once with --internal so review.html exists, with the fixture roster and map."""
    out = tmp_path_factory.mktemp("site") / "build" / "site"
    build(FIXTURE, out, internal=True, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS)
    return out


@pytest.fixture(scope="session")
def pages(built):
    return {p.relative_to(built).as_posix(): p.read_text(encoding="utf-8") for p in built.rglob("*.html")}


def at_width(html: str, phone: bool) -> str:
    """The landing's markup as one width shows it (static/style.css, under 600px): a `.phone-only` span is not shown on
    a wide screen and a `.phone-off` span is not shown on a phone. Each holds text only."""
    import re
    gone = "phone-off" if phone else "phone-only"
    return re.sub(rf'<span class="{gone}">[^<]*</span>', "", html)


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.children, self.text = tag, dict(attrs), parent, [], []
        self.parts = []  # text and child nodes in document order

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def all_text(self):
        """Text of this element and everything inside it, in document order."""
        return "".join(p if isinstance(p, str) else p.all_text() for p in self.parts)


VOID = {"meta", "link", "br", "img", "input", "hr"}


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.cur)
        self.cur.children.append(n)
        self.cur.parts.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.text.append(data)
        self.cur.parts.append(data)


def parse(html: str) -> Node:
    t = _Tree()
    t.feed(html)
    return t.root
