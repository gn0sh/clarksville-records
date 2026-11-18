"""The reviewed lists under config/ that let a run do what its guards would otherwise refuse (I-in, I-pub; ADR 0011
decisions 2a and 4). Each is a YAML list, changed only by a person's reviewed pull request:

- config/fin-books-accepted.yml (schema/fin-books-accepted.schema.json): city budget book readings a person accepted;
  collector/fin_books.py worse_than_committed reads it. Key: (locality, book_id, source_sha256).
- config/published-fact-changes.yml (schema/published-fact-changes.schema.json): published facts a deploy may change
  or remove; the content tripwire (task B4) reads it. Key: (path, fact_id); each entry pins one exact change
  (path, fact_id, change, value_sha256), so it is spent once the live site shows that value.

load() applies the schema with the date format checked (listed_on must be a real day, not only YYYY-MM-DD) and refuses
a key listed twice. Any problem raises ReviewedListError naming the file and the entry index, never a value, so a
caller fails closed (the guard holds).
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
FIN_BOOKS_ACCEPTED = "fin-books-accepted"
PUBLISHED_FACT_CHANGES = "published-fact-changes"
KEYS = {FIN_BOOKS_ACCEPTED: ("locality", "book_id", "source_sha256"), PUBLISHED_FACT_CHANGES: ("path", "fact_id")}


class ReviewedListError(ValueError):
    pass


def validator(name: str) -> Draft202012Validator:
    """The list's schema (always this checkout's schema/), with the format checker on."""
    schema = json.loads((ROOT / "schema" / f"{name}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def problems(name: str, data) -> list[str]:
    """Why `data` is not a valid list `name` (schema with formats, then duplicate keys); [] when it is."""
    out = [f"entry {'/'.join(str(x) for x in e.absolute_path) or '(list)'}: {e.validator} check failed"
           for e in sorted(validator(name).iter_errors(data), key=lambda e: [str(x) for x in e.absolute_path])]
    if out or not isinstance(data, list):
        return out
    seen: dict[tuple, int] = {}
    for i, entry in enumerate(data):
        key = tuple(entry[k] for k in KEYS[name])
        if key in seen:
            out.append(f"entry {i}: lists the same {', '.join(KEYS[name])} as entry {seen[key]}")
        else:
            seen[key] = i
    return out


def load(name: str, root: Path = ROOT, path: Path | None = None) -> list[dict]:
    """The checked entries of config/<name>.yml. A missing file is an empty list (nothing accepted, the guard holds);
    an unreadable or invalid one raises ReviewedListError."""
    p = Path(path) if path else Path(root) / "config" / f"{name}.yml"
    if not p.is_file():
        return []
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ReviewedListError(f"{p.name}: not readable YAML ({type(exc).__name__})") from exc
    found = problems(name, data)
    if found:
        raise ReviewedListError(f"{p.name}: " + "; ".join(found[:10]))
    return data
