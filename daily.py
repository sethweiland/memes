#!/usr/bin/env python3
"""
Generate 5 memes for daily review.

Usage:
    python daily.py                  # Random topic from archives
    python daily.py "banjo memes"    # Specific topic
"""

import sys
from dotenv import load_dotenv

load_dotenv()

from src.config import load_domain
from src.core.pipeline import MemePipeline, PipelineConfig


def main():
    config = load_domain("bluegrass")
    pipeline = MemePipeline(config, PipelineConfig(
        num_concepts=20,
        num_images=5,
        creativity=1.2,
    ))

    if len(sys.argv) > 1:
        topic = sys.argv[1]
    else:
        try:
            topics = pipeline.rag.brainstorm_topics(
                seed_query="funny bluegrass",
                num_topics=1,
            )
            topic = topics[0]
        except Exception as e:
            print(f"Brainstorm failed ({e}), asking Grok for a topic...")
            from src.core.grok import GrokClient
            grok = GrokClient()
            response = grok._chat([
                {"role": "user", "content": (
                    f"Suggest ONE specific, funny meme topic about {config.display_name}. "
                    "Be creative and specific — pick a particular artist, instrument quirk, "
                    "festival moment, or genre debate. Just return the topic, nothing else."
                )}
            ], temperature=1.0)
            grok.close()
            topic = response.strip()
        print(f"Random topic: {topic}\n")

    result = pipeline.run(topic)
    print(f"\n5 memes ready in: {result.output_dir}")


if __name__ == "__main__":
    main()
