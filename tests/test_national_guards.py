"""Daylight Digest shared guards (sitegen/national_guards.py; docs/architecture/daylight-national.md 3.5 and 6; task
B14). One test per rule. Problem keys: national/url-scheme-untrusted (finding 4), national/untrusted-size (finding 12),
national/writer-token-scope (ids before paths, finding 6)."""
import copy

import pytest

from sitegen import national as nat
from sitegen import national_guards as g

OFFICIAL = "https://montgomerytn.gov/commission/agenda"


def feed(**meeting):
    m = {"id": "2026-12-14-formal", "date": "2026-12-14", "time": None, "title": "Formal Session",
         "title_ours": True, "meeting_url": "https://mcgtn.org/meeting",
         "agenda": {"state": "final", "url": "https://mcgtn.org/a.pdf", "status_as_posted": None},
         "may_be_incomplete": False, "items_withheld": False, "item_count": 1,
         "items": [{"seq": 1, "number": "CZ-12-2026", "text": "Application of Chris Blackwell from AG to E-1",
                    "source": {"url": "https://mcgtn.org/a.pdf#page=1", "page": 1}}]}
    m.update(meeting)
    return {"schema": "daylight-upcoming/1",
            "body": {"id": "county-47125", "name": "Montgomery County Commission", "tz": "America/Chicago",
                     "official_url": OFFICIAL, "platform": "daylight", "full_url": "meetings/agendas.html"},
            "checked_at": "2026-11-19T14:02:00Z", "last_ok_at": "2026-11-19T14:02:00Z", "meetings": [m]}


# --- allowed_url: https_link, no credentials or odd port, the platform's host allowlist (finding 4) ---------------

def test_url_javascript_scheme_refused():
    assert g.allowed_url("javascript:alert(1)") == ""
    assert g.allowed_url("JavaScript://webapi.legistar.com/%0aalert(1)", "legistar", "salem") == ""


def test_url_http_refused():
    assert g.allowed_url("http://mcgtn.org/a.pdf") == ""
    assert g.allowed_url("http://salem.legistar.com/Calendar.aspx", "legistar", "salem") == ""


def test_url_credentialed_refused():
    assert g.allowed_url("https://user:pw@mcgtn.org/a.pdf") == ""
    assert g.allowed_url("https://webapi.legistar.com@evil.example/x", "legistar", "salem") == ""
    assert g.allowed_url("https://salem.legistar.com:8443/x", "legistar", "salem") == ""


def test_url_https_kept_on_daylight_any_host():
    assert g.allowed_url("https://mcgtn.org/a.pdf#page=1") == "https://mcgtn.org/a.pdf#page=1"
    assert g.allowed_url("https://mcgtn.org:443/a.pdf") == "https://mcgtn.org:443/a.pdf"


def test_url_host_allowlist_off_daylight():
    assert g.allowed_url("https://salem.legistar.com/View.ashx?M=A", "legistar", "salem")
    assert g.allowed_url("https://WebAPI.Legistar.com/v1/salem/events", "legistar", "salem")
    assert g.allowed_url("https://SALEM.legistar.com/x", "legistar", "Salem")            # finding 10: lowercased
    assert g.allowed_url("https://evil.example/x", "legistar", "salem") == ""
    assert g.allowed_url("https://other.legistar.com/x", "legistar", "salem") == ""
    assert g.allowed_url("https://salem.legistar.com.evil.example/x", "legistar", "salem") == ""
    assert g.allowed_url("https://salem.legistar.com/x", "boarddocs") == ""              # unknown platform: no hosts


def test_link_or_official_falls_back():
    assert g.link_or_official("javascript:alert(1)", OFFICIAL) == OFFICIAL
    assert g.link_or_official(None, OFFICIAL) == OFFICIAL
    assert g.link_or_official("https://mcgtn.org/m", OFFICIAL) == "https://mcgtn.org/m"


def test_feed_bad_urls_become_null():
    f = feed(meeting_url="javascript:alert(1)")
    f["body"]["official_url"] = "http://montgomerytn.gov/"
    f["meetings"][0]["agenda"]["url"] = "https://a:b@mcgtn.org/a.pdf"
    f["meetings"][0]["items"][0]["source"]["url"] = "data:text/html,<script>alert(1)</script>"
    out, counts = g.clean_feed(f)
    m = out["meetings"][0]
    assert out["body"]["official_url"] is None
    assert m["meeting_url"] is None and m["agenda"]["url"] is None and m["items"][0]["source"]["url"] is None
    assert counts.urls_dropped == 4


