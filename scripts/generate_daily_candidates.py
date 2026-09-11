#!/usr/bin/env python3
"""
Generate daily meme candidates for human review.

Creates a batch of meme candidates with local paths, captions, and metadata.
Candidates are saved to data/daily_candidates/{date}.json with status=pending.

Usage:
    python scripts/generate_daily_candidates.py                     # Generate default count (5)
    python scripts/generate_daily_candidates.py --count 10         # Generate 10 candidates
    python scripts/generate_daily_candidates.py --topic "banjos"   # Specific topic
    python scripts/generate_daily_candidates.py --domain bluegrass # Specific domain
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.config import load_domain
from src.core.pipeline import MemePipeline, PipelineConfig
from src.core.meme_assets import upload_meme_to_s3, get_queue_storage


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


DAILY_CANDIDATES_DIR = Path("data/daily_candidates")


def generate_candidates(
    count: int = 5,
    domain: str = "bluegrass",
    topic: str = None,
    creativity: float = 1.2,
) -> dict:
    """
    Generate a batch of meme candidates.
    
    Args:
        count: Number of meme candidates to generate
        domain: Domain pack to use
        topic: Optional specific topic (random if not provided)
        creativity: Creativity parameter (0.5-2.0)
    
    Returns:
        dict with candidates metadata
    """
    logger.info(f"Generating {count} daily candidates for domain: {domain}")
    
    # Load domain config
    config = load_domain(domain)
    
    # Daily path: a few solid concepts from topic + model taste.
    # Skip RAG context (keep the code, just don't lean on it).
    pipeline = MemePipeline(config, PipelineConfig(
        num_concepts=count,
        num_images=count,
        num_context_chunks=0,
        expand_queries=False,
        creativity=creativity,
    ))
    
    # Determine topic from Grok general knowledge (not RAG brainstorm)
    if topic is None:
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
    
    logger.info(f"Topic: {topic}")
    
    # Generate memes
    result = pipeline.run(topic)
    
    logger.info(f"Generated {result.images_generated} images in {result.output_dir}")
    
    return {
        "topic": topic,
        "domain": domain,
        "result": result,
    }


def save_daily_candidates(
    candidates_data: dict,
    date_str: str = None,
) -> Path:
    """
    Save candidates to daily JSON file.
    
    Args:
        candidates_data: Output from generate_candidates()
        date_str: Date string (YYYY-MM-DD), defaults to today
    
    Returns:
        Path to saved JSON file
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    DAILY_CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DAILY_CANDIDATES_DIR / f"{date_str}.json"
    
    result = candidates_data["result"]
    
    # Build candidate records and upload to S3
    candidates = []
    for i, img in enumerate(result.top_memes, start=1):
        # Get metadata from .txt file if available
        metadata = {}
        local_path = img.get("local_path") or img.get("filepath") or img.get("path") or ""
        if local_path:
            txt_path = Path(local_path).with_suffix(".txt")
            if txt_path.exists():
                metadata = _parse_metadata(txt_path)

        idx = img.get("index", i)
        
        # Upload image to S3
        public_url = None
        s3_key = None
        if local_path and Path(local_path).is_file():
            filename = Path(local_path).name
            logger.info(f"Uploading candidate #{idx} to S3: {filename}")
            try:
                upload_result = upload_meme_to_s3(local_path, filename)
                if upload_result.success:
                    public_url = upload_result.public_url
                    s3_key = upload_result.s3_key
                    logger.info(f"✅ Uploaded to S3: {public_url}")
                else:
                    logger.warning(f"⚠️ S3 upload failed for {filename}: {upload_result.error}")
            except Exception as e:
                logger.warning(f"⚠️ S3 upload exception for {filename}: {e}")
        
        candidate = {
            "id": f"{date_str}_{idx}",
            "index": idx,
            "template": img.get("template") or img.get("format") or img.get("name", "Unknown"),
            "top_text": img.get("top_text", ""),
            "bottom_text": img.get("bottom_text", ""),
            "caption": img.get("caption") or metadata.get("caption", ""),
            "public_url": public_url,
            "s3_key": s3_key,
            "local_path": str(local_path),
            "filename": Path(local_path).name if local_path else "",
            "status": "pending",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "scores": img.get("scores", {}),
            "overall_score": img.get("overall_score"),
        }
        candidates.append(candidate)
    
    # Save to JSON (S3 + local)
    data = {
        "date": date_str,
        "topic": candidates_data["topic"],
        "domain": candidates_data["domain"],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "output_dir": str(result.output_dir),
        "total_count": len(candidates),
        "candidates": candidates,
    }
    
    # Save to S3 and local via queue storage
    queue_storage = get_queue_storage()
    saved_to_s3 = queue_storage.save(date_str, data)
    
    if saved_to_s3:
        logger.info(f"Saved {len(candidates)} candidates to S3 and local cache")
    else:
        logger.info(f"Saved {len(candidates)} candidates to local cache only")
    
    return output_path


def _parse_metadata(txt_path: Path) -> dict:
    """Parse meme .txt metadata file."""
    text = txt_path.read_text(errors="replace")
    data = {}
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("SUGGESTED CAPTION FOR POSTING:"):
            data["caption"] = line.split(":", 1)[1].strip()
    return data


def main():
    parser = argparse.ArgumentParser(
        description="Generate daily meme candidates for human review"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="Number of candidates to generate (default: 10)"
    )
    parser.add_argument(
        "--domain",
        default="bluegrass",
        help="Domain pack to use (default: bluegrass)"
    )
    parser.add_argument(
        "--topic",
        help="Specific topic (random if not provided)"
    )
    parser.add_argument(
        "--creativity",
        type=float,
        default=1.2,
        help="Creativity parameter 0.5-2.0 (default: 1.2)"
    )
    parser.add_argument(
        "--date",
        help="Date for candidates YYYY-MM-DD (default: today)"
    )
    
    args = parser.parse_args()
    
    try:
        # Generate candidates
        candidates_data = generate_candidates(
            count=args.count,
            domain=args.domain,
            topic=args.topic,
            creativity=args.creativity,
        )
        
        # Save to daily file
        output_path = save_daily_candidates(
            candidates_data,
            date_str=args.date,
        )
        
        print(f"\n✅ Generated {args.count} daily candidates")
        print(f"📁 Saved to: {output_path}")
        print(f"💡 Topic: {candidates_data['topic']}")
        print(f"\n🌐 Review at: http://localhost:5050/memes/gallery/daily-candidates/")
        
    except Exception as e:
        logger.error(f"Failed to generate daily candidates: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
