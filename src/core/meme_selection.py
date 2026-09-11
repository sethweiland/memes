"""Selection helpers for choosing a diverse render set from evaluated memes."""

from __future__ import annotations

from .two_stage import EvaluatedMeme


def select_balanced_indices(
    evaluated: list[EvaluatedMeme],
    limit: int = 6,
    min_originals: int | None = None,
) -> list[int]:
    """
    Return 1-based indices into the already-sorted evaluated list.

    The selector deliberately avoids "top N are all the same kind of joke" by
    reserving slots for original local formats, absurdist/surprising concepts,
    concise high-scorers, and classic templates before filling by score.
    """
    selected: list[int] = []

    def add_first(predicate) -> None:
        if len(selected) >= limit:
            return
        for idx, item in enumerate(evaluated, 1):
            if idx in selected:
                continue
            if predicate(item):
                selected.append(idx)
                return

    def is_original(item: EvaluatedMeme) -> bool:
        return item.idea.format.lower().startswith("original ")

    def is_absurd_or_novel(item: EvaluatedMeme) -> bool:
        notes = (item.evaluation_notes or "").lower()
        return (
            item.is_absurdist
            or item.scores.get("novelty", 0) >= 7
            or "absurd" in notes
            or "surprising" in notes
            or "unexpected" in notes
        )

    def is_concise(item: EvaluatedMeme) -> bool:
        word_count = len((item.idea.top_text + " " + item.idea.bottom_text).split())
        return word_count <= 18 and item.overall_score >= 6.5

    def is_classic(item: EvaluatedMeme) -> bool:
        return not is_original(item) and item.overall_score >= 6.5

    if min_originals is None:
        min_originals = 0 if limit < 4 else max(1, round(limit * 0.35))

    for idx, item in enumerate(evaluated, 1):
        if len([i for i in selected if is_original(evaluated[i - 1])]) >= min_originals:
            break
        if idx not in selected and is_original(item):
            selected.append(idx)

    add_first(is_absurd_or_novel)
    add_first(is_concise)
    add_first(is_classic)

    used_formats = {
        evaluated[idx - 1].idea.format.lower()
        for idx in selected
        if 0 < idx <= len(evaluated)
    }

    for idx, item in enumerate(evaluated, 1):
        if len(selected) >= limit:
            break
        fmt = item.idea.format.lower()
        if idx in selected:
            continue
        if fmt in used_formats and len(evaluated) > limit:
            continue
        selected.append(idx)
        used_formats.add(fmt)

    return selected[:limit]
