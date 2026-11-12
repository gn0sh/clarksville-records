"""Name normaliser and resolver (architecture "Names and merge rules"; spec G2).

data/names.yml is the roster: one entry per official with id, name, surname, given, title, sources and aliases
(each alias with its reason and an example source page). The rules below apply identically to every official:

1. Normalise: NFKC, trim, drop leading titles (Commissioner, Comm., Chairman, Chairwoman, Mayor, Mr., Mrs., Ms.,
   Dr.), drop "." and ",", collapse spaces, casefold.
2. Exact match of the normalised string against each official's normalised name and aliases.
3. Surname-only match (optionally with a first initial, "J. Smith"), only against that meeting's roster and only
   when exactly one official on it has that surname (and initial).
4. Anything else is unmatched: the fact fails its name check and is held back. No fuzzy auto-merge, ever.
   Edit-distance suggestions go to build/name-candidates.json; a person adds an alias by PR.

Within one roll call the vote table's cells are paired one-to-one with that meeting's attendance header names by
the M0 parser (collector/parse.py assign_names): it is a P2 check, and a roll call whose cells do not pair cleanly,
or whose counts disagree with the stated tally, is held back. Only header names and motion names go through the
rules above.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
NAMES = ROOT / "data" / "names.yml"
TITLES = ("commissioner", "comm", "chairman", "chairwoman", "mayor", "mr", "mrs", "ms", "dr")


class RosterError(Exception):
    pass


def normalise(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").strip()
    s = s.replace(".", " ").replace(",", " ")
    toks = s.split()
    while toks and toks[0].casefold() in TITLES:
        toks.pop(0)
    return " ".join(toks).casefold()


def load_roster(path: Path = NAMES) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    officials = data.get("officials") or []
    for o in officials:
        for k in ("id", "name", "surname", "given"):
            if not o.get(k):
                raise RosterError(f"names.yml: official missing {k}: {o}")
        if not re.fullmatch(r"[a-z0-9-]+", o["id"]):
            raise RosterError(f"names.yml: bad id {o['id']!r}")
        o.setdefault("title", "County Commissioner")
        o["aliases"] = [a if isinstance(a, dict) else {"alias": a} for a in (o.get("aliases") or [])]
    return officials


class Resolver:
    def __init__(self, officials: list[dict]):
        self.officials = {o["id"]: o for o in officials}
        self.exact: dict[str, str] = {}
        for o in officials:
            for s in [o["name"]] + [a["alias"] for a in o["aliases"]]:
                k = normalise(s)
                if k in self.exact and self.exact[k] != o["id"]:
                    raise RosterError(f"names.yml: {s!r} normalises to {k!r}, already used by {self.exact[k]}")
                self.exact[k] = o["id"]
        self.surnames = {o["id"]: normalise(o["surname"]) for o in officials}
        self.givens = {o["id"]: normalise(o["given"]) for o in officials}

    def exact_match(self, raw: str) -> str | None:
        """Rules 1-2."""
        return self.exact.get(normalise(raw))

    def resolve(self, raw: str, roster_ids=None) -> tuple[str | None, str]:
        """-> (official_id or None, rule). roster_ids enables rule 3 (motion names at one meeting)."""
        oid = self.exact_match(raw)
        if oid:
            return oid, "exact"
        if roster_ids:
            toks = normalise(raw).split()
            if toks:
                sur = toks[-1]
                initial = toks[0][0] if len(toks) == 2 and len(toks[0]) == 1 else None
                if len(toks) == 1 or initial:
                    cands = [i for i in sorted(set(roster_ids)) if self.surnames.get(i) == sur
                             and (initial is None or self.givens.get(i, "").startswith(initial))]
                    if len(cands) == 1:
                        return cands[0], "surname" if initial is None else "initial+surname"
        return None, "unmatched"

    def suggestions(self, raw: str, n: int = 3) -> list[dict]:
        k = normalise(raw)
        scored = sorted(((SequenceMatcher(None, k, normalise(o["name"])).ratio(), o["id"]) for o in
                         self.officials.values()), reverse=True)[:n]
        return [{"official_id": i, "score": round(s, 3)} for s, i in scored]


def public_officials(officials: list[dict]) -> list[dict]:
    """Facts-file shape: {id, name, surname, given, title, aliases[]}, sorted by id."""
    return sorted(({"id": o["id"], "name": o["name"], "surname": o["surname"], "given": o["given"],
                    "title": o.get("title", "County Commissioner"),
                    "aliases": sorted({a["alias"] for a in o["aliases"]})} for o in officials),
                  key=lambda o: o["id"])
