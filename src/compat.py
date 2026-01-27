"""
Backward compatibility layer for existing code.
Allows existing code using BluegrassRAG to continue working.

DEPRECATED: Use the new domain-agnostic classes instead:
    - DomainRAG instead of BluegrassRAG
    - DomainVectorStore instead of BluegrassVectorStore
    - DomainRetriever instead of BluegrassRetriever
    - ContentProcessor instead of ArticleProcessor
    - ContentChunk instead of ArticleChunk
"""

import warnings
from pathlib import Path
from typing import Optional

from .config.domain_config import DomainConfig
from .core.rag import DomainRAG, TokenBudget, TokenBudgetExceeded
from .core.vectorstore import DomainVectorStore
from .core.retriever import DomainRetriever
from .core.processor import ContentProcessor, ContentChunk
from .core.pipeline import MemePipeline, PipelineConfig

# Default domain config path
_DEFAULT_BLUEGRASS_CONFIG = Path(__file__).parent.parent / "domains/bluegrass/config.yaml"


def _get_default_bluegrass_config() -> DomainConfig:
    """Load the default bluegrass configuration."""
    if not _DEFAULT_BLUEGRASS_CONFIG.exists():
        raise FileNotFoundError(
            f"Default bluegrass config not found at {_DEFAULT_BLUEGRASS_CONFIG}. "
            "Please ensure the domains/bluegrass/ directory exists with config.yaml"
        )
    return DomainConfig.from_yaml(_DEFAULT_BLUEGRASS_CONFIG)


class BluegrassRAG(DomainRAG):
    """
    Backward-compatible BluegrassRAG class.

    DEPRECATED: Use DomainRAG with explicit domain configuration instead.

    Example migration:
        # Old way (deprecated)
        rag = BluegrassRAG()

        # New way
        from src.config import load_domain
        config = load_domain("bluegrass")
        rag = DomainRAG(config)
    """

    def __init__(
        self,
        persist_dir: str = "data/chroma",
        bm25_path: str = "data/bm25_index.pkl",
        chunk_size: int = 750,
        chunk_overlap: int = 100,
        token_budget: Optional[int] = None,
    ):
        warnings.warn(
            "BluegrassRAG is deprecated. Use DomainRAG with explicit domain config instead. "
            "See src/compat.py docstring for migration example.",
            DeprecationWarning,
            stacklevel=2
        )
        domain_config = _get_default_bluegrass_config()
        super().__init__(domain_config, token_budget=token_budget)


class BluegrassVectorStore(DomainVectorStore):
    """
    Backward-compatible BluegrassVectorStore class.

    DEPRECATED: Use DomainVectorStore with explicit domain configuration instead.
    """

    def __init__(
        self,
        persist_dir: str = "data/chroma",
        bm25_path: str = "data/bm25_index.pkl",
        cache_size: int = 1000,
    ):
        warnings.warn(
            "BluegrassVectorStore is deprecated. Use DomainVectorStore instead.",
            DeprecationWarning,
            stacklevel=2
        )
        domain_config = _get_default_bluegrass_config()
        super().__init__(domain_config, persist_dir=persist_dir, bm25_path=bm25_path, cache_size=cache_size)


class BluegrassRetriever(DomainRetriever):
    """
    Backward-compatible BluegrassRetriever class.

    DEPRECATED: Use DomainRetriever with explicit domain configuration instead.
    """

    def __init__(self, vectorstore: Optional[BluegrassVectorStore] = None):
        warnings.warn(
            "BluegrassRetriever is deprecated. Use DomainRetriever instead.",
            DeprecationWarning,
            stacklevel=2
        )
        domain_config = _get_default_bluegrass_config()
        super().__init__(domain_config, vectorstore=vectorstore)


class ArticleProcessor(ContentProcessor):
    """
    Backward-compatible ArticleProcessor class.

    DEPRECATED: Use ContentProcessor with explicit domain configuration instead.
    """

    def __init__(self, chunk_size: int = 750, chunk_overlap: int = 100):
        warnings.warn(
            "ArticleProcessor is deprecated. Use ContentProcessor instead.",
            DeprecationWarning,
            stacklevel=2
        )
        domain_config = _get_default_bluegrass_config()
        super().__init__(domain_config, chunk_size=chunk_size, chunk_overlap=chunk_overlap)


# Alias for backward compatibility
ArticleChunk = ContentChunk
