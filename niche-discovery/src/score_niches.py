"""
Step 3: Compute opportunity scores for niches.

Input: data/reddit_metrics.json
Output: data/scored_niches.json

Opportunity Score = Community Strength × Supply Gap × Visual Factor × Engagement Quality

Where:
- Community Strength = log10(subscribers) × avg_comments
- Supply Gap = 1 / max(existing_meme_count, 1)  # Fewer memes = higher opportunity
- Visual Factor = 0.5 + (image_post_ratio × 0.5)  # Image-sharing communities easier
- Engagement Quality = median_score / avg_score  # Less reliance on viral outliers
"""

import json
import logging
import math
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"


@dataclass
class ScoredNiche:
    """A niche with its opportunity score."""
    niche_name: str
    category: str
    subreddit_name: str
    subscribers: int
    active_users: int

    # Raw metrics
    avg_score: float
    avg_comments: float
    median_score: float
    image_post_ratio: float
    existing_meme_count: int

    # Computed scores
    community_strength: float
    supply_gap: float
    visual_factor: float
    engagement_quality: float
    opportunity_score: float
    normalized_score: float  # 0-100

    # Content samples
    top_post_titles: list[str]
    top_post_texts: list[str]


def compute_opportunity_score(metrics: dict) -> dict:
    """Compute the opportunity score components."""
    subscribers = max(metrics.get("subscribers", 0), 1)
    avg_comments = max(metrics.get("avg_comments", 0), 0.1)
    existing_meme_count = max(metrics.get("existing_meme_count", 0), 1)
    image_post_ratio = metrics.get("image_post_ratio", 0)
    avg_score = max(metrics.get("avg_score", 1), 1)
    median_score = max(metrics.get("median_score", 0), 0)

    # Community strength: size × engagement
    community_strength = math.log10(subscribers) * avg_comments

    # Supply gap: inverse of existing meme content
    # Cap at 100 to prevent huge values for 1-meme subreddits
    supply_gap = min(1.0 / existing_meme_count, 1.0)

    # Visual culture factor
    visual_factor = 0.5 + (image_post_ratio * 0.5)

    # Engagement quality: median vs avg ratio
    engagement_quality = median_score / avg_score if avg_score > 0 else 0.5

    # Combined score
    opportunity_score = (
        community_strength *
        supply_gap *
        visual_factor *
        engagement_quality
    )

    return {
        "community_strength": round(community_strength, 2),
        "supply_gap": round(supply_gap, 4),
        "visual_factor": round(visual_factor, 2),
        "engagement_quality": round(engagement_quality, 2),
        "opportunity_score": round(opportunity_score, 4),
    }


def score_all_niches() -> list[ScoredNiche]:
    """Score all niches from reddit_metrics.json."""
    metrics_file = DATA_DIR / "reddit_metrics.json"
    if not metrics_file.exists():
        logger.error("No reddit_metrics.json found. Run scrape_reddit.py first.")
        return []

    metrics_data = json.loads(metrics_file.read_text())
    logger.info(f"Loaded {len(metrics_data)} metrics")

    # Filter to found subreddits
    found = [m for m in metrics_data if m.get("subreddit_found")]
    logger.info(f"Scoring {len(found)} niches with found subreddits")

    scored = []
    for m in found:
        scores = compute_opportunity_score(m)

        niche = ScoredNiche(
            niche_name=m["niche_name"],
            category=m["category"],
            subreddit_name=m["subreddit_name"],
            subscribers=m["subscribers"],
            active_users=m.get("active_users", 0),
            avg_score=m.get("avg_score", 0),
            avg_comments=m.get("avg_comments", 0),
            median_score=m.get("median_score", 0),
            image_post_ratio=m.get("image_post_ratio", 0),
            existing_meme_count=m.get("existing_meme_count", 0),
            community_strength=scores["community_strength"],
            supply_gap=scores["supply_gap"],
            visual_factor=scores["visual_factor"],
            engagement_quality=scores["engagement_quality"],
            opportunity_score=scores["opportunity_score"],
            normalized_score=0,  # Computed below
            top_post_titles=m.get("top_post_titles", []),
            top_post_texts=m.get("top_post_texts", []),
        )
        scored.append(niche)

    # Normalize scores to 0-100
    if scored:
        max_score = max(n.opportunity_score for n in scored)
        min_score = min(n.opportunity_score for n in scored)
        score_range = max_score - min_score if max_score > min_score else 1

        for n in scored:
            n.normalized_score = round(
                ((n.opportunity_score - min_score) / score_range) * 100, 1
            )

    # Sort by score descending
    scored.sort(key=lambda x: -x.opportunity_score)

    # Save results
    output_file = DATA_DIR / "scored_niches.json"
    with open(output_file, "w") as f:
        json.dump([asdict(n) for n in scored], f, indent=2)

    logger.info(f"Saved {len(scored)} scored niches to {output_file}")

    # Print top 30
    print("\n" + "=" * 70)
    print("TOP 30 NICHE OPPORTUNITIES")
    print("=" * 70)
    print(f"{'Rank':<5} {'Score':<8} {'Niche':<30} {'Subreddit':<20} {'Subs':<10}")
    print("-" * 70)
    for i, n in enumerate(scored[:30], 1):
        print(f"{i:<5} {n.normalized_score:<8.1f} {n.niche_name[:29]:<30} r/{n.subreddit_name[:18]:<18} {n.subscribers:>9,}")
    print()

    return scored


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    scored = score_all_niches()
    print(f"\nScored {len(scored)} niches")
