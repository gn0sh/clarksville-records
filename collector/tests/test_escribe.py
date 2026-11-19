"""eScribe reader (collector/escribe.py, ADR 0012 A1.4) on the recorded Salem calendar answer (E0); no network."""
import copy
import json
from datetime import date
from pathlib import Path

import pytest

from cities import readers
from collector import escribe
from collector.windows import Window

FIX = Path(__file__).parent / "fixtures" / "escribe"
ANSWER = FIX / "escribe-GetCalendarMeetings-2026-06-01_2026-11-18.json"
HOST = "https://pub-salem.escribemeetings.com"


@pytest.fixture
def cfg():
    return escribe.load_config(FIX / "escribe.yml")


@pytest.fixture
def answer():
    return json.loads(ANSWER.read_text(encoding="utf-8"))


def by_id(rows):
    return {r["agenda_id"]: r for r in rows}


def test_only_configured_body_names_become_rows(cfg, answer):
    rows = escribe.listing_rows(cfg, answer)
    assert [r["title"] for r in rows] == ["City Council", "City Council", "City Council", "City Council Work Session",
                                          "City Council Special Meeting"]       # the Housing Authority is skipped
    assert all(r["source"] == "escribe" for r in rows)
    narrow = {**cfg, "body_names": ("City Council",)}
    assert {r["title"] for r in escribe.listing_rows(narrow, answer)} == {"City Council"}


def test_meeting_ids_kinds_dates_and_row_shape(cfg, answer):
    rows = by_id(escribe.listing_rows(cfg, answer))
    r = rows["escribe-a775a6f9-2c1c-4cd5-b2c2-734e9eb57208"]
    assert r["date"] == "2026-09-28" and r["start_time"] == "18:00" and r["kind"] == "regular"
    assert r["event_id"] == "a775a6f9-2c1c-4cd5-b2c2-734e9eb57208"
    assert set(r) >= {"date", "title", "kind", "agenda_id", "agenda_url", "minutes_url", "video_url", "source",
                      "event_id", "official_page"}
    assert rows["escribe-86d0cf7f-02ac-4114-8210-8776878002bd"]["kind"] == "work-session"
    assert rows["escribe-fa95385f-9c13-42ad-afe2-b341c1a1b237"]["kind"] == "special"
    upper = copy.deepcopy(answer)
    upper["d"][0]["ID"] = upper["d"][0]["ID"].upper()
    assert escribe.listing_rows(cfg, upper)[0]["agenda_id"] == "escribe-a775a6f9-2c1c-4cd5-b2c2-734e9eb57208"


def test_agenda_and_minutes_resolve_against_the_portal_host_pdf_first(cfg, answer):
    rows = by_id(escribe.listing_rows(cfg, answer))
    r = rows["escribe-a775a6f9-2c1c-4cd5-b2c2-734e9eb57208"]
    assert r["agenda_url"] == f"{HOST}/FileStream.ashx?DocumentId=1129"         # "Agenda" PDF, not its HTML
    assert r["minutes_url"] == f"{HOST}/FileStream.ashx?DocumentId=1670"
    assert r["official_page"].startswith(f"{HOST}/MeetingsCalendarView.aspx/Meeting?Id=a775a6f9")
    both = rows["escribe-f37c724c-2c88-4198-8ea9-df5fb3e2ff7a"]                 # PostMinutes PDF and HTML
    assert both["minutes_url"].startswith(f"{HOST}/FileStream.ashx?DocumentId=")
    cover = rows["escribe-fa95385f-9c13-42ad-afe2-b341c1a1b237"]                # only an AgendaCover
    assert cover["agenda_url"].startswith(f"{HOST}/FileStream.ashx?DocumentId=") and cover["minutes_url"] is None


def test_html_minutes_are_the_fallback(cfg, answer):
    a = copy.deepcopy(answer)
    m = next(x for x in a["d"] if x["ID"].startswith("f37c724c"))
    m["MeetingDocumentLink"] = [d for d in m["MeetingDocumentLink"]
                                if not (d["Type"] == "PostMinutes" and d["Format"] == ".pdf")]
    row = by_id(escribe.listing_rows(cfg, a))["escribe-f37c724c-2c88-4198-8ea9-df5fb3e2ff7a"]
    assert row["minutes_url"].startswith(f"{HOST}/Meeting.aspx?Id=f37c724c") and "PostMinutes" in row["minutes_url"]


def test_a_meeting_without_postminutes_has_no_minutes_url(cfg, answer):
    r = by_id(escribe.listing_rows(cfg, answer))["escribe-2bc032f7-5828-4a9a-ad70-2f3f8c50fa44"]
    assert r["minutes_url"] is None and r["agenda_url"] is not None


