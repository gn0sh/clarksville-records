"""The multi-city template (cities/, config/cities/, config/brand.yml; docs/adr/0007-multi-city-template.md).
Synthetic cities in tmp_path only; nothing here touches the network."""
import json
import shutil
import socket
from datetime import date
from pathlib import Path

import pytest
import yaml

from cities import __main__ as cli
from cities import brand, check, plan, readers, registry, scaffold
from cities.errors import CityError
from collector import fetch, legistar

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the cities package must never open a connection")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


READY_CITY = """\
slug: testville-or
name: Testville
state: OR
timezone: America/Los_Angeles
status: draft
domain: testville.daylight.gnoshcodes.com
platform_facts: config/cities/testville-or/platform-facts.md
sources:
  - {portal: legistar, config: config/cities/testville-or/legistar.yml}
allowed_hosts:
  - {host: webapi.legistar.com, robots: "allows all; 2026-11-16, platform-facts.md", terms: "read 2026-11-16"}
  - {host: testville.legistar.com, robots: "allows all; 2026-11-16", terms: "read 2026-11-16"}
launch: {launch_days: 365, earliest: "2018-01-01"}
sky_place: {lat: 44.0, lon: -123.0}
district_lookup: {url: "https://example.org/lookup", label: Example lookup}
geocoder_places: [Testville]
"""


def make_root(tmp_path: Path, city_text: str = READY_CITY, slug: str = "testville-or") -> Path:
    """A tiny repo root: the real brand file, one synthetic city with a Legistar source and a facts stub."""
    (tmp_path / "config").mkdir()
    shutil.copy(ROOT / "config" / "brand.yml", tmp_path / "config" / "brand.yml")
    d = tmp_path / "config" / "cities" / slug
    d.mkdir(parents=True)
    (d / "city.yml").write_text(city_text, encoding="utf-8")
    (d / "platform-facts.md").write_text("# facts\n", encoding="utf-8")
    src = (ROOT / "config" / "cities" / "salem-or" / "legistar.yml").read_text(encoding="utf-8")
    src = "\n".join(line.split(" #")[0] for line in src.splitlines() if not line.startswith("#"))
    src = src.replace("client: salem", "client: testville").replace('"2016-01-01"', '"2018-01-01"')
    (d / "legistar.yml").write_text(src.replace("city: salem-or", f"city: {slug}") + "\n", encoding="utf-8")
    return tmp_path


def edit(root: Path, old: str, new: str, slug: str = "testville-or") -> None:
    p = root / "config" / "cities" / slug / "city.yml"
    text = p.read_text(encoding="utf-8")
    assert old in text, old
    p.write_text(text.replace(old, new), encoding="utf-8")


# ------------------------------------------------------------------ brand (B)
def test_brand_file_pins_the_one_coffee_link():
    b = brand.load_brand()
    assert b["support_url"] == brand.BMAC_URL == "https://buymeacoffee.com/gnoshcodes"
    assert b["support_enabled"] is True


def test_clarksville_site_yml_brand_values_equal_brand_yml():
    """Drift guard while config/site.yml still carries the brand keys (removed after Clarksville round 2)."""
    site = yaml.safe_load((ROOT / "config" / "site.yml").read_text(encoding="utf-8"))
    assert brand.drift(brand.load_brand(), site) == []


