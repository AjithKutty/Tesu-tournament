# Implementation Plan: Web Scraper Input Source

## Overview

`src/parse_web.py` is an alternative to `src/parse_tournament.py`. Both produce identical JSON files in the tournament's `output/divisions/` directory so the downstream pipeline works unchanged.

Scraped data is cached in the tournament's `scraped/` directory to avoid re-scraping on subsequent runs.

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/parse_web.py` | Modify | Add tournament dir support, scrape caching |
| `src/main.py` | Modify | Accept `--tournament` arg, load config |
| `src/parse_tournament.py` | Modify | Accept tournament dir, read config for mappings |
| `requirements.txt` | Modify | Add `pyyaml` |

No changes to the scraping logic itself — only path handling and config loading.

## CLI Interface

```bash
# Full pipeline with tournament config:
python src/main.py --tournament tournaments/kumpoo-2025

# Override source via CLI:
python src/main.py --tournament tournaments/kumpoo-2025 --source web

# Web scraping with match results:
python src/main.py --tournament tournaments/kumpoo-2025 --source web --full-results

# Standalone:
python src/parse_web.py --tournament tournaments/kumpoo-2025
```

## Scrape Caching

When scraping, save raw HTML/JSON responses to `tournaments/<name>/scraped/`:
- `draws_list.json` — draw list metadata
- `draw_meta_{N}.json` — per-draw metadata
- `draw_matches_{N}.html` — per-draw match data
- `clubs.json` — club list

On subsequent runs, if cached files exist, load from cache instead of making HTTP requests. A `--rescrape` flag forces fresh scraping.

## Config Integration

- **Tournament name**: Read from `tournament.yaml` (fallback: scrape from page)
- **Event names and level categories**: Read from `divisions.yaml` (same mappings as Excel parser)
- **Doubles events**: Read from `divisions.yaml`
- **Output directory**: `tournaments/<name>/output/divisions/`

## Data Gaps and Handling

| Gap | Handling |
|-----|---------|
| No club per player on web | Set `"club": null` for all player entries |
| No draw positions on web | Infer from match order in Round 1 |
| No explicit round names | Derive from draw_size |
| No bracket for unplayed rounds | Generate "Winner R1-M1" structural placeholders |
| Division `"clubs"` list empty | `tournament_index.json` has full club list from clubs.aspx |

## Robustness

- 0.5s delay between requests (avoid IP throttling)
- Retry cookie bypass if mid-session redirect to cookie wall
- Graceful skip for draws that fail to parse (log warning)
- UTF-8 encoding throughout for Finnish characters
- Cache invalidation via `--rescrape` flag

## Verification Steps

1. `python src/main.py --tournament tournaments/kumpoo-2025` — Excel mode works
2. `python src/main.py --tournament tournaments/kumpoo-2025 --source web` — produces JSON, caches scraped data
3. Second run with web source loads from cache (no HTTP requests)
4. `--rescrape` forces fresh scraping
5. Compare JSON structure: same keys, same format values
6. Full pipeline with web data: all 3 steps complete, `index.html` loads
