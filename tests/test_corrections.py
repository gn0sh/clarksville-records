"""M1.5 correction intake (docs/design/correction-intake.md): the "Report an error" links on every fact-bearing page,
report.html with the channels config/site.yml `corrections:` turns on, the GitHub issue form, and static/report.js,
which must never inject the URL's fragment as HTML. Problem-key family: corrections/*."""
import json
import os
import shutil
import subprocess
from urllib.parse import parse_qs, quote, urlsplit

import pytest
import yaml

from conftest import FIXTURE, FIXTURE_DISTRICTS, FIXTURE_SEATS, ROOT, parse
from qa import site_checks
from sitegen import build as sitegen_build, config, views
from test_council_pages import CFG, CITY, MEETINGS, subset
from test_fin_pages import FIN
from test_site_neutrality import BANNED

REPORT_JS = ROOT / "site" / "static" / "report.js"
FORM = ROOT / ".github" / "ISSUE_TEMPLATE" / views.CORRECTION_FORM
CLOSED = "Corrections open when the site launches."
JS_SAFE = "!'()*~"   # what encodeURIComponent leaves as is
ON = {"github_repo": "example-owner/example-records", "email": "corrections@example.org"}


@pytest.fixture(scope="module")
def full(tmp_path_factory):
    """The fixture county with the finance fixture and the council fixture: every fact-bearing page type."""
    d = tmp_path_factory.mktemp("corr")
    city = subset(json.loads((CITY / "facts.json").read_text(encoding="utf-8")), MEETINGS)
    wards = [w for w in json.loads((CITY / "wards.json").read_text(encoding="utf-8")) if w["meeting_id"] in MEETINGS]
    (d / "facts.json").write_text(json.dumps(city), encoding="utf-8")
    (d / "wards.json").write_text(json.dumps(wards), encoding="utf-8")
    cfg = {**CFG, "facts_path": d / "facts.json", "wards_path": d / "wards.json"}
    out = d / "build" / "site"
    sitegen_build.build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS, finance_path=FIN,
                        councils=[cfg])
    return out, {p.relative_to(out).as_posix(): p.read_text(encoding="utf-8") for p in out.rglob("*.html")}


def page_link(html: str):
    return [n for n in parse(html).walk() if n.tag == "p" and n.attrs.get("class") == "report-page"]


# -- links on every fact-bearing page type (corrections/link-missing)

WANT_TYPES = {"meeting", "items", "official", "votes", "district", "finance_index", "fund", "capital",
              "contracts_index", "contract", "council_home", "council_member", "council_meetings", "council_items"}


def test_every_fact_page_type_has_the_page_level_link(full):
    out, pages = full
    seen = set()
    for rel, html in pages.items():
        t = site_checks.page_type(rel)
        if t not in WANT_TYPES:
            continue
        seen.add(t)
        got = page_link(html)
        assert len(got) == 1, rel
        a = [c for c in got[0].walk() if c.tag == "a"]
        root = "../" * rel.count("/")
        assert [x.attrs["href"] for x in a] == [f"{root}report.html"], rel
        assert a[0].all_text() == "Report an error on this page"
    assert seen == WANT_TYPES, WANT_TYPES - seen


def test_no_page_level_link_where_there_are_no_facts(full):
    _, pages = full
    for rel in ("index.html", "about.html", "search.html", "report.html", "changes.html", "data.html"):
        assert not page_link(pages[rel]), rel


def test_every_fact_row_report_link_goes_to_the_report_page(full):
    out, pages = full
    n = 0
    for rel, html in pages.items():
        root = "../" * rel.count("/")
        for el in parse(html).walk():
            if "data-fact-id" not in el.attrs:
                continue
            hrefs = [a.attrs.get("href") for a in el.walk() if a.tag == "a" and a.all_text() == "Report an error"]
            if hrefs:
                n += 1
                assert hrefs == [f"{root}report.html"], (rel, el.attrs["data-fact-id"])
        assert "about.html#corrections" not in html, rel
    assert n > 50
    assert (out / "static" / "report.js").is_file()


