"""
Domain-Agnostic Meme Generator.

Usage:
    from src.config import load_domain
    from src.core import DomainRAG, MemePipeline, PipelineConfig

    config = load_domain("bluegrass")
    rag = DomainRAG(config)
    # or
    pipeline = MemePipeline(config, PipelineConfig(num_concepts=15))
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

# Core components
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

__all__ = [
    # Configuration
    "DomainConfig",
    "EntityCategory",
    "TopicCategory",
    "ToneIndicator",
    "PromptTemplates",
    "load_domain",
    "list_domains",
    # Core RAG
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
]
