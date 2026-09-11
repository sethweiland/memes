"""
Small AI critic loop for recursive meme improvement.

The loop is intentionally tiny:
1. Pick a few high-potential concepts.
2. Ask a stronger critic model what almost works and what to change.
3. Feed the critique back into a second, small generation pass.
4. Persist the critique as reusable prompt memory.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
import json

from .grok import MemeIdea
from .openai_provider import OpenAIResponsesClient
from .two_stage import EvaluatedMeme


AI_FEEDBACK_PATH = Path("data/ai_feedback.json")


@dataclass
class AICritique:
    topic: str
    model: str
    created_at: str
    raw_response: str
    rewrite_brief: str
    prompt_rules: list[str]
    candidate_count: int

    def to_prompt_section(self) -> str:
        lines = ["AI CRITIC LOOP FEEDBACK:"]
        if self.rewrite_brief:
            lines.append(f"- Rewrite brief: {self.rewrite_brief}")
        for rule in self.prompt_rules[:8]:
            lines.append(f"- Critic rule: {rule}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return asdict(self)


def select_critique_targets(evaluated: list[EvaluatedMeme], limit: int = 3) -> list[EvaluatedMeme]:
    """
    Select a tiny set of candidates worth improving.

    Prefer concepts that are not trash, but have obvious room to get sharper.
    """
    if not evaluated:
        return []

    def score(item: EvaluatedMeme) -> tuple[float, float]:
        humor = item.scores.get("humor", 0)
        novelty = item.scores.get("novelty", item.scores.get("cultural_legitimacy", 0))
        compression = item.scores.get("compression", 5)
        # Good enough to care about, imperfect enough to improve.
        improvement_potential = max(0, 10 - min(novelty or 0, compression or 0))
        return (humor + item.overall_score + improvement_potential, item.overall_score)

    candidates = [item for item in evaluated if item.overall_score >= 4.5]
    if not candidates:
        candidates = evaluated[:]
    candidates.sort(key=score, reverse=True)
    return candidates[:limit]


def _format_candidates(candidates: list[EvaluatedMeme]) -> str:
    blocks = []
    for idx, item in enumerate(candidates, 1):
        idea = item.idea
        scores = " ".join(f"{k}={v}" for k, v in item.scores.items())
        blocks.append(f"""CANDIDATE {idx}
Template: {idea.format}
Top: {idea.top_text}
Bottom: {idea.bottom_text}
Scores: {scores}
Overall: {item.overall_score:.1f}
Evaluator notes: {item.evaluation_notes}
""")
    return "\n".join(blocks)


def _parse_critique_response(topic: str, model: str, response: str, candidate_count: int) -> AICritique:
    rewrite_brief = ""
    prompt_rules: list[str] = []
    current = ""

    for raw_line in response.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("REWRITE_BRIEF:"):
            rewrite_brief = line.split(":", 1)[1].strip()
            current = "rewrite"
        elif upper.startswith("PROMPT_RULES:"):
            current = "rules"
        elif upper.startswith("RULE:"):
            prompt_rules.append(line.split(":", 1)[1].strip())
        elif line.startswith("-") and current == "rules":
            prompt_rules.append(line.lstrip("- ").strip())
        elif current == "rewrite" and not rewrite_brief:
            rewrite_brief = line

    if not rewrite_brief:
        rewrite_brief = "Make the strongest candidates more specific, shorter, and less obvious."
    if not prompt_rules:
        prompt_rules = [
            "Keep one clear comedic turn per meme.",
            "Prefer scene-native specificity over broad topic labels.",
            "Cut explanatory setup text.",
        ]

    return AICritique(
        topic=topic,
        model=model,
        created_at=datetime.now().isoformat(timespec="seconds"),
        raw_response=response,
        rewrite_brief=rewrite_brief,
        prompt_rules=prompt_rules,
        candidate_count=candidate_count,
    )


class AIImprovementLoop:
    """Ask a stronger model for critique that can be fed into generation."""

    def __init__(self, model: str = "gpt-5.5"):
        self.model = model
        self.client = OpenAIResponsesClient(default_model=model)

    def critique(
        self,
        topic: str,
        evaluated: list[EvaluatedMeme],
        context_text: str = "",
        limit: int = 3,
    ) -> AICritique | None:
        targets = select_critique_targets(evaluated, limit=limit)
        if not targets:
            return None

        prompt = f"""You are a senior meme editor. Your job is not to be nice; it is to make a tiny set of memes more postable.

Topic: {topic}

Context:
{context_text if context_text else "No extra context."}

Candidates:
{_format_candidates(targets)}

Return this exact structure:

REWRITE_BRIEF: one concise paragraph describing how the next pass should improve these memes
PROMPT_RULES:
- actionable rule
- actionable rule
- actionable rule

Focus on:
- sharper social truth
- more specific insider detail
- less explanatory text
- stronger template fit
- one clean punchline per meme
"""

        response = self.client._chat(
            [{"role": "user", "content": prompt}],
            model=self.model,
            temperature=0.4,
            max_tokens=700,
        )
        return _parse_critique_response(topic, self.model, response, len(targets))


def load_ai_feedback() -> list[dict]:
    if not AI_FEEDBACK_PATH.exists():
        return []
    try:
        return json.loads(AI_FEEDBACK_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def save_ai_feedback(critique: AICritique) -> None:
    AI_FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    history = load_ai_feedback()
    history.append(critique.to_dict())
    AI_FEEDBACK_PATH.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_ai_feedback_context(limit: int = 3) -> str:
    history = load_ai_feedback()
    if not history:
        return ""
    lines = ["PAST AI CRITIC FEEDBACK (soft guidance):"]
    for item in history[-limit:]:
        topic = item.get("topic", "unknown topic")
        brief = item.get("rewrite_brief", "")
        if brief:
            lines.append(f"- For {topic}: {brief}")
        for rule in item.get("prompt_rules", [])[:3]:
            lines.append(f"  Rule: {rule}")
    return "\n".join(lines)
