"""
Grok API client for meme content generation.
Uses xAI's Grok model via their API.
"""

import os
from dataclasses import dataclass

import httpx

from .secrets import get_secret_value


@dataclass
class MemeIdea:
    """A generated meme idea with supporting context."""
    format: str  # e.g., "Drake meme", "Distracted boyfriend"
    top_text: str
    bottom_text: str
    explanation: str
    source_quote: str  # Original quote that inspired this
    artist_reference: str


class GrokClient:
    """Client for xAI's Grok API."""

    BASE_URL = "https://api.x.ai/v1"
    DEFAULT_MODEL = "grok-4.6"

    def __init__(self, api_key: str | None = None, default_model: str | None = None):
        """
        Args:
            api_key: xAI API key. If not provided, uses XAI_API_KEY env var.
            default_model: Default model to use for API calls.
        """
        self.api_key = api_key or get_secret_value("XAI_API_KEY", ("XAI_API_KEY", "xai_api_key"))
        if not self.api_key:
            raise ValueError(
                "XAI_API_KEY not found. Set it in .env, AWS Secrets Manager, or pass api_key parameter."
            )
        self.default_model = default_model or self.DEFAULT_MODEL

        self.client = httpx.Client(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=600.0,  # grok-4.6 concept batches can be slow
        )

    def _chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 1.0,  # Higher = more creative/risky
        max_tokens: int = 1000,
    ) -> str:
        """
        Send a chat completion request to Grok.

        Args:
            messages: List of message dicts with role and content
            model: Model to use
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response

        Returns:
            Response content string
        """
        request_json = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        response = self.client.post("/chat/completions", json=request_json)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            detail = self._format_error_detail(response)
            raise RuntimeError(
                f"xAI chat completion failed ({response.status_code}) "
                f"for model '{request_json['model']}': {detail}"
            ) from e
        data = response.json()
        
        # Log token usage for spend tracking (S3 ops/usage + local fallback).
        # Cost is a heuristic — xAI chat responses only include token counts.
        try:
            usage = data.get("usage", {})
            if usage:
                from .token_tracker import log_token_usage, resolve_write_project
                log_token_usage(
                    provider="xai",
                    model=request_json["model"],
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    estimated_cost_usd=None,
                    project=resolve_write_project(),
                )
        except Exception:
            # Don't break generation if logging fails
            pass
        
        return data["choices"][0]["message"]["content"]

    @staticmethod
    def _format_error_detail(response: httpx.Response) -> str:
        """Return a useful xAI error message without leaking request secrets."""
        try:
            payload = response.json()
        except ValueError:
            text = response.text.strip()
            return text[:500] if text else "No response body"

        if isinstance(payload, dict):
            parts = []
            for key in ("error", "message", "code"):
                value = payload.get(key)
                if value:
                    parts.append(str(value))
            if parts:
                return " - ".join(parts)[:500]
        return str(payload)[:500]

    def generate_meme_ideas(
        self,
        topic: str,
        context_chunks: list[dict],
        num_ideas: int = 3,
    ) -> list[MemeIdea]:
        """
        Generate meme ideas based on retrieved bluegrass context.

        Args:
            topic: The meme topic/theme
            context_chunks: List of retrieved chunks with text and metadata
            num_ideas: Number of meme ideas to generate

        Returns:
            List of MemeIdea objects
        """
        # Format context for the prompt
        context_text = self._format_context(context_chunks)

        system_prompt = """You are a comedy writer specializing in bluegrass music humor.
You create memes that are funny to bluegrass fans - people who know the artists,
the inside jokes, the stereotypes, and the culture.

Your memes should:
- Reference specific artists, songs, or stories from bluegrass history
- Play on bluegrass stereotypes (banjo players, mandolin chop, high lonesome sound)
- Use authentic bluegrass dialect when appropriate ("ain't", "reckon", etc.)
- Be funny to people who actually know bluegrass, not just generic country music jokes
- Ground the humor in real quotes, stories, or facts from the provided context

Popular meme formats to consider:
- Drake meme (thing you don't want / thing you want)
- Distracted boyfriend (temptation vs. what you have)
- Two buttons (hard choice)
- Galaxy brain (increasingly absurd progression)
- "Nobody: / Bluegrass fans:" format
- "POV: You're..." format"""

        user_prompt = f"""Topic: {topic}

Here is relevant context from Bluegrass Unlimited archives:

{context_text}

Generate {num_ideas} meme ideas based on this context.

Use this EXACT format for each meme (no markdown, no numbering):

FORMAT: name of meme template
TOP_TEXT: the top text
BOTTOM_TEXT: the bottom text
EXPLANATION: why this is funny to bluegrass fans
SOURCE_QUOTE: quote or fact that inspired this
ARTIST_REFERENCE: which artist this references

---

FORMAT: next meme...
"""

        response = self._chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])

        return self._parse_meme_response(response)

    def _format_context(self, chunks: list[dict]) -> str:
        """Format context chunks for the prompt."""
        formatted = []
        for i, chunk in enumerate(chunks, 1):
            metadata = chunk.get('metadata', {})
            source = metadata.get('source', 'Unknown source')
            artist = metadata.get('artist_subject', '')
            year = metadata.get('year', '')

            header = f"[{i}] {source}"
            if artist:
                header += f" - About {artist}"
            if year:
                header += f" ({year})"

            formatted.append(f"{header}\n{chunk['text'][:1000]}")

        return "\n\n".join(formatted)

    def _parse_meme_response(self, response: str) -> list[MemeIdea]:
        """Parse Grok's response into MemeIdea objects."""
        import re
        import json as _json

        memes = []

        # JSON fallback: if no FORMAT: markers and response looks like JSON
        stripped = response.strip()
        if "FORMAT:" not in response.upper() and "TEMPLATE:" not in response.upper():
            if stripped.startswith(("{", "[")):
                try:
                    data = _json.loads(stripped)
                    if isinstance(data, dict):
                        data = [data]
                    for item in data:
                        if isinstance(item, dict):
                            memes.append(MemeIdea(
                                format=item.get("format", item.get("template", "")),
                                top_text=item.get("top_text", ""),
                                bottom_text=item.get("bottom_text", ""),
                                explanation=item.get("explanation", ""),
                                source_quote=item.get("source_quote", ""),
                                artist_reference=item.get("artist_reference", ""),
                            ))
                    if memes:
                        return memes
                except _json.JSONDecodeError:
                    pass

        # Split on "---" OR on blank line(s) followed by "FORMAT:" or "TEMPLATE:"
        # This handles both separator styles Grok might use
        sections = re.split(r'(?:^|\n)---\s*\n|(?:\n\s*\n)(?=(?:FORMAT|TEMPLATE):)', response, flags=re.IGNORECASE)

        def clean_value(val: str) -> str:
            """Clean markdown and parentheses from values."""
            val = val.strip()
            # Remove surrounding parentheses
            if val.startswith("(") and val.endswith(")"):
                val = val[1:-1]
            # Remove markdown bold
            val = val.replace("**", "")
            # Remove (none) or similar
            if val.lower() in ["(none)", "none", "n/a"]:
                val = ""
            return val.strip()

        field_marker_re = re.compile(
            r'\b(FORMAT|TEMPLATE|TOP[_ ]?(?:TEXT|PANEL[_ ]?TEXT)|BOTTOM[_ ]?(?:TEXT|PANEL[_ ]?TEXT)|'
            r'TOP_PANEL_TEXT|BOTTOM_PANEL_TEXT|PANEL[_ ]?\d+[_ ]?TEXT|'
            r'EXPLANATION|SOURCE[_ ]?QUOTE|ARTIST[_ ]?REFERENCE):',
            flags=re.IGNORECASE,
        )

        def normalize_inline_markers(text: str) -> str:
            """Put known field markers on their own lines when the model emits one-line records."""
            return field_marker_re.sub(lambda m: "\n" + m.group(0), text).strip()

        for section in sections:
            section = section.strip()
            if not section:
                continue

            meme = MemeIdea(
                format="",
                top_text="",
                bottom_text="",
                explanation="",
                source_quote="",
                artist_reference="",
            )

            section = normalize_inline_markers(section)
            lines = section.split('\n')
            current_field = None
            panel_texts: list[tuple[int, str]] = []

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                # Skip header lines like "**Meme Idea 1**"
                if line.startswith("**") and line.endswith("**"):
                    continue
                if line.startswith("#"):
                    continue

                # Remove leading ** from field labels
                line = line.lstrip("*").strip()

                upper_line = line.upper()
                if upper_line.startswith("FORMAT:") or upper_line.startswith("TEMPLATE:"):
                    meme.format = clean_value(line.split(":", 1)[1])
                    current_field = "format"
                elif re.match(r'^PANEL[_ ]?\d+[_ ]?TEXT:', upper_line):
                    label, value = line.split(":", 1)
                    panel_num_match = re.search(r'\d+', label)
                    panel_num = int(panel_num_match.group(0)) if panel_num_match else len(panel_texts) + 1
                    panel_texts.append((panel_num, clean_value(value)))
                    current_field = None
                elif upper_line.startswith("TOP_TEXT:") or upper_line.startswith("TOP TEXT:"):
                    meme.top_text = clean_value(line.split(":", 1)[1])
                    current_field = "top_text"
                elif upper_line.startswith("TOP_PANEL_TEXT:") or upper_line.startswith("TOP PANEL TEXT:"):
                    meme.top_text = clean_value(line.split(":", 1)[1])
                    current_field = "top_text"
                elif upper_line.startswith("BOTTOM_TEXT:") or upper_line.startswith("BOTTOM TEXT:"):
                    meme.bottom_text = clean_value(line.split(":", 1)[1])
                    current_field = "bottom_text"
                elif upper_line.startswith("BOTTOM_PANEL_TEXT:") or upper_line.startswith("BOTTOM PANEL TEXT:"):
                    meme.bottom_text = clean_value(line.split(":", 1)[1])
                    current_field = "bottom_text"
                elif upper_line.startswith("EXPLANATION:"):
                    meme.explanation = clean_value(line.split(":", 1)[1])
                    current_field = "explanation"
                elif upper_line.startswith("SOURCE_QUOTE:") or upper_line.startswith("SOURCE QUOTE:"):
                    meme.source_quote = clean_value(line.split(":", 1)[1])
                    current_field = "source_quote"
                elif upper_line.startswith("ARTIST_REFERENCE:") or upper_line.startswith("ARTIST REFERENCE:"):
                    meme.artist_reference = clean_value(line.split(":", 1)[1])
                    current_field = "artist_reference"
                elif current_field:
                    # Continuation of previous field
                    current_value = getattr(meme, current_field)
                    setattr(meme, current_field, current_value + " " + line)

            if panel_texts and not (meme.top_text or meme.bottom_text):
                panels = [text for _, text in sorted(panel_texts, key=lambda p: p[0]) if text]
                if panels:
                    meme.top_text = panels[0]
                    meme.bottom_text = " / ".join(panels[1:])

            if meme.format or meme.top_text:  # Has some content
                memes.append(meme)

        # Warn if parse success rate is low
        if len(sections) > 1 and len(memes) < len(sections) * 0.5:
            print(f"  Warning: parsed {len(memes)} memes from {len(sections)} sections — possible format drift")

        return memes

    def brainstorm_topics(
        self,
        context_chunks: list[dict],
        num_topics: int = 5,
    ) -> list[str]:
        """
        Generate potential meme topics from context.

        Args:
            context_chunks: Retrieved context chunks
            num_topics: Number of topics to generate

        Returns:
            List of topic suggestions
        """
        context_text = self._format_context(context_chunks[:5])

        prompt = f"""Based on these bluegrass articles, suggest {num_topics} funny meme topics.

{context_text}

Focus on:
- Artist personalities and quirks
- Instrument-specific stereotypes
- Genre debates and gatekeeping
- Festival culture
- Jam session dynamics

Return just the topics, one per line, no numbering."""

        response = self._chat([
            {"role": "user", "content": prompt}
        ], temperature=0.9)

        topics = [t.strip() for t in response.strip().split('\n') if t.strip()]
        return topics[:num_topics]

    def close(self):
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


if __name__ == "__main__":
    # Quick test (requires XAI_API_KEY)
    from dotenv import load_dotenv
    load_dotenv()

    try:
        client = GrokClient()
        print("Grok client initialized successfully")
    except ValueError as e:
        print(f"Grok client error: {e}")
