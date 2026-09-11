"""
Video ad generation pipeline.
Orchestrates: context retrieval -> concept generation -> evaluation ->
human review -> video generation -> TTS -> composition.
"""

from dataclasses import dataclass, field
from datetime import datetime

from .grok import GrokClient
from .video_dataclasses import (
    VideoAdConcept,
    EvaluatedVideoAd,
    GeneratedClip,
    GeneratedVoiceover,
    ComposedVideo,
    CostTracker,
    BudgetExceeded,
)
from .video_concept_generator import VideoConceptGenerator
from .video_evaluator import VideoAdEvaluator, VIDEO_EVALUATION_CRITERIA
from .video_providers import VideoProvider, get_provider
from .tts_provider import TTSProvider, get_tts_provider
from .video_composer import VideoComposer


@dataclass
class VideoPipelineConfig:
    """Configuration for the video ad pipeline."""
    # Generation
    num_concepts: int = 10
    concepts_per_batch: int = 5
    num_scenes: int = 2                 # Scenes per video (1-3)
    target_duration: float = 7.0        # Target video duration (5-10s)
    creativity: float = 1.0

    # Providers
    video_provider: str = "kling"
    tts_provider: str = "elevenlabs"    # "elevenlabs" or "none"
    tts_voice_id: str = "default"

    # Evaluation
    num_to_review: int = 10
    num_to_produce: int = 3
    eval_batch_size: int = 5

    # Output
    output_dir: str = "output/videos"
    aspect_ratio: str = "9:16"          # Vertical for social ads

    # Budget
    max_video_cost: float = 5.0         # Max spend per pipeline run in USD

    # Audio
    background_music_path: str | None = None
    music_volume: float = 0.15

    def __post_init__(self):
        if not 1 <= self.num_concepts <= 100:
            raise ValueError(f"num_concepts must be 1-100, got {self.num_concepts}")
        if not 1 <= self.num_scenes <= 3:
            raise ValueError(f"num_scenes must be 1-3, got {self.num_scenes}")
        if not 5.0 <= self.target_duration <= 10.0:
            raise ValueError(f"target_duration must be 5.0-10.0, got {self.target_duration}")
        if not 0.0 <= self.creativity <= 2.0:
            raise ValueError(f"creativity must be 0.0-2.0, got {self.creativity}")


@dataclass
class VideoPipelineResult:
    """Results from a video pipeline run."""
    timestamp: str
    topic: str
    concepts_generated: int
    concepts_evaluated: int
    videos_produced: int
    videos: list[dict]
    output_dir: str
    cost_summary: dict = field(default_factory=dict)


