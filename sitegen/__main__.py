"""python -m sitegen --facts <facts.json> --out build/site [--internal] [--no-geocoder] [--finance <finance.json>]
    [--target preview|pages]

--no-geocoder: no "Find your district" address box on the landing (and no geocoder in the page's CSP), only the plain
"Not sure of your district?" lookup line. Use it for the claude.ai preview, where the box cannot reach the geocoder."""
import argparse
import sys

from . import config
from .build import BuildError, build


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m sitegen", description="Render the Clarksville Records static site.")
    ap.add_argument("--facts", required=True, help="facts JSON (schema/facts.schema.json)")
    ap.add_argument("--out", required=True, help="output directory, e.g. build/site")
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
                       geocoder=not args.no_geocoder, target=args.target, **extra)
    except BuildError as exc:
        print(f"sitegen: {exc}", file=sys.stderr)
        return 1
    print(f"sitegen: wrote {len(result['pages'])} pages, {result['files']} files in total, to {args.out} "
          f"(target {result['target']}, cap {config.max_files(result['target'])} with the export; transcript pages "
          f"{result['transcript_pages'] if result['transcripts'] else 'left out'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