def test_report_page_links_resolve(full):
    out, _ = full
    pages = {p.relative_to(out).as_posix(): site_checks.parse(p) for p in out.rglob("*.html")}
    assert site_checks.check_links(out, pages, no_export=True) == []
    assert site_checks.check_external(pages) == []


# -- config off / on (corrections/config)

def render_report(monkeypatch, corrections):
    monkeypatch.setitem(config.SITE, "corrections", corrections)
    ix = views.Index(json.loads(FIXTURE.read_text(encoding="utf-8")))
    return sitegen_build.make_env().get_template("report.html.j2").render(
        site=views.site_context(ix), root="", page_name="Report an error", **views.report_page())


def _page(html: str) -> site_checks.Page:
    p = site_checks.Page()
    p.feed(html)
    return p


def test_report_page_closed_without_a_channel(monkeypatch):
    html = render_report(monkeypatch, {"github_repo": "", "email": ""})
    assert CLOSED in html
    assert 'id="report-issue"' not in html and 'id="report-mail"' not in html and "mailto:" not in html
    assert "What to include" in html and "static/report.js" in html
    assert "The link" not in html and "links above" not in html


def test_the_real_config_opens_github_issues_on_the_public_repo(monkeypatch):
    """corrections/channel-set-in-production-build (manager decision 2026-11-10): the channel is GitHub issues on
    gn0sh/clarksville-records; an email may be added at go-live."""
    assert config.SITE["corrections"]["github_repo"] == "gn0sh/clarksville-records"
    html = render_report(monkeypatch, config.SITE["corrections"])
    assert CLOSED not in html
    a = next(a for a in parse(html).walk() if a.tag == "a" and a.attrs.get("id") == "report-issue")
    assert a.attrs["href"] == "https://github.com/gn0sh/clarksville-records/issues/new?template=correction.yml"
    assert "Open an issue on GitHub" in "".join(a.text)
    if not config.SITE["corrections"]["email"]:
        assert "The link above opens GitHub only when you choose it." in html and "email program" not in html


@pytest.mark.parametrize("corr, target, bad", [
    ({"github_repo": "o/n", "email": ""}, "pages", None),
    ({"github_repo": "", "email": "a@example.org"}, "pages", None),
    ({"github_repo": "", "email": ""}, "pages", "offers no channel"),
    ({"github_repo": "", "email": ""}, "preview", None),          # the claude.ai preview is not the public site
])
def test_site_checks_fail_a_pages_build_without_a_report_channel(monkeypatch, corr, target, bad):
    html = render_report(monkeypatch, corr)
    problems, _ = site_checks.check_report_channel({"report.html": _page(html)},
                                                   {"corrections": corr}, target)
    assert (problems == []) if bad is None else any(bad in p for p in problems), problems


def test_site_checks_fail_a_report_page_that_does_not_link_the_configured_channel(monkeypatch):
    closed = render_report(monkeypatch, {"github_repo": "", "email": ""})
    problems, _ = site_checks.check_report_channel({"report.html": _page(closed)},
                                                   {"corrections": {"github_repo": "o/n", "email": ""}}, "pages")
    assert any("does not link https://github.com/o/n/issues/new" in p for p in problems)
    assert any("not open" in p for p in problems)
    assert site_checks.check_report_channel({}, {"corrections": {"github_repo": "o/n"}}, "pages")[0] == \
        ["report.html is not built"]


