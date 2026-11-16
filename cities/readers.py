"""Portal readers by portal type: which collector module reads a city's source, and which keys its config file needs.

A city is config only when every one of its sources names a portal type here that is built and shared. `local`
readers hold one locality's specifics in code (Clarksville and Montgomery County today) and can't serve another city
yet. A portal listed as not built makes validation say so plainly instead of failing later in a run."""
from __future__ import annotations

import importlib
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Reader:
    label: str
    module: str | None          # collector module that reads it (None: not built yet)
    loader: str | None          # its config loader, called with the config path (None: no config file)
    required: tuple = ()        # top-level keys its config file must set
    shared: bool = True         # False: holds one locality's specifics in code (not reusable by another city yet)
    note: str = ""
    host_keys: tuple = ()       # config keys holding a host the reader asks
    url_keys: tuple = ()        # config keys holding a URL the reader asks ({host} is the first host_keys value)
    link_keys: tuple = ()       # config keys listing hosts the site only links to (never asked; never a denied host)

    @property
    def built(self) -> bool:
        return self.module is not None

    def load(self, path: Path):
        """Run the reader's own loader on a config file (its checks are stricter than the key list)."""
        if not (self.module and self.loader):
            return None
        return getattr(importlib.import_module(self.module), self.loader)(path)

    def hosts(self, path: Path) -> tuple:
        """Hosts the reader will ask for this config, read from the file as written (a draft that doesn't load yet
        still names its hosts). UNVERIFIED values name no host."""
        if self.module == "collector.legistar":
            from collector import legistar
            return legistar.allowed_hosts(legistar.load_config(path))
        data = _data(path)
        hosts = [str(data[k]).strip().lower() for k in self.host_keys if _real(data.get(k))]
        base = hosts[0] if hosts else None
        for k in self.url_keys:
            url = data.get(k)
            if not _real(url) or ("{host}" in url and not base):
                continue
            h = urllib.parse.urlsplit(url.replace("{host}", base or "")).hostname
            if h:
                hosts.append(h.lower())
        return tuple(dict.fromkeys(hosts))

    def link_hosts(self, path: Path) -> tuple:
        data = _data(path)
        return tuple(str(h).strip().lower() for k in self.link_keys if isinstance(data.get(k), list)
                     for h in data[k] if _real(h))


def _data(path: Path) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _real(value) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not value.strip().upper().startswith("UNVERIFIED")


READERS: dict[str, Reader] = {
    "agenda_center": Reader(
        "CivicPlus Agenda Center", "collector.agenda_center", "load_config",
        ("locality", "body", "official_title", "host", "category_id", "category_name", "search_url", "years",
         "kind_rules", "vote_labels"), host_keys=("host",), url_keys=("search_url",)),
    "civicclerk": Reader(
        "CivicClerk", "collector.civicclerk", "load_config",
        ("locality", "api_host", "category_name", "from_date", "events_url", "file_url", "agenda_types",
         "minutes_types", "video_hosts"), host_keys=("api_host",), url_keys=("events_url", "file_url"),
        link_keys=("video_hosts",)),
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
