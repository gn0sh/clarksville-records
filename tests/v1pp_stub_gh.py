#!/usr/bin/env python3
"""A small stateful GitHub behind a stub `gh`, for tests/test_v1pp_probe.py (task V1, the V1'' probe).

State lives in GH_STATE (JSON, written back after each call); the test's knobs in GH_CFG (JSON, read only). Every call
is appended to GH_CALLS as {"method", "path", "argv"}. --jq is applied with the real jq (-r), as gh does, so the
scripts' filters are exercised. An error answers like gh: a JSON body on stdout, "gh: <message> (HTTP <code>)" on
stderr, exit 1. No network: nothing here reaches GitHub."""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

a = sys.argv[1:]
cfg = json.load(open(os.environ["GH_CFG"]))
st_path = os.environ["GH_STATE"]
st = json.load(open(st_path))
REPO = "repos/gn0sh/clarksville-records/"
# a job log's 302 target, as gh would name it in an error: the path and query carry a signed, short-lived read token
STORAGE_HOST = "productionresultssa1.blob.core.windows.net"
STORAGE_URL = "https://" + STORAGE_HOST + "/actions-results/x/y.txt?sv=2025-01-05&sig=SECRETSIG%2Babc"

_Q = "/actions-results/x/y.txt?sv=2025-01-05&sig=SECRETSIG%2Babc"
DIAG = {   # log_fail modes for the sanitizer: a URL with no scheme, a JSON-escaped one, userinfo, C1 and bidi controls
    "schemeless": "gh: error reading " + STORAGE_HOST + _Q + " (EOF)",
    "jsonesc": 'gh: {"message":"Moved","url":"https:\\/\\/' + STORAGE_HOST + _Q.replace("/", "\\/") + '"} (HTTP 403)',
    "userinfo": 'gh: Get "https://gn0sh:SECRETPASS@' + STORAGE_HOST + _Q + '": EOF',
    "controls": "gh: \u009b31mbad\u202e gate\u0085way\u2066 x\u2069\u202a (HTTP 502)",
}
# raw stderr bytes: a control (U+009B, U+202E) nested inside another one's bytes, so one removal pass leaves a live one
# (v1pp-probe/log-read-diag-controls-nested)
DIAG_RAW = {
    "nested-c1": b"gh: bad \xc2\xc2\x9b\x9b gateway (HTTP 502)",
    "nested-bidi": b"gh: bad \xe2\x80\xe2\x80\xae\xae gateway (HTTP 502)",
}


def save():
    json.dump(st, open(st_path, "w"))


def method():
    return a[a.index("-X") + 1] if "-X" in a else "GET"


def fields():
    out = {}
    for i, x in enumerate(a):
        if x in ("-f", "-F") and i + 1 < len(a):
            k, _, v = a[i + 1].partition("=")
            out[k] = v
    return out


