"""perf/clamp-layout-thrash: site/static/clamp.js reads every height before it writes, runs resize at most once a
frame, and on a <details> toggle measures only the .clamp inside it. Runs the script under node with a stub DOM that
logs each layout read and each write."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "site" / "static" / "clamp.js"

HARNESS = r"""
const log = [];
function el(name, tall) {
  const cls = new Set(name === "inner" ? ["clamp", "in-details"] : ["clamp"]);
  const e = {
    name, id: "", next: null,
    classList: {
      add: c => { log.push("write " + name); cls.add(c); },
      remove: c => { log.push("write " + name); cls.delete(c); },
      toggle: (c, on) => { on ? cls.add(c) : cls.delete(c); },
      contains: c => cls.has(c),
    },
    style: { setProperty: () => log.push("write " + name) },
    getAttribute: a => (a === "data-lines" ? "2" : null),
    get nextElementSibling() { return e.next; },
    get clientHeight() { log.push("read " + name); return 40; },
    get scrollHeight() { log.push("read " + name); return tall ? 200 : 40; },
    insertAdjacentElement: (_, b) => { log.push("write " + name); e.next = b; },
  };
  return e;
}
const els = [el("a", true), el("b", false), el("c", true), el("inner", true)];
const listeners = {};
let frames = [];
global.document = {
  documentElement: { classList: { add: () => {} } },
  querySelectorAll: () => els,
  createElement: () => ({ classList: { contains: c => c === "clamp-btn" }, setAttribute() {}, getAttribute: () => "false",
                          addEventListener() {}, remove() {} }),
  addEventListener: (t, f) => { listeners[t] = f; },
};
global.window = {
  addEventListener: (t, f) => { listeners[t] = f; },
  requestAnimationFrame: f => { frames.push(f); },
};
require(process.argv[2]);
const out = { first: log.splice(0) };
listeners.resize(); listeners.resize(); listeners.resize();
out.frames = frames.length;
frames.forEach(f => f()); frames = [];
out.resize = log.splice(0);
const details = { open: true, querySelectorAll: () => els.filter(e => e.name === "inner") };
listeners.toggle({ target: details });
out.toggle = log.splice(0);
listeners.toggle({ target: { open: false, querySelectorAll: () => els } });
out.closed = log.splice(0);
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    h = tmp_path_factory.mktemp("clamp") / "harness.js"
    h.write_text(HARNESS, encoding="utf-8")
    res = subprocess.run(["node", str(h), str(SCRIPT)], capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def _reads_then_writes(log):
    """No write between the first and the last read: one layout per pass."""
    reads = [i for i, x in enumerate(log) if x.startswith("read")]
    assert reads, log
    assert not [x for x in log[reads[0]:reads[-1]] if x.startswith("write")], log


def test_one_pass_reads_every_height_before_writing(run):
    _reads_then_writes(run["first"])
    assert {x.split()[1] for x in run["first"] if x.startswith("read")} == {"a", "b", "c", "inner"}


def test_resize_runs_once_per_frame(run):
    assert run["frames"] == 1
    _reads_then_writes(run["resize"])


def test_opening_details_measures_only_the_clamp_inside_it(run):
    assert {x.split()[1] for x in run["toggle"]} == {"inner"}
    assert run["closed"] == []
