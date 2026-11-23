# ruff: noqa: E501
"""The morning note's invitation on the front page (front-signup, 2026-11-18). Owner: "I found the link to sign up for
the morning note in the hamburger menu, but I had to go looking for it ... that opportunity needs to be on the main
page, probably near the top." While the sign-up form is enabled the landing shows one sentence and a link to the form
on the Alerts page (alerts.html#note), right under the address card; off, or with no note at all, it shows nothing.
It is a link, not a second form: no email field, nothing posted, no outside link, no support ask."""
import copy
import re

import pytest

from conftest import ROOT, note_off, parse
from qa import site_checks
from sitegen import config, morning
from test_morning_page import ENABLED, _build

CSS = (ROOT / "site" / "static" / "style.css").read_text(encoding="utf-8")
INVITE = re.compile(r'<section class="note-invite"[^>]*>(.*?)</section>', re.S)


@pytest.fixture(scope="module")
def on(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    out = tmp_path_factory.mktemp("front-signup-on") / "site"
    cfg = copy.deepcopy(config.SITE)
    cfg["morning_note"].update(ENABLED)
    pages = _build(out, mp, cfg)
    mp.undo()
    return out, pages, cfg


@pytest.fixture(scope="module")
def off(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    out = tmp_path_factory.mktemp("front-signup-off") / "site"
    pages = _build(out, mp, cfg=note_off(config.SITE))
    mp.undo()
    return pages


def test_front_page_invites_to_the_form_when_enabled(on):
    out, pages, cfg = on
    t = cfg["morning_note"]["page"]
    cards = INVITE.findall(pages["index.html"])
    assert len(cards) == 1
    card = cards[0]
    assert " ".join(parse(card).all_text().split()) == f'{t["front_pitch"]} {t["front_button"]}'
    # one real link, to the form's anchor on the Alerts page; that anchor is the enabled form
    assert re.findall(r"<a\b[^>]*>", card) == ['<a class="note-invite-btn" href="alerts.html#note">']
    assert f'>{t["front_button"]}</a>' in card
    assert re.search(r'<form class="mn-card" id="note" action="https://forms\.example\.net/', pages["alerts.html"])
    # the section is named for a screen reader ("Morning note", the Method page's heading for it)
    assert f'<section class="note-invite" aria-label="{t["method_heading"]}">' in pages["index.html"]


def test_the_invitation_is_a_link_not_a_second_form(on):
    _, pages, cfg = on
    card = INVITE.search(pages["index.html"]).group(1)
    for tag in ("<input", "<form", "<button", "<script", "<img", "data-ext", "http://", "https://"):
        assert tag not in card, tag
    # no money ask beside it: the support line and link stay where they were (the Alerts page and the footer)
    assert cfg["support_line"] not in card and "buymeacoffee" not in card.lower()
    # the landing's CSP gains nothing: the form's origin is on the Alerts page only
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', pages["index.html"]).group(1)
    assert "forms.example.net" not in csp


def test_it_is_near_the_top_under_the_address_card_and_before_the_doors(on):
    _, pages, _ = on
    html = pages["index.html"]
    find, invite = html.index('<section class="find"'), html.index('<section class="note-invite"')
    after = min(html.index(mark) for mark in ('id="doors-h"', 'id="meetings"') if mark in html)
    assert html.index('id="welcome-h"') < find < invite < after
    # a phone moves the meetings above the doors by CSS order; the invitation moves with the address card
    assert ".landing > .note-invite { order: -1; }" in CSS


def test_only_the_front_page_and_the_body_pages_carry_it(on):
    """Wall of text (owner, 2026-11-19): a first-time visitor may land on a body's page and never see the front page,
    so the county's, the city's and the planning commission's landing pages carry the same invitation, beside their
    header (_hub.html.j2 body_head `invite`). No other page does. The fixture build has the county's."""
    _, pages, cfg = on
    t = cfg["morning_note"]["page"]
    assert sorted(rel for rel, html in pages.items() if "note-invite" in html) == ["index.html", "montgomery-county.html"]
    html = pages["montgomery-county.html"]
    card = INVITE.findall(html)
    assert len(card) == 1
    assert " ".join(parse(card[0]).all_text().split()) == f'{t["front_pitch"]} {t["front_button"]}'
    assert re.findall(r"<a\b[^>]*>", card[0]) == ['<a class="note-invite-btn" href="alerts.html#note">']
    # it follows the body's header, inside the one wrapper that sets it beside the header on a wide screen
    top = html.index('<div class="body-top">')
    assert top < html.index('<div class="body-head"') < html.index('<section class="note-invite"') < html.index('id="hub-h"')


def test_absent_while_the_form_is_off(off):
    t = config.SITE["morning_note"]["page"]
    for rel, html in off.items():
        assert "note-invite" not in html and t["front_pitch"] not in html and t["front_button"] not in html, rel


def test_absent_with_no_note_block(tmp_path, monkeypatch):
    cfg = copy.deepcopy(config.SITE)
    del cfg["morning_note"]
    pages = _build(tmp_path / "site", monkeypatch, cfg)
    assert "note-invite" not in pages["index.html"]


def test_words_are_config_text(tmp_path, monkeypatch):
    cfg = copy.deepcopy(config.SITE)
    cfg["morning_note"].update(ENABLED)
    cfg["morning_note"]["page"].update({"front_pitch": "FRONT-PITCH.", "front_button": "FRONT-BUTTON"})
    card = INVITE.search(_build(tmp_path / "site", monkeypatch, cfg)["index.html"]).group(1)
    assert "<p>FRONT-PITCH.</p>" in card and ">FRONT-BUTTON</a>" in card


@pytest.mark.parametrize("key", ["front_pitch", "front_button"])
@pytest.mark.parametrize("value", ["", " ", None])
def test_config_refuses_missing_words(key, value):
    cfg = copy.deepcopy(config.SITE)
    cfg["morning_note"]["page"][key] = value
    assert any(f"morning_note.page.{key} must be set" in p for p in morning.problems(cfg)), morning.problems(cfg)


def test_shipped_words():
    t = config.SITE["morning_note"]["page"]
    assert t["front_button"] == "Sign up for the morning note"
    assert t["front_pitch"] == (
        "Your local government, in plain words: one short email by 7 AM with what's new on the lists you pick (council votes from your seats, zoning near you, budget and contracts) plus the next public meetings. Quiet day? No email."
    )
    # the lists are picked on the sign-up form (morning_note.lists), so the words may name them
    assert morning.problems(config.SITE) == []


def test_link_check_passes_with_the_invitation(on):
    out, _, cfg = on
    pages = {f.relative_to(out).as_posix(): site_checks.parse(f) for f in out.rglob("*.html")}
    assert site_checks.check_links(out, pages, no_export=True) == []
    assert site_checks.check_external(pages, out, cfg) == []