@pytest.mark.parametrize("url", ["https://evil.example/FileStream.ashx?DocumentId=1670",
                                 "//evil.example/FileStream.ashx?DocumentId=1670",
                                 "http://pub-salem.escribemeetings.com/FileStream.ashx?DocumentId=1670",
                                 "https://pub-salem.escribemeetings.com:8443/FileStream.ashx?DocumentId=1670",
                                 "https://x@pub-salem.escribemeetings.com/FileStream.ashx?DocumentId=1670"])
def test_a_document_on_another_host_is_dropped_and_logged(cfg, answer, url):
    # test-only modified copy: the recorded answer has no document off the portal host
    a = copy.deepcopy(answer)
    m = a["d"][0]
    for d in m["MeetingDocumentLink"]:
        if d["Type"] == "PostMinutes":
            d["Url"] = url
    log = []
    row = escribe.listing_rows(cfg, a, log)[0]
    assert row["minutes_url"] is None
    assert any(line.startswith("escribe/") and "a775a6f9" in line for line in log)
    allowed = {**cfg, "file_hosts": ("evil.example",)}
    if url.startswith("https://evil.example/"):
        assert escribe.listing_rows(allowed, a)[0]["minutes_url"] == url


def test_video_is_a_link_only_and_only_on_video_hosts(cfg, answer):
    rows = by_id(escribe.listing_rows(cfg, answer))
    assert rows["escribe-a775a6f9-2c1c-4cd5-b2c2-734e9eb57208"]["video_url"] == \
        "https://www.youtube.com/watch?v=pMA-ZXyPK_8"
    assert rows["escribe-f37c724c-2c88-4198-8ea9-df5fb3e2ff7a"]["video_url"].startswith("https://youtu.be/")
    log = []
    no_video = escribe.listing_rows({**cfg, "video_hosts": ()}, answer, log)
    assert all(r["video_url"] is None for r in no_video) and any("video-host-not-listed" in x for x in log)
    # a video link never becomes a document: no row's agenda or minutes is on a video host
    assert not any("youtu" in (r["agenda_url"] or "") + (r["minutes_url"] or "") for r in rows.values())
    assert "youtube.com" not in escribe.allowed_hosts(cfg)


def test_the_answer_is_checked_never_trusted(cfg, answer):
    with pytest.raises(escribe.AnswerError):
        escribe.listing_rows(cfg, answer["d"])
    with pytest.raises(escribe.AnswerError):
        escribe.listing_rows(cfg, {"d": ["x"]})
    a = copy.deepcopy(answer)
    a["d"][0]["ID"] = "../../x"
    a["d"][1]["StartDate"] = "2026-13-40"
    a["d"].append(copy.deepcopy(a["d"][2]))                                   # the same meeting twice
    log = []
    rows = escribe.listing_rows(cfg, a, log)
    assert len(rows) == 3
    assert any(x.startswith("escribe/bad-meeting-id") for x in log) and any(x.startswith("escribe/bad-start") for x in log)


def test_calendar_request_sends_only_the_date_window(cfg):
    url, payload = escribe.calendar_request(cfg, Window(date(2026, 7, 1), date(2026, 12, 31)))
    assert url == f"{HOST}/MeetingsCalendarView.aspx/GetCalendarMeetings"
    assert payload == {"calendarStartDate": "2026-07-01", "calendarEndDate": "2026-12-31"}
    with pytest.raises(ValueError):
        escribe.calendar_request(cfg, Window(date(2026, 1, 1), date(2026, 12, 31)))     # longer than 6 months
    assert escribe.post_paths(cfg) == (("pub-salem.escribemeetings.com", url.split(".com", 1)[1]),)
    assert escribe.allowed_hosts(cfg) == ("pub-salem.escribemeetings.com",)


@pytest.mark.parametrize("change", [("host: pub-salem.escribemeetings.com", "host: https://evil.example/"),
                                    ("launch_days: 365", "launch_days: 5"),
                                    ("minutes_types: [PostMinutes]", "minutes_types: []"),
                                    ("  - [regular, '^']", "  - [regular, '(']"),
                                    ("video_hosts: [youtube.com, youtu.be]", "video_hosts: ['a b']"),
                                    ("city: salem-or\n", "")])
def test_a_bad_config_fails_loudly(tmp_path, change):
    p = tmp_path / "escribe.yml"
    text = (FIX / "escribe.yml").read_text()
    assert change[0] in text
    p.write_text(text.replace(change[0], change[1]))
    with pytest.raises(escribe.ConfigError):
        escribe.load_config(p)


def test_the_registry_knows_the_escribe_reader():
    r = readers.READERS["escribe"]
    assert r.built and r.required == escribe.REQUIRED
    assert r.hosts(FIX / "escribe.yml") == ("pub-salem.escribemeetings.com",)
    assert r.link_hosts(FIX / "escribe.yml") == ("youtube.com", "youtu.be")
    assert r.load(FIX / "escribe.yml")["host"] == "pub-salem.escribemeetings.com"
