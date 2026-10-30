"""Reproducible local ingest and bounded monthly archive download commands."""

import argparse
import json
import sys

from .pipeline import fetch_month, run_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the WA FuelWatch historical price warehouse")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="Load complete, closed monthly CSV snapshots")
    ingest.add_argument("--file", action="append", required=True, help="CSV path; repeat for multiple months")
    ingest.add_argument("--source-url", action="append", help="Original source URL; repeat in file order")
    fetch = commands.add_parser("fetch", help="Download a closed monthly publisher CSV and ingest it")
    fetch.add_argument("--month", help="YYYY-MM; defaults to the previous completed UTC calendar month")
    for command in (ingest, fetch):
        command.add_argument("--data-dir", default="data")
        command.add_argument("--as-of", help="Assessment date YYYY-MM-DD; defaults to today's UTC date")
    args = parser.parse_args()
    try:
        if args.command == "ingest":
            result = run_pipeline(args.data_dir, files=args.file, source_urls=args.source_url, as_of=args.as_of)
        else:
            result = fetch_month(args.data_dir, month=args.month, as_of=args.as_of)
    except Exception as exc:
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
