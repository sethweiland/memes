"""
Step 2: Scrape Reddit metrics for candidate niches.

Input: data/candidates.json
Output: data/reddit_metrics.json
"""

import json
import logging
import os
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from statistics import median

import praw
from prawcore.exceptions import Redirect, NotFound, Forbidden
from tqdm import tqdm

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"


@dataclass
class RedditMetrics:
    """Metrics scraped from Reddit for a niche."""
    niche_name: str
    category: str

    # Subreddit info
    subreddit_found: bool = False
    subreddit_name: str = ""
    subscribers: int = 0
    active_users: int = 0
    created_utc: float = 0

    # Engagement metrics (from top 25 hot posts)
    avg_score: float = 0
    avg_comments: float = 0
    median_score: float = 0
    image_post_ratio: float = 0

    # Meme supply check
    existing_meme_count: int = 0

    # Content samples (for qualitative eval later)
    top_post_titles: list[str] = field(default_factory=list)
    top_post_texts: list[str] = field(default_factory=list)

    # Error tracking
    error: str = ""


def get_reddit_client() -> praw.Reddit:
    """Initialize Reddit client from env vars."""
    return praw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        user_agent="niche-meme-research/1.0",
    )


def scrape_subreddit(reddit: praw.Reddit, subreddit_name: str) -> dict | None:
    """Scrape metrics from a single subreddit. Returns None if not found."""
    try:
        sub = reddit.subreddit(subreddit_name)
        # Access an attribute to trigger the fetch
        _ = sub.subscribers
    except (Redirect, NotFound):
        return None
    except Forbidden:
        logger.debug(f"  Subreddit r/{subreddit_name} is private/quarantined")
        return None
    except Exception as e:
        logger.debug(f"  Error accessing r/{subreddit_name}: {e}")
        return None

    # Get basic info
    metrics = {
        "subreddit_name": sub.display_name,
        "subscribers": sub.subscribers or 0,
        "active_users": getattr(sub, "accounts_active", 0) or 0,
        "created_utc": getattr(sub, "created_utc", 0),
    }

    # Sample hot posts for engagement
    try:
        hot_posts = list(sub.hot(limit=25))

        if hot_posts:
            scores = [p.score for p in hot_posts]
            comments = [p.num_comments for p in hot_posts]

            metrics["avg_score"] = sum(scores) / len(scores)
            metrics["avg_comments"] = sum(comments) / len(comments)
            metrics["median_score"] = median(scores) if scores else 0

            # Image post ratio
            image_posts = sum(1 for p in hot_posts if not p.is_self)
            metrics["image_post_ratio"] = image_posts / len(hot_posts)

            # Top post samples
            metrics["top_post_titles"] = [p.title for p in hot_posts[:10]]
            metrics["top_post_texts"] = [
                (p.selftext[:200] if p.is_self and p.selftext else "")
                for p in hot_posts[:10]
            ]
    except Exception as e:
        logger.debug(f"  Error getting hot posts: {e}")

    # Check meme supply
    try:
        meme_results = list(sub.search("meme", limit=100))
        metrics["existing_meme_count"] = len(meme_results)
    except Exception as e:
        logger.debug(f"  Error searching for memes: {e}")
        metrics["existing_meme_count"] = 0

    return metrics


def scrape_candidate(reddit: praw.Reddit, candidate: dict) -> RedditMetrics:
    """Scrape metrics for a single candidate niche."""
    metrics = RedditMetrics(
        niche_name=candidate["niche_name"],
        category=candidate["category"],
    )

    # Try each likely subreddit
    subreddits = candidate.get("likely_subreddits", [])
    best_sub = None
    best_subscribers = 0

    for sub_name in subreddits:
        sub_name = sub_name.strip().replace("r/", "")
        if not sub_name:
            continue

        result = scrape_subreddit(reddit, sub_name)
        if result and result.get("subscribers", 0) > best_subscribers:
            best_sub = result
            best_subscribers = result["subscribers"]

        time.sleep(0.5)  # Rate limit

    if best_sub:
        metrics.subreddit_found = True
        metrics.subreddit_name = best_sub["subreddit_name"]
        metrics.subscribers = best_sub["subscribers"]
        metrics.active_users = best_sub.get("active_users", 0)
        metrics.created_utc = best_sub.get("created_utc", 0)
        metrics.avg_score = best_sub.get("avg_score", 0)
        metrics.avg_comments = best_sub.get("avg_comments", 0)
        metrics.median_score = best_sub.get("median_score", 0)
        metrics.image_post_ratio = best_sub.get("image_post_ratio", 0)
        metrics.existing_meme_count = best_sub.get("existing_meme_count", 0)
        metrics.top_post_titles = best_sub.get("top_post_titles", [])
        metrics.top_post_texts = best_sub.get("top_post_texts", [])

    return metrics


def scrape_all_candidates(resume: bool = True) -> list[RedditMetrics]:
    """Scrape Reddit metrics for all candidates."""
    # Load candidates
    candidates_file = DATA_DIR / "candidates.json"
    if not candidates_file.exists():
        logger.error("No candidates.json found. Run generate_niches.py first.")
        return []

    candidates = json.loads(candidates_file.read_text())
    logger.info(f"Loaded {len(candidates)} candidates")

    # Load existing results for resumability
    output_file = DATA_DIR / "reddit_metrics.json"
    existing_results = {}
    if resume and output_file.exists():
        data = json.loads(output_file.read_text())
        existing_results = {r["niche_name"]: r for r in data}
        logger.info(f"Resuming from {len(existing_results)} existing results")

    # Initialize Reddit client
    reddit = get_reddit_client()
    logger.info("Connected to Reddit API")

    # Scrape each candidate
    results = []
    for candidate in tqdm(candidates, desc="Scraping Reddit"):
        name = candidate["niche_name"]

        # Skip if already scraped
        if name in existing_results:
            results.append(RedditMetrics(**existing_results[name]))
            continue

        metrics = scrape_candidate(reddit, candidate)
        results.append(metrics)

        # Save incrementally every 50
        if len(results) % 50 == 0:
            with open(output_file, "w") as f:
                json.dump([asdict(r) for r in results], f, indent=2)
            logger.info(f"  Saved checkpoint at {len(results)} results")

        time.sleep(1)  # Rate limit between candidates

    # Final save
    with open(output_file, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)

    # Stats
    found = sum(1 for r in results if r.subreddit_found)
    logger.info(f"Scraped {len(results)} candidates, {found} subreddits found")

    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    results = scrape_all_candidates()

    print(f"\nScraped {len(results)} candidates")
    found = [r for r in results if r.subreddit_found]
    print(f"Subreddits found: {len(found)}")

    print("\nTop 10 by subscribers:")
    top = sorted(found, key=lambda x: -x.subscribers)[:10]
    for r in top:
        print(f"  r/{r.subreddit_name}: {r.subscribers:,} subscribers")
