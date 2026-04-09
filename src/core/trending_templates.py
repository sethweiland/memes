"""
Trending meme templates fetcher.
Scrapes imgflip for trending, new, and top templates to keep the catalog fresh.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Load .env for API keys (needed for auto-description)
load_dotenv()

from .templates import TemplatesCatalog, MemeTemplate


@dataclass
class TrendingTemplate:
    """A trending template scraped from imgflip."""
    id: str
    name: str
    url: str
    category: Literal["top_30_days", "top_new", "top_all_time"]
    rank: int  # Position in the list (1 = most trending)
    box_count: int = 2  # Default, may be updated


@dataclass
class TrendingCache:
    """Cache of trending templates."""
    top_30_days: list[TrendingTemplate] = field(default_factory=list)
    top_new: list[TrendingTemplate] = field(default_factory=list)
    top_all_time: list[TrendingTemplate] = field(default_factory=list)
    descriptions: dict[str, str] = field(default_factory=dict)  # lowercase name -> description
    last_updated: str = ""

    def to_dict(self) -> dict:
        return {
            "top_30_days": [
                {"id": t.id, "name": t.name, "url": t.url, "rank": t.rank, "box_count": t.box_count}
                for t in self.top_30_days
            ],
            "top_new": [
                {"id": t.id, "name": t.name, "url": t.url, "rank": t.rank, "box_count": t.box_count}
                for t in self.top_new
            ],
            "top_all_time": [
                {"id": t.id, "name": t.name, "url": t.url, "rank": t.rank, "box_count": t.box_count}
                for t in self.top_all_time
            ],
            "descriptions": self.descriptions,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TrendingCache":
        cache = cls()
        cache.last_updated = data.get("last_updated", "")
        cache.descriptions = data.get("descriptions", {})

        for category in ["top_30_days", "top_new", "top_all_time"]:
            templates = []
            for t in data.get(category, []):
                templates.append(TrendingTemplate(
                    id=t["id"],
                    name=t["name"],
                    url=t["url"],
                    category=category,
                    rank=t["rank"],
                    box_count=t.get("box_count", 2),
                ))
            setattr(cache, category, templates)

        return cache


class TrendingTemplatesFetcher:
    """
    Fetches trending meme templates from imgflip.

    Scrapes three categories:
    - top_30_days: Currently trending
    - top_new: Newest templates
    - top_all_time: Classics that always work
    """

    BASE_URL = "https://imgflip.com/memetemplates"
    CACHE_FILE = "data/trending_templates.json"

    # How many to fetch per category
    DEFAULT_LIMIT = 30

    def __init__(self, cache_dir: str = "data"):
        self.cache_dir = Path(cache_dir)
        self.cache_path = self.cache_dir / "trending_templates.json"
        self.cache: TrendingCache | None = None
        self._load_cache()

    def _load_cache(self):
        """Load cached trending data if available."""
        if self.cache_path.exists():
            try:
                with open(self.cache_path) as f:
                    data = json.load(f)
                self.cache = TrendingCache.from_dict(data)
            except (json.JSONDecodeError, OSError):
                self.cache = None

    def _save_cache(self):
        """Save trending data to cache."""
        if self.cache is None:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, 'w') as f:
            json.dump(self.cache.to_dict(), f, indent=2)

    def _scrape_category(
        self,
        category: Literal["top_30_days", "top_new", "top_all_time"],
        limit: int = DEFAULT_LIMIT,
    ) -> list[TrendingTemplate]:
        """
        Scrape templates from a specific category.

        Args:
            category: Which list to fetch
            limit: Max templates to fetch

        Returns:
            List of TrendingTemplate objects
        """
        # Map category to URL sort parameter
        sort_params = {
            "top_30_days": "top-30-days",
            "top_new": "top-new",
            "top_all_time": "top-all-time",
        }

        url = f"{self.BASE_URL}?sort={sort_params[category]}"

        try:
            response = httpx.get(url, timeout=15, follow_redirects=True)
            response.raise_for_status()
        except Exception as e:
            print(f"  Failed to fetch {category}: {e}")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        templates = []

        # Find template cards - imgflip uses <div class="mt-box"> for each template
        boxes = soup.find_all('div', class_='mt-box')

        for rank, box in enumerate(boxes[:limit], 1):
            try:
                # Find the title element (h3.mt-title contains the link)
                title_elem = box.find('h3', class_='mt-title')
                if not title_elem:
                    continue

                link = title_elem.find('a')
                if not link:
                    continue

                name = link.get_text(strip=True)
                href = link.get('href', '')

                # URL format is /meme/Template-Name - use the slug as ID
                # Extract slug from URL like /meme/Drake-Hotline-Bling
                match = re.search(r'/meme/([^/]+)', href)
                if not match:
                    continue
                template_slug = match.group(1)

                # Get image URL
                img = box.find('img')
                img_url = img.get('src', '') if img else ''
                if img_url.startswith('//'):
                    img_url = 'https:' + img_url

                # Use slug as ID for now (we can resolve to numeric ID later if needed)
                box_count = 2  # Default

                templates.append(TrendingTemplate(
                    id=template_slug,
                    name=name,
                    url=img_url,
                    category=category,
                    rank=rank,
                    box_count=box_count,
                ))

            except Exception as e:
                continue

        return templates

    def _dedupe_templates(self, templates: list[TrendingTemplate]) -> list[TrendingTemplate]:
        """Deduplicate templates by lowercase name."""
        seen = set()
        result = []
        for t in templates:
            key = t.name.lower().strip()
            if key not in seen:
                seen.add(key)
                result.append(t)
        return result

    def refresh(self, limit: int = DEFAULT_LIMIT, auto_describe: bool = True) -> TrendingCache:
        """
        Fetch fresh trending templates from all categories.

        Args:
            limit: Max templates per category
            auto_describe: If True, generate descriptions for new templates via vision

        Returns:
            TrendingCache with all categories populated
        """
        print("Fetching trending templates from imgflip...")

        # Preserve existing descriptions
        old_descriptions = self.cache.descriptions if self.cache else {}

        # Scrape each category (keep all, including duplicates across categories)
        top_new = self._dedupe_templates(self._scrape_category("top_new", limit))
        top_30_days = self._dedupe_templates(self._scrape_category("top_30_days", limit))
        top_all_time = self._dedupe_templates(self._scrape_category("top_all_time", limit))

        self.cache = TrendingCache(
            top_30_days=top_30_days,
            top_new=top_new,
            top_all_time=top_all_time,
            descriptions=old_descriptions.copy(),
            last_updated=datetime.now(timezone.utc).isoformat(),
        )

        print(f"  Top 30 days: {len(self.cache.top_30_days)} templates")
        print(f"  Top new: {len(self.cache.top_new)} templates")
        print(f"  Top all time: {len(self.cache.top_all_time)} templates")

        # Auto-describe new templates
        if auto_describe:
            self._describe_new_templates()

        self._save_cache()
        return self.cache

    def _describe_new_templates(self) -> None:
        """Generate descriptions for templates that don't have them yet."""
        if self.cache is None:
            return

        # Collect all unique templates
        all_templates = []
        seen = set()
        for t in self.cache.top_30_days + self.cache.top_new + self.cache.top_all_time:
            key = t.name.lower().strip()
            if key not in seen:
                seen.add(key)
                all_templates.append(t)

        # Find templates needing descriptions
        need_description = [
            t for t in all_templates
            if t.name.lower().strip() not in self.cache.descriptions
        ]

        if not need_description:
            print("  All templates already have descriptions")
            return

        print(f"  Generating descriptions for {len(need_description)} new templates...")

        try:
            from .template_describer import TemplateDescriber

            try:
                describer = TemplateDescriber()
            except ValueError as e:
                # API key not configured - skip auto-description silently
                print(f"  Skipping auto-description: {e}")
                return

            for i, t in enumerate(need_description):
                print(f"    [{i+1}/{len(need_description)}] {t.name}...")
                try:
                    # Create a minimal template object for the describer
                    mock_template = type('Template', (), {
                        'id': t.id,
                        'name': t.name,
                        'url': t.url,
                    })()
                    result = describer.describe_template(mock_template)
                    if result.description and result.confidence >= 5:
                        self.cache.descriptions[t.name.lower().strip()] = result.description
                        print(f"      ✓ Confidence: {result.confidence}/10")
                    else:
                        print(f"      ✗ Low confidence ({result.confidence}/10), skipped")
                except Exception as e:
                    print(f"      ✗ Error: {e}")

            print(f"  Descriptions generated: {len(self.cache.descriptions)} total")
        except ImportError:
            print("  Warning: TemplateDescriber not available, skipping auto-description")

    def get_trending(
        self,
        top_30_days: int = 5,
        top_new: int = 3,
        top_all_time: int = 2,
        refresh_if_stale_hours: int = 24,
    ) -> list[TrendingTemplate]:
        """
        Get a mix of trending templates from all categories.

        Args:
            top_30_days: How many from the trending category
            top_new: How many from the new category
            top_all_time: How many from all-time classics
            refresh_if_stale_hours: Auto-refresh if cache is older than this

        Returns:
            Mixed list of TrendingTemplate objects
        """
        # Check if we need to refresh
        if self.cache is None:
            self.refresh()
        elif refresh_if_stale_hours > 0 and self.cache.last_updated:
            try:
                last_update = datetime.fromisoformat(self.cache.last_updated.replace('Z', '+00:00'))
                age_hours = (datetime.now(timezone.utc) - last_update).total_seconds() / 3600
                if age_hours > refresh_if_stale_hours:
                    self.refresh()
            except Exception:
                pass

        if self.cache is None:
            return []

        # Build mixed list
        result = []
        result.extend(self.cache.top_30_days[:top_30_days])
        result.extend(self.cache.top_new[:top_new])
        result.extend(self.cache.top_all_time[:top_all_time])

        # Deduplicate by lowercase name (handles case variations like "Worse Than Epstein" vs "worse than epstein")
        seen_names = set()
        deduped = []
        for t in result:
            normalized = t.name.lower().strip()
            if normalized not in seen_names:
                seen_names.add(normalized)
                deduped.append(t)

        return deduped

    def get_prompt_section(
        self,
        top_30_days: int = 10,
        top_new: int = 10,
        top_all_time: int = 10,
    ) -> str:
        """
        Get a formatted section for inclusion in generation prompts.

        Returns a string like:

        TRENDING TEMPLATES (try these for freshness):
        🔥 TRENDING NOW (Top 30 Days):
        - Template Name 1
        - Template Name 2
        ...
        """
        trending = self.get_trending(top_30_days, top_new, top_all_time)

        if not trending:
            return ""

        # Group by category
        by_category = {
            "top_30_days": [],
            "top_new": [],
            "top_all_time": [],
        }
        for t in trending:
            by_category[t.category].append(t)

        # Get descriptions from cache
        descriptions = self.cache.descriptions if self.cache else {}

        def format_template(t: TrendingTemplate) -> list[str]:
            """Format a single template with description if available."""
            result = [f"  - {t.name}"]
            desc = descriptions.get(t.name.lower().strip())
            if desc:
                result.append(f"    {desc}")
            return result

        lines = ["TRENDING TEMPLATES (use these for variety):"]

        if by_category["top_30_days"]:
            lines.append("\n🔥 HOT RIGHT NOW (trending this month):")
            for t in by_category["top_30_days"]:
                lines.extend(format_template(t))

        if by_category["top_new"]:
            lines.append("\n✨ FRESH FORMATS (new templates):")
            for t in by_category["top_new"]:
                lines.extend(format_template(t))

        if by_category["top_all_time"]:
            lines.append("\n👑 CLASSICS (always work):")
            for t in by_category["top_all_time"]:
                lines.extend(format_template(t))

        return "\n".join(lines)

    def sync_to_catalog(
        self,
        catalog: TemplatesCatalog,
        generate_descriptions: bool = False,
    ) -> list[MemeTemplate]:
        """
        Add trending templates to the main catalog if they're not already there.

        Args:
            catalog: The TemplatesCatalog to update
            generate_descriptions: If True, use LLM to generate descriptions for new templates

        Returns:
            List of newly added templates
        """
        if self.cache is None:
            self.refresh()

        if self.cache is None:
            return []

        new_templates = []
        all_trending = (
            self.cache.top_30_days +
            self.cache.top_new +
            self.cache.top_all_time
        )

        for trending in all_trending:
            if trending.id not in catalog.templates:
                template = MemeTemplate(
                    id=trending.id,
                    name=trending.name,
                    url=trending.url,
                    width=500,  # Default, could be fetched
                    height=500,
                    box_count=trending.box_count,
                    description="",  # Will be filled by AI if generate_descriptions=True
                )
                catalog.templates[template.id] = template
                new_templates.append(template)

                # Record metadata
                catalog.metadata[template.id] = {
                    "discovered_via": f"trending_{trending.category}",
                    "discovered_at": datetime.now(timezone.utc).isoformat(),
                    "source": "imgflip_trending",
                    "trending_rank": trending.rank,
                    "name": template.name,
                }

        if new_templates:
            catalog._save_expanded_cache()
            catalog._save_metadata()
            print(f"Added {len(new_templates)} trending templates to catalog")

        return new_templates