if a[:1] == ["--git"]:   # the stub git (tests/test_v1pp_probe.py puts it on PATH as git): init, fetch, push only
    g = a[1:]
    sub = next(x for x in g if x in ("init", "fetch", "push"))
    seen = {k: v for k, v in os.environ.items()
            if k.startswith("GIT_") or k in ("SSH_ASKPASS",)}   # what git would see (v1pp-probe/tag-git-env)
    with open(os.environ["GH_CALLS"], "a") as f:
        f.write(json.dumps({"method": "git " + sub, "path": "", "argv": g, "env": seen}) + "\n")
    if sub == "init":
        sys.exit(0)
    how = cfg.get("git_tag", "refuse")
    if sub == "fetch":
        assert g[-2] == "https://github.com/gn0sh/clarksville-records.git" and g[-1] == st["refs"]["heads/main"], g
        if how == "fetch_fail":
            sys.stderr.write("fatal: unable to access 'https://github.com/gn0sh/clarksville-records.git/': "
                             "Could not resolve host: github.com\n")
            sys.exit(128)
        sys.exit(0)
    assert g[-1] == st["refs"]["heads/main"] + ":refs/tags/main", g
    assert "credential.helper=!gh auth git-credential" in g, g
    url = "https://github.com/gn0sh/clarksville-records.git"
    if "tags/main" in st["refs"] or how == "uptodate":   # the ref is there at that sha already
        sys.stderr.write("Everything up-to-date\n")
        sys.exit(0)
    if how == "create_no_to":
        sys.exit(0)
    if how == "rewrite":   # an insteadOf rewrite sent it elsewhere
        sys.stderr.write("remote: error: GH013: Repository rule violations found for refs/tags/main.\n"
                         "To https://example.invalid/other.git\n ! [remote rejected] x -> main\n")
        sys.exit(1)
    if how == "hook":      # a local hook's words, not GitHub's
        sys.stderr.write("To %s\nerror: rule violation (pre-push hook)\nerror: failed to push some refs\n" % url)
        sys.exit(1)
    if how == "create":
        st["refs"]["tags/main"] = st["refs"]["heads/main"]
        json.dump(st, open(st_path, "w"))
        sys.stderr.write("To %s\n * [new tag]  main -> main\n" % url)
        sys.exit(0)
    if how == "other":
        sys.stderr.write("fatal: the remote end hung up unexpectedly\n")
        sys.exit(128)
    sys.stderr.write("remote: error: GH013: Repository rule violations found for refs/tags/main.\nremote: - Cannot "
                     "create ref due to creations being restricted.\nTo %s\n ! [remote rejected] %s -> main (push "
                     "declined due to repository rule violations)\n" % (url, st["refs"]["heads/main"]))
    sys.exit(1)

path = next((x for x in a if x.startswith("repos/")), "")
short = path[len(REPO):] if path.startswith(REPO) else path
with open(os.environ["GH_CALLS"], "a") as f:
    how_called = "api --help" if a[:2] == ["api", "--help"] else method() if a[:1] == ["api"] else " ".join(a[:2])
    f.write(json.dumps({"method": how_called, "path": short, "argv": a,
                        "gitenv": {k: v for k, v in os.environ.items()
                                   if k.startswith("GIT_") or k == "SSH_ASKPASS"}}) + "\n")


def jq_out(body):
    if "--silent" in a:
        return ""
    if "--jq" in a:
        r = subprocess.run(["jq", "-r", a[a.index("--jq") + 1]], input=json.dumps(body), capture_output=True,
                           text=True, env=os.environ)
        assert r.returncode == 0, (a, r.stderr)
        return r.stdout
    return json.dumps(body) + "\n"


def ok(body):
    save()
    sys.stdout.write(jq_out(body))
    sys.exit(0)


def err(code, msg):
    save()
    sys.stdout.write(json.dumps({"message": msg, "status": str(code)}) + "\n")
    sys.stderr.write("gh: %s (HTTP %d)\n" % (msg, code))
    sys.exit(1)


def sha(*parts):
    return hashlib.sha1("/".join(parts).encode()).hexdigest()


# one call answers like a gh 502: {"<substring of the call>": <how many times, -1 = always>}
joined = " ".join(a)
for sub, n in cfg.get("fail", {}).items():
    if sub in joined:
        used = st.setdefault("failed", {}).get(sub, 0)
        if n < 0 or used < n:
            st["failed"][sub] = used + 1
            err(502, "Server Error")

# v1pp-probe/log-read-escape-flag: which gh this is. "new" (the default, gh 2.104.0 as on Brian's PC) refuses to print
# a body holding terminal escape sequences unless --allow-escape-sequences is passed; "old" (gh 2.89.0, as in the
# cloud) has no such flag, and passing it is an unknown-flag error
GH = cfg.get("gh", "new")
VERSION = {"new": "2.104.0 (2026-11-10)", "old": "2.89.0 (2026-11-01)"}[GH]
ESC_FLAG = "--allow-escape-sequences"
if a[:1] == ["--version"]:   # the results file's header records line 1 (v1pp-probe/log-read-diag)
    print("gh version %s\nhttps://github.com/cli/cli/releases/tag/v%s" % (VERSION, VERSION.split()[0]))
    sys.exit(0)
