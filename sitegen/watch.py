"""Official meeting video: one plain "Watch" link per body (Brian, 2026-11-11).

config/site.yml `video:` holds, per body key (config `county_key`, a council's and the RPC's `body_key`), the page
where that body itself posts its meeting video, and the words naming where the link goes. It is a link only: nothing
is ever fetched from it (collector/fetch.py does not know it). A body with no entry has no Watch link anywhere; no link
is ever guessed. A meeting whose own recording the facts carry (a council's `video_url`, kept only when
transcripts.video_ok allows it: https on config.VIDEO_HOSTS) links that recording instead of the body's page.

Where it shows: each day card (sitegen/days.py), each body's home page and the county meeting pages (build.py), and
each morning-note entry about a meeting (sitegen/morning.py `watch`, the preview page). qa/site_checks.py accepts a
body link by its exact config URL (data-ext="watch") and a recording as a meeting's video_url (data-ext="video").
"""
from __future__ import annotations

from . import config


def entries(cfg: dict | None = None) -> dict[str, dict]:
    """{body key: {url, host}} of the `video:` block, the entries that may become a link only (https, a host label)."""
    block = (config.SITE if cfg is None else cfg).get("video") or {}
    if not isinstance(block, dict):
        return {}
    return {k: v for k, v in block.items() if isinstance(v, dict) and config.https_link(v.get("url"))
            and isinstance(v.get("host"), str) and v["host"].strip()}


def problems(cfg: dict) -> list[str]:
    """Build refusals: every `video:` entry is {url: an https link, host: words}; the two labels are set with it."""
    block = cfg.get("video")
    if block is None:
        return []
    if not isinstance(block, dict):
        return ["video must be a mapping of body key to {url, host}"]
    out = [f"video.{k} must be {{url: an https link, host: words}}, got {v!r}" for k, v in block.items()
           if k not in entries(cfg)]
    if block:
        for k in ("video_link", "video_label", "video_recording"):
            if not isinstance(cfg.get(k), str) or not cfg[k].strip():
                out.append(f"{k} must be set when video is")
        if "{host}" not in str(cfg.get("video_label") or ""):
            out.append("video_label must contain {host}")
    return out


def body(key: str | None, cfg: dict | None = None) -> dict | None:
    """The Watch link of body `key`: {url, link, label, ext: "watch"}, or None when the body has no entry."""
    cfg = config.SITE if cfg is None else cfg
    v = entries(cfg).get(key or "")
    if v is None:
        return None
    return {"url": v["url"], "link": cfg["video_link"], "label": cfg["video_label"].format(host=v["host"].strip()),
            "ext": "watch"}


def meeting(key: str | None, video_url=None, cfg: dict | None = None) -> dict | None:
    """A meeting's Watch link: its own recording when the facts carry one video_ok allows, else the body's page."""
    from .transcripts import video_ok   # transcripts imports views, which may import this module
    cfg = config.SITE if cfg is None else cfg
    b = body(key, cfg)
    if b is not None and video_ok(video_url):
        return {**b, "url": video_url, "label": cfg["video_recording"], "ext": "video"}
    return b
