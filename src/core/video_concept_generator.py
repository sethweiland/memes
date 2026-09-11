"""
Video ad concept generator using Grok.
Generates structured VideoAdConcept objects from topics and context.
"""

import re

from .grok import GrokClient
from .video_dataclasses import VideoAdConcept, VideoScene


class VideoConceptGenerator:
    """
    Generate video ad concepts using Grok.
    Follows the same structured-field parsing pattern as GrokClient._parse_meme_response.
    """

    def __init__(self, grok: GrokClient | None = None):
        self.grok = grok or GrokClient()

    def generate_concepts(
        self,
        topic: str,
        context_text: str = "",
        num_concepts: int = 5,
        num_scenes: int = 2,
        target_duration: float = 7.0,
        creativity: float = 1.0,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
    ) -> list[VideoAdConcept]:
        """
        Generate video ad concepts.

        Args:
            topic: The ad topic / product / brand
            context_text: Web search or RAG context
            num_concepts: Number of concepts to generate
            num_scenes: Scenes per concept (1-3)
            target_duration: Target video duration in seconds
            creativity: Temperature for generation
            system_prompt: Override system prompt (from Jinja2 template)
            user_prompt: Override user prompt (from Jinja2 template)
        """
        if system_prompt is None:
            system_prompt = self._default_system_prompt()

        if user_prompt is None:
            user_prompt = self._default_user_prompt(
                topic, context_text, num_concepts, num_scenes, target_duration
            )

        response = self.grok._chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], max_tokens=4000, temperature=creativity)

        return self._parse_video_response(response, num_scenes)

    def _default_system_prompt(self) -> str:
        return """You are an expert creative director for short-form video ads (5-10 seconds).

You create punchy, scroll-stopping video ad concepts that work on TikTok, Instagram Reels, and YouTube Shorts.

Your ads should:
- HOOK in the first 2 seconds — the visual must stop the scroll
- Keep it SIMPLE — one clear message per ad, no clutter
- Make the CTA feel natural, not forced
- Use specific, vivid visual descriptions that AI video generators can produce
- Write voiceover scripts that are conversational, not corporate
- Think mobile-first — bold visuals, readable text overlays

WHAT MAKES A GREAT 5-10 SECOND AD:
- Emotional or surprising opening shot
- One key message or value proposition
- Clear call-to-action that flows from the message
- Consistent visual tone throughout"""

    def _default_user_prompt(
        self,
        topic: str,
        context_text: str,
        num_concepts: int,
        num_scenes: int,
        target_duration: float,
    ) -> str:
        context_section = ""
        if context_text:
            context_section = f"""
CONTEXT (use for relevant facts, angles, or inspiration):
{context_text}
"""

        scene_instructions = ""
        for i in range(1, num_scenes + 1):
            scene_instructions += f"""SCENE_{i}_VISUAL: Describe what the viewer sees (be specific enough for AI video generation)
SCENE_{i}_VOICEOVER: What is spoken during this scene
SCENE_{i}_TEXT: On-screen text overlay (or "none")
SCENE_{i}_DURATION: Duration in seconds (e.g., 3.0)
"""

        return f"""Topic: {topic}
{context_section}
Generate {num_concepts} video ad concepts. Each ad should be {target_duration:.0f} seconds total with {num_scenes} scene(s).

Use this EXACT format for each concept (no markdown, no numbering):

TITLE: working title for the concept
HOOK: the attention-grabbing opening (what makes someone stop scrolling)
{scene_instructions}CTA_TEXT: call-to-action text shown on screen
CTA_VOICEOVER: spoken call-to-action
TONE: the overall feel (e.g., energetic, emotional, humorous, informative)
AUDIENCE: who this ad targets
EXPLANATION: why this concept works

---

TITLE: next concept...
"""

    def _parse_video_response(
        self,
        response: str,
        num_scenes: int = 2,
    ) -> list[VideoAdConcept]:
        """Parse Grok's response into VideoAdConcept objects."""
        concepts = []

        # Split on "---" separators
        sections = re.split(
            r'(?:^|\n)---\s*\n|(?:\n\s*\n)(?=TITLE:)',
            response,
            flags=re.IGNORECASE
        )

        for section in sections:
            section = section.strip()
            if not section:
                continue

            concept = self._parse_single_concept(section, num_scenes)
            if concept and (concept.title or concept.scenes):
                concepts.append(concept)

        if len(sections) > 1 and len(concepts) < len(sections) * 0.5:
            print(f"  Warning: parsed {len(concepts)} concepts from {len(sections)} sections")

        return concepts

    def _parse_single_concept(
        self,
        section: str,
        num_scenes: int,
    ) -> VideoAdConcept | None:
        """Parse a single concept section."""
        fields: dict[str, str] = {}
        lines = section.split('\n')
        current_field = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Skip headers like "**Concept 1**"
            if line.startswith("**") and line.endswith("**"):
                continue
            if line.startswith("#"):
                continue

            line = line.lstrip("*").strip()
            upper = line.upper()

            # Check for field markers
            matched = False
            for prefix in [
                "TITLE:", "HOOK:",
                "CTA_TEXT:", "CTA TEXT:", "CTA_VOICEOVER:", "CTA VOICEOVER:",
                "TONE:", "AUDIENCE:", "EXPLANATION:",
            ]:
                if upper.startswith(prefix):
                    field_name = prefix.rstrip(":").replace(" ", "_").lower()
                    fields[field_name] = line.split(":", 1)[1].strip()
                    current_field = field_name
                    matched = True
                    break

            if not matched:
                # Check scene fields: SCENE_N_VISUAL, SCENE_N_VOICEOVER, etc.
                scene_match = re.match(
                    r'SCENE[_\s]*(\d+)[_\s]*(VISUAL|VOICEOVER|TEXT|DURATION)\s*:',
                    line, re.IGNORECASE
                )
                if scene_match:
                    scene_num = scene_match.group(1)
                    field_type = scene_match.group(2).lower()
                    field_name = f"scene_{scene_num}_{field_type}"
                    fields[field_name] = line.split(":", 1)[1].strip()
                    current_field = field_name
                elif current_field:
                    # Continuation of previous field
                    fields[current_field] = fields[current_field] + " " + line

        if not fields:
            return None

        # Build scenes
        scenes = []
        for i in range(1, num_scenes + 1):
            visual = fields.get(f"scene_{i}_visual", "")
            voiceover = fields.get(f"scene_{i}_voiceover", "")
            text = fields.get(f"scene_{i}_text", "")
            duration_str = fields.get(f"scene_{i}_duration", "")

            if text.lower() in ("none", "n/a", ""):
                text = ""

            # Parse duration
            try:
                duration = float(''.join(c for c in duration_str if c.isdigit() or c == '.') or "3.0")
            except ValueError:
                duration = 3.0

            if visual or voiceover:
                scenes.append(VideoScene(
                    scene_number=i,
                    duration_seconds=duration,
                    visual_prompt=visual,
                    voiceover_text=voiceover,
                    text_overlay=text,
                ))

        # Calculate total duration from scenes
        total_duration = sum(s.duration_seconds for s in scenes) if scenes else 7.0

        return VideoAdConcept(
            title=fields.get("title", ""),
            hook=fields.get("hook", ""),
            scenes=scenes,
            cta_text=fields.get("cta_text", ""),
            cta_voiceover=fields.get("cta_voiceover", ""),
            total_duration=total_duration,
            tone=fields.get("tone", ""),
            target_audience=fields.get("audience", ""),
            explanation=fields.get("explanation", ""),
        )

    def close(self):
        self.grok.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
