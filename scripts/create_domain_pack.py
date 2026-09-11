#!/usr/bin/env python3
"""
Create a new meme domain pack under domains/<name>.

Usage:
    python scripts/create_domain_pack.py golf "Golf Culture"
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DOMAINS_DIR = ROOT / "domains"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise ValueError("Domain name must contain at least one letter or number")
    return slug


def write_new(path: Path, content: str) -> None:
    if path.exists():
        raise FileExistsError(f"{path} already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_config(name: str, display_name: str, description: str) -> str:
    return f"""name: {name}
display_name: {display_name}
description: {description}

content_source_name: Web Search
content_source_description: web search results

entity_categories:
  - name: people
    display_name: People
    patterns: {{}}
  - name: places
    display_name: Places
    patterns: {{}}

topic_categories:
  - name: culture
    patterns: ["culture", "community", "scene"]
  - name: events
    patterns: ["event", "show", "festival", "conference", "tournament"]
  - name: people
    patterns: ["artist", "player", "creator", "personality"]
  - name: gear
    patterns: ["gear", "equipment", "setup", "tool"]

tone_indicators:
  - tone: insider
    patterns: ["inside joke", "deep cut", "fans know"]
  - tone: timely
    patterns: ["news", "new", "today", "announced", "upcoming"]

tone_guidelines:
  - Laugh with the community, not at it
  - Be specific enough that real insiders feel seen
  - Avoid generic jokes that could apply to any topic
  - Prefer affectionate roasting, social truth, and recognizable rituals

style_guidelines:
  - Write in normal internet English
  - Keep meme text compact and instantly readable
  - Use concrete details, not vague category labels

humor_focus:
  - Community rituals
  - Status games and tiny identity signals
  - Gear or taste debates
  - Event culture
  - Newcomer vs insider misunderstandings

evaluation_criteria:
  - name: humor
    display_name: Humor
    description: Is it actually funny? Would people share this?
    weight: 0.45
    scoring_guide:
      low: "Not funny, forced, or confusing"
      medium: "Mildly amusing, decent chuckle"
      high: "Actually hilarious, would make insiders laugh"

  - name: cultural_legitimacy
    display_name: Cultural Legitimacy
    description: Would real people in this niche recognize and appreciate it?
    weight: 0.25
    scoring_guide:
      low: "Generic, could be any topic"
      medium: "Somewhat niche-specific"
      high: "Feels native to the community"

  - name: novelty
    display_name: Novelty
    description: Does it find a fresh angle instead of the obvious first joke?
    weight: 0.20
    scoring_guide:
      low: "Obvious or overdone"
      medium: "Decent angle, familiar execution"
      high: "Fresh, specific, or surprising"

  - name: compression
    display_name: Compression
    description: Is the joke concise and instantly readable?
    weight: 0.10
    scoring_guide:
      low: "Too wordy or explains itself"
      medium: "Readable but could be tighter"
      high: "Sharp and fast"

current_events:
  enabled: true
  search_queries:
    - "{display_name}"
    - "{display_name} news"
    - "{display_name} events"
  max_results: 10

topic_radar:
  watchlist_sources:
    publications:
      - name: Example News Source
        url: https://example.com/
        notes: Replace with a niche-specific publication, newsletter, or blog
    festivals: []
    social_lanes:
      - emerging people in the scene
      - event announcements
      - gear or taste debates
      - community etiquette complaints
  priority_entities: []
  event_terms:
    - event announcement
    - lineup
    - meetup
    - release
  rituals:
    - arguing about what counts as authentic
    - buying gear to solve a personality problem
    - turning a casual hang into a competitive display
  seed_topics:
    - topic: {display_name} insiders taking a tiny ritual way too seriously
      lane: evergreen_culture
      source: scaffold seed
      why_now: Reliable evergreen community behavior while better sources are added.
      meme_angle: Escalate the ritual until it feels like an official institution.
      audience: {display_name} insiders
      freshness_score: 5
      relevance_score: 8
      comedy_score: 8

absurdism_detection:
  enabled: true
  low_accuracy_threshold: 4
  high_humor_threshold: 6
"""


def build_entities() -> str:
    return """known_entities:
  people: []
  groups: []
  places: []
  events: []
  terms: []
