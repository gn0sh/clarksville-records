"""Content-addressed document store and data/manifest.json (architecture "Document store and manifest").

- Bytes live at <store>/<sha256>.pdf (default data/store/, overridable by RECORDS_STORE). Not committed.
- data/manifest.json (committed) has one entry per (url, sha256): url, sha256, bytes, content_type, kind,
  meeting_date, label, first_fetched_at, etag, last_modified.
- An entry keeps its first_fetched_at while its hash is unchanged (the "fetch date" shown, N4). New bytes for a
  known URL become a new entry; the old one stays so old facts keep their citation, and the change is logged in
  data/changes.jsonl. "Last checked" times go only to the run log, so a run with nothing new leaves the manifest
  byte-identical (AC4.5).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .fetch import FetchFailed

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "manifest.json"
CHANGES = ROOT / "data" / "changes.jsonl"
FIELDS = ("url", "sha256", "bytes", "content_type", "kind", "meeting_date", "label", "first_fetched_at",
          "etag", "last_modified")


def store_dir() -> Path:
    return Path(os.environ.get("RECORDS_STORE", ROOT / "data" / "store"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm_entry(e: dict) -> dict:
    """Accept M0 spike entries (fetched_at, file) and return the M1 shape."""
    out = {k: e.get(k) for k in FIELDS}
    out["first_fetched_at"] = e.get("first_fetched_at") or e.get("fetched_at")
    out["kind"] = e.get("kind") or "minutes"
    if e.get("superseded_by"):
        out["superseded_by"] = e["superseded_by"]      # only on replaced entries, so others stay byte-identical
    return out


class Store:
    def __init__(self, manifest_path: Path = MANIFEST, root: Path | None = None,
                 changes_path: Path | None = None, now=_now):
        self.manifest_path = Path(manifest_path)
        self.root = Path(root) if root else store_dir()
        self.changes_path = Path(changes_path) if changes_path else self.manifest_path.parent / "changes.jsonl"
        self.now = now
        raw = json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else []
        self.entries = [_norm_entry(e) for e in raw]

    # ------------------------------------------------------------ lookups
    def path_for(self, sha256: str) -> Path:
        return self.root / f"{sha256}.pdf"

    def has_bytes(self, sha256: str) -> bool:
        return self.path_for(sha256).exists()

    def latest(self, url: str) -> dict | None:
        cands = [e for e in self.entries if e["url"] == url]
        return max(cands, key=lambda e: e["first_fetched_at"] or "") if cands else None

    def current(self) -> list[dict]:
        """The latest entry per URL: what a build reads. Older entries stay in the manifest for citations only
        (marked superseded_by); their bytes are not needed, so a missing old blob never fails a run."""
        return [e for e in self.entries if self.latest(e["url"]) is e]

    def superseded(self) -> list[dict]:
        return [e for e in self.entries if self.latest(e["url"]) is not e]

    # ------------------------------------------------------------ writes
    def put(self, url: str, body: bytes, headers: dict | None = None, meta: dict | None = None) -> tuple[dict, str]:
        """Store bytes for url. Returns (entry, status) with status 'unchanged' | 'new' | 'changed'."""
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        meta = meta or {}
        digest = hashlib.sha256(body).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        p = self.path_for(digest)
        if not p.exists():
            tmp = p.with_suffix(".part")
            tmp.write_bytes(body)
            tmp.replace(p)
        same = next((e for e in self.entries if e["url"] == url and e["sha256"] == digest), None)
        if same:
            return same, "unchanged"
        prev = self.latest(url)
        entry = {
            "url": url, "sha256": digest, "bytes": len(body),
            "content_type": headers.get("content-type", ""),
            "kind": meta.get("kind", "minutes"), "meeting_date": meta.get("meeting_date"),
            "label": meta.get("label"), "first_fetched_at": self.now(),
            "etag": headers.get("etag"), "last_modified": headers.get("last-modified"),
        }
        self.entries.append(entry)
        if prev:
            prev["superseded_by"] = digest
            self._log_change({"date": entry["first_fetched_at"][:10], "fact_id": f"src-{prev['sha256'][:12]}",
                              "field": "sha256", "old": prev["sha256"], "new": digest,
                              "note": "the county replaced this document; the old version stays as its own source",
                              "source_url": url, "page": None})
        return entry, "changed" if prev else "new"

    def _log_change(self, rec: dict) -> None:
        self.changes_path.parent.mkdir(parents=True, exist_ok=True)
        with self.changes_path.open("a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")

    def save(self) -> None:
        """Write the manifest deterministically (sorted, stable); unchanged content gives identical bytes."""
        ents = sorted(self.entries, key=lambda e: (e["meeting_date"] or "", e["url"], e["first_fetched_at"] or ""))
        text = json.dumps(ents, indent=2, sort_keys=True) + "\n"
        if not self.manifest_path.exists() or self.manifest_path.read_text() != text:
            self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
            self.manifest_path.write_text(text)


def fetch_into_store(fetcher, store: Store, url: str, meta: dict | None = None) -> tuple[dict, str]:
    """Return the stored entry for url, downloading only when its bytes are not in the store."""
    known = store.latest(url)
    if known and store.has_bytes(known["sha256"]):
        changed = False
        for k in ("kind", "meeting_date", "label"):        # discovery metadata may be filled in later
            if meta and meta.get(k) and known.get(k) != meta[k]:
                known[k] = meta[k]
                changed = True
        return known, "cached-meta" if changed else "cached"
    status, body, headers = fetcher.get(url)
    if status != 200:
        raise FetchFailed(f"HTTP {status} for {url}")
    if body[:4] != b"%PDF":
        raise FetchFailed(f"not a PDF: {url} ({headers.get('Content-Type')})")
    return store.put(url, body, headers, meta)
