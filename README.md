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
cp .env.example .env
```

**Required keys:**

| Key | Where to get it |
|-----|-----------------|
| `OPENAI_API_KEY` | [OpenAI Platform](https://platform.openai.com/api-keys) - for embeddings |
| `XAI_API_KEY` | [xAI Console](https://console.x.ai/) - for Grok-4 generation |
| `IMGFLIP_USERNAME` | [imgflip.com](https://imgflip.com/) - free account |
| `IMGFLIP_PASSWORD` | Same imgflip account password |

**Optional keys (for niche discovery):**

| Key | Where to get it |
|-----|-----------------|
| `REDDIT_CLIENT_ID` | [Reddit Apps](https://www.reddit.com/prefs/apps) - create a "script" app |
| `REDDIT_CLIENT_SECRET` | Same Reddit app |

### 3. Index the articles (first time only)

```python
from src.config import load_domain
from src.core.rag import DomainRAG

config = load_domain("bluegrass")
rag = DomainRAG(config)
rag.index_articles("articles/bluegrass_unlimited_archives.json")
```

## Usage

### Web UI (Recommended)

The meme pipeline includes a web interface with a Master Dashboard for managing the full workflow:

```bash
python web/run.py
# Open http://localhost:5050 in your browser
```

**Dashboard Features:**
- **Stats Overview**: Template catalog size, pending daily candidates, gallery count, S3 configuration
- **Brand/Page Selector**: Switch between multiple Instagram pages (configured via `instagram_brands.json`)
- **Quick Links**: Direct access to Generate, Gallery, Templates Review, Discovery, and Video tools
- **Recent Memes Strip**: Preview of your latest generated content

**Pages:**
- **Dashboard**: Ops overview with stats and quick links
- **Spend**: Tech spending tracker for subscriptions and API costs
  - Tracks subscriptions (Imgflip, Vercel, etc.)
  - Shows API/usage costs (AWS Cost Explorer, xAI tokens, Fly.io hosting)
  - xAI / Grok tokens from shared S3 `ops/usage/` (local fallback if S3 is unset)
  - **By Project** rollup (tokens + allocated fixed). Unallocated stay visible.
  - Monthly total with active/cancelled breakdown
  - Subscription ledger: `data/tech_spend.json`
- **Generate**: Create memes with custom topics and settings
- **Gallery**: Browse and filter generated memes
- **Daily Queue**: Review daily candidate memes for Instagram
- **Templates**: Review and manage template descriptions
- **Video Memes**: Generate and edit video content
- **Discovery**: Find new niches and trending topics

**Multi-Brand Setup (Optional):**

Copy the example brands file and customize:
```bash
cp instagram_brands.example.json instagram_brands.json
# Edit instagram_brands.json to add your Instagram pages
```

The brand selector appears automatically when multiple brands are configured.

### Daily Candidate Queue & S3 Storage

The daily candidate workflow uses S3-backed storage for both queue metadata and images, making it container-friendly (Fly, Docker, etc.):

**Queue Storage:**
- Candidate queue JSON stored in S3 under `ops/queue/daily-candidates/{date}.json` (private)
- Local cache in `data/daily_candidates/` when S3 is unset or unreachable
- Web UI loads from S3 with local fallback

**Image Storage:**
- New generated JPEGs upload under `public/memes/generated/` (world-readable for Instagram)
- Template catalog stays at `public/memes/templates/{id}.{ext}` (not migrated)
- Candidate records include `public_url` and `s3_key` fields
- Review UI displays images directly from S3 public URLs
- Approve flow uses existing `public_url` (no local file dependency)

**Token usage (Spend):**
- Monthly JSON at `ops/usage/{provider}/{YYYY}/{MM}.json` (private; ETag concurrency)
- Local cache at `data/usage/{provider}/{YYYY}/{MM}.json`
- Each event includes `project` (string id). This repo defaults to `memes`.
- Other jobs (e.g. waiver-wire) set `USAGE_PROJECT` or `MEME_PROJECT` before `log_token_usage`. Same monthly S3 object — no per-project prefixes and no extra xAI keys.
- Logging a token call never breaks meme generation if S3 is down

See `infra/meme-assets/README.md` for the full bucket tree and IAM.

**Generation Flow:**
```bash
python scripts/generate_daily_candidates.py
# Generates memes, uploads each to S3, saves queue to S3 + local cache
```

**Review & Approve:**
1. Navigate to `/gallery/daily-candidates/` in the web UI
2. Images load from S3 public URLs
3. Approve publishes to Instagram using S3 URL directly
4. No shared filesystem required between generation and web host

**S3 Configuration Required:**
- `MEME_ASSETS_BUCKET`: S3 bucket name (see `infra/meme-assets/README.md`)
- `MEME_ASSETS_PUBLIC_BASE_URL`: Public HTTPS base URL for bucket
- `AWS_DEFAULT_REGION`: AWS region

If S3 is not configured, the system falls back to local-only storage (queue and images on disk).

### Generate Memes (Python API)

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
│   │   ├── s3_store.py                      # Shared S3 client + bucket layout
│   │   ├── token_tracker.py                 # xAI usage → ops/usage monthly JSON
│   │   ├── meme_assets.py                   # Public JPEG upload + queue JSON
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

## Production Deployment

The meme ops web UI can be deployed as a Docker container to Fly.io or any Docker host.

### Fly.io Deployment

1. **Install Fly CLI**: https://fly.io/docs/hands-on/install-flyctl/

2. **Login to Fly.io**:
   ```bash
   fly auth login
   ```

3. **Deploy the app**:
   ```bash
   fly launch
   # Or if already launched:
   fly deploy
   ```

4. **Set secrets** (required environment variables):
   ```bash
   fly secrets set \
     OPENAI_API_KEY=your_key \
     XAI_API_KEY=your_key \
     IMGFLIP_USERNAME=your_username \
     IMGFLIP_PASSWORD=your_password \
     MEME_ASSETS_BUCKET=bluegrass-meme-pipeline-dev-meme-assets \
     AWS_DEFAULT_REGION=us-east-1 \
     AWS_ACCESS_KEY_ID=your_key \
     AWS_SECRET_ACCESS_KEY=your_secret
   ```

   **Optional secrets** (for Instagram publishing, video generation, etc.):
   ```bash
   fly secrets set \
     META_IG_ACCESS_TOKEN=your_token \
     META_IG_USER_ID=your_user_id \
     META_APP_ID=your_app_id \
     META_PAGE_ID=your_page_id \
     ELEVENLABS_API_KEY=your_key \
     KLING_API_KEY=your_key
   ```

5. **Configure Cloudflare Access** (optional):
   - Point `ops.sethweiland.com` to your Fly.io app
   - Configure Cloudflare Access to protect the app
   - The app listens on `$PORT` (default 8080) and works behind reverse proxies

### Docker Deployment

Build and run locally:

```bash
# Build the image
docker build -t meme-ops .

# Run the container
docker run -p 8080:8080 \
  -e OPENAI_API_KEY=your_key \
  -e XAI_API_KEY=your_key \
  -e IMGFLIP_USERNAME=your_username \
  -e IMGFLIP_PASSWORD=your_password \
  meme-ops
```

### Health Check

The app exposes a `/healthz` endpoint that returns `{"status": "ok"}` for container orchestration health checks.

### Notes

- The app runs on port 8080 by default (configurable via `$PORT`)
- Uses gunicorn with 2 workers and 120s timeout
- Data directories (`data/`, `output/`) are ephemeral in the container
- Persist queue JSON and xAI token usage in S3 under `ops/` (same bucket as public memes)
- Generated Instagram JPEGs go under `public/memes/generated/`
- ChromaDB indexes are stored in `data/*/chroma/` and need to be pre-built or regenerated on startup

## License

MIT
