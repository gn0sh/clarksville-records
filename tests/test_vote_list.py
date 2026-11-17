"""onceover/votes/member-yes-no-list (Brian, Nov 14): each official's vote list. Filter by Yes / No / Abstain / Other /
Absent (the same options for every official), rows = item + meeting date + vote + source, downloadable as CSV of
exactly the rows shown. Only confirmed votes recorded by name; a vote that names no one is nobody's Yes."""
import json
import os
import re
import shutil
import subprocess

import pytest

from sitegen import build as build_mod, config, views


def _rows(html):
    return re.findall(r'<tr data-vote="([a-z]+)" data-date="(\d{4}-\d{2}-\d{2})">(.*?)(?=\n<tr|\n</tbody>)', html, re.S)


def test_every_official_has_a_vote_list_linked_from_their_page(pages, facts):
    for o in facts["officials"]:
        page = pages[f"officials/{o['id']}.html"]
        assert f'href="../officials/{o["id"]}/votes.html?vote=no"' in page, o["id"]
        # the same order as the list page's filter: All first (N3)
        links = re.findall(r'href="\.\./officials/[^/]+/votes\.html(?:\?vote=([a-z]+))?">', page)
        assert links == ["", "yes", "no", "abstain", "other", "absent"], links
        assert "vote-list-pages" not in page          # one page each in the fixture
        assert f'officials/{o["id"]}/votes.html' in pages


def test_rows_are_the_confirmed_votes_and_absences_and_match_the_bar(pages, facts):
    ix = views.Index(facts)
    for o in facts["officials"]:
        html = pages[f"officials/{o['id']}/votes.html"]
        rows = _rows(html)
        c = views.official_counts(ix, o["id"])
        got = {k: sum(1 for r in rows if r[0] == k) for k, _ in views.VOTE_LIST_KEYS}
        assert got == {"yes": c["yes"], "no": c["no"], "abstain": c["abstain"], "other": c["other"],
                       "absent": c["rc_absent"]}, o["id"]
        # every row links its source page, and the filter shows each option with its count
        assert all('target="_blank"' in r[2] and "#page=" in r[2] for r in rows)
        for k, label in views.VOTE_LIST_KEYS:
            assert f'value="{k}"> {label} ({got[k]})</label>' in html
        # newest first
        dates = [r[1] for r in rows]
        assert dates == sorted(dates, reverse=True)
        # left out: the not confirmed ones, counted apart (votes cast, then while absent), never listed; the first
        # number is the official page's own rc_voted_nc
        left = re.search(r'class="muted vote-list-left"><span data-n="rc_voted_nc">(\d+)</span> votes? cast and '
                         r'<span data-n="rc_absent_nc">(\d+)</span> votes? while recorded absent are not confirmed\*', html)
        assert left and int(left.group(1)) == c["rc_voted_nc"] and int(left.group(2)) == c["rc_absent_nc"]
        official = pages[f"officials/{o['id']}.html"]
        assert re.search(rf'data-n="rc_voted_nc">{c["rc_voted_nc"]}<', official)


def test_unconfirmed_and_unnamed_votes_never_become_rows(facts):
    ix = views.Index(facts)
    held = {rc["id"] for rc in facts["roll_calls"] if rc["verification"]["status"] != "verified"}
    for o in facts["officials"]:
        for r in views.vote_list_rows(ix, o["id"]):
            assert not any(r["meeting_href"].endswith("#" + h) for h in held)
            if r["key"] != "absent":
                rc_id, oid = r["fact_id"].split("/")
                rc = ix.roll_calls[rc_id]
                assert any(v["official_id"] == o["id"] for v in rc["votes"])   # recorded by name for this person


def test_a_motion_without_a_roll_call_is_never_a_members_vote(facts):
    """A voice vote is a motion with no roll call in the facts: it adds no row for anyone."""
    f = json.loads(json.dumps(facts))
    before = {o["id"]: len(views.vote_list_rows(views.Index(f), o["id"])) for o in f["officials"]}
    mo = dict(f["motions"][0], id="mo-voice-only")
    f["motions"].append(mo)
    ix = views.Index(f)
    assert {o["id"]: len(views.vote_list_rows(ix, o["id"])) for o in f["officials"]} == before


