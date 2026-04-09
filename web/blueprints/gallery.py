"""
Gallery blueprint — browse past meme output and serve images.
"""

import os
from pathlib import Path

from flask import Blueprint, render_template, send_from_directory, send_file, request, abort

from web.image_export import resize_for_instagram

bp = Blueprint("gallery", __name__)

MEMES_DIR = Path("output/memes")


def _get_meme_files() -> list[dict]:
    """Get all .jpg files in output/memes, newest first."""
    if not MEMES_DIR.exists():
        return []

    files = sorted(MEMES_DIR.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)
    results = []
    for f in files:
        meta_path = f.with_suffix(".txt")
        metadata = {}
        if meta_path.exists():
            metadata = _parse_metadata(meta_path)
        results.append({
            "filename": f.name,
            "path": str(f),
            "metadata": metadata,
        })
    return results


def _parse_metadata(meta_path: Path) -> dict:
    """Parse a meme .txt metadata file into a dict."""
    text = meta_path.read_text(errors="replace")
    data = {}
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("MEME:"):
            data["template"] = line.split(":", 1)[1].strip()
        elif line.startswith("TOP TEXT:"):
            data["top_text"] = line.split(":", 1)[1].strip()
        elif line.startswith("BOTTOM TEXT:"):
            data["bottom_text"] = line.split(":", 1)[1].strip()
        elif line.startswith("SUGGESTED CAPTION FOR POSTING:"):
            data["caption"] = line.split(":", 1)[1].strip()
    return data


@bp.route("/")
def index():
    memes = _get_meme_files()
    return render_template("gallery/index.html", memes=memes)


@bp.route("/image/<path:filename>")
def serve_image(filename):
    if not MEMES_DIR.exists():
        abort(404)
    return send_from_directory(MEMES_DIR.resolve(), filename)


@bp.route("/download/<path:filename>")
def download(filename):
    """Download a meme image, optionally resized for Instagram."""
    filepath = MEMES_DIR / filename
    if not filepath.is_file():
        abort(404)

    fmt = request.args.get("format", "")

    if fmt == "instagram":
        buf = resize_for_instagram(str(filepath))
        stem = filepath.stem
        return send_file(
            buf,
            mimetype="image/jpeg",
            as_attachment=True,
            download_name=f"{stem}_instagram.jpg",
        )

    return send_file(
        filepath,
        as_attachment=True,
        download_name=filename,
    )
