"""Landing: the address search leads and the map is second; "Your seats" (static/seats.js) keeps the visitor's ward and
district numbers in this browser only, under one namespaced key, and survives blocked or throwing storage."""
import json
import re
import shutil
import subprocess

import pytest

from conftest import FIXTURE, ROOT, build, parse
from sitegen import config
from test_council_pages import cfg, city_facts, city_wards, cpages, site  # noqa: F401  (council fixture site)

SEATS_JS = ROOT / "site" / "static" / "seats.js"
ADDRESS_JS = ROOT / "site" / "static" / "address.js"


@pytest.fixture(scope="module")
def addr_site(tmp_path_factory):
    out = tmp_path_factory.mktemp("seats") / "build" / "site"
    build(FIXTURE, out, seats_path=None, districts_path=config.DISTRICTS_PATH)
    return out


def test_address_search_precedes_the_map_in_the_dom(addr_site):
    html = (addr_site / "index.html").read_text(encoding="utf-8")
    assert html.index('id="your-seats"') < html.index('id="addr-form"') < html.index("<svg class=\"county-map")
    assert html.index('id="addr-form"') < html.index('class="landing-grid"') < html.index("<svg class=\"county-map")
    form = next(n for n in parse(html).walk() if n.attrs.get("id") == "addr-form")
    label = next(n for n in form.walk() if n.tag == "label")
    assert " ".join(label.all_text().split()).startswith("Find your ")
    assert " by address" in label.all_text() and label.attrs["for"] == "addr-q"
    assert "<h1" in html[:html.index('id="addr-form"')]                      # the purpose line still leads
    assert re.search(r'static/seats\.js" defer></script>\s*<script src="static/georef\.js" defer></script>\s*'
                     r'<script src="static/address\.js" defer>', html)       # seats.js loads before address.js


def test_your_seats_box_has_a_forget_button_and_the_storage_line(addr_site):
    html = (addr_site / "index.html").read_text(encoding="utf-8")
    box = next(n for n in parse(html).walk() if n.attrs.get("id") == "your-seats")
    assert "hidden" in box.attrs                                             # shown by the script, on a later visit
    btn = next(n for n in box.walk() if n.tag == "button")
    assert btn.attrs["type"] == "button" and btn.attrs["id"] == "seats-forget" and btn.all_text().strip() == "Forget"
    assert "Saved only in this browser, on this device." in " ".join(box.all_text().split())
    assert "no cookies" in box.all_text()
    assert "No cookies." in html                                              # the address box's own one-line notice
    method = (addr_site / "method.html").read_text(encoding="utf-8")
    assert "cr-your-seats" in method and "never sent anywhere" in method and "sets no cookies" in method


def test_no_inline_script_or_handler_was_added_for_seats(addr_site):
    html = (addr_site / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"\son(click|load|submit)=", html)
    inline = re.findall(r"<script(?![^>]*\ssrc=)(?![^>]*application/json)[^>]*>", html)
    assert inline == [], inline                                              # the CSP allows no inline script here


def test_seat_list_links_resolve(cpages, site):  # noqa: F811
    out, _ = site
    tree = parse(cpages["index.html"])
    rows = [n for n in tree.walk() if n.tag == "li" and ("data-seat" in n.attrs or "data-district" in n.attrs)]
    assert rows and any("data-seat" in r.attrs for r in rows) and any("data-district" in r.attrs for r in rows)
    ids_by_page = {}
    for r in rows:
        a = next(c for c in r.children if c.tag == "a")
        assert a.attrs["href"] and any("d-label" in c.attrs.get("class", "") for c in a.walk())
        path, _, frag = a.attrs["href"].partition("#")
        target = out / path
        assert target.is_file(), a.attrs["href"]
        if frag:
            ids = ids_by_page.setdefault(path, set(re.findall(r'id="([^"]+)"', target.read_text(encoding="utf-8"))))
            assert frag in ids, a.attrs["href"]


def test_the_script_uses_one_namespaced_key_and_no_other_channel():
    js = SEATS_JS.read_text(encoding="utf-8")
    assert re.findall(r'"(cr-[a-z-]+)"', js) == ["cr-your-seats"]
    for banned in ("document.cookie", "sessionStorage", "indexedDB", "fetch(", "XMLHttpRequest", "sendBeacon",
                   "innerHTML", "eval(", "WebSocket"):
        assert banned not in js, banned
    assert len(re.findall(r"\.(?:setItem|getItem|removeItem)\(", js)) == 3
    assert all(re.search(r"\btry \{[^}]*" + m, js) for m in ("getItem", "setItem", "removeItem"))
    code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    assert code.count("localStorage") == 1                                  # reached only through the try/catch store()
    assert "CRSeats.save({ district: r.district })" in ADDRESS_JS.read_text(encoding="utf-8")