if a[:2] == ["api", "--help"]:
    print("Make an authenticated HTTP request to the GitHub API and print the response.\n\nUSAGE\n"
          "  gh api <endpoint> [flags]\n\nFLAGS")
    if GH == "new" and not cfg.get("help_without_flag"):   # the knob: a test that the flag is what makes it read
        print("      --allow-escape-sequences   Output the response even if it contains terminal escape sequences")
    print("      --cache duration           Cache the response, e.g. \"3600s\", \"60m\", \"1h\"\n"
          "  -F, --field key=value          Add a typed parameter in key=value format\n"
          "  -H, --header key:value         Add a HTTP request header in key:value format")
    sys.exit(0)
if GH == "old" and ESC_FLAG in a:
    sys.stderr.write("unknown flag: %s\n\nUsage:  gh api <endpoint> [flags]\n" % ESC_FLAG)
    sys.exit(1)
if a[:2] == ["auth", "status"]:
    print(cfg.get("scopes", "Token scopes: 'gist', 'read:org', 'repo', 'workflow'"))
    sys.exit(0)
if a[:2] == ["auth", "refresh"]:
    if cfg.get("refresh_fail") and "--remove-scopes" not in a:   # the browser step was not finished
        sys.stderr.write("gh: authentication failed\n")
        sys.exit(1)
    sys.exit(0)

RUNS = {"probe/v1pp-runner": 500, "probe/v1pp-env": 501, "v1pp-probe": 502}
if a[:2] == ["run", "list"]:
    b = a[a.index("--branch") + 1]
    if b in cfg.get("no_run", []) or b not in RUNS:
        ok([])
    head = st["refs"].get("heads/" + b) or st["refs"].get("tags/" + b) or ""
    ok([{"databaseId": RUNS[b], "headSha": head}])
if a[:2] == ["run", "watch"]:
    sys.exit(0)
if a[:2] == ["run", "view"]:
    rid = a[2]
    if "--log" in a:   # try 1: it gave nothing for a finished run; the scripts read each job's log instead
        sys.exit(1)
    status = cfg.get("run_status", {}).get(rid, "completed")
    if rid in st.get("cancelled", []):
        status = "completed"
    ok({"status": status})

assert a[:1] == ["api"], a
m = method()
refs = st["refs"]
sys_lag = st.setdefault("lag", {})

if short.startswith("git/ref/"):                       # GET one ref
    r = short[len("git/ref/"):]
    if sys_lag.get(r, 0) > 0:                           # a deleted ref a lagging replica still shows
        sys_lag[r] -= 1
        ok({"ref": "refs/" + r, "object": {"sha": st["deleted"][r]}})
    reads = st.setdefault("reads", {})
    n = reads.get(r, 0)
    reads[r] = n + 1
    if r == "heads/main" and n > 0 and cfg.get("main_after"):     # main after the first read (the guard's)
        if cfg["main_after"] == "FAIL":
            err(502, "Server Error")
        refs["heads/main"] = cfg["main_after"]
    if r == "tags/main" and n > 0 and cfg.get("tag_main_reads_fail"):
        err(502, "Server Error")
    if r in refs:
        ok({"ref": "refs/" + r, "object": {"sha": refs[r]}})
    err(404, "Not Found")
