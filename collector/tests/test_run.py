"""CLI run: export holds no unverified fact, a re-run changes no committed file (AC4.5), exit codes 0/2/3."""
import copy
import hashlib
import json
import os
import sys
from pathlib import Path

import jsonschema
import pytest

import collector.__main__ as M
from collector.export import CSV_FILES, export
from collector.store import Store

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schema" / "facts.schema.json").read_text())


def public_schema():
    """The facts schema minus the raw OCR fields, which the public export drops (plus the motion's type_label)."""
    s = copy.deepcopy(SCHEMA)
    for k in ("motion", "person_ref", "attendance", "vote"):
        d = s["$defs"][k]
        d["required"] = [r for r in d["required"] if r not in ("text", "raw_name")]
    for k, f in (("vote", "raw_value"), ("roll_call", "outcome_text")):
        s["$defs"][k]["required"] = [r for r in s["$defs"][k]["required"] if r != f]
    s["$defs"]["motion"]["properties"]["type_label"] = {"type": "string"}
    s["$defs"]["roll_call"]["properties"]["vote_on"] = {"type": ["string", "null"]}  # derived label, fixed patterns
    for k in ("motion", "roll_call", "vote"):
        s["$defs"][k]["properties"]["confirmed"] = {"type": "boolean"}
        s["$defs"][k]["required"] = s["$defs"][k]["required"] + ["confirmed"]
    # SHOW_UNCONFIRMED_VALUES off: an unconfirmed roll call's outcome and each of its votes' value are null
    for k, f in (("vote", "value"), ("roll_call", "outcome")):
        p = s["$defs"][k]["properties"][f]
        s["$defs"][k]["properties"][f] = {"anyOf": [p, {"type": "null"}]}
    return s


def committed_facts():
    return json.loads((ROOT / "data" / "facts.json").read_text())


def test_export_marks_unconfirmed_and_places_no_guessed_name(tmp_path):
    """Invariant: held-back counts. Every roll call and vote is exported with `confirmed`; an unresolved vote has no
    official; held motion attribution and unverified attendance are left out."""
    from sitegen.views import Index
    facts = committed_facts()
    export(facts, tmp_path)
    out = json.loads((tmp_path / "data" / "facts.json").read_text())
    jsonschema.validate(out, public_schema())
    assert len(out["roll_calls"]) == len(facts["roll_calls"])
    unconfirmed = 0
    for r, src in zip(out["roll_calls"], facts["roll_calls"]):
        assert r["confirmed"] == (src["verification"]["status"] == "verified")
        assert all(v["confirmed"] == r["confirmed"] for v in r["votes"])
        assert [v["official_id"] for v in r["votes"]] == [v["official_id"] for v in src["votes"]]
        if r["confirmed"]:
            assert [v["value"] for v in r["votes"]] == [v["value"] for v in src["votes"]] and r["outcome"]
        else:  # SHOW_UNCONFIRMED_VALUES = False (default, CEO 2026-11-07): link only, no parsed value
            assert all(v["value"] is None for v in r["votes"]) and r["outcome"] is None and r["stated_tally"] is None
        unconfirmed += not r["confirmed"]
    assert unconfirmed, "the committed facts have unconfirmed roll calls to test against"
    ix = Index(facts)
    for m, src in zip(out["motions"], facts["motions"]):
        att = ix.attribution(src)
        assert (m["moved_by"] is not None) == bool(att["mover"]) and (m["seconded_by"] is not None) == bool(att["seconder"])
    for m in out["meetings"]:
        if m["verification"]["status"] != "verified":
            assert m["attendance"] == []
    held_att = {f"{m['id']}/att/" for m in facts["meetings"] if m["verification"]["status"] != "verified"}
    votes = (tmp_path / "data" / "votes.csv").read_text().splitlines()
    assert "confirmed" in votes[0].split(",")
    assert len(votes) - 1 == sum(len(r["votes"]) for r in facts["roll_calls"])
    for name in CSV_FILES:
        text = (tmp_path / "data" / f"{name}.csv").read_text()
        assert not any(h in text for h in held_att), name
        header = text.splitlines()[0]
        if name not in ("officials", "sources"):
            assert all(c in header for c in ("source_url", "source_sha256", "page", "fetched_at")), name
    refs = {x["id"] for k in ("roll_calls", "motions") for x in out[k]}
    assert all(e["ref"] is None or e["ref"] in refs for e in out["item_events"])


