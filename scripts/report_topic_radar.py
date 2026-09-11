#!/usr/bin/env python3
"""
Print a readable report from a cached Topic Radar file.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RADAR_DIR = ROOT / "data" / "topic_radar"


def report(domain: str, limit: int) -> str:
    path = RADAR_DIR / f"{domain}.json"
    if not path.exists():
        raise FileNotFoundError(f"No cached radar file found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    lanes: dict[str, list[dict]] = defaultdict(list)
    for topic in data.get("topics", []):
        lanes[topic.get("lane", "unknown")].append(topic)

    lines = [
        f"Topic Radar: {data.get('display_name', domain)}",
        f"Generated: {data.get('generated_at', 'unknown')}",
        f"Count: {data.get('count', 0)}",
        "",
    ]

    for lane, topics in sorted(lanes.items()):
        lines.append(f"## {lane.replace('_', ' ').title()}")
        for topic in topics[:limit]:
            lines.append(f"- {topic.get('overall_score', '?')} {topic.get('topic', '')}")
            if topic.get("meme_angle"):
                lines.append(f"  angle: {topic['meme_angle']}")
            if topic.get("why_now"):
                lines.append(f"  why: {topic['why_now']}")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Report cached Topic Radar output")
    parser.add_argument("--domain", default="bluegrass", help="Domain cache to report")
    parser.add_argument("--limit", type=int, default=5, help="Topics per lane")
    args = parser.parse_args()

    print(report(args.domain, max(1, args.limit)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
