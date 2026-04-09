"""
Domain configuration utilities.

Usage:
    from src.config import load_domain, list_domains

    config = load_domain("bluegrass")
    # Use config with DomainRAG, MemePipeline, etc.
"""

from pathlib import Path
from typing import Optional

from .domain_config import DomainConfig, EntityCategory, TopicCategory, ToneIndicator
from .prompt_templates import PromptTemplates

# Default domains directory (relative to project root)
_DOMAINS_DIR = Path(__file__).parent.parent.parent / "domains"


def load_domain(name: str, domains_dir: Optional[Path] = None) -> DomainConfig:
    """
    Load a domain configuration by name.

    Args:
        name: Domain name (e.g., "bluegrass")
        domains_dir: Optional custom domains directory

    Returns:
        DomainConfig for the domain

    Raises:
        ValueError: If domain not found

    Example:
        config = load_domain("bluegrass")
        rag = DomainRAG(config)
    """
    domains_dir = domains_dir or _DOMAINS_DIR
    config_path = domains_dir / name / "config.yaml"

    if not config_path.exists():
        available = list_domains(domains_dir)
        raise ValueError(
            f"Domain '{name}' not found at {config_path}. "
            f"Available domains: {available or 'none'}"
        )

    return DomainConfig.from_yaml(config_path)


def list_domains(domains_dir: Optional[Path] = None) -> list[str]:
    """
    List all available domain configurations.

    Args:
        domains_dir: Optional custom domains directory

    Returns:
        List of domain names
    """
    domains_dir = domains_dir or _DOMAINS_DIR

    if not domains_dir.exists():
        return []

    return sorted([
        d.name for d in domains_dir.iterdir()
        if d.is_dir() and (d / "config.yaml").exists()
    ])


__all__ = [
    "DomainConfig",
    "EntityCategory",
    "TopicCategory",
    "ToneIndicator",
    "PromptTemplates",
    "load_domain",
    "list_domains",
]
