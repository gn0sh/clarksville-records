"""The import layering of `cities` and `collector` (ADR 0012 decision 7; the cycle ADR 0007 names).

- A `cities` module imports from `collector` only `hosts` and `windows` at module level. Imports inside a function
  (cities/readers.py's lazy reader loads) are allowed.
- A `collector` module imports `cities` only inside a CLI entry function (`main`, `cmd_*`) that resolves `--city`.
- collector/hosts.py and collector/windows.py are leaves: no `cities` or `collector` import at all.
And both packages import cleanly in a fresh process in either order. No network.
"""
import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ("cities", "collector")
LEAVES = ("hosts", "windows")


def is_entry(func: str | None) -> bool:
    """A CLI entry function: `main` or `cmd_*` (where `--city` is resolved)."""
    return func is not None and (func == "main" or func.startswith("cmd_"))


def imports(tree: ast.Module, package: str) -> list[tuple[str, int, str | None]]:
    """(absolute module name, line, enclosing top function or None) for every import. A relative import resolves
    against `package` (the modules checked sit at the package's top level). `from <package> import x` yields
    `<package>.x`, since x may be a submodule."""
    out = []

    def visit(node, func):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, func or child.name)
                continue
            if isinstance(child, ast.Import):
                out.extend((a.name, child.lineno, func) for a in child.names)
            elif isinstance(child, ast.ImportFrom):
                if child.level > 1:
                    out.append(("..", child.lineno, func))
                else:
                    mod = (f"{package}.{child.module}" if child.module else package) if child.level else child.module
                    if mod in PACKAGES:
                        out.extend((f"{mod}.{a.name}", child.lineno, func) for a in child.names)
                    else:
                        out.append((mod, child.lineno, func))
            visit(child, func)

    visit(tree, None)
    return out


def layer_errors(path: Path, package: str) -> list[str]:
    errors = []
    for mod, line, func in imports(ast.parse(path.read_text(encoding="utf-8"), str(path)), package):
        where = f"{package}/{path.name}:{line} imports {mod}"
        parts = mod.split(".")
        if mod == "..":
            errors.append(f"{where}: no imports above the package")
        elif package == "collector" and path.stem in LEAVES:
            if parts[0] in PACKAGES:
                errors.append(f"{where}: collector/{path.stem}.py is a leaf module")
        elif package == "cities" and parts[0] == "collector" and func is None:
            if len(parts) < 2 or parts[1] not in LEAVES:
                errors.append(f"{where}: a cities module imports only collector.hosts/windows at module level")
        elif package == "collector" and parts[0] == "cities" and not is_entry(func):
            errors.append(f"{where}: a collector module imports cities only inside a CLI entry function")
    return errors


@pytest.mark.parametrize("path", sorted(ROOT.glob("cities/*.py")) + sorted(ROOT.glob("collector/*.py")),
                         ids=lambda p: f"{p.parent.name}/{p.name}")
def test_import_layering(path):
    assert layer_errors(path, path.parent.name) == []


def test_the_rule_catches_each_kind_of_break(tmp_path):
    def errs(package, name, src):
        (tmp_path / package).mkdir(exist_ok=True)
        p = tmp_path / package / name
        p.write_text(src)
        return layer_errors(p, package)

    assert errs("cities", "a.py", "from collector.fetch import DENIED_HOSTS\n")
    assert errs("cities", "b.py", "from collector import fetch\n")
    assert errs("cities", "c.py", "import collector.legistar\n")
    assert errs("cities", "d.py", "import collector\n")
    assert errs("cities", "e.py", "try:\n    from collector import fetch\nexcept ImportError:\n    pass\n")
    assert errs("cities", "f.py", "class C:\n    from collector import fetch\n")
    assert not errs("cities", "g.py", "from collector.hosts import host_matches\nfrom collector import windows\n")
    assert not errs("cities", "h.py", "def load():\n    from collector import legistar\n")
    assert errs("collector", "i.py", "from cities import registry\n")
    assert errs("collector", "j.py", "def helper():\n    import cities.registry\n")
    assert errs("collector", "k.py", "def main():\n    pass\n\n\ndef other():\n    from cities.plan import Window\n")
    assert not errs("collector", "l.py", "def main(argv=None):\n    from cities import registry\n")
    assert not errs("collector", "m.py", "def cmd_city(args):\n    def inner():\n        from cities import registry\n")
    assert errs("collector", "hosts.py", "from . import limits\n")
    assert errs("collector", "windows.py", "def f():\n    from cities.errors import CityError\n")
    assert not errs("collector", "n.py", "from .hosts import host_matches\nfrom . import windows\n")


@pytest.mark.parametrize("order", [("cities.registry", "collector.fetch"), ("collector.fetch", "cities.registry"),
                                   ("cities.plan", "collector.legistar"), ("collector.legistar", "cities.plan"),
                                   ("cities", "collector"), ("collector", "cities")],
                         ids=lambda o: " then ".join(o))
def test_fresh_process_imports_in_either_order(order):
    code = "; ".join(f"import {m}" for m in order)
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


def test_the_moved_names_are_the_same_objects():
    from cities import plan, registry
    from collector import fetch, hosts, legistar, windows
    assert fetch.DENIED_HOSTS is hosts.DENIED_HOSTS == ("cityofclarksville.com", "dev2.montgomerytn.gov")
    assert fetch.host_matches is hosts.host_matches is registry.host_matches
    assert fetch.plain_hostname is hosts.plain_hostname and fetch.PLAIN_HOST is hosts.PLAIN_HOST
    assert legistar.Window is plan.Window is windows.Window
    assert legistar.launch_windows is windows.launch_windows
    assert issubclass(windows.WindowError, ValueError) and plan.WindowError is windows.WindowError
