"""
Insight-first creative planning for meme generation.

The generator should not jump straight from topic to captions. This module
creates a compact brief of tensions, joke structures, and visual strategies
that the caption/template stage can execute against.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol


class ChatProvider(Protocol):
    def _chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 1.0,
        max_tokens: int = 1000,
    ) -> str:
        ...


@dataclass
class CreativeBrief:
    """Creative direction for a meme generation run."""

    topic: str
    audience: str = ""
    tensions: list[str] = field(default_factory=list)
    format_strategies: list[str] = field(default_factory=list)
    original_asset_ideas: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)

    def to_prompt_section(self) -> str:
        """Format the brief for downstream meme execution prompts."""
        sections = ["CREATIVE BRIEF - use this before writing captions:"]

        if self.audience:
            sections.append(f"\nAudience / native voice:\n- {self.audience}")

        if self.tensions:
            sections.append("\nMemeable tensions / social truths:")
            sections.extend(f"- {item}" for item in self.tensions[:10])

        if self.format_strategies:
            sections.append("\nJoke structures to execute:")
            sections.extend(f"- {item}" for item in self.format_strategies[:8])

        if self.original_asset_ideas:
            sections.append("\nOriginal visual asset ideas:")
            sections.extend(f"- {item}" for item in self.original_asset_ideas[:6])
            sections.append(
                "- If the current renderer only supports existing templates, translate these into the closest listed template instead of inventing an unavailable template."
            )

        if self.avoid:
            sections.append("\nAvoid:")
            sections.extend(f"- {item}" for item in self.avoid[:8])

        sections.append(
            "\nExecution rule: each meme should pick ONE tension and ONE structure. Do not pile unrelated facts into one caption."
        )
        return "\n".join(sections).strip()


def build_creative_brief(
    provider: ChatProvider,
    topic: str,
    context_text: str = "",
    num_tensions: int = 8,
) -> CreativeBrief:
    """
    Ask the text model for an insight-first creative brief.

    Returns a best-effort fallback brief if the provider fails or emits invalid
    JSON, so generation can continue.
    """
    prompt = f"""Create an insight-first creative brief for high-quality memes.

Topic: {topic}

Context:
{context_text if context_text else "No extra context supplied."}

Think from first principles. Do NOT write finished memes yet.

Find the real comedic fuel:
- contradictions, status games, delusions, gatekeeping, awkward rituals
- painful truths people in the community recognize
- tensions between what people say and what they do
- visual situations that could become original meme assets

Return ONLY valid JSON with this shape:
{{
  "audience": "1-2 sentences on the native voice and community vibe",
  "tensions": ["{num_tensions} specific memeable tensions or social truths"],
  "format_strategies": ["specific joke structure + when to use it"],
  "original_asset_ideas": ["specific original image/fake screenshot/starter pack/scene ideas"],
  "avoid": ["generic or overused angles to avoid"]
}}

Keep every item concise and concrete. Prefer specificity over broad advice."""

    try:
        raw = provider._chat(
            [{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=1400,
        )
        data = _parse_json_object(raw)
        return CreativeBrief(
            topic=topic,
            audience=str(data.get("audience", "")).strip(),
            tensions=_string_list(data.get("tensions")),
            format_strategies=_string_list(data.get("format_strategies")),
            original_asset_ideas=_string_list(data.get("original_asset_ideas")),
            avoid=_string_list(data.get("avoid")),
        )
    except Exception:
        return CreativeBrief(
            topic=topic,
            tensions=[
                f"What people say about {topic} vs what they actually do",
                f"The tiny status signals and rituals around {topic}",
                f"The annoying behavior everyone recognizes but rarely says out loud",
            ],
            format_strategies=[
                "Comparison template: rejected normal behavior vs preferred unhinged behavior",
                "Reaction template: a painfully specific scenario with a deadpan punchline",
                "Escalation template: normal interest becoming absurd commitment",
            ],
            original_asset_ideas=[
                f"Fake screenshot or starter pack built around the most recognizable {topic} behavior"
            ],
            avoid=[
                "Generic observations",
                "Explaining the joke",
                "Using context facts without a comedic turn",
            ],
        )


def _parse_json_object(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(text[start:end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("Creative brief response was not a JSON object")
    return parsed


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
