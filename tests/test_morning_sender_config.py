# ruff: noqa: E501
"""The sender's config block and its guards (T4.3: config/site.yml `morning_note.sender`, sitegen/morning.py
sender_problems(); sender/settings.py, the deliver stage's reader that needs no PyYAML)."""
import copy
from pathlib import Path

import pytest
import yaml

from sitegen import config, morning
from sitegen.build import site_url_problems
from sender import settings as settings_mod

ROOT = Path(__file__).resolve().parent.parent
SITE_YML = ROOT / "config" / "site.yml"
FORM_ON = {"enabled": True, "provider": "Example Mail", "form_action": "https://example.com/subscribe",
           "privacy_url": "https://example.com/privacy"}


def problems(sender=None, note=None, site_url="https://records.example.com/", drop=()):
    cfg = copy.deepcopy(config.SITE)
    cfg["alerts"]["site_url"] = site_url
    cfg["morning_note"].update(note or {})
    cfg["morning_note"]["sender"].update(sender or {})
    for k in drop:
        del cfg["morning_note"]["sender"][k]
    return morning.problems(cfg)


def test_the_shipped_block_is_off_and_clean():
    s = yaml.safe_load(SITE_YML.read_text(encoding="utf-8"))["morning_note"]["sender"]   # the file, not the env
    assert s == {"enabled": False, "provider": "buttondown", "api_base": "https://api.buttondown.com/v1",
                 "mode": "stamp", "send_at": "07:00", "latest_send": "10:00", "max_editions": 80,
                 "max_recipients": 2000, "canary_only": True, "link_hosts": s["link_hosts"], "text": s["text"]}
    assert sorted(s["text"]) == ["open_site", "subject", "why"]
    assert morning.problems(config.SITE) == [] and site_url_problems(config.SITE) == []
    assert tuple(s) == morning.SENDER_KEYS


def test_the_form_sends_lists_where_the_sender_reads_them_and_the_page_promises_no_exact_time():
    """task-contract/t43-form-fields: the deliver stage reads a subscriber's lists from `metadata.lists`; a form that
    sent them as tags would reach nobody while the run says "sent". `ids` mode mails when the run ends, so the page
    says "by 7:00 AM", true in both modes."""
    mn = yaml.safe_load(SITE_YML.read_text(encoding="utf-8"))["morning_note"]
    assert mn["form_fields"]["lists"] == "metadata__lists"
    assert "by 7:00 AM" in mn["page"]["about"] and "at 7:00 AM" not in mn["page"]["about"]


def test_no_secret_or_address_is_in_the_config():
    raw = SITE_YML.read_text(encoding="utf-8")
    block = raw[raw.index("  sender:"):raw.index("  page:")]
    assert "@" not in block and "token" not in block.lower() and "api_key" not in block.lower()


def test_enabling_the_sender_needs_the_form_enabled_and_a_site_url():
    assert problems() == []                                              # off: clean with or without a site URL
    assert problems(site_url="") == []
    off_form = problems({"enabled": True})
    assert any("morning_note.enabled must be true" in p for p in off_form)
    no_url = problems({"enabled": True}, FORM_ON, site_url="")
    assert no_url and all("site_url" in p for p in no_url)
    hosts = config.SITE["morning_note"]["sender"]["link_hosts"] + ",records.example.com"
    assert problems({"enabled": True, "link_hosts": hosts}, FORM_ON) == []
    cfg = copy.deepcopy(config.SITE)                                     # and the build's own check refuses it
    cfg["morning_note"]["sender"]["enabled"] = True
    assert any("morning_note.sender.enabled" in p for p in site_url_problems(cfg))


