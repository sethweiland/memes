"""
Retriever with hybrid search, query expansion, and reranking.
"""

from typing import Optional
from dataclasses import dataclass

from openai import OpenAI

from .vectorstore import BluegrassVectorStore


@dataclass
class RetrievalResult:
    """A single retrieval result with combined scoring."""
    id: str
    text: str
    metadata: dict
    semantic_score: float = 0.0
    keyword_score: float = 0.0
    combined_score: float = 0.0


class BluegrassRetriever:
    """
    Hybrid retriever combining semantic and keyword search with reranking.
    """

    def __init__(self, vectorstore: Optional[BluegrassVectorStore] = None):
        """
        Args:
            vectorstore: Existing vectorstore instance, or creates new one
        """
        self.vectorstore = vectorstore or BluegrassVectorStore()
        self.openai_client = OpenAI()

    def expand_query(self, query: str, num_variants: int = 3) -> list[str]:
        """
        Expand a query into multiple search variants for better recall.

        Args:
            query: Original search query
            num_variants: Number of query variants to generate

        Returns:
            List of query variants including original
        """
        prompt = f"""Generate {num_variants} alternative search queries for finding bluegrass music articles.
Original query: "{query}"

Generate queries that:
- Rephrase the original meaning
- Use synonyms or related terms
- Capture different aspects of the same topic

Return ONLY the queries, one per line, no numbering or bullets."""

        response = self.openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=200,
        )

        variants = response.choices[0].message.content.strip().split('\n')
        variants = [v.strip() for v in variants if v.strip()]

        # Include original query
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

        Supported filters:
            - artist: str - Filter by artist subject
            - instrument: str - Filter by instrument mentioned
            - year_range: tuple[int, int] - Filter by year range
            - topic: str - Filter by topic
        """
        conditions = []

        if 'artist' in filters and filters['artist']:
            conditions.append({
                "artist_subject": {"$eq": filters['artist']}
            })

        if 'instrument' in filters and filters['instrument']:
            conditions.append({
                "instruments": {"$contains": filters['instrument']}
            })

        if 'year_range' in filters and filters['year_range']:
            start_year, end_year = filters['year_range']
            conditions.append({"year": {"$gte": start_year}})
            conditions.append({"year": {"$lte": end_year}})

        if 'topic' in filters and filters['topic']:
            conditions.append({
                "topics": {"$contains": filters['topic']}
            })

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    def hybrid_search(
        self,
        query: str,
        k: int = 10,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
        expand_query: bool = True,
        filters: Optional[dict] = None,
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

        Returns:
            List of RetrievalResult objects, ranked by combined score
        """
        # Expand query if requested
        queries = self.expand_query(query) if expand_query else [query]

        # Build ChromaDB filter
        chroma_filter = self._build_chroma_filter(filters) if filters else None

        # Collect results from all queries
        all_results: dict[str, RetrievalResult] = {}

        for q in queries:
            # Semantic search
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
                # Take max semantic score across query variants
                all_results[r['id']].semantic_score = max(
                    all_results[r['id']].semantic_score,
                    r['score']
                )

            # Keyword search (no filtering support in BM25)
            keyword_results = self.vectorstore.keyword_search(q, k=k * 2)
            for r in keyword_results:
                if r['id'] not in all_results:
                    all_results[r['id']] = RetrievalResult(
                        id=r['id'],
                        text=r['text'],
                        metadata=r['metadata'],
                    )
                # Take max keyword score across query variants
                all_results[r['id']].keyword_score = max(
                    all_results[r['id']].keyword_score,
                    r['score']
                )

        # Normalize scores
        results = list(all_results.values())
        if not results:
            return []

        semantic_scores = [r.semantic_score for r in results]
        keyword_scores = [r.keyword_score for r in results]

        norm_semantic = self._normalize_scores(semantic_scores)
        norm_keyword = self._normalize_scores(keyword_scores)

        # Calculate combined scores
        for i, r in enumerate(results):
            r.combined_score = (
                semantic_weight * norm_semantic[i] +
                keyword_weight * norm_keyword[i]
            )

        # Sort by combined score and return top k
        results.sort(key=lambda x: x.combined_score, reverse=True)
        return self._deduplicate(results[:k])

    def _deduplicate(
        self,
        results: list[RetrievalResult],
        similarity_threshold: float = 0.9,
    ) -> list[RetrievalResult]:
        """
        Remove near-duplicate results based on text similarity.

        Args:
            results: List of results to deduplicate
            similarity_threshold: Jaccard similarity threshold for deduplication

        Returns:
            Deduplicated list of results
        """
        if len(results) <= 1:
            return results

        def jaccard_similarity(text1: str, text2: str) -> float:
            """Calculate Jaccard similarity between two texts."""
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
        """Search for content about a specific artist."""
        return self.hybrid_search(
            f"{artist} bluegrass music stories",
            k=k,
            filters={"artist": artist}
        )

    def search_by_instrument(
        self,
        instrument: str,
        query: str = "",
        k: int = 10
    ) -> list[RetrievalResult]:
        """Search for content about a specific instrument."""
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
        search_query = query or "bluegrass history stories"
        return self.hybrid_search(
            search_query,
            k=k,
            filters={"year_range": (start_year, end_year)}
        )


if __name__ == "__main__":
    # Quick test
    retriever = BluegrassRetriever()
    print("Retriever initialized")

    # Test query expansion
    expanded = retriever.expand_query("weird banjo players")
    print(f"Query expansion: {expanded}")
