"""scripts/clock-report.py (ADR 0015 decision 8, task T4): the per-day morning clock report and the S1-S3 summary,
on fixture JSON in the shape GitHub's API returns (no network, no gh)."""
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sitegen import morning  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "clock-report.py"
_spec = importlib.util.spec_from_file_location("clock_report", SCRIPT)
cr = importlib.util.module_from_spec(_spec)
sys.modules["clock_report"] = cr
_spec.loader.exec_module(cr)

WF = yaml.safe_load((ROOT / ".github" / "workflows" / "daily-update.yml").read_text(encoding="utf-8"))
SITE = yaml.safe_load((ROOT / "config" / "site.yml").read_text(encoding="utf-8"))
NOW = "2026-12-05 12:00"            # site time; the fixture days are Dec 1 to 5 (CST, UTC-6)

_ids = iter(range(1000, 100000))


def _run(rid, event, title, created, started=None, attempt=1):
    return {"id": rid, "event": event, "display_title": title, "created_at": created,
            "run_started_at": started or created, "head_branch": "main", "run_attempt": attempt}


def _line(minute, hour):
    return f"Daily update (schedule {minute} {hour} * * *)"


def _jobs(fx, rid, arm=None, collect=True, note=None, deliver_at=None, note_log=None, attempt=1):
    """The run's jobs: arm (its log says send=<arm>, or no arm job when arm is None), update (Collect ran or was
    skipped), and a note job (note = its conclusion, completed at note[1]) whose log is note_log."""
    jobs = fx["jobs"].setdefault(str(rid), [])
    if arm is not None:
        jid = next(_ids)
        jobs.append({"id": jid, "name": "arm", "conclusion": "success", "run_attempt": attempt, "steps": []})
        fx["logs"][str(jid)] = (f"2026-12-01T08:41:00.0Z Site time ... arm window [00:00, 08:00): send={arm}\n"
                                if arm in ("true", "false") else "")
    jobs.append({"id": next(_ids), "name": "update", "conclusion": "success", "run_attempt": attempt,
                 "steps": [{"name": "Collect (polite fetch, parse, verify)",
                            "conclusion": "success" if collect else "skipped"}]})
    if note:
        jid = next(_ids)
        steps = [{"name": "Deliver the morning note", "conclusion": note[0], "completed_at": deliver_at}] \
            if deliver_at else []
        jobs.append({"id": jid, "name": "note", "conclusion": note[0], "completed_at": note[1],
                     "run_attempt": attempt, "steps": steps})
        if note_log is not None:
            fx["logs"][str(jid)] = note_log
    else:
        jobs.append({"id": next(_ids), "name": "note", "conclusion": "skipped", "completed_at": None,
                     "run_attempt": attempt, "steps": []})


def _sent(day, status="sent", created=3):
    return (f"2026-12-01T12:50:00.0Z morning note {day}: {status}; emails created {created}; "
            f"recipients in total 9\n")


