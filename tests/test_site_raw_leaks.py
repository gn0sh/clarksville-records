"""leak-path/raw-name-fallback, partial resolution and leak-path/data-downloads: raw OCR text reaches no public page
or data file. Raw fields live only in internal builds (review.html, --internal exports)."""
import copy
import json
import re
from html import unescape
from pathlib import Path

import pytest

from collector.export import export
from sitegen.build import build
from conftest import parse
from test_site_review_fixes import (MEETING_DEC, MO_SHOWN, RC_SHOWN, build_pages, by_id, public, unverify)


EV_SHOWN = "ev-314626e6-p9-2"  # the item-page event for MO_SHOWN


def _block(pages, page, fact_id):
    key = "data-fact-id" if page.startswith("items/") else "id"
    fact_id = EV_SHOWN if page.startswith("items/") else fact_id
    return " ".join(next(n for n in parse(pages[page]).walk() if n.attrs.get(key) == fact_id).all_text().split())


def _official_line(pages):
    row = next(n for n in parse(pages["officials/a-example.html"]).walk()
               if n.attrs.get("data-fact-id") == f"{RC_SHOWN}/a-example")
    return " ".join(row.all_text().split())


def _with_motion(facts, **refs):
    f = copy.deepcopy(facts)
    mo = by_id(f, "motions", MO_SHOWN)
    mo.update(refs)
    return f, mo


def test_partial_resolution_shows_only_resolved_name_everywhere(tmp_path, facts):
    f, _ = _with_motion(facts, moved_by={"official_id": None, "raw_name": "Qqraw Mover"})
    pages = build_pages(tmp_path, f)
    for page in (f"meetings/{MEETING_DEC}.html", "items/2024.html"):
        text = _block(pages, page, MO_SHOWN)
        assert "Seconded by" in text and "A. Example" in text and "Moved by" not in text, page
    line = _official_line(pages)
    assert "Seconded by" in line and "A. Example" in line and "Moved by" not in line
    for name, html in public(pages).items():
        assert "Qqraw" not in html, name


def test_unresolved_official_id_both_roles_is_under_review(tmp_path, facts):
    f, _ = _with_motion(facts, moved_by={"official_id": None, "raw_name": "Qqraw One"},
                        seconded_by={"official_id": None, "raw_name": "Qqraw Two"})
    pages = build_pages(tmp_path, f)
    for page in (f"meetings/{MEETING_DEC}.html", "items/2024.html"):
        text = _block(pages, page, MO_SHOWN)
        assert "Attribution under review" in text and "Moved by" not in text and "Seconded by" not in text, page
    rc = _block(pages, f"meetings/{MEETING_DEC}.html", RC_SHOWN)
    assert "Attribution under review" in rc and "Moved by" not in rc
    line = _official_line(pages)
    assert "Attribution under review" in line and "Moved by" not in line
    for name, html in public(pages).items():
        assert "Qqraw" not in html, name


def test_unverified_motion_has_no_moved_by_anywhere(tmp_path, facts):
    f, mo = _with_motion(facts)
    unverify(mo)
    pages = build_pages(tmp_path, f)
    for page in (f"meetings/{MEETING_DEC}.html", "items/2024.html"):
        text = _block(pages, page, MO_SHOWN)
        assert "Attribution under review" in text and "Moved by" not in text and "Seconded by" not in text, page
    line = _official_line(pages)
    assert "Moved by" not in line and "Seconded by" not in line


def _raw_facts(facts):
    f = copy.deepcopy(facts)
    for mo in f["motions"]:
        mo["text"] = f"On Motion to Adopt Qqtext {mo['id']} by Commissioner Smitl1"
        for k in ("moved_by", "seconded_by"):
            mo[k]["raw_name"] = f"Qqraw {mo['id']} {k}"
    for m in f["meetings"]:
        for a in m["attendance"]:
            a["raw_name"] = "Qqraw attendee"
    for rc in f["roll_calls"]:
        for v in rc["votes"]:
            v["raw_name"] = "Qqraw voter"
            v["raw_value"] = "Qqrawvalue"
        rc["outcome_text"] = "Qqoutcome"
    return f


def test_public_data_files_have_no_raw_ocr_fields(tmp_path, facts):
    files = export(_raw_facts(facts), tmp_path)
    assert {p.name for p in files} >= {"facts.json", "motions.csv", "votes.csv", "attendance.csv"}
    for p in files:
        text = p.read_text(encoding="utf-8")
        for token in ("Qqraw", "Qqtext", "Qqrawvalue", "Qqoutcome", "outcome_text", "raw_value", "Smitl1", "moved_by_raw", "seconded_by_raw", "raw_name"):
            assert token not in text, (p.name, token)
    header = (tmp_path / "data" / "motions.csv").read_text(encoding="utf-8").splitlines()[0].split(",")
    assert "text" not in header and "type_label" in header
    data = json.loads((tmp_path / "data" / "facts.json").read_text(encoding="utf-8"))
    assert all("text" not in m for m in data["motions"])


