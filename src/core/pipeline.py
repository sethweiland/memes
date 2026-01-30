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
    # Generation
    num_concepts: int = 100           # How many concepts to generate
    concepts_per_batch: int = 10      # Concepts per Grok call
    num_context_chunks: int = 5       # RAG context chunks per batch
    creativity: float = 1.0           # Temperature (0.0-1.5)

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


@dataclass
class EvaluatedMeme:
    """A meme with evaluation scores for human review."""
    idea: MemeIdea
    scores: dict[str, int]        # Criterion name -> score (1-10)
    overall_score: float          # Weighted combination
    evaluation_notes: str         # AI's notes on the meme
    is_absurdist: bool = False    # Flag for intentional absurdism

    def get_score(self, criterion: str) -> int:
        """Get score for a specific criterion."""
        return self.scores.get(criterion, 0)

    def to_dict(self) -> dict:
        result = {
            "format": self.idea.format,
            "top_text": self.idea.top_text,
            "bottom_text": self.idea.bottom_text,
            "overall_score": self.overall_score,
            "evaluation_notes": self.evaluation_notes,
            "is_absurdist": self.is_absurdist,
        }
        # Add individual scores
        result.update(self.scores)
        return result


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

    # =========================================================================
    # TWO-STAGE GENERATION (human-in-the-loop)
    # =========================================================================

    def generate_freely(
        self,
        topic: str,
        context_text: str,
        template_catalog: str,
        num_ideas: int = 10,
    ) -> list[MemeIdea]:
        """
        Stage 1: Generate memes WITHOUT explanation requirement.
        Higher creativity, no justification needed = more unexpected ideas.
        """
        # Use prompt template if available
        if self.prompts.has_template("system_generation_free"):
            system_prompt = self.prompts.render("system_generation_free")
        else:
            system_prompt = f"""You are a comedy writer for {self.domain.display_name.lower()} memes.
Be weird, unexpected, creative. Take risks. No explanations needed - just write funny memes."""

        if self.prompts.has_template("user_generation_free"):
            user_prompt = self.prompts.render(
                "user_generation_free",
                topic=topic,
                context_text=context_text,
                template_catalog=template_catalog,
                num_ideas=num_ideas,
            )
        else:
            user_prompt = f"""Topic: {topic}

CONTEXT FROM {self.domain.content_source_description.upper()}:
{context_text}

{template_catalog}

Generate {num_ideas} memes. Be creative, unexpected, absurdist. Take risks.
DON'T explain why they're funny - just write them.

Use EXACT format:

FORMAT: template name
TOP_TEXT: top text
BOTTOM_TEXT: bottom text

---

FORMAT: next template..."""

        response = self.rag.grok._chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], max_tokens=2000, temperature=self.config.generation_creativity)

        return self.rag.grok._parse_meme_response(response)

    def evaluate_for_review(
        self,
        memes: list[MemeIdea],
        context_text: str,
    ) -> list[EvaluatedMeme]:
        """
        Stage 2: Evaluate memes using domain-specific criteria.
        Returns ALL memes with scores - human makes final selection.
        """
        if not memes:
            return []

        # Build meme list for evaluation
        meme_list = ""
        for i, m in enumerate(memes, 1):
            meme_list += f"""
MEME {i}:
Template: {m.format}
Top: {m.top_text}
Bottom: {m.bottom_text}
"""

        # Get evaluation criteria from domain config
        criteria_section = self.domain.get_evaluation_prompt_section()

        # Build response format based on criteria
        criteria_names = [c.name.upper() for c in self.domain.evaluation_criteria]
        score_format = " ".join([f"{name}=X" for name in criteria_names])

        prompt = f"""You are evaluating {self.domain.display_name.lower()} memes. Score each on these criteria:

{criteria_section}

CONTEXT (use this to verify accuracy):
{context_text}

MEMES TO EVALUATE:
{meme_list}

For each meme, respond with:
MEME 1: {score_format}
NOTES: Brief note on why it works (or doesn't)

MEME 2: {score_format}
NOTES: ...

Be STRICT on accuracy criteria. If a fact is made up, score it low."""

        response = self.rag.grok._chat([
            {"role": "user", "content": prompt}
        ], max_tokens=2000, temperature=0.3)

        return self._parse_evaluations(memes, response)

    def _parse_evaluations(
        self,
        memes: list[MemeIdea],
        response: str,
    ) -> list[EvaluatedMeme]:
        """Parse evaluation response into EvaluatedMeme objects."""
        evaluated = []
        lines = response.strip().split('\n')

        current_idx = None
        current_scores: dict[str, int] = {}
        current_notes = ""

        # Get criterion names from domain config
        criterion_names = {c.name.upper(): c.name for c in self.domain.evaluation_criteria}

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.upper().startswith("MEME "):
                # Save previous
                if current_idx is not None and current_scores:
                    evaluated.append(self._create_evaluated_meme(
                        memes[current_idx] if current_idx < len(memes) else None,
                        current_scores,
                        current_notes
                    ))

                # Parse new meme scores
                try:
                    parts = line.split(":", 1)
                    meme_num = int(parts[0].replace("MEME", "").strip()) - 1
                    current_idx = meme_num
                    current_scores = {}
                    current_notes = ""

                    score_part = parts[1] if len(parts) > 1 else ""

                    # Parse scores for each criterion
                    for upper_name, actual_name in criterion_names.items():
                        if upper_name + "=" in score_part.upper():
                            idx = score_part.upper().find(upper_name + "=")
                            val_str = score_part[idx + len(upper_name) + 1:].split()[0]
                            val_str = ''.join(c for c in val_str if c.isdigit())
                            if val_str:
                                current_scores[actual_name] = int(val_str)
                except (ValueError, IndexError):
                    continue

            elif line.upper().startswith("NOTES:"):
                current_notes = line.split(":", 1)[1].strip() if ":" in line else ""

        # Don't forget last one
        if current_idx is not None and current_scores:
            evaluated.append(self._create_evaluated_meme(
                memes[current_idx] if current_idx < len(memes) else None,
                current_scores,
                current_notes
            ))

        # Sort by overall score
        evaluated = [e for e in evaluated if e is not None]
        evaluated.sort(key=lambda x: x.overall_score, reverse=True)

        return evaluated

    def _create_evaluated_meme(
        self,
        meme: MemeIdea | None,
        scores: dict[str, int],
        notes: str,
    ) -> EvaluatedMeme | None:
        """Create EvaluatedMeme from parsed scores."""
        if meme is None:
            return None

        # Calculate overall score using domain config
        overall = self.domain.calculate_overall_score(scores)

        # Check for absurdism
        is_absurdist = self.domain.is_potential_absurdism(scores)

        return EvaluatedMeme(
            idea=meme,
            scores=scores,
            overall_score=overall,
            evaluation_notes=notes,
            is_absurdist=is_absurdist,
        )

    def review_candidates(
        self,
        evaluated: list[EvaluatedMeme],
        num_to_review: int | None = None,
    ) -> None:
        """
        Present memes for human review.
        Shows scores as guidance but emphasizes human decision-making.
        """
        num_to_review = num_to_review or self.config.num_to_review
        to_show = evaluated[:num_to_review]

        print(f"\n{'='*70}")
        print(f"MEMES FOR HUMAN REVIEW ({len(to_show)} of {len(evaluated)})")
        print("Scores are guidance - YOU make the final call!")
        print(f"{'='*70}")

        for i, e in enumerate(to_show, 1):
            print(f"\n{'─'*60}")
            print(f"#{i} - {e.idea.format}")
            print(f"{'─'*60}")
            print(f"Top: {e.idea.top_text}")
            print(f"Bottom: {e.idea.bottom_text}")

            print(f"\n📊 SCORES:")
            for crit in self.domain.evaluation_criteria:
                score = e.scores.get(crit.name, 0)
                note = ""
                if crit.low_score_note and score < 4:
                    note = f" ⚠️ ({crit.low_score_note})"
                print(f"   {crit.display_name}: {score}/10{note}")

            print(f"   Overall: {e.overall_score:.1f}/10")
            print(f"\n📝 AI Notes: {e.evaluation_notes}")

            if e.is_absurdist:
                print(f"\n🎭 NOTE: Low accuracy but decent humor - might be intentional absurdism!")

        print(f"\n{'='*70}")
        print("HUMAN DECISION TIME")
        print(f"{'='*70}")
        print("Review the memes above. Pick which ones to generate images for.")
        print("Intentionally absurd memes (low accuracy, high humor) might still be great!")

    def run_two_stage(
        self,
        topic: str,
        num_concepts: int | None = None,
        num_to_review: int | None = None,
    ) -> list[EvaluatedMeme]:
        """
        Run two-stage generation: generate freely, then evaluate.
        Returns evaluated memes for human selection.

        Args:
            topic: Meme topic/theme
            num_concepts: Override number of concepts to generate
            num_to_review: Override number to surface for review

        Returns:
            List of EvaluatedMeme for human review
        """
        num_concepts = num_concepts or self.config.num_concepts
        num_to_review = num_to_review or self.config.num_to_review

        print(f"\n{'='*70}")
        print(f"TWO-STAGE MEME GENERATION: {topic}")
        print(f"{'='*70}")

        # Get context
        context = self.rag.get_context(topic, k=self.config.num_context_chunks)
        context_text = "\n\n".join([
            f"[{c['metadata'].get('source', 'Unknown')}]\n{c['text'][:600]}"
            for c in context
        ])

        template_catalog = self.catalog.get_prompt_catalog(limit=50, randomize=True)

        # Stage 1: Generate freely
        print(f"\n{'='*70}")
        print("STAGE 1: FREE GENERATION (no explanation required)")
        print(f"{'='*70}")

        all_memes = []
        batches_needed = (num_concepts + self.config.concepts_per_batch - 1) // self.config.concepts_per_batch

        for batch_num in range(batches_needed):
            remaining = num_concepts - len(all_memes)
            batch_size = min(self.config.concepts_per_batch, remaining)
            if batch_size <= 0:
                break

            memes = self.generate_freely(
                topic=topic,
                context_text=context_text,
                template_catalog=template_catalog,
                num_ideas=batch_size,
            )
            all_memes.extend(memes)
            print(f"  Batch {batch_num + 1}/{batches_needed}: {len(memes)} memes")

        print(f"\nGenerated {len(all_memes)} memes")

        # Stage 2: Evaluate
        print(f"\n{'='*70}")
        print("STAGE 2: EVALUATION (scores as guidance, not filter)")
        print(f"{'='*70}")

        evaluated = self.evaluate_for_review(all_memes, context_text)
        print(f"Evaluated {len(evaluated)} memes")

        # Present for review
        self.review_candidates(evaluated, num_to_review)

        return evaluated

    def generate_selected(
        self,
        evaluated: list[EvaluatedMeme],
        indices: list[int],
    ) -> list[GeneratedMeme]:
        """
        Generate images for human-selected memes.

        Args:
            evaluated: List of evaluated memes from run_two_stage
            indices: 1-based indices of memes to generate (from review_candidates output)

        Returns:
            List of GeneratedMeme with local file paths
        """
        selected = [evaluated[i - 1].idea for i in indices if 0 < i <= len(evaluated)]

        if not selected:
            print("No valid memes selected.")
            return []

        print(f"\nGenerating {len(selected)} selected memes...")
        return self.generate_images_from_concepts(selected, num_images=len(selected))
