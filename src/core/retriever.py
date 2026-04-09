"""
Retriever with hybrid search, query expansion, and reranking.
Domain-agnostic version that uses prompt templates.
"""

from typing import Optional, TYPE_CHECKING
from dataclasses import dataclass

from .grok import GrokClient
from .vectorstore import DomainVectorStore

if TYPE_CHECKING:
    from ..config.domain_config import DomainConfig
    from ..config.prompt_templates import PromptTemplates


@dataclass
class RetrievalResult:
    """A single retrieval result with combined scoring."""
    id: str
    text: str
    metadata: dict
    semantic_score: float = 0.0
    keyword_score: float = 0.0
    combined_score: float = 0.0


class DomainRetriever:
    """
    Hybrid retriever combining semantic and keyword search with reranking.

    Uses domain configuration and prompt templates for query expansion.
    """

    def __init__(
        self,
        domain_config: "DomainConfig",
        vectorstore: Optional[DomainVectorStore] = None,
        prompt_templates: Optional["PromptTemplates"] = None,
    ):
        """
        Args:
            domain_config: Domain configuration
            vectorstore: Existing vectorstore instance, or creates new one
            prompt_templates: Prompt templates for query expansion
        """
        self.domain = domain_config
        self.vectorstore = vectorstore or DomainVectorStore(domain_config)
        self.prompts = prompt_templates
        self.grok_client = GrokClient()

    def expand_query(self, query: str, num_variants: int = 3) -> list[str]:
        """
        Expand a query into multiple search variants for better recall.

        Args:
            query: Original search query
            num_variants: Number of query variants to generate

        Returns:
            List of query variants including original
        """
        # Use prompt template if available
        if self.prompts and self.prompts.has_template("query_expansion"):
            prompt = self.prompts.render(
                "query_expansion",
                query=query,
                num_variants=num_variants,
            )
        else:
            # Fallback to generic prompt
            prompt = f"""Generate {num_variants} alternative search queries for finding {self.domain.display_name.lower()} articles.
Original query: "{query}"

Generate queries that:
- Rephrase the original meaning
- Use synonyms or related terms
- Capture different aspects of the same topic

Return ONLY the queries, one per line, no numbering or bullets."""

        response = self.grok_client._chat(
            messages=[{"role": "user", "content": prompt}],
            model="grok-3-mini",
            temperature=0.7,
            max_tokens=200,
        )

        variants = response.strip().split('\n')
        variants = [v.strip() for v in variants if v.strip()]

        return [query] + variants[:num_variants]

    def _normalize_scores(self, scores: list[float]) -> list[float]:
        """Normalize scores to 0-1 range."""
        if not scores:
            return []
        min_score = min(scores)
        max_score = max(scores)
        if max_score == min_score:
            return [1.0] * len(scores)
        return [(s - min_score) / (max_score - min_score) for s in scores]

    def _build_chroma_filter(self, filters: dict) -> Optional[dict]:
        """
        Build ChromaDB where filter from user-friendly filter dict.

        Supported filters (passed to ChromaDB):
            - artist: str - Filter by artist subject
            - year_range: tuple[int, int] - Filter by year range

        Note: instrument and topic filters are handled via post-filtering
        since ChromaDB doesn't support substring matching.
        """
        conditions = []

        if 'artist' in filters and filters['artist']:
            conditions.append({
                "artist_subject": {"$eq": filters['artist']}
            })

        if 'year_range' in filters and filters['year_range']:
            start_year, end_year = filters['year_range']
            conditions.append({"year": {"$gte": start_year}})
            conditions.append({"year": {"$lte": end_year}})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    def _apply_post_filters(
        self,
        results: list[RetrievalResult],
        filters: dict
    ) -> list[RetrievalResult]:
        """
        Apply filters that require substring matching (not supported by ChromaDB).

        Filters handled here:
            - instrument: str - Filter by instrument mentioned in metadata
            - topic: str - Filter by topic mentioned in metadata
        """
        filtered = results

        if 'instrument' in filters and filters['instrument']:
            instrument = filters['instrument'].lower()
            filtered = [
                r for r in filtered
                if instrument in r.metadata.get('instruments', '').lower()
            ]

        if 'topic' in filters and filters['topic']:
            topic = filters['topic'].lower()
            filtered = [
                r for r in filtered
                if topic in r.metadata.get('topics', '').lower()
            ]

        return filtered

    def hybrid_search(
        self,
        query: str,
        k: int = 10,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
        expand_query: bool = True,
        filters: Optional[dict] = None,
        exclude_ids: set[str] | None = None,
    ) -> list[RetrievalResult]:
        """
        Perform hybrid search combining semantic and keyword search.

        Args:
            query: Search query
            k: Number of results to return
            semantic_weight: Weight for semantic search scores
            keyword_weight: Weight for keyword search scores
            expand_query: Whether to expand query into variants
            filters: Optional filter dict (artist, instrument, year_range, topic)
            exclude_ids: Optional set of chunk IDs to exclude from results

        Returns:
            List of RetrievalResult objects, ranked by combined score
        """
        queries = self.expand_query(query) if expand_query else [query]
        chroma_filter = self._build_chroma_filter(filters) if filters else None

        all_results: dict[str, RetrievalResult] = {}

        for q in queries:
            semantic_results = self.vectorstore.semantic_search(
                q, k=k * 2, where=chroma_filter
            )
            for r in semantic_results:
                if r['id'] not in all_results:
                    all_results[r['id']] = RetrievalResult(
                        id=r['id'],
                        text=r['text'],
                        metadata=r['metadata'],
                    )
                all_results[r['id']].semantic_score = max(
                    all_results[r['id']].semantic_score,
                    r['score']
                )

            keyword_results = self.vectorstore.keyword_search(q, k=k * 2)
            for r in keyword_results:
                if r['id'] not in all_results:
                    all_results[r['id']] = RetrievalResult(
                        id=r['id'],
                        text=r['text'],
                        metadata=r['metadata'],
                    )
                all_results[r['id']].keyword_score = max(
                    all_results[r['id']].keyword_score,
                    r['score']
                )

        # Filter out excluded IDs before ranking
        if exclude_ids:
            all_results = {k: v for k, v in all_results.items() if k not in exclude_ids}

        results = list(all_results.values())
        if not results:
            return []

        semantic_scores = [r.semantic_score for r in results]
        keyword_scores = [r.keyword_score for r in results]

        norm_semantic = self._normalize_scores(semantic_scores)
        norm_keyword = self._normalize_scores(keyword_scores)

        for i, r in enumerate(results):
            r.combined_score = (
                semantic_weight * norm_semantic[i] +
                keyword_weight * norm_keyword[i]
            )

        results.sort(key=lambda x: x.combined_score, reverse=True)

        # Apply post-filters for instrument/topic (not supported by ChromaDB)
        if filters:
            results = self._apply_post_filters(results, filters)

        return self._deduplicate(results[:k])

    def _deduplicate(
        self,
        results: list[RetrievalResult],
        similarity_threshold: float = 0.9,
    ) -> list[RetrievalResult]:
        """Remove near-duplicate results based on text similarity."""
        if len(results) <= 1:
            return results

        def jaccard_similarity(text1: str, text2: str) -> float:
            words1 = set(text1.lower().split())
            words2 = set(text2.lower().split())
            intersection = words1 & words2
            union = words1 | words2
            return len(intersection) / len(union) if union else 0

        deduplicated = []
        for result in results:
            is_duplicate = False
            for existing in deduplicated:
                if jaccard_similarity(result.text, existing.text) > similarity_threshold:
                    is_duplicate = True
                    break
            if not is_duplicate:
                deduplicated.append(result)

        return deduplicated

    def search_by_artist(self, artist: str, k: int = 10) -> list[RetrievalResult]:
        """Search for content about a specific artist/entity."""
        return self.hybrid_search(
            f"{artist} {self.domain.display_name.lower()} stories",
            k=k,
            filters={"artist": artist}
        )

    def search_by_instrument(
        self,
        instrument: str,
        query: str = "",
        k: int = 10
    ) -> list[RetrievalResult]:
        """Search for content about a specific instrument/category."""
        search_query = f"{instrument} {query}" if query else f"{instrument} technique stories"
        return self.hybrid_search(
            search_query,
            k=k,
            filters={"instrument": instrument}
        )

    def search_by_era(
        self,
        start_year: int,
        end_year: int,
        query: str = "",
        k: int = 10
    ) -> list[RetrievalResult]:
        """Search for content from a specific era."""
        search_query = query or f"{self.domain.display_name.lower()} history stories"
        return self.hybrid_search(
            search_query,
            k=k,
            filters={"year_range": (start_year, end_year)}
        )


# Backward compatibility alias
BluegrassRetriever = DomainRetriever
