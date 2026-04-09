"""
Domain classifier for determining if a topic matches a configured domain.
Used to decide whether to use domain-specific RAG or web search fallback.
"""

from dataclasses import dataclass

from src.config import list_domains, load_domain
from .grok import GrokClient


@dataclass
class ClassificationResult:
    """Result of domain classification."""
    domain: str | None           # Matched domain name or None
    confidence: float            # 0.0-1.0
    suggested_searches: list[str]  # Web search queries for this topic


class DomainClassifier:
    """
    Classifies topics to determine if they match a configured domain.

    Uses keyword matching first (fast), then LLM classification if needed.
    """

    def __init__(self, grok: GrokClient | None = None):
        """
        Args:
            grok: Optional GrokClient for LLM classification. Created if not provided.
        """
        self._grok = grok
        self._owns_grok = False

    @property
    def grok(self) -> GrokClient:
        """Lazy-load GrokClient."""
        if self._grok is None:
            self._grok = GrokClient()
            self._owns_grok = True
        return self._grok

    def close(self):
        """Close the GrokClient if we own it."""
        if self._owns_grok and self._grok is not None:
            self._grok.close()
            self._grok = None

    def classify(self, topic: str) -> ClassificationResult:
        """
        Check if topic matches any configured domain.

        Uses a two-stage approach:
        1. Fast keyword matching against domain patterns
        2. LLM classification if keyword matching is inconclusive

        Args:
            topic: User's meme topic

        Returns:
            ClassificationResult with matched domain (or None), confidence, and search suggestions
        """
        available = list_domains()
        if not available:
            return ClassificationResult(
                domain=None,
                confidence=0.0,
                suggested_searches=self._suggest_searches(topic),
            )

        # Stage 1: Fast keyword matching
        keyword_match = self._keyword_match(topic, available)
        if keyword_match and keyword_match[1] >= 0.8:
            return ClassificationResult(
                domain=keyword_match[0],
                confidence=keyword_match[1],
                suggested_searches=[],  # Will use domain RAG, no need for searches
            )

        # Stage 2: LLM classification for ambiguous cases
        llm_result = self._llm_classify(topic, available)
        return llm_result

    def _keyword_match(
        self,
        topic: str,
        domains: list[str],
    ) -> tuple[str, float] | None:
        """
        Fast keyword matching against domain patterns.

        Args:
            topic: User's topic
            domains: List of available domain names

        Returns:
            Tuple of (domain_name, confidence) or None if no match
        """
        topic_lower = topic.lower()
        best_match: tuple[str, float] | None = None

        for domain_name in domains:
            try:
                config = load_domain(domain_name)
            except ValueError:
                continue

            score = 0.0
            matches = 0

            # Check domain name directly
            if domain_name.lower() in topic_lower:
                score += 0.5
                matches += 1

            # Check display name
            if config.display_name.lower() in topic_lower:
                score += 0.4
                matches += 1

            # Check entity categories (instruments, etc.)
            for cat in config.entity_categories:
                for entity, patterns in cat.patterns.items():
                    for pattern in [entity] + patterns:
                        if pattern.lower() in topic_lower:
                            score += 0.3
                            matches += 1
                            break

            # Check topic categories
            for cat in config.topic_categories:
                for pattern in cat.patterns:
                    if pattern.lower() in topic_lower:
                        score += 0.2
                        matches += 1
                        break

            # Normalize score (cap at 1.0)
            confidence = min(1.0, score)

            if confidence > 0 and (best_match is None or confidence > best_match[1]):
                best_match = (domain_name, confidence)

        return best_match

    def _llm_classify(
        self,
        topic: str,
        domains: list[str],
    ) -> ClassificationResult:
        """
        Use LLM to classify topic into a domain (or none).

        Args:
            topic: User's topic
            domains: Available domain names

        Returns:
            ClassificationResult
        """
        # Build domain descriptions
        domain_info = {}
        for name in domains:
            try:
                config = load_domain(name)
                domain_info[name] = config.description
            except ValueError:
                continue

        if not domain_info:
            return ClassificationResult(
                domain=None,
                confidence=0.0,
                suggested_searches=self._suggest_searches(topic),
            )

        # Build prompt
        domain_list = "\n".join(
            f"- {name}: {desc}" for name, desc in domain_info.items()
        )

        prompt = f"""Given the meme topic "{topic}", determine if it matches any of these domains:

{domain_list}

If the topic clearly fits a domain, respond with:
DOMAIN: domain_name
CONFIDENCE: high/medium/low

If the topic doesn't fit any domain well, respond with:
DOMAIN: none
SEARCHES: query1 | query2 | query3

For example:
- "banjo memes" would match "bluegrass" with high confidence
- "elon musk memes" would match none, with searches like "elon musk news | elon musk twitter | tesla memes"

Be strict - only match if the topic is clearly about the domain's subject matter."""

        try:
            response = self.grok._chat(
                [{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.3,
            )

            return self._parse_llm_response(response, topic)

        except Exception as e:
            print(f"  LLM classification failed: {e}")
            return ClassificationResult(
                domain=None,
                confidence=0.0,
                suggested_searches=self._suggest_searches(topic),
            )

    def _parse_llm_response(
        self,
        response: str,
        topic: str,
    ) -> ClassificationResult:
        """Parse LLM classification response."""
        response_upper = response.upper()

        domain = None
        confidence = 0.0
        searches: list[str] = []

        for line in response.split("\n"):
            line = line.strip()
            upper = line.upper()

            if upper.startswith("DOMAIN:"):
                value = line.split(":", 1)[1].strip().lower()
                if value != "none":
                    domain = value

            elif upper.startswith("CONFIDENCE:"):
                value = line.split(":", 1)[1].strip().lower()
                if "high" in value:
                    confidence = 0.9
                elif "medium" in value:
                    confidence = 0.7
                elif "low" in value:
                    confidence = 0.5

            elif upper.startswith("SEARCHES:"):
                value = line.split(":", 1)[1].strip()
                searches = [s.strip() for s in value.split("|") if s.strip()]

        # If no domain matched, generate search suggestions
        if not domain and not searches:
            searches = self._suggest_searches(topic)

        return ClassificationResult(
            domain=domain,
            confidence=confidence,
            suggested_searches=searches,
        )

    def _suggest_searches(self, topic: str) -> list[str]:
        """
        Generate web search queries for any topic.

        Args:
            topic: The meme topic

        Returns:
            List of 2-3 search queries
        """
        # Clean topic - remove common suffixes
        clean_topic = topic.lower()
        for suffix in [" memes", " meme", " jokes", " humor"]:
            if clean_topic.endswith(suffix):
                clean_topic = clean_topic[:-len(suffix)].strip()

        return [
            f"{clean_topic} funny",
            f"{clean_topic} news 2024",
            f"why {clean_topic} is popular",
        ][:3]
