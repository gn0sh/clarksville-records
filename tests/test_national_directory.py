"""Daylight Digest curated files and page directory (sitegen/national.py; docs/architecture/daylight-national.md 3.2-3.4,
section 11; security findings 5, 7, 9). One test per refusal of architecture 3.2, the shipped files, the page
directory and MAX_ANSWER. Problem keys: privacy-withhold/national-prefix, national/r5-not-enforced,
national/postmessage-hardening."""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from sitegen import national as nat

LABELS = nat.load_labels()
BUILT = datetime(2026, 11, 19, 15, 0, tzinfo=timezone.utc)

COVERED = {"gov": "place-4715160", "also": [], "body_name": "Clarksville City Council", "state": "TN",
           "status": "covered", "official_url": "https://www.clarksvilletn.gov/", "checked": "2026-11-19",
           "checked_url": "https://clarksvilletn.portal.civicclerk.com/", "items": "shown", "platform": "daylight",
           "daylight": {"body": "city", "full_url": "city/"}}
CANT = {"gov": "sdu-4703030", "body_name": "Clarksville-Montgomery County School System Board of Education",
        "state": "TN", "status": "cant-cover", "reason": "blocks-readers", "reason_url": "https://www.cmcss.net/",
        "official_url": "https://www.cmcss.net/", "checked": "2026-11-10",
        "checked_doc": "docs/research/rpc-cmcss-sources.md"}
LEGISTAR = {"gov": "place-4164900", "body_name": "Salem City Council", "state": "OR", "status": "covered",
            "official_url": "https://salem.legistar.com/Calendar.aspx", "checked": "2026-12-01",
            "checked_url": "https://salem.legistar.com/Calendar.aspx", "items": "shown", "platform": "legistar",
            "legistar": {"client": "salem", "body_id": 138, "tz": "America/Los_Angeles", "final_statuses": ["Final"]},
            "host_ok": {"date": "2026-12-01", "link": "https://github.com/gn0sh/clarksville-records/pull/1"}}


def write_dir(tmp_path, govs, **top):
    p = tmp_path / "directory.yml"
    p.write_text(yaml.safe_dump({"schema": "daylight-directory/1", "govs": govs, **top}, sort_keys=False),
                 encoding="utf-8")
    return p


def load(tmp_path, *govs, labels=LABELS, **top):
    return nat.load_directory(write_dir(tmp_path, list(govs), **top), labels)


def changed(base, **kw):
    """A copy of `base` with keys set (a value of ... removes the key); `a__b` sets a nested key."""
    e = copy.deepcopy(base)
    for k, v in kw.items():
        obj, key = (e[k.split("__")[0]], k.split("__")[1]) if "__" in k else (e, k)
        if v is ...:
            obj.pop(key, None)
        else:
            obj[key] = v
    return e


# --- the shipped files -------------------------------------------------------------------------------------------

def test_shipped_files_load():
    d, flags, labels = nat.load_all()
    ids = [g["gov"] for g in d.govs]
    assert ids == ["place-4715160", "county-47125", "sdu-4703030"]
    city, county, cmcss = d.govs
    for g in (city, county):
        assert (g["status"], g["platform"], g["items"]) == ("covered", "daylight", "shown")
    assert city["daylight"] == {"body": "city", "full_url": "city/"}
    assert county["daylight"]["body"] == "county"
    assert (cmcss["status"], cmcss["reason"], cmcss["items"]) == ("cant-cover", "blocks-readers", "withheld")
    assert cmcss["checked_doc"] == "docs/research/rpc-cmcss-sources.md"
    assert cmcss["official_url"] == cmcss["reason_url"] == "https://www.cmcss.net/"
    assert labels["reason.blocks-readers"] == "Its records site blocks automated readers."


