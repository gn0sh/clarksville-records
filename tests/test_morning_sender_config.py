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
                 "max_recipients": 2000, "canary_only": True, "text": s["text"]}
    assert sorted(s["text"]) == ["open_site", "subject", "why"]
    assert morning.problems(config.SITE) == [] and site_url_problems(config.SITE) == []
    assert tuple(s) == morning.SENDER_KEYS


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
    assert problems({"enabled": True}, FORM_ON) == []
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
    assert got["top"] == {k: full[k] for k in ("site_timezone", "district_count", "ward_count")}
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


def test_a_missing_config_file_is_an_error(tmp_path):
    with pytest.raises(settings_mod.SettingsError):
        settings_mod.load(tmp_path / "nope.yml")


def test_reader_and_build_checks_use_the_same_rules():
    assert settings_mod.SCALARS + ("text",) == morning.SENDER_KEYS
    assert settings_mod._API_BASE.pattern == morning._API_BASE.pattern
