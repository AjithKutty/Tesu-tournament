"""
Unified tournament pipeline: parse input → generate schedules → build website.

Usage:
    # Excel mode (default):
    python src/main.py
    python src/main.py --source excel --file "path/to/draws.xlsx"

    # Web scraping mode:
    python src/main.py --source web --url "https://badmintonfinland.tournamentsoftware.com/sport/draws.aspx?id=..."

    # Web scraping with match results:
    python src/main.py --source web --url "..." --full-results

Runs all three stages in sequence:
  1. parse (Excel or web)  → output/divisions/*.json
  2. generate_schedule     → output/schedules/*.json
  3. generate_website      → output/webpages/index.html
"""

import sys
import os
import argparse

# Ensure src/ is on the import path so sibling modules resolve
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parse_tournament import main as parse_excel_main
from parse_web import main as parse_web_main
from generate_schedule import main as schedule_main
from generate_website import main as website_main


def main():
    parser = argparse.ArgumentParser(
        description="Badminton tournament website generator pipeline"
    )
    parser.add_argument(
        "--source",
        choices=["excel", "web"],
        default="excel",
        help="Input source: 'excel' (default) or 'web'",
    )
    parser.add_argument(
        "--file",
        default=None,
        help="Excel file path (used when --source=excel)",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Tournament draws page URL (required when --source=web)",
    )
    parser.add_argument(
        "--full-results",
        action="store_true",
        help="Include match results from web (only with --source=web)",
    )
    args = parser.parse_args()

    if args.source == "web" and not args.url:
        parser.error("--url is required when --source=web")

    print("=" * 60)
    print(f"Step 1/3: Parsing tournament data (source: {args.source})")
    print("=" * 60)

    if args.source == "excel":
        parse_excel_main(filepath=args.file)
    else:
        parse_web_main(url=args.url, full_results=args.full_results)

    print()
    print("=" * 60)
    print("Step 2/3: Generating match schedules")
    print("=" * 60)
    schedule_main()

    print()
    print("=" * 60)
    print("Step 3/3: Building website")
    print("=" * 60)
    website_main()

    print()
    print("=" * 60)
    print("Done! Open output/webpages/index.html in a browser.")
    print("=" * 60)


if __name__ == "__main__":
    main()
