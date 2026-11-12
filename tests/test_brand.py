"""The gnoshcodes credit is the hook (gnoshcodes.com), not the old logo D, and the site check
`brand/no-old-gnoshcodes` fails a build that still carries the old logo."""
import hashlib
import re
import shutil

from qa import site_checks
from sitegen import config

BRAND = config.STATIC_DIR / "brand"
OLD_WORDMARK = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="-4 8 273 50"><path fill="#2B4BA5" '
                'd="M-2 24h4v4h-4zM-2 28h4v4h-4z"/><path d="M98.95 23.46L94 22L89.05 23.46"/></svg>')
OLD_MARK = '<svg viewBox="0 0 64 64"><path d="M8 20h6v6h-6zM8 26h6v6h-6z"/><path d="M32 11A21 21 0 0 1 32 53"/></svg>'


def test_hook_lockups_ship_with_an_accessible_name_and_no_old_logo():
    for mode in ("light", "dark"):
        svg = (BRAND / f"gnoshcodes-hook-{mode}.svg").read_text(encoding="utf-8")
        assert 'role="img" aria-label="gnoshcodes"' in svg and "<title>gnoshcodes</title>" in svg, mode
        assert not any(s.decode() in svg for s in site_checks.OLD_BRAND_SIGNATURES), mode
        assert "<text" not in svg and "font-family" not in svg, mode    # outlined: no font is loaded for the logo
    assert not list(BRAND.glob("gnoshcodes-wordmark-*"))
    assert hashlib.sha1((BRAND / "favicon.ico").read_bytes()).hexdigest() != site_checks.OLD_BRAND_FAVICON_SHA1


def test_built_footer_credit_uses_the_hook_light_and_dark(built, pages):
    checked = 0
    for name, html in pages.items():
        if "gc-credit" not in html:
            continue
        checked += 1
        credit = re.search(r'<p class="gc-credit">(.*?)</p>', html).group(1)
        assert re.findall(r'src="[^"]*static/brand/(gnoshcodes-hook-(?:light|dark)\.svg)"', credit) == \
            ["gnoshcodes-hook-light.svg", "gnoshcodes-hook-dark.svg"], name
        assert credit.count('alt="gnoshcodes"') == 2, name
    assert checked > 0                                                  # the credit is on pages, so the loop checked some
    assert site_checks.check_old_brand(built)[0] == []


def test_every_page_asks_for_the_hook_favicon_not_a_cached_old_one(pages):
    """Code-review nit: `?v=hook` on the favicon link, so a browser that cached the old logo D icon fetches it again."""
    for name, html in pages.items():
        assert re.findall(r'<link rel="icon" href="[^"]*static/brand/(favicon\.ico[^"]*)"', html) == \
            ["favicon.ico?v=hook"], name


def test_check_fails_on_old_path_data_names_and_favicon(built, tmp_path):
    site = tmp_path / "site"
    shutil.copytree(built, site)
    assert site_checks.check_old_brand(site)[0] == []
    (site / "static" / "brand" / "gnoshcodes-wordmark-color-light.svg").write_text(OLD_WORDMARK, encoding="utf-8")
    (site / "static" / "mark.svg").write_text(OLD_MARK, encoding="utf-8")
    page = site / "index.html"
    page.write_text(page.read_text(encoding="utf-8").replace("gnoshcodes-hook-dark.svg", "gnoshcodes-lockup-color-dark.svg"),
                    encoding="utf-8")
    shutil.copy(BRAND / "favicon.ico", site / "static" / "brand" / "icon-copy.ico")   # the new favicon passes
    problems = site_checks.check_old_brand(site)[0]
    assert len(problems) == 4, problems
    assert any(p.startswith("static/brand/gnoshcodes-wordmark-color-light.svg: named like") for p in problems)
    assert any(p.startswith("static/brand/gnoshcodes-wordmark-color-light.svg: 2 old") for p in problems)
    assert any(p.startswith("static/mark.svg: 2 old") for p in problems)
    assert any(p.startswith("index.html: 1 old") for p in problems)


def test_check_fails_on_the_old_favicon_bytes(tmp_path, monkeypatch):
    (tmp_path / "favicon.ico").write_bytes(b"\x00old")
    monkeypatch.setattr(site_checks, "OLD_BRAND_FAVICON_SHA1", hashlib.sha1(b"\x00old").hexdigest())
    assert site_checks.check_old_brand(tmp_path)[0] == ["favicon.ico: is the old gnoshcodes favicon"]


def test_old_daylight_colors_check_passes_the_build_and_fails_on_either_old_hex(built, tmp_path):
    """brand/no-old-daylight-colors: the old blue and orange are flagged in any file and any case, as six digits,
    with a two-digit alpha, or as rgb()/rgba(); a longer hex string that merely contains the digits (a hash) is not."""
    assert site_checks.check_old_daylight_colors(built)[0] == []
    (tmp_path / "a.css").write_text("a { color: #2b4ba5; } b { color: #EF5E35 }", encoding="utf-8")
    (tmp_path / "alpha.css").write_text("a { color: #2B4BA5cc; } b { background: #ef5e3580 }", encoding="utf-8")
    (tmp_path / "icon.svg").write_text('<svg><path fill="#2B4BA5"/></svg>', encoding="utf-8")
    (tmp_path / "rgb.css").write_text("a { color: rgb(43, 75, 165); } b { border-color: RGBA(239,94,53,.4) }"
                                      " c { color: rgb(43 75 165 / 50%) }", encoding="utf-8")
    (tmp_path / "data.json").write_text('{"sha": "002b4ba5ef5e35ff", "frag": "#2B4BA5ef12", "long": "#ef5e35abc"}',
                                        encoding="utf-8")
    (tmp_path / "ok.css").write_text("a { color: #0F1F3D; } b { color: #D2561B } c { color: rgb(43, 75, 16) }"
                                     " d { color: rgba(239, 94, 530, 1) } e { color: rgb(143, 75, 165) }",
                                     encoding="utf-8")
    problems, note = site_checks.check_old_daylight_colors(tmp_path)
    assert problems == ["a.css: old Daylight color(s) #2B4BA5, #EF5E35",
                        "alpha.css: old Daylight color(s) #2B4BA5, #EF5E35",
                        "icon.svg: old Daylight color(s) #2B4BA5",
                        "rgb.css: old Daylight color(s) #2B4BA5, #EF5E35"]
    assert note.startswith("6 files scanned")


def test_old_daylight_alpha_hex_is_a_hit_only_when_no_hex_digit_follows(tmp_path):
    (tmp_path / "hit.html").write_text('<p style="color:#2B4BA5ef">x</p>', encoding="utf-8")       # 8 digits, then a quote
    (tmp_path / "miss.json").write_text('"#2B4BA5e" "#2B4BA5ef0" "#ef5e35123456"', encoding="utf-8")  # 7, 9, 12 digits
    assert site_checks.check_old_daylight_colors(tmp_path)[0] == ["hit.html: old Daylight color(s) #2B4BA5"]
