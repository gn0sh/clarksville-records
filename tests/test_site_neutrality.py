"""F5: neutrality (AC1.5, template lint). N1: same layout for every official."""
import copy
import re

import pytest

from conftest import ROOT, parse
from sitegen import views

BANNED = re.compile(r"\b(rank|score|grade|missed|percent|best|worst)|%", re.IGNORECASE)
COUNT_WORDS = re.compile(r"count|total|num|len|size|absent|present|yes|no\b|vote|n_", re.IGNORECASE)


def normalise_totals(s: str) -> str:
    """Numbers to N, and singular forms to plural: only grammatical number may vary with a count."""
    s = re.sub(r"\d+", "N", s)
    return (s.replace("roll call in", "roll calls in").replace("N roll call not", "N roll calls not").replace("meeting in", "meetings in")
            .replace("N vote in", "N votes in")
            .replace(" is not shown because it is ", " are not shown because they are ")
            .replace("period is ", "period are ").replace("period has ", "period have ")
            .replace("and is not", "and are not").replace("roll call under review is", "roll calls under review are"))


def skeleton(html: str) -> list:
    """Tag names, ids, heading and column-header text, in order. Row data and the contents of the year list are
    data, so tbody contents and year options are skipped."""
    out = []

    def visit(n, skip):
        for c in n.children:
            if skip:
                continue
            tag = c.tag
            out.append((tag, c.attrs.get("id", ""), c.attrs.get("class", "")))
            if tag in ("h2", "h3", "th"):
                out.append(("text", c.all_text().strip()))
            if tag == "tbody":
                continue
            if tag == "select" and c.attrs.get("id") == "filter-year":
                out.append(("options-skipped",))
                continue
            visit(c, False)

    visit(parse(html), False)
    return out


def test_official_pages_have_identical_skeleton(pages, facts):
    ids = [o["id"] for o in facts["officials"]]
    assert len(ids) >= 2
    base = skeleton(pages[f"officials/{ids[0]}.html"])
    for oid in ids[1:]:
        assert skeleton(pages[f"officials/{oid}.html"]) == base, oid


def test_official_with_no_data_has_same_skeleton(pages, facts):
    """Every section renders even when empty (a fixed sentence, never missing)."""
    lonely = copy.deepcopy(facts)
    lonely["officials"].append(
        {"id": "z-nobody", "name": "Z. Nobody", "surname": "Nobody", "given": "Z.", "title": "Commissioner", "aliases": []})
    from conftest import FIXTURE_SEATS
    from sitegen.seats import load_rows
    ix = views.Index(lonely, load_rows(FIXTURE_SEATS))  # the session build has the fixture roster
    from sitegen.build import make_env
    site = dict(views.site_context(ix), internal=True)  # the session-built pages are internal builds
    html = make_env().get_template("official.html.j2").render(
        site=site, root="../", page_name="x", report_page=True,
            official_record=views.official_record("official.html.j2", site, {}), **views.official("z-nobody", ix))
    assert "No votes, attendance, motions or seconds are shown" in html
    assert skeleton(html) == skeleton(pages["officials/a-example.html"])


def test_totals_wording_is_fixed(pages, facts):
    texts = set()
    for o in facts["officials"]:
        t = views.totals_sentences(views.Index(facts), o["id"])
        assert len(t) == 5
        norm = [normalise_totals(s) for s in t]
        texts.add(tuple(norm))
    assert len(texts) == 1


def _template_text(path):
    raw = path.read_text(encoding="utf-8")
    raw = re.sub(r"\{#.*?#\}", "", raw, flags=re.S)  # Jinja comments
    raw = re.sub(r"\{%.*?%\}", "", raw, flags=re.S)  # Jinja statements (their delimiters contain the percent sign)
    return raw


TEMPLATES = sorted((ROOT / "site" / "templates").glob("*.j2"))


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_template_has_no_banned_words(path):
    m = BANNED.search(_template_text(path))
    assert m is None, f"{path.name}: banned term {m.group(0)!r}"


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_template_never_sorts_by_a_count(path):
    raw = path.read_text(encoding="utf-8")
    for m in re.finditer(r"\bsort\b|\bdictsort\b|\bgroupby\b", raw):
        # Templates do not sort at all; ordering is decided once, in views.py, by name or date.
        pytest.fail(f"{path.name}: template sorts ({raw[m.start():m.start() + 40]!r}); sort in views.py by name or date")


def test_views_sort_keys_are_not_counts():
    src = (ROOT / "sitegen" / "views.py").read_text(encoding="utf-8")
    for m in re.finditer(r"sort\(key=([^\n]*)|sorted\([^\n]*key=([^\n]*)", src):
        key = m.group(1) or m.group(2)
        assert not re.search(r"\blen\(|count|total", key), key
