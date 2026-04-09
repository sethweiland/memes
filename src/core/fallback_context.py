"""
Fallback context provider for when no domain-specific RAG is available.
Uses DuckDuckGo web search to gather context for any topic.
"""

from dataclasses import dataclass

try:
    from ddgs import DDGS
    HAS_DDGS = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        HAS_DDGS = True
    except ImportError:
        HAS_DDGS = False


@dataclass
class SearchResult:
    """A web search result."""
    title: str
    url: str
    body: str = ""


class FallbackContextProvider:
    """
    Provides context when no domain-specific RAG is available.
    Uses web search to gather relevant information for any topic.
    """

    def __init__(self):
        pass

    def search_web(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """
        Search DuckDuckGo for a query.

        Args:
            query: Search query
            max_results: Maximum number of results to return

        Returns:
            List of SearchResult objects
        """
        if not HAS_DDGS:
            print("  duckduckgo-search not installed, skipping web search")
            return []

        results: list[SearchResult] = []
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append(SearchResult(
                        title=r.get("title", "").strip(),
                        url=r.get("href", ""),
                        body=r.get("body", "").strip(),
                    ))
        except Exception as e:
            print(f"  Web search failed for '{query}': {e}")

        return results

    def get_web_context(self, topic: str, max_results: int = 5) -> str:
        """
        Get context via web search for any topic.

        Args:
            topic: The topic to search for
            max_results: Maximum number of search results

        Returns:
            Formatted context string suitable for LLM prompts
        """
        # Generate search queries for meme context
        queries = self._generate_search_queries(topic)

        all_results: list[SearchResult] = []
        seen_urls: set[str] = set()

        for query in queries:
            results = self.search_web(query, max_results=max(2, max_results // len(queries)))
            for r in results:
                if r.url not in seen_urls and r.body:
                    seen_urls.add(r.url)
                    all_results.append(r)

        if not all_results:
            return ""

        # Format as context
        lines = []
        for r in all_results[:max_results]:
            line = f"[{r.title}]"
            if r.body:
                # Truncate body to keep context concise
                body_preview = r.body[:300].strip()
                if len(r.body) > 300:
                    body_preview += "..."
                line += f"\n{body_preview}"
            lines.append(line)

        return "\n\n".join(lines)

    def _generate_search_queries(self, topic: str) -> list[str]:
        """
        Generate search queries for a meme topic.

        Args:
            topic: The user's meme topic

        Returns:
            List of search queries (2-3 queries)
        """
        # Clean topic - remove common suffixes like "memes"
        clean_topic = topic.lower()
        for suffix in [" memes", " meme", " jokes", " humor"]:
            if clean_topic.endswith(suffix):
                clean_topic = clean_topic[:-len(suffix)].strip()

        queries = [
            f"{clean_topic} funny facts",
            f"{clean_topic} news",
        ]

        # Add a more specific query if topic seems like a person or thing
        if " " not in clean_topic or len(clean_topic.split()) <= 3:
            queries.append(f"why is {clean_topic} popular")

        return queries[:3]

    def get_context_with_suggestions(
        self,
        topic: str,
        suggested_searches: list[str] | None = None,
        max_results: int = 5,
    ) -> str:
        """
        Get context using provided search suggestions.

        Args:
            topic: The topic
            suggested_searches: Pre-generated search queries (from domain classifier)
            max_results: Maximum number of results

        Returns:
            Formatted context string
        """
        queries = suggested_searches or self._generate_search_queries(topic)

        all_results: list[SearchResult] = []
        seen_urls: set[str] = set()

        for query in queries:
            results = self.search_web(query, max_results=max(2, max_results // len(queries)))
            for r in results:
                if r.url not in seen_urls and r.body:
                    seen_urls.add(r.url)
                    all_results.append(r)

        if not all_results:
            return ""

        lines = []
        for r in all_results[:max_results]:
            line = f"[{r.title}]"
            if r.body:
                body_preview = r.body[:300].strip()
                if len(r.body) > 300:
                    body_preview += "..."
                line += f"\n{body_preview}"
            lines.append(line)

        return "\n\n".join(lines)
