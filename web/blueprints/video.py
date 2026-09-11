"""
Video blueprint — two-stage video ad generation workflow.
Stage 1: Generate concepts + evaluate (cheap LLM calls).
Stage 2: Produce videos for selected concepts (expensive video gen + TTS).
"""

from flask import Blueprint, render_template, request, jsonify, send_from_directory
from pathlib import Path

from web import jobs

bp = Blueprint("video", __name__)


# ---------------------------------------------------------------------------
# Stage 1 worker
# ---------------------------------------------------------------------------

def _run_video_stage1(job, topic, num_concepts, num_scenes, target_duration, creativity):
    """Background worker: generate video ad concepts + evaluate."""
    from src.core.video_pipeline import VideoAdPipeline, VideoPipelineConfig
    from src.core.video_evaluator import VIDEO_EVALUATION_CRITERIA
    from src.core.fallback_context import FallbackContextProvider

    job.progress = "Setting up video pipeline..."

    config = VideoPipelineConfig(
        num_concepts=num_concepts,
        num_scenes=num_scenes,
        target_duration=target_duration,
        creativity=creativity,
    )
    pipeline = VideoAdPipeline(config=config)

    # Get web context
    job.progress = "Searching for context..."
    try:
        fallback = FallbackContextProvider()
        context_text = fallback.get_web_context(topic, max_results=5)
    except Exception:
        context_text = ""

    # Generate concepts in batches
    all_concepts = []
    batches_needed = (num_concepts + config.concepts_per_batch - 1) // config.concepts_per_batch

    for batch_num in range(batches_needed):
        remaining = num_concepts - len(all_concepts)
        batch_size = min(config.concepts_per_batch, remaining)
        if batch_size <= 0:
            break

        job.progress = f"Generating concepts batch {batch_num + 1}/{batches_needed}..."
        concepts = pipeline.concept_generator.generate_concepts(
            topic=topic,
            context_text=context_text,
            num_concepts=batch_size,
            num_scenes=num_scenes,
            target_duration=target_duration,
            creativity=creativity,
        )
        all_concepts.extend(concepts)
        job.progress = f"Generated {len(all_concepts)}/{num_concepts} concepts..."

    # Evaluate
    job.progress = f"Evaluating {len(all_concepts)} concepts..."
    evaluated = pipeline.evaluate_concepts(all_concepts, context_text)
    job.progress = f"Evaluation complete — {len(evaluated)} concepts scored"

    # Store for stage 2
    job.result = {
        "evaluated": evaluated,
        "pipeline": pipeline,
        "topic": topic,
        "context_text": context_text,
        "criteria": [
            {
                "name": c.name,
                "display_name": c.display_name,
                "weight": c.weight,
            }
            for c in VIDEO_EVALUATION_CRITERIA
        ],
    }


# ---------------------------------------------------------------------------
# Stage 2 worker
# ---------------------------------------------------------------------------

def _run_video_stage2(job, pipeline, evaluated, selected_indices):
    """Background worker: produce videos for selected concepts."""
    from src.core.video_output import save_video_metadata

    selected = [
        evaluated[i - 1].concept
        for i in selected_indices
        if 0 < i <= len(evaluated)
    ]

    if not selected:
        job.result = {"videos": []}
        return

    job.progress = f"Producing {len(selected)} video ads..."

    videos = []
    for i, concept in enumerate(selected):
        job.progress = f"Producing video {i + 1}/{len(selected)}: {concept.title}..."
        try:
            video = pipeline._produce_single(concept)
            videos.append(video)
        except Exception as e:
            print(f"Failed to produce '{concept.title}': {e}")
            job.progress = f"Video {i + 1} failed, continuing..."

    job.progress = "Saving metadata..."
    save_video_metadata(videos)

    job.result = {
        "videos": [
            {
                "title": v.concept.title,
                "filename": Path(v.output_path).name if v.output_path else None,
                "output_path": v.output_path,
                "thumbnail": Path(v.thumbnail_path).name if v.thumbnail_path else None,
                "total_cost": round(v.total_cost, 4),
                "total_duration": round(v.total_duration, 1),
                "hook": v.concept.hook,
                "cta_text": v.concept.cta_text,
                "scenes": [
                    {
                        "scene_number": s.scene_number,
                        "visual_prompt": s.visual_prompt[:100],
                        "voiceover_text": s.voiceover_text,
                    }
                    for s in v.concept.scenes
                ],
            }
            for v in videos
        ],
        "cost_summary": pipeline.cost_tracker.summary(),
    }
    job.progress = f"Done — {len(videos)} videos produced"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route("/")
