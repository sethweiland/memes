"""
Daily candidate queue document helpers.

Keeps rationale / scores / grounding on the JSON the dashboard reads,
including old queues that predate these fields.
"""

from __future__ import annotations

from .grounding import idea_rationale
from .two_stage import EvaluatedMeme


def parse_topic_response(text: str) -> tuple[str, str]:
    """Parse TOPIC: / RATIONALE: from a topic-suggestion response."""
    topic = ""
    rationale = ""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("TOPIC:"):
            topic = line.split(":", 1)[1].strip()
        elif upper.startswith("RATIONALE:"):
            rationale = line.split(":", 1)[1].strip()
    if not topic:
        # Model returned a bare topic string
        topic = (text or "").strip().split("\n")[0].strip().strip('"')
    return topic, rationale


def select_daily_candidates(
    evaluated: list[EvaluatedMeme],
    count: int,
) -> list[EvaluatedMeme]:
    """
    Prefer grounded, higher-scoring memes. Skip invented specific claims
    unless that would empty the batch (human still needs something to review).
    """
    if not evaluated:
        return []
    keep = [item for item in evaluated if getattr(item, "grounding_action", "ok") != "skip"]
    if not keep:
        keep = list(evaluated)
    keep.sort(key=lambda item: item.overall_score, reverse=True)
    return keep[: max(0, count)]


def _scores_dict(scores) -> dict:
    if not isinstance(scores, dict):
        return {}
    out = {}
    for key, value in scores.items():
        if value is None:
            continue
        try:
            out[str(key)] = int(value) if float(value) == int(value) else float(value)
        except (TypeError, ValueError):
            continue
    return out


def grounding_payload(grounding) -> dict | None:
    if not isinstance(grounding, dict):
        return None
    claim = str(grounding.get("claim") or "").strip()
    support = str(grounding.get("support") or "").strip()
    confidence = str(grounding.get("confidence") or "").strip()
    if not (claim or support or confidence):
        return None
    return {
        "claim": claim,
        "support": support,
        "confidence": confidence,
    }


def build_candidate_record(
    *,
    date_str: str,
    index: int,
    template: str,
    top_text: str,
    bottom_text: str,
    caption: str,
    public_url: str | None,
    s3_key: str | None,
    local_path: str,
    filename: str,
    created_at: str,
    scores=None,
    overall_score=None,
    rationale: str = "",
    evaluation_notes: str = "",
    grounding=None,
    status: str = "pending",
) -> dict:
    """One candidate object as stored in the daily queue JSON."""
    record = {
        "id": f"{date_str}_{index}",
        "index": index,
        "template": template,
        "top_text": top_text or "",
        "bottom_text": bottom_text or "",
        "caption": caption or "",
        "public_url": public_url,
        "s3_key": s3_key,
        "local_path": str(local_path or ""),
        "filename": filename or "",
        "status": status,
        "created_at": created_at,
        "scores": _scores_dict(scores),
        "overall_score": overall_score,
        "rationale": (rationale or "").strip(),
        "evaluation_notes": (evaluation_notes or "").strip(),
    }
    payload = grounding_payload(grounding)
    if payload:
        record["grounding"] = payload
    return record


def candidate_from_evaluated(
    *,
    date_str: str,
    index: int,
    img: dict,
    evaluated: EvaluatedMeme | None,
    public_url: str | None,
    s3_key: str | None,
    local_path: str,
    filename: str,
    created_at: str,
    caption: str = "",
) -> dict:
    rationale = ""
    notes = ""
    scores = img.get("scores") or {}
    overall = img.get("overall_score")
    grounding = img.get("grounding")
    if evaluated is not None:
        rationale = idea_rationale(evaluated.idea)
        notes = evaluated.evaluation_notes or ""
        scores = evaluated.scores or scores
        overall = evaluated.overall_score if evaluated.overall_score is not None else overall
        grounding = evaluated.grounding if evaluated.grounding is not None else grounding
    else:
        rationale = (img.get("rationale") or "").strip()
        notes = (img.get("evaluation_notes") or "").strip()
    if overall is not None:
        try:
            overall = round(float(overall), 1)
        except (TypeError, ValueError):
            overall = None
    return build_candidate_record(
        date_str=date_str,
        index=index,
        template=img.get("template") or img.get("format") or img.get("name", "Unknown"),
        top_text=img.get("top_text", ""),
        bottom_text=img.get("bottom_text", ""),
        caption=caption or img.get("caption", ""),
        public_url=public_url,
        s3_key=s3_key,
        local_path=local_path,
        filename=filename,
        created_at=created_at,
        scores=scores,
        overall_score=overall,
        rationale=rationale,
        evaluation_notes=notes,
        grounding=grounding,
    )


def build_queue_document(
    *,
    date_str: str,
    topic: str,
    topic_rationale: str,
    domain: str,
    generated_at: str,
    output_dir: str,
    candidates: list[dict],
) -> dict:
    return {
        "date": date_str,
        "topic": topic,
        "topic_rationale": (topic_rationale or "").strip(),
        "domain": domain,
        "generated_at": generated_at,
        "output_dir": str(output_dir or ""),
        "total_count": len(candidates),
        "candidates": candidates,
    }


def candidate_has_why(candidate: dict, topic_rationale: str = "") -> bool:
    """True when the dashboard should render a Why block."""
    if (topic_rationale or "").strip():
        return True
    if (candidate.get("rationale") or "").strip():
        return True
    if (candidate.get("evaluation_notes") or "").strip():
        return True
    scores = candidate.get("scores")
    if isinstance(scores, dict) and scores:
        return True
    if candidate.get("overall_score") is not None:
        return True
    if grounding_payload(candidate.get("grounding")):
        return True
    return False


def why_preview(candidate: dict, topic_rationale: str = "") -> str:
    for value in (
        candidate.get("rationale"),
        candidate.get("evaluation_notes"),
        topic_rationale,
    ):
        text = (value or "").strip()
        if text:
            return text
    grounding = grounding_payload(candidate.get("grounding")) or {}
    if grounding.get("claim"):
        return grounding["claim"]
    return "Why"
