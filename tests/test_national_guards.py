"""Daylight Digest shared guards (sitegen/national_guards.py; docs/architecture/daylight-national.md 3.5 and 6; task
B14). One test per rule. Problem keys: national/url-scheme-untrusted (finding 4), national/untrusted-size (finding 12),
national/writer-token-scope (ids before paths, finding 6)."""
import copy
import json

import pytest

from sitegen import national as nat
from sitegen import national_guards as g

OFFICIAL = "https://montgomerytn.gov/commission/agenda"
REVIEW = next(r.digest for r in nat.SHOWN_REVIEWED if r.gov == "county-47125")


def feed(**meeting):
    m = {"id": "2026-12-14-formal", "date": "2026-12-14", "time": None, "title": "Formal Session",
         "title_ours": True, "meeting_url": "https://mcgtn.org/meeting",
         "agenda": {"state": "final", "url": "https://mcgtn.org/a.pdf", "status_as_posted": None},
         "may_be_incomplete": False, "items_withheld": False, "item_count": 1,
         "items": [{"seq": 1, "number": "CZ-12-2026", "text": "Application of Chris Blackwell from AG to E-1",
                    "source": {"url": "https://mcgtn.org/a.pdf#page=1", "page": 1}}]}
    m.update(meeting)
    return {"schema": "daylight-upcoming/1", "review": REVIEW,
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


# --- review fixes (B14 code review) -------------------------------------------------------------------------------

RAISING_URLS = ("https://[x/", "https://[::1/x", "https://]x/", "https://a＃b.org/", "https://a℀.org/")


@pytest.mark.parametrize("url", RAISING_URLS)
def test_url_urlsplit_error_refused_not_raised(url):
    # national/url-scheme-untrusted/urlsplit-raises
    assert g.allowed_url(url) == "" and g.allowed_url(url, "legistar", "salem") == ""
    f = feed(meeting_url=url)
    f["meetings"][0]["agenda"]["url"] = url
    f["meetings"][0]["items"][0]["source"]["url"] = url
    f["body"]["official_url"] = url
    out, counts = g.clean_feed(f)
    m = out["meetings"][0]
    assert out["body"]["official_url"] is None and m["meeting_url"] is None and m["agenda"]["url"] is None
    assert m["items"][0]["source"]["url"] is None and counts.urls_dropped == 4


@pytest.mark.parametrize("ch", ["‮", "⁦", "​", "﻿", "­", "\U000e0041", "\x85"])
def test_url_with_bidi_or_invisible_refused(ch):
    # national/url-scheme-untrusted/bidi-in-url
    assert g.allowed_url(f"https://mcgtn.org/{ch}gpj.exe") == ""
    assert g.allowed_url(f"https://salem.legistar.com/{ch}x", "legistar", "salem") == ""


def test_lone_surrogate_stripped_and_counted():
    # national/untrusted-size/lone-surrogate: json.loads accepts a lone surrogate escape
    text, n = g.clean_text(json.loads('"A\\ud800B\\udfffC"'))
    assert text == "ABC" and n == 2
    f = feed()
    f["meetings"][0]["items"][0]["text"] = json.loads('"x\\ud800y"')
    out, counts = g.clean_feed(f)
    assert out["meetings"][0]["items"][0]["text"] == "xy" and counts.chars_stripped == 1
    out["meetings"][0]["items"][0]["text"].encode("utf-8")           # writable as UTF-8 JSON


def test_invisible_characters_stripped_and_counted():
    text, n = g.clean_text("Zo​ne‌ ‍A⁠⁢B﻿ so­ft \U000e0041\U000e007fC")
    assert text == "Zone AB soft C" and n == 9


def test_items_cap_applies_after_non_objects_are_dropped():
    # national/untrusted-size/items-cap-order
    f = feed()
    one = f["meetings"][0]["items"][0]
    f["meetings"][0]["items"] = ["junk", None, 7] + [dict(copy.deepcopy(one), seq=i) for i in range(1, 151)]
    out, counts = g.clean_feed(f)
    assert [i["seq"] for i in out["meetings"][0]["items"]] == list(range(1, 151)) and counts.items_dropped == 3
    f["meetings"][0]["items"].append(dict(copy.deepcopy(one), seq=151))
    out, counts = g.clean_feed(f)
    assert len(out["meetings"][0]["items"]) == 150 and counts.items_dropped == 4


def test_cut_never_splits_a_combining_mark_or_zwj_sequence():
    text, cut = g.cut_text("x" * 1_999 + "é" + "y")                     # combining acute at the cap
    assert cut and text == "x" * 1_999
    text, cut = g.cut_text("x" * 1_998 + "\U0001F469‍\U0001F4BB" + "y")   # ZWJ just before the cap
    assert cut and text == "x" * 1_998
    text, cut = g.cut_text("x" * 1_999 + "\U0001F44D\U0001F3FD" + "y")        # skin-tone modifier at the cap
    assert cut and text == "x" * 1_999
    text, cut = g.cut_text("x" * 2_001)
    assert cut and text == "x" * 2_000


def test_clean_feed_does_not_mutate_a_dirty_input():
    f = feed(title="A‮B", meeting_url="javascript:alert(1)")
    item = f["meetings"][0]["items"][0]
    f["meetings"][0]["items"] = ["junk", dict(copy.deepcopy(item), text="y" * 3_000), copy.deepcopy(item)]
    f["meetings"].append({"id": "../x"})
    before = copy.deepcopy(f)
    out, counts = g.clean_feed(f)
    assert f == before and out != before and counts.any()


@pytest.mark.parametrize("bad", [None, [], "feed", 3])
def test_non_object_feed_refused(bad):
    with pytest.raises(g.UnsafeIdError):
        g.clean_feed(bad)


# --- is_shown and bind_feed: the shown gate (section 11.2, 11.3 item 6; privacy-withhold/national-prefix) ---------

def county_entry(**changes):
    e = dict(nat.load_directory().get("county-47125"))
    e.update(changes)
    return e


def test_is_shown_needs_items_shown_and_a_review_digest():
    e = county_entry()
    assert g.is_shown(e)
    assert not g.is_shown(county_entry(items="withheld"))
    assert not g.is_shown(county_entry(review=None))
    assert not g.is_shown(county_entry(review="x" * 64))
    assert not g.is_shown({k: v for k, v in e.items() if k != "items"})
    assert not g.is_shown(None) and not g.is_shown({"items": "shown", "review": REVIEW.upper()})


def test_bind_shown_and_matching_is_unchanged():
    f = feed()
    out, counts = g.bind_feed(f, county_entry())
    assert out == f and out is not f
    assert (counts.withheld_stripped, counts.review_mismatch) == (0, 0)


def test_bind_withheld_entry_strips_and_counts():
    out, counts = g.bind_feed(feed(), county_entry(items="withheld", review=None))
    m = out["meetings"][0]
    assert (m["items"], m["item_count"], m["items_withheld"], out["review"]) == ([], None, True, None)
    assert (counts.withheld_stripped, counts.review_mismatch) == (1, 0)
    assert "Blackwell" not in json.dumps(out)


def test_bind_stale_review_strips_and_counts():
    out, counts = g.bind_feed(feed(), county_entry(review="0" * 64))
    assert out["meetings"][0]["items"] == [] and out["review"] is None
    assert (counts.withheld_stripped, counts.review_mismatch) == (0, 1)
    out, counts = g.bind_feed(dict(feed(), review=None), county_entry())     # a feed read before any review
    assert out["meetings"][0]["items"] == [] and counts.review_mismatch == 1


def test_bind_counts_summary_has_counts_only():
    _, counts = g.bind_feed(feed(), county_entry(items="withheld", review=None))
    assert counts.summary() == "withheld_stripped=1, review_mismatch=0"


@pytest.mark.parametrize("change", [{"id": "place-4715160"}, {"platform": "legistar"}, {"id": None}])
def test_bind_other_body_or_platform_raises(change):
    f = feed()
    f["body"].update(change)
    with pytest.raises(g.BindError):
        g.bind_feed(f, county_entry())


@pytest.mark.parametrize("bad", [None, [], {"meetings": []}, {"body": "county-47125"}])
def test_bind_not_a_feed_raises(bad):
    with pytest.raises(g.BindError):
        g.bind_feed(bad, county_entry())


def test_bind_error_is_a_value_error_and_guards_import_only_config():
    assert issubclass(g.BindError, ValueError)
    src = g.__file__ and open(g.__file__, encoding="utf-8").read()
    assert "from . import config" in src and "from .national" not in src and "import sitegen.national" not in src



# --- security review of v3 (docs/reviews/security-daylight-national-withhold-v3.md) -------------------------------

def withheld_feed():
    f = feed(title="Hearing for Jane Doe", time="6 PM at Jane Doe's house")
    f["meetings"][0]["agenda"]["status_as_posted"] = "Final (Jane Doe)"
    f["body"]["name"] = "Jane Doe Youth Council"
    return f


def test_free_text_outside_items_withheld_entry():
    out, _ = g.bind_feed(withheld_feed(), county_entry(items="withheld", review=None))
    m = out["meetings"][0]
    assert (m["title"], m["title_ours"], m["time"], m["agenda"]["status_as_posted"]) == (g.WITHHELD_TITLE, True,
                                                                                        None, None)
    assert "Jane" not in json.dumps(out)


def test_free_text_kept_for_a_shown_entry():
    out, _ = g.bind_feed(feed(title="Formal Session", time="6:00 PM"), county_entry())
    assert (out["meetings"][0]["title"], out["meetings"][0]["time"]) == ("Formal Session", "6:00 PM")


@pytest.mark.parametrize("entry", [{}, {"items": "withheld", "review": None}])
def test_body_is_rewritten_from_the_entry(entry):
    e = county_entry(**entry)
    f = withheld_feed()
    f["body"].update(tz="Mars/Base", official_url="https://evil.example/", full_url="x/", extra="y")
    out, _ = g.bind_feed(f, e)
    assert out["body"] == {"id": "county-47125", "name": "Montgomery County Commission", "tz": "America/Chicago",
                           "official_url": e["official_url"], "platform": "daylight",
                           "full_url": "meetings/agendas.html"}


def test_body_tz_from_a_legistar_entry():
    e = {"gov": "place-4164900", "body_name": "Salem City Council", "official_url": "https://salem.legistar.com/",
         "platform": "legistar", "legistar": {"client": "salem", "body_id": 1, "tz": "America/Los_Angeles"},
         "items": "withheld", "review": None}
    f = feed()
    f["body"].update(id="place-4164900", platform="legistar")
    out, _ = g.bind_feed(f, e)
    assert out["body"]["tz"] == "America/Los_Angeles" and out["body"]["full_url"] is None


@pytest.mark.parametrize("meetings", [{"a": {}}, "x", None, [1], [{}, []]])
def test_bind_shape_meetings_must_be_a_list_of_objects(meetings):
    f = feed()
    f["meetings"] = meetings
    with pytest.raises(g.BindError, match="meetings must be a list of objects"):
        g.bind_feed(f, county_entry())


def test_bind_shape_unknown_top_level_key_refused():
    f = dict(feed(), notes="Jane Doe")
    with pytest.raises(g.BindError, match="unknown top-level key 'notes'"):
        g.bind_feed(f, county_entry())


def test_error_echo_bad_id_and_long_values():
    f = feed()
    f["body"]["id"] = "<script>" + "x" * 500
    with pytest.raises(g.BindError) as err:
        g.bind_feed(f, county_entry())
    assert "<bad id>" in str(err.value) and "script" not in str(err.value)
    f = feed()
    f["body"]["platform"] = "p" * 500
    with pytest.raises(g.BindError) as err:
        g.bind_feed(f, county_entry())
    assert len(str(err.value)) < 200
    with pytest.raises(g.BindError) as err:
        g.bind_feed(dict(feed(), **{"k" * 500: 1}), county_entry())
    assert len(str(err.value)) < 200
    with pytest.raises(g.BindError) as err:
        g.bind_feed(feed(), county_entry(gov="<img>" * 50))
    assert "<img>" not in str(err.value)