def test_shipped_gov_flags_seed_b2():
    flags = nat.load_gov_flags()
    assert {"state": "09", "layer": "county", "show": False} in flags.rules      # Connecticut
    assert {"state": "44", "layer": "county", "show": False} in flags.rules      # Rhode Island
    ma = {i for i in flags.hide if i.startswith("county-25")}
    assert ma == {"county-25003", "county-25009", "county-25011", "county-25013", "county-25015", "county-25017",
                  "county-25019", "county-25025", "county-25027"}
    assert "county-25001" not in flags.hide and "county-25021" not in flags.hide   # Barnstable, Norfolk keep theirs
    assert flags.lines["place-4752006"] == "consolidated" and "place-4752006" in flags.hide
    assert "county-47037" in flags.show
    va = [i for i, line in flags.lines.items() if i.startswith("county-51")]
    assert len(va) == 38 and all(flags.lines[i] == "independent-city" for i in va)
    assert all(int(i[-3:]) >= 510 for i in va)            # VA pattern: county codes 510 and up are cities
    # every independent-city county equivalent is hidden, so the place card is the one card (UX: "One card")
    assert all(i in flags.hide for i, line in flags.lines.items() if line == "independent-city")


def test_valid_legistar_entry_with_host_ok_loads(tmp_path):
    d = load(tmp_path, LEGISTAR)
    assert d.govs[0]["legistar"]["client"] == "salem"


def test_missing_items_means_withheld(tmp_path):
    d = load(tmp_path, changed(COVERED, items=...))
    assert d.govs[0]["items"] == "withheld"


def test_also_same_layer_becomes_alias(tmp_path):
    # a re-coded GEOID keeps its id; the new GEOID, same layer, goes in `also` (3.1)
    e = changed(COVERED, also=["place-4715161"])
    assert load(tmp_path, e).alias == {"place-4715161": "place-4715160"}


@pytest.mark.parametrize("also", ["county-47125", "sdu-4703030", "cousub-4712590886"])
def test_also_cross_layer_refused(tmp_path, also):
    # privacy-withhold/also-cross-layer: a school district (or any other layer) never rides on a city's entry
    with pytest.raises(nat.NationalConfigError, match="also-cross-layer"):
        load(tmp_path, changed(COVERED, also=[also]))


# --- refusals (architecture 3.2), one per case -----------------------------------------------------------------

