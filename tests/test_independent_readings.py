"""Invariant: independent readings (architecture, problem family `parse-accuracy`, stated after hit 2).

Two readings are independent only when their engines differ (text layer, tesseract); a same-engine reading can veto
but never corroborates. Any dissent (a clean reading with another value, or a malformed one) leaves a zoning field
null or holds a roll call; there is no majority. The five cases the architecture names, restated by QA.
"""
import json
from pathlib import Path

import pytest

from collector import parse as P
from collector import zoning as Z
from collector.tests.test_zoning import AGENDA, resolution

ROOT = Path(__file__).resolve().parent.parent
MARCH_2024 = "505a509b28f729ae"         # March 11, 2024 minutes: CZ-01-2024 on p2 (agenda) and p5 (resolution)


@pytest.fixture(scope="module")
def rules():
    return Z.load_rules()


def pooled(readings, sid="src-505a509b28f7", date="2024-03-11"):
    return [(r, sid, date) for r in readings]


def case(readings, n="CZ-01-2024"):
    return [r for r in readings if r.case == n]


# ------------------------------------------------------------------ 1. CZ-01-2024, OCR on and off

def test_cz_01_2024_applicant_is_null_on_the_page_texts_whatever_the_ocr(rules):
    """The page prints "Johnathan Blick" three times; the text layer reads "Buck" twice. With tesseract reading the
    name right everywhere, the text layer's "Buck" still dissents; with --no-ocr (one engine) nothing publishes."""
    text = case(Z.page_readings([AGENDA, resolution()], rules))
    right = resolution(name="Johnathan Blick", name2="Johnathan Blick")
    tess = case(Z.page_readings(["", right], rules, engine="tesseract"))
    assert Z.decide(pooled(text))["applicant"] is None                       # --no-ocr
    assert Z.decide(pooled(text + tess))["applicant"] is None                # OCR on


def _store_doc():
    from collector.store import Store
    st = Store()
    e = next((e for e in st.entries if e["sha256"].startswith(MARCH_2024)), None)
    return (st, e) if e and st.has_bytes(e["sha256"]) else (None, None)


@pytest.mark.skipif(_store_doc()[0] is None, reason="the March 2024 minutes are not in this checkout's store")
@pytest.mark.parametrize("use_ocr", [True, False])
def test_cz_01_2024_applicant_is_null_on_the_real_minutes(use_ocr):
    from collector.minutes import TEXT_CACHE, cached_pages, zoning_readings
    st, e = _store_doc()
    pdf = st.path_for(e["sha256"])
    pages = cached_pages(pdf, TEXT_CACHE)
    rs = case(zoning_readings(pdf, e, pages, use_ocr))
    assert any(r.field == "applicant" and "Buck" in r.shown for r in rs)        # the misread is there to veto
    assert ({r.engine for r in rs} == {"text-layer", "tesseract"}) == use_ocr
    assert Z.decide(pooled(rs))["applicant"] is None


def test_cz_01_2024_applicant_is_null_in_the_committed_facts():
    facts = json.loads((ROOT / "data" / "facts.json").read_text(encoding="utf-8"))
    it = next(i for i in facts["items"] if i["number"] == "CZ-01-2024")
    assert it["zoning"]["applicant"] is None


# ------------------------------------------------------------------ 2. same engine never corroborates

def test_two_text_layer_printings_that_agree_publish_nothing_alone(rules):
    page = resolution(name="Johnathan Blick", name2="Johnathan Blick")
    text = case(Z.page_readings([page], rules))
    names = [r for r in text if r.field == "applicant"]
    assert len({r.printing for r in names}) >= 2 and len({r.key for r in names}) == 1   # printings agree...
    out = Z.decide(pooled(text) + pooled(text, "src-aaaaaaaaaaaa"))                       # ...even in two documents
    assert all(v is None for v in out.values())                                          # one engine: nothing


# ------------------------------------------------------------------ 3. one malformed reading vetoes

