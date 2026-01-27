"""
Meme generation pipeline.
Orchestrates: RAG retrieval -> bulk generation -> image creation
"""

import json
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import TYPE_CHECKING

from .rag import DomainRAG
from .templates import TemplatesCatalog
from .evaluator import MemeEvaluator, ScoredMeme
from .meme_generator import MemeImageGenerator, GeneratedMeme
from .grok import MemeIdea

if TYPE_CHECKING:
    from ..config.domain_config import DomainConfig


@dataclass
class PipelineConfig:
    """Configuration for the meme pipeline."""
    num_concepts: int = 100
    concepts_per_batch: int = 10
    num_context_chunks: int = 5
    creativity: float = 1.0

    eval_batch_size: int = 10

    num_images: int = 5
    output_dir: str = "output/memes"

    token_budget: int = 100000


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
    Full pipeline for domain-specific meme generation.

    Usage:
        from src.config import load_domain
        from src.core.pipeline import MemePipeline, PipelineConfig

        config = load_domain("bluegrass")
        pipeline = MemePipeline(config, PipelineConfig(num_concepts=15))
        result = pipeline.run("banjo player stereotypes")
    """

    def __init__(
        self,
        domain_config: "DomainConfig",
        config: PipelineConfig | None = None
    ):
        self.domain = domain_config
        self.config = config or PipelineConfig()

        # Initialize prompt templates
        from ..config.prompt_templates import PromptTemplates
        self.prompts = PromptTemplates(domain_config.prompts_dir, domain_config)

        # Initialize components
        self.rag = DomainRAG(domain_config, token_budget=self.config.token_budget)
        self.catalog = TemplatesCatalog()
        self.evaluator = MemeEvaluator()
        self.generator: MemeImageGenerator | None = None

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

        template_catalog = self.catalog.get_prompt_catalog(limit=50, randomize=True)

        all_concepts = []
        batches_needed = (num_concepts + concepts_per_batch - 1) // concepts_per_batch

        print(f"Generating {num_concepts} concepts in {batches_needed} batches...")

        for batch_num in range(batches_needed):
            remaining = num_concepts - len(all_concepts)
            batch_size = min(concepts_per_batch, remaining)

            if batch_size <= 0:
                break

            context = self.rag.get_context(
                topic,
                k=self.config.num_context_chunks,
            )

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

        # Use prompt templates if available
        if self.prompts.has_template("system_generation"):
            system_prompt = self.prompts.render("system_generation")
        else:
            # Fallback
            system_prompt = f"""You are a comedy writer for {self.domain.display_name.lower()} memes.
Create memes that {self.domain.display_name.lower()} fans will find hilarious.
Be creative and go for unexpected angles, absurdist humor, and deep cuts."""

        if self.prompts.has_template("user_generation"):
            user_prompt = self.prompts.render(
                "user_generation",
                topic=topic,
                context_text=context_text,
                template_catalog=template_catalog,
                num_ideas=num_ideas,
            )
        else:
            # Fallback
            user_prompt = f"""Topic: {topic}

CONTEXT FROM {self.domain.content_source_description.upper()}:
{context_text}

{template_catalog}

Generate {num_ideas} diverse meme concepts. Use different templates for variety.

Use this EXACT format for each (no markdown):

FORMAT: exact template name from list above
TOP_TEXT: the top text
BOTTOM_TEXT: the bottom text
EXPLANATION: why funny
SOURCE_QUOTE: quote/fact that inspired this
ARTIST_REFERENCE: artist(s) referenced

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
        Generate images directly from concepts.

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

            # Use prompt template if available
            if self.prompts.has_template("caption"):
                prompt = self.prompts.render(
                    "caption",
                    top_text=idea.top_text,
                    bottom_text=idea.bottom_text,
                    explanation=idea.explanation,
                    source_quote=idea.source_quote,
                    artist_reference=idea.artist_reference,
                )
            else:
                # Fallback
                context = f"""
Meme: {idea.top_text} / {idea.bottom_text}
Why it's funny: {idea.explanation}
Source material: {idea.source_quote if idea.source_quote else 'N/A'}
Artist referenced: {idea.artist_reference if idea.artist_reference else 'N/A'}
"""
                prompt = f"""Write a short social media caption (2-3 sentences) that explains the historical context behind this {self.domain.display_name.lower()} meme.

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
                img.caption = idea.explanation

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

        # 2. Generate images
        images = self.generate_images_from_concepts(concepts, num_images)

        # 3. Generate captions
        images = self.generate_captions(images)

        # 4. Save metadata
        print("Saving metadata files...")
        self._save_meme_metadata(images)

        # 5. Build result
        result = PipelineResult(
            timestamp=timestamp,
            topic=topic,
            concepts_generated=len(concepts),
            concepts_evaluated=0,
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

        self._save_manifest(result)
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
        """
        print(f"Quick test: {topic}")

        concepts = self.generate_concepts(topic, num_concepts=10)
        scored = self.evaluate_concepts(concepts)

        print("\nTop 5 concepts:")
        for i, s in enumerate(scored[:5], 1):
            print(f"\n{i}. {s.idea.format} (score: {s.overall_score:.1f})")
            print(f"   Top: {s.idea.top_text}")
            print(f"   Bottom: {s.idea.bottom_text}")
            print(f"   Scores: H={s.humor_score} A={s.authenticity_score} F={s.template_fit_score}")

        return scored
