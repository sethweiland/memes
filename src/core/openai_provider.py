"""
OpenAI Responses API adapter for meme generation.

Implements the small client surface used by the existing pipeline:
_chat(...) and _parse_meme_response(...).
"""

from __future__ import annotations

from openai import OpenAI

from .grok import GrokClient, MemeIdea
from .secrets import get_secret_value


class OpenAIResponsesClient:
    """OpenAI client compatible with the existing GrokClient call shape."""

    DEFAULT_MODEL = "gpt-5.4-mini"

    def __init__(self, api_key: str | None = None, default_model: str | None = None):
        self.api_key = api_key or get_secret_value("OPENAI_API_KEY", ("OPENAI_API_KEY", "openai_api_key"))
        if not self.api_key:
            raise ValueError(
                "OPENAI_API_KEY not found. Set it in .env, AWS Secrets Manager, "
                "or pass api_key parameter."
            )
        self.default_model = default_model or self.DEFAULT_MODEL
        self.client = OpenAI(api_key=self.api_key)

    def _chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 1.0,
        max_tokens: int = 1000,
    ) -> str:
        """Send a text generation request through the Responses API."""
        target_model = model or self.default_model
        instructions = []
        input_messages = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                instructions.append(content)
            else:
                input_messages.append({
                    "role": "assistant" if role == "assistant" else "user",
                    "content": content,
                })

        kwargs = {
            "model": target_model,
            "input": input_messages or [{"role": "user", "content": ""}],
            "max_output_tokens": max_tokens,
        }
        if instructions:
            kwargs["instructions"] = "\n\n".join(instructions)

        # Some reasoning models ignore or reject temperature. Try it first for
        # compatibility with existing creativity controls, then retry plainly.
        try:
            response = self.client.responses.create(**kwargs, temperature=temperature)
        except Exception as e:
            if "temperature" not in str(e).lower():
                raise
            response = self.client.responses.create(**kwargs)

        return response.output_text

    def _parse_meme_response(self, response: str) -> list[MemeIdea]:
        """Reuse the existing robust meme parser."""
        return GrokClient._parse_meme_response(None, response)
