"""
Step 4: LLM qualitative evaluation of top niches.

Input: data/scored_niches.json (top N)
Output: data/final_ranked.json, data/final_report.csv
"""

import json
import logging
import csv
from dataclasses import dataclass, asdict, field
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from src.core.grok import GrokClient
from run_tracker import RunTracker, NicheRecord

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"


EVAL_PROMPT = """Here are the top posts from the r/{subreddit} community ({subscribers:,} subscribers):

Titles:
{titles}

Sample post content:
{texts}

This community is about: {niche_name} - {description}

Evaluate this community as a target for a dedicated AI-powered meme page. Rate each dimension 1-10:

1. inside_joke_density — Does this community have recurring humor, shared references, or in-jokes?
2. visual_meme_potential — Could the humor translate well into image-based meme formats?
3. identity_strength — How strong is the "us vs them" or shared identity that makes community-specific content resonate?
4. engagement_likelihood — Would members share/engage with memes about their community?
5. content_sustainability — Is there enough variety in topics to sustain ongoing meme content (not just one joke)?

Also provide:
- top_3_recurring_themes: The 3 most meme-able recurring topics or jokes you see
- sample_meme_concepts: 2 specific meme ideas that would work for this community
- risks: Any reasons this might NOT work (e.g., community is too serious, humor is too niche to package, etc.)

Return as JSON only. No markdown. Example:
{{
  "inside_joke_density": 7,
  "visual_meme_potential": 8,
  "identity_strength": 9,
  "engagement_likelihood": 7,
  "content_sustainability": 6,
  "top_3_recurring_themes": ["theme1", "theme2", "theme3"],
  "sample_meme_concepts": ["Drake meme about X vs Y", "Expanding brain about Z"],
  "risks": "Community might be too small for viral reach"
}}"""


@dataclass
class FinalNiche:
    """Final evaluated niche with both quant and qual scores."""
    niche_name: str
    category: str
    subreddit: str
    subscribers: int

    # Quantitative
    quantitative_score: float
    community_strength: float
    supply_gap: float

    # Qualitative ratings (1-10)
    inside_joke_density: int = 0
    visual_meme_potential: int = 0
    identity_strength: int = 0
    engagement_likelihood: int = 0
    content_sustainability: int = 0

    # Qualitative extras
    top_themes: list[str] = field(default_factory=list)
    sample_meme_concepts: list[str] = field(default_factory=list)
    risks: str = ""

    # Combined
    qualitative_score: float = 0
    final_score: float = 0


def evaluate_niche(grok: GrokClient, niche: dict) -> dict:
    """Run qualitative evaluation on a single niche."""
    prompt = EVAL_PROMPT.format(
        subreddit=niche["subreddit_name"],
        subscribers=niche["subscribers"],
        titles="\n".join(f"- {t}" for t in niche.get("top_post_titles", [])[:10]),
        texts="\n".join(t for t in niche.get("top_post_texts", [])[:5] if t),
        niche_name=niche["niche_name"],
        description=niche.get("description", "No description"),
    )

    for attempt in range(3):
        try:
            response = grok._chat(
                messages=[{"role": "user", "content": prompt}],
                model="grok-3-mini",
                temperature=0.3,
            )

            # Parse JSON
            result = json.loads(response.strip())
            return result

        except json.JSONDecodeError:
            logger.warning(f"  Attempt {attempt + 1}: JSON parse error")
            continue
        except Exception as e:
            logger.warning(f"  Attempt {attempt + 1}: {e}")
            continue

    return {}


