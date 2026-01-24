"""
Daily meme generation pipeline.
Orchestrates: RAG retrieval → bulk generation → evaluation → image creation
"""

import json
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict

from .rag import BluegrassRAG
from .templates import TemplatesCatalog
from .evaluator import MemeEvaluator, ScoredMeme
from .meme_generator import MemeImageGenerator, GeneratedMeme
from .grok import MemeIdea


@dataclass
class PipelineConfig:
    """Configuration for the meme pipeline."""
    # Generation
    num_concepts: int = 100  # How many concepts to generate
    concepts_per_batch: int = 10  # Concepts per Grok call
    num_context_chunks: int = 5  # RAG context per batch
    creativity: float = 1.0  # 0.0-1.5, higher = more creative/risky jokes

    # Evaluation
    eval_batch_size: int = 10  # Memes per evaluation call

    # Output
    num_images: int = 5  # Final images to generate
    output_dir: str = "output/memes"

    # Token budget
    token_budget: int = 100000  # ~$0.02, plenty for 100 concepts


@dataclass
class PipelineResult:
    """Results from a pipeline run."""
    timestamp: str
    topic: str
    concepts_generated: int
    concepts_evaluated: int
    images_generated: int
    top_memes: list[dict]
    output_dir: str


class MemePipeline:
    """
    Full pipeline for daily meme generation.

    Usage:
        pipeline = MemePipeline()
        result = pipeline.run("banjo player stereotypes")
        # Images saved to output/memes/
    """

    def __init__(self, config: PipelineConfig | None = None):
        self.config = config or PipelineConfig()

        # Initialize components
        self.rag = BluegrassRAG(token_budget=self.config.token_budget)
        self.catalog = TemplatesCatalog()
        self.evaluator = MemeEvaluator()
        self.generator: MemeImageGenerator | None = None  # Lazy init

    def _get_generator(self) -> MemeImageGenerator:
        """Lazy-load image generator (requires imgflip creds)."""
        if self.generator is None:
            self.generator = MemeImageGenerator(output_dir=self.config.output_dir)
        return self.generator

    def generate_concepts(
        self,
        topic: str,
        num_concepts: int | None = None,
    ) -> list[MemeIdea]:
        """
        Generate many meme concepts using RAG + Grok.

        Args:
            topic: The meme topic/theme
            num_concepts: Override config.num_concepts

        Returns:
            List of MemeIdea objects
        """
        num_concepts = num_concepts or self.config.num_concepts
        concepts_per_batch = self.config.concepts_per_batch

        # Get template catalog for the prompt (randomly sample 50 from 1000+ templates)
        template_catalog = self.catalog.get_prompt_catalog(limit=50, randomize=True)

        all_concepts = []
        batches_needed = (num_concepts + concepts_per_batch - 1) // concepts_per_batch

        print(f"Generating {num_concepts} concepts in {batches_needed} batches...")

        for batch_num in range(batches_needed):
            remaining = num_concepts - len(all_concepts)
            batch_size = min(concepts_per_batch, remaining)

            if batch_size <= 0:
                break

            # Get fresh context for variety
            context = self.rag.get_context(
                topic,
                k=self.config.num_context_chunks,
            )

            # Generate with template awareness
            concepts = self._generate_batch(
                topic=topic,
                context=context,
                template_catalog=template_catalog,
                num_ideas=batch_size,
            )

            all_concepts.extend(concepts)
            print(f"  Batch {batch_num + 1}/{batches_needed}: {len(concepts)} concepts")

        print(f"Total concepts generated: {len(all_concepts)}")
        return all_concepts

    def _generate_batch(
        self,
        topic: str,
        context: list[dict],
        template_catalog: str,
        num_ideas: int,
    ) -> list[MemeIdea]:
        """Generate a batch of concepts with template awareness."""
        # Format context
        context_text = "\n\n".join([
            f"[{c['metadata'].get('source', 'Unknown')}]\n{c['text'][:500]}"
            for c in context
        ])

        system_prompt = """You are a comedy writer for bluegrass music memes.
Create memes that bluegrass fans will find hilarious - reference specific artists,
inside jokes, instrument stereotypes, and genre culture.

Be creative and go for unexpected angles, absurdist humor, and deep cuts.

IMPORTANT TONE GUIDELINES:
- Be affectionate and celebratory toward bluegrass legends, not mocking or negative
- Humor should come from love of the genre, not tearing anyone down
- It's OK to joke about quirks/personalities, but always with respect
- Think "laughing with" not "laughing at"
- Positive > negative energy

Write in normal internet English. Avoid overdoing dialect or apostrophes (don't write
"eyein'", "glarin'", "reckon", etc). Keep it natural and readable.
Ground humor in real facts/stories from the provided context."""

        user_prompt = f"""Topic: {topic}

CONTEXT FROM BLUEGRASS UNLIMITED ARCHIVES:
{context_text}

{template_catalog}

Generate {num_ideas} diverse meme concepts. Use different templates for variety.
Pick templates that best fit each joke's structure.

BE CREATIVE AND TAKE RISKS. Avoid obvious jokes. Go for unexpected humor.
TRY LESS COMMON TEMPLATES - don't just use Drake/Distracted Boyfriend every time!

Use this EXACT format for each (no markdown):

FORMAT: exact template name from list above
TOP_TEXT: the top text (for 2-box templates)
BOTTOM_TEXT: the bottom text (for 2-box templates)
EXPLANATION: why funny to bluegrass fans
SOURCE_QUOTE: quote/fact that inspired this
ARTIST_REFERENCE: artist(s) referenced

FOR MULTI-PANEL TEMPLATES (3+ boxes like Expanding Brain, Panik Kalm Panik, Gru's Plan):
- Put panel 1 in TOP_TEXT
- Put remaining panels in BOTTOM_TEXT, separated by " / "
- Example for Expanding Brain (4 boxes):
  TOP_TEXT: First level idea
  BOTTOM_TEXT: Second level / Third level / Fourth galaxy brain level

---

FORMAT: next template name...
"""

        response = self.rag.grok._chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], max_tokens=4000, temperature=self.config.creativity)

        return self.rag.grok._parse_meme_response(response)

    def evaluate_concepts(
        self,
        concepts: list[MemeIdea],
    ) -> list[ScoredMeme]:
        """
        Evaluate and rank all concepts.

        Args:
            concepts: List of meme concepts

        Returns:
            Sorted list of ScoredMeme (best first)
        """
        print(f"Evaluating {len(concepts)} concepts...")
        scored = self.evaluator.evaluate_batch(
            concepts,
            batch_size=self.config.eval_batch_size,
        )
        print(f"Evaluation complete. Top score: {scored[0].overall_score:.1f}")
        return scored

    def generate_images_from_concepts(
        self,
        concepts: list[MemeIdea],
        num_images: int | None = None,
    ) -> list[GeneratedMeme]:
        """
        Generate images directly from concepts (no evaluation step).

        Args:
            concepts: List of MemeIdea objects
            num_images: Number of images to generate

        Returns:
            List of GeneratedMeme with local file paths
        """
        num_images = num_images or self.config.num_images
        generator = self._get_generator()

        print(f"Generating {num_images} images...")
        generated = []

        for idea in concepts[:num_images]:
            try:
                meme = generator.generate(idea, download=True)
                generated.append(meme)
                print(f"  Generated: {meme.template.name}")
            except Exception as e:
                print(f"  Failed '{idea.format}': {e}")

        print(f"Generated {len(generated)} images")
        return generated

    def generate_captions(self, images: list[GeneratedMeme]) -> list[GeneratedMeme]:
        """
        Generate social media captions with historical context for each meme.

        Args:
            images: List of generated memes

        Returns:
            Same list with captions populated
        """
        print("Generating captions with historical context...")

        for img in images:
            idea = img.idea
            # Build context from the meme's explanation and source
            context = f"""
Meme: {idea.top_text} / {idea.bottom_text}
Why it's funny: {idea.explanation}
Source material: {idea.source_quote if idea.source_quote else 'N/A'}
Artist referenced: {idea.artist_reference if idea.artist_reference else 'N/A'}
"""
            prompt = f"""Write a short social media caption (2-3 sentences) that explains the historical context behind this bluegrass meme.

{context}

The caption should:
- Explain the real history that makes this funny
- Be educational but not dry
- Sound natural for Instagram/Twitter
- NOT include hashtags

Just write the caption, nothing else."""

            try:
                caption = self.rag.grok._chat([
                    {"role": "user", "content": prompt}
                ], max_tokens=200, temperature=0.7)
                img.caption = caption.strip()
            except Exception as e:
                print(f"  Caption failed for {img.template.name}: {e}")
                img.caption = idea.explanation  # Fallback to explanation

        print(f"Generated {len([i for i in images if i.caption])} captions")
        return images

    def run(
        self,
        topic: str,
        num_concepts: int | None = None,
        num_images: int | None = None,
    ) -> PipelineResult:
        """
        Run the full pipeline.

        Args:
            topic: Meme topic/theme
            num_concepts: Override number of concepts to generate
            num_images: Override number of final images

        Returns:
            PipelineResult with summary and file paths
        """
        timestamp = datetime.now().isoformat()
        print(f"\n{'='*60}")
        print(f"MEME PIPELINE: {topic}")
        print(f"{'='*60}\n")

        # 1. Generate concepts
        concepts = self.generate_concepts(topic, num_concepts)

        # 2. Generate images (take first N concepts - Grok-4 is good enough without eval)
        images = self.generate_images_from_concepts(concepts, num_images)

        # 3. Generate captions with historical context
        images = self.generate_captions(images)

        # 4. Save individual metadata files for each meme
        print("Saving metadata files...")
        self._save_meme_metadata(images)

        # 5. Save results
        result = PipelineResult(
            timestamp=timestamp,
            topic=topic,
            concepts_generated=len(concepts),
            concepts_evaluated=0,  # No longer using evaluator
            images_generated=len(images),
            top_memes=[
                {
                    "rank": i + 1,
                    "template": img.template.name,
                    "top_text": img.idea.top_text,
                    "bottom_text": img.idea.bottom_text,
                    "image_url": img.image_url,
                    "local_path": img.local_path,
                    "caption": img.caption,
                }
                for i, img in enumerate(images)
            ],
            output_dir=self.config.output_dir,
        )

        # Save manifest
        self._save_manifest(result)

        # Print summary
        self._print_summary(result)

        return result

    def _save_manifest(self, result: PipelineResult):
        """Save results manifest to JSON."""
        output_path = Path(self.config.output_dir)
        manifest_path = output_path / f"manifest_{result.timestamp.replace(':', '-')}.json"

        with open(manifest_path, 'w') as f:
            json.dump(asdict(result), f, indent=2)

        print(f"\nManifest saved: {manifest_path}")

    def _save_meme_metadata(self, images: list[GeneratedMeme]):
        """Save individual metadata files for each meme (for reviewing before posting)."""
        for img in images:
            if not img.local_path:
                continue

            # Create metadata file path (same as image but .txt)
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

    def _print_summary(self, result: PipelineResult):
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
        print(f"Token usage: {self.rag.budget.summary()}")

    def quick_test(self, topic: str) -> list[ScoredMeme]:
        """
        Quick test: generate 10 concepts, evaluate, but don't create images.
        Useful for testing without imgflip credentials.
        """
        print(f"Quick test: {topic}")

        # Generate just 10 concepts
        concepts = self.generate_concepts(topic, num_concepts=10)

        # Evaluate
        scored = self.evaluate_concepts(concepts)

        # Print top 5
        print("\nTop 5 concepts:")
        for i, s in enumerate(scored[:5], 1):
            print(f"\n{i}. {s.idea.format} (score: {s.overall_score:.1f})")
            print(f"   Top: {s.idea.top_text}")
            print(f"   Bottom: {s.idea.bottom_text}")
            print(f"   Scores: H={s.humor_score} A={s.authenticity_score} F={s.template_fit_score}")

        return scored


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    pipeline = MemePipeline()

    # Quick test without image generation
    pipeline.quick_test("banjo players being weird at jam sessions")