# Singleton fetcher instance for category lookups
_fetcher_instance: TrendingTemplatesFetcher | None = None


def get_fetcher() -> TrendingTemplatesFetcher:
    """Get or create the singleton fetcher instance."""
    global _fetcher_instance
    if _fetcher_instance is None:
        _fetcher_instance = TrendingTemplatesFetcher()
    return _fetcher_instance


def get_trending_prompt_section(
    top_30_days: int = 10,
    top_new: int = 10,
    top_all_time: int = 5,
) -> str:
    """Get trending templates section for prompts. Favors new/trending over classics."""
    return get_fetcher().get_prompt_section(top_30_days, top_new, top_all_time)


def get_template_category(template_name: str) -> str | None:
    """
    Look up which category a template belongs to.

    Priority: new > trending > classic
    (New templates are most important to track, then trending, then classics)

    Args:
        template_name: Name of the template (fuzzy match)

    Returns:
        Category string ("trending", "new", "classic") or None if not in trending lists
    """
    fetcher = get_fetcher()
    if fetcher.cache is None:
        return None

    name_lower = template_name.lower().strip()

    # Check new FIRST - these are the fresh templates we want to track
    for t in fetcher.cache.top_new:
        if name_lower in t.name.lower() or t.name.lower() in name_lower:
            return "new"

    # Then trending (currently hot)
    for t in fetcher.cache.top_30_days:
        if name_lower in t.name.lower() or t.name.lower() in name_lower:
            return "trending"

    # Finally classics
    for t in fetcher.cache.top_all_time:
        if name_lower in t.name.lower() or t.name.lower() in name_lower:
            return "classic"

    return None


def get_category_badge(category: str | None) -> dict:
    """
    Get badge info for a category.

    Returns:
        Dict with emoji, label, and css_class
    """
    badges = {
        "trending": {"emoji": "🔥", "label": "Trending", "css_class": "badge-trending"},
        "new": {"emoji": "✨", "label": "New", "css_class": "badge-new"},
        "classic": {"emoji": "👑", "label": "Classic", "css_class": "badge-classic"},
    }
    return badges.get(category, {"emoji": "", "label": "", "css_class": ""})


if __name__ == "__main__":
    # Test the fetcher
    fetcher = TrendingTemplatesFetcher()
    fetcher.refresh(limit=10)

    print("\n" + "=" * 60)
    print(fetcher.get_prompt_section())
