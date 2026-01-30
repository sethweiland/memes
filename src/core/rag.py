"""
Main RAG interface for domain-specific meme generation.
Orchestrates the full pipeline: indexing, retrieval, and generation.
"""

import os
from typing import Optional, TYPE_CHECKING
from dataclasses import dataclass

from dotenv import load_dotenv

from .processor import ContentProcessor, ContentChunk
from .vectorstore import DomainVectorStore
from .retriever import DomainRetriever, RetrievalResult
from .grok import GrokClient, MemeIdea

if TYPE_CHECKING:
    from ..config.domain_config import DomainConfig
    from ..config.prompt_templates import PromptTemplates


@dataclass
class TokenBudget:
    """
    Track token usage across a session.

    Token Budget Guide:
    -------------------
    Tokens are roughly 4 characters or 0.75 words. Here's what different
    budgets get you:

    - 10,000 tokens (~$0.002): ~10 searches, no meme generation
    - 50,000 tokens (~$0.01): ~20 searches + 5 meme generations
    - 100,000 tokens (~$0.02): ~30 searches + 15 meme generations
    - 500,000 tokens (~$0.10): Heavy usage, ~100 searches + 50 memes
    - None (unlimited): No tracking, pay as you go
    """
    limit: Optional[int] = None
    used: int = 0
    searches: int = 0
    meme_generations: int = 0
    cache_hits: int = 0

    TOKENS_PER_SEARCH: int = 1000
    TOKENS_PER_SEARCH_NO_EXPAND: int = 100
    TOKENS_PER_MEME_GEN: int = 4000
    TOKENS_PER_BRAINSTORM: int = 2500

    def check(self, tokens_needed: int, operation: str) -> bool:
        """Check if we have budget for an operation."""
        if self.limit is None:
            return True
        if self.used + tokens_needed > self.limit:
            remaining = self.limit - self.used
            raise TokenBudgetExceeded(
                f"Token budget exceeded. "
                f"Need ~{tokens_needed:,} tokens for {operation}, "
                f"but only {remaining:,} remaining of {self.limit:,} budget. "
                f"Used so far: {self.used:,} tokens."
            )
        return True

    def record(self, tokens: int, operation: str):
        """Record token usage."""
        self.used += tokens
        if "search" in operation.lower():
            self.searches += 1
        elif "meme" in operation.lower():
            self.meme_generations += 1

    def summary(self) -> dict:
        """Get usage summary."""
        return {
            "tokens_used": self.used,
            "tokens_limit": self.limit or "unlimited",
            "tokens_remaining": (self.limit - self.used) if self.limit else "unlimited",
            "searches": self.searches,
            "meme_generations": self.meme_generations,
            "cache_hits": self.cache_hits,
        }


class TokenBudgetExceeded(Exception):
    """Raised when token budget is exceeded."""
    pass


