"""
Video ad concept evaluator.
Scores and ranks video ad concepts using Grok.
Follows the same pattern as MemeEvaluator.
"""

from dataclasses import dataclass, field

from .grok import GrokClient
from .video_dataclasses import VideoAdConcept, EvaluatedVideoAd

from src.config.domain_config import EvaluationCriterion, ScoringGuide


# Video-specific evaluation criteria
VIDEO_EVALUATION_CRITERIA = [
    EvaluationCriterion(
        name="hook_strength",
        display_name="Hook Strength",
        description="Does the opening grab attention in the first 2 seconds?",
        weight=0.30,
        scoring_guide=ScoringGuide(
            low="Weak or generic opening, wouldn't stop scrolling",
            medium="Decent hook, might pause briefly",
            high="Immediately compelling, would stop scrolling",
        ),
    ),
    EvaluationCriterion(
        name="visual_clarity",
        display_name="Visual Clarity",
        description="Are the visual prompts clear and producible by AI video generation?",
        weight=0.25,
        scoring_guide=ScoringGuide(
            low="Vague, overly complex, or impossible to generate",
            medium="Reasonable but could be more specific",
            high="Crystal clear, specific, highly producible",
        ),
    ),
    EvaluationCriterion(
        name="message_coherence",
        display_name="Message Coherence",
        description="Does the ad tell a clear story with a logical CTA?",
        weight=0.25,
        scoring_guide=ScoringGuide(
            low="Confusing narrative or disconnected CTA",
            medium="Coherent but not compelling",
            high="Clear story arc with natural CTA",
        ),
    ),
    EvaluationCriterion(
        name="audience_fit",
        display_name="Audience Fit",
        description="Would the target audience connect with this?",
        weight=0.20,
        scoring_guide=ScoringGuide(
            low="Wrong tone or irrelevant to audience",
            medium="Acceptable for the audience",
            high="Perfectly tailored to the audience",
        ),
    ),
]