BAD = [
    ("unknown-entry-key", [changed(COVERED, notes="x")], "notes: unknown key"),
    ("unknown-platform-key", [changed(COVERED, daylight__extra=1)], "extra: unknown key"),
    ("bad-id-short", [changed(COVERED, gov="place-471516")], "gov: bad id"),
    ("bad-id-layer", [changed(COVERED, gov="town-4715160")], "gov: bad id"),
    ("bad-id-long", [changed(COVERED, gov="county-471250")], "gov: bad id"),
    ("bad-also-id", [changed(COVERED, also=["place-47"])], "also: bad id"),
    ("duplicate-gov", [COVERED, changed(COVERED, body_name="Other Council")], "duplicate id place-4715160"),
    ("duplicate-across-also", [COVERED, changed(CANT, also=["place-4715160"])], "duplicate id place-4715160"),
    ("missing-state", [changed(COVERED, state=...)], "state: missing"),
    ("unknown-state", [changed(COVERED, state="XX")], "state: must be a USPS"),
    ("lowercase-state", [changed(COVERED, state="tn")], "state: must be a USPS"),
    ("state-not-the-ids", [changed(COVERED, state="KY")], "KY does not match"),
    ("cant-cover-no-reason", [changed(CANT, reason=...)], "reason: a cant-cover entry needs"),
    ("cant-cover-no-reason-url", [changed(CANT, reason_url=...)], "reason_url: a cant-cover entry needs"),
    ("cant-cover-no-checked", [changed(CANT, checked=...)], "checked: missing"),
    ("covered-no-platform", [changed(COVERED, platform=..., daylight=...)], "platform: a covered entry needs"),
    ("covered-no-platform-keys", [changed(COVERED, daylight=...)], "daylight: missing platform keys"),
    ("daylight-no-full-url", [changed(COVERED, daylight__full_url=...)], "full_url: missing"),
    ("platform-keys-without-platform", [changed(CANT, daylight={"body": "x", "full_url": "x/"})],
     "daylight: platform keys without"),
    ("other-platforms-keys", [changed(COVERED, legistar=LEGISTAR["legistar"])], "legistar: keys for another"),
    ("unknown-platform", [changed(COVERED, platform="boarddocs", daylight=...)], "platform: unknown platform"),
    ("unknown-platform-keys", [changed(COVERED, platform="boarddocs", daylight=..., boarddocs={})], "unknown key"),
    ("http-official-url", [changed(COVERED, official_url="http://www.clarksvilletn.gov/")], "official_url: must be"),
    ("javascript-checked-url", [changed(COVERED, checked_url="javascript:alert(1)")], "checked_url: must be"),
    ("credentialed-reason-url", [changed(CANT, reason_url="https://u:p@www.cmcss.net/")], "reason_url: must be"),
    ("other-port-url", [changed(COVERED, official_url="https://www.clarksvilletn.gov:8443/")], "official_url"),
    ("unknown-reason", [changed(CANT, reason="too-hard")], "reason: unknown reason"),
    ("reason-on-covered", [changed(COVERED, reason="terms")], "reason: only a cant-cover"),
    ("bad-status", [changed(COVERED, status="soon")], "status: must be"),
    ("bad-checked-date", [changed(COVERED, checked="2026-13-01")], "checked: must be a date"),
    ("checked-url-and-doc", [changed(COVERED, checked_doc="docs/research/rpc-cmcss-sources.md")],
     "not both"),
    ("checked-doc-missing", [changed(CANT, checked_doc="docs/research/none.md")], "checked_doc: must be"),
    ("checked-doc-escape", [changed(CANT, checked_doc="docs/../CLAUDE.md")], "checked_doc: must be"),
    ("body-name-bidi", [changed(COVERED, body_name="City ‮Council")], "body_name: longer than"),
    ("body-name-empty", [changed(COVERED, body_name=" ")], "body_name: must be non-empty"),
    # privacy-withhold/national-prefix (finding 5, architecture section 11)
    ("items-shown-sdu", [changed(CANT, gov="sdu-4703030", items="shown")], "never allowed for a school"),
    ("items-shown-sds", [changed(CANT, gov="sds-4703030", items="shown")], "never allowed for a school"),
    ("items-shown-sde", [changed(CANT, gov="sde-4703030", items="shown")], "never allowed for a school"),
    ("items-shown-youth-council", [changed(COVERED, body_name="Clarksville Youth Council")],
     "general-purpose"),
    ("items-shown-school-board-under-city", [changed(COVERED, body_name="City School Board of Trustees")],
     "general-purpose"),
    ("items-shown-not-a-governing-body", [changed(COVERED, body_name="Clarksville Parks Department")],
     "general-purpose"),
    ("items-bad-value", [changed(COVERED, items="yes")], "items: must be shown or withheld"),
    # a YAML list or mapping where a word belongs is a config error, never a TypeError
    ("state-as-list", [changed(COVERED, state=["TN"])], "state: must be a USPS"),
    ("state-as-mapping", [changed(COVERED, state={"TN": 1})], "state: must be a USPS"),
    ("platform-as-list", [changed(COVERED, platform=["daylight"])], "platform: must be a platform name"),
    ("status-as-list", [changed(COVERED, status=["covered"])], "status: must be"),
    ("items-as-list", [changed(COVERED, items=["shown"])], "items: must be shown or withheld"),
    ("reason-as-list", [changed(CANT, reason=["terms"])], "reason: unknown reason"),
    # national/r5-not-enforced (finding 7) and the platform key checks
    ("legistar-no-host-ok", [changed(LEGISTAR, host_ok=...)], "host_ok: platform 'legistar' needs"),
    ("legistar-host-ok-no-link", [changed(LEGISTAR, host_ok={"date": "2026-12-01"})], "link: missing"),
    ("legistar-host-ok-http-link", [changed(LEGISTAR, host_ok__link="http://github.com/x")], "link: must be"),
    ("legistar-host-ok-bad-date", [changed(LEGISTAR, host_ok__date="soon")], "date: must be a date"),
    ("full-url-parent", [changed(COVERED, daylight__full_url="../city/")], "full_url: must be a site path"),
    ("full-url-dotdot-inside", [changed(COVERED, daylight__full_url="city/../../x")], "full_url: must be"),
    ("full-url-absolute", [changed(COVERED, daylight__full_url="/city/")], "full_url: must be"),
    ("full-url-scheme", [changed(COVERED, daylight__full_url="https://evil.example/")], "full_url: must be"),
    ("full-url-uppercase", [changed(COVERED, daylight__full_url="City/")], "full_url: must be"),
    ("daylight-bad-body", [changed(COVERED, daylight__body="City Council")], "body: must match"),
    ("legistar-bad-client", [changed(LEGISTAR, legistar__client="Salem!")], "client: must match"),
    ("legistar-short-client", [changed(LEGISTAR, legistar__client="s")], "client: must match"),
    ("legistar-no-client", [changed(LEGISTAR, legistar__client=...)], "client: missing"),
    ("legistar-bad-body-id", [changed(LEGISTAR, legistar__body_id="138")], "body_id: must be"),
    ("legistar-bad-tz", [changed(LEGISTAR, legistar__tz="America/Nowhere")], "tz: must be a time zone"),
    ("legistar-no-tz", [changed(LEGISTAR, legistar__tz=...)], "tz: missing"),
    ("final-statuses-not-list", [changed(LEGISTAR, legistar__final_statuses="Final")], "final_statuses"),
    ("final-statuses-unknown", [changed(LEGISTAR, legistar__final_statuses=["Final", "Draft"])], "final_statuses"),
    ("final-statuses-empty", [changed(LEGISTAR, legistar__final_statuses=[])], "final_statuses"),
    ("final-statuses-repeat", [changed(LEGISTAR, legistar__final_statuses=["Final", "Final"])], "final_statuses"),
    # every URL on a non-daylight entry is on the platform's hosts (finding 4)
    ("legistar-url-off-host", [changed(LEGISTAR, official_url="https://www.cityofsalem.net/")],
     "official_url: host is not a Legistar host"),
    ("legistar-url-other-client", [changed(LEGISTAR, checked_url="https://portland.legistar.com/")],
     "checked_url: host is not a Legistar host"),
]


