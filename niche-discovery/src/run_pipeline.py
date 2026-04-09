#!/usr/bin/env python3
"""
Full pipeline orchestrator for niche discovery.

Usage:
    python src/run_pipeline.py                    # Run full pipeline
    python src/run_pipeline.py --from-step 3      # Resume from scoring
    python src/run_pipeline.py --only-step 2      # Only run scraping
    python src/run_pipeline.py --top-n 30         # Evaluate top 30 instead of 50
"""

import argparse
import logging
from pathlib import Path

from generate_niches import generate_all_niches
from scrape_reddit import scrape_all_candidates
from score_niches import score_all_niches
from qualitative_eval import evaluate_top_niches
from run_tracker import RunTracker

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"


def run_step(step: int, top_n: int = 50):
    """Run a single step of the pipeline."""
    if step == 1:
        logger.info("=" * 60)
        logger.info("STEP 1: Generating niche candidates")
        logger.info("=" * 60)
        candidates = generate_all_niches()
        logger.info(f"Generated {len(candidates)} candidates")

    elif step == 2:
        logger.info("=" * 60)
        logger.info("STEP 2: Scraping Reddit metrics")
        logger.info("=" * 60)
        results = scrape_all_candidates()
        found = sum(1 for r in results if r.subreddit_found)
        logger.info(f"Scraped {len(results)} candidates, {found} subreddits found")

    elif step == 3:
        logger.info("=" * 60)
        logger.info("STEP 3: Scoring opportunities")
        logger.info("=" * 60)
        scored = score_all_niches()
        logger.info(f"Scored {len(scored)} niches")

    elif step == 4:
        logger.info("=" * 60)
        logger.info(f"STEP 4: Qualitative evaluation (top {top_n})")
        logger.info("=" * 60)
        results = evaluate_top_niches(top_n=top_n)
        logger.info(f"Evaluated {len(results)} niches")


def run_full_pipeline(from_step: int = 1, top_n: int = 50):
    """Run the full pipeline from a given step."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    for step in range(from_step, 5):
        run_step(step, top_n=top_n)

    # Print final summary
    tracker = RunTracker()
    tracker.print_summary()

    # Export CSV
    csv_path = tracker.export_csv()
    logger.info(f"Exported full dataset to {csv_path}")


def main():
    parser = argparse.ArgumentParser(description="Niche Meme Discovery Pipeline")
    parser.add_argument(
        "--from-step",
        type=int,
        default=1,
        choices=[1, 2, 3, 4],
        help="Start from this step (1=generate, 2=scrape, 3=score, 4=evaluate)"
    )
    parser.add_argument(
        "--only-step",
        type=int,
        choices=[1, 2, 3, 4],
        help="Only run this step"
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=50,
        help="Number of niches to qualitatively evaluate (default: 50)"
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Just print the tracker summary"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose logging"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    if args.summary:
        tracker = RunTracker()
        tracker.print_summary()
        return

    if args.only_step:
        run_step(args.only_step, top_n=args.top_n)
    else:
        run_full_pipeline(from_step=args.from_step, top_n=args.top_n)


if __name__ == "__main__":
    main()