class VideoAdPipeline:
    """
    Full pipeline for video ad creative generation.

    Usage:
        config = VideoPipelineConfig(num_concepts=10, num_scenes=2)
        pipeline = VideoAdPipeline(config=config)
        # Stage 1: generate concepts
        concepts = pipeline.generate_concepts("coffee brand ad")
        evaluated = pipeline.evaluate_concepts(concepts)
        # Human selects which to produce...
        # Stage 2: produce videos
        videos = pipeline.produce_videos([evaluated[0].concept, evaluated[2].concept])
    """

    def __init__(self, config: VideoPipelineConfig | None = None):
        self.config = config or VideoPipelineConfig()
        self.cost_tracker = CostTracker(max_budget=self.config.max_video_cost)

        # Lazy-loaded components
        self._grok: GrokClient | None = None
        self._concept_gen: VideoConceptGenerator | None = None
        self._evaluator: VideoAdEvaluator | None = None
        self._video_provider: VideoProvider | None = None
        self._tts_provider: TTSProvider | None = None
        self._composer: VideoComposer | None = None

    @property
    def grok(self) -> GrokClient:
        if self._grok is None:
            self._grok = GrokClient()
        return self._grok

    @property
    def concept_generator(self) -> VideoConceptGenerator:
        if self._concept_gen is None:
            self._concept_gen = VideoConceptGenerator(self.grok)
        return self._concept_gen

    @property
    def evaluator(self) -> VideoAdEvaluator:
        if self._evaluator is None:
            self._evaluator = VideoAdEvaluator()
        return self._evaluator

    @property
    def video_provider(self) -> VideoProvider:
        if self._video_provider is None:
            self._video_provider = get_provider(self.config.video_provider)
        return self._video_provider

    @property
    def tts_provider(self) -> TTSProvider | None:
        if self.config.tts_provider == "none":
            return None
        if self._tts_provider is None:
            self._tts_provider = get_tts_provider(self.config.tts_provider)
        return self._tts_provider

    @property
    def composer(self) -> VideoComposer:
        if self._composer is None:
            self._composer = VideoComposer(
                output_dir=f"{self.config.output_dir}/final"
            )
        return self._composer

    def generate_concepts(
        self,
        topic: str,
        context_text: str = "",
        num_concepts: int | None = None,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
    ) -> list[VideoAdConcept]:
        """Generate video ad concepts in batches."""
        num_concepts = num_concepts or self.config.num_concepts
        all_concepts = []
        batches_needed = (num_concepts + self.config.concepts_per_batch - 1) // self.config.concepts_per_batch

        print(f"Generating {num_concepts} video ad concepts in {batches_needed} batches...")

        for batch_num in range(batches_needed):
            remaining = num_concepts - len(all_concepts)
            batch_size = min(self.config.concepts_per_batch, remaining)
            if batch_size <= 0:
                break

            concepts = self.concept_generator.generate_concepts(
                topic=topic,
                context_text=context_text,
                num_concepts=batch_size,
                num_scenes=self.config.num_scenes,
                target_duration=self.config.target_duration,
                creativity=self.config.creativity,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            all_concepts.extend(concepts)
            print(f"  Batch {batch_num + 1}/{batches_needed}: {len(concepts)} concepts")

        print(f"Total concepts generated: {len(all_concepts)}")
        return all_concepts

    def evaluate_concepts(
        self,
        concepts: list[VideoAdConcept],
        context_text: str = "",
        eval_prompt: str | None = None,
    ) -> list[EvaluatedVideoAd]:
        """Evaluate and rank concepts."""
        print(f"Evaluating {len(concepts)} concepts...")
        evaluated = self.evaluator.evaluate_batch(
            concepts,
            context_text=context_text,
            batch_size=self.config.eval_batch_size,
            eval_prompt=eval_prompt,
        )
        if evaluated:
            print(f"Evaluation complete. Top score: {evaluated[0].overall_score:.1f}")
        return evaluated

    def produce_videos(
        self,
        concepts: list[VideoAdConcept],
    ) -> list[ComposedVideo]:
        """
        Produce final videos for the given concepts.
        This is the expensive step — video gen + TTS + composition.
        """
        produced = []

        for i, concept in enumerate(concepts):
            print(f"\nProducing video {i + 1}/{len(concepts)}: {concept.title}")

            try:
                video = self._produce_single(concept)
                produced.append(video)
                print(f"  Done: {video.output_path} (${video.total_cost:.2f})")
            except BudgetExceeded as e:
                print(f"  Budget exceeded: {e}")
                print(f"  Stopping production. {len(produced)} videos completed.")
                break
            except Exception as e:
                print(f"  Failed to produce '{concept.title}': {e}")

        return produced

    def _produce_single(self, concept: VideoAdConcept) -> ComposedVideo:
        """Produce a single video ad."""
        # 1. Generate video clips for each scene
        clips = []
        for scene in concept.scenes:
            # Check budget before expensive API call
            estimated_cost = scene.duration_seconds * self.video_provider.cost_per_second
            self.cost_tracker.check(estimated_cost, f"video clip scene {scene.scene_number}")

            import time
            start = time.time()

            local_path, cost = self.video_provider.generate_clip(
                prompt=scene.visual_prompt,
                duration_seconds=scene.duration_seconds,
                aspect_ratio=self.config.aspect_ratio,
            )

            gen_time = time.time() - start
            self.cost_tracker.record(cost, "video_clip", self.video_provider.name)

            clips.append(GeneratedClip(
                scene=scene,
                video_path=local_path,
                provider=self.video_provider.name,
                generation_cost=cost,
                generation_time=gen_time,
            ))

        # 2. Generate per-scene voiceovers for proper sync
        scene_voiceovers: list[GeneratedVoiceover | None] = []
        if self.tts_provider:
            for scene in concept.scenes:
                if scene.voiceover_text.strip():
                    try:
                        audio_path, duration = self.tts_provider.synthesize(
                            scene.voiceover_text,
                            voice_id=self.config.tts_voice_id,
                        )
                        scene_voiceovers.append(GeneratedVoiceover(
                            text=scene.voiceover_text,
                            audio_path=audio_path,
                            duration_seconds=duration,
                            voice_id=self.config.tts_voice_id,
                        ))
                    except Exception as e:
                        print(f"  Voiceover failed for scene {scene.scene_number}: {e}")
                        scene_voiceovers.append(None)
                else:
                    scene_voiceovers.append(None)

            # Generate CTA voiceover separately
            cta_voiceover = None
            if concept.cta_voiceover.strip():
                try:
                    audio_path, duration = self.tts_provider.synthesize(
                        concept.cta_voiceover,
                        voice_id=self.config.tts_voice_id,
                    )
                    cta_voiceover = GeneratedVoiceover(
                        text=concept.cta_voiceover,
                        audio_path=audio_path,
                        duration_seconds=duration,
                        voice_id=self.config.tts_voice_id,
                    )
                except Exception as e:
                    print(f"  CTA voiceover failed: {e}")
        else:
            scene_voiceovers = [None] * len(concept.scenes)
            cta_voiceover = None

        # 3. Compose final video with per-scene audio sync
        composed = self.composer.compose(
            concept=concept,
            clips=clips,
            scene_voiceovers=scene_voiceovers,
            cta_voiceover=cta_voiceover,
            background_music_path=self.config.background_music_path,
            music_volume=self.config.music_volume,
        )

        return composed

    def run(
        self,
        topic: str,
        context_text: str = "",
    ) -> VideoPipelineResult:
        """Run the full pipeline end-to-end (no human review)."""
        timestamp = datetime.now().isoformat()

        print(f"\n{'='*60}")
        print(f"VIDEO AD PIPELINE: {topic}")
        print(f"{'='*60}\n")

        concepts = self.generate_concepts(topic, context_text)
        evaluated = self.evaluate_concepts(concepts, context_text)

        # Take top N
        top_concepts = [e.concept for e in evaluated[:self.config.num_to_produce]]
        videos = self.produce_videos(top_concepts)

        result = VideoPipelineResult(
            timestamp=timestamp,
            topic=topic,
            concepts_generated=len(concepts),
            concepts_evaluated=len(evaluated),
            videos_produced=len(videos),
            videos=[
                {
                    "title": v.concept.title,
                    "output_path": v.output_path,
                    "thumbnail_path": v.thumbnail_path,
                    "total_cost": v.total_cost,
                    "total_duration": v.total_duration,
                }
                for v in videos
            ],
            output_dir=self.config.output_dir,
            cost_summary=self.cost_tracker.summary(),
        )

        return result
