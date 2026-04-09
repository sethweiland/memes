"""
Generate blueprint — two-stage meme generation workflow.
Supports domain-specific RAG, web search fallback, or pure LLM generation.
"""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for

from web import jobs
from web.feedback import save_feedback, load_feedback, build_feedback_context

bp = Blueprint("generate", __name__)


# Context mode constants
CONTEXT_MODE_AUTO = "auto"
CONTEXT_MODE_RAG = "rag"
CONTEXT_MODE_WEB = "web"
CONTEXT_MODE_NONE = "none"


# ---------------------------------------------------------------------------
# Stage 1 worker
# ---------------------------------------------------------------------------

def _run_stage1(job, topic, num_concepts, creativity, domain=None, context_mode="auto", model="grok-4-0709"):
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

    job.progress = "Loading models..."

    pipe_config = PipelineConfig(
        num_concepts=num_concepts,
        generation_creativity=creativity,
        creativity=creativity,
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

            job.progress = f"Generating batch {batch_num + 1}/{batches_needed}..."

            memes = two_stage.generate_freely(
                topic=topic,
                context_text=context_text,
                template_catalog=template_catalog,
                num_ideas=batch_size,
                previously_covered=previously_covered if previously_covered else None,
                previously_used_templates=previously_used_templates if previously_used_templates else None,
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
        template_catalog = two_stage.catalog.get_prompt_catalog(limit=50, randomize=True)

        feedback_ctx = build_feedback_context()
        if feedback_ctx:
            context_text += "\n\n" + feedback_ctx

        # Generate in batches
        all_memes = []
        previously_covered: list[str] = []
        previously_used_templates: list[str] = []
        batches_needed = (num_concepts + pipe_config.concepts_per_batch - 1) // pipe_config.concepts_per_batch

        for batch_num in range(batches_needed):
            remaining = num_concepts - len(all_memes)
            batch_size = min(pipe_config.concepts_per_batch, remaining)
            if batch_size <= 0:
                break

            job.progress = f"Generating batch {batch_num + 1}/{batches_needed}..."

            memes = two_stage.generate_freely(
                topic=topic,
                context_text=context_text,
                template_catalog=template_catalog,
                num_ideas=batch_size,
                previously_covered=previously_covered if previously_covered else None,
                previously_used_templates=previously_used_templates if previously_used_templates else None,
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

    job.progress = f"Evaluating {len(all_memes)} concepts..."
    evaluated = two_stage.evaluate_for_review(all_memes, context_text_final)
    job.progress = f"Evaluation complete — {len(evaluated)} memes scored"

    # Store pipeline + evaluated memes for Stage 2
    job.result = {
        "evaluated": evaluated,
        "pipeline": pipeline,
        "topic": topic,
        "context_mode": context_mode,
        "domain": domain,
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


@bp.route("/api/start", methods=["POST"])
def api_start():
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", "").strip()
    if not topic:
        return jsonify({"error": "Topic is required"}), 400

    num_concepts = int(data.get("num_concepts", 20))
    creativity = float(data.get("creativity", 1.0))
    context_mode = data.get("context_mode", CONTEXT_MODE_AUTO)
    model = data.get("model", "grok-4-0709")

    # Clamp values
    num_concepts = max(5, min(100, num_concepts))
    creativity = max(0.3, min(1.5, creativity))

    # Validate model
    valid_models = {"grok-4-0709", "grok-4-1-fast-reasoning", "grok-3-mini"}
    if model not in valid_models:
        model = "grok-4-0709"

    # Validate context_mode
    if context_mode not in (CONTEXT_MODE_AUTO, CONTEXT_MODE_RAG, CONTEXT_MODE_WEB, CONTEXT_MODE_NONE):
        context_mode = CONTEXT_MODE_AUTO

    # Auto-detect domain if context_mode is "auto"
    domain = None
    if context_mode == CONTEXT_MODE_AUTO:
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

    job_id = jobs.submit(_run_stage1, topic, num_concepts, creativity, domain, context_mode, model)
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
            resp["evaluated"] = [
                {
                    "index": i + 1,
                    "format": e.idea.format,
                    "top_text": e.idea.top_text,
                    "bottom_text": e.idea.bottom_text,
                    "overall_score": round(e.overall_score, 1),
                    "scores": e.scores,
                    "evaluation_notes": e.evaluation_notes,
                    "is_absurdist": e.is_absurdist,
                    "template_category": getattr(e, "template_category", ""),
                }
                for i, e in enumerate(job.result["evaluated"])
            ]
            resp["topic"] = job.result.get("topic", "")
            resp["domain_criteria"] = job.result.get("domain_criteria", [])

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
    selected_indices = [int(i) for i in selected_indices if 0 < int(i) <= len(evaluated)]
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
        from src.core.grok import GrokClient

        # Check if any domains are configured
        domains = list_domains()

        grok = GrokClient()

        if domains:
            # Pick a random domain and suggest topic for it
            import random
            domain_name = random.choice(domains)
            config = load_domain(domain_name)
            response = grok._chat([
                {"role": "user", "content": (
                    f"Suggest ONE specific, funny meme topic about {config.display_name}. "
                    "Be creative and specific — pick a particular artist, quirk, "
                    "moment, or debate. Just return the topic, nothing else."
                )}
            ], temperature=1.0)
        else:
            # No domains - suggest a general trending meme topic
            response = grok._chat([
                {"role": "user", "content": (
                    "Suggest ONE specific, funny meme topic that's trending or popular right now. "
                    "It could be about tech, pop culture, sports, politics, or anything meme-worthy. "
                    "Be specific. Just return the topic, nothing else."
                )}
            ], temperature=1.0)

        grok.close()
        return jsonify({"topic": response.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
