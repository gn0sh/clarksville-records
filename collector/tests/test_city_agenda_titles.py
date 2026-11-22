"""note-titles: an item the minutes print with only its number takes the caption its meeting's own agenda prints for
exactly that number (collector/city_minutes.agenda_captions, collector/city_build.agenda_titles). Fixtures: the
text layer (pdftotext -layout) of six stored CivicClerk agendas, collector/tests/fixtures/city/agenda_<date>.txt."""
import copy
import dataclasses
import json
from pathlib import Path

import jsonschema
import pytest

from collector import agenda_center as ac
from collector.city_build import build
from collector.city_minutes import agenda_captions, caption_text, parse_text
from collector.shrink_guard import keep_documents, shrink_guard, vote_content

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures" / "city"
SCHEMA = json.loads((ROOT / "schema" / "facts.schema.json").read_text())
DATES = ("2024-01-04", "2025-07-01", "2025-09-04", "2026-01-08", "2026-05-07", "2026-07-02")


@pytest.fixture(scope="module")
def cfg():
    return ac.load_config(ac.config_path("clarksville-tn"))


def agenda(date: str) -> list[str]:
    return (FIX / f"agenda_{date}.txt").read_text(encoding="utf-8").split("\f")


@pytest.fixture(scope="module")
def caps(cfg):
    return {d: agenda_captions(agenda(d), cfg) for d in DATES}


# ------------------------------------------------------------------ reading the agenda
def test_every_numbered_entry_of_each_fixture_agenda_gives_one_caption(caps):
    assert {d: len(c) for d, c in caps.items()} == {"2024-01-04": 27, "2025-07-01": 23, "2025-09-04": 27,
                                                     "2026-01-08": 16, "2026-05-07": 18, "2026-07-02": 14}
    assert all(len(v) == 1 for c in caps.values() for v in c.values())       # no number printed twice


def test_caption_is_verbatim_with_its_labels_and_without_the_planning_commission_note(caps):
    assert caps["2026-07-02"][("ordinance", "95-2025-26")] == [(
        "(FIRST READING) [ZONING CASE Z-22-2025] An Ordinance amending the zoning code and map of the City of "
        "Clarksville, application of Youth Realty, LLC for a zone change on a parcel of land located on the eastern "
        "frontage of Professional Park Dr, 1,850 +/- feet south of the intersection of Dunlop Ln & Professional Park "
        "Dr from O-1 Office District to C-2 General Commercial District.", 1)]


def test_kind_and_number_both_key_the_caption(caps):
    c = caps["2026-07-02"]
    assert c[("ordinance", "71-2025-26")][0][0].startswith("(SECOND READING) [ZONING CASE Z-11-2025] An Ordinance")
    assert c[("resolution", "71-2025-26")][0][0] == (
        "A Resolution approving a Certificate of Compliance for sale of wine in a food store at Sudden Service #25, "
        "located at 601 Hornbuckle Rd, Clarksville TN.")


def test_a_number_inside_a_caption_is_no_entry_and_a_sponsor_and_committee_note_are_cut(caps):
    c = caps["2026-07-02"]
    assert ("ordinance", "88-2025-26") not in c
    assert c[("ordinance", "93-2025-26")][0][0] == (
        "(FIRST READING) An Ordinance amending the Operating Budgets for the Fiscal Year 2026-27 for the Clarksville "
        "Parking Commission, a Proprietary Fund (ORDINANCE 88-2025-26)")         # "[Councilman Ambar Marquis] ..." cut
    assert c[("resolution", "69-2025-26")][0][0].endswith("by the Mayor on March 20, 2026.")   # "Councilman Wanda
    assert c[("ordinance", "94-2025-26")][0][0].endswith("greenway development along Matlock Rd.")   # Smith" cut