@pytest.mark.parametrize("change, word", [
    ({"api_base": "http://api.buttondown.com/v1"}, "api_base"), ({"api_base": ""}, "api_base"),
    ({"api_base": "https://api.example.com/v1?x=1"}, "api_base"), ({"api_base": "https://user@example.com/"}, "api_base"),
    ({"mode": "everyone"}, "mode"), ({"mode": None}, "mode"),
    ({"send_at": "7:00"}, "send_at"), ({"send_at": "07:00:00"}, "send_at"), ({"send_at": 700}, "send_at"),
    ({"latest_send": "25:00"}, "latest_send"), ({"send_at": "10:00"}, "before latest_send"),
    ({"send_at": "11:00"}, "before latest_send"),
    ({"max_editions": 0}, "max_editions"), ({"max_editions": "80"}, "max_editions"), ({"max_editions": True}, "max_editions"),
    ({"max_recipients": -1}, "max_recipients"), ({"max_recipients": 1.5}, "max_recipients"),
    ({"enabled": "false"}, "enabled"), ({"enabled": None}, "enabled"), ({"canary_only": "no"}, "canary_only"),
    ({"provider": ""}, "provider"), ({"text": "words"}, "text"),
    ({"text": {"subject": "No marks", "why": "w", "open_site": "o"}}, "{site_name}"),
    ({"text": {"subject": "{site_name} {date}", "why": "", "open_site": "o"}}, "text.why"),
    ({"text": {"subject": "{site_name} {date}", "why": "w", "open_site": "o", "footer": "x"}}, "text.footer is not a known key"),
    ({"api_key": "x"}, "api_key is not a known key"), ({"recipients": ["x"]}, "recipients is not a known key")])
def test_shape_checks_apply_even_while_off(change, word):
    got = problems(change)
    assert got and any(word in p for p in got), got


@pytest.mark.parametrize("key", morning.SENDER_KEYS)
def test_every_key_must_be_set(key):
    assert f"morning_note.sender.{key} must be set" in problems(drop=[key])


def test_the_block_may_be_left_out_and_must_be_a_mapping():
    cfg = copy.deepcopy(config.SITE)
    del cfg["morning_note"]["sender"]
    assert morning.problems(cfg) == []
    cfg["morning_note"]["sender"] = ["enabled"]
    assert morning.problems(cfg) == ["morning_note.sender must be a mapping"]


# ------------------------------------------------------------------ the deliver stage's reader (no PyYAML)
def test_the_stdlib_reader_agrees_with_yaml_on_the_shipped_file():
    got = settings_mod.parse(SITE_YML.read_text(encoding="utf-8"))
    full = yaml.safe_load(SITE_YML.read_text(encoding="utf-8"))
    assert got["sender"] == {k: v for k, v in full["morning_note"]["sender"].items() if k != "text"}
    assert got["top"] == {k: full[k] for k in ("site_timezone", "district_count", "ward_count", "support_url")}
    s = settings_mod.load(SITE_YML)
    assert (s.enabled, s.canary_only, s.mode, s.max_recipients, s.timezone) == (False, True, "stamp", 2000, "America/Chicago")
    assert (s.district_count, s.ward_count, s.send_at, s.latest_send) == (21, 12, "07:00", "10:00")


BASE = """site_timezone: America/Chicago   # a comment
district_count: 21
ward_count: 12
other:
  sender:
    enabled: true
morning_note:
  enabled: false
  lists:
    - {key: zoning, label: Zoning}
  sender:
    enabled: false
    provider: buttondown
    api_base: https://api.buttondown.com/v1
    mode: stamp              # stamp | ids
    send_at: "07:00"
    latest_send: '10:00'     # late
    max_editions: 80
    max_recipients: 2000
    canary_only: true
    link_hosts: "example.com,www.cmcrpc.com"
    text:
      enabled: true
      subject: "{site_name} morning note, {date}"
  page:
    enabled: true
    mode: ids
"""


def test_the_reader_takes_only_the_sender_block():
    s = settings_mod.from_values(**settings_mod.parse(BASE))
    assert s.enabled is False and s.mode == "stamp" and s.latest_send == "10:00" and s.canary_only is True
    assert yaml.safe_load(BASE)["morning_note"]["sender"]["latest_send"] == "10:00"


@pytest.mark.parametrize("old, new", [
    ("    enabled: false\n    provider", "    provider"),                            # a key is missing
    ("    enabled: false\n    provider", "    enabled: yes\n    provider"),          # not true/false
    ("    enabled: false\n    provider", "    enabled: false\n    enabled: true\n    provider"),   # set twice
    ("    enabled: false\n    provider", "    enabled:\n    provider"),              # no value
    ("    canary_only: true", "    canary_only: [true]"),
    ("    mode: stamp ", "    mode: all "), ("    max_recipients: 2000", "    max_recipients: 0"),
    ("    max_recipients: 2000", "    max_recipients: lots"),
    ("https://api.buttondown.com/v1", "http://api.buttondown.com/v1"),
    ("https://api.buttondown.com/v1", "https://api.buttondown.com/v1?to=https://evil.example.com"),
    ("    send_at: \"07:00\"", "    send_at: \"7am\""), ("    send_at: \"07:00\"", "    send_at: \"12:00\""),
    ("    send_at: \"07:00\"", "    send_at: \"07:00"),                              # an open quote
    ("  sender:\n    enabled: false", "  sender: {enabled: false}\n  x:"),          # flow style: not read, so missing
    ("district_count: 21", "district_count: many"), ("site_timezone: America/Chicago   # a comment\n", "")])
