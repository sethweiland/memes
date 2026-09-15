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
from .secrets import get_secret_value


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
    evaluation_notes: str = ""
    scores: dict | None = None
    overall_score: float | None = None
    grounding: dict | None = None


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
        self.username = username or get_secret_value("IMGFLIP_USERNAME", ("IMGFLIP_USERNAME", "imgflip_username"))
        self.password = password or get_secret_value("IMGFLIP_PASSWORD", ("IMGFLIP_PASSWORD", "imgflip_password"))

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

        if template.id.startswith("local:"):
            local_path = self._generate_local_template(idea, template)
            return GeneratedMeme(
                idea=idea,
                template=template,
                image_url="",
                page_url="",
                local_path=local_path,
            )

        if not self.username or not self.password:
            raise ValueError(
                "imgflip credentials required for imgflip templates. Set IMGFLIP_USERNAME "
                "and IMGFLIP_PASSWORD in .env or use an Original local format."
            )

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

    def _generate_local_template(self, idea: MemeIdea, template: MemeTemplate) -> str:
        """Render an original local meme format with Pillow."""
        from PIL import Image, ImageDraw, ImageFont

        def font(size: int, bold: bool = False):
            candidates = [
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
                "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
            ]
            for candidate in candidates:
                try:
                    return ImageFont.truetype(candidate, size)
                except OSError:
                    continue
            return ImageFont.load_default()

        boxes = self._prepare_boxes(idea, template)
        top = boxes[0] if boxes else ""
        bottom = boxes[1] if len(boxes) > 1 else ""

        img = Image.new("RGB", (template.width, template.height), "#f4f1ea")
        draw = ImageDraw.Draw(img)

        if template.id == "local:fake-social-post":
            self._draw_fake_social_post(draw, top, bottom, font)
        elif template.id == "local:fake-text-message":
            self._draw_fake_text_message(draw, top, bottom, font)
        elif template.id == "local:starter-pack":
            self._draw_starter_pack(draw, top, bottom, font)
        elif template.id == "local:fake-notification":
            self._draw_fake_notification(draw, top, bottom, font)
        elif template.id == "local:fake-poll":
            self._draw_fake_poll(draw, top, bottom, font)
        elif template.id == "local:classified-ad":
            self._draw_classified_ad(draw, top, bottom, font)
        elif template.id == "local:field-guide":
            self._draw_field_guide(draw, top, bottom, font)
        elif template.id == "local:freestyle-card":
            self._draw_freestyle_card(draw, top, bottom, font)
        else:
            self._draw_fake_social_post(draw, top, bottom, font)

        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in template.name)
        path = self.output_dir / f"{safe_name}_{os.urandom(3).hex()}.jpg"
        img.save(path, "JPEG", quality=92)
        return str(path)

    def _wrap_text(self, draw, text: str, font, max_width: int) -> list[str]:
        """Wrap text to fit a pixel width."""
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            bbox = draw.textbbox((0, 0), candidate, font=font)
            if bbox[2] - bbox[0] <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    def _draw_wrapped(self, draw, text: str, xy: tuple[int, int], font, fill: str, max_width: int, line_gap: int = 10) -> int:
        x, y = xy
        for line in self._wrap_text(draw, text, font, max_width):
            draw.text((x, y), line, font=font, fill=fill)
            bbox = draw.textbbox((x, y), line, font=font)
            y += (bbox[3] - bbox[1]) + line_gap
        return y

    def _draw_fake_social_post(self, draw, handle: str, post: str, font):
        name = handle.strip() or "local meme account"
        username = self._username_from_name(name)
        initials = "".join(part[0] for part in name.split()[:2]).upper() or "M"
        avatar_color = self._color_from_text(name)

        draw.rounded_rectangle((90, 145, 990, 810), radius=34, fill="#ffffff", outline="#d8d8d8", width=3)
        draw.ellipse((135, 205, 225, 295), fill=avatar_color)
        avatar_font = font(34, True)
        bbox = draw.textbbox((0, 0), initials, font=avatar_font)
        draw.text((180 - (bbox[2] - bbox[0]) / 2, 250 - (bbox[3] - bbox[1]) / 2 - 4), initials, font=avatar_font, fill="#ffffff")
        draw.text((250, 205), name, font=font(42, True), fill="#111111")
        draw.text((250, 258), username, font=font(30), fill="#6a6f73")
        draw.text((890, 214), "...", font=font(44, True), fill="#888888")
        self._draw_wrapped(draw, post, (135, 365), font(52, True), "#111111", 810, 16)
        draw.line((135, 692, 945, 692), fill="#e6e6e6", width=2)
        draw.text((135, 728), "reply", font=font(28), fill="#7a7a7a")
        draw.text((305, 728), "repost", font=font(28), fill="#7a7a7a")
        draw.text((500, 728), "like", font=font(28), fill="#7a7a7a")
        draw.text((660, 728), "send", font=font(28), fill="#7a7a7a")

    def _draw_fake_text_message(self, draw, first: str, reply: str, font):
        def bubble_height(text: str, bubble_font, max_width: int, min_height: int = 120) -> tuple[list[str], int]:
            lines = self._wrap_text(draw, text, bubble_font, max_width)
            line_heights = []
            for line in lines:
                bbox = draw.textbbox((0, 0), line, font=bubble_font)
                line_heights.append(bbox[3] - bbox[1])
            text_height = sum(line_heights) + max(0, len(lines) - 1) * 12
            return lines, max(min_height, text_height + 70)

        first_font = font(42)
        reply_font = font(42)
        first_lines, first_h = bubble_height(first, first_font, 540)
        reply_lines, reply_h = bubble_height(reply, reply_font, 520, min_height=150)
        first_top = 270
        first_bottom = first_top + first_h
        reply_top = first_bottom + 90
        reply_bottom = reply_top + reply_h

        if reply_bottom > 850:
            reply_font = font(36)
            reply_lines, reply_h = bubble_height(reply, reply_font, 520, min_height=140)
            reply_bottom = reply_top + reply_h
        if reply_bottom > 850:
            reply_lines = reply_lines[:4]
            if reply_lines:
                reply_lines[-1] = reply_lines[-1].rstrip(". ") + "..."
            reply_h = 330
            reply_bottom = reply_top + reply_h

        draw.rounded_rectangle((80, 110, 1000, 930), radius=46, fill="#ffffff")
        draw.text((120, 150), "Messages", font=font(42, True), fill="#111111")
        draw.rounded_rectangle((130, first_top, 760, first_bottom), radius=34, fill="#e8e8ec")
        y = first_top + 35
        for line in first_lines:
            draw.text((165, y), line, font=first_font, fill="#111111")
            bbox = draw.textbbox((165, y), line, font=first_font)
            y += (bbox[3] - bbox[1]) + 12

        draw.rounded_rectangle((320, reply_top, 940, reply_bottom), radius=34, fill="#1f7aff")
        y = reply_top + 35
        for line in reply_lines:
            draw.text((360, y), line, font=reply_font, fill="#ffffff")
            bbox = draw.textbbox((360, y), line, font=reply_font)
            y += (bbox[3] - bbox[1]) + 12
        draw.text((395, min(reply_bottom + 70, 875)), "Delivered", font=font(26), fill="#8a8a8a")

    def _draw_starter_pack(self, draw, title: str, items_text: str, font):
        draw.text((80, 80), title or "Starter pack", font=font(58, True), fill="#111111")
        items = [i.strip() for i in items_text.replace("\n", " / ").split(" / ") if i.strip()][:6]
        if not items:
            items = ["specific opinion", "too many tabs open", "one weird hill to die on", "group chat evidence"]
        cells = [(80, 210), (570, 210), (80, 500), (570, 500), (80, 790), (570, 790)]
        for item, (x, y) in zip(items, cells):
            draw.rounded_rectangle((x, y, x + 430, y + 210), radius=24, fill="#ffffff", outline="#d7d1c7", width=3)
            self._draw_wrapped(draw, item, (x + 28, y + 42), font(34, True), "#111111", 370, 10)

    def _draw_fake_notification(self, draw, source: str, notification: str, font):
        draw.rounded_rectangle((100, 250, 980, 600), radius=42, fill="#ffffff", outline="#d8d8d8", width=3)
        draw.rounded_rectangle((145, 300, 225, 380), radius=22, fill="#111111")
        draw.text((250, 298), source or "Notification", font=font(38, True), fill="#111111")
        draw.text((250, 345), "now", font=font(28), fill="#888888")
        self._draw_wrapped(draw, notification, (145, 435), font(46, True), "#111111", 790, 12)

    def _draw_fake_poll(self, draw, question: str, options_text: str, font):
        draw.rounded_rectangle((90, 130, 990, 910), radius=34, fill="#ffffff", outline="#d8d8d8", width=3)
        draw.text((135, 180), "scene poll", font=font(30, True), fill="#666666")
        self._draw_wrapped(draw, question or "choose your fighter", (135, 235), font(48, True), "#111111", 810, 12)
        options = [o.strip() for o in options_text.replace("\n", " / ").split(" / ") if o.strip()][:4]
        if not options:
            options = ["option one", "option two", "somehow both"]
        y = 430
        colors = ["#1f7aff", "#5f6368", "#34a853", "#fbbc04"]
        for i, option in enumerate(options):
            draw.rounded_rectangle((135, y, 945, y + 86), radius=20, fill="#f4f6f8", outline="#e0e0e0", width=2)
            bar_width = max(140, 650 - i * 110)
            draw.rounded_rectangle((135, y, 135 + bar_width, y + 86), radius=20, fill=colors[i % len(colors)])
            draw.text((165, y + 23), option, font=font(30, True), fill="#ffffff" if i < 3 else "#111111")
            y += 112

    def _draw_classified_ad(self, draw, headline: str, body: str, font):
        draw.rectangle((85, 85, 995, 995), fill="#fbf4df", outline="#2b2b2b", width=5)
        draw.text((125, 125), "CLASSIFIEDS", font=font(42, True), fill="#111111")
        draw.line((125, 185, 955, 185), fill="#111111", width=4)
        self._draw_wrapped(draw, headline or "For sale: one very specific problem", (125, 235), font(56, True), "#111111", 830, 12)
        draw.line((125, 410, 955, 410), fill="#b8aa88", width=2)
        self._draw_wrapped(draw, body, (125, 455), font(38), "#222222", 820, 12)
        draw.text((125, 900), "serious inquiries only / no lowballers", font=font(28, True), fill="#555555")

    def _draw_field_guide(self, draw, subject: str, traits_text: str, font):
        draw.rounded_rectangle((85, 85, 995, 995), radius=28, fill="#eef2e6", outline="#51614a", width=4)
        draw.text((125, 125), "FIELD GUIDE", font=font(34, True), fill="#51614a")
        self._draw_wrapped(draw, subject or "common jam circle specimen", (125, 185), font(56, True), "#111111", 820, 10)
        draw.rounded_rectangle((125, 340, 955, 560), radius=24, fill="#dbe5d2", outline="#91a385", width=3)
        draw.text((170, 390), "fig. 1", font=font(30, True), fill="#51614a")
        draw.line((260, 455, 860, 455), fill="#51614a", width=5)
        draw.ellipse((520, 405, 600, 485), fill="#51614a")
        traits = [t.strip() for t in traits_text.replace("\n", " / ").split(" / ") if t.strip()][:5]
        y = 620
        for trait in traits:
            draw.text((145, y), "-", font=font(34, True), fill="#51614a")
            y = self._draw_wrapped(draw, trait, (185, y), font(34, True), "#111111", 720, 8) + 8

    def _draw_freestyle_card(self, draw, title: str, body: str, font):
        draw.rectangle((0, 0, 1080, 1080), fill="#101014")
        draw.rounded_rectangle((85, 100, 995, 980), radius=36, fill="#f7f1e3", outline="#ffcc66", width=5)
        draw.text((125, 150), "UNOFFICIAL NOTICE", font=font(30, True), fill="#7a4d00")
        self._draw_wrapped(draw, title or "freestyle dispatch", (125, 240), font(64, True), "#111111", 830, 14)
        draw.line((125, 450, 955, 450), fill="#d8c89a", width=3)
        self._draw_wrapped(draw, body, (125, 505), font(44, True), "#111111", 820, 14)
        draw.text((125, 900), "posted from the group chat evidence locker", font=font(26), fill="#6d6252")

    def _username_from_name(self, name: str) -> str:
        import re
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        return "@" + (slug or "inside_jokes")[:24]

    def _color_from_text(self, text: str) -> str:
        palette = ["#2f6fed", "#b23a48", "#2a9d8f", "#7b2cbf", "#d97706", "#2f3e46"]
        return palette[sum(ord(c) for c in text) % len(palette)]

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
