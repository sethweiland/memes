"""
Bluegrass RAG Pipeline for Meme Generation.
"""

from .rag import BluegrassRAG
from .processor import ArticleProcessor, ArticleChunk
from .vectorstore import BluegrassVectorStore
from .retriever import BluegrassRetriever, RetrievalResult
from .grok import GrokClient, MemeIdea
from .templates import TemplatesCatalog, MemeTemplate
from .evaluator import MemeEvaluator, ScoredMeme
from .meme_generator import MemeImageGenerator, GeneratedMeme
from .pipeline import MemePipeline, PipelineConfig, PipelineResult

__all__ = [
    # Core RAG
    "BluegrassRAG",
    "ArticleProcessor",
    "ArticleChunk",
    "BluegrassVectorStore",
    "BluegrassRetriever",
    "RetrievalResult",
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
