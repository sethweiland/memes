"""
Domain-aware topic radar.

The radar proposes meme topics before generation. It is deliberately source
shaped: each candidate says where it came from, why it might matter now, and
what comedic angle the generator should exploit.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from src.config.domain_config import DomainConfig
from src.core.current_events import CurrentEventsSearch


@dataclass
class TopicCandidate:
    topic: str
    lane: str
    source: str
    why_now: str
    meme_angle: str
    audience: str
    freshness_score: int
    relevance_score: int
    comedy_score: int
    risk_notes: str = ""

    @property
    def overall_score(self) -> float:
        return round(
            self.freshness_score * 0.25
            + self.relevance_score * 0.35
            + self.comedy_score * 0.40,
            1,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["overall_score"] = self.overall_score
        return data


class TopicRadar:
    """Generate scored topic candidates for a domain pack."""

    def __init__(self, domain: DomainConfig):
        self.domain = domain
        self.raw_config = self._load_raw_config()
        self.radar_config = self.raw_config.get("topic_radar", {}) or {}
        self.rng = random.Random(self._seed(domain.name))

    def _seed(self, value: str) -> int:
        return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:8], 16)

    def _load_raw_config(self) -> dict[str, Any]:
        config_path = Path("domains") / self.domain.name / "config.yaml"
        if not config_path.exists():
            return {}
        try:
            return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}

    def generate(self, limit: int = 18, include_news: bool = True) -> list[TopicCandidate]:
        candidates: list[TopicCandidate] = []
        candidates.extend(self._configured_candidates())
        candidates.extend(self._anchor_artist_candidates())
        candidates.extend(self._evergreen_candidates())
        candidates.extend(self._festival_candidates())
        candidates.extend(self._wildcard_candidates())
        if include_news:
            candidates.extend(self._news_candidates())

        deduped = self._dedupe(candidates)
        deduped.sort(key=lambda c: c.overall_score, reverse=True)
        return deduped[:limit]

    def _configured_candidates(self) -> list[TopicCandidate]:
        rows = self.radar_config.get("seed_topics", []) or []
        candidates = []
        for row in rows:
            topic = str(row.get("topic", "")).strip()
            if not topic:
                continue
            candidates.append(TopicCandidate(
                topic=topic,
                lane=str(row.get("lane", "seed")),
                source=str(row.get("source", f"{self.domain.display_name} domain pack")),
                why_now=str(row.get("why_now", "Manually seeded as a reliable meme lane.")),
                meme_angle=str(row.get("meme_angle", "Find the social tension insiders recognize immediately.")),
                audience=str(row.get("audience", f"{self.domain.display_name} fans")),
                freshness_score=int(row.get("freshness_score", 6)),
                relevance_score=int(row.get("relevance_score", 9)),
                comedy_score=int(row.get("comedy_score", 8)),
                risk_notes=str(row.get("risk_notes", "")),
            ))
        return candidates

    def _anchor_artist_candidates(self) -> list[TopicCandidate]:
        people = list(self.domain.known_entities.get("artists", []))
        priority = self.radar_config.get("priority_entities", []) or []
        ordered = [p for p in priority if p in people]
        ordered.extend(p for p in people if p not in ordered)

        candidates = []
        for name in ordered[:12]:
            if name.lower() in {"bill monroe", "earl scruggs", "lester flatt"}:
                why_now = "Evergreen reference point: fans use the legends as cultural gravity."
                freshness = 5
            else:
                why_now = "Recurring artist lane with enough recognition for fresh jokes."
                freshness = 7
            candidates.append(TopicCandidate(
                topic=f"{name} fan behavior vs normal human behavior",
                lane="anchor_artist",
                source="entities.yaml artists",
                why_now=why_now,
                meme_angle="Turn fandom rituals, status signals, or show behavior into the joke.",
                audience=f"{self.domain.display_name} fans who know {name}",
                freshness_score=freshness,
                relevance_score=9,
                comedy_score=8,
                risk_notes="Keep it affectionate; joke about fan behavior or scene rituals more than the artist personally.",
            ))
        return candidates

    def _evergreen_candidates(self) -> list[TopicCandidate]:
        focus_items = self.domain.humor_focus or ["community rituals", "gear debates", "event culture"]
        candidates = []
        for focus in focus_items:
            candidates.append(TopicCandidate(
                topic=f"{focus} getting taken way too seriously",
                lane="evergreen_culture",
                source="domain humor_focus",
                why_now="Evergreen behavior that stays memeable even when there is no news hook.",
                meme_angle="Escalate a tiny insider ritual until it becomes absurdly high stakes.",
                audience=f"Core {self.domain.display_name} insiders",
                freshness_score=5,
                relevance_score=8,
                comedy_score=8,
            ))
        return candidates

    def _festival_candidates(self) -> list[TopicCandidate]:
        event_terms = self.radar_config.get("event_terms", []) or ["festival", "tour", "lineup", "camping"]
        candidates = []
        for term in event_terms[:8]:
            candidates.append(TopicCandidate(
                topic=f"upcoming {self.domain.display_name.lower()} {term} chaos",
                lane="festival_event",
                source="domain event terms",
                why_now="Events create deadline energy: lineups, travel, camping, tickets, weather, and group-chat planning.",
                meme_angle="Make the joke about preparation spiraling into a lifestyle crisis.",
                audience=f"{self.domain.display_name} event-goers",
                freshness_score=8,
                relevance_score=8,
                comedy_score=7,
            ))
        return candidates

    def _wildcard_candidates(self) -> list[TopicCandidate]:
        rituals = self.radar_config.get("rituals", []) or [
            "arguing about what counts as authentic",
            "buying gear to solve a personality problem",
            "turning a casual hang into a competitive display",
        ]
        candidates = []
        for ritual in rituals[:8]:
            candidates.append(TopicCandidate(
                topic=ritual,
                lane="wildcard",
                source="topic_radar rituals",
                why_now="Wildcard lane for weirder original memes and fake screenshot formats.",
                meme_angle="Treat the behavior like a public scandal, medical condition, or official institution.",
                audience=f"Online {self.domain.display_name} fans",
                freshness_score=6,
                relevance_score=7,
                comedy_score=9,
            ))
        return candidates

    def _news_candidates(self) -> list[TopicCandidate]:
        if not self.domain.current_events.enabled:
            return []

        try:
            items = CurrentEventsSearch(self.domain).filter_relevant(
                CurrentEventsSearch(self.domain).search_news()
            )
        except Exception:
            return []

        candidates = []
        for item in items[:8]:
            title = item.title.strip()
            if not title:
                continue
            candidates.append(TopicCandidate(
                topic=title,
                lane="current_event",
                source=item.source or "news search",
                why_now=item.body[:180].strip() if item.body else "Recent search result from the domain current-events radar.",
                meme_angle="Find the fan reaction, group-chat take, or tiny scene implication behind the headline.",
                audience=f"{self.domain.display_name} fans following current news",
                freshness_score=10,
                relevance_score=8,
                comedy_score=6,
                risk_notes="Verify facts before making a strong claim.",
            ))
        return candidates

    def _dedupe(self, candidates: list[TopicCandidate]) -> list[TopicCandidate]:
        seen: set[str] = set()
        deduped: list[TopicCandidate] = []
        for candidate in candidates:
            key = candidate.topic.lower().strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped


def build_topic_radar(domain: DomainConfig, limit: int = 18, include_news: bool = True) -> list[dict[str, Any]]:
    return [candidate.to_dict() for candidate in TopicRadar(domain).generate(limit=limit, include_news=include_news)]