"""


SYSTEM_PROMPT = """You are a professional comedy writer creating {{ domain.display_name | lower }} memes.
Your job is to make memes that feel native to the community, not generic topic jokes.

TONE:
{% for guideline in domain.tone_guidelines %}
- {{ guideline }}
{% endfor %}

STYLE:
{% for guideline in domain.style_guidelines %}
- {{ guideline }}
{% endfor %}

Use specificity, subverted expectations, and recognizable community rituals.
Do not explain the joke in the meme text.
"""


USER_PROMPT = """Topic: {{ topic }}

CONTEXT FROM {{ domain.content_source_description | upper }}:
{{ context_text }}

AVAILABLE TEMPLATES:
{{ template_catalog }}

{% if trending_section %}
{{ trending_section }}
{% endif %}

Generate {{ num_ideas }} diverse meme concepts. Use different templates.

Focus on:
{% for focus in domain.humor_focus %}
- {{ focus }}
{% endfor %}

OUTPUT FORMAT:

FORMAT: exact template name from list above
TOP_TEXT: the top text
BOTTOM_TEXT: the bottom text
EXPLANATION: why this is funny to {{ domain.display_name | lower }} insiders
SOURCE_QUOTE: quote/fact/context that inspired this, if any
ARTIST_REFERENCE: person/group/event referenced, if any

---

FORMAT: next template name...
"""


EVALUATION_PROMPT = """You are evaluating {{ domain.display_name | lower }} meme concepts.

Score each meme on these criteria:

{% for crit in domain.evaluation_criteria %}
{{ loop.index }}. {{ crit.name | upper }} (1-10): {{ crit.description }}
   - 1-3: {{ crit.scoring_guide.low }}
   - 4-6: {{ crit.scoring_guide.medium }}
   - 7-10: {{ crit.scoring_guide.high }}

{% endfor %}
{% if context_text %}
CONTEXT:
{{ context_text }}
{% endif %}

MEMES TO EVALUATE:
{{ meme_text }}

For each meme, respond with this exact format:
MEME 1: {% for crit in domain.evaluation_criteria %}{{ crit.name | upper }}=X {% endfor %}
NOTES: Brief explanation
"""


BRAINSTORM_PROMPT = """Based on these {{ domain.display_name | lower }} notes, suggest {{ num_topics }} funny meme topics.

{{ context_text }}

Focus on:
{% for focus in domain.humor_focus %}
- {{ focus }}
{% endfor %}

Return just the topics, one per line, no numbering.
"""


CAPTION_PROMPT = """Write a short social media caption for this {{ domain.display_name | lower }} meme.

Meme: {{ top_text }} / {{ bottom_text }}
Why it is funny: {{ explanation }}
Source material: {{ source_quote if source_quote else 'N/A' }}
Reference: {{ artist_reference if artist_reference else 'N/A' }}

Relevant context:
{{ context_text if context_text else 'N/A' }}

Keep it natural, concise, and do not include hashtags.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a new domain pack")
    parser.add_argument("name", help="Domain slug or name, e.g. golf")
    parser.add_argument("display_name", help='Display name, e.g. "Golf Culture"')
    parser.add_argument("--description", default="", help="Short domain description")
    args = parser.parse_args()

    name = slugify(args.name)
    description = args.description or f"{args.display_name} meme culture and community"
    domain_dir = DOMAINS_DIR / name
    prompts_dir = domain_dir / "prompts"

    if domain_dir.exists():
        raise SystemExit(f"Domain pack already exists: {domain_dir}")

    write_new(domain_dir / "config.yaml", build_config(name, args.display_name, description))
    write_new(domain_dir / "entities.yaml", build_entities())
    write_new(prompts_dir / "system_generation.j2", SYSTEM_PROMPT)
    write_new(prompts_dir / "system_generation_free.j2", SYSTEM_PROMPT)
    write_new(prompts_dir / "user_generation.j2", USER_PROMPT)
    write_new(prompts_dir / "user_generation_free.j2", USER_PROMPT)
    write_new(prompts_dir / "evaluation.j2", EVALUATION_PROMPT)
    write_new(prompts_dir / "brainstorm.j2", BRAINSTORM_PROMPT)
    write_new(prompts_dir / "caption.j2", CAPTION_PROMPT)

    print(f"Created domain pack: {domain_dir}")
    print("Next: edit config.yaml, entities.yaml, and prompts for the niche.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
