"""
Content processor for chunking and metadata extraction.
Generic implementation that works with any domain configuration.
"""

import json
import re
from typing import Optional, TYPE_CHECKING
from dataclasses import dataclass, field, asdict

import tiktoken

if TYPE_CHECKING:
    from ..config.domain_config import DomainConfig


@dataclass
class ContentChunk:
    """A chunk of content with extracted metadata."""
    text: str
    chunk_id: str
    content_url: str
    title: str
    author: str
    source: str
    year: Optional[int] = None
    primary_entity: Optional[str] = None
    entities_mentioned: list[str] = field(default_factory=list)
    categories: dict[str, list[str]] = field(default_factory=dict)
    topics: list[str] = field(default_factory=list)
    tone: str = "informative"

    # Backward compatibility properties
    @property
    def artist_subject(self) -> Optional[str]:
        return self.primary_entity

    @property
    def artists_mentioned(self) -> list[str]:
        return self.entities_mentioned

    @property
    def instruments(self) -> list[str]:
        return self.categories.get('instruments', [])

    @property
    def article_url(self) -> str:
        return self.content_url

    def to_dict(self) -> dict:
        return asdict(self)


# Backward compatibility alias
ArticleChunk = ContentChunk


class ContentProcessor:
    """
    Process content into searchable chunks with metadata extraction.

    Uses domain configuration for entity extraction instead of hardcoded values.
    """

    def __init__(
        self,
        domain_config: "DomainConfig",
        chunk_size: int = 750,
        chunk_overlap: int = 100
    ):
        """
        Args:
            domain_config: Domain configuration with entities and categories
            chunk_size: Target tokens per chunk (500-1000 recommended)
            chunk_overlap: Overlap tokens between chunks
        """
        self.domain = domain_config
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.tokenizer = tiktoken.get_encoding("cl100k_base")

    def load_articles(self, json_path: str) -> list[dict]:
        """Load articles from JSON file."""
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self.tokenizer.encode(text))

    def _clean_content(self, content: str) -> str:
        """Clean article content while preserving dialect and speech patterns."""
        # Remove large navigation blocks
        content = re.sub(r'Skip to content.*?The Archives', '', content, flags=re.DOTALL)
        content = re.sub(r'Log in to Your Account.*?The Archives', '', content, flags=re.DOTALL)

        # Remove navigation menu items
        nav_patterns = [
            r'^Home\s*$', r'^Articles\s*$', r'^Search\s*$', r'^Login\s*$',
            r'^Contact\s*$', r'^Subscribe\s*$', r'^Magazine\s*$',
            r'^The Tradition\s*$', r'^The Artists\s*$', r'^The Sound\s*$',
            r'^The Venue\s*$', r'^Reviews\s*$', r'^Podcasts\s*$',
            r'^Lessons\s*$', r'^Jam Track\s*$', r'^The Archives\s*$',
            r'^Current Issue\s*$', r'^Past Issues\s*$', r'^Festival Guide\s*$',
            r'^Talent Directory\s*$', r'^Workshops/Camps\s*$', r'^Our History\s*$',
            r'^Staff\s*$', r'^Advertise\s*$', r'^Remember Me\s*$',
            r'^Log In\s*$', r'^Register\s*$', r'^Lost your password\?\s*$',
        ]
        for pattern in nav_patterns:
            content = re.sub(pattern, '', content, flags=re.MULTILINE)

        # Remove social/metadata lines
        content = re.sub(r'^Facebook\s*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'^Tweet\s*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'^Print\s*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'^\|\s*No Comments\s*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'^\|\s*Posted on.*$', '', content, flags=re.MULTILINE)

        # Remove breadcrumb patterns
        content = re.sub(r'Home\s*>\s*Articles\s*>\s*The Archives\s*>', '', content)
        content = re.sub(r'Home\s*>\s*Articles\s*Articles', '', content)
        content = re.sub(r'Home\s*>\s*Articles', '', content)

        # Remove other boilerplate
        content = re.sub(r'Read More »', '', content)
        content = re.sub(r'IssueM Articles', '', content)
        content = re.sub(r'Log in to Your Account', '', content)

        # Clean up whitespace
        lines = content.split('\n')
        cleaned_lines = []
        seen_real_content = False
        for line in lines:
            stripped = line.strip()
            if not seen_real_content and len(stripped) < 20 and stripped in [
                'Contact', 'Subscribe', 'Search', 'Login', 'Magazine', '>', '|'
            ]:
                continue
            if len(stripped) > 50:
                seen_real_content = True
            cleaned_lines.append(line)
        content = '\n'.join(cleaned_lines)

        content = re.sub(r'\n{3,}', '\n\n', content)
        content = re.sub(r' {2,}', ' ', content)
        content = re.sub(r'^\s*\|\s*$', '', content, flags=re.MULTILINE)

        return content.strip()

    def _extract_year(self, article: dict) -> Optional[int]:
        """Extract publication year from article metadata."""
        source = article.get('original_source') or ''
        match = re.search(r'\b(19[5-9]\d|20[0-2]\d)\b', source)
        if match:
            return int(match.group(1))
        return None

    def _extract_source_info(self, article: dict) -> str:
        """Extract clean source citation."""
        source = article.get('original_source') or ''
        # Try to extract source name and date
        source_name = self.domain.content_source_name
        match = re.search(
            rf'{re.escape(source_name)}(?:\s+Magazine)?\s+(\w+\s+\d{{4}})',
            source
        )
        if match:
            return f"{source_name}, {match.group(1)}"
        return source_name

    def _extract_primary_entity(self, article: dict) -> Optional[str]:
        """Determine the main entity subject of the article."""
        title = article.get('title') or ''
        content = (article.get('content') or '')[:2000]

        all_entities = self.domain.get_all_known_entities()

        # Check title first
        for entity in all_entities:
            if entity.lower() in title.lower():
                return entity

        # Check early content
        entity_counts = {}
        for entity in all_entities:
            count = len(re.findall(
                rf'\b{re.escape(entity)}\b',
                content,
                re.IGNORECASE
            ))
            if count > 0:
                entity_counts[entity] = count

        if entity_counts:
            return max(entity_counts, key=entity_counts.get)
        return None

    def _extract_entities_mentioned(self, text: str) -> list[str]:
        """Find all known entities mentioned in text."""
        mentioned = []
        all_entities = self.domain.get_all_known_entities()
        for entity in all_entities:
            if re.search(rf'\b{re.escape(entity)}\b', text, re.IGNORECASE):
                mentioned.append(entity)
        return mentioned

    def _extract_categories(self, text: str) -> dict[str, list[str]]:
        """Extract all category matches from text."""
        found = {}
        text_lower = text.lower()

        for category in self.domain.entity_categories:
            matches = []
            for name, patterns in category.patterns.items():
                for pattern in patterns:
                    if pattern in text_lower:
                        matches.append(name)
                        break
            if matches:
                found[category.name] = list(set(matches))

        return found

    def _extract_topics(self, text: str) -> list[str]:
        """Classify text into topic categories."""
        found = []
        text_lower = text.lower()

        for topic in self.domain.topic_categories:
            for pattern in topic.patterns:
                if pattern in text_lower:
                    found.append(topic.name)
                    break

        return found

    def _detect_tone(self, text: str) -> str:
        """Detect the tone of the text."""
        text_lower = text.lower()

        for indicator in self.domain.tone_indicators:
            if any(pattern in text_lower for pattern in indicator.patterns):
                return indicator.tone

        return "informative"

    def _split_into_paragraphs(self, text: str) -> list[str]:
        """Split text into paragraphs while preserving structure."""
        paragraphs = re.split(r'\n\n+', text)
        return [p.strip() for p in paragraphs if p.strip()]

    def _chunk_text(self, text: str) -> list[str]:
        """Chunk text with overlap, preserving paragraph boundaries where possible."""
        paragraphs = self._split_into_paragraphs(text)
        chunks = []
        current_chunk = []
        current_tokens = 0

        for para in paragraphs:
            para_tokens = self._count_tokens(para)

            if para_tokens > self.chunk_size:
                if current_chunk:
                    chunks.append('\n\n'.join(current_chunk))
                    current_chunk = []
                    current_tokens = 0

                sentences = re.split(r'(?<=[.!?])\s+', para)
                for sent in sentences:
                    sent_tokens = self._count_tokens(sent)
                    if current_tokens + sent_tokens > self.chunk_size and current_chunk:
                        chunks.append(' '.join(current_chunk))
                        overlap_text = ' '.join(current_chunk[-2:]) if len(current_chunk) > 1 else ''
                        current_chunk = [overlap_text] if overlap_text else []
                        current_tokens = self._count_tokens(overlap_text) if overlap_text else 0
                    current_chunk.append(sent)
                    current_tokens += sent_tokens

            elif current_tokens + para_tokens <= self.chunk_size:
                current_chunk.append(para)
                current_tokens += para_tokens

            else:
                chunks.append('\n\n'.join(current_chunk))

                overlap_tokens = 0
                overlap_paras = []
                for p in reversed(current_chunk):
                    p_tokens = self._count_tokens(p)
                    if overlap_tokens + p_tokens <= self.chunk_overlap:
                        overlap_paras.insert(0, p)
                        overlap_tokens += p_tokens
                    else:
                        break

                current_chunk = overlap_paras + [para]
                current_tokens = overlap_tokens + para_tokens

        if current_chunk:
            chunks.append('\n\n'.join(current_chunk))

        return chunks

    def process_article(self, article: dict, article_idx: int) -> list[ContentChunk]:
        """Process a single article into chunks with metadata."""
        content = self._clean_content(article.get('content') or '')

        if not content or len(content) < 100:
            return []

        year = self._extract_year(article)
        source = self._extract_source_info(article)
        primary_entity = self._extract_primary_entity(article)
        title = article.get('title') or 'Unknown'
        author = article.get('author') or 'Unknown'
        author = re.sub(r'\s*\|\s*\w+\s+\d+,\s+\d+', '', author).strip() or 'Unknown'

        text_chunks = self._chunk_text(content)

        chunks = []
        for i, chunk_text in enumerate(text_chunks):
            chunk = ContentChunk(
                text=chunk_text,
                chunk_id=f"article_{article_idx}_chunk_{i}",
                content_url=article.get('url', ''),
                title=title,
                author=author,
                source=source,
                year=year,
                primary_entity=primary_entity,
                entities_mentioned=self._extract_entities_mentioned(chunk_text),
                categories=self._extract_categories(chunk_text),
                topics=self._extract_topics(chunk_text),
                tone=self._detect_tone(chunk_text),
            )
            chunks.append(chunk)

        return chunks

    def process_all(self, json_path: str) -> list[ContentChunk]:
        """Process all articles from JSON file."""
        articles = self.load_articles(json_path)
        all_chunks = []

        for idx, article in enumerate(articles):
            chunks = self.process_article(article, idx)
            all_chunks.extend(chunks)

        return all_chunks


# Backward compatibility alias
ArticleProcessor = ContentProcessor
