# ruff: noqa: E501, F811
"""Task B7 (daylight-national): the morning note sender ignores "req-" tags. A confirmed subscriber who carries only
"req-" tags gets no edition, and "req-" tags next to "note-" tags change nothing about the note they get. FIXTURE
data only, an in-memory fake provider, no connection."""
import pytest

from sender import common, deliver
from test_morning import D, inputs  # noqa: F401
from test_morning_sender_plan import msite  # noqa: F401
from test_morning_sender_deliver import Fake, go, key_for, plan, settings, stamp, sub  # noqa: F401

REQ = ["req-records", "req-nashville-2", "req-district-5", "req-ward-3", "req-budget"]
# lookalikes: a req- tag that ends with a whole note- tag, so only a prefix check on the whole name tells them apart
LOOKALIKE = ["req-note-budget", "req-note-contracts", "req-note-ward-3", "req-note-district-5"]


def with_tags(n: int, tags: list, type_="regular") -> dict:
    row = sub(n, [], type_=type_)
    row["tags"] = list(tags)
    return row


def test_req_tags_do_not_change_what_recipient_reads():
    s = settings()
    base = ["note-budget", "note-district-7", "note-ward-3"]
    for extra in (REQ, ["req-zoning", "req-district-9"], ["req-note-ward-4", "req-note-district-2"]):
        a = deliver.recipient({"id": "a", "type": "regular", "tags": base, "metadata": {}}, s)
        b = deliver.recipient({"id": "a", "type": "regular", "tags": base + extra, "metadata": {}}, s)
        assert a == b and common.signature(b.lists, b.district, b.ward) == "budget|7|3"
    # a base that LACKS what the lookalikes name: none of it may leak in (no list, no seat)
    lean = ["note-budget"]
    got = deliver.recipient({"id": "a", "type": "regular", "tags": lean + LOOKALIKE, "metadata": {}}, s)
    assert common.signature(got.lists, got.district, got.ward) == "budget|-|-"
    for tags in (REQ, LOOKALIKE, ["req-note-ward-3"], ["req-note-district-5"], ["req-note-contracts"]):
        only = deliver.recipient({"id": "a", "type": "regular", "tags": tags, "metadata": {}}, s)
        assert (only.lists, only.district, only.ward) == ((), None, None)


def test_a_confirmed_subscriber_with_only_req_tags_gets_no_edition(plan):
    fake = Fake([sub(1, ["budget"]), with_tags(2, REQ), with_tags(3, ["req-budget", "req-contracts", "vip"]),
                 with_tags(4, LOOKALIKE), with_tags(5, ["req-note-budget"])])
    res, _ = go(plan, fake)
    assert (res.code, res.status, res.editions, res.recipients) == (0, "sent", 1, 1)
    (p,) = fake.created
    assert fake.audience(p) == {"sub-0001-secret"}
    assert p["filters"]["filters"][0]["value"] == stamp(key_for(plan, ["budget"]))


def test_only_req_tags_alone_is_the_no_tags_stop_and_sends_nothing(plan):
    fake = Fake([with_tags(1, REQ)])
    res, _ = go(plan, fake)
    assert (res.code, res.status, res.editions) == (2, "no-tags", 0)
    assert fake.created == [] and not fake.sent_drafts and "set_metadata" not in fake.calls


@pytest.mark.parametrize("lists, district, ward", [
    (["budget"], None, None), (["budget"], 7, None), (["contracts"], None, None), (["budget", "contracts"], None, 3)])
@pytest.mark.parametrize("extra", [REQ, ["req-budget", "req-district-2", "req-ward-1"], LOOKALIKE,
                                   ["req-note-ward-9", "req-note-district-9", "req-note-zoning"]])
def test_note_and_req_tags_get_exactly_the_note_without_the_req_tags(plan, lists, district, ward, extra):
    plain = sub(1, lists, district=district, ward=ward)
    mixed = sub(2, lists, district=district, ward=ward)
    mixed["tags"] = mixed["tags"] + extra
    solo, both = Fake([plain]), Fake([mixed])
    go(plan, solo)
    go(plan, both)
    assert len(solo.created) == len(both.created) == 1
    want = key_for(plan, lists, district, ward)
    for fake in (solo, both):
        (p,) = fake.created
        assert p["filters"]["filters"][0]["value"] == stamp(want)
    assert solo.created[0]["body"] == both.created[0]["body"]
    assert solo.created[0]["subject"] == both.created[0]["subject"]
    together = Fake([sub(1, lists, district=district, ward=ward), mixed])
    go(plan, together)
    (p,) = together.created                                        # one edition, both people in it
    assert together.audience(p) == {"sub-0001-secret", "sub-0002-secret"}
