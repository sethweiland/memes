"""
Jinja2 prompt template management.
Loads and renders domain-specific prompt templates.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

if TYPE_CHECKING:
    from .domain_config import DomainConfig


class PromptTemplates:
    """
    Manages Jinja2 prompt templates for a domain.

    Templates are loaded from the domain's prompts/ directory.
    The domain config is always available as {{ domain }} in templates.

    Usage:
        templates = PromptTemplates(config.prompts_dir, config)
        prompt = templates.render("system_generation")
        prompt = templates.render("user_generation", topic="banjos", context="...")
    """

    TEMPLATE_NAMES = [
        "system_generation",    # Main meme generation system prompt
        "user_generation",      # Main meme generation user prompt
        "system_generation_free",
        "user_generation_free",
        "caption",              # Social media caption generation
        "brainstorm",           # Topic brainstorming
        "query_expansion",      # Search query expansion
        "evaluation",           # Meme concept evaluation
    ]

    def __init__(self, prompts_dir: Path, domain_config: "DomainConfig"):
        """
        Initialize prompt template manager.

        Args:
            prompts_dir: Directory containing .j2 template files
            domain_config: Domain configuration (available as {{ domain }})
        """
        self.prompts_dir = Path(prompts_dir)
        self.domain_config = domain_config

        if not self.prompts_dir.exists():
            raise FileNotFoundError(f"Prompts directory not found: {self.prompts_dir}")

        self.env = Environment(
            loader=FileSystemLoader(self.prompts_dir),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # Pre-check which templates exist
        self._available_templates = set()
        for name in self.TEMPLATE_NAMES:
            template_file = f"{name}.j2"
            if (self.prompts_dir / template_file).exists():
                self._available_templates.add(name)

    def has_template(self, template_name: str) -> bool:
        """Check if a template exists on disk (not just the static name list)."""
        if template_name in self._available_templates:
            return True
        return (self.prompts_dir / f"{template_name}.j2").exists()

    def render(self, template_name: str, **kwargs: Any) -> str:
        """
        Render a template with domain context and additional variables.

        Args:
            template_name: Name of template (without .j2 extension)
            **kwargs: Additional variables for the template

        Returns:
            Rendered prompt string

        Raises:
            TemplateNotFound: If template doesn't exist
        """
        template_file = f"{template_name}.j2"

        try:
            template = self.env.get_template(template_file)
        except TemplateNotFound:
            raise TemplateNotFound(
                f"Template '{template_name}' not found in {self.prompts_dir}. "
                f"Expected file: {template_file}"
            )

        # Always include domain config in context
        context = {
            "domain": self.domain_config,
            **kwargs
        }

        return template.render(**context)

    def list_available(self) -> list[str]:
        """List all available template names."""
        return sorted(self._available_templates)
