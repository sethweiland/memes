# Niche Meme Discovery Tool

Identifies underserved online communities ripe for dedicated meme pages.

## Quick Start

```bash
# Generate candidate niches
python src/generate_niches.py

# Scrape Reddit metrics
python src/scrape_reddit.py

# Score opportunities
python src/score_niches.py

# Qualitative evaluation
python src/qualitative_eval.py

# Or run full pipeline
python src/run_pipeline.py
```

## Data Flow

```
config/niche_seeds.yaml     → LLM generates candidates
        ↓
data/candidates.json        → PRAW scrapes Reddit
        ↓
data/reddit_metrics.json    → Scoring algorithm
        ↓
data/scored_niches.json     → LLM evaluates meme-ability
        ↓
data/final_ranked.json      → Your ranked opportunities
```

## Key Files

- `data/run_history.json` - Tracks all runs with timestamps, topics tested
- `data/final_ranked.json` - Full ranked results with metadata
- `data/final_report.csv` - Clean summary for spreadsheets
