"""Regression tests for the sitegen code review (problem keys in each test's docstring)."""
import copy
import json
import re

import pytest

from conftest import parse
from sitegen import views
from sitegen.build import BuildError, build

MEETING_DEC = "2024-12-09-formal"
MEETING_NOV = "2024-11-04-formal"
MEETING_OCT = "2024-10-07-formal"  # attendance not extracted, no facts
RC_HELD = "rc-314626e6-p16-1"      # unverified roll call at MEETING_DEC
RC_SHOWN = "rc-314626e6-p10-1"     # verified roll call at MEETING_DEC, motion MO_SHOWN
MO_SHOWN = "mo-314626e6-p9-2"      # moved d-testperson, seconded a-example


def by_id(facts, coll, fid):
    return next(x for x in facts[coll] if x["id"] == fid)


def unverify(fact, check="names_resolve"):
    fact["verification"] = {"status": "unverified", "checks": [{"check": check, "ok": False}]}


def build_pages(tmp_path, facts, changes=None):
    path = tmp_path / "facts.json"
    path.write_text(json.dumps(facts), encoding="utf-8")
    if changes is not None:
        (tmp_path / "changes.jsonl").write_text("\n".join(json.dumps(c) for c in changes) + "\n", encoding="utf-8")
    out = tmp_path / "build" / "site"
    build(path, out, internal=True)
    return {p.relative_to(out).as_posix(): p.read_text(encoding="utf-8") for p in out.rglob("*.html")}


def public(pages):
    return {k: v for k, v in pages.items() if k != "review.html"}


def totals(facts):
    ix = views.Index(facts)
    return {o["id"]: views.totals_sentences(ix, o["id"]) for o in facts["officials"]}


# The confirmed / not confirmed count rule (neutrality/held-count) is covered in tests/test_held_counts.py.


# --- neutrality/under-review-mislabelled --------------------------------------------------------------------------


def test_not_extracted_and_under_review_are_separate_sentences(tmp_path, facts):
    """neutrality/under-review-mislabelled: a meeting whose attendance is under review is not described as having no
    extracted attendance section. Two fixed sentences, identical for every official."""
    f = copy.deepcopy(facts)
    unverify(by_id(f, "meetings", MEETING_NOV), "absent_count_matches_stated")
    t = totals(f)
    not_ext = "1 meeting in this period has no extracted attendance section and is not counted."
    review = "1 meeting in this period has an attendance section that is under review and is not counted."
    assert {(s[3], s[4]) for s in t.values()} == {(not_ext, review)}
    pages = build_pages(tmp_path, f)
    for o in f["officials"]:
        html = pages[f"officials/{o['id']}.html"]
        assert not_ext in html and review in html
    assert "Attendance for this meeting is under review" in pages[f"meetings/{MEETING_NOV}.html"]


def test_fixture_counts_each_attendance_state(facts):
    """neutrality/under-review-mislabelled: the fixture has one not-extracted meeting and none under review."""
    s = totals(facts)["a-example"]
    assert s[3].startswith("1 meeting in this period has no extracted attendance section")
    assert s[4].startswith("0 meetings in this period have an attendance section that is under review")


# --- verified-gate/motion-over-hidden ------------------------------------------------------------------------------


def test_failed_motion_check_holds_back_only_attribution(tmp_path, facts):
    """verified-gate/motion-over-hidden + motion-text-names: the verified roll call stays; the unverified motion shows
    only its type in plain words, never its sentence; Moved/Seconded go."""
    f = copy.deepcopy(facts)
    mo = by_id(f, "motions", MO_SHOWN)
    unverify(mo, "seconder_resolves")
    mo["moved_by"] = {"official_id": None, "raw_name": "Qq Unresolved Mover"}
    mo["seconded_by"] = {"official_id": None, "raw_name": "Qq Unresolved Seconder"}
    pages = build_pages(tmp_path, f)

    meeting = parse(pages[f"meetings/{MEETING_DEC}.html"])
    block = next(n for n in meeting.walk() if n.attrs.get("id") == MO_SHOWN)
    text = " ".join(block.all_text().split())
    assert "Motion to approve" in text and mo["text"] not in text
    assert text.count("Attribution under review") == 1
    rc_block = next(n for n in meeting.walk() if n.attrs.get("id") == RC_SHOWN)
    assert "Motion to approve" in rc_block.all_text() and "Attribution under review" in rc_block.all_text()
    assert mo["text"] not in rc_block.all_text()

    items = pages["items/2024.html"]
    assert mo["text"] not in items and "Attribution under review" in items
    # The vote rows for the verified roll call show the type and the fixed sentence, not the raw motion text.
    a_page = pages["officials/a-example.html"]
    row = next(n for n in parse(a_page).walk() if n.attrs.get("data-fact-id") == f"{RC_SHOWN}/a-example")
    assert "Motion to approve" in row.all_text() and "Attribution under review" in row.all_text()
    assert mo["text"] not in row.all_text()
    # No Moved/Seconded rows from the held motion, and the unresolved names appear nowhere public.
    for name, html in public(pages).items():
        assert f"{MO_SHOWN}/moved" not in html and f"{MO_SHOWN}/seconded" not in html, name
        assert "Qq Unresolved" not in html, name
    assert "Qq Unresolved" not in pages["review.html"]  # review lists failed checks, not the raw names
    assert MO_SHOWN in pages["review.html"]


