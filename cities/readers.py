"""Portal readers by portal type: which collector module reads a city's source, and which keys its config file needs.

A city is config only when every one of its sources names a portal type here that is built and shared. `local`
readers hold one locality's specifics in code (Clarksville and Montgomery County today) and can't serve another city
yet. A portal listed as not built makes validation say so plainly instead of failing later in a run."""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Reader:
    label: str
    module: str | None          # collector module that reads it (None: not built yet)
    loader: str | None          # its config loader, called with the config path (None: no config file)
    required: tuple = ()        # top-level keys its config file must set
    shared: bool = True         # False: holds one locality's specifics in code (not reusable by another city yet)
    note: str = ""

    @property
    def built(self) -> bool:
        return self.module is not None

    def load(self, path: Path):
        """Run the reader's own loader on a config file (its checks are stricter than the key list)."""
        if not (self.module and self.loader):
            return None
        return getattr(importlib.import_module(self.module), self.loader)(path)

    def hosts(self, path: Path) -> tuple:
        """Hosts the reader will ask for this config, when the reader can say (legistar.allowed_hosts)."""
        if self.module != "collector.legistar":
            return ()
        from collector import legistar
        return legistar.allowed_hosts(legistar.load_config(path))


READERS: dict[str, Reader] = {
    "agenda_center": Reader(
        "CivicPlus Agenda Center", "collector.agenda_center", "load_config",
        ("locality", "body", "official_title", "host", "category_id", "category_name", "search_url", "years",
         "kind_rules", "vote_labels")),
    "civicclerk": Reader(
        "CivicClerk", "collector.civicclerk", "load_config",
        ("locality", "api_host", "category_name", "from_date", "events_url", "file_url", "agenda_types",
         "minutes_types", "video_hosts")),
    "legistar": Reader(
        "Legistar Web API", "collector.legistar", "load_config",
        ("city", "client", "body_name", "official_title", "launch_days", "earliest", "vote_values", "kind_rules"),
        note="listing and vote rows only; not wired into a daily run yet"),
    "municode": Reader("Municode Meetings", None, None, note="wanted for Columbus GA and Fort Collins"),
    # Clarksville / Montgomery County only: their specifics live in code or in one locality's file.
    "county_minutes": Reader("Montgomery County Commission minutes", "collector.discover", None, shared=False,
                             note="body and years in collector/config.py"),
    "county_agendas": Reader("Montgomery County Commission agendas", "collector.county_agenda", None, shared=False,
                             note="index URL in collector/county_agenda.py"),
    "rpc": Reader("Clarksville-Montgomery County Regional Planning Commission", "collector.rpc", "load_config",
                  ("locality", "body", "listing_url", "facts", "fetch_hosts"), shared=False),
    "finance": Reader("Montgomery County purchasing archive and budget", "collector.fin_config", "load",
                      ("archive_url", "archive_header", "bonfire_hosts"), shared=False),
    "zoning": Reader("Zoning case rules", "collector.zoning", "load_rules", shared=False),
}


def reader(portal: str) -> Reader | None:
    return READERS.get(portal)
