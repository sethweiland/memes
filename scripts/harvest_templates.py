#!/usr/bin/env python3
"""
Batch template harvester — searches imgflip's search_memes API with curated
terms, deduplicates against the existing catalog, tracks search history for
budget management, and records template provenance metadata.

Usage:
    python scripts/harvest_templates.py                    # Run all unsearched terms
    python scripts/harvest_templates.py --dry-run          # Preview without API calls
    python scripts/harvest_templates.py --limit 30         # Cap at 30 searches this run
    python scripts/harvest_templates.py --force            # Re-search even if done recently
    python scripts/harvest_templates.py --query "pickle rick"  # Single one-off search
    python scripts/harvest_templates.py --skip-days 30     # Skip terms searched within N days
    python scripts/harvest_templates.py --terms-file x.json    # Custom terms file
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.templates import TemplatesCatalog

DEFAULT_TERMS_FILE = "data/search_terms.json"
SEARCH_HISTORY_FILE = "data/search_history.json"
MONTHLY_BUDGET = 200
BUDGET_WARNING_THRESHOLD = 180
DEFAULT_SKIP_DAYS = 30
SLEEP_BETWEEN_CALLS = 1.5


def load_search_terms(terms_file: str) -> list[str]:
    """Load and flatten search terms from categorized JSON."""
    path = Path(terms_file)
    if not path.exists():
        print(f"Error: terms file not found: {terms_file}")
        sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    terms = []
    for category_terms in data["categories"].values():
        terms.extend(category_terms)
    return terms


def load_search_history() -> dict:
    """Load search history from JSON file."""
    path = Path(SEARCH_HISTORY_FILE)
    if not path.exists():
        return {"searches": []}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"searches": []}


def save_search_history(history: dict):
    """Save search history to JSON file."""
    Path(SEARCH_HISTORY_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(SEARCH_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def count_monthly_searches(history: dict) -> int:
    """Count searches performed in the current calendar month."""
    now = datetime.now(timezone.utc)
    prefix = now.strftime("%Y-%m")
    return sum(
        1 for s in history["searches"]
        if s.get("searched_at", "").startswith(prefix)
    )


def get_recently_searched(history: dict, skip_days: int) -> set[str]:
    """Return set of queries searched within the last skip_days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=skip_days)
    recent = set()
    for s in history["searches"]:
        try:
            searched_at = datetime.fromisoformat(s["searched_at"])
            if searched_at.tzinfo is None:
                searched_at = searched_at.replace(tzinfo=timezone.utc)
            if searched_at >= cutoff:
                recent.add(s["query"])
        except (KeyError, ValueError):
            continue
    return recent


def parse_args():
    parser = argparse.ArgumentParser(
        description="Batch search imgflip for meme templates"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview what would be searched without making API calls"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Maximum number of searches to perform this run"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-search terms even if searched recently"
    )
    parser.add_argument(
        "--query", type=str, default=None,
        help="Single one-off search query (bypasses terms file)"
    )
    parser.add_argument(
        "--skip-days", type=int, default=DEFAULT_SKIP_DAYS,
        help=f"Skip terms searched within N days (default {DEFAULT_SKIP_DAYS})"
    )
    parser.add_argument(
        "--terms-file", type=str, default=DEFAULT_TERMS_FILE,
        help=f"Path to search terms JSON file (default {DEFAULT_TERMS_FILE})"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Load credentials
    username = os.getenv("IMGFLIP_USERNAME")
    password = os.getenv("IMGFLIP_PASSWORD")
    if not args.dry_run and (not username or not password):
        print("Error: IMGFLIP_USERNAME and IMGFLIP_PASSWORD env vars required")
        sys.exit(1)

    # Load catalog and history
    catalog = TemplatesCatalog()
    history = load_search_history()
    monthly_count = count_monthly_searches(history)

    print(f"Catalog: {len(catalog.templates)} templates")
    print(f"Monthly budget: {monthly_count}/{MONTHLY_BUDGET} searches used")

    if monthly_count >= BUDGET_WARNING_THRESHOLD:
        print(f"WARNING: Approaching monthly budget ({monthly_count}/{MONTHLY_BUDGET})")

    # Determine which terms to search
    if args.query:
        terms_to_search = [args.query]
    else:
        all_terms = load_search_terms(args.terms_file)
        if args.force:
            terms_to_search = all_terms
        else:
            recently_searched = get_recently_searched(history, args.skip_days)
            terms_to_search = [t for t in all_terms if t not in recently_searched]

    if args.limit is not None:
        terms_to_search = terms_to_search[:args.limit]

    # Check budget
    remaining_budget = MONTHLY_BUDGET - monthly_count
    if len(terms_to_search) > remaining_budget and not args.dry_run:
        print(f"WARNING: {len(terms_to_search)} terms requested but only "
              f"{remaining_budget} searches left in budget. Capping at {remaining_budget}.")
        terms_to_search = terms_to_search[:remaining_budget]

    if not terms_to_search:
        print("No terms to search (all recently searched or none remaining).")
        return

    # Dry run: just show what would be done
    if args.dry_run:
        print(f"\n[DRY RUN] Would search {len(terms_to_search)} terms:")
        for i, term in enumerate(terms_to_search, 1):
            print(f"  {i}. {term}")
        print(f"\nBudget after: {monthly_count + len(terms_to_search)}/{MONTHLY_BUDGET}")
        return

    # Execute searches
    print(f"\nSearching {len(terms_to_search)} terms...")
    total_new = 0
    searches_done = 0
    errors = 0

    for i, term in enumerate(terms_to_search, 1):
        print(f"  [{i}/{len(terms_to_search)}] Searching: {term!r}", end=" ... ")

        entry = {
            "query": term,
            "searched_at": datetime.now(timezone.utc).isoformat(),
            "results_count": 0,
            "new_count": 0,
            "success": False,
            "error": None,
        }

        try:
            new_templates = catalog.search_and_add(
                term, username, password, record_metadata=True
            )
            entry["results_count"] = len(catalog.templates)
            entry["new_count"] = len(new_templates)
            entry["success"] = True
            total_new += len(new_templates)
            searches_done += 1
            print(f"{len(new_templates)} new")
        except Exception as e:
            entry["error"] = str(e)
            errors += 1
            print(f"ERROR: {e}")

        # Append and save after every search (crash-safe)
        history["searches"].append(entry)
        save_search_history(history)

        # Sleep between calls (skip after last one)
        if i < len(terms_to_search):
            time.sleep(SLEEP_BETWEEN_CALLS)

    # Summary
    print(f"\n{'=' * 50}")
    print(f"Searches performed: {searches_done}")
    print(f"Errors: {errors}")
    print(f"New templates found: {total_new}")
    print(f"Total catalog size: {len(catalog.templates)}")
    print(f"Monthly budget used: {monthly_count + searches_done}/{MONTHLY_BUDGET}")

    remaining = MONTHLY_BUDGET - monthly_count - searches_done
    if remaining > 0:
        print(f"Budget remaining: {remaining} searches")
    else:
        print("Budget exhausted for this month.")


if __name__ == "__main__":
    main()