if short == "git/refs" and m == "POST":
    fl = fields()
    r = fl["ref"][len("refs/"):]
    if r == "tags/main":
        how = cfg.get("tag_main", "refuse")
        if how in ("refuse", "other") and not cfg.get("no_suite"):   # R-T's evaluation, as GitHub records it
            now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            ev = [{"rule_source": {"type": "ruleset", "id": 27685093, "name": "tag main: blocked"},
                   "enforcement": "active", "result": "fail", "rule_type": "creation"}]
            suite = {"id": 900, "actor_name": "gn0sh", "before_sha": "0" * 40, "after_sha": fl["sha"],
                     "ref": "refs/tags/main", "pushed_at": now, "result": "fail", "evaluation_result": None,
                     "rule_evaluations": cfg.get("suite_evals", ev)}
            suite.update(cfg.get("suite_over", {}))
            st.setdefault("suites", []).append(suite)
            for extra in cfg.get("suite_extra", []):   # another suite, e.g. an earlier try's
                st["suites"].append({**suite, **extra})
        if how == "refuse":
            err(422, "Repository rule violations found\n\nCannot create ref due to creations being restricted.")
        if how == "other":
            err(422, "Reference update failed")
        if how == "502":
            err(502, "Server Error")
        refs[r] = fl["sha"]
        ok({"ref": "refs/" + r, "object": {"sha": fl["sha"]}})
    if r in refs:
        err(422, "Reference already exists")
    refs[r] = fl["sha"]
    st.setdefault("created", []).append(r)
    ok({"ref": "refs/" + r, "object": {"sha": fl["sha"]}})
if short.startswith("actions/runs/") and short.endswith("/cancel") and m == "POST":
    rid = short.split("/")[2]
    if rid not in [str(x) for x in cfg.get("cancel_ignored", [])]:
        st.setdefault("cancelled", []).append(rid)
    ok({})
if short.startswith("git/refs/") and m == "DELETE":
    r = short[len("git/refs/"):]
    if r in cfg.get("delete_fail", []):
        err(502, "Server Error")
    if r == "tags/main" and r not in refs and cfg.get("tag_main_delete") == "rule":
        err(422, "Repository rule violations found\n\nCannot delete this protected ref.")
    if r not in refs:
        err(422, "Reference does not exist")
    if r in cfg.get("delete_ignored", []):
        ok({})
    st.setdefault("deleted", {})[r] = refs.pop(r)
    if cfg.get("ref_lag", {}).get(r):
        sys_lag[r] = cfg["ref_lag"][r]
    ok({})
if short.startswith("contents/") and m == "PUT":
    fl = fields()
    b = fl["branch"]
    assert "heads/" + b in refs, a
    c = sha("commit", b, short)
    refs["heads/" + b] = c
    st.setdefault("files", {})[b] = short[len("contents/"):]
    ok({"commit": {"sha": c}, "content": {"sha": sha("blob", b)}})
if short.startswith("contents/") and m == "GET":
    p, _, ref = short[len("contents/"):].partition("?ref=")
    where = {"main": "on_main", "records-data": "on_rd"}[ref]
    if p in cfg.get(where, []):
        ok({"sha": sha("file", p)})
    err(404, "Not Found")
if short == "pulls" and m == "POST":
    fl = fields()
    if cfg.get("pr_422", 0) > st.get("pr_422", 0):      # the branch not visible yet (read-after-write rule 6)
        st["pr_422"] = st.get("pr_422", 0) + 1
        err(422, "Validation Failed")
    b = fl["head"]
    n = st.setdefault("next_pr", 77)
    st["next_pr"] = n + 1
    st.setdefault("prs", {})[str(n)] = {"head": b, "state": "open", "merged": False}
    ok({"number": n, "head": {"sha": refs["heads/" + b]}})
if short.startswith("pulls?"):
    q = dict(x.split("=", 1) for x in short.split("?", 1)[1].split("&"))
    assert q["state"] == "all" and q["base"] == "main" and q["head"].startswith("gn0sh:"), a
    b = q["head"][len("gn0sh:"):]
    ok([{"number": int(n)} for n, pr in sorted(st.get("prs", {}).items()) if pr["head"] == b])
if short.startswith("pulls/") and m == "PATCH":
    n = short.split("/")[1]
    pr = st["prs"][n]
    if fields().get("state") == "closed" and n not in [str(x) for x in cfg.get("close_ignored", [])]:
        pr["state"] = "closed"
        if int(n) in cfg.get("merged_after_cleanup", []):   # a merge that landed meanwhile (verdict race)
            pr["merged"] = True
    if int(n) in cfg.get("close_fail", []):
        err(502, "Server Error")
    ok({"number": int(n), "state": pr["state"], "merged": pr["merged"] or int(n) in cfg.get("merged", [])})