def test_the_page_is_the_same_for_every_official(pages, facts):
    def skeleton(html):
        main = html[html.index("<main"):html.index("</main>")]
        words = re.sub(r"\d+", "N", re.sub(r"<[^>]+>", "", main.split("<tbody>")[0]))
        return (re.findall(r"<h[1-3][^>]*>", main), re.findall(r"<th[^>]*>(.*?)</th>", main),
                re.findall(r'<input type="radio" name="vote" value="([a-z]*)"', main), words.count("not confirmed*"))
    sk = {o["id"]: skeleton(pages[f"officials/{o['id']}/votes.html"]) for o in facts["officials"]}
    first = next(iter(sk.values()))
    assert all(v == first for v in sk.values())
    assert first[2] == ["", "yes", "no", "abstain", "other", "absent"]


def test_a_long_list_is_split_by_years_and_each_part_links_the_others(tmp_path, monkeypatch):
    from conftest import FIXTURE
    facts = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for m in sorted(facts["meetings"], key=lambda m: m["date"])[:2]:   # two years of votes, so there are years to split
        m["date"] = "2023" + m["date"][4:]
    path = tmp_path / "facts.json"
    path.write_text(json.dumps(facts), encoding="utf-8")
    oid = facts["officials"][0]["id"]
    rows = views.vote_list_rows(views.Index(facts), oid)
    assert len({r["date"][:4] for r in rows}) == 2
    monkeypatch.setattr(config, "PAGE_BYTES", 1)        # every list is "too long": one page per year
    monkeypatch.setattr(config, "PAGE_TARGET", 1)
    out = tmp_path / "site"
    build_mod.build(path, out)
    parts = sorted((out / "officials" / oid).glob("votes*.html"))
    assert len(parts) >= 2
    seen = []
    for p in parts:
        html = p.read_text(encoding="utf-8")
        assert html.count('aria-current="page"') >= 1 and 'class="vote-parts"' in html
        for q in parts:
            assert f'href="{q.name}"' in html
        seen += _rows(html)
    assert len(seen) == len(rows)
    official = (out / "officials" / f"{oid}.html").read_text(encoding="utf-8")
    assert (f"The list is long, so it is on {len(parts)} pages by year; these counts cover all of them."
            in official)
    from qa import site_checks
    problems, note = site_checks.check_vote_lists(out, facts)
    assert problems == [], problems


def _node():
    return shutil.which("node")


def _browser_ok():
    return bool(_node()) and (os.path.exists("/opt/pw-browsers") or bool(shutil.which("playwright")))


BROWSER_JS = r"""
const path = require('path'); const fs = require('fs');
let pw; for (const r of [process.env.NODE_PATH, '/opt/node22/lib/node_modules'].filter(Boolean)) { try { pw = require(path.join(r, 'playwright')); break; } catch (e) {} }
(async () => {
  const b = await pw.chromium.launch(); const out = {};
  for (const w of [375, 1280]) {
    const ctx = await b.newContext({ viewport: { width: w, height: 800 }, acceptDownloads: true }); const p = await ctx.newPage();
    const errs = []; p.on('pageerror', e => errs.push(String(e)));
    await p.goto('file://' + process.argv[1] + '?vote=no');
    const r = {};
    r.formShown = await p.isVisible('#vote-filter');
    r.checked = await p.$eval('input[name=vote]:checked', e => e.value);
    r.visible = await p.$$eval('#vote-table tbody tr[data-vote]', rs => rs.filter(x => !x.hidden).map(x => x.dataset.vote));
    r.status = await p.textContent('#vote-status');
    const [dl] = await Promise.all([p.waitForEvent('download'), p.click('#vote-csv')]);
    r.csv = fs.readFileSync(await dl.path(), 'utf8'); r.name = dl.suggestedFilename();
    await p.check('input[name=vote][value=""]');
    r.all = await p.$$eval('#vote-table tbody tr[data-vote]', rs => rs.filter(x => !x.hidden).length);
    r.sw = await p.evaluate(() => document.documentElement.scrollWidth); r.iw = w;
    r.errs = errs; out[w] = r; await ctx.close();
  }
  await b.close(); console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
"""


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_filter_and_csv_in_a_browser(built, facts):
    ix = views.Index(facts)
    o = max(facts["officials"], key=lambda o: views.official_counts(ix, o["id"])["no"])
    n_no = views.official_counts(ix, o["id"])["no"]
    total = len(views.vote_list_rows(ix, o["id"]))
    env = dict(os.environ)
    if "NODE_PATH" not in env:
        env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    r = subprocess.run(["node", "-e", BROWSER_JS, str(built / "officials" / o["id"] / "votes.html")],
                       capture_output=True, text=True, timeout=300, env=env)
    assert r.returncode == 0, r.stderr
    for w, x in json.loads(r.stdout).items():
        assert x["formShown"] and x["checked"] == "no" and not x["errs"], (w, x)
        assert x["visible"] == ["no"] * n_no, (w, x)
        assert x["csv"].startswith("\ufeff")       # UTF-8 byte order mark, for spreadsheets
        lines = x["csv"].lstrip("\ufeff").strip().split("\r\n")
        assert lines[0] == "date,item,vote_on,vote,record_page,source"
        assert len(lines) == 1 + n_no and all(',"No",' in ln for ln in lines[1:]), (w, lines)
        assert x["name"] == f"{o['id']}-votes-no.csv"
        assert x["all"] == total
        assert x["sw"] <= x["iw"], (w, x)          # nothing scrolls sideways