def evaluate_top_niches(top_n: int = 50) -> list[FinalNiche]:
    """Evaluate the top N scored niches."""
    scored_file = DATA_DIR / "scored_niches.json"
    if not scored_file.exists():
        logger.error("No scored_niches.json found. Run score_niches.py first.")
        return []

    scored = json.loads(scored_file.read_text())
    logger.info(f"Loaded {len(scored)} scored niches, evaluating top {top_n}")

    grok = GrokClient()
    tracker = RunTracker()

    # Start a run for tracking
    run_id = tracker.start_run(
        categories=list(set(n["category"] for n in scored[:top_n])),
        config={"top_n": top_n, "step": "qualitative_eval"}
    )

    results = []
    for i, niche in enumerate(scored[:top_n], 1):
        logger.info(f"[{i}/{top_n}] Evaluating {niche['niche_name']}...")

        eval_result = evaluate_niche(grok, niche)

        if not eval_result:
            logger.warning(f"  Failed to evaluate, skipping")
            continue

        # Compute qualitative score (average of 5 dimensions)
        qual_scores = [
            eval_result.get("inside_joke_density", 0),
            eval_result.get("visual_meme_potential", 0),
            eval_result.get("identity_strength", 0),
            eval_result.get("engagement_likelihood", 0),
            eval_result.get("content_sustainability", 0),
        ]
        qual_avg = sum(qual_scores) / len(qual_scores) if qual_scores else 0

        # Final score: 40% quantitative, 60% qualitative
        quant_normalized = niche["normalized_score"] / 10  # 0-10 scale
        final = (quant_normalized * 0.4) + (qual_avg * 0.6)

        final_niche = FinalNiche(
            niche_name=niche["niche_name"],
            category=niche["category"],
            subreddit=niche["subreddit_name"],
            subscribers=niche["subscribers"],
            quantitative_score=niche["normalized_score"],
            community_strength=niche["community_strength"],
            supply_gap=niche["supply_gap"],
            inside_joke_density=eval_result.get("inside_joke_density", 0),
            visual_meme_potential=eval_result.get("visual_meme_potential", 0),
            identity_strength=eval_result.get("identity_strength", 0),
            engagement_likelihood=eval_result.get("engagement_likelihood", 0),
            content_sustainability=eval_result.get("content_sustainability", 0),
            top_themes=eval_result.get("top_3_recurring_themes", []),
            sample_meme_concepts=eval_result.get("sample_meme_concepts", []),
            risks=eval_result.get("risks", ""),
            qualitative_score=round(qual_avg, 1),
            final_score=round(final, 2),
        )
        results.append(final_niche)

        # Track in run tracker
        tracker.add_or_update_niche(NicheRecord(
            niche_name=final_niche.niche_name,
            category=final_niche.category,
            subreddit=final_niche.subreddit,
            subscribers=final_niche.subscribers,
            quantitative_score=final_niche.quantitative_score,
            qualitative_score=final_niche.qualitative_score,
            final_score=final_niche.final_score,
            inside_joke_density=final_niche.inside_joke_density,
            visual_meme_potential=final_niche.visual_meme_potential,
            identity_strength=final_niche.identity_strength,
            engagement_likelihood=final_niche.engagement_likelihood,
            content_sustainability=final_niche.content_sustainability,
            top_themes=final_niche.top_themes,
            sample_meme_concepts=final_niche.sample_meme_concepts,
            risks=final_niche.risks,
        ), run_id)

    # Sort by final score
    results.sort(key=lambda x: -x.final_score)

    # Update run with top 10
    tracker.update_run(run_id,
        niches_scored=len(results),
        top_10_niches=[n.niche_name for n in results[:10]]
    )

    # Save full results
    output_file = DATA_DIR / "final_ranked.json"
    with open(output_file, "w") as f:
        json.dump([asdict(n) for n in results], f, indent=2)
    logger.info(f"Saved {len(results)} final rankings to {output_file}")

    # Save CSV report
    csv_file = DATA_DIR / "final_report.csv"
    with open(csv_file, "w", newline="") as f:
        fieldnames = [
            "rank", "niche_name", "subreddit", "subscribers",
            "final_score", "quantitative_score", "qualitative_score",
            "inside_joke_density", "visual_meme_potential", "identity_strength",
            "top_themes", "sample_meme_concepts", "risks"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i, n in enumerate(results, 1):
            writer.writerow({
                "rank": i,
                "niche_name": n.niche_name,
                "subreddit": f"r/{n.subreddit}",
                "subscribers": n.subscribers,
                "final_score": n.final_score,
                "quantitative_score": n.quantitative_score,
                "qualitative_score": n.qualitative_score,
                "inside_joke_density": n.inside_joke_density,
                "visual_meme_potential": n.visual_meme_potential,
                "identity_strength": n.identity_strength,
                "top_themes": "; ".join(n.top_themes),
                "sample_meme_concepts": "; ".join(n.sample_meme_concepts),
                "risks": n.risks,
            })
    logger.info(f"Saved CSV report to {csv_file}")

    # Print results
    print("\n" + "=" * 80)
    print("FINAL RANKINGS - TOP MEME PAGE OPPORTUNITIES")
    print("=" * 80)
    print(f"{'Rank':<5} {'Final':<7} {'Qual':<6} {'Niche':<25} {'Subreddit':<18} {'Themes'}")
    print("-" * 80)
    for i, n in enumerate(results[:20], 1):
        themes = ", ".join(n.top_themes[:2]) if n.top_themes else "-"
        print(f"{i:<5} {n.final_score:<7.2f} {n.qualitative_score:<6.1f} {n.niche_name[:24]:<25} r/{n.subreddit[:16]:<16} {themes[:30]}")
    print()

    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-n", type=int, default=50, help="Number of niches to evaluate")
    args = parser.parse_args()

    results = evaluate_top_niches(top_n=args.top_n)
    print(f"\nEvaluated {len(results)} niches")
