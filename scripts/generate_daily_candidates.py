#!/usr/bin/env python3
"""
Generate daily meme candidates for human review.

Creates a batch of meme candidates with local paths, captions, rationale,
evaluation notes, scores, and optional grounding. Candidates are saved to
S3 ops/queue/daily-candidates/{date}.json plus a local cache. Nothing auto-posts.

Usage:
    python scripts/generate_daily_candidates.py                     # Generate default count (5)
    python scripts/generate_daily_candidates.py --count 10         # Generate 10 candidates
    python scripts/generate_daily_candidates.py --topic "banjos"   # Specific topic
    python scripts/generate_daily_candidates.py --domain bluegrass # Specific domain
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.config import load_domain
from src.core.daily_queue import (
    build_queue_document,
    candidate_from_evaluated,
    parse_topic_response,
    select_daily_candidates,
)
from src.core.grounding import GROUNDING_LIMIT, ground_evaluated, idea_rationale
from src.core.meme_assets import get_queue_storage, upload_meme_to_s3
from src.core.pipeline import MemePipeline, PipelineConfig, PipelineResult
from src.core.two_stage import TwoStagePipeline


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


DAILY_CANDIDATES_DIR = Path("data/daily_candidates")

# Extra concepts so the grounding gate can skip thin claims without emptying the batch.
# Still one generation call at default count (concepts_per_batch=10).
MAX_EXTRA_CONCEPTS = 3


def _suggest_topic(grok, display_name: str, topic: str | None) -> tuple[str, str]:
    """Return (topic, topic_rationale). One short LLM call."""
    if topic:
        response = grok._chat([
            {"role": "user", "content": (
                f"Topic: {topic}\n"
                f"In ONE short line, why would this be a timely or funny meme topic "
                f"today for {display_name}? Do not invent fake news. "
                "If it is evergreen, say so.\n\n"
                "Respond EXACTLY:\n"
                f"TOPIC: {topic}\n"
                "RATIONALE: one short line"
            )}
        ], temperature=0.4, max_tokens=120)
        parsed_topic, rationale = parse_topic_response(response)
        return topic, rationale or parsed_topic

    response = grok._chat([
        {"role": "user", "content": (
            f"Suggest ONE specific, funny meme topic about {display_name} that a real fan "
            "would recognize. Be creative and specific — pick a particular artist, "
            "instrument quirk, festival moment, or genre debate. Do not invent a fake "
            "news event.\n\n"
            "Respond EXACTLY:\n"
            "TOPIC: the topic\n"
            "RATIONALE: one short line on why this topic today (tour, viral clip, "
            "scene debate, seasonal calendar, or evergreen). Do not invent festival lore."
        )}
    ], temperature=1.0, max_tokens=150)
    parsed_topic, rationale = parse_topic_response(response)
    if not parsed_topic:
        parsed_topic = response.strip().split("\n")[0].strip()
    return parsed_topic, rationale


def generate_candidates(
    count: int = 5,
    domain: str = "bluegrass",
    topic: str = None,
    creativity: float = 1.2,
) -> dict:
    """
    Generate a batch of meme candidates with rationale, scores, and grounding.

    Args:
        count: Number of meme candidates to generate
        domain: Domain pack to use
        topic: Optional specific topic (random if not provided)
        creativity: Creativity parameter (0.5-2.0)

    Returns:
        dict with candidates metadata
    """
    logger.info(f"Generating {count} daily candidates for domain: {domain}")

    config = load_domain(domain)

    # Daily path: a few solid concepts from topic + model taste.
    # Skip RAG context (keep the code, just don't lean on it).
    pipeline = MemePipeline(config, PipelineConfig(
        num_concepts=count,
        num_images=count,
        num_context_chunks=0,
        expand_queries=False,
        creativity=creativity,
        generation_creativity=creativity,
    ))
    two_stage = TwoStagePipeline(pipeline)
    grok = pipeline.rag.grok

    topic, topic_rationale = _suggest_topic(grok, config.display_name, topic)
    logger.info(f"Topic: {topic}")
    if topic_rationale:
        logger.info(f"Topic rationale: {topic_rationale}")

    gen_count = min(count + MAX_EXTRA_CONCEPTS, GROUNDING_LIMIT)
    pipeline._fetch_current_events()
    template_catalog = pipeline.catalog.get_prompt_catalog(limit=50, randomize=True)
    context_text = pipeline.current_events_context or ""

    logger.info(f"Stage 1: generating {gen_count} concepts (target {count} after grounding)")
    memes = two_stage.generate_freely(
        topic=topic,
        context_text=context_text,
        template_catalog=template_catalog,
        num_ideas=gen_count,
    )
    logger.info(f"Stage 2: evaluating {len(memes)} concepts")
    evaluated = two_stage.evaluate_for_review(memes, context_text)

    try:
        logger.info("Grounding specific person/gear claims (bounded)")
        evaluated = ground_evaluated(grok, topic, evaluated, limit=min(GROUNDING_LIMIT, len(evaluated)))
    except Exception as exc:
        logger.warning(f"Grounding pass skipped: {exc}")

    selected = select_daily_candidates(evaluated, count)
    logger.info(f"Selected {len(selected)} of {len(evaluated)} after grounding gate")

    images = pipeline.generate_images_from_concepts(
        [item.idea for item in selected],
        num_images=len(selected),
    )

    eval_by_idea = {id(item.idea): item for item in selected}
    for img in images:
        ev = eval_by_idea.get(id(img.idea))
        if ev is None:
            continue
        img.evaluation_notes = ev.evaluation_notes or ""
        img.scores = ev.scores or {}
        img.overall_score = ev.overall_score
        img.grounding = ev.grounding
        img.score = ev.overall_score

    images = pipeline.generate_captions(images)

    timestamp = datetime.now().isoformat()
    top_memes = []
    for i, img in enumerate(images, start=1):
        ev = eval_by_idea.get(id(img.idea))
        top_memes.append({
            "rank": i,
            "index": i,
            "template": img.template.name,
            "top_text": img.idea.top_text,
            "bottom_text": img.idea.bottom_text,
            "image_url": img.image_url,
            "local_path": img.local_path,
            "caption": img.caption,
            "rationale": idea_rationale(img.idea),
            "evaluation_notes": img.evaluation_notes,
            "scores": img.scores or (ev.scores if ev else {}),
            "overall_score": round(img.overall_score, 1) if img.overall_score is not None else (
                round(ev.overall_score, 1) if ev else None
            ),
            "grounding": img.grounding or (ev.grounding if ev else None),
        })

    result = PipelineResult(
        timestamp=timestamp,
        topic=topic,
        concepts_generated=len(memes),
        concepts_evaluated=len(evaluated),
        images_generated=len(images),
        top_memes=top_memes,
        output_dir=pipeline.config.output_dir,
    )

    logger.info(f"Generated {result.images_generated} images in {result.output_dir}")

    return {
        "topic": topic,
        "topic_rationale": topic_rationale,
        "domain": domain,
        "result": result,
    }


def save_daily_candidates(
    candidates_data: dict,
    date_str: str = None,
) -> Path:
    """
    Save candidates to daily JSON file (S3 + local cache).
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    DAILY_CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DAILY_CANDIDATES_DIR / f"{date_str}.json"

    result = candidates_data["result"]
    created_at = datetime.now().isoformat(timespec="seconds")

    candidates = []
    for i, img in enumerate(result.top_memes, start=1):
        metadata = {}
        local_path = img.get("local_path") or img.get("filepath") or img.get("path") or ""
        if local_path:
            txt_path = Path(local_path).with_suffix(".txt")
            if txt_path.exists():
                metadata = _parse_metadata(txt_path)

        idx = img.get("index", i)

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

        candidate = candidate_from_evaluated(
            date_str=date_str,
            index=idx,
            img=img,
            evaluated=None,
            public_url=public_url,
            s3_key=s3_key,
            local_path=str(local_path),
            filename=Path(local_path).name if local_path else "",
            created_at=created_at,
            caption=img.get("caption") or metadata.get("caption", ""),
        )
        candidates.append(candidate)

    data = build_queue_document(
        date_str=date_str,
        topic=candidates_data["topic"],
        topic_rationale=candidates_data.get("topic_rationale", ""),
        domain=candidates_data["domain"],
        generated_at=created_at,
        output_dir=str(result.output_dir),
        candidates=candidates,
    )

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
        help="Number of candidates to generate (default: 5)"
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
        candidates_data = generate_candidates(
            count=args.count,
            domain=args.domain,
            topic=args.topic,
            creativity=args.creativity,
        )

        output_path = save_daily_candidates(
            candidates_data,
            date_str=args.date,
        )

        print(f"\n✅ Generated {len(candidates_data['result'].top_memes)} daily candidates")
        print(f"📁 Saved to: {output_path}")
        print(f"💡 Topic: {candidates_data['topic']}")
        if candidates_data.get("topic_rationale"):
            print(f"📝 Why today: {candidates_data['topic_rationale']}")
        print(f"\n🌐 Review at: http://localhost:5050/memes/gallery/daily-candidates/")

    except Exception as e:
        logger.error(f"Failed to generate daily candidates: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
