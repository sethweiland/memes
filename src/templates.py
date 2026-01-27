"""
Meme template catalog from imgflip.
Fetches and caches available templates with descriptions for Grok to choose from.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

import httpx


def _load_extra_descriptions() -> dict[str, str]:
    """Load additional template descriptions from JSON file."""
    extra_path = Path("data/new_template_descriptions.json")
    if extra_path.exists():
        with open(extra_path) as f:
            return json.load(f)
    return {}


@dataclass
class MemeTemplate:
    """A meme template from imgflip."""
    id: str
    name: str
    url: str
    width: int
    height: int
    box_count: int
    description: str = ""

    def to_prompt_format(self) -> str:
        """Format for including in LLM prompt."""
        boxes = f"{self.box_count} text boxes"
        desc = f" - {self.description}" if self.description else ""
        return f"- {self.name} ({boxes}){desc}"


# Hand-written descriptions for popular templates to help Grok understand them
TEMPLATE_DESCRIPTIONS = {
    "Drake Hotline Bling": "TOP_TEXT=thing rejected, BOTTOM_TEXT=thing approved. Drake dismisses top, approves bottom.",
    "Two Buttons": "TOP_TEXT=button 1 choice, BOTTOM_TEXT=button 2 choice. Sweating over difficult decision.",
    "Distracted Boyfriend": "TOP_TEXT=boyfriend label, BOTTOM_TEXT=other woman label / girlfriend label. Guy tempted by new thing over current thing.",
    "Change My Mind": "TOP_TEXT=controversial opinion on the sign, BOTTOM_TEXT=not used. Person at table daring others to disagree.",
    "Expanding Brain": "TOP_TEXT=basic level 1, BOTTOM_TEXT=level 2 / level 3 / galaxy brain level 4. Escalating absurdity.",
    "Is This A Pigeon?": "TOP_TEXT=what they're misidentifying, BOTTOM_TEXT=what they wrongly call it. Obvious misidentification.",
    "One Does Not Simply": "TOP_TEXT='One does not simply', BOTTOM_TEXT=thing that's harder than it seems.",
    "Batman Slapping Robin": "TOP_TEXT=Robin's bad take (cut off mid-sentence), BOTTOM_TEXT=Batman's correction. Shutting down bad opinions.",
    "Left Exit 12 Off Ramp": "TOP_TEXT=sensible path, BOTTOM_TEXT=exit sign / car label. Choosing unexpected/worse option.",
    "Waiting Skeleton": "TOP_TEXT=what you're waiting for, BOTTOM_TEXT=optional extra context. Waiting forever.",
    "Roll Safe": "TOP_TEXT=flawed 'clever' logic, BOTTOM_TEXT=not used. Guy tapping head smugly.",
    "Ancient Aliens": "TOP_TEXT=thing being explained, BOTTOM_TEXT='Aliens' or absurd explanation.",
    "Surprised Pikachu": "TOP_TEXT=action taken, BOTTOM_TEXT=obvious consequence. Shocked at predictable outcome.",
    "Woman Yelling At Cat": "TOP_TEXT=angry woman's complaint, BOTTOM_TEXT=cat's confused response. One side unreasonable.",
    "They're The Same Picture": "TOP_TEXT=thing 1, BOTTOM_TEXT=thing 2. Pam says they're identical.",
    "Buff Doge vs. Cheems": "TOP_TEXT=strong/old version label, BOTTOM_TEXT=weak/new version label. Then vs now comparison.",
    "Gru's Plan": "TOP_TEXT=step 1 of plan, BOTTOM_TEXT=step 2 / step 3 / step 4 (the backfire). Plan goes wrong.",
    "Always Has Been": "TOP_TEXT='Wait, it's all X?', BOTTOM_TEXT='Always has been.' Astronaut with gun reveal.",
    "Panik Kalm Panik": "TOP_TEXT=first panic, BOTTOM_TEXT=calm / second panic. False sense of security.",
    "Tuxedo Winnie The Pooh": "TOP_TEXT=basic/crude version, BOTTOM_TEXT=fancy/sophisticated version.",
    "Bernie Sanders Once Again Asking": "TOP_TEXT=not used, BOTTOM_TEXT=what Bernie is asking for repeatedly.",
    "Boardroom Meeting Suggestion": "TOP_TEXT=question asked, BOTTOM_TEXT=suggestion 1 / suggestion 2 / good idea that gets rejected.",
    "Disaster Girl": "TOP_TEXT=chaos happening, BOTTOM_TEXT=not used. Girl smiling at destruction she caused.",
    "Hide the Pain Harold": "TOP_TEXT=painful situation, BOTTOM_TEXT=not used. Forced smile hiding pain.",
    "Monkey Puppet": "TOP_TEXT=uncomfortable truth, BOTTOM_TEXT=not used. Looking away awkwardly.",
    "Spider-Man Pointing": "TOP_TEXT=first thing, BOTTOM_TEXT=second identical thing. Two same things pointing at each other.",
    "This Is Fine": "TOP_TEXT=disaster happening around you, BOTTOM_TEXT='This is fine' or similar denial.",
    "Sad Pablo Escobar": "TOP_TEXT=what you're waiting for, BOTTOM_TEXT=still waiting / alone. Loneliness and waiting.",
    "Epic Handshake": "TOP_TEXT=group 1 (left arm), BOTTOM_TEXT=group 2 (right arm) / what they agree on (middle handshake).",
    "UNO Draw 25": "TOP_TEXT=easy thing they refuse to do, BOTTOM_TEXT=drawing 25 cards instead.",
    "Trade Offer": "TOP_TEXT=what you receive, BOTTOM_TEXT=what I receive. Transaction proposal.",
}

# Merge in additional descriptions from generated JSON
TEMPLATE_DESCRIPTIONS.update(_load_extra_descriptions())


class TemplatesCatalog:
    """Manage meme templates from imgflip."""

    IMGFLIP_API = "https://api.imgflip.com/get_memes"
    SEARCH_API = "https://api.imgflip.com/search_memes"
    CACHE_FILE = "data/meme_templates.json"
    EXPANDED_CACHE_FILE = "data/meme_templates_expanded.json"

    def __init__(self, cache_dir: str = "data", use_expanded: bool = True):
        self.cache_dir = Path(cache_dir)
        self.cache_path = self.cache_dir / "meme_templates.json"
        self.expanded_cache_path = self.cache_dir / "meme_templates_expanded.json"
        self.use_expanded = use_expanded
        self.templates: dict[str, MemeTemplate] = {}
        self._load_or_fetch()

    def _load_or_fetch(self):
        """Load from cache or fetch from API."""
        # Prefer expanded cache if available and enabled
        if self.use_expanded and self.expanded_cache_path.exists():
            self._load_cache(self.expanded_cache_path)
        elif self.cache_path.exists():
            self._load_cache(self.cache_path)
        else:
            self.refresh()

    def _load_cache(self, path: Path | None = None):
        """Load templates from cache file."""
        path = path or self.cache_path
        with open(path, 'r') as f:
            data = json.load(f)
            for t in data:
                # Add description if we have one
                if not t.get('description'):
                    t['description'] = TEMPLATE_DESCRIPTIONS.get(t['name'], '')
                template = MemeTemplate(**t)
                self.templates[template.id] = template

    def _save_cache(self):
        """Save templates to cache file."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {
                "id": t.id,
                "name": t.name,
                "url": t.url,
                "width": t.width,
                "height": t.height,
                "box_count": t.box_count,
                "description": t.description,
            }
            for t in self.templates.values()
        ]
        with open(self.cache_path, 'w') as f:
            json.dump(data, f, indent=2)

    def refresh(self):
        """Fetch fresh templates from imgflip API."""
        response = httpx.get(self.IMGFLIP_API)
        response.raise_for_status()
        data = response.json()

        if not data.get("success"):
            raise RuntimeError(f"imgflip API error: {data}")

        self.templates = {}
        for meme in data["data"]["memes"]:
            # Add description if we have one
            description = TEMPLATE_DESCRIPTIONS.get(meme["name"], "")
            template = MemeTemplate(
                id=meme["id"],
                name=meme["name"],
                url=meme["url"],
                width=meme["width"],
                height=meme["height"],
                box_count=meme["box_count"],
                description=description,
            )
            self.templates[template.id] = template

        self._save_cache()
        print(f"Cached {len(self.templates)} meme templates")

    def get_by_name(self, name: str) -> MemeTemplate | None:
        """Find template by name (fuzzy match)."""
        name_lower = name.lower()
        for template in self.templates.values():
            if name_lower in template.name.lower():
                return template
        return None

    def get_by_id(self, template_id: str) -> MemeTemplate | None:
        """Get template by ID."""
        return self.templates.get(template_id)

    def get_popular(self, limit: int = 50) -> list[MemeTemplate]:
        """Get most popular templates (imgflip returns them sorted by popularity)."""
        return list(self.templates.values())[:limit]

    def get_prompt_catalog(self, limit: int = 30, randomize: bool = False) -> str:
        """
        Get formatted catalog for LLM prompt.
        Includes descriptions to help the model understand each template.

        Args:
            limit: Max templates to include
            randomize: If True, randomly sample from all templates instead of top N
        """
        import random

        if randomize and len(self.templates) > limit:
            # Always include top 20 popular ones, then randomly sample the rest
            all_templates = list(self.templates.values())
            popular = all_templates[:20]  # Top 20 are most recognizable
            others = all_templates[20:]
            random_picks = random.sample(others, min(limit - 20, len(others)))
            selected = popular + random_picks
            random.shuffle(selected)  # Mix them up
        else:
            selected = self.get_popular(limit)

        lines = ["Available meme templates (pick one by exact name):"]
        for template in selected:
            lines.append(template.to_prompt_format())
        return "\n".join(lines)

    def find_best_match(self, name: str) -> MemeTemplate | None:
        """
        Find best matching template for a name.
        Tries exact match, then partial match, then word match.
        """
        name_lower = name.lower().strip()

        # Exact match
        for template in self.templates.values():
            if template.name.lower() == name_lower:
                return template

        # Partial match
        for template in self.templates.values():
            if name_lower in template.name.lower() or template.name.lower() in name_lower:
                return template

        # Word match (any word from template name appears in query)
        for template in self.templates.values():
            template_words = set(template.name.lower().split())
            query_words = set(name_lower.split())
            if template_words & query_words:  # Any overlap
                return template

        return None

    def search_and_add(self, query: str, username: str, password: str) -> list[MemeTemplate]:
        """
        Search imgflip for templates matching query and add to catalog.
        Requires imgflip Premium subscription.

        Args:
            query: Search term
            username: imgflip username
            password: imgflip password

        Returns:
            List of newly added templates
        """
        response = httpx.post(self.SEARCH_API, data={
            'username': username,
            'password': password,
            'query': query
        }, timeout=15)
        response.raise_for_status()
        data = response.json()

        if not data.get('success'):
            raise RuntimeError(f"imgflip search error: {data.get('error_message')}")

        new_templates = []
        for meme in data['data'].get('memes', []):
            if meme['id'] not in self.templates:
                template = MemeTemplate(
                    id=meme['id'],
                    name=meme['name'],
                    url=meme['url'],
                    width=meme['width'],
                    height=meme['height'],
                    box_count=meme['box_count'],
                    description=TEMPLATE_DESCRIPTIONS.get(meme['name'], ''),
                )
                self.templates[template.id] = template
                new_templates.append(template)

        if new_templates:
            self._save_expanded_cache()

        return new_templates

    def _save_expanded_cache(self):
        """Save all templates to expanded cache file."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        data = [
            {
                "id": t.id,
                "name": t.name,
                "url": t.url,
                "width": t.width,
                "height": t.height,
                "box_count": t.box_count,
                "description": t.description,
            }
            for t in self.templates.values()
        ]
        with open(self.expanded_cache_path, 'w') as f:
            json.dump(data, f, indent=2)


if __name__ == "__main__":
    catalog = TemplatesCatalog()
    print(f"Loaded {len(catalog.templates)} templates")
    print("\nTop 10 templates:")
    for t in catalog.get_popular(10):
        print(f"  {t.name} ({t.box_count} boxes)")
    print("\nPrompt catalog preview:")
    print(catalog.get_prompt_catalog(5))