@pytest.mark.parametrize("old,new,match", [
    ("support_url: https://buymeacoffee.com/gnoshcodes", "support_url: https://www.buymeacoffee.com/gnoshcodes",
     "support_url must be"),
    ("support_enabled: true", "support_enabled: false", "support_enabled must be true"),
    ("operator: gnoshcodes LLC\n", "", "missing brand keys operator"),
])
def test_brand_file_refuses_a_changed_or_missing_key(tmp_path, old, new, match):
    p = tmp_path / "brand.yml"
    p.write_text((ROOT / "config" / "brand.yml").read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    with pytest.raises(CityError, match=match):
        brand.load_brand(p)


@pytest.mark.parametrize("line", [
    "support_enabled: false\n", "support_url: https://example.org/tip\n", "site_name: Other\n",
    "site:\n  support_line: Other words\n", "site:\n  corrections: {email: x@example.org}\n",
])
def test_a_city_that_sets_a_brand_key_fails_plainly(tmp_path, line):
    root = make_root(tmp_path, READY_CITY + line)
    with pytest.raises(CityError, match="shared brand setting, set once in config/brand.yml"):
        registry.load_city("testville-or", root)


def test_merged_settings_carry_the_brand_and_the_city():
    b = brand.load_brand()
    clarksville = registry.load_city("clarksville-tn")
    s = registry.site_settings(clarksville, b)
    site = yaml.safe_load((ROOT / "config" / "site.yml").read_text(encoding="utf-8"))
    assert s["support_url"] == brand.BMAC_URL and s["corrections"]["email"] == site["corrections"]["email"]
    assert s["corrections"]["github_repo"] == site["corrections"]["github_repo"]     # the city's own key kept
    assert s["sky_place"] == site["sky_place"]


def test_new_city_settings_come_from_its_file_plus_brand(tmp_path):
    root = make_root(tmp_path)
    s = registry.site_settings(registry.load_city("testville-or", root), brand.load_brand())
    assert s["site_timezone"] == "America/Los_Angeles" and s["today_place"] == "Testville"
    assert s["district_lookup_url"] == "https://example.org/lookup" and s["support_enabled"] is True


# ------------------------------------------------------------------ registry (A) and hosts (C)
def test_every_committed_city_loads_and_list_shows_them(capsys):
    assert [c["slug"] for c in registry.load_all()] == ["clarksville-tn", "murfreesboro-tn", "salem-or"]
    assert cli.main(["list", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {r["slug"]: (r["status"], r["domain"]) for r in rows} == {
        "clarksville-tn": ("live", "daylight.gnoshcodes.com"),
        "murfreesboro-tn": ("draft", "murfreesboro.daylight.gnoshcodes.com"),
        "salem-or": ("draft", "salem.daylight.gnoshcodes.com")}


def test_clarksville_points_at_todays_files():
    c = registry.load_city("clarksville-tn")
    assert c["settings"] == "config/site.yml" and c["status"] == "live" and c["launch"] is None
    assert all((ROOT / s["config"]).is_file() for s in c["sources"] if s.get("config"))


def test_clarksville_hosts_equal_the_fetchers_allowlist():
    assert registry.allowed_hosts(registry.load_city("clarksville-tn")) == fetch.ALLOWED_HOSTS


def test_denied_hosts_are_never_allowed_for_any_city(tmp_path):
    for city in registry.load_all() + [registry.load_city("testville-or", make_root(tmp_path))]:
        for d in fetch.DENIED_HOSTS:
            assert not registry.may_fetch(city, d) and not registry.may_fetch(city, "www." + d), (city["slug"], d)


@pytest.mark.parametrize("host", ["cityofclarksville.com", "www.cityofclarksville.com", "dev2.montgomerytn.gov"])
def test_a_city_listing_a_denied_host_fails(tmp_path, host):
    root = make_root(tmp_path)
    edit(root, "  - {host: testville.legistar.com,", f"  - {{host: {host}, robots: x, terms: x}}\n"
                                                   "  - {host: testville.legistar.com,")
    with pytest.raises(CityError, match="denied host and can never be allowed"):
        registry.load_city("testville-or", root)


def test_a_citys_own_denied_host_is_refused_too(tmp_path):
    root = make_root(tmp_path, READY_CITY + "denied_hosts: [testville.legistar.com]\n")
    with pytest.raises(CityError, match="denied host"):
        registry.load_city("testville-or", root)


def test_a_reader_host_missing_from_the_allowlist_fails(tmp_path):
    root = make_root(tmp_path)
    edit(root, "  - {host: testville.legistar.com, robots: \"allows all; 2026-11-16\", terms: \"read 2026-11-16\"}\n", "")
    with pytest.raises(CityError, match="asks testville.legistar.com, not in allowed_hosts"):
        registry.load_city("testville-or", root)


@pytest.mark.parametrize("old,new,match", [
    ("slug: testville-or", "slug: testville", "slug must be the folder name"),
    ("state: OR", "state: WA", "state must be"),
    ("status: draft", "status: public", "status must be one of"),
    ("domain: testville.daylight.gnoshcodes.com", "domain: testville.example.com", "domain must be"),
    ("timezone: America/Los_Angeles", "timezone: Pacific", "not an IANA zone"),
    ("earliest: \"2018-01-01\"", "earliest: \"2017-01-01\"", "differ from"),
    ("sky_place: {lat: 44.0, lon: -123.0}", "sky_place: [44, -123]", "sky_place is"),
    ("name: Testville\n", "name: Testville\ncolour: blue\n", "unknown keys colour"),
])
def test_a_malformed_city_names_the_key(tmp_path, old, new, match):
    root = make_root(tmp_path)
    edit(root, old, new)
    with pytest.raises(CityError, match=match):
        registry.load_city("testville-or", root)


def test_two_cities_cannot_share_a_domain(tmp_path):
    root = make_root(tmp_path)
    shutil.copytree(root / "config" / "cities" / "testville-or", root / "config" / "cities" / "otherville-or")
    p = root / "config" / "cities" / "otherville-or" / "city.yml"
    p.write_text(p.read_text().replace("slug: testville-or", "slug: otherville-or"))
    with pytest.raises(CityError, match="already testville-or's|already otherville-or's"):
        registry.load_all(root)


# ------------------------------------------------------------------ readers (D)
def test_readers_registry_names_built_and_unbuilt_portals():
    assert {"agenda_center", "civicclerk", "legistar", "municode"} <= set(readers.READERS)
    assert not readers.READERS["municode"].built
    assert readers.READERS["legistar"].required == legistar.REQUIRED
    for c in registry.load_all():
        assert all(s["reader"].built for s in c["sources"]), c["slug"]


def test_an_unknown_portal_fails_and_names_the_known_ones(tmp_path):
    root = make_root(tmp_path)
    edit(root, "{portal: legistar,", "{portal: granicus,")
    with pytest.raises(CityError, match="portal 'granicus' is unknown .*legistar"):
        registry.load_city("testville-or", root)


def test_a_source_missing_a_reader_key_fails(tmp_path):
    root = make_root(tmp_path)
    p = root / "config" / "cities" / "testville-or" / "legistar.yml"
    p.write_text(p.read_text().replace("body_name:", "body:"))
    with pytest.raises(CityError, match="Legistar Web API reader needs body_name"):
        registry.load_city("testville-or", root)


# ------------------------------------------------------------------ check (F)
def test_a_complete_city_is_ready(tmp_path):
    root = make_root(tmp_path)
    text, code = check.render("testville-or", root)
    assert code == 0 and text.endswith("READY") and "[ ]" not in text, text


def test_salem_is_not_ready_and_says_why():
    text, code = check.render("salem-or")
    assert code == 1 and text.endswith("items to do")
    assert "host webapi.legistar.com: robots.txt not checked" in text
    assert "host salem.legistar.com: terms of use not checked" in text
    assert "missing: config/cities/salem-or/city.yml line" in text and "sky_place: UNVERIFIED" in text
    assert "UNVERIFIED: config/cities/salem-or/legistar.yml line" in text
    assert "source legistar (config/cities/salem-or/legistar.yml): shared reader built; config loads" in text


def test_murfreesboro_is_a_draft_agenda_center_city_not_ready():
    c = registry.load_city("murfreesboro-tn")
    assert c["status"] == "draft" and [s["portal"] for s in c["sources"]] == ["agenda_center"]
    assert registry.allowed_hosts(c) == ("www.murfreesborotn.gov",)
    assert c["district_lookup"] == {"url": "https://web.go-vote-tn.elections.tn.gov/", "label": "GoVoteTN"}
    text, code = check.render("murfreesboro-tn")
    assert code == 1 and "host www.murfreesborotn.gov: robots.txt not checked" in text
    assert "config does not load yet" in text


def test_clarksville_check_lists_unrecorded_host_checks():
    text, code = check.render("clarksville-tn")
    assert code == 1 and "host montgomeryminutes.bisonline.com: robots.txt not checked" in text
    assert "host clarksvilletn.gov: robots.txt checked:" in text
    assert "source county_minutes: Clarksville-only reader built" in text


def test_an_unbuilt_reader_makes_a_city_not_ready(tmp_path):
    root = make_root(tmp_path)
    edit(root, "  - {portal: legistar, config: config/cities/testville-or/legistar.yml}",
         "  - {portal: legistar, config: config/cities/testville-or/legistar.yml}\n  - {portal: municode}")
    text, code = check.render("testville-or", root)
    assert code == 1 and "source municode: the Municode Meetings reader is not built yet" in text


def test_an_invalid_city_exits_2(tmp_path):
    root = make_root(tmp_path, READY_CITY + "support_url: https://example.org\n")
    text, code = check.render("testville-or", root)
    assert code == 2 and "city file is invalid" in text


# ------------------------------------------------------------------ scaffolder (F)
@pytest.mark.parametrize("portal,files", [
    ("legistar", {"city.yml", "platform-facts.md", "legistar.yml"}),
    ("agenda_center", {"city.yml", "platform-facts.md", "agenda_center.yml"}),
    ("civicclerk", {"city.yml", "platform-facts.md", "civicclerk.yml"}),
    ("municode", {"city.yml", "platform-facts.md"}),
])
def test_new_city_scaffold_loads_and_is_not_ready(tmp_path, portal, files):
    root = make_root(tmp_path)
    written = scaffold.new_city("killeen-tx", "Killeen", "TX", portal, "America/Chicago", root, date(2026, 11, 16))
    assert {p.name for p in written} == files
    city = registry.load_city("killeen-tx", root)
    assert city["status"] == "draft" and city["domain"] == "killeen.daylight.gnoshcodes.com"
    assert city["launch"] == {"launch_days": 365, "earliest": None}
    text, code = check.render("killeen-tx", root)
    assert code == 1 and "sky_place: UNVERIFIED" in text and "timezone: America/Chicago" in text
    facts = (root / "config" / "cities" / "killeen-tx" / "platform-facts.md").read_text()
    assert "Killeen, TX" in facts and ("not checked" in facts)
    assert "$" not in (root / "config" / "cities" / "killeen-tx" / "city.yml").read_text()


@pytest.mark.parametrize("args,match", [
    (("testville-or", "T", "OR", "legistar", "America/Los_Angeles"), "already exists"),
    (("Bad Slug", "B", "OR", "legistar", "America/Los_Angeles"), "slug"),
    (("bend-or", "Bend", "WA", "legistar", "America/Los_Angeles"), "state"),
    (("bend-or", "Bend", "OR", "granicus", "America/Los_Angeles"), "unknown"),
    (("bend-or", "Bend", "OR", "rpc", "America/Los_Angeles"), "Clarksville-only"),
    (("bend-or", "Bend", "OR", "legistar", "Pacific/Nowhere"), "IANA"),
])
def test_new_city_refuses_bad_input_and_writes_nothing(tmp_path, args, match):
    root = make_root(tmp_path)
    before = sorted(p.name for p in (root / "config" / "cities").iterdir())
    with pytest.raises(CityError, match=match):
        scaffold.new_city(*args, root=root)
    assert sorted(p.name for p in (root / "config" / "cities").iterdir()) == before


# ------------------------------------------------------------------ planner (E)
def city(slug, status="live", earliest=date(2020, 1, 1), launch=True):
    return {"slug": slug, "status": status,
            "launch": {"launch_days": 365, "earliest": earliest} if launch else None}


def test_launch_windows_moved_but_legistar_names_still_work():
    assert legistar.launch_windows is plan.launch_windows and legistar.Window is plan.Window


def test_plan_puts_daily_updates_first_and_shares_one_budget():
    today = date(2026, 11, 16)
    a = plan.new_state("a-or", date(2026, 1, 10), 365, date(2020, 1, 1))
    b = plan.new_state("b-or", date(2026, 3, 1), 365, date(2020, 1, 1))
    b = plan.mark_done(b, plan.next_window(b, date(2020, 1, 1)), date(2020, 1, 1))
    cities = [city("b-or"), city("a-or"), city("clarksville-tn", launch=False), city("new-or"),
              city("draft-or", status="draft")]
    p = plan.plan_run(cities, {"a-or": a, "b-or": b}, today, 80, daily_minutes=5, year_minutes=30)
    assert [(j.slug, j.kind) for j in p.jobs] == [
        ("a-or", "daily"), ("b-or", "daily"), ("clarksville-tn", "daily"), ("new-or", "launch"), ("a-or", "backfill")]
    assert [(j.slug, j.kind) for j in p.skipped] == [("b-or", "backfill")]       # fewest years done goes first
    assert p.left == 5 and all(j.slug != "draft-or" for j in p.jobs + p.skipped)
    assert p.jobs[3].window == plan.Window(date(2025, 11, 17), date(2026, 11, 17))
    assert p.jobs[4].window == plan.Window(date(2024, 1, 12), date(2025, 1, 11))   # 365 days older than its launch


def test_a_tiny_budget_still_never_backfills_before_dailies():
    st = plan.new_state("a-or", date(2026, 1, 10), 365, date(2020, 1, 1))
    p = plan.plan_run([city("a-or")], {"a-or": st}, date(2026, 11, 16), 20, daily_minutes=5, year_minutes=30)
    assert [j.kind for j in p.jobs] == ["daily"] and [j.kind for j in p.skipped] == ["backfill"]


def test_backfill_goes_newest_first_one_year_at_a_time_to_earliest():
    earliest = date(2023, 6, 1)
    st = plan.new_state("a-or", date(2026, 1, 10), 365, earliest)
    seen = []
    while (w := plan.next_window(st, earliest)) is not None:
        seen.append(w)
        st = plan.mark_done(st, w, earliest)
    assert [w.start for w in seen] == [date(2024, 1, 12), date(2023, 6, 1)]
    assert seen[0].end == date(2025, 1, 11) and all(a.start == b.end for a, b in zip(seen, seen[1:]))
    with pytest.raises(CityError, match="not the next backfill window"):
        plan.mark_done(plan.new_state("a-or", date(2026, 1, 10), 365, earliest), seen[1], earliest)


def test_windows_do_not_shift_from_day_to_day():
    st = plan.new_state("a-or", date(2026, 1, 10), 365, date(2020, 1, 1))
    one = plan.plan_run([city("a-or")], {"a-or": st}, date(2026, 5, 1), 99)
    two = plan.plan_run([city("a-or")], {"a-or": st}, date(2026, 9, 30), 99)
    assert one.jobs[1].window == two.jobs[1].window


def test_an_unknown_earliest_means_the_launch_year_only():
    st = plan.new_state("a-or", date(2026, 1, 10), 365, date(2025, 1, 11))
    p = plan.plan_run([city("a-or", earliest=None)], {"a-or": st}, date(2026, 11, 16), 99)
    assert [j.kind for j in p.jobs] == ["daily"]


def test_state_is_written_only_for_a_city_with_a_launch_plan(tmp_path):
    root = make_root(tmp_path)
    c = registry.load_city("testville-or", root)
    st = plan.new_state("testville-or", date(2026, 11, 16), 365, c["launch"]["earliest"])
    path = plan.save_state(c, st, root)
    assert path == root / "data" / "cities" / "testville-or" / "backfill.json"
    assert plan.load_state("testville-or", root) == st
    with pytest.raises(CityError, match="no launch block"):
        plan.save_state(registry.load_city("clarksville-tn"), plan.new_state(
            "clarksville-tn", date(2026, 11, 16), 365, date(2016, 1, 1)), root)
    assert not (ROOT / "data" / "cities").exists()


def test_cli_plan_prints_and_writes_nothing(capsys):
    assert cli.main(["plan", "--budget", "60", "--today", "2026-11-16"]) == 0
    out = capsys.readouterr().out
    assert "clarksville-tn" in out and "salem-or" not in out and "Nothing was run" in out
    assert not (ROOT / "data" / "cities").exists()


def test_cli_validate_and_check_exit_codes(capsys):
    assert cli.main([]) == 0 and "3 cities valid" in capsys.readouterr().out
    assert cli.main(["check", "salem-or"]) == 1
    assert cli.main(["check", "nowhere-xx"]) == 2


# ------------------------------------------------------------------ review fixes (code review on aa63844)
@pytest.mark.parametrize("value", ["unverified", "Unverified 2026-11-16", "TODO", "not checked", "allows all"])
def test_a_host_check_counts_only_with_a_date_and_no_unverified_mark(tmp_path, value):
    root = make_root(tmp_path)
    edit(root, 'robots: "allows all; 2026-11-16, platform-facts.md"', f'robots: "{value}"')
    text, code = check.render("testville-or", root)
    assert code == 1 and "host webapi.legistar.com: robots.txt not checked" in text


def test_clarksville_dated_robots_lines_still_count():
    assert registry.check_recorded("allows all; verified by fetch 2026-11-07 (docs/platform-facts.md)")
    assert not registry.check_recorded("UNVERIFIED (no terms check on record; Brian approved collection 2026-11-09)")


def test_a_clarksville_only_reader_is_refused_for_another_city(tmp_path):
    root = make_root(tmp_path)
    edit(root, "  - {portal: legistar, config: config/cities/testville-or/legistar.yml}",
         "  - {portal: legistar, config: config/cities/testville-or/legistar.yml}\n"
         "  - {portal: rpc, config: config/cities/testville-or/legistar.yml}")
    with pytest.raises(CityError, match="Clarksville-only reader; it can't serve another city"):
        registry.load_city("testville-or", root)


def test_clarksville_reader_hosts_come_from_its_files():
    c = registry.load_city("clarksville-tn")
    by = {s["portal"]: s["reader"].hosts(ROOT / s["config"]) for s in c["sources"] if s.get("config")}
    assert by["agenda_center"] == ("www.clarksvilletn.gov",)
    assert by["civicclerk"] == ("clarksvilletn.api.civicclerk.com",)


def agenda_center_city(root: Path, host: str, video: str = "") -> None:
    d = root / "config" / "cities" / "testville-or"
    (d / "agenda_center.yml").write_text(f"""\
locality: testville-or
body: Testville City Council
official_title: Council Member
host: {host}
category_id: 3
category_name: City Council
search_url: "https://{host}/AgendaCenter/Search/?CIDs={{cid}}&year={{year}}"
years: [2020, 2026]
kind_rules: [[regular, '^']]
vote_labels: {{}}
""", encoding="utf-8")
    edit(root, "  - {portal: legistar, config: config/cities/testville-or/legistar.yml}",
         "  - {portal: legistar, config: config/cities/testville-or/legistar.yml}\n"
         "  - {portal: agenda_center, config: config/cities/testville-or/agenda_center.yml}")


def test_an_agenda_center_host_off_the_allowlist_fails(tmp_path):
    root = make_root(tmp_path)
    agenda_center_city(root, "www.testville.gov")
    with pytest.raises(CityError, match="asks www.testville.gov, not in allowed_hosts"):
        registry.load_city("testville-or", root)


def test_a_reader_naming_a_denied_host_fails(tmp_path):
    root = make_root(tmp_path)
    agenda_center_city(root, "www.cityofclarksville.com")
    with pytest.raises(CityError, match="denied host and can never be asked"):
        registry.load_city("testville-or", root)


def test_a_civicclerk_video_host_may_not_be_denied(tmp_path):
    root = make_root(tmp_path)
    d = root / "config" / "cities" / "testville-or"
    src = (ROOT / "config" / "localities" / "clarksville-tn" / "civicclerk.yml").read_text(encoding="utf-8")
    (d / "civicclerk.yml").write_text(src.replace("video_hosts: [cpmedia.azureedge.net]",
                                                  "video_hosts: [cityofclarksville.com]"), encoding="utf-8")
    edit(root, "  - {portal: legistar, config: config/cities/testville-or/legistar.yml}",
         "  - {portal: legistar, config: config/cities/testville-or/legistar.yml}\n"
         "  - {portal: civicclerk, config: config/cities/testville-or/civicclerk.yml}")
    with pytest.raises(CityError, match="cityofclarksville.com is a denied host"):
        registry.load_city("testville-or", root)


def test_an_earliest_in_the_future_is_refused(tmp_path):
    root = make_root(tmp_path)
    edit(root, 'earliest: "2018-01-01"', 'earliest: "2999-01-01"')
    with pytest.raises(CityError, match="is in the future"):
        registry.load_city("testville-or", root)
    with pytest.raises(CityError, match="no launch window"):
        plan.launch_windows(date(2026, 11, 16), 365, date(2026, 11, 18))


def test_live_with_a_launch_plan_needs_the_owners_go_ahead(tmp_path):
    root = make_root(tmp_path)
    edit(root, "status: draft", "status: live")
    with pytest.raises(CityError, match="status live needs go_ahead"):
        registry.load_city("testville-or", root)
    edit(root, "status: live", "status: live\ngo_ahead: {date: \"2999-01-01\", by: Brian}")
    with pytest.raises(CityError, match="not in the future"):
        registry.load_city("testville-or", root)
    edit(root, '"2999-01-01"', '"2026-11-16"')
    assert registry.load_city("testville-or", root)["go_ahead"] == {"date": "2026-11-16", "by": "Brian"}


def test_leap_day_launch_has_no_gap_or_overlap():
    ws = plan.launch_windows(date(2028, 2, 29), 365, date(2026, 1, 1))
    assert ws[0] == plan.Window(date(2027, 3, 2), date(2028, 3, 1))           # 365 days ending on Feb 29
    assert ws[1] == plan.Window(date(2026, 3, 2), date(2027, 3, 2))
    assert ws[-1] == plan.Window(date(2026, 1, 1), date(2026, 3, 2))
    assert all(a.start == b.end for a, b in zip(ws, ws[1:]))


def test_a_budget_exactly_equal_to_the_jobs_runs_them_all():
    st = plan.new_state("a-or", date(2026, 1, 10), 365, date(2020, 1, 1))
    p = plan.plan_run([city("a-or")], {"a-or": st}, date(2026, 11, 16), 35, daily_minutes=5, year_minutes=30)
    assert [j.kind for j in p.jobs] == ["daily", "backfill"] and p.skipped == [] and p.left == 0


def test_an_earliest_inside_the_launch_window_means_one_window_only():
    earliest = date(2026, 6, 1)
    assert plan.launch_windows(date(2026, 11, 16), 365, earliest) == [plan.Window(earliest, date(2026, 11, 17))]
    st = plan.new_state("a-or", date(2026, 11, 16), 365, earliest)
    assert st["done"] == ["2026-06-01"] and plan.next_window(st, earliest) is None


def test_a_broken_yaml_file_exits_2(monkeypatch, capsys):
    def broken(*a, **k):
        raise yaml.YAMLError("bad indent")
    monkeypatch.setattr(cli, "load_all", broken)
    assert cli.main(["list"]) == 2 and "bad indent" in capsys.readouterr().err


# ------------------------------------------------------------------ delta review
def test_a_live_city_without_a_launch_block_still_needs_the_go_ahead(tmp_path):
    root = make_root(tmp_path)
    edit(root, 'launch: {launch_days: 365, earliest: "2018-01-01"}\n', "")
    edit(root, "status: draft", "status: live")
    p = root / "config" / "cities" / "testville-or" / "legistar.yml"
    p.write_text(p.read_text().replace('earliest: "2018-01-01"', 'earliest: "2016-01-01"'))
    with pytest.raises(CityError, match="status live needs go_ahead"):
        registry.load_city("testville-or", root)
    assert registry.load_city("clarksville-tn")["status"] == "live"          # the one exemption


@pytest.mark.parametrize("value", ["not checked 2026-11-16", "Todo: read it 2026-11-16"])
def test_a_dated_line_saying_not_checked_or_todo_is_not_a_record(value):
    assert not registry.check_recorded(value)


def test_one_city_with_bad_windows_is_left_out_not_the_whole_plan():
    bad = city("bad-or", earliest=date(2027, 1, 1))
    p = plan.plan_run([bad, city("ok-or", launch=False)], {"bad-or": None}, date(2026, 11, 16), 60)
    assert [(j.slug, j.kind) for j in p.jobs] == [("ok-or", "daily")]
    assert len(p.errors) == 1 and p.errors[0].startswith("bad-or: ") and "no launch window" in p.errors[0]