@pytest.mark.parametrize("on", [ON, {**ON, "email": ""}, {**ON, "github_repo": ""}])
def test_report_page_on(monkeypatch, on):
    html = render_report(monkeypatch, on)
    assert CLOSED not in html
    links = {a.attrs.get("id"): a for a in parse(html).walk() if a.tag == "a" and a.attrs.get("id")}
    if on["github_repo"]:
        a = links["report-issue"]
        assert a.attrs["href"] == "https://github.com/example-owner/example-records/issues/new?template=correction.yml"
        assert a.attrs["data-ext"] == "corrections" and "noreferrer" in a.attrs["rel"]
        assert a.attrs["href"] in site_checks.allowed_external(config.SITE, None, None)
    else:
        assert "report-issue" not in links
    if on["email"]:
        assert links["report-mail"].attrs["href"] == "mailto:corrections@example.org"
        assert site_checks.corrections_links(config.SITE)[1] == "mailto:corrections@example.org"
    else:
        assert "report-mail" not in links


def test_report_link_survives_site_checks_when_on(monkeypatch, tmp_path):
    monkeypatch.setitem(config.SITE, "corrections", ON)
    monkeypatch.setattr(site_checks, "_site_cfg", lambda: config.SITE)
    out = tmp_path / "site"
    sitegen_build.build(FIXTURE, out, seats_path=FIXTURE_SEATS, districts_path=FIXTURE_DISTRICTS)
    pg = {"report.html": site_checks.parse(out / "report.html")}
    assert site_checks.check_links(out, pg, no_export=True) == []
    facts = json.loads(FIXTURE.read_text(encoding="utf-8"))
    problems, _ = site_checks.check_sources(out, pg, facts, None, site_checks.allowed_external(config.SITE, None, None))
    assert problems == []


@pytest.mark.parametrize("bad, msg", [
    ({"github_repo": "owner/name?x=1"}, "owner/name"),
    ({"github_repo": "https://github.com/owner/name"}, "owner/name"),
    ({"github_repo": "owner/../x"}, "owner/name"),
    ({"github_repo": "o/."}, "owner/name"),      # corr-config/repo-dot
    ({"github_repo": "o/.."}, "owner/name"),
    ({"github_repo": "./x"}, "owner/name"),
    ({"github_repo": 'own"er/name'}, "owner/name"),
    ({"email": "a@b.org?cc=x@y.org"}, "plain address"),
    ({"email": "<script>@x.org"}, "plain address"),
    ({"email": "a b@x.org"}, "plain address"),
    ({"email": "nobody"}, "plain address"),
    ({"github_repo": "", "email": "", "extra": "x"}, "unknown key"),
])
def test_bad_corrections_config_fails_the_build(bad, msg):
    problems = sitegen_build.site_url_problems({**config.SITE, "corrections": bad})
    assert any(msg in p for p in problems), problems


def test_good_corrections_config_passes():
    assert sitegen_build.site_url_problems({**config.SITE, "corrections": ON}) == []
    assert sitegen_build.site_url_problems(config.SITE) == []


# -- wording (corrections/wording)

def test_report_wording_is_neutral_and_about_explains_corrections(full):
    _, pages = full
    main = pages["report.html"].split('<main id="main">')[1].split("</main>")[0]
    assert BANNED.search(main) is None
    about = pages["about.html"]
    assert 'id="how-corrections-work"' in about
    assert "a value is never changed without a source" in about
    assert 'href="report.html"' in about


def test_report_js_never_writes_html():
    js = REPORT_JS.read_text(encoding="utf-8")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "localStorage",
                "sessionStorage", "document.cookie", "fetch(", "XMLHttpRequest", "sendBeacon"):
        code = "\n".join(line for line in js.splitlines() if not line.lstrip().startswith(("/*", "*", "//")))
        assert bad not in code.replace("(never innerHTML)", ""), bad


# -- the issue form (corrections/issue-form)

