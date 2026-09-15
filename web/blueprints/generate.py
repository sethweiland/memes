"""
Generate blueprint — two-stage meme generation workflow.
Supports domain-specific RAG, web search fallback, or pure LLM generation.
"""

import json
from datetime import datetime
from pathlib import Path

from flask import Blueprint, render_template, request, jsonify, redirect, url_for

from web import jobs
from web.feedback import save_feedback, load_feedback, build_feedback_context

bp = Blueprint("generate", __name__)


# Context mode constants
CONTEXT_MODE_AUTO = "auto"
CONTEXT_MODE_RAG = "rag"
CONTEXT_MODE_WEB = "web"
CONTEXT_MODE_NONE = "none"


def _coerce_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Stage 1 worker
# ---------------------------------------------------------------------------

def _run_stage1(
    job,
    topic,
    num_concepts,
    creativity,
    domain=None,
    context_mode="auto",
    model="gpt-5.4-mini",
    humor_edge=7,
    ai_refine=False,
    critic_model="gpt-5.5",
):
    """
    Background worker: generate freely + evaluate.

    Args:
        job: Background job instance
        topic: Meme topic
        num_concepts: Number of concepts to generate
        creativity: Generation creativity (0.3-1.5)
        domain: Domain name or None for generic
        context_mode: "rag", "web", or "none"
        model: Grok model to use for generation
    """
    from src.config import load_domain
    from src.core.pipeline import MemePipeline, PipelineConfig
    from src.core.two_stage import TwoStagePipeline, GenericTwoStagePipeline, _format_context_text
    from src.core.fallback_context import FallbackContextProvider
    from src.core.generic_config import get_generic_config
    from src.core.creative_brief import build_creative_brief

    job.progress = "Loading models..."

    pipe_config = PipelineConfig(
        num_concepts=num_concepts,
        generation_creativity=creativity,
        creativity=creativity,
        humor_edge=humor_edge,
    )

    # Determine which pipeline to use based on context_mode
    if domain and context_mode == CONTEXT_MODE_RAG:
        # Domain-specific RAG pipeline
        job.progress = f"Loading {domain} domain config..."
        config = load_domain(domain)
        pipeline = MemePipeline(config, pipe_config)

        job.progress = "Fetching current events..."
        pipeline._fetch_current_events()

        two_stage = TwoStagePipeline(pipeline)
        eval_criteria = config.evaluation_criteria

        feedback_ctx = build_feedback_context()
        template_catalog = pipeline.catalog.get_prompt_catalog(limit=50, randomize=True)

        # Split current events for rotation
        ce_items = [
            item.strip() for item in (pipeline.current_events_context or "").split("\n")
            if item.strip()
        ]

        # Generate in batches with per-batch context rotation
        all_memes = []
        used_chunk_ids: set[str] = set()
        previously_covered: list[str] = []
        previously_used_templates: list[str] = []
        creative_brief_text = ""
        batches_needed = (num_concepts + pipe_config.concepts_per_batch - 1) // pipe_config.concepts_per_batch

        for batch_num in range(batches_needed):
            remaining = num_concepts - len(all_memes)
            batch_size = min(pipe_config.concepts_per_batch, remaining)
            if batch_size <= 0:
                break

            job.progress = f"Retrieving context for batch {batch_num + 1}/{batches_needed}..."

            context = pipeline.rag.get_context(
                topic,
                k=pipe_config.num_context_chunks,
                expand_query=pipe_config.expand_queries,
                exclude_ids=used_chunk_ids if used_chunk_ids else None,
            )
            used_chunk_ids.update(c['id'] for c in context)

            batch_ce = ""
            if ce_items:
                items_per_batch = max(1, min(2, len(ce_items)))
                start = (batch_num * items_per_batch) % len(ce_items)
                batch_ce_items = []
                for i in range(items_per_batch):
                    batch_ce_items.append(ce_items[(start + i) % len(ce_items)])
                batch_ce = "\n".join(batch_ce_items)

            context_text = _format_context_text(context, batch_ce)
            if feedback_ctx:
                context_text += "\n\n" + feedback_ctx

            if not creative_brief_text:
                job.progress = "Finding memeable tensions..."
                creative_brief_text = build_creative_brief(
                    pipeline.rag.grok,
                    topic=topic,
                    context_text=context_text,
                ).to_prompt_section()

            job.progress = f"Generating batch {batch_num + 1}/{batches_needed}..."

            memes = two_stage.generate_freely(
                topic=topic,
                context_text=context_text,
                template_catalog=template_catalog,
                num_ideas=batch_size,
                previously_covered=previously_covered if previously_covered else None,
                previously_used_templates=previously_used_templates if previously_used_templates else None,
                creative_brief=creative_brief_text,
            )
            all_memes.extend(memes)

            for m in memes:
                # Track used templates to avoid duplicates
                if m.format:
                    previously_used_templates.append(m.format)
                # Track topics for content diversity
                refs = []
                if m.format:
                    refs.append(m.format)
                for text in [m.top_text or "", m.bottom_text or ""]:
                    words = [w for w in text.split() if w[0:1].isupper() and len(w) > 2]
                    refs.extend(words[:3])
                previously_covered.extend(refs)

            job.progress = f"Generated {len(all_memes)}/{num_concepts} concepts..."

        context_text_final = context_text

    else:
        # Generic pipeline: web search or no context
        job.progress = "Setting up generic pipeline..."
        config = get_generic_config()
        eval_criteria = config.evaluation_criteria

        # Get context based on mode
        if context_mode == CONTEXT_MODE_WEB:
            job.progress = "Searching the web for context..."
            fallback = FallbackContextProvider()
            context_text = fallback.get_web_context(topic, max_results=5)
        else:
            # CONTEXT_MODE_NONE
            context_text = ""

        # Use generic two-stage pipeline
        two_stage = GenericTwoStagePipeline(config, pipe_config, model=model)
        pipeline = two_stage  # For stage 2
        classic_template_catalog = two_stage.catalog.get_classic_prompt_catalog(limit=50, randomize=True)
        original_template_catalog = two_stage.catalog.get_original_prompt_catalog()

        feedback_ctx = build_feedback_context()
        if feedback_ctx:
            context_text += "\n\n" + feedback_ctx

        all_memes = []
        previously_covered: list[str] = []
        previously_used_templates: list[str] = []
        job.progress = "Finding memeable tensions..."
        creative_brief_text = build_creative_brief(
            two_stage.grok,
            topic=topic,
            context_text=context_text,
        ).to_prompt_section()

        original_target = max(2, round(num_concepts * 0.4)) if num_concepts >= 8 else max(1, num_concepts // 3)
        classic_target = max(0, num_concepts - original_target)
        lanes = [
            ("classic", classic_target, classic_template_catalog),
            ("original", original_target, original_template_catalog),
        ]

        for lane_name, lane_target, lane_catalog in lanes:
            generated_in_lane = 0
            batches_needed = (lane_target + pipe_config.concepts_per_batch - 1) // pipe_config.concepts_per_batch
            for batch_num in range(batches_needed):
                remaining = lane_target - generated_in_lane
                batch_size = min(pipe_config.concepts_per_batch, remaining)
                if batch_size <= 0:
                    break

                job.progress = f"Generating {lane_name} batch {batch_num + 1}/{batches_needed}..."

                memes = two_stage.generate_freely(
                    topic=topic,
                    context_text=context_text,
                    template_catalog=lane_catalog,
                    num_ideas=batch_size,
                    previously_covered=previously_covered if previously_covered else None,
                    previously_used_templates=previously_used_templates if previously_used_templates else None,
                    creative_brief=creative_brief_text,
                    format_lane=lane_name,
                )
                all_memes.extend(memes)
                generated_in_lane += len(memes)

                for m in memes:
                    if m.format:
                        previously_used_templates.append(m.format)
                    refs = []
                    if m.format:
                        refs.append(m.format)
                    for text in [m.top_text or "", m.bottom_text or ""]:
                        words = [w for w in text.split() if w[0:1].isupper() and len(w) > 2]
                        refs.extend(words[:3])
                    previously_covered.extend(refs)

                job.progress = f"Generated {len(all_memes)}/{num_concepts} concepts..."

        context_text_final = context_text

    job.progress = f"Evaluating {len(all_memes)} concepts..."
    evaluated = two_stage.evaluate_for_review(all_memes, context_text_final)
    job.progress = f"Evaluation complete — {len(evaluated)} memes scored"

    ai_critique = None
    ai_critique_error = ""
    if ai_refine and evaluated:
        try:
            from src.core.ai_improvement_loop import AIImprovementLoop, save_ai_feedback

            job.progress = "Running tiny AI critic loop..."
            critic = AIImprovementLoop(model=critic_model)
            ai_critique = critic.critique(
                topic=topic,
                evaluated=evaluated,
                context_text=context_text_final,
                limit=3,
            )
            if ai_critique:
                save_ai_feedback(ai_critique)
                improvement_brief = ai_critique.to_prompt_section()
                job.progress = "Generating critic-informed rewrites..."
                rewrite_count = min(3, max(1, num_concepts // 6))
                if domain and context_mode == CONTEXT_MODE_RAG:
                    rewrite_catalog = template_catalog
                    improved = two_stage.generate_freely(
                        topic=topic,
                        context_text=context_text_final,
                        template_catalog=rewrite_catalog,
                        num_ideas=rewrite_count,
                        previously_covered=previously_covered if previously_covered else None,
                        previously_used_templates=previously_used_templates if previously_used_templates else None,
                        creative_brief=(creative_brief_text + "\n\n" + improvement_brief).strip(),
                    )
                else:
                    improved = two_stage.generate_freely(
                        topic=topic,
                        context_text=context_text_final,
                        template_catalog=original_template_catalog + "\n\n" + classic_template_catalog,
                        num_ideas=rewrite_count,
                        previously_covered=previously_covered if previously_covered else None,
                        previously_used_templates=previously_used_templates if previously_used_templates else None,
                        creative_brief=(creative_brief_text + "\n\n" + improvement_brief).strip(),
                        format_lane="mixed",
                    )
                if improved:
                    job.progress = f"Evaluating {len(improved)} critic rewrites..."
                    improved_evaluated = two_stage.evaluate_for_review(improved, context_text_final)
                    for item in improved_evaluated:
                        item.generation_source = "critic_rewrite"
                    evaluated.extend(improved_evaluated)
                    evaluated.sort(key=lambda e: e.overall_score, reverse=True)
        except Exception as e:
            ai_critique_error = str(e)

    try:
        from src.core.grounding import ground_evaluated

        grok_client = getattr(getattr(two_stage, "rag", None), "grok", None) or getattr(two_stage, "grok", None)
        if grok_client and evaluated:
            job.progress = "Grounding specific claims..."
            evaluated = ground_evaluated(grok_client, topic, evaluated)
    except Exception:
        pass

    # Store pipeline + evaluated memes for Stage 2
    job.result = {
        "evaluated": evaluated,
        "pipeline": pipeline,
        "topic": topic,
        "context_mode": context_mode,
        "domain": domain,
        "creative_brief": creative_brief_text,
        "ai_critique": ai_critique.to_dict() if ai_critique else None,
        "ai_critique_error": ai_critique_error,
        "domain_criteria": [
            {
                "name": c.name,
                "display_name": c.display_name,
                "weight": c.weight,
            }
            for c in eval_criteria
        ],
    }


# ---------------------------------------------------------------------------
# Stage 2 worker
# ---------------------------------------------------------------------------

def _run_stage2(job, pipeline, evaluated, selected_indices):
    """Background worker: generate images + captions for selected memes."""
    from src.core.two_stage import TwoStagePipeline, GenericTwoStagePipeline
    from src.core.output import save_meme_metadata
    from src.core.pipeline import MemePipeline

    # Determine if we have a domain pipeline or generic pipeline
    if isinstance(pipeline, MemePipeline):
        two_stage = TwoStagePipeline(pipeline)
    else:
        # pipeline is already a GenericTwoStagePipeline
        two_stage = pipeline

    job.progress = f"Generating images for {len(selected_indices)} memes..."
    images = two_stage.generate_selected(evaluated, selected_indices)

    job.progress = "Generating captions..."
    if isinstance(pipeline, MemePipeline):
        images = pipeline.generate_captions(images)
    else:
        images = two_stage.generate_captions(images)

    job.progress = "Saving metadata..."
    save_meme_metadata(images)

    job.result = {
        "images": [
            {
                "filename": img.local_path.split("/")[-1] if img.local_path else None,
                "local_path": img.local_path,
                "template": img.template.name,
                "top_text": img.idea.top_text,
                "bottom_text": img.idea.bottom_text,
                "caption": img.caption or "",
                "image_url": img.image_url,
            }
            for img in images
        ]
    }
    job.progress = f"Done — {len(images)} memes generated"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route("/")
def start():
    return render_template("generate/start.html")


@bp.route("/api/domains")
def api_domains():
    from src.config import list_domain_summaries

    return jsonify({"domains": list_domain_summaries()})


@bp.route("/api/topic-radar")
def api_topic_radar():
    import json
    from pathlib import Path

    from src.config import list_domains, load_domain
    from src.core.topic_radar import build_topic_radar

    domain = (request.args.get("domain") or "bluegrass").strip()
    limit = max(1, min(_coerce_int(request.args.get("limit"), 18), 50))
    include_news = request.args.get("news", "1") not in ("0", "false", "False")

    if domain not in list_domains():
        return jsonify({"error": f"Unknown domain pack: {domain}"}), 404

    config = load_domain(domain)
    try:
        topics = build_topic_radar(config, limit=limit, include_news=include_news)
        source = "live"
    except Exception:
        cache_path = Path("data/topic_radar") / f"{domain}.json"
        if not cache_path.exists():
            raise
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        topics = cached.get("topics", [])[:limit]
        source = "cache"

    return jsonify({
        "domain": domain,
        "display_name": config.display_name,
        "source": source,
        "topics": topics,
    })


@bp.route("/api/start", methods=["POST"])
def api_start():
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", "").strip()
    if not topic:
        return jsonify({"error": "Topic is required"}), 400

    num_concepts = _coerce_int(data.get("num_concepts"), 20)
    creativity = _coerce_float(data.get("creativity"), 1.0)
    humor_edge = _coerce_int(data.get("humor_edge"), 7)
    context_mode = data.get("context_mode", CONTEXT_MODE_AUTO)
    requested_domain = (data.get("domain") or "").strip()
    model = data.get("model", "gpt-5.4-mini")
    ai_refine = bool(data.get("ai_refine", False))
    critic_model = data.get("critic_model", "gpt-5.5")

    # Clamp values
    num_concepts = max(5, min(100, num_concepts))
    creativity = max(0.3, min(1.5, creativity))
    humor_edge = max(1, min(10, humor_edge))

    # Validate model
    valid_models = {"gpt-5.4-mini", "gpt-5.5", "gpt-5.4", "grok-4.6", "grok-4-0709", "grok-4-1-fast-reasoning", "grok-3-mini"}
    if model not in valid_models:
        model = "gpt-5.4-mini"
    if critic_model not in valid_models:
        critic_model = "gpt-5.5"

    # Validate context_mode
    if context_mode not in (CONTEXT_MODE_AUTO, CONTEXT_MODE_RAG, CONTEXT_MODE_WEB, CONTEXT_MODE_NONE):
        context_mode = CONTEXT_MODE_AUTO

    # Explicit domain selection wins. This is the extensibility path for
    # domain packs: bluegrass today, other niches later.
    domain = None
    if requested_domain:
        from src.config import list_domains

        if requested_domain in list_domains():
            domain = requested_domain
            context_mode = CONTEXT_MODE_RAG
        elif context_mode == CONTEXT_MODE_RAG:
            context_mode = CONTEXT_MODE_WEB

    # Auto-detect domain if context_mode is "auto"
    if not domain and context_mode == CONTEXT_MODE_AUTO:
        from src.core.domain_classifier import DomainClassifier
        from src.core.grok import GrokClient

        try:
            classifier = DomainClassifier()
            result = classifier.classify(topic)
            classifier.close()

            if result.domain and result.confidence >= 0.6:
                domain = result.domain
                context_mode = CONTEXT_MODE_RAG
            else:
                context_mode = CONTEXT_MODE_WEB
        except Exception as e:
            # Fall back to web search on classification error
            print(f"Domain classification failed: {e}")
            context_mode = CONTEXT_MODE_WEB

    elif context_mode == CONTEXT_MODE_RAG:
        # User explicitly requested RAG - need to detect domain
        from src.core.domain_classifier import DomainClassifier

        try:
            classifier = DomainClassifier()
            result = classifier.classify(topic)
            classifier.close()

            if result.domain:
                domain = result.domain
            else:
                # No domain matched - fall back to web
                context_mode = CONTEXT_MODE_WEB
        except Exception:
            context_mode = CONTEXT_MODE_WEB

    job_id = jobs.submit(
        _run_stage1,
        topic,
        num_concepts,
        creativity,
        domain,
        context_mode,
        model,
        humor_edge,
        ai_refine,
        critic_model,
    )
    return jsonify({
        "job_id": job_id,
        "detected_domain": domain,
        "context_mode": context_mode,
    })


@bp.route("/api/status/<job_id>")
def api_status(job_id):
    job = jobs.get(job_id)
    if job is None:
        return jsonify({"error": "Job not found"}), 404

    resp = {
        "state": job.state,
        "progress": job.progress,
    }

    if job.state == "failed":
        resp["error"] = job.error

    if job.state == "done" and job.result:
        # For stage 1 results, serialize evaluated memes
        if "evaluated" in job.result:
            from src.core.meme_selection import select_balanced_indices

            resp["evaluated"] = [
                {
                    "index": i + 1,
                    "format": e.idea.format,
                    "top_text": e.idea.top_text,
                    "bottom_text": e.idea.bottom_text,
                    "overall_score": round(e.overall_score, 1),
                    "scores": e.scores,
                    "evaluation_notes": e.evaluation_notes,
                    "rationale": (getattr(e.idea, "rationale", "") or e.idea.explanation or "").strip(),
                    "grounding": getattr(e, "grounding", None),
                    "is_absurdist": e.is_absurdist,
                    "template_category": getattr(e, "template_category", ""),
                    "generation_source": getattr(e, "generation_source", ""),
                }
                for i, e in enumerate(job.result["evaluated"])
            ]
            resp["topic"] = job.result.get("topic", "")
            resp["domain_criteria"] = job.result.get("domain_criteria", [])
            resp["creative_brief"] = job.result.get("creative_brief", "")
            resp["ai_critique"] = job.result.get("ai_critique")
            resp["ai_critique_error"] = job.result.get("ai_critique_error", "")
            resp["recommended_indices"] = select_balanced_indices(
                job.result["evaluated"],
                limit=min(6, len(job.result["evaluated"])),
            )

        # For stage 2 results, serialize images
        if "images" in job.result:
            resp["images"] = job.result["images"]

    return jsonify(resp)


@bp.route("/review/<job_id>")
def review(job_id):
    job = jobs.get(job_id)
    if job is None:
        return render_template("generate/review.html", job_id=job_id, expired=True)
    return render_template("generate/review.html", job_id=job_id, expired=False)


@bp.route("/api/finalize", methods=["POST"])
def api_finalize():
    data = request.get_json(silent=True) or {}
    source_job_id = data.get("job_id", "")
    selected_indices = data.get("selected_indices", [])

    if not source_job_id or not selected_indices:
        return jsonify({"error": "job_id and selected_indices are required"}), 400

    source_job = jobs.get(source_job_id)
    if source_job is None or source_job.state != "done":
        return jsonify({"error": "Source job not found or not complete"}), 404

    if "pipeline" not in source_job.result:
        return jsonify({"error": "Session expired — pipeline not available"}), 410

    pipeline = source_job.result["pipeline"]
    evaluated = source_job.result["evaluated"]

    # Validate indices
    selected_indices = [
        idx for idx in (_coerce_int(i, 0) for i in selected_indices)
        if 0 < idx <= len(evaluated)
    ]
    if not selected_indices:
        return jsonify({"error": "No valid indices selected"}), 400

    job_id = jobs.submit(_run_stage2, pipeline, evaluated, selected_indices)
    return jsonify({"job_id": job_id})


@bp.route("/results/<job_id>")
def results(job_id):
    job = jobs.get(job_id)
    if job is None:
        return render_template("generate/results.html", job_id=job_id, expired=True)
    return render_template("generate/results.html", job_id=job_id, expired=False)


@bp.route("/api/feedback", methods=["POST"])
def api_feedback():
    """Persist user ratings and feedback for a generation session."""
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "")
    topic = data.get("topic", "")
    stage = data.get("stage", "")
    memes_data = data.get("memes", [])

    if not session_id or stage not in ("review", "results"):
        return jsonify({"error": "session_id and valid stage required"}), 400

    # Build feedback entry from client-supplied ratings merged with meme data
    from datetime import datetime

    entry = {
        "session_id": session_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "topic": topic,
        "stage": stage,
        "memes": memes_data,
    }
    try:
        save_feedback(entry)
    except Exception as e:
        return jsonify({"error": f"Failed to save feedback: {e}"}), 500
    return jsonify({"ok": True})


@bp.route("/feedback")
def feedback_page():
    """Render feedback history page."""
    history = load_feedback()
    # Compute summary stats per session
    sessions = []
    for entry in reversed(history):
        rated = [m for m in entry.get("memes", []) if m.get("user_rating") is not None]
        avg = (
            round(sum(m["user_rating"] for m in rated) / len(rated), 1)
            if rated
            else None
        )
        sessions.append({
            "session_id": entry.get("session_id", ""),
            "timestamp": entry.get("timestamp", ""),
            "topic": entry.get("topic", ""),
            "stage": entry.get("stage", ""),
            "num_rated": len(rated),
            "avg_rating": avg,
            "memes": entry.get("memes", []),
        })
    return render_template("generate/feedback.html", sessions=sessions)


@bp.route("/api/surprise", methods=["POST"])
def api_surprise():
    """Generate a random topic via brainstorming."""
    try:
        from src.config import list_domains, load_domain
        from src.core.topic_radar import TopicRadar

        data = request.get_json(silent=True) or {}
        requested_domain = (data.get("domain") or "").strip()

        domains = list_domains()
        domain_name = requested_domain if requested_domain in domains else (domains[0] if domains else "")

        if domain_name:
            config = load_domain(domain_name)
            candidates = TopicRadar(config).generate(limit=12, include_news=False)
            if candidates:
                import random
                weights = [max(1, int(c.overall_score * 10)) for c in candidates]
                picked = random.choices(candidates, weights=weights, k=1)[0]
                return jsonify({
                    "topic": picked.topic,
                    "domain": domain_name,
                    "lane": picked.lane,
                    "meme_angle": picked.meme_angle,
                })

        return jsonify({"topic": "a niche community taking a tiny ritual way too seriously"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Instagram Publishing
# ---------------------------------------------------------------------------

PUBLISH_LOG_PATH = Path("data/instagram_publish_log.json")


def _load_publish_log() -> list[dict]:
    """Load Instagram publish history."""
    if not PUBLISH_LOG_PATH.exists():
        return []
    try:
        return json.loads(PUBLISH_LOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_publish_log(entry: dict):
    """Append a publish entry to the log."""
    log = _load_publish_log()
    log.append(entry)
    PUBLISH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PUBLISH_LOG_PATH.write_text(
        json.dumps(log, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


@bp.route("/api/instagram/publish", methods=["POST"])
def api_instagram_publish():
    """
    Publish an approved meme to Instagram.
    
    Expects JSON:
    {
        "public_image_url": "https://...",  # Publicly accessible image URL
        "caption": "Your caption here",
        "filename": "optional-for-logging.jpg"
    }
    
    Returns:
    {
        "success": true,
        "post_id": "...",
        "permalink": "https://instagram.com/p/...",
        "error": null
    }
    """
    data = request.get_json(silent=True) or {}
    
    public_image_url = data.get("public_image_url", "").strip()
    caption = data.get("caption", "").strip()
    filename = data.get("filename", "")
    
    if not public_image_url:
        return jsonify({
            "success": False,
            "error": "public_image_url is required (must be a publicly accessible JPEG URL)"
        }), 400
    
    if not caption:
        return jsonify({
            "success": False,
            "error": "caption is required"
        }), 400
    
    # Validate that credentials are available
    try:
        from src.core.instagram_publisher import publish_to_instagram
        
        result = publish_to_instagram(
            image_url=public_image_url,
            caption=caption,
        )
        
        # Log the publish attempt
        log_entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "filename": filename,
            "caption": caption[:100] + ("..." if len(caption) > 100 else ""),
            "success": result.success,
            "post_id": result.post_id,
            "permalink": result.permalink,
            "error": result.error,
            "container_id": result.container_id,
        }
        _save_publish_log(log_entry)
        
        if result.success:
            return jsonify({
                "success": True,
                "post_id": result.post_id,
                "permalink": result.permalink,
                "error": None,
            })
        else:
            return jsonify({
                "success": False,
                "post_id": None,
                "permalink": None,
                "error": result.error,
            }), 500
            
    except ValueError as e:
        # Missing credentials
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
    except Exception as e:
        # Unexpected error
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": f"Unexpected error: {str(e)}"
        }), 500


@bp.route("/api/instagram/history")
def api_instagram_history():
    """Get Instagram publish history."""
    log = _load_publish_log()
    return jsonify({
        "history": log,
        "count": len(log),
    })