def test_anything_the_reader_cannot_read_is_an_error_never_a_guess(old, new):
    assert old in BASE
    with pytest.raises(settings_mod.SettingsError):
        settings_mod.from_values(**settings_mod.parse(BASE.replace(old, new, 1)))


SENDER_END = "    canary_only: true\n"
PAGE = "  page:\n"


# settings-parity/unmatched-line-skipped: every one of these reads differently in PyYAML (or not at all), so the
# reader must refuse the file rather than skip the line it does not understand.
@pytest.mark.parametrize("old, new", [
    (SENDER_END, SENDER_END + "    \"enabled\": true\n"),                         # a quoted key
    (SENDER_END, SENDER_END + "    'canary_only': false\n"),
    (SENDER_END, SENDER_END + "    enabled : true\n"),                            # a space before the colon
    (SENDER_END, SENDER_END + "    ? canary_only\n    : false\n"),               # the explicit-key form
    (SENDER_END, SENDER_END + "    <<: {canary_only: false}\n"),                  # a merge key
    (PAGE, "  sender: {enabled: true}\n" + PAGE),                                  # a second sender, flow style
    (PAGE, "  sender:\n    enabled: true\n" + PAGE),                              # a second sender, block style
    ("  sender:\n    enabled: false", "  sender: &s\n    enabled: false"),        # sender must be a plain block
    ("  sender:\n    enabled: false", "  \"sender\":\n    enabled: false"),
    (BASE[-20:], BASE[-20:] + "morning_note:\n  sender:\n    enabled: true\n"),   # a second morning_note
    (BASE[-20:], BASE[-20:] + "\"morning_note\":\n  sender:\n    enabled: true\n"),
    (BASE[-20:], BASE[-20:] + "? morning_note\n: {sender: {enabled: true}}\n"),
    ("    max_recipients: 2000", "    max_recipients: 0100"),                     # PyYAML reads 64
    ("    max_recipients: 2000", "    max_recipients: 1_000"), ("    max_recipients: 2000", "    max_recipients: 0x10"),
    ("    max_recipients: 2000", "    max_recipients: 2000.0"), ("    max_recipients: 2000", "    max_recipients: +2000"),
    ("    max_editions: 80", "    max_editions: 1:20"),                           # sexagesimal: PyYAML reads 80
    ("    send_at: \"07:00\"", "    send_at: 07:00"), ("    latest_send: '10:00'", "    latest_send: 10:00"),
    ("    provider: buttondown", "    provider: yes"), ("    provider: buttondown", "    provider: null"),
    ("    provider: buttondown", "    provider: ~"), ("    provider: buttondown", "    provider: On"),
    ("    send_at: \"07:00\"", "    send_at: \"07:\\x30\""),                     # an escape PyYAML would expand
    ("    latest_send: '10:00'", "    latest_send: '10:''00'"),
    ("    enabled: false\n", "    enabled: false\x0b    enabled: true\n"),          # VT: a line break to splitlines()
    ("    enabled: false\n", "    enabled: false\x1c\n"),
    ("    enabled: false\n", "    enabled: false\r    enabled: true\n"),
    ("    enabled: false\n", "    enabled: false\u200b\n"),
    ("    enabled: false\n    provider", "    enabled: false\n     canary_only: false\n    provider"),   # deeper: continues a value
    ("    provider: buttondown", "   provider: buttondown"),                       # an indent no sibling has
    ("    provider: buttondown", "\tprovider: buttondown"),
    (SENDER_END, SENDER_END + "    - enabled: true\n"),
    ("    send_at: \"07:00\"", "    send_at: \"07:00\n      \""),                 # a value over two lines
    ("  lists:\n    - {key: zoning, label: Zoning}", "  lists:\n    - {key: zoning,\n  sender: x}"),
    ("site_timezone: America/Chicago   # a comment", "site_timezone: America/Chicago\nsite_timezone: Europe/Paris"),
    ("site_timezone: America/Chicago   # a comment", "site_timezone:\n  x: 1")])
