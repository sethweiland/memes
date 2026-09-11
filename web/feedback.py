"""
Feedback persistence and prompt injection for human-in-the-loop learning.
"""

import json
import re
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path

FEEDBACK_PATH = Path("data/feedback.json")


def load_feedback() -> list[dict]:
    """Read full feedback history from disk."""
    if not FEEDBACK_PATH.exists():
        return []
    with open(FEEDBACK_PATH, "r") as f:
        return json.load(f)


def save_feedback(session: dict):
    """Append a feedback session entry to the JSON file."""
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    history = load_feedback()
    history.append(session)
    with open(FEEDBACK_PATH, "w") as f:
        json.dump(history, f, indent=2)


def _extract_proper_nouns(text: str) -> list[str]:
    """Extract likely proper nouns / named references from meme text."""
    # Match capitalized words that aren't common sentence starters
    common_words = {
        "The", "This", "That", "When", "What", "Where", "Who", "How",
        "Why", "You", "Your", "I", "My", "Me", "We", "Our", "It",
        "No", "Not", "But", "And", "Or", "If", "So", "Just", "All",
        "Every", "Don't", "Can't", "Won't", "Top", "Bottom", "FORMAT",
    }
    words = re.findall(r"\b[A-Z][a-z]{2,}\b", text)
    return [w for w in words if w not in common_words]


def build_feedback_context(limit: int = 5) -> str:
    """Aggregate recent feedback into soft prompt context.

    Returns a string block to append to the generation prompt, or "" if
    there is no meaningful feedback yet.
    """
    history = load_feedback()
    if not history:
        return ""

    # Collect per-format stats from all sessions
    format_ratings: dict[str, list[float]] = defaultdict(list)
    praised_quotes: list[str] = []
    criticism_quotes: list[str] = []

    # Topic tracking
    low_rated_topics: Counter = Counter()
    high_rated_topics: Counter = Counter()
    topic_notes_list: list[str] = []

    for session in history:
        # Collect explicit topic notes from user
        for meme in session.get("memes", []):
            tn = (meme.get("topic_notes") or "").strip()
            if tn:
                topic_notes_list.append(tn)

        for meme in session.get("memes", []):
            rating = meme.get("user_rating")
            if rating is None:
                continue
            fmt = meme.get("format", "Unknown")
            format_ratings[fmt].append(float(rating))

            feedback_text = (meme.get("user_feedback") or "").strip()
            if feedback_text:
                if rating >= 4:
                    praised_quotes.append(feedback_text)
                elif rating <= 2:
                    criticism_quotes.append(feedback_text)

            # Extract topic references from meme text
            combined_text = " ".join([
                meme.get("top_text", ""),
                meme.get("bottom_text", ""),
            ])
            nouns = _extract_proper_nouns(combined_text)
            if rating <= 2:
                low_rated_topics.update(nouns)
            elif rating >= 4:
                high_rated_topics.update(nouns)

    if not format_ratings and not topic_notes_list:
        return ""

    # Compute averages
    format_avgs = {
        fmt: sum(scores) / len(scores) for fmt, scores in format_ratings.items()
    }

    loved = sorted(
        [(fmt, avg) for fmt, avg in format_avgs.items() if avg >= 4.0],
        key=lambda x: -x[1],
    )
    disliked = sorted(
        [(fmt, avg) for fmt, avg in format_avgs.items() if avg <= 2.5],
        key=lambda x: x[1],
    )

    lines = ["PAST USER FEEDBACK (use to guide humor style):"]

    if loved:
        names = ", ".join(f"{fmt} (avg {avg:.1f} stars)" for fmt, avg in loved[:5])
        lines.append(f"- User loves: {names}")

    if disliked:
        names = ", ".join(f"{fmt} (avg {avg:.1f} stars)" for fmt, avg in disliked[:5])
        lines.append(f"- User dislikes: {names}")

    # Topic-level feedback: topics appearing in 2+ low-rated memes
    overused = [topic for topic, count in low_rated_topics.most_common(10) if count >= 2]
    enjoyed = [topic for topic, count in high_rated_topics.most_common(10) if count >= 2]

    if overused:
        lines.append(f"- Overused topics (vary these): {', '.join(overused[:8])}")
    if enjoyed:
        lines.append(f"- Topics user enjoyed: {', '.join(enjoyed[:8])}")

    # Explicit topic notes from user
    for note in topic_notes_list[-limit:]:
        lines.append(f'- User topic note: "{note}"')

    # Recent praise (most recent first, up to limit)
    for quote in praised_quotes[-limit:]:
        lines.append(f'- Recent praise: "{quote}"')

    for quote in criticism_quotes[-limit:]:
        lines.append(f'- Recent criticism: "{quote}"')

    ai_context = ""
    try:
        from src.core.ai_improvement_loop import build_ai_feedback_context
        ai_context = build_ai_feedback_context(limit=3)
    except Exception:
        ai_context = ""

    if ai_context:
        lines.append("")
        lines.append(ai_context)

    return "\n".join(lines)
