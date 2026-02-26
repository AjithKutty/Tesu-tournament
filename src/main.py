"""
Unified tournament pipeline: parse Excel → generate schedules → build website.

Usage:
    python src/main.py

Runs all three stages in sequence:
  1. parse_tournament  — Excel → output/divisions/*.json
  2. generate_schedule — divisions → output/schedules/*.json
  3. generate_website  — divisions + schedules → output/webpages/index.html
"""

import sys
import os

# Ensure src/ is on the import path so sibling modules resolve
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parse_tournament import main as parse_main
from generate_schedule import main as schedule_main
from generate_website import main as website_main


def main():
    print("=" * 60)
    print("Step 1/3: Parsing Excel file")
    print("=" * 60)
    parse_main()

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
