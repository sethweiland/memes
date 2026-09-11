"""
Data structures for the video ad creative pipeline.
Analogous to MemeIdea, GeneratedMeme, and EvaluatedMeme from the meme pipeline.
"""

from dataclasses import dataclass, field


@dataclass
class VideoScene:
    """A single scene in a video ad."""
    scene_number: int                   # 1-based index
    duration_seconds: float             # Typically 2-5 seconds
    visual_prompt: str                  # Text-to-video prompt for the gen API
    voiceover_text: str                 # TTS narration for this scene
    text_overlay: str                   # On-screen text (can be empty)
    text_overlay_position: str = "bottom"  # "top", "center", "bottom"


@dataclass
class VideoAdConcept:
    """A complete video ad concept (analogous to MemeIdea)."""
    title: str                          # Working title
    hook: str                           # Opening hook / attention grabber
    scenes: list[VideoScene] = field(default_factory=list)
    cta_text: str = ""                  # Call-to-action text ("Shop Now", etc.)
    cta_voiceover: str = ""             # Spoken CTA
    total_duration: float = 7.0         # Target duration in seconds (5-10)
    tone: str = ""                      # "energetic", "emotional", "humorous", etc.
    target_audience: str = ""           # Brief description
    explanation: str = ""               # Why this concept works
    source_reference: str = ""          # Context that inspired it


@dataclass
class GeneratedClip:
    """A single generated video clip from a video gen API."""
    scene: VideoScene
    video_path: str                     # Local path to the clip file
    provider: str                       # "kling", "runway", "veo"
    generation_cost: float = 0.0        # Cost in USD
    generation_time: float = 0.0        # Seconds taken to generate


@dataclass
class GeneratedVoiceover:
    """A generated voiceover audio file."""
    text: str
    audio_path: str                     # Local path to audio file
    duration_seconds: float = 0.0
    voice_id: str = "default"


@dataclass
class ComposedVideo:
    """A fully composed video ad (analogous to GeneratedMeme)."""
    concept: VideoAdConcept
    clips: list[GeneratedClip] = field(default_factory=list)
    voiceover: GeneratedVoiceover | None = None
    output_path: str = ""               # Final composed video path
    thumbnail_path: str | None = None
    total_cost: float = 0.0             # Sum of all generation costs
    total_duration: float = 0.0         # Actual final duration


@dataclass
class EvaluatedVideoAd:
    """A video ad concept with evaluation scores (analogous to EvaluatedMeme)."""
    concept: VideoAdConcept
    scores: dict[str, int] = field(default_factory=dict)
    overall_score: float = 0.0
    evaluation_notes: str = ""

    def get_score(self, criterion: str) -> int:
        return self.scores.get(criterion, 0)

    def to_dict(self) -> dict:
        result = {
            "title": self.concept.title,
            "hook": self.concept.hook,
            "cta_text": self.concept.cta_text,
            "tone": self.concept.tone,
            "target_audience": self.concept.target_audience,
            "total_duration": self.concept.total_duration,
            "overall_score": self.overall_score,
            "evaluation_notes": self.evaluation_notes,
            "scenes": [
                {
                    "scene_number": s.scene_number,
                    "duration_seconds": s.duration_seconds,
                    "visual_prompt": s.visual_prompt,
                    "voiceover_text": s.voiceover_text,
                    "text_overlay": s.text_overlay,
                }
                for s in self.concept.scenes
            ],
        }
        result.update(self.scores)
        return result


@dataclass
class CostTracker:
    """Track costs across video generation operations."""
    max_budget: float = 5.0             # USD
    total_spent: float = 0.0
    costs: list[dict] = field(default_factory=list)

    def check(self, estimated_cost: float, operation: str):
        """Raise BudgetExceeded if this operation would exceed budget."""
        if self.total_spent + estimated_cost > self.max_budget:
            raise BudgetExceeded(
                f"Budget exceeded: ${self.total_spent:.2f} spent + "
                f"${estimated_cost:.2f} estimated for '{operation}' > "
                f"${self.max_budget:.2f} limit"
            )

    def record(self, cost: float, operation: str, provider: str = ""):
        """Record a cost."""
        self.total_spent += cost
        self.costs.append({
            "operation": operation,
            "provider": provider,
            "cost": cost,
        })

    def summary(self) -> dict:
        return {
            "total_spent": round(self.total_spent, 4),
            "max_budget": self.max_budget,
            "num_operations": len(self.costs),
            "costs": self.costs,
        }


class BudgetExceeded(Exception):
    """Raised when video generation would exceed the cost budget."""
    pass