@pytest.mark.parametrize("govs,match", [(g, m) for _, g, m in BAD], ids=[i for i, _, _ in BAD])
def test_directory_refuses(tmp_path, govs, match):
    with pytest.raises(nat.NationalConfigError, match=match):
        load(tmp_path, *govs)


# privacy-withhold/body-name-word-check: the governing-body phrase must end the name; no school, youth, child,
# pension or other special-purpose stem anywhere in it
NOT_GENERAL = ["Early Childhood Council", "Childcare Commission", "Schoolboard Commission", "Head Start Policy Council",
               "Junior Council", "Planning Commission", "Civil Service Commission", "Police Pension Board of Trustees",
               "Preschool City Council", "City Council Youth Advisory Board", "Clarksville Parks Department"]
GENERAL = ["Clarksville City Council", "Montgomery County Commission", "Town Board", "Arlington County Board",
           "Board of County Commissioners", "Board of Mayor and Aldermen", "Metropolitan Council"]


@pytest.mark.parametrize("name", NOT_GENERAL)
def test_items_shown_refused_for_body_name(tmp_path, name):
    with pytest.raises(nat.NationalConfigError, match="items: `shown` needs a body_name"):
        load(tmp_path, changed(COVERED, body_name=name))


@pytest.mark.parametrize("name", NOT_GENERAL)
def test_withheld_body_name_still_loads(tmp_path, name):
    assert load(tmp_path, changed(COVERED, body_name=name, items="withheld")).govs[0]["items"] == "withheld"


@pytest.mark.parametrize("name", GENERAL)
def test_items_shown_accepted_for_body_name(tmp_path, name):
    assert load(tmp_path, changed(COVERED, body_name=name)).govs[0]["items"] == "shown"


def test_shipped_shown_names_pass_the_word_check():
    d = nat.load_directory()
    assert {g["body_name"] for g in d.govs if g["items"] == "shown"} == {"Clarksville City Council",
                                                                        "Montgomery County Commission"}