def _fixture():
    fx = {"runs": [], "jobs": {}, "logs": {}}
    # Dec 1, on time from a schedule run: the 02:37 UTC line created 08:40Z (02:40 CST, 6.0 h late), armed,
    # Deliver done 06:50, emails at 07:00
    fx["runs"].append(_run(1, "schedule", _line(37, 2), "2026-12-01T08:40:00Z", "2026-12-01T08:41:00Z"))
    _jobs(fx, 1, arm="true", note=("success", "2026-12-01T12:58:00Z"), deliver_at="2026-12-01T12:50:00Z",
          note_log=_sent("2026-12-01"))
    # Dec 2, on time from the PC clock (a dispatch at 03:07); a schedule line came at 09:00, not armed
    fx["runs"].append(_run(2, "workflow_dispatch", "Daily update (morning note)", "2026-12-02T09:07:00Z"))
    _jobs(fx, 2, arm="true", note=("success", "2026-12-02T12:45:00Z"), deliver_at="2026-12-02T12:40:00Z",
          note_log=_sent("2026-12-02"))
    fx["runs"].append(_run(3, "schedule", _line(37, 2), "2026-12-02T15:00:00Z"))
    _jobs(fx, 3, arm="false")
    # Dec 3, late: the 06:37 line created 12:30Z (06:30 CST), armed, Deliver done 08:30
    fx["runs"].append(_run(4, "schedule", _line(37, 6), "2026-12-03T12:30:00Z"))
    _jobs(fx, 4, arm="true", note=("success", "2026-12-03T14:35:00Z"), deliver_at="2026-12-03T14:30:00Z",
          note_log=_sent("2026-12-03"))
    # Dec 4, none: the only run came at 09:00, not armed
    fx["runs"].append(_run(5, "schedule", _line(37, 23), "2026-12-04T15:00:00Z"))
    _jobs(fx, 5, arm="false")
    # Dec 5, two send runs: the first sends, the second (same plan) says "sent; emails created 0"; plus the 20:37 line
    # the evening before (Dec 4 22:00 CST: not armed, a collect-and-deploy run on Dec 4)
    fx["runs"].append(_run(6, "schedule", _line(37, 20), "2026-12-05T04:00:00Z"))
    _jobs(fx, 6, arm="false")
    fx["runs"].append(_run(7, "schedule", _line(37, 23), "2026-12-05T07:00:00Z", "2026-12-05T07:01:00Z"))
    _jobs(fx, 7, arm="true", note=("success", "2026-12-05T08:45:00Z"), deliver_at="2026-12-05T08:40:00Z",
          note_log=_sent("2026-12-05"))
    fx["runs"].append(_run(8, "schedule", _line(37, 2), "2026-12-05T09:00:00Z"))
    _jobs(fx, 8, arm="true", note=("success", "2026-12-05T10:50:00Z"), deliver_at="2026-12-05T10:45:00Z",
          note_log=_sent("2026-12-05", created=0))
    return fx


def _report(tmp_path, fx, *args):
    f = tmp_path / "saved.json"
    f.write_text(json.dumps(fx))
    return f


