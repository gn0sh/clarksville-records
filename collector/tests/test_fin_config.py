"""F1: config/localities/<locality>/finance.yml loads, and a missing or malformed key fails loudly (AC-F12)."""
import copy

import pytest
import yaml

from collector import fin_config
from collector.fin_config import FinanceConfigError


@pytest.fixture(scope="module")
def raw():
    return yaml.safe_load(fin_config.default_path().read_text(encoding="utf-8"))


def test_real_config_loads(raw):
    cfg = fin_config.load()
    assert cfg.archive_url.startswith("https://") and cfg.archive_host
    assert len(cfg.archive_header) == 3
    assert cfg.bonfire_hosts and all(h == h.lower() for h in cfg.bonfire_hosts)
    assert {s for s, _ in cfg.stage_rules} <= set(fin_config.STAGES)
    assert cfg.stage_rules[-1][0] == "other"            # the catch-all comes last
    assert set(cfg.bidtab.fields) == set(fin_config.BIDTAB_FIELDS)


@pytest.mark.parametrize("path", [
    ("archive_url",), ("archive_header",), ("status_words",), ("date_formats",), ("stage_rules",),
    ("bonfire_hosts",), ("scan_producers",), ("bidtab",), ("bidtab", "fields"), ("bidtab", "fields", "awardee"),
    ("bidtab", "columns"), ("bidtab", "columns", "total"), ("bidtab", "blocks", "first_label"),
    ("bidtab", "blocks", "total_labels"), ("budget",), ("budget", "books"), ("capital_fund",),
])
def test_missing_key_fails_loudly(raw, path):
    cfg = copy.deepcopy(raw)
    node = cfg
    for k in path[:-1]:
        node = node[k]
    del node[path[-1]]
    with pytest.raises(FinanceConfigError, match=path[-1]):
        fin_config.parse(cfg)


@pytest.mark.parametrize("edit, match", [
    (lambda c: c.update(archive_url="http://example.invalid/a"), "https"),
    (lambda c: c.update(archive_header=["Bid Name", "Award Date"]), "3 header cells"),
    (lambda c: c["stage_rules"].insert(0, ["award", "x"]), "unknown stage"),
    (lambda c: c["stage_rules"].insert(0, ["bid", "("]), "bad regex"),
    (lambda c: c.update(status_words=[]), "status_words"),
    (lambda c: c.update(date_formats=["Month D, YYYY"]), "strptime"),
    (lambda c: c.update(bonfire_hosts="mcgtn.bonfirehub.com"), "bonfire_hosts"),
])
def test_malformed_value_fails_loudly(raw, edit, match):
    cfg = copy.deepcopy(raw)
    edit(cfg)
    with pytest.raises(FinanceConfigError, match=match):
        fin_config.parse(cfg)


def test_a_label_or_a_list_of_labels(raw):
    cfg = copy.deepcopy(raw)
    cfg["bidtab"]["fields"]["project"] = "Bid Project"
    assert fin_config.parse(cfg).bidtab.fields["project"] == ("Bid Project",)
    assert fin_config.load().bidtab.fields["department"] == ("Department",)
    for bad in ([], [""], 5):
        cfg["bidtab"]["fields"]["project"] = bad
        with pytest.raises(FinanceConfigError, match="bidtab.fields.project"):
            fin_config.parse(cfg)
    del cfg["bidtab"]["blocks"]
    cfg["bidtab"]["fields"]["project"] = "Bid Project"
    assert fin_config.parse(cfg).bidtab.blocks is None          # the blocks layout is optional per locality


def test_missing_file_fails(tmp_path):
    with pytest.raises(FinanceConfigError):
        fin_config.load(tmp_path / "finance.yml")
