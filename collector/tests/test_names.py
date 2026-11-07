"""Name merge rules 1-4 (G2) and the committed roster."""
import pytest

from collector.names import NAMES, Resolver, RosterError, load_roster, normalise, public_officials

ROSTER = [
    {"id": "jerry-allbert", "name": "Jerry Allbert", "surname": "Allbert", "given": "Jerry", "aliases": []},
    {"id": "randy-allbert", "name": "Randy Allbert", "surname": "Allbert", "given": "Randy",
     "aliases": [{"alias": "Randy Alibert", "reason": "OCR", "example": "src-x p1"}]},
    {"id": "joe-smith", "name": "Joe Smith", "surname": "Smith", "given": "Joe", "aliases": []},
    {"id": "tangi-smith", "name": "Tangi Smith", "surname": "Smith", "given": "Tangi",
     "aliases": [{"alias": "Tangi C. Smith"}]},
    {"id": "john-gannon", "name": "John Gannon", "surname": "Gannon", "given": "John", "aliases": []},
]


@pytest.fixture
def r():
    return Resolver(ROSTER)


def test_rule1_normalise_titles_punctuation_case_spaces():
    assert normalise("  Commissioner  Tangi C.  Smith, ") == "tangi c smith"
    assert normalise("Mr. Dr. JOHN Gannon") == "john gannon"
    assert normalise("Ｊｏｈｎ Gannon") == "john gannon"          # NFKC


def test_rule2_exact_name_or_alias(r):
    assert r.resolve("Randy Alibert") == ("randy-allbert", "exact")
    assert r.resolve("Commissioner Tangi C. Smith") == ("tangi-smith", "exact")


def test_rule3_surname_only_when_unique_on_that_meetings_roster(r):
    roster = {"jerry-allbert", "randy-allbert", "joe-smith", "tangi-smith", "john-gannon"}
    assert r.resolve("Gannon", roster) == ("john-gannon", "surname")
    assert r.resolve("Allbert", roster) == (None, "unmatched")            # two Allberts: never picked
    assert r.resolve("J. Smith", roster) == ("joe-smith", "initial+surname")
    assert r.resolve("Allbert", {"jerry-allbert", "joe-smith"}) == ("jerry-allbert", "surname")
    assert r.resolve("Gannon") == (None, "unmatched")                     # no roster: no surname rule


def test_rule4_no_fuzzy_merge(r):
    roster = {o["id"] for o in ROSTER}
    for raw in ("Jerry Ailbert", "Gaimon", "John Gannon Jr", "Randy Albert"):
        assert r.resolve(raw, roster)[0] is None, raw
    assert r.suggestions("Jerry Ailbert")[0]["official_id"] == "jerry-allbert"   # suggestion only


def test_alias_used_by_two_officials_is_an_error():
    bad = ROSTER + [{"id": "x", "name": "Randy Alibert", "surname": "Alibert", "given": "Randy", "aliases": []}]
    with pytest.raises(RosterError):
        Resolver(bad)


def test_committed_roster_loads_and_every_alias_has_a_reason():
    roster = load_roster(NAMES)
    Resolver(roster)
    assert roster and len({o["id"] for o in roster}) == len(roster)
    for o in roster:
        for a in o["aliases"]:
            assert a.get("reason") and a.get("example"), (o["id"], a)
    pub = public_officials(roster)
    assert [o["id"] for o in pub] == sorted(o["id"] for o in pub)
    assert set(pub[0]) == {"id", "name", "surname", "given", "title", "aliases"}