def test_a_file_the_two_readers_could_read_differently_is_refused(old, new):
    """Refused means: the deliver reader raises, or PyYAML cannot load it (the site cannot build at all), or
    parity() names a difference (the build and the plan fail)."""
    assert old in BASE
    assert refused(BASE.replace(old, new, 1))


def refused(text: str) -> bool:
    try:
        settings_mod.parse(text)
    except settings_mod.SettingsError:
        return True
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError:
        return True
    return bool(settings_mod.parity(text, loaded))


# The sender block and the three top-level keys stay strict: the reader itself refuses these, whatever PyYAML says.
@pytest.mark.parametrize("old, new", [
    (SENDER_END, SENDER_END + "    \"enabled\": true\n"), (SENDER_END, SENDER_END + "    enabled : true\n"),
    (SENDER_END, SENDER_END + "    ? canary_only\n    : false\n"), (SENDER_END, SENDER_END + "    <<: {canary_only: false}\n"),
    (SENDER_END, SENDER_END + "    - enabled: true\n"), (PAGE, "  sender: {enabled: true}\n" + PAGE),
    (PAGE, "  sender:\n    enabled: true\n" + PAGE), ("  sender:\n    enabled: false", "  sender: &s\n    enabled: false"),
    ("    max_recipients: 2000", "    max_recipients: 0100"), ("    send_at: \"07:00\"", "    send_at: 07:00"),
    ("    provider: buttondown", "    provider: yes"), ("    enabled: false\n", "    enabled: false\u200b\n"),
    ("    enabled: false\n", "    enabled: false\x0b    enabled: true\n"),
    ("    enabled: false\n    provider", "    enabled: false\n     canary_only: false\n    provider"),
    ("    provider: buttondown", "   provider: buttondown"), ("    send_at: \"07:00\"", "    send_at: \"07:00\n      \""),
    ("    enabled: false\n", "    enabled: false\n    enabled: true\n"),
    ("site_timezone: America/Chicago   # a comment", "site_timezone: America/Chicago\nsite_timezone: Europe/Paris"),
    ("district_count: 21", "district_count: 021"), ("district_count: 21", "district_count: 21\u200b")])
def test_the_sender_block_and_its_top_level_keys_stay_strict(old, new):
    assert old in BASE
    with pytest.raises(settings_mod.SettingsError):
        settings_mod.parse(BASE.replace(old, new, 1))


# settings-parity/too-strict-daily-outage: valid YAML outside the sender block (and its folded text) must never stop
# the daily build. Each reads the same in both readers.
@pytest.mark.parametrize("old, new", [
    ("  page:\n    enabled: true", "  page:\n    about: >-\n      folded text\n      over two lines\n    enabled: true"),
    ("  page:\n    enabled: true", "  page:\n    about: a plain value\n      continued here\n    enabled: true"),
    ("  page:\n    enabled: true", "  page:\n    heading: \"a quoted value\n      over two lines\"\n    enabled: true"),
    ("  page:\n    enabled: true", "  page:\n    \"quoted-key\": x\n    hyphen-key: y\n    enabled: true"),
    ("  lists:\n    - {key: zoning, label: Zoning}", "  lists:\n  - {key: zoning, label: Zoning}"),
    ("other:\n", "flow: {a: 1,\n  b: 2}\nother:\n"),
    ("      subject: \"{site_name} morning note, {date}\"", "      subject: \"{site_name} morning note, {date}\"\n      why: >-\n        You get\n        this note."),
    ("  page:\n", "  # a comment with a zero\u200bwidth space and a \u200d joiner\n  page:\n"),
    ("site_timezone: America/Chicago   # a comment", "# top comment \u200b\nsite_timezone: America/Chicago   # a comment"),
    ("    enabled: true\n    mode: ids", "    enabled: true\n    label: \"Zoning\u200dnear me\"\n    mode: ids"),
    ("    enabled: false\n", "    enabled: false\u2028"), ("    enabled: false\n", "    enabled: false\x85")])
