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


@pytest.fixture(scope="session")
def facts():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    """The fixture site, built once with --internal so review.html exists."""
    out = tmp_path_factory.mktemp("site") / "build" / "site"
    build(FIXTURE, out, internal=True)
    return out


@pytest.fixture(scope="session")
def pages(built):
    return {p.relative_to(built).as_posix(): p.read_text(encoding="utf-8") for p in built.rglob("*.html")}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.children, self.text = tag, dict(attrs), parent, [], []

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def all_text(self):
        return "".join(self.text) + "".join(c.all_text() for c in self.children)


VOID = {"meta", "link", "br", "img", "input", "hr"}


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.cur)
        self.cur.children.append(n)
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


def parse(html: str) -> Node:
    t = _Tree()
    t.feed(html)
    return t.root