if short.startswith("pulls/") and m == "GET":
    n = short.split("/")[1]
    pr = st["prs"][n]
    merged = pr["merged"] or int(n) in cfg.get("merged", [])
    ok({"number": int(n), "state": pr["state"], "merged": merged})
if short.startswith("actions/runs/") and short.endswith("/jobs"):
    rid = short.split("/")[2]
    default = {"501": [("github-pages", 601), ("morning-note", 602)], "502": [("github-pages", 603), ("morning-note", 604)]}
    jobs = cfg.get("jobs", {}).get(rid)
    if jobs is None and rid == "700":   # the self-check's daily-update run (v1pp-probe/log-read-selfcheck)
        jobs = [{"id": 701, "name": "gate", "status": "completed", "conclusion": "success", "steps": [{"name": "x"}]}]
    if jobs is None and rid == "500":
        jobs = [{"id": 600, "name": "probe", "status": "completed", "conclusion": "success", "steps": [{"name": "Try"}]}]
    if jobs is None:
        jobs = [{"id": i, "name": nm, "status": "completed", "conclusion": "failure", "steps": []} for nm, i in default[rid]]
        jobs.append({"id": {"501": 605, "502": 606}[rid], "name": "pages-api", "status": "completed",
                     "conclusion": "success", "steps": [{"name": "Try"}]})
    ok({"total_count": len(jobs), "jobs": jobs})
if short.startswith("actions/jobs/") and short.endswith("/logs"):   # plain text, as gh prints it after the redirect
    jid = short.split("/")[2]
    reads = st.setdefault("log_reads", {})
    reads[jid] = reads.get(jid, 0) + 1
    if reads[jid] <= cfg.get("log_lag", {}).get(jid, 0):            # not ready yet
        err(404, "Not Found")
    how = cfg.get("log_fail", {}).get(jid)   # v1pp-probe/job-log-unreadable: ways a read can fail on Brian's PC
    if how and (os.environ.get("GH_DEBUG") or os.environ.get("DEBUG")):   # v1pp-probe/gh-debug-legacy
        sys.stderr.write("* Request to https://api.github.com/x DEBUGLINE Authorization: token gho_x\n")
    if how in DIAG:                          # one stderr line, as gh would print it (v1pp-probe/log-read-diag-*)
        save()
        sys.stderr.flush()
        sys.stderr.buffer.write((DIAG[how] + "\n").encode("utf-8"))
        sys.exit(1)
    if how in DIAG_RAW:
        save()
        sys.stderr.flush()
        sys.stderr.buffer.write(DIAG_RAW[how] + b"\n")
        sys.exit(1)
    if how == "dns":                         # the 302 to storage, not resolved: stderr carries the signed URL
        save()
        sys.stderr.write('gh: Get "%s": dial tcp: lookup %s: no such host\n' % (STORAGE_URL, STORAGE_HOST))
        sys.exit(1)
    if how == "s403":                        # storage answers 403 with an XML body that may echo the request
        save()
        sys.stdout.write('<?xml version="1.0" encoding="utf-8"?><Error><Code>AuthenticationFailed</Code>SECRETBODY'
                         '</Error>\n')
        sys.stderr.write("gh: HTTP 403 (%s)\n" % STORAGE_URL)
        sys.exit(1)
    if how == "empty":                       # exit 0 with no body
        save()
        sys.exit(0)
    if how == "token":                       # a long token-like string, and a line past the 200-character cap
        save()
        sys.stderr.write("\n  \ngh: bad credentials ghp_" + "A" * 36 + " " + "word " * 60 + "\nsecond line\n")
        sys.exit(1)
    if jid == "701":                         # the self-check's log: never shown (I-log 3)
        text = "2026-11-21T09:07:00.0000000Z SELFCHECK-BODY gate passed\n"
    elif jid == "600":
        text = cfg.get("runner_log", "")
    elif jid in ("605", "606"):   # the pages-api job's answer, by default refused on branch or environment grounds
        rid = {"605": "501", "606": "502"}[jid]
        who = {"501": 'Branch "probe/v1pp-env"', "502": 'Tag "v1pp-probe"'}[rid]
        text = cfg.get("env_logs", {}).get(rid, (
            '2026-11-21T15:00:00.0000000Z echo "V1PP-RESULT $t $s exit=$code $(printf ...)"\n'
            "2026-11-21T15:00:02.0000000Z V1PP-RESULT PAGES api exit=1 gh: %s is not allowed to "
            "deploy to github-pages due to environment protection rules. (HTTP 400)\n" % who))
    else:
        err(404, "Not Found")
    if cfg.get("ansi", True):   # as GitHub serves a log: ANSI colours on each line (v1pp-probe/log-read-escape-flag)
        text = re.sub(r"(?m)^([0-9T:.-]+Z )(.*)$", "\\1\x1b[36;1m\\2\x1b[0m", text)
    save()
    if GH == "new" and "\x1b" in text and ESC_FLAG not in a:   # gh 2.104's check, as Brian's PC showed it
        sys.stderr.write("the response contains terminal escape sequences; pass %s to output it anyway\n" % ESC_FLAG)
        sys.exit(1)
    if how == "bom":                         # the body starts with a UTF-8 BOM, as GitHub serves it (F3)
        sys.stdout.flush()
        sys.stdout.buffer.write(b"\xef\xbb\xbf" + text.encode("utf-8"))
        sys.exit(0)
    sys.stdout.write(text)
    sys.exit(0)
