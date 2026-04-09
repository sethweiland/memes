"""
Vision-based template description using Grok.
Downloads template images, analyzes them with Grok vision, and produces
structured descriptions for the meme catalog.
"""

import base64
import time
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from .grok import GrokClient


@dataclass
class DescriptionResult:
    """Result of analyzing a meme template image with vision."""
    template_id: str
    template_name: str
    description: str
    confidence: int  # 1-10
    panel_structure: str
    comedic_pattern: str
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.template_id,
            "name": self.template_name,
            "description": self.description,
            "confidence": self.confidence,
            "panel_structure": self.panel_structure,
            "comedic_pattern": self.comedic_pattern,
            "generated_at": self.generated_at,
        }


VISION_PROMPT = """Analyze this meme template image. This is a BLANK meme template (may have placeholder text or example text).

Provide the following information:

DESCRIPTION: Write 2-3 sentences describing the visual layout AND how to use this template. Mention: how many panels/sections, what characters or objects appear, what expressions they have, and what goes in each text area. For multi-panel templates, describe what happens in EACH panel in sequence (e.g., "Panel 1: character makes a bold claim. Panel 2: someone asks a follow-up. Panel 3: awkward silence. Panel 4: concern."). Explain the comedic progression, not just the visual layout. End with "Use for [pattern]."

PANEL_STRUCTURE: Describe the layout briefly (e.g., "2 panels top/bottom", "4 panels grid", "single image with top/bottom text")

COMEDIC_PATTERN: Name the comedic pattern in 2-5 words (e.g., "rejection vs approval", "escalating absurdity", "dramatic irony")

CONFIDENCE: Rate 1-10 how confident you are that you correctly identified this template and its standard usage:
- 8-10: You clearly recognize the template and know its standard meme usage
- 5-7: You can see the layout and guess the usage but aren't sure of the standard format
- 1-4: You're guessing or the image is unclear

Use this EXACT format (one field per line, no extra text):
DESCRIPTION: ...
PANEL_STRUCTURE: ...
COMEDIC_PATTERN: ...
CONFIDENCE: ..."""


class TemplateDescriber:
    """Analyzes meme template images using Grok vision to generate descriptions."""

    def __init__(self, grok_client: GrokClient | None = None):
        self.grok = grok_client or GrokClient()
        self._http = httpx.Client(timeout=30.0)

    def describe_template(self, template) -> DescriptionResult:
        """
        Analyze a template image and return a structured description.

        Args:
            template: MemeTemplate with id, name, url fields

        Returns:
            DescriptionResult with description, confidence, etc.
        """
        try:
            image_b64 = self._download_image_as_base64(template.url)
        except Exception as e:
            return DescriptionResult(
                template_id=template.id,
                template_name=template.name,
                description="",
                confidence=0,
                panel_structure="",
                comedic_pattern="",
                error=f"Image download failed: {e}",
            )

        try:
            response = self.grok._chat(
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}",
                            },
                        },
                        {
                            "type": "text",
                            "text": f"Template name: {template.name}\n\n{VISION_PROMPT}",
                        },
                    ],
                }],
                model="grok-2-vision-latest",
                temperature=0.3,
                max_tokens=500,
            )
            return self._parse_response(template.id, template.name, response)
        except Exception as e:
            return DescriptionResult(
                template_id=template.id,
                template_name=template.name,
                description="",
                confidence=0,
                panel_structure="",
                comedic_pattern="",
                error=f"Vision call failed: {e}",
            )

    def _download_image_as_base64(self, url: str) -> str:
        """Download an image and return its base64-encoded content."""
        response = self._http.get(url)
        response.raise_for_status()
        return base64.b64encode(response.content).decode("utf-8")

    def _parse_response(
        self, template_id: str, template_name: str, response: str
    ) -> DescriptionResult:
        """Parse the structured vision response into a DescriptionResult."""
        description = ""
        panel_structure = ""
        comedic_pattern = ""
        confidence = 0

        for line in response.strip().split("\n"):
            line = line.strip()
            if not line:
                continue

            upper = line.upper()
            if upper.startswith("DESCRIPTION:"):
                description = line.split(":", 1)[1].strip()
            elif upper.startswith("PANEL_STRUCTURE:") or upper.startswith("PANEL STRUCTURE:"):
                panel_structure = line.split(":", 1)[1].strip()
            elif upper.startswith("COMEDIC_PATTERN:") or upper.startswith("COMEDIC PATTERN:"):
                comedic_pattern = line.split(":", 1)[1].strip()
            elif upper.startswith("CONFIDENCE:"):
                val = line.split(":", 1)[1].strip()
                # Extract first number from the value
                digits = "".join(c for c in val.split()[0] if c.isdigit())
                if digits:
                    confidence = min(10, max(1, int(digits)))

        return DescriptionResult(
            template_id=template_id,
            template_name=template_name,
            description=description,
            confidence=confidence,
            panel_structure=panel_structure,
            comedic_pattern=comedic_pattern,
        )

    def close(self):
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
