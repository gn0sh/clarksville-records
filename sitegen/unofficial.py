"""The "independent, unofficial" wording, in one place (config/site.yml `unofficial:`). Every surface (page footer,
header tag, home and About, feeds, morning note, export README, <meta>/Open Graph, <title>) takes its text from
here, and qa/site_checks.py `unofficial/notice-on-every-page` looks for the same notice text in the built files."""
from . import config


def _join(names: list[str]) -> str:
    return ", ".join(names[:-1]) + ", or " + names[-1] if len(names) > 2 else " or ".join(names)


def load(cfg: dict | None = None) -> dict:
    """{tag, notice, correction_label, differ, not_advice, email_line, bodies}."""
    cfg = config.SITE if cfg is None else cfg
    u = cfg["unofficial"]
    notice = u["notice"].format(site_name=cfg["site_name"], operator=cfg["operator"],
                                bodies=_join([b["name"] for b in u["bodies"]]))
    return {"tag": u["tag"], "notice": notice, "correction_label": u["correction_label"], "differ": u["differ"],
            "not_advice": u["not_advice"], "email_line": u["email_line"], "bodies": u["bodies"]}


def problems(cfg: dict | None = None) -> list[str]:
    """Config mistakes the build refuses: the block, its keys, and an https URL for each of the four bodies."""
    cfg = config.SITE if cfg is None else cfg
    u = cfg.get("unofficial")
    if not isinstance(u, dict):
        return ["unofficial: block is missing"]
    bad = [f"unofficial.{k} is missing" for k in ("tag", "notice", "correction_label", "differ", "not_advice",
                                                  "email_line", "bodies") if not u.get(k)]
    for b in u.get("bodies") or []:
        if not (b.get("name") and b.get("label") and str(b.get("url", "")).startswith("https://")):
            bad.append(f"unofficial.bodies entry {b!r} needs name, label and an https url")
    if len(u.get("bodies") or []) < 4:
        bad.append("unofficial.bodies must name the City, the County, CMCSS and the Regional Planning Commission")
    return bad


def export_readme(cfg: dict | None = None) -> str:
    """data/README.txt, written beside the export's files."""
    t = load(cfg)
    links = "\n".join(f"  {b['label']}: {b['url']}" for b in t["bodies"])
    return (f"{t['notice']}\n\n{t['differ']} {t['not_advice']}\n\nThe official sites:\n{links}\n\n"
            "These files carry the facts the pages show, each with the source document it came from.\n")