@pytest.mark.parametrize("date,key,end", [
    # a committee note wrapped over two lines, and two committees in one note
    ("2024-01-04", ("ordinance", "52-2023-24"), "for the Tiny Town Road sidewalk project."),
    ("2024-01-04", ("ordinance", "39-2023-24"), "relative to gas rates, charges, and/or fees"),
    ("2024-01-04", ("ordinance", "54-2023-24"), "for the purpose of road realignment and a park complex."),
    # "Committe" as printed; two notes and a bracketed sponsor; a sponsor then a note of an unheaded committee
    ("2025-09-04", ("ordinance", "18-2025-26"), "in partnership with Appalachian Service Project."),
    ("2025-09-04", ("resolution", "08-2025-26"), "return the results of the study to theCity Council."),
    ("2025-09-04", ("resolution", "18-2025-26"), "to be designated as Kenny York Memorial Way."),
    # a board's note in parentheses after a bare sponsor
    ("2026-01-08", ("resolution", "38-2025-26"), "General Manager of the Clarksville Gas & Water Department."),
    ("2026-01-08", ("resolution", "39-2025-26"), "the Pennyrile Regional Energy Agency (PREA)."),
    ("2026-05-07", ("ordinance", "67-2025-26"), "design and construction of various projects."),
    # a free-text planning commission note
    ("2025-07-01", ("ordinance", "112-2024-25"), "to include Fort Campbell Boulevard and Tiny Town Road Corridors."),
    ("2025-07-01", ("ordinance", "98-2024-25"), "for the purpose of a Sewer Pump Station"),
])
def test_trailing_notes_are_cut(caps, date, key, end):
    text = caps[date][key][0][0]
    assert text.endswith(end)
    assert "Committe" not in text[-40:] and "RPC" not in text and "Mayor Pitts" not in text


@pytest.mark.parametrize("date,key,end,page", [
    # cut by a page break: the next page goes on in lower case, or right of that page's entry labels
    ("2025-09-04", ("resolution", "13-2025-26"), "(Clarksville Bottle Shop, 549 Neptune Dr) and repealing the "
                                                 "certificate of compliance for Clarksville Bottle Shop (924 "
                                                 "Providence Blvd).", 3),
    ("2026-05-07", ("ordinance", "58-2025-26"), "to R-3 Three Family Residential District.", 1),
])
def test_a_caption_runs_on_over_a_page_break(caps, date, key, end, page):
    text, p = caps[date][key][0]
    assert text.endswith(end) and p == page


def test_a_page_break_before_the_next_entry_ends_the_caption(caps):
    text = caps["2026-07-02"][("resolution", "73-2025-26")][0][0]
    assert text.endswith("Certificate of Compliance for Planet Liquors (2400 Madison St).")


def test_labels_alone_are_no_caption(cfg):
    assert caption_text("(FIRST READING) [ZONING CASE Z-1-2026]  RPC: Approval/Approval", cfg.agenda_captions,
                        set(cfg.agenda_captions.committee_names)) == ""


def test_one_entry_for_two_items_gives_neither_a_caption(cfg):
    page = ("     A.   RESOLUTION 10-2025-26 and RESOLUTION 11-2025-26 Resolutions approving two things\n\n"
            "     B.   RESOLUTION 12-2025-26 RESOLUTION 13-2025-26 A Resolution\n")
    assert agenda_captions([page], cfg) == {}


def test_no_captions_without_the_config_key(cfg):
    assert agenda_captions(agenda("2026-07-02"), dataclasses.replace(cfg, agenda_captions=None)) == {}


def test_agenda_captions_config_is_checked():
    raw = ac.yaml.safe_load(ac.config_path("clarksville-tn").read_text(encoding="utf-8"))
    for bad in ({k: v for k, v in raw["agenda_captions"].items() if k != "notes"},
                {**raw["agenda_captions"], "committee_heading": r"^\d+\.\s+(.+) Committee"},
                {**raw["agenda_captions"], "entry": "("}):
        with pytest.raises(ac.AgendaCenterConfigError):
            ac.parse_config({**raw, "agenda_captions": bad})


# ------------------------------------------------------------------ the build
MINUTES_JUL = """                     CLARKSVILLE CITY COUNCIL
                         REGULAR SESSION
                           JULY 2, 2026

CALL TO ORDER

     The regular session of the Clarksville City Council was called to order by Mayor Joe Pitts
     on Thursday, July 2, 2026, at 6:00 p.m. in City Council Chambers.

ATTENDANCE

     PRESENT:      Richard Garrett (Ward 1), Vondell Richmond (Ward 2), Ron Erb (Ward 3)

PLANNING COMMISSION

    ORDINANCE 95-2025-26

           Councilman Erb made a motion to adopt this ordinance on first reading. The motion was seconded by
           Councilman Garrett. The following vote was recorded:

                   AYE: Erb, Garrett, Pitts, Richmond

           The motion to adopt this ordinance on first reading passed.

NEW BUSINESS

    RESOLUTION 69-2025-26

           Councilman Erb made a motion to adopt this resolution. The motion was seconded by
           Councilman Garrett. The following vote was recorded:

                   AYE: Erb, Garrett, Pitts

                   NAY: Richmond

           The motion to adopt this resolution passed.
"""