def _days(fx, n=5, now=NOW):
    tz = cr.site_zone()
    when = datetime.strptime(now, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    return {d.day.isoformat(): d for d in cr.collect(cr.Source(cr.REPO, fx), tz, when, n)}


def test_each_kind_of_day():
    days = _days(_fixture())
    assert list(days) == ["2026-12-01", "2026-12-02", "2026-12-03", "2026-12-04", "2026-12-05"]
    want = {"2026-12-01": ("on time", True, True), "2026-12-02": ("on time", True, False),
            "2026-12-03": ("late", False, False), "2026-12-04": ("none", False, False),
            "2026-12-05": ("on time", True, True)}
    for day, (verdict, s1, s2) in want.items():
        d = days[day]
        assert (d.verdict, d.s1, d.s2, d.problems) == (verdict, s1, s2, []), day
    # the two send runs on Dec 5: one real send, one "sent; emails created 0", both on the schedule route
    notes = [n for r in days["2026-12-05"].runs for n in r.notes]
    assert [(n.route, n.conclusion, n.status, n.emails, n.sent) for n in notes] == [
        ("schedule", "success", "sent", 3, True), ("schedule", "success", "sent", 0, False)]
    # the PC's run is the dispatch route; the evening line belongs to the day it started (Dec 4)
    assert [n.route for r in days["2026-12-02"].runs for n in r.notes] == ["dispatch"]
    assert [r.id for r in days["2026-12-04"].runs] == [5, 6]


def test_the_printed_report(tmp_path, capsys):
    f = _report(tmp_path, _fixture())
    assert cr.main(["--from-json", str(f), "--now", NOW, "--days", "5"]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0] == "2026-12-01 (America/Chicago): note on time; collecting runs 1"
    assert lines[1] == ("  run 1: schedule 37 2 * * *, late 6.0 h; created 12-01 02:40, started 12-01 02:41; "
                        "armed yes (log)")
    assert lines[2] == "    note (schedule): success, completed 12-01 06:58, deliver sent at 12-01 06:50"
    assert "2026-12-03 (America/Chicago): note late; collecting runs 1" in lines
    assert "2026-12-04 (America/Chicago): note none; collecting runs 2" in lines
    assert "  run 6: schedule 37 20 * * *, late 7.4 h; created 12-04 22:00, started 12-04 22:00; armed no (log)" \
        in lines
    assert '  run 2: workflow_dispatch "Daily update (morning note)"; created 12-02 03:07, started 12-02 03:07; ' \
           'armed yes (log)' in lines
    assert "    note (schedule): success, completed 12-05 04:50, deliver sent (0 emails) at 12-05 04:45" in lines
    assert "PROBLEM" not in out


def test_the_summary(tmp_path, capsys):
    f = _report(tmp_path, _fixture())
    assert cr.main(["--from-json", str(f), "--now", NOW, "--summary", "5"]) == 0
    out = capsys.readouterr().out
    assert "Over 5 site days (2026-12-01 to 2026-12-05):" in out
    assert "S1 (note done by 06:55): 3 of 5 (target: at least 4)" in out
    assert "No-send days (left out of S1): 0" in out
    assert "S2 (armed schedule run created by 05:00): 2 of 5" in out
    assert "S3 (safety problems seen): 0 day(s)" in out and "S3 by hand:" in out


def test_two_sent_deliveries_and_a_send_after_ten_are_safety_problems(tmp_path, capsys):
    fx = _fixture()
    # Dec 5's second run says sent too (two plans' emails), and Dec 3's note finished at 10:30
    fx["logs"][str(fx["jobs"]["8"][-1]["id"])] = _sent("2026-12-05")
    fx["jobs"]["4"][-1]["steps"][0]["completed_at"] = "2026-12-03T16:30:00Z"
    fx["jobs"]["4"][-1]["completed_at"] = "2026-12-03T16:31:00Z"
    days = _days(fx)
    assert days["2026-12-05"].problems == ["2 deliveries say sent (two plans' emails?)"]
    assert days["2026-12-03"].problems == ["run 4: a note job succeeded after 10:00"]
    f = _report(tmp_path, fx)
    assert cr.main(["--from-json", str(f), "--now", NOW, "--summary", "5"]) == 0
    out = capsys.readouterr().out
    assert "S3 (safety problems seen): 2 day(s)" in out and "2026-12-05: 2 deliveries say sent" in out


def test_a_note_stopped_by_the_route_check_is_a_safety_problem():
    fx = {"runs": [_run(9, "schedule", _line(37, 2), "2026-12-05T08:40:00Z")], "jobs": {}, "logs": {}}
    _jobs(fx, 9, arm="true", note=("failure", "2026-12-05T10:00:00Z"),
          note_log="::error::only an armed run may send: a scheduled run's first attempt, ... Nothing sent.\n")
    d = _days(fx, 1)["2026-12-05"]
    assert d.verdict == "none" and d.problems == ["run 9: the note job was stopped by the route or arm check"]


def test_armed_is_derived_from_the_start_when_there_is_no_arm_log():
    """Runs from before the arm job, or whose logs expired: armed from the start time in site time."""
    fx = {"runs": [_run(10, "schedule", "Daily update", "2026-12-05T06:00:00Z"),          # 00:00 CST
                   _run(11, "schedule", _line(37, 6), "2026-12-05T13:59:00Z"),            # 07:59 CST
                   _run(12, "schedule", _line(37, 6), "2026-12-05T14:00:00Z"),            # 08:00 CST
                   _run(13, "workflow_dispatch", "Daily update", "2026-12-05T05:59:00Z")],  # Dec 4 23:59
          "jobs": {}, "logs": {}}
    _jobs(fx, 11, arm="")                         # an arm job whose log can't be read
    days = _days(fx, 2)
    runs = {r.id: r for d in days.values() for r in d.runs}
    assert {i: (r.armed, r.armed_from) for i, r in runs.items()} == {
        10: (True, "derived"), 11: (True, "derived"), 12: (False, "derived"), 13: (False, "derived")}
    assert runs[10].line is None and runs[10].collected is None          # no jobs read: collected unknown
    assert [r.id for r in days["2026-12-04"].runs] == [13]


def test_the_first_attempts_arm_decides():
    fx = {"runs": [_run(14, "schedule", _line(37, 2), "2026-12-05T08:40:00Z", attempt=2)], "jobs": {}, "logs": {}}
    _jobs(fx, 14, arm="false", attempt=2)
    _jobs(fx, 14, arm="true", attempt=1)
    run = _days(fx, 1)["2026-12-05"].runs[0]
    assert (run.armed, run.armed_from) == (True, "log")


@pytest.mark.parametrize("created,line,hours", [
    ("2026-12-05T08:40:00Z", (2, 37), 6.05),
    ("2026-12-05T02:00:00Z", (2, 37), 23.38),          # created before the line's time that day: yesterday's firing
    ("2026-12-05T08:00:00Z", (20, 37), 11.38),         # across UTC midnight
    ("2026-12-05T06:37:00Z", (6, 37), 0.0),
])
def test_lateness_is_from_the_lines_last_firing(created, line, hours):
    got = cr.lateness(cr.parse_time(created), line)
    assert abs(got.total_seconds() / 3600 - hours) < 0.01 and got >= timedelta(0)


def test_the_report_reads_the_workflows_own_run_names():
    """ADR 0015 decision 2: every schedule line's run name, as run-name formats it, gives the line back."""
    expr = WF["run-name"]
    assert "format('Daily update (schedule {0})', github.event.schedule)" in expr
    for entry in (WF.get("on") or WF[True])["schedule"]:
        minute, hour = entry["cron"].split()[:2]
        assert cr.schedule_line(f"Daily update (schedule {entry['cron']})") == (int(hour), int(minute))
    for title in ("Daily update", "Daily update (morning note)", "Daily update (schedule 37 2 * * 1)",
                  "Daily update (schedule 99 2 * * *)", "Daily update (schedule */5 * * * *)"):
        assert cr.schedule_line(title) is None, title


def test_the_constants_match_the_workflow_and_the_config():
    env = WF["jobs"]["arm"]["steps"][0]["env"]
    assert cr.ARM_UNTIL.strftime("%H:%M") == env["ARM_UNTIL"]
    mn = SITE["morning_note"]
    assert cr.CUTOFF.strftime("%H:%M") == mn["cutoff"] and cr.CUTOFF_FROM.isoformat() == str(mn["cutoff_from"])
    assert cr.LEGACY_CUTOFF.strftime("%H:%M") == morning.LEGACY_CUTOFF
    assert cr.CUTOFF < cr.ARM_UNTIL and cr.LEGACY_CUTOFF < cr.ARM_UNTIL
    assert cr.LATEST_SEND.strftime("%H:%M") == SITE["morning_note"]["sender"]["latest_send"]
    assert cr.site_zone().key == SITE["site_timezone"]
    note = {s["name"] for s in WF["jobs"]["note"]["steps"]}
    update = {s["name"] for s in WF["jobs"]["update"]["steps"]}
    assert cr.DELIVER_STEP in note and cr.COLLECT_STEP in update
    assert cr.ROUTE_REFUSAL in next(s["run"] for s in WF["jobs"]["note"]["steps"] if s["name"] == cr.DELIVER_STEP)
    assert cr.ARM_LOG.search("Site time ...; arm window [00:00, 08:00): send=true")
    assert "arm window [" in WF["jobs"]["arm"]["steps"][0]["run"] and "): send=$send" in WF["jobs"]["arm"]["steps"][0]["run"]


def test_it_reads_github_only_through_gh_api_get(monkeypatch, capsys):
    """Read-only, no token handling: every call is `gh api -X GET`, and the script never names a token."""
    calls = []

    class Done:
        def __init__(self, out):
            self.returncode, self.stdout, self.stderr = 0, out, ""

    def fake(cmd, **kw):
        calls.append(cmd)
        path = cmd[-1]
        if "/workflows/" in path:
            return Done(json.dumps({"workflow_runs": [_run(20, "schedule", _line(37, 2), "2026-12-05T08:40:00Z")]}))
        if path.endswith("/jobs?filter=all&per_page=100"):
            return Done(json.dumps({"jobs": [{"id": 77, "name": "arm", "run_attempt": 1, "steps": []}]}))
        return Done("x arm window [00:00, 08:00): send=true\n")

    monkeypatch.setattr(cr.subprocess, "run", fake)
    assert cr.main(["--now", NOW, "--days", "1"]) == 0
    assert all(c[:4] == ["gh", "api", "-X", "GET"] and len(c) == 5 for c in calls), calls
    assert calls[0][-1].startswith("repos/gn0sh/clarksville-records/actions/workflows/daily-update.yml/runs?"
                                   "branch=main&created=%3E%3D2026-12-04T06:00:00Z&per_page=100&page=1")
    assert "armed yes (log)" in capsys.readouterr().out
    text = SCRIPT.read_text(encoding="utf-8")
    assert "TOKEN" not in text and "environ" not in text and '"-X", "GET"' in text


def test_a_failed_run_list_read_fails_loudly(monkeypatch, capsys):
    class Failed:
        returncode, stdout, stderr = 1, "", "HTTP 403"

    monkeypatch.setattr(cr.subprocess, "run", lambda cmd, **kw: Failed())
    assert cr.main(["--now", NOW]) == 1
    assert "could not read the runs" in capsys.readouterr().err


def test_parse_time_is_utc():
    assert cr.parse_time("2026-12-05T08:40:00Z") == datetime(2026, 12, 5, 8, 40, tzinfo=timezone.utc)
    assert cr.parse_time(None) is None


def _day(*notes_args, day="2026-12-05"):
    """One site day from (arm, note-conclusion, deliver log text, deliver_at) runs, all schedule runs at 02:40 CST."""
    fx = {"runs": [], "jobs": {}, "logs": {}}
    for i, (conclusion, log, at) in enumerate(notes_args):
        rid = 300 + i
        fx["runs"].append(_run(rid, "schedule", _line(37, 2), f"{day}T08:4{i}:00Z"))
        _jobs(fx, rid, arm="true", note=(conclusion, f"{day}T12:58:00Z"), deliver_at=at, note_log=log)
    return _days(fx, 1)[day]


def test_a_claim_by_a_different_plan_is_possible_lost_records():
    d = _day(("success", _sent("2026-12-05", "claimed (the day belongs to an earlier, different plan)", 0),
              "2026-12-05T12:50:00Z"))
    assert d.problems == ["run 300: the day was claimed by a different plan: possible lost records"]
    assert (d.verdict, d.s1) == ("none", False)          # a claim is not a send


def test_a_published_run_after_a_send_is_neither_a_send_nor_a_problem():
    """security/stamp-cleared-after-publish: a same-plan run after send_at says "published" and creates nothing."""
    d = _day(("success", _sent("2026-12-05"), "2026-12-05T12:50:00Z"),
             ("success", "2026-12-05T13:20:00Z morning note 2026-12-05: published (the day's emails are already "
                         "published); emails created 0; recipients in total 0\n", "2026-12-05T13:20:00Z"))
    assert (d.verdict, d.s1, d.problems) == ("on time", True, [])
    assert [n.status for r in d.runs for n in r.notes] == ["sent", "published"]
    assert sum(n.sent for r in d.runs for n in r.notes) == 1


@pytest.mark.parametrize("status", ["disabled", "no-canary", "wrong-date"])
def test_disabled_no_canary_and_wrong_date_never_count_as_on_time(status):
    d = _day(("success", f"2026-12-05T12:50:00Z morning note 2026-12-05: {status}\n", "2026-12-05T12:50:00Z"))
    assert (d.verdict, d.s1, d.no_send, d.problems) == ("none", False, False, [])


def test_a_no_send_day_leaves_s1s_count(tmp_path, capsys):
    fx = _fixture()
    # Dec 4 (a "none" day) becomes a no-send day: its note says no-send
    fx["runs"].append(_run(30, "schedule", _line(37, 2), "2026-12-04T08:40:00Z"))
    _jobs(fx, 30, arm="true", note=("success", "2026-12-04T12:00:00Z"), deliver_at="2026-12-04T11:59:00Z",
          note_log="2026-12-04T11:59:00Z morning note 2026-12-04: no-send; nothing new\n")
    days = _days(fx)
    assert (days["2026-12-04"].verdict, days["2026-12-04"].no_send, days["2026-12-04"].s1) == ("no-send", True, False)
    f = _report(tmp_path, fx)
    assert cr.main(["--from-json", str(f), "--now", NOW, "--summary", "5"]) == 0
    out = capsys.readouterr().out
    assert "S1 (note done by 06:55): 3 of 4 (target: at least 3)" in out
    assert "No-send days (left out of S1): 1 (2026-12-04)" in out


def test_a_sent_line_without_a_count_is_not_a_send():
    d = _day(("success", "2026-12-05T12:50:00Z morning note 2026-12-05: sent\n", "2026-12-05T12:50:00Z"))
    assert (d.verdict, d.s1) == ("none", False)


def test_before_the_switch_day_a_run_is_derived_armed_only_from_07_to_08():
    """Nov 27 (before T = 2026-11-30): cut(D) is the legacy 07:00; from T on it is 00:00."""
    assert cr.cut_for(datetime(2026, 11, 29, tzinfo=timezone.utc).date()).strftime("%H:%M") == "07:00"
    fx = {"runs": [_run(40, "schedule", _line(37, 2), "2026-11-27T08:40:00Z"),     # 02:40 CST
                   _run(41, "schedule", _line(37, 6), "2026-11-27T12:59:00Z"),     # 06:59
                   _run(42, "schedule", _line(37, 6), "2026-11-27T13:00:00Z"),     # 07:00
                   _run(43, "schedule", _line(37, 6), "2026-11-27T13:59:00Z"),     # 07:59
                   _run(44, "schedule", _line(37, 6), "2026-11-27T14:00:00Z"),     # 08:00
                   _run(45, "schedule", _line(37, 2), "2026-11-30T06:00:00Z")],    # T 00:00 CST
          "jobs": {}, "logs": {}}
    runs = {r.id: r.armed for d in _days(fx, 4, "2026-11-30 12:00").values() for r in d.runs}
    assert runs == {40: False, 41: False, 42: True, 43: True, 44: False, 45: True}


def test_unreadable_run_data_exits_2_with_one_line(tmp_path, capsys):
    fx = _fixture()
    fx["runs"][3]["created_at"] = "not-a-date"
    f = _report(tmp_path, fx)
    assert cr.main(["--from-json", str(f), "--now", NOW, "--days", "5"]) == 2
    cap = capsys.readouterr()
    assert cap.out == "" and len(cap.err.splitlines()) == 1 and "run 4" in cap.err and cap.err.startswith("clock-report:")


@pytest.mark.parametrize("damage", [
    lambda fx: fx["runs"][0].pop("id"),                                   # KeyError
    lambda fx: fx["runs"][0].update(created_at=12345),                    # TypeError
    lambda fx: fx["jobs"]["1"][-1].update(completed_at="yesterday"),      # ValueError from a job
    lambda fx: fx.update(runs=["x"]),                                     # a run that is not an object
    lambda fx: fx["jobs"]["1"][-1].update(steps=["x"]),                   # a step that is not an object
    lambda fx: fx["jobs"].update({"1": {"name": "arm"}}),                 # a run's jobs as an object, not a list
    lambda fx: fx.update(jobs=[]),                                        # the jobs map as a list
])
def test_other_bad_shapes_exit_2_too(tmp_path, capsys, damage):
    fx = _fixture()
    damage(fx)
    f = _report(tmp_path, fx)
    assert cr.main(["--from-json", str(f), "--now", NOW, "--days", "5"]) == 2
    cap = capsys.readouterr()
    assert cap.out == "" and len(cap.err.splitlines()) == 1


def test_a_saved_file_that_is_not_json_exits_2(tmp_path, capsys):
    f = tmp_path / "bad.json"
    f.write_text("{nope")
    assert cr.main(["--from-json", str(f), "--now", NOW]) == 2
    assert len(capsys.readouterr().err.splitlines()) == 1


def test_the_report_constants_equal_the_arm_job_env():
    env = next(st for st in WF["jobs"]["arm"]["steps"] if st.get("id") == "arm")["env"]
    assert cr.CUTOFF.strftime("%H:%M") == env["CUTOFF"]
    assert cr.CUTOFF_FROM.isoformat() == str(env["CUTOFF_FROM"])
    assert cr.LEGACY_CUTOFF.strftime("%H:%M") == env["LEGACY_CUTOFF"]
