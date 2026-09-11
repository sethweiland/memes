"""
Two-stage meme generation pipeline (human-in-the-loop).
Stage 1: Generate freely without explanation.
Stage 2: Evaluate using domain-specific criteria.

Supports both domain-specific (TwoStagePipeline) and generic (GenericTwoStagePipeline) modes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Union

from .grok import MemeIdea, GrokClient
from .openai_provider import OpenAIResponsesClient
from .meme_generator import GeneratedMeme, MemeImageGenerator
from .templates import TemplatesCatalog
from .taste_examples import format_taste_examples

if TYPE_CHECKING:
    from .pipeline import MemePipeline, PipelineConfig
    from .generic_config import GenericConfig


@dataclass
class EvaluatedMeme:
    """A meme with evaluation scores for human review."""
    idea: MemeIdea
    scores: dict[str, int]        # Criterion name -> score (1-10)
    overall_score: float          # Weighted combination
    evaluation_notes: str         # AI's notes on the meme
    is_absurdist: bool = False    # Flag for intentional absurdism
    template_category: str = ""   # "trending", "new", "classic", or ""
    generation_source: str = ""   # e.g. "critic_rewrite"

    def get_score(self, criterion: str) -> int:
        """Get score for a specific criterion."""
        return self.scores.get(criterion, 0)

    def to_dict(self) -> dict:
        result = {
            "format": self.idea.format,
            "top_text": self.idea.top_text,
            "bottom_text": self.idea.bottom_text,
            "overall_score": self.overall_score,
            "evaluation_notes": self.evaluation_notes,
            "is_absurdist": self.is_absurdist,
            "template_category": self.template_category,
        }
        # Add individual scores
        result.update(self.scores)
        return result


def _format_context_text(context: list[dict], current_events_context: str = "", max_chars: int = 600) -> str:
    """Format RAG context and current events into text for LLM prompts."""
    context_text = "\n\n".join([
        f"[{c['metadata'].get('source', 'Unknown')}]\n{c['text'][:max_chars]}"
        for c in context
    ])
    if current_events_context:
        context_text += f"\n\nCURRENT NEWS & EVENTS (use for timely memes):\n{current_events_context}"
    return context_text


class TwoStagePipeline:
    """
    Wraps a MemePipeline to provide two-stage generation with human review.

    Usage:
        pipeline = MemePipeline(config, PipelineConfig(...))
        two_stage = TwoStagePipeline(pipeline)
        evaluated = two_stage.run("banjo memes")
        # Human reviews and picks indices...
        images = two_stage.generate_selected(evaluated, [1, 3, 5])
    """

    def __init__(self, pipeline: "MemePipeline"):
        self.pipeline = pipeline

    @property
    def config(self):
        return self.pipeline.config

    @property
    def domain(self):
        return self.pipeline.domain

    @property
    def rag(self):
        return self.pipeline.rag

    @property
    def prompts(self):
        return self.pipeline.prompts

    def generate_freely(
        self,
        topic: str,
        context_text: str,
        template_catalog: str,
        num_ideas: int = 10,
        previously_covered: list[str] | None = None,
        previously_used_templates: list[str] | None = None,
        trending_section: str = "",
        creative_brief: str = "",
    ) -> list[MemeIdea]:
        """
        Stage 1: Generate memes WITHOUT explanation requirement.
        Higher creativity, no justification needed = more unexpected ideas.

        Args:
            previously_covered: Topics/references from prior batches to avoid repeating
            previously_used_templates: Template names already used - avoid reusing
            trending_section: Optional trending templates section to inject
        """
        # Get trending templates if not provided
        if not trending_section:
            try:
                from .trending_templates import get_trending_prompt_section
                trending_section = get_trending_prompt_section()
            except Exception:
                trending_section = ""

        if self.prompts.has_template("system_generation_free"):
            system_prompt = self.prompts.render("system_generation_free")
        else:
            system_prompt = f"""You are a comedy writer for {self.domain.display_name.lower()} memes.
