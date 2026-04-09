"""
Current events search for timely meme generation.
Uses DuckDuckGo news search + LLM relevance filtering.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

try:
    from ddgs import DDGS
    HAS_DDGS = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        HAS_DDGS = True
    except ImportError:
        HAS_DDGS = False

if TYPE_CHECKING:
    from ..config.domain_config import DomainConfig


@dataclass
class NewsItem:
    """A news search result."""
    title: str
    url: str
    body: str = ""
    source: str = ""


class CurrentEventsSearch:
    """
    Searches for current news and filters for meme-worthy items.

    Uses DuckDuckGo news search for headlines, then an LLM call
    to filter for items relevant and funny enough for meme generation.
    """

    def __init__(self, domain_config: "DomainConfig"):
        self.domain = domain_config
        self.ce_config = domain_config.current_events

    def search_news(self) -> list[NewsItem]:
        """
        Search DuckDuckGo news for each configured query.
        Deduplicates results by title.
        """
        if not HAS_DDGS:
            print("  duckduckgo-search not installed, skipping news search")
            return []

        seen_titles: set[str] = set()
        all_items: list[NewsItem] = []
        max_per_query = max(1, self.ce_config.max_results // max(1, len(self.ce_config.search_queries)))

        with DDGS() as ddgs:
            for query in self.ce_config.search_queries:
                try:
                    results = ddgs.news(query, max_results=max_per_query)
                    for r in results:
                        title = r.get("title", "").strip()
                        if not title or title.lower() in seen_titles:
                            continue
                        seen_titles.add(title.lower())
                        all_items.append(NewsItem(
                            title=title,
                            url=r.get("url", ""),
                            body=r.get("body", ""),
                            source=r.get("source", ""),
                        ))
                except Exception as e:
                    print(f"  News search failed for '{query}': {e}")

        return all_items[:self.ce_config.max_results]

    def filter_relevant(self, news_items: list[NewsItem]) -> list[NewsItem]:
        """
        Use Grok to filter news items for meme-worthiness.
        On failure, returns all items (fail open).
        """
        if not news_items:
            return []

        from .grok import GrokClient

        headline_list = "\n".join(
            f"{i+1}. {item.title}" for i, item in enumerate(news_items)
        )

        prompt = f"""Below are recent news headlines. Which ones would be funny or relevant for {self.domain.display_name} fans to make memes about?

{headline_list}

Return ONLY the numbers of meme-worthy headlines (comma-separated), or NONE if none are relevant.
Example: 1, 3, 5
Example: NONE"""

        try:
            grok = GrokClient()
            response = grok._chat([
                {"role": "user", "content": prompt}
            ], max_tokens=100, temperature=0.3)
            grok.close()

            response = response.strip().upper()
            if "NONE" in response:
                return []

            # Parse comma-separated numbers
            indices = []
            for part in response.replace(",", " ").split():
                cleaned = ''.join(c for c in part if c.isdigit())
                if cleaned:
                    idx = int(cleaned) - 1
                    if 0 <= idx < len(news_items):
                        indices.append(idx)

            if not indices:
                return news_items  # Couldn't parse — fail open

            return [news_items[i] for i in indices]

        except Exception as e:
            print(f"  Relevance filter failed: {e}")
            return news_items  # Fail open

    def get_current_events_context(self) -> str:
        """
        Orchestrate search -> filter -> format.
        Returns a formatted string for injection into prompts, or empty string.
        """
        if not self.ce_config.enabled:
            return ""

        print("Fetching current events...")
        items = self.search_news()
        if not items:
            print("  No news items found")
            return ""

        print(f"  Found {len(items)} news items, filtering for relevance...")
        relevant = self.filter_relevant(items)
        if not relevant:
            print("  No relevant news items after filtering")
            return ""

        print(f"  {len(relevant)} relevant news items selected")

        lines = []
        for item in relevant:
            line = f"- {item.title}"
            if item.body:
                # Truncate body to keep context concise
                body_preview = item.body[:150].strip()
                if len(item.body) > 150:
                    body_preview += "..."
                line += f" — {body_preview}"
            lines.append(line)

        return "\n".join(lines)
