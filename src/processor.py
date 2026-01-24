"""
Article processor for chunking and metadata extraction.
Handles loading bluegrass articles, extracting rich metadata, and smart chunking.
"""

import json
import re
from typing import Optional
from dataclasses import dataclass, field, asdict

import tiktoken


# Known bluegrass artists for entity extraction
KNOWN_ARTISTS = {
    "Bill Monroe", "Earl Scruggs", "Lester Flatt", "Ralph Stanley", "Carter Stanley",
    "Jimmy Martin", "Mac Wiseman", "Del McCoury", "Ricky Skaggs", "Tony Rice",
    "J.D. Crowe", "Doyle Lawson", "Sam Bush", "Bela Fleck", "Jerry Douglas",
    "Alison Krauss", "Rhonda Vincent", "Doc Watson", "Clarence White", "Roland White",
    "Bobby Osborne", "Sonny Osborne", "Red Allen", "Frank Wakefield", "David Grisman",
    "Peter Rowan", "Vassar Clements", "Kenny Baker", "Byron Berline", "Stuart Duncan",
    "Mark O'Connor", "Chris Thile", "Sierra Hull", "Molly Tuttle", "Billy Strings",
    "Red Rector", "Larry Sparks", "Charlie Waller", "John Duffey", "Mike Auldridge",
    "Curly Seckler", "Chubby Wise", "Cedric Rainwater", "Howard Watts", "Don Reno",
    "Red Smiley", "Jim & Jesse", "Jim McReynolds", "Jesse McReynolds", "Carl Story",
    "Hylo Brown", "Charlie Moore", "Bill Napier", "The Country Gentlemen",
    "The Seldom Scene", "New Grass Revival", "Bluegrass Alliance", "The Dillards",
}

# Instruments for classification
INSTRUMENTS = {
    "mandolin": ["mandolin", "mando"],
    "banjo": ["banjo", "5-string", "five-string"],
    "fiddle": ["fiddle", "violin", "fiddler", "fiddlin"],
    "guitar": ["guitar", "flatpick", "flat-pick", "dreadnought"],
    "dobro": ["dobro", "resonator", "resophonic"],
    "bass": ["bass", "upright bass", "string bass", "doghouse"],
}

# Topics for classification
TOPIC_PATTERNS = {
    "technique": ["technique", "style", "picking", "chop", "lick", "run"],
    "history": ["history", "origin", "began", "started", "founded", "early days"],
    "recording": ["record", "album", "session", "studio", "track"],
    "touring": ["tour", "road", "travel", "show", "festival", "concert"],
    "personal": ["born", "grew up", "childhood", "family", "married", "wife", "husband"],
    "gear": ["instrument", "strings", "pick", "mic", "amp", "setup"],
    "business": ["contract", "label", "money", "paid", "booking", "manager"],
    "jam": ["jam", "picking party", "session", "sitting in"],
}


@dataclass
class ArticleChunk:
    """A chunk of an article with extracted metadata."""
    text: str
    chunk_id: str
    article_url: str
    title: str
    author: str
    source: str
    year: Optional[int] = None
    artist_subject: Optional[str] = None
    artists_mentioned: list[str] = field(default_factory=list)
    instruments: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    tone: str = "informative"

    def to_dict(self) -> dict:
        return asdict(self)


