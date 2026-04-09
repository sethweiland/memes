"""
Core components for domain-agnostic meme generation.
"""

from .processor import ContentProcessor, ContentChunk
from .vectorstore import DomainVectorStore
from .retriever import DomainRetriever, RetrievalResult
from .rag import DomainRAG, TokenBudget, TokenBudgetExceeded
from .grok import GrokClient, MemeIdea
from .templates import TemplatesCatalog, MemeTemplate
from .evaluator import MemeEvaluator, ScoredMeme
from .meme_generator import MemeImageGenerator, GeneratedMeme
from .pipeline import MemePipeline, PipelineConfig, PipelineResult
from .two_stage import TwoStagePipeline, GenericTwoStagePipeline, EvaluatedMeme
from .output import save_manifest, save_meme_metadata, print_summary
from .current_events import CurrentEventsSearch
from .fallback_context import FallbackContextProvider
from .domain_classifier import DomainClassifier, ClassificationResult
from .generic_config import GenericConfig, get_generic_config, GENERIC_EVALUATION_CRITERIA

__all__ = [
    "ContentProcessor",
    "ContentChunk",
    "DomainVectorStore",
    "DomainRetriever",
    "RetrievalResult",
    "DomainRAG",
    "TokenBudget",
    "TokenBudgetExceeded",
    "GrokClient",
    "MemeIdea",
    "TemplatesCatalog",
    "MemeTemplate",
    "MemeEvaluator",
    "ScoredMeme",
    "MemeImageGenerator",
    "GeneratedMeme",
    "MemePipeline",
    "PipelineConfig",
    "PipelineResult",
    "TwoStagePipeline",
    "GenericTwoStagePipeline",
    "EvaluatedMeme",
    "CurrentEventsSearch",
    "FallbackContextProvider",
    "DomainClassifier",
    "ClassificationResult",
    "GenericConfig",
    "get_generic_config",
    "GENERIC_EVALUATION_CRITERIA",
]