def test_valid_yaml_outside_the_sender_values_is_accepted(old, new):
    assert old in BASE
    text = BASE.replace(old, new, 1)
    loaded = yaml.safe_load(text)
    assert settings_mod.parity(text, loaded) == [], settings_mod.parity(text, loaded)
    assert settings_mod.from_values(**settings_mod.parse(text)).mode == "stamp"


@pytest.mark.parametrize("change", [
    lambda s: s.replace("  page:\n", "  page:\n    folded: >-\n      some folded\n      text\n", 1),
    lambda s: s.replace("  page:\n", "  # zero\u200bwidth in a comment\n  page:\n", 1),
    lambda s: "\ufeff" + s])
def test_the_build_check_accepts_valid_yaml_elsewhere_in_the_shipped_file(tmp_path, change):
    path = tmp_path / "site.yml"
    path.write_text(change(SITE_YML.read_text(encoding="utf-8")), encoding="utf-8")
    assert morning.reader_problems(path) == []


def test_line_endings_and_a_byte_order_mark_read_the_same():
    want = settings_mod.parse(BASE)
    assert settings_mod.parse(BASE.replace("\n", "\r\n")) == want
    assert settings_mod.parse("\ufeff" + BASE) == want


def test_parity_with_pyyaml_on_the_shipped_file():
    text = SITE_YML.read_text(encoding="utf-8")
    assert settings_mod.parity(text, yaml.safe_load(text)) == []


@pytest.mark.parametrize("path, value", [
    (("morning_note", "sender", "enabled"), True), (("morning_note", "sender", "canary_only"), False),
    (("morning_note", "sender", "max_recipients"), 64), (("morning_note", "sender", "max_recipients"), "2000"),
    (("morning_note", "sender", "enabled"), 0), (("ward_count",), 13)])
def test_parity_names_any_value_pyyaml_reads_differently(path, value):
    text = SITE_YML.read_text(encoding="utf-8")
    loaded = yaml.safe_load(text)
    node = loaded
    for k in path[:-1]:
        node = node[k]
    node[path[-1]] = value
    got = settings_mod.parity(text, loaded)
    assert len(got) == 1 and path[-1] in got[0], got


def test_parity_reports_a_file_the_reader_refuses():
    text = SITE_YML.read_text(encoding="utf-8").replace("    canary_only: true", "    \"canary_only\": false", 1)
    got = settings_mod.parity(text, yaml.safe_load(text))
    assert got and "sender/settings.py" in got[0]


def test_the_build_refuses_a_config_the_reader_reads_differently(tmp_path, monkeypatch):
    from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS
    from sitegen.build import BuildError, build
    bad = tmp_path / "site.yml"
    bad.write_text(SITE_YML.read_text(encoding="utf-8").replace("    max_recipients: 2000", "    max_recipients: 0100"),
                   encoding="utf-8")
    assert morning.reader_problems(SITE_YML) == []
    assert morning.reader_problems(bad)
    monkeypatch.setattr(config, "SITE_CONFIG_PATH", bad)
    with pytest.raises(BuildError, match="sender/settings.py"):
        build(FIXTURE, tmp_path / "s", seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS)


def test_the_plan_command_refuses_a_config_the_reader_reads_differently(tmp_path, monkeypatch, capsys):
    from sender.__main__ import main
    cfg = copy.deepcopy(config.SITE)
    cfg["morning_note"]["sender"]["canary_only"] = False       # what PyYAML gave is not what the deliver job reads
    monkeypatch.setattr(config, "SITE", cfg)
    assert main(["plan", "--site", str(tmp_path / "site"), "--out", str(tmp_path / "out")]) == 2
    assert "canary_only" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("base", [
    "https://api.buttondown.com.evil.example/v1", "https://evil.example/v1", "https://api.buttondown.com:8443/v1",
    "https://API.buttondown.com/v1", "https://xapi.buttondown.com/v1", "https://buttondown.com/v1",
    "https://api.buttondown.com./v1",
    # settings/api-base-path: the path is the provider's API root, exactly
    "https://api.buttondown.com/v1/../x", "https://api.buttondown.com/v1/..", "https://api.buttondown.com/v2",
    "https://api.buttondown.com/", "https://api.buttondown.com", "https://api.buttondown.com/v1/",
    "https://api.buttondown.com/v1/emails"])