def test_issue_form_is_valid():
    form = yaml.safe_load(FORM.read_text(encoding="utf-8"))
    assert {"name", "description", "body"} <= set(form)
    assert all(isinstance(form[k], str) and form[k].strip() for k in ("name", "description"))
    ids = []
    for el in form["body"]:
        assert el["type"] in {"markdown", "input", "textarea", "dropdown", "checkboxes"}, el
        if el["type"] == "markdown":
            assert el["attributes"]["value"].strip()
            assert "id" not in el
            continue
        assert el["attributes"]["label"].strip()
        assert set(el.get("validations", {})) <= {"required"}
        ids.append(el["id"])
    assert len(ids) == len(set(ids))
    assert all(i.replace("_", "").isalnum() for i in ids)
    assert set(views.CORRECTION_FIELDS) <= set(ids)
    js = REPORT_JS.read_text(encoding="utf-8")
    assert all(f'"&{f}="' in js for f in views.CORRECTION_FIELDS)


# -- static/report.js under node: the fragment is filtered and every value URL-encoded (corrections/encoding)

HOSTILE = [
    "#page=<script>alert(1)</script>.html&id=\"><img src=x onerror=alert(1)>",
    "#page=%3Cscript%3Ealert(1)%3C%2Fscript%3E&id=%22%3E%3Cimg%20src%3Dx%20onerror%3Dalert(1)%3E",
    "#page=javascript:alert(1)//.html&id=a'b",
    "#page=https://evil.example/x.html&id=x%00y",
    "#page=../../etc/passwd.html&id=%E0%A4%A",
    "#page=meetings//x.html&id=" + "a" * 161,
    "#page=/meetings/x.html&id=<b>",
]

