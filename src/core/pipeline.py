"""
Meme generation pipeline.
Orchestrates: RAG retrieval -> bulk generation -> image creation
"""

from datetime import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .rag import DomainRAG, TokenBudgetExceeded
from .templates import TemplatesCatalog
from .evaluator import MemeEvaluator, ScoredMeme
from .meme_generator import MemeImageGenerator, GeneratedMeme
from .grok import MemeIdea
from .current_events import CurrentEventsSearch
from .output import save_manifest, save_meme_metadata, print_summary
from .two_stage import _format_context_text

if TYPE_CHECKING:
    from ..config.domain_config import DomainConfig


@dataclass
class PipelineConfig:
    """Configuration for the meme pipeline."""
    # Generation
    num_concepts: int = 100           # How many concepts to generate
    concepts_per_batch: int = 10      # Concepts per Grok call
    num_context_chunks: int = 5       # RAG context chunks per batch
    creativity: float = 1.0           # Temperature (0.0-1.5)

    # RAG
    expand_queries: bool = True       # Whether to expand search queries for better recall

    # Evaluation
    evaluate: bool = True             # Evaluate concepts before image generation
    min_score: float = 0.0            # Minimum score to keep a concept (0.0 = keep all)

    # Two-stage evaluation
    two_stage: bool = True            # Use two-stage generation (recommended)
    generation_creativity: float = 1.0  # Temperature for stage 1 (1.0 = balanced, 1.4 = high variance)
    eval_batch_size: int = 10         # Memes per evaluation call

    # Output
    num_to_review: int = 15           # How many to surface for human review
    num_images: int = 5               # Final images to generate (after human selection)
    output_dir: str = "output/memes"

    # Budget
    token_budget: int = 100000

    def __post_init__(self):
        """Validate configuration values."""
        if not 1 <= self.num_concepts <= 500:
            raise ValueError(f"num_concepts must be 1-500, got {self.num_concepts}")
        if not 1 <= self.concepts_per_batch <= 25:
            raise ValueError(f"concepts_per_batch must be 1-25, got {self.concepts_per_batch}")
        if not 0.0 <= self.creativity <= 2.0:
            raise ValueError(f"creativity must be 0.0-2.0, got {self.creativity}")
        if not 0.0 <= self.generation_creativity <= 2.0:
            raise ValueError(f"generation_creativity must be 0.0-2.0, got {self.generation_creativity}")
        if not 1 <= self.num_images <= 50:
            raise ValueError(f"num_images must be 1-50, got {self.num_images}")
        if self.token_budget is not None and self.token_budget < 1000:
            raise ValueError(f"token_budget must be >= 1000 or None, got {self.token_budget}")


# Backward-compatible re-export
from .two_stage import EvaluatedMeme  # noqa: E402


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
        self.current_events_context: str = ""

    def _get_generator(self) -> MemeImageGenerator:
        """Lazy-load image generator (requires imgflip creds)."""
        if self.generator is None:
            self.generator = MemeImageGenerator(output_dir=self.config.output_dir)
        return self.generator

    def _fetch_current_events(self):
        """Fetch current events context once per run."""
        try:
            searcher = CurrentEventsSearch(self.domain)
            self.current_events_context = searcher.get_current_events_context()
            if self.current_events_context:
                print("Current events context loaded")
            else:
                print("No current events context (disabled or no relevant news)")
        except Exception as e:
            print(f"Current events fetch failed: {e}")
            self.current_events_context = ""

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
        num_concepts = max(1, min(500, num_concepts))
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

            try:
                self.rag.budget.check(self.rag.budget.TOKENS_PER_MEME_GEN, "concept batch")
            except TokenBudgetExceeded:
                print(f"  Token budget exceeded after {len(all_concepts)} concepts — stopping generation")
                break

            context = self.rag.get_context(
                topic,
                k=self.config.num_context_chunks,
                expand_query=self.config.expand_queries,
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
        context_text = _format_context_text(context, self.current_events_context, max_chars=500)

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
        num_images = max(1, min(50, num_images))
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
            try:
                self.rag.budget.check(self.rag.budget.TOKENS_PER_CAPTION, "caption generation")
            except TokenBudgetExceeded:
                print(f"  Token budget exceeded — skipping remaining captions")
                break

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
                self.rag.budget.record(self.rag.budget.TOKENS_PER_CAPTION, "caption generation")
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

        # 0. Fetch current events
        self._fetch_current_events()

        # 1. Generate concepts
        concepts = self.generate_concepts(topic, num_concepts)

        # 2. Evaluate and rank (if enabled)
        concepts_evaluated = 0
        if self.config.evaluate and concepts:
            scored = self.evaluate_concepts(concepts)
            concepts_evaluated = len(scored)
            # Filter by min_score
            if self.config.min_score > 0:
                scored = [s for s in scored if s.overall_score >= self.config.min_score]
            # Use ranked order for image generation
            concepts = [s.idea for s in scored]

        # 3. Generate images
        images = self.generate_images_from_concepts(concepts, num_images)

        # 3. Generate captions
        images = self.generate_captions(images)

        # 4. Save metadata
        print("Saving metadata files...")
        save_meme_metadata(images)

        # 5. Build result
        result = PipelineResult(
            timestamp=timestamp,
            topic=topic,
            concepts_generated=len(concepts),
            concepts_evaluated=concepts_evaluated,
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

        save_manifest(result, self.config.output_dir)
        print_summary(result, self.rag.budget.summary())

        return result

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

    # =========================================================================
    # TWO-STAGE GENERATION — delegated to TwoStagePipeline
    # =========================================================================

    def run_two_stage(
        self,
        topic: str,
        num_concepts: int | None = None,
        num_to_review: int | None = None,
    ) -> list[EvaluatedMeme]:
        """
        Run two-stage generation: generate freely, then evaluate.
        Returns evaluated memes for human selection.

        Delegates to TwoStagePipeline.run().
        """
        from .two_stage import TwoStagePipeline
        return TwoStagePipeline(self).run(topic, num_concepts, num_to_review)

    def generate_selected(
        self,
        evaluated: list[EvaluatedMeme],
        indices: list[int],
    ) -> list[GeneratedMeme]:
        """
        Generate images for human-selected memes.

        Delegates to TwoStagePipeline.generate_selected().
        """
        from .two_stage import TwoStagePipeline
        return TwoStagePipeline(self).generate_selected(evaluated, indices)
