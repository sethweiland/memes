# Domain-Agnostic Meme Generator

A RAG-powered pipeline that generates memes using historical content from any domain. Ships with a bluegrass music configuration using Bluegrass Unlimited magazine archives.

## How It Works

```
Content Archives (e.g., 276 bluegrass articles)
              ↓
     [RAG: ChromaDB + BM25]
              ↓
  Topic → Retrieve Context → Grok-4 → Meme Concepts
              ↓
     [imgflip API] → Images + Captions
              ↓
        Output: Memes with historical context
```

## Features

- **Domain-Agnostic**: Configure for any content domain via YAML
- **RAG Pipeline**: Hybrid search (semantic + keyword) over chunked content
- **Prompt Templates**: Jinja2 templates for all LLM prompts
- **Grok-4 Generation**: Creates meme concepts with appropriate templates
- **Caption Generation**: Adds historical context for social media posts
- **imgflip Integration**: Renders actual meme images from 100+ templates

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API keys

Copy `.env.example` to `.env` and add your keys:

```bash
# Required
OPENAI_API_KEY=your_openai_key      # For embeddings
XAI_API_KEY=your_xai_key            # For Grok-4

# Required for image generation
IMGFLIP_USERNAME=your_username       # Free account at imgflip.com
IMGFLIP_PASSWORD=your_password
```

### 3. Index the articles (first time only)

```python
from src.config import load_domain
from src.core.rag import DomainRAG

config = load_domain("bluegrass")
rag = DomainRAG(config)
rag.index_articles("articles/bluegrass_unlimited_archives.json")
```

## Usage

### Generate Memes

```python
from src.config import load_domain
from src.core.pipeline import MemePipeline, PipelineConfig

config = load_domain("bluegrass")
pipeline_config = PipelineConfig(
    num_concepts=15,    # How many ideas to generate
    num_images=10,      # How many to render
    creativity=1.2,     # 0.0-1.5, higher = more creative
)

pipeline = MemePipeline(config, pipeline_config)
result = pipeline.run("what makes bluegrass special")

# Images saved to output/memes/
# Each meme includes a caption with historical context
```

### Search the Archives

```python
from src.config import load_domain
from src.core.rag import DomainRAG

config = load_domain("bluegrass")
rag = DomainRAG(config)

# Basic search
results = rag.search("Earl Scruggs three-finger picking", k=5)

# Search with filters
results = rag.search(
    "mandolin technique",
    filters={"instrument": "mandolin", "year_range": (1960, 1980)}
)

# Search by artist
results = rag.search_by_artist("Bill Monroe", k=5)
```

## Project Structure

```
meme-generator/
├── articles/
│   └── bluegrass_unlimited_archives.json   # Source content
├── domains/                                 # Domain configurations
│   └── bluegrass/
│       ├── config.yaml                      # Domain settings
│       ├── entities.yaml                    # Known entities (artists, etc.)
│       └── prompts/                         # Jinja2 prompt templates
│           ├── system_generation.j2
│           ├── user_generation.j2
│           ├── caption.j2
│           ├── brainstorm.j2
│           ├── query_expansion.j2
│           └── evaluation.j2
├── data/
│   └── bluegrass/                           # Domain-specific indexes
│       ├── chroma/                          # Vector DB
│       └── bm25_index.pkl                   # Keyword search index
├── output/
│   └── memes/                               # Generated memes
├── src/
│   ├── config/                              # Configuration system
│   │   ├── domain_config.py                 # DomainConfig dataclass
│   │   ├── prompt_templates.py              # Jinja2 template manager
│   │   └── __init__.py                      # load_domain(), list_domains()
│   ├── core/                                # Core components
│   │   ├── processor.py                     # Content chunking + metadata
│   │   ├── vectorstore.py                   # ChromaDB + BM25 hybrid search
│   │   ├── retriever.py                     # Query expansion + reranking
│   │   ├── rag.py                           # DomainRAG interface
│   │   ├── pipeline.py                      # Main orchestration
│   │   ├── grok.py                          # Grok-4 API client
│   │   ├── templates.py                     # imgflip template catalog
│   │   ├── evaluator.py                     # Meme scoring
│   │   └── meme_generator.py                # imgflip image generation
│   ├── compat.py                            # Backward compatibility
│   └── __init__.py
├── .env.example
├── requirements.txt
└── README.md
```

## Domain Configuration

Each domain is configured via YAML files in `domains/<name>/`:

### config.yaml
```yaml
name: bluegrass
display_name: Bluegrass Music
description: Bluegrass music culture and history

content_source_name: Bluegrass Unlimited
content_source_description: Bluegrass Unlimited Archives

tone_guidelines:
  - Be affectionate toward legends, not mocking
  - Humor should come from love of the genre

style_guidelines:
  - Write in normal internet English
  - Avoid overdoing dialect

humor_focus:
  - Artist personalities and quirks
  - Instrument-specific stereotypes
```

### entities.yaml
```yaml
known_entities:
  artists:
    - Bill Monroe
    - Earl Scruggs
    # ...
```

### prompts/*.j2
Jinja2 templates with access to `{{ domain }}` configuration:
```jinja2
You are a comedy writer for {{ domain.display_name | lower }} memes.
{% for guideline in domain.tone_guidelines %}
- {{ guideline }}
{% endfor %}
```

## Adding a New Domain

1. Create `domains/<name>/config.yaml` with domain settings
2. Create `domains/<name>/entities.yaml` with known entities
3. Create `domains/<name>/prompts/` with all 6 prompt templates
4. Add your content source JSON
5. Index and generate:

```python
from src.config import load_domain
from src.core.rag import DomainRAG
from src.core.pipeline import MemePipeline, PipelineConfig

config = load_domain("your_domain")
rag = DomainRAG(config)
rag.index_articles("path/to/your/content.json")

pipeline = MemePipeline(config)
result = pipeline.run("your topic")
```

## Pipeline Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `num_concepts` | 100 | Meme ideas to generate |
| `num_images` | 5 | Final images to render |
| `creativity` | 1.0 | Temperature for Grok (0.0-1.5) |
| `token_budget` | 100000 | Max tokens per session |

## Costs

Approximate costs per run (10 memes):
- Grok-4: ~$0.005
- OpenAI embeddings: ~$0.001
- imgflip: Free

## Example Output

Each meme comes with:
1. **Image**: Rendered meme from imgflip
2. **Caption**: Historical context for posting

```
#1 - Always Has Been
   "Wait, bluegrass banjo has always been Earl Scruggs?" / "Always has been"

   Caption: Ever wonder why bluegrass fans lose it over this meme? It's a nod
   to how Scruggs revolutionized the genre in the 1940s with his three-finger
   picking style, essentially defining modern bluegrass banjo.
```

## Backward Compatibility

The old API still works but shows deprecation warnings:

```python
# Old way (deprecated)
from src import BluegrassRAG
rag = BluegrassRAG()  # Shows deprecation warning

# New way (recommended)
from src.config import load_domain
from src.core.rag import DomainRAG
config = load_domain("bluegrass")
rag = DomainRAG(config)
```

## License

MIT
