"""
Prompt-time retrieval for approved meme taste examples.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TasteExample:
    id: str
    template: str
    text: str
    tags: list[str]
    humor_patterns: list[str]
    why_it_works: str
    generation_lesson: str


class TasteExampleStore:
    """Load and select approved examples for prompt injection."""

    def __init__(self, path: str = "data/meme_training/approved.jsonl"):
        self.path = Path(path)
        self.examples = self._load()

    def _load(self) -> list[TasteExample]:
        if not self.path.exists():
            return []

        examples: list[TasteExample] = []
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not row.get("approved", False):
                continue

            visible = row.get("visible_text", {})
            parts = []
            if visible.get("top"):
                parts.append(visible["top"])
            if visible.get("bottom"):
                parts.append(visible["bottom"])
            parts.extend(visible.get("other", []))

            examples.append(TasteExample(
                id=row.get("id", ""),
                template=row.get("template", ""),
                text=" / ".join(part for part in parts if part),
                tags=row.get("tags", []),
                humor_patterns=row.get("humor_patterns", []),
                why_it_works=row.get("why_it_works", ""),
                generation_lesson=row.get("generation_lesson", ""),
            ))

        return examples

    def select(self, topic: str, limit: int = 8) -> list[TasteExample]:
        """Select relevant examples by simple keyword/tag scoring."""
        if not self.examples:
            return []

        topic_terms = set(re.findall(r"\b[a-z0-9']+\b", topic.lower()))
        scored: list[tuple[int, TasteExample]] = []

        for example in self.examples:
            searchable = " ".join([
                example.template,
                example.text,
                " ".join(example.tags),
                " ".join(example.humor_patterns),
                example.why_it_works,
                example.generation_lesson,
            ]).lower()
            terms = set(re.findall(r"\b[a-z0-9']+\b", searchable))
            score = len(topic_terms & terms)

            for tag in example.tags:
                tag_terms = set(re.findall(r"\b[a-z0-9']+\b", tag.lower()))
                if topic_terms & tag_terms:
                    score += 2

            if score > 0:
                scored.append((score, example))

        scored.sort(key=lambda item: item[0], reverse=True)
        selected = [example for _, example in scored[:limit]]

        if len(selected) < limit:
            fallback_ids = {example.id for example in selected}
            fallback_tags = {
                "jam session", "fiddle tune", "banjo", "festival", "gatekeeping",
                "instrument stereotypes", "lyrics", "gear", "tempo", "practice",
            }
            for example in self.examples:
                if example.id in fallback_ids:
                    continue
                if fallback_tags & set(example.tags):
                    selected.append(example)
                    fallback_ids.add(example.id)
                    if len(selected) >= limit:
                        break

        return selected[:limit]


def format_taste_examples(topic: str, limit: int = 8) -> str:
    """Return a prompt block with relevant approved examples."""
    examples = TasteExampleStore().select(topic, limit=limit)
    if not examples:
        return ""

    lines = [
        "APPROVED MEME TASTE EXAMPLES",
        "Study these for structure, specificity, rhythm, and punchline logic. Do not copy their text.",
    ]
    for i, example in enumerate(examples, 1):
        lines.append("")
        lines.append(f"Example {i}:")
        lines.append(f"Text: {example.text}")
        if example.tags:
            lines.append(f"Tags: {', '.join(example.tags[:6])}")
        if example.humor_patterns:
            lines.append(f"Patterns: {', '.join(example.humor_patterns[:4])}")
        if example.why_it_works:
            lines.append(f"Why it works: {example.why_it_works}")
        if example.generation_lesson:
            lines.append(f"Lesson: {example.generation_lesson}")

    return "\n".join(lines)

