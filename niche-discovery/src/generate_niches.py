"""
Step 1: Generate candidate niches using LLM.

Input: config/niche_seeds.yaml
Output: data/candidates.json
"""

import json
import logging
import yaml
from pathlib import Path
from dataclasses import dataclass, asdict

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from src.core.grok import GrokClient

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent / "config"
DATA_DIR = Path(__file__).parent.parent / "data"


@dataclass
class NicheCandidate:
    """A candidate niche from LLM generation."""
    niche_name: str
    category: str
    likely_subreddits: list[str]
    description: str


GENERATION_PROMPT = """Generate a list of {count} specific online subcommunities/niches within the category "{name}".
Description: {hint}

For each niche, provide:
- niche_name: A clear, specific name for this community (e.g., "HVAC technicians" not just "tradespeople")
- likely_subreddits: A list of 1-3 subreddit names (without r/) that this community likely uses. Guess the most probable subreddit names — they don't have to be verified yet.
- description: One sentence describing the community and what makes their humor unique

Focus on communities that:
1. Have strong shared identity ("us vs them" mentality)
2. Have inside jokes, jargon, or recurring memes
3. Are underserved by dedicated meme content
4. Would engage with memes about their community

Return as a JSON array. No markdown formatting, just raw JSON.

Example format:
[
  {{
    "niche_name": "HVAC technicians",
    "likely_subreddits": ["HVAC", "hvacadvice", "bluecollarbros"],
    "description": "Tradespeople who fix heating/cooling systems; humor involves thermostat wars, attic crawls, and 'it's not the capacitor' jokes"
  }}
]"""


def load_seeds() -> list[dict]:
    """Load category seeds from YAML config."""
    config_path = CONFIG_DIR / "niche_seeds.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return config.get("categories", [])


BATCH_SIZE = 20  # Generate in small batches to avoid truncation


def generate_batch(grok: GrokClient, category: dict, batch_num: int, batch_size: int, existing: set[str]) -> list[NicheCandidate]:
    """Generate a single batch of niches."""
    prompt = GENERATION_PROMPT.format(
        count=batch_size,
        name=category["name"],
        hint=category["hint"],
    )

    # Add variety hint for subsequent batches
    if batch_num > 0:
        prompt += f"\n\nThis is batch {batch_num + 1}. Generate DIFFERENT niches from previous batches. Be creative and explore less obvious subcommunities."

    for attempt in range(3):
        try:
            response = grok._chat(
                messages=[{"role": "user", "content": prompt}],
                model="grok-3-mini",
                temperature=0.8 + (batch_num * 0.05),  # Increase temp for variety
                max_tokens=4000,
            )

            # Try to extract JSON from response
            response_text = response.strip()

            # Handle markdown code blocks
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            niches_data = json.loads(response_text)

            candidates = []
            for item in niches_data:
                name = item.get("niche_name", "").strip()
                if not name:
                    continue

                # Skip if already seen
                if name.lower() in existing:
                    continue

                existing.add(name.lower())
                candidates.append(NicheCandidate(
                    niche_name=name,
                    category=category["name"],
                    likely_subreddits=item.get("likely_subreddits", []),
                    description=item.get("description", ""),
                ))

            return candidates

        except json.JSONDecodeError as e:
            logger.warning(f"    Batch {batch_num + 1} attempt {attempt + 1} failed: JSON parse error")
            continue
        except Exception as e:
            logger.warning(f"    Batch {batch_num + 1} attempt {attempt + 1} failed: {e}")
            continue

    return []


def generate_for_category(grok: GrokClient, category: dict, existing: set[str]) -> list[NicheCandidate]:
    """Generate niches for a single category in batches."""
    total_count = category["count"]
    num_batches = (total_count + BATCH_SIZE - 1) // BATCH_SIZE

    logger.info(f"Generating {total_count} niches for {category['name']} in {num_batches} batches...")

    all_candidates = []
    for batch_num in range(num_batches):
        batch_size = min(BATCH_SIZE, total_count - len(all_candidates))
        if batch_size <= 0:
            break

        logger.info(f"  Batch {batch_num + 1}/{num_batches} ({batch_size} niches)...")
        candidates = generate_batch(grok, category, batch_num, batch_size, existing)
        all_candidates.extend(candidates)
        logger.info(f"    Got {len(candidates)} unique niches (total: {len(all_candidates)})")

    logger.info(f"  Generated {len(all_candidates)} unique niches for {category['name']}")
    return all_candidates


def generate_all_niches(skip_existing: bool = True) -> list[NicheCandidate]:
    """Generate niches for all categories."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    grok = GrokClient()
    categories = load_seeds()

    # Load existing to dedupe
    existing = set()
    if skip_existing:
        candidates_file = DATA_DIR / "candidates.json"
        if candidates_file.exists():
            data = json.loads(candidates_file.read_text())
            existing = {c["niche_name"].lower() for c in data}
            logger.info(f"Loaded {len(existing)} existing candidates to skip")

    all_candidates = []
    for category in categories:
        candidates = generate_for_category(grok, category, existing)
        all_candidates.extend(candidates)

    # Save results
    output_path = DATA_DIR / "candidates.json"
    with open(output_path, "w") as f:
        json.dump([asdict(c) for c in all_candidates], f, indent=2)

    logger.info(f"Saved {len(all_candidates)} candidates to {output_path}")
    return all_candidates


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    candidates = generate_all_niches()
    print(f"\nGenerated {len(candidates)} niche candidates")
    print("\nSample niches:")
    for c in candidates[:10]:
        print(f"  - {c.niche_name} ({c.category})")
        print(f"    Subreddits: {', '.join(c.likely_subreddits)}")
