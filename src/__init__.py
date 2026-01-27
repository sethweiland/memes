"""
Domain-Agnostic Meme Generator.

New Usage (recommended):
    from src.config import load_domain
    from src.core import DomainRAG, MemePipeline, PipelineConfig

    config = load_domain("bluegrass")
    rag = DomainRAG(config)
    # or
    pipeline = MemePipeline(config, PipelineConfig(num_concepts=15))

Legacy Usage (deprecated but still works):
    from src import BluegrassRAG
    rag = BluegrassRAG()  # Shows deprecation warning
"""

# Configuration system
from .config import (
    DomainConfig,
    EntityCategory,
    TopicCategory,
    ToneIndicator,
    PromptTemplates,
    load_domain,
    list_domains,
)

# New generic exports (recommended)
from .core import (
    # RAG components
    DomainRAG,
    ContentProcessor,
    ContentChunk,
    DomainVectorStore,
    DomainRetriever,
    RetrievalResult,
    TokenBudget,
    TokenBudgetExceeded,
    # Meme generation
    GrokClient,
    MemeIdea,
    TemplatesCatalog,
    MemeTemplate,
    MemeEvaluator,
    ScoredMeme,
    MemeImageGenerator,
    GeneratedMeme,
    # Pipeline
    MemePipeline,
    PipelineConfig,
    PipelineResult,
)

# Backward compatibility (deprecated)
from .compat import (
    BluegrassRAG,
    BluegrassVectorStore,
    BluegrassRetriever,
    ArticleProcessor,
    ArticleChunk,
)

__all__ = [
    # Configuration
    "DomainConfig",
    "EntityCategory",
    "TopicCategory",
    "ToneIndicator",
    "PromptTemplates",
    "load_domain",
    "list_domains",
    # Core RAG (new)
    "DomainRAG",
    "ContentProcessor",
    "ContentChunk",
    "DomainVectorStore",
    "DomainRetriever",
    "RetrievalResult",
    "TokenBudget",
    "TokenBudgetExceeded",
    # Meme generation
    "GrokClient",
    "MemeIdea",
    "TemplatesCatalog",
    "MemeTemplate",
    "MemeEvaluator",
    "ScoredMeme",
    "MemeImageGenerator",
    "GeneratedMeme",
    # Pipeline
    "MemePipeline",
    "PipelineConfig",
    "PipelineResult",
    # Deprecated (backward compat)
    "BluegrassRAG",
    "BluegrassVectorStore",
    "BluegrassRetriever",
    "ArticleProcessor",
    "ArticleChunk",
]