NODE = r"""
const r = require(process.argv[2]);
const out = {hostile: [], ok: null, links: null};
for (const h of JSON.parse(process.argv[3])) out.hostile.push(r.parseHash(h));
out.ok = r.parseHash("#page=meetings%2F2024-01-08.html&id=rc-2024-01-08-3%2Fo-smith&junk=1");
const pageUrl = "https://example.org/meetings/x.html?a=1&title=evil#\"<script>'";
const l = r.links({page: "meetings/x.html", id: "rc-1/o-a"}, pageUrl,
  "https://github.com/o/n/issues/new?template=correction.yml", "mailto:c@example.org");
const u = new URL(l.issue);
out.links = {issue: l.issue, mail: l.mail, titles: u.searchParams.getAll("title"),
  page_url: u.searchParams.getAll("page_url"), fact_id: u.searchParams.getAll("fact_id"),
  template: u.searchParams.getAll("template")};
out.refused = r.links({id: "x"}, "", "javascript:alert(1)//https://github.com/", "mailto:a@b.org?cc=z@y.org");
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node not available")
def test_report_js_filters_and_encodes(tmp_path):
    script = tmp_path / "probe.js"
    script.write_text(NODE, encoding="utf-8")
    res = subprocess.run(["node", str(script), str(REPORT_JS), json.dumps(HOSTILE)], capture_output=True, text=True,
                         timeout=60)
    assert res.returncode == 0, res.stderr
    r = json.loads(res.stdout)
    assert r["hostile"] == [{}] * len(HOSTILE)
    assert r["ok"] == {"page": "meetings/2024-01-08.html", "id": "rc-2024-01-08-3/o-smith"}
    L = r["links"]
    for href in (L["issue"], L["mail"]):
        for ch in "<>\"' #\n":
            assert ch not in href.split("?", 1)[1], (ch, href)
    assert L["titles"] == ["Correction: rc-1/o-a"] and L["template"] == ["correction.yml"]
    assert L["page_url"] == ["https://example.org/meetings/x.html?a=1&title=evil#\"<script>'"]
    assert L["fact_id"] == ["rc-1/o-a"]
    mail = urlsplit(L["mail"])
    q = parse_qs(mail.query)
    assert mail.scheme == "mailto" and mail.path == "c@example.org" and set(q) == {"subject", "body"}
    assert "Fact id: rc-1/o-a" in q["body"][0]
    assert r["refused"] == {"issue": "", "mail": ""}


# -- in a browser: the fragment is shown as text, nothing is injected, nav.js fills the link (corrections/xss)

def _browser_ok():
    return bool(shutil.which("node")) and (os.path.exists("/opt/pw-browsers") or bool(shutil.which("playwright")))


BROWSER = r"""
const path = require('path');
let pw;
for (const r of ['', ...(process.env.NODE_PATH || '').split(path.delimiter).filter(Boolean)]) {
  try { pw = require(r ? path.join(r, 'playwright') : 'playwright'); break; } catch (e) { /* next */ }
}
(async () => {
  const [site, meeting, hostile] = process.argv.slice(2);
  const browser = await pw.chromium.launch();
  const page = await browser.newPage();
  const out = {dialogs: 0, errors: []};
  page.on('dialog', d => { out.dialogs++; d.dismiss(); });
  page.on('pageerror', e => out.errors.push(String(e)));
  const base = 'file://' + site + '/';
  out.hostile = [];
  for (const h of JSON.parse(hostile)) {
    await page.goto('about:blank');   // a fresh load each time (a fragment-only change would not rerun the script)
    await page.goto(base + 'report.html' + h);
    await page.waitForTimeout(50);
    out.hostile.push(await page.evaluate(() => ({
      hidden: document.getElementById('report-about').hidden,
      imgs: document.querySelectorAll('img:not(.gc-logo)').length,
      scripts: [...document.scripts].map(s => s.getAttribute('src')),
      text: document.getElementById('report-about').textContent,
    })));
  }
  await page.goto('about:blank');
  await page.goto(base + 'report.html#page=meetings%2Fx.html&id=%3Cb%3E');
  out.badId = await page.evaluate(() => ({hidden: document.getElementById('report-about').hidden,
    page: document.getElementById('report-page-url').textContent,
    id: document.getElementById('report-fact-id').textContent, bold: document.querySelectorAll('b').length}));
  // nav.js: following a row's Report an error link carries the page path and the row's fact id
  await page.goto(base + meeting);
  const a = await page.$('[data-fact-id] a[href$="report.html"]');   // a handle: the href changes below
  out.factId = await a.evaluate(el => el.closest('[data-fact-id]').getAttribute('data-fact-id'));
  await a.dispatchEvent('mousedown');
  out.href = await a.getAttribute('href');
  await Promise.all([page.waitForEvent('load'), a.evaluate(el => el.click())]);
  out.landed = await page.evaluate(() => ({url: location.pathname + location.hash,
    page: document.getElementById('report-page-url').textContent,
    id: document.getElementById('report-fact-id').textContent}));
  await browser.close();
  console.log(JSON.stringify(out));
})();
"""


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_report_page_in_a_browser(full, tmp_path):
    out, pages = full
    meeting = next(r for r in sorted(pages) if r.startswith("meetings/") and "data-fact-id" in pages[r])
    script = tmp_path / "probe.js"
    script.write_text(BROWSER, encoding="utf-8")
    env = dict(os.environ)
    env.setdefault("NODE_PATH", subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip())
    res = subprocess.run(["node", str(script), str(out.resolve()), meeting, json.dumps(HOSTILE)], capture_output=True,
                         text=True, timeout=180, env=env)
    assert res.returncode == 0, res.stderr
    r = json.loads(res.stdout.strip().splitlines()[-1])
    assert r["errors"] == [] and r["dialogs"] == 0
    for h in r["hostile"]:
        assert h["hidden"] is True and h["imgs"] == 0
        assert all(s and s.startswith("static/") for s in h["scripts"]), h["scripts"]
    # a well-formed path that is not a built page is labelled, never shown as a page of this site (report-frag/text-spoof)
    assert r["badId"] == {"hidden": False, "page": "meetings/x.html (not a page of this site)", "id": "Not given",
                          "bold": 0}
    assert r["href"].startswith("../report.html#page=" + quote(meeting, safe=JS_SAFE)), r
    assert r["href"].endswith("&id=" + quote(r["factId"], safe=JS_SAFE))
    assert r["landed"]["page"] == meeting      # a file:// site shows the path, never a local file address
    assert r["landed"]["id"] == r["factId"]


# -- report-frag/text-spoof: the page path is checked against the built page list; the about box says it is from the link

def test_build_writes_the_page_list_and_report_page_loads_it_first(full):
    out, pages = full
    js = (out / "static" / "pages.js").read_text(encoding="utf-8")
    listed = json.loads(js.split("=", 1)[1].strip().rstrip(";"))
    assert set(listed) == set(pages) and "report.html" in listed
    html = pages["report.html"]
    assert html.index("static/pages.js") < html.index("static/report.js")
    assert "from the link you followed (not checked" in html


@pytest.mark.skipif(not shutil.which("node"), reason="node not available")
def test_report_js_page_status(tmp_path):
    script = tmp_path / "probe.js"
    script.write_text(
        'const r = require(process.argv[2]); const L = ["a.html", "meetings/x.html"];'
        'console.log(JSON.stringify([r.pageStatus("a.html", L), r.pageStatus("evil/made-up.html", L),'
        'r.pageStatus("a.html", undefined), r.pageStatus(undefined, L)]));', encoding="utf-8")
    res = subprocess.run(["node", str(script), str(REPORT_JS)], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout) == ["known", "unknown", "unchecked", "none"]


# -- nav-report/regex-overmatch and hash-decode/finance-uncaught, in a browser

BROWSER2 = r"""
const path = require('path');
let pw;
for (const r of ['', ...(process.env.NODE_PATH || '').split(path.delimiter).filter(Boolean)]) {
  try { pw = require(r ? path.join(r, 'playwright') : 'playwright'); break; } catch (e) { /* next */ }
}
(async () => {
  const [site, meeting, fin] = process.argv.slice(2);
  const browser = await pw.chromium.launch();
  const page = await browser.newPage();
  const out = {errors: []};
  page.on('pageerror', e => out.errors.push(String(e)));
  const base = 'file://' + site + '/';
  await page.goto(base + meeting);
  out.nav = await page.evaluate(() => {
    const hrefs = ['https://evil.example/report.html', '//evil.example/report.html', 'https://evil.example/x/report.html#a',
                   '../report.html', 'report.html'];
    const res = [];
    for (const h of hrefs) {
      const a = document.createElement('a'); a.setAttribute('href', h); document.body.appendChild(a);
      a.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
      res.push([h, a.getAttribute('href')]);
    }
    return res;
  });
  await page.goto('about:blank');
  await page.goto(base + fin + '#%E0%A4%A');       // a malformed escape in the hash
  await page.waitForTimeout(100);
  out.finOpen = await page.evaluate(() => document.querySelectorAll('details.fin-group').length);
  await browser.close();
  console.log(JSON.stringify(out));
})();
"""


@pytest.mark.skipif(not _browser_ok(), reason="Playwright (node) not available")
def test_nav_rewrites_only_own_report_links_and_finance_ignores_a_bad_hash(full, tmp_path):
    out, pages = full
    meeting = next(r for r in sorted(pages) if r.startswith("meetings/") and "data-fact-id" in pages[r])
    fin = next(r for r in sorted(pages) if "fin-group" in pages[r])
    script = tmp_path / "probe2.js"
    script.write_text(BROWSER2, encoding="utf-8")
    env = dict(os.environ)
    env.setdefault("NODE_PATH", subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip())
    res = subprocess.run(["node", str(script), str(out.resolve()), meeting, fin], capture_output=True, text=True,
                         timeout=180, env=env)
    assert res.returncode == 0, res.stderr
    r = json.loads(res.stdout.strip().splitlines()[-1])
    assert r["errors"] == [], r["errors"]            # finance.js did not throw on the bad hash
    assert r["finOpen"] >= 1
    by = dict(map(tuple, r["nav"]))
    for off in ("https://evil.example/report.html", "//evil.example/report.html", "https://evil.example/x/report.html#a"):
        assert by[off] == off, by                    # off-site links are left exactly as written
    assert by["../report.html"].startswith("../report.html#page=") and by["report.html"].startswith("report.html#page=")
