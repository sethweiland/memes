#!/usr/bin/env python3
"""
Cache Topic Radar candidates for one or all domain packs.

Examples:
    python scripts/cache_topic_radar.py --domain bluegrass --no-news
    python scripts/cache_topic_radar.py --all --limit 30
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import list_domains, load_domain
from src.core.topic_radar import build_topic_radar


OUT_DIR = ROOT / "data" / "topic_radar"


def balance_lanes(topics: list[dict], limit: int, per_lane: int) -> list[dict]:
    """Return a lane-balanced subset while preserving score order within lanes."""
    if per_lane <= 0:
        return topics[:limit]

    selected: list[dict] = []
    lane_counts: Counter[str] = Counter()
    deferred: list[dict] = []

    for topic in topics:
        lane = topic.get("lane", "")
        if lane_counts[lane] < per_lane:
            selected.append(topic)
            lane_counts[lane] += 1
        else:
            deferred.append(topic)
        if len(selected) >= limit:
            return selected

    for topic in deferred:
        selected.append(topic)
        if len(selected) >= limit:
            break
    return selected


def cache_domain(domain_name: str, limit: int, include_news: bool, per_lane: int) -> Path:
    config = load_domain(domain_name)
    raw_topics = build_topic_radar(config, limit=max(limit * 3, limit), include_news=include_news)
    topics = balance_lanes(raw_topics, limit=limit, per_lane=per_lane)
    lane_counts = Counter(topic["lane"] for topic in topics)

    payload = {
        "domain": config.name,
        "display_name": config.display_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "include_news": include_news,
        "limit": limit,
        "per_lane": per_lane,
        "count": len(topics),
        "lane_counts": dict(sorted(lane_counts.items())),
        "topics": topics,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{config.name}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Cache Topic Radar output")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--domain", help="Domain pack to cache, e.g. bluegrass")
    group.add_argument("--all", action="store_true", help="Cache all domain packs")
    parser.add_argument("--limit", type=int, default=30, help="Max topics per domain")
    parser.add_argument("--per-lane", type=int, default=4, help="Soft max topics per lane before filling remainder")
    parser.add_argument("--no-news", action="store_true", help="Skip live news search")
    args = parser.parse_args()

    domains = list_domains() if args.all else [args.domain]
    if not domains:
        print("No domain packs found")
        return 1

    include_news = not args.no_news
    for domain_name in domains:
        path = cache_domain(
            domain_name,
            limit=max(1, args.limit),
            include_news=include_news,
            per_lane=max(0, args.per_lane),
        )
        print(f"Cached {domain_name}: {path.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
