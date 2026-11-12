"""AC-F6: the collector's committed output (data/finance.json) matches the hand labels in collector/fin_hand_labels.json.

Zero wrong values: every labelled bidder name, printed order and total, the awardee and the dates must be equal; a tab the
labels call not_read must carry no bidder and no awardee; a total printed in a form the site does not read as a number
(`"$ 765,790.00"`) must stay a held value (no cents), never a guessed number."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LABELS = json.loads((ROOT / "collector" / "fin_hand_labels.json").read_text(encoding="utf-8"))["solicitations"]
FIN = json.loads((ROOT / "data" / "finance.json").read_text(encoding="utf-8"))
SOL = {s["slug"]: s for s in FIN["solicitations"]}
DOCS = {d["id"]: d for d in FIN["documents"]}


def cents(printed: str) -> int:
    return round(float(re.sub(r"[^\d.]", "", printed)) * 100)


def test_label_set_meets_ac_f6_mix():
    kinds = [v["tab"] for v in LABELS.values()]
    assert len(LABELS) >= 10
    assert kinds.count("read") >= 10 and kinds.count("not_read") >= 3 and kinds.count("none") >= 1
    reasons = {v.get("reason") for v in LABELS.values() if v["tab"] == "not_read"}
    assert {"layout", "shared_url", "not_pdf"} <= reasons
    assert any(v.get("scanned_award_letters") for v in LABELS.values()), "a scanned award letter must be labelled"
    assert any(len(v.get("bidders", [])) == 2 for v in LABELS.values()), "a two-bidder tab"
    assert any(len(v.get("bidders", [])) >= 10 for v in LABELS.values()), "a many-bidder tab"
    assert any(v.get("awardee") for v in LABELS.values() if v["tab"] == "read"), "a tab that names its awardee"
    assert any(not all(b[2] for b in v.get("bidders", [])) for v in LABELS.values()), "a held total"


@pytest.mark.parametrize("slug", sorted(LABELS))
def test_collector_output_matches_hand_label(slug):
    lab = LABELS[slug]
    assert slug in SOL, f"{slug} is not in data/finance.json"
    sol = SOL[slug]
    bt = sol["bid_tab"]
    if "document_labels" in lab:
        assert sorted(sol["document_labels"]) == sorted(lab["document_labels"])
    if "scanned_award_letters" in lab:
        scanned = [DOCS[i] for i in sol["document_ids"] if DOCS[i]["stage"] == "award_letter" and DOCS[i]["scanned"]]
        assert len(scanned) == lab["scanned_award_letters"]
    if lab["tab"] == "none":
        assert bt is None
        return
    assert bt is not None
    if lab["tab"] == "not_read":
        assert bt["not_read_reason"] == lab["reason"], "wrong or missing not-read reason"
        assert bt["bidders"] == [], "values were read from a tab the labels say must not be read"
        assert bt["awardee_text"] is None and bt["awardee_match"] is None
        assert bt["awardee_page"] is None and bt["award_date_text"] is None
        return
    # read tab: nothing wrong, nothing missing, printed order kept
    assert bt["not_read_reason"] is None
    assert bt["tab_type"] == lab["tab_type"]
    got = [(b["printed_order"], b["name"], b["total_as_printed"], b["total_cents"]) for b in bt["bidders"]]
    want = []
    for i, (name, total, ok) in enumerate(lab["bidders"], 1):
        want.append((i, name, total, cents(total) if ok else None))
    assert got == want
    assert all(b["page"] == 1 for b in bt["bidders"])
    assert bt["bid_date_text"] == lab["bid_date"]
    assert bt["award_date_text"] == lab["award_date"]
    assert bt["awardee_text"] == lab["awardee"]
    if lab["awardee"]:
        names = [b[0] for b in lab["bidders"]]
        norm = lambda s: re.sub(r"\s*&\s*", "&", re.sub(r"\s+", " ", s)).casefold().strip("_ .,")  # noqa: E731
        hits = [i for i, n in enumerate(names, 1) if norm(n) == norm(lab["awardee"])]
        assert len(hits) == 1 and bt["awardee_match"] == f"bidder:{hits[0]}"
    else:
        assert bt["awardee_match"] == "none_named"
