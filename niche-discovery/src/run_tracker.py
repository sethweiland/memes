"""
Run history tracking for the niche discovery pipeline.

Tracks:
- All pipeline runs with timestamps
- Which niches have been tested
- Scores and evaluations over time
- Manual notes (e.g., Instagram page exists)
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"


@dataclass
class NicheRecord:
    """A single niche with all its metadata."""
    niche_name: str
    category: str
    subreddit: str
    subscribers: int = 0

    # Scores
    quantitative_score: float = 0.0
    qualitative_score: float = 0.0
    final_score: float = 0.0

    # Qualitative eval
    inside_joke_density: int = 0
    visual_meme_potential: int = 0
    identity_strength: int = 0
    engagement_likelihood: int = 0
    content_sustainability: int = 0
    top_themes: list[str] = field(default_factory=list)
    sample_meme_concepts: list[str] = field(default_factory=list)
    risks: str = ""

    # Metadata
    first_discovered: str = ""
    last_evaluated: str = ""
    run_ids: list[str] = field(default_factory=list)

    # Manual fields (you fill these in)
    instagram_page_exists: Optional[bool] = None
    instagram_page_url: str = ""
    instagram_followers: int = 0
    notes: str = ""
    status: str = "new"  # new, researching, launched, skipped


@dataclass
class RunRecord:
    """A single pipeline run."""
    run_id: str
    timestamp: str
    categories_processed: list[str]
    niches_generated: int
    niches_scored: int
    top_10_niches: list[str]
    config: dict = field(default_factory=dict)


class RunTracker:
    """Tracks all pipeline runs and niche discoveries."""

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.history_file = self.data_dir / "run_history.json"
        self.niches_file = self.data_dir / "all_niches.json"

        self.runs: list[RunRecord] = []
        self.niches: dict[str, NicheRecord] = {}  # keyed by lowercase niche_name

        self._load()

    def _load(self):
        """Load existing history."""
        if self.history_file.exists():
            data = json.loads(self.history_file.read_text())
            self.runs = [RunRecord(**r) for r in data.get("runs", [])]
            logger.info(f"Loaded {len(self.runs)} previous runs")

        if self.niches_file.exists():
            data = json.loads(self.niches_file.read_text())
            self.niches = {
                k: NicheRecord(**v) for k, v in data.items()
            }
            logger.info(f"Loaded {len(self.niches)} tracked niches")

    def _save(self):
        """Save history to disk."""
        # Save runs
        self.history_file.write_text(json.dumps({
            "runs": [asdict(r) for r in self.runs],
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }, indent=2))

        # Save niches
        self.niches_file.write_text(json.dumps({
            k: asdict(v) for k, v in self.niches.items()
        }, indent=2))

    def start_run(self, categories: list[str], config: dict = None) -> str:
        """Start a new pipeline run. Returns run_id."""
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        run = RunRecord(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            categories_processed=categories,
            niches_generated=0,
            niches_scored=0,
            top_10_niches=[],
            config=config or {},
        )
        self.runs.append(run)
        self._save()
        logger.info(f"Started run {run_id}")
        return run_id

    def update_run(self, run_id: str, **kwargs):
        """Update a run's metadata."""
        for run in self.runs:
            if run.run_id == run_id:
                for k, v in kwargs.items():
                    setattr(run, k, v)
                self._save()
                return

    def add_or_update_niche(self, niche: NicheRecord, run_id: str):
        """Add a niche or update existing one."""
        key = niche.niche_name.lower().strip()

        if key in self.niches:
            # Update existing - preserve manual fields
            existing = self.niches[key]
            niche.instagram_page_exists = existing.instagram_page_exists
            niche.instagram_page_url = existing.instagram_page_url
            niche.instagram_followers = existing.instagram_followers
            niche.notes = existing.notes
            niche.status = existing.status
            niche.first_discovered = existing.first_discovered
            niche.run_ids = existing.run_ids + [run_id]
        else:
            niche.first_discovered = datetime.now(timezone.utc).isoformat()
            niche.run_ids = [run_id]

        niche.last_evaluated = datetime.now(timezone.utc).isoformat()
        self.niches[key] = niche
        self._save()

    def get_tested_niches(self) -> set[str]:
        """Get all niche names we've already tested."""
        return set(self.niches.keys())

    def get_niches_by_status(self, status: str) -> list[NicheRecord]:
        """Get niches by status (new, researching, launched, skipped)."""
        return [n for n in self.niches.values() if n.status == status]

    def export_csv(self, output_path: Path = None) -> Path:
        """Export all niches to CSV for spreadsheet analysis."""
        import csv

        output_path = output_path or (self.data_dir / "niches_export.csv")

        fields = [
            "niche_name", "category", "subreddit", "subscribers",
            "final_score", "quantitative_score", "qualitative_score",
            "inside_joke_density", "visual_meme_potential", "identity_strength",
            "top_themes", "sample_meme_concepts", "risks",
            "instagram_page_exists", "instagram_page_url", "notes", "status",
            "first_discovered", "last_evaluated"
        ]

        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for niche in sorted(self.niches.values(), key=lambda x: -x.final_score):
                row = asdict(niche)
                row["top_themes"] = "; ".join(row["top_themes"])
                row["sample_meme_concepts"] = "; ".join(row["sample_meme_concepts"])
                writer.writerow({k: row[k] for k in fields})

        logger.info(f"Exported {len(self.niches)} niches to {output_path}")
        return output_path

    def print_summary(self):
        """Print a summary of tracked data."""
        print(f"\n{'='*60}")
        print("NICHE DISCOVERY TRACKER SUMMARY")
        print(f"{'='*60}")
        print(f"Total runs: {len(self.runs)}")
        print(f"Total niches tracked: {len(self.niches)}")
        print()

        by_status = {}
        for n in self.niches.values():
            by_status[n.status] = by_status.get(n.status, 0) + 1
        print("By status:")
        for status, count in sorted(by_status.items()):
            print(f"  {status}: {count}")

        print()
        print("Top 10 by final score:")
        top = sorted(self.niches.values(), key=lambda x: -x.final_score)[:10]
        for i, n in enumerate(top, 1):
            ig = "📸" if n.instagram_page_exists else "  "
            print(f"  {i:2}. {ig} {n.niche_name[:30]:30} ({n.subreddit}) - {n.final_score:.1f}")
        print()
