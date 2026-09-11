#!/usr/bin/env python3
"""
Summarize saved meme feedback into topic/template signals.

This is a bridge toward a smarter radar: before we model anything fancy, we
need a small factual report of what users selected and rated.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FEEDBACK_PATH = ROOT / "data" / "feedback.json"
OUT_PATH = ROOT / "data" / "feedback_summary.json"


def avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def summarize(path: Path = FEEDBACK_PATH) -> dict:
    if not path.exists():
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "sessions": 0,
            "topics": [],
            "templates": [],
        }

    entries = json.loads(path.read_text(encoding="utf-8"))
    topic_stats: dict[str, dict] = defaultdict(lambda: {
        "topic": "",
        "sessions": 0,
        "memes": 0,
        "selected": 0,
        "ratings": [],
        "templates": defaultdict(int),
    })
    template_stats: dict[str, dict] = defaultdict(lambda: {
        "template": "",
        "memes": 0,
        "selected": 0,
        "ratings": [],
        "topics": defaultdict(int),
    })

    for entry in entries:
        topic = (entry.get("topic") or "unknown").strip() or "unknown"
        tstats = topic_stats[topic]
        tstats["topic"] = topic
        tstats["sessions"] += 1

        for meme in entry.get("memes", []):
            template = (meme.get("format") or meme.get("template") or "unknown").strip() or "unknown"
            selected = bool(meme.get("selected"))
            rating = meme.get("user_rating")

            tstats["memes"] += 1
            tstats["templates"][template] += 1
            if selected:
                tstats["selected"] += 1
            if isinstance(rating, (int, float)):
                tstats["ratings"].append(float(rating))

            mstats = template_stats[template]
            mstats["template"] = template
            mstats["memes"] += 1
            mstats["topics"][topic] += 1
            if selected:
                mstats["selected"] += 1
            if isinstance(rating, (int, float)):
                mstats["ratings"].append(float(rating))

    topics = []
    for row in topic_stats.values():
        templates = sorted(row["templates"].items(), key=lambda item: item[1], reverse=True)
        topics.append({
            "topic": row["topic"],
            "sessions": row["sessions"],
            "memes": row["memes"],
            "selected": row["selected"],
            "selection_rate": round(row["selected"] / row["memes"], 3) if row["memes"] else 0,
            "avg_rating": avg(row["ratings"]),
            "top_templates": [{"template": name, "count": count} for name, count in templates[:8]],
        })

    templates = []
    for row in template_stats.values():
        topics_for_template = sorted(row["topics"].items(), key=lambda item: item[1], reverse=True)
        templates.append({
            "template": row["template"],
            "memes": row["memes"],
            "selected": row["selected"],
            "selection_rate": round(row["selected"] / row["memes"], 3) if row["memes"] else 0,
            "avg_rating": avg(row["ratings"]),
            "top_topics": [{"topic": name, "count": count} for name, count in topics_for_template[:8]],
        })

    topics.sort(key=lambda row: (row["avg_rating"] is not None, row["avg_rating"] or 0, row["selected"]), reverse=True)
    templates.sort(key=lambda row: (row["avg_rating"] is not None, row["avg_rating"] or 0, row["selected"]), reverse=True)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sessions": len(entries),
        "topics": topics,
        "templates": templates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize meme feedback")
    parser.add_argument("--input", default=str(FEEDBACK_PATH), help="Feedback JSON path")
    parser.add_argument("--output", default=str(OUT_PATH), help="Summary JSON path")
    args = parser.parse_args()

    summary = summarize(Path(args.input))
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Wrote {out_path}")
    print(f"Sessions: {summary['sessions']}")
    for topic in summary["topics"][:5]:
        rating = topic["avg_rating"] if topic["avg_rating"] is not None else "n/a"
        print(f"- {topic['topic']}: selected {topic['selected']}/{topic['memes']}, avg rating {rating}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
