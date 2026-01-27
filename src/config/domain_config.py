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

        # Set paths relative to config file
        prompts_dir = config_path.parent / "prompts"
        data_dir = Path("data") / data['name']

        return cls(
            entity_categories=entity_categories,
            topic_categories=topic_categories,
            tone_indicators=tone_indicators,
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