def _digest(paths):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.exists()}


OFFLINE_RUN_ENV = "RECORDS_OFFLINE_RUN_TEST"


def offline_run_skip_reason(env=None) -> str | None:
    """Why the real offline run below must not run here, or None. It is opt-in (pipeline/tests-step-offline-run): it
    runs the real collector on the real data/, which no ordinary test run may do. In CI the document store is
    restored from the cache, so "the store is complete" alone used to switch it on in the workflow's Tests step."""
    env = os.environ if env is None else env
    if env.get(OFFLINE_RUN_ENV) != "1":
        return (f"opt-in: set {OFFLINE_RUN_ENV}=1 to run the real `collector run --offline` twice (never set in CI: "
                "the Tests step must not run the collector)")
    store = Store()
    if not all(store.has_bytes(e["sha256"]) for e in store.entries):
        return "the document store is empty in this checkout (run `python -m collector run` once)"
    return None


def test_second_offline_run_changes_no_committed_file(tmp_path, monkeypatch):
    """AC4.5 on the real documents. Opt-in, and even then the site is built in a temporary folder with the launch
    target's file cap: the repo's build/site (what the workflow uploads and deploys) is never rebuilt by a test."""
    why = offline_run_skip_reason()
    if why:
        pytest.skip(why)
    from sitegen import config
    monkeypatch.setattr(M, "BUILD", tmp_path / "build")
    monkeypatch.setattr(config, "DEFAULT_TARGET", "pages")
    committed = [ROOT / "data" / "facts.json", ROOT / "data" / "manifest.json", ROOT / "data" / "changes.jsonl"]
    assert M.main(["run", "--offline"]) != M.REFUSED
    before = _digest(committed)
    assert M.main(["run", "--offline"]) != M.REFUSED
    assert _digest(committed) == before


class _CompleteStore:
    """A store that holds every document, as in CI, where data/store is restored from the Actions cache."""
    entries = [{"sha256": "0" * 64}]

    def has_bytes(self, sha256):
        return True


def test_offline_run_test_is_opt_in_even_with_a_complete_store(monkeypatch, tmp_path):
    """pipeline/tests-step-offline-run: the workflow's Tests step sets no opt-in, so the real run is skipped there."""
    monkeypatch.setattr(sys.modules[__name__], "Store", _CompleteStore)
    assert "opt-in" in offline_run_skip_reason({})
    assert "opt-in" in offline_run_skip_reason({OFFLINE_RUN_ENV: "true"})          # only the exact value "1"
    assert offline_run_skip_reason({OFFLINE_RUN_ENV: "1"}) is None
    monkeypatch.delenv(OFFLINE_RUN_ENV, raising=False)
    ran = []
    monkeypatch.setattr(M, "main", lambda argv=None: ran.append(argv))
    with pytest.raises(pytest.skip.Exception, match="opt-in"):
        test_second_offline_run_changes_no_committed_file(tmp_path, monkeypatch)
    assert ran == []
    import yaml
    wf = (ROOT / ".github" / "workflows" / "daily-update.yml").read_text(encoding="utf-8")
    assert OFFLINE_RUN_ENV not in wf
    tests_step = next(s for s in yaml.safe_load(wf)["jobs"]["update"]["steps"] if s.get("name", "").startswith("Tests"))
    assert "env" not in tests_step and tests_step["run"] == "python -m pytest -q -x"


