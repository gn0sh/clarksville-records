"""Render the static site from a facts file. Entry point: `build(facts_path, out_dir, internal=False)`."""
from __future__ import annotations

import functools
import json
import posixpath
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

import jinja2
from jsonschema import Draft202012Validator, FormatChecker

from . import county_agendas as agendas_mod
from . import rpc as rpc_mod
from . import morning_page
from . import budget_views, config, council as council_mod, days as days_mod, feeds as feeds_mod, fin_views, \
    georef as georef_mod, morning as morning_mod, \
    transcripts as transcripts_mod, \
    seats as seats_mod, views


class BuildError(Exception):
    pass


FORMAT_CHECKER = FormatChecker()


@FORMAT_CHECKER.checks("uri")
def _is_https_uri(value) -> bool:
    """`format: uri` in our schemas means an absolute https URL with a host and no whitespace, quotes or angle
    brackets. jsonschema's own uri check needs an optional package, so the rule is defined here, in one place."""
    if not isinstance(value, str):
        return True
    if any(c.isspace() or c in "\"'<>`\\" or ord(c) < 32 for c in value):
        return False
    u = urlsplit(value)
    return u.scheme.lower() in config.ALLOWED_URL_SCHEMES and bool(u.netloc) and value.lower().startswith("https://")


def _validator(schema_path: Path) -> Draft202012Validator:
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FORMAT_CHECKER)


def _schema_errors(validator: Draft202012Validator, doc) -> list[str]:
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))

    def message(e) -> str:
        if e.validator == "format" and e.validator_value == "uri":
            return f"{e.instance!r} is not allowed: source links must be https:// URLs"
        return e.message

    return [f"  {'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {message(e)}" for e in errors[:20]]


def check_references(facts: dict) -> None:
    """Every id a fact points at must exist. Raises BuildError naming the first missing id and where it was used."""
    ids = {k: {x["id"] for x in facts[k]} for k in ("sources", "officials", "meetings", "items", "motions", "roll_calls")}

    def need(kind: str, value, where: str) -> None:
        if value not in ids[kind]:
            raise BuildError(f"{where} refers to {kind[:-1]} id {value!r}, which is not in the facts file")

    def need_official(ref, where: str) -> None:
        if ref is not None and ref["official_id"] is not None:
            need("officials", ref["official_id"], where)

    for m in facts["meetings"]:
        need("sources", m["source_id"], f"meeting {m['id']}")
        for a in m["attendance"]:
            need_official(a, f"meeting {m['id']} attendance")
    for e in facts["item_events"]:
        where = f"item event {e['id']}"
        need("items", e["item_id"], where)
        need("meetings", e["meeting_id"], where)
        need("sources", e["source_id"], where)
        if e["ref"] is not None:
            if e["type"] == "motion":
                need("motions", e["ref"], where)
            elif e["type"] == "roll_call":
                need("roll_calls", e["ref"], where)
            elif e["ref"] not in ids["motions"] | ids["roll_calls"]:
                raise BuildError(f"{where} refers to motion or roll call id {e['ref']!r}, which is not in the facts file")
    for mo in facts["motions"]:
        where = f"motion {mo['id']}"
        need("meetings", mo["meeting_id"], where)
        need("items", mo["item_id"], where)
        need("sources", mo["source_id"], where)
        need_official(mo["moved_by"], where + " moved_by")
        need_official(mo["seconded_by"], where + " seconded_by")
    for rc in facts["roll_calls"]:
        where = f"roll call {rc['id']}"
        need("meetings", rc["meeting_id"], where)
        need("items", rc["item_id"], where)
        need("sources", rc["source_id"], where)
        if rc["motion_id"] is not None:
            need("motions", rc["motion_id"], where)
        for v in rc["votes"]:
            need_official(v, where + " vote")
    for c in facts["corrections"]:
        need("sources", c["source_id"], f"correction of {c['fact_id']}")
    for it in facts["items"]:
        for name, f in (it.get("zoning") or {}).items():
            if f is not None:
                need("sources", f["source_id"], f"item {it['id']} zoning {name}")


def load_facts(facts_path: Path) -> dict:
    facts = json.loads(Path(facts_path).read_text(encoding="utf-8"))
    lines = _schema_errors(_validator(config.SCHEMA_PATH), facts)
    if lines:
        raise BuildError(f"{facts_path} does not match schema/facts.schema.json:\n" + "\n".join(lines))
    check_references(facts)
    return facts


def load_finance(finance_path: Path, facts_fixture: bool) -> dict:
    """data/finance.json (schema/finance.schema.json), reference- and scan-checked (architecture 7). A FIXTURE finance
    file is never mixed with real facts, nor real finance with fixture facts: made-up vendors must never sit on a
    real build, and the FIXTURE banner covers every page or none."""
    fin = json.loads(Path(finance_path).read_text(encoding="utf-8"))
    lines = _schema_errors(_validator(config.FINANCE_SCHEMA_PATH), fin)
    if lines:
        raise BuildError(f"{finance_path} does not match schema/finance.schema.json:\n" + "\n".join(lines))
    try:
        fin_views.check_references(fin)
    except fin_views.FinanceError as exc:
        raise BuildError(f"{finance_path}: {exc}") from exc
    if bool(fin.get("fixture")) != facts_fixture:
        raise BuildError(f"{finance_path}: a {'FIXTURE' if fin.get('fixture') else 'real'} finance file cannot be "
                         f"built with a {'FIXTURE' if facts_fixture else 'real'} facts file")
    return fin


