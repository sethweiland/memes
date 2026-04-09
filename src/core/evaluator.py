"""
AI-powered meme concept evaluator.
Scores and ranks meme ideas based on humor, authenticity, and template fit.
Uses Grok for evaluation.
"""

from dataclasses import dataclass

from .grok import GrokClient, MemeIdea


@dataclass
class ScoredMeme:
    """A meme concept with evaluation scores."""
    idea: MemeIdea
    humor_score: float  # 1-10: How funny is it?
    authenticity_score: float  # 1-10: How bluegrass-authentic?
    template_fit_score: float  # 1-10: How well does text fit the template?
    overall_score: float  # Weighted combination
    reasoning: str  # Why these scores?

    def __str__(self) -> str:
        return (
            f"{self.idea.format} (Score: {self.overall_score:.1f})\n"
            f"  Top: {self.idea.top_text}\n"
            f"  Bottom: {self.idea.bottom_text}\n"
            f"  Scores: Humor={self.humor_score}, Auth={self.authenticity_score}, Fit={self.template_fit_score}"
        )


class MemeEvaluator:
    """Evaluate and rank meme concepts using Grok."""

    def __init__(self):
        self.client = GrokClient()

    def evaluate_batch(
        self,
        memes: list[MemeIdea],
        batch_size: int = 10,
    ) -> list[ScoredMeme]:
        """
        Evaluate a batch of meme concepts.

        Args:
            memes: List of MemeIdea objects to evaluate
            batch_size: Number of memes to evaluate per API call

        Returns:
            List of ScoredMeme objects, sorted by overall_score descending
        """
        scored = []

        for i in range(0, len(memes), batch_size):
            batch = memes[i:i + batch_size]
            batch_scores = self._evaluate_batch(batch)
            scored.extend(batch_scores)

        # Sort by overall score
        scored.sort(key=lambda x: x.overall_score, reverse=True)
        return scored

    def _evaluate_batch(self, memes: list[MemeIdea]) -> list[ScoredMeme]:
        """Evaluate a single batch of memes."""
        # Format memes for the prompt
        meme_text = ""
        for i, meme in enumerate(memes, 1):
            meme_text += f"""
MEME {i}:
Template: {meme.format}
Top text: {meme.top_text}
Bottom text: {meme.bottom_text}
Context: {meme.explanation[:200] if meme.explanation else 'N/A'}
"""

        prompt = f"""You are evaluating bluegrass music meme concepts. Score each meme on three criteria:

1. HUMOR (1-10): Is it actually funny? Would bluegrass fans laugh?
   - 1-3: Not funny, forced, or doesn't make sense
   - 4-6: Mildly amusing, average humor
   - 7-8: Genuinely funny, good comedic timing
   - 9-10: Hilarious, would go viral in bluegrass community

2. AUTHENTICITY (1-10): Does it reflect real bluegrass culture?
   - 1-3: Generic, could apply to any music genre
   - 4-6: Somewhat bluegrass-specific
   - 7-8: Clearly from someone who knows bluegrass
   - 9-10: Deep cut that only real fans would get

3. TEMPLATE_FIT (1-10): Does the text work with this meme format?
   - 1-3: Wrong template choice, text doesn't fit the format
   - 4-6: Okay fit, but not ideal
   - 7-8: Good match between template and content
   - 9-10: Perfect use of the template

Here are the memes to evaluate:
{meme_text}

For each meme, respond with this EXACT format (one per meme):
MEME 1: HUMOR=X AUTHENTICITY=X TEMPLATE_FIT=X
REASON: Brief explanation

MEME 2: HUMOR=X AUTHENTICITY=X TEMPLATE_FIT=X
REASON: Brief explanation

...and so on for each meme."""

        response = self.client._chat(
            messages=[{"role": "user", "content": prompt}],
            model="grok-3-mini",  # Fast model for evaluation
            temperature=0.3,  # Lower temp for more consistent scoring
            max_tokens=1500,
        )

        return self._parse_scores(memes, response)

    def _parse_scores(self, memes: list[MemeIdea], response: str) -> list[ScoredMeme]:
        """Parse the evaluation response into ScoredMeme objects."""
        scored = []
        lines = response.strip().split('\n')

        current_meme_idx = None
        current_scores = {}
        current_reason = ""

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for "MEME N:" line
            if line.upper().startswith("MEME "):
                # Save previous meme if exists
                if current_meme_idx is not None and current_scores:
                    scored.append(self._create_scored_meme(
                        memes[current_meme_idx],
                        current_scores,
                        current_reason
                    ))

                # Parse new meme scores
                try:
                    # Extract meme number
                    parts = line.split(":")
                    meme_num = int(parts[0].replace("MEME", "").strip()) - 1
                    current_meme_idx = meme_num
                    current_scores = {}
                    current_reason = ""

                    # Parse scores from rest of line
                    score_part = parts[1] if len(parts) > 1 else ""
                    for score_type in ["HUMOR", "AUTHENTICITY", "TEMPLATE_FIT"]:
                        if score_type + "=" in score_part.upper():
                            # Find the score value
                            idx = score_part.upper().find(score_type + "=")
                            val_str = score_part[idx + len(score_type) + 1:].split()[0]
                            # Clean up the value
                            val_str = ''.join(c for c in val_str if c.isdigit() or c == '.')
                            if val_str:
                                current_scores[score_type.lower()] = float(val_str)
                except (ValueError, IndexError):
                    continue

            elif line.upper().startswith("REASON:"):
                current_reason = line.split(":", 1)[1].strip() if ":" in line else ""

        # Don't forget the last meme
        if current_meme_idx is not None and current_scores:
            scored.append(self._create_scored_meme(
                memes[current_meme_idx],
                current_scores,
                current_reason
            ))

        # Warn if parse rate is low
        if scored and len(scored) < len(memes) * 0.5:
            print(f"  Warning: parsed scores for {len(scored)}/{len(memes)} memes — possible format drift")

        # Handle case where parsing failed - assign default scores
        parsed_ids = set(id(s.idea) for s in scored)
        for meme in memes:
            if id(meme) not in parsed_ids:
                scored.append(ScoredMeme(
                    idea=meme,
                    humor_score=5.0,
                    authenticity_score=5.0,
                    template_fit_score=5.0,
                    overall_score=5.0,
                    reasoning="(Unable to parse score)"
                ))

        return scored

    def _create_scored_meme(
        self,
        meme: MemeIdea,
        scores: dict,
        reason: str
    ) -> ScoredMeme:
        """Create a ScoredMeme from parsed scores."""
        humor = scores.get("humor", 5.0)
        auth = scores.get("authenticity", 5.0)
        fit = scores.get("template_fit", 5.0)

        # Weighted overall score (humor matters most for memes)
        overall = (humor * 0.5) + (auth * 0.3) + (fit * 0.2)

        return ScoredMeme(
            idea=meme,
            humor_score=humor,
            authenticity_score=auth,
            template_fit_score=fit,
            overall_score=overall,
            reasoning=reason,
        )

    def get_top_n(
        self,
        memes: list[MemeIdea],
        n: int = 5,
    ) -> list[ScoredMeme]:
        """
        Evaluate all memes and return the top N.

        Args:
            memes: List of meme concepts
            n: Number of top memes to return

        Returns:
            Top N memes sorted by score
        """
        scored = self.evaluate_batch(memes)
        return scored[:n]


if __name__ == "__main__":
    # Quick test with mock data
    from .grok import MemeIdea

    test_memes = [
        MemeIdea(
            format="Drake Meme",
            top_text="Electric banjo",
            bottom_text="Acoustic banjo with that Earl Scruggs roll",
            explanation="Bluegrass purists hate electric instruments",
            source_quote="",
            artist_reference="Earl Scruggs",
        ),
        MemeIdea(
            format="Change My Mind",
            top_text="Bill Monroe sitting at table",
            bottom_text="If it ain't got mandolin chop, it ain't bluegrass",
            explanation="Monroe was famously strict about bluegrass definition",
            source_quote="",
            artist_reference="Bill Monroe",
        ),
    ]

    evaluator = MemeEvaluator()
    scored = evaluator.evaluate_batch(test_memes)

    print("Evaluation results:")
    for s in scored:
        print(f"\n{s}")