def test_opted_in_offline_run_never_rebuilds_the_repo_site(sandbox, monkeypatch, tmp_path):
    """The replay from the bug sweep: a complete store, the Tests step's environment (no RECORDS_BUILD_TARGET, so
    the 500-file preview cap) and a site of 505 files. The run used to rebuild build/site in place and then raise
    BuildError; now it builds in the test's own folder under the pages cap and the repo's build/ is not touched."""
    import sitegen.build
    from sitegen import config
    monkeypatch.delenv("RECORDS_BUILD_TARGET", raising=False)
    monkeypatch.delenv("RECORDS_SITE_URL", raising=False)
    monkeypatch.setattr(config, "DEFAULT_TARGET", "preview")
    monkeypatch.setenv(OFFLINE_RUN_ENV, "1")
    monkeypatch.setattr(sys.modules[__name__], "Store", _CompleteStore)
    monkeypatch.setattr(M, "missing_inputs", lambda store: [])
    monkeypatch.setattr(M, "shrink_reason", lambda *a, **k: None)
    monkeypatch.setattr(M, "FACTS", ROOT / "data" / "facts.json")     # committed, as in CI; the fake build returns it
    repo_build = tmp_path / "repo" / "build"                          # stands for the repo's build/, which CI uploads
    monkeypatch.setattr(M, "BUILD", repo_build)
    built = []

    def fake_site_build(facts_path, out_dir, **kw):
        built.append(Path(out_dir))
        for i in range(505):                                          # over the preview cap, under the pages cap
            (Path(out_dir) / "p").mkdir(parents=True, exist_ok=True)
            (Path(out_dir) / "p" / f"{i}.html").write_text("x")
    monkeypatch.setattr(sitegen.build, "build", fake_site_build)
    own = tmp_path / "own"
    own.mkdir()
    test_second_offline_run_changes_no_committed_file(own, monkeypatch)
    assert built == [own / "build" / "site"] * 2
    assert not repo_build.exists()
    assert (own / "build" / "publish-files.json").is_file()


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "FACTS", tmp_path / "facts.json")
    monkeypatch.setattr(M, "BUILD", tmp_path / "build")
    monkeypatch.setattr(M, "MANIFEST", tmp_path / "manifest.json")
    facts = committed_facts()
    report = {"gates": {"roll_calls": 1, "verified": 1, "verified_rate": 1.0, "held_back": 0,
                        "held_back_source_error": 0, "verified_rate_gate": {"min": 0.9, "pass": True},
                        "g4": {"status": "pass", "uniform_share": 0.0, "flagged": []}}, "pass": True}

    class B:
        unresolved = {}
    state = {"report": report, "fail": False, "fin_code": 0, "fin_calls": []}

    def fake_build(store, log, use_ocr=True):
        log["parsed"] = 1
        if state["fail"]:
            log["failures"].append({"stage": "parse", "error": "boom"})
        return facts, state["report"], B()
    monkeypatch.setattr(M, "cmd_build", fake_build)

    def fake_finance(store, log, offline, **kw):
        state["fin_calls"].append((offline, kw))
        if state["fin_code"] == 2:
            log["failures"].append({"stage": "fin_build", "error": "boom"})
        return state["fin_code"]
    monkeypatch.setattr(M, "run_finance", fake_finance)
    monkeypatch.setattr(M, "FINANCE", tmp_path / "finance.json")
    state["agenda_calls"] = []
    monkeypatch.setattr(M, "run_agendas",
                        lambda log, offline, fetcher=None: state["agenda_calls"].append((offline, fetcher)))
    return state


@pytest.mark.parametrize("fail,gate_pass,fin_code,code", [
    (False, True, 0, 0), (True, True, 0, 2), (False, False, 0, 3),
    (False, True, 2, 2),                 # finance fetch or build failure
    (False, True, 3, 3),                 # finance parity 'review needed' is a gate (A5)
])
def test_exit_codes(sandbox, capsys, fail, gate_pass, fin_code, code):
    sandbox["fail"] = fail
    sandbox["report"]["pass"] = gate_pass
    sandbox["fin_code"] = fin_code
    assert M.main(["run", "--offline"]) == code
    out = capsys.readouterr().out
    assert ("gh issue create --repo gn0sh/clarksville-records" in out) == (code != 0)


