"""
Generic configuration for meme generation without a specific domain.
Provides fallback evaluation criteria and helper functions.
"""

from dataclasses import dataclass, field
from typing import Optional

from src.config.domain_config import EvaluationCriterion, ScoringGuide, AbsurdismDetection


@dataclass
class GenericConfig:
    """
    Minimal configuration for domain-agnostic meme generation.
    Mirrors the interface of DomainConfig but without domain-specific content.
    """
    # Identity
    name: str = "generic"
    display_name: str = "General"
    description: str = "General meme generation for any topic"

    # Content source
    content_source_name: str = "Web Search"
    content_source_description: str = "web search results"

    # Evaluation criteria
    evaluation_criteria: list[EvaluationCriterion] = field(default_factory=list)
    absurdism_detection: AbsurdismDetection = field(default_factory=AbsurdismDetection)

    def __post_init__(self):
        if not self.evaluation_criteria:
            self.evaluation_criteria = GENERIC_EVALUATION_CRITERIA.copy()

    def get_evaluation_prompt_section(self) -> str:
        """Generate the evaluation criteria section for prompts."""
        if not self.evaluation_criteria:
            return ""

        lines = []
        for i, crit in enumerate(self.evaluation_criteria, 1):
            lines.append(f"{i}. {crit.name.upper()} (1-10): {crit.description}")
            lines.append(f"   - 1-3: {crit.scoring_guide.low}")
            lines.append(f"   - 4-6: {crit.scoring_guide.medium}")
            lines.append(f"   - 7-10: {crit.scoring_guide.high}")
            lines.append("")

        return "\n".join(lines)

    def get_criterion_by_name(self, name: str) -> Optional[EvaluationCriterion]:
        """Get an evaluation criterion by name."""
        for crit in self.evaluation_criteria:
            if crit.name == name:
                return crit
        return None

    def is_potential_absurdism(self, scores: dict[str, int]) -> bool:
        """Check if a meme might be intentional absurdism (and reward it)."""
        if not self.absurdism_detection.enabled:
            return False

        # For generic config, check relevance instead of source_accuracy
        relevance = scores.get("relevance", 10)
        humor = scores.get("humor", 0)

        # Low relevance + high humor = intentional absurdism (good!)
        return (
            relevance < self.absurdism_detection.low_accuracy_threshold
            and humor >= self.absurdism_detection.high_humor_threshold
        )

    def calculate_overall_score(self, scores: dict[str, int]) -> float:
        """Calculate overall score from individual criterion scores."""
        if not self.evaluation_criteria:
            return sum(scores.values()) / len(scores) if scores else 0

        total = 0.0
        for crit in self.evaluation_criteria:
            if crit.name in scores:
                total += scores[crit.name] * crit.weight

        # Bonus for intentional absurdism (low relevance but high humor)
        if self.is_potential_absurdism(scores):
            total *= 1.1  # 10% bonus for being intentionally weird and funny

        return total


# Generic evaluation criteria for any topic
# NOTE: Humor is weighted highest at 60% - funny beats everything
GENERIC_EVALUATION_CRITERIA = [
    EvaluationCriterion(
        name="humor",
        display_name="Humor",
        description="Is it actually funny? Would people share this?",
        weight=0.60,
        scoring_guide=ScoringGuide(
            low="Not funny, confusing, or trying too hard",
            medium="Mildly amusing, decent chuckle",
            high="Actually hilarious, would go viral, makes you laugh out loud",
        ),
    ),
    EvaluationCriterion(
        name="relevance",
        display_name="Topic Relevance",
        description="Does the meme connect to the topic (even if absurdly)?",
        weight=0.25,
        scoring_guide=ScoringGuide(
            low="Completely random, no connection to topic",
            medium="Loosely related or absurdist take on the topic",
            high="Cleverly tied to the topic or brilliant absurdist twist",
        ),
        low_score_note="Might be intentional absurdism",
    ),
    EvaluationCriterion(
        name="template_fit",
        display_name="Template Fit",
        description="Does the text work with the meme format?",
        weight=0.15,
        scoring_guide=ScoringGuide(
            low="Misuses the template or text doesn't fit",
            medium="Acceptable fit, gets the job done",
            high="Perfect use of the template format",
        ),
    ),
]


def get_generic_config() -> GenericConfig:
    """Get a generic config instance for domain-agnostic generation."""
    return GenericConfig()
