"""python -m sitegen --facts <facts.json> --out build/site [--internal]"""
import argparse
import sys

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
    args = ap.parse_args(argv)
    extra = {}
    if args.seats:
        extra["seats_path"] = args.seats
    if args.districts:
        extra["districts_path"] = args.districts
    try:
        result = build(args.facts, args.out, internal=args.internal,
                       changes_path=args.changes, report_path=args.report, **extra)
    except BuildError as exc:
        print(f"sitegen: {exc}", file=sys.stderr)
        return 1
    print(f"sitegen: wrote {len(result['pages'])} pages, {result['files']} files in total, to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
