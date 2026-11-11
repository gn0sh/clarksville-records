# main-protect invariant (loop rule: `main-protect` hit 3)
devops-engineer, 2026-11-11. Sources: security reviews `security-tip-fixes-f94b8a9` (S1, S3) and
`security-tip-fixes2-a618a04` (N1, `main-protect/pr-check-path-scope`). Applies to the `note` job of
`.github/workflows/daily-update.yml`, the only job that gets `BUTTONDOWN_API_KEY`.

## The invariant
**No code that runs with the send key can reach `main` except through a reviewed pull request.** "Code" is anything the
job executes or that can change what it executes: the workflow, the actions it uses, every Python module it imports,
and any file or variable that can change which module is imported. Everything else the job reads is data and is
validated as data. The rule that enforces it: every file the job can load as code is (a) outside `data/`, so the PR
check covers it, and (b) not reachable by any other path. `data/` is the only part of the repository excluded from the
PR check (the push job commits it daily without a PR), so nothing in the job may load anything from `data/` or from
the repository root.

## Every way code or config reaches the job, and its guard after this fix
| # | Consumer | How it is guarded |
|---|---|---|
| 1 | The workflow file (job, `if:`, `run:` scripts, env, `MAIN_PR_BASELINE`) | `.github/` is outside `data/`: every first-parent commit on main after the baseline that touches it must be a merged PR (PR check). The stale-rerun check refuses a run whose tree (outside `data/`) differs from main's. A workflow pushed to main that drops these steps: the runbook's required reviewer on the `morning-note` environment (residual, below). |
| 2 | Other workflows (`.github/workflows/*`) that could name the `morning-note` environment | Same PR check (`.github/`); the environment's deployment-branch rule (main only) and required reviewer. |
| 3 | Actions (`checkout`, `setup-python`, `download-artifact`) | Pinned by full commit sha in the workflow (test `test_no_secrets_and_pinned_actions`); the pins are in `.github/`, so PR-checked. |
| 4 | Bash for `run:` steps | GitHub's `bash --noprofile --norc -eo pipefail`; no repo file is sourced. `GITHUB_ENV`/`GITHUB_PATH` are written only by `setup-python` and by "Validate the plan files" (`PLAN`, a path whose day folder matched `^[0-9]{4}-[0-9]{2}-[0-9]{2}$`), so no earlier step can set `BASH_ENV`, `LD_PRELOAD` or `PATH`. No repo code runs before the key step except the isolated sender (row 6). |
| 5 | Tools `git`, `gh`, `jq`, `find`, `cp` | From the GitHub runner image, not the repo. `git` reads `.git/config` written by `checkout`; repo files cannot define hooks or filter drivers. |
| 6 | **`sys.path` and imports** (N1) | Before: `python -E -s -m sender` and `python -E -s -c` put the checkout root first on `sys.path`, so a root `json.py`/`argparse.py` (or package) shadowed the standard library. After: step "Stage the sender outside the checkout" copies only the regular `sender/*.py` files to `$RUNNER_TEMP/note-lib/sender/`, and every Python run in the job is `python -I -S -c '...'` with that one folder inserted: `-I` drops the cwd and script dir, every `PYTHON*` variable and the user site; `-S` drops site-packages, `.pth` files and `sitecustomize`. `sys.path` is that folder plus the standard library only, so an import of anything but `sender` or the standard library (including optional fallbacks such as `winreg` or `tzdata`) fails. |
| 7 | `sender/*.py` | PR-checked and stale-checked (outside `data/`). Copied after both checks; no `__pycache__` (a committed unchecked-hash `.pyc` would load without its source), no symlink, no subfolder. |
| 8 | Current directory (checkout root) | Used only to find `config/site.yml`; never on `sys.path`. Root files (`conftest.py`, `*.py`, `pyproject.toml`) are no longer importable, and are PR-checked anyway. |
| 9 | `config/site.yml` (data: link hosts, mode, limits) | Read by `sender/settings.py`'s own parser (no PyYAML). PR-checked and stale-checked. |
| 10 | The plan artifact (`morning-send`, from the job that parses untrusted PDFs) | Untrusted data: downloaded to `$RUNNER_TEMP`, outside the checkout and `sys.path`; layout, names, symlinks and size checked by "Validate the plan files"; schema, bodies and links by `sender.deliver.check_plan`. Never executed. |
| 11 | `data/` | Not read by the note job and not on `sys.path`; so it is safe to leave out of the PR check. |
| 12 | Environment and secrets | Key and canary ids only in the deliver step's env; `GH_TOKEN` (read-only) only in the PR check; `-I` ignores `PYTHON*`. |
| 13 | Installed packages | None: no pip step, no cache; `-S` leaves out site-packages entirely. Interpreter from `setup-python` (pinned). |
| 14 | The PR-baseline check | Pathspec widened from `sender/ config/site.yml .github/` to `. ':(exclude)data/'`: any direct push outside `data/` after `MAIN_PR_BASELINE` refuses the send. Fails closed on an unset baseline, shallow history or an API error. The stale-rerun check uses the same pathspec. |

## Residual (not code paths; covered by people, recorded in the runbook)
- A writer who merges their own PR with 0 approvals, or a workflow pushed to main that drops the checks: the required
  reviewer on the `morning-note` environment (runbook 5.0) stops the job before it gets the key.
- S3 (unverified): pushing a PR's head straight to main can mark the PR merged with that sha as `merge_commit_sha`;
  covered only by the required reviewer.
