"""Render the static site from a facts file. Entry point: `build(facts_path, out_dir, internal=False)`."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

import jinja2
from jsonschema import Draft202012Validator, FormatChecker

from . import config, views


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


def load_facts(facts_path: Path) -> dict:
    facts = json.loads(Path(facts_path).read_text(encoding="utf-8"))
    lines = _schema_errors(_validator(config.SCHEMA_PATH), facts)
    if lines:
        raise BuildError(f"{facts_path} does not match schema/facts.schema.json:\n" + "\n".join(lines))
    check_references(facts)
    return facts


def make_env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(config.TEMPLATE_DIR)),
        autoescape=jinja2.select_autoescape(["html", "j2"]),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


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


def _clean(out: Path) -> None:
    """Remove what this generator owns. `data/` belongs to the collector's export and is left alone."""
    out.mkdir(parents=True, exist_ok=True)
    for p in out.glob("*.html"):
        p.unlink()
    for d in ("officials", "meetings", "items", "static"):
        shutil.rmtree(out / d, ignore_errors=True)


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


def build(facts_path, out_dir, internal: bool = False, changes_path=None, report_path=None) -> dict:
    facts_path, out = Path(facts_path), Path(out_dir)
    facts = load_facts(facts_path)
    ix = views.Index(facts)
    env = make_env()

    if config.OPERATOR_NAME == config.OPERATOR_PLACEHOLDER:
        print(f"WARNING: OPERATOR_NAME in sitegen/config.py is still the placeholder "
              f"{config.OPERATOR_PLACEHOLDER!r}. A public build must not use it.", file=sys.stderr)

    if changes_path is None:
        changes_path = facts_path.parent / "changes.jsonl"
    if report_path is None:
        report_path = out.parent / "report.json"

    _clean(out)
    site = views.site_context(ix)
    site["internal"] = internal
    written: list[str] = []

    def render(template: str, rel: str, page_name: str, **ctx) -> None:
        depth = rel.count("/")
        html = env.get_template(template).render(
            site=site, root="../" * depth, page_name=page_name, **ctx)
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        written.append(rel)

    render("index.html.j2", "index.html", "Officials", **views.officials_index(ix))
    for o in facts["officials"]:
        ctx = views.official(o["id"], ix)
        render("official.html.j2", f"officials/{o['id']}.html", o["name"], **ctx)
    for m in facts["meetings"]:
        ctx = views.meeting(m["id"], ix)
        render("meeting.html.j2", f"meetings/{m['id']}.html", f"Meeting {m['date']}", **ctx)
    for year in ix.item_years():
        render("items_year.html.j2", f"items/{year}.html", f"Items {year}", **views.items_year(year, ix))
    render("about.html.j2", "about.html", "About", **views.about(ix))
    render("changes.html.j2", "changes.html", "Changes", **views.changes(read_changes(changes_path)))
    if internal:
        render("review.html.j2", "review.html", "Review (internal)",
               **views.review(ix, read_report(report_path)))

    shutil.copytree(config.STATIC_DIR, out / "static")
    manifest = write_publish_manifest(out)
    return {"pages": written, "files": len(manifest) + 1}