def make_env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(config.TEMPLATE_DIR)),
        autoescape=jinja2.select_autoescape(["html", "j2"]),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # the not_confirmed macro's sentence per held check (provenance/held-sentence-misstates)
    env.globals["held_text"] = config.FIN_TEXT["held"]
    return env


def read_changes(path: Path | None) -> list[dict]:
    if path is None or not Path(path).is_file():
        return []
    validator = _validator(config.CHANGES_SCHEMA_PATH)
    entries = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BuildError(f"{path} line {n}: not valid JSON ({exc})") from exc
        problems = _schema_errors(validator, entry)
        if problems:
            raise BuildError(f"{path} line {n} does not match schema/changes.schema.json:\n" + "\n".join(problems))
        entries.append(entry)
    return entries


def read_report(path: Path | None) -> dict | None:
    if path is None or not Path(path).is_file():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _clean(out: Path, extra_dirs=(), export: bool = True) -> None:
    """Remove what this generator owns. `data/` belongs to the collector's export and is left alone, unless the build
    goes without the export (`export` False): then an earlier export there is removed, so no stale data/ file is
    published beside a data.html that says the files are not there. `extra_dirs`: each council's page folder
    (council.yml slug)."""
    out.mkdir(parents=True, exist_ok=True)
    if not export:
        shutil.rmtree(out / "data", ignore_errors=True)
    for p in out.glob("*.html"):
        p.unlink()
    for d in ("officials", "meetings", "items", "static", "districts", "votes", "contracts", "finance", "capital",
              feeds_mod.FOLDER, morning_mod.FOLDER, *extra_dirs):
        shutil.rmtree(out / d, ignore_errors=True)


def load_councils(councils, fixture: bool) -> list:
    """Each council (a config.COUNCILS entry): its facts file, schema- and reference-checked like the county's, and
    its wards file, as a council.CouncilIndex. A FIXTURE council is never built beside real county facts, nor a real
    one beside fixture facts (made-up people must never sit next to real ones)."""
    out = []
    for cfg in councils:
        facts = load_facts(cfg["facts_path"])
        if bool(facts.get("fixture")) != fixture:
            raise BuildError(f"{cfg['facts_path']}: a {'FIXTURE' if facts.get('fixture') else 'real'} council facts "
                             f"file cannot be built with a {'FIXTURE' if fixture else 'real'} county facts file")
        wards_path = Path(cfg["wards_path"])
        wards = json.loads(wards_path.read_text(encoding="utf-8")) if wards_path.is_file() else []
        out.append(council_mod.load(cfg, facts, wards))
    return out


