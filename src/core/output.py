"""
Output helpers for the meme pipeline.
Standalone functions for saving manifests, metadata, and printing summaries.
"""

import json
from pathlib import Path
from dataclasses import asdict

from .meme_generator import GeneratedMeme

if __name__ != "__main__":
    # Avoid circular imports — PipelineResult is only needed for type hints
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from .pipeline import PipelineResult


def save_manifest(result: "PipelineResult", output_dir: str):
    """Save results manifest to JSON."""
    output_path = Path(output_dir)
    manifest_path = output_path / f"manifest_{result.timestamp.replace(':', '-')}.json"

    with open(manifest_path, 'w') as f:
        json.dump(asdict(result), f, indent=2)

    print(f"\nManifest saved: {manifest_path}")


def save_meme_metadata(images: list[GeneratedMeme]):
    """Save individual metadata files for each meme."""
    for img in images:
        if not img.local_path:
            continue

        image_path = Path(img.local_path)
        metadata_path = image_path.with_suffix('.txt')

        idea = img.idea
        content = f"""MEME: {img.template.name}
================================================================================

TOP TEXT: {idea.top_text}
BOTTOM TEXT: {idea.bottom_text}

--------------------------------------------------------------------------------
WHY IT'S FUNNY (for your reference):
{idea.explanation}

--------------------------------------------------------------------------------
SOURCE/INSPIRATION:
{idea.source_quote if idea.source_quote else 'N/A'}

ARTIST(S) REFERENCED:
{idea.artist_reference if idea.artist_reference else 'N/A'}

--------------------------------------------------------------------------------
SUGGESTED CAPTION FOR POSTING:
{img.caption if img.caption else 'N/A'}

--------------------------------------------------------------------------------
IMAGE FILE: {img.local_path}
IMAGE URL: {img.image_url}
"""
        with open(metadata_path, 'w') as f:
            f.write(content)

        print(f"  Metadata: {metadata_path}")


def print_summary(result: "PipelineResult", token_summary: dict | None = None):
    """Print pipeline summary."""
    print(f"\n{'='*60}")
    print("PIPELINE COMPLETE")
    print(f"{'='*60}")
    print(f"Topic: {result.topic}")
    print(f"Concepts generated: {result.concepts_generated}")
    print(f"Images created: {result.images_generated}")
    print(f"\nGENERATED MEMES:")

    for meme in result.top_memes:
        print(f"\n  #{meme['rank']} - {meme['template']}")
        print(f"     Top: {meme['top_text'][:50]}...")
        print(f"     Bottom: {meme['bottom_text'][:50]}...")
        print(f"     File: {meme['local_path']}")
        if meme.get('caption'):
            print(f"     Caption: {meme['caption'][:100]}...")

    print(f"\nOutput directory: {result.output_dir}")
    if token_summary is not None:
        print(f"Token usage: {token_summary}")