def start():
    return render_template("video/start.html")


@bp.route("/api/start", methods=["POST"])
def api_start():
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", "").strip()
    if not topic:
        return jsonify({"error": "Topic is required"}), 400

    num_concepts = int(data.get("num_concepts", 10))
    num_scenes = int(data.get("num_scenes", 2))
    target_duration = float(data.get("target_duration", 7.0))
    creativity = float(data.get("creativity", 1.0))

    # Clamp values
    num_concepts = max(3, min(50, num_concepts))
    num_scenes = max(1, min(3, num_scenes))
    target_duration = max(5.0, min(10.0, target_duration))
    creativity = max(0.3, min(1.5, creativity))

    job_id = jobs.submit(
        _run_video_stage1,
        topic, num_concepts, num_scenes, target_duration, creativity,
    )
    return jsonify({"job_id": job_id})


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
        # Stage 1: serialize evaluated concepts
        if "evaluated" in job.result:
            resp["evaluated"] = [
                {
                    "index": i + 1,
                    "title": e.concept.title,
                    "hook": e.concept.hook,
                    "cta_text": e.concept.cta_text,
                    "tone": e.concept.tone,
                    "target_audience": e.concept.target_audience,
                    "total_duration": e.concept.total_duration,
                    "overall_score": round(e.overall_score, 1),
                    "scores": e.scores,
                    "evaluation_notes": e.evaluation_notes,
                    "scenes": [
                        {
                            "scene_number": s.scene_number,
                            "duration_seconds": s.duration_seconds,
                            "visual_prompt": s.visual_prompt,
                            "voiceover_text": s.voiceover_text,
                            "text_overlay": s.text_overlay,
                        }
                        for s in e.concept.scenes
                    ],
                }
                for i, e in enumerate(job.result["evaluated"])
            ]
            resp["topic"] = job.result.get("topic", "")
            resp["criteria"] = job.result.get("criteria", [])

        # Stage 2: serialize produced videos
        if "videos" in job.result:
            resp["videos"] = job.result["videos"]
            resp["cost_summary"] = job.result.get("cost_summary", {})

    return jsonify(resp)


@bp.route("/review/<job_id>")
def review(job_id):
    job = jobs.get(job_id)
    if job is None:
        return render_template("video/review.html", job_id=job_id, expired=True)
    return render_template("video/review.html", job_id=job_id, expired=False)


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

    selected_indices = [int(i) for i in selected_indices if 0 < int(i) <= len(evaluated)]
    if not selected_indices:
        return jsonify({"error": "No valid indices selected"}), 400

    job_id = jobs.submit(_run_video_stage2, pipeline, evaluated, selected_indices)
    return jsonify({"job_id": job_id})


@bp.route("/results/<job_id>")
def results(job_id):
    job = jobs.get(job_id)
    if job is None:
        return render_template("video/results.html", job_id=job_id, expired=True)
    return render_template("video/results.html", job_id=job_id, expired=False)


@bp.route("/preview/<path:filename>")
def preview(filename):
    """Serve video files for preview."""
    video_dir = Path("output/videos/final").resolve()
    return send_from_directory(str(video_dir), filename)
