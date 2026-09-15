"""
Bounded factual-grounding pass for meme concepts.

One extra LLM call, capped like the critic loop: at most GROUNDING_LIMIT
candidates, modest max_tokens. Used to stop invented person/gear claims
(e.g. Billy + Telecaster with no known beat) from landing as confident captions.
Does not auto-post.
"""

from __future__ import annotations

from dataclasses import dataclass

from .grok import MemeIdea
from .two_stage import EvaluatedMeme

GROUNDING_LIMIT = 12
GROUNDING_MAX_TOKENS = 900
DOWNSCORE_PENALTY = 2.5
MIN_SCORE = 1.0


@dataclass
class GroundingNote:
    hinges: bool = False
    claim: str = ""
    support: str = ""
    confidence: str = ""  # high | medium | low
    action: str = "ok"  # ok | downscore | skip
    rationale: str = ""

    def to_dict(self) -> dict | None:
        """Queue-facing payload. Empty / non-hinging notes are omitted."""
        if not self.hinges and not self.claim:
            return None
        data = {
            "claim": self.claim.strip(),
            "support": self.support.strip(),
            "confidence": self.confidence.strip().lower(),
        }
        if not any(data.values()):
            return None
        return data


def idea_rationale(idea: MemeIdea) -> str:
    """Reviewer-facing reason the joke exists."""
    return (idea.rationale or idea.explanation or "").strip()


def _normalize_action(raw: str) -> str:
    value = (raw or "ok").strip().lower()
    if value in {"skip", "drop", "reject"}:
        return "skip"
    if value in {"downscore", "down", "penalize", "low"}:
        return "downscore"
    return "ok"


def _normalize_confidence(raw: str) -> str:
    value = (raw or "").strip().lower()
    if value.startswith("high"):
        return "high"
    if value.startswith("med"):
        return "medium"
    if value.startswith("low"):
        return "low"
    return value


def _truthy(raw: str) -> bool:
    return (raw or "").strip().lower() in {"yes", "y", "true", "1", "hinges"}


def parse_grounding_response(response: str, count: int) -> list[GroundingNote]:
    """Parse a grounding LLM response into one note per meme index."""
    notes = [GroundingNote() for _ in range(count)]
    current_idx = None
    current = GroundingNote()

    def commit():
        nonlocal current_idx, current
        if current_idx is not None and 0 <= current_idx < count:
            notes[current_idx] = current
        current = GroundingNote()
        current_idx = None

    for raw_line in (response or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("MEME "):
            commit()
            try:
                num_part = line.split(":", 1)[0]
                current_idx = int(num_part.replace("MEME", "").strip()) - 1
            except ValueError:
                current_idx = None
            current = GroundingNote()
            continue
        if current_idx is None:
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key_u = key.strip().upper()
        value = value.strip()
        if key_u == "HINGES":
            current.hinges = _truthy(value)
        elif key_u == "CLAIM":
            current.claim = value
            if value:
                current.hinges = True
        elif key_u == "SUPPORT":
            current.support = value
        elif key_u == "CONFIDENCE":
            current.confidence = _normalize_confidence(value)
        elif key_u == "ACTION":
            current.action = _normalize_action(value)
        elif key_u == "RATIONALE":
            current.rationale = value

    commit()
    return notes


def apply_grounding(
    evaluated: list[EvaluatedMeme],
    notes: list[GroundingNote],
    *,
    apply_penalties: bool = True,
) -> list[EvaluatedMeme]:
    """Attach grounding to evaluated memes and optionally downscore thin claims."""
    for item, note in zip(evaluated, notes):
        item.grounding = note.to_dict()
        item.grounding_action = note.action if note.hinges else "ok"
        if note.rationale and not idea_rationale(item.idea):
            item.idea.rationale = note.rationale
            if not item.idea.explanation:
                item.idea.explanation = note.rationale
        if not apply_penalties or not note.hinges:
            continue
        if note.action == "downscore" or (
            note.action == "ok" and note.confidence == "low" and not _support_looks_known(note.support)
        ):
            item.overall_score = max(MIN_SCORE, float(item.overall_score) - DOWNSCORE_PENALTY)
            item.grounding_action = "downscore"
        elif note.action == "skip":
            item.overall_score = max(MIN_SCORE, min(float(item.overall_score), 3.0))
            item.grounding_action = "skip"
    return evaluated


def _support_looks_known(support: str) -> bool:
    text = (support or "").lower()
    if not text:
        return False
    unknown_markers = (
        "no known",
        "cannot cite",
        "can't cite",
        "unverif",
        "invent",
        "not known",
        "no documented",
        "no viral",
        "made up",
        "unknown",
    )
    return not any(marker in text for marker in unknown_markers)


def _format_candidates(evaluated: list[EvaluatedMeme]) -> str:
    blocks = []
    for idx, item in enumerate(evaluated, 1):
        idea = item.idea
        blocks.append(
            f"MEME {idx}:\n"
            f"Template: {idea.format}\n"
            f"Top: {idea.top_text}\n"
            f"Bottom: {idea.bottom_text}\n"
            f"Rationale: {idea_rationale(idea) or '(none yet)'}\n"
        )
    return "\n".join(blocks)


def ground_evaluated(
    chat_client,
    topic: str,
    evaluated: list[EvaluatedMeme],
    *,
    limit: int = GROUNDING_LIMIT,
    apply_penalties: bool = True,
) -> list[EvaluatedMeme]:
    """
    One bounded LLM call over the top ``limit`` evaluated memes.

    Failures are swallowed by the caller — generation should still complete.
    """
    if not evaluated or chat_client is None:
        return evaluated

    targets = evaluated[: max(0, min(limit, len(evaluated)))]
    if not targets:
        return evaluated

    prompt = f"""You are fact-checking meme jokes before a human reviews them.

Topic: {topic}

For each meme, decide if it HINGES on a specific claim about a real person, band,
instrument, piece of gear, tour, or historical fact
(example of a thin claim: "Billy Strings unplugs his Telecaster").

If it DOES hinge:
- CLAIM: the specific claim in one line
- SUPPORT: a known beat you can cite (tour moment, viral clip, documented gear,
  or a well-known scene stereotype). If you cannot cite one, say "no known beat" —
  do NOT invent festival lore, fake tours, or made-up gear history.
- CONFIDENCE: high | medium | low
- ACTION:
  - ok: known beat, or a clearly marked scene stereotype (stereotype may be low confidence)
  - downscore: plausible but unverified
  - skip: invented-sounding specific fact with no known beat
- RATIONALE: one short line on why the joke works / what cultural beat it hits
  (for the human reviewer, not for the meme text)

If it does NOT hinge (pure template joke, generic scene roast with no named fact):
HINGES: no
ACTION: ok
RATIONALE: one short line why the joke works

Use this exact format:

MEME 1:
HINGES: yes|no
CLAIM:
SUPPORT:
CONFIDENCE:
ACTION: ok|downscore|skip
RATIONALE:

{_format_candidates(targets)}
"""

    response = chat_client._chat(
        [{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=GROUNDING_MAX_TOKENS,
    )
    notes = parse_grounding_response(response, len(targets))
    apply_grounding(targets, notes, apply_penalties=apply_penalties)
    return evaluated