def test_one_malformed_reading_nulls_a_field_both_engines_agree_on(rules):
    page = resolution(name="Johnathan Blick", name2="Johnathan Blick")
    both = case(Z.page_readings([page], rules) + Z.page_readings([page], rules, engine="tesseract"))
    assert Z.decide(pooled(both))["acreage"]["value"] == 2.32
    bad = case(Z.page_readings([page.replace("containing 2.32 +1- acres", "containing 0.00 +1- acres")], rules,
                               engine="tesseract"))
    acres = [r for r in bad if r.field == "acreage"]
    assert [(r.key, r.value) for r in acres] == [(Z.MALFORMED, None)]       # matched, failed the number check: kept
    assert Z.decide(pooled(both + acres))["acreage"] is None


# ------------------------------------------------------------------ 4. "---" or "?" in the text layer holds

ROSTER = ["A", "B", "C", "D"]


def _reading(source, votes, absent=("D",), tally=(2, 1, 0), reasons=(), clean=None):
    return P.Reading(source, dict(votes), tally, list(absent), list(reasons), {},
                     clean if clean is not None else {m: True for m in votes}, tally)


@pytest.fixture
def body_of_four(monkeypatch):
    monkeypatch.setattr(P, "FULL_BODY", 3)          # a small body, so 2 of 3 Yes passes the outcome check


def _rc(readings):
    rc = P.RollCall(source="t", meeting_date=None, page=1, end_page=1, line=0, item=None, item_title=None,
                    kind="resolution", outcome_text="Adopted", motion=None, mover=None, seconder=None,
                    votes={}, tally=None, absent=[])
    rc.roster = list(ROSTER)
    rc.readings = readings
    P.decide(rc)
    return rc


TESS = {"A": "Yes", "B": "Yes", "C": "No", "D": "---"}


@pytest.mark.parametrize("cell,reason", [("---", "no vote read for present member: B"),
                                         ("?", "conflicting vote marks ['Y', 'N'] for B")])
def test_a_dash_or_query_in_the_text_layer_holds_a_roll_call_tesseract_reads_cleanly(cell, reason, body_of_four):
    tess = _reading("tesseract", TESS)
    assert not P.check_outcome("Adopted", tess.tally) and _rc([tess]).status == "Verified"   # passes P2 alone
    text = _reading("text-layer", dict(TESS, B=cell), reasons=[reason],
                    clean={"A": True, "B": cell != "?", "C": True, "D": True})
    rc = _rc([text, tess])
    assert rc.status == "Unverified"
    assert any(x.startswith("sources disagree for B") for x in rc.reasons), rc.reasons
    assert P.cell_dissent(text, tess, "B") and not P.cell_dissent(text, tess, "A")


def test_the_one_cell_rule_is_shared_by_combine_and_source_inconsistent(body_of_four):
    from collector import verify as V
    a = _reading("text-layer", dict(TESS, B="---"), reasons=["listed absent but has vote Yes: C"])
    b = _reading("tesseract", TESS, reasons=["listed absent but has vote Yes: C"])
    c = P.combine([a, b], ROSTER)
    assert c.votes["B"] == "?" and any("dissent for B" in x for x in c.reasons)
    rc = _rc([a, b])
    assert rc.status == "Unverified" and not V.source_inconsistent(rc)      # they do not agree on every vote
    # an ABSENT line with a problem is malformed: it holds the combination instead of being skipped
    d = _reading("text-layer", TESS, reasons=["absent name not on roster: 'Zed'", "no vote read for present member: A"])
    assert any("ABSENT line has a problem" in x for x in P.combine([d, b], ROSTER).reasons)


def test_a_tally_read_garbled_by_one_engine_is_dissent(body_of_four):
    """parse-accuracy/tests-miss-new-dissent: tesseract passes P2 alone; the text layer found the tally line but a
    count is garbled. That is dissent: decide holds, disagreements names it, combine holds."""
    tess = _reading("tesseract", TESS)
    text = _reading("text-layer", TESS, tally=None, reasons=["tally unreadable ('?2', '1', '0')"])
    text.printed = None
    assert [d for d in P.disagreements(text, tess) if "a count read garbled" in d]
    rc = _rc([text, tess])
    assert rc.status == "Unverified" and any("a count read garbled" in x for x in rc.reasons), rc.reasons
    b = _reading("tesseract", TESS, reasons=["no vote read for present member: A"])
    assert "a reading read the stated tally garbled" in P.combine([text, b], ROSTER).reasons
    # a tally line not found at all is "none", not dissent
    gone = _reading("text-layer", TESS, tally=None, reasons=["stated tally not found"])
    assert not P.disagreements(gone, tess)