def test_feed_legistar_urls_checked_against_client_hosts():
    f = feed(meeting_url="https://salem.legistar.com/MeetingDetail.aspx?ID=1")
    f["meetings"][0]["agenda"]["url"] = "https://mcgtn.org/a.pdf"
    out, counts = g.clean_feed(f, "legistar", "salem")
    assert out["meetings"][0]["meeting_url"] == "https://salem.legistar.com/MeetingDetail.aspx?ID=1"
    assert out["meetings"][0]["agenda"]["url"] is None
    assert out["body"]["official_url"] is None          # montgomerytn.gov is not a Legistar host
    assert counts.urls_dropped == 3                     # agenda.url, items[].source.url, body.official_url


# --- ids before paths and tags ----------------------------------------------------------------------------------

def test_checked_id():
    assert g.checked_id("county-47125") == "county-47125"
    for bad in ("county-4712", "county-47125/../x", "../county-47125", "place-47125", "County-47125", None, 47125,
                "county-47125\n"):
        with pytest.raises(g.UnsafeIdError):
            g.checked_id(bad)


def test_checked_meeting_id():
    assert g.checked_meeting_id("2026-12-14-formal") == "2026-12-14-formal"
    for bad in ("", "-x", "a/b", "a..b", "A", "x" * 81, "2026-12-14\r\nBEGIN:VEVENT", None):
        with pytest.raises(g.UnsafeIdError):
            g.checked_meeting_id(bad)


def test_trailing_newline_never_passes_a_path_rule():
    # `$` matches before a final newline; every id and path rule uses fullmatch (a YAML `|` scalar ends in "\n").
    assert g.id_layer("county-47125\n") is None
    assert not nat._safe_path("city/\n")
    assert nat.CLIENT_RE.fullmatch("salem\n") is None and nat.CLIENT_RE.match("salem\n") is not None


def test_feed_bad_body_id_refused():
    f = feed()
    f["body"]["id"] = "../../index"
    with pytest.raises(g.UnsafeIdError):
        g.clean_feed(f)


def test_feed_bad_meeting_id_dropped():
    f = feed(id="../x")
    out, counts = g.clean_feed(f)
    assert out["meetings"] == [] and counts.meetings_dropped == 1


def test_builder_shares_the_id_rule():
    assert nat.id_layer is g.id_layer and nat.allowed_url is g.allowed_url and nat.BAD_TEXT_RE is g.BAD_TEXT_RE


# --- text: controls and bidi stripped and counted; caps (finding 12) --------------------------------------------

def test_bidi_string_stripped_and_counted():
    text, n = g.clean_text("Rezone ‮FDP.exe‬ lot ⁦A⁩ ‏B؜")
    assert text == "Rezone FDP.exe lot A B" and n == 6


def test_controls_stripped_and_counted_whitespace_joined():
    text, n = g.clean_text("A\x00B\x1b[31m C\x7f\x85D\r\nBEGIN:VEVENT\tE")
    assert text == "AB[31m CD BEGIN:VEVENT E" and n == 4


def test_feed_text_fields_cleaned_and_counted():
    f = feed(title="Formal‮ Session\x07")
    f["meetings"][0]["items"][0]["text"] = "Item‮ one\x00"
    out, counts = g.clean_feed(f)
    assert out["meetings"][0]["title"] == "Formal Session"
    assert out["meetings"][0]["items"][0]["text"] == "Item one"
    assert counts.chars_stripped == 4 and "chars_stripped=4" in counts.summary()


def test_item_text_cut_at_2000():
    f = feed()
    f["meetings"][0]["items"][0]["text"] = "x" * 2_001
    out, counts = g.clean_feed(f)
    item = out["meetings"][0]["items"][0]
    assert len(item["text"]) == 2_000 and item["cut"] is True and counts.texts_cut == 1
    f["meetings"][0]["items"][0]["text"] = "x" * 2_000
    out, _ = g.clean_feed(f)
    assert len(out["meetings"][0]["items"][0]["text"]) == 2_000 and "cut" not in out["meetings"][0]["items"][0]


def test_items_capped_at_150_per_meeting():
    f = feed()
    one = f["meetings"][0]["items"][0]
    f["meetings"][0]["items"] = [dict(copy.deepcopy(one), seq=i) for i in range(1, 152)]
    out, counts = g.clean_feed(f)
    assert [i["seq"] for i in out["meetings"][0]["items"]] == list(range(1, 151)) and counts.items_dropped == 1


def test_meetings_capped_at_60_per_government():
    f = feed()
    one = f["meetings"][0]
    f["meetings"] = [dict(copy.deepcopy(one), id=f"m-{i}") for i in range(61)]
    out, counts = g.clean_feed(f)
    assert [m["id"] for m in out["meetings"]] == [f"m-{i}" for i in range(60)] and counts.meetings_dropped == 1


def test_clean_feed_leaves_a_clean_feed_unchanged_and_input_untouched():
    f = feed()
    before = copy.deepcopy(f)
    out, counts = g.clean_feed(f)
    assert out == before and f == before and not counts.any()
