"""
Daily candidates blueprint — review and approve meme candidates.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from flask import Blueprint, render_template, request, jsonify, abort

from src.core.meme_assets import upload_meme_to_s3, get_queue_storage
from src.core.instagram_publisher import publish_to_instagram


bp = Blueprint("daily_candidates", __name__, url_prefix="/memes/gallery/daily-candidates")
logger = logging.getLogger(__name__)


def _load_candidates_file(date_str: str) -> dict:
    """Load candidates JSON for a specific date from S3 (with local fallback)."""
    queue_storage = get_queue_storage()
    return queue_storage.load(date_str)


def _save_candidates_file(date_str: str, data: dict):
    """Save candidates JSON for a specific date to S3 and local cache."""
    queue_storage = get_queue_storage()
    queue_storage.save(date_str, data)


def _list_available_dates() -> list[dict]:
    """List all available candidate dates from S3 and local, newest first."""
    queue_storage = get_queue_storage()
    return queue_storage.list_dates()


@bp.route("/")
def index():
    """Daily candidates review page."""
    # Default to today's date
    today = datetime.now().strftime("%Y-%m-%d")
    selected_date = request.args.get("date", today)
    
    # Load candidates for selected date
    data = _load_candidates_file(selected_date)
    
    # Get list of available dates
    available_dates = _list_available_dates()
    
    return render_template(
        "daily_candidates/index.html",
        selected_date=selected_date,
        data=data,
        available_dates=available_dates,
    )


@bp.route("/api/candidates/<date_str>")
def api_get_candidates(date_str: str):
    """Get candidates for a specific date."""
    data = _load_candidates_file(date_str)
    if not data:
        return jsonify({"error": "No candidates found for this date"}), 404
    
    return jsonify(data)


@bp.route("/api/candidates/<date_str>/approve/<candidate_id>", methods=["POST"])
def api_approve_candidate(date_str: str, candidate_id: str):
    """
    Approve a candidate and publish to Instagram.
    
    JSON body:
    {
        "caption": "edited caption (optional)",
        "public_image_url": "https://... (optional, will auto-upload if not provided)"
    }
    """
    data = _load_candidates_file(date_str)
    if not data:
        return jsonify({"error": "Candidates not found"}), 404
    
    # Find the candidate
    candidate = None
    for c in data.get("candidates", []):
        if c["id"] == candidate_id:
            candidate = c
            break
    
    if not candidate:
        return jsonify({"error": "Candidate not found"}), 404
    
    # Get request data
    request_data = request.get_json(silent=True) or {}
    caption = request_data.get("caption", candidate.get("caption", "")).strip()
    
    if not caption:
        return jsonify({"error": "Caption is required"}), 400
    
    # Update candidate caption if edited
    if request_data.get("caption"):
        candidate["caption"] = caption
    
    # Use public_url from candidate if available, otherwise upload from local path
    public_image_url = candidate.get("public_url") or request_data.get("public_image_url", "").strip()
    
    if not public_image_url:
        # Fall back to uploading from local path
        local_path = candidate.get("local_path")
        if not local_path or not Path(local_path).is_file():
            return jsonify({
                "error": "No public URL available and local file not found. "
                        "The image may need to be re-generated with S3 upload enabled."
            }), 404
        
        try:
            logger.info(f"Auto-uploading {local_path} to S3...")
            upload_result = upload_meme_to_s3(local_path, candidate.get("filename"))
            
            if not upload_result.success:
                return jsonify({
                    "error": f"Failed to upload to S3: {upload_result.error}"
                }), 500
            
            public_image_url = upload_result.public_url
            candidate["public_url"] = public_image_url
            candidate["s3_key"] = upload_result.s3_key
            logger.info(f"Auto-upload successful: {public_image_url}")
            
        except ValueError as e:
            return jsonify({
                "error": f"S3 not configured: {str(e)}"
            }), 400
        except Exception as e:
            logger.error(f"S3 upload failed: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({
                "error": f"S3 upload failed: {str(e)}"
            }), 500
    
    # Publish to Instagram
    try:
        result = publish_to_instagram(
            image_url=public_image_url,
            caption=caption,
        )
        
        if result.success:
            # Mark candidate as approved
            candidate["status"] = "approved"
            candidate["approved_at"] = datetime.now().isoformat(timespec="seconds")
            candidate["public_url"] = public_image_url
            candidate["instagram_post_id"] = result.post_id
            candidate["instagram_permalink"] = result.permalink
            
            # Save updated candidates
            _save_candidates_file(date_str, data)
            
            return jsonify({
                "success": True,
                "post_id": result.post_id,
                "permalink": result.permalink,
                "public_url": public_image_url,
            })
        else:
            return jsonify({
                "success": False,
                "error": result.error,
            }), 500
            
    except Exception as e:
        logger.error(f"Instagram publish failed: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": f"Instagram publish failed: {str(e)}"
        }), 500


@bp.route("/api/candidates/<date_str>/skip/<candidate_id>", methods=["POST"])
def api_skip_candidate(date_str: str, candidate_id: str):
    """Mark a candidate as skipped."""
    data = _load_candidates_file(date_str)
    if not data:
        return jsonify({"error": "Candidates not found"}), 404
    
    # Find and update candidate
    for c in data.get("candidates", []):
        if c["id"] == candidate_id:
            c["status"] = "skipped"
            c["skipped_at"] = datetime.now().isoformat(timespec="seconds")
            _save_candidates_file(date_str, data)
            return jsonify({"success": True})
    
    return jsonify({"error": "Candidate not found"}), 404


@bp.route("/api/candidates/<date_str>/update-caption/<candidate_id>", methods=["POST"])
def api_update_caption(date_str: str, candidate_id: str):
    """Update a candidate's caption."""
    data = _load_candidates_file(date_str)
    if not data:
        return jsonify({"error": "Candidates not found"}), 404
    
    request_data = request.get_json(silent=True) or {}
    caption = request_data.get("caption", "").strip()
    
    if not caption:
        return jsonify({"error": "Caption is required"}), 400
    
    # Find and update candidate
    for c in data.get("candidates", []):
        if c["id"] == candidate_id:
            c["caption"] = caption
            c["caption_updated_at"] = datetime.now().isoformat(timespec="seconds")
            _save_candidates_file(date_str, data)
            return jsonify({"success": True})
    
    return jsonify({"error": "Candidate not found"}), 404