MINUTES_AUG = MINUTES_JUL.replace("JULY 2, 2026", "AUGUST 6, 2026").replace("July 2, 2026", "August 6, 2026") \
    .replace("    ORDINANCE 95-2025-26\n", "    ORDINANCE 96-2025-26\n") \
    .replace("    RESOLUTION 69-2025-26\n", "    RESOLUTION 69-2025-26 Requiring council approval before a lease "
                                            "ends\n") \
    .replace("NEW BUSINESS", "OLD BUSINESS\n\n    ORDINANCE 9-2025-26\n\n           Councilman Erb made a motion to "
                             "adopt this ordinance. The motion was seconded by\n           Councilman Garrett. The "
                             "following vote was recorded:\n\n                   AYE: Erb, Garrett, Pitts, Richmond\n"
                             "\n           The motion to adopt this ordinance passed.\n\nNEW BUSINESS")

AGENDA_AUG = """     A.   ORDINANCE 96-2025-26 (SECOND READING) An Ordinance approving one thing

     B.   ORDINANCE 96-2025-26 (SECOND READING) An Ordinance approving another thing

     C.   ORDINANCE 09-2025-26 (SECOND READING) An Ordinance with a leading zero

     D.   RESOLUTION 69-2025-26 A Resolution as the agenda prints it
"""


class FakeStore:
    def __init__(self, entries):
        self.entries = {e["url"]: e for e in entries}

    def latest(self, url):
        return self.entries.get(url)

    def has_bytes(self, sha):
        return True

    def path_for(self, sha):
        return Path(f"/nonexistent/{sha}.pdf")


CC = "https://clarksvilletn.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId={},plainText=false)"


def sha(n: int) -> str:
    return f"{n:x}".ljust(64, "0")


def setup():
    rows = [{"date": d, "title": "City Council Regular Session", "kind": "regular", "agenda_id": f"{d}-{n}",
             "agenda_url": CC.format(n), "minutes_url": CC.format(n + 1), "has_previous_versions": False}
            for d, n in (("2026-07-02", 3162), ("2026-08-06", 3300))]
    entries = [{"url": r[f"{k}_url"], "sha256": sha(n), "kind": k, "meeting_date": r["date"],
                "first_fetched_at": "2026-11-09T10:00:00+00:00"}
               for n, (r, k) in enumerate([(rows[0], "agenda"), (rows[0], "minutes"),
                                           (rows[1], "agenda"), (rows[1], "minutes")], start=1)]
    text = {sha(1): agenda("2026-07-02"), sha(2): [MINUTES_JUL], sha(3): [AGENDA_AUG], sha(4): [MINUTES_AUG]}
    of = lambda path: text[Path(path).stem]                                          # noqa: E731
    return rows, FakeStore(entries), of


def run(cfg):
    rows, store, of = setup()
    return build(cfg, rows, store, parse=lambda p, c: parse_text(of(p), c), inspect=lambda p: (3, "text"),
                 pages=of)


@pytest.fixture(scope="module")
def built(cfg):
    return run(cfg)


@pytest.fixture(scope="module")
def without(cfg):
    return run(dataclasses.replace(cfg, agenda_captions=None))


def items_of(facts):
    return {i["id"]: i for i in facts["items"]}


def test_an_untitled_item_takes_its_meetings_agenda_caption_with_its_source(built):
    facts, _ = built
    it = items_of(facts)["ordinance-95-2025-26"]
    assert it["title"].startswith("(FIRST READING) [ZONING CASE Z-22-2025] An Ordinance amending the zoning code")
    assert it["title_source"] == {"kind": "agenda", "source_id": f"src-{sha(1)[:12]}", "page": 1,
                                  "meeting_id": "2026-07-02-regular"}
    m = next(m for m in facts["meetings"] if m["id"] == "2026-07-02-regular")
    assert m["agenda_source_id"] == it["title_source"]["source_id"]


def test_a_title_any_minutes_print_is_never_replaced(built):
    """RESOLUTION 69-2025-26: untitled in the July minutes, whose agenda prints its caption; the August minutes print
    a title. The minutes' words win, with no title_source."""
    it = items_of(built[0])["resolution-69-2025-26"]
    assert it["title"] == "Requiring council approval before a lease ends" and "title_source" not in it


def test_two_different_captions_for_one_number_give_no_title(built):
    facts, summary = built
    it = items_of(facts)["ordinance-96-2025-26"]
    assert it["title"] == "" and "title_source" not in it
    assert summary["agenda_titles"]["ambiguous"] == [{"item_id": "ordinance-96-2025-26",
                                                      "meeting_id": "2026-08-06-regular",
                                                      "source_id": f"src-{sha(3)[:12]}", "pages": [1]}]


