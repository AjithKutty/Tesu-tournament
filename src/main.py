"""
Unified tournament pipeline: parse input → generate schedules → build website.

Usage:
    # Run with tournament config:
    python src/main.py --tournament tournaments/kumpoo-2025

    # Override input source:
    python src/main.py --tournament tournaments/kumpoo-2025 --source web
    python src/main.py --tournament tournaments/kumpoo-2025 --source web --full-results

    # Override Excel file:
    python src/main.py --tournament tournaments/kumpoo-2025 --source excel --file "path/to/draws.xlsx"

Runs all four stages in sequence:
  1. parse (Excel or web)  → tournaments/<name>/output/divisions/*.json
  2. generate_schedule     → tournaments/<name>/output/schedules/*.json
  3. verify_schedule       → checks bracket completeness, round ordering, coverage, conflicts
  4. generate_website      → tournaments/<name>/output/webpages/index.html
"""

import sys
import os
import argparse

# Ensure src/ is on the import path so sibling modules resolve
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config, get_tournament_name
from parse_tournament import main as parse_excel_main
from parse_web import main as parse_web_main
from parse_entries import main as parse_entries_main
from generate_schedule import main as schedule_main
from verify_schedule import verify as verify_main
from generate_website import main as website_main


def main():
    parser = argparse.ArgumentParser(
        description="Badminton tournament website generator pipeline"
    )
    parser.add_argument(
        "--tournament",
        required=True,
        help="Path to tournament directory (e.g. tournaments/kumpoo-2025)",
    )
    parser.add_argument(
        "--source",
        choices=["excel", "web"],
        default=None,
        help="Input source: 'excel' or 'web' (overrides tournament.yaml)",
    )
    parser.add_argument(
        "--file",
        default=None,
        help="Excel file path (overrides tournament.yaml)",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Tournament draws page URL (overrides tournament.yaml)",
    )
    parser.add_argument(
        "--full-results",
        action="store_true",
        help="Include match results from web (only with --source=web)",
    )
    parser.add_argument(
        "--rescrape",
        action="store_true",
        help="Force fresh web scraping (ignore cached data)",
    )
    parser.add_argument(
        "--get-winners",
        action="store_true",
        help="Use actual winner names from scraped data in later bracket rounds "
             "(default: use structural placeholders like 'Winner R1-M1')",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible draws (entries-only mode)",
    )
    args = parser.parse_args()

    # Load config
    config = load_config(args.tournament)
    tournament_name = get_tournament_name(config)

    # Determine input source
    source = args.source or config["tournament"].get("input", {}).get("source", "excel")
    full_results = args.full_results or config["tournament"].get("input", {}).get("full_results", False)

    if source == "web":
        url = args.url or config["tournament"].get("input", {}).get("web_url")
        if not url:
            parser.error("No URL provided: use --url or set web_url in tournament.yaml")

    print("=" * 60)
    print(f"Tournament: {tournament_name}")
    print(f"Step 1/4: Parsing tournament data (source: {source})")
    print("=" * 60)

    if source == "excel":
        filepath = args.file
        if not filepath:
            excel_file = config["tournament"].get("input", {}).get("excel_file")
            if excel_file:
                filepath = os.path.join(config["paths"]["input_dir"], excel_file)
        _, count = parse_excel_main(config=config, filepath=filepath)
        if count == 0:
            print("\nNo draws found in Excel — falling back to entries-only mode")
            parse_entries_main(config=config, seed=args.seed)
    else:
        parse_web_main(config=config, url=url, full_results=full_results,
                       rescrape=args.rescrape, get_winners=args.get_winners,
                       seed=args.seed)

    print()
    print("=" * 60)
    print("Step 2/4: Generating match schedules")
    print("=" * 60)
    schedule_main(config=config)

    print()
    print("=" * 60)
    print("Step 3/4: Verifying schedule")
    print("=" * 60)
    issue_count = verify_main(config=config)

    print()
    print("=" * 60)
    print("Step 4/4: Building website")
    print("=" * 60)
    website_main(config=config)

    output_file = os.path.join(config["paths"]["webpages_dir"], "index.html")
    print()
    print("=" * 60)
    print(f"Done! Open {output_file} in a browser.")
    print("=" * 60)


if __name__ == "__main__":
    main()
