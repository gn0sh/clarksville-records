"""Cookie-free visitor counting (ADR 0008, docs/ops/analytics.md): config/site.yml `analytics`.

Off while `code` is empty (the default): no page loads static/count.js and views.csp keeps connect-src 'none'. On,
every page of a `pages` build with real data loads static/count.js with the counter's address in its
data-goatcounter attribute, and the CSP's connect-src names that one origin. The provider is GoatCounter only; the
script is our own (static/count.js), so exactly the fields ADR 0008 lists are sent and nothing a visitor types.
"""
from __future__ import annotations

import re

from . import config

PROVIDERS = ("goatcounter",)
CODE = re.compile(r"[a-z0-9][a-z0-9-]{1,48}[a-z0-9]")
PRIVACY_URL = "https://www.goatcounter.com/help/privacy"
PROVIDER_LABEL = {"goatcounter": "GoatCounter"}

# Set by the build for the pages it renders (sitegen/build.py), read by views.csp: None while counting is off.
_ORIGIN: str | None = None


# The disclosure, About (neutrality rule 6) and Method (privacy) alike, only while counting is on. Plain facts: what is
# sent, what never is, who receives it. {label} is the provider's name.
COUNTED = ("Visits are counted without cookies by {label}: the page address without anything after the \"?\", the "
           "site that linked here (not its page), the screen size, and two events, a Buy Me a Coffee link clicked and "
           "a search run. The words of a search and what you type in the address box are never sent. Browsers that "
           "send Do Not Track or Global Privacy Control are not counted.")


def problems(cfg: dict | None = None) -> list[str]:
    """What is wrong with config/site.yml `analytics` (the build refuses to run on any)."""
    cfg = config.SITE if cfg is None else cfg
    a = cfg.get("analytics")
    if a is None:
        return []
    if not isinstance(a, dict):
        return ["analytics must be a mapping {provider, code}"]
    out = []
    if set(a) - {"provider", "code"}:
        out.append(f"analytics: unknown keys {sorted(set(a) - {'provider', 'code'})}")
    if a.get("provider") not in PROVIDERS:
        out.append(f"analytics.provider must be one of {list(PROVIDERS)}, got {a.get('provider')!r}")
    code = a.get("code")
    if code is None:
        code = ""
    if not isinstance(code, str) or (code and not CODE.fullmatch(code)):
        out.append(f"analytics.code must be empty or a GoatCounter site code (a-z, 0-9, -), got {code!r}")
    return out


def settings(cfg: dict | None = None, target: str = "pages", fixture: bool = False) -> dict | None:
    """The counter for this build, or None (code empty, a preview or fixture build). Call problems() first."""
    cfg = config.SITE if cfg is None else cfg
    a = cfg.get("analytics") or {}
    code = a.get("code") or ""
    if not code or target != "pages" or fixture or problems(cfg):
        return None
    origin = f"https://{code}.goatcounter.com"
    label = PROVIDER_LABEL[a["provider"]]
    return {"provider": a["provider"], "label": label, "code": code, "origin": origin,
            "endpoint": origin + "/count", "privacy_url": PRIVACY_URL, "counted": COUNTED.format(label=label)}


def activate(s: dict | None) -> None:
    """The build's counter, for views.csp (None: off)."""
    global _ORIGIN
    _ORIGIN = s["origin"] if s else None


def origin() -> str | None:
    return _ORIGIN
