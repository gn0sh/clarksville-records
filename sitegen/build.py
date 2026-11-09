"""Render the static site from a facts file. Entry point: `build(facts_path, out_dir, internal=False)`."""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

import jinja2
from jsonschema import Draft202012Validator, FormatChecker

from . import budget_views, config, council as council_mod, fin_views, georef as georef_mod, seats as seats_mod, views


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


def _clean(out: Path, extra_dirs=()) -> None:
    """Remove what this generator owns. `data/` belongs to the collector's export and is left alone. `extra_dirs`:
    each council's page folder (council.yml slug)."""
    out.mkdir(parents=True, exist_ok=True)
    for p in out.glob("*.html"):
        p.unlink()
    for d in ("officials", "meetings", "items", "static", "districts", "votes", "contracts", "finance", "capital",
              *extra_dirs):
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


def write_publish_manifest(out: Path) -> dict:
    """{published path: local path}, index.html excluded. Call again after the export adds data/ files."""
    out = Path(out)
    files = sorted(p for p in out.rglob("*") if p.is_file())
    if len(files) > config.MAX_FILES:
        raise BuildError(f"site has {len(files)} files; the limit is {config.MAX_FILES}")
    manifest = {p.relative_to(out).as_posix(): str(p) for p in files if p.relative_to(out).as_posix() != "index.html"}
    (out.parent / "publish-files.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


DEFAULT = object()


SITE_URL_KEYS = ("redistricting_page", "old_lines_map_url", "swap_source", "support_url",
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
    return out


def build(facts_path, out_dir, internal: bool = False, changes_path=None, report_path=None,
          seats_path=DEFAULT, districts_path=DEFAULT, geocoder: bool = True, finance_path=DEFAULT,
          capital_fund=DEFAULT, councils=DEFAULT) -> dict:
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
    build builds config.COUNCILS and a fixture build none. Each gets its pages under its own folder (council.py)."""
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
    except (seats_mod.SeatsError, ValueError) as exc:
        raise BuildError(str(exc)) from exc
    bad = site_url_problems(config.SITE)
    if bad:
        raise BuildError("config/site.yml: " + "; ".join(bad))
    ix = views.Index(facts, seat_rows)
    if councils is DEFAULT:
        councils = () if fixture else config.COUNCILS
    cixs = load_councils(councils, fixture)
    county_names = {o["name"]: ix.official_href(o["id"]) for o in facts["officials"]}
    for c in cixs:  # a county official named in a council item title links to their county page
        c.extra_names = county_names
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

    _clean(out, [c.slug for c in cixs])
    site = views.site_context(ix, contracts=fx is not None, budget=budget_pages, councils=cixs)
    site["internal"] = internal
    site["councils"] = [council_mod.landing_entry(c) for c in cixs]
    written: list[str] = []

    def render(template: str, rel: str, page_name: str, site_ctx=None, **ctx) -> None:
        depth = rel.count("/")
        html = env.get_template(template).render(
            site=site_ctx or site, root="../" * depth, page_name=page_name, **ctx)
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        written.append(rel)

    render("index.html.j2", "index.html", "Map", **views.landing(ix, districts, georef, geocoder))
    render("officials.html.j2", "officials.html", "Officials", **views.officials_page(ix))
    render("meetings_index.html.j2", "meetings.html", "Meetings", **views.meetings_page(ix))
    for n in range(1, config.SITE["district_count"] + 1):
        ctx = views.district(n, ix, districts)
        render("district.html.j2", f"districts/{n:02d}.html", ctx["title"], **ctx)
    for year in site["vote_years_desc"]:
        render("votes_year.html.j2", f"votes/{year}.html", f"Votes {year}", **views.votes_year(year, ix))
    render("search.html.j2", "search.html", "Search", **views.search_page(ix, fx, cixs))
    for c in config.SITE["coming"]:
        if c["slug"] in {coming_slugs[p] for p in budget_pages}:
            continue
        render("coming.html.j2", f"{c['slug']}.html", c["title"], **views.coming(c["slug"]))
    render("data.html.j2", "data.html", "Data downloads", **views.data_page())
    if fx is not None:
        title = config.FIN_TEXT["contracts"]["title"]
        render("fin_contracts_index.html.j2", "contracts/index.html", title, **fin_views.contracts_index(fx))
        for sol in fin_data["solicitations"]:
            ctx = fin_views.solicitation(sol["id"], fx)
            render("fin_solicitation.html.j2", f"contracts/{sol['slug']}.html", f"{title}: {sol['title']}", **ctx)
        render("glossary.html.j2", "glossary.html", "Glossary", **fin_views.glossary())
    if bg is not None:
        title = config.FIN_TEXT["budget"]["title"]
        render("fin_index.html.j2", budget_views.INDEX, title, **budget_views.finance_index(bg))
        for no in bg.funds:
            ctx = budget_views.fund(no, bg)
            render("fin_fund.html.j2", bg.fund_href(no), f"{title}: {ctx['title']}", **ctx)
        if bg.capital_fund:
            render("fin_capital.html.j2", budget_views.CAPITAL, config.FIN_TEXT["budget"]["capital_title"],
                   **budget_views.capital(bg))
    for o in facts["officials"]:
        ctx = views.official(o["id"], ix)
        render("official.html.j2", f"officials/{o['id']}.html", o["name"], **ctx)
    for oid in sorted(ix.seats.roster_only):  # in the roster, not in the facts: a page that says nothing is recorded
        ctx = views.roster_official(oid, ix)
        render("official_roster.html.j2", f"officials/{oid}.html", ctx["official"]["name"], **ctx)
    for m in facts["meetings"]:
        ctx = views.meeting(m["id"], ix)
        render("meeting.html.j2", f"meetings/{m['id']}.html", f"Meeting {m['date']}", m=ctx, **ctx)
    for year in ix.item_years():
        render("items_year.html.j2", f"items/{year}.html", f"Items {year}", **views.items_year(year, ix))
    for c in cixs:  # council pages (council.py): home, one page per member, per year of meetings, per year of items
        cs = council_mod.site_for(site, c)
        render("council_home.html.j2", c.home_href(), c.page_name(), cs, council=c.nav_label,
               council_href=c.home_href(), **council_mod.home(c))
        for o in c.facts["officials"]:
            render("official.html.j2", c.official_href(o["id"]), o["name"], cs, **council_mod.member(o["id"], c))
        for y in c.meeting_years():
            render("council_meetings_year.html.j2", f"{c.slug}/meetings/{y}.html", c.page_name(f"Meetings {y}"), cs,
                   council=c.nav_label, council_href=c.home_href(), **council_mod.meetings_year(y, c))
        for y in c.item_years():
            render("council_items_year.html.j2", f"{c.slug}/items/{y}.html", c.page_name(f"Items {y}"), cs,
                   council=c.nav_label, council_href=c.home_href(), **council_mod.items_year(y, c))
    render("about.html.j2", "about.html", "About", **views.about(ix), glance=views.record_glance(ix))
    render("changes.html.j2", "changes.html", "Changes", **views.changes(read_changes(changes_path)))
    if internal:
        render("review.html.j2", "review.html", "Review (internal)",
               **views.review(ix, read_report(report_path)))

    shutil.copytree(config.STATIC_DIR, out / "static")
    # A script, not a JSON file, so search also works when the site is opened from files or a zip (no fetch).
    index_js = "window.SEARCH_INDEX = " + json.dumps(views.search_index(ix, fx, cixs), separators=(",", ":"),
                                                     ensure_ascii=True) + ";\n"
    (out / "static" / "search-index.js").write_text(index_js, encoding="utf-8")
    manifest = write_publish_manifest(out)
    return {"pages": written, "files": len(manifest) + 1}