@pytest.mark.skipif(not shutil.which("node"), reason="node not available")
def test_seats_script_reads_writes_and_handles_storage_exceptions(tmp_path):
    prog = f"""
const assert = require("assert");
const eq = (a, b) => assert.strictEqual(JSON.stringify(a), JSON.stringify(b));  // the script runs in another realm
const S = require({json.dumps(str(SEATS_JS))});
function fake(opts) {{
  const data = {{}}; const calls = [];
  const ls = {{
    getItem(k) {{ calls.push(['get', k]); if (opts.get) throw new Error('denied'); return k in data ? data[k] : null; }},
    setItem(k, v) {{ calls.push(['set', k]); if (opts.set) throw new Error('quota'); data[k] = String(v); }},
    removeItem(k) {{ calls.push(['rm', k]); if (opts.rm) throw new Error('denied'); delete data[k]; }},
  }};
  return {{ data, calls, ls }};
}}
// the script reads window.localStorage; run a fresh copy of it against a fake window
const vm = require('vm'); const fs = require('fs');
function load(win) {{
  const src = fs.readFileSync({json.dumps(str(SEATS_JS))}, 'utf8');
  const m = {{ exports: {{}} }};
  vm.runInNewContext(src, {{ module: m, window: win }}, {{ filename: 'seats.js' }});
  return m.exports;
}}
// 1. normal use: one key, only two numbers, merged, then forgotten
let f = fake({{}}); let api = load({{ localStorage: f.ls }});
assert.strictEqual(api.read(), null);
assert.strictEqual(api.save({{ district: 5 }}), true);
eq(api.read(), {{ district: 5, ward: null }});
assert.strictEqual(api.save({{ ward: 3 }}), true);
eq(api.read(), {{ district: 5, ward: 3 }});
eq(Object.keys(f.data), ['cr-your-seats']);
eq(JSON.parse(f.data['cr-your-seats']), {{ district: 5, ward: 3 }});
assert.ok(f.calls.every((c) => c[1] === 'cr-your-seats'));
assert.strictEqual(api.forget(), true); eq(f.data, {{}});
// 2. junk in, nothing out; junk never written
for (const bad of [{{ district: '5' }}, {{ district: 0 }}, {{ district: 1.5 }}, {{ district: 1e9 }}, {{ ward: null }}, null, 'x', []]) {{
  assert.strictEqual(api.save(bad), false); }}
eq(f.data, {{}});
for (const raw of [null, '', '{{', '[]', '"a"', '{{"district":"x"}}', '{{"href":"https://evil.example"}}']) {{
  assert.strictEqual(api.parse(raw), null, String(raw)); }}
eq(api.parse('{{"district":4,"href":"https://evil.example"}}'), {{ district: 4, ward: null }});
// 3. every storage call may throw: no exception escapes, the answer is "nothing"
for (const opts of [{{ get: 1 }}, {{ set: 1 }}, {{ rm: 1 }}, {{ get: 1, set: 1, rm: 1 }}]) {{
  const g = fake(opts); const a = load({{ localStorage: g.ls }});
  assert.doesNotThrow(() => {{ a.read(); a.save({{ district: 2 }}); a.forget(); }});
}}
assert.strictEqual(load({{ localStorage: fake({{ get: 1 }}).ls }}).read(), null);
assert.strictEqual(load({{ localStorage: fake({{ set: 1 }}).ls }}).save({{ district: 2 }}), false);
// 4. the storage accessor itself may throw (blocked site data), or be absent
const blocked = {{}}; Object.defineProperty(blocked, 'localStorage', {{ get() {{ throw new Error('SecurityError'); }} }});
for (const win of [blocked, {{}}]) {{
  const a = load(win);
  assert.strictEqual(a.read(), null); assert.strictEqual(a.save({{ district: 2 }}), false); assert.strictEqual(a.forget(), false);
}}
console.log('ok');
"""
    p = tmp_path / "seats_test.js"
    p.write_text(prog, encoding="utf-8")
    res = subprocess.run(["node", str(p)], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0 and res.stdout.strip() == "ok", res.stderr
