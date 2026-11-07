"""Render the static site from a facts file. Entry point: `build(facts_path, out_dir, internal=False)`."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import jinja2
from jsonschema import Draft202012Validator

from . import config, views


class BuildError(Exception):
    pass


def load_facts(facts_path: Path) -> dict:
    facts = json.loads(Path(facts_path).read_text(encoding="utf-8"))
    schema = json.loads(config.SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(facts), key=lambda e: list(e.absolute_path))
    if errors:
        lines = [f"  {'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}" for e in errors[:20]]
        raise BuildError(f"{facts_path} does not match schema/facts.schema.json:\n" + "\n".join(lines))
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
    entries = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise BuildError(f"{path} line {n}: not valid JSON ({exc})") from exc
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
