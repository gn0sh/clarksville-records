"""sitegen picks the city (ADR 0012 decision 1, task T3; problem family city-only/clarksville-identical).

`python -m sitegen --city <slug>` reads --city before sitegen.config is imported and sets DAYLIGHT_CITY; a clash
with the variable, or with the city this process already loaded, exits 2. Clarksville's settings and PRIMARY equal
today's literals, and its build is byte-identical with and without --city (tests/test_clarksville_identical.py).
A city-only build itself comes later (T6); here only the settings it would read are checked. No network.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sitegen import config  # noqa: E402
from sitegen.build import BuildError, build  # noqa: E402

FIXTURE = ROOT / "site" / "fixtures" / "facts.sample.json"


def run(*args, city_env=None):
    env = {k: v for k, v in os.environ.items() if k != "DAYLIGHT_CITY"}
    if city_env:
        env["DAYLIGHT_CITY"] = city_env
    return subprocess.run([sys.executable, "-m", "sitegen", *args], cwd=ROOT, capture_output=True, text=True, env=env)


def probe(slug: str) -> dict:
    """sitegen.config as a fresh process loads it for one city (its settings are read once, at import)."""
    code = ("import json; from sitegen import config as c; print(json.dumps({'city': c.CITY, 'primary': c.PRIMARY, "
            "'paths': [None if p is None else str(p) for p in (c.COUNTY_AGENDAS, c.SEATS_PATH, c.DISTRICTS_PATH, "
            "c.FIN_LOCALITY_PATH)], 'councils': len(c.COUNCILS), 'locality': c.LOCALITY, 'capital': c.CAPITAL_FUND, "
            "'site_name': c.SITE_NAME, 'live': c.SITE['live'], 'legacy': c.LEGACY_SETTINGS}))")
    env = {**{k: v for k, v in os.environ.items() if k != "DAYLIGHT_CITY"}, "DAYLIGHT_CITY": slug}
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_help_names_the_city_flag_with_and_without_it():
    plain = run("--help")
    assert plain.returncode == 0 and "--city" in plain.stdout and "--facts FACTS --out OUT" in plain.stdout
    city = run("--city", "murfreesboro-tn", "--help")
    assert city.returncode == 0 and "[--facts FACTS] [--out OUT]" in city.stdout   # a new city's files have defaults
    legacy = run("--city", "clarksville-tn", "--help")
    assert legacy.returncode == 0 and "--facts FACTS --out OUT" in legacy.stdout   # Clarksville's are always named


def test_a_city_that_differs_from_the_environment_exits_2():
    r = run("--city", "clarksville-tn", "--facts", str(FIXTURE), "--out", "unused", city_env="murfreesboro-tn")
    assert r.returncode == 2 and "differs from DAYLIGHT_CITY=murfreesboro-tn" in r.stderr
    assert not (ROOT / "unused").exists()


def test_the_same_city_in_both_places_is_fine():
    r = run("--city", "clarksville-tn", "--help", city_env="clarksville-tn")
    assert r.returncode == 0, r.stderr


def test_an_unknown_city_exits_2_naming_it():
    r = run("--city", "nowhere-tn", "--facts", str(FIXTURE), "--out", "unused")
    assert r.returncode == 2 and "city nowhere-tn" in r.stderr and "no such city file" in r.stderr


def test_clarksville_with_city_still_needs_facts_and_out():
    r = run("--city", "clarksville-tn")
    assert r.returncode == 2 and "required: --facts, --out" in r.stderr


def test_a_new_city_defaults_its_facts_path():
    r = run("--city", "murfreesboro-tn")
    assert r.returncode == 1 and "data/localities/murfreesboro-tn/facts.json: no such facts file" in r.stderr
    assert not (ROOT / "build" / "murfreesboro-tn").exists()


def test_in_process_another_city_exits_2_and_build_refuses_it(monkeypatch, tmp_path):
    from sitegen.__main__ import main
    monkeypatch.delenv("DAYLIGHT_CITY", raising=False)
    assert config.CITY == "clarksville-tn"
    assert main(["--city", "murfreesboro-tn", "--facts", str(FIXTURE), "--out", str(tmp_path / "s")]) == 2
    assert "DAYLIGHT_CITY" not in os.environ
    with pytest.raises(BuildError, match="sitegen was loaded for clarksville-tn; run a new process for murfreesboro-tn"):
        build(FIXTURE, tmp_path / "s", city="murfreesboro-tn")
    assert not (tmp_path / "s").exists()


def test_clarksville_primary_equals_todays_literals():
    site = yaml.safe_load((ROOT / "config" / "site.yml").read_text(encoding="utf-8"))
    assert config.CITY == "clarksville-tn" and config.LEGACY_SETTINGS is True
    assert list(config.SITE) == list(site)                 # the legacy file as read, not the merged dict
    if "RECORDS_SITE_URL" not in os.environ:                # the launch override sets alerts.site_url only
        assert config.SITE == site
    assert config.PRIMARY == {
        "key": "county", "name": "Montgomery County Commission", "label": "County Commission",
        "meeting_title_body": "County Commission",
        "record": {"url": "https://montgomerytn.gov/clerk/county-commission-minutes",
                   "label": "Montgomery County clerk, commission minutes"},
        "kind_labels": {"formal": "Formal meeting", "informal": "Informal meeting", "special": "Special meeting"},
        "held_sentences": None, "seats": "districts"}
    assert tuple(config.PRIMARY) == config.PRIMARY_KEYS


def test_clarksville_paths_are_unchanged():
    assert config.SITE_CONFIG_PATH == ROOT / "config" / "site.yml"
    assert config.COUNTY_AGENDAS == ROOT / "data" / "county-agendas" / "agendas.json"
    assert config.SEATS_PATH == ROOT / "config" / "localities" / "montgomery-tn" / "seats.yml"
    assert config.DISTRICTS_PATH == ROOT / "config" / "localities" / "montgomery-tn" / "districts.json"
    assert config.FIN_LOCALITY_PATH == ROOT / "config" / "localities" / "montgomery-tn" / "finance.yml"
    assert config.LOCALITY == "montgomery-tn" and [c["locality"] for c in config.COUNCILS] == ["clarksville-tn"]


def test_clarksville_by_environment_loads_the_same_settings():
    p = probe("clarksville-tn")
    assert p["city"] == "clarksville-tn" and p["legacy"] is True and p["locality"] == "montgomery-tn"
    assert p["primary"]["key"] == "county" and p["councils"] == 1 and None not in p["paths"]


def test_a_city_only_settings_file_leaves_the_county_paths_out():
    p = probe("murfreesboro-tn")
    assert p["city"] == "murfreesboro-tn" and p["legacy"] is False
    assert p["paths"] == [None, None, None, None] and p["councils"] == 0 and p["locality"] is None
    assert p["capital"] is None and p["site_name"] == "Daylight" and p["live"] is False
    assert p["primary"]["key"] == "council" and p["primary"]["seats"] == "at_large"
    assert p["primary"]["meeting_title_body"] == p["primary"]["label"] == "City Council"
    assert set(p["primary"]) == set(config.PRIMARY_KEYS)