def write_publish_manifest(out: Path, target: str | None = None) -> dict:
    """{published path: local path}, index.html excluded. Call again after the export adds data/ files.
    `target`: the host the build is for (config.MAX_FILES_BY_TARGET): its file cap applies."""
    out = Path(out)
    files = sorted(p for p in out.rglob("*") if p.is_file())
    cap = config.max_files(target)
    if len(files) > cap:
        raise BuildError(f"site has {len(files)} files; the limit for the {target} target is {cap}")
    manifest = {p.relative_to(out).as_posix(): str(p) for p in files if p.relative_to(out).as_posix() != "index.html"}
    (out.parent / "publish-files.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def export_file_count(fixture: bool, councils, finance: bool, rpc: bool = False) -> int:
    """How many files the open-data export (collector/export.py export_site) adds under data/: facts.json plus one
    CSV per table for the county and for each council, the Regional Planning Commission's facts.json and CSVs when its
    pages are built (`rpc`), and finance.json plus its CSVs when finance is built."""
    from collector.export import CSV_FILES
    from collector.fin_export import FIN_FILES
    from collector.rpc_export import RPC_FILES
    per_body = 1 + len(CSV_FILES)
    return (per_body * (1 + len(councils)) + ((1 + len(RPC_FILES)) if rpc else 0)
            + ((1 + len(FIN_FILES)) if finance and not fixture else 0))


def balanced_chunks(weights: list[int], k: int) -> list[range]:
    """Split indexes 0..n-1 into at most k contiguous, non-empty runs of about equal total weight."""
    n, total = len(weights), sum(weights) or 1
    k = max(1, min(k, n))
    cuts, acc, j = [0], 0, 1
    for i, w in enumerate(weights):
        acc += w
        if j < k and acc >= total * j / k and i + 1 < n and i + 1 > cuts[-1]:
            cuts.append(i + 1)
            j += 1
    cuts.append(n)
    return [range(a, b) for a, b in zip(cuts, cuts[1:]) if b > a]


def plan_parts(entries: list[dict], size_of, weights: list[int] | None = None) -> list[list[str]]:
    """The parts of one year page (city-pages/page-weight): [[entry id, ...], ...] in page order. One part when the
    page fits config.PAGE_BYTES; otherwise contiguous runs by date, each weighed by its context's size (or `weights`),
    as few as keep every part under PAGE_BYTES. `size_of(entries)` renders a page of those entries and returns its
    bytes. Also the fund and capital pages, by heading (finance-pages/page-weight)."""
    import math
    size = size_of(entries)
    if size <= config.PAGE_BYTES or len(entries) < 2:
        return [[e["id"] for e in entries]]
    weights = weights or [len(json.dumps(e, default=str)) for e in entries]
    k = math.ceil(size / config.PAGE_TARGET)
    while True:
        runs = [[entries[i] for i in r] for r in balanced_chunks(weights, k)]
        if k >= len(entries) or all(size_of(run) <= config.PAGE_BYTES for run in runs):
            return [[e["id"] for e in run] for run in runs]
        k += 1


def pack_years(groups: list[dict], size_of) -> list[list[dict]]:
    """A council member's history pages (city-pages/file-budget): the year groups (newest first) in runs of
    consecutive years, each run one page, a run growing while `size_of(run)` (the rendered page's bytes) stays under
    config.PAGE_TARGET. A year too big for that on its own keeps its own page. Order is never changed. Only adjacent
    years join (city-pages/year-run-label): a page named "2018-2023" would imply service in the years between."""
    runs: list[list[dict]] = []
    for g in groups:
        if (runs and int(runs[-1][-1]["year"]) - int(g["year"]) == 1
                and size_of(runs[-1] + [g]) <= config.PAGE_TARGET):
            runs[-1].append(g)
        else:
            runs.append([g])
    return runs


def years_key(run: list[dict]) -> str:
    """A history page's name from its years: '2024' alone, '2024-2026' for a run (oldest first)."""
    ys = sorted(g["year"] for g in run)
    return ys[0] if len(ys) == 1 else f"{ys[0]}-{ys[-1]}"


def part_label(dates: list[str]) -> str:
    dates = sorted(d for d in dates if d)
    if not dates:
        return "No appearance listed"
    return dates[0] if dates[0] == dates[-1] else f"{dates[0]} to {dates[-1]}"


DEFAULT = object()


SITE_URL_KEYS = ("redistricting_page", "old_lines_map_url", "swap_source", "support_url", "operator_url",
                "district_lookup_url", "geocoder_url", "geocoder_privacy_url")

# geocoder_url goes into the landing's CSP script-src as a source expression and gets the address box's query added,
# so it is a plain https base: host and path characters only (no query, fragment, space, quote, ';' or ',').
_GEOCODER_BASE = re.compile(r"https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?(?:/[A-Za-z0-9._~%!$()*+=:@/-]*)?")
# Words the address box and the lookup line show, required with the link they name (addr-pin/privacy-copy-not-config).
SITE_TEXT_FOR = {"geocoder_url": ("geocoder_label", "geocoder_short", "geocoder_privacy_url"),
                 "district_lookup_url": ("district_lookup_label",)}


def site_url_problems(cfg: dict) -> list[str]:
    """Every link in config/site.yml must be https (N4); an empty value means "not set" and is never rendered.
    geocoder_url is a base the address box adds its own query to, so it may carry no query or fragment."""
    out = [f"{k} must be an https link, got {cfg[k]!r}" for k in SITE_URL_KEYS
           if cfg.get(k) and not _is_https_uri(cfg[k])]
    if cfg.get("geocoder_url") and not _GEOCODER_BASE.fullmatch(str(cfg["geocoder_url"])):
        out.append(f"geocoder_url must be a base URL with no query or fragment, got {cfg['geocoder_url']!r}")
    for link, needs in SITE_TEXT_FOR.items():
        if cfg.get(link):
            out += [f"{k} must be set when {link} is" for k in needs
                    if not isinstance(cfg.get(k), str) or not cfg[k].strip()]
    return out + corrections_problems(cfg) + feeds_mod.problems(cfg) + morning_mod.problems(cfg)


# config/site.yml `corrections:` (views.corrections_context): a GitHub owner/name and a plain e-mail address. Both go
# into an href, so only these shapes are allowed (no query, fragment, space, quote or angle bracket).
_GITHUB_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}")
_EMAIL = re.compile(r"[A-Za-z0-9._+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")

# Templates of fact-bearing pages: each gets the page-level "Report an error on this page" link (base.html.j2).
REPORT_TEMPLATES = frozenset({
    "meeting.html.j2", "items_year.html.j2", "votes_year.html.j2", "official.html.j2", "official_year.html.j2",
    "official_roster.html.j2", "district.html.j2", "council_home.html.j2", "council_meetings_year.html.j2",
    "council_items_year.html.j2", "fin_index.html.j2", "fin_fund.html.j2", "fin_capital.html.j2",
    "fin_contracts_index.html.j2", "fin_solicitation.html.j2", "transcript.html.j2", "rpc_home.html.j2",
    "rpc_meetings_year.html.j2", "today.html.j2", "county_agendas.html.j2", "morning.html.j2"})


def corrections_problems(cfg: dict) -> list[str]:
    c = cfg.get("corrections")
    if c is None:
        return []
    if not isinstance(c, dict):
        return ["corrections must be a mapping with github_repo and email"]
    out = [f"corrections has an unknown key {k!r}" for k in c if k not in ("github_repo", "email")]
    repo, email = c.get("github_repo") or "", c.get("email") or ""
    if repo and not (isinstance(repo, str) and _GITHUB_REPO.fullmatch(repo) and ".." not in repo
                     and all(part not in (".", "..") for part in repo.split("/"))):
        out.append(f"corrections.github_repo must be owner/name, got {repo!r}")
    if email and not (isinstance(email, str) and _EMAIL.fullmatch(email) and ".." not in email):
        out.append(f"corrections.email must be a plain address, got {email!r}")
    return out