def test_only_the_exact_number_matches(built):
    it = items_of(built[0])["ordinance-9-2025-26"]               # the agenda prints 09-2025-26
    assert it["title"] == "" and "title_source" not in it


def test_report_and_schema(built):
    facts, summary = built
    assert {k: v for k, v in summary["agenda_titles"].items() if k != "ambiguous"} == {
        "untitled": 3, "filled": 1, "agendas_read": 2}
    jsonschema.validate({k: v for k, v in facts.items() if k != "_wards"}, SCHEMA)


def test_votes_checks_and_counts_do_not_change(built, without):
    (a, sa), (b, sb) = built, without
    for k in ("meetings", "roll_calls", "motions", "item_events", "officials", "sources", "coverage"):
        assert a[k] == b[k], k
    assert [i["id"] for i in a["items"]] == [i["id"] for i in b["items"]]
    strip = lambda s: {k: v for k, v in s.items() if k != "agenda_titles"}           # noqa: E731
    assert strip(sa) == strip(sb)
    assert sb["agenda_titles"]["filled"] == 0
    assert vote_content(a, ["2026-07-02-regular", "2026-08-06-regular"]) == \
        vote_content(b, ["2026-07-02-regular", "2026-08-06-regular"])


def test_the_shrink_guard_sees_no_loss_when_titles_appear(built, without):
    new, old = built[0], without[0]
    assert shrink_guard(new, old) == {"kept": [], "corrections": []}


def test_a_kept_document_leaves_no_dangling_title_source(built, without):
    """The same rule as pipeline/keep-closure-dangling-zoning-ref: an item still shown whose title cites a meeting
    (or agenda) the keep took out takes the committed item's title, here none, never a dangling citation."""
    new, old = copy.deepcopy(built[0]), copy.deepcopy(without[0])
    old["meetings"] = [m for m in old["meetings"] if m["id"] != "2026-07-02-regular"]   # committed: no July meeting
    it96 = items_of(new)["ordinance-96-2025-26"]                     # voted in August, titled from July's agenda
    it96.update(title="Qq July caption", title_source={"kind": "agenda", "source_id": f"src-{sha(1)[:12]}",
                                                       "page": 1, "meeting_id": "2026-07-02-regular"})
    out = keep_documents(new, old, [{"source_id": f"src-{sha(2)[:12]}", "meeting_ids": ["2026-07-02-regular"]}])
    assert "2026-07-02-regular" not in {m["id"] for m in out["meetings"]}
    published, shown = {s["id"] for s in out["sources"]}, {m["id"] for m in out["meetings"]}
    for it in out["items"]:
        t = it.get("title_source")
        assert not t or (t["source_id"] in published and t["meeting_id"] in shown)
    assert {k: v for k, v in items_of(out)["ordinance-96-2025-26"].items()} == items_of(old)["ordinance-96-2025-26"]


def test_a_kept_document_whose_agenda_stays_published_keeps_the_title(built):
    new = copy.deepcopy(built[0])
    out = keep_documents(new, copy.deepcopy(new), [{"source_id": f"src-{sha(4)[:12]}",
                                                     "meeting_ids": ["2026-08-06-regular"]}])
    assert items_of(out)["ordinance-95-2025-26"]["title_source"]["meeting_id"] == "2026-07-02-regular"


# ------------------------------------------------------------------ the site's item type rule
def test_a_filled_zoning_caption_makes_the_item_a_rezoning(built):
    from sitegen.views import item_types
    it = items_of(built[0])["ordinance-95-2025-26"]
    assert item_types(it) == ["rezoning", "ordinance"]
    assert item_types({**it, "title": ""}) == ["ordinance"]                        # untitled: the number only


# ------------------------------------------------------------------ the export
def test_the_export_cites_the_agenda_for_a_title_it_prints(built, tmp_path):
    import csv
    import io

    from collector.export import PROVENANCE, export
    from collector.tests.test_provenance import unregistered_keys
    facts = {k: v for k, v in copy.deepcopy(built[0]).items() if k != "_wards"}
    files = {f.name: f for f in export(facts, tmp_path)}
    rows = {r["id"]: r for r in csv.DictReader(io.StringIO(files["items.csv"].read_text(encoding="utf-8")))}
    assert rows["ordinance-95-2025-26"]["title_source_url"] == CC.format(3162) + "#page=1"
    assert rows["ordinance-95-2025-26"]["title_source_page"] == "1"
    assert rows["resolution-69-2025-26"]["title_source_url"] == ""
    assert all(f"items.{c}" in PROVENANCE for c in rows["ordinance-95-2025-26"])
    assert not unregistered_keys(json.loads(files["facts.json"].read_text(encoding="utf-8")))
