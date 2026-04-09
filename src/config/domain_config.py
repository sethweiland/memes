"""
Domain configuration management.
Defines the structure for domain-specific settings loaded from YAML.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import yaml


@dataclass
class EntityCategory:
    """A category of entities for extraction (e.g., instruments, positions)."""
    name: str                           # e.g., "instruments"
    display_name: str                   # e.g., "Instruments"
    patterns: dict[str, list[str]]      # e.g., {"mandolin": ["mandolin", "mando"]}


@dataclass
class TopicCategory:
    """A topic category for classification."""
    name: str                           # e.g., "technique"
    patterns: list[str]                 # e.g., ["technique", "style", "picking"]


@dataclass
class ToneIndicator:
    """Indicators for tone detection."""
    tone: str                           # e.g., "nostalgic"
    patterns: list[str]                 # e.g., ["remember", "those days"]


@dataclass
class ScoringGuide:
    """Scoring guide for an evaluation criterion."""
    low: str                            # Description for low scores (1-3)
    medium: str                         # Description for medium scores (4-6)
    high: str                           # Description for high scores (7-10)


@dataclass
class EvaluationCriterion:
    """A criterion for evaluating meme quality."""
    name: str                           # e.g., "source_accuracy"
    display_name: str                   # e.g., "Historical Accuracy"
    description: str                    # e.g., "Is the history/reference real?"
    weight: float                       # Weight in overall score (0.0-1.0)
    scoring_guide: ScoringGuide         # Guide for scoring
    low_score_note: str = ""            # Note for low scores (e.g., "intentional absurdism?")


@dataclass
class AbsurdismDetection:
    """Configuration for detecting intentional absurdism."""
    enabled: bool = True
    low_accuracy_threshold: int = 4     # Below this = low accuracy
    high_humor_threshold: int = 6       # Above this = high humor


@dataclass
class CurrentEventsConfig:
    """Configuration for current events news search."""
    enabled: bool = False
    search_queries: list[str] = field(default_factory=list)
    max_results: int = 10


@dataclass
class DomainConfig:
    """
    Complete domain configuration.

    Loaded from YAML files in domains/<name>/config.yaml
    """
    # Identity
    name: str                           # e.g., "bluegrass"
    display_name: str                   # e.g., "Bluegrass Music"
    description: str                    # e.g., "Bluegrass music culture and history"

    # Content source
    content_source_name: str            # e.g., "Bluegrass Unlimited"
    content_source_description: str     # e.g., "Bluegrass Unlimited Archives"

    # Entity extraction
    known_entities: dict[str, set[str]] = field(default_factory=dict)
    entity_categories: list[EntityCategory] = field(default_factory=list)

    # Classification
    topic_categories: list[TopicCategory] = field(default_factory=list)
    tone_indicators: list[ToneIndicator] = field(default_factory=list)

    # Tone guidelines for generation
    tone_guidelines: list[str] = field(default_factory=list)

    # Style guidelines
    style_guidelines: list[str] = field(default_factory=list)

    # Humor focus areas
    humor_focus: list[str] = field(default_factory=list)

    # Evaluation criteria for two-stage generation
    evaluation_criteria: list[EvaluationCriterion] = field(default_factory=list)
    absurdism_detection: AbsurdismDetection = field(default_factory=AbsurdismDetection)
    current_events: CurrentEventsConfig = field(default_factory=CurrentEventsConfig)

    # Paths (set after loading)
    prompts_dir: Path = field(default_factory=lambda: Path("prompts"))
    data_dir: Path = field(default_factory=lambda: Path("data"))

    # Vector store
    collection_name: str = ""

    def __post_init__(self):
        if not self.collection_name:
            self.collection_name = f"{self.name}_articles"

    @classmethod
    def from_yaml(cls, config_path: Path) -> "DomainConfig":
        """
        Load domain config from YAML file.

        Args:
            config_path: Path to config.yaml file

        Returns:
            DomainConfig instance
        """
        config_path = Path(config_path)

        with open(config_path, 'r') as f:
            data = yaml.safe_load(f)

        # Load entities from separate file if it exists
        entities_path = config_path.parent / "entities.yaml"
        if entities_path.exists():
            with open(entities_path, 'r') as f:
                entities_data = yaml.safe_load(f)
            data['known_entities'] = {
                k: set(v) for k, v in entities_data.get('known_entities', {}).items()
            }
        else:
            data['known_entities'] = {}

        # Parse entity categories
        entity_categories = [
            EntityCategory(
                name=cat['name'],
                display_name=cat.get('display_name', cat['name'].title()),
                patterns=cat.get('patterns', {})
            )
            for cat in data.pop('entity_categories', [])
        ]

        # Parse topic categories
        topic_categories = [
            TopicCategory(name=cat['name'], patterns=cat.get('patterns', []))
            for cat in data.pop('topic_categories', [])
        ]

        # Parse tone indicators
        tone_indicators = [
            ToneIndicator(tone=ind['tone'], patterns=ind.get('patterns', []))
            for ind in data.pop('tone_indicators', [])
        ]

        # Parse evaluation criteria
        evaluation_criteria = []
        for crit in data.pop('evaluation_criteria', []):
            scoring_guide = crit.get('scoring_guide', {})
            evaluation_criteria.append(EvaluationCriterion(
                name=crit['name'],
                display_name=crit.get('display_name', crit['name'].title()),
                description=crit.get('description', ''),
                weight=crit.get('weight', 0.33),
                scoring_guide=ScoringGuide(
                    low=scoring_guide.get('low', 'Low quality'),
                    medium=scoring_guide.get('medium', 'Medium quality'),
                    high=scoring_guide.get('high', 'High quality'),
                ),
                low_score_note=crit.get('low_score_note', ''),
            ))

        # Parse absurdism detection config
        absurdism_data = data.pop('absurdism_detection', {})
        absurdism_detection = AbsurdismDetection(
            enabled=absurdism_data.get('enabled', True),
            low_accuracy_threshold=absurdism_data.get('low_accuracy_threshold', 4),
            high_humor_threshold=absurdism_data.get('high_humor_threshold', 6),
        )

        # Parse current events config
        current_events_data = data.pop('current_events', {})
        current_events = CurrentEventsConfig(
            enabled=current_events_data.get('enabled', False),
            search_queries=current_events_data.get('search_queries', []),
            max_results=current_events_data.get('max_results', 10),
        )

        # Set paths relative to config file
        prompts_dir = config_path.parent / "prompts"
        data_dir = Path("data") / data['name']

        return cls(
            entity_categories=entity_categories,
            topic_categories=topic_categories,
            tone_indicators=tone_indicators,
            evaluation_criteria=evaluation_criteria,
            absurdism_detection=absurdism_detection,
            current_events=current_events,
            prompts_dir=prompts_dir,
            data_dir=data_dir,
            **{k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        )

    def get_all_known_entities(self) -> set[str]:
        """Get all known entities across all entity types."""
        all_entities = set()
        for entities in self.known_entities.values():
            all_entities.update(entities)
        return all_entities

    def get_entity_type(self, entity: str) -> Optional[str]:
        """Get the type of a known entity (e.g., 'artists' for 'Bill Monroe')."""
        for entity_type, entities in self.known_entities.items():
            if entity in entities:
                return entity_type
        return None

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

    def calculate_overall_score(self, scores: dict[str, int]) -> float:
        """Calculate overall score from individual criterion scores."""
        if not self.evaluation_criteria:
            return sum(scores.values()) / len(scores) if scores else 0

        total = 0.0
        for crit in self.evaluation_criteria:
            if crit.name in scores:
                total += scores[crit.name] * crit.weight

        # Bonus for intentional absurdism (low accuracy but high humor)
        # Instead of penalizing low accuracy, we reward it when combined with high humor
        if self.absurdism_detection.enabled:
            accuracy = scores.get("source_accuracy", 10)
            humor = scores.get("humor", 0)
            if (accuracy < self.absurdism_detection.low_accuracy_threshold
                    and humor >= self.absurdism_detection.high_humor_threshold):
                # Absurdist bonus: +10% for being intentionally weird and funny
                total *= 1.1

        return total

    def is_potential_absurdism(self, scores: dict[str, int]) -> bool:
        """Check if a meme might be intentional absurdism."""
        if not self.absurdism_detection.enabled:
            return False

        accuracy = scores.get("source_accuracy", 10)
        humor = scores.get("humor", 0)

        return (
            accuracy < self.absurdism_detection.low_accuracy_threshold
            and humor >= self.absurdism_detection.high_humor_threshold
        )