def build(facts_path, out_dir, internal: bool = False, changes_path=None, report_path=None,
          seats_path=DEFAULT, districts_path=DEFAULT, geocoder: bool = True, finance_path=DEFAULT,
          capital_fund=DEFAULT, councils=DEFAULT, target: str | None = None, transcripts: bool = True,
          rpc=DEFAULT, today=None, county_agendas=DEFAULT, morning_manifests=DEFAULT,
          export: bool = True) -> dict:
    """`geocoder=False` (`--no-geocoder`) draws no landing address box and allows no geocoder in the CSP: the build
    for the claude.ai preview, where the box could not reach the geocoder. The plain lookup line shows instead.
    `seats_path` / `districts_path`: the roster and map files. Left out, a real build reads config/seats.yml and
    config/localities/<locality>/districts.json; a fixture facts file reads neither (made-up people must never be
    joined to the real roster), so tests pass their own fixture files. None means: no such file.
    `finance_path`: finance.json (bids and awards). Left out, a real build reads finance.json next to the facts file
    when it exists; a fixture facts file reads none. Without it the Bids and awards pages are not written and Finance
    keeps its "coming" page. With budget lines in it, Finance (finance/index.html, one page per fund) and Capital
    projects (capital/index.html) replace their "coming" pages.
    `capital_fund`: the fund the capital projects page shows; left out, config.CAPITAL_FUND (finance.yml), or the
    FIXTURE fund for a fixture build.
    `councils`: the councils to build beside the county (config.COUNCILS entries, council.yml); left out, a real
    build builds config.COUNCILS and a fixture build none. Each gets its pages under its own folder (council.py).
    `target`: "preview" (the claude.ai artifact, config.MAX_FILES_BY_TARGET caps it at 500 files) or "pages" (GitHub
    Pages). When the preview build with its export would pass its cap, it is built again without the transcript
    pages (`transcripts=False`): each meeting with a transcript then says so, and the member pages keep their
    call-ons with the video links (sitegen/transcripts.py). Year and meeting pages are never split to make room.
    `rpc`: the Regional Planning Commission's rpc.yml as rpc.load_config returns it, or None for no RPC pages; left
    out, config/site.yml `rpc:` for a real build and none for a fixture build (sitegen/rpc.py).
    `today`: the date the day page (sitegen/days.py, today.html) is built around; left out, today in the site's zone
    (or RECORDS_TODAY).
    `county_agendas`: the county agendas file (collector/county_agenda.py) whose meetings the minutes do not cover yet
    are shown as agenda-only meetings (sitegen/county_agendas.py); left out, config.COUNTY_AGENDAS for a real build
    and none for a fixture build. None: no agenda-only meetings.
    `morning_manifests`: the collectors' manifests the morning note (sitegen/morning.py) reads first_fetched_at from;
    left out, config/site.yml `morning_note.manifests` for a real build and none for a fixture build (made-up sources
    have no manifest rows). None: no morning/ files. The preview target writes none.
    `export`: whether the open-data export (collector export, data/) goes with this build. A preview still over its
    cap without the transcript pages is built again with export=False: no page (data.html, about.html, the finance
    and contracts indexes) links a data/ file, data.html and about.html say the files are on the full site, and any
    earlier export in `out_dir/data` is removed."""
    target = target or config.DEFAULT_TARGET
    if target not in config.MAX_FILES_BY_TARGET:
        raise BuildError(f"unknown target {target!r}; one of {', '.join(sorted(config.MAX_FILES_BY_TARGET))}")
    facts_path, out = Path(facts_path), Path(out_dir)
    facts = load_facts(facts_path)
    fixture = bool(facts.get("fixture"))
    if seats_path is DEFAULT:
        seats_path = None if fixture else config.SEATS_PATH
    if districts_path is DEFAULT:
        districts_path = None if fixture else config.DISTRICTS_PATH
    if finance_path is DEFAULT:  # the default file is optional; a path given by name must exist
        finance_path = None if fixture else facts_path.parent / "finance.json"
        if finance_path is not None and not finance_path.is_file():
            finance_path = None
    elif finance_path is not None and not Path(finance_path).is_file():
        raise BuildError(f"{finance_path}: no such finance file")
    fin_data = load_finance(finance_path, fixture) if finance_path is not None else None
    try:
        seat_rows = seats_mod.load_rows(seats_path)
        districts = seats_mod.load_districts(districts_path)
        georef = georef_mod.load_for_map(districts_path, districts)
        ward_map = georef_mod.wards_of(districts) is not None    # the landing map draws the wards and finds them
    except (seats_mod.SeatsError, ValueError) as exc:
        raise BuildError(str(exc)) from exc
    bad = site_url_problems(config.SITE)
    if bad:
        raise BuildError("config/site.yml: " + "; ".join(bad))
    ix = views.Index(facts, seat_rows)
    built_day = today or days_mod.today_in_zone()
    # County agendas posted before their minutes (sitegen/county_agendas.py); none for a fixture build
    if county_agendas is DEFAULT:
        county_agendas = None if fixture else config.COUNTY_AGENDAS
    ax = agendas_mod.make(ix, built_day, county_agendas)
    if councils is DEFAULT:
        councils = () if fixture else config.COUNCILS
    cixs = load_councils(councils, fixture)
    for c in cixs:
        try:
            c.tx = transcripts_mod.Transcripts(c, transcripts_mod.load(c.cfg["facts_path"], c.facts), pages=transcripts)
        except transcripts_mod.TranscriptLoadError as exc:
            raise BuildError(str(exc)) from exc
    try:
        if rpc is DEFAULT:   # a fixture build reads no real RPC facts
            rpc = None if fixture else rpc_mod.load_config(config.SITE.get("rpc"))
        rpx = rpc_mod.load(rpc, fixture)
    except (rpc_mod.RpcError, OSError, ValueError) as exc:
        raise BuildError(str(exc)) from exc
    if rpx is not None:   # Planning Commission -> County Commission: CZ- cases link to the county's items both ways
        rpx.link_county(ix)
    fx = fin_views.Finance(fin_data, facts["officials"]) if fin_data is not None else None
    if capital_fund is DEFAULT:
        capital_fund = config.FIXTURE_CAPITAL_FUND if fixture else config.CAPITAL_FUND
    try:
        bg = budget_views.Budget(fx, capital_fund) if fx is not None and fin_data.get("budget_lines") else None
    except fin_views.FinanceError as exc:
        raise BuildError(f"{finance_path}: {exc}") from exc
    budget_pages = () if bg is None else ("Finance",) + (("Capital projects",) if bg.capital_fund else ())
    coming_slugs = {"Finance": "finance", "Capital projects": "capital-projects"}
    env = make_env()

    if config.OPERATOR_NAME == config.OPERATOR_PLACEHOLDER:
        print(f"WARNING: OPERATOR_NAME in sitegen/config.py is still the placeholder "
              f"{config.OPERATOR_PLACEHOLDER!r}. A public build must not use it.", file=sys.stderr)

    if changes_path is None:
        changes_path = facts_path.parent / "changes.jsonl"
    if report_path is None:
        report_path = out.parent / "report.json"

    _clean(out, [c.slug for c in cixs] + ([rpx.slug] if rpx else []), export=export)
    site = views.site_context(ix, contracts=fx is not None, budget=budget_pages, councils=cixs, rpc=rpx)
    site["internal"] = internal
    site["councils"] = [council_mod.landing_entry(c) for c in cixs]
    site["transcripts_omitted"] = not transcripts
    site["ward_map"] = ward_map
    site["export_omitted"] = not export
    # None unless the morning note's sign-up form is enabled: then the landing and Method pages drop "never sent"
    site["morning_note"] = morning_page.privacy()
    if rpx is not None:
        site["rpc_record"] = {"url": rpx.cfg["record_url"], "label": rpx.cfg["record_label"]}
    written: list[str] = []

    def html_of(template: str, rel: str, page_name: str, site_ctx=None, **ctx) -> str:
        depth = rel.count("/")
        return env.get_template(template).render(
            site=site_ctx or site, root="../" * depth, page_name=page_name,
            report_page=template in REPORT_TEMPLATES,
            official_record=views.official_record(template, site_ctx or site, ctx), **ctx)

    def render(template: str, rel: str, page_name: str, site_ctx=None, **ctx) -> None:
        html = html_of(template, rel, page_name, site_ctx, **ctx)
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        written.append(rel)

    # Year pages (items; a council's meetings), split in parts when over config.PAGE_BYTES (city-pages/page-weight).
    # Each: (Index, kind, template, folder, year, page name, site ctx, extra ctx, list key, date of an entry, ctx).
    def year_specs():
        for year in ix.item_years():
            yield (ix, "item", "items_year.html.j2", "items", year, f"Items {year}", None, {}, "items",
                   lambda e: e["first"], lambda y: views.items_year(y, ix))
        for c in cixs:
            cs = council_mod.site_for(site, c)
            extra = {"council": c.nav_label, "council_href": c.home_href()}
            for y in c.meeting_years():
                yield (c, "meeting", "council_meetings_year.html.j2", f"{c.slug}/meetings", y,
                       c.page_name(f"Meetings {y}"), cs, extra, "meetings", lambda e: e["meeting"]["date"],
                       lambda y, c=c: council_mod.meetings_year(y, c))
            for y in c.item_years():
                yield (c, "item", "council_items_year.html.j2", f"{c.slug}/items", y, c.page_name(f"Items {y}"), cs,
                       extra, "items", lambda e: e["first"], lambda y, c=c: council_mod.items_year(y, c))

    def with_entries(ctx: dict, key: str, entries: list[dict]) -> dict:
        out_ctx = {**ctx, key: entries}
        if key == "items":
            out_ctx["toc_groups"] = views._toc_groups(entries)
        return out_ctx

    plans = {}
    for (bix, kind, tpl, folder, year, name, sctx, extra, key, date_of, make) in year_specs():
        ctx = make(year)
        rel = f"{folder}/{year}.html"
        parts = plan_parts(ctx[key], lambda es: len(html_of(tpl, rel, name, sctx, **extra,
                                                                  **with_entries(ctx, key, es)).encode("utf-8")))
        plans[(folder, year)] = parts
        for n, ids in enumerate(parts, 1):
            for i in ids:
                bix.page_parts[(kind, i)] = n

    # Transcript pages (sitegen/transcripts.py), one per meeting, in parts by line when over config.PAGE_BYTES; planned
    # before any page links a line, so each line link names its part.
    tx_plans = []
    for c in cixs:
        if not c.tx.pages:
            continue
        cs = council_mod.site_for(site, c)
        extra = {"council": c.nav_label, "council_href": c.home_href()}
        for mid in sorted(c.tx.by_meeting):
            ctx = c.tx.page(mid)
            name = c.page_name(f"Transcript {ctx['meeting']['date']}")
            rel = c.tx.page_href(mid)

            def size_of(es, ctx=ctx, rel=rel, name=name, cs=cs, extra=extra):
                return len(html_of("transcript.html.j2", rel, name, cs, **extra,
                                   **{**ctx, "lines": es, "parts": []}).encode("utf-8"))

            parts = plan_parts(ctx["lines"], size_of, [len(x["text"]) + 200 for x in ctx["lines"]])
            for n, ids in enumerate(parts, 1):
                for i in ids:
                    c.tx.part_of[(mid, int(i[1:]))] = n
            tx_plans.append((c, cs, extra, mid, name, parts))

    def render_transcript_pages():
        for c, cs, extra, mid, name, parts in tx_plans:
            ctx = c.tx.page(mid)
            by_id = {x["id"]: x for x in ctx["lines"]}
            runs = [[by_id[i] for i in ids] for ids in parts]
            nav = [{"href": posixpath.basename(c.tx.page_href(mid, n)),
                    "label": f"{run[0]['time']} to {run[-1]['time']}"}
                   for n, run in enumerate(runs, 1)] if len(runs) > 1 else []
            for n, run in enumerate(runs, 1):
                render("transcript.html.j2", c.tx.page_href(mid, n), name if n == 1 else f"{name} (part {n})", cs,
                       **extra, **{**ctx, "lines": run, "parts": [{**p, "current": i == n} for i, p in enumerate(nav, 1)]})

    def render_year_pages():
        for (bix, kind, tpl, folder, year, name, sctx, extra, key, date_of, make) in year_specs():
            ctx = make(year)   # again, now that every link knows its part
            by_id = {e["id"]: e for e in ctx[key]}
            parts = plans[(folder, year)]
            runs = [[by_id[i] for i in ids] for ids in parts]
            nav = [{"href": f"{year}{'' if n == 1 else f'-{n}'}.html", "label": part_label([date_of(e) for e in run])}
                   for n, run in enumerate(runs, 1)] if len(runs) > 1 else []
            for n, run in enumerate(runs, 1):
                suffix = "" if n == 1 else f"-{n}"
                render(tpl, f"{folder}/{year}{suffix}.html", name if n == 1 else f"{name} (part {n})", sctx, **extra,
                       **{**with_entries(ctx, key, run),
                          "parts": [{**p, "current": i == n} for i, p in enumerate(nav, 1)]})

    render("index.html.j2", "index.html", "Map", **views.landing(ix, districts, georef, geocoder, site["councils"]))
    render("officials.html.j2", "officials.html", "Officials", **views.officials_page(ix))
    render("meetings_index.html.j2", "meetings.html", "Meetings", **views.meetings_page(ix),
           agenda_only=ax.list_entries() if ax else [], agendas_href=agendas_mod.PAGE,
           agenda_list_lede=config.COUNTY_AGENDAS_TEXT["list_lede"])
    if ax and ax.meetings:
        render("county_agendas.html.j2", agendas_mod.PAGE, "Agendas without minutes yet", **ax.page())
    for n in range(1, config.SITE["district_count"] + 1):
        ctx = views.district(n, ix, districts)
        render("district.html.j2", f"districts/{n:02d}.html", ctx["title"], **ctx)
    for year in site["vote_years_desc"]:
        render("votes_year.html.j2", f"votes/{year}.html", f"Votes {year}", **views.votes_year(year, ix))
    render("search.html.j2", "search.html", "Search", **views.search_page(ix, fx, cixs, rpx))
    for c in config.SITE["coming"]:
        if c["slug"] in {coming_slugs[p] for p in budget_pages}:
            continue
        render("coming.html.j2", f"{c['slug']}.html", c["title"], **views.coming(c["slug"]))
    render("data.html.j2", "data.html", "Data downloads",
           **views.data_page(cixs, finance=fx is not None and fin_views.EXPORTS_READY and not fixture, rpc=rpx))
    if fx is not None:
        title = config.FIN_TEXT["contracts"]["title"]
        render("fin_contracts_index.html.j2", "contracts/index.html", title,
               **fin_views.contracts_index(fx, export=export))
        for sol in fin_data["solicitations"]:
            ctx = fin_views.solicitation(sol["id"], fx)
            render("fin_solicitation.html.j2", f"contracts/{sol['slug']}.html", f"{title}: {sol['title']}", **ctx)
        render("glossary.html.j2", "glossary.html", "Glossary", **fin_views.glossary())
    if bg is not None:
        title = config.FIN_TEXT["budget"]["title"]
        render("fin_index.html.j2", budget_views.INDEX, title, **budget_views.finance_index(bg, export=export))
        # Fund and capital pages over config.PAGE_BYTES are split in parts by heading (finance-pages/page-weight):
        # every fund is planned first, so each line's row has its part before any page links to it.
        split = []
        for no in bg.funds:
            split.append(("fin_fund.html.j2", bg.fund_href(no), None, functools.partial(budget_views.fund, no, bg),
                          "sections", True))
        if bg.capital_fund:
            split.append(("fin_capital.html.j2", budget_views.CAPITAL, config.FIN_TEXT["budget"]["capital_title"],
                          functools.partial(budget_views.capital, bg), None, False))
        planned = []
        for tpl, rel, name, make, key, owns_lines in split:
            full = make()
            name = name or f"{title}: {full['title']}"
            us = budget_views.units(full, key)
            by_id = {u["id"]: u for u in us}
            parts = plan_parts(us, lambda es: len(html_of(tpl, rel, name, parts=[], **make(
                keep={e["id"] for e in es}, page=rel)).encode("utf-8")), [u["weight"] for u in us]) if us else [[]]
            stem = rel[:-len(".html")]
            paths = [rel if n == 1 else f"{stem}-{n}.html" for n in range(1, len(parts) + 1)]
            part_of = {gid: path for ids, path in zip(parts, paths) for gid in ids}
            if owns_lines and len(parts) > 1:
                for gid, path in part_of.items():
                    for line_id in by_id[gid]["lines"]:
                        bg.line_pages[line_id] = path
            planned.append((tpl, name, make, parts, paths, part_of, by_id))
        for tpl, name, make, parts, paths, part_of, by_id in planned:
            nav = [{"href": posixpath.basename(p), "label": budget_views.part_label([by_id[i] for i in ids])}
                   for ids, p in zip(parts, paths)] if len(parts) > 1 else []
            for n, (ids, path) in enumerate(zip(parts, paths), 1):
                ctx = make(keep=set(ids), page=path, part_of=part_of) if len(parts) > 1 else make()
                render(tpl, path, name if n == 1 else f"{name} (part {n})",
                       **ctx, parts=[{**p, "current": i == n} for i, p in enumerate(nav, 1)])
    for o in facts["officials"]:
        ctx = views.official(o["id"], ix)
        render("official.html.j2", f"officials/{o['id']}.html", o["name"], **ctx)
    for oid in sorted(ix.seats.roster_only):  # in the roster, not in the facts: a page that says nothing is recorded
        ctx = views.roster_official(oid, ix)
        render("official_roster.html.j2", f"officials/{oid}.html", ctx["official"]["name"], **ctx)
    for m in facts["meetings"]:
        ctx = views.meeting(m["id"], ix)
        render("meeting.html.j2", f"meetings/{m['id']}.html", f"Meeting {m['date']}", m=ctx, **ctx)
    render_year_pages()   # county items; each council's meetings and items (in parts when too big)
    render_transcript_pages()
    for c in cixs:  # council pages (council.py): home, one page per member and per year of their history
        cs = council_mod.site_for(site, c)
        render("council_home.html.j2", c.home_href(), c.page_name(), cs, council=c.nav_label,
               council_href=c.home_href(), **council_mod.home(c))
        for o in c.facts["officials"]:
            ctx = council_mod.member(o["id"], c)
            groups = [g for g in ctx["row_groups"] if g["year"]]

            def year_page(run, ctx=ctx, o=o):
                key = years_key(run)
                rel = f"{c.slug}/members/{o['id']}/{key}.html"
                label = key.replace("-", " to ")
                return rel, (f"{o['name']} {label}", cs), dict(
                    council=c.nav_label, council_href=c.home_href(), official=ctx["official"],
                    official_href=c.official_href(o["id"]), year=label, years=[g["year"] for g in run],
                    year_pages=ctx["year_pages"], types=ctx["types"], groups=run)

            def size_of(run):
                rel, (name, s), kw = year_page(run)
                return len(html_of("official_year.html.j2", rel, name, s, **kw).encode("utf-8"))

            runs = pack_years(groups, size_of)
            c.year_pages[o["id"]] = {g["year"]: years_key(run) for run in runs for g in run}
            ctx = council_mod.member(o["id"], c)      # the year links now name each year's page
            render("official.html.j2", c.official_href(o["id"]), o["name"], cs, **ctx)
            for run in runs:
                run = [g for g in ctx["row_groups"] if g["year"] in {x["year"] for x in run}]
                rel, (name, s), kw = year_page(run, ctx)
                render("official_year.html.j2", rel, name, s, **kw)
    if rpx is not None:   # Regional Planning Commission (sitegen/rpc.py): home and one page per year of meetings
        render("rpc_home.html.j2", rpx.home_href(), rpx.page_name(), **rpx.home())
        for y in rpx.years():
            render("rpc_meetings_year.html.j2", rpx.year_href(y), rpx.page_name(f"Meetings {y}"),
                   rpc_href=rpx.home_href(), rpc_label=rpx.nav_label, **rpx.meetings_year(y))
    # Day by day (Daylight M2): after the year pages, so every council meeting link knows its part
    try:
        render("today.html.j2", days_mod.PAGE, "Today", **days_mod.page(ix, cixs, rpx, fx, built_day, ax=ax))
    except days_mod.DaysError as exc:
        raise BuildError(str(exc)) from exc
    render("about.html.j2", "about.html", "About", **views.about(ix), glance=views.record_glance(ix))
    trust = views.trust_pages(ix)
    render("who.html.j2", "who-runs-this.html", "Who runs this", **trust)
    render("rules.html.j2", "our-rules.html", "Our rules", **trust)
    render("corrections.html.j2", "corrections.html", "Corrections", **trust)
    render("method.html.j2", "method.html", "Method", **trust)
    render("changes.html.j2", "changes.html", "Changes", **views.changes(read_changes(changes_path)))
    render("report.html.j2", "report.html", "Report an error", **views.report_page())
    feed_rows = feeds_mod.feed_list(cixs, rpc=rpx, fin=fin_data, target=target) if site["alerts"] else []
    if site["alerts"]:   # Alerts v1 (sitegen/feeds.py): written last, when every item and meeting link knows its part
        for rel, body in feeds_mod.build_feeds(ix, cixs, rpc=rpx, fin=fin_data, target=target).items():
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            (out / rel).write_bytes(body)
    if morning_manifests is DEFAULT:
        mn = morning_mod.settings()
        morning_manifests = None if fixture or mn is None else mn["manifests"]
    morning_note = None
    if morning_manifests is not None and morning_mod.settings() is not None and target != "preview":
        # The morning note (Daylight M3, sitegen/morning.py): after every page, so each entry's link knows its part.
        # Pages target only: the claude.ai preview may leave sections out (docs/status.md Decisions, 2026-11-09) and
        # is at its file cap.
        try:
            first = morning_mod.first_fetched(morning_manifests)
            bulk = morning_mod.bulk_urls(morning_manifests, morning_mod.settings()["backfill"]["initial_run_hours"])
            docs = morning_mod.documents(ix, cixs, rpx, ax, fx, bg, first)
            as_of = max([x for x in [ix.data_as_of(), *(c.data_as_of() for c in cixs)] if x != "unknown"]
                        + [s["fetched_at"] for s in (rpx.facts["sources"] if rpx else []) if s.get("fetched_at")],
                        default="")
            morning_note = morning_mod.write(out, built_day, docs, first, data_as_of=as_of, bulk=bulk)
        except morning_mod.MorningError as exc:
            raise BuildError(str(exc)) from exc
    if site["alerts"]:
        # The Alerts page and its #note section (M3 T3), after the note: the preview link is there only when the
        # preview page (morning/index.html, today's note from write()) is built.
        has_preview = morning_note is not None and morning_page.on()
        alerts_ctx = feeds_mod.alerts_page(cixs, rpc=rpx, fin=fin_data, target=target, feeds=feed_rows)
        alerts_ctx.setdefault("seat_feeds", [f for f in feed_rows if f.get("kind") == "zoning-seat"])
        alerts_ctx.update(morning_page.alerts_context(feed_rows, preview=has_preview))
        render("alerts.html.j2", feeds_mod.PAGE, "Alerts", **alerts_ctx)
        if has_preview:
            render("morning.html.j2", morning_page.PAGE, morning_page.title(),
                   **morning_page.preview(morning_note, feed_rows))
    if internal:
        render("review.html.j2", "review.html", "Review (internal)",
               **views.review(ix, read_report(report_path)))

    shutil.copytree(config.STATIC_DIR, out / "static")
    # A script, not a JSON file, so search also works when the site is opened from files or a zip (no fetch).
    index_js = "window.SEARCH_INDEX = " + json.dumps(views.search_index(ix, fx, cixs, rpx), separators=(",", ":"),
                                                     ensure_ascii=True) + ";\n"
    (out / "static" / "search-index.js").write_text(index_js, encoding="utf-8")
    # The built page paths, for static/report.js: a page path in a report link is shown as a page of this site only
    # when it is in this list (report-frag/text-spoof).
    (out / "static" / "pages.js").write_text(
        "window.BUILT_PAGES = " + json.dumps(sorted(written), separators=(",", ":")) + ";\n", encoding="utf-8")
    # The target's file cap, counting the export still to come (data/ in `out` now may be an older export's).
    cap = config.max_files(target)
    built = sum(1 for p in out.rglob("*") if p.is_file() and p.relative_to(out).parts[0] != "data")
    expected = built + (export_file_count(fixture, cixs, fx is not None and fin_views.EXPORTS_READY, rpx is not None)
                        if export else 0)
    tx_pages = sum(len(p[5]) for p in tx_plans)
    if expected > cap and tx_pages and target == "preview":
        print(f"sitegen: {expected} files with the export is over the {target} cap of {cap}; building again without "
              f"the {tx_pages} transcript pages", file=sys.stderr)
        return build(facts_path, out_dir, internal, changes_path, report_path, seats_path, districts_path, geocoder,
                     finance_path, capital_fund, councils, target, transcripts=False, rpc=rpc, today=today,
                     county_agendas=county_agendas, morning_manifests=morning_manifests, export=export)
    if expected > cap and export and target == "preview":
        print(f"sitegen: {expected} files with the export is over the {target} cap of {cap}; building again without "
              f"the open-data export (do not run `collector export` for this preview; data.html says the files are "
              f"on the full site)", file=sys.stderr)
        return build(facts_path, out_dir, internal, changes_path, report_path, seats_path, districts_path, geocoder,
                     finance_path, capital_fund, councils, target, transcripts=transcripts, rpc=rpc, today=today,
                     county_agendas=county_agendas, morning_manifests=morning_manifests, export=False)
    manifest = write_publish_manifest(out, target)
    return {"pages": written, "files": len(manifest) + 1, "target": target, "transcripts": transcripts,
            "transcript_pages": tx_pages, "files_with_export": expected,
            "morning": morning_note, "export": export}