class ArticleProcessor:
    """Process bluegrass articles into searchable chunks with metadata."""

    def __init__(self, chunk_size: int = 750, chunk_overlap: int = 100):
        """
        Args:
            chunk_size: Target tokens per chunk (500-1000 recommended)
            chunk_overlap: Overlap tokens between chunks
        """
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

        # Remove navigation menu items (often appear as single words on lines)
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

        # Remove "Reprinted from" header if it appears mid-content (keep at start)
        lines = content.split('\n')
        cleaned_lines = []
        seen_real_content = False
        for line in lines:
            stripped = line.strip()
            # Skip empty nav-like short lines at the start
            if not seen_real_content and len(stripped) < 20 and stripped in [
                'Contact', 'Subscribe', 'Search', 'Login', 'Magazine', '>', '|'
            ]:
                continue
            if len(stripped) > 50:  # Found real content
                seen_real_content = True
            cleaned_lines.append(line)
        content = '\n'.join(cleaned_lines)

        # Remove repeated whitespace but preserve paragraph breaks
        content = re.sub(r'\n{3,}', '\n\n', content)
        content = re.sub(r' {2,}', ' ', content)
        content = re.sub(r'^\s*\|\s*$', '', content, flags=re.MULTILINE)  # Lone pipes

        return content.strip()

    def _extract_year(self, article: dict) -> Optional[int]:
        """Extract publication year from article metadata."""
        source = article.get('original_source') or ''
        # Look for patterns like "September 1975" or "1975"
        match = re.search(r'\b(19[5-9]\d|20[0-2]\d)\b', source)
        if match:
            return int(match.group(1))
        return None

    def _extract_source_info(self, article: dict) -> str:
        """Extract clean source citation."""
        source = article.get('original_source') or ''
        # Extract "Bluegrass Unlimited Magazine Month Year" pattern
        match = re.search(
            r'Bluegrass Unlimited(?:\s+Magazine)?\s+(\w+\s+\d{4})',
            source
        )
        if match:
            return f"Bluegrass Unlimited, {match.group(1)}"
        return "Bluegrass Unlimited"

    def _extract_artist_subject(self, article: dict) -> Optional[str]:
        """Determine the main artist subject of the article."""
        title = article.get('title') or ''
        content = (article.get('content') or '')[:2000]  # Check first part

        # Check title first
        for artist in KNOWN_ARTISTS:
            if artist.lower() in title.lower():
                return artist

        # Check early content for artist names
        artist_counts = {}
        for artist in KNOWN_ARTISTS:
            count = len(re.findall(
                rf'\b{re.escape(artist)}\b',
                content,
                re.IGNORECASE
            ))
            if count > 0:
                artist_counts[artist] = count

        if artist_counts:
            return max(artist_counts, key=artist_counts.get)
        return None

    def _extract_artists_mentioned(self, text: str) -> list[str]:
        """Find all artists mentioned in text."""
        mentioned = []
        for artist in KNOWN_ARTISTS:
            if re.search(rf'\b{re.escape(artist)}\b', text, re.IGNORECASE):
                mentioned.append(artist)
        return mentioned

    def _extract_instruments(self, text: str) -> list[str]:
        """Identify instruments mentioned in text."""
        found = []
        text_lower = text.lower()
        for instrument, patterns in INSTRUMENTS.items():
            for pattern in patterns:
                if pattern in text_lower:
                    found.append(instrument)
                    break
        return found

    def _extract_topics(self, text: str) -> list[str]:
        """Classify text into topic categories."""
        found = []
        text_lower = text.lower()
        for topic, patterns in TOPIC_PATTERNS.items():
            for pattern in patterns:
                if pattern in text_lower:
                    found.append(topic)
                    break
        return found

    def _detect_tone(self, text: str) -> str:
        """Detect the tone of the text."""
        text_lower = text.lower()

        # Check for nostalgic indicators
        nostalgic_words = ["remember", "those days", "back then", "used to", "old times"]
        if any(word in text_lower for word in nostalgic_words):
            return "nostalgic"

        # Check for humorous indicators
        humor_words = ["funny", "laugh", "joke", "hilarious", "crazy"]
        if any(word in text_lower for word in humor_words):
            return "humorous"

        # Check for technical/instructional
        tech_words = ["technique", "position", "finger", "fret", "timing"]
        if any(word in text_lower for word in tech_words):
            return "technical"

        # Check for personal/biographical
        personal_words = ["born", "grew up", "childhood", "family"]
        if any(word in text_lower for word in personal_words):
            return "biographical"

        return "informative"

    def _split_into_paragraphs(self, text: str) -> list[str]:
        """Split text into paragraphs while preserving structure."""
        paragraphs = re.split(r'\n\n+', text)
        return [p.strip() for p in paragraphs if p.strip()]

    def _chunk_text(self, text: str) -> list[str]:
        """
        Chunk text with overlap, preserving paragraph boundaries where possible.
        """
        paragraphs = self._split_into_paragraphs(text)
        chunks = []
        current_chunk = []
        current_tokens = 0

        for para in paragraphs:
            para_tokens = self._count_tokens(para)

            # If single paragraph exceeds chunk size, split it
            if para_tokens > self.chunk_size:
                # Finish current chunk first
                if current_chunk:
                    chunks.append('\n\n'.join(current_chunk))
                    current_chunk = []
                    current_tokens = 0

                # Split large paragraph by sentences
                sentences = re.split(r'(?<=[.!?])\s+', para)
                for sent in sentences:
                    sent_tokens = self._count_tokens(sent)
                    if current_tokens + sent_tokens > self.chunk_size and current_chunk:
                        chunks.append(' '.join(current_chunk))
                        # Keep overlap
                        overlap_text = ' '.join(current_chunk[-2:]) if len(current_chunk) > 1 else ''
                        current_chunk = [overlap_text] if overlap_text else []
                        current_tokens = self._count_tokens(overlap_text) if overlap_text else 0
                    current_chunk.append(sent)
                    current_tokens += sent_tokens

            # Normal case: paragraph fits
            elif current_tokens + para_tokens <= self.chunk_size:
                current_chunk.append(para)
                current_tokens += para_tokens

            # Chunk is full, start new one with overlap
            else:
                chunks.append('\n\n'.join(current_chunk))

                # Create overlap from end of current chunk
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

        # Add final chunk
        if current_chunk:
            chunks.append('\n\n'.join(current_chunk))

        return chunks

    def process_article(self, article: dict, article_idx: int) -> list[ArticleChunk]:
        """Process a single article into chunks with metadata."""
        content = self._clean_content(article.get('content') or '')

        if not content or len(content) < 100:
            return []

        # Extract article-level metadata
        year = self._extract_year(article)
        source = self._extract_source_info(article)
        artist_subject = self._extract_artist_subject(article)
        title = article.get('title') or 'Unknown'
        author = article.get('author') or 'Unknown'
        # Clean author string (remove date portion)
        author = re.sub(r'\s*\|\s*\w+\s+\d+,\s+\d+', '', author).strip() or 'Unknown'

        # Chunk the content
        text_chunks = self._chunk_text(content)

        chunks = []
        for i, chunk_text in enumerate(text_chunks):
            chunk = ArticleChunk(
                text=chunk_text,
                chunk_id=f"article_{article_idx}_chunk_{i}",
                article_url=article.get('url', ''),
                title=title,
                author=author,
                source=source,
                year=year,
                artist_subject=artist_subject,
                artists_mentioned=self._extract_artists_mentioned(chunk_text),
                instruments=self._extract_instruments(chunk_text),
                topics=self._extract_topics(chunk_text),
                tone=self._detect_tone(chunk_text),
            )
            chunks.append(chunk)

        return chunks

    def process_all(self, json_path: str) -> list[ArticleChunk]:
        """Process all articles from JSON file."""
        articles = self.load_articles(json_path)
        all_chunks = []

        for idx, article in enumerate(articles):
            chunks = self.process_article(article, idx)
            all_chunks.extend(chunks)

        return all_chunks


if __name__ == "__main__":
    # Quick test
    processor = ArticleProcessor()
    chunks = processor.process_all("articles/bluegrass_unlimited_archives.json")
    print(f"Processed {len(chunks)} chunks")
    if chunks:
        print(f"Sample chunk: {chunks[0].to_dict()}")
