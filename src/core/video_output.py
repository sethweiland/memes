"""
Output helpers for the video ad pipeline.
Saves manifests, metadata, and prints summaries.
"""

import json
from pathlib import Path
from datetime import datetime

from .video_dataclasses import ComposedVideo


def save_video_manifest(result, output_dir: str):
    """Save video pipeline results manifest to JSON."""
    output_path = Path(output_dir) / "manifests"
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = result.timestamp.replace(":", "-")
    manifest_path = output_path / f"video_manifest_{timestamp}.json"

    # Build serializable dict
    manifest = {
        "timestamp": result.timestamp,
        "topic": result.topic,
        "concepts_generated": result.concepts_generated,
        "concepts_evaluated": result.concepts_evaluated,
        "videos_produced": result.videos_produced,
        "videos": result.videos,
        "cost_summary": result.cost_summary,
        "output_dir": result.output_dir,
    }

    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)

    print(f"\nManifest saved: {manifest_path}")


def save_video_metadata(videos: list[ComposedVideo]):
    """Save individual metadata files for each video."""
    for video in videos:
        if not video.output_path:
            continue

        video_path = Path(video.output_path)
        metadata_path = video_path.with_suffix('.txt')

        concept = video.concept
        scenes_text = ""
        for scene in concept.scenes:
            scenes_text += f"""
Scene {scene.scene_number} ({scene.duration_seconds}s):
  Visual: {scene.visual_prompt}
  Voiceover: {scene.voiceover_text}
  Text overlay: {scene.text_overlay or 'none'}
"""

        content = f"""VIDEO AD: {concept.title}
================================================================================

HOOK: {concept.hook}

SCENES:
{scenes_text}
CTA TEXT: {concept.cta_text}
CTA VOICEOVER: {concept.cta_voiceover}

--------------------------------------------------------------------------------
CONCEPT DETAILS:
Tone: {concept.tone}
Target audience: {concept.target_audience}
Why it works: {concept.explanation}

--------------------------------------------------------------------------------
PRODUCTION DETAILS:
Duration: {video.total_duration:.1f}s
Cost: ${video.total_cost:.2f}
Video file: {video.output_path}
Thumbnail: {video.thumbnail_path or 'N/A'}
"""

        with open(metadata_path, 'w') as f:
            f.write(content)

        print(f"  Metadata: {metadata_path}")


def print_video_summary(result, cost_summary: dict | None = None):
    """Print pipeline summary."""
    print(f"\n{'='*60}")
    print("VIDEO AD PIPELINE COMPLETE")
    print(f"{'='*60}")
    print(f"Topic: {result.topic}")
    print(f"Concepts generated: {result.concepts_generated}")
    print(f"Videos produced: {result.videos_produced}")

    if result.videos:
        print(f"\nPRODUCED VIDEOS:")
        for i, video in enumerate(result.videos, 1):
            print(f"\n  #{i} - {video['title']}")
            print(f"     Duration: {video['total_duration']:.1f}s")
            print(f"     Cost: ${video['total_cost']:.2f}")
            print(f"     File: {video['output_path']}")

    if cost_summary:
        print(f"\nCost summary: ${cost_summary.get('total_spent', 0):.2f} "
              f"/ ${cost_summary.get('max_budget', 0):.2f} budget")

    print(f"\nOutput directory: {result.output_dir}")