def test_a_preview_over_its_cap_leaves_the_vote_lists_out_and_says_so(tmp_path, monkeypatch):
    """The claude.ai preview (500 files): after the transcript pages and the export, the vote list pages go, and every
    official page says the list is on the full site instead of linking a page that is not there."""
    from conftest import FIXTURE
    out = tmp_path / "site"
    full = build_mod.build(FIXTURE, out, target="preview")
    assert full["vote_lists"]
    monkeypatch.setitem(config.MAX_FILES_BY_TARGET, "preview", full["files"] - 2)   # still over without the export
    res = build_mod.build(FIXTURE, out, target="preview")
    assert res["vote_lists"] is False
    assert not list((out / "officials").rglob("votes*.html"))
    facts = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for o in facts["officials"]:
        html = (out / "officials" / f"{o['id']}.html").read_text(encoding="utf-8")
        assert "/votes.html" not in html and "is on the full site; this preview leaves those pages out." in html


def test_site_checks_recount_every_vote_list_and_catch_a_wrong_row(built, facts, tmp_path):
    """qa/site_checks.py vote-list: recounted from the facts, not from sitegen."""
    import shutil as sh
    from qa import site_checks
    problems, note = site_checks.check_vote_lists(built, facts)
    assert problems == [] and note.startswith(f"{len(facts['officials'])} vote lists")
    site = tmp_path / "s"
    sh.copytree(built, site)
    oid = facts["officials"][0]["id"]
    f = site / "officials" / oid / "votes.html"
    f.write_text(f.read_text(encoding="utf-8").replace('<tr data-vote="yes"', '<tr data-vote="no"', 1), encoding="utf-8")
    problems, _ = site_checks.check_vote_lists(site, facts)
    assert any("rows differ from the facts" in p for p in problems)
    assert any("filter counts" in p for p in problems)


def test_site_checks_catch_a_row_the_parser_cannot_read(built, facts, tmp_path):
    """votes/check-unparsed-rows: a <tr> written with attributes in another order still shows on the page (votes.js
    takes every tbody tr[data-vote]), so the check counts every <tr> and fails when it cannot read one."""
    import shutil as sh
    from qa import site_checks
    site = tmp_path / "s"
    sh.copytree(built, site)
    oid = next(o["id"] for o in facts["officials"] if (site / "officials" / o["id"] / "votes.html").is_file()
               and '<tr data-vote="' in (site / "officials" / o["id"] / "votes.html").read_text(encoding="utf-8"))
    f = site / "officials" / oid / "votes.html"
    f.write_text(re.sub(r'<tr data-vote="([a-z]*)" data-date="([\d-]+)">', r'<tr data-date="\2" data-vote="\1">',
                        f.read_text(encoding="utf-8"), count=1), encoding="utf-8")
    problems, _ = site_checks.check_vote_lists(site, facts)
    assert any("<tr> rows in the table body" in p for p in problems)


def test_site_checks_accept_a_left_out_vote_list_only_on_the_preview_target(built, facts, tmp_path):
    """votes/check-omitted-any-target: the 'left out (preview)' pass is for the preview target only."""
    import shutil as sh
    from qa import site_checks
    site = tmp_path / "s"
    sh.copytree(built, site)
    oid = facts["officials"][0]["id"]
    shutil.rmtree(site / "officials" / oid)
    page = site / "officials" / f"{oid}.html"
    page.write_text(page.read_text(encoding="utf-8") + f"<p>x {site_checks.VL_OMITTED}</p>", encoding="utf-8")
    problems, note = site_checks.check_vote_lists(site, facts, target="preview")
    assert not any(oid in p for p in problems) and "1 left out (preview)" in note
    problems, _ = site_checks.check_vote_lists(site, facts, target="pages")
    assert any(oid in p and "only the preview target" in p for p in problems)
