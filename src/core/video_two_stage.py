"""
Two-stage video ad generation pipeline (human-in-the-loop).
Stage 1: Generate and evaluate concepts (cheap).
Stage 2: Produce videos for human-selected concepts (expensive).

Follows the same pattern as GenericTwoStagePipeline for memes.
"""

from __future__ import annotations

from .grok import GrokClient
from .video_dataclasses import (
    VideoAdConcept,
    EvaluatedVideoAd,
    ComposedVideo,
)
from .video_concept_generator import VideoConceptGenerator
from .video_evaluator import VideoAdEvaluator, VIDEO_EVALUATION_CRITERIA
from .video_pipeline import VideoAdPipeline, VideoPipelineConfig
from .fallback_context import FallbackContextProvider


class VideoTwoStagePipeline:
    """
    Two-stage video ad generation with human review.

    Usage:
        config = VideoPipelineConfig(num_concepts=10, num_scenes=2)
        two_stage = VideoTwoStagePipeline(config=config)
        evaluated = two_stage.generate_and_evaluate("coffee brand ad")
        # Human reviews and picks indices...
        videos = two_stage.produce_selected(evaluated, [1, 3])
    """

    def __init__(
        self,
        pipeline: VideoAdPipeline | None = None,
        config: VideoPipelineConfig | None = None,
    ):
        self.pipeline = pipeline or VideoAdPipeline(config=config)
        self.config = self.pipeline.config

    def generate_concepts(
        self,
        topic: str,
        context_text: str = "",
        num_concepts: int | None = None,
        previously_covered: list[str] | None = None,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
    ) -> list[VideoAdConcept]:
        """
        Stage 1a: Generate video ad concepts.
        Uses web search or LLM knowledge for context (no RAG archive).
        """
        num_concepts = num_concepts or self.config.num_concepts

        # Get web context if none provided
        if not context_text:
            try:
                fallback = FallbackContextProvider()
                context_text = fallback.get_web_context(topic, max_results=5)
            except Exception:
                context_text = ""

        return self.pipeline.generate_concepts(
            topic=topic,
            context_text=context_text,
            num_concepts=num_concepts,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    def evaluate_concepts(
        self,
        concepts: list[VideoAdConcept],
        context_text: str = "",
        eval_prompt: str | None = None,
    ) -> list[EvaluatedVideoAd]:
        """Stage 1b: Evaluate and rank concepts."""
        return self.pipeline.evaluate_concepts(
            concepts,
            context_text=context_text,
            eval_prompt=eval_prompt,
        )

    def generate_and_evaluate(
        self,
        topic: str,
        context_text: str = "",
        num_concepts: int | None = None,
    ) -> list[EvaluatedVideoAd]:
        """
        Stage 1 combined: generate + evaluate.
        Returns evaluated concepts for human review.
        """
        num_concepts = num_concepts or self.config.num_concepts

        print(f"\n{'='*60}")
        print(f"VIDEO AD GENERATION: {topic}")
        print(f"{'='*60}")

        # Get web context
        if not context_text:
            print("Searching for context...")
            try:
                fallback = FallbackContextProvider()
                context_text = fallback.get_web_context(topic, max_results=5)
            except Exception as e:
                print(f"  Web search failed: {e}")
                context_text = ""

        # Generate concepts
        print(f"\nGenerating {num_concepts} concepts...")
        concepts = self.pipeline.generate_concepts(
            topic=topic,
            context_text=context_text,
            num_concepts=num_concepts,
        )

        # Evaluate
        print(f"\nEvaluating {len(concepts)} concepts...")
        evaluated = self.pipeline.evaluate_concepts(concepts, context_text)

        # Review
        self.review_candidates(evaluated)

        return evaluated

    def review_candidates(
        self,
        evaluated: list[EvaluatedVideoAd],
        num_to_review: int | None = None,
    ):
        """Present concepts for human review."""
        num_to_review = num_to_review or self.config.num_to_review
        to_show = evaluated[:num_to_review]

        print(f"\n{'='*60}")
        print(f"VIDEO AD CONCEPTS FOR REVIEW ({len(to_show)} of {len(evaluated)})")
        print(f"{'='*60}")

        for i, e in enumerate(to_show, 1):
            print(f"\n{'_'*50}")
            print(f"#{i} - {e.concept.title} (Score: {e.overall_score:.1f})")
            print(f"{'_'*50}")
            print(f"Hook: {e.concept.hook}")
            for scene in e.concept.scenes:
                print(f"  Scene {scene.scene_number} ({scene.duration_seconds}s):")
                print(f"    Visual: {scene.visual_prompt[:100]}...")
                print(f"    VO: {scene.voiceover_text[:80]}")
                if scene.text_overlay:
                    print(f"    Text: {scene.text_overlay}")
            print(f"CTA: {e.concept.cta_text}")
            print(f"Tone: {e.concept.tone} | Audience: {e.concept.target_audience}")

            print(f"\nScores:")
            for crit in VIDEO_EVALUATION_CRITERIA:
                score = e.scores.get(crit.name, 0)
                print(f"  {crit.display_name}: {score}/10")
            print(f"  Overall: {e.overall_score:.1f}/10")

            if e.evaluation_notes:
                print(f"Notes: {e.evaluation_notes}")

        print(f"\n{'='*60}")
        print("Pick which concepts to produce into videos.")
        print(f"{'='*60}")

    def produce_selected(
        self,
        evaluated: list[EvaluatedVideoAd],
        indices: list[int],
    ) -> list[ComposedVideo]:
        """
        Stage 2: Produce videos for human-selected concepts.
        This is the expensive step.

        Args:
            evaluated: List of evaluated concepts from generate_and_evaluate()
            indices: 1-based indices of concepts to produce
        """
        selected = [
            evaluated[i - 1].concept
            for i in indices
            if 0 < i <= len(evaluated)
        ]

        if not selected:
            print("No valid concepts selected.")
            return []

        print(f"\nProducing {len(selected)} video ads...")
        return self.pipeline.produce_videos(selected)
