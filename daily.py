#!/usr/bin/env python3
"""
Generate 5 memes for daily review.

Usage:
    python daily.py                              # Random topic, default domain (bluegrass)
    python daily.py "banjo memes"                # Specific topic, default domain
    python daily.py --domain billsimmons         # Random topic, Bill Simmons domain
    python daily.py --domain billsimmons "Celtics homerism"  # Specific topic + domain
"""

import sys
import argparse
from dotenv import load_dotenv

load_dotenv()

from src.config import load_domain, list_domains
from src.core.pipeline import MemePipeline, PipelineConfig


# Default seed queries per domain for brainstorming
DOMAIN_SEED_QUERIES = {
    "bluegrass": "funny bluegrass",
    "billsimmons": "Bill Simmons podcast moments",
}


def main():
    parser = argparse.ArgumentParser(description="Generate memes for daily review")
    parser.add_argument("topic", nargs="?", help="Topic for meme generation")
    parser.add_argument("--domain", "-d", default="bluegrass",
                        help=f"Domain to use. Available: {list_domains()}")
    parser.add_argument("--num-concepts", "-n", type=int, default=20,
                        help="Number of concepts to generate")
    parser.add_argument("--num-images", "-i", type=int, default=5,
                        help="Number of images to generate")
    args = parser.parse_args()

    print(f"Loading domain: {args.domain}")
    config = load_domain(args.domain)

    pipeline = MemePipeline(config, PipelineConfig(
        num_concepts=args.num_concepts,
        num_images=args.num_images,
        creativity=1.2,
    ))

    if args.topic:
        topic = args.topic
    else:
        seed_query = DOMAIN_SEED_QUERIES.get(args.domain, f"funny {config.display_name}")
        topics = pipeline.rag.brainstorm_topics(
            seed_query=seed_query,
            num_topics=1,
        )
        topic = topics[0]
        print(f"Random topic: {topic}\n")

    result = pipeline.run(topic)
    print(f"\n{args.num_images} memes ready in: {result.output_dir}")


if __name__ == "__main__":
    main()
