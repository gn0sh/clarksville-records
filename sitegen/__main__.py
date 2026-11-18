"""python -m sitegen [--city <slug>] --facts <facts.json> --out build/site [--internal] [--no-geocoder]
    [--finance <finance.json>] [--target preview|pages]

--city: the city whose settings the build reads (config/cities/<slug>/, ADR 0012 decision 1; default clarksville-tn,
or DAYLIGHT_CITY). It is read before sitegen.config is imported, because the settings are read once, at import; a
--city that differs from DAYLIGHT_CITY, or from the city this process already loaded, exits 2. For a new city,
--facts defaults to data/localities/<slug>/facts.json and --out to build/<slug>/site. Clarksville's own command line
(no --city, --facts and --out given) is unchanged.

--no-geocoder: no "Find your district" address box on the landing (and no geocoder in the page's CSP), only the plain
"Not sure of your district?" lookup line. Use it for the claude.ai preview, where the box cannot reach the geocoder."""
import argparse
import os
import sys

CITY_ENV = "DAYLIGHT_CITY"


def _pick_city(argv: list[str]) -> tuple[str | None, str | None]:
    """(the --city slug or None, an error or None), before sitegen.config is imported."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--city")
    known, _ = pre.parse_known_args(argv)
    if known.city is None:
        return None, None
    env = os.environ.get(CITY_ENV)
    if env and env != known.city:
        return None, f"--city {known.city} differs from {CITY_ENV}={env}; set one of them"
    loaded = sys.modules.get("sitegen.config")
    if loaded is not None and loaded.CITY != known.city:
        return None, f"sitegen was loaded for {loaded.CITY}; run a new process for {known.city}"
    return known.city, None


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    city, err = _pick_city(argv)
    if err:
        print(f"sitegen: {err}", file=sys.stderr)
        return 2
    if city is not None:
        os.environ[CITY_ENV] = city
    from cities.errors import CityError
    try:
        from . import config
    except CityError as exc:
        print(f"sitegen: city {city or os.environ.get(CITY_ENV)}: {exc}", file=sys.stderr)
        return 2
    from .build import BuildError, build

    # A new city's files have a default home; Clarksville's (a legacy settings file) are always named.
    defaults = city is not None and not config.LEGACY_SETTINGS
    ap = argparse.ArgumentParser(prog="python -m sitegen", description="Render the Daylight static site of one city.")
    ap.add_argument("--city", help=f"the city's slug (config/cities/<slug>/; default {config.DEFAULT_CITY}, or "
                    f"{CITY_ENV}); a new city's --facts and --out then have defaults")
    ap.add_argument("--facts", required=not defaults, default=f"data/localities/{city}/facts.json" if defaults else None,
                    help="facts JSON (schema/facts.schema.json); with --city of a new city, "
                    "data/localities/<slug>/facts.json")
    ap.add_argument("--out", required=not defaults, default=f"build/{city}/site" if defaults else None,
                    help="output directory, e.g. build/site; with --city of a new city, build/<slug>/site")
    ap.add_argument("--internal", action="store_true", help="also write review.html (never in a public build)")
    ap.add_argument("--changes", help="changes.jsonl (default: next to the facts file)")
    ap.add_argument("--report", help="report.json from the verifier (default: next to --out)")
    ap.add_argument("--seats", help="holder records (default: config/seats.yml; none for a fixture facts file)")
    ap.add_argument("--districts", help="map file (default: config/localities/<locality>/districts.json)")
    ap.add_argument("--finance", help="finance JSON (schema/finance.schema.json; default: finance.json next to the "
                    "facts file, none for a fixture facts file). Without it Bids and awards is not built")
    ap.add_argument("--no-geocoder", action="store_true",
                    help="draw no landing address box (the claude.ai preview build); the plain lookup line stays")
    ap.add_argument("--target", choices=("preview", "pages"), default=config.DEFAULT_TARGET,
                    help="the host: preview (claude.ai artifact, at most 500 files; transcript pages are left out when "
                    "the site would pass that) or pages (GitHub Pages, at most 3000 files)")
    args = ap.parse_args(argv)
    if not os.path.isfile(args.facts):
        print(f"sitegen: {args.facts}: no such facts file", file=sys.stderr)
        return 1
    extra = {}
    if args.seats:
        extra["seats_path"] = args.seats
    if args.districts:
        extra["districts_path"] = args.districts
    if args.finance:
        extra["finance_path"] = args.finance
    try:
        result = build(args.facts, args.out, internal=args.internal,
                       changes_path=args.changes, report_path=args.report,
                       geocoder=not args.no_geocoder, target=args.target, city=args.city, **extra)
    except BuildError as exc:
        print(f"sitegen: {exc}", file=sys.stderr)
        return 1
    print(f"sitegen: wrote {len(result['pages'])} pages, {result['files']} files in total, to {args.out} "
          f"(target {result['target']}, cap {config.max_files(result['target'])} with the export; transcript pages "
          f"{result['transcript_pages'] if result['transcripts'] else 'left out'}"
          f"{'' if result.get('export', True) else '; open-data export left out'})")
    print(headroom_line(result))
    return 0


def headroom_line(result: dict) -> str:
    """The files still free under the target's cap: the cap minus the files the site has once the export is in."""
    from . import config
    cap, n = config.max_files(result["target"]), result["files_with_export"]
    return f"sitegen: file headroom {cap - n} ({result['target']} cap {cap} minus {n} files with the export)"


if __name__ == "__main__":
    sys.exit(main())