def test_run_calls_the_finance_steps_after_the_votes_steps(sandbox, tmp_path):
    """A1: `run` calls fin fetch/build (offline: build only) with the run's paths, after facts.json is written."""
    M.main(["run", "--offline"])
    (offline, kw), = sandbox["fin_calls"]
    assert offline is True and kw["fetcher"] is None
    assert kw["finance_path"] == tmp_path / "finance.json" and kw["report_path"] == tmp_path / "build" / "report.json"
    assert (tmp_path / "facts.json").exists()


def test_online_run_shares_one_polite_fetcher_that_denies_bonfire(sandbox, monkeypatch):
    from collector import fin_config
    seen = {}
    monkeypatch.setattr(M, "cmd_fetch", lambda store, log, fetcher=None: seen.setdefault("votes", fetcher))
    M.main(["run"])
    (offline, kw), = sandbox["fin_calls"]
    assert offline is False and kw["fetcher"] is seen["votes"]
    assert set(fin_config.load().bonfire_hosts) <= set(kw["fetcher"].extra_denied)


def test_discovery_block_is_a_logged_failure_not_a_crash(monkeypatch):
    from collector.fetch import HostBlocked

    def blocked(f):
        raise HostBlocked("dev2.montgomerytn.gov: HTTP 403 from the site")
    monkeypatch.setattr(M, "fetch_index", blocked)
    log = {"found": None, "new": [], "fetched": {}, "failures": []}

    class F:
        log = []
    M.cmd_fetch(Store(Path("/nonexistent/manifest.json")), log, fetcher=F())
    assert log["failures"][0]["stage"] == "discover" and "HostBlocked" in log["failures"][0]["error"]


def test_online_run_reads_the_county_agendas_with_the_same_fetcher(sandbox, monkeypatch):
    """Fix 2 (docs/research/county-recency.md): `run` includes the county agenda step, so the daily update runs it."""
    seen = {}
    monkeypatch.setattr(M, "cmd_fetch", lambda store, log, fetcher=None: seen.setdefault("votes", fetcher))
    M.main(["run"])
    assert sandbox["agenda_calls"] == [(False, seen["votes"])]
    M.main(["run", "--offline"])
    assert sandbox["agenda_calls"][-1] == (True, None)


def test_minutes_missing_from_the_store_are_refetched_at_their_manifest_url_only(tmp_path):
    """The 2020-2021 packets the index no longer lists: requested again at the URL the manifest recorded, nothing else."""
    import hashlib
    body = b"%PDF-1.4 minutes"
    sha = hashlib.sha256(body).hexdigest()
    url = "https://montgomeryminutes.bisonline.com/viewpdf.php?id=abc"
    (tmp_path / "manifest.json").write_text(json.dumps([{"url": url, "sha256": sha, "bytes": len(body), "kind": "minutes",
                                                         "meeting_date": "2020-03", "label": "March 2020 Minutes",
                                                         "first_fetched_at": "2026-11-07T00:00:00+00:00"}]))
    store = Store(tmp_path / "manifest.json", root=tmp_path / "store")
    store.save()                                                           # the manifest in its committed form
    before = (tmp_path / "manifest.json").read_bytes()

    class F:
        calls = []

        def get(self, u):
            self.calls.append(u)
            return 200, body, {}
    log = {"new": [], "failures": []}
    M.refetch_missing(store, log, F(), listed=set())
    store.save()
    assert F.calls == [url] and log["refetched"] == {url: "unchanged"} and store.has_bytes(sha)
    assert (tmp_path / "manifest.json").read_bytes() == before            # same bytes: the manifest is unchanged
    F.calls.clear()
    M.refetch_missing(store, log, F(), listed=set())
    assert F.calls == []                                                   # nothing missing: nothing requested