class VideoAdEvaluator:
    """Evaluate and rank video ad concepts using Grok."""

    def __init__(self, criteria: list[EvaluationCriterion] | None = None):
        self.client = GrokClient()
        self.criteria = criteria or VIDEO_EVALUATION_CRITERIA

    def evaluate_batch(
        self,
        concepts: list[VideoAdConcept],
        context_text: str = "",
        batch_size: int = 5,
        eval_prompt: str | None = None,
    ) -> list[EvaluatedVideoAd]:
        """
        Evaluate a batch of video ad concepts.

        Args:
            concepts: List of VideoAdConcept objects
            context_text: Optional context for evaluation
            batch_size: Concepts per API call
            eval_prompt: Override evaluation prompt (from Jinja2 template)

        Returns:
            List of EvaluatedVideoAd, sorted by overall_score descending
        """
        evaluated = []

        for i in range(0, len(concepts), batch_size):
            batch = concepts[i:i + batch_size]
            batch_results = self._evaluate_batch(batch, context_text, eval_prompt)
            evaluated.extend(batch_results)

        evaluated.sort(key=lambda x: x.overall_score, reverse=True)
        return evaluated

    def _evaluate_batch(
        self,
        concepts: list[VideoAdConcept],
        context_text: str = "",
        eval_prompt: str | None = None,
    ) -> list[EvaluatedVideoAd]:
        """Evaluate a single batch."""
        if eval_prompt is None:
            eval_prompt = self._build_eval_prompt(concepts, context_text)

        response = self.client._chat(
            messages=[{"role": "user", "content": eval_prompt}],
            model="grok-3-mini",
            temperature=0.3,
            max_tokens=2000,
        )

        return self._parse_scores(concepts, response)

    def _build_eval_prompt(
        self,
        concepts: list[VideoAdConcept],
        context_text: str = "",
    ) -> str:
        """Build evaluation prompt from concepts."""
        concepts_text = self._format_concepts_for_eval(concepts)

        criteria_section = ""
        for i, crit in enumerate(self.criteria, 1):
            criteria_section += f"""{i}. {crit.name.upper()} (1-10): {crit.description}
   - 1-3: {crit.scoring_guide.low}
   - 4-6: {crit.scoring_guide.medium}
   - 7-10: {crit.scoring_guide.high}

"""

        score_format = " ".join(f"{c.name.upper()}=X" for c in self.criteria)

        context_section = ""
        if context_text:
            context_section = f"""
CONTEXT (for reference):
{context_text}
"""

        return f"""You are evaluating video ad concepts. Score each on these criteria:

{criteria_section}
{context_section}
CONCEPTS TO EVALUATE:
{concepts_text}

For each concept, respond with:
CONCEPT 1: {score_format}
NOTES: Brief note on why it works (or doesn't)

CONCEPT 2: {score_format}
NOTES: ...

Be STRICT. If the hook is weak, score it low. If visuals are vague, score them low."""

    def _format_concepts_for_eval(self, concepts: list[VideoAdConcept]) -> str:
        """Format concepts for the evaluation prompt."""
        text = ""
        for i, c in enumerate(concepts, 1):
            text += f"\nCONCEPT {i}:\n"
            text += f"Title: {c.title}\n"
            text += f"Hook: {c.hook}\n"
            for scene in c.scenes:
                text += f"Scene {scene.scene_number}: {scene.visual_prompt[:200]}\n"
                text += f"  Voiceover: {scene.voiceover_text[:150]}\n"
                if scene.text_overlay:
                    text += f"  Text overlay: {scene.text_overlay}\n"
            text += f"CTA: {c.cta_text}\n"
            text += f"Tone: {c.tone}\n"
            text += f"Audience: {c.target_audience}\n"
        return text

    def _parse_scores(
        self,
        concepts: list[VideoAdConcept],
        response: str,
    ) -> list[EvaluatedVideoAd]:
        """Parse evaluation response into EvaluatedVideoAd objects."""
        evaluated = []
        lines = response.strip().split('\n')

        current_idx = None
        current_scores: dict[str, int] = {}
        current_notes = ""

        criterion_names = {c.name.upper(): c.name for c in self.criteria}

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.upper().startswith("CONCEPT "):
                # Save previous concept
                if current_idx is not None and current_scores:
                    evaluated.append(self._create_evaluated(
                        concepts[current_idx] if current_idx < len(concepts) else None,
                        current_scores,
                        current_notes,
                    ))

                try:
                    parts = line.split(":", 1)
                    num = int(parts[0].upper().replace("CONCEPT", "").strip()) - 1
                    current_idx = num
                    current_scores = {}
                    current_notes = ""

                    score_part = parts[1] if len(parts) > 1 else ""
                    for upper_name, actual_name in criterion_names.items():
                        if upper_name + "=" in score_part.upper():
                            idx = score_part.upper().find(upper_name + "=")
                            val_str = score_part[idx + len(upper_name) + 1:].split()[0]
                            val_str = ''.join(c for c in val_str if c.isdigit())
                            if val_str:
                                current_scores[actual_name] = int(val_str)
                except (ValueError, IndexError):
                    continue

            elif line.upper().startswith("NOTES:"):
                current_notes = line.split(":", 1)[1].strip() if ":" in line else ""

        # Don't forget the last concept
        if current_idx is not None and current_scores:
            evaluated.append(self._create_evaluated(
                concepts[current_idx] if current_idx < len(concepts) else None,
                current_scores,
                current_notes,
            ))

        if evaluated and len(evaluated) < len(concepts) * 0.5:
            print(f"  Warning: parsed scores for {len(evaluated)}/{len(concepts)} concepts")

        # Assign defaults for unparsed concepts
        parsed_ids = {id(e.concept) for e in evaluated}
        for concept in concepts:
            if id(concept) not in parsed_ids:
                evaluated.append(EvaluatedVideoAd(
                    concept=concept,
                    scores={c.name: 5 for c in self.criteria},
                    overall_score=5.0,
                    evaluation_notes="(Unable to parse score)",
                ))

        return evaluated

    def _create_evaluated(
        self,
        concept: VideoAdConcept | None,
        scores: dict[str, int],
        notes: str,
    ) -> EvaluatedVideoAd | None:
        """Create EvaluatedVideoAd from parsed scores."""
        if concept is None:
            return None

        # Weighted overall score
        overall = 0.0
        for crit in self.criteria:
            if crit.name in scores:
                overall += scores[crit.name] * crit.weight

        return EvaluatedVideoAd(
            concept=concept,
            scores=scores,
            overall_score=overall,
            evaluation_notes=notes,
        )

    def close(self):
        self.client.close()