Be weird, unexpected, creative. Take risks. No explanations needed - just write funny memes."""

        if self.prompts.has_template("user_generation_free"):
            user_prompt = self.prompts.render(
                "user_generation_free",
                topic=topic,
                context_text=context_text,
                template_catalog=template_catalog,
                num_ideas=num_ideas,
                trending_section=trending_section,
            )
        else:
            user_prompt = f"""Topic: {topic}

CONTEXT FROM {self.domain.content_source_description.upper()}:
{context_text}

{template_catalog}

{trending_section}

Generate {num_ideas} memes. Be creative, unexpected, absurdist. Take risks.
DON'T explain why they're funny - just write them.

TEMPLATE REQUIREMENTS — STRICT:
- EVERY meme must use a DIFFERENT template (no duplicates!)
- PRIORITIZE ✨ FRESH FORMATS — use at least 50% of your memes with new/fresh templates
- Use remaining slots for 🔥 HOT RIGHT NOW and 👑 CLASSICS
- Spread across ALL categories, don't cluster on the same few templates

Use EXACT format:

FORMAT: template name
TOP_TEXT: top text
BOTTOM_TEXT: bottom text

---

FORMAT: next template..."""

        if creative_brief:
            user_prompt += f"\n\n{creative_brief}"

        # Diversity instructions
        user_prompt += "\n\nDIVERSITY REQUIREMENTS (MANDATORY):"
        user_prompt += "\n- Each meme MUST use a DIFFERENT template. NO duplicate templates allowed."
        user_prompt += "\n- Each meme must reference a DIFFERENT topic, person, or situation."

        if previously_used_templates:
            # Deduplicate template list
            seen_templates = []
            for t in previously_used_templates:
                if t.lower() not in [s.lower() for s in seen_templates]:
                    seen_templates.append(t)
            template_avoid_list = ", ".join(seen_templates[:15])
            user_prompt += f"\n\nDO NOT use these templates (already used): {template_avoid_list}"

        if previously_covered:
            # Deduplicate and limit the list
            seen = []
            for t in previously_covered:
                if t not in seen:
                    seen.append(t)
            avoid_list = ", ".join(seen[:20])
            user_prompt += f"\nAvoid these topics already covered: {avoid_list}"

        response = self.rag.grok._chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], max_tokens=2000, temperature=self.config.generation_creativity)

        return self.rag.grok._parse_meme_response(response)

    def evaluate_for_review(
        self,
        memes: list[MemeIdea],
        context_text: str,
    ) -> list[EvaluatedMeme]:
        """
        Stage 2: Evaluate memes using domain-specific criteria.
        Returns ALL memes with scores - human makes final selection.
        """
        if not memes:
            return []

        meme_list = ""
        for i, m in enumerate(memes, 1):
            meme_list += f"""
MEME {i}:
Template: {m.format}
Top: {m.top_text}
Bottom: {m.bottom_text}
"""

        criteria_section = self.domain.get_evaluation_prompt_section()
        criteria_names = [c.name.upper() for c in self.domain.evaluation_criteria]
        score_format = " ".join([f"{name}=X" for name in criteria_names])

        prompt = f"""You are evaluating {self.domain.display_name.lower()} memes. Score each on these criteria:

{criteria_section}

CONTEXT (use this to verify accuracy):
{context_text}

MEMES TO EVALUATE:
{meme_list}

