"""collector-input/unread-file-mislabel (security review tip45 1e5b9a7, finding 3): a fetched file that pdfinfo or
pdftotext could not inspect is published as unreadable, never as "not fetched" or "scanned"."""
import subprocess
from pathlib import Path

from collector import agenda_center as ac
from collector import city_build, fin_checks, fin_facts, fin_run
from collector.city_minutes import parse_text
from collector.tests.fin_fake import CFG, FakeFin
from collector.tests.test_city_minutes import PAGE1, PAGE2, rows_and_store
from sitegen import days, fin_views

MINUTES_SHA = "2".ljust(64, "0")          # rows_and_store: the 2019-12-05 minutes file


def test_city_minutes_that_cannot_be_inspected_are_unreadable_not_not_fetched():
    cfg = ac.load_config(ac.config_path("clarksville-tn"))
    rows, store, ok = rows_and_store()

    def inspect(path):
        if MINUTES_SHA in str(path):
            raise subprocess.TimeoutExpired(["pdfinfo", str(path)], 120)
        return ok(path)
    facts, summary = city_build.build(cfg, rows, store, parse=lambda p, c: parse_text([PAGE1, PAGE2], c),
                                      inspect=inspect)
    m = {x["id"]: x for x in facts["meetings"]}["2019-12-05-regular"]
    assert m["minutes_status"] == "unreadable"
    assert m["source_id"] != f"src-{MINUTES_SHA[:12]}"                  # the agenda is cited, not the minutes
    assert summary["minutes_status"].get("unreadable") == 1
    assert "unreadable" in city_build.MINUTES_STATUS


def test_every_minutes_status_has_true_words_on_the_site():
    assert set(days.MINUTES_WORDS) == set(city_build.MINUTES_STATUS) - {"read"}
    assert "could not be read" in days.MINUTES_WORDS["unreadable"]
    assert "not fetched" not in days.MINUTES_WORDS["unreadable"].lower()


def test_scan_guard_names_an_unreadable_source_apart_from_a_scan():
    doc = {"status": "fetched", "shared_by": []}
    assert fin_checks.unreadable(doc, {"text_layer": "unreadable"}) == "unreadable"
    assert fin_checks.unreadable(doc, {"text_layer": "none"}) == "scan"
    assert fin_checks.unreadable(doc, {"text_layer": "text"}) is None


def test_a_finance_file_that_timed_out_is_unreadable_not_scanned(tmp_path, monkeypatch, capsys):
    ff = FakeFin(tmp_path)
    target = ff.store.latest(_rock_url())["sha256"]          # a text bid tab (its layout is not read)

    def run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    real_meta = fin_facts.pdf_meta

    def meta(pdf: Path, cfg, cache_dir=None):
        if pdf.stem == target:
            monkeypatch.setattr(fin_facts.subprocess, "run", run)
            try:
                return real_meta(pdf, cfg, None)
            finally:
                monkeypatch.setattr(fin_facts.subprocess, "run", subprocess.run)
        return ff.meta(pdf, cfg, cache_dir)
    monkeypatch.setattr(fin_facts, "pdf_meta", meta)
    fin, _ = fin_facts.build(ff.store, CFG, status_path=ff.status_path, meta_cache=None,
                             words_for=ff.words_for, book_words=ff.book_words)
    src = next(s for s in fin["sources"] if s["sha256"] == target)
    assert src["text_layer"] == "unreadable" and src["pages"] is None
    docs = [d for d in fin["documents"] if d["source_id"] == src["id"]]
    assert docs and not any(d["scanned"] for d in docs)                 # never called a scan
    assert fin_run.validate(fin) == []                                  # the schema knows the value
    fx = fin_views.Finance(fin)
    sol = next(s for s in fin["solicitations"] if docs[0]["id"] in s["document_ids"])
    view = fin_views._doc_link(fx, docs[0], sol)
    assert view["note"] == fin_views.C["unreadable"] and not view["scanned"]
    assert "pdf inspection failed (TimeoutExpired)" in capsys.readouterr().err
    tab = next(s["bid_tab"] for s in fin["solicitations"] if s["bid_tab"]
               and s["bid_tab"]["document_id"] == docs[0]["id"])
    assert tab["not_read_reason"] == "unreadable"                       # its own reason, not "scan" or "layout"
    assert fin["coverage"]["n_tab_not_read"] == {"layout": 0, "scan": 2, "shared_url": 2, "not_pdf": 1,
                                                 "not_fetched": 0, "unreadable": 1}
    assert fin_views.C["not_read"]["unreadable"]


def _rock_url() -> str:
    from collector.tests.fin_fake import links
    return next(u for u, _, _ in links() if u.endswith("Bid%20Tab%20-%20Hwy%20Dept%20Rock%20FY27.pdf"))