# --- escape/unsafe-url-scheme --------------------------------------------------------------------------------------


@pytest.mark.parametrize("url", [
    "http://example.invalid/m.pdf", "javascript:alert(1)", "data:text/html,<b>x</b>", "//example.invalid/m.pdf",
    "https:/example.invalid/m.pdf", "https://exa mple.invalid/m.pdf", 'https://example.invalid/"onmouseover=x',
    "HTTPS://", "ftp://example.invalid/m.pdf",
])
def test_non_https_source_url_fails_the_build(tmp_path, facts, url):
    """escape/unsafe-url-scheme"""
    f = copy.deepcopy(facts)
    f["sources"][0]["url"] = url
    with pytest.raises(BuildError, match="https"):
        build_pages(tmp_path, f)


@pytest.mark.parametrize("entry", [
    {"date": "2026-11-07", "source_url": "javascript:alert(1)"},
    {"date": "2026-11-07", "source_url": "http://example.invalid/m.pdf"},
    {"date": "2026-11-07", "note": "x", "unexpected": 1},
    {"note": "no date"},
    {"date": "2026-11-07", "page": 0},
])
def test_bad_changes_line_fails_the_build(tmp_path, facts, entry):
    """escape/unsafe-url-scheme: changes.jsonl lines are validated like the facts file."""
    with pytest.raises(BuildError, match="changes.jsonl line 2"):
        build_pages(tmp_path, copy.deepcopy(facts), changes=[{"date": "2026-11-07", "note": "ok"}, entry])


def test_good_changes_line_renders(tmp_path, facts):
    pages = build_pages(tmp_path, copy.deepcopy(facts), changes=[
        {"date": "2026-11-07", "fact_id": RC_SHOWN, "field": "outcome", "old": "failed", "new": "passed",
         "source_url": "https://example.invalid/fixture/minutes-2024-12.pdf", "page": 10}])
    assert 'href="https://example.invalid/fixture/minutes-2024-12.pdf#page=10"' in pages["changes.html"]


# --- contract/no-referential-check ---------------------------------------------------------------------------------


def _set(path, value):
    def mutate(f):
        coll, fid, *keys = path
        obj = by_id(f, coll, fid)
        for k in keys[:-1]:
            obj = obj[k]
        obj[keys[-1]] = value
    return mutate


@pytest.mark.parametrize("mutate,missing", [
    (_set(("roll_calls", RC_SHOWN, "meeting_id"), "2099-01-01-formal"), "2099-01-01-formal"),
    (_set(("roll_calls", RC_SHOWN, "source_id"), "src-000000000000"), "src-000000000000"),
    (_set(("roll_calls", RC_SHOWN, "item_id"), "99-99-99"), "99-99-99"),
    (_set(("roll_calls", RC_SHOWN, "motion_id"), "mo-00000000-p1-1"), "mo-00000000-p1-1"),
    (lambda f: by_id(f, "roll_calls", RC_SHOWN)["votes"][0].update(official_id="z-ghost"), "z-ghost"),
    (_set(("motions", MO_SHOWN, "moved_by", "official_id"), "z-ghost"), "z-ghost"),
    (_set(("motions", MO_SHOWN, "item_id"), "99-99-99"), "99-99-99"),
    (lambda f: by_id(f, "meetings", MEETING_DEC)["attendance"][0].update(official_id="z-ghost"), "z-ghost"),
    (_set(("meetings", MEETING_DEC, "source_id"), "src-000000000000"), "src-000000000000"),
    (_set(("item_events", "ev-314626e6-p10-1", "ref"), "rc-00000000-p1-1"), "rc-00000000-p1-1"),
    (_set(("item_events", "ev-314626e6-p10-1", "item_id"), "99-99-99"), "99-99-99"),
    (_set(("item_events", "ev-314626e6-p10-1", "meeting_id"), "2099-01-01-formal"), "2099-01-01-formal"),
])
def test_dangling_reference_fails_the_build(tmp_path, facts, mutate, missing):
    """contract/no-referential-check"""
    f = copy.deepcopy(facts)
    mutate(f)
    with pytest.raises(BuildError, match=re.escape(repr(missing))):
        build_pages(tmp_path, f)