if short.startswith("actions/workflows/daily-update.yml/runs?"):   # the self-check's run: the newest completed one
    q = dict(x.split("=", 1) for x in short.split("?", 1)[1].split("&"))
    assert q == {"status": "completed", "per_page": "5"}, q
    ids = [] if cfg.get("selfcheck_run") == "none" else cfg.get("selfcheck_runs", [700])   # newest first
    ok({"total_count": len(ids), "workflow_runs": [{"id": i, "status": "completed", "conclusion": "success"} for i in ids]})
if short.startswith("rulesets/rule-suites?"):   # GitHub's record of each ref update (fields per its OpenAPI description)
    q = dict(x.split("=", 1) for x in short.split("?", 1)[1].split("&"))
    assert q == {"ref": "refs/tags/main", "time_period": "day", "per_page": "100"}, q
    n = st["suite_reads"] = st.get("suite_reads", 0) + 1
    if n <= cfg.get("suite_lag", 0):
        ok([])
    ok([{k: v for k, v in x.items() if k != "rule_evaluations"} for x in st.get("suites", [])])
if short.startswith("rulesets/rule-suites/"):
    sid = int(short.split("/")[2])
    x = next((x for x in st.get("suites", []) if x["id"] == sid), None)
    if x is None or cfg.get("suite_unreadable"):
        err(404, "Not Found")
    ok(x)
if short.startswith("check-runs/") and short.endswith("/annotations"):
    jid = short.split("/")[1]
    over = cfg.get("annotations", {})
    if jid in over:
        ok([{"message": x} for x in over[jid]])
    what = {"601": ('Branch "probe/v1pp-env"', "github-pages"), "602": ('Branch "probe/v1pp-env"', "morning-note"),
            "603": ('Tag "v1pp-probe"', "github-pages"), "604": ('Tag "v1pp-probe"', "morning-note")}[jid]
    ok([{"message": "%s is not allowed to deploy to %s due to environment protection rules." % what}])
if short == "actions/permissions/workflow":
    if m == "PUT":
        st["r2"] = fields()["can_approve_pull_request_reviews"] == "true"
        st.setdefault("r2_puts", 0)
        st["r2_puts"] += 1
        ok({})
    ok({"default_workflow_permissions": "read", "can_approve_pull_request_reviews": st.get("r2", False)})
err(500, "stub: unexpected call " + joined)