def test_different_absent_names_are_dissent(body_of_four):
    """parse-accuracy/tests-miss-new-dissent: two readings that both read the ABSENT line, with different names."""
    tess = _reading("tesseract", TESS)
    text = _reading("text-layer", TESS, absent=("C",),
                    reasons=["listed absent but has vote No: C", "no vote read for present member: D"])
    assert [d for d in P.disagreements(text, tess) if "ABSENT names" in d]
    rc = _rc([text, tess])
    assert rc.status == "Unverified" and any("ABSENT names" in x for x in rc.reasons), rc.reasons
    b = _reading("tesseract", TESS, reasons=["no vote read for present member: A"])
    assert "ABSENT line not read alike by any reading" in P.combine([text, b], ROSTER).reasons
    # an ABSENT line not found is "none"
    gone = _reading("text-layer", TESS, absent=(), reasons=["ABSENT line not found"])
    assert not [d for d in P.disagreements(gone, tess) if "ABSENT" in d]


def test_every_reading_of_a_consent_reprint_can_dissent(body_of_four):
    """parse-accuracy/reprint-dissent-unchecked: a reprint never corroborates, but any of its readings (either engine,
    or their combination) dissents against any reading of the roll call's own printing (Oct 2022 p143: the reprint's
    tesseract read "?" for one member while its text layer agreed; Feb 2021 p99: the text layer read "---")."""
    from types import SimpleNamespace as NS
    from collector.facts import reprint_dissent
    own = NS(page=32, readings=[_reading("text-layer", TESS)], combined=None)
    agree = _reading("text-layer", TESS)
    query = _reading("tesseract", dict(TESS, B="?"), reasons=["conflicting vote marks ['Y', 'N'] for B"])
    assert not reprint_dissent(own, [NS(page=122, readings=[agree], combined=None)])
    out = reprint_dissent(own, [NS(page=143, readings=[agree, query], combined=None)])
    assert out and all("for B" in d for d in out) and any(d.startswith("p32 text-layer vs p143 tesseract") for d in out)
    dash = _reading("text-layer", dict(TESS, B="---"), reasons=["no vote read for present member: B"])
    assert any("for B" in d for d in reprint_dissent(own, [NS(page=99, readings=[dash], combined=None)]))
    garbled = _reading("tesseract", TESS, tally=None, reasons=["tally unreadable ('2', '?', '0')"])
    assert any("garbled" in d for d in reprint_dissent(own, [NS(page=90, readings=[agree, garbled], combined=None)]))
    # pairs inside the roll call's own printing are decide's, not repeated here
    own2 = NS(page=32, readings=[_reading("text-layer", TESS), query], combined=None)
    out = reprint_dissent(own2, [NS(page=122, readings=[agree], combined=None)])
    assert out == [d for d in out if d.startswith("p32 tesseract vs p122 text-layer")] and out


# ------------------------------------------------------------------ 5. shown form

def test_shown_form_of_mcdonald_and_mc_donald_is_mcdonald(rules):
    def rd(engine, shown, printing="submitted"):
        v = Z._applicant(shown)
        return Z.Reading("CZ-09-2024", "applicant", v[0], v[1], v[2], printing, engine, 3)
    for text, tess in (("Ann McDonald", "Ann Mc Donald"), ("Ann Mc Donald", "Ann McDonald")):
        out = Z.decide(pooled([rd("text-layer", text), rd("tesseract", tess)]))
        assert out["applicant"]["value"] == "Ann McDonald", (text, tess)
    # a form both engines read character for character wins; a break both engines saw is kept
    out = Z.decide(pooled([rd("text-layer", "AnnMcDonald"), rd("tesseract", "Ann Mc Donald"),
                           rd("text-layer", "Ann McDonald", "heading"), rd("tesseract", "Ann McDonald", "heading")]))
    assert out["applicant"]["value"] == "Ann McDonald"
    out = Z.decide(pooled([rd("text-layer", "AnnMcDonald"), rd("text-layer", "Ann McDonald", "heading"),
                           rd("tesseract", "Ann Mc Donald")]))
    assert out["applicant"]["value"] == "Ann McDonald"                  # never the reading with the most spaces