For each meme, respond with:
MEME 1: {score_format}
NOTES: Brief note on why it works (or doesn't)

MEME 2: {score_format}
NOTES: ...

Be STRICT on accuracy criteria. If a fact is made up, score it low."""

        response = self.rag.grok._chat([
            {"role": "user", "content": prompt}
        ], max_tokens=2000, temperature=0.3)

        return self._parse_evaluations(memes, response)

    def _parse_evaluations(
        self,
        memes: list[MemeIdea],
        response: str,
    ) -> list[EvaluatedMeme]:
        """Parse evaluation response into EvaluatedMeme objects."""
        evaluated = []
        lines = response.strip().split('\n')

        current_idx = None
        current_scores: dict[str, int] = {}
        current_notes = ""

        criterion_names = {c.name.upper(): c.name for c in self.domain.evaluation_criteria}

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.upper().startswith("MEME "):
                if current_idx is not None and current_scores:
                    evaluated.append(self._create_evaluated_meme(
                        memes[current_idx] if current_idx < len(memes) else None,
                        current_scores,
                        current_notes
                    ))

                try:
                    parts = line.split(":", 1)
                    meme_num = int(parts[0].replace("MEME", "").strip()) - 1
                    current_idx = meme_num
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

        if current_idx is not None and current_scores:
            evaluated.append(self._create_evaluated_meme(
                memes[current_idx] if current_idx < len(memes) else None,
                current_scores,
                current_notes
            ))

        evaluated = [e for e in evaluated if e is not None]
        evaluated.sort(key=lambda x: x.overall_score, reverse=True)

        if evaluated and len(evaluated) < len(memes) * 0.5:
            print(f"  Warning: parsed evaluations for {len(evaluated)}/{len(memes)} memes — possible format drift")

        return evaluated

    def _create_evaluated_meme(
        self,
        meme: MemeIdea | None,
        scores: dict[str, int],
        notes: str,
    ) -> EvaluatedMeme | None:
        """Create EvaluatedMeme from parsed scores."""
        if meme is None:
            return None

        overall = self.domain.calculate_overall_score(scores)
        is_absurdist = self.domain.is_potential_absurdism(scores)

        # Look up template category
        template_category = ""
        try:
            from .trending_templates import get_template_category
            template_category = get_template_category(meme.format) or ""
        except Exception:
            pass

        return EvaluatedMeme(
            idea=meme,
            scores=scores,
            overall_score=overall,
            evaluation_notes=notes,
            is_absurdist=is_absurdist,
            template_category=template_category,
        )

    def review_candidates(
        self,
        evaluated: list[EvaluatedMeme],
        num_to_review: int | None = None,
    ) -> None:
        """
        Present memes for human review.
        Shows scores as guidance but emphasizes human decision-making.
        """
        num_to_review = num_to_review or self.config.num_to_review
        to_show = evaluated[:num_to_review]

        print(f"\n{'='*70}")
        print(f"MEMES FOR HUMAN REVIEW ({len(to_show)} of {len(evaluated)})")
        print("Scores are guidance - YOU make the final call!")
        print(f"{'='*70}")

        for i, e in enumerate(to_show, 1):
            print(f"\n{'─'*60}")
            print(f"#{i} - {e.idea.format}")
            print(f"{'─'*60}")
            print(f"Top: {e.idea.top_text}")
            print(f"Bottom: {e.idea.bottom_text}")

            print(f"\n📊 SCORES:")
            for crit in self.domain.evaluation_criteria:
                score = e.scores.get(crit.name, 0)
                note = ""
                if crit.low_score_note and score < 4:
                    note = f" ⚠️ ({crit.low_score_note})"
                print(f"   {crit.display_name}: {score}/10{note}")

            print(f"   Overall: {e.overall_score:.1f}/10")
            print(f"\n📝 AI Notes: {e.evaluation_notes}")

            if e.is_absurdist:
                print(f"\n🎭 NOTE: Low accuracy but decent humor - might be intentional absurdism!")

        print(f"\n{'='*70}")
        print("HUMAN DECISION TIME")
        print(f"{'='*70}")
        print("Review the memes above. Pick which ones to generate images for.")
        print("Intentionally absurd memes (low accuracy, high humor) might still be great!")

    def run(
        self,
        topic: str,
        num_concepts: int | None = None,
        num_to_review: int | None = None,
    ) -> list[EvaluatedMeme]:
        """
        Run two-stage generation: generate freely, then evaluate.
        Returns evaluated memes for human selection.

        Args:
            topic: Meme topic/theme
            num_concepts: Override number of concepts to generate
            num_to_review: Override number to surface for review

        Returns:
            List of EvaluatedMeme for human review
        """
        num_concepts = num_concepts or self.config.num_concepts
        num_to_review = num_to_review or self.config.num_to_review

        print(f"\n{'='*70}")
        print(f"TWO-STAGE MEME GENERATION: {topic}")
        print(f"{'='*70}")

        # Fetch current events
        self.pipeline._fetch_current_events()

        # Split current events into individual items for rotation
        ce_items = [
            item.strip() for item in (self.pipeline.current_events_context or "").split("\n")
            if item.strip()
        ]

        template_catalog = self.pipeline.catalog.get_prompt_catalog(limit=50, randomize=True)

        # Stage 1: Generate freely
        print(f"\n{'='*70}")
        print("STAGE 1: FREE GENERATION (no explanation required)")
        print(f"{'='*70}")

        all_memes = []
        used_chunk_ids: set[str] = set()
        previously_covered: list[str] = []
        batches_needed = (num_concepts + self.config.concepts_per_batch - 1) // self.config.concepts_per_batch

        for batch_num in range(batches_needed):
            remaining = num_concepts - len(all_memes)
            batch_size = min(self.config.concepts_per_batch, remaining)
            if batch_size <= 0:
                break

            # Per-batch context: exclude previously used chunks
            context = self.rag.get_context(
                topic,
                k=self.config.num_context_chunks,
                expand_query=self.config.expand_queries,
                exclude_ids=used_chunk_ids if used_chunk_ids else None,
            )
            used_chunk_ids.update(c['id'] for c in context)

            # Rotate current events across batches
            batch_ce = ""
            if ce_items:
                items_per_batch = max(1, min(2, len(ce_items)))
                start = (batch_num * items_per_batch) % len(ce_items)
                batch_ce_items = []
                for i in range(items_per_batch):
                    batch_ce_items.append(ce_items[(start + i) % len(ce_items)])
                batch_ce = "\n".join(batch_ce_items)

            context_text = _format_context_text(context, batch_ce)

            memes = self.generate_freely(
                topic=topic,
                context_text=context_text,
                template_catalog=template_catalog,
                num_ideas=batch_size,
                previously_covered=previously_covered if previously_covered else None,
            )
            all_memes.extend(memes)

            # Track topics for diversity in next batch
            for m in memes:
                refs = []
                if m.format:
                    refs.append(m.format)
                for text in [m.top_text or "", m.bottom_text or ""]:
                    words = [w for w in text.split() if w[0:1].isupper() and len(w) > 2]
                    refs.extend(words[:3])
                previously_covered.extend(refs)

            print(f"  Batch {batch_num + 1}/{batches_needed}: {len(memes)} memes")

        print(f"\nGenerated {len(all_memes)} memes")

        # Stage 2: Evaluate
        print(f"\n{'='*70}")
        print("STAGE 2: EVALUATION (scores as guidance, not filter)")
        print(f"{'='*70}")

        evaluated = self.evaluate_for_review(all_memes, context_text)
        print(f"Evaluated {len(evaluated)} memes")

        # Present for review
        self.review_candidates(evaluated, num_to_review)

        return evaluated

    def generate_selected(
        self,
        evaluated: list[EvaluatedMeme],
        indices: list[int],
    ) -> list[GeneratedMeme]:
        """
        Generate images for human-selected memes.

        Args:
            evaluated: List of evaluated memes from run()
            indices: 1-based indices of memes to generate (from review_candidates output)

        Returns:
            List of GeneratedMeme with local file paths
        """
        selected = [evaluated[i - 1].idea for i in indices if 0 < i <= len(evaluated)]

        if not selected:
            print("No valid memes selected.")
            return []

        print(f"\nGenerating {len(selected)} selected memes...")
        return self.pipeline.generate_images_from_concepts(selected, num_images=len(selected))


class GenericTwoStagePipeline:
    """
    Two-stage pipeline for generic (non-domain-specific) meme generation.

    Works without a domain RAG - uses web search or LLM knowledge only.

    Usage:
        from src.core.generic_config import get_generic_config
        from src.core.pipeline import PipelineConfig

        config = get_generic_config()
        pipe_config = PipelineConfig(...)
        two_stage = GenericTwoStagePipeline(config, pipe_config)
        evaluated = two_stage.generate_and_evaluate("elon musk memes", context_text)
    """

    def __init__(
        self,
        generic_config: "GenericConfig",
        pipe_config: "PipelineConfig",
        model: str = "gpt-5.4-mini",
    ):
        self.domain = generic_config  # Alias for compatibility
        self.config = pipe_config
        self.catalog = TemplatesCatalog()
        self._model = model
        self._grok: GrokClient | OpenAIResponsesClient | None = None
        self._generator: MemeImageGenerator | None = None

    @property
    def grok(self) -> GrokClient | OpenAIResponsesClient:
        """Lazy-load the configured text generation provider."""
        if self._grok is None:
            if self._model.startswith("gpt-"):
                self._grok = OpenAIResponsesClient(default_model=self._model)
            else:
                self._grok = GrokClient(default_model=self._model)
        return self._grok

    def _get_generator(self) -> MemeImageGenerator:
        """Lazy-load image generator."""
        if self._generator is None:
            self._generator = MemeImageGenerator(output_dir=self.config.output_dir)
        return self._generator

    def _detect_persona(self, topic: str) -> str:
        """
        Analyze the topic to determine the appropriate persona/tone for memes.

        Returns a persona description to inject into the generation prompt.
        """
        prompt = f"""Analyze this meme topic and determine the appropriate persona/tone:

Topic: {topic}

Consider:
1. What online community/subculture is this associated with?
2. What's their humor style? (ironic, sincere, absurdist, edgy, wholesome, self-deprecating, etc.)
3. What's their "vibe"? (terminally online, normie, professional, niche hobbyist, etc.)
4. What slang, references, or in-jokes would resonate?
5. What's considered "based" or authentic vs "cringe" in this community?

Respond with a SHORT (2-3 sentence) persona description that captures how memes for this community should feel. Be specific about tone and style. If this is a niche/terminally-online community, say so explicitly.

Example for "looksmaxxing": "Terminally online community with ironic self-awareness. Humor is self-deprecating yet aspirational, uses terms like 'mogging', 'glow-up', and rates things on scales. Memes should feel like they came from someone deep in the rabbit hole, not a normie observer."

Your response (just the persona, nothing else):"""

        try:
            response = self.grok._chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            return response.strip()
        except Exception:
            return ""

    def generate_freely(
        self,
        topic: str,
        context_text: str,
        template_catalog: str,
        num_ideas: int = 10,
        previously_covered: list[str] | None = None,
        previously_used_templates: list[str] | None = None,
        creative_brief: str = "",
        format_lane: str = "mixed",
    ) -> list[MemeIdea]:
        """
        Stage 1: Generate memes WITHOUT explanation requirement.
        Works with any topic, not just domain-specific ones.

        Args:
            topic: Meme topic
            context_text: Context from web search or empty string
            template_catalog: Available meme templates
            num_ideas: Number of ideas to generate
            previously_covered: Topics to avoid repeating
            previously_used_templates: Template names already used - avoid reusing
        """
        # Keep image rendering reliable: only offer templates from the renderable
        # imgflip catalog. Raw trending scrape names may not have captionable IDs.
        trending_section = ""

        # Detect persona/tone for this topic's community
        persona = self._detect_persona(topic)
        persona_section = ""
        if persona:
            persona_section = f"""
COMMUNITY PERSONA — Match this vibe:
{persona}

Your memes should feel like they came from someone IN this community, not an outside observer.
"""

        edge_level = getattr(self.config, "humor_edge", 7)
        if edge_level <= 3:
            edge_section = """
EDGE LEVEL: BRAND-SAFE
- Keep jokes broadly acceptable and non-edgy.
- Still avoid bland recap text; every meme needs a real punchline.
"""
        elif edge_level <= 7:
            edge_section = """
EDGE LEVEL: PAGE VOICE
- Write like a funny niche meme account, not a brand calendar.
- Roast behaviors, habits, gatekeeping, awkward social dynamics, and scene stereotypes.
- Mild sarcasm, self-owning, and chaotic festival/jam energy are encouraged.
"""
        else:
            edge_section = """
EDGE LEVEL: FERMENTED
- Be sharper, weirder, more deadpan, and less polished.
- Roast the scene from inside the scene. Make the account feel run by someone sleep-deprived at a campsite jam.
- Prefer unhinged specificity, social discomfort, petty musician behavior, and painfully true observations.
- Do not become hateful or target protected traits; aim sideways at culture and behavior.
"""

        system_prompt = f"""You are a professional comedy writer creating memes that make people actually laugh out loud.
{persona_section}
{edge_section}
HUMOR TECHNIQUES — Use these deliberately:

1. SUBVERT EXPECTATIONS: Setup creates one expectation → punchline goes somewhere completely different
2. SPECIFICITY OVER GENERALITY: Vague = not funny. Hyper-specific = hilarious
3. ESCALATION / ABSURDIST SPIRAL: Start normal → get progressively more unhinged
4. RELATABLE PAIN POINTS: Things that are painfully true but nobody says out loud
5. CONTRAST / JUXTAPOSITION: Put two incompatible things together
6. DEADPAN ABSURDISM: State something completely ridiculous as if it's normal

WHAT NOT TO DO:
- Don't explain the joke in the meme text
- Don't use "Nobody: / Absolutely nobody:" format (overused)
- Don't make generic observations that could apply to anything
- Don't write event recap text pretending to be a joke
- Don't cram unrelated context facts into one meme
- Don't sound like a sponsor post, local newspaper blurb, or family-friendly festival brochure
- Don't be safe — take actual creative risks

Write memes that feel fresh and internet-savvy. Go weird. Make it actually funny."""

        context_section = ""
        if context_text:
            context_section = f"""
CONTEXT (use this for relevant facts/references):
{context_text}
"""

        taste_examples = format_taste_examples(topic, limit=8)
        taste_section = ""
        if taste_examples:
            taste_section = f"""
{taste_examples}
"""

        if format_lane == "original":
            lane_requirements = """FORMAT LANE: ORIGINAL ASSETS ONLY
- Use ONLY Original locally rendered formats from the available list.
- Make these feel like native screenshots/posts/notifications/starter packs, not normal captioned templates.
- Prioritize believable fake UI text, painfully specific social situations, and concise observational jokes.
- Use Original Freestyle Card for weirder, more out-there ideas that do not fit fake social UI.
- Use Original Field Guide for "type of person/specimen" jokes.
- Use Original Classified Ad for fake marketplace, wanted, lost/found, or desperate-scene jokes.
- Use Original Fake Poll for false choices, social dilemmas, and rigged community votes.
- Do not use famous/imgflip templates in this lane."""
        elif format_lane == "classic":
            lane_requirements = """FORMAT LANE: KNOWN TEMPLATES ONLY
- Use ONLY classic/imgflip templates from the available list.
- Do not use Original locally rendered formats in this lane.
- Choose templates where the known meme grammar strengthens the joke."""
        else:
            lane_requirements = """FORMAT LANE: MIXED
- Use classic templates and original local formats where each is strongest."""

        user_prompt = f"""Topic: {topic}
{context_section}
{taste_section}
{template_catalog}

{creative_brief}

{lane_requirements}

Generate {num_ideas} memes.

TEMPLATE REQUIREMENTS — STRICT:
- EVERY meme must use a DIFFERENT template (no duplicates!)
- Use ONLY exact template names from AVAILABLE TEMPLATES above
- Prefer familiar, legible templates unless a fresher listed template fits the joke perfectly
- Use 25-40% Original locally rendered formats when the joke is a fake post, text message, notification, starter pack, or custom scene.
- Spread across categories, don't cluster on the same few templates

STYLE REQUIREMENTS:
- ONE JOKE PER MEME. No reference pileups.
- Make the joke understandable in under 2 seconds.
- Use context as seasoning, not the meal.
- Prefer painful community truths over factual summaries.
- Keep each text box short. If a panel needs more than 12 words, it probably is not a meme.
- At least 2 should be UNHINGED/ABSURDIST (intentionally weird)
- At least 2 should be HYPER-SPECIFIC (detailed scenarios)
- Aim for actual laughs, not polite smiles
- NO explanations — if you have to explain it, rewrite it

Use EXACT format:

FORMAT: template name
TOP_TEXT: top text
BOTTOM_TEXT: bottom text

---

FORMAT: next template..."""

        # Diversity instructions
        user_prompt += "\n\nDIVERSITY REQUIREMENTS (MANDATORY):"
        user_prompt += "\n- Each meme MUST use a DIFFERENT template. NO duplicate templates allowed."
        user_prompt += "\n- Each meme must reference a DIFFERENT angle, scenario, or joke."

        if previously_used_templates:
            # Deduplicate template list
            seen_templates = []
            for t in previously_used_templates:
                if t.lower() not in [s.lower() for s in seen_templates]:
                    seen_templates.append(t)
            template_avoid_list = ", ".join(seen_templates[:15])
            user_prompt += f"\n\nDO NOT use these templates (already used): {template_avoid_list}"

        if previously_covered:
            seen = []
            for t in previously_covered:
                if t not in seen:
                    seen.append(t)
            avoid_list = ", ".join(seen[:20])
            user_prompt += f"\nAvoid these angles already covered: {avoid_list}"

        response = self.grok._chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], max_tokens=2000, temperature=self.config.generation_creativity)

        return self.grok._parse_meme_response(response)

    def evaluate_for_review(
        self,
        memes: list[MemeIdea],
        context_text: str,
    ) -> list[EvaluatedMeme]:
        """
        Stage 2: Evaluate memes using generic criteria.
        Returns ALL memes with scores - human makes final selection.
        """
        if not memes:
            return []

        meme_list = ""
        for i, m in enumerate(memes, 1):
            meme_list += f"""
MEME {i}:
Template: {m.format}
Top: {m.top_text}
Bottom: {m.bottom_text}
"""

        criteria_section = self.domain.get_evaluation_prompt_section()
        criteria_names = [c.name.upper() for c in self.domain.evaluation_criteria]
        score_format = " ".join([f"{name}=X" for name in criteria_names])

        prompt = f"""You are evaluating memes. Score each on these criteria:

{criteria_section}

CONTEXT (for reference):
{context_text if context_text else "No additional context provided."}

MEMES TO EVALUATE:
{meme_list}

For each meme, respond with:
MEME 1: {score_format}
NOTES: Brief note on why it works (or doesn't)

MEME 2: {score_format}
NOTES: ...

Be STRICT on humor. If it's not actually funny, score it low."""
        prompt += f"""

HUMOR EDGE SETTING: {getattr(self.config, "humor_edge", 7)}/10
Penalize memes that are brand-safe but bland, overly wholesome, corporate, brochure-like, or just summarize context.
Penalize reference pileups: a meme with too many unrelated facts and no clean punchline should score low on humor.
Reward one clear comedic turn, painful truth, inside-scene specificity, deadpan absurdism, and jokes that sound postable by a real meme page.
"""

        response = self.grok._chat([
            {"role": "user", "content": prompt}
        ], max_tokens=2000, temperature=0.3)

        return self._parse_evaluations(memes, response)

    def _parse_evaluations(
        self,
        memes: list[MemeIdea],
        response: str,
    ) -> list[EvaluatedMeme]:
        """Parse evaluation response into EvaluatedMeme objects."""
        evaluated = []
        lines = response.strip().split('\n')

        current_idx = None
        current_scores: dict[str, int] = {}
        current_notes = ""

        criterion_names = {c.name.upper(): c.name for c in self.domain.evaluation_criteria}

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.upper().startswith("MEME "):
                if current_idx is not None and current_scores:
                    evaluated.append(self._create_evaluated_meme(
                        memes[current_idx] if current_idx < len(memes) else None,
                        current_scores,
                        current_notes
                    ))

                try:
                    parts = line.split(":", 1)
                    meme_num = int(parts[0].replace("MEME", "").strip()) - 1
                    current_idx = meme_num
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

        if current_idx is not None and current_scores:
            evaluated.append(self._create_evaluated_meme(
                memes[current_idx] if current_idx < len(memes) else None,
                current_scores,
                current_notes
            ))

        evaluated = [e for e in evaluated if e is not None]
        evaluated.sort(key=lambda x: x.overall_score, reverse=True)

        if evaluated and len(evaluated) < len(memes) * 0.5:
            print(f"  Warning: parsed evaluations for {len(evaluated)}/{len(memes)} memes — possible format drift")

        return evaluated

    def _create_evaluated_meme(
        self,
        meme: MemeIdea | None,
        scores: dict[str, int],
        notes: str,
    ) -> EvaluatedMeme | None:
        """Create EvaluatedMeme from parsed scores."""
        if meme is None:
            return None

        overall = self.domain.calculate_overall_score(scores)
        is_absurdist = self.domain.is_potential_absurdism(scores)

        # Look up template category
        template_category = ""
        try:
            from .trending_templates import get_template_category
            template_category = get_template_category(meme.format) or ""
        except Exception:
            pass

        return EvaluatedMeme(
            idea=meme,
            scores=scores,
            overall_score=overall,
            evaluation_notes=notes,
            is_absurdist=is_absurdist,
            template_category=template_category,
        )

    def generate_images_from_concepts(
        self,
        concepts: list[MemeIdea],
        num_images: int | None = None,
    ) -> list[GeneratedMeme]:
        """
        Generate images directly from concepts.

        Args:
            concepts: List of MemeIdea objects
            num_images: Number of images to generate

        Returns:
            List of GeneratedMeme with local file paths
        """
        num_images = num_images or self.config.num_images
        num_images = max(1, min(50, num_images))
        generator = self._get_generator()

        print(f"Generating {num_images} images...")
        generated = []

        for idea in concepts[:num_images]:
            try:
                meme = generator.generate(idea, download=True)
                generated.append(meme)
                print(f"  Generated: {meme.template.name}")
            except Exception as e:
                print(f"  Failed '{idea.format}': {e}")

        print(f"Generated {len(generated)} images")
        return generated

    def generate_captions(self, images: list[GeneratedMeme]) -> list[GeneratedMeme]:
        """
        Generate social media captions for each meme.

        Args:
            images: List of generated memes

        Returns:
            Same list with captions populated
        """
        print("Generating captions...")

        for img in images:
            idea = img.idea

            prompt = f"""Write a short social media caption (1-2 sentences) for this meme.

Meme template: {idea.format}
Top text: {idea.top_text}
Bottom text: {idea.bottom_text}

The caption should:
- Be witty or add context
- Sound natural for Instagram/Twitter
- NOT include hashtags

Just write the caption, nothing else."""

            try:
                caption = self.grok._chat([
                    {"role": "user", "content": prompt}
                ], max_tokens=150, temperature=0.7)
                img.caption = caption.strip()
            except Exception as e:
                print(f"  Caption failed for {img.template.name}: {e}")
                img.caption = ""

        print(f"Generated {len([i for i in images if i.caption])} captions")
        return images

    def generate_selected(
        self,
        evaluated: list[EvaluatedMeme],
        indices: list[int],
    ) -> list[GeneratedMeme]:
        """
        Generate images for human-selected memes.

        Args:
            evaluated: List of evaluated memes from evaluate_for_review()
            indices: 1-based indices of memes to generate

        Returns:
            List of GeneratedMeme with local file paths
        """
        selected = [evaluated[i - 1].idea for i in indices if 0 < i <= len(evaluated)]

        if not selected:
            print("No valid memes selected.")
            return []

        print(f"\nGenerating {len(selected)} selected memes...")
        return self.generate_images_from_concepts(selected, num_images=len(selected))
