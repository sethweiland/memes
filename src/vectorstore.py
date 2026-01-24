"""
Vector store implementation using ChromaDB and BM25 for hybrid search.
"""

import os
import pickle
from collections import OrderedDict
from typing import Optional

import chromadb
from chromadb.config import Settings
from openai import OpenAI
from rank_bm25 import BM25Okapi

from .processor import ArticleChunk


class EmbeddingCache:
    """Simple LRU cache for query embeddings."""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.cache: OrderedDict[str, list[float]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, text: str) -> Optional[list[float]]:
        if text in self.cache:
            self.cache.move_to_end(text)
            self.hits += 1
            return self.cache[text]
        self.misses += 1
        return None

    def set(self, text: str, embedding: list[float]):
        if text in self.cache:
            self.cache.move_to_end(text)
        else:
            if len(self.cache) >= self.max_size:
                self.cache.popitem(last=False)
            self.cache[text] = embedding

    def stats(self) -> dict:
        total = self.hits + self.misses
        hit_rate = self.hits / total if total > 0 else 0
        return {"hits": self.hits, "misses": self.misses, "hit_rate": f"{hit_rate:.1%}"}


class BluegrassVectorStore:
    """Vector store combining ChromaDB (semantic) and BM25 (keyword) search."""

    COLLECTION_NAME = "bluegrass_articles"

    def __init__(
        self,
        persist_dir: str = "data/chroma",
        bm25_path: str = "data/bm25_index.pkl",
        cache_size: int = 1000,
    ):
        """
        Args:
            persist_dir: Directory for ChromaDB persistence
            bm25_path: Path to save/load BM25 index
            cache_size: Max number of query embeddings to cache
        """
        self.persist_dir = persist_dir
        self.bm25_path = bm25_path

        # Initialize OpenAI client for embeddings
        self.openai_client = OpenAI()

        # Query embedding cache
        self.embedding_cache = EmbeddingCache(max_size=cache_size)

        # Initialize ChromaDB
        self.chroma_client = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False)
        )

        # Get or create collection
        self.collection = self.chroma_client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )

        # BM25 components
        self.bm25_index: Optional[BM25Okapi] = None
        self.bm25_corpus: list[str] = []
        self.bm25_ids: list[str] = []

        # Load BM25 if exists
        self._load_bm25()

    def _get_embedding(self, text: str, use_cache: bool = True) -> list[float]:
        """Get embedding for text using OpenAI, with caching."""
        if use_cache:
            cached = self.embedding_cache.get(text)
            if cached is not None:
                return cached

        response = self.openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        embedding = response.data[0].embedding

        if use_cache:
            self.embedding_cache.set(text, embedding)

        return embedding

    def _get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for multiple texts."""
        # OpenAI allows up to 2048 inputs per request
        batch_size = 100
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            response = self.openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=batch
            )
            all_embeddings.extend([d.embedding for d in response.data])

        return all_embeddings

    def _tokenize(self, text: str) -> list[str]:
        """Simple tokenization for BM25."""
        # Lowercase and split on non-alphanumeric
        import re
        tokens = re.findall(r'\b\w+\b', text.lower())
        return tokens

    def _save_bm25(self):
        """Save BM25 index to disk."""
        os.makedirs(os.path.dirname(self.bm25_path), exist_ok=True)
        with open(self.bm25_path, 'wb') as f:
            pickle.dump({
                'corpus': self.bm25_corpus,
                'ids': self.bm25_ids,
            }, f)

    def _load_bm25(self):
        """Load BM25 index from disk if exists."""
        if os.path.exists(self.bm25_path):
            with open(self.bm25_path, 'rb') as f:
                data = pickle.load(f)
                self.bm25_corpus = data['corpus']
                self.bm25_ids = data['ids']
                if self.bm25_corpus:
                    tokenized = [self._tokenize(doc) for doc in self.bm25_corpus]
                    self.bm25_index = BM25Okapi(tokenized)

    def add_chunks(self, chunks: list[ArticleChunk], show_progress: bool = True):
        """
        Add chunks to both vector stores.

        Args:
            chunks: List of ArticleChunk objects
            show_progress: Whether to print progress
        """
        if not chunks:
            return

        if show_progress:
            print(f"Indexing {len(chunks)} chunks...")

        # Prepare data for ChromaDB
        ids = [chunk.chunk_id for chunk in chunks]
        texts = [chunk.text for chunk in chunks]
        metadatas = []

        for chunk in chunks:
            metadata = {
                "article_url": chunk.article_url,
                "title": chunk.title,
                "author": chunk.author,
                "source": chunk.source,
                "year": chunk.year or 0,
                "artist_subject": chunk.artist_subject or "",
                "artists_mentioned": ",".join(chunk.artists_mentioned),
                "instruments": ",".join(chunk.instruments),
                "topics": ",".join(chunk.topics),
                "tone": chunk.tone,
            }
            metadatas.append(metadata)

        # Get embeddings
        if show_progress:
            print("Generating embeddings...")
        embeddings = self._get_embeddings_batch(texts)

        # Add to ChromaDB in batches
        batch_size = 100
        for i in range(0, len(chunks), batch_size):
            end_idx = min(i + batch_size, len(chunks))
            self.collection.add(
                ids=ids[i:end_idx],
                embeddings=embeddings[i:end_idx],
                documents=texts[i:end_idx],
                metadatas=metadatas[i:end_idx],
            )
            if show_progress:
                print(f"  Added {end_idx}/{len(chunks)} to ChromaDB")

        # Build BM25 index
        if show_progress:
            print("Building BM25 index...")
        self.bm25_corpus = texts
        self.bm25_ids = ids
        tokenized_corpus = [self._tokenize(doc) for doc in texts]
        self.bm25_index = BM25Okapi(tokenized_corpus)
        self._save_bm25()

        if show_progress:
            print(f"Indexing complete. Total chunks: {self.collection.count()}")

    def semantic_search(
        self,
        query: str,
        k: int = 10,
        where: Optional[dict] = None,
    ) -> list[dict]:
        """
        Search using semantic similarity (embeddings).

        Args:
            query: Search query
            k: Number of results
            where: Optional ChromaDB filter dict

        Returns:
            List of results with text, metadata, and distance
        """
        query_embedding = self._get_embedding(query)

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        output = []
        for i in range(len(results['ids'][0])):
            output.append({
                'id': results['ids'][0][i],
                'text': results['documents'][0][i],
                'metadata': results['metadatas'][0][i],
                'distance': results['distances'][0][i],
                'score': 1 - results['distances'][0][i],  # Convert distance to similarity
            })
        return output

    def keyword_search(self, query: str, k: int = 10) -> list[dict]:
        """
        Search using BM25 keyword matching.

        Args:
            query: Search query
            k: Number of results

        Returns:
            List of results with text, id, and BM25 score
        """
        if self.bm25_index is None:
            return []

        tokenized_query = self._tokenize(query)
        scores = self.bm25_index.get_scores(tokenized_query)

        # Get top k indices
        top_indices = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True
        )[:k]

        output = []
        for idx in top_indices:
            if scores[idx] > 0:  # Only include if there's a match
                # Get full metadata from ChromaDB
                result = self.collection.get(
                    ids=[self.bm25_ids[idx]],
                    include=["documents", "metadatas"]
                )
                output.append({
                    'id': self.bm25_ids[idx],
                    'text': self.bm25_corpus[idx],
                    'metadata': result['metadatas'][0] if result['metadatas'] else {},
                    'score': scores[idx],
                })
        return output

    def get_chunk_count(self) -> int:
        """Get total number of chunks in the store."""
        return self.collection.count()

    def clear(self):
        """Clear all data from the vector store."""
        self.chroma_client.delete_collection(self.COLLECTION_NAME)
        self.collection = self.chroma_client.create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
        self.bm25_index = None
        self.bm25_corpus = []
        self.bm25_ids = []
        if os.path.exists(self.bm25_path):
            os.remove(self.bm25_path)


if __name__ == "__main__":
    # Quick test
    store = BluegrassVectorStore()
    print(f"Current chunk count: {store.get_chunk_count()}")