def test_internal_export_keeps_raw_fields(tmp_path, facts):
    files = export(_raw_facts(facts), tmp_path, internal=True)
    text = next(p for p in files if p.name == "motions.csv").read_text(encoding="utf-8")
    assert "moved_by_raw" in text and "Qqtext" in text
    assert "Qqoutcome" in next(p for p in files if p.name == "roll_calls.csv").read_text(encoding="utf-8")


def test_junk_raw_vote_value_never_reaches_public_html(tmp_path, facts):
    """raw-ocr-leak/vote-raw-value: an `other` vote prints the minutes' wording only from the fixed list; anything else
    is plain "Other". Confirmed and unconfirmed roll calls alike."""
    from sitegen.views import vote_label
    f = copy.deepcopy(facts)
    for rc in f["roll_calls"]:
        rc["votes"][0].update(value="other", raw_value="Qqjunk Smitl1 C0mm")
        rc["votes"][1].update(value="other", raw_value=" recused. ")
    pages = build_pages(tmp_path, f)
    for name, html in public(pages).items():
        assert "Qqjunk" not in html and "Smitl1" not in html, name
    assert "Other: Recused" in pages[f"meetings/{MEETING_DEC}.html"]
    assert vote_label("other", "Qqjunk") == "Other"
    assert [vote_label("other", w) for w in ("Recused", "ABSENT", "Not Voting", "present")] == [
        "Other: Recused", "Other: Absent", "Other: Not voting", "Other: Present"]


def test_public_html_never_prints_outcome_text(tmp_path, facts):
    f = _raw_facts(facts)
    pages = build_pages(tmp_path, f)
    for name, html in public(pages).items():
        assert "Qqoutcome" not in html, name


# --- raw-ocr-leak/verification-detail: the REAL committed facts, built and exported as a public site ---------------

REAL = Path(__file__).resolve().parent.parent / "data" / "facts.json"


@pytest.fixture(scope="module")
def real_public(tmp_path_factory):
    """The committed data/facts.json, built without --internal and exported the public way: {path: text}."""
    out = tmp_path_factory.mktemp("real") / "build" / "site"
    build(REAL, out, internal=False)
    export(json.loads(REAL.read_text(encoding="utf-8")), out)
    files = {p.relative_to(out).as_posix(): p.read_text(encoding="utf-8")
             for p in out.rglob("*") if p.is_file() and p.suffix in (".html", ".csv", ".json", ".js", ".txt")}
    assert "review.html" not in files and "data/facts.json" in files
    return files


def _real_facts():
    return json.loads(REAL.read_text(encoding="utf-8"))


def test_real_public_export_has_status_and_check_names_only(real_public):
    data = json.loads(real_public["data/facts.json"])
    for coll in ("roll_calls", "motions", "meetings"):
        for x in data[coll]:
            v = x["verification"]
            assert set(v) == {"status", "checks"}, (coll, x["id"])
            assert all(set(c) == {"check", "ok"} for c in v["checks"]), (coll, x["id"])


def test_real_public_files_carry_no_check_detail(real_public):
    f = _real_facts()
    details = {c["detail"] for coll in ("roll_calls", "motions", "meetings") for x in f[coll]
               for c in x["verification"]["checks"] if len(c.get("detail") or "") >= 8}
    assert any("unmatched" in d for d in details), "the committed facts have raw-name details to test against"
    for name, text in real_public.items():
        body = text + "\n" + unescape(text)
        for d in details:
            assert d not in body, (name, d)


def test_real_public_files_carry_no_unmatched_raw_name(real_public):
    """Every name the program read that matched no official ("R. Ailbert", "T. Smitl1") appears in no public file,
    except where it is an official's own name, surname or listed variant (the About page and officials.csv)."""
    f = _real_facts()
    refs = [v for r in f["roll_calls"] for v in r["votes"]] + [a for m in f["meetings"] for a in m["attendance"]]
    refs += [m[k] for m in f["motions"] for k in ("moved_by", "seconded_by") if m[k]]
    raw = sorted({x["raw_name"] for x in refs if not x["official_id"] and x["raw_name"].strip()}, key=len, reverse=True)
    assert raw, "the committed facts have unmatched names to test against"
    shown = sorted({n for o in f["officials"] for n in [o["name"], o["surname"], *o["aliases"]]}, key=len, reverse=True)
    mask = re.compile("|".join(map(re.escape, shown)))
    rx = re.compile(r"(?<!\w)(" + "|".join(map(re.escape, raw)) + r")(?!\w)")
    for name, text in real_public.items():
        body = mask.sub(" ", text + "\n" + unescape(text))
        hit = rx.search(body)
        assert hit is None, (name, hit and hit.group(1))


def test_internal_export_keeps_check_detail(tmp_path):
    export(_real_facts(), tmp_path, internal=True)
    data = json.loads((tmp_path / "data" / "facts.json").read_text(encoding="utf-8"))
    assert any(c.get("detail") for r in data["roll_calls"] for c in r["verification"]["checks"])
