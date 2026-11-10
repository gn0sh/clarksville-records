"""topics/number-prefix-not-typed (bug sweep 2026-11-10, H5): an item's type comes from what its number prints.

The City Council's minutes print each numbered item with its kind in front ("ORDINANCE 09-2025-26", "RESOLUTION
12-2025-26"); collector/city_build.py keeps that as the item's number. The kind word is an exact number prefix, so
the item carries that type whatever its title says, or when it has no title at all.
"""
import json
from collections import Counter

import pytest

from sitegen import config, views

KIND_WORDS = {"ORDINANCE": "ordinance", "RESOLUTION": "resolution"}


def test_a_numbered_ordinance_or_resolution_carries_its_type():
    assert "ordinance" in views.item_types({"number": "ORDINANCE 09-2025-26", "title": ""})
    assert "resolution" in views.item_types({"number": "RESOLUTION 12-2025-26", "title": ""})


def test_the_kind_prefix_adds_to_the_title_types_and_never_guesses_the_other_kind():
    budget = {"number": "ORDINANCE 12-2022-23", "title": "(First Reading) Amending the budget"}
    assert views.item_types(budget) == ["budget", "ordinance"]
    # a resolution whose title names an ordinance keeps both: the prefix is exact, the title rule is unchanged
    assert views.item_types({"number": "RESOLUTION 5-2020-21", "title": ""}) == ["resolution"]
    assert views.item_types({"number": "ORDINANCE 5-2020-21", "title": ""}) == ["ordinance"]


@pytest.mark.parametrize("number", ["ORDINANCES 1-2020-21", "RESOLUTIONS", "ORDINANCE", "24-7-4", "AB-5-2022", "", None])
def test_only_the_whole_kind_word_before_a_number_is_a_prefix(number):
    """The prefix is the printed kind word and the space after it; a county number or a longer word is not one."""
    assert views.item_types({"number": number, "title": ""}) == ["other"]


def test_the_two_kind_prefixes_are_configured_exactly():
    by_key = {t["key"]: t for t in config.SITE["item_types"]}
    assert by_key["ordinance"]["prefixes"] == ["ORDINANCE "] and by_key["resolution"]["prefixes"] == ["RESOLUTION "]


def test_every_committed_item_numbered_with_a_kind_word_carries_that_type():
    """Over the committed facts of every council: no item numbered ORDINANCE/RESOLUTION is left out of its type."""
    seen, missing = Counter(), []
    data = config.REPO_ROOT / "data"
    paths = [data / "facts.json", *sorted((data / "localities").glob("*/facts.json"))]
    for path in paths:
        for it in json.loads(path.read_text(encoding="utf-8"))["items"]:
            word = (it.get("number") or "").split(" ")[0]
            if word in KIND_WORDS:
                seen[word] += 1
                if KIND_WORDS[word] not in views.item_types(it):
                    missing.append(f"{path.parent.name}: {it['number']}")
    assert seen["ORDINANCE"] and seen["RESOLUTION"], "the committed city facts hold numbered ordinances and resolutions"
    assert missing == [], f"{len(missing)} items not typed by their number, first: {missing[:3]}"