def test_load_all_refuses_a_listed_government_in_hide(tmp_path):
    for name in ("directory.yml", "labels.yml", "gov-flags.yml"):
        (tmp_path / name).write_text((nat.NATIONAL_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    flags = yaml.safe_load((tmp_path / "gov-flags.yml").read_text(encoding="utf-8"))
    flags["hide"].append({"id": "county-47125", "why": "x", "source": SRC})
    (tmp_path / "gov-flags.yml").write_text(yaml.safe_dump(flags), encoding="utf-8")
    with pytest.raises(nat.NationalConfigError, match="county-47125 is in directory.yml"):
        nat.load_all(tmp_path)


def test_refuses_unknown_top_level_key(tmp_path):
    with pytest.raises(nat.NationalConfigError, match="extra: unknown key"):
        load(tmp_path, COVERED, extra=1)


def test_refuses_wrong_schema(tmp_path):
    p = tmp_path / "directory.yml"
    p.write_text("schema: daylight-directory/2\ngovs: []\n", encoding="utf-8")
    with pytest.raises(nat.NationalConfigError, match="schema"):
        nat.load_directory(p, LABELS)


def test_refuses_reason_without_label(tmp_path):
    labels = {k: v for k, v in LABELS.items() if k != "reason.blocks-readers"}
    with pytest.raises(nat.NationalConfigError, match="no label reason.blocks-readers"):
        load(tmp_path, CANT, labels=labels)


def test_reads_with_safe_load_only(tmp_path):
    p = tmp_path / "directory.yml"
    p.write_text("schema: daylight-directory/1\ngovs: !!python/object/apply:os.getcwd []\n", encoding="utf-8")
    with pytest.raises(nat.NationalConfigError, match="cannot read"):
        nat.load_directory(p, LABELS)


def test_error_names_the_entry(tmp_path):
    with pytest.raises(nat.NationalConfigError, match=r"govs\[1\] sdu-4703030: reason"):
        load(tmp_path, COVERED, changed(CANT, reason="nope"))


# --- gov-flags.yml and labels.yml ------------------------------------------------------------------------------

SRC = "https://www.census.gov/library/reference/code-lists/class-codes.html"


def write_flags(tmp_path, **parts):
    p = tmp_path / "gov-flags.yml"
    p.write_text(yaml.safe_dump({"schema": "daylight-govflags/1", **parts}), encoding="utf-8")
    return p


FLAG_BAD = [
    ("hidden-and-shown", {"hide": [{"id": "county-47037", "why": "x", "source": SRC}],
                          "show": [{"id": "county-47037", "why": "x", "source": SRC}]}, "both hidden and shown"),
    ("line-without-label", {"lines": [{"id": "place-4752006", "line": "merged", "why": "x", "source": SRC}]},
     "no label note.merged"),
    ("bad-id", {"hide": [{"id": "county-9110", "why": "x", "source": SRC}]}, "bad id"),
    ("no-source", {"hide": [{"id": "county-09110", "why": "x"}]}, "source: missing"),
    ("http-source", {"hide": [{"id": "county-09110", "why": "x", "source": "http://census.gov/"}]}, "source: must"),
    ("no-why", {"show": [{"id": "county-47037", "why": "", "source": SRC}]}, "why: must be non-empty"),
    ("duplicate-hide", {"hide": [{"id": "county-09110", "why": "x", "source": SRC}] * 2}, "duplicate id"),
    ("rule-state-not-fips", {"rules": [{"state": 9, "layer": "county", "show": False, "why": "x", "source": SRC}]},
     "state: must be a two-digit"),
    ("rule-bad-layer", {"rules": [{"state": "09", "layer": "counties", "show": False, "why": "x", "source": SRC}]},
     "layer: unknown"),
    ("rule-show-not-bool", {"rules": [{"state": "09", "layer": "county", "show": "no", "why": "x", "source": SRC}]},
     "show: must be true or false"),
    ("unknown-key", {"hide": [{"id": "county-09110", "why": "x", "source": SRC, "note": 1}]}, "note: unknown key"),
    ("unknown-part", {"alias": []}, "alias: unknown key"),
]


@pytest.mark.parametrize("parts,match", [(p, m) for _, p, m in FLAG_BAD], ids=[i for i, _, _ in FLAG_BAD])
def test_gov_flags_refuse(tmp_path, parts, match):
    with pytest.raises(nat.NationalConfigError, match=match):
        nat.load_gov_flags(write_flags(tmp_path, **parts), LABELS)


def test_labels_refuse_missing_slot(tmp_path):
    p = tmp_path / "labels.yml"
    labels = {k: v for k, v in LABELS.items() if k != "slot.cousub"}
    p.write_text(yaml.safe_dump({"schema": "daylight-labels/1", "labels": labels}), encoding="utf-8")
    with pytest.raises(nat.NationalConfigError, match="slot.cousub: missing"):
        nat.load_labels(p)


def test_labels_refuse_bad_key(tmp_path):
    p = tmp_path / "labels.yml"
    p.write_text(yaml.safe_dump({"schema": "daylight-labels/1", "labels": {**LABELS, "__proto__": "x"}}),
                 encoding="utf-8")
    with pytest.raises(nat.NationalConfigError, match="bad label key"):
        nat.load_labels(p)


# --- the page directory (3.4) ------------------------------------------------------------------------------------

def test_page_directory_shape():
    d, flags, labels = nat.load_all()
    last = {"place-4715160": "2026-11-19T14:02:00Z", "county-47125": "2026-11-17T14:02:00Z"}
    p = nat.page_directory(d, flags, labels, built_at=BUILT, last_ok_at=last)
    assert set(p) == {"schema", "built", "root", "govs", "alias", "hide", "show", "rules", "lines", "labels"}
    assert (p["schema"], p["built"], p["root"]) == ("daylight-pagedir/1", "2026-11-19", "../")
    assert p["govs"]["place-4715160"] == {"board": "Clarksville City Council", "status": "covered",
                                          "page": "digest/tn/place-4715160.html", "full": "city/", "stale": False}
    assert p["govs"]["county-47125"] == {"board": "Montgomery County Commission", "status": "covered",
                                         "page": "digest/tn/county-47125.html", "full": "meetings/agendas.html",
                                         "stale": False}
    assert p["govs"]["sdu-4703030"] == {
        "board": "Clarksville-Montgomery County School System Board of Education", "status": "cant-cover",
        "reason": "blocks-readers", "checked": "2026-11-10", "reason_url": "https://www.cmcss.net/",
        "official_url": "https://www.cmcss.net/"}
    assert p["rules"] == [{"state": "09", "layer": "county", "show": False},
                          {"state": "44", "layer": "county", "show": False}]
    assert p["lines"]["place-4752006"] == "consolidated" and p["lines"]["county-51760"] == "independent-city"
    assert "county-25017" in p["hide"] and p["show"] == ["county-47037"]
    assert p["labels"] == labels and p["alias"] == {}
    # no curated `why` or `source` text and no item text reaches the browser
    assert "why" not in json.dumps(p) and "source" not in json.dumps(p) and "items" not in json.dumps(p)


@pytest.mark.parametrize("last,stale", [(None, True), ("not a time", True), ("2026-11-16T14:59:00Z", True),
                                        ("2026-11-16T15:00:00Z", False), ("2026-11-19T14:00:00+00:00", False)])
def test_page_directory_stale(last, stale):
    d = nat.Directory(govs=(dict(COVERED, checked=None),))
    p = nat.page_directory(d, nat.GovFlags(), LABELS, built_at=BUILT, last_ok_at={"place-4715160": last})
    assert p["govs"]["place-4715160"]["stale"] is stale


def test_page_directory_is_pure():
    d, flags, labels = nat.load_all()
    before = copy.deepcopy((d.govs, flags.lines, labels))
    a = nat.page_directory(d, flags, labels, built_at=BUILT, last_ok_at={})
    a["govs"].clear()
    a["labels"].clear()
    b = nat.page_directory(d, flags, labels, built_at=BUILT, last_ok_at={})
    assert b["govs"] and b["labels"] and (d.govs, flags.lines, labels) == before


@pytest.mark.parametrize("root", ["/", "https://x/", "..", "./", "../x/"])
def test_page_directory_refuses_bad_root(root):
    with pytest.raises(ValueError):
        nat.page_directory(nat.Directory(govs=()), nat.GovFlags(), LABELS, built_at=BUILT, last_ok_at={}, root=root)


def test_page_directory_refuses_naive_time():
    with pytest.raises(ValueError):
        nat.page_directory(nat.Directory(govs=()), nat.GovFlags(), LABELS, built_at=BUILT.replace(tzinfo=None),
                           last_ok_at={})


def test_bad_page_path_refused():
    with pytest.raises(nat.NationalConfigError, match="page"):
        nat.gov_page({"gov": "place-4715160", "state": "../TN"})


def test_embed_json_is_tojson_safe():
    hostile = {"labels": {"note.x": "</script><script>alert('x')</script> &  "}}
    text = nat.embed_json(hostile)
    assert not any(c in text for c in "<>&' ")
    assert json.loads(text) == hostile


def test_embedded_directory_stays_small():
    d, flags, labels = nat.load_all()
    text = nat.embed_json(nat.page_directory(d, flags, labels, built_at=BUILT, last_ok_at={}))
    assert len(text.encode()) < 60_000          # 3.4: above about 60 KB it moves to digest/pagedir.json


# --- MAX_ANSWER (security "needs verification": 20 matches x 6 layers) -----------------------------------------

def _unit(layer_code: str, geoid: str, name: str) -> dict:
    """One layer unit with every field the recorded answer carries (docs/platform-facts.md "Census geocoder") plus
    the usual extras, at the longest realistic widths."""
    return {"OBJECTID": 123456, "OID": "27590335395836", "GEOID": geoid, "NAME": name, "BASENAME": name,
            "STATE": geoid[:2], layer_code: geoid[2:], "FUNCSTAT": "A", "LSADC": "25", "CLASSCC": "C1",
            "MTFCC": "G4110", "AREALAND": 2_501_234_567, "AREAWATER": 123_456_789, "CENTLAT": "+36.5683296",
            "CENTLON": "-087.3510374", "INTPTLAT": "+36.5664516", "INTPTLON": "-087.3490853", "UR": "",
            "LOGRADE": "PK", "HIGRADE": "12", "SDTYP": "", "LSAD": "25", "STATENS": "01325873",
            "COUNTYNS": "01639772", "PLACENS": "02404071", "GEOIDFQ": "1600000US" + geoid}


def _match(n: int) -> dict:
    name = "Clarksville-Montgomery County School System Unified District"     # 59 characters, longer than most
    layers = {"Incorporated Places": [_unit("PLACE", "4715160", name)],
              "Counties": [_unit("COUNTY", "47125", name)],
              "County Subdivisions": [_unit("COUSUB", "4712590886", name)],
              "Unified School Districts": [_unit("SDUNI", "4703030", name)],
              "Secondary School Districts": [_unit("SDSEC", "4703031", name)],
              "Elementary School Districts": [_unit("SDELM", "4703032", name)]}
    return {"matchedAddress": f"{1000 + n} NORTH SECOND STREET EXTENSION, CLARKSVILLE, TN, 37040",
            "coordinates": {"x": -87.361481272763, "y": 36.527643783069},
            "tigerLine": {"tigerLineId": "57681742", "side": "L"},
            "addressComponents": {"fromAddress": "1000", "toAddress": "1098", "preQualifier": "", "preDirection": "N",
                                  "preType": "", "streetName": "SECOND STREET EXTENSION", "suffixType": "ST",
                                  "suffixDirection": "", "suffixQualifier": "", "city": "CLARKSVILLE", "state": "TN",
                                  "zip": "37040"},
            "geographies": layers}


def test_max_answer_fits_20_matches_of_6_layers():
    answer = {"result": {"input": {"address": {"address": "x" * 200},
                                   "benchmark": {"id": "4", "benchmarkName": "Public_AR_Current",
                                                 "benchmarkDescription": "Public Address Ranges - Current Benchmark",
                                                 "isDefault": True},
                                   "vintage": {"id": "4", "vintageName": "Current_Current",
                                               "vintageDescription": "Current Vintage - Current Benchmark",
                                               "isDefault": True}},
                         "addressMatches": [_match(n) for n in range(nat.MAX_MATCHES)]}}
    size = len(json.dumps(answer, separators=(",", ":")))
    assert nat.MAX_ANSWER == 220_000
    assert size * 1.3 < nat.MAX_ANSWER, size      # room for fields the Census adds later
    one = len(json.dumps(_match(0), separators=(",", ":")))
    assert one < nat.ANSWER_LAYERS * nat.UNIT_CHARS + nat.MATCH_CHARS


def test_independent_city_line_ids_are_county_equivalents():
    flags = nat.load_gov_flags()
    assert all(i.startswith("county-") for i, line in flags.lines.items() if line == "independent-city")
    assert set(flags.lines) - set(flags.hide) == set()     # each line's id is hidden: no duplicate card


def test_now_is_not_read():
    # the builder passes the build instant in; a later instant only changes `built` and `stale`
    d = nat.Directory(govs=(dict(COVERED, checked=None),))
    later = BUILT + timedelta(days=10)
    p = nat.page_directory(d, nat.GovFlags(), LABELS, built_at=later, last_ok_at={"place-4715160": "2026-11-19T14:00:00Z"})
    assert p["built"] == "2026-11-29" and p["govs"]["place-4715160"]["stale"] is True
