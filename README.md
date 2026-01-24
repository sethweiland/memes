# Bluegrass Meme Generator

A RAG-powered pipeline that generates bluegrass music memes using historical content from Bluegrass Unlimited magazine archives.

## How It Works

```
Bluegrass Unlimited Archives (276 articles)
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

- **RAG Pipeline**: Hybrid search (semantic + keyword) over 2000+ chunks of bluegrass history
- **Smart Context**: Retrieves relevant quotes, stories, and facts to ground meme humor
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
from src.rag import BluegrassRAG

rag = BluegrassRAG()
rag.index_articles("articles/bluegrass_unlimited_archives.json")
```

## Usage

### Generate Memes

```python
from src.pipeline import MemePipeline, PipelineConfig

config = PipelineConfig(
    num_concepts=15,    # How many ideas to generate
    num_images=10,      # How many to render
    creativity=1.2,     # 0.0-1.5, higher = more creative
)

pipeline = MemePipeline(config)
result = pipeline.run("what makes bluegrass special")

# Images saved to output/memes/
# Each meme includes a caption with historical context
```

### Search the Archives

```python
from src.rag import BluegrassRAG

rag = BluegrassRAG()

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
bluegrass/
├── articles/
│   └── bluegrass_unlimited_archives.json   # Source data
├── data/
│   ├── chroma/                             # Vector DB
│   └── bm25_index.pkl                      # Keyword search index
├── output/
│   └── memes/                              # Generated memes
├── src/
│   ├── processor.py      # Article chunking + metadata extraction
│   ├── vectorstore.py    # ChromaDB + BM25 hybrid search
│   ├── retriever.py      # Query expansion + reranking
│   ├── templates.py      # imgflip template catalog
│   ├── grok.py           # Grok-4 API client
│   ├── meme_generator.py # imgflip image generation
│   ├── pipeline.py       # Main orchestration
│   └── rag.py            # RAG interface
├── .env.example
├── requirements.txt
└── README.md
```

## Configuration

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

## License

MIT
