"""
Meme image generator using imgflip API.
Takes meme concepts and creates actual images.
"""

import os
from dataclasses import dataclass
from pathlib import Path

import httpx

from .templates import TemplatesCatalog, MemeTemplate
from .grok import MemeIdea
from .evaluator import ScoredMeme


@dataclass
class GeneratedMeme:
    """A generated meme image."""
    idea: MemeIdea
    template: MemeTemplate
    image_url: str
    page_url: str
    local_path: str | None = None
    score: float | None = None
    caption: str | None = None  # Social media caption with historical context


class MemeImageGenerator:
    """Generate meme images using imgflip API."""

    CAPTION_URL = "https://api.imgflip.com/caption_image"

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        output_dir: str = "output/memes",
    ):
        """
        Args:
            username: imgflip username (or IMGFLIP_USERNAME env var)
            password: imgflip password (or IMGFLIP_PASSWORD env var)
            output_dir: Directory to save downloaded images
        """
        self.username = username or os.getenv("IMGFLIP_USERNAME")
        self.password = password or os.getenv("IMGFLIP_PASSWORD")

        if not self.username or not self.password:
            raise ValueError(
                "imgflip credentials required. Set IMGFLIP_USERNAME and IMGFLIP_PASSWORD "
                "in .env or pass to constructor. Sign up free at imgflip.com"
            )

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.catalog = TemplatesCatalog()
        self.client = httpx.Client(timeout=30.0)

    def generate(
        self,
        idea: MemeIdea,
        template: MemeTemplate | None = None,
        download: bool = True,
    ) -> GeneratedMeme:
        """
        Generate a meme image from an idea.

        Args:
            idea: The meme concept
            template: Specific template to use (or auto-match from idea.format)
            download: Whether to download the image locally

        Returns:
            GeneratedMeme with URLs and optional local path
        """
        # Find template if not provided
        if template is None:
            template = self.catalog.find_best_match(idea.format)
            if template is None:
                raise ValueError(f"Could not find template for: {idea.format}")

        # Prepare text boxes based on template box count
        boxes = self._prepare_boxes(idea, template)

        # Call imgflip API
        data = {
            "template_id": template.id,
            "username": self.username,
            "password": self.password,
        }

        # Add boxes
        for i, box in enumerate(boxes):
            data[f"boxes[{i}][text]"] = box

        response = self.client.post(self.CAPTION_URL, data=data)
        response.raise_for_status()
        result = response.json()

        if not result.get("success"):
            raise RuntimeError(f"imgflip error: {result.get('error_message', 'Unknown error')}")

        image_url = result["data"]["url"]
        page_url = result["data"]["page_url"]

        # Download image if requested
        local_path = None
        if download:
            local_path = self._download_image(image_url, idea.format)

        return GeneratedMeme(
            idea=idea,
            template=template,
            image_url=image_url,
            page_url=page_url,
            local_path=local_path,
        )

    def _prepare_boxes(self, idea: MemeIdea, template: MemeTemplate) -> list[str]:
        """Prepare text boxes for the template."""
        import re

        # Clean text of formatting markers
        def clean_text(text: str) -> str:
            if not text:
                return ""
            # Remove markers like BUTTON_1:, MIDDLE_TEXT:, TOP_TEXT_1:, etc.
            text = re.sub(r'\b(BUTTON_?\d*|MIDDLE_TEXT|TOP_TEXT_?\d*|BOTTOM_TEXT_?\d*|TEXT_?\d*):\s*', '', text)
            # Remove leftover markers at start
            text = re.sub(r'^[\s:]+', '', text)
            return text.strip()

        # Try to extract multiple texts from markers or "/" separators
        def extract_panels(text: str) -> list[str]:
            if not text:
                return []
            # First try splitting on explicit markers
            parts = re.split(r'\s*(?:BUTTON_?\d+|TOP_TEXT_?\d+|MIDDLE_TEXT|BOTTOM_TEXT_?\d+|TEXT_?\d+):\s*', text)
            parts = [p.strip() for p in parts if p.strip()]

            # If that didn't split anything, try splitting on " / " (Grok's multi-panel separator)
            if len(parts) == 1 and " / " in text:
                parts = [p.strip() for p in text.split(" / ") if p.strip()]

            return parts

        boxes = []

        # For multi-panel templates (3+ boxes), try to extract panels
        if template.box_count >= 3:
            # Combine top and bottom text, checking both for "/" separators
            top_panels = extract_panels(idea.top_text or "")
            bottom_panels = extract_panels(idea.bottom_text or "")

            # If top_text has enough panels, use those
            if len(top_panels) >= template.box_count:
                boxes = top_panels[:template.box_count]
            # If bottom_text has the multi-panel content (common pattern)
            elif len(bottom_panels) >= template.box_count - 1:
                boxes = top_panels[:1] + bottom_panels
            else:
                # Combine both
                boxes = top_panels + bottom_panels
        else:
            # Standard 2-box template
            boxes.append(clean_text(idea.top_text))
            boxes.append(clean_text(idea.bottom_text))

        # Ensure we have enough boxes (pad with empty)
        while len(boxes) < template.box_count:
            boxes.append("")

        # Clean all boxes
        boxes = [clean_text(b) for b in boxes]

        return boxes[:template.box_count]

    def _download_image(self, url: str, name: str) -> str:
        """Download image to local directory."""
        # Clean up name for filename
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in name)
        safe_name = safe_name[:50]  # Limit length

        # Find unique filename
        base_path = self.output_dir / f"{safe_name}.jpg"
        path = base_path
        counter = 1
        while path.exists():
            path = self.output_dir / f"{safe_name}_{counter}.jpg"
            counter += 1

        # Download
        response = self.client.get(url)
        response.raise_for_status()

        with open(path, 'wb') as f:
            f.write(response.content)

        return str(path)

    def generate_batch(
        self,
        scored_memes: list[ScoredMeme],
        limit: int = 5,
        download: bool = True,
    ) -> list[GeneratedMeme]:
        """
        Generate images for top scored memes.

        Args:
            scored_memes: List of ScoredMeme objects (should be pre-sorted)
            limit: Max number of images to generate
            download: Whether to download images locally

        Returns:
            List of GeneratedMeme objects
        """
        generated = []

        for scored in scored_memes[:limit]:
            try:
                meme = self.generate(scored.idea, download=download)
                meme.score = scored.overall_score
                generated.append(meme)
                print(f"Generated: {meme.template.name} (score: {scored.overall_score:.1f})")
            except Exception as e:
                print(f"Failed to generate '{scored.idea.format}': {e}")

        return generated

    def close(self):
        """Close HTTP client."""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    # Quick test
    try:
        gen = MemeImageGenerator()
        print(f"Generator ready, output dir: {gen.output_dir}")

        # Test with a simple meme
        test_idea = MemeIdea(
            format="Drake Hotline Bling",
            top_text="Learning guitar from YouTube",
            bottom_text="Learning from a bluegrass jam session",
            explanation="",
            source_quote="",
            artist_reference="",
        )

        result = gen.generate(test_idea)
        print(f"Generated: {result.image_url}")
        print(f"Saved to: {result.local_path}")

    except ValueError as e:
        print(f"Setup needed: {e}")