class DomainRAG:
    """
    Main RAG interface for domain-specific meme generation.

    Usage:
        from src.config import load_domain
        from src.core.rag import DomainRAG

        config = load_domain("bluegrass")
        rag = DomainRAG(config, token_budget=50000)
        rag.index_content("articles/bluegrass_unlimited_archives.json")
        ideas = rag.generate_meme_ideas("Bill Monroe being stubborn")
        print(rag.budget.summary())
    """

    def __init__(
        self,
        domain_config: "DomainConfig",
        token_budget: Optional[int] = None,
    ):
        """
        Initialize the RAG pipeline.

        Args:
            domain_config: Domain configuration
            token_budget: Optional token limit for the session
        """
        load_dotenv()

        self.domain = domain_config
        self.budget = TokenBudget(limit=token_budget)

        # Initialize prompt templates
        from ..config.prompt_templates import PromptTemplates
        self.prompts = PromptTemplates(domain_config.prompts_dir, domain_config)

        # Initialize components with domain config
        self.processor = ContentProcessor(domain_config)
        self.vectorstore = DomainVectorStore(domain_config)
        self.retriever = DomainRetriever(domain_config, self.vectorstore, self.prompts)

        # Grok client (lazy initialization)
        self._grok_client: Optional[GrokClient] = None

    @property
    def grok(self) -> GrokClient:
        """Lazy-load Grok client."""
        if self._grok_client is None:
            self._grok_client = GrokClient()
        return self._grok_client

    def index_articles(
        self,
        json_path: str,
        clear_existing: bool = False,
        show_progress: bool = True,
    ) -> int:
        """
        Index articles from JSON file into the vector store.

        Args:
            json_path: Path to JSON articles file
            clear_existing: Whether to clear existing index first
            show_progress: Whether to print progress

        Returns:
            Number of chunks indexed
        """
        if clear_existing:
            if show_progress:
                print("Clearing existing index...")
            self.vectorstore.clear()

        existing_count = self.vectorstore.get_chunk_count()
        if existing_count > 0 and not clear_existing:
            if show_progress:
                print(f"Index already contains {existing_count} chunks. "
                      "Use clear_existing=True to reindex.")
            return existing_count

        if show_progress:
            print(f"Processing articles from {json_path}...")
        chunks = self.processor.process_all(json_path)

        if show_progress:
            print(f"Generated {len(chunks)} chunks from articles")

        self.vectorstore.add_chunks(chunks, show_progress=show_progress)

        return len(chunks)

    # Alias for backward compatibility
    index_content = index_articles

    def search(
        self,
        query: str,
        k: int = 10,
        filters: Optional[dict] = None,
        expand_query: bool = True,
    ) -> list[RetrievalResult]:
        """
        Search for relevant content.

        Args:
            query: Search query
            k: Number of results
            filters: Optional filters (artist, instrument, year_range, topic)
            expand_query: Whether to expand query for better recall

        Returns:
            List of RetrievalResult objects
        """
        tokens_needed = (
            self.budget.TOKENS_PER_SEARCH if expand_query
            else self.budget.TOKENS_PER_SEARCH_NO_EXPAND
        )
        self.budget.check(tokens_needed, "search")

        results = self.retriever.hybrid_search(
            query=query,
            k=k,
            expand_query=expand_query,
            filters=filters,
        )

        cache_stats = self.vectorstore.embedding_cache.stats()
        if cache_stats["hits"] > self.budget.cache_hits:
            new_hits = cache_stats["hits"] - self.budget.cache_hits
            tokens_needed = max(100, tokens_needed - (new_hits * 50))
            self.budget.cache_hits = cache_stats["hits"]

        self.budget.record(tokens_needed, "search")
        return results

    def get_context(
        self,
        topic: str,
        k: int = 5,
        filters: Optional[dict] = None,
    ) -> list[dict]:
        """
        Get formatted context for a topic, ready for LLM consumption.

        Args:
            topic: Topic to search for
            k: Number of context chunks
            filters: Optional filters

        Returns:
            List of dicts with text and metadata
        """
        results = self.search(topic, k=k, filters=filters)
        return [
            {
                'text': r.text,
                'metadata': r.metadata,
                'score': r.combined_score,
            }
            for r in results
        ]

    def generate_meme_ideas(
        self,
        topic: str,
        num_ideas: int = 3,
        num_context_chunks: int = 5,
        filters: Optional[dict] = None,
    ) -> list[MemeIdea]:
        """
        Generate meme ideas for a topic using RAG.

        Args:
            topic: Meme topic/theme
            num_ideas: Number of meme ideas to generate
            num_context_chunks: Number of context chunks to retrieve
            filters: Optional filters for retrieval

        Returns:
            List of MemeIdea objects
        """
        self.budget.check(self.budget.TOKENS_PER_MEME_GEN, "meme generation")

        context = self.get_context(
            topic,
            k=num_context_chunks,
            filters=filters,
        )

        if not context:
            raise ValueError(f"No relevant content found for topic: {topic}")

        ideas = self.grok.generate_meme_ideas(
            topic=topic,
            context_chunks=context,
            num_ideas=num_ideas,
        )

        self.budget.record(self.budget.TOKENS_PER_MEME_GEN, "meme generation")
        return ideas

    def brainstorm_topics(
        self,
        seed_query: str = "",
        num_topics: int = 5,
    ) -> list[str]:
        """
        Generate meme topic ideas based on the archive content.

        Args:
            seed_query: Query to find interesting content
            num_topics: Number of topics to generate

        Returns:
            List of topic suggestions
        """
        self.budget.check(self.budget.TOKENS_PER_BRAINSTORM, "brainstorm")

        if not seed_query:
            seed_query = f"{self.domain.display_name.lower()} history stories"

        context = self.get_context(seed_query, k=5)
        topics = self.grok.brainstorm_topics(context, num_topics=num_topics)

        self.budget.record(self.budget.TOKENS_PER_BRAINSTORM, "brainstorm")
        return topics

    def search_by_artist(self, artist: str, k: int = 10) -> list[RetrievalResult]:
        """Search for content about a specific artist."""
        return self.retriever.search_by_artist(artist, k=k)

    def search_by_instrument(
        self,
        instrument: str,
        query: str = "",
        k: int = 10,
    ) -> list[RetrievalResult]:
        """Search for content about a specific instrument."""
        return self.retriever.search_by_instrument(instrument, query, k=k)

    def search_by_era(
        self,
        start_year: int,
        end_year: int,
        query: str = "",
        k: int = 10,
    ) -> list[RetrievalResult]:
        """Search for content from a specific era."""
        return self.retriever.search_by_era(start_year, end_year, query, k=k)

    def get_stats(self) -> dict:
        """Get statistics about the indexed content and usage."""
        cache_stats = self.vectorstore.embedding_cache.stats()
        return {
            "total_chunks": self.vectorstore.get_chunk_count(),
            "bm25_indexed": len(self.vectorstore.bm25_corpus),
            "embedding_cache": cache_stats,
            "token_usage": self.budget.summary(),
        }

    def close(self):
        """Clean up resources."""
        if self._grok_client:
            self._grok_client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# Backward compatibility alias
BluegrassRAG = DomainRAG