def test_api_base_is_pinned_to_the_providers_own_host(base):
    """settings/api-base-host: the host the key is sent to is fixed in code per provider, not taken from config."""
    with pytest.raises(settings_mod.SettingsError, match="api_base"):
        settings_mod.from_values(**settings_mod.parse(BASE.replace("https://api.buttondown.com/v1", base, 1)))
    assert any("api_base" in p for p in problems({"api_base": base}))


def test_an_unknown_provider_has_no_host_and_is_refused():
    with pytest.raises(settings_mod.SettingsError, match="provider"):
        settings_mod.from_values(**settings_mod.parse(BASE.replace("provider: buttondown", "provider: elsewhere", 1)))
    assert any("provider" in p for p in problems({"provider": "elsewhere"}))
    assert settings_mod.PROVIDER_HOSTS == {"buttondown": "api.buttondown.com"}


def test_a_missing_config_file_is_an_error(tmp_path):
    with pytest.raises(settings_mod.SettingsError):
        settings_mod.load(tmp_path / "nope.yml")


def test_reader_and_build_checks_use_the_same_rules():
    assert settings_mod.SCALARS + ("text",) == morning.SENDER_KEYS
    assert settings_mod._API_BASE.pattern == morning._API_BASE.pattern



# ------------------------------------------------------------------ plan-untrusted/body-unchecked: link hosts
def test_the_link_hosts_cover_every_collector_source_and_the_support_link():
    import re as re_mod
    hosts = set(yaml.safe_load(SITE_YML.read_text(encoding="utf-8"))["morning_note"]["sender"]["link_hosts"].split(","))
    seen = set()
    for path in config.SITE["morning_note"]["manifests"]:
        seen |= set(re_mod.findall(r"https://([A-Za-z0-9.-]+)", (ROOT / path).read_text(encoding="utf-8")))
    assert seen and seen <= hosts, seen - hosts
    # Low (a): anyone can host a page on the support link's host, so that host is not a link host; the one
    # support URL is allowed exactly instead (settings.link_urls, from the top-level support_url)
    assert config.SITE["support_url"].split("/")[2] not in hosts
    assert set(settings_mod.load(SITE_YML).link_hosts) == hosts          # the deliver stage reads the same list
    assert settings_mod.load(SITE_YML).link_urls == (config.SITE["support_url"],)


@pytest.mark.parametrize("value", ["http://tips.example.com/", "https://user" + "@tips.example.com/",
                                   "https://tips.example.com:444/", 'https://tips.example.com/"x', "tips.example.com",
                                   "https://Tips.example.com/", 7])
def test_a_support_url_the_deliver_stage_could_not_allow_exactly_is_refused(value):
    got = settings_mod.parse(SITE_YML.read_text(encoding="utf-8"))
    with pytest.raises(settings_mod.SettingsError, match="support_url"):
        settings_mod.from_values({**got["top"], "support_url": value}, got["sender"])
    assert any("support_url" in p for p in morning.sender_problems({**config.SITE, "support_url": value}))


def test_no_support_url_allows_no_exact_link():
    got = settings_mod.parse(SITE_YML.read_text(encoding="utf-8"))
    top = {k: v for k, v in got["top"].items() if k != "support_url"}
    assert settings_mod.from_values(top, got["sender"]).link_urls == ()


@pytest.mark.parametrize("value", ["", "Example.com", "a..b", "https://example.com", "example.com/x", "ex ample.com",
                                   "example.com,", "-a.example", "localhost"])
def test_a_malformed_link_host_list_is_refused(value):
    assert any("link_hosts" in p for p in problems({"link_hosts": value}))
    with pytest.raises(settings_mod.SettingsError, match="link_hosts"):
        settings_mod.from_values(**{**settings_mod.parse(SITE_YML.read_text(encoding="utf-8")),
                                    "sender": {**settings_mod.parse(SITE_YML.read_text(encoding="utf-8"))["sender"],
                                               "link_hosts": value}})


def test_enabling_needs_the_site_host_among_the_link_hosts():
    got = problems({"enabled": True}, FORM_ON)
    assert any("link_hosts" in p and "records.example.com" in p for p in got), got
    base = config.SITE["morning_note"]["sender"]["link_hosts"]
    assert problems({"enabled": True, "link_hosts": base + ",records.example.com"}, FORM_ON) == []
