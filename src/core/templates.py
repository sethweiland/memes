"""
Meme template catalog from imgflip.
Fetches and caches available templates with descriptions for Grok to choose from.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

import httpx


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
    "Drake Hotline Bling": "Two panels: top shows Drake dismissing something, bottom shows Drake approving something. Use for 'thing I don't want' vs 'thing I prefer'.",
    "Two Buttons": "Sweating person must choose between two buttons. Use for difficult choices or dilemmas.",
    "Distracted Boyfriend": "Guy looking at another woman while girlfriend looks angry. Use for being tempted by something new over what you have.",
    "Change My Mind": "Person sitting at table with sign. Use for controversial or stubborn opinions.",
    "Expanding Brain": "4 panels showing increasingly 'galaxy brain' ideas. Use for escalating absurdity.",
    "Is This A Pigeon?": "Anime character pointing at butterfly asking 'Is this a pigeon?'. Use for misidentifying something obvious.",
    "One Does Not Simply": "Boromir explaining something is not simple. Use for things that are harder than they seem.",
    "Batman Slapping Robin": "Batman slapping Robin mid-sentence. Use for shutting down bad takes.",
    "Left Exit 12 Off Ramp": "Car swerving to exit. Use for choosing an unexpected/worse option.",
    "Waiting Skeleton": "Skeleton on bench. Use for waiting forever for something.",
    "Roll Safe": "Guy tapping head smugly. Use for 'clever' logic that's actually dumb.",
    "Ancient Aliens": "History channel guy with wild hair. Use for absurd explanations.",
    "Surprised Pikachu": "Pikachu with shocked face. Use for obvious consequences someone didn't expect.",
    "Woman Yelling At Cat": "Two panels: angry woman pointing, confused cat at dinner table. Use for arguments where one side is unreasonable.",
    "They're The Same Picture": "Office scene comparing two pictures. Use for things that are identical despite claims otherwise.",
    "Buff Doge vs. Cheems": "Strong doge vs weak doge. Use for 'then vs now' or comparing strong/weak versions.",
    "Gru's Plan": "4 panels: Gru presents plan, realizes flaw. Use for plans that backfire.",
    "Always Has Been": "Astronaut pointing gun at another astronaut. 'Wait, it's all X?' 'Always has been.'",
    "Panik Kalm Panik": "3 panels showing panic, calm, then panic again. Use for false sense of security.",
    "Tuxedo Winnie The Pooh": "Regular Pooh vs fancy Pooh. Use for basic vs sophisticated versions of same thing.",
    "Bernie Sanders Once Again Asking": "Bernie at podium. Use for repeatedly asking for something.",
    "Boardroom Meeting Suggestion": "Person thrown out window for suggestion. Use for rejecting good ideas.",
    "Disaster Girl": "Girl smiling in front of fire. Use for causing chaos and being pleased about it.",
    "Hide the Pain Harold": "Old man with forced smile hiding pain. Use for pretending everything is fine.",
    "Monkey Puppet": "Puppet looking away awkwardly. Use for avoiding uncomfortable truths.",
    "Spider-Man Pointing": "Two Spider-Men pointing at each other. Use for two things that are the same.",
    "This Is Fine": "Dog in burning room saying 'this is fine'. Use for ignoring obvious problems.",
    "Sad Pablo Escobar": "Pablo Escobar waiting alone. Use for loneliness or waiting.",
    "Epic Handshake": "Two arms clasping in agreement. Use for unlikely allies or shared opinions.",
    "UNO Draw 25": "Choice between doing something or drawing 25 cards. Use for refusing to do something easy.",
}


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