# --- test gaps: unverified text never public; escaping ------------------------------------------------------------


def test_unverified_text_fields_appear_on_no_public_page(tmp_path, facts):
    """Unverified roll calls' outcome text, raw names and raw vote wording, and the raw names of attendance under
    review, are on no public page."""
    f = copy.deepcopy(facts)
    rc = by_id(f, "roll_calls", RC_HELD)
    rc["outcome_text"] = "Qq held outcome text"
    for n, v in enumerate(rc["votes"]):
        v.update(official_id=None, raw_name=f"Qq Held Voter {n}", value="other", raw_value=f"Qq held wording {n}")
    nov = by_id(f, "meetings", MEETING_NOV)
    unverify(nov, "names_resolve")
    nov["attendance"][0].update(official_id=None, raw_name="Qq Held Attendee")
    pages = build_pages(tmp_path, f)
    secrets = ["Qq held outcome text", "Qq Held Voter", "Qq held wording", "Qq Held Attendee"]
    for name, html in public(pages).items():
        for s in secrets:
            assert s not in html, f"{name} shows {s!r}"
    assert "Qq held outcome text" in pages["review.html"]
    # The original fixture's held roll call outcome text is not public either.
    original = by_id(facts, "roll_calls", RC_HELD)["outcome_text"]
    pub = "".join(public(pages).values())
    assert original not in pub


XSS = ['<script>alert(1)</script>', '"><img src=x onerror=x>']


@pytest.mark.parametrize("payload", XSS)
def test_text_fields_are_escaped(tmp_path, facts, payload):
    """Every text field from the facts and changes files is escaped, never rendered as markup."""
    f = copy.deepcopy(facts)
    f["coverage"]["body"] += payload
    for o in f["officials"]:
        o["name"] += payload
        o["title"] += payload
        o["aliases"].append(payload)
    for it in f["items"]:
        it["title"] += payload
        it["number"] = (it["number"] or "") + payload
    for e in f["item_events"]:
        e["label"] += payload
    for mo in f["motions"]:
        mo["text"] += payload
    for rc in f["roll_calls"]:
        rc["outcome_text"] += payload
        rc["votes"][0].update(value="other", raw_value="Recused" + payload)
    for m in f["meetings"]:
        m["body"] += payload
    pages = build_pages(tmp_path, f, changes=[
        {"date": "2026-11-07", "fact_id": payload, "field": payload, "old": payload, "new": payload, "note": payload}])
    for name, html in pages.items():
        assert "<script>alert" not in html, name
        assert "<img src=x" not in html, name   # the footer logo is a real <img class="gc-logo">
        assert 'onerror=x>' not in html, name
    assert "&lt;script&gt;" in pages["changes.html"] or "&lt;img" in pages["changes.html"]
    assert "&lt;" in pages["officials/a-example.html"]


# --- nit: source link wording follows the source kind --------------------------------------------------------------


def test_source_link_names_the_document_kind(tmp_path, facts):
    f = copy.deepcopy(facts)
    by_id(f, "sources", "src-99d3ff2945a5")["kind"] = "agenda"
    pages = build_pages(tmp_path, f)
    nov = pages[f"meetings/{MEETING_NOV}.html"]
    assert "(opens the agenda PDF in a new tab)" in nov and "(opens the minutes PDF in a new tab)" not in nov
    assert "(opens the minutes PDF in a new tab)" in pages[f"meetings/{MEETING_DEC}.html"]


# --- verified-gate/motion-text-names: no raw OCR sentence of an unverified motion, no raw outcome text -------------


