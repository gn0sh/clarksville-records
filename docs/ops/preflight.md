# Preflight: the local checks before a pull request goes to review

Run these from the repository folder and paste the output in the pull request (playbook step 4).

1. Install: `python -m pip install --require-hashes --only-binary :all: -r requirements.lock` (and `pip install ruff` once).
2. **Data** (ADR 0011): from the cutover on, `main` tracks no `data/`; the collector's output lives on branch
   `records-data`. Fill `data/` from it:
   - bash: `bash scripts/fetch-data.sh`
   - PowerShell: `powershell -NoProfile -File scripts\fetch-data.ps1`

   It never commits or pushes, and keeps the `data/` it replaces at `.git/fetch-data/previous` until the next run.
   Until the cutover `data/` is still tracked, so it prints "nothing to fetch" and changes nothing.
3. Lint: `ruff check .`
4. Tests: `python -m pytest -q` (slow: run it in the background).
   With `--basetemp=<folder>`, give each concurrent session its own folder: a second session on the same folder
   stops with a usage error (`conftest.py`; two sessions sharing one once emptied each other's test folders,
   main-protect/test-flake). Delete the folder after the run.
5. Build and site checks:
   `python -m sitegen --facts data/facts.json --out build/site`, then
   `python -m qa.site_checks --site build/site --facts data/facts.json --store data/store --no-browser`.