def test_no_unverified_motion_text_and_no_outcome_text_on_any_public_page(tmp_path, facts):
    """Every public page: no raw sentence of an unverified motion (it can carry misread names) and no roll call's
    outcome_text. The outcome reads Passed/Failed/Other with a tally counted from the votes. Both stay on review.html."""
    f = copy.deepcopy(facts)
    for mo in f["motions"]:
        unverify(mo, "seconder_resolves")
        mo["text"] = f"On Motion to Adopt by Commissioner Qq{mo['id']} Beat, seconded by Commissioner Smitl1, the foregoing"
    for rc in f["roll_calls"]:
        rc["outcome_text"] = f"Qqoutcome Com\u00b1issionerGannon {rc['id']}"
    pages = build_pages(tmp_path, f)
    pub = public(pages)
    for name, html in pub.items():
        assert "Beat, seconded" not in html and "Smitl1" not in html and "Qqoutcome" not in html, name
        for mo in f["motions"]:
            assert mo["text"] not in html, name
        for rc in f["roll_calls"]:
            assert rc["outcome_text"] not in html, name
    assert "Motion to adopt" in pages[f"meetings/{MEETING_DEC}.html"]
    assert "Qqoutcome" in pages["review.html"] and "Smitl1" in pages["review.html"]


def test_no_raw_motion_text_even_when_verified(tmp_path, facts):
    """Verified motions show the type label and 'Moved by <display name>, seconded by <display name>' from the
    resolved officials, never the raw sentence or raw OCR names. The raw text stays on review.html."""
    f = copy.deepcopy(facts)
    for mo in f["motions"]:
        mo["text"] = f"On Motion to Adopt by Commissioner Qq{mo['id']} Beat, seconded by Commissioner Smitl1, the foregoing"
        for k in ("moved_by", "seconded_by"):
            mo[k]["raw_name"] = f"Qqraw {mo['id']} {k}"
    pages = build_pages(tmp_path, f)
    for name, html in public(pages).items():
        assert "Beat, seconded" not in html and "Smitl1" not in html and "Qqraw" not in html, name
        for mo in f["motions"]:
            assert mo["text"] not in html, name
    mo = by_id(f, "motions", MO_SHOWN)
    names = {o["id"]: o["name"] for o in f["officials"]}
    html = pages[f"meetings/{MEETING_DEC}.html"]
    text = " ".join(re.sub(r"<[^>]+>", "", html).split())
    assert "Motion to adopt." in text
    assert f"Moved by {names[mo['moved_by']['official_id']]}, seconded by {names[mo['seconded_by']['official_id']]}" in text


def test_outcome_shows_label_and_tally_counted_from_votes(tmp_path, facts):
    f = copy.deepcopy(facts)
    rc = by_id(f, "roll_calls", RC_SHOWN)
    yes = sum(v["value"] == "yes" for v in rc["votes"])
    no = sum(v["value"] == "no" for v in rc["votes"])
    rc["outcome_text"] = "Qqoutcome raw"
    pages = build_pages(tmp_path, f)
    block = next(n for n in parse(pages[f"meetings/{MEETING_DEC}.html"]).walk() if n.attrs.get("id") == RC_SHOWN)
    text = " ".join(block.all_text().split())
    assert f"Passed (counted: {yes} yes, {no} no" in text and "Qqoutcome" not in text


def test_outcome_kind_label_uses_fixed_full_match_patterns_only():
    """The "Vote on:" label comes from the outcome clause by fixed full-match patterns; anything else gets none."""
    from sitegen.views import outcome_kind_label as k
    tail = " by the following roll call vote:"
    assert k("The foregoing Amendment was Adopted" + tail) == "Amendment"
    assert k("The foregoing Resolution, As Amended, was Adopted" + tail) == "Resolution, as amended"
    assert k("The foregoing Resolution was Adopted, as Amended," + tail) == "Resolution, as amended"
    assert k("the foregoing Resolution Failed by the following roll call Vote:") == "Resolution"
    assert k("Brown The foregoing Amendment was Approved" + tail) == "Amendment"
    assert k("The Motion to Defer was Approved" + tail) == "Motion to defer"
    assert k("the foregoing Consent Agenda items were Adopted and Approved" + tail) == "Consent agenda"
    # no exact match: no label, and never any of the clause's own words
    assert k("Mayor Golden was elected by the following roll call vote:") is None
    assert k("The foregoing Amendment to cut funding for the Assessor's renovation Failed" + tail) is None
    assert k("") is None and k(None) is None
